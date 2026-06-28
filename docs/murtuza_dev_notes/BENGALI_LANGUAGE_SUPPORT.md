# Bengali Language Support — Implementation Report

**Date:** 2026-06-24  
**Status:** Planned (not yet implemented)  
**Current state:** All contexts use English (Deepgram Aura-2 English TTS)

---

## Problem Statement

The system prompt–based language detection ("detect caller language and respond in kind") does **not work** with the Deepgram Voice Agent provider. The root cause is not the LLM — GPT-4o-mini can generate Bengali text correctly — but the **TTS engine** (Deepgram Aura-2), which is English-only and cannot pronounce Bengali.

---

## Deepgram Compatibility with Bengali

| Component | Provider | Bengali Support | Notes |
|---|---|---|---|
| STT (Speech-to-Text) | Deepgram nova-3 | ✅ Yes | Can transcribe Bengali speech using `language: bn` |
| LLM | GPT-4o-mini (OpenAI) | ✅ Yes | Generates correct Bengali text |
| TTS (Text-to-Speech) | Deepgram Aura-2 | ❌ No | English-only voices — Bengali text will sound broken/garbled |

**Conclusion:** Deepgram full-agent provider cannot support Bengali voice output. The STT half works, but the TTS half blocks full Bengali support.

---

## Implementation Plan (Future)

### Phase 1 — Switch Bengali contexts to Google Gemini Live

Google Gemini Live supports Bengali end-to-end (STT + LLM + TTS).

**Contexts to switch:**
- `default` (appointment booking — patient-facing, Bengali callers)
- `ivr_main` (main IVR — first contact)

**Config change in `config/ai-agent.local.yaml`:**

```yaml
contexts:
  default:
    provider: google_live    # change from: deepgram
    # ... rest of config unchanged

  ivr_main:
    provider: google_live    # change from: deepgram
    # ... rest of config unchanged
```

**Google Gemini Live Bengali TTS voice:**
- Language code: `bn-BD` (Bangladesh Bengali) or `bn-IN` (India Bengali)
- Configure under Google provider settings once switched

---

### Phase 2 (Alternative) — Pipeline Mode

If Google Gemini Live is not preferred, use pipeline (separate STT + LLM + TTS) mode:

```yaml
pipelines:
  default_pipeline:
    stt_provider: deepgram
    stt_language: bn-BD
    llm_provider: openai
    llm_model: gpt-4o-mini
    tts_provider: google
    tts_language: bn-BD
    tts_voice: bn-BD-Standard-A   # or bn-BD-Wavenet-A for better quality
```

Pipeline mode gives more control but adds latency (~300–500ms extra per turn) compared to full-agent providers.

---

### Phase 3 — Prompt Update for Fixed Bengali

Once TTS supports Bengali, remove the dynamic language detection block and replace with a fixed rule:

```
LANGUAGE RULE:
Always respond in Bengali (বাংলা).
If the caller speaks in English, still respond in Bengali.
Exception: if the caller explicitly asks you to switch to English, switch immediately and stay in English for that call.
```

---

## Revert Plan (Back to English)

To revert to the current English-only setup after Bengali testing:

1. Change `provider: google_live` back to `provider: deepgram` in affected contexts
2. Remove or comment out the LANGUAGE DETECTION block from prompts
3. Restart engine: `docker compose restart ai_engine`

The English prompts are preserved in git history — run `git diff main` to see the full diff if needed.

---

## Current Workaround (Not Recommended)

Setting `agent_language: "bn"` in the Deepgram provider config will make STT understand Bengali speech better, but TTS output will still be English-accented and unnatural for Bengali listeners.

```yaml
# In ai-agent.local.yaml — providers section
providers:
  deepgram:
    enabled: true
    agent_language: "bn"   # STT only — TTS still broken
```

This is **not suitable** for production use with Bengali-speaking patients.

---

## Summary

| Approach | Bengali STT | Bengali TTS | Latency | Effort |
|---|---|---|---|---|
| Deepgram (current) | ✅ with `language: bn` | ❌ Not supported | Low | — |
| Google Gemini Live | ✅ | ✅ | Low | Change `provider:` key |
| Pipeline (Deepgram STT + Google TTS) | ✅ | ✅ | Medium (+300ms) | More config changes |

**Recommended path:** Switch to `google_live` provider for Bengali contexts. Lowest effort, full Bengali support.

---

## Files to Modify When Implementing

| File | Change |
|---|---|
| `config/ai-agent.local.yaml` | Change `provider: deepgram` → `provider: google_live` for `default` and `ivr_main` contexts; add Bengali language config |
| `config/ai-agent.local.yaml` | Replace LANGUAGE DETECTION block with fixed Bengali rule in prompt |
| `.env` | Ensure `GOOGLE_API_KEY` is set (needed for Gemini Live) |
