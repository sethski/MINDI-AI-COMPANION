from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

from .schemas import CreateMemoryNoteRequest, MemoryDocument, MemoryDocumentChunk, MemoryNote, now_iso

ALLOWED_DOCUMENT_SUFFIXES = {
    ".txt",
    ".md",
    ".json",
    ".csv",
    ".log",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".html",
    ".css",
    ".yaml",
    ".yml",
}


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
    clean = " ".join(text.split())
    if not clean:
        return []
    if len(clean) <= chunk_size:
        return [clean]

    chunks: list[str] = []
    step = max(1, chunk_size - overlap)
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        chunks.append(clean[start:end])
        if end >= len(clean):
            break
        start += step
    return chunks


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_documents (
                  id TEXT PRIMARY KEY,
                  source_path TEXT NOT NULL UNIQUE,
                  title TEXT NOT NULL,
                  imported_at TEXT NOT NULL,
                  chunk_count INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_document_chunks (
                  id TEXT PRIMARY KEY,
                  document_id TEXT NOT NULL,
                  chunk_index INTEGER NOT NULL,
                  text TEXT NOT NULL,
                  FOREIGN KEY(document_id) REFERENCES memory_documents(id)
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

    def import_document(self, source_path: Path) -> MemoryDocument:
        text = self._read_text_file(source_path)
        chunks = chunk_text(text)
        imported_at = now_iso()
        title = source_path.name

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM memory_documents WHERE source_path = ?;",
                (str(source_path),),
            ).fetchone()
            if existing:
                document_id = existing["id"]
                conn.execute(
                    """
                    UPDATE memory_documents
                    SET title = ?, imported_at = ?, chunk_count = ?
                    WHERE id = ?;
                    """,
                    (title, imported_at, len(chunks), document_id),
                )
                conn.execute(
                    "DELETE FROM memory_document_chunks WHERE document_id = ?;",
                    (document_id,),
                )
            else:
                document_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO memory_documents (id, source_path, title, imported_at, chunk_count)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (document_id, str(source_path), title, imported_at, len(chunks)),
                )

            for index, chunk in enumerate(chunks):
                conn.execute(
                    """
                    INSERT INTO memory_document_chunks (id, document_id, chunk_index, text)
                    VALUES (?, ?, ?, ?);
                    """,
                    (str(uuid4()), document_id, index, chunk),
                )
            conn.commit()

        return MemoryDocument(
            id=document_id,
            sourcePath=str(source_path),
            title=title,
            importedAt=imported_at,
            chunkCount=len(chunks),
        )

    def search_documents(self, query: str, limit: int = 20) -> list[MemoryDocumentChunk]:
        q = query.strip()
        if not q:
            return []

        pattern = f"%{q}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  c.id,
                  c.document_id,
                  c.chunk_index,
                  c.text,
                  d.source_path,
                  d.title
                FROM memory_document_chunks c
                INNER JOIN memory_documents d ON d.id = c.document_id
                WHERE c.text LIKE ? OR d.title LIKE ?
                ORDER BY c.chunk_index ASC
                LIMIT ?;
                """,
                (pattern, pattern, max(1, min(limit, 200))),
            ).fetchall()

        q_low = q.lower()
        result: list[MemoryDocumentChunk] = []
        for row in rows:
            text = row["text"]
            score = float(text.lower().count(q_low)) + (1.0 if q_low in row["title"].lower() else 0.0)
            result.append(
                MemoryDocumentChunk(
                    id=row["id"],
                    documentId=row["document_id"],
                    sourcePath=row["source_path"],
                    title=row["title"],
                    text=text,
                    chunkIndex=row["chunk_index"],
                    score=score,
                )
            )
        result.sort(key=lambda item: item.score, reverse=True)
        return result

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

    @staticmethod
    def _read_text_file(path: Path) -> str:
        if path.suffix.lower() not in ALLOWED_DOCUMENT_SUFFIXES:
            raise ValueError("unsupported_file_type")
        size = path.stat().st_size
        if size > 5 * 1024 * 1024:
            raise ValueError("file_too_large")
        return path.read_text(encoding="utf-8", errors="ignore")
