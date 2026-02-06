from __future__ import annotations

from typing import Any, Dict, Optional

import structlog
from jinja2.sandbox import SandboxedEnvironment

logger = structlog.get_logger(__name__)

_ENV = SandboxedEnvironment(autoescape=False)


def _normalize_template(raw: Any) -> Optional[str]:
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    return s or None


def render_html_template(
    *,
    html_template: str,
    variables: Dict[str, Any],
) -> str:
    if not isinstance(html_template, str):
        raise TypeError("html_template must be a string")
    if len(html_template) > 200_000:
        raise ValueError("html_template too large")
    template = _ENV.from_string(html_template)
    return template.render(**(variables or {}))


def render_html_template_with_fallback(
    *,
    template_override: Any,
    default_template: str,
    variables: Dict[str, Any],
    call_id: str,
    tool_name: str,
) -> str:
    override = _normalize_template(template_override)
    if override:
        try:
            return render_html_template(html_template=override, variables=variables)
        except Exception as e:
            logger.warning(
                "Email template override render failed; falling back to default",
                call_id=call_id,
                tool=tool_name,
                error=str(e),
            )
    return render_html_template(html_template=default_template, variables=variables)

