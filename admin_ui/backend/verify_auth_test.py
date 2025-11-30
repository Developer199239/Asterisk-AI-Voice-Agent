import requests
import time
import sys

BASE_URL = "http://localhost:8000"

def wait_for_backend():
    print("Waiting for backend...")
    for _ in range(10):
        try:
            requests.get(f"{BASE_URL}/health")
            print("Backend is up!")
            return True
        except:
            time.sleep(1)
    return False

def test_auth():
    if not wait_for_backend():
        print("Backend failed to start")
        sys.exit(1)

    # 1. Test unauthorized access
    print("Testing unauthorized access...")
    try:
        res = requests.get(f"{BASE_URL}/api/wizard/status")
        if res.status_code == 401:
            print("✅ Unauthorized access blocked (401)")
        else:
            print(f"❌ Expected 401, got {res.status_code}")
            sys.exit(1)
    except Exception as e:
        print(f"❌ Request failed: {e}")
        sys.exit(1)

    # 2. Login
    print("Testing login...")
    login_data = {"username": "admin", "password": "admin"}
    res = requests.post(f"{BASE_URL}/api/auth/login", data=login_data)
    if res.status_code == 200:
        token = res.json()["access_token"]
        print("✅ Login successful")
    else:
        print(f"❌ Login failed: {res.status_code} {res.text}")
        sys.exit(1)

    # 3. Test authorized access
    print("Testing authorized access...")
    headers = {"Authorization": f"Bearer {token}"}
    res = requests.get(f"{BASE_URL}/api/wizard/status", headers=headers)
    if res.status_code == 200:
        print("✅ Authorized access successful")
    else:
        print(f"❌ Authorized access failed: {res.status_code}")
        sys.exit(1)

    # 4. Change password
    print("Testing password change...")
    change_data = {"old_password": "admin", "new_password": "newpass"}
    res = requests.post(f"{BASE_URL}/api/auth/change-password", json=change_data, headers=headers)
    if res.status_code == 200:
        print("✅ Password change successful")
    else:
        print(f"❌ Password change failed: {res.status_code} {res.text}")
        sys.exit(1)

    # 5. Login with new password
    print("Testing login with new password...")
    login_data = {"username": "admin", "password": "newpass"}
    res = requests.post(f"{BASE_URL}/api/auth/login", data=login_data)
    if res.status_code == 200:
        print("✅ Login with new password successful")
    else:
        print(f"❌ Login with new password failed: {res.status_code} {res.text}")
        sys.exit(1)

    # 6. Revert password
    print("Reverting password...")
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    change_data = {"old_password": "newpass", "new_password": "admin"}
    res = requests.post(f"{BASE_URL}/api/auth/change-password", json=change_data, headers=headers)
    if res.status_code == 200:
        print("✅ Password reverted")
    else:
        print(f"❌ Password revert failed: {res.status_code}")
        sys.exit(1)

    print("\n🎉 ALL AUTH TESTS PASSED")

if __name__ == "__main__":
    test_auth()
