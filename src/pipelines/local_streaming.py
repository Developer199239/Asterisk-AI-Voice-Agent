"""
Local streaming audio pipeline.

Phase A scope:
- Implement in-memory STT buffering with VAD using Vosk.
- Keep existing TTS playback path unchanged (engine still uses file playback).

Future phases will implement streaming TTS and external media send.
"""

from __future__ import annotations

import audioop
from typing import AsyncIterator, Optional

import webrtcvad  # type: ignore

from src.pipelines.base import AudioPipeline
from src.models.cache import model_cache


class LocalStreamingPipeline(AudioPipeline):
    """Streaming pipeline using Vosk STT with VAD and in-memory buffering.

    Note: Input chunks are expected to be 8kHz ulaw bytes from the snoop channel.
    We convert to 16-bit PCM and upsample if needed for recognizer compatibility.
    """

    def __init__(self, config):
        self.config = config
        self.stt_audio_buffer = bytearray()
        self.vad = webrtcvad.Vad(getattr(config, "vad_aggressiveness", 2))

        self.vosk_model = None
        self.vosk_recognizer = None

    async def start(self) -> None:
        """Load Vosk model once and prepare recognizer template."""
        stt_path = self.config.providers.get("local", {}).get("stt_model")

        def _load_vosk():
            import vosk  # local import to avoid import cost if unused
            return vosk.Model(stt_path)

        self.vosk_model = model_cache.get_model(f"vosk::{stt_path}", _load_vosk)

        # recognizer needs to be created per stream/sample rate; we'll create
        # lazily on first audio as needed.

    async def stop(self) -> None:
        """No-op for now. Models are kept hot via cache."""
        return

    async def process_stt(self, audio_chunk: bytes) -> Optional[str]:
        """Buffer ulaw chunk, run VAD, and emit transcript when utterance ends."""
        if not audio_chunk:
            return None

        # Convert 8-bit ulaw → 16-bit PCM mono @ 8kHz
        pcm16 = audioop.ulaw2lin(audio_chunk, 2)

        # VAD expects 16k mono 16-bit PCM frames of 10/20/30ms. Upsample to 16k.
        pcm16_16k, _ = audioop.ratecv(pcm16, 2, 1, 8000, 16000, None)

        self.stt_audio_buffer.extend(pcm16_16k)

        # Choose 20ms frames for VAD
        frame_bytes = int(0.02 * 16000) * 2  # samples * 2 bytes per sample

        # Check last frame for speech/non-speech
        if len(self.stt_audio_buffer) < frame_bytes:
            return None

        last_frame = self.stt_audio_buffer[-frame_bytes:]
        is_speech = self.vad.is_speech(last_frame, 16000)

        # If non-speech detected and we have accumulated audio, finalize utterance
        if not is_speech and len(self.stt_audio_buffer) >= frame_bytes * 5:
            # Create a recognizer and feed the buffered PCM
            import vosk  # local import
            if self.vosk_recognizer is None:
                self.vosk_recognizer = vosk.KaldiRecognizer(self.vosk_model, 16000)

            # Feed in chunks to recognizer
            text = ""
            buf = bytes(self.stt_audio_buffer)
            self.stt_audio_buffer.clear()
            step = 3200  # 100ms at 16kHz * 2 bytes
            for i in range(0, len(buf), step):
                self.vosk_recognizer.AcceptWaveform(buf[i : i + step])
            result = self.vosk_recognizer.FinalResult()
            try:
                import json
                parsed = json.loads(result)
                text = (parsed.get("text") or "").strip()
            except Exception:
                text = ""

            return text or None

        return None

    async def process_tts(self, text: str) -> AsyncIterator[bytes]:
        """Placeholder streaming TTS: yield nothing for Phase A.

        In Phase C, this will synthesize and stream ulaw/PCM frames.
        """
        if not text:
            return
        # Intentionally left as a stub for now
        if False:
            yield b""  # pragma: no cover


