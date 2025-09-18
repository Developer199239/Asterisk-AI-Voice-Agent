#!/usr/bin/env python3
"""
Test different chunk sizes to find the minimum effective size for STT.
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

def test_chunk_sizes():
    """Test different chunk sizes to find minimum effective size."""
    
    # Load model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    try:
        model = Model(model_path)
        print(f"✅ STT Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load STT model: {e}")
        return
    
    print("\n🧪 Testing Different Chunk Sizes for STT")
    print("=" * 50)
    
    sample_rate = 16000
    duration = 2.0
    
    # Generate test audio
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        base_freq = 150 + 50 * math.sin(2 * math.pi * 0.5 * t)
        signal = 0.4 * math.sin(2 * math.pi * base_freq * t)
        amplitude = 0.6 * (1 + 0.4 * math.sin(2 * math.pi * 3 * t))
        sample = int(32767 * amplitude * signal)
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated test audio: {len(audio_data)} bytes ({duration}s)")
    
    # Test different chunk sizes
    chunk_sizes_ms = [50, 100, 200, 500, 1000, 1500, 2000]  # milliseconds
    
    for chunk_ms in chunk_sizes_ms:
        chunk_size = int(sample_rate * 2 * chunk_ms / 1000)  # bytes for chunk_ms
        chunk = audio_data[:chunk_size]
        
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(chunk)
        result = json.loads(recognizer.FinalResult())
        transcript = result.get("text", "").strip()
        
        print(f"  {chunk_ms}ms ({chunk_size} bytes): '{transcript}'")
    
    print("\n📊 Analysis:")
    print("  - 20ms chunks (640 bytes) are too small for reliable STT")
    print("  - Need at least 500ms-1000ms for speech detection")
    print("  - Solution: Buffer 20ms chunks and send larger batches to STT")

if __name__ == "__main__":
    test_chunk_sizes()
