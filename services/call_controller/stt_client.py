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

    async def connect(self):
        try:
            headers = {'Authorization': f'Token {self.config.api_key}'}
            ws_url = f"wss://api.deepgram.com/v1/listen?model={self.config.model}&language={self.config.language}&encoding=linear16&sample_rate=8000"
            
            logger.info("Connecting to Deepgram...")
            self.websocket = await websockets.connect(ws_url, additional_headers=headers)
            logger.info("✅ Successfully connected to Deepgram.")
            asyncio.create_task(self._receive_loop())
        except Exception as e:
            logger.error("Failed to connect to Deepgram", error=str(e))
            raise

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
        if self.websocket:
            await self.websocket.close()
            logger.info("Disconnected from Deepgram.")

    async def send_audio(self, audio_chunk: bytes):
        if self.websocket:
            try:
                await self.websocket.send(audio_chunk)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("Attempted to send audio on a closed connection.")
