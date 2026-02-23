# GA 6.3.1 Readiness Assessment

**Audit date:** 2026-02-23  
**Branch target:** `local-ai-server-improvements` -> `main`  
**Release target:** `v6.3.1`  
**Baseline reference:** `archived/GA-6.0.0-Readiness.md`

## Executive Summary

**GA Ready:** ⚠️ Conditional (post-audit)  
**Primary focus:** Production-quality Local AI Server onboarding + model lifecycle (download → switch → rebuild → runtime), with stronger guardrails and clearer UX.

**Key evidence:**

- `pytest -q`: **617 passed, 4 skipped** (2026-02-23). *Note: no CI artifact or commit hash attached — treat as indicative.*
- Community GPU validation on RTX 4090 shows **~1.0s E2E** with **~540–550ms LLM avg** under full-local runtime (see "Indicative Performance Observations"). *N=16–18 samples; not statistically rigorous.*

**Post-audit fixes applied (commit TBD):**

- 🔴 **Rebuild race condition** (`_active_rebuild` TOCTOU) — fixed with atomic check-and-set under lock.
- 🟠 **Archive extraction TOCTOU** — `extractall` now uses validated member lists only (zip + tar).
- 🟠 **GGUF magic-byte validation** — corrupt/truncated `.gguf` downloads now caught before load.
- 🟠 **Active-call guard on model switch** — blocks switch when calls are in progress (overridable).

**Conditional gates before tagging:**

1. Run an operator validation pass for **backend enable/rebuild flow** from Admin UI on a fresh GPU host (Faster-Whisper + MeloTTS + Whisper.cpp optional).
2. Confirm **split-host posture** is documented and explicitly “best-effort” (or provide a minimal split-host guide + TLS proxy recommendation).

---

## Release Scope

### Local AI Server improvements

- Runtime stability hardening: degraded-start behavior, clearer capabilities reporting, and safer defaults on CPU-only hosts.
- GPU ergonomics: `LOCAL_LLM_GPU_LAYERS=-1` auto selection, footgun warnings, and better operator visibility of effective GPU offload.
- Tool gateway: structured local tool-call normalization with allowlisting and repair paths for malformed model outputs.

### Onboarding UX

- Setup Wizard and Models page now surface backend availability (capabilities-aware UI) and clearer “requires rebuild” guidance.
- Model download UX and metadata improved, with safer extraction and checksum sidecars where available.

### GPU learnings integration

- Import-order mitigation for CUDA runtime collisions (torch preload before llama.cpp).
- Whisper-family STT echo/talk-loop mitigations via TTS playback suppression + improved segment gating.

### Model lifecycle robustness

- Clearer separation between: model assets (download) vs backend packages/binaries (rebuild) vs active runtime selection (switch/reload).

---

## Audit Learnings Integrated (GPU-LEARNINGS + Local AI Server Audit)

This release explicitly incorporates and/or tracks the high-signal items from:

- `archived/GPU-LEARNINGS.md`
- `archived/local-ai-server-audit-report.md`

Key integrations:

- **GPU layers best practice**: guide operators toward `LOCAL_LLM_GPU_LAYERS=-1` and warn when GPU is detected but CPU-only layers are configured.
- **CUDA import-order mitigation**: torch preload before `llama_cpp` to avoid Kokoro/Torch failures due to `libcudart` symbol mismatches.
- **Whisper-family echo/talk-loop prevention**: suppress STT during TTS playback and improve segment gating/AgentAudioDone timing for ExternalMedia RTP.
- **Degraded-start behavior**: Local AI Server starts without hard-failing when optional backends/models are missing, enabling recovery from the Admin UI.
- **Model caching strategy**: persist LLM auto-context tuning decisions under the data volume where possible to avoid repeated cold-start tuning.

---

## Validation Checklist

### Setup Wizard validation

- [ ] Local provider selection (`local` and `local_hybrid`) writes consistent `.env` + YAML configuration.
- [ ] Wizard completion step can start/recreate `local_ai_server` from Admin UI without “compose context” path issues.
- [ ] Backend capability gating works: options disabled when backend not present and guidance is visible.

### Model download workflow

- [ ] Single-model download produces correct paths under `models/stt`, `models/tts`, `models/llm`, and `models/kroko`.
- [x] Archive extraction is safe (no path traversal, no symlink extraction, validated member lists passed to `extractall`) and does not delete unexpected directories.
- [ ] Partial downloads (`.part`) are cleaned up on failure and do not corrupt the target model directory.
- [x] GGUF download: filename validation (`.gguf`) **and** magic-byte header validation enforced; corrupt/truncated downloads are caught and cleaned up with actionable error messages.

