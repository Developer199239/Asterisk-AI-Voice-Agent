# Call Framework Analysis — Deepgram Provider

## ✅ REGRESSION PASS — September 22, 2025 (AudioSocket Two-Way Conversation)

**Outcome**
- AudioSocket-first Deepgram regression executed end-to-end with both caller and agent audio flowing cleanly through the engine.
- No playback backlog or gating stalls observed; capture re-enabled between turns and barge-in window reopened as expected.

**Highlights**
- Greeting reached the caller immediately via tmpfs file playback; upstream speech was relayed to Deepgram with stable chunk sizes (~320 B PCM-16/8 kHz).
- Deepgram returned transcripts for each caller turn, and responses were synthesized and delivered back over the existing file-based playback path without glitches.
- Health check after hangup reported `ari_connected=true`, `audiosocket_listening=true`, and `active_calls: 0`.
- Provider prompt/instructions now emphasise concise (<20 word) answers to reduce LLM and TTS processing time per turn.

**Latest Verification (2025-09-22 23:47 UTC-7)**
- Conversation turns completed in ≤1.8 s from speech end to playback, as captured by `ai_agent_turn_latency_seconds` histograms during the call.
- `ai_agent_last_turn_latency_seconds` and `ai_agent_last_transcription_latency_seconds` reset to 0 after cleanup, confirming coordinator metrics unwind correctly between sessions.
- Greeting playback now skips Deepgram TTS synthesis when the provider lacks `text_to_speech`, eliminating repeated `AttributeError` stack traces.

**Remaining Work**
- Capture Prometheus metrics immediately after regressions (before container restarts) so histogram buckets persist for trend analysis.
- Prepare for downstream streaming by wiring feature-flag guards and jitter buffer defaults without regressing the current file playback path.
- Cross-IDE note: mirror these findings into `.cursor/` and `.windsurf/` rules when behaviour changes so Cursor/Windsurf sessions inherit the same regression state.

---

## ❌ REGRESSION BLOCKER — September 22, 2025 (Streaming playback loop / caller audio dropped)

**Outcome**
- Deepgram keeps talking in a loop; the caller never hears an opportunity to respond and any speech from the caller is ignored.

**Key Evidence**
- After the greeting, the engine immediately schedules ~100 micro-playbacks in succession (`🔊 AUDIO PLAYBACK - Started … audio_size=960`) and each one adds a gating token; active_count climbs into the 20s while `audio_capture_enabled=False` (`logs/server-ai-engine-call.log:324-900`).
- Every RTP frame arriving from the caller while Deepgram is speaking is discarded with `RTP audio dropped - capture disabled or TTS playing` (`logs/server-ai-engine-call.log:930-1130`).
- When the playback backlog finally drains, gating flips back to zero but by then Deepgram has already queued the next response, so capture never stays enabled long enough to stream caller audio; the conversation devolves into Deepgram talking to itself.
- Cleanup ends with `Cannot clear gating token - call not found` warnings because the session is destroyed before the final backlog finishes (`logs/server-ai-engine-call.log:19769-20130`).

**Why It Broke**
- Our file-based playback pipeline treats every `AgentAudio` chunk as a separate deterministic playback. Deepgram streams dozens of micro-segments per response, so the ConversationCoordinator keeps capture disabled almost continuously. Because WebRTC capture is gated during playback, caller audio is dropped for the entire response, preventing Deepgram from ever hearing the user.
- The refactor fixed the earlier `NameError`, so we now process these events, but the gating strategy is still incompatible with continuous streaming providers.

**Follow-up**
- ✅ **Fix applied (2025-09-22):** `AgentAudio` chunks now buffer in-session and flush on `AgentAudioDone`, producing a single playback per response so gating drops back to zero quickly.
- Allow continuous providers to receive caller audio even while TTS playback tokens are active (e.g., keep provider streaming but suppress VAD while agent speaks).
- Ensure cleanup drains any remaining playback references before removing the session to avoid the `Cannot clear gating token` warning storm.
- Re-test after revising gating so that logs show caller RTP frames processed (`audio_capture_enabled=True`) immediately after each response and Deepgram stops self-looping.

## ❌ REGRESSION BLOCKER — September 22, 2025 (AgentAudio handler NameError)

