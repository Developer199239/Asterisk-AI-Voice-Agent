# GPU + Vast.ai learnings (Asterisk AI Voice Agent)

Date: 2026-02-20 to 2026-02-21  
GPU tested: 1× RTX 4090 (24 GB VRAM) on Vast.ai

## 1) Vast.ai instance types: Container/Jupyter vs VM

### Container/Jupyter template (what it’s good for)
- Great for quick **GPU benchmarking** and running a single process (e.g., `python main.py` for `local_ai_server`).
- You typically **do not** get a full init system (`systemd`) and **cannot rely on a Docker daemon** being present/running.
- Result: our repo `./preflight.sh` fails with **“Docker daemon not running”** on container-style instances by design.

### VM template (what it’s good for)
- Required if you want the full “GA” stack with **Docker Compose** (admin UI, ai engine, local ai server, etc.).
- You get `systemd` and can run `docker` as a service.

## 2) Docker GPU passthrough on the VM

### Symptom
- Compose up of GPU services fails with:
  - `could not select device driver "nvidia" with capabilities: [[gpu]]`
- `./preflight.sh` shows:
  - GPU detected + toolkit installed
  - but Docker GPU passthrough test fails

### Fix (host VM)
1) Install NVIDIA container tooling (if missing):
   - `apt-get update && apt-get install -y nvidia-container-toolkit nvidia-container-runtime`
2) Configure Docker to use the NVIDIA runtime:
   - `nvidia-ctk runtime configure --runtime=docker`
3) Restart Docker:
   - `systemctl restart docker`

### Verify
- `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`
- If that works, the Compose GPU services should start.

## 3) local_ai_server: no-API-key “embedded” stack realities

### LLM (Phi-3 mini GGUF)
- Works well on 4090 with `llama-cpp-python` CUDA build.
- Key env:
  - `LOCAL_LLM_GPU_LAYERS=-1` (or a positive layer count)

### STT
- “Kroko embedded” in this repo **is not turnkey** unless the image includes the expected kroko server/binary + model assets.
- **Sherpa-onnx** works fully offline once models are present:
  - `LOCAL_STT_BACKEND=sherpa`
  - `SHERPA_MODEL_PATH=.../sherpa-onnx-streaming-zipformer-en-2023-06-26`

### TTS
- **Kokoro (HF mode)** downloads from HuggingFace by default (no API key required), but inside the GPU Docker image we hit a hard failure.
- Observed failure in container:
  - `ImportError: ... libc10_cuda.so: undefined symbol cudaGetDriverEntryPointByVersion, version libcudart.so.12`
- Interpretation:
  - torch / CUDA runtime **collision**: importing `llama_cpp` first can load an older `libcudart.so.12`, and later `torch` import (Kokoro) fails.
- Practical workaround:
  - Use **Piper** for fully-local TTS (no HF download), or
  - preload `torch` before importing `llama_cpp` in `local_ai_server` (enables Kokoro hot-switch), or
  - pin a torch build compatible with the CUDA runtime in the image (follow-up work).

## 4) local_ai_server: testing + benchmarks

### Basic health check (websocket)
- `python smoke_test_ws.py --url ws://127.0.0.1:8765 --auth-token "$LOCAL_WS_AUTH_TOKEN" --verbose`

### Quick latency probes
- LLM and TTS p50/p95 can be tested by repeatedly sending `llm_request` / `tts_request` messages over WS.
- On the 4090 we observed very low single-request latencies once warmed, which is encouraging for a <2–3s voice-agent target.

## 5) Admin UI “Fully Local” wizard issues (affects Local Hybrid too)

### Symptom
- Wizard reports:
  - `Error response from daemon: No such container: local_ai_server`
  - or can’t start/inspect `local_ai_server` from the UI.

### Root cause (high-level)
- Wizard executes `docker compose` from the **admin_ui container context**, not from the host project root.
- That breaks relative paths / bind mounts and leads to “container not found” / “wrong project” behavior.

### Impact
- Both **Fully Local** and **Local Hybrid** flows call the same wizard “start local server” endpoint, so they share the problem.

### Tracking
- Linear issue created to fix wizard compose execution context and log retrieval (and to ensure Local Hybrid uses the corrected code path).

## 6) Access patterns: UI vs WS vs SIP

### Admin UI
- If the UI is bound only on localhost, you must port-forward it:
  - `ssh -p <ssh_port> root@<host_ip> -L 3003:127.0.0.1:3003`

### local_ai_server
- WS is typically on `8765`; for remote testing use Vast port opening/tunnels or SSH forwarding:
  - `ssh ... -L 8765:127.0.0.1:8765`

