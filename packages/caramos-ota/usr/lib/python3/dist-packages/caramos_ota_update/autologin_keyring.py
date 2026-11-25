"""A keyring that opens by itself for a user LightDM logs in automatically, so that apps keep their sign-in.

Zalo, Lark, Chrome and other Electron and Chromium apps keep the key of their saved sign-in in the Secret Service's
default keyring (gnome-keyring). A login with a password unlocks the login keyring with that password (PAM,
pam_gnome_keyring). An automatic login has no password: there was no keyring at all, the first app that saved a
secret asked to "Choose password for new keyring", and with a password typed there the keyring was locked after every
automatic login, so apps asked for it again or lost their sign-in when the question was closed.

At every automatic login (LightDM's lightdm-autologin, the session's Service in logind), before the desktop starts,
/etc/X11/Xsession.d/96caramos-login-actions runs ensure() as the user:
- the default keyring opens without a password (one with an empty password, made here or by the person): nothing.
  A keyring loaded by a daemon that just started says Locked even with an empty password, so ensure() asks the
  Secret Service to Unlock it: gnome-keyring opens a keyring with an empty password at once, and for one with a
  password only returns a prompt, which is never shown here (Dismiss);
- else a keyring CaramOS made before (LABELS) that opens without a password becomes the default again;
- else a new keyring with an empty password, which gnome-keyring keeps unencrypted and never locks, is made and
  becomes the default: gnome-keyring's own CreateWithMasterPassword with an empty secret, then SetAlias("default").
  On a computer that opens the session without a password it adds nothing anyone at the computer could not read.
A keyring with a password that apps open by themselves (the default one, such as the "Default keyring" made by that
question, and the login keyring of someone who logged in with a password before) is moved first, before gnome-keyring
reads the keyrings, into ~/.local/share/keyrings/locked-by-password, where gnome-keyring does not look (set_aside):
nothing could open it after an automatic login, so apps asked for its password at every login. Nothing is deleted:
README.txt there says how to get its secrets back. New secrets go to the new keyring; an app whose key was in the old
one signs in once more. Keyrings people made themselves under another name stay where they are.

Logins with a password are never touched. gnome-keyring is started through its systemd user unit first: asked through
D-Bus before that, D-Bus started a second gnome-keyring-daemon (--start) that stayed idle for the whole session
(about 9 MB, seen on the Xfce edition, where xdg-desktop-portal asks for the Secret Service at login).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

SERVICE = "org.freedesktop.secrets"
PATH = "/org/freedesktop/secrets"
SERVICE_INTERFACE = "org.freedesktop.Secret.Service"
COLLECTION_INTERFACE = "org.freedesktop.Secret.Collection"
INTERNAL_INTERFACE = "org.gnome.keyring.InternalUnsupportedGuiltRiddenInterface"
LABEL_PROPERTY = "org.freedesktop.Secret.Collection.Label"
UNIT = "gnome-keyring-daemon.service"
AUTOLOGIN_SERVICE = "lightdm-autologin"
# The label of the keyring made here, and its Vietnamese name; Seahorse (Passwords and Keys) shows it.
LABEL = "Automatic login"
LABELS = (LABEL, "Đăng nhập tự động")
WAIT_SECONDS = 5
TIMEOUT_MS = 20000
# ~/.local/share/keyrings: <name>.keyring files, and "default", the name of the default keyring.
KEYRINGS = Path(".local/share/keyrings")
SET_ASIDE = "locked-by-password"
# gnome-keyring writes a keyring with a password in its encrypted binary format, one without in a text format.
BINARY_HEADER = b"GnomeKeyring\n\r\x00\n"
README = """Các chùm chìa khoá trong thư mục này có mật khẩu. Máy này tự đăng nhập, không gõ mật khẩu, nên không mở được
chúng, và ứng dụng cứ hỏi mật khẩu của chúng mỗi lần đăng nhập. CaramOS đã cất chúng vào đây; máy dùng một chùm chìa khoá
không mật khẩu thay thế. Không có gì bị xoá.

