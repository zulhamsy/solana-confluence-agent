# Solana Confluence Agent — Masterplan & System Blueprint

A locally-hosted Telegram analysis agent that scores Solana tokens across security,
on-chain flow and technicals, then returns an entry, a stop and three ATR-scaled targets.

- **Provider pricing** verified against live documentation, August 2026.
- **Thresholds** calibrated against live token data, not intuition (measurements in Section 2).
- **Status:** the runnable build exists in this directory — 14 modules, ~1,420 lines, compiling
  clean, analysis engines verified end-to-end against live DexScreener, Rugcheck and
  GeckoTerminal responses.

---

## Section 0 — Build status

### The runnable half already exists

This is not a plan waiting on an implementation. What follows documents the system in this
directory and the decisions behind it.

| | |
|---|---|
| **3** | Zero-key providers — DexScreener, Rugcheck, GeckoTerminal cover security, liquidity and OHLCV with no API key and no credit card |
| **$0** | Monthly cost to start. The free path is genuinely complete for manual, on-demand scanning. Paid tiers buy latency and trench coverage, not capability |
| **4** | Defects caught by live testing. Each would have silently produced wrong verdicts |

### What live testing changed

Writing the code against the documented schemas produced four bugs that only appeared when
real responses arrived:

1. **Quote-side mint confusion.** Querying USDC returned a pool where USDC is the *quote*
   token, so the agent reported on `PUMP` instead. Fixed by filtering to pools where the
   queried mint is the base token.
2. **No `totalSupply` field.** Rugcheck's report has no root-level supply, so holder
   concentration computed as `amount / totalSupply` silently divided by zero. Each holder
   carries its own `pct`.
3. **LP-lock rule hard-failed every mature token.** BONK reads 24% "locked" because its
   liquidity comes from 114 independent providers, not a lock contract. The rule now branches
   on LP-provider count.
4. **Missing data inflated confidence.** A fresh trench token with no candle history scored
   **96/100**, because redistributing the technicals weight left only two clean dimensions.
   Ignorance now caps the score, never raises it.

The last one is a design principle rather than a patch:
**a dimension with no data must lower the ceiling, not raise the average.**

### Known gap

The Telegram handler layer (`bot/handlers.py`, `main.py`) is written but has never been
executed — `python3.12-venv` is not installed on this machine, so `python-telegram-bot`
could not be installed. The analysis engines, provider fetchers and MarkdownV2 rendering
are all verified against live data. See Section 5.6.

---

## Section 1 — Data providers & API ecosystem map

Pricing below was read from the providers' own documentation in August 2026. Where a provider
gates pricing behind sales, that is stated rather than estimated.

### 1.1 DEX data & price feeds

| Provider | Model | Free tier | Paid | Data |
|---|---|---|---|---|
| **DexScreener** *(core)* | Free | 300 rpm on pair/token endpoints; 60 rpm on profiles, boosts, metas. No key | — | Price, liquidity per pool, 5m/1h/6h/24h volume, buy/sell counts, pool age, boost leaderboard |
| **GeckoTerminal** *(core)* | Free | 30 calls/min, keyless | Rolls into CoinGecko Pro | OHLCV (1m→1d, aggregatable), token-level total reserve & 24h volume, trending pools |
| **Jupiter** | Freemium | Lite: 1 rps, unlimited credits, no key | $25 / 25M credits · $100 / 100M · $500 / 500M | Price v3, token metadata v2, quotes, Ultra swap. Real slippage modelling |
| **Birdeye** | Freemium | Standard: 30,000 CU/mo at 1 rps | $39 / 1.5M CU · $99 / 5M · $199 / 15M (+WebSocket) · $499 / 60M | OHLCV on brand-new pools, trader PnL, token holders, top traders, WebSocket |
| **CoinGecko** | Freemium | Demo: 10,000 calls/mo | From $35/mo (100k calls, 300 rpm) | CEX-listed reference prices, global market context |

