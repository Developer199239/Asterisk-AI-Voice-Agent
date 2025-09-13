import asyncio
import websockets

async def test_connection():
    uri = "ws://127.0.0.1:8765"
    print(f"Attempting to connect to {uri}...")
    try:
        async with websockets.connect(uri, open_timeout=5) as websocket:
            print("Connection successful!")
            print(f"Received server handshake: {websocket.response_headers}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
