import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from app.collectors.deribit import DeribitCollector


class StubDeribitCollector(DeribitCollector):
    def __init__(self, results: dict[str, Any]) -> None:
        self.results = results

    async def _get_result(self, client, method: str, params: dict[str, Any]) -> Any:
        return self.results[method]


def test_recent_cvd_uses_directional_usd_amounts() -> None:
    collector = StubDeribitCollector({
        "get_last_trades_by_instrument": {
            "trades": [
                {"timestamp": 2_000, "amount": 300.0, "direction": "buy"},
                {"timestamp": 1_000, "amount": 100.0, "direction": "sell"},
            ]
        }
    })
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = asyncio.run(collector._recent_cvd(None, fetched_at))[0]

    assert point.value == 200.0
    assert point.metadata["imbalancePct"] == 50.0
    assert point.metadata["tradeCount"] == 2


def test_perpetual_open_interest_is_already_usd_amount() -> None:
    collector = StubDeribitCollector({
        "get_book_summary_by_instrument": [{
            "open_interest": 715_000_000,
            "creation_timestamp": 1_000,
            "mark_price": 63_800,
            "index_price": 63_790,
        }]
    })
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = asyncio.run(collector._open_interest(None, fetched_at))[0]

    assert point.value == 715_000_000
    assert point.unit == "USD"
    assert point.metadata["amountBasis"] == "Deribit USD amount units for perpetuals"
    assert point.metadata["timestampSource"].startswith("creation_timestamp")


def test_deribit_metric_group_has_independent_timeout() -> None:
    collector = StubDeribitCollector({})
    collector.group_timeout_seconds = 0.01

    async def slow_group():
        await asyncio.sleep(1)

    with pytest.raises(TimeoutError, match="metric group exceeded"):
        asyncio.run(collector._bounded_group(slow_group()))


def test_order_book_imbalance_uses_equal_depth_levels() -> None:
    collector = StubDeribitCollector({
        "get_order_book": {
            "timestamp": 1_000,
            "bids": [[100.0, 300.0], [99.9, 100.0]],
            "asks": [[100.1, 100.0], [100.2, 100.0]],
        }
    })
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = asyncio.run(collector._order_book(None, fetched_at))[0]

    assert point.value == pytest.approx(100.0 / 3.0)
    assert point.metadata["bidDepthUsd"] == 400.0
    assert point.metadata["askDepthUsd"] == 200.0
    assert point.metadata["depthBasisBps"] == 25
    assert set(point.metadata["depthBands"]) == {"10", "25", "50", "100"}


def test_order_book_fixed_band_excludes_distant_levels() -> None:
    collector = StubDeribitCollector({
        "get_order_book": {
            "timestamp": 1_000,
            "bids": [[100.0, 300.0], [99.0, 900.0]],
            "asks": [[100.1, 100.0], [101.0, 900.0]],
        }
    })
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = asyncio.run(collector._order_book(None, fetched_at))[0]

    assert point.value == pytest.approx(50.0)
    assert point.metadata["bidDepthUsd"] == 300.0
    assert point.metadata["askDepthUsd"] == 100.0


def test_black_forward_delta_has_consistent_call_put_pair() -> None:
    call_delta = DeribitCollector._black_forward_delta(
        60_000.0, 60_000.0, 50.0, 30.0 / 365.0, "call"
    )
    put_delta = DeribitCollector._black_forward_delta(
        60_000.0, 60_000.0, 50.0, 30.0 / 365.0, "put"
    )

    assert call_delta is not None
    assert put_delta is not None
    assert call_delta - put_delta == pytest.approx(1.0)
    assert 0.5 < call_delta < 0.6


def test_delta_iv_and_total_variance_interpolation() -> None:
    records = [
        {"optionType": "call", "delta": 0.20, "iv": 40.0},
        {"optionType": "call", "delta": 0.30, "iv": 50.0},
    ]

    assert DeribitCollector._interpolate_delta_iv(records, "call", 0.25) == pytest.approx(45.0)
    assert DeribitCollector._interpolate_total_variance(
        40.0, 10.0, 40.0, 40.0, 30.0
    ) == pytest.approx(40.0)


def test_funding_rate_is_stored_as_percent() -> None:
    collector = StubDeribitCollector({
        "get_funding_rate_history": [
            {"timestamp": 1_000, "interest_8h": 0.0001, "index_price": 60_000}
        ]
    })
    fetched_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    point = asyncio.run(collector._funding_history(None, fetched_at))[0]

    assert point.value == 0.01
    assert point.unit == "percent per 8h"


def test_option_quote_filter_requires_liquidity_and_two_sided_quote() -> None:
    usable = DeribitCollector._usable_option_quote

    assert usable(10.0, 0.01, 0.015)
    assert not usable(0.0, 0.01, 0.015)
    assert not usable(10.0, 0.0, 0.015)
    assert not usable(10.0, 0.01, 0.04)
