from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class FearGreedCollector:
    source = "alternative_fear_greed"
    name = "Alternative.me Fear & Greed"
    source_url = "https://api.alternative.me/fng/?limit=0&format=json"
    description = "Alternative.me 加密市场恐惧贪婪指数历史，用作情绪辅助观察。"
    license = "Alternative.me public API; attribution required"
    metrics = ("FearGreedIndex",)

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        fetched_at = datetime.now(timezone.utc)
        watermark = watermarks.get("FearGreedIndex")
        cutoff = watermark - timedelta(days=3) if watermark else None
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.source_url)
            response.raise_for_status()
            payload = response.json()
        records = payload.get("data", []) if isinstance(payload, dict) else []
        points: list[DataPoint] = []
        for item in records:
            try:
                timestamp = int(item["timestamp"])
                value = float(item["value"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= value <= 100:
                continue
            observed_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if cutoff and observed_at < cutoff:
                continue
            points.append(
                DataPoint(
                    source=self.source,
                    metric="FearGreedIndex",
                    observed_at=observed_at,
                    value=value,
                    unit="index 0-100",
                    fetched_at=fetched_at,
                    metadata={
                        "frequency": "daily",
                        "classification": item.get("value_classification"),
                        "sourceUrl": self.source_url,
                    },
                )
            )
        if not points:
            raise RuntimeError("Alternative.me returned no usable Fear & Greed observations.")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
        )
