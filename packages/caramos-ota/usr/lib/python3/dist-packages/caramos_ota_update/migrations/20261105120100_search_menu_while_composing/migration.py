"""Let the Start Menu search find apps while a word is still being typed in Vietnamese.

Lotus, in its Preedit mode, keeps the word being typed as a composition (preedit) until a space or Enter
ends it. The search box of the Cinnamenu Start Menu only searched what was committed to its text, so with
Vietnamese typing on ("V") it showed nothing while typing "fire", "may tinh" or "tiếng" (ticket H-1098; it
was noticed after switching the desktop to English, but it happened in any language). Cinnamon's input
method keeps the composition it shows (Main.inputMethod._preeditStr), and the entry signals cursor-changed
whenever it changes, so Cinnamenu now searches the text with the composition at the cursor, and searches
again as the composition changes.

Hook 0170 copies Cinnamenu from the spices repository, as it was when the ISO was built, into
/usr/share/cinnamon/applets, so CaramOS releases carry different Cinnamenu code: the 5.8 folder of the 1.3.1 ISO
connects the search entry in one line through `this.appThis`, the one of 1.3.3 over four lines through
`this.applet`. This patches each version folder whose code has the lines the change goes into, in either
form, and leaves any other one as it is. Cinnamenu is reloaded in the sessions of logged-in users, so the
menu works at once.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

DESCRIPTION = "Start Menu search finds apps while a word is still being typed in Vietnamese"

SYSTEMD_RUNTIME = Path("/run/systemd/system")
CINNAMENU = Path("/usr/share/cinnamon/applets/Cinnamenu@json")
UUID = "Cinnamenu@json"
MARKER = "// CaramOS: the word an input method is still composing"
RELOAD_TIMEOUT = 30

APPLET_OLD = """    _onSearchTextChanged() {
        const searchText = this.display.searchView.searchEntryText.get_text();
"""
APPLET_NEW = """    // CaramOS: the word an input method is still composing (the Lotus preedit) belongs to the search too.
    _withPreedit(text) {
        const entry = this.display.searchView.searchEntryText;
        const preedit = Main.inputMethod && entry.has_preedit() ? Main.inputMethod._preeditStr || '' : '';
        if (!preedit) {
            return text;
        }
        const position = entry.get_cursor_position();
        const at = position < 0 ? text.length : position;
        return text.slice(0, at) + preedit + text.slice(at);
    }

    _onSearchTextChanged() {
        const searchText = this._withPreedit(this.display.searchView.searchEntryText.get_text());
"""
# Where display.js connects the search entry's text-changed to the search, in one line or over several,
# through the applet's object (this.appThis in older Cinnamenu, this.applet in newer).
DISPLAY_SIGNAL = re.compile(
    r"(?P<indent>[ \t]*)this\.displaySignals\.connect\(\s*this\.searchView\.searchEntryText,\s*'text-changed',\s*"
    r"\(\.\.\.args\)\s*=>\s*this\.(?P<owner>appThis|applet)\._onSearchTextChanged\(\.\.\.args\)\s*\);[ \t]*\n")
DISPLAY_ADDITION = """{indent}// CaramOS: an input method changes its preedit (a word still being composed) without text-changed.
{indent}let composing = false;
{indent}this.displaySignals.connect(this.searchView.searchEntryText, 'cursor-changed', () => {{
{indent}    const now = this.searchView.searchEntryText.has_preedit();
{indent}    if (now || composing) {{
{indent}        this.{owner}._onSearchTextChanged();
{indent}    }}
{indent}    composing = now;
{indent}}});
"""


def patched(applet: str, display: str) -> tuple[str, str] | None:
    """Both files with the change; None when either does not have the lines it goes into."""

    signals = list(DISPLAY_SIGNAL.finditer(display))
    if applet.count(APPLET_OLD) != 1 or len(signals) != 1 or "Main = imports.ui.main" not in applet:
        return None
    signal = signals[0]
    addition = DISPLAY_ADDITION.format(indent=signal.group("indent"), owner=signal.group("owner"))
    return (applet.replace(APPLET_OLD, APPLET_NEW, 1),
            display[:signal.end()] + addition + display[signal.end():])


def _write(path: Path, content: str) -> None:
    mode = path.stat().st_mode & 0o777
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, mode)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def patch_folder(context: MigrationContext, folder: Path) -> bool:
    applet_path, display_path = folder / "applet.js", folder / "display.js"
    if not (applet_path.is_file() and display_path.is_file()) or applet_path.is_symlink() or display_path.is_symlink():
        return False
    applet = applet_path.read_text(encoding="utf-8")
    display = display_path.read_text(encoding="utf-8")
    if MARKER in applet:
        context.log(f"the search of {folder} already sees the input method's composition")
        return False
    result = patched(applet, display)
    if result is None:
        context.log(f"{folder} is another Cinnamenu version; leave it as it is")
        return False
    context.log(f"let the search of {folder} see the input method's composition")
    if not context.dry_run:
        # display.js first: on its own it only calls a search that already exists.
        _write(display_path, result[1])
        _write(applet_path, result[0])
    return True


def _reload_in_sessions(context: MigrationContext) -> None:
    for user in start_fcitx._desktop_users():
        environment = start_fcitx.session_environment(user.pw_uid)
        if environment is None:
            continue
        command = ["runuser", "-u", user.pw_name, "--", "env", "-i",
                   *(f"{name}={value}" for name, value in sorted(environment.items())),
                   "gdbus", "call", "--session", "--dest", "org.Cinnamon", "--object-path", "/org/Cinnamon",
                   "--method", "org.Cinnamon.ReloadXlet", UUID, "APPLET"]
        try:
            result = subprocess.run(command, check=False, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=RELOAD_TIMEOUT)
        except (OSError, subprocess.SubprocessError) as exc:
            context.log(f"warning: could not reload the Start Menu of {user.pw_name}, it changes at the next login: {exc}")
            continue
        if result.returncode == 0:
            context.log(f"reloaded the Start Menu of {user.pw_name}")
        else:
            context.log(f"warning: the Start Menu of {user.pw_name} changes at the next login")


def run(context: MigrationContext) -> None:
    if not CINNAMENU.is_dir():
        context.log(f"{CINNAMENU} is not installed")
        return
    changed = False
    for folder in sorted(path for path in CINNAMENU.iterdir() if path.is_dir() and not path.is_symlink()):
        changed = patch_folder(context, folder) or changed
    if changed and not context.dry_run and SYSTEMD_RUNTIME.is_dir():
        _reload_in_sessions(context)
