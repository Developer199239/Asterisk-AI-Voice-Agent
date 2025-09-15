import asyncio
import uuid
from typing import Optional, Callable, Dict, Any

from .logging_config import get_logger

logger = get_logger(__name__)


class AudioSocketServer:
    """
    Minimal AudioSocket TCP server scaffold.
    Accepts inbound TCP connections from Asterisk AudioSocket and logs activity.

    Note: This is an initial scaffold to prepare for full-duplex streaming.
    It currently reads and discards data. Integration with providers will land
    in the streaming phase (downstream_mode == 'stream').
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8090,
                 on_audio: Optional[Callable[[str, bytes], None]] = None,
                 on_accept: Optional[Callable[[str], None]] = None,
                 on_close: Optional[Callable[[str], None]] = None):
        self.host = host
        self.port = port
        self.on_audio = on_audio
        self.on_accept = on_accept
        self.on_close = on_close
        self._server: Optional[asyncio.base_events.Server] = None
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._new_conn_queue: asyncio.Queue = asyncio.Queue()

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        sockets = ", ".join(str(s.getsockname()) for s in self._server.sockets or [])
        logger.info("AudioSocket server listening", sockets=sockets)

    async def stop(self):
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            logger.info("AudioSocket server stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info('peername')
        conn_id = uuid.uuid4().hex[:12]
        self._connections[conn_id] = {
            "reader": reader,
            "writer": writer,
            "peer": peer,
            # Expect an initial AudioSocket/1.0 header from Asterisk
            "header_pending": True,
            "header_buf": bytearray(),
            "out_buf": bytearray(),
            "format": 'ulaw',
            "rate": 8000,
        }
        logger.info("AudioSocket connection accepted", peer=peer, conn_id=conn_id)
        
        # AudioSocket connection established - ready to receive/send raw ulaw frames
        logger.debug("AudioSocket connection ready for audio data", conn_id=conn_id)
        
        # Announce new connection for assignment by engine
        try:
            self._new_conn_queue.put_nowait(conn_id)
        except asyncio.QueueFull:
            logger.warning("New connection queue full; connection may not be assignable", conn_id=conn_id)
        # Notify accept callback to allow immediate pairing
        try:
            if self.on_accept:
                self.on_accept(conn_id)
        except Exception:
            logger.debug("on_accept handler error", exc_info=True)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                conn = self._connections.get(conn_id)
                if not conn:
                    continue
                buf: bytearray = conn.get("in_buf") or bytearray()
                buf.extend(data)
                conn["in_buf"] = buf
                # Parse TLV frames: type(1) len(2 big-endian) payload
                while True:
                    if len(buf) < 3:
                        break
                    ftype = buf[0]
                    flen = (buf[1] << 8) | buf[2]
                    if len(buf) < 3 + flen:
                        break
                    payload = bytes(buf[3:3+flen])
                    del buf[:3+flen]
                    try:
                        if ftype == 0x01 and flen == 16:
                            conn['uuid'] = payload
                            logger.info("Received UUID from client", conn_id=conn_id)
                        elif ftype == 0x10 and flen > 0:
                            if self.on_audio:
                                self.on_audio(conn_id, payload)
                        elif ftype == 0x00:
                            logger.info("Terminate received from client", conn_id=conn_id)
                            raise asyncio.CancelledError()
                        elif ftype == 0xFF:
                            logger.warning("Error packet received from client", conn_id=conn_id)
                        else:
                            logger.debug("Unknown TLV type", conn_id=conn_id, ftype=hex(ftype), flen=flen)
                    except Exception:
                        logger.debug("Error handling TLV frame", conn_id=conn_id, exc_info=True)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.warning("AudioSocket connection error", exc_info=True)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            self._connections.pop(conn_id, None)
            logger.info("AudioSocket connection closed", peer=peer, conn_id=conn_id)
            # Notify close callback for cleanup
            try:
                if self.on_close:
                    self.on_close(conn_id)
            except Exception:
                logger.debug("on_close handler error", exc_info=True)

    async def await_connection(self, timeout: Optional[float] = None) -> Optional[str]:
        """Wait for the next incoming connection and return its conn_id."""
        try:
            return await asyncio.wait_for(self._new_conn_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def try_get_connection_nowait(self) -> Optional[str]:
        """Non-blocking fetch of next pending connection id, if any."""
        try:
            return self._new_conn_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def close_connection(self, conn_id: str):
        """Close a specific connection by ID."""
        conn = self._connections.get(conn_id)
        if not conn:
            return
        writer: asyncio.StreamWriter = conn.get("writer")
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        finally:
            self._connections.pop(conn_id, None)

    async def send_audio(self, conn_id: str, data: bytes):
        """Send downstream audio (PCM16LE@8k) framed as TLV type 0x10."""
        conn = self._connections.get(conn_id)
        if not conn:
            return
        writer: asyncio.StreamWriter = conn.get("writer")
        try:
            flen = len(data)
            header = bytes([0x10, (flen >> 8) & 0xFF, flen & 0xFF])
            writer.write(header + data)
            await writer.drain()
        except Exception:
            logger.debug("Error sending audio to AudioSocket", conn_id=conn_id, exc_info=True)

    def get_connection_info(self, conn_id: str) -> Dict[str, Any]:
        return dict(self._connections.get(conn_id, {}))
