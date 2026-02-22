# Community Test Matrix — Local AI Server

Help us build the definitive reference for what works best when running AAVA fully local.
Submit your results via [GitHub Issue](https://github.com/hkjarral/Asterisk-AI-Voice-Agent/issues/new?template=local-ai-test-result.md) or PR to this file.

---

## How to Contribute

1. **Run a test call** using a Local AI Server configuration (any STT + TTS + LLM combination).
2. **Record your results** using the template below or the GitHub issue template.
3. **Submit** a PR adding a row to the results table, or open an issue with the `community-test` label.

### What to Measure

- **STT Latency**: Time from end of speech to transcript appearing in logs.
- **LLM Latency**: Time from transcript to first LLM token (check `local_ai_server` logs for `[LLM]` timing).
- **TTS Latency**: Time from LLM response to first audio byte.
- **End-to-End**: Perceived time from user stops speaking to hearing the AI reply.
- **Call Quality**: Subjective 1-5 rating (1 = unusable, 5 = indistinguishable from cloud).

---

## Backend Compatibility Quick Reference

| Backend | Type | CPU | GPU | Build Arg | Approx Size | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| Vosk | STT | Good | No benefit | `INCLUDE_VOSK=true` (default) | 50-200 MB | Best CPU STT; real-time streaming |
| Sherpa-ONNX | STT | Good | No benefit | `INCLUDE_SHERPA=true` (default) | 30-150 MB | Streaming; good multi-language |
| Kroko Cloud | STT | Yes | Yes | N/A | 0 | Requires API key at kroko.ai |
| Kroko Embedded | STT | Yes | Yes | `INCLUDE_KROKO_EMBEDDED=true` | ~100 MB | Self-hosted ONNX server |
| Faster-Whisper | STT | Slow | Recommended | `INCLUDE_FASTER_WHISPER=true` | 75-3000 MB | Auto-downloads from HuggingFace |
| Whisper.cpp | STT | Slow | Good | `INCLUDE_WHISPER_CPP=true` | 75-3000 MB | Manual model download |
| Piper | TTS | Good | No benefit | `INCLUDE_PIPER=true` (default) | 15-60 MB | Best CPU TTS; ONNX voices |
| Kokoro | TTS | OK | Better | `INCLUDE_KOKORO=true` (default) | ~200 MB | Higher quality; multi-voice |
| MeloTTS | TTS | OK | Better | `INCLUDE_MELOTTS=true` | ~500 MB | Multi-accent English |
| llama.cpp | LLM | Not recommended | Required | `INCLUDE_LLAMA=true` (default) | 2-8 GB | CPU: 10-30s/response |

---

## Community Results

### Legend

- **E2E**: End-to-end perceived latency (user stops speaking → hears reply)
- **Quality**: Subjective 1-5 (1=unusable, 3=usable, 5=cloud-quality)
- **Transport**: `em` = ExternalMedia RTP, `as` = AudioSocket

### Results Table

<!-- APPEND YOUR RESULTS HERE — one row per test configuration -->

| Date | Contributor | Hardware | GPU | STT Backend | STT Model | TTS Backend | TTS Voice | LLM Model | LLM Context | Transport | E2E Latency | Quality | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2025-07-14 | @maintainer | Vast.ai A100 40GB | A100 | vosk | en-us-0.22 | piper | lessac-medium | phi-3-mini Q4_K_M | 2048 | em | ~2s | 3 | Baseline GPU test |
| 2025-07-14 | @maintainer | Vast.ai A100 40GB | A100 | faster_whisper | base | kokoro | af_heart | phi-3-mini Q4_K_M | 2048 | em | ~1.5s | 4 | Whisper + Kokoro combo |
| | | | | | | | | | | | | | |

---

## Submission Template

Use this when adding a row or opening an issue:

```
**Date**: YYYY-MM-DD
**Hardware**: e.g., "Ryzen 7 5800X, 32GB RAM" or "Vast.ai RTX 4090 24GB"
**GPU**: e.g., "RTX 4090 24GB" or "None (CPU only)"
**STT**: Backend + model (e.g., "vosk / en-us-0.22" or "faster_whisper / base")
**TTS**: Backend + voice (e.g., "piper / lessac-medium" or "kokoro / af_heart")
**LLM**: Model + context (e.g., "phi-3-mini Q4_K_M / n_ctx=2048") or "Cloud (GPT-4o)"
**Transport**: ExternalMedia RTP or AudioSocket
**Pipeline**: local_only / local_hybrid / other
**E2E Latency**: Approximate (e.g., "~2s", "3-5s")
**Quality (1-5)**: Your rating
**Notes**: Any observations (echo issues, model switching behavior, etc.)
```

---

## FAQ

**Q: How do I measure latency?**
Set `LOCAL_LOG_LEVEL=DEBUG` and check timestamps in `docker compose logs local_ai_server`. Look for:
- `STT result` → transcript timestamp
- `LLM response` → first token timestamp
- `TTS audio` → first byte timestamp

**Q: What pipeline should I use?**
- `local_only`: All local (STT + LLM + TTS). Requires GPU for usable LLM latency.
- `local_hybrid`: Local STT + TTS, cloud LLM (e.g., GPT-4o). Best quality on CPU.

**Q: Can I test from a different machine?**
Yes — set up split-host mode. See `docs/LOCAL_ONLY_SETUP.md` for details on configuring `LOCAL_WS_HOST=0.0.0.0` with `LOCAL_WS_AUTH_TOKEN`.
