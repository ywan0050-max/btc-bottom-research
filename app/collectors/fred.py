from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, time, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class FredCollector:
    source = "fred"
    name = "Federal Reserve Economic Data (FRED)"
    source_url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    description = "Federal Reserve Economic Data macro and market series."
    license = "FRED terms of use; underlying series may have separate terms"
    series = {
        "WALCL": ("FedAssets", "million USD", "weekly"),
        "RRPONTSYD": ("OvernightRRP", "billion USD", "business day"),
        "DGS10": ("US10Y", "percent", "business day"),
        "DTWEXBGS": ("BroadDollar", "index", "business day"),
        "NFCI": ("FinancialConditions", "index", "weekly"),
        "BAMLH0A0HYM2": ("HighYieldSpread", "percent", "business day"),
        "DFII10": ("US10YReal", "percent", "business day"),
        "M2SL": ("USM2", "billion USD", "monthly"),
    }
    metrics = tuple(config[0] for config in series.values())

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        fetched_at = datetime.now(timezone.utc)
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            groups = await asyncio.gather(
                *[
                    self._collect_series(
                        client,
                        series_id,
                        config,
                        fetched_at,
                        watermarks.get(config[0]),
                    )
                    for series_id, config in self.series.items()
                ],
                return_exceptions=True,
            )
        points: list[DataPoint] = []
        metric_errors: dict[str, str] = {}
        for (series_id, config), group in zip(self.series.items(), groups, strict=True):
            metric = config[0]
            if isinstance(group, Exception):
                metric_errors[metric] = (
                    f"{series_id}: {type(group).__name__}: {group}"
                )[:800]
                continue
            if not group:
                metric_errors[metric] = f"{series_id}: no usable observations returned."
                continue
            points.extend(group)
        if not points:
            details = "; ".join(metric_errors.values())
            raise RuntimeError(f"FRED returned no usable observations. {details}")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
            metric_errors,
        )

    async def _collect_series(
        self,
        client: httpx.AsyncClient,
        series_id: str,
        config: tuple[str, str, str],
        fetched_at: datetime,
        watermark: datetime | None,
    ) -> list[DataPoint]:
        metric, unit, frequency = config
        overlap_days = 75 if frequency == "monthly" else 21 if frequency == "weekly" else 7
        start_date = max(
            datetime(2016, 1, 1, tzinfo=timezone.utc),
            watermark - timedelta(days=overlap_days)
            if watermark
            else datetime(2016, 1, 1, tzinfo=timezone.utc),
        ).date()
        response = await client.get(
            self.source_url,
            params={"id": series_id, "cosd": start_date.isoformat()},
        )
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))
        points: list[DataPoint] = []
        for row in reader:
            raw_value = row.get(series_id)
            if raw_value in (None, "", "."):
                continue
            observed_date = datetime.strptime(row["observation_date"], "%Y-%m-%d").date()
            points.append(
                DataPoint(
                    source=self.source,
                    metric=metric,
                    observed_at=datetime.combine(observed_date, time.min, tzinfo=timezone.utc),
                    value=float(raw_value),
                    unit=unit,
                    fetched_at=fetched_at,
                    metadata={
                        "seriesId": series_id,
                        "frequency": frequency,
                        "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
                    },
                )
            )
        return points
