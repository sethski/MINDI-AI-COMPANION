"""Task CRUD and sync queue."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    CreateTaskRequest,
    SyncQueueRequest,
    TaskItem,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
    now_iso,
)


class TaskService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def add_task(self, request: CreateTaskRequest) -> TaskItem:
        if request.idempotencyKey:
            cached = self._store._idempotency_cache.get(request.idempotencyKey)
            if cached is not None:
                return cached
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
        self._store.tasks.insert(0, task)
        self._store.scheduler_alerted_due.pop(task.id, None)
        self._store._persist_durable_state()
        if request.idempotencyKey:
            self._store._idempotency_cache.set(request.idempotencyKey, task)
        return task

    def update_task_status(self, task_id: str, request: TaskStatusUpdateRequest) -> TaskItem | None:
        for task in self._store.tasks:
            if task.id != task_id:
                continue
            task.status = request.status
            if request.status != "done":
                self._store.scheduler_alerted_due.pop(task.id, None)
            self._store._persist_durable_state()
            return task
        return None

    def update_task(self, task_id: str, request: TaskUpdateRequest) -> TaskItem | None:
        for task in self._store.tasks:
            if task.id != task_id:
                continue
            if "title" in request.model_fields_set and request.title is not None:
                task.title = request.title
            if "dueAt" in request.model_fields_set:
                task.dueAt = request.dueAt
                task.nextRunAt = request.dueAt
                self._store.scheduler_alerted_due.pop(task.id, None)
            if "recurrence" in request.model_fields_set:
                task.recurrence = request.recurrence
            if "status" in request.model_fields_set and request.status is not None:
                task.status = request.status
                if request.status != "done":
                    self._store.scheduler_alerted_due.pop(task.id, None)
            self._store._persist_durable_state()
            return task
        return None

    def delete_task(self, task_id: str) -> TaskItem | None:
        for index, task in enumerate(self._store.tasks):
            if task.id != task_id:
                continue
            removed = self._store.tasks.pop(index)
            self._store.scheduler_alerted_due.pop(task_id, None)
            self._store._persist_durable_state()
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
        self._store.sync_queue.insert(0, item)
        return item
