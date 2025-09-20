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
        self.input_mode: str = 'mulaw8k'  # or 'pcm16_8k' or 'pcm16_16k'
        self._pending_tts_responses: Dict[str, asyncio.Future] = {}  # Track pending TTS responses

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

    async def initialize(self):
        """Initialize persistent connection to Local AI Server."""
        try:
            if self.websocket and not self.websocket.closed:
                logger.debug("WebSocket already connected, skipping initialization")
                return
            
            logger.info("Initializing connection to Local AI Server...", url=self.ws_url)
            self.websocket = await self._connect_ws()
            logger.info("✅ Successfully connected to Local AI Server.")
            
            # Start tasks only if not already running
            if not self._listener_task or self._listener_task.done():
                self._listener_task = asyncio.create_task(self._receive_loop())
            if not self._sender_task or self._sender_task.done():
                self._sender_task = asyncio.create_task(self._send_loop())
        except Exception:
            logger.error("Failed to initialize connection to Local AI Server", exc_info=True)
            raise

    async def start_session(self, call_id: str):
        try:
            # Check if already connected
            if self.websocket and not self.websocket.closed:
                logger.debug("WebSocket already connected, reusing connection", call_id=call_id)
                self._active_call_id = call_id
                return
            
            # If not connected, initialize first
            await self.initialize()
            self._active_call_id = call_id
        except Exception:
            logger.error("Failed to start session", call_id=call_id, exc_info=True)
            raise

    async def send_audio(self, audio_chunk: bytes):
        """Send audio chunk to Local AI Server for STT processing."""
        try:
            logger.info("🎵 PROVIDER INPUT - Sending to Local AI Server",
                         bytes=len(audio_chunk),
                         queue_size=self._send_queue.qsize(),
                         input_mode=self.input_mode)
            
            # Enqueue for sender loop; drop if queue is full to avoid backpressure explosions
            await self._send_queue.put(audio_chunk)
            
        except Exception as e:
            logger.error("Failed to enqueue audio for Local AI Server", 
                         error=str(e), bytes=len(audio_chunk), exc_info=True)

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
                # Handle different input modes
                if self.input_mode == 'pcm16_16k':
                    # Already 16kHz PCM, just concatenate
                    pcm16k = b"".join(batch)
                elif self.input_mode == 'pcm16_8k':
                    # 8kHz PCM, resample to 16kHz
                    pcm8k = b"".join(batch)
                    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                else:
                    # µ-law 8kHz, convert to PCM then resample
                    pcm8k = b"".join(audioop.ulaw2lin(b, 2) for b in batch)
                    pcm16k, _ = audioop.ratecv(pcm8k, 2, 1, 8000, 16000, None)
                
                # Process audio batch for STT
                total_bytes = sum(len(b) for b in batch)
                logger.info("🔄 PROVIDER BATCH - Processing for STT",
                             frames=len(batch),
                             total_bytes=total_bytes,
                             input_mode=self.input_mode)
                
                msg = json.dumps({
                    "type": "audio", 
                    "data": base64.b64encode(pcm16k).decode('utf-8'),
                    "rate": 16000,
                    "format": "pcm16le"
                })
                try:
                    await self.websocket.send(msg)
                    logger.debug("WebSocket batch send successful", 
                                 frames=len(batch), 
                                 in_bytes=total_bytes)
                except websockets.exceptions.ConnectionClosed as e:
                    logger.warning("WebSocket closed during send, attempting reconnect", 
                                   code=getattr(e, 'code', None), 
                                   reason=getattr(e, 'reason', None))
                    ok = await self._reconnect()
                    if ok:
                        try:
                            await self.websocket.send(msg)
                            logger.debug("WebSocket resend after reconnect successful", frames=len(batch))
                        except Exception as e:
                            logger.error("WebSocket resend failed after reconnect", error=str(e), exc_info=True)
                except Exception as e:
                    logger.error("WebSocket send error", error=str(e), exc_info=True)
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
        # DON'T close the WebSocket - keep it alive for reuse
        # if self.websocket:
        #     await self.websocket.close()
        #     logger.info("Disconnected from Local AI Server.")
        
        # Just clear the active call ID
        self._active_call_id = None
        logger.info("Provider session stopped, WebSocket connection maintained.")

    async def _receive_loop(self):
        if not self.websocket:
            return
        try:
            async for message in self.websocket:
                # Handle binary messages (raw audio)
                if isinstance(message, bytes):
                    audio_event = {'type': 'AgentAudio', 'data': message, 'call_id': self._active_call_id}
                    if self.on_event:
                        await self.on_event(audio_event)
                # Handle JSON messages (TTS responses, etc.)
                elif isinstance(message, str):
                    try:
                        data = json.loads(message)
                        # Handle TTS responses
                        if data.get("type") == "tts_response":
                            # Find the pending TTS response and complete it
                            text = data.get("text", "")
                            if text in self._pending_tts_responses:
                                future = self._pending_tts_responses.pop(text)
                                if not future.done():
                                    future.set_result(data)
                                    logger.info("TTS response received and delivered", text=text[:50])
                                else:
                                    logger.warning("TTS response received but future already completed", text=text[:50])
                            else:
                                logger.warning("TTS response received but no pending request found", text=text[:50])
                        else:
                            logger.debug("Received JSON message from Local AI Server", message=data)
                    except json.JSONDecodeError:
                        logger.warning("Received non-JSON string message from Local AI Server", message=message)
                else:
                    logger.warning("Received unknown message type from Local AI Server", message_type=type(message))
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Local AI Server connection closed", reason=str(e))
        except Exception:
            logger.error("Error receiving events from Local AI Server", exc_info=True)

    async def speak(self, text: str):
        # This provider works by streaming STT->LLM->TTS on the server side.
        # Direct speech injection is not the primary mode of operation.
        logger.warning("Direct 'speak' method not implemented for this provider. Use the streaming pipeline.")
    
    async def text_to_speech(self, text: str) -> Optional[bytes]:
        """Generate TTS audio for the given text."""
        try:
            if not self.websocket or self.websocket.closed:
                logger.error("WebSocket not connected for TTS")
                return None
            
            # Send TTS request to Local AI Server
            tts_message = {
                "type": "tts_request",
                "text": text,
                "call_id": self._active_call_id or "greeting"
            }
            
            await self.websocket.send(json.dumps(tts_message))
            logger.info("Sent TTS request to Local AI Server", text=text[:50] + "..." if len(text) > 50 else text)
            
            # Wait for TTS response using a future-based approach
            response_future = asyncio.Future()
            self._pending_tts_responses[text] = response_future
            
            try:
                # Wait for response with timeout
                response_data = await asyncio.wait_for(response_future, timeout=10.0)
                
                if response_data.get("type") == "tts_response" and response_data.get("audio_data"):
                    # Decode base64 audio data
                    audio_data = base64.b64decode(response_data["audio_data"])
                    logger.info("Received TTS audio data", size=len(audio_data))
                    return audio_data
                else:
                    logger.warning("Unexpected TTS response format", response=response_data)
                    return None
                    
            except asyncio.TimeoutError:
                logger.error("TTS request timed out")
                return None
            finally:
                # Clean up the pending response
                self._pending_tts_responses.pop(text, None)
                
        except Exception as e:
            logger.error("Failed to generate TTS", text=text, error=str(e), exc_info=True)
            return None
    
    def get_provider_info(self) -> Dict[str, Any]:
        return {
            "name": "LocalProvider",
            "type": "local_stream",
            "supported_codecs": self.supported_codecs,
        }
    
    def is_ready(self) -> bool:
        return self.websocket is not None and not self.websocket.closed
