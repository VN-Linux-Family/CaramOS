"""Passwords typed into Cinnamon's own password boxes stay hidden while Vietnamese typing is on (ticket H-1200:
"CaramOS bị hiện mật khẩu khi nhập vào để cập nhật trong Trình quản lý cập nhật").

Cinnamon draws some password boxes itself (St.PasswordEntry): the polkit dialog that asks for the password before
Update Manager, Driver Check or the App Center installs anything, the keyring dialogs and the Wi-Fi/VPN secrets
dialog. They show dots, but unlike GNOME Shell's St, Cinnamon's never tells the input method that the box is for a
password: the content purpose of its text stays NORMAL. Fcitx5 then lets Lotus compose there, and Clutter draws the
word being composed (the preedit) in clear text next to the dots until the word is committed. Telex also changes
the password itself ("bans" becomes "bán"), so a right password can be refused.

Cinnamon's input method (js/misc/inputMethod.js, which passes the purpose to Fcitx5 through its IBus frontend) gets a
marked block: when the focused text belongs to an St.PasswordEntry or hides its letters, the purpose sent is
PASSWORD. Fcitx5 then types plain letters there and shows nothing in clear (its AllowInputMethodForPassword and
ShowPreeditForPassword are off by default), as it already does in GTK password boxes; Vietnamese typing stays on
everywhere else.

The block goes after a line of the file that is checked first; a file whose lines changed is left as it is. A
Cinnamon update puts the original file back: caramos_ota_update.cinnamon_patches makes the change again after each
one (debian/triggers). Cinnamon reads the file when it starts, so the change shows from the next login.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Keep passwords hidden in Cinnamon's password boxes while Vietnamese typing is on"

INPUT_METHOD_JS = Path("/usr/share/cinnamon/js/misc/inputMethod.js")
START = "// CARAMOS_PASSWORD_PURPOSE_START"
END = "// CARAMOS_PASSWORD_PURPOSE_END"
ANCHOR = "    vfunc_update_content_purpose(purpose) {\n"
BLOCK = f"""        {START} (ticket H-1200): Cinnamon's password boxes (St.PasswordEntry: polkit,
        // keyring, network secrets) hide their text but leave its purpose NORMAL, so Fcitx5 let Lotus compose there
        // and the word being composed showed in clear. Sent as a password, Fcitx5 types plain letters there.
        if (purpose == Clutter.InputContentPurpose.NORMAL) {{
            let caramosFocus = global.stage.get_key_focus();
            if (caramosFocus instanceof Clutter.Text &&
                (caramosFocus.password_char || caramosFocus.get_parent() instanceof imports.gi.St.PasswordEntry))
                purpose = Clutter.InputContentPurpose.PASSWORD;
        }}
        {END}
"""


def patched(source: str) -> str:
    """inputMethod.js with the block; the same text when it is there already, "" when the line it goes after is not
    there exactly once."""

    if source.count(START) == 1 and source.count(END) == 1:
        return source
    if START in source or END in source or source.count(ANCHOR) != 1:
        return ""
    return source.replace(ANCHOR, ANCHOR + BLOCK, 1)


def _write(path: Path, content: str) -> None:
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, path.stat().st_mode & 0o777)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def restore(context: MigrationContext, path: Path = INPUT_METHOD_JS) -> None:
    """Puts the block into Cinnamon's input method, when the file is the one it knows."""

    if path.is_symlink() or not path.is_file():
        context.log(f"no Cinnamon input method at {path}; nothing to change")
        return
    source = path.read_text(encoding="utf-8")
    new = patched(source)
    if not new:
        context.log(f"warning: {path} is not as expected; password boxes stay as they are")
        return
    if new == source:
        context.log("Cinnamon's password boxes are marked as passwords already")
        return
    context.log(f"mark Cinnamon's password boxes as passwords for the input method: {path}")
    if not context.dry_run:
        _write(path, new)


def run(context: MigrationContext) -> None:
    restore(context)
