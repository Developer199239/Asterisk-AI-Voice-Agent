# Tuning Recipes

Quick, copy-pasteable presets for common deployment scenarios. Adjust to suit your trunks and network.

See also: `docs/Configuration-Reference.md` for detailed option effects and ranges.

## Quiet office lines (sensitive, responsive)

```yaml
barge_in:
  enabled: true
  initial_protection_ms: 300
  min_ms: 280
  energy_threshold: 1200
  cooldown_ms: 800
  post_tts_end_protection_ms: 250

streaming:
  jitter_buffer_ms: 90
  min_start_ms: 280
  low_watermark_ms: 180
```

Why: Lower energy threshold and min_ms make barge-in more responsive. Keep jitter and warm-up modest.

## Noisy call center (robust, less false triggers)

```yaml
barge_in:
  enabled: true
  initial_protection_ms: 400
  min_ms: 450
  energy_threshold: 2200
  cooldown_ms: 1200
  post_tts_end_protection_ms: 300

vad:
  webrtc_aggressiveness: 1
  webrtc_end_silence_frames: 35
  min_utterance_duration_ms: 2600

streaming:
  jitter_buffer_ms: 140
  min_start_ms: 350
  low_watermark_ms: 240
```

Why: Higher thresholds reduce false barge-ins; larger buffers handle jitter; slightly longer utterances improve STT.

## Lowest latency (more sensitive to jitter/echo)

```yaml
barge_in:
  enabled: true
  initial_protection_ms: 250
  min_ms: 280
  energy_threshold: 1400
  cooldown_ms: 600
  post_tts_end_protection_ms: 250

streaming:
  jitter_buffer_ms: 80
  min_start_ms: 250
  low_watermark_ms: 160
```

Why: Minimal buffering and faster barge-in. Expect higher risk of underruns and occasional self-echo on some trunks.

## Stability-first (tolerant, slightly higher latency)

```yaml
barge_in:
  enabled: true
  initial_protection_ms: 450
  min_ms: 500
  energy_threshold: 2000
  cooldown_ms: 1200
  post_tts_end_protection_ms: 300

streaming:
  jitter_buffer_ms: 150
  min_start_ms: 380
  low_watermark_ms: 260
  provider_grace_ms: 600
```

Why: Larger buffers and conservative barge-in minimize glitches at the cost of slightly slower starts.

## OpenAI Realtime server-side turn detection

Enable on the provider to improve turn-taking (optional):

```yaml
providers:
  openai_realtime:
    # ...
    turn_detection:
      type: "server_vad"
      silence_duration_ms: 200
      threshold: 0.5
      prefix_padding_ms: 200
```

Use with or without local VAD. If both run, prefer conservative local VAD (e.g., longer end-silence) to avoid clashes.

## Streaming vs file playback

- `downstream_mode: stream`: best UX, requires stable network; tune `streaming.*` buffers.
- `downstream_mode: file`: more tolerant to jitter and provider hiccups, at the cost of response latency.
