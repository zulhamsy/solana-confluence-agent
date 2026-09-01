"""GoPlus Security — independent, free, keyless token security API for Solana.

Docs: https://docs.gopluslabs.io/reference/solanatokensecurityusingget
Used as a secondary security opinion alongside Rugcheck.
"""
from __future__ import annotations

from core.http import request

BASE = "https://api.gopluslabs.io/api/v1/solana/token_security"


async def report(mint: str) -> dict | None:
    """Returns GoPlus security dictionary for mint."""
    data = await request("goplus", BASE, params={"contract_addresses": mint}, ttl=900)
    if not data or not isinstance(data, dict):
        return None
    res = data.get("result") or {}
    return res.get(mint)
