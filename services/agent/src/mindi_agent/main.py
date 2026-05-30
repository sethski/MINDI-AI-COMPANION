from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .schemas import (
    AppControlRequest,
    AddPermissionGrantRequest,
    AlertActionRequest,
    AutomationChainRequest,
    AssistantRequest,
    CreateMemoryNoteRequest,
    CreateTaskRequest,
    TaskStatusUpdateRequest,
    TaskUpdateRequest,
    DocumentImportRequest,
    FileOrganizeRequest,
    OcrImportRequest,
    PerceptionAnalyzeRequest,
    SyncQueueRequest,
    TaskNextRunRequest,
    TaskTimeParseRequest,
    CalendarExportRequest,
    CalendarImportRequest,
    SecurityRecoveryRequest,
    WebScrapeRequest,
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


@app.patch("/tasks/{task_id}/status")
def update_task_status(task_id: str, payload: TaskStatusUpdateRequest):
    task = store.update_task_status(task_id=task_id, request=payload)
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task


@app.patch("/tasks/{task_id}")
def update_task(task_id: str, payload: TaskUpdateRequest):
    task = store.update_task(task_id=task_id, request=payload)
    if task is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return task


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    removed = store.delete_task(task_id=task_id)
    if removed is None:
        raise HTTPException(status_code=404, detail="task_not_found")
    return {"accepted": True, "deletedId": task_id}


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


@app.get("/memory/notes")
def memory_notes(limit: int = Query(default=50, ge=1, le=200)):
    return store.list_memory_notes(limit=limit)


@app.post("/memory/notes")
def create_memory_note(payload: CreateMemoryNoteRequest):
    return store.add_memory_note(payload)


@app.get("/memory/search")
def memory_search(q: str = Query(default="", alias="query"), limit: int = Query(default=50, ge=1, le=200)):
    return store.search_memory(query=q, limit=limit)


@app.post("/memory/documents/import")
def memory_document_import(payload: DocumentImportRequest):
    return store.import_document(payload)


@app.get("/memory/documents/search")
def memory_document_search(
    q: str = Query(default="", alias="query"),
    limit: int = Query(default=20, ge=1, le=200),
):
    return store.search_documents(query=q, limit=limit)


@app.post("/memory/ocr/import")
def memory_ocr_import(payload: OcrImportRequest):
    return store.import_ocr_document(payload)


@app.post("/perception/screen/analyze")
def perception_screen_analyze(payload: PerceptionAnalyzeRequest):
    return store.analyze_screen(payload)


@app.get("/perception/permissions")
def perception_permissions():
    return store.perception_permission_status()


@app.get("/memory/perception")
def memory_perception(limit: int = Query(default=20, ge=1, le=200)):
    return store.list_perception_snapshots(limit=limit)


@app.get("/memory/perception/search")
def memory_perception_search(
    q: str = Query(default="", alias="query"),
    limit: int = Query(default=20, ge=1, le=200),
):
    return store.search_perception_snapshots(query=q, limit=limit)


@app.get("/memory/auto-index/status")
def memory_auto_index_status():
    return store.auto_index_status()


@app.post("/memory/auto-index/scan")
def memory_auto_index_scan():
    return store.auto_index_scan_once()


@app.get("/ops/scheduler/status")
def ops_scheduler_status():
    return store.scheduler_status()


@app.post("/ops/scheduler/scan")
def ops_scheduler_scan():
    return store.scheduler_scan_once()


@app.post("/ops/scheduler/next-run")
def ops_scheduler_next_run(payload: TaskNextRunRequest):
    return store.task_next_run(payload)


@app.post("/ops/scheduler/parse-time")
def ops_scheduler_parse_time(payload: TaskTimeParseRequest):
    return store.parse_task_time(payload)


@app.post("/ops/web/scrape")
def ops_web_scrape(payload: WebScrapeRequest):
    return store.scrape_web(payload)


@app.get("/ops/security/events")
def ops_security_events(
    status: str = Query(default="open"),
    limit: int = Query(default=25, ge=1, le=200),
):
    return store.list_security_events(status=status, limit=limit)


@app.post("/ops/security/scan")
def ops_security_scan():
    return store.scan_security()


@app.post("/ops/security/recover")
def ops_security_recover(payload: SecurityRecoveryRequest):
    return store.recover_security_event(payload)


@app.post("/ops/automation/run")
def ops_automation_run(payload: AutomationChainRequest):
    return store.run_automation_chain(payload)


@app.get("/ops/alerts/feed")
def ops_alerts_feed(limit: int = Query(default=25, ge=1, le=200)):
    return store.alerts_feed(limit=limit)


@app.post("/ops/alerts/action")
def ops_alerts_action(payload: AlertActionRequest):
    return store.alerts_action(payload)


@app.post("/calendar/export")
def calendar_export(payload: CalendarExportRequest):
    return store.export_calendar(payload)


@app.post("/calendar/import")
def calendar_import(payload: CalendarImportRequest):
    return store.import_calendar(payload)
