import base64
import binascii
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import io
from pathlib import Path
import re
from shutil import move
import subprocess
from threading import Event, Thread
from time import time
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo
from PIL import Image

from .memory_db import ALLOWED_DOCUMENT_SUFFIXES, MemoryDB
from .ocr_service import OCR_IMAGE_SUFFIXES, extract_text_for_ocr
from .schemas import (
    AutoIndexStatus,
    SchedulerStatus,
    SecurityEvent,
    AutomationChainRequest,
    AutomationChainResponse,
    AutomationChainStepResult,
    SecurityRecoveryRequest,
    SecurityRecoveryResponse,
    SecurityScanResponse,
    TaskNextRunRequest,
    TaskNextRunResponse,
    TaskTimeParseRequest,
    TaskTimeParseResponse,
    CalendarExportRequest,
    CalendarExportResponse,
    CalendarImportRequest,
    CalendarImportResponse,
    AppControlRequest,
    AppControlResponse,
    ActionLogItem,
    ActionTier,
    AddPermissionGrantRequest,
    AlertItem,
    AgentStatus,
    AssistantRequest,
    AssistantResponse,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
    DocumentImportRequest,
    DocumentImportResponse,
    DocumentSearchResponse,
    FileOrganizeItem,
    FileOrganizeRequest,
    FileOrganizeResponse,
    HubSnapshot,
    MemoryDocument,
    MemoryDocumentChunk,
    MemoryNote,
    MemorySearchResponse,
    OcrImportRequest,
    OcrImportResponse,
    PerceptionAnalyzeRequest,
    PerceptionAnalyzeResponse,
    PerceptionPermissionStatus,
    PerceptionSnapshot,
    PerceptionSnapshotSearchResponse,
    PerceptionUiBlock,
    PermissionGrant,
    PolicyDecision,
    SyncQueueRequest,
    TaskItem,
    WebScrapeRequest,
    WebScrapeResponse,
    now_iso,
)

PERCEPTION_SCREEN_SUBJECT = "perception.screen.capture"
PERCEPTION_CAMERA_SUBJECT = "perception.camera.capture"
SUSPICIOUS_PROCESS_RULES: dict[str, tuple[str, str]] = {
    "mimikatz.exe": ("critical", "Credential dumping tool detected."),
    "psexec.exe": ("warning", "Remote execution tool detected."),
    "procdump.exe": ("warning", "Process dump utility detected."),
    "ncat.exe": ("warning", "Network tunneling utility detected."),
    "nc.exe": ("warning", "Network tunneling utility detected."),
}


class _ScrapeHtmlParser(HTMLParser):
    def __init__(self, base_url: str, max_links: int = 20) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_links = max_links
        self.title: str | None = None
        self._capture_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self._capture_title = True
        if normalized in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if normalized == "a" and len(self._links) < self.max_links:
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value.strip()
                    break
            if href:
                joined = urljoin(self.base_url, href)
                if joined not in self._links:
                    self._links.append(joined)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self._capture_title = False
        if normalized in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._capture_title:
            if self.title:
                self.title = f"{self.title} {text}".strip()
            else:
                self.title = text
            return
        self._chunks.append(text)

    def parsed_text(self, max_chars: int) -> str:
        joined = " ".join(self._chunks)
        return joined[:max_chars].strip()

    def parsed_links(self) -> list[str]:
        return self._links


def _category_for_suffix(suffix: str) -> str:
    by_suffix = {
        ".png": "images",
        ".jpg": "images",
        ".jpeg": "images",
        ".gif": "images",
        ".webp": "images",
        ".pdf": "documents",
        ".docx": "documents",
        ".txt": "documents",
        ".md": "documents",
        ".csv": "data",
        ".json": "data",
        ".zip": "archives",
        ".7z": "archives",
    }
    return by_suffix.get(suffix.lower(), "other")


