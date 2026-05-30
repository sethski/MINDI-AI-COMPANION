# MINDI-AI-COMPANION

Windows-first local assistant. Current repo layout:

- `apps/desktop/` Tauri + React notch shell
- `services/agent/` Python FastAPI local agent
- `packages/shared/` shared contracts and types
- `docs/` PRD and implementation notes

## Current Implementation (Phase 1 Spine)

- Notch-style desktop shell in `apps/desktop` with PRD tab layout.
- Local-first quick toggles and offline sync queue persistence.
- Hybrid sync worker in desktop app replays queued offline actions with retry/backoff.
- Service worker cache for offline shell boot.
- FastAPI local agent in `services/agent` for:
  - health checks
  - hub snapshot (status/tasks/alerts/logs)
  - assistant response with safety policy gate
  - task creation
  - local sync queue intake
- Shared TypeScript contracts in `packages/shared`.

## Current Implementation (Phase 2 Control Slice)

- Control APIs for allow/deny permission grants.
- Safe file organize pipeline with `preview` and `apply` modes.
- Allowlist enforcement before file operations.
- App control APIs for allowlisted `open`, `focus`, and confirmation-gated `close`.
- Audit log entries for file organize runs.
- Control tab UI for folder allowlist management and file-organize actions.

## Current Implementation (Phase 3 Memory Foundation)

- Local SQLite memory store at `data/runtime/memory.db`.
- Memory note APIs:
  - `GET /memory/notes`
  - `POST /memory/notes`
  - `GET /memory/search?query=...`
- Document ingestion APIs:
  - `POST /memory/documents/import`
  - `GET /memory/documents/search?query=...`
- OCR ingestion API:
  - `POST /memory/ocr/import`
- Background auto-index watcher:
  - `GET /memory/auto-index/status`
  - `POST /memory/auto-index/scan`
- Task due scheduler:
  - `GET /ops/scheduler/status`
  - `POST /ops/scheduler/scan`
  - `POST /ops/scheduler/next-run`
  - `POST /ops/scheduler/parse-time`
- Calendar export:
  - `POST /calendar/export` (`.ics`)
  - `POST /calendar/import` (`.ics` -> tasks)
  - Import path includes conflict detection (UID-first, then title + dueAt fallback).
  - Import parses `DTSTART;TZID=...`, `VALARM` reminder triggers, and `EXDATE` exclusions.
- Memory tab UI for note creation and retrieval.
- Playwright E2E coverage:
  - task status transitions (`todo` -> `done` -> `todo`)
  - calendar export/import roundtrip with dedupe validation

## Current Implementation (Phase 4 Perception Slice)

- Screen analysis API:
  - `POST /perception/screen/analyze`
  - Accepts either `path` or inline `imageDataUrl` capture payloads.
  - Extracts OCR text (when available) and lightweight UI text-region blocks from screenshots.
  - Handles OCR failures gracefully by returning detected blocks with an OCR error reason.
- Perception memory bridge:
  - Every successful screen-analysis run is persisted into local SQLite as a perception snapshot.
  - `GET /memory/perception`
  - `GET /memory/perception/search?query=...`
  - Assistant context can answer screen-oriented prompts using the latest stored snapshot.
- Perception safety gate:
  - `GET /perception/permissions` reports current screen/camera action-permission decisions.
  - `POST /perception/screen/analyze` now enforces `action=perception.screen.capture` allow grant.
  - Blocked perception attempts are appended to audit logs with explicit denial/required reasons.
- Vision tab capture hook:
  - Captures a live screen frame via browser display-capture API.
  - Sends the frame to local perception analysis and renders block + OCR summary.
  - Includes richer live diagnostics: confidence/coverage metrics, OCR metadata, and local snapshot-history search/details.

## Current Implementation (Phase 5 Ops Slice)

- Web scraping API:
  - `POST /ops/web/scrape`
  - Safe HTTP/HTTPS fetch with HTML/text extraction, title + links capture.
  - Optional `storeAsNote` path persists scraped content to local memory notes.
  - Domain permission gate enforces allow/deny policy using `scope=domain` grants.
- Ops tab UI:
  - Run scrape jobs from URL input.
  - View scrape output, extracted links, and note-storage result.
  - Manage domain allowlist entries directly from Ops/Control flows.
