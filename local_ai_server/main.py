import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from websockets.server import serve
from vosk import Model as VoskModel, KaldiRecognizer
from llama_cpp import Llama
from piper import PiperVoice

logging.basicConfig(level=logging.INFO)

SUPPORTED_MODES = {"full", "stt", "llm", "tts"}
DEFAULT_MODE = "full"
ULAW_SAMPLE_RATE = 8000
PCM16_TARGET_RATE = 16000


@dataclass
class SessionContext:
    """# Milestone7: Track per-connection defaults for selective mode handling."""
    call_id: str = "unknown"
    mode: str = DEFAULT_MODE
    recognizer: Optional[KaldiRecognizer] = None
    last_partial: str = ""
    partial_emitted: bool = False


class AudioProcessor:
    """Handles audio format conversions for MVP uLaw 8kHz pipeline"""

    @staticmethod
    def resample_audio(input_data: bytes,
                       input_rate: int,
                       output_rate: int,
                       input_format: str = "raw",
                       output_format: str = "raw") -> bytes:
        """Resample audio using sox"""
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{input_format}", delete=False) as input_file:
                input_file.write(input_data)
                input_path = input_file.name

            with tempfile.NamedTemporaryFile(suffix=f".{output_format}", delete=False) as output_file:
                output_path = output_file.name

            # Use sox to resample - specify input format for raw PCM data
            cmd = [
                "sox",
                "-t",
                "raw",
                "-r",
                str(input_rate),
                "-e",
                "signed-integer",
                "-b",
                "16",
                "-c",
                "1",
                input_path,
                "-r",
                str(output_rate),
                "-c",
                "1",
                "-e",
                "signed-integer",
                "-b",
                "16",
                output_path,
            ]

            subprocess.run(cmd, capture_output=True, check=True)

            with open(output_path, "rb") as f:
                resampled_data = f.read()

            os.unlink(input_path)
            os.unlink(output_path)

            return resampled_data

        except Exception as exc:  # pragma: no cover - defensive guard
            logging.error("Audio resampling failed: %s", exc)
            return input_data

    @staticmethod
    def convert_to_ulaw_8k(input_data: bytes, input_rate: int) -> bytes:
        """Convert audio to uLaw 8kHz format for ARI playback"""
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as input_file:
                input_file.write(input_data)
                input_path = input_file.name

            with tempfile.NamedTemporaryFile(suffix=".ulaw", delete=False) as output_file:
                output_path = output_file.name

            cmd = [
                "sox",
                input_path,
                "-r",
                str(ULAW_SAMPLE_RATE),
                "-c",
                "1",
                "-e",
                "mu-law",
                "-t",
                "raw",
                output_path,
            ]

            subprocess.run(cmd, capture_output=True, check=True)

            with open(output_path, "rb") as f:
                ulaw_data = f.read()

            os.unlink(input_path)
            os.unlink(output_path)

            return ulaw_data

        except Exception as exc:  # pragma: no cover - defensive guard
            logging.error("uLaw conversion failed: %s", exc)
            return input_data


