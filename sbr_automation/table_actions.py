from __future__ import annotations

import re
import time
from typing import Optional

from playwright.async_api import (
    Error as PlaywrightError,
    Locator,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from .playwright_helpers import ensure_click


TABLE_SELECTOR = "#table_direktori_usaha"
TABLE_WRAPPER_SELECTOR = "#table_direktori_usaha_wrapper"
SEARCH_INPUT_SELECTORS = (
    "#table_direktori_usaha_filter input[type='search']",
    "input[type='search'][aria-controls='table_direktori_usaha']",
)
PROCESSING_SELECTORS = (
    f"{TABLE_WRAPPER_SELECTOR} .dataTables_processing",
    f"{TABLE_WRAPPER_SELECTOR} .dt-processing",
    ".blockUI.blockOverlay",
)


async def _locate_search_box(page: Page) -> Optional[Locator]:
    for selector in SEARCH_INPUT_SELECTORS:
        candidate = page.locator(selector)
        if await candidate.count() > 0:
            return candidate.first

    table = page.locator(TABLE_SELECTOR)
    try:
        await table.wait_for(state="attached", timeout=2000)
    except PlaywrightTimeoutError:
        return None

    candidates: list[Locator] = []

    header_inputs = table.locator("thead input")
    header_count = await header_inputs.count()
    for idx in range(header_count):
        candidates.append(header_inputs.nth(idx))

    fallback_inputs = table.locator("tfoot input")
    fallback_count = await fallback_inputs.count()
    for idx in range(fallback_count):
        candidates.append(fallback_inputs.nth(idx))

    for locator in candidates:
        placeholder = (await locator.get_attribute("placeholder") or "").lower()
        aria = (await locator.get_attribute("aria-label") or "").lower()
        name_attr = (await locator.get_attribute("name") or "").lower()
        label = f"{placeholder} {aria} {name_attr}"
        if "idsbr" in label or "id sbr" in label:
            return locator

    if candidates:
        return candidates[0]
    return None


async def _is_selector_visible(page: Page, selector: str) -> bool:
    try:
        return await page.evaluate(
            """
            sel => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.visibility === 'hidden' || style.display === 'none') return false;
                const opacity = parseFloat(style.opacity || '1');
                if (opacity === 0) return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            }
            """,
            selector,
        )
    except Exception:  # noqa: BLE001
        return False


async def _wait_table_idle(page: Page, timeout: int) -> None:
    deadline = time.monotonic() + timeout / 1000
    idle_confirmations = 0
    announced_wait = False

    while time.monotonic() < deadline:
        if page.is_closed():
            return

        overlay_visible = False
        for selector in PROCESSING_SELECTORS:
            if await _is_selector_visible(page, selector):
                overlay_visible = True
                break

        if not overlay_visible:
            idle_confirmations += 1
            if announced_wait:
                print("    [Tabel] Selesai memuat.")
                announced_wait = False
            if idle_confirmations >= 2:
                return
        else:
            idle_confirmations = 0
            if not announced_wait:
                print("    [Tabel] Menunggu tabel selesai memuat...")
                announced_wait = True
        await page.wait_for_timeout(120)


async def _set_input_value(locator: Locator, value: str) -> None:
    await locator.evaluate(
        """(el, val) => {
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        value,
    )


async def _apply_table_search(page: Page, text: str, timeout: int) -> bool:
    search_box = await _locate_search_box(page)
    if not search_box:
        return False

    if text:
        print(f"    [Cari] Terapkan filter: {text}")
    else:
        print("    [Cari] Hapus filter tabel")

    try:
        await search_box.wait_for(state="visible", timeout=timeout)
    except PlaywrightTimeoutError:
        return False

    try:
        await _set_input_value(search_box, text)
    except PlaywrightError:
        try:
            await search_box.fill("")
            if text:
                await search_box.type(text, delay=30)
        except PlaywrightError:
            return False

    await page.wait_for_timeout(250)
    await _wait_table_idle(page, min(timeout, 4000))
    return True


async def _await_row(table: Locator, row: Locator, timeout: int) -> Optional[Locator]:
    try:
        await row.wait_for(state="visible", timeout=timeout)
        return row
    except PlaywrightTimeoutError:
        empty = table.locator("tbody tr td.dataTables_empty").first
        try:
            await empty.wait_for(state="visible", timeout=500)
        except PlaywrightTimeoutError:
            pass
        return None


def _text_variants(raw_text: str) -> list[str]:
    base = raw_text.strip()
    if not base:
        return []

    variants = [base]

    decimal_variant = base.replace(",", ".")
    if decimal_variant not in variants:
        variants.append(decimal_variant)

    if re.fullmatch(r"-?\d+(?:\.\d+)?", decimal_variant):
        stripped = decimal_variant.rstrip("0").rstrip(".")
        if stripped and stripped not in variants:
            variants.append(stripped)
        try:
            numeric = float(decimal_variant)
        except ValueError:
            pass
        else:
            if numeric.is_integer():
                integer_form = str(int(numeric))
                if integer_form not in variants:
                    variants.append(integer_form)

    # Preserve order while dropping duplicates
    seen = set()
    ordered = []
    for variant in variants:
        if variant not in seen:
            ordered.append(variant)
            seen.add(variant)
    return ordered


async def click_edit_by_index(page: Page, index0: int, *, timeout: int, perform_click: bool = True) -> bool:
    table = page.locator(TABLE_SELECTOR)
    await table.wait_for(state="visible", timeout=timeout)
    await _wait_table_idle(page, timeout)

    rows = table.locator("tbody > tr")
    if index0 >= await rows.count():
        return False

    row = rows.nth(index0)
    btn = row.locator("css=td >> div.d-flex.align-items-center.col-actions >> a.btn-edit-perusahaan").first
    if await btn.count() == 0:
        fallback = row.locator(f"xpath=//*[@id='table_direktori_usaha']/tbody/tr[{index0+1}]/td[10]/div/a[1]")
        if await fallback.count() == 0:
            return False
        if not perform_click:
            return True
        return await ensure_click(fallback, name="Edit row (fallback)", timeout=timeout, attempts=1)

    if not perform_click:
        return True

    ok = await ensure_click(btn, name="Edit row", timeout=timeout, attempts=1)
    return bool(ok)


async def click_edit_by_text(page: Page, text: str, *, timeout: int, perform_click: bool = True) -> bool:
    text = text.strip()
    if not text:
        return False

    print(f"    [Cari] Target baris: {text}")

    table = page.locator(TABLE_SELECTOR)
    await table.wait_for(state="visible", timeout=timeout)
    await _wait_table_idle(page, timeout)

    for candidate in _text_variants(text):
        pattern = re.compile(re.escape(candidate), re.I)
        used_filter = await _apply_table_search(page, candidate, timeout)
        row_locator = table.locator("tbody tr").filter(has_text=pattern).first

        if used_filter:
            await _wait_table_idle(page, timeout)

        row: Optional[Locator]
        if used_filter:
            row = await _await_row(table, row_locator, timeout)
        else:
            try:
                await row_locator.wait_for(state="visible", timeout=timeout)
                row = row_locator
            except PlaywrightTimeoutError:
                row = None

        if not row:
            print(f"    [Cari] Tidak menemukan baris untuk '{candidate}'.")
            if used_filter:
                await _apply_table_search(page, "", timeout)
            continue

        btn = row.locator("css=td >> div.d-flex.align-items-center.col-actions >> a.btn-edit-perusahaan").first
        if await btn.count() > 0:
            print("    [Klik] Tombol edit ditemukan (primary selector).")
            if perform_click:
                ok = await ensure_click(btn, name="Edit by text", timeout=timeout, attempts=1)
                if used_filter:
                    await _apply_table_search(page, "", timeout)
                if ok:
                    return True
                continue
            if used_filter:
                await _apply_table_search(page, "", timeout)
            return True

        fallback = row.locator("xpath=.//td[div[contains(@class,'col-actions')]]//a[1]")
        if await fallback.count() > 0:
            print("    [Klik] Tombol edit ditemukan (fallback selector).")
            if perform_click:
                ok = await ensure_click(fallback, name="Edit by text (fallback)", timeout=timeout, attempts=1)
                if used_filter:
                    await _apply_table_search(page, "", timeout)
                if ok:
                    return True
                continue
            if used_filter:
                await _apply_table_search(page, "", timeout)
            return True

        print("    [Klik] Tombol edit tidak tersedia pada baris yang ditemukan.")

    return False
