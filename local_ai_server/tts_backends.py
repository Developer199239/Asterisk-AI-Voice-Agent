from __future__ import annotations

import logging
import os
from typing import Optional


class KokoroTTSBackend:
    """Kokoro TTS backend using the kokoro package."""

    def __init__(
        self, voice: str = "af_heart", lang_code: str = "a", model_path: Optional[str] = None
    ):
        self.voice = voice
        self.lang_code = lang_code
        self.model_path = model_path
        self.pipeline = None
        self._initialized = False
        self.sample_rate = 24000

    def initialize(self) -> bool:
        try:
            from kokoro import KPipeline
            from kokoro.model import KModel

            logging.info(
                "🎙️ KOKORO - Initializing TTS (voice=%s, lang=%s)",
                self.voice,
                self.lang_code,
            )

            if self.model_path and os.path.isdir(self.model_path):
                config_path = os.path.join(self.model_path, "config.json")
                model_path = os.path.join(self.model_path, "kokoro-v1_0.pth")

                if os.path.exists(config_path) and os.path.exists(model_path):
                    logging.info(
                        "🎙️ KOKORO - Loading local model from %s", self.model_path
                    )
                    kmodel = KModel(
                        config=config_path,
                        model=model_path,
                        repo_id="hexgrad/Kokoro-82M",
                    )
                    self.pipeline = KPipeline(
                        lang_code=self.lang_code,
                        model=kmodel,
                        repo_id="hexgrad/Kokoro-82M",
                    )
                else:
                    logging.warning(
                        "⚠️ KOKORO - Local model files not found, falling back to HuggingFace"
                    )
                    self.pipeline = KPipeline(
                        lang_code=self.lang_code, repo_id="hexgrad/Kokoro-82M"
                    )
            else:
                logging.info(
                    "🎙️ KOKORO - Using HuggingFace model (will download if needed)"
                )
                self.pipeline = KPipeline(
                    lang_code=self.lang_code, repo_id="hexgrad/Kokoro-82M"
                )

            self._initialized = True
            logging.info("✅ KOKORO - TTS initialized successfully")
            return True
        except ImportError:
            logging.error("❌ KOKORO - kokoro package not installed")
            return False
        except Exception as exc:
            logging.error("❌ KOKORO - Failed to initialize: %s", exc)
            return False

    def synthesize(self, text: str) -> bytes:
        if not self._initialized or not self.pipeline:
            logging.error("❌ KOKORO - Not initialized")
            return b""

        try:
            import numpy as np

            audio_chunks = []
            generator = self.pipeline(text, voice=self.voice)

            for _, (_, _, audio) in enumerate(generator):
                if audio is not None:
                    audio_chunks.append(audio)

            if not audio_chunks:
                logging.warning("⚠️ KOKORO - No audio generated")
                return b""

            full_audio = np.concatenate(audio_chunks)
            audio_int16 = (full_audio * 32767).astype(np.int16)

            logging.debug(
                "🎙️ KOKORO - Generated %d samples at %dHz",
                len(audio_int16),
                self.sample_rate,
            )
            return audio_int16.tobytes()
        except Exception as exc:
            logging.error("❌ KOKORO - Synthesis failed: %s", exc)
            return b""

    def shutdown(self) -> None:
        self.pipeline = None
        self._initialized = False
        logging.info("🛑 KOKORO - TTS shutdown")

