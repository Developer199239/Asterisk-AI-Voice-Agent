import random
import struct
from .logging_config import get_logger

logger = get_logger(__name__)

class RTPPacketizer:
    def __init__(self, ssrc):
        self.sequence_number = random.randint(0, 65535)
        self.timestamp = random.randint(0, 4294967295)
        self.ssrc = ssrc
        logger.debug(f"RTP Packetizer initialized.", initial_seq=self.sequence_number, initial_ts=self.timestamp, ssrc=self.ssrc)

    def packetize(self, payload: bytes, payload_type: int = 0) -> bytes:
        header = struct.pack('!BBHII',
            0b10000000,  # Version 2, no padding, no extension, no CSRC
            payload_type,
            self.sequence_number,
            self.timestamp,
            self.ssrc
        )
        self.sequence_number = (self.sequence_number + 1) % 65536
        # ulaw is 1 byte per sample. Timestamp increases by number of samples.
        self.timestamp = (self.timestamp + len(payload)) % 4294967296
        return header + payload
