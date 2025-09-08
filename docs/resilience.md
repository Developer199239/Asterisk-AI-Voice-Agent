# Resilience and Error Handling

This document outlines the resilience and error handling strategies implemented in the Asterisk AI Voice Agent v2.0 to ensure high availability and graceful degradation of service.

## 1. Retry Mechanisms

External API calls are susceptible to transient failures. To handle this, we use the `tenacity` library to implement an exponential backoff retry strategy.

- **Library:** `tenacity`
- **Strategy:** Exponential backoff with jitter.
- **Configuration:**
  - **Attempts:** 3-5 retries.
  - **Wait Time:** Exponentially increasing wait time between retries (e.g., 1s, 2s, 4s, ...).
- **Services Affected:** `llm_service`, `tts_service`, `stt_service` (for OpenAI API calls).

### Example: `llm_service` OpenAI Client

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import APIConnectionError, RateLimitError, APIStatusError

@retry(
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((APIConnectionError, RateLimitError, APIStatusError))
)
async def _create_completion_with_retry(...):
    # ... OpenAI API call ...
```

## 2. Circuit Breaker Pattern

To prevent a single failing service from causing a cascade failure across the system, we use the circuit breaker pattern for critical service-to-service communication.

- **Library:** `pybreaker`
- **Strategy:** The circuit breaker monitors for failures. After a certain number of failures, it "opens" and subsequent calls fail immediately without attempting to contact the failing service. After a timeout, it enters a "half-open" state to test if the service has recovered.
- **Configuration:**
  - **Max Failures:** 3-5 consecutive failures.
  - **Reset Timeout:** 30-60 seconds.
- **Services Affected:**
  - `shared/redis_client.py`: Protects all Redis publish and subscribe operations.
  - `services/call_controller/ari_client.py`: Protects all HTTP calls to the Asterisk REST Interface (ARI).

## 3. Fallback Strategies (Graceful Degradation)

When a service or its dependencies fail permanently (i.e., retries and circuit breakers have failed), the system gracefully degrades its functionality.

- **STT Service Failure:** If the Speech-to-Text service fails to process audio, it publishes an error message to the message queue. This results in the system playing a message like, "I'm sorry, I didn't catch that. Could you please repeat yourself?".
- **LLM Service Failure:**
  1.  **Primary to Fallback Model:** The `LLMService` will first attempt to fall back from the primary model (e.g., `gpt-4o`) to a secondary model (e.g., `gpt-3.5-turbo`).
  2.  **Scripted Responses:** If all LLM models are unavailable, the `LLMService` uses the `FallbackResponseManager` to provide a scripted, generic error response (e.g., "I'm sorry, I'm having some technical difficulties.").
- **TTS Service Failure:** If the Text-to-Speech service (OpenAI TTS) fails, the `TTSService` falls back to using the Asterisk `SayAlpha` application to read the response aloud.

## 4. Health Checks

Each microservice exposes a standardized `/health` endpoint using FastAPI. This endpoint provides the overall health status of the service and the status of its critical dependencies.

- **Endpoint:** `/health`
- **Healthy Response:** `{"status": "healthy", ...}` with HTTP status code 200.
- **Unhealthy Response:** `{"status": "unhealthy", ...}` with HTTP status code 503.
- **Dependency Checks:**
  - `call_controller`: Checks ARI, Redis, and RTPEngine.
  - `stt_service`: Checks Redis and OpenAI Realtime API.
  - `llm_service`: Checks Redis and OpenAI API.
  - `tts_service`: Checks Redis and OpenAI TTS API.

## 5. Operational Runbook

### Scenario: `call_controller` is unhealthy

1.  **Symptom:** The `/health` endpoint for the `call_controller` returns a 503 status, or the service is in a restart loop.
2.  **Check Logs:** `docker-compose logs call_controller`.
3.  **Potential Causes & Fixes:**
    - **Cannot connect to ARI:**
      - Verify Asterisk is running.
      - Check `ari.conf` and `http.conf` in Asterisk.
      - Ensure the ARI user and password in `.env` are correct.
      - Check for network connectivity issues between the Docker container and the Asterisk host.
    - **Cannot connect to Redis:**
      - Verify the Redis container is running (`docker-compose ps`).
      - Check Redis logs (`docker-compose logs redis`).

### Scenario: A specific AI service (STT, LLM, TTS) is unhealthy

1.  **Symptom:** The `/health` endpoint for the service returns a 503 status, or the service is in a restart loop.
2.  **Check Logs:** `docker-compose logs <service_name>`.
3.  **Potential Causes & Fixes:**
    - **OpenAI API Connection Error:**
      - Verify the `OPENAI_API_KEY` in the `.env` file is correct and has not expired.
      - Check for network connectivity to `api.openai.com`.
      - Check the OpenAI status page for outages.
    - **Invalid Model Error:** The model specified for the service may be incorrect or deprecated. Check the service's client configuration and update the model name.
