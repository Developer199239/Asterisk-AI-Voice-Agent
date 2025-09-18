#!/usr/bin/env python3
"""
Comprehensive analysis of the audio pipeline to understand what we're sending to STT.
"""

import asyncio
import websockets
import json
import base64
import struct
import math
import time

async def analyze_audio_pipeline():
    """Analyze what we're actually sending to the STT."""
    
    print("🔍 AUDIO PIPELINE ANALYSIS")
    print("=" * 50)
    
    # 1. RTP Layer Analysis
    print("\n1. RTP LAYER ANALYSIS")
    print("-" * 30)
    print("RTP Packet Structure:")
    print("  - RTP Header: 12 bytes")
    print("  - Audio Payload: 160 bytes (20ms of 8kHz µ-law)")
    print("  - Total RTP Packet: 172 bytes")
    print()
    print("Codec Processing:")
    print("  - Input: 160 bytes µ-law (8kHz)")
    print("  - Convert: µ-law → PCM16 (320 bytes)")
    print("  - Resample: 8kHz → 16kHz (640 bytes)")
    print("  - Output: 640 bytes PCM16 (16kHz)")
    
    # 2. What STT Actually Receives
    print("\n2. STT INPUT ANALYSIS")
    print("-" * 30)
    print("STT receives:")
    print("  - Format: Base64 encoded PCM16")
    print("  - Sample Rate: 16kHz")
    print("  - Bit Depth: 16-bit")
    print("  - Channels: Mono")
    print("  - Chunk Size: 640 bytes (20ms)")
    print("  - Data Rate: 32,000 bytes/sec")
    
    # 3. Test with Real Audio Data
    print("\n3. TESTING WITH REAL AUDIO DATA")
    print("-" * 30)
    
    # Generate realistic audio that mimics speech
    sample_rate = 16000
    duration = 0.5  # 500ms
    frequency = 440  # A4 note
    
    # Create a more complex audio pattern
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        
        # Create a speech-like pattern with formants
        signal = (
            0.2 * math.sin(2 * math.pi * 200 * t) +   # Fundamental
            0.1 * math.sin(2 * math.pi * 400 * t) +   # First harmonic
            0.05 * math.sin(2 * math.pi * 800 * t) +  # Second harmonic
            0.03 * math.sin(2 * math.pi * 1200 * t)   # Third harmonic
        )
        
        # Add amplitude modulation (speech rhythm)
        amplitude = 0.5 * (1 + 0.3 * math.sin(2 * math.pi * 2 * t))
        
        # Add some noise for realism
        noise = 0.02 * (math.random() - 0.5) if hasattr(math, 'random') else 0
        
        sample = int(32767 * amplitude * (signal + noise))
        samples.append(sample)
    
    audio_data = struct.pack("<" + "h" * len(samples), *samples)
    print(f"Generated test audio: {len(audio_data)} bytes")
    print(f"Duration: {len(audio_data) / (sample_rate * 2):.3f} seconds")
    print(f"Sample range: {min(samples)} to {max(samples)}")
    
    # 4. Test STT with Different Chunk Sizes
    print("\n4. TESTING STT WITH DIFFERENT CHUNK SIZES")
    print("-" * 30)
    
    chunk_sizes = [640, 1280, 2560, 5120]  # 20ms, 40ms, 80ms, 160ms
    
    for chunk_size in chunk_sizes:
        if chunk_size <= len(audio_data):
            chunk = audio_data[:chunk_size]
            duration_ms = chunk_size / (sample_rate * 2) * 1000
            
            print(f"\nTesting {duration_ms:.1f}ms chunk ({chunk_size} bytes):")
            
            # Test with Local AI Server
            try:
                async with websockets.connect("ws://localhost:8765") as websocket:
                    # Send audio chunk
                    audio_b64 = base64.b64encode(chunk).decode('utf-8')
                    message = {
                        "type": "audio",
                        "data": audio_b64
                    }
                    await websocket.send(json.dumps(message))
                    
                    # Send end signal
                    await websocket.send(json.dumps({"type": "audio_end"}))
                    
                    # Wait for response
                    try:
                        response = await asyncio.wait_for(websocket.recv(), timeout=3.0)
                        result = json.loads(response)
                        transcript = result.get('transcript', '')
                        
                        if transcript:
                            print(f"  ✅ SUCCESS: '{transcript}'")
                        else:
                            print(f"  ❌ FAILED: No speech detected")
                            
                    except asyncio.TimeoutError:
                        print(f"  ⏰ TIMEOUT: No response")
                        
            except Exception as e:
                print(f"  ❌ ERROR: {e}")
    
    # 5. Analysis of RTP vs Direct Audio
    print("\n5. RTP vs DIRECT AUDIO COMPARISON")
    print("-" * 30)
    print("RTP Processing:")
    print("  ✅ Handles packet loss detection")
    print("  ✅ Manages jitter buffering")
    print("  ✅ Validates sequence numbers")
    print("  ✅ Converts codecs (µ-law → PCM16)")
    print("  ✅ Resamples audio (8kHz → 16kHz)")
    print("  ❌ Adds latency (20ms chunks)")
    print("  ❌ May lose speech context across chunks")
    print()
    print("Direct Audio to STT:")
    print("  ✅ Lower latency")
    print("  ✅ Better speech context")
    print("  ❌ No packet loss handling")
    print("  ❌ No jitter buffering")
    print("  ❌ No codec conversion")
    
    # 6. Recommendations
    print("\n6. RECOMMENDATIONS")
    print("-" * 30)
    print("For better STT performance:")
    print("  1. Increase chunk size to 100-200ms (1600-3200 bytes)")
    print("  2. Implement audio buffering to accumulate chunks")
    print("  3. Add voice activity detection (VAD)")
    print("  4. Consider streaming STT instead of chunk-based")
    print("  5. Test with actual speech samples")
    print("  6. Verify STT model configuration")

if __name__ == "__main__":
    asyncio.run(analyze_audio_pipeline())
