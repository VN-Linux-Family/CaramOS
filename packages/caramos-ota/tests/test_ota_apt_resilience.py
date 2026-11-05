"""The Update Center against a system it does not own (tickets H-1100, H-1102, H-1105):

- a software source added by another program that no longer works fails `apt-get update`; the CaramOS PPA is
  updated alone and the update goes on;
- a package dpkg could not finish fails every `apt-get install`; the OTA engine counts as updated when it
  was installed anyway, and the CaramOS Lotus package is upgraded along with it when that is the one.
"""

from __future__ import annotations

import io
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from caramos_ota import apt, cli

GITHUB_IO_FAILURE = """E: Failed to fetch https://github.io/./InRelease  Clearsigned file is not valid, got 'NOSPLIT' (does the network require authentication?)
E: The repository 'https://github.io ./ InRelease' is not signed.
"""
PPA_FAILURE = """E: Failed to fetch https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu/dists/noble/InRelease  Could not resolve 'ppa.launchpadcontent.net'
"""
PPA_SOURCES = """Types: deb
URIs: https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu
Suites: noble
Components: main
Signed-By: /usr/share/keyrings/caramos-archive-keyring.gpg
"""


def done(code: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, "", stderr)


class FailedSourcesTests(unittest.TestCase):
    def test_reads_the_sources_out_of_apt_errors(self) -> None:
        self.assertEqual(["https://github.io"], apt.failed_sources(GITHUB_IO_FAILURE))
        self.assertEqual(["https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu"],
                         apt.failed_sources(PPA_FAILURE))
        self.assertEqual(["http://archive.example.org/ubuntu"], apt.failed_sources(
            "W: Failed to fetch http://archive.example.org/ubuntu/dists/noble/main/binary-amd64/Packages  404\n"))
        self.assertEqual([], apt.failed_sources("E: Could not get lock /var/lib/apt/lists/lock\n"))


class AptUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root / "sources.list.d").mkdir()
        (root / "sources.list").write_text("# see sources.list.d\n", encoding="utf-8")
        (root / "sources.list.d/caramos-ppa.sources").write_text(PPA_SOURCES, encoding="utf-8")
        (root / "sources.list.d/broken-guide.list").write_text("deb https://github.io ./\n", encoding="utf-8")
        for name, value in (("APT_SOURCES_LIST", root / "sources.list"), ("APT_SOURCES_DIR", root / "sources.list.d")):
            patcher = mock.patch.object(apt, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.calls: list[list[str]] = []
        self.copied: list[str] = []

    def fake_update(self, results):
        answers = iter(results)

        def update(extra):
            self.calls.append(extra)
            parts = next((item.split("=", 1)[1] for item in extra if item.startswith("Dir::Etc::SourceParts=")), "")
            if parts:
                self.copied = sorted(path.name for path in Path(parts).iterdir())
            return next(answers)
        return update

    def test_a_broken_source_of_another_program_is_skipped(self) -> None:
        with mock.patch.object(apt, "_apt_get_update", side_effect=self.fake_update([done(100, GITHUB_IO_FAILURE), done(0)])), \
                mock.patch.object(apt, "log_warn") as warn, redirect_stdout(io.StringIO()) as out:
            apt.apt_update()
        self.assertEqual(2, len(self.calls))
        self.assertIn("APT::Get::List-Cleanup=0", self.calls[1])
        self.assertEqual(["caramos-ppa.sources"], self.copied)
        self.assertIn("https://github.io", warn.call_args.args[0])
        self.assertIn("broken-guide.list", warn.call_args.args[0])
        self.assertIn("the CaramOS update goes on", out.getvalue())

    def test_a_failed_caramos_ppa_still_stops_the_update(self) -> None:
        for results in ([done(100, PPA_FAILURE)], [done(100, GITHUB_IO_FAILURE), done(100, PPA_FAILURE)],
                        [done(100, "E: Could not get lock /var/lib/apt/lists/lock\n")]):
            self.calls = []
            with mock.patch.object(apt, "_apt_get_update", side_effect=self.fake_update(results)), \
                    redirect_stdout(io.StringIO()) as out, self.assertRaises(SystemExit):
                apt.apt_update()
            self.assertIn("Failed to update package index", out.getvalue())

    def test_a_clean_update_runs_once(self) -> None:
        with mock.patch.object(apt, "_apt_get_update", side_effect=self.fake_update([done(0)])), \
                redirect_stdout(io.StringIO()):
            apt.apt_update()
        self.assertEqual([[]], self.calls)


class CandidateVersionTests(unittest.TestCase):
    def test_apt_cache_runs_in_english_on_a_vietnamese_system(self) -> None:
        # What apt-cache policy prints with LANG=vi_VN and LANGUAGE=vi_VN:vi, as on CaramOS installs.
        vietnamese = "fcitx5-lotus:\n  Đã cài đặt: 3.5.6-1\n  Ứng cử:     6.0.5-1\n"
        english = "fcitx5-lotus:\n  Installed: 3.5.6-1\n  Candidate: 6.0.5-1\n"

        def fake_run(args, **kwargs):
            environment = kwargs.get("env") or {}
            localized = "LANGUAGE" in environment or environment.get("LC_ALL") != "C.UTF-8"
            return subprocess.CompletedProcess(args, 0, vietnamese if localized else english, "")

        with mock.patch.dict(apt.os.environ, {"LANG": "vi_VN", "LANGUAGE": "vi_VN:vi"}), \
                mock.patch.object(apt.subprocess, "run", side_effect=fake_run):
            self.assertEqual("6.0.5-1", apt.candidate_version("fcitx5-lotus"))


class SelfUpdateTests(unittest.TestCase):
    def run_self_update(self, *, install_ok: bool, status: dict[str, tuple[str, str]], candidates: dict[str, str]):
        installed = []

        def package_status(name):
            return status.get(name, ("", ""))

        def install(packages):
            installed.append(packages)
            return install_ok

        with mock.patch.object(cli, "install_packages", side_effect=install), \
                mock.patch.object(apt, "package_status", side_effect=package_status), \
                mock.patch.object(cli, "candidate_version", side_effect=lambda name: candidates.get(name, "")), \
                mock.patch.object(apt, "candidate_version", side_effect=lambda name: candidates.get(name, "")), \
                mock.patch.object(cli, "broken_packages", return_value=["nvidia-dkms-470"]), \
                mock.patch.object(cli, "installed_version", return_value=status.get("caramos-ota", ("", ""))[1]), \
                mock.patch.object(cli, "update_installed_app_center"), \
                mock.patch.object(cli.os, "execv") as execv, redirect_stdout(io.StringIO()) as out:
            try:
                cli.self_update_ota_if_needed(skip_self_update=False, reexec_args=["/usr/bin/caramos-ota", "--check"])
                exit_code = None
            except SystemExit as exc:
                exit_code = exc.code
        return installed, exit_code, out.getvalue(), execv

    def test_installed_despite_another_broken_package_goes_on(self) -> None:
        installed, exit_code, out, _execv = self.run_self_update(
            install_ok=False, status={"caramos-ota": ("ii", "1.3.4-0caramos1")}, candidates={"caramos-ota": "1.3.4-0caramos1"})
        self.assertEqual([["caramos-ota"]], installed)
        self.assertIsNone(exit_code)
        self.assertIn("nvidia-dkms-470", out)

    def test_not_installed_still_stops(self) -> None:
        _installed, exit_code, out, _execv = self.run_self_update(
            install_ok=False, status={"caramos-ota": ("ii", "1.3.3-0caramos1")}, candidates={"caramos-ota": "1.3.4-0caramos1"})
        self.assertEqual(apt.EXIT_APT, exit_code)
        self.assertIn("Failed to update caramos-ota", out)

    def test_without_a_known_candidate_a_failed_install_stops(self) -> None:
        _installed, exit_code, _out, _execv = self.run_self_update(
            install_ok=False, status={"caramos-ota": ("ii", "1.3.3-0caramos1")}, candidates={})
        self.assertEqual(apt.EXIT_APT, exit_code)

    def test_a_broken_lotus_is_upgraded_with_the_engine(self) -> None:
        # CaramOS 1.0.12 machines kept Lotus 3.5.6, whose postinst has a syntax error (ticket H-1100).
        installed, exit_code, _out, _execv = self.run_self_update(
            install_ok=True, status={"caramos-ota": ("ii", "1.3.4-0caramos1"), "fcitx5-lotus": ("iF", "3.5.6-1")},
            candidates={"caramos-ota": "1.3.4-0caramos1", "fcitx5-lotus": "6.0.0-1"})
        self.assertEqual([["caramos-ota", "fcitx5-lotus"]], installed)
        self.assertIsNone(exit_code)

    def test_what_was_printed_reaches_a_pipe_before_the_restart(self) -> None:
        class Pipe(io.StringIO):
            flushed_text = ""

            def flush(self) -> None:
                Pipe.flushed_text = self.getvalue()

        pipe = Pipe()
        versions = iter(["1.3.3-0caramos1", "1.3.4-0caramos1"])
        with mock.patch.object(cli, "install_packages", return_value=False), \
                mock.patch.object(apt, "package_status", return_value=("ii", "1.3.4-0caramos1")), \
                mock.patch.object(cli, "candidate_version", return_value="1.3.4-0caramos1"), \
                mock.patch.object(apt, "candidate_version", return_value="1.3.4-0caramos1"), \
                mock.patch.object(cli, "broken_packages", return_value=["nvidia-dkms-470"]), \
                mock.patch.object(cli, "installed_version", side_effect=lambda name: next(versions)), \
                mock.patch.object(cli, "update_installed_app_center"), \
                mock.patch.object(cli.os, "execv", side_effect=lambda *args: self.assertIn("nvidia-dkms-470", Pipe.flushed_text)) as execv, \
                mock.patch.object(cli.sys, "stdout", pipe):
            cli.self_update_ota_if_needed(skip_self_update=False, reexec_args=["/usr/bin/caramos-ota", "--check"])
        execv.assert_called_once()

    def test_a_working_lotus_is_left_to_the_update_manager(self) -> None:
        installed, _exit_code, _out, _execv = self.run_self_update(
            install_ok=True, status={"caramos-ota": ("ii", "1.3.4-0caramos1"), "fcitx5-lotus": ("ii", "5.0.5-1")},
            candidates={"caramos-ota": "1.3.4-0caramos1", "fcitx5-lotus": "6.0.0-1"})
        self.assertEqual([["caramos-ota"]], installed)


if __name__ == "__main__":
    unittest.main()
