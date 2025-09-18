#!/usr/bin/env python3
"""
Test STT with different chunk sizes to find optimal configuration.
This will help us understand if 20ms chunks are too small for Vosk STT.
"""

import asyncio
import websockets
import json
import base64
import struct
import math

async def test_stt_chunk_sizes():
    """Test STT with different chunk sizes to find optimal performance."""
    
    # Generate test audio - 1 second of 16kHz PCM16
    sample_rate = 16000
    duration = 1.0
    frequency = 440  # A4 note
    
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        # Generate a simple tone that should be detectable
        sample = int(32767 * 0.1 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated test audio: {len(audio_data)} bytes for {duration}s at {sample_rate}Hz")
    
    # Test different chunk sizes
    chunk_sizes = [640, 1280, 2560, 5120, 10240]  # 20ms, 40ms, 80ms, 160ms, 320ms
    
    for chunk_size in chunk_sizes:
        if chunk_size <= len(audio_data):
            chunk = audio_data[:chunk_size]
            duration_ms = chunk_size / (sample_rate * 2) * 1000
            print(f"\nTesting chunk size: {chunk_size} bytes ({duration_ms:.1f}ms)")
            
            # Test with Local AI Server
            try:
                async with websockets.connect("ws://localhost:8765") as websocket:
                    # Send audio chunk
                    audio_b64 = base64.b64encode(chunk).decode('utf-8')
                    message = {
                        "type": "audio",
                        "data": audio_b64,
                        "format": "pcm16",
                        "sample_rate": 16000
                    }
                    await websocket.send(json.dumps(message))
                    
                    # Send end signal
                    await websocket.send(json.dumps({"type": "audio_end"}))
                    
                    # Wait for response
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        result = json.loads(response)
                        transcript = result.get('transcript', '')
                        print(f"  STT Result: '{transcript}'")
                        
                        if transcript:
                            print(f"  ✅ SUCCESS: Speech detected with {duration_ms:.1f}ms chunk")
                        else:
                            print(f"  ❌ FAILED: No speech detected with {duration_ms:.1f}ms chunk")
                            
                    except asyncio.TimeoutError:
                        print(f"  ⏰ TIMEOUT: No response for {duration_ms:.1f}ms chunk")
                        
            except Exception as e:
                print(f"  ❌ ERROR: {e}")

if __name__ == "__main__":
    asyncio.run(test_stt_chunk_sizes())
