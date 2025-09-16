#!/usr/bin/env python3
"""
Test Non-Stasis Bridge Pattern
This tests creating bridges outside Stasis context
"""

import asyncio
import aiohttp
import json
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class NonStasisBridgeTest:
    def __init__(self):
        self.ari_base = "http://127.0.0.1:8088/ari"
        self.ari_auth = aiohttp.BasicAuth("AIAgent", "AIAgent123")
        
    async def test_non_stasis_bridge(self):
        """Test creating bridges outside Stasis context"""
        try:
            logger.info("🧪 Testing Non-Stasis Bridge Pattern")
            
            # Step 1: Create a Local channel outside Stasis
            logger.info("Step 1: Creating Local channel outside Stasis...")
            channel_data = {
                "endpoint": "Local/s@ai-agent-media-fork",
                "channelVars": {"test_var": "test_value"}
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.ari_base}/channels",
                    auth=self.ari_auth,
                    json=channel_data
                ) as resp:
                    if resp.status != 201:
                        logger.error(f"❌ Failed to create Local channel: {resp.status}")
                        return False
                    
                    channel_info = await resp.json()
                    local_channel_id = channel_info["id"]
                    logger.info(f"✅ Local channel created: {local_channel_id}")
                
                # Step 2: Create a bridge outside Stasis context
                logger.info("Step 2: Creating bridge outside Stasis...")
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
                
                # Step 3: Try to add Local channel to non-Stasis bridge
                logger.info("Step 3: Testing Local channel addition to non-Stasis bridge...")
                async with session.post(
                    f"{self.ari_base}/bridges/{bridge_id}/addChannel",
                    auth=self.ari_auth,
                    json={"channel": local_channel_id}
                ) as resp:
                    if resp.status == 204:
                        logger.info("✅ Local channel added to non-Stasis bridge successfully")
                        return True
                    else:
                        error_text = await resp.text()
                        logger.error(f"❌ Failed to add Local channel to non-Stasis bridge: {resp.status} - {error_text}")
                        return False
                
        except Exception as e:
            logger.error(f"❌ Test failed with exception: {e}")
            return False

def main():
    test = NonStasisBridgeTest()
    success = asyncio.run(test.test_non_stasis_bridge())
    
    if success:
        logger.info("🎉 Non-Stasis Bridge test PASSED")
        sys.exit(0)
    else:
        logger.error("💥 Non-Stasis Bridge test FAILED")
        sys.exit(1)

if __name__ == "__main__":
    main()
