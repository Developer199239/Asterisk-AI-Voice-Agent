from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import docker
from fastapi import APIRouter, HTTPException, Query

from api.log_events import LogEvent, parse_log_line, should_hide_payload

router = APIRouter()


def _parse_iso_to_epoch_seconds(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def _split_csv(values: Optional[Sequence[str]]) -> List[str]:
    out: List[str] = []
    for v in values or []:
        if not v:
            continue
        parts = [p.strip() for p in str(v).split(",")]
        out.extend([p for p in parts if p])
    return out


@router.get("/{container_name}")
async def get_container_logs(container_name: str, tail: int = 100):
    """
    Fetch logs from a specific container.
    """
    try:
        client = docker.from_env()
        # Filter by name to find the correct container
        # We use a loose match because docker compose prepends project name
        containers = client.containers.list(all=True, filters={"name": container_name})
        
        if not containers:
            # Try exact match if loose match fails or returns multiple (though list returns list)
            try:
                container = client.containers.get(container_name)
                containers = [container]
            except docker.errors.NotFound:
                raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found")

        # Pick the first match (usually the most relevant one if unique enough)
        container = containers[0]
        
        # Get logs
        logs = container.logs(tail=tail).decode('utf-8')
        return {"logs": logs, "container_id": container.id, "name": container.name}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{container_name}/events")
async def get_container_log_events(
    container_name: str,
    call_id: Optional[str] = None,
    q: Optional[str] = None,
    levels: Optional[List[str]] = Query(default=None),
    categories: Optional[List[str]] = Query(default=None),
    hide_payloads: bool = True,
    since: Optional[str] = None,
    until: Optional[str] = None,
    since_seconds_ago: Optional[int] = None,
    limit: int = 500,
) -> Dict[str, Any]:
    """
    Fetch parsed, filterable log events from a container.

    This is designed for the Admin UI "Events" view to enable fast troubleshooting.
    """
    try:
        client = docker.from_env()
        containers = client.containers.list(all=True, filters={"name": container_name})
        if not containers:
            try:
                container = client.containers.get(container_name)
                containers = [container]
            except docker.errors.NotFound:
                raise HTTPException(status_code=404, detail=f"Container '{container_name}' not found")
        container = containers[0]

        q_norm = (q or "").strip().lower() or None
        call_id_norm = (call_id or "").strip() or None

        wanted_levels = {v.strip().lower() for v in _split_csv(levels)} if levels else set()
        wanted_categories = {v.strip().lower() for v in _split_csv(categories)} if categories else set()

        since_epoch = _parse_iso_to_epoch_seconds(since)
        until_epoch = _parse_iso_to_epoch_seconds(until)
        if since_epoch is None and since_seconds_ago and since_seconds_ago > 0:
            since_epoch = int(datetime.now(timezone.utc).timestamp()) - int(since_seconds_ago)

        # Keep volume bounded: use time-window when provided, otherwise tail.
        logs_bytes = container.logs(
            since=since_epoch,
            until=until_epoch,
            tail=None if (since_epoch or until_epoch) else 2000,
            timestamps=False,
        )
        logs_text = (logs_bytes or b"").decode("utf-8", errors="replace")

        events: List[LogEvent] = []
        for line in logs_text.splitlines():
            parsed = parse_log_line(line)
            if not parsed:
                continue
            event, _kv = parsed
            if hide_payloads and should_hide_payload(event):
                continue
            if call_id_norm and event.call_id != call_id_norm:
                continue
            if wanted_levels and event.level not in wanted_levels:
                continue
            if wanted_categories and event.category not in wanted_categories:
                continue
            if q_norm and q_norm not in (event.raw or "").lower() and q_norm not in (event.msg or "").lower():
                continue
            events.append(event)

        # Sort by timestamp when available, otherwise keep input order
        events_sorted = sorted(
            events,
            key=lambda e: (e.ts is None, e.ts or datetime.min.replace(tzinfo=timezone.utc)),
        )
        if limit and limit > 0:
            events_sorted = events_sorted[-int(limit):]

        return {
            "events": [e.to_dict() for e in events_sorted],
            "container_id": container.id,
            "name": container.name,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
