# LLM Warmup Process Explained

## Overview

The **LLM warmup** is a startup latency test that runs automatically when the `local-ai-server` container boots up. It measures how long the first LLM inference takes and serves multiple purposes.

---

## Bootup Sequence

When the local AI server starts, it follows this exact order:

```
1. Load STT model (Vosk)           → ~5-15 seconds
2. Load LLM model (Llama)          → ~10-30 seconds
3. Run warmup latency check        → ~60-180 seconds ⏰
4. Load TTS model (Piper)          → ~2-5 seconds
5. Start WebSocket server          → Ready for calls
```

The warmup happens at **step 3**, after the LLM is loaded into memory.

---

## What Happens During Warmup

### Step-by-Step Process

#### 1. **LLM Model Loading** (lines 254-279)
```python
self.llm_model = Llama(
    model_path=self.llm_model_path,      # 7.3GB file for Llama-2-13B
    n_ctx=self.llm_context,              # Context window: 512 tokens
    n_threads=self.llm_threads,          # CPU threads: 16
    n_batch=self.llm_batch,              # Batch size: 512
    use_mmap=True,                       # Memory-map the file
    use_mlock=self.llm_use_mlock,        # Pin to RAM (prevent swap)
)
```

**What's happening:**
- Reads the 7.3GB GGUF model file from disk
- Memory-maps it (reads file directly from disk without loading to RAM fully)
- If `use_mlock=1`: Pins it to physical RAM to prevent OS from swapping
- Allocates context buffer (512 tokens × embedding size)
- Initializes KV cache for attention mechanism

**Time**: 10-30 seconds depending on disk I/O

---

#### 2. **Warmup Test Trigger** (line 222)
```python
await self.run_startup_latency_check()
```

After the model is loaded, the warmup test begins.

---

#### 3. **Test Prompt Creation** (lines 290-294)
```python
session = SessionContext(call_id="startup-latency")
sample_text = "Hello, can you hear me?"
prompt, prompt_tokens, truncated, raw_tokens = self._prepare_llm_prompt(
    session, sample_text
)
```

**What it does:**
- Creates a fake session with sample user input
- Builds a full prompt with system message + user message
- Counts tokens in the prompt (~47 tokens for this test)

**Example prompt sent to LLM:**
```
<|system|>
You are a helpful AI voice assistant. Respond naturally and conversationally to the caller.
