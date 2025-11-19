# Deepgram Provider Implementation

Technical implementation for Deepgram Voice Agent integration.

## Overview

**File**: `src/providers/deepgram.py`

Deepgram Voice Agent: Monolithic real-time streaming with built-in STT, LLM, and TTS.

## Configuration

```yaml
provider_name: deepgram
deepgram:
  api_key: ${DEEPGRAM_API_KEY}
  model: aura-asteria-en
  encoding: linear16
  sample_rate: 16000
  agent:
    listen:
      model: nova-2
    think:
      provider:
        type: open_ai
      model: gpt-4
      functions: []  # Tool schemas
    speak:
      model: aura-asteria-en
```

## Function Calling (Critical)

### Field Name
**Use `functions` not `tools`**:

```python
# ✅ CORRECT (Deepgram):
agent.think.functions = [...]

# ❌ WRONG (OpenAI naming):
agent.think.tools = [...]
```

### Event Type
**Use exact string `FunctionCallRequest`**:

```python
# ✅ CORRECT:
elif event_type == "FunctionCallRequest"

# ❌ WRONG:
elif event_type == "function_call"
```

### Schema Format

Direct array, no type wrapper:

```python
[{
    "name": "transfer",
    "description": "Transfer call",
    "parameters": {
        "type": "object",
        "properties": {
            "destination": {"type": "string"}
        }
    }
}]
```

## Audio Formats

**Recommended**: `linear16` @ `16000` (matches internal format, no transcoding)

**Alternative**: `mulaw` @ `8000` (telephony-native)

## Key Events

- `FunctionCallRequest`: Tool invocation
- `UserStartedSpeaking`: User speech detected
- `AgentAudioDone`: Response complete
- `ConversationText`: Transcript

## Common Issues

**Low RMS Warnings**: Natural silence, can filter in logging config

**Function Call Timeout**: Send `FunctionCallResponse` within 10 seconds

**Format Mismatch**: Match yaml config to actual audio encoding

## References

- Deepgram Docs: https://developers.deepgram.com/docs/voice-agents-function-calling
- User Setup: `docs/Provider-Deepgram-Setup.md` (to be created)
