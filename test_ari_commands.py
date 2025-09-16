#!/usr/bin/env python3
"""
Comprehensive ARI Commands Test
Tests all ARI commands to ensure they work correctly after the URL fix.
"""

import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.ari_client import ARIClient
from src.config import load_config
from src.logging_config import configure_logging, get_logger

logger = get_logger(__name__)

async def test_ari_commands():
    """Test all ARI commands comprehensively."""
    configure_logging()
    
    # Load configuration
    config = load_config()
    
    # Create ARI client
    ari_client = ARIClient(
        username=config.asterisk.username,
        password=config.asterisk.password,
        base_url=f"http://{config.asterisk.host}:{config.asterisk.port}",
        app_name=config.asterisk.app_name
    )
    
    try:
        # Test 1: Connect to ARI
        logger.info("🔌 Testing ARI connection...")
        await ari_client.connect()
        logger.info("✅ ARI connection successful")
        
        # Test 2: Get Asterisk info
        logger.info("📊 Testing get Asterisk info...")
        try:
            info = await ari_client.send_command("GET", "asterisk/info")
            logger.info("✅ Asterisk info retrieved", version=info.get('build', {}).get('version'))
        except Exception as e:
            logger.error("❌ Failed to get Asterisk info", error=str(e))
        
        # Test 3: List applications
        logger.info("📱 Testing list applications...")
        try:
            apps = await ari_client.send_command("GET", "applications")
            logger.info("✅ Applications listed", count=len(apps))
            for app in apps:
                logger.info("  - Application", name=app.get('name'), bridge_count=app.get('bridge_count'))
        except Exception as e:
            logger.error("❌ Failed to list applications", error=str(e))
        
        # Test 4: List channels
        logger.info("📞 Testing list channels...")
        try:
            channels = await ari_client.send_command("GET", "channels")
            logger.info("✅ Channels listed", count=len(channels))
            for channel in channels:
                logger.info("  - Channel", 
                           id=channel.get('id'), 
                           name=channel.get('name'),
                           state=channel.get('state'))
        except Exception as e:
            logger.error("❌ Failed to list channels", error=str(e))
        
        # Test 5: List bridges
        logger.info("🌉 Testing list bridges...")
        try:
            bridges = await ari_client.send_command("GET", "bridges")
            logger.info("✅ Bridges listed", count=len(bridges))
            for bridge in bridges:
                logger.info("  - Bridge", 
                           id=bridge.get('id'), 
                           bridge_type=bridge.get('bridge_type'),
                           bridge_class=bridge.get('bridge_class'))
        except Exception as e:
            logger.error("❌ Failed to list bridges", error=str(e))
        
        # Test 6: List endpoints
        logger.info("🔗 Testing list endpoints...")
        try:
            endpoints = await ari_client.send_command("GET", "endpoints")
            logger.info("✅ Endpoints listed", count=len(endpoints))
            for endpoint in endpoints:
                logger.info("  - Endpoint", 
                           resource=endpoint.get('resource'),
                           state=endpoint.get('state'))
        except Exception as e:
            logger.error("❌ Failed to list endpoints", error=str(e))
        
        # Test 7: Create a test bridge
        logger.info("🌉 Testing create bridge...")
        try:
            bridge_id = await ari_client.create_bridge("mixing")
            if bridge_id:
                logger.info("✅ Bridge created", bridge_id=bridge_id)
                
                # Test 8: Get bridge info
                logger.info("📊 Testing get bridge info...")
                try:
                    bridge_info = await ari_client.send_command("GET", f"bridges/{bridge_id}")
                    logger.info("✅ Bridge info retrieved", 
                               id=bridge_info.get('id'),
                               bridge_type=bridge_info.get('bridge_type'))
                except Exception as e:
                    logger.error("❌ Failed to get bridge info", error=str(e))
                
                # Test 9: Delete the test bridge
                logger.info("🗑️ Testing delete bridge...")
                try:
                    await ari_client.send_command("DELETE", f"bridges/{bridge_id}")
                    logger.info("✅ Bridge deleted", bridge_id=bridge_id)
                except Exception as e:
                    logger.error("❌ Failed to delete bridge", error=str(e))
            else:
                logger.error("❌ Failed to create bridge")
        except Exception as e:
            logger.error("❌ Failed to create bridge", error=str(e))
        
        # Test 10: List sounds
        logger.info("🔊 Testing list sounds...")
        try:
            sounds = await ari_client.send_command("GET", "sounds")
            logger.info("✅ Sounds listed", count=len(sounds))
            for sound in sounds[:5]:  # Show first 5 sounds
                logger.info("  - Sound", id=sound.get('id'))
        except Exception as e:
            logger.error("❌ Failed to list sounds", error=str(e))
        
        # Test 11: Get system info
        logger.info("⚙️ Testing get system info...")
        try:
            system_info = await ari_client.send_command("GET", "asterisk/info")
            logger.info("✅ System info retrieved", 
                       version=system_info.get('build', {}).get('version'),
                       uptime=system_info.get('status', {}).get('uptime'))
        except Exception as e:
            logger.error("❌ Failed to get system info", error=str(e))
        
        # Test 12: Get configuration
        logger.info("⚙️ Testing get configuration...")
        try:
            config_info = await ari_client.send_command("GET", "asterisk/config")
            logger.info("✅ Configuration retrieved", 
                       categories=len(config_info.get('categories', {})))
        except Exception as e:
            logger.error("❌ Failed to get configuration", error=str(e))
        
        logger.info("🎉 ARI commands test completed successfully!")
        
    except Exception as e:
        logger.error("❌ ARI commands test failed", error=str(e), exc_info=True)
    finally:
        # Disconnect
        await ari_client.disconnect()
        logger.info("🔌 Disconnected from ARI")

if __name__ == "__main__":
    asyncio.run(test_ari_commands())
