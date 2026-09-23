from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twelvedata_api_key: str | None = None
    econ_calendar_api_key: str | None = None
    coingecko_api_key: str | None = None
    news_api_key: str | None = None
    # US central bank rate/CPI/NFP/10Y yield via FRED -- see
    # data_sources/macro_data.py. Free, but unlike coingecko/binance/goplus/
    # dexscreener above, FRED requires a key even for basic series reads.
    fred_api_key: str | None = None
    # LP-holder-type check (app/data_sources/lp_lock_heuristic.py) -- free,
    # requires a key (https://bscscan.com/apis). Unset by default: this is
    # a yes/no fact (is the LP token held by a contract or a wallet), not
    # an estimate, so there's deliberately no synthetic fallback -- it's
    # either checked for real or not reported at all.
    bscscan_api_key: str | None = None

    analysis_cache_ttl_seconds: int = 180

    # Persistent support/resistance zone memory (app/data_sources/sr_memory_store.py)
    # -- a local SQLite file, not a separate database server. Survives across
    # requests/restarts so touch/hold/break history actually accumulates over
    # real time, unlike everything else in this framework's stateless per-
    # request computation.
    sr_memory_db_path: str = "sr_memory.db"

    # Specialist LLM synthesis agent (app/agents/specialist_agent.py) -- makes
    # the final BUY/SELL/HOLD call itself from the already-computed technical/
    # fundamentals/news evidence, instead of the deterministic weighted-formula
    # fallback in signal_synthesis_agent. Two independent providers, chosen per
    # request by the caller (e.g. free tier -> Gemini, paid tier -> Claude).
    # Either being unset just means that provider isn't available; the caller
    # falls back to the deterministic formula, never a fabricated verdict.
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"


settings = Settings()
