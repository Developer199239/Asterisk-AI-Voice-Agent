"""
OpenAI Realtime provider implementation.

This module integrates OpenAI's server-side Realtime WebSocket transport into the
Asterisk AI Voice Agent without requiring WebRTC. Audio from AudioSocket is
converted to PCM16 @ 16 kHz, streamed to OpenAI, and PCM16 24 kHz output is
resampled to the configured downstream AudioSocket format (µ-law or PCM16 8 kHz).
"""

from __future__ import annotations

import asyncio
import audioop
import base64
import contextlib
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import websockets
from websockets import WebSocketClientProtocol
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from structlog import get_logger

from .base import AIProviderInterface
from ..audio import (
    convert_pcm16le_to_target_format,
    mulaw_to_pcm16le,
    resample_audio,
)
from ..config import OpenAIRealtimeProviderConfig

logger = get_logger(__name__)

_COMMIT_INTERVAL_SEC = 0.2
_KEEPALIVE_INTERVAL_SEC = 15.0
_COMMIT_MIN_MS = 120.0  # ensure provider receives >=120 ms per commit
_SPEECH_RMS_THRESHOLD = 200  # simple energy gate for classifying speech frames


class OpenAIRealtimeProvider(AIProviderInterface):
    """
    OpenAI Realtime provider using server-side WebSocket transport.

    Lifecycle:
    1. start_session(call_id) -> establishes WebSocket session.
    2. send_audio(bytes) -> converts inbound AudioSocket frames to PCM16 16 kHz,
       base64-encodes, and streams via input_audio_buffer.
    3. Provider output deltas are decoded, resampled to AudioSocket format, and
       emitted as AgentAudio / AgentAudioDone events.
    4. stop_session() -> closes the WebSocket and cancels background tasks.
    """

    def __init__(
        self,
        config: OpenAIRealtimeProviderConfig,
        on_event,
    ):
        super().__init__(on_event)
        self.config = config
        self.websocket: Optional[WebSocketClientProtocol] = None
        self._receive_task: Optional[asyncio.Task] = None
        self._keepalive_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()

        self._call_id: Optional[str] = None
        self._pending_response: bool = False
        self._in_audio_burst: bool = False
        self._first_output_chunk_logged: bool = False
        self._closing: bool = False
        self._closed: bool = False

        self._input_resample_state: Optional[tuple] = None
        self._output_resample_state: Optional[tuple] = None
        self._transcript_buffer: str = ""
        self._input_info_logged: bool = False
        # Aggregate converted 16 kHz PCM16 bytes and commit in >=100ms chunks
        self._pending_audio_16k: bytearray = bytearray()
        self._last_commit_ts: float = 0.0
        self._last_commit_error_ts: float = 0.0
        self._last_audio_append_ts: float = 0.0
        bytes_per_sample = 2  # PCM16
        provider_rate = int(getattr(self.config, "provider_input_sample_rate_hz", 16000) or 16000)
        self._bytes_per_sample: int = bytes_per_sample
        self._provider_rate: int = provider_rate
        self._commit_min_ms: float = float(getattr(self.config, "commit_min_ms", None) or _COMMIT_MIN_MS)
        self._commit_min_bytes: int = max(
            bytes_per_sample,
            int(provider_rate * (self._commit_min_ms / 1000.0) * bytes_per_sample),
        )
        self._pending_speech_ms: float = 0.0
        self._speech_rms_threshold: int = _SPEECH_RMS_THRESHOLD
        self._commit_grace_seconds: float = 0.35  # allow short pauses before padding with silence
        # Serialize append/commit to avoid empty commits from races
        self._audio_lock: asyncio.Lock = asyncio.Lock()
        # Track provider output format we requested in session.update
        self._provider_output_format: str = "pcm16"
        self._provider_output_rate: int = int(getattr(self.config, "output_sample_rate_hz", 24000) or 24000)
        # Greeting-only server VAD deferral
        self._defer_turn_detection: bool = False
        self._greeting_phase: bool = False
        self._td_enabled: bool = False
        # Telemetry counters (debug logging only)
        self._event_seq: int = 0
        self._audio_chunk_seq: int = 0
        self._text_chunk_seq: int = 0

    @property
    def supported_codecs(self):
        fmt = (self.config.target_encoding or "ulaw").lower()
        return [fmt]

    async def start_session(self, call_id: str):
        if not self.config.api_key:
            raise ValueError("OpenAI Realtime provider requires OPENAI_API_KEY")

        await self.stop_session()
        self._call_id = call_id
        self._pending_response = False
        self._in_audio_burst = False
        self._first_output_chunk_logged = False
        self._input_resample_state = None
        self._output_resample_state = None
        self._transcript_buffer = ""
        self._closing = False
        self._closed = False
        self._event_seq = 0
        self._audio_chunk_seq = 0
        self._text_chunk_seq = 0

        url = self._build_ws_url()
        headers = [
            ("Authorization", f"Bearer {self.config.api_key}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        if self.config.organization:
            headers.append(("OpenAI-Organization", self.config.organization))

        logger.info("Connecting to OpenAI Realtime", url=url, call_id=call_id)
        try:
            self.websocket = await websockets.connect(url, extra_headers=headers)
        except Exception:
            logger.error("Failed to connect to OpenAI Realtime", call_id=call_id, exc_info=True)
            raise

        # For the greeting, defer server-side VAD to avoid early segmentation
        self._defer_turn_detection = bool(getattr(self.config, "turn_detection", None))
        self._greeting_phase = self._defer_turn_detection
        await self._send_session_update(include_turn_detection=not self._defer_turn_detection)

        # Proactively request an initial response so the agent can greet
        # even before user audio arrives. Prefer explicit greeting text
        # when provided; otherwise fall back to generic instructions.
        try:
            if (self.config.greeting or "").strip():
                await self._send_explicit_greeting()
            else:
                await self._ensure_response_request()
        except Exception:
            logger.debug("Initial response.create request failed", call_id=call_id, exc_info=True)

        self._receive_task = asyncio.create_task(self._receive_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        logger.info("OpenAI Realtime session established", call_id=call_id)

    async def send_audio(self, audio_chunk: bytes):
        if not audio_chunk:
            return
        if not self.websocket or self.websocket.closed:
            logger.debug("Dropping inbound audio: websocket not ready", call_id=self._call_id)
            return
        # During the initial greeting, avoid touching input_audio_buffer to prevent
        # empty commits and reduce provider-side latency before first output.
        if self._greeting_phase:
            try:
                logger.info("Dropping inbound audio during greeting", call_id=self._call_id)
            except Exception:
                pass
            return

        try:
            # Log input codec/config once for diagnosis
            if not self._input_info_logged:
                try:
                    logger.info(
                        "OpenAI input config",
                        call_id=self._call_id,
                        input_encoding=self.config.input_encoding,
                        input_sample_rate_hz=self.config.input_sample_rate_hz,
                        provider_input_sample_rate_hz=self.config.provider_input_sample_rate_hz,
                    )
                    self._input_info_logged = True
                except Exception:
                    pass

            pcm16 = self._convert_inbound_audio(audio_chunk)
            if not pcm16:
                return

            # Log first conversion sizes to verify resample
            if self._input_info_logged is True and self._input_resample_state is not None:
                try:
                    logger.debug(
                        "OpenAI input frame sizes",
                        call_id=self._call_id,
                        src_bytes=len(audio_chunk),
                        dst_bytes=len(pcm16),
                    )
                except Exception:
                    pass

            async with self._audio_lock:
                await self._append_audio_buffer(pcm16)

                self._pending_audio_16k.extend(pcm16)
                pending_bytes = len(self._pending_audio_16k)
                speech_ms = self._estimate_speech_ms(pcm16)
                if speech_ms > 0.0:
                    self._pending_speech_ms += speech_ms
                self._last_audio_append_ts = time.time()

                logger.debug(
                    "OpenAI inbound audio buffered",
                    call_id=self._call_id,
                    appended_bytes=len(pcm16),
                    pending_bytes=pending_bytes,
                )

                await self._maybe_commit_audio()
        except ConnectionClosedError:
            logger.warning("OpenAI Realtime socket closed while sending audio", call_id=self._call_id)
        except Exception:
            logger.error("Failed to send audio to OpenAI Realtime", call_id=self._call_id, exc_info=True)

    async def stop_session(self):
        if self._closing or self._closed:
            return

        self._closing = True
        try:
            if self._receive_task:
                self._receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._receive_task
            if self._keepalive_task:
                self._keepalive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._keepalive_task

            async with self._audio_lock:
                await self._maybe_commit_audio(force=True)

            if self.websocket and not self.websocket.closed:
                await self.websocket.close()

            await self._emit_audio_done()
        finally:
            self._receive_task = None
            self._keepalive_task = None
            self.websocket = None
            self._call_id = None
            self._closing = False
            self._closed = True
            self._pending_response = False
            self._in_audio_burst = False
            self._input_resample_state = None
            self._output_resample_state = None
            self._transcript_buffer = ""
            logger.info("OpenAI Realtime session stopped")

    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "name": "OpenAIRealtimeProvider",
            "type": "cloud",
            "model": self.config.model,
            "voice": self.config.voice,
            "supported_codecs": self.supported_codecs,
        }

    def is_ready(self) -> bool:
        return bool(self.config.api_key)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _build_ws_url(self) -> str:
        base = (self.config.base_url or "").strip()
        # Fallback if unresolved placeholders exist or scheme isn't ws/wss
        if base.startswith("${") or not base.startswith(("ws://", "wss://")):
            logger.warning("Invalid OpenAI base_url in config; falling back to default", base_url=base)
            base = "wss://api.openai.com/v1/realtime"
        base = base.rstrip("/")
        return f"{base}?model={self.config.model}"

    async def _send_session_update(self, *, include_turn_detection: bool = True):
        # Map config modalities to output_modalities per latest guide
        output_modalities = [m for m in (self.config.response_modalities or []) if m in ("audio", "text")]
        if not output_modalities:
            output_modalities = ["audio"]

        # Choose OpenAI output format for this session:
        # If downstream target is μ-law, request g711_ulaw from provider to test end-to-end μ-law.
        # Otherwise keep PCM16.
        provider_rate = int(getattr(self.config, "provider_input_sample_rate_hz", 24000) or 24000)
        output_rate = int(getattr(self.config, "output_sample_rate_hz", 24000) or 24000)
        input_audio_format: Dict[str, Any] = {
            "type": "pcm16",
            "sample_rate_hz": provider_rate,
        }
        output_audio_format: Dict[str, Any] = {
            "type": "pcm16",
            "sample_rate_hz": output_rate,
        }

        session: Dict[str, Any] = {
            # Model is selected via URL; keep accepted keys here
            "modalities": output_modalities,
            "input_audio_format": input_audio_format,
            "output_audio_format": output_audio_format,
            "voice": self.config.voice,
        }
        # Record provider output format for runtime handling
        self._provider_output_format = output_audio_format.get("type", "pcm16")
        self._provider_output_rate = output_audio_format.get("sample_rate_hz", output_rate)
        # Optional server-side VAD/turn detection at session level
        if include_turn_detection and getattr(self.config, "turn_detection", None):
            try:
                td = self.config.turn_detection
                session["turn_detection"] = {
                    "type": td.type,
                    "silence_duration_ms": td.silence_duration_ms,
                    "threshold": td.threshold,
                    "prefix_padding_ms": td.prefix_padding_ms,
                }
            except Exception:
                logger.debug("Failed to include turn_detection in session.update", call_id=self._call_id, exc_info=True)

        if self.config.instructions:
            session["instructions"] = self.config.instructions

        payload: Dict[str, Any] = {
            "type": "session.update",
            "event_id": f"sess-{uuid.uuid4()}",
            "session": session,
        }

        await self._send_json(payload)

    async def _send_explicit_greeting(self):
        greeting = (self.config.greeting or "").strip()
        if not greeting or not self.websocket or self.websocket.closed:
            return

        # Map config modalities to output_modalities
        output_modalities = [m for m in (self.config.response_modalities or []) if m in ("audio", "text")] or ["audio"]

        response_payload: Dict[str, Any] = {
            "type": "response.create",
            "event_id": f"resp-{uuid.uuid4()}",
            "response": {
                # Force audio modality for greeting at response level (optional)
                "modalities": output_modalities,
                # Be explicit to ensure the model speaks immediately
                "instructions": f"Please greet the user with the following: {greeting}",
                "metadata": {"call_id": self._call_id, "purpose": "initial_greeting"},
                # Optionally strip context to avoid distractions
                "input": [],
            },
        }

        await self._send_json(response_payload)
        self._pending_response = True

    async def _ensure_response_request(self):
        if self._pending_response or not self.websocket or self.websocket.closed:
            return

        response_payload: Dict[str, Any] = {
            "type": "response.create",
            "event_id": f"resp-{uuid.uuid4()}",
            "response": {
                # Use 'modalities' which is accepted by server
                "modalities": [m for m in (self.config.response_modalities or []) if m in ("audio", "text")] or ["audio"],
                "metadata": {"call_id": self._call_id},
            },
        }
        if self.config.instructions:
            response_payload["response"]["instructions"] = self.config.instructions

        await self._send_json(response_payload)
        self._pending_response = True

    async def _send_json(self, payload: Dict[str, Any]):
        if not self.websocket or self.websocket.closed:
            return
        # Avoid logging base64 audio payloads; but log control message types
        try:
            ptype = payload.get("type")
            if ptype and not ptype.startswith("input_audio_buffer."):
                logger.debug("OpenAI send", call_id=self._call_id, type=ptype)
            elif ptype == "input_audio_buffer.commit":
                logger.debug("OpenAI send commit", call_id=self._call_id, type=ptype)
        except Exception:
            pass
        message = json.dumps(payload)
        async with self._send_lock:
            await self.websocket.send(message)

    async def _append_audio_buffer(self, pcm16: bytes) -> None:
        if not pcm16:
            return
        audio_b64 = base64.b64encode(pcm16).decode("ascii")
        await self._send_json({"type": "input_audio_buffer.append", "audio": audio_b64})

    async def _append_silence(self, byte_count: int) -> None:
        if byte_count <= 0:
            return
        silence = b"\x00" * byte_count
        await self._append_audio_buffer(silence)
        self._pending_audio_16k.extend(silence)
        self._last_audio_append_ts = time.time()

    def _pending_audio_duration_ms(self) -> float:
        if not self._provider_rate or not self._bytes_per_sample:
            return 0.0
        return (len(self._pending_audio_16k) / (self._bytes_per_sample * self._provider_rate)) * 1000.0

    def _estimate_speech_ms(self, pcm16: bytes) -> float:
        if not pcm16 or not self._provider_rate or not self._bytes_per_sample:
            return 0.0
        try:
            rms = audioop.rms(pcm16, self._bytes_per_sample)
        except Exception:
            logger.debug("Failed to compute RMS for speech estimate", call_id=self._call_id, exc_info=True)
            return 0.0
        if rms < self._speech_rms_threshold:
            return 0.0
        return (len(pcm16) / (self._bytes_per_sample * self._provider_rate)) * 1000.0

    async def _maybe_commit_audio(self, *, force: bool = False) -> None:
        if not self.websocket or self.websocket.closed:
            return
        pending_bytes = len(self._pending_audio_16k)
        pending_ms = self._pending_audio_duration_ms()
        pending_speech_ms = self._pending_speech_ms
        if pending_bytes <= 0:
            logger.debug(
                "OpenAI commit skip: no pending audio",
                call_id=self._call_id,
                force=force,
            )
            return

        min_bytes = self._commit_min_bytes
        now = time.time()
        elapsed_since_last_commit = now - self._last_commit_ts if self._last_commit_ts else None
        elapsed_since_error = now - self._last_commit_error_ts if self._last_commit_error_ts else None
        elapsed_since_append = now - self._last_audio_append_ts if self._last_audio_append_ts else 0.0

        speech_ready = pending_speech_ms >= self._commit_min_ms
        if not speech_ready:
            # Flush if we've held the buffer longer than grace or accumulated a large backlog.
            if (
                elapsed_since_append >= self._commit_grace_seconds
                or (pending_ms >= (self._commit_min_ms * 3))
            ):
                speech_ready = True

        if not speech_ready and not force:
            logger.debug(
                "OpenAI commit skip: waiting for speech",
                call_id=self._call_id,
                pending_bytes=pending_bytes,
                pending_ms=pending_ms,
                pending_speech_ms=pending_speech_ms,
                min_ms=self._commit_min_ms,
                elapsed_since_append=elapsed_since_append,
                elapsed_since_last_commit=elapsed_since_last_commit,
                elapsed_since_error=elapsed_since_error,
                force=force,
            )
            return

        logger.info(
            "OpenAI commit pending",
            call_id=self._call_id,
            pending_bytes=pending_bytes,
            pending_ms=pending_ms,
            pending_speech_ms=pending_speech_ms,
            min_bytes=min_bytes,
            min_ms=self._commit_min_ms,
            elapsed_since_append=elapsed_since_append,
            elapsed_since_last_commit=elapsed_since_last_commit,
            elapsed_since_error=elapsed_since_error,
            force=force,
        )

        committed_bytes = pending_bytes
        committed_ms = pending_ms
        await self._send_json({"type": "input_audio_buffer.commit"})
        logger.debug(
            "OpenAI committed input audio",
            call_id=self._call_id,
            bytes_committed=committed_bytes,
            ms_committed=committed_ms,
            speech_ms_committed=pending_speech_ms,
        )
        self._pending_audio_16k.clear()
        self._pending_speech_ms = 0.0
        self._last_commit_ts = time.time()
        self._last_commit_error_ts = 0.0

    def _convert_inbound_audio(self, audio_chunk: bytes) -> Optional[bytes]:
        fmt = (self.config.input_encoding or "slin16").lower()
        pcm_8k = audio_chunk

        if fmt in ("ulaw", "mulaw", "mu-law"):
            pcm_8k = mulaw_to_pcm16le(audio_chunk)
        elif fmt not in ("slin16", "linear16", "pcm16"):
            logger.warning("Unsupported input encoding for OpenAI Realtime", encoding=fmt)
            return None

        if self.config.input_sample_rate_hz != self.config.provider_input_sample_rate_hz:
            pcm_16k, self._input_resample_state = resample_audio(
                pcm_8k,
                self.config.input_sample_rate_hz,
                self.config.provider_input_sample_rate_hz,
                state=self._input_resample_state,
            )
            return pcm_16k

        return pcm_8k

    async def _receive_loop(self):
        assert self.websocket is not None
        try:
            async for message in self.websocket:
                if isinstance(message, bytes):
                    continue
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    logger.warning("Failed to decode OpenAI Realtime payload", payload_preview=message[:64])
                    continue
                await self._handle_event(event)
        except asyncio.CancelledError:
            pass
        except (ConnectionClosedError, ConnectionClosedOK):
            logger.info("OpenAI Realtime connection closed", call_id=self._call_id)
        except Exception:
            logger.error("OpenAI Realtime receive loop error", call_id=self._call_id, exc_info=True)
        finally:
            await self._emit_audio_done()
            self._pending_response = False

    async def _handle_event(self, event: Dict[str, Any]):
        event_type = event.get("type")
        debug_enabled = logging.getLogger("src.providers.openai_realtime").isEnabledFor(logging.DEBUG)

        if debug_enabled:
            self._event_seq += 1
            logger.debug(
                "OpenAI event received",
                call_id=self._call_id,
                seq=self._event_seq,
                event_type=event_type,
                payload_keys=sorted(event.keys()),
            )

        # Log top-level error events with full payload to diagnose API contract issues
        if event_type == "error":
            error = event.get("error") or {}
            code = (error.get("code") or "").strip()
            if code == "input_audio_buffer_commit_empty":
                # Provider rejected commit: mark error timestamp and allow
                # additional audio to accumulate before retrying.
                async with self._audio_lock:
                    self._last_commit_error_ts = time.time()
                logger.warning(
                    "OpenAI commit rejected due to insufficient audio",
                    call_id=self._call_id,
                    provider_message=error.get("message"),
                )
            # Use 'error_event' key to avoid structlog 'event' argument conflict
            logger.error("OpenAI Realtime error event", call_id=self._call_id, error_event=event)
            return

        if event_type == "response.created":
            logger.debug("OpenAI response created", call_id=self._call_id)
            return

        if event_type == "response.delta":
            delta = event.get("delta") or {}
            delta_type = delta.get("type")

            if delta_type == "output_audio.delta":
                audio_b64 = delta.get("audio")
                if audio_b64:
                    await self._handle_output_audio(audio_b64)
            elif delta_type == "output_audio.done":
                await self._emit_audio_done()
            elif delta_type == "output_text.delta":
                text = delta.get("text")
                if text:
                    if debug_enabled:
                        self._text_chunk_seq += 1
                        logger.debug(
                            "OpenAI text delta received",
                            call_id=self._call_id,
                            seq=self._text_chunk_seq,
                            chars=len(text),
                            is_final=False,
                        )
                    await self._emit_transcript(text, is_final=False)
            elif delta_type == "output_text.done":
                if self._transcript_buffer:
                    await self._emit_transcript("", is_final=True)
            return

        # Modern event naming variants (top-level types)
        if event_type == "response.output_audio.delta":
            audio_b64 = (
                event.get("audio")
                or (event.get("delta") or {}).get("audio")
            )
            if audio_b64:
                await self._handle_output_audio(audio_b64)
            else:
                logger.debug("Missing audio in response.output_audio.delta", call_id=self._call_id)
            return

        if event_type == "response.output_audio.done":
            await self._emit_audio_done()
            return

        # Additional modern variant used by some previews
        if event_type == "response.audio.delta":
            audio_b64 = event.get("delta")
            if audio_b64:
                await self._handle_output_audio(audio_b64)
            else:
                logger.debug("Missing audio in response.audio.delta", call_id=self._call_id)
            return

        if event_type == "response.audio.done":
            await self._emit_audio_done()
            return

        if event_type == "response.audio_transcript.delta":
            delta = event.get("delta")
            text = event.get("text")
            if text is None:
                if isinstance(delta, dict):
                    text = delta.get("text")
                elif isinstance(delta, str):
                    text = delta
            if text:
                await self._emit_transcript(text, is_final=False)
            return

        if event_type == "response.audio_transcript.done":
            if self._transcript_buffer:
                await self._emit_transcript("", is_final=True)
            return

        if event_type in ("response.completed", "response.error", "response.cancelled", "response.done"):
            await self._emit_audio_done()
            if event_type == "response.error":
                logger.error("OpenAI Realtime response error", call_id=self._call_id, error=event.get("error"))
            self._pending_response = False
            if self._transcript_buffer:
                await self._emit_transcript("", is_final=True)
            return

        if event_type == "input_transcription.completed":
            transcript = event.get("transcript")
            if transcript:
                await self._emit_transcript(transcript, is_final=True)
            return

        if event_type == "response.output_text.delta":
            delta = event.get("delta") or {}
            text = delta.get("text")
            if text:
                if debug_enabled:
                    self._text_chunk_seq += 1
                    logger.debug(
                        "OpenAI text delta received",
                        call_id=self._call_id,
                        seq=self._text_chunk_seq,
                        chars=len(text),
                        is_final=False,
                    )
                await self._emit_transcript(text, is_final=False)
            return

        # Optional acks/telemetry for audio buffer operations
        if event_type and event_type.startswith("input_audio_buffer"):
            logger.debug("OpenAI input_audio_buffer ack", call_id=self._call_id, event_type=event_type)
            return

        # Additional transcript variants per guide
        if event_type == "response.output_audio_transcript.delta":
            delta = event.get("delta")
            text = None
            if isinstance(delta, dict):
                text = delta.get("text")
            elif isinstance(delta, str):
                text = delta
            if text:
                if debug_enabled:
                    self._text_chunk_seq += 1
                    logger.debug(
                        "OpenAI text delta received",
                        call_id=self._call_id,
                        seq=self._text_chunk_seq,
                        chars=len(text),
                        is_final=False,
                    )
                await self._emit_transcript(text, is_final=False)
            return

        if event_type == "response.output_audio_transcript.done":
            if debug_enabled and self._transcript_buffer:
                logger.debug(
                    "OpenAI text stream completed",
                    call_id=self._call_id,
                    total_chars=len(self._transcript_buffer),
                )
            if self._transcript_buffer:
                await self._emit_transcript("", is_final=True)
            return

        logger.debug("Unhandled OpenAI Realtime event", event_type=event_type)

    async def _handle_output_audio(self, audio_b64: str):
        if logging.getLogger("src.providers.openai_realtime").isEnabledFor(logging.DEBUG):
            self._audio_chunk_seq += 1
            logger.debug(
                "OpenAI audio delta received",
                call_id=self._call_id,
                chunk_index=self._audio_chunk_seq,
                payload_bytes=len(audio_b64 or ""),
            )
        try:
            pcm_24k = base64.b64decode(audio_b64)
        except Exception:
            logger.warning("Invalid base64 audio payload from OpenAI", call_id=self._call_id)
            return

        if not pcm_24k:
            return

        # If provider is emitting μ-law (g711_ulaw), pass-through directly to downstream.
        target_rate = self.config.target_sample_rate_hz
        pcm_target, self._output_resample_state = resample_audio(
            pcm_24k,
            self._provider_output_rate,
            target_rate,
            state=self._output_resample_state,
        )

        outbound = convert_pcm16le_to_target_format(pcm_target, self.config.target_encoding)
        if not outbound:
            return

        debug_enabled = logging.getLogger("src.providers.openai_realtime").isEnabledFor(logging.DEBUG)

        if self.on_event:
            if not self._first_output_chunk_logged:
                logger.info(
                    "OpenAI Realtime first audio chunk",
                    call_id=self._call_id,
                    bytes=len(outbound),
                    target_encoding=self.config.target_encoding,
                )
                self._first_output_chunk_logged = True

            if debug_enabled:
                logger.debug(
                    "Emitting AgentAudio chunk",
                    call_id=self._call_id,
                    chunk_index=self._audio_chunk_seq,
                    outbound_bytes=len(outbound),
                    provider_format=self._provider_output_format,
                )

            self._in_audio_burst = True
            try:
                await self.on_event(
                    {
                        "type": "AgentAudio",
                        "data": outbound,
                        "streaming_chunk": True,
                        "call_id": self._call_id,
                    }
                )
            except Exception:
                logger.error("Failed to emit AgentAudio event", call_id=self._call_id, exc_info=True)

    async def _emit_audio_done(self):
        if not self._in_audio_burst or not self.on_event or not self._call_id:
            return
        debug_enabled = logging.getLogger("src.providers.openai_realtime").isEnabledFor(logging.DEBUG)
        if debug_enabled:
            logger.debug(
                "Agent audio burst completed",
                call_id=self._call_id,
                chunks=self._audio_chunk_seq,
            )
        try:
            await self.on_event(
                {
                    "type": "AgentAudioDone",
                    "streaming_done": True,
                    "call_id": self._call_id,
                }
            )
        except Exception:
            logger.error("Failed to emit AgentAudioDone event", call_id=self._call_id, exc_info=True)
        finally:
            self._in_audio_burst = False
            self._output_resample_state = None
            self._first_output_chunk_logged = False
            self._audio_chunk_seq = 0
            self._text_chunk_seq = 0
            # After the first provider output completes, enable server-side VAD if deferred
            if self._defer_turn_detection and self._greeting_phase and not self._td_enabled:
                try:
                    await self._enable_turn_detection()
                except Exception:
                    logger.debug("Failed to enable turn_detection after greeting", call_id=self._call_id, exc_info=True)
                finally:
                    self._greeting_phase = False
                    self._defer_turn_detection = False

    async def _emit_transcript(self, text: str, *, is_final: bool):
        if not self.on_event or not self._call_id:
            return

        if text:
            self._transcript_buffer += text

        payload = {
            "type": "Transcript",
            "call_id": self._call_id,
            "text": text or self._transcript_buffer,
            "is_final": is_final,
        }
        try:
            await self.on_event(payload)
        except Exception:
            logger.error("Failed to emit transcript event", call_id=self._call_id, exc_info=True)

        if is_final:
            self._transcript_buffer = ""

    async def _enable_turn_detection(self):
        """Enable server-side turn detection via session.update after greeting."""
        if not getattr(self.config, "turn_detection", None):
            return
        if not self.websocket or self.websocket.closed:
            return
        td = self.config.turn_detection
        payload: Dict[str, Any] = {
            "type": "session.update",
            "event_id": f"sess-td-{uuid.uuid4()}",
            "session": {
                "turn_detection": {
                    "type": td.type,
                    "silence_duration_ms": td.silence_duration_ms,
                    "threshold": td.threshold,
                    "prefix_padding_ms": td.prefix_padding_ms,
                }
            },
        }
        await self._send_json(payload)
        self._td_enabled = True
        logger.info("OpenAI Realtime turn_detection enabled after greeting", call_id=self._call_id)

    async def _keepalive_loop(self):
        try:
            while self.websocket and not self.websocket.closed:
                await asyncio.sleep(_KEEPALIVE_INTERVAL_SEC)
                if not self.websocket or self.websocket.closed:
                    break
                try:
                    # Use native WebSocket ping control frames instead of
                    # sending an application-level {"type":"ping"} event,
                    # which Realtime rejects with invalid_request_error.
                    async with self._send_lock:
                        if self.websocket and not self.websocket.closed:
                            await self.websocket.ping()
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.debug("OpenAI Realtime keepalive failed", call_id=self._call_id, exc_info=True)
                    break
        except asyncio.CancelledError:
            pass
