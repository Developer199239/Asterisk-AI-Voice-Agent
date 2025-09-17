#!/usr/bin/env python3
import tempfile
import wave
import subprocess
import os
from piper import PiperVoice

print("Testing fixed Piper TTS...")
model_path = "/app/models/tts/en_US-lessac-medium.onnx"
try:
    voice = PiperVoice.load(model_path)
    print(f"✅ Piper voice loaded successfully")
    
    # Test synthesis with fixed API
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_file:
        wav_path = wav_file.name
    
    with wave.open(wav_path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(22050)
        
        # Generate audio using Piper - collect AudioChunk objects
        audio_generator = voice.synthesize("Hello, this is a test.")
        for audio_chunk in audio_generator:
            wav_file.writeframes(audio_chunk.audio_int16_bytes)
    
    with open(wav_path, "rb") as f:
        wav_data = f.read()
    
    print(f"✅ Generated WAV: {len(wav_data)} bytes")
    
    # Test sox conversion
    with tempfile.NamedTemporaryFile(suffix=".ulaw", delete=False) as ulaw_file:
        ulaw_path = ulaw_file.name
    
    cmd = ["sox", wav_path, "-r", "8000", "-c", "1", "-e", "mu-law", "-t", "raw", ulaw_path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        with open(ulaw_path, "rb") as f:
            ulaw_data = f.read()
        print(f"✅ Converted to uLaw: {len(ulaw_data)} bytes")
    else:
        print(f"❌ Sox conversion failed: {result.stderr}")
    
    os.unlink(wav_path)
    os.unlink(ulaw_path)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
