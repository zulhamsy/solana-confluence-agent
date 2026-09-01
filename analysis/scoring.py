"""Confluence engine: fold the four dimension scores into one decision.

Weights: Security 30 / On-chain 30 / Technicals 25 / Sentiment 15.
When a dimension has no data its weight is redistributed across the rest and
the result is marked degraded — a missing dimension must not silently score 0.
"""
from __future__ import annotations

from dataclasses import dataclass, field

WEIGHTS = {"security": 0.30, "onchain": 0.30, "technicals": 0.25, "sentiment": 0.15}

# Ceilings applied when a dimension has no data at all.
CAP_NO_TECHNICALS = 70.0
CAP_TWO_MISSING = 55.0

RISK_TIERS = [
    # (label, min confluence, max allowed portfolio % per position)
    ("Low", 80, 5.0),
    ("Medium", 65, 3.0),
    ("High", 50, 1.5),
    ("Degenerate", 0, 0.5),
]


@dataclass
class Verdict:
    confluence: float
    risk: str
    action: str
    size_pct: float
    rationale: list[str] = field(default_factory=list)
    degraded: list[str] = field(default_factory=list)
    parts: dict[str, float] = field(default_factory=dict)


def _risk_tier(score: float, sec_score: float, liq_usd: float, tier: str) -> tuple[str, float]:
    label, size = "Degenerate", 0.5
    for name, floor, cap in RISK_TIERS:
        if score >= floor:
            label, size = name, cap
            break
    # Structural overrides: a great chart cannot buy you a lower risk label.
    if sec_score < 70 and label in ("Low", "Medium"):
        label, size = "High", 1.5
    if tier == "trench" and label == "Low":
        label, size = "Medium", 2.0
    if liq_usd < 50_000:
        label, size = "Degenerate", min(size, 0.5)
    return label, size


def decide(
    *,
    security,
    onchain,
    technicals,
    sentiment_score: float | None = None,
) -> Verdict:
    available = {
        "security": security.score if security.data_ok else None,
        "onchain": onchain.score if onchain.data_ok else None,
        "technicals": technicals.score if technicals.data_ok else None,
        "sentiment": sentiment_score,
    }
    degraded = [k for k, v in available.items() if v is None]
    live = {k: v for k, v in available.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in live) or 1.0
    confluence = round(sum(v * WEIGHTS[k] for k, v in live.items()) / total_w, 1)

    # Redistribution must never make ignorance look like conviction. A token
    # with no chart history scored 96/100 in testing purely because the two
    # dimensions that DID return data were clean. Cap by what we actually know.
    if "technicals" in degraded:
        confluence = min(confluence, CAP_NO_TECHNICALS)
    if len(degraded) >= 2:
        confluence = min(confluence, CAP_TWO_MISSING)
    if security.score == 0.0 and not security.data_ok:
        confluence = 0.0

    # Hard fail is absolute and bypasses the weighted average entirely.
    if security.hard_fail:
        return Verdict(
            confluence=0.0,
            risk="Degenerate",
            action="AVOID",
            size_pct=0.0,
            rationale=["Security hard-fail: " + security.flags[0] if security.flags else "Security hard-fail."],
            degraded=degraded,
            parts=live,
        )

    risk, size_cap = _risk_tier(confluence, security.score, onchain.liq_usd, onchain.tier)

    if confluence >= 80 and technicals.data_ok and technicals.trend in ("uptrend", "chop"):
        action = "STRONG BUY"
    elif confluence >= 68 and onchain.tier == "trench":
        action = "SPECULATIVE ENTRY"
    elif confluence >= 68:
        action = "BUY"
    elif confluence >= 55 and (technicals.rsi or 50) > 72:
        action = "WAIT FOR DIP"
    elif confluence >= 55:
        action = "WATCHLIST"
    else:
        action = "AVOID"

    if (technicals.trend == "downtrend" or (technicals.rsi or 50) > 72) and action in ("STRONG BUY", "BUY", "SPECULATIVE ENTRY"):
        action = "WAIT FOR DIP"

    # No chart, no timed entry: the structure may be sound but there is no
    # level to enter against and no ATR to place a stop from.
    if not technicals.data_ok and action in ("STRONG BUY", "BUY", "SPECULATIVE ENTRY"):
        action = "WATCHLIST"
        rationale_prefix = ["No usable candle history — cannot define entry, stop or targets."]
    else:
        rationale_prefix = []

    size = 0.0 if action in ("AVOID", "WATCHLIST") else size_cap
    if action == "WAIT FOR DIP":
        size = round(size_cap / 2, 2)

    rationale = rationale_prefix + (security.flags + onchain.flags)[:2] + technicals.notes[:2]
    return Verdict(
        confluence=confluence,
        risk=risk,
        action=action,
        size_pct=size,
        rationale=rationale,
        degraded=degraded,
        parts=live,
    )
