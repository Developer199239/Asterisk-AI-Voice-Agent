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
                    
                    # Process audio for STT
                    logging.info(f"🎵 STT INPUT - Received audio: {len(audio_data)} bytes")
                    
                    # Full pipeline
                    logging.info("🔄 STT PROCESSING - Starting...")
                    transcript = await self.process_stt(audio_data)
                    logging.info(f"📝 STT RESULT - Transcript: '{transcript}'")
                    
                    if transcript.strip():  # Only process if we have actual speech
                        logging.info("🔄 LLM PROCESSING - Starting...")
                        llm_response = await self.process_llm(transcript)
                        logging.info(f"🤖 LLM RESULT - Response: '{llm_response}'")
                        
                        if llm_response.strip():  # Only generate TTS if we have a response
                            logging.info("🔄 TTS PROCESSING - Starting...")
                            audio_response = await self.process_tts(llm_response)
                            logging.info(f"🔊 TTS RESULT - Generated audio: {len(audio_response)} bytes")
                            
                            # Send audio response as binary data
                            await websocket.send(audio_response)
                            logging.info("📤 TTS OUTPUT - Sent to client")
                        else:
                            logging.info("🤖 LLM - Empty response, skipping TTS")
                    else:
                        logging.info("📝 STT - No speech detected, skipping LLM/TTS")
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
                elif data.get("type") == "timeout_greeting":
                    # Handle timeout greeting message - generate TTS for "Are you still there?"
                    timeout_text = data.get("message", "Are you still there? I'm here and ready to help.")
                    call_id = data.get("call_id", "unknown")
                    logging.info(f"Processing timeout greeting for call {call_id}: {timeout_text}")
                    
                    # Generate TTS audio for the timeout greeting
                    audio_response = await self.process_tts(timeout_text)
                    
                    # Send the timeout greeting audio back as binary data
                    await websocket.send(audio_response)
                    logging.info(f"Sent timeout greeting audio for call {call_id}")
                elif data.get("type") == "tts_request":
                    # Handle direct TTS request - generate TTS for the given text
                    tts_text = data.get("text", "")
                    call_id = data.get("call_id", "unknown")
                    logging.info(f"Processing TTS request for call {call_id}: {tts_text}")
                    
                    # Generate TTS audio for the text
                    audio_response = await self.process_tts(tts_text)
                    
                    # Send TTS response as JSON with base64 encoded audio
                    response = {
                        "type": "tts_response",
                        "audio_data": base64.b64encode(audio_response).decode('utf-8'),
                        "call_id": call_id
                    }
                    await websocket.send(json.dumps(response))
                    logging.info(f"Sent TTS response for call {call_id}: {len(audio_response)} bytes")
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
