"""
Foundational pipeline abstractions for composing STT, LLM, and TTS components.

This module defines lightweight async interfaces that individual adapters
(local server, Deepgram, OpenAI, Google, etc.) can implement. The
`PipelineOrchestrator` (see orchestrator.py) uses these contracts to build
per-call pipelines that the Engine can drive without being tied to any single
provider.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any


class Component(ABC):
    """Base class for all pipeline components."""

    async def start(self) -> None:
        """Warm up component resources (optional)."""

    async def stop(self) -> None:
        """Release resources (optional)."""

    async def open_call(self, call_id: str, options: Dict[str, Any]) -> None:
        """Prepare per-call state (optional)."""

    async def close_call(self, call_id: str) -> None:
        """Release per-call state (optional)."""

    async def validate_connectivity(self, options: Dict[str, Any]) -> Dict[str, Any]:
        """Validate component can connect to required services.
        
        Returns dict with:
            - healthy: bool - Whether component is ready
            - error: str - Error message if unhealthy
            - details: Dict[str, Any] - Additional diagnostic info
        
        Default implementation returns healthy=True.
        Components should override to test actual connectivity.
        """
        return {"healthy": True, "error": None, "details": {}}


class STTComponent(Component):
    """Speech-to-text component."""

    @abstractmethod
    async def transcribe(
        self,
        call_id: str,
        audio_pcm16: bytes,
        sample_rate_hz: int,
        options: Dict[str, Any],
    ) -> str:
        """Return a transcript for the provided PCM16 audio buffer."""


class LLMComponent(Component):
    """Language model component."""

    @abstractmethod
    async def generate(
        self,
        call_id: str,
        transcript: str,
        context: Dict[str, Any],
        options: Dict[str, Any],
    ) -> str:
        """Generate a response given transcript + context."""


class TTSComponent(Component):
    """Text-to-speech component."""

    @abstractmethod
    async def synthesize(
        self,
        call_id: str,
        text: str,
        options: Dict[str, Any],
    ) -> AsyncIterator[bytes]:
        """Yield audio frames (μ-law or PCM) for the supplied text."""


