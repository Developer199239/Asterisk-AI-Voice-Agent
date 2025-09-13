#!/usr/bin/env python3
"""
Test script for Local AI Server container
Tests model loading, TTS functionality, and WebSocket server
"""

import asyncio
import json
import logging
import websockets
import base64
import os
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class LocalAIServerTester:
    def __init__(self):
        self.ws_url = "ws://127.0.0.1:8765"
        
    async def test_websocket_server(self):
        """Test WebSocket server is running"""
        logger.info("🔍 Testing WebSocket server availability...")
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                logger.info("✅ WebSocket server is running and accepting connections")
                return True
        except Exception as e:
            logger.error(f"❌ WebSocket server not available: {e}")
            return False
    
    async def test_greeting_message(self):
        """Test greeting message handling"""
        logger.info("🔍 Testing greeting message handling...")
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                # Send greeting message
                greeting_msg = {
                    "type": "greeting",
                    "call_id": "test_call_456",
                    "message": "Hello! This is a test greeting message."
                }
                
                await websocket.send(json.dumps(greeting_msg))
                logger.info("✅ Greeting message sent")
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=15.0)
                    
                    # Check if response is binary audio data (not JSON)
                    if isinstance(response, bytes):
                        logger.info(f"✅ Greeting audio response received - {len(response)} bytes")
                        return True
                    else:
                        # Try to parse as JSON (fallback)
                        try:
                            response_data = json.loads(response)
                            if response_data.get('type') == 'audio_response':
                                audio_data = response_data.get('data', '')
                                if audio_data:
                                    decoded_audio = base64.b64decode(audio_data)
                                    logger.info(f"✅ Greeting audio response received - {len(decoded_audio)} bytes")
                                    return True
                        except json.JSONDecodeError:
                            logger.error(f"❌ Unexpected response format: {type(response)}")
                            return False
                        
                except asyncio.TimeoutError:
                    logger.error("❌ No response received within 15 seconds")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Greeting message test error: {e}")
            return False
    
    async def test_audio_message(self):
        """Test audio message processing"""
        logger.info("🔍 Testing audio message processing...")
        
        try:
            async with websockets.connect(self.ws_url) as websocket:
                # Create dummy audio data (1 second of silence)
                dummy_audio = b'\x00' * 16000  # 1 second at 16kHz, 8-bit
                audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')
                
                audio_msg = {
                    "type": "audio",
                    "data": audio_b64
                }
                
                await websocket.send(json.dumps(audio_msg))
                logger.info("✅ Audio message sent")
                
                # Wait for response
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=20.0)
                    
                    # Check if response is binary audio data (not JSON)
                    if isinstance(response, bytes):
                        logger.info(f"✅ Audio processing response received - {len(response)} bytes")
                        return True
                    else:
                        # Try to parse as JSON (fallback)
                        try:
                            response_data = json.loads(response)
                            if response_data.get('type') == 'audio_response':
                                audio_data = response_data.get('data', '')
                                if audio_data:
                                    decoded_audio = base64.b64decode(audio_data)
                                    logger.info(f"✅ Audio processing response received - {len(decoded_audio)} bytes")
                                    return True
                        except json.JSONDecodeError:
                            logger.error(f"❌ Unexpected response format: {type(response)}")
                            return False
                        
                except asyncio.TimeoutError:
                    logger.error("❌ No audio processing response within 20 seconds")
                    return False
                    
        except Exception as e:
            logger.error(f"❌ Audio message test error: {e}")
            return False
    
    def test_model_files(self):
        """Test if model files exist"""
        logger.info("🔍 Testing model file availability...")
        
        model_paths = {
            "STT Model": "/app/models/stt/vosk-model-small-en-us-0.15",
            "LLM Model": "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
        }
        
        results = {}
        for model_name, model_path in model_paths.items():
            if os.path.exists(model_path):
                logger.info(f"✅ {model_name} found: {model_path}")
                results[model_name] = True
            else:
                logger.error(f"❌ {model_name} not found: {model_path}")
                results[model_name] = False
        
        return all(results.values())
    
    def test_tts_functionality(self):
        """Test TTS functionality directly"""
        logger.info("🔍 Testing TTS functionality...")
        
        try:
            from lightweight_tts import LightweightTTS
            
            # Initialize TTS model
            tts_model = LightweightTTS()
            logger.info("✅ TTS model initialized")
            
            # Test TTS generation
            test_text = "Hello, this is a test of the text to speech system."
            wav_data = tts_model.tts(test_text)
            
            if wav_data and len(wav_data) > 0:
                logger.info(f"✅ TTS generation successful - {len(wav_data)} bytes generated")
                return True
            else:
                logger.error("❌ TTS generation failed - no audio data")
                return False
                
        except Exception as e:
            logger.error(f"❌ TTS functionality test error: {e}")
            return False
    
    def test_stt_functionality(self):
        """Test STT functionality directly"""
        logger.info("🔍 Testing STT functionality...")
        
        try:
            from vosk import Model as VoskModel, KaldiRecognizer
            
            # Check if model exists
            model_path = "/app/models/stt/vosk-model-small-en-us-0.15"
            if not os.path.exists(model_path):
                logger.error(f"❌ STT model not found: {model_path}")
                return False
            
            # Initialize STT model
            stt_model = VoskModel(model_path)
            recognizer = KaldiRecognizer(stt_model, 16000)
            logger.info("✅ STT model initialized")
            
            # Test with dummy audio (1 second of silence)
            dummy_audio = b'\x00' * 32000  # 1 second at 16kHz, 16-bit
            recognizer.AcceptWaveform(dummy_audio)
            result = recognizer.FinalResult()
            
            logger.info(f"✅ STT processing successful - Result: {result}")
            return True
            
        except Exception as e:
            logger.error(f"❌ STT functionality test error: {e}")
            return False
    
    def test_llm_functionality(self):
        """Test LLM functionality directly"""
        logger.info("🔍 Testing LLM functionality...")
        
        try:
            from llama_cpp import Llama
            
            # Check if model exists
            model_path = "/app/models/llm/TinyLlama-1.1B-Chat-v1.0.Q4_K_M.gguf"
            if not os.path.exists(model_path):
                logger.error(f"❌ LLM model not found: {model_path}")
                return False
            
            # Initialize LLM model
            llm_model = Llama(model_path=model_path, n_ctx=2048)
            logger.info("✅ LLM model initialized")
            
            # Test with simple prompt
            test_prompt = "Q: What is 2+2? A:"
            output = llm_model(test_prompt, max_tokens=50, stop=["Q:", "\n"], echo=False)
            
            if output and 'choices' in output and len(output['choices']) > 0:
                response = output['choices'][0]['text'].strip()
                logger.info(f"✅ LLM processing successful - Response: {response}")
                return True
            else:
                logger.error("❌ LLM processing failed - no response")
                return False
                
        except Exception as e:
            logger.error(f"❌ LLM functionality test error: {e}")
            return False

