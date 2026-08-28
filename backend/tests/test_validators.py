from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.validators import (
    compute_missing_fields,
    format_confirmation_summary,
    format_display_date,
    is_valid_indian_vehicle,
    normalize_freight_amount,
    normalize_vehicle_number,
    resolve_relative_date,
)


def test_normalize_vehicle_number():
    assert normalize_vehicle_number("HR 55 AB 1234") == "HR55AB1234"
    assert normalize_vehicle_number("hr-55-ab-1234") == "HR55AB1234"


def test_indian_vehicle_validation():
    assert is_valid_indian_vehicle("HR55AB1234") is True
    assert is_valid_indian_vehicle("INVALID") is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("42000", 42000.0),
        ("42 hazaar", 42000.0),
        ("42k", 42000.0),
        ("1.5 lakh", 150000.0),
        ("Rs 42,000", 42000.0),
    ],
)
def test_normalize_freight_amount(raw, expected):
    assert normalize_freight_amount(raw) == expected


def test_resolve_kal_date():
    ref = datetime(2026, 8, 28, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    iso, clarification = resolve_relative_date("kal", timezone="Asia/Kolkata", reference=ref)
    assert iso == "2026-08-29"
    assert clarification is None


def test_format_display_date_dd_mm_yy():
    assert format_display_date("2026-08-29") == "29/08/26"
    assert format_display_date("2023-10-24") == "24/10/23"


def test_confirmation_summary_uses_dd_mm_yy():
    summary = format_confirmation_summary(
        9,
        {
            "vehicle_number": "HR55AB1234",
            "origin": "Gurgaon",
            "destination": "Jaipur",
            "pickup_date": "2026-08-29",
            "pickup_window": None,
            "customer_name": "ABC party",
            "freight_amount": 42000,
            "driver_name": "Rakesh",
        },
    )
    assert "Pickup: 29/08/26," in summary
    assert "2026-08-29" not in summary


def test_compute_missing_fields():
    fields = {"origin": "Gurgaon", "destination": None}
    config = {"origin": True, "destination": True, "freight_amount": True}
    missing = compute_missing_fields(fields, config)
    assert "destination" in missing
    assert "freight_amount" in missing
    assert "origin" not in missing
