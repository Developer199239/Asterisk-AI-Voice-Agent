# Local AI Server Deep Audit Report

**Branch**: `local-ai-server-improvements`
**Date**: 2026-02-21 (audit) · 2026-02-21 (implementation update)
**Scope**: End-to-end Local AI Server experience — setup, onboarding, defaults, model switching, cross-machine connectivity

### Implementation Status

| Finding | Status | Commit |
| --- | --- | --- |
| F-2: Auth enforcement (non-loopback) | ✅ Already in `server.py` (fail-closed) | Pre-existing on branch |
| F-3: Capabilities fallback LLM on CPU minimal | ✅ Fixed | `c60aaa72` |
| F-5: GPU layers footgun | ✅ Fixed (.env.example + preflight) | `2d15a394` |
| F-8: Healthcheck 3-hour window | ✅ Fixed (30 retries) | `1e3fa154` |
| F-9: Preflight --local-server asterisk_media | ✅ Fixed (skip + grep env) | `a25df4ef` |
| F-10: No model compatibility matrix | ✅ Community test matrix published | `d83faef2` |
| F-12: Dead `_verify_model_loaded()` | ✅ Removed | `c60aaa72` |
| F-13: `_read_env_values()` quote handling | ✅ Fixed | `c60aaa72` |
| F-14: EXPOSE 8765 in Dockerfiles | ✅ Added | `1e3fa154` |
| F-1: Split-host setup guide | 🔲 Remaining (docs only) | — |
| F-4: Split-host container rebuild | 🔲 Remaining (needs Admin UI work) | — |
| F-6: `LOCAL_ONLY_SETUP.md` outdated | 🔲 Remaining | — |
| F-7: Split-host detection in UI | 🔲 Remaining (needs frontend work) | — |
| F-11: Pin nvidia/cuda digest | 🔲 Remaining (low priority) | — |

**Related docs updated**: `archived/GPU-LEARNINGS.md` (sections 16-19), `docs/contributing/milestones/milestone-26-local-ai-server-improvements.md` (audit-driven hardening table), `docs/COMMUNITY_TEST_MATRIX.md` (new), `.github/ISSUE_TEMPLATE/local-ai-test-result.md` (new).

---

## Branch Intent Summary

The `local-ai-server-improvements` branch (Milestone 26) targets three reliability gaps exposed during GPU cloud testing:

1. **Whisper STT self-echo**: ExternalMedia transport re-enters capture too early when using Whisper backends, causing continuous self-talk.
2. **LLM prompt mismatch**: AI engine's system prompt wasn't consistently applied to `local_ai_server`, producing irrelevant responses.
3. **LLM context overflow**: Large system prompts exceed default `LOCAL_LLM_CONTEXT` (768), crashing llama.cpp.

Key changes include: segment gating re-arm conditioned on Whisper backend detection, system prompt sync via SHA-256 dedup, LLM context auto-tuning on GPU (default 2048), prompt-fit guard rails, and Admin UI enhancements for LLM tuning.

---

## A) Executive Summary

### Top 10 Issues by Impact