### SIP/RTP (Asterisk)
- SIP+RTP are usually **UDP**, which SSH `-L` does not forward.
- For “real calls” from a laptop softphone, plan on:
  - opening UDP 5060 + RTP range on Vast, **or**
  - using a VPN overlay (Tailscale/WireGuard) between laptop ↔ VM.

## 7) Asterisk behind NAT on Vast (VM)

On Vast, the VM may have only private addresses (e.g. `10.x`) and rely on Vast port-forwarding/NAT for the public IP. In that setup:

- Configure `pjsip.conf` transport with:
  - `external_signaling_address = <public_ip>`
  - `external_media_address = <public_ip>`
  - `local_net = <vm_subnet>`
- Consider shrinking the RTP port range in `rtp.conf` for easier port-forwarding:
  - Example: `rtpstart=10000` and `rtpend=10047` (24 calls worth of RTP port pairs).

## 8) Recommended approach for “real calls”: Tailscale

For SIP/RTP testing from a laptop softphone, a mesh/VPN overlay (Tailscale/WireGuard) is usually simpler than Vast port mapping (especially for RTP ranges).

Example (this run):
- VM Tailscale IP: `100.114.35.94`
- Laptop Tailscale IP: `100.97.52.23`

What we changed to make SIP/RTP stable over Tailscale:
- `/etc/asterisk/pjsip.conf` `transport-udp-nat`:
  - `external_signaling_address = <tailscale_ip>`
  - `external_media_address = <tailscale_ip>`
  - `external_signaling_port = 5060`
  - `local_net = 100.64.0.0/10` (plus the VM subnet)

## 9) Ensuring “shipped” Local AI backends actually work on GPU

### Why UI model switching can fail on GPU instances
The Admin UI can only switch to backends that are present in the `local_ai_server` image. On GPU instances, the `docker-compose.gpu.yml` override must forward the same build args (e.g., `INCLUDE_FASTER_WHISPER`, `INCLUDE_KROKO_EMBEDDED`) so `.env` toggles actually affect the GPU image.

### Current defaults (GPU image)
- `local_ai_server/Dockerfile.gpu` now defaults `INCLUDE_FASTER_WHISPER=true` so Whisper STT is available out of the box on GPU builds.
- `INCLUDE_KROKO_EMBEDDED` remains opt-in because it pulls a vendor binary at build time and requires an explicit checksum pin.

### Kroko embedded prerequisites (no API key)
To use **Kroko embedded** (no API key), you need:
1) `INCLUDE_KROKO_EMBEDDED=true` during build
2) `KROKO_SERVER_SHA256=<sha256>` set in `.env` (pins the downloaded `kroko-server` binary)
3) A Kroko model file in `models/kroko/` (wizard can download from the catalog)

Compute the checksum (on the host VM):
- `curl -fsSL https://download.kroko.ai/binaries/kroko-onnx-online-websocket-server | sha256sum`

Then set:
- `KROKO_SERVER_SHA256=<printed_sha>`

### Wizard / UI behavior improvements
- Wizard STT backend selection is now capability-aware:
  - Disables Faster-Whisper if the image doesn’t include it
  - Disables Kroko “Embedded Mode” if the image doesn’t include the embedded binary, with guidance on required rebuild args
- Env page now exposes `KROKO_SERVER_SHA256` when `INCLUDE_KROKO_EMBEDDED=true`.

## 10) Automated UI-path model load testing (recommended)

To validate “loads via UI” (same endpoints the Models page uses), run this on the VM:
- `python3 tools/ui_model_matrix.py --all-tts`

What it does:
- Calls `POST /api/local-ai/switch` for each target STT/TTS backend/model
- Records pass/fail + elapsed time
- Skips backends not present in `/api/local-ai/capabilities` with a clear reason

Useful options:
- `python3 tools/ui_model_matrix.py --all-tts --all-stt`
- `python3 tools/ui_model_matrix.py --json-out /tmp/aava-model-matrix.json`
- `python3 tools/ui_model_matrix.py --no-revert`

## 11) 2026-02-21 verification results (Vast RTX 4090 VM)

### Setup
- Branch: `local-ai-server-improvements`
- Services: `admin_ui`, `ai_engine`, `local_ai_server` via Docker Compose (GPU override)
- Local AI image rebuilt on-host:
  - `docker compose -p asterisk-ai-voice-agent -f docker-compose.yml -f docker-compose.gpu.yml up -d --build --force-recreate local_ai_server`

### UI-path model matrix
Run (auto-auths by minting a JWT from `JWT_SECRET` in `.env`):
- `python3 tools/ui_model_matrix.py --base http://127.0.0.1:3003 --all-stt --all-tts --json-out /tmp/aava-model-matrix.json`