async def main():
    """Run all tests"""
    logger.info("🚀 Starting Local AI Server comprehensive tests...")
    
    tester = LocalAIServerTester()
    results = {}
    
    # Test 1: WebSocket Server
    results['websocket_server'] = await tester.test_websocket_server()
    
    # Test 2: Model Files
    results['model_files'] = tester.test_model_files()
    
    # Test 3: TTS Functionality
    results['tts_functionality'] = tester.test_tts_functionality()
    
    # Test 4: STT Functionality
    results['stt_functionality'] = tester.test_stt_functionality()
    
    # Test 5: LLM Functionality
    results['llm_functionality'] = tester.test_llm_functionality()
    
    # Test 6: Greeting Message (requires server to be running)
    if results['websocket_server']:
        results['greeting_message'] = await tester.test_greeting_message()
    else:
        results['greeting_message'] = False
        logger.warning("⚠️ Skipping greeting message test - WebSocket server not available")
    
    # Test 7: Audio Message (requires server to be running)
    if results['websocket_server']:
        results['audio_message'] = await tester.test_audio_message()
    else:
        results['audio_message'] = False
        logger.warning("⚠️ Skipping audio message test - WebSocket server not available")
    
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
        logger.info("🎉 All tests passed! Local AI Server is ready.")
    else:
        logger.info("⚠️ Some tests failed. Check the logs above for details.")

if __name__ == "__main__":
    asyncio.run(main())
