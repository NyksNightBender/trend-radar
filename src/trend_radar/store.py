"""Files in data/: one CSV per day for the raw top list, one JSON per day for the results."""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path
from typing import Any

from .detect import TopList


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _top_path(self, day: date) -> Path:
        return self.root / "top" / f"{day:%Y}" / f"{day:%Y-%m-%d}.csv"

    def _day_path(self, day: date) -> Path:
        return self.root / "days" / f"{day:%Y}" / f"{day:%Y-%m-%d}.json"

    def load_top(self, day: date) -> TopList | None:
        path = self._top_path(day)
        if not path.exists():
            return None
        with path.open(encoding="utf-8", newline="") as f:
            return TopList(
                day=day, views={r["article"]: int(r["views"]) for r in csv.DictReader(f)}
            )

    def save_top(self, top: TopList) -> None:
        path = self._top_path(top.day)
        path.parent.mkdir(parents=True, exist_ok=True)
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(["rank", "article", "views"])
        ranked = sorted(top.views.items(), key=lambda kv: (-kv[1], kv[0]))
        for rank, (article, views) in enumerate(ranked, start=1):
            writer.writerow([rank, article, views])
        path.write_text(buf.getvalue(), encoding="utf-8")

    def has_day(self, day: date) -> bool:
        return self._day_path(day).exists()

    def save_day(self, day: date, result: dict[str, Any]) -> None:
        path = self._day_path(day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def days(self) -> list[date]:
        return sorted(date.fromisoformat(p.stem) for p in (self.root / "days").glob("*/*.json"))

    def load_day(self, day: date) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self._day_path(day).read_text(encoding="utf-8"))
        return data
