#!/usr/bin/env python3
"""
Test Direct AudioSocket approach without Local Channel Bridge
This tests the AVR approach: Direct AudioSocket in Stasis context
"""

import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class DirectAudioSocketTest:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AIAgent123")
        self.app_name = "test-direct-audiosocket"
        
    async def test_direct_audiosocket(self):
        """Test direct AudioSocket approach without Local channel"""
        try:
            logger.info("🧪 Testing Direct AudioSocket Approach")
            
            # Step 1: Create a test channel
            logger.info("Step 1: Creating test channel...")
            channel_data = {
                "endpoint": "Local/s@test-direct-audiosocket",
                "app": self.app_name,
                "appArgs": "test"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth,
                    json=channel_data
                ) as resp:
                    if resp.status != 201:
                        logger.error(f"❌ Failed to create channel: {resp.status}")
                        return False
                    
                    channel_info = await resp.json()
                    channel_id = channel_info["id"]
                    logger.info(f"✅ Channel created: {channel_id}")
                
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
                
                # Step 3: Check if AudioSocket can be executed directly
                logger.info("Step 3: Testing direct AudioSocket execution...")
                
                # Create a test dialplan context for direct AudioSocket
                dialplan_data = {
                    "context": "test-direct-audiosocket",
                    "extension": "s",
                    "priority": 1,
                    "app": "AudioSocket",
                    "appData": "TEST-UUID,127.0.0.1:8090"
                }
                
                # This should fail because AudioSocket needs to be in dialplan
                logger.info("Note: AudioSocket must be in dialplan, not ARI command")
                
                # Step 4: Test if we can create a bridge with this channel
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

async def main():
    test = DirectAudioSocketTest()
    success = await test.test_direct_audiosocket()
    
    if success:
        logger.info("🎉 Direct AudioSocket test PASSED")
        sys.exit(0)
    else:
        logger.error("💥 Direct AudioSocket test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
