import requests
import sys

BASE_URL = "http://localhost:3003"
LOGIN_URL = f"{BASE_URL}/api/auth/login"
ENV_URL = f"{BASE_URL}/api/config/env"

def debug_env():
    session = requests.Session()
    
    # Login
    print(f"Logging in to {LOGIN_URL}...")
    try:
        resp = session.post(LOGIN_URL, data={"username": "admin", "password": "password"}, timeout=5)
        if resp.status_code == 401:
             # Try default admin/admin
             resp = session.post(LOGIN_URL, data={"username": "admin", "password": "admin"}, timeout=5)
        
        if resp.status_code != 200:
            print(f"Login failed: {resp.status_code} {resp.text}")
            return
        token = resp.json().get("access_token")
        print(f"Login successful. Token: {token[:10]}...")
    except Exception as e:
        print(f"Login connection failed: {e}")
        return

    # Fetch Env
    print(f"Fetching env from {ENV_URL}...")
    try:
        headers = {"Authorization": f"Bearer {token}"}
        resp = session.get(ENV_URL, headers=headers, timeout=5)
        print(f"Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Keys found: {len(data)}")
            print(f"Keys: {list(data.keys())}")
            if 'ASTERISK_HOST' in data:
                print(f"ASTERISK_HOST: {data['ASTERISK_HOST']}")
            else:
                print("ASTERISK_HOST not found in response")
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Env fetch failed: {e}")

if __name__ == "__main__":
    debug_env()
