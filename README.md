# Solana Telegram Analysis Agent

On-demand, locally-hosted Telegram agent that scores Solana tokens across
security, on-chain liquidity/flow, and technicals, then emits an entry, stop
and three ATR-scaled targets.

Manual by design: every verdict is produced by a slash command. The pipeline is
already async and stateless per scan, so an autonomous scheduler is an added
caller of `analysis.pipeline.scan()`, not a rewrite.

## Setup

```bash
sudo apt install python3.12-venv        # not present on this machine yet
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                    # add TELEGRAM_BOT_TOKEN + your user id
python main.py
```

## Commands

| Command | What it does |
|---|---|
| `/scan <mint>` | Full report: security, on-chain, technicals, trade plan |
| `/discover midcap` | Scores GeckoTerminal trending Solana pools (light mode) |
| `/discover trench` | Scores the DexScreener boost leaderboard (light mode) |
| `/trend` | Alias for `/discover midcap` |
| `/health` | Purges expired cache rows, confirms liveness |

## Zero-key data path

| Provider | Used for | Free-tier limit | Client budget |
|---|---|---|---|
| DexScreener | price, pools, txn counts | 300 rpm | 4 rps |
| Rugcheck | authorities, LP, holders, insiders | ~1 rps anonymous | 0.8 rps |
| GeckoTerminal | OHLCV, token-level liquidity | 30 rpm | 0.45 rps |

Every call goes through `core.http.request()`, which is cache-first
(memory + SQLite), token-bucketed per provider, and retries 429/5xx with
`Retry-After` honoured. A dead provider degrades a score; it never fails a scan.

## Calibration notes

Thresholds in `analysis/onchain.py` were fitted against live tokens, not
guessed. Measured references at build time: BONK $1.21M liquidity / 0.47% of
mcap; JUP $3.27M / 0.46%; fresh boosted trench tokens $50–90k / 10–14%. An
intuitive "liquidity must be 3% of mcap" floor rejects every real Solana
mid-cap.

Known limitations, all deliberate:

- Rugcheck's `knownAccounts` only labels `AMM` and `LOCKER`, so unlabelled team
  treasuries and CEX omnibus wallets inflate top-10 concentration on governance
  tokens (JUP reads 66%). High top-10 on a large, widely-listed token means
  "verify manually", not "rug".
- GeckoTerminal does not index brand-new pools, so very fresh trench tokens
  return no candles. The scoring engine caps a no-technicals verdict at 70 and
  downgrades any buy to `WATCHLIST`. Birdeye's free tier is the upgrade path.
- Sentiment is unwired: X API v2 removed its free tier in Feb 2026. Its 15%
  weight is redistributed and the response marks the input as degraded.

## Layout

```
config.py              settings + per-provider rate budgets
core/http.py           shared client, token buckets, retry, cache-first fetch
core/cache.py          TTL cache: in-memory L1 + SQLite L2
providers/             one module per API, no business logic
analysis/indicators.py EMA / RSI / MACD / ATR / VWAP / fractal pivots on numpy
analysis/security.py   authorities, LP, concentration, insiders -> 0-100
analysis/onchain.py    depth, liq/mcap, turnover, buy pressure -> 0-100
analysis/technicals.py trend, momentum, location, HTF veto -> 0-100 + levels
analysis/scoring.py    weighted confluence, risk tier, action, position size
analysis/pipeline.py   two-round orchestration (cheap gates before candles)
bot/handlers.py        command surface, auth allowlist
bot/templates.py       MarkdownV2 rendering
```
