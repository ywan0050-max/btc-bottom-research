from __future__ import annotations

import asyncio
import copy
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from .analytics import build_overview
from .collectors import (
    BlockchainChartsCollector,
    CoinMetricsCollector,
    DeribitCollector,
    FearGreedCollector,
    FredCollector,
    MempoolSpaceCollector,
    StablecoinsCollector,
    TreasuryCollector,
)
from .config import (
    ARCHIVE_SECONDS,
    COLLECTOR_TIMEOUT_SECONDS,
    ENABLE_DERIBIT,
    FAST_REFRESH_SECONDS,
    PARQUET_DIR,
    SLOW_REFRESH_SECONDS,
)
from .db import Database


class ResearchService:
    score_rule_version = "2026-08-factor-experiment-v2"

    def __init__(self, database: Database) -> None:
        self.database = database
        self.source_catalog = [
            CoinMetricsCollector(),
            BlockchainChartsCollector(),
            MempoolSpaceCollector(),
            TreasuryCollector(),
            FredCollector(),
            StablecoinsCollector(),
            FearGreedCollector(),
            DeribitCollector(),
        ]
        self.collectors = [
            collector
            for collector in self.source_catalog
            if getattr(collector, "active", True)
            and (collector.source != "deribit_public" or ENABLE_DERIBIT)
        ]
        self._refresh_lock = asyncio.Lock()
        self._archive_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task[dict[str, Any]] | None = None
        self._metric_names: set[str] = set()
        self._overview_lock = threading.RLock()
        self._overview_cache: dict[str, Any] | None = None
        self._overview_cached_at: datetime | None = None
        self._overview_cache_error: str | None = None
        self._state: dict[str, Any] = {
            "status": "idle",
            "startedAt": None,
            "finishedAt": None,
            "sources": {},
            "trigger": None,
            "scope": [],
        }
        self._archive_state: dict[str, Any] = {
            "status": "idle",
            "startedAt": None,
            "finishedAt": None,
            "filesWritten": 0,
            "rowsArchived": 0,
            "path": str(PARQUET_DIR),
            "error": None,
        }
        self._scheduler_state: dict[str, Any] = {
            "status": "idle",
            "fastIntervalSeconds": FAST_REFRESH_SECONDS if ENABLE_DERIBIT else None,
            "slowIntervalSeconds": SLOW_REFRESH_SECONDS,
            "archiveIntervalSeconds": ARCHIVE_SECONDS,
            "nextFastAt": None,
            "nextSlowAt": None,
            "nextArchiveAt": None,
            "lastFastAt": None,
            "lastSlowAt": None,
        }

    @property
    def refresh_state(self) -> dict[str, Any]:
        return self._state

    @property
    def archive_state(self) -> dict[str, Any]:
        return self._archive_state

    @property
    def scheduler_state(self) -> dict[str, Any]:
        return self._scheduler_state

    @property
    def metric_names(self) -> list[str]:
        return sorted(self._metric_names)

    def load_metric_names(self) -> None:
        self._metric_names = set(self.database.metric_names())

    @property
    def overview_cache_state(self) -> dict[str, Any]:
        with self._overview_lock:
            cached = self._overview_cache is not None
            cached_at = self._overview_cached_at
            error = self._overview_cache_error
            generated_at = (
                self._overview_cache.get("generatedAt")
                if self._overview_cache is not None
                else None
            )
        if cached and error:
            cache_status = "degraded"
        elif cached:
            cache_status = "ready"
        elif error:
            cache_status = "error"
        else:
            cache_status = "empty"
        return {
            "status": cache_status,
            "generatedAt": generated_at,
            "cachedAt": cached_at.isoformat() if cached_at else None,
            "ageSeconds": (
                round(
                    max(
                        0.0,
                        (datetime.now(timezone.utc) - cached_at).total_seconds(),
                    ),
                    1,
                )
                if cached_at
                else None
            ),
            "error": error,
        }

    def refresh_overview_cache(
        self, refresh_state: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            overview = build_overview(
                self.database,
                copy.deepcopy(refresh_state if refresh_state is not None else self._state),
            )
        except Exception as exc:
            with self._overview_lock:
                self._overview_cache_error = self._error_text(exc)
            raise
        with self._overview_lock:
            self._overview_cache = overview
            self._overview_cached_at = datetime.now(timezone.utc)
            self._overview_cache_error = None
        return overview

    @staticmethod
    def _error_text(exc: BaseException) -> str:
        return f"{type(exc).__name__}: {exc}"[:800]

    @staticmethod
    def _pending_sources(collectors: list[Any], status: str) -> dict[str, Any]:
        return {
            collector.source: {
                "name": getattr(collector, "name", collector.source),
                "status": status,
                "rowsWritten": 0,
                "error": None,
                "finishedAt": None,
            }
            for collector in collectors
        }

    async def _collect_with_timeout(
        self, collector: Any, watermarks: dict[str, datetime]
    ) -> tuple[Any, Any]:
        try:
            async with asyncio.timeout(COLLECTOR_TIMEOUT_SECONDS):
                return collector, await collector.collect(watermarks)
        except TimeoutError as exc:
            return collector, TimeoutError(
                f"Collector exceeded {COLLECTOR_TIMEOUT_SECONDS:g} seconds."
            )
        except Exception as exc:
            return collector, exc

    async def _record_failed_source(
        self,
        collector: Any,
        started_at: datetime,
        exc: BaseException,
    ) -> None:
        error = self._error_text(exc)
        metric_states = [
            {
                "metric": metric,
                "status": "error",
                "rowsWritten": 0,
                "error": error,
            }
            for metric in collector.metrics
        ]
        await asyncio.to_thread(
            self.database.record_refresh_result,
            collector.source,
            started_at,
            "error",
            0,
            error,
            metric_states,
        )
        self._state["sources"][collector.source] = {
            "name": getattr(collector, "name", collector.source),
            "status": "error",
            "rowsWritten": 0,
            "error": error,
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "metrics": {state["metric"]: state for state in metric_states},
        }

    def start_refresh(self) -> bool:
        if self._refresh_lock.locked():
            return False
        if self._refresh_task is not None and not self._refresh_task.done():
            return False
        self._state = {
            "status": "queued",
            "startedAt": None,
            "finishedAt": None,
            "sources": self._pending_sources(self.collectors, "pending"),
            "trigger": "manual",
            "scope": [collector.source for collector in self.collectors],
        }
        self._refresh_task = asyncio.create_task(
            self.refresh(self.collectors, trigger="manual")
        )
        return True

    async def refresh(
        self,
        collectors: list[Any] | None = None,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        if self._refresh_lock.locked():
            return self._state

        selected_collectors = collectors or self.collectors
        async with self._refresh_lock:
            started_at = datetime.now(timezone.utc)
            self._state = {
                "status": "running",
                "startedAt": started_at.isoformat(),
                "finishedAt": None,
                "sources": self._pending_sources(selected_collectors, "running"),
                "trigger": trigger,
                "scope": [collector.source for collector in selected_collectors],
            }

            watermarks = await asyncio.gather(
                *(
                    asyncio.to_thread(
                        self.database.latest_observed_times, collector.metrics
                    )
                    for collector in selected_collectors
                )
            )
            tasks = [
                asyncio.create_task(
                    self._collect_with_timeout(collector, metric_watermarks)
                )
                for collector, metric_watermarks in zip(
                    selected_collectors, watermarks, strict=True
                )
            ]
            any_success = False
            for task in asyncio.as_completed(tasks):
                collector, result = await task
                if isinstance(result, Exception):
                    await self._record_failed_source(collector, started_at, result)
                    continue

                try:
                    rows_by_metric = await asyncio.to_thread(
                        self.database.replace_series_counts, result.points
                    )
                    rows_written = sum(rows_by_metric.values())
                    self._metric_names.update(point.metric for point in result.points)
                except Exception as exc:
                    error = self._error_text(exc)
                    metric_states = [
                        {
                            "metric": metric,
                            "status": "error",
                            "rowsWritten": 0,
                            "error": error,
                        }
                        for metric in result.expected_metrics
                    ]
                    await asyncio.to_thread(
                        self.database.record_refresh_result,
                        collector.source,
                        started_at,
                        "error",
                        0,
                        error,
                        metric_states,
                    )
                    self._state["sources"][collector.source] = {
                        "name": getattr(collector, "name", collector.source),
                        "status": "error",
                        "rowsWritten": 0,
                        "error": error,
                        "finishedAt": datetime.now(timezone.utc).isoformat(),
                        "metrics": {
                            state["metric"]: state for state in metric_states
                        },
                    }
                    continue

                metric_states = []
                for metric in result.expected_metrics:
                    metric_error = result.metric_errors.get(metric)
                    metric_states.append(
                        {
                            "metric": metric,
                            "status": "error" if metric_error else "ok",
                            "rowsWritten": rows_by_metric.get(metric, 0),
                            "error": metric_error,
                        }
                    )
                source_status = "partial" if result.metric_errors else "ok"
                source_error = (
                    "; ".join(result.metric_errors.values())[:800]
                    if result.metric_errors
                    else None
                )
                any_success = True
                await asyncio.to_thread(
                    self.database.record_refresh_result,
                    collector.source,
                    started_at,
                    source_status,
                    rows_written,
                    source_error,
                    metric_states,
                )
                self._state["sources"][collector.source] = {
                    "name": getattr(collector, "name", collector.source),
                    "status": source_status,
                    "rowsWritten": rows_written,
                    "error": source_error,
                    "finishedAt": datetime.now(timezone.utc).isoformat(),
                    "metrics": {
                        state["metric"]: state for state in metric_states
                    },
                }

            finished_at = datetime.now(timezone.utc)
            source_states = self._state["sources"].values()
            has_errors = any(source["status"] != "ok" for source in source_states)
            final_state = {
                **self._state,
                "status": (
                    "partial"
                    if any_success and has_errors
                    else "ok"
                    if any_success
                    else "error"
                ),
                "finishedAt": finished_at.isoformat(),
            }
            overview = None
            try:
                overview = await asyncio.to_thread(
                    self.refresh_overview_cache, final_state
                )
            except Exception:
                # Keep the previous valid cache; health exposes the cache error.
                pass
            try:
                if any_success and overview is not None:
                    await asyncio.to_thread(
                        self.database.record_score_snapshot,
                        overview,
                        self.score_rule_version,
                    )
            finally:
                self._state = final_state
            return self._state

    async def archive(self) -> dict[str, Any]:
        if self._archive_lock.locked():
            return self._archive_state
        async with self._archive_lock:
            self._archive_state = {
                **self._archive_state,
                "status": "running",
                "startedAt": datetime.now(timezone.utc).isoformat(),
                "finishedAt": None,
                "error": None,
            }
            self._archive_state = await asyncio.to_thread(
                self.database.archive_to_parquet, PARQUET_DIR
            )
            return self._archive_state

    async def scheduler(self) -> None:
        fast_collectors = [
            collector
            for collector in self.collectors
            if collector.source == "deribit_public"
        ]
        self._scheduler_state["status"] = "starting"
        try:
            await self.refresh(self.collectors, trigger="startup")
            await self.archive()
            now = datetime.now(timezone.utc)
            next_fast = (
                now + timedelta(seconds=FAST_REFRESH_SECONDS)
                if fast_collectors
                else None
            )
            next_slow = now + timedelta(seconds=SLOW_REFRESH_SECONDS)
            next_archive = now + timedelta(seconds=ARCHIVE_SECONDS)
            self._scheduler_state.update(
                {
                    "status": "running",
                    "lastFastAt": self._state.get("finishedAt"),
                    "lastSlowAt": self._state.get("finishedAt"),
                }
            )

            while True:
                self._scheduler_state.update(
                    {
                        "nextFastAt": next_fast.isoformat() if next_fast else None,
                        "nextSlowAt": next_slow.isoformat(),
                        "nextArchiveAt": next_archive.isoformat(),
                    }
                )
                now = datetime.now(timezone.utc)
                next_due = min(
                    item for item in (next_fast, next_slow, next_archive) if item
                )
                await asyncio.sleep(
                    max(1.0, min(30.0, (next_due - now).total_seconds()))
                )
                now = datetime.now(timezone.utc)

                if now >= next_slow:
                    await self.refresh(
                        self.collectors, trigger="scheduled_slow"
                    )
                    completed = datetime.now(timezone.utc)
                    self._scheduler_state["lastSlowAt"] = self._state.get(
                        "finishedAt"
                    )
                    self._scheduler_state["lastFastAt"] = self._state.get(
                        "finishedAt"
                    )
                    next_slow = completed + timedelta(
                        seconds=SLOW_REFRESH_SECONDS
                    )
                    if next_fast:
                        next_fast = completed + timedelta(
                            seconds=FAST_REFRESH_SECONDS
                        )
                elif next_fast and now >= next_fast:
                    await self.refresh(
                        fast_collectors, trigger="scheduled_fast"
                    )
                    completed = datetime.now(timezone.utc)
                    self._scheduler_state["lastFastAt"] = self._state.get(
                        "finishedAt"
                    )
                    next_fast = completed + timedelta(
                        seconds=FAST_REFRESH_SECONDS
                    )

                if now >= next_archive:
                    if not self._refresh_lock.locked():
                        await self.archive()
                        next_archive = datetime.now(timezone.utc) + timedelta(
                            seconds=ARCHIVE_SECONDS
                        )
                    else:
                        next_archive = now + timedelta(minutes=1)
        except asyncio.CancelledError:
            self._scheduler_state["status"] = "stopped"
            raise
        except Exception as exc:
            self._scheduler_state["status"] = "error"
            self._scheduler_state["error"] = self._error_text(exc)
            self._state["status"] = "error"
            self._state["finishedAt"] = datetime.now(timezone.utc).isoformat()
            raise

    def overview(self) -> dict[str, Any]:
        with self._overview_lock:
            cached = self._overview_cache
        if cached is not None:
            return cached
        return self.refresh_overview_cache()

    def refresh_history(self, limit: int = 20) -> dict[str, Any]:
        history = self.database.refresh_history(limit)
        enabled_sources = {collector.source for collector in self.collectors}
        history["consecutiveFailures"] = [
            item
            for item in history["consecutiveFailures"]
            if item["source"] in enabled_sources
        ]
        return history

    def score_history(self, limit: int) -> list[dict[str, Any]]:
        return self.database.score_history(limit)

    def cvdd_references(self) -> dict[str, Any]:
        return self.database.cvdd_reference_summary()

    def add_cvdd_reference(
        self,
        source_name: str,
        source_url: str,
        observed_date: Any,
        value_usd: float,
        note: str | None,
    ) -> dict[str, Any]:
        entry = self.database.upsert_cvdd_reference(
            source_name,
            source_url,
            observed_date,
            value_usd,
            note,
        )
        return {"entry": entry, "summary": self.cvdd_references()}

    def sources(self) -> list[dict[str, Any]]:
        latest_runs = {
            run["source"]: run for run in self.database.latest_refreshes()
        }
        metric_runs = self.database.latest_metric_refreshes()
        metric_summaries = {
            summary["metric"]: summary
            for summary in self.database.metric_summaries()
        }
        runs_by_source: dict[str, list[dict[str, Any]]] = {}
        for metric_run in metric_runs:
            runs_by_source.setdefault(metric_run["source"], []).append(metric_run)

        result = []
        for collector in self.source_catalog:
            latest_refresh = latest_runs.get(collector.source)
            active = getattr(collector, "active", True)
            enabled = collector in self.collectors
            if not active:
                latest_refresh = {
                    **(latest_refresh or {}),
                    "status": "retired",
                    "error": getattr(collector, "retirement_note", None),
                }
            elif not enabled:
                latest_refresh = {
                    **(latest_refresh or {}),
                    "status": "paused",
                    "error": (
                        "Macro mode pauses Deribit automatic refresh. Set "
                        "BTC_RESEARCH_ENABLE_DERIBIT=1 to enable it."
                    ),
                }
            result.append(
                {
                    "id": collector.source,
                    "name": collector.name,
                    "url": collector.source_url,
                    "description": collector.description,
                    "license": collector.license,
                    "active": active,
                    "enabled": enabled,
                    "note": getattr(collector, "retirement_note", None),
                    "metrics": [
                        {
                            "metric": metric,
                            "latestObservation": metric_summaries.get(metric),
                            "refresh": next(
                                (
                                    item
                                    for item in runs_by_source.get(collector.source, [])
                                    if item["metric"] == metric
                                ),
                                None,
                            ),
                        }
                        for metric in collector.metrics
                    ],
                    "refresh": latest_refresh,
                }
            )
        return result
