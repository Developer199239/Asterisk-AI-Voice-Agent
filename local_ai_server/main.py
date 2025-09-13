import asyncio
import base64
import json
import logging
import os
from typing import Optional

from websockets.server import serve
from vosk import Model as VoskModel, KaldiRecognizer
from llama_cpp import Llama
from lightweight_tts import LightweightTTS

logging.basicConfig(level=logging.INFO)

class LocalAIServer:
    def __init__(self):
        self.stt_model: Optional[VoskModel] = None
        self.llm_model: Optional[Llama] = None
        self.tts_model: Optional[LightweightTTS] = None

    async def initialize_models(self):
        logging.info("Pre-loading AI models...")
        # These paths will be inside the container, mounted from the host
        stt_model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
        llm_model_path = "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
        
        if not os.path.exists(stt_model_path):
            raise FileNotFoundError(f"STT model not found at {stt_model_path}")
        if not os.path.exists(llm_model_path):
            raise FileNotFoundError(f"LLM model not found at {llm_model_path}")

        self.stt_model = VoskModel(stt_model_path)
        self.llm_model = Llama(model_path=llm_model_path, n_ctx=2048)
        self.tts_model = LightweightTTS()
        logging.info("All models loaded successfully")

    async def process_stt(self, audio_data: bytes) -> str:
        # Placeholder for STT processing
        recognizer = KaldiRecognizer(self.stt_model, 16000)
        recognizer.AcceptWaveform(audio_data)
        result = json.loads(recognizer.FinalResult())
        return result.get("text", "")

    async def process_llm(self, text: str) -> str:
        # Placeholder for LLM processing
        if self.llm_model:
            output = self.llm_model(f"Q: {text} A: ", max_tokens=150, stop=["Q:", "\n"], echo=False)
            return output['choices'][0]['text'].strip()
        return "I am a local AI assistant."

    async def process_tts(self, text: str) -> bytes:
        # Placeholder for TTS processing
        if self.tts_model:
            wav_bytes = self.tts_model.tts(text)
            return wav_bytes
        return b""

    async def handler(self, websocket):
        logging.info(f"New connection established: {websocket.remote_address}")
        try:
            async for message in websocket:
                data = json.loads(message)
                if data.get("type") == "audio":
                    audio_data = base64.b64decode(data["data"])
                    
                    # Full pipeline
                    transcript = await self.process_stt(audio_data)
                    logging.info(f"Transcript: {transcript}")
                    
                    llm_response = await self.process_llm(transcript)
                    logging.info(f"LLM Response: {llm_response}")
                    
                    audio_response = await self.process_tts(llm_response)
                    
                    # Send audio response as binary data
                    await websocket.send(audio_response)
                elif data.get("type") == "greeting":
                    # Handle greeting message - generate TTS for the greeting
                    greeting_text = data.get("message", "Hello! I'm your AI assistant. How can I help you today?")
                    call_id = data.get("call_id", "unknown")
                    logging.info(f"Processing greeting for call {call_id}: {greeting_text}")
                    
                    # Generate TTS audio for the greeting
                    audio_response = await self.process_tts(greeting_text)
                    
                    # Send the greeting audio back as binary data
                    await websocket.send(audio_response)
                    logging.info(f"Sent greeting audio for call {call_id}")
                else:
                    logging.warning(f"Unknown message type: {data.get('type')}")
        except Exception as e:
            logging.error(f"Error in WebSocket handler: {e}", exc_info=True)
        finally:
            logging.info(f"Connection closed: {websocket.remote_address}")

async def main():
    server = LocalAIServer()
    await server.initialize_models()
    async with serve(server.handler, "0.0.0.0", 8765):
        logging.info("Local AI Server started on ws://0.0.0.0:8765")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
