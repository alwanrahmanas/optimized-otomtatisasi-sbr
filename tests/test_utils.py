from __future__ import annotations

import pandas as pd
import pytest

from sbr_automation import utils


def test_norm_space_handles_nan_and_whitespace():
    assert utils.norm_space(None) == ""
    assert utils.norm_space(float("nan")) == ""
    assert utils.norm_space(pd.NA) == ""
    assert utils.norm_space("  a   b  ") == "a b"
    assert utils.norm_space(" a\nb\tc ") == "a b c"


def test_nonempty_uses_norm_space():
    assert utils.nonempty("  data  ")
    assert not utils.nonempty(" \t ")
    assert not utils.nonempty(None)


def test_norm_phone_strips_non_digits():
    assert utils.norm_phone("0812-3456-7890") == "081234567890"
    assert utils.norm_phone(" (021) 123 4567 ") == "0211234567"
    assert utils.norm_phone("") == ""


def test_norm_float_extracts_first_number():
    assert utils.norm_float("abc 12.5 xyz") == "12.5"
    assert utils.norm_float(" -7,3 ") == "-7.3"
    assert utils.norm_float("no number") == ""


@pytest.mark.asyncio
async def test_with_retry_eventually_succeeds():
    calls = {"n": 0}

    async def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("fail first")
        return "ok"

    result = await utils.with_retry(flaky, attempts=3, delay_ms=10, backoff=1.0)
    assert result == "ok"
    assert calls["n"] == 2
