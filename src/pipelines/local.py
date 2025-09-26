"""
# Milestone7: Local pipeline adapters for the local AI server.

These adapters implement the STT/LLM/TTS interfaces defined in `base.py` by
talking directly to the local AI server WebSocket (default ws://127.0.0.1:8765).
Each adapter maintains its own connection lifecycle so pipelines can mix and
match local components without sharing provider state.
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, Optional, Tuple

import websockets
from websockets.client import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed

from ..config import AppConfig, LocalProviderConfig
from ..logging_config import get_logger
from .base import LLMComponent, STTComponent, TTSComponent

logger = get_logger(__name__)

_DEFAULT_WS_URL = "ws://127.0.0.1:8765"


def _merge_dicts(base: Dict[str, Any], override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(base or {})
    if override:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge_dicts(merged[key], value)
            elif value is not None:
                merged[key] = value
    return merged


@dataclass
class _LocalSessionState:
    websocket: WebSocketClientProtocol
    options: Dict[str, Any]
    mode: str
    call_id: str
    handshake_complete: bool = False


class _LocalAdapterBase:
    """Shared helpers for local pipeline adapters."""

    def __init__(
        self,
        component_key: str,
        app_config: AppConfig,
        provider_config: LocalProviderConfig,
        pipeline_defaults: Optional[Dict[str, Any]],
        *,
        default_mode: str,
    ):
        self.component_key = component_key
        self._app_config = app_config
        self._provider_config = provider_config
        self._provider_defaults = provider_config.model_dump()
        self._pipeline_defaults = pipeline_defaults or {}
        self._default_mode = default_mode
        self._sessions: Dict[str, _LocalSessionState] = {}
        self._closed = False

    async def start(self) -> None:
        logger.debug(
            "Local adapter initialized",
            component=self.component_key,
            default_mode=self._default_mode,
        )

    async def stop(self) -> None:
        self._closed = True
        for call_id in list(self._sessions.keys()):
            await self.close_call(call_id)
        logger.debug("Local adapter stopped", component=self.component_key)

    async def open_call(self, call_id: str, options: Dict[str, Any]) -> None:
        if self._closed:
            raise RuntimeError(f"Adapter {self.component_key} has been stopped")

        merged = self._compose_options(options)
        existing = self._sessions.get(call_id)
        if existing:
            if existing.websocket.closed:
                self._sessions.pop(call_id, None)
            else:
                # Reuse any open websocket session regardless of handshake status
                logger.debug(
                    "Reusing existing local adapter session",
                    component=self.component_key,
                    call_id=call_id,
                )
                return

        ws_url = merged.get("ws_url") or _DEFAULT_WS_URL
        connect_timeout = float(merged.get("connect_timeout_sec", 5.0))
        mode = merged.get("mode", self._default_mode)

        logger.info(
            "Opening local adapter session",
            component=self.component_key,
            call_id=call_id,
            url=ws_url,
            mode=mode,
        )

        try:
            websocket = await asyncio.wait_for(
                websockets.connect(
                    ws_url,
                    ping_interval=None,
                    ping_timeout=None,
                    max_size=None,
                ),
                timeout=connect_timeout,
            )
        except Exception as exc:
            logger.error(
                "Failed to connect to local AI server",
                component=self.component_key,
                call_id=call_id,
                error=str(exc),
            )
            raise

        session = _LocalSessionState(
            websocket=websocket,
            options=merged,
            mode=mode,
            call_id=call_id,
            handshake_complete=False,
        )
        self._sessions[call_id] = session

        await self._send_json(
            session,
            {
                "type": "set_mode",
                "mode": mode,
                "call_id": call_id,
            },
        )
        try:
            logger.info(
                "Local adapter set_mode sent",
                component=self.component_key,
                call_id=call_id,
                mode=mode,
            )
        except Exception:
            pass
        try:
            # Best-effort handshake; proceed without failing if ack not received
            await self._await_mode_ready(session, merged)
        except Exception:
            logger.warning(
                "Local adapter handshake not confirmed; proceeding without mode_ready",
                component=self.component_key,
                call_id=call_id,
                exc_info=True,
            )
        try:
            # Diagnostic: confirm session index and mode after set_mode send
            logger.info(
                "Local adapter session opened",
                component=self.component_key,
                call_id=call_id,
                mode=mode,
                session_keys=list(self._sessions.keys()),
                url=ws_url,
            )
        except Exception:
            logger.debug("Local adapter session open logging failed", exc_info=True)

    async def close_call(self, call_id: str) -> None:
        session = self._sessions.pop(call_id, None)
        if not session:
            return

        try:
            await session.websocket.close()
        except Exception as exc:
            logger.warning(
                "Error closing local adapter session",
                component=self.component_key,
                call_id=call_id,
                error=str(exc),
            )
        finally:
            logger.info(
                "Local adapter session closed",
                component=self.component_key,
                call_id=call_id,
            )

    def _compose_options(self, runtime_options: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        merged = _merge_dicts(dict(self._provider_defaults or {}), self._pipeline_defaults)
        merged = _merge_dicts(merged, runtime_options)
        merged.setdefault("ws_url", merged.get("ws_url") or _DEFAULT_WS_URL)
        merged.setdefault("connect_timeout_sec", merged.get("connect_timeout_sec", 5.0))
        merged.setdefault("response_timeout_sec", merged.get("response_timeout_sec", 5.0))
        merged.setdefault("mode", merged.get("mode", self._default_mode))
        merged.setdefault("locale", merged.get("locale") or merged.get("language") or "en-US")
        merged.setdefault("chunk_ms", merged.get("chunk_ms", 200))
        return merged

    async def _send_json(self, session: _LocalSessionState, payload: Dict[str, Any]) -> None:
        try:
            await session.websocket.send(json.dumps(payload))
        except Exception as exc:
            logger.error(
                "Failed to send JSON payload to local AI server",
                component=self.component_key,
                call_id=session.call_id,
                payload_type=payload.get("type"),
                error=str(exc),
            )
            raise

    async def _await_mode_ready(self, session: _LocalSessionState, options: Dict[str, Any]) -> None:
        handshake_timeout = float(
            options.get(
                "handshake_timeout_sec",
                max(float(options.get("connect_timeout_sec", 5.0)), 5.0),
            )
        )
        deadline = time.perf_counter() + handshake_timeout
        while True:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                raise asyncio.TimeoutError("Local adapter handshake timed out")
            kind, message = await self._recv_any(session, remaining)
            if kind != "json":
                logger.debug(
                    "Ignoring non-JSON message during handshake",
                    component=self.component_key,
                    call_id=session.call_id,
                    message_type=kind,
                )
                continue
            msg_type = message.get("type")
            if msg_type != "mode_ready":
                logger.debug(
                    "Unexpected JSON payload during handshake",
                    component=self.component_key,
                    call_id=session.call_id,
                    payload_type=msg_type,
                )
                continue
            ack_mode = message.get("mode")
            if ack_mode:
                session.mode = ack_mode
            ack_call_id = message.get("call_id")
            if ack_call_id:
                session.call_id = ack_call_id
            session.handshake_complete = True
            logger.info(
                "Local adapter handshake complete",
                component=self.component_key,
                call_id=session.call_id,
                mode=session.mode,
            )
            return

    async def _recv_any(
        self,
        session: _LocalSessionState,
        timeout: float,
    ) -> Tuple[str, Any]:
        try:
            message = await asyncio.wait_for(session.websocket.recv(), timeout=timeout)
        except ConnectionClosed as exc:
            logger.warning(
                "Local AI server connection closed",
                component=self.component_key,
                call_id=session.call_id,
                code=getattr(exc, "code", None),
                reason=getattr(exc, "reason", None),
            )
            raise
        except asyncio.TimeoutError as exc:
            raise exc

        if isinstance(message, bytes):
            return "binary", message

        if isinstance(message, str):
            try:
                payload = json.loads(message)
                return "json", payload
            except json.JSONDecodeError:
                logger.debug(
                    "Discarding non-JSON text message from local server",
                    component=self.component_key,
                    call_id=session.call_id,
                    preview=message[:64],
                )
                return "text", message

        logger.debug(
            "Received unsupported message type from local server",
            component=self.component_key,
            call_id=session.call_id,
            message_type=type(message).__name__,
        )
        return "unknown", message

    async def _ensure_session(self, call_id: str, options: Dict[str, Any]) -> _LocalSessionState:
        session = self._sessions.get(call_id)
        if session and not session.websocket.closed:
            return session

        if session and session.websocket.closed:
            self._sessions.pop(call_id, None)

        await self.open_call(call_id, options)
        session = self._sessions.get(call_id)
        if session and not session.websocket.closed:
            return session

        raise RuntimeError(f"Local adapter session not available for call {call_id}")


class LocalSTTAdapter(STTComponent, _LocalAdapterBase):
    """# Milestone7: STT adapter backed by the local AI server."""

    def __init__(
        self,
        component_key: str,
        app_config: AppConfig,
        provider_config: LocalProviderConfig,
        options: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            component_key,
            app_config,
            provider_config,
            options,
            default_mode="stt",
        )

    async def transcribe(
        self,
        call_id: str,
        audio_pcm16: bytes,
        sample_rate_hz: int,
        options: Dict[str, Any],
    ) -> str:
        runtime_options = options or {}
        session = await self._ensure_session(call_id, runtime_options)

        merged = self._compose_options(runtime_options)
        logger.debug(
            "Sending STT audio chunk",
            component=self.component_key,
            call_id=call_id,
            bytes=len(audio_pcm16),
            rate=sample_rate_hz,
        )
        payload = {
            "type": "audio",
            "mode": "stt",
            "call_id": call_id,
            "rate": sample_rate_hz,
            "data": base64.b64encode(audio_pcm16).decode("ascii"),
        }

        await self._send_json(session, payload)

        timeout = float(merged.get("response_timeout_sec", 5.0))
        started_at = time.perf_counter()

        while True:
            kind, message = await self._recv_any(session, timeout)
            if kind != "json":
                continue
            if message.get("type") != "stt_result":
                continue

            transcript = message.get("text", "").strip()
            latency_ms = (time.perf_counter() - started_at) * 1000.0
            logger.info(
                "Local STT transcript received",
                component=self.component_key,
                call_id=call_id,
                latency_ms=round(latency_ms, 2),
                transcript_preview=transcript[:80],
            )
            return transcript


