"""
OpenAI Realtime provider implementation.

This module integrates OpenAI's server-side Realtime WebSocket transport into the
Asterisk AI Voice Agent without requiring WebRTC. Audio from AudioSocket is
converted to PCM16 @ 16 kHz, streamed to OpenAI, and PCM16 24 kHz output is
resampled to the configured downstream AudioSocket format (µ-law or PCM16 8 kHz).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
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

        await self._send_session_update()

        self._receive_task = asyncio.create_task(self._receive_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

        logger.info("OpenAI Realtime session established", call_id=call_id)

    async def send_audio(self, audio_chunk: bytes):
        if not audio_chunk:
            return
        if not self.websocket or self.websocket.closed:
            logger.debug("Dropping inbound audio: websocket not ready", call_id=self._call_id)
            return

        try:
            pcm16 = self._convert_inbound_audio(audio_chunk)
            if not pcm16:
                return

            audio_b64 = base64.b64encode(pcm16).decode("ascii")

            await self._send_json({"type": "input_audio_buffer.append", "audio": audio_b64})
            await self._send_json({"type": "input_audio_buffer.commit"})
            await self._ensure_response_request()
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
        base = self.config.base_url.rstrip("/")
        return f"{base}?model={self.config.model}"

    async def _send_session_update(self):
        payload: Dict[str, Any] = {
            "type": "session.update",
            "session": {
                "voice": self.config.voice,
                "modalities": self.config.response_modalities,
                "input_audio_format": "pcm16",
                "input_audio_sample_rate_hz": self.config.provider_input_sample_rate_hz,
                "output_audio_format": "pcm16",
                "output_audio_sample_rate_hz": self.config.output_sample_rate_hz,
            },
        }
        if self.config.instructions:
            payload["session"]["instructions"] = self.config.instructions

        await self._send_json(payload)

    async def _ensure_response_request(self):
        if self._pending_response or not self.websocket or self.websocket.closed:
            return

        response_payload: Dict[str, Any] = {
            "type": "response.create",
            "response": {
                "modalities": self.config.response_modalities,
                "metadata": {"call_id": self._call_id},
            },
        }
        if self.config.instructions:
            response_payload["response"]["instructions"] = self.config.instructions
        if "audio" in self.config.response_modalities:
            response_payload["response"]["audio"] = {
                "voice": self.config.voice,
                "format": "pcm16",
                "sample_rate_hz": self.config.output_sample_rate_hz,
            }

        await self._send_json(response_payload)
        self._pending_response = True

    async def _send_json(self, payload: Dict[str, Any]):
        if not self.websocket or self.websocket.closed:
            return
        message = json.dumps(payload)
        async with self._send_lock:
            await self.websocket.send(message)

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
                    await self._emit_transcript(text, is_final=False)
            elif delta_type == "output_text.done":
                if self._transcript_buffer:
                    await self._emit_transcript("", is_final=True)
            return

        if event_type in ("response.completed", "response.error", "response.cancelled"):
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
                await self._emit_transcript(text, is_final=False)
            return

        logger.debug("Unhandled OpenAI Realtime event", event_type=event_type)

    async def _handle_output_audio(self, audio_b64: str):
        try:
            pcm_24k = base64.b64decode(audio_b64)
        except Exception:
            logger.warning("Invalid base64 audio payload from OpenAI", call_id=self._call_id)
            return

        if not pcm_24k:
            return

        target_rate = self.config.target_sample_rate_hz
        pcm_target, self._output_resample_state = resample_audio(
            pcm_24k,
            self.config.output_sample_rate_hz,
            target_rate,
            state=self._output_resample_state,
        )

        outbound = convert_pcm16le_to_target_format(pcm_target, self.config.target_encoding)
        if not outbound:
            return

        if self.on_event:
            if not self._first_output_chunk_logged:
                logger.info(
                    "OpenAI Realtime first audio chunk",
                    call_id=self._call_id,
                    bytes=len(outbound),
                    target_encoding=self.config.target_encoding,
                )
                self._first_output_chunk_logged = True

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

    async def _keepalive_loop(self):
        try:
            while self.websocket and not self.websocket.closed:
                await asyncio.sleep(_KEEPALIVE_INTERVAL_SEC)
                if not self.websocket or self.websocket.closed:
                    break
                try:
                    async with self._send_lock:
                        if self.websocket and not self.websocket.closed:
                            await self.websocket.send(json.dumps({"type": "ping"}))
                except asyncio.CancelledError:
                    break
                except Exception:
                    logger.debug("OpenAI Realtime keepalive failed", call_id=self._call_id, exc_info=True)
                    break
        except asyncio.CancelledError:
            pass