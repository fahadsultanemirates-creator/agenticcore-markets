from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    twelvedata_api_key: str | None = None
    alpha_vantage_api_key: str | None = None
    econ_calendar_api_key: str | None = None
    coingecko_api_key: str | None = None
    coinmarketcap_api_key: str | None = None
    news_api_key: str | None = None

    analysis_cache_ttl_seconds: int = 180


settings = Settings()
