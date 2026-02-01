"""
Debug trace helpers for HTTP tools.

These utilities are intentionally lightweight and provider-agnostic: they only
help HTTP tools emit useful request/response context when LOG_LEVEL=debug.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, Mapping, Optional


_ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
_BRACE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def debug_enabled(logger: logging.Logger) -> bool:
    return bool(logger and logger.isEnabledFor(logging.DEBUG))


def preview(value: Any, *, limit: int = 4096) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, bytes):
            s = value.decode("utf-8", errors="replace")
        else:
            s = str(value)
    except Exception:
        s = "<unprintable>"
    if limit and len(s) > limit:
        return s[:limit] + "…"
    return s


def extract_used_env_vars(*templates: Optional[str]) -> list[str]:
    names: set[str] = set()
    for t in templates:
        if not t:
            continue
        for m in _ENV_PATTERN.finditer(t):
            names.add(m.group(1))
    return sorted(names)


def extract_used_brace_vars(*templates: Optional[str]) -> list[str]:
    names: set[str] = set()
    for t in templates:
        if not t:
            continue
        for m in _BRACE_PATTERN.finditer(t):
            names.add(m.group(1))
    return sorted(names)


def build_var_snapshot(
    *,
    used_brace_vars: Iterable[str],
    used_env_vars: Iterable[str],
    values: Mapping[str, Any],
    env: Mapping[str, str],
) -> Dict[str, Any]:
    brace: Dict[str, Any] = {}
    for name in used_brace_vars:
        try:
            brace[name] = values.get(name)
        except Exception:
            brace[name] = None

    envs: Dict[str, Any] = {}
    for name in used_env_vars:
        try:
            envs[name] = env.get(name)
        except Exception:
            envs[name] = None

    return {"vars": brace, "env": envs}

