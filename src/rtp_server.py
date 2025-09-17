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

class RTPServer:
    """
    RTP Server for handling bidirectional audio streams with Asterisk External Media.
    
    This server:
    1. Receives RTP packets from Asterisk (caller audio)
    2. Forwards audio to AI pipeline for processing
    3. Receives processed audio from AI pipeline
    4. Sends RTP packets back to Asterisk (AI response audio)
    """
    
    def __init__(self, host: str, port_range: tuple, engine_callback: Callable):
        self.host = host
        self.port_range = port_range
        self.engine_callback = engine_callback
        self.sessions: Dict[str, RTPSession] = {}
        self.port_pool = list(range(port_range[0], port_range[1]))
        self.used_ports = set()
        self.running = False
        self.server_task: Optional[asyncio.Task] = None
        
        # RTP constants
        self.RTP_VERSION = 2
        self.RTP_PAYLOAD_TYPE_ULAW = 0
        self.RTP_HEADER_SIZE = 12
        self.SAMPLE_RATE = 8000
        self.SAMPLES_PER_PACKET = 160  # 20ms at 8kHz
        
        logger.info(f"RTP Server initialized - Host: {host}, Port Range: {port_range}")
    
    async def start(self):
        """Start the RTP server."""
        if self.running:
            logger.warning("RTP server already running")
            return
        
        self.running = True
        logger.info("RTP Server started")
    
    async def stop(self):
        """Stop the RTP server and cleanup all sessions."""
        self.running = False
        
        # Close all active sessions
        for session in list(self.sessions.values()):
            await self._cleanup_session(session)
        
        logger.info("RTP Server stopped")
    
    async def create_session(self, call_id: str, remote_host: str = "127.0.0.1") -> int:
        """
        Create a new RTP session for a call.
        
        Args:
            call_id: Unique identifier for the call
            remote_host: Asterisk server host (usually 127.0.0.1)
            
        Returns:
            Local port number for RTP communication
            
        Raises:
            RuntimeError: If no ports available or session creation fails
        """
        if call_id in self.sessions:
            logger.warning(f"RTP session already exists for call {call_id}")
            return self.sessions[call_id].local_port
        
        # Allocate a port
        local_port = await self._allocate_port()
        if local_port is None:
            raise RuntimeError("No available RTP ports")
        
        try:
            # Create UDP socket for RTP
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind((self.host, local_port))
            sock.setblocking(False)
            
            # Create session
            session = RTPSession(
                call_id=call_id,
                local_port=local_port,
                remote_host=remote_host,
                remote_port=0,  # Will be set when we receive first packet
                socket=sock,
                sequence_number=0,
                timestamp=0,
                ssrc=hash(call_id) & 0xFFFFFFFF,
                created_at=time.time(),
                last_packet_at=time.time()
            )
            
            self.sessions[call_id] = session
            
            # Start RTP receiver task
            asyncio.create_task(self._rtp_receiver(session))
            
            logger.info(f"RTP session created for call {call_id} on port {local_port}")
            return local_port
            
        except Exception as e:
            # Cleanup on failure
            self.used_ports.discard(local_port)
            if call_id in self.sessions:
                del self.sessions[call_id]
            raise RuntimeError(f"Failed to create RTP session for {call_id}: {e}")
    
    async def send_audio(self, call_id: str, pcm_data: bytes):
        """
        Send PCM audio data to Asterisk via RTP.
        
        Args:
            call_id: Call identifier
            pcm_data: 16-bit PCM audio data
        """
        if call_id not in self.sessions:
            logger.warning(f"No RTP session found for call {call_id}")
            return
        
        session = self.sessions[call_id]
        
        try:
            # Convert PCM to ulaw
            ulaw_data = audioop.lin2ulaw(pcm_data, 2)
            
            # Build RTP packet
            rtp_header = struct.pack('!HHII',
                0x80,  # Version 2, no padding, no extension, no CSRC
                self.RTP_PAYLOAD_TYPE_ULAW,  # Payload type 0 (ulaw)
                session.sequence_number,
                session.timestamp
            )
            
            rtp_packet = rtp_header + ulaw_data
            
            # Send RTP packet
            await asyncio.get_event_loop().sock_sendto(
                session.socket, rtp_packet, (session.remote_host, session.remote_port)
            )
            
            # Update sequence number and timestamp
            session.sequence_number = (session.sequence_number + 1) % 65536
            session.timestamp += self.SAMPLES_PER_PACKET
            session.last_packet_at = time.time()
            
            logger.debug(f"Sent RTP packet for call {call_id} - Seq: {session.sequence_number-1}, TS: {session.timestamp-self.SAMPLES_PER_PACKET}")
            
        except Exception as e:
            logger.error(f"Failed to send RTP audio for call {call_id}: {e}")
    
    async def cleanup_session(self, call_id: str):
        """Cleanup RTP session for a call."""
        if call_id in self.sessions:
            session = self.sessions[call_id]
            await self._cleanup_session(session)
            del self.sessions[call_id]
            logger.info(f"RTP session cleaned up for call {call_id}")
    
    async def _allocate_port(self) -> Optional[int]:
        """Allocate an available port from the pool."""
        for port in self.port_pool:
            if port not in self.used_ports:
                self.used_ports.add(port)
                return port
        return None
    
    async def _rtp_receiver(self, session: RTPSession):
        """Receive RTP packets from Asterisk."""
        logger.info(f"RTP receiver started for call {session.call_id} on port {session.local_port}")
        
        while self.running and session.call_id in self.sessions:
            try:
                # Receive RTP packet
                data, addr = await asyncio.get_event_loop().sock_recvfrom(session.socket, 1500)
                
                # Update remote address if not set
                if session.remote_port == 0:
                    session.remote_host, session.remote_port = addr
                    logger.info(f"RTP remote address set for call {session.call_id}: {addr}")
                
                # Parse RTP header
                if len(data) >= self.RTP_HEADER_SIZE:
                    rtp_header = struct.unpack('!HHII', data[:self.RTP_HEADER_SIZE])
                    version, payload_type, sequence, timestamp = rtp_header
                    
                    # Validate RTP version
                    if (version >> 6) != self.RTP_VERSION:
                        logger.warning(f"Invalid RTP version for call {session.call_id}: {version >> 6}")
                        continue
                    
                    # Extract audio payload
                    audio_payload = data[self.RTP_HEADER_SIZE:]
                    
                    # Convert ulaw to PCM for AI processing
                    pcm_data = audioop.ulaw2lin(audio_payload, 2)
                    
                    # Forward to AI pipeline
                    try:
                        await self.engine_callback(session.call_id, pcm_data)
                    except Exception as e:
                        logger.error(f"Error in AI pipeline callback for call {session.call_id}: {e}")
                    
                    session.last_packet_at = time.time()
                    
                    logger.debug(f"Received RTP packet for call {session.call_id} - Seq: {sequence}, TS: {timestamp}, Payload: {len(audio_payload)} bytes")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self.running:
                    logger.error(f"RTP receiver error for call {session.call_id}: {e}")
                break
        
        logger.info(f"RTP receiver stopped for call {session.call_id}")
    
    async def _cleanup_session(self, session: RTPSession):
        """Cleanup a single RTP session."""
        try:
            # Release port
            self.used_ports.discard(session.local_port)
            
            # Close socket
            if session.socket:
                session.socket.close()
            
            logger.debug(f"RTP session cleaned up - Call: {session.call_id}, Port: {session.local_port}")
            
        except Exception as e:
            logger.error(f"Error cleaning up RTP session for call {session.call_id}: {e}")
    
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
        return {
            "running": self.running,
            "total_sessions": len(self.sessions),
            "active_sessions": active_sessions,
            "available_ports": len(self.port_pool) - len(self.used_ports),
            "used_ports": len(self.used_ports)
        }
