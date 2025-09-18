#!/usr/bin/env python3
"""
Test the audio resampling function to verify it works correctly.
"""

import audioop
import struct

def resample_8k_to_16k(pcm_8k: bytes) -> bytes:
    """Resample PCM16 8kHz to 16kHz using audioop.ratecv."""
    try:
        # Use audioop.ratecv for proper resampling
        pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
        return pcm_16k
    except Exception as e:
        print(f"Resampling failed: {e}")
        return pcm_8k  # Return original if resampling fails

def test_resampling():
    """Test resampling with the Asterisk audio file."""
    
    # Read the 8kHz file
    with open("test_audio.sln16", "rb") as f:
        pcm_8k = f.read()
    
    print(f"Original 8kHz file: {len(pcm_8k)} bytes")
    print(f"Duration: {len(pcm_8k) / (8000 * 2):.2f} seconds")
    
    # Resample to 16kHz
    pcm_16k = resample_8k_to_16k(pcm_8k)
    
    print(f"Resampled 16kHz file: {len(pcm_16k)} bytes")
    print(f"Duration: {len(pcm_16k) / (16000 * 2):.2f} seconds")
    print(f"Expected size: {len(pcm_8k) * 2} bytes")
    print(f"Size ratio: {len(pcm_16k) / len(pcm_8k):.2f}")
    
    # Check first few samples
    samples_8k = [struct.unpack("<h", pcm_8k[i:i+2])[0] for i in range(0, 20, 2)]
    samples_16k = [struct.unpack("<h", pcm_16k[i:i+2])[0] for i in range(0, 40, 2)]
    
    print(f"First 10 samples 8kHz: {samples_8k}")
    print(f"First 20 samples 16kHz: {samples_16k}")
    
    # Save resampled file for testing
    with open("test_audio_16k.sln16", "wb") as f:
        f.write(pcm_16k)
    
    print("✅ Resampled file saved as test_audio_16k.sln16")

if __name__ == "__main__":
    test_resampling()
