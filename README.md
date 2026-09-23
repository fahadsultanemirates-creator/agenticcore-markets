# AgenticCore Markets — Analysis Framework

Live technical + fundamental + news signal analysis for whichever forex pair
or crypto asset a subscriber selects. This is the agent pipeline behind the
dashboard: a FastAPI service that, per symbol, runs five agents and returns
a synthesized BUY/SELL/HOLD signal with reasoning.

## Architecture

- **`technical_analysis_agent`** — shared engine for both forex and crypto.
  Pulls OHLCV and computes RSI, MACD, moving averages, ATR, 50/200 EMA
  alignment, RSI divergence, volume-profile point of control, and
  support/resistance.
- **`forex_fundamentals_agent`** — economic calendar events, central bank
  commentary, real US macro data (rates/CPI/unemployment/payrolls) when a
  FRED key is set, non-US growth/current-account data (World Bank) and EUR
  rate/inflation data (ECB) for the non-USD leg, the global risk-on/risk-off
  regime, and CFTC COT positioning.
- **`crypto_fundamentals_agent`** — the on-chain safety gate
  (contract/honeypot checks, liquidity depth, holder concentration, plus a
  weaker LP-holder-type heuristic), tokenomics (circulating vs. FDV, next
  scheduled token unlock), derivatives positioning (OI/funding/taker flow on
  both perp AND spot, so a leverage-only move can be told apart from one
  spot flow actually confirms), on-chain activity, BTC macro backdrop, and
  ecosystem notes. A failed safety gate is a hard override enforced in
  `signal_synthesis_agent`, not just one more weighted input — "skip the
  trade regardless of chart patterns."
- **`news_aggregation_agent`** — recent timestamped news per asset with
  sentiment, shared across both asset classes.
- **`signal_synthesis_agent`** — combines the three inputs into a final
  signal with a written rationale (not a bare call), subject to the safety
  gate override above.
- **`cache_layer`** — in-memory TTL cache (`app/cache/cache_layer.py`) so
  concurrent subscribers requesting the same symbol share one computation
  instead of recomputing per request. Default TTL: 3 minutes
  (`ANALYSIS_CACHE_TTL_SECONDS`).

`app/orchestrator.py` wires the agents together per asset and fronts them
with the cache. `app/main.py` exposes the HTTP API.

## Data sources

Each data-source client (`app/data_sources/`) is pluggable: where the
provider is genuinely keyless (GoPlus, DexScreener, Binance, CoinGecko's
basic endpoints), it always attempts the live call first; where a key is
required (TwelveData, FRED), it only attempts live when the key is set.
Either way, any failure — no key, blocked network, non-2xx, malformed
response — degrades to deterministic synthetic sample data, so the full
pipeline always runs end-to-end.

| Client | Live provider | Env var | Verification status |
|---|---|---|---|
| `price_feed.py` | TwelveData | `TWELVEDATA_API_KEY` | Written, never executed against the live API |
| `econ_calendar.py` | *(not yet wired — synthetic only)* | `ECON_CALENDAR_API_KEY` | N/A |
| `crypto_market.py` | CoinGecko (market data + BTC dominance) | `COINGECKO_API_KEY` (optional, keyless works) | Written, parse logic unit-tested against fixtures; live call unverified in this dev environment (egress-restricted) |
| `crypto_safety.py` | GoPlus (contract security) + DexScreener (liquidity) | — (keyless) | Written, parse logic unit-tested against realistic fixtures; live call unverified in this dev environment |
| `derivatives.py` | Binance public futures API (OI, funding, perp taker flow) + Binance spot klines (spot taker flow, the actual "CVD" comparison) | — (keyless) | Written, parse logic unit-tested against fixtures; live call unverified in this dev environment |
| `token_unlocks.py` | DefiLlama emissions/unlocks tracker | — (keyless) | Written, parse logic unit-tested against a realistic fixture; **lower confidence than the row above** — the exact response shape wasn't confirmed against a live response, so parsing is deliberately defensive (broad except, degrades to "no unlock data" rather than a wrong number) |
| `intl_macro.py` (World Bank half) | World Bank API — GDP growth + current account, per currency's dominant economy | — (keyless) | Written, parse logic unit-tested against the documented `[metadata, data]` shape; high confidence (stable, well-documented public API), live call unverified in this dev environment |
| `intl_macro.py` (ECB half) | ECB Statistical Data Warehouse — EUR main refi rate + HICP inflation | — (keyless) | Written; **lower confidence** — the exact SDW series keys were not verified against a live response, so any failure degrades to `None` the same as "FRED unavailable" |
| `lp_lock_heuristic.py` | BscScan — is the top LP-token holder a contract or a wallet | `BSCSCAN_API_KEY` | **Deliberately not true lock verification** — confirming a specific locker service (Unicrypt/PinkLock/etc.) would require guessing that service's exact vault addresses, which was never confirmed and won't be guessed. This checks a narrower, high-confidence fact instead (contract bytecode present or not) and returns `None` ("not checked") rather than a fabricated yes/no when the key is unset or the check fails — never "assumed safe" |
| `macro_data.py` | FRED (US rates/CPI/unemployment/payrolls) | `FRED_API_KEY` | Written, parse logic unit-tested against fixtures; live call unverified (also requires a key nobody has set yet) |
| `cot_report.py` | CFTC COT report | — | **Stub only** — `_fetch_live` raises `NotImplementedError`. Dataset id/schema were never confirmed against a live response, so no speculative parsing code was written against it (same call already made for `econ_calendar.py`/`news_feed.py`) |
| `news_feed.py` | *(not yet wired — synthetic only)* | `NEWS_API_KEY` | N/A |

