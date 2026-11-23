"""Telex or VNI: the typing method of Lotus, CaramOS's Vietnamese input method (Fcitx 5).

Lotus keeps its settings in ~/.config/fcitx5/conf/lotus.conf (InputMethod="Telex" by default, from /etc/skel; the
values are those of the Lotus settings window). While Fcitx runs, the setting changes through Fcitx's own D-Bus
interface, as the settings window does, and Fcitx writes the file at once; otherwise the file is written here and
Fcitx reads it when it starts.
"""

from __future__ import annotations

import re
from pathlib import Path

TELEX, VNI = "Telex", "VNI"
CONF = Path(".config/fcitx5/conf/lotus.conf")
SKEL = Path("/etc/skel/.config/fcitx5/conf/lotus.conf")
_LINE = re.compile(r'^(\s*InputMethod\s*=\s*)"?([^"\n]*)"?\s*$', re.M)


def current(home: Path | None = None) -> str | None:
    try:
        text = ((home or Path.home()) / CONF).read_text(encoding="utf-8")
    except OSError:
        return None
    match = _LINE.search(text)
    return match.group(2).strip() if match else None


def with_method(text: str, method: str) -> str:
    if _LINE.search(text):
        return _LINE.sub(lambda match: f'{match.group(1)}"{method}"', text, count=1)
    return text.rstrip("\n") + ("\n" if text.strip() else "") + f'InputMethod="{method}"\n'


def write_conf(method: str, home: Path | None = None, skel: Path = SKEL) -> Path:
    path = (home or Path.home()) / CONF
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        try:
            text = skel.read_text(encoding="utf-8")
        except OSError:
            text = ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(with_method(text, method), encoding="utf-8")
    return path


def set_method(method: str, home: Path | None = None) -> str:
    """Set Lotus to Telex or VNI; returns "fcitx" when the running Fcitx took it, "file" otherwise."""

    if method not in (TELEX, VNI):
        raise ValueError(method)
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        config = GLib.Variant("a{sv}", {"InputMethod": GLib.Variant("s", method)})
        bus.call_sync("org.fcitx.Fcitx5", "/controller", "org.fcitx.Fcitx.Controller1", "SetConfig",
                      GLib.Variant("(sv)", ("fcitx://config/addon/lotus", config)), None, Gio.DBusCallFlags.NONE,
                      5000, None)
        if current(home) == method:
            return "fcitx"
    except Exception:   # noqa: BLE001 - no Fcitx, no D-Bus, or an older Fcitx: write the file instead
        pass
    write_conf(method, home)
    return "file"
