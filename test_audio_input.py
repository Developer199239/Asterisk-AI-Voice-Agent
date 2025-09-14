#!/usr/bin/env python3
"""
Asterisk AI Voice Agent - Audio Input Pipeline Test Script

This script tests different approaches for capturing caller audio:
1. Current snoop implementation (with invalid parameters)
2. Corrected snoop implementation (fixed parameters)
3. External Media channels (alternative approach)

Usage: python test_audio_input.py [test_type]
Test types: current, corrected, external, all
"""

import asyncio
import json
import base64
import time
import sys
from typing import Dict, Any, Optional
import aiohttp
import websockets
from websockets.exceptions import ConnectionClosed
import structlog

# Configure logging with colored console output for better debugging
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Add colored console renderer for live debugging
        structlog.dev.ConsoleRenderer(colors=True),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)

class AudioInputTester:
    def __init__(self, ari_host="127.0.0.1", ari_port=8088, username="AIAgent", password="AiAgent+2025?"):
        self.ari_host = ari_host
        self.ari_port = ari_port
        self.username = username
        self.password = password
        self.http_url = f"http://{ari_host}:{ari_port}"
        # Use the same format as the main engine
        import urllib.parse
        safe_username = urllib.parse.quote(username, safe='')
        safe_password = urllib.parse.quote(password, safe='')
        self.ws_url = f"ws://{ari_host}:{ari_port}/ari/events?api_key={safe_username}:{safe_password}&app=audio-test&subscribeAll=true"
        
        # STT Engine connection
        self.stt_websocket = None
        self.stt_ws_url = "ws://127.0.0.1:8765"
        
        self.websocket = None
        self.http_session = None
        self.active_channels = {}
        self.audio_frames_received = 0
        self.audio_data_received = 0
        self.test_results = {}
        self.snoop_channels = {}
        self.bridges = {}  # Track bridges for cleanup

    async def start(self, test_type="all"):
        """Start the test session."""
        logger.info("Starting Audio Input Pipeline Test", test_type=test_type)
        self.test_type = test_type
        
        # Create HTTP session
        auth = aiohttp.BasicAuth(self.username, self.password)
        self.http_session = aiohttp.ClientSession(auth=auth)
        
        # Connect to STT engine
        await self.connect_to_stt_engine()
        
        # Connect to ARI WebSocket
        await self.connect_websocket()
        
        # Start event listener
        asyncio.create_task(self.listen_for_events())
        
        # Start periodic monitoring
        asyncio.create_task(self.periodic_monitoring())

    async def connect_to_stt_engine(self):
        """Connect to the Local AI Server for STT processing."""
        try:
            logger.info("Connecting to STT engine...", url=self.stt_ws_url)
            self.stt_websocket = await websockets.connect(self.stt_ws_url)
            logger.info("✅ Connected to STT engine")
        except Exception as e:
            logger.error("Failed to connect to STT engine", error=str(e))
            self.stt_websocket = None

    async def send_audio_to_stt(self, audio_data: bytes):
        """Send audio data to STT engine for processing."""
        if self.stt_websocket:
            try:
                # Send raw audio bytes to STT engine (same format as main engine)
                await self.stt_websocket.send(audio_data)
                logger.info("🎤 Sent audio to STT engine", audio_size=len(audio_data))
            except Exception as e:
                logger.error("Failed to send audio to STT engine", error=str(e))

    async def connect_websocket(self):
        """Connect to ARI WebSocket."""
        try:
            self.websocket = await websockets.connect(self.ws_url)
            logger.info("Connected to ARI WebSocket", url=self.ws_url)
        except Exception as e:
            logger.error("Failed to connect to ARI WebSocket", error=str(e))
            raise

    async def listen_for_events(self):
        """Listen for ARI events."""
        try:
            async for message in self.websocket:
                try:
                    event_data = json.loads(message)
                    await self.handle_event(event_data)
                except json.JSONDecodeError as e:
                    logger.error("Failed to parse event", error=str(e), message=message)
        except ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.error("Error in event listener", error=str(e))

    async def handle_event(self, event_data: Dict[str, Any]):
        """Handle ARI events."""
        event_type = event_data.get("type")
        
        # Enhanced event logging
        if event_type in ["ChannelAudioFrame", "ChannelEnteredBridge", "ChannelLeftBridge", "ChannelStateChange"]:
            logger.info("🔍 RELEVANT EVENT", 
                       event_type=event_type, 
                       channel_id=event_data.get("channel", {}).get("id"),
                       bridge_id=event_data.get("bridge", {}).get("id") if "bridge" in event_data else None,
                       event_data=event_data)
        
        if event_type == "StasisStart":
            await self.handle_stasis_start(event_data)
        elif event_type == "ChannelAudioFrame":
            await self.handle_audio_frame(event_data)
        elif event_type == "StasisEnd":
            await self.handle_stasis_end(event_data)
        elif event_type == "ChannelEnteredBridge":
            await self.handle_channel_entered_bridge(event_data)
        elif event_type == "ChannelLeftBridge":
            await self.handle_channel_left_bridge(event_data)
        elif event_type == "ChannelStateChange":
            await self.handle_channel_state_change(event_data)
        else:
            logger.debug("Received event", event_type=event_type)

    async def handle_stasis_start(self, event_data: Dict[str, Any]):
        """Handle StasisStart event."""
        channel = event_data.get("channel", {})
        channel_id = channel.get("id")
        channel_name = channel.get("name")
        
        # --- ARCHITECT'S FIX ---
        # If the channel entering Stasis is already a snoop channel, ignore it.
        if channel_name and channel_name.startswith("Snoop/"):
            logger.info("Ignoring StasisStart for our own snoop channel.", channel_id=channel_id, channel_name=channel_name)
            return
        # -----------------------
        
        # Prevent multiple test executions on the same channel
        if channel_id in self.active_channels:
            logger.warning("Channel already being tested, skipping", channel_id=channel_id)
            return
        
        logger.info("📞 New call received", channel_id=channel_id, channel_name=channel_name)
        self.active_channels[channel_id] = {
            "channel": channel,
            "start_time": time.time(),
            "audio_frames": 0,
            "audio_data": 0,
            "test_type": self.test_type
        }
        
        # Answer the channel
        await self.answer_channel(channel_id)
        
        # Run the appropriate test
        if self.test_type == "all":
            # Test all approaches sequentially
            await self.test_current_snoop(channel_id)
            await asyncio.sleep(2)
            await self.test_corrected_snoop(channel_id)
            await asyncio.sleep(2)
            await self.test_external_media(channel_id)
        elif self.test_type == "current":
            await self.test_current_snoop(channel_id)
        elif self.test_type == "corrected":
            await self.test_corrected_snoop(channel_id)
        elif self.test_type == "external":
            await self.test_external_media(channel_id)

    async def test_current_snoop(self, channel_id: str):
        """Test current snoop implementation with invalid parameters."""
        logger.info("Testing CURRENT snoop implementation", channel_id=channel_id)
        
        try:
            # Create snoop with current (potentially invalid) parameters
            snoop_url = f"{self.http_url}/ari/channels/{channel_id}/snoop"
            params = {
                "spy": "in",
                "whisper": "none",
                "app": "audio-test",
                "snoopId": f"snoop_current_{channel_id}",  # Wrong parameter name
                "options": "audioframe"  # Invalid parameter
            }
            
            async with self.http_session.post(snoop_url, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    snoop_id = result.get("id")
                    self.snoop_channels[snoop_id] = "current"
                    logger.info("Current snoop created", snoop_id=snoop_id, status=response.status)
                else:
                    error_text = await response.text()
                    logger.error("Failed to create current snoop", 
                               status=response.status, 
                               error=error_text)
                               
        except Exception as e:
            logger.error("Error creating current snoop", error=str(e))

    async def test_corrected_snoop(self, channel_id: str):
        """Test corrected snoop implementation with ARCHITECT'S DEFINITIVE SOLUTION."""
        logger.info("Testing CORRECTED snoop implementation with ARCHITECT'S BRIDGE SOLUTION", channel_id=channel_id)
        
        try:
            # Step 1: Answer the Main Channel
            logger.info("  [Step 1] Answering main channel...", channel_id=channel_id)
            async with self.http_session.post(f"{self.http_url}/ari/channels/{channel_id}/answer") as response:
                if response.status != 204:
                    logger.error("  [FAIL] Could not answer channel", status=response.status)
                    return
            logger.info("  [OK] Main channel answered.", channel_id=channel_id)

            # Step 2: Create the Snoop Channel (with unique ID to prevent conflicts)
            import time
            unique_suffix = int(time.time() * 1000) % 10000  # 4-digit unique suffix
            snoop_id = f"snoop_{channel_id}_{unique_suffix}"
            logger.info("  [Step 2] Creating snoop channel...", main_channel_id=channel_id, snoop_id=snoop_id)
            async with self.http_session.post(
                f"{self.http_url}/ari/channels/{channel_id}/snoop",
                params={
                    "app": "audio-test",
                    "snoopId": snoop_id,
                    "spy": "in"
                }
            ) as response:
                if response.status != 200:
                    logger.error("  [FAIL] Could not create snoop channel", status=response.status, body=await response.text())
                    return
                snoop_channel = await response.json()
                snoop_channel_id = snoop_channel['id']
                self.snoop_channels[snoop_channel_id] = "corrected"
                logger.info("  [OK] Snoop channel created", snoop_channel_id=snoop_channel_id)

            # Step 3: Create a Mixing Bridge
            logger.info("  [Step 3] Creating a new mixing bridge...")
            async with self.http_session.post(f"{self.http_url}/ari/bridges", params={"type": "mixing"}) as response:
                if response.status != 200:
                    logger.error("  [FAIL] Could not create bridge", status=response.status)
                    return
                bridge = await response.json()
                bridge_id = bridge['id']
                self.bridges[bridge_id] = {"channels": []}
                logger.info("  [OK] Mixing bridge created", bridge_id=bridge_id)

            # Step 4: Add Snoop Channel to the Bridge
            logger.info("  [Step 4] Adding snoop channel to the bridge...", snoop_channel_id=snoop_channel_id, bridge_id=bridge_id)
            async with self.http_session.post(f"{self.http_url}/ari/bridges/{bridge_id}/addChannel", params={"channel": snoop_channel_id}) as response:
                if response.status != 204:
                    logger.error("  [FAIL] Could not add snoop channel to bridge", status=response.status)
                    return
            logger.info("  [OK] Snoop channel added to bridge. Waiting for ChannelEnteredBridge event...")

            # Step 5: Add the Main Channel to the same bridge to activate its media path
            logger.info("  [Step 5 - THE FIX] Adding MAIN channel to the bridge to activate media...", main_channel_id=channel_id, bridge_id=bridge_id)
            async with self.http_session.post(f"{self.http_url}/ari/bridges/{bridge_id}/addChannel", params={"channel": channel_id}) as response:
                if response.status != 204:
                    logger.error("  [FAIL] Could not add main channel to bridge", status=response.status)
                    return
            logger.info("  [OK] Main channel added to bridge. Asterisk is now forced to process its media. Waiting for ChannelEnteredBridge event...")
            
            # Final check log
            logger.info("  [SETUP COMPLETE] Both channels are being added to the bridge. We should now start receiving ChannelAudioFrame events.")

        except Exception as e:
            logger.error("Error during call setup", error=str(e))

    async def test_external_media(self, channel_id: str):
        """Test external media channel approach."""
        logger.info("Testing EXTERNAL MEDIA implementation", channel_id=channel_id)
        
        try:
            # Create external media channel
            external_url = f"{self.http_url}/ari/channels/externalMedia"
            params = {
                "app": "audio-test",
                "external_host": "127.0.0.1:8089",
                "format": "ulaw",
                "connection_type": "client"
            }
            
            async with self.http_session.post(external_url, params=params) as response:
                if response.status == 200:
                    result = await response.json()
                    external_id = result.get("id")
                    logger.info("External media created", external_id=external_id, status=response.status)
                else:
                    error_text = await response.text()
                    logger.error("Failed to create external media", 
                               status=response.status, 
                               error=error_text)
                               
        except Exception as e:
            logger.error("Error creating external media", error=str(e))

    async def handle_audio_frame(self, event_data: Dict[str, Any]):
        """Handle ChannelAudioFrame event."""
        channel = event_data.get("channel", {})
        channel_id = channel.get("id")
        
        self.audio_frames_received += 1
        
        # Check which type of snoop this is
        snoop_type = self.snoop_channels.get(channel_id, "unknown")
        
        # Process audio frame
        frame_data = event_data.get("frame", {})
        audio_payload = frame_data.get("payload")
        
        # Enhanced debugging - THE SUCCESS CONDITION!
        logger.info("🎉 [SUCCESS] RECEIVED ChannelAudioFrame! Two-way audio is now possible!", 
                  channel_id=channel_id,
                  snoop_type=snoop_type,
                  frame_data=frame_data,
                  has_payload=bool(audio_payload),
                  payload_length=len(audio_payload) if audio_payload else 0,
                  total_frames=self.audio_frames_received)
        
        if audio_payload:
            try:
                audio_data = base64.b64decode(audio_payload)
                self.audio_data_received += len(audio_data)
                
                logger.info("✅ AUDIO DATA PROCESSED", 
                          channel_id=channel_id,
                          snoop_type=snoop_type,
                          frame_size=len(audio_data),
                          total_frames=self.audio_frames_received,
                          total_data=self.audio_data_received)
                
                # Forward audio to STT engine for processing
                await self.send_audio_to_stt(audio_data)
                
                # Update stats for active channel
                for active_id, channel_data in self.active_channels.items():
                    if channel_id.startswith(f"snoop_{channel_data['test_type']}"):
                        channel_data["audio_frames"] += 1
                        channel_data["audio_data"] += len(audio_data)
                        break
                
                # Test STT processing (simplified)
                await self.test_stt_processing(audio_data, channel_id)
                
            except Exception as e:
                logger.error("Failed to process audio frame", error=str(e), channel_id=channel_id)
        else:
            logger.warning("Audio frame received but no payload", channel_id=channel_id, frame_data=frame_data)

    async def handle_stasis_end(self, event_data: Dict[str, Any]):
        """Handle StasisEnd event."""
        channel = event_data.get("channel", {})
        channel_id = channel.get("id")
        
        logger.info("StasisEnd received", channel_id=channel_id)
        
        if channel_id in self.active_channels:
            # Generate test results
            call_duration = time.time() - self.active_channels[channel_id]["start_time"]
            self.test_results[channel_id] = {
                "duration": call_duration,
                "audio_frames": self.active_channels[channel_id]["audio_frames"],
                "audio_data": self.active_channels[channel_id]["audio_data"],
                "test_type": self.active_channels[channel_id]["test_type"],
                "success": self.active_channels[channel_id]["audio_frames"] > 0
            }
            
            logger.info("📊 TEST RESULTS", 
                       channel_id=channel_id,
                       results=self.test_results[channel_id])
            
            # Print summary
            if self.test_results[channel_id]["success"]:
                logger.info("✅ TEST PASSED: Audio frames were received!")
            else:
                logger.error("❌ TEST FAILED: No audio frames received")
            
            # Clean up bridges associated with this channel
            await self.cleanup_bridges_for_channel(channel_id)
            
            del self.active_channels[channel_id]

    async def answer_channel(self, channel_id: str):
        """Answer the incoming channel."""
        try:
            async with self.http_session.post(
                f"{self.http_url}/ari/channels/{channel_id}/answer"
            ) as response:
                if response.status == 204:
                    logger.info("Channel answered", channel_id=channel_id)
                else:
                    logger.error("Failed to answer channel", 
                               channel_id=channel_id, 
                               status=response.status)
        except Exception as e:
            logger.error("Error answering channel", error=str(e))

    async def handle_channel_entered_bridge(self, event_data: Dict[str, Any]):
        """Handle ChannelEnteredBridge event."""
        channel = event_data.get("channel", {})
        bridge = event_data.get("bridge", {})
        channel_id = channel.get("id")
        bridge_id = bridge.get("id")
        
        # Determine channel type
        channel_type = "unknown"
        if channel_id in self.snoop_channels:
            channel_type = "snoop"
        elif channel_id in self.active_channels:
            channel_type = "main"
        
        logger.info(f"✅ [BRIDGE EVENT] Channel '{channel_type}' ({channel_id}) successfully entered bridge {bridge_id}")
        
        # This is the definitive confirmation log
        if channel_type == "main":
            logger.info("✅ [MEDIA PATH ACTIVE] The main channel is now in the bridge. Audio frames should start generating.")
        
        # Check if this is our snoop channel
        if channel_id in self.snoop_channels:
            logger.info("🎯 SNOOP CHANNEL ENTERED BRIDGE - AUDIO SHOULD BE ACTIVE NOW!", 
                       snoop_id=channel_id, 
                       bridge_id=bridge_id)

    async def handle_channel_left_bridge(self, event_data: Dict[str, Any]):
        """Handle ChannelLeftBridge event."""
        channel = event_data.get("channel", {})
        bridge = event_data.get("bridge", {})
        channel_id = channel.get("id")
        bridge_id = bridge.get("id")
        
        logger.info("Channel left bridge", 
                   channel_id=channel_id, 
                   bridge_id=bridge_id)

    async def handle_channel_state_change(self, event_data: Dict[str, Any]):
        """Handle ChannelStateChange event."""
        channel = event_data.get("channel", {})
        channel_id = channel.get("id")
        old_state = event_data.get("old_state")
        new_state = event_data.get("new_state")
        
        # Only log state changes for snoop channels
        if channel_id in self.snoop_channels:
            logger.info("🔄 SNOOP CHANNEL STATE CHANGE", 
                       snoop_id=channel_id, 
                       old_state=old_state, 
                       new_state=new_state)

    async def monitor_snoop_channel(self, snoop_id: str, bridge_id: str):
        """Monitor snoop channel status and audio activity."""
        try:
            # Get channel details
            channel_url = f"{self.http_url}/ari/channels/{snoop_id}"
            async with self.http_session.get(channel_url) as response:
                if response.status == 200:
                    channel_data = await response.json()
                    logger.info("📊 SNOOP CHANNEL STATUS", 
                               snoop_id=snoop_id,
                               state=channel_data.get("state"),
                               name=channel_data.get("name"),
                               caller=channel_data.get("caller"),
                               connected=channel_data.get("connected"),
                               creationtime=channel_data.get("creationtime"))
                else:
                    logger.warning("Failed to get snoop channel status", 
                                 snoop_id=snoop_id, 
                                 status=response.status)
            
            # Get bridge details
            bridge_url = f"{self.http_url}/ari/bridges/{bridge_id}"
            async with self.http_session.get(bridge_url) as response:
                if response.status == 200:
                    bridge_data = await response.json()
                    logger.info("📊 BRIDGE STATUS", 
                               bridge_id=bridge_id,
                               bridge_type=bridge_data.get("bridge_type"),
                               channels=bridge_data.get("channels", []),
                               channel_count=len(bridge_data.get("channels", [])))
                else:
                    logger.warning("Failed to get bridge status", 
                                 bridge_id=bridge_id, 
                                 status=response.status)
                                 
        except Exception as e:
            logger.error("Error monitoring snoop channel", error=str(e), snoop_id=snoop_id)

    async def play_silence_on_main_channel(self, main_channel_id: str):
        """Play silence on main channel to activate audio path (ARCHITECT'S FINAL SOLUTION)."""
        try:
            # Play continuous silence on the main channel to keep its audio path active
            play_url = f"{self.http_url}/ari/channels/{main_channel_id}/play"
            play_params = {
                "media": "sound:silence/1"  # Plays 1 second of silence
            }
            
            async with self.http_session.post(play_url, params=play_params) as response:
                if response.status == 201 or response.status == 204:
                    logger.info("🔇 SILENCE PLAYING ON MAIN CHANNEL - AUDIO PATH ACTIVATED!", 
                              main_channel_id=main_channel_id)
                    
                    # Start continuous silence playback to keep audio path active
                    asyncio.create_task(self.continuous_silence_playback(main_channel_id))
                else:
                    error_text = await response.text()
                    logger.error("Failed to play silence on main channel", 
                               main_channel_id=main_channel_id,
                               status=response.status, 
                               error=error_text)
                               
        except Exception as e:
            logger.error("Error playing silence on main channel", error=str(e), main_channel_id=main_channel_id)

    async def continuous_silence_playback(self, main_channel_id: str):
        """Continuously play silence to keep audio path active."""
        try:
            while main_channel_id in self.active_channels:
                # Play 1 second of silence
                play_url = f"{self.http_url}/ari/channels/{main_channel_id}/play"
                play_params = {"media": "sound:silence/1"}
                
                async with self.http_session.post(play_url, params=play_params) as response:
                    if response.status == 201 or response.status == 204:
                        logger.debug("🔇 Silence playback continued", main_channel_id=main_channel_id)
                    else:
                        logger.warning("Silence playback failed", main_channel_id=main_channel_id, status=response.status)
                        break
                
                # Wait for silence to finish playing (1 second)
                await asyncio.sleep(1.1)
                
        except Exception as e:
            logger.error("Error in continuous silence playback", error=str(e), main_channel_id=main_channel_id)

    async def periodic_monitoring(self):
        """Periodically monitor audio frame activity and channel status."""
        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                
                if self.active_channels:
                    logger.info("📈 PERIODIC STATUS CHECK", 
                               active_channels=len(self.active_channels),
                               total_audio_frames=self.audio_frames_received,
                               total_audio_data=self.audio_data_received,
                               snoop_channels=len(self.snoop_channels),
                               bridges=len(self.bridges))
                    
                    # Check if we should be receiving audio frames
                    for channel_id, channel_data in self.active_channels.items():
                        if channel_data["audio_frames"] == 0:
                            logger.warning("⚠️ NO AUDIO FRAMES RECEIVED", 
                                         channel_id=channel_id,
                                         test_type=channel_data["test_type"],
                                         duration=time.time() - channel_data["start_time"])
                            
            except Exception as e:
                logger.error("Error in periodic monitoring", error=str(e))

    async def test_stt_processing(self, audio_data: bytes, channel_id: str):
        """Test STT processing with the audio data."""
        try:
            # This is a simplified STT test - in real implementation,
            # we would send this to the local AI server
            logger.info("STT processing test", 
                       channel_id=channel_id,
                       audio_size=len(audio_data))
            
            # TODO: Send to local AI server for actual STT processing
            # For now, just simulate processing
            await asyncio.sleep(0.1)
            
        except Exception as e:
            logger.error("STT processing failed", error=str(e))

    async def cleanup_bridges_for_channel(self, channel_id: str):
        """Clean up bridges associated with a specific channel."""
        try:
            # Find bridges associated with this channel's snoop channels
            bridges_to_cleanup = []
            for bridge_id, snoop_id in self.bridges.items():
                if snoop_id.startswith(f"snoop_corrected_{channel_id}"):
                    bridges_to_cleanup.append(bridge_id)
            
            # Clean up the bridges
            for bridge_id in bridges_to_cleanup:
                try:
                    async with self.http_session.delete(f"{self.http_url}/ari/bridges/{bridge_id}") as response:
                        if response.status == 204:
                            logger.info("✅ Bridge cleaned up", bridge_id=bridge_id)
                        else:
                            logger.warning("Failed to cleanup bridge", bridge_id=bridge_id, status=response.status)
                    del self.bridges[bridge_id]
                except Exception as e:
                    logger.error("Error cleaning up bridge", bridge_id=bridge_id, error=str(e))
        except Exception as e:
            logger.error("Error in bridge cleanup", error=str(e))

    async def cleanup(self):
        """Clean up resources."""
        # Clean up all remaining bridges
        for bridge_id in list(self.bridges.keys()):
            try:
                async with self.http_session.delete(f"{self.http_url}/ari/bridges/{bridge_id}") as response:
                    if response.status == 204:
                        logger.info("✅ Bridge cleaned up", bridge_id=bridge_id)
            except Exception as e:
                logger.error("Error cleaning up bridge", bridge_id=bridge_id, error=str(e))
        
        if self.websocket:
            await self.websocket.close()
        if self.http_session:
            await self.http_session.close()

async def main():
    """Main test function."""
    test_type = sys.argv[1] if len(sys.argv) > 1 else "corrected"
    
    logger.info("Starting audio input pipeline test", test_type=test_type)
    
    tester = AudioInputTester()
    
    try:
        await tester.start(test_type)
        
        # Keep running until interrupted
        logger.info("Test script running. Make a test call to trigger testing.")
        logger.info("Press Ctrl+C to stop.")
        
        while True:
            await asyncio.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error("Test failed", error=str(e))
    finally:
        await tester.cleanup()
        logger.info("Test completed")

if __name__ == "__main__":
    asyncio.run(main())
