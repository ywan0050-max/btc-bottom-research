from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class CoinMetricsCollector:
    source = "coinmetrics_community"
    name = "Coin Metrics Community"
    metrics = ("PriceUSD", "CapMVRVCur")
    source_url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    description = "Coin Metrics Community daily BTC price and on-chain metrics."
    license = "CC BY-NC 4.0"

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        latest = min(
            (watermarks[metric] for metric in self.metrics if metric in watermarks),
            default=None,
        )
        start_time = max(
            datetime(2016, 1, 1, tzinfo=timezone.utc),
            latest - timedelta(days=3) if latest else datetime(2016, 1, 1, tzinfo=timezone.utc),
        )
        params = {
            "assets": "btc",
            "metrics": "PriceUSD,CapMVRVCur",
            "frequency": "1d",
            "start_time": start_time.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            ),
            "page_size": "10000",
        }
        fetched_at = datetime.now(timezone.utc)
        records: list[dict[str, str]] = []

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.source_url, params=params)
            response.raise_for_status()
            payload = response.json()
            records.extend(payload.get("data", []))
            next_url = payload.get("next_page_url")
            page_count = 1
            while next_url and page_count < 5:
                response = await client.get(next_url)
                response.raise_for_status()
                payload = response.json()
                records.extend(payload.get("data", []))
                next_url = payload.get("next_page_url")
                page_count += 1

        points: list[DataPoint] = []
        metric_units = {"PriceUSD": "USD", "CapMVRVCur": "ratio"}
        for record in records:
            observed_at = datetime.fromisoformat(record["time"].replace("Z", "+00:00"))
            for metric, unit in metric_units.items():
                raw_value = record.get(metric)
                if raw_value in (None, ""):
                    continue
                points.append(
                    DataPoint(
                        source=self.source,
                        metric=metric,
                        observed_at=observed_at,
                        value=float(raw_value),
                        unit=unit,
                        fetched_at=fetched_at,
                        metadata={
                            "asset": "btc",
                            "frequency": "1d",
                            "license": "CC BY-NC 4.0",
                            "sourceUrl": self.source_url,
                        },
                    )
                )

        if not points:
            raise RuntimeError("Coin Metrics returned no usable observations.")
        available = {point.metric for point in points}
        metric_errors = {
            metric: "API response contained no usable observations for this metric."
            for metric in self.metrics
            if metric not in available
        }
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
            metric_errors,
        )
