import json
import wave
import audioop
from vosk import Model, KaldiRecognizer
from llama_cpp import Llama
from piper import PiperVoice
from .base import AIProviderInterface
from typing import List, Optional
from ..config import LocalProviderConfig, LLMConfig

class LocalProvider(AIProviderInterface):
    """
    Local AI Provider.
    Orchestrates local STT, LLM, and TTS models.
    """
    def __init__(self, config: LocalProviderConfig, llm_config: LLMConfig):
        self.config = config
        self.llm_config = llm_config
        self._stt_model: Optional[Model] = None
        self._llm: Optional[Llama] = None
        self._tts_voice: Optional[PiperVoice] = None

    @property
    def stt_model(self) -> Model:
        if self._stt_model is None:
            self._stt_model = Model(self.config.stt_model)
        return self._stt_model

    @property
    def llm(self) -> Llama:
        if self._llm is None:
            self._llm = Llama(model_path=self.config.llm_model, n_ctx=2048)
        return self._llm

    @property
    def tts_voice(self) -> PiperVoice:
        if self._tts_voice is None:
            self._tts_voice = PiperVoice.load(self.config.tts_voice)
        return self._tts_voice

    @property
    def supported_codecs(self) -> List[str]:
        return ["ulaw", "slin16"]

    async def start_session(self, call_id: str, on_event: callable):
        self.recognizer = KaldiRecognizer(self.stt_model, 8000)
        self.on_event = on_event

    async def send_audio(self, audio_chunk: bytes):
        # Vosk expects 16-bit PCM, so we need to convert from ulaw
        pcm_audio, _ = audioop.ulaw2lin(audio_chunk, 2)
        if self.recognizer.AcceptWaveform(pcm_audio):
            result = json.loads(self.recognizer.Result())
            if result.get("text"):
                await self.on_event({"type": "Transcription", "text": result["text"]})
                # Once we have the text, we can send it to the LLM
                await self._generate_llm_response(result["text"])

    async def _generate_llm_response(self, text: str):
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
        if response and response['choices']:
            response_text = response['choices'][0]['message']['content']
            await self.on_event({"type": "LLMResponse", "text": response_text})
            # Once we have the LLM response, we can synthesize the audio
            await self._synthesize_tts_audio(response_text)

    async def _synthesize_tts_audio(self, text: str):
        # Synthesize audio from the text
        with wave.open("temp_tts.wav", "wb") as wav_file:
            self.tts_voice.synthesize(text, wav_file)
        
        # Read the audio data and convert it to ulaw
        with wave.open("temp_tts.wav", "rb") as wav_file:
            pcm_data = wav_file.readframes(wav_file.getnframes())
            ulaw_data = audioop.lin2ulaw(pcm_data, 2)
            await self.on_event({"type": "AgentAudio", "data": ulaw_data})

    async def stop_session(self):
        # To be implemented: clean up local models
        pass