- Security monitoring + recovery:
  - `POST /ops/security/scan`
  - `GET /ops/security/events`
  - `POST /ops/security/recover`
  - Detects suspicious process signatures and Defender-service down state.
  - Supports recovery actions: dismiss event, deny app, and confirmation-gated kill process.
  - Ops tab now shows security events and recovery controls.
- Deeper automation chains:
  - `POST /ops/automation/run`
  - Executes multi-step chains across scrape/task/note/security-scan steps.
  - Returns per-step status, failure index, and recovery hints for failed chain runs.
  - Ops tab includes automation-chain runner with step-by-step result panel.
- Alerts and recovery flows:
  - `GET /ops/alerts/feed`
  - `POST /ops/alerts/action`
  - Prioritized alert feed with severity counts and top-risk ordering.
  - Alert actions: dismiss, create recovery task, and export alert report (JSON with recent logs).
- Offline privacy hardening:
  - `GET /ops/privacy/status`
  - `POST /ops/privacy/update`
  - Sensitive-text redaction toggle (enabled by default) for stored scrape notes and stored perception snapshots.
  - Response metadata reports whether storage redaction was applied and match count.
- AI smoke and benchmark run:
  - `POST /ops/ai/smoke`
  - Runs runtime probes for LLM/ASR/OCR with typed pass/fail reasons and per-feature latency metadata.
  - Ops tab includes a smoke runner for real local model-path validation before release.

## Current Implementation (Phase 6 Intelligence)

- Style profile controls:
  - `GET /ops/intelligence/style`
  - `POST /ops/intelligence/style`
  - Supports language mode (`english`, `taglish`, `tagalog`) and curated slang-layer terms.
- Eval suite and reliability loop:
  - `POST /ops/intelligence/eval/run`
  - `GET /ops/intelligence/eval/history`
  - Supports `active`, `pending`, and `learning` eval scopes with stored score history and gate state.
- Prompt and policy tuning:
  - Stage pending tuning candidates before apply.
  - Apply is blocked unless the exact pending candidate set has already passed eval.
  - Supports preset, verbosity, and risky-term tuning with discard/reset controls.
- Self-improvement loop:
  - Approved local memory notes can be used as learning sources.
  - Extraction only accepts explicit style markers and filters blocked or risky terms.
  - Learned slang must pass its own eval gate before apply.
- Light LoRA-prep export, if justified:
  - `GET /ops/intelligence/adaptation/status`
  - `POST /ops/intelligence/adaptation/export`
  - Recommends `none`, `prompt_only`, or `lora` from local evidence and can export a bounded local adaptation pack when justified.
- Ops tab intelligence panel:
  - Manage active and pending tuning, run evals, review learning sources and candidates, apply gated slang, and export adaptation artifacts.

## Run Desktop

```bash
pnpm install
pnpm dev:desktop
```

## Run Full Stack

```bash
pnpm dev:all
```

## Run Agent

```bash
python -m pip install -e services/agent[dev]
pnpm dev:agent
```

## Run AI Runtime

```bash
python -m pip install -e services/ai_runtime
pnpm dev:ai-runtime
```

Notes:
- Install `llama.cpp` and make sure `llama-cli` is available in your shell `PATH`.
- Configure `LLM model path (GGUF)` in Settings before using `/assistant/respond` runtime inference.
- ASR uses `qwen-asr`; configure `ASR model path` for `Qwen/Qwen3-ASR-1.7B`.
- OCR uses GLM-OCR via Hugging Face `transformers`; configure `OCR model path` for `zai-org/GLM-OCR`.
- Dataset prep endpoint `/ops/intelligence/dataset/prepare` now validates artifact schemas and auto-registers the generated `language_pack_ph.json` into runtime config (`llmLanguagePackPath`) for prompt-time style hints.

Release hardening checklist:
- Keep `offlineMode` enabled and provision model files manually (no runtime downloader).
- Confirm all three model paths resolve locally in `Settings > AI Runtime Config`.
- Verify `Ops > AI Runtime Observability` shows explicit readiness/error state for `llm`, `asr`, and `ocr`.
- Validate degraded fallback paths before release:
  - `/assistant/respond` falls back to rule-based response when runtime LLM fails.
  - `/memory/ocr/import` and `/perception/screen/analyze` preserve response structure when OCR runtime fails.
- Run `pnpm test:agent` before packaging.

## Test Agent

```bash
pnpm test:agent
```

## Test E2E

```bash
pnpm test:e2e
```
