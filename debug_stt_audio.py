#!/usr/bin/env python3
"""
Comprehensive STT audio debugging script.
Analyzes the actual audio content being sent to STT to understand why speech detection fails.
"""

import asyncio
import websockets
import json
import base64
import struct
import math
import time
import sys
import os

# Add the models directory to path
sys.path.append('/app/models/stt/vosk-model-small-en-us-0.15')

try:
    from vosk import Model, KaldiRecognizer
    print("✅ Vosk imported successfully")
except ImportError as e:
    print(f"❌ Failed to import Vosk: {e}")
    sys.exit(1)

class STTAudioDebugger:
    def __init__(self):
        self.model = None
        self.audio_samples = []
        self.total_audio_bytes = 0
        
    def load_model(self):
        """Load the STT model."""
        model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
        try:
            self.model = Model(model_path)
            print(f"✅ STT Model loaded from: {model_path}")
            return True
        except Exception as e:
            print(f"❌ Failed to load STT model: {e}")
            return False
    
    def analyze_audio_content(self, audio_data):
        """Analyze the audio content for debugging."""
        if len(audio_data) == 0:
            return {"error": "Empty audio data"}
        
        # Convert bytes to samples for analysis
        samples = struct.unpack('<' + 'h' * (len(audio_data) // 2), audio_data)
        
        analysis = {
            "size_bytes": len(audio_data),
            "num_samples": len(samples),
            "duration_ms": len(samples) / 16000 * 1000,  # 16kHz sample rate
            "sample_range": (min(samples), max(samples)),
            "rms_energy": math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0,
            "zero_samples": sum(1 for s in samples if s == 0),
            "non_zero_samples": sum(1 for s in samples if s != 0),
            "max_amplitude": max(abs(s) for s in samples) if samples else 0,
            "first_10_samples": samples[:10] if len(samples) >= 10 else samples,
            "last_10_samples": samples[-10:] if len(samples) >= 10 else samples
        }
        
        # Calculate signal characteristics
        analysis["signal_present"] = analysis["rms_energy"] > 100  # Threshold for signal detection
        analysis["signal_quality"] = "good" if analysis["rms_energy"] > 1000 else "poor" if analysis["rms_energy"] > 100 else "silence"
        
        return analysis
    
    def test_stt_with_audio(self, audio_data):
        """Test STT with the provided audio data."""
        if not self.model:
            return {"error": "Model not loaded"}
        
        try:
            recognizer = KaldiRecognizer(self.model, 16000)
            recognizer.AcceptWaveform(audio_data)
            result = json.loads(recognizer.FinalResult())
            transcript = result.get("text", "").strip()
            
            # Also try partial result
            recognizer2 = KaldiRecognizer(self.model, 16000)
            recognizer2.AcceptWaveform(audio_data)
            partial = recognizer2.PartialResult()
            
            return {
                "transcript": transcript,
                "partial": partial,
                "has_speech": len(transcript) > 0,
                "transcript_length": len(transcript)
            }
        except Exception as e:
            return {"error": str(e)}
    
    def generate_test_audio(self, duration_ms=1000, frequency=440, amplitude=0.5):
        """Generate test audio for comparison."""
        sample_rate = 16000
        num_samples = int(sample_rate * duration_ms / 1000)
        
        samples = []
        for i in range(num_samples):
            t = i / sample_rate
            # Generate a more complex signal that should be detectable
            signal = (
                amplitude * 0.3 * math.sin(2 * math.pi * frequency * t) +
                amplitude * 0.2 * math.sin(2 * math.pi * frequency * 2 * t) +
                amplitude * 0.1 * math.sin(2 * math.pi * frequency * 3 * t)
            )
            sample = int(32767 * signal)
            samples.append(sample)
        
        return struct.pack('<' + 'h' * len(samples), *samples)
    
    async def monitor_live_audio(self):
        """Monitor live audio from the Local AI Server."""
        print("🔍 Monitoring live audio from Local AI Server...")
        print("📞 Make a test call now!")
        
        try:
            async with websockets.connect("ws://localhost:8765") as websocket:
                print("✅ Connected to Local AI Server")
                
                audio_count = 0
                total_audio = b""
                
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        
                        if data.get("type") == "audio":
                            audio_data = base64.b64decode(data.get("data", ""))
                            audio_count += 1
                            total_audio += audio_data
                            
                            print(f"\n--- Audio Chunk #{audio_count} ---")
                            
                            # Analyze this chunk
                            analysis = self.analyze_audio_content(audio_data)
                            print(f"Size: {analysis['size_bytes']} bytes")
                            print(f"Duration: {analysis['duration_ms']:.1f}ms")
                            print(f"Sample range: {analysis['sample_range']}")
                            print(f"RMS Energy: {analysis['rms_energy']:.2f}")
                            print(f"Signal quality: {analysis['signal_quality']}")
                            print(f"Non-zero samples: {analysis['non_zero_samples']}/{analysis['num_samples']}")
                            
                            # Test STT with this chunk
                            stt_result = self.test_stt_with_audio(audio_data)
                            print(f"STT Result: '{stt_result.get('transcript', 'ERROR')}'")
                            print(f"Has speech: {stt_result.get('has_speech', False)}")
                            
                            # If we have enough audio, test with accumulated audio
                            if len(total_audio) >= 3200:  # 200ms at 16kHz
                                print(f"\n--- Testing with accumulated audio ({len(total_audio)} bytes) ---")
                                accumulated_stt = self.test_stt_with_audio(total_audio)
                                print(f"Accumulated STT: '{accumulated_stt.get('transcript', 'ERROR')}'")
                                print(f"Accumulated has speech: {accumulated_stt.get('has_speech', False)}")
                            
                            # Stop after 20 chunks or if we get speech
                            if audio_count >= 20 or stt_result.get('has_speech', False):
                                break
                                
                    except json.JSONDecodeError:
                        continue
                    except Exception as e:
                        print(f"Error processing message: {e}")
                        continue
                
                print(f"\n📊 Summary:")
                print(f"Total audio chunks: {audio_count}")
                print(f"Total audio bytes: {len(total_audio)}")
                print(f"Total duration: {len(total_audio) / (16000 * 2) * 1000:.1f}ms")
                
        except Exception as e:
            print(f"❌ Error connecting to Local AI Server: {e}")
    
    def test_with_generated_audio(self):
        """Test STT with generated audio to verify it works."""
        print("🧪 Testing STT with generated audio...")
        
        # Generate test audio
        test_audio = self.generate_test_audio(duration_ms=1000, frequency=440, amplitude=0.3)
        print(f"Generated test audio: {len(test_audio)} bytes")
        
        # Analyze the generated audio
        analysis = self.analyze_audio_content(test_audio)
        print(f"Generated audio analysis: {analysis}")
        
        # Test STT with generated audio
        stt_result = self.test_stt_with_audio(test_audio)
        print(f"Generated audio STT result: {stt_result}")
        
        return stt_result.get('has_speech', False)

def main():
    debugger = STTAudioDebugger()
    
    if not debugger.load_model():
        return
    
    print("🔍 STT Audio Debugging Tool")
    print("=" * 50)
    
    # Test 1: Verify STT works with generated audio
    print("\n1. Testing STT with generated audio...")
    if debugger.test_with_generated_audio():
        print("✅ STT is working with generated audio")
    else:
        print("❌ STT is not working even with generated audio")
        return
    
    # Test 2: Monitor live audio
    print("\n2. Monitoring live audio from test call...")
    asyncio.run(debugger.monitor_live_audio())

if __name__ == "__main__":
    main()
