"""Feedback & Help: the question mark in the panel (applet caramos-help@caramos), the caramos-help command,
menu entry and form, and migration 20261012180000_add_help_applet, which puts the applet on existing panels."""

from __future__ import annotations

import ast
import configparser
import importlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
APPLET = ROOT / "usr/share/caramos-ota/applets/caramos-help@caramos"
APP = ROOT / "usr/share/caramos-ota/driver-check"
VI_PO = ROOT / "po/caramos-ota/vi.po"
PANEL_DEFAULTS = REPO / "config/includes.chroot/etc/dconf/db/local.d/01-caramos-task17-panel"
PANEL_HOOK = REPO / "config/hooks/live/0170-cinnamon-task17-spices.hook.chroot"
HELP = "'panel1:right:4:caramos-help@caramos:8'"

# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(APP))

from caramos_driver_check import help_app, helpdesk  # noqa: E402

migration = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")


def translations(path: Path) -> dict[str, str]:
    """msgid -> msgstr of a .po file (singular entries)."""

    entries: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("msgid "):
            msgid, msgstr, current = [line[6:]], None, None
            current = msgid
        elif line.startswith("msgstr "):
            msgstr = [line[7:]]
            current = msgstr
        elif line.startswith('"') and current is not None:
            current.append(line)
        elif not line.strip() and msgid is not None and msgstr is not None:
            entries["".join(ast.literal_eval(part) for part in msgid)] = "".join(
                ast.literal_eval(part) for part in msgstr)
            msgid = msgstr = current = None
    return entries


