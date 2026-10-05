"""The source package uploaded to the PPA must not carry local test output or developer settings."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

PKG_DIR = Path(__file__).parents[1]


class SourcePackageTests(unittest.TestCase):
    def test_local_files_are_left_out_of_the_source_tarball(self) -> None:
        # dpkg-source packs the whole directory and ignores .gitignore.
        options = (PKG_DIR / "debian/source/options").read_text(encoding="utf-8")
        ignored = set(re.findall(r'^tar-ignore\s*=\s*"([^"]+)"', options, flags=re.M))
        self.assertLessEqual({"dist-testkit", "vm.local.env"}, ignored)

    def test_gpg_unlock_asks_in_the_terminal(self) -> None:
        # A pinentry started by gpg-agent never reaches a VS Code / SSH terminal and times out.
        makefile = (PKG_DIR / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("\ngpg-unlock:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("--pinentry-mode loopback", recipe)
        self.assertIn("--pinentry-mode error", recipe)


if __name__ == "__main__":
    unittest.main()
