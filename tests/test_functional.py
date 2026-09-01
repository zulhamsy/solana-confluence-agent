"""Comprehensive functional test suite for Solana Trade Bot core modules."""
import asyncio
import numpy as np
import time
from core import cache, http
from analysis import indicators as ind
from analysis import security, onchain, technicals, scoring, pipeline
from bot import templates as T

def test_indicators():
    print("\n--- Testing analysis/indicators.py ---")
    # 1. EMA test
    arr = np.array([10.0, 11.0, 12.0, 13.0, 14.0])
    ema_res = ind.ema(arr, 3)
    assert len(ema_res) == 5
    assert ema_res[0] == 10.0
    assert ema_res[-1] > 12.0
    print("  [✓] EMA calculation verified")

    # 2. RSI test
    flat = np.ones(50) * 100.0
    rsi_flat = ind.rsi(flat)
    assert not np.isnan(rsi_flat[-1])

    up = np.linspace(10, 50, 60)
    rsi_up = ind.rsi(up)
    assert rsi_up[-1] > 70.0
    print(f"  [✓] RSI upward trend verified: {rsi_up[-1]:.1f}")

    down = np.linspace(50, 10, 60)
    rsi_down = ind.rsi(down)
    assert rsi_down[-1] < 30.0
    print(f"  [✓] RSI downward trend verified: {rsi_down[-1]:.1f}")

    # 3. MACD test
    line, sig, hist = ind.macd(up)
    assert len(line) == len(up)
    assert len(sig) == len(up)
    assert len(hist) == len(up)
    print("  [✓] MACD line, signal, and histogram verified")

    # 4. ATR test
    high = up + 2.0
    low = up - 2.0
    close = up
    atr_val = ind.atr(high, low, close)
    assert atr_val[-1] > 0
    print(f"  [✓] ATR verified: {atr_val[-1]:.2f}")

    # 5. VWAP test
    vol = np.ones(len(up)) * 1000.0
    vwap_val = ind.vwap(high, low, close, vol)
    assert vwap_val > 0
    print(f"  [✓] VWAP verified: {vwap_val:.2f}")

    # 6. Swing levels test
    h_series = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1], dtype=float)
    l_series = h_series - 1.0
    h_pivots, l_pivots = ind.swing_levels(h_series, l_series, lookback=3)
    assert 20.0 in h_pivots
    print(f"  [✓] Swing pivots identified: Highs={h_pivots}, Lows={l_pivots}")

def test_security():
    print("\n--- Testing analysis/security.py ---")
    # Case 1: Hard fail on Mint Authority
    rep_mint = {
        "mintAuthority": "SomeAuthorityPubkey",
        "freezeAuthority": None,
        "rugged": False,
        "markets": [{"lp": {"lpLockedPct": 100.0}}],
        "topHolders": [{"pct": 5.0}],
    }
    sec_read = security.analyse(rep_mint, tier="midcap")
    assert sec_read.hard_fail is True
    assert sec_read.score == 0.0
    print("  [✓] Mint authority triggers hard-fail")

    # Case 2: Hard fail on Freeze Authority
    rep_freeze = {
        "mintAuthority": None,
        "freezeAuthority": "SomeFreezePubkey",
        "rugged": False,
        "markets": [{"lp": {"lpLockedPct": 100.0}}],
        "topHolders": [{"pct": 5.0}],
    }
    sec_read2 = security.analyse(rep_freeze, tier="midcap")
    assert sec_read2.hard_fail is True
    print("  [✓] Freeze authority triggers hard-fail")

    # Case 3: Mature token with distributed LP (>= 50 providers)
    rep_mature = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "rugged": False,
        "markets": [{"lp": {"lpLockedPct": 24.0}}],
        "totalLPProviders": 114,
        "topHolders": [{"pct": 3.0} for _ in range(10)],
        "score_normalised": 15,
    }
    sec_read3 = security.analyse(rep_mature, tier="midcap")
    assert sec_read3.hard_fail is False
    assert sec_read3.score >= 70.0
    print(f"  [✓] Mature token with 114 LP providers passes security (Score: {sec_read3.score})")

    # Case 4: Trench token with low LP lock (< 50%) -> hard fail
    rep_trench_rug = {
        "mintAuthority": None,
        "freezeAuthority": None,
        "rugged": False,
        "markets": [{"lp": {"lpLockedPct": 30.0}}],
        "totalLPProviders": 1,
        "topHolders": [{"pct": 5.0}],
    }
    sec_read4 = security.analyse(rep_trench_rug, tier="trench")
    assert sec_read4.hard_fail is True
    print("  [✓] Trench token with <50% LP lock triggers hard-fail")

