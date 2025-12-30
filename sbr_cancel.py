from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from sbr_automation.cancel import process_cancel
from sbr_automation.config import (
    DEFAULT_KEEP_RUNS,
    CancelOptions,
    ExcelSelection,
    RuntimeConfig,
    create_run_directories,
    load_profile_defaults,
)
from sbr_automation.excel_loader import resolve_excel


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
        "pause_after_edit",
        "max_wait",
        "run_id",
        "keep_runs",
    }
    profile_defaults = load_profile_defaults(initial.profile, allowed_profile_keys)

    parser = argparse.ArgumentParser(description="SBR Cancel Submit (attach via CDP)", parents=[base])
    if profile_defaults:
        parser.set_defaults(**profile_defaults)
    parser.set_defaults(profile=initial.profile)
    parser.add_argument("--excel", help="Path ke file Excel (auto-scan folder kerja bila tidak diisi)")
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
    parser.add_argument("--pause-after-edit", type=int, default=1000, help="Jeda setelah klik Edit (ms)")
    parser.add_argument("--max-wait", type=int, default=6000, help="Timeout tunggu elemen/tab (ms)")
    parser.add_argument("--run-id", help="Gunakan run ID khusus (huruf/angka/-/_) untuk folder artefak")
    parser.add_argument("--keep-runs", type=int, help="Batasi jumlah folder run yang dipertahankan (default 10)")
    return parser.parse_args(remaining)


def build_options(args: argparse.Namespace, working_dir: Path) -> tuple[CancelOptions, RuntimeConfig]:
    excel_selection: ExcelSelection = resolve_excel(args.excel, working_dir, args.sheet)
    keep_runs = args.keep_runs if args.keep_runs is not None else DEFAULT_KEEP_RUNS
    run_id, log_dir, screenshot_dir, cancel_dir, started_at = create_run_directories(args.run_id, keep_runs)
    options = CancelOptions(
        excel=excel_selection,
        match_by=args.match_by,
        start_row=args.start,
        end_row=args.end,
        stop_on_error=args.stop_on_error,
    )

    config = RuntimeConfig(
        cdp_endpoint=args.cdp_endpoint,
        sheet_index=args.sheet,
        pause_after_edit_ms=args.pause_after_edit,
        max_wait_ms=args.max_wait,
        log_dir=log_dir,
        screenshot_dir=screenshot_dir,
        cancel_screenshot_dir=cancel_dir,
        run_id=run_id,
        run_started_at=started_at,
        keep_runs=keep_runs,
        profile_path=args.profile,
    )
    return options, config


def main() -> None:
    args = parse_args()
    options, config = build_options(args, Path.cwd())
    asyncio.run(process_cancel(options, config))


if __name__ == "__main__":
    main()
