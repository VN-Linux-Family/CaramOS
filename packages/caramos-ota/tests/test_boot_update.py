"""The update at the next start (caramos_ota.auto_update.boot_run): an update that waited because someone was logged
in installs before the login screen. Computers on CaramOS 1.3.3 or older never updated by themselves before it."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota import auto_update, cli, manifest
from caramos_ota.constants import EXIT_APT, EXIT_LATER, EXIT_REPO
from caramos_ota.models import ReleaseInfo
from caramos_ota_update import cli as update_cli
from caramos_ota_update import runner as runner_module
from caramos_ota_update.registry import ANYTIME, NOBODY_LOGGED_IN, MigrationDescriptor
from caramos_ota_update.runner import DEADLINE_ENV, MigrationRunner, MigrationsLeftForLater

ROOT = Path(__file__).parents[1]

# A 1.3.3 computer: the update to the newest CaramOS includes migrations that wait for nobody to be logged in.
UPDATE = {"release": "1.5.2.1", "current_version": "1.3.3",
          "migration_ids": ["20261105120000_keep_lotus_settings", "20261126200100_xfce_notifications_bottom_right"],
          "packages": [{"name": "Bộ gõ giữ cài đặt của bạn"}]}


def plan(*ids: str) -> SimpleNamespace:
    return SimpleNamespace(migrations=[SimpleNamespace(migration_id=item, unattended=NOBODY_LOGGED_IN, desktops=())
                                       for item in ids], target_version="1.5.2.1")


def unit(path: Path) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), []).append(value.strip())
    return values


class StateCase(unittest.TestCase):
    """state.json, the result and the flag files in a temporary folder; the update itself patched."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(self.tmp)], check=False))
        self.state = {"schema": 2, "available_update": dict(UPDATE), "transactions": []}
        self.messages: list[str] = []
        patches = [
            mock.patch.object(auto_update, "is_enabled", return_value=True),
            mock.patch("caramos_ota.state.load_state", side_effect=lambda: json.loads(json.dumps(self.state))),
            mock.patch("caramos_ota.state.save_state", side_effect=self.save),
            mock.patch("caramos_ota.release.detect_caramos",
                       return_value=SimpleNamespace(version="1.3.3", codename="noble", channel="stable")),
            mock.patch("caramos_ota.manifest.resolve_update_plan", return_value=plan(*UPDATE["migration_ids"])),
            mock.patch.object(auto_update, "skip_reason", return_value=None),
            mock.patch.object(auto_update, "wait_for_network", return_value=True),
            mock.patch.object(auto_update, "boot_message", side_effect=self.messages.append),
            mock.patch.object(auto_update, "system_language", return_value="vi"),
            mock.patch.object(auto_update, "RESULT_FILE", self.tmp / "auto-update.json"),
            mock.patch.object(auto_update, "REBOOT_REQUIRED", self.tmp / "reboot-required"),
            mock.patch.object(auto_update, "BOOT_FLAG", self.tmp / "boot-update-pending"),
            mock.patch.object(auto_update, "BOOT_GAVE_UP", self.tmp / "boot-update-gave-up"),
            mock.patch.object(auto_update, "log_info"),
            mock.patch.object(auto_update, "log_warn"),
            mock.patch.object(auto_update, "log_error"),
            mock.patch("builtins.print"),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, state) -> None:
        self.state = json.loads(json.dumps(state))

    def last_try(self) -> dict:
        return self.state[auto_update.STATUS_KEY]

    def flag(self) -> dict | None:
        return auto_update.read_boot_flag()

    def leave_flag(self, tries: int = 0, update: dict | None = None) -> None:
        auto_update.write_boot_flag(update or UPDATE, tries)

    def result(self) -> dict:
        return json.loads((self.tmp / "auto-update.json").read_text(encoding="utf-8"))


