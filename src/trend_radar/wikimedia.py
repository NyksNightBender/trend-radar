"""Small async client for the Wikimedia Pageviews API and the MediaWiki Action API."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import ACTION_API, PAGEVIEWS_API, PROJECT, USER_AGENT
from .detect import TopList
from .titles import display


@dataclass(frozen=True)
class Summary:
    title: str
    description: str | None
    extract: str | None
    thumbnail: str | None


class ApiError(RuntimeError):
    pass


# ---------- parsing (pure functions, tested with fixtures) ----------


def parse_top(day: date, payload: Any) -> TopList:
    try:
        articles = payload["items"][0]["articles"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ApiError(f"unexpected top-list shape for {day}") from exc
    return TopList(day=day, views={str(a["article"]): int(a["views"]) for a in articles})


def parse_daily(payload: Any) -> dict[date, int]:
    items = payload.get("items", []) if isinstance(payload, dict) else []
    out: dict[date, int] = {}
    for item in items:
        stamp = str(item["timestamp"])  # e.g. "2026110700"
        out[datetime.strptime(stamp[:8], "%Y%m%d").date()] = int(item["views"])
    return out


def parse_summaries(requested: Iterable[str], payload: Any) -> dict[str, Summary]:
    """Maps each requested title (underscored, as in the top lists) to its summary, following
    the API's title normalisation and redirects."""
    query = payload.get("query", {}) if isinstance(payload, dict) else {}
    hops: dict[str, str] = {}
    for key in ("normalized", "redirects"):
        for hop in query.get(key, []):
            hops[str(hop["from"])] = str(hop["to"])
    pages = {str(p["title"]): p for p in query.get("pages", []) if not p.get("missing")}
    result: dict[str, Summary] = {}
    for title in requested:
        name = display(title)
        for _ in range(3):
            if name in pages:
                break
            name = hops.get(name, name)
        page = pages.get(name)
        if page is None:
            continue
        thumb = page.get("thumbnail") or {}
        extract = (page.get("extract") or "").strip() or None
        result[title] = Summary(
            title=str(page["title"]),
            description=page.get("description"),
            extract=extract,
            thumbnail=thumb.get("source"),
        )
    return result


# ---------- network ----------


class Wikimedia:
    def __init__(self, client: httpx.AsyncClient, concurrency: int = 4, retries: int = 5) -> None:
        self._client = client
        self._limit = asyncio.Semaphore(concurrency)
        self._retries = retries
        self.requests = 0

    @staticmethod
    def http_client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

    async def _get(
        self, url: str, params: dict[str, str] | None = None, not_found_tries: int = 1
    ) -> Any | None:
        """GET JSON; None on 404. Retries rate limits, server errors and network errors.

        The Pageviews API sometimes answers 404 for data it does have and serves it on the next
        try, so callers can ask for a few attempts before a 404 is taken as final.
        """
        delay = 1.0
        not_found = 0
        for attempt in range(1, self._retries + 1):
            async with self._limit:
                self.requests += 1
                try:
                    res = await self._client.get(url, params=params)
                except httpx.TransportError as exc:
                    if attempt == self._retries:
                        raise ApiError(f"{url}: {exc!r}") from exc
                    res = None
            if res is not None:
                if res.status_code == 404:
                    not_found += 1
                    if not_found >= not_found_tries:
                        return None
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60.0)
                    continue
                if res.status_code < 400:
                    return res.json()
                if res.status_code != 429 and res.status_code < 500:
                    raise ApiError(f"{url}: HTTP {res.status_code}")
                if attempt == self._retries:
                    raise ApiError(f"{url}: HTTP {res.status_code} after {attempt} attempts")
                retry_after = res.headers.get("retry-after", "")
                if retry_after.isdigit():
                    delay = max(delay, float(retry_after))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
        return None

    async def top(self, day: date, access: str = "all-access") -> TopList | None:
        """The day's 1000 most viewed pages (human traffic), or None if not published yet."""
        url = f"{PAGEVIEWS_API}/top/{PROJECT}/{access}/{day:%Y/%m/%d}"
        payload = await self._get(url, not_found_tries=3)
        return None if payload is None else parse_top(day, payload)

    async def daily(self, article: str, start: date, end: date) -> dict[date, int]:
        """Daily human views of one article, all platforms. Days without data are omitted."""
        title = quote(article, safe="")
        url = (
            f"{PAGEVIEWS_API}/per-article/{PROJECT}/all-access/user/{title}/daily/"
            f"{start:%Y%m%d}00/{end:%Y%m%d}00"
        )
        payload = await self._get(url, not_found_tries=2)
        return {} if payload is None else parse_daily(payload)

    async def summaries(self, titles: list[str]) -> dict[str, Summary]:
        """Short description, two-sentence intro and thumbnail, 20 titles per request."""
        out: dict[str, Summary] = {}
        for i in range(0, len(titles), 20):
            batch = titles[i : i + 20]
            params = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "extracts|pageimages|description",
                "exintro": "1",
                "explaintext": "1",
                "exsentences": "2",
                "exlimit": "20",
                "piprop": "thumbnail",
                "pithumbsize": "320",
                "pilimit": "20",
                "titles": "|".join(display(t) for t in batch),
            }
            payload = await self._get(ACTION_API, params)
            if payload is not None:
                out.update(parse_summaries(batch, payload))
        return out
