"""
Client for handling real-time transcription with a cloud provider (e.g., Deepgram).
"""

import asyncio
import websockets
import structlog
from typing import Callable, Optional

from shared.config import DeepgramConfig

logger = structlog.get_logger(__name__)

class STTClient:
    def __init__(self, config: DeepgramConfig, on_transcript: Callable):
        self.config = config
        self.on_transcript = on_transcript
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None

    async def connect(self):
        """Connect to the STT provider's WebSocket."""
        uri = f"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=8000&channels=1"
        headers = {'Authorization': f'Token {self.config.api_key}'}
        try:
            self.websocket = await websockets.connect(uri, extra_headers=headers)
            logger.info("Successfully connected to STT WebSocket.")
        except Exception as e:
            logger.error("Failed to connect to STT WebSocket", exc_info=True)
            raise

    async def send_audio(self, audio_chunk: bytes):
        """Send a chunk of audio data to the STT provider."""
        if self.websocket:
            await self.websocket.send(audio_chunk)

    async def receive_transcripts(self):
        """Listen for and process incoming transcripts."""
        while self.websocket:
            try:
                message = await self.websocket.recv()
                await self.on_transcript(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning("STT WebSocket connection closed.")
                break
            except Exception as e:
                logger.error("Error receiving transcript", exc_info=True)
                break

    async def disconnect(self):
        """Disconnect from the STT WebSocket."""
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
            logger.info("Disconnected from STT WebSocket.")
