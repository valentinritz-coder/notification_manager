from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from .hafas_gate import HafasConfig, HafasGate
from .poll import run_poll
from .report import run_report
from .subscribe import run_subscribe
from .io import copy_file, redact_data
from .notification_log import convert_notification_log_export, parse_package_filter


def _build_hafas(args: argparse.Namespace) -> HafasGate:
    config = HafasConfig(
        base_url=args.base_url,
        aid=args.aid,
        user_id=args.user_id,
        client_id=args.client_id,
        channel_id=args.channel_id,
        lang=args.lang,
        ver=args.ver,
        hci_client_type=args.hci_client_type,
        hci_client_version=args.hci_client_version,
        hci_version=args.hci_version,
        timeout_sec=args.timeout_sec,
    )
    return HafasGate(config)


def _add_hafas_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", required=True, help="HAFAS /gate endpoint")
    parser.add_argument("--aid", required=True, help="AID credential")
    parser.add_argument("--user-id", required=True, help="External user id")
    parser.add_argument(
        "--client-id",
        default="HAFAS",
        help="HAFAS client id enum for envelope client.id (e.g., HAFAS, CFL)",
    )
    parser.add_argument(
        "--channel-id",
        required=True,
        help="Push channel id (ANDROID-xxxx) for subscription delivery",
    )
    parser.add_argument("--lang", default="eng")
    parser.add_argument("--ver", default="1.72")
    parser.add_argument("--hci-client-type", default="AND")
    parser.add_argument("--hci-client-version", type=int, default=1000680)
    parser.add_argument("--hci-version", default="1.72")
    parser.add_argument("--timeout-sec", type=int, default=30)


def main() -> None:
    parser = argparse.ArgumentParser(prog="campaign")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subscribe_parser = subparsers.add_parser("subscribe", help="Create subscriptions")
    subscribe_parser.add_argument("--scenario", required=True, type=Path)
    subscribe_parser.add_argument("--out-root", required=True, type=Path)
    subscribe_parser.add_argument("--no-save-logs", action="store_true")
    _add_hafas_args(subscribe_parser)

    poll_parser = subparsers.add_parser("poll", help="Poll subscriptions for rtEvents")
    poll_parser.add_argument("--run-dir", required=True, type=Path)
    poll_parser.add_argument("--poll-sec", type=int, default=None)
    poll_parser.add_argument("--pre-window-min", type=int, default=None)
    poll_parser.add_argument("--post-window-min", type=int, default=None)
    poll_parser.add_argument("--idle-grace-min", type=int, default=None)
    poll_parser.add_argument("--max-minutes", type=int, default=0)
    poll_parser.add_argument("--include-raw", action="store_true")
    poll_parser.add_argument("--no-save-logs", action="store_true")
    poll_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print one line per poll attempt with scheduling decisions",
    )
    _add_hafas_args(poll_parser)

    sync_parser = subparsers.add_parser("sync-device-notifs", help="Copy device NDJSON into run folder")
    sync_parser.add_argument("--run-dir", required=True, type=Path)
    sync_parser.add_argument("--device-ndjson", required=True, type=Path)

    import_log_parser = subparsers.add_parser(
        "import-notification-log",
        help="Convert Notification Log export JSON into device NDJSON",
    )
    import_log_parser.add_argument("--export-json", required=True, type=Path)
    import_log_parser.add_argument("--out-ndjson", type=Path, default=None)
    import_log_parser.add_argument("--run-dir", type=Path, default=None)
    import_log_parser.add_argument("--append", action="store_true")
    import_log_parser.add_argument("--include-removed", action="store_true")
    import_log_parser.add_argument("--packages", default="")

    report_parser = subparsers.add_parser("report", help="Generate report")
    report_parser.add_argument("--run-dir", required=True, type=Path)
    report_parser.add_argument("--device-ndjson", type=Path, default=None)
    report_parser.add_argument("--out", type=Path, default=None)
    report_parser.add_argument("--match-threshold", type=float, default=70.0)
    report_parser.add_argument("--no-markdown", action="store_true")

    search_parser = subparsers.add_parser("search", help="List active subscriptions")
    _add_hafas_args(search_parser)

    args = parser.parse_args()

    if args.client_id.upper().startswith("ANDROID-"):
        print(
            "Warning: --client-id looks like a push channel id. Use --channel-id for "
            "ANDROID-xxxx and --client-id for the HAFAS/CFL client enum.",
            file=sys.stderr,
        )

    if args.command == "subscribe":
        hafas = _build_hafas(args)
        run_dir = run_subscribe(
            scenario_path=args.scenario,
            out_root=args.out_root,
            hafas=hafas,
            save_logs=not args.no_save_logs,
        )
        print(run_dir)
        return

    if args.command == "poll":
        hafas = _build_hafas(args)
        scenario = (args.run_dir / "scenario.json").read_text(encoding="utf-8")
        scenario_data = json.loads(scenario)
        poll_sec = args.poll_sec or scenario_data.get("pollSec", 120)
        pre_window_min = args.pre_window_min or scenario_data.get("preWindowMin", 10)
        post_window_min = args.post_window_min or scenario_data.get("postWindowMin", 30)
        idle_grace_min = (
            args.idle_grace_min
            if args.idle_grace_min is not None
            else scenario_data.get("idleGraceMin", 15)
        )
        max_runtime_min = args.max_minutes or scenario_data.get("maxRuntimeMin", 0)
        run_poll(
            run_dir=args.run_dir,
            hafas=hafas,
            poll_sec=poll_sec,
            pre_window_min=pre_window_min,
            post_window_min=post_window_min,
            idle_grace_min=idle_grace_min,
            max_runtime_min=max_runtime_min,
            include_raw=args.include_raw,
            save_logs=not args.no_save_logs,
            verbose=args.verbose,
        )
        return

    if args.command == "sync-device-notifs":
        dest = args.run_dir / "device/notifications.ndjson"
        copy_file(args.device_ndjson, dest)
        print(dest)
        return

    if args.command == "import-notification-log":
        if args.out_ndjson is None and args.run_dir is None:
            raise SystemExit("--out-ndjson or --run-dir is required")
        if args.out_ndjson is not None and args.run_dir is not None:
            raise SystemExit("Provide only one of --out-ndjson or --run-dir")
        out_ndjson = args.out_ndjson or (args.run_dir / "device/notifications.ndjson")
        packages = parse_package_filter(args.packages)
        written = convert_notification_log_export(
            args.export_json,
            out_ndjson,
            append=args.append,
            include_removed=args.include_removed,
            packages=packages,
        )
        print(f"OK: wrote {written} NDJSON lines -> {out_ndjson}")
        return

    if args.command == "report":
        report_dir = run_report(
            run_dir=args.run_dir,
            device_ndjson=args.device_ndjson,
            out_dir=args.out,
            match_threshold=args.match_threshold,
            write_markdown=not args.no_markdown,
        )
        print(report_dir)
        return

    if args.command == "search":
        hafas = _build_hafas(args)
        response, corr_id, _ = hafas.subscr_search()
        secrets = {
            hafas.config.aid: "<AID>",
            hafas.config.user_id: "<USER_ID>",
            hafas.config.channel_id: "<CHANNEL_ID>",
        }
        print(f"Correlation ID: {corr_id}")
        print(redact_data(response, secrets))


if __name__ == "__main__":
    main()