### Model switching

- [ ] Hot-switch (WS `switch_model`) works for non-rebuild changes (e.g., Kokoro voice, Faster-Whisper model selection).
- [ ] Switch that requires container recreate reliably rolls back on failure (no “stuck” half-applied `.env`/YAML state).
- [ ] Kroko embedded inference behaves correctly when model path points to `/app/models/kroko/...`.

### GPU auto-detection

- [ ] Preflight writes `GPU_AVAILABLE=true` on GPU hosts and emits warning when `LOCAL_LLM_GPU_LAYERS=0`.
- [ ] Runtime GPU detection in `local_ai_server` is visible in status and reflected in UI.
- [ ] `LOCAL_LLM_GPU_LAYERS=-1` yields a sensible effective layer count by VRAM tier.

### Guardrails

- [ ] `hangup_call` is blocked unless end-of-call intent is present in the user transcript (configurable policy modes).
- [ ] Tool allowlist enforcement drops any non-allowlisted tool calls before execution.
- [ ] Transfer intent detection does not leak “tool chatter” into spoken output.

### Tool execution safety

- [ ] Local tool gateway “repair” turns do not bypass allowlists or policy restrictions.
- [x] Model switch endpoint blocks when active calls are in progress (best-effort check; overridable with `force_incompatible_apply`).

### Container rebuild scenarios

- [ ] Optional backends can be enabled via Admin UI and container rebuild reports actionable errors (disk, build, restart).
- [ ] Rebuild is safe against stale compose execution context (runs on host paths, not container paths).
- [ ] `local_ai_server` healthcheck reaches `healthy` within an expected window for large models (or degrades with clear logs).

### IPv6 behavior validation

- [ ] Preflight warns when IPv6 is enabled (best-effort GA policy) and docs provide mitigation steps.
- [ ] DNS/networking remains stable under host-network Docker when IPv6 is disabled/enabled per guidance.

### Error recovery flows

- [ ] Corrupt `.env` or YAML: Admin UI shows actionable parse error and provides recovery path.
- [ ] Missing model files: Local AI Server starts degraded (non-fail-fast) and UI guides recovery.
- [ ] Runtime GPU unavailable: CUDA selections are blocked or warned with clear “why” messaging.

---

## Known Risks

### High

- **Split-host deployment gaps**: Remote Local AI Server (separate GPU host) remains best-effort; model management and rebuild flows are not fully supported without additional docs and/or proxying.
- **Backend enable/rebuild correctness across environments**: Must be validated on at least one clean GPU host path (Docker + NVIDIA runtime + fresh checkout).

### Medium

- **GGUF integrity validation**: ~~Extension checks only~~ → Now validates GGUF magic bytes (`0x47475546`) after download; corrupt files are removed with actionable error. *(Fixed post-audit.)*
- **“Thank you” hangup ambiguity**: Guardrails reduce hallucinated tool calls, but polite mid-call closings can still be ambiguous; tune hangup policy markers if false positives occur.

### Low

- **Large model startup timing**: Healthcheck windows are improved but still dependent on disk/VRAM/first-run downloads and warmup behavior.

---

## Indicative Performance Observations

> **Disclaimer:** N=16–18 samples from a single community host. These are indicative measurements, not controlled benchmarks. Do not cite as statistically significant.

### Community RTX 4090 (Ubuntu 22.04.5, Docker 29.2.1, ExternalMedia RTP, full-local)

- **E2E latency**: ~1.0s (steady state).
- **LLM latency**: ~541–546ms average (16–18 samples), last-sample ~608–625ms.
- **STT**: Kroko embedded (port 6006), 35–52 transcripts observed per session.
- **TTS**:
  - Kokoro (af_heart, hf mode): "Natural voice quality".
  - MeloTTS (EN-US): slower first turns, then improves (warm-up/caching behavior suspected).

---

## Rollback Plan

If production regression is detected post-tag:

1. Revert the `main` deployment to the previous tag (target: `v6.2.2`).
2. Restore `.env` and `config/ai-agent.yaml` from last-known-good backups (Admin UI writes are atomic; prefer its backups if present).
3. Recreate containers:
   - `docker compose -p asterisk-ai-voice-agent up -d --force-recreate`
4. Validate:
   - `agent check --local`
   - Place a smoke test call and confirm hangup/tool behavior.

---

## Pre-PR Checklist

