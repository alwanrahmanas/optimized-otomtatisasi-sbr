from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

from .config import ExcelSelection
from .utils import format_candidates, norm_space

REQUIRED_COLUMNS_AUTOFILL = ("status", "email", "sumber", "catatan")
REQUIRED_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "status": ("status", "keberadaan_usaha"),
    "email": ("email",),
    "sumber": ("sumber", "sumber_profiling"),
    "catatan": ("catatan", "catatan_profiling"),
}
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    **REQUIRED_COLUMN_ALIASES,
    "idsbr": ("idsbr", "idsbr_master"),
    "nama": ("nama", "nama_usaha", "nama_usaha_pembetulan", "nama_komersial_usaha"),
}
PROFILE_FIELD_KEYS = (
    "nama_usaha_pembetulan",
    "nama_komersial_usaha",
    "alamat_pembetulan",
    "nama_sls",
    "kodepos",
    "nomor_telepon",
    "nomor_whatsapp",
    "website",
    "keberadaan_usaha",
    "idsbr_master",
    "kdprov_pindah",
    "kdkab_pindah",
    "kdprov",
    "kdkab",
    "kdkec",
    "kddesa",
    "jenis_kepemilikan_usaha",
    "bentuk_badan_hukum_usaha",
    "sumber_profiling",
    "catatan_profiling",
)


def resolve_excel(path_arg: str | None, search_dir: Path, sheet_index: int) -> ExcelSelection:
    if path_arg:
        path = Path(path_arg).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"File Excel tidak ditemukan: {path}")
        return ExcelSelection(path=path, sheet_index=sheet_index)

    search_locations = [search_dir, search_dir / "data"]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for location in search_locations:
        if not location.exists():
            continue
        for candidate in sorted(location.glob("*.xlsx")):
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)

    if not candidates:
        raise FileNotFoundError(
            "Tidak ditemukan file .xlsx di folder kerja maupun folder 'data'. "
            "Gunakan argumen --excel untuk memilih file secara eksplisit."
        )
    if len(candidates) > 1:
        raise RuntimeError(
            "Ditemukan lebih dari satu file Excel. Pilih salah satu dengan --excel. Kandidat: "
            f"{format_candidates(candidates)}"
        )
    return ExcelSelection(path=candidates[0], sheet_index=sheet_index)


def load_dataframe(selection: ExcelSelection, dtype: str | Sequence[str] | dict | None = str) -> pd.DataFrame:
    """Load Excel with header cleaning and fallback for multi-row headers."""
    def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df.columns = [_clean_column_name(col) for col in df.columns]
        return df

    df = pd.read_excel(selection.path, sheet_name=selection.sheet_index, dtype=dtype)
    df = _clean_columns(df)

    # If no key columns found (multi-row header), retry with header=1
    key_candidates = ("idsbr", "nama", "keberadaan_usaha", "status")
    if not any(has_column(df, key, aliases=COLUMN_ALIASES) for key in key_candidates):
        alt = pd.read_excel(selection.path, sheet_name=selection.sheet_index, dtype=dtype, header=1)
        df = _clean_columns(alt)

    return df


def ensure_required_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise RuntimeError(f"Kolom wajib belum ada di Excel: {', '.join(missing)}")


def ensure_profile_fields(df: pd.DataFrame) -> None:
    """Pastikan kolom baru untuk pengisian Profiling tersedia."""
    ensure_required_columns(df, PROFILE_FIELD_KEYS)


def extract_profile_payload(df_row) -> dict[str, str]:
    """Kembalikan payload Profiling untuk satu baris Excel."""
    return {key: norm_space(df_row.get(key)) for key in PROFILE_FIELD_KEYS}


def slice_rows(df: pd.DataFrame, start: int | None, end: int | None) -> tuple[int, int]:
    start_idx = 0 if start is None else max(start - 1, 0)
    end_idx = len(df) if end is None else min(end, len(df))
    return start_idx, end_idx


def load_profile_payloads(
    selection: ExcelSelection,
    *,
    start: int | None = None,
    end: int | None = None,
) -> list[dict[str, str]]:
    """Membaca Excel lalu mengembalikan list payload Profiling SBR per baris."""
    df = load_dataframe(selection)
    ensure_profile_fields(df)
    start_idx, end_idx = slice_rows(df, start, end)
    return [extract_profile_payload(df.iloc[i]) for i in range(start_idx, end_idx)]


def _clean_column_name(raw: object) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float) and pd.isna(raw):
        return ""
    text = str(raw)
    # Ambil baris pertama sebelum newline/penjelasan
    text = text.splitlines()[0]
    text = text.strip()
    text = re.sub(r"\s+", "_", text)
    text = text.strip("_")
    return text.lower()


def has_column(df: pd.DataFrame, name: str, *, aliases: dict[str, tuple[str, ...]] | None = None) -> bool:
    if name in df.columns:
        return True
    if aliases:
        for cand in aliases.get(name, ()):
            if cand in df.columns:
                return True
    return False


def ensure_required_with_aliases(df: pd.DataFrame, required: Iterable[str], aliases: dict[str, tuple[str, ...]]) -> None:
    missing: list[str] = []
    for base in required:
        if not has_column(df, base, aliases=aliases):
            missing.append(base)
    if missing:
        raise RuntimeError(f"Kolom wajib belum ada di Excel: {', '.join(missing)}")
