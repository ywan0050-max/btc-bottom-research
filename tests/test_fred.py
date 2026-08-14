import asyncio
from datetime import datetime, timezone

from app.collectors.fred import FredCollector


class StubResponse:
    text = "observation_date,M2SL\n2026-05-01,23000.0\n2026-06-01,23155.2\n"

    def raise_for_status(self) -> None:
        return None


class StubClient:
    def __init__(self) -> None:
        self.params = None

    async def get(self, _url, *, params):
        self.params = params
        return StubResponse()


def test_fred_m2_series_configuration_and_parsing() -> None:
    collector = FredCollector()
    client = StubClient()
    fetched_at = datetime(2026, 8, 14, tzinfo=timezone.utc)
    watermark = datetime(2026, 6, 1, tzinfo=timezone.utc)

    points = asyncio.run(
        collector._collect_series(
            client,
            "M2SL",
            collector.series["M2SL"],
            fetched_at,
            watermark,
        )
    )

    assert collector.series["M2SL"] == ("USM2", "billion USD", "monthly")
    assert client.params == {"id": "M2SL", "cosd": "2026-03-18"}
    assert [point.value for point in points] == [23000.0, 23155.2]
    assert all(point.metric == "USM2" for point in points)
    assert all(point.unit == "billion USD" for point in points)
    assert points[-1].metadata["frequency"] == "monthly"
