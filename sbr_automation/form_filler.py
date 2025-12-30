from __future__ import annotations

import re
from typing import Dict

from playwright.async_api import Page

from .config import RuntimeConfig
from .excel_loader import PROFILE_FIELD_KEYS
from .models import RowContext
from .playwright_helpers import slow_pause
from .utils import describe_exception, nonempty, norm_space, with_retry


def _form_log(message: str) -> None:
    print(f"    [Form] {message}")


async def update_field(
    page: Page,
    selector: str,
    value: object,
    field_name: str,
    logger=None,
    *,
    timeout: int = 4000,
) -> tuple[bool, str]:
    """Isi field hanya jika Excel memiliki nilai."""
    if not nonempty(value):
        msg = f"Skip {field_name} (Excel kosong)"
        if logger:
            logger.info(msg)
        else:
            _form_log(f"{msg}.")
        return False, "skip"

    try:
        target = page.locator(selector).first
        await target.wait_for(state="visible", timeout=timeout)
        await target.scroll_into_view_if_needed()
        tag_name = ""
        try:
            tag_name = (await target.evaluate("(el) => (el.tagName || '').toLowerCase()")) or ""
        except Exception:
            tag_name = ""

        if tag_name == "select":
            await target.select_option(str(value))
        else:
            await target.fill(str(value))
        msg = f"Update {field_name}: {value}"
        if logger:
            logger.info(msg)
        else:
            _form_log(msg)
        return True, "updated"
    except Exception as exc:  # noqa: BLE001
        msg = f"Gagal update {field_name}: {describe_exception(exc)}"
        if logger and hasattr(logger, "warning"):
            logger.warning(msg)
        else:
            _form_log(msg)
        return False, "error"


async def update_select2_field(
    page: Page,
    select_selector: str,
    value: object,
    field_name: str,
    *,
    timeout: int = 5000,
) -> tuple[bool, str]:
    """Isi select2 (single) dengan cara klik selection, ketik nilai, Enter."""
    if not nonempty(value):
        _form_log(f"Skip {field_name} (Excel kosong).")
        return False, "skip"

    try:
        select_loc = page.locator(select_selector).first
        await select_loc.wait_for(state="attached", timeout=timeout)

        # Coba select_option langsung jika select bukan select2 tersembunyi
        cls = (await select_loc.get_attribute("class")) or ""
        val_text = str(value)
        if "select2-hidden-accessible" not in cls:
            try:
                await select_loc.wait_for(state="visible", timeout=timeout)
                await select_loc.select_option(val_text)
                _form_log(f"Update {field_name} (select): {val_text}")
                return True, "updated"
            except Exception:
                pass

        selection = select_loc.locator(
            "xpath=following-sibling::span[contains(@class,'select2')][1]//span[contains(@class,'select2-selection')]"
        ).first
        await selection.wait_for(state="visible", timeout=timeout)

        async def _do_select2():
            await selection.click()
            search = page.locator("input.select2-search__field").first
            await search.wait_for(state="visible", timeout=timeout)
            await search.fill("")
            await search.type(val_text)
            await page.keyboard.press("Enter")

        await with_retry(_do_select2, attempts=3, delay_ms=120, backoff=1.4)
        _form_log(f"Update {field_name} (select2): {val_text}")
        return True, "updated"
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Gagal update {field_name} (select2): {describe_exception(exc)}")
        return False, "error"


async def _apply_status(page: Page, ctx: RowContext, config: RuntimeConfig) -> None:
    if not ctx.status:
        return

    radio_id = config.status_id_map.get(ctx.status)
    if radio_id:
        radio = page.locator(f"#{radio_id}")
        try:
            await radio.wait_for(state="attached", timeout=4000)
            try:
                await radio.check()
            except Exception:
                await radio.click(force=True)
            _form_log(f"Status usaha diatur ke: {ctx.status}")
        except Exception as exc:  # noqa: BLE001
            _form_log(f"Gagal set status '{ctx.status}': {describe_exception(exc)}")
    else:
        lbl = page.locator("label").filter(has_text=re.compile(re.escape(ctx.status), re.I)).first
        try:
            await lbl.wait_for(state="visible", timeout=4000)
            target_id = await lbl.get_attribute("for")
            if target_id:
                await page.locator(f"#{target_id}").check()
            else:
                await lbl.click(force=True)
            _form_log(f"Status usaha diisi melalui label fallback: {ctx.status}")
        except Exception as exc:  # noqa: BLE001
            _form_log(f"Gagal menemukan label status '{ctx.status}': {describe_exception(exc)}")

    await slow_pause(page, config)


