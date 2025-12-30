from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


DEFAULT_PROFILE_FIELD_SELECTORS: Dict[str, str] = {
    "nama_usaha_pembetulan": (
        "input#nama_usaha_pembetulan, input[name='nama_usaha_pembetulan'], "
        "input#nama_usaha, input[name='namaUsaha'], input[name='nama_usaha']"
    ),
    "nama_komersial_usaha": (
        "input#nama_komersial_usaha, input[name='nama_komersial_usaha'], "
        "input#nama_komersial, input[name='nama_komersial'], "
        "input#nama-komersial, input[name='namaKomersial'], "
        "input[placeholder*='Nama Komersial']"
    ),
    "alamat_pembetulan": (
        "textarea#alamat_pembetulan, textarea[name='alamat_pembetulan'], "
        "input#alamat_pembetulan, input[name='alamat_pembetulan'], "
        "input#alamat_usaha, input[name='alamat'], input#alamat"
    ),
    "nama_sls": "input#nama_sls, input[name='nama_sls'], input#sls, input[name='sls']",
    "kodepos": "input#kodepos, input[name='kodepos'], input[name='kode_pos']",
    "nomor_telepon": (
        "input#nomor_telepon, input[name='nomor_telepon'], input[name='telepon'], "
        "input[name='no_telp'], input[name='no_telp_usaha']"
    ),
    "nomor_whatsapp": (
        "input#whatsapp, input[name='whatsapp'], input[name='nomor_whatsapp'], input[name='no_whatsapp']"
    ),
    "website": "input#website, input[name='website']",
    "keberadaan_usaha": (
        "input#keberadaan_usaha, select#keberadaan_usaha, "
        "input[name='keberadaan_usaha'], select[name='keberadaan_usaha']"
    ),
    "idsbr_master": "input#idsbr_master, input[name='idsbr_master']",
    "kdprov_pindah": "input#kdprov_pindah, input[name='kdprov_pindah']",
    "kdkab_pindah": "input#kdkab_pindah, input[name='kdkab_pindah']",
    "kdprov": "input#kdprov, input[name='kdprov']",
    "kdkab": "input#kdkab, input[name='kdkab']",
    "kdkec": "input#kdkec, input[name='kdkec']",
    "kddesa": "input#kddesa, input[name='kddesa']",
    "jenis_kepemilikan_usaha": (
        "select#jenis_kepemilikan_usaha, select[name='jenis_kepemilikan_usaha'], "
        "input#jenis_kepemilikan_usaha, input[name='jenis_kepemilikan_usaha']"
    ),
    "bentuk_badan_hukum_usaha": (
        "select#bentuk_badan_hukum_usaha, select[name='bentuk_badan_hukum_usaha'], "
        "input#bentuk_badan_hukum_usaha, input[name='bentuk_badan_hukum_usaha']"
    ),
    "sumber_profiling": (
        "#sumber_profiling, input#sumber_profiling, input[name='sumber_profiling'], "
        "textarea#sumber_profiling, textarea[name='sumber_profiling']"
    ),
    "catatan_profiling": "#catatan_profiling, textarea#catatan_profiling, textarea[name='catatan_profiling']",
}

# select2-backed fields (klik span, ketik, Enter)
DEFAULT_SELECT2_FIELD_SELECTORS: Dict[str, str] = {
    "kdprov_pindah": "#provinsi_pindah",
    "kdkab_pindah": "#kabupaten_kota_pindah",
    "kdprov": "#provinsi",
    "kdkab": "#kabupaten_kota",
    "kdkec": "#kecamatan",
    "kddesa": "#kelurahan_desa",
    "jenis_kepemilikan_usaha": "#jenis_kepemilikan_usaha",
    "bentuk_badan_hukum_usaha": "#badan_usaha",
}


def load_field_selectors(path: str | Path | None) -> tuple[Dict[str, str], Dict[str, str]]:
    """Load selector map (CSS/select2) from JSON; merge dengan default."""
    profile = dict(DEFAULT_PROFILE_FIELD_SELECTORS)
    select2 = dict(DEFAULT_SELECT2_FIELD_SELECTORS)

    if not path:
        return profile, select2

    file_path = Path(path).expanduser()
    if not file_path.is_absolute():
        file_path = (Path.cwd() / file_path).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"File selector tidak ditemukan: {file_path}")

    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"File selector tidak valid (JSON error): {exc}") from exc

    if not isinstance(raw, dict):
        raise RuntimeError("File selector harus berupa objek/dictionary JSON.")

    raw_fields = raw.get("fields", {})
    raw_select2 = raw.get("select2", {})

    def _merge(source, target: Dict[str, str], label: str) -> None:
        if not source:
            return
        if not isinstance(source, dict):
            raise RuntimeError(f"Bagian '{label}' harus berupa objek JSON (string -> string).")
        for key, value in source.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise RuntimeError(f"Entri '{label}' wajib string -> string, temuan: {key!r}: {value!r}")
            target[key] = value

    _merge(raw_fields, profile, "fields")
    _merge(raw_select2, select2, "select2")

    return profile, select2