| # | Issue | Severity | Area |
|---|-------|----------|------|
| 1 | **Split-host model management broken** — Admin UI scans local `models/` but Local AI Server is remote; switch/delete/list endpoints fail silently | Critical | Networking/UI |
| 2 | **No auth enforcement when LOCAL_WS_HOST=0.0.0.0** — user can expose Local AI Server to network without authentication | High | Security |
| 3 | **Capabilities fallback claims LLM available on CPU minimal mode** — leads users to attempt LLM operations that fail | High | Config/UI |
| 4 | **Split-host container rebuild impossible** — Admin UI's docker socket can't reach remote local_ai_server; "Rebuild" button fails with confusing error | High | Networking/UI |
| 5 | **`LOCAL_LLM_GPU_LAYERS=0` uncommented in .env.example** — GPU users who run preflight but don't change this footgun still run CPU inference | Medium | Config |
| 6 | **`docs/LOCAL_ONLY_SETUP.md` outdated** — references AudioSocket as default, no mention of runtime_mode/GPU/CPU fallback | Medium | Docs |
| 7 | **No split-host setup guide** — community's most-requested deployment pattern has zero documentation | Medium | Docs |
| 8 | **Healthcheck 3-hour unhealthy window** — `retries: 180 × interval: 60s` confuses users expecting quick feedback | Low | Docker |
| 9 | **`--local-server` preflight still creates asterisk_media/** — irrelevant for standalone GPU server | Low | Preflight |
| 10 | **No model compatibility matrix** — users don't know which backends need GPU, which build args, or disk requirements | Medium | Docs |

### Top 10 Quick Wins

| # | Quick Win | Effort | Impact |
|---|-----------|--------|--------|
| 1 | Add preflight warning when `LOCAL_WS_HOST != 127.0.0.1` and `LOCAL_WS_AUTH_TOKEN` is empty | 1 line | High (security) |
| 2 | Fix capabilities fallback: return `llm.available=false` when `runtime_mode=minimal` | 3 lines | High |
| 3 | Comment out `LOCAL_LLM_GPU_LAYERS=0` in `.env.example`, add note "uncomment and set -1 for GPU" | 1 line | Medium |
| 4 | Skip `asterisk_media/` setup in `--local-server` preflight mode | 2-line guard | Low |
| 5 | Add `EXPOSE 8765` to both Dockerfiles (informational) | 1 line each | Low |
| 6 | Reduce healthcheck `retries` from 180 to 30, add comment explaining large model loads | 1 line | Low |
| 7 | Remove dead `_verify_model_loaded()` function (unused by switch flow) | Delete ~35 lines | Low (cleanup) |
| 8 | Add split-host detection warning in Admin UI when `HEALTH_CHECK_LOCAL_AI_URL` points to non-localhost | UI tooltip | Medium |
| 9 | Pin `nvidia/cuda` image digest in `Dockerfile.gpu` | 1 line | Low (supply chain) |
| 10 | Fix `_read_env_values()` to handle quoted values (`VAR="value"`) | 5 lines | Low |

---

## B) Findings Table

### F-1: No Split-Host Setup Guide

| Field | Value |
|-------|-------|
| **Area** | Documentation |
| **Severity** | Medium |
| **Symptom** | Community users attempting GPU-on-separate-machine have no documentation path |
| **Root Cause** | `docs/LOCAL_ONLY_SETUP.md` only covers single-host; no dedicated guide for split deployment |
| **Reproduction** | Search docs/ for "split" or "remote local ai" — zero results |
| **Proposed Fix** | Create `docs/SPLIT_HOST_SETUP.md` with architecture diagram, required env vars, firewall ports, example configs |
| **Files** | `docs/SPLIT_HOST_SETUP.md` (new) |
| **Validation** | Follow guide on two separate machines; verify call completes end-to-end |

### F-2: Split-Host Model Management Broken

| Field | Value |
|-------|-------|
| **Area** | Admin UI / Networking |
| **Severity** | Critical |
| **Symptom** | In split-host mode, "Installed Models" shows empty list; "Switch Model" and "Delete Model" fail |
| **Root Cause** | `list_available_models()` scans `PROJECT_ROOT/models/` on admin_ui's filesystem. In split-host, admin_ui and local_ai_server don't share a `models/` volume. `delete_model()` maps `/app/models/` to local filesystem. |
| **Reproduction** | Run admin_ui on Machine A, local_ai_server on Machine B. Open Models page → "Installed" tab is empty despite models loaded on B. |
| **Proposed Fix** | For split-host: proxy model listing through the local_ai_server WS `status` response (which already reports loaded models). Add a `remote_models` flag to detect split-host and skip local filesystem operations. For delete: disable delete button when remote, show tooltip "Delete models directly on the GPU server". |
| **Files** | `admin_ui/backend/api/local_ai.py` (list_available_models, delete_model), `admin_ui/frontend/src/pages/System/ModelsPage.tsx` |
| **Validation** | Split-host setup: Models page shows remotely-loaded models; switch works; delete shows appropriate message |

### F-3: No Auth Enforcement for Non-Loopback Bind

| Field | Value |
|-------|-------|
| **Area** | Security |
| **Severity** | High |
| **Symptom** | User sets `LOCAL_WS_HOST=0.0.0.0` without `LOCAL_WS_AUTH_TOKEN`; Local AI Server is exposed without authentication |
| **Root Cause** | Neither `preflight.sh` nor `local_ai_server/config.py` validate that auth is configured when binding non-loopback |
| **Reproduction** | Set `LOCAL_WS_HOST=0.0.0.0`, leave `LOCAL_WS_AUTH_TOKEN` empty. Start local_ai_server. Connect from remote machine without token — succeeds. |
| **Proposed Fix** | 1) `preflight.sh`: warn when `LOCAL_WS_HOST != 127.0.0.1` and token is empty. 2) `local_ai_server/config.py`: log a SECURITY WARNING at startup. 3) Optionally: refuse to start without token when non-loopback (breaking but safe). |
| **Files** | `preflight.sh`, `local_ai_server/config.py`, `local_ai_server/server.py` |
| **Validation** | Start with `0.0.0.0` + no token → see clear warning in logs and preflight output |

### F-4: Capabilities Fallback Claims LLM Available on CPU Minimal

| Field | Value |
|-------|-------|
| **Area** | Admin UI Backend |
| **Severity** | High |
| **Symptom** | On CPU-only minimal mode, capabilities endpoint returns `llm.available=true`, leading users to attempt LLM config |
| **Root Cause** | `get_backend_capabilities()` exception handler (line 647-652) unconditionally sets `capabilities["llm"] = {"available": True}`. When local_ai_server is in `minimal` mode, LLM is not preloaded. |
| **Reproduction** | Start local_ai_server on CPU (no GPU). Query `/api/local-ai/capabilities`. LLM shows "available: true" even though `runtime_mode=minimal` and no LLM is loaded. |
| **Proposed Fix** | Check `runtime_mode` from status response; if `minimal`, set `llm.available=false` with reason "CPU minimal mode — LLM not loaded. Set LOCAL_AI_MODE=full or add GPU." |
| **Files** | `admin_ui/backend/api/local_ai.py` (`get_backend_capabilities`) |
| **Validation** | CPU minimal mode → capabilities returns `llm.available=false` with actionable message |

### F-5: GPU_LAYERS=0 Footgun in .env.example

| Field | Value |
|-------|-------|
| **Area** | Configuration |
| **Severity** | Medium |
| **Symptom** | User runs `preflight.sh` which sets `GPU_AVAILABLE=true`, but `LOCAL_LLM_GPU_LAYERS=0` is active in .env — LLM still runs on CPU |
| **Root Cause** | `.env.example` has `LOCAL_LLM_GPU_LAYERS=0` uncommented as an active default |
| **Reproduction** | Copy `.env.example` to `.env`. Run preflight (GPU detected). Start local_ai_server with GPU compose. Observe LLM uses 0 GPU layers. |
| **Proposed Fix** | Comment out `LOCAL_LLM_GPU_LAYERS=0` in `.env.example`. Add preflight check: when `GPU_AVAILABLE=true` and `LOCAL_LLM_GPU_LAYERS=0`, suggest setting to `-1`. |
| **Files** | `.env.example`, `preflight.sh` |
| **Validation** | Fresh install with GPU → preflight suggests GPU layers; .env.example doesn't silently force CPU |

### F-6: Split-Host Container Rebuild Impossible via UI

| Field | Value |
|-------|-------|
| **Area** | Admin UI |
| **Severity** | High |
| **Symptom** | "Rebuild Local AI Server" button in Admin UI fails when local_ai_server is on a remote machine |
| **Root Cause** | `_recreate_via_compose("local_ai_server")` uses the local Docker socket. In split-host, the remote container isn't controllable via the local socket. |
| **Reproduction** | Split-host setup. Click "Rebuild" in Admin UI → error (container not found or compose fails). |
| **Proposed Fix** | Detect split-host mode (e.g., `HEALTH_CHECK_LOCAL_AI_URL` points to non-localhost). Disable rebuild button; show tooltip "Local AI Server is remote — rebuild on the GPU server directly". Provide the compose command to copy. |
| **Files** | `admin_ui/frontend/src/pages/System/ModelsPage.tsx`, `admin_ui/backend/api/local_ai.py` |
| **Validation** | Split-host: rebuild button disabled with helpful message; single-host: button works normally |

### F-7: `--local-server` Preflight Creates Irrelevant Directories

| Field | Value |
|-------|-------|
| **Area** | Preflight |
| **Severity** | Low |
| **Symptom** | Running `preflight.sh --local-server` on a standalone GPU server creates `asterisk_media/` directory |
| **Root Cause** | `check_directories()` runs unconditionally before the `LOCAL_SERVER_ONLY` branch. It creates `asterisk_media/ai-generated`, `data/`, and `models/`. Only `data/` and `models/` are relevant for local_ai_server. |
| **Reproduction** | Run `./preflight.sh --local-server` on a fresh GPU server. See `asterisk_media/` created. |
| **Proposed Fix** | In `check_directories()`, skip `asterisk_media/` creation when `LOCAL_SERVER_ONLY=true`. Keep `data/` and `models/` creation. |
| **Files** | `preflight.sh` (`check_directories`) |
| **Validation** | `--local-server` mode: only `data/` and `models/` created; no `asterisk_media/` |

### F-8: Healthcheck Window Too Long

| Field | Value |
|-------|-------|
| **Area** | Docker |
| **Severity** | Low |
| **Symptom** | `docker ps` shows `(health: starting)` for up to 3 hours; users think container is broken |
| **Root Cause** | `retries: 180` × `interval: 60s` = 180 minutes before marking unhealthy |
| **Reproduction** | Start local_ai_server with a large model. Run `docker ps` — shows `(health: starting)` for extended period. |
| **Proposed Fix** | Reduce `retries` to 30 (30 min window after start_period). Add comment: "Large models may take 5-10 min to load; increase retries if needed." |
| **Files** | `docker-compose.yml` |
| **Validation** | Normal model load: healthy within 5 min. Failed load: unhealthy after ~32 min, not 3 hours. |

### F-9: Dead Code — `_verify_model_loaded()`

| Field | Value |
|-------|-------|
| **Area** | Code Quality |
| **Severity** | Low |
| **Symptom** | Confusing dead code that tries `ws://local_ai_server:8765` (won't work in host networking) |
| **Root Cause** | `_verify_model_loaded()` (lines 1102-1137) appears to be an older implementation superseded by `_wait_for_status()`. It's not called by the main switch flow. |
| **Reproduction** | Grep for `_verify_model_loaded` — no callers in the codebase. |
| **Proposed Fix** | Remove the function. |
| **Files** | `admin_ui/backend/api/local_ai.py` |
| **Validation** | All switch tests still pass; no references to removed function |

### F-10: `_read_env_values()` Doesn't Handle Quoted Values

| Field | Value |
|-------|-------|
| **Area** | Admin UI Backend |
| **Severity** | Low |
| **Symptom** | If `.env` contains `VAR="value"` or `VAR='value'`, the read function returns the quotes as part of the value |
| **Root Cause** | Line 1151: `value = line.split('=', 1)[1].strip()` — no quote stripping |
| **Reproduction** | Set `LOCAL_WS_AUTH_TOKEN="my-token"` in .env. Read via `_read_env_values()` — returns `"my-token"` with quotes. |
| **Proposed Fix** | Strip surrounding quotes: `value = value.strip().strip('"').strip("'")` |
| **Files** | `admin_ui/backend/api/local_ai.py` |
| **Validation** | Unit test: `_read_env_values` with quoted values returns unquoted |

### F-11: `docs/LOCAL_ONLY_SETUP.md` Outdated

| Field | Value |
|-------|-------|
| **Area** | Documentation |
| **Severity** | Medium |
| **Symptom** | Guide references `audio_transport: audiosocket` as default; no mention of runtime_mode, GPU, CPU fallback |
| **Root Cause** | Not updated since ExternalMedia became default and runtime_mode was added |
| **Reproduction** | Read the guide — follows AudioSocket path, no GPU instructions |
| **Proposed Fix** | Rewrite to cover: ExternalMedia as default transport, runtime_mode (full/minimal), CPU fallback (Vosk+Piper), GPU setup with docker-compose.gpu.yml, model download steps |
| **Files** | `docs/LOCAL_ONLY_SETUP.md` |
| **Validation** | Follow updated guide from scratch → working local deployment |

### F-12: No Model Compatibility Matrix

| Field | Value |
|-------|-------|
| **Area** | Documentation |
| **Severity** | Medium |
| **Symptom** | Users don't know which backends need GPU, which build args, or disk space requirements |
| **Root Cause** | Information scattered across .env.example comments, Dockerfiles, and Admin UI tooltips |
| **Reproduction** | Try to determine "Can I run Faster-Whisper on CPU?" — no single source answers this |
| **Proposed Fix** | Create a compatibility matrix table in docs showing: backend, CPU/GPU support, build arg, disk size, quality notes |
| **Files** | `docs/LOCAL_ONLY_SETUP.md` or new `docs/LOCAL_AI_COMPATIBILITY.md` |
| **Validation** | Matrix covers all 5 STT + 3 TTS + LLM backends with accurate info |

### F-13: `check_ports_local_server()` Sources .env Unsafely

| Field | Value |
|-------|-------|
| **Area** | Preflight / Security |
| **Severity** | Low |
| **Symptom** | `source "$SCRIPT_DIR/.env"` can execute arbitrary code if .env contains shell commands |
| **Root Cause** | Line 2350-2351 in preflight.sh: direct `source` of .env file |
| **Reproduction** | Add `$(touch /tmp/pwned)` to .env. Run preflight. `/tmp/pwned` is created. |
| **Proposed Fix** | Use grep-based extraction like other check functions: `port="$(grep -E '^LOCAL_WS_PORT=' "$SCRIPT_DIR/.env" \| cut -d= -f2 \| tr -d '[:space:]')"` |
| **Files** | `preflight.sh` |
| **Validation** | Preflight correctly reads LOCAL_WS_PORT without sourcing entire .env |

### F-14: No TLS for WS Connection in Split-Host

| Field | Value |
|-------|-------|
| **Area** | Security / Networking |
| **Severity** | Medium (for split-host over untrusted network) |
| **Symptom** | Audio and model data transmitted in plaintext between machines |
| **Root Cause** | `local_ai_server/server.py` only supports `ws://`, not `wss://`. No TLS termination documented. |
| **Reproduction** | Split-host setup over public network. Packet capture shows plaintext audio/text. |
| **Proposed Fix** | Phase 1: Document reverse proxy (nginx/caddy) for TLS termination in split-host guide. Phase 2 (future): Native wss:// support in server.py. |
| **Files** | `docs/SPLIT_HOST_SETUP.md` (new), future: `local_ai_server/server.py` |
| **Validation** | Guide includes TLS proxy example; connection works through proxy |

---

## C) Golden Path Setup Guides

### C1: GPU Server Separate from Asterisk/AI Engine (Split-Host)

```
┌─────────────────────────┐         ┌─────────────────────────┐
│   Machine A (Asterisk)  │         │   Machine B (GPU)       │
│                         │         │                         │
│  ┌───────────────────┐  │   WS    │  ┌───────────────────┐  │
│  │    AI Engine       │──────────────│  Local AI Server   │  │
│  │  (ai_engine)       │  │  :8765  │  │ (local_ai_server)  │  │
│  └───────────────────┘  │         │  └───────────────────┘  │
│  ┌───────────────────┐  │         │                         │
│  │    Admin UI        │  │         │  GPU: NVIDIA RTX/Tesla  │
│  │  (admin_ui:3003)   │  │         │  Models: /app/models/   │
│  └───────────────────┘  │         │                         │
│  ┌───────────────────┐  │         └─────────────────────────┘
│  │    Asterisk        │  │
│  │  (ARI + RTP)       │  │
│  └───────────────────┘  │
└─────────────────────────┘
```

**Required Ports**:
- Machine A → B: TCP 8765 (Local AI WS)
- Machine A: TCP 8088 (ARI), UDP 18080-18099 (RTP), TCP 3003 (Admin UI)

**Machine B (GPU Server) Setup**:
```bash
# 1. Clone repo and enter directory
git clone https://github.com/hkjarral/Asterisk-AI-Voice-Agent.git
cd Asterisk-AI-Voice-Agent

# 2. Run preflight for Local AI Server only
sudo ./preflight.sh --local-server --apply-fixes

# 3. Configure .env on GPU server
# Key settings:
LOCAL_WS_HOST=0.0.0.0              # Bind to all interfaces (required for remote access)
LOCAL_WS_AUTH_TOKEN=<generate-with-openssl-rand-hex-32>  # REQUIRED for security
LOCAL_WS_PORT=8765
GPU_AVAILABLE=true                  # Auto-set by preflight
LOCAL_LLM_GPU_LAYERS=-1            # Use GPU for LLM
# LOCAL_AI_MODE=full               # Default when GPU detected

# 4. Build and start with GPU support
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build local_ai_server

# 5. Verify
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f local_ai_server
# Look for: "WebSocket server started on ws://0.0.0.0:8765"
```

**Machine A (Asterisk/AI Engine) Setup**:
```bash
# In .env on Machine A:
LOCAL_WS_URL=ws://<gpu-server-ip>:8765
LOCAL_WS_AUTH_TOKEN=<same-token-as-gpu-server>
HEALTH_CHECK_LOCAL_AI_URL=ws://<gpu-server-ip>:8765

# In config/ai-agent.yaml:
providers:
  local:
    type: full
    enabled: true
    capabilities: [stt, llm, tts]
    base_url: ws://<gpu-server-ip>:8765
    auth_token: ${LOCAL_WS_AUTH_TOKEN}
```

**Common Pitfalls**:
- Firewall: Ensure port 8765 is open between machines
- Auth token must match on both sides
- `HEALTH_CHECK_LOCAL_AI_URL` must be set on Machine A for Admin UI status checks
- Model management (download/delete) must be done directly on Machine B
- "Rebuild" button in Admin UI won't work for remote server — rebuild on Machine B directly
- No TLS by default — use VPN or reverse proxy for production over untrusted networks

### C2: CPU-Only Local AI Server (Vosk + Piper Default)

```
┌─────────────────────────────────┐
│   Single Machine (CPU only)     │
│                                 │
│  ┌───────────────────┐          │
│  │    Asterisk         │         │
│  └────────┬──────────┘          │
│           │ ARI                  │
│  ┌────────▼──────────┐          │
│  │    AI Engine        │         │
│  │  (host network)     │         │
│  └────────┬──────────┘          │
│           │ WS :8765             │
│  ┌────────▼──────────┐          │
│  │  Local AI Server    │         │
│  │  STT: Vosk          │         │
│  │  TTS: Piper          │        │
│  │  LLM: SKIPPED        │        │
│  │  (runtime=minimal)    │       │
│  └───────────────────┘          │
│                                 │
│  ┌───────────────────┐          │
│  │    Admin UI :3003   │         │
│  └───────────────────┘          │
└─────────────────────────────────┘
```

**Required Ports**: TCP 8088 (ARI), UDP 18080-18099 (RTP), TCP 3003 (Admin UI), TCP 8765 (loopback only)

**Setup**:
```bash
# 1. Preflight
sudo ./preflight.sh --apply-fixes

# 2. Key .env settings (auto-configured by preflight on CPU):
# GPU_AVAILABLE=false           → runtime_mode defaults to "minimal"
# LOCAL_STT_BACKEND=vosk        → CPU-friendly STT
# LOCAL_TTS_BACKEND=piper       → CPU-friendly TTS
# LOCAL_LLM_GPU_LAYERS=0        → no GPU (LLM skipped in minimal mode anyway)

# 3. Start services
docker compose up -d admin_ui
# Complete Setup Wizard at http://localhost:3003
# Choose "local_hybrid" pipeline (local STT/TTS, cloud LLM like GPT-4o)
# OR "local_only" pipeline (but LLM won't load on CPU minimal mode)

docker compose up -d ai_engine local_ai_server

# 4. Verify
docker compose logs local_ai_server | grep "runtime_mode"
# Should show: runtime_mode=minimal (skips LLM preload)
```

**Example docker-compose override** (none needed — defaults work):
```yaml
# docker-compose.yml defaults are correct for CPU:
# INCLUDE_VOSK=true, INCLUDE_PIPER=true, INCLUDE_KOKORO=true, INCLUDE_LLAMA=true
# LLM binary is included but not preloaded in minimal mode
```

**Common Pitfalls**:
- Don't set `LOCAL_AI_MODE=full` on CPU — LLM inference will be extremely slow
- `local_only` pipeline requires LLM; use `local_hybrid` (local STT/TTS + cloud LLM) on CPU
- Vosk requires downloading a model first (via Admin UI Models page or Setup Wizard)
- Piper requires downloading a voice model (.onnx + .onnx.json)
- If you want LLM on CPU anyway: `LOCAL_AI_MODE=full` + expect 10-30s per response

### C3: Single-Host All-in-One (GPU)

```
┌───────────────────────────────────┐
│   Single Machine (with GPU)       │
│                                   │
│  ┌───────────────────┐            │
│  │    Asterisk          │          │
│  └────────┬──────────┘            │
│           │ ARI                    │
│  ┌────────▼──────────┐            │
│  │    AI Engine         │          │
│  │  (host network)      │          │
│  └────────┬──────────┘            │
│           │ WS :8765 (loopback)    │
│  ┌────────▼──────────┐            │
│  │  Local AI Server     │          │
│  │  STT: Vosk/Whisper    │         │
│  │  TTS: Piper/Kokoro    │         │
│  │  LLM: Phi-3 (GPU)     │        │
│  │  runtime=full          │        │
│  └───────────────────┘            │
│                                   │
│  ┌───────────────────┐            │
│  │    Admin UI :3003    │          │
│  └───────────────────┘            │
│                                   │
│  GPU: NVIDIA (passthrough)         │
└───────────────────────────────────┘
```

**Required Ports**: TCP 8088 (ARI), UDP 18080-18099 (RTP), TCP 3003 (Admin UI)

**Setup**:
```bash
# 1. Preflight (detects GPU, installs nvidia-container-toolkit if needed)
sudo ./preflight.sh --apply-fixes

# 2. Verify GPU_AVAILABLE=true in .env (auto-set by preflight)
grep GPU_AVAILABLE .env

# 3. Set GPU layers (NOT auto-set — you must do this):
# Edit .env:
LOCAL_LLM_GPU_LAYERS=-1    # Auto-use all GPU layers

# 4. Build with GPU Dockerfile and start
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build local_ai_server
docker compose up -d admin_ui ai_engine

# 5. Complete Setup Wizard → choose "local_only" pipeline

# 6. Download models via Admin UI → Models page
#    - STT: Vosk en-US 0.22 (or Faster-Whisper for higher accuracy)
#    - TTS: Piper en_US-lessac-medium (or Kokoro)
#    - LLM: Phi-3 Mini Q4_K_M

# 7. Verify
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs local_ai_server | tail -20
# Look for: "GPU detected", "llm_context=2048", "runtime_mode=full"
```

**Example docker-compose.gpu.yml override** (already provided in repo):
```yaml
# GPU compose includes by default:
# INCLUDE_FASTER_WHISPER=true, INCLUDE_WHISPER_CPP=true (GPU benefits)
# INCLUDE_VOSK=true, INCLUDE_SHERPA=true, INCLUDE_PIPER=true, INCLUDE_KOKORO=true
# INCLUDE_LLAMA=true (built with CUDA support)
```

**Common Pitfalls**:
- Must use `-f docker-compose.gpu.yml` overlay for GPU — base compose builds CPU-only llama.cpp
- `LOCAL_LLM_GPU_LAYERS` must be set to `-1` (or a specific layer count) — it's `0` by default
- nvidia-container-toolkit must be configured: `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`
- Auto-context tuning: first boot may try multiple n_ctx values — this is normal, results are cached
- Large models (7B+) may need 16GB+ VRAM; Phi-3 Mini Q4 needs ~3GB

---

## D) Test Matrix

### Backend × Hardware Matrix

| Backend | Type | CPU | GPU | Build Arg | Disk Size | Notes |
|---------|------|-----|-----|-----------|-----------|-------|
| **Vosk** | STT | ✅ Good | ✅ (no benefit) | `INCLUDE_VOSK=true` (default) | 50-200 MB | Best CPU STT; streaming |
| **Sherpa-ONNX** | STT | ✅ Good | ✅ (no benefit) | `INCLUDE_SHERPA=true` (default) | 30-150 MB | Streaming; multi-language |
| **Kroko Cloud** | STT | ✅ | ✅ | N/A | 0 | Requires API key |
| **Kroko Embedded** | STT | ✅ | ✅ | `INCLUDE_KROKO_EMBEDDED=true` | ~100 MB | Needs ONNX runtime + model |
| **Faster-Whisper** | STT | ⚠️ Slow | ✅ Best | `INCLUDE_FASTER_WHISPER=true` | 75-3000 MB | Auto-downloads from HF; CUDA strongly recommended |
| **Whisper.cpp** | STT | ⚠️ Slow | ✅ Good | `INCLUDE_WHISPER_CPP=true` | 75-3000 MB | Manual model download |
| **Piper** | TTS | ✅ Good | ✅ (no benefit) | `INCLUDE_PIPER=true` (default) | 15-60 MB | Best CPU TTS; ONNX voices |
| **Kokoro** | TTS | ✅ OK | ✅ Better | `INCLUDE_KOKORO=true` (default) | ~200 MB | Higher quality; spaCy dependency |
| **MeloTTS** | TTS | ✅ OK | ✅ Better | `INCLUDE_MELOTTS=true` | ~500 MB | Multi-accent; larger image |
| **llama.cpp (LLM)** | LLM | ❌ Not recommended | ✅ Required | `INCLUDE_LLAMA=true` (default) | 2-8 GB | CPU: 10-30s/response; GPU: <1s |

### Deployment × Pipeline Matrix

| Deployment | Pipeline | STT | LLM | TTS | Expected Outcome |
|------------|----------|-----|-----|-----|------------------|
| **CPU single-host** | `local_hybrid` | Vosk (local) | GPT-4o (cloud) | Piper (local) | ✅ Recommended for CPU |
| **CPU single-host** | `local_only` | Vosk (local) | Phi-3 (local) | Piper (local) | ⚠️ LLM very slow on CPU |
| **GPU single-host** | `local_only` | Vosk/Whisper | Phi-3 (GPU) | Piper/Kokoro | ✅ Best fully-local |
| **GPU single-host** | `local_hybrid` | Whisper (GPU) | GPT-4o (cloud) | Kokoro (local) | ✅ Best hybrid |
| **GPU split-host** | `local_only` | Vosk/Whisper | Phi-3 (GPU) | Piper/Kokoro | ✅ With auth + firewall |
| **GPU split-host** | `local_hybrid` | Whisper (GPU) | GPT-4o (cloud) | Kokoro (local) | ✅ With auth + firewall |

### Regression Test Checklist

| # | Test | Expected | Status |
|---|------|----------|--------|
| 1 | CPU start, LOCAL_AI_MODE unset → runtime_mode=minimal | LLM skipped, STT+TTS load | Verify |
| 2 | GPU start, LOCAL_AI_MODE unset → runtime_mode=full | All backends load | Verify |
| 3 | GPU start, LOCAL_LLM_CONTEXT unset → default 2048 | Status shows context=2048 | Verify |
| 4 | CPU start, LOCAL_LLM_CONTEXT unset → default 768 | Status shows context=768 | Verify |
| 5 | Switch STT vosk→sherpa via Admin UI | Hot-switch succeeds, no restart | Verify |
| 6 | Switch STT vosk→faster_whisper (no build arg) | Capability-aware error shown | Verify |
| 7 | Switch TTS piper→kokoro via Admin UI | Hot-switch succeeds | Verify |
| 8 | Switch LLM model via Admin UI | Restart + verify loaded | Verify |
| 9 | Whisper STT + ExternalMedia → no self-echo | Segment gating re-armed for Whisper only | Verify |
| 10 | Large system prompt > n_ctx → truncated gracefully | No crash, warning logged | Verify |
| 11 | Split-host: AI engine connects to remote local_ai_server | Call completes end-to-end | Verify |
| 12 | Split-host: Admin UI shows remote server status | Status endpoint returns connected | Verify |
| 13 | Auth token mismatch → clear error | WS auth rejected, logged | Verify |
| 14 | Non-loopback bind + no auth → warning | Preflight and startup warn | Not yet |

---

## E) Concrete PR Plan

### PR 1: Security — Auth Enforcement for Non-Loopback Bind
**Goal**: Prevent unauthenticated exposure of Local AI Server
**Files**:
- `preflight.sh` — add check when `LOCAL_WS_HOST != 127.0.0.1` and token empty
- `local_ai_server/config.py` — log SECURITY WARNING at startup
- `local_ai_server/server.py` — optional: refuse start without token on non-loopback
**Risk**: Low (additive warnings, no behavior change for default config)
**Test**: Preflight with non-loopback + no token → warning. Start server → warning in logs.

### PR 2: Fix Capabilities Fallback + LLM Minimal Mode
**Goal**: Don't claim LLM available when it's not loaded
**Files**:
- `admin_ui/backend/api/local_ai.py` — check runtime_mode in capabilities fallback
- `admin_ui/backend/api/local_ai.py` — strip quotes in `_read_env_values()`
- `admin_ui/backend/api/local_ai.py` — remove dead `_verify_model_loaded()` function
**Risk**: Low (fixes incorrect status reporting)
**Test**: CPU minimal → capabilities returns `llm.available=false`

### PR 3: GPU Layers Footgun Fix
**Goal**: Prevent silent CPU-only LLM on GPU systems
**Files**:
- `.env.example` — comment out `LOCAL_LLM_GPU_LAYERS=0`, add guidance comment
- `preflight.sh` — suggest `-1` when GPU detected and layers=0
**Risk**: Low (does not change defaults for existing .env files)
**Test**: Fresh install with GPU → preflight output includes GPU layers suggestion

### PR 4: Split-Host Awareness in Admin UI
**Goal**: Graceful degradation when Local AI Server is remote
**Files**:
- `admin_ui/backend/api/local_ai.py` — detect remote server, disable delete, proxy model list
- `admin_ui/frontend/src/pages/System/ModelsPage.tsx` — disable rebuild button for remote, show tooltip
**Risk**: Medium (UI behavior change for split-host users)
**Test**: Split-host → Models page shows remote models; rebuild disabled with message; switch still works

### PR 5: Preflight Hardening for --local-server
**Goal**: Clean up irrelevant checks in local-server-only mode
**Files**:
- `preflight.sh` — skip asterisk_media in `--local-server` mode
- `preflight.sh` — fix `check_ports_local_server()` to not source .env directly
- `preflight.sh` — reduce healthcheck retries from 180 to 30
**Risk**: Low
**Test**: `--local-server` mode: no asterisk_media created; port check works; env not sourced

### PR 6: Documentation — Setup Guides + Compatibility Matrix
**Goal**: Close the documentation gap for all three deployment patterns
**Files**:
- `docs/LOCAL_ONLY_SETUP.md` — full rewrite with current defaults
- `docs/SPLIT_HOST_SETUP.md` — new guide (from Golden Path C1)
- Add compatibility matrix to `docs/LOCAL_ONLY_SETUP.md`
**Risk**: None (docs only)
**Test**: Follow each guide from scratch → working deployment

### PR 7: Docker Improvements
**Goal**: Better defaults and supply chain hygiene
**Files**:
- `docker-compose.yml` — reduce healthcheck retries, add `EXPOSE 8765` to Dockerfiles
- `local_ai_server/Dockerfile` — add `EXPOSE 8765`
- `local_ai_server/Dockerfile.gpu` — add `EXPOSE 8765`, pin CUDA image digest
**Risk**: Low
**Test**: Build succeeds; healthcheck transitions appropriately

### Recommended PR Merge Order
1. **PR 1** (Security) — highest priority, independent
2. **PR 2** (Capabilities fix) — high impact, small change
3. **PR 3** (GPU footgun) — medium impact, trivial
4. **PR 5** (Preflight) — low risk, cleanup
5. **PR 7** (Docker) — low risk, cleanup
6. **PR 6** (Docs) — no code risk, can be reviewed in parallel
7. **PR 4** (Split-host UI) — most complex, benefits from earlier fixes

---

## Appendix: Files Audited

| File | Lines | Key Observations |
|------|-------|------------------|
| `local_ai_server/server.py` | 1099 | Core WS server, model orchestration, auto-context tuning |
| `local_ai_server/config.py` | 188 | `LocalAIConfig` dataclass, env-based config, runtime_mode logic |
| `local_ai_server/status_builder.py` | 178 | Status response builder, GPU status, prompt fit |
| `local_ai_server/Dockerfile.gpu` | 162 | CUDA 12.4.1 multi-stage build |
| `preflight.sh` | 2617 | Full preflight with --local-server, GPU detection, directory setup |
| `install.sh` | ~1800 | Install wizard, secrets dir setup, YAML update fix |
| `docker-compose.yml` | 180 | All three services, healthcheck, volume mounts |
| `docker-compose.gpu.yml` | 61 | GPU overlay, Dockerfile.gpu build, device reservation |
| `admin_ui/backend/api/local_ai.py` | 1391 | Model CRUD, switch with rollback, capabilities, status |
| `admin_ui/frontend/src/pages/System/ModelsPage.tsx` | 1323 | Model UI, active models, capabilities display |
| `src/providers/local.py` | ~964 | LocalProvider WS client, prompt sync, audio timing |
| `src/engine.py` | ~8100+ | Segment gating re-arm for Whisper backend |
| `.env.example` | 521 | All config vars documented |
| `docs/LOCAL_ONLY_SETUP.md` | 256 | Outdated local setup guide |
| `docs/contributing/milestones/milestone-26-local-ai-server-improvements.md` | 83 | Milestone spec |
