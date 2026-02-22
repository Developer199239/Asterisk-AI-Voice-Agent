"""
Tool call parser for local LLMs.

Parses LLM responses to extract tool calls in the format:
<tool_call>
{"name": "tool_name", "arguments": {"param": "value"}}
</tool_call>

This is model-agnostic and works with any LLM that can output structured text.
"""

import re
import json
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# Pattern to match tool calls in LLM output
TOOL_CALL_PATTERN = re.compile(
    r'<tool_call>\s*(\{.*?\})\s*</tool_call>',
    re.DOTALL | re.IGNORECASE
)

# Some models occasionally wrap tool calls in a tag named after the tool, e.g.
# <hangup_call>{...}</hangup_call>. We treat these as tool calls too, but the
# caller should validate allowlisted tool names before executing anything.
NAMED_TOOL_CALL_PATTERN = re.compile(
    r'<(?P<tag>[a-zA-Z0-9_]+)>\s*(?P<json>\{.*?\})\s*</(?P=tag)>',
    re.DOTALL
)

# Sometimes models emit a malformed wrapper where they start with the closing
# tag (e.g., `</tool_call> {...}`) or omit the closing tag entirely. We'll try
# to recover a JSON object adjacent to either tag.
TOOL_CALL_TAG_PATTERN = re.compile(
    r'</?tool_call>',
    re.IGNORECASE
)

# Alternative patterns for fallback parsing
FUNCTOOLS_PATTERN = re.compile(
    r'functools\[(\[.*?\])\]',
    re.DOTALL | re.IGNORECASE
)

JSON_FUNCTION_PATTERN = re.compile(
    r'\{\s*"function"\s*:\s*"([^"]+)"\s*,\s*"function_parameters"\s*:\s*(\{.*?\})\s*\}',
    re.DOTALL
)

_CONTROL_TOKEN_PREFIXES = ("<|system|>", "<|user|>", "<|assistant|>", "<|enduser|>", "<|end|>")


def _extract_json_object(text: str, start_index: int) -> Optional[Tuple[str, int]]:
    """
    Extract the first JSON object starting at or after start_index.

    Returns (json_string, end_index_exclusive) or None.
    """
    if not text:
        return None
    n = len(text)
    i = start_index
    while i < n and text[i] != "{":
        i += 1
    if i >= n:
        return None

    depth = 0
    in_string = False
    escape = False
    for j in range(i, n):
        ch = text[j]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1], j + 1

    return None


def _strip_control_tokens(text: str) -> str:
    """
    Remove common chat-template control tokens that occasionally leak into outputs.
    """
    if not text:
        return text
    # If a control token appears, truncate at its first occurrence to avoid speaking garbage.
    lowest = None
    for token in _CONTROL_TOKEN_PREFIXES:
        idx = text.find(token)
        if idx != -1:
            lowest = idx if lowest is None else min(lowest, idx)
    if lowest is not None:
        text = text[:lowest]
    return text.strip()


