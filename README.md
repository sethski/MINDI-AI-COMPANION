# MINDI-AI-COMPANION

Windows-first local assistant. Current repo layout:

- `apps/desktop/` Tauri + React notch shell
- `services/agent/` Python FastAPI local agent
- `packages/shared/` shared contracts and types
- `docs/` PRD and implementation notes

## Current Implementation (Phase 1 Spine)

- Notch-style desktop shell in `apps/desktop` with PRD tab layout.
- Local-first quick toggles and offline sync queue persistence.
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
- Memory tab UI for note creation and retrieval.

## Run Desktop

```bash
pnpm install
pnpm dev:desktop
```

## Run Agent

```bash
python -m pip install -e services/agent[dev]
pnpm dev:agent
```

## Test Agent

```bash
pnpm test:agent
```
