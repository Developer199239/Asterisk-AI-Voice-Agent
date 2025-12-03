# Walkthrough - Local AI Server Support

## Overview
This update improves the handling of the Local AI Server in the Admin UI. It enables specific configuration for the local provider, activates the system monitoring page, and ensures the local server is correctly set up and integrated with the wizard.

## Changes

### 1. Providers Page (`ProvidersPage.tsx`)
-   Imported `LocalProviderForm`.
-   Added logic to render `LocalProviderForm` when the provider name is `local`.
-   This exposes fields for:
    -   WebSocket URL (`ws_url`)
    -   LLM Model (`llm_model`)
    -   STT Model (`stt_model`)
    -   TTS Model (`tts_model`)
    -   LLM URL (`llm_url`)

### 2. Docker Page (`DockerPage.tsx`)
-   Removed mock data.
-   Implemented `fetchContainers` using `axios.get('/api/system/containers')`.
-   Implemented `handleRestart` using `axios.post('/api/system/containers/{id}/restart')`.
-   Added error handling and loading states.

### 3. Wizard Integration (`wizard.py` & `Wizard.tsx`)
-   **Backend**: Added logic to `save_setup_config` to check for and start the `local_ai_server` container if `local_hybrid` is selected.
-   **Frontend**: Added a visual indicator in the Wizard to inform users that the local server is required for the hybrid mode.

### 4. Local Server Setup
-   **Dockerfile**: Fixed missing `libatomic1` dependency in `local_ai_server/Dockerfile`.
-   **Models**: Ran `scripts/model_setup.sh` to download required STT/LLM/TTS models.

## Verification

### Automated Tests
-   **Backend API**: Verified `Docker API` returns running containers (`verify_local_flow.py`).
-   **Local Server**: Verified `local_ai_server` container is running and healthy (`verify_local_server.py`).

### UI Verification (Browser Test)
-   **Providers Page**: Confirmed that editing the "local" provider shows the specialized form with WebSocket and Model fields.
-   **Docker Page**: Confirmed that the page lists `local_ai_server`, `admin_ui`, and `ai_engine` with "running" status.
-   **Wizard**: Confirmed that selecting "Local Hybrid" displays the "Local Server Required" warning box.

### 5. Dashboard Health Checks
-   **Backend**: Implemented `/api/system/health` to aggregate status from `local_ai_server` (WebSocket) and `ai_engine` (HTTP).
-   **Frontend**: Added `HealthWidget` to `DockerPage` to display real-time status of AI services.
-   **Infrastructure**: Switched `ai_engine` and `local_ai_server` to `bridge` network mode to enable reliable inter-container communication.
-   **Configuration**: Updated `ai-agent.yaml` to point `ai_engine` to `ws://local_ai_server:8765`.

> [!NOTE]
> `local_ai_server` takes several minutes to load models (RNNLM). During this time, the health check will report "Error" or "Connecting". This is normal behavior.

### Debugging & Fixes
- **Local AI Server**: Fixed "Connection Rejected" (400) error by disabling strict Origin header checks in `main.py`. This allows the Admin UI (running in a container) to connect via WebSocket.
- **AI Engine**: Fixed "Connection Refused" to Asterisk by setting `ASTERISK_HOST=host.docker.internal` in `docker-compose.yml`. This allows the engine to reach the host's Asterisk instance from the bridge network.
- **Health Status**:
    - `local_ai_server`: Now shows "Connected" (Green) when models are loaded.
    - `ai_engine`: Now shows "Degraded" (Yellow) if Asterisk is not running, but the health endpoint itself is reachable.

### Dashboard Enhancements
- **Health Widget**: Moved to the main Dashboard page. Now displays:
    - **Local AI Server**: STT, LLM, and TTS model names and load status.
    - **AI Engine**: ARI connection status, active pipelines, and provider readiness.
- **Service Status**: Removed redundant section from Dashboard; consolidated into the Health Widget.
- **Docker Page**: Removed the Health Widget to reduce duplication.

### Stability Improvements
- **Parallel Health Checks**: Updated `/api/system/health` to fetch `local_ai_server` and `ai_engine` status concurrently using `asyncio.gather`, reducing total latency and preventing timeouts.
- **Non-Blocking Metrics**: Updated `/api/system/metrics` to use non-blocking CPU usage collection, preventing API contention.
- **Error Handling**: Improved error logging in the backend to aid debugging.

### Verification Results (Health Checks)
-   **Backend API**: Verified `/api/system/health` returns valid JSON for both services, including new `pipelines` and `providers` fields.
-   **Connectivity**: Confirmed `admin_ui` can reach `local_ai_server` (WebSocket) and `ai_engine` (HTTP).
-   **Frontend**: Verified Health Widget displays status correctly (no longer "Error").
