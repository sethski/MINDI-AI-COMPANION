"""Headless runtime smoke: agent + ai_runtime health, /ops/ai/status, assistant, ops smoke."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

AGENT = "http://127.0.0.1:8765"
RUNTIME = "http://127.0.0.1:8877"
LOG_PATH = Path(__file__).resolve().parents[1] / "debug-6dda4e.log"
SESSION = "6dda4e"
RUN_ID = "post-fix"


def log(hypothesis_id: str, location: str, message: str, data: dict) -> None:
    entry = {
        "sessionId": SESSION,
        "runId": RUN_ID,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
    }
    line = json.dumps(entry, ensure_ascii=False)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


def get(url: str, timeout: float = 10.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def post(url: str, payload: dict, timeout: float = 120.0) -> tuple[int, dict | str]:
    raw = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=raw,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, json.loads(body)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(detail)
        except json.JSONDecodeError:
            return exc.code, detail
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)


def main() -> int:
    failures: list[str] = []

    # H1: agent reachable
    code, body = get(f"{AGENT}/health")
    log("H1", "runtime_smoke:agent_health", "agent /health", {"status": code, "body": body})
    if code != 200 or not (isinstance(body, dict) and body.get("ok")):
        failures.append("agent_health")

    # H2: ai_runtime reachable
    code, body = get(f"{RUNTIME}/health", timeout=15.0)
    log("H2", "runtime_smoke:runtime_health", "ai_runtime /health", {"status": code, "body": body})
    if code != 200:
        failures.append("runtime_health")

    # H3: /ops/ai/status exposes explicit readiness reasons (not fake success)
    code, status = get(f"{AGENT}/ops/ai/status", timeout=15.0)
    log("H3", "runtime_smoke:ops_ai_status", "/ops/ai/status", {"status": code, "body": status})
    if code != 200 or not isinstance(status, dict):
        failures.append("ops_ai_status_http")
    else:
        features = status.get("features") or {}
        for feat in ("llm", "asr", "ocr"):
            f = features.get(feat) or {}
            ready = f.get("ready")
            reason = f.get("lastFailureReason")
            log(
                "H3",
                f"runtime_smoke:feature_{feat}",
                f"feature {feat}",
                {"ready": ready, "lastFailureReason": reason},
            )
            if ready is True and reason:
                failures.append(f"{feat}_ready_with_failure_reason")

    # H4: assistant does not claim non-degraded success when LLM not configured
    code, assistant = post(
        f"{AGENT}/assistant/respond",
        {"text": "runtime smoke: one word status"},
        timeout=300.0,
    )
    log("H4", "runtime_smoke:assistant", "/assistant/respond", {"status": code, "body": assistant})
    if code != 200 or not isinstance(assistant, dict):
        failures.append("assistant_http")
    elif assistant.get("degraded") is False and assistant.get("fallbackReason") is None:
        llm = (status.get("features") or {}).get("llm") if isinstance(status, dict) else {}
        if not (isinstance(llm, dict) and llm.get("ready")):
            failures.append("assistant_fake_success_without_llm")

    # H5: ops/ai/smoke returns probe reasons (LLM only, fast)
    code, smoke = post(
        f"{AGENT}/ops/ai/smoke",
        {
            "includeLlm": True,
            "includeAsr": False,
            "includeOcr": False,
            "llmPrompt": "Say OK.",
            "languageMode": "english",
        },
        timeout=120.0,
    )
    log("H5", "runtime_smoke:ops_smoke", "/ops/ai/smoke", {"status": code, "body": smoke})
    if code != 200 or not isinstance(smoke, dict):
        failures.append("ops_smoke_http")
    else:
        llm_probe = (smoke.get("probes") or {}).get("llm") or {}
        if llm_probe.get("attempted") and llm_probe.get("accepted") and not llm_probe.get("reason"):
            llm_feat = (status.get("features") or {}).get("llm") if isinstance(status, dict) else {}
            if not (isinstance(llm_feat, dict) and llm_feat.get("ready")):
                failures.append("smoke_llm_fake_accept")

    # H6: runtime direct /status if present
    code, rt_status = get(f"{RUNTIME}/status", timeout=15.0)
    log("H6", "runtime_smoke:runtime_status", "ai_runtime /status", {"status": code, "body": rt_status})

    summary = {
        "failures": failures,
        "passed": len(failures) == 0,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
    }
    log("SUMMARY", "runtime_smoke:summary", "runtime smoke complete", summary)
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
