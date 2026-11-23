#!/usr/bin/env python3
"""Show the pages of the CaramOS Update Center with sample data, without running an update.

Not shipped: tools/ is not installed. It imports the notifier from this source tree, and the sample changes come
from the newest migration manifests of the tree that apply to this desktop. When msgfmt is installed it compiles
po/caramos-ota/vi.po first, so a Vietnamese session reads the tree's translations; a tree with compiled catalogs in
usr/share/locale (a copy made for a VM) uses those.

    tools/preview-update-center.py update           1.3.11 to 1.4.0, the 8 newest changes
    tools/preview-update-center.py security         the same with a security fix, 3 changes
    tools/preview-update-center.py same-version     changes that keep the version (1.4.0 to 1.4.0)
    tools/preview-update-center.py version-only     only the version number changes (1.4.0 to 1.4.1)
    tools/preview-update-center.py progress         the update half done, with its log
    tools/preview-update-center.py done | failed | cancelled | busy
    tools/preview-update-center.py none             nothing new
    tools/preview-update-center.py waited           the update an automatic update left for later (metered)
    tools/preview-update-center.py auto-updated     what an automatic update installed (auto-restart: with a restart)
    tools/preview-update-center.py auto-failed      the failure page of an automatic update
    tools/preview-update-center.py demo [OUTCOME]   the real controller; Update runs a pretend update that ends
                                                    with OUTCOME (done, failed, cancelled or busy; default done)

Options:
    --size WxH            window size instead of the default one
    --geometry-file PATH  write where the window is drawn (x, y, width, height on the screen), for screenshots
    --locale-dir DIR      compiled catalogs to use (DIR/vi/LC_MESSAGES/caramos-ota.mo)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "usr/lib/python3/dist-packages"
PO = ROOT / "po/caramos-ota/vi.po"
PAGES = ("update", "security", "same-version", "version-only", "progress", "done", "failed", "cancelled", "busy",
         "none", "waited", "auto-updated", "auto-restart", "auto-failed", "demo")
OUTCOMES = ("done", "failed", "cancelled", "busy")

LOG_LINES = [
    "[✓] Repository: ppa:vietnamlinuxfamily/caram-os",
    "[✓] Updating package index...",
    "Hit:1 http://archive.ubuntu.com/ubuntu noble InRelease",
    "Get:2 http://archive.ubuntu.com/ubuntu noble-updates InRelease [126 kB]",
    "Hit:3 https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu noble InRelease",
    "Fetched 126 kB in 1s (98.4 kB/s)",
    "Reading package lists...",
    "CaramOS target version: {target}",
    "[INFO] Migration path: {current} -> {target}",
]
FAILURE_LINES = [
    "E: Failed to fetch http://archive.ubuntu.com/ubuntu/pool/universe/c/copyq/copyq_7.1.0-1_amd64.deb  "
    "Temporary failure resolving 'archive.ubuntu.com'",
    "[ERROR] Migration 20261120100000_clipboard_history failed: apt-get install copyq exited with 100",
    "Error: Migration update failed.",
    "Log: /var/log/caramos-ota/2026-11-21.log",
]


def prepare_locale(locale_dir: str | None) -> None:
    """Point caramos_ota.i18n at catalogs built from this tree; it reads the variable when it is imported."""

    if locale_dir:
        os.environ["CARAMOS_OTA_LOCALEDIR"] = locale_dir
    elif PO.is_file() and shutil.which("msgfmt"):
        target = Path(tempfile.mkdtemp(prefix="update-center-preview-")) / "vi/LC_MESSAGES"
        target.mkdir(parents=True)
        subprocess.run(["msgfmt", "-o", str(target / "caramos-ota.mo"), str(PO)], check=True)
        os.environ["CARAMOS_OTA_LOCALEDIR"] = str(target.parents[1])
    elif (ROOT / "usr/share/locale/vi/LC_MESSAGES/caramos-ota.mo").is_file():
        os.environ["CARAMOS_OTA_LOCALEDIR"] = str(ROOT / "usr/share/locale")


def sample_update(*, current: str = "1.3.11", target: str = "1.4.0", count: int = 8, severity: str = "") -> dict:
    """update_info as caramos_ota_notifier.state builds it, from the newest manifests that apply here."""

    from caramos_ota.manifest import _manifest_from_descriptors
    from caramos_ota.models import ReleaseInfo
    from caramos_ota_update.desktop import applies
    from caramos_ota_update.registry import discover_migrations

    newest = [item for item in discover_migrations() if not item.legacy and applies(item.desktops)][-count:]
    release = ReleaseInfo(name="CaramOS", version=current, codename=newest[-1].codename, channel=newest[-1].channel)
    manifest = _manifest_from_descriptors(newest, release, target)
    return {
        "detected_at": "preview",
        "release": target,
        "to_version": target,
        "current_version": current,
        "from_version": current,
        "channel": manifest.channel,
        "severity": severity or manifest.severity,
        "size": manifest.size,
        "size_en": manifest.size_en,
        "title": manifest.title,
        "summary": manifest.summary,
        "title_en": manifest.title_en,
        "summary_en": manifest.summary_en,
        "migration_ids": [item.migration_id for item in newest],
        "packages": [
            {
                "name": item.title,
                "current_version": "",
                "available_version": "",
                "description": item.summary,
                "required": False,
                "name_en": item.title_en,
                "description_en": item.summary_en,
            }
            for item in newest
        ],
    }


def version_only_update() -> dict:
    """What the daily check saves when only the version number changes (caramos_ota.apt.detect_updates)."""

    return {
        "detected_at": "preview", "release": "1.4.1", "to_version": "1.4.1",
        "current_version": "1.4.0", "from_version": "1.4.0", "channel": "stable", "severity": "normal",
        "size": "Thông tin phiên bản", "size_en": "Release metadata",
        "title": "Cập nhật CaramOS", "title_en": "CaramOS update", "migration_ids": [],
        "packages": [{"name": "CaramOS release metadata", "current_version": "1.4.0", "available_version": "1.4.1",
                      "description": "Update CaramOS release metadata to packaged target.", "required": True}],
    }


def log_text(update_info: dict, *, failed: bool = False) -> list[str]:
    values = {"current": update_info["current_version"], "target": update_info["release"]}
    lines = [line.format(**values) for line in LOG_LINES]
    for migration_id in update_info["migration_ids"][: 1 if failed else 4]:
        lines.append(f"[INFO] Starting migration {migration_id}")
        if not failed:
            lines.append(f"[INFO] Finished migration {migration_id}")
    return lines + (FAILURE_LINES if failed else [])


def write_geometry(window, path: str) -> bool:
    """The drawn part of the window (header bar and pages, no shadow), in screen pixels."""

    header, child = window.get_titlebar(), window.get_child()
    origin = window.get_window().get_origin()
    x, y = header.translate_coordinates(window, 0, 0)
    bottom = child.translate_coordinates(window, 0, child.get_allocated_height())[1]
    geometry = {"x": origin.x + x, "y": origin.y + y, "width": header.get_allocated_width(), "height": bottom - y}
    Path(path).write_text(json.dumps(geometry), encoding="utf-8")
    return False


def pretend_toggle(GLib):
    """A stand-in for the pkexec helper of the Automatic updates switch: the setting follows a second later."""

    def toggle(wanted: bool, finish) -> None:
        print("Automatic updates", "on" if wanted else "off")
        GLib.timeout_add(1000, finish, wanted)

    return toggle


def auto_result(update_info: dict, outcome: str, *, restart: bool = False) -> dict:
    """What caramos_ota.auto_update.run() writes for the users' notifiers."""

    return {"schema": 1, "id": "preview", "outcome": outcome, "started_at": "2026-11-23T10:30:00+07:00",
            "finished_at": "2026-11-23T10:32:00+07:00", "exit_code": 0 if outcome == "done" else 1,
            "from_version": update_info["current_version"], "to_version": update_info["release"], "restart": restart,
            "update": update_info, "output": "\n".join(log_text(update_info, failed=outcome == "failed"))}


