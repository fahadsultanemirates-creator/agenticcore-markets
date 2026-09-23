"""Non-US macro data to extend forex_fundamentals_agent's real-data
coverage beyond the USD leg (macro_data.py's FRED integration).

Two different confidence levels in this one file:

- World Bank API (GDP growth, current account balance) -- free, keyless,
  a stable and extremely well-documented public API, high confidence in
  the exact shape used here. Not real-time (annual data, published with a
  lag), but genuinely real. Uses each currency's single largest/dominant
  economy (DE for EUR, not an aggregate "euro area" code) specifically
  because individual-country ISO codes are unambiguous, while the exact
  aggregate-region code for "euro area" in World Bank's system was not
  confirmed against a live response.

- ECB Statistical Data Warehouse (main refinancing rate, HICP inflation)
  for EUR specifically -- free, keyless. LOWER confidence than the World
  Bank piece: the exact SDW series keys used here were not verified
  against a live response (this sandbox blocks reaching it), so treat
  this the same as price_feed.py's TwelveData path -- written correctly
  to the best of available knowledge, not proven against a real response.
  Any failure (wrong key, schema mismatch) degrades to None, handled by
  the caller the same as "FRED unavailable."
"""

import httpx

_WORLD_BANK_URL = "https://api.worldbank.org/v2/country/{country_code}/indicator/{indicator_code}"
_ECB_SDW_URL = "https://data-api.ecb.europa.eu/service/data/{flow_ref}/{series_key}"

_GDP_GROWTH_INDICATOR = "NY.GDP.MKTP.KD.ZG"
_CURRENT_ACCOUNT_INDICATOR = "BN.CAB.XOKA.GD.ZS"

# Dominant/representative economy per currency -- unambiguous ISO2 codes,
# not aggregate region codes.
_REPRESENTATIVE_COUNTRY = {
    "EUR": "DE",
    "GBP": "GB",
    "JPY": "JP",
    "AUD": "AU",
    "NZD": "NZ",
    "CAD": "CA",
    "CHF": "CH",
    "USD": "US",
}

_ECB_MAIN_REFI_RATE = ("FM", "B.U2.EUR.4F.KR.MRR_FR.LEV")
_ECB_HICP_INFLATION = ("ICP", "M.U2.N.000000.4.ANR")


def parse_world_bank_latest_value(payload: list) -> float | None:
    """Pure parse: World Bank's response is [metadata, data_array], newest
    observation first; returns the first non-null value."""
    if not isinstance(payload, list) or len(payload) < 2 or not payload[1]:
        return None
    for row in payload[1]:
        if row.get("value") is not None:
            return float(row["value"])
    return None


class IntlMacroClient:
    async def fetch_growth_snapshot(self, currency: str) -> dict | None:
        country = _REPRESENTATIVE_COUNTRY.get(currency)
        if not country:
            return None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                gdp_resp = await client.get(
                    _WORLD_BANK_URL.format(country_code=country, indicator_code=_GDP_GROWTH_INDICATOR),
                    params={"format": "json", "per_page": 5},
                )
                gdp_resp.raise_for_status()
                current_account_resp = await client.get(
                    _WORLD_BANK_URL.format(country_code=country, indicator_code=_CURRENT_ACCOUNT_INDICATOR),
                    params={"format": "json", "per_page": 5},
                )
                current_account_resp.raise_for_status()

            gdp_growth_pct = parse_world_bank_latest_value(gdp_resp.json())
            current_account_pct_gdp = parse_world_bank_latest_value(current_account_resp.json())
            if gdp_growth_pct is None and current_account_pct_gdp is None:
                return None
            return {"country": country, "gdp_growth_pct": gdp_growth_pct, "current_account_pct_gdp": current_account_pct_gdp}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return None

    async def fetch_eur_snapshot(self) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                rate = await self._fetch_ecb_series(client, *_ECB_MAIN_REFI_RATE)
                hicp = await self._fetch_ecb_series(client, *_ECB_HICP_INFLATION)
            if rate is None and hicp is None:
                return None
            return {"main_refi_rate_pct": rate, "hicp_yoy_pct": hicp}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            return None

    async def _fetch_ecb_series(self, client: httpx.AsyncClient, flow_ref: str, series_key: str) -> float | None:
        resp = await client.get(
            _ECB_SDW_URL.format(flow_ref=flow_ref, series_key=series_key),
            params={"format": "jsondata", "lastNObservations": 1},
        )
        resp.raise_for_status()
        payload = resp.json()
        series = payload["dataSets"][0]["series"]
        first_series = next(iter(series.values()))
        observations = first_series["observations"]
        latest = next(iter(observations.values()))
        return float(latest[0])
