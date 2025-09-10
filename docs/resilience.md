# Resilience and Error Handling v3.0

This document outlines the resilience and error handling strategies for the Asterisk AI Voice Agent v3.0.

## 1. AI Provider Resilience

Since the core AI logic is handled by external providers (like Deepgram), the primary resilience strategy involves managing the connection to these services.

### 1.1 Connection Management

-   **Automatic Reconnection**: The `DeepgramAgentClient` (and future provider clients) will implement automatic reconnection logic with exponential backoff in case the WebSocket connection is dropped.
-   **Keep-Alive Messages**: The client sends periodic keep-alive messages to prevent the connection from timing out.

### 1.2 Graceful Degradation

If the AI provider is unavailable, the system will fall back to a basic, scripted response.

-   **Provider Unreachable**: If the initial connection to the provider fails, the call will be handled by a fallback mechanism that plays a pre-recorded message (e.g., "We are currently experiencing technical difficulties. Please call back later.") and then hangs up.
-   **Mid-call Failure**: If the connection drops during a call, the system will attempt to reconnect. If it fails, it will play the same error message and terminate the call.

## 2. Asterisk ARI Connection

The connection to the Asterisk server's ARI is critical.

-   **Circuit Breaker**: The `ARIClient` uses a circuit breaker pattern (`pybreaker`). If multiple attempts to connect to ARI fail, the circuit will open, and the service will immediately report itself as unhealthy without flooding the network with connection attempts.
-   **Health Checks**: The service's `/health` endpoint constantly monitors the ARI connection status.

## 3. Health Checks

The `call_controller` service exposes a `/health` endpoint that provides the overall health of the system.

-   **Endpoint**: `http://localhost:15000/health`
-   **Healthy Response**: `{"status": "healthy", "dependencies": {"ari": "connected", "redis": "connected", "ai_provider": "connected"}}` (HTTP 200)
-   **Unhealthy Response**: `{"status": "unhealthy", ...}` (HTTP 503)
-   **Dependency Checks**:
    -   **ARI**: Is the WebSocket connection to Asterisk active?
    -   **Redis**: Can we connect to the Redis server?
    -   **AI Provider**: Is the connection to the selected AI provider active?

## 4. Operational Runbook

### Scenario: Service is Unhealthy or in a Restart Loop

1.  **Symptom**: `docker-compose ps` shows the `call_controller` restarting, or the `/health` endpoint returns a 503 error.
2.  **Check Logs**: `docker-compose logs -f call_controller`.
3.  **Potential Causes & Fixes**:
    -   **Cannot connect to ARI**:
        -   Verify Asterisk is running.
        -   Check the ARI user, password, and host in your `.env` file.
        -   Ensure network connectivity between the container and Asterisk.
    -   **Cannot connect to AI Provider**:
        -   Verify the API keys in your `.env` file are correct.
        -   Check for network connectivity to the provider's API endpoint (e.g., `agent.deepgram.com`).
        -   Check the provider's status page for outages.
    -   **Cannot connect to Redis**:
        -   Verify the Redis container is running (`docker-compose ps`).
        -   Check Redis logs (`docker-compose logs redis`).
