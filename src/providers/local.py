import json
import wave
import audioop
import os
import io
import asyncio
from vosk import Model, KaldiRecognizer
from llama_cpp import Llama
from piper import PiperVoice
from .base import AIProviderInterface
from typing import List, Optional, Dict, Any
from ..config import LocalProviderConfig, LLMConfig
from ..logging_config import get_logger

# Determine the absolute path to the project root from this file's location
_PROJ_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = get_logger(__name__)

class LocalProvider(AIProviderInterface):
    """
    Local AI Provider.
    Orchestrates local STT, LLM, and TTS models.
    """
    
    @property
    def supported_codecs(self) -> List[str]:
        """Returns a list of supported codec names, in order of preference."""
        return ["ulaw", "pcm"]
    
    def __init__(self, config: LocalProviderConfig, llm_config: LLMConfig):
        self.config = config
        self.llm_config = llm_config
        self.on_event: Optional[callable] = None
        self.recognizer: Optional[KaldiRecognizer] = None

        # Resolve model paths to be absolute
        self._stt_model_path = self._resolve_path(self.config.stt_model)
        self._llm_model_path = self._resolve_path(self.config.llm_model)
        self._tts_voice_path = self._resolve_path(self.config.tts_voice)

        # Lazy-loaded models
        self._stt_model: Optional[Model] = None
        self._llm: Optional[Llama] = None
        self._tts_voice: Optional[PiperVoice] = None
        logger.info("LocalProvider initialized with lazy-loading models.")

    def _resolve_path(self, path: str) -> str:
        """Resolves a path to be absolute, relative to the project root."""
        if not os.path.isabs(path):
            return os.path.join(_PROJ_DIR, path)
        return path

    @property
    def stt_model(self) -> Model:
        if self._stt_model is None:
            logger.debug(f"Loading STT model from: {self._stt_model_path}")
            self._stt_model = Model(self._stt_model_path)
        return self._stt_model

    @property
    def llm(self) -> Llama:
        if self._llm is None:
            logger.debug(f"Loading LLM model from: {self._llm_model_path}")
            self._llm = Llama(model_path=self._llm_model_path, n_ctx=2048, verbose=False)
        return self._llm

    @property
    def tts_voice(self) -> PiperVoice:
        if self._tts_voice is None:
            logger.debug(f"Loading TTS voice from: {self._tts_voice_path}")
            self._tts_voice = PiperVoice.load(self._tts_voice_path)
        return self._tts_voice

    async def start_session(self, call_id: str, on_event: callable):
        # Initialize Vosk recognizer for 16kHz since we upsample from 8kHz
        self.recognizer = KaldiRecognizer(self.stt_model, 16000)
        self.on_event = on_event

    async def send_audio(self, audio_chunk: bytes):
        """Process audio chunk for STT using Vosk."""
        try:
            if not self.recognizer:
                logger.warning("Recognizer not initialized, skipping audio processing")
                return
                
            # Vosk expects 16-bit PCM, so we need to convert from ulaw
            pcm_audio = audioop.ulaw2lin(audio_chunk, 2)
            
            # Vosk expects 16kHz, but ulaw from Asterisk is 8kHz, so upsample
            pcm_audio, _ = audioop.ratecv(pcm_audio, 2, 1, 8000, 16000, None)
            
            if self.recognizer.AcceptWaveform(pcm_audio):
                result = json.loads(self.recognizer.Result())
                if result.get("text"):
                    logger.debug(f"STT transcription: {result['text']}")
                    await self.on_event({"type": "Transcription", "text": result["text"]})
                    # Once we have the text, we can send it to the LLM
                    await self._generate_llm_response(result["text"])
        except Exception as e:
            logger.error(f"Error processing audio chunk: {e}")
            # Continue processing even if one chunk fails

    async def _generate_llm_response(self, text: str):
        """Generate LLM response using local Llama model."""
        try:
            logger.debug(f"Generating LLM response for: {text}")
            
            # Create a chat completion request
            response = self.llm.create_chat_completion(
                messages=[
                    {"role": "system", "content": self.llm_config.prompt},
                    {"role": "user", "content": text}
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens
            )
            
            # Extract the response text and send it as an event
            if response and response.get('choices'):
                response_text = response['choices'][0]['message']['content']
                logger.debug(f"LLM response: {response_text}")
                await self.on_event({"type": "LLMResponse", "text": response_text})
                # Once we have the LLM response, we can synthesize the audio
                await self._synthesize_tts_audio(response_text)
            else:
                logger.warning("No valid LLM response generated")
                await self.on_event({"type": "LLMResponse", "text": "I'm sorry, I didn't understand that."})
                
        except Exception as e:
            logger.error(f"Error generating LLM response: {e}")
            # Send a fallback response
            await self.on_event({"type": "LLMResponse", "text": "I'm having trouble processing that right now."})

    async def _synthesize_tts_audio(self, text: str):
        """Synthesize TTS audio using in-memory processing for better performance."""
        try:
            # Use in-memory buffer instead of temporary file
            wav_buffer = io.BytesIO()
            
            # Synthesize audio directly to buffer
            with wave.open(wav_buffer, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(22050)  # Piper default sample rate
                self.tts_voice.synthesize(text, wav_file)
            
            # Reset buffer position and read the audio data
            wav_buffer.seek(0)
            with wave.open(wav_buffer, "rb") as wav_file:
                pcm_data = wav_file.readframes(wav_file.getnframes())
                
                # Convert from 22050 Hz to 8000 Hz (telephony standard)
                # Simple downsampling - in production, use proper resampling
                downsample_factor = 22050 // 8000
                pcm_data = pcm_data[::downsample_factor]
                
                # Convert PCM to ulaw
                ulaw_data = audioop.lin2ulaw(pcm_data, 2)
                
                # Send audio in chunks for better streaming
                chunk_size = 160  # 20ms at 8kHz
                for i in range(0, len(ulaw_data), chunk_size):
                    chunk = ulaw_data[i:i + chunk_size]
                    if chunk:
                        await self.on_event({"type": "AgentAudio", "data": chunk})
                        await asyncio.sleep(0.02)  # 20ms delay between chunks
                        
        except Exception as e:
            logger.error(f"TTS synthesis error: {e}")
            # Send silence as fallback
            silence = b'\x7f' * 160  # ulaw silence
            await self.on_event({"type": "AgentAudio", "data": silence})

    async def speak(self, text: str):
        """Speak the given text using TTS."""
        try:
            logger.debug(f"Speaking: {text}")
            if not self.on_event:
                logger.warning("No event handler set, TTS audio will not be sent")
                return
            await self._synthesize_tts_audio(text)
        except Exception as e:
            logger.error(f"Error speaking text: {e}")

    async def stop_session(self):
        """Clean up resources and reset state."""
        try:
            if self.recognizer:
                self.recognizer = None
            logger.info("LocalProvider session stopped and resources cleaned up")
        except Exception as e:
            logger.error(f"Error during session cleanup: {e}")
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the provider and its capabilities."""
        return {
            "name": "LocalProvider",
            "type": "local",
            "supported_codecs": self.supported_codecs,
            "stt_model": self.config.stt_model,
            "llm_model": self.config.llm_model,
            "tts_voice": self.config.tts_voice,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens
        }
    
    def is_ready(self) -> bool:
        """Check if the provider is ready to process audio."""
        return self.recognizer is not None and self.on_event is not None
