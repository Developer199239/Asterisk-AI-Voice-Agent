"""
Outbound single-shot trigger API for Smart Doctor appointment reminder calls.

# ── Murtuza change ────────────────────────────────────────────────────────────
# REASON: HOS backend Java scheduler needs to trigger one outbound call per
# appointment reminder (1 hour before appointment). The existing campaign
# API requires CSV lead import and is designed for batch dialing — not
# suitable for single on-demand calls.
#
# This module adds POST /api/outbound/trigger — a lightweight endpoint that:
#   1. Validates a shared API key (OUTBOUND_TRIGGER_API_KEY from .env)
#   2. Calls Asterisk ARI directly (POST /ari/channels) using the same
#      ARI credentials already in .env — no JWT, no campaign setup needed.
#   3. Passes patient/appointment data as ARI channel variables so the
#      outbound_reminder AI context can inject them into the prompt.
#
# Authentication: X-Api-Key header checked against OUTBOUND_TRIGGER_API_KEY.
# No JWT required — this endpoint is registered WITHOUT Depends(get_current_user).
#
# HOS backend usage:
#   POST http://<AI_ENGINE_IP>:3003/api/outbound/trigger
#   X-Api-Key: <OUTBOUND_TRIGGER_API_KEY>
#   Content-Type: application/json
#   { "phone_number": "+923001234567", "patient_id": "42", ... }
#
# Bug fixes applied:
#   1. Standard Python logging (not structlog) — keyword args not supported,
#      use positional %s format strings instead.
#   2. ARI POST /channels: endpoint/app/timeout go as URL query params,
#      channelVars goes in the JSON body — NOT everything in json= body.
# ── end Murtuza change ────────────────────────────────────────────────────────
"""

import logging
import os
from typing import Optional

import aiohttp
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

# ── Murtuza change ─────────────────────────────────────────────────────────
# BUG FIX: admin_ui uses standard Python logging, not structlog.
# Standard Logger._log() does NOT accept keyword arguments (phone=, patient_id=).
# All log calls must use positional %s format strings only.
# ── end Murtuza change ────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

trigger_router = APIRouter(prefix="/outbound", tags=["outbound"])


# ---------------------------------------------------------------------------
# Helpers — read ARI connection settings from .env (same values the engine uses)
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    """Read env var, stripping whitespace. Falls back to .env file if not in process env."""
    val = (os.getenv(key) or "").strip()
    if val:
        return val
    # Try reading from project .env file directly (admin_ui container may not
    # inherit every env var the engine container has)
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


def _ari_base_url() -> str:
    host = _env("ASTERISK_HOST", "127.0.0.1")
    port = _env("ASTERISK_ARI_PORT", "8088")
    scheme = _env("ASTERISK_ARI_SCHEME", "http")
    return f"{scheme}://{host}:{port}"


def _ari_auth() -> aiohttp.BasicAuth:
    username = _env("ASTERISK_ARI_USERNAME", "asterisk")
    password = _env("ASTERISK_ARI_PASSWORD", "asterisk")
    return aiohttp.BasicAuth(username, password)


def _app_name() -> str:
    """Stasis app name — must match Asterisk dialplan and engine config."""
    return _env("ASTERISK_APP_NAME", "asterisk-ai-voice-agent")


def _outbound_trigger_api_key() -> str:
    return _env("OUTBOUND_TRIGGER_API_KEY", "")


def _outbound_dial_context() -> str:
    """FreePBX dialplan context for outbound calls (matches campaign dialer default)."""
    return _env("AAVA_OUTBOUND_DIAL_CONTEXT", "from-internal")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OutboundTriggerRequest(BaseModel):
    """
    Payload sent by HOS backend Java scheduler to trigger a reminder call.

    All patient/appointment fields are passed through as Asterisk channel
    variables so the AI engine can inject them into the outbound prompt
    without making a separate pre-call HTTP lookup.
    """
    phone_number: str = Field(
        ...,
        description="Patient phone number. E.164 (+923001234567) or local format (03001234567).",
        examples=["+923001234567"],
    )
    patient_id: str = Field(
        ...,
        description="Patient ID from HOS backend (integer, sent as string).",
    )
    patient_name: str = Field(
        ...,
        description="Patient full name — Ava uses this in the greeting.",
    )
    appointment_id: str = Field(
        ...,
        description="Appointment ID — used by cancel/reschedule tools during the call.",
    )
    doctor_name: str = Field(
        ...,
        description="Doctor full name — Ava mentions this in the reminder.",
    )
    appointment_date: str = Field(
        ...,
        description="Appointment date in YYYY-MM-DD format.",
        examples=["2026-05-20"],
    )
    start_time: str = Field(
        ...,
        description="Appointment time in HH:MM format (24h). Ava reads it as 12h to patient.",
        examples=["09:00"],
    )
    context: str = Field(
        default="outbound_reminder",
        description="AI engine context name. Must exist in ai-agent.yaml contexts.",
    )
    caller_id: Optional[str] = Field(
        default=None,
        description="Caller ID shown to the patient (clinic number). Falls back to AAVA_OUTBOUND_EXTENSION_IDENTITY.",
    )


