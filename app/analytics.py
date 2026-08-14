from __future__ import annotations

import math
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

from .db import Database


METRIC_LIMITS = {
    "PriceUSD": 5000,
    "CapMVRVCur": 5000,
    "CoinDaysDestroyed": 10000,
    "BlockchainPriceUSD": 10000,
    "TGA": 2000,
    "FedAssets": 1000,
    "OvernightRRP": 5000,
    "US10Y": 5000,
    "BroadDollar": 5000,
    "FinancialConditions": 1000,
    "HighYieldSpread": 5000,
    "US10YReal": 5000,
    "USM2": 1000,
    "StablecoinSupplyUSD": 5000,
    "FearGreedIndex": 5000,
    "HashRate": 10000,
    "MiningDifficulty": 1000,
    "FundingRate8h": 1000,
    "OpenInterestUSD": 1000,
    "TradeCVDUSD": 1000,
    "OrderBookImbalance25bps": 1000,
    "ATMIV7D": 1000,
    "ATMIV30D": 1000,
    "ATMIV90D": 1000,
    "RR25_7D": 1000,
    "RR25_30D": 1000,
    "RR25_90D": 1000,
    "BF25_30D": 1000,
    "IVTermSlope7D30D": 1000,
    "IVTermSlope30D90D": 1000,
}

METRIC_QUALITY = {
    "PriceUSD": {"frequency": "daily", "staleDays": 4, "cadenceScore": 100},
    "CapMVRVCur": {"frequency": "daily", "staleDays": 4, "cadenceScore": 100},
    "CoinDaysDestroyed": {"frequency": "daily", "staleDays": 4, "cadenceScore": 85},
    "BlockchainPriceUSD": {"frequency": "daily", "staleDays": 4, "cadenceScore": 85},
    "TGA": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "FedAssets": {"frequency": "weekly", "staleDays": 10, "cadenceScore": 80},
    "OvernightRRP": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "US10Y": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "BroadDollar": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "FinancialConditions": {"frequency": "weekly", "staleDays": 10, "cadenceScore": 80},
    "HighYieldSpread": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "US10YReal": {"frequency": "business day", "staleDays": 5, "cadenceScore": 92},
    "USM2": {"frequency": "monthly", "staleDays": 75, "cadenceScore": 65},
    "StablecoinSupplyUSD": {"frequency": "daily", "staleDays": 4, "cadenceScore": 88},
    "FearGreedIndex": {"frequency": "daily", "staleDays": 4, "cadenceScore": 82},
    "HashRate": {"frequency": "daily", "staleDays": 4, "cadenceScore": 90},
    "MiningDifficulty": {"frequency": "2016 blocks", "staleDays": 18, "cadenceScore": 72},
    "FundingRate8h": {"frequency": "hourly", "staleDays": 0.25, "cadenceScore": 100},
    "OpenInterestUSD": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "TradeCVDUSD": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "OrderBookImbalance25bps": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "ATMIV7D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "ATMIV30D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "ATMIV90D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "RR25_7D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "RR25_30D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "RR25_90D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "BF25_30D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "IVTermSlope7D30D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
    "IVTermSlope30D90D": {"frequency": "snapshot", "staleDays": 0.125, "cadenceScore": 95},
}

# Confidence follows the enabled long-horizon research surface. Retired CDD and
# paused short-cycle Deribit metrics remain visible but do not dilute this score.
CONFIDENCE_METRICS = (
    "PriceUSD",
    "CapMVRVCur",
    "TGA",
    "FedAssets",
    "OvernightRRP",
    "US10Y",
    "BroadDollar",
    "FinancialConditions",
    "HighYieldSpread",
    "US10YReal",
    "HashRate",
    "MiningDifficulty",
)


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def observation_age_days(now: datetime, observed_at: datetime, frequency: str) -> float:
    """Age in calendar days, counting only weekdays for business-day series."""
    if frequency != "business day":
        return max(0.0, (now - observed_at).total_seconds() / 86400.0)
    if observed_at >= now:
        return 0.0
    start_date = observed_at.date()
    end_date = now.date()
    if start_date == end_date:
        return max(0.0, (now - observed_at).total_seconds() / 86400.0)
    age = 0.0
    if start_date.weekday() < 5:
        start_midnight = datetime.combine(start_date, datetime.min.time(), tzinfo=observed_at.tzinfo)
        age += (start_midnight + timedelta(days=1) - observed_at).total_seconds() / 86400.0
    current = start_date + timedelta(days=1)
    while current < end_date:
        if current.weekday() < 5:
            age += 1.0
        current += timedelta(days=1)
    if end_date.weekday() < 5:
        end_midnight = datetime.combine(end_date, datetime.min.time(), tzinfo=now.tzinfo)
        age += (now - end_midnight).total_seconds() / 86400.0
    return max(0.0, age)


def percentile_rank(values: list[float], current: float) -> float | None:
    clean = [value for value in values if math.isfinite(value)]
    if len(clean) < 2:
        return None
    below_or_equal = sum(value <= current for value in clean)
    return below_or_equal / len(clean)


def nearest_before(series: list[dict[str, Any]], target: datetime) -> dict[str, Any] | None:
    for point in reversed(series):
        observed_at = datetime.fromisoformat(point["observedAt"])
        if observed_at <= target:
            return point
    return None


def percent_change(current: float, previous: float | None) -> float | None:
    if previous in (None, 0):
        return None
    return (current - previous) / previous * 100.0


def average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + end - 1) / 2.0 + 1.0
        for original_index, _ in ordered[index:end]:
            ranks[original_index] = rank
        index = end
    return ranks


def spearman_correlation(
    values_a: list[float], values_b: list[float], minimum_samples: int = 20
) -> float | None:
    if len(values_a) != len(values_b) or len(values_a) < minimum_samples:
        return None
    ranks_a = average_ranks(values_a)
    ranks_b = average_ranks(values_b)
    mean_a = statistics.fmean(ranks_a)
    mean_b = statistics.fmean(ranks_b)
    covariance = sum(
        (value_a - mean_a) * (value_b - mean_b)
        for value_a, value_b in zip(ranks_a, ranks_b, strict=True)
    )
    variance_a = sum((value - mean_a) ** 2 for value in ranks_a)
    variance_b = sum((value - mean_b) ** 2 for value in ranks_b)
    denominator = math.sqrt(variance_a * variance_b)
    return covariance / denominator if denominator else None


