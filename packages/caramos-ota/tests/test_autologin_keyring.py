"""A keyring that opens by itself after LightDM's automatic login (caramos_ota_update.autologin_keyring, migration
20261125130100): apps such as Zalo and Lark keep their sign-in; logins with a password are left alone."""

from __future__ import annotations

import importlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update import autologin_keyring as keyring
from caramos_ota_update import deferred
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261125130100_autologin_keyring"
migration = importlib.import_module("caramos_ota_update.migrations.20261125130100_autologin_keyring.migration")
OLD = "/org/freedesktop/secrets/collection/Default_5fkeyring"
OURS = "/org/freedesktop/secrets/collection/Automatic_5flogin"
SESSION = "/org/freedesktop/secrets/collection/session"


def done(code: int = 0, out: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, "")


class FakeService:
    """gnome-keyring as ensure() sees it: collections with a label and a lock, and the default alias."""

    def __init__(self, collections: dict[str, tuple[str, bool]], default: str = "/", running: bool = True,
                 made_locked: bool = False) -> None:
        self.collections_ = dict(collections)
        self.default_ = default
        self.running = running
        self.made_locked = made_locked
        self.calls: list[tuple] = []

    def start(self) -> bool:
        self.calls.append(("start",))
        return self.running

    def default(self) -> str:
        return self.default_

    def collections(self) -> list[str]:
        return list(self.collections_)

    def opens(self, path: str) -> bool:
        self.calls.append(("opens", path))
        return not self.collections_[path][1]

    def label(self, path: str) -> str:
        return self.collections_[path][0]

    def create(self, label: str) -> str:
        self.calls.append(("create", label))
        self.collections_[OURS] = (label, self.made_locked)
        return OURS

    def set_default(self, path: str) -> None:
        self.calls.append(("set_default", path))
        self.default_ = path


class EnsureTests(unittest.TestCase):
    def ensure(self, service: FakeService) -> tuple[str, list[str]]:
        messages: list[str] = []
        return keyring.ensure(service, messages.append, "Automatic login"), messages

    def test_no_keyring_yet_one_without_a_password_becomes_the_default(self) -> None:
        service = FakeService({SESSION: ("Session", False)})
        outcome, messages = self.ensure(service)
        self.assertEqual(keyring.MADE, outcome)
        self.assertEqual([("start",), ("create", "Automatic login"), ("set_default", OURS), ("opens", OURS)],
                         service.calls)
        self.assertIn("no keyring yet", messages[-1])

    def test_a_locked_keyring_with_a_password_stays_and_a_new_one_is_the_default(self) -> None:
        # Someone typed a password at "Choose password for new keyring": locked after every automatic login.
        service = FakeService({SESSION: ("Session", False), OLD: ("Default keyring", True)}, default=OLD)
        outcome, messages = self.ensure(service)
        self.assertEqual(keyring.MADE, outcome)
        self.assertEqual(OURS, service.default_)
        self.assertEqual(("Default keyring", True), service.collections_[OLD], "the old one is not touched")
        self.assertIn("has a password; it stays as it is", messages[-1])

    def test_a_default_that_opens_by_itself_is_left_alone(self) -> None:
        for label in ("Default keyring", "Automatic login", "Login"):
            with self.subTest(label=label):
                service = FakeService({OLD: (label, False)}, default=OLD)
                self.assertEqual(keyring.READY, self.ensure(service)[0])
                self.assertEqual([("start",), ("opens", OLD)], service.calls)

    def test_the_keyring_made_before_becomes_the_default_again(self) -> None:
        for label in keyring.LABELS:
            with self.subTest(label=label):
                service = FakeService({OLD: ("Default keyring", True), OURS: (label, False)}, default=OLD)
                self.assertEqual(keyring.SWITCHED, self.ensure(service)[0])
                self.assertEqual([("start",), ("opens", OLD), ("opens", OURS), ("set_default", OURS)],
                                 service.calls)

    def test_another_unlocked_keyring_is_not_taken_over(self) -> None:
        other = "/org/freedesktop/secrets/collection/Work"
        service = FakeService({OLD: ("Default keyring", True), other: ("Work", False)}, default=OLD)
        self.assertEqual(keyring.MADE, self.ensure(service)[0])
        self.assertEqual(OURS, service.default_)

    def test_without_gnome_keyring_or_when_it_fails(self) -> None:
        service = FakeService({}, running=False)
        self.assertEqual(keyring.UNAVAILABLE, self.ensure(service)[0])
        self.assertEqual([("start",)], service.calls)
        self.assertEqual(keyring.FAILED, self.ensure(FakeService({}, made_locked=True))[0])
        broken = FakeService({})
        broken.create = mock.Mock(side_effect=RuntimeError("org.freedesktop.DBus.Error.UnknownMethod"))
        outcome, messages = self.ensure(broken)
        self.assertEqual(keyring.FAILED, outcome)
        self.assertIn("UnknownMethod", messages[-1])

    def test_the_name_follows_the_language_of_the_session(self) -> None:
        self.assertEqual("Đăng nhập tự động", keyring.label_for({"LANG": "vi_VN.UTF-8"}))
        self.assertEqual("Đăng nhập tự động", keyring.label_for({"LANGUAGE": "vi", "LANG": "en_US.UTF-8"}))
        self.assertEqual("Automatic login", keyring.label_for({"LANG": "en_US.UTF-8"}))
        self.assertEqual("Automatic login", keyring.label_for({}))


