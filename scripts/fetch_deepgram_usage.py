#!/usr/bin/env python3
"""
Fetch Deepgram usage/logs for a project or a specific request_id.

Usage examples:
  export DEEPGRAM_API_KEY=...  # required
  export DEEPGRAM_PROJECT_ID=...  # optional, or pass --project-id

  # Get all requests in a time window (UTC ISO-8601 or YYYY-MM-DD)
  python scripts/fetch_deepgram_usage.py --project-id "$DEEPGRAM_PROJECT_ID" \
      --start 2025-10-13T21:00:00Z --end 2025-10-13T22:00:00Z --status succeeded --limit 100

  # Fetch and print summary usage for the same window
  python scripts/fetch_deepgram_usage.py --project-id "$DEEPGRAM_PROJECT_ID" \
      --start 2025-10-13 --end 2025-10-13 --summary

  # Filter the returned requests by request_id after listing
  python scripts/fetch_deepgram_usage.py --project-id "$DEEPGRAM_PROJECT_ID" \
      --start 2025-10-13T21:00:00Z --end 2025-10-13T22:00:00Z --filter-request-id <REQUEST_ID>

Notes:
- Endpoints used:
  - GET https://api.deepgram.com/v1/projects/{project_id}/requests
  - GET https://api.deepgram.com/v1/projects/{project_id}/usage
- Voice Agent requests should appear under the same Deepgram project usage.
- For precise correlation, capture and pass the request_id you logged at connect time.
"""
import os
import sys
import json
import asyncio
import argparse
from typing import Any, Dict, Optional

import aiohttp

API_BASE = "https://api.deepgram.com/v1"


def env_or(arg: Optional[str], env_key: str) -> Optional[str]:
    return arg or os.environ.get(env_key)


async def fetch_all_requests(session: aiohttp.ClientSession, project_id: str, api_key: str,
                             start: Optional[str], end: Optional[str], status: Optional[str],
                             page: int, limit: int) -> Dict[str, Any]:
    url = f"{API_BASE}/projects/{project_id}/requests"
    params = {}
    if start:
        params["start"] = start
    if end:
        params["end"] = end
    if status:
        params["status"] = status
    if page is not None:
        params["page"] = str(page)
    if limit is not None:
        params["limit"] = str(limit)
    headers = {
        "Authorization": f"Token {api_key}",
        "accept": "application/json",
    }
    async with session.get(url, headers=headers, params=params, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.json()


async def fetch_usage_summary(session: aiohttp.ClientSession, project_id: str, api_key: str,
                              start: str, end: str) -> Dict[str, Any]:
    url = f"{API_BASE}/projects/{project_id}/usage"
    params = {"start": start, "end": end}
    headers = {
        "Authorization": f"Token {api_key}",
        "accept": "application/json",
    }
    async with session.get(url, headers=headers, params=params, timeout=30) as resp:
        resp.raise_for_status()
        return await resp.json()


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="Fetch Deepgram usage/logs")
    parser.add_argument("--project-id", default=None, help="Deepgram Project ID (or set DEEPGRAM_PROJECT_ID)")
    parser.add_argument("--start", default=None, help="Start time (ISO-8601 or YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End time (ISO-8601 or YYYY-MM-DD)")
    parser.add_argument("--status", default=None, help="Filter by status (e.g., succeeded, failed)")
    parser.add_argument("--page", type=int, default=0, help="Pagination page (default 0)")
    parser.add_argument("--limit", type=int, default=50, help="Results per page (default 50)")
    parser.add_argument("--filter-request-id", default=None, help="Filter results by request_id after fetch")
    parser.add_argument("--summary", action="store_true", help="Fetch usage summary instead of requests list")
    parser.add_argument("--output", default=None, help="Write JSON output to file path")

    args = parser.parse_args()
    api_key = env_or(None, "DEEPGRAM_API_KEY")
    if not api_key:
        print("Missing DEEPGRAM_API_KEY in environment", file=sys.stderr)
        return 2
    project_id = env_or(args.project_id, "DEEPGRAM_PROJECT_ID")
    if not project_id:
        print("Missing --project-id and DEEPGRAM_PROJECT_ID env", file=sys.stderr)
        return 2

    async with aiohttp.ClientSession() as session:
        if args.summary:
            if not args.start or not args.end:
                print("--summary requires --start and --end", file=sys.stderr)
                return 2
            data = await fetch_usage_summary(session, project_id, api_key, args.start, args.end)
            out = data
        else:
            data = await fetch_all_requests(session, project_id, api_key, args.start, args.end, args.status, args.page, args.limit)
            # Optional filter by request_id
            if args.filter_request_id and isinstance(data, dict) and isinstance(data.get("requests"), list):
                data["requests"] = [r for r in data["requests"] if r.get("request_id") == args.filter_request_id]
            out = data

    text = json.dumps(out, indent=2, sort_keys=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
        print(f"Wrote {args.output} ({len(text)} bytes)")
    else:
        print(text)
    return 0


def main() -> None:
    try:
        code = asyncio.run(main_async())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
