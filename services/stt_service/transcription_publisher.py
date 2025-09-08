"""
Transcription Publisher for STT Service

This module handles Redis publishing of transcription results with proper
channel correlation and error handling.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

logger = logging.getLogger(__name__)


class TranscriptionStatus(Enum):
    """Transcription status enumeration."""
    PARTIAL = "partial"
    FINAL = "final"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class TranscriptionMessage:
    """Transcription message schema."""
    message_id: str
    channel_id: Optional[str] = None
    ssrc: Optional[int] = None
    text: str = ""
    status: TranscriptionStatus = TranscriptionStatus.PARTIAL
    timestamp: float = field(default_factory=time.time)
    confidence: Optional[float] = None
    language: Optional[str] = None
    duration: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'message_id': self.message_id,
            'channel_id': self.channel_id,
            'ssrc': self.ssrc,
            'text': self.text,
            'status': self.status.value,
            'timestamp': self.timestamp,
            'confidence': self.confidence,
            'language': self.language,
            'duration': self.duration,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TranscriptionMessage':
        """Create from dictionary."""
        return cls(
            message_id=data.get('message_id', str(uuid4())),
            channel_id=data.get('channel_id'),
            ssrc=data.get('ssrc'),
            text=data.get('text', ''),
            status=TranscriptionStatus(data.get('status', TranscriptionStatus.PARTIAL.value)),
            timestamp=data.get('timestamp', time.time()),
            confidence=data.get('confidence'),
            language=data.get('language'),
            duration=data.get('duration'),
            metadata=data.get('metadata', {})
        )


class TranscriptionPublisher:
    """Handles Redis publishing of transcription results."""
    
    def __init__(self, redis_client, channel_correlation_manager=None):
        """Initialize the transcription publisher."""
        self.redis_client = redis_client
        self.channel_correlation = channel_correlation_manager
        self.publish_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.running = False
        self.publish_task: Optional[asyncio.Task] = None
        self.retry_attempts = 3
        self.retry_delay = 1.0
        
        # Statistics
        self.stats = {
            'messages_published': 0,
            'messages_failed': 0,
            'retry_attempts': 0,
            'queue_size': 0
        }
        
        logger.info("TranscriptionPublisher initialized")
    
    async def start(self):
        """Start the publisher."""
        if self.running:
            return
        
        self.running = True
        self.publish_task = asyncio.create_task(self._publish_loop())
        logger.info("TranscriptionPublisher started")
    
    async def stop(self):
        """Stop the publisher."""
        self.running = False
        if self.publish_task:
            self.publish_task.cancel()
            try:
                await self.publish_task
            except asyncio.CancelledError:
                pass
        logger.info("TranscriptionPublisher stopped")
    
    async def publish_transcription(
        self,
        text: str,
        is_final: bool = False,
        channel_id: Optional[str] = None,
        ssrc: Optional[int] = None,
        confidence: Optional[float] = None,
        language: Optional[str] = None,
        duration: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Publish a transcription result."""
        try:
            # Create transcription message
            message = TranscriptionMessage(
                message_id=str(uuid4()),
                channel_id=channel_id,
                ssrc=ssrc,
                text=text,
                status=TranscriptionStatus.FINAL if is_final else TranscriptionStatus.PARTIAL,
                confidence=confidence,
                language=language,
                duration=duration,
                metadata=metadata or {}
            )
            
            # Add to publish queue
            await self.publish_queue.put(message)
            self.stats['queue_size'] = self.publish_queue.qsize()
            
            logger.debug(f"Queued transcription message: {message.message_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error queuing transcription message: {e}")
            self.stats['messages_failed'] += 1
            return False
    
    async def publish_error(
        self,
        error_message: str,
        channel_id: Optional[str] = None,
        ssrc: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Publish an error message."""
        try:
            message = TranscriptionMessage(
                message_id=str(uuid4()),
                channel_id=channel_id,
                ssrc=ssrc,
                text=error_message,
                status=TranscriptionStatus.ERROR,
                metadata=metadata or {}
            )
            
            await self.publish_queue.put(message)
            self.stats['queue_size'] = self.publish_queue.qsize()
            
            logger.debug(f"Queued error message: {message.message_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error queuing error message: {e}")
            self.stats['messages_failed'] += 1
            return False
    
    async def _publish_loop(self):
        """Main publishing loop."""
        while self.running:
            try:
                # Wait for messages with timeout
                try:
                    message = await asyncio.wait_for(
                        self.publish_queue.get(), 
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Publish message
                success = await self._publish_message(message)
                if success:
                    self.stats['messages_published'] += 1
                else:
                    self.stats['messages_failed'] += 1
                
                # Update queue size
                self.stats['queue_size'] = self.publish_queue.qsize()
                
            except Exception as e:
                logger.error(f"Error in publish loop: {e}")
                await asyncio.sleep(0.1)
    
    async def _publish_message(self, message: TranscriptionMessage) -> bool:
        """Publish a single message to Redis."""
        for attempt in range(self.retry_attempts):
            try:
                # Convert message to JSON
                message_dict = message.to_dict()
                message_json = json.dumps(message_dict, ensure_ascii=False)
                
                # Publish to Redis
                await self.redis_client.publish("stt:transcription:complete", message_json)
                
                # Update channel correlation if available
                if self.channel_correlation and message.channel_id:
                    self.channel_correlation.update_channel_activity(
                        message.channel_id,
                        activity_type="transcript",
                        transcript_text=message.text,
                        is_final=(message.status == TranscriptionStatus.FINAL),
                        message_id=message.message_id,
                        confidence=message.confidence
                    )
                
                logger.debug(f"Published transcription message: {message.message_id}")
                return True
                
            except Exception as e:
                logger.warning(f"Publish attempt {attempt + 1} failed: {e}")
                self.stats['retry_attempts'] += 1
                
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff
                else:
                    logger.error(f"Failed to publish message after {self.retry_attempts} attempts: {e}")
                    return False
        
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get publisher statistics."""
        return {
            **self.stats,
            'queue_size': self.publish_queue.qsize(),
            'running': self.running
        }
    
    async def flush_queue(self) -> int:
        """Flush all pending messages in the queue."""
        flushed_count = 0
        while not self.publish_queue.empty():
            try:
                message = self.publish_queue.get_nowait()
                success = await self._publish_message(message)
                if success:
                    flushed_count += 1
            except asyncio.QueueEmpty:
                break
            except Exception as e:
                logger.error(f"Error flushing message: {e}")
        
        logger.info(f"Flushed {flushed_count} messages from queue")
        return flushed_count


class TranscriptionSubscriber:
    """Handles subscription to transcription messages."""
    
    def __init__(self, redis_client, on_transcription: Optional[callable] = None):
        """Initialize the transcription subscriber."""
        self.redis_client = redis_client
        self.on_transcription = on_transcription
        self.running = False
        self.subscribe_task: Optional[asyncio.Task] = None
        
        # Statistics
        self.stats = {
            'messages_received': 0,
            'messages_processed': 0,
            'messages_failed': 0
        }
        
        logger.info("TranscriptionSubscriber initialized")
    
    async def start(self):
        """Start the subscriber."""
        if self.running:
            return
        
        self.running = True
        self.subscribe_task = asyncio.create_task(self._subscribe_loop())
        logger.info("TranscriptionSubscriber started")
    
    async def stop(self):
        """Stop the subscriber."""
        self.running = False
        if self.subscribe_task:
            self.subscribe_task.cancel()
            try:
                await self.subscribe_task
            except asyncio.CancelledError:
                pass
        logger.info("TranscriptionSubscriber stopped")
    
    async def _subscribe_loop(self):
        """Main subscription loop."""
        try:
            # Subscribe to transcription channel
            await self.redis_client.subscribe(
                ["stt:transcription:complete"], 
                self._handle_message
            )
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error in subscribe loop: {e}")
    
    async def _handle_message(self, channel: str, message: str):
        """Handle incoming transcription message."""
        try:
            self.stats['messages_received'] += 1
            
            # Parse JSON message
            message_data = json.loads(message)
            transcription = TranscriptionMessage.from_dict(message_data)
            
            # Process message
            if self.on_transcription:
                await self.on_transcription(transcription)
            
            self.stats['messages_processed'] += 1
            logger.debug(f"Processed transcription message: {transcription.message_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse transcription message: {e}")
            self.stats['messages_failed'] += 1
        except Exception as e:
            logger.error(f"Error handling transcription message: {e}")
            self.stats['messages_failed'] += 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get subscriber statistics."""
        return {
            **self.stats,
            'running': self.running
        }
