#!/usr/bin/env python3
"""
Test script to debug the STT pipeline using actual Asterisk audio files.
This will help identify if the issue is with audio format conversion or STT processing.
"""

import asyncio
import websockets
import json
import base64
import sys
import os

async def test_stt_with_audio_file(audio_file_path, local_ai_server_url="ws://localhost:8765"):
    """Test STT with an actual audio file from Asterisk."""
    
    print(f"🎵 Testing STT with audio file: {audio_file_path}")
    
    # Read the audio file
    try:
        with open(audio_file_path, 'rb') as f:
            audio_data = f.read()
        print(f"📁 Audio file size: {len(audio_data)} bytes")
    except Exception as e:
        print(f"❌ Error reading audio file: {e}")
        return
    
    # Connect to Local AI Server
    try:
        async with websockets.connect(local_ai_server_url) as websocket:
            print(f"✅ Connected to Local AI Server at {local_ai_server_url}")
            
            # Send audio data in chunks (simulating real-time streaming)
            chunk_size = 1600  # 20ms of 16kHz PCM16 audio
            total_chunks = len(audio_data) // chunk_size
            
            print(f"🔄 Sending {total_chunks} chunks of {chunk_size} bytes each")
            
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                if len(chunk) < chunk_size:
                    # Pad last chunk with zeros
                    chunk += b'\x00' * (chunk_size - len(chunk))
                
                # Encode as base64
                audio_b64 = base64.b64encode(chunk).decode('utf-8')
                
                # Send audio data
                message = {
                    "type": "audio",
                    "data": audio_b64,
                    "format": "pcm16",
                    "sample_rate": 16000
                }
                
                await websocket.send(json.dumps(message))
                print(f"📤 Sent chunk {i//chunk_size + 1}/{total_chunks}")
                
                # Wait a bit to simulate real-time
                await asyncio.sleep(0.02)  # 20ms delay
            
            # Send end of audio signal
            end_message = {
                "type": "audio_end"
            }
            await websocket.send(json.dumps(end_message))
            print("📤 Sent end of audio signal")
            
            # Wait for response
            print("⏳ Waiting for STT response...")
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                result = json.loads(response)
                print(f"📝 STT Response: {result}")
                
                if result.get('transcript'):
                    print(f"✅ SUCCESS: Transcript = '{result['transcript']}'")
                else:
                    print(f"❌ FAILED: No transcript in response")
                    
            except asyncio.TimeoutError:
                print("⏰ Timeout waiting for STT response")
            
    except Exception as e:
        print(f"❌ Error connecting to Local AI Server: {e}")

async def test_direct_audio_processing():
    """Test the audio processing pipeline directly."""
    
    print("\n🔍 Testing audio processing pipeline...")
    
    # Test with a simple sine wave (440Hz for 1 second)
    import math
    import struct
    
    sample_rate = 16000
    duration = 1.0  # 1 second
    frequency = 440  # A4 note
    
    # Generate sine wave
    samples = []
    for i in range(int(sample_rate * duration)):
        t = i / sample_rate
        sample = int(32767 * math.sin(2 * math.pi * frequency * t))
        samples.append(sample)
    
    # Convert to bytes (PCM16)
    audio_data = struct.pack('<' + 'h' * len(samples), *samples)
    
    print(f"🎵 Generated test audio: {len(audio_data)} bytes, {sample_rate}Hz, 16-bit PCM")
    
    # Test with Local AI Server
    await test_stt_with_audio_data(audio_data, "Generated sine wave")

async def test_stt_with_audio_data(audio_data, description):
    """Test STT with raw audio data."""
    
    local_ai_server_url = "ws://localhost:8765"
    
    try:
        async with websockets.connect(local_ai_server_url) as websocket:
            print(f"✅ Connected to Local AI Server for {description}")
            
            # Send audio data
            audio_b64 = base64.b64encode(audio_data).decode('utf-8')
            
            message = {
                "type": "audio",
                "data": audio_b64,
                "format": "pcm16",
                "sample_rate": 16000
            }
            
            await websocket.send(json.dumps(message))
            print(f"📤 Sent {description} audio data")
            
            # Send end signal
            end_message = {"type": "audio_end"}
            await websocket.send(json.dumps(end_message))
            
            # Wait for response
            response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            result = json.loads(response)
            print(f"📝 STT Response for {description}: {result}")
            
    except Exception as e:
        print(f"❌ Error testing {description}: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        asyncio.run(test_stt_with_audio_file(audio_file))
    else:
        print("Usage: python test_stt_pipeline.py <audio_file>")
        print("Or run without arguments to test with generated audio")
        asyncio.run(test_direct_audio_processing())