**Outcome**
- Deepgram streamed back-to-back responses, never un-gated capture, and caller speech was ignored.

**Key Evidence**
- `Error in provider event handler ... name 'call_data' is not defined` on every `AgentAudio` chunk (`logs/server-ai-engine-call.log:210-233`).
- TTS gating `active_count` climbs steadily (1→13) while `audio_capture_enabled=False`, so each RTP frame is dropped (`logs/server-ai-engine-call.log:147-339`, `73-130`).
- After hangup we spam `Cannot clear gating token - call not found` and `PlaybackFinished for unknown playback ID` because the session already cleaned up.

**Why It Broke**
- Refactor replaced dict-based `call_data` with `CallSession`, but the Deepgram `AgentAudio` path still referenced the old dict variable. The handler now raises before clearing provider timeouts or updating conversation state, so gating tokens never release.

**Follow-up**
- ✅ **Fix applied (2025-09-22):** `on_provider_event` now uses the `CallSession` object, cancels any pending provider timeout task, updates `session.conversation_state`, and persists the session (`src/engine.py:2368-2434`).
- Needs redeploy verification: expect to see a single `AgentAudio` playback per response, `audio_capture_enabled=True` once playback finishes, and no `NameError` / gating warnings on the next regression.

## ❌ REGRESSION BLOCKER — September 22, 2025 (VAD `frame_buffer` missing)

**Outcome**
- Deepgram greeting looped, but live caller audio never reached the provider; engine eventually fell back to dumping a 4 s buffer into the local provider.

**Key Evidence**
- `Error in VAD processing ... KeyError: 'frame_buffer'` repeats for every frame once capture re-enabled (`logs/ai-engine-latest.log:365-978`).
- With VAD blown up, the engine pushes a 4-second batch to the legacy pipeline instead of streaming (`logs/ai-engine-latest.log:989-990`).
- Local AI server, not Deepgram, handled TTS/STT for the entire call (`logs/local-ai-server-latest.log:62-76`).

**Why It Broke**
- When capture resumed after the greeting, the session’s VAD state lacked the `frame_buffer` key even though the guard existed, so `_process_rtp_audio_with_vad` crashed on every chunk. Because the coroutine raised before hitting `provider.send_audio`, upstream audio never left the engine, leaving Deepgram idle while playback manager kept serving greetings/responses.

**Follow-up**
- Harden the VAD state bootstrap: ensure `frame_buffer` (and the rest of the baseline keys) are restored whenever gating flips capture back on; emit a one-off log dumping `session.vad_state.keys()` the next time the guard fires.
- Confirm why Deepgram never emitted a handshake (`Connecting to Deepgram Voice Agent`) — we may still be short-circuiting to the local provider when greeting synthesis is requested. Re-run regression once the VAD guard is fixed and Deepgram session start is confirmed.
- ✅ **Fix applied (2025-09-22):** `src/engine.py` now rebuilds the default VAD state and patches missing keys whenever capture resumes via `_ensure_vad_state_keys`. Expect one-off warnings (`VAD state missing keys, patching defaults`) on the next call; if they reappear afterward, re-open this blocker.
- Next regression should show uninterrupted VAD processing (no `KeyError: 'frame_buffer'`) and downstream Deepgram events (`Connecting to Deepgram Voice Agent`, `AgentAudio`). Capture fresh logs after redeploy with `make server-logs SERVICE=ai-engine`.

## ❌ REGRESSION BLOCKER — September 22, 2025 (Typed Config Not Deployed)

**Outcome**
- No greeting or downstream audio played; call was torn down after a few seconds.

**Key Evidence**
- `Error starting provider session for ExternalMedia ... 'dict' object has no attribute 'api_key'` (`ai-engine` container, 20:23:00 UTC-7, channel_id=1758572574.571).
- Continuous `🎤 AUDIO CAPTURE - Check audio_capture_enabled=False` followed by `RTP audio dropped` while RTP frames streamed in.

**Why It Broke**
- The remote container still runs the pre-fix code path that hands a raw dict into `DeepgramProvider`, so accessing `.api_key` crashes provider startup before the greeting can synthesize.

**Follow-up**
- Rebuild and redeploy the ai-engine with the new `DeepgramProviderConfig` wiring, then rerun the regression call.
- After redeploy, verify logs show `Connecting to Deepgram Voice Agent...` and `Provider session started for ExternalMedia` before testing audio.

