from abc import ABC, abstractmethod
from typing import List, Callable, Dict, Any

class AIProviderInterface(ABC):
    """
    Abstract Base Class for AI Providers.

    This class defines the contract that all AI provider implementations must follow.
    """
    def __init__(self, on_event: Callable[[Dict[str, Any]], None]):
        self.on_event = on_event

    @property
    @abstractmethod
    def supported_codecs(self) -> List[str]:
        """Returns a list of supported codec names, in order of preference."""
        pass

    @abstractmethod
    async def start_session(self, call_id: str, on_event: callable):
        """Initializes the connection to the AI provider for a new call."""
        pass

    @abstractmethod
    async def send_audio(self, audio_chunk: bytes):
        """Sends a chunk of audio data to the AI provider."""
        pass

    @abstractmethod
    async def stop_session(self):
        """Closes the connection and cleans up resources for the call."""
        pass

    # Optional: providers can override to describe codec/sample alignment characteristics.
    def describe_alignment(
        self,
        *,
        audiosocket_format: str,
        streaming_encoding: str,
        streaming_sample_rate: int,
    ) -> List[str]:
        """
        Return human-readable issues when the provider's implementation conflicts with
        the configured AudioSocket/streaming formats. Defaults to no findings.
        """
        return []
