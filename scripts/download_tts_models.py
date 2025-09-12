#!/usr/bin/env python3
"""
Pre-download Coqui TTS models to avoid downloading during live calls.
This script runs during Docker build to ensure models are ready.
"""

import os
import sys
from pathlib import Path

def download_tts_models():
    """Download Coqui TTS models to the models directory."""
    try:
        # Import TTS only when needed
        from TTS.api import TTS
        
        # Set the model directory
        models_dir = Path("/app/models/tts")
        models_dir.mkdir(parents=True, exist_ok=True)
        
        print("Pre-downloading Coqui TTS models...")
        
        # Download the TTS model
        tts = TTS("tts_models/en/ljspeech/tacotron2-DDC")
        
        # Test the model by generating a short audio sample
        print("Testing TTS model...")
        test_text = "Hello, this is a test."
        test_audio = tts.tts(test_text)
        
        print(f"TTS model downloaded and tested successfully!")
        print(f"Model files saved to: {models_dir}")
        
        return True
        
    except Exception as e:
        print(f"Error downloading TTS models: {e}")
        return False

if __name__ == "__main__":
    success = download_tts_models()
    sys.exit(0 if success else 1)
