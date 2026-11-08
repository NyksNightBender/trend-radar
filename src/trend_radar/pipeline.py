"""One run: store any top lists that are needed, then analyse each day that is still missing."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from .config import PROJECT, Settings
from .detect import (
    Score,
    TopList,
    baseline_from_history,
    is_spike,
    lockstep,
    mobile_share,
    score,
    screen,
)
from .store import Store
from .titles import display, is_article, is_sensitive, wiki_url
from .wikimedia import Summary


class PageviewSource(Protocol):
    requests: int

    async def top(self, day: date, access: str = "all-access") -> TopList | None: ...
    async def daily(self, article: str, start: date, end: date) -> dict[date, int]: ...
    async def summaries(self, titles: list[str]) -> dict[str, Summary]: ...


def utc_today() -> date:
    return datetime.now(UTC).date()


def target_days(store: Store, today: date, backfill: int = 0, lookback: int = 7) -> list[date]:
    """Yesterday, plus recent days that were missed or a requested backfill, oldest first.

    Days are UTC days, the same calendar GitHub uses for the contribution graph.
    """
    span = max(lookback, backfill)
    candidates = (today - timedelta(days=i) for i in range(1, span + 1))
    return sorted(d for d in candidates if not store.has_day(d))


async def ensure_top_lists(
    store: Store, api: PageviewSource, days: Iterable[date]
) -> dict[date, TopList]:
    tops: dict[date, TopList] = {}
    missing: list[date] = []
    for day in sorted(set(days)):
        stored = store.load_top(day)
        if stored is None:
            missing.append(day)
        else:
            tops[day] = stored
    fetched = await asyncio.gather(*(api.top(day) for day in missing))
    for day, top in zip(missing, fetched, strict=True):
        if top is not None:
            store.save_top(top)
            tops[day] = top
    return tops


def _approximate_history(
    article: str, day: date, tops: dict[date, TopList], length: int
) -> list[int | None]:
    start = day - timedelta(days=length - 1)
    series: list[int | None] = []
    for i in range(length):
        top = tops.get(start + timedelta(days=i))
        series.append(None if top is None else top.views.get(article))
    return series


async def analyse_day(
    day: date, tops: dict[date, TopList], api: PageviewSource, settings: Settings
) -> dict[str, Any]:
    top = tops[day]
    articles = [a for a in top.views if is_article(a)]
    candidates = screen(top, tops, articles, settings)

    span = max(settings.history_days, settings.baseline_days + 1)
    start = day - timedelta(days=span - 1)
    histories = await asyncio.gather(
        *(api.daily(article, start, day) for article, _ in candidates), return_exceptions=True
    )

    found: list[tuple[str, Score, list[int | None], bool]] = []
    for (article, rough), history in zip(candidates, histories, strict=True):
        chart_start = day - timedelta(days=settings.history_days - 1)
        if isinstance(history, BaseException) or not history:
            # Exact history unavailable: keep the conservative screening score.
            series = _approximate_history(article, day, tops, settings.history_days)
            if is_spike(rough, settings):
                found.append((article, rough, series, True))
            continue
        views = history.get(day, top.views[article])
        exact = score(views, baseline_from_history(history, day, settings.baseline_days), settings)
        if is_spike(exact, settings):
            series = [
                history.get(chart_start + timedelta(days=i), 0)
                for i in range(settings.history_days)
            ]
            found.append((article, exact, list(series), False))
    found.sort(key=lambda item: item[1].excess, reverse=True)

    desktop = await api.top(day, access="desktop")
    same_source = lockstep(
        {article: s.excess for article, s, *_ in found},
        settings.lockstep_tolerance,
        settings.lockstep_size,
    )
    kept: list[tuple[str, Score, list[int | None], bool, float | None]] = []
    bots: list[dict[str, Any]] = []
    for article, s, series, approximate in found:
        share = mobile_share(article, s.views, desktop)
        reason = None
        if article in same_source:
            reason = "lockstep"
        elif share is not None and share < settings.min_mobile_share:
            reason = "desktop"
        if reason:
            bots.append(
                {
                    "article": article,
                    "title": display(article),
                    "views": s.views,
                    "usual": round(s.median),
                    "mobile_share": None if share is None else round(share, 2),
                    "reason": reason,
                }
            )
        else:
            kept.append((article, s, series, approximate, share))

    kept = kept[: settings.max_spikes + 10]
    summaries = await api.summaries([article for article, *_ in kept]) if kept else {}

    spikes: list[dict[str, Any]] = []
    hidden = 0
    for article, s, series, approximate, share in kept:
        summary = summaries.get(article)
        description = summary.description if summary else None
        if is_sensitive(display(article), description):
            hidden += 1
            continue
        if len(spikes) == settings.max_spikes:
            break
        title = summary.title if summary else display(article)
        spikes.append(
            {
                "rank": len(spikes) + 1,
                "article": article,
                "title": title,
                "url": wiki_url(title),
                "views": s.views,
                "usual": round(s.median),
                "ratio": round(s.ratio, 1),
                "z": round(s.z, 1),
                "mobile_share": None if share is None else round(share, 2),
                "description": description,
                "extract": summary.extract if summary else None,
                "history": {
                    "start": (day - timedelta(days=settings.history_days - 1)).isoformat(),
                    "views": series,
                },
                "approximate": approximate,
            }
        )

    return {
        "date": day.isoformat(),
        "project": PROJECT,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "settings": settings.as_dict(),
        "stats": {
            "pages": len(top.views),
            "articles": len(articles),
            "cutoff": top.cutoff,
            "candidates": len(candidates),
            "spikes": len(spikes),
            "bots": len(bots),
            "hidden": hidden,
        },
        "spikes": spikes,
        "bots": bots,
    }


async def run(
    store: Store, api: PageviewSource, settings: Settings, today: date, backfill: int = 0
) -> list[date]:
    """Analyses every missing day whose data is published. Returns the days written."""
    targets = target_days(store, today, backfill)
    if not targets:
        return []
    needed = {t - timedelta(days=i) for t in targets for i in range(settings.baseline_days + 1)}
    tops = await ensure_top_lists(store, api, needed)
    written: list[date] = []
    for day in targets:
        if day not in tops:
            print(f"{day}: not published by Wikimedia yet")
            continue
        result = await analyse_day(day, tops, api, settings)
        store.save_day(day, result)
        stats = result["stats"]
        print(
            f"{day}: {stats['articles']} articles, {stats['candidates']} candidates, "
            f"{stats['spikes']} spikes, {stats['bots']} suspected bots"
        )
        written.append(day)
    return written
