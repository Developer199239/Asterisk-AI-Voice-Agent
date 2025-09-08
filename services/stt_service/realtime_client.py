"""
OpenAI Realtime API Client

This module provides a client for interacting with OpenAI's Realtime API
for streaming speech-to-text, text-to-speech, and large language model operations.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed, WebSocketException
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class RealtimeMessageType(Enum):
    """OpenAI Realtime API message types."""
    # Session management
    SESSION_UPDATE = "session.update"
    SESSION_CLEAR = "session.clear"
    
    # Input messages
    INPUT_AUDIO_BUFFER_APPEND = "input_audio_buffer.append"
    INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
    CONVERSATION_ITEM_CREATE = "conversation.item.create"
    RESPONSE_CREATE = "response.create"
    RESPONSE_CANCEL = "response.cancel"
    
    # Output messages
    SESSION_CREATED = "session.created"
    SESSION_UPDATED = "session.updated"
    SESSION_CLEARED = "session.cleared"
    INPUT_AUDIO_BUFFER_SPOKEN = "input_audio_buffer.speech_started"
    INPUT_AUDIO_BUFFER_SPEECH_ENDED = "input_audio_buffer.speech_ended"
    CONVERSATION_ITEM_CREATED = "conversation.item.created"
    CONVERSATION_ITEM_UPDATED = "conversation.item.updated"
    RESPONSE_AUDIO_TRANSCRIPT_DELTA = "response.audio_transcript.delta"
    RESPONSE_AUDIO_DELTA = "response.audio.delta"
    RESPONSE_DONE = "response.done"
    RESPONSE_CANCELLED = "response.cancelled"
    ERROR = "error"


class VoiceType(Enum):
    """Available voice types for TTS."""
    ALLOY = "alloy"
    ECHO = "echo"
    FABLE = "fable"
    ONYX = "onyx"
    NOVA = "nova"
    SHIMMER = "shimmer"


@dataclass
class RealtimeConfig:
    """Configuration for the Realtime API client."""
    api_key: str
    model: str = "gpt-4o-realtime-preview"
    voice: VoiceType = VoiceType.ALLOY
    language: str = "en"
    base_url: str = "wss://api.openai.com/v1/realtime"
    instructions: str = "You are a helpful AI assistant for Jugaar LLC."
    temperature: float = 0.8
    max_response_tokens: int = 4096
    input_audio_format: str = "pcm16"
    output_audio_format: str = "pcm16"
    sample_rate: int = 24000
    channels: int = 1
    vad_threshold: float = 0.5
    silence_duration_ms: int = 200
    prefix_padding_ms: int = 300
    enable_logging: bool = True
    log_level: str = "INFO"


@dataclass
class RealtimeMessage:
    """OpenAI Realtime API message structure."""
    message_type: RealtimeMessageType
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class AudioChunk:
    """Audio chunk for streaming."""
    data: bytes
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 20  # 20ms chunks


class RealtimeClient:
    """
    OpenAI Realtime API client for streaming STT, LLM, and TTS operations.
    """
    
    def __init__(self, config: RealtimeConfig):
        """Initialize the Realtime API client."""
        self.config = config
        self.websocket: Optional[websockets.WebSocketServerProtocol] = None
        self.session_id: Optional[str] = None
        self.is_connected = False
        self.is_responding = False
        
        # Callbacks
        self.on_connect: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_error: Optional[Callable[[str, Exception], None]] = None
        self.on_transcript: Optional[Callable[[str], None]] = None
        self.on_audio: Optional[Callable[[bytes], None]] = None
        self.on_response_done: Optional[Callable[[Dict[str, Any]], None]] = None
        
        # Statistics
        self.stats = {
            'messages_sent': 0,
            'messages_received': 0,
            'audio_chunks_sent': 0,
            'audio_chunks_received': 0,
            'transcripts_received': 0,
            'responses_completed': 0,
            'errors': 0,
            'connection_time': 0,
            'last_activity': 0
        }
        
        # Audio buffer
        self.audio_buffer: List[AudioChunk] = []
        self.max_buffer_size = 100  # Maximum number of chunks to buffer
        
        # Message handling
        self._message_handlers = {
            RealtimeMessageType.SESSION_CREATED: self._handle_session_created,
            RealtimeMessageType.SESSION_UPDATED: self._handle_session_updated,
            RealtimeMessageType.INPUT_AUDIO_BUFFER_SPOKEN: self._handle_speech_started,
            RealtimeMessageType.INPUT_AUDIO_BUFFER_SPEECH_ENDED: self._handle_speech_ended,
            RealtimeMessageType.CONVERSATION_ITEM_CREATED: self._handle_conversation_item_created,
            RealtimeMessageType.RESPONSE_AUDIO_TRANSCRIPT_DELTA: self._handle_transcript_delta,
            RealtimeMessageType.RESPONSE_AUDIO_DELTA: self._handle_audio_delta,
            RealtimeMessageType.RESPONSE_DONE: self._handle_response_done,
            RealtimeMessageType.RESPONSE_CANCELLED: self._handle_response_cancelled,
            RealtimeMessageType.ERROR: self._handle_error
        }
    
    @retry(
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception)
    )
    async def connect(self) -> bool:
        """Connect to OpenAI Realtime API."""
        uri = f"wss://api.openai.com/v1/realtime?model={self.config.model}&language={self.config.language}"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}"
        }
        if self.config.enable_logging:
            logger.info(f"Connecting to OpenAI Realtime API: {uri}")
        try:
            self.websocket = await websockets.connect(
                uri,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            )
            
            self.is_connected = True
            self.stats['connection_time'] = time.time()
            self.stats['last_activity'] = time.time()
            
            if self.config.enable_logging:
                logger.info("Connected to OpenAI Realtime API")
            
            # Start message handling loop
            asyncio.create_task(self._message_loop())
            
            # Call connect callback
            if self.on_connect:
                if asyncio.iscoroutinefunction(self.on_connect):
                    await self.on_connect()
                else:
                    self.on_connect()
            
            return True
            
        except Exception as e:
            self.is_connected = False
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Failed to connect to OpenAI Realtime API: {e}")
            
            if self.on_error:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(f"Connection failed: {e}", e)
                else:
                    self.on_error(f"Connection failed: {e}", e)
            
            return False
    
    async def test_connection(self) -> bool:
        """Test the connection to the Realtime API without starting the full client."""
        uri = f"wss://api.openai.com/v1/realtime?model={self.config.model}&language={self.config.language}"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}"
        }
        try:
            async with websockets.connect(
                uri,
                additional_headers=headers,
                ping_interval=5,
                ping_timeout=5,
                close_timeout=5
            ) as websocket:
                # If connection succeeds, we're good.
                logger.info("Realtime API connection test successful.")
                return True
        except Exception as e:
            logger.error(f"Realtime API connection test failed: {e}")
            return False
    
    async def disconnect(self):
        """Disconnect from OpenAI Realtime API."""
        if not self.is_connected:
            return
        
        self.is_connected = False
        
        try:
            if self.websocket:
                await self.websocket.close()
                self.websocket = None
            
            if self.config.enable_logging:
                logger.info("Disconnected from OpenAI Realtime API")
            
            # Call disconnect callback
            if self.on_disconnect:
                if asyncio.iscoroutinefunction(self.on_disconnect):
                    await self.on_disconnect()
                else:
                    self.on_disconnect()
                    
        except Exception as e:
            if self.config.enable_logging:
                logger.error(f"Error during disconnect: {e}")
    
    async def initialize_session(self) -> bool:
        """Initialize the Realtime API session."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        session_config = {
            "modalities": ["text", "audio"],
            "instructions": self.config.instructions,
            "voice": self.config.voice.value,
            "input_audio_format": self.config.input_audio_format,
            "output_audio_format": self.config.output_audio_format,
            "input_audio_transcription": {
                "model": "whisper-1"
            },
            "turn_detection": {
                "type": "server_vad",
                "threshold": self.config.vad_threshold,
                "prefix_padding_ms": self.config.prefix_padding_ms,
                "silence_duration_ms": self.config.silence_duration_ms
            },
            "tools": [],
            "tool_choice": "auto",
            "temperature": self.config.temperature,
            "max_response_output_tokens": self.config.max_response_tokens
        }
        
        message = {
            "type": RealtimeMessageType.SESSION_UPDATE.value,
            "session": session_config
        }
        
        return await self._send_message(message)
    
    async def send_audio_chunk(self, audio_data: bytes) -> bool:
        """Send audio chunk to the Realtime API."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        # Encode audio data as base64
        audio_b64 = base64.b64encode(audio_data).decode('utf-8')
        
        message = {
            "type": RealtimeMessageType.INPUT_AUDIO_BUFFER_APPEND.value,
            "audio": audio_b64
        }
        
        success = await self._send_message(message)
        if success:
            self.stats['audio_chunks_sent'] += 1
            self.stats['last_activity'] = time.time()
        
        return success
    
    async def commit_audio_buffer(self) -> bool:
        """Commit the audio buffer to trigger processing."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        message = {
            "type": RealtimeMessageType.INPUT_AUDIO_BUFFER_COMMIT.value
        }
        
        return await self._send_message(message)
    
    async def send_text_message(self, text: str) -> bool:
        """Send text message to the Realtime API."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        message = {
            "type": RealtimeMessageType.CONVERSATION_ITEM_CREATE.value,
            "item": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": text}]
            }
        }
        
        return await self._send_message(message)
    
    async def create_response(self, modalities: List[str] = None) -> bool:
        """Create a response with specified modalities."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        if modalities is None:
            modalities = ["text", "audio"]
        
        message = {
            "type": RealtimeMessageType.RESPONSE_CREATE.value,
            "response": {
                "modalities": modalities,
                "instructions": self.config.instructions
            }
        }
        
        return await self._send_message(message)
    
    async def cancel_response(self) -> bool:
        """Cancel the current response."""
        if not self.is_connected:
            raise ConnectionError("Not connected to OpenAI Realtime API")
        
        message = {
            "type": RealtimeMessageType.RESPONSE_CANCEL.value
        }
        
        return await self._send_message(message)
    
    async def _send_message(self, message: Dict[str, Any]) -> bool:
        """Send a message to the Realtime API."""
        try:
            if not self.websocket:
                raise ConnectionError("WebSocket not available")
            
            message_str = json.dumps(message)
            await self.websocket.send(message_str)
            
            self.stats['messages_sent'] += 1
            self.stats['last_activity'] = time.time()
            
            if self.config.enable_logging:
                logger.debug(f"Sent message: {message['type']}")
            
            return True
            
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Failed to send message: {e}")
            
            if self.on_error:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(f"Send message failed: {e}", e)
                else:
                    self.on_error(f"Send message failed: {e}", e)
            
            return False
    
    async def _message_loop(self):
        """Main message handling loop."""
        try:
            while self.is_connected and self.websocket:
                message_str = await self.websocket.recv()
                message_data = json.loads(message_str)
                
                self.stats['messages_received'] += 1
                self.stats['last_activity'] = time.time()
                
                await self._handle_message(message_data)
                
        except ConnectionClosed:
            if self.config.enable_logging:
                logger.info("WebSocket connection closed")
        except WebSocketException as e:
            if self.config.enable_logging:
                logger.error(f"WebSocket error: {e}")
        except Exception as e:
            if self.config.enable_logging:
                logger.error(f"Unexpected error in message loop: {e}")
        finally:
            self.is_connected = False
    
    async def _handle_message(self, message_data: Dict[str, Any]):
        """Handle incoming message from Realtime API."""
        try:
            message_type_str = message_data.get('type')
            if not message_type_str:
                return
            
            # Convert string to enum
            try:
                message_type = RealtimeMessageType(message_type_str)
            except ValueError:
                if self.config.enable_logging:
                    logger.warning(f"Unknown message type: {message_type_str}")
                return
            
            # Handle message with appropriate handler
            handler = self._message_handlers.get(message_type)
            if handler:
                await handler(message_data)
            else:
                if self.config.enable_logging:
                    logger.debug(f"No handler for message type: {message_type.value}")
                    
        except Exception as e:
            self.stats['errors'] += 1
            
            if self.config.enable_logging:
                logger.error(f"Error handling message: {e}")
            
            if self.on_error:
                if asyncio.iscoroutinefunction(self.on_error):
                    await self.on_error(f"Message handling failed: {e}", e)
                else:
                    self.on_error(f"Message handling failed: {e}", e)
    
    async def _handle_session_created(self, message_data: Dict[str, Any]):
        """Handle session created message."""
        self.session_id = message_data.get('session', {}).get('id')
        
        if self.config.enable_logging:
            logger.info(f"Session created: {self.session_id}")
    
    async def _handle_session_updated(self, message_data: Dict[str, Any]):
        """Handle session updated message."""
        if self.config.enable_logging:
            logger.debug("Session updated")
    
    async def _handle_speech_started(self, message_data: Dict[str, Any]):
        """Handle speech started message."""
        if self.config.enable_logging:
            logger.debug("Speech started")
    
    async def _handle_speech_ended(self, message_data: Dict[str, Any]):
        """Handle speech ended message."""
        if self.config.enable_logging:
            logger.debug("Speech ended")
    
    async def _handle_conversation_item_created(self, message_data: Dict[str, Any]):
        """Handle conversation item created message."""
        if self.config.enable_logging:
            logger.debug("Conversation item created")
    
    async def _handle_transcript_delta(self, message_data: Dict[str, Any]):
        """Handle transcript delta message."""
        delta = message_data.get('delta', {})
        text = delta.get('text', '')
        
        if text and self.on_transcript:
            if asyncio.iscoroutinefunction(self.on_transcript):
                await self.on_transcript(text)
            else:
                self.on_transcript(text)
        
        self.stats['transcripts_received'] += 1
        
        if self.config.enable_logging:
            logger.debug(f"Transcript delta: {text}")
    
    async def _handle_audio_delta(self, message_data: Dict[str, Any]):
        """Handle audio delta message."""
        delta = message_data.get('delta', {})
        audio_b64 = delta.get('audio', '')
        
        if audio_b64:
            try:
                audio_data = base64.b64decode(audio_b64)
                
                if self.on_audio:
                    if asyncio.iscoroutinefunction(self.on_audio):
                        await self.on_audio(audio_data)
                    else:
                        self.on_audio(audio_data)
                
                self.stats['audio_chunks_received'] += 1
                
                if self.config.enable_logging:
                    logger.debug(f"Audio delta: {len(audio_data)} bytes")
                    
            except Exception as e:
                if self.config.enable_logging:
                    logger.error(f"Error decoding audio data: {e}")
    
    async def _handle_response_done(self, message_data: Dict[str, Any]):
        """Handle response done message."""
        response = message_data.get('response', {})
        self.is_responding = False
        self.stats['responses_completed'] += 1
        
        if self.on_response_done:
            if asyncio.iscoroutinefunction(self.on_response_done):
                await self.on_response_done(response)
            else:
                self.on_response_done(response)
        
        if self.config.enable_logging:
            logger.info("Response completed")
    
    async def _handle_response_cancelled(self, message_data: Dict[str, Any]):
        """Handle response cancelled message."""
        self.is_responding = False
        
        if self.config.enable_logging:
            logger.info("Response cancelled")
    
    async def _handle_error(self, message_data: Dict[str, Any]):
        """Handle error message."""
        error = message_data.get('error', {})
        error_type = error.get('type', 'unknown')
        error_code = error.get('code', 'unknown')
        error_message = error.get('message', 'Unknown error')
        
        self.stats['errors'] += 1
        
        if self.config.enable_logging:
            logger.error(f"Realtime API error: {error_type} - {error_code}: {error_message}")
        
        if self.on_error:
            error_exception = Exception(f"{error_type}: {error_message}")
            if asyncio.iscoroutinefunction(self.on_error):
                await self.on_error(f"Realtime API error: {error_message}", error_exception)
            else:
                self.on_error(f"Realtime API error: {error_message}", error_exception)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        stats = self.stats.copy()
        stats['is_connected'] = self.is_connected
        stats['is_responding'] = self.is_responding
        stats['session_id'] = self.session_id
        
        if stats['connection_time'] > 0:
            stats['uptime'] = time.time() - stats['connection_time']
        else:
            stats['uptime'] = 0
        
        return stats