def weighted_bucket(
    key: str,
    label: str,
    weight: float,
    items: list[dict[str, Any]],
    minimum_coverage: float = 50.0,
) -> dict[str, Any]:
    total_weight = sum(float(item["weight"]) for item in items)
    available = [item for item in items if item.get("score") is not None]
    available_weight = sum(float(item["weight"]) for item in available)
    coverage = available_weight / total_weight * 100.0 if total_weight else 0.0
    score = (
        sum(float(item["score"]) * float(item["weight"]) for item in available)
        / available_weight
        if available_weight and coverage >= minimum_coverage
        else None
    )
    return {
        "key": key,
        "label": label,
        "weight": weight,
        "score": round(score) if score is not None else None,
        "coverage": round(coverage),
        "components": [
            {
                **item,
                "score": round(item["score"]) if item.get("score") is not None else None,
            }
            for item in items
        ],
    }


def combine_factor_buckets(
    buckets: list[dict[str, Any]], minimum_groups: int
) -> tuple[float | None, float]:
    available = [bucket for bucket in buckets if bucket.get("score") is not None]
    effective_weights = [
        float(bucket["weight"]) * float(bucket["coverage"]) / 100.0
        for bucket in available
    ]
    total_effective_weight = sum(effective_weights)
    coverage = sum(
        float(bucket["weight"]) * float(bucket["coverage"]) / 100.0
        for bucket in buckets
    )
    if len(available) < minimum_groups or not total_effective_weight:
        return None, coverage
    score = sum(
        float(bucket["score"]) * effective_weight
        for bucket, effective_weight in zip(available, effective_weights, strict=True)
    ) / total_effective_weight
    return score, coverage


def change_series(
    points: list[dict[str, Any]], days: int, percent: bool = True
) -> dict[date, float]:
    changes: dict[date, float] = {}
    previous_index = 0
    for index, point in enumerate(points):
        observed_at = datetime.fromisoformat(point["observedAt"])
        target = observed_at - timedelta(days=days)
        while (
            previous_index + 1 < index
            and datetime.fromisoformat(points[previous_index + 1]["observedAt"])
            <= target
        ):
            previous_index += 1
        previous = points[previous_index] if previous_index < index else None
        if not previous or datetime.fromisoformat(previous["observedAt"]) > target:
            continue
        current_value = float(point["value"])
        previous_value = float(previous["value"])
        value = (
            percent_change(current_value, previous_value)
            if percent
            else current_value - previous_value
        )
        if value is not None and math.isfinite(value):
            changes[observed_at.date()] = value
    return changes


def bucket_latest(
    points: list[dict[str, Any]], minutes: int = 15
) -> list[dict[str, Any]]:
    """Keep the latest observation in each fixed UTC time bucket."""
    bucket_seconds = minutes * 60
    buckets: dict[int, dict[str, Any]] = {}
    for point in points:
        observed_at = datetime.fromisoformat(point["observedAt"])
        bucket = int(observed_at.timestamp()) // bucket_seconds
        current = buckets.get(bucket)
        if current is None or observed_at > datetime.fromisoformat(
            current["observedAt"]
        ):
            buckets[bucket] = point
    return sorted(
        buckets.values(),
        key=lambda point: datetime.fromisoformat(point["observedAt"]),
    )


def window_has_coverage(
    points: list[dict[str, Any]],
    window: timedelta,
    minimum_samples: int,
    minimum_span_ratio: float = 0.9,
) -> bool:
    if len(points) < minimum_samples:
        return False
    observed_times = [
        datetime.fromisoformat(point["observedAt"]) for point in points
    ]
    return max(observed_times) - min(observed_times) >= window * minimum_span_ratio


def factor_contributions(
    buckets: list[dict[str, Any]], neutral_score: float = 50.0
) -> list[dict[str, Any]]:
    effective_weights = {
        bucket["key"]: (
            float(bucket["weight"]) * float(bucket["coverage"]) / 100.0
        )
        for bucket in buckets
        if bucket.get("score") is not None
    }
    total_effective_weight = sum(effective_weights.values())
    return [
        {
            "key": bucket["key"],
            "label": bucket["label"],
            "score": bucket["score"],
            "weight": bucket["weight"],
            "coverage": bucket["coverage"],
            "effectiveWeight": (
                round(effective_weights[bucket["key"]] / total_effective_weight * 100.0, 1)
                if bucket.get("score") is not None and total_effective_weight
                else None
            ),
            "points": (
                round(
                    (float(bucket["score"]) - neutral_score)
                    * effective_weights[bucket["key"]]
                    / total_effective_weight,
                    1,
                )
                if bucket.get("score") is not None and total_effective_weight
                else None
            ),
        }
        for bucket in buckets
    ]


def status_label(score: float | None) -> str:
    if score is None:
        return "数据不足"
    if score >= 75:
        return "底部环境显著"
    if score >= 55:
        return "进入观察区"
    if score >= 35:
        return "信号偏弱"
    return "尚未形成"


def reversal_status_label(score: float | None) -> str:
    if score is None:
        return "等待衍生品与成交数据"
    if score >= 70:
        return "反转动能较强"
    if score >= 55:
        return "出现初步确认"
    if score >= 40:
        return "确认信号分化"
    return "尚未确认"


def cycle_status_label(score: float | None) -> str:
    if score is None:
        return "等待长期估值数据"
    if score >= 75:
        return "长期估值显著偏低"
    if score >= 55:
        return "进入长期观察区"
    if score >= 35:
        return "长期估值中性"
    return "长期估值仍偏高"


