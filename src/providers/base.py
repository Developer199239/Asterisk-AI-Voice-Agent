from abc import ABC, abstractmethod
from typing import List

class AIProviderInterface(ABC):
    """
    Abstract Base Class for AI Providers.

    This class defines the contract that all AI provider implementations must follow.
    """

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
