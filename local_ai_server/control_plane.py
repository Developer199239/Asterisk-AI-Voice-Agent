from __future__ import annotations

import os
from dataclasses import replace
from typing import Any, Dict, List, Tuple

from config import LocalAIConfig


def apply_switch_model_request(
    config: LocalAIConfig, data: Dict[str, Any]
) -> Tuple[LocalAIConfig, List[str]]:
    changed: List[str] = []
    new_config = config

    if "stt_backend" in data:
        backend = (data["stt_backend"] or "").strip().lower()
        if backend in ("vosk", "sherpa", "kroko", "faster_whisper", "whisper_cpp"):
            new_config = replace(new_config, stt_backend=backend)
            changed.append(f"stt_backend={backend}")

    if "stt_model_path" in data:
        stt_path = data["stt_model_path"]
        if new_config.stt_backend == "sherpa":
            new_config = replace(new_config, sherpa_model_path=stt_path)
            changed.append(f"sherpa_model_path={os.path.basename(stt_path)}")
        elif new_config.stt_backend == "kroko":
            new_config = replace(new_config, kroko_model_path=stt_path)
            changed.append(f"kroko_model_path={os.path.basename(stt_path)}")
        else:
            new_config = replace(new_config, stt_model_path=stt_path)
            changed.append(f"stt_model_path={os.path.basename(stt_path)}")

    if "sherpa_model_path" in data:
        value = data["sherpa_model_path"]
        new_config = replace(new_config, sherpa_model_path=value)
        changed.append(f"sherpa_model_path={os.path.basename(value)}")

    if "kroko_model_path" in data:
        value = data["kroko_model_path"]
        new_config = replace(new_config, kroko_model_path=value)
        changed.append(f"kroko_model_path={os.path.basename(value)}")

    if "kroko_language" in data:
        value = data["kroko_language"]
        new_config = replace(new_config, kroko_language=value)
        changed.append(f"kroko_language={value}")

    if "kroko_url" in data:
        new_config = replace(new_config, kroko_url=data["kroko_url"])
        changed.append("kroko_url=updated")

    if "kroko_port" in data:
        try:
            port = int(data["kroko_port"])
            new_config = replace(new_config, kroko_port=port)
            changed.append(f"kroko_port={port}")
        except Exception:
            pass

    if "kroko_embedded" in data:
        raw = data["kroko_embedded"]
        if isinstance(raw, str):
            raw = raw.strip().lower() in ("1", "true", "yes", "y", "on")
        embedded = bool(raw)
        new_config = replace(new_config, kroko_embedded=embedded)
        changed.append(f"kroko_embedded={'1' if embedded else '0'}")

    if "llm_model_path" in data:
        value = data["llm_model_path"]
        new_config = replace(new_config, llm_model_path=value)
        changed.append(f"llm_model_path={os.path.basename(value)}")

    if "tts_backend" in data:
        backend = (data["tts_backend"] or "").strip().lower()
        if backend in ("piper", "kokoro", "melotts"):
            new_config = replace(new_config, tts_backend=backend)
            changed.append(f"tts_backend={backend}")

    if "tts_model_path" in data:
        value = data["tts_model_path"]
        if new_config.tts_backend == "piper":
            new_config = replace(new_config, tts_model_path=value)
            changed.append(f"tts_model_path={os.path.basename(value)}")
        else:
            new_config = replace(new_config, kokoro_model_path=value)
            changed.append(f"kokoro_model_path={os.path.basename(value)}")

    if "kokoro_voice" in data:
        value = data["kokoro_voice"]
        new_config = replace(new_config, kokoro_voice=value)
        changed.append(f"kokoro_voice={value}")

    if "kokoro_mode" in data:
        value = (data["kokoro_mode"] or "local").strip().lower()
        new_config = replace(new_config, kokoro_mode=value)
        changed.append(f"kokoro_mode={value}")

    if "kokoro_model_path" in data:
        value = data["kokoro_model_path"]
        new_config = replace(new_config, kokoro_model_path=value)
        changed.append(f"kokoro_model_path={os.path.basename(value)}")

    if "kokoro_api_base_url" in data:
        new_config = replace(new_config, kokoro_api_base_url=(data["kokoro_api_base_url"] or "").strip())
        changed.append("kokoro_api_base_url=updated")

    if "kokoro_api_key" in data:
        new_config = replace(new_config, kokoro_api_key=(data["kokoro_api_key"] or "").strip())
        changed.append("kokoro_api_key=updated")

    if "kokoro_api_model" in data:
        value = (data["kokoro_api_model"] or "model").strip()
        new_config = replace(new_config, kokoro_api_model=value)
        changed.append(f"kokoro_api_model={value}")

    return new_config, changed

