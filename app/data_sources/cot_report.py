"""CFTC Commitments of Traders (COT) report for forex positioning --
non-commercial (speculative) net long/short on currency futures, and
whether that positioning looks crowded/overextended.

Unlike crypto_safety.py/derivatives.py (GoPlus, DexScreener, Binance), this
is NOT wired to a live provider yet. The CFTC does publish this for free at
publicreporting.cftc.gov, but its dataset id and exact field names weren't
verified against a live response before this was written (this sandbox's
egress policy blocks reaching it at all), so writing speculative parsing
code against an unconfirmed schema would be worse than being explicit about
the gap -- same call the repo already made for econ_calendar.py and
news_feed.py. _fetch_live is a real seam, not a real integration: fill it in
once the dataset id/schema are confirmed against a live pull.
"""

from datetime import datetime, timedelta, timezone

from app.data_sources.mock_utils import rng_for
from app.models import PositioningResult

# Rough historical range used only to judge whether a synthetic net
# position looks "crowded" -- not a real historical distribution.
_CROWDED_THRESHOLD_CONTRACTS = 80_000


class CotReportClient:
    async def fetch_positioning(self, currency: str) -> PositioningResult:
        try:
            return await self._fetch_live(currency)
        except NotImplementedError:
            return self._synthetic_positioning(currency)

    async def _fetch_live(self, currency: str) -> PositioningResult:  # pragma: no cover - no provider wired yet
        raise NotImplementedError("Live CFTC COT provider not yet integrated -- schema unverified, see module docstring")

    def _synthetic_positioning(self, currency: str) -> PositioningResult:
        rng = rng_for(currency, "cot")
        net_position = rng.uniform(-120_000, 120_000)
        is_extreme = abs(net_position) > _CROWDED_THRESHOLD_CONTRACTS
        note = (
            f"Speculative net position of {net_position:+,.0f} contracts is "
            f"{'near a crowded extreme -- watch for a mean-reversion or squeeze' if is_extreme else 'within a normal range'}."
        )
        return PositioningResult(
            currency=currency,
            as_of_report_date=datetime.now(timezone.utc) - timedelta(days=3),  # COT is reported with a lag
            net_speculative_position=net_position,
            is_crowded_extreme=is_extreme,
            note=note,
        )
