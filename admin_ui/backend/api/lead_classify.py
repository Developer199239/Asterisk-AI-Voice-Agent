"""
Lead Classification API.

POST /api/lead/classify

Accepts a user/AI conversation, calls OpenAI to detect whether it contains
a hospital service lead, classifies the lead type, extracts key entities,
and returns structured JSON.

Authentication: X-Api-Key header — must match LEAD_CLASSIFY_API_KEY in .env.
No JWT required — designed for machine-to-machine calls (HIS, CRM backends).
"""

import logging
import os
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

lead_classify_router = APIRouter(prefix="/lead", tags=["lead-classify"])

# ---------------------------------------------------------------------------
# Env helpers (same pattern as outbound_trigger.py)
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    val = (os.getenv(key) or "").strip()
    if val:
        return val
    project_root = os.environ.get("PROJECT_ROOT", "/app/project")
    env_path = os.path.join(project_root, ".env")
    try:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    if k.strip() == key:
                        return v.strip().strip('"').strip("'")
    except Exception:
        pass
    return default


def _lead_classify_api_key() -> str:
    return _env("LEAD_CLASSIFY_API_KEY", "")


def _openai_api_key() -> str:
    return _env("OPENAI_API_KEY", "")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ConversationTurn(BaseModel):
    role: Literal["user", "assistant"] = Field(
        ...,
        description="Speaker: 'user' for patient, 'assistant' for AI agent.",
    )
    content: str = Field(..., description="Spoken text for this turn.")


class LeadClassifyRequest(BaseModel):
    conversation: List[ConversationTurn] = Field(
        ...,
        min_length=1,
        description="Full conversation turns in chronological order.",
    )
    caller_number: Optional[str] = Field(
        default=None,
        description="Caller phone number (E.164 or local format). Passed through to response.",
    )
    call_id: Optional[str] = Field(
        default=None,
        description="Optional session/call identifier. Passed through to response.",
    )


class LeadClassifyResponse(BaseModel):
    is_lead: bool = Field(..., description="True if the conversation contains a service lead.")
    lead_type: Optional[str] = Field(
        default=None,
        description=(
            "Lead category. One of: Appointment, Diagnostic Test, Cabin Booking, Surgery, "
            "Admission, Health Package, Home Sample Collection, Ambulance, Follow-up, "
            "Billing, Emergency, Pharmacy, Test Report, Other. Null if is_lead is false."
        ),
    )
    intent: Optional[str] = Field(
        default=None,
        description="Short description of what the caller wants. Null if is_lead is false.",
    )
    confidence: float = Field(
        ...,
        description="Model confidence 0.0–1.0.",
        ge=0.0,
        le=1.0,
    )
    routing: Literal["auto_route", "needs_clarification", "transfer_human"] = Field(
        ...,
        description=(
            "Suggested action: "
            "auto_route (confidence > 0.90), "
            "needs_clarification (0.70–0.90), "
            "transfer_human (< 0.70)."
        ),
    )
    entities: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted entities (date, patient, test_name, cabin_type, etc.).",
    )
    call_id: Optional[str] = Field(default=None)
    caller_number: Optional[str] = Field(default=None)


# ---------------------------------------------------------------------------
# LLM prompt + classification logic
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a hospital conversation classifier for Smart Doctor Clinic.

Your job is to analyse a patient/AI conversation and return structured JSON.

Determine:
1. Is this conversation a lead (patient wants a hospital service)?
2. What is the lead type?
3. What is the caller's intent?
4. Extract all relevant entities (dates, names, test names, cabin types, etc.).
5. Assign a confidence score 0.0–1.0 for your classification.

Possible lead types (pick the closest match):
- Appointment
- Diagnostic Test
- Cabin Booking
- Surgery
- Admission
- Health Package
- Home Sample Collection
- Ambulance
- Follow-up
- Billing
- Emergency
- Pharmacy
- Test Report
- Other

Return ONLY a valid JSON object with this exact structure:
{
  "is_lead": true or false,
  "lead_type": "string or null",
  "intent": "short description or null",
  "confidence": 0.0 to 1.0,
  "entities": {
    "any relevant key-value pairs extracted from the conversation"
  }
}

