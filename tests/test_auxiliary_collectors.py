import asyncio
from datetime import datetime, timedelta, timezone

import app.collectors.fear_greed as fear_greed_module
import app.collectors.stablecoins as stablecoins_module
from app.collectors.fear_greed import FearGreedCollector
from app.collectors.stablecoins import StablecoinsCollector


class StubResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class StubClient:
    def __init__(self, payload, **_kwargs):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url):
        return StubResponse(self.payload)


def test_stablecoin_collector_parses_usd_and_uses_overlap(monkeypatch) -> None:
    latest = datetime(2026, 1, 10, tzinfo=timezone.utc)
    payload = [
        {"date": str(int((latest - timedelta(days=4)).timestamp())), "totalCirculatingUSD": {"peggedUSD": 100}},
        {"date": str(int((latest - timedelta(days=2)).timestamp())), "totalCirculatingUSD": {"peggedUSD": 120}},
    ]
    monkeypatch.setattr(
        stablecoins_module.httpx,
        "AsyncClient",
        lambda **kwargs: StubClient(payload, **kwargs),
    )

    result = asyncio.run(
        StablecoinsCollector().collect({"StablecoinSupplyUSD": latest})
    )

    assert len(result.points) == 1
    assert result.points[0].value == 120
    assert result.points[0].unit == "USD"


def test_fear_greed_collector_preserves_classification(monkeypatch) -> None:
    observed = datetime(2026, 1, 10, tzinfo=timezone.utc)
    payload = {
        "data": [
            {
                "value": "21",
                "value_classification": "Extreme Fear",
                "timestamp": str(int(observed.timestamp())),
            }
        ]
    }
    monkeypatch.setattr(
        fear_greed_module.httpx,
        "AsyncClient",
        lambda **kwargs: StubClient(payload, **kwargs),
    )

    result = asyncio.run(FearGreedCollector().collect())

    assert result.points[0].value == 21
    assert result.points[0].unit == "index 0-100"
    assert result.points[0].metadata["classification"] == "Extreme Fear"
