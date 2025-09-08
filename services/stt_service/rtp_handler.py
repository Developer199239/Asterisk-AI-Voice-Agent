"""
RTP Stream Handler for STT Service

This module handles RTP stream reception and processing for speech-to-text.
It implements UDP server using asyncio.DatagramProtocol for RTP packet reception.
"""

import asyncio
import logging
import struct
import time
import audioop
from dataclasses import dataclass
from typing import Dict, Optional, Callable, Any, List, Tuple
from enum import Enum

from .vad_handler import VADHandler, SpeechSegment
from .channel_correlation import ChannelCorrelationManager, ChannelState

logger = logging.getLogger(__name__)


class RTPPayloadType(Enum):
    """RTP payload types for audio codecs."""
    PCMU = 0      # G.711 μ-law
    PCMA = 8      # G.711 A-law
    G722 = 9      # G.722
    G729 = 18     # G.729
    OPUS = 111    # Opus (dynamic)


@dataclass
class RTPPacket:
    """RTP packet structure."""
    version: int
    padding: bool
    extension: bool
    csrc_count: int
    marker: bool
    payload_type: int
    sequence_number: int
    timestamp: int
    ssrc: int
    payload: bytes
    csrc_list: List[int] = None
    extension_header: Optional[bytes] = None
    
    def __post_init__(self):
        if self.csrc_list is None:
            self.csrc_list = []
    
    @property
    def header_length(self) -> int:
        """Calculate total header length including CSRC and extension."""
        length = 12  # Basic header
        length += self.csrc_count * 4  # CSRC list
        if self.extension:
            length += 4  # Extension header length field
            if self.extension_header:
                length += len(self.extension_header)
        return length
    
    def get_audio_samples(self, sample_rate: int = 8000) -> Optional[bytes]:
        """Extract and decode audio samples from RTP payload."""
        try:
            payload_type = RTPPayloadType(self.payload_type)
            
            if payload_type == RTPPayloadType.PCMU:
                # G.711 μ-law to linear PCM
                return audioop.ulaw2lin(self.payload, 2)
            elif payload_type == RTPPayloadType.PCMA:
                # G.711 A-law to linear PCM
                return audioop.alaw2lin(self.payload, 2)
            elif payload_type == RTPPayloadType.G722:
                # G.722 - return as-is (already 16-bit PCM)
                return self.payload
            else:
                logger.warning(f"Unsupported payload type: {self.payload_type}")
                return None
                
        except ValueError:
            logger.warning(f"Unknown payload type: {self.payload_type}")
            return None
        except Exception as e:
            logger.error(f"Error decoding audio: {e}")
            return None
    
    @staticmethod
    def parse_rtp_packet(data: bytes) -> Optional['RTPPacket']:
        """Parse RTP packet from raw bytes with full header support."""
        if len(data) < 12:
            logger.warning("RTP packet too short")
            return None
            
        try:
            # Parse basic RTP header (first 12 bytes)
            header = struct.unpack('!BBHII', data[:12])
            
            version = (header[0] >> 6) & 0x3
            padding = bool((header[0] >> 5) & 0x1)
            extension = bool((header[0] >> 4) & 0x1)
            csrc_count = header[0] & 0xF
            
            marker = bool((header[1] >> 7) & 0x1)
            payload_type = header[1] & 0x7F
            
            sequence_number = header[2]
            timestamp = header[3]
            ssrc = header[4]
            
            # Calculate header length
            header_length = 12 + (csrc_count * 4)
            
            # Parse CSRC list if present
            csrc_list = []
            if csrc_count > 0:
                csrc_data = data[12:header_length]
                csrc_list = list(struct.unpack(f'!{csrc_count}I', csrc_data))
            
            # Parse extension header if present
            extension_header = None
            if extension:
                if len(data) < header_length + 4:
                    logger.warning("RTP packet too short for extension header")
                    return None
                
                # Extension header: 16-bit length field, then extension data
                ext_length = struct.unpack('!H', data[header_length:header_length + 2])[0]
                ext_length *= 4  # Length is in 32-bit words
                
                if len(data) < header_length + 4 + ext_length:
                    logger.warning("RTP packet too short for extension data")
                    return None
                
                extension_header = data[header_length + 2:header_length + 2 + ext_length]
                header_length += 4 + ext_length
            
            # Extract payload
            payload = data[header_length:]
            
            # Remove padding if present
            if padding and len(payload) > 0:
                padding_length = payload[-1]
                if padding_length > 0 and padding_length <= len(payload):
                    payload = payload[:-padding_length]
            
            return RTPPacket(
                version=version,
                padding=padding,
                extension=extension,
                csrc_count=csrc_count,
                marker=marker,
                payload_type=payload_type,
                sequence_number=sequence_number,
                timestamp=timestamp,
                ssrc=ssrc,
                payload=payload,
                csrc_list=csrc_list,
                extension_header=extension_header
            )
            
        except struct.error as e:
            logger.error(f"Error parsing RTP packet: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error parsing RTP packet: {e}")
            return None


