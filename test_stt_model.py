#!/usr/bin/env python3
"""
Test STT model with different configurations to identify the issue.
"""

import json
import base64
import struct
import math
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

def test_stt_model():
    """Test STT model with different configurations."""
    
    # Load model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    try:
        model = Model(model_path)
        print(f"✅ STT Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load STT model: {e}")
        return
    
    print("\n🧪 Testing STT Model Configurations")
    print("=" * 50)
    
    # Test 1: Simple sine wave
    print("\n1. Testing with sine wave (440Hz, 1 second):")
    sample_rate = 16000
    duration = 1.0
    frequency = 440
    
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        sample = int(32767 * 0.5 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"   Generated audio: {len(audio_data)} bytes")
    
    # Test with different sample rates
    for rate in [8000, 16000, 22050]:
        try:
            recognizer = KaldiRecognizer(model, rate)
            recognizer.AcceptWaveform(audio_data)
            result = json.loads(recognizer.FinalResult())
            transcript = result.get("text", "").strip()
            print(f"   Sample rate {rate}: '{transcript}'")
        except Exception as e:
            print(f"   Sample rate {rate}: ERROR - {e}")
    
    # Test 2: Silence
    print("\n2. Testing with silence:")
    silence = b"\x00" * 16000
    print(f"   Silence audio: {len(silence)} bytes")
    
    try:
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(silence)
        result = json.loads(recognizer.FinalResult())
        transcript = result.get("text", "").strip()
        print(f"   Silence result: '{transcript}'")
    except Exception as e:
        print(f"   Silence ERROR: {e}")
    
    # Test 3: Check model files
    print("\n3. Checking model files:")
    model_files = [
        "conf/mfcc.conf",
        "conf/model.conf", 
        "ivector/final.ie",
        "graph/HCLr.fst",
        "graph/Gr.fst",
        "graph/phones/word_boundary.int"
    ]
    
    for file_path in model_files:
        full_path = os.path.join(model_path, file_path)
        exists = os.path.exists(full_path)
        size = os.path.getsize(full_path) if exists else 0
        print(f"   {file_path}: {'✅' if exists else '❌'} ({size} bytes)")
    
    # Test 4: Try with actual speech-like patterns
    print("\n4. Testing with speech-like patterns:")
    
    # Generate more complex audio that mimics speech
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        
        # Create formant-like structure
        signal = (
            0.3 * math.sin(2 * math.pi * 200 * t) +   # F0
            0.2 * math.sin(2 * math.pi * 800 * t) +   # F1
            0.1 * math.sin(2 * math.pi * 1200 * t) +  # F2
            0.05 * math.sin(2 * math.pi * 2000 * t)   # F3
        )
        
        # Add amplitude modulation
        amplitude = 0.5 * (1 + 0.3 * math.sin(2 * math.pi * 2 * t))
        
        sample = int(32767 * amplitude * signal)
        samples.append(sample)
    
    speech_audio = struct.pack("<" + "h" * len(samples), *samples)
    print(f"   Speech-like audio: {len(speech_audio)} bytes")
    
    try:
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(speech_audio)
        result = json.loads(recognizer.FinalResult())
        transcript = result.get("text", "").strip()
        print(f"   Speech-like result: '{transcript}'")
        
        # Try partial result
        recognizer2 = KaldiRecognizer(model, 16000)
        recognizer2.AcceptWaveform(speech_audio)
        partial = recognizer2.PartialResult()
        print(f"   Partial result: {partial}")
        
    except Exception as e:
        print(f"   Speech-like ERROR: {e}")
    
    # Test 5: Check if model is working at all
    print("\n5. Testing model basic functionality:")
    try:
        recognizer = KaldiRecognizer(model, 16000)
        print(f"   Recognizer created: ✅")
        
        # Try with empty audio
        recognizer.AcceptWaveform(b"")
        result = json.loads(recognizer.FinalResult())
        print(f"   Empty audio result: '{result.get('text', '')}'")
        
        # Try with minimal audio
        minimal_audio = struct.pack("<hh", 1000, -1000)
        recognizer2 = KaldiRecognizer(model, 16000)
        recognizer2.AcceptWaveform(minimal_audio)
        result2 = json.loads(recognizer2.FinalResult())
        print(f"   Minimal audio result: '{result2.get('text', '')}'")
        
    except Exception as e:
        print(f"   Basic functionality ERROR: {e}")

if __name__ == "__main__":
    test_stt_model()
