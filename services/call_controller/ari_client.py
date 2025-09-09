"""
A new, simplified Asterisk ARI WebSocket Client.
Focuses on robust connection and logging to debug startup issues.
"""

import asyncio
import json
import websockets
from typing import Dict, Any, Optional, Callable, List
import aiohttp
import structlog

from shared.config import AsteriskConfig

logger = structlog.get_logger(__name__)

class ARIClient:
    def __init__(self, config: AsteriskConfig):
        self.config = config
        self.ws_url = f"ws://{config.host}:{config.asterisk_port}/ari/events?api_key={config.username}:{config.password}&app={config.app_name}"
        self.http_url = f"http://{config.host}:{config.asterisk_port}/ari"
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.event_handlers: Dict[str, List[Callable]] = {}

    async def connect(self):
        logger.info("ARIClient: connect() called.")
        if self.running:
            logger.warning("ARIClient is already running.")
            return

        try:
            logger.info("Creating aiohttp ClientSession.")
            self.http_session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(self.config.username, self.config.password))
            
            logger.info(f"Attempting to connect to WebSocket: {self.ws_url}")
            self.websocket = await websockets.connect(self.ws_url)
            self.running = True
            logger.info("Successfully connected to ARI WebSocket.")
        except Exception as e:
            logger.error("Failed to connect to ARI.", error=str(e), exc_info=True)
            self.running = False
            if self.http_session and not self.http_session.closed:
                await self.http_session.close()
            raise

    async def start_listening(self):
        if not self.running or not self.websocket:
            logger.error("Cannot start listening, client is not connected.")
            return

        logger.info("Starting ARI event listener loop.")
        try:
            async for message in self.websocket:
                try:
                    event_data = json.loads(message)
                    event_type = event_data.get("type", "unknown")
                    logger.debug("Received ARI event", event_type=event_type, data=event_data)
                    if event_type in self.event_handlers:
                        for handler in self.event_handlers[event_type]:
                            asyncio.create_task(handler(event_data))
                except json.JSONDecodeError:
                    logger.warning("Failed to decode ARI event JSON", message=message)
                except Exception as e:
                    logger.error("Error processing ARI event", exc_info=True)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("ARI WebSocket connection closed.", reason=str(e))
        except Exception as e:
            logger.error("Exception in ARI listener loop.", exc_info=True)
        finally:
            self.running = False
            logger.info("ARI event listener loop stopped.")

    async def disconnect(self):
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            logger.info("ARI WebSocket disconnected.")
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            self.http_session = None
            logger.info("ARI HTTP session closed.")

    def add_event_handler(self, event_type: str, handler: Callable):
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)

    async def answer_channel(self, channel_id: str):
        if not self.http_session:
            return
        url = f"{self.http_url}/channels/{channel_id}/answer"
        try:
            async with self.http_session.post(url) as response:
                if response.status == 204:
                    logger.info("Answered channel", channel_id=channel_id)
                else:
                    logger.error("Failed to answer channel", channel_id=channel_id, status=response.status)
        except Exception as e:
            logger.error("Exception answering channel", exc_info=True)
