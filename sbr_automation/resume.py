from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict

from .utils import describe_exception

RESUME_ELIGIBLE_LEVELS = {"OK"}
_RESUME_PREFIX = "[Resume]"


def load_resume_entries(
    log_path: Path,
    *,
    start_display: int,
    end_display: int,
) -> Dict[int, dict]:
    """Baca log sebelumnya dan pilih baris yang berstatus OK dalam rentang display."""
    if not log_path.exists():
        print(f"{_RESUME_PREFIX} Log sebelumnya tidak ditemukan.")
        return {}

    try:
        with log_path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            entries = {int(row["row_index"]): row for row in reader if row.get("row_index", "").isdigit()}
    except Exception as exc:  # noqa: BLE001
        print(f"{_RESUME_PREFIX} Gagal membaca log: {describe_exception(exc)}")
        return {}

    eligible: Dict[int, dict] = {}
    for idx, row in entries.items():
        if idx < start_display or idx > end_display:
            continue
        level = (row.get("level") or "").upper()
        if level in RESUME_ELIGIBLE_LEVELS:
            eligible[idx] = row

    if not eligible:
        print(f"{_RESUME_PREFIX} Tidak ada baris OK pada rentang yang diminta.")
    else:
        print(f"{_RESUME_PREFIX} {len(eligible)} baris akan dilewati berdasarkan log sebelumnya.")
    return eligible


def resolve_resume_log_path(current_log: Path) -> Path:
    """Cari log resume terbaru jika log untuk run ini belum ada."""
    if current_log.exists():
        return current_log

    run_dir = current_log.parent
    base_dir = run_dir.parent if run_dir.parent != run_dir else run_dir
    prefix = "log_sbr_autofill"

    def _latest_matching(directory: Path) -> Path | None:
        if not directory.exists():
            return None
        candidates = sorted(directory.glob(f"{prefix}_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            return candidates[0]
        legacy = directory / f"{prefix}.csv"
        return legacy if legacy.exists() else None

    if run_dir.exists():
        found = _latest_matching(run_dir)
        if found:
            return found

    if base_dir.exists():
        for candidate_dir in sorted([p for p in base_dir.iterdir() if p.is_dir()], reverse=True):
            found = _latest_matching(candidate_dir)
            if found:
                return found

        legacy = base_dir / current_log.name
        if base_dir != run_dir and legacy.exists():
            return legacy

    return current_log
