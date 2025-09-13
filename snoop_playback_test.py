import asyncio
import logging
import os
import uuid
import wave

import ari

logging.basicConfig(level=logging.INFO)

# --- Configuration ---
ASTERISK_URL = "http://127.0.0.1:8088/"
ASTERISK_USERNAME = "AIAgent"
ASTERISK_PASSWORD = "AiAgent+2025?"
APP_NAME = "snoop-test"
CHANNEL_TO_CALL = "PJSIP/101"
SHARED_MEDIA_DIR = "/mnt/asterisk_media/ai-generated"

# --- State ---
client = None
test_call_channel = None

async def on_stasis_start(channel_obj, event):
    """Main handler for our test call."""
    global test_call_channel
    channel = channel_obj['channel']
    channel_id = channel['id']
    logging.info(f"Call started: {channel_id}")

    await client.channels.answer(channelId=channel_id)
    test_call_channel = channel

    # 1. Start Snoop
    logging.info("Starting snoop channel...")
    snoop_channel = await client.channels.snoopChannel(
        channelId=channel_id,
        app=APP_NAME,
        spy="in"
    )
    snoop_id = snoop_channel['id']
    logging.info(f"Snoop channel created: {snoop_id}")

    # 2. Listen for one audio frame
    first_frame_received = asyncio.Event()

    async def on_audio_frame(snoop_obj, ev):
        if not first_frame_received.is_set():
            logging.info(f"SUCCESS: Received first audio frame from snoop channel {snoop_obj['id']}")
            first_frame_received.set()
    
    client.on_channel_event("ChannelAudioFrame", on_audio_frame)

    await first_frame_received.wait()

    # 3. Create and play a dummy audio file
    await create_and_play_dummy_file(channel_id)


async def create_and_play_dummy_file(channel_id):
    """Creates a silent WAV file and tells Asterisk to play it."""
    unique_filename = f"test-playback-{uuid.uuid4()}.wav"
    file_path = os.path.join(SHARED_MEDIA_DIR, unique_filename)
    asterisk_uri = f"sound:ai-generated/{unique_filename.replace('.wav', '')}"

    logging.info(f"Creating dummy audio file at: {file_path}")
    # Create a 1-second silent WAV file
    with wave.open(file_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(8000)
        wf.writeframes(b'\x00' * 16000)
    
    os.chmod(file_path, 0o666) # Make sure asterisk can read it

    logging.info(f"Telling Asterisk to play: {asterisk_uri}")
    playback = await client.channels.play(channelId=channel_id, media=asterisk_uri)
    
    playback_id = playback['id']
    logging.info(f"Playback started with ID: {playback_id}")

    # 4. Wait for playback to finish and clean up
    playback_finished = asyncio.Event()

    async def on_playback_finished(playback_obj, ev):
        if playback_obj['id'] == playback_id:
            logging.info(f"SUCCESS: Received PlaybackFinished event for {playback_id}")
            if os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"SUCCESS: Cleaned up audio file: {file_path}")
            else:
                logging.error(f"FAILURE: Audio file was already gone: {file_path}")
            playback_finished.set()

    client.on_playback_event("PlaybackFinished", on_playback_finished)
    
    await playback_finished.wait()
    await client.channels.hangup(channelId=channel_id)


async def main():
    global client
    os.makedirs(SHARED_MEDIA_DIR, exist_ok=True)
    
    async with ari.connect(ASTERISK_URL, ASTERISK_USERNAME, ASTERISK_PASSWORD) as ari_client:
        client = ari_client
        client.on_channel_event("StasisStart", on_stasis_start)

        logging.info(f"ARI client connected. Starting app '{APP_NAME}'")
        
        # Start the app and wait for calls
        asyncio.create_task(client.run(apps=APP_NAME))

        # Originate a call to our app to kick off the test
        logging.info(f"Originating test call to {CHANNEL_TO_CALL}")
        try:
            await client.channels.originate(
                endpoint=CHANNEL_TO_CALL,
                app=APP_NAME,
                timeout=30
            )
        except Exception as e:
            logging.error(f"Failed to originate call: {e}")
            return

        # Wait for the test call to finish
        await asyncio.sleep(30) # Timeout
        logging.info("Test finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
