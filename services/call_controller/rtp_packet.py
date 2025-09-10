import struct
from dataclasses import dataclass

@dataclass
class RtpPacket:
    version: int
    padding: bool
    extension: bool
    csrc_count: int
    marker: bool
    payload_type: int
    sequence_number: int
    timestamp: int
    ssrc: int
    payload: bytes

    @classmethod
    def parse(cls, data: bytes):
        if len(data) < 12:
            raise ValueError("RTP packet must be at least 12 bytes long")

        header = data[:12]
        payload = data[12:]

        # Unpack the first 12 bytes of the header
        # The format string is:
        # ! - network byte order (big-endian)
        # B - unsigned char (1 byte)
        # B - unsigned char (1 byte)
        # H - unsigned short (2 bytes)
        # I - unsigned int (4 bytes)
        # I - unsigned int (4 bytes)
        first_byte, second_byte, sequence_number, timestamp, ssrc = struct.unpack('!BBHII', header)

        version = (first_byte >> 6) & 0b11
        padding = (first_byte >> 5) & 0b1 == 1
        extension = (first_byte >> 4) & 0b1 == 1
        csrc_count = first_byte & 0b1111

        marker = (second_byte >> 7) & 0b1 == 1
        payload_type = second_byte & 0b01111111

        return cls(
            version=version,
            padding=padding,
            extension=extension,
            csrc_count=csrc_count,
            marker=marker,
            payload_type=payload_type,
            sequence_number=sequence_number,
            timestamp=timestamp,
            ssrc=ssrc,
            payload=payload
        )
