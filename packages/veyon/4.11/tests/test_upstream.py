"""tools/upstream.py: which Veyon release is newer, and the bump of the recipe (`make test-tools`)."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("veyon_upstream", ROOT / "tools" / "upstream.py")
upstream = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upstream)

SHA = {version: f"{index:x}" * 64 for index, version in enumerate(("4.11.4", "4.11.5", "4.11.6", "4.11.10", "4.9.8",
                                                                   "4.12.0"), start=1)}


def release(version: str, **changes: object) -> dict[str, object]:
    name = f"veyon-{version}-src.tar.bz2"
    item: dict[str, object] = {
        "tag_name": f"v{version}", "draft": False, "prerelease": False, "published_at": "2026-12-01T10:00:00Z",
        "assets": [
            {"name": f"veyon_{version}.0-ubuntu.24.04_amd64.deb", "digest": "sha256:" + "f" * 64,
             "browser_download_url": f"{upstream.DOWNLOAD_PREFIX}v{version}/veyon_{version}.0-ubuntu.24.04_amd64.deb"},
            {"name": name, "digest": "sha256:" + SHA.get(version, "e" * 64),
             "browser_download_url": f"{upstream.DOWNLOAD_PREFIX}v{version}/{name}"},
        ],
    }
    item.update(changes)
    return item


class ReleasesTests(unittest.TestCase):
    def test_only_stable_releases_with_a_checked_source_tarball(self) -> None:
        data = [
            release("4.11.6", draft=True),
            release("4.11.6", prerelease=True),
            release("4.11.6", tag_name="v4.11.6-rc1"),
            release("4.11.6", assets=[]),
            release("4.11.6", assets=[{"name": "veyon-4.11.6-src.tar.bz2", "digest": "",
                                       "browser_download_url": f"{upstream.DOWNLOAD_PREFIX}v4.11.6/veyon-4.11.6-src.tar.bz2"}]),
            release("4.11.6", assets=[{"name": "veyon-4.11.6-src.tar.bz2", "digest": "sha256:" + "a" * 64,
                                       "browser_download_url": "https://example.org/veyon-4.11.6-src.tar.bz2"}]),
            "not a release",
            release("4.11.5"),
        ]
        found = upstream.stable_releases(data)
        self.assertEqual([upstream.Release("4.11.5", SHA["4.11.5"], f"{upstream.RELEASE_PAGE}v4.11.5", "2026-12-01")],
                         found)

    def test_the_newest_by_version_not_by_date(self) -> None:
        # The API lists by date: a 4.9 maintenance release can come after 4.11; 4.11.10 is newer than 4.11.6.
        found = upstream.stable_releases([release("4.9.8"), release("4.11.10"), release("4.11.6"), release("4.11.5")])
        self.assertEqual("4.11.10", upstream.choose(found).version)
        self.assertEqual("4.11.6", upstream.choose(found, "4.11.6").version)
        with self.assertRaises(upstream.UpstreamError):
            upstream.choose(found, "4.11.7")
        with self.assertRaises(upstream.UpstreamError):
            upstream.choose([])


class RecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.changelog = self.tmp / "changelog"
        self.makefile = self.tmp / "Makefile"
        shutil.copy(upstream.CHANGELOG, self.changelog)
        shutil.copy(upstream.MAKEFILE, self.makefile)
        self.debian, self.current = upstream.packaged(self.changelog)

    def test_the_recipe_is_what_the_tool_reads(self) -> None:
        self.assertRegex(self.current, r"^\d+\.\d+\.\d+$")
        self.assertTrue(self.debian.startswith(self.current + "+repack"), self.debian)
        self.assertEqual(1, len(upstream.SHA256_LINE.findall(upstream.MAKEFILE.read_text(encoding="utf-8"))))

    def test_bump_writes_a_changelog_entry_and_the_pin(self) -> None:
        before_changelog = self.changelog.read_text(encoding="utf-8")
        before_makefile = self.makefile.read_text(encoding="utf-8")
        new = upstream.write_bump(upstream.Release("99.0.1", "9" * 64, f"{upstream.RELEASE_PAGE}v99.0.1"),
                                  self.changelog, self.makefile, datetime(2026, 12, 3, 1, 2, 3, tzinfo=timezone.utc))
        self.assertEqual("99.0.1+repack1-0caramos1", new)
        self.assertEqual(
            "veyon (99.0.1+repack1-0caramos1) noble; urgency=medium\n\n"
            "  * New upstream release 99.0.1:\n"
            "    https://github.com/veyon/veyon/releases/tag/v99.0.1\n\n"
            " -- Vietnam Linux Family <developer@vietnamlinuxfamily.net>  Thu, 03 Dec 2026 01:02:03 +0000\n\n"
            + before_changelog, self.changelog.read_text(encoding="utf-8"))
        after = self.makefile.read_text(encoding="utf-8")
        self.assertIn("\nUPSTREAM_SHA256 := " + "9" * 64 + "\n", after)
        self.assertEqual(len(before_makefile.splitlines()), len(after.splitlines()))
        changed = [line for line, old in zip(after.splitlines(), before_makefile.splitlines()) if line != old]
        self.assertEqual(["UPSTREAM_SHA256 := " + "9" * 64], changed, "only the pin changes")
        self.assertEqual(("99.0.1+repack1-0caramos1", "99.0.1"), upstream.packaged(self.changelog))
        if shutil.which("dpkg-parsechangelog"):
            fields = subprocess.run(["dpkg-parsechangelog", "-l", str(self.changelog)], capture_output=True,
                                    text=True, check=True).stdout
            self.assertIn("Version: 99.0.1+repack1-0caramos1\n", fields)
            self.assertIn("Distribution: noble\n", fields)

    def test_bump_to_the_same_or_an_older_version(self) -> None:
        before = self.changelog.read_text(encoding="utf-8")
        with mock.patch("sys.stdout"):
            self.assertEqual(0, upstream.bump(self.current, "1" * 64, self.changelog, self.makefile))
        self.assertEqual(before, self.changelog.read_text(encoding="utf-8"), "the same version changes nothing")
        with self.assertRaises(upstream.UpstreamError):
            upstream.bump("1.0.0", "1" * 64, self.changelog, self.makefile)

    def test_bump_asks_github_for_the_newest(self) -> None:
        data = [release("4.11.5"), release("4.11.6"), release("99.0.0", prerelease=True)]
        with mock.patch.object(upstream, "fetch_releases", return_value=data), \
                mock.patch.object(upstream, "packaged", return_value=("4.11.5+repack1-0caramos1", "4.11.5")), \
                mock.patch("sys.stdout"):
            self.assertEqual(0, upstream.bump(changelog=self.changelog, makefile=self.makefile))
        self.assertTrue(self.changelog.read_text(encoding="utf-8").startswith("veyon (4.11.6+repack1-0caramos1) "))
        self.assertIn("UPSTREAM_SHA256 := " + SHA["4.11.6"], self.makefile.read_text(encoding="utf-8"))

    def test_check_reports_a_newer_release(self) -> None:
        output = self.tmp / "github-output"
        data = [release("4.11.5"), release("4.11.6"), release("4.12.0")]
        with mock.patch.object(upstream, "fetch_releases", return_value=data), \
                mock.patch.object(upstream, "packaged", return_value=("4.11.5+repack1-0caramos1", "4.11.5")), \
                mock.patch("sys.stdout"):
            self.assertEqual(1, upstream.check(output=str(output)))
            self.assertEqual(1, upstream.check("4.11.6", str(output)))
            self.assertEqual(0, upstream.check("4.11.5", str(output)))
        blocks = output.read_text(encoding="utf-8").split("version=")[1:]
        self.assertEqual(f"4.12.0\nsha256={SHA['4.12.0']}\npage={upstream.RELEASE_PAGE}v4.12.0\npackaged=4.11.5\n"
                         "newer=true\nseries=new\n", blocks[0])
        self.assertIn("newer=true\nseries=same\n", blocks[1])
        self.assertIn("newer=false\n", blocks[2])

    def test_arguments(self) -> None:
        self.assertEqual("4.11.6", upstream.version_argument("4.11.6"))
        for bad in ("4.11", "v4.11.6", "4.11.6; rm -rf /", ""):
            with self.assertRaises(Exception):
                upstream.version_argument(bad)
        with mock.patch("sys.stderr") as stderr, self.assertRaises(SystemExit):
            upstream.main(["bump", "--sha256", "1" * 64])
        self.assertIn("--sha256 needs --version", "".join(call.args[0] for call in stderr.write.call_args_list))

    def test_the_command_line(self) -> None:
        data = [release("4.11.5"), release("4.11.6")]
        with mock.patch.object(upstream, "fetch_releases", return_value=data), \
                mock.patch.object(upstream, "packaged", return_value=("4.11.5+repack1-0caramos1", "4.11.5")), \
                mock.patch("sys.stdout"):
            self.assertEqual(1, upstream.main(["check"]))
            self.assertEqual(0, upstream.main(["check", "--version", "4.11.5"]))
            self.assertEqual(2, upstream.main(["check", "--version", "4.11.7"]), "not on GitHub")
        with mock.patch.object(upstream, "fetch_releases", side_effect=upstream.UpstreamError("offline")), \
                mock.patch("sys.stderr"):
            self.assertEqual(2, upstream.main(["check"]))


if __name__ == "__main__":
    unittest.main()