## ❌ REGRESSION BLOCKER — September 22, 2025 (Second Attempt, Same Crash)

**Outcome**
- Deepgram call again produced silence; provider startup failed before greeting playback.

**Key Evidence**
- `ExternalMedia channel mapped to caller ...`
- `Error starting provider session for ExternalMedia ... 'dict' object has no attribute 'api_key'` (`ai-engine`, 20:29:22 UTC-7, caller_channel_id=1758572957.574).
- Stack trace shows `DeepgramProvider.start_session` still receiving a dict instead of the typed config.

**Why It Broke**
- The running container still uses the old Deepgram implementation; redeploy has not occurred, so the bug persists.

**Follow-up**
- Force rebuild and redeploy the `ai-engine` image (`make deploy-force` or equivalent). Confirm the new container logs the typed-config validation line and the Deepgram WebSocket handshake before scheduling another regression.
- While the server is still tracking `develop` and our fixes live on a feature branch, copy the patched files directly onto `/root/Asterisk-Agent-Develop/src` before redeploying to confirm the change in place. Once audio is verified, merge the feature branch into `develop` and perform a clean `git pull` + `docker-compose up --build -d ai-engine` on the server to normalize.
## 🛠️ Verification Snapshot — September 22, 2025 (Post-Redeploy Sanity Check)

- Copied patched `src/config.py`, `src/engine.py`, and `src/providers/deepgram.py` directly onto `/root/Asterisk-Agent-Develop/src` and rebuilt `ai-engine`.
- Manual `docker exec ai_engine python -` probe confirmed `DeepgramProvider.config` resolves to `DeepgramProviderConfig` and a test `provider.start_session('test')` successfully established the Deepgram websocket (see logs for `Connecting to Deepgram Voice Agent...` followed by `✅ Successfully connected`).
- If a regression call still throws `'dict' object has no attribute "api_key"`, double-check timestamp—older log entries can appear after redeploy. Run the inline probe again to verify the container is serving the typed provider before the next call.

## ⚠️ PARTIAL SUCCESS — September 22, 2025 (Greeting Plays, Caller Audio Not Routed)

**Outcome**
- Deepgram greeted the caller and the call cleaned up cleanly, but no downstream response followed the user’s speech.

**Key Evidence**
- `🎤 AUDIO CAPTURE - ENABLED - Processing audio ... audio_capture_enabled=True` (caller audio reached the engine).
- No `Provider input` or Deepgram transcription events after the greeting; instead VAD reported silence (`webrtc_silence_frames=948`) and the call timed out.

**Hypothesis**
- Caller audio is flowing but VAD never sees a voiced frame, so the engine never sends chunks to Deepgram.

**Next Checks**
- Cross-check Deepgram websocket logs (look for `Transcription` events) and verify chunk forwarding in `_process_rtp_audio_with_vad` now that the typed config is live.

## INVESTIGATION — September 22, 2025 (VAD Not Detecting Speech)

**Outcome**
- After the greeting, the caller spoke but received no response. The call eventually timed out. The system was "listening" but not "hearing" any speech.

**Root Cause Analysis**
- The Voice Activity Detection (VAD) system failed to detect any voiced frames from the caller's RTP audio stream.
- The `_process_rtp_audio_with_vad` function was called, and `audio_capture_enabled` was `True`.
- However, the WebRTC VAD reported only silence (`webrtc_silence_frames=948`), so no audio was ever buffered or sent to the Deepgram provider for transcription.
- This is confirmed by the absence of `Provider input` or Deepgram `Transcription` events in the logs after the greeting.

**Architectural Context**
- As noted in `Architecture.md`, even though Deepgram supports continuous streaming, the conversation state (i.e., deciding when the user has finished speaking) is still driven by the engine's VAD.
- This VAD failure is the root cause of the one-way conversation.