async def _focus_identitas_section(page: Page) -> None:
    try:
        ident_section = page.locator(
            "xpath=//*[self::h4 or self::h5][contains(., 'IDENTITAS USAHA/PERUSAHAAN')]"
            "/ancestor::*[contains(@class,'card') or contains(@class,'section')][1]"
        )
        if await ident_section.count() > 0:
            await ident_section.scroll_into_view_if_needed()
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Gagal memfokus bagian Identitas: {describe_exception(exc)}")


async def _fill_phone(page: Page, phone: str) -> None:
    try:
        tel_input = (
            page.get_by_placeholder(re.compile(r"^Nomor\s*Telepon$", re.I))
            .or_(page.locator("input#nomor_telepon, input[name='nomor_telepon'], input[name='no_telp'], input[name='telepon']"))
        ).first
        await tel_input.wait_for(state="visible", timeout=3000)
        if nonempty(phone):
            await tel_input.fill("")
            await tel_input.fill(phone)
            _form_log(f"Nomor telepon diisi: {phone}")
        else:
            _form_log("Nomor telepon dilewati (Excel kosong).")
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Pengisian nomor telepon bermasalah: {describe_exception(exc)}")


async def _fill_whatsapp(page: Page, whatsapp: str) -> None:
    def _normalize_wa(raw: str) -> tuple[str, str]:
        """Return (+62-prefixed, subscriber-only)."""
        digits = re.findall(r"\d", raw or "")
        if not digits:
            return "", ""
        if digits[:2] == ["6", "2"]:
            digits = digits[2:]
        elif digits[:1] == ["0"]:
            digits = digits[1:]
        subscriber = "".join(digits)
        formatted = f"+62-{subscriber}" if subscriber else ""
        return formatted, subscriber

    try:
        wa_input = (
            page.get_by_placeholder(re.compile(r"Whatsapp", re.I))
            .or_(page.locator("input#whatsapp, input[name='whatsapp'], input[name='nomor_whatsapp'], input[name='no_whatsapp']"))
        ).first
        await wa_input.wait_for(state="visible", timeout=3000)
        if nonempty(whatsapp):
            formatted, subscriber = _normalize_wa(whatsapp)
            if not formatted:
                _form_log("Nomor WhatsApp kosong setelah normalisasi; dilewati.")
                return
            try:
                existing = (await wa_input.input_value()) or ""
            except Exception:
                existing = ""
            fill_value = formatted
            # Jika input sudah menyediakan prefix +62- tetap, isi hanya nomor sisanya.
            if existing.strip().startswith("+62-"):
                fill_value = subscriber
            await wa_input.fill("")
            await wa_input.fill(fill_value)
            _form_log(f"Nomor WhatsApp diisi: {formatted}")
        else:
            _form_log("Nomor WhatsApp dilewati (Excel kosong).")
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Pengisian nomor WhatsApp bermasalah: {describe_exception(exc)}")


async def _fill_website(page: Page, website: str) -> None:
    try:
        web_input = (
            page.get_by_placeholder(re.compile(r"Website", re.I))
            .or_(page.locator("input#website, input[name='website']"))
        ).first
        await web_input.wait_for(state="visible", timeout=3000)
        if nonempty(website):
            await web_input.fill("")
            await web_input.fill(website)
            _form_log(f"Website diisi: {website}")
        else:
            _form_log("Website dilewati (Excel kosong).")
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Pengisian website bermasalah: {describe_exception(exc)}")


