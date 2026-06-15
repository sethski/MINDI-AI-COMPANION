"""Automation chains, alerts feed, and app control."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionLogItem,
    ActionTier,
    AlertActionRequest,
    AlertActionResponse,
    AlertFeedResponse,
    AppControlRequest,
    AppControlResponse,
    AutomationChainRequest,
    AutomationChainResponse,
    AutomationChainStepResult,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    WebScrapeRequest,
    now_iso,
)


class AutomationService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def run_automation_chain(self, request: AutomationChainRequest) -> AutomationChainResponse:
        chain_name = (request.name or "").strip() or "ops_chain"
        if not request.steps:
            return AutomationChainResponse(
                accepted=False, reason="empty_steps", name=chain_name,
                totalSteps=0, completedSteps=0, steps=[],
            )

        results: list[AutomationChainStepResult] = []
        completed_steps = 0
        failed_step_index: int | None = None
        recovery_summary: str | None = None

        for index, step in enumerate(request.steps):
            started_at = now_iso()
            accepted = False
            reason = "unsupported_step"
            recovery_hint: str | None = "Use one of: web_scrape, create_task, create_note, security_scan."
            detail: str | None = None

            if step.kind == "web_scrape":
                if not (step.url or "").strip():
                    reason = "url_required"
                    recovery_hint = "Provide a valid HTTP/HTTPS URL."
                else:
                    scrape = self._store.scrape_web(
                        WebScrapeRequest(url=(step.url or "").strip(), maxChars=3500, storeAsNote=bool(step.storeAsNote))
                    )
                    accepted = scrape.accepted
                    reason = scrape.reason
                    detail = f"textLength={scrape.textLength}, links={len(scrape.links)}"
                    recovery_hint = (
                        "Allow the domain then retry." if scrape.reason == "domain_not_allowed"
                        else "Check URL accessibility and content type."
                    )
            elif step.kind == "create_task":
                title = (step.title or "").strip()
                if not title:
                    reason = "title_required"
                    recovery_hint = "Provide a task title."
                else:
                    task = self._store.add_task(
                        CreateTaskRequest(title=title, dueAt=(step.dueAt or None), recurrence=step.recurrence)
                    )
                    accepted = True
                    reason = "ok"
                    detail = f"taskId={task.id}"
                    recovery_hint = None
            elif step.kind == "create_note":
                title = (step.title or "").strip()
                text = (step.text or "").strip()
                if not title or not text:
                    reason = "title_and_text_required"
                    recovery_hint = "Provide note title and text."
                else:
                    note = self._store.add_memory_note(
                        CreateMemoryNoteRequest(title=title, content=text, tags=["automation", "ops"])
                    )
                    accepted = True
                    reason = "ok"
                    detail = f"noteId={note.id}"
                    recovery_hint = None
            elif step.kind == "security_scan":
                scan = self._store.scan_security()
                accepted = scan.accepted
                reason = scan.reason
                detail = f"newAlerts={scan.newAlerts}, scanned={scan.scannedProcessCount}"
                recovery_hint = "Review open security events and apply recovery actions."

            finished_at = now_iso()
            results.append(AutomationChainStepResult(
                index=index, kind=step.kind, accepted=accepted, reason=reason,
                startedAt=started_at, finishedAt=finished_at,
                recoveryHint=recovery_hint, detail=detail,
            ))

            if accepted:
                completed_steps += 1
                continue
            failed_step_index = index
            recovery_summary = f"Step {index + 1} failed ({step.kind}): {reason}."
            if not request.continueOnFailure:
                break

        accepted_chain = failed_step_index is None
        chain_reason = "ok" if accepted_chain else "partial_failure"
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"automation_chain:{chain_name}",
                tier=ActionTier.reversible,
                result="allowed" if accepted_chain else "blocked",
                reason=f"{chain_reason}:completed={completed_steps}/{len(request.steps)}",
                createdAt=now_iso(),
            ),
        )
        return AutomationChainResponse(
            accepted=accepted_chain, reason=chain_reason, name=chain_name,
            totalSteps=len(request.steps), completedSteps=completed_steps,
            failedStepIndex=failed_step_index, steps=results, recoverySummary=recovery_summary,
        )

    def alerts_feed(self, limit: int = 25) -> AlertFeedResponse:
        severity_weight = {"critical": 3, "warning": 2, "info": 1}
        ranked = sorted(
            self._store.alerts,
            key=lambda item: (severity_weight.get(item.severity, 0), item.createdAt),
            reverse=True,
        )
        trimmed = ranked[: max(1, min(limit, 200))]
        critical = sum(1 for item in self._store.alerts if item.severity == "critical")
        warning = sum(1 for item in self._store.alerts if item.severity == "warning")
        info = sum(1 for item in self._store.alerts if item.severity == "info")
        return AlertFeedResponse(
            accepted=True, reason="ok", total=len(self._store.alerts),
            critical=critical, warning=warning, info=info, items=trimmed,
        )

    def alerts_action(self, request: AlertActionRequest) -> AlertActionResponse:
        alert = next((item for item in self._store.alerts if item.id == request.alertId), None)
        if alert is None:
            return AlertActionResponse(accepted=False, reason="alert_not_found")

        if request.action == "dismiss":
            self._store.alerts = [item for item in self._store.alerts if item.id != request.alertId]
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()), intent=f"alerts_action:dismiss:{request.alertId}",
                    tier=ActionTier.reversible, result="allowed", reason="dismissed", createdAt=now_iso(),
                ),
            )
            return AlertActionResponse(accepted=True, reason="dismissed")

        if request.action == "create_recovery_task":
            task = self._store.add_task(CreateTaskRequest(title=f"Recovery: {alert.title}", dueAt=None, recurrence=None))
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()), intent=f"alerts_action:create_recovery_task:{request.alertId}",
                    tier=ActionTier.reversible, result="allowed", reason=f"task:{task.id}", createdAt=now_iso(),
                ),
            )
            return AlertActionResponse(accepted=True, reason="recovery_task_created", createdTaskId=task.id)

        if request.action == "export_report":
            export_dir = Path("data/runtime/exports").resolve()
            export_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = export_dir / f"mindi-alert-report-{timestamp}.json"
            payload = {
                "generatedAt": now_iso(),
                "alert": alert.model_dump(),
                "recentLogs": [item.model_dump() for item in self._store.logs[:20]],
            }
            path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()), intent=f"alerts_action:export_report:{request.alertId}",
                    tier=ActionTier.reversible, result="allowed", reason=str(path), createdAt=now_iso(),
                ),
            )
            return AlertActionResponse(accepted=True, reason="report_exported", reportPath=str(path))

        return AlertActionResponse(accepted=False, reason="unsupported_action")

    def control_app(self, request: AppControlRequest) -> AppControlResponse:
        app_id = request.appId.strip()
        if not app_id:
            return AppControlResponse(
                accepted=False, reason="app_id_required",
                tier=ActionTier.read_only, requiresConfirmation=False,
            )
        if not self._store._is_app_allowed(app_id):
            return AppControlResponse(
                accepted=False, reason="app_not_allowlisted",
                tier=ActionTier.risky, requiresConfirmation=False,
            )

        tier = ActionTier.reversible
        requires_confirmation = False
        if request.action == "close":
            tier = ActionTier.risky
            if not request.confirm:
                return AppControlResponse(
                    accepted=False, reason="confirmation_required_for_close",
                    tier=tier, requiresConfirmation=True,
                )
            requires_confirmation = True

        try:
            if request.action == "open":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", app_id],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                reason = "opened"
            elif request.action == "close":
                subprocess.run(
                    ["taskkill", "/IM", app_id, "/T"],
                    check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                reason = "close_requested"
            else:
                reason = "focus_requested"
        except Exception as exc:
            return AppControlResponse(
                accepted=False, reason=f"app_control_failed:{exc.__class__.__name__}",
                tier=tier, requiresConfirmation=requires_confirmation,
            )

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()), intent=f"app_control:{request.action}:{app_id}",
                tier=tier, result="allowed", reason=reason, createdAt=now_iso(),
            ),
        )
        return AppControlResponse(accepted=True, reason=reason, tier=tier, requiresConfirmation=requires_confirmation)
