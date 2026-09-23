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


settings = Settings()