**Next Steps & Recommended Fixes**
1.  **Tune VAD Aggressiveness**: The `webrtc_aggressiveness` setting in `config/ai-agent.yaml` is likely too high for telephony audio. Lower it from `2` to `0` (least aggressive) to make it more sensitive.
2.  **Verify Fallback Mechanism**: Ensure the `fallback_interval_ms` logic, which forces audio processing even when VAD is silent, is correctly engaging for the Deepgram provider path. The current VAD failure suggests it is not.
3.  **Add Debug Logging**: Add temporary logging in `_process_rtp_audio_with_vad` to inspect the raw audio frames. This will confirm if the audio is corrupted/silent or if the VAD is simply misinterpreting it.

---

## Milestone 6 — Streaming Observability Checklist (In Progress)

- **What to verify**
  - Streaming path engages when `downstream_mode=stream` is enabled for Deepgram and provider emits streaming chunks.
  - `/health` exposes a `streaming` block with sensible values while the call is in flight.
  - Prometheus metrics reflect live streaming activity and fallbacks.

- **Quick commands**
  - Health:
    ```bash
    make test-health
    # or
    curl -sS ${HEALTH_URL:-http://127.0.0.1:15000/health} | jq .
    ```
  - Metrics:
    ```bash
    make test-metrics
    # or
    curl -sS ${METRICS_URL:-http://127.0.0.1:15000/metrics} \
      | egrep "ai_agent_streaming_|ai_agent_rtp_|ai_agent_(turn|transcription)_|ai_agent_audio_capture_enabled|ai_agent_tts_gating_active"
    ```

- **Metrics to watch during a streaming call**
  - `ai_agent_streaming_active{call_id}` should be `1` while audio is streaming.
  - `ai_agent_streaming_bytes_total{call_id}` should increase steadily.
  - `ai_agent_streaming_jitter_buffer_depth{call_id}` should stay within a few queued chunks (config-driven).
  - `ai_agent_streaming_last_chunk_age_seconds{call_id}` should remain low; spikes indicate provider stalls.
  - `ai_agent_streaming_keepalives_sent_total{call_id}` increments during the call.
  - `ai_agent_streaming_keepalive_timeouts_total{call_id}` increments only when the downstream path stalls.
  - When inducing stalls/silence, expect `ai_agent_streaming_fallbacks_total{call_id}` and `/health.streaming.fallbacks_total` to increment.

- **/health expectations (during call)**
  - `streaming.active_streams >= 1`
  - `streaming.ready_count` and `streaming.response_count` flip as provider events arrive.
  - `streaming.fallbacks_total` increases only when a fallback is triggered.
  - `streaming_details[]` includes per-call records: `call_id`, `provider`, `streaming_started`, `bytes_sent`, `fallbacks`, `last_error`.

- **Post-call checks**
  - `make test-health` → `active_calls: 0` and `streaming.active_streams: 0` once cleanup completes.
  - Streaming gauges (active, jitter depth, last chunk age) drop back to 0 shortly after cleanup.

- **Notes**
  - Maintain detailed Deepgram streaming logs in this file and reference this checklist from `call-framework.md` instead of duplicating content.

---

## 2025-09-22 - Milestone 6: Streaming TTS Implementation

**Implementation Summary**
- ✅ Extended `config/ai-agent.yaml` with streaming configuration parameters
- ✅ Created `StreamingPlaybackManager` for real-time audio streaming via AudioSocket/ExternalMedia
- ✅ Updated Deepgram provider to support incremental AgentAudio streaming with Ready/AgentResponse states
- ✅ Integrated streaming playback into engine with automatic fallback to file playback
- ✅ Added comprehensive unit tests for streaming functionality
- ✅ Documented dialplan contexts for testing streaming vs file-based playback

**Key Features Implemented**
1. **Streaming Configuration**: Added `streaming.*` knobs for sample rate, jitter buffer, keepalive, timeouts
2. **StreamingPlaybackManager**: Handles real-time audio chunk streaming with jitter buffering and keepalive
3. **Deepgram Streaming**: Enhanced provider to emit streaming events and handle incremental audio chunks
4. **Automatic Fallback**: Streaming automatically falls back to file playback on errors/timeouts
5. **ConversationCoordinator Integration**: Streaming respects gating rules and state management
6. **Dialplan Contexts**: `from-ai-agent` (local/file), `from-ai-agent-deepgram` (Deepgram/file), `ai-agent-media-fork` (AudioSocket binder reused for streaming tests)

