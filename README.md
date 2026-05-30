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
