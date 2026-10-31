import asyncio
import logging
import time

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select, update

from app.common import PageParams, paginate
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.core.session import ACCESS_COOKIE, DEVICE_COOKIE
from app.db.tenant_models import Notification
from app.deps import Ctx, get_ctx, resolve_tenant_user
from app.modules.chat import live
from app.realtime import manager, publish_threadsafe

log = logging.getLogger("worksphere.ws")
router = APIRouter(tags=["notifications"])


def ser(n: Notification) -> dict:
    return {"id": n.id, "title": n.title, "body": n.body, "kind": n.kind, "link": n.link, "is_read": n.is_read, "created_at": n.created_at}


@router.get("/notifications")
def list_notifications(unread_only: bool = False, params: PageParams = Depends(), ctx: Ctx = Depends(get_ctx)):
    stmt = select(Notification).where(Notification.user_id == ctx.user.id).order_by(Notification.id.desc())
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    return paginate(ctx.db, stmt, params, ser)


@router.get("/notifications/unread-count")
def unread_count(ctx: Ctx = Depends(get_ctx)):
    return {"count": ctx.db.scalar(select(func.count(Notification.id)).where(Notification.user_id == ctx.user.id, Notification.is_read.is_(False))) or 0}


@router.post("/notifications/read-all", status_code=204)
def read_all(ctx: Ctx = Depends(get_ctx)):
    ctx.db.execute(update(Notification).where(Notification.user_id == ctx.user.id, Notification.is_read.is_(False)).values(is_read=True))
    ctx.db.commit()


@router.post("/notifications/{nid}/read", status_code=204)
def mark_read(nid: int, ctx: Ctx = Depends(get_ctx)):
    n = ctx.db.get(Notification, nid)
    if n is None or n.user_id != ctx.user.id:
        raise NotFound()
    n.is_read = True
    ctx.db.commit()


WS_RECHECK_SECONDS = 30  # how often an open socket re-proves its session (tests lower this)


async def _watch_session(websocket: WebSocket, token: str, device: str | None) -> None:
    """Close the socket (4401) as soon as its session is no longer valid: signed out, password changed or reset, account
    disabled, company suspended, or the access token expired. The browser then reconnects with its refreshed cookie."""
    while True:
        await asyncio.sleep(WS_RECHECK_SECONDS)
        try:
            _, db, _ = await run_in_threadpool(resolve_tenant_user, token, device)
            db.close()
        except Exception:
            try:
                await websocket.close(code=4401)
            except Exception:
                pass
            return


def watch_session(websocket: WebSocket) -> "asyncio.Task":
    return asyncio.create_task(_watch_session(websocket, websocket.state.ws_token, websocket.state.ws_device))


async def authenticate_ws(websocket: WebSocket):
    """First-message auth keeps tokens out of URLs/logs. Returns (company, user) or None (socket closed).
    On success the caller must start `watch_session(websocket)` and cancel it when the socket ends."""
    await websocket.accept()
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        if msg.get("type") != "auth":
            raise AppError("auth required")
        token = msg.get("token")
        if not isinstance(token, str):  # browser session: the httpOnly cookie travels with the handshake
            origin = websocket.headers.get("origin")
            if origin and origin not in get_settings().cors_origin_list:
                raise AppError("origin not allowed")
            token = websocket.cookies.get(ACCESS_COOKIE)
            if not token:
                raise AppError("auth required")
        device = websocket.cookies.get(DEVICE_COOKIE)
        company, db, user = await run_in_threadpool(resolve_tenant_user, token, device)
        db.close()
        websocket.state.ws_token, websocket.state.ws_device = token, device
        return company, user
    except Exception:
        try:
            await websocket.close(code=4401)
        except Exception:
            pass
        return None


_background: set[asyncio.Task] = set()  # keeps fire-and-forget tasks alive until they finish


async def _safely(coro) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001 - presence is best-effort; the socket is already gone
        log.debug("presence update failed", exc_info=True)


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket):
    auth = await authenticate_ws(websocket)
    if auth is None:
        return
    company, user = auth
    came_online = manager.add(company.id, user.id, websocket)
    await websocket.send_json({"type": "ready"})
    watcher = watch_session(websocket)

    async def tell_partners(online: bool) -> None:
        """Presence goes only to people the user chats with."""
        seen = await run_in_threadpool(live.stamp_last_seen, company, user.id)
        partners = await run_in_threadpool(live.partners_of, company, user.id)
        if partners:
            await run_in_threadpool(publish_threadsafe, company.id, partners, {"type": "presence", "data": {"user_id": user.id, "online": online, "last_seen_at": seen}})

    last_typing: dict[int, float] = {}
    try:
        if came_online:
            await tell_partners(True)
        while True:
            msg = await websocket.receive_json()
            kind = msg.get("type") if isinstance(msg, dict) else None
            if kind == "ping":
                await websocket.send_json({"type": "pong"})
            elif kind == "typing" and isinstance(msg.get("conversation_id"), int):
                cid, now = msg["conversation_id"], time.monotonic()
                if now - last_typing.get(cid, 0) < 1.5:  # at most one signal every 1.5 s per conversation
                    continue
                last_typing[cid] = now
                audience = await run_in_threadpool(live.typing_audience, company, user.id, cid)
                if audience:
                    await run_in_threadpool(publish_threadsafe, company.id, audience, {"type": "chat_typing", "data": {"conversation_id": cid, "user_id": user.id, "name": user.full_name}})
            elif kind == "ack" and isinstance(msg.get("conversation_id"), int) and isinstance(msg.get("message_id"), int):
                res = await run_in_threadpool(live.acknowledge, company, user.id, msg["conversation_id"], msg["message_id"])
                if res:
                    others, mark = res
                    await run_in_threadpool(publish_threadsafe, company.id, others, {"type": "chat_delivered", "data": {"conversation_id": msg["conversation_id"], "user_id": user.id, "last_delivered_id": mark}})
    except (WebSocketDisconnect, ValueError, RuntimeError):
        pass
    finally:
        watcher.cancel()
        if manager.remove(company.id, user.id, websocket):
            # its own task: the handler may be cancelled while the socket closes, and "went offline" must still be told
            task = asyncio.create_task(_safely(tell_partners(False)))
            _background.add(task)
            task.add_done_callback(_background.discard)