**Configuration Changes**
```yaml
downstream_mode: "file"  # Default, can be set to "stream"
streaming:
  sample_rate: 8000
  jitter_buffer_ms: 50
  keepalive_interval_ms: 5000
  connection_timeout_ms: 10000
  fallback_timeout_ms: 2000
  chunk_size_ms: 20
```

**Testing Status**
- ✅ Unit tests created for `StreamingPlaybackManager` and engine integration
- ⚠️ Integration tests pending (requires Docker environment)
- ⚠️ Manual regression testing pending (requires server deployment)

**Expected Log Patterns**
- File-based: `🔊 TTS START - Response playback started via PlaybackManager`
- Streaming: `🎵 STREAMING STARTED - Real-time audio streaming initiated`
- Fallback: `🎵 STREAMING FALLBACK - Switched to file playback`

**Next Actions**
1. Deploy to test server and run integration tests
2. Test streaming mode via `[from-ai-agent-deepgram]` with `DOWNSTREAM_MODE=stream`
3. Verify fallback behaviour under network stress
4. Update this regression log with real streaming metrics once outbound transport is wired

---

## 2025-09-22 19:18 PDT — AudioSocket Deepgram Regression (from-ai-agent-deepgram)

**Call Setup**
- Dialed inbound route landed in `ivr-3`, jumped to the new context: `Goto("SIP/callcentricB12-00000067", "from-ai-agent-deepgram,s,1")`.
- Context sets `AI_PROVIDER=deepgram` and enters `Stasis(asterisk-ai-voice-agent)`; engine originated the usual `Local/<uuid>@ai-agent-media-fork` leg to spin up AudioSocket on port 8090.
- Config left at `downstream_mode=file` (streaming flag off) so downstream audio still flowed over file playback; upstream capture remained AudioSocket-first.

**Results**
- Greeting and subsequent Deepgram responses played cleanly with no gating backlog; `AudioSocket connection accepted` and `bound to channel` logged within ~200 ms of call start.
- Health check after hangup (`make server-health`) reported `active_calls: 0`, `streaming.active_streams: 0`, and both providers ready.
- Prometheus scrape (`make test-metrics`) showed new streaming gauges at zero (expected while downstream_mode=file) and populated RTP ingress counters for the call.
- Asterisk log snippet confirms context routing and no media errors were emitted.

**Artifacts Gathered**
- `docker-compose logs -n 200 ai-engine` captured AudioSocket bind, Deepgram transcription/response events, fallback counters staying at 0.
- `/metrics` snapshot stored under `logs/2025-09-22-deepgram-streaming-metrics.txt` (local) for latency comparison.

**Next Steps**
1. Enable `downstream_mode=stream` on the next regression to exercise the StreamingPlaybackManager path now that the control-plane is stable.
2. Capture `/metrics` mid-call looking for `ai_agent_streaming_*` gauges (expect active/fallback counters to tick once outbound streaming is wired).
3. Add a short README note on the server documenting which DID targets `from-ai-agent-deepgram` so on-call engineers can re-run the check.

---

## Streaming Regression Checklist — `downstream_mode=stream` (2025-09-22 19:52 PDT)

- **Prerequisites**
  - Set `downstream_mode=stream` (env `DOWNSTREAM_MODE=stream` or update `config/ai-agent.yaml`).
  - Confirm `make server-health` reports `streaming.active_streams: 0` and both providers ready.

- **Call Flow**
  1. Route a call through `from-ai-agent-deepgram`.
  2. During the call, watch `docker-compose logs -f ai-engine` for `🎵 STREAMING PLAYBACK - Started` and `RTP streaming send` entries.
  3. Run `make test-metrics` mid-call; expect `ai_agent_streaming_active{call_id}=1`, `ai_agent_streaming_bytes_total` increasing, and `ai_agent_streaming_fallbacks_total=0`.
  4. After hangup, `make server-health` should show `active_calls: 0`, `streaming.active_streams: 0`, and `streaming.last_error` cleared.

- **Troubleshooting**
  - If `ai_agent_streaming_fallbacks_total` increments, inspect `streaming.last_error` (e.g., `transport-failure` or `timeout`) and check the Asterisk RTP path. The engine will continue with file playback automatically.
  - Silence on the call usually indicates the ExternalMedia leg is missing or blocked; verify bridge membership and firewall rules for the RTP port.

