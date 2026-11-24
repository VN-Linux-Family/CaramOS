"""Create a desktop shortcut for any place (ticket H-1190): migration 20261123120100_desktop_shortcuts_anywhere and
/usr/share/caramos-ota/desktop-shortcut/caramos-desktop-shortcut."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "usr/share/caramos-ota/desktop-shortcut/caramos-desktop-shortcut"
migration = importlib.import_module("caramos_ota_update.migrations.20261123120100_desktop_shortcuts_anywhere.migration")
nemo_actions = importlib.import_module("caramos_ota_update.migrations.20261117100100_nemo_actions_in_menu.migration")

try:
    import gi

    gi.require_version("Gio", "2.0")
    from gi.repository import Gio  # noqa: F401

    HAVE_GI = True
except (ImportError, ValueError):
    HAVE_GI = False

SPICE = "create-desktop-shortcut@anaximeno"


def load_helper():
    loader = importlib.machinery.SourceFileLoader("caramos_desktop_shortcut", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


helper = load_helper()


def spice_action() -> str:
    """The action file as migration 20261117100100 writes it from the spice's template."""

    return nemo_actions.build_action(SPICE, nemo_actions.TEMPLATES[SPICE], {"vi": {
        "Create a desktop shortcut": "Tạo lối tắt trên màn hình"}})


