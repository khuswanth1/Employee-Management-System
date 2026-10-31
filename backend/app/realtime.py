"""WebSocket fan-out, keyed by (company_id, user_id).

Without `REDIS_URL` events are delivered to sockets held by this process. With it, `publish_threadsafe` publishes to a Redis
channel and every instance's subscriber delivers to its own sockets, so a user connected to instance A gets events produced
on instance B. Delivery stays best-effort (notifications are persisted separately). WebRTC signaling rooms are NOT shared:
all peers of one room must reach the same instance (see nginx.conf, `api_rooms`).
"""
import asyncio
import json
import logging
from collections import defaultdict

import anyio.from_thread
from fastapi import WebSocket

log = logging.getLogger("worksphere.realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._conns: dict[tuple[int, int], set[WebSocket]] = defaultdict(set)

    def add(self, company_id: int, user_id: int, ws: WebSocket) -> bool:
        """True when this is the person's first live connection (they just came online)."""
        first = not self._conns.get((company_id, user_id))
        self._conns[(company_id, user_id)].add(ws)
        return first

    def remove(self, company_id: int, user_id: int, ws: WebSocket) -> bool:
        """True when that was their last live connection (they just went offline)."""
        self._conns[(company_id, user_id)].discard(ws)
        if not self._conns[(company_id, user_id)]:
            self._conns.pop((company_id, user_id), None)
            return True
        return False

    def is_online(self, company_id: int, user_id: int) -> bool:
        """Per process: with several backend instances a person connected elsewhere shows offline here (a Redis presence key would fix that)."""
        return bool(self._conns.get((company_id, user_id)))

    async def publish(self, company_id: int, user_ids: list[int], message: dict) -> None:
        for uid in set(user_ids):
            for ws in list(self._conns.get((company_id, uid), ())):
                try:
                    await ws.send_json(message)
                except Exception:
                    self.remove(company_id, uid, ws)

    def online_count(self, company_id: int) -> int:
        return sum(1 for (cid, _) in self._conns if cid == company_id)


manager = ConnectionManager()


class RedisBridge:
    """Carries events between instances over one Redis pub/sub channel. Each payload names its tenant, and delivery goes
    through ConnectionManager's (company_id, user_id) keys, so tenant separation is the same as in-process."""

    def __init__(self, local: ConnectionManager, get_sync, get_async, channel: str) -> None:
        self.local, self._get_sync, self._get_async, self.channel = local, get_sync, get_async, channel
        self.ready = asyncio.Event()

    def publish(self, company_id: int, user_ids: list[int], message: dict) -> bool:
        """Blocking; call from worker threads. False if Redis could not take it (caller then delivers locally)."""
        r = self._get_sync()
        if r is None:
            return False
        try:
            r.publish(self.channel, json.dumps({"c": company_id, "u": sorted(set(user_ids)), "m": message}, default=str))
            return True
        except Exception:  # noqa: BLE001
            log.warning("Redis publish failed; delivering to local sockets only")
            return False

    async def run(self) -> None:
        """Subscriber loop: reconnects with backoff. Events published while it is down are lost (best-effort)."""
        delay = 1.0
        while True:
            pubsub = None
            try:
                client = self._get_async()
                if client is None:
                    return
                pubsub = client.pubsub()
                await pubsub.subscribe(self.channel)
                self.ready.set()
                delay = 1.0
                async for item in pubsub.listen():
                    if item.get("type") != "message":
                        continue
                    try:
                        data = json.loads(item["data"])
                        await self.local.publish(int(data["c"]), [int(u) for u in data["u"]], data["m"])
                    except (ValueError, KeyError, TypeError):
                        log.warning("ignored a malformed realtime event")
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                self.ready.clear()
                log.warning("Redis subscriber lost; retrying in %.0fs", delay)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except Exception:  # noqa: BLE001
                        pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)


def _make_bridge() -> RedisBridge:
    from app.core import redis_client
    from app.core.config import get_settings

    return RedisBridge(manager, lambda: redis_client.get_sync(), lambda: redis_client.get_async(), get_settings().redis_channel)


bridge = _make_bridge()


def publish_threadsafe(company_id: int, user_ids: list[int], message: dict) -> None:
    """Call from sync (threadpool) code. Never raises; realtime is best-effort."""
    if not user_ids:
        return
    try:
        if bridge.publish(company_id, user_ids, message):
            return  # the subscriber of every instance (this one included) delivers it
        anyio.from_thread.run(manager.publish, company_id, user_ids, message)
    except RuntimeError:
        # Not inside a request thread (e.g. a script); nothing to push to.
        pass
    except Exception:
        log.exception("realtime publish failed")


class RoomManager:
    """WebRTC signaling rooms: (company_id, room_id) -> {peer_id: (websocket, display_name)}."""

    MAX_PEERS = 8  # mesh topology; beyond this an SFU is required

    def __init__(self) -> None:
        self.rooms: dict[tuple[int, str], dict[str, tuple[WebSocket, str, int | None]]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def join(self, company_id: int, room: str, peer_id: str, ws: WebSocket, name: str, user_id: int | None = None) -> list[dict] | None:
        async with self._lock:
            peers = self.rooms[(company_id, room)]
            if len(peers) >= self.MAX_PEERS:
                return None
            existing = [{"peer_id": p, "name": n} for p, (_, n, _u) in peers.items()]
            peers[peer_id] = (ws, name, user_id)
            return existing

    async def leave(self, company_id: int, room: str, peer_id: str) -> None:
        async with self._lock:
            peers = self.rooms.get((company_id, room), {})
            peers.pop(peer_id, None)
            if not peers:
                self.rooms.pop((company_id, room), None)

    async def send(self, company_id: int, room: str, peer_id: str, message: dict) -> None:
        entry = self.rooms.get((company_id, room), {}).get(peer_id)
        if entry:
            try:
                await entry[0].send_json(message)
            except Exception:
                pass

    async def kick_user(self, company_id: int, room: str, user_id: int) -> int:
        """Disconnect every connection of this person from the room (4403). Returns how many were closed."""
        n = 0
        for pid, (ws, _name, uid) in list(self.rooms.get((company_id, room), {}).items()):
            if uid == user_id:
                try:
                    await ws.send_json({"type": "error", "reason": "removed"})
                    await ws.close(code=4403)
                except Exception:  # noqa: BLE001 - already gone
                    pass
                n += 1
        return n

    async def broadcast(self, company_id: int, room: str, message: dict, exclude: str | None = None) -> None:
        for pid in list(self.rooms.get((company_id, room), {})):
            if pid != exclude:
                await self.send(company_id, room, pid, message)


rooms = RoomManager()
