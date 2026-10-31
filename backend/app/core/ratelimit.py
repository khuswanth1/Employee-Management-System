import hashlib
import logging
import secrets
import threading
import time
from collections import defaultdict, deque

from app.core import redis_client
from app.core.errors import AppError

log = logging.getLogger("worksphere.ratelimit")


class LoginLimiter:
    """Sliding-window failure limiter. Counts live in Redis (sorted set per key) when `REDIS_URL` is set, so several backend
    instances share one budget; otherwise, or while Redis is unreachable, they are kept in this process."""

    def __init__(self, max_failures: int = 5, window: int = 900, name: str = "login") -> None:
        self.max, self.window, self.name = max_failures, window, name
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    # ---- redis side: keys are hashed so e-mail addresses and IPs never appear in Redis
    def _rkey(self, key: str) -> str:
        return f"worksphere:rl:{self.name}:{hashlib.sha256(key.encode()).hexdigest()[:32]}"

    def _redis(self):
        return redis_client.get_sync()

    # ---- in-process side
    def _prune(self, key: str) -> deque[float]:
        q = self._fails[key]
        cutoff = time.monotonic() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def check(self, key: str) -> None:
        try:
            from app.core.config import get_settings
            if get_settings().environment == "development":
                return
        except Exception:
            pass
        r = self._redis()
        if r is not None:
            try:
                k, now = self._rkey(key), time.time()
                pipe = r.pipeline()
                pipe.zremrangebyscore(k, 0, now - self.window)
                pipe.zcard(k)
                count = pipe.execute()[1]
                if count >= self.max:
                    raise AppError("Too many failed attempts. Try again later.", status_code=429, code="rate_limited")
                return
            except AppError:
                raise
            except Exception:  # noqa: BLE001 - Redis down: degrade to this process's own count instead of failing open
                log.warning("Redis unavailable for rate limiting; using the in-process counter")
        with self._lock:
            if len(self._prune(key)) >= self.max:
                raise AppError("Too many failed attempts. Try again later.", status_code=429, code="rate_limited")

    def fail(self, key: str) -> None:
        r = self._redis()
        if r is not None:
            try:
                k, now = self._rkey(key), time.time()
                pipe = r.pipeline()
                pipe.zadd(k, {f"{now}:{secrets.token_hex(4)}": now})
                pipe.expire(k, self.window + 1)
                pipe.execute()
                return
            except Exception:  # noqa: BLE001
                log.warning("Redis unavailable for rate limiting; using the in-process counter")
        with self._lock:
            self._prune(key).append(time.monotonic())

    def reset(self, key: str) -> None:
        r = self._redis()
        if r is not None:
            try:
                r.delete(self._rkey(key))
            except Exception:  # noqa: BLE001
                log.warning("Redis unavailable; could not reset a rate-limit counter")
        with self._lock:
            self._fails.pop(key, None)

    def clear(self) -> None:
        r = self._redis()
        if r is not None:
            try:
                for k in r.scan_iter(f"worksphere:rl:{self.name}:*"):
                    r.delete(k)
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._fails.clear()


login_limiter = LoginLimiter(name="login")

# E-mail flows: counted per request (not only failures) so they cannot be used to spam a mailbox or guess tokens.
reset_request_limiter = LoginLimiter(max_failures=5, window=3600, name="reset-request")
token_confirm_limiter = LoginLimiter(max_failures=10, window=3600, name="token-confirm")
