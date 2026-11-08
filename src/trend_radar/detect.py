"""Spike detection: compare a page's views with its own normal traffic.

Two passes keep the number of API calls small:

1. Screening uses only the stored daily top-1000 lists. When a page was not in a day's list,
   its views that day were below the list's cutoff, so the cutoff is used as an upper bound
   (a right-censored value). The resulting baseline can only be too high, never too low, so
   screening never inflates a spike.
2. The best candidates then get their exact daily history from the per-article endpoint, and
   the final robust z-score and ratio are computed from that.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from .config import Settings


@dataclass(frozen=True)
class TopList:
    day: date
    views: dict[str, int] = field(default_factory=dict)  # article -> views, at most 1000 rows

    @property
    def cutoff(self) -> int:
        """Views of the last page in the list: anything missing had fewer."""
        return min(self.views.values()) if self.views else 0


@dataclass(frozen=True)
class Baseline:
    median: float
    mad: float
    days: int
    censored: int = 0  # days where only the upper bound was known


@dataclass(frozen=True)
class Score:
    views: int
    median: float
    z: float
    ratio: float

    @property
    def excess(self) -> float:
        return self.views - self.median


def _baseline(values: list[float], censored: int = 0) -> Baseline:
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return Baseline(median=med, mad=mad, days=len(values), censored=censored)


def baseline_from_history(history: Mapping[date, int], day: date, days: int) -> Baseline:
    """Exact baseline from a per-article daily series. Missing days had zero views."""
    values = [float(history.get(day - timedelta(days=i), 0)) for i in range(1, days + 1)]
    return _baseline(values)


def baseline_from_top_lists(
    article: str, day: date, tops: Mapping[date, TopList], days: int
) -> Baseline | None:
    """Upper-bound baseline from stored top lists; None when too few lists are stored."""
    values: list[float] = []
    censored = 0
    for i in range(1, days + 1):
        top = tops.get(day - timedelta(days=i))
        if top is None:
            continue
        seen = top.views.get(article)
        if seen is None:
            censored += 1
            values.append(float(top.cutoff))
        else:
            values.append(float(seen))
    if len(values) < days // 2:
        return None
    return _baseline(values, censored)


def score(views: int, base: Baseline, settings: Settings) -> Score:
    # MAD is 0 for flat series, so give the scale a floor to keep z finite and meaningful.
    scale = 1.4826 * max(base.mad, 0.05 * base.median, 5.0)
    return Score(
        views=views,
        median=base.median,
        z=(views - base.median) / scale,
        ratio=views / max(base.median, settings.median_floor),
    )


def is_spike(s: Score, settings: Settings) -> bool:
    return s.views >= settings.min_views and s.ratio >= settings.min_ratio and s.z >= settings.min_z


def screen(
    top: TopList, tops: Mapping[date, TopList], articles: Iterable[str], settings: Settings
) -> list[tuple[str, Score]]:
    """First pass over a day's top list; returns candidates, biggest excess first."""
    found: list[tuple[str, Score]] = []
    for article in articles:
        views = top.views[article]
        if views < settings.min_views:
            continue
        base = baseline_from_top_lists(article, top.day, tops, settings.baseline_days)
        if base is None:
            continue
        s = score(views, base, settings)
        if s.ratio >= settings.screen_ratio:
            found.append((article, s))
    found.sort(key=lambda item: item[1].excess, reverse=True)
    return found[: settings.candidates]


def mobile_share(article: str, views: int, desktop: TopList | None) -> float | None:
    """Share of the day's views that did not come from desktop browsers.

    Real-world interest in Türkiye is mostly mobile; automated traffic that slips through
    Wikimedia's bot filter is almost always desktop. A page missing from the desktop top list
    had fewer desktop views than that list's cutoff, so the result is then a lower bound.
    """
    if desktop is None or views <= 0:
        return None
    seen = desktop.views.get(article)
    if seen is None:
        if desktop.cutoff >= views:
            return None  # the bound says nothing
        seen = desktop.cutoff
    return max(0.0, 1.0 - seen / views)
