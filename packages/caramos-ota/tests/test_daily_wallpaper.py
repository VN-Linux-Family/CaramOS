"""caramos-daily-wallpaper (ticket H-1161): a photo of Vietnam a day, turned on and off in System Settings >
Backgrounds by picking a photo of its folder or another wallpaper."""

from __future__ import annotations

import configparser
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_daily_wallpaper import cli, core

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "usr/share/caramos-ota/daily-wallpaper/photos.json"
UNITS = ROOT / "usr/lib/systemd/user"
DAY = dt.date(2026, 11, 17)
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"


def photo(index: int, data: bytes, base: Path, **changes: str) -> dict:
    data = data if data.startswith((JPEG, b"<")) else JPEG + data
    path = base / f"photo{index}.jpg"
    path.write_bytes(data)
    entry = {"id": f"p{index}", "url": path.as_uri(), "sha256": hashlib.sha256(data).hexdigest(),
             "title": f"Ảnh số {index}", "author": "Tác giả", "license": "CC BY-SA 4.0",
             "source": f"https://commons.wikimedia.org/wiki/File:P{index}.jpg"}
    entry.update(changes)
    return entry


class ManifestTests(unittest.TestCase):
    def test_the_shipped_list(self) -> None:
        photos = core.load_manifest(MANIFEST)
        self.assertGreaterEqual(len(photos), 20)
        self.assertEqual(len(photos), len({p.id for p in photos}), "ids are unique")
        for item in photos:
            self.assertTrue(item.url.startswith(core.LIST_URL.rsplit("/", 1)[0] + "/"), f"{item.id}: hosted on the website")
            self.assertRegex(item.license, r"^(CC BY(-SA)? [0-9.]+|CC0( 1\.0)?|Public domain)$")
            self.assertTrue(item.source.startswith("https://commons.wikimedia.org/wiki/File:"), item.id)
            self.assertLessEqual(len(item.author), 40, f"{item.id}: an author name, not a message")

    def test_bad_entries_are_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = photo(1, b"one", Path(tmp))
            path = Path(tmp) / "photos.json"
            path.write_text(json.dumps({"photos": [good, {**good, "sha256": "nope"}, {**good, "url": "http://x/y"},
                                                   {k: v for k, v in good.items() if k != "title"}]}),
                            encoding="utf-8")
            self.assertEqual(["p1"], [item.id for item in core.load_manifest(path)])

    def test_every_computer_shows_the_same_photo_on_a_day(self) -> None:
        photos = core.load_manifest(MANIFEST)
        self.assertEqual(photos[0], core.photo_for_day(photos, core.EPOCH))
        self.assertEqual(photos[1], core.photo_for_day(photos, core.EPOCH + dt.timedelta(days=1)))
        self.assertEqual(photos[0], core.photo_for_day(photos, core.EPOCH + dt.timedelta(days=len(photos))))
        with self.assertRaises(core.WallpaperError):
            core.photo_for_day([], DAY)


class NamesAndModesTests(unittest.TestCase):
    def test_the_file_name_credits_the_author(self) -> None:
        item = core.Photo("x", "https://h/a/Foo.JPG", "0" * 64, "Vịnh Hạ Long", "A/B & C: D", "CC BY 4.0", "s")
        name = core.file_name(item, DAY)
        self.assertEqual("2026-11-17 Vịnh Hạ Long (Ảnh: A B C D, CC BY 4.0).jpg", name)
        long_name = core.file_name(core.Photo("x", item.url, item.sha256, "Rất dài " * 40, "A", "CC0", "s"), DAY)
        self.assertLessEqual(len(long_name.encode("utf-8")), 204)
        self.assertTrue(long_name.endswith(".jpg"))

    def test_modes(self) -> None:
        folder = Path("/home/caram/.local/share/caramos/wallpapers") / core.FOLDER_NAME
        inside = core.file_uri(folder / "2026-11-17 Vịnh Hạ Long.jpg")
        self.assertIn("%E1%BB%97i", inside, "Backgrounds writes percent-encoded file URIs")
        self.assertEqual("follow", core.mode(folder, inside, False, ""))
        self.assertEqual("off", core.mode(folder, "file:///usr/share/backgrounds/caramos/default.png", False, ""))
        self.assertEqual("slideshow", core.mode(folder, "file:///x.png", True, "directory://" + str(folder)))
        self.assertEqual("off", core.mode(folder, "file:///x.png", True, "directory:///home/caram/Pictures"))
        self.assertEqual("off", core.mode(folder, "", False, ""))

    def test_register_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folders = Path(tmp) / "cinnamon/backgrounds/user-folders.lst"
            folder, pictures = Path(tmp) / "daily", Path(tmp) / "Pictures"
            self.assertTrue(core.register_folder(folder, folders, pictures))
            self.assertEqual(f"{pictures}\n{folder}\n", folders.read_text(encoding="utf-8"))
            self.assertFalse(core.register_folder(folder, folders, pictures))
            folders.write_text("/data/photos\n", encoding="utf-8")
            core.register_folder(folder, folders, pictures)
            self.assertEqual(f"/data/photos\n{folder}\n", folders.read_text(encoding="utf-8"))


