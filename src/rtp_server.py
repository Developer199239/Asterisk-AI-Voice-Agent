"""
RTP Server for External Media Integration with Asterisk.
Handles bidirectional RTP audio streams for AI voice agent.
"""

import asyncio
import socket
import struct
import audioop
import logging
import time
from typing import Dict, Optional, Callable, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class RTPSession:
    """Represents an active RTP session for a call."""
    call_id: str
    local_port: int
    remote_host: str
    remote_port: int
    socket: socket.socket
    sequence_number: int
    timestamp: int
    ssrc: int
    created_at: float
    last_packet_at: float
    # Enhanced fields for jitter buffering and monitoring
    expected_sequence: int = 0
    packet_loss_count: int = 0
    last_sequence: int = 0
    jitter_buffer: list = None
    frames_received: int = 0
    frames_processed: int = 0
    
    def __post_init__(self):
        if self.jitter_buffer is None:
            self.jitter_buffer = []

class RTPServer:
    """
    RTP Server for handling bidirectional audio streams with Asterisk External Media.
    
    This server:
    1. Receives RTP packets from Asterisk (caller audio)
    2. Forwards audio to AI pipeline for processing
    3. Receives processed audio from AI pipeline
    4. Sends RTP packets back to Asterisk (AI response audio)
    """
    
    def __init__(self, host: str, port: int, engine_callback: Callable, codec: str = "ulaw"):
        self.host = host
        self.port = port
        self.engine_callback = engine_callback
        self.codec = codec
        self.sessions: Dict[str, RTPSession] = {}
        self.ssrc_to_call_id: Dict[int, str] = {}  # SSRC mapping
        self.running = False
        self.server_task: Optional[asyncio.Task] = None
        self.server_socket: Optional[socket.socket] = None
        
        # RTP constants
        self.RTP_VERSION = 2
        self.RTP_PAYLOAD_TYPE_ULAW = 0
        self.RTP_HEADER_SIZE = 12
        self.SAMPLE_RATE = 8000
        self.SAMPLES_PER_PACKET = 160  # 20ms at 8kHz
        
        logger.info(f"RTP Server initialized - Host: {host}, Port: {port}")
    
    async def start(self):
        """Start the RTP server."""
        if self.running:
            logger.warning("RTP server already running")
            return
        
        try:
            # Create UDP socket for RTP
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.setblocking(False)
            
            self.running = True
            self.server_task = asyncio.create_task(self._rtp_receiver())
            
            logger.info(f"RTP Server started - Host: {self.host}, Port: {self.port}, Codec: {self.codec}")
            
        except Exception as e:
            logger.error(f"Failed to start RTP server: {e}")
            raise
    
    async def stop(self):
        """Stop the RTP server and cleanup all sessions."""
        self.running = False
        
        # Cancel server task
        if self.server_task:
            self.server_task.cancel()
            try:
                await self.server_task
            except asyncio.CancelledError:
                pass
        
        # Close server socket
        if self.server_socket:
            self.server_socket.close()
        
        # Close all active sessions
        for session in list(self.sessions.values()):
            await self._cleanup_session(session)
        
        logger.info("RTP Server stopped")
    
    async def _rtp_receiver(self):
        """Main RTP receiver loop."""
        logger.info("RTP receiver started", host=self.host, port=self.port)
        
        while self.running:
            try:
                # Receive RTP packet
                data, addr = await asyncio.get_event_loop().sock_recvfrom(self.server_socket, 1500)
                
                # Parse RTP header
                if len(data) >= self.RTP_HEADER_SIZE:
                    # Correct RTP header parsing
                    b0, b1 = data[0], data[1]
                    version = b0 >> 6
                    pt = b1 & 0x7F
                    m = (b1 >> 7) & 0x01
                    sequence = struct.unpack('!H', data[2:4])[0]
                    timestamp = struct.unpack('!I', data[4:8])[0]
                    ssrc = struct.unpack('!I', data[8:12])[0]
                    
                    # Validate RTP version
                    if version != self.RTP_VERSION:
                        logger.warning("Invalid RTP version", version=version, expected=self.RTP_VERSION)
                        continue
                    
                    # Extract audio payload
                    audio_payload = data[self.RTP_HEADER_SIZE:]
                    
                    # Find or create session based on SSRC
                    call_id = self.ssrc_to_call_id.get(ssrc)
                    if not call_id:
                        # New SSRC - create session
                        call_id = f"call_{ssrc}_{int(time.time())}"
                        await self._create_session_from_ssrc(call_id, ssrc, addr)
                        self.ssrc_to_call_id[ssrc] = call_id
                        logger.info("New RTP session created", call_id=call_id, ssrc=ssrc, addr=addr)
                    
                    # Process packet and call engine with SSRC directly
                    logger.debug("RTP packet received", ssrc=ssrc, sequence=sequence, size=len(audio_payload), addr=addr)
                    await self._process_rtp_packet_with_ssrc(ssrc, sequence, timestamp, audio_payload)
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logger.error("RTP receiver error", error=str(e))
                break
        
        logger.info("RTP receiver stopped")
    
    async def _create_session_from_ssrc(self, call_id: str, ssrc: int, addr: tuple):
        """Create a new RTP session from SSRC."""
        session = RTPSession(
            call_id=call_id,
            local_port=self.port,
            remote_host=addr[0],
            remote_port=addr[1],
            socket=None,  # Not used in new architecture
            sequence_number=0,
            timestamp=0,
            ssrc=ssrc,
            created_at=time.time(),
            last_packet_at=time.time()
        )
        
        self.sessions[call_id] = session
        logger.info("RTP session created from SSRC", call_id=call_id, ssrc=ssrc, addr=addr)
    
    async def _process_rtp_packet_with_ssrc(self, ssrc: int, sequence: int, timestamp: int, audio_payload: bytes):
        """Process an RTP packet and call engine with SSRC directly."""
        # Get call_id from SSRC mapping
        call_id = self.ssrc_to_call_id.get(ssrc)
        if not call_id:
            logger.warning("No call_id found for SSRC", ssrc=ssrc)
            return
        
        if call_id not in self.sessions:
            logger.warning("No session found for call_id", call_id=call_id, ssrc=ssrc)
            return
        
        session = self.sessions[call_id]
        session.frames_received += 1
        session.last_packet_at = time.time()
        
        # Sequence validation and loss detection
        if session.expected_sequence == 0:
            session.expected_sequence = sequence
        else:
            expected = session.expected_sequence
            if sequence != expected:
                if sequence > expected:
                    # Packet loss detected
                    lost_packets = sequence - expected
                    session.packet_loss_count += lost_packets
                    logger.debug("Packet loss detected", 
                               ssrc=ssrc, 
                               expected=expected, 
                               received=sequence, 
                               lost=lost_packets)
                else:
                    # Out of order packet
                    logger.debug("Out of order packet", 
                               ssrc=ssrc, 
                               expected=expected, 
                               received=sequence)
        
        session.expected_sequence = sequence + 1
        session.last_sequence = sequence
        
        # Decode audio based on codec
        if self.codec == "ulaw":
            pcm_data = audioop.ulaw2lin(audio_payload, 2)  # Convert ulaw to PCM16
        elif self.codec == "slin16":
            pcm_data = audio_payload  # Already PCM16
        else:
            logger.error("Unsupported codec", codec=self.codec)
            return
        
        # Resample from 8kHz to 16kHz
        pcm_16k = self._resample_8k_to_16k(pcm_data)
        
        # Forward to engine with SSRC directly
        try:
            await self.engine_callback(ssrc, pcm_16k)
            session.frames_processed += 1
        except Exception as e:
            logger.error("Error in engine callback", ssrc=ssrc, error=str(e))

    async def _process_rtp_packet(self, call_id: str, ssrc: int, sequence: int, timestamp: int, audio_payload: bytes):
        """Process an RTP packet with jitter buffering and codec conversion."""
        if call_id not in self.sessions:
            logger.warning("No session found for call", call_id=call_id)
            return
        
        session = self.sessions[call_id]
        session.frames_received += 1
        session.last_packet_at = time.time()
        
        # Sequence validation and loss detection
        if session.expected_sequence == 0:
            session.expected_sequence = sequence
        else:
            expected = session.expected_sequence
            if sequence != expected:
                if sequence > expected:
                    # Packet loss detected
                    lost_packets = sequence - expected
                    session.packet_loss_count += lost_packets
                    logger.debug("Packet loss detected", 
                               call_id=call_id, 
                               expected=expected, 
                               received=sequence, 
                               lost=lost_packets)
                else:
                    # Out of order packet
                    logger.debug("Out of order packet", 
                               call_id=call_id, 
                               expected=expected, 
                               received=sequence)
        
        session.expected_sequence = sequence + 1
        session.last_sequence = sequence
        
        # Decode audio based on codec
        if self.codec == "ulaw":
            pcm_data = audioop.ulaw2lin(audio_payload, 2)  # Convert ulaw to PCM16
        elif self.codec == "slin16":
            pcm_data = audio_payload  # Already PCM16
        else:
            logger.error("Unsupported codec", codec=self.codec)
            return
        
        # Resample from 8kHz to 16kHz
        pcm_16k = self._resample_8k_to_16k(pcm_data)
        
        # Forward to engine
        try:
            await self.engine_callback(call_id, pcm_16k)
            session.frames_processed += 1
        except Exception as e:
            logger.error("Error in engine callback", call_id=call_id, error=str(e))
    
    def _resample_8k_to_16k(self, pcm_8k: bytes) -> bytes:
        """Resample PCM16 8kHz to 16kHz using audioop.ratecv."""
        try:
            # Use audioop.ratecv for proper resampling
            pcm_16k, _ = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, None)
            return pcm_16k
        except Exception as e:
            logger.error("Resampling failed", error=str(e))
            return pcm_8k  # Return original if resampling fails
    
    def get_call_id_for_ssrc(self, ssrc: int) -> Optional[str]:
        """Get call ID for a given SSRC."""
        return self.ssrc_to_call_id.get(ssrc)
    
    def map_ssrc_to_call_id(self, ssrc: int, call_id: str):
        """Manually map an SSRC to a call ID (for ExternalMedia integration)."""
        self.ssrc_to_call_id[ssrc] = call_id
        logger.info("SSRC mapped to call ID", ssrc=ssrc, call_id=call_id)
    
    
    async def cleanup_session(self, call_id: str):
        """Cleanup RTP session for a call."""
        if call_id in self.sessions:
            session = self.sessions[call_id]
            await self._cleanup_session(session)
            del self.sessions[call_id]
            logger.info(f"RTP session cleaned up for call {call_id}")
    
    
    async def _cleanup_session(self, session: RTPSession):
        """Cleanup a single RTP session."""
        try:
            # Remove SSRC mapping
            if session.ssrc in self.ssrc_to_call_id:
                del self.ssrc_to_call_id[session.ssrc]
            
            logger.debug("RTP session cleaned up", 
                        call_id=session.call_id, 
                        ssrc=session.ssrc,
                        frames_received=session.frames_received,
                        frames_processed=session.frames_processed)
            
        except Exception as e:
            logger.error("Error cleaning up RTP session", 
                        call_id=session.call_id, 
                        error=str(e))
    
    def get_session_info(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get information about an RTP session."""
        if call_id not in self.sessions:
            return None
        
        session = self.sessions[call_id]
        return {
            "call_id": session.call_id,
            "local_port": session.local_port,
            "remote_host": session.remote_host,
            "remote_port": session.remote_port,
            "sequence_number": session.sequence_number,
            "timestamp": session.timestamp,
            "ssrc": session.ssrc,
            "created_at": session.created_at,
            "last_packet_at": session.last_packet_at,
            "active": time.time() - session.last_packet_at < 30  # 30 second timeout
        }
    
    def get_stats(self) -> Dict[str, Any]:
        """Get RTP server statistics."""
        active_sessions = sum(1 for s in self.sessions.values() if time.time() - s.last_packet_at < 30)
        total_frames_received = sum(s.frames_received for s in self.sessions.values())
        total_frames_processed = sum(s.frames_processed for s in self.sessions.values())
        total_packet_loss = sum(s.packet_loss_count for s in self.sessions.values())
        
        return {
            "running": self.running,
            "host": self.host,
            "port": self.port,
            "codec": self.codec,
            "total_sessions": len(self.sessions),
            "active_sessions": active_sessions,
            "total_frames_received": total_frames_received,
            "total_frames_processed": total_frames_processed,
            "total_packet_loss": total_packet_loss,
            "ssrc_mappings": len(self.ssrc_to_call_id)
        }
    
    def get_session_stats(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a specific RTP session."""
        if call_id not in self.sessions:
            return None
        
        session = self.sessions[call_id]
        return {
            "call_id": session.call_id,
            "ssrc": session.ssrc,
            "remote_host": session.remote_host,
            "remote_port": session.remote_port,
            "frames_received": session.frames_received,
            "frames_processed": session.frames_processed,
            "packet_loss_count": session.packet_loss_count,
            "last_sequence": session.last_sequence,
            "expected_sequence": session.expected_sequence,
            "created_at": session.created_at,
            "last_packet_at": session.last_packet_at,
            "active": time.time() - session.last_packet_at < 30
        }
