"""
Barge-in Event Detection System

This module implements VAD-based barge-in event detection and Redis publishing
for call controller. It detects when a user interrupts TTS playback with speech.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Any
from collections import deque

logger = logging.getLogger(__name__)


class BargeInState(Enum):
    """Barge-in detection state."""
    IDLE = "idle"
    MONITORING = "monitoring"
    DETECTED = "detected"
    DEBOUNCING = "debouncing"


class TTSPlaybackState(Enum):
    """TTS playback state."""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass
class BargeInEvent:
    """Barge-in event data."""
    event_id: str
    channel_id: str
    ssrc: Optional[int] = None
    timestamp: float = field(default_factory=time.time)
    confidence: float = 1.0
    duration: float = 0.0
    tts_session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSPlaybackSession:
    """TTS playback session tracking."""
    session_id: str
    channel_id: str
    start_time: float
    end_time: Optional[float] = None
    state: TTSPlaybackState = TTSPlaybackState.PLAYING
    volume_level: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BargeInConfig:
    """Configuration for barge-in detection."""
    sensitivity_threshold: float = 0.7  # VAD sensitivity threshold
    debounce_duration_ms: int = 200  # Debounce duration in milliseconds
    min_speech_duration_ms: int = 100  # Minimum speech duration to trigger
    max_silence_duration_ms: int = 500  # Maximum silence before reset
    tts_volume_threshold: float = 0.1  # Minimum TTS volume to consider active
    enable_debouncing: bool = True
    enable_volume_correlation: bool = True
    enable_timing_correlation: bool = True


class BargeInDetector:
    """Detects barge-in events during TTS playback."""
    
    def __init__(self, config: BargeInConfig, redis_client, channel_correlation_manager=None):
        """Initialize the barge-in detector."""
        self.config = config
        self.redis_client = redis_client
        self.channel_correlation = channel_correlation_manager
        
        # State tracking
        self.state = BargeInState.IDLE
        self.active_tts_sessions: Dict[str, TTSPlaybackSession] = {}
        self.channel_states: Dict[str, Dict[str, Any]] = {}
        
        # Debouncing
        self.debounce_timers: Dict[str, asyncio.Task] = {}
        self.last_speech_times: Dict[str, float] = {}
        
        # Statistics
        self.stats = {
            'barge_in_events': 0,
            'false_positives': 0,
            'debounced_events': 0,
            'tts_sessions_tracked': 0
        }
        
        # Callbacks
        self.on_barge_in: Optional[Callable[[BargeInEvent], None]] = None
        
        logger.info("BargeInDetector initialized")
    
    async def start(self):
        """Start the barge-in detector."""
        logger.info("BargeInDetector started")
    
    async def stop(self):
        """Stop the barge-in detector."""
        # Cancel all debounce timers
        for timer in self.debounce_timers.values():
            timer.cancel()
        self.debounce_timers.clear()
        
        logger.info("BargeInDetector stopped")
    
    def register_tts_session(self, session_id: str, channel_id: str, metadata: Dict[str, Any] = None) -> bool:
        """Register a new TTS playback session."""
        try:
            session = TTSPlaybackSession(
                session_id=session_id,
                channel_id=channel_id,
                start_time=time.time(),
                metadata=metadata or {}
            )
            
            self.active_tts_sessions[session_id] = session
            
            # Initialize channel state if needed
            if channel_id not in self.channel_states:
                self.channel_states[channel_id] = {
                    'last_speech_time': 0.0,
                    'speech_duration': 0.0,
                    'is_speaking': False,
                    'barge_in_detected': False
                }
            
            # Start monitoring for this channel
            self._start_monitoring(channel_id)
            
            self.stats['tts_sessions_tracked'] += 1
            logger.info(f"Registered TTS session {session_id} for channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error registering TTS session: {e}")
            return False
    
    def unregister_tts_session(self, session_id: str) -> bool:
        """Unregister a TTS playback session."""
        try:
            if session_id in self.active_tts_sessions:
                session = self.active_tts_sessions.pop(session_id)
                session.end_time = time.time()
                session.state = TTSPlaybackState.STOPPED
                
                # Stop monitoring if no more active sessions for this channel
                channel_id = session.channel_id
                active_sessions = [s for s in self.active_tts_sessions.values() if s.channel_id == channel_id]
                if not active_sessions:
                    self._stop_monitoring(channel_id)
                
                logger.info(f"Unregistered TTS session {session_id} for channel {channel_id}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error unregistering TTS session: {e}")
            return False
    
    def update_tts_volume(self, session_id: str, volume_level: float) -> bool:
        """Update TTS volume level for a session."""
        try:
            if session_id in self.active_tts_sessions:
                self.active_tts_sessions[session_id].volume_level = volume_level
                return True
            return False
            
        except Exception as e:
            logger.error(f"Error updating TTS volume: {e}")
            return False
    
    def process_speech_detection(self, channel_id: str, ssrc: Optional[int] = None, 
                                confidence: float = 1.0, duration: float = 0.0) -> bool:
        """Process speech detection for barge-in analysis."""
        try:
            current_time = time.time()
            
            # Check if we're monitoring this channel
            if channel_id not in self.channel_states:
                return False
            
            # Check if there are active TTS sessions for this channel
            active_sessions = [s for s in self.active_tts_sessions.values() 
                             if s.channel_id == channel_id and s.state == TTSPlaybackState.PLAYING]
            
            if not active_sessions:
                # No active TTS, not a barge-in
                return False
            
            # Update channel state
            channel_state = self.channel_states[channel_id]
            channel_state['last_speech_time'] = current_time
            channel_state['speech_duration'] += duration
            channel_state['is_speaking'] = True
            
            # Check if this is a potential barge-in
            if self._is_potential_barge_in(channel_id, confidence, duration, active_sessions):
                # Check debouncing
                if self.config.enable_debouncing:
                    if channel_id in self.debounce_timers:
                        # Cancel existing timer
                        self.debounce_timers[channel_id].cancel()
                    
                    # Start new debounce timer
                    self.debounce_timers[channel_id] = asyncio.create_task(
                        self._debounce_barge_in(channel_id, ssrc, confidence, duration, active_sessions[0].session_id)
                    )
                else:
                    # Immediate barge-in detection
                    await self._trigger_barge_in(channel_id, ssrc, confidence, duration, active_sessions[0].session_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing speech detection: {e}")
            return False
    
    def _is_potential_barge_in(self, channel_id: str, confidence: float, duration: float, 
                              active_sessions: List[TTSPlaybackSession]) -> bool:
        """Check if speech detection is a potential barge-in."""
        try:
            # Check confidence threshold
            if confidence < self.config.sensitivity_threshold:
                return False
            
            # Check minimum speech duration
            if duration < (self.config.min_speech_duration_ms / 1000.0):
                return False
            
            # Check if TTS is actually playing (volume check)
            if self.config.enable_volume_correlation:
                max_volume = max(session.volume_level for session in active_sessions)
                if max_volume < self.config.tts_volume_threshold:
                    return False
            
            # Check timing correlation
            if self.config.enable_timing_correlation:
                current_time = time.time()
                for session in active_sessions:
                    # Check if speech started during TTS playback
                    if session.start_time <= current_time <= (session.end_time or current_time):
                        return True
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking potential barge-in: {e}")
            return False
    
    async def _debounce_barge_in(self, channel_id: str, ssrc: Optional[int], 
                                confidence: float, duration: float, session_id: str):
        """Debounce barge-in detection."""
        try:
            # Wait for debounce duration
            await asyncio.sleep(self.config.debounce_duration_ms / 1000.0)
            
            # Check if we still have active speech
            channel_state = self.channel_states.get(channel_id)
            if not channel_state:
                return
            
            current_time = time.time()
            time_since_speech = current_time - channel_state['last_speech_time']
            
            # If speech is still active, trigger barge-in
            if time_since_speech < (self.config.max_silence_duration_ms / 1000.0):
                await self._trigger_barge_in(channel_id, ssrc, confidence, duration, session_id)
            else:
                # False positive, speech stopped
                self.stats['false_positives'] += 1
                logger.debug(f"Debounced false positive barge-in for channel {channel_id}")
            
            # Clean up debounce timer
            if channel_id in self.debounce_timers:
                del self.debounce_timers[channel_id]
                
        except asyncio.CancelledError:
            # Timer was cancelled, ignore
            pass
        except Exception as e:
            logger.error(f"Error in debounce timer: {e}")
    
    async def _trigger_barge_in(self, channel_id: str, ssrc: Optional[int], 
                               confidence: float, duration: float, session_id: str):
        """Trigger a barge-in event."""
        try:
            # Create barge-in event
            event = BargeInEvent(
                event_id=f"barge_in_{int(time.time() * 1000)}",
                channel_id=channel_id,
                ssrc=ssrc,
                confidence=confidence,
                duration=duration,
                tts_session_id=session_id,
                metadata={
                    'detection_time': time.time(),
                    'sensitivity_threshold': self.config.sensitivity_threshold,
                    'debounced': self.config.enable_debouncing
                }
            )
            
            # Update channel state
            if channel_id in self.channel_states:
                self.channel_states[channel_id]['barge_in_detected'] = True
            
            # Publish barge-in event to Redis
            await self._publish_barge_in_event(event)
            
            # Call callback if set
            if self.on_barge_in:
                try:
                    await self.on_barge_in(event)
                except Exception as e:
                    logger.error(f"Error in barge-in callback: {e}")
            
            self.stats['barge_in_events'] += 1
            logger.info(f"Barge-in detected for channel {channel_id}, session {session_id}")
            
        except Exception as e:
            logger.error(f"Error triggering barge-in: {e}")
    
    async def _publish_barge_in_event(self, event: BargeInEvent):
        """Publish barge-in event to Redis."""
        try:
            message = {
                'event_type': 'barge_in',
                'event_id': event.event_id,
                'channel_id': event.channel_id,
                'ssrc': event.ssrc,
                'timestamp': event.timestamp,
                'confidence': event.confidence,
                'duration': event.duration,
                'tts_session_id': event.tts_session_id,
                'metadata': event.metadata
            }
            
            await self.redis_client.publish("calls:control:play", message)
            logger.debug(f"Published barge-in event: {event.event_id}")
            
        except Exception as e:
            logger.error(f"Error publishing barge-in event: {e}")
    
    def _start_monitoring(self, channel_id: str):
        """Start monitoring a channel for barge-in events."""
        if channel_id not in self.channel_states:
            self.channel_states[channel_id] = {
                'last_speech_time': 0.0,
                'speech_duration': 0.0,
                'is_speaking': False,
                'barge_in_detected': False
            }
        
        logger.debug(f"Started monitoring channel {channel_id} for barge-in events")
    
    def _stop_monitoring(self, channel_id: str):
        """Stop monitoring a channel for barge-in events."""
        if channel_id in self.channel_states:
            # Cancel any pending debounce timer
            if channel_id in self.debounce_timers:
                self.debounce_timers[channel_id].cancel()
                del self.debounce_timers[channel_id]
            
            # Reset channel state
            self.channel_states[channel_id]['barge_in_detected'] = False
            self.channel_states[channel_id]['is_speaking'] = False
            
            logger.debug(f"Stopped monitoring channel {channel_id} for barge-in events")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            **self.stats,
            'active_tts_sessions': len(self.active_tts_sessions),
            'monitored_channels': len(self.channel_states),
            'pending_debounce_timers': len(self.debounce_timers)
        }
    
    def get_channel_state(self, channel_id: str) -> Optional[Dict[str, Any]]:
        """Get state for a specific channel."""
        return self.channel_states.get(channel_id)
    
    def get_active_tts_sessions(self) -> Dict[str, TTSPlaybackSession]:
        """Get all active TTS sessions."""
        return self.active_tts_sessions.copy()
