"""PII detection and redaction patterns, shared across scraping and OCR import."""

from __future__ import annotations

import re

SENSITIVE_TEXT_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "[REDACTED_EMAIL]"),
    # Requires separator characters to avoid matching plain integers like order IDs.
    ("phone", re.compile(r"\b(?:\+\d{1,3}[\s\-.])?(?:\(?\d{3}\)?[\s\-.]){1,2}\d{3}[\s\-.]?\d{4}\b"), "[REDACTED_PHONE]"),
    # Requires the canonical grouped-card format (XXXX-XXXX-XXXX-XXXX or space-separated).
    ("card", re.compile(r"\b(?:\d{4}[- ]){3}\d{4}\b"), "[REDACTED_CARD]"),
    ("secret", re.compile(r"\b(?:sk|pk|api|token|auth|key|secret|access)[-_]?[A-Za-z0-9]{12,}\b", re.IGNORECASE), "[REDACTED_SECRET]"),
    ("github_token", re.compile(r"\b(?:ghp_|gho_|ghu_|github_pat_)[A-Za-z0-9_]{20,}\b"), "[REDACTED_SECRET]"),
    ("aws_key", re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "[REDACTED_SECRET]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), "[REDACTED_SECRET]"),
    ("pem_header", re.compile(r"-----BEGIN [A-Z ]+-----"), "[REDACTED_KEY]"),
    (
        "password",
        re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+"),
        "[REDACTED_PASSWORD]",
    ),
]


def redact_sensitive_text(text: str) -> tuple[str, int]:
    """Apply all PII patterns to *text*, returning (redacted_text, match_count)."""
    current = text
    total = 0
    for _, pattern, replacement in SENSITIVE_TEXT_PATTERNS:
        current, count = pattern.subn(replacement, current)
        total += count
    return current, total
