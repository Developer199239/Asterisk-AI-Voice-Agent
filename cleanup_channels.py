#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Channel Cleanup Script
Cleans up all active channels and calls created by the test script
"""

import asyncio
import aiohttp
import json
import logging
import sys
import os

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class ChannelCleanup:
    def __init__(self, ari_host: str = "127.0.0.1", ari_port: int = 8088, 
                 ari_username: str = "asterisk", ari_password: str = "asterisk"):
        self.ari_host = ari_host
        self.ari_port = ari_port
        self.ari_username = ari_username
        self.ari_password = ari_password
        self.base_url = f"http://{ari_host}:{ari_port}/ari"
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            auth=aiohttp.BasicAuth(self.ari_username, self.ari_password)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_all_channels(self):
        """Get all active channels"""
        try:
            async with self.session.get(f"{self.base_url}/channels") as response:
                if response.status == 200:
                    channels = await response.json()
                    logger.info(f"📋 Found {len(channels)} active channels")
                    return channels
                else:
                    logger.error(f"❌ Failed to get channels - Status: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"❌ Error getting channels: {e}")
            return []
    
    async def hangup_channel(self, channel_id: str) -> bool:
        """Hang up a specific channel"""
        try:
            async with self.session.delete(f"{self.base_url}/channels/{channel_id}") as response:
                if response.status == 204:
                    logger.info(f"✅ Channel {channel_id} hung up successfully")
                    return True
                else:
                    logger.warning(f"⚠️ Channel {channel_id} hangup returned status: {response.status}")
                    return False
        except Exception as e:
            logger.warning(f"⚠️ Error hanging up channel {channel_id}: {e}")
            return False
    
    async def cleanup_all_channels(self):
        """Clean up all active channels"""
        try:
            logger.info("🧹 Starting channel cleanup...")
            
            # Get all active channels
            channels = await self.get_all_channels()
            
            if not channels:
                logger.info("✅ No active channels found")
                return
            
            # Hang up all channels
            cleanup_tasks = []
            for channel in channels:
                channel_id = channel.get('id')
                channel_name = channel.get('name', 'Unknown')
                channel_state = channel.get('state', 'Unknown')
                
                logger.info(f"🔌 Hanging up channel: {channel_id} ({channel_name}) - State: {channel_state}")
                cleanup_tasks.append(self.hangup_channel(channel_id))
            
            # Wait for all hangup operations to complete
            if cleanup_tasks:
                results = await asyncio.gather(*cleanup_tasks, return_exceptions=True)
                
                successful = sum(1 for result in results if result is True)
                failed = len(results) - successful
                
                logger.info(f"📊 Cleanup complete: {successful} successful, {failed} failed")
            else:
                logger.info("✅ No channels to clean up")
                
        except Exception as e:
            logger.error(f"❌ Error during cleanup: {e}")
    
    async def get_applications(self):
        """Get all registered applications"""
        try:
            async with self.session.get(f"{self.base_url}/applications") as response:
                if response.status == 200:
                    apps = await response.json()
                    logger.info(f"📋 Found {len(apps)} registered applications")
                    return apps
                else:
                    logger.error(f"❌ Failed to get applications - Status: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"❌ Error getting applications: {e}")
            return []
    
    async def cleanup_application(self, app_name: str):
        """Clean up a specific application"""
        try:
            async with self.session.delete(f"{self.base_url}/applications/{app_name}") as response:
                if response.status == 204:
                    logger.info(f"✅ Application {app_name} cleaned up successfully")
                    return True
                else:
                    logger.warning(f"⚠️ Application {app_name} cleanup returned status: {response.status}")
                    return False
        except Exception as e:
            logger.warning(f"⚠️ Error cleaning up application {app_name}: {e}")
            return False

async def main():
    """Main cleanup function"""
    logger.info("🚀 Starting Channel Cleanup")
    logger.info("=" * 50)
    
    # Load environment variables
    ari_host = os.getenv("ASTERISK_HOST", "127.0.0.1")
    ari_username = os.getenv("ASTERISK_ARI_USERNAME", "asterisk")
    ari_password = os.getenv("ASTERISK_ARI_PASSWORD", "asterisk")
    
    # Load from .env file if it exists
    try:
        from dotenv import load_dotenv
        load_dotenv()
        ari_host = os.getenv("ASTERISK_HOST", ari_host)
        ari_username = os.getenv("ASTERISK_ARI_USERNAME", ari_username)
        ari_password = os.getenv("ASTERISK_ARI_PASSWORD", ari_password)
    except ImportError:
        pass
    
    logger.info(f"ARI Host: {ari_host}")
    logger.info(f"ARI Username: {ari_username}")
    logger.info(f"ARI Password: {'*' * len(ari_password)}")
    logger.info("")
    
    async with ChannelCleanup(ari_host, 8088, ari_username, ari_password) as cleanup:
        # Clean up all channels
        await cleanup.cleanup_all_channels()
        
        # Wait a moment for cleanup to complete
        await asyncio.sleep(2)
        
        # Check if any channels remain
        remaining_channels = await cleanup.get_all_channels()
        if remaining_channels:
            logger.warning(f"⚠️ {len(remaining_channels)} channels still active after cleanup")
            for channel in remaining_channels:
                logger.warning(f"   - {channel.get('id')} ({channel.get('name', 'Unknown')})")
        else:
            logger.info("✅ All channels cleaned up successfully")
        
        # Show applications
        apps = await cleanup.get_applications()
        if apps:
            logger.info("📋 Registered applications:")
            for app in apps:
                logger.info(f"   - {app.get('name', 'Unknown')}")
        
        logger.info("🎉 Cleanup complete!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n⏹️ Cleanup interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"💥 Cleanup failed with error: {e}")
        sys.exit(1)
