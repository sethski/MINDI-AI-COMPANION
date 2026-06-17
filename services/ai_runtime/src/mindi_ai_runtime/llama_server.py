"""Persistent llama-server process manager for warm streaming LLM inference."""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

_server_lock = threading.Lock()
_server_process: subprocess.Popen[str] | None = None
_server_model_path: str | None = None
_server_port: int = 8081


def _server_binary(server_command: str) -> str | None:
    command = server_command.strip()
    if not command:
        return None
    if Path(command).exists():
        return command
    return shutil.which(command)


def _health_ok(port: int) -> bool:
    try:
        with urlopen(f"http://127.0.0.1:{port}/health", timeout=2.0) as resp:
            return resp.status == 200
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def ensure_llama_server(
    *,
    server_command: str,
    model_path: Path,
    port: int = 8081,
    context_size: int = 4096,
    threads: int = 0,
) -> tuple[bool, dict]:
    global _server_process, _server_model_path, _server_port

    binary = _server_binary(server_command)
    if binary is None:
        return False, {"reason": "llama_server_binary_missing"}
    if not model_path.exists() or not model_path.is_file():
        return False, {"reason": "voice_model_path_missing"}

    resolved = str(model_path.resolve())
    with _server_lock:
        _server_port = port
        if (
            _server_process is not None
            and _server_process.poll() is None
            and _server_model_path == resolved
            and _health_ok(port)
        ):
            return True, {"reason": "ok", "port": port}

        if _server_process is not None and _server_process.poll() is None:
            _server_process.terminate()
            try:
                _server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _server_process.kill()

        command = [
            binary,
            "-m",
            resolved,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "-c",
            str(max(256, context_size)),
            "-ngl",
            "0",
            "--parallel",
            "1",
        ]
        if threads > 0:
            command.extend(["-t", str(threads)])

        try:
            _server_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            _server_process = None
            _server_model_path = None
            return False, {"reason": "llama_server_spawn_failed"}

        _server_model_path = resolved
        for _ in range(40):
            if _health_ok(port):
                return True, {"reason": "ok", "port": port}
            if _server_process.poll() is not None:
                _server_process = None
                _server_model_path = None
                return False, {"reason": "llama_server_exited_early"}
            import time

            time.sleep(0.25)

        return False, {"reason": "llama_server_health_timeout"}


def stop_llama_server() -> None:
    global _server_process, _server_model_path
    with _server_lock:
        if _server_process is not None and _server_process.poll() is None:
            _server_process.terminate()
            try:
                _server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _server_process.kill()
        _server_process = None
        _server_model_path = None


def _parse_sse_line(line: str) -> str | None:
    if not line.startswith("data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == "[DONE]":
        return None
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta") if isinstance(choices[0], dict) else None
    if not isinstance(delta, dict):
        return None
    content = delta.get("content")
    if content is None:
        return None
    return str(content)


def stream_chat_completion(
    *,
    port: int,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float = 120.0,
) -> Iterator[str]:
    payload = {
        "model": "voice",
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "max_tokens": max(1, max_tokens),
        "temperature": float(temperature),
    }
    raw = json.dumps(payload, ensure_ascii=True).encode("utf-8")
    req = Request(
        url=f"http://127.0.0.1:{port}/v1/chat/completions",
        method="POST",
        data=raw,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(req, timeout=timeout) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            token = _parse_sse_line(line)
            if token:
                yield token


def chat_completion(
    *,
    port: int,
    prompt: str,
    max_tokens: int,
    temperature: float,
    timeout: float = 120.0,
) -> tuple[bool, dict]:
    chunks = list(
        stream_chat_completion(
            port=port,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )
    )
    reply = "".join(chunks).strip()
    if not reply:
        return False, {"reason": "llama_server_empty_output"}
    return True, {"reply": reply}
