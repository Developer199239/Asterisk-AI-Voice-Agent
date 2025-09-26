import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from typing import Any, Dict, Optional

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
    """# Milestone7: Lightweight per-connection state for selective mode handling."""
    call_id: str = "unknown"
    mode: str = DEFAULT_MODE


class AudioProcessor:
    """Handles audio format conversions for selective pipelines."""

    @staticmethod
    def _write_temp_file(suffix: str, payload: bytes) -> str:
        temp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        temp.write(payload)
        temp.flush()
        temp.close()
        return temp.name

    @staticmethod
    def resample_audio(input_data: bytes,
                       input_rate: int,
                       output_rate: int,
                       input_format: str = "raw",
                       output_format: str = "raw") -> bytes:
        try:
            input_path = AudioProcessor._write_temp_file(f".{input_format}", input_data)
            output_path = AudioProcessor._write_temp_file(f".{output_format}", b"")

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

            with open(output_path, "rb") as handle:
                resampled = handle.read()
            os.unlink(input_path)
            os.unlink(output_path)
            return resampled
        except Exception as exc:  # pragma: no cover
            logging.error("Audio resampling failed: %s", exc)
            return input_data

    @staticmethod
    def convert_to_ulaw_8k(input_data: bytes, input_rate: int) -> bytes:
        try:
            input_path = AudioProcessor._write_temp_file(".wav", input_data)
            output_path = AudioProcessor._write_temp_file(".ulaw", b"")

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

            with open(output_path, "rb") as handle:
                ulaw = handle.read()
            os.unlink(input_path)
            os.unlink(output_path)
            return ulaw
        except Exception as exc:  # pragma: no cover
            logging.error("uLaw conversion failed: %s", exc)
            return input_data


