import asyncio
import base64
import json
from typing import Callable, Optional, List, Dict, Any
import websockets.exceptions

from structlog import get_logger

from ..config import LocalProviderConfig
from .base import AIProviderInterface

logger = get_logger(__name__)

class LocalProvider(AIProviderInterface):
    """
    AI Provider that connects to the external Local AI Server via WebSockets.
    """
    def __init__(self, config: LocalProviderConfig, on_event: Callable[[Dict[str, Any]], None]):
        super().__init__(on_event)
        self.config = config
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self.ws_url = "ws://127.0.0.1:8765"
        self._listener_task: Optional[asyncio.Task] = None
        self._active_call_id: Optional[str] = None
        self.input_mode: str = 'mulaw8k'  # or 'pcm16_8k'

    @property
    def supported_codecs(self) -> List[str]:
        return ["ulaw"]

    async def start_session(self, call_id: str):
        try:
            logger.info("Connecting to Local AI Server...", url=self.ws_url)
            self.websocket = await websockets.connect(self.ws_url)
            logger.info("✅ Successfully connected to Local AI Server.")
            self._active_call_id = call_id
            self._listener_task = asyncio.create_task(self._receive_loop())
        except Exception as e:
            logger.error("Failed to connect to Local AI Server", exc_info=True)
            raise

    async def send_audio(self, audio_chunk: bytes):
        if self.websocket:
            try:
                # Convert upstream to PCM16@16000 for the local server STT
                import audioop
                if self.input_mode == 'pcm16_8k':
                    pcm8k = audio_chunk
                else:
                    pcm8k = audioop.ulaw2lin(audio_chunk, 2)
                pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)

                audio_message = {
                    "type": "audio",
                    "data": base64.b64encode(pcm16k).decode('utf-8')
                }
                await self.websocket.send(json.dumps(audio_message))
                logger.info("Sent converted audio to Local AI Server for STT→LLM→TTS processing", 
                           in_bytes=len(audio_chunk), out_bytes=len(pcm16k))
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning("WebSocket connection closed during audio send", code=e.code, reason=e.reason)
                raise
            except Exception as e:
                logger.error("Error converting/sending audio to Local AI Server", error=str(e), exc_info=True)
                raise

    def set_input_mode(self, mode: str):
        # mode: 'mulaw8k' or 'pcm16_8k'
        self.input_mode = mode

    async def play_initial_greeting(self, call_id: str):
        """Play an initial greeting message to the caller."""
        try:
            # Send a greeting message to the local AI server
            greeting_message = {
                "type": "greeting",
                "call_id": call_id,
                "message": "Hello! I'm your AI assistant. How can I help you today?"
            }
            
            if self.websocket:
                await self.websocket.send(json.dumps(greeting_message))
                logger.info("Sent greeting message to Local AI Server", call_id=call_id)
            else:
                logger.warning("Cannot send greeting: WebSocket not connected", call_id=call_id)
        except Exception as e:
            logger.error("Failed to send greeting message", call_id=call_id, error=str(e), exc_info=True)

    async def stop_session(self):
        if self._listener_task:
            self._listener_task.cancel()
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Local AI Server.")

    async def _receive_loop(self):
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                # The local AI server will send back raw audio bytes for TTS
                if isinstance(message, bytes):
                    audio_event = {'type': 'AgentAudio', 'data': message, 'call_id': self._active_call_id}
                    if self.on_event:
                        await self.on_event(audio_event)
                else:
                    logger.warning("Received non-binary message from Local AI Server", message=message)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Local AI Server connection closed", reason=str(e))
        except Exception:
            logger.error("Error receiving events from Local AI Server", exc_info=True)

    async def speak(self, text: str):
        # This provider works by streaming STT->LLM->TTS on the server side.
        # Direct speech injection is not the primary mode of operation.
        logger.warning("Direct 'speak' method not implemented for this provider. Use the streaming pipeline.")
    
    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "name": "LocalProvider",
            "type": "local_stream",
            "supported_codecs": self.supported_codecs,
        }
    
    def is_ready(self) -> bool:
        return self.websocket is not None and not self.websocket.closed