class LeaveForStartTests(StateCase):
    """caramos-ota --auto-upgrade while someone works."""

    def test_an_update_that_waits_for_open_desktops_is_left_for_the_next_start(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.IN_USE, "keep_lotus would change open desktops")
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.run())
        upgrade.assert_not_called()
        self.assertEqual({"update": auto_update.update_key(UPDATE), "tries": 0}, {
            key: self.flag()[key] for key in ("update", "tries")})
        self.assertEqual((auto_update.SKIPPED, auto_update.IN_USE), (self.last_try()["outcome"],
                                                                      self.last_try()["reason"]))
        self.assertEqual(0o644, (self.tmp / "boot-update-pending").stat().st_mode & 0o777)

    def test_the_same_update_keeps_its_tries_and_a_new_one_starts_again(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.IN_USE, "x")
        self.leave_flag(tries=2)
        auto_update.run()
        self.assertEqual(2, self.flag()["tries"])
        self.state["available_update"] = dict(UPDATE, release="1.5.2.2")
        auto_update.run()
        self.assertEqual((0, "1.5.2.2"), (self.flag()["tries"], self.flag()["release"]))

    def test_an_update_starts_gave_up_is_left_to_the_update_center(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.IN_USE, "x")
        auto_update.give_up_at_start(UPDATE)
        auto_update.run()
        self.assertIsNone(self.flag())
        self.assertEqual(auto_update.GAVE_UP, self.last_try()["reason"])

    def test_other_reasons_leave_nothing_for_the_start(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.METERED, "metered")
        auto_update.run()
        self.assertIsNone(self.flag())

    def test_an_update_installed_meanwhile_takes_the_flag_away(self) -> None:
        self.leave_flag()
        with mock.patch.object(auto_update, "run_upgrade", return_value=(0, "Update complete.\n")):
            self.assertEqual(0, auto_update.run())
        self.assertIsNone(self.flag())


