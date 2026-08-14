from __future__ import annotations

import json
import os
import statistics
import threading
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from .models import DataPoint


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.path))

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    source VARCHAR NOT NULL,
                    metric VARCHAR NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    value DOUBLE NOT NULL,
                    unit VARCHAR NOT NULL,
                    fetched_at TIMESTAMPTZ NOT NULL,
                    metadata_json VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS observations_identity
                ON observations(source, metric, observed_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS refresh_runs (
                    run_id VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ NOT NULL,
                    status VARCHAR NOT NULL,
                    rows_written INTEGER NOT NULL,
                    error VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS metric_refresh_runs (
                    run_id VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    metric VARCHAR NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ NOT NULL,
                    status VARCHAR NOT NULL,
                    rows_written INTEGER NOT NULL,
                    error VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS score_snapshots (
                    observed_at TIMESTAMPTZ NOT NULL,
                    environment_score DOUBLE,
                    cycle_score DOUBLE,
                    reversal_score DOUBLE,
                    confidence_score DOUBLE,
                    reversal_coverage VARCHAR NOT NULL,
                    rule_version VARCHAR NOT NULL,
                    payload_json VARCHAR NOT NULL
                )
                """
            )
            connection.execute(
                "ALTER TABLE score_snapshots ADD COLUMN IF NOT EXISTS cycle_score DOUBLE"
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS score_snapshots_identity
                ON score_snapshots(observed_at)
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS archive_runs (
                    run_id VARCHAR NOT NULL,
                    started_at TIMESTAMPTZ NOT NULL,
                    finished_at TIMESTAMPTZ NOT NULL,
                    status VARCHAR NOT NULL,
                    files_written INTEGER NOT NULL,
                    rows_archived BIGINT NOT NULL,
                    archive_path VARCHAR NOT NULL,
                    error VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cvdd_reference_entries (
                    entry_id VARCHAR NOT NULL,
                    source_key VARCHAR NOT NULL,
                    source_name VARCHAR NOT NULL,
                    source_url VARCHAR NOT NULL,
                    observed_date DATE NOT NULL,
                    observed_month DATE NOT NULL,
                    value_usd DOUBLE NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    note VARCHAR
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS cvdd_reference_identity
                ON cvdd_reference_entries(source_key, observed_month)
                """
            )

    def replace_series(self, points: Iterable[DataPoint]) -> int:
        return sum(self.replace_series_counts(points).values())

    def replace_series_counts(self, points: Iterable[DataPoint]) -> dict[str, int]:
        grouped: dict[tuple[str, str], list[DataPoint]] = defaultdict(list)
        for point in points:
            grouped[(point.source, point.metric)].append(point)
        if not grouped:
            return {}

        rows_written: dict[str, int] = defaultdict(int)
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                for (source, metric), series in grouped.items():
                    rows = [
                        (
                            point.source,
                            point.metric,
                            point.observed_at,
                            point.value,
                            point.unit,
                            point.fetched_at,
                            json.dumps(point.metadata, ensure_ascii=False),
                        )
                        for point in series
                    ]
                    first_observed = min(point.observed_at for point in series)
                    last_observed = max(point.observed_at for point in series)
                    existing = {
                        row[0]: (row[1], row[2], row[3])
                        for row in connection.execute(
                            """
                            SELECT observed_at, value, unit, metadata_json
                            FROM observations
                            WHERE source = ? AND metric = ?
                              AND observed_at BETWEEN ? AND ?
                            """,
                            [source, metric, first_observed, last_observed],
                        ).fetchall()
                    }
                    changed = sum(
                        existing.get(point.observed_at)
                        != (
                            point.value,
                            point.unit,
                            json.dumps(point.metadata, ensure_ascii=False),
                        )
                        for point in series
                    )
                    for offset in range(0, len(rows), 500):
                        batch = rows[offset : offset + 500]
                        placeholders = ", ".join(
                            "(?, ?, ?, ?, ?, ?, ?)" for _ in batch
                        )
                        parameters = [value for row in batch for value in row]
                        connection.execute(
                            f"""
                            INSERT INTO observations
                            (source, metric, observed_at, value, unit, fetched_at, metadata_json)
                            VALUES {placeholders}
                            ON CONFLICT (source, metric, observed_at) DO UPDATE SET
                                value = excluded.value,
                                unit = excluded.unit,
                                fetched_at = excluded.fetched_at,
                                metadata_json = excluded.metadata_json
                            """,
                            parameters,
                        )
                    rows_written[metric] += changed
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
        return dict(rows_written)

    def record_refresh(
        self,
        source: str,
        started_at: datetime,
        status: str,
        rows_written: int,
        error: str | None = None,
    ) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO refresh_runs
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    source,
                    started_at,
                    datetime.now(timezone.utc),
                    status,
                    rows_written,
                    error,
                ],
            )

    def record_metric_refreshes(
        self,
        source: str,
        started_at: datetime,
        results: Iterable[dict[str, Any]],
    ) -> None:
        finished_at = datetime.now(timezone.utc)
        rows = [
            (
                str(uuid.uuid4()),
                source,
                result["metric"],
                started_at,
                finished_at,
                result["status"],
                result["rowsWritten"],
                result.get("error"),
            )
            for result in results
        ]
        if not rows:
            return
        with self._lock, self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO metric_refresh_runs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def record_refresh_result(
        self,
        source: str,
        started_at: datetime,
        status: str,
        rows_written: int,
        error: str | None,
        metric_results: Iterable[dict[str, Any]],
    ) -> None:
        """Persist source and metric refresh states in one transaction."""
        finished_at = datetime.now(timezone.utc)
        metric_rows = [
            (
                str(uuid.uuid4()),
                source,
                result["metric"],
                started_at,
                finished_at,
                result["status"],
                result["rowsWritten"],
                result.get("error"),
            )
            for result in metric_results
        ]
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                connection.execute(
                    """
                    INSERT INTO refresh_runs
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        str(uuid.uuid4()),
                        source,
                        started_at,
                        finished_at,
                        status,
                        rows_written,
                        error,
                    ],
                )
                if metric_rows:
                    connection.executemany(
                        """
                        INSERT INTO metric_refresh_runs
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        metric_rows,
                    )
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise

    def series(self, metric: str, limit: int = 5000) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, metric, observed_at, value, unit, fetched_at, metadata_json
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY observed_at ORDER BY fetched_at DESC
                    ) AS rank
                    FROM observations
                    WHERE metric = ?
                )
                WHERE rank = 1
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                [metric, limit],
            ).fetchall()

        result = [self._observation_row(row) for row in rows]
        result.reverse()
        return result

    def latest_refreshes(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, started_at, finished_at, status, rows_written, error
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY source ORDER BY finished_at DESC
                    ) AS rank
                    FROM refresh_runs
                )
                WHERE rank = 1
                ORDER BY source
                """
            ).fetchall()
        return [
            {
                "source": row[0],
                "startedAt": row[1].isoformat(),
                "finishedAt": row[2].isoformat(),
                "status": row[3],
                "rowsWritten": row[4],
                "error": row[5],
            }
            for row in rows
        ]

    def refresh_history(self, limit: int = 20) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                WITH recent_starts AS (
                    SELECT DISTINCT started_at
                    FROM refresh_runs
                    ORDER BY started_at DESC
                    LIMIT ?
                )
                SELECT source, started_at, finished_at, status, rows_written, error
                FROM refresh_runs
                WHERE started_at IN (SELECT started_at FROM recent_starts)
                ORDER BY started_at DESC, source
                """,
                [limit],
            ).fetchall()
            failure_rows = connection.execute(
                """
                WITH last_ok AS (
                    SELECT source, MAX(finished_at) AS last_ok_at
                    FROM refresh_runs
                    WHERE status = 'ok'
                    GROUP BY source
                ),
                failure_counts AS (
                    SELECT runs.source, COUNT(*) AS failure_count
                    FROM refresh_runs AS runs
                    LEFT JOIN last_ok ON last_ok.source = runs.source
                    WHERE runs.status <> 'ok'
                      AND (
                        last_ok.last_ok_at IS NULL
                        OR runs.finished_at > last_ok.last_ok_at
                      )
                    GROUP BY runs.source
                ),
                latest AS (
                    SELECT source, status, finished_at, error
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY source ORDER BY finished_at DESC
                        ) AS rank
                        FROM refresh_runs
                    )
                    WHERE rank = 1
                )
                SELECT latest.source, failure_counts.failure_count,
                       latest.status, latest.finished_at, latest.error
                FROM latest
                JOIN failure_counts ON failure_counts.source = latest.source
                WHERE failure_counts.failure_count > 0
                ORDER BY failure_counts.failure_count DESC, latest.source
                """
            ).fetchall()

        grouped: dict[datetime, list[tuple[Any, ...]]] = {}
        for row in rows:
            grouped.setdefault(row[1], []).append(row)

        runs = []
        for started_at, source_rows in grouped.items():
            finished_at = max(row[2] for row in source_rows)
            sources = [
                {
                    "source": row[0],
                    "status": row[3],
                    "rowsWritten": row[4],
                    "error": row[5],
                    "finishedAt": row[2].isoformat(),
                }
                for row in source_rows
            ]
            ok_count = sum(item["status"] == "ok" for item in sources)
            failed_count = len(sources) - ok_count
            overall_status = (
                "ok"
                if failed_count == 0
                else "error"
                if ok_count == 0 and all(
                    item["status"] == "error" for item in sources
                )
                else "partial"
            )
            runs.append(
                {
                    "startedAt": started_at.isoformat(),
                    "finishedAt": finished_at.isoformat(),
                    "durationSeconds": round(
                        max(0.0, (finished_at - started_at).total_seconds()), 1
                    ),
                    "status": overall_status,
                    "sourceCount": len(sources),
                    "okCount": ok_count,
                    "failedCount": failed_count,
                    "rowsWritten": sum(item["rowsWritten"] for item in sources),
                    "sources": sources,
                }
            )

        return {
            "runs": runs,
            "consecutiveFailures": [
                {
                    "source": row[0],
                    "count": row[1],
                    "lastStatus": row[2],
                    "lastFinishedAt": row[3].isoformat(),
                    "error": row[4],
                }
                for row in failure_rows
            ],
        }

    def latest_metric_refreshes(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, metric, started_at, finished_at, status, rows_written, error
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY source, metric ORDER BY finished_at DESC
                    ) AS rank
                    FROM metric_refresh_runs
                )
                WHERE rank = 1
                ORDER BY source, metric
                """
            ).fetchall()
        return [
            {
                "source": row[0],
                "metric": row[1],
                "startedAt": row[2].isoformat(),
                "finishedAt": row[3].isoformat(),
                "status": row[4],
                "rowsWritten": row[5],
                "error": row[6],
            }
            for row in rows
        ]

    def metric_summaries(self) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT source, metric, observed_at, unit, fetched_at
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY metric
                        ORDER BY observed_at DESC, fetched_at DESC
                    ) AS rank
                    FROM observations
                )
                WHERE rank = 1
                ORDER BY metric
                """
            ).fetchall()
        return [
            {
                "source": row[0],
                "metric": row[1],
                "observedAt": row[2].isoformat(),
                "unit": row[3],
                "fetchedAt": row[4].isoformat(),
            }
            for row in rows
        ]

    def metric_names(self) -> list[str]:
        with self._lock, self.connect() as connection:
            return [row[0] for row in connection.execute(
                "SELECT DISTINCT metric FROM observations ORDER BY metric"
            ).fetchall()]

    def latest_observed_times(
        self, metrics: Iterable[str]
    ) -> dict[str, datetime]:
        metric_list = list(metrics)
        if not metric_list:
            return {}
        placeholders = ", ".join("?" for _ in metric_list)
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT metric, MAX(observed_at)
                FROM observations
                WHERE metric IN ({placeholders})
                GROUP BY metric
                """,
                metric_list,
            ).fetchall()
        return {row[0]: row[1] for row in rows if row[1] is not None}

    def record_score_snapshot(
        self, overview: dict[str, Any], rule_version: str
    ) -> None:
        observed_at = datetime.fromisoformat(overview["generatedAt"])
        scores = overview.get("scores", {})
        factor_model = overview.get("factorModel", {})
        long_term = factor_model.get("longTerm") or scores.get("environment", {})
        reversal = factor_model.get("reversal") or scores.get("reversal", {})
        confidence = scores.get("confidence", {})
        reversal_coverage = reversal.get("coverage", "0/0")
        if isinstance(reversal_coverage, (int, float)):
            reversal_coverage = f"{round(reversal_coverage)}%"
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO score_snapshots
                (observed_at, environment_score, cycle_score, reversal_score,
                 confidence_score, reversal_coverage, rule_version, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (observed_at) DO UPDATE SET
                    environment_score = excluded.environment_score,
                    cycle_score = excluded.cycle_score,
                    reversal_score = excluded.reversal_score,
                    confidence_score = excluded.confidence_score,
                    reversal_coverage = excluded.reversal_coverage,
                    rule_version = excluded.rule_version,
                    payload_json = excluded.payload_json
                """,
                [
                    observed_at,
                    long_term.get("value"),
                    scores.get("cycle", {}).get("value"),
                    reversal.get("value"),
                    confidence.get("value"),
                    reversal_coverage,
                    rule_version,
                    json.dumps(overview, ensure_ascii=False),
                ],
            )

    def score_history(self, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            rows = connection.execute(
                """
                SELECT observed_at, environment_score, cycle_score,
                       reversal_score, confidence_score, reversal_coverage,
                       rule_version
                FROM score_snapshots
                ORDER BY observed_at DESC
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        result = [
            {
                "observedAt": row[0].isoformat(),
                "environment": row[1],
                "cycle": row[2],
                "reversal": row[3],
                "confidence": row[4],
                "reversalCoverage": row[5],
                "ruleVersion": row[6],
            }
            for row in rows
        ]
        result.reverse()
        return result

    def upsert_cvdd_reference(
        self,
        source_name: str,
        source_url: str,
        observed_date: date,
        value_usd: float,
        note: str | None = None,
    ) -> dict[str, Any]:
        source_name = " ".join(source_name.strip().split())
        source_key = source_name.casefold()
        observed_month = observed_date.replace(day=1)
        recorded_at = datetime.now(timezone.utc)
        entry_id = str(uuid.uuid4())
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO cvdd_reference_entries
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_key, observed_month) DO UPDATE SET
                    source_name = excluded.source_name,
                    source_url = excluded.source_url,
                    observed_date = excluded.observed_date,
                    value_usd = excluded.value_usd,
                    recorded_at = excluded.recorded_at,
                    note = excluded.note
                """,
                [
                    entry_id,
                    source_key,
                    source_name,
                    source_url,
                    observed_date,
                    observed_month,
                    value_usd,
                    recorded_at,
                    note,
                ],
            )
        return {
            "sourceName": source_name,
            "sourceUrl": source_url,
            "observedDate": observed_date.isoformat(),
            "observedMonth": observed_month.isoformat(),
            "valueUsd": value_usd,
            "recordedAt": recorded_at.isoformat(),
            "note": note,
        }

    def cvdd_reference_summary(self, history_limit: int = 36) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            latest_month_row = connection.execute(
                "SELECT MAX(observed_month) FROM cvdd_reference_entries"
            ).fetchone()
            latest_month = latest_month_row[0] if latest_month_row else None
            current_rows = connection.execute(
                """
                SELECT source_name, source_url, observed_date, observed_month,
                       value_usd, recorded_at, note
                FROM cvdd_reference_entries
                WHERE observed_month = ?
                ORDER BY source_name
                """,
                [latest_month],
            ).fetchall() if latest_month else []
            history_rows = connection.execute(
                """
                SELECT source_name, source_url, observed_date, observed_month,
                       value_usd, recorded_at, note
                FROM cvdd_reference_entries
                ORDER BY observed_month DESC, source_name
                LIMIT ?
                """,
                [history_limit],
            ).fetchall()

        def serialize(row: tuple[Any, ...]) -> dict[str, Any]:
            return {
                "sourceName": row[0],
                "sourceUrl": row[1],
                "observedDate": row[2].isoformat(),
                "observedMonth": row[3].isoformat(),
                "valueUsd": float(row[4]),
                "recordedAt": row[5].isoformat(),
                "note": row[6],
            }

        history = [serialize(row) for row in history_rows]
        if not current_rows:
            return {
                "available": False,
                "latestMonth": None,
                "medianValueUsd": None,
                "minimumValueUsd": None,
                "maximumValueUsd": None,
                "spreadPercent": None,
                "sourceCount": 0,
                "latestObservedAt": None,
                "latestRecordedAt": None,
                "nextReviewAt": None,
                "stale": True,
                "agreement": "waiting",
                "sources": [],
                "history": history,
            }

        sources = [serialize(row) for row in current_rows]
        values = [item["valueUsd"] for item in sources]
        median_value = float(statistics.median(values))
        minimum = min(values)
        maximum = max(values)
        spread_percent = (
            (maximum - minimum) / median_value * 100.0 if median_value else None
        )
        latest_observed = max(row[2] for row in current_rows)
        latest_recorded = max(row[5] for row in current_rows)
        next_review = latest_recorded + timedelta(days=30)
        now = datetime.now(timezone.utc)
        observation_age = (now.date() - latest_observed).days
        stale = now > next_review or observation_age > 45
        agreement = (
            "single_source"
            if len(values) == 1
            else "close"
            if spread_percent is not None and spread_percent <= 5
            else "mixed"
            if spread_percent is not None and spread_percent <= 15
            else "divergent"
        )
        return {
            "available": True,
            "latestMonth": latest_month.isoformat(),
            "medianValueUsd": median_value,
            "minimumValueUsd": minimum,
            "maximumValueUsd": maximum,
            "spreadPercent": spread_percent,
            "sourceCount": len(values),
            "latestObservedAt": latest_observed.isoformat(),
            "latestRecordedAt": latest_recorded.isoformat(),
            "nextReviewAt": next_review.isoformat(),
            "stale": stale,
            "agreement": agreement,
            "sources": sources,
            "history": history,
        }

    def archive_to_parquet(self, archive_dir: Path) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc)
        archive_dir = archive_dir.resolve()
        archive_dir.mkdir(parents=True, exist_ok=True)
        files_written = 0
        rows_archived = 0
        error: str | None = None
        status = "ok"

        try:
            with self._lock, self.connect() as connection:
                months = connection.execute(
                    """
                    SELECT DISTINCT
                        EXTRACT(year FROM observed_at)::INTEGER AS year,
                        EXTRACT(month FROM observed_at)::INTEGER AS month
                    FROM observations
                    ORDER BY year, month
                    """
                ).fetchall()
                for year, month in months:
                    target_dir = (
                        archive_dir
                        / "observations"
                        / f"year={year:04d}"
                        / f"month={month:02d}"
                    )
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target = target_dir / "observations.parquet"
                    temporary = target_dir / f".{uuid.uuid4().hex}.parquet.tmp"
                    relation = connection.sql(
                        """
                        SELECT source, metric, observed_at, value, unit,
                               fetched_at, metadata_json
                        FROM observations
                        WHERE EXTRACT(year FROM observed_at) = ?
                          AND EXTRACT(month FROM observed_at) = ?
                        ORDER BY source, metric, observed_at
                        """,
                        params=[year, month],
                    )
                    month_rows = relation.count("*").fetchone()[0]
                    relation.write_parquet(str(temporary), compression="zstd")
                    os.replace(temporary, target)
                    files_written += 1
                    rows_archived += int(month_rows)

                score_target = archive_dir / "scores" / "score_snapshots.parquet"
                score_target.parent.mkdir(parents=True, exist_ok=True)
                score_temporary = score_target.parent / f".{uuid.uuid4().hex}.parquet.tmp"
                score_relation = connection.sql(
                    """
                    SELECT observed_at, environment_score, cycle_score,
                           reversal_score, confidence_score, reversal_coverage,
                           rule_version, payload_json
                    FROM score_snapshots
                    ORDER BY observed_at
                    """
                )
                score_rows = score_relation.count("*").fetchone()[0]
                score_relation.write_parquet(
                    str(score_temporary), compression="zstd"
                )
                os.replace(score_temporary, score_target)
                files_written += 1
                rows_archived += int(score_rows)

                cvdd_rows = connection.execute(
                    "SELECT COUNT(*) FROM cvdd_reference_entries"
                ).fetchone()[0]
                if cvdd_rows:
                    cvdd_target = (
                        archive_dir / "references" / "cvdd_monthly_reference.parquet"
                    )
                    cvdd_target.parent.mkdir(parents=True, exist_ok=True)
                    cvdd_temporary = (
                        cvdd_target.parent / f".{uuid.uuid4().hex}.parquet.tmp"
                    )
                    connection.sql(
                        """
                        SELECT source_name, source_url, observed_date,
                               observed_month, value_usd, recorded_at, note
                        FROM cvdd_reference_entries
                        ORDER BY observed_month, source_name
                        """
                    ).write_parquet(str(cvdd_temporary), compression="zstd")
                    os.replace(cvdd_temporary, cvdd_target)
                    files_written += 1
                    rows_archived += int(cvdd_rows)
        except Exception as exc:
            status = "error"
            error = f"{type(exc).__name__}: {exc}"[:800]

        finished_at = datetime.now(timezone.utc)
        with self._lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO archive_runs
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid.uuid4()),
                    started_at,
                    finished_at,
                    status,
                    files_written,
                    rows_archived,
                    str(archive_dir),
                    error,
                ],
            )
        return {
            "status": status,
            "startedAt": started_at.isoformat(),
            "finishedAt": finished_at.isoformat(),
            "filesWritten": files_written,
            "rowsArchived": rows_archived,
            "path": str(archive_dir),
            "error": error,
        }

    def latest_archive(self) -> dict[str, Any] | None:
        with self._lock, self.connect() as connection:
            row = connection.execute(
                """
                SELECT started_at, finished_at, status, files_written,
                       rows_archived, archive_path, error
                FROM archive_runs
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return {
            "status": row[2],
            "startedAt": row[0].isoformat(),
            "finishedAt": row[1].isoformat(),
            "filesWritten": row[3],
            "rowsArchived": row[4],
            "path": row[5],
            "error": row[6],
        }

    @staticmethod
    def _observation_row(row: tuple[Any, ...]) -> dict[str, Any]:
        try:
            metadata = json.loads(row[6])
        except (TypeError, json.JSONDecodeError):
            metadata = {}
        return {
            "source": row[0],
            "metric": row[1],
            "observedAt": row[2].isoformat(),
            "value": row[3],
            "unit": row[4],
            "fetchedAt": row[5].isoformat(),
            "metadata": metadata,
        }
