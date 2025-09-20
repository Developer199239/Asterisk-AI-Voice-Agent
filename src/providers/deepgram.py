import asyncio
import json
import websockets
from typing import Callable, Optional, List, Dict, Any
import websockets.exceptions

from structlog import get_logger
from ..config import LLMConfig
from .base import AIProviderInterface

logger = get_logger(__name__)

class DeepgramProvider(AIProviderInterface):
    def __init__(self, config: Dict[str, Any], llm_config: LLMConfig, on_event: Callable[[Dict[str, Any]], None]):
        super().__init__(on_event)
        self.config = config
        self.llm_config = llm_config
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._is_audio_flowing = False
        self.request_id: Optional[str] = None

    @property
    def supported_codecs(self) -> List[str]:
        return ["ulaw"]

    async def start_session(self, call_id: str):
        ws_url = f"wss://agent.deepgram.com/v1/agent/converse"
        headers = {'Authorization': f'Token {self.config.api_key}'}

        try:
            logger.info("Connecting to Deepgram Voice Agent...", url=ws_url)
            self.websocket = await websockets.connect(ws_url, extra_headers=list(headers.items()))
            logger.info("✅ Successfully connected to Deepgram Voice Agent.")

            await self._configure_agent()

            asyncio.create_task(self._receive_loop())
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

        except Exception as e:
            logger.error("Failed to connect to Deepgram Voice Agent", exc_info=True)
            if self._keep_alive_task:
                self._keep_alive_task.cancel()
            raise

    async def _configure_agent(self):
        """Builds and sends the V1 Settings message to the Deepgram Voice Agent."""
        settings = {
            "type": "Settings",
            "audio": {
                "input": { "encoding": "mulaw", "sample_rate": 8000 },
                "output": { "encoding": "mulaw", "sample_rate": 8000, "container": "none" }
            },
            "agent": {
                "greeting": "Hello, I am an AI Assistant for Jugaar LLC. How can I help you today.",
                "language": "en",
                "listen": { "provider": { "type": "deepgram", "model": self.config.model, "smart_format": True } },
                "think": { "provider": { "type": "open_ai", "model": self.llm_config.model }, "prompt": self.llm_config.prompt },
                "speak": { "provider": { "type": "deepgram", "model": self.config.tts_model } }
            }
        }
        await self.websocket.send(json.dumps(settings))
        logger.info("Deepgram agent configured.")

    async def send_audio(self, audio_chunk: bytes):
        if self.websocket:
            try:
                self._is_audio_flowing = True
                await self.websocket.send(audio_chunk)
            except websockets.exceptions.ConnectionClosed as e:
                logger.debug("Could not send audio packet: Connection closed.", code=e.code, reason=e.reason)
            except Exception:
                logger.error("An unexpected error occurred while sending audio chunk", exc_info=True)

    async def stop_session(self):
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Deepgram Voice Agent.")

    async def _keep_alive(self):
        while True:
            try:
                await asyncio.sleep(10)
                if self.websocket and not self.websocket.closed:
                    if not self._is_audio_flowing:
                        await self.websocket.send(json.dumps({"type": "KeepAlive"}))
                    self._is_audio_flowing = False
                else:
                    break
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Error in keep-alive task", exc_info=True)
                break

    async def _receive_loop(self):
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                if isinstance(message, str):
                    try:
                        event_data = json.loads(message)
                        if self.on_event:
                            await self.on_event(event_data)
                    except json.JSONDecodeError:
                        logger.error("Failed to parse JSON message from Deepgram", message=message)
                elif isinstance(message, bytes):
                    audio_event = {'type': 'AgentAudio', 'data': message}
                    if self.on_event:
                        await self.on_event(audio_event)
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Deepgram Voice Agent connection closed", reason=str(e))
        except Exception:
            logger.error("Error receiving events from Deepgram Voice Agent", exc_info=True)

    async def speak(self, text: str):
        if not text or not self.websocket:
            return
        inject_message = {"type": "InjectAgentMessage", "message": text}
        try:
            await self.websocket.send(json.dumps(inject_message))
        except websockets.exceptions.ConnectionClosed as e:
            logger.error("Failed to send inject agent message: Connection is closed.", exc_info=True, code=e.code, reason=e.reason)
    
    def get_provider_info(self) -> Dict[str, Any]:
        """Get information about the provider and its capabilities."""
        return {
            "name": "DeepgramProvider",
            "type": "cloud",
            "supported_codecs": self.supported_codecs,
            "model": self.config.model,
            "tts_model": self.config.tts_model
        }
    
    def is_ready(self) -> bool:
        """Check if the provider is ready to process audio."""
        return self.websocket is not None and self.event_handler is not None
