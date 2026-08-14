import asyncio

import app.service as service_module
from app.service import ResearchService


class SlowCollector:
    source = "slow"
    name = "Slow public source"
    metrics = ("SlowMetric",)

    async def collect(self, _watermarks):
        await asyncio.sleep(1)


def test_collector_total_timeout(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(service_module, "COLLECTOR_TIMEOUT_SECONDS", 0.01)
    service = ResearchService(None)

    collector, result = asyncio.run(
        service._collect_with_timeout(SlowCollector(), {})
    )

    assert collector.source == "slow"
    assert isinstance(result, TimeoutError)
    assert "0.01 seconds" in str(result)


def test_refresh_progress_lists_sources_before_completion() -> None:
    states = ResearchService._pending_sources([SlowCollector()], "running")

    assert states == {
        "slow": {
            "name": "Slow public source",
            "status": "running",
            "rowsWritten": 0,
            "error": None,
            "finishedAt": None,
        }
    }


def test_retired_source_is_catalogued_but_not_refreshed(tmp_path) -> None:
    service = ResearchService(None)

    assert "blockchain_charts" in {
        collector.source for collector in service.source_catalog
    }
    assert "blockchain_charts" not in {
        collector.source for collector in service.collectors
    }


def test_health_metric_names_are_an_in_memory_snapshot() -> None:
    service = ResearchService(None)
    service._metric_names.update({"PriceUSD", "HashRate"})

    assert service.metric_names == ["HashRate", "PriceUSD"]


def test_overview_uses_cache_until_it_is_explicitly_refreshed(monkeypatch) -> None:
    builds = []

    def fake_build(_database, refresh_state):
        builds.append(refresh_state)
        return {"generatedAt": f"build-{len(builds)}", "refresh": refresh_state}

    monkeypatch.setattr(service_module, "build_overview", fake_build)
    service = ResearchService(None)

    first = service.overview()
    second = service.overview()
    refreshed = service.refresh_overview_cache()

    assert first is second
    assert first["generatedAt"] == "build-1"
    assert refreshed["generatedAt"] == "build-2"
    assert service.overview() is refreshed
    assert len(builds) == 2
    assert service.overview_cache_state["status"] == "ready"


def test_refresh_history_hides_failures_for_retired_or_paused_sources() -> None:
    class HistoryDatabase:
        @staticmethod
        def refresh_history(_limit):
            return {
                "runs": [],
                "consecutiveFailures": [
                    {"source": "coinmetrics_community", "count": 1},
                    {"source": "blockchain_charts", "count": 15},
                    {"source": "deribit_public", "count": 9},
                ],
            }

    service = ResearchService(HistoryDatabase())

    assert service.refresh_history()["consecutiveFailures"] == [
        {"source": "coinmetrics_community", "count": 1}
    ]
