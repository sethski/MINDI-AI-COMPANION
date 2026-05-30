from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AppControlRequest,
    AddPermissionGrantRequest,
    AssistantRequest,
    CreateTaskRequest,
    FileOrganizeRequest,
    SyncQueueRequest,
)
from .store import RuntimeStore

app = FastAPI(title="MINDI Local Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

store = RuntimeStore()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "mindi-agent", "version": app.version}


@app.get("/hub/snapshot")
def hub_snapshot():
    return store.snapshot()


@app.post("/assistant/respond")
def assistant_respond(payload: AssistantRequest):
    return store.respond(payload)


@app.get("/tasks")
def list_tasks():
    return store.tasks


@app.post("/tasks")
def add_task(payload: CreateTaskRequest):
    return store.add_task(payload)


@app.get("/audit/logs")
def list_logs():
    return store.logs


@app.post("/sync/queue")
def queue_sync(payload: SyncQueueRequest):
    return store.enqueue_sync(payload)


@app.get("/control/permissions")
def list_permissions():
    return store.list_permissions()


@app.post("/control/permissions")
def add_permission(payload: AddPermissionGrantRequest):
    return store.add_permission(payload)


@app.post("/control/file-organize")
def control_file_organize(payload: FileOrganizeRequest):
    return store.file_organize(payload)


@app.get("/control/apps/allowlist")
def control_apps_allowlist():
    return {"apps": store.list_allowed_apps()}


@app.post("/control/apps/action")
def control_apps_action(payload: AppControlRequest):
    return store.control_app(payload)
