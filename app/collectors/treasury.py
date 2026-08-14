from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class TreasuryCollector:
    source = "us_treasury_fiscal_data"
    name = "U.S. Treasury Fiscal Data"
    metrics = ("TGA",)
    source_url = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/"
        "accounting/dts/operating_cash_balance"
    )
    description = "U.S. Treasury Daily Treasury General Account closing balance."
    license = "U.S. government public data"

    async def collect(
        self, watermarks: dict[str, datetime] | None = None
    ) -> CollectorResult:
        watermarks = watermarks or {}
        watermark = watermarks.get("TGA")
        filters = [
            "account_type:eq:Treasury General Account (TGA) Closing Balance"
        ]
        if watermark:
            filters.append(
                f"record_date:gte:{(watermark - timedelta(days=14)).date().isoformat()}"
            )
        params = {
            "filter": ",".join(filters),
            "sort": "-record_date",
            "page[size]": "1500",
        }
        fetched_at = datetime.now(timezone.utc)
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        ) as client:
            response = await client.get(self.source_url, params=params)
            response.raise_for_status()
            records = response.json().get("data", [])

        points: list[DataPoint] = []
        for record in records:
            raw_value = record.get("close_today_bal")
            if raw_value in (None, "null", ""):
                raw_value = record.get("open_today_bal")
            if raw_value in (None, "null", ""):
                continue
            observed_date = datetime.strptime(record["record_date"], "%Y-%m-%d").date()
            points.append(
                DataPoint(
                    source=self.source,
                    metric="TGA",
                    observed_at=datetime.combine(observed_date, time.min, tzinfo=timezone.utc),
                    value=float(str(raw_value).replace(",", "")),
                    unit="million USD",
                    fetched_at=fetched_at,
                    metadata={
                        "frequency": "business day",
                        "accountType": record.get("account_type"),
                        "sourceUrl": self.source_url,
                    },
                )
            )

        if not points:
            raise RuntimeError("Treasury Fiscal Data returned no usable TGA observations.")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
        )