class BootRunTests(StateCase):
    """caramos-ota --boot-update at a start."""

    def test_without_the_flag_nothing_happens(self) -> None:
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.boot_run())
        upgrade.assert_not_called()
        self.assertEqual([], self.messages)

    def test_automatic_updates_off_or_no_update_any_more_take_the_flag_away(self) -> None:
        for change in ("off", "none"):
            with self.subTest(change=change):
                self.leave_flag()
                auto_update.is_enabled.return_value = change != "off"
                self.state["available_update"] = None if change == "none" else dict(UPDATE)
                with mock.patch.object(auto_update, "run_upgrade") as upgrade:
                    self.assertEqual(0, auto_update.boot_run())
                upgrade.assert_not_called()
                self.assertIsNone(self.flag())

    def test_the_update_installs_before_the_login_screen(self) -> None:
        self.leave_flag()
        calls = []

        def upgrade(language, environment_extra=None, progress=None):
            calls.append((language, environment_extra, progress))
            return 0, "Update complete.\n"

        before = time.time()
        with mock.patch.object(auto_update, "run_upgrade", side_effect=upgrade):
            self.assertEqual(0, auto_update.boot_run())
        language, extra, progress = calls[0]
        self.assertEqual("vi", language)
        limit = float(extra[DEADLINE_ENV])
        self.assertAlmostEqual(before + auto_update.BOOT_MINUTES * 60, limit, delta=5)
        self.assertTrue(callable(progress))
        # Open desktops cannot stop it: nobody can be logged in yet.
        self.assertTrue(auto_update.skip_reason.call_args.kwargs["at_start"])
        self.assertEqual(auto_update.DONE, self.result()["outcome"])
        self.assertEqual(("1.3.3", "1.5.2.1"), (self.result()["from_version"], self.result()["to_version"]))
        self.assertEqual(auto_update.DONE, self.last_try()["outcome"])
        self.assertIsNone(self.flag())
        self.assertEqual([auto_update.boot_screen("vi", "preparing"), auto_update.BOOT_TEXTS["vi"]["done"]],
                         self.messages)

    def test_each_start_that_begins_counts_before_the_update_runs(self) -> None:
        self.leave_flag(tries=1)
        seen = []
        with mock.patch.object(auto_update, "run_upgrade",
                               side_effect=lambda *a, **k: seen.append(self.flag()["tries"]) or (EXIT_LATER, "")):
            auto_update.boot_run()
        self.assertEqual([2], seen)

    def test_the_time_limit_leaves_the_rest_for_the_next_start(self) -> None:
        self.leave_flag()
        with mock.patch.object(auto_update, "run_upgrade", return_value=(EXIT_LATER, "Stopped at the time limit")):
            self.assertEqual(0, auto_update.boot_run())
        self.assertEqual(1, self.flag()["tries"])
        self.assertEqual((auto_update.SKIPPED, auto_update.TIME_LIMIT), (self.last_try()["outcome"],
                                                                          self.last_try()["reason"]))
        self.assertFalse((self.tmp / "auto-update.json").exists())

    def test_no_network_or_no_ppa_leaves_it_for_the_next_start(self) -> None:
        self.leave_flag()
        auto_update.wait_for_network.return_value = False
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.boot_run())
        upgrade.assert_not_called()
        self.assertEqual((1, auto_update.NO_NETWORK), (self.flag()["tries"], self.last_try()["reason"]))
        auto_update.wait_for_network.return_value = True
        for code in (EXIT_REPO, EXIT_APT):
            with self.subTest(code=code), mock.patch.object(auto_update, "run_upgrade", return_value=(code, "")):
                self.assertEqual(0, auto_update.boot_run())
                self.assertEqual(auto_update.NO_NETWORK, self.last_try()["reason"])
                self.assertIsNotNone(self.flag())

    def test_a_failure_waits_for_the_update_center(self) -> None:
        self.leave_flag()
        with mock.patch.object(auto_update, "run_upgrade", return_value=(1, "Error: Migration update failed.")):
            self.assertEqual(1, auto_update.boot_run())
        self.assertEqual(auto_update.FAILED, self.result()["outcome"])
        self.assertIsNone(self.flag())

    def test_three_starts_without_the_update_finished_give_it_up(self) -> None:
        self.leave_flag(tries=auto_update.BOOT_TRIES)
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.boot_run())
        upgrade.assert_not_called()
        self.assertIsNone(self.flag())
        self.assertEqual(auto_update.update_key(UPDATE),
                         json.loads((self.tmp / "boot-update-gave-up").read_text(encoding="utf-8"))["update"])
        self.assertEqual(auto_update.GAVE_UP, self.last_try()["reason"])
        self.assertFalse(auto_update.leave_for_start(UPDATE))

    def test_a_flag_for_an_older_update_starts_counting_again(self) -> None:
        self.leave_flag(tries=auto_update.BOOT_TRIES, update=dict(UPDATE, release="1.5.2"))
        with mock.patch.object(auto_update, "run_upgrade", return_value=(0, "")) as upgrade:
            auto_update.boot_run()
        upgrade.assert_called_once()

    def test_reasons_to_wait_at_a_start(self) -> None:
        for reason, keeps in ((auto_update.METERED, True), (auto_update.BATTERY, True), (auto_update.APT_BUSY, True),
                              (auto_update.FAILED_BEFORE, False), (auto_update.LIVE, False),
                              (auto_update.OVERLAY, False)):
            with self.subTest(reason=reason):
                self.leave_flag()
                auto_update.skip_reason.return_value = (reason, "detail")
                with mock.patch.object(auto_update, "run_upgrade") as upgrade:
                    self.assertEqual(0, auto_update.boot_run())
                upgrade.assert_not_called()
                self.assertEqual(keeps, self.flag() is not None)
                if keeps:
                    self.assertEqual(0, self.flag()["tries"])   # nothing began: not a try
                self.assertEqual(reason, self.last_try()["reason"])
                auto_update.clear_boot_flag()