Observed summary on this VM:
- **OK**: Vosk, Sherpa (STT), Piper voices (TTS), Kokoro voices (TTS), Faster-Whisper (STT base/small/medium)
- **Skipped (action required)**:
  - Whisper.cpp: backend available, but **no** ggml `.bin` model present under `models/stt/`
  - Kroko embedded: requires rebuilding `local_ai_server` with `INCLUDE_KROKO_EMBEDDED=true` (and providing a Kroko model file under `models/kroko/`)
  - MeloTTS: requires rebuilding `local_ai_server` with `INCLUDE_MELOTTS=true`

### Key reliability fix: Kroko embedded hot-switch inference
The Admin UI now infers `kroko_embedded=true` for STT switches when the selected model path points at `/app/models/kroko/...` (or a `.onnx/.data` file), so “select Kroko embedded in UI” doesn’t silently remain in cloud mode and fail without an API key.

## 12) Whisper Base STT “agent keeps speaking” RCA (ExternalMedia)

### Symptom
- With `LOCAL_STT_BACKEND=faster_whisper` (base/small), the agent can enter a loop where it keeps responding without waiting for caller turns.
- `local_ai_server` logs show repeated short transcripts while TTS is active (self-echo-like behavior).

### What logs showed
- `ai_engine` provider chunk logs had missing audio format metadata:
  - `encoding=""`
  - `sample_rate_hz=0`
  - `approx_duration_ms=0.0`
- `ConversationCoordinator` cleared segment gating immediately after chunk arrival (`reason=segment-end`), re-enabling capture too early.

### Root cause
- `src/providers/local.py` emitted `AgentAudioDone` immediately on each binary chunk.
- The same provider did not attach `encoding`/`sample_rate` to `AgentAudio`.
- Net effect: engine could not estimate playback duration and dropped TTS gating before playback actually finished.

### Fix implemented
- Local provider now:
  1) Parses `tts_audio` metadata from local-ai-server and caches `encoding` + `sample_rate`.
  2) Emits `AgentAudio` with normalized format hints (`mulaw`/`linear16`) and sample rate.
  3) Delays `AgentAudioDone` by estimated playout duration (`bytes / (rate * bytes_per_sample) + small tail`).
  4) Applies same delayed-done behavior to `tts_response` base64 audio path.

### Validation
- Added unit coverage in `tests/test_local_provider_audio_timing.py`:
  - binary + `tts_audio` metadata path
  - `tts_response` JSON audio path
  - metadata-missing fallback (`mulaw`/`8kHz`)

## 13) Whisper-only segment-gating rearm (2026-02-21)

### Goal
- Apply Option A only to Whisper STT paths to avoid regressions in Vosk/Sherpa/Kroko.

### Implementation
- `local_ai_server` now includes `stt_backend` in every `stt_result` payload, including `stt_unavailable` finals.
- `src/providers/local.py` now tracks runtime STT backend (`stt_result.stt_backend`) and exposes:
  - `get_active_stt_backend()`
  - `is_whisper_stt_active()` (`faster_whisper` or `whisper_cpp`)
- `src/engine.py` `AgentAudioDone` continuous-stream branch now re-arms segment gating for:
  - `google_live` (existing behavior)
  - `local` provider **only when** runtime backend is Whisper (`faster_whisper` / `whisper_cpp`)

### Why this limits regression risk
- Non-Whisper local STT backends keep the previous behavior (no forced rearm).
- Re-arm condition keys off runtime backend reported by local-ai-server, not only static config.

### Validation
- `pytest -q tests/test_local_provider_audio_timing.py`
- Result: `5 passed`

## 14) LLM context overflow fix (2026-02-21)

### Symptom
- When the Admin UI / engine pushed a large `default` system prompt into `local_ai_server`, the server could crash llama.cpp with:
  - `ValueError: Requested tokens (...) exceed context window of 768`

### Root cause
- `LOCAL_LLM_CONTEXT` defaulted to `768`, and prompt trimming only removed user turns, not the system prompt. If the system prompt alone exceeded `n_ctx`, the prompt still overflowed.

### Fix
- `local_ai_server/config.py` now defaults `llm_context` to `2048` when `GPU_AVAILABLE=true` (unless `LOCAL_LLM_CONTEXT` is set).
- `local_ai_server/server.py` now hardens prompt sizing:
  - System prompt is truncated as a last resort to prevent overflow.
  - `max_tokens` is reduced dynamically based on remaining context.

## 15) New preflight mode: Local AI Server only

To make GPU onboarding simpler (especially on cloud VMs), we added a preflight mode that runs only the checks needed to bring up `local_ai_server`:

