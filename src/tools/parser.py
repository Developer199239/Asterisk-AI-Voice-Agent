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

# Alternative patterns for fallback parsing
FUNCTOOLS_PATTERN = re.compile(
    r'functools\[(\[.*?\])\]',
    re.DOTALL | re.IGNORECASE
)

JSON_FUNCTION_PATTERN = re.compile(
    r'\{\s*"function"\s*:\s*"([^"]+)"\s*,\s*"function_parameters"\s*:\s*(\{.*?\})\s*\}',
    re.DOTALL
)


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
    
    # Remove functools[...] blocks
    clean = FUNCTOOLS_PATTERN.sub('', clean)
    
    # Remove {"function": ...} blocks
    clean = JSON_FUNCTION_PATTERN.sub('', clean)
    
    # Clean up extra whitespace
    clean = re.sub(r'\n\s*\n', '\n', clean)
    clean = clean.strip()
    
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
