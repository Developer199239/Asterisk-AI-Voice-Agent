import asyncio
import socket
import structlog
from typing import Callable, Optional

logger = structlog.get_logger(__name__)

class UDPServerProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_datagram: Callable):
        self.on_datagram = on_datagram
        super().__init__()

    def connection_made(self, transport):
        self.transport = transport
        logger.info("UDP transport connection made")

    def datagram_received(self, data, addr):
        asyncio.create_task(self.on_datagram(data, addr))

    def error_received(self, exc):
        logger.error("UDP connection error", exc_info=exc)

    def connection_lost(self, exc):
        logger.warning("UDP transport connection lost")


class UDPServer:
    def __init__(self, host: str, port: int, on_datagram: Callable):
        self.host = host
        self.port = port
        self.on_datagram = on_datagram
        self.transport = None
        self.protocol = None
        self._is_running = False

    async def start(self):
        logger.info(f"Starting UDP server on {self.host}:{self.port}...")
        loop = asyncio.get_running_loop()
        try:
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: UDPServerProtocol(self.on_datagram),
                local_addr=(self.host, self.port),
                reuse_port=True
            )
            self._is_running = True
            logger.info("UDP server is running.")
            # Keep it running
            while self._is_running:
                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"Failed to start UDP server: {e}", exc_info=True)

    def stop(self):
        logger.info("Stopping UDP server...")
        self._is_running = False
        if self.transport:
            self.transport.close()
        logger.info("UDP server stopped.")

async def main():
    server = UDPServer('0.0.0.0', 54322, lambda data, addr: logger.info("Received datagram", source_addr=addr, size=len(data)))
    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
