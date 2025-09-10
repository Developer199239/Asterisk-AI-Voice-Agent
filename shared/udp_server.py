import asyncio
from typing import Callable, Coroutine
import structlog

logger = structlog.get_logger(__name__)

class UDPServer:
    def __init__(self, on_data: Callable[[bytes, tuple], Coroutine]):
        self.on_data = on_data
        self.transport = None
        self.host = None
        self.port = None

    class UDPProtocol(asyncio.DatagramProtocol):
        def __init__(self, on_data: Callable[[bytes, tuple], Coroutine]):
            self.on_data = on_data
            self.transport = None
            # Get the running event loop in the constructor, which runs in the main thread
            self.loop = asyncio.get_running_loop()
            super().__init__()

        def connection_made(self, transport):
            self.transport = transport
            logger.info("UDP server connection made", transport=transport)

        def datagram_received(self, data, addr):
            # Use call_soon_threadsafe to safely schedule the coroutine from the I/O thread
            self.loop.call_soon_threadsafe(asyncio.create_task, self.on_data(data, addr))

        def error_received(self, exc):
            logger.error("UDP server error", exc=exc)

        def connection_lost(self, exc):
            logger.warning("UDP transport connection lost", exc=exc)

    async def start(self, host: str, port: int):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(
            lambda: self.UDPProtocol(self.on_data),
            local_addr=(host, port)
        )
        # Store the actual host and port the OS is listening on
        self.host, self.port = self.transport.get_extra_info('sockname')
        logger.info(f"UDP Server listening on {self.host}:{self.port}")

    async def send(self, data: bytes, addr: tuple):
        if self.transport:
            self.transport.sendto(data, addr)
        else:
            logger.warning("UDP transport not available, cannot send data.")

    def stop(self):
        if self.transport:
            self.transport.close()
            logger.info("UDP server stopped.")
