import asyncio
import socket
import structlog

logger = structlog.get_logger(__name__)

class UDPServerProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        logger.info("UDP transport connection made")
        self.transport = transport

    def datagram_received(self, data, addr):
        logger.info(f"Received {len(data)} bytes from {addr}")
        # Here we would parse RTP and forward to STT

    def error_received(self, exc):
        logger.error(f"UDP server error: {exc}")

    def connection_lost(self, exc):
        logger.warning("UDP transport connection lost")


class UDPServer:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.transport = None
        self.protocol = None
        self._is_running = False

    async def start(self):
        logger.info(f"Starting UDP server on {self.host}:{self.port}...")
        loop = asyncio.get_running_loop()
        try:
            self.transport, self.protocol = await loop.create_datagram_endpoint(
                lambda: UDPServerProtocol(),
                local_addr=(self.host, self.port)
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
    server = UDPServer('0.0.0.0', 54321)
    try:
        await server.start()
    except KeyboardInterrupt:
        server.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
