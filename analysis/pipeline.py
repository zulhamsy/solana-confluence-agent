"""Orchestrates one full scan: fan out to providers, fold into a verdict."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from analysis import onchain as onchain_mod
from analysis import scoring, security, technicals
from core import cache
from core.http import gather
from providers import dexscreener, geckoterminal, goplus, rugcheck


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
    # Round 1: pair, rugcheck, goplus and geckoterminal concurrent calls.
    agg, rc, gp, tstats = await gather(
        dexscreener.aggregate(mint),
        rugcheck.report(mint),
        goplus.report(mint),
        geckoterminal.token_stats(mint),
    )
    if not agg:
        return None
    pair = agg["pair"]

    onc = onchain_mod.analyse(agg, tstats)
    sec = security.analyse(rc, goplus_report=gp, tier=onc.tier)

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
    price_usd = float(pair.get("priceUsd") or 0)
    symbol_str = base.get("symbol") or "???"

    result = ScanResult(
        mint=mint,
        symbol=symbol_str,
        name=base.get("name") or "Unknown",
        price=price_usd,
        pair_url=pair.get("url") or "",
        change=pair.get("priceChange") or {},
        security=sec,
        onchain=onc,
        technicals=tech,
        verdict=verdict,
    )

    if not light:
        lv = tech.levels
        await cache.record_scan({
            "timestamp": time.time(),
            "mint": mint,
            "symbol": symbol_str,
            "tier": onc.tier,
            "price": price_usd,
            "confluence": verdict.confluence,
            "risk": verdict.risk,
            "action": verdict.action,
            "entry_price": lv.entry if lv else None,
            "stop_price": lv.stop if lv else None,
            "tp1_price": lv.tp[0] if (lv and len(lv.tp) > 0) else None,
            "tp2_price": lv.tp[1] if (lv and len(lv.tp) > 1) else None,
            "tp3_price": lv.tp[2] if (lv and len(lv.tp) > 2) else None,
        })

    return result


async def scan_many(mints: list[str], concurrency: int = 4, *, light: bool = True) -> list[ScanResult]:
    """Bounded concurrency — the token buckets throttle, this bounds memory."""
    sem = asyncio.Semaphore(concurrency)

    async def one(m: str):
        async with sem:
            return await scan(m, light=light)

    results = await gather(*(one(m) for m in mints))
    return [r for r in results if r]
