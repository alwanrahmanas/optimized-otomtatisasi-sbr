from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RowContext:
    table_index: int
    display_index: int
    idsbr: str
    nama: str
    status: str
    phone: str
    whatsapp: str
    email: str
    website: str
    latitude: str
    longitude: str
    sumber: str
    catatan: str
    profiling_payload: dict[str, str]


@dataclass(slots=True)
class SubmitResult:
    code: str
    detail: str = ""
