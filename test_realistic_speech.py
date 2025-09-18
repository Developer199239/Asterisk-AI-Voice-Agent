#!/usr/bin/env python3
"""
Test STT with realistic speech patterns to understand why it's not detecting speech.
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

def test_realistic_speech():
    """Test STT with realistic speech patterns."""
    
    # Load model
    model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
    try:
        model = Model(model_path)
        print(f"✅ STT Model loaded from: {model_path}")
    except Exception as e:
        print(f"❌ Failed to load STT model: {e}")
        return
    
    print("\n🧪 Testing with Realistic Speech Patterns")
    print("=" * 50)
    
    sample_rate = 16000
    duration = 3.0  # 3 seconds
    
    # Generate audio that mimics human speech characteristics
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        
        # Create a more realistic speech pattern
        # Vary frequency over time (like speech)
        base_freq = 150 + 50 * math.sin(2 * math.pi * 0.5 * t)  # Varying fundamental
        
        # Add formants (speech resonances)
        signal = (
            0.4 * math.sin(2 * math.pi * base_freq * t) +           # F0
            0.3 * math.sin(2 * math.pi * (base_freq * 2) * t) +     # F0 harmonic
            0.2 * math.sin(2 * math.pi * 800 * t) +                 # F1
            0.15 * math.sin(2 * math.pi * 1200 * t) +               # F2
            0.1 * math.sin(2 * math.pi * 2000 * t)                  # F3
        )
        
        # Add speech-like amplitude modulation
        amplitude = 0.6 * (1 + 0.4 * math.sin(2 * math.pi * 3 * t))
        
        # Add some noise for realism
        noise = 0.05 * (math.random() - 0.5) if hasattr(math, "random") else 0
        
        sample = int(32767 * amplitude * (signal + noise))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated realistic speech: {len(audio_data)} bytes ({duration}s)")
    
    # Analyze the audio
    rms_energy = math.sqrt(sum(s*s for s in samples) / len(samples))
    max_amplitude = max(abs(s) for s in samples)
    print(f"Audio analysis: RMS={rms_energy:.2f}, Max={max_amplitude}")
    
    # Test 1: Full audio
    print("\n1. Testing with full 3-second audio:")
    recognizer = KaldiRecognizer(model, 16000)
    recognizer.AcceptWaveform(audio_data)
    result = json.loads(recognizer.FinalResult())
    transcript = result.get("text", "").strip()
    
    print(f"   Full audio result: '{transcript}'")
    print(f"   Result length: {len(transcript)}")
    
    # Test 2: Partial results
    print("\n2. Testing partial results:")
    recognizer2 = KaldiRecognizer(model, 16000)
    recognizer2.AcceptWaveform(audio_data)
    partial = recognizer2.PartialResult()
    print(f"   Partial result: {partial}")
    
    # Test 3: Chunked processing (like real-time)
    print("\n3. Testing with 20ms chunks (real-time simulation):")
    chunk_size = int(16000 * 2 * 0.02)  # 20ms at 16kHz
    chunk_count = 0
    
    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i + chunk_size]
        if len(chunk) > 0:
            chunk_count += 1
            recognizer3 = KaldiRecognizer(model, 16000)
            recognizer3.AcceptWaveform(chunk)
            result3 = json.loads(recognizer3.FinalResult())
            transcript3 = result3.get("text", "").strip()
            print(f"   Chunk {chunk_count}: {len(chunk)} bytes -> '{transcript3}'")
            
            if chunk_count >= 10:  # Test first 10 chunks
                break
    
    # Test 4: Try with different durations
    print("\n4. Testing with different durations:")
    durations = [0.5, 1.0, 2.0, 5.0]
    
    for dur in durations:
        # Generate shorter audio
        samples_short = []
        for i in range(int(sample_rate * dur)):
            t = i / sample_rate
            base_freq = 150 + 50 * math.sin(2 * math.pi * 0.5 * t)
            signal = 0.4 * math.sin(2 * math.pi * base_freq * t)
            amplitude = 0.6 * (1 + 0.4 * math.sin(2 * math.pi * 3 * t))
            sample = int(32767 * amplitude * signal)
            samples_short.append(sample)
        
        audio_short = struct.pack("<" + "h" * len(samples_short), *samples_short)
        
        recognizer4 = KaldiRecognizer(model, 16000)
        recognizer4.AcceptWaveform(audio_short)
        result4 = json.loads(recognizer4.FinalResult())
        transcript4 = result4.get("text", "").strip()
        
        print(f"   Duration {dur}s: '{transcript4}'")
    
    # Test 5: Check if model expects specific audio characteristics
    print("\n5. Testing model sensitivity:")
    
    # Test with very loud audio
    loud_samples = [int(s * 2) for s in samples[:16000]]  # First second, doubled
    loud_audio = struct.pack("<" + "h" * len(loud_samples), *loud_samples)
    
    recognizer5 = KaldiRecognizer(model, 16000)
    recognizer5.AcceptWaveform(loud_audio)
    result5 = json.loads(recognizer5.FinalResult())
    transcript5 = result5.get("text", "").strip()
    print(f"   Loud audio: '{transcript5}'")
    
    # Test with very quiet audio
    quiet_samples = [int(s * 0.1) for s in samples[:16000]]  # First second, 10% volume
    quiet_audio = struct.pack("<" + "h" * len(quiet_samples), *quiet_samples)
    
    recognizer6 = KaldiRecognizer(model, 16000)
    recognizer6.AcceptWaveform(quiet_audio)
    result6 = json.loads(recognizer6.FinalResult())
    transcript6 = result6.get("text", "").strip()
    print(f"   Quiet audio: '{transcript6}'")

if __name__ == "__main__":
    test_realistic_speech()
