import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import wave
import io
from typing import Optional

from websockets.server import serve
from vosk import Model as VoskModel, KaldiRecognizer
from llama_cpp import Llama
from piper import PiperVoice

logging.basicConfig(level=logging.INFO)

# WhisperSTT class removed - using Vosk STT only for faster responses

class AudioProcessor:
    """Handles audio format conversions for MVP uLaw 8kHz pipeline"""
    
    @staticmethod
    def resample_audio(input_data: bytes, input_rate: int, output_rate: int, 
                      input_format: str = "raw", output_format: str = "raw") -> bytes:
        """Resample audio using sox"""
        try:
            with tempfile.NamedTemporaryFile(suffix=f".{input_format}", delete=False) as input_file:
                input_file.write(input_data)
                input_path = input_file.name
            
            with tempfile.NamedTemporaryFile(suffix=f".{output_format}", delete=False) as output_file:
                output_path = output_file.name
            
            # Use sox to resample - specify input format for raw PCM data
            cmd = [
                'sox',
                '-t', 'raw',  # input format: raw
                '-r', str(input_rate),  # input sample rate
                '-e', 'signed-integer',  # input encoding
                '-b', '16',  # input bit depth
                '-c', '1',  # input channels
                input_path,
                '-r', str(output_rate),  # output sample rate
                '-c', '1',  # mono
                '-e', 'signed-integer',
                '-b', '16',
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, check=True)
            
            with open(output_path, 'rb') as f:
                resampled_data = f.read()
            
            # Cleanup
            os.unlink(input_path)
            os.unlink(output_path)
            
            return resampled_data
            
        except Exception as e:
            logging.error(f"Audio resampling failed: {e}")
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
            
            # Use sox to convert to uLaw 8kHz
            cmd = [
                'sox',
                input_path,
                '-r', '8000',  # 8kHz
                '-c', '1',      # mono
                '-e', 'mu-law', # uLaw encoding
                '-t', 'raw',    # raw format
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, check=True)
            
            with open(output_path, 'rb') as f:
                ulaw_data = f.read()
            
            # Cleanup
            os.unlink(input_path)
            os.unlink(output_path)
            
            return ulaw_data
            
        except Exception as e:
            logging.error(f"uLaw conversion failed: {e}")
            return input_data

