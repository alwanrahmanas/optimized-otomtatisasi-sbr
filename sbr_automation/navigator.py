from __future__ import annotations

from typing import Tuple

from playwright.async_api import BrowserContext, Error as PlaywrightError, Page

from .config import RuntimeConfig
from .utils import describe_exception


async def find_edit_href(page: Page, text: str) -> str:
    text = (text or "").strip().lower()
    return await page.evaluate(
        """
        (target) => {
            const table = document.querySelector('#table_direktori_usaha');
            if (!table) return '';
            const rows = Array.from(table.querySelectorAll('tbody tr'));
            for (const tr of rows) {
                const content = (tr.innerText || '').toLowerCase();
                if (target && !content.includes(target)) continue;
                const link = tr.querySelector('a.btn-edit-perusahaan');
                if (link && link.href) return link.href;
            }
            return '';
        }
        """,
        text,
    )


async def open_form_page(
    context: BrowserContext,
    page: Page,
    *,
    match_value: str,
    fallback_text: str,
    config: RuntimeConfig,
) -> Tuple[Page | None, str, str]:
    """Cari tab form setelah klik Edit; kembalikan (page, note, detail_error)."""
    existing_page_ids = {id(p) for p in context.pages}
    before_url = page.url
    try:
        before_title = await page.title()
    except Exception:
        before_title = ""

    await page.wait_for_timeout(config.pause_after_edit_ms)

    try:
        new_page = await context.wait_for_event("page", timeout=config.max_wait_ms)
        return new_page, "Tab form baru terdeteksi (event page).", ""
    except PlaywrightError as exc:
        exc_detail = describe_exception(exc)

    fallback_page = next((p for p in context.pages if id(p) not in existing_page_ids), None)
    after_url = page.url
    try:
        after_title = await page.title()
    except Exception:
        after_title = ""

    if fallback_page:
        return fallback_page, "Tab form baru terdeteksi (fallback inspeksi pages).", ""
    if after_url != before_url or (after_title and after_title != before_title):
        return page, "Form dibuka di tab yang sama (URL/title berubah).", ""

    href_detail = ""
    href = ""
    if fallback_text:
        try:
            href = await find_edit_href(page, fallback_text)
        except Exception as inner_exc:  # noqa: BLE001
            href_detail = describe_exception(inner_exc)

        if href:
            try:
                await page.evaluate(
                    """
                    (url) => {
                        const a = document.createElement('a');
                        a.href = url;
                        a.target = '_blank';
                        a.rel = 'noopener';
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                    }
                    """,
                    href,
                )
            except Exception as inner_exc:  # noqa: BLE001
                href_detail = describe_exception(inner_exc)
            else:
                try:
                    new_page = await context.wait_for_event("page", timeout=config.max_wait_ms)
                    return new_page, "Tab form baru terdeteksi (fallback buka href).", ""
                except PlaywrightError:
                    after_url = page.url
                    try:
                        after_title = await page.title()
                    except Exception:
                        after_title = ""
                    if after_url != before_url or (after_title and after_title != before_title):
                        return page, "Form dibuka di tab yang sama (fallback href).", ""

    detail = f"Tidak ada tab form: {exc_detail}"
    after_url_final = page.url
    if after_url_final == before_url:
        detail += " | URL tidak berubah"
    if href_detail:
        detail += f" | Fallback href: {href_detail}"
    return None, "", detail
