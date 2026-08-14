from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator


@dataclass(frozen=True, slots=True)
class DataPoint:
    source: str
    metric: str
    observed_at: datetime
    value: float
    unit: str
    fetched_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectorResult:
    source: str
    points: list[DataPoint]
    source_url: str
    description: str
    expected_metrics: tuple[str, ...] = ()
    metric_errors: dict[str, str] = field(default_factory=dict)


class CvddReferenceInput(BaseModel):
    source_name: str = Field(min_length=2, max_length=100)
    source_url: str = Field(min_length=8, max_length=500)
    observed_date: date
    value_usd: float = Field(gt=0, le=10_000_000)
    note: str | None = Field(default=None, max_length=500)

    @field_validator("source_name")
    @classmethod
    def normalize_source_name(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if len(normalized) < 2:
            raise ValueError("source_name is too short")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        normalized = value.strip()
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("source_url must be a complete http:// or https:// URL")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("source_url must not contain credentials")
        if any(character.isspace() for character in normalized):
            raise ValueError("source_url must not contain whitespace")
        return urlunsplit(
            (
                parsed.scheme.lower(),
                parsed.netloc,
                parsed.path,
                parsed.query,
                parsed.fragment,
            )
        )

    @field_validator("observed_date")
    @classmethod
    def validate_observed_date(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("observed_date cannot be in the future")
        return value
