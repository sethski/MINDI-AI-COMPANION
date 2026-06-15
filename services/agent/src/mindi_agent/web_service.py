"""Web scraping and domain/app permission helpers."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

if TYPE_CHECKING:
    from .store import RuntimeStore

from .privacy_utils import redact_sensitive_text
from .schemas import (
    ActionLogItem,
    ActionTier,
    CreateMemoryNoteRequest,
    WebScrapeRequest,
    WebScrapeResponse,
    now_iso,
)


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Allow same-host redirects only; block cross-host redirects to prevent SSRF."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        orig_host = (urlparse(req.full_url).hostname or "").lower()
        new_host = (urlparse(newurl).hostname or "").lower()
        if orig_host != new_host:
            raise URLError(f"cross_host_redirect_blocked:{new_host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _ScrapeHtmlParser(HTMLParser):
    def __init__(self, base_url: str, max_links: int = 20) -> None:
        super().__init__()
        self.base_url = base_url
        self.max_links = max_links
        self.title: str | None = None
        self._capture_title = False
        self._skip_depth = 0
        self._chunks: list[str] = []
        self._links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self._capture_title = True
        if normalized in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if normalized == "a" and len(self._links) < self.max_links:
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value.strip()
                    break
            if href:
                joined = urljoin(self.base_url, href)
                if joined not in self._links:
                    self._links.append(joined)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized == "title":
            self._capture_title = False
        if normalized in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        text = " ".join(data.split()).strip()
        if not text:
            return
        if self._capture_title:
            if self.title:
                self.title = f"{self.title} {text}".strip()
            else:
                self.title = text
            return
        self._chunks.append(text)

    def parsed_text(self, max_chars: int) -> str:
        joined = " ".join(self._chunks)
        return joined[:max_chars].strip()

    def parsed_links(self) -> list[str]:
        return self._links


class WebService:
    def __init__(self, store: RuntimeStore) -> None:
        self._store = store

    def list_allowed_apps(self) -> list[str]:
        app_grants = [g for g in self._store.permission_grants if g.scope == "app"]
        denied = {g.subject.lower() for g in app_grants if g.decision == "deny"}
        allowed = [g.subject for g in app_grants if g.decision == "allow"]
        return [app for app in allowed if app.lower() not in denied]

    def is_app_allowed(self, app_id: str) -> bool:
        return app_id.lower() in {app.lower() for app in self.list_allowed_apps()}

    def resolve_domain_permission(self, hostname: str) -> str:
        host = hostname.strip().lower()
        if not host:
            return "deny"
        domain_grants = [g for g in self._store.permission_grants if g.scope == "domain"]
        for grant in domain_grants:
            subject = grant.subject.strip().lower()
            if not subject:
                continue
            if subject == "*" or host == subject or host.endswith(f".{subject}"):
                return grant.decision
            if subject.startswith("*."):
                root = subject[2:]
                if host == root or host.endswith(f".{root}"):
                    return grant.decision
        return "unset"

    def is_domain_allowed(self, hostname: str) -> bool:
        decision = self.resolve_domain_permission(hostname)
        if decision == "deny":
            return False
        domain_grants = [g for g in self._store.permission_grants if g.scope == "domain"]
        has_allow = any(g.decision == "allow" for g in domain_grants)
        if has_allow:
            return decision == "allow"
        return True

    def scrape_web(self, request: WebScrapeRequest) -> WebScrapeResponse:
        raw_url = (request.url or "").strip()
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return WebScrapeResponse(accepted=False, reason="invalid_url", url=raw_url)

        host = parsed.hostname or ""
        if not self.is_domain_allowed(host):
            return WebScrapeResponse(accepted=False, reason="domain_not_allowed", url=raw_url)

        headers = {
            "User-Agent": "MINDI-Local-Agent/0.2 (+local-safe-scrape)",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.2",
        }
        http_request = Request(raw_url, headers=headers, method="GET")
        _opener = build_opener(_SafeRedirectHandler())

        try:
            with _opener.open(http_request, timeout=10) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                body = response.read(512_000)
        except URLError:
            return WebScrapeResponse(accepted=False, reason="fetch_failed", url=raw_url)
        except Exception:
            return WebScrapeResponse(accepted=False, reason="fetch_error", url=raw_url)

        if not body:
            return WebScrapeResponse(accepted=False, reason="empty_response", url=raw_url)

        decoded = body.decode("utf-8", errors="ignore")
        title: str | None = None
        links: list[str] = []
        text_content = ""

        if "text/html" in content_type or "<html" in decoded.lower():
            parser = _ScrapeHtmlParser(base_url=raw_url, max_links=20)
            parser.feed(decoded)
            parser.close()
            title = parser.title
            links = parser.parsed_links()
            text_content = parser.parsed_text(max_chars=request.maxChars)
        elif "text/plain" in content_type:
            text_content = " ".join(decoded.split())[: request.maxChars].strip()
        else:
            return WebScrapeResponse(accepted=False, reason="unsupported_content_type", url=raw_url)

        stored_note_id: str | None = None
        storage_redacted = False
        redaction_count = 0
        storage_text = text_content
        if self._store.privacy_redaction_enabled and text_content:
            storage_text, redaction_count = redact_sensitive_text(text_content)
            storage_redacted = redaction_count > 0
        if request.storeAsNote and text_content:
            note_title = (title or parsed.netloc or raw_url)[:140]
            note = self._store.add_memory_note(
                CreateMemoryNoteRequest(
                    title=f"Web scrape: {note_title}",
                    content=storage_text,
                    tags=["web", "ops", "scrape"],
                )
            )
            stored_note_id = note.id

        self._store.logs.insert(
            0,
            ActionLogItem(
                id=str(uuid4()),
                intent=f"web_scrape:{parsed.netloc}",
                tier=ActionTier.read_only,
                result="allowed",
                reason=f"text:{len(text_content)}",
                createdAt=now_iso(),
            ),
        )

        return WebScrapeResponse(
            accepted=True,
            reason="ok",
            url=raw_url,
            storageRedacted=storage_redacted,
            redactionCount=redaction_count,
            title=title,
            text=text_content,
            textLength=len(text_content),
            links=links,
            storedNoteId=stored_note_id,
        )
