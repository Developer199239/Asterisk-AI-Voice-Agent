# Milestone 8 — Optional Monitoring & Analytics Stack

## Objective
Ship an opt-in monitoring container and documentation so operators can visualize health metrics, evaluate provider combinations, and prepare for future analytics (transcripts, sentiment). Defaults must be simple to enable and expose dashboards over HTTP/HTTPS.

## Success Criteria
- `docker-compose.yml` includes a disabled-by-default monitoring service (Prometheus + Grafana or equivalent) with persistent volume mounts.
- `Makefile` exposes `make monitor-up` / `make monitor-down` targets that launch/stop the monitoring stack locally and on the server.
- Dashboards display streaming metrics (restart counts, buffer depth, provider stats) without additional configuration.
- Documentation explains how to interpret metrics and how to extend the stack with transcript/sentiment hooks.

## Dependencies
- Milestones 5–7 (streaming telemetry and pipeline metadata) completed so metrics are available.

## Work Breakdown

### 8.1 Monitoring Service Definition
- Add Prometheus service to `docker-compose.yml` scraping `ai-engine` metrics endpoint.
- Add Grafana service with pre-built dashboards (stored in `monitoring/dashboards/`).
- Ensure services are optional: default compose file keeps them stopped; instructions explain enabling them.

### 8.2 Makefile & Scripts
- Add Make targets:
  - `make monitor-up`
  - `make monitor-down`
  - `make monitor-logs`
  - `make monitor-reload` (optional)
- Ensure targets work both locally and via SSH (using existing pattern in Makefile).

### 8.3 Metrics & Dashboards
- Verify `/metrics` exposes required labels (pipeline name, provider, streaming stats).
- Create dashboard panels for:
  - Streaming restart count per call
  - Jitter buffer depth trends
  - Turn latency histograms
  - Provider distribution (Deepgram vs OpenAI, pipeline names)
- Store dashboard JSON files under `monitoring/dashboards/` and document upload/import steps.

### 8.4 Documentation
- Update `docs/Architecture.md` with monitoring overview and port defaults.
- Add `docs/Monitoring.md` (or section) walking through enabling the stack, accessing Grafana, and customizing dashboards.
- Mention future hooks for transcript/sentiment analytics (Deepgram Test Intelligence, etc.).

## Deliverables
- Updated `docker-compose.yml` and `Makefile`.
- Dashboard JSON files and optional provisioning config.
- Documentation (`docs/Architecture.md`, `docs/Monitoring.md` or equivalent) plus roadmap update.

## Verification Checklist
- `make monitor-up` spins up Prometheus + Grafana; Grafana accessible at configured port (document default).
- Dashboard shows live data during a regression call.
- Stopping the monitoring stack does not impact AI engine services.

## Handover Notes
- Future milestone: integrate transcript archive and sentiment metrics; leave TODOs or comments where hooks should be inserted.
- Ensure IDE rule files mention optional monitoring commands and expectations.
