# Local AI Server Improvements (GPU Host) — Progress Log

Branch: `local-ai-server-improvements`  
Primary host: `root@10.44.0.103`  
Scope: Local (no cloud) two-way telephony conversation quality/latency.

## Problem Statement

Whisper-family STT backends (`faster_whisper`, `whisper_cpp`) are batch models. The previous Local AI Server implementation was emitting “final” transcripts on a fixed ~1s buffer, which:

- Chopped utterances into unnatural fragments (poor coherence).
- Increased turn-taking errors (LLM responds to partial thoughts).
- Increased the chance of punctuation-only “finals” (e.g., `"?"`) reaching downstream logic.

## Changes Implemented

### 1) Admin UI: model guidance + correct “Installed” detection

- File: `admin_ui/frontend/src/pages/System/ModelsPage.tsx`
- Adds: description + notes + recommended badge (from models catalog).
- Fixes: “Installed” detection false positives (previously used substring match, which could match unrelated files like TTS model names).
- Commit (already pushed): `c119ba12 ui: improve STT model guidance and install detection`

### 2) Local AI Server: shared Whisper-family telephony segmenter (utterance endpointer)

Files:

- `local_ai_server/server.py`
  - Replaces “1s chunk => final transcript” for `faster_whisper` and `whisper_cpp`.
  - Adds energy-based utterance segmentation with preroll + silence endpointer.
  - Runs one-shot decode per utterance using backend `transcribe_pcm16()`.
  - Adds `_whisper_cpp_lock` to avoid concurrent Whisper.cpp access.
- `local_ai_server/stt_backends.py`
  - Adds `transcribe_pcm16(pcm16_16khz_mono: bytes) -> str` for both backends.
- `local_ai_server/config.py`
  - Adds telephony segmentation knobs (separate from `LOCAL_STT_IDLE_MS`).
- `local_ai_server/session.py`
  - Adds per-call segmentation state.

### New Env Knobs (Local AI Server)

- `LOCAL_STT_SEGMENT_ENERGY_THRESHOLD` (default `1200`)
- `LOCAL_STT_SEGMENT_PREROLL_MS` (default `200`)
- `LOCAL_STT_SEGMENT_MIN_MS` (default `250`)
- `LOCAL_STT_SEGMENT_SILENCE_MS` (default `500`)
- `LOCAL_STT_SEGMENT_MAX_MS` (default `12000`)

## Rationale / Expected Impact

- Fewer STT “finals”, but each “final” is a complete utterance (better coherence).
- Lower turn-taking jitter (LLM gets full thought, not 1s fragments).
- Better multilingual baseline because segmentation is language-agnostic and telephony-friendly.

## Deployment Notes (Git-tracked only)

On `10.44.0.103`:

- Pull tracked branch: `local-ai-server-improvements`
- Rebuild `local_ai_server` (image-baked code; not bind-mounted like `ai_engine`).
- Restart `local_ai_server` container.

## Test Calls / Observations (references)

- `1772235703.109` — whisper.cpp call where conversation was incoherent / agent “not hearing”.
- Future: after deployment, re-run this scenario with identical model combo to compare.

## Rollback

- On host, reset to previous known good commit, rebuild `local_ai_server`, restart.

## 2026-02-28 — UI/Config Alignment Pass

### Goals

- Align Admin UI env keys with Local AI Server runtime keys.
- Expose previously hidden runtime knobs for STT/TTS/LLM.
- Preserve backward compatibility for older `.env` keys.

### Changes

- `admin_ui/frontend/src/pages/System/EnvPage.tsx`
  - Fixed STT idle key mapping to canonical `LOCAL_STT_IDLE_MS` (with UI fallback read for legacy `LOCAL_STT_IDLE_TIMEOUT_MS`).
  - Fixed Whisper.cpp model path mapping to canonical `WHISPER_CPP_MODEL_PATH` (with legacy read fallback in UI).
  - Added Whisper segmentation controls for whisper-family STT:
    - `LOCAL_STT_SEGMENT_ENERGY_THRESHOLD`
    - `LOCAL_STT_SEGMENT_SILENCE_MS`
    - Advanced: `LOCAL_STT_SEGMENT_PREROLL_MS`, `LOCAL_STT_SEGMENT_MIN_MS`, `LOCAL_STT_SEGMENT_MAX_MS`
  - Added missing Whisper.cpp language control: `WHISPER_CPP_LANGUAGE`.
  - Added missing Kokoro controls: `KOKORO_LANG`, `KOKORO_API_MODEL`.
  - Added missing advanced LLM controls:
    - `LOCAL_LLM_GPU_LAYERS_AUTO_DEFAULT`
    - `LOCAL_TOOL_GATEWAY_ENABLED`
    - `LOCAL_LLM_SYSTEM_PROMPT`
    - `LOCAL_LLM_STOP_TOKENS`
  - Added tooltips for all newly exposed options.
- `local_ai_server/config.py`
  - Added compatibility alias for Whisper.cpp path:
    - `WHISPER_CPP_MODEL_PATH` OR legacy `LOCAL_WHISPER_CPP_MODEL_PATH`
  - Added compatibility alias for STT idle timeout:
    - `LOCAL_STT_IDLE_MS` OR legacy `LOCAL_STT_IDLE_TIMEOUT_MS`

### Validation

- `python3 -m py_compile local_ai_server/config.py` passed.
- `npm --prefix admin_ui/frontend run build` passed.

## 2026-02-28 — LLM Tool-Calling Alignment Fixes

### Root Cause Investigation (call `1772257351.121`)

