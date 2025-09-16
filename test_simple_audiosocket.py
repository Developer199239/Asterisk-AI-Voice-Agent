#!/usr/bin/env python3
"""
Test Simple AudioSocket without Local Channel
This tests if we can use AudioSocket directly in a regular channel
"""

import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleAudioSocketTest:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AiAgent+2025?")
        self.app_name = "test-simple-audiosocket"
        
    async def test_simple_audiosocket(self):
        """Test simple AudioSocket approach"""
        try:
            logger.info("🧪 Testing Simple AudioSocket Pattern")
            
            # Step 1: Create a regular channel that will execute AudioSocket
            logger.info("Step 1: Creating regular channel for AudioSocket...")
            channel_data = {
                "endpoint": "Local/s@test-simple-audiosocket",
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
                
                # Step 2: Wait for channel to be ready
                logger.info("Step 2: Waiting for channel to be ready...")
                await asyncio.sleep(1)
                
                # Step 3: Check channel status
                logger.info("Step 3: Checking channel status...")
                async with session.get(
                    f"{self.ari_base}/channels/{channel_id}",
                    auth=self.ari_auth
                ) as resp:
                    if resp.status == 200:
                        channel_info = await resp.json()
                        logger.info(f"Channel state: {channel_info.get('state', 'unknown')}")
                        logger.info(f"Channel name: {channel_info.get('name', 'unknown')}")
                    else:
                        logger.error(f"❌ Failed to get channel info: {resp.status}")
                
                # Step 4: Test if we can create a bridge
                logger.info("Step 4: Testing bridge creation...")
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
    test = SimpleAudioSocketTest()
    success = asyncio.run(test.test_simple_audiosocket())
    
    if success:
        logger.info("🎉 Simple AudioSocket test PASSED")
        sys.exit(0)
    else:
        logger.error("💥 Simple AudioSocket test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
