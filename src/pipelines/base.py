"""
Foundational audio pipeline abstractions for in-memory, streaming STT/TTS.

These interfaces allow us to swap implementations (local, cloud) while keeping
the `Engine` and `ARI` layers stable. All implementations must be non-blocking
and asyncio-friendly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional


class AudioPipeline(ABC):
    """Abstract base class for streaming audio pipelines.

    Implementations handle:
    - Model lifecycle: start() to lazily load and warm models; stop() to cleanup
    - STT: process incoming ulaw/pcm audio chunks and emit completed transcripts
    - TTS: synthesize text as an async stream of ulaw/pcm chunks for playback
    """

    @abstractmethod
    async def start(self) -> None:
        """Initialize and warm models/resources.

        Called once at application startup (or when the Engine initializes the
        pipeline). Must return quickly or perform long work asynchronously.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Release resources and prepare for shutdown.

        Implementations should gracefully release memory and handles; this may
        be a no-op if models are intended to stay hot for the process lifetime.
        """

    @abstractmethod
    async def process_stt(self, audio_chunk: bytes) -> Optional[str]:
        """Process an incoming audio chunk and return a transcript if utterance ended.

        - Input chunks should be raw ulaw or PCM bytes as produced by our AudioSocket
          channel handler. Implementations may resample/convert as needed.
        - Should buffer internally and use VAD/end-of-speech detection.
        - Return a non-empty string only when a full utterance is recognized;
          otherwise return None to indicate more audio is needed.
        """

    @abstractmethod
    async def process_tts(self, text: str) -> AsyncIterator[bytes]:
        """Synthesize text to an async stream of audio chunks.

        - Yield ulaw or PCM frames suitable for immediate playback/packetization.
        - Streaming allows low-latency playback while synthesis continues.
        """


