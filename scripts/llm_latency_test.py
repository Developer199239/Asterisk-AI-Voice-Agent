"""Measure latency of the local LLM via the pipeline adapters.

Usage (from project root):

    make llm-latency

The Makefile target runs this script inside the ai-engine container so the
measurement reflects the same environment that serves live traffic.
"""

import asyncio
import statistics
import time
from typing import List

from src.config import load_config, LocalProviderConfig
from src.logging_config import configure_logging
from src.pipelines.local import LocalLLMAdapter

PROMPTS = [
    "Hello there, can you hear me?",
    "Can you summarize our next steps?",
    "Explain what this service can do in two sentences."
]


async def measure_once(adapter: LocalLLMAdapter, call_id: str, prompt: str) -> tuple[float, str]:
    context = {"messages": [{"role": "user", "content": prompt}]}
    options = {"response_timeout_sec": 120.0}
    started = time.perf_counter()
    response = await adapter.generate(call_id, prompt, context, options)
    latency_ms = (time.perf_counter() - started) * 1000.0
    return latency_ms, response


async def main() -> None:
    configure_logging()
    config = load_config()
    provider_cfg = LocalProviderConfig(**config.providers["local"])

    adapter = LocalLLMAdapter("local_llm_latency", config, provider_cfg, {"mode": "llm"})
    await adapter.start()
    call_id = "latency-check"
    await adapter.open_call(call_id, {"mode": "llm"})

    latencies: List[float] = []
    try:
        for prompt in PROMPTS:
            latency_ms, response_text = await measure_once(adapter, call_id, prompt)
            latencies.append(latency_ms)
            print(f"Prompt: {prompt!r} -> {latency_ms:.2f} ms")
            print(f"Response: {response_text}\n")
    finally:
        await adapter.close_call(call_id)
        await adapter.stop()

    if latencies:
        print("--- Summary ---")
        print(f"Samples: {len(latencies)}")
        print(f"Min: {min(latencies):.2f} ms")
        print(f"Max: {max(latencies):.2f} ms")
        print(f"Mean: {statistics.mean(latencies):.2f} ms")
        if len(latencies) > 1:
            print(f"Std Dev: {statistics.pstdev(latencies):.2f} ms")


if __name__ == "__main__":
    asyncio.run(main())
