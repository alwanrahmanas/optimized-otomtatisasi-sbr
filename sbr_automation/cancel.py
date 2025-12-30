from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError, Page

from .config import CancelOptions, RuntimeConfig
from .excel_loader import ensure_required_columns, load_dataframe, slice_rows
from .logbook import LogBook, LogEvent, update_run_index
from .playwright_helpers import attach_browser, ensure_cdp_ready, pick_active_page
from .table_actions import click_edit_by_index, click_edit_by_text
from .utils import (
    ScreenshotResult,
    clear_attention_flag,
    describe_exception,
    note_with_reason,
    norm_space,
    take_screenshot,
    timestamp,
)


BASE_REQUIRED_COLUMNS_CANCEL = ()
MATCH_BY_REQUIRED_COLUMNS_CANCEL = {
    "idsbr": ("IDSBR",),
    "name": ("Nama",),
}

_ROW_DIVIDER = "=" * 72
_ROW_SUBDIVIDER = "-" * 72


@dataclass(slots=True)
class CancelRowContext:
    table_index: int
    display_index: int
    idsbr: str
    nama: str


async def _log_screenshot(page: Page, label: str, config: RuntimeConfig) -> ScreenshotResult:
    return await take_screenshot(page, config.cancel_screenshot_dir, label)


def _format_match_value(ctx: CancelRowContext, match_by: str) -> str:
    if match_by == "index":
        return "" if ctx.table_index is None else str(ctx.table_index)
    if match_by == "idsbr":
        return ctx.idsbr or ""
    if match_by == "name":
        return ctx.nama or ""
    return ""


def _print_row_header(ctx: CancelRowContext, match_by: str, match_value: str) -> None:
    title = ctx.idsbr or ctx.nama or "(tanpa nama)"
    print(f"\n{_ROW_DIVIDER}")
    print(f"Baris {ctx.display_index}: {title}")
    print(f"Target : {match_value or '-'} (match_by={match_by})")
    print(_ROW_SUBDIVIDER)


def _print_run_summary(ok_rows: int, error_rows: int, logbook: LogBook, config: RuntimeConfig) -> None:
    print(f"\n{_ROW_DIVIDER}")
    print("Selesai Cancel Submit.")
    print(f"  - Baris sukses    : {ok_rows}")
    print(f"  - Baris bermasalah: {error_rows}")
    print(f"  - Log CSV         : {logbook.path}")
    if logbook.report_path:
        print(f"  - Laporan HTML    : {logbook.report_path}")
    if getattr(config, "run_id", ""):
        print(f"  - Run ID          : {config.run_id}")
    print(_ROW_SUBDIVIDER)


async def _do_cancel(new_page: Page, config: RuntimeConfig) -> str:
    print("    [Form] Membuka tab form...")

    try:
        btn = new_page.locator("xpath=//*[@id='cancel-submit-final']/span")
        if await btn.count() == 0:
            btn = new_page.locator("button:has-text('Cancel Submit'), a:has-text('Cancel Submit')").first
        await btn.wait_for(state="visible", timeout=config.max_wait_ms)
        await btn.scroll_into_view_if_needed(timeout=config.max_wait_ms)
        await btn.click()
        print("    [Klik] Cancel Submit")
    except Exception as exc:  # noqa: BLE001
        detail = f"ERROR: Gagal klik Cancel Submit ({describe_exception(exc)})"
        print(f"    [Gagal] {detail}")
        return detail

    try:
        modal = new_page.locator("div.modal.show, div[role='dialog']")
        with_text = modal.filter(has_text=re.compile("Konfirmasi", re.I)).first
        target = with_text if await with_text.count() > 0 else modal.first
        await target.wait_for(timeout=4000)
        ya_btn = target.locator("button:has-text('Ya, batalkan!'), a:has-text('Ya, batalkan!')").first
        await ya_btn.click(force=True)
        print("    [Konfirmasi] Ya, batalkan!")
    except Exception as exc:  # noqa: BLE001
        detail = f"ERROR: Gagal klik 'Ya, batalkan!' ({describe_exception(exc)})"
        print(f"    [Gagal] {detail}")
        return detail

    try:
        for _ in range(20):
            ok_btn = new_page.locator("button:has-text('OK')").first
            if await ok_btn.count() > 0 and await ok_btn.is_visible():
                await ok_btn.click(force=True)
                print("    [Sukses] OK ditekan")
                return "OK"
            await new_page.wait_for_timeout(250)
        print("    [Info] Tidak menemukan dialog Success; diasumsikan OK")
        return "OK"
    except Exception as exc:  # noqa: BLE001
        detail = f"ERROR: Gagal menutup dialog success ({describe_exception(exc)})"
        print(f"    [Gagal] {detail}")
        return detail


