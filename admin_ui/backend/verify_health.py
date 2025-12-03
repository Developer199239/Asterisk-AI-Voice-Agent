import requests
import json

def test_health_endpoint():
    try:
        # Assuming admin_ui is running on localhost:3003 (mapped to 8000)
        # Wait, the user accesses it via 3003, but I might need to access it via the container IP or localhost if mapped.
        # The docker-compose says "3003:8000".
        url = "http://localhost:3003/api/system/health"
        
        # We need authentication. I'll use the login flow from verify_auth_test.py
        # We need authentication. I'll use the login flow from verify_auth_test.py
        auth_url = "http://localhost:3003/api/auth/login"
        auth_data = {"username": "admin", "password": "admin"}
        
        print(f"Logging in to {auth_url}...")
        auth_response = requests.post(auth_url, data=auth_data)
        if auth_response.status_code != 200:
            print(f"Login failed: {auth_response.text}")
            return

        token = auth_response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        print(f"Testing {url}...")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            print("Success! Response:")
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Failed with status {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_health_endpoint()