- **Artifacts**
  - Metrics snapshot, `/health` JSON, and ai-engine logs archived alongside this entry (`logs/2025-09-22-streaming-regression/`).

## ✅ Regression Pass — 2025-09-22 20:38 PDT (Streaming Enabled)

- `DOWNSTREAM_MODE=stream` enabled; ai-engine logs show `🎵 STREAMING PLAYBACK - Started` and continuous RTP ingress/egress without triggering `STREAMING FALLBACK` entries.
- Live `/health` after hangup reported `total_frames_received: 1029`, `total_packet_loss: 0`, `active_streams: 0`.
- `/metrics` currently exposes only baseline gauges; capture mid-call metrics next run to confirm streaming counters emit once Prometheus wiring is extended.
- Next focus: add client-visible streaming metrics, tighten keepalive/reconnect handling, and exercise barge-in behaviour.

---

## 2025-09-23 00:26 PDT — AudioSocket Regression Failure (from-ai-agent-deepgram)

**Call Setup**
- Routed DID into `from-ai-agent-deepgram`, which set `AI_PROVIDER=deepgram` and entered `Stasis(asterisk-ai-voice-agent)`.
- Engine created the caller bridge and originated the Local leg (`Local/82c5869a-10d5-4ecb-96ab-92875c4fd856@ai-agent-media-fork/n`) exactly as in the previous AudioSocket flow.

**Observed Behaviour**
- Asterisk attempted to execute `AudioSocket(82c5869a-10d5-4ecb-96ab-92875c4fd856,127.0.0.1:18090)` and immediately logged `Connection refused` (`/var/log/asterisk/full`, 00:26:51). The Local legs tore down before any audio flowed.
- `docker-compose logs ai-engine` for the same window only shows the hybrid bridge set-up messages (`🎯 DIALPLAN EXTERNALMEDIA - ...`) followed by `Channel destroyed` events—there is no `AudioSocket connection accepted/bound` entry.
- Local AI server log confirms a websocket handshake from the engine, but no STT/LLM/TTS activity was triggered (`docker-compose logs local-ai-server`).

**Preliminary Root Cause**
- The dialplan is targeting `AUDIOSOCKET_PORT=18090`, but the ai-engine build does not expose a listener on that socket (there is no `AudioSocket server listening` log, and the container has no bound port). The prior regression used port 8090.
- Because the AudioSocket bind never happens, the engine never starts a provider session; the call ends after the Local channels hang up, producing silence on the line.

**Next Actions**
1. Align the dialplan port back to the engine’s configured AudioSocket listener (historically 8090) or expose the correct port from the engine if it has moved.
2. Confirm the engine is actually launching its AudioSocket server at container start—capture the `AudioSocket server listening` log (or add it back if it regressed) before placing the next call.
3. Re-run the regression once the TCP bind succeeds and verify `AudioSocket connection accepted` plus Deepgram transcription/response events return to the logs.

---

## 2025-09-23 01:01 PDT — AudioSocket Regression (engine listener enabled)

**Observed Behaviour**
- Ai-engine now reports `AudioSocket connection accepted` and binds the UUID from the first Local leg, but `/var/log/asterisk/full` immediately logs `res_audiosocket.c: Received non-audio AudioSocket message` and tears down the call.
- `docker-compose logs ai-engine` reveals a second AudioSocket connection from the complementary Local leg; the engine sends a `uuid-rejected` error TLV back, which Asterisk classifies as the non-audio frame.
- Local AI server still notes only the transient handshake and no STT/LLM traffic, confirming the media path never opens.

**Root Cause**
- The `[ai-agent-media-fork]` dialplan executes for both `Local/...;1` and `Local/...;2`. Each leg opens an AudioSocket connection with the same UUID. The engine treated any subsequent UUID handshake as an error and responded with an `Error` TLV (type `0xFF`), which Asterisk logged before dropping the bridge.

**Next Actions**
1. Permit duplicate UUID handshakes to close silently (or reuse the existing session) instead of emitting an `Error` frame so Asterisk does not abort the bridge.
2. Keep the UUID mapping in place until all legs have completed their handshakes, then proceed with provider processing once the primary connection remains.
3. Retry the regression after the duplicate-handshake guard is in place and ensure the first socket stays bound long enough for audio frames to reach the provider.

---
