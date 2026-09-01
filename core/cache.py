"""TTL cache: in-memory L1 (hot, per-process) + SQLite L2 (survives restarts).

Rationale: on a personal PC the scarce resource is API quota, not disk. L2 means
a bot restart does not re-burn a day of Rugcheck credits.
"""
from __future__ import annotations

import json
import time

import aiosqlite
from cachetools import TTLCache

from config import settings

_L1: TTLCache = TTLCache(maxsize=2048, ttl=60)
_DB: aiosqlite.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
    k        TEXT PRIMARY KEY,
    v        TEXT NOT NULL,
    expires  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS kv_expires ON kv(expires);
"""


async def init() -> None:
    global _DB
    _DB = await aiosqlite.connect(settings.cache_db)
    await _DB.executescript(_SCHEMA)
    await _DB.execute("PRAGMA journal_mode=WAL")
    await _DB.commit()


async def close() -> None:
    if _DB is not None:
        await _DB.close()


async def get(key: str):
    if key in _L1:
        return _L1[key]
    if _DB is None:
        return None
    async with _DB.execute("SELECT v, expires FROM kv WHERE k = ?", (key,)) as cur:
        row = await cur.fetchone()
    if row and row[1] > time.time():
        value = json.loads(row[0])
        _L1[key] = value
        return value
    return None


async def set(key: str, value, ttl: int) -> None:
    _L1[key] = value
    if _DB is None:
        return
    await _DB.execute(
        "INSERT INTO kv (k, v, expires) VALUES (?, ?, ?) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v, expires = excluded.expires",
        (key, json.dumps(value), time.time() + ttl),
    )
    await _DB.commit()


async def vacuum() -> int:
    """Drop expired rows. Call hourly from the job queue."""
    if _DB is None:
        return 0
    cur = await _DB.execute("DELETE FROM kv WHERE expires < ?", (time.time(),))
    await _DB.commit()
    return cur.rowcount or 0