async def _fill_email(page: Page, ctx: RowContext) -> None:
    try:
        cb_email = page.locator("#check-email").first
        cb_exists = await cb_email.count() > 0
        if cb_exists:
            await cb_email.wait_for(state="attached", timeout=500)

        email_input = (
            page.locator("input#email, input[name='email'], input[type='email']")
            .or_(page.get_by_placeholder(re.compile(r"^email$", re.I)))
        ).first

        web_state = await page.evaluate(
            """
            () => {
                const inp = document.querySelector('input#email, input[name="email"], input[type="email"]');
                return inp ? (inp.value || '').trim() : '';
            }
            """
        )
        web_value = web_state.strip()

        if nonempty(ctx.email):
            try:
                if cb_exists:
                    try:
                        if not await cb_email.is_checked():
                            await cb_email.check()
                    except Exception:
                        await cb_email.click(force=True)
                await email_input.wait_for(state="visible", timeout=400)
                await email_input.fill("")
                await email_input.fill(ctx.email)
                _form_log(f"Email diisi: {ctx.email}")
            except Exception as exc:  # noqa: BLE001
                _form_log(f"Gagal mengisi email: {describe_exception(exc)}")
        else:
            if web_value:
                _form_log(f"Email sudah ada di web, dibiarkan: {web_value}")
            else:
                if cb_exists:
                    try:
                        if await cb_email.is_checked():
                            await cb_email.uncheck()
                            _form_log("Email kosong, checkbox email dimatikan.")
                        else:
                            _form_log("Email kosong, checkbox email sudah dimatikan.")
                    except Exception:
                        try:
                            await cb_email.click(force=True)
                            _form_log("Email kosong, checkbox email dicoba dimatikan via klik.")
                        except Exception as exc:  # noqa: BLE001
                            _form_log(f"Gagal mematikan checkbox email: {describe_exception(exc)}")
                else:
                    _form_log("Email dilewati (Excel kosong).")
    except Exception as exc:  # noqa: BLE001
        _form_log(f"Pengelolaan email bermasalah: {describe_exception(exc)}")


async def _fill_coordinates(page: Page, ctx: RowContext) -> None:
    if ctx.latitude:
        try:
            lat_input = (
                page.locator("input#latitude, input[name='latitude']")
                .or_(page.get_by_placeholder(re.compile(r"^latitude", re.I)))
            ).first
            await lat_input.wait_for(state="visible", timeout=1500)
            await lat_input.fill("")
            await lat_input.fill(ctx.latitude)
            _form_log(f"Latitude diisi: {ctx.latitude}")
        except Exception as exc:  # noqa: BLE001
            _form_log(f"Gagal mengisi latitude: {describe_exception(exc)}")
    else:
        _form_log("Latitude dilewati.")

    if ctx.longitude:
        try:
            lon_input = (
                page.locator("input#longitude, input[name='longitude']")
                .or_(page.get_by_placeholder(re.compile(r"^longitude", re.I)))
            ).first
            await lon_input.wait_for(state="visible", timeout=1500)
            await lon_input.fill("")
            await lon_input.fill(ctx.longitude)
            _form_log(f"Longitude diisi: {ctx.longitude}")
        except Exception as exc:  # noqa: BLE001
            _form_log(f"Gagal mengisi longitude: {describe_exception(exc)}")
    else:
        _form_log("Longitude dilewati.")


async def _fill_identitas_section(page: Page, ctx: RowContext) -> None:
    await _focus_identitas_section(page)
    await _fill_phone(page, ctx.phone)
    await _fill_whatsapp(page, ctx.whatsapp)
    await _fill_website(page, ctx.website)
    await _fill_email(page, ctx)
    await _fill_coordinates(page, ctx)


