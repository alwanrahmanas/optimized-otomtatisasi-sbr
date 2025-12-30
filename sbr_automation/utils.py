from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
from playwright.async_api import Page


TIMESTAMP_FMT = "%Y%m%d_%H%M%S"


def timestamp() -> str:
    """Generate a filesystem-friendly timestamp."""
    return datetime.now().strftime(TIMESTAMP_FMT)


def norm_space(value: object) -> str:
    """Normalize whitespace and coerce NaN/None to empty string."""
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    # pandas may give numpy scalars; cast to string first
    return re.sub(r"\s+", " ", str(value)).strip()


def nonempty(value: object) -> bool:
    """Return True when a value is not null/empty/whitespace-only."""
    return bool(norm_space(value))


def norm_phone(value: object) -> str:
    """Keep only digits of telephone input."""
    digits = re.findall(r"\d", norm_space(value))
    return "".join(digits)


def norm_float(value: object) -> str:
    """Extract first float-compatible token from text."""
    text = norm_space(value).replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def clear_attention_flag(flag_path: Path | None) -> None:
    """Hapus file penanda agar tidak ada flag basi yang tersisa."""
    if not flag_path:
        return
    try:
        flag_path.unlink(missing_ok=True)
    except Exception:
        pass


def signal_attention(flag_path: Path | None) -> None:
    """Buat file penanda untuk memicu AHK/skrip lain menampilkan jendela."""
    if not flag_path:
        return
    try:
        flag_path.parent.mkdir(parents=True, exist_ok=True)
        flag_path.touch(exist_ok=True)
    except Exception:
        pass


@dataclass(slots=True)
class ScreenshotResult:
    path: Optional[Path]
    reason: str | None = None


async def take_screenshot(page: Page, dest_dir: Path, label: str) -> ScreenshotResult:
    """Capture screenshot with sanitized filename."""
    safe_label = re.sub(r"[^a-zA-Z0-9_-]+", "-", label).strip("-") or "capture"
    filename = f"{timestamp()}_{safe_label[:40]}.png"
    target = ensure_directory(dest_dir) / filename
    try:
        await page.screenshot(path=str(target), full_page=True)
        return ScreenshotResult(target)
    except Exception as exc:  # noqa: BLE001
        return ScreenshotResult(None, reason=str(exc))


def format_candidates(files: Iterable[Path]) -> str:
    return ", ".join(sorted(str(p) for p in files))


def describe_exception(exc: Exception) -> str:
    return f"{exc.__class__.__name__}: {exc}"


def note_with_reason(note: str, shot: ScreenshotResult) -> str:
    if shot.path or not shot.reason:
        return note
    return f"{note} (screenshot-error: {shot.reason})"


async def with_retry(
    fn,
    *,
    attempts: int = 3,
    delay_ms: int = 150,
    backoff: float = 1.5,
) -> object:
    """Jalankan coroutine dengan retry dan backoff sederhana."""
    last_exc: Exception | None = None
    wait = delay_ms / 1000
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if i == attempts - 1:
                break
            await asyncio.sleep(wait)
            wait *= backoff
    if last_exc:
        raise last_exc
