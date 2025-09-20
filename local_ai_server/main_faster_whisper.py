#!/usr/bin/env python3
"""
Local AI Server with Faster-Whisper STT Support
Optimized for telephony audio with better accuracy than Vosk
"""

import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
import wave
import time
from typing import Optional, Dict, Any

from websockets.server import serve
from llama_cpp import Llama
from piper import PiperVoice

# Try to import Faster-Whisper, fallback to Vosk if not available
try:
    from faster_whisper import WhisperModel
    FASTER_WHISPER_AVAILABLE = True
    logging.info("✅ Faster-Whisper available")
except ImportError:
    FASTER_WHISPER_AVAILABLE = False
    from vosk import Model as VoskModel, KaldiRecognizer
    logging.warning("⚠️ Faster-Whisper not available, falling back to Vosk")

logging.basicConfig(level=logging.INFO)

class AudioProcessor:
    """Handles audio format conversions for telephony audio"""
    
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
            
            # Use sox to resample
            cmd = [
                'sox',
                '-t', 'raw',
                '-r', str(input_rate),
                '-e', 'signed-integer',
                '-b', '16',
                '-c', '1',
                input_path,
                '-r', str(output_rate),
                '-c', '1',
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
            logging.error(f"Error resampling audio: {e}")
            return input_data

class FasterWhisperSTT:
    """Faster-Whisper STT implementation optimized for telephony"""
    
    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.model = None
        self.model_loaded = False
        self.load_time = 0
        
        # Telephony-optimized settings
        self.sample_rate = 16000
        self.vad_filter = True
        self.vad_threshold = 0.35
        
        logging.info(f"🎤 Faster-Whisper STT initialized: {model_size} on {device}")
    
    async def load_model(self):
        """Load the Faster-Whisper model"""
        if self.model_loaded:
            return
        
        try:
            start_time = time.time()
            logging.info(f"🔄 Loading Faster-Whisper model: {self.model_size}")
            
            self.model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
                download_root="/app/models/stt/faster_whisper"
            )
            
            self.load_time = time.time() - start_time
            self.model_loaded = True
            
            logging.info(f"✅ Faster-Whisper model loaded in {self.load_time:.2f}s")
            
        except Exception as e:
            logging.error(f"❌ Failed to load Faster-Whisper model: {e}")
            raise
    
    async def process_stt(self, audio_data: bytes, input_rate: int = 16000) -> str:
        """Process STT with Faster-Whisper"""
        try:
            if not self.model_loaded:
                await self.load_model()
            
            # Convert audio bytes to numpy array
            audio_array = self._bytes_to_numpy(audio_data, input_rate)
            
            if len(audio_array) == 0:
                logging.warning("Empty audio data received")
                return ""
            
            # Log audio characteristics
            duration = len(audio_array) / self.sample_rate
            logging.info(f"🎵 STT INPUT - Processing audio: {len(audio_data)} bytes, {duration:.2f}s, {input_rate}Hz")
            
            # Transcribe with telephony optimizations
            start_time = time.time()
            
            segments, info = self.model.transcribe(
                audio_array,
                language="en",
                task="transcribe",
                vad_filter=self.vad_filter,
                vad_threshold=self.vad_threshold,
                word_timestamps=True,
                condition_on_previous_text=False,
                initial_prompt="This is a phone conversation. The speaker is saying hello and asking how someone is doing today."
            )
            
            # Collect all segments
            transcript_parts = []
            for segment in segments:
                transcript_parts.append(segment.text.strip())
            
            transcript = " ".join(transcript_parts).strip()
            
            processing_time = time.time() - start_time
            
            # Log results
            if transcript:
                logging.info(f"📝 STT RESULT - Transcript: '{transcript}' (length: {len(transcript)})")
                logging.info(f"⏱️ STT TIMING - Processed in {processing_time:.2f}s")
            else:
                logging.warning("📝 STT RESULT - No speech detected")
            
            return transcript
            
        except Exception as e:
            logging.error(f"❌ STT processing error: {e}", exc_info=True)
            return ""
    
    def _bytes_to_numpy(self, audio_data: bytes, sample_rate: int):
        """Convert audio bytes to numpy array for Faster-Whisper"""
        try:
            import numpy as np
            
            # Convert bytes to 16-bit signed integers
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # Normalize to float32 range [-1.0, 1.0]
            audio_array = audio_array.astype(np.float32) / 32768.0
            
            # Resample if needed
            if sample_rate != self.sample_rate:
                audio_array = self._resample_audio(audio_array, sample_rate, self.sample_rate)
            
            return audio_array
            
        except Exception as e:
            logging.error(f"Error converting audio bytes to numpy: {e}")
            return np.array([])
    
    def _resample_audio(self, audio, orig_sr: int, target_sr: int):
        """Simple resampling using numpy"""
        try:
            import numpy as np
            
            # Simple linear interpolation resampling
            ratio = target_sr / orig_sr
            new_length = int(len(audio) * ratio)
            
            # Create new indices
            old_indices = np.arange(len(audio))
            new_indices = np.linspace(0, len(audio) - 1, new_length)
            
            # Interpolate
            resampled = np.interp(new_indices, old_indices, audio)
            
            return resampled.astype(np.float32)
            
        except Exception as e:
            logging.error(f"Error resampling audio: {e}")
            return audio

