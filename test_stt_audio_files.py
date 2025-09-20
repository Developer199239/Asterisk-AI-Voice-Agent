#!/usr/bin/env python3
"""
Test STT functionality with known Asterisk audio files
This script tests our STT model with known audio files to verify accuracy
"""

import os
import sys
import base64
import json
import asyncio
import websockets
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class STTAudioTester:
    def __init__(self, local_ai_server_url="ws://localhost:8765"):
        self.local_ai_server_url = local_ai_server_url
        self.test_files = [
            # Simple, clear speech files
            ("1-yes-2-no.sln16", "1 yes 2 no"),
            ("afternoon.sln16", "afternoon"),
            ("auth-thankyou.sln16", "auth thank you"),
            ("demo-thanks.sln16", "demo thanks"),
            ("dir-welcome.sln16", "dir welcome"),
            ("cdir-welcome.wav", "cdir welcome"),
        ]
    
    async def test_stt_with_file(self, file_path, expected_text):
        """Test STT with a specific audio file"""
        try:
            # Read the audio file
            with open(file_path, 'rb') as f:
                audio_data = f.read()
            
            logger.info(f"Testing file: {file_path}")
            logger.info(f"Expected text: '{expected_text}'")
            logger.info(f"Audio size: {len(audio_data)} bytes")
            
            # Connect to local AI server
            async with websockets.connect(self.local_ai_server_url) as websocket:
                # Send audio data
                msg = json.dumps({
                    "type": "audio", 
                    "data": base64.b64encode(audio_data).decode('utf-8'),
                    "rate": 16000,  # sln16 is 16kHz
                    "format": "pcm16le"
                })
                
                await websocket.send(msg)
                logger.info("Audio sent to STT")
                
                # Wait for response
                response = await websocket.recv()
                result = json.loads(response)
                
                if result.get("type") == "stt_result":
                    transcript = result.get("transcript", "")
                    logger.info(f"STT Result: '{transcript}'")
                    
                    # Compare with expected
                    expected_lower = expected_text.lower().strip()
                    transcript_lower = transcript.lower().strip()
                    
                    # Simple similarity check
                    similarity = self.calculate_similarity(expected_lower, transcript_lower)
                    
                    logger.info(f"Expected: '{expected_text}'")
                    logger.info(f"Got: '{transcript}'")
                    logger.info(f"Similarity: {similarity:.2f}%")
                    
                    return {
                        "file": file_path,
                        "expected": expected_text,
                        "transcript": transcript,
                        "similarity": similarity,
                        "success": similarity > 50.0
                    }
                else:
                    logger.error(f"Unexpected response type: {result.get('type')}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error testing {file_path}: {e}")
            return None
    
    def calculate_similarity(self, text1, text2):
        """Calculate simple similarity between two texts"""
        words1 = set(text1.split())
        words2 = set(text2.split())
        
        if not words1 and not words2:
            return 100.0
        if not words1 or not words2:
            return 0.0
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        return (len(intersection) / len(union)) * 100
    
    async def run_tests(self, audio_dir="/var/lib/asterisk/sounds/en"):
        """Run STT tests on all test files"""
        logger.info("Starting STT Audio File Tests")
        logger.info(f"Testing files in: {audio_dir}")
        
        results = []
        
        for filename, expected_text in self.test_files:
            file_path = os.path.join(audio_dir, filename)
            
            if os.path.exists(file_path):
                result = await self.test_stt_with_file(file_path, expected_text)
                if result:
                    results.append(result)
            else:
                logger.warning(f"File not found: {file_path}")
        
        # Print summary
        logger.info("\n" + "="*60)
        logger.info("STT TEST SUMMARY")
        logger.info("="*60)
        
        successful_tests = 0
        total_tests = len(results)
        
        for result in results:
            status = "✅ PASS" if result["success"] else "❌ FAIL"
            logger.info(f"{status} {result['file']}")
            logger.info(f"    Expected: '{result['expected']}'")
            logger.info(f"    Got:      '{result['transcript']}'")
            logger.info(f"    Similarity: {result['similarity']:.1f}%")
            logger.info("")
            
            if result["success"]:
                successful_tests += 1
        
        logger.info(f"Results: {successful_tests}/{total_tests} tests passed")
        logger.info(f"Success rate: {(successful_tests/total_tests)*100:.1f}%")
        
        return results

async def main():
    tester = STTAudioTester()
    results = await tester.run_tests()
    
    # Exit with error code if any tests failed
    failed_tests = [r for r in results if not r["success"]]
    if failed_tests:
        logger.error(f"{len(failed_tests)} tests failed")
        sys.exit(1)
    else:
        logger.info("All tests passed!")
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(main())