@dataclass
class RTPStreamInfo:
    """Information about an RTP stream."""
    ssrc: int
    payload_type: int
    sample_rate: int
    channels: int
    first_packet_time: float
    last_packet_time: float
    packet_count: int
    bytes_received: int
    sequence_number: int
    expected_sequence: int
    lost_packets: int


class RTPStreamHandler:
    """Handles individual RTP stream processing."""
    
    def __init__(
        self, 
        ssrc: int, 
        payload_type: int, 
        channel_id: Optional[str] = None,
        correlation_manager: Optional[ChannelCorrelationManager] = None,
        on_audio_data: Callable[[bytes, RTPStreamInfo], None],
        on_speech_segment: Optional[Callable[[SpeechSegment, RTPStreamInfo], None]] = None
    ):
        self.ssrc = ssrc
        self.payload_type = payload_type
        self.channel_id = channel_id
        self.correlation_manager = correlation_manager
        self.on_audio_data = on_audio_data
        self.on_speech_segment = on_speech_segment
        
        # Stream information
        self.info = RTPStreamInfo(
            ssrc=ssrc,
            payload_type=payload_type,
            sample_rate=self._get_sample_rate(payload_type),
            channels=1,  # Assume mono for now
            first_packet_time=0,
            last_packet_time=0,
            packet_count=0,
            bytes_received=0,
            sequence_number=0,
            expected_sequence=0,
            lost_packets=0
        )
        
        # Audio buffer for reassembly
        self.audio_buffer = bytearray()
        self.last_timestamp = 0
        
        # Initialize VAD
        self.vad_handler = VADHandler(
            sample_rate=self.info.sample_rate,
            frame_duration_ms=20,
            on_speech_end=self._on_speech_segment
        )
        
    def _get_sample_rate(self, payload_type: int) -> int:
        """Get sample rate for payload type."""
        sample_rates = {
            RTPPayloadType.PCMU.value: 8000,
            RTPPayloadType.PCMA.value: 8000,
            RTPPayloadType.G722.value: 8000,
            RTPPayloadType.G729.value: 8000,
            RTPPayloadType.OPUS.value: 48000,
        }
        return sample_rates.get(payload_type, 8000)
    
    def process_packet(self, packet: RTPPacket) -> bool:
        """Process an RTP packet."""
        try:
            # Update stream info
            current_time = time.time()
            if self.info.first_packet_time == 0:
                self.info.first_packet_time = current_time
            
            self.info.last_packet_time = current_time
            self.info.packet_count += 1
            self.info.bytes_received += len(packet.payload)
            
            # Update channel correlation if available
            if self.correlation_manager and self.channel_id:
                self.correlation_manager.update_channel_activity(
                    self.channel_id,
                    activity_type="rtp_packet",
                    bytes=len(packet.payload),
                    ssrc=self.ssrc,
                    payload_type=self.payload_type
                )
            
            # Check for packet loss
            if self.info.expected_sequence > 0:
                expected = (self.info.expected_sequence + 1) % 65536
                if packet.sequence_number != expected:
                    lost = (packet.sequence_number - expected) % 65536
                    self.info.lost_packets += lost
                    logger.warning(f"Lost {lost} packets for SSRC {self.ssrc}")
            
            self.info.expected_sequence = packet.sequence_number
            
            # Check for timestamp discontinuity (new talk spurt)
            if self.last_timestamp > 0 and packet.timestamp < self.last_timestamp:
                # Timestamp wrapped around or new talk spurt
                logger.debug(f"Timestamp discontinuity for SSRC {self.ssrc}")
                self.audio_buffer.clear()
            
            self.last_timestamp = packet.timestamp
            
            # Extract and decode audio samples
            audio_samples = packet.get_audio_samples(self.info.sample_rate)
            if audio_samples:
                # Process audio through VAD
                speech_segments = self.vad_handler.process_audio(audio_samples)
                
                # Handle detected speech segments
                for segment in speech_segments:
                    # Update channel correlation for speech activity
                    if self.correlation_manager and self.channel_id:
                        self.correlation_manager.update_channel_activity(
                            self.channel_id,
                            activity_type="speech_segment",
                            segment_duration=segment.duration,
                            segment_confidence=segment.confidence
                        )
                    
                    if self.on_speech_segment:
                        self.on_speech_segment(segment, self.info)
                
                # Also call the original audio data handler for continuous processing
                self.on_audio_data(audio_samples, self.info)
            else:
                # Fallback: add raw payload to buffer
                self.audio_buffer.extend(packet.payload)
                
                # Process raw audio data if we have enough
                if len(self.audio_buffer) >= 320:  # 20ms of 8kHz audio
                    audio_data = bytes(self.audio_buffer)
                    self.audio_buffer.clear()
                    
                    # Process through VAD
                    speech_segments = self.vad_handler.process_audio(audio_data)
                    
                    # Handle detected speech segments
                    for segment in speech_segments:
                        if self.on_speech_segment:
                            self.on_speech_segment(segment, self.info)
                    
                    # Call audio data handler
                    self.on_audio_data(audio_data, self.info)
            
            return True
            
        except Exception as e:
            logger.error(f"Error processing RTP packet for SSRC {self.ssrc}: {e}")
            return False
    
    def _on_speech_segment(self, segment: SpeechSegment):
        """Handle detected speech segment."""
        if self.on_speech_segment:
            try:
                self.on_speech_segment(segment, self.info)
            except Exception as e:
                logger.error(f"Error handling speech segment for SSRC {self.ssrc}: {e}")
    
    def get_vad_state(self):
        """Get current VAD state."""
        return self.vad_handler.get_current_state()
    
    def reset_vad(self):
        """Reset VAD state."""
        self.vad_handler.reset()


