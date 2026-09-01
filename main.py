"""Entrypoint. `python main.py` — long-polling, no inbound ports, no webhook."""
from __future__ import annotations

import logging

from telegram.ext import AIORateLimiter, Application

from bot import handlers
from config import settings
from core import cache, http


def build() -> Application:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set — copy .env.example to .env")

    app = (
        Application.builder()
        .token(settings.telegram_token)
        .rate_limiter(AIORateLimiter())          # respects Telegram's own limits
        .concurrent_updates(4)                   # bounded: a personal PC, not a server
        .post_init(lambda _: http.startup())
        .post_shutdown(lambda _: http.shutdown())
        .build()
    )
    handlers.register(app)
    app.job_queue.run_repeating(lambda _: cache.vacuum(), interval=3600, first=3600)
    return app


if __name__ == "__main__":
    build().run_polling(drop_pending_updates=True)
