"""Single source of truth for runtime configuration and provider budgets."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class ProviderLimit:
    """Free-tier envelope for one provider. rps is enforced client-side."""

    name: str
    rps: float
    burst: int = 1
    ttl: int = 60  # default cache lifetime in seconds


@dataclass(frozen=True)
class Settings:
    telegram_token: str = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    allowed_users: set[int] = field(default_factory=lambda: _ids(os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")))
    rugcheck_jwt: str = os.environ.get("RUGCHECK_JWT", "")
    helius_key: str = os.environ.get("HELIUS_API_KEY", "")
    birdeye_key: str = os.environ.get("BIRDEYE_API_KEY", "")
    jupiter_key: str = os.environ.get("JUPITER_API_KEY", "")
    cache_db: str = os.environ.get("CACHE_DB", "data/cache.sqlite")
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")

    # Client-side rate budgets. Keep these BELOW the published limit so a
    # burst of concurrent scans can never get the key throttled or banned.
    limits: dict[str, ProviderLimit] = field(
        default_factory=lambda: {
            "dexscreener": ProviderLimit("dexscreener", rps=4.0, burst=8, ttl=30),
            "rugcheck": ProviderLimit("rugcheck", rps=0.8, burst=2, ttl=900),
            "geckoterminal": ProviderLimit("geckoterminal", rps=0.45, burst=3, ttl=60),
            "birdeye": ProviderLimit("birdeye", rps=0.8, burst=1, ttl=120),
            "jupiter": ProviderLimit("jupiter", rps=0.8, burst=1, ttl=15),
            "helius": ProviderLimit("helius", rps=8.0, burst=10, ttl=300),
        }
    )


settings = Settings()
