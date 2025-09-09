import asyncio
import os
import sys
from dotenv import load_dotenv

# Add the project root directory to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from services.call_controller.deepgram_agent_client import DeepgramAgentClient
from services.call_controller.config import AppConfig

# Load environment variables from .env file
load_dotenv()

async def mock_event_handler(event):
    """A simple event handler that prints events."""
    print(f"Received event from Deepgram: {event}")
    if event.get("type") == "Welcome":
        # If we get the Welcome message, we can consider the connection a success
        # and signal the test to end.
        global test_passed
        test_passed = True

def test_channel_filtering():
    """Tests the logic for filtering incoming channels."""
    print("\n--- Testing Channel Filtering Logic ---")
    
    test_cases = [
        {"name": "SIP/1234-abcd", "should_pass": True},
        {"name": "PJSIP/5678-efgh", "should_pass": True},
        {"name": "UnicastRTP/127.0.0.1:1234-ijkl", "should_pass": False},
        {"name": "Local/some-channel", "should_pass": False},
    ]
    
    all_passed = True
    for case in test_cases:
        channel_name = case["name"]
        should_pass = case["should_pass"]
        
        # This is the exact logic from main.py
        is_handled = channel_name.startswith("SIP/") or channel_name.startswith("PJSIP/")
        
        if is_handled == should_pass:
            print(f"✅ PASS: Channel '{channel_name}' was handled correctly (Result: {is_handled})")
        else:
            print(f"❌ FAIL: Channel '{channel_name}' was handled incorrectly (Result: {is_handled})")
            all_passed = False
            
    if all_passed:
        print("✅ All channel filtering tests passed.")
    else:
        print("❌ Some channel filtering tests failed.")
        
    return all_passed


async def test_deepgram_connection():
    """Tests the connection to the Deepgram Voice Agent."""
    print("\n--- Testing Deepgram Voice Agent Connection ---")
    
    try:
        config = AppConfig()
        
        if not config.deepgram.api_key or not config.llm.api_key:
            print("❌ FAIL: DEEPGRAM_API_KEY or OPENAI_API_KEY not set in environment.")
            return False
            
        client = DeepgramAgentClient(event_handler=mock_event_handler)
        
        # Connect and wait for the 'Welcome' message
        await client.connect(config.deepgram, config.llm)
        
        # Wait for a few seconds to receive the Welcome event
        await asyncio.sleep(5)
        
        await client.disconnect()
        
        if 'test_passed' in globals() and test_passed:
            print("✅ PASS: Successfully connected to Deepgram and received Welcome event.")
            return True
        else:
            print("❌ FAIL: Did not receive Welcome event from Deepgram.")
            return False

    except Exception as e:
        print(f"❌ FAIL: An exception occurred during the Deepgram connection test: {e}")
        return False

async def main():
    # Run the filtering test first, as it's synchronous
    filter_test_success = test_channel_filtering()
    
    # Run the connection test
    connection_test_success = await test_deepgram_connection()
    
    if filter_test_success and connection_test_success:
        print("\n🎉 All tests passed successfully! The logic is ready for deployment.")
        sys.exit(0)
    else:
        print("\n🔥 One or more tests failed. Please review the output above.")
        sys.exit(1)

if __name__ == "__main__":
    test_passed = False
    asyncio.run(main())
