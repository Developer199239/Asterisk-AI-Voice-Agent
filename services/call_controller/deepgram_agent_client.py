import asyncio
import json
import websockets
from typing import Callable, Optional
import websockets.exceptions

from structlog import get_logger
from shared.config import DeepgramConfig, LLMServiceConfig as LLMConfig

# Force git update by adding a comment
logger = get_logger(__name__)

class DeepgramAgentClient:
    def __init__(self, event_handler: Callable):
        self.event_handler = event_handler
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._is_audio_flowing = False
        self.request_id: Optional[str] = None

    async def connect(self, deepgram_config: DeepgramConfig, llm_config: LLMConfig):
        ws_url = f"wss://agent.deepgram.com/v1/agent/converse?encoding=linear16&sample_rate=16000"
        headers = {'Authorization': f'Token {deepgram_config.api_key}'}

        try:
            logger.info("Connecting to Deepgram Voice Agent...", url=ws_url)
            self.websocket = await websockets.connect(ws_url, additional_headers=headers)
            logger.info("✅ Successfully connected to Deepgram Voice Agent.")

            await self._configure_agent(deepgram_config, llm_config)

            asyncio.create_task(self._receive_loop())
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

        except Exception as e:
            logger.error("Failed to connect to Deepgram Voice Agent", exc_info=True)
            if self._keep_alive_task:
                self._keep_alive_task.cancel()
            raise

    async def _configure_agent(self, deepgram_config: DeepgramConfig, llm_config: LLMConfig):
        """Builds and sends the V1 Settings message to the Deepgram Voice Agent."""
        settings = {
            "type": "Settings",
            "audio": {
                "input": {
                    "encoding": "linear16",
                    "sample_rate": 16000
                },
                "output": {
                    "encoding": "linear16",
                    "sample_rate": 24000,
                    "container": "none"
                }
            },
            "agent": {
                "language": "en",
                "listen": {
                    "provider": {
                        "type": "deepgram",
                        "model": deepgram_config.model,
                        "smart_format": True
                    }
                },
                "think": {
                    "provider": {
                        "type": "open_ai",
                        "model": llm_config.model
                    },
                    "prompt": llm_config.prompt
                },
                "speak": {
                    "provider": {
                        "type": "deepgram",
                        "model": deepgram_config.tts_model
                    }
                }
            }
        }
        await self.websocket.send(json.dumps(settings))
        logger.debug("Sent agent settings", settings=settings)

    async def speak(self, text: str):
        """Send a speak command to the agent."""
        if not text:
            logger.warning("Speak command received with empty text.")
            return

        if not self.websocket:
            logger.warning("Speak command called but websocket is not connected.")
            return

        speak_message = {
            "type": "Speak",
            "text": text
        }
        
        try:
            await self.websocket.send(json.dumps(speak_message))
            logger.debug("Sent speak command", text=text)
        except websockets.exceptions.ConnectionClosed as e:
            logger.error("Failed to send speak command: Connection is closed.", exc_info=True, code=e.code, reason=e.reason)

    async def _keep_alive(self):
        """Sends a keep-alive message every 10 seconds to maintain the connection."""
        while True:
            try:
                await asyncio.sleep(10)
                # Use 'not self.websocket.closed' to check connection state
                if self.websocket and not self.websocket.closed:
                    if not self._is_audio_flowing:
                        await self.websocket.send(json.dumps({"type": "KeepAlive"}))
                        logger.debug("Sent KeepAlive message.")
                    self._is_audio_flowing = False
                else:
                    logger.warning("WebSocket is closed, stopping keep-alive.")
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Error in keep-alive task", exc_info=True)
                break

    async def _receive_loop(self):
        """Continuously listen for messages from the WebSocket."""
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                # Check if message is text (JSON) or binary (audio)
                if isinstance(message, str):
                    # Handle text messages (JSON events)
                    try:
                        event_data = json.loads(message)
                        # If this is the Welcome message, store the request_id
                        if event_data.get('type') == 'Welcome':
                            self.request_id = event_data.get('request_id')
                        
                        # Add the request_id to every event we pass to the handler
                        if self.request_id:
                            event_data['request_id'] = self.request_id

                        await self.event_handler(event_data)
                    except json.JSONDecodeError as e:
                        logger.error("Failed to parse JSON message from Deepgram", error=str(e), message=message)
                elif isinstance(message, bytes):
                    # Handle binary messages (audio data)
                    import base64
                    audio_b64 = base64.b64encode(message).decode('utf-8')
                    audio_event = {
                        'type': 'AgentAudio',
                        'data': audio_b64
                    }
                    
                    # Add the request_id if we have it
                    if self.request_id:
                        audio_event['request_id'] = self.request_id
                    
                    logger.debug("Received binary audio from Deepgram", size=len(message))
                    await self.event_handler(audio_event)
                else:
                    logger.warning("Received unknown message type from Deepgram", message_type=type(message))
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Deepgram Voice Agent connection closed", reason=str(e))
        except Exception:
            logger.error("Error receiving events from Deepgram Voice Agent", exc_info=True)

    async def disconnect(self):
        """Disconnects the WebSocket client."""
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Deepgram Voice Agent.")

    async def send_audio(self, audio_chunk: bytes):
        """Send an audio chunk through the WebSocket."""
        if self.websocket:
            try:
                logger.debug("Attempting to send audio chunk to Deepgram...", chunk_size=len(audio_chunk))
                self._is_audio_flowing = True
                
                # Deepgram Voice Agent expects audio as base64-encoded text in JSON format
                import base64
                audio_b64 = base64.b64encode(audio_chunk).decode('utf-8')
                audio_message = {
                    "type": "Audio",
                    "data": audio_b64
                }
                
                await self.websocket.send(json.dumps(audio_message))
                logger.debug("Successfully sent audio chunk.")
            except websockets.exceptions.ConnectionClosed as e:
                # This can happen normally at the end of a call.
                logger.debug("Could not send audio packet: Connection closed.", code=e.code, reason=e.reason)
            except Exception:
                logger.error("An unexpected error occurred while sending audio chunk", exc_info=True)
