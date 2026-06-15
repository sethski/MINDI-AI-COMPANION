"""Security scanning, event management, and process recovery.

SecurityService holds all logic that was previously spread across RuntimeStore.
It receives a RuntimeStore reference at construction time to share mutable state
(security_events, alerts, logs) without copying or duplicating it.
"""

from __future__ import annotations

import csv
import io
import subprocess
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    AlertItem,
    SecurityEvent,
    SecurityRecoveryRequest,
    SecurityRecoveryResponse,
    SecurityScanResponse,
    now_iso,
)

SUSPICIOUS_PROCESS_RULES: dict[str, tuple[str, str]] = {
    "mimikatz.exe": ("critical", "Credential dumping tool detected."),
    "psexec.exe": ("warning", "Remote execution tool detected."),
    "procdump.exe": ("warning", "Process dump utility detected."),
    "ncat.exe": ("warning", "Network tunneling utility detected."),
    "nc.exe": ("warning", "Network tunneling utility detected."),
}


def parse_tasklist_csv(stdout: str) -> list[tuple[str, int | None]]:
    rows: list[tuple[str, int | None]] = []
    reader = csv.reader(io.StringIO(stdout))
    for row in reader:
        if len(row) < 2:
            continue
        process_name = row[0].strip().strip('"')
        pid_text = row[1].strip().strip('"')
        try:
            pid_value: int | None = int(pid_text.replace(",", ""))
        except ValueError:
            pid_value = None
        if process_name:
            rows.append((process_name, pid_value))
    return rows


class SecurityService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def create_security_event(
        self,
        *,
        severity: str,
        title: str,
        detail: str,
        source: str,
        process_name: str | None = None,
        pid: int | None = None,
        recovery_actions: list[str] | None = None,
    ) -> SecurityEvent:
        event = SecurityEvent(
            id=str(uuid4()),
            severity=severity,  # type: ignore[arg-type]
            title=title,
            detail=detail,
            source=source,  # type: ignore[arg-type]
            status="open",
            processName=process_name,
            pid=pid,
            recoveryActions=recovery_actions or ["dismiss"],
            createdAt=now_iso(),
            resolvedAt=None,
        )
        self._store.security_events.insert(0, event)
        self._store.alerts.insert(
            0,
            AlertItem(
                id=str(uuid4()),
                severity=event.severity,
                title=f"Security: {event.title}",
                detail=event.detail,
                createdAt=event.createdAt,
            ),
        )
        self._store.alerts = self._store.alerts[:100]
        return event

    def list_security_events(self, status: str = "open", limit: int = 25) -> list[SecurityEvent]:
        normalized = status.strip().lower()
        items = self._store.security_events
        if normalized in {"open", "resolved"}:
            items = [e for e in self._store.security_events if e.status == normalized]
        return items[: max(1, min(limit, 200))]

    def scan_security(self) -> SecurityScanResponse:
        new_events: list[SecurityEvent] = []
        process_rows: list[tuple[str, int | None]] = []

        try:
            tasklist = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                check=False,
                capture_output=True,
                text=True,
            )
            if tasklist.returncode == 0:
                process_rows = parse_tasklist_csv(tasklist.stdout or "")
        except Exception:
            self._store.security_last_error = "tasklist_failed"

        known_open_keys = {
            f"{event.processName or ''}:{event.pid or ''}:{event.title}"
            for event in self._store.security_events
            if event.status == "open"
        }

        for process_name, pid in process_rows:
            lowered = process_name.lower()
            if lowered not in SUSPICIOUS_PROCESS_RULES:
                continue
            severity, detail = SUSPICIOUS_PROCESS_RULES[lowered]
            title = f"Suspicious process {process_name}"
            key = f"{process_name}:{pid or ''}:{title}"
            if key in known_open_keys:
                continue
            event = self.create_security_event(
                severity=severity,
                title=title,
                detail=detail,
                source="process_scan",
                process_name=process_name,
                pid=pid,
                recovery_actions=["kill_process", "deny_app", "dismiss"],
            )
            new_events.append(event)
            known_open_keys.add(key)

        try:
            defender = subprocess.run(
                ["sc", "query", "WinDefend"],
                check=False,
                capture_output=True,
                text=True,
            )
            if defender.returncode == 0 and "RUNNING" not in (defender.stdout or "").upper():
                title = "Windows Defender service not running"
                key = f":::{title}"
                if key not in known_open_keys:
                    event = self.create_security_event(
                        severity="critical",
                        title=title,
                        detail="Built-in malware protection service is not in RUNNING state.",
                        source="defender_service",
                        recovery_actions=["dismiss"],
                    )
                    new_events.append(event)
                    known_open_keys.add(key)
        except Exception:
            self._store.security_last_error = "defender_query_failed"

        self._store.security_last_scan = now_iso()
        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="security_scan",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"events:{len(new_events)}",
                createdAt=now_iso(),
            ),
        )
        return SecurityScanResponse(
            accepted=True,
            reason="ok",
            scannedProcessCount=len(process_rows),
            newAlerts=len(new_events),
            events=new_events,
        )

    def recover_security_event(self, request: SecurityRecoveryRequest) -> SecurityRecoveryResponse:
        event = next((item for item in self._store.security_events if item.id == request.eventId), None)
        if event is None:
            return SecurityRecoveryResponse(accepted=False, reason="event_not_found")
        if event.status == "resolved":
            return SecurityRecoveryResponse(accepted=False, reason="event_already_resolved", event=event)

        action = request.action
        target = (request.target or "").strip()

        if action == "dismiss":
            event.status = "resolved"
            event.resolvedAt = now_iso()
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent=f"security_recover:dismiss:{event.id}",
                    tier=ActionTier.reversible,
                    result="allowed",
                    reason="dismissed",
                    createdAt=now_iso(),
                ),
            )
            return SecurityRecoveryResponse(accepted=True, reason="dismissed", event=event)

        if action == "deny_app":
            app_target = target or (event.processName or "")
            if not app_target:
                return SecurityRecoveryResponse(accepted=False, reason="target_required", event=event)
            self._store.add_permission(
                AddPermissionGrantRequest(
                    scope="app",
                    subject=app_target,
                    decision="deny",
                )
            )
            event.status = "resolved"
            event.resolvedAt = now_iso()
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent=f"security_recover:deny_app:{app_target}",
                    tier=ActionTier.reversible,
                    result="allowed",
                    reason="app_denied",
                    createdAt=now_iso(),
                ),
            )
            return SecurityRecoveryResponse(accepted=True, reason="app_denied", event=event)

        if action == "kill_process":
            process_target = target or (event.processName or "")
            if not process_target:
                return SecurityRecoveryResponse(accepted=False, reason="target_required", event=event)
            if not request.confirm:
                return SecurityRecoveryResponse(accepted=False, reason="confirmation_required", event=event)
            try:
                subprocess.run(
                    ["taskkill", "/IM", process_target, "/T"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return SecurityRecoveryResponse(accepted=False, reason="kill_failed", event=event)
            event.status = "resolved"
            event.resolvedAt = now_iso()
            self._store.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent=f"security_recover:kill_process:{process_target}",
                    tier=ActionTier.risky,
                    result="allowed",
                    reason="kill_requested",
                    createdAt=now_iso(),
                ),
            )
            return SecurityRecoveryResponse(accepted=True, reason="kill_requested", event=event)

        return SecurityRecoveryResponse(accepted=False, reason="unsupported_action", event=event)
