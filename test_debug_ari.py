#!/usr/bin/env python3
"""
Debug ARI 400 Error
"""

import asyncio
import aiohttp
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def debug_ari_error():
    """Debug ARI 400 error"""
    ari_base = "http://127.0.0.1:8088/ari"
    ari_auth = aiohttp.BasicAuth("AIAgent", "AiAgent+2025?")
    
    try:
        # Test 1: Simple channel creation
        logger.info("Test 1: Simple channel creation...")
        channel_data = {
            "endpoint": "Local/s@ai-agent-media-fork"
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{ari_base}/channels",
                auth=ari_auth,
                json=channel_data
            ) as resp:
                logger.info(f"Status: {resp.status}")
                if resp.status != 201:
                    error_text = await resp.text()
                    logger.error(f"Error: {error_text}")
                else:
                    result = await resp.json()
                    logger.info(f"Success: {result}")
                
    except Exception as e:
        logger.error(f"Exception: {e}")

if __name__ == "__main__":
    asyncio.run(debug_ari_error())
