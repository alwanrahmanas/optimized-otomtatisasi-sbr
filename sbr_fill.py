from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sbr_automation.autofill import process_autofill
from sbr_automation.config import (
    DEFAULT_KEEP_RUNS,
    AutofillOptions,
    ExcelSelection,
    MatchStrategy,
    RuntimeConfig,
    create_run_directories,
    load_profile_defaults,
    load_status_map,
)
from sbr_automation.excel_loader import resolve_excel
from sbr_automation.field_selectors import load_field_selectors


def parse_args() -> argparse.Namespace:
    base = argparse.ArgumentParser(add_help=False)
    base.add_argument("--profile", help="Path file profil JSON berisi default argumen CLI")
    initial, remaining = base.parse_known_args()

    allowed_profile_keys = {
        "excel",
        "sheet",
        "match_by",
        "start",
        "end",
        "stop_on_error",
        "cdp_endpoint",
        "no_slow_mode",
        "step_delay",
        "pause_after_edit",
        "pause_after_submit",
        "max_wait",
        "resume",
        "dry_run",
        "skip_status",
        "status_map",
        "selectors",
        "run_id",
        "keep_runs",
    }
    profile_defaults = load_profile_defaults(initial.profile, allowed_profile_keys)

    parser = argparse.ArgumentParser(description="SBR Autofill (Chrome attach via CDP)", parents=[base])
    if profile_defaults:
        parser.set_defaults(**profile_defaults)
    parser.set_defaults(profile=initial.profile)
    parser.add_argument("--excel", help="Path ke file Excel (jika tidak diisi akan auto-scan folder kerja)")
    parser.add_argument("--sheet", type=int, default=0, help="Index sheet Excel (default: 0)")
    parser.add_argument("--match-by", choices=["index", "idsbr", "name"], default="index", help="Metode mencari tombol Edit")
    parser.add_argument("--start", type=int, help="Mulai dari baris ke- (1-indexed)")
    parser.add_argument("--end", type=int, help="Sampai baris ke- (inklusif)")
    parser.add_argument("--stop-on-error", action="store_true", help="Berhenti saat menemukan error pertama")
    parser.add_argument(
        "--cdp-endpoint",
        default="http://localhost:9222",
        help="Endpoint CDP Chrome (default: http://localhost:9222)",
    )
    parser.add_argument("--no-slow-mode", action="store_true", help="Menonaktifkan jeda antar langkah")
    parser.add_argument("--step-delay", type=int, default=700, help="Lama jeda slow mode (ms)")
    parser.add_argument("--pause-after-edit", type=int, default=1000, help="Jeda setelah klik Edit (ms)")
    parser.add_argument("--pause-after-submit", type=int, default=300, help="Jeda setelah klik Submit (ms)")
    parser.add_argument("--max-wait", type=int, default=6000, help="Timeout tunggu elemen/tab (ms)")
    parser.add_argument(
        "--skip-status",
        action="store_true",
        help="Lewati pengisian status usaha (gunakan jika hanya ingin memperbarui field lain)",
    )
    parser.add_argument(
        "--status-map",
        help="Path JSON berisi pemetaan Status -> ID radio pada MATCHAPRO",
    )
    parser.add_argument(
        "--selectors",
        help="Path JSON kustom untuk selector field Profiling (fields/select2)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Hanya uji pencarian tombol Edit tanpa membuka form dan mengisi data",
    )
    parser.add_argument("--resume", action="store_true", help="Lewati baris yang sebelumnya berstatus OK di log")
    parser.add_argument("--run-id", help="Gunakan run ID khusus (huruf/angka/-/_) untuk folder artefak")
    parser.add_argument("--keep-runs", type=int, help="Batasi jumlah folder run yang dipertahankan (default 10)")
    return parser.parse_args(remaining)


def build_options(args: argparse.Namespace, working_dir: Path) -> tuple[AutofillOptions, RuntimeConfig]:
    excel_selection: ExcelSelection = resolve_excel(args.excel, working_dir, args.sheet)
    status_map = load_status_map(args.status_map)
    profile_selectors, select2_selectors = load_field_selectors(args.selectors)
    keep_runs = args.keep_runs if args.keep_runs is not None else DEFAULT_KEEP_RUNS
    run_id, log_dir, screenshot_dir, cancel_dir, started_at = create_run_directories(args.run_id, keep_runs)
    options = AutofillOptions(
        excel=excel_selection,
        match_by=args.match_by,
        start_row=args.start,
        end_row=args.end,
        stop_on_error=args.stop_on_error,
        resume=args.resume,
        dry_run=args.dry_run,
    )

    config = RuntimeConfig(
        cdp_endpoint=args.cdp_endpoint,
        sheet_index=args.sheet,
        pause_after_edit_ms=args.pause_after_edit,
        pause_after_submit_ms=args.pause_after_submit,
        max_wait_ms=args.max_wait,
        slow_mode=not args.no_slow_mode,
        step_delay_ms=args.step_delay,
        skip_status=args.skip_status,
        status_id_map=status_map,
        profile_field_selectors=profile_selectors,
        select2_field_selectors=select2_selectors,
        screenshot_dir=screenshot_dir,
        cancel_screenshot_dir=cancel_dir,
        log_dir=log_dir,
        run_id=run_id,
        run_started_at=started_at,
        keep_runs=keep_runs,
        profile_path=args.profile,
    )
    return options, config


def main() -> None:
    args = parse_args()
    options, config = build_options(args, Path.cwd())
    asyncio.run(process_autofill(options, config))


if __name__ == "__main__":
    main()
