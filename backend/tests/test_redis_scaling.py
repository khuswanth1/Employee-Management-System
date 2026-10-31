"""Behaviour with several backend instances sharing Redis (simulated with fakeredis; no Redis server was available)."""
import asyncio
import json
import time

import fakeredis
import fakeredis.aioredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app import realtime
from app.core import redis_client
from app.core.errors import AppError
from app.core.ratelimit import LoginLimiter
from app.realtime import ConnectionManager, RedisBridge


@pytest.fixture
def server():
    return fakeredis.FakeServer()


@pytest.fixture
def use_redis(monkeypatch, server):
    client = fakeredis.FakeRedis(server=server)
    monkeypatch.setattr(redis_client, "get_sync", lambda: client)
    return client


class Broken:
    """Stands in for an unreachable Redis."""

    def __getattr__(self, name):
        def boom(*a, **k):
            raise RedisConnectionError("down")
        return boom


# ------------------------------------------------------------- rate limiter

def test_without_redis_nothing_changes():
    assert redis_client.get_sync() is None and redis_client.get_async() is None
    lim = LoginLimiter(max_failures=2, name="plain")
    lim.fail("k"); lim.fail("k")
    with pytest.raises(AppError):
        lim.check("k")


def test_two_instances_share_one_failure_budget(use_redis):
    a, b = LoginLimiter(max_failures=3, name="shared"), LoginLimiter(max_failures=3, name="shared")  # two processes
    for _ in range(3):
        a.fail("acme|x@y.z|1.2.3.4")
    with pytest.raises(AppError) as e:
        b.check("acme|x@y.z|1.2.3.4")
    assert e.value.status_code == 429
    b.check("acme|someone-else|1.2.3.4")  # other keys are unaffected
    b.reset("acme|x@y.z|1.2.3.4")  # a successful sign-in on the other instance clears it for everyone
    a.check("acme|x@y.z|1.2.3.4")


def test_limiters_with_different_names_do_not_share_counters(use_redis):
    a, b = LoginLimiter(max_failures=1, name="one"), LoginLimiter(max_failures=1, name="two")
    a.fail("k")
    with pytest.raises(AppError):
        a.check("k")
    b.check("k")


def test_failures_expire_with_the_window(use_redis):
    lim = LoginLimiter(max_failures=1, window=1, name="win")
    lim.fail("k")
    with pytest.raises(AppError):
        lim.check("k")
    time.sleep(1.3)
    lim.check("k")


def test_no_personal_data_in_redis_keys(use_redis):
    lim = LoginLimiter(name="pii")
    lim.fail("acme|jane.doe@acme.com|203.0.113.7")
    keys = [k.decode() for k in use_redis.keys("*")]
    assert keys and all("jane" not in k and "@" not in k and "203.0" not in k for k in keys)


def test_clear_only_touches_its_own_counters(use_redis):
    a, b = LoginLimiter(name="ca"), LoginLimiter(name="cb")
    a.fail("k"); b.fail("k")
    a.clear()
    names = [k.decode() for k in use_redis.keys("*")]
    assert any(":cb:" in n for n in names) and not any(":ca:" in n for n in names)


def test_redis_outage_degrades_to_the_local_counter_instead_of_failing_open(monkeypatch):
    monkeypatch.setattr(redis_client, "get_sync", lambda: Broken())
    lim = LoginLimiter(max_failures=2, name="down")
    lim.check("k")
    lim.fail("k"); lim.fail("k")
    with pytest.raises(AppError):
        lim.check("k")
    lim.reset("k"); lim.clear()
    lim.check("k")


# ------------------------------------------------------------ cluster lock

def test_only_one_instance_holds_the_lock(use_redis):
    t1 = redis_client.acquire_lock("job", 30)
    assert t1 and redis_client.acquire_lock("job", 30) is None
    redis_client.release_lock("job", "not-the-owner")
    assert redis_client.acquire_lock("job", 30) is None  # a stranger cannot release it
    redis_client.release_lock("job", t1)
    assert redis_client.acquire_lock("job", 30)


def test_lock_expires_if_the_holder_dies(use_redis):
    assert redis_client.acquire_lock("job2", 1)
    assert redis_client.acquire_lock("job2", 1) is None
    time.sleep(1.3)
    assert redis_client.acquire_lock("job2", 1)


def test_lock_is_always_granted_without_redis_or_when_it_is_down(monkeypatch):
    assert redis_client.acquire_lock("j", 5)
    monkeypatch.setattr(redis_client, "get_sync", lambda: Broken())
    assert redis_client.acquire_lock("j", 5)
    redis_client.release_lock("j", "t")  # must not raise