"Unverified in this dev environment" means exactly that, not "broken" —
the parsing logic is tested against realistic sample payloads shaped like
each provider's actual documented response format, but the live HTTP call
itself has never completed successfully because this sandbox's egress
policy blocks reaching any of these hosts. The first real deployment with
outbound internet access should smoke-test each live path before trusting
it for real trading decisions.

See `.env.example` for the full list.

## Running locally

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

- `GET /health`
- `GET /api/v1/assets` — supported symbols
- `GET /api/v1/analysis/{symbol}` — e.g. `/api/v1/analysis/EURUSD`, `/api/v1/analysis/BTCUSD`

## Tests

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Covers indicator math (including ATR/divergence/volume-profile), cache
TTL/concurrency behavior, each agent in isolation, the new data-source
parse functions against realistic fixtures, the safety-gate override in
signal synthesis, and the full orchestrated pipeline end-to-end for EURUSD
(forex), BTCUSD (crypto, no contract), and ACUSD (crypto, real BEP-20
contract — AgenticCore's own token) — proving the shared technical engine
serves all of them unmodified, and that the safety gate actually runs for
a real token contract, not just the two native assets.

## Build order status

1. ✅ EURUSD fully working end-to-end (data → technical → fundamental →
   news → synthesized signal).
2. ✅ Crypto (BTCUSD, ETHUSD, ACUSD) reusing the shared technical/signal
   engine, including the on-chain safety gate for actual token contracts.
3. ⬜ Wire into the dashboard.
4. ✅ Tier 1 (pure math on existing OHLCV data): ATR, 50/200 EMA alignment,
   RSI divergence, volume-profile POC — live-verified.
5. 🟡 Tier 2 (free/keyless providers): crypto safety gate (GoPlus +
   DexScreener), crypto derivatives incl. spot CVD (Binance), BTC dominance
   + FDV (CoinGecko), token unlocks (DefiLlama), non-US growth data (World
   Bank), EUR rate/inflation (ECB) — written and parse-tested against
   realistic fixtures, live call unverified in this dev environment
   (egress-restricted; see the Data sources table above).
6. 🟡 Tier 3 (free-tier-with-signup providers): US macro via FRED, LP-holder-
   type heuristic via BscScan — written, each requires its own API key to
   even attempt the live path.
7. ⬜ Tier 4 (paid or genuinely hard to source / intentionally scoped down):
   exchange-to-wallet netflow, non-US PMI at API quality, CFTC COT (schema
   not confirmed against a live response, so left as a documented stub
   rather than unverified guesswork — see `cot_report.py`), and true LP-lock
   verification (which specific locker service, for how long — scoped down
   to the weaker contract-vs-wallet heuristic in `lp_lock_heuristic.py`
   instead of guessing at locker contract addresses).

## Adding a new asset

Add an entry to `_ASSET_REGISTRY` in `app/assets.py` — no agent or
orchestration code needs to change. For an actual token contract (not a
base-layer native asset like BTC/ETH), also set `contract_address` and
`chain_id` so the safety-gate agent has something to check — see the
`ACUSD` entry for a live example (AgenticCore's own BEP-20 token).