- `./preflight.sh --local-server`

What it does:
- Runs core OS/Docker/compose/env/GPU checks
- Skips Asterisk detection/config audits and Admin UI-specific checks
- Skips `asterisk_media/` directory creation (irrelevant for standalone GPU server)
- Checks the Local AI Server WS port (`LOCAL_WS_PORT`, default `8765`)
- Warns if `LOCAL_LLM_GPU_LAYERS=0` while GPU is detected (see below)

This is intended as the recommended “first command” for anyone who wants to benchmark and tune the Local provider on a GPU machine before setting up full telephony.

## 16) GPU layers footgun (2025-07-14)

### Problem
`.env.example` shipped `LOCAL_LLM_GPU_LAYERS=0` as an **uncommented active default**. Users who:
1. Copied `.env.example` to `.env`
2. Ran `preflight.sh` (which correctly set `GPU_AVAILABLE=true`)
3. Built with `docker-compose.gpu.yml`

...still ran LLM inference on CPU because `LOCAL_LLM_GPU_LAYERS=0` was never changed.

### Fix
- `.env.example`: `LOCAL_LLM_GPU_LAYERS=0` is now **commented out**. Users must explicitly uncomment and set `-1` for auto GPU offloading.
- `preflight.sh`: After setting `GPU_AVAILABLE=true`, checks if `LOCAL_LLM_GPU_LAYERS=0` in `.env` and warns with suggestion to set `-1`.

### Practical advice
- **Always set `LOCAL_LLM_GPU_LAYERS=-1`** on GPU systems. This auto-detects available layers.
- If you need fine-grained control (e.g., shared GPU), set a specific number like `35`.
- The config default in `local_ai_server/config.py` is `0` (safe for CPU), but `from_env()` reads the env var.

## 17) Capabilities fallback: CPU minimal mode (2025-07-14)

### Problem
When `local_ai_server` was unreachable or returned an unexpected response, the Admin UI capabilities endpoint (`/api/local-ai/capabilities`) unconditionally claimed `llm.available=true`. On CPU-only systems where `runtime_mode=minimal` (the default when `GPU_AVAILABLE=false`), LLM is **not preloaded**, so this misled the UI into offering LLM configuration.

### Fix
Capabilities fallback now checks `GPU_AVAILABLE` and `LOCAL_AI_MODE` from env:
- If `GPU_AVAILABLE=true` or `LOCAL_AI_MODE=full`: claims LLM available (reasonable assumption)
- Otherwise: `llm.available=false` with message "CPU minimal mode — LLM not preloaded. Set LOCAL_AI_MODE=full or add GPU."

### Practical advice
- On CPU-only systems, use `local_hybrid` pipeline (local STT/TTS + cloud LLM like GPT-4o).
- If you **must** run LLM on CPU: set `LOCAL_AI_MODE=full` explicitly. Expect 10-30s per response.

## 18) Docker healthcheck timing (2025-07-14)

### Problem
`docker-compose.yml` had `retries: 180` with `interval: 60s` = **3-hour window** before marking the container unhealthy. Users ran `docker ps`, saw `(health: starting)` for extended periods, and thought the container was broken.

### Fix
Reduced to `retries: 30` (30-minute window after `start_period: 120s`). This is still generous — most models load in 2-5 minutes. Large models (7B+) may take up to 15 minutes on first boot with auto-context tuning.

### If your model takes longer
Increase `retries` in `docker-compose.yml` or use a local override:
```yaml
# docker-compose.override.yml
services:
  local_ai_server:
    healthcheck:
      retries: 60  # 60 min window
```

## 19) Security: non-loopback bind enforcement (already in server.py)

### Design
`local_ai_server/server.py` already implements **fail-closed** security: if `LOCAL_WS_HOST` is non-loopback (e.g., `0.0.0.0`) and `LOCAL_WS_AUTH_TOKEN` is empty, the server **refuses to start** with a clear error:

```
SECURITY: LOCAL_WS_HOST=0.0.0.0 (non-loopback) but LOCAL_WS_AUTH_TOKEN is not set.
Refusing to start - set LOCAL_WS_AUTH_TOKEN or bind to 127.0.0.1.
```

### Practical advice for split-host
1. On the GPU server: `LOCAL_WS_HOST=0.0.0.0` + `LOCAL_WS_AUTH_TOKEN=<openssl rand -hex 32>`
2. On the AI engine machine: `LOCAL_WS_URL=ws://<gpu-ip>:8765` + same token
3. Ensure port 8765 is firewalled to only allow the AI engine machine
4. For production over untrusted networks: use a VPN (Tailscale/WireGuard) or TLS reverse proxy
