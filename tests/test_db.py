from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from app.db import Database
from app.models import DataPoint


def test_replace_series_is_idempotent(tmp_path) -> None:
    database = Database(tmp_path / "test.duckdb")
    database.initialize()
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

    first = DataPoint(
        source="test",
        metric="PriceUSD",
        observed_at=observed_at,
        value=100.0,
        unit="USD",
        fetched_at=observed_at,
    )
    revised = DataPoint(
        source="test",
        metric="PriceUSD",
        observed_at=observed_at,
        value=101.0,
        unit="USD",
        fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )

    assert database.replace_series([first]) == 1
    assert database.replace_series([revised]) == 1
    assert database.replace_series([revised]) == 0
    series = database.series("PriceUSD")
    assert len(series) == 1
    assert series[0]["value"] == 101.0


def test_replace_series_batches_large_imports(tmp_path) -> None:
    database = Database(tmp_path / "large.duckdb")
    database.initialize()
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    points = [
        DataPoint(
            source="test",
            metric="HashRate",
            observed_at=observed_at + timedelta(hours=index),
            value=float(index),
            unit="EH/s",
            fetched_at=observed_at,
        )
        for index in range(1200)
    ]

    assert database.replace_series(points) == 1200
    assert len(database.series("HashRate", 1500)) == 1200
    assert database.replace_series(points) == 0


def test_watermarks_and_parquet_archive(tmp_path) -> None:
    database = Database(tmp_path / "test.duckdb")
    database.initialize()
    observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    database.replace_series([
        DataPoint(
            source="test",
            metric="PriceUSD",
            observed_at=observed_at,
            value=100.0,
            unit="USD",
            fetched_at=observed_at,
        )
    ])

    assert database.latest_observed_times(["PriceUSD"])["PriceUSD"] == observed_at
    archive = database.archive_to_parquet(tmp_path / "parquet")

    assert archive["status"] == "ok"
    assert archive["filesWritten"] == 2
    observation_file = (
        tmp_path
        / "parquet"
        / "observations"
        / "year=2026"
        / "month=01"
        / "observations.parquet"
    )
    assert observation_file.exists()
    with duckdb.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM read_parquet(?)", [str(observation_file)]
        ).fetchone()[0] == 1


def test_score_snapshot_schema_migrates_and_records_cycle_score(tmp_path) -> None:
    path = tmp_path / "legacy.duckdb"
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE score_snapshots (
                observed_at TIMESTAMPTZ NOT NULL,
                environment_score DOUBLE,
                reversal_score DOUBLE,
                confidence_score DOUBLE,
                reversal_coverage VARCHAR NOT NULL,
                rule_version VARCHAR NOT NULL,
                payload_json VARCHAR NOT NULL
            )
            """
        )

    database = Database(path)
    database.initialize()
    database.record_score_snapshot(
        {
            "generatedAt": "2026-08-12T00:00:00+00:00",
            "scores": {
                "environment": {"value": 50},
                "cycle": {"value": 70},
                "reversal": {"value": None, "coverage": "0/6"},
                "confidence": {"value": 90},
            },
        },
        "test-cycle-v1",
    )

    history = database.score_history()
    assert history[0]["cycle"] == 70
    assert history[0]["ruleVersion"] == "test-cycle-v1"


def test_score_snapshot_prefers_factor_model_scores(tmp_path) -> None:
    database = Database(tmp_path / "factor.duckdb")
    database.initialize()
    database.record_score_snapshot(
        {
            "generatedAt": "2026-08-12T00:00:00+00:00",
            "scores": {
                "environment": {"value": 51},
                "cycle": {"value": 74},
                "reversal": {"value": 30, "coverage": "3/6"},
                "confidence": {"value": 90},
            },
            "factorModel": {
                "longTerm": {"value": 57},
                "reversal": {"value": None, "coverage": 59},
            },
        },
        "factor-v2",
    )

    history = database.score_history()
    assert history[0]["environment"] == 57
    assert history[0]["reversal"] is None
    assert history[0]["reversalCoverage"] == "59%"


def test_refresh_result_records_source_and_metrics_together(tmp_path) -> None:
    database = Database(tmp_path / "refresh.duckdb")
    database.initialize()
    started_at = datetime(2026, 8, 12, tzinfo=timezone.utc)

    database.record_refresh_result(
        "test_source",
        started_at,
        "partial",
        3,
        "MetricB failed",
        [
            {
                "metric": "MetricA",
                "status": "ok",
                "rowsWritten": 3,
                "error": None,
            },
            {
                "metric": "MetricB",
                "status": "error",
                "rowsWritten": 0,
                "error": "MetricB failed",
            },
        ],
    )

    assert database.latest_refreshes()[0]["status"] == "partial"
    metrics = {item["metric"]: item for item in database.latest_metric_refreshes()}
    assert metrics["MetricA"]["rowsWritten"] == 3
    assert metrics["MetricB"]["status"] == "error"


def test_refresh_history_groups_rounds_and_counts_consecutive_failures(tmp_path) -> None:
    database = Database(tmp_path / "refresh-history.duckdb")
    database.initialize()
    first_started = datetime.now(timezone.utc) - timedelta(minutes=10)
    second_started = datetime.now(timezone.utc) - timedelta(minutes=5)

    database.record_refresh_result("source_a", first_started, "ok", 4, None, [])
    database.record_refresh_result(
        "source_b", first_started, "error", 0, "first failure", []
    )
    database.record_refresh_result(
        "source_a", second_started, "error", 0, "new failure", []
    )
    database.record_refresh_result(
        "source_b", second_started, "error", 0, "second failure", []
    )

    history = database.refresh_history(20)

    assert len(history["runs"]) == 2
    assert history["runs"][0]["status"] == "error"
    assert history["runs"][0]["failedCount"] == 2
    assert history["runs"][1]["status"] == "partial"
    failures = {
        item["source"]: item["count"]
        for item in history["consecutiveFailures"]
    }
    assert failures == {"source_a": 1, "source_b": 2}


def test_cvdd_monthly_references_use_median_and_upsert_by_source(tmp_path) -> None:
    database = Database(tmp_path / "cvdd.duckdb")
    database.initialize()

    database.upsert_cvdd_reference(
        "Source A", "https://example.com/a", date(2026, 8, 10), 40000.0
    )
    database.upsert_cvdd_reference(
        "Source B", "https://example.com/b", date(2026, 8, 11), 42000.0
    )
    database.upsert_cvdd_reference(
        "Source A", "https://example.com/a-new", date(2026, 8, 12), 41000.0
    )

    summary = database.cvdd_reference_summary()

    assert summary["available"] is True
    assert summary["sourceCount"] == 2
    assert summary["medianValueUsd"] == 41500.0
    assert summary["minimumValueUsd"] == 41000.0
    assert summary["maximumValueUsd"] == 42000.0
    assert summary["spreadPercent"] == pytest.approx(1000 / 41500 * 100)
    assert summary["agreement"] == "close"
    assert len(summary["history"]) == 2
    assert summary["sources"][0]["sourceUrl"] == "https://example.com/a-new"
