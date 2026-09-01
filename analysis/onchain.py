"""Liquidity, volume dynamics and wallet flow from the DexScreener pair object."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OnchainRead:
    score: float = 0.0
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    liq_usd: float = 0.0
    pool_count: int = 0
    mcap: float = 0.0
    liq_ratio: float = 0.0
    vol24: float = 0.0
    buy_ratio_1h: float | None = None
    tier: str = "unknown"
    data_ok: bool = False


# Thresholds differ by tier because the same number means opposite things:
# $40k liquidity is a red flag on a $30M mid-cap and normal for a fresh trench.
# Calibrated against live Solana tokens, not intuition. Measured references:
#   BONK  — $707k liq over 30 pools, liq/mcap 0.3%, turnover ~0.01x
#   JUP   — $2.4M liq over 30 pools, liq/mcap 0.3%
#   fresh boosted trench — $50-90k liq over 2 pools, liq/mcap 10-14%
# An "intuitive" 3% liq/mcap floor rejected every real mid-cap on Solana.
BANDS = {
    "midcap": dict(min_liq=250_000, liq_ratio=(0.25, 12.0), vol_mcap=(0.005, 1.5), min_txns=800),
    "trench": dict(min_liq=25_000, liq_ratio=(3.0, 45.0), vol_mcap=(0.20, 15.0), min_txns=250),
}


def classify_tier(mcap: float) -> str:
    return "midcap" if mcap >= 5_000_000 else "trench"


def analyse(agg: dict | None, token_stats: dict | None = None) -> OnchainRead:
    """`agg` is providers.dexscreener.aggregate(); `token_stats` is the
    GeckoTerminal token-level view, which wins on liquidity/volume/mcap
    whenever it reports more (DexScreener caps its pool list)."""
    read = OnchainRead()
    if not agg or not agg.get("pair"):
        read.flags.append("No DEX pair data — token may be unlisted or dead.")
        return read

    read.data_ok = True
    pair = agg["pair"]
    liq = agg["liquidity_usd"]
    mcap = pair.get("marketCap") or pair.get("fdv") or 0.0
    vol = agg["volume"]
    txns = agg["txns"]
    read.pool_count = agg["pool_count"]
    if token_stats:
        liq = max(liq, token_stats["liquidity_usd"])
        mcap = token_stats["mcap"] or mcap
        vol = dict(vol, h24=max(vol.get("h24") or 0.0, token_stats["vol24"]))
    read.liq_usd, read.mcap, read.vol24 = liq, mcap, vol.get("h24") or 0.0
    read.tier = classify_tier(mcap)
    band = BANDS[read.tier]
    points = 0.0

    # 1. Liquidity depth (25 pts)
    if liq >= band["min_liq"]:
        points += 25
        read.notes.append(f"Liquidity ${liq:,.0f} across {read.pool_count} pool(s) — sufficient for {read.tier}.")
    elif liq >= band["min_liq"] * 0.5:
        points += 12
        read.flags.append(f"Thin liquidity ${liq:,.0f} — expect heavy slippage.")
    else:
        read.flags.append(f"Liquidity ${liq:,.0f} below tier floor ${band['min_liq']:,.0f}.")

    # 2. Liquidity-to-marketcap ratio (20 pts) — too low = exit trap
    read.liq_ratio = 100.0 * liq / mcap if mcap else 0.0
    lo, hi = band["liq_ratio"]
    if lo <= read.liq_ratio <= hi:
        points += 20
        read.notes.append(f"Liq/MCap {read.liq_ratio:.1f}% — healthy.")
    elif read.liq_ratio < lo:
        read.flags.append(f"Liq/MCap {read.liq_ratio:.1f}% — valuation unsupported by depth.")
    else:
        points += 12
        read.notes.append(f"Liq/MCap {read.liq_ratio:.1f}% — unusually deep vs cap.")

    # 3. Volume / MCap turnover (20 pts)
    turnover = read.vol24 / mcap if mcap else 0.0
    vlo, vhi = band["vol_mcap"]
    if vlo <= turnover <= vhi:
        points += 20
        read.notes.append(f"24h turnover {turnover:.2f}x mcap — real participation.")
    elif turnover < vlo:
        points += 5
        read.flags.append(f"24h turnover {turnover:.2f}x — attention is fading.")
    else:
        points += 8
        read.flags.append(f"24h turnover {turnover:.2f}x — likely wash/bot volume.")

    # 4. Buy/sell pressure, 1h (20 pts)
    h1 = txns.get("h1") or {}
    buys, sells = h1.get("buys") or 0, h1.get("sells") or 0
    if buys + sells >= 20:
        read.buy_ratio_1h = buys / (buys + sells)
        if read.buy_ratio_1h >= 0.58:
            points += 20
            read.notes.append(f"1h buy pressure {read.buy_ratio_1h:.0%} — bid-side control.")
        elif read.buy_ratio_1h >= 0.48:
            points += 12
        else:
            read.flags.append(f"1h buy pressure {read.buy_ratio_1h:.0%} — distribution.")
    else:
        read.flags.append("Fewer than 20 trades in the last hour — illiquid tape.")

    # 5. Trade count / age sanity (15 pts)
    if (txns.get("h24") or {}).get("buys", 0) + (txns.get("h24") or {}).get("sells", 0) >= band["min_txns"]:
        points += 15
    else:
        points += 5
        read.flags.append("Low 24h trade count for this tier.")

    read.score = round(min(points, 100.0), 1)
    return read
