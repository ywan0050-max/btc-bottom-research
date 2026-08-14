from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class StablecoinsCollector:
    source = "defillama_stablecoins"
    name = "DefiLlama Stablecoins"
    source_url = "https://stablecoins.llama.fi/stablecoincharts/all"
    description = "全链稳定币总流通量历史，用作加密原生流动性辅助观察。"
    license = "DefiLlama API; aggregated public data, subject to DefiLlama terms"
    metrics = ("StablecoinSupplyUSD",)

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        fetched_at = datetime.now(timezone.utc)
        watermark = watermarks.get("StablecoinSupplyUSD")
        cutoff = watermark - timedelta(days=3) if watermark else None
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.source_url)
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("DefiLlama stablecoin response is not a list.")
        points: list[DataPoint] = []
        for item in payload:
            try:
                timestamp = int(item["date"])
                value = float(item["totalCirculatingUSD"]["peggedUSD"])
            except (KeyError, TypeError, ValueError):
                continue
            if value < 0:
                continue
            observed_at = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            if cutoff and observed_at < cutoff:
                continue
            points.append(
                DataPoint(
                    source=self.source,
                    metric="StablecoinSupplyUSD",
                    observed_at=observed_at,
                    value=value,
                    unit="USD",
                    fetched_at=fetched_at,
                    metadata={
                        "frequency": "daily",
                        "scope": "all stablecoins aggregated by DefiLlama",
                        "sourceUrl": self.source_url,
                    },
                )
            )
        if not points:
            raise RuntimeError("DefiLlama returned no usable stablecoin observations.")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
        )
