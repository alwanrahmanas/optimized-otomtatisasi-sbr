from __future__ import annotations

import csv
from pathlib import Path

from sbr_automation.resume import load_resume_entries, resolve_resume_log_path


def _write_log(path: Path, rows: list[dict]) -> None:
    fieldnames = ["row_index", "level", "note"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_resume_entries_filters_range_and_level(tmp_path: Path):
    log_path = tmp_path / "log_sbr_autofill.csv"
    _write_log(
        log_path,
        [
            {"row_index": "1", "level": "OK", "note": "ok"},
            {"row_index": "2", "level": "ERROR", "note": "err"},
            {"row_index": "5", "level": "OK", "note": "ok"},
        ],
    )
    entries = load_resume_entries(log_path, start_display=1, end_display=3)
    assert set(entries.keys()) == {1}


def test_load_resume_entries_handles_missing_file(tmp_path: Path):
    log_path = tmp_path / "missing.csv"
    entries = load_resume_entries(log_path, start_display=1, end_display=10)
    assert entries == {}


def test_resolve_resume_log_path_prefers_existing(tmp_path: Path):
    base = tmp_path / "artifacts" / "logs" / "2025-01-01"
    base.mkdir(parents=True)
    preferred = base / "log_sbr_autofill.csv"
    preferred.write_text("dummy", encoding="utf-8")
    resolved = resolve_resume_log_path(preferred)
    assert resolved == preferred


def test_resolve_resume_log_path_finds_latest(tmp_path: Path):
    day_dir = tmp_path / "artifacts" / "logs" / "2025-01-02"
    day_dir.mkdir(parents=True)
    older = day_dir / "log_sbr_autofill_00-00-01.csv"
    newer = day_dir / "log_sbr_autofill_00-00-02.csv"
    older.write_text("old", encoding="utf-8")
    newer.write_text("new", encoding="utf-8")
    resolved = resolve_resume_log_path(day_dir / "log_sbr_autofill.csv")
    assert resolved == newer
