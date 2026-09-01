"""Security & tokenomics scoring from the Rugcheck report.

Hard fails short-circuit the whole pipeline: no technical setup redeems a
mintable token with pullable liquidity.

Field notes (verified against api.rugcheck.xyz/v1/tokens/{mint}/report):
  - there is no `totalSupply` at the root; each topHolder carries its own `pct`
  - topHolders INCLUDES AMM pool vaults, so `knownAccounts` must filter them out
    or every deep-liquidity token looks like whale-controlled
  - `score_normalised` is 0-100 where LOWER is safer
"""
from __future__ import annotations

from dataclasses import dataclass, field

# knownAccounts["<addr>"]["type"] values that are pools/locks, not real holders.
# knownAccounts only labels "AMM" and "LOCKER" today, so team treasuries and
# CEX omnibus wallets stay unlabelled and DO inflate top-10 concentration on
# governance tokens (measured: JUP reads 66%). Treat a high top-10 on a large,
# widely-listed token as "verify manually", not as an automatic rug signal.
NON_HOLDER_TYPES = {"amm", "lp", "vault", "lock", "locker", "burn", "market"}


@dataclass
class SecurityRead:
    score: float = 0.0
    hard_fail: bool = False
    flags: list[str] = field(default_factory=list)   # blocking / severe
    warnings: list[str] = field(default_factory=list)
    passes: list[str] = field(default_factory=list)
    top10_pct: float | None = None
    lp_locked_pct: float | None = None
    rc_risk: int | None = None
    data_ok: bool = False


def _real_holders(report: dict) -> list[dict]:
    """topHolders minus AMM vaults, lockers and burn addresses."""
    known = report.get("knownAccounts") or {}

    def is_pool(h: dict) -> bool:
        for addr in (h.get("address"), h.get("owner")):
            entry = known.get(addr) or {}
            if (entry.get("type") or "").lower() in NON_HOLDER_TYPES:
                return True
        return False

    return [h for h in (report.get("topHolders") or []) if not is_pool(h)]


