import hashlib
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import parser as date_parser
from dateutil.relativedelta import relativedelta

from app.config import settings

# Explicit calendar year in user text: 2026, or 30/10/23, or 30-10-2025
_EXPLICIT_YEAR_RE = re.compile(
    r"(?:\b(?:19|20)\d{2}\b|\b\d{1,2}[/.\-]\d{1,2}[/.\-](\d{2}|\d{4})\b)",
    re.IGNORECASE,
)

INDIAN_VEHICLE_PATTERN = re.compile(
    r"^[A-Z]{2}[0-9]{1,2}[A-Z]{0,3}[0-9]{1,4}$",
    re.IGNORECASE,
)

FIELD_PRIORITY = [
    "origin",
    "destination",
    "pickup_date",
    "customer_name",
    "freight_amount",
    "pickup_window",
    "vehicle_number",
    "driver_name",
]

FIELD_QUESTIONS_HI = {
    "origin": "Load kahan se uthega? Origin batayein.",
    "destination": "Maal kahan jayega? Destination batayein.",
    "pickup_date": "Pickup kab hai? Date ya 'kal' / 'aaj' likhein.",
    "pickup_window": "Pickup subah hai, dopahar ya shaam?",
    "customer_name": "Kaunsi party / customer ka maal hai?",
    "freight_amount": "Freight kitna hai? Amount batayein (jaise 42000 ya 42 hazaar).",
    "vehicle_number": "Kaunsi gaadi jayegi? Vehicle number batayein.",
    "driver_name": "Driver ka naam kya hai?",
}

LOW_CONFIDENCE_THRESHOLD = 0.75


def normalize_vehicle_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[\s\-]", "", value.strip().upper())
    return cleaned or None


def is_valid_indian_vehicle(value: str | None) -> bool:
    if not value:
        return False
    return bool(INDIAN_VEHICLE_PATTERN.match(value))


def normalize_freight_amount(value: str | float | int | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None

    text = str(value).lower().strip()
    text = re.sub(r"₹|rs\.?", "", text, flags=re.I)
    text = text.replace(",", "").strip()
    if not text:
        return None

    multiplier = 1.0
    if "hazaar" in text or "hazar" in text or text.endswith("k"):
        multiplier = 1000.0
        text = re.sub(r"(hazaar|hazar|k)$", "", text)
    elif "lakh" in text or "lac" in text:
        multiplier = 100000.0
        text = re.sub(r"(lakh|lac)$", "", text)

    text = re.sub(r"[^0-9.]", "", text)
    if not text:
        return None

    try:
        amount = float(text) * multiplier
    except ValueError:
        return None
    return amount if amount > 0 else None


def phrase_mentions_year(phrase: str | None) -> bool:
    """True only when the user (or transcript) explicitly included a calendar year."""
    if not phrase or not str(phrase).strip():
        return False
    return bool(_EXPLICIT_YEAR_RE.search(str(phrase)))


def coerce_pickup_year(
    iso_date: str | None,
    *,
    phrase: str | None,
    timezone: str,
    reference: datetime | None = None,
) -> str | None:
    """If no year was spoken, force the reference/current year (e.g. 2026)."""
    if not iso_date:
        return None
    text = str(iso_date).strip()
    try:
        parsed = date.fromisoformat(text[:10])
    except ValueError:
        try:
            parsed = date_parser.parse(text).date()
        except (ValueError, TypeError, OverflowError):
            return iso_date

    if phrase_mentions_year(phrase):
        return parsed.isoformat()

    tz = ZoneInfo(timezone)
    now = reference or datetime.now(tz)
    return parsed.replace(year=now.year).isoformat()


def resolve_relative_date(
    phrase: str | None,
    *,
    timezone: str,
    reference: datetime | None = None,
) -> tuple[str | None, str | None]:
    """Return (iso_date, clarification) from Hindi/Hinglish relative phrases."""
    if not phrase:
        return None, None

    raw = phrase.strip()
    lower = raw.lower()
    tz = ZoneInfo(timezone)
    now = reference or datetime.now(tz)
    today = now.date()

    mapping = {
        "aaj": today,
        "today": today,
        "kal": today + timedelta(days=1),
        "tomorrow": today + timedelta(days=1),
        "parso": today + timedelta(days=2),
        "parson": today + timedelta(days=2),
    }
    for key, resolved in mapping.items():
        if key in lower.split():
            return resolved.isoformat(), None

    try:
        parsed = date_parser.parse(raw, fuzzy=True, default=now.replace(hour=9, minute=0))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        iso = parsed.date().isoformat()
        return coerce_pickup_year(iso, phrase=raw, timezone=timezone, reference=now), None
    except (ValueError, OverflowError):
        return None, f"Pickup date samajh nahi aayi: '{raw}'. Date ya 'kal'/'aaj' likhein."


def hash_payload(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def compute_missing_fields(fields: dict, required_config: dict) -> list[str]:
    missing = []
    for field_name, is_required in required_config.items():
        if not is_required:
            continue
        value = fields.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing


def next_missing_field(missing_fields: list[str]) -> str | None:
    for field in FIELD_PRIORITY:
        if field in missing_fields:
            return field
    return missing_fields[0] if missing_fields else None


def question_for_field(field: str) -> str:
    return FIELD_QUESTIONS_HI.get(field, f"{field} batayein.")


def low_confidence_fields(confidence: dict, fields: dict, required_config: dict) -> list[str]:
    flagged = []
    for field_name in required_config:
        if not fields.get(field_name):
            continue
        score = confidence.get(field_name)
        if score is not None and score < LOW_CONFIDENCE_THRESHOLD:
            flagged.append(field_name)
    intent_score = confidence.get("intent")
    if intent_score is not None and intent_score < LOW_CONFIDENCE_THRESHOLD:
        flagged.append("intent")
    return flagged


def draft_expires_at(timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    return datetime.now(tz) + timedelta(hours=settings.draft_expiry_hours)


def format_display_date(value: str | None) -> str:
    """Format stored ISO date (YYYY-MM-DD) as DD/MM/YYYY for WhatsApp replies."""
    if not value:
        return ""
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text[:10], fmt).strftime("%d/%m/%Y")
        except ValueError:
            continue
    try:
        return date_parser.parse(text).date().strftime("%d/%m/%Y")
    except (ValueError, TypeError, OverflowError):
        return text


def format_confirmation_summary(draft_id: int, fields: dict) -> str:
    pickup = format_display_date(fields.get("pickup_date")) or fields.get("pickup_date") or ""
    lines = [
        f"Trip draft #D-{draft_id}",
        f"Vehicle: {fields.get('vehicle_number') or 'Unassigned'}",
        f"Route: {fields.get('origin')} -> {fields.get('destination')}",
        f"Pickup: {pickup}, {(fields.get('pickup_window') or 'Any time').title()}",
        f"Customer: {fields.get('customer_name')}",
        f"Freight: Rs {int(fields.get('freight_amount', 0)):,}",
        f"Driver: {fields.get('driver_name') or 'Unassigned'}",
    ]
    return "\n".join(lines)
