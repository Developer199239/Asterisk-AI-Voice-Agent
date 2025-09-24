# Milestone 6 — OpenAI Realtime Voice Agent Integration

## Objective
Add first-class support for OpenAI’s Realtime voice agents so users can swap between Deepgram and OpenAI using configuration only. Reuse the AudioSocket architecture and streaming transport from Milestone 5.

## Success Criteria
- `config/ai-agent.yaml` can set `default_provider: openai_realtime` and a regression call completes with clear two-way conversation.
- Provider exposes codec/sample-rate metadata so the streaming manager automatically resamples to the configured `audiosocket.format`.
- Regression documentation includes an OpenAI voice call walkthrough with logs, metrics, and tuning guidance.

## Dependencies
- Milestone 5 complete (streaming transport production-ready).
- OpenAI API credentials available in `.env` / environment variables.

## Work Breakdown

### 6.1 Provider Implementation
- Create `src/providers/openai_realtime.py` implementing `AIProviderInterface`.
- Establish the Realtime session (WebRTC or WebSocket) suitable for server-side telephony. Document chosen transport in the provider docstring.
- Map inbound audio frames to OpenAI’s streaming input API; handle partial transcripts and final responses.
- Emit `ProviderEvent` objects consistent with Deepgram (`AgentAudio`, `AgentAudioDone`, transcripts).

### 6.2 Configuration & Secrets
- Extend provider section in `config/ai-agent.yaml` with an `openai_realtime` block (API key env reference, voice preset, model name, sample rate, codec expectations).
- Update `src/config.py` with Pydantic models and validation.
- Document required env vars in `README.md` / `docs/Architecture.md` (e.g., `OPENAI_API_KEY`).

### 6.3 Codec & Transport Alignment
- Ensure provider returns metadata (encoding, sample rate) to `StreamingPlaybackManager` and VAD.
- Add automated downsampling/up-sampling or µ-law conversion as necessary.
- Add regression assertions verifying that AudioSocket transport receives the correct frame size.

### 6.4 Regression & Documentation
- Create `docs/regressions/openai-call-framework.md` mirroring the Deepgram guide (call steps, log snippets, metrics).
- Update `call-framework.md` with an OpenAI regression section and checklist.
- Update `docs/ROADMAP.md` and `docs/Architecture.md` to reflect OpenAI support.

## Deliverables
- New provider module, config schemas, and tests.
- Updated documentation (roadmap, architecture, regression guide, README env vars).
- Regression log capturing a successful OpenAI call (call ID, duration, audio quality notes).

## Verification Checklist
- Switching `default_provider` between `deepgram` and `openai_realtime` works without restarting containers beyond the standard reload.
- Logs show `OpenAI Realtime session started` and streaming metrics identical to Deepgram baseline.
- `/metrics` includes provider label `openai_realtime` for turn/latency gauges.

## Handover Notes
- Coordinate with Milestone 7 (pipeline configurability). Ensure provider metadata is compatible with the new pipeline abstraction.
- Flag any API limitations (e.g., token quotas) in the regression doc for future optimization.
