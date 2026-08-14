import asyncio
from datetime import datetime, timezone

import httpx
import pytest

from app.collectors.mempool import MempoolSpaceCollector


def test_mempool_collector_parses_hashrate_and_difficulty() -> None:
    payload = {
        "hashrates": [
            {"timestamp": 1_700_000_000, "avgHashrate": 500_000_000_000_000_000_000}
        ],
        "difficulty": [
            {
                "time": 1_700_000_000,
                "height": 816_480,
                "difficulty": 67_957_779_029_897.88,
                "adjustment": 1.05,
            }
        ],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/all")
        return httpx.Response(200, json=payload)

    collector = MempoolSpaceCollector()

    async def collect():
        original = httpx.AsyncClient

        class StubClient(httpx.AsyncClient):
            def __init__(self, *args, **kwargs):
                super().__init__(transport=httpx.MockTransport(handler))

        httpx.AsyncClient = StubClient
        try:
            return await collector.collect({})
        finally:
            httpx.AsyncClient = original

    result = asyncio.run(collect())
    points = {point.metric: point for point in result.points}
    assert points["HashRate"].value == pytest.approx(500.0)
    assert points["HashRate"].unit == "EH/s"
    assert points["MiningDifficulty"].value == 67_957_779_029_897.88
    assert points["MiningDifficulty"].metadata["height"] == 816_480


def test_mempool_collector_uses_incremental_window_with_watermarks() -> None:
    watermark = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert MempoolSpaceCollector._cutoff(watermark).day == 18
