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
exten => s,1,NoOp(Handing call to AI engine with hybrid pipeline override)
 same => n,Set(AI_PROVIDER=hybrid_support)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[from-ai-agent-deepgram]
exten => s,1,NoOp(Handing call to AI engine with Deepgram override)
 same => n,Set(AI_PROVIDER=deepgram)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

[from-ai-agent-openai]
exten => s,1,NoOp(Handing call to AI engine with OpenAI pipeline)
 same => n,Set(AI_PROVIDER=default)
 same => n,Stasis(asterisk-ai-voice-agent)
 same => n,Hangup()

exten => _X.,1,NoOp(Local channel starting AudioSocket for ${EXTEN})
 same => n,Answer()
 same => n,Set(AUDIOSOCKET_HOST=127.0.0.1)
 same => n,Set(AUDIOSOCKET_PORT=8090)
 same => n,Set(AUDIOSOCKET_UUID=${EXTEN})
 same => n,AudioSocket(${AUDIOSOCKET_UUID},${AUDIOSOCKET_HOST}:${AUDIOSOCKET_PORT},ulaw)
 same => n,Hangup()

; keep ;1 leg alive while the engine streams audio
exten => s,1,NoOp(Local keepalive for AudioSocket leg)
 same => n,Wait(60)
 same => n,Hangup()
{{ ... }}
  host: 127.0.0.1
  port: 8088
  username: asterisk-ai-voice-agent
  password: ${ASTERISK_ARI_PASSWORD}
  app_name: asterisk-ai-voice-agent

# AudioSocket listener
audiosocket:
  host: 0.0.0.0
  port: 8090
  format: ulaw

# Streaming transport defaults (Milestone 5)
streaming:
  min_start_ms: 120
  low_watermark_ms: 80
  provider_grace_ms: 500
  jitter_buffer_ms: 160

barge_in:
  post_tts_end_protection_ms: 350

# Providers (examples)
providers:
  deepgram:
    api_key: ${DEEPGRAM_API_KEY}
    input_sample_rate_hz: 8000
  openai:
    api_key: ${OPENAI_API_KEY}
  local:
    enable_stt: true
    enable_llm: true
    enable_tts: true

# Pipelines (Milestone 7)
pipelines:
  default:
    stt: openai_stt
    llm: openai_llm
    tts: openai_tts
    options: {}
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

## 7. Troubleshooting

- **Call never binds to AudioSocket**: verify port 8090 reachability, ensure the Local originate made it into Asterisk logs, and confirm `AUDIOSOCKET_UUID` matches the EXTEN passed from the dialplan.
- **Frequent streaming fallbacks**: adjust `streaming.min_start_ms` (higher warm-up) or `low_watermark_ms` (higher threshold). Capture logs and `/metrics` snapshots for regression notes.
- **Provider-specific failures**: check API credentials in `.env`, ensure `default_provider` and `active_pipeline` align, and review provider logs for `invalid_request_error` or throttle messages.

## 8. GA Readiness Checklist (FreePBX)

Use this checklist alongside `docs/plan/ROADMAP.md` and the launch strategy under `docs/plan/` to prepare your deployment for GA:
{{ ... }}
```yaml
# Application
default_provider: openai_realtime
audio_transport: audiosocket
downstream_mode: file
Keeping these items up to date ensures your FreePBX deployment stays aligned with the broader GA readiness plan.
