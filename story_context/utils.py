import html as html_mod
import re
from datetime import datetime, timezone
from typing import Iterator


def now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunked(values: list, size: int) -> Iterator[list]:
    """Yield successive chunks of `size` from `values`."""
    for i in range(0, len(values), size):
        yield values[i : i + size]


def slugify(text: str) -> str:
    """Lowercase, replace spaces and special chars with hyphens."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def normalize_newlines(text: str) -> str:
    """Normalize Windows line endings to Unix."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def html_to_plain_fallback(html_text: str) -> str:
    """Convert HTML to plain text using stdlib only.

    # Forked from sync/engine.py _html_to_plain() — keep in sync manually.
    # Note: fixed regex for block-level tags (original had malformed group).
    """
    text = re.sub(r"<br\s*/?>", "\n", html_text, flags=re.IGNORECASE)
    text = re.sub(r"</?(div|p|li)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def has_html_tags(text: str) -> bool:
    """Return True if text contains any HTML tag."""
    return bool(re.search(r"<[a-zA-Z]", text))
