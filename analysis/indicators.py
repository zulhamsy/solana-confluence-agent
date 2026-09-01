"""Hand-rolled indicators on numpy. No pandas/pandas-ta: ~40 MB RSS saved and
no unmaintained dependency in the hot path.
"""
from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return values
    alpha = 2.0 / (period + 1.0)
    out = np.empty_like(values, dtype=float)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(close: np.ndarray, period: int = 14) -> np.ndarray:
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain, avg_loss = ema(gain, period), ema(loss, period)
    rs = np.divide(avg_gain, avg_loss, out=np.full_like(avg_gain, np.inf), where=avg_loss > 0)
    return 100.0 - (100.0 / (1.0 + rs))


def macd(close: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line, sig, line - sig


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    prev = np.roll(close, 1)
    prev[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    return ema(tr, period)


def vwap(high: np.ndarray, low: np.ndarray, close: np.ndarray, vol: np.ndarray) -> float:
    typical = (high + low + close) / 3.0
    total = vol.sum()
    return float((typical * vol).sum() / total) if total > 0 else float(close[-1])


def swing_levels(high: np.ndarray, low: np.ndarray, lookback: int = 5) -> tuple[list[float], list[float]]:
    """Fractal pivots: a bar higher/lower than `lookback` bars either side."""
    highs, lows = [], []
    for i in range(lookback, len(high) - lookback):
        window_h = high[i - lookback : i + lookback + 1]
        window_l = low[i - lookback : i + lookback + 1]
        if high[i] == window_h.max():
            highs.append(float(high[i]))
        if low[i] == window_l.min():
            lows.append(float(low[i]))
    return highs, lows
