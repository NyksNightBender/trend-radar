"""Helpers for Wikipedia page titles."""

from __future__ import annotations

from urllib.parse import quote

from .config import NON_ARTICLE_NAMESPACES, SENSITIVE_WORDS, SKIP_TITLES, WIKI


def is_article(title: str) -> bool:
    """True for encyclopedia articles; False for the main page, search, categories and so on."""
    if title in SKIP_TITLES or not title.strip():
        return False
    if ":" in title:
        prefix = title.split(":", 1)[0].replace("_", " ").strip().casefold()
        if prefix in NON_ARTICLE_NAMESPACES:
            return False
    return True


def display(title: str) -> str:
    return title.replace("_", " ")


def wiki_url(title: str) -> str:
    return f"{WIKI}/wiki/{quote(title.replace(' ', '_'), safe='')}"


def is_sensitive(*texts: str | None) -> bool:
    joined = " ".join(t for t in texts if t).casefold()
    return any(word in joined for word in SENSITIVE_WORDS)
