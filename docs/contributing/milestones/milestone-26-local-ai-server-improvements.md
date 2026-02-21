# Milestone 26: Local AI Server Improvements (GPU hardening + Whisper stability)

## Summary

Harden the fully-local `local_ai_server` path (STT/LLM/TTS over WebSocket) for GPU cloud testing (Vast.ai) with reliable model switching via Admin UI, Whisper STT stability on ExternalMedia, and safe/consistent LLM prompting (including large system prompts).

## Status: 🚧 In Progress

## Problem Statement

Testing the “Fully Local” provider on a rented GPU exposed a few reliability gaps:

- **Whisper STT loop / self-echo**: with ExternalMedia, the agent could re-enter capture too early and keep responding while TTS was still playing.
- **Local LLM prompt mismatch**: the AI engine’s configured context/system prompt wasn’t consistently applied to `local_ai_server`, leading to irrelevant responses.
- **LLM context overflow**: large system prompts could exceed `LOCAL_LLM_CONTEXT` (default `768`) and crash llama.cpp with `Requested tokens exceed context window`.
- **Cloud reality**: Vast container templates don’t provide `systemd`/Docker daemon; the “GA” compose stack requires a VM instance + working NVIDIA Container Toolkit.

## Solution

### 1) Whisper-only stability for continuous-stream transport

Make “segment gating re-arm” behavior apply to the Local provider only when the runtime STT backend is Whisper, to avoid regressions in Vosk/Sherpa/Kroko.

### 2) Prompt sync between AI engine and local_ai_server

At session start, push the AI engine’s system prompt to `local_ai_server` so local LLM inference matches the configured context.

### 3) LLM context hardening

- Default the local server’s context window to **2048** when `GPU_AVAILABLE=true` (unless overridden via `LOCAL_LLM_CONTEXT`).
- Add server-side guards so **no prompt** can exceed `n_ctx`:
  - Truncate system prompt as a last resort when the configured context is too small.
  - Reduce `max_tokens` dynamically based on prompt size.

## Implementation Details

### Local AI Server

| File | Change |
|------|--------|
| `local_ai_server/config.py` | Default `llm_context` to `2048` when `GPU_AVAILABLE=true` unless `LOCAL_LLM_CONTEXT` is set |
| `local_ai_server/server.py` | Guard llama.cpp calls: reduce `max_tokens` to fit context, and prevent prompt > `n_ctx` |
| `local_ai_server/server.py` | Prompt builder hardening: if system prompt alone exceeds `n_ctx`, truncate it (last resort) |
| `local_ai_server/server.py` | Emit `stt_backend` field in `stt_result` payloads for engine-side backend-aware logic |

### AI Engine / Local Provider

| File | Change |
|------|--------|
| `src/providers/local.py` | On session start, request `status` from `local_ai_server` and sync `llm_config.system_prompt` (deduped by digest) |
| `src/providers/local.py` | Track runtime STT backend from `stt_result.stt_backend` (`faster_whisper` / `whisper_cpp`) |
| `src/engine.py` | Re-arm segment gating for `local` provider **only when** runtime STT backend is Whisper |

### Tests

| File | Change |
|------|--------|
| `tests/test_local_ai_server_config.py` | Verify `LOCAL_LLM_CONTEXT` default behavior (GPU=2048, CPU=768, env override respected) |
| `tests/test_local_provider_audio_timing.py` | Coverage for Whisper-only gating + backend detection (added during this milestone) |

## Operational Notes (Vast.ai)

- **Container/Jupyter templates**: good for quick model/latency benchmarking, but typically **don’t** run Docker daemon (`preflight.sh` will fail).
- **VM templates**: required for the full compose stack and long-running services.
- **GPU Docker**: ensure NVIDIA Container Toolkit is configured so Compose can allocate `--gpus`.

## Verification Checklist

- `local_ai_server` starts on GPU with `LOCAL_LLM_GPU_LAYERS=-1` and `LOCAL_LLM_CONTEXT` unset → `llm_context=2048`.
- Switching to Whisper STT (Faster-Whisper or whisper.cpp) no longer causes continuous self-talk on ExternalMedia.
- Switching between STT/TTS/LLM models via Admin UI succeeds for shipped backends; failures are capability-aware and actionable.
- No `Requested tokens exceed context window` errors in `local_ai_server` logs when using the default `default` context prompt.

