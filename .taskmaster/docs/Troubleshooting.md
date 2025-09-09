# Asterisk AI Voice Agent - Troubleshooting Guide

This document tracks common issues, diagnostic steps, and resolutions encountered during the development of the Asterisk AI Voice Agent v2.0.

## Issue: `call_controller` service in a crash/restart loop

### Symptom 1: `ari show app <app_name>` fails or shows no registration.
- **Initial Diagnosis:** The service is not starting correctly or is crashing before it can register with ARI.
- **Finding 1.1:** `docker logs` shows the container starting and stopping immediately with an exit code of `0`.
    - **Cause:** The main `asyncio` event loop in `services/call_controller/main.py` was not blocking. The script ran to completion and exited successfully without keeping the service alive.
    - **Resolution:** Rewrote the `main` function to use `asyncio.Event()` and signal handlers (`SIGINT`, `SIGTERM`) to create a persistent loop that waits for a shutdown signal before exiting gracefully.

### Symptom 2: `ConnectionTimeoutError` when connecting to ARI.
- **Initial Diagnosis:** The `call_controller` container cannot establish a network connection to the Asterisk server on the ARI port (8088).
- **Finding 2.1:** A minimal diagnostic script (`test_ari.py`) confirmed the timeout was due to networking, not a Python environment issue. The Docker bridge network could not reach the host's port.
    - **Cause:** Firewall rules or Docker networking complexities were blocking the connection from the container's private IP to the host.
    - **Resolution:** Switched the `call_controller` service in `docker-compose.yml` to use `network_mode: host`. This places the container directly on the host's network stack, allowing it to connect to Asterisk via `127.0.0.1`. The `ASTERISK_HOST` environment variable was overridden in `docker-compose.yml` to point to `127.0.0.1`.

### Symptom 3: `redis... Name or service not known` in logs after switching to host networking.
- **Initial Diagnosis:** With the `call_controller` on the host network, it could no longer resolve the hostname `redis`, which only existed on the Docker bridge network.
- **Finding 3.1:** The service crashed immediately upon startup because it couldn't connect to its Redis dependency.
    - **Cause:** Inconsistent network modes between services.
    - **Resolution:**
        1. Moved all services (`redis`, `stt_service`, etc.) to `network_mode: host` in `docker-compose.yml` for consistent networking.
        2. Overrode the `REDIS_URL` environment variable in `docker-compose.yml` for all services to `redis://127.0.0.1:6379`.
        3. Added tenacious retry logic to the `RedisMessageQueue.connect()` method in `shared/redis_client.py` to handle startup race conditions where a service might start before Redis is fully initialized.

### Symptom 4: Pydantic `ValidationError` for `CallNewMessage`.
- **Initial Diagnosis:** The application crashed during call handling (`StasisStart` event).
- **Finding 4.1:** Logs showed that required fields (`message_id`, `source_service`, `call_id`) were missing when creating the `CallNewMessage` object.
    - **Cause:** The `_handle_stasis_start` method in `services/call_controller/main.py` was not generating or supplying these required values.
    - **Resolution:** Updated the `_handle_stasis_start` method to import `uuid` and generate unique IDs for `message_id` and `call_id`, and to correctly populate all required fields from the event and config data.

### Symptom 5: `rtpengine` Connection Error: `Cannot connect to host 172.20.0.3:2223`.
- **Initial Diagnosis:** After fixing the Redis issue, the service failed when trying to connect to `rtpengine`.
- **Finding 5.1:** The service was still trying to connect to the old, hardcoded Docker bridge IP for `rtpengine`.
    - **Cause:** The `RTPENGINE_HOST` was not being correctly set for host networking mode.
    - **Resolution:** Overrode the `RTPENGINE_HOST` environment variable in `docker-compose.yml` for the `call_controller` service to `127.0.0.1`.

### Symptom 6: `AttributeError: 'RedisMessageQueue' object has no attribute 'listen'`.
- **Initial Diagnosis:** The service crashes, but the logs show the error is happening after the ARI and Redis connections are established.
- **Finding 6.1:** An incorrect method name was used to listen for Redis messages.
    - **Cause:** A likely Docker build caching issue where an older version of `shared/redis_client.py` was being used in the container, even after the code was updated locally. The fix was correct, but the deployment was stale.
    - **Resolution:**
        1. Corrected the code in `services/call_controller/main.py` to use the proper `listen()` method.
        2. Added `docker system prune -f` to the deployment script on the server to force the removal of old images and cache, ensuring a clean build with the latest code.
