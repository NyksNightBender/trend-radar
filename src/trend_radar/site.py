"""Renders the static site from the JSON files in data/days/."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, date, datetime, time
from email.utils import format_datetime
from importlib.resources import files
from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup

from .config import REPO_URL, SITE_URL
from .store import Store

MONTHS = [
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
]
WEEKDAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def tr_int(n: float) -> str:
    return f"{round(n):,}".replace(",", ".")


def tr_date(value: str | date, weekday: bool = False) -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    text = f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    return f"{text}, {WEEKDAYS[d.weekday()]}" if weekday else text


def tr_short(value: str | date) -> str:
    d = date.fromisoformat(value) if isinstance(value, str) else value
    return f"{d.day} {MONTHS[d.month - 1][:3]}"


def ratio(r: float) -> str:
    return f"{r:.0f}×" if r >= 10 else f"{r:.1f}×".replace(".", ",")


def sparkline(values: list[int | None], usual: float, width: int = 150, height: int = 42) -> Markup:
    """Inline SVG of the last weeks. Unknown days (below the top-list cutoff) count as zero."""
    nums = [v or 0 for v in values]
    if len(nums) < 2:
        return Markup("")
    peak = max(max(nums), usual, 1)
    step = width / (len(nums) - 1)

    def y(v: float) -> float:
        return height - 3 - (v / peak) * (height - 8)

    pts = " ".join(f"{i * step:.1f},{y(v):.1f}" for i, v in enumerate(nums))
    last_x, last_y = (len(nums) - 1) * step, y(nums[-1])
    return Markup(
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'role="img" aria-label="Son {len(nums)} günün görüntülenmeleri">'
        f'<polygon class="spark-area" points="0,{height} {pts} {width},{height}"/>'
        f'<line class="spark-usual" x1="0" x2="{width}" y1="{y(usual):.1f}" y2="{y(usual):.1f}"/>'
        f'<polyline class="spark-line" points="{pts}"/>'
        f'<circle class="spark-dot" cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5"/></svg>'
    )


def hue(text: str) -> int:
    """A stable colour for a page's initial, so the list is not a wall of grey boxes."""
    return sum(ord(c) * (i + 1) for i, c in enumerate(text)) % 360


def heat(r: float) -> str:
    return "hot" if r >= 20 else "warm" if r >= 8 else "mild"


def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("trend_radar", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        tr_int=tr_int,
        tr_date=tr_date,
        tr_short=tr_short,
        ratio=ratio,
        sparkline=sparkline,
        heat=heat,
        hue=hue,
    )
    env.globals.update(repo_url=REPO_URL, site_url=SITE_URL)
    return env


def week_highlights(days: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    """Largest jumps across the last seven analysed days, one entry per page."""
    best: dict[str, dict[str, Any]] = {}
    for day in days[-7:]:
        for s in day["spikes"]:
            excess = s["views"] - s["usual"]
            if s["article"] not in best or excess > best[s["article"]]["excess"]:
                best[s["article"]] = {**s, "excess": excess, "date": day["date"]}
    return sorted(best.values(), key=lambda s: s["excess"], reverse=True)[:limit]


def build(store: Store, out: Path) -> int:
    env = environment()
    days = [store.load_day(d) for d in store.days()]
    if out.exists():
        shutil.rmtree(out)
    (out / "gun").mkdir(parents=True)
    (out / "api" / "gun").mkdir(parents=True)

    static = files("trend_radar") / "static"
    for name in ("style.css", "favicon.svg"):
        (out / name).write_bytes((static / name).read_bytes())

    day_tpl = env.get_template("day.html")
    pages = 0
    for i, day in enumerate(days):
        prev_day = days[i - 1]["date"] if i > 0 else None
        next_day = days[i + 1]["date"] if i + 1 < len(days) else None
        html = day_tpl.render(day=day, prev_day=prev_day, next_day=next_day, root="../", week=None)
        (out / "gun" / f"{day['date']}.html").write_text(html, encoding="utf-8")
        (out / "api" / "gun" / f"{day['date']}.json").write_text(
            json.dumps(day, ensure_ascii=False), encoding="utf-8"
        )
        pages += 1

    latest = days[-1] if days else None
    index = day_tpl.render(
        day=latest,
        prev_day=days[-2]["date"] if len(days) > 1 else None,
        next_day=None,
        root="",
        week=week_highlights(days),
        is_index=True,
    )
    (out / "index.html").write_text(index, encoding="utf-8")
    if latest:
        (out / "api" / "latest.json").write_text(
            json.dumps(latest, ensure_ascii=False), encoding="utf-8"
        )

    months: dict[str, list[dict[str, Any]]] = {}
    for day in reversed(days):
        d = date.fromisoformat(day["date"])
        months.setdefault(f"{MONTHS[d.month - 1]} {d.year}", []).append(day)
    (out / "arsiv.html").write_text(
        env.get_template("archive.html").render(months=months, root="", count=len(days)),
        encoding="utf-8",
    )
    (out / "nasil.html").write_text(
        env.get_template("method.html").render(root=""), encoding="utf-8"
    )

    def pub_date(day: dict[str, Any]) -> str:
        stamp = day.get("generated_at")
        if stamp:
            return format_datetime(datetime.fromisoformat(stamp))
        return format_datetime(datetime.combine(date.fromisoformat(day["date"]), time(), UTC))

    feed = env.get_template("feed.xml").render(days=list(reversed(days[-30:])), pub_date=pub_date)
    (out / "feed.xml").write_text(feed, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    return pages + 3
