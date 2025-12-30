from __future__ import annotations

import pandas as pd

from sbr_automation.loader import _normalize_status, _select_phone_value


def test_normalize_status_handles_numeric_and_alias():
    assert _normalize_status("1") == "Aktif"
    assert _normalize_status("8") == "Aktif Nonrespon"
    assert _normalize_status("belum berproduksi") == "Belum Beroperasi/Berproduksi"
    assert _normalize_status("Custom") == "Custom"


def test_select_phone_value_prefers_filled_alias():
    df_row = pd.Series(
        {
            "nomor_whatsapp": "  0812 0000 1111 ",
            "nomor_telepon": "",
        }
    )
    assert _select_phone_value(df_row).strip() == "0812 0000 1111"

    df_row2 = pd.Series({"Phone": "123", "nomor_whatsapp": ""})
    assert _select_phone_value(df_row2) == "123"
