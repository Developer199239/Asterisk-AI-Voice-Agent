#!/usr/bin/env python3
"""
Test STT with speech-like audio patterns to see if it can detect them.
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

def generate_speech_like_audio(sample_rate=16000, duration=1.0):
    """Generate audio that mimics speech characteristics."""
    samples = []
    
    # Create a more complex audio pattern that might be detected as speech
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        
        # Mix multiple frequencies to create a more complex signal
        # This simulates the formants in human speech
        signal = (
            0.1 * math.sin(2 * math.pi * 200 * t) +  # Fundamental frequency
            0.05 * math.sin(2 * math.pi * 400 * t) +  # First harmonic
            0.03 * math.sin(2 * math.pi * 800 * t) +  # Second harmonic
            0.02 * math.sin(2 * math.pi * 1200 * t) + # Third harmonic
            0.01 * math.sin(2 * math.pi * 1600 * t)   # Fourth harmonic
        )
        
        # Add some amplitude modulation to simulate speech rhythm
        amplitude = 0.3 * (1 + 0.5 * math.sin(2 * math.pi * 3 * t))  # 3Hz modulation
        
        # Add some noise to make it more realistic
        noise = 0.01 * (math.random() - 0.5) if hasattr(math, 'random') else 0
        
        sample = int(32767 * amplitude * (signal + noise))
        samples.append(sample)
    
    return samples

def test_speech_like_audio():
    """Test STT with speech-like audio patterns."""
    
    # Load the STT model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    try:
        model = Model(model_path)
        print(f"✅ Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load model: {e}")
        return
    
    # Test with speech-like audio
    print("\n🎵 Testing with speech-like audio patterns...")
    
    sample_rate = 16000
    durations = [0.5, 1.0, 2.0, 3.0]  # Test different durations
    
    for duration in durations:
        print(f"\n--- Testing {duration}s of speech-like audio ---")
        
        # Generate speech-like audio
        samples = generate_speech_like_audio(sample_rate, duration)
        audio_data = struct.pack("<" + "h" * len(samples), *samples)
        
        print(f"Generated audio: {len(audio_data)} bytes")
        print(f"Sample range: {min(samples)} to {max(samples)}")
        
        # Test with STT
        recognizer = KaldiRecognizer(model, 16000)
        recognizer.AcceptWaveform(audio_data)
        result = json.loads(recognizer.FinalResult())
        transcript = result.get("text", "").strip()
        
        print(f"STT Result: '{transcript}'")
        
        if transcript:
            print("✅ SUCCESS: Speech detected!")
        else:
            print("❌ FAILED: No speech detected")
    
    # Test with actual speech file if available
    print("\n🎵 Testing with actual speech file...")
    speech_file = "/var/lib/asterisk/sounds/en/1-yes-2-no.sln16"
    if os.path.exists(speech_file):
        print(f"Found speech file: {speech_file}")
        
        with open(speech_file, 'rb') as f:
            raw_data = f.read()
        
        print(f"Raw file size: {len(raw_data)} bytes")
        
        # Convert from 8kHz to 16kHz
        import audioop
        pcm_8k = audioop.ulaw2lin(raw_data, 2)
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        
        print(f"Converted to 16kHz: {len(pcm_16k)} bytes")
        
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
    else:
        print("No speech file found for testing")

if __name__ == "__main__":
    test_speech_like_audio()