The `hangup_call` tool failed to execute despite the caller explicitly requesting to hang up.
Investigation revealed a chain of failures in the LLM hot-reload and tool-calling pipeline:

1. **Qwen 2.5-3B loaded with wrong `chat_format`** — After switching from Llama 3.1-8B (`llama-3`) to Qwen 2.5-3B (`chatml`) via Admin UI, the `chat_format` was not propagated during hot-reload. Qwen ran with the stale `llama-3` template.
2. **Tool capability probe used wrong API path** — The probe always used raw text completion (`self.llm_model(prompt)`) instead of the chat completion API (`create_chat_completion()`), which chat-format models require. Result: `level=none` (false negative).
3. **`policy=off` blocked all tools including hangup heuristic** — When probe returned `none`, `_resolve_tool_policy()` set `policy=off`, which completely disabled tool dispatch including the text-based `hangup_call` heuristic that doesn't need LLM tool-calling capability.

### Fixes Implemented

#### Fix 1: `chat_format` in `_LLM_CONFIG_MAP` (Critical)

- **File**: `local_ai_server/control_plane.py`
- **Change**: Added `"chat_format": "llm_chat_format"` to `_LLM_CONFIG_MAP`
- **Impact**: `chat_format` is now propagated to `LocalAIConfig` during hot-reload model switches via `apply_switch_model_request()`.

#### Fix 2: `chat_format` in WS switch payload (Critical)

- **File**: `admin_ui/backend/api/local_ai.py`
- **Change**: When building the `switch_model` WS payload for LLM switches, the backend now resolves `chat_format` from the model catalog (`LLM_MODELS`) by matching on `model_path` and includes it in `llm_config`.
- **Impact**: The hot-reload path sends the correct `chat_format` for the new model, so `local_ai_server` applies it immediately (no container restart needed).

#### Fix 3: Tool probe uses correct API path (Medium)

- **File**: `local_ai_server/server.py` (`_probe_llm_tool_capability`)
- **Change**: When `self.llm_chat_format` is set, the probe now uses `create_chat_completion()` with a system+user message pair instead of raw `self.llm_model(prompt)`. Falls back to raw completion for models without `chat_format`.
- **Impact**: Probe results now match the actual inference path used during calls.

**Before**: Qwen 2.5-3B probe → `level=none` (wrong chat template + wrong API)  
**After**: Qwen 2.5-3B probe → `level=partial` with `chat_format=chatml` ✅

#### Fix 4: `hangup_call` heuristic works when `policy=off` (Medium)

- **File**: `src/providers/local.py` (`_process_llm_text_fallback`)
- **Change**: When `policy=off`, instead of unconditionally setting `tool_calls = None`, the code now checks if:
  - `hangup_call` is in `_allowed_tools`, AND
  - the last user transcript contains end-of-call intent markers (same marker list as `local_ai_server`).
  If both conditions are met, emits `hangup_call` with `tool_path=heuristic`.
- **Impact**: Callers can always hang up gracefully, regardless of LLM tool-calling capability.
- **Added**: `_END_CALL_MARKERS` tuple and `_user_has_end_call_intent()` method on `LocalProvider`.

#### Fix 5: Qwen 2.5-3B catalog metadata (Low)

- **File**: `admin_ui/backend/api/models_catalog.py`
- **Change**: Added `"tool_calling": "experimental"` and `tool_calling_note` to the Qwen 2.5-3B entry.
- **Impact**: Admin UI now shows accurate tool-calling support info for Qwen 2.5-3B.

### Model Catalog Audit

All 15 LLM models in `LLM_MODELS` were audited for `chat_format` correctness:

| Model | chat_format | tool_calling | Correct? |
|-------|-------------|-------------|----------|
| TinyLlama 1.1B | chatml | — | ✅ |
| Llama 3.2-3B | llama-3 | — | ✅ |
| Phi-3-mini-4K | chatml | experimental | ✅ |
| Qwen 2.5-3B | chatml | experimental (new) | ✅ |
| Gemma 2-2B | gemma | — | ✅ |
| Mistral 7B v0.3 | mistral-instruct | — | ✅ |
| Qwen 2.5-7B | chatml | recommended | ✅ |
| Llama 3.1-8B | llama-3 | recommended | ✅ |
| Functionary v3.2 | functionary-v2 | recommended | ✅ |
| Hermes 3 (8B) | chatml | recommended | ✅ |
| Mistral Nemo 12B | mistral-instruct | recommended | ✅ |
| Command R7B | chatml | recommended | ✅ |
| Gemma 2-9B | gemma | — | ✅ |
| Phi-4-14B | chatml | — | ✅ |
| Qwen 2.5-14B | chatml | — | ✅ |

### Deployment

- **Commit**: `08cb2db7` on branch `local-ai-server-improvements`
- **Server**: `root@10.44.0.103` (`/root/AVA-AI-Voice-Agent-for-Asterisk`)
- **Build**: `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build local_ai_server ai_engine`
- **Validation**:
  - `local_ai_server` log: `chat_format=chatml`, probe `level=partial` ✅
  - `ai_engine` log: `Provider validated and ready` ✅, `Engine started and listening for calls` ✅

### Files Changed

| File | Lines Changed |
|------|--------------|
| `local_ai_server/control_plane.py` | +1 (chat_format in _LLM_CONFIG_MAP) |
| `admin_ui/backend/api/local_ai.py` | +8 (catalog lookup + chat_format in payload) |
| `local_ai_server/server.py` | +33 −14 (chat-aware probe path) |
| `src/providers/local.py` | +30 (hangup heuristic + end-call markers) |
| `admin_ui/backend/api/models_catalog.py` | +2 (Qwen 2.5-3B tool_calling) |
