from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html import escape
import os
from pathlib import Path
from typing import Iterable, Literal, Optional

import pandas as pd

from .utils import signal_attention

Level = Literal["OK", "WARN", "ERROR"]


@dataclass(slots=True)
class LogEvent:
    ts: str
    row_index: int
    level: Level
    stage: str
    idsbr: str = ""
    nama: str = ""
    match_value: str = ""
    note: str = ""
    screenshot: str = ""


@dataclass
class LogBook:
    path: Path
    report_path: Optional[Path] = None
    attention_flag: Optional[Path] = None
    _events: list[LogEvent] = field(default_factory=list)

    def append(self, event: LogEvent) -> None:
        self._events.append(event)
        if event.level == "ERROR":
            signal_attention(self.attention_flag)

    def extend(self, events: Iterable[LogEvent]) -> None:
        for event in events:
            self.append(event)

    def recent_issues(self, *, limit: int = 3, levels: tuple[Level, ...] = ("ERROR", "WARN")) -> list[LogEvent]:
        priority = {"ERROR": 0, "WARN": 1, "OK": 2}
        selected: list[LogEvent] = [e for e in self._events if e.level in levels]
        selected.sort(key=lambda e: (priority.get(e.level, 99), e.row_index))
        return selected[:limit]

    def _build_report(self, df: pd.DataFrame) -> str:
        timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        level_counts = df["level"].value_counts().to_dict()
        summary_items = "".join(
            f"<li><strong>{escape(level)}</strong>: {count}</li>" for level, count in level_counts.items()
        )

        log_dir = self.path.parent.resolve()

        def _make_link(value: str) -> str:
            if not value:
                return ""
            try:
                target = Path(value)
            except Exception:
                return escape(value)

            href = value
            display = target.name
            if target.exists():
                try:
                    rel = target.resolve().relative_to(log_dir)
                    href = rel.as_posix()
                except ValueError:
                    href = os.path.relpath(target, log_dir).replace("\\", "/")
            else:
                href = target.as_posix()
            return f'<a href="{escape(href)}">{escape(display)}</a>'

        df_display = df.copy()
        df_display["screenshot"] = df_display["screenshot"].apply(_make_link)
        table_html = df_display.to_html(index=False, escape=False)
        csv_source = escape(os.path.relpath(self.path, log_dir).replace("\\", "/"))

        return f"""<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="utf-8">
    <title>Laporan SBR Automation</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 2rem; background: #f8f9fa; color: #212529; }}
        h1, h2 {{ color: #0b7285; }}
        .summary {{ background: #e3fafc; padding: 1rem; border-radius: 8px; margin-bottom: 1.5rem; }}
        table {{ border-collapse: collapse; width: 100%; background: #fff; }}
        th, td {{ border: 1px solid #dee2e6; padding: 0.5rem; text-align: left; font-size: 0.95rem; }}
        th {{ background: #0b7285; color: #fff; position: sticky; top: 0; }}
        tr:nth-child(even) {{ background: #f1f3f5; }}
        a {{ color: #0b7285; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Laporan Otomatisasi Profiling SBR</h1>
    <p>Dibuat pada: {escape(timestamp_str)}</p>
    <div class="summary">
        <h2>Ringkasan Level</h2>
        <ul>
            {summary_items or "<li>Belum ada data</li>"}
        </ul>
        <p>CSV sumber: <code>{csv_source}</code></p>
    </div>
    <h2>Detail Baris</h2>
    {table_html}
</body>
</html>
"""

    def save(self) -> None:
        if not self._events:
            return
        df = pd.DataFrame([asdict(e) for e in self._events])
        df.to_csv(self.path, index=False)
        if self.report_path:
            report_html = self._build_report(df)
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            self.report_path.write_text(report_html, encoding="utf-8")


def update_run_index(index_path: Path, entry: dict) -> None:
    fieldnames = [
        "run_id",
        "started_at",
        "command",
        "resume",
        "dry_run",
        "skip_status",
        "ok_rows",
        "error_rows",
        "skipped_rows",
        "log_csv",
        "log_html",
        "profile",
    ]

    index_path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    if index_path.exists():
        try:
            with index_path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    if row.get("run_id") != entry.get("run_id"):
                        rows.append(row)
        except Exception:
            rows = []

    rows.append({key: entry.get(key, "") for key in fieldnames})

    with index_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
