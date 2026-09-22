"""US macro data (Fed funds rate, CPI, unemployment, payrolls, 10Y yield)
from FRED (Federal Reserve Economic Data) -- free, but requires an API key
(FRED_API_KEY) unlike the other Tier 2 sources in this module set.

FRED covers the US side of any pair well; it doesn't have clean equivalents
for every other central bank/economy, so this only replaces the USD leg of
forex_fundamentals_agent's macro read -- the non-USD leg (and the whole
picture when no key is set) still falls back to the existing central-bank
commentary + placeholder macro bias.
"""

from datetime import datetime

import httpx

from app.config import settings

_FRED_URL = "https://api.stlouisfed.org/fred/series/observations"

_SERIES = {
    "fed_funds_rate": "FEDFUNDS",
    "unemployment_rate": "UNRATE",
    "ust_10y_yield": "DGS10",
    "cpi_index": "CPIAUCSL",  # monthly index level, not YoY -- computed below
    "payrolls": "PAYEMS",  # thousands of persons, level -- MoM change computed below
}


def parse_cpi_yoy(observations: list[dict]) -> float | None:
    """Pure parse: FRED returns monthly observations newest-first. YoY %
    change needs the latest value against the one 12 observations back."""
    values = [float(o["value"]) for o in observations if o.get("value") not in (None, ".")]
    if len(values) < 13:
        return None
    return (values[0] - values[12]) / values[12] * 100


def parse_payrolls_change(observations: list[dict]) -> float | None:
    """Pure parse: month-over-month change in nonfarm payrolls (thousands)."""
    values = [float(o["value"]) for o in observations if o.get("value") not in (None, ".")]
    if len(values) < 2:
        return None
    return values[0] - values[1]


class MacroDataClient:
    def is_available(self) -> bool:
        return bool(settings.fred_api_key)

    async def fetch_us_snapshot(self) -> dict | None:
        if not self.is_available():
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                fed_funds, unrate, ust10y, cpi, payrolls = [
                    await self._fetch_series(client, series_id, limit)
                    for series_id, limit in [
                        (_SERIES["fed_funds_rate"], 1),
                        (_SERIES["unemployment_rate"], 1),
                        (_SERIES["ust_10y_yield"], 1),
                        (_SERIES["cpi_index"], 13),
                        (_SERIES["payrolls"], 2),
                    ]
                ]

            return {
                "fed_funds_rate_pct": float(fed_funds[0]["value"]) if fed_funds else None,
                "unemployment_rate_pct": float(unrate[0]["value"]) if unrate else None,
                "ust_10y_yield_pct": float(ust10y[0]["value"]) if ust10y else None,
                "cpi_yoy_pct": parse_cpi_yoy(cpi),
                "payrolls_change_thousands": parse_payrolls_change(payrolls),
                "as_of": datetime.now().isoformat(),
            }
        except (httpx.HTTPError, ValueError, KeyError, IndexError):
            return None

    async def _fetch_series(self, client: httpx.AsyncClient, series_id: str, limit: int) -> list[dict]:
        resp = await client.get(
            _FRED_URL,
            params={
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            },
        )
        resp.raise_for_status()
        return resp.json().get("observations", [])
