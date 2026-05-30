from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .schemas import AssistantRequest, CreateTaskRequest, SyncQueueRequest
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
