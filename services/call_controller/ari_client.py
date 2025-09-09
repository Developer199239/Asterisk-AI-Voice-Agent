"""
A new, simplified Asterisk ARI WebSocket Client.
Focuses on robust connection and logging to debug startup issues.
"""

import asyncio
import json
from typing import Dict, Any, Optional, Callable, List
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import websockets
import structlog

from shared.config import AsteriskConfig

logger = structlog.get_logger(__name__)

class ARIClient:
    """A client for interacting with the Asterisk REST Interface (ARI)."""

    def __init__(self, config: AsteriskConfig):
        self.config = config
        self.ws_url = f"ws://{config.host}:{config.asterisk_port}/ari/events?api_key={config.username}:{config.password}&app={config.app_name}"
        self.http_url = f"http://{config.host}:{config.asterisk_port}/ari"
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.event_handlers: Dict[str, List[Callable]] = {}

    def on_event(self, event_type: str, handler: Callable):
        """Alias for add_event_handler for backward compatibility."""
        self.add_event_handler(event_type, handler)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
    )
    async def connect(self):
        """Connect to the ARI WebSocket and establish an HTTP session."""
        logger.info("Connecting to ARI...")
        try:
            # First, test HTTP connection to ensure ARI is available
            self.http_session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(self.config.username, self.config.password))
            async with self.http_session.get(f"{self.http_url}/asterisk/info") as response:
                if response.status != 200:
                    raise ConnectionError(f"Failed to connect to ARI HTTP endpoint. Status: {response.status}")
                logger.info("Successfully connected to ARI HTTP endpoint.")

            # Then, connect to the WebSocket
            self.websocket = await websockets.connect(self.ws_url)
            self.running = True
            logger.info("Successfully connected to ARI WebSocket.")
        except Exception as e:
            logger.error("Failed to connect to ARI, will retry...", error=str(e), exc_info=True)
            if self.http_session and not self.http_session.closed:
                await self.http_session.close()
            raise

    async def start_listening(self):
        """Start listening for events from the ARI WebSocket."""
        if not self.running or not self.websocket:
            logger.error("Cannot start listening, client is not connected.")
            return

        logger.info("Starting ARI event listener.")
        try:
            async for message in self.websocket:
                try:
                    event_data = json.loads(message)
                    event_type = event_data.get("type")
                    if event_type and event_type in self.event_handlers:
                        for handler in self.event_handlers[event_type]:
                            asyncio.create_task(handler(event_data))
                except json.JSONDecodeError:
                    logger.warning("Failed to decode ARI event JSON", message=message)
        except websockets.exceptions.ConnectionClosed:
            logger.warning("ARI WebSocket connection closed.")
            self.running = False
        except Exception as e:
            logger.error("An error occurred in the ARI listener", exc_info=True)
            self.running = False

    async def disconnect(self):
        """Disconnect from the ARI WebSocket and close the HTTP session."""
        self.running = False
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        if self.http_session and not self.http_session.closed:
            await self.http_session.close()
            self.http_session = None
        logger.info("Disconnected from ARI.")

    def add_event_handler(self, event_type: str, handler: Callable):
        """Register a handler for a specific ARI event type."""
        if event_type not in self.event_handlers:
            self.event_handlers[event_type] = []
        self.event_handlers[event_type].append(handler)
        logger.debug("Added event handler", event_type=event_type, handler=handler.__name__)

    async def send_command(self, method: str, resource: str, data: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a command to the ARI HTTP endpoint."""
        url = f"{self.http_url}/{resource}"
        try:
            async with self.http_session.request(method, url, json=data, params=params) as response:
                if response.status >= 400:
                    reason = await response.text()
                    logger.error("ARI command failed", method=method, url=url, status=response.status, reason=reason)
                    # To prevent crashing on expected 404s for hangup, we return a dict
                    return {"status": response.status, "reason": reason}
                if response.status == 204: # No Content
                    return {"status": response.status}
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error("ARI HTTP request failed", exc_info=True)
            return {"status": 500, "reason": str(e)}

    async def answer_channel(self, channel_id: str):
        """Answer a channel."""
        logger.info("Answering channel", channel_id=channel_id)
        await self.send_command("POST", f"channels/{channel_id}/answer")

    async def hangup_channel(self, channel_id: str):
        """Hang up a channel."""
        logger.info("Hanging up channel", channel_id=channel_id)
        await self.send_command("DELETE", f"channels/{channel_id}")

    async def play_media(self, channel_id: str, media_uri: str) -> Optional[Dict[str, Any]]:
        """Play media on a channel."""
        logger.info("Playing media on channel", channel_id=channel_id, media_uri=media_uri)
        return await self.send_command("POST", f"channels/{channel_id}/play", data={"media": media_uri})

    async def create_bridge(self) -> Optional[Dict[str, Any]]:
        """Create a new bridge."""
        logger.info("Creating a new bridge")
        return await self.send_command("POST", "bridges")

    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str):
        """Add a channel to a bridge."""
        logger.info("Adding channel to bridge", channel_id=channel_id, bridge_id=bridge_id)
        await self.send_command("POST", f"bridges/{bridge_id}/addChannel", data={"channel": channel_id})

    async def destroy_bridge(self, bridge_id: str):
        """Destroy a bridge."""
        logger.info("Destroying bridge", bridge_id=bridge_id)
        await self.send_command("DELETE", f"bridges/{bridge_id}")

    async def list_channels(self) -> List[Dict[str, Any]]:
        """List all active channels."""
        logger.debug("Listing all channels")
        return await self.send_command("GET", "channels")

    async def list_bridges(self) -> List[Dict[str, Any]]:
        """List all active bridges."""
        logger.debug("Listing all bridges")
        return await self.send_command("GET", "bridges")

    async def create_external_media_channel(self, app_name: str, external_host: str) -> Optional[Dict[str, Any]]:
        """Create an external media channel for streaming."""
        logger.info("Creating externalMedia channel...", external_host=external_host)
        return await self.send_command(
            "POST",
            "channels/externalMedia",
            params={
                "app": app_name,
                "external_host": external_host,
                "format": "slin16"
            }
        )