# ---------------------------------------------------------------- pub/sub

class FakeWS:
    def __init__(self):
        self.got: list[dict] = []

    async def send_json(self, msg):
        self.got.append(msg)


async def _until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


def _instance(server):
    mgr = ConnectionManager()
    sync = fakeredis.FakeRedis(server=server)
    async_client = {}

    def get_async():
        return async_client.setdefault("c", fakeredis.aioredis.FakeRedis(server=server))

    return mgr, RedisBridge(mgr, lambda: sync, get_async, "test:events")


def test_event_published_on_one_instance_reaches_sockets_on_the_other(server):
    async def scenario():
        (ma, ba), (mb, bb) = _instance(server), _instance(server)
        mine_a, mine_b, other_user, other_tenant = FakeWS(), FakeWS(), FakeWS(), FakeWS()
        ma.add(1, 7, mine_a)
        mb.add(1, 7, mine_b)       # same person, second device on instance B
        mb.add(1, 8, other_user)   # a colleague who is not addressed
        mb.add(2, 7, other_tenant) # same user id in another company
        tasks = [asyncio.create_task(ba.run()), asyncio.create_task(bb.run())]
        await asyncio.wait_for(asyncio.gather(ba.ready.wait(), bb.ready.wait()), 3)
        assert await asyncio.to_thread(ba.publish, 1, [7], {"type": "notification", "data": {"title": "Hi"}})
        assert await _until(lambda: mine_a.got and mine_b.got)
        await asyncio.sleep(0.2)
        for t in tasks:
            t.cancel()
        return mine_a.got, mine_b.got, other_user.got, other_tenant.got

    a, b, other_user, other_tenant = asyncio.run(scenario())
    assert a == b == [{"type": "notification", "data": {"title": "Hi"}}]  # exactly once each
    assert other_user == [] and other_tenant == []  # neither another person nor another company


def test_malformed_events_are_skipped_and_do_not_kill_the_subscriber(server):
    async def scenario():
        m, bridge = _instance(server)
        ws = FakeWS()
        m.add(1, 7, ws)
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(bridge.ready.wait(), 3)
        raw = fakeredis.FakeRedis(server=server)
        for junk in ("not json", json.dumps({"c": 1}), json.dumps({"c": "x", "u": [1], "m": {}}), json.dumps([1, 2])):
            raw.publish("test:events", junk)
        await asyncio.to_thread(bridge.publish, 1, [7], {"type": "ok"})
        assert await _until(lambda: ws.got)
        task.cancel()
        return ws.got

    assert asyncio.run(scenario()) == [{"type": "ok"}]


def test_publish_reports_failure_so_the_caller_can_deliver_locally(server):
    mgr = ConnectionManager()
    assert RedisBridge(mgr, lambda: None, lambda: None, "c").publish(1, [1], {}) is False
    assert RedisBridge(mgr, lambda: Broken(), lambda: None, "c").publish(1, [1], {}) is False


def test_publish_threadsafe_uses_redis_when_it_can_and_local_delivery_otherwise(monkeypatch):
    local = []
    monkeypatch.setattr(realtime.anyio.from_thread, "run", lambda fn, *a: local.append(a))
    monkeypatch.setattr(realtime.bridge, "publish", lambda *a: True)
    realtime.publish_threadsafe(1, [7], {"x": 1})
    assert local == []  # left to the subscribers
    monkeypatch.setattr(realtime.bridge, "publish", lambda *a: False)
    realtime.publish_threadsafe(1, [7], {"x": 1})
    assert local == [(1, [7], {"x": 1})]
    realtime.publish_threadsafe(1, [], {"x": 1})  # nobody to tell
    assert len(local) == 1


def test_subscriber_reconnects_after_the_connection_drops(server):
    async def scenario():
        mgr = ConnectionManager()
        ws = FakeWS()
        mgr.add(1, 7, ws)
        sync = fakeredis.FakeRedis(server=server)
        calls = {"n": 0}

        def get_async():
            calls["n"] += 1
            if calls["n"] == 1:
                raise RedisConnectionError("first connect fails")
            return fakeredis.aioredis.FakeRedis(server=server)

        bridge = RedisBridge(mgr, lambda: sync, get_async, "test:events")
        task = asyncio.create_task(bridge.run())
        await asyncio.wait_for(bridge.ready.wait(), 5)  # succeeds after the 1 s backoff
        await asyncio.to_thread(bridge.publish, 1, [7], {"type": "back"})
        assert await _until(lambda: ws.got)
        task.cancel()
        return calls["n"], ws.got

    n, got = asyncio.run(scenario())
    assert n >= 2 and got == [{"type": "back"}]
