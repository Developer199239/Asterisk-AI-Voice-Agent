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
        self._sender_task: Optional[asyncio.Task] = None
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._active_call_id: Optional[str] = None
        self.input_mode: str = 'mulaw8k'  # or 'pcm16_8k'

    @property
    def supported_codecs(self) -> List[str]:
        return ["ulaw"]

    async def _connect_ws(self):
        # Use conservative client settings; server will drive pings if needed
        return await websockets.connect(
            self.ws_url,
            ping_interval=None,         # disable client pings to avoid false timeouts
            ping_timeout=None,
            close_timeout=10,
            max_size=None
        )

    async def _reconnect(self):
        backoff = [1, 2, 5, 10]
        for delay in backoff + [10, 10, 10]:
            try:
                logger.info("Reconnecting to Local AI Server...", url=self.ws_url, delay=delay)
                self.websocket = await self._connect_ws()
                logger.info("✅ Reconnected to Local AI Server.")
                # Restart listener and sender loops
                if self._listener_task is None or self._listener_task.done():
                    self._listener_task = asyncio.create_task(self._receive_loop())
                if self._sender_task is None or self._sender_task.done():
                    self._sender_task = asyncio.create_task(self._send_loop())
                return True
            except Exception:
                logger.warning("Reconnect attempt failed", exc_info=True)
                await asyncio.sleep(delay)
        return False

    async def start_session(self, call_id: str):
        try:
            logger.info("Connecting to Local AI Server...", url=self.ws_url)
            self.websocket = await self._connect_ws()
            logger.info("✅ Successfully connected to Local AI Server.")
            self._active_call_id = call_id
            self._listener_task = asyncio.create_task(self._receive_loop())
            self._sender_task = asyncio.create_task(self._send_loop())
        except Exception:
            logger.error("Failed to connect to Local AI Server", exc_info=True)
            raise

    async def send_audio(self, audio_chunk: bytes):
        # Enqueue for sender loop; drop if queue is full to avoid backpressure explosions
        try:
            await self._send_queue.put(audio_chunk)
        except Exception:
            logger.debug("Send queue put failed", exc_info=True)

    async def _send_loop(self):
        BATCH_MS = 20  # send cadence ~50fps
        while True:
            try:
                # Wait for first chunk
                chunk = await self._send_queue.get()
                if chunk is None:
                    continue
                # Coalesce additional chunks available now (non-blocking)
                batch = [chunk]
                try:
                    while True:
                        batch.append(self._send_queue.get_nowait())
                except asyncio.QueueEmpty:
                    pass

                # Convert and send one aggregated message
                import audioop
                # Concatenate at 8k then resample once
                if self.input_mode == 'pcm16_8k':
                    pcm8k = b"".join(batch)
                else:
                    pcm8k = b"".join(audioop.ulaw2lin(b, 2) for b in batch)
                pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                msg = json.dumps({"type": "audio", "data": base64.b64encode(pcm16k).decode('utf-8')})
                try:
                    await self.websocket.send(msg)
                    logger.debug("WS batch send", frames=len(batch), in_bytes=sum(len(b) for b in batch), pcm8k=len(pcm8k), pcm16k=len(pcm16k))
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning("WebSocket closed during send, attempting reconnect", code=getattr(e, 'code', None), reason=getattr(e, 'reason', None))
                    ok = await self._reconnect()
                    if ok:
                        try:
                            await self.websocket.send(msg)
                            logger.debug("WS resend after reconnect ok", frames=len(batch))
                        except Exception:
                            logger.error("WS resend failed after reconnect", exc_info=True)
                except Exception:
                    logger.error("WS send error", exc_info=True)
                # Pace the loop
                await asyncio.sleep(BATCH_MS / 1000.0)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Sender loop error", exc_info=True)
                await asyncio.sleep(0.1)

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