def desktop_entry(path: Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser["Desktop Entry"]


class AppletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (APPLET / "applet.js").read_text(encoding="utf-8")

    def test_metadata(self) -> None:
        metadata = json.loads((APPLET / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(APPLET.name, metadata["uuid"])
        self.assertEqual(1, metadata["max-instances"])

    def test_javascript_syntax(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        subprocess.run([node, "--check", str(APPLET / "applet.js")], check=True, capture_output=True, text=True)

    def test_the_panel_menu_and_window_show_the_question_mark_of_the_icon_theme(self) -> None:
        # Drawn like the panel icons next to it, in any icon theme.
        self.assertIn("const ICON = 'dialog-question-symbolic';", self.source)
        self.assertIn("this.set_applet_icon_symbolic_name(ICON);", self.source)
        self.assertIn("twoLines(this._themed(ICON), _('Feedback & Help'),", self.source)
        window = (APP / "caramos_driver_check/ui/help.py").read_text(encoding="utf-8")
        self.assertIn('icon_bubble("dialog-question-symbolic", 36,', window)

    def test_the_bug_is_shipped_with_the_applet_and_the_window(self) -> None:
        # The icon theme has no bug: the same drawing in the menu and the window.
        name = "caramos-bug-symbolic.svg"
        self.assertEqual((APP / "icons" / name).read_bytes(), (APPLET / "icons" / name).read_bytes())
        self.assertIn(f"'{name}'", self.source)
        self.assertEqual([name], sorted(path.name for path in (APPLET / "icons").iterdir()))

    def test_last_on_the_right_it_keeps_off_the_rounded_end_of_the_panel(self) -> None:
        self.assertIn("this.actor.add_style_class_name('caramos-help-panel-button');", self.source)
        css = (APPLET / "stylesheet.css").read_text(encoding="utf-8")
        for panel in ("top", "bottom"):
            self.assertIn(f".panel-{panel} .panelRight > .caramos-help-panel-button:last-child", css)
        self.assertIn("margin-right: 8px;", css)

    def test_the_menu_opens_each_kind_of_request_and_driver_check(self) -> None:
        for kind in help_app.KINDS:
            self.assertIn(f"['caramos-help', '--type', '{kind}']", self.source)
        self.assertIn("['caramos-driver-check']", self.source)

    def test_it_lists_the_requests_the_window_keeps(self) -> None:
        self.assertEqual(Path("/h/.local/state/caramos-help/requests.json"), helpdesk.history_path({"HOME": "/h"}))
        self.assertIn("GLib.getenv('XDG_STATE_HOME')", self.source)
        self.assertIn("[GLib.get_home_dir(), '.local', 'state']", self.source)
        self.assertIn("[state, 'caramos-help', 'requests.json']", self.source)
        # Only https pages are opened, like the window does.
        self.assertIn("item.url.startsWith('https://')", self.source)

    def test_requests_shared_with_the_community_say_so(self) -> None:
        # The window keeps the choice (helpdesk.remember); the theme's people icon tells it from the message.
        self.assertIn("} else if (request.public === true) {", self.source)
        self.assertIn("note.add_child(chip('system-users-symbolic', _('Shared with the community')));", self.source)
        self.assertIn("noteFor(request));", self.source)

    def test_answers_from_the_community_take_the_place_of_shared(self) -> None:
        self.assertIn("ngettext('%d answer from the community', '%d answers from the community', answers)",
                      self.source)
        self.assertIn("note.add_child(chip('system-users-symbolic', text.replace('%d', String(answers)), "
                      "!finished(request)));", self.source)
        window = (APP / "caramos_driver_check/ui/requests.py").read_text(encoding="utf-8")
        self.assertIn('ngettext("%d answer from the community", "%d answers from the community",', window)
        catalog = (VI_PO).read_text(encoding="utf-8")
        self.assertIn('msgid "%d answer from the community"\nmsgid_plural "%d answers from the community"\n'
                      'msgstr[0] "Có %d câu trả lời từ cộng đồng"', catalog)
        readme = (ROOT / "po/README.md").read_text(encoding="utf-8")
        self.assertIn("--language=JavaScript --from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 --join-existing",
                      readme)
        css = (APPLET / "stylesheet.css").read_text(encoding="utf-8")
        self.assertIn(".caramos-help-note {", css)
        self.assertIn(".caramos-help-chip {", css)
        self.assertIn(".caramos-help-note-icon {\n  icon-size: 12px;", css)

    def test_requests_say_what_vnlf_says_in_the_words_of_the_window(self) -> None:
        try:
            from caramos_driver_check.ui import requests as window_list
        except ImportError:   # the package builders have no GTK
            self.skipTest("python3-gi is not installed")

        start = self.source.index("function statusOf(request) {")
        words = set(re.findall(r"_\('([^']*)'\)", self.source[start:self.source.index("\n}\n", start)]))
        statuses = [{"status": "GONE"}, {"replied": True}, {"status": "IN_REVIEW"}, {"status": "RESOLVED"},
                    {"status": "CLOSED"}]
        self.assertEqual(words, {window_list.status_text(item)[0] for item in statuses})
        self.assertEqual(("", ""), window_list.status_text({"status": "OPEN"}))
        # An answer VNLF gave to a request it has not finished stands out.
        self.assertIn("chip(status[0], status[1], request.replied === true && !finished(request))", self.source)

    def test_finished_requests_are_lighter_and_leave_the_menu_as_in_helpdesk(self) -> None:
        self.assertIn(f"const KEEP_FINISHED_DAYS = {helpdesk.KEEP_FINISHED_DAYS};", self.source)
        self.assertIn("const FINISHED = [%s];" % ", ".join(f"'{status}'" for status in helpdesk.FINISHED), self.source)
        self.assertIn("requests.filter(request => listed(request, now)).slice(0, REQUESTS_SHOWN)", self.source)
        self.assertIn("if (finished(request)) item.row.opacity = 150;", self.source)

    def test_the_window_lists_the_others(self) -> None:
        self.assertIn("if (shown.length < requests.length) {", self.source)
        self.assertIn("_('See all %d requests')", self.source)
        self.assertIn("Util.spawn(['caramos-help', '--requests'])", self.source)

    def test_vnlf_is_asked_now_and_then_by_caramos_help(self) -> None:
        self.assertIn("Gio.Subprocess.new(['caramos-help', '--refresh'], Gio.SubprocessFlags.NONE)", self.source)
        self.assertIn("const REFRESH_EVERY_SECONDS = 30 * 60;", self.source)
        # Only with requests, one at a time, and not after the applet is gone.
        self.assertIn("if (this._refreshing || !this._hasRequests) return;", self.source)
        self.assertIn("GLib.source_remove(this._refreshId);", self.source)

    def test_the_panel_never_waits(self) -> None:
        self.assertIn("load_contents_async", self.source)
        for blocking in ("spawn_sync", "file_get_contents", "load_contents(", "spawnCommandLine"):
            self.assertNotIn(blocking, self.source)

    def test_the_list_is_built_while_the_menu_is_closed(self) -> None:
        # Items added to an open Cinnamon menu are squeezed into its old height.
        self.assertIn("monitor_file(", self.source)
        self.assertIn("this._monitor.cancel();", self.source)
        self.assertEqual(2, self.source.count("if (this.menu.isOpen)"))

    def test_texts_are_translated(self) -> None:
        texts = set(re.findall(r"\b_\('((?:[^'\\]|\\.)*)'\)", self.source))
        self.assertGreaterEqual(len(texts), 20)
        catalog = translations(VI_PO)
        for text in sorted(texts):
            with self.subTest(text=text):
                self.assertTrue(catalog.get(text), f"no Vietnamese for {text!r}: run xgettext with the applet (po/README.md)")
        self.assertIn("const TEXT_DOMAIN = 'caramos-ota';", self.source)


class FormTests(unittest.TestCase):
    """The form of Feedback & Help and Driver Check (ui/help.py), read as text: it needs a display to run."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (APP / "caramos_driver_check/ui/help.py").read_text(encoding="utf-8")

    def test_sharing_with_the_community_is_asked_last_and_ticked(self) -> None:
        box = 'self.public = Gtk.CheckButton(label=_("Let the VNLF community see it and help"), active=True)'
        self.assertIn(box, self.source)
        # The user's answer stays when another kind is chosen.
        self.assertNotIn("self.public.set_active(", self.source)
        # Right above Send: the last thing in the form.
        start = self.source.index(box)
        end = self.source.index("content.append(form)", start)
        self.assertEqual(["self.public", "public_note"], re.findall(r"form\.append\(([^)]*)\)", self.source[start:end]))
        self.assertIn('_("Your contact is not made public.")', self.source)

    def test_it_says_that_pictures_and_videos_are_published_with_a_shared_request(self) -> None:
        attachments = (APP / "caramos_driver_check/ui/attachments.py").read_text(encoding="utf-8")
        self.assertNotIn("Only the VNLF team sees them.", attachments)
        self.assertIn('"request, they are published with it once VNLF has reviewed them."', attachments)

    def test_the_request_carries_the_choice(self) -> None:
        self.assertIn("tuple(self.attachments.ready()), self.public.get_active(),", self.source)
        self.assertIn("public=request.public, logs=request.log_texts())", self.source)
        self.assertIn('if payload.get("public"):', self.source)

    def test_the_header_opens_the_requests_sent_before(self) -> None:
        self.assertIn("on_requests=self.show_requests if helpdesk.sent_requests() else None,", self.source)
        self.assertIn('label=_("Your requests")))', self.source)
        self.assertIn('self._set_page("requests", page)', self.source)

    def test_texts_are_translated(self) -> None:
        catalog = translations(VI_PO)
        self.assertEqual("Cho cộng đồng VNLF xem để cùng giúp", catalog["Let the VNLF community see it and help"])
        self.assertEqual("Thông tin liên hệ không công khai.", catalog["Your contact is not made public."])
        self.assertEqual("Đã chia sẻ với cộng đồng", catalog["Shared with the community"])


class CommandTests(unittest.TestCase):
    def test_kinds(self) -> None:
        self.assertEqual("os", help_app.parse_args([]).kind)
        self.assertEqual("bug", help_app.parse_args(["--type", "bug"]).kind)
        self.assertEqual("feedback", help_app.parse_args(["--type", "feedback"]).kind)
        self.assertTrue(set(help_app.KINDS) <= set(helpdesk.KINDS))
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            help_app.parse_args(["--type", "driver"])   # Driver Check's own
        self.assertTrue(help_app.parse_args(["--requests"]).requests)
        self.assertFalse(help_app.parse_args([]).requests)

    def test_refresh_needs_no_window(self) -> None:
        answered = (helpdesk.News({"id": "H-1", "url": "https://vietnamlinuxfamily.net/caramos/help/a"}, reply=True),)
        for news, shown in (((), 0), (answered, 1)):
            with self.subTest(news=news), \
                    mock.patch.object(helpdesk, "refresh", return_value=helpdesk.Refresh(1, 0, news)) as refresh, \
                    mock.patch("caramos_driver_check.notify.show_news", return_value=0) as show, \
                    mock.patch.dict("os.environ", {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                self.assertEqual(0, help_app.main(["--refresh"]))
                refresh.assert_called_once_with()
                self.assertEqual(shown, show.call_count)

    def test_the_command_loads_the_app_from_usr_share(self) -> None:
        command = ROOT / "usr/bin/caramos-help"
        text = command.read_text(encoding="utf-8")
        self.assertIn('sys.path.insert(0, "/usr/share/caramos-ota/driver-check")', text)
        self.assertIn("from caramos_driver_check.help_app import main", text)
        self.assertTrue(command.stat().st_mode & 0o111)

    def test_menu_entry(self) -> None:
        entry = desktop_entry(ROOT / "usr/share/applications/caramos-help.desktop")
        self.assertEqual("/usr/bin/caramos-help", entry["Exec"])
        self.assertEqual("Góp ý & hỗ trợ", entry["Name[vi]"])
        self.assertEqual("caramos-help", entry["StartupWMClass"])

    def test_package_installs_every_part(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in (
            "usr/bin/caramos-help usr/bin/",
            "usr/share/applications/caramos-help.desktop usr/share/applications/",
            "usr/share/caramos-ota/applets/caramos-help@caramos usr/share/cinnamon/applets/",
        ):
            self.assertIn(line + "\n", install)
            self.assertTrue((ROOT / line.split()[0]).exists(), line)

    def test_build_and_smoke_test_compile_the_command(self) -> None:
        testkit = (ROOT / "tools/caramos-ota-testkit.sh").read_text(encoding="utf-8")
        self.assertEqual(2, len(re.findall(r"usr/bin/caramos-help \\", testkit)))
        self.assertIn("command -v caramos-help\n", testkit)


class PanelTests(unittest.TestCase):
    STOCK = ("['panel1:left:0:Cinnamenu@json:0', 'panel1:center:0:grouped-window-list@cinnamon.org:1', "
             "'panel1:right:0:systray@cinnamon.org:2', 'panel1:right:1:notifications@cinnamon.org:5', "
             "'panel1:right:2:calendar@cinnamon.org:7', 'panel1:right:3:caramos-control-center@caramos:0']")
    WITH_HELP = STOCK[:-1] + f", {HELP}]"

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_new_installs_have_it_at_the_right_end(self) -> None:
        # The last icon: only Show desktop's strip, which shows nothing until pointed at, comes after it
        # (Cinnamon's corner bar, migration 20261124100000).
        with_corner_bar = self.WITH_HELP[:-1] + ", 'panel1:right:5:cornerbar@cinnamon.org:9']"
        for path in (PANEL_DEFAULTS, PANEL_HOOK):
            with self.subTest(path=path.name):
                self.assertIn(f"enabled-applets={with_corner_bar}\n", path.read_text(encoding="utf-8"))

    def test_it_goes_at_the_right_end_of_the_stock_panel(self) -> None:
        self.assertEqual(self.WITH_HELP, migration.add_applet(self.STOCK))

    def test_it_goes_after_the_applets_of_a_changed_panel(self) -> None:
        panel = ("@as ['panel1:left:0:Cinnamenu@json:0', 'panel1:right:0:systray@cinnamon.org:2', "
                 "'panel1:right:5:calendar@cinnamon.org:7', 'panel1:right:6:caramos-control-center@caramos:9', "
                 "'panel1:right:4:keyboard@cinnamon.org:3']")
        self.assertEqual(
            "['panel1:left:0:Cinnamenu@json:0', 'panel1:right:0:systray@cinnamon.org:2', "
            "'panel1:right:5:calendar@cinnamon.org:7', 'panel1:right:6:caramos-control-center@caramos:9', "
            "'panel1:right:4:keyboard@cinnamon.org:3', 'panel1:right:7:caramos-help@caramos:10']",
            migration.add_applet(panel))

    def test_on_the_panel_with_the_control_center_else_the_clock(self) -> None:
        self.assertEqual(
            "['panel1:right:0:calendar@cinnamon.org:1', 'panel2:right:0:caramos-control-center@caramos:0', "
            "'panel2:right:1:caramos-help@caramos:2']",
            migration.add_applet("['panel1:right:0:calendar@cinnamon.org:1', "
                                 "'panel2:right:0:caramos-control-center@caramos:0']"))
        self.assertEqual(
            "['panel1:left:0:Cinnamenu@json:0', 'panel2:right:0:calendar@cinnamon.org:1', "
            "'panel2:right:1:sound@cinnamon.org:2', 'panel2:right:2:caramos-help@caramos:3']",
            migration.add_applet("['panel1:left:0:Cinnamenu@json:0', 'panel2:right:0:calendar@cinnamon.org:1', "
                                 "'panel2:right:1:sound@cinnamon.org:2']"))
        # Neither: the first panel.
        self.assertEqual("['panel1:right:0:systray@cinnamon.org:2', 'panel1:right:1:caramos-help@caramos:3']",
                         migration.add_applet("['panel1:right:0:systray@cinnamon.org:2']"))

    def test_a_panel_with_the_applet_or_an_unknown_format_is_left_alone(self) -> None:
        self.assertEqual(self.WITH_HELP, migration.add_applet(self.WITH_HELP))
        for value in ("@as []", "[]", "not a list", "['panel1:right']", "[1, 2]", "['a', "):
            with self.subTest(value=value):
                self.assertIsNone(migration.add_applet(value))

    def test_only_a_second_panel(self) -> None:
        self.assertEqual("['panel2:right:0:systray@cinnamon.org:3', 'panel2:right:1:caramos-help@caramos:4']",
                         migration.add_applet("['panel2:right:0:systray@cinnamon.org:3']"))

    def test_system_defaults(self) -> None:
        source = f"[org/cinnamon]\nenabled-applets={self.STOCK}\npanels-height=['1:48']\n"
        updated = migration.updated_defaults(source)
        self.assertEqual(f"[org/cinnamon]\nenabled-applets={self.WITH_HELP}\npanels-height=['1:48']\n", updated)
        self.assertEqual(updated, migration.updated_defaults(updated))
        self.assertIsNone(migration.updated_defaults("[org/cinnamon]\npanels-height=['1:48']\n"))
        self.assertIsNone(migration.updated_defaults(f"[org/other]\nenabled-applets={self.STOCK}\n"))

    def run_migration(self, dry_run: bool, logged_in: bool = False) -> tuple[str, mock.Mock, mock.Mock]:
        with tempfile.TemporaryDirectory() as temp:
            applet = Path(temp) / "applet"
            applet.mkdir()
            (applet / "applet.js").write_text("", encoding="utf-8")
            defaults = Path(temp) / "01-caramos-task17-panel"
            defaults.write_text(f"[org/cinnamon]\nenabled-applets={self.STOCK}\n", encoding="utf-8")
            bus = Path(temp) / "bus"
            if logged_in:
                bus.touch()
            context = MigrationContext(dry_run=dry_run)
            with mock.patch.object(migration, "APPLET_DIR", applet), \
                    mock.patch.object(migration, "PANEL_DCONF_FILE", defaults), \
                    mock.patch.object(migration, "_desktop_users", return_value=[("caram", 1000, Path(temp))]), \
                    mock.patch.object(migration, "_session_bus", return_value=bus), \
                    mock.patch.object(migration, "_add_for_user") as add_for_user, \
                    mock.patch.object(context, "run_command") as run_command, \
                    mock.patch.object(context, "log"):
                migration.run(context)
            return defaults.read_text(encoding="utf-8"), run_command, add_for_user

    def test_run_updates_the_defaults_and_every_user(self) -> None:
        text, run_command, add_for_user = self.run_migration(dry_run=False)
        self.assertIn(HELP, text)
        run_command.assert_called_once_with(["dconf", "update"], allow_fail=True)
        self.assertEqual("caram", add_for_user.call_args.args[1])

    def test_no_dconf_update_under_a_running_session(self) -> None:
        # Cinnamon 6.6 crashes when the system database is rebuilt under it; gsettings changes the panel.
        text, run_command, add_for_user = self.run_migration(dry_run=False, logged_in=True)
        self.assertIn(HELP, text)
        run_command.assert_not_called()
        self.assertEqual("caram", add_for_user.call_args.args[1])

    def test_dry_run_changes_nothing(self) -> None:
        text, run_command, add_for_user = self.run_migration(dry_run=True)
        self.assertNotIn("caramos-help", text)
        run_command.assert_not_called()
        add_for_user.assert_not_called()

    def test_a_user_panel_is_set_once_through_gsettings(self) -> None:
        context = MigrationContext()
        answers = [subprocess.CompletedProcess([], 0, self.STOCK + "\n", ""), subprocess.CompletedProcess([], 0, "", "")]
        with mock.patch.object(migration.subprocess, "run", side_effect=answers) as run, \
                mock.patch.object(context, "log"):
            migration._add_for_user(context, "caram", 1000, Path("/home/caram"))
        set_call = run.call_args_list[1].args[0]
        self.assertEqual(["gsettings", "set", "org.cinnamon", "enabled-applets"], set_call[-5:-1])
        self.assertIn(HELP, set_call[-1])
        self.assertEqual(["runuser", "-u", "caram", "--"], set_call[:4])

        with_help = subprocess.CompletedProcess([], 0, self.WITH_HELP + "\n", "")
        with mock.patch.object(migration.subprocess, "run", side_effect=[with_help]) as run, \
                mock.patch.object(context, "log"):
            migration._add_for_user(context, "caram", 1000, Path("/home/caram"))
        self.assertEqual(1, run.call_count)   # read only

    def test_only_people_who_log_in_get_the_applet(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            accounts = [
                ("root", 0, home, "/bin/bash"),
                ("caram", 1000, home, "/bin/bash"),
                ("guest", 1001, "/nonexistent", "/bin/bash"),
                ("backup", 1002, home, "/usr/sbin/nologin"),
                ("earlyoom", 61876, "/", "/usr/sbin/nologin"),   # systemd DynamicUser of a service
                ("nobody", 65534, "/nonexistent", "/usr/sbin/nologin"),
            ]
            entries = [mock.Mock(pw_name=name, pw_uid=uid, pw_dir=path, pw_shell=shell) for name, uid, path, shell in accounts]
            with mock.patch.object(migration.pwd, "getpwall", return_value=entries):
                self.assertEqual([("caram", 1000, Path(home))], migration._desktop_users())

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).with_name("manifest.json")).read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["schema"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()