class RTPUDPServer(asyncio.DatagramProtocol):
    """UDP server for receiving RTP streams."""
    
    def __init__(
        self, 
        on_audio_data: Callable[[bytes, RTPStreamInfo], None],
        on_speech_segment: Optional[Callable[[SpeechSegment, RTPStreamInfo], None]] = None,
        correlation_manager: Optional[ChannelCorrelationManager] = None
    ):
        self.on_audio_data = on_audio_data
        self.on_speech_segment = on_speech_segment
        self.correlation_manager = correlation_manager
        self.streams: Dict[int, RTPStreamHandler] = {}
        self.transport = None
        self.logger = logging.getLogger(f"{__name__}.RTPUDPServer")
        
    def connection_made(self, transport):
        """Called when connection is made."""
        self.transport = transport
        self.logger.info("RTP UDP server started")
    
    def datagram_received(self, data, addr):
        """Called when a datagram is received."""
        try:
            # Parse RTP packet
            packet = self._parse_rtp_packet(data)
            if not packet:
                return
            
            # Get or create stream handler
            ssrc = packet.ssrc
            if ssrc not in self.streams:
                # Try to find channel ID from correlation manager
                channel_id = None
                if self.correlation_manager:
                    channel_info = self.correlation_manager.get_channel_by_ssrc(ssrc)
                    if channel_info:
                        channel_id = channel_info.channel_id
                
                self.streams[ssrc] = RTPStreamHandler(
                    ssrc=ssrc,
                    payload_type=packet.payload_type,
                    channel_id=channel_id,
                    correlation_manager=self.correlation_manager,
                    on_audio_data=self.on_audio_data,
                    on_speech_segment=self.on_speech_segment
                )
                self.logger.info(f"New RTP stream: SSRC={ssrc}, PT={packet.payload_type}, Channel={channel_id}")
            
            # Process packet
            stream_handler = self.streams[ssrc]
            success = stream_handler.process_packet(packet)
            
            if not success:
                self.logger.error(f"Failed to process packet for SSRC {ssrc}")
            
        except Exception as e:
            self.logger.error(f"Error processing datagram from {addr}: {e}")
    
    def _parse_rtp_packet(self, data: bytes) -> Optional[RTPPacket]:
        """Parse RTP packet from raw data using the static method."""
        return RTPPacket.parse_rtp_packet(data)
    
    def error_received(self, exc):
        """Called when an error occurs."""
        self.logger.error(f"RTP UDP server error: {exc}")
    
    def connection_lost(self, exc):
        """Called when connection is lost."""
        if exc:
            self.logger.error(f"RTP UDP server connection lost: {exc}")
        else:
            self.logger.info("RTP UDP server connection closed")
    
    def get_stream_info(self, ssrc: int) -> Optional[RTPStreamInfo]:
        """Get information about a specific stream."""
        stream_handler = self.streams.get(ssrc)
        return stream_handler.info if stream_handler else None
    
    def get_all_streams(self) -> Dict[int, RTPStreamInfo]:
        """Get information about all streams."""
        return {ssrc: handler.info for ssrc, handler in self.streams.items()}
    
    def remove_stream(self, ssrc: int) -> bool:
        """Remove a stream handler."""
        if ssrc in self.streams:
            del self.streams[ssrc]
            self.logger.info(f"Removed stream SSRC {ssrc}")
            return True
        return False


