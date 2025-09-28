# Tests Overview

This document explains the test layout and how to run tests locally and on a server.

## Test Locations

- `tests/`: Python unit/integration tests for the engine and pipelines
  - `tests/test_audio_resampler.py`
  - `tests/test_pipeline_*.py` (adapters and runner lifecycle)
  - `tests/test_playback_manager.py`
  - `tests/test_session_store.py`
- `scripts/test_externalmedia_call.py`: Health-driven end-to-end call flow check
- `scripts/test_externalmedia_deployment.py`: ARI + RTP deployment sanity
- `local_ai_server/test_local_ai_server.py`: Local AI server smoke test (optional)

## Prerequisites

- Engine running via `docker-compose up -d` (or `make up`)
- Health endpoint available at `http://127.0.0.1:15000/health`
- Python 3.10+ and dependencies (inside the ai-engine container or host venv)

## Running Unit Tests

Run inside the ai-engine container (recommended):

```bash
# From repo root
docker-compose exec ai-engine pytest -q
```

Or locally (ensure venv matches requirements):

```bash
pip install -r requirements.txt
pytest -q
```

## Running End-to-End ExternalMedia Tests

- Call flow test:

```bash
python3 scripts/test_externalmedia_call.py --url http://127.0.0.1:15000/health
```

- Deployment sanity:

```bash
python3 scripts/test_externalmedia_deployment.py
```

## Troubleshooting

- Ensure containers are healthy: `make ps` and `make logs`
- Clear logs between runs to improve signal: `make server-clear-logs` (localhost-aware)
- Validate configuration: `python3 scripts/validate_externalmedia_config.py`

## CI Suggestions (Optional)

- Add a GitHub Action to run `pytest -q` on PRs
- Publish captured logs as artifacts when E2E tests fail
