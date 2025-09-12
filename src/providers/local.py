import asyncio
import json
import logging
import os
import audioop
import wave
import io
import numpy as np
from typing import Callable, Dict, Any, List, Optional

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

try:
    import webrtcvad
except ImportError:
    webrtcvad = None

logger = logging.getLogger(__name__)

class LocalProvider(AIProviderInterface):
    """AI Provider for local models (Vosk, Llama, Piper)."""

    def __init__(self, config: LocalProviderConfig, on_provider_event: Callable):
        self.config = config
        self.on_provider_event = on_provider_event
        self.stt_model: Optional[VoskModel] = None
        self.llm_model: Optional[Llama] = None
        self.tts_model: Optional[TTS] = None
        self._models_loaded = False
        self.recognizers: Dict[str, KaldiRecognizer] = {}

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
        if not self.llm_model:
            model_path = _resolve_path(self.config.llm_model)
            logger.debug(f"Loading LLM model from: {model_path}")
            if not os.path.exists(model_path):
                logger.error(f"LLM model path does not exist: {model_path}")
                return
            self.llm_model = Llama(model_path=model_path, n_ctx=2048, verbose=False)

    def _initialize_tts(self):
        if self.tts_model is None:
            if TTS is None:
                logger.error("TTS library not installed. Please install it with 'pip install TTS'")
                return
            try:
                model_name = self.config.tts_voice
                logger.debug(f"Loading TTS model by name: {model_name}")
                self.tts_model = TTS(model_name=model_name)
                logger.info("TTS model loaded successfully.")
            except Exception as e:
                logger.error(f"Error loading TTS model: {e}")

    async def preload_models(self):
        """Load all models into memory."""
        if self._models_loaded:
            return
        logger.info("Pre-loading local models...")
        try:
            # Load STT model (Vosk)
            stt_model_path = self.config.stt_model_path
            if not os.path.exists(stt_model_path):
                raise FileNotFoundError(f"STT model not found at {stt_model_path}")
            self.stt_model = VoskModel(stt_model_path)
            logger.info("STT model loaded successfully.")

            # Load LLM model (Llama)
            llm_model_path = self.config.llm_model_path
            if not os.path.exists(llm_model_path):
                raise FileNotFoundError(f"LLM model not found at {llm_model_path}")
            self.llm_model = Llama(model_path=llm_model_path, n_ctx=2048)
            logger.info("LLM model loaded successfully.")

            # Load TTS model (Coqui TTS)
            self.tts_model = TTS(self.config.tts_model_name)
            logger.info("TTS model loaded successfully.")
            
            self._models_loaded = True
            logger.info("All local models pre-loaded.")
        except Exception as e:
            logger.error("Failed to preload local models", exc_info=True)
            self._models_loaded = False

    async def start_session(self, channel_id: str):
        """Start a new session for a channel."""
        logger.info("Starting new session", channel_id=channel_id)
        if not self._models_loaded or not self.stt_model:
            logger.error("Cannot start session, models not loaded.", channel_id=channel_id)
            return
        # Create a new recognizer for this channel
        self.recognizers[channel_id] = KaldiRecognizer(self.stt_model, 8000)
        
        # Start audio streaming
        await self.engine.ari_client.start_audio_streaming(
            channel_id, self.engine.config.asterisk.ari_app_name
        )
        self.engine.ari_client.set_audio_frame_handler(
            lambda audio_data: self.send_audio(channel_id, audio_data)
        )

    async def stop_session(self, channel_id: str):
        """Stop the session for a channel."""
        logger.info("Stopping session", channel_id=channel_id)
        self.recognizers.pop(channel_id, None)
        self.llm_model = None  # Release LLM model
        self.tts_model = None  # Release TTS model
        await self.engine.ari_client.stop_audio_streaming(channel_id)

    def is_ready(self) -> bool:
        """Check if all models are loaded and ready."""
        return (self.stt_model is not None and 
                self.recognizer is not None and 
                self.llm_model is not None and 
                self.tts_model is not None)

    async def send_audio(self, channel_id: str, audio_chunk: bytes):
        """Process an incoming audio chunk."""
        if not self._models_loaded:
            logger.warning("send_audio called before models were loaded. Ignoring.", channel_id=channel_id)
            return
        
        recognizer = self.recognizers.get(channel_id)
        if not recognizer:
            logger.warning("No recognizer found for channel", channel_id=channel_id)
            return

        # Process audio with Vosk
        if recognizer.AcceptWaveform(audio_chunk):
            result = json.loads(recognizer.Result())
            transcript = result.get("text", "")
            if transcript:
                logger.info("Transcription result", transcript=transcript, channel_id=channel_id)
                await self.on_provider_event(channel_id, {"type": "UserSaid", "text": transcript})
                # Get LLM response and speak it
                llm_response = await self.get_llm_response(transcript)
                await self.speak(channel_id, llm_response)
        else:
            partial_result = json.loads(recognizer.PartialResult())
            if partial_result.get("partial"):
                logger.debug("Partial transcription", partial=partial_result["partial"], channel_id=channel_id)


    async def transcribe_and_respond(self, channel_id: str):
        """Transcribe buffered audio, get LLM response, and speak it."""
        try:
            recognizer = KaldiRecognizer(self.stt_model, 8000)
            if recognizer.AcceptWaveform(bytes(self.audio_buffer)):
                result = json.loads(recognizer.Result())
                transcript = result.get("text", "")
                if transcript:
                    logger.info("Transcription result", transcript=transcript)
                    # Get LLM response
                    llm_response = await self.get_llm_response(transcript)
                    # Speak the response
                    await self.speak(channel_id, llm_response)
            self.audio_buffer.clear()
        except Exception as e:
            logger.error("Error during transcription and response", exc_info=True)
            self.audio_buffer.clear()

    async def get_llm_response(self, text: str) -> str:
        """Get a response from the LLM."""
        if not self.llm_model:
            logger.error("LLM model not loaded.")
            return "I am unable to respond right now."
        try:
            response = self.llm_model.create_chat_completion(
                messages=[
                    {"role": "system", "content": self.config.llm_system_prompt},
                    {"role": "user", "content": text},
                ]
            )
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error("Error getting LLM response", exc_info=True)
            return "I'm sorry, I had a problem processing that."

    async def speak(self, channel_id: str, text: str):
        """Synthesize text to speech and send it back to the engine."""
        if not self._models_loaded or not self.tts_model:
            logger.warning("Speak called before models were loaded. Ignoring.", channel_id=channel_id)
            return

        try:
            logger.info("Synthesizing TTS for text", text=text, channel_id=channel_id)
            # Synthesize audio to a WAV byte string
            wav_bytes = self.tts_model.tts(text=text) # This returns a list of audio samples
            
            # Convert to numpy array and then to bytes
            wav_np = np.array(wav_bytes, dtype=np.int16)
            
            # Resample from TTS sample rate (e.g., 22050) to Asterisk sample rate (8000)
            resampled_audio = audioop.ratecv(wav_np.tobytes(), 2, 1, self.tts_model.synthesizer.output_sample_rate, 8000, None)[0]

            # Convert from 16-bit linear PCM to 8-bit u-law
            ulaw_audio = audioop.lin2ulaw(resampled_audio, 2)

            if ulaw_audio:
                await self.on_provider_event(channel_id, {"type": "ProviderSaid", "data": ulaw_audio})
            else:
                logger.error("TTS synthesis returned no data.", channel_id=channel_id)
        except Exception as e:
            logger.error("Error during TTS synthesis", exc_info=True, channel_id=channel_id)

    async def play_initial_greeting(self, channel_id: str):
        """Play the initial greeting message."""
        if self.config.greeting:
            logger.info("Playing initial greeting", greeting=self.config.greeting, channel_id=channel_id)
            await self.speak(channel_id, self.config.greeting)
        else:
            logger.warning("No greeting configured.", channel_id=channel_id)

def _resolve_path(path: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.join(_PROJ_DIR, path)