class StartConditionTests(unittest.TestCase):
    def test_open_desktops_do_not_count_at_a_start_and_apt_gets_a_minute(self) -> None:
        checks = {"live_session": False, "overlay_root": False, "ota_busy": False, "metered": False,
                  "battery_low": False, "low_disk": []}
        pending = plan("20261105120000_keep_lotus_settings")
        with mock.patch.multiple(auto_update, **{name: mock.Mock(return_value=value) for name, value in checks.items()}), \
                mock.patch.object(auto_update, "desktop_sessions", return_value=["caram"]) as sessions, \
                mock.patch.object(auto_update, "apt_busy", side_effect=[True, False]), \
                mock.patch.object(auto_update, "wait_for_apt", return_value=True) as wait_apt:
            self.assertIsNone(auto_update.skip_reason(UPDATE, pending, {}, at_start=True))
            sessions.assert_not_called()
            wait_apt.assert_called_once()
            self.assertEqual(auto_update.IN_USE, auto_update.skip_reason(UPDATE, pending, {})[0])

    def test_wait_for_apt(self) -> None:
        sleeps = []
        self.assertTrue(auto_update.wait_for_apt(60, busy=iter([True, True, False]).__next__, sleep=sleeps.append))
        self.assertEqual([3, 3], sleeps)
        self.assertFalse(auto_update.wait_for_apt(6, busy=lambda: True, sleep=lambda _s: None))


class StartScreenTests(unittest.TestCase):
    def test_the_line_under_the_start_up_animation(self) -> None:
        run = mock.Mock()
        with mock.patch("builtins.print") as printed:
            auto_update.boot_message("Đang cập nhật CaramOS", run=run)
        self.assertEqual(["plymouth", "display-message", "--text=Đang cập nhật CaramOS"], run.call_args.args[0])
        printed.assert_called_once_with("Đang cập nhật CaramOS", flush=True)
        with mock.patch("builtins.print"):
            auto_update.boot_message("x", run=mock.Mock(side_effect=FileNotFoundError("plymouth")))

    def test_the_screen_says_it_happens_only_once(self) -> None:
        self.assertEqual("Đang bắt đầu cập nhật CaramOS. Đừng tắt máy.\nViệc này diễn ra một lần duy nhất trên máy "
                         "dùng CaramOS cũ. Xong lần này, bạn sẽ không gặp lại màn hình này nữa.",
                         auto_update.boot_screen("vi", "preparing"))
        self.assertIn("only once", auto_update.boot_screen("en", "progress", done=1, total=2))

    def test_no_letter_the_start_up_font_cannot_draw(self) -> None:
        # The initramfs's Ubuntu font has no combining hook above (U+0309): "chỉ", "để", "bản" showed boxes on the
        # VM's start-up screen. Letters with the other marks are drawn from the letter and its combining mark.
        import unicodedata

        for language, texts in auto_update.BOOT_TEXTS.items():
            for key, text in texts.items():
                with self.subTest(language=language, key=key):
                    hooked = [ch for ch in unicodedata.normalize("NFD", text) if ch == "\u0309"]
                    self.assertEqual([], hooked, text)

    def test_texts_in_both_languages(self) -> None:
        self.assertEqual("Đang cập nhật CaramOS: xong 3/12 bước. Đừng tắt máy.",
                         auto_update.boot_text("vi", "progress", done=3, total=12))
        self.assertEqual("Updating CaramOS: 3 of 12 steps done. Do not turn off the computer.",
                         auto_update.boot_text("en", "progress", done=3, total=12))
        self.assertEqual(auto_update.BOOT_TEXTS["en"]["preparing"], auto_update.boot_text("fr", "preparing"))

    def test_progress_counts_the_ledger_and_shows_each_change_once(self) -> None:
        shown = []
        done = iter([0, 0, 1, 2])
        with mock.patch.object(auto_update, "migrations_done", side_effect=lambda ids: next(done)), \
                mock.patch.object(auto_update, "boot_message", side_effect=shown.append):
            update = auto_update.boot_progress(["a", "b"], "vi")
            for _ in range(4):
                update()
        once = auto_update.BOOT_TEXTS["vi"]["once"]
        self.assertEqual([f"Đang cập nhật CaramOS: xong {done}/2 bước. Đừng tắt máy.\n{once}" for done in (0, 1, 2)],
                         shown)

    def test_migrations_done_reads_the_ledger(self) -> None:
        ledger = {"schema": 1, "applied_migrations": [{"id": "a"}, {"id": "c"}]}
        with mock.patch("caramos_ota_update.ledger.load_ledger", return_value=ledger):
            self.assertEqual(1, auto_update.migrations_done(["a", "b"]))
        with mock.patch("caramos_ota_update.ledger.load_ledger", side_effect=RuntimeError("broken")):
            self.assertEqual(0, auto_update.migrations_done(["a"]))

    def test_network_through_nm_online(self) -> None:
        run = mock.Mock(return_value=SimpleNamespace(returncode=0))
        self.assertTrue(auto_update.wait_for_network(45, run=run))
        self.assertEqual(["nm-online", "-q", "-t", "45"], run.call_args.args[0])
        self.assertFalse(auto_update.wait_for_network(45, run=mock.Mock(return_value=SimpleNamespace(returncode=1))))
        self.assertFalse(auto_update.wait_for_network(45, run=mock.Mock(side_effect=FileNotFoundError("nm-online"))))

    def test_the_update_runs_with_its_time_limit_and_shows_progress(self) -> None:
        inhibitor = mock.Mock(pid=4242)
        child = mock.Mock()
        child.poll.side_effect = [None, None, 0]
        child.returncode = 0

        def popen(command, **kwargs):
            if command[0] == "systemd-inhibit":
                return inhibitor
            kwargs["stdout"].write("Update complete.\n")
            popen.env = kwargs["env"]
            popen.command = command
            return child

        progress = mock.Mock()
        with mock.patch.object(auto_update.subprocess, "Popen", side_effect=popen), \
                mock.patch.object(auto_update.os, "killpg"), mock.patch.object(auto_update.time, "sleep"):
            code, output = auto_update.run_upgrade("vi", environment_extra={DEADLINE_ENV: "123"}, progress=progress)
        self.assertEqual((0, "Update complete.\n"), (code, output))
        self.assertEqual(["/usr/bin/caramos-ota", "--upgrade", "--yes", "--unattended"], popen.command)
        self.assertEqual("123", popen.env[DEADLINE_ENV])
        self.assertEqual("noninteractive", popen.env["DEBIAN_FRONTEND"])
        self.assertEqual(3, progress.call_count)