class MigrationTests(unittest.TestCase):
    def test_the_spice_action_runs_the_helper_with_uris(self) -> None:
        new = migration.updated(spice_action())
        self.assertIn(f'\nExec={migration.HELPER} "%U"\n', new)
        self.assertNotIn("action.py", new)
        # Everything else stays: the translated name, the condition that hides it on the Desktop, the icon.
        self.assertEqual(spice_action().replace('Exec=<create-desktop-shortcut@anaximeno/action.py "%F">',
                                                migration.EXEC), new)
        self.assertIn("Name[vi]=Tạo lối tắt trên màn hình", new)
        self.assertIn('Conditions=exec <create-desktop-shortcut@anaximeno/check.sh "%P">;', new)
        self.assertEqual(new, migration.updated(new))

    def test_the_spice_line_with_or_without_quotes(self) -> None:
        for line in ('Exec=<create-desktop-shortcut@anaximeno/action.py %F>',
                     'Exec=<create-desktop-shortcut@anaximeno/action.py "%F">'):
            with self.subTest(line=line):
                self.assertIn(migration.EXEC, migration.updated(f"[Nemo Action]\n{line}\nSelection=notnone\n"))

    def test_an_action_someone_changed_stays(self) -> None:
        for text in ("[Nemo Action]\nExec=/usr/local/bin/my-shortcut %U\n",
                     "[Nemo Action]\nName=No exec line\n",
                     '[Nemo Action]\nExec=<create-desktop-shortcut@anaximeno/action.py "%F">\nExec=other\n'):
            with self.subTest(text=text):
                self.assertEqual("", migration.updated(text))

    def run_on(self, text: str | None, dry_run: bool = False) -> tuple[Path, list[str]]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        action = Path(tmp.name) / f"{SPICE}.nemo_action"
        if text is not None:
            action.write_text(text, encoding="utf-8")
            action.chmod(0o644)
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.run(MigrationContext(dry_run=dry_run), action)
        return action, logged

    def test_run(self) -> None:
        action, _logged = self.run_on(spice_action())
        self.assertIn(migration.EXEC, action.read_text(encoding="utf-8"))
        self.assertEqual(0o644, action.stat().st_mode & 0o777)
        action, logged = self.run_on(action.read_text(encoding="utf-8"))
        self.assertIn("already", logged[0])

    def test_dry_run_and_other_actions(self) -> None:
        action, _logged = self.run_on(spice_action(), dry_run=True)
        self.assertEqual(spice_action(), action.read_text(encoding="utf-8"))
        action, logged = self.run_on("[Nemo Action]\nExec=/usr/local/bin/my-shortcut %U\n")
        self.assertEqual("[Nemo Action]\nExec=/usr/local/bin/my-shortcut %U\n", action.read_text(encoding="utf-8"))
        self.assertTrue(logged[0].startswith("warning:"), logged)
        _action, logged = self.run_on(None)
        self.assertIn("nothing to change", logged[0])

    def test_manifest_and_package(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)  # Files is Nemo on both editions
        self.assertEqual("anytime", manifest["unattended"])  # Nemo reads the action again by itself
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertEqual(migration.HELPER, Path("/") / HELPER.relative_to(ROOT))
        self.assertTrue(os.access(HELPER, os.X_OK))
        self.assertIn("usr/share/caramos-ota/desktop-shortcut usr/share/caramos-ota/\n",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.desktop = Path(tmp.name)

    def test_uris_from_args(self) -> None:
        self.assertEqual(["file:///a%20b", "sftp://h/c"], helper.uris_from_args(["file:///a%20b", "sftp://h/c"]))
        self.assertEqual(["file:///a", "file:///b"], helper.uris_from_args(["file:///a file:///b"]))
        self.assertEqual([], helper.uris_from_args([""]))

    def test_fuse_paths_back_to_their_place(self) -> None:
        mounts = [("/run/user/1000/gvfs/smb-share:server=nas,share=docs", "smb://nas/docs/"),
                  ("/run/user/1000/gvfs/google-drive:host=gmail.com,user=an", "google-drive://an@gmail.com/")]
        self.assertEqual("smb://nas/docs/H%E1%BB%93%20s%C6%A1/B%C3%A1o%20c%C3%A1o%20%231",
                         helper.gvfs_uri_of_fuse_path(
                             Path("/run/user/1000/gvfs/smb-share:server=nas,share=docs/Hồ sơ/Báo cáo #1"), mounts))
        self.assertEqual("google-drive://an@gmail.com/0AAbc/1Xyz-_", helper.gvfs_uri_of_fuse_path(
            Path("/run/user/1000/gvfs/google-drive:host=gmail.com,user=an/0AAbc/1Xyz-_"), mounts))
        self.assertIsNone(helper.gvfs_uri_of_fuse_path(Path("/run/user/1000/gvfs/sftp:host=x/a"), mounts))

    def test_file_names(self) -> None:
        self.assertEqual("Báo cáo 2025-2026", helper.safe_file_name("Báo cáo 2025/2026"))
        self.assertEqual("Hai dòng", helper.safe_file_name("Hai\ndòng"))
        self.assertEqual("hidden", helper.safe_file_name(".hidden"))
        self.assertEqual("Shortcut", helper.safe_file_name(".."))
        self.assertLessEqual(len(helper.safe_file_name("ố" * 300).encode("utf-8")), helper.MAX_NAME_BYTES)

    def test_launcher_text(self) -> None:
        text = helper.launcher_text("Hồ sơ\\2026\n", "google-drive://an@gmail.com/0AAbc/1Xyz", "folder-remote")
        self.assertEqual("[Desktop Entry]\nVersion=1.0\nType=Link\nName=Hồ sơ\\\\2026\\n\nIcon=folder-remote\n"
                         "URL=google-drive://an@gmail.com/0AAbc/1Xyz\n", text)

    def test_a_second_shortcut_to_the_same_place_replaces_the_first(self) -> None:
        uri = "sftp://nas/home/an/H%E1%BB%93%20s%C6%A1"
        first = helper.launcher_path(self.desktop, "Hồ sơ", uri)
        helper.write_launcher(first, helper.launcher_text("Hồ sơ", uri, "folder-remote"))
        self.assertEqual(0o755, first.stat().st_mode & 0o777)
        self.assertEqual(uri, helper.launcher_url(first))
        self.assertEqual(first, helper.launcher_path(self.desktop, "Hồ sơ", uri))

    def test_a_name_taken_by_something_else_gets_a_number(self) -> None:
        (self.desktop / "Hồ sơ.desktop").write_text("[Desktop Entry]\nType=Application\nExec=x\n", encoding="utf-8")
        (self.desktop / "Hồ sơ (2).desktop").symlink_to("/nonexistent")
        path = helper.launcher_path(self.desktop, "Hồ sơ", "sftp://nas/x")
        self.assertEqual(self.desktop / "Hồ sơ (3).desktop", path)

    def test_local_items_go_to_the_spice_with_plain_paths(self) -> None:
        uris = ["file:///home/an/Chia%20s%E1%BA%BB/B%C3%A1o%20c%C3%A1o%20%231", "file:///home/an/Tom's%20a"]
        places = {uris[0]: ("path", "/home/an/Chia sẻ/Báo cáo #1"), uris[1]: ("path", "/home/an/Tom's a")}
        with mock.patch.object(helper, "desktop_folder", return_value=self.desktop), \
                mock.patch.object(helper, "place", side_effect=places.get), \
                mock.patch.object(helper, "make_launcher") as make_launcher, \
                mock.patch.object(helper, "run_spice", return_value=0) as run_spice, \
                mock.patch.object(helper, "tell_not_created") as tell:
            self.assertEqual(0, helper.main(uris))
        run_spice.assert_called_once_with(["/home/an/Chia sẻ/Báo cáo #1", "/home/an/Tom's a"])
        make_launcher.assert_not_called()
        tell.assert_not_called()

    def test_other_places_get_launchers_and_a_failure_is_told(self) -> None:
        uris = ["google-drive://an@gmail.com/0AAbc/1Xyz", "smb://gone/share/x"]

        def make(desktop: Path, uri: str) -> Path:
            if "gone" in uri:
                raise OSError("not mounted")
            return desktop / "Kế hoạch.desktop"

        with mock.patch.object(helper, "desktop_folder", return_value=self.desktop), \
                mock.patch.object(helper, "place", side_effect=lambda uri: ("uri", uri)), \
                mock.patch.object(helper, "make_launcher", side_effect=make) as make_launcher, \
                mock.patch.object(helper, "run_spice") as run_spice, \
                mock.patch.object(helper, "tell_not_created") as tell, \
                mock.patch("builtins.print"):
            self.assertEqual(1, helper.main(uris))
        self.assertEqual([mock.call(self.desktop, uri) for uri in uris], make_launcher.call_args_list)
        run_spice.assert_not_called()
        tell.assert_called_once()

    @unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
    def test_place(self) -> None:
        local = self.desktop / "Báo cáo #1"
        local.mkdir()
        self.assertEqual(("path", str(local)), helper.place(local.as_uri()))
        self.assertEqual(("uri", "sftp://nas/home/an/x"), helper.place("sftp://nas/home/an/x"))
        # A path in GVfs's FUSE folder that GIO does not map back (no GVfs here): the place, from the mounts.
        fuse = self.desktop / "gvfs"
        share = fuse / "smb-share:server=nas,share=docs" / "Hồ sơ"
        share.mkdir(parents=True)
        with mock.patch.object(helper, "fuse_root", return_value=fuse), \
                mock.patch.object(helper, "mounts", return_value=[(str(share.parent), "smb://nas/docs/")]):
            self.assertEqual(("uri", "smb://nas/docs/H%E1%BB%93%20s%C6%A1"), helper.place(share.as_uri()))

    @unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
    def test_make_launcher_for_a_folder(self) -> None:
        folder = self.desktop / "Thư mục xa"
        folder.mkdir()
        desktop = self.desktop / "Desktop"
        desktop.mkdir()
        with mock.patch.object(helper, "trust") as trust:
            path = helper.make_launcher(desktop, folder.as_uri())
        self.assertEqual(desktop / "Thư mục xa.desktop", path)
        text = path.read_text(encoding="utf-8")
        self.assertIn("Name=Thư mục xa\n", text)
        self.assertIn("Icon=folder-remote\n", text)
        self.assertIn(f"URL={folder.as_uri()}\n", text)
        trust.assert_called_once_with(path)


if __name__ == "__main__":
    unittest.main()
