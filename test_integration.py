#!/usr/bin/env python3
"""
Integration test script
Tests the complete flow from AI Engine to Local AI Server
"""

import asyncio
import json
import logging
import websockets
import aiohttp
from urllib.parse import quote

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IntegrationTester:
    def __init__(self):
        self.ari_url = "http://127.0.0.1:8088/ari"
        self.ari_username = "AIAgent"
        self.ari_password = "AiAgent+2025?"
        self.ws_url = "ws://127.0.0.1:8765"
        
    async def test_complete_greeting_flow(self):
        """Test the complete greeting flow from AI Engine to Local AI Server"""
        logger.info("🔍 Testing complete greeting flow...")
        
        try:
            # Step 1: Connect to Local AI Server
            async with websockets.connect(self.ws_url) as websocket:
                logger.info("✅ Connected to Local AI Server")
                
                # Step 2: Send greeting message (as AI Engine would)
                greeting_msg = {
                    "type": "greeting",
                    "call_id": "integration_test_789",
                    "message": "Hello! I'm your AI assistant. How can I help you today?"
                }
                
                await websocket.send(json.dumps(greeting_msg))
                logger.info("✅ Greeting message sent to Local AI Server")
                
                # Step 3: Wait for audio response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=20.0)
                    response_data = json.loads(response)
                    
                    if response_data.get('type') == 'audio_response':
                        audio_data = response_data.get('data', '')
                        if audio_data:
                            # Decode and analyze audio
                            import base64
                            decoded_audio = base64.b64decode(audio_data)
                            
                            logger.info(f"✅ Audio response received - {len(decoded_audio)} bytes")
                            
                            # Step 4: Simulate AI Engine playing the audio
                            # (In real scenario, this would be played via ARI)
                            logger.info("✅ Audio ready for playback via ARI")
                            
                            # Step 5: Verify audio format
                            if len(decoded_audio) > 1000:  # Reasonable audio size
                                logger.info("✅ Audio appears to be valid (sufficient size)")
                                return True
                            else:
                                logger.warning("⚠️ Audio seems too small, might be empty or invalid")
                                return False
                        else:
                            logger.error("❌ Empty audio data received")
                            return False
                    else:
                        logger.error(f"❌ Unexpected response type: {response_data.get('type')}")
                        return False
                        
                except asyncio.TimeoutError:
                    logger.error("❌ No response received within 20 seconds")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Integration test error: {e}")
            return False
    
    async def test_audio_processing_flow(self):
        """Test the complete audio processing flow"""
        logger.info("🔍 Testing complete audio processing flow...")
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                logger.info("✅ Connected to Local AI Server")
                
                # Create dummy audio data (simulating caller speech)
                dummy_audio = b'\x00' * 32000  # 2 seconds at 16kHz, 16-bit
                audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')
                
                audio_msg = {
                    "type": "audio",
                    "data": audio_b64
                }
                
                await websocket.send(json.dumps(audio_msg))
                logger.info("✅ Audio message sent to Local AI Server")
                
                # Wait for processing response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                    response_data = json.loads(response)
                    
                    if response_data.get('type') == 'audio_response':
                        audio_data = response_data.get('data', '')
                        if audio_data:
                            import base64
                            decoded_audio = base64.b64decode(audio_data)
                            
                            logger.info(f"✅ Processed audio response received - {len(decoded_audio)} bytes")
                            logger.info("✅ Complete audio processing flow successful")
                            return True
                        else:
                            logger.error("❌ Empty processed audio received")
                            return False
                    else:
                        logger.error(f"❌ Unexpected response type: {response_data.get('type')}")
                        return False
                        
                except asyncio.TimeoutError:
                    logger.error("❌ No processing response within 30 seconds")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Audio processing test error: {e}")
            return False
    
    async def test_ari_playback_simulation(self):
        """Test ARI playback simulation"""
        logger.info("🔍 Testing ARI playback simulation...")
        
        try:
            # Create test audio file
            import wave
            import io
            
            # Generate 1 second of test tone
            sample_rate = 8000
            duration = 1.0
            samples = int(sample_rate * duration)
            
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(sample_rate)
                
                # Generate a simple tone
                import math
                tone_data = []
                for i in range(samples):
                    value = int(32767 * 0.3 * math.sin(2 * math.pi * 440 * i / sample_rate))
                    tone_data.append(value.to_bytes(2, byteorder='little', signed=True))
                
                wav_file.writeframes(b''.join(tone_data))
            
            wav_data = wav_buffer.getvalue()
            
            # Write to shared media directory
            test_file_path = "/mnt/asterisk_media/integration_test.wav"
            with open(test_file_path, 'wb') as f:
                f.write(wav_data)
            
            logger.info(f"✅ Test audio file created: {test_file_path}")
            logger.info(f"✅ File size: {len(wav_data)} bytes")
            
            # Verify file exists and is readable
            import os
            if os.path.exists(test_file_path):
                file_size = os.path.getsize(test_file_path)
                logger.info(f"✅ File verified - Size: {file_size} bytes")
                return True
            else:
                logger.error("❌ Test file not found after creation")
                return False
                
        except Exception as e:
            logger.error(f"❌ ARI playback simulation error: {e}")
            return False
    
    async def test_websocket_connection_stability(self):
        """Test WebSocket connection stability"""
        logger.info("🔍 Testing WebSocket connection stability...")
        
        try:
            # Test multiple connections
            connections = []
            for i in range(3):
                websocket = await websockets.connect(self.ws_url)
                connections.append(websocket)
                logger.info(f"✅ Connection {i+1} established")
            
            # Send messages on all connections
            for i, websocket in enumerate(connections):
                test_msg = {
                    "type": "greeting",
                    "call_id": f"stability_test_{i}",
                    "message": f"Test message {i+1}"
                }
                await websocket.send(json.dumps(test_msg))
                logger.info(f"✅ Message sent on connection {i+1}")
            
            # Close all connections
            for i, websocket in enumerate(connections):
                await websocket.close()
                logger.info(f"✅ Connection {i+1} closed")
            
            logger.info("✅ WebSocket connection stability test passed")
            return True
            
        except Exception as e:
            logger.error(f"❌ WebSocket stability test error: {e}")
            return False

async def main():
    """Run all integration tests"""
    logger.info("🚀 Starting Integration comprehensive tests...")
    
    tester = IntegrationTester()
    results = {}
    
    # Test 1: Complete Greeting Flow
    results['greeting_flow'] = await tester.test_complete_greeting_flow()
    
    # Test 2: Audio Processing Flow
    results['audio_processing'] = await tester.test_audio_processing_flow()
    
    # Test 3: ARI Playback Simulation
    results['ari_playback'] = await tester.test_ari_playback_simulation()
    
    # Test 4: WebSocket Stability
    results['websocket_stability'] = await tester.test_websocket_connection_stability()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("📊 INTEGRATION TEST RESULTS SUMMARY")
    logger.info("="*50)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{test_name.replace('_', ' ').title()}: {status}")
    
    passed = sum(results.values())
    total = len(results)
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All integration tests passed! System is ready for end-to-end testing.")
    else:
        logger.info("⚠️ Some integration tests failed. Check the logs above for details.")

if __name__ == "__main__":
    asyncio.run(main())