Docs: [DexScreener](https://docs.dexscreener.com/api/reference) ·
[GeckoTerminal](https://apiguide.geckoterminal.com/) ·
[Jupiter](https://developers.jup.ag/pricing) ·
[Birdeye](https://docs.birdeye.so/docs/pricing) ·
[CoinGecko](https://www.coingecko.com/en/api/pricing)

> CoinGecko's Demo rate limit is documented inconsistently (30 vs 100 calls/min across their
> pages); the monthly 10,000-call cap is the binding constraint either way.

### 1.2 Solana RPC & on-chain indexers

| Provider | Model | Free tier | Paid | Notes |
|---|---|---|---|---|
| **Helius** | Freemium | 1M credits/mo, 10 rps, no card | $49 Developer (50 rps) · $499 Business (200 rps) · $999 Professional (500 rps) | Best free RPC + DAS. Watch credit weights: standard call 1, `getProgramAccounts` 10, DAS 10, Enhanced Transactions 100 |
| **Shyft** | Freemium | Unmetered credits at 10 rps | $199 Build · $349 Grow · $649 Accelerate | Flat pricing, no credit metering. gRPC/Yellowstone on paid tiers |
| **Moralis** | Freemium | 40,000 CU/day | From $49; Pro 100M CU/mo | Average request ≈ 72 CU, so the free daily budget is ~550 calls |
| **QuickNode** | Paid | 7-day trial only — no permanent free tier | From $49; Solana RPC billed 30 credits/call | Metis (Jupiter swap) add-on draws on the same credit pool; free plan gets a shared public Jupiter endpoint |
| **Triton / Alchemy** | Paid | Trials / small free tiers | Enterprise-oriented | Relevant only once you are landing your own transactions. Skip for analysis |

Docs: [Helius plans](https://www.helius.dev/docs/billing/plans) ·
[Shyft pricing](https://shyft.to/solana-rpc-grpc-pricing) ·
[Moralis pricing](https://docs.moralis.com/get-started/pricing) ·
[QuickNode Metis](https://www.quicknode.com/docs/solana/metis-overview)

**You do not need an RPC yet.** Every metric in this blueprint comes from indexed HTTP APIs.
An RPC key becomes necessary at two moments: when you want holder snapshots the aggregators
do not expose, and when you start signing transactions. Register the Helius free key now,
leave it unused.

### 1.3 Security & contract audit APIs

| Provider | Model | Free tier | Data |
|---|---|---|---|
| **Rugcheck.xyz** *(core)* | Freemium | Public API ~1 rps, keyless; JWT or FluxRPC key raises the ceiling | Mint/freeze authority, transfer fee, per-market `lpLockedPct`, top holders with insider flags, insider networks, locker owners, launchpad, `score_normalised` risk index |
| **GoPlus Security** | Free | Open free API service | Solana token security (beta): mint/freeze, taxes, holder distribution, liquidity. Excellent independent cross-check |
| **Solodit / BlockSec** | Paid | — | Audit-report aggregation and EVM-centric exploit monitoring. Not useful for SPL meme/mid-cap flow. Skip |

Docs: [Rugcheck swagger](https://api.rugcheck.xyz/swagger/index.html) ·
[GoPlus Solana](https://docs.gopluslabs.io/reference/solanatokensecurityusingget)

Run **both** Rugcheck and GoPlus and treat disagreement as a red flag in itself. They are
both free, they index independently, and a token that looks clean to one and dirty to the
other deserves a manual look.

### 1.4 Social sentiment & mindshare

> **This category broke in 2026.** X switched the API to pay-per-use in February 2026 and
> discontinued the free tier; reads cost about **$5 per 1,000** ($0.005 each), profile
> lookups $0.010, with a hard 2M reads/month ceiling below Enterprise. The legacy $200/mo
> Basic tier was retired and its subscribers force-migrated after 1 June 2026. There is no
> longer a free way to compute your own X sentiment at useful volume.

| Provider | Model | Cost | Notes |
|---|---|---|---|
| **X / Twitter API v2** | Paid | $0.005/read · $0.015/post · Enterprise from ~$42k/mo | Only worth it if you build your own bot-detection. At 2,000 reads per token scan, that is $10 per token |
| **LunarCrush** | Freemium | Not publicly retrievable — the pricing page renders client-side | v4 REST API: social volume, engagement, AltRank, sentiment, per-coin time series. Historically the cheapest real option — [verify directly](https://lunarcrush.com/developers/pricing) |
| **Kaito AI** | Paid | Enterprise, sales-gated | Best-in-class mindshare and smart-follower weighting. No self-serve tier — [api](https://pro.kaito.ai/kaito-api) |
| **Cookie DAO / cookie.fun** | Freemium | Web dashboard free; DataSwarm API partner-gated | Mindshare leaderboards, smart-follower counts, narrative trends. Powers GeckoTerminal's social tab |

**Recommendation: leave sentiment unwired at launch.** The scoring engine already treats it
as a degradable input — its 15% is redistributed and the response says so explicitly. A free
proxy that is better than nothing: DexScreener's boost leaderboard plus Telegram member
growth, both of which you can poll for free. Buying X reads to compute a sentiment score you
cannot validate is the worst available trade.

### 1.5 Smart money & wallet analytics

| Provider | Model | Free tier | Paid | Notes |
|---|---|---|---|---|
| **Vybe Network** | Freemium | 12,000 credits/mo at 4 rpm, all endpoints (social sign-in required) | $49 dev · $600 business · $1,100 premium | Best free smart-money option: token holder time series, wallet PnL, program activity. 4 rpm is tight but fine for manual scans |
| **Cielo Finance** | Freemium | Free web app, track 250 wallets | $59 Pro · $199 Whale (API access) | Wallet discovery ranked by realized PnL and win rate; bot-filtered feeds. The $199 tier is the cheapest real smart-money API |
| **Nansen** | Paid | Limited free tier | $99 Standard · $1,899 VIP (API) — or pay-per-use $0.01/call basic, $0.05 advanced, settled in USDC | The new pay-per-use model is the interesting one: label-grade Smart Money without a subscription |
| **Solscan Pro** | Paid | Basic public endpoints only | Sales-gated; V2 endpoints flat 100 CU each. Tiers commonly cited around $199/$499/$999 — **treat as unverified** | Good transaction-level detail; poor value versus Vybe at the low end |
| **Hellomoon** | — | — | — | Effectively deprecated for this use case. Vybe is the successor in practice |

Docs: [Vybe pricing](https://docs.vybenetwork.com/docs/pricing) ·
[Cielo API](https://api-info.cielo.finance/) · [Nansen API](https://nansen.ai/api)

### 1.6 The recommended path

**Stage 0 — $0/mo (now)**
DexScreener + Rugcheck + GeckoTerminal. Keyless, complete for mid-caps, already implemented.
Add GoPlus as a second security opinion and register the Helius free key for later.

**Stage 1 — $39–88/mo**
`+ Birdeye Lite ($39)` for OHLCV on pools GeckoTerminal has not indexed yet — the single
biggest gap for trench tokens. `+ Vybe $49` when 4 rpm starts blocking you.

**Stage 2 — ~$300/mo**
`+ Cielo Whale ($199)` for real smart-money inflows, `+ Birdeye Premium ($199)` for WebSocket
streaming. Only worth it once you are automating execution.

> **The one upgrade that matters.** Everything except **fresh-pool OHLCV** is adequately
> covered for free. GeckoTerminal does not index brand-new pools, which is exactly where
> trench tokens live — verified in testing: two boosted tokens returned zero candles from
> every timeframe. If you trade trenches seriously, Birdeye Lite at $39 is the first dollar
> to spend.

---

## Section 2 — The multi-dimensional evaluation matrix

Thresholds are tier-dependent because the same figure carries opposite meaning at different
scales: $40,000 of liquidity is an alarm on a $30M mid-cap and unremarkable on a fresh launch.
The agent classifies tier first — **mid-cap at ≥$5M market cap, trench below** — then applies
the matching band.

> **These numbers were fitted, not guessed.** The first draft used intuitive thresholds and
> rejected every legitimate Solana mid-cap. Measured at build time:
> **BONK** — $1.21M liquidity across 30+ pools, liquidity/mcap **0.47%**, 24h turnover 0.0012×.
> **JUP** — $3.27M liquidity, **0.46%**, turnover 0.004×.
> Fresh boosted trench tokens — $50–90k liquidity across 2 pools, **10–14%**.
> A "liquidity must be 3% of market cap" rule sounds prudent and eliminates the entire
> mid-cap universe.

### 2.1 Security & tokenomics fundamentals

| Parameter | Source | Mid-cap | Trench | Failure mode |
|---|---|---|---|---|
| Mint authority | Rugcheck | Must be `null` | Must be `null` | **hard fail** — supply inflation |
| Freeze authority | Rugcheck | Must be `null` | Must be `null` | **hard fail** — honeypot |
| Transfer fee (Token-2022) | Rugcheck | 0% | ≤5% | **hard fail** above 5% |
| Already-rugged flag | Rugcheck | false | false | **hard fail** |
| LP burned / locked | Rugcheck `markets[].lp` | ≥90% **or** ≥50 independent LP providers | ≥80% | **hard fail** below 50% |
| Top-10 holders (pools excluded) | Rugcheck `topHolders[].pct` | ≤25% ideal · ≤40% tolerated | ≤35% ideal · ≤50% tolerated | −18 to −35 pts |
| Insider / bundler cluster | Rugcheck insider flags + `insiderNetworks` | <5% | <15% | −12 to −30 pts |
| Rugcheck risk index | `score_normalised` (0 = safest) | <30 | <30 | −10 at 30 · −25 at 60 |
| Mutable metadata | Rugcheck risks | warn only | warn only | −5 pts |

**The mature-token LP trap.** A young token's liquidity sits in one pool and *must* be burned
or time-locked. A mature token's liquidity is supplied by hundreds of independent LPs and
nothing is "locked" — BONK reads 24% locked across 114 providers. Applying one rule to both
marks every established token a rug. The check branches on provider count for exactly this
reason.

**Known false positive, left visible on purpose.** Rugcheck's `knownAccounts` map labels only
`AMM` and `LOCKER` types. Team treasuries, staking programs and CEX omnibus wallets stay
unlabelled and therefore count as concentration — **JUP measures 66% top-10** this way. The
agent surfaces the number rather than suppressing it; on a large, widely-listed token read it
as "verify manually", not "rug".

### 2.2 On-chain metrics & smart money flow

| Parameter | Mid-cap band | Trench band | Weight |
|---|---|---|---|
| Total liquidity (all pools) | ≥$250,000 | ≥$25,000 | 25 pts |
| Liquidity / market cap | 0.25% – 12% | 3% – 45% | 20 pts |
| 24h volume / market cap | 0.005× – 1.5× | 0.20× – 15× | 20 pts |
| 1h buy pressure (buys ÷ total) | ≥58% strong · ≥48% neutral | ≥58% strong · ≥48% neutral | 20 pts |
| 24h trade count | ≥800 | ≥250 | 15 pts |
| Minimum tape activity | ≥20 trades in the last hour, or the tape is too thin to read | | gate |

Both ends of every band matter. Turnover *above* the ceiling is not enthusiasm, it is wash
trading — a token doing 20× its market cap in a day on a $400k cap is bots trading with
themselves. Liquidity far *above* the ratio ceiling usually means the market cap figure is
wrong.

**Data-source correction.** DexScreener's token-pairs endpoint returns a capped slice of
pools — 30 observed — so summing it understates a mid-cap's depth. BONK sums to $707k from
DexScreener versus $1.21M from GeckoTerminal's token-level `total_reserve_in_usd`. The agent
takes the larger of the two for liquidity, volume and market cap.

**Wallet growth & smart money (stage 1).** Not in the free build, and honestly labelled as
such. Unique-buyer growth and 24–48h holder retention need Vybe's holder time series (free
tier: 12k credits/mo at 4 rpm); smart-money inflows need Cielo Whale or Nansen pay-per-use.
Both slot in as additional dimensions with the same degradable-input contract — the score
ceiling drops until they report.

### 2.3 Social sentiment & mindshare (deferred)

Specified for completeness, unwired by choice — see Section 1.4. When the budget exists:
social volume velocity (24h vs 7d baseline), engagement-per-follower as a bot heuristic,
follower-quality weighting, Telegram member growth rate, and a mindshare percentile from
Kaito or Cookie. Until then its 15% is redistributed and every response carries a
`degraded inputs` line.

### 2.4 Technical analysis & price action

| Component | Rule | Points |
|---|---|---|
| Trend structure | EMA 9 > 21 > 50 on 15m → aligned bullish · interleaved → chop · inverted → downtrend | 35 / 15 / 0 |
| Momentum | RSI 45–68 constructive · <30 oversold reversion · >78 overbought, wait | 25 / 18 / 0 |
| MACD | Histogram crossing positive this bar · already positive · negative but contracting | 20 / 14 / 7 |
| Location | 0 to +6% vs session VWAP · below VWAP (needs reclaim) · >+15% extended | 20 / 10 / 4 |
| Higher-timeframe veto | 1h EMA21 < EMA50 caps the technical score at 60 regardless of the 15m picture | cap |
| Minimum history | <60 candles on 15m → technicals excluded entirely, **not** scored as zero | gate |

Timeframes are read as a hierarchy, not a set: 5m for entry timing, 15m as the scoring base,
1h as veto. That ordering is what stops the agent from calling a long into a higher-timeframe
breakdown — the single most expensive mistake a momentum bot makes.

**Dynamic stops and targets.** The stop is the *lower* of two candidates, so both volatility
and structure have to be respected:

```python
# analysis/technicals.py
mult   = {"low": 1.5, "medium": 2.0, "high": 2.5, "degenerate": 3.0}[risk]
atr_stop   = close - mult * ATR(14)
structural = max(support for support in swing_lows if support < close) * 0.985
stop       = min(atr_stop, structural)

risk_per_unit = close - stop
TP1, TP2, TP3 = close + 1.5R, close + 3.0R, close + 5.0R
```

The ATR multiple widens with the risk tier because a trench token given only 1.5× ATR of room
is stopped out by ordinary noise before the thesis has a chance to be wrong. Targets are
expressed in R-multiples rather than percentages, so the reward is always stated relative to
what you are actually risking. Verified live on BONK: ATR 1.3%, stop −2.7%, TP1 at 1.5R.

---

## Section 3 — Scoring engine & decision algorithm

```
Security 30% │ On-chain 30% │ Technicals 25% │ Sentiment 15% (currently degraded)
```

### 3.1 Confluence aggregation, and the three rules that override it

The base case is a weighted mean over the dimensions that returned data, renormalised by
their weights. Three overrides sit on top, and they exist because the naive mean produced
dangerous output in testing.

```python
# analysis/scoring.py
live       = {dim: score for dim, score in available.items() if score is not None}
confluence = sum(s * WEIGHTS[d] for d, s in live.items()) / sum(WEIGHTS[d] for d in live)

# Override 1 — ignorance lowers the ceiling, never raises the average.
# Measured: a no-history trench token scored 96/100 before this existed.
if "technicals" in degraded:  confluence = min(confluence, 70)
if len(degraded) >= 2:        confluence = min(confluence, 55)

# Override 2 — a security hard-fail bypasses arithmetic entirely.
if security.hard_fail:
    return Verdict(confluence=0, risk="Degenerate", action="AVOID", size_pct=0)

# Override 3 — no chart, no trade. There is no level to enter against.
if not technicals.data_ok and action in ("STRONG BUY", "BUY", "SPECULATIVE ENTRY"):
    action = "WATCHLIST"
```

### 3.2 Risk classification system

| Tier | Confluence | Max position | Structural override |
|---|---|---|---|
| **Low** | ≥80 | 5.0% | Unavailable to trench tokens — capped at Medium regardless of score |
| **Medium** | ≥65 | 3.0% | Downgraded to High if security < 70 |
| **High** | ≥50 | 1.5% | — |
| **Degenerate** | <50 | 0.5% | Forced for any token with <$50k liquidity, whatever else it scores |

The overrides encode a conviction worth stating plainly: **a clean chart cannot buy a lower
risk label.** Score is a ranking device; the risk tier is set by structure — security quality,
tier, and whether you can actually exit the position.

### 3.3 Recommendation engine

| Output | Trigger | Size |
|---|---|---|
| **STRONG BUY** | Confluence ≥80 · technicals present · trend uptrend or chop | Full tier allocation |
| **BUY** | Confluence ≥68 · mid-cap tier | Full tier allocation |
| **SPECULATIVE ENTRY** | Confluence ≥68 · trench tier | Full tier allocation (≤2%) |
| **WAIT FOR DIP** | Confluence ≥55 with RSI >72, *or* any buy signal in a 15m downtrend | Half tier allocation |
| **WATCHLIST** | Confluence ≥55 · or any buy signal without candle history | 0% |
| **AVOID** | Confluence <55 · or any security hard-fail | 0% |

### 3.4 Verified against live tokens

| Token | Sec | On-chain | Tech | Confluence | Verdict | Why this is right |
|---|---|---|---|---|---|---|
| BONK | 77 | 77 | 60 | 72 | **BUY · Medium · 3%** | Clean authorities, LP across 114 providers, 15m uptrend, but a 1h veto capped the technical score |
| JUP | 60 | 65 | n/a | 55 | **WATCHLIST · High** | Unlabelled treasury wallets read as 66% top-10; missing candles capped it at 55 |
| USDC | 0 | 65 | n/a | 0 | **AVOID · Degenerate** | Live mint *and* freeze authority. Correct output — and a reminder these rules are for SPL trading tokens, not stablecoins |
| Fresh trench (×2) | 100 | 92 | n/a | 55 | **WATCHLIST · High** | Perfect on paper. No candle history anywhere, so no entry, no stop, no trade. Was 96/100 before the cap existed |

---

## Section 4 — System architecture & workflow

### Two rounds, cheap gates first

The pipeline is ordered by cost, not by logic. Candles are the expensive input —
GeckoTerminal allows 30 calls a minute — so nothing fetches them until the free structural
checks have already passed. A token with an active mint authority never costs a single OHLCV
call.

```
/scan <mint>                ROUND 1 — cached, concurrent, free
allowlist check   ────────▶ ┌──────────────────────────────────┐
                            │ DexScreener  pools·price·txns    │
                            │ Rugcheck     authorities·LP·hldrs│
                            │ GeckoTerminal true reserve·vol24 │
                            └──────────────────────────────────┘
                              ↳ one failure ⇒ that dimension degrades, the scan survives
                                        │
                                        ▼
                                  ╔═══════════╗   hard-fail ⇒ skip candles
                                  ║   GATE    ║
                                  ║ liq≥$15k  ║
                                  ╚═══════════╝
                                        │
                                        ▼        ROUND 2 — rate-limited
                            ┌──────────────────────────────────┐
                            │ OHLCV: 15m first, then 5m + 1h   │
                            │ pool not indexed? → GT top-pool  │
                            │ skipped entirely in /discover    │
                            └──────────────────────────────────┘
                                        │
                                        ▼
                            Confluence → caps + overrides → risk tier
                            → position size → MarkdownV2
```

One `/scan`: five provider calls at worst, zero on a fully cached repeat, and no OHLCV spend
on tokens that fail structurally.

### 4.1 Telegram command triggers

| Command | Behaviour | Cost |
|---|---|---|
| `/scan <mint>` | Full report: security, on-chain, technicals, trade plan | ≤5 calls |
| `/discover midcap` | Scores GeckoTerminal trending Solana pools, light mode | ~26 calls |
| `/discover trench` | Scores the DexScreener boost leaderboard, light mode | ~26 calls |
| `/trend` | Alias for `/discover midcap` | — |
| `/health` | Purges expired cache rows, confirms liveness | 0 |

**Why discovery runs light.** Twelve candidates × three timeframes at 30 calls/min would take
90 seconds and consume the entire minute's OHLCV budget. Light mode shortlists on security
and liquidity — both cheap and heavily cached — and the no-technicals cap of 70 guarantees a
light scan can never emit a buy signal on its own. Discovery proposes; `/scan` confirms.

### 4.2 API aggregation architecture — free-tier survival

Every outbound call goes through one function, which is what makes rate-limit discipline a
property of the system rather than of each fetcher.

- **Per-provider token buckets** sized *below* the published limit — DexScreener 4 rps
  against 5, GeckoTerminal 0.45 rps against 0.5, Rugcheck 0.8 rps against 1. A burst of
  concurrent scans can never get a key throttled.
- **Two-level cache.** In-memory TTL for the hot path, SQLite (WAL) beneath it so a restart
  does not re-burn a day of Rugcheck credits. TTLs are set per provider by how fast the data
  actually moves: 900s security, 60s OHLCV, 15s quotes.
- **429 handling** honours `Retry-After` with jitter; 5xx gets exponential backoff; 404
  returns immediately rather than retrying three times.
- **Failures return `None`, never raise.** One dead provider degrades a score and says so in
  the output. It does not kill a scan.
- **Fallback chains** where a second free source exists: GeckoTerminal's own top-pool lookup
  when the DexScreener pool address is not indexed there.

> **Rate limiting is not optional, empirically.** An unthrottled test script hitting
> GeckoTerminal returned zero candles on several timeframes. The cause was not missing data —
> it was a silent 429 whose body was a Cloudflare notice. Without a bucket and without
> status-code inspection, that reads as "this token has no chart" and the agent draws a
> confident wrong conclusion.

### 4.3 Local PC execution pipeline

| | |
|---|---|
| **Footprint** | Long-polling, so no inbound ports, no webhook, no reverse proxy. Six dependencies. Indicators are hand-written on numpy rather than pulling pandas plus an unmaintained TA library — roughly 40 MB of RSS saved and one fewer supply-chain surface. Expect <120 MB idle |
| **Concurrency** | `concurrent_updates(4)` and a semaphore of 4 inside `scan_many`. The token buckets throttle the network; the semaphore bounds memory. One asyncio loop, one process, no worker pool |
| **Persistence** | A single SQLite file in WAL mode. No Redis, no Postgres, no Docker. Hourly vacuum runs on the bot's own job queue |
| **Availability** | Manual commands mean downtime costs nothing. When you want it always-on, a systemd user unit with `Restart=on-failure` is the whole answer — no orchestration |

---

## Section 5 — Step-by-step technical blueprint

### 5.1 Recommended tech stack, and why

**Python 3.12** over Node, for one reason that outweighs the rest: numerical work. RSI, ATR,
VWAP and pivot detection are natural on numpy and awkward in TypeScript, and this is
fundamentally a numerical pipeline with a chat interface bolted on. **python-telegram-bot
21.x** is fully async with a built-in rate limiter and job queue, so the scheduler for future
automation is already in the box. **httpx** for HTTP/2 connection pooling, **aiosqlite** for
the cache, **numpy** for indicators. Six dependencies total.

### 5.2 Modular directory structure

```
solana-trade/
├─ config.py              settings + per-provider rate budgets
├─ main.py                entrypoint, long-polling, job queue
├─ core/
│  ├─ http.py             shared client · token buckets · retry · cache-first fetch
│  └─ cache.py            TTL cache: memory L1 + SQLite L2
├─ providers/             one module per API — no business logic lives here
│  ├─ dexscreener.py      token_pairs · best_pair · aggregate · boosted_top
│  ├─ rugcheck.py         report · summary
│  └─ geckoterminal.py    ohlcv · trending · top_pool · token_stats
├─ analysis/              pure functions — no I/O, trivially testable
│  ├─ indicators.py       EMA · RSI · MACD · ATR · VWAP · fractal pivots
│  ├─ security.py         authorities · LP · concentration · insiders → 0-100
│  ├─ onchain.py          depth · liq/mcap · turnover · pressure → 0-100
│  ├─ technicals.py       trend · momentum · location · HTF veto → 0-100 + levels
│  ├─ scoring.py          weighted confluence · caps · risk tier · size
│  └─ pipeline.py         two-round orchestration
└─ bot/
   ├─ handlers.py         command surface · auth allowlist
   └─ templates.py        MarkdownV2 rendering
```

The boundary that earns its keep: `providers/` knows about HTTP and nothing about trading;
`analysis/` knows about trading and nothing about HTTP. Every scoring function takes plain
dicts and returns a dataclass, so you can unit-test the entire decision engine on saved JSON
fixtures with no network at all.

### 5.3 The core fetch — `core/http.py`

This one function is the whole free-tier strategy. Cache-first, bucket-gated, retrying, and
non-raising.

```python
class TokenBucket:
    """Async leaky bucket. Shared by all coroutines hitting one provider."""
    async def take(self):
        async with self._lock:
            while True:
                now = time.monotonic()
                self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rps)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
                await asyncio.sleep((1.0 - self.tokens) / self.rps)


async def request(provider, url, *, params=None, ttl=None, attempts=3):
    """Cache-first, rate-limited, retrying JSON fetch. Returns None on failure.

    Returning None instead of raising is deliberate: one dead provider must
    degrade a score, never kill a scan."""
    ttl = settings.limits[provider].ttl if ttl is None else ttl
    key = f"{provider}:{sha1(url + str(params))}"

    if (hit := await cache.get(key)) is not None:
        return hit

    for i in range(attempts):
        await bucket(provider).take()
        try:
            resp = await _client.get(url, params=params)
            if resp.status_code == 429:
                await asyncio.sleep(float(resp.headers.get("Retry-After", 2**i)) + random.uniform(0, .4))
                continue
            if resp.status_code >= 500:
                await asyncio.sleep(2**i + random.uniform(0, .4)); continue
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            await cache.set(key, data := resp.json(), ttl)
            return data
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(2**i * .3)
    return None
```

### 5.4 Orchestration — `analysis/pipeline.py`

```python
async def scan(mint: str, *, light: bool = False) -> ScanResult | None:
    # Round 1 — three free, cached, concurrent calls.
    agg, rc, tstats = await gather(
        dexscreener.aggregate(mint),      # base-side pools only, summed
        rugcheck.report(mint),
        geckoterminal.token_stats(mint),  # corrects DexScreener's 30-pool cap
    )
    if not agg:
        return None

    onc = onchain.analyse(agg, tstats)              # classifies tier, then bands
    sec = security.analyse(rc, tier=onc.tier)       # tier-aware thresholds

    # Round 2 — candles, only past the cheap gates.
    tech = technicals.TechRead()
    if not light and not sec.hard_fail and onc.liq_usd >= 15_000:
        pool = agg["pair"]["pairAddress"]
        base = await geckoterminal.ohlcv(pool, "15m")
        if not base:                                # GT indexes pools separately
            pool = await geckoterminal.top_pool(mint) or pool
            base = await geckoterminal.ohlcv(pool, "15m")
        m5, h1 = await gather(geckoterminal.ohlcv(pool, "5m"), geckoterminal.ohlcv(pool, "1h"))
        tech = technicals.analyse({"5m": m5, "15m": base, "1h": h1},
                                  risk="high" if onc.tier == "trench" else "medium")

    return ScanResult(..., verdict=scoring.decide(security=sec, onchain=onc, technicals=tech))
```

**Built for the automation you will add later.** `scan()` is stateless, async, and returns a
dataclass. Autonomous mode is a new caller — `app.job_queue.run_repeating` over a watchlist,
pushing any verdict above a threshold — not a rewrite. The one piece deliberately absent is
order execution: Jupiter's swap API would slot into an `execution/` package, and nothing
above it needs to change.

### 5.5 Telegram output template

Rendered MarkdownV2 from a live BONK scan. Bars are drawn with block characters rather than
emoji so the columns align in monospace; every dynamic value passes through an escaper, and
link targets use a separate escaper because escaping the dots inside a URL silently breaks
the link.

```
🟢 *BUY* — $Bonk
_Bonk_ · MIDCAP

*Confluence* `███████░░░` *72/100*
⚖️ Risk: *Medium* · Suggested size: *3%* of portfolio

*━━ Score breakdown ━━*
Security   `██████░░`  77.0
On-chain   `██████░░`  77.0
Technicals `█████░░░`  60.0
Sentiment  `░░░░░░░░`   n/a

*━━ Market ━━*
Price $0.00000295  ·  MCap $259.58M
Liq $1.21M (0.5% of mcap)  ·  Vol24 $319.68K
h1: -1.3% · h6: +0.9% · h24: -1.1%
1h buy pressure: *54%*

*━━ Security ━━*
⚠️ Top-10 holders 38.6% — concentrated.
⚠️ Rugcheck: Mutable metadata
✅ Mint authority revoked
✅ Freeze authority revoked
✅ No transfer tax
✅ LP distributed across 114 providers (lock not applicable)

*━━ Trade plan (15m) ━━*
Trend: *uptrend* · RSI 40 · ATR 1.3%
Entry  $0.00000294
Stop   $0.00000286  (-2.7%)
TP1    $0.00000305  (1.5R)
TP2    $0.00000317  (3.0R)
TP3    $0.00000333  (5.0R)

• EMA 9>21>50 — trend aligned bullish on 15m.
• Price +0.6% vs VWAP — holding above value.
• 1h EMA21 < EMA50 — higher timeframe caps the technical score.

⚙️ Degraded inputs: sentiment — weights redistributed.

DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
[Chart] · [Rugcheck]

_Analysis only, not financial advice. Verify before sizing._
```

Three things this layout does deliberately: the verdict and position size sit in the first
four lines, because that is all you will read most of the time; the score breakdown always
shows all four dimensions with `n/a` where data is missing, so an absent input is visible
rather than invisible; and the stop appears above the targets, because the risk is the number
you have to accept before the reward is meaningful.

### 5.6 Running it

```bash
# python3-venv is not installed on this machine yet — this is the only blocker
sudo apt install python3.12-venv

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # TELEGRAM_BOT_TOKEN from @BotFather + your numeric user id
python main.py
```

> **Set the allowlist before the first run.** `TELEGRAM_ALLOWED_USER_IDS` gates every handler.
> Left empty, the bot answers anyone who finds it — and a bot token in a public chat is a free
> API-quota faucet for strangers.

---

## Section 6 — Roadmap

1. **Install `python3.12-venv` and run it.** Everything else is speculation until you have
   seen the agent's output on tokens you already have an opinion about.
2. **Add GoPlus as a second security opinion.** Free, independent, and disagreement between
   two security sources is itself a signal.
3. **Log every verdict to SQLite with the price at scan time.** This is the highest-value
   item on the list and it costs an afternoon. Without it you cannot know whether your weights
   are any good; with three weeks of it you can measure the hit rate of each action tier and
   re-fit the thresholds against your own results rather than my calibration.
4. **Wire Vybe's free tier** for holder growth and retention — the one genuinely missing
   dimension in the current build.
5. **Buy Birdeye Lite ($39)** if and only if trench tokens are where you actually trade. It
   fixes the fresh-pool OHLCV gap and nothing else does at that price.
6. **Then automate.** A watchlist poller over `scan()` pushing verdicts above a threshold,
   then Jupiter swap execution behind a confirmation step. The pipeline is already shaped for
   both.

> **The honest limitation.** This agent filters and ranks. It does not predict. Its real value
> is negative: it eliminates honeypots, mint-authority traps, pulled liquidity and wash volume
> before you look at a chart, and it refuses to produce a trade plan when it cannot see one.
> The confluence score is a ranking device for surviving candidates — not a probability, and
> never a substitute for your own read on whether the trade makes sense.

---

*Provider pricing read from official documentation in August 2026 and subject to change
without notice — re-verify before committing spend. Thresholds calibrated against live Solana
token data at build time; markets drift and so should the numbers. Nothing here is financial
advice.*
