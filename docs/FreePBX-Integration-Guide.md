# FreePBX Integration Guide (AudioSocket-First Architecture)

**Note:** This guide reflects the GA-track deployment. AudioSocket is the default upstream transport, with automatic fallback to file playback. ExternalMedia RTP remains available for legacy scenarios and troubleshooting but is no longer the primary path.

## 1. Overview

The Asterisk AI Voice Agent v3.0 integrates with FreePBX by combining ARI call control with an AudioSocket TCP listener hosted in the `ai-engine`. Each inbound call enters Stasis, the engine originates an AudioSocket leg, and `StreamingPlaybackManager` paces provider audio downstream while retaining tmpfs file playback as a fallback. ExternalMedia RTP can be preserved as an optional path when needed.

## 2. Prerequisites

- FreePBX installation with Asterisk 16+ (or FreePBX 15+) and ARI enabled.
- Docker and Docker Compose installed on the same host as FreePBX.
- Repository cloned (e.g., `/root/Asterisk-AI-Voice-Agent`).
- Port **8090/TCP** accessible for AudioSocket connections (plus 18080/UDP if retaining the legacy RTP path).
- Valid `.env` containing ARI credentials and provider API keys.

## 3. Dialplan Configuration

### 3.1 AudioSocket Contexts

Append the following contexts to `extensions_custom.conf` (or the appropriate custom include). Each context can be targeted from a FreePBX Custom Destination or IVR option so you can exercise a specific provider pipeline during testing.

```asterisk
[from-ai-agent]
exten => s,1,NoOp(Handing call directly to AI engine (default provider))
 same => n,Set(AI_PROVIDER=local_only)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[from-ai-agent-custom]
exten => s,1,NoOp(Handing call to AI engine with custom override)
 same => n,Set(AI_PROVIDER=custom)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[from-ai-agent-deepgram]
exten => s,1,NoOp(Handing call to AI engine with Deepgram override)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[from-ai-agent-openai]
exten => s,1,NoOp(Handing call to AI engine with OpenAI Realtime override)
 same => n,Set(AI_PROVIDER=openai_realtime)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[ai-agent-media-fork]
exten => _X.,1,NoOp(Local channel starting AudioSocket for ${EXTEN})
 same => n,Answer()
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,Set(AUDIOSOCKET_UUID=${EXTEN})
 same => n,Set(AS_UUID_RAW=${SHELL(cat /proc/sys/kernel/random/uuid 2>/dev/null || uuidgen 2>/dev/null)})
 same => n,Set(AS_UUID=${TOUPPER(${FILTER(0-9A-Fa-f-,${AS_UUID_RAW})})})
 same => n,ExecIf($[${LEN(${AS_UUID})} != 36]?Set(AS_UUID=${TOUPPER(${FILTER(0-9A-Fa-f-,${SHELL(uuidgen 2>/dev/null)})})}))
 same => n,NoOp(AS_UUID=${AS_UUID} LEN=${LEN(${AS_UUID})})
 same => n,AudioSocket(${AS_UUID},${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT})
 same => n,Hangup()

; keep ;1 leg alive while the engine streams audio
exten => s,1,NoOp(Local)
 same => n,Wait(60)
 same => n,Hangup()
```

Map the desired context to a Custom Destination (for example, `from-ai-agent-openai,s,1`) and reuse it inside an IVR to give testers a menu of provider options. Use the `AI_PROVIDER` values above to align with the YAML pipelines you plan to exercise.

> **Optional ExternalMedia Fallback**: Retain your previous `[ai-externalmedia]` context if you need the RTP-based path for troubleshooting. Swap transports via `config/ai-agent.yaml` when required.

### 3.2 Inbound Route

1. Open the FreePBX Admin panel.
2. Navigate to **Connectivity → Inbound Routes**.
3. Create or edit a route and set **Set Destination** → **Custom Destination** → `from-ai-agent,s,1`.
4. Apply configuration changes and reload the dialplan.

### 3.3 ARI Configuration

Ensure `/etc/asterisk/ari.conf` includes:

```ini
[general]
enabled = yes
pretty = yes
allowed_origins = 127.0.0.1

[asterisk-ai-voice-agent]
type = user
read_only = no
password = your_ari_password
```

## 4. AI Voice Agent Configuration

### 4.1 Environment (.env)

```bash
# Asterisk
ASTERISK_HOST=127.0.0.1
ASTERISK_ARI_USERNAME=asterisk-ai-voice-agent
ASTERISK_ARI_PASSWORD=your_ari_password

# Providers (set as needed)
DEEPGRAM_API_KEY=your_deepgram_key
OPENAI_API_KEY=your_openai_key
```

### 4.2 `config/ai-agent.yaml`