@dataclass
class RuntimeStore:
    started_at: float = field(default_factory=time)
    tasks: list[TaskItem] = field(default_factory=list)
    alerts: list[AlertItem] = field(default_factory=list)
    logs: list[ActionLogItem] = field(default_factory=list)
    sync_queue: list[dict] = field(default_factory=list)
    permission_grants: list[PermissionGrant] = field(default_factory=list)
    memory_db: MemoryDB = field(default_factory=MemoryDB)
    auto_index_stop: Event = field(default_factory=Event)
    auto_index_thread: Thread | None = field(default=None, init=False)
    auto_index_last_scan: str | None = None
    auto_index_last_error: str | None = None
    auto_index_indexed_total: int = 0
    auto_index_indexed_last_run: int = 0
    auto_index_seen_mtime: dict[str, int] = field(default_factory=dict)
    scheduler_stop: Event = field(default_factory=Event)
    scheduler_thread: Thread | None = field(default=None, init=False)
    scheduler_last_scan: str | None = None
    scheduler_last_error: str | None = None
    scheduler_alerts_total: int = 0
    scheduler_alerts_last_run: int = 0
    scheduler_alerted_due: dict[str, str] = field(default_factory=dict)
    security_events: list[SecurityEvent] = field(default_factory=list)
    security_last_scan: str | None = None
    security_last_error: str | None = None

    def __post_init__(self) -> None:
        # Safe default for local file organization sandbox.
        self.permission_grants.append(
            PermissionGrant(
                id=str(uuid4()),
                scope="folder",
                subject="data",
                decision="allow",
                createdAt=now_iso(),
            )
        )
        self.start_auto_indexer()
        self.start_scheduler()
        self.permission_grants.append(
            PermissionGrant(
                id=str(uuid4()),
                scope="app",
                subject="notepad.exe",
                decision="allow",
                createdAt=now_iso(),
            )
        )

    def status(self) -> AgentStatus:
        return AgentStatus(
            state="ready",
            uptimeSeconds=max(0, int(time() - self.started_at)),
            listening=True,
            agentVersion="0.2.0",
            currentProfile="safe",
        )

    def snapshot(self) -> HubSnapshot:
        return HubSnapshot(
            status=self.status(),
            alerts=self.alerts[:5],
            tasks=self.tasks[:10],
            logs=self.logs[:10],
        )

    def policy_decision(self, request: AssistantRequest) -> PolicyDecision:
        text = request.text.lower()
        risky_terms = ["delete", "remove", "uninstall", "registry", "firewall", "credential"]
        if any(term in text for term in risky_terms):
            return PolicyDecision(
                allowed=False,
                tier=ActionTier.risky,
                reason="requires_confirmation_or_unlock",
                requiresUnlock=True,
            )
        return PolicyDecision(
            allowed=True,
            tier=ActionTier.read_only,
            reason="safe_read_or_chat",
            requiresUnlock=False,
        )

    def respond(self, request: AssistantRequest) -> AssistantResponse:
        decision = self.policy_decision(request)
        result = "allowed" if decision.allowed else "blocked"
        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=request.text,
                tier=decision.tier,
                result=result,
                reason=decision.reason,
                createdAt=now_iso(),
            ),
        )
        if decision.allowed:
            latest_snapshot = self.memory_db.latest_perception_snapshot()
            lowered = (request.text or "").lower()
            asks_about_screen = any(
                term in lowered
                for term in ("screen", "vision", "display", "what do you see", "what's on screen", "ocr")
            )
            if asks_about_screen and latest_snapshot is not None:
                snippet = (latest_snapshot.text or "").strip()
                summary = snippet[:220] if snippet else "No OCR text available."
                reply = (
                    "Latest perception snapshot available. "
                    f"Captured at {latest_snapshot.createdAt}, blocks={latest_snapshot.blockCount}, "
                    f"textLength={latest_snapshot.textLength}. "
                    f"Summary: {summary}"
                )
            else:
                reply = "Acknowledged. I can proceed locally and keep this action in audit logs."
            suggestions = ["Create note", "Add task", "Show status"]
            status = "ready"
        else:
            reply = "Blocked for safety. Confirm or unlock before risky execution."
            suggestions = ["Explain risk", "Request confirmation", "Open safety panel"]
            status = "blocked"
        return AssistantResponse(
            reply=reply,
            decision=decision,
            suggestedActions=suggestions,
            status=status,
        )

    def add_task(self, request: CreateTaskRequest) -> TaskItem:
        task = TaskItem(
            id=str(uuid4()),
            externalId=None,
            title=request.title,
            dueAt=request.dueAt,
            recurrence=request.recurrence,
            reminderMinutesBefore=None,
            nextRunAt=request.dueAt,
            status="todo",
            source="manual",
        )
        self.tasks.insert(0, task)
        if task.id in self.scheduler_alerted_due:
            self.scheduler_alerted_due.pop(task.id, None)
        return task

    def update_task_status(self, task_id: str, request: TaskStatusUpdateRequest) -> TaskItem | None:
        for task in self.tasks:
            if task.id != task_id:
                continue
            task.status = request.status
            if request.status != "done":
                self.scheduler_alerted_due.pop(task.id, None)
            return task
        return None

    def update_task(self, task_id: str, request: TaskUpdateRequest) -> TaskItem | None:
        for task in self.tasks:
            if task.id != task_id:
                continue
            if "title" in request.model_fields_set and request.title is not None:
                task.title = request.title
            if "dueAt" in request.model_fields_set:
                task.dueAt = request.dueAt
                task.nextRunAt = request.dueAt
                self.scheduler_alerted_due.pop(task.id, None)
            if "recurrence" in request.model_fields_set:
                task.recurrence = request.recurrence
            if "status" in request.model_fields_set and request.status is not None:
                task.status = request.status
                if request.status != "done":
                    self.scheduler_alerted_due.pop(task.id, None)
            return task
        return None

    def delete_task(self, task_id: str) -> TaskItem | None:
        for index, task in enumerate(self.tasks):
            if task.id != task_id:
                continue
            removed = self.tasks.pop(index)
            self.scheduler_alerted_due.pop(task_id, None)
            return removed
        return None

    def enqueue_sync(self, request: SyncQueueRequest) -> dict:
        item = {
            "id": str(uuid4()),
            "type": request.type,
            "payload": request.payload,
            "createdAt": now_iso(),
            "status": "queued",
        }
        self.sync_queue.insert(0, item)
        return item

    def list_permissions(self) -> list[PermissionGrant]:
        return self.permission_grants

    def add_permission(self, request: AddPermissionGrantRequest) -> PermissionGrant:
        grant = PermissionGrant(
            id=str(uuid4()),
            scope=request.scope,
            subject=request.subject,
            decision=request.decision,
            createdAt=now_iso(),
        )
        self.permission_grants.insert(0, grant)
        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"permission_grant:{grant.scope}:{grant.subject}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"decision:{grant.decision}",
                createdAt=now_iso(),
            ),
        )
        return grant

    @staticmethod
    def _subject_matches(grant_subject: str, target_subject: str) -> bool:
        grant_value = grant_subject.strip().lower()
        target_value = target_subject.strip().lower()
        if not grant_value:
            return False
        if grant_value == "*" or grant_value == target_value:
            return True
        if grant_value.endswith("*"):
            return target_value.startswith(grant_value[:-1])
        return False

    def _resolve_action_permission_decision(self, subject: str) -> str:
        normalized = subject.strip().lower()
        if not normalized:
            return "deny"
        for grant in self.permission_grants:
            if grant.scope != "action":
                continue
            if self._subject_matches(grant.subject, normalized):
                return grant.decision
        return "unset"

    def _is_action_allowed(self, subject: str) -> bool:
        return self._resolve_action_permission_decision(subject) == "allow"

    def perception_permission_status(self) -> PerceptionPermissionStatus:
        screen_decision = self._resolve_action_permission_decision(PERCEPTION_SCREEN_SUBJECT)
        camera_decision = self._resolve_action_permission_decision(PERCEPTION_CAMERA_SUBJECT)
        return PerceptionPermissionStatus(
            screenSubject=PERCEPTION_SCREEN_SUBJECT,
            cameraSubject=PERCEPTION_CAMERA_SUBJECT,
            screenAllowed=screen_decision == "allow",
            cameraAllowed=camera_decision == "allow",
            screenDecision=screen_decision,
            cameraDecision=camera_decision,
        )

    def list_allowed_apps(self) -> list[str]:
        app_grants = [grant for grant in self.permission_grants if grant.scope == "app"]
        denied = {grant.subject.lower() for grant in app_grants if grant.decision == "deny"}
        allowed = [grant.subject for grant in app_grants if grant.decision == "allow"]
        return [app for app in allowed if app.lower() not in denied]

    def _is_app_allowed(self, app_id: str) -> bool:
        return app_id.lower() in {app.lower() for app in self.list_allowed_apps()}

    def _resolve_domain_permission_decision(self, hostname: str) -> str:
        host = hostname.strip().lower()
        if not host:
            return "deny"
        domain_grants = [grant for grant in self.permission_grants if grant.scope == "domain"]
        for grant in domain_grants:
            subject = grant.subject.strip().lower()
            if not subject:
                continue
            if subject == "*" or host == subject or host.endswith(f".{subject}"):
                return grant.decision
            if subject.startswith("*."):
                root = subject[2:]
                if host == root or host.endswith(f".{root}"):
                    return grant.decision
        return "unset"

    def _is_domain_allowed(self, hostname: str) -> bool:
        decision = self._resolve_domain_permission_decision(hostname)
        if decision == "deny":
            return False
        domain_grants = [grant for grant in self.permission_grants if grant.scope == "domain"]
        has_allow = any(grant.decision == "allow" for grant in domain_grants)
        if has_allow:
            return decision == "allow"
        return True

    def _is_path_allowed(self, path: Path) -> bool:
        normalized = path.resolve()
        grants = [g for g in self.permission_grants if g.scope == "folder"]
        denies = [Path(g.subject).resolve() for g in grants if g.decision == "deny"]
        allows = [Path(g.subject).resolve() for g in grants if g.decision == "allow"]

        if any(str(normalized).startswith(str(deny)) for deny in denies):
            return False
        if not allows:
            return False
        return any(str(normalized).startswith(str(allow)) for allow in allows)

    def file_organize(self, request: FileOrganizeRequest) -> FileOrganizeResponse:
        source = Path(request.sourceDir).resolve()
        target = Path(request.targetDir).resolve()

        if not source.exists() or not source.is_dir():
            return FileOrganizeResponse(
                accepted=False,
                reason="source_not_found",
                movedCount=0,
                items=[],
            )

        if not self._is_path_allowed(source) or not self._is_path_allowed(target):
            return FileOrganizeResponse(
                accepted=False,
                reason="folder_not_allowed",
                movedCount=0,
                items=[],
            )

        items: list[FileOrganizeItem] = []
        for child in source.iterdir():
            if child.is_file():
                category = _category_for_suffix(child.suffix)
                dest = target / category / child.name
                items.append(
                    FileOrganizeItem(
                        fileName=child.name,
                        sourcePath=str(child),
                        targetPath=str(dest),
                        category=category,
                    )
                )

        if request.mode == "apply":
            for item in items:
                destination = Path(item.targetPath)
                destination.parent.mkdir(parents=True, exist_ok=True)
                move(item.sourcePath, item.targetPath)
            reason = "applied"
        else:
            reason = "preview_only"

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"file_organize:{request.mode}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=reason,
                createdAt=now_iso(),
            ),
        )

        return FileOrganizeResponse(
            accepted=True,
            reason=reason,
            movedCount=len(items) if request.mode == "apply" else 0,
            items=items,
        )

    def scrape_web(self, request: WebScrapeRequest) -> WebScrapeResponse:
        raw_url = (request.url or "").strip()
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return WebScrapeResponse(
                accepted=False,
                reason="invalid_url",
                url=raw_url,
            )

        host = parsed.hostname or ""
        if not self._is_domain_allowed(host):
            return WebScrapeResponse(
                accepted=False,
                reason="domain_not_allowed",
                url=raw_url,
            )

        headers = {
            "User-Agent": "MINDI-Local-Agent/0.2 (+local-safe-scrape)",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.2",
        }
        http_request = Request(raw_url, headers=headers, method="GET")

        try:
            with urlopen(http_request, timeout=10) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                body = response.read(512_000)
        except URLError:
            return WebScrapeResponse(
                accepted=False,
                reason="fetch_failed",
                url=raw_url,
            )
        except Exception:
            return WebScrapeResponse(
                accepted=False,
                reason="fetch_error",
                url=raw_url,
            )

        if not body:
            return WebScrapeResponse(
                accepted=False,
                reason="empty_response",
                url=raw_url,
            )

        decoded = body.decode("utf-8", errors="ignore")
        title: str | None = None
        links: list[str] = []
        text_content = ""

        if "text/html" in content_type or "<html" in decoded.lower():
            parser = _ScrapeHtmlParser(base_url=raw_url, max_links=20)
            parser.feed(decoded)
            parser.close()
            title = parser.title
            links = parser.parsed_links()
            text_content = parser.parsed_text(max_chars=request.maxChars)
        elif "text/plain" in content_type:
            text_content = " ".join(decoded.split())[: request.maxChars].strip()
        else:
            return WebScrapeResponse(
                accepted=False,
                reason="unsupported_content_type",
                url=raw_url,
            )

        stored_note_id: str | None = None
        if request.storeAsNote and text_content:
            note_title = (title or parsed.netloc or raw_url)[:140]
            note = self.add_memory_note(
                CreateMemoryNoteRequest(
                    title=f"Web scrape: {note_title}",
                    content=text_content,
                    tags=["web", "ops", "scrape"],
                )
            )
            stored_note_id = note.id

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"web_scrape:{parsed.netloc}",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"text:{len(text_content)}",
                createdAt=now_iso(),
            ),
        )

        return WebScrapeResponse(
            accepted=True,
            reason="ok",
            url=raw_url,
            title=title,
            text=text_content,
            textLength=len(text_content),
            links=links,
            storedNoteId=stored_note_id,
        )

    def run_automation_chain(self, request: AutomationChainRequest) -> AutomationChainResponse:
        chain_name = (request.name or "").strip() or "ops_chain"
        if not request.steps:
            return AutomationChainResponse(
                accepted=False,
                reason="empty_steps",
                name=chain_name,
                totalSteps=0,
                completedSteps=0,
                steps=[],
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
                    scrape = self.scrape_web(
                        WebScrapeRequest(
                            url=(step.url or "").strip(),
                            maxChars=3500,
                            storeAsNote=bool(step.storeAsNote),
                        )
                    )
                    accepted = scrape.accepted
                    reason = scrape.reason
                    detail = f"textLength={scrape.textLength}, links={len(scrape.links)}"
                    recovery_hint = (
                        "Allow the domain then retry."
                        if scrape.reason == "domain_not_allowed"
                        else "Check URL accessibility and content type."
                    )
            elif step.kind == "create_task":
                title = (step.title or "").strip()
                if not title:
                    reason = "title_required"
                    recovery_hint = "Provide a task title."
                else:
                    task = self.add_task(
                        CreateTaskRequest(
                            title=title,
                            dueAt=(step.dueAt or None),
                            recurrence=step.recurrence,
                        )
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
                    note = self.add_memory_note(
                        CreateMemoryNoteRequest(
                            title=title,
                            content=text,
                            tags=["automation", "ops"],
                        )
                    )
                    accepted = True
                    reason = "ok"
                    detail = f"noteId={note.id}"
                    recovery_hint = None
            elif step.kind == "security_scan":
                scan = self.scan_security()
                accepted = scan.accepted
                reason = scan.reason
                detail = f"newAlerts={scan.newAlerts}, scanned={scan.scannedProcessCount}"
                recovery_hint = "Review open security events and apply recovery actions."

            finished_at = now_iso()
            results.append(
                AutomationChainStepResult(
                    index=index,
                    kind=step.kind,
                    accepted=accepted,
                    reason=reason,
                    startedAt=started_at,
                    finishedAt=finished_at,
                    recoveryHint=recovery_hint,
                    detail=detail,
                )
            )

            if accepted:
                completed_steps += 1
                continue

            failed_step_index = index
            recovery_summary = f"Step {index + 1} failed ({step.kind}): {reason}."
            if not request.continueOnFailure:
                break

        accepted_chain = failed_step_index is None
        chain_reason = "ok" if accepted_chain else "partial_failure"

        self.logs.insert(
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
            accepted=accepted_chain,
            reason=chain_reason,
            name=chain_name,
            totalSteps=len(request.steps),
            completedSteps=completed_steps,
            failedStepIndex=failed_step_index,
            steps=results,
            recoverySummary=recovery_summary,
        )

    @staticmethod
    def _parse_tasklist_csv(stdout: str) -> list[tuple[str, int | None]]:
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

    def _create_security_event(
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
        self.security_events.insert(0, event)
        self.alerts.insert(
            0,
            AlertItem(
                id=str(uuid4()),
                severity=event.severity,
                title=f"Security: {event.title}",
                detail=event.detail,
                createdAt=event.createdAt,
            ),
        )
        self.alerts = self.alerts[:100]
        return event

    def list_security_events(self, status: str = "open", limit: int = 25) -> list[SecurityEvent]:
        normalized = status.strip().lower()
        items = self.security_events
        if normalized in {"open", "resolved"}:
            items = [event for event in self.security_events if event.status == normalized]
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
                process_rows = self._parse_tasklist_csv(tasklist.stdout or "")
        except Exception:
            self.security_last_error = "tasklist_failed"

        known_open_keys = {
            f"{event.processName or ''}:{event.pid or ''}:{event.title}"
            for event in self.security_events
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
            event = self._create_security_event(
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
                    event = self._create_security_event(
                        severity="critical",
                        title=title,
                        detail="Built-in malware protection service is not in RUNNING state.",
                        source="defender_service",
                        recovery_actions=["dismiss"],
                    )
                    new_events.append(event)
                    known_open_keys.add(key)
        except Exception:
            self.security_last_error = "defender_query_failed"

        self.security_last_scan = now_iso()
        self.logs.insert(
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
        event = next((item for item in self.security_events if item.id == request.eventId), None)
        if event is None:
            return SecurityRecoveryResponse(accepted=False, reason="event_not_found")
        if event.status == "resolved":
            return SecurityRecoveryResponse(accepted=False, reason="event_already_resolved", event=event)

        action = request.action
        target = (request.target or "").strip()

        if action == "dismiss":
            event.status = "resolved"
            event.resolvedAt = now_iso()
            self.logs.insert(
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
            self.add_permission(
                AddPermissionGrantRequest(
                    scope="app",
                    subject=app_target,
                    decision="deny",
                )
            )
            event.status = "resolved"
            event.resolvedAt = now_iso()
            self.logs.insert(
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
            self.logs.insert(
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

    def control_app(self, request: AppControlRequest) -> AppControlResponse:
        app_id = request.appId.strip()
        if not app_id:
            return AppControlResponse(
                accepted=False,
                reason="app_id_required",
                tier=ActionTier.read_only,
                requiresConfirmation=False,
            )

        if not self._is_app_allowed(app_id):
            return AppControlResponse(
                accepted=False,
                reason="app_not_allowlisted",
                tier=ActionTier.risky,
                requiresConfirmation=False,
            )

        tier = ActionTier.reversible
        requires_confirmation = False
        if request.action == "close":
            tier = ActionTier.risky
            if not request.confirm:
                return AppControlResponse(
                    accepted=False,
                    reason="confirmation_required_for_close",
                    tier=tier,
                    requiresConfirmation=True,
                )
            requires_confirmation = True

        try:
            if request.action == "open":
                subprocess.Popen(
                    ["cmd", "/c", "start", "", app_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                reason = "opened"
            elif request.action == "close":
                subprocess.run(
                    ["taskkill", "/IM", app_id, "/T"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                reason = "close_requested"
            else:
                # Windows focus control is layered for now; this is a readiness hook.
                reason = "focus_requested"
        except Exception as exc:
            return AppControlResponse(
                accepted=False,
                reason=f"app_control_failed:{exc.__class__.__name__}",
                tier=tier,
                requiresConfirmation=requires_confirmation,
            )

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"app_control:{request.action}:{app_id}",
                tier=tier,
                result="allowed",
                reason=reason,
                createdAt=now_iso(),
            ),
        )

        return AppControlResponse(
            accepted=True,
            reason=reason,
            tier=tier,
            requiresConfirmation=requires_confirmation,
        )

    def add_memory_note(self, request: CreateMemoryNoteRequest) -> MemoryNote:
        note = self.memory_db.add_note(request)
        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"memory_note:create:{note.title}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="stored_locally",
                createdAt=now_iso(),
            ),
        )
        return note

    def list_memory_notes(self, limit: int = 50) -> list[MemoryNote]:
        return self.memory_db.list_notes(limit=limit)

    def search_memory(self, query: str, limit: int = 50) -> MemorySearchResponse:
        return MemorySearchResponse(query=query, items=self.memory_db.search_notes(query, limit=limit))

    def list_perception_snapshots(self, limit: int = 20) -> list[PerceptionSnapshot]:
        return self.memory_db.list_perception_snapshots(limit=limit)

    def search_perception_snapshots(self, query: str, limit: int = 20) -> PerceptionSnapshotSearchResponse:
        return PerceptionSnapshotSearchResponse(
            query=query,
            items=self.memory_db.search_perception_snapshots(query=query, limit=limit),
        )

    def import_document(self, request: DocumentImportRequest) -> DocumentImportResponse:
        source = Path(request.path).resolve()
        if not source.exists() or not source.is_file():
            return DocumentImportResponse(accepted=False, reason="document_not_found")
        if not self._is_path_allowed(source):
            return DocumentImportResponse(accepted=False, reason="folder_not_allowed")

        try:
            document = self.memory_db.import_document(source)
        except ValueError as exc:
            return DocumentImportResponse(accepted=False, reason=str(exc))

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"document_import:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="document_indexed",
                createdAt=now_iso(),
            ),
        )
        return DocumentImportResponse(accepted=True, reason="indexed", document=document)

    def search_documents(self, query: str, limit: int = 20) -> DocumentSearchResponse:
        items = self.memory_db.search_documents(query=query, limit=limit)
        return DocumentSearchResponse(query=query, items=items)

    def import_ocr_document(self, request: OcrImportRequest) -> OcrImportResponse:
        source = Path(request.path).resolve()
        if not source.exists() or not source.is_file():
            return OcrImportResponse(accepted=False, reason="document_not_found")
        if not self._is_path_allowed(source):
            return OcrImportResponse(accepted=False, reason="folder_not_allowed")

        try:
            extracted_text, extraction_mode = extract_text_for_ocr(source)
            document = self.memory_db.import_extracted_document(
                source_path=source,
                text=extracted_text,
                title=source.name,
            )
        except ValueError as exc:
            return OcrImportResponse(accepted=False, reason=str(exc))

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"ocr_import:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=extraction_mode,
                createdAt=now_iso(),
            ),
        )
        return OcrImportResponse(accepted=True, reason=extraction_mode, document=document)

    @staticmethod
    def _box_intersection_area(
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> int:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1 = max(ax1, bx1)
        iy1 = max(ay1, by1)
        ix2 = min(ax2, bx2)
        iy2 = min(ay2, by2)
        iw = max(0, ix2 - ix1 + 1)
        ih = max(0, iy2 - iy1 + 1)
        return iw * ih

    @staticmethod
    def _merge_overlapping_boxes(
        boxes: list[tuple[int, int, int, int, float]],
    ) -> list[tuple[int, int, int, int, float]]:
        if not boxes:
            return []
        merged = sorted(boxes, key=lambda item: (item[1], item[0]))
        changed = True
        while changed:
            changed = False
            next_boxes: list[tuple[int, int, int, int, float]] = []
            while merged:
                current = merged.pop(0)
                cx1, cy1, cx2, cy2, cscore = current
                keep = True
                for index, other in enumerate(merged):
                    ox1, oy1, ox2, oy2, oscore = other
                    intersection = RuntimeStore._box_intersection_area(
                        (cx1, cy1, cx2, cy2),
                        (ox1, oy1, ox2, oy2),
                    )
                    if intersection <= 0:
                        continue
                    c_area = (cx2 - cx1 + 1) * (cy2 - cy1 + 1)
                    o_area = (ox2 - ox1 + 1) * (oy2 - oy1 + 1)
                    overlap_ratio = intersection / max(1, min(c_area, o_area))
                    if overlap_ratio < 0.35:
                        continue
                    nx1 = min(cx1, ox1)
                    ny1 = min(cy1, oy1)
                    nx2 = max(cx2, ox2)
                    ny2 = max(cy2, oy2)
                    nscore = max(cscore, oscore)
                    merged.pop(index)
                    merged.insert(0, (nx1, ny1, nx2, ny2, nscore))
                    keep = False
                    changed = True
                    break
                if keep:
                    next_boxes.append(current)
            merged = next_boxes
        return merged

    @staticmethod
    def _find_runs(active: list[bool], min_size: int) -> list[tuple[int, int]]:
        runs: list[tuple[int, int]] = []
        start: int | None = None
        for index, value in enumerate(active):
            if value and start is None:
                start = index
            elif not value and start is not None:
                if index - start >= min_size:
                    runs.append((start, index - 1))
                start = None
        if start is not None and len(active) - start >= min_size:
            runs.append((start, len(active) - 1))
        return runs

    def _extract_ui_blocks_from_image(
        self,
        source: Path,
        max_blocks: int,
    ) -> tuple[int, int, list[PerceptionUiBlock]]:
        with Image.open(source) as image:
            grayscale = image.convert("L")
            width, height = grayscale.size
            scale = max(1.0, max(width, height) / 480.0)
            sample_width = max(1, int(width / scale))
            sample_height = max(1, int(height / scale))
            sampled = grayscale.resize((sample_width, sample_height))

            pixels = sampled.load()
            row_active: list[bool] = []
            for y in range(sample_height):
                active_count = 0
                for x in range(sample_width):
                    if pixels[x, y] < 232:
                        active_count += 1
                row_active.append(active_count >= max(2, int(sample_width * 0.03)))

            row_runs = self._find_runs(row_active, min_size=max(2, int(sample_height * 0.01)))
            boxes: list[tuple[int, int, int, int, float]] = []
            for y0, y1 in row_runs:
                column_active: list[bool] = []
                run_height = y1 - y0 + 1
                for x in range(sample_width):
                    active_count = 0
                    for y in range(y0, y1 + 1):
                        if pixels[x, y] < 232:
                            active_count += 1
                    column_active.append(active_count >= max(1, int(run_height * 0.08)))

                col_runs = self._find_runs(column_active, min_size=max(3, int(sample_width * 0.02)))
                for x0, x1 in col_runs:
                    sx1 = int(x0 * scale)
                    sy1 = int(y0 * scale)
                    sx2 = min(width - 1, int((x1 + 1) * scale) - 1)
                    sy2 = min(height - 1, int((y1 + 1) * scale) - 1)
                    area = (sx2 - sx1 + 1) * (sy2 - sy1 + 1)
                    if area < max(200, int(width * height * 0.0003)):
                        continue
                    density = min(
                        1.0,
                        ((x1 - x0 + 1) * (y1 - y0 + 1))
                        / max(1.0, float(sample_width * sample_height)),
                    )
                    boxes.append((sx1, sy1, sx2, sy2, max(0.05, density * 30)))

            merged = self._merge_overlapping_boxes(boxes)
            merged = sorted(
                merged,
                key=lambda item: ((item[2] - item[0] + 1) * (item[3] - item[1] + 1)),
                reverse=True,
            )[:max_blocks]
            ui_blocks = [
                PerceptionUiBlock(
                    x=x1,
                    y=y1,
                    width=max(1, x2 - x1 + 1),
                    height=max(1, y2 - y1 + 1),
                    kind="text_region",
                    confidence=round(min(0.99, score), 3),
                    textSnippet=None,
                )
                for x1, y1, x2, y2, score in merged
            ]
        return width, height, ui_blocks

    def analyze_screen(self, request: PerceptionAnalyzeRequest) -> PerceptionAnalyzeResponse:
        if not self._is_action_allowed(PERCEPTION_SCREEN_SUBJECT):
            decision = self._resolve_action_permission_decision(PERCEPTION_SCREEN_SUBJECT)
            reason = "screen_permission_denied" if decision == "deny" else "screen_permission_required"
            self.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent="perception_screen_analyze",
                    tier=ActionTier.risky,
                    result="blocked",
                    reason=reason,
                    createdAt=now_iso(),
                ),
            )
            return PerceptionAnalyzeResponse(
                accepted=False,
                reason=reason,
            )

        source: Path | None = None
        remove_source_after = False

        image_data_url = (request.imageDataUrl or "").strip()
        path_value = (request.path or "").strip()
        if image_data_url:
            if not image_data_url.startswith("data:image/") or ";base64," not in image_data_url:
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="invalid_image_data_url",
                )
            header, encoded = image_data_url.split(",", 1)
            mime_part = header[5:].split(";", 1)[0].lower()
            suffix = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
                "image/bmp": ".bmp",
                "image/tiff": ".tiff",
            }.get(mime_part)
            if suffix is None:
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="unsupported_file_type",
                )
            try:
                image_bytes = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error):
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="invalid_image_data_url",
                )
            if not image_bytes:
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="invalid_image_data_url",
                )
            captures_dir = Path("data/runtime/perception").resolve()
            captures_dir.mkdir(parents=True, exist_ok=True)
            source = captures_dir / f"capture-{uuid4()}{suffix}"
            source.write_bytes(image_bytes)
            remove_source_after = True
        elif path_value:
            source = Path(path_value).resolve()
            if not source.exists() or not source.is_file():
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="image_not_found",
                )
            if source.suffix.lower() not in OCR_IMAGE_SUFFIXES:
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="unsupported_file_type",
                )
            if not self._is_path_allowed(source):
                return PerceptionAnalyzeResponse(
                    accepted=False,
                    reason="folder_not_allowed",
                )
        else:
            return PerceptionAnalyzeResponse(
                accepted=False,
                reason="path_or_image_required",
            )

        try:
            width, height, blocks = self._extract_ui_blocks_from_image(
                source=source,
                max_blocks=request.maxBlocks,
            )
        except Exception:
            if remove_source_after:
                try:
                    source.unlink(missing_ok=True)
                except Exception:
                    pass
            return PerceptionAnalyzeResponse(
                accepted=False,
                reason="image_parse_failed",
            )

        text: str | None = None
        ocr_mode: str | None = None
        ocr_error: str | None = None
        if request.includeOcr:
            try:
                text, ocr_mode = extract_text_for_ocr(source)
            except ValueError as exc:
                ocr_error = str(exc)

        reason = "ok"
        if request.includeOcr and ocr_error is not None:
            reason = "ocr_unavailable_blocks_extracted"

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"perception_screen_analyze:{source.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"blocks:{len(blocks)}",
                createdAt=now_iso(),
            ),
        )

        snapshot = self.memory_db.add_perception_snapshot(
            source_path=str(source),
            reason=reason,
            ocr_mode=ocr_mode,
            text=text,
            block_count=len(blocks),
            image_width=width,
            image_height=height,
        )

        response = PerceptionAnalyzeResponse(
            accepted=True,
            reason=reason,
            snapshotId=snapshot.id,
            path=str(source),
            imageWidth=width,
            imageHeight=height,
            ocrMode=ocr_mode,
            ocrError=ocr_error,
            text=text,
            textLength=len(text or ""),
            blocks=blocks,
        )
        if remove_source_after:
            try:
                source.unlink(missing_ok=True)
            except Exception:
                pass
        return response

    def _watched_paths(self) -> list[Path]:
        defaults = [Path("data/inbox"), Path("data/notes"), Path("data/screenshots")]
        folder_grants = [
            Path(grant.subject)
            for grant in self.permission_grants
            if grant.scope == "folder" and grant.decision == "allow"
        ]
        seen: set[str] = set()
        resolved_dirs: list[Path] = []
        for candidate in defaults + folder_grants:
            path = candidate.resolve()
            if not path.exists() or not path.is_dir():
                continue
            key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            resolved_dirs.append(path)
        return resolved_dirs

    def auto_index_status(self) -> AutoIndexStatus:
        paths = [str(path) for path in self._watched_paths()]
        return AutoIndexStatus(
            running=self.auto_index_thread is not None and self.auto_index_thread.is_alive(),
            watchedPaths=paths,
            lastScanAt=self.auto_index_last_scan,
            indexedTotal=self.auto_index_indexed_total,
            indexedLastRun=self.auto_index_indexed_last_run,
            lastError=self.auto_index_last_error,
        )

    def start_auto_indexer(self) -> None:
        if self.auto_index_thread is not None and self.auto_index_thread.is_alive():
            return
        self.auto_index_stop.clear()
        self.auto_index_thread = Thread(target=self._auto_index_loop, daemon=True)
        self.auto_index_thread.start()

    def _auto_index_loop(self) -> None:
        while not self.auto_index_stop.is_set():
            self.auto_index_scan_once()
            self.auto_index_stop.wait(30)

    def auto_index_scan_once(self) -> AutoIndexStatus:
        indexed_now = 0
        self.auto_index_last_error = None
        supported_suffixes = ALLOWED_DOCUMENT_SUFFIXES | OCR_IMAGE_SUFFIXES | {".pdf"}

        for directory in self._watched_paths():
            for file_path in directory.rglob("*"):
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in supported_suffixes:
                    continue
                try:
                    mtime_ns = file_path.stat().st_mtime_ns
                except OSError:
                    continue
                file_key = str(file_path.resolve())
                if self.auto_index_seen_mtime.get(file_key) == mtime_ns:
                    continue

                try:
                    if file_path.suffix.lower() in ALLOWED_DOCUMENT_SUFFIXES:
                        self.memory_db.import_document(file_path)
                    else:
                        extracted_text, _ = extract_text_for_ocr(file_path)
                        self.memory_db.import_extracted_document(
                            source_path=file_path,
                            text=extracted_text,
                            title=file_path.name,
                        )
                    self.auto_index_seen_mtime[file_key] = mtime_ns
                    indexed_now += 1
                except ValueError as exc:
                    self.auto_index_seen_mtime[file_key] = mtime_ns
                    self.auto_index_last_error = str(exc)

        self.auto_index_last_scan = now_iso()
        self.auto_index_indexed_last_run = indexed_now
        self.auto_index_indexed_total += indexed_now
        return self.auto_index_status()

    def scheduler_status(self) -> SchedulerStatus:
        return SchedulerStatus(
            running=self.scheduler_thread is not None and self.scheduler_thread.is_alive(),
            lastScanAt=self.scheduler_last_scan,
            alertsTotal=self.scheduler_alerts_total,
            alertsLastRun=self.scheduler_alerts_last_run,
            trackedTasks=len(self.tasks),
            lastError=self.scheduler_last_error,
        )

    def start_scheduler(self) -> None:
        if self.scheduler_thread is not None and self.scheduler_thread.is_alive():
            return
        self.scheduler_stop.clear()
        self.scheduler_thread = Thread(target=self._scheduler_loop, daemon=True)
        self.scheduler_thread.start()

    def _scheduler_loop(self) -> None:
        while not self.scheduler_stop.is_set():
            self.scheduler_scan_once()
            self.scheduler_stop.wait(20)

    @staticmethod
    def _parse_due_at(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _parse_time_component(raw: str | None) -> tuple[int, int]:
        if not raw:
            return (9, 0)
        text = raw.strip().lower()
        match_ampm = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", text)
        if match_ampm:
            hour = int(match_ampm.group(1))
            minute = int(match_ampm.group(2) or "0")
            meridiem = match_ampm.group(3)
            hour = hour % 12
            if meridiem == "pm":
                hour += 12
            return (hour, minute)

        match_24 = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?", text)
        if match_24:
            hour = int(match_24.group(1))
            minute = int(match_24.group(2) or "0")
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return (hour, minute)
        return (9, 0)

    @staticmethod
    def _resolve_timezone(name: str | None) -> tuple[timezone | ZoneInfo, bool]:
        if not name:
            return timezone.utc, False
        tz_name = name.strip()
        if not tz_name:
            return timezone.utc, False
        try:
            return ZoneInfo(tz_name), False
        except Exception:
            pass

        normalized = tz_name.upper()
        fallback_minutes = {
            "UTC": 0,
            "ETC/UTC": 0,
            "GMT": 0,
            "ASIA/MANILA": 8 * 60,
            "ASIA/SINGAPORE": 8 * 60,
            "ASIA/HONG_KONG": 8 * 60,
            "ASIA/TOKYO": 9 * 60,
            "ASIA/SEOUL": 9 * 60,
            "AMERICA/NEW_YORK": -5 * 60,
            "AMERICA/CHICAGO": -6 * 60,
            "AMERICA/DENVER": -7 * 60,
            "AMERICA/LOS_ANGELES": -8 * 60,
            "EUROPE/LONDON": 0,
            "EUROPE/PARIS": 60,
        }.get(normalized)
        if fallback_minutes is not None:
            return timezone(timedelta(minutes=fallback_minutes)), True

        offset_match = re.fullmatch(r"(?:UTC|GMT)\s*([+-])\s*(\d{1,2})(?::?(\d{2}))?", normalized)
        if offset_match:
            sign = 1 if offset_match.group(1) == "+" else -1
            hours = int(offset_match.group(2))
            minutes = int(offset_match.group(3) or "0")
            total_minutes = sign * (hours * 60 + minutes)
            return timezone(timedelta(minutes=total_minutes)), True
        return timezone.utc, True

    @staticmethod
    def _format_utc(value: datetime) -> str:
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _compute_next_run(self, due: datetime, recurrence: str, now_utc: datetime) -> datetime:
        interval = timedelta(days=1) if recurrence == "daily" else timedelta(days=7)
        next_due = due
        while next_due <= now_utc:
            next_due = next_due + interval
        return next_due

    def task_next_run(self, request: TaskNextRunRequest) -> TaskNextRunResponse:
        due = self._parse_due_at(request.dueAt)
        if due is None:
            return TaskNextRunResponse(accepted=False, reason="invalid_dueAt")
        now_utc = datetime.now(timezone.utc)
        next_due = self._compute_next_run(due=due, recurrence=request.recurrence, now_utc=now_utc)
        return TaskNextRunResponse(
            accepted=True,
            reason="ok",
            nextRunAt=self._format_utc(next_due),
        )

    def parse_task_time(self, request: TaskTimeParseRequest) -> TaskTimeParseResponse:
        text = (request.text or "").strip()
        if not text:
            return TaskTimeParseResponse(accepted=False, reason="empty_text")

        tz_name = request.timezone
        tz, timezone_fallback = self._resolve_timezone(tz_name or "UTC")

        now_local = datetime.now(tz)
        lowered = text.lower()

        # Direct ISO path first.
        direct = self._parse_due_at(text)
        if direct is not None:
            reason = "iso_with_timezone_fallback" if timezone_fallback else "iso"
            return TaskTimeParseResponse(accepted=True, reason=reason, dueAt=self._format_utc(direct))

        # in N minutes/hours/days
        in_match = re.fullmatch(r"in\s+(\d+)\s*(minute|minutes|hour|hours|day|days)", lowered)
        if in_match:
            amount = int(in_match.group(1))
            unit = in_match.group(2)
            delta = timedelta(minutes=amount)
            if "hour" in unit:
                delta = timedelta(hours=amount)
            elif "day" in unit:
                delta = timedelta(days=amount)
            due = now_local + delta
            return TaskTimeParseResponse(
                accepted=True,
                reason="relative_with_timezone_fallback" if timezone_fallback else "relative",
                dueAt=self._format_utc(due.astimezone(timezone.utc)),
            )

        # today/tomorrow [time]
        tt_match = re.fullmatch(r"(today|tomorrow)(?:\s+(.+))?", lowered)
        if tt_match:
            base = now_local.date()
            if tt_match.group(1) == "tomorrow":
                base = base + timedelta(days=1)
            hour, minute = self._parse_time_component(tt_match.group(2))
            due_local = datetime(
                base.year,
                base.month,
                base.day,
                hour,
                minute,
                tzinfo=tz,
            )
            return TaskTimeParseResponse(
                accepted=True,
                reason="day_phrase_with_timezone_fallback" if timezone_fallback else "day_phrase",
                dueAt=self._format_utc(due_local.astimezone(timezone.utc)),
            )

        # next weekday [time]
        nw_match = re.fullmatch(
            r"next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+(.+))?",
            lowered,
        )
        if nw_match:
            weekdays = {
                "monday": 0,
                "tuesday": 1,
                "wednesday": 2,
                "thursday": 3,
                "friday": 4,
                "saturday": 5,
                "sunday": 6,
            }
            target = weekdays[nw_match.group(1)]
            current = now_local.weekday()
            days_ahead = (target - current + 7) % 7
            if days_ahead == 0:
                days_ahead = 7
            base = now_local.date() + timedelta(days=days_ahead)
            hour, minute = self._parse_time_component(nw_match.group(2))
            due_local = datetime(
                base.year,
                base.month,
                base.day,
                hour,
                minute,
                tzinfo=tz,
            )
            return TaskTimeParseResponse(
                accepted=True,
                reason="next_weekday_with_timezone_fallback" if timezone_fallback else "next_weekday",
                dueAt=self._format_utc(due_local.astimezone(timezone.utc)),
            )

        return TaskTimeParseResponse(accepted=False, reason="unsupported_time_phrase")

    @staticmethod
    def _ics_escape(value: str) -> str:
        return (
            value.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace("\n", "\\n")
        )

    @staticmethod
    def _ics_dt(value: datetime) -> str:
        return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def export_calendar(self, request: CalendarExportRequest) -> CalendarExportResponse:
        export_dir = Path("data/runtime/exports").resolve()
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        file_name = (request.fileName or f"mindi-calendar-{timestamp}.ics").strip()
        if not file_name.lower().endswith(".ics"):
            file_name = f"{file_name}.ics"
        safe_name = Path(file_name).name
        target = export_dir / safe_name

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//MINDI//Task Calendar//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
        ]

        event_count = 0
        now_utc = datetime.now(timezone.utc)
        for task in self.tasks:
            if task.status == "done" and not request.includeCompleted:
                continue
            due = self._parse_due_at(task.dueAt)
            if due is None:
                continue

            uid = f"{task.id}@mindi.local"
            summary = self._ics_escape(task.title)
            dtstamp = self._ics_dt(now_utc)
            dtstart = self._ics_dt(due)
            dtend = self._ics_dt(due + timedelta(minutes=30))
            status = "COMPLETED" if task.status == "done" else "CONFIRMED"

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{dtstamp}",
                    f"DTSTART:{dtstart}",
                    f"DTEND:{dtend}",
                    f"SUMMARY:{summary}",
                    f"STATUS:{status}",
                ]
            )
            if task.recurrence == "daily":
                lines.append("RRULE:FREQ=DAILY")
            elif task.recurrence == "weekly":
                lines.append("RRULE:FREQ=WEEKLY")
            if task.reminderMinutesBefore is not None and task.reminderMinutesBefore > 0:
                lines.extend(
                    [
                        "BEGIN:VALARM",
                        f"TRIGGER:-PT{task.reminderMinutesBefore}M",
                        "ACTION:DISPLAY",
                        "DESCRIPTION:Task reminder",
                        "END:VALARM",
                    ]
                )
            lines.append("END:VEVENT")
            event_count += 1

        lines.append("END:VCALENDAR")
        target.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

        self.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent="calendar_export",
                tier=ActionTier.reversible,
                result="allowed",
                reason=f"events:{event_count}",
                createdAt=now_iso(),
            ),
        )

        return CalendarExportResponse(
            accepted=True,
            reason="exported",
            filePath=str(target),
            eventCount=event_count,
        )

    @staticmethod
    def _ics_unescape(value: str) -> str:
        return (
            value.replace("\\n", "\n")
            .replace("\\,", ",")
            .replace("\\;", ";")
            .replace("\\\\", "\\")
        )

    @staticmethod
    def _unfold_ics_lines(raw_text: str) -> list[str]:
        unfolded: list[str] = []
        for line in raw_text.splitlines():
            if (line.startswith(" ") or line.startswith("\t")) and unfolded:
                unfolded[-1] = unfolded[-1] + line[1:]
                continue
            unfolded.append(line)
        return unfolded

    @staticmethod
    def _parse_ics_property(line: str) -> tuple[str, dict[str, str], str] | None:
        if ":" not in line:
            return None
        head, value = line.split(":", 1)
        parts = head.split(";")
        key = parts[0].upper().strip()
        params: dict[str, str] = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            name, raw_value = part.split("=", 1)
            params[name.upper().strip()] = raw_value.strip()
        return key, params, value.strip()

    def _parse_ics_datetime(self, raw: str, tzid: str | None = None) -> datetime | None:
        value = raw.strip()
        if not value:
            return None
        tz, _ = self._resolve_timezone(tzid or "UTC")
        try:
            if value.endswith("Z"):
                dt = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            if "T" in value:
                dt_local = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz)
                return dt_local.astimezone(timezone.utc)
            dt_local = datetime.strptime(value, "%Y%m%d").replace(tzinfo=tz)
            return dt_local.astimezone(timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def _parse_ics_trigger_minutes(raw: str) -> int | None:
        text = raw.strip().upper()
        if not text.startswith("-P"):
            return None
        match = re.fullmatch(
            r"-P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?",
            text,
        )
        if not match:
            return None
        days = int(match.group(1) or "0")
        hours = int(match.group(2) or "0")
        minutes = int(match.group(3) or "0")
        seconds = int(match.group(4) or "0")
        total_minutes = days * 24 * 60 + hours * 60 + minutes + (1 if seconds > 0 else 0)
        if total_minutes <= 0:
            return None
        return total_minutes

    def _find_task_conflict(self, title: str, due_at: str, external_id: str | None) -> TaskItem | None:
        if external_id:
            for task in self.tasks:
                if (task.externalId or "").strip() == external_id:
                    return task
        normalized_title = " ".join(title.split()).lower()
        for task in self.tasks:
            if (task.dueAt or "") != due_at:
                continue
            if " ".join(task.title.split()).lower() == normalized_title:
                return task
        return None

    def import_calendar(self, request: CalendarImportRequest) -> CalendarImportResponse:
        source = Path(request.filePath).resolve()
        if not source.exists() or not source.is_file():
            return CalendarImportResponse(
                accepted=False,
                reason="file_not_found",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )
        if source.suffix.lower() != ".ics":
            return CalendarImportResponse(
                accepted=False,
                reason="unsupported_file_type",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )
        if not self._is_path_allowed(source):
            return CalendarImportResponse(
                accepted=False,
                reason="folder_not_allowed",
                importedCount=0,
                createdCount=0,
                updatedCount=0,
                skippedCount=0,
            )

        raw_text = source.read_text(encoding="utf-8", errors="ignore")
        lines = self._unfold_ics_lines(raw_text)
        created_count = 0
        updated_count = 0
        skipped_count = 0
        current: dict[str, str] = {}
        current_dtstart_tzid: str | None = None
        current_exdates: list[tuple[str, str | None]] = []
        current_reminder_minutes: int | None = None
        in_event = False
        in_alarm = False

        def flush_event() -> None:
            nonlocal created_count, updated_count, skipped_count
            nonlocal current, current_dtstart_tzid, current_exdates, current_reminder_minutes
            title_raw = current.get("SUMMARY", "").strip()
            uid_raw = current.get("UID", "").strip()
            dtstart_raw = current.get("DTSTART", "").strip()
            if not title_raw or not dtstart_raw:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return
            due = self._parse_ics_datetime(dtstart_raw, tzid=current_dtstart_tzid)
            if due is None:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return
            recurrence: str | None = None
            rrule = current.get("RRULE", "").upper()
            if "FREQ=DAILY" in rrule:
                recurrence = "daily"
            elif "FREQ=WEEKLY" in rrule:
                recurrence = "weekly"

            excluded = False
            for exdate_value, exdate_tzid in current_exdates:
                for token in [part.strip() for part in exdate_value.split(",") if part.strip()]:
                    exdate = self._parse_ics_datetime(token, tzid=exdate_tzid)
                    if exdate is not None and exdate == due:
                        excluded = True
                        break
                if excluded:
                    break
            if excluded:
                skipped_count += 1
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                return

            title = self._ics_unescape(title_raw)
            external_id = self._ics_unescape(uid_raw) if uid_raw else None
            due_at = self._format_utc(due)
            conflict = self._find_task_conflict(
                title=title,
                due_at=due_at,
                external_id=external_id,
            )
            if conflict is not None:
                conflict.externalId = external_id or conflict.externalId
                conflict.title = title
                conflict.dueAt = due_at
                conflict.nextRunAt = due_at
                conflict.recurrence = recurrence
                conflict.reminderMinutesBefore = current_reminder_minutes
                conflict.source = "assistant"
                updated_count += 1
            else:
                task = TaskItem(
                    id=str(uuid4()),
                    externalId=external_id,
                    title=title,
                    dueAt=due_at,
                    recurrence=recurrence,
                    reminderMinutesBefore=current_reminder_minutes,
                    nextRunAt=due_at,
                    status="todo",
                    source="assistant",
                )
                self.tasks.insert(0, task)
                created_count += 1
            current = {}
            current_dtstart_tzid = None
            current_exdates = []
            current_reminder_minutes = None

        for raw_line in lines:
            line = raw_line.strip()
            if line == "BEGIN:VEVENT":
                in_event = True
                in_alarm = False
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                continue
            if line == "END:VEVENT":
                if in_event:
                    flush_event()
                in_event = False
                in_alarm = False
                current = {}
                current_dtstart_tzid = None
                current_exdates = []
                current_reminder_minutes = None
                continue
            if line == "BEGIN:VALARM":
                in_alarm = True
                continue
            if line == "END:VALARM":
                in_alarm = False
                continue
            if not in_event:
                continue

            parsed = self._parse_ics_property(line)
            if parsed is None:
                continue
            key, params, value = parsed

            if in_alarm:
                if key == "TRIGGER":
                    minutes_before = self._parse_ics_trigger_minutes(value)
                    if minutes_before is not None:
                        current_reminder_minutes = minutes_before
                continue

            current[key] = value
            if key == "DTSTART":
                current_dtstart_tzid = params.get("TZID")
            elif key == "EXDATE":
                current_exdates.append((value, params.get("TZID")))

        imported_count = created_count + updated_count
        if imported_count > 0:
            self.logs.insert(
                0,
                ActionLogItem(
                    id=str(uuid4()),
                    intent="calendar_import",
                    tier=ActionTier.reversible,
                    result="allowed",
                    reason=f"created:{created_count},updated:{updated_count},skipped:{skipped_count}",
                    createdAt=now_iso(),
                ),
            )

        return CalendarImportResponse(
            accepted=True,
            reason="imported",
            importedCount=imported_count,
            createdCount=created_count,
            updatedCount=updated_count,
            skippedCount=skipped_count,
        )

    def scheduler_scan_once(self) -> SchedulerStatus:
        now_utc = datetime.now(timezone.utc)
        created_alerts = 0
        self.scheduler_last_error = None

        for task in self.tasks:
            if task.status == "done":
                continue
            due = self._parse_due_at(task.dueAt)
            if due is None:
                continue

            marker = f"{task.id}:{task.dueAt}"
            if due <= now_utc and self.scheduler_alerted_due.get(task.id) != marker:
                overdue_seconds = (now_utc - due).total_seconds()
                severity = "critical" if overdue_seconds >= 3600 else "warning"
                detail = (
                    f"Task '{task.title}' reached due time ({task.dueAt})."
                    if overdue_seconds < 60
                    else f"Task '{task.title}' is overdue ({task.dueAt})."
                )
                self.alerts.insert(
                    0,
                    AlertItem(
                        id=str(uuid4()),
                        severity=severity,
                        title=f"Task Due: {task.title}",
                        detail=detail,
                        createdAt=now_iso(),
                    ),
                )
                self.scheduler_alerted_due[task.id] = marker
                if task.recurrence in {"daily", "weekly"}:
                    next_due = self._compute_next_run(
                        due=due,
                        recurrence=task.recurrence,
                        now_utc=now_utc,
                    )
                    task.nextRunAt = self._format_utc(next_due)
                    task.dueAt = task.nextRunAt
                created_alerts += 1

        self.alerts = self.alerts[:100]
        self.scheduler_last_scan = now_iso()
        self.scheduler_alerts_last_run = created_alerts
        self.scheduler_alerts_total += created_alerts
        return self.scheduler_status()
