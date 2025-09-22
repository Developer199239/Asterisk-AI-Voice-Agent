"""
Core data models for the Asterisk AI Voice Agent.

This module defines the typed data structures that replace the dict soup
in the original engine.py implementation.
"""

from dataclasses import dataclass, field
from typing import Optional, Set, Dict, Any
import time


@dataclass
class PlaybackRef:
    """Reference to an active audio playback."""
    playback_id: str
    call_id: str
    channel_id: str
    bridge_id: Optional[str]
    media_uri: str
    audio_file: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class CallSession:
    """Complete session state for a call."""
    # Core identifiers
    call_id: str              # canonical (caller_channel_id)
    caller_channel_id: str
    local_channel_id: Optional[str] = None
    external_media_id: Optional[str] = None
    external_media_call_id: Optional[str] = None
    bridge_id: Optional[str] = None
    
    # Provider and conversation state
    provider_name: str = "local"
    conversation_state: str = "greeting"  # greeting | listening | processing
    
    # Audio capture and TTS gating
    audio_capture_enabled: bool = False
    tts_playing: bool = False
    tts_tokens: Set[str] = field(default_factory=set)
    tts_active_count: int = 0
    
    # VAD and audio processing state
    vad_state: Dict[str, Any] = field(default_factory=dict)
    fallback_state: Dict[str, Any] = field(default_factory=dict)
    
    # Cleanup and lifecycle
    cleanup_after_tts: bool = False
    created_at: float = field(default_factory=time.time)
    
    def __post_init__(self):
        """Initialize default VAD and fallback state."""
        if not self.vad_state:
            self.vad_state = {
                "state": "listening",
                "speaking": False,
                "speech_real_start_fired": False,
                "pre_roll_buffer": b"",
                "utterance_buffer": b"",
                "utterance_id": 0,
                "last_utterance_end_ms": 0,
                "webrtc_speech_frames": 0,
                "webrtc_silence_frames": 0,
                "webrtc_last_decision": False,
                "audio_buffer": b"",
                "last_voice_ms": 0,
                "tts_playing": False
            }
        
        if not self.fallback_state:
            self.fallback_state = {
                "audio_buffer": b"",
                "last_vad_speech_time": time.time(),
                "buffer_start_time": None,
                "frame_count": 0
            }


@dataclass
class ProviderSession:
    """Session state for a provider connection."""
    call_id: str
    provider_name: str
    websocket_connected: bool = False
    input_mode: str = "pcm16_16k"  # pcm16_16k | pcm16_8k
    created_at: float = field(default_factory=time.time)


@dataclass
class TransportConfig:
    """Configuration for ExternalMedia transport settings."""
    transport_type: str = "externalmedia"  # Only ExternalMedia supported
    rtp_host: str = "0.0.0.0"
    rtp_port: int = 18080
    codec: str = "ulaw"
    direction: str = "both"
    jitter_buffer_ms: int = 20
