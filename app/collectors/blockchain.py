from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class BlockchainChartsCollector:
    """Fetch the public daily Coin Days Destroyed chart series.

    The source publishes the raw CDD series, while CVDD is calculated locally
    in analytics.py so the derived value remains reproducible and auditable.
    """

    source = "blockchain_charts"
    name = "Blockchain.com Charts"
    active = False
    retirement_note = (
        "CDD chart endpoints now return 404. Automatic refresh is disabled; "
        "previously cached real observations are retained for audit only."
    )
    metrics = ("CoinDaysDestroyed", "BlockchainPriceUSD")
    source_url = "https://www.blockchain.com/explorer/charts"
    api_base = "https://api.blockchain.info/charts"
    charts = {
        "CoinDaysDestroyed": (("coindaysdestroyed", "bitcoin-days-destroyed"), "coin-days"),
        "BlockchainPriceUSD": ("market-price", "USD"),
    }
    description = "Public Bitcoin Days Destroyed and market-price chart series."
    license = "Blockchain.com public chart API; verify current terms before redistribution"

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
                *(
                    self._collect_chart(
                        client,
                        metric,
                        chart_name,
                        unit,
                        fetched_at,
                        watermarks.get(metric),
                    )
                    for metric, (chart_name, unit) in self.charts.items()
                ),
                return_exceptions=True,
            )

        points: list[DataPoint] = []
        metric_errors: dict[str, str] = {}
        for metric, group in zip(self.charts, groups, strict=True):
            if isinstance(group, Exception):
                metric_errors[metric] = f"{type(group).__name__}: {group}"[:800]
            elif group:
                points.extend(group)
            else:
                metric_errors[metric] = "Chart API returned no usable observations."

        if not points:
            details = "; ".join(
                f"{metric}: {error}" for metric, error in metric_errors.items()
            )
            raise RuntimeError(f"Blockchain.com Charts returned no usable data. {details}")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
            metric_errors,
        )

    async def _collect_chart(
        self,
        client: httpx.AsyncClient,
        metric: str,
        chart_name: str | tuple[str, ...],
        unit: str,
        fetched_at: datetime,
        watermark: datetime | None,
    ) -> list[DataPoint]:
        start_date = max(
            date(2009, 1, 1),
            (watermark - timedelta(days=14)).date()
            if watermark
            else date(2009, 1, 1),
        )
        chart_names = (chart_name,) if isinstance(chart_name, str) else chart_name
        payload: dict[str, Any] | None = None
        selected_chart = chart_names[0]
        last_error: Exception | None = None
        for candidate in chart_names:
            try:
                response = await client.get(
                    f"{self.api_base}/{candidate}",
                    params={
                        "start": start_date.isoformat(),
                        "end": fetched_at.date().isoformat(),
                        "format": "json",
                        "sampled": "false",
                    },
                )
                response.raise_for_status()
                candidate_payload = response.json()
                if candidate_payload.get("values"):
                    payload = candidate_payload
                    selected_chart = candidate
                    break
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
        if payload is None:
            if last_error:
                raise last_error
            return []
        points: list[DataPoint] = []
        for record in payload.get("values", []) or []:
            raw_value = record.get("y")
            raw_timestamp = record.get("x")
            if raw_value in (None, "") or raw_timestamp in (None, ""):
                continue
            observed_date = datetime.fromtimestamp(
                float(raw_timestamp), tz=timezone.utc
            ).date()
            points.append(
                DataPoint(
                    source=self.source,
                    metric=metric,
                    observed_at=datetime.combine(
                        observed_date, time.min, tzinfo=timezone.utc
                    ),
                    value=float(raw_value),
                    unit=unit,
                    fetched_at=fetched_at,
                    metadata={
                        "asset": "btc",
                        "frequency": "daily",
                        "sourceUrl": f"{self.api_base}/{selected_chart}",
                        "chartName": selected_chart,
                    },
                )
            )

        return points