def parse_tool_calls(response: str) -> List[Dict[str, Any]]:
    """
    Extract tool calls from LLM response.
    
    Supports multiple formats:
    1. <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    2. functools[{"name": "...", "arguments": {...}}]
    3. {"function": "...", "function_parameters": {...}}
    
    Args:
        response: Raw LLM response text
        
    Returns:
        List of tool call dictionaries with 'name' and 'parameters' keys
    """
    tool_calls = []
    
    # Try primary format: <tool_call>...</tool_call>
    matches = TOOL_CALL_PATTERN.findall(response)
    for match in matches:
        try:
            tool_data = json.loads(match)
            if "name" in tool_data:
                tool_calls.append({
                    "name": tool_data["name"],
                    "parameters": tool_data.get("arguments", tool_data.get("parameters", {}))
                })
                logger.debug(
                    "Parsed tool call (primary format): tool=%s params=%s",
                    tool_data["name"],
                    tool_data.get("arguments", {})
                )
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse tool call JSON: %s", e)
            continue
    
    if tool_calls:
        return tool_calls

    # Try named-tag format: <hangup_call>{...}</hangup_call>
    # Note: This is a best-effort fallback. Downstream must validate tool names.
    for tag, json_str in NAMED_TOOL_CALL_PATTERN.findall(response):
        if tag.lower() == "tool_call":
            continue
        try:
            tool_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse named tool call JSON: %s", e)
            continue

        name = tool_data.get("name") or tag
        parameters = tool_data.get("arguments") or tool_data.get("parameters")
        if parameters is None:
            # Allow compact forms like: <hangup_call>{"farewell_message":"Bye"}</hangup_call>
            parameters = {k: v for k, v in tool_data.items() if k != "name"}

        tool_calls.append({
            "name": name,
            "parameters": parameters if isinstance(parameters, dict) else {},
        })
        logger.debug(
            "Parsed tool call (named tag): tool=%s tag=%s params=%s",
            name,
            tag,
            parameters if isinstance(parameters, dict) else {},
        )

    if tool_calls:
        return tool_calls

    # Try malformed tool_call tags (e.g., `</tool_call> {...}` or `<tool_call> {...}` without close).
    try:
        for match in TOOL_CALL_TAG_PATTERN.finditer(response or ""):
            extracted = _extract_json_object(response, match.end())
            if not extracted:
                continue
            json_str, _end = extracted
            try:
                tool_data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            if isinstance(tool_data, dict) and "name" in tool_data:
                tool_calls.append({
                    "name": tool_data["name"],
                    "parameters": tool_data.get("arguments", tool_data.get("parameters", {})),
                })
                logger.debug(
                    "Parsed tool call (adjacent tag): tool=%s params=%s",
                    tool_data.get("name"),
                    tool_data.get("arguments", {}),
                )
    except Exception:
        # Defensive: never let parsing crash the engine.
        pass

    if tool_calls:
        return tool_calls
    
    # Try functools format: functools[{...}]
    functools_matches = FUNCTOOLS_PATTERN.findall(response)
    for match in functools_matches:
        try:
            tools_list = json.loads(match)
            if isinstance(tools_list, list):
                for tool_data in tools_list:
                    if "name" in tool_data:
                        tool_calls.append({
                            "name": tool_data["name"],
                            "parameters": tool_data.get("arguments", {})
                        })
        except json.JSONDecodeError:
            continue
    
    if tool_calls:
        return tool_calls
    
    # Try function format: {"function": "...", "function_parameters": {...}}
    func_matches = JSON_FUNCTION_PATTERN.findall(response)
    for func_name, params_str in func_matches:
        try:
            params = json.loads(params_str)
            tool_calls.append({
                "name": func_name,
                "parameters": params
            })
        except json.JSONDecodeError:
            continue
    
    return tool_calls


def extract_text_without_tools(response: str) -> str:
    """
    Remove tool call markers from response and return clean text.
    
    Args:
        response: Raw LLM response with potential tool calls
        
    Returns:
        Clean text suitable for TTS
    """
    # Remove <tool_call>...</tool_call> blocks
    clean = TOOL_CALL_PATTERN.sub('', response)

    # Remove <tool_name>...</tool_name> blocks with embedded JSON
    clean = NAMED_TOOL_CALL_PATTERN.sub('', clean)

    # Remove stray tool_call tags and any adjacent JSON object.
    try:
        while True:
            m = TOOL_CALL_TAG_PATTERN.search(clean)
            if not m:
                break
            # Remove tag itself.
            start = m.start()
            end = m.end()
            # Also remove an immediate JSON object if present.
            extracted = _extract_json_object(clean, end)
            if extracted:
                _json_str, json_end = extracted
                clean = clean[:start] + clean[json_end:]
            else:
                clean = clean[:start] + clean[end:]
    except Exception:
        pass
    
    # Remove functools[...] blocks
    clean = FUNCTOOLS_PATTERN.sub('', clean)
    
    # Remove {"function": ...} blocks
    clean = JSON_FUNCTION_PATTERN.sub('', clean)
    
    # Clean up extra whitespace
    clean = re.sub(r'\n\s*\n', '\n', clean)
    clean = clean.strip()

    # Finally, strip leaked chat-template control tokens.
    clean = _strip_control_tokens(clean)
    
    return clean


def parse_response_with_tools(response: str) -> Tuple[Optional[str], Optional[List[Dict]]]:
    """
    Parse LLM response and separate text from tool calls.
    
    Args:
        response: Raw LLM response
        
    Returns:
        Tuple of (clean_text, tool_calls)
        - clean_text: Text suitable for TTS (None if empty)
        - tool_calls: List of tool call dicts (None if no tools)
    """
    tool_calls = parse_tool_calls(response)
    clean_text = extract_text_without_tools(response)
    
    return (
        clean_text if clean_text else None,
        tool_calls if tool_calls else None
    )


def validate_tool_call(tool_call: Dict[str, Any], available_tools: List[str]) -> bool:
    """
    Validate that a tool call references a known tool.
    
    Args:
        tool_call: Tool call dictionary with 'name' key
        available_tools: List of valid tool names
        
    Returns:
        True if valid, False otherwise
    """
    name = tool_call.get("name", "")
    if name not in available_tools:
        logger.warning(
            "Unknown tool in LLM response: %s (available: %s)",
            name,
            available_tools
        )
        return False
    return True
