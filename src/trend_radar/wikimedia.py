"""Small async client for the Wikimedia Pageviews API and the MediaWiki Action API."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Sequence
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


class ApiError(RuntimeError):
    pass


# ---------- parsing (pure functions, tested with fixtures) ----------

PLATFORMS = ("desktop", "mobile-web", "mobile-app")


def combine_top_lists(day: date, parts: Sequence[TopList | None]) -> TopList | None:
    """Sums per-platform top lists into one. Needs the mobile-web list, which carries most of
    Turkish Wikipedia's traffic; a page missing from a platform's list counts 0 there, so the
    result slightly undercounts, and final scores use exact per-article views anyway."""
    by_platform = dict(zip(PLATFORMS, parts, strict=True))
    if by_platform.get("mobile-web") is None:
        return None
    views: dict[str, int] = {}
    for part in parts:
        if part is not None:
            for article, count in part.views.items():
                views[article] = views.get(article, 0) + count
    ranked = sorted(views.items(), key=lambda kv: (-kv[1], kv[0]))[:1000]
    return TopList(day=day, views=dict(ranked), rebuilt=True)


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
        extract = (page.get("extract") or "").strip() or None
        result[title] = Summary(
            title=str(page["title"]),
            description=page.get("description"),
            extract=extract,
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
        """The day's 1000 most viewed pages (human traffic), or None if not published yet.

        Wikimedia sometimes never publishes the combined list for a day whose per-platform
        lists exist (2026-10-31 is one), so the combined list is rebuilt from those.
        """
        url = f"{PAGEVIEWS_API}/top/{PROJECT}/{access}/{day:%Y/%m/%d}"
        payload = await self._get(url, not_found_tries=3)
        if payload is not None:
            return parse_top(day, payload)
        if access != "all-access":
            return None
        parts = await asyncio.gather(*(self.top(day, a) for a in PLATFORMS))
        return combine_top_lists(day, parts)

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
        """Short description and two-sentence intro, 20 titles per request. No images: most
        spikes are about people, and the site does not republish their photos."""
        out: dict[str, Summary] = {}
        for i in range(0, len(titles), 20):
            batch = titles[i : i + 20]
            params = {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
                "prop": "extracts|description",
                "exintro": "1",
                "explaintext": "1",
                "exsentences": "2",
                "exlimit": "20",
                "titles": "|".join(display(t) for t in batch),
            }
            payload = await self._get(ACTION_API, params)
            if payload is not None:
                out.update(parse_summaries(batch, payload))
        return out
