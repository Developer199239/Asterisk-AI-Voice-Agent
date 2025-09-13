import asyncio
import logging
import os
import uuid
import wave
import aiohttp
import json

logging.basicConfig(level=logging.INFO)

# --- Configuration ---
ASTERISK_URL = "https://127.0.0.1:8089/ari"
ASTERISK_USERNAME = "AIAgent"
ASTERISK_PASSWORD = "AiAgent+2025?"
APP_NAME = "asterisk-ai-voice-agent"
CHANNEL_TO_CALL = "PJSIP/8002"
SHARED_MEDIA_DIR = "/mnt/asterisk_media/ai-generated"

async def send_ari_command(session, method, resource, data=None):
    url = f"{ASTERISK_URL}/{resource}"
    try:
        async with session.request(method, url, json=data) as response:
            if response.status >= 400:
                logging.error(f"ARI command failed: {response.status} {await response.text()}")
                return None
            if response.status == 204:
                return {}
            return await response.json()
    except Exception as e:
        logging.error(f"ARI request exception: {e}")
        return None

async def main():
    os.makedirs(SHARED_MEDIA_DIR, exist_ok=True)
    
    # Create SSL context that doesn't verify certificates (for self-signed certs)
    import ssl
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    async with aiohttp.ClientSession(
        auth=aiohttp.BasicAuth(ASTERISK_USERNAME, ASTERISK_PASSWORD),
        connector=aiohttp.TCPConnector(ssl=ssl_context)
    ) as session:
        logging.info(f"Originating test call to {CHANNEL_TO_CALL}")
        originate_data = {
            "endpoint": CHANNEL_TO_CALL,
            "app": APP_NAME,
            "timeout": 30
        }
        channel = await send_ari_command(session, "POST", "channels", data=originate_data)
        if not channel:
            logging.error("Failed to originate channel.")
            return

        channel_id = channel['id']
        logging.info(f"Call started: {channel_id}")
        
        await asyncio.sleep(2) # Wait for the channel to be answered

        # Create and play a dummy audio file
        unique_filename = f"test-playback-{uuid.uuid4()}.wav"
        file_path = os.path.join(SHARED_MEDIA_DIR, unique_filename)
        asterisk_uri = f"sound:ai-generated/{unique_filename.replace('.wav', '')}"

        logging.info(f"Creating dummy audio file at: {file_path}")
        with wave.open(file_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(8000)
            wf.writeframes(b'\x00' * 16000)
        os.chmod(file_path, 0o666)
        logging.info(f"SUCCESS: Dummy file created at {file_path}")

        logging.info(f"Telling Asterisk to play: {asterisk_uri}")
        play_data = {"media": asterisk_uri}
        playback = await send_ari_command(session, "POST", f"channels/{channel_id}/play", data=play_data)
        
        if playback:
            logging.info(f"SUCCESS: Playback started with ID: {playback['id']}")
            await asyncio.sleep(5) # Wait for playback to finish
            if os.path.exists(file_path):
                os.remove(file_path)
                logging.info(f"SUCCESS: Cleaned up audio file: {file_path}")
        else:
            logging.error("FAILURE: Playback command failed.")

        await send_ari_command(session, "DELETE", f"channels/{channel_id}")
        logging.info("Test finished.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
