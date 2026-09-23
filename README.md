# AgenticCore Markets — Analysis Framework

Live technical + fundamental + news signal analysis for whichever forex pair,
commodity, or crypto asset a subscriber selects — including a token typed in
that isn't pre-registered anywhere. This is the agent pipeline behind the
dashboard (and, before that, the Telegram bot testing surface): a FastAPI
service that, per symbol, runs five agents and returns a synthesized
BUY/SELL/HOLD signal with reasoning.

## Asset coverage

- **Forex**: all 28 major pairs (the 8 major currencies — USD, EUR, GBP, JPY,
  CHF, CAD, AUD, NZD — pairwise, C(8,2) = 28), e.g. EURUSD, GBPJPY, AUDNZD.
- **Commodities**: gold, silver, WTI crude, Brent crude, natural gas
  (XAUUSD, XAGUSD, USOILUSD, UKOILUSD, NATGASUSD).
- **Crypto**: BTC, ETH, and AC (AgenticCore's own token) are curated in the
  static registry; **any other token can be typed in directly** — see
  "Any-token crypto lookup" below — and gets the exact same
  technical/fundamentals/news/signal pipeline as a curated asset.

## Architecture

- **`technical_analysis_agent`** — shared engine across all three asset
  classes. Pulls OHLCV and computes RSI, MACD, moving averages, ATR, 50/200
  EMA alignment, RSI divergence, volume-profile point of control, and
  support/resistance (real swing-high/low pivot detection on the OHLCV
  series, not a placeholder) — plus persistent S/R zone **memory** via
  `sr_memory.py`, weighted as a primary score component, not a minor nudge
  (see "Persistent support/resistance memory" below). For crypto, the price
  feed tries CoinGecko's OHLC endpoint first (broad token coverage, not
  just Binance/TwelveData majors) before falling back to TwelveData/
  synthetic — see "Crypto price data coverage" below for the real limits.
- **`forex_fundamentals_agent`** — economic calendar events, central bank
  commentary for all 8 major currencies, real US macro data
  (rates/CPI/unemployment/payrolls) when a FRED key is set, non-US
  growth/current-account data (World Bank) and EUR rate/inflation data (ECB)
  for the non-USD leg, the global risk-on/risk-off regime, and CFTC COT
  positioning.
- **`commodity_fundamentals_agent`** — the real-yield/USD-rate backdrop (the
  actual mechanism by which Fed policy moves non-yielding metals), the same
  shared risk-on/risk-off regime (safe-haven demand for gold/silver vs.
  growth-linked demand for energy), and CFTC COT positioning on the
  commodity's own futures. Does **not** cover physical supply/demand
  (OPEC output, EIA inventories) — see the data-sources table for why.
- **`crypto_fundamentals_agent`** — the on-chain safety gate
  (contract/honeypot checks, liquidity depth, holder concentration, plus a
  weaker LP-holder-type heuristic), whale/holder-concentration visibility
  (top1/top5/top10/top20 percentiles and a whale count, all from the same
  GoPlus holder list the safety gate already fetches), tokenomics
  (circulating vs. FDV, next scheduled token unlock), derivatives
  positioning (OI/funding/taker flow on both perp AND spot, so a
  leverage-only move can be told apart from one spot flow actually
  confirms), on-chain activity, BTC macro backdrop, and ecosystem notes. A
  failed safety gate is a hard override enforced in
  `signal_synthesis_agent`, not just one more weighted input — "skip the
  trade regardless of chart patterns." Runs identically whether the asset
  came from the static registry or was resolved on the fly (see below).
- **`news_aggregation_agent`** — recent timestamped news per asset with
  sentiment, shared across all three asset classes.
- **`signal_synthesis_agent`** — the deterministic fallback: combines the
  three inputs into a final signal via a weighted formula with a written
  rationale (not a bare call), subject to the safety gate override above.
  Used whenever no specialist LLM is requested, or the requested one isn't
  available.
