from unittest.mock import patch

from mindi_agent.action_router import ActionRouter, classify_action
from mindi_agent.main import app, store
from mindi_agent.schemas import AutoIndexStatus
from fastapi.testclient import TestClient

client = TestClient(app)


def test_classify_scan_files_intent() -> None:
    plan = classify_action("scan my files now")
    assert plan is not None
    assert plan.tool == "scan_files"


def test_classify_open_app_intent() -> None:
    plan = classify_action("open notepad")
    assert plan is not None
    assert plan.tool == "open_app"
    assert plan.args["appId"] == "notepad.exe"


def test_classify_research_intent() -> None:
    plan = classify_action("research quantum computing trends")
    assert plan is not None
    assert plan.tool == "web_research"


def test_memory_graph_endpoint() -> None:
    response = client.get("/memory/graph")
    assert response.status_code == 200
    body = response.json()
    assert "nodes" in body
    assert "edges" in body
    assert "generatedAt" in body


def test_assistant_scan_files_action_route() -> None:
    router = ActionRouter(store)
    plan = router.classify("scan my documents and files")
    assert plan is not None
    mock_status = AutoIndexStatus(
        running=True,
        watchedPaths=["data/inbox"],
        onDemandPaths=["C:/Users/test/Documents"],
        indexedTotal=3,
        indexedLastRun=1,
    )
    with patch.object(store, "auto_index_scan_once", return_value=mock_status):
        result = router.execute(plan, original_text="scan my documents and files")
    assert result.handled is True
    assert result.immediate is True
    assert result.executed_actions[0].tool == "scan_files"


def test_assistant_respond_create_task_route() -> None:
    response = client.post(
        "/assistant/respond",
        json={"text": "create task buy groceries", "mode": "action"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert any(action["tool"] == "create_task" for action in body.get("executedActions", []))
