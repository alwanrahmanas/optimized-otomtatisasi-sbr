from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Literal, Mapping, Optional, Set

from .field_selectors import DEFAULT_PROFILE_FIELD_SELECTORS, DEFAULT_SELECT2_FIELD_SELECTORS
from .utils import ensure_directory


BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = ensure_directory(BASE_DIR / "artifacts")

DEFAULT_SCREENSHOT_DIR = ensure_directory(ARTIFACTS_DIR / "screenshots")
DEFAULT_CANCEL_SCREENSHOT_DIR = ensure_directory(ARTIFACTS_DIR / "screenshots_cancel")
DEFAULT_LOG_DIR = ensure_directory(ARTIFACTS_DIR / "logs")
DEFAULT_ATTENTION_FLAG = ARTIFACTS_DIR / "chromium_attention.flag"

DEFAULT_STATUS_ID_MAP: Dict[str, str] = {
    "Aktif": "kondisi_aktif",
    "Tutup Sementara": "kondisi_tutup_sementara",
    "Belum Beroperasi/Berproduksi": "kondisi_belum_beroperasi_berproduksi",
    "Tutup": "kondisi_tutup",
    "Alih Usaha": "kondisi_alih_usaha",
    "Tidak Ditemukan": "kondisi_tidak_ditemukan",
    "Aktif Pindah": "kondisi_aktif_pindah",
    "Aktif Nonrespon": "kondisi_aktif_nonrespon",
    "Duplikat": "kondisi_duplikat",
    "Salah Kode Wilayah": "kondisi_salah_kode_wilayah",
}

DEFAULT_KEEP_RUNS = 10


@dataclass(slots=True)
class RuntimeConfig:
    cdp_endpoint: str = "http://localhost:9222"
    sheet_index: int = 0
    pause_after_edit_ms: int = 1000
    pause_after_submit_ms: int = 300
    max_wait_ms: int = 6000
    slow_mode: bool = True
    step_delay_ms: int = 700
    verbose: bool = True
    close_browser_on_exit: bool = False
    skip_status: bool = False
    status_id_map: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_STATUS_ID_MAP))
    profile_field_selectors: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_PROFILE_FIELD_SELECTORS))
    select2_field_selectors: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_SELECT2_FIELD_SELECTORS))

    screenshot_dir: Path = DEFAULT_SCREENSHOT_DIR
    cancel_screenshot_dir: Path = DEFAULT_CANCEL_SCREENSHOT_DIR
    log_dir: Path = DEFAULT_LOG_DIR
    run_id: str = ""
    run_started_at: str = ""
    keep_runs: int = DEFAULT_KEEP_RUNS
    profile_path: Optional[str] = None
    attention_flag: Optional[Path] = DEFAULT_ATTENTION_FLAG


@dataclass(slots=True)
class ExcelSelection:
    path: Path
    sheet_index: int


MatchStrategy = Literal["index", "idsbr", "name"]


@dataclass(slots=True)
class AutofillOptions:
    excel: ExcelSelection
    match_by: MatchStrategy = "index"
    start_row: Optional[int] = None  # 1-indexed from CLI
    end_row: Optional[int] = None  # inclusive
    stop_on_error: bool = False
    resume: bool = False
    dry_run: bool = False


@dataclass(slots=True)
class CancelOptions:
    excel: ExcelSelection
    match_by: MatchStrategy = "index"
    start_row: Optional[int] = None
    end_row: Optional[int] = None
    stop_on_error: bool = False


def load_status_map(path: str | Path | None) -> Dict[str, str]:
    if not path:
        return dict(DEFAULT_STATUS_ID_MAP)

    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"File status map tidak ditemukan: {file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"File status map tidak valid (JSON error): {exc}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError("File status map harus berupa objek/dictionary JSON.")

    merged = dict(DEFAULT_STATUS_ID_MAP)
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise RuntimeError("Status map wajib memetakan string (status) ke string (id radio).")
        merged[key] = value

    return merged


def load_profile_defaults(path: str | None, allowed_keys: set[str]) -> Dict[str, Any]:
    if not path:
        return {}

    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()

    if not file_path.is_file():
        raise FileNotFoundError(f"File profil tidak ditemukan: {file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"File profil tidak valid (JSON error): {exc}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError("File profil harus berupa objek/dictionary JSON.")

    unknown = [key for key in raw if key not in allowed_keys]
    if unknown:
        allowed_str = ", ".join(sorted(allowed_keys))
        raise RuntimeError(f"Kunci profil tidak dikenali: {', '.join(unknown)}. Pilihan yang valid: {allowed_str}")

    return dict(raw)


def _sanitize_run_id(candidate: str | None, fallback: str) -> str:
    if not candidate:
        return fallback
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", candidate).strip("_")
    return slug or fallback


def _prune_old_runs(base_dir: Path, keep: int, reserved: Set[str]) -> None:
    if keep <= 0 or not base_dir.exists():
        return
    dirs = [p for p in base_dir.iterdir() if p.is_dir()]
    if len(dirs) <= keep:
        return
    dirs.sort(key=lambda p: p.stat().st_mtime)
    remaining = len(dirs)
    for path in dirs:
        if remaining <= keep:
            break
        if path.name in reserved:
            continue
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            continue
        remaining -= 1


def create_run_directories(run_id: str | None = None, keep_runs: int | None = None) -> tuple[str, Path, Path, Path, str]:
    now = datetime.now()
    day_folder = now.strftime("%Y-%m-%d")
    time_label = now.strftime("%H-%M-%S")

    base_log_dir = ensure_directory(DEFAULT_LOG_DIR / day_folder)
    base_screenshot_dir = ensure_directory(DEFAULT_SCREENSHOT_DIR / day_folder)
    base_cancel_dir = ensure_directory(DEFAULT_CANCEL_SCREENSHOT_DIR / day_folder)

    default_label = time_label
    sanitized = _sanitize_run_id(run_id, default_label)

    def _exists_for_label(label: str) -> bool:
        return any(
            path.exists()
            for path in (
                base_log_dir / f"log_sbr_autofill_{label}.csv",
                base_log_dir / f"log_sbr_cancel_{label}.csv",
                base_log_dir / f"log_sbr_autofill_{label}.html",
                base_log_dir / f"log_sbr_cancel_{label}.html",
            )
        )

    candidate = sanitized
    counter = 2
    while _exists_for_label(candidate):
        candidate = f"{sanitized}-{counter:02d}"
        counter += 1

    limit = DEFAULT_KEEP_RUNS if keep_runs is None else keep_runs
    _prune_old_runs(DEFAULT_LOG_DIR, limit, {day_folder})
    _prune_old_runs(DEFAULT_SCREENSHOT_DIR, limit, {day_folder})
    _prune_old_runs(DEFAULT_CANCEL_SCREENSHOT_DIR, limit, {day_folder})

    started_at = now.isoformat(timespec="seconds")
    return candidate, base_log_dir, base_screenshot_dir, base_cancel_dir, started_at
