#!/usr/bin/env python3
"""
Debug STT model to understand why it's not detecting speech.
"""

import json
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
    """Test STT model with different audio configurations."""
    
    # Load the STT model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    if not os.path.exists(model_path):
        print(f"❌ Model path not found: {model_path}")
        return
    
    try:
        model = Model(model_path)
        print(f"✅ Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return
    
    # Test 1: Simple tone
    print("\n🎵 Test 1: Simple 440Hz tone (500ms)")
    sample_rate = 16000
    duration = 0.5
    frequency = 440
    
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        sample = int(32767 * 0.1 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated audio: {len(audio_data)} bytes")
    
    recognizer = KaldiRecognizer(model, 16000)
    recognizer.AcceptWaveform(audio_data)
    result = json.loads(recognizer.FinalResult())
    transcript = result.get("text", "").strip()
    print(f"STT Result: '{transcript}'")
    
    # Test 2: Longer duration
    print("\n🎵 Test 2: Simple 440Hz tone (2 seconds)")
    duration = 2.0
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        sample = int(32767 * 0.1 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated audio: {len(audio_data)} bytes")
    
    recognizer = KaldiRecognizer(model, 16000)
    recognizer.AcceptWaveform(audio_data)
    result = json.loads(recognizer.FinalResult())
    transcript = result.get("text", "").strip()
    print(f"STT Result: '{transcript}'")
    
    # Test 3: Check model configuration
    print("\n🔧 Test 3: Model configuration")
    conf_file = os.path.join(model_path, "conf", "mfcc.conf")
    if os.path.exists(conf_file):
        with open(conf_file, 'r') as f:
            print(f"MFCC Config:\n{f.read()}")
    
    # Test 4: Test with silence
    print("\n🎵 Test 4: Silence (should return empty)")
    samples = [0] * int(sample_rate * 0.5)  # 500ms of silence
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    
    recognizer = KaldiRecognizer(model, 16000)
    recognizer.AcceptWaveform(audio_data)
    result = json.loads(recognizer.FinalResult())
    transcript = result.get("text", "").strip()
    print(f"Silence STT Result: '{transcript}'")

if __name__ == "__main__":
    test_stt_model()
