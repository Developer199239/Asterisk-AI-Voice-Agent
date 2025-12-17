"""
Call History API endpoints (Milestone 21).

Provides REST API for viewing, searching, and managing call history records.
"""

import csv
import io
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

# Add project root to path for imports
project_root = os.environ.get("PROJECT_ROOT", "/app/project")
if project_root not in sys.path:
    sys.path.insert(0, project_root)

logger = logging.getLogger(__name__)

router = APIRouter()


class CallRecordResponse(BaseModel):
    """Response model for a call record."""
    id: str
    call_id: str
    caller_number: Optional[str] = None
    caller_name: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    duration_seconds: float = 0.0
    provider_name: str = "unknown"
    pipeline_name: Optional[str] = None
    pipeline_components: dict = {}
    context_name: Optional[str] = None
    conversation_history: list = []
    outcome: str = "completed"
    transfer_destination: Optional[str] = None
    error_message: Optional[str] = None
    tool_calls: list = []
    avg_turn_latency_ms: float = 0.0
    max_turn_latency_ms: float = 0.0
    total_turns: int = 0
    caller_audio_format: str = "ulaw"
    codec_alignment_ok: bool = True
    barge_in_count: int = 0
    created_at: Optional[str] = None


class CallListResponse(BaseModel):
    """Response model for paginated call list."""
    calls: List[CallRecordResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class CallStatsResponse(BaseModel):
    """Response model for call statistics."""
    total_calls: int = 0
    avg_duration_seconds: float = 0.0
    max_duration_seconds: float = 0.0
    min_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    avg_latency_ms: float = 0.0
    total_turns: int = 0
    total_barge_ins: int = 0
    outcomes: dict = {}
    providers: dict = {}
    pipelines: dict = {}
    contexts: dict = {}
    calls_per_day: list = []
    top_callers: list = []
    calls_with_tools: int = 0
    top_tools: dict = {}
    active_calls: int = 0


class FilterOptionsResponse(BaseModel):
    """Response model for filter dropdown options."""
    providers: List[str] = []
    pipelines: List[str] = []
    contexts: List[str] = []
    outcomes: List[str] = []


def _get_call_history_store():
    """Get the call history store instance."""
    try:
        from src.core.call_history import get_call_history_store
        return get_call_history_store()
    except ImportError as e:
        logger.error(f"Failed to import call_history module: {e}")
        raise HTTPException(status_code=500, detail="Call history module not available")


def _record_to_response(record) -> CallRecordResponse:
    """Convert a CallRecord to a response model."""
    return CallRecordResponse(
        id=record.id,
        call_id=record.call_id,
        caller_number=record.caller_number,
        caller_name=record.caller_name,
        start_time=record.start_time.isoformat() if record.start_time else None,
        end_time=record.end_time.isoformat() if record.end_time else None,
        duration_seconds=record.duration_seconds,
        provider_name=record.provider_name,
        pipeline_name=record.pipeline_name,
        pipeline_components=record.pipeline_components or {},
        context_name=record.context_name,
        conversation_history=record.conversation_history or [],
        outcome=record.outcome,
        transfer_destination=record.transfer_destination,
        error_message=record.error_message,
        tool_calls=record.tool_calls or [],
        avg_turn_latency_ms=record.avg_turn_latency_ms,
        max_turn_latency_ms=record.max_turn_latency_ms,
        total_turns=record.total_turns,
        caller_audio_format=record.caller_audio_format,
        codec_alignment_ok=record.codec_alignment_ok,
        barge_in_count=record.barge_in_count,
        created_at=record.created_at.isoformat() if record.created_at else None,
    )


@router.get("/calls", response_model=CallListResponse)
async def list_calls(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    caller_number: Optional[str] = Query(None, description="Filter by caller number (partial match)"),
    caller_name: Optional[str] = Query(None, description="Filter by caller name (partial match)"),
    provider_name: Optional[str] = Query(None, description="Filter by provider"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline"),
    context_name: Optional[str] = Query(None, description="Filter by context"),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
    has_tool_calls: Optional[bool] = Query(None, description="Filter calls with tool executions"),
    min_duration: Optional[float] = Query(None, description="Minimum duration in seconds"),
    max_duration: Optional[float] = Query(None, description="Maximum duration in seconds"),
    order_by: str = Query("start_time", description="Column to order by"),
    order_dir: str = Query("DESC", description="Order direction (ASC/DESC)"),
):
    """
    List call history records with pagination and filtering.
    """
    store = _get_call_history_store()
    
    # Parse dates
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    # Get total count
    total = await store.count(
        start_date=parsed_start,
        end_date=parsed_end,
        caller_number=caller_number,
        provider_name=provider_name,
        pipeline_name=pipeline_name,
        context_name=context_name,
        outcome=outcome,
    )
    
    # Get paginated records
    offset = (page - 1) * page_size
    records = await store.list(
        limit=page_size,
        offset=offset,
        start_date=parsed_start,
        end_date=parsed_end,
        caller_number=caller_number,
        caller_name=caller_name,
        provider_name=provider_name,
        pipeline_name=pipeline_name,
        context_name=context_name,
        outcome=outcome,
        has_tool_calls=has_tool_calls,
        min_duration=min_duration,
        max_duration=max_duration,
        order_by=order_by,
        order_dir=order_dir,
    )
    
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    return CallListResponse(
        calls=[_record_to_response(r) for r in records],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/calls/stats", response_model=CallStatsResponse)
async def get_call_stats(
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
):
    """
    Get aggregate statistics for the dashboard.
    """
    store = _get_call_history_store()
    
    # Parse dates
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    stats = await store.get_stats(start_date=parsed_start, end_date=parsed_end)
    
    # Fetch active calls from ai_engine health endpoint (Milestone 21)
    active_calls = 0
    try:
        import aiohttp
        ai_engine_url = os.getenv("AI_ENGINE_HEALTH_URL", "http://ai-engine:15000")
        logger.info(f"Fetching active calls from {ai_engine_url}/sessions/stats")
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{ai_engine_url}/sessions/stats", timeout=aiohttp.ClientTimeout(total=2)) as resp:
                if resp.status == 200:
                    session_stats = await resp.json()
                    active_calls = session_stats.get("active_calls", 0)
                    logger.info(f"Active calls from ai_engine: {active_calls}")
                else:
                    logger.warning(f"ai_engine returned status {resp.status}")
    except Exception as e:
        logger.warning(f"Failed to fetch active calls from ai_engine: {e}")
    
    stats["active_calls"] = active_calls
    
    return CallStatsResponse(**stats)


@router.get("/calls/filters", response_model=FilterOptionsResponse)
async def get_filter_options():
    """
    Get distinct values for filter dropdowns.
    """
    store = _get_call_history_store()
    
    providers = await store.get_distinct_values("provider_name")
    pipelines = await store.get_distinct_values("pipeline_name")
    contexts = await store.get_distinct_values("context_name")
    outcomes = await store.get_distinct_values("outcome")
    
    return FilterOptionsResponse(
        providers=providers,
        pipelines=pipelines,
        contexts=contexts,
        outcomes=outcomes,
    )


@router.get("/calls/{record_id}", response_model=CallRecordResponse)
async def get_call(record_id: str):
    """
    Get a single call record by ID.
    """
    store = _get_call_history_store()
    
    record = await store.get(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call record not found")
    
    return _record_to_response(record)


@router.get("/calls/{record_id}/transcript")
async def get_call_transcript(record_id: str):
    """
    Get just the conversation history for a call.
    """
    store = _get_call_history_store()
    
    record = await store.get(record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Call record not found")
    
    return {
        "call_id": record.call_id,
        "conversation_history": record.conversation_history or [],
    }


@router.delete("/calls/{record_id}")
async def delete_call(record_id: str):
    """
    Delete a single call record.
    """
    store = _get_call_history_store()
    
    success = await store.delete(record_id)
    if not success:
        raise HTTPException(status_code=404, detail="Call record not found")
    
    return {"status": "deleted", "id": record_id}


@router.delete("/calls")
async def bulk_delete_calls(
    before_date: Optional[str] = Query(None, description="Delete records before this date (ISO format)"),
    older_than_days: Optional[int] = Query(None, ge=1, description="Delete records older than N days"),
):
    """
    Bulk delete call records by date.
    """
    if not before_date and not older_than_days:
        raise HTTPException(
            status_code=400, 
            detail="Must specify either before_date or older_than_days"
        )
    
    store = _get_call_history_store()
    
    if older_than_days:
        cutoff = datetime.now() - timedelta(days=older_than_days)
    else:
        try:
            cutoff = datetime.fromisoformat(before_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid before_date format")
    
    deleted = await store.delete_before(cutoff)
    
    return {"status": "deleted", "count": deleted, "before": cutoff.isoformat()}


@router.get("/calls/export/csv")
async def export_calls_csv(
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    provider_name: Optional[str] = Query(None, description="Filter by provider"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline"),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
):
    """
    Export call records as CSV.
    """
    store = _get_call_history_store()
    
    # Parse dates
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    # Get all matching records (limit to 10000 for safety)
    records = await store.list(
        limit=10000,
        offset=0,
        start_date=parsed_start,
        end_date=parsed_end,
        provider_name=provider_name,
        pipeline_name=pipeline_name,
        outcome=outcome,
    )
    
    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "ID", "Call ID", "Caller Number", "Caller Name",
        "Start Time", "End Time", "Duration (s)",
        "Provider", "Pipeline", "Context", "Outcome",
        "Transfer Destination", "Error Message",
        "Tool Calls", "Avg Latency (ms)", "Max Latency (ms)",
        "Total Turns", "Barge-ins"
    ])
    
    # Data rows
    for r in records:
        writer.writerow([
            r.id, r.call_id, r.caller_number or "", r.caller_name or "",
            r.start_time.isoformat() if r.start_time else "",
            r.end_time.isoformat() if r.end_time else "",
            round(r.duration_seconds, 2),
            r.provider_name, r.pipeline_name or "", r.context_name or "", r.outcome,
            r.transfer_destination or "", r.error_message or "",
            len(r.tool_calls), round(r.avg_turn_latency_ms, 2), round(r.max_turn_latency_ms, 2),
            r.total_turns, r.barge_in_count
        ])
    
    csv_content = output.getvalue()
    
    filename = f"call_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/calls/export/json")
async def export_calls_json(
    start_date: Optional[str] = Query(None, description="Filter by start date (ISO format)"),
    end_date: Optional[str] = Query(None, description="Filter by end date (ISO format)"),
    provider_name: Optional[str] = Query(None, description="Filter by provider"),
    pipeline_name: Optional[str] = Query(None, description="Filter by pipeline"),
    outcome: Optional[str] = Query(None, description="Filter by outcome"),
):
    """
    Export call records as JSON.
    """
    store = _get_call_history_store()
    
    # Parse dates
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid start_date format")
    if end_date:
        try:
            parsed_end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid end_date format")
    
    # Get all matching records (limit to 10000 for safety)
    records = await store.list(
        limit=10000,
        offset=0,
        start_date=parsed_start,
        end_date=parsed_end,
        provider_name=provider_name,
        pipeline_name=pipeline_name,
        outcome=outcome,
    )
    
    # Convert to JSON-serializable format
    data = {
        "exported_at": datetime.now().isoformat(),
        "total_records": len(records),
        "records": [_record_to_response(r).model_dump() for r in records]
    }
    
    json_content = json.dumps(data, indent=2)
    
    filename = f"call_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    return Response(
        content=json_content,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
