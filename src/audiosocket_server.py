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

    def __init__(self, host: str = "127.0.0.1", port: int = 8090, on_audio: Optional[Callable[[str, bytes], None]] = None):
        self.host = host
        self.port = port
        self.on_audio = on_audio
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
            # AudioSocket protocol typically sends a text header first; parse once
            "header_pending": True,
            "header_buf": bytearray(),
        }
        logger.info("AudioSocket connection accepted", peer=peer, conn_id=conn_id)
        # Announce new connection for assignment by engine
        try:
            self._new_conn_queue.put_nowait(conn_id)
        except asyncio.QueueFull:
            logger.warning("New connection queue full; connection may not be assignable", conn_id=conn_id)
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                if self.on_audio:
                    try:
                        conn = self._connections.get(conn_id)
                        if conn and conn.get("header_pending"):
                            # Accumulate until we detect header terminator (\r\n\r\n or \n\n)
                            buf: bytearray = conn["header_buf"]
                            buf.extend(data)
                            raw = bytes(buf)
                            # Find header end
                            end = -1
                            for delim in (b"\r\n\r\n", b"\n\n"):
                                idx = raw.find(delim)
                                if idx != -1:
                                    end = idx + len(delim)
                                    break
                            if end != -1:
                                # Drop header and forward remainder
                                payload = raw[end:]
                                conn["header_pending"] = False
                                conn["header_buf"] = bytearray()  # free
                                if payload:
                                    self.on_audio(conn_id, payload)
                                continue
                            # Safety: if header grows too large, assume no header and pass through
                            if len(raw) > 2048:
                                conn["header_pending"] = False
                                conn["header_buf"] = bytearray()
                                self.on_audio(conn_id, raw)
                            # else keep accumulating
                        else:
                            self.on_audio(conn_id, data)
                    except Exception:
                        # Non-fatal
                        logger.debug("on_audio handler error", exc_info=True)
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

    async def await_connection(self, timeout: Optional[float] = None) -> Optional[str]:
        """Wait for the next incoming connection and return its conn_id."""
        try:
            return await asyncio.wait_for(self._new_conn_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
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