class VoskSTT:
    """Vosk STT implementation (fallback)"""
    
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.model = None
        self.recognizer = None
        self.model_loaded = False
        
        logging.info(f"🎤 Vosk STT initialized: {model_path}")
    
    async def load_model(self):
        """Load the Vosk model"""
        if self.model_loaded:
            return
        
        try:
            logging.info(f"🔄 Loading Vosk model: {self.model_path}")
            
            self.model = VoskModel(self.model_path)
            self.recognizer = KaldiRecognizer(self.model, 16000)
            self.recognizer.SetWords(True)
            
            self.model_loaded = True
            logging.info("✅ Vosk model loaded successfully")
            
        except Exception as e:
            logging.error(f"❌ Failed to load Vosk model: {e}")
            raise
    
    async def process_stt(self, audio_data: bytes, input_rate: int = 16000) -> str:
        """Process STT with Vosk"""
        try:
            if not self.model_loaded:
                await self.load_model()
            
            # Resample if needed
            if input_rate != 16000:
                audio_data = AudioProcessor.resample_audio(audio_data, input_rate, 16000)
            
            # Process with Vosk
            if self.recognizer.AcceptWaveform(audio_data):
                result = json.loads(self.recognizer.Result())
                transcript = result.get('text', '').strip()
            else:
                # Partial result
                result = json.loads(self.recognizer.PartialResult())
                transcript = result.get('partial', '').strip()
            
            if transcript:
                logging.info(f"📝 STT RESULT - Transcript: '{transcript}' (length: {len(transcript)})")
            else:
                logging.warning("📝 STT RESULT - No speech detected")
            
            return transcript
            
        except Exception as e:
            logging.error(f"❌ STT processing error: {e}", exc_info=True)
            return ""

