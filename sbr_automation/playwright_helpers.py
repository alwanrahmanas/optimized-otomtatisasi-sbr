from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional
from urllib.error import URLError
from urllib.request import urlopen

from playwright.async_api import (
    Browser,
    BrowserContext,
    Error as PlaywrightError,
    Locator,
    Page,
    async_playwright,
)

from .config import RuntimeConfig


async def slow_pause(page: Page, config: RuntimeConfig, ms: Optional[int] = None) -> None:
    if not config.slow_mode:
        return
    await page.wait_for_timeout(ms or config.step_delay_ms)


async def remove_overlays(page: Page) -> None:
    await page.evaluate(
        "() => document.querySelectorAll('.tooltip,.modal-backdrop,.swal2-container').forEach(el => el.remove())"
    )


async def ensure_click(
    locator: Locator,
    *,
    name: str,
    timeout: int,
    attempts: int = 3,
) -> bool:
    for _ in range(attempts):
        try:
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.scroll_into_view_if_needed(timeout=timeout)
            await locator.click()
            return True
        except Exception:  # noqa: BLE001
            page = locator.page
            try:
                await remove_overlays(page)
            except Exception:
                pass
            await asyncio.sleep(0.15)
    return False


def ensure_cdp_ready(config: RuntimeConfig) -> None:
    endpoint = config.cdp_endpoint.rstrip("/")
    test_url = f"{endpoint}/json/version"
    timeout_seconds = max(config.max_wait_ms, 2000) / 1000

    try:
        with urlopen(test_url, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise RuntimeError(
                    f"Chrome CDP merespons status {status} untuk {test_url}. "
                    "Periksa apakah remote debugging telah diaktifkan."
                )
            payload = response.read()
    except URLError as exc:
        raise RuntimeError(
            f"Gagal menghubungi Chrome CDP di {test_url}. "
            "Pastikan Chrome dijalankan dengan remote debugging, misalnya:\n"
            r'  & "C:\Program Files\Google\Chrome\Application\chrome.exe" '
            r'--remote-debugging-port=9222 --user-data-dir="C:\ChromeProfileSBR"'
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Gagal memverifikasi Chrome CDP: {exc}") from exc

    if b"webSocketDebuggerUrl" not in payload:
        raise RuntimeError(
            f"Endpoint {test_url} merespons, tetapi tidak ditemukan `webSocketDebuggerUrl`. "
            "Pastikan versi Chrome mendukung CDP dan remote debugging aktif."
        )


def _pick_context(browser: Browser) -> BrowserContext:
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError(
            "Tidak menemukan context aktif di Chrome. "
            "Pastikan sudah membuka halaman Direktori Usaha pada profil Chrome yang sama."
        )
    return contexts[-1]


@asynccontextmanager
async def attach_browser(config: RuntimeConfig) -> AsyncIterator[tuple[Browser, BrowserContext]]:
    async with async_playwright() as p:
        try:
            browser = await p.chromium.connect_over_cdp(config.cdp_endpoint)
        except PlaywrightError as exc:  # noqa: BLE001
            raise RuntimeError(
                "Gagal terhubung ke Chrome melalui CDP. Pastikan Chrome dijalankan dengan "
                "`--remote-debugging-port=9222` dan port sesuai pengaturan."
            ) from exc

        context = _pick_context(browser)
        try:
            yield browser, context
        finally:
            if config.close_browser_on_exit:
                try:
                    await browser.close()
                except PlaywrightError:
                    pass


def pick_active_page(context: BrowserContext) -> Page:
    pages = context.pages
    if not pages:
        raise RuntimeError(
            "Tidak ada tab terbuka pada context saat ini. "
            "Buka terlebih dahulu tab Direktori Usaha sebelum menjalankan skrip."
        )
    return pages[-1]
