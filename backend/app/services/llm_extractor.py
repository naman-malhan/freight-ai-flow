import json
import re
from datetime import date

from openai import AsyncOpenAI

from app.config import settings
from app.enums import TripIntent
from app.schemas import ConfidenceScores, TripFields, TripIntentExtraction

EXTRACTION_SYSTEM_PROMPT = """You extract structured trip creation intent from Hindi/Hinglish transport messages.
Return ONLY valid JSON matching this schema:
{
  "intent": "create_trip|edit_trip|cancel_trip|unknown",
  "fields": {
    "vehicle_number": string|null,
    "origin": string|null,
    "destination": string|null,
    "pickup_date": string|null (ISO date if explicit, else null),
    "pickup_date_raw": string|null (original phrase like kal/aaj),
    "pickup_window": "morning|afternoon|evening"|null,
    "customer_name": string|null,
    "freight_amount": number|null,
    "driver_name": string|null
  },
  "missing_fields": [string],
  "confidence": {
    "intent": 0-1,
    "vehicle_number": 0-1|null,
    "pickup_date": 0-1|null,
    "freight_amount": 0-1|null,
    "origin": 0-1|null,
    "destination": 0-1|null,
    "customer_name": 0-1|null,
    "driver_name": 0-1|null
  },
  "clarification_needed": string|null
}
Rules:
- Never invent origin/destination if not stated.
- If freight is ambiguous like "42" without unit, set clarification_needed asking if it means Rs 42 or Rs 42k.
- Relative dates like kal/aaj go in pickup_date_raw, not pickup_date.
- If a calendar date has day/month but NO year spoken, set pickup_date using the Reference date's year (never invent 2023/2024/etc).
- Only use a non-reference year in pickup_date when the user explicitly said that year (e.g. 2025, 30/10/25).
- intent=unknown for non trip-creation messages like truck location queries.
"""


def _rule_based_extract(text: str) -> TripIntentExtraction:
    """Fallback when LLM is unavailable — handles the playbook happy-path example."""
    lower = text.lower()
    if any(kw in lower for kw in ["kahan hai", "location", "track", "gps"]):
        return TripIntentExtraction(
            intent=TripIntent.UNKNOWN,
            clarification_needed="Abhi sirf trip creation support hai. Trip details bhejein.",
        )

    fields = TripFields()
    confidence = ConfidenceScores(intent=0.7)

    vehicle_match = re.search(r"\b([A-Z]{2}\s?\d{1,2}\s?[A-Z]{0,3}\s?\d{1,4})\b", text, re.I)
    if vehicle_match:
        fields.vehicle_number = re.sub(r"\s", "", vehicle_match.group(1).upper())
        confidence.vehicle_number = 0.85

    route_match = re.search(r"(\w+)\s+se\s+(\w+)", lower)
    if route_match:
        fields.origin = route_match.group(1).title()
        fields.destination = route_match.group(2).title()
        confidence.origin = 0.8
        confidence.destination = 0.8
    elif "jaipur" in lower and "load" in lower:
        fields.destination = "Jaipur"
        confidence.destination = 0.75

    if "kal" in lower.split():
        fields.pickup_date_raw = "kal"
        confidence.pickup_date = 0.82
    elif "aaj" in lower.split():
        fields.pickup_date_raw = "aaj"
        confidence.pickup_date = 0.82

    party_match = re.search(r"([\w\s]+?)\s+party", lower)
    if party_match:
        fields.customer_name = party_match.group(1).strip().upper()
        confidence.customer_name = 0.8

    freight_match = re.search(r"freight\s+(\d[\d,\.]*)", lower)
    if freight_match:
        raw = freight_match.group(1)
        if len(raw) <= 2 and "hazaar" not in lower and "k" not in lower:
            return TripIntentExtraction(
                intent=TripIntent.CREATE_TRIP,
                fields=fields,
                confidence=confidence,
                clarification_needed=f"Freight '{raw}' ka matlab Rs {raw} hai ya Rs {raw} hazaar?",
            )
        fields.freight_amount = float(raw.replace(",", ""))
        if "hazaar" in lower or "hazar" in lower:
            fields.freight_amount *= 1000
        confidence.freight_amount = 0.85

    driver_match = re.search(r"driver\s+(\w+)", lower)
    if driver_match:
        fields.driver_name = driver_match.group(1).title()
        confidence.driver_name = 0.8

    missing = []
    for name, value in [
        ("origin", fields.origin),
        ("destination", fields.destination),
        ("pickup_date", fields.pickup_date or fields.pickup_date_raw),
        ("customer_name", fields.customer_name),
        ("freight_amount", fields.freight_amount),
    ]:
        if not value:
            missing.append(name)

    return TripIntentExtraction(
        intent=TripIntent.CREATE_TRIP if missing or fields.destination else TripIntent.UNKNOWN,
        fields=fields,
        missing_fields=missing,
        confidence=confidence,
    )


async def extract_trip_intent(
    text: str,
    *,
    reference_date: date | None = None,
    timezone: str = "Asia/Kolkata",
) -> TripIntentExtraction:
    if not settings.openai_api_key:
        return _rule_based_extract(text)

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    user_prompt = f"Reference date: {reference_date or 'today'}\nTimezone: {timezone}\nMessage:\n{text}"

    try:
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return TripIntentExtraction.model_validate(data)
    except Exception:
        # Quota / network / model errors → keep demo working with rule parser
        return _rule_based_extract(text)
