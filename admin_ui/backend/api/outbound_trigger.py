"""
Outbound single-shot trigger API for Smart Doctor appointment reminder and lead follow-up calls.

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
from fastapi import APIRouter, Header, HTTPException, Query
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
    """FreePBX dialplan context for outbound reminder calls."""
    return _env("AAVA_OUTBOUND_DIAL_CONTEXT", "from-internal")


def _outbound_lead_dial_context() -> str:
    """FreePBX dialplan context for outbound lead follow-up calls."""
    return _env("AAVA_OUTBOUND_LEAD_DIAL_CONTEXT", "from-ai-outbound-lead")


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class OutboundTriggerRequest(BaseModel):
    """
    Payload sent by HOS backend to trigger a single outbound call.

    For outbound_reminder: phone_number + patient_id + patient_name + appointment_id +
    doctor_name + appointment_date + start_time are required.

    For outbound_lead: phone_number + patient_name + lead_id are required;
    all appointment fields are optional and ignored.
    """
    phone_number: str = Field(
        ...,
        description="Patient phone number. E.164 (+923001234567) or local format (03001234567).",
        examples=["+923001234567"],
    )
    patient_name: str = Field(
        ...,
        description="Patient full name — Ava uses this in the greeting.",
    )
    context: str = Field(
        default="outbound_reminder",
        description="AI engine context name. Must exist in ai-agent.yaml contexts.",
    )
    # ── Reminder-only fields ────────────────────────────────────────────────
    patient_id: Optional[str] = Field(
        default=None,
        description="Patient ID from HOS backend. Required for outbound_reminder.",
    )
    appointment_id: Optional[str] = Field(
        default=None,
        description="Appointment ID. Required for outbound_reminder.",
    )
    doctor_name: Optional[str] = Field(
        default=None,
        description="Doctor full name. Required for outbound_reminder.",
    )
    appointment_date: Optional[str] = Field(
        default=None,
        description="Appointment date in YYYY-MM-DD format. Required for outbound_reminder.",
        examples=["2026-05-20"],
    )
    start_time: Optional[str] = Field(
        default=None,
        description="Appointment time in HH:MM format (24h). Required for outbound_reminder.",
        examples=["09:00"],
    )
    # ── Lead-only fields ────────────────────────────────────────────────────
    lead_id: Optional[str] = Field(
        default=None,
        description="Lead ID from HOS backend. Required for outbound_lead.",
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
    summary="Trigger a single outbound call (reminder or lead follow-up)",
    description=(
        "Called by the HOS backend to trigger one outbound call. "
        "Set context='outbound_reminder' for appointment reminders, "
        "'outbound_lead' for lead follow-up calls. "
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

    def _safe(s: str) -> str:
        return (s or "").replace(",", " ").replace("|", " ")

    ari_url = f"{_ari_base_url()}/ari/channels"

    # ── Branch: outbound_lead vs outbound_reminder ──────────────────────────
    if req.context == "outbound_lead":
        if not req.lead_id:
            raise HTTPException(status_code=422, detail="lead_id is required for outbound_lead")

        dial_context = _outbound_lead_dial_context()
        # Extension format: PHONE_LEADID (2 parts, parsed by dialplan CUT())
        _dial_ext = f"{req.phone_number}_{req.lead_id}"

        _data_arg = "|".join([
            f"patient_name={_safe(req.patient_name)}",
            f"lead_id={_safe(req.lead_id)}",
            f"context=outbound_lead",
        ])

        ari_query_params = {
            "endpoint": f"Local/{_dial_ext}@{dial_context}",
            "app":      _app_name(),
            "appArgs":  f"outbound_lead,{_data_arg}",
            "timeout":  "20",
            "callerId": caller_id,
        }
        ari_body = {
            "channelVars": {
                "AI_CONTEXT":   "outbound_lead",
                "LEAD_ID":      req.lead_id,
                "PATIENT_NAME": req.patient_name,
                "CALL_TYPE":    "outbound_lead",
            },
        }
        _vars_to_set = {
            "AI_CONTEXT":   "outbound_lead",
            "LEAD_ID":      req.lead_id,
            "PATIENT_NAME": req.patient_name,
            "CALL_TYPE":    "outbound_lead",
        }

        logger.info(
            "Outbound trigger [lead]: originating — phone=%s lead_id=%s dial_context=%s ari=%s",
            req.phone_number, req.lead_id, dial_context, ari_url,
        )

    else:
        # outbound_reminder (default) — all appointment fields required
        missing = [f for f in ("patient_id", "appointment_id", "doctor_name", "appointment_date", "start_time")
                   if not getattr(req, f)]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Fields required for outbound_reminder: {', '.join(missing)}",
            )

        dial_context = _outbound_dial_context()
        _dial_ext = f"{req.phone_number}_{req.appointment_id}_{req.patient_id}"

        _data_arg = "|".join([
            f"patient_name={_safe(req.patient_name)}",
            f"doctor_name={_safe(req.doctor_name)}",
            f"appointment_date={_safe(req.appointment_date)}",
            f"start_time={_safe(req.start_time)}",
            f"appointment_id={_safe(req.appointment_id)}",
            f"patient_id={_safe(req.patient_id)}",
            f"context={_safe(req.context)}",
        ])

        ari_query_params = {
            "endpoint": f"Local/{_dial_ext}@{dial_context}",
            "app":      _app_name(),
            "appArgs":  f"outbound_reminder,{_data_arg}",
            "timeout":  "20",
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

        logger.info(
            "Outbound trigger [reminder]: originating — phone=%s patient_id=%s appointment_id=%s context=%s dial_context=%s ari=%s",
            req.phone_number, req.patient_id, req.appointment_id, req.context, dial_context, ari_url,
        )

    try:
        async with aiohttp.ClientSession(auth=_ari_auth()) as http_session:
            async with http_session.post(
                ari_url,
                params=ari_query_params,
                json=ari_body,
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
                    "Outbound trigger: call originated — channel_id=%s phone=%s context=%s",
                    channel_id, req.phone_number, req.context,
                )

            if channel_id and channel_id != "unknown":
                _var_url = f"{ari_url}/{channel_id}/variable"
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


@trigger_router.get(
    "/context-status",
    summary="Check if an AI context has an active call",
    description=(
        "Checks ARI for active channels in the given context. "
        "Authenticates via X-Api-Key header (same key as /trigger). "
        "No JWT required — designed for machine-to-machine calls from HOS backend."
    ),
)
async def outbound_context_status(
    context: str = Query(..., description="AI context name, e.g. outbound_reminder"),
    x_api_key: Optional[str] = Header(default=None),
):
    api_key = _outbound_trigger_api_key()
    if not api_key:
        raise HTTPException(status_code=503, detail="Outbound trigger is not configured.")
    if not x_api_key or x_api_key != api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

    ari_base = _ari_base_url()
    auth = _ari_auth()

    try:
        async with aiohttp.ClientSession(auth=auth) as session:
            # Get all active channels from ARI
            async with session.get(
                f"{ari_base}/ari/channels",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return {"context": context, "busy": False, "active_calls": 0, "calls": []}
                channels = await resp.json(content_type=None)

            # Check AI_CONTEXT variable on each channel
            matching = []
            for ch in channels:
                ch_id = ch.get("id", "")
                if not ch_id:
                    continue
                try:
                    async with session.get(
                        f"{ari_base}/ari/channels/{ch_id}/variable",
                        params={"variable": "AI_CONTEXT"},
                        timeout=aiohttp.ClientTimeout(total=3),
                    ) as vresp:
                        if vresp.status == 200:
                            vdata = await vresp.json(content_type=None)
                            if vdata.get("value") == context:
                                matching.append({"call_id": ch_id, "context": context, "status": "active"})
                except Exception:
                    continue

        return {
            "context": context,
            "busy": len(matching) > 0,
            "active_calls": len(matching),
            "calls": matching,
        }
    except aiohttp.ClientConnectorError:
        raise HTTPException(status_code=502, detail=f"Cannot reach Asterisk ARI at {ari_base}")
    except Exception as exc:
        logger.error("context-status check failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
