import asyncio
import json
import uuid
from typing import Any, Dict, Optional

import aiohttp
from structlog.stdlib import get_logger

from shared.config import MediasoupConfig

logger = get_logger()


class MediasoupClient:
    """Client for interacting with a mediasoup server."""

    def __init__(self, config: MediasoupConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._pending_requests: Dict[str, asyncio.Future] = {}

    async def connect(self):
        """Connect to the mediasoup server."""
        if self.is_connected:
            logger.warning("Already connected to mediasoup")
            return

        self._session = aiohttp.ClientSession()
        try:
            self._ws = await self._session.ws_connect(self.config.ws_url)
            asyncio.create_task(self._listen())
            logger.info("Connected to mediasoup server")
        except aiohttp.ClientError as e:
            logger.error("Failed to connect to mediasoup", error=str(e))
            await self.disconnect()
            raise

    async def disconnect(self):
        """Disconnect from the mediasoup server."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        self._ws = None
        self._session = None
        logger.info("Disconnected from mediasoup server")

    @property
    def is_connected(self) -> bool:
        """Check if the client is connected."""
        return self._ws is not None and not self._ws.closed

    async def _listen(self):
        """Listen for incoming messages from the mediasoup server."""
        if not self._ws:
            return

        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                request_id = data.get("id")
                if request_id and request_id in self._pending_requests:
                    future = self._pending_requests.pop(request_id)
                    if "error" in data:
                        future.set_exception(Exception(data["error"]))
                    else:
                        future.set_result(data.get("data"))
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                logger.warning("Mediasoup WebSocket connection closed")
                break

    async def _send_request(self, method: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Send a request to the mediasoup server."""
        if not self.is_connected or not self._ws:
            raise ConnectionError("Not connected to mediasoup server")

        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future

        request = {
            "id": request_id,
            "method": method,
            "data": data or {},
        }
        await self._ws.send_json(request)

        try:
            return await asyncio.wait_for(future, timeout=self.config.request_timeout)
        except asyncio.TimeoutError:
            self._pending_requests.pop(request_id, None)
            raise TimeoutError(f"Mediasoup request '{method}' timed out")

    async def get_router_rtp_capabilities(self) -> Dict[str, Any]:
        """Get the RTP capabilities of the mediasoup router."""
        return await self._send_request("getRouterRtpCapabilities")

    async def create_webrtc_transport(self) -> Dict[str, Any]:
        """Create a new WebRTC transport."""
        return await self._send_request("createWebRtcTransport")

    async def create_plain_transport(self, rtcp_mux: bool = False, comedia: bool = True) -> Dict[str, Any]:
        """Create a new Plain transport."""
        data = {
            "rtcpMux": rtcp_mux,
            "comedia": comedia,
        }
        return await self._send_request("createPlainTransport", data)

    async def connect_transport(self, transport_id: str, dtls_parameters: Dict[str, Any]):
        """Connect a transport."""
        data = {
            "transportId": transport_id,
            "dtlsParameters": dtls_parameters,
        }
        await self._send_request("connectWebRtcTransport", data)

    async def produce(self, transport_id: str, kind: str, rtp_parameters: Dict[str, Any]) -> str:
        """Create a new producer."""
        data = {
            "transportId": transport_id,
            "kind": kind,
            "rtpParameters": rtp_parameters,
        }
        result = await self._send_request("produce", data)
        return result["id"]
