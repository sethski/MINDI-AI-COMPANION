"""File organisation helpers."""

from __future__ import annotations

from pathlib import Path
from shutil import move
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionLogItem,
    ActionTier,
    FileOrganizeItem,
    FileOrganizeRequest,
    FileOrganizeResponse,
    now_iso,
)


def category_for_suffix(suffix: str) -> str:
    by_suffix = {
        ".png": "images",
        ".jpg": "images",
        ".jpeg": "images",
        ".gif": "images",
        ".webp": "images",
        ".pdf": "documents",
        ".docx": "documents",
        ".txt": "documents",
        ".md": "documents",
        ".csv": "data",
        ".json": "data",
        ".zip": "archives",
        ".7z": "archives",
    }
    return by_suffix.get(suffix.lower(), "other")


class FileService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def file_organize(self, request: FileOrganizeRequest) -> FileOrganizeResponse:
        source = Path(request.sourceDir).resolve()
        target = Path(request.targetDir).resolve()

        if not source.exists() or not source.is_dir():
            return FileOrganizeResponse(accepted=False, reason="source_not_found", movedCount=0, items=[])

        if not self._store._is_path_allowed(source) or not self._store._is_path_allowed(target):
            return FileOrganizeResponse(accepted=False, reason="folder_not_allowed", movedCount=0, items=[])

        items: list[FileOrganizeItem] = []
        for child in source.iterdir():
            if child.is_file():
                cat = category_for_suffix(child.suffix)
                dest = target / cat / child.name
                items.append(
                    FileOrganizeItem(
                        fileName=child.name,
                        sourcePath=str(child),
                        targetPath=str(dest),
                        category=cat,
                    )
                )

        if request.mode == "apply":
            for item in items:
                destination = Path(item.targetPath)
                destination.parent.mkdir(parents=True, exist_ok=True)
                move(item.sourcePath, item.targetPath)
            reason = "applied"
        else:
            reason = "preview_only"

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"file_organize:{request.mode}",
                tier=ActionTier.reversible,
                result="allowed",
                reason=reason,
                createdAt=now_iso(),
            ),
        )
        return FileOrganizeResponse(
            accepted=True,
            reason=reason,
            movedCount=len(items) if request.mode == "apply" else 0,
            items=items,
        )
