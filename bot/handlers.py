"""Telegram command surface. Handlers stay thin: parse, delegate, render."""
from __future__ import annotations

import logging
import re

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from analysis import pipeline
from bot import templates as T
from config import settings
from core import cache
from providers import dexscreener, geckoterminal

log = logging.getLogger(__name__)
MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


def _authorised(update: Update) -> bool:
    if not settings.allowed_users:
        return True  # open mode: only sane while the token is private
    return bool(update.effective_user and update.effective_user.id in settings.allowed_users)


async def guard(update: Update) -> bool:
    if _authorised(update):
        return True
    if update.message:
        await update.message.reply_text("Not authorised.")
    return False


async def start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    await update.message.reply_text(
        "Solana analysis agent.\n\n"
        "/scan <mint>       full multi-dimensional report\n"
        "/discover midcap   scan trending mid-caps\n"
        "/discover trench   scan boosted low-caps\n"
        "/trend             top movers with confluence > 60\n"
        "/history           show recent scan records\n"
        "/health            cache + provider status"
    )


async def scan(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    if not ctx.args or not MINT_RE.match(ctx.args[0]):
        await update.message.reply_text("Usage: /scan <solana_mint_address>")
        return

    mint = ctx.args[0]
    await ctx.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
    note = await update.message.reply_text(f"Scanning {mint[:6]}…{mint[-4:]}")
    try:
        result = await pipeline.scan(mint)
    except Exception:
        log.exception("scan failed for %s", mint)
        await note.edit_text("Scan failed — check logs.")
        return
    if not result:
        await note.edit_text("No tradeable Solana pair found for that mint.")
        return
    await note.edit_text(
        T.render_scan(result), parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True
    )


async def discover(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    mode = (ctx.args[0].lower() if ctx.args else "midcap")
    if mode not in ("midcap", "trench"):
        await update.message.reply_text("Usage: /discover <midcap|trench>")
        return

    note = await update.message.reply_text(f"Building {mode} candidate set…")
    mints: list[str] = []
    if mode == "midcap":
        for pool in await geckoterminal.trending():
            addr = ((pool.get("relationships") or {}).get("base_token") or {}).get("data", {}).get("id", "")
            if addr.startswith("solana_"):
                mints.append(addr.split("_", 1)[1])
    else:
        for boost in await dexscreener.boosted_top():
            if boost.get("chainId") == "solana" and boost.get("tokenAddress"):
                mints.append(boost["tokenAddress"])

    mints = list(dict.fromkeys(mints))[:12]
    if not mints:
        await note.edit_text("No candidates returned by the discovery sources.")
        return

    await note.edit_text(f"Scoring {len(mints)} candidates…")
    results = await pipeline.scan_many(mints)
    keep = [r for r in results if r.onchain.tier == mode and r.verdict.action != "AVOID"]
    keep.sort(key=lambda r: r.verdict.confluence, reverse=True)
    if not keep:
        await note.edit_text(f"Scanned {len(results)} — none cleared the {mode} filters. That is a result.")
        return
    body = "\n\n".join(T.render_row(r) for r in keep[:6])
    await note.edit_text(
        f"*{T.esc(mode.upper())} candidates* \\({T.esc(len(keep))} of {T.esc(len(results))} passed\\)\n\n{body}",
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


async def trend(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ctx.args = ["midcap"]
    await discover(update, ctx)


async def history(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
    if not await guard(update):
        return
    scans = await cache.get_recent_scans(limit=8)
    if not scans:
        await update.message.reply_text("No scan history found yet.")
        return
    lines = ["*Recent Scans History*"]
    for s in scans:
        icon = T.ACTION_ICON.get(s["action"], "⚪")
        p_str = T.price(s["price"])
        lines.append(
            f"{icon} *${T.esc(s['symbol'])}* — `{T.esc(p_str)}` "
            f"· *{T.esc(f'{s[\"confluence\"]:.0f}')}/100* \\({T.esc(s['action'])}\\)\n"
            f"  `{T.esc(s['mint'])}`"
        )
    await update.message.reply_text(
        "\n\n".join(lines),
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )


def register(app: Application) -> None:
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("scan", scan))
    app.add_handler(CommandHandler("discover", discover))
    app.add_handler(CommandHandler("trend", trend))
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("history", history))