def test_onchain():
    print("\n--- Testing analysis/onchain.py ---")
    agg_midcap = {
        "pair": {"marketCap": 200_000_000, "priceUsd": "0.00002", "url": "https://dexscreener.com"},
        "pool_count": 30,
        "liquidity_usd": 1_200_000,
        "volume": {"m5": 1000, "h1": 20000, "h6": 100000, "h24": 500_000},
        "txns": {
            "h1": {"buys": 60, "sells": 40},
            "h24": {"buys": 1000, "sells": 800},
        }
    }
    onc_read = onchain.analyse(agg_midcap)
    assert onc_read.tier == "midcap"
    assert onc_read.score >= 70
    assert onc_read.buy_ratio_1h == 0.6
    print(f"  [✓] Healthy mid-cap scored: {onc_read.score} (Tier: {onc_read.tier})")

    agg_trench = {
        "pair": {"marketCap": 100_000, "priceUsd": "0.001", "url": "https://dexscreener.com"},
        "pool_count": 1,
        "liquidity_usd": 5_000,
        "volume": {"h24": 10_000},
        "txns": {"h1": {"buys": 5, "sells": 5}, "h24": {"buys": 50, "sells": 50}},
    }
    onc_trench = onchain.analyse(agg_trench)
    assert onc_trench.tier == "trench"
    assert onc_trench.score < 50
    print(f"  [✓] Low liquidity trench flagged: Score {onc_trench.score}")

def test_technicals():
    print("\n--- Testing analysis/technicals.py ---")
    t = np.linspace(1, 100, 100)
    close = np.exp(t * 0.01) + np.sin(t) * 0.05
    high = close + 0.02
    low = close - 0.02
    open_p = close - 0.005
    vol = np.ones(100) * 50000.0

    candles_15m = [[i * 900, open_p[i], high[i], low[i], close[i], vol[i]] for i in range(100)]
    candles_5m = [[i * 300, open_p[i % 100], high[i % 100], low[i % 100], close[i % 100], vol[i % 100]] for i in range(100)]
    candles_1h = [[i * 3600, open_p[i % 100], high[i % 100], low[i % 100], close[i % 100], vol[i % 100]] for i in range(60)]

    tech_read = technicals.analyse({
        "5m": candles_5m,
        "15m": candles_15m,
        "1h": candles_1h,
    }, risk="medium")

    assert tech_read.data_ok is True
    assert tech_read.trend == "uptrend"
    assert tech_read.levels is not None
    assert tech_read.levels.stop < tech_read.levels.entry
    assert len(tech_read.levels.tp) == 3
    print(f"  [✓] Technical analysis computed: Trend={tech_read.trend}, Score={tech_read.score}, Stop={tech_read.levels.stop:.4f}, TP1={tech_read.levels.tp[0]:.4f}")

    # Test SL Clamping on extreme volatility
    extreme_levels = technicals.levels_from_atr(close=1.0, atr_val=0.8, supports=[0.01], risk="degenerate")
    assert extreme_levels.stop >= 0.10  # Clamped above 10% price floor
    assert extreme_levels.stop < 1.0
    print(f"  [✓] Extreme volatility stop loss clamped safely: {extreme_levels.stop:.2f}")

def test_scoring():
    print("\n--- Testing analysis/scoring.py ---")
    sec = security.SecurityRead(score=80.0, data_ok=True)
    onc = onchain.OnchainRead(score=75.0, data_ok=True, liq_usd=500_000, tier="midcap")
    tech = technicals.TechRead(score=70.0, data_ok=True, trend="uptrend", rsi=55.0)

    verdict = scoring.decide(security=sec, onchain=onc, technicals=tech)
    assert verdict.action in ("STRONG BUY", "BUY")
    assert verdict.risk in ("Low", "Medium")
    print(f"  [✓] Confluence score: {verdict.confluence}, Action: {verdict.action}, Risk: {verdict.risk}, Size: {verdict.size_pct}%")

    # Test Overbought RSI override -> WAIT FOR DIP
    tech_overbought = technicals.TechRead(score=85.0, data_ok=True, trend="uptrend", rsi=78.0)
    verdict_ob = scoring.decide(security=sec, onchain=onc, technicals=tech_overbought)
    assert verdict_ob.action == "WAIT FOR DIP"
    print(f"  [✓] RSI 78 overbought correctly downgraded BUY to {verdict_ob.action}")

    sec_fail = security.SecurityRead(score=0.0, hard_fail=True, data_ok=True, flags=["MINT ACTIVE"])
    verdict_fail = scoring.decide(security=sec_fail, onchain=onc, technicals=tech)
    assert verdict_fail.action == "AVOID"
    assert verdict_fail.confluence == 0.0
    print("  [✓] Security hard-fail override verified")

    tech_empty = technicals.TechRead(data_ok=False)
    verdict_notec = scoring.decide(security=sec, onchain=onc, technicals=tech_empty)
    assert verdict_notec.confluence <= 55.0
    assert verdict_notec.action == "WATCHLIST"
    print(f"  [✓] Missing technicals capped confluence at {verdict_notec.confluence} and action is WATCHLIST")

