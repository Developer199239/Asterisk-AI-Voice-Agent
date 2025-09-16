#!/usr/bin/env python3
"""
Test AVR Dial Pattern
This tests the AVR approach: Dial(AudioSocket/...) directly
"""

import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AVRDialPatternTest:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AiAgent+2025?")
        self.app_name = "test-avr-dial"
        
    async def test_avr_dial_pattern(self):
        """Test AVR Dial pattern approach"""
        try:
            logger.info("🧪 Testing AVR Dial Pattern")
            
            # Step 1: Create a channel that will dial AudioSocket
            logger.info("Step 1: Creating channel for AVR Dial pattern...")
            channel_data = {
                "endpoint": "Local/5001@test-avr-dial",
                "app": self.app_name,
                "appArgs": "test"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth,
                    json=channel_data
                ) as resp:
                    if resp.status not in [200, 201]:
                        logger.error(f"❌ Failed to create channel: {resp.status}")
                        error_text = await resp.text()
                        logger.error(f"Error details: {error_text}")
                        return False
                    
                    channel_info = await resp.json()
                    channel_id = channel_info["id"]
                    logger.info(f"✅ Channel created: {channel_id} (status: {resp.status})")
                
                # Step 2: Wait for AudioSocket to establish
                logger.info("Step 2: Waiting for AudioSocket connection...")
                await asyncio.sleep(3)
                
                # Step 3: Check if we can create a bridge
                logger.info("Step 3: Testing bridge creation...")
                bridge_data = {
                    "type": "mixing"
                }
                
                async with session.post(
                    f"{self.ari_base}/bridges",
                    auth=self.ari_auth,
                    json=bridge_data
                ) as resp:
                    if resp.status not in [200, 201]:
                        logger.error(f"❌ Failed to create bridge: {resp.status}")
                        return False
                    
                    bridge_info = await resp.json()
                    bridge_id = bridge_info["id"]
                    logger.info(f"✅ Bridge created: {bridge_id} (status: {resp.status})")
                
                # Step 4: Try to add channel to bridge
                logger.info("Step 4: Testing channel addition to bridge...")
                async with session.post(
                    f"{self.ari_base}/bridges/{bridge_id}/addChannel",
                    auth=self.ari_auth,
                    json={"channel": channel_id}
                ) as resp:
                    if resp.status == 204:
                        logger.info("✅ Channel added to bridge successfully")
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ Failed to add channel to bridge: {resp.status} - {error_text}")
                        return False
                
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            return False

def main():
    test = AVRDialPatternTest()
    success = asyncio.run(test.test_avr_dial_pattern())
    
    if success:
        logger.info("🎉 AVR Dial Pattern test PASSED")
        sys.exit(0)
    else:
        logger.error("💥 AVR Dial Pattern test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
