"""GeckoTerminal — free keyless OHLCV, 30 calls/min. The TA data source.

Docs: https://apiguide.geckoterminal.com
"""
from __future__ import annotations

from core.http import request

BASE = "https://api.geckoterminal.com/api/v2"
HEADERS = {"Accept": "application/json;version=20230302"}

# (timeframe, aggregate) per label the bot understands.
TF = {"5m": ("minute", 5), "15m": ("minute", 15), "1h": ("hour", 1), "4h": ("hour", 4)}


async def ohlcv(pool: str, tf: str = "15m", limit: int = 200) -> list[list[float]]:
    """Returns oldest-first [[ts, o, h, l, c, v], ...]."""
    timeframe, aggregate = TF[tf]
    data = await request(
        "geckoterminal",
        f"{BASE}/networks/solana/pools/{pool}/ohlcv/{timeframe}",
        params={"aggregate": aggregate, "limit": limit, "currency": "usd"},
        headers=HEADERS,
        ttl=45,
    )
    rows = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    return list(reversed(rows))  # API returns newest-first


async def trending(page: int = 1) -> list[dict]:
    data = await request(
        "geckoterminal",
        f"{BASE}/networks/solana/trending_pools",
        params={"page": page, "duration": "1h"},
        headers=HEADERS,
        ttl=120,
    )
    return (data or {}).get("data") or []


async def top_pool(mint: str) -> str | None:
    """GeckoTerminal's own deepest pool for a token, used when the DexScreener
    pool address is not indexed here."""
    data = await request(
        "geckoterminal",
        f"{BASE}/networks/solana/tokens/{mint}/pools",
        params={"page": 1, "sort": "h24_volume_usd_liquidity_desc"},
        headers=HEADERS,
        ttl=600,
    )
    pools = (data or {}).get("data") or []
    if not pools:
        return None
    return (pools[0].get("attributes") or {}).get("address") or pools[0].get("id", "").split("_", 1)[-1]


async def token_stats(mint: str) -> dict | None:
    """Token-level liquidity/volume/mcap.

    Needed because DexScreener's token-pairs endpoint returns a capped slice of
    pools (30 observed), so summing it understates a mid-cap's real depth
    (BONK: $707k summed vs $1.21M actual).
    """
    data = await request(
        "geckoterminal", f"{BASE}/networks/solana/tokens/{mint}", headers=HEADERS, ttl=120
    )
    a = ((data or {}).get("data") or {}).get("attributes") or {}
    if not a:
        return None

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    return {
        "liquidity_usd": num(a.get("total_reserve_in_usd")),
        "vol24": num((a.get("volume_usd") or {}).get("h24")),
        "mcap": num(a.get("market_cap_usd")) or num(a.get("fdv_usd")),
        "price": num(a.get("price_usd")),
    }