Cần lấy lại mật khẩu đã lưu trong một chùm chìa khoá cũ: chép file .keyring của nó về thư mục ~/.local/share/keyrings,
mở “Mật khẩu và khoá”, mở khoá nó bằng mật khẩu cũ, rồi chép thứ cần lấy, hoặc đổi mật khẩu của nó thành để trống.

The keyrings in this folder have a password. This computer logs in by itself, without a password, so it could not open
them, and apps asked for their password at every login. CaramOS moved them here; the computer uses a keyring without a
password instead. Nothing was deleted.

To get back what an old keyring holds: copy its .keyring file back to ~/.local/share/keyrings, open Passwords and Keys,
unlock it with the old password, then copy what you need, or change its password to an empty one.
"""

READY = "ready"            # the default keyring opens by itself already
SWITCHED = "switched"      # an unlocked keyring made here before is the default again
MADE = "made"              # a new keyring with an empty password is the default
UNAVAILABLE = "unavailable"   # no Secret Service (gnome-keyring is not installed or does not start)
FAILED = "failed"

Runner = Callable[[list[str]], "subprocess.CompletedProcess[str]"]


def autologin_session(environ: Mapping[str, str], run: Runner) -> bool:
    """This login is LightDM's automatic login (and not a login with a password, nor SSH)."""

    session = environ.get("XDG_SESSION_ID", "")
    if not session:
        return False
    result = run(["loginctl", "show-session", session, "-p", "Service", "--value"])
    return result.returncode == 0 and result.stdout.strip() == AUTOLOGIN_SERVICE


class SecretService:
    """The calls ensure() makes, on the session bus; replaced in the tests."""

    def __init__(self, run: Runner) -> None:
        from gi.repository import Gio, GLib

        self.Gio, self.GLib = Gio, GLib
        self.run = run
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)

    def start(self) -> bool:
        """gnome-keyring through its systemd unit (not through D-Bus: see above); whether the service answers."""

        if self.run(["systemctl", "--user", "start", UNIT]).returncode != 0:
            # No such unit (an older gnome-keyring): D-Bus starts it.
            try:
                self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                   "StartServiceByName", self.GLib.Variant("(su)", (SERVICE, 0)),
                                   self.GLib.VariantType("(u)"), self.Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
            except self.GLib.Error:
                return False
        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            try:
                owner = self.bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                           "NameHasOwner", self.GLib.Variant("(s)", (SERVICE,)),
                                           self.GLib.VariantType("(b)"), self.Gio.DBusCallFlags.NONE, TIMEOUT_MS,
                                           None).unpack()[0]
            except self.GLib.Error:
                owner = False
            if owner or time.monotonic() > deadline:
                return bool(owner)
            time.sleep(0.2)

    def _call(self, path: str, interface: str, method: str, parameters, reply: str | None) -> Any:
        result = self.bus.call_sync(SERVICE, path, interface, method, parameters,
                                    self.GLib.VariantType(reply) if reply else None,
                                    self.Gio.DBusCallFlags.NO_AUTO_START, TIMEOUT_MS, None)
        return result.unpack() if result is not None else None

    def _property(self, path: str, name: str) -> Any:
        return self._call(path, "org.freedesktop.DBus.Properties", "Get",
                          self.GLib.Variant("(ss)", (COLLECTION_INTERFACE, name)), "(v)")[0]

    def default(self) -> str:
        return self._call(PATH, SERVICE_INTERFACE, "ReadAlias", self.GLib.Variant("(s)", ("default",)), "(o)")[0]

    def collections(self) -> list[str]:
        return list(self._call(PATH, "org.freedesktop.DBus.Properties", "Get",
                               self.GLib.Variant("(ss)", (SERVICE_INTERFACE, "Collections")), "(v)")[0])

    def opens(self, path: str) -> bool:
        """Whether the keyring opens without a password: Unlock opens one with an empty password at once; for one
        with a password it returns a prompt, which is dismissed, never shown."""

        unlocked, prompt = self._call(PATH, SERVICE_INTERFACE, "Unlock", self.GLib.Variant("(ao)", ([path],)), "(aoo)")
        if prompt not in ("", "/"):
            try:
                self._call(prompt, "org.freedesktop.Secret.Prompt", "Dismiss", None, None)
            except self.GLib.Error:
                pass
        return path in unlocked

    def label(self, path: str) -> str:
        return str(self._property(path, "Label"))

    def create(self, label: str) -> str:
        """A keyring with an empty password: gnome-keyring keeps it unencrypted and never locks it."""

        session = self._call(PATH, SERVICE_INTERFACE, "OpenSession",
                             self.GLib.Variant("(sv)", ("plain", self.GLib.Variant("s", ""))), "(vo)")[1]
        properties = {LABEL_PROPERTY: self.GLib.Variant("s", label)}
        return self._call(PATH, INTERNAL_INTERFACE, "CreateWithMasterPassword",
                          self.GLib.Variant("(a{sv}(oayays))", (properties, (session, b"", b"", "text/plain"))),
                          "(o)")[0]

    def set_default(self, path: str) -> None:
        self._call(PATH, SERVICE_INTERFACE, "SetAlias", self.GLib.Variant("(so)", ("default", path)), None)


