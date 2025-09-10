"""
Channel ID Correlation System

This module provides channel ID tracking and correlation across all STT operations
and messages. It manages channel mapping and state for concurrent call handling.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Set
from enum import Enum

logger = logging.getLogger(__name__)


class ChannelState(Enum):
    """Channel state enumeration."""
    WAITING_FOR_RTP = "waiting_for_rtp"
    RTP_ACTIVE = "rtp_active"
    SPEECH_DETECTED = "speech_detected"
    PROCESSING = "processing"
    COMPLETED = "completed"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class ChannelInfo:
    """Information about a channel/call."""
    channel_id: str
    ssrc: Optional[int] = None
    payload_type: Optional[int] = None
    sample_rate: int = 8000
    channels: int = 1
    state: ChannelState = ChannelState.WAITING_FOR_RTP
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    packet_count: int = 0
    bytes_received: int = 0
    speech_segments: int = 0
    transcripts: int = 0
    errors: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class ChannelCorrelationManager:
    """Manages channel ID correlation and tracking."""
    
    def __init__(self, timeout_seconds: int = 300, cleanup_interval: int = 60):
        """Initialize the channel correlation manager."""
        self.channels: Dict[str, ChannelInfo] = {}
        self.ssrc_to_channel: Dict[int, str] = {}  # SSRC -> Channel ID mapping
        self.timeout_seconds = timeout_seconds
        self.cleanup_interval = cleanup_interval
        self.cleanup_task: Optional[asyncio.Task] = None
        self.running = False
        
        logger.info("Channel Correlation Manager initialized")
    
    async def start(self):
        """Start the correlation manager."""
        if self.running:
            return
        
        self.running = True
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Channel Correlation Manager started")
    
    async def stop(self):
        """Stop the correlation manager."""
        self.running = False
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Channel Correlation Manager stopped")
    
    def register_channel(self, channel_id: str, metadata: Dict[str, Any] = None) -> ChannelInfo:
        """Register a new channel."""
        if channel_id in self.channels:
            logger.warning(f"Channel {channel_id} already registered")
            return self.channels[channel_id]
        
        channel_info = ChannelInfo(
            channel_id=channel_id,
            metadata=metadata or {}
        )
        
        self.channels[channel_id] = channel_info
        logger.info(f"Registered channel {channel_id}")
        
        return channel_info
    
    def correlate_ssrc(self, ssrc: int, channel_id: str) -> bool:
        """Correlate an SSRC with a channel ID."""
        try:
            # Check if SSRC is already mapped
            if ssrc in self.ssrc_to_channel:
                existing_channel = self.ssrc_to_channel[ssrc]
                if existing_channel != channel_id:
                    logger.warning(f"SSRC {ssrc} already mapped to channel {existing_channel}, updating to {channel_id}")
                else:
                    return True  # Already correctly mapped
            
            # Check if channel exists
            if channel_id not in self.channels:
                logger.error(f"Channel {channel_id} not found for SSRC correlation")
                return False
            
            # Update mappings
            self.ssrc_to_channel[ssrc] = channel_id
            self.channels[channel_id].ssrc = ssrc
            self.channels[channel_id].state = ChannelState.RTP_ACTIVE
            
            logger.info(f"Correlated SSRC {ssrc} with channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error correlating SSRC {ssrc} with channel {channel_id}: {e}")
            return False
    
    def get_channel_by_ssrc(self, ssrc: int) -> Optional[ChannelInfo]:
        """Get channel information by SSRC."""
        channel_id = self.ssrc_to_channel.get(ssrc)
        if channel_id:
            return self.channels.get(channel_id)
        return None
    
    def get_channel(self, channel_id: str) -> Optional[ChannelInfo]:
        """Get channel information by channel ID."""
        return self.channels.get(channel_id)
    
    def update_channel_activity(self, channel_id: str, activity_type: str = "general", **kwargs) -> bool:
        """Update channel activity and statistics."""
        try:
            channel = self.channels.get(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found for activity update")
                return False
            
            # Update last activity time
            channel.last_activity = time.time()
            
            # Update specific statistics
            if activity_type == "rtp_packet":
                channel.packet_count += 1
                channel.bytes_received += kwargs.get('bytes', 0)
            elif activity_type == "speech_segment":
                channel.speech_segments += 1
                channel.state = ChannelState.SPEECH_DETECTED
            elif activity_type == "transcript":
                channel.transcripts += 1
                channel.state = ChannelState.PROCESSING
            elif activity_type == "error":
                channel.errors += 1
                channel.state = ChannelState.ERROR
            elif activity_type == "completed":
                channel.state = ChannelState.COMPLETED
            
            # Update metadata
            if kwargs:
                channel.metadata.update(kwargs)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating channel activity for {channel_id}: {e}")
            return False
    
    def update_channel_state(self, channel_id: str, state: ChannelState) -> bool:
        """Update channel state."""
        try:
            channel = self.channels.get(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found for state update")
                return False
            
            old_state = channel.state
            channel.state = state
            channel.last_activity = time.time()
            
            logger.debug(f"Channel {channel_id} state changed: {old_state.value} -> {state.value}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating channel state for {channel_id}: {e}")
            return False
    
    def remove_channel(self, channel_id: str) -> bool:
        """Remove a channel and clean up mappings."""
        try:
            channel = self.channels.get(channel_id)
            if not channel:
                logger.warning(f"Channel {channel_id} not found for removal")
                return False
            
            # Remove SSRC mapping if exists
            if channel.ssrc and channel.ssrc in self.ssrc_to_channel:
                del self.ssrc_to_channel[channel.ssrc]
            
            # Remove channel
            del self.channels[channel_id]
            
            logger.info(f"Removed channel {channel_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error removing channel {channel_id}: {e}")
            return False
    
    def get_all_channels(self) -> Dict[str, ChannelInfo]:
        """Get all channels."""
        return self.channels.copy()
    
    def get_channels_by_state(self, state: ChannelState) -> List[ChannelInfo]:
        """Get channels by state."""
        return [channel for channel in self.channels.values() if channel.state == state]
    
    def get_channel_stats(self) -> Dict[str, Any]:
        """Get channel statistics."""
        total_channels = len(self.channels)
        state_counts = {}
        
        for state in ChannelState:
            state_counts[state.value] = len(self.get_channels_by_state(state))
        
        total_packets = sum(channel.packet_count for channel in self.channels.values())
        total_bytes = sum(channel.bytes_received for channel in self.channels.values())
        total_speech_segments = sum(channel.speech_segments for channel in self.channels.values())
        total_transcripts = sum(channel.transcripts for channel in self.channels.values())
        total_errors = sum(channel.errors for channel in self.channels.values())
        
        return {
            'total_channels': total_channels,
            'state_counts': state_counts,
            'total_packets': total_packets,
            'total_bytes': total_bytes,
            'total_speech_segments': total_speech_segments,
            'total_transcripts': total_transcripts,
            'total_errors': total_errors,
            'ssrc_mappings': len(self.ssrc_to_channel)
        }
    
    async def _cleanup_loop(self):
        """Background cleanup loop for timed-out channels."""
        while self.running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                await self._cleanup_timed_out_channels()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def _cleanup_timed_out_channels(self):
        """Clean up timed-out channels."""
        current_time = time.time()
        timed_out_channels = []
        
        for channel_id, channel in self.channels.items():
            if current_time - channel.last_activity > self.timeout_seconds:
                timed_out_channels.append(channel_id)
        
        for channel_id in timed_out_channels:
            logger.warning(f"Channel {channel_id} timed out, removing")
            self.remove_channel(channel_id)
        
        if timed_out_channels:
            logger.info(f"Cleaned up {len(timed_out_channels)} timed-out channels")