BINARY = keyring.BINARY_HEADER + b"\x00\x00 encrypted"
TEXT = b"[keyring]\ndisplay-name=Automatic login\nlock-on-idle=false\n"


class SetAsideTests(unittest.TestCase):
    """Keyrings with a password that apps open by themselves go to locked-by-password before gnome-keyring reads
    them; nothing is deleted."""

    def setUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        self.dir = Path(self.folder.name)
        self.messages: list[str] = []

    def tearDown(self) -> None:
        self.folder.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        path = self.dir / name
        path.write_bytes(data)
        return path

    def test_the_default_and_the_login_keyring_with_a_password_are_moved(self) -> None:
        self.write("default", b"Default_keyring")
        self.write("Default_keyring.keyring", BINARY)
        self.write("login.keyring", BINARY)
        self.write("Automatic_login.keyring", TEXT)
        self.write("Work.keyring", BINARY)

        moved = keyring.set_aside(self.dir, self.messages.append)

        aside = self.dir / keyring.SET_ASIDE
        self.assertEqual([aside / "Default_keyring.keyring", aside / "login.keyring"], moved)
        self.assertEqual(BINARY, (aside / "login.keyring").read_bytes())
        self.assertFalse((self.dir / "login.keyring").exists())
        self.assertFalse((self.dir / "Default_keyring.keyring").exists())
        # A keyring without a password, and one the person made under another name, stay.
        self.assertTrue((self.dir / "Automatic_login.keyring").exists())
        self.assertTrue((self.dir / "Work.keyring").exists())
        self.assertIn("Không có gì bị xoá", (aside / "README.txt").read_text(encoding="utf-8"))
        self.assertEqual(0o700, aside.stat().st_mode & 0o777)
        self.assertEqual(2, len(self.messages))

    def test_keyrings_without_a_password_stay(self) -> None:
        self.write("default", b"login")
        self.write("login.keyring", TEXT)
        self.assertEqual([], keyring.set_aside(self.dir, self.messages.append))
        self.assertFalse((self.dir / keyring.SET_ASIDE).exists())

    def test_no_keyrings_folder_yet(self) -> None:
        self.assertEqual([], keyring.set_aside(self.dir / "missing", self.messages.append))

    def test_a_name_already_set_aside_is_kept(self) -> None:
        aside = self.dir / keyring.SET_ASIDE
        aside.mkdir()
        (aside / "login.keyring").write_bytes(b"first")
        self.write("login.keyring", BINARY)
        moved = keyring.set_aside(self.dir, self.messages.append)
        self.assertEqual(1, len(moved))
        self.assertRegex(moved[0].name, r"^login-\d{8}-\d{6}\.keyring$")
        self.assertEqual(b"first", (aside / "login.keyring").read_bytes())

    def test_the_default_file_cannot_point_outside_the_folder(self) -> None:
        self.write("default", b"../../.ssh/id_ed25519")
        self.assertEqual([], keyring.password_keyrings(self.dir))

    def test_ensure_sets_them_aside_before_gnome_keyring_reads_them(self) -> None:
        self.write("login.keyring", BINARY)
        service = FakeService({})
        order: list[str] = []
        real_start = service.start

        def start() -> bool:
            order.append("start" if (self.dir / keyring.SET_ASIDE / "login.keyring").exists() else "start-too-early")
            return real_start()

        service.start = start
        self.assertEqual(keyring.MADE, keyring.ensure(service, self.messages.append, "Automatic login", self.dir))
        self.assertEqual(["start"], order)
        self.assertIn("the keyring with a password is set aside", self.messages[-1])

    def test_ensure_goes_on_when_the_folder_cannot_be_changed(self) -> None:
        service = FakeService({})
        with mock.patch.object(keyring, "set_aside", side_effect=PermissionError("read-only")):
            self.assertEqual(keyring.MADE, keyring.ensure(service, self.messages.append, "Automatic login", self.dir))
        self.assertIn("could not set the keyrings with a password aside", self.messages[0])


