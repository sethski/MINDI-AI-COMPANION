"""Compose web scrape, local RAG, and OCR context into cited research summaries."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .schemas import (
    ActionLogItem,
    ActionTier,
    ExecutedAction,
    WebScrapeRequest,
    now_iso,
)
from .action_router import ActionRouteResult


class ResearchService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def run_research(self, *, query: str, url: str | None = None) -> ActionRouteResult:
        citations: list[dict] = []
        context_blocks: list[str] = []
        executed: list[ExecutedAction] = []

        resolved_url = (url or "").strip() or self._extract_url_from_query(query)
        if resolved_url:
            scrape = self._store.scrape_web(
                WebScrapeRequest(url=resolved_url, maxChars=6000, storeAsNote=True)
            )
            executed.append(
                ExecutedAction(
                    tool="web_scrape",
                    accepted=scrape.accepted,
                    reason=scrape.reason,
                    detail=resolved_url,
                    tier=ActionTier.read_only.value,
                )
            )
            if scrape.accepted and scrape.text:
                citations.append(
                    {
                        "sourceType": "web",
                        "sourcePath": resolved_url,
                        "title": scrape.title or resolved_url,
                        "textPreview": (scrape.text or "")[:280],
                        "score": 1.0,
                    }
                )
                context_blocks.append(
                    "\n".join(
                        [
                            f"Web source: {resolved_url}",
                            f"Title: {scrape.title or 'Untitled'}",
                            f"Content:\n{(scrape.text or '')[:4200]}",
                        ]
                    )
                )

        rag_items = self._store.memory_db.search_documents(query=query, limit=4)
        for index, item in enumerate(rag_items, start=1):
            citations.append(
                {
                    "sourceType": "document",
                    "chunkId": item.id,
                    "documentId": item.documentId,
                    "sourcePath": item.sourcePath,
                    "title": item.title,
                    "textPreview": item.text[:280],
                    "score": item.score,
                }
            )
            context_blocks.append(
                "\n".join(
                    [
                        f"Local source {index}: {item.title}",
                        f"Path: {item.sourcePath}",
                        f"Excerpt: {item.text[:900]}",
                    ]
                )
            )

        if not context_blocks:
            return ActionRouteResult(
                handled=True,
                immediate=True,
                reply=(
                    "I need a URL or indexed local files to research. "
                    "Say 'scan my files' first, or give me a link to summarize."
                ),
                executed_actions=executed,
                citations=[],
            )

        llm_prompt = (
            "You are MINDI doing local research. Summarize the sources below for the user. "
            "Cite sources by title or URL. Do not invent facts outside the provided context. "
            "If evidence is thin, say what is missing.\n\n"
            + "\n\n".join(context_blocks)
            + f"\n\n<user_query>{query}</user_query>"
        )

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"web_research:{resolved_url or 'local'}",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"sources:{len(context_blocks)}",
                createdAt=now_iso(),
            ),
        )

        return ActionRouteResult(
            handled=True,
            immediate=False,
            llm_prompt=llm_prompt,
            citations=citations,
            executed_actions=executed,
        )

    @staticmethod
    def _extract_url_from_query(query: str) -> str | None:
        from .action_router import _extract_url

        return _extract_url(query)
