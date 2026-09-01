"""Turn OHLCV into a trend verdict, a 0-100 technical score and ATR-based levels."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from analysis import indicators as ind


@dataclass
class Levels:
    entry: float
    stop: float
    tp: list[float]
    atr_pct: float
    r_multiple: float


@dataclass
class TechRead:
    score: float = 0.0
    trend: str = "unknown"
    notes: list[str] = field(default_factory=list)
    rsi: float | None = None
    vwap: float | None = None
    levels: Levels | None = None
    data_ok: bool = False


def _arrays(rows: list[list[float]]):
    a = np.asarray(rows, dtype=float)
    return a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]  # o h l c v


def levels_from_atr(close: float, atr_val: float, supports: list[float], risk: str) -> Levels:
    """SL below the nearest structural support, floored at 1.5x ATR.

    ATR multiple widens with risk tier: a trench token that only gets 1.5x ATR
    of room is stopped out by ordinary noise.
    """
    mult = {"low": 1.5, "medium": 2.0, "high": 2.5, "degenerate": 3.0}.get(risk, 2.0)
    atr_stop = close - mult * atr_val
    below = [s for s in supports if s < close]
    structural = max(below) * 0.985 if below else atr_stop
    stop = min(atr_stop, structural)
    risk_per_unit = max(close - stop, 1e-12)
    return Levels(
        entry=close,
        stop=stop,
        tp=[close + m * risk_per_unit for m in (1.5, 3.0, 5.0)],
        atr_pct=100.0 * atr_val / close,
        r_multiple=risk_per_unit / close * 100.0,
    )


def analyse(ohlcv_by_tf: dict[str, list[list[float]]], risk: str = "medium") -> TechRead:
    read = TechRead()
    base = ohlcv_by_tf.get("15m") or []
    if len(base) < 60:
        read.notes.append("Insufficient candle history — technicals excluded from score.")
        return read

    read.data_ok = True
    _, high, low, close, vol = _arrays(base)
    price = float(close[-1])
    points = 0.0

    # 1. Trend structure via EMA stack (35 pts)
    e9, e21, e50 = ind.ema(close, 9), ind.ema(close, 21), ind.ema(close, 50)
    if e9[-1] > e21[-1] > e50[-1]:
        read.trend, points = "uptrend", points + 35
        read.notes.append("EMA 9>21>50 — trend aligned bullish on 15m.")
    elif e9[-1] < e21[-1] < e50[-1]:
        read.trend = "downtrend"
        read.notes.append("EMA 9<21<50 — bearish stack; entries are counter-trend.")
    else:
        read.trend, points = "chop", points + 15
        read.notes.append("EMAs interleaved — ranging / no clean trend.")

    # 2. Momentum: RSI position + hidden divergence (25 pts)
    r = ind.rsi(close)
    read.rsi = float(r[-1])
    if 45 <= r[-1] <= 68:
        points += 25
        read.notes.append(f"RSI {r[-1]:.0f} — constructive, not extended.")
    elif r[-1] < 30:
        points += 18
        read.notes.append(f"RSI {r[-1]:.0f} — oversold; mean-reversion setup.")
    elif r[-1] > 78:
        read.notes.append(f"RSI {r[-1]:.0f} — overbought; wait for a retrace.")
    else:
        points += 10

    # 3. MACD histogram flipping positive (20 pts)
    _, _, hist = ind.macd(close)
    if hist[-1] > 0 and hist[-2] <= 0:
        points += 20
        read.notes.append("MACD histogram just crossed positive.")
    elif hist[-1] > 0:
        points += 14
    elif hist[-1] > hist[-2]:
        points += 7
        read.notes.append("MACD still negative but contracting.")

    # 4. Location vs VWAP (20 pts) — reclaiming VWAP is the cleanest long trigger
    vw = ind.vwap(high, low, close, vol)
    read.vwap = vw
    dev = (price - vw) / vw * 100.0
    if 0 <= dev <= 6:
        points += 20
        read.notes.append(f"Price {dev:+.1f}% vs VWAP — holding above value.")
    elif dev > 15:
        points += 4
        read.notes.append(f"Price {dev:+.1f}% extended above VWAP — poor entry location.")
    elif dev < 0:
        points += 10
        read.notes.append(f"Price {dev:+.1f}% below VWAP — needs a reclaim to confirm.")
    else:
        points += 12

    # Higher-timeframe veto: never score a 15m long above 60 into a 1h downtrend
    h1 = ohlcv_by_tf.get("1h") or []
    if len(h1) >= 55:
        _, _, _, c1, _ = _arrays(h1)
        if ind.ema(c1, 21)[-1] < ind.ema(c1, 50)[-1]:
            points = min(points, 60)
            read.notes.append("1h EMA21 < EMA50 — higher timeframe caps the technical score.")

    a = ind.atr(high, low, close)
    _, supports = ind.swing_levels(high, low)
    read.levels = levels_from_atr(price, float(a[-1]), supports, risk)
    read.score = round(min(points, 100.0), 1)
    return read