class SessionTests(unittest.TestCase):
    def test_only_lightdms_automatic_login(self) -> None:
        def answer(service: str):
            return lambda args: done(0, service + "\n") if args[:2] == ["loginctl", "show-session"] else done(1)

        environ = {"XDG_SESSION_ID": "c2"}
        self.assertTrue(keyring.autologin_session(environ, answer("lightdm-autologin")))
        for service in ("lightdm", "sshd", "gdm-password", ""):
            with self.subTest(service=service):
                self.assertFalse(keyring.autologin_session(environ, answer(service)))
        self.assertFalse(keyring.autologin_session({}, answer("lightdm-autologin")))
        self.assertFalse(keyring.autologin_session(environ, lambda _args: done(1)))


class FakeBus:
    """The session bus as SecretService uses it: records each call and answers like gnome-keyring."""

    def __init__(self, GLib, unlock: tuple[list[str], str] = ([OURS], "/")) -> None:
        self.GLib = GLib
        self.unlock = unlock
        self.calls: list[tuple] = []

    def call_sync(self, name, path, interface, method, parameters, reply_type, _flags, _timeout,  # noqa: ANN001
                  _cancellable):
        self.calls.append((name, path, interface, method, parameters.unpack() if parameters is not None else None,
                           reply_type.dup_string() if reply_type is not None else None))
        V = self.GLib.Variant
        answers = {
            "NameHasOwner": V("(b)", (True,)),
            "ReadAlias": V("(o)", ("/",)),
            "OpenSession": V("(vo)", (V("s", ""), "/org/freedesktop/secrets/session/s1")),
            "CreateWithMasterPassword": V("(o)", (OURS,)),
            "Get": V("(v)", (V("b", False),)),
            "Unlock": V("(aoo)", self.unlock),
        }
        return answers.get(method)


class SecretServiceTests(unittest.TestCase):
    def test_a_keyring_with_a_password_is_never_prompted_for(self) -> None:
        try:
            from gi.repository import GLib
        except ImportError:   # the package builders have no PyGObject
            self.skipTest("PyGObject is not installed")
        service = keyring.SecretService.__new__(keyring.SecretService)
        service.Gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0, NO_AUTO_START=1))
        service.GLib = GLib
        service.bus = FakeBus(GLib, unlock=([], "/org/freedesktop/secrets/prompt/p1"))
        self.assertFalse(service.opens(OLD))
        self.assertEqual(["Unlock", "Dismiss"], [call[3] for call in service.bus.calls],
                         "the prompt object is dismissed, never shown (Prompt is not called)")
        service.bus = FakeBus(GLib, unlock=([OURS], "/"))
        self.assertTrue(service.opens(OURS))
        self.assertEqual(["Unlock"], [call[3] for call in service.bus.calls])

    def test_the_calls_to_gnome_keyring(self) -> None:
        try:
            from gi.repository import GLib
        except ImportError:   # the package builders have no PyGObject
            self.skipTest("PyGObject is not installed")
        commands = []
        service = keyring.SecretService.__new__(keyring.SecretService)
        service.Gio = SimpleNamespace(DBusCallFlags=SimpleNamespace(NONE=0, NO_AUTO_START=1))
        service.GLib = GLib
        service.bus = FakeBus(GLib)
        service.run = lambda args: commands.append(args) or done()
        self.assertTrue(service.start())
        self.assertEqual([["systemctl", "--user", "start", "gnome-keyring-daemon.service"]], commands,
                         "the systemd unit, not D-Bus activation: no second daemon")
        self.assertEqual("/", service.default())
        self.assertEqual(OURS, service.create("Automatic login"))
        service.set_default(OURS)
        create = next(call for call in service.bus.calls if call[3] == "CreateWithMasterPassword")
        self.assertEqual(("org.freedesktop.secrets", "/org/freedesktop/secrets",
                          "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"), create[:3])
        properties, secret = create[4]
        self.assertEqual({"org.freedesktop.Secret.Collection.Label": "Automatic login"}, properties)
        session, parameters, value, content_type = secret
        self.assertEqual("/org/freedesktop/secrets/session/s1", session)
        self.assertEqual((b"", b"", "text/plain"), (bytes(parameters), bytes(value), content_type), "an empty password")
        alias = service.bus.calls[-1]
        self.assertEqual(("SetAlias", ("default", OURS)), (alias[3], alias[4]))
        opened = next(call for call in service.bus.calls if call[3] == "OpenSession")
        self.assertEqual(("plain", ""), opened[4])


