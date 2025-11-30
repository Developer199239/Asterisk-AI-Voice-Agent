import requests
import json
import sys

BASE_URL = "http://localhost:3003/api"
AUTH_URL = f"{BASE_URL}/auth/login"
WIZARD_SAVE_URL = f"{BASE_URL}/wizard/save"

def login():
    print(f"Logging in to {AUTH_URL}...")
    try:
        response = requests.post(
            AUTH_URL,
            data={"username": "admin", "password": "admin"},
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        if response.status_code == 200:
            token = response.json().get("access_token")
            print("Login successful.")
            return token
        else:
            print(f"Login failed: {response.status_code} - {response.text}")
            sys.exit(1)
    except Exception as e:
        print(f"Login exception: {e}")
        sys.exit(1)

def test_missing_key(token):
    print("\nTesting missing OpenAI key for local_hybrid...")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "provider": "local_hybrid",
        "asterisk_host": "127.0.0.1",
        "asterisk_username": "asterisk",
        "asterisk_password": "password",
        "greeting": "Hello",
        "ai_name": "Asterisk",
        "ai_role": "Assistant",
        # Missing openai_key
    }
    
    try:
        response = requests.post(WIZARD_SAVE_URL, json=payload, headers=headers)
        if response.status_code == 400 and "OpenAI API Key is required" in response.text:
            print("Success: Correctly rejected missing key with 400.")
        else:
            print(f"Failure: Expected 400, got {response.status_code} - {response.text}")
            sys.exit(1)
    except Exception as e:
        print(f"Exception: {e}")
        sys.exit(1)

def test_valid_config(token):
    print("\nTesting valid local_hybrid config...")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "provider": "local_hybrid",
        "asterisk_host": "127.0.0.1",
        "asterisk_username": "asterisk",
        "asterisk_password": "password",
        "greeting": "Hello",
        "ai_name": "Asterisk",
        "ai_role": "Assistant",
        "openai_key": "sk-test-key" # Dummy key, validation is skipped in save endpoint (only format check if any)
    }
    
    try:
        response = requests.post(WIZARD_SAVE_URL, json=payload, headers=headers)
        if response.status_code == 200:
            print("Success: Valid config saved successfully.")
        else:
            print(f"Failure: Expected 200, got {response.status_code} - {response.text}")
            # If it failed with 500, check logs for NameError
            sys.exit(1)
    except Exception as e:
        print(f"Exception: {e}")
        sys.exit(1)

if __name__ == "__main__":
    token = login()
    test_missing_key(token)
    test_valid_config(token)
