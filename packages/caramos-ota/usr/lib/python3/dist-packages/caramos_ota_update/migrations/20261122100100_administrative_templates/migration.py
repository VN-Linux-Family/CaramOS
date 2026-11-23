"""Files: right-click > "Mới" > "Văn bản hành chính", the templates of Nghị định 30/2020/NĐ-CP.

The package ships the documents (usr/share/caramos-ota/templates/nd30: công văn, quyết định, tờ trình, báo cáo,
thông báo, giấy mời, biên bản, biên bản bàn giao tài sản) and caramos-templates, which puts each set of templates
into a user's Templates folder once. Users whose office templates went in before this version have that set's
record already; the new set has its own (templates-nd30.json), so caramos-templates.timer adds the folder at their
next login. This starts the service in the sessions that are open now, so the folder is there at once. Files the
user has are never replaced, and a user without a Templates folder gets it when xdg-user-dirs makes one. Nemo shows
the folder as a submenu: "Văn bản hành chính" in Vietnamese sessions, "Vietnamese Official Documents" in English
ones. A failure is logged and does not stop the update.
"""

from __future__ import annotations

import importlib

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Files: the administrative document templates of Nghị định 30 under right-click > New"

files_new_menu = importlib.import_module("caramos_ota_update.migrations.20261118090000_files_new_menu.migration")

SERVICE = "caramos-templates.service"
SERVICE_FILE = files_new_menu.TIMER_FILE.parent / SERVICE


def run(context: MigrationContext) -> None:
    if context.dry_run:
        context.log(f"start {SERVICE} in the open sessions")
        return
    if not SERVICE_FILE.exists():
        context.log(f"{SERVICE_FILE} is missing; no templates")
        return
    for username, uid in files_new_menu._desktop_users():
        if not files_new_menu._user_manager_running(uid):
            continue
        reload = files_new_menu._systemctl(username, uid, "daemon-reload")
        start = files_new_menu._systemctl(username, uid, "start", SERVICE) if reload.returncode == 0 else reload
        if start.returncode == 0:
            context.log(f"started {SERVICE} for {username}")
        else:
            context.log(f"could not start {SERVICE} for {username} ({start.stderr.strip()[:160]}); "
                        "the templates come at the next login")
