import asyncio
import os
import signal
import uuid
from typing import Dict, Any, Optional

from .ari_client import ARIClient
from aiohttp import web
from .config import AppConfig, load_config
from .logging_config import get_logger, configure_logging
from .providers.base import AIProviderInterface
from .audiosocket_server import AudioSocketServer
from .providers.deepgram import DeepgramProvider
from .providers.local import LocalProvider

logger = get_logger(__name__)

class Engine:
    """Simplified AI Voice Agent Engine with direct AudioSocket handling."""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.ari_client = ARIClient(
            username=config.asterisk.username,
            password=config.asterisk.password,
            base_url=f"http://{config.asterisk.host}:{config.asterisk.port}",
            app_name=config.asterisk.app_name
        )
        self.audiosocket_server = AudioSocketServer(port=8090)  # Default AudioSocket port
        self.providers: Dict[str, AIProviderInterface] = {}
        self.active_calls: Dict[str, Dict[str, Any]] = {}  # channel_id -> call_data
        self.uuid_to_channel: Dict[str, str] = {}  # uuid -> channel_id
        self.running = False
        
        # Setup providers
        self._setup_providers()
        
        # Setup AudioSocket callbacks
        self.audiosocket_server.set_audio_callback(self._on_audiosocket_audio)
        self.audiosocket_server.set_connection_callback(self._on_audiosocket_connection)
        self.audiosocket_server.set_disconnection_callback(self._on_audiosocket_disconnection)

    def _setup_providers(self):
        """Initialize AI providers."""
        try:
            # Local provider
            if self.config.providers.local.enabled:
                self.providers['local'] = LocalProvider(self.config.providers.local)
                logger.info("Local provider initialized")
            
            # Deepgram provider
            if self.config.providers.deepgram.enabled:
                self.providers['deepgram'] = DeepgramProvider(self.config.providers.deepgram)
                logger.info("Deepgram provider initialized")
                
            logger.info("Providers setup complete", 
                       providers=list(self.providers.keys()))
        except Exception as e:
            logger.error("Failed to setup providers", error=str(e), exc_info=True)

    async def start(self):
        """Start the engine."""
        logger.info("Starting simplified AI Voice Agent Engine")
        
        try:
            # Connect to ARI
            await self.ari_client.connect()
            logger.info("ARI connected successfully")
            
            # Start AudioSocket server
            await self.audiosocket_server.start_server()
            logger.info(f"AudioSocket server listening on port {self.config.audiosocket.port}")
            
            # Setup ARI event handlers
            self.ari_client.set_event_handler("StasisStart", self._handle_stasis_start)
            self.ari_client.set_event_handler("StasisEnd", self._handle_stasis_end)
            self.ari_client.set_event_handler("ChannelDestroyed", self._handle_channel_destroyed)
            
            # Start ARI event processing
            await self.ari_client.start_event_processing()
            logger.info("ARI event processing started")
            
            self.running = True
            logger.info("Engine started successfully")
            
        except Exception as e:
            logger.error("Failed to start engine", error=str(e), exc_info=True)
            raise

    async def stop(self):
        """Stop the engine."""
        logger.info("Stopping engine")
        self.running = False
        
        # Stop AudioSocket server
        await self.audiosocket_server.stop_server()
        
        # Disconnect ARI
        await self.ari_client.disconnect()
        
        logger.info("Engine stopped")

    async def _handle_stasis_start(self, event: dict):
        """Handle new call entering Stasis - simplified approach."""
        channel = event.get('channel', {})
        channel_id = channel.get('id')
        caller_info = channel.get('caller', {})
        
        if not channel_id:
            logger.warning("No channel ID in StasisStart event")
            return
            
        logger.info("New call received", 
                   channel_id=channel_id,
                   caller={"name": caller_info.get("name"), "number": caller_info.get("number")})
        
        try:
            # Answer the channel
            await self.ari_client.answer_channel(channel_id)
            logger.info("Channel answered", channel_id=channel_id)
            
            # Generate UUID for this call
            call_uuid = str(uuid.uuid4())
            self.uuid_to_channel[call_uuid] = channel_id
            
            # Store call data
            self.active_calls[channel_id] = {
                "uuid": call_uuid,
                "channel": channel,
                "status": "waiting_for_audiosocket",
                "provider": None
            }
            
            logger.info("Call ready for AudioSocket", 
                       channel_id=channel_id, 
                       uuid=call_uuid)
            
            # Play initial greeting
            await self._play_initial_greeting(channel_id)
            
        except Exception as e:
            logger.error("Failed to handle StasisStart", 
                        channel_id=channel_id, 
                        error=str(e), exc_info=True)
            await self._cleanup_call(channel_id)

    async def _handle_stasis_end(self, event: dict):
        """Handle call ending."""
        channel_id = event.get('channel', {}).get('id')
        if channel_id:
            logger.info("Call ended", channel_id=channel_id)
            await self._cleanup_call(channel_id)

    async def _handle_channel_destroyed(self, event: dict):
        """Handle channel destruction."""
        channel_id = event.get('channel', {}).get('id')
        if channel_id:
            logger.info("Channel destroyed", channel_id=channel_id)
            await self._cleanup_call(channel_id)

    async def _on_audiosocket_connection(self, conn_id: str, uuid: str):
        """Handle new AudioSocket connection with UUID."""
        logger.info("AudioSocket connection established", 
                   conn_id=conn_id, 
                   uuid=uuid)
        
        # Find channel for this UUID
        channel_id = self.uuid_to_channel.get(uuid)
        if not channel_id:
            logger.warning("No channel found for UUID", uuid=uuid, conn_id=conn_id)
            return
        
        # Update call data
        if channel_id in self.active_calls:
            self.active_calls[channel_id]["conn_id"] = conn_id
            self.active_calls[channel_id]["status"] = "connected"
            
            # Start provider session
            await self._start_provider_session(channel_id)
            
            logger.info("AudioSocket bound to channel", 
                       channel_id=channel_id, 
                       conn_id=conn_id, 
                       uuid=uuid)

    async def _on_audiosocket_disconnection(self, conn_id: str):
        """Handle AudioSocket disconnection."""
        logger.info("AudioSocket connection closed", conn_id=conn_id)
        
        # Find and cleanup call
        for channel_id, call_data in self.active_calls.items():
            if call_data.get("conn_id") == conn_id:
                await self._cleanup_call(channel_id)
                break

    async def _on_audiosocket_audio(self, conn_id: str, audio_data: bytes):
        """Handle incoming audio from AudioSocket."""
        # Find channel for this connection
        channel_id = None
        for cid, call_data in self.active_calls.items():
            if call_data.get("conn_id") == conn_id:
                channel_id = cid
                break
        
        if not channel_id:
            logger.debug("Audio received for unknown connection", conn_id=conn_id)
            return
        
        call_data = self.active_calls.get(channel_id)
        if not call_data or call_data.get("status") != "connected":
            logger.debug("Audio received for inactive call", 
                        channel_id=channel_id, 
                        conn_id=conn_id)
            return
        
        # Send audio to provider
        provider = call_data.get("provider")
        if provider:
            try:
                await provider.send_audio(audio_data)
            except Exception as e:
                logger.error("Failed to send audio to provider", 
                           channel_id=channel_id, 
                           error=str(e))

    async def _start_provider_session(self, channel_id: str):
        """Start AI provider session for the call."""
        try:
            provider = self.providers.get(self.config.default_provider)
            if not provider:
                logger.error("Default provider not found", provider=self.config.default_provider)
                return
            
            # Start provider session
            await provider.start_session(channel_id)
            
            # Store provider in call data
            self.active_calls[channel_id]["provider"] = provider
            
            logger.info("Provider session started", 
                       channel_id=channel_id, 
                       provider=self.config.default_provider)
            
        except Exception as e:
            logger.error("Failed to start provider session", 
                        channel_id=channel_id, 
                        error=str(e), exc_info=True)

    async def _play_initial_greeting(self, channel_id: str):
        """Play initial greeting to the caller."""
        try:
            # This is a placeholder - you can implement actual greeting playback here
            logger.info("Playing initial greeting", channel_id=channel_id)
            
            # For now, just log that greeting would be played
            # In a real implementation, you'd use ARI to play a sound file
            
        except Exception as e:
            logger.error("Failed to play greeting", 
                        channel_id=channel_id, 
                        error=str(e))

    async def _cleanup_call(self, channel_id: str):
        """Clean up call resources."""
        try:
            call_data = self.active_calls.pop(channel_id, None)
            if call_data:
                # Clean up UUID mapping
                uuid = call_data.get("uuid")
                if uuid and uuid in self.uuid_to_channel:
                    del self.uuid_to_channel[uuid]
                
                # Stop provider session
                provider = call_data.get("provider")
                if provider:
                    try:
                        await provider.stop_session(channel_id)
                    except Exception as e:
                        logger.error("Failed to stop provider session", 
                                   channel_id=channel_id, 
                                   error=str(e))
                
                logger.info("Call cleaned up", channel_id=channel_id)
            
        except Exception as e:
            logger.error("Failed to cleanup call", 
                        channel_id=channel_id, 
                        error=str(e), exc_info=True)

async def main():
    """Main entry point."""
    configure_logging()
    logger.info("Starting AI Voice Agent Engine")
    
    try:
        # Load configuration
        config = load_config()
        
        # Create and start engine
        engine = Engine(config)
        
        # Setup signal handlers
        def signal_handler(signum, frame):
            logger.info("Received signal, shutting down", signal=signum)
            asyncio.create_task(engine.stop())
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start engine
        await engine.start()
        
        # Keep running
        while engine.running:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt")
    except Exception as e:
        logger.error("Engine failed", error=str(e), exc_info=True)
    finally:
        if 'engine' in locals():
            await engine.stop()
        logger.info("Engine shutdown complete")

if __name__ == "__main__":
    asyncio.run(main())
