from dataclasses import dataclass, field
from time import time
from uuid import uuid4

from .schemas import (
    ActionLogItem,
    ActionTier,
    AlertItem,
    AgentStatus,
    AssistantRequest,
    AssistantResponse,
    CreateTaskRequest,
    HubSnapshot,
    PolicyDecision,
    SyncQueueRequest,
    TaskItem,
    now_iso,
)


@dataclass
class RuntimeStore:
    started_at: float = field(default_factory=time)
    tasks: list[TaskItem] = field(default_factory=list)
    alerts: list[AlertItem] = field(default_factory=list)
    logs: list[ActionLogItem] = field(default_factory=list)
    sync_queue: list[dict] = field(default_factory=list)

    def status(self) -> AgentStatus:
        return AgentStatus(
            state="ready",
            uptimeSeconds=max(0, int(time() - self.started_at)),
            listening=True,
            agentVersion="0.1.0",
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
            title=request.title,
            dueAt=request.dueAt,
            status="todo",
            source="manual",
        )
        self.tasks.insert(0, task)
        return task

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
