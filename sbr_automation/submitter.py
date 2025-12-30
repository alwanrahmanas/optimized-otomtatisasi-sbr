from __future__ import annotations

import re

from playwright.async_api import Locator, Page

from .config import RuntimeConfig
from .form_filler import collect_error_hints
from .models import RowContext, SubmitResult
from .utils import norm_space, with_retry


async def is_locked_page(page: Page) -> bool:
    patterns = [
        re.compile("tidak bisa melakukan edit", re.I),
        re.compile("sedang diedit oleh user lain", re.I),
    ]
    for pattern in patterns:
        try:
            locator = page.get_by_text(pattern)
            await locator.wait_for(state="visible", timeout=1500)
            return True
        except Exception:  # noqa: BLE001
            continue

    try:
        back_btn = page.get_by_role("button", name=re.compile("Back to Home", re.I))
        await back_btn.wait_for(state="visible", timeout=1500)
        return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def is_finalized_form(page: Page) -> bool:
    cancel_btn = (
        page.locator("button#cancel-submit-final, #cancel-submit-final")
        .or_(page.get_by_role("button", name=re.compile("Cancel Submit", re.I)))
        .first
    )
    submit_candidates = [
        page.get_by_role("button", name=re.compile("Submit Final", re.I)).first,
        page.locator("text=Submit Final").first,
    ]

    try:
        visible_cancel = await cancel_btn.is_visible(timeout=1500)
    except Exception:
        visible_cancel = False
    if not visible_cancel:
        return False

    for candidate in submit_candidates:
        try:
            if await candidate.is_visible(timeout=800):
                return False
        except Exception:
            continue

    return True


async def submit_form(page: Page, ctx: RowContext, config: RuntimeConfig) -> SubmitResult:
    btn_role = page.get_by_role("button", name=re.compile("Submit Final", re.I))
    btn_text = page.locator("text=Submit Final").first
    cancel_btn = (
        page.locator("button#cancel-submit-final, #cancel-submit-final")
        .or_(page.get_by_role("button", name=re.compile("Cancel Submit", re.I)))
        .first
    )

    async def try_click(locator: Locator) -> bool:
        try:
            if await locator.is_visible(timeout=800):
                await locator.click()
                return True
        except Exception:
            return False
        return False

    async def click_with_retry(locator: Locator) -> bool:
        async def _op():
            ok = await try_click(locator)
            if not ok:
                raise RuntimeError("target tidak bisa diklik")
            return True

        try:
            await with_retry(_op, attempts=3, delay_ms=150, backoff=1.4)
            return True
        except Exception:
            return False

    if not (await click_with_retry(btn_role) or await click_with_retry(btn_text)):
        try:
            if await cancel_btn.is_visible(timeout=800):
                return SubmitResult("OK", "Lewati submit: form sudah final (hanya ada tombol Cancel Submit).")
        except Exception:
            pass
        hints = await collect_error_hints(page)
        detail = "CODE:SUBMIT_NO_BUTTON Tombol Submit Final tidak terlihat atau tidak dapat diklik."
        if hints:
            detail += f" | Petunjuk: {', '.join(hints)}"
        return SubmitResult("NO_SUBMIT_BUTTON", detail)

    await page.wait_for_timeout(config.pause_after_submit_ms)

    try:
        err = page.get_by_text(re.compile("Masih terdapat isian yang harus diperbaiki", re.I))
        await err.wait_for(state="visible", timeout=1000)
        err_text = ""
        try:
            err_text = norm_space(await err.text_content())
        except Exception:
            err_text = ""
        ok = page.get_by_role("button", name=re.compile("^OK$", re.I))
        if await ok.is_visible():
            await ok.click()
        hints = await collect_error_hints(page)
        detail_parts = ["CODE:SUBMIT_ERROR_FILL Form menolak submit karena ada isian yang perlu diperbaiki."]
        if err_text:
            detail_parts.append(f"Pesan: {err_text}")
        if hints:
            detail_parts.append(f"Petunjuk: {', '.join(hints)}")
        return SubmitResult("ERROR_FILL", " | ".join(detail_parts))
    except Exception:
        pass

    try:
        kons = page.get_by_text(re.compile("Cek Konsistensi", re.I))
        await kons.wait_for(state="visible", timeout=800)
        ign = page.get_by_role("button", name=re.compile("^Ignore$", re.I))
        if await ign.is_visible():
            await ign.click(force=True)
            await page.wait_for_timeout(250)
    except Exception:
        pass

    clicked_confirm = False
    for _ in range(10):
        ya = page.locator("div.modal.show, div[role='dialog']").locator(
            "button:has-text('Ya, Submit'), a:has-text('Ya, Submit'), button:has-text('Ya, Submit!'), a:has-text('Ya, Submit!')"
        ).first
        if await ya.count() > 0 and await ya.is_visible():
            async def _click_confirm():
                try:
                    await ya.click(force=True)
                except Exception:
                    await page.evaluate(
                        """
                        () => {
                            const modal = document.querySelector('.modal.show,[role="dialog"]');
                            if (!modal) return;
                            const yes = modal.querySelector('button, a');
                            if (yes) yes.click();
                        }
                        """
                    )

            try:
                await with_retry(_click_confirm, attempts=3, delay_ms=120, backoff=1.3)
                clicked_confirm = True
                await page.wait_for_timeout(400)
                break
            except Exception:
                pass
        await page.wait_for_timeout(200)

    success_seen = False
    for _ in range(20):
        try:
            okb = page.get_by_role("button", name=re.compile("^OK$", re.I))
            if await okb.is_visible():
                try:
                    await with_retry(lambda: okb.click(force=True), attempts=2, delay_ms=100, backoff=1.2)
                    await page.wait_for_timeout(150)
                    success_seen = True
                    break
                except Exception:
                    pass
        except Exception:
            pass

        toast = page.locator(".toast, .alert-success, .swal2-popup").first
        try:
            if await toast.is_visible(timeout=120):
                success_seen = True
                break
        except Exception:
            pass

        if not await submit_still_visible(page):
            success_seen = True
            break

        await page.wait_for_timeout(200)

    if success_seen:
        return SubmitResult("OK", "Submit final sukses")
    if clicked_confirm:
        hints = await collect_error_hints(page)
        detail = "CODE:SUBMIT_NO_SUCCESS_SIGNAL Tidak ada sinyal sukses setelah konfirmasi submit."
        if hints:
            detail += f" | Petunjuk: {', '.join(hints)}"
        return SubmitResult("NO_SUCCESS_SIGNAL", detail)
    return SubmitResult("NO_CONFIRM", "CODE:SUBMIT_NO_CONFIRM Dialog konfirmasi Submit Final tidak muncul.")


async def submit_still_visible(page: Page) -> bool:
    btn_role = page.get_by_role("button", name=re.compile("Submit Final", re.I))
    btn_text = page.locator("text=Submit Final").first
    try:
        return await btn_role.is_visible(timeout=120) or await btn_text.is_visible(timeout=120)
    except Exception:
        return True
