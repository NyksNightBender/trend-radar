import asyncio
from datetime import timedelta
from pathlib import Path

from tests.world import DAY, FakeApi
from trend_radar import readme, site
from trend_radar.config import Settings
from trend_radar.pipeline import run, target_days
from trend_radar.store import Store


def test_end_to_end(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    api = FakeApi()
    tomorrow = DAY + timedelta(days=1)
    written = asyncio.run(run(store, api, Settings(), today=tomorrow))
    assert written == [DAY - timedelta(days=i) for i in range(6, -1, -1)]  # a week of lookback

    day = store.load_day(DAY)
    titles = [s["article"] for s in day["spikes"]]
    assert titles == ["Patlayan_Madde"]  # Atatürk is popular every day, so it is no spike
    spike = day["spikes"][0]
    assert spike["views"] == 60_000 and spike["usual"] == 400 and spike["ratio"] == 150
    assert spike["history"]["views"][-1] == 60_000 and len(spike["history"]["views"]) == 42
    reasons = {b["article"]: b["reason"] for b in day["bots"]}
    assert reasons == {
        "Bot_Sayfa": "desktop",
        **{f"Genel_{i}": "lockstep" for i in range(1, 5)},
    }
    assert day["stats"]["hidden"] == 1  # the sensitive page
    assert api.daily_calls <= 3 * Settings().candidates  # screening keeps API use small

    # A second run on the same day does nothing.
    again = FakeApi()
    assert asyncio.run(run(store, again, Settings(), today=tomorrow)) == []
    assert again.requests == 0

    out = tmp_path / "_site"
    site.build(store, out)
    index = (out / "index.html").read_text(encoding="utf-8")
    assert "Patlayan Madde" in index and "60.000" in index and "150×" in index
    assert '<svg class="spark"' in index
    assert "Hassas" not in index and "Bot Sayfa" in index  # bots are listed separately
    assert (out / f"gun/{DAY}.html").exists() and (out / "feed.xml").exists()
    assert "7 Kasım 2026" in (out / "arsiv.html").read_text(encoding="utf-8")

    md = readme.render(day)
    assert "[Patlayan Madde](https://tr.wikipedia.org/wiki/Patlayan_Madde)" in md
    assert "60,000" in md and "150×" in md


def test_unpublished_day_is_retried_later(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    api = FakeApi(published_until=DAY - timedelta(days=1))
    written = asyncio.run(run(store, api, Settings(), today=DAY + timedelta(days=1)))
    assert DAY not in written
    assert DAY in target_days(store, DAY + timedelta(days=1))


class FlakyApi(FakeApi):
    """Fails while analysing one day, as a network error or bad response would."""

    async def top(self, day, access="all-access"):  # type: ignore[no-untyped-def]
        if access == "desktop" and day == DAY - timedelta(days=1):
            raise RuntimeError("connection reset")
        return await super().top(day, access)


def test_one_failing_day_does_not_block_the_others(tmp_path: Path) -> None:
    store = Store(tmp_path / "data")
    written = asyncio.run(run(store, FlakyApi(), Settings(), today=DAY + timedelta(days=1)))
    assert DAY in written and DAY - timedelta(days=1) not in written
    assert DAY - timedelta(days=1) in target_days(store, DAY + timedelta(days=1))  # retried later
