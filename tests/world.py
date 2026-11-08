"""A small synthetic Wikipedia used by the tests."""

from __future__ import annotations

from datetime import date, timedelta

from trend_radar.detect import TopList
from trend_radar.wikimedia import Summary

DAY = date(2026, 11, 7)
STEADY = {f"Madde_{i}": 100 + 3 * i for i in range(1_100)}  # list cutoff ~400, as on trwiki
FIXED = {"Anasayfa": 900_000, "Özel:Ara": 300_000, "Mustafa_Kemal_Atatürk": 20_000}
SPIKING = {
    # Four unrelated pages that gain the same number of views: one automated source.
    "Genel_1": (500, 6_400),
    "Genel_2": (500, 6_420),
    "Genel_3": (500, 6_380),
    "Genel_4": (500, 6_440),
    "Patlayan_Madde": (400, 60_000),
    "Bot_Sayfa": (300, 40_000),
    "Hassas_Madde": (200, 30_000),
}
DESKTOP_SHARE = {"Bot_Sayfa": 0.97, "Patlayan_Madde": 0.25}


def views(article: str, day: date) -> int:
    if article in SPIKING:
        usual, peak = SPIKING[article]
        return peak if day == DAY else usual
    if article in FIXED:
        return FIXED[article]
    return STEADY[article] + (day.toordinal() * 7 + len(article)) % 50


def top_list(day: date, desktop: bool = False) -> TopList:
    everything = [*STEADY, *FIXED, *SPIKING]
    counts = {a: views(a, day) for a in everything}
    if desktop:
        counts = {a: round(v * DESKTOP_SHARE.get(a, 0.3)) for a, v in counts.items()}
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[:1_000]
    return TopList(day=day, views=dict(ranked))


class FakeApi:
    def __init__(self, published_until: date = DAY) -> None:
        self.published_until = published_until
        self.requests = 0
        self.daily_calls = 0

    async def top(self, day: date, access: str = "all-access") -> TopList | None:
        self.requests += 1
        if day > self.published_until:
            return None
        return top_list(day, desktop=access == "desktop")

    async def daily(self, article: str, start: date, end: date) -> dict[date, int]:
        self.requests += 1
        self.daily_calls += 1
        out: dict[date, int] = {}
        d = start
        while d <= end:
            out[d] = views(article, d)
            d += timedelta(days=1)
        return out

    async def summaries(self, titles: list[str]) -> dict[str, Summary]:
        self.requests += 1
        return {
            t: Summary(
                title=t.replace("_", " "),
                description="pornografik film oyuncusu" if t == "Hassas_Madde" else "Örnek madde",
                extract=f"{t.replace('_', ' ')} hakkında kısa bir özet.",
                thumbnail=None,
            )
            for t in titles
        }