class RTPStreamManager:
    """Manages RTP streams and UDP server."""
    
    def __init__(self, host: str = "0.0.0.0", port: int = 5004, correlation_manager: Optional[ChannelCorrelationManager] = None):
        self.host = host
        self.port = port
        self.correlation_manager = correlation_manager
        self.server = None
        self.transport = None
        self.protocol = None
        self.logger = logging.getLogger(f"{__name__}.RTPStreamManager")
        
    async def start(
        self, 
        on_audio_data: Callable[[bytes, RTPStreamInfo], None],
        on_speech_segment: Optional[Callable[[SpeechSegment, RTPStreamInfo], None]] = None
    ) -> bool:
        """Start the RTP UDP server."""
        try:
            # Create UDP server
            loop = asyncio.get_event_loop()
            self.protocol = RTPUDPServer(on_audio_data, on_speech_segment, self.correlation_manager)
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: self.protocol,
                local_addr=(self.host, self.port)
            )
            
            self.logger.info(f"RTP UDP server started on {self.host}:{self.port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start RTP UDP server: {e}")
            return False
    
    async def stop(self):
        """Stop the RTP UDP server."""
        try:
            if self.transport:
                self.transport.close()
                self.logger.info("RTP UDP server stopped")
        except Exception as e:
            self.logger.error(f"Error stopping RTP UDP server: {e}")
    
    def get_stream_info(self, ssrc: int) -> Optional[RTPStreamInfo]:
        """Get information about a specific stream."""
        if self.protocol:
            return self.protocol.get_stream_info(ssrc)
        return None
    
    def get_all_streams(self) -> Dict[int, RTPStreamInfo]:
        """Get information about all streams."""
        if self.protocol:
            return self.protocol.get_all_streams()
        return {}
    
    def remove_stream(self, ssrc: int) -> bool:
        """Remove a stream handler."""
        if self.protocol:
            return self.protocol.remove_stream(ssrc)
        return False