def analyse(report: dict | None, goplus_report: dict | None = None, tier: str = "midcap") -> SecurityRead:
    read = SecurityRead()
    if not report and not goplus_report:
        read.flags.append("Security reports unavailable — treat as untrusted.")
        read.hard_fail = True
        return read

    read.data_ok = True
    token = (report or {}).get("token") or {}
    points = 100.0

    # --- Authorities: binary, non-negotiable ---
    rc_mint = bool((report or {}).get("mintAuthority") or token.get("mintAuthority"))
    gp_mint = str((goplus_report or {}).get("mintable", {}).get("status", "0")) == "1"

    if rc_mint or gp_mint:
        src = "Rugcheck & GoPlus" if (rc_mint and gp_mint) else ("GoPlus" if gp_mint else "Rugcheck")
        read.flags.append(f"MINT AUTHORITY ACTIVE ({src}) — supply can be inflated at will.")
        read.hard_fail = True
    else:
        read.passes.append("Mint authority revoked")

    rc_freeze = bool((report or {}).get("freezeAuthority") or token.get("freezeAuthority"))
    gp_freeze = str((goplus_report or {}).get("freezable", {}).get("status", "0")) == "1"

    if rc_freeze or gp_freeze:
        src = "Rugcheck & GoPlus" if (rc_freeze and gp_freeze) else ("GoPlus" if gp_freeze else "Rugcheck")
        read.flags.append(f"FREEZE AUTHORITY ACTIVE ({src}) — balance can be frozen (honeypot vector).")
        read.hard_fail = True
    else:
        read.passes.append("Freeze authority revoked")

    if (report or {}).get("rugged"):
        read.flags.append("Rugcheck marks this token as ALREADY RUGGED.")
        read.hard_fail = True

    if str((goplus_report or {}).get("non_transferable", "0")) == "1":
        read.flags.append("GoPlus: NON-TRANSFERABLE token detected (Honeypot).")
        read.hard_fail = True

    # --- Transfer fee / tax (Token-2022 extension) ---
    fee = float((((report or {}).get("transferFee") or {}).get("pct") or 0))
    if fee > 5:
        read.flags.append(f"Transfer tax {fee:.1f}% — exit cost is punitive.")
        read.hard_fail = True
    elif fee > 0:
        read.warnings.append(f"Transfer tax {fee:.1f}%")
        points -= 10
    else:
        read.passes.append("No transfer tax")

    # --- Liquidity ownership ---------------------------------------------
    # Two legitimate shapes exist and conflating them produces false rugs:
    #   (a) young token: one LP, must be BURNED or time-locked
    #   (b) mature token: hundreds of independent LPs, nothing is "locked"
    markets = (report or {}).get("markets") or []
    lp_locked = max([((m.get("lp") or {}).get("lpLockedPct") or 0.0) for m in markets], default=0.0)
    providers = (report or {}).get("totalLPProviders") or 0
    read.lp_locked_pct = lp_locked
    distributed = tier == "midcap" and providers >= 50

    if distributed:
        read.passes.append(f"LP distributed across {providers:,} providers (lock not applicable)")
    elif report:
        floor = 90.0 if tier == "midcap" else 80.0
        if lp_locked >= floor:
            read.passes.append(f"LP burned/locked {lp_locked:.0f}%")
        elif lp_locked >= 50:
            read.warnings.append(f"LP only {lp_locked:.0f}% locked with {providers} providers — partial rug risk.")
            points -= 22
        else:
            read.flags.append(f"LP {lp_locked:.0f}% locked, {providers} provider(s) — liquidity can be pulled.")
            read.hard_fail = True

    # --- Holder concentration (pool vaults excluded) ---
    if report:
        holders = _real_holders(report)
        organic = [h for h in holders if not h.get("insider")]
        if organic:
            read.top10_pct = sum(float(h.get("pct") or 0) for h in organic[:10])
            cap = 25.0 if tier == "midcap" else 35.0
            if read.top10_pct <= cap:
                read.passes.append(f"Top-10 holders {read.top10_pct:.1f}%")
            elif read.top10_pct <= cap + 15:
                read.warnings.append(f"Top-10 holders {read.top10_pct:.1f}% — concentrated.")
                points -= 18
            else:
                read.flags.append(f"Top-10 holders {read.top10_pct:.1f}% — one exit dumps the chart.")
                points -= 35

        # --- Insider / bundler clusters ---
        insider_pct = sum(float(h.get("pct") or 0) for h in holders if h.get("insider"))
        if insider_pct > 15:
            read.flags.append(f"Insider/bundled wallets hold {insider_pct:.1f}%.")
            points -= 30
        elif insider_pct > 5:
            read.warnings.append(f"Insider cluster {insider_pct:.1f}%")
            points -= 12

        if tier == "trench":
            nets = report.get("insiderNetworks") or []
            if nets:
                read.warnings.append(f"{len(nets)} insider network(s) detected in the holder graph.")
                points -= 8

        # --- Rugcheck's own normalised risk (0 = safest) as corroboration ---
        rc = report.get("score_normalised")
        if isinstance(rc, (int, float)):
            read.rc_risk = int(rc)
            if rc >= 60:
                read.flags.append(f"Rugcheck risk index {rc:.0f}/100.")
                points -= 25
            elif rc >= 30:
                read.warnings.append(f"Rugcheck risk index {rc:.0f}/100")
                points -= 10
            else:
                read.passes.append(f"Rugcheck risk index {rc:.0f}/100")

        # --- Named risks ---
        for risk in report.get("risks") or []:
            level, name = (risk.get("level") or "").lower(), risk.get("name") or "risk"
            if level == "danger":
                read.flags.append(f"Rugcheck: {name}")
                points -= 15
            elif level == "warn" and name not in " ".join(read.warnings):
                read.warnings.append(f"Rugcheck: {name}")
                points -= 5

    # Secondary corroboration note from GoPlus
    if goplus_report:
        if (goplus_report.get("trusted_token") or 0) == 1:
            read.passes.append("GoPlus verified token")
        elif not read.hard_fail:
            read.passes.append("GoPlus authority checks passed")

    read.score = 0.0 if read.hard_fail else round(max(points, 0.0), 1)
    return read
