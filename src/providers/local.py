import asyncio
import json
import logging
import os
import audioop
import wave
import io
import numpy as np
from typing import Callable, Dict, Any, List

from ..config import load_config, _PROJ_DIR, LocalProviderConfig
from .base import AIProviderInterface

try:
    from vosk import Model as VoskModel, KaldiRecognizer
except ImportError:
    VoskModel = None
    KaldiRecognizer = None

try:
    from llama_cpp import Llama
except ImportError:
    Llama = None

try:
    from TTS.api import TTS
except ImportError:
    TTS = None

logger = logging.getLogger(__name__)

class LocalProvider(AIProviderInterface):
    def __init__(self, config: LocalProviderConfig, on_event: Callable[[Dict[str, Any]], None]):
        super().__init__(on_event)
        self.config = config
        self.stt_model = None
        self.recognizer = None
        self.llm = None
        self.tts = None
        self.is_speaking = False
        logger.info("LocalProvider initialized with lazy-loading models.")

    @property
    def supported_codecs(self) -> List[str]:
        return ["ulaw"]

    def _initialize_stt(self):
        if not VoskModel or not KaldiRecognizer:
            logger.error("Vosk is not installed. Please install it with 'pip install vosk'")
            return
        if not self.stt_model:
            model_path = _resolve_path(self.config.stt_model)
            logger.debug(f"Loading STT model from: {model_path}")
            if not os.path.exists(model_path):
                logger.error(f"STT model path does not exist: {model_path}")
                return
            self.stt_model = VoskModel(model_path)
        self.recognizer = KaldiRecognizer(self.stt_model, 16000)

    def _initialize_llm(self):
        if not Llama:
            logger.error("llama-cpp-python is not installed. Please install it with 'pip install llama-cpp-python'")
            return
        if not self.llm:
            model_path = _resolve_path(self.config.llm_model)
            logger.debug(f"Loading LLM model from: {model_path}")
            if not os.path.exists(model_path):
                logger.error(f"LLM model path does not exist: {model_path}")
                return
            self.llm = Llama(model_path=model_path, n_ctx=2048, verbose=False)

    def _initialize_tts(self):
        if self.tts is None:
            if TTS is None:
                logger.error("TTS library not installed. Please install it with 'pip install TTS'")
                return
            try:
                model_name = self.config.tts_voice
                logger.debug(f"Loading TTS model by name: {model_name}")
                self.tts = TTS(model_name=model_name)
                logger.info("TTS model loaded successfully.")
            except Exception as e:
                logger.error(f"Error loading TTS model: {e}")

    async def start_session(self, initial_greeting: str, system_prompt: str):
        self._initialize_stt()
        self.system_prompt = system_prompt
        if initial_greeting:
            await self.speak(initial_greeting)

    async def stop_session(self):
        self.recognizer = None
        self.llm = None  # Release LLM model
        self.tts = None  # Release TTS model
        logger.info("LocalProvider session stopped and resources cleaned up")

    def is_ready(self) -> bool:
        """Check if all models are loaded and ready."""
        return (self.stt_model is not None and 
                self.recognizer is not None and 
                self.llm is not None and 
                self.tts is not None)

    async def send_audio(self, audio_chunk: bytes):
        if not self.recognizer:
            return

        pcm_audio = audioop.ulaw2lin(audio_chunk, 2)
        pcm_audio, _ = audioop.ratecv(pcm_audio, 2, 1, 8000, 16000, None)

        if self.recognizer.AcceptWaveform(pcm_audio):
            result = json.loads(self.recognizer.Result())
            if result.get("text"):
                logger.debug(f"STT transcription: {result['text']}")
                await self.on_event({"type": "Transcription", "text": result["text"]})
                await self._generate_llm_response(result["text"])

    async def _generate_llm_response(self, text: str):
        if not self.llm:
            self._initialize_llm()
        if not self.llm:
            logger.error("LLM not initialized, cannot generate response.")
            return

        logger.debug(f"Generating LLM response for: {text}")
        
        # Simple prompt structure
        full_prompt = f"{self.system_prompt}\n\nUser: {text}\nAssistant:"
        
        try:
            output = self.llm(
                full_prompt,
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                stop=["User:", "\n"],
                echo=False
            )
            response_text = output['choices'][0]['text'].strip()
            logger.debug(f"LLM response: {response_text}")
            await self.speak(response_text)
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")

    async def speak(self, text: str):
        if not self.tts:
            self._initialize_tts()
        if not self.tts:
            logger.error("TTS not initialized, cannot speak.")
            return
            
        self.is_speaking = True
        logger.debug(f"Speaking: {text}")
        await self._synthesize_tts_audio(text)
        self.is_speaking = False

    async def _synthesize_tts_audio(self, text: str):
        """Synthesize TTS audio using Coqui TTS."""
        try:
            # TTS.tts() returns a list of integers (waveform)
            wav_data = self.tts.tts(text=text, speaker=self.tts.speakers[0] if self.tts.is_multi_speaker else None, language=self.tts.languages[0] if self.tts.is_multi_lingual else None)
            
            # Convert list of ints to a numpy array of 16-bit integers
            pcm_data = np.array(wav_data, dtype=np.int16)
            
            # The TTS model outputs at its own sample rate (e.g., 22050Hz). We need to resample to 8000Hz for Asterisk.
            tts_sample_rate = self.tts.synthesizer.output_sample_rate
            pcm_data_resampled, _ = audioop.ratecv(pcm_data.tobytes(), 2, 1, tts_sample_rate, 8000, None)
            
            # Convert the 16-bit linear PCM back to 8-bit ulaw.
            ulaw_data = audioop.lin2ulaw(pcm_data_resampled, 2)
            
            logger.debug(f"Synthesized {len(ulaw_data)} bytes of ulaw audio.")

            chunk_size = 160  # 20ms at 8kHz
            for i in range(0, len(ulaw_data), chunk_size):
                chunk = ulaw_data[i:i + chunk_size]
                if chunk:
                    await self.on_event({"type": "AgentAudio", "data": chunk})
                    await asyncio.sleep(0.02)

        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            # Send silence as a fallback
            silence = b'\\x7f' * 160
            await self.on_event({"type": "AgentAudio", "data": silence})

def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(_PROJ_DIR, path)
