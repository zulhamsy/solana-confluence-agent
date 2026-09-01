"""DexScreener — free, keyless, 300 rpm on the pair endpoints.

Primary source for price, liquidity, volume, txn counts and pool metadata.
Docs: https://docs.dexscreener.com/api/reference
"""
from __future__ import annotations

from core.http import request

BASE = "https://api.dexscreener.com"


async def token_pairs(mint: str) -> list[dict]:
    """Solana pools where `mint` is the BASE token.

    The filter matters: a stablecoin or SOL query returns hundreds of pools in
    which it is the QUOTE side, and reading baseToken off those reports the
    wrong asset entirely.
    """
    data = await request("dexscreener", f"{BASE}/token-pairs/v1/solana/{mint}") or []
    return [p for p in data if ((p.get("baseToken") or {}).get("address") == mint)]


async def best_pair(mint: str) -> dict | None:
    """The pool that actually matters: deepest USD liquidity."""
    pairs = await token_pairs(mint)
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)


async def aggregate(mint: str) -> dict | None:
    """Token-wide totals plus the reference pool.

    A mid-cap's liquidity is spread over Raydium, Meteora, Orca and Whirlpool;
    judging depth from one pool understates it by an order of magnitude.
    """
    pairs = await token_pairs(mint)
    if not pairs:
        return None
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    total_liq = sum((p.get("liquidity") or {}).get("usd") or 0 for p in pairs)
    txns: dict[str, dict[str, int]] = {}
    for window in ("m5", "h1", "h6", "h24"):
        txns[window] = {
            "buys": sum(((p.get("txns") or {}).get(window) or {}).get("buys") or 0 for p in pairs),
            "sells": sum(((p.get("txns") or {}).get(window) or {}).get("sells") or 0 for p in pairs),
        }
    return {
        "pair": best,
        "pool_count": len(pairs),
        "liquidity_usd": total_liq,
        "volume": {w: sum((p.get("volume") or {}).get(w) or 0 for p in pairs) for w in ("m5", "h1", "h6", "h24")},
        "txns": txns,
    }


async def search(query: str) -> list[dict]:
    data = await request("dexscreener", f"{BASE}/latest/dex/search", params={"q": query})
    return (data or {}).get("pairs") or []


async def boosted_top() -> list[dict]:
    """Paid-boost leaderboard — a crude but free discovery surface for trenches."""
    return await request("dexscreener", f"{BASE}/token-boosts/top/v1") or []
