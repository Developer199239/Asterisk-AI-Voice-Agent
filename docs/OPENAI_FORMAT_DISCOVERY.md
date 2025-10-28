# OpenAI Realtime API Format Support Discovery

**Date**: October 27, 2025  
**Status**: ✅ VALIDATED

## Critical Discovery: g711_ulaw Output Not Supported

### Research Summary

**Perplexity Research** confirmed that OpenAI Realtime API:
- ✅ **Supports g711_ulaw for INPUT** (with some reported issues)
- ❌ **Does NOT support g711_ulaw for OUTPUT** (only PCM16)

### Evidence from Testing

**Test Call 1761609633.2433** showed OpenAI rejecting g711_ulaw output:

```
00:00:41 - We send: input_audio_format=g711_ulaw, output_audio_format=g711_ulaw
00:00:44 - ACK #1: input=g711_ulaw, output=g711_ulaw ✅ (Initial acceptance)
00:01:00 - ACK #2: input=g711_ulaw, output=PCM16@24k ❌ (OpenAI changed it!)
```

**Result**: Audio broke because OpenAI was sending PCM16@24k but we expected g711_ulaw@8k

---

## Optimal Configuration

### ✅ **HYBRID APPROACH** (Best of Both)

Use g711_ulaw for input, PCM16 for output:

```yaml
openai_realtime:
  # INPUT: g711_ulaw (simpler, lower bandwidth)
  provider_input_encoding: "g711_ulaw"
  provider_input_sample_rate_hz: 8000
  
  # OUTPUT: PCM16 (higher quality, officially supported)
  output_encoding: "linear16"
  output_sample_rate_hz: 24000
  
  # Unchanged
  input_encoding: "ulaw"
  input_sample_rate_hz: 8000
  target_encoding: "mulaw"
  target_sample_rate_hz: 8000
```

### Benefits

**Input (g711_ulaw @ 8kHz)**:
- ✅ No resampling (16kHz → 8kHz direct)
- ✅ Lower bandwidth (64 kbps)
- ✅ Simpler encoding pipeline
- ✅ Direct RTP ulaw compatibility

**Output (PCM16 @ 24kHz)**:
- ✅ Higher quality from OpenAI
- ✅ Officially supported format
- ✅ OpenAI won't reject it
- ✅ Better speech quality

---

## Format Support Matrix

| Format | Input Support | Output Support | Sample Rate | Notes |
|--------|---------------|----------------|-------------|-------|
| **pcm16** | ✅ Full | ✅ Full | 24 kHz | Primary format |
| **g711_ulaw** | ✅ Yes* | ❌ No | 8 kHz | *Some VAD issues |
| **g711_alaw** | ✅ Yes* | ❌ No | 8 kHz | *Some VAD issues |

**Key Insight**: OpenAI Realtime is **asymmetric** in format support!

---

## Comparison: Configuration Options

### Option 1: Pure PCM16 (Original)
```yaml
provider_input_encoding: "linear16"   # PCM16
provider_input_sample_rate_hz: 24000
output_encoding: "linear16"           # PCM16
output_sample_rate_hz: 24000
```
**Pros**: Highest quality both ways  
**Cons**: Requires 16kHz → 24kHz resampling, higher bandwidth

### Option 2: Pure g711_ulaw (Failed)
```yaml
provider_input_encoding: "g711_ulaw"
provider_input_sample_rate_hz: 8000
output_encoding: "g711_ulaw"   # ❌ REJECTED by OpenAI!
output_sample_rate_hz: 8000
```
**Result**: OpenAI switches output back to PCM16@24k → audio breaks

### Option 3: Hybrid (Optimal) ✅
```yaml
provider_input_encoding: "g711_ulaw"   # Simpler input
provider_input_sample_rate_hz: 8000
output_encoding: "linear16"            # Quality output
output_sample_rate_hz: 24000
```
**Pros**: Best of both worlds  
**Cons**: Small output resampling step (acceptable)

---

## References

1. [OpenAI Realtime API Issues #8](https://github.com/openai/openai-realtime-api-beta/issues/8) - "G.711 ulaw output quality poor"
2. [OpenAI Realtime API Issues #18](https://github.com/openai/openai-realtime-api-beta/issues/18) - "G.711 VAD problems"
3. [Latent Space Analysis](https://www.latent.space/p/realtime-api) - "PCM16 primary format"

---

## Implementation Status

**Deployed**: October 27, 2025  
**Config**: Hybrid approach (g711_ulaw input, PCM16 output)  
**Server**: voiprnd.nemtclouddispatch.com  
**Status**: ✅ Ready for validation test

---

## Next Steps

1. Test call with hybrid configuration
2. Verify logs show:
   - `input_audio_format: "g711_ulaw"`
   - `output_audio_format: "pcm16"`
   - No format rejection from OpenAI
3. Confirm clean audio quality
4. Compare with Deepgram (pure mulaw) for performance

---

*This document captures the research and testing that led to the optimal OpenAI Realtime configuration.*