async def process_cancel(options: CancelOptions, config: RuntimeConfig) -> None:
    clear_attention_flag(getattr(config, "attention_flag", None))
    df = load_dataframe(options.excel)
    required_columns = tuple(BASE_REQUIRED_COLUMNS_CANCEL) + MATCH_BY_REQUIRED_COLUMNS_CANCEL.get(
        options.match_by, ()
    )
    try:
        ensure_required_columns(df, required_columns)
    except RuntimeError as exc:
        missing_match = [
            col for col in MATCH_BY_REQUIRED_COLUMNS_CANCEL.get(options.match_by, ()) if col not in df.columns
        ]
        if missing_match:
            raise RuntimeError(
                f"Kolom Excel untuk '--match-by {options.match_by}' wajib ada: {', '.join(missing_match)}."
            ) from exc
        raise

    start_idx, end_idx = slice_rows(df, options.start_row, options.end_row)
    log_filename = f"log_sbr_cancel_{config.run_id}.csv" if config.run_id else "log_sbr_cancel.csv"
    log_path = config.log_dir / log_filename
    logbook = LogBook(
        log_path,
        report_path=config.log_dir / log_filename.replace(".csv", ".html"),
        attention_flag=getattr(config, "attention_flag", None),
    )

    print("Memeriksa koneksi Chrome (CDP)...")
    try:
        ensure_cdp_ready(config)
    except RuntimeError as exc:
        print(f"Gagal memverifikasi Chrome CDP: {exc}")
        raise
    else:
        print("Chrome CDP siap digunakan.")

    ok_rows = 0
    error_rows = 0

    async with attach_browser(config) as (_, context):
        page = pick_active_page(context)

        for i in range(start_idx, end_idx):
            row = df.iloc[i]
            ctx = CancelRowContext(
                table_index=i,
                display_index=i + 1,
                idsbr=norm_space(row.get("IDSBR")),
                nama=norm_space(row.get("Nama")),
            )

            match_value = _format_match_value(ctx, options.match_by)
            _print_row_header(ctx, options.match_by, match_value)
            clicked = False
            try:
                if options.match_by == "index":
                    clicked = await click_edit_by_index(page, ctx.table_index, timeout=config.max_wait_ms)
                elif options.match_by == "idsbr":
                    clicked = await click_edit_by_text(page, match_value, timeout=config.max_wait_ms)
                elif options.match_by == "name":
                    clicked = await click_edit_by_text(page, match_value, timeout=config.max_wait_ms)
            except Exception as exc:  # noqa: BLE001
                shot = await _log_screenshot(page, f"exception_click_edit_{ctx.display_index}", config)
                note = note_with_reason(
                    f"Exception klik Edit (target {options.match_by}={match_value or '-'}) : {describe_exception(exc)}",
                    shot,
                )
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="ERROR",
                        stage="CLICK_EDIT",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                error_rows += 1
                if options.stop_on_error:
                    break
                continue

            if not clicked:
                shot = await _log_screenshot(page, f"gagal_click_edit_{ctx.display_index}", config)
                note = note_with_reason(
                    f"Tombol Edit tidak ditemukan (target {options.match_by}={match_value or '-'})", shot
                )
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="ERROR",
                        stage="CLICK_EDIT",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                error_rows += 1
                if options.stop_on_error:
                    break
                continue

            try:
                ya_edit = page.get_by_role("button", name="Ya, edit!")
                if await ya_edit.count() > 0:
                    await ya_edit.click()
            except PlaywrightError:
                pass

            await page.wait_for_timeout(config.pause_after_edit_ms)

            try:
                new_page = await context.wait_for_event("page", timeout=config.max_wait_ms)
            except PlaywrightError as exc:
                shot = await _log_screenshot(page, f"no_new_tab_{ctx.display_index}", config)
                note = note_with_reason(f"Tidak ada tab form: {describe_exception(exc)}", shot)
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="ERROR",
                        stage="OPEN_TAB",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                error_rows += 1
                if options.stop_on_error:
                    break
                continue

            await new_page.bring_to_front()
            raw_result = await _do_cancel(new_page, config)
            result_note = raw_result
            shot_path = ""
            if raw_result != "OK":
                shot = await _log_screenshot(new_page, f"cancel_issue_{ctx.display_index}", config)
                result_note = note_with_reason(raw_result, shot)
                shot_path = shot.path or ""

            try:
                await new_page.close()
            except PlaywrightError:
                pass

            await page.bring_to_front()

            logbook.append(
                LogEvent(
                    ts=timestamp(),
                    row_index=ctx.display_index,
                    level="OK" if raw_result == "OK" else "ERROR",
                    stage="CANCEL",
                    idsbr=ctx.idsbr,
                    nama=ctx.nama,
                    match_value=match_value,
                    note=result_note,
                    screenshot=shot_path,
                )
            )
            if raw_result == "OK":
                ok_rows += 1
            else:
                error_rows += 1
                if options.stop_on_error:
                    break

    logbook.save()
    update_run_index(
        logbook.path.parent.parent / "index.csv",
        {
            "run_id": config.run_id,
            "started_at": config.run_started_at,
            "command": "cancel",
            "resume": "False",
            "dry_run": "False",
            "skip_status": str(config.skip_status),
            "ok_rows": str(ok_rows),
            "error_rows": str(error_rows),
            "skipped_rows": "0",
            "log_csv": str(logbook.path),
            "log_html": str(logbook.report_path or ""),
            "profile": config.profile_path or "",
        },
    )
    _print_run_summary(ok_rows, error_rows, logbook, config)

    issues = logbook.recent_issues()
    if issues:
        print("\nCatatan penting:")
        for issue in issues:
            note = issue.note.strip()
            if len(note) > 140:
                note = f"{note[:137]}..."
            print(f" - Baris {issue.row_index} [{issue.level}/{issue.stage}]: {note}")
