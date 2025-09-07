"""
RTPEngine HTTP API Client

This module provides HTTP client functionality for controlling the rtpengine
media proxy, including port allocation and media stream management.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Tuple
import aiohttp
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type


logger = logging.getLogger(__name__)


class RTPEngineClient:
    """HTTP client for rtpengine media proxy control"""
    
    def __init__(self, host: str = "rtpengine", port: int = 2223):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def connect(self):
        """Initialize HTTP session"""
        try:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30),
                connector=aiohttp.TCPConnector(limit=100)
            )
            
            # Test connection
            await self.health_check()
            logger.info(f"✅ Connected to rtpengine at {self.host}:{self.port}")
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to rtpengine: {e}")
            raise
    
    async def disconnect(self):
        """Close HTTP session"""
        if self.session:
            await self.session.close()
        logger.info("Disconnected from rtpengine")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((ConnectionError, OSError, aiohttp.ClientError))
    )
    async def health_check(self) -> bool:
        """Check rtpengine health"""
        try:
            if not self.session:
                return False
            
            async with self.session.get(f"{self.base_url}/status") as response:
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"rtpengine status: {data}")
                    return True
                else:
                    logger.error(f"rtpengine health check failed: {response.status}")
                    return False
        except Exception as e:
            logger.error(f"rtpengine health check error: {e}")
            return False
    
    async def offer(self, call_id: str, sdp_offer: str, 
                   local_rtp_port: int, remote_rtp_port: int,
                   local_rtcp_port: int, remote_rtcp_port: int) -> Optional[Dict[str, Any]]:
        """
        Create media session with SDP offer
        
        Args:
            call_id: Unique call identifier
            sdp_offer: SDP offer from Asterisk
            local_rtp_port: Local RTP port for media
            local_rtcp_port: Local RTCP port for control
            remote_rtp_port: Remote RTP port for media
            remote_rtcp_port: Remote RTCP port for control
            
        Returns:
            RTPEngine response with SDP answer or None if failed
        """
        try:
            data = {
                "command": "offer",
                "call-id": call_id,
                "sdp": sdp_offer,
                "replace": ["origin", "session-connection"],
                "flags": ["generate-mid"],
                "media": {
                    "ICE": "remove",
                    "protocol": "RTP/AVP",
                    "rtcp-mux": ["demux"]
                },
                "rtp": {
                    "local-port": local_rtp_port,
                    "remote-port": remote_rtp_port
                },
                "rtcp": {
                    "local-port": local_rtcp_port,
                    "remote-port": remote_rtcp_port
                }
            }
            
            async with self.session.post(f"{self.base_url}/offer", json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"Created rtpengine session for call {call_id}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to create rtpengine session: {response.status} - {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error creating rtpengine session for call {call_id}: {e}")
            return None
    
    async def answer(self, call_id: str, sdp_answer: str) -> bool:
        """
        Update media session with SDP answer
        
        Args:
            call_id: Unique call identifier
            sdp_answer: SDP answer from remote party
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                "command": "answer",
                "call-id": call_id,
                "sdp": sdp_answer
            }
            
            async with self.session.post(f"{self.base_url}/answer", json=data) as response:
                if response.status == 200:
                    logger.info(f"Updated rtpengine session with answer for call {call_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to update rtpengine session: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error updating rtpengine session for call {call_id}: {e}")
            return False
    
    async def delete(self, call_id: str) -> bool:
        """
        Delete media session
        
        Args:
            call_id: Unique call identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                "command": "delete",
                "call-id": call_id
            }
            
            async with self.session.post(f"{self.base_url}/delete", json=data) as response:
                if response.status == 200:
                    logger.info(f"Deleted rtpengine session for call {call_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to delete rtpengine session: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error deleting rtpengine session for call {call_id}: {e}")
            return False
    
    async def query(self, call_id: str) -> Optional[Dict[str, Any]]:
        """
        Query media session status
        
        Args:
            call_id: Unique call identifier
            
        Returns:
            Session status information or None if failed
        """
        try:
            data = {
                "command": "query",
                "call-id": call_id
            }
            
            async with self.session.post(f"{self.base_url}/query", json=data) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"rtpengine session status for call {call_id}: {result}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to query rtpengine session: {response.status} - {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error querying rtpengine session for call {call_id}: {e}")
            return None
    
    async def start_recording(self, call_id: str, recording_path: str) -> bool:
        """
        Start recording media session
        
        Args:
            call_id: Unique call identifier
            recording_path: Path to save recording
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                "command": "start-recording",
                "call-id": call_id,
                "recording-path": recording_path
            }
            
            async with self.session.post(f"{self.base_url}/start-recording", json=data) as response:
                if response.status == 200:
                    logger.info(f"Started recording for call {call_id} to {recording_path}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to start recording: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error starting recording for call {call_id}: {e}")
            return False
    
    async def stop_recording(self, call_id: str) -> bool:
        """
        Stop recording media session
        
        Args:
            call_id: Unique call identifier
            
        Returns:
            True if successful, False otherwise
        """
        try:
            data = {
                "command": "stop-recording",
                "call-id": call_id
            }
            
            async with self.session.post(f"{self.base_url}/stop-recording", json=data) as response:
                if response.status == 200:
                    logger.info(f"Stopped recording for call {call_id}")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to stop recording: {response.status} - {error_text}")
                    return False
                    
        except Exception as e:
            logger.error(f"Error stopping recording for call {call_id}: {e}")
            return False
    
    async def get_stats(self) -> Optional[Dict[str, Any]]:
        """
        Get rtpengine statistics
        
        Returns:
            Statistics information or None if failed
        """
        try:
            async with self.session.get(f"{self.base_url}/stats") as response:
                if response.status == 200:
                    result = await response.json()
                    logger.debug(f"rtpengine stats: {result}")
                    return result
                else:
                    error_text = await response.text()
                    logger.error(f"Failed to get rtpengine stats: {response.status} - {error_text}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting rtpengine stats: {e}")
            return None


if __name__ == "__main__":
    # Test rtpengine client
    async def test_rtpengine_client():
        client = RTPEngineClient()
        
        try:
            await client.connect()
            
            # Test health check
            health = await client.health_check()
            print(f"✅ rtpengine health check: {health}")
            
            # Test stats
            stats = await client.get_stats()
            if stats:
                print(f"✅ rtpengine stats: {stats}")
            
        except Exception as e:
            print(f"❌ rtpengine test failed: {e}")
        finally:
            await client.disconnect()
    
    # Run test
    asyncio.run(test_rtpengine_client())
