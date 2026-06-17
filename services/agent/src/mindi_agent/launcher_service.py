"""Open URLs and local files via the OS launcher."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import ActionLogItem, ActionTier, LauncherRequest, LauncherResponse, now_iso


class LauncherService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def open_url(self, request: LauncherRequest) -> LauncherResponse:
        raw = (request.target or "").strip()
        if not raw:
            return LauncherResponse(accepted=False, reason="url_required", kind="url")
        normalized = raw if "://" in raw else f"https://{raw}"
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return LauncherResponse(accepted=False, reason="invalid_url", kind="url", target=raw)
        host = parsed.hostname or ""
        if not self._store._is_domain_allowed(host):
            return LauncherResponse(accepted=False, reason="domain_not_allowed", kind="url", target=normalized)

        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", normalized],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return LauncherResponse(
                accepted=False,
                reason=f"launch_failed:{exc}",
                kind="url",
                target=normalized,
            )

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"launcher_open_url:{host}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="opened",
                createdAt=now_iso(),
            ),
        )
        return LauncherResponse(accepted=True, reason="opened", kind="url", target=normalized)

    def open_file(self, request: LauncherRequest) -> LauncherResponse:
        raw = (request.target or "").strip().strip("\"'")
        if not raw:
            return LauncherResponse(accepted=False, reason="path_required", kind="file")
        resolved = Path(raw).expanduser().resolve()
        if not resolved.exists():
            return LauncherResponse(
                accepted=False,
                reason="file_not_found",
                kind="file",
                target=str(resolved),
            )
        if not self._store._is_path_allowed(resolved):
            return LauncherResponse(
                accepted=False,
                reason="folder_not_allowed",
                kind="file",
                target=str(resolved),
            )

        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", str(resolved)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            return LauncherResponse(
                accepted=False,
                reason=f"launch_failed:{exc}",
                kind="file",
                target=str(resolved),
            )

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"launcher_open_file:{resolved.name}",
                tier=ActionTier.reversible,
                result="allowed",
                reason="opened",
                createdAt=now_iso(),
            ),
        )
        return LauncherResponse(accepted=True, reason="opened", kind="file", target=str(resolved))
