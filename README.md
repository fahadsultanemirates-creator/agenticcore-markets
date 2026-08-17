# AgenticCore Markets — Analysis Framework

Live technical + fundamental + news signal analysis for whichever forex pair
or crypto asset a subscriber selects. This is the agent pipeline behind the
dashboard: a FastAPI service that, per symbol, runs five agents and returns
a synthesized BUY/SELL/HOLD signal with reasoning.

## Architecture

- **`technical_analysis_agent`** — shared engine for both forex and crypto.
  Pulls OHLCV and computes RSI, MACD, moving averages, and support/resistance.
- **`forex_fundamentals_agent`** — economic calendar events, central bank
  commentary, macro sentiment.
- **`crypto_fundamentals_agent`** — market cap/volume, on-chain metrics,
  tokenomics/ecosystem news.
- **`news_aggregation_agent`** — recent timestamped news per asset with
  sentiment, shared across both asset classes.
- **`signal_synthesis_agent`** — combines the three inputs into a final
  signal with a written rationale (not a bare call).
- **`cache_layer`** — in-memory TTL cache (`app/cache/cache_layer.py`) so
  concurrent subscribers requesting the same symbol share one computation
  instead of recomputing per request. Default TTL: 3 minutes
  (`ANALYSIS_CACHE_TTL_SECONDS`).

`app/orchestrator.py` wires the agents together per asset and fronts them
with the cache. `app/main.py` exposes the HTTP API.

## Data sources

Each data-source client (`app/data_sources/`) is pluggable: if the matching
API key is set in the environment, it calls the live provider; otherwise it
falls back to deterministic synthetic sample data, so the full pipeline runs
end-to-end with no keys configured.

| Client | Live provider | Env var |
|---|---|---|
| `price_feed.py` | TwelveData | `TWELVEDATA_API_KEY` |
| `econ_calendar.py` | *(not yet wired — synthetic only)* | `ECON_CALENDAR_API_KEY` |
| `crypto_market.py` | CoinGecko | `COINGECKO_API_KEY` |
| `news_feed.py` | *(not yet wired — synthetic only)* | `NEWS_API_KEY` |

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

Covers indicator math, cache TTL/concurrency behavior, each agent in
isolation, and the full orchestrated pipeline end-to-end for both EURUSD
(forex) and BTCUSD (crypto) — proving the shared technical engine serves
both asset classes unmodified.

## Build order status

1. ✅ EURUSD fully working end-to-end (data → technical → fundamental →
   news → synthesized signal).
2. ✅ Crypto (BTCUSD, ETHUSD) reusing the shared technical/signal engine.
3. ⬜ Wire into the dashboard.

## Adding a new asset

Add an entry to `_ASSET_REGISTRY` in `app/assets.py` — no agent or
orchestration code needs to change.