- **`specialist_agent`** — an LLM (Claude or Gemini, chosen per request)
  that reads the same technical/fundamentals/news evidence and makes the
  actual final call itself, weighing conflicting signals with judgment
  rather than a fixed formula. See "Specialist LLM agent" below.
- **`cache_layer`** — in-memory TTL cache (`app/cache/cache_layer.py`) so
  concurrent subscribers requesting the same symbol (and the same model
  choice) share one computation instead of recomputing per request.
  Default TTL: 3 minutes (`ANALYSIS_CACHE_TTL_SECONDS`).

`app/orchestrator.py` wires the agents together per asset (routing to the
right fundamentals agent by `asset_type`, and to the specialist agent or
the deterministic fallback by the requested `model`) and fronts them with
the cache. `app/main.py` exposes the HTTP API.

## Any-token crypto lookup

`app/data_sources/asset_resolver.py` resolves a crypto token that isn't in
the curated static registry (`app/assets.py`) at request time — this is
what lets someone type an arbitrary token (e.g. into the Telegram bot) and
get a real signal without it being pre-registered anywhere. Two entry
points, chosen automatically by what was typed:

- **A symbol/name** ("PEPE", "PEPEUSD") — via CoinGecko's free/keyless
  `/search` + `/coins/{id}` endpoints (preferring an exact symbol match
  over a fuzzy one), reading the matched coin's `platforms` field for a
  contract address. Only finds tokens CoinGecko has already indexed.
- **A raw contract address** ("0x...", 42 hex chars) — resolved directly
  via DexScreener's `/tokens/{address}` endpoint, which queries the
  chain/DEX itself instead of any index. This closes the gap the
  symbol-search path can't: a token that's real and has DEX liquidity but
  is too new or too small for CoinGecko to have indexed yet. A CoinGecko
  id is still opportunistically looked up afterward (so live market-
  cap/OHLC data works too if it happens to be indexed); that lookup
  failing doesn't fail the resolution, it just means market/technical data
  for that token stays synthetic while safety/liquidity (contract-direct,
  no index needed) are still real.

Either way:
- `orchestrator.get_analysis(symbol)` tries the static registry first (the
  28 forex pairs, 5 commodities, and 3 curated crypto assets are a closed,
  curated universe); on a miss, it treats the input as a crypto lookup and
  calls the resolver, which picks the entry point above based on the
  input's shape.
- A contract address is only mapped to the on-chain safety gate on a chain
  this framework can actually check (Ethereum, BSC, Polygon, Arbitrum,
  Optimism, Base, Avalanche, Fantom — see the chain_id maps in that file).
  A token on an unmapped chain, or via the symbol path with an unmapped
  platform, still resolves and gets full technical/fundamentals/news/signal
  analysis — just without the safety gate (`has_contract=False`, same
  treatment as BTC/ETH) — since running that check without a confirmed
  chain_id would be guessing, not checking.
- A symbol or address that resolves to nothing real (typo, doesn't exist,
  no DEX liquidity) raises the same `KeyError` → HTTP 404 as before this
  existed.
- No synthetic fallback exists for resolution itself — unlike a data point
  (market cap, RSI, etc.), fabricating what a token *is* would be actively
  misleading, not illustrative. If neither provider can be reached (as in
  this dev sandbox — egress-restricted, see below) or doesn't know the
  token, the lookup returns "not found" rather than guessing.

## Persistent support/resistance memory

`app/agents/sr_memory.py` + `app/data_sources/sr_memory_store.py` give
`technical_analysis_agent` an actual memory, unlike everything else in this
framework (which recomputes fresh from scratch on every request). This
exists because real-world results from a live level-based forex system
back a specific claim: tested support/resistance structure holds up as a
signal, economic-calendar/news-driven signals don't — so key levels are
weighted as a **primary** score component here, not a minor nudge like RSI
divergence.

- **Storage**: a local SQLite file (`SR_MEMORY_DB_PATH`, default
  `sr_memory.db`) — not a separate database server, zero added
  infrastructure for a single-process VPS deployment.
