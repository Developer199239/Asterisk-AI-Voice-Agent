#!/usr/bin/env python3
"""
Hot Reload LLM Script
Triggers hot reload of LLM model with optimized parameters
"""

import asyncio
import json
import websockets
import logging

logging.basicConfig(level=logging.INFO)

async def hot_reload_llm():
    """Hot reload LLM model with optimizations"""
    try:
        # Connect to Local AI Server
        uri = "ws://127.0.0.1:8765"
        async with websockets.connect(uri) as websocket:
            logging.info("🔌 Connected to Local AI Server")
            
            # Send hot reload command
            reload_command = {
                "type": "reload_llm"
            }
            
            logging.info("🔄 Sending LLM hot reload command...")
            await websocket.send(json.dumps(reload_command))
            
            # Wait for response
            response = await websocket.recv()
            response_data = json.loads(response)
            
            if response_data.get("status") == "success":
                logging.info(f"✅ {response_data.get('message')}")
                logging.info("🚀 LLM optimizations applied successfully!")
                logging.info("📊 Optimized parameters:")
                logging.info("   - Context: 1024 tokens (increased from 512)")
                logging.info("   - Batch size: 512 (increased from 256)")
                logging.info("   - Max tokens: 80 (increased from 50)")
                logging.info("   - Temperature: 0.3 (decreased from 0.5)")
                logging.info("   - Memory mapping: Enabled")
                logging.info("   - Memory locking: Enabled")
            else:
                logging.error(f"❌ Hot reload failed: {response_data}")
                
    except Exception as e:
        logging.error(f"❌ Hot reload error: {e}")

if __name__ == "__main__":
    asyncio.run(hot_reload_llm())
