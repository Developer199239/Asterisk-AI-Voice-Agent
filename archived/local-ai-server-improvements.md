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

