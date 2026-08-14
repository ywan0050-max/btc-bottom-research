from __future__ import annotations

import asyncio
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..config import HTTP_TIMEOUT_SECONDS, USER_AGENT
from ..models import CollectorResult, DataPoint


class DeribitCollector:
    source = "deribit_public"
    name = "Deribit Public API"
    option_metrics = (
        "ATMIV7D",
        "ATMIV30D",
        "ATMIV90D",
        "RR25_7D",
        "RR25_30D",
        "RR25_90D",
        "BF25_30D",
        "IVTermSlope7D30D",
        "IVTermSlope30D90D",
    )
    metrics = (
        "FundingRate8h",
        "OpenInterestUSD",
        "TradeCVDUSD",
        "OrderBookImbalance25bps",
        *option_metrics,
    )
    source_url = "https://docs.deribit.com/"
    api_url = "https://www.deribit.com/api/v2/public"
    description = (
        "Deribit BTC perpetual funding, open interest, taker flow, fixed-bps "
        "order-book depth, and BTC option volatility surface."
    )
    license = "Deribit public market data; subject to Deribit terms of service"
    instrument = "BTC-PERPETUAL"
    group_timeout_seconds = 20.0

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
            task_specs = (
                (
                    ("FundingRate8h",),
                    self._funding_history(
                        client, fetched_at, watermarks.get("FundingRate8h")
                    ),
                ),
                (("OpenInterestUSD",), self._open_interest(client, fetched_at)),
                (("TradeCVDUSD",), self._recent_cvd(client, fetched_at)),
                (("OrderBookImbalance25bps",), self._order_book(client, fetched_at)),
                (self.option_metrics, self._option_surface(client, fetched_at)),
            )
            groups = await asyncio.gather(
                *(self._bounded_group(spec[1]) for spec in task_specs),
                return_exceptions=True,
            )

        points: list[DataPoint] = []
        metric_errors: dict[str, str] = {}
        for (expected_metrics, _), group in zip(task_specs, groups, strict=True):
            if isinstance(group, Exception):
                error = f"{type(group).__name__}: {group}"[:800]
                metric_errors.update(
                    {metric: error for metric in expected_metrics}
                )
                continue
            if not group:
                metric_errors.update(
                    {
                        metric: "No usable observations returned."
                        for metric in expected_metrics
                    }
                )
                continue
            points.extend(group)
            available = {point.metric for point in group}
            for metric in expected_metrics:
                if metric not in available:
                    metric_errors[metric] = "No usable observation was derived."

        if not points:
            details = "; ".join(
                f"{metric}: {error}" for metric, error in metric_errors.items()
            )
            raise RuntimeError(f"Deribit returned no usable observations. {details}")
        return CollectorResult(
            self.source,
            points,
            self.source_url,
            self.description,
            self.metrics,
            metric_errors,
        )

    async def _bounded_group(self, coroutine: Any) -> Any:
        try:
            async with asyncio.timeout(self.group_timeout_seconds):
                return await coroutine
        except TimeoutError as exc:
            raise TimeoutError(
                f"Deribit metric group exceeded {self.group_timeout_seconds:g} seconds."
            ) from exc

    async def _funding_history(
        self,
        client: httpx.AsyncClient,
        fetched_at: datetime,
        watermark: datetime | None = None,
    ) -> list[DataPoint]:
        end = fetched_at
        start = (
            max(end - timedelta(days=45), watermark - timedelta(hours=2))
            if watermark
            else end - timedelta(days=45)
        )
        payload = await self._get_result(
            client,
            "get_funding_rate_history",
            {
                "instrument_name": self.instrument,
                "start_timestamp": int(start.timestamp() * 1000),
                "end_timestamp": int(end.timestamp() * 1000),
            },
        )
        if not isinstance(payload, list):
            raise RuntimeError("Funding history result is not a list.")

        points = []
        for item in payload:
            raw_value = item.get("interest_8h")
            timestamp = item.get("timestamp")
            if raw_value is None or timestamp is None:
                continue
            points.append(
                DataPoint(
                    source=self.source,
                    metric="FundingRate8h",
                    observed_at=self._from_milliseconds(timestamp),
                    value=float(raw_value) * 100.0,
                    unit="percent per 8h",
                    fetched_at=fetched_at,
                    metadata={
                        "instrument": self.instrument,
                        "frequency": "hourly",
                        "rateBasis": "8h",
                        "indexPrice": item.get("index_price"),
                        "sourceUrl": f"{self.api_url}/get_funding_rate_history",
                    },
                )
            )
        return points

    async def _open_interest(
        self,
        client: httpx.AsyncClient,
        fetched_at: datetime,
    ) -> list[DataPoint]:
        payload = await self._get_result(
            client,
            "get_book_summary_by_instrument",
            {"instrument_name": self.instrument},
        )
        if not isinstance(payload, list) or not payload:
            raise RuntimeError("Book summary result is empty.")
        item = payload[0]
        raw_value = item.get("open_interest")
        timestamp = item.get("creation_timestamp")
        if raw_value is None or timestamp is None:
            raise RuntimeError("Book summary omitted open interest or timestamp.")
        return [
            DataPoint(
                source=self.source,
                metric="OpenInterestUSD",
                observed_at=self._from_milliseconds(timestamp),
                value=float(raw_value),
                unit="USD",
                fetched_at=fetched_at,
                metadata={
                    "instrument": self.instrument,
                    "instrumentType": "reversed perpetual",
                    "frequency": "snapshot",
                    "amountBasis": "Deribit USD amount units for perpetuals",
                    "rawOpenInterest": float(raw_value),
                    "timestampSource": "creation_timestamp (summary observation time)",
                    "schemaVersion": "deribit-open-interest-v2",
                    "indexPrice": item.get("index_price"),
                    "markPrice": item.get("mark_price"),
                    "volume24hUsd": item.get("volume_usd"),
                    "sourceUrl": f"{self.api_url}/get_book_summary_by_instrument",
                },
            )
        ]

    async def _recent_cvd(
        self,
        client: httpx.AsyncClient,
        fetched_at: datetime,
    ) -> list[DataPoint]:
        payload = await self._get_result(
            client,
            "get_last_trades_by_instrument",
            {
                "instrument_name": self.instrument,
                "count": 1000,
                "sorting": "desc",
            },
        )
        trades = payload.get("trades", []) if isinstance(payload, dict) else []
        usable = [
            trade
            for trade in trades
            if trade.get("timestamp") is not None
            and trade.get("amount") is not None
            and trade.get("direction") in {"buy", "sell"}
        ]
        if not usable:
            raise RuntimeError("Recent trades result contained no directional trades.")

        buy_volume = sum(
            float(trade["amount"])
            for trade in usable
            if trade["direction"] == "buy"
        )
        sell_volume = sum(
            float(trade["amount"])
            for trade in usable
            if trade["direction"] == "sell"
        )
        total_volume = buy_volume + sell_volume
        if total_volume <= 0:
            raise RuntimeError("Recent directional trade volume is zero.")
        timestamps = [int(trade["timestamp"]) for trade in usable]
        imbalance = (buy_volume - sell_volume) / total_volume * 100.0
        window_start = self._from_milliseconds(min(timestamps))
        window_end = self._from_milliseconds(max(timestamps))
        return [
            DataPoint(
                source=self.source,
                metric="TradeCVDUSD",
                observed_at=window_end,
                value=buy_volume - sell_volume,
                unit="USD",
                fetched_at=fetched_at,
                metadata={
                    "instrument": self.instrument,
                    "frequency": "snapshot",
                    "tradeCount": len(usable),
                    "buyVolumeUsd": buy_volume,
                    "sellVolumeUsd": sell_volume,
                    "imbalancePct": imbalance,
                    "windowStart": window_start.isoformat(),
                    "windowEnd": window_end.isoformat(),
                    "windowMinutes": (window_end - window_start).total_seconds() / 60.0,
                    "scope": "most recent 1000 Deribit trades",
                    "sourceUrl": f"{self.api_url}/get_last_trades_by_instrument",
                },
            )
        ]

    async def _order_book(
        self,
        client: httpx.AsyncClient,
        fetched_at: datetime,
    ) -> list[DataPoint]:
        payload = await self._get_result(
            client,
            "get_order_book",
            {"instrument_name": self.instrument, "depth": 1000},
        )
        if not isinstance(payload, dict):
            raise RuntimeError("Order book result is not an object.")
        bids = payload.get("bids", [])
        asks = payload.get("asks", [])
        if not bids or not asks or payload.get("timestamp") is None:
            raise RuntimeError("Order book omitted bids, asks, or timestamp.")
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        midpoint = (best_bid + best_ask) / 2.0
        depth_bands: dict[str, dict[str, float | None]] = {}
        for band_bps in (10, 25, 50, 100):
            minimum_bid = midpoint * (1.0 - band_bps / 10000.0)
            maximum_ask = midpoint * (1.0 + band_bps / 10000.0)
            bid_depth = sum(
                float(level[1])
                for level in bids
                if float(level[0]) >= minimum_bid
            )
            ask_depth = sum(
                float(level[1])
                for level in asks
                if float(level[0]) <= maximum_ask
            )
            total_depth = bid_depth + ask_depth
            imbalance = (
                (bid_depth - ask_depth) / total_depth * 100.0
                if total_depth > 0
                else None
            )
            depth_bands[str(band_bps)] = {
                "bidDepthUsd": bid_depth,
                "askDepthUsd": ask_depth,
                "imbalancePct": imbalance,
            }
        primary = depth_bands["25"]
        if primary["imbalancePct"] is None:
            raise RuntimeError("Order book depth within 25 bps is zero.")
        top_50_bids = sum(float(level[1]) for level in bids[:50])
        top_50_asks = sum(float(level[1]) for level in asks[:50])
        return [
            DataPoint(
                source=self.source,
                metric="OrderBookImbalance25bps",
                observed_at=self._from_milliseconds(payload["timestamp"]),
                value=float(primary["imbalancePct"]),
                unit="percent",
                fetched_at=fetched_at,
                metadata={
                    "instrument": self.instrument,
                    "frequency": "snapshot",
                    "depthLevels": min(len(bids), len(asks)),
                    "depthBasisBps": 25,
                    "bidDepthUsd": primary["bidDepthUsd"],
                    "askDepthUsd": primary["askDepthUsd"],
                    "depthBands": depth_bands,
                    "top50BidDepthUsd": top_50_bids,
                    "top50AskDepthUsd": top_50_asks,
                    "bestBid": best_bid,
                    "bestAsk": best_ask,
                    "midpoint": midpoint,
                    "markPrice": payload.get("mark_price"),
                    "spreadBps": (best_ask - best_bid) / midpoint * 10000.0,
                    "scope": "resting depth within fixed distance of midpoint",
                    "sourceUrl": f"{self.api_url}/get_order_book",
                },
            )
        ]

    async def _option_surface(
        self,
        client: httpx.AsyncClient,
        fetched_at: datetime,
    ) -> list[DataPoint]:
        summaries, instruments = await asyncio.gather(
            self._get_result(
                client,
                "get_book_summary_by_currency",
                {"currency": "BTC", "kind": "option"},
            ),
            self._get_result(
                client,
                "get_instruments",
                {"currency": "BTC", "kind": "option", "expired": "false"},
            ),
        )
        if not isinstance(summaries, list) or not isinstance(instruments, list):
            raise RuntimeError("Option surface response is not a list.")

        instrument_by_name = {
            item.get("instrument_name"): item
            for item in instruments
            if item.get("instrument_name")
        }
        by_expiry: dict[int, list[dict[str, Any]]] = {}
        for summary in summaries:
            instrument = instrument_by_name.get(summary.get("instrument_name"))
            if not instrument:
                continue
            try:
                expiration_ms = int(instrument["expiration_timestamp"])
                expiration = self._from_milliseconds(expiration_ms)
                years = (expiration - fetched_at).total_seconds() / (365.0 * 86400.0)
                forward = float(summary["underlying_price"])
                strike = float(instrument["strike"])
                iv = float(summary["mark_iv"])
                option_type = str(instrument["option_type"])
                open_interest = float(summary.get("open_interest") or 0.0)
                bid_price = float(summary.get("bid_price") or 0.0)
                ask_price = float(summary.get("ask_price") or 0.0)
            except (KeyError, TypeError, ValueError):
                continue
            if (
                years <= 1.0 / 365.0
                or forward <= 0
                or strike <= 0
                or iv <= 0
                or not self._usable_option_quote(open_interest, bid_price, ask_price)
            ):
                continue
            quote_mid = (bid_price + ask_price) / 2.0
            delta = self._black_forward_delta(
                forward, strike, iv, years, option_type
            )
            if delta is None:
                continue
            by_expiry.setdefault(expiration_ms, []).append(
                {
                    "instrument": summary.get("instrument_name"),
                    "expiration": expiration,
                    "forward": forward,
                    "strike": strike,
                    "iv": iv,
                    "optionType": option_type,
                    "delta": delta,
                    "openInterest": summary.get("open_interest"),
                    "bidPrice": bid_price,
                    "askPrice": ask_price,
                    "relativeSpread": (ask_price - bid_price) / quote_mid,
                }
            )

        expiry_surfaces: list[dict[str, Any]] = []
        for expiration_ms, records in sorted(by_expiry.items()):
            surface = self._surface_for_expiry(records, fetched_at)
            if surface:
                surface["expirationMs"] = expiration_ms
                expiry_surfaces.append(surface)
        if len(expiry_surfaces) < 2:
            raise RuntimeError("Too few usable option expiries for fixed-tenor interpolation.")

        fixed: dict[int, dict[str, Any]] = {}
        for days in (7, 30, 90):
            interpolated = self._fixed_tenor_surface(expiry_surfaces, days)
            if interpolated:
                fixed[days] = interpolated

        points: list[DataPoint] = []
        for days, surface in fixed.items():
            common_metadata = {
                "frequency": "snapshot",
                "currency": "BTC",
                "targetDays": days,
                "interpolation": "total variance between bracketing expiries",
                "lowerExpiry": surface["lowerExpiry"],
                "upperExpiry": surface["upperExpiry"],
                "sourceUrl": f"{self.api_url}/get_book_summary_by_currency",
            }
            points.extend(
                [
                    DataPoint(
                        source=self.source,
                        metric=f"ATMIV{days}D",
                        observed_at=fetched_at,
                        value=surface["atmIv"],
                        unit="annualized percent",
                        fetched_at=fetched_at,
                        metadata={**common_metadata, "surfacePoint": "ATM"},
                    ),
                    DataPoint(
                        source=self.source,
                        metric=f"RR25_{days}D",
                        observed_at=fetched_at,
                        value=surface["call25Iv"] - surface["put25Iv"],
                        unit="volatility points",
                        fetched_at=fetched_at,
                        metadata={
                            **common_metadata,
                            "definition": "25-delta call IV minus 25-delta put IV",
                            "call25Iv": surface["call25Iv"],
                            "put25Iv": surface["put25Iv"],
                        },
                    ),
                ]
            )
            if days == 30:
                points.append(
                    DataPoint(
                        source=self.source,
                        metric="BF25_30D",
                        observed_at=fetched_at,
                        value=(surface["call25Iv"] + surface["put25Iv"]) / 2.0
                        - surface["atmIv"],
                        unit="volatility points",
                        fetched_at=fetched_at,
                        metadata={
                            **common_metadata,
                            "definition": "mean 25-delta wing IV minus ATM IV",
                        },
                    )
                )

        if 7 in fixed and 30 in fixed:
            points.append(
                self._term_slope_point(
                    "IVTermSlope7D30D", fixed[7], fixed[30], 7, 30, fetched_at
                )
            )
        if 30 in fixed and 90 in fixed:
            points.append(
                self._term_slope_point(
                    "IVTermSlope30D90D", fixed[30], fixed[90], 30, 90, fetched_at
                )
            )
        return points

    @staticmethod
    def _usable_option_quote(
        open_interest: float, bid_price: float, ask_price: float
    ) -> bool:
        if open_interest <= 0 or bid_price <= 0 or ask_price < bid_price:
            return False
        midpoint = (bid_price + ask_price) / 2.0
        return midpoint > 0 and (ask_price - bid_price) / midpoint <= 1.0

    @staticmethod
    def _black_forward_delta(
        forward: float,
        strike: float,
        iv_percent: float,
        years: float,
        option_type: str,
    ) -> float | None:
        sigma = iv_percent / 100.0
        denominator = sigma * math.sqrt(years)
        if forward <= 0 or strike <= 0 or denominator <= 0:
            return None
        d1 = (math.log(forward / strike) + 0.5 * sigma * sigma * years) / denominator
        call_delta = 0.5 * (1.0 + math.erf(d1 / math.sqrt(2.0)))
        return call_delta if option_type == "call" else call_delta - 1.0

    @classmethod
    def _surface_for_expiry(
        cls, records: list[dict[str, Any]], fetched_at: datetime
    ) -> dict[str, Any] | None:
        if not records:
            return None
        expiration = records[0]["expiration"]
        days = (expiration - fetched_at).total_seconds() / 86400.0
        if days <= 1:
            return None
        forward = statistics.median(float(record["forward"]) for record in records)
        closest_distance = min(
            abs(math.log(float(record["strike"]) / forward)) for record in records
        )
        atm_candidates = [
            float(record["iv"])
            for record in records
            if abs(math.log(float(record["strike"]) / forward))
            <= closest_distance + 1e-12
        ]
        call_iv = cls._interpolate_delta_iv(records, "call", 0.25)
        put_iv = cls._interpolate_delta_iv(records, "put", 0.25)
        if not atm_candidates or call_iv is None or put_iv is None:
            return None
        return {
            "days": days,
            "expiration": expiration.isoformat(),
            "atmIv": statistics.fmean(atm_candidates),
            "call25Iv": call_iv,
            "put25Iv": put_iv,
        }

    @staticmethod
    def _interpolate_delta_iv(
        records: list[dict[str, Any]], option_type: str, target: float
    ) -> float | None:
        candidates = sorted(
            (
                (abs(float(record["delta"])), float(record["iv"]))
                for record in records
                if record["optionType"] == option_type
                and math.isfinite(float(record["delta"]))
                and math.isfinite(float(record["iv"]))
            ),
            key=lambda item: item[0],
        )
        if not candidates:
            return None
        closest = min(candidates, key=lambda item: abs(item[0] - target))
        if abs(closest[0] - target) < 1e-9:
            return closest[1]
        lower = max((item for item in candidates if item[0] < target), default=None)
        upper = min((item for item in candidates if item[0] > target), default=None)
        if lower and upper and upper[0] != lower[0]:
            weight = (target - lower[0]) / (upper[0] - lower[0])
            return lower[1] + (upper[1] - lower[1]) * weight
        return closest[1] if abs(closest[0] - target) <= 0.08 else None

    @classmethod
    def _fixed_tenor_surface(
        cls, surfaces: list[dict[str, Any]], target_days: int
    ) -> dict[str, Any] | None:
        lower = max(
            (surface for surface in surfaces if surface["days"] <= target_days),
            key=lambda surface: surface["days"],
            default=None,
        )
        upper = min(
            (surface for surface in surfaces if surface["days"] >= target_days),
            key=lambda surface: surface["days"],
            default=None,
        )
        if lower is None or upper is None:
            return None
        return {
            "atmIv": cls._interpolate_total_variance(
                lower["atmIv"], lower["days"], upper["atmIv"], upper["days"], target_days
            ),
            "call25Iv": cls._interpolate_total_variance(
                lower["call25Iv"], lower["days"], upper["call25Iv"], upper["days"], target_days
            ),
            "put25Iv": cls._interpolate_total_variance(
                lower["put25Iv"], lower["days"], upper["put25Iv"], upper["days"], target_days
            ),
            "lowerExpiry": lower["expiration"],
            "upperExpiry": upper["expiration"],
        }

    @staticmethod
    def _interpolate_total_variance(
        lower_iv: float,
        lower_days: float,
        upper_iv: float,
        upper_days: float,
        target_days: float,
    ) -> float:
        if abs(upper_days - lower_days) < 1e-9:
            return (lower_iv + upper_iv) / 2.0
        lower_variance = (lower_iv / 100.0) ** 2 * lower_days / 365.0
        upper_variance = (upper_iv / 100.0) ** 2 * upper_days / 365.0
        weight = (target_days - lower_days) / (upper_days - lower_days)
        target_variance = lower_variance + (upper_variance - lower_variance) * weight
        return math.sqrt(max(0.0, target_variance) / (target_days / 365.0)) * 100.0

    def _term_slope_point(
        self,
        metric: str,
        short_surface: dict[str, Any],
        long_surface: dict[str, Any],
        short_days: int,
        long_days: int,
        fetched_at: datetime,
    ) -> DataPoint:
        return DataPoint(
            source=self.source,
            metric=metric,
            observed_at=fetched_at,
            value=short_surface["atmIv"] - long_surface["atmIv"],
            unit="volatility points",
            fetched_at=fetched_at,
            metadata={
                "frequency": "snapshot",
                "definition": f"{short_days}D ATM IV minus {long_days}D ATM IV",
                "shortDays": short_days,
                "longDays": long_days,
                "sourceUrl": f"{self.api_url}/get_book_summary_by_currency",
            },
        )

    async def _get_result(
        self,
        client: httpx.AsyncClient,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                response = await client.get(
                    f"{self.api_url}/{method}", params=params
                )
                response.raise_for_status()
                break
            except (httpx.ConnectError, httpx.TimeoutException):
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))
        if response is None:
            raise RuntimeError(f"Deribit {method} returned no response.")
        payload = response.json()
        if payload.get("error"):
            error = payload["error"]
            raise RuntimeError(error.get("message") or str(error))
        if "result" not in payload:
            raise RuntimeError(f"Deribit {method} response omitted result.")
        return payload["result"]

    @staticmethod
    def _from_milliseconds(value: int | float) -> datetime:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
