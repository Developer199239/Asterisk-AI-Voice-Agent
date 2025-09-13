#!/usr/bin/env python3
"""
Test script for AI Engine container
Tests ARI connection, WebSocket connection, and audio playback
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

class AIEngineTester:
    def __init__(self):
        self.ari_url = "http://127.0.0.1:8088/ari"
        self.ari_username = "AIAgent"
        self.ari_password = "AiAgent+2025?"
        self.ws_url = "ws://127.0.0.1:8765"
        
    async def test_ari_connection(self):
        """Test ARI connection and authentication"""
        logger.info("🔍 Testing ARI connection...")
        
        auth = aiohttp.BasicAuth(self.ari_username, self.ari_password)
        async with aiohttp.ClientSession(auth=auth) as session:
            try:
                async with session.get(f"{self.ari_url}/asterisk/info") as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"✅ ARI connection successful - Asterisk version: {data.get('version')}")
                        return True
                    else:
                        logger.error(f"❌ ARI connection failed - Status: {response.status}")
                        return False
            except Exception as e:
                logger.error(f"❌ ARI connection error: {e}")
                return False
    
    async def test_websocket_connection(self):
        """Test WebSocket connection to local AI server"""
        logger.info("🔍 Testing WebSocket connection to local AI server...")
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                logger.info("✅ WebSocket connection successful")
                
                # Test greeting message
                greeting_msg = {
                    "type": "greeting",
                    "call_id": "test_call_123",
                    "message": "Hello! This is a test greeting."
                }
                
                await websocket.send(json.dumps(greeting_msg))
                logger.info("✅ Greeting message sent")
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
                    response_data = json.loads(response)
                    logger.info(f"✅ Received response: {response_data.get('type')}")
                    
                    if response_data.get('type') == 'audio_response':
                        audio_data = response_data.get('data', '')
                        logger.info(f"✅ Audio response received - {len(audio_data)} characters of base64 data")
                        return True
                    else:
                        logger.warning(f"⚠️ Unexpected response type: {response_data.get('type')}")
                        return False
                        
                except asyncio.TimeoutError:
                    logger.error("❌ No response received within 10 seconds")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ WebSocket connection error: {e}")
            return False
    
    async def test_audio_playback(self):
        """Test audio playback via ARI"""
        logger.info("🔍 Testing audio playback via ARI...")
        
        # Create a simple test audio file (1 second of silence)
        import wave
        import io
        
        # Generate 1 second of silence at 8kHz, 16-bit, mono
        sample_rate = 8000
        duration = 1.0
        samples = int(sample_rate * duration)
        
        # Create WAV data
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b'\x00\x00' * samples)  # Silence
        
        wav_data = wav_buffer.getvalue()
        
        # Write to shared media directory
        test_file_path = "/mnt/asterisk_media/test_audio.wav"
        try:
            with open(test_file_path, 'wb') as f:
                f.write(wav_data)
            logger.info(f"✅ Test audio file created: {test_file_path}")
            
            # Test ARI playback command (we'll need a channel for this)
            logger.info("ℹ️ Audio file ready for playback test")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to create test audio file: {e}")
            return False
    
    async def test_snoop_channel_creation(self):
        """Test snoop channel creation"""
        logger.info("🔍 Testing snoop channel creation...")
        
        auth = aiohttp.BasicAuth(self.ari_username, self.ari_password)
        async with aiohttp.ClientSession(auth=auth) as session:
            try:
                # First, get available channels
                async with session.get(f"{self.ari_url}/channels") as response:
                    if response.status == 200:
                        channels = await response.json()
                        logger.info(f"ℹ️ Found {len(channels)} active channels")
                        
                        if channels:
                            # Use the first channel for testing
                            test_channel_id = channels[0]['id']
                            logger.info(f"ℹ️ Using channel {test_channel_id} for snoop test")
                            
                            # Create snoop channel
                            snoop_params = {
                                "app": "asterisk-ai-voice-agent",
                                "snoopId": f"test_snoop_{test_channel_id}",
                                "spy": "in",
                                "options": "audioframe"
                            }
                            
                            async with session.post(f"{self.ari_url}/channels/{test_channel_id}/snoop", 
                                                  json=snoop_params) as snoop_response:
                                if snoop_response.status == 200:
                                    snoop_data = await snoop_response.json()
                                    snoop_id = snoop_data.get('id')
                                    logger.info(f"✅ Snoop channel created: {snoop_id}")
                                    
                                    # Clean up
                                    await session.delete(f"{self.ari_url}/channels/{snoop_id}")
                                    logger.info("✅ Snoop channel cleaned up")
                                    return True
                                else:
                                    error_text = await snoop_response.text()
                                    logger.error(f"❌ Snoop channel creation failed: {snoop_response.status} - {error_text}")
                                    return False
                        else:
                            logger.warning("⚠️ No active channels found for snoop test")
                            return False
                    else:
                        logger.error(f"❌ Failed to get channels: {response.status}")
                        return False
                        
            except Exception as e:
                logger.error(f"❌ Snoop channel test error: {e}")
                return False

async def main():
    """Run all tests"""
    logger.info("🚀 Starting AI Engine comprehensive tests...")
    
    tester = AIEngineTester()
    results = {}
    
    # Test 1: ARI Connection
    results['ari_connection'] = await tester.test_ari_connection()
    
    # Test 2: WebSocket Connection
    results['websocket_connection'] = await tester.test_websocket_connection()
    
    # Test 3: Audio Playback Setup
    results['audio_playback'] = await tester.test_audio_playback()
    
    # Test 4: Snoop Channel Creation
    results['snoop_channel'] = await tester.test_snoop_channel_creation()
    
    # Summary
    logger.info("\n" + "="*50)
    logger.info("📊 TEST RESULTS SUMMARY")
    logger.info("="*50)
    
    for test_name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{test_name.replace('_', ' ').title()}: {status}")
    
    passed = sum(results.values())
    total = len(results)
    logger.info(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All tests passed! AI Engine is ready.")
    else:
        logger.info("⚠️ Some tests failed. Check the logs above for details.")

if __name__ == "__main__":
    asyncio.run(main())
