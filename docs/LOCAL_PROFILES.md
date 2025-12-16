# Local Profiles (No Models Bundled)

Local mode is a first-class path in this project, but **models are not shipped inside Docker images**. You must download and mount models into `./models` (default) or provide equivalent paths via environment variables.

## Goals

- Predictable “local stack” that boots reliably
- Clear expectations for CPU/RAM/GPU
- Explicit build profiles so contributors don’t accidentally ship multi-GB images

## Recommended Profiles

### Profile: `local-core` (recommended default)

Use when you want “fully local” call handling with the default stack:

- STT: Vosk
- LLM: llama.cpp (GGUF)
- TTS: Piper
- No Sherpa, no Kokoro, no embedded Kroko

Run:

- `docker compose -f docker-compose.yml -f docker-compose.local-core.yml build local-ai-server`
- `docker compose up -d`

### Profile: `local-full` (power users)

Enable additional backends (Sherpa, Kokoro, embedded Kroko). This is heavier, increases build times, and may exceed CI runner disk limits.

Run:

- `docker compose build local-ai-server` (default settings)

## Hardware Expectations (Rule of Thumb)

- **CPU-only “core”:** expect multi-second LLM turns on small CPUs; prioritize fewer concurrent local calls.
- **GPU (if used):** large variance by GPU + model; tune `LOCAL_LLM_GPU_LAYERS` and thread counts.
- **RAM:** ensure the model(s) you choose fit comfortably; leave headroom for Docker + Asterisk.

## Model Paths (defaults)

Mounted by `docker-compose.yml`:

- Host: `./models`
- Container: `/app/models`

Defaults used by `local_ai_server`:

- STT: `LOCAL_STT_MODEL_PATH=/app/models/stt/...`
- LLM: `LOCAL_LLM_MODEL_PATH=/app/models/llm/...`
- TTS: `LOCAL_TTS_MODEL_PATH=/app/models/tts/...`

Adjust these in `.env` to match your downloaded model locations.
