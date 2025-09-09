import asyncio
import json
import websockets
from typing import Callable, Optional

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

    async def connect(self, deepgram_config: DeepgramConfig, llm_config: LLMConfig):
        ws_url = f"wss://api.deepgram.com/v1/agent?encoding=linear16&sample_rate=8000"
        headers = {'Authorization': f'Token {deepgram_config.api_key}'}

        try:
            logger.info("Connecting to Deepgram Voice Agent...")
            self.websocket = await websockets.connect(ws_url, extra_headers=headers)
            logger.info("✅ Successfully connected to Deepgram Voice Agent.")

            # Send initial configuration
            await self._configure_agent(deepgram_config, llm_config)

            asyncio.create_task(self._receive_loop())
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

        except Exception:
            logger.error("Failed to connect to Deepgram Voice Agent", exc_info=True)
            if self._keep_alive_task:
                self._keep_alive_task.cancel()
            raise

    async def _configure_agent(self, deepgram_config: DeepgramConfig, llm_config: LLMConfig):
        settings = {
            "type": "Settings",
            "agent": {
                "listen": {
                    "provider": {
                        "type": "deepgram",
                        "model": deepgram_config.model,
                    }
                },
                "think": {
                    "provider": {
                        "type": "open_ai",
                        "model": llm_config.model,
                        "api_key": llm_config.api_key
                    },
                    "prompt": llm_config.prompt,
                },
                "speak": {
                    "provider": {
                        "type": "deepgram",
                        "model": deepgram_config.tts_model
                    }
                },
                "greeting": llm_config.greeting
            }
        }
        await self.websocket.send(json.dumps(settings))

    async def _keep_alive(self):
        try:
            while True:
                if self.websocket and self.websocket.open:
                    await self.websocket.send(json.dumps({"type": "KeepAlive"}))
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Keep-alive task could not send message, connection is closed.")
        except Exception:
            logger.error("Error in keep-alive task", exc_info=True)

    async def _receive_loop(self):
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                await self.event_handler(json.loads(message))
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Deepgram Voice Agent connection closed", reason=str(e))
        except Exception:
            logger.error("Error receiving events from Deepgram Voice Agent", exc_info=True)

    async def disconnect(self):
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Deepgram Voice Agent.")

    async def send_audio(self, audio_chunk: bytes):
        if self.websocket and self.websocket.open:
            try:
                await self.websocket.send(audio_chunk)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Attempted to send audio on a closed Deepgram Agent connection.")
