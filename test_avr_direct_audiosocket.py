#!/usr/bin/env python3
"""
Test AVR Direct AudioSocket Pattern
This tests the approach used by AVR project: Direct AudioSocket in dialplan
"""

import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AVRDirectAudioSocketTest:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AiAgent+2025?")
        self.app_name = "test-avr-direct"
        
    async def test_avr_direct_audiosocket(self):
        """Test AVR direct AudioSocket approach"""
        try:
            logger.info("🧪 Testing AVR Direct AudioSocket Pattern")
            
            # Step 1: Create a channel that will execute AudioSocket directly in dialplan
            logger.info("Step 1: Creating channel for direct AudioSocket...")
            channel_data = {
                "endpoint": "Local/s@test-avr-direct",
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
                
                # Step 2: Answer the channel
                logger.info("Step 2: Answering channel...")
                async with session.post(
                    f"{self.ari_base}/channels/{channel_id}/answer",
                    auth=self.ari_auth
                ) as resp:
                    if resp.status != 204:
                        logger.error(f"❌ Failed to answer channel: {resp.status}")
                        return False
                    logger.info("✅ Channel answered")
                
                # Step 3: Wait for AudioSocket to establish
                logger.info("Step 3: Waiting for AudioSocket connection...")
                await asyncio.sleep(2)
                
                # Step 4: Check if we can create a bridge with this channel
                logger.info("Step 4: Testing bridge creation...")
                bridge_data = {
                    "type": "mixing"
                }
                
                async with session.post(
                    f"{self.ari_base}/bridges",
                    auth=self.ari_auth,
                    json=bridge_data
                ) as resp:
                    if resp.status != 201:
                        logger.error(f"❌ Failed to create bridge: {resp.status}")
                        return False
                    
                    bridge_info = await resp.json()
                    bridge_id = bridge_info["id"]
                    logger.info(f"✅ Bridge created: {bridge_id}")
                
                # Step 5: Try to add channel to bridge
                logger.info("Step 5: Testing channel addition to bridge...")
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
    test = AVRDirectAudioSocketTest()
    success = asyncio.run(test.test_avr_direct_audiosocket())
    
    if success:
        logger.info("🎉 AVR Direct AudioSocket test PASSED")
        sys.exit(0)
    else:
        logger.error("💥 AVR Direct AudioSocket test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
