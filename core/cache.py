"""TTL cache: in-memory L1 (hot, per-process) + SQLite L2 (survives restarts).

Rationale: on a personal PC the scarce resource is API quota, not disk. L2 means
a bot restart does not re-burn a day of Rugcheck credits.
"""
from __future__ import annotations

import json
import os
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

CREATE TABLE IF NOT EXISTS scan_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    mint        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    tier        TEXT NOT NULL,
    price       REAL NOT NULL,
    confluence  REAL NOT NULL,
    risk        TEXT NOT NULL,
    action      TEXT NOT NULL,
    entry_price REAL,
    stop_price  REAL,
    tp1_price   REAL,
    tp2_price   REAL,
    tp3_price   REAL
);
CREATE INDEX IF NOT EXISTS idx_scan_history_mint ON scan_history(mint);
CREATE INDEX IF NOT EXISTS idx_scan_history_time ON scan_history(timestamp);
"""


async def init() -> None:
    global _DB
    db_dir = os.path.dirname(settings.cache_db)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
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


async def record_scan(entry: dict) -> None:
    """Persist scan verdict for hit rate tracking and performance analytics."""
    if _DB is None:
        return
    await _DB.execute(
        """
        INSERT INTO scan_history (
            timestamp, mint, symbol, tier, price, confluence, risk, action,
            entry_price, stop_price, tp1_price, tp2_price, tp3_price
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entry.get("timestamp", time.time()),
            entry.get("mint", ""),
            entry.get("symbol", ""),
            entry.get("tier", "unknown"),
            entry.get("price", 0.0),
            entry.get("confluence", 0.0),
            entry.get("risk", ""),
            entry.get("action", ""),
            entry.get("entry_price"),
            entry.get("stop_price"),
            entry.get("tp1_price"),
            entry.get("tp2_price"),
            entry.get("tp3_price"),
        ),
    )
    await _DB.commit()


async def get_recent_scans(limit: int = 10) -> list[dict]:
    """Retrieve recent scan records."""
    if _DB is None:
        return []
    async with _DB.execute(
        """
        SELECT timestamp, mint, symbol, tier, price, confluence, risk, action,
               entry_price, stop_price, tp1_price, tp2_price, tp3_price
        FROM scan_history
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (limit,),
    ) as cur:
        rows = await cur.fetchall()
        return [
            {
                "timestamp": r[0],
                "mint": r[1],
                "symbol": r[2],
                "tier": r[3],
                "price": r[4],
                "confluence": r[5],
                "risk": r[6],
                "action": r[7],
                "entry_price": r[8],
                "stop_price": r[9],
                "tp1_price": r[10],
                "tp2_price": r[11],
                "tp3_price": r[12],
            }
            for r in rows
        ]
