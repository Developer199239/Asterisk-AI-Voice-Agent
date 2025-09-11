"""
A new, simplified Asterisk ARI WebSocket Client.
Focuses on robust connection and logging to debug startup issues.
"""

import asyncio
import json
import os
import tempfile
import wave
import audioop
from typing import Dict, Any, Optional, Callable, List
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import websockets
import structlog

from websockets.exceptions import ConnectionClosed
from websockets.legacy.client import WebSocketClientProtocol

from .config import AsteriskConfig
from .logging_config import get_logger

logger = get_logger(__name__)

class ARIClient:
    """A client for interacting with the Asterisk REST Interface (ARI)."""

    def __init__(self, username: str, password: str, base_url: str, app_name: str):
        self.username = username
        self.password = password
        self.http_url = base_url
        ws_host = base_url.replace("http://", "").split('/')[0]
        self.ws_url = f"ws://{ws_host}/ari/events?api_key={username}:{password}&app={app_name}"
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.http_session: Optional[aiohttp.ClientSession] = None
        self.running = False
        self.event_handlers: Dict[str, List[Callable]] = {}
        self.active_snoops: Dict[str, str] = {}  # channel_id -> snoop_channel_id
        self.audio_frame_handler: Optional[Callable] = None

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
            self.http_session = aiohttp.ClientSession(auth=aiohttp.BasicAuth(self.username, self.password))
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
                    
                    # Handle audio frames from snoop channels
                    if event_type == "ChannelAudioFrame":
                        channel = event_data.get('channel', {})
                        channel_id = channel.get('id')
                        if channel_id in self.active_snoops.values():
                            asyncio.create_task(self._on_audio_frame(channel, event_data))
                    
                    # Handle other events
                    if event_type and event_type in self.event_handlers:
                        for handler in self.event_handlers[event_type]:
                            asyncio.create_task(handler(event_data))
                except json.JSONDecodeError:
                    logger.warning("Failed to decode ARI event JSON", message=message)
        except ConnectionClosed:
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

    async def handle_audio_frame(self, event_data: dict, audio_handler: Callable):
        """Handle audio frames from snoop channels."""
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        audio_data = event_data.get('audio', {})
        
        if channel_id and audio_data:
            # Extract the raw audio data
            audio_payload = audio_data.get('data')
            if audio_payload:
                # Convert from base64 if needed, or handle as raw bytes
                import base64
                try:
                    raw_audio = base64.b64decode(audio_payload)
                    await audio_handler(channel_id, raw_audio)
                except Exception as e:
                    logger.error("Error processing audio frame", error=str(e))

    async def handle_dtmf_received(self, event_data: dict, dtmf_handler: Callable):
        """Handle DTMF events from snoop channels."""
        channel = event_data.get('channel', {})
        channel_id = channel.get('id')
        digit = event_data.get('digit')
        
        if channel_id and digit:
            await dtmf_handler(channel_id, digit)

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
        # We add a check here. If the command fails with a 404, we log it
        # as a debug message instead of an error, as this can happen in race
        # conditions during cleanup and is not necessarily a critical failure.
        response = await self.send_command("DELETE", f"channels/{channel_id}")
        if response and response.get("status") == 404:
            logger.debug("Channel hangup failed (404), likely already hung up.", channel_id=channel_id)

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

    async def get_app(self, app_name: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific ARI application."""
        logger.debug("Getting details for ARI app", app_name=app_name)
        return await self.send_command("GET", f"applications/{app_name}")

    async def start_audio_streaming(self, channel_id: str, app_name: str) -> Optional[str]:
        """Start audio streaming using snoop channel - replaces externalMedia logic."""
        try:
            # Create a unique ID for the snoop channel
            snoop_id = f"snoop_{channel_id}"

            # Command Asterisk to create the snoop channel
            snoop_channel = await self.create_snoop_channel(channel_id, app_name, snoop_id)
            
            if not snoop_channel or 'id' not in snoop_channel:
                logger.error("Failed to create snoop channel", channel_id=channel_id)
                return None

            # Start snooping to capture audio frames
            await self.start_snoop(snoop_channel['id'], app_name)

            # Store the snoop channel mapping
            self.active_snoops[channel_id] = snoop_channel['id']
            logger.info(f"Snoop channel {snoop_channel['id']} created for {channel_id}")

            return snoop_channel['id']

        except Exception as e:
            logger.error(f"Failed to start audio streaming for {channel_id}: {e}")
            return None

    async def _on_audio_frame(self, channel, event):
        """Handles incoming raw audio frames from the snoop channel."""
        try:
            # Extract audio data from the event
            if 'frame' in event and 'data' in event['frame']:
                audio_data = event['frame']['data']
                
                # Forward to the registered audio frame handler
                if self.audio_frame_handler:
                    await self.audio_frame_handler(audio_data)
                else:
                    logger.debug(f"Received audio frame but no handler registered: {len(audio_data)} bytes")
            else:
                logger.debug("Received audio frame event without data")
                
        except Exception as e:
            logger.error(f"Error handling audio frame: {e}")

    def set_audio_frame_handler(self, handler: Callable):
        """Set the handler for incoming audio frames."""
        self.audio_frame_handler = handler

    async def play_audio_file(self, channel_id: str, file_path: str) -> bool:
        """Play an audio file to the specified channel with enhanced error handling."""
        try:
            import time
            start_time = time.time()
            
            # Enhanced file verification with detailed logging
            for attempt in range(15):  # Try up to 15 times (1.5 seconds total)
                if os.path.exists(file_path):
                    if os.access(file_path, os.R_OK):
                        file_size = os.path.getsize(file_path)
                        if file_size > 0:
                            logger.debug(f"File verified: {file_path} ({file_size} bytes) - attempt {attempt + 1}")
                            break
                        else:
                            logger.warning(f"File exists but is empty: {file_path} - attempt {attempt + 1}")
                    else:
                        logger.warning(f"File exists but not readable: {file_path} (permissions: {oct(os.stat(file_path).st_mode)[-3:]}) - attempt {attempt + 1}")
                else:
                    logger.warning(f"File not found: {file_path} - attempt {attempt + 1}")
                
                time.sleep(0.1)  # 100ms delay
            
            # Final verification
            if not os.path.exists(file_path):
                logger.error(f"Audio file not found after 15 attempts: {file_path}")
                return False
            
            if not os.access(file_path, os.R_OK):
                logger.error(f"Audio file not readable: {file_path} (permissions: {oct(os.stat(file_path).st_mode)[-3:]})")
                return False

            file_size = os.path.getsize(file_path)
            if file_size == 0:
                logger.error(f"Audio file is empty: {file_path}")
                return False

            # Set channel variable for debugging
            await self.send_command(
                "POST",
                f"channels/{channel_id}/variable",
                data={"variable": "AUDIO_FILE_PATH", "value": file_path}
            )
            
            # Use ARI to play the file
            result = await self.send_command(
                "POST",
                f"channels/{channel_id}/play",
                data={"media": f"sound:{file_path}"}
            )
            
            elapsed_time = (time.time() - start_time) * 1000  # milliseconds
            if result:
                logger.info(f"Playing audio file {file_path} ({file_size} bytes) on channel {channel_id} - took {elapsed_time:.1f}ms")
                return True
            else:
                logger.error(f"Failed to play audio file {file_path} after {elapsed_time:.1f}ms")
                return False
                
        except Exception as e:
            logger.error(f"Error playing audio file {file_path}: {e}")
            return False

    async def create_audio_file_from_ulaw(self, ulaw_data: bytes, sample_rate: int = 8000) -> str:
        """Convert ulaw audio data to a WAV file and return the file path."""
        try:
            # Convert ulaw to linear PCM
            pcm_data = audioop.ulaw2lin(ulaw_data, 2)  # 2 bytes per sample (16-bit)
            
            # Create timestamped filename for better debugging
            import time
            timestamp = int(time.time() * 1000)  # milliseconds
            filename = f"audio_{timestamp}_{len(pcm_data)}.wav"
            temp_file_path = f"/tmp/asterisk-audio/{filename}"
            
            # Write WAV file
            with wave.open(temp_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 2 bytes per sample (16-bit)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm_data)
            
            # Set proper permissions for Asterisk to read the file
            os.chmod(temp_file_path, 0o644)  # rw-r--r--
            
            # Force filesystem sync and verify file exists
            os.sync()  # Force filesystem sync
            
            # Wait and verify file is accessible
            for attempt in range(10):  # Try up to 10 times (1 second total)
                if os.path.exists(temp_file_path) and os.access(temp_file_path, os.R_OK):
                    file_size = os.path.getsize(temp_file_path)
                    if file_size > 0:
                        logger.debug(f"Created WAV file: {temp_file_path} ({file_size} bytes) - attempt {attempt + 1}")
                        return temp_file_path
                time.sleep(0.1)  # 100ms delay
            
            logger.error(f"Failed to create accessible WAV file after 10 attempts: {temp_file_path}")
            return ""
            
        except Exception as e:
            logger.error(f"Error creating audio file from ulaw: {e}")
            return ""

    async def cleanup_audio_file(self, file_path: str, delay: float = 5.0):
        """Clean up an audio file after a delay."""
        try:
            await asyncio.sleep(delay)
            if os.path.exists(file_path):
                os.unlink(file_path)
                logger.debug(f"Cleaned up audio file: {file_path}")
        except Exception as e:
            logger.error(f"Error cleaning up audio file {file_path}: {e}")

    async def create_snoop_channel(self, channel_id: str, app_name: str, snoop_id: str) -> Optional[Dict[str, Any]]:
        """Create a snoop channel to capture audio from the main channel."""
        logger.info("Creating snoop channel...", channel_id=channel_id, snoop_id=snoop_id)

        data = {
            "app": app_name,
            "spy": "in",  # Capture incoming audio from the channel
            "snoopId": snoop_id
        }

        return await self.send_command(
            "POST",
            f"channels/{channel_id}/snoop",
            data=data
        )

    async def start_snoop(self, snoop_channel_id: str, app_name: str) -> Optional[Dict[str, Any]]:
        """Start snooping on the snoop channel."""
        logger.info("Starting snoop...", snoop_channel_id=snoop_channel_id)
        data = {
            "spy": "in",  # Specify direction for snooping
            "app": app_name  # Required: Application name for snooped audio
        }
        return await self.send_command("POST", f"channels/{snoop_channel_id}/snoop", data=data)

    async def stop_audio_streaming(self, channel_id: str) -> bool:
        """Stop audio streaming and clean up snoop channel."""
        try:
            if channel_id in self.active_snoops:
                snoop_channel_id = self.active_snoops[channel_id]
                
                # Stop snooping
                await self.stop_snoop(snoop_channel_id)
                
                # Hang up the snoop channel
                await self.hangup_channel(snoop_channel_id)
                
                # Remove from active snoops
                del self.active_snoops[channel_id]
                
                logger.info(f"Stopped audio streaming for channel {channel_id}")
                return True
            else:
                logger.warning(f"No active snoop found for channel {channel_id}")
                return False
                
        except Exception as e:
            logger.error(f"Error stopping audio streaming for {channel_id}: {e}")
            return False

    async def stop_snoop(self, snoop_channel_id: str) -> Optional[Dict[str, Any]]:
        """Stop snooping on the snoop channel."""
        logger.info("Stopping snoop...", snoop_channel_id=snoop_channel_id)
        return await self.send_command("DELETE", f"channels/{snoop_channel_id}/snoop")

    async def create_external_media_channel(self, channel_id: str, app_name: str, external_host: str, external_port: int) -> Optional[Dict[str, Any]]:
        """Create an external media channel for bidirectional audio streaming."""
        logger.info("Creating external media channel...", channel_id=channel_id, external_host=external_host, external_port=external_port)
        
        data = {
            "app": app_name,
            "external_host": external_host,
            "external_port": external_port,
            "format": "ulaw"  # Use ulaw for compatibility
        }
        
        return await self.send_command("POST", f"channels/{channel_id}/externalMedia", data=data)

    async def create_bridge(self) -> Optional[Dict[str, Any]]:
        """Create a bridge for connecting channels."""
        logger.info("Creating bridge...")
        return await self.send_command("POST", "bridges")

    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str) -> Optional[Dict[str, Any]]:
        """Add a channel to a bridge."""
        logger.info("Adding channel to bridge...", bridge_id=bridge_id, channel_id=channel_id)
        return await self.send_command("POST", f"bridges/{bridge_id}/addChannel", data={"channel": channel_id})

    async def remove_channel_from_bridge(self, bridge_id: str, channel_id: str) -> Optional[Dict[str, Any]]:
        """Remove a channel from a bridge."""
        logger.info("Removing channel from bridge...", bridge_id=bridge_id, channel_id=channel_id)
        return await self.send_command("POST", f"bridges/{bridge_id}/removeChannel", data={"channel": channel_id})

    async def destroy_bridge(self, bridge_id: str) -> Optional[Dict[str, Any]]:
        """Destroy a bridge."""
        logger.info("Destroying bridge...", bridge_id=bridge_id)
        return await self.send_command("DELETE", f"bridges/{bridge_id}")
