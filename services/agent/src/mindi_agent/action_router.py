"""Map natural-language intents to local control actions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionTier,
    AppControlRequest,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    ExecutedAction,
    LauncherRequest,
    WebScrapeRequest,
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(
    r"(?:^|\s)((?:www\.)?[a-z0-9][-a-z0-9.]*\.[a-z]{2,}(?:/[^\s]*)?)",
    re.IGNORECASE,
)
_WIN_PATH_RE = re.compile(r"([A-Za-z]:\\(?:[^\\/\"']+\\)*[^\\/\"'\s]+)")
_UNIX_PATH_RE = re.compile(r"(/(?:[^\\s\"']+/)+[^\\s\"']+)")

_APP_ALIASES: dict[str, str] = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "spotify": "spotify.exe",
    "vscode": "Code.exe",
    "code": "Code.exe",
    "explorer": "explorer.exe",
    "files": "explorer.exe",
    "word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
}

_DESTRUCTIVE_TERMS = frozenset(
    {"delete", "remove", "uninstall", "wipe", "format", "erase", "destroy"}
)


@dataclass
class ActionPlan:
    tool: str
    args: dict[str, str]
    tier: ActionTier = ActionTier.reversible
    confidence: float = 1.0


@dataclass
class ActionRouteResult:
    handled: bool = False
    immediate: bool = False
    reply: str = ""
    executed_actions: list[ExecutedAction] = field(default_factory=list)
    llm_prompt: str | None = None
    citations: list[dict] = field(default_factory=list)


def _extract_url(text: str) -> str | None:
    match = _URL_RE.search(text)
    if match:
        return match.group(0).rstrip(".,)")
    for candidate in _BARE_DOMAIN_RE.findall(text):
        cleaned = candidate.strip().rstrip(".,)")
        if "." in cleaned and " " not in cleaned:
            return cleaned
    return None


def _extract_file_path(text: str) -> str | None:
    win = _WIN_PATH_RE.search(text)
    if win:
        return win.group(1)
    unix = _UNIX_PATH_RE.search(text)
    if unix:
        return unix.group(1)
    return None


def _normalize_app_id(raw: str) -> str:
    key = raw.strip().lower()
    if key in _APP_ALIASES:
        return _APP_ALIASES[key]
    if key.endswith(".exe"):
        return key
    return f"{key}.exe"


def classify_action(text: str) -> ActionPlan | None:
    trimmed = (text or "").strip()
    if not trimmed:
        return None
    lowered = trimmed.lower()

    if any(term in lowered for term in _DESTRUCTIVE_TERMS):
        return None

    if re.search(r"\b(scan|index)\b", lowered) and re.search(
        r"\b(files?|documents?|folders?|downloads?|desktop)\b", lowered
    ):
        return ActionPlan(tool="scan_files", args={}, tier=ActionTier.reversible, confidence=0.95)

    if "scan my files" in lowered or "index my files" in lowered:
        return ActionPlan(tool="scan_files", args={}, tier=ActionTier.reversible, confidence=0.98)

    url = _extract_url(trimmed)
    if url and re.search(r"\b(open|go to|visit|browse|launch)\b", lowered):
        return ActionPlan(tool="open_url", args={"url": url}, tier=ActionTier.reversible, confidence=0.9)

    file_path = _extract_file_path(trimmed)
    if file_path and re.search(r"\b(open|show|view|launch)\b", lowered):
        if re.search(r"\b(file|document|pdf|folder|path)\b", lowered) or file_path:
            return ActionPlan(
                tool="open_file",
                args={"path": file_path},
                tier=ActionTier.reversible,
                confidence=0.88,
            )

    app_match = re.search(
        r"\b(?:open|launch|start|run)\s+(?:the\s+)?([a-z][a-z0-9._-]{1,24})\b",
        lowered,
    )
    if app_match:
        app_name = app_match.group(1)
        if app_name not in {"a", "an", "the", "my", "this", "that", "url", "file", "app"}:
            return ActionPlan(
                tool="open_app",
                args={"appId": _normalize_app_id(app_name)},
                tier=ActionTier.reversible,
                confidence=0.85,
            )

    if re.search(r"\b(research|look up|investigate|find out about)\b", lowered):
        return ActionPlan(
            tool="web_research",
            args={"query": trimmed, "url": url or ""},
            tier=ActionTier.read_only,
            confidence=0.8,
        )

    if re.search(
        r"\b(capture|scan|look at|analyze|help with|what(?:'s| is) on)\b.*\b(screen|display)\b",
        lowered,
    ) or re.search(r"\bscreen help\b", lowered):
        return ActionPlan(
            tool="screen_help",
            args={},
            tier=ActionTier.read_only,
            confidence=0.88,
        )

    if url and re.search(r"\b(summarize|summary|scrape|read)\b", lowered):
        return ActionPlan(
            tool="web_research",
            args={"query": trimmed, "url": url},
            tier=ActionTier.read_only,
            confidence=0.82,
        )

    task_match = re.search(
        r"\b(?:create|add|make|remind(?: me)?(?: to)?)\s+(?:a\s+)?task(?:\s+(?:to|called|named))?\s+(.+)",
        trimmed,
        flags=re.IGNORECASE,
    )
    if task_match:
        title = task_match.group(1).strip().rstrip(".")
        if title:
            return ActionPlan(
                tool="create_task",
                args={"title": title[:200]},
                tier=ActionTier.reversible,
                confidence=0.86,
            )

    note_match = re.search(
        r"\b(?:remember|note|save)\s+(?:that\s+)?(.+)",
        trimmed,
        flags=re.IGNORECASE,
    )
    if note_match:
        content = note_match.group(1).strip().rstrip(".")
        if len(content) >= 3:
            return ActionPlan(
                tool="create_note",
                args={"title": content[:80], "content": content},
                tier=ActionTier.reversible,
                confidence=0.84,
            )

    return None


class ActionRouter:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def classify(self, text: str) -> ActionPlan | None:
        return classify_action(text)

    def execute(self, plan: ActionPlan, *, original_text: str) -> ActionRouteResult:
        if plan.tool == "open_app":
            return self._open_app(plan)
        if plan.tool == "open_url":
            return self._open_url(plan)
        if plan.tool == "open_file":
            return self._open_file(plan)
        if plan.tool == "scan_files":
            return self._scan_files()
        if plan.tool == "web_research":
            return self._store._research_svc.run_research(
                query=plan.args.get("query") or original_text,
                url=(plan.args.get("url") or "").strip() or None,
            )
        if plan.tool == "create_task":
            return self._create_task(plan)
        if plan.tool == "create_note":
            return self._create_note(plan)
        if plan.tool == "screen_help":
            return self._screen_help()
        return ActionRouteResult(handled=False)

    def _screen_help(self) -> ActionRouteResult:
        action = ExecutedAction(
            tool="screen_help",
            accepted=True,
            reason="hotkey_required",
            detail="Ctrl+Shift+S",
            tier=ActionTier.read_only.value,
        )
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply="Press Ctrl+Shift+S to capture your screen. I will read it and suggest what to focus on.",
            executed_actions=[action],
        )

    def _open_app(self, plan: ActionPlan) -> ActionRouteResult:
        app_id = plan.args.get("appId", "")
        result = self._store.control_app(AppControlRequest(action="open", appId=app_id))
        action = ExecutedAction(
            tool="open_app",
            accepted=result.accepted,
            reason=result.reason,
            detail=app_id,
            tier=result.tier.value,
        )
        if result.accepted:
            reply = f"Opened {app_id}."
        elif result.reason == "app_not_allowlisted":
            reply = f"I cannot open {app_id} yet. Add it to the app allowlist in Control."
        else:
            reply = f"Could not open {app_id}: {result.reason}."
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=reply,
            executed_actions=[action],
        )

    def _open_url(self, plan: ActionPlan) -> ActionRouteResult:
        url = plan.args.get("url", "")
        result = self._store.open_launcher(LauncherRequest(kind="url", target=url))
        action = ExecutedAction(
            tool="open_url",
            accepted=result.accepted,
            reason=result.reason,
            detail=result.target or url,
            tier=ActionTier.reversible.value,
        )
        if result.accepted:
            reply = f"Opened {result.target or url} in your browser."
        elif result.reason == "domain_not_allowed":
            reply = "That domain is not on the allowlist. Add it under Control permissions."
        else:
            reply = f"Could not open the URL: {result.reason}."
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=reply,
            executed_actions=[action],
        )

    def _open_file(self, plan: ActionPlan) -> ActionRouteResult:
        path = plan.args.get("path", "")
        result = self._store.open_launcher(LauncherRequest(kind="file", target=path))
        action = ExecutedAction(
            tool="open_file",
            accepted=result.accepted,
            reason=result.reason,
            detail=result.target or path,
            tier=ActionTier.reversible.value,
        )
        if result.accepted:
            reply = f"Opened {result.target or path}."
        elif result.reason == "folder_not_allowed":
            reply = "That file path is outside allowed folders. Grant folder access in Control."
        else:
            reply = f"Could not open the file: {result.reason}."
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=reply,
            executed_actions=[action],
        )

    def _scan_files(self) -> ActionRouteResult:
        status = self._store.auto_index_scan_once(include_user_folders=True)
        indexed = status.indexedLastRun
        path_names = [Path(p).name for p in (status.onDemandPaths or [])[:4]]
        paths = ", ".join(path_names) or "your folders"
        action = ExecutedAction(
            tool="scan_files",
            accepted=True,
            reason="ok",
            detail=f"indexed={indexed}",
            tier=ActionTier.reversible.value,
        )
        reply = (
            f"Scanned {paths}. Indexed {indexed} new or changed files "
            f"({status.indexedTotal} total indexed)."
        )
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=reply,
            executed_actions=[action],
        )

    def _create_task(self, plan: ActionPlan) -> ActionRouteResult:
        title = plan.args.get("title", "")
        task = self._store.add_task(CreateTaskRequest(title=title))
        action = ExecutedAction(
            tool="create_task",
            accepted=True,
            reason="ok",
            detail=task.id,
            tier=ActionTier.reversible.value,
        )
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=f"Created task: {task.title}.",
            executed_actions=[action],
        )

    def _create_note(self, plan: ActionPlan) -> ActionRouteResult:
        title = plan.args.get("title", "Note")
        content = plan.args.get("content", title)
        note = self._store.add_memory_note(
            CreateMemoryNoteRequest(title=title, content=content, tags=["assistant"])
        )
        action = ExecutedAction(
            tool="create_note",
            accepted=True,
            reason="ok",
            detail=note.id,
            tier=ActionTier.reversible.value,
        )
        return ActionRouteResult(
            handled=True,
            immediate=True,
            reply=f"Saved note: {note.title}.",
            executed_actions=[action],
        )
