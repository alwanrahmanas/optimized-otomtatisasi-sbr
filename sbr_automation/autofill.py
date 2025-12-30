from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from playwright.async_api import Error as PlaywrightError, Page

from .config import AutofillOptions, RuntimeConfig
from .form_filler import fill_form
from .loader import MATCH_BY_REQUIRED_COLUMNS, load_rows
from .logbook import LogBook, LogEvent, update_run_index
from .models import RowContext
from .navigator import open_form_page
from .playwright_helpers import attach_browser, ensure_cdp_ready, pick_active_page
from .resume import load_resume_entries, resolve_resume_log_path
from .submitter import is_finalized_form, is_locked_page, submit_form
from .table_actions import click_edit_by_index, click_edit_by_text
from .utils import (
    ScreenshotResult,
    clear_attention_flag,
    describe_exception,
    note_with_reason,
    take_screenshot,
    timestamp,
)


_ROW_DIVIDER = "=" * 72
_ROW_SUBDIVIDER = "-" * 72


@dataclass
class AutofillStats:
    """Statistics from an autofill run."""
    success_count: int = 0
    error_count: int = 0
    skip_count: int = 0
    recent_errors: list[str] = field(default_factory=list)



def _format_match_value(ctx: RowContext, match_by: str) -> str:
    if match_by == "index":
        return "" if ctx.table_index is None else str(ctx.table_index)
    if match_by == "idsbr":
        return ctx.idsbr or ""
    if match_by == "name":
        return ctx.nama or ""
    return ""


def _print_row_header(ctx: RowContext, match_by: str, match_value: str) -> None:
    name = ctx.nama or "(tanpa nama)"
    status_label = ctx.status or "-"
    target = match_value or "-"
    print(f"\n{_ROW_DIVIDER}")
    print(f"Baris {ctx.display_index}: {name}")
    print(f"Status : {status_label}")
    print(f"Target : {target} (match_by={match_by})")
    print(_ROW_SUBDIVIDER)


def _print_resume_skip(ctx: RowContext, prev_level: str, prev_stage: str, note_detail: str) -> None:
    name = ctx.nama or "(tanpa nama)"
    print(f"\n{_ROW_DIVIDER}")
    print(f"Baris {ctx.display_index}: {name}")
    print("Status : Dilewati (mode resume)")
    extras = []
    if prev_level:
        extras.append(f"Status sebelumnya: {prev_level}")
    if prev_stage:
        extras.append(f"Stage: {prev_stage}")
    if note_detail:
        extras.append(f"Catatan: {note_detail}")
    if extras:
        print("Info   : " + " | ".join(extras))
    print(_ROW_SUBDIVIDER)


def _print_run_summary(
    ok_rows: int,
    error_rows: int,
    skipped_rows: int,
    logbook: LogBook,
    config: RuntimeConfig,
    *,
    dry_run: bool,
) -> None:
    heading = "Dry-run selesai." if dry_run else "Selesai."
    print(f"\n{_ROW_DIVIDER}")
    print(heading)
    print(f"  - Baris sukses    : {ok_rows}")
    print(f"  - Baris bermasalah: {error_rows}")
    print(f"  - Baris dilewati  : {skipped_rows}")
    print(f"  - Log CSV         : {logbook.path}")
    if logbook.report_path:
        print(f"  - Laporan HTML    : {logbook.report_path}")
    if getattr(config, "run_id", ""):
        print(f"  - Run ID          : {config.run_id}")
    print(_ROW_SUBDIVIDER)


async def _log_screenshot(
    page: Page,
    label: str,
    config: RuntimeConfig,
    *,
    for_cancel: bool = False,
) -> ScreenshotResult:
    directory = config.cancel_screenshot_dir if for_cancel else config.screenshot_dir
    return await take_screenshot(page, directory, label)


