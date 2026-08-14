from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class MempoolSpaceCollector:
    source = "mempool_space"
    name = "mempool.space"
    metrics = ("HashRate", "MiningDifficulty")
    source_url = "https://mempool.space/docs/api/rest"
    api_base = "https://mempool.space/api/v1/mining/hashrate"
    description = (
        "Public Bitcoin network hashrate and difficulty history used for "
        "long-cycle miner stress research."
    )
    license = (
        "Public API backed by Bitcoin network data; mempool project is "
        "open source (AGPL-3.0)"
    )

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        fetched_at = datetime.now(timezone.utc)
        duration = "3m" if all(metric in watermarks for metric in self.metrics) else "all"

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(f"{self.api_base}/{duration}")
            response.raise_for_status()
            payload = response.json()

        points: list[DataPoint] = []
        metric_errors: dict[str, str] = {}
        hash_cutoff = self._cutoff(watermarks.get("HashRate"))
        for record in payload.get("hashrates", []) or []:
            observed_at = self._timestamp(record.get("timestamp"))
            raw_value = record.get("avgHashrate")
            if observed_at is None or raw_value in (None, ""):
                continue
            value = float(raw_value) / 1e18
            if value < 0 or (hash_cutoff and observed_at < hash_cutoff):
                continue
            points.append(
                DataPoint(
                    source=self.source,
                    metric="HashRate",
                    observed_at=observed_at,
                    value=value,
                    unit="EH/s",
                    fetched_at=fetched_at,
                    metadata={
                        "frequency": "daily",
                        "rawUnit": "H/s",
                        "sourceUrl": f"{self.api_base}/{duration}",
                    },
                )
            )

        difficulty_cutoff = self._cutoff(watermarks.get("MiningDifficulty"))
        for record in payload.get("difficulty", []) or []:
            observed_at = self._timestamp(record.get("time"))
            raw_value = record.get("difficulty")
            if observed_at is None or raw_value in (None, ""):
                continue
            value = float(raw_value)
            if value <= 0 or (difficulty_cutoff and observed_at < difficulty_cutoff):
                continue
            points.append(
                DataPoint(
                    source=self.source,
                    metric="MiningDifficulty",
                    observed_at=observed_at,
                    value=value,
                    unit="difficulty",
                    fetched_at=fetched_at,
                    metadata={
                        "frequency": "2016 blocks",
                        "height": record.get("height"),
                        "adjustment": record.get("adjustment"),
                        "sourceUrl": f"{self.api_base}/{duration}",
                    },
                )
            )

        available = {point.metric for point in points}
        for metric in self.metrics:
            if metric not in available:
                metric_errors[metric] = "API response contained no usable observations."
        if not points:
            raise RuntimeError("mempool.space returned no usable mining observations.")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
            metric_errors,
        )

    @staticmethod
    def _timestamp(value: object) -> datetime | None:
        if value in (None, ""):
            return None
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    @staticmethod
    def _cutoff(watermark: datetime | None) -> datetime | None:
        return watermark - timedelta(days=14) if watermark else None
