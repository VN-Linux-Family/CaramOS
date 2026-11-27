"""After an update that changed it, the CaramOS Control Center of running Xfce sessions starts again (ticket H-1216).

The Control Center of Xfce runs for the whole session and reads its style when it starts, but loads the sound level of
the sound keys (osd.py) only at the first press. A computer that updated to caramos-ota 1.5.2-0caramos6 or newer while
someone worked drew the new slim sound level in the tall box of the old one, until the next login. preinst keeps the
checksums of the version being replaced; postinst (caramos_ota.control_center_restart) ends the running Control
Centers when the files changed, or when the version replaced is older than 1.5.2.2, and the panel plugin starts the
installed one three seconds later.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota import control_center_restart as ccr

ROOT = Path(__file__).resolve().parents[1]
DEBIAN = ROOT / "debian"
PLUGIN = ROOT.parent / "xfce4-caramos-plugin/src/caramos-control-center.c"

MD5SUMS = """\
11111111111111111111111111111111  usr/share/caramos-ota/xfce/caramos-control-center
22222222222222222222222222222222  usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc/osd.py
33333333333333333333333333333333  usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc/style.css
44444444444444444444444444444444  usr/share/locale/vi/LC_MESSAGES/caramos-control-center.mo
55555555555555555555555555555555  usr/share/caramos-ota/xfce/caramos-volume
66666666666666666666666666666666  usr/share/caramos-ota/xfce/panel-islands.css
77777777777777777777777777777777  usr/share/locale/vi/LC_MESSAGES/caramos-ota.mo
88888888888888888888888888888888  usr/lib/python3/dist-packages/caramos_ota/constants.py
"""


def snippet(script: Path, first: str, last: str) -> str:
    """The lines of a maintainer script from the one containing `first` to the next one that is `last`."""

    lines = script.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if first in line)
    end = next(index for index in range(start + 1, len(lines)) if lines[index] == last)
    return "\n".join(lines[start:end + 1]) + "\n"


class ControlCenterFilesTests(unittest.TestCase):
    def test_the_program_its_code_its_style_and_its_translations_count(self):
        self.assertEqual({
            "11111111111111111111111111111111  usr/share/caramos-ota/xfce/caramos-control-center",
            "22222222222222222222222222222222  usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc/osd.py",
            "33333333333333333333333333333333  usr/share/caramos-ota/xfce/control-center/caramos_xfce_cc/style.css",
            "44444444444444444444444444444444  usr/share/locale/vi/LC_MESSAGES/caramos-control-center.mo",
        }, ccr.control_center_sums(MD5SUMS))

    def test_a_file_with_a_longer_name_does_not_count(self):
        self.assertEqual(set(), ccr.control_center_sums(
            "11111111111111111111111111111111  usr/share/caramos-ota/xfce/caramos-control-center.bak\n"
            "22222222222222222222222222222222  usr/share/caramos-ota/xfce/control-center\n"))

    def test_an_update_that_changed_only_other_files_changed_nothing_here(self):
        after = MD5SUMS.replace("55555555555555555555555555555555", "5" * 31 + "a") \
                       .replace("77777777777777777777777777777777", "7" * 31 + "a") \
                       .replace("88888888888888888888888888888888", "8" * 31 + "a")
        self.assertFalse(ccr.files_changed(MD5SUMS, after))

    def test_a_changed_added_or_removed_file_is_a_change(self):
        self.assertTrue(ccr.files_changed(MD5SUMS, MD5SUMS.replace("3" * 32, "3" * 31 + "a")))
        self.assertTrue(ccr.files_changed(MD5SUMS, MD5SUMS + "9" * 32 + "  usr/share/caramos-ota/xfce/control-center/"
                                                              "caramos_xfce_cc/new.py\n"))
        self.assertTrue(ccr.files_changed(MD5SUMS, MD5SUMS.replace(
            "4" * 32 + "  usr/share/locale/vi/LC_MESSAGES/caramos-control-center.mo\n", "")))

    def test_without_the_old_list_it_is_a_change(self):
        self.assertTrue(ccr.files_changed(None, MD5SUMS))
        self.assertTrue(ccr.files_changed(MD5SUMS, None))


class ProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proc = Path(tempfile.mkdtemp())
        (self.proc / "1").mkdir()
        (self.proc / "1" / "root").symlink_to("/")
        (self.proc / "self").mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self.proc)

    def process(self, pid: int, *arguments: str) -> None:
        (self.proc / str(pid)).mkdir()
        (self.proc / str(pid) / "cmdline").write_bytes(b"".join(item.encode() + b"\0" for item in arguments))

    def test_the_control_centers_of_every_session_and_nothing_else(self):
        self.process(1332, "/usr/bin/python3", ccr.LAUNCHER, "--plug", "25165831")
        self.process(2001, "/usr/bin/python3", ccr.LAUNCHER, "--toggle")
        self.process(2002, "python3", "-I", ccr.LAUNCHER)
        self.process(1131, "/usr/lib/x86_64-linux-gnu/xfce4/panel/wrapper-2.0",
                     "/usr/lib/x86_64-linux-gnu/xfce4/panel/plugins/libcaramos-control-center.so", "5")
        self.process(3000, "/usr/bin/nano", ccr.LAUNCHER)  # someone reading it
        self.process(3001, "/usr/bin/python3", "/usr/share/caramos-ota/xfce/caramos-control-center.bak")
        (self.proc / "3002").mkdir()  # a kernel thread: an empty command line
        (self.proc / "3002" / "cmdline").write_bytes(b"")
        (self.proc / "3003").mkdir()  # it ended meanwhile: no command line any more
        self.assertEqual([1332, 2001, 2002], ccr.running_control_centers(self.proc))

    def kills(self, old_version: str, before: str | None, after: str, older: bool) -> list[tuple[int, int]]:
        self.process(1332, "/usr/bin/python3", ccr.LAUNCHER, "--plug", "25165831")
        self.process(1500, "/usr/bin/python3", ccr.LAUNCHER, "--plug", "41943047")  # a second user's session
        lists = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, lists)
        if before is not None:
            (lists / "before").write_text(before, encoding="utf-8")
        (lists / "after").write_text(after, encoding="utf-8")
        signals = []
        with mock.patch.object(ccr, "older_than_fix", return_value=older):
            ended = ccr.restart(old_version, lists / "before", lists / "after", self.proc,
                                lambda pid, number: signals.append((pid, number)))
        self.assertEqual([pid for pid, _ in signals], ended)
        return signals

    def test_an_update_that_changed_the_control_center_ends_each_running_one(self):
        self.assertEqual([(1332, signal.SIGTERM), (1500, signal.SIGTERM)],
                         self.kills("1.5.2.2-0caramos1", MD5SUMS, MD5SUMS.replace("2" * 32, "2" * 31 + "a"), False))

    def test_an_update_that_left_it_as_it_was_ends_nothing(self):
        self.assertEqual([], self.kills("1.5.2.2-0caramos1", MD5SUMS, MD5SUMS, False))

    def test_an_update_from_before_the_fix_ends_them_even_when_nothing_changed(self):
        # The sound level of 1.5.2-0caramos6 may already show in the old box (ticket H-1216).
        self.assertEqual([(1332, signal.SIGTERM), (1500, signal.SIGTERM)],
                         self.kills("1.5.2.1-0caramos1", MD5SUMS, MD5SUMS, True))

    def test_a_first_install_ends_nothing(self):
        self.assertEqual([], self.kills("", None, MD5SUMS, True))

    def test_without_the_old_checksums_they_start_again(self):
        self.assertEqual([(1332, signal.SIGTERM), (1500, signal.SIGTERM)],
                         self.kills("1.5.2.2-0caramos1", None, MD5SUMS, False))

    def test_a_chroot_ends_nothing(self):
        # Building the ISO: the processes listed are those of the computer that builds it.
        (self.proc / "1" / "root").unlink()
        (self.proc / "1" / "root").symlink_to(self.proc)
        self.assertEqual([], self.kills("1.5.2.1-0caramos1", MD5SUMS, MD5SUMS, True))

    def test_a_control_center_that_ended_meanwhile_is_no_error(self):
        self.process(1332, "/usr/bin/python3", ccr.LAUNCHER, "--plug", "25165831")

        def gone(pid: int, number: int) -> None:
            raise ProcessLookupError(pid)

        with mock.patch.object(ccr, "older_than_fix", return_value=True):
            self.assertEqual([], ccr.restart("1.5.2.1-0caramos1", proc=self.proc, kill=gone))


class VersionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dpkg"), "needs dpkg")
    def test_versions_before_the_fix(self):
        for version in ("1.3.3-0caramos1", "1.5.2-0caramos7", "1.5.2.1-0caramos1", "1.5.2.1-0caramos1~test3"):
            self.assertTrue(ccr.older_than_fix(version), version)
        for version in ("1.5.2.2-0caramos1~test1", "1.5.2.2-0caramos1", "1.5.2.2-0caramos2", "1.5.2.3-0caramos1",
                        "1.5.3-0caramos1"):
            self.assertFalse(ccr.older_than_fix(version), version)


class MainTests(unittest.TestCase):
    def test_nothing_fails_the_update(self):
        with mock.patch.object(ccr, "restart", side_effect=RuntimeError("no /proc")), \
                mock.patch("sys.stderr"):
            self.assertEqual(0, ccr.main(["--old-version", "1.5.2.1-0caramos1"]))
        with mock.patch("sys.stderr"):
            self.assertEqual(0, ccr.main(["--no-such-option"]))

    def test_it_says_how_many_started_again(self):
        with mock.patch.object(ccr, "restart", return_value=[1332, 1500]) as restart, \
                mock.patch("builtins.print") as printed:
            self.assertEqual(0, ccr.main(["--old-version", "1.5.2.1-0caramos1"]))
        restart.assert_called_once_with("1.5.2.1-0caramos1")
        self.assertIn("2 session(s)", printed.call_args.args[0])


class MaintainerScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.info = self.root / "var/lib/dpkg/info"
        self.info.mkdir(parents=True)
        self.before = self.root / "run/caramos-ota/control-center-before.md5sums"

    def run_sh(self, code: str, *arguments: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(["sh", "-e", "-c", code, "script", *arguments], capture_output=True, text=True,
                              check=False, env={**os.environ, "DPKG_ROOT": str(self.root), **(env or {})})

    def preinst(self) -> str:
        return snippet(DEBIAN / "preinst", "# The CaramOS Control Center of Xfce runs", "esac")

    def test_preinst_keeps_the_checksums_of_the_version_being_replaced(self):
        (self.info / "caramos-ota.md5sums").write_text(MD5SUMS, encoding="utf-8")
        result = self.run_sh(self.preinst(), "upgrade", "1.5.2.1-0caramos1", "1.5.2.2-0caramos1")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(MD5SUMS, self.before.read_text(encoding="utf-8"))

    def test_preinst_never_fails_and_leaves_no_old_copy(self):
        self.before.parent.mkdir(parents=True)
        self.before.write_text("old", encoding="utf-8")
        result = self.run_sh(self.preinst(), "upgrade", "1.5.2.1-0caramos1", "1.5.2.2-0caramos1")  # no md5sums
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.before.exists())

    def test_preinst_keeps_nothing_on_a_first_install(self):
        (self.info / "caramos-ota.md5sums").write_text(MD5SUMS, encoding="utf-8")
        result = self.run_sh(self.preinst(), "install")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(self.before.exists())

    def postinst(self) -> str:
        return snippet(DEBIAN / "postinst", "# The CaramOS Control Center of running Xfce sessions", "        rm -f "
                       '"$DPKG_ROOT/run/caramos-ota/control-center-before.md5sums" || true')

    def run_postinst(self, *arguments: str, dpkg_root: str) -> tuple[subprocess.CompletedProcess, str]:
        stubs = self.root / "bin"
        stubs.mkdir(exist_ok=True)
        calls = self.root / "python3-calls"
        stub = stubs / "python3"
        stub.write_text(f'#!/bin/sh\necho "$*" >> "{calls}"\nexit 3\n', encoding="utf-8")
        stub.chmod(0o755)
        self.before.parent.mkdir(parents=True, exist_ok=True)
        self.before.write_text(MD5SUMS, encoding="utf-8")
        code = f'DPKG_ROOT="{dpkg_root}"\n' + self.postinst().replace(
            '"$DPKG_ROOT/run/caramos-ota/', f'"{self.root}/run/caramos-ota/')
        result = self.run_sh(code, *arguments, env={"PATH": f"{stubs}:{os.environ['PATH']}"})
        return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

    def test_postinst_asks_for_the_restart_after_an_upgrade_and_never_fails(self):
        result, calls = self.run_postinst("configure", "1.5.2.1-0caramos1", dpkg_root="")
        self.assertEqual(0, result.returncode, result.stderr)  # the stub fails with 3
        self.assertEqual("-I -m caramos_ota.control_center_restart --old-version 1.5.2.1-0caramos1\n", calls)
        self.assertFalse(self.before.exists())

    def test_postinst_does_not_ask_on_a_first_install_or_in_another_root(self):
        self.assertEqual("", self.run_postinst("configure", "", dpkg_root="")[1])
        self.assertEqual("", self.run_postinst("configure", "1.5.2.1-0caramos1", dpkg_root="/target")[1])


class PanelPluginTests(unittest.TestCase):
    @unittest.skipUnless(PLUGIN.exists(), "needs the xfce4-caramos-plugin source")
    def test_the_panel_plugin_starts_the_control_center_again_when_it_ends(self):
        source = PLUGIN.read_text(encoding="utf-8")
        self.assertIn("#define RESTART_SECONDS 3", source)
        self.assertIn('g_signal_connect (cc->socket, "plug-removed", G_CALLBACK (plug_removed), cc);', source)
        self.assertIn("g_child_watch_add (cc->pid, control_center_exited, cc);", source)

    def test_the_launcher_is_the_one_the_panel_plugin_starts(self):
        launcher = ROOT / ccr.LAUNCHER.lstrip("/")
        self.assertTrue(launcher.exists())
        self.assertEqual("#!/usr/bin/python3", launcher.read_text(encoding="utf-8").splitlines()[0])


if __name__ == "__main__":
    unittest.main()