async def test_cache_and_templates():
    print("\n--- Testing core/cache.py & bot/templates.py ---")
    await cache.init()
    try:
        await cache.set("test_key", {"symbol": "TEST", "val": 123}, ttl=2)
        val = await cache.get("test_key")
        assert val == {"symbol": "TEST", "val": 123}
        print("  [✓] L1 & L2 cache set/get verified")

        # Test Scan History in Cache
        sample_scan = {
            "timestamp": time.time(),
            "mint": "TestMint111111111111111111111111111111111111",
            "symbol": "TEST",
            "tier": "midcap",
            "price": 1.25,
            "confluence": 78.5,
            "risk": "Medium",
            "action": "BUY",
            "entry_price": 1.25,
            "stop_price": 1.15,
            "tp1_price": 1.40,
        }
        await cache.record_scan(sample_scan)
        scans = await cache.get_recent_scans(limit=5)
        assert len(scans) >= 1
        assert scans[0]["symbol"] == "TEST"
        print(f"  [✓] SQLite scan_history persisted and retrieved ({len(scans)} records)")

        raw_text = "Testing 1.5% [gain] with *stars* and _underscores_ & (parens) - dashes!"
        escaped = T.esc(raw_text)
        assert r"\." in escaped
        assert r"\*" in escaped
        assert r"\_" in escaped
        assert r"\(" in escaped
        assert r"\-" in escaped
        print("  [✓] MarkdownV2 escaper properly escapes special chars")

        raw_url = "https://dexscreener.com/solana/abc(123)"
        esc_u = T.esc_url(raw_url)
        assert r"\)" in esc_u
        assert r"\." not in esc_u
        print("  [✓] MarkdownV2 URL escaper properly preserves dots and escapes parens")
    finally:
        await cache.close()

async def test_live_pipeline():
    print("\n--- Testing Live API Integration via analysis/pipeline.py ---")
    await http.startup()
    try:
        bonk_mint = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
        print(f"  Fetching live scan for BONK ({bonk_mint})...")
        r_bonk = await pipeline.scan(bonk_mint)
        assert r_bonk is not None
        assert "bonk" in r_bonk.symbol.lower()
        assert r_bonk.onchain.tier == "midcap"
        print(f"  [✓] BONK: Price ${r_bonk.price:.8f} | Score {r_bonk.verdict.confluence:.1f} | Action {r_bonk.verdict.action}")

        # Verify scan history was recorded
        recent = await cache.get_recent_scans(limit=1)
        assert len(recent) > 0
        assert recent[0]["mint"] == bonk_mint
        print(f"  [✓] Live scan successfully logged to SQLite history (symbol: {recent[0]['symbol']})")

        msg = T.render_scan(r_bonk)
        assert len(msg) > 100
        print("  [✓] BONK MarkdownV2 template rendered cleanly without error")

        usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
        print(f"  Fetching live scan for USDC ({usdc_mint})...")
        r_usdc = await pipeline.scan(usdc_mint)
        assert r_usdc is not None
        assert r_usdc.verdict.action == "AVOID"
        assert r_usdc.verdict.risk == "Degenerate"
        print(f"  [✓] USDC: Confluence {r_usdc.verdict.confluence} | Action {r_usdc.verdict.action} (Correctly flagged mint/freeze authority)")
    finally:
        await http.shutdown()

async def main():
    test_indicators()
    test_security()
    test_onchain()
    test_technicals()
    test_scoring()
    await test_cache_and_templates()
    await test_live_pipeline()
    print("\n==========================================")
    print("  ALL FUNCTIONAL & LIVE TESTS PASSED!     ")
    print("==========================================\n")

if __name__ == "__main__":
    asyncio.run(main())
