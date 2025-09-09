import asyncio
import os
import logging
import websockets
import sys

# --- Detailed, Verbose Logging Setup ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)

async def test_ari_connection():
    """
    A minimal, self-contained script to test the ARI WebSocket connection.
    """
    logging.info("--- Starting Minimal ARI Connection Test ---")

    # 1. Read connection details from environment variables
    host = os.getenv("ASTERISK_HOST")
    port = os.getenv("ARI_PORT", "8088")
    username = os.getenv("ARI_USERNAME")
    password = os.getenv("ARI_PASSWORD")
    app_name = "asterisk-ai-voice-agent"

    logging.debug(f"Read environment variables: HOST={host}, PORT={port}, USER={username}")

    if not all([host, username, password]):
        logging.error("Missing one or more required environment variables: ASTERISK_HOST, ARI_USERNAME, ARI_PASSWORD")
        return

    # 2. Construct the WebSocket URL
    ws_url = f"ws://{host}:{port}/ari/events?api_key={username}:{password}&app={app_name}"
    logging.info(f"Constructed WebSocket URL: {ws_url}")

    # 3. Attempt to connect with detailed error logging
    try:
        logging.info("Attempting to connect to WebSocket...")
        async with websockets.connect(ws_url) as websocket:
            logging.info("--- CONNECTION SUCCESSFUL! ---")
            logging.info(f"WebSocket connection established: {websocket.local_address} -> {websocket.remote_address}")
            
            # Keep the connection alive for a moment to ensure it's stable
            await asyncio.sleep(5)
            logging.info("Connection remained stable for 5 seconds.")

    except websockets.exceptions.InvalidURI as e:
        logging.error(f"--- CONNECTION FAILED: Invalid URI ---", exc_info=True)
    except websockets.exceptions.ConnectionClosedError as e:
        logging.error(f"--- CONNECTION FAILED: Connection was closed unexpectedly ---", exc_info=True)
    except ConnectionRefusedError:
        logging.error(f"--- CONNECTION FAILED: Connection was refused by the server. Check host, port, and firewall. ---", exc_info=True)
    except Exception as e:
        logging.error(f"--- CONNECTION FAILED: An unexpected error occurred ---", exc_info=True)

    finally:
        logging.info("--- Test script finished. Container will stay alive for 60 seconds for log inspection. ---")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(test_ari_connection())
