"""Updates never wait for an answer to dpkg (ticket H-1207).

CaramOS 1.4.0 and 1.5.0 shipped the office defaults as the configuration file /etc/xdg/mimeapps.list. On a computer
that already had a file of that name, made by its user or by another program, dpkg asked which one to keep when it
configured caramos-ota. The OTA's self-update runs without a terminal: dpkg read end-of-file, caramos-ota stayed
unconfigured ("install ok unpacked"), and the computer could not update any more. The self-update runs the installed
caramos-ota, so only the package itself can stop the question: the defaults are now
/usr/share/applications/{x-cinnamon,xfce}-mimeapps.list (tests/test_open_document.py), and its maintainer scripts deal
with the old file:

- preinst moves the old file aside only when it is still the one dpkg installed (the checksum dpkg recorded), so dpkg
  forgets it; postinst deletes it; postrm puts it back when the upgrade fails;
- any other file stays as it is: one someone changed, a symbolic link, and the file the user had on a computer that
  stopped updating (dpkg recorded no checksum there: "newconffile"); dpkg keeps it as an obsolete configuration file;
- postinst deletes the copy of the old list that the failed configure left (/etc/xdg/mimeapps.list.dpkg-new), and
  nothing else.

Every apt-get and dpkg run of caramos-ota, its migrations and its helpers now also passes --force-confdef
--force-confold, as automatic updates did already, so a question about another configuration file cannot stop an
update either.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota import apt, auto_update
from caramos_ota.constants import APT_NONINTERACTIVE_OPTIONS, DPKG_NONINTERACTIVE_OPTIONS, NONINTERACTIVE_ENV
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
DEBIAN = ROOT / "debian"
# /etc/xdg/mimeapps.list as caramos-ota 1.4.0-0caramos1 and 1.5.0-0caramos2 shipped it (the same file).
OLD_LIST = Path(__file__).resolve().parent / "data/etc-xdg-mimeapps.list-1.4.0"
OLD_SUM = hashlib.md5(OLD_LIST.read_bytes()).hexdigest()
USERS_LIST = b"[Default Applications]\ntext/plain=org.x.editor.desktop\n"
QUIET = ["-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]


def snippet(script: Path, first: str, last: str) -> str:
    """The lines of a maintainer script from the one containing `first` to the next one that is `last`."""

    lines = script.read_text(encoding="utf-8").splitlines()
    start = next(index for index, line in enumerate(lines) if first in line)
    end = next(index for index in range(start + 1, len(lines)) if lines[index] == last)
    return "\n".join(lines[start:end + 1]) + "\n"


class MaintainerScriptTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.xdg = self.root / "etc/xdg"
        self.xdg.mkdir(parents=True)
        self.old = self.xdg / "mimeapps.list"
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.conffiles = self.root / "conffiles"
        # dpkg-query -W -f='${Conffiles}\n' caramos-ota, as dpkg answers it: what self.conffiles says.
        stub = self.bin / "dpkg-query"
        stub.write_text('#!/bin/sh\n[ -f "$CONFFILES" ] || exit 1\ncat "$CONFFILES"\n', encoding="utf-8")
        stub.chmod(0o755)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def recorded(self, text: str) -> None:
        self.conffiles.write_text(text, encoding="utf-8")

    def run_script(self, script: str | Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        if isinstance(script, Path):
            command = ["sh", str(script), *arguments]
        else:
            command = ["sh", "-c", script, "sh", *arguments]
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "DPKG_ROOT": str(self.root), "CONFFILES": str(self.conffiles)}
        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        return result

    def names(self) -> list[str]:
        return sorted(path.name for path in self.xdg.iterdir())


class PreinstTests(MaintainerScriptTestCase):
    def preinst(self, *arguments: str) -> None:
        self.run_script(DEBIAN / "preinst", *(arguments or ("upgrade", "1.5.0-0caramos2")))

    def test_the_unchanged_old_list_is_moved_aside(self) -> None:
        for flags in ("", " obsolete"):
            with self.subTest(flags=flags):
                shutil.copyfile(OLD_LIST, self.old)
                self.recorded(f"\n /etc/X11/Xsession.d/85caramos-nemo-menu 209c054329af06099302d5e638ae2f56\n"
                              f" /etc/xdg/mimeapps.list {OLD_SUM}{flags}\n")
                self.preinst()
                self.assertEqual(["mimeapps.list.dpkg-remove"], self.names())
                self.assertEqual(OLD_LIST.read_bytes(), (self.xdg / "mimeapps.list.dpkg-remove").read_bytes())
                (self.xdg / "mimeapps.list.dpkg-remove").unlink()

    def test_a_changed_list_stays(self) -> None:
        self.old.write_bytes(OLD_LIST.read_bytes() + b"text/plain=org.x.editor.desktop\n")
        self.recorded(f" /etc/xdg/mimeapps.list {OLD_SUM}\n")
        self.preinst()
        self.assertEqual(["mimeapps.list"], self.names())

    def test_the_users_own_file_on_a_computer_that_stopped_updating_stays(self) -> None:
        self.old.write_bytes(USERS_LIST)
        self.recorded(" /etc/xdg/mimeapps.list newconffile\n")
        self.preinst()
        self.assertEqual(["mimeapps.list"], self.names())
        self.assertEqual(USERS_LIST, self.old.read_bytes())

    def test_a_symbolic_link_stays(self) -> None:
        shutil.copyfile(OLD_LIST, self.xdg / "copy.list")
        self.old.symlink_to("copy.list")
        self.recorded(f" /etc/xdg/mimeapps.list {OLD_SUM}\n")
        self.preinst()
        self.assertTrue(self.old.is_symlink())
        self.assertEqual(["copy.list", "mimeapps.list"], self.names())

    def test_a_file_the_package_never_had_stays(self) -> None:
        self.old.write_bytes(OLD_LIST.read_bytes())
        for conffiles in ("\n /etc/logrotate.d/caramos-ota 45397716e4736cb887b441523b666941\n", None):
            with self.subTest(conffiles=conffiles):
                if conffiles is None:
                    self.conffiles.unlink()   # dpkg-query fails: caramos-ota is not installed
                else:
                    self.recorded(conffiles)
                for arguments in (("install",), ("upgrade", "1.3.9-0caramos1")):
                    self.preinst(*arguments)
                    self.assertEqual(["mimeapps.list"], self.names())

    def test_only_on_install_and_upgrade(self) -> None:
        shutil.copyfile(OLD_LIST, self.old)
        self.recorded(f" /etc/xdg/mimeapps.list {OLD_SUM}\n")
        self.preinst("abort-upgrade", "1.5.1-0caramos1")
        self.assertEqual(["mimeapps.list"], self.names())

    def test_has_the_debhelper_marker(self) -> None:
        text = (DEBIAN / "preinst").read_text(encoding="utf-8")
        self.assertIn("\n#DEBHELPER#\n", text)
        self.assertTrue((DEBIAN / "preinst").stat().st_mode & 0o111)


class PostinstTests(MaintainerScriptTestCase):
    def postinst(self) -> None:
        body = snippet(DEBIAN / "postinst", "The office defaults of 1.4.0 and 1.5.0", "        ;;")
        self.run_script('set -e\ncase "$1" in\n    configure)\n' + body + "esac\n", "configure", "1.5.0-0caramos2")

    def test_deletes_what_preinst_moved_aside(self) -> None:
        shutil.copyfile(OLD_LIST, self.xdg / "mimeapps.list.dpkg-remove")
        self.postinst()
        self.assertEqual([], self.names())

    def test_deletes_the_copy_of_the_old_list_a_failed_configure_left(self) -> None:
        self.old.write_bytes(USERS_LIST)
        shutil.copyfile(OLD_LIST, self.xdg / "mimeapps.list.dpkg-new")
        self.postinst()
        self.assertEqual(["mimeapps.list"], self.names())
        self.assertEqual(USERS_LIST, self.old.read_bytes())

    def test_any_other_file_stays(self) -> None:
        (self.xdg / "mimeapps.list.dpkg-new").write_bytes(USERS_LIST)
        (self.xdg / "mimeapps.list.dpkg-dist").write_bytes(OLD_LIST.read_bytes())
        (self.xdg / "mimeapps.list.dpkg-old").write_bytes(USERS_LIST)
        self.postinst()
        self.assertEqual(["mimeapps.list.dpkg-dist", "mimeapps.list.dpkg-new", "mimeapps.list.dpkg-old"], self.names())

    def test_the_checksum_is_the_old_lists(self) -> None:
        self.assertEqual("656282d52d81c53509c4b22f05ebdd66", OLD_SUM)
        self.assertIn(OLD_SUM, (DEBIAN / "postinst").read_text(encoding="utf-8"))


class PostrmTests(MaintainerScriptTestCase):
    def postrm(self, *arguments: str) -> None:
        body = snippet(DEBIAN / "postrm", "    abort-install|abort-upgrade)", "esac")
        self.run_script('set -e\ncase "$1" in\n' + body, *arguments)

    def test_a_failed_upgrade_puts_the_old_list_back(self) -> None:
        shutil.copyfile(OLD_LIST, self.xdg / "mimeapps.list.dpkg-remove")
        self.postrm("abort-upgrade", "1.5.0-0caramos2")
        self.assertEqual(["mimeapps.list"], self.names())
        self.assertEqual(OLD_LIST.read_bytes(), self.old.read_bytes())

    def test_never_over_another_file(self) -> None:
        shutil.copyfile(OLD_LIST, self.xdg / "mimeapps.list.dpkg-remove")
        self.old.write_bytes(USERS_LIST)
        self.postrm("abort-install")
        self.assertEqual(USERS_LIST, self.old.read_bytes())

    def test_not_after_a_good_upgrade(self) -> None:
        shutil.copyfile(OLD_LIST, self.xdg / "mimeapps.list.dpkg-remove")
        self.postrm("upgrade", "1.5.1-0caramos1")
        self.assertEqual(["mimeapps.list.dpkg-remove"], self.names())


class PackageTests(unittest.TestCase):
    def test_no_configuration_file_named_mimeapps_list(self) -> None:
        shipped = [path.relative_to(ROOT) for path in (ROOT / "etc").rglob("*") if path.is_file()]
        self.assertFalse([path for path in shipped if "mimeapps" in path.name], shipped)


class NoQuestionsTests(unittest.TestCase):
    """apt-get and dpkg runs that could configure a package ask nothing."""

    def test_the_options_and_environment(self) -> None:
        self.assertEqual(("--force-confdef", "--force-confold"), DPKG_NONINTERACTIVE_OPTIONS)
        self.assertEqual(tuple(QUIET), APT_NONINTERACTIVE_OPTIONS)
        self.assertEqual({"DEBIAN_FRONTEND": "noninteractive", "UCF_FORCE_CONFFOLD": "1"}, NONINTERACTIVE_ENV)

    def test_automatic_updates_use_the_same(self) -> None:
        conf = (ROOT / "usr/share/caramos-ota/auto-update/apt.conf").read_text(encoding="utf-8")
        self.assertEqual(list(DPKG_NONINTERACTIVE_OPTIONS), re.findall(r'^\s*"(--force-[a-z]+)";', conf, re.M))
        self.assertEqual("/usr/share/caramos-ota/auto-update/apt.conf", auto_update.APT_CONFIG)
        for name, value in NONINTERACTIVE_ENV.items():
            self.assertEqual(value, auto_update.UNATTENDED_ENV[name], name)

    def run_ota(self, function, *arguments) -> tuple[list[str], dict[str, str]]:
        with mock.patch.object(apt, "run_command",
                               return_value=subprocess.CompletedProcess([], 0)) as run_command:
            function(*arguments)
        call = run_command.call_args
        return call.args[0], call.kwargs["env"]

    def assert_quiet(self, env: dict[str, str]) -> None:
        self.assertEqual("noninteractive", env["DEBIAN_FRONTEND"])
        self.assertEqual("1", env["UCF_FORCE_CONFFOLD"])
        self.assertEqual(os.environ.get("PATH"), env.get("PATH"))

    def test_the_ota_self_update_install_remove_downgrade_and_repairs(self) -> None:
        for function, arguments, command in (
                (apt.install_packages, (["caramos-ota", "fcitx5-lotus"],),
                 ["apt-get", *QUIET, "install", "--yes", "--", "caramos-ota", "fcitx5-lotus"]),
                (apt.remove_package, ("zoom",), ["apt-get", *QUIET, "remove", "--yes", "--", "zoom"]),
                (apt.downgrade_package, ("caramos-ota", "1.5.0-0caramos2"),
                 ["apt-get", *QUIET, "install", "--yes", "--allow-downgrades", "--", "caramos-ota=1.5.0-0caramos2"]),
                (apt.repair_dpkg, (), ["dpkg", "--configure", "-a", "--force-confdef", "--force-confold"]),
                (apt.repair_apt, (), ["apt-get", *QUIET, "--fix-broken", "install", "--yes"])):
            with self.subTest(function=function.__name__):
                args, env = self.run_ota(function, *arguments)
                self.assertEqual(command, args)
                self.assert_quiet(env)

    def test_migrations(self) -> None:
        context = MigrationContext()
        for method, arguments, command in (
                (context.apt_install, (["hw-probe"],), [*QUIET, "install", "--yes", "--", "hw-probe"]),
                (context.apt_replace, (["power-profiles-daemon"], ["tlp"]),
                 [*QUIET, "install", "--yes", "--", "power-profiles-daemon", "tlp-"]),
                (context.apt_remove, (["tlp"],), [*QUIET, "remove", "--yes", "--", "tlp"])):
            with self.subTest(method=method.__name__), mock.patch.object(context, "run_command") as run_command:
                method(*arguments)
                self.assertEqual(["apt-get", *command], run_command.call_args.args[0])
                self.assert_quiet(run_command.call_args.kwargs["env"])

    def test_phong_may(self) -> None:
        sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/lab"))
        try:
            from caramos_lab import helper
        finally:
            sys.path.remove(str(ROOT / "usr/share/caramos-ota/lab"))
        process = mock.Mock(stdout=iter(()), wait=mock.Mock(return_value=0))
        with mock.patch.object(helper, "installed", return_value=False), \
                mock.patch.object(helper, "emit"), \
                mock.patch.object(helper.subprocess, "Popen", return_value=process) as popen:
            helper.apt_install(["veyon-service"])
        command = popen.call_args.args[0]
        self.assertEqual(["apt-get", "-o", "DPkg::Lock::Timeout=300", *QUIET, "install", "-y",
                          "--no-install-recommends", "veyon-service"], command)
        self.assert_quiet(popen.call_args.kwargs["env"])


if __name__ == "__main__":
    unittest.main()
