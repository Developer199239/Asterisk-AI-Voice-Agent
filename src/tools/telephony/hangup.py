"""
Hangup Call Tool - End the current call.

Allows full AI agents to end calls when appropriate (e.g., after goodbye).
"""

from typing import Dict, Any
from src.tools.base import Tool, ToolDefinition, ToolParameter, ToolCategory
from src.tools.context import ToolExecutionContext
import structlog
import re
import time

logger = structlog.get_logger(__name__)

_AFFIRMATIVE_MARKERS = (
    "yes",
    "yeah",
    "yep",
    "correct",
    "that's correct",
    "thats correct",
    "that's right",
    "thats right",
    "right",
    "exactly",
	"affirmative",
)

_NEGATIVE_MARKERS = (
    "no",
    "nope",
    "nah",
    "negative",
    "don't",
    "dont",
    "do not",
    "not",
    "not needed",
    "no need",
    "no thanks",
    "no thank you",
    "decline",
    "skip",
)

_END_CALL_MARKERS = (
    "bye",
    "goodbye",
    "hang up",
    "hangup",
    "end the call",
    "end call",
    "that's all",
    "thats all",
    "nothing else",
    "no thanks",
    "no thank you",
    "i'm done",
    "im done",
    "all set",
)


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _looks_like_emailish(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if "@" in t:
        return bool(re.search(r"@[a-z0-9.-]+\\.[a-z]{2,}", t))
    # Common spoken-email patterns
    if " at " in f" {t} ":
        return (" dot " in f" {t} ") or bool(re.search(r"\\b[a-z]{2,}\\.(com|net|org|io|co)\\b", t))
    return False


def _is_affirmative(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    return any(m in t for m in _AFFIRMATIVE_MARKERS)

def _is_negative(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    # Avoid treating "not sure" / "not really" as a transcript decline by requiring either
    # a direct negative marker or explicit "don't/do not" phrases.
    if any(m in t for m in ("don't", "dont", "do not")):
        return True
    if t in ("no", "nope", "nah", "negative"):
        return True
    return any(m in t for m in _NEGATIVE_MARKERS)


def _is_end_call_intent(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    return any(m in t for m in _END_CALL_MARKERS)


def _assistant_is_confirming_contact(text: str) -> bool:
    t = _norm(text)
    if not t:
        return False
    if "is that correct" in t or "is that right" in t or "did i get that" in t:
        return True
    if "email" in t and t.endswith("?"):
        return True
    if "email address" in t and ("confirm" in t or "correct" in t):
        return True
    return False


class HangupCallTool(Tool):
    """
    End the current call.
    
    Use when:
    - Caller says goodbye/thank you/that's all
    - Call purpose is complete
    - Caller explicitly asks to end the call
    
    Only available to full agents (not partial/assistant agents).
    """
    
    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="hangup_call",
            description=(
                "End the current call with a farewell message. Use this tool when:\n"
                "- User says goodbye, bye, see you, talk to you later, take care, etc.\n"
                "- User says 'that's all', 'nothing else', 'I'm good', 'I'm done', 'all set'\n"
                "- User thanks you after receiving help: 'thanks', 'thank you', 'appreciate it'\n"
                "- Conversation naturally concludes after completing user's request\n"
                "- User explicitly requests to end the call\n"
                "IMPORTANT: Only use this tool when you are confident the caller wants to end the call.\n"
                "SEQUENCE: When you decide to end the call, call hangup_call with farewell_message set to the\n"
                "exact goodbye sentence you intend to say, then immediately speak that exact sentence as your\n"
                "final response. Do not continue the conversation after invoking this tool.\n"
                "If you are uncertain, ask 'Is there anything else I can help with?' as a normal response "
                "(do NOT call this tool)."
            ),
            category=ToolCategory.TELEPHONY,
            requires_channel=True,
            max_execution_time=5,
            parameters=[
                ToolParameter(
                    name="farewell_message",
                    type="string",
                    description="Farewell message to speak before hanging up. Should be warm and professional.",
                    required=False
                )
            ]
        )
    
    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> Dict[str, Any]:
        """
        End the call.
        
        Args:
            parameters: {farewell_message: Optional[str]}
            context: Tool execution context
        
        Returns:
            {
                status: "success" | "error",
                message: "Farewell message",
                will_hangup: true
            }
        """
        farewell = parameters.get('farewell_message')
        
        if not farewell:
            # Use default from config or hardcoded
            farewell = context.get_config_value(
                'tools.hangup_call.farewell_message',
                "Thank you for calling. Goodbye!"
            )

        # Provider-agnostic guardrail: do not let the model end the call while the caller is
        # supplying/confirming structured contact info (e.g., transcript email). This prevents
        # premature hangups like "Is that correct? … Goodbye" before the caller answers.
        try:
            session_store = getattr(context, "session_store", None)
            if session_store:
                session = await session_store.get_by_call_id(context.call_id)
            else:
                session = None
            history = getattr(session, "conversation_history", None) if session else None
            if isinstance(history, list) and history:
                last_user = next(
                    (m for m in reversed(history) if m.get("role") == "user" and str(m.get("content") or "").strip()),
                    None,
                )
                last_assistant = next(
                    (m for m in reversed(history) if m.get("role") == "assistant" and str(m.get("content") or "").strip()),
                    None,
                )
                last_user_text = str((last_user or {}).get("content") or "")
                last_assistant_text = str((last_assistant or {}).get("content") or "")

                # If transcript sending is enabled, enforce a "offer transcript" step before hanging up.
                # This keeps end-of-call UX consistent across providers, especially when the model tries
                # to jump straight to hangup_call on "thanks/that's all".
                try:
                    transcript_cfg = context.get_config_value("tools.request_transcript", {}) or {}
                    transcript_enabled = bool(isinstance(transcript_cfg, dict) and transcript_cfg.get("enabled", False))
                except Exception:
                    transcript_enabled = False
                try:
                    allowed_tools = getattr(session, "allowed_tools", None) if session else None
                    request_transcript_allowed = True
                    if isinstance(allowed_tools, (list, tuple, set)):
                        request_transcript_allowed = "request_transcript" in set(str(t) for t in allowed_tools)
                except Exception:
                    request_transcript_allowed = True

                if transcript_enabled and request_transcript_allowed:
                    # Provider-agnostic transcript offer state:
                    # Some providers do not reliably persist assistant transcripts into conversation_history
                    # before the model triggers the next tool call. Rely on an explicit per-call flag
                    # instead of brittle substring scans to avoid repeated "transcript?" prompts.
                    now = time.time()
                    try:
                        guard = session.vad_state.setdefault("hangup_guard", {}) if isinstance(getattr(session, "vad_state", None), dict) else {}
                        tstate = guard.setdefault("transcript_offer", {}) if isinstance(guard, dict) else {}
                    except Exception:
                        guard = {}
                        tstate = {}

                    offered = bool(tstate.get("offered", False))
                    pending = bool(tstate.get("pending_response", False))
                    declined = bool(tstate.get("declined", False))
                    accepted = bool(tstate.get("accepted", False))
                    offered_at = float(tstate.get("offered_at_ts", 0.0) or 0.0)
                    offered_count = int(tstate.get("offered_count", 0) or 0)

                    # Back-compat: if recent history clearly contains a transcript offer, treat it as offered.
                    # This helps providers where assistant transcripts ARE persisted.
                    if not offered:
                        recent = " ".join(
                            str(m.get("content") or "")
                            for m in history[-10:]
                            if isinstance(m, dict) and m.get("role") in ("user", "assistant")
                        ).lower()
                        if ("email you a transcript" in recent) or ("email" in recent and "transcript" in recent):
                            offered = True
                            pending = True
                            if offered_at <= 0.0:
                                offered_at = now
                            offered_count = max(1, offered_count)

                    if offered and pending:
                        # Interpret the most recent user utterance as the transcript decision when possible.
                        if _is_affirmative(last_user_text):
                            accepted = True
                            pending = False
                        elif _is_negative(last_user_text):
                            declined = True
                            pending = False

                    if not offered:
                        offered = True
                        pending = True
                        declined = False
                        accepted = False
                        offered_at = now
                        offered_count = offered_count + 1
                        try:
                            tstate.update(
                                {
                                    "offered": True,
                                    "pending_response": True,
                                    "declined": False,
                                    "accepted": False,
                                    "offered_at_ts": offered_at,
                                    "offered_count": offered_count,
                                }
                            )
                            if isinstance(guard, dict):
                                guard["transcript_offer"] = tstate
                                session.vad_state["hangup_guard"] = guard
                            if context.session_store:
                                await context.session_store.upsert_call(session)
                        except Exception:
                            pass
                        logger.info(
                            "📞 Hangup blocked: transcript not offered yet",
                            call_id=context.call_id,
                            last_user_preview=last_user_text[:80],
                        )
                        return {
                            "status": "blocked",
                            "message": "Before we hang up, would you like me to email you a transcript of our conversation?",
                            "will_hangup": False,
                            "ai_should_speak": True,
                        }

                    # Persist state updates from user answer parsing.
                    try:
                        tstate.update(
                            {
                                "offered": bool(offered),
                                "pending_response": bool(pending),
                                "declined": bool(declined),
                                "accepted": bool(accepted),
                                "offered_at_ts": float(offered_at or 0.0),
                                "offered_count": int(offered_count or 0),
                            }
                        )
                        if isinstance(guard, dict):
                            guard["transcript_offer"] = tstate
                            session.vad_state["hangup_guard"] = guard
                        if context.session_store:
                            await context.session_store.upsert_call(session)
                    except Exception:
                        pass

                    if accepted:
                        # Transcript accepted but no email captured yet: do not hang up.
                        has_email = bool(getattr(session, "transcript_emails", None))
                        if not has_email:
                            return {
                                "status": "blocked",
                                "message": "Sure — what email address should I send the transcript to?",
                                "will_hangup": False,
                                "ai_should_speak": True,
                            }

                    if pending and not (declined or accepted):
                        # Transcript was offered very recently but the user hasn't answered yet.
                        # Use a short prompt to reduce repeated long questions if the model calls again.
                        short = "Would you like a transcript emailed? Please say yes or no."
                        long = "Before we hang up, would you like me to email you a transcript of our conversation?"
                        msg = short if (offered_count >= 1 and offered_at and (now - offered_at) < 15.0) else long
                        return {
                            "status": "blocked",
                            "message": msg,
                            "will_hangup": False,
                            "ai_should_speak": True,
                        }

                pending_contact_confirmation = (
                    _looks_like_emailish(last_user_text)
                    and not _is_affirmative(last_user_text)
                    and _assistant_is_confirming_contact(last_assistant_text)
                    and not _is_end_call_intent(last_user_text)
                )
                if pending_contact_confirmation:
                    logger.info(
                        "📞 Hangup blocked: pending contact confirmation",
                        call_id=context.call_id,
                        last_user_preview=last_user_text[:80],
                        last_assistant_preview=last_assistant_text[:80],
                    )
                    return {
                        "status": "blocked",
                        "message": (
                            "Before we hang up, I just need to confirm the email address for the transcript. "
                            "Could you please confirm if that's correct?"
                        ),
                        "will_hangup": False,
                        "ai_should_speak": True,
                    }
        except Exception:
            logger.debug("Hangup guardrail check failed", call_id=context.call_id, exc_info=True)
        
        logger.info("📞 Hangup requested", 
                   call_id=context.call_id,
                   farewell=farewell)
        
        try:
            # Mark the session so the engine will hang up after the farewell audio finishes.
            # This is a safety net in case provider-specific "HangupReady" events do not fire.
            await context.update_session(cleanup_after_tts=True)
            logger.info("✅ Call will hangup after farewell", call_id=context.call_id)
            
            # Return farewell message with will_hangup flag
            # This triggers Option C: provider marks next response as farewell,
            # emits HangupReady when farewell completes, engine hangs up
            # NO cleanup_after_tts - prevents race condition with old mechanism
            return {
                "status": "success",
                "message": farewell,
                "will_hangup": True
            }
            
        except Exception as e:
            logger.error(f"Error preparing hangup: {e}", exc_info=True)
            return {
                "status": "error",
                "message": "Goodbye!",
                "will_hangup": True,
                "error": str(e)
            }