def build_cycle_valuation(
    price_series: list[dict[str, Any]],
    mvrv_series: list[dict[str, Any]],
    cdd_series: list[dict[str, Any]],
    cdd_price_series: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cycle: dict[str, Any] = {
        "observedAt": None,
        "realizedPrice": None,
        "distanceToRealizedPrice": None,
        "nupl": None,
        "mayerMultiple": None,
        "mayerPercentile5y": None,
        "cvdd": None,
        "cvddStatus": "waiting_reliable_free_source",
        "cvddObservedAt": None,
        "cvddCoverageDays": 0,
        "cvddCoverageStart": None,
        "cvddMultiple": None,
        "cvddPercentile5y": None,
    }
    components: list[dict[str, Any]] = []

    if price_series and mvrv_series:
        mvrv_by_time = {
            datetime.fromisoformat(point["observedAt"]): point
            for point in mvrv_series
        }
        price_point = next(
            (
                point
                for point in reversed(price_series)
                if datetime.fromisoformat(point["observedAt"]) in mvrv_by_time
            ),
            None,
        )
        common_time = (
            datetime.fromisoformat(price_point["observedAt"])
            if price_point
            else None
        )
        mvrv_point = mvrv_by_time.get(common_time) if common_time else None
        if price_point and mvrv_point:
            price = float(price_point["value"])
            mvrv = float(mvrv_point["value"])
            if price > 0 and mvrv > 0:
                cycle["observedAt"] = common_time.isoformat()
                cycle["realizedPrice"] = price / mvrv
                cycle["distanceToRealizedPrice"] = (mvrv - 1.0) * 100.0
                cycle["nupl"] = (1.0 - 1.0 / mvrv) * 100.0

                five_year_cutoff = common_time - timedelta(days=365 * 5)
                mvrv_values = [
                    float(point["value"])
                    for point in mvrv_series
                    if datetime.fromisoformat(point["observedAt"])
                    >= five_year_cutoff
                ]
                rank = percentile_rank(mvrv_values, mvrv)
                if rank is not None:
                    components.append({
                        "key": "mvrv",
                        "label": "MVRV / NUPL",
                        "score": (1.0 - rank) * 100.0,
                        "detail": f"MVRV 五年滚动百分位 {rank * 100.0:.1f}%",
                    })

    if len(price_series) >= 200:
        price_values = [float(point["value"]) for point in price_series]
        rolling_sum = sum(price_values[:200])
        mayer_history: list[tuple[datetime, float]] = []
        for index in range(199, len(price_values)):
            if index > 199:
                rolling_sum += price_values[index] - price_values[index - 200]
            moving_average = rolling_sum / 200.0
            if moving_average > 0:
                mayer_history.append((
                    datetime.fromisoformat(price_series[index]["observedAt"]),
                    price_values[index] / moving_average,
                ))
        if mayer_history:
            latest_time, current_mayer = mayer_history[-1]
            five_year_cutoff = latest_time - timedelta(days=365 * 5)
            five_year_values = [
                value for observed_at, value in mayer_history
                if observed_at >= five_year_cutoff
            ]
            rank = percentile_rank(five_year_values, current_mayer)
            cycle["mayerMultiple"] = current_mayer
            cycle["mayerPercentile5y"] = (
                rank * 100.0 if rank is not None else None
            )
            if rank is not None:
                components.append({
                    "key": "mayer",
                    "label": "Mayer Multiple",
                    "score": (1.0 - rank) * 100.0,
                    "detail": f"五年滚动百分位 {rank * 100.0:.1f}%",
                })

    if cdd_price_series and cdd_series:
        prices_by_date = {
            datetime.fromisoformat(point["observedAt"]).date(): float(point["value"])
            for point in cdd_price_series
            if float(point["value"]) > 0
        }
        matched = [
            (datetime.fromisoformat(point["observedAt"]).date(), float(point["value"]))
            for point in cdd_series
            if datetime.fromisoformat(point["observedAt"]).date() in prices_by_date
            and math.isfinite(float(point["value"]))
            and float(point["value"]) >= 0
        ]
        matched.sort()
        has_early_history = matched and matched[0][0] <= date(2011, 1, 1)
        if len(matched) >= 365 and has_early_history:
            cumulative_value_days = 0.0
            start_date = matched[0][0]
            cvdd_history: list[tuple[date, float, float]] = []
            for observed_date, cdd in matched:
                cumulative_value_days += cdd * prices_by_date[observed_date]
                market_age_days = max(
                    1, (observed_date - date(2009, 1, 3)).days + 1
                )
                value = cumulative_value_days / market_age_days / 6_000_000.0
                if value > 0:
                    cvdd_history.append(
                        (observed_date, value, prices_by_date[observed_date] / value)
                    )
            latest_date, cvdd, cvdd_multiple = cvdd_history[-1]
            five_year_cutoff = latest_date - timedelta(days=365 * 5)
            five_year_multiples = [
                multiple
                for observed_date, _, multiple in cvdd_history
                if observed_date >= five_year_cutoff
            ]
            rank = percentile_rank(five_year_multiples, cvdd_multiple)
            cycle["cvdd"] = cvdd
            cycle["cvddStatus"] = "available_daily_approximation"
            cycle["cvddObservedAt"] = latest_date.isoformat()
            cycle["cvddCoverageDays"] = len(matched)
            cycle["cvddCoverageStart"] = start_date.isoformat()
            cycle["cvddMultiple"] = cvdd_multiple
            cycle["cvddPercentile5y"] = rank * 100.0 if rank is not None else None
            components.append({
                "key": "cvdd",
                "label": "CVDD 近似值",
                "score": (1.0 - rank) * 100.0 if rank is not None else None,
                "detail": (
                    f"现价/CVDD {cvdd_multiple:.2f}，五年百分位 {rank * 100.0:.1f}%"
                    if rank is not None
                    else f"日频 CDD×价格累计，覆盖 {len(matched)} 天"
                ),
            })
        else:
            reason = (
                "历史未覆盖到 2011 年前"
                if matched and not has_early_history
                else f"仅对齐 {len(matched)} 天"
            )
            components.append({
                "key": "cvdd",
                "label": "CVDD 近似值",
                "score": None,
                "detail": f"CDD 与同源价格{reason}，暂不计算",
            })
    else:
        components.append({
            "key": "cvdd",
            "label": "CVDD 近似值",
            "score": None,
            "detail": "等待公开 CDD 原始序列与价格对齐",
        })
    return cycle, components


def build_overview(database: Database, refresh_state: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    series = {
        metric: database.series(metric, limit)
        for metric, limit in METRIC_LIMITS.items()
    }

    price_series = series["PriceUSD"]
    mvrv_series = series["CapMVRVCur"]
    cdd_series = series["CoinDaysDestroyed"]
    cdd_price_series = series["BlockchainPriceUSD"]
    tga_series = series["TGA"]
    fed_series = series["FedAssets"]
    rrp_series = series["OvernightRRP"]
    funding_series = series["FundingRate8h"]
    open_interest_series = series["OpenInterestUSD"]
    trade_cvd_series = series["TradeCVDUSD"]
    order_book_series = series["OrderBookImbalance25bps"]
    rr25_30d_series = series["RR25_30D"]
    hash_rate_series = series["HashRate"]
    difficulty_series = series["MiningDifficulty"]
    stablecoin_series = series["StablecoinSupplyUSD"]
    fear_greed_series = series["FearGreedIndex"]

    market: dict[str, Any] = {
        "price": None,
        "priceChange7d": None,
        "priceChange30d": None,
        "drawdownFromHigh": None,
        "realizedVol30d": None,
        "ma200w": None,
        "distanceTo200w": None,
        "mvrv": None,
        "mvrvPercentile5y": None,
        "asOf": None,
    }

    components: list[dict[str, Any]] = []
    if price_series:
        latest = price_series[-1]
        latest_time = datetime.fromisoformat(latest["observedAt"])
        current_price = float(latest["value"])
        market["price"] = current_price
        point_7d = nearest_before(price_series, latest_time - timedelta(days=7))
        point_30d = nearest_before(price_series, latest_time - timedelta(days=30))
        market["priceChange7d"] = percent_change(
            current_price, float(point_7d["value"]) if point_7d else None
        )
        market["priceChange30d"] = percent_change(
            current_price, float(point_30d["value"]) if point_30d else None
        )
        all_prices = [float(point["value"]) for point in price_series]
        all_time_high = max(all_prices)
        market["drawdownFromHigh"] = percent_change(current_price, all_time_high)
        drawdown_score = clamp((abs(min(market["drawdownFromHigh"], -10.0)) - 10.0) / 60.0 * 100.0)
        components.append({
            "key": "drawdown",
            "label": "周期回撤",
            "score": drawdown_score,
            "detail": f"距 2016 年以来高点 {market['drawdownFromHigh']:.1f}%",
        })

        recent_prices = all_prices[-31:]
        if len(recent_prices) >= 20:
            log_returns = [
                math.log(recent_prices[index] / recent_prices[index - 1])
                for index in range(1, len(recent_prices))
                if recent_prices[index - 1] > 0
            ]
            if len(log_returns) >= 2:
                market["realizedVol30d"] = statistics.stdev(log_returns) * math.sqrt(365) * 100

        if len(all_prices) >= 1400:
            ma_window = all_prices[-1400:]
            ma_200w = statistics.fmean(ma_window)
            distance = percent_change(current_price, ma_200w)
            market["ma200w"] = ma_200w
            market["distanceTo200w"] = distance
            ma_score = clamp((60.0 - (distance or 0.0)) / 75.0 * 100.0)
            components.append({
                "key": "ma200w",
                "label": "200周均线",
                "score": ma_score,
                "detail": f"现价相对均线 {distance:.1f}%",
            })

    if mvrv_series:
        latest = mvrv_series[-1]
        latest_time = datetime.fromisoformat(latest["observedAt"])
        current_mvrv = float(latest["value"])
        five_year_cutoff = latest_time - timedelta(days=365 * 5)
        five_year_values = [
            float(point["value"])
            for point in mvrv_series
            if datetime.fromisoformat(point["observedAt"]) >= five_year_cutoff
        ]
        rank = percentile_rank(five_year_values, current_mvrv)
        market["mvrv"] = current_mvrv
        market["mvrvPercentile5y"] = rank * 100.0 if rank is not None else None
    market_latest_points = [points[-1] for points in (price_series, mvrv_series) if points]
    market_as_of = min(
        (datetime.fromisoformat(point["observedAt"]) for point in market_latest_points),
        default=None,
    )
    market["asOf"] = market_as_of.isoformat() if market_as_of else None
    cycle, cycle_components = build_cycle_valuation(
        price_series, mvrv_series, cdd_series, cdd_price_series
    )

    macro: dict[str, Any] = {
        "tga": float(tga_series[-1]["value"]) if tga_series else None,
        "tgaChange7d": None,
        "netLiquidity": None,
        "netLiquidityChange30d": None,
        "us10y": float(series["US10Y"][-1]["value"]) if series["US10Y"] else None,
        "us10yChange90d": None,
        "broadDollar": float(series["BroadDollar"][-1]["value"]) if series["BroadDollar"] else None,
        "broadDollarChange90d": None,
        "financialConditions": (
            float(series["FinancialConditions"][-1]["value"])
            if series["FinancialConditions"] else None
        ),
        "highYieldSpread": (
            float(series["HighYieldSpread"][-1]["value"])
            if series["HighYieldSpread"] else None
        ),
        "us10yReal": (
            float(series["US10YReal"][-1]["value"])
            if series["US10YReal"] else None
        ),
        "usM2": float(series["USM2"][-1]["value"]) if series["USM2"] else None,
        "usM2Change12m": None,
        "usM2ObservedAt": series["USM2"][-1]["observedAt"] if series["USM2"] else None,
        "netLiquidityObservedAt": None,
        "asOf": None,
        "stablecoinSupplyUsd": (
            float(stablecoin_series[-1]["value"]) if stablecoin_series else None
        ),
        "stablecoinSupplyChange30d": None,
        "stablecoinSupplyObservedAt": (
            stablecoin_series[-1]["observedAt"] if stablecoin_series else None
        ),
        "fearGreed": (
            float(fear_greed_series[-1]["value"]) if fear_greed_series else None
        ),
        "fearGreedClassification": (
            (fear_greed_series[-1].get("metadata") or {}).get("classification")
            if fear_greed_series else None
        ),
        "fearGreedObservedAt": (
            fear_greed_series[-1]["observedAt"] if fear_greed_series else None
        ),
    }

    if series["US10Y"]:
        latest_us10y_time = datetime.fromisoformat(series["US10Y"][-1]["observedAt"])
        previous_us10y = nearest_before(
            series["US10Y"], latest_us10y_time - timedelta(days=90)
        )
        if previous_us10y:
            macro["us10yChange90d"] = (
                macro["us10y"] - float(previous_us10y["value"])
            )

    if series["BroadDollar"]:
        latest_dollar_time = datetime.fromisoformat(
            series["BroadDollar"][-1]["observedAt"]
        )
        previous_dollar = nearest_before(
            series["BroadDollar"], latest_dollar_time - timedelta(days=90)
        )
        if previous_dollar:
            macro["broadDollarChange90d"] = percent_change(
                macro["broadDollar"], float(previous_dollar["value"])
            )

    if series["USM2"]:
        latest_m2_time = datetime.fromisoformat(series["USM2"][-1]["observedAt"])
        previous_m2 = nearest_before(
            series["USM2"], latest_m2_time - timedelta(days=365)
        )
        if previous_m2:
            macro["usM2Change12m"] = percent_change(
                float(series["USM2"][-1]["value"]), float(previous_m2["value"])
            )

    if tga_series:
        latest_tga_time = datetime.fromisoformat(tga_series[-1]["observedAt"])
        tga_7d = nearest_before(tga_series, latest_tga_time - timedelta(days=7))
        if tga_7d:
            macro["tgaChange7d"] = float(tga_series[-1]["value"]) - float(tga_7d["value"])

    if fed_series and tga_series and rrp_series:
        latest_common = min(
            datetime.fromisoformat(fed_series[-1]["observedAt"]),
            datetime.fromisoformat(tga_series[-1]["observedAt"]),
            datetime.fromisoformat(rrp_series[-1]["observedAt"]),
        )

        def net_liquidity_at(moment: datetime) -> float | None:
            fed = nearest_before(fed_series, moment)
            tga = nearest_before(tga_series, moment)
            rrp = nearest_before(rrp_series, moment)
            if not (fed and tga and rrp):
                return None
            return float(fed["value"]) / 1000.0 - float(tga["value"]) / 1000.0 - float(rrp["value"])

        net_current = net_liquidity_at(latest_common)
        net_previous = net_liquidity_at(latest_common - timedelta(days=30))
        macro["netLiquidity"] = net_current
        macro["netLiquidityObservedAt"] = latest_common.isoformat()
        if net_current is not None and net_previous is not None:
            change = net_current - net_previous
            macro["netLiquidityChange30d"] = change
            components.append({
                "key": "netLiquidity",
                "label": "宏观净流动性",
                "score": clamp((change + 150.0) / 300.0 * 100.0),
                "detail": f"30 日变化 {change:+.1f} 十亿美元",
            })

    if stablecoin_series:
        stablecoin_latest_time = datetime.fromisoformat(stablecoin_series[-1]["observedAt"])
        stablecoin_previous = nearest_before(
            stablecoin_series, stablecoin_latest_time - timedelta(days=30)
        )
        if stablecoin_previous:
            macro["stablecoinSupplyChange30d"] = percent_change(
                float(stablecoin_series[-1]["value"]),
                float(stablecoin_previous["value"]),
            )

    macro_latest_points = [
        points[-1]
        for points in (
            tga_series,
            fed_series,
            rrp_series,
            series["US10Y"],
            series["BroadDollar"],
            series["FinancialConditions"],
            series["HighYieldSpread"],
            series["US10YReal"],
            series["USM2"],
            stablecoin_series,
            fear_greed_series,
        )
        if points
    ]
    macro_as_of = max(
        (datetime.fromisoformat(point["observedAt"]) for point in macro_latest_points),
        default=None,
    )
    macro["asOf"] = macro_as_of.isoformat() if macro_as_of else None

    mining: dict[str, Any] = {
        "hashRate": float(hash_rate_series[-1]["value"]) if hash_rate_series else None,
        "hashRate30d": None,
        "hashRate60d": None,
        "hashRibbonSpread": None,
        "hashRibbonStatus": "waiting",
        "difficulty": (
            float(difficulty_series[-1]["value"]) if difficulty_series else None
        ),
        "difficultyAdjustment": None,
    }
    if difficulty_series:
        difficulty_metadata = difficulty_series[-1].get("metadata") or {}
        adjustment = difficulty_metadata.get("adjustment")
        mining["difficultyAdjustment"] = (
            (float(adjustment) - 1.0) * 100.0 if adjustment is not None else None
        )
    if len(hash_rate_series) >= 60:
        hash_values = [float(point["value"]) for point in hash_rate_series]
        average_30d = statistics.fmean(hash_values[-30:])
        average_60d = statistics.fmean(hash_values[-60:])
        mining["hashRate30d"] = average_30d
        mining["hashRate60d"] = average_60d
        mining["hashRibbonSpread"] = percent_change(average_30d, average_60d)
        mining["hashRibbonStatus"] = (
            "capitulation" if average_30d < average_60d else "recovery"
        )

    derivatives: dict[str, Any] = {
        "fundingRate8h": None,
        "fundingPercentile30d": None,
        "fundingChange7d": None,
        "openInterestUsd": None,
        "openInterestChange7d": None,
        "tradeCvdUsd": None,
        "tradeFlowImbalance": None,
        "tradeCount": None,
        "tradeWindowMinutes": None,
        "orderBookImbalance": None,
        "bidDepthUsd": None,
        "askDepthUsd": None,
        "spreadBps": None,
        "depthBands": None,
    }
    if funding_series:
        latest_funding = funding_series[-1]
        latest_funding_time = datetime.fromisoformat(latest_funding["observedAt"])
        current_funding = float(latest_funding["value"])
        funding_cutoff = latest_funding_time - timedelta(days=30)
        funding_values = [
            float(point["value"])
            for point in funding_series
            if datetime.fromisoformat(point["observedAt"]) >= funding_cutoff
        ]
        funding_rank = percentile_rank(funding_values, current_funding)
        funding_7d = nearest_before(
            funding_series, latest_funding_time - timedelta(days=7)
        )
        derivatives["fundingRate8h"] = current_funding
        derivatives["fundingPercentile30d"] = (
            funding_rank * 100.0 if funding_rank is not None else None
        )
        funding_7d_age = (
            latest_funding_time - datetime.fromisoformat(funding_7d["observedAt"])
            if funding_7d
            else None
        )
        derivatives["fundingChange7d"] = (
            current_funding - float(funding_7d["value"])
            if funding_7d and funding_7d_age <= timedelta(days=7, hours=2)
            else None
        )

    if open_interest_series:
        latest_open_interest = open_interest_series[-1]
        latest_open_interest_time = datetime.fromisoformat(
            latest_open_interest["observedAt"]
        )
        current_open_interest = float(latest_open_interest["value"])
        open_interest_7d = nearest_before(
            open_interest_series, latest_open_interest_time - timedelta(days=7)
        )
        open_interest_7d_age = (
            latest_open_interest_time
            - datetime.fromisoformat(open_interest_7d["observedAt"])
            if open_interest_7d
            else None
        )
        derivatives["openInterestUsd"] = current_open_interest
        derivatives["openInterestChange7d"] = percent_change(
            current_open_interest,
            (
                float(open_interest_7d["value"])
                if open_interest_7d
                and open_interest_7d_age <= timedelta(days=7, hours=1)
                else None
            ),
        )

    if trade_cvd_series:
        latest_trade_cvd = trade_cvd_series[-1]
        trade_metadata = latest_trade_cvd.get("metadata") or {}
        derivatives["tradeCvdUsd"] = float(latest_trade_cvd["value"])
        derivatives["tradeFlowImbalance"] = trade_metadata.get("imbalancePct")
        derivatives["tradeCount"] = trade_metadata.get("tradeCount")
        derivatives["tradeWindowMinutes"] = trade_metadata.get("windowMinutes")

    if order_book_series:
        latest_order_book = order_book_series[-1]
        order_book_metadata = latest_order_book.get("metadata") or {}
        derivatives["orderBookImbalance"] = float(latest_order_book["value"])
        derivatives["bidDepthUsd"] = order_book_metadata.get("bidDepthUsd")
        derivatives["askDepthUsd"] = order_book_metadata.get("askDepthUsd")
        derivatives["spreadBps"] = order_book_metadata.get("spreadBps")
        derivatives["depthBands"] = order_book_metadata.get("depthBands")

    options: dict[str, Any] = {
        "atmIv7d": float(series["ATMIV7D"][-1]["value"]) if series["ATMIV7D"] else None,
        "atmIv30d": float(series["ATMIV30D"][-1]["value"]) if series["ATMIV30D"] else None,
        "atmIv90d": float(series["ATMIV90D"][-1]["value"]) if series["ATMIV90D"] else None,
        "rr25_7d": float(series["RR25_7D"][-1]["value"]) if series["RR25_7D"] else None,
        "rr25_30d": float(series["RR25_30D"][-1]["value"]) if series["RR25_30D"] else None,
        "rr25_90d": float(series["RR25_90D"][-1]["value"]) if series["RR25_90D"] else None,
        "bf25_30d": float(series["BF25_30D"][-1]["value"]) if series["BF25_30D"] else None,
        "termSlope7d30d": float(series["IVTermSlope7D30D"][-1]["value"]) if series["IVTermSlope7D30D"] else None,
        "termSlope30d90d": float(series["IVTermSlope30D90D"][-1]["value"]) if series["IVTermSlope30D90D"] else None,
        "ivMinusRealizedVol30d": None,
        "rr25Change24h": None,
    }
    if options["atmIv30d"] is not None and market["realizedVol30d"] is not None:
        options["ivMinusRealizedVol30d"] = (
            options["atmIv30d"] - market["realizedVol30d"]
        )
    if rr25_30d_series:
        latest_rr_time = datetime.fromisoformat(rr25_30d_series[-1]["observedAt"])
        previous_rr = nearest_before(
            rr25_30d_series, latest_rr_time - timedelta(hours=24)
        )
        previous_rr_age = (
            latest_rr_time - datetime.fromisoformat(previous_rr["observedAt"])
            if previous_rr
            else None
        )
        if previous_rr and previous_rr_age <= timedelta(hours=26):
            options["rr25Change24h"] = (
                options["rr25_30d"] - float(previous_rr["value"])
            )

    scored_cycle_components = [
        component["score"]
        for component in cycle_components
        if component["score"] is not None
    ]
    cycle_score = (
        statistics.fmean(scored_cycle_components)
        if scored_cycle_components
        else None
    )

    expected_metrics = list(METRIC_LIMITS)
    available_metrics = [metric for metric in expected_metrics if series[metric]]
    latest_metric_refreshes = {
        run["metric"]: run for run in database.latest_metric_refreshes()
    }
    metric_quality: list[dict[str, Any]] = []
    for metric in expected_metrics:
        config = METRIC_QUALITY[metric]
        points = series[metric]
        refresh_run = latest_metric_refreshes.get(metric)
        if metric in {"CoinDaysDestroyed", "BlockchainPriceUSD"}:
            refresh_run = {
                **(refresh_run or {}),
                "status": "retired",
                "error": (
                    "CDD chart endpoints now return 404. Automatic refresh is "
                    "disabled; previously cached real observations are retained."
                ),
            }
        if not points:
            metric_quality.append({
                "metric": metric,
                "available": False,
                "observedAt": None,
                "fetchedAt": None,
                "frequency": config["frequency"],
                "ageDays": None,
                "stale": True,
                "refreshStatus": refresh_run.get("status", "never") if refresh_run else "never",
                "refreshError": refresh_run.get("error") if refresh_run else None,
            })
            continue
        latest = points[-1]
        observed_at = datetime.fromisoformat(latest["observedAt"])
        age_days = observation_age_days(now, observed_at, config["frequency"])
        refresh_failed = bool(refresh_run and refresh_run["status"] != "ok")
        stale = age_days > config["staleDays"] or refresh_failed
        metric_quality.append({
            "metric": metric,
            "available": True,
            "observedAt": latest["observedAt"],
            "fetchedAt": latest["fetchedAt"],
            "frequency": config["frequency"],
            "ageDays": round(age_days, 1),
            "stale": stale,
            "refreshStatus": refresh_run["status"] if refresh_run else "cached",
            "refreshError": refresh_run["error"] if refresh_run else None,
        })
    confidence_quality = [
        item for item in metric_quality if item["metric"] in CONFIDENCE_METRICS
    ]
    confidence_available = [item for item in confidence_quality if item["available"]]
    confidence_freshness = [
        clamp(
            100.0
            * (
                1.0
                - float(item["ageDays"])
                / METRIC_QUALITY[item["metric"]]["staleDays"]
            )
        )
        for item in confidence_available
        if item["ageDays"] is not None
    ]
    availability = len(confidence_available) / len(CONFIDENCE_METRICS) * 100.0
    freshness = (
        statistics.fmean(confidence_freshness) if confidence_freshness else 0.0
    )
    cadence = (
        statistics.fmean(
            METRIC_QUALITY[item["metric"]]["cadenceScore"]
            for item in confidence_available
        )
        if confidence_available
        else 0.0
    )
    cache_health = (
        sum(not item["stale"] for item in confidence_available)
        / len(confidence_available)
        * 100.0
        if confidence_available
        else 0.0
    )
    confidence_components = [
        {"key": "availability", "label": "指标可用性", "value": availability, "weight": 40},
        {"key": "freshness", "label": "观测新鲜度", "value": freshness, "weight": 25},
        {"key": "frequency", "label": "数据频率", "value": cadence, "weight": 10},
        {"key": "staleness", "label": "缓存未过期", "value": cache_health, "weight": 25},
    ]
    confidence = sum(
        component["value"] * component["weight"] / 100.0
        for component in confidence_components
    )

    quality_by_metric = {item["metric"]: item for item in metric_quality}
    reversal_components: list[dict[str, Any]] = []
    def fresh_metric(metric: str) -> bool:
        quality = quality_by_metric.get(metric, {})
        return bool(quality.get("available") and not quality.get("stale"))

    funding_percentile = (
        derivatives["fundingPercentile30d"] if fresh_metric("FundingRate8h") else None
    )
    reversal_components.append({
        "key": "funding",
        "label": "资金费率降温",
        "score": 100.0 - funding_percentile if funding_percentile is not None else None,
        "detail": (
            f"8小时费率 {derivatives['fundingRate8h']:+.4f}%，30日百分位 {funding_percentile:.1f}%"
            if funding_percentile is not None
            else "等待资金费率历史"
        ),
    })
    open_interest_change = (
        derivatives["openInterestChange7d"] if fresh_metric("OpenInterestUSD") else None
    )
    reversal_components.append({
        "key": "openInterest",
        "label": "OI 7日趋势",
        "score": (
            clamp(50.0 + open_interest_change * 5.0)
            if open_interest_change is not None
            else None
        ),
        "detail": (
            f"7日变化 {open_interest_change:+.1f}%"
            if open_interest_change is not None
            else "等待本地快照积累满7日"
        ),
    })
    trade_flow = (
        derivatives["tradeFlowImbalance"] if fresh_metric("TradeCVDUSD") else None
    )
    reversal_components.append({
        "key": "tradeFlow",
        "label": "近期主动成交",
        "score": clamp((float(trade_flow) + 100.0) / 2.0) if trade_flow is not None else None,
        "detail": (
            f"最近 {derivatives['tradeCount']} 笔成交买卖量差 {float(trade_flow):+.1f}%"
            if trade_flow is not None
            else "等待近期主动成交数据"
        ),
    })
    book_imbalance = (
        derivatives["orderBookImbalance"]
        if fresh_metric("OrderBookImbalance25bps")
        else None
    )
    reversal_components.append({
        "key": "orderBook",
        "label": "25bps当前盘口",
        "score": (
            clamp((float(book_imbalance) + 100.0) / 2.0)
            if book_imbalance is not None
            else None
        ),
        "detail": (
            f"25bps当前深度差 {float(book_imbalance):+.1f}%"
            if book_imbalance is not None
            else "等待固定距离订单簿快照"
        ),
    })
    rr25_change = options["rr25Change24h"] if fresh_metric("RR25_30D") else None
    reversal_components.append({
        "key": "optionSkew",
        "label": "25Delta偏斜修复",
        "score": clamp(50.0 + rr25_change * 10.0) if rr25_change is not None else None,
        "detail": (
            f"30天 RR25 过去24小时变化 {rr25_change:+.2f} 波动率点"
            if rr25_change is not None
            else "等待 24 小时期权偏斜历史"
        ),
    })
    derivative_metrics = (
        "FundingRate8h",
        "OpenInterestUSD",
        "TradeCVDUSD",
        "OrderBookImbalance25bps",
    )
    derivatives_current = all(
        quality_by_metric.get(metric, {}).get("available")
        and not quality_by_metric.get(metric, {}).get("stale")
        for metric in derivative_metrics
    )
    cycle_component_by_key = {
        component["key"]: component for component in cycle_components
    }
    environment_component_by_key = {
        component["key"]: component for component in components
    }
    reversal_component_by_key = {
        component["key"]: component for component in reversal_components
    }

    onchain_bucket = weighted_bucket(
        "onchain",
        "链上估值",
        45,
        [
            {
                "key": "mvrvFamily",
                "label": "MVRV 家族",
                "weight": 55,
                "score": cycle_component_by_key.get("mvrv", {}).get("score"),
                "detail": "MVRV、NUPL 与已实现价格为同源证据，只计一次",
            },
            {
                "key": "cvdd",
                "label": "CVDD 近似值",
                "weight": 45,
                "score": cycle_component_by_key.get("cvdd", {}).get("score"),
                "detail": cycle_component_by_key.get("cvdd", {}).get(
                    "detail", "等待公开 CDD 历史"
                ),
            },
        ],
    )
    price_bucket = weighted_bucket(
        "priceCycle",
        "价格周期",
        25,
        [
            {
                "key": "drawdown",
                "label": "周期回撤",
                "weight": 35,
                "score": environment_component_by_key.get("drawdown", {}).get("score"),
                "detail": environment_component_by_key.get("drawdown", {}).get("detail"),
            },
            {
                "key": "ma200w",
                "label": "200 周均线",
                "weight": 35,
                "score": environment_component_by_key.get("ma200w", {}).get("score"),
                "detail": environment_component_by_key.get("ma200w", {}).get("detail"),
            },
            {
                "key": "mayer",
                "label": "Mayer Multiple",
                "weight": 30,
                "score": cycle_component_by_key.get("mayer", {}).get("score"),
                "detail": cycle_component_by_key.get("mayer", {}).get("detail"),
            },
        ],
    )
    macro_bucket = weighted_bucket(
        "macro",
        "宏观环境",
        30,
        [
            {
                "key": "netLiquidity",
                "label": "净流动性 30 日",
                "weight": 50,
                "score": environment_component_by_key.get("netLiquidity", {}).get("score"),
                "detail": environment_component_by_key.get("netLiquidity", {}).get("detail"),
            },
            {
                "key": "broadDollar",
                "label": "美元 90 日趋势",
                "weight": 25,
                "score": (
                    clamp(50.0 - macro["broadDollarChange90d"] * 10.0)
                    if macro["broadDollarChange90d"] is not None
                    else None
                ),
                "detail": (
                    f"90 日变化 {macro['broadDollarChange90d']:+.1f}%"
                    if macro["broadDollarChange90d"] is not None
                    else "等待 90 日美元指数历史"
                ),
            },
            {
                "key": "us10y",
                "label": "10 年期收益率",
                "weight": 25,
                "score": (
                    clamp(50.0 - macro["us10yChange90d"] * 25.0)
                    if macro["us10yChange90d"] is not None
                    else None
                ),
                "detail": (
                    f"90 日变化 {macro['us10yChange90d']:+.2f} 个百分点"
                    if macro["us10yChange90d"] is not None
                    else "等待 90 日收益率历史"
                ),
            },
        ],
    )
    long_term_buckets = [onchain_bucket, price_bucket, macro_bucket]
    long_term_score, long_term_coverage = combine_factor_buckets(
        long_term_buckets, minimum_groups=2
    )

    leverage_bucket = weighted_bucket(
        "leverage",
        "杠杆状态",
        25,
        [
            {
                "key": "funding",
                "label": "资金费率降温",
                "weight": 55,
                "score": reversal_component_by_key["funding"]["score"],
                "detail": reversal_component_by_key["funding"]["detail"],
            },
            {
                "key": "openInterest",
                "label": "OI 7 日趋势",
                "weight": 45,
                "score": reversal_component_by_key["openInterest"]["score"],
                "detail": reversal_component_by_key["openInterest"]["detail"],
            },
        ],
    )
    flow_bucket = weighted_bucket(
        "flow",
        "主动成交",
        30,
        [
            {
                "key": "tradeFlow",
                "label": "近期主动成交",
                "weight": 100,
                "score": reversal_component_by_key["tradeFlow"]["score"],
                "detail": reversal_component_by_key["tradeFlow"]["detail"],
            }
        ],
    )
    book_bucket = weighted_bucket(
        "book",
        "盘口结构",
        25,
        [
            {
                "key": "orderBook",
                "label": "25 bps 盘口",
                "weight": 100,
                "score": reversal_component_by_key["orderBook"]["score"],
                "detail": reversal_component_by_key["orderBook"]["detail"],
            },
        ],
    )
    option_bucket = weighted_bucket(
        "options",
        "期权确认",
        20,
        [
            {
                "key": "optionSkew",
                "label": "25Delta 偏斜修复",
                "weight": 100,
                "score": reversal_component_by_key["optionSkew"]["score"],
                "detail": reversal_component_by_key["optionSkew"]["detail"],
            }
        ],
    )
    reversal_buckets = [
        leverage_bucket, flow_bucket, book_bucket, option_bucket
    ]
    factor_reversal_score, factor_reversal_coverage = combine_factor_buckets(
        reversal_buckets, minimum_groups=3
    )
    if not derivatives_current:
        factor_reversal_score = None

    macro_proxy_by_date: dict[date, float] = {}
    if fed_series and tga_series and rrp_series:
        for point in fed_series:
            observed_at = datetime.fromisoformat(point["observedAt"])
            tga_point = nearest_before(tga_series, observed_at)
            rrp_point = nearest_before(rrp_series, observed_at)
            if tga_point and rrp_point:
                macro_proxy_by_date[observed_at.date()] = (
                    float(point["value"]) / 1000.0
                    - float(tga_point["value"]) / 1000.0
                    - float(rrp_point["value"])
                )
    price_30d = change_series(price_series, 30)
    price_365d = change_series(price_series, 365)
    mvrv_30d = change_series(mvrv_series, 30)
    dollar_90d = change_series(series["BroadDollar"], 90)
    stablecoin_30d = change_series(stablecoin_series, 30)
    m2_365d = change_series(series["USM2"], 365)
    liquidity_points = [
        {"observedAt": observed_at.isoformat(), "value": value}
        for observed_at, value in (
            (datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc), value)
            for day, value in sorted(macro_proxy_by_date.items())
        )
    ]
    liquidity_30d = change_series(liquidity_points, 30, percent=False)

    def correlation_item(
        key: str,
        label_a: str,
        label_b: str,
        left: dict[date, float],
        right: dict[date, float],
        note: str,
    ) -> dict[str, Any]:
        common_dates = sorted(set(left) & set(right))
        if common_dates:
            cutoff = common_dates[-1] - timedelta(days=365 * 5)
            common_dates = [day for day in common_dates if day >= cutoff]
        value = spearman_correlation(
            [left[day] for day in common_dates],
            [right[day] for day in common_dates],
        )
        return {
            "key": key,
            "left": label_a,
            "right": label_b,
            "value": round(value, 2) if value is not None else None,
            "samples": len(common_dates),
            "note": note,
        }

    correlations = [
        {
            "key": "mvrv-nupl",
            "left": "MVRV",
            "right": "NUPL",
            "value": 1.0,
            "samples": len(mvrv_series),
            "note": "代数同源，只保留一票",
            "structural": True,
        },
        correlation_item(
            "mvrv-price",
            "MVRV 30 日变化",
            "BTC 30 日变化",
            mvrv_30d,
            price_30d,
            "最近五年同日变化，降低趋势性伪相关",
        ),
        correlation_item(
            "liquidity-price",
            "净流动性 30 日变化",
            "BTC 30 日变化",
            liquidity_30d,
            price_30d,
            "按周频美联储观测日对齐",
        ),
        correlation_item(
            "dollar-price",
            "美元 90 日变化",
            "BTC 30 日变化",
            dollar_90d,
            price_30d,
            "不同窗口，仅作历史方向参考",
        ),
        correlation_item(
            "stablecoin-price",
            "稳定币供应 30 日变化",
            "BTC 30 日变化",
            stablecoin_30d,
            price_30d,
            "最近五年同日变化；同步相关不表示资金流领先价格",
        ),
        correlation_item(
            "m2-price",
            "美国 M2 12 个月变化",
            "BTC 12 个月变化",
            m2_365d,
            price_365d,
            "按月频 M2 观测日对齐；发布滞后且不表示因果",
        ),
    ]

    long_term_contributions = factor_contributions(long_term_buckets)
    factor_model = {
        "version": "2026-08-factor-experiment-v2",
        "longTerm": {
            "value": round(long_term_score) if long_term_score is not None else None,
            "label": status_label(long_term_score),
            "coverage": round(long_term_coverage),
            "buckets": long_term_buckets,
            "contributions": long_term_contributions,
        },
        "reversal": {
            "value": (
                round(factor_reversal_score)
                if factor_reversal_score is not None
                else None
            ),
            "label": reversal_status_label(factor_reversal_score),
            "coverage": round(factor_reversal_coverage),
            "buckets": reversal_buckets,
        },
        "confidence": round(confidence),
        "quadrant": {
            "x": round(long_term_score) if long_term_score is not None else None,
            "y": (
                round(factor_reversal_score)
                if factor_reversal_score is not None
                else None
            ),
            "status": (
                "confirmed"
                if long_term_score is not None
                and factor_reversal_score is not None
                and long_term_score >= 55
                and factor_reversal_score >= 55
                else "forming"
                if long_term_score is not None and long_term_score >= 55
                else "unconfirmed"
            ),
        },
        "correlations": correlations,
        "notes": [
            "MVRV、NUPL 与已实现价格同源，只在链上估值中合并计权一次。",
            "净流动性已包含 Fed、TGA 与 RRP，三个原始序列不重复评分。",
            "缺失项不计零分；因子覆盖不足 50% 时整组等待。",
            "盘口与近期成交属于 Deribit 单一市场的短周期线索，不是宏观长期底部证据。",
            "当前分数是手工阈值实验，尚未做历史回测，不代表概率、胜率或投资建议。",
            "反转模型至少需要三个因子组且衍生品数据未过期；这些组都来自 Deribit，缺失项显示等待，不填零分。",
        ],
    }

    data_as_of = max(
        (
            datetime.fromisoformat(points[-1]["observedAt"])
            for points in series.values()
            if points
        ),
        default=None,
    )

    return {
        "generatedAt": now.isoformat(),
        "dataAsOf": data_as_of.isoformat() if data_as_of else None,
        "scores": {
            "environment": {
                "value": round(long_term_score) if long_term_score is not None else None,
                "label": status_label(long_term_score),
                "coverage": f"{round(long_term_coverage)}%",
                "components": long_term_buckets,
            },
            "cycle": {
                "value": round(cycle_score) if cycle_score is not None else None,
                "label": cycle_status_label(cycle_score),
                "coverage": f"{len(scored_cycle_components)}/{len(cycle_components)}",
                "components": [
                    {
                        **component,
                        "score": (
                            round(component["score"])
                            if component["score"] is not None
                            else None
                        ),
                    }
                    for component in cycle_components
                ],
            },
            "reversal": {
                "value": (
                    round(factor_reversal_score)
                    if factor_reversal_score is not None
                    else None
                ),
                "label": reversal_status_label(factor_reversal_score),
                "coverage": f"{round(factor_reversal_coverage)}%",
                "components": reversal_buckets,
            },
            "confidence": {
                "value": round(confidence),
                "availability": round(availability),
                "freshness": round(freshness),
                "frequency": round(cadence),
                "cacheHealth": round(cache_health),
                "components": [
                    {**component, "value": round(component["value"])}
                    for component in confidence_components
                ],
            },
        },
        "market": market,
        "cycle": cycle,
        "macro": macro,
        "mining": mining,
        "derivatives": derivatives,
        "options": options,
        "factorModel": factor_model,
        "availableMetrics": available_metrics,
        "missingMetrics": [metric for metric in expected_metrics if not series[metric]],
        "dataQuality": metric_quality,
        "refresh": refresh_state,
    }
