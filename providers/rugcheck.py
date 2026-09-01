"""Rugcheck.xyz — authority/LP/holder risk. Public API ~1 rps, no key required.

Docs / swagger: https://api.rugcheck.xyz/swagger/index.html
A JWT (or FluxRPC key) raises the ceiling; anonymous is fine for manual scans.
"""
from __future__ import annotations

from config import settings
from core.http import request

BASE = "https://api.rugcheck.xyz/v1"


def _headers() -> dict:
    if settings.rugcheck_jwt:
        return {"Authorization": f"Bearer {settings.rugcheck_jwt}"}
    return {}


async def report(mint: str) -> dict | None:
    """Full report: authorities, risks[], topHolders, markets[], LP lock state."""
    return await request("rugcheck", f"{BASE}/tokens/{mint}/report", headers=_headers(), ttl=900)


async def summary(mint: str) -> dict | None:
    """Cheap variant — score + risks only. Use for discovery pre-filtering."""
    return await request("rugcheck", f"{BASE}/tokens/{mint}/report/summary", headers=_headers(), ttl=900)
