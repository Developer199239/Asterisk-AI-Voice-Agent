from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Dict, Optional

import resend
import structlog

logger = structlog.get_logger(__name__)


class _ResendRateLimiter:
    def __init__(self, max_per_second: float = 2.0) -> None:
        if max_per_second <= 0:
            max_per_second = 1.0
        self._min_interval = 1.0 / max_per_second
        self._lock = asyncio.Lock()
        self._last_sent_at: float = 0.0

    async def wait_turn(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_sent_at
            sleep_for = self._min_interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            self._last_sent_at = time.monotonic()


_limiter = _ResendRateLimiter(max_per_second=float(os.getenv("RESEND_MAX_RPS", "2") or "2"))
_api_key_configured: Optional[str] = None


def _ensure_api_key() -> bool:
    global _api_key_configured
    api_key = os.getenv("RESEND_API_KEY")
    if not api_key:
        return False
    if _api_key_configured != api_key:
        resend.api_key = api_key
        _api_key_configured = api_key
    return True


def _is_rate_limit_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "too many requests" in msg or "rate limit" in msg or "429" in msg


async def send_email(
    *,
    email_data: Dict[str, Any],
    call_id: str,
    log_label: str,
    recipient: str,
    max_retries: int = 3,
) -> Optional[Dict[str, Any]]:
    """
    Send email via Resend with a simple process-wide rate limiter.

    Resend enforces 2 requests/second on many plans; outbound tooling can trigger multiple
    email sends back-to-back (summary + transcript). We serialize + retry to avoid 429s.
    """
    if not _ensure_api_key():
        logger.error("RESEND_API_KEY not configured", call_id=call_id)
        return None

    for attempt in range(max_retries + 1):
        await _limiter.wait_turn()
        try:
            response = await asyncio.to_thread(resend.Emails.send, email_data)
            email_id = response.get("id") if isinstance(response, dict) else getattr(response, "id", None)
            logger.info(
                f"{log_label} sent successfully",
                call_id=call_id,
                recipient=recipient,
                email_id=email_id,
            )
            return response if isinstance(response, dict) else {"id": email_id}
        except Exception as exc:  # noqa: BLE001
            if attempt < max_retries and _is_rate_limit_error(exc):
                backoff = 0.75 * (2**attempt)
                logger.warning(
                    f"{log_label} rate-limited; retrying",
                    call_id=call_id,
                    recipient=recipient,
                    error=str(exc),
                    retry_in_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                continue

            logger.error(
                f"Failed to send {log_label.lower()}",
                call_id=call_id,
                recipient=recipient,
                error=str(exc),
                exc_info=True,
            )
            return None