- **Zone clustering**: a new pivot merges into an existing zone within a
  relative tolerance (0.15% for forex/commodities, 1% for crypto — wider,
  given crypto's larger effective spreads/volatility); the zone's stored
  price is a running average that converges over repeated touches.
- **Hold vs. break, independently detected**: a hold is pivot-anchored (a
  bounce — price moves away from the zone by more than tolerance without
  closing through it). A break does **not** require a pivot to form at the
  break point — a rally already underway can blow straight through a level
  with no local peak/trough there — so breaks are found by scanning every
  zone against all bars newer than its last test, independent of pivot
  detection. A confirmed break flips the zone's kind (classic "old
  resistance becomes new support") rather than retiring it.
- **No double-counting**: re-processing the same historical pivot on every
  request would silently inflate touch counts every time someone just asks
  for analysis again, without any new market data occurring — a real
  correctness trap for a "memory" system. A per-symbol watermark (pivots)
  and a per-zone watermark (breaks) both prevent this; see the module
  docstrings for the exact mechanism.
- **Strength labeling**: `new` / `weak` / `moderate` / `strong` / `very
  strong`, from a score combining hold count, touch count, and break count
  — surfaced as `key_levels` on `TechnicalAnalysisResult`, and cited by
  name in the technical summary ("price is near a very strong support at
  X, tested 6 times, held 5").

This only actually accumulates real history once the service runs
continuously against live market data over real time — a single request
(or this sandbox's synthetic OHLCV, which is deterministic per-symbol) only
exercises the mechanics, not weeks of genuine touch history. Verified via
unit tests that simulate the accumulation directly (repeated holds, a
break with a kind-flip, and the watermark preventing reprocessing).

## Specialist LLM agent

`app/agents/specialist_agent.py` is an alternative to the deterministic
`signal_synthesis_agent` formula: instead of a fixed weighted average, an
LLM reads the same technical (incl. S/R memory)/fundamentals/news evidence
and makes the actual BUY/SELL/HOLD call itself, with its own reasoning —
closer to how a human analyst weighs conflicting signals. Opt in per
request via `?model=claude` or `?model=gemini` on
`/api/v1/analysis/{symbol}`; omitting it uses the deterministic formula.

- **Claude** (`ANTHROPIC_API_KEY`, model configurable via
  `ANTHROPIC_MODEL`, default `claude-opus-5`) — official `anthropic` SDK,
  `client.messages.parse()` with a Pydantic output schema. High confidence
  in this pattern (documented, current SDK usage).
- **Gemini** (`GEMINI_API_KEY`, model configurable via `GEMINI_MODEL`,
  default `gemini-2.5-flash`) — official `google-genai` SDK. **Moderate
  confidence** on the exact structured-output parameter shape (Gemini
  isn't covered by this project's reference material the way Claude is):
  tries schema-constrained JSON first, falls back to parsing JSON out of
  plain text on any failure.
- **Never a hard dependency**: if the requested provider's key isn't set,
  or the call fails for any reason (rate limit, network, malformed
  response), `orchestrator.py` falls back to the deterministic formula
  automatically — a trading-signal service can't go down because an LLM
  provider had an outage. Neither provider was live-tested in this dev
  environment (no keys configured when this was built, and egress is
  restricted regardless) — verified via guard-path tests (no key → `None`,
  malformed key → `None`, never a raised exception) rather than a live call.
- **Cache key includes the model choice** — a `claude` request and a
  `gemini` request for the same symbol within the same TTL window get
  independent cache entries, not whichever one happened to ask first.

Suggested product framing (from the original discussion this was built
for): a free/demo tier on Gemini, a paid tier on Claude — this service just
exposes both; which one a given user gets is a decision for the caller
(the Telegram bot, or the dashboard) to make per request, not baked in here.

## Crypto price data coverage (the honest limits)

Different pieces of crypto analysis have genuinely different real-world
coverage, worth being explicit about rather than implying it's uniform:

- **Fundamentals/safety** (market cap, tokenomics, contract security,
  liquidity) scale to almost any token — CoinGecko aggregates across many
  exchanges itself, and GoPlus/DexScreener query the chain/DEX directly by
  contract address, independent of any listing.
- **Technicals** (RSI, support/resistance, etc.) use CoinGecko's OHLC
  endpoint for crypto — broader than Binance/TwelveData, but with two real
  caveats: no volume data (see `volume_profile_poc`'s zero-volume
  fallback in `indicators.py`), and coarser candle granularity than the
  ~hourly bars forex gets (roughly 4-hour candles over a 30-day window,
  per CoinGecko's free-tier tiering) — still real price action, just a
  different effective timeframe than the intended ~10-day/hourly view.
- **Derivatives** (open interest, funding, spot+perp taker flow/CVD) only
  works for tokens actually trading on Binance. For anything else —
  most small-cap tokens — this degrades to synthetic. No free provider
  covers OI/funding broadly across exchanges; this is a real, currently
  unaddressed gap for the long tail, not just an "unverified" one.

Bottom line: a token resolved dynamically will get real safety/liquidity/
tokenomics data and real (if coarser) price action, but its derivatives
positioning read is very likely synthetic unless it happens to be a
Binance-listed asset.

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
| `price_feed.py` (forex/commodities) | TwelveData | `TWELVEDATA_API_KEY` | Written, never executed against the live API (no key configured) |
| `price_feed.py` (crypto) | CoinGecko OHLC endpoint — tried first for any crypto asset with a known `coingecko_id`, broader coverage than TwelveData | — (keyless) | Written, parse logic unit-tested against a realistic fixture; **moderate confidence** on the exact day-range→candle-granularity tiering (general shape confirmed, exact cutoffs not verified against a live response); no volume data from this endpoint — see "Crypto price data coverage" above |
| `econ_calendar.py` | *(not yet wired — synthetic only)* | `ECON_CALENDAR_API_KEY` | N/A |
| `crypto_market.py` | CoinGecko (market data + BTC dominance) | `COINGECKO_API_KEY` (optional, keyless works) | Written, parse logic unit-tested against fixtures; live call unverified in this dev environment (egress-restricted) |
| `crypto_safety.py` | GoPlus (contract security) + DexScreener (liquidity) | — (keyless) | Written, parse logic unit-tested against realistic fixtures; live call unverified in this dev environment |
| `derivatives.py` | Binance public futures API (OI, funding, perp taker flow) + Binance spot klines (spot taker flow, the actual "CVD" comparison) | — (keyless) | Written, parse logic unit-tested against fixtures; live call unverified in this dev environment. **Coverage limit, not a verification issue**: only works for tokens actually listed on Binance — most small-cap/long-tail tokens will always degrade to synthetic here, no free provider covers OI/funding broadly across exchanges |
| `token_unlocks.py` | DefiLlama emissions/unlocks tracker | — (keyless) | Written, parse logic unit-tested against a realistic fixture; **lower confidence than the row above** — the exact response shape wasn't confirmed against a live response, so parsing is deliberately defensive (broad except, degrades to "no unlock data" rather than a wrong number) |
| `intl_macro.py` (World Bank half) | World Bank API — GDP growth + current account, per currency's dominant economy | — (keyless) | Written, parse logic unit-tested against the documented `[metadata, data]` shape; high confidence (stable, well-documented public API), live call unverified in this dev environment |
| `intl_macro.py` (ECB half) | ECB Statistical Data Warehouse — EUR main refi rate + HICP inflation | — (keyless) | Written; **lower confidence** — the exact SDW series keys were not verified against a live response, so any failure degrades to `None` the same as "FRED unavailable" |
| `lp_lock_heuristic.py` | BscScan — is the top LP-token holder a contract or a wallet | `BSCSCAN_API_KEY` | **Deliberately not true lock verification** — confirming a specific locker service (Unicrypt/PinkLock/etc.) would require guessing that service's exact vault addresses, which was never confirmed and won't be guessed. This checks a narrower, high-confidence fact instead (contract bytecode present or not) and returns `None` ("not checked") rather than a fabricated yes/no when the key is unset or the check fails — never "assumed safe". Key is configured, live call unverified in this dev environment (egress-restricted) |
| `macro_data.py` | FRED (US rates/CPI/unemployment/payrolls, incl. fed funds + 10Y yield used by `commodity_fundamentals_agent`'s rate backdrop) | `FRED_API_KEY` | Written, parse logic unit-tested against fixtures; key is configured, live call unverified in this dev environment (egress-restricted) |
| `asset_resolver.py` (symbol path) | CoinGecko `/search` + `/coins/{id}` — resolves a crypto symbol/name not in the static registry | — (keyless) | Written, parse logic unit-tested against realistic fixtures; live call unverified in this dev environment. No synthetic fallback by design — see "Any-token crypto lookup" above |
| `asset_resolver.py` (address path) | DexScreener `/tokens/{address}` — resolves a raw contract address directly, independent of CoinGecko's index, plus an opportunistic CoinGecko `/coins/{platform}/contract/{address}` id lookup | — (keyless) | Written, parse logic unit-tested against realistic fixtures; live call unverified in this dev environment. DexScreener's own chain-slug naming (e.g. `bsc`, not CoinGecko's `binance-smart-chain`) confirmed only for the chains explicitly mapped in that file |
| `cot_report.py` | CFTC COT report — used by both forex and commodity fundamentals (positioning on currency AND commodity futures) | — | **Stub only** — `_fetch_live` raises `NotImplementedError`. Dataset id/schema were never confirmed against a live response, so no speculative parsing code was written against it (same call already made for `econ_calendar.py`/`news_feed.py`) |
| `news_feed.py` | *(not yet wired — synthetic only)* | `NEWS_API_KEY` | N/A |
| Physical commodity supply/demand (OPEC output, EIA crude/gas inventories) | — | — | **Not built.** Needs a paid provider, or EIA's API (has a free tier, but its exact schema wasn't confirmed against a live response, so nothing was written against it) |
| `specialist_agent.py` (Claude) | Anthropic Claude API | `ANTHROPIC_API_KEY` | Written per the current documented SDK pattern (`client.messages.parse` + Pydantic schema); not live-tested (no key configured when built, egress-restricted regardless). Guard paths (no key, invalid key) are tested |
| `specialist_agent.py` (Gemini) | Google Gemini API | `GEMINI_API_KEY` | Written; **moderate confidence** on the exact structured-output parameter shape (not covered by this project's Claude-focused reference material) — defensive fallback to plain-text JSON parsing on any failure. Not live-tested, same reason as above |

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
- `GET /api/v1/assets` — all 36 curated symbols (28 forex + 5 commodities +
  3 crypto)
- `GET /api/v1/analysis/{symbol}` — e.g. `/api/v1/analysis/EURUSD`,
  `/api/v1/analysis/GBPJPY`, `/api/v1/analysis/XAUUSD`,
  `/api/v1/analysis/BTCUSD`, or any other crypto symbol/contract address
  not in the registry (e.g. `/api/v1/analysis/DOGEUSD`) — resolved live via
  `asset_resolver.py`. Optional `?model=claude` or `?model=gemini` to use
  the specialist LLM agent instead of the deterministic formula (falls back
  automatically if that provider's key isn't configured).

## Tests

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

130+ tests. Covers indicator math (including ATR/divergence/volume-profile),
cache TTL/concurrency behavior, each agent in isolation (forex, crypto, and
commodity fundamentals), the persistent S/R memory system (repeated holds,
a break with a kind-flip, and the watermark preventing reprocessing — each
test gets an isolated SQLite file via an autouse fixture in
`tests/conftest.py`, never the real database), the specialist agent's
guard paths (no key, invalid key → `None`, never a raised exception), the
new data-source parse functions against realistic fixtures, the safety-gate
override in signal synthesis, the asset-registry shape (28 forex pairs, 5
commodities), the asset-resolver's parse functions (both the symbol-search
and contract-address paths), and the full orchestrated pipeline end-to-end
for EURUSD (forex), GBPJPY (forex cross), XAUUSD (commodity), BTCUSD
(crypto, no contract), ACUSD (crypto, real BEP-20 contract), a
manually-built dynamically-resolved asset, and the `?model=` param's
fallback behavior — proving the shared technical/news/signal engine serves
all of them unmodified, and that the safety gate actually runs for a real
token contract in both the curated and dynamically-resolved paths.

## Build order status

1. ✅ EURUSD fully working end-to-end (data → technical → fundamental →
   news → synthesized signal).
2. ✅ Crypto (BTCUSD, ETHUSD, ACUSD, plus any other token via dynamic
   resolution) reusing the shared technical/signal engine, including the
   on-chain safety gate for actual token contracts.
2b. ✅ Full asset coverage: all 28 forex major pairs, 5 commodities (gold,
    silver, WTI, Brent, nat gas) via a dedicated `commodity_fundamentals_agent`,
    and any crypto token (by symbol OR raw contract address) via
    `asset_resolver.py` — not just the original 3-pair/3-coin seed set.
2c. ✅ Persistent support/resistance memory (`sr_memory.py`) weighted as a
    primary technical-score component, per real-world results showing S/R
    structure holds up where news/calendar signals don't. Crypto
    whale/holder-concentration visibility surfaced from data already being
    fetched. A specialist LLM agent (Claude or Gemini, opt-in per request)
    that makes the actual final call itself instead of a fixed formula,
    with the deterministic formula as an always-available fallback.
3. ⬜ Test end-to-end via the Telegram bot (already built, running on the
   VPS alongside the MT5 forex framework) before wiring into the dashboard.
4. ⬜ Wire into the dashboard.
5. ✅ Tier 1 (pure math on existing OHLCV data): ATR, 50/200 EMA alignment,
   RSI divergence, volume-profile POC — live-verified.
6. 🟡 Tier 2 (free/keyless providers): crypto safety gate (GoPlus +
   DexScreener), crypto derivatives incl. spot CVD (Binance), BTC dominance
   + FDV (CoinGecko), token unlocks (DefiLlama), non-US growth data (World
   Bank), EUR rate/inflation (ECB), any-token resolution (CoinGecko
   search) — written and parse-tested against realistic fixtures, live
   call unverified in this dev environment (egress-restricted; see the
   Data sources table above).
7. 🟡 Tier 3 (free-tier-with-signup providers): US macro via FRED, LP-holder-
   type heuristic via BscScan — both keys are now configured; live call
   still unverified in this dev environment (egress-restricted).
8. ⬜ Tier 4 (paid or genuinely hard to source / intentionally scoped down):
   exchange-to-wallet netflow, non-US PMI at API quality, physical
   commodity supply/demand (OPEC output, EIA inventories), CFTC COT
   (schema not confirmed against a live response, so left as a documented
   stub rather than unverified guesswork — see `cot_report.py`), and true
   LP-lock verification (which specific locker service, for how long —
   scoped down to the weaker contract-vs-wallet heuristic in
   `lp_lock_heuristic.py` instead of guessing at locker contract addresses).

## Adding a new asset

**Forex/commodities**: these are closed, curated universes (28 major pairs;
gold/silver/oil/gas) — add an entry to `_ASSET_REGISTRY` in `app/assets.py`
(or, for forex, add the currency to `_MAJOR_CURRENCIES` and every pair
follows automatically). No agent or orchestration code needs to change.

**Crypto**: no registration needed at all for an arbitrary token — see
"Any-token crypto lookup" above. Only add an entry to `_ASSET_REGISTRY`
for a token that should be curated (guaranteed fast, no live resolution
call) rather than resolved on demand — set `contract_address` and
`chain_id` so the safety-gate agent has something to check (see the
`ACUSD` entry for a live example, AgenticCore's own BEP-20 token), and
`coingecko_id` so `crypto_market.py` can fetch real market data instead of
falling back to synthetic.
