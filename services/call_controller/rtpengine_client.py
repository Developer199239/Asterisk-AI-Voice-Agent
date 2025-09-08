import aiohttp
from typing import Dict, Any, Optional
from structlog.stdlib import get_logger

from shared.config import RTPEngineConfig

logger = get_logger()


class RTPEngineClient:
    """Client for interacting with the RTPEngine."""

    def __init__(self, config: RTPEngineConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self):
        """Create an aiohttp ClientSession."""
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession()
        logger.info("RTPEngineClient session created")

    async def disconnect(self):
        """Close the aiohttp ClientSession."""
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("RTPEngineClient session closed")

    async def _send_request(self, command: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Send a request to the RTPEngine."""
        if not self._session:
            raise ConnectionError("RTPEngineClient is not connected. Call connect() first.")

        url = self.config.rtpengine_url
        payload = {"command": command, **params}
        try:
            async with self._session.post(url, json=payload) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Error sending request to RTPEngine: {e}", command=command, params=params)
            return None

    async def offer(self, call_id: str, sdp: str = "v=0\no=- 0 0 IN IP4 127.0.0.1\ns=-\nc=IN IP4 127.0.0.1\nt=0 0\nm=audio 16404 RTP/AVP 0 8 101\na=rtpmap:0 PCMU/8000\na=rtpmap:8 PCMA/8000\na=rtpmap:101 telephone-event/8000\na=fmtp:101 0-16\na=sendrecv\n") -> Optional[Dict[str, Any]]:
        """Send an 'offer' command to RTPEngine."""
        params = {
            "call-id": call_id,
            "sdp": sdp,
            "from-tag": f"{call_id}-from",
            "to-tag": f"{call_id}-to",
            "ICE": "remove",
            "replace": ["origin", "session-connection"],
        }
        return await self._send_request("offer", params)

    async def answer(self, call_id: str, sdp: str) -> Optional[Dict[str, Any]]:
        """Send an 'answer' command to RTPEngine."""
        params = {
            "call-id": call_id,
            "sdp": sdp,
            "from-tag": f"{call_id}-from",
            "to-tag": f"{call_id}-to",
        }
        return await self._send_request("answer", params)

    async def delete(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Send a 'delete' command to RTPEngine."""
        params = {
            "call-id": call_id,
            "from-tag": f"{call_id}-from",
            "to-tag": f"{call_id}-to",
        }
        return await self._send_request("delete", params)

    async def ping(self) -> bool:
        """Check the status of the RTPEngine."""
        result = await self._send_request("ping", {})
        return result is not None and result.get("result") == "pong"
