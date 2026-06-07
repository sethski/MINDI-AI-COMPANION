from pathlib import Path
from collections import Counter
import json
import math
import re
import sqlite3
from threading import Lock
from uuid import uuid4

from .schemas import (
    CreateMemoryNoteRequest,
    MemoryDocument,
    MemoryDocumentChunk,
    MemoryNote,
    PerceptionSnapshot,
    now_iso,
)

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

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'-]{1,31}")
_SEMANTIC_ALIASES = {
    "arrange": ("organize", "sort", "order"),
    "arranging": ("organize", "sort", "order"),
    "clean": ("organize", "tidy", "sort"),
    "cleanup": ("organize", "tidy", "sort"),
    "messy": ("organize", "tidy", "sort"),
    "tidy": ("organize", "clean", "sort"),
    "sort": ("organize", "arrange", "order"),
    "sorted": ("organize", "arrange", "order"),
    "organise": ("organize", "arrange", "sort"),
    "organize": ("arrange", "sort", "folder"),
    "organizes": ("organize", "arrange", "sort"),
    "folder": ("directory", "files", "documents"),
    "folders": ("folder", "directory", "files", "documents"),
    "file": ("document", "folder", "download"),
    "files": ("file", "document", "folder", "download"),
    "document": ("file", "note", "content"),
    "documents": ("document", "file", "note", "content"),
    "download": ("file", "folder", "sort"),
    "downloads": ("download", "file", "folder", "sort"),
    "safe": ("confirmation", "blocked", "guard"),
    "safely": ("safe", "confirmation", "guard"),
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


def _normalize_token(token: str) -> str:
    token = token.lower().strip("'")
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def _semantic_vector(text: str) -> dict[str, float]:
    terms: Counter[str] = Counter()
    for raw in _TOKEN_PATTERN.findall(text):
        token = _normalize_token(raw)
        if not token:
            continue
        terms[token] += 1.0
        for alias in _SEMANTIC_ALIASES.get(token, ()):
            terms[alias] += 0.45
    return dict(terms)


def _cosine_score(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    shared = set(left) & set(right)
    dot = sum(left[key] * right[key] for key in shared)
    if dot <= 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _keyword_score(query: str, title: str, text: str) -> float:
    q = query.lower().strip()
    haystack = f"{title} {text}".lower()
    if not q:
        return 0.0
    score = float(haystack.count(q)) * 3.0
    for token in {_normalize_token(raw) for raw in _TOKEN_PATTERN.findall(q)}:
        if token and token in haystack:
            score += 1.0
    return score


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
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_document_chunk_embeddings (
                  chunk_id TEXT PRIMARY KEY,
                  provider TEXT NOT NULL,
                  model TEXT NOT NULL,
                  vector_json TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(chunk_id) REFERENCES memory_document_chunks(id)
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS perception_snapshots (
                  id TEXT PRIMARY KEY,
                  source_path TEXT,
                  reason TEXT NOT NULL,
                  ocr_mode TEXT,
                  text TEXT,
                  text_length INTEGER NOT NULL,
                  block_count INTEGER NOT NULL,
                  image_width INTEGER,
                  image_height INTEGER,
                  created_at TEXT NOT NULL
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

    def get_note(self, note_id: str) -> MemoryNote | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, content, tags, created_at, updated_at
                FROM memory_notes
                WHERE id = ?;
                """,
                (note_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_note(row)

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
        return self.import_extracted_document(source_path=source_path, text=text, title=source_path.name)

    def import_extracted_document(self, source_path: Path, text: str, title: str | None = None) -> MemoryDocument:
        chunks = chunk_text(text)
        resolved = source_path.resolve()
        imported_at = now_iso()
        document_title = (title or source_path.name).strip() or source_path.name

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM memory_documents WHERE source_path = ?;",
                (str(resolved),),
            ).fetchone()
            if existing:
                document_id = existing["id"]
                conn.execute(
                    """
                    UPDATE memory_documents
                    SET title = ?, imported_at = ?, chunk_count = ?
                    WHERE id = ?;
                    """,
                    (document_title, imported_at, len(chunks), document_id),
                )
                conn.execute(
                    """
                    DELETE FROM memory_document_chunk_embeddings
                    WHERE chunk_id IN (
                      SELECT id FROM memory_document_chunks WHERE document_id = ?
                    );
                    """,
                    (document_id,),
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
                    (document_id, str(resolved), document_title, imported_at, len(chunks)),
                )

            for index, chunk in enumerate(chunks):
                chunk_id = str(uuid4())
                conn.execute(
                    """
                    INSERT INTO memory_document_chunks (id, document_id, chunk_index, text)
                    VALUES (?, ?, ?, ?);
                    """,
                    (chunk_id, document_id, index, chunk),
                )
                vector_json = json.dumps(_semantic_vector(f"{document_title} {chunk}"), sort_keys=True)
                conn.execute(
                    """
                    INSERT INTO memory_document_chunk_embeddings (chunk_id, provider, model, vector_json, created_at)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (chunk_id, "local_semantic", "intfloat/multilingual-e5-small-compatible", vector_json, imported_at),
                )
            conn.commit()

        return MemoryDocument(
            id=document_id,
            sourcePath=str(resolved),
            title=document_title,
            importedAt=imported_at,
            chunkCount=len(chunks),
        )

    def search_documents(self, query: str, limit: int = 20) -> list[MemoryDocumentChunk]:
        q = query.strip()
        if not q:
            return []

        query_vector = _semantic_vector(q)
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  c.id,
                  c.document_id,
                  c.chunk_index,
                  c.text,
                  d.source_path,
                  d.title,
                  e.vector_json
                FROM memory_document_chunks c
                INNER JOIN memory_documents d ON d.id = c.document_id
                LEFT JOIN memory_document_chunk_embeddings e ON e.chunk_id = c.id
                ORDER BY d.imported_at DESC, c.chunk_index ASC
                LIMIT ?;
                """,
                (max(1, min(limit * 50, 5000)),),
            ).fetchall()

        result: list[MemoryDocumentChunk] = []
        for row in rows:
            text = row["text"]
            keyword = _keyword_score(q, row["title"], text)
            try:
                chunk_vector = json.loads(row["vector_json"] or "{}")
            except json.JSONDecodeError:
                chunk_vector = _semantic_vector(f"{row['title']} {text}")
            semantic = _cosine_score(query_vector, chunk_vector)
            if keyword <= 0 and semantic <= 0:
                continue
            retrieval_mode = "hybrid" if keyword > 0 and semantic > 0 else "semantic" if semantic > 0 else "keyword"
            score = keyword + (semantic * 5.0)
            result.append(
                MemoryDocumentChunk(
                    id=row["id"],
                    documentId=row["document_id"],
                    sourcePath=row["source_path"],
                    title=row["title"],
                    text=text,
                    chunkIndex=row["chunk_index"],
                    score=score,
                    retrievalMode=retrieval_mode,
                )
            )
        result.sort(key=lambda item: item.score, reverse=True)
        return result[: max(1, min(limit, 200))]

    def add_perception_snapshot(
        self,
        *,
        source_path: str | None,
        reason: str,
        ocr_mode: str | None,
        text: str | None,
        block_count: int,
        image_width: int | None,
        image_height: int | None,
    ) -> PerceptionSnapshot:
        snapshot_id = str(uuid4())
        created_at = now_iso()
        normalized_text = (text or "").strip() or None
        text_length = len(normalized_text or "")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO perception_snapshots (
                  id, source_path, reason, ocr_mode, text, text_length, block_count, image_width, image_height, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    snapshot_id,
                    source_path,
                    reason.strip(),
                    (ocr_mode or "").strip() or None,
                    normalized_text,
                    text_length,
                    max(0, int(block_count)),
                    image_width,
                    image_height,
                    created_at,
                ),
            )
            conn.commit()
        return PerceptionSnapshot(
            id=snapshot_id,
            sourcePath=source_path,
            reason=reason.strip(),
            ocrMode=(ocr_mode or "").strip() or None,
            text=normalized_text,
            textLength=text_length,
            blockCount=max(0, int(block_count)),
            imageWidth=image_width,
            imageHeight=image_height,
            createdAt=created_at,
        )

    def list_perception_snapshots(self, limit: int = 20) -> list[PerceptionSnapshot]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  id,
                  source_path,
                  reason,
                  ocr_mode,
                  text,
                  text_length,
                  block_count,
                  image_width,
                  image_height,
                  created_at
                FROM perception_snapshots
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._row_to_perception_snapshot(row) for row in rows]

    def search_perception_snapshots(self, query: str, limit: int = 20) -> list[PerceptionSnapshot]:
        q = query.strip()
        if not q:
            return self.list_perception_snapshots(limit=limit)
        pattern = f"%{q}%"
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  id,
                  source_path,
                  reason,
                  ocr_mode,
                  text,
                  text_length,
                  block_count,
                  image_width,
                  image_height,
                  created_at
                FROM perception_snapshots
                WHERE text LIKE ? OR reason LIKE ? OR source_path LIKE ?
                ORDER BY created_at DESC
                LIMIT ?;
                """,
                (pattern, pattern, pattern, max(1, min(limit, 200))),
            ).fetchall()
        return [self._row_to_perception_snapshot(row) for row in rows]

    def latest_perception_snapshot(self) -> PerceptionSnapshot | None:
        items = self.list_perception_snapshots(limit=1)
        if not items:
            return None
        return items[0]

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
    def _row_to_perception_snapshot(row: sqlite3.Row) -> PerceptionSnapshot:
        return PerceptionSnapshot(
            id=row["id"],
            sourcePath=row["source_path"],
            reason=row["reason"],
            ocrMode=row["ocr_mode"],
            text=row["text"],
            textLength=int(row["text_length"] or 0),
            blockCount=int(row["block_count"] or 0),
            imageWidth=row["image_width"],
            imageHeight=row["image_height"],
            createdAt=row["created_at"],
        )

    @staticmethod
    def _read_text_file(path: Path) -> str:
        if path.suffix.lower() not in ALLOWED_DOCUMENT_SUFFIXES:
            raise ValueError("unsupported_file_type")
        size = path.stat().st_size
        if size > 5 * 1024 * 1024:
            raise ValueError("file_too_large")
        return path.read_text(encoding="utf-8", errors="ignore")
