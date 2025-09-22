"""
PlaybackManager - Centralized audio playback and TTS gating management.

This extracts all playback/TTS gating logic from the Engine and provides
a clean interface for playing audio with deterministic playback IDs and
token-aware gating.
"""

import asyncio
import uuid
import time
import os
from typing import Optional, Dict, Any
import structlog

from src.core.session_store import SessionStore
from src.core.models import PlaybackRef, CallSession

logger = structlog.get_logger(__name__)


class PlaybackManager:
    """
    Manages audio playback with deterministic IDs and token-aware gating.
    
    Responsibilities:
    - Generate deterministic playback IDs
    - Manage file lifecycle in /mnt/asterisk_media
    - Handle token/refcount gating
    - Track active playbacks
    - Provide fallback mechanisms
    """
    
    def __init__(self, session_store: SessionStore, ari_client, media_dir: str = "/mnt/asterisk_media/ai-generated"):
        self.session_store = session_store
        self.ari_client = ari_client
        self.media_dir = media_dir
        
        # Ensure media directory exists
        os.makedirs(media_dir, exist_ok=True)
        
        logger.info("PlaybackManager initialized",
                   media_dir=media_dir)
    
    async def play_audio(self, call_id: str, audio_bytes: bytes, 
                        playback_type: str = "response", engine=None) -> Optional[str]:
        """
        Play audio with deterministic playback ID and gating.
        
        Args:
            call_id: Canonical call ID
            audio_bytes: Audio data to play
            playback_type: Type of playback (greeting, response, etc.)
            engine: Engine instance for accessing active_calls (temporary migration support)
        
        Returns:
            playback_id if successful, None if failed
        """
        try:
            # Get session to determine target channel
            session = await self.session_store.get_by_call_id(call_id)
            
            # TEMPORARY MIGRATION: If no session in SessionStore, create one from Engine state
            if not session and engine:
                call_data = engine.active_calls.get(call_id)
                if call_data:
                    # Create CallSession from existing call_data
                    provider = call_data.get("provider")
                    provider_name = "unknown"
                    if provider:
                        # Try different ways to get provider name
                        if hasattr(provider, 'name'):
                            provider_name = provider.name
                        elif hasattr(provider, '__class__'):
                            provider_name = provider.__class__.__name__.lower()
                        elif isinstance(provider, dict):
                            provider_name = provider.get("name", "unknown")
                    
                    session = CallSession(
                        call_id=call_id,
                        caller_channel_id=call_id,
                        bridge_id=call_data.get("bridge_id"),
                        provider_name=provider_name,
                        conversation_state=call_data.get("conversation_state", "unknown"),
                        external_media_id=call_data.get("external_media_id"),
                        external_media_call_id=call_data.get("external_media_call_id")
                    )
                    await self.session_store.upsert_call(session)
                    logger.info("🔧 MIGRATION - Created CallSession from Engine state", call_id=call_id)
                else:
                    logger.error("Cannot play audio - call session not found and no engine fallback",
                               call_id=call_id)
                    return None
            elif not session:
                logger.error("Cannot play audio - call session not found",
                           call_id=call_id)
                return None
            
            # Generate deterministic playback ID
            playback_id = self._generate_playback_id(call_id, playback_type)
            
            # Create audio file
            audio_file = await self._create_audio_file(audio_bytes, playback_id)
            if not audio_file:
                return None
            
            # Set TTS gating before playing
            await self.session_store.set_gating_token(call_id, playback_id)
            
            # Play audio via ARI
            success = await self._play_via_ari(session, audio_file, playback_id)
            if not success:
                # Cleanup gating token if playback failed
                await self.session_store.clear_gating_token(call_id, playback_id)
                return None
            
            # Create playback reference
            playback_ref = PlaybackRef(
                playback_id=playback_id,
                call_id=call_id,
                channel_id=session.caller_channel_id,
                bridge_id=session.bridge_id,
                media_uri=f"sound:ai-generated/{os.path.basename(audio_file).replace('.ulaw', '')}",
                audio_file=audio_file
            )
            
            # Track playback reference
            await self.session_store.add_playback(playback_ref)
            
            logger.info("🔊 AUDIO PLAYBACK - Started",
                       call_id=call_id,
                       playback_id=playback_id,
                       audio_size=len(audio_bytes),
                       playback_type=playback_type)
            
            return playback_id
            
        except Exception as e:
            logger.error("Error playing audio",
                        call_id=call_id,
                        playback_type=playback_type,
                        error=str(e),
                        exc_info=True)
            return None
    
    async def on_playback_finished(self, playback_id: str) -> bool:
        """
        Handle PlaybackFinished event from Asterisk.
        
        Args:
            playback_id: The playback ID that finished
        
        Returns:
            True if handled successfully, False otherwise
        """
        try:
            # Get playback reference
            playback_ref = await self.session_store.pop_playback(playback_id)
            if not playback_ref:
                logger.warning("🔊 PlaybackFinished for unknown playback ID",
                             playback_id=playback_id)
                return False
            
            # Clear TTS gating token
            success = await self.session_store.clear_gating_token(
                playback_ref.call_id, playback_id)
            
            # Clean up audio file
            await self._cleanup_audio_file(playback_ref.audio_file)
            
            logger.info("🔊 PlaybackFinished - Audio playback completed",
                       playback_id=playback_id,
                       call_id=playback_ref.call_id,
                       gating_cleared=success)
            
            return True
            
        except Exception as e:
            logger.error("Error handling PlaybackFinished",
                        playback_id=playback_id,
                        error=str(e),
                        exc_info=True)
            return False
    
    def _generate_playback_id(self, call_id: str, playback_type: str) -> str:
        """Generate deterministic playback ID."""
        timestamp = int(time.time() * 1000)
        return f"{playback_type}:{call_id}:{timestamp}"
    
    async def _create_audio_file(self, audio_bytes: bytes, playback_id: str) -> Optional[str]:
        """Create audio file from bytes."""
        try:
            # Generate unique filename
            filename = f"audio-{playback_id.replace(':', '-')}.ulaw"
            file_path = os.path.join(self.media_dir, filename)
            
            # Write audio data
            with open(file_path, 'wb') as f:
                f.write(audio_bytes)
            
            logger.debug("Audio file created",
                        file_path=file_path,
                        size=len(audio_bytes))
            
            return file_path
            
        except Exception as e:
            logger.error("Error creating audio file",
                        playback_id=playback_id,
                        error=str(e),
                        exc_info=True)
            return None
    
    async def _play_via_ari(self, session: CallSession, audio_file: str, 
                           playback_id: str) -> bool:
        """Play audio file via ARI bridge."""
        try:
            if not session.bridge_id:
                logger.error("Cannot play audio - no bridge ID",
                           call_id=session.call_id,
                           playback_id=playback_id)
                return False
            
            # Create sound URI (remove .ulaw extension - Asterisk adds it)
            sound_uri = f"sound:ai-generated/{os.path.basename(audio_file).replace('.ulaw', '')}"
            
            # Play via bridge with deterministic playback ID
            success = await self.ari_client.play_media_on_bridge_with_id(
                session.bridge_id, 
                sound_uri, 
                playback_id
            )
            
            if success:
                logger.info("Bridge playback started",
                           bridge_id=session.bridge_id,
                           media_uri=sound_uri,
                           playback_id=playback_id)
            else:
                logger.error("Failed to start bridge playback",
                           bridge_id=session.bridge_id,
                           media_uri=sound_uri,
                           playback_id=playback_id)
            
            return success
            
        except Exception as e:
            logger.error("Error playing audio via ARI",
                        call_id=session.call_id,
                        playback_id=playback_id,
                        error=str(e),
                        exc_info=True)
            return False
    
    async def _cleanup_audio_file(self, audio_file: str) -> None:
        """Clean up audio file after playback."""
        try:
            if os.path.exists(audio_file):
                os.remove(audio_file)
                logger.debug("Audio file cleaned up",
                           file_path=audio_file)
        except Exception as e:
            logger.warning("Error cleaning up audio file",
                         file_path=audio_file,
                         error=str(e))
    
    async def get_active_playbacks(self) -> Dict[str, PlaybackRef]:
        """Get all active playbacks."""
        # This would need to be implemented in SessionStore
        # For now, return empty dict
        return {}
    
    async def cleanup_expired_playbacks(self, max_age_seconds: float = 300) -> int:
        """Clean up playbacks older than max_age_seconds."""
        # This would need to be implemented in SessionStore
        # For now, return 0
        return 0
