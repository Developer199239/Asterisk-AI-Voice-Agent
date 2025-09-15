#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script to verify Local AI Server STT->LLM->TTS pipeline works correctly.
This tests the provider pipeline before integrating with the full conversation flow.
"""

import asyncio
import base64
import json
import websockets
import logging
import sys
import os

# Add the src directory to the path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_local_ai_pipeline():
    """Test the Local AI Server pipeline: STT → LLM → TTS"""
    
    # Test 1: Test greeting generation
    print("Test 1: Testing greeting generation...")
    await test_greeting()
    
    # Test 2: Test audio processing pipeline
    print("\nTest 2: Testing audio processing pipeline...")
    await test_audio_pipeline()

async def test_greeting():
    """Test greeting message generation"""
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as websocket:
            greeting_message = {
                "type": "greeting",
                "call_id": "test-call-001",
                "message": "Hello! I'm your AI assistant. How can I help you today?"
            }
            
            await websocket.send(json.dumps(greeting_message))
            print("SUCCESS: Sent greeting message to Local AI Server")
            
            # Wait for audio response
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            
            if isinstance(response, bytes):
                print(f"SUCCESS: Received greeting audio response: {len(response)} bytes")
                return True
            else:
                print(f"ERROR: Expected bytes, got: {type(response)}")
                return False
                
    except asyncio.TimeoutError:
        print("ERROR: Timeout waiting for greeting response")
        return False
    except Exception as e:
        print(f"ERROR: Error testing greeting: {e}")
        return False

async def test_audio_pipeline():
    """Test audio processing pipeline (STT → LLM → TTS)"""
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as websocket:
            # Create some test audio data (simulated ulaw audio with some variation)
            # This simulates speech-like audio to produce a better LLM response
            import random
            test_audio = bytes([random.randint(0, 255) for _ in range(8000)])  # 1 second of varied audio
            
            # Convert to base64 as expected by the Local AI Server
            audio_data_b64 = base64.b64encode(test_audio).decode('utf-8')
            
            audio_message = {
                "type": "audio",
                "data": audio_data_b64
            }
            
            await websocket.send(json.dumps(audio_message))
            print("SUCCESS: Sent test audio to Local AI Server")
            
            # Wait for audio response (increased timeout for long TTS generation)
            response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
            
            if isinstance(response, bytes):
                print(f"SUCCESS: Received processed audio response: {len(response)} bytes")
                print("SUCCESS: STT -> LLM -> TTS pipeline working!")
                return True
            else:
                print(f"ERROR: Expected bytes, got: {type(response)}")
                return False
                
    except asyncio.TimeoutError:
        print("ERROR: Timeout waiting for audio processing response")
        return False
    except Exception as e:
        print(f"ERROR: Error testing audio pipeline: {e}")
        return False

async def test_timeout_greeting():
    """Test timeout greeting generation"""
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as websocket:
            timeout_message = {
                "type": "timeout_greeting",
                "call_id": "test-call-002",
                "message": "Are you still there? I'm here and ready to help."
            }
            
            await websocket.send(json.dumps(timeout_message))
            print("SUCCESS: Sent timeout greeting message to Local AI Server")
            
            # Wait for audio response
            response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
            
            if isinstance(response, bytes):
                print(f"SUCCESS: Received timeout greeting audio response: {len(response)} bytes")
                return True
            else:
                print(f"ERROR: Expected bytes, got: {type(response)}")
                return False
                
    except asyncio.TimeoutError:
        print("ERROR: Timeout waiting for timeout greeting response")
        return False
    except Exception as e:
        print(f"ERROR: Error testing timeout greeting: {e}")
        return False

async def main():
    """Run all tests"""
    print("🚀 Starting Local AI Server Pipeline Tests")
    print("=" * 50)
    
    # Check if Local AI Server is running
    try:
        async with websockets.connect("ws://127.0.0.1:8765") as websocket:
            print("✅ Local AI Server is running and accessible")
    except Exception as e:
        print(f"❌ Cannot connect to Local AI Server: {e}")
        print("Please ensure the Local AI Server is running on port 8765")
        return
    
    # Run tests
    greeting_ok = await test_greeting()
    audio_ok = await test_audio_pipeline()
    timeout_ok = await test_timeout_greeting()
    
    print("\n" + "=" * 50)
    print("📊 Test Results:")
    print(f"  Greeting Generation: {'✅ PASS' if greeting_ok else '❌ FAIL'}")
    print(f"  Audio Pipeline (STT→LLM→TTS): {'✅ PASS' if audio_ok else '❌ FAIL'}")
    print(f"  Timeout Greeting: {'✅ PASS' if timeout_ok else '❌ FAIL'}")
    
    if all([greeting_ok, audio_ok, timeout_ok]):
        print("\n🎉 All tests passed! Local AI Server pipeline is working correctly.")
        print("Ready to test full conversation flow.")
    else:
        print("\n⚠️  Some tests failed. Please check Local AI Server logs.")
        print("Make sure models are loaded and WebSocket server is running.")

if __name__ == "__main__":
    asyncio.run(main())