class RunnerTimeLimitTests(unittest.TestCase):
    """caramos-ota-update stops between two migrations once the start-up update's time is up."""

    def descriptor(self, migration_id: str, desktops: tuple[str, ...] = ()) -> MigrationDescriptor:
        return MigrationDescriptor(migration_id=migration_id, release=None, description=migration_id, source="test",
                                   directory=Path("/nonexistent"), module_path=Path("/nonexistent/migration.py"),
                                   schema=2, codename="noble", channel="stable", severity="normal", size="",
                                   title=migration_id, summary="", release_notes_vi=[], release_notes_en=[],
                                   desktops=desktops, unattended=ANYTIME)

    def run_runner(self, migrations, environ):
        context = mock.MagicMock()
        context.dry_run = False
        runner = MigrationRunner(context=context)
        ran = []
        with mock.patch.object(runner_module, "bootstrap_ledger", return_value={"schema": 1,
                                                                                "applied_migrations": []}), \
                mock.patch.object(runner_module, "discover_migrations", return_value=migrations), \
                mock.patch.object(runner_module, "resolve_plan",
                                  return_value=SimpleNamespace(migrations=migrations, target_version="1.5.2.1")), \
                mock.patch.object(runner_module, "start_transaction", return_value="txn"), \
                mock.patch.object(runner_module, "mark_migration_running"), \
                mock.patch.object(runner_module, "mark_migration_complete"), \
                mock.patch.object(runner_module, "mark_applied", side_effect=lambda ledger, item: ran.append(
                    item.migration_id)), \
                mock.patch.object(runner_module, "mark_transaction_success") as success, \
                mock.patch.object(runner_module, "mark_transaction_stopped") as stopped, \
                mock.patch.object(runner, "_run_one"), \
                mock.patch.dict(os.environ, dict(environ, CARAMOS_OTA_DESKTOP="cinnamon"), clear=False):
            try:
                runner.run(current_version="1.3.3", target_version="1.5.2.1")
                left = None
            except MigrationsLeftForLater as exc:
                left = str(exc)
        return ran, left, success, stopped

    def test_without_a_limit_everything_runs(self) -> None:
        items = [self.descriptor("a"), self.descriptor("b")]
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(DEADLINE_ENV, None)
            ran, left, success, stopped = self.run_runner(items, {})
        self.assertEqual((["a", "b"], None), (ran, left))
        success.assert_called_once()
        stopped.assert_not_called()

    def test_past_the_limit_no_migration_starts_and_the_done_ones_stay_done(self) -> None:
        items = [self.descriptor("a"), self.descriptor("b")]
        ran, left, success, stopped = self.run_runner(items, {DEADLINE_ENV: str(time.time() - 1)})
        self.assertEqual([], ran)
        self.assertIn("2 migration(s) left", left)
        success.assert_not_called()
        stopped.assert_called_once()

    def test_the_other_editions_migrations_are_recorded_even_past_the_limit(self) -> None:
        items = [self.descriptor("xfce-only", ("xfce",)), self.descriptor("b")]
        ran, left, _success, _stopped = self.run_runner(items, {DEADLINE_ENV: str(time.time() - 1)})
        self.assertEqual(["xfce-only"], ran)
        self.assertIn("1 migration(s) left", left)

    def test_a_broken_limit_is_no_limit(self) -> None:
        self.assertIsNone(runner_module.deadline({DEADLINE_ENV: "soon"}))
        self.assertIsNone(runner_module.deadline({}))
        self.assertEqual(12.0, runner_module.deadline({DEADLINE_ENV: "12"}))

    def test_the_runner_cli_says_the_rest_comes_later(self) -> None:
        with mock.patch.object(update_cli, "init_log"), mock.patch.object(update_cli, "acquire_lock"), \
                mock.patch.object(update_cli, "log_info"), \
                mock.patch.object(update_cli, "_read_current_version", return_value="1.3.3"), \
                mock.patch.object(update_cli, "_current_release_values", return_value={}), \
                mock.patch.object(update_cli, "MigrationRunner") as runner, mock.patch("builtins.print"):
            runner.return_value.run.side_effect = MigrationsLeftForLater("1 migration(s) left")
            self.assertEqual(EXIT_LATER, update_cli.main(["--lock-fd", "9"]))

    def test_the_upgrade_passes_the_code_on(self) -> None:
        with mock.patch.object(cli, "current_lock_fd", return_value=9), \
                mock.patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=EXIT_LATER)), \
                mock.patch.object(cli, "log_info"), mock.patch("builtins.print"):
            with self.assertRaises(SystemExit) as stopped:
                cli.run_migration_update("1.5.2.1", dry_run=False, unattended=True)
        self.assertEqual(EXIT_LATER, stopped.exception.code)


