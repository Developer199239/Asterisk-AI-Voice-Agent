"""
Lead Classification API — FastAPI route layer.

POST /api/lead/classify

Authentication: X-Api-Key header (LEAD_CLASSIFY_API_KEY in .env).
LLM logic  → llm/openai_client.py
Prompt     → prompts/lead_classify.py

After classification, if is_lead is true, the handler automatically
POSTs the lead to HOS via HOS_API_BASE_URL/api/v1/tools/leads.
"""

import json
import logging
import os
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from llm.openai_client import chat_completion_json
from prompts.lead_classify import build_messages, format_conversation

logger = logging.getLogger(__name__)

lead_classify_router = APIRouter(prefix="/lead", tags=["lead-classify"])


# ---------------------------------------------------------------------------
# Env helpers
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
    confidence: float = Field(..., description="Model confidence 0.0–1.0.", ge=0.0, le=1.0)
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
# Routing helper
# ---------------------------------------------------------------------------

def _derive_routing(confidence: float) -> str:
    if confidence > 0.90:
        return "auto_route"
    if confidence >= 0.70:
        return "needs_clarification"
    return "transfer_human"


# ---------------------------------------------------------------------------
# Lead save helper
# ---------------------------------------------------------------------------

# Lead types that warrant HIGH priority
_HIGH_PRIORITY_TYPES = {"emergency", "admission", "surgery", "icu"}


async def _save_lead(
    result: Dict[str, Any],
    caller_number: str,
    call_id: str,
    conversation_turns: List[Any],
) -> None:
    """POST lead to HOS API when is_lead is true. Errors are logged but never raised."""
    lead_type = result.get("lead_type") or "Other"
    intent = result.get("intent") or ""
    entities = result.get("entities") or {}

    name = (
        entities.get("patient")
        or entities.get("patient_name")
        or caller_number
        or "Unknown"
    )
    priority = "HIGH" if lead_type.lower() in _HIGH_PRIORITY_TYPES else "NORMAL"

    # Build conversation JSON — same shape as {transcript_json} in webhooks
    discussion_details = json.dumps(
        [{"role": t.role, "content": t.content} for t in conversation_turns],
        ensure_ascii=False,
    )

    payload = {
        "name": name,
        "phone": caller_number or "",
        "source": "AI_VOICE_AGENT",
        "interestedService": lead_type,
        "processingMode": "AI_AUTOMATED",
        "priority": priority,
        "assignedTo": "",
        "discussionSummary": intent,
        "discussionDetails": discussion_details,
    }

    hos_base = _env("HOS_API_BASE_URL", "http://168.144.27.225")
    hos_key = _env("HOS_API_KEY", "dev-api-key-replace-in-production")
    hos_tenant = _env("HOS_TENANT_ID", "1")
    url = f"{hos_base}/api/v1/tools/leads"

    request_headers = {
        "Content-Type": "application/json",
        "X-Tenant-ID": hos_tenant,
        "X-API-Key": hos_key,
    }

    logger.info("=" * 60)
    logger.info("LEAD SAVE REQUEST")
    logger.info("  call_id : %s", call_id)
    logger.info("  METHOD  : POST")
    logger.info("  URL     : %s", url)
    logger.info("  HEADERS :")
    for k, v in request_headers.items():
        logger.info("    %s: %s", k, v)
    logger.info("  BODY    :")
    logger.info("%s", json.dumps(payload, indent=4, ensure_ascii=False))
    logger.info("=" * 60)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=request_headers)

        logger.info("=" * 60)
        logger.info("LEAD SAVE RESPONSE")
        logger.info("  call_id    : %s", call_id)
        logger.info("  STATUS     : %d", resp.status_code)
        logger.info("  HEADERS    :")
        for k, v in resp.headers.items():
            logger.info("    %s: %s", k, v)
        logger.info("  BODY       :")
        try:
            logger.info("%s", json.dumps(resp.json(), indent=4, ensure_ascii=False))
        except Exception:
            logger.info("%s", resp.text)
        logger.info("=" * 60)

        if resp.status_code < 300:
            logger.info("LEAD SAVE SUCCESS: call_id=%s lead_type=%s", call_id, lead_type)
        else:
            logger.warning("LEAD SAVE FAILED: call_id=%s status=%d", call_id, resp.status_code)
    except Exception as exc:
        logger.error("LEAD SAVE ERROR: %s", exc, exc_info=True)


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
    # ── API key gate ─────────────────────────────────────────────────────────
    api_key = _lead_classify_api_key()
    if not api_key:
        logger.error("LEAD_CLASSIFY_API_KEY not set — endpoint disabled")
        raise HTTPException(
            status_code=503,
            detail="Set LEAD_CLASSIFY_API_KEY in .env and restart the Admin UI container.",
        )
    if not x_api_key or x_api_key != api_key:
        logger.warning(
            "Lead classify rejected — bad X-Api-Key (prefix: %s)",
            (x_api_key or "")[:6] or "(none)",
        )
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    # ── OpenAI key check ─────────────────────────────────────────────────────
    openai_key = _openai_api_key()
    if not openai_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not set in .env.")

    # ── Log request ──────────────────────────────────────────────────────────
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

    # ── Build prompt and call LLM ────────────────────────────────────────────
    conversation_text = format_conversation(req.conversation)
    messages = build_messages(conversation_text)

    try:
        result = await chat_completion_json(messages, openai_key)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Lead classify: unexpected error — %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Classification failed: {exc}")

    # ── Parse result ─────────────────────────────────────────────────────────
    is_lead: bool = bool(result.get("is_lead", False))
    lead_type: Optional[str] = result.get("lead_type") if is_lead else None
    intent: Optional[str] = result.get("intent") if is_lead else None
    confidence: float = float(result.get("confidence", 0.0))
    entities: Dict[str, Any] = result.get("entities", {}) if is_lead else {}
    routing = _derive_routing(confidence)

    # ── Save lead to HOS if detected ─────────────────────────────────────────
    if is_lead:
        await _save_lead(
            result=result,
            caller_number=req.caller_number or "",
            call_id=req.call_id or "",
            conversation_turns=req.conversation,
        )

    # ── Log response ─────────────────────────────────────────────────────────
    logger.info("LEAD CLASSIFY RESPONSE")
    logger.info("=" * 60)
    logger.info("  call_id       : %s", req.call_id or "(none)")
    logger.info("  caller_number : %s", req.caller_number or "(none)")
    logger.info("  is_lead       : %s", is_lead)
    logger.info("  lead_type     : %s", lead_type or "none")
    logger.info("  intent        : %s", intent or "none")
    logger.info("  confidence    : %.2f", confidence)
    logger.info("  routing       : %s", routing)
    logger.info("  entities      : %s", json.dumps(entities, ensure_ascii=False))
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
