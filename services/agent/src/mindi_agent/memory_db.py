from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

from .schemas import CreateMemoryNoteRequest, MemoryNote, now_iso


class MemoryDB:
    def __init__(self, db_path: Path | None = None) -> None:
        self._lock = Lock()
        default_path = Path("data/runtime/memory.db")
        self.db_path = db_path or default_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_notes (
                  id TEXT PRIMARY KEY,
                  title TEXT NOT NULL,
                  content TEXT NOT NULL,
                  tags TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                """
            )
            conn.commit()

    def add_note(self, payload: CreateMemoryNoteRequest) -> MemoryNote:
        note_id = str(uuid4())
        timestamp = now_iso()
        tags_value = ",".join(tag.strip() for tag in payload.tags if tag.strip())
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_notes (id, title, content, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (note_id, payload.title.strip(), payload.content.strip(), tags_value, timestamp, timestamp),
            )
            conn.commit()
        return MemoryNote(
            id=note_id,
            title=payload.title.strip(),
            content=payload.content.strip(),
            tags=[tag for tag in tags_value.split(",") if tag],
            createdAt=timestamp,
            updatedAt=timestamp,
        )

    def list_notes(self, limit: int = 50) -> list[MemoryNote]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, content, tags, created_at, updated_at
                FROM memory_notes
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    def search_notes(self, query: str, limit: int = 50) -> list[MemoryNote]:
        q = query.strip()
        if not q:
            return self.list_notes(limit=limit)
        pattern = f"%{q}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, title, content, tags, created_at, updated_at
                FROM memory_notes
                WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
                ORDER BY updated_at DESC
                LIMIT ?;
                """,
                (pattern, pattern, pattern, max(1, min(limit, 200))),
            ).fetchall()
        return [self._row_to_note(row) for row in rows]

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> MemoryNote:
        tags = [tag for tag in (row["tags"] or "").split(",") if tag]
        return MemoryNote(
            id=row["id"],
            title=row["title"],
            content=row["content"],
            tags=tags,
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )
