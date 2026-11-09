import asyncio
from datetime import date
from typing import Any

import httpx
import pytest

from trend_radar.wikimedia import (
    Wikimedia,
    combine_top_lists,
    parse_daily,
    parse_summaries,
    parse_top,
)

TOP = {
    "items": [
        {
            "project": "tr.wikipedia",
            "access": "all-access",
            "year": "2026",
            "month": "11",
            "day": "07",
            "articles": [
                {"article": "Anasayfa", "views": 812345, "rank": 1},
                {"article": "Mustafa_Kemal_Atatürk", "views": 20113, "rank": 2},
            ],
        }
    ]
}
DAILY = {
    "items": [
        {
            "project": "tr.wikipedia",
            "article": "X",
            "granularity": "daily",
            "timestamp": "2026110500",
            "access": "all-access",
            "agent": "user",
            "views": 120,
        },
        {
            "project": "tr.wikipedia",
            "article": "X",
            "granularity": "daily",
            "timestamp": "2026110700",
            "access": "all-access",
            "agent": "user",
            "views": 9000,
        },
    ]
}
SUMMARIES = {
    "batchcomplete": True,
    "query": {
        "normalized": [{"fromencoded": False, "from": "Ataturk", "to": "Ataturk"}],
        "redirects": [{"from": "Ataturk", "to": "Mustafa Kemal Atatürk"}],
        "pages": [
            {
                "pageid": 1,
                "ns": 0,
                "title": "Mustafa Kemal Atatürk",
                "extract": "Türk asker ve devlet adamı.",
                "description": "Türkiye Cumhuriyeti'nin kurucusu",
            },
            {"pageid": 2, "ns": 0, "title": "Ege Üniversitesi", "extract": ""},
            {"ns": 0, "title": "Olmayan Sayfa", "missing": True},
        ],
    },
}


def test_parse_top() -> None:
    top = parse_top(date(2026, 11, 7), TOP)
    assert top.views == {"Anasayfa": 812345, "Mustafa_Kemal_Atatürk": 20113}
    assert top.cutoff == 20113


def test_parse_daily() -> None:
    assert parse_daily(DAILY) == {date(2026, 11, 5): 120, date(2026, 11, 7): 9000}
    assert parse_daily({}) == {}


def test_parse_summaries_follows_redirects() -> None:
    found = parse_summaries(["Ataturk", "Ege_Üniversitesi", "Olmayan_Sayfa"], SUMMARIES)
    assert found["Ataturk"].title == "Mustafa Kemal Atatürk"
    assert found["Ataturk"].description == "Türkiye Cumhuriyeti'nin kurucusu"
    assert found["Ege_Üniversitesi"].extract is None
    assert "Olmayan_Sayfa" not in found


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_client_retries_rate_limits_and_maps_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("trend_radar.wikimedia.asyncio.sleep", no_sleep)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "2026/11/08" in request.url.path:
            return httpx.Response(404, json={"title": "Not found."})
        if calls["n"] == 1:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json=TOP)

    async def go() -> None:
        async with _client(handler) as http:
            api = Wikimedia(http)
            top = await api.top(date(2026, 11, 7))
            assert top is not None and top.cutoff == 20113
            assert await api.top(date(2026, 11, 8)) is None

    asyncio.run(go())
    # one rate-limited try and one success; then the missing day gets three tries for the
    # combined list and three for each of the three platform lists
    assert calls["n"] == 14


def test_client_builds_encoded_per_article_url() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=DAILY)

    async def go() -> None:
        async with _client(handler) as http:
            await Wikimedia(http).daily("AC/DC", date(2026, 10, 1), date(2026, 11, 7))

    asyncio.run(go())
    assert seen[0].endswith(
        "/per-article/tr.wikipedia/all-access/user/AC%2FDC/daily/2026100100/2026110700"
    )


def _top_payload(rows: dict[str, int]) -> dict[str, Any]:
    articles = [{"article": a, "views": v, "rank": i} for i, (a, v) in enumerate(rows.items(), 1)]
    return {"items": [{"articles": articles}]}


def test_missing_combined_list_is_rebuilt_from_platforms(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("trend_radar.wikimedia.asyncio.sleep", no_sleep)
    platforms = {
        "desktop": {"A": 100, "B": 900},
        "mobile-web": {"A": 1_000, "C": 300},
        "mobile-app": {"A": 50},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        access = request.url.path.split("/")[-4]
        if access in platforms and "2026/10/31" in request.url.path:
            return httpx.Response(200, json=_top_payload(platforms[access]))
        return httpx.Response(404, json={"title": "Not found."})

    async def go() -> None:
        async with _client(handler) as http:
            api = Wikimedia(http)
            top = await api.top(date(2026, 10, 31))
            assert top is not None and top.rebuilt
            assert top.views == {"A": 1_150, "B": 900, "C": 300}
            assert await api.top(date(2026, 11, 1)) is None  # nothing published at all

    asyncio.run(go())


def test_platform_lists_without_mobile_web_are_not_enough() -> None:
    day = date(2026, 10, 31)
    desktop = parse_top(day, _top_payload({"A": 5}))
    assert combine_top_lists(day, [desktop, None, None]) is None