class CliTests(unittest.TestCase):
    def test_boot_update_runs_the_update_at_start_without_the_lock(self) -> None:
        parser = cli.build_parser()
        self.assertEqual("boot_update", cli.selected_action(parser.parse_args(["--boot-update"])))
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock") as lock, mock.patch.object(cli, "log_info"), \
                mock.patch.object(cli.auto_update, "boot_run", return_value=0) as boot_run, \
                mock.patch.object(cli.auto_update, "run") as run:
            self.assertEqual(0, cli.main(["--boot-update"]))
        boot_run.assert_called_once()
        run.assert_not_called()
        lock.assert_not_called()


class PackagingTests(unittest.TestCase):
    def test_the_unit_runs_before_anyone_can_log_in(self) -> None:
        service = unit(ROOT / "lib/systemd/system/caramos-ota-boot-update.service")
        self.assertEqual([str(auto_update.BOOT_FLAG)], service["ConditionPathExists"])
        self.assertEqual(["!boot=casper"], service["ConditionKernelCommandLine"])
        self.assertEqual(["/usr/bin/caramos-ota --boot-update"], service["ExecStart"])
        before = " ".join(service["Before"]).split()
        for name in ("systemd-user-sessions.service", "display-manager.service", "caramos-ota-check.service",
                     "caramos-ota-auto-update.service", "caramos-ota-dconf-update.service"):
            self.assertIn(name, before)
        # Not after network-online.target: every start without the flag would wait for the network.
        self.assertEqual(["local-fs.target NetworkManager.service"], service["After"])
        self.assertEqual(["oneshot"], service["Type"])
        self.assertEqual(["mixed"], service["KillMode"])
        self.assertEqual(["multi-user.target"], service["WantedBy"])
        minutes = int(service["TimeoutStartSec"][0].removesuffix("min"))
        self.assertGreater(minutes, auto_update.BOOT_MINUTES + 15)

    def test_the_package_enables_it_and_never_starts_or_stops_it(self) -> None:
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        self.assertIn("dh_installsystemd --no-start --no-stop-on-upgrade caramos-ota-boot-update.service\n", rules)
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertIn("lib/systemd/system/caramos-ota-boot-update.service lib/systemd/system/\n", install)

    def test_the_update_center_words_the_new_reasons(self) -> None:
        from caramos_ota_notifier import ui

        for reason in (auto_update.IN_USE, auto_update.NO_NETWORK, auto_update.TIME_LIMIT, auto_update.GAVE_UP):
            self.assertIn(reason, auto_update.REASONS)
            self.assertTrue(ui.waiting_text(reason))
        self.assertIn("next start", ui.waiting_text(auto_update.IN_USE))