Rules:
- is_lead is false for greetings, farewells, or completely off-topic conversations.
- lead_type and intent must be null when is_lead is false.
- entities may be empty {} if nothing specific was mentioned.
- confidence must reflect how certain you are about your classification.
- Do not add any text outside the JSON object."""


def _format_conversation(turns: List[ConversationTurn]) -> str:
    lines = []
    for turn in turns:
        speaker = "Patient" if turn.role == "user" else "AI Agent"
        lines.append(f"{speaker}: {turn.content}")
    return "\n".join(lines)


def _derive_routing(confidence: float) -> str:
    if confidence > 0.90:
        return "auto_route"
    if confidence >= 0.70:
        return "needs_clarification"
    return "transfer_human"


async def _call_openai(conversation_text: str, openai_key: str) -> Dict[str, Any]:
    payload = {
        "model": "gpt-4o-mini",
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Classify this conversation:\n\n{conversation_text}",
            },
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {openai_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code != 200:
        logger.error(
            "OpenAI API error — status=%s body=%s",
            response.status_code,
            response.text[:500],
        )
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI API returned HTTP {response.status_code}",
        )

    data = response.json()
    import json as _json
    raw = data["choices"][0]["message"]["content"]
    return _json.loads(raw)


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@lead_classify_router.post(
    "/classify",
    response_model=LeadClassifyResponse,
    summary="Classify a conversation for hospital service leads",
    description=(
        "Accepts a user/AI conversation transcript and uses OpenAI to detect "
        "whether it contains a hospital service lead, extract entities, and "
        "return a structured classification. "
        "Authenticates via `X-Api-Key` header (set `LEAD_CLASSIFY_API_KEY` in .env). "
        "No JWT required — designed for machine-to-machine calls."
    ),
)
async def classify_lead(
    req: LeadClassifyRequest,
    x_api_key: Optional[str] = Header(
        default=None,
        description="Shared API key. Must match LEAD_CLASSIFY_API_KEY in .env.",
    ),
):
    # ── API key gate ────────────────────────────────────────────────────────
    api_key = _lead_classify_api_key()
    if not api_key:
        logger.error("LEAD_CLASSIFY_API_KEY not set in .env — lead classify endpoint is disabled")
        raise HTTPException(
            status_code=503,
            detail=(
                "Lead classify is not configured. "
                "Set LEAD_CLASSIFY_API_KEY in .env and restart the Admin UI container."
            ),
        )
    if not x_api_key or x_api_key != api_key:
        logger.warning(
            "Lead classify: rejected — invalid or missing X-Api-Key (prefix: %s)",
            (x_api_key or "")[:6] or "(none)",
        )
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # ── OpenAI key check ────────────────────────────────────────────────────
    openai_key = _openai_api_key()
    if not openai_key:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY not set in .env.",
        )

    conversation_text = _format_conversation(req.conversation)

    # ── Request details ─────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("LEAD CLASSIFY REQUEST")
    logger.info("=" * 60)
    logger.info("  call_id       : %s", req.call_id or "(none)")
    logger.info("  caller_number : %s", req.caller_number or "(none)")
    logger.info("  turns         : %d", len(req.conversation))
    logger.info("  conversation  :")
    for i, turn in enumerate(req.conversation, 1):
        logger.info("    [%d] %s: %s", i, turn.role.upper(), turn.content)
    logger.info("=" * 60)

    try:
        result = await _call_openai(conversation_text, openai_key)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Lead classify: unexpected error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Classification failed: {exc}")

    is_lead: bool = bool(result.get("is_lead", False))
    lead_type: Optional[str] = result.get("lead_type") if is_lead else None
    intent: Optional[str] = result.get("intent") if is_lead else None
    confidence: float = float(result.get("confidence", 0.0))
    entities: Dict[str, Any] = result.get("entities", {}) if is_lead else {}
    routing = _derive_routing(confidence)

    # ── Response details ─────────────────────────────────────────────────────
    import json as _json
    logger.info("LEAD CLASSIFY RESPONSE")
    logger.info("=" * 60)
    logger.info("  call_id       : %s", req.call_id or "(none)")
    logger.info("  caller_number : %s", req.caller_number or "(none)")
    logger.info("  is_lead       : %s", is_lead)
    logger.info("  lead_type     : %s", lead_type or "none")
    logger.info("  intent        : %s", intent or "none")
    logger.info("  confidence    : %.2f", confidence)
    logger.info("  routing       : %s", routing)
    logger.info("  entities      : %s", _json.dumps(entities, ensure_ascii=False))
    logger.info("=" * 60)

    return LeadClassifyResponse(
        is_lead=is_lead,
        lead_type=lead_type,
        intent=intent,
        confidence=confidence,
        routing=routing,
        entities=entities,
        call_id=req.call_id,
        caller_number=req.caller_number,
    )
