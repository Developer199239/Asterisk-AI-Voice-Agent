"""
Tools API endpoints for testing HTTP tools before saving.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import httpx
import re
import os
import logging
import time

router = APIRouter()
logger = logging.getLogger(__name__)

# Default test values for template variables
DEFAULT_TEST_VALUES = {
    "caller_number": "+15551234567",
    "called_number": "+18005551234",
    "caller_name": "Test Caller",
    "caller_id": "+15551234567",
    "call_id": "1234567890.123",
    "context_name": "test-context",
    "campaign_id": "test-campaign",
    "lead_id": "test-lead-123",
}


class TestHTTPRequest(BaseModel):
    """Request model for testing HTTP tools."""
    url: str
    method: str = "GET"
    headers: Dict[str, str] = {}
    query_params: Dict[str, str] = {}
    body_template: Optional[str] = None
    timeout_ms: int = 5000
    test_values: Dict[str, str] = {}


class TestHTTPResponse(BaseModel):
    """Response model for HTTP tool test results."""
    success: bool
    status_code: Optional[int] = None
    response_time_ms: float
    headers: Dict[str, str] = {}
    body: Optional[Any] = None
    body_raw: Optional[str] = None
    error: Optional[str] = None
    resolved_url: str
    resolved_body: Optional[str] = None
    suggested_mappings: List[Dict[str, str]] = []


def _substitute_variables(template: str, values: Dict[str, str]) -> str:
    """
    Substitute template variables like {caller_number} and ${ENV_VAR}.
    """
    result = template
    
    # First, substitute {variable} style placeholders
    for key, value in values.items():
        result = result.replace(f"{{{key}}}", str(value))
    
    # Then substitute ${ENV_VAR} style environment variables
    env_pattern = re.compile(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}')
    def env_replacer(match):
        env_name = match.group(1)
        return os.environ.get(env_name, f"${{{env_name}}}")
    
    result = env_pattern.sub(env_replacer, result)
    return result


def _extract_json_paths(obj: Any, prefix: str = "") -> List[Dict[str, str]]:
    """
    Extract all JSON paths from a response object for suggested mappings.
    Returns list of {path, value, type} for each leaf node.
    """
    paths = []
    
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                paths.extend(_extract_json_paths(value, new_prefix))
            else:
                paths.append({
                    "path": new_prefix,
                    "value": str(value)[:100] if value is not None else "null",
                    "type": type(value).__name__
                })
    elif isinstance(obj, list) and len(obj) > 0:
        # Only show first element of arrays
        paths.extend(_extract_json_paths(obj[0], f"{prefix}[0]"))
        if len(obj) > 1:
            paths.append({
                "path": f"{prefix}[*]",
                "value": f"(array with {len(obj)} items)",
                "type": "array"
            })
    
    return paths


@router.post("/test-http", response_model=TestHTTPResponse)
async def test_http_tool(request: TestHTTPRequest):
    """
    Test an HTTP tool configuration by making the actual request.
    
    This endpoint:
    1. Substitutes template variables with test values
    2. Makes the HTTP request
    3. Returns the response with suggested variable mappings
    """
    # Merge default test values with provided ones
    test_values = {**DEFAULT_TEST_VALUES, **request.test_values}
    
    # Resolve URL with variable substitution
    resolved_url = _substitute_variables(request.url, test_values)
    
    # Build query parameters
    resolved_params = {}
    for key, value in request.query_params.items():
        resolved_params[key] = _substitute_variables(value, test_values)
    
    # Resolve headers
    resolved_headers = {}
    for key, value in request.headers.items():
        resolved_headers[key] = _substitute_variables(value, test_values)
    
    # Resolve body template
    resolved_body = None
    if request.body_template:
        resolved_body = _substitute_variables(request.body_template, test_values)
    
    # Prepare the response
    response_data = TestHTTPResponse(
        success=False,
        response_time_ms=0,
        resolved_url=resolved_url,
        resolved_body=resolved_body
    )
    
    # Make the HTTP request
    start_time = time.time()
    timeout_seconds = request.timeout_ms / 1000.0
    
    try:
        async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
            # Prepare request kwargs
            kwargs: Dict[str, Any] = {
                "method": request.method.upper(),
                "url": resolved_url,
                "headers": resolved_headers,
                "params": resolved_params if resolved_params else None,
            }
            
            # Add body for POST/PUT/PATCH
            if request.method.upper() in ("POST", "PUT", "PATCH") and resolved_body:
                kwargs["content"] = resolved_body
            
            # Make the request
            resp = await client.request(**kwargs)
            
            response_data.response_time_ms = (time.time() - start_time) * 1000
            response_data.status_code = resp.status_code
            response_data.headers = dict(resp.headers)
            response_data.body_raw = resp.text[:10000]  # Limit response size
            
            # Try to parse as JSON
            try:
                json_body = resp.json()
                response_data.body = json_body
                response_data.suggested_mappings = _extract_json_paths(json_body)
            except Exception:
                # Not JSON, just use raw text
                response_data.body = resp.text[:10000]
            
            response_data.success = 200 <= resp.status_code < 300
            
            if not response_data.success:
                response_data.error = f"HTTP {resp.status_code}: {resp.reason_phrase}"
                
    except httpx.TimeoutException:
        response_data.response_time_ms = (time.time() - start_time) * 1000
        response_data.error = f"Request timed out after {request.timeout_ms}ms"
    except httpx.ConnectError as e:
        response_data.response_time_ms = (time.time() - start_time) * 1000
        response_data.error = f"Connection failed: {str(e)}"
    except Exception as e:
        response_data.response_time_ms = (time.time() - start_time) * 1000
        response_data.error = f"Request failed: {str(e)}"
        logger.exception("HTTP tool test failed")
    
    return response_data


@router.get("/test-values")
async def get_default_test_values():
    """
    Get the default test values for template variable substitution.
    """
    return DEFAULT_TEST_VALUES