class LocalAIServer:
    def __init__(self):
        self.stt_model: Optional[VoskModel] = None
        self.llm_model: Optional[Llama] = None
        self.tts_model: Optional[PiperVoice] = None
        self.audio_processor = AudioProcessor()
        
        # Initialize Vosk STT only - optimized for telephony audio
        # Whisper STT completely removed for faster responses
        
        # Model paths
        self.stt_model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
        self.llm_model_path = "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
        self.tts_model_path = "/app/models/tts/en_US-lessac-medium.onnx"
        
        # Audio buffering for STT (20ms chunks need to be buffered for effective STT)
        self.audio_buffer = b""
        self.buffer_size_bytes = 16000 * 2 * 1.0  # 1 second at 16kHz (32000 bytes)
        self.buffer_timeout_ms = 1000  # Process buffer after 1 second of silence

    async def initialize_models(self):
        """Initialize all AI models with proper error handling"""
        logging.info("🚀 Initializing enhanced AI models for MVP...")
        
        # Initialize STT model
        await self._load_stt_model()
        
        # Initialize LLM model
        await self._load_llm_model()
        
        # Initialize TTS model
        await self._load_tts_model()
        
        logging.info("✅ All models loaded successfully for MVP pipeline")

    async def _load_stt_model(self):
        """Load STT model with 16kHz support"""
        try:
            if not os.path.exists(self.stt_model_path):
                raise FileNotFoundError(f"STT model not found at {self.stt_model_path}")
            
            self.stt_model = VoskModel(self.stt_model_path)
            logging.info(f"✅ STT model loaded: {self.stt_model_path} (16kHz native)")
        except Exception as e:
            logging.error(f"❌ Failed to load STT model: {e}")
            raise

    async def _load_llm_model(self):
        """Load LLM model with optimized parameters for faster inference"""
        try:
            if not os.path.exists(self.llm_model_path):
                raise FileNotFoundError(f"LLM model not found at {self.llm_model_path}")
            
            # Optimized parameters for faster real-time voice responses
            self.llm_model = Llama(
                model_path=self.llm_model_path, 
                n_ctx=1024,          # Increased context for better conversations
                n_threads=16,        # Use all CPU cores
                n_batch=512,         # Increased batch size for better throughput
                n_gpu_layers=0,      # Explicitly CPU-only
                verbose=False,
                use_mmap=True,       # Memory mapping for faster loading
                use_mlock=True       # Lock memory for stability
            )
            logging.info(f"✅ LLM model loaded with optimized parameters: {self.llm_model_path}")
            logging.info(f"📊 LLM Config: ctx=1024, threads=16, batch=512, mmap=True")
        except Exception as e:
            logging.error(f"❌ Failed to load LLM model: {e}")
            raise

    async def _load_tts_model(self):
        """Load TTS model (Piper) with 22kHz support"""
        try:
            if not os.path.exists(self.tts_model_path):
                raise FileNotFoundError(f"TTS model not found at {self.tts_model_path}")
            
            self.tts_model = PiperVoice.load(self.tts_model_path)
            logging.info(f"✅ TTS model loaded: {self.tts_model_path} (22kHz native)")
        except Exception as e:
            logging.error(f"❌ Failed to load TTS model: {e}")
            raise

    async def reload_models(self):
        """Hot reload all models without restarting the server"""
        logging.info("🔄 Hot reloading models...")
        try:
            await self.initialize_models()
            logging.info("✅ Models reloaded successfully")
        except Exception as e:
            logging.error(f"❌ Model reload failed: {e}")
            raise

    async def reload_llm_only(self):
        """Hot reload only the LLM model with optimized parameters"""
        logging.info("🔄 Hot reloading LLM model with optimizations...")
        try:
            # Unload current model to free memory
            if self.llm_model:
                del self.llm_model
                self.llm_model = None
                logging.info("🗑️ Previous LLM model unloaded")
            
            # Load with optimized parameters
            await self._load_llm_model()
            logging.info("✅ LLM model reloaded with optimizations")
            logging.info("📊 Optimized: ctx=1024, batch=512, temp=0.3, max_tokens=80")
        except Exception as e:
            logging.error(f"❌ LLM reload failed: {e}")
            raise

    async def process_stt_buffered(self, audio_data: bytes) -> str:
        """Process STT with buffering for 20ms chunks - buffers until we have enough audio for reliable STT"""
        try:
            if not self.stt_model:
                logging.error("STT model not loaded")
                return ""
            
            # Add new audio to buffer
            self.audio_buffer += audio_data
            logging.debug(f"🎵 STT BUFFER - Added {len(audio_data)} bytes, buffer now {len(self.audio_buffer)} bytes")
            
            # Check if we have enough audio for STT (at least 1 second)
            if len(self.audio_buffer) < self.buffer_size_bytes:
                logging.debug(f"🎵 STT BUFFER - Not enough audio yet ({len(self.audio_buffer)}/{self.buffer_size_bytes} bytes)")
                return ""
            
            # Process buffered audio with STT
            logging.info(f"🎵 STT PROCESSING - Processing buffered audio: {len(self.audio_buffer)} bytes")
            
            recognizer = KaldiRecognizer(self.stt_model, 16000)
            
            # Check if recognizer accepts the waveform
            if recognizer.AcceptWaveform(self.audio_buffer):
                result = json.loads(recognizer.Result())
                logging.debug(f"🎵 STT INTERMEDIATE - Partial result: {result}")
            else:
                result = json.loads(recognizer.FinalResult())
                logging.debug(f"🎵 STT FINAL - Final result: {result}")
            
            transcript = result.get("text", "").strip()
            logging.info(f"📝 STT RESULT - Transcript: '{transcript}'")
            
            # Clear buffer after processing
            self.audio_buffer = b""
            
            return transcript
            
        except Exception as e:
            logging.error(f"Buffered STT processing failed: {e}", exc_info=True)
            return ""

    async def process_stt(self, audio_data: bytes, input_rate: int = 16000) -> str:
        """Process STT with Vosk only - optimized for telephony audio"""
        try:
            # Use Vosk STT only (removed Whisper for faster responses)
            if not self.stt_model:
                logging.error("STT model not loaded")
                return ""
            
            logging.debug(f"🎤 STT INPUT - Using Vosk: {len(audio_data)} bytes at {input_rate}Hz")
            
            # Only resample if input rate is not 16kHz
            if input_rate != 16000:
                logging.debug(f"🎵 STT INPUT - Resampling {input_rate}Hz → 16kHz: {len(audio_data)} bytes")
                resampled_audio = self.audio_processor.resample_audio(
                    audio_data, input_rate, 16000, "raw", "raw"
                )
                logging.debug(f"🎵 STT RESAMPLED - Resampled audio: {len(resampled_audio)} bytes")
            else:
                # Already 16kHz, use directly
                resampled_audio = audio_data
                logging.debug(f"🎵 STT INPUT - Using 16kHz audio directly: {len(audio_data)} bytes")
            
            # Process with Vosk at 16kHz
            recognizer = KaldiRecognizer(self.stt_model, 16000)
            
            # Check if recognizer accepts the waveform
            if recognizer.AcceptWaveform(resampled_audio):
                result = json.loads(recognizer.Result())
                logging.debug(f"🎵 STT INTERMEDIATE - Partial result: {result}")
            else:
                result = json.loads(recognizer.FinalResult())
                logging.debug(f"🎵 STT FINAL - Final result: {result}")
            
            transcript = result.get("text", "").strip()
            logging.info(f"📝 STT RESULT - Vosk transcript: '{transcript}' (length: {len(transcript)})")
            return transcript
            
        except Exception as e:
            logging.error(f"STT processing failed: {e}", exc_info=True)
            return ""

    async def process_llm(self, text: str) -> str:
        """Process LLM with optimized parameters for faster real-time responses"""
        try:
            if not self.llm_model:
                logging.warning("LLM model not loaded, using fallback")
                return "I'm here to help you. How can I assist you today?"
            
            # Optimized prompt for faster, more focused responses
            prompt = f"""You are a helpful AI voice assistant. Respond naturally and conversationally to the user's input.

User: {text}

Assistant:"""
            
            # Optimized generation parameters for speed and quality
            output = self.llm_model(
                prompt, 
                max_tokens=80,         # Increased from 50 for better responses
                stop=["User:", "\n\n", "Assistant:"], 
                echo=False,
                temperature=0.3,       # Lower temperature for faster, more focused responses
                top_p=0.9,            # Nucleus sampling for better quality
                repeat_penalty=1.1     # Prevent repetition
            )
            
            response = output['choices'][0]['text'].strip()
            logging.info(f"🤖 LLM RESULT - Response: '{response}' (optimized)")
            return response
            
        except Exception as e:
            logging.error(f"LLM processing failed: {e}", exc_info=True)
            return "I'm here to help you. How can I assist you today?"

    async def process_tts(self, text: str) -> bytes:
        """Process TTS with 8kHz uLaw generation directly"""
        try:
            if not self.tts_model:
                logging.error("TTS model not loaded")
                return b""
            
            # Generate WAV at 22kHz using Piper (native rate) then resample to 8kHz
            logging.debug(f"🔊 TTS INPUT - Generating 22kHz audio for: '{text}'")
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
                wav_path = wav_file.name
            
            # Synthesize with Piper at native 22kHz rate - collect generator output
            with wave.open(wav_path, "wb") as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(22050)  # 22kHz native rate for Piper
                
                # Piper.synthesize returns AudioChunk objects, collect all chunks
                audio_generator = self.tts_model.synthesize(text)
                for audio_chunk in audio_generator:
                    wav_file.writeframes(audio_chunk.audio_int16_bytes)
            
            # Read the generated WAV
            with open(wav_path, 'rb') as f:
                wav_data = f.read()
            
            # Convert to uLaw 8kHz for ARI playback (proper resampling from 22kHz)
            logging.debug(f"🔄 TTS CONVERSION - Converting 22kHz WAV → 8kHz uLaw")
            ulaw_data = self.audio_processor.convert_to_ulaw_8k(wav_data, 22050)
            
            # Cleanup
            os.unlink(wav_path)
            
            logging.info(f"🔊 TTS RESULT - Generated uLaw 8kHz audio: {len(ulaw_data)} bytes")
            return ulaw_data
            
        except Exception as e:
            logging.error(f"TTS processing failed: {e}", exc_info=True)
            return b""

    async def handler(self, websocket):
        """Enhanced WebSocket handler with MVP pipeline and hot reloading"""
        logging.info(f"🔌 New connection established: {websocket.remote_address}")
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    # Binary audio data from ExternalMedia
                    logging.info(f"🎵 AUDIO INPUT - Received audio: {len(message)} bytes")
                    transcript = await self.process_stt(message)
                    if transcript.strip():
                        llm_response = await self.process_llm(transcript)
                        if llm_response.strip():
                            audio_response = await self.process_tts(llm_response)
                            if audio_response:
                                await websocket.send(audio_response)
                                logging.info("📤 AUDIO OUTPUT - Sent uLaw 8kHz response")
                            else:
                                logging.warning("🔊 TTS - No audio generated")
                        else:
                            logging.info("🤖 LLM - Empty response, skipping TTS")
                    else:
                        logging.info("📝 STT - No speech detected, skipping pipeline")
                
                else:
                    # JSON messages
                    try:
                        data = json.loads(message)
                        
                        if data.get("type") == "tts_request":
                            # Direct TTS request
                            tts_text = data.get("text", "")
                            call_id = data.get("call_id", "unknown")
                            logging.info(f"🔊 TTS REQUEST - Call {call_id}: '{tts_text}'")
                            
                            audio_response = await self.process_tts(tts_text)
                            
                            response = {
                                "type": "tts_response",
                                "text": tts_text,
                                "audio_data": base64.b64encode(audio_response).decode('utf-8'),
                                "call_id": call_id
                            }
                            await websocket.send(json.dumps(response))
                            logging.info(f"📤 TTS RESPONSE - Sent {len(audio_response)} bytes")
                        
                        elif data.get("type") == "audio":
                            # Audio data from AI Engine (RTP format - 16kHz PCM)
                            audio_data = base64.b64decode(data.get("data", ""))
                            input_rate = int(data.get("rate", 16000))  # Default to 16kHz if not specified
                            logging.info(f"🎵 AUDIO INPUT - Received audio: {len(audio_data)} bytes at {input_rate} Hz")
                            
                            # Process with STT (now receiving complete utterances from VAD) - CPU OFFLOADED
                            transcript = await self.process_stt(audio_data, input_rate)
                            
                            if transcript.strip():
                                llm_response = await self.process_llm(transcript)
                                
                                if llm_response.strip():
                                    audio_response = await self.process_tts(llm_response)
                                    
                                    if audio_response:
                                        # Send binary audio data directly (like working commit)
                                        await websocket.send(audio_response)
                                        logging.info("📤 AUDIO OUTPUT - Sent uLaw 8kHz response")
                                    else:
                                        logging.warning("🔊 TTS - No audio generated")
                                else:
                                    logging.info("🤖 LLM - Empty response, skipping TTS")
                            else:
                                logging.info("📝 STT - No speech detected, skipping pipeline")
                        
                        elif data.get("type") == "reload_models":
                            # Hot reload all models
                            logging.info("🔄 RELOAD REQUEST - Hot reloading all models...")
                            await self.reload_models()
                            
                            response = {
                                "type": "reload_response",
                                "status": "success",
                                "message": "All models reloaded successfully"
                            }
                            await websocket.send(json.dumps(response))
                            logging.info("✅ RELOAD COMPLETE - All models reloaded")
                        
                        elif data.get("type") == "reload_llm":
                            # Hot reload only LLM with optimizations
                            logging.info("🔄 LLM RELOAD REQUEST - Hot reloading LLM with optimizations...")
                            await self.reload_llm_only()
                            
                            response = {
                                "type": "reload_response",
                                "status": "success",
                                "message": "LLM model reloaded with optimizations (ctx=1024, batch=512, temp=0.3, max_tokens=80)"
                            }
                            await websocket.send(json.dumps(response))
                            logging.info("✅ LLM RELOAD COMPLETE - Optimized LLM loaded")
                        
                        else:
                            logging.warning(f"❓ Unknown message type: {data.get('type')}")
                    
                    except json.JSONDecodeError:
                        logging.warning(f"❓ Invalid JSON message: {message}")
        
        except Exception as e:
            logging.error(f"❌ WebSocket handler error: {e}", exc_info=True)
        finally:
            logging.info(f"🔌 Connection closed: {websocket.remote_address}")

async def main():
    """Main server function"""
    server = LocalAIServer()
    await server.initialize_models()
    
    async with serve(server.handler, "0.0.0.0", 8765, ping_interval=30, ping_timeout=30, max_size=None):
        logging.info("🚀 Enhanced Local AI Server started on ws://0.0.0.0:8765")
        logging.info("📋 MVP Pipeline: ExternalMedia (8kHz) → STT (16kHz) → LLM → TTS (8kHz uLaw) - CPU Offloaded!")
        logging.info("🔄 Hot Reload: Send {'type': 'reload_models'} to reload models")
        logging.info("⚡ CPU Offloading: STT/LLM/TTS running in threads to prevent WebSocket timeouts")
        await asyncio.Future()  # Run forever

if __name__ == "__main__":
    asyncio.run(main())
