#!/usr/bin/env python3
"""
Test STT with actual Asterisk speech files.
"""

import json
import base64
import struct
import audioop
import os
import sys

# Add the models directory to path
sys.path.append('/app/models/stt/vosk-model-small-en-us-0.15')

try:
    from vosk import Model, KaldiRecognizer
    print("✅ Vosk imported successfully")
except ImportError as e:
    print(f"❌ Failed to import Vosk: {e}")
    sys.exit(1)

def test_real_speech():
    """Test STT with actual Asterisk speech files."""
    
    # Load STT model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    try:
        model = Model(model_path)
        print(f"✅ Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return
    
    # Test with actual Asterisk speech file
    speech_file = "/var/lib/asterisk/sounds/en/1-yes-2-no.sln16"
    if os.path.exists(speech_file):
        print(f"\n🎵 Testing with actual speech file: {speech_file}")
        
        with open(speech_file, "rb") as f:
            raw_data = f.read()
        
        print(f"Raw file size: {len(raw_data)} bytes")
        
        # Convert from 8kHz µ-law to 16kHz PCM16
        pcm_8k = audioop.ulaw2lin(raw_data, 2)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        
        print(f"Converted to 16kHz: {len(pcm_16k)} bytes")
        print(f"Duration: {len(pcm_16k) / (16000 * 2):.3f} seconds")
        
        # Test with STT
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(pcm_16k)
        result = json.loads(recognizer.FinalResult())
        transcript = result.get("text", "").strip()
        
        print(f"STT Result: '{transcript}'")
        
        if transcript:
            print("✅ SUCCESS: Speech detected in actual file!")
        else:
            print("❌ FAILED: No speech detected in actual file")
            
            # Try with partial results
            recognizer = KaldiRecognizer(model, 16000)
            recognizer.AcceptWaveform(pcm_16k)
            partial = recognizer.PartialResult()
            print(f"Partial result: {partial}")
            
            # Try with different chunk sizes
            print("\n🔍 Testing with different chunk sizes...")
            chunk_sizes = [1600, 3200, 6400, 12800]  # 50ms, 100ms, 200ms, 400ms
            
            for chunk_size in chunk_sizes:
                if chunk_size <= len(pcm_16k):
                    chunk = pcm_16k[:chunk_size]
                    duration_ms = chunk_size / (16000 * 2) * 1000
                    
                    print(f"\nTesting {duration_ms:.1f}ms chunk ({chunk_size} bytes):")
                    
                    recognizer = KaldiRecognizer(model, 16000)
                    recognizer.AcceptWaveform(chunk)
                    result = json.loads(recognizer.FinalResult())
                    transcript = result.get("text", "").strip()
                    
                    if transcript:
                        print(f"  ✅ SUCCESS: '{transcript}'")
                    else:
                        print(f"  ❌ FAILED: No speech detected")
    else:
        print(f"❌ Speech file not found: {speech_file}")
        
        # List available speech files
        sounds_dir = "/var/lib/asterisk/sounds"
        if os.path.exists(sounds_dir):
            print(f"\nAvailable speech files in {sounds_dir}:")
            for root, dirs, files in os.walk(sounds_dir):
                for file in files:
                    if file.endswith('.sln16'):
                        full_path = os.path.join(root, file)
                        print(f"  {full_path}")

if __name__ == "__main__":
    test_real_speech()
