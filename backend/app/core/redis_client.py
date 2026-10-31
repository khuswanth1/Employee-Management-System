"""Optional shared Redis. With `REDIS_URL` empty everything runs in-process (single instance); with it set, the rate limiter,
live-event fan-out and the background-job lock work across several backend instances.

Callers must fetch clients through `get_sync()` / `get_async()` on every use (never keep them) so tests can swap them."""
import logging
import secrets

from app.core.config import get_settings

log = logging.getLogger("worksphere.redis")
_sync = None
_async = None


def enabled() -> bool:
    return bool(get_settings().redis_url)


def get_sync():
    """Blocking client for code running in worker threads, or None when Redis is not configured."""
    global _sync
    if not enabled():
        return None
    if _sync is None:
        import redis

        _sync = redis.Redis.from_url(get_settings().redis_url, socket_timeout=2, socket_connect_timeout=2, health_check_interval=30)
    return _sync


def get_async():
    """asyncio client for the pub/sub subscriber, or None when Redis is not configured."""
    global _async
    if not enabled():
        return None
    if _async is None:
        import redis.asyncio as aredis

        _async = aredis.Redis.from_url(get_settings().redis_url, health_check_interval=30)
    return _async


def acquire_lock(name: str, ttl_seconds: int) -> str | None:
    """Try to become the single runner of `name`. Returns a token to release with, or None if someone else holds it.
    Without Redis there is only one instance, so the caller always wins; if Redis is down it also wins (better to risk a duplicate
    than to stop the job everywhere)."""
    r = get_sync()
    token = secrets.token_hex(8)
    if r is None:
        return token
    try:
        return token if r.set(f"worksphere:lock:{name}", token, nx=True, ex=ttl_seconds) else None
    except Exception:  # noqa: BLE001 - redis.RedisError, imported lazily
        log.warning("Redis unavailable; running %s without a cluster lock", name)
        return token


def release_lock(name: str, token: str) -> None:
    r = get_sync()
    if r is None:
        return
    key = f"worksphere:lock:{name}"
    try:
        # compare-and-delete (WATCH/MULTI) so a lock that expired and was taken by someone else is never released by us
        with r.pipeline() as p:
            try:
                p.watch(key)
                if p.get(key) == token.encode():
                    p.multi()
                    p.delete(key)
                    p.execute()
            finally:
                p.reset()
    except Exception:  # noqa: BLE001 - includes WatchError: someone else changed it, nothing to release
        log.warning("could not release lock %s", name)
