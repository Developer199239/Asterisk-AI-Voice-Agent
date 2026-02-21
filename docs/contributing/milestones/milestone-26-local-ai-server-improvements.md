# Milestone 26: Local AI Server Improvements (GPU Hardening + UI Model Switching)

## Summary

Harden `local_ai_server` so it can be deployed on **real GPU hosts** (e.g. Vast.ai) and reliably **switch/load models via the Admin UI** without confusing “it’s running but not loading” failure modes.

Key outcomes:
- Reliable GPU builds respect `.env` build toggles (Compose override parity).
- Kokoro TTS can be hot-switched even when `llama_cpp` is present (CUDA import-order collision fix).
- UI prevents selecting unsupported backends (capability-aware gating).
- CPU-only hosts default to a **minimal** runtime (STT + TTS only) so startup doesn’t depend on LLM files.
- Added repeatable “UI-path” matrix testing script for STT/TTS.

## Status

**Status**: In Progress (hardening + test matrix validation)  
**Date**: February 2026  
**Primary environments**: Ubuntu 24.04 host + Docker Compose; RTX 4090 on Vast.ai; Tailscale for SIP/RTP

## Motivation

Operators need a predictable path to:
1) spin up a CPU-only local stack (STT+TTS) that starts fast and never blocks on LLM files, and
2) upgrade to GPU acceleration + richer model matrix (Whisper, Kokoro, etc.) with **UI-managed switching** that matches what the server can actually load.

## Implementation Details

### 1) GPU Compose override parity

Problem: `docker-compose.gpu.yml` previously replaced the build definition and **dropped build args**, so `.env` toggles like `INCLUDE_FASTER_WHISPER=true` had no effect on GPU builds.

Fix:
- `docker-compose.gpu.yml` forwards the same build args as `docker-compose.yml` (plus Kroko checksum args).

### 2) Kokoro TTS hot-switch reliability (CUDA runtime collision)

Symptom: switching to Kokoro via UI could fail with a misleading “package not installed” message.

Root cause: native extension import order could cause `llama_cpp` to load a CUDA runtime that later breaks `torch` import (required by Kokoro).

Fix:
- `local_ai_server/optional_imports.py`: best-effort preload `torch` before importing `llama_cpp`.
- `local_ai_server/tts_backends.py`: log ImportError with traceback (`exc_info=True`) so operators see the real failure.

### 3) Capability-aware UI gating + rebuild support

Problem: UI allowed selecting backends that the current `local_ai_server` image cannot run (e.g. Kroko embedded without the binary; Whisper backends without packages).

Fixes:
- Wizard STT selection now disables incompatible choices based on `/api/local-ai/capabilities`.
- Models page adds compatibility warnings + force-rebuild flow for:
  - Faster-Whisper
  - Whisper.cpp
  - MeloTTS
  - Kroko embedded (requires `KROKO_SERVER_SHA256`)
- Env page exposes `KROKO_SERVER_SHA256` when Kroko embedded is enabled.

### 4) Whisper.cpp backend support end-to-end

Fixes:
- `local_ai_server/control_plane.py`: correctly applies `stt_model_path` to `whisper_cpp_model_path` when switching backend.
- Admin UI switch payload + env/yaml persistence support `whisper_cpp`.
- Admin UI model scanner recognizes `models/stt/ggml-*.bin` (or `*whisper*.bin`) as `whisper_cpp` models.

### 5) CPU-first minimal defaults

Goal: on CPU-only hosts, `local_ai_server` should start with **only STT+TTS**, defaulting to:
- STT: `vosk`
- TTS: `piper`

Fix:
- `local_ai_server/config.py`: if `LOCAL_AI_MODE` is unset, default to:
  - `full` when `GPU_AVAILABLE=true`
  - `minimal` when `GPU_AVAILABLE=false`
- `.env.example`: no longer hard-sets `LOCAL_AI_MODE=full`; documents the automatic defaulting.

## Validation Checklist

### UI-path model switching matrix (recommended)

Run on the host running Admin UI:
- `python3 tools/ui_model_matrix.py --all-tts --all-stt --json-out /tmp/aava-model-matrix.json`

What it verifies:
- Uses the same endpoints the Admin UI uses (`/api/local-ai/switch`, `/api/local-ai/models`, `/api/local-ai/capabilities`).
- Confirms each selected backend/model switches and reports loaded status.

### Whisper.cpp prerequisites
- `INCLUDE_WHISPER_CPP=true` in the `local_ai_server` image build.
- A ggml model file present in `models/stt/` (e.g. `ggml-base.en.bin`).

### Kroko embedded prerequisites
- `INCLUDE_KROKO_EMBEDDED=true`
- `KROKO_SERVER_SHA256=<sha256>` set in `.env`
- a Kroko model file under `models/kroko/`

## Notes / References

- Operational notes for Vast.ai + Asterisk + Tailscale are kept in `archived/GPU-LEARNINGS.md`.