def pretend_upgrade(outcome: str, update_info: dict):
    """A stand-in for app.run_upgrade_stream: the lines of a real run, slowly, then the outcome."""

    from caramos_ota_notifier import app

    def run(on_line):
        lines = log_text(update_info, failed=outcome == "failed")
        if outcome == "cancelled":
            lines = ["Error executing command as another user: Request dismissed"]
        elif outcome == "busy":
            lines = ["Error: Another CaramOS OTA operation is already running."]
        for line in lines:
            time.sleep(0.6)
            on_line(line)
        result = {"done": app.DONE, "failed": app.FAILED, "cancelled": app.CANCELLED, "busy": app.BUSY}[outcome]
        return result, "\n".join(lines)

    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("page", nargs="?", default="update", choices=PAGES)
    parser.add_argument("outcome", nargs="?", default="done", choices=OUTCOMES, help="demo only")
    parser.add_argument("--size", help="window size, e.g. 380x360")
    parser.add_argument("--geometry-file")
    parser.add_argument("--locale-dir")
    args = parser.parse_args(argv)

    prepare_locale(args.locale_dir)
    sys.path.insert(0, str(DIST))
    from caramos_ota_notifier import app, ui

    Gtk, _gdk, GLib = ui.import_gtk()
    quit_loop = lambda *_args: Gtk.main_quit()   # noqa: E731
    update = sample_update()
    switch = ui.AutoUpdateSwitch(enabled=True, on_toggle=pretend_toggle(GLib))

    if args.page == "demo":
        app.run_upgrade_stream = pretend_upgrade(args.outcome, update)
        app.problem.help_available = lambda: True
        app.problem.ask_for_help = lambda detail, info: print("Ask for help pressed; the log has", len(detail), "characters")
        controller = app.UpdateWindowController(Gtk, GLib, update, {"current_version": "1.3.11"})
        window = controller.window
    else:
        window, stack = ui.build_update_window()
        window.connect("destroy", quit_loop)
        close = window.destroy
        if args.page in ("update", "security", "same-version", "version-only"):
            info = {
                "update": update,
                "security": sample_update(count=3, severity="security"),
                "same-version": sample_update(current="1.4.0"),
                "version-only": version_only_update(),
            }[args.page]
            page = ui.build_update_page(info, lambda: print("Update pressed"), close, auto_update=switch)
        elif args.page == "waited":
            switch.note = "metered"
            page = ui.build_update_page(update, lambda: print("Update pressed"), close, auto_update=switch)
        elif args.page in ("auto-updated", "auto-restart"):
            page = ui.build_auto_updated_page(auto_result(update, "done", restart=args.page == "auto-restart"), close,
                                              auto_update=switch)
        elif args.page == "auto-failed":
            result = auto_result(update, "failed")
            page = ui.build_result_page(app.FAILED, app.auto_update_ui.failure_detail(result), close,
                                        on_help=lambda: print("Ask for help pressed"), update_info=update)
        elif args.page == "progress":
            page, progress, stage, log_view = ui.build_progress_page(update)
            progress.set_fraction(0.45)
            stage.set_text(app.stage_for_line("[INFO] Starting migration 20261120100300_external_monitor_brightness"))
            log_view.get_buffer().set_text("\n".join(log_text(update)))
        elif args.page == "none":
            page = ui.build_no_update_page({"current_version": "1.4.0", "latest_version": "1.4.0"}, close,
                                           auto_update=switch)
        else:
            outcome = {"done": app.DONE, "failed": app.FAILED, "cancelled": app.CANCELLED, "busy": app.BUSY}[args.page]
            detail = "\n".join(log_text(update, failed=outcome == app.FAILED))
            if outcome == app.CANCELLED:
                detail = "Error executing command as another user: Request dismissed"
            elif outcome == app.BUSY:
                detail = "Error: Another CaramOS OTA operation is already running."
            page = ui.build_result_page(
                outcome, detail, close,
                on_help=(lambda: print("Ask for help pressed")) if outcome == app.FAILED else None,
                on_retry=(lambda: print("Try again pressed")) if outcome in (app.CANCELLED, app.BUSY) else None,
                update_info=update,
            )
        stack.add_named(page, args.page)

    if args.size:
        width, height = (int(value) for value in args.size.lower().split("x"))
        window.resize(width, height)
    window.show_all()
    if args.geometry_file:
        GLib.timeout_add(800, write_geometry, window, args.geometry_file)
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