class LocalLLMAdapter(LLMComponent, _LocalAdapterBase):
    """# Milestone7: LLM adapter backed by the local AI server."""

    def __init__(
        self,
        component_key: str,
        app_config: AppConfig,
        provider_config: LocalProviderConfig,
        options: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            component_key,
            app_config,
            provider_config,
            options,
            default_mode="llm",
        )

    async def generate(
        self,
        call_id: str,
        transcript: str,
        context: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        runtime_options = options or {}
        session = await self._ensure_session(call_id, runtime_options)

        merged = self._compose_options(runtime_options)
        logger.debug(
            "Sending LLM request",
            component=self.component_key,
            call_id=call_id,
            transcript_preview=(transcript or "")[:80],
        )
        payload = {
            "type": "llm_request",
            "call_id": call_id,
            "mode": "llm",
            "text": transcript,
            "context": context.get("messages") or context,
        }

        await self._send_json(session, payload)

        timeout = float(merged.get("response_timeout_sec", 5.0))
        started_at = time.perf_counter()

        while True:
            kind, message = await self._recv_any(session, timeout)
            if kind != "json":
                continue
            if message.get("type") != "llm_response":
                continue

            response = message.get("text", "").strip()
            latency_ms = (time.perf_counter() - started_at) * 1000.0
            logger.info(
                "Local LLM response received",
                component=self.component_key,
                call_id=call_id,
                latency_ms=round(latency_ms, 2),
                response_preview=response[:80],
            )
            return response


class LocalTTSAdapter(TTSComponent, _LocalAdapterBase):
    """# Milestone7: TTS adapter backed by the local AI server."""

    def __init__(
        self,
        component_key: str,
        app_config: AppConfig,
        provider_config: LocalProviderConfig,
        options: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            component_key,
            app_config,
            provider_config,
            options,
            default_mode="tts",
        )

    async def synthesize(
        self,
        call_id: str,
        text: str,
        options: Dict[str, Any],
    ) -> AsyncIterator[bytes]:
        if not text:
            return
        runtime_options = options or {}
        session = await self._ensure_session(call_id, runtime_options)

        merged = self._compose_options(runtime_options)
        logger.debug(
            "Sending TTS request",
            component=self.component_key,
            call_id=call_id,
            text_preview=(text or "")[:80],
        )
        payload = {
            "type": "tts_request",
            "call_id": call_id,
            "mode": "tts",
            "text": text,
        }

        await self._send_json(session, payload)

        timeout = float(merged.get("response_timeout_sec", 8.0))
        started_at = time.perf_counter()
        yielded_audio = False

        while True:
            kind, message = await self._recv_any(session, timeout)
            if kind == "json":
                msg_type = message.get("type")
                if msg_type == "tts_response" and message.get("audio_data"):
                    decoded = base64.b64decode(message["audio_data"])
                    latency_ms = (time.perf_counter() - started_at) * 1000.0
                    logger.info(
                        "Local TTS response (base64) received",
                        component=self.component_key,
                        call_id=call_id,
                        latency_ms=round(latency_ms, 2),
                        bytes=len(decoded),
                    )
                    yielded_audio = True
                    yield decoded
                    break
                if msg_type == "tts_audio":
                    logger.debug(
                        "Local TTS metadata received",
                        component=self.component_key,
                        call_id=call_id,
                        meta=message,
                    )
                    continue
                continue

            if kind == "binary":
                latency_ms = (time.perf_counter() - started_at) * 1000.0
                logger.info(
                    "Local TTS audio chunk received",
                    component=self.component_key,
                    call_id=call_id,
                    latency_ms=round(latency_ms, 2),
                    chunk_bytes=len(message),
                )
                yielded_audio = True
                yield message
                # Assume the local server sends a single binary payload per request.
                break

        if not yielded_audio:
            logger.warning(
                "Local TTS returned no audio data",
                component=self.component_key,
                call_id=call_id,
            )


__all__ = [
    "LocalSTTAdapter",
    "LocalLLMAdapter",
    "LocalTTSAdapter",
]