class LoginCommandTests(unittest.TestCase):
    def run_main(self, autologin: bool, queued: bool) -> tuple[mock.Mock, mock.Mock]:
        with tempfile.TemporaryDirectory() as folder:
            queue = Path(folder)
            if queued:
                (queue / "1000.json").write_text(json.dumps({"schema": 1, "user": "minh", "actions": []}),
                                                 encoding="utf-8")
            user = SimpleNamespace(pw_name="minh", pw_dir=folder)
            # A Vietnamese session's locale, and only that: Launchpad builds with LC_ALL=C.UTF-8, which comes before
            # LANG (label_for), so leaving the machine's other locale variables in made the label English there.
            session_locale = {"LANG": "vi_VN.UTF-8", "LANGUAGE": "", "LC_ALL": "", "LC_MESSAGES": ""}
            with mock.patch.object(os, "getuid", return_value=1000), \
                    mock.patch.object(deferred.pwd, "getpwuid", return_value=user), \
                    mock.patch.object(keyring, "autologin_session", return_value=autologin), \
                    mock.patch.object(keyring, "ensure", return_value=keyring.MADE) as ensure, \
                    mock.patch.object(deferred, "run_pending") as pending, \
                    mock.patch.dict(os.environ, session_locale):
                self.assertEqual(0, deferred.main([], queue_dir=queue, keyring=lambda run: "service"))
        return ensure, pending

    def test_an_automatic_login_gets_the_keyring_first(self) -> None:
        ensure, pending = self.run_main(autologin=True, queued=True)
        self.assertEqual(("service",), ensure.call_args.args[:1])
        self.assertEqual("Đăng nhập tự động", ensure.call_args.args[2])
        keyrings = ensure.call_args.kwargs["keyrings"]   # the user's ~/.local/share/keyrings
        self.assertEqual(Path(".local/share/keyrings"), keyrings.relative_to(keyrings.parents[2]))
        pending.assert_called_once()

    def test_a_login_with_a_password_is_left_alone(self) -> None:
        ensure, pending = self.run_main(autologin=False, queued=False)
        ensure.assert_not_called()
        pending.assert_not_called()

    def test_a_keyring_failure_does_not_stop_the_waiting_steps(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            queue = Path(folder)
            (queue / "1000.json").write_text(json.dumps({"schema": 1, "user": "minh", "actions": []}),
                                             encoding="utf-8")
            user = SimpleNamespace(pw_name="minh", pw_dir=folder)
            with mock.patch.object(os, "getuid", return_value=1000), \
                    mock.patch.object(deferred.pwd, "getpwuid", return_value=user), \
                    mock.patch.object(keyring, "autologin_session", return_value=True), \
                    mock.patch.object(keyring, "ensure", side_effect=RuntimeError("no bus")), \
                    mock.patch.object(deferred, "run_pending") as pending, mock.patch("sys.stderr"):
                self.assertEqual(0, deferred.main([], queue_dir=queue, keyring=lambda run: "service"))
        pending.assert_called_once()

    def test_the_xsession_hook_runs_for_automatic_logins(self) -> None:
        hook = (ROOT / "etc/X11/Xsession.d/96caramos-login-actions").read_text(encoding="utf-8")
        self.assertIn('loginctl show-session "${XDG_SESSION_ID:-none}" -p Service --value', hook)
        self.assertIn('[ "$CARAMOS_LOGIN_SERVICE" = lightdm-autologin ]', hook)
        sourced = subprocess.run(["sh", "-c", 'set -e; XDG_SESSION_ID=none; . "$1"; echo ok', "sh",
                                  str(ROOT / "etc/X11/Xsession.d/96caramos-login-actions")],
                                 capture_output=True, text=True, check=False)
        self.assertEqual("ok", sourced.stdout.strip(), "Xsession runs with set -e: the login must go on")


class MigrationTests(unittest.TestCase):
    def test_who_lightdm_logs_in(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.assertEqual("", migration.autologin_user(root))
            share = root / "usr/share/lightdm/lightdm.conf.d"
            share.mkdir(parents=True)
            (share / "50-x.conf").write_text("[Seat:*]\nautologin-user=old\n", encoding="utf-8")
            (root / "etc/lightdm").mkdir(parents=True)
            (root / "etc/lightdm/lightdm.conf").write_text("[Seat:*]\nautologin-guest=false\nautologin-user=minh\n",
                                                           encoding="utf-8")
            self.assertEqual("minh", migration.autologin_user(root), "lightdm.conf comes last")
            context = MigrationContext(unattended=True)
            with mock.patch.object(context, "log") as log:
                migration.run(context, root)
            self.assertIn("LightDM logs minh in automatically", log.call_args.args[0])

    def test_manifest(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("anytime", manifest["unattended"], "it changes nothing on an open desktop")
        self.assertNotIn("desktops", manifest, "both editions")
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("một lần cuối", " ".join(manifest["release_notes_vi"]), "Zalo and Lark may ask once more")
        self.assertIn("one last time", " ".join(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()