Below is a minimal AudioSocket-first configuration. Adjust hosts, credentials, and providers to match your deployment. See `docs/milestones/milestone-5-streaming-transport.md` for tuning guidance and `docs/milestones/milestone-7-configurable-pipelines.md` for pipeline details once shipped.

```yaml
# Application
default_provider: deepgram
audio_transport: audiosocket
# keep downstream_mode=file until streaming defaults are tuned for your trunk
downstream_mode: file

# Asterisk
asterisk:
  host: 127.0.0.1
  port: 8088
  username: asterisk-ai-voice-agent
  password: ${ASTERISK_ARI_PASSWORD}
  app_name: asterisk-ai-voice-agent

# AudioSocket listener
audiosocket:
  host: 0.0.0.0
  port: 8090
  format: pcm16_8k

# Streaming transport defaults (Milestone 5)
streaming:
  min_start_ms: 120
  low_watermark_ms: 80
  fallback_timeout_ms: 4000
  provider_grace_ms: 500
  jitter_buffer_ms: 160

barge_in:
  post_tts_end_protection_ms: 350

# Providers (examples)
providers:
  deepgram:
    api_key: ${DEEPGRAM_API_KEY}
    input_sample_rate_hz: 8000
  openai_realtime:
    api_key: ${OPENAI_API_KEY}
    turn_detection:
      type: server_vad
      silence_duration_ms: 400
  local:
    enable_stt: true
    enable_llm: true
    enable_tts: true

# Pipelines (Milestone 7)
pipelines:
  default:
    stt: deepgram_streaming
    llm: openai_realtime
    tts: deepgram_tts
    options:
      language: en-US
active_pipeline: default
```

## 5. Deployment Workflow

```bash
# Start services (both ai-engine + local-ai-server)
docker-compose up -d

# Watch logs for AudioSocket listener and ARI binding
docker-compose logs -f ai-engine
```

For cloud-only deployments you may run `docker-compose up -d ai-engine`. Ensure logs show `AudioSocket server listening` and `Successfully connected to ARI` before testing calls.

## 6. Verification & Testing

1. **Health Check**
   ```bash
   curl http://127.0.0.1:15000/health
   ```
   Expect `audiosocket_listening: true`, `audio_transport: "audiosocket"`, and provider readiness.

2. **Test Call**
   - Place a call into the inbound route.
   - Confirm log events: `AudioSocket connection accepted`, `AudioSocket connection bound to channel`, provider greeting, streaming buffer depth messages, and `PlaybackFinished` cleanup.
   - Scrape `/metrics` to capture latency gauges (`ai_agent_turn_latency_seconds`, etc.) before stopping containers.

3. **Log Monitoring**
   ```bash
   docker-compose logs -f ai-engine
   docker-compose logs -f local-ai-server
   tail -f /var/log/asterisk/full
   ```

## 7. Troubleshooting

- **Call never binds to AudioSocket**: verify port 8090 reachability, ensure the Local originate made it into Asterisk logs, and confirm `AUDIOSOCKET_UUID` matches the EXTEN passed from the dialplan.
- **Frequent streaming fallbacks**: adjust `streaming.min_start_ms` (higher warm-up) or `low_watermark_ms` (higher threshold). Capture logs and `/metrics` snapshots for regression notes.
- **Provider-specific failures**: check API credentials in `.env`, confirm `default_provider` and `active_pipeline` align, and review provider logs for `invalid_request_error` or throttle messages.
- **Need legacy RTP path**: swap `audio_transport` to `externalmedia`, ensure the RTP server is bound to port 18080, and route calls to `[ai-externalmedia]` while testing.

## 8. GA Readiness Checklist (FreePBX)

Use this checklist alongside `docs/ROADMAP.md` and the launch strategy under `plan/` to prepare your deployment for GA:

- [ ] Milestone 5 streaming defaults tuned for your trunk; regression notes captured in `docs/regressions/`.
- [ ] Milestone 6 provider parity verified (Deepgram + OpenAI Realtime) with call IDs recorded in `call-framework.md`.
- [ ] Pipelines (Milestone 7) validated on a staging extension once available; `active_pipeline` swaps succeed after hot reload.
- [ ] Optional monitoring stack (Milestone 8) smoke-tested; `/metrics` snapshots archived before container restarts.
- [ ] FreePBX operations docs updated and cross-linked with community/launch collateral per `plan/Asterisk AI Voice Agent_ Your Comprehensive Open Source Launch Strategy.md`.
- [ ] Contributors and operators briefed on fallback procedures (`audio_transport`, `downstream_mode`, rollback plan).

Keeping these items up to date ensures your FreePBX deployment stays aligned with the broader GA readiness plan.