def label_for(environ: Mapping[str, str]) -> str:
    """The new keyring's name in the language of the session."""

    language = next((environ.get(name) for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG") if environ.get(name)),
                    "")
    return LABELS[1] if language.startswith("vi") else LABELS[0]


def password_keyrings(directory: Path) -> list[Path]:
    """The keyrings apps open by themselves (the default one and the login one) that have a password."""

    names = {"login"}
    try:
        default = (directory / "default").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        default = ""
    if default and "/" not in default and not default.startswith("."):
        names.add(default)
    found = []
    for name in sorted(names):
        path = directory / f"{name}.keyring"
        try:
            with path.open("rb") as handle:
                header = handle.read(len(BINARY_HEADER))
        except OSError:
            continue
        if header == BINARY_HEADER and not path.is_symlink():
            found.append(path)
    return found


def set_aside(directory: Path, log: Callable[[str], None]) -> list[Path]:
    """Move the keyrings with a password that apps open by themselves into directory/locked-by-password, where
    gnome-keyring does not look; where they went."""

    keyrings = password_keyrings(directory)
    if not keyrings:
        return []
    target = directory / SET_ASIDE
    target.mkdir(mode=0o700, exist_ok=True)
    readme = target / "README.txt"
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    moved = []
    for path in keyrings:
        destination = target / path.name
        if destination.exists():
            destination = target / f"{path.stem}-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}"
        path.rename(destination)
        moved.append(destination)
        log(f"the keyring {path.name} has a password nothing can type here: moved to {destination}")
    return moved


def ensure(service, log: Callable[[str], None], label: str = LABEL, keyrings: Path | None = None) -> str:
    """The default keyring opens by itself after this automatic login: how it went (READY, SWITCHED, MADE...).
    keyrings: the user's ~/.local/share/keyrings, whose keyrings with a password are set aside first."""

    moved: list[Path] = []
    if keyrings is not None:
        try:
            moved = set_aside(keyrings, log)
        except OSError as exc:
            log(f"warning: could not set the keyrings with a password aside: {exc}")
    if not service.start():
        log("no Secret Service (gnome-keyring): nothing to do")
        return UNAVAILABLE
    try:
        default = service.default()
        if default not in ("", "/") and service.opens(default):
            log("the default keyring opens without a password already")
            return READY
        for path in service.collections():
            if path.endswith("/session") or path == default:
                continue
            name = service.label(path)
            if name in LABELS and service.opens(path):
                service.set_default(path)
                log(f"the keyring “{name}”, without a password, is the default again")
                return SWITCHED
        path = service.create(label)
        service.set_default(path)
        if not service.opens(path):
            log(f"warning: the new keyring “{label}” does not open")
            return FAILED
        if moved:
            what = "the keyring with a password is set aside"
        elif default in ("", "/"):
            what = "no keyring yet"
        else:
            what = "the default keyring has a password; it stays as it is"
        log(f"{what}: the keyring “{label}”, without a password, is the default now")
        return MADE
    except Exception as exc:   # noqa: BLE001 - the login goes on, and the next one tries again
        log(f"warning: the keyring could not be set up: {exc}")
        return FAILED
