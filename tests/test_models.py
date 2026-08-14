from datetime import date

import pytest
from pydantic import ValidationError

from app.models import CvddReferenceInput


def test_cvdd_reference_input_validates_public_page_and_positive_value() -> None:
    payload = CvddReferenceInput(
        source_name="  CoinGlass  ",
        source_url="https://www.coinglass.com/example",
        observed_date=date(2026, 8, 14),
        value_usd=45000,
    )

    assert payload.source_name == "CoinGlass"
    assert payload.value_usd == 45000

    with pytest.raises(ValidationError):
        CvddReferenceInput(
            source_name="x",
            source_url="not-a-url",
            observed_date=date(2026, 8, 14),
            value_usd=-1,
        )

    for invalid_url in (
        "https://",
        "https://user:secret@example.com/chart",
        "javascript:alert(1)",
        "https://example.com/a b",
    ):
        with pytest.raises(ValidationError):
            CvddReferenceInput(
                source_name="Source A",
                source_url=invalid_url,
                observed_date=date(2026, 8, 14),
                value_usd=45000,
            )
