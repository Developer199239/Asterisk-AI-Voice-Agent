"""
Asterisk ARI (Asterisk REST Interface) WebSocket Client

This module provides WebSocket connectivity to Asterisk ARI for real-time
call management and control.
"""

import asyncio
import json
import logging
import websockets
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from shared.config import AsteriskConfig
import structlog

logger = structlog.get_logger(__name__)


class ARIEvent:
    """Represents an ARI event with type and data"""
    
    def __init__(self, event_type: str, data: Dict[str, Any]):
        self.type = event_type
        self.data = data
        self.timestamp = datetime.utcnow()
    
    def __str__(self):
        return f"ARIEvent(type={self.type}, timestamp={self.timestamp})"


class ARIClient:
    """Asterisk ARI WebSocket client for call management"""
    
    def __init__(self, config: AsteriskConfig):
        self.host = config.host
        self.port = config.asterisk_port
        self.username = config.username
        self.password = config.password
        
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.running = False
        
        # ARI URLs
        self.ws_url = f"ws://{self.host}:{self.port}/ari/events?api_key={self.username}:{self.password}&app=asterisk-ai-voice-agent"
        self.http_url = f"http://{self.host}:{self.port}/ari"
    
    async def connect(self):
        """Connect to Asterisk ARI WebSocket and HTTP API"""
        if self.websocket:
            logger.warning("Already connected to ARI WebSocket")
            return

        ws_url = f"ws://{self.host}:{self.port}/ari/events?api_key={self.username}:{self.password}&app=asterisk-ai-voice-agent"
        logger.info(f"Connecting to ARI WebSocket at {ws_url}")
        try:
            # Create HTTP session for ARI API calls
            self.http_session = aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(self.username, self.password),
                timeout=aiohttp.ClientTimeout(total=30)
            )
            
            # Test HTTP connection first
            await self._test_http_connection()
            
            # Connect to WebSocket
            self.websocket = await websockets.connect(
                ws_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            logger.info("Successfully connected to ARI WebSocket")
            
        except Exception as e:
            logger.error("ARI WebSocket connection failed", error=str(e), exc_info=True)
            if self.http_session:
                await self.http_session.close()
            raise
    
    async def disconnect(self):
        """Disconnect from ARI"""
        self.running = False
        
        if self.websocket:
            await self.websocket.close()
        
        if self.http_session:
            await self.http_session.close()
        
        logger.info("Disconnected from Asterisk ARI")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((ConnectionError, OSError))
    )
    async def _test_http_connection(self):
        """Test HTTP connection to ARI"""
        try:
            async with self.http_session.get(f"{self.http_url}/asterisk/info") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"ARI HTTP connection successful: {data.get('system', {}).get('version', 'Unknown')}")
                else:
                    raise ConnectionError(f"ARI HTTP connection failed: {response.status}")
        except Exception as e:
            logger.error(f"ARI HTTP connection test failed: {e}")
            raise
    
    async def _connect_websocket(self):
        """Connect to ARI WebSocket"""
        try:
            self.websocket = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=10,
                close_timeout=10
            )
            logger.info("ARI WebSocket connected")
        except Exception as e:
            logger.error(f"Failed to connect to ARI WebSocket: {e}")
            raise
    
    async def start_listening(self):
        """Start listening for ARI events"""
        if not self.websocket:
            raise RuntimeError("Not connected to ARI WebSocket")
        
        self.running = True
        logger.info("Started listening for ARI events")
        
        try:
            async for message in self.websocket:
                if not self.running:
                    break
                
                try:
                    event_data = json.loads(message)
                    event = ARIEvent(
                        event_type=event_data.get("type", "unknown"),
                        data=event_data
                    )
                    
                    await self._handle_event(event)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse ARI event: {e}")
                except Exception as e:
                    logger.error(f"Error handling ARI event: {e}")
                    
        except websockets.exceptions.ConnectionClosed:
            logger.warning("ARI WebSocket connection closed")
        except Exception as e:
            logger.error(f"Error in ARI event loop: {e}")
            raise
        finally:
            self.running = False
    
    async def stop_listening(self):
        """Stop listening for ARI events"""
        self.running = False
        logger.info("Stopped listening for ARI events")
    
    async def _handle_event(self, event: ARIEvent):
        """Handle incoming ARI event"""
        try:
            # Log event
            logger.debug(f"Received ARI event: {event.type}")
            
            # Route to handlers
            if event.type in self.event_handlers:
                for handler in self.event_handlers[event.type]:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Error in event handler for {event.type}: {e}")
            
        except Exception as e:
            logger.error(f"Error handling ARI event {event.type}: {e}")
    
    def add_event_handler(self, event_type: str, handler: Callable):
        """Add event handler for specific event type"""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.debug(f"Added event handler for {event_type}")
    
    # ARI API Methods
    
    async def answer_channel(self, channel_id: str) -> bool:
        """Answer a channel"""
        try:
            async with self.http_session.post(f"{self.http_url}/channels/{channel_id}/answer") as response:
                if response.status == 204:
                    logger.info(f"Answered channel {channel_id}")
                    return True
                else:
                    logger.error(f"Failed to answer channel {channel_id}: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error answering channel {channel_id}: {e}")
            return False
    
    async def hangup_channel(self, channel_id: str, reason: str = "normal") -> bool:
        """Hangup a channel"""
        try:
            async with self.http_session.delete(f"{self.http_url}/channels/{channel_id}?reason={reason}") as response:
                if response.status == 204:
                    logger.info(f"Hung up channel {channel_id}")
                    return True
                else:
                    logger.error(f"Failed to hangup channel {channel_id}: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error hanging up channel {channel_id}: {e}")
            return False
    
    async def play_media(self, channel_id: str, media: str, language: str = "en") -> bool:
        """Play media to a channel"""
        try:
            data = {
                "media": media,
                "language": language
            }
            async with self.http_session.post(f"{self.http_url}/channels/{channel_id}/play", json=data) as response:
                if response.status == 201:
                    logger.info(f"Started playing media to channel {channel_id}")
                    return True
                else:
                    logger.error(f"Failed to play media to channel {channel_id}: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error playing media to channel {channel_id}: {e}")
            return False
    
    async def stop_media(self, channel_id: str) -> bool:
        """Stop media playback on a channel"""
        try:
            async with self.http_session.post(f"{self.http_url}/channels/{channel_id}/stop") as response:
                if response.status == 204:
                    logger.info(f"Stopped media on channel {channel_id}")
                    return True
                else:
                    logger.error(f"Failed to stop media on channel {channel_id}: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Error stopping media on channel {channel_id}: {e}")
            return False
    
    async def get_channel_info(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get channel information"""
        try:
            async with self.http_session.get(f"{self.http_url}/channels/{channel_id}") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get channel info for {channel_id}: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting channel info for {channel_id}: {e}")
            return None
    
    async def health_check(self) -> bool:
        """Check ARI connection health"""
        try:
            if not self.http_session:
                return False
            
            async with self.http_session.get(f"{self.http_url}/asterisk/info") as response:
                return response.status == 200
        except Exception:
            return False
    
    async def ping(self) -> bool:
        """Ping ARI to check connection status."""
        return await self.health_check()


if __name__ == "__main__":
    # Test ARI client
    async def test_ari_client():
        client = ARIClient(
            config=AsteriskConfig(
                host="voiprnd.nemtclouddispatch.com",
                asterisk_port=8088,
                username="AIAgent",
                password="c4d5359e2f9ddd394cd6aa116c1c6a96"
            )
        )
        
        try:
            await client.connect()
            
            # Add test event handler
            async def test_handler(event):
                print(f"Received event: {event.type}")
            
            client.add_event_handler("StasisStart", test_handler)
            
            # Start listening (will run for a few seconds)
            await asyncio.wait_for(client.start_listening(), timeout=10)
            
        except asyncio.TimeoutError:
            print("Test completed (timeout)")
        except Exception as e:
            print(f"Test failed: {e}")
        finally:
            await client.disconnect()
    
    # Run test
    asyncio.run(test_ari_client())
