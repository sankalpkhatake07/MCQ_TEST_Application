"""Real-time fan-out for live proctoring and live ranking.

- Single process: an in-memory broker (asyncio queues).
- Several replicas behind a load balancer: set REDIS_URL and events are relayed through Redis pub/sub.
- Optional: MONGO_URL mirrors proctoring events into MongoDB for large-scale analytics (the SQL table stays the
  source of truth for scoring).
"""
import asyncio
import json
import logging
from typing import AsyncIterator, Dict, Set

from . import config

log = logging.getLogger("mcq.events")
_loop = None
_subs: Dict[str, Set[asyncio.Queue]] = {}
_redis_sync = None
_mongo = None


def bind_loop(loop):
    global _loop
    _loop = loop


def _redis_client():
    global _redis_sync
    if _redis_sync is None and config.REDIS_URL:
        import redis
        _redis_sync = redis.Redis.from_url(config.REDIS_URL)
    return _redis_sync


def _deliver_local(channel: str, payload: dict):
    for q in list(_subs.get(channel, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


def publish(channel: str, payload: dict):
    """Safe to call from sync (threadpool) route handlers."""
    try:
        r = _redis_client()
        if r is not None:
            r.publish(channel, json.dumps(payload))
            return
    except Exception as e:  # redis down: fall back to local delivery
        log.warning("redis publish failed: %s", e)
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_deliver_local, channel, payload)


async def subscribe(channel: str) -> AsyncIterator[dict]:
    if config.REDIS_URL:
        import redis.asyncio as aredis
        client = aredis.Redis.from_url(config.REDIS_URL)
        pubsub = client.pubsub()
        await pubsub.subscribe(channel)
        try:
            while True:
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                if msg is None:
                    yield {"type": "ping"}
                    continue
                yield json.loads(msg["data"])
        finally:
            await pubsub.unsubscribe(channel)
            await client.aclose()
    else:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        _subs.setdefault(channel, set()).add(q)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(q.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield {"type": "ping"}
        finally:
            _subs.get(channel, set()).discard(q)


def mirror_event(doc: dict):
    """Best-effort copy of a proctoring event to MongoDB (if configured)."""
    global _mongo
    if not config.MONGO_URL:
        return
    try:
        if _mongo is None:
            from pymongo import MongoClient
            _mongo = MongoClient(config.MONGO_URL, serverSelectionTimeoutMS=2000)[config.MONGO_DB]["proctor_events"]
        _mongo.insert_one(dict(doc))
    except Exception as e:
        log.warning("mongo mirror failed: %s", e)
