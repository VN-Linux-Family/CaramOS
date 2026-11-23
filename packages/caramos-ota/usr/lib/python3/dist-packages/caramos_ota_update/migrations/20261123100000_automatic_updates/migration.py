"""Automatic updates: new CaramOS versions install by themselves, and everyone logged in is told afterwards.

The owner (2026-11-23): "làm luôn tính năng auto update cho OTA nhé, kiểu có 1 nút là tự động cập nhật, mặc định là
bật ấy". The package brings all of it (caramos_ota.auto_update): the setting, on unless /etc/caramos-ota/auto-update.conf
says no; caramos-ota-auto-update.service, which caramos-ota-check.service starts after each successful daily check; the
Update Center's "Tự động cập nhật" switch; and caramos-ota-auto-update-notify.path, a systemd user unit enabled for
every user, which shows the notification when an automatic update finishes.

A user service manager that is already running sees that unit only after a reload: here each logged-in user's manager
is reloaded and the unit started, so the people at work now are told when this update, if it installs by itself, or
the next one is done. A failure is logged and does not stop the update; the unit then starts at the next login. Its
notes tell users about the feature and how to turn it off.
"""

from __future__ import annotations

import importlib

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Automatic updates: tell the people logged in now when an update installs by itself"

files_new_menu = importlib.import_module("caramos_ota_update.migrations.20261118090000_files_new_menu.migration")

UNIT = "caramos-ota-auto-update-notify.path"
UNIT_FILE = files_new_menu.TIMER_FILE.parent / UNIT


def run(context: MigrationContext) -> None:
    if context.dry_run:
        context.log(f"start {UNIT} in the open sessions")
        return
    if not UNIT_FILE.exists():
        context.log(f"{UNIT_FILE} is missing; nothing to start")
        return
    for username, uid in files_new_menu._desktop_users():
        if not files_new_menu._user_manager_running(uid):
            continue
        reload = files_new_menu._systemctl(username, uid, "daemon-reload")
        start = files_new_menu._systemctl(username, uid, "start", UNIT) if reload.returncode == 0 else reload
        if start.returncode == 0:
            context.log(f"started {UNIT} for {username}")
        else:
            context.log(f"could not start {UNIT} for {username} ({start.stderr.strip()[:160]}); "
                        "it starts at the next login")
