"""Proactive intelligence: briefings, deadline nudges, idle insights."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import AlertItem, ProactiveNudge, ProactiveStatus, now_iso

NudgeKind = Literal["briefing", "deadline", "idle_insight", "reminder"]


@dataclass
class _ProactiveState:
    orb_idle: bool = True
    last_orb_activity_at: str | None = None
    last_morning_briefing_date: str | None = None
    last_evening_briefing_date: str | None = None
    last_idle_insight_at: str | None = None
    morning_hour: int = 8
    evening_hour: int = 18
    idle_insight_minutes: int = 45
    enabled: bool = True


class ProactiveService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store
        self._state = _ProactiveState()
        self._nudges: list[ProactiveNudge] = []
        self._delivered_alert_ids: set[str] = set()

    def status(self) -> ProactiveStatus:
        return ProactiveStatus(
            enabled=self._state.enabled,
            orbIdle=self._state.orb_idle,
            pendingNudges=len(self._nudges),
            lastMorningBriefingDate=self._state.last_morning_briefing_date,
            lastEveningBriefingDate=self._state.last_evening_briefing_date,
            lastIdleInsightAt=self._state.last_idle_insight_at,
            morningHour=self._state.morning_hour,
            eveningHour=self._state.evening_hour,
            idleInsightMinutes=self._state.idle_insight_minutes,
        )

    def set_orb_idle(self, idle: bool) -> ProactiveStatus:
        self._state.orb_idle = idle
        if not idle:
            self._state.last_orb_activity_at = now_iso()
        return self.status()

    def tick(self) -> None:
        if not self._state.enabled:
            return
        self._maybe_enqueue_briefing()
        self._maybe_enqueue_idle_insight()

    def enqueue_alert_nudges(self, alerts: list[AlertItem]) -> int:
        created = 0
        for alert in alerts:
            if alert.id in self._delivered_alert_ids:
                continue
            self._push_nudge(
                kind="deadline",
                title=alert.title,
                message=alert.detail,
            )
            self._delivered_alert_ids.add(alert.id)
            created += 1
        return created

    def build_briefing_text(self, slot: Literal["morning", "evening"]) -> str:
        hub = self._store.snapshot()
        open_tasks = [task for task in hub.tasks if task.status != "done"]
        due_soon = [
            task
            for task in open_tasks
            if task.dueAt
            and self._store._parse_due_at(task.dueAt) is not None
            and self._store._parse_due_at(task.dueAt) <= datetime.now(timezone.utc).replace(
                hour=23, minute=59, second=59
            )
        ][:4]
        alert_bits = [f"{alert.title}: {alert.detail}" for alert in hub.alerts[:3]]
        greeting = "Good morning" if slot == "morning" else "Good evening"
        task_line = (
            f"You have {len(open_tasks)} open task{'s' if len(open_tasks) != 1 else ''}."
            if open_tasks
            else "No open tasks right now."
        )
        due_line = (
            "Due soon: " + ", ".join(task.title for task in due_soon) + "."
            if due_soon
            else ""
        )
        alert_line = "Alerts: " + "; ".join(alert_bits) + "." if alert_bits else ""
        parts = [greeting + ".", task_line]
        if due_line:
            parts.append(due_line)
        if alert_line:
            parts.append(alert_line)
        return " ".join(parts)

    def run_briefing_now(self, slot: Literal["morning", "evening"] = "morning") -> ProactiveNudge:
        message = self.build_briefing_text(slot)
        return self._push_nudge(
            kind="briefing",
            title="Daily briefing",
            message=message,
        )

    def consume_nudges(self, *, limit: int = 3, only_when_idle: bool = True) -> list[ProactiveNudge]:
        if only_when_idle and not self._state.orb_idle:
            return []
        if not self._nudges:
            return []
        batch = self._nudges[: max(1, min(limit, 10))]
        self._nudges = self._nudges[len(batch) :]
        return batch

    def _maybe_enqueue_briefing(self) -> None:
        now_local = datetime.now()
        today = now_local.date().isoformat()
        hour = now_local.hour

        if hour >= self._state.morning_hour and self._state.last_morning_briefing_date != today:
            self.run_briefing_now("morning")
            self._state.last_morning_briefing_date = today

        if hour >= self._state.evening_hour and self._state.last_evening_briefing_date != today:
            self.run_briefing_now("evening")
            self._state.last_evening_briefing_date = today

    def _maybe_enqueue_idle_insight(self) -> None:
        if not self._state.orb_idle:
            return
        now = datetime.now(timezone.utc)
        if self._state.last_idle_insight_at:
            last = datetime.fromisoformat(self._state.last_idle_insight_at.replace("Z", "+00:00"))
            if (now - last).total_seconds() < self._state.idle_insight_minutes * 60:
                return

        notes = self._store.memory_db.list_notes(limit=3)
        docs = self._store.memory_db.list_documents(limit=3)
        if not notes and not docs:
            return

        bits: list[str] = []
        if notes:
            bits.append(f'Recent note: "{notes[0].title}"')
        if docs:
            bits.append(f'Indexed file: "{docs[0].title}"')
        message = " ".join(bits) + ". Ask me if you want a recap."
        self._push_nudge(kind="idle_insight", title="Idle insight", message=message)
        self._state.last_idle_insight_at = now_iso()

    def _push_nudge(self, *, kind: NudgeKind, title: str, message: str) -> ProactiveNudge:
        nudge = ProactiveNudge(
            id=str(uuid4()),
            kind=kind,
            title=title,
            message=message,
            createdAt=now_iso(),
        )
        self._nudges.append(nudge)
        self._nudges = self._nudges[-20:]
        return nudge