class HotfixNotesTests(unittest.TestCase):
    """A version that changes only CaramOS's own programs shows its own notes (release_metadata)."""

    def build(self, descriptors, current="1.5.2", target="1.5.2.1"):
        release = ReleaseInfo(name="CaramOS", version=current, codename="noble", channel="stable")
        with mock.patch.object(manifest, "PRODUCT_VERSION", "1.5.2.1"), \
                mock.patch.object(manifest, "RELEASE_TITLE_VI", "Máy cũ tự cập nhật lúc khởi động"), \
                mock.patch.object(manifest, "RELEASE_TITLE_EN", "Older computers update at start-up"), \
                mock.patch.object(manifest, "RELEASE_NOTES_VI", ("Ghi chú 1",)), \
                mock.patch.object(manifest, "RELEASE_NOTES_EN", ("Note 1",)), \
                mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "cinnamon"}):
            return manifest._manifest_from_descriptors(descriptors, release, target)

    def test_a_version_only_update_says_what_it_brings(self) -> None:
        built = self.build([])
        self.assertEqual("Máy cũ tự cập nhật lúc khởi động", built.title)
        self.assertEqual("Older computers update at start-up", built.title_en)
        self.assertEqual(["Ghi chú 1"], built.release_notes_vi)
        self.assertEqual(["Note 1"], built.release_notes_en)
        self.assertEqual("CaramOS đã được cập nhật", self.build([], current="1.5.2.1").title)
        self.assertEqual("Cập nhật CaramOS", self.build([], target="1.5.3").title)

    def test_the_shipped_metadata_is_consistent(self) -> None:
        from caramos_ota import release_metadata

        self.assertEqual(bool(release_metadata.RELEASE_NOTES_VI), bool(release_metadata.RELEASE_TITLE_VI))
        self.assertEqual(len(release_metadata.RELEASE_NOTES_VI), len(release_metadata.RELEASE_NOTES_EN))


if __name__ == "__main__":
    unittest.main()