class EnhancedLocalAIServer:
    """Minimal pipeline variant demonstrating #Milestone7 selective mode support."""

    def __init__(self):
        self.stt_model_path = os.getenv(
            "LOCAL_STT_MODEL_PATH", "/app/models/stt/vosk-model-small-en-us-0.15"
        )
        self.llm_model_path = os.getenv(
            "LOCAL_LLM_MODEL_PATH", "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
        )
        self.tts_model_path = os.getenv(
            "LOCAL_TTS_MODEL_PATH", "/app/models/tts/en_US-lessac-medium.onnx"
        )

        self.stt_model: Optional[VoskModel] = None
        self.llm_model: Optional[Llama] = None
        self.tts_model: Optional[PiperVoice] = None
        self.audio_tools = AudioProcessor()

    async def initialize_models(self):
        await self._load_stt()
        await self._load_llm()
        await self._load_tts()
        logging.info("✅ Enhanced local models ready with selective mode support")

    async def _load_stt(self):
        if not os.path.exists(self.stt_model_path):
            raise FileNotFoundError(self.stt_model_path)
        self.stt_model = VoskModel(self.stt_model_path)
        logging.info("Loaded STT model at %s", self.stt_model_path)

    async def _load_llm(self):
        if not os.path.exists(self.llm_model_path):
            raise FileNotFoundError(self.llm_model_path)
        self.llm_model = Llama(model_path=self.llm_model_path, n_ctx=1024, verbose=False)
        logging.info("Loaded LLM model at %s", self.llm_model_path)

    async def _load_tts(self):
        if not os.path.exists(self.tts_model_path):
            raise FileNotFoundError(self.tts_model_path)
        self.tts_model = PiperVoice.load(self.tts_model_path)
        logging.info("Loaded TTS model at %s", self.tts_model_path)

    async def reload_models(self):
        logging.info("🔄 Hot reloading all models (#Milestone7 audit path)")
        await self.initialize_models()

    async def process_stt(self, pcm16: bytes, sample_rate_hz: int) -> str:
        if not self.stt_model:
            logging.warning("STT requested before model ready")
            return ""
        if sample_rate_hz != PCM16_TARGET_RATE:
            pcm16 = self.audio_tools.resample_audio(pcm16, sample_rate_hz, PCM16_TARGET_RATE)
        recognizer = KaldiRecognizer(self.stt_model, PCM16_TARGET_RATE)
        if recognizer.AcceptWaveform(pcm16):
            result = recognizer.Result()
        else:
            result = recognizer.FinalResult()
        text = json.loads(result).get("text", "").strip()
        logging.debug("STT transcript: %s", text)
        return text

    async def process_llm(self, text: str) -> str:
        if not text:
            return ""
        if not self.llm_model:
            logging.warning("LLM requested before model ready")
            return ""
        prompt = (
            "You are a focused AI assistant answering succinctly.\n\n"
            f"User: {text}\n\nAssistant:"
        )
        output = self.llm_model(prompt, max_tokens=64, stop=["User:"], echo=False)
        choices = output.get("choices", [])
        response = choices[0].get("text", "").strip() if choices else ""
        logging.debug("LLM response: %s", response)
        return response

    async def process_tts(self, text: str) -> bytes:
        if not text:
            return b""
        if not self.tts_model:
            logging.warning("TTS requested before model ready")
            return b""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
            wav_path = wav_file.name
        with wave.open(wav_path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(22050)
            for chunk in self.tts_model.synthesize(text):
                handle.writeframes(chunk.audio_int16_bytes)
        with open(wav_path, "rb") as wav_file:
            wav_bytes = wav_file.read()
        os.unlink(wav_path)
        return self.audio_tools.convert_to_ulaw_8k(wav_bytes, 22050)

    def _normalize_mode(self, data: Dict[str, Any], session: SessionContext) -> str:
        requested = data.get("mode")
        if requested in SUPPORTED_MODES:
            session.mode = requested
        return session.mode

    async def _send_json(self, websocket, payload: Dict[str, Any]) -> None:
        await websocket.send(json.dumps(payload))

    async def _handle_tts(self, websocket, session: SessionContext, data: Dict[str, Any]) -> None:
        text = data.get("text", "")
        request_id = data.get("request_id")
        audio = await self.process_tts(text)
        if request_id:
            await self._send_json(
                websocket,
                {
                    "type": "tts_audio",
                    "call_id": session.call_id,
                    "mode": "tts",
                    "request_id": request_id,
                    "encoding": "mulaw",
                    "sample_rate_hz": ULAW_SAMPLE_RATE,
                    "byte_length": len(audio),
                },
            )
        if audio:
            await websocket.send(audio)

    async def _route_audio(
        self,
        websocket,
        session: SessionContext,
        payload: Dict[str, Any],
        pcm_bytes: bytes,
    ) -> None:
        mode = self._normalize_mode(payload, session)
        rate = int(payload.get("rate", PCM16_TARGET_RATE))
        request_id = payload.get("request_id")

        if payload.get("call_id"):
            session.call_id = payload["call_id"]

        if mode == "stt":
            transcript = await self.process_stt(pcm_bytes, rate)
            await self._send_json(
                websocket,
                {
                    "type": "stt_result",
                    "text": transcript,
                    "call_id": session.call_id,
                    "mode": "stt",
                    "request_id": request_id,
                },
            )
            return

        if mode == "llm":
            transcript = await self.process_stt(pcm_bytes, rate)
            if not transcript:
                return
            llm_response = await self.process_llm(transcript)
            await self._send_json(
                websocket,
                {
                    "type": "llm_response",
                    "text": llm_response,
                    "call_id": session.call_id,
                    "mode": "llm",
                    "request_id": request_id,
                },
            )
            return

        if mode == "tts":
            logging.warning("Received raw audio for mode='tts'; ignoring frame")
            return

        # Full pipeline (#Milestone7 default path)
        transcript = await self.process_stt(pcm_bytes, rate)
        if not transcript:
            return
        llm_response = await self.process_llm(transcript)
        if not llm_response:
            return
        audio = await self.process_tts(llm_response)
        if request_id:
            await self._send_json(
                websocket,
                {
                    "type": "tts_audio",
                    "call_id": session.call_id,
                    "mode": "full",
                    "request_id": request_id,
                    "encoding": "mulaw",
                    "sample_rate_hz": ULAW_SAMPLE_RATE,
                    "byte_length": len(audio),
                },
            )
        if audio:
            await websocket.send(audio)

    async def _handle_json(self, websocket, session: SessionContext, message: str) -> None:
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logging.warning("Invalid JSON message: %s", message)
            return

        msg_type = data.get("type")
        if msg_type == "set_mode":
            requested = data.get("mode", DEFAULT_MODE)
            if requested in SUPPORTED_MODES:
                session.mode = requested
                logging.info("Session mode set to %s", session.mode)
            else:
                logging.warning("Unsupported mode requested: %s", requested)
            return

        if msg_type == "audio":
            encoded = data.get("data", "")
            if not encoded:
                logging.warning("Audio payload missing 'data'")
                return
            try:
                pcm_bytes = base64.b64decode(encoded)
            except Exception as exc:
                logging.warning("Failed to decode audio payload: %s", exc)
                return
            await self._route_audio(websocket, session, data, pcm_bytes)
            return

        if msg_type == "tts_request":
            await self._handle_tts(websocket, session, data)
            return

        if msg_type == "llm_request":
            text = data.get("text", "")
            request_id = data.get("request_id")
            response = await self.process_llm(text)
            await self._send_json(
                websocket,
                {
                    "type": "llm_response",
                    "text": response,
                    "call_id": session.call_id,
                    "mode": "llm",
                    "request_id": request_id,
                },
            )
            return

        if msg_type == "reload_models":
            await self.reload_models()
            await self._send_json(
                websocket,
                {"type": "reload_response", "status": "success", "message": "Models reloaded"},
            )
            return

        logging.warning("Unknown message type: %s", msg_type)

    async def handler(self, websocket):
        logging.info("🔌 Enhanced connection established: %s", websocket.remote_address)
        session = SessionContext()
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    await self._route_audio(websocket, session, {"mode": session.mode}, message)
                else:
                    await self._handle_json(websocket, session, message)
        except Exception as exc:  # pragma: no cover
            logging.error("WebSocket handler error: %s", exc, exc_info=True)
        finally:
            logging.info("🔌 Enhanced connection closed: %s", websocket.remote_address)


async def main():
    server = EnhancedLocalAIServer()
    await server.initialize_models()
    async with serve(server.handler, "0.0.0.0", 8765, max_size=None):
        logging.info(
            "🚀 Enhanced Local AI Server ready with #Milestone7 selective modes (ws://0.0.0.0:8765)"
        )
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