class LocalAIServer:
    def __init__(self):
        self.stt_model: Optional[VoskModel] = None
        self.llm_model: Optional[Llama] = None
        self.tts_model: Optional[PiperVoice] = None
        self.audio_processor = AudioProcessor()

        # Model paths
        self.stt_model_path = os.getenv(
            "LOCAL_STT_MODEL_PATH", "/app/models/stt/vosk-model-small-en-us-0.15"
        )
        self.llm_model_path = os.getenv(
            "LOCAL_LLM_MODEL_PATH", "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
        )
        self.tts_model_path = os.getenv(
            "LOCAL_TTS_MODEL_PATH", "/app/models/tts/en_US-lessac-medium.onnx"
        )

        default_threads = max(1, min(16, os.cpu_count() or 1))
        self.llm_threads = int(os.getenv("LOCAL_LLM_THREADS", str(default_threads)))
        self.llm_context = int(os.getenv("LOCAL_LLM_CONTEXT", "768"))
        self.llm_batch = int(os.getenv("LOCAL_LLM_BATCH", "256"))
        self.llm_max_tokens = int(os.getenv("LOCAL_LLM_MAX_TOKENS", "48"))
        self.llm_temperature = float(os.getenv("LOCAL_LLM_TEMPERATURE", "0.2"))
        self.llm_top_p = float(os.getenv("LOCAL_LLM_TOP_P", "0.85"))
        self.llm_repeat_penalty = float(os.getenv("LOCAL_LLM_REPEAT_PENALTY", "1.05"))

        # Audio buffering for STT (20ms chunks need to be buffered for effective STT)
        self.audio_buffer = b""
        self.buffer_size_bytes = PCM16_TARGET_RATE * 2 * 1.0  # 1 second at 16kHz (32000 bytes)
        self.buffer_timeout_ms = 1000  # Process buffer after 1 second of silence

    async def initialize_models(self):
        """Initialize all AI models with proper error handling"""
        logging.info("🚀 Initializing enhanced AI models for MVP...")

        await self._load_stt_model()
        await self._load_llm_model()
        await self._load_tts_model()

        logging.info("✅ All models loaded successfully for MVP pipeline")

    async def _load_stt_model(self):
        """Load STT model with 16kHz support"""
        try:
            if not os.path.exists(self.stt_model_path):
                raise FileNotFoundError(f"STT model not found at {self.stt_model_path}")

            self.stt_model = VoskModel(self.stt_model_path)
            logging.info("✅ STT model loaded: %s (16kHz native)", self.stt_model_path)
        except Exception as exc:
            logging.error("❌ Failed to load STT model: %s", exc)
            raise

    async def _load_llm_model(self):
        """Load LLM model with optimized parameters for faster inference"""
        try:
            if not os.path.exists(self.llm_model_path):
                raise FileNotFoundError(f"LLM model not found at {self.llm_model_path}")

            self.llm_model = Llama(
                model_path=self.llm_model_path,
                n_ctx=self.llm_context,
                n_threads=self.llm_threads,
                n_batch=self.llm_batch,
                n_gpu_layers=0,
                verbose=False,
                use_mmap=True,
                use_mlock=True,
            )
            logging.info("✅ LLM model loaded: %s", self.llm_model_path)
            logging.info(
                "📊 LLM Config: ctx=%s, threads=%s, batch=%s, max_tokens=%s, temp=%s",
                self.llm_context,
                self.llm_threads,
                self.llm_batch,
                self.llm_max_tokens,
                self.llm_temperature,
            )
        except Exception as exc:
            logging.error("❌ Failed to load LLM model: %s", exc)
            raise

    async def _load_tts_model(self):
        """Load TTS model (Piper) with 22kHz support"""
        try:
            if not os.path.exists(self.tts_model_path):
                raise FileNotFoundError(f"TTS model not found at {self.tts_model_path}")

            self.tts_model = PiperVoice.load(self.tts_model_path)
            logging.info("✅ TTS model loaded: %s (22kHz native)", self.tts_model_path)
        except Exception as exc:
            logging.error("❌ Failed to load TTS model: %s", exc)
            raise

    async def reload_models(self):
        """Hot reload all models without restarting the server"""
        logging.info("🔄 Hot reloading models...")
        try:
            await self.initialize_models()
            logging.info("✅ Models reloaded successfully")
        except Exception as exc:
            logging.error("❌ Model reload failed: %s", exc)
            raise

    async def reload_llm_only(self):
        """Hot reload only the LLM model with optimized parameters"""
        logging.info("🔄 Hot reloading LLM model with optimizations...")
        try:
            if self.llm_model:
                del self.llm_model
                self.llm_model = None
                logging.info("🗑️ Previous LLM model unloaded")

            await self._load_llm_model()
            logging.info("✅ LLM model reloaded with optimizations")
            logging.info(
                "📊 Optimized: ctx=%s, batch=%s, temp=%s, max_tokens=%s",
                self.llm_context,
                self.llm_batch,
                self.llm_temperature,
                self.llm_max_tokens,
            )
        except Exception as exc:
            logging.error("❌ LLM reload failed: %s", exc)
            raise

    async def process_stt_buffered(self, audio_data: bytes) -> str:
        """Process STT with buffering for 20ms chunks"""
        try:
            if not self.stt_model:
                logging.error("STT model not loaded")
                return ""

            self.audio_buffer += audio_data
            logging.debug(
                "🎵 STT BUFFER - Added %s bytes, buffer now %s bytes",
                len(audio_data),
                len(self.audio_buffer),
            )

            if len(self.audio_buffer) < self.buffer_size_bytes:
                logging.debug(
                    "🎵 STT BUFFER - Not enough audio yet (%s/%s bytes)",
                    len(self.audio_buffer),
                    self.buffer_size_bytes,
                )
                return ""

            logging.info("🎵 STT PROCESSING - Processing buffered audio: %s bytes", len(self.audio_buffer))

            recognizer = KaldiRecognizer(self.stt_model, PCM16_TARGET_RATE)

            if recognizer.AcceptWaveform(self.audio_buffer):
                result = json.loads(recognizer.Result())
            else:
                result = json.loads(recognizer.FinalResult())

            transcript = result.get("text", "").strip()
            if transcript:
                logging.info("📝 STT RESULT - Transcript: '%s'", transcript)
            else:
                logging.debug("📝 STT RESULT - Transcript empty after buffering")

            self.audio_buffer = b""
            return transcript

        except Exception as exc:
            logging.error("Buffered STT processing failed: %s", exc, exc_info=True)
            return ""

    async def process_stt(self, audio_data: bytes, input_rate: int = PCM16_TARGET_RATE) -> str:
        """Process STT with Vosk only - optimized for telephony audio"""
        try:
            if not self.stt_model:
                logging.error("STT model not loaded")
                return ""

            logging.debug("🎤 STT INPUT - %s bytes at %s Hz", len(audio_data), input_rate)

            if input_rate != PCM16_TARGET_RATE:
                logging.debug(
                    "🎵 STT INPUT - Resampling %s Hz → %s Hz: %s bytes",
                    input_rate,
                    PCM16_TARGET_RATE,
                    len(audio_data),
                )
                resampled_audio = self.audio_processor.resample_audio(
                    audio_data, input_rate, PCM16_TARGET_RATE, "raw", "raw"
                )
            else:
                resampled_audio = audio_data

            recognizer = KaldiRecognizer(self.stt_model, PCM16_TARGET_RATE)

            if recognizer.AcceptWaveform(resampled_audio):
                result = json.loads(recognizer.Result())
            else:
                result = json.loads(recognizer.FinalResult())

            transcript = result.get("text", "").strip()
            if transcript:
                logging.info(
                    "📝 STT RESULT - Vosk transcript: '%s' (length: %s)",
                    transcript,
                    len(transcript),
                )
            else:
                logging.debug("📝 STT RESULT - Vosk transcript empty")
            return transcript

        except Exception as exc:
            logging.error("STT processing failed: %s", exc, exc_info=True)
            return ""

    async def process_llm(self, text: str) -> str:
        """Process LLM with optimized parameters for faster real-time responses"""
        try:
            if not self.llm_model:
                logging.warning("LLM model not loaded, using fallback")
                return "I'm here to help you. How can I assist you today?"

            prompt = (
                "You are a helpful AI voice assistant. Respond naturally and conversationally to the user's input.\n\n"
                f"User: {text}\n\nAssistant:"
            )

            output = self.llm_model(
                prompt,
                max_tokens=self.llm_max_tokens,
                stop=["User:", "\n\n", "Assistant:"],
                echo=False,
                temperature=self.llm_temperature,
                top_p=self.llm_top_p,
                repeat_penalty=self.llm_repeat_penalty,
            )

            choices = output.get("choices", []) if isinstance(output, dict) else []
            if not choices:
                logging.warning("🤖 LLM RESULT - No choices returned, using fallback response")
                return "I'm here to help you. How can I assist you today?"

            response = choices[0].get("text", "").strip()
            logging.info("🤖 LLM RESULT - Response: '%s'", response)
            return response

        except Exception as exc:
            logging.error("LLM processing failed: %s", exc, exc_info=True)
            return "I'm here to help you. How can I assist you today?"

    async def process_tts(self, text: str) -> bytes:
        """Process TTS with 8kHz uLaw generation directly"""
        try:
            if not self.tts_model:
                logging.error("TTS model not loaded")
                return b""

            logging.debug("🔊 TTS INPUT - Generating 22kHz audio for: '%s'", text)

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = wav_file.name

            with wave.open(wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(22050)

                audio_generator = self.tts_model.synthesize(text)
                for audio_chunk in audio_generator:
                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

            with open(wav_path, "rb") as wav_file:
                wav_data = wav_file.read()

            ulaw_data = self.audio_processor.convert_to_ulaw_8k(wav_data, 22050)
            os.unlink(wav_path)

            logging.info("🔊 TTS RESULT - Generated uLaw 8kHz audio: %s bytes", len(ulaw_data))
            return ulaw_data

        except Exception as exc:
            logging.error("TTS processing failed: %s", exc, exc_info=True)
            return b""

    def _reset_stt_session(self, session: SessionContext) -> None:
        """Clear recognizer state after emitting a final transcript."""
        session.recognizer = None
        session.last_partial = ""
        session.partial_emitted = False

    def _ensure_stt_recognizer(self, session: SessionContext) -> Optional[KaldiRecognizer]:
        if not self.stt_model:
            logging.error("STT model not loaded")
            return None
        if session.recognizer is None:
            session.recognizer = KaldiRecognizer(self.stt_model, PCM16_TARGET_RATE)
            session.last_partial = ""
            session.partial_emitted = False
        return session.recognizer

    async def _process_stt_stream(
        self,
        session: SessionContext,
        audio_data: bytes,
        input_rate: int,
    ) -> List[Dict[str, Any]]:
        """Feed audio into the session recognizer and return transcript updates."""
        recognizer = self._ensure_stt_recognizer(session)
        if not recognizer:
            return []

        if input_rate != PCM16_TARGET_RATE:
            logging.debug(
                "🎵 STT INPUT - Resampling %s Hz → %s Hz: %s bytes",
                input_rate,
                PCM16_TARGET_RATE,
                len(audio_data),
            )
            audio_bytes = self.audio_processor.resample_audio(
                audio_data, input_rate, PCM16_TARGET_RATE, "raw", "raw"
            )
        else:
            audio_bytes = audio_data

        updates: List[Dict[str, Any]] = []

        try:
            has_final = recognizer.AcceptWaveform(audio_bytes)
        except Exception as exc:  # pragma: no cover - defensive guard
            logging.error("STT recognition failed: %s", exc, exc_info=True)
            return updates

        if has_final:
            try:
                result = json.loads(recognizer.Result() or "{}")
            except json.JSONDecodeError:
                result = {}
            text = (result.get("text") or "").strip()
            confidence = result.get("confidence")
            logging.info(
                "📝 STT RESULT - Vosk final transcript: '%s'",
                text,
            )
            updates.append(
                {
                    "text": text,
                    "is_final": True,
                    "is_partial": False,
                    "confidence": confidence,
                }
            )
            self._reset_stt_session(session)
            return updates

        # Emit partial result to mirror remote streaming providers.
        try:
            partial_payload = json.loads(recognizer.PartialResult() or "{}")
        except json.JSONDecodeError:
            partial_payload = {}
        partial_text = (partial_payload.get("partial") or "").strip()
        if partial_text != session.last_partial or not session.partial_emitted:
            session.last_partial = partial_text
            session.partial_emitted = True
            logging.debug(
                "📝 STT PARTIAL - '%s'",
                partial_text,
            )
            updates.append(
                {
                    "text": partial_text,
                    "is_final": False,
                    "is_partial": True,
                    "confidence": None,
                }
            )

        return updates

    def _normalize_mode(self, data_mode: Optional[str], session: SessionContext) -> str:
        if data_mode and data_mode in SUPPORTED_MODES:
            session.mode = data_mode
            return data_mode
        return session.mode

    async def _send_json(self, websocket, payload: Dict[str, Any]) -> None:
        await websocket.send(json.dumps(payload))

    async def _emit_stt_result(
        self,
        websocket,
        transcript: str,
        session: SessionContext,
        request_id: Optional[str],
        *,
        source_mode: str,
        is_final: bool,
        is_partial: bool,
        confidence: Optional[float],
    ) -> None:
        payload = {
            "type": "stt_result",
            "text": transcript,
            "call_id": session.call_id,
            "mode": source_mode,
            "is_final": is_final,
            "is_partial": is_partial,
        }
        if confidence is not None:
            payload["confidence"] = confidence
        if request_id:
            payload["request_id"] = request_id
        await self._send_json(websocket, payload)

    async def _emit_llm_response(
        self,
        websocket,
        llm_response: str,
        session: SessionContext,
        request_id: Optional[str],
        *,
        source_mode: str,
    ) -> None:
        if not llm_response:
            return
        payload = {
            "type": "llm_response",
            "text": llm_response,
            "call_id": session.call_id,
            "mode": source_mode,
        }
        if request_id:
            payload["request_id"] = request_id
        await self._send_json(websocket, payload)

    async def _emit_tts_audio(
        self,
        websocket,
        audio_bytes: bytes,
        session: SessionContext,
        request_id: Optional[str],
        *,
        source_mode: str,
    ) -> None:
        if request_id:
            # Milestone7: emit metadata event for selective TTS while keeping binary transport.
            metadata = {
                "type": "tts_audio",
                "call_id": session.call_id,
                "mode": source_mode,
                "request_id": request_id,
                "encoding": "mulaw",
                "sample_rate_hz": ULAW_SAMPLE_RATE,
                "byte_length": len(audio_bytes or b""),
            }
            await self._send_json(websocket, metadata)
        if audio_bytes:
            await websocket.send(audio_bytes)

    async def _handle_audio_payload(
        self,
        websocket,
        session: SessionContext,
        data: Dict[str, Any],
        *,
        incoming_bytes: Optional[bytes] = None,
    ) -> None:
        """
        Decode audio payload and route it through the pipeline according to the requested mode.
        """
        mode = self._normalize_mode(data.get("mode"), session)
        request_id = data.get("request_id")
        call_id = data.get("call_id")
        if call_id:
            session.call_id = call_id

        if incoming_bytes is None:
            encoded_audio = data.get("data", "")
            if not encoded_audio:
                logging.warning("Audio payload missing 'data'")
                return
            try:
                audio_bytes = base64.b64decode(encoded_audio)
            except Exception as exc:
                logging.warning("Failed to decode base64 audio payload: %s", exc)
                return
        else:
            audio_bytes = incoming_bytes

        if not audio_bytes:
            logging.debug("Audio payload empty after decoding")
            return

        input_rate = int(data.get("rate", PCM16_TARGET_RATE))

        if mode in {"stt", "llm", "full"}:
            stt_events = await self._process_stt_stream(session, audio_bytes, input_rate)
            if not stt_events:
                return

            for event in stt_events:
                await self._emit_stt_result(
                    websocket,
                    event.get("text", ""),
                    session,
                    request_id,
                    source_mode=mode,
                    is_final=event.get("is_final", False),
                    is_partial=event.get("is_partial", False),
                    confidence=event.get("confidence"),
                )

                if not event.get("is_final"):
                    continue

                final_text = (event.get("text") or "").strip()
                if not final_text:
                    continue

                if mode in {"llm", "full"}:
                    llm_response = await self.process_llm(final_text)
                    await self._emit_llm_response(
                        websocket,
                        llm_response,
                        session,
                        request_id,
                        source_mode=mode if mode != "full" else "llm",
                    )

                    if mode == "full" and llm_response:
                        audio_response = await self.process_tts(llm_response)
                        await self._emit_tts_audio(
                            websocket,
                            audio_response,
                            session,
                            request_id,
                            source_mode="full",
                        )
            return

        if mode == "tts":
            logging.warning("Received audio payload with mode=tts; expected text request. Skipping.")
            return

        # Default full pipeline (STT → LLM → TTS).
        stt_events = await self._process_stt_stream(session, audio_bytes, input_rate)
        for event in stt_events:
            await self._emit_stt_result(
                websocket,
                event.get("text", ""),
                session,
                request_id,
                source_mode="full",
                is_final=event.get("is_final", False),
                is_partial=event.get("is_partial", False),
                confidence=event.get("confidence"),
            )

            if not event.get("is_final"):
                continue

            final_text = (event.get("text") or "").strip()
            if not final_text:
                continue

            llm_response = await self.process_llm(final_text)
            if not llm_response:
                continue

            audio_response = await self.process_tts(llm_response)
            await self._emit_tts_audio(
                websocket,
                audio_response,
                session,
                request_id,
                source_mode="full",
            )

    async def _handle_tts_request(
        self,
        websocket,
        session: SessionContext,
        data: Dict[str, Any],
    ) -> None:
        text = data.get("text", "").strip()
        if not text:
            logging.warning("TTS request missing 'text'")
            return

        mode = self._normalize_mode(data.get("mode"), session)
        if mode not in {"tts", "full"}:
            # Milestone7: allow callers to force binary TTS even outside default 'tts' mode.
            logging.debug("Overriding session mode to 'tts' for explicit TTS request")
            mode = "tts"

        request_id = data.get("request_id")
        call_id = data.get("call_id")
        if call_id:
            session.call_id = call_id

        audio_response = await self.process_tts(text)
        await self._emit_tts_audio(
            websocket,
            audio_response,
            session,
            request_id,
            source_mode=mode,
        )

    async def _handle_llm_request(
        self,
        websocket,
        session: SessionContext,
        data: Dict[str, Any],
    ) -> None:
        text = data.get("text", "").strip()
        if not text:
            logging.warning("LLM request missing 'text'")
            return

        mode = self._normalize_mode(data.get("mode"), session)
        request_id = data.get("request_id")
        call_id = data.get("call_id")
        if call_id:
            session.call_id = call_id

        llm_response = await self.process_llm(text)
        await self._emit_llm_response(
            websocket,
            llm_response,
            session,
            request_id,
            source_mode=mode or "llm",
        )

    async def _handle_json_message(self, websocket, session: SessionContext, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logging.warning("❓ Invalid JSON message: %s", message)
            return

        msg_type = data.get("type")
        if not msg_type:
            logging.warning("JSON payload missing 'type': %s", data)
            return

        if msg_type == "set_mode":
            # Milestone7: allow clients to pre-select default mode for subsequent binary frames.
            requested = data.get("mode", DEFAULT_MODE)
            if requested in SUPPORTED_MODES:
                session.mode = requested
                logging.info("Session mode updated to %s", session.mode)
            else:
                logging.warning("Unsupported mode requested: %s", requested)
            call_id = data.get("call_id")
            if call_id:
                session.call_id = call_id
            response = {
                "type": "mode_ready",
                "mode": session.mode,
                "call_id": session.call_id,
            }
            await self._send_json(websocket, response)
            return

        if msg_type == "audio":
            await self._handle_audio_payload(websocket, session, data)
            return

        if msg_type == "tts_request":
            await self._handle_tts_request(websocket, session, data)
            return

        if msg_type == "llm_request":
            await self._handle_llm_request(websocket, session, data)
            return

        if msg_type == "reload_models":
            logging.info("🔄 RELOAD REQUEST - Hot reloading all models...")
            await self.reload_models()
            response = {
                "type": "reload_response",
                "status": "success",
                "message": "All models reloaded successfully",
            }
            await self._send_json(websocket, response)
            return

        if msg_type == "reload_llm":
            logging.info("🔄 LLM RELOAD REQUEST - Hot reloading LLM with optimizations...")
            await self.reload_llm_only()
            response = {
                "type": "reload_response",
                "status": "success",
                "message": (
                    "LLM model reloaded with optimizations (ctx="
                    f"{self.llm_context}, batch={self.llm_batch}, temp={self.llm_temperature}, "
                    f"max_tokens={self.llm_max_tokens})"
                ),
            }
            await self._send_json(websocket, response)
            return

        logging.warning("❓ Unknown message type: %s", msg_type)

    async def _handle_binary_message(self, websocket, session: SessionContext, message: bytes) -> None:
        logging.info("🎵 AUDIO INPUT - Received binary audio: %s bytes", len(message))
        await self._handle_audio_payload(
            websocket,
            session,
            data={"mode": session.mode},
            incoming_bytes=message,
        )

    async def handler(self, websocket):
        """Enhanced WebSocket handler with MVP pipeline and hot reloading"""
        logging.info("🔌 New connection established: %s", websocket.remote_address)
        session = SessionContext()
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    await self._handle_binary_message(websocket, session, message)
                else:
                    await self._handle_json_message(websocket, session, message)
        except Exception as exc:
            logging.error("❌ WebSocket handler error: %s", exc, exc_info=True)
        finally:
            self._reset_stt_session(session)
            logging.info("🔌 Connection closed: %s", websocket.remote_address)


async def main():
    """Main server function"""
    server = LocalAIServer()
    await server.initialize_models()

    async with serve(
        server.handler,
        "0.0.0.0",
        8765,
        ping_interval=30,
        ping_timeout=30,
        max_size=None,
    ):
        logging.info("🚀 Enhanced Local AI Server started on ws://0.0.0.0:8765")
        logging.info(
            "📋 Pipeline: ExternalMedia (8kHz) → STT (16kHz) → LLM → TTS (8kHz uLaw) "
            "- now with #Milestone7 selective mode support"
        )
        await asyncio.Future()  # Run forever


if __name__ == "__main__":
    asyncio.run(main())
