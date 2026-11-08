"""Keeps the "Yesterday" table in README.md current."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from .config import SITE_URL

START = "<!-- TODAY:START -->"
END = "<!-- TODAY:END -->"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(day: dict[str, Any], limit: int = 5) -> str:
    when = date.fromisoformat(day["date"])
    spikes = day["spikes"][:limit]
    if not spikes:
        return f"_No unusual spikes on {when:%-d %B %Y}._"
    lines = [
        f"**Biggest jumps on Turkish Wikipedia, {when:%-d %B %Y}** ([full list]({SITE_URL}))",
        "",
        "| # | Page | Views | Usual | Jump |",
        "| ---: | --- | ---: | ---: | ---: |",
    ]
    for s in spikes:
        about = f" · {_cell(s['description'])}" if s.get("description") else ""
        lines.append(
            f"| {s['rank']} | [{_cell(s['title'])}]({s['url']}){about} | {s['views']:,} | "
            f"~{s['usual']:,} | {s['ratio']:g}× |"
        )
    return "\n".join(lines)


def update(readme: Path, day: dict[str, Any]) -> None:
    text = readme.read_text(encoding="utf-8")
    start, end = text.find(START), text.find(END)
    if start == -1 or end < start:
        raise ValueError("README.md is missing the TODAY markers")
    text = f"{text[: start + len(START)]}\n{render(day)}\n{text[end:]}"
    readme.write_text(text, encoding="utf-8")