- [ ] Branch is rebased/merged cleanly onto `main` (no accidental revert of `v6.2.x` fixes).
- [ ] `pytest -q` is green in CI and locally (or waived only for environment-constrained tests with documented rationale).
- [ ] Admin UI wizard can complete “Fully Local” and “Local Hybrid” without docker compose context failures.
- [ ] `CHANGELOG.md` includes a complete `v6.3.1` section with categories (Added/Improved/Fixed/Guardrails/Performance/Docs).
- [ ] `docs/LOCAL_ONLY_SETUP.md` aligns with current defaults (ExternalMedia RTP, runtime_mode, GPU layers, tool gateway).

---

## Release Checklist

- [ ] Merge PR to `main`.
- [ ] Tag `v6.3.1` on the merge commit.
- [ ] Build/publish images if applicable (ai_engine, admin_ui, local_ai_server, updater).
- [ ] Update release notes with benchmark evidence + known limitations (split-host, optional backends, GPU layer guidance).

---

## Post-Release Monitoring Plan

- Monitor first-run onboarding funnel:
  - Wizard completion rates for local/local_hybrid
  - Local AI Server health transitions (starting → healthy/degraded)
- Monitor guardrails:
  - Count of blocked `hangup_call` tool calls and transcripts triggering blocks
  - Any reports of “tool chatter” spoken output
- Monitor performance:
  - LLM latency distribution (p50/p95) for common GGUF models
  - STT echo/talk-loop reports on Whisper-family backends
- Triage queue:
  - Close/resolve remaining backlog items (GPU model matrix coverage, split-host docs, rebuild ergonomics)

---

## Post-Audit Appendix (2026-02-23)

Independent forensic audit performed against live codebase. Findings and remediations:

### Bugs Fixed

| # | Severity | Issue | Fix | File |
|---|----------|-------|-----|------|
| 1 | Critical | `start_rebuild_job()` TOCTOU race — two concurrent requests could both pass `_active_rebuild` check | Moved check-and-set inside `_rebuild_jobs_lock` | `rebuild_jobs.py` |
| 2 | High | `extractall()` called without validated member list (zip + tar) — theoretical TOCTOU | `extractall` now receives `members=safe_members` | `wizard.py` |
| 3 | High | No GGUF magic-byte validation — corrupt downloads crash `llama.cpp` at load | Added `_validate_gguf_magic()` check after download; removes corrupt file | `wizard.py` |
| 4 | High | Model switch during active calls could disrupt audio | Added active-call guard via `_check_active_calls()` before switch | `local_ai.py` |

### Report Corrections

| # | Original Claim | Correction |
|---|----------------|------------|
| 1 | `demo_post_call_webhook` checklist item (line 101) | Removed — this is an optional configured HTTP tool example (not a built-in/default tool) and is not required for GA readiness |
| 2 | "GA Ready: ✅ Conditional" | Changed to ⚠️ — conditional gate should not use a green checkmark |
| 3 | "Performance Benchmarks" section | Reframed as "Indicative Performance Observations" with statistical disclaimer |
| 4 | GGUF validation rated Medium | Upgraded — now fixed; magic-byte check prevents container crashes |

### Remaining Gaps (not blocking, documented for awareness)

- **Rebuild rollback covers `.env` only, not Docker image** — after build-success + restart-failure, orphaned image may mismatch `.env`. Manual `docker compose build` required to recover.
- **No concurrent download guard** — two simultaneous downloads for the same model path can corrupt the file. Low probability in practice (UI serializes).
- **No download resume** — `urllib.request.urlretrieve` does not support HTTP range requests. Interrupted large downloads restart from zero.
- **Multi-GPU untested** — `LOCAL_LLM_GPU_LAYERS=-1` behavior with 2+ GPUs is undocumented and untested.
- **GPU driver/CUDA mismatch** — `nvidia-smi` success + `torch.cuda.is_available()` failure produces silent CPU fallback without explicit warning for this specific scenario.
- **IPv6-only hosts** — `127.0.0.1` health checks would fail on IPv6-only Docker hosts.

### Recommended Pre-Merge Tests

| # | Test | Method | Priority |
|---|------|--------|----------|
| 1 | Fresh-host wizard walkthrough | Clean GPU host, wizard end-to-end | Must-have |
| 2 | Concurrent rebuild requests | Two simultaneous `/rebuild/start` calls | Must-have |
| 3 | Rebuild failure rollback | Kill Docker daemon mid-build, verify `.env` state | Should-have |
| 4 | GGUF corruption | Truncate a `.gguf` file, trigger load | Should-have |
| 5 | Model switch during active call | Start call, trigger switch, verify guard | Should-have |
