"""One shared HTTP client, one token bucket per provider, one retry policy.

Every provider module goes through `request()`. That is what makes free-tier
survival a property of the system rather than of each fetcher.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from typing import Any

import httpx

from config import settings
from core import cache

log = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None
_buckets: dict[str, "TokenBucket"] = {}


class TokenBucket:
    """Async leaky bucket. Shared by all coroutines hitting one provider."""

    def __init__(self, rps: float, burst: int) -> None:
        self.rps = rps
        self.burst = max(1, burst)
        self.tokens = float(self.burst)
        self.updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def take(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rps)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self.tokens) / self.rps)


def bucket(provider: str) -> TokenBucket:
    if provider not in _buckets:
        limit = settings.limits[provider]
        _buckets[provider] = TokenBucket(limit.rps, limit.burst)
    return _buckets[provider]


async def startup() -> None:
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(12.0, connect=5.0),
        limits=httpx.Limits(max_connections=24, max_keepalive_connections=12),
        headers={"User-Agent": "solana-trade-agent/0.1"},
        http2=True,
        follow_redirects=True,
    )
    await cache.init()


async def shutdown() -> None:
    if _client:
        await _client.aclose()
    await cache.close()


async def request(
    provider: str,
    url: str,
    *,
    method: str = "GET",
    params: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
    ttl: int | None = None,
    attempts: int = 3,
) -> Any | None:
    """Cache-first, rate-limited, retrying JSON fetch. Returns None on failure.

    Returning None instead of raising is deliberate: one dead provider must
    degrade a score, never kill a scan.
    """
    limit = settings.limits[provider]
    ttl = limit.ttl if ttl is None else ttl
    p_str = json.dumps(params, sort_keys=True) if params else ""
    b_str = json.dumps(json_body, sort_keys=True) if json_body else ""
    key = f"{provider}:{hashlib.sha1(f'{method}:{url}:{p_str}:{b_str}'.encode()).hexdigest()}"

    if method == "GET" and ttl > 0:
        hit = await cache.get(key)
        if hit is not None:
            return hit

    assert _client is not None, "call core.http.startup() first"
    for i in range(attempts):
        await bucket(provider).take()
        try:
            resp = await _client.request(method, url, params=params, json=json_body, headers=headers)
            if resp.status_code == 429:
                try:
                    wait = float(resp.headers.get("Retry-After", 2 ** i))
                except (ValueError, TypeError):
                    wait = float(2 ** i)
                log.warning("%s throttled us; backing off %.1fs", provider, wait)
                await asyncio.sleep(wait + random.uniform(0, 0.4))
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(2 ** i + random.uniform(0, 0.4))
                continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            if method == "GET" and ttl > 0:
                await cache.set(key, data, ttl)
            return data
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("%s %s failed (%s/%s): %s", provider, url, i + 1, attempts, exc)
            await asyncio.sleep(2 ** i * 0.3)
    return None


async def gather(*coros):
    """asyncio.gather that never propagates — each slot is a value or None."""
    out = await asyncio.gather(*coros, return_exceptions=True)
    clean = []
    for r in out:
        if isinstance(r, BaseException):
            log.warning("subtask failed: %r", r)
            clean.append(None)
        else:
            clean.append(r)
    return clean