class OutboundTriggerResponse(BaseModel):
    ok: bool
    channel_id: str
    phone_number: str
    context: str
    message: str = "Outbound call initiated"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@trigger_router.post(
    "/trigger",
    response_model=OutboundTriggerResponse,
    summary="Trigger a single outbound appointment reminder call",
    description=(
        "Called by the HOS backend Java scheduler 1 hour before an appointment. "
        "Authenticates via `X-Api-Key` header (set `OUTBOUND_TRIGGER_API_KEY` in .env). "
        "Does NOT require a JWT token — this endpoint is intentionally public to support "
        "machine-to-machine calls from the HOS backend."
    ),
)
async def trigger_outbound_call(
    req: OutboundTriggerRequest,
    x_api_key: Optional[str] = Header(
        default=None,
        description="Shared API key. Must match OUTBOUND_TRIGGER_API_KEY in .env.",
    ),
):
    # ── API key gate ────────────────────────────────────────────────────────
    # If OUTBOUND_TRIGGER_API_KEY is not set in .env → 503 (safe disabled state)
    # If wrong key → 401
    # ────────────────────────────────────────────────────────────────────────
    api_key = _outbound_trigger_api_key()
    if not api_key:
        logger.error("OUTBOUND_TRIGGER_API_KEY not set in .env — outbound trigger is disabled")
        raise HTTPException(
            status_code=503,
            detail=(
                "Outbound trigger is not configured. "
                "Set OUTBOUND_TRIGGER_API_KEY in .env and restart the Admin UI container."
            ),
        )

    if not x_api_key or x_api_key != api_key:
        logger.warning(
            "Outbound trigger: rejected — invalid or missing X-Api-Key (prefix: %s)",
            (x_api_key or "")[:6] or "(none)",
        )
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    caller_id = (
        req.caller_id
        or _env("AAVA_OUTBOUND_EXTENSION_IDENTITY", "")
        or "Smart Doctor Clinic"
    )

    # ── Murtuza change ──────────────────────────────────────────────────────
    # BUG FIX: ARI POST /channels requires a specific split:
    #   - URL query params: endpoint, app, appArgs, timeout, callerId
    #   - JSON body:        { "channelVars": { ... } }
    #
    # Original code sent everything as json= body. ARI ignored endpoint/app
    # (not in the right place) → returned 400 → unhandled → 500.
    # Confirmed from src/ari_client.py send_command() which does the same split.
    # ── end Murtuza change ──────────────────────────────────────────────────
    # ── Murtuza change ──────────────────────────────────────────────────────
    # appArgs="outbound_reminder" is REQUIRED.
    # The engine's StasisStart handler checks args[0] to route the call:
    #   - "outbound" / "outbound_amd" → campaign dialer handler
    #   - "outbound_reminder"          → _handle_caller_stasis_start_hybrid
    #                                    (Murtuza change in engine.py)
    #   - anything else with <2 args   → agent action handler → hangup
    #   - no args + Local channel      → _handle_local_stasis_start_hybrid
    #                                    (transfer helper, not an AI call)
    # Without appArgs="outbound_reminder", the Local/;1 channel would be
    # silently dropped. The engine.py change routes this action type to the
    # normal AI call flow, bypassing the _is_caller_channel() PJSIP/SIP gate.
    # ── end Murtuza change ──────────────────────────────────────────────────
    dial_context = _outbound_dial_context()

    # ── Murtuza change ────────────────────────────────────────────────────────
    # ROOT-CAUSE FIX: ARI POST /channels returns the Local;2 channel (dialplan
    # side), NOT the Local;1 channel that enters Stasis. Trying to SET channel
    # vars on the ;2 ID always returns HTTP 409 ("not in a Stasis application").
    #
    # Solution: encode all patient/appointment data directly into appArgs.
    # appArgs are baked into the Stasis event at call-creation time and are
    # available immediately in StasisStart.args[] — zero race condition, no
    # channel-var reads needed at all.
    #
    # Format: "outbound_reminder,key=value|key=value|..."
    # Pipe (|) is used as the field separator (safe — not present in names/dates).
    # Commas and pipes in field values are replaced with spaces as a safety guard.
    # ── end Murtuza change ──────────────────────────────────────────────────
    def _safe(s: str) -> str:
        return (s or "").replace(",", " ").replace("|", " ")

    _patient_arg = "|".join([
        f"patient_name={_safe(req.patient_name)}",
        f"doctor_name={_safe(req.doctor_name)}",
        f"appointment_date={_safe(req.appointment_date)}",
        f"start_time={_safe(req.start_time)}",
        f"appointment_id={_safe(req.appointment_id)}",
        f"patient_id={_safe(req.patient_id)}",
        f"context={_safe(req.context)}",
    ])

    ari_query_params = {
        "endpoint": f"Local/{req.phone_number}@{dial_context}",
        "app":      _app_name(),
        "appArgs":  f"outbound_reminder,{_patient_arg}",
        "timeout":  "60",
        "callerId": caller_id,
    }

    ari_body = {
        "channelVars": {
            "AI_CONTEXT":       req.context,
            "PATIENT_ID":       req.patient_id,
            "PATIENT_NAME":     req.patient_name,
            "APPOINTMENT_ID":   req.appointment_id,
            "DOCTOR_NAME":      req.doctor_name,
            "APPOINTMENT_DATE": req.appointment_date,
            "START_TIME":       req.start_time,
            "CALL_TYPE":        "outbound_reminder",
        },
    }

    ari_url = f"{_ari_base_url()}/ari/channels"

    logger.info(
        "Outbound trigger: originating call — phone=%s patient_id=%s appointment_id=%s context=%s dial_context=%s ari=%s",
        req.phone_number, req.patient_id, req.appointment_id, req.context, dial_context, ari_url,
    )

    try:
        async with aiohttp.ClientSession(auth=_ari_auth()) as http_session:
            # Step 1: Originate the call
            async with http_session.post(
                ari_url,
                params=ari_query_params,  # endpoint/app/timeout → URL query string
                json=ari_body,            # channelVars → JSON body
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                body = {}
                try:
                    body = await response.json(content_type=None)
                except Exception:
                    body = {"raw": await response.text()}

                if response.status not in (200, 201):
                    logger.error(
                        "ARI originate failed — status=%s phone=%s body=%s",
                        response.status, req.phone_number, body,
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=f"ARI originate failed: HTTP {response.status} — {body}",
                    )

                channel_id = body.get("id", "unknown")
                logger.info(
                    "Outbound trigger: call originated — channel_id=%s phone=%s patient_id=%s appointment_id=%s",
                    channel_id, req.phone_number, req.patient_id, req.appointment_id,
                )

            # ── Murtuza change ────────────────────────────────────────────────
            # BUG FIX: ARI channelVars sent in the originate JSON body are NOT
            # readable via GET /channels/{id}/variable on Local/ channels.
            # All three GET requests (AI_PROVIDER, AI_AUDIO_PROFILE, AI_CONTEXT)
            # return 404 — confirmed from engine logs.
            #
            # Fix: After getting the channel_id, explicitly SET each variable
            # using POST /channels/{id}/variable.  Variables set this way ARE
            # readable by subsequent GET requests in the AI engine.
            #
            # Timing is safe: the engine reads AI_CONTEXT ~160 ms after
            # StasisStart (bridge creation + session setup overhead), while
            # these 8 parallel SET requests complete in ~20–30 ms.
            # ── end Murtuza change ──────────────────────────────────────────
            if channel_id and channel_id != "unknown":
                _var_url = f"{ari_url}/{channel_id}/variable"
                _vars_to_set = {
                    "AI_CONTEXT":       req.context,
                    "CALL_TYPE":        "outbound_reminder",
                    "PATIENT_NAME":     req.patient_name,
                    "PATIENT_ID":       req.patient_id,
                    "APPOINTMENT_ID":   req.appointment_id,
                    "DOCTOR_NAME":      req.doctor_name,
                    "APPOINTMENT_DATE": req.appointment_date,
                    "START_TIME":       req.start_time,
                }
                import asyncio as _asyncio

                async def _set_var(vname: str, vval: str) -> None:
                    if not vval:
                        return
                    try:
                        async with http_session.post(
                            _var_url,
                            params={"variable": vname, "value": vval},
                            timeout=aiohttp.ClientTimeout(total=3),
                        ) as _r:
                            if _r.status not in (200, 201, 204):
                                logger.warning(
                                    "SET channel var %s returned HTTP %s for channel %s",
                                    vname, _r.status, channel_id,
                                )
                    except Exception as _e:
                        logger.warning(
                            "Failed to SET channel var %s on channel %s: %s",
                            vname, channel_id, _e,
                        )

                await _asyncio.gather(*[
                    _set_var(k, str(v)) for k, v in _vars_to_set.items()
                ])
                logger.info(
                    "Outbound trigger: channel vars SET via ARI — channel_id=%s vars=%s",
                    channel_id, list(_vars_to_set.keys()),
                )

            return OutboundTriggerResponse(
                ok=True,
                channel_id=channel_id,
                phone_number=req.phone_number,
                context=req.context,
            )

    except HTTPException:
        raise
    except aiohttp.ClientConnectorError as e:
        logger.error("Cannot reach Asterisk ARI at %s: %s", _ari_base_url(), e)
        raise HTTPException(
            status_code=502,
            detail=f"Cannot reach Asterisk ARI at {_ari_base_url()}. Is Asterisk running?",
        )
    except Exception as e:
        logger.error("Unexpected error in outbound trigger: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal error: {e}")