async def _fill_additional_fields(page: Page, ctx: RowContext, config: RuntimeConfig) -> dict[str, object]:
    updated = 0
    errors: list[str] = []

    if nonempty(ctx.sumber):
        try:
            await page.get_by_placeholder(re.compile("Sumber Profiling", re.I)).fill(ctx.sumber)
            _form_log(f"Sumber Profiling diisi: {ctx.sumber}")
            updated += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"sumber_profiling: {describe_exception(exc)}")
            _form_log(f"Field Sumber Profiling tidak ditemukan: {describe_exception(exc)}")
        await slow_pause(page, config)
    else:
        _form_log("Sumber Profiling dilewati (Excel kosong).")

    if nonempty(ctx.catatan):
        try:
            await page.wait_for_selector("#catatan_profiling", state="visible", timeout=3000)
            await page.fill("#catatan_profiling", ctx.catatan)
            await page.evaluate(
                """
                () => {
                    const el = document.querySelector('#catatan_profiling');
                    if (el) {
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
                """
            )
            _form_log(f"Catatan diisi ({len(ctx.catatan)} karakter).")
            updated += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"catatan_profiling: {describe_exception(exc)}")
            _form_log(f"Gagal mengisi catatan: {describe_exception(exc)}")
        await slow_pause(page, config)
    else:
        _form_log("Catatan Profiling dilewati (Excel kosong).")

    return {"updated": updated, "errors": errors}


async def collect_error_hints(page: Page) -> list[str]:
    selectors = [
        ".swal2-popup .swal2-html-container, .swal2-popup .swal2-title",
        "div.modal.show .modal-body, div[role='dialog'].show .modal-body",
        ".alert-danger, .alert-warning, .alert-error, .text-danger, .invalid-feedback, .help-block",
        ".toast, .toast-body, .toast-message",
    ]
    hints: list[str] = []
    for selector in selectors:
        try:
            texts = await page.locator(selector).all_text_contents()
        except Exception:
            continue
        for text in texts:
            cleaned = norm_space(text)
            if cleaned and cleaned not in hints:
                hints.append(cleaned)
    return hints[:5]


async def _check_and_accept_idsbr_master(page: Page, config: RuntimeConfig) -> tuple[bool, str]:
    try:
        btn = (
            page.locator("#button-check-idsbr, button#button-check-idsbr")
            .or_(page.get_by_role("button", name=re.compile("^check$", re.I)))
        ).first
        await btn.wait_for(state="visible", timeout=4000)
        await btn.click(force=True)
        print("    [IDSBR] Tombol Check ditekan.")
    except Exception as exc:  # noqa: BLE001
        return False, f"Cek IDSBR gagal diklik: {describe_exception(exc)}"

    await slow_pause(page, config)

    modal = page.locator(
        "div.modal.show, div[role='dialog'].show, .modal.show, #container-check-idsbr-modal"
    ).first
    try:
        await modal.wait_for(state="visible", timeout=max(config.max_wait_ms, 3500))
    except Exception as exc:  # noqa: BLE001
        try:
            await page.wait_for_selector("#accept-idsbr", timeout=1800)
        except Exception:
            pass
        hints = await collect_error_hints(page)
        detail = f"Modal konfirmasi IDSBR tidak muncul: {describe_exception(exc)}"
        if hints:
            detail += f" | Petunjuk: {', '.join(hints)}"
        return False, detail

    try:
        accept_btn = modal.locator("#accept-idsbr, button#accept-idsbr, [data-bs-dismiss][id*='accept']").first
        await accept_btn.wait_for(state="visible", timeout=4000)
        await accept_btn.scroll_into_view_if_needed(timeout=1500)
        await accept_btn.click(force=True)
        print("    [IDSBR] Konfirmasi Accept ditekan.")
    except Exception as exc:  # noqa: BLE001
        hints = await collect_error_hints(page)
        detail = f"Gagal klik Accept pada konfirmasi IDSBR: {describe_exception(exc)}"
        if hints:
            detail += f" | Petunjuk: {', '.join(hints)}"
        return False, detail

    try:
        await modal.wait_for(state="hidden", timeout=4000)
    except Exception:
        pass

    await slow_pause(page, config)
    return True, ""


