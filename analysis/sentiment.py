"""Sentiment & Market Attention Proxy.

Evaluates organic attention vs artificial hype using keyless free data:
- Volume velocity (5m annualized vs 1h volume surge)
- 1h Buy/Sell transaction momentum
- DexScreener Boost presence (trench tier only, with anti-trap safeguards)
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SentimentRead:
    score: float = 0.0
    flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    boost_count: int = 0
    surge_ratio: float = 0.0
    data_ok: bool = False
    is_artificial_hype: bool = False


def analyse(agg: dict | None, boost_data: list[dict] | None = None, tier: str = "midcap") -> SentimentRead:
    read = SentimentRead()
    if not agg or not agg.get("pair"):
        return read

    read.data_ok = True
    pair = agg["pair"]
    vol = agg.get("volume") or {}
    txns = agg.get("txns") or {}
    liq_usd = agg.get("liquidity_usd") or 0.0

    # 1. Volume Velocity (5m rate vs 1h average) - Max 40 pts
    v5m = vol.get("m5") or 0.0
    vh1 = vol.get("h1") or 0.0
    expected_5m = vh1 / 12.0 if vh1 > 0 else 0.0
    surge = (v5m / expected_5m) if expected_5m > 0 else 1.0
    read.surge_ratio = surge

    points = 50.0  # Base neutral sentiment

    if surge >= 2.5:
        points += 20
        read.notes.append(f"Volume surge {surge:.1f}x vs 1h avg — rapid attention inflow.")
    elif surge >= 1.2:
        points += 10
        read.notes.append(f"Steady volume velocity ({surge:.1f}x).")
    elif surge < 0.3 and vh1 > 1000:
        points -= 15
        read.flags.append("Volume velocity dropping sharply in last 5m.")

    # 2. Transaction Flow Sentiment (1h buy dominance) - Max 30 pts
    h1_txns = txns.get("h1") or {}
    buys, sells = h1_txns.get("buys") or 0, h1_txns.get("sells") or 0
    total_tx = buys + sells
    buy_ratio = buys / total_tx if total_tx > 0 else 0.5

    if total_tx >= 10:
        if buy_ratio >= 0.65:
            points += 15
            read.notes.append(f"Strong crowd buying sentiment ({buy_ratio:.0%} buys).")
        elif buy_ratio <= 0.35:
            points -= 20
            read.flags.append(f"Heavy crowd dumping ({1 - buy_ratio:.0%} sells).")

    # 3. Boost & Hype Safeguard (Trench Tier Only)
    mint = ((pair.get("baseToken") or {}).get("address") or "").lower()
    boost_count = 0
    if boost_data and isinstance(boost_data, list):
        for b in boost_data:
            if (b.get("tokenAddress") or "").lower() == mint:
                boost_count = int(b.get("totalAmount") or b.get("amount") or 1)
                break
    read.boost_count = boost_count

    if tier == "trench":
        if boost_count > 0:
            # Check for Artificial Trap: High boost + thin liquidity or sell dominance
            if buy_ratio < 0.45 or liq_usd < 20_000:
                read.is_artificial_hype = True
                read.flags.append(f"Artificial Hype Alert: {boost_count} boosts with weak liquidity / sell pressure.")
                points -= 25
            else:
                points += 15
                read.notes.append(f"Active community boost ({boost_count} boosts registered).")
    else:
        # Mid-caps don't rely on boosts; award points based on organic healthy liquidity turnover
        mcap = pair.get("marketCap") or pair.get("fdv") or 1.0
        turnover_24h = (vol.get("h24") or 0.0) / mcap if mcap > 0 else 0.0
        if 0.02 <= turnover_24h <= 1.0:
            points += 10
            read.notes.append("Healthy institutional/organic participation rate.")

    read.score = round(max(min(points, 100.0), 0.0), 1)
    return read
