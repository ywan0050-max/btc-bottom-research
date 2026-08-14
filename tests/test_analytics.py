from app.analytics import (
    bucket_latest,
    build_cycle_valuation,
    change_series,
    clamp,
    cycle_status_label,
    factor_contributions,
    nearest_before,
    percent_change,
    percentile_rank,
    reversal_status_label,
    spearman_correlation,
    window_has_coverage,
    weighted_bucket,
    observation_age_days,
)
import pytest

from datetime import datetime, timedelta, timezone


def test_percentile_rank() -> None:
    assert percentile_rank([1.0, 2.0, 3.0, 4.0], 2.0) == 0.5


def test_percent_change() -> None:
    assert percent_change(120.0, 100.0) == 20.0
    assert percent_change(120.0, 0.0) is None


def test_business_day_age_skips_weekends_without_under_counting_friday() -> None:
    observed = datetime(2026, 8, 7, tzinfo=timezone.utc)
    thursday = datetime(2026, 8, 13, 12, tzinfo=timezone.utc)
    saturday = datetime(2026, 8, 15, 12, tzinfo=timezone.utc)

    assert observation_age_days(thursday, observed, "business day") == pytest.approx(4.5)
    assert observation_age_days(saturday, observed, "business day") == pytest.approx(6.0)


def test_clamp() -> None:
    assert clamp(-1.0) == 0.0
    assert clamp(42.0) == 42.0
    assert clamp(101.0) == 100.0


def test_nearest_before_does_not_use_a_future_observation() -> None:
    series = [
        {"observedAt": "2026-01-01T00:00:00+00:00", "value": 1.0},
        {"observedAt": "2026-01-03T00:00:00+00:00", "value": 2.0},
    ]
    target = datetime(2026, 1, 2, tzinfo=timezone.utc)
    assert nearest_before(series, target)["value"] == 1.0


def test_reversal_status_label() -> None:
    assert reversal_status_label(None) == "等待衍生品与成交数据"
    assert reversal_status_label(72.0) == "反转动能较强"
    assert reversal_status_label(56.0) == "出现初步确认"
    assert reversal_status_label(45.0) == "确认信号分化"
    assert reversal_status_label(30.0) == "尚未确认"


def test_cycle_valuation_uses_real_data_without_double_counting_derivatives() -> None:
    start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    price_series = [
        {
            "observedAt": (start + timedelta(days=index)).isoformat(),
            "value": 100.0 + index / 10,
        }
        for index in range(400)
    ]
    price_series[-1]["value"] = 120.0
    mvrv_series = [
        {"observedAt": point["observedAt"], "value": 1.0 + index / 1000}
        for index, point in enumerate(price_series)
    ]
    mvrv_series[-1]["value"] = 1.2

    cdd_series = [
        {"observedAt": point["observedAt"], "value": 10.0}
        for point in price_series
    ]
    cycle, components = build_cycle_valuation(
        price_series, mvrv_series, cdd_series, price_series
    )

    assert cycle["realizedPrice"] == 100.0
    assert round(cycle["nupl"], 4) == 16.6667
    assert cycle["mayerMultiple"] is not None
    assert [component["key"] for component in components] == [
        "mvrv", "mayer", "cvdd"
    ]
    assert components[-1]["score"] is None


def test_cycle_status_label() -> None:
    assert cycle_status_label(None) == "等待长期估值数据"
    assert cycle_status_label(80) == "长期估值显著偏低"
    assert cycle_status_label(60) == "进入长期观察区"


def test_spearman_correlation_tracks_rank_direction() -> None:
    assert spearman_correlation(list(range(20)), list(range(20))) == 1.0
    assert spearman_correlation(list(range(20)), list(reversed(range(20)))) == -1.0
    assert spearman_correlation([1.0, 2.0], [1.0, 2.0]) is None


def test_change_series_supports_monthly_year_over_year_windows() -> None:
    points = [
        {"observedAt": "2024-06-01T00:00:00+00:00", "value": 100.0},
        {"observedAt": "2025-05-01T00:00:00+00:00", "value": 110.0},
        {"observedAt": "2025-06-01T00:00:00+00:00", "value": 120.0},
    ]

    changes = change_series(points, 365)

    assert changes == {datetime(2025, 6, 1).date(): pytest.approx(20.0)}


def test_weighted_bucket_ignores_missing_without_treating_it_as_zero() -> None:
    bucket = weighted_bucket(
        "test",
        "测试因子",
        25,
        [
            {"key": "available", "label": "可用", "weight": 60, "score": 80},
            {"key": "missing", "label": "缺失", "weight": 40, "score": None},
        ],
    )
    assert bucket["score"] == 80
    assert bucket["coverage"] == 60


def test_factor_contributions_reconcile_to_weighted_score() -> None:
    buckets = [
        {"key": "a", "label": "A", "weight": 45, "coverage": 55, "score": 82},
        {"key": "b", "label": "B", "weight": 25, "coverage": 100, "score": 70},
        {"key": "c", "label": "C", "weight": 30, "coverage": 100, "score": 26},
    ]

    contributions = factor_contributions(buckets)
    effective = [bucket["weight"] * bucket["coverage"] / 100 for bucket in buckets]
    expected = sum(
        bucket["score"] * weight for bucket, weight in zip(buckets, effective, strict=True)
    ) / sum(effective)

    assert sum(item["points"] for item in contributions) == pytest.approx(
        expected - 50, abs=0.15
    )
    assert sum(item["effectiveWeight"] for item in contributions) == pytest.approx(
        100, abs=0.15
    )


def test_time_buckets_require_actual_window_coverage() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dense_but_short = [
        {
            "observedAt": (start + timedelta(minutes=index)).isoformat(),
            "value": float(index),
        }
        for index in range(100)
    ]
    full_window = [
        {
            "observedAt": (start + timedelta(minutes=15 * index)).isoformat(),
            "value": float(index),
        }
        for index in range(23)
    ]

    assert len(bucket_latest(dense_but_short)) == 7
    assert not window_has_coverage(dense_but_short, timedelta(hours=6), 18)
    assert window_has_coverage(full_window, timedelta(hours=6), 18)


def test_cvdd_approximation_requires_early_matched_history() -> None:
    start = datetime(2010, 1, 1, tzinfo=timezone.utc)
    prices = [
        {"observedAt": (start + timedelta(days=index)).isoformat(), "value": 100.0}
        for index in range(500)
    ]
    cdd = [
        {"observedAt": point["observedAt"], "value": 10.0}
        for point in prices
    ]

    cycle, components = build_cycle_valuation(prices, [], cdd, prices)

    market_age_days = (start.date() + timedelta(days=499) - datetime(2009, 1, 3).date()).days + 1
    expected = 500 * 10.0 * 100.0 / market_age_days / 6_000_000.0
    assert cycle["cvdd"] == pytest.approx(expected)
    assert cycle["cvddStatus"] == "available_daily_approximation"
    assert cycle["cvddCoverageDays"] == 500
    assert components[-1]["score"] is not None