class LocalAIServer:
    """Local AI Server with Faster-Whisper STT support"""
    
    def __init__(self):
        self.audio_processor = AudioProcessor()
        self.stt_provider = None
        self.llm_model = None
        self.tts_voice = None
        self.models_loaded = False
        
        # Model paths
        self.llm_model_path = "/app/models/llm/llama-2-7b-chat.Q4_K_M.gguf"
        self.tts_model_path = "/app/models/tts/en_US-lessac-medium.onnx"
        self.vosk_model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
        
        # STT configuration
        self.stt_provider_type = os.getenv("STT_PROVIDER", "faster_whisper")  # faster_whisper or vosk
        self.faster_whisper_model = os.getenv("FASTER_WHISPER_MODEL", "base")  # tiny, base, small, medium, large
        
        logging.info(f"🤖 Local AI Server initialized with STT provider: {self.stt_provider_type}")
    
    async def load_models(self):
        """Load all AI models"""
        try:
            logging.info("🔄 Loading AI models...")
            
            # Load STT model
            if self.stt_provider_type == "faster_whisper" and FASTER_WHISPER_AVAILABLE:
                self.stt_provider = FasterWhisperSTT(
                    model_size=self.faster_whisper_model,
                    device="cpu",
                    compute_type="int8"
                )
                await self.stt_provider.load_model()
                logging.info("✅ Faster-Whisper STT loaded")
            else:
                # Fallback to Vosk
                self.stt_provider = VoskSTT(self.vosk_model_path)
                await self.stt_provider.load_model()
                logging.info("✅ Vosk STT loaded (fallback)")
            
            # Load LLM model
            logging.info("🔄 Loading LLM model...")
            self.llm_model = Llama(
                model_path=self.llm_model_path,
                n_ctx=2048,
                n_threads=4,
                verbose=False
            )
            logging.info("✅ LLM model loaded")
            
            # Load TTS model
            logging.info("🔄 Loading TTS model...")
            self.tts_voice = PiperVoice.load(self.tts_model_path)
            logging.info("✅ TTS model loaded")
            
            self.models_loaded = True
            logging.info("✅ All models loaded successfully")
            
        except Exception as e:
            logging.error(f"❌ Failed to load models: {e}")
            raise
    
    async def process_stt(self, audio_data: bytes, input_rate: int = 16000) -> str:
        """Process STT with the configured provider"""
        if not self.models_loaded:
            await self.load_models()
        
        return await self.stt_provider.process_stt(audio_data, input_rate)
    
    async def process_llm(self, transcript: str) -> str:
        """Process LLM response"""
        try:
            if not self.llm_model:
                return "I'm sorry, I'm having trouble processing your request."
            
            # Create prompt for telephony conversation
            prompt = f"""<s>[INST] You are a helpful AI assistant in a phone conversation. The caller said: "{transcript}"

Please respond naturally and helpfully, keeping your response concise and appropriate for a phone call. [/INST]"""
            
            # Generate response
            response = self.llm_model(
                prompt,
                max_tokens=150,
                temperature=0.7,
                top_p=0.9,
                stop=["</s>", "[INST]"]
            )
            
            llm_response = response['choices'][0]['text'].strip()
            
            if llm_response:
                logging.info(f"🤖 LLM RESULT - Response: '{llm_response}'")
            else:
                logging.warning("🤖 LLM RESULT - No response generated")
            
            return llm_response
            
        except Exception as e:
            logging.error(f"❌ LLM processing error: {e}")
            return "I'm sorry, I'm having trouble processing your request."
    
    async def process_tts(self, text: str) -> bytes:
        """Process TTS response"""
        try:
            if not self.tts_voice:
                return b""
            
            # Generate TTS audio
            audio_data = self.tts_voice.synthesize(text)
            
            if audio_data:
                logging.info(f"🔊 TTS RESULT - Generated audio: {len(audio_data)} bytes")
            else:
                logging.warning("🔊 TTS RESULT - No audio generated")
            
            return audio_data
            
        except Exception as e:
            logging.error(f"❌ TTS processing error: {e}")
            return b""
    
    async def handle_websocket(self, websocket, path):
        """Handle WebSocket connections"""
        try:
            logging.info(f"🔌 New WebSocket connection: {websocket.remote_address}")
            
            async for message in websocket:
                try:
                    data = json.loads(message)
                    
                    if data.get("type") == "audio":
                        # Audio data from AI Engine
                        audio_data = base64.b64decode(data.get("data", ""))
                        input_rate = int(data.get("rate", 16000))
                        
                        logging.info(f"🎵 AUDIO INPUT - Received audio: {len(audio_data)} bytes at {input_rate} Hz")
                        
                        # Process with STT
                        transcript = await self.process_stt(audio_data, input_rate)
                        
                        if transcript.strip():
                            # Process with LLM
                            llm_response = await self.process_llm(transcript)
                            
                            if llm_response.strip():
                                # Process with TTS
                                tts_audio = await self.process_tts(llm_response)
                                
                                if tts_audio:
                                    # Send TTS audio back
                                    await websocket.send(tts_audio)
                                    logging.info("📤 AUDIO OUTPUT - Sent TTS response")
                                else:
                                    logging.warning("📤 AUDIO OUTPUT - No TTS audio to send")
                            else:
                                logging.warning("🤖 LLM - No response generated")
                        else:
                            logging.warning("📝 STT - No transcript generated")
                    
                    elif data.get("type") == "text":
                        # Direct text input
                        text = data.get("text", "")
                        logging.info(f"📝 TEXT INPUT - Received text: '{text}'")
                        
                        # Process with LLM
                        llm_response = await self.process_llm(text)
                        
                        if llm_response.strip():
                            # Process with TTS
                            tts_audio = await self.process_tts(llm_response)
                            
                            if tts_audio:
                                # Send TTS audio back
                                await websocket.send(tts_audio)
                                logging.info("📤 AUDIO OUTPUT - Sent TTS response")
                            else:
                                logging.warning("📤 AUDIO OUTPUT - No TTS audio to send")
                        else:
                            logging.warning("🤖 LLM - No response generated")
                    
                    else:
                        logging.warning(f"Unknown message type: {data.get('type')}")
                
                except json.JSONDecodeError:
                    logging.error("Invalid JSON received")
                except Exception as e:
                    logging.error(f"Error processing message: {e}")
        
        except Exception as e:
            logging.error(f"WebSocket error: {e}")
        finally:
            logging.info(f"🔌 WebSocket connection closed: {websocket.remote_address}")

async def main():
    """Main server function"""
    logging.info("🚀 Starting Local AI Server with Faster-Whisper STT")
    
    # Create server instance
    server = LocalAIServer()
    
    # Load models
    await server.load_models()
    
    # Start WebSocket server
    port = int(os.getenv("PORT", 8765))
    logging.info(f"🌐 Starting WebSocket server on port {port}")
    
    async with serve(server.handle_websocket, "0.0.0.0", port):
        logging.info("✅ Local AI Server ready!")
        logging.info(f"📊 STT Provider: {server.stt_provider_type}")
        logging.info(f"🎤 STT Model: {server.faster_whisper_model if server.stt_provider_type == 'faster_whisper' else 'vosk'}")
        logging.info("🔄 Waiting for connections...")
        
        # Keep server running
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