async def _handle_idsbr_master(page: Page, ctx: RowContext, config: RuntimeConfig) -> dict[str, object]:
    updated = 0
    skipped = 0
    errors: list[str] = []

    idsbr_master = norm_space(ctx.profiling_payload.get("idsbr_master"))
    status_duplikat = (ctx.status or "").lower() == "duplikat"

    if not idsbr_master:
        message = "IDSBR Master kosong; cek Duplikat dilewati."
        if status_duplikat:
            message = "Status Duplikat tetapi kolom idsbr_master kosong; wajib diisi sebelum submit."
            errors.append(message)
        else:
            skipped += 1
        _form_log(f"[IDSBR] {message}")
        return {"updated": updated, "skipped": skipped, "errors": errors}

    selector = config.profile_field_selectors.get("idsbr_master")
    if not selector:
        errors.append("idsbr_master: selector tidak dikonfigurasi.")
        _form_log("[IDSBR] Selector idsbr_master tidak ditemukan di konfigurasi.")
        return {"updated": updated, "skipped": skipped, "errors": errors}

    success, state = await update_field(page, selector, idsbr_master, "idsbr_master", None)
    if state == "skip":
        skipped += 1
        return {"updated": updated, "skipped": skipped, "errors": errors}
    if success:
        updated += 1
    else:
        errors.append("idsbr_master: gagal mengisi field.")
        return {"updated": updated, "skipped": skipped, "errors": errors}

    await slow_pause(page, config)

    if not status_duplikat:
        _form_log("[IDSBR] Status bukan Duplikat; konfirmasi IDSBR Master dilewati.")
        return {"updated": updated, "skipped": skipped, "errors": errors}

    ok, detail = await _check_and_accept_idsbr_master(page, config)
    if ok:
        updated += 1
    else:
        errors.append(detail)

    return {"updated": updated, "skipped": skipped, "errors": errors}


async def _fill_profile_payload_fields(page: Page, ctx: RowContext, config: RuntimeConfig) -> dict[str, object]:
    """Isi kolom-kolom baru Profiling berdasarkan payload Excel."""
    updated = 0
    skipped = 0
    errors: list[str] = []
    profile_selectors: Dict[str, str] = config.profile_field_selectors
    select2_selectors: Dict[str, str] = config.select2_field_selectors

    for key in PROFILE_FIELD_KEYS:
        if key in {"nomor_telepon", "nomor_whatsapp", "website", "sumber_profiling", "catatan_profiling"}:
            continue
        if key == "keberadaan_usaha":
            skipped += 1
            continue

        if key == "idsbr_master":
            result = await _handle_idsbr_master(page, ctx, config)
            updated += result.get("updated", 0)
            skipped += result.get("skipped", 0)
            errors.extend(result.get("errors", []))
            continue

        select_selector = select2_selectors.get(key)
        if select_selector:
            success, status = await update_select2_field(
                page,
                select_selector,
                ctx.profiling_payload.get(key, ""),
                key,
            )
            if status == "skip":
                skipped += 1
            elif success:
                updated += 1
            else:
                errors.append(key)
            await slow_pause(page, config)
            continue

        selector = profile_selectors.get(key)
        if not selector:
            skipped += 1
            continue

        success, status = await update_field(page, selector, ctx.profiling_payload.get(key, ""), key, None)
        if status == "skip":
            skipped += 1
        elif success:
            updated += 1
        else:
            errors.append(key)
        await slow_pause(page, config)

    return {"updated": updated, "skipped": skipped, "errors": errors}


async def fill_form(page: Page, ctx: RowContext, config: RuntimeConfig) -> dict[str, object]:
    _form_log("Mengisi form...")
    summary: dict[str, object] = {"updated": 0, "skipped": 0, "errors": []}
    if config.skip_status:
        _form_log("Status usaha dilewati (skip-status aktif).")
        summary["skipped"] = 1
    else:
        await _apply_status(page, ctx, config)
        summary["updated"] = 1

    await _fill_identitas_section(page, ctx)
    add_result = await _fill_additional_fields(page, ctx, config)
    summary["updated"] += add_result.get("updated", 0)
    summary["errors"].extend(add_result.get("errors", []))

    payload_result = await _fill_profile_payload_fields(page, ctx, config)
    summary["updated"] += payload_result.get("updated", 0)
    summary["skipped"] += payload_result.get("skipped", 0)
    summary["errors"].extend(payload_result.get("errors", []))

    _form_log("Form selesai diisi.")
    return summary
