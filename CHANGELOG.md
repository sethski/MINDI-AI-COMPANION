# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Hybrid offline-to-online sync worker in desktop app with queued action replay and exponential backoff.
- Task management expansion:
  - status transitions (`todo`, `in_progress`, `done`)
  - edit task fields (`title`, `dueAt`, `recurrence`, `status`)
  - delete task API and UI action
- Calendar hardening:
  - UID-first dedupe with title+due fallback
  - TZID-aware `DTSTART` import with fallback timezone resolver
  - `VALARM` trigger parsing and reminder export
  - `EXDATE` exclusion handling
- Playwright E2E coverage for task lifecycle and calendar import/export dedupe.
- GitHub Actions CI workflow running agent tests, desktop build, and E2E tests.

### Changed
- README now documents hybrid sync replay, hardened calendar behavior, and E2E test command.

## [0.1.0] - 2026-05-26

### Added
- Initial Windows-first MINDI shell and local FastAPI agent foundation.
- Control, memory ingestion, OCR, scheduler, and calendar export/import baseline.