async def process_autofill(options: AutofillOptions, config: RuntimeConfig) -> AutofillStats:
    clear_attention_flag(getattr(config, "attention_flag", None))
    contexts, start_display, end_display = load_rows(options, config)

    resume_entries: Dict[int, dict] = {}
    log_filename = f"log_sbr_autofill_{config.run_id}.csv" if config.run_id else "log_sbr_autofill.csv"
    log_path = config.log_dir / log_filename
    resume_log_path = log_path
    if options.resume:
        resume_log_path = resolve_resume_log_path(log_path)
        if resume_log_path != log_path and resume_log_path.exists():
            print(f"Mode resume membaca log sebelumnya: {resume_log_path}")
        resume_entries = load_resume_entries(
            resume_log_path,
            start_display=start_display,
            end_display=end_display,
        )

    if options.dry_run:
        print("Mode dry-run aktif: tombol Edit hanya diverifikasi, form tidak dibuka.")

    report_filename = log_filename.replace(".csv", ".html")
    logbook = LogBook(
        log_path,
        report_path=config.log_dir / report_filename,
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
    skipped_rows = 0
    error_rows = 0
    recent_errors: list[str] = []  # Track recent errors for WhatsApp notification

    async with attach_browser(config) as (_, context):
        page = pick_active_page(context)

        for ctx in contexts:
            page_ids_before_click = {id(p) for p in context.pages}
            if options.resume and ctx.display_index in resume_entries:
                prev = resume_entries.pop(ctx.display_index)
                prev_level = prev.get("level", "OK")
                prev_stage = prev.get("stage", "")
                note_detail = prev.get("note", "")
                _print_resume_skip(ctx, prev_level, prev_stage, note_detail)
                extra = f"Status sebelumnya: {prev_level}"
                if prev_stage:
                    extra += f" | Stage: {prev_stage}"
                if note_detail:
                    extra += f" | Catatan: {note_detail}"
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="OK",
                        stage="RESUME_SKIP",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=ctx.idsbr or ctx.nama,
                        note=f"Dilewati (resume). {extra}",
                        screenshot="",
                    )
                )
                skipped_rows += 1
                continue

            match_value = _format_match_value(ctx, options.match_by)
            _print_row_header(ctx, options.match_by, match_value)
            clicked = False
            try:
                if options.match_by == "index":
                    clicked = await click_edit_by_index(
                        page,
                        ctx.table_index,
                        timeout=config.max_wait_ms,
                        perform_click=not options.dry_run,
                    )
                elif options.match_by == "idsbr":
                    clicked = await click_edit_by_text(
                        page,
                        match_value,
                        timeout=config.max_wait_ms,
                        perform_click=not options.dry_run,
                    )
                elif options.match_by == "name":
                    clicked = await click_edit_by_text(
                        page,
                        match_value,
                        timeout=config.max_wait_ms,
                        perform_click=not options.dry_run,
                    )
            except Exception as exc:  # noqa: BLE001
                shot = await _log_screenshot(page, f"exception_click_edit_{ctx.display_index}", config)
                note = note_with_reason(
                    f"CODE:CLICK_EDIT_EXCEPTION (target {options.match_by}={match_value or '-'}) : {describe_exception(exc)}",
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
                # Track error for notification
                error_msg = f"Baris {ctx.display_index}: CODE:CLICK_EDIT_EXCEPTION"
                recent_errors.append(error_msg)
                if options.stop_on_error:
                    break
                continue

            if not clicked:
                shot = await _log_screenshot(page, f"gagal_click_edit_{ctx.display_index}", config)
                note = note_with_reason(
                    f"CODE:CLICK_EDIT_TIMEOUT Tombol Edit tidak ditemukan atau tidak bisa diklik (target {options.match_by}={match_value or '-'})",
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
                # Track error for notification
                error_msg = f"Baris {ctx.display_index}: CODE:CLICK_EDIT_TIMEOUT"
                recent_errors.append(error_msg)
                if options.stop_on_error:
                    break
                continue

            if options.dry_run:
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="OK",
                        stage="DRY_RUN",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note="Tombol Edit ditemukan (dry-run, form tidak dibuka).",
                        screenshot="",
                    )
                )
                ok_rows += 1
                continue

            try:
                ya_edit = page.get_by_role("button", name=re.compile(r"Ya,\s*edit!?$", re.I))
                if await ya_edit.count() > 0:
                    await ya_edit.click()
            except PlaywrightError:
                pass

            new_page, open_note, open_error = await open_form_page(
                context,
                page,
                match_value=match_value,
                fallback_text=match_value or ctx.idsbr or ctx.nama,
                config=config,
            )

            # Tutup tab ekstra jika klik Edit sempat terpanggil lebih dari sekali
            try:
                extra_pages = [
                    p for p in context.pages if id(p) not in page_ids_before_click and p is not new_page
                ]
                for extra in extra_pages:
                    try:
                        await extra.close()
                        print("    [Info] Menutup tab ekstra hasil klik ganda.")
                    except PlaywrightError:
                        pass
            except Exception:
                pass

            if not new_page:
                shot = await _log_screenshot(page, f"no_new_tab_{ctx.display_index}", config)
                detail = open_error or "CODE:OPEN_TAB_NO_PAGE Tidak ada tab form."
                note = note_with_reason(detail, shot)
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
            if open_note:
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="OK",
                        stage="OPEN_TAB",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=open_note,
                        screenshot="",
                    )
                )

            try:
                if await is_finalized_form(new_page):
                    print("    [Lewati] Form sudah berstatus final (hanya ada Cancel Submit).")
                    logbook.append(
                        LogEvent(
                            ts=timestamp(),
                            row_index=ctx.display_index,
                            level="OK",
                            stage="FINAL_SKIP",
                            idsbr=ctx.idsbr,
                            nama=ctx.nama,
                            match_value=match_value,
                            note="CODE:FINAL_ALREADY_SUBMITTED Dilewati: form sudah final (tombol Cancel Submit terlihat).",
                            screenshot="",
                        )
                    )
                    try:
                        await new_page.close()
                    except PlaywrightError:
                        pass
                    await page.bring_to_front()
                    skipped_rows += 1
                    continue
            except Exception as exc:  # noqa: BLE001
                print(f"    [Cek] Gagal memeriksa status final: {describe_exception(exc)}")

            if await is_locked_page(new_page):
                shot = await _log_screenshot(new_page, f"locked_{ctx.display_index}", config)
                note = note_with_reason(
                    "CODE:FORM_LOCKED Usaha sedang diedit oleh pengguna lain. Tutup tab sebelum lanjut.", shot
                )
                print("    [Lewati] Lock terdeteksi: usaha sedang dibuka oleh pengguna lain.")
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="WARN",
                        stage="ACCESS",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                try:
                    await new_page.close()
                except PlaywrightError:
                    pass
                await page.bring_to_front()
                skipped_rows += 1
                continue

            try:
                fill_summary = await fill_form(new_page, ctx, config)
                updated = int(fill_summary.get("updated", 0))
                skipped = int(fill_summary.get("skipped", 0))
                errors = fill_summary.get("errors", [])
                note_fill = f"Form terisi (update={updated}, skip={skipped})"
                level = "OK"
                screenshot_path = ""
                if errors:
                    level = "ERROR"
                    note_fill += f" | Kendala: {', '.join(errors)}"
                    shot = await _log_screenshot(new_page, f"fill_errors_{ctx.display_index}", config)
                    screenshot_path = shot.path or ""
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level=level,
                        stage="FILL",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note_fill,
                        screenshot=screenshot_path,
                    )
                )
                if errors:
                    error_rows += 1
                    try:
                        await new_page.close()
                    except PlaywrightError:
                        pass
                    await page.bring_to_front()
                    if options.stop_on_error:
                        break
                    continue
            except Exception as exc:  # noqa: BLE001
                shot = await _log_screenshot(new_page, f"exception_fill_form_{ctx.display_index}", config)
                note = note_with_reason(f"Exception isi form: {describe_exception(exc)}", shot)
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="ERROR",
                        stage="FILL",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                error_rows += 1
                try:
                    await new_page.close()
                except PlaywrightError:
                    pass
                if options.stop_on_error:
                    break
                else:
                    await page.bring_to_front()
                    continue

            try:
                result = await submit_form(new_page, ctx, config)
                if result.code != "OK":
                    shot = await _log_screenshot(
                        new_page, f"submit_issue_{ctx.display_index}_{result.code}", config
                    )
                    detail_note = result.code
                    if result.detail:
                        detail_note = f"{result.code} | {result.detail}"
                    note = note_with_reason(detail_note, shot)
                    logbook.append(
                        LogEvent(
                            ts=timestamp(),
                            row_index=ctx.display_index,
                            level="ERROR",
                            stage="SUBMIT",
                            idsbr=ctx.idsbr,
                            nama=ctx.nama,
                            match_value=match_value,
                            note=note,
                            screenshot=shot.path or "",
                        )
                    )
                    error_rows += 1
                    try:
                        await new_page.close()
                    except PlaywrightError:
                        pass
                    await page.bring_to_front()
                    if options.stop_on_error:
                        break
                    continue
                else:
                    success_note = result.detail or "Submit final sukses"
                    logbook.append(
                        LogEvent(
                            ts=timestamp(),
                            row_index=ctx.display_index,
                            level="OK",
                            stage="SUBMIT",
                            idsbr=ctx.idsbr,
                            nama=ctx.nama,
                            match_value=match_value,
                            note=success_note,
                            screenshot="",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                shot = await _log_screenshot(new_page, f"exception_submit_{ctx.display_index}", config)
                note = note_with_reason(f"EXCEPTION: {describe_exception(exc)}", shot)
                logbook.append(
                    LogEvent(
                        ts=timestamp(),
                        row_index=ctx.display_index,
                        level="ERROR",
                        stage="SUBMIT",
                        idsbr=ctx.idsbr,
                        nama=ctx.nama,
                        match_value=match_value,
                        note=note,
                        screenshot=shot.path or "",
                    )
                )
                error_rows += 1
                if options.stop_on_error:
                    try:
                        await new_page.close()
                    except PlaywrightError:
                        pass
                    break
                else:
                    try:
                        await new_page.close()
                    except PlaywrightError:
                        pass
                    await page.bring_to_front()
                    continue

            try:
                await new_page.close()
            except PlaywrightError:
                pass

            await page.bring_to_front()
            await page.wait_for_timeout(800)
            logbook.append(
                LogEvent(
                    ts=timestamp(),
                    row_index=ctx.display_index,
                    level="OK",
                    stage="ROW_DONE",
                    idsbr=ctx.idsbr,
                    nama=ctx.nama,
                    match_value=match_value,
                    note="Baris selesai diproses",
                    screenshot="",
                )
            )
            ok_rows += 1

    logbook.save()
    index_path = logbook.path.parent.parent / "index.csv"
    update_run_index(
        index_path,
        {
            "run_id": config.run_id,
            "started_at": config.run_started_at,
            "command": "autofill",
            "resume": str(options.resume),
            "dry_run": str(options.dry_run),
            "skip_status": str(config.skip_status),
            "ok_rows": str(ok_rows),
            "error_rows": str(error_rows),
            "skipped_rows": str(skipped_rows),
            "log_csv": str(logbook.path),
            "log_html": str(logbook.report_path or ""),
            "profile": config.profile_path or "",
        },
    )
    _print_run_summary(
        ok_rows,
        error_rows,
        skipped_rows,
        logbook,
        config,
        dry_run=options.dry_run,
    )

    issues = logbook.recent_issues()
    if issues:
        print("\nCatatan penting:")
        for issue in issues:
            note = issue.note.strip()
            if len(note) > 140:
                note = f"{note[:137]}..."
            print(
                f" - Baris {issue.row_index} [{issue.level}/{issue.stage}]: {note}"
            )
    
    # Return statistics for WhatsApp notification
    return AutofillStats(
        success_count=ok_rows,
        error_count=error_rows,
        skip_count=skipped_rows,
        recent_errors=recent_errors[-5:],  # Keep last 5 errors
    )
