from __future__ import annotations

from typing import Dict, Iterable, Tuple

from .config import AutofillOptions, RuntimeConfig
from .excel_loader import (
    COLUMN_ALIASES,
    REQUIRED_COLUMNS_AUTOFILL,
    ensure_profile_fields,
    ensure_required_with_aliases,
    extract_profile_payload,
    load_dataframe,
    slice_rows,
)
from .models import RowContext
from .utils import norm_float, norm_phone, norm_space

PHONE_COLUMN_CANDIDATES = (
    "nomor_telepon",
    "Nomor Telepon",
    "No Telepon",
    "No. Telepon",
    "Telepon",
    "Telepon/HP",
    "Phone",
)
WHATSAPP_COLUMN_CANDIDATES = (
    "nomor_whatsapp",
    "whatsapp",
    "no_whatsapp",
    "no whatsapp",
)

STATUS_NORMALIZATION = {
    "aktif nonrespons": "Aktif Nonrespon",
    "belum berproduksi": "Belum Beroperasi/Berproduksi",
}
STATUS_NUMERIC_MAP = {
    "1": "Aktif",
    "2": "Tutup Sementara",
    "3": "Belum Beroperasi/Berproduksi",
    "4": "Tutup",
    "5": "Alih Usaha",
    "6": "Tidak Ditemukan",
    "7": "Aktif Pindah",
    "8": "Aktif Nonrespon",
    "9": "Duplikat",
    "10": "Salah Kode Wilayah",
    "11": "Salah Kode Wilayah",
}

MATCH_BY_REQUIRED_COLUMNS: Dict[str, Iterable[str]] = {
    "idsbr": ("idsbr", "idsbr_master"),
    "name": ("nama", "nama_usaha", "nama_usaha_pembetulan"),
}


def _select_phone_value(df_row) -> object:
    columns = getattr(df_row, "index", ())
    for column in PHONE_COLUMN_CANDIDATES:
        if column in columns:
            value = df_row.get(column)
            if norm_space(value):
                return value
    for column in PHONE_COLUMN_CANDIDATES:
        if column in columns:
            return df_row.get(column)
    return df_row.get("Nomor Telepon")


def _select_whatsapp_value(df_row) -> object:
    columns = getattr(df_row, "index", ())
    for column in WHATSAPP_COLUMN_CANDIDATES:
        if column in columns:
            value = df_row.get(column)
            if norm_space(value):
                return value
    for column in WHATSAPP_COLUMN_CANDIDATES:
        if column in columns:
            return df_row.get(column)
    return df_row.get("nomor_whatsapp") or df_row.get("whatsapp")


def _normalize_status(status: str) -> str:
    if not status:
        return ""
    if status.isdigit():
        mapped = STATUS_NUMERIC_MAP.get(status.strip())
        if mapped:
            return mapped
    return STATUS_NORMALIZATION.get(status.lower(), status)


def _context_from_row(df_row, table_index: int, display_index: int) -> RowContext:
    idsbr_value = norm_space(df_row.get("idsbr") or df_row.get("idsbr_master") or df_row.get("IDSBR"))
    sumber = norm_space(df_row.get("sumber_profiling") or df_row.get("sumber"))
    catatan = norm_space(df_row.get("catatan_profiling") or df_row.get("catatan"))
    return RowContext(
        table_index=table_index,
        display_index=display_index,
        idsbr=idsbr_value,
        nama=norm_space(
            df_row.get("nama")
            or df_row.get("nama_usaha")
            or df_row.get("nama_usaha_pembetulan")
            or df_row.get("nama_komersial_usaha")
        ),
        status=_normalize_status(norm_space(df_row.get("status") or df_row.get("keberadaan_usaha"))),
        phone=norm_phone(_select_phone_value(df_row)),
        whatsapp=norm_phone(_select_whatsapp_value(df_row)),
        email=norm_space(df_row.get("email")),
        website=norm_space(df_row.get("website")),
        latitude=norm_float(df_row.get("latitude")),
        longitude=norm_float(df_row.get("longitude")),
        sumber=sumber,
        catatan=catatan,
        profiling_payload=extract_profile_payload(df_row),
    )


def _validate_columns(options: AutofillOptions, df) -> None:
    required_columns = tuple(REQUIRED_COLUMNS_AUTOFILL) + tuple(MATCH_BY_REQUIRED_COLUMNS.get(options.match_by, ()))
    ensure_required_with_aliases(df, required_columns, COLUMN_ALIASES)
    ensure_profile_fields(df)


def load_rows(
    options: AutofillOptions,
    config: RuntimeConfig,  # config disertakan untuk ekspansi mendatang (mis. dtype)
) -> Tuple[list[RowContext], int, int]:
    """
    Membaca Excel, memvalidasi kolom, dan mengembalikan list RowContext serta rentang display (start/end).
    """
    df = load_dataframe(options.excel)
    try:
        _validate_columns(options, df)
    except RuntimeError as exc:
        missing_match = [
            col
            for col in MATCH_BY_REQUIRED_COLUMNS.get(options.match_by, ())
            if not any(alias in df.columns for alias in COLUMN_ALIASES.get(col, (col,)))
        ]
        if missing_match:
            raise RuntimeError(
                f"Kolom Excel untuk '--match-by {options.match_by}' wajib ada: {', '.join(missing_match)}."
            ) from exc
        raise
    start_idx, end_idx = slice_rows(df, options.start_row, options.end_row)
    start_display = start_idx + 1
    end_display = end_idx if end_idx else len(df)

    contexts: list[RowContext] = []
    for i in range(start_idx, end_idx):
        contexts.append(_context_from_row(df.iloc[i], i, i + 1))

    return contexts, start_display, end_display
