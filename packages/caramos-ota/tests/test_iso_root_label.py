"""The ISO's installer hook that names the new system's root file system "CaramOS" (ticket H-1198).

config/includes.chroot/usr/lib/ubiquity/target-config/50caramos_root_label runs on the live system near the end of an
install, with the new system mounted on /target. These tests run it with stand-ins for findmnt, blkid, lsblk, e2label
and sfdisk, so they need no disk and no root."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
HOOK_DIR = REPO / "config/includes.chroot/usr/lib/ubiquity/target-config"
HOOK = HOOK_DIR / "50caramos_root_label"

# Each stand-in answers from T_* variables; e2label and sfdisk only write their arguments to $T_LOG.
STUBS = {
    "findmnt": '[ -n "${T_SRC:-}" ] || exit 1\necho "$T_SRC"\n',
    "blkid": 'case "$*" in\n'
             '  *"-s TYPE"*) echo "${T_FSTYPE:-}" ;;\n'
             '  *"-s LABEL"*) [ -z "${T_LABEL:-}" ] || echo "$T_LABEL" ;;\n'
             'esac\n',
    "lsblk": 'case "$*" in\n'
             '  *" TYPE "*) echo "${T_TYPE:-}" ;;\n'
             '  *" PTTYPE "*) echo "${T_PTTYPE:-}" ;;\n'
             '  *" PARTLABEL "*) echo "${T_PARTLABEL:-}" ;;\n'
             '  *" PKNAME "*) echo "${T_PKNAME:-}" ;;\n'
             '  *" PARTN "*) echo "${T_PARTN:-}" ;;\n'
             'esac\n',
    "e2label": 'echo "e2label $*" >> "$T_LOG"\n',
    "sfdisk": 'echo "sfdisk $*" >> "$T_LOG"\n',
}
SFDISK = "sfdisk --no-reread --no-tell-kernel --part-label"


@unittest.skipUnless(HOOK.is_file(), "the source package has no config/")
class RootLabelHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.work = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.work)
        self.bin = self.work / "bin"
        self.bin.mkdir()
        for name, body in STUBS.items():
            stub = self.bin / name
            stub.write_text("#!/bin/sh\n" + body, encoding="utf-8")
            stub.chmod(0o755)

    def run_hook(self, **scenario: str) -> list[str]:
        target = self.work / "target"
        installed_copy = target / "usr/lib/ubiquity/target-config/50caramos_root_label"
        installed_copy.parent.mkdir(parents=True, exist_ok=True)
        installed_copy.write_text("copied from the live image\n", encoding="utf-8")
        log = self.work / "commands.log"
        log.write_text("", encoding="utf-8")
        env = {"PATH": f"{self.bin}:/usr/bin:/bin", "CARAMOS_TARGET": str(target), "T_LOG": str(log),
               **{f"T_{key.upper()}": value for key, value in scenario.items()}}
        result = subprocess.run(["sh", str(HOOK)], env=env, capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(installed_copy.exists(), "the hook removes its copy from the new system")
        self.stderr = result.stderr
        return log.read_text(encoding="utf-8").splitlines()

    def test_gpt_install_gets_the_label_and_the_partition_name(self) -> None:
        self.assertEqual(["e2label /dev/vda3 CaramOS", f"{SFDISK} /dev/vda 3 CaramOS"],
                         self.run_hook(src="/dev/vda3", fstype="ext4", type="part", pttype="gpt", pkname="vda",
                                       partn="3"))
        # Ubiquity's log-output keeps stderr only (stdout is passed through): the installer's syslog shows what it did.
        self.assertEqual(["CaramOS: file system label of /dev/vda3 set to CaramOS",
                          "CaramOS: name of partition 3 of /dev/vda set to CaramOS"], self.stderr.splitlines())

    def test_nvme_partition(self) -> None:
        self.assertEqual(["e2label /dev/nvme0n1p2 CaramOS", f"{SFDISK} /dev/nvme0n1 2 CaramOS"],
                         self.run_hook(src="/dev/nvme0n1p2", fstype="ext4", type="part", pttype="gpt",
                                       pkname="nvme0n1", partn="2"))

    def test_mbr_has_no_partition_names(self) -> None:
        self.assertEqual(["e2label /dev/sda1 CaramOS"],
                         self.run_hook(src="/dev/sda1", fstype="ext4", type="part", pttype="dos", pkname="sda",
                                       partn="1"))

    def test_lvm_and_encryption_name_no_partition(self) -> None:
        self.assertEqual(["e2label /dev/mapper/vgcaramos-root CaramOS"],
                         self.run_hook(src="/dev/mapper/vgcaramos-root", fstype="ext4", type="lvm"))
        self.assertEqual(["e2label /dev/mapper/nvme0n1p3_crypt CaramOS"],
                         self.run_hook(src="/dev/mapper/nvme0n1p3_crypt", fstype="ext4", type="crypt"))

    def test_names_the_user_gave_stay(self) -> None:
        self.assertEqual([], self.run_hook(src="/dev/sda2", fstype="ext4", label="MyRoot", type="part",
                                           pttype="gpt", partlabel="root", pkname="sda", partn="2"))
        # Each name on its own: a file system label from "Something else", an empty partition name.
        self.assertEqual([f"{SFDISK} /dev/sda 2 CaramOS"],
                         self.run_hook(src="/dev/sda2", fstype="ext4", label="MyRoot", type="part", pttype="gpt",
                                       pkname="sda", partn="2"))

    def test_other_file_systems_are_left_alone(self) -> None:
        self.assertEqual([], self.run_hook(src="/dev/sda2[/@]", fstype="btrfs"))
        self.assertEqual([], self.run_hook(src="/dev/sda2", fstype="xfs", type="part", pttype="dos", pkname="sda",
                                           partn="2"))

    def test_nothing_without_a_mounted_target(self) -> None:
        self.assertEqual([], self.run_hook())

    def test_ubiquity_runs_it(self) -> None:
        # plugininstall.py runs the executables of target-config whose names have no dot.
        self.assertNotIn(".", HOOK.name)
        self.assertTrue(os.access(HOOK, os.X_OK))
        self.assertTrue(HOOK.read_text(encoding="utf-8").startswith("#!/bin/sh\n"))
        self.assertIn(f'rm -f "$TARGET/usr/lib/ubiquity/target-config/{HOOK.name}"', HOOK.read_text(encoding="utf-8"))


@unittest.skipUnless((REPO / "scripts/repack.sh").is_file(), "the source package has no scripts/")
class IsoVolumeLabelTests(unittest.TestCase):
    def test_the_usb_is_not_named_like_the_installed_system(self) -> None:
        # The installed root file system is "CaramOS"; the installer USB carries the version and the edition, within
        # the 32 characters of an ISO 9660 volume ID (xorriso stops the build beyond that).
        line = next(line for line in (REPO / "scripts/repack.sh").read_text(encoding="utf-8").splitlines()
                    if line.strip().startswith("-volid "))
        expression = line.strip()[len("-volid "):]
        for edition, shown in (("cinnamon", "Cinnamon"), ("xfce", "Xfce")):
            script = f'source scripts/config.sh; printf "%s\\n%s" "$CARAMOS_VERSION" {expression}'
            result = subprocess.run(["bash", "-c", script], cwd=REPO, capture_output=True, text=True, check=True,
                                    env={"PATH": "/usr/bin:/bin", "MINT_EDITION": edition})
            version, label = result.stdout.split("\n")
            self.assertEqual(f"CaramOS {version} {shown}", label)
            self.assertLessEqual(len(label), 32)


if __name__ == "__main__":
    unittest.main()