class FetchAndPruneTests(unittest.TestCase):
    def test_fetch_checks_the_hash_and_leaves_no_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            folder = base / "wallpapers" / core.FOLDER_NAME
            folder.mkdir(parents=True)
            item = core.Photo(**photo(1, b"jpeg bytes", base))
            core.fetch(item, folder / "today.jpg")
            self.assertEqual(JPEG + b"jpeg bytes", (folder / "today.jpg").read_bytes())
            self.assertEqual(0o644, (folder / "today.jpg").stat().st_mode & 0o777)
            bad = core.Photo(**{**photo(2, b"other", base), "sha256": "1" * 64})
            with self.assertRaises(core.WallpaperError):
                core.fetch(bad, folder / "bad.jpg")
            self.assertFalse((folder / "bad.jpg").exists())
            self.assertEqual([], list((base / "wallpapers").glob(".caramos-wallpaper-*")))
            page = core.Photo(**photo(3, b"<html>Not found</html>", base))
            with self.assertRaises(core.WallpaperError):
                core.fetch(page, folder / "page.jpg")   # the hash matches, but a web page is not a picture
            self.assertFalse((folder / "page.jpg").exists())

    def test_prune_keeps_the_newest_and_the_current(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            names = [f"2026-11-{day:02d} Ảnh.jpg" for day in range(1, 11)]
            for name in names:
                (folder / name).write_bytes(b"x")
            (folder / core.NOTES_NAME).write_text("notes", encoding="utf-8")
            removed = core.prune(folder, 3, folder / names[1])
            self.assertEqual(sorted(names[:1] + names[2:7]), sorted(path.name for path in removed))
            self.assertEqual(sorted([names[1]] + names[7:] + [core.NOTES_NAME]),
                             sorted(path.name for path in folder.iterdir()))


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        (self.home / "Pictures").mkdir(parents=True)
        source = self.root / "source"
        source.mkdir()
        self.manifest = self.root / "photos.json"
        self.manifest.write_text(json.dumps({"photos": [photo(i, f"photo {i}".encode(), source) for i in range(3)]}),
                                 encoding="utf-8")
        self.settings = {("org.cinnamon.desktop.background", "picture-uri"): "file:///usr/share/backgrounds/x.png",
                         ("org.cinnamon.desktop.background.slideshow", "slideshow-enabled"): "false",
                         ("org.cinnamon.desktop.background.slideshow", "image-source"): ""}
        self.metered = False
        for name, replacement in (("gsettings_get", lambda schema, key: self.settings[(schema, key)]),
                                  ("gsettings_set_string", self.set_setting),
                                  ("pictures_dir", lambda home: home / "Pictures"),
                                  ("metered", lambda: self.metered),
                                  ("edition", lambda: "cinnamon")):
            patcher = mock.patch.object(cli, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_setting(self, schema: str, key: str, value: str) -> bool:
        self.settings[(schema, key)] = value
        return True

    def run_day(self, day: dt.date, list_url: str | None = None) -> int:
        with mock.patch("builtins.print"):
            return cli.run(self.home, day, self.manifest, list_url=list_url or self.manifest.as_uri())

    @property
    def folder(self) -> Path:
        return core.folder_of(self.home)

    def test_first_run_adds_the_folder_and_keeps_the_wallpaper(self) -> None:
        self.assertEqual(0, self.run_day(DAY))
        folders = (self.home / ".config/cinnamon/backgrounds/user-folders.lst").read_text(encoding="utf-8")
        self.assertEqual(f"{self.home / 'Pictures'}\n{self.folder}\n", folders)
        photos = sorted(path.name for path in self.folder.glob("2026-*"))
        self.assertEqual(1, len(photos))
        self.assertEqual("file:///usr/share/backgrounds/x.png", self.settings[("org.cinnamon.desktop.background",
                                                                                 "picture-uri")])
        notes = (self.folder / core.NOTES_NAME).read_text(encoding="utf-8")
        self.assertIn(photos[0], notes)
        self.assertIn("https://commons.wikimedia.org/wiki/File:", notes)

    def test_picking_a_daily_photo_turns_the_daily_change_on_and_another_wallpaper_off(self) -> None:
        self.run_day(DAY)
        first = next(self.folder.glob("2026-*"))
        key = ("org.cinnamon.desktop.background", "picture-uri")
        self.settings[key] = core.file_uri(first)            # the user picks it in Backgrounds
        self.run_day(DAY + dt.timedelta(days=1))
        newest = sorted(self.folder.glob("2026-*"))[-1]
        self.assertNotEqual(first, newest)
        self.assertEqual(core.file_uri(newest), self.settings[key])
        self.settings[key] = "file:///home/caram/Pictures/mine.jpg"   # the user picks their own photo
        self.run_day(DAY + dt.timedelta(days=2))
        self.assertEqual("file:///home/caram/Pictures/mine.jpg", self.settings[key])
        self.assertEqual(3, len(list(self.folder.glob("2026-*"))), "the photos keep arriving in the folder")

    def test_a_slideshow_of_the_folder_is_left_to_cinnamon(self) -> None:
        self.run_day(DAY)
        self.settings[("org.cinnamon.desktop.background.slideshow", "slideshow-enabled")] = "true"
        self.settings[("org.cinnamon.desktop.background.slideshow", "image-source")] = f"directory://{self.folder}"
        before = dict(self.settings)
        self.run_day(DAY + dt.timedelta(days=1))
        self.assertEqual(before, self.settings)
        self.assertEqual(2, len(list(self.folder.glob("2026-*"))))

    def test_removing_the_folder_from_backgrounds_turns_it_off_for_good(self) -> None:
        self.run_day(DAY)
        folders = self.home / ".config/cinnamon/backgrounds/user-folders.lst"
        folders.write_text(f"{self.home / 'Pictures'}\n", encoding="utf-8")
        self.run_day(DAY + dt.timedelta(days=1))
        self.assertEqual(f"{self.home / 'Pictures'}\n", folders.read_text(encoding="utf-8"))
        self.assertEqual(1, len(list(self.folder.glob("2026-*"))))

    def test_a_photo_that_changed_gives_way_to_the_next(self) -> None:
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        today = core.candidates(core.load_manifest(self.manifest), DAY)[0]
        for entry in data["photos"]:
            if entry["id"] == today.id:
                entry["sha256"] = "3" * 64     # Wikimedia re-rendered the thumbnail
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(0, self.run_day(DAY))
        saved = sorted(path.name for path in self.folder.glob("2026-*"))
        self.assertEqual(1, len(saved))
        self.assertNotIn(today.title, saved[0])
        self.assertEqual(0, self.run_day(DAY))
        self.assertEqual(saved, sorted(path.name for path in self.folder.glob("2026-*")), "one photo a day")

    def test_candidates_wrap_around(self) -> None:
        photos = core.load_manifest(MANIFEST)
        last_day = core.EPOCH + dt.timedelta(days=len(photos) - 1)
        self.assertEqual([photos[-1], photos[0], photos[1]], core.candidates(photos, last_day))
        self.assertEqual([], core.candidates([], DAY))

    def test_metered_networks_and_failed_downloads_wait(self) -> None:
        self.metered = True
        self.assertEqual(0, self.run_day(DAY))
        self.assertEqual([], list(self.folder.glob("2026-*")))
        self.metered = False
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        for entry in data["photos"]:
            entry["sha256"] = "2" * 64
        self.manifest.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(0, self.run_day(DAY))
        self.assertEqual([], list(self.folder.glob("2026-*")))


class XfceRunTests(unittest.TestCase):
    """CaramOS Xfce: the folder is a bookmark (Desktop settings > Folder) and each monitor and workspace showing one
    of its photos follows the daily photo."""

    WORKSPACE = "/backdrop/screen0/monitorVirtual-1/workspace0/last-image"
    OTHER = "/backdrop/screen0/monitorVirtual-1/workspace1/last-image"

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.bookmarks = self.home / ".config/gtk-3.0/bookmarks"
        self.bookmarks.parent.mkdir(parents=True)
        self.bookmarks.write_text("file:///home/caram/T%C3%A0i%20li%E1%BB%87u\nfile:///home/caram/%E1%BA%A2nh\n",
                                  encoding="utf-8")
        source = self.root / "source"
        source.mkdir()
        self.manifest = self.root / "photos.json"
        self.manifest.write_text(json.dumps({"photos": [photo(i, f"photo {i}".encode(), source) for i in range(3)]}),
                                 encoding="utf-8")
        sage = "/usr/share/backgrounds/CaramOS/03-sage-mist-2k.jpg"
        self.images = {self.WORKSPACE: sage, self.OTHER: sage, "/backdrop/screen0/monitor0/image-path": sage}
        self.wallpapers = self.root / "usr/share/backgrounds/CaramOS"   # the five CaramOS wallpapers
        self.wallpapers.mkdir(parents=True)
        patcher = mock.patch.object(core, "XFCE_WALLPAPERS", self.wallpapers)
        patcher.start()
        self.addCleanup(patcher.stop)
        refuse = lambda *args: self.fail("no Cinnamon settings on Xfce")
        for name, replacement in (("gsettings_get", refuse), ("gsettings_set_string", refuse),
                                  ("pictures_dir", lambda home: home / "Pictures"), ("metered", lambda: False),
                                  ("edition", lambda: "xfce"), ("xfconf_images", lambda: dict(self.images)),
                                  ("xfconf_set", self.set_image)):
            patcher = mock.patch.object(cli, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)

    def set_image(self, name: str, value: str) -> bool:
        self.images[name] = value
        return True

    def run_day(self, day: dt.date) -> int:
        with mock.patch("builtins.print"):
            return cli.run(self.home, day, self.manifest, list_url=self.manifest.as_uri())

    @property
    def folder(self) -> Path:
        return core.folder_of(self.home)

    def test_first_run_bookmarks_the_folder_and_keeps_the_wallpaper(self) -> None:
        before = dict(self.images)
        self.assertEqual(0, self.run_day(DAY))
        lines = self.bookmarks.read_text(encoding="utf-8").splitlines()
        self.assertEqual(4, len(lines), "the other bookmarks stay")
        self.assertEqual([self.wallpapers, self.folder], [core.uri_path(line) for line in lines[-2:]])
        self.assertIn("Vi%E1%BB%87t%20Nam", lines[-1], "percent-encoded, as GTK writes it")
        self.assertFalse((self.home / ".config/cinnamon").exists())
        self.assertEqual(before, self.images)
        self.assertEqual(1, len(list(self.folder.glob("2026-*"))))
        self.run_day(DAY + dt.timedelta(days=1))
        self.assertEqual(4, len(self.bookmarks.read_text(encoding="utf-8").splitlines()), "added once")

    def test_the_caramos_wallpapers_are_bookmarked_once(self) -> None:
        # A user who already had the daily photos bookmarked (before 2026-11-19) gets the five wallpapers too.
        state = self.home / ".local/state/caramos/daily-wallpaper.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"bookmarked": True}), encoding="utf-8")
        with self.bookmarks.open("a", encoding="utf-8") as handle:
            handle.write(core.file_uri(self.folder) + "\n")
        self.run_day(DAY)
        lines = self.bookmarks.read_text(encoding="utf-8").splitlines()
        self.assertEqual([self.folder, self.wallpapers], [core.uri_path(line) for line in lines[-2:]])
        # Removed by the user: it stays removed, and the daily photos go on.
        self.bookmarks.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        self.run_day(DAY + dt.timedelta(days=1))
        self.assertFalse(core.bookmarked(self.wallpapers, self.bookmarks))
        self.assertEqual(2, len(list(self.folder.glob("2026-*"))))

    def test_no_caramos_wallpapers_no_bookmark(self) -> None:
        self.wallpapers.rmdir()
        self.run_day(DAY)
        self.assertFalse(core.bookmarked(self.wallpapers, self.bookmarks))
        self.assertTrue(core.bookmarked(self.folder, self.bookmarks))

    def test_a_workspace_showing_a_daily_photo_follows_it(self) -> None:
        self.run_day(DAY)
        first = next(self.folder.glob("2026-*"))
        self.images[self.WORKSPACE] = str(first)            # the user picks it in Desktop settings
        self.run_day(DAY + dt.timedelta(days=1))
        newest = sorted(self.folder.glob("2026-*"))[-1]
        self.assertNotEqual(first, newest)
        self.assertEqual(str(newest), self.images[self.WORKSPACE])
        self.assertEqual("/usr/share/backgrounds/CaramOS/03-sage-mist-2k.jpg", self.images[self.OTHER])
        self.images[self.WORKSPACE] = "/home/caram/Pictures/mine.jpg"   # another picture: that one stops following
        self.run_day(DAY + dt.timedelta(days=2))
        self.assertEqual("/home/caram/Pictures/mine.jpg", self.images[self.WORKSPACE])

    def test_removing_the_bookmark_turns_it_off_for_good(self) -> None:
        self.run_day(DAY)
        self.bookmarks.write_text("file:///home/caram/T%C3%A0i%20li%E1%BB%87u\n", encoding="utf-8")
        self.run_day(DAY + dt.timedelta(days=1))
        self.assertEqual(1, len(self.bookmarks.read_text(encoding="utf-8").splitlines()))
        self.assertEqual(1, len(list(self.folder.glob("2026-*"))))

    def test_a_mint_xfce_that_ran_the_cinnamon_steps_gets_the_bookmark(self) -> None:
        state = self.home / ".local/state/caramos/daily-wallpaper.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"registered": True}), encoding="utf-8")
        self.run_day(DAY)
        self.assertTrue(core.bookmarked(self.folder, self.bookmarks))

    def test_bookmarks_with_a_name_and_the_desktop_properties(self) -> None:
        folder = Path("/home/caram/.local/share/caramos/wallpapers") / core.FOLDER_NAME
        with tempfile.TemporaryDirectory() as tmp:
            bookmarks = Path(tmp) / "bookmarks"
            bookmarks.write_text(core.file_uri(folder) + " Ảnh nền\n", encoding="utf-8")
            self.assertTrue(core.bookmarked(folder, bookmarks))
            self.assertFalse(core.add_bookmark(folder, bookmarks))
        photo_path = str(folder / "2026-11-17 Hạ Long.jpg")
        images = {"/backdrop/screen0/monitorHDMI-1/workspace2/last-image": photo_path,
                  "/backdrop/screen0/monitor0/last-image": photo_path,
                  "/backdrop/screen0/monitor0/image-path": photo_path,
                  "/backdrop/screen0/monitorDP-1/workspace0/last-image": "/usr/share/backgrounds/x.jpg"}
        self.assertEqual(["/backdrop/screen0/monitor0/last-image", "/backdrop/screen0/monitorHDMI-1/workspace2/last-image"],
                         core.xfce_following(folder, images))

    def test_prune_keeps_every_picture_on_screen(self) -> None:
        folder = self.root / "photos"
        folder.mkdir()
        days = [DAY + dt.timedelta(days=offset) for offset in range(5)]
        for day in days:
            (folder / f"{day.isoformat()} Ảnh.jpg").write_bytes(JPEG)
        oldest, second = (folder / f"{day.isoformat()} Ảnh.jpg" for day in days[:2])
        removed = core.prune(folder, 2, None, also={oldest})
        self.assertNotIn(oldest, removed)
        self.assertIn(second, removed)
        self.assertTrue(oldest.exists())


class ListTests(unittest.TestCase):
    """The list comes from the website; the last one fetched and then the packaged copy stand in for it."""

    def test_only_allowed_hosts_in_a_list_from_the_website(self) -> None:
        good = {"id": "a", "sha256": "a" * 64, "title": "Ảnh", "author": "A", "license": "CC0", "source": "s"}
        urls = ["https://caramos.vietnamlinuxfamily.net/wallpapers/a.jpg", "https://upload.wikimedia.org/a.jpg",
                "https://thumb.wikimedia.org/a.jpg", "file:///etc/hostname", "http://caramos.vietnamlinuxfamily.net/a.jpg",
                "https://evil.example/a.jpg", "https://caramos.vietnamlinuxfamily.net.evil.example/a.jpg"]
        text = json.dumps({"photos": [{**good, "id": f"p{i}", "url": url} for i, url in enumerate(urls)]})
        self.assertEqual(["p0", "p1", "p2"], [item.id for item in core.parse_manifest(text)])
        self.assertEqual(["p0", "p1", "p2", "p3"], [item.id for item in core.parse_manifest(text, allow_files=True)])
        self.assertEqual([], core.parse_manifest("[1, 2]"))

    def test_website_then_last_list_then_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "pkg").mkdir()
            web = root / "web/photos.json"
            web.write_text(json.dumps({"photos": [photo(1, b"web", root / "web")]}), encoding="utf-8")
            packaged = root / "pkg/photos.json"
            packaged.write_text(json.dumps({"photos": [photo(2, b"pkg", root / "pkg")]}), encoding="utf-8")
            cache = root / "cache/photos.json"
            with mock.patch("builtins.print"):
                self.assertEqual(["p1"], [item.id for item in cli.photo_list(web.as_uri(), cache, packaged)])
                self.assertTrue(cache.exists(), "the website's list is kept")
                missing = (root / "web/gone.json").as_uri()
                # A list kept from the website may not point at files: here it does (a test list), so it is empty.
                self.assertEqual(["p2"], [item.id for item in cli.photo_list(missing, cache, packaged)])
                cache.write_text(json.dumps({"photos": [{**photo(4, b"x", root / "web"),
                                                         "url": "https://caramos.vietnamlinuxfamily.net/w/4.jpg"}]}),
                                 encoding="utf-8")
                self.assertEqual(["p4"], [item.id for item in cli.photo_list(missing, cache, packaged)])

    def test_a_list_too_big_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.json"
            big.write_text(" " * (core.LIST_MAX_BYTES + 10), encoding="utf-8")
            self.assertEqual([], core.fetch_list(big.as_uri(), Path(tmp) / "cache.json"))


class UnitTests(unittest.TestCase):
    def test_user_timer(self) -> None:
        timer = configparser.ConfigParser(interpolation=None)
        timer.read_string((UNITS / "caramos-daily-wallpaper.timer").read_text(encoding="utf-8"))
        self.assertEqual("timers.target", timer["Install"]["WantedBy"])
        self.assertEqual("true", timer["Timer"]["Persistent"])
        self.assertEqual("!@system", timer["Unit"]["ConditionUser"])
        self.assertEqual("!boot=casper", timer["Unit"]["ConditionKernelCommandLine"])
        service = configparser.ConfigParser(interpolation=None)
        service.read_string((UNITS / "caramos-daily-wallpaper.service").read_text(encoding="utf-8"))
        self.assertEqual("/usr/bin/caramos-daily-wallpaper", service["Service"]["ExecStart"])
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for path in ("usr/bin/caramos-daily-wallpaper", "usr/lib/python3/dist-packages/caramos_daily_wallpaper",
                     "usr/lib/systemd/user/caramos-daily-wallpaper.timer", "usr/share/caramos-ota/daily-wallpaper"):
            self.assertIn(path, install)


if __name__ == "__main__":
    unittest.main()


class StartTimerMigrationTests(unittest.TestCase):
    """Migration 20261117100200_daily_wallpaper starts the user timer in the sessions that are open."""

    def setUp(self) -> None:
        import importlib

        self.migration = importlib.import_module("caramos_ota_update.migrations.20261117100200_daily_wallpaper.migration")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        timer = self.root / "caramos-daily-wallpaper.timer"
        timer.write_text("[Timer]\n", encoding="utf-8")
        (self.root / "run/1000/systemd").mkdir(parents=True)
        (self.root / "run/1000/systemd/private").write_text("", encoding="utf-8")
        self.calls: list[list[str]] = []
        for name, value in (("TIMER_FILE", timer), ("RUNTIME_ROOT", self.root / "run"),
                            ("_desktop_users", lambda: [("caram", 1000), ("away", 1001)])):
            patcher = mock.patch.object(self.migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, command, **kwargs):
        import subprocess

        self.calls.append(command)
        self.assertEqual("/run/user/1000".replace("/run/user", str(self.root / "run")), kwargs["env"]["XDG_RUNTIME_DIR"])
        return subprocess.CompletedProcess(command, 0, "", "")

    def run_migration(self, dry_run: bool = False) -> None:
        from caramos_ota_update.context import MigrationContext

        with mock.patch("builtins.print"), mock.patch("caramos_ota_update.context.log_info"), \
                mock.patch.object(self.migration.subprocess, "run", self.fake_run):
            self.migration.run(MigrationContext(dry_run=dry_run))

    def test_reloads_and_starts_for_logged_in_users_only(self) -> None:
        self.run_migration()
        self.assertEqual([
            ["runuser", "-u", "caram", "--", "systemctl", "--user", "daemon-reload"],
            ["runuser", "-u", "caram", "--", "systemctl", "--user", "start", "caramos-daily-wallpaper.timer"],
        ], self.calls)

    def test_dry_run_and_a_missing_timer_do_nothing(self) -> None:
        self.run_migration(dry_run=True)
        self.assertEqual([], self.calls)
        with mock.patch.object(self.migration, "TIMER_FILE", self.root / "missing.timer"):
            self.run_migration()
        self.assertEqual([], self.calls)
