"""Telegram MarkdownV2 rendering. All dynamic text passes through `esc()`."""
from __future__ import annotations

import re

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

_MDV2 = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

ACTION_ICON = {
    "STRONG BUY": "🟢",
    "BUY": "🟢",
    "SPECULATIVE ENTRY": "🟡",
    "WAIT FOR DIP": "🟠",
    "WATCHLIST": "⚪",
    "AVOID": "🔴",
}
RISK_ICON = {"Low": "🛡", "Medium": "⚖️", "High": "⚠️", "Degenerate": "☠️"}


def esc(text) -> str:
    return _MDV2.sub(r"\\\1", str(text))


def esc_url(url: str) -> str:
    r"""Inside a MarkdownV2 link target only ) and \ are special. Escaping the
    dots as well (as esc() would) silently breaks the link."""
    return url.replace("\\", "\\\\").replace(")", "\\)")


def usd(v: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= div:
            return f"${v / div:.2f}{unit}"
    return f"${v:.2f}"


def price(v: float) -> str:
    if v == 0:
        return "$0"
    if v < 0.000001:
        return f"${v:.10f}".rstrip("0")
    if v < 1:
        return f"${v:.8f}".rstrip("0")
    return f"${v:,.4f}"


def bar(score: float, width: int = 10) -> str:
    filled = round(score / 100 * width)
    return "█" * filled + "░" * (width - filled)


def render_scan(r) -> str:
    v, sec, onc, tech = r.verdict, r.security, r.onchain, r.technicals
    L = []
    L.append(f"{ACTION_ICON.get(v.action, '⚪')} *{esc(v.action)}* — ${esc(r.symbol)}")
    L.append(f"_{esc(r.name)}_ · {esc(onc.tier.upper())}")
    L.append("")
    L.append(f"*Confluence* `{bar(v.confluence)}` *{esc(f'{v.confluence:.0f}')}/100*")
    L.append(f"{RISK_ICON.get(v.risk, '')} Risk: *{esc(v.risk)}* · Suggested size: *{esc(f'{v.size_pct:g}%')}* of portfolio")
    L.append("")
    L.append("*━━ Score breakdown ━━*")
    for key, label in (("security", "Security  "), ("onchain", "On\\-chain  "), ("technicals", "Technicals"), ("sentiment", "Sentiment ")):
        val = v.parts.get(key)
        cell = f"`{bar(val, 8)}` {val:>5.1f}" if val is not None else "`░░░░░░░░`   n/a"
        L.append(f"{label} {cell}")
    L.append("")
    L.append("*━━ Market ━━*")
    L.append(f"Price {esc(price(r.price))}  ·  MCap {esc(usd(onc.mcap))}")
    L.append(f"Liq {esc(usd(onc.liq_usd))} \\({esc(f'{onc.liq_ratio:.1f}')}% of mcap\\)  ·  Vol24 {esc(usd(onc.vol24))}")
    chg = " · ".join(f"{k}: {esc(f'{r.change.get(k, 0):+.1f}')}%" for k in ("m5", "h1", "h6", "h24") if k in r.change)
    if chg:
        L.append(chg)
    if onc.buy_ratio_1h is not None:
        L.append(f"1h buy pressure: *{esc(f'{onc.buy_ratio_1h:.0%}')}*")
    L.append("")

    L.append("*━━ Security ━━*")
    for f in sec.flags[:4]:
        L.append(f"🚨 {esc(f)}")
    for w in sec.warnings[:3]:
        L.append(f"⚠️ {esc(w)}")
    for p in sec.passes[:4]:
        L.append(f"✅ {esc(p)}")
    L.append("")

    if tech.data_ok and tech.levels:
        lv = tech.levels
        L.append("*━━ Trade plan \\(15m\\) ━━*")
        L.append(f"Trend: *{esc(tech.trend)}* · RSI {esc(f'{tech.rsi:.0f}')} · ATR {esc(f'{lv.atr_pct:.1f}')}%")
        L.append(f"Entry  `{esc(price(lv.entry))}`")
        L.append(f"Stop   `{esc(price(lv.stop))}`  \\(\\-{esc(f'{lv.r_multiple:.1f}')}%\\)")
        for i, tp in enumerate(lv.tp, 1):
            rr = (tp - lv.entry) / max(lv.entry - lv.stop, 1e-12)
            L.append(f"TP{i}    `{esc(price(tp))}`  \\({esc(f'{rr:.1f}')}R\\)")
        L.append("")
        for n in tech.notes[:4]:
            L.append(f"• {esc(n)}")
    else:
        L.append("_Technicals unavailable \\(insufficient candle history\\)\\._")

    if getattr(r, "sentiment", None) and r.sentiment.data_ok:
        s_items = r.sentiment.flags + r.sentiment.notes
        if s_items:
            L.append("*━━ Attention & Sentiment ━━*")
            for item in s_items[:3]:
                icon = "🚨" if item in r.sentiment.flags else "👁️"
                L.append(f"{icon} {esc(item)}")
            L.append("")

    if v.degraded:
        L.append(f"⚙️ Degraded inputs: {esc(', '.join(v.degraded))} — weights redistributed\\.")
        L.append("")

    L.append(f"`{esc(r.mint)}`")
    L.append(f"[Chart]({esc_url(r.pair_url)}) · [Rugcheck](https://rugcheck.xyz/tokens/{r.mint})")
    L.append("")
    L.append("_Analysis only, not financial advice\\. Verify before sizing\\._")
    return "\n".join(L)


def build_scan_keyboard(r) -> InlineKeyboardMarkup:
    chart_url = r.pair_url if r.pair_url else f"https://dexscreener.com/solana/{r.mint}"
    rugcheck_url = f"https://rugcheck.xyz/tokens/{r.mint}"
    keyboard = [
        [
            InlineKeyboardButton("📈 DexScreener", url=chart_url),
            InlineKeyboardButton("🛡️ Rugcheck", url=rugcheck_url),
        ],
        [
            InlineKeyboardButton("🔄 Re-Scan", callback_data=f"rescan:{r.mint}"),
            InlineKeyboardButton("📋 Copy CA", callback_data=f"copy:{r.mint}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def render_row(r) -> str:
    v = r.verdict
    return (
        f"{ACTION_ICON.get(v.action, '⚪')} *${esc(r.symbol)}* — {esc(f'{v.confluence:.0f}')}/100 "
        f"· {esc(v.risk)} · {esc(usd(r.onchain.mcap))} mcap · liq {esc(usd(r.onchain.liq_usd))}\n"
        f"  `{esc(r.mint)}`"
    )
