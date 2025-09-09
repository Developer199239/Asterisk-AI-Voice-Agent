"""
Client for handling real-time transcription with a cloud provider (e.g., Deepgram).
"""

import asyncio
import json
import websockets
import structlog
from typing import Callable, Optional
import functools
from websockets.client import WebSocketClientProtocol

from shared.config import DeepgramConfig

logger = structlog.get_logger(__name__)

class STTClient:
    def __init__(self, config: DeepgramConfig, transcript_handler: Callable):
        self.config = config
        self.transcript_handler = transcript_handler
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._keep_alive_task: Optional[asyncio.Task] = None
        self._is_audio_flowing = False

    async def connect(self):
        try:
            headers = {'Authorization': f'Token {self.config.api_key}'}
            ws_url = f"wss://api.deepgram.com/v1/listen?model={self.config.model}&language={self.config.language}&encoding=linear16&sample_rate=8000"
            
            logger.info("Connecting to Deepgram...")
            self.websocket = await websockets.connect(ws_url, additional_headers=headers)
            logger.info("✅ Successfully connected to Deepgram.")
            
            # Start the receive loop and the keep-alive task
            asyncio.create_task(self._receive_loop())
            self._keep_alive_task = asyncio.create_task(self._keep_alive())

        except Exception as e:
            logger.error("Failed to connect to Deepgram", error=str(e))
            if self._keep_alive_task:
                self._keep_alive_task.cancel()
            raise

    async def _keep_alive(self):
        """Send a KeepAlive message every 10 seconds to maintain the connection."""
        try:
            while True:
                if self.websocket and not self._is_audio_flowing:
                    await self.websocket.send(json.dumps({"type": "KeepAlive"}))
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass # Task was cancelled, which is expected.
        except websockets.exceptions.ConnectionClosed:
            logger.warning("Keep-alive task could not send message, connection is closed.")
        except Exception as e:
            logger.error("Error in keep-alive task", exc_info=True)

    async def _receive_loop(self):
        if not self.websocket:
            return

        try:
            async for message in self.websocket:
                await self.transcript_handler(message)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Deepgram connection closed.")
        except Exception as e:
            logger.error("Error receiving transcripts", exc_info=True)

    async def disconnect(self):
        if self._keep_alive_task:
            self._keep_alive_task.cancel()
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Deepgram.")

    async def send_audio(self, audio_chunk: bytes):
        if self.websocket:
            try:
                if not self._is_audio_flowing:
                    self._is_audio_flowing = True # Stop sending KeepAlives once audio starts
                await self.websocket.send(audio_chunk)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Attempted to send audio on a closed connection.")
