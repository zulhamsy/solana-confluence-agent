"""Orchestrates one full scan: fan out to providers, fold into a verdict."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from analysis import onchain as onchain_mod
from analysis import scoring, security, technicals
from core.http import gather
from providers import dexscreener, geckoterminal, rugcheck


@dataclass
class ScanResult:
    mint: str
    symbol: str
    name: str
    price: float
    pair_url: str
    change: dict
    security: security.SecurityRead
    onchain: onchain_mod.OnchainRead
    technicals: technicals.TechRead
    verdict: scoring.Verdict


async def scan(mint: str, *, light: bool = False) -> ScanResult | None:
    """`light=True` skips OHLCV entirely.

    Candles are the expensive input — GeckoTerminal allows 30 calls/min, so a
    12-token discovery sweep with full TA would take 90s and burn the whole
    minute's budget. Discovery shortlists on security + liquidity (which are
    cheap and cached); /scan then confirms the shortlist with full technicals.
    The scoring engine caps a no-technicals verdict at 70, so a light scan can
    never emit a buy signal on its own.
    """
    # Round 1: the pair is needed to know the pool address and the tier.
    agg, rc, tstats = await gather(
        dexscreener.aggregate(mint),
        rugcheck.report(mint),
        geckoterminal.token_stats(mint),
    )
    if not agg:
        return None
    pair = agg["pair"]

    onc = onchain_mod.analyse(agg, tstats)
    sec = security.analyse(rc, tier=onc.tier)

    # Round 2: candles, only if the token cleared the cheap structural gates.
    tech = technicals.TechRead()
    if not light and not sec.hard_fail and onc.liq_usd >= 15_000:
        # GeckoTerminal indexes pools independently; the DexScreener pool id is
        # usually but not always present, so fall back to GT's own pool list.
        pool = pair.get("pairAddress")
        base = await geckoterminal.ohlcv(pool, "15m")
        if not base:
            pool = await geckoterminal.top_pool(mint) or pool
            base = await geckoterminal.ohlcv(pool, "15m")
        m5, h1 = await gather(geckoterminal.ohlcv(pool, "5m"), geckoterminal.ohlcv(pool, "1h"))
        candles = {"5m": m5 or [], "15m": base or [], "1h": h1 or []}
        provisional = "high" if onc.tier == "trench" else "medium"
        tech = technicals.analyse(candles, risk=provisional)

    verdict = scoring.decide(security=sec, onchain=onc, technicals=tech)
    base = pair.get("baseToken") or {}
    return ScanResult(
        mint=mint,
        symbol=base.get("symbol") or "???",
        name=base.get("name") or "Unknown",
        price=float(pair.get("priceUsd") or 0),
        pair_url=pair.get("url") or "",
        change=pair.get("priceChange") or {},
        security=sec,
        onchain=onc,
        technicals=tech,
        verdict=verdict,
    )


async def scan_many(mints: list[str], concurrency: int = 4, *, light: bool = True) -> list[ScanResult]:
    """Bounded concurrency — the token buckets throttle, this bounds memory."""
    sem = asyncio.Semaphore(concurrency)

    async def one(m: str):
        async with sem:
            return await scan(m, light=light)

    results = await gather(*(one(m) for m in mints))
    return [r for r in results if r]
