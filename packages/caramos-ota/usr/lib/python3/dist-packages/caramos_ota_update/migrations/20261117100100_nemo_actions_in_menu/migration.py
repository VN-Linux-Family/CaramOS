"""Put the three Nemo actions CaramOS installs into the right-click menu of the file manager.

Hook 0170 copies three actions from cinnamon-spices-actions into /usr/share/nemo/actions: Copy path to clipboard
(copy-path-to-clipboard@claudiux), Create a desktop shortcut (create-desktop-shortcut@anaximeno) and Send with KDE
Connect (send-with-kdeconnect@rcalixte). It copied only each spice's files/<uuid> folder. The action file Nemo
reads, <uuid>.nemo_action, is built from <uuid>.nemo_action.in at the root of the spice, so the menu never had
the actions. This writes /usr/share/nemo/actions/<uuid>.nemo_action for each:

- from the spice's own template when the ISO kept it (<uuid>/<uuid>.nemo_action.in, since 1.3.11), or else the
  template below, taken from cinnamon-spices-actions on 2026-11-17;
- with Name and Comment in every language of the spice's po/ folder (Name[vi]=…), as the Cinnamon Spices website
  builds them, since Nemo reads translated names from the action file;
- Copy path runs its script from /usr/share/nemo/actions, not ~/.local/share/nemo/actions (a per-user install).

Nemo hides an action whose dependency is missing: xclip, which Copy path uses on X11, is installed when it is
missing. Send with KDE Connect shows up once KDE Connect (and xenity) are installed. The dialogs of Create a
desktop shortcut look for their translations in ~/.local/share/locale, so its po/ folder is compiled there for
every user and /etc/skel, as 20261016220000_translate_cinnamon_spices does for the Cinnamon spices.

An action whose folder is gone is skipped, and an action file already there is kept. Hiding an action (Nemo >
Edit > Plugins) stays the user's choice. Nemo picks the new actions up at once.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Show the Nemo actions CaramOS installs in the file manager's right-click menu"

ACTIONS = Path("/usr/share/nemo/actions")
XCLIP = Path("/usr/bin/xclip")
USER_ACTIONS = Path(".local/share/nemo/actions")
TRANSLATE_SPICES = "caramos_ota_update.migrations.20261016220000_translate_cinnamon_spices.migration"
TRANSLATABLE = ("Name", "Comment")
LANGUAGE_RE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?(@[a-z]+)?$")

# <uuid>.nemo_action.in of cinnamon-spices-actions (master, 2026-11-17).
TEMPLATES = {
    "copy-path-to-clipboard@claudiux": """\
[Nemo Action]
_Name=Copy path to clipboard
_Comment=Copy the full path of the selected item to the clipboard
Exec=/usr/bin/env bash -c '$HOME/.local/share/nemo/actions/copy-path-to-clipboard@claudiux/copy-pah.sh %F %U'
Selection=notnone
Extensions=any
Quote=double
EscapeSpaces=true
Icon-Name=edit-copy
Dependencies=xclip;
""",
    "create-desktop-shortcut@anaximeno": """\
[Nemo Action]
_Name=Create a desktop shortcut
_Comment=Create a shortcut of the selected items on the Desktop folder
Icon-Name=emblem-symbolic-link
Dependencies=python3;bash;
Exec=<create-desktop-shortcut@anaximeno/action.py "%F">
Conditions=exec <create-desktop-shortcut@anaximeno/check.sh "%P">;
Extensions=any;
Selection=notnone
Separator=" "
""",
    "send-with-kdeconnect@rcalixte": """\
[Nemo Action]
_Name=Send with KDE Connect
_Comment=Send file(s) to a paired device
Exec=<send-with-kdeconnect@rcalixte/send-with-kdeconnect@rcalixte.sh %F>
Icon-Name=kdeconnect
Selection=notnone
Extensions=nodirs;
Dependencies=gettext;kdeconnect-cli;xenity;
""",
}
# Actions whose own windows are translated through ~/.local/share/locale.
RUNTIME_TRANSLATED = ("create-desktop-shortcut@anaximeno",)


def _unquote(text: str) -> str:
    """The value of a po string literal, without its quotes."""

    out = []
    chars = iter(text[1:-1])
    for char in chars:
        if char == "\\":
            escaped = next(chars, "")
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(escaped, escaped))
        else:
            out.append(char)
    return "".join(out)


def read_po(text: str) -> dict[str, str]:
    """msgid -> msgstr of a po file: translated, non-fuzzy, single-form entries only."""

    entries: dict[str, str] = {}
    state: dict[str, object] = {"msgid": None, "msgstr": None, "current": None, "fuzzy": False}

    def finish() -> None:
        if state["msgid"] and state["msgstr"] and not state["fuzzy"]:
            entries[str(state["msgid"])] = str(state["msgstr"])
        state.update(msgid=None, msgstr=None, current=None, fuzzy=False)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            finish()
        elif line.startswith("#"):
            if state["msgstr"] is not None:   # the comments of the next entry
                finish()
            if line.startswith("#,") and "fuzzy" in line:
                state["fuzzy"] = True
        elif line.startswith("msgid ") and line[6:].startswith('"'):
            if state["msgstr"] is not None:
                finish()
            state.update(msgid=_unquote(line[6:]), current="msgid")
        elif line.startswith("msgstr ") and line[7:].startswith('"') and state["msgid"] is not None:
            state.update(msgstr=_unquote(line[7:]), current="msgstr")
        elif line.startswith('"') and state["current"] in ("msgid", "msgstr"):
            key = str(state["current"])
            state[key] = str(state[key]) + _unquote(line)
        else:   # msgctxt, msgid_plural, msgstr[n]: action names use none of them
            state["current"] = None
    finish()
    return entries


def translations(po_dir: Path) -> dict[str, dict[str, str]]:
    """{language: {msgid: msgstr}} from po_dir/<language>.po."""

    found: dict[str, dict[str, str]] = {}
    for po in sorted(po_dir.glob("*.po")):
        language = po.name[:-3]
        if not LANGUAGE_RE.fullmatch(language):
            continue
        try:
            entries = read_po(po.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if entries:
            found[language] = entries
    return found


def _one_line(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


def build_action(uuid: str, template: str, languages: dict[str, dict[str, str]]) -> str:
    """The .nemo_action of a spice template: _Key=value becomes Key=value plus Key[lang]=translation."""

    lines = []
    for line in template.splitlines():
        key = line[1:].split("=", 1)[0] if line.startswith("_") and "=" in line else None
        if key in TRANSLATABLE:
            value = line.split("=", 1)[1]
            lines.append(f"{key}={value}")
            for language, entries in sorted(languages.items()):
                translated = entries.get(value, "").strip()
                if translated and translated != value:
                    lines.append(f"{key}[{language}]={_one_line(translated)}")
            continue
        if line.startswith("_"):
            line = line[1:]
        if line.startswith("Exec="):
            # A spice installed per user lives in ~/.local/share/nemo/actions; this one is in ACTIONS.
            line = line.replace("$HOME/.local/share/nemo/actions/", f"{ACTIONS}/")
            line = line.replace("~/.local/share/nemo/actions/", f"{ACTIONS}/")
        lines.append(line)
    return "\n".join(lines) + "\n"


def _template(uuid: str) -> str:
    own = ACTIONS / uuid / f"{uuid}.nemo_action.in"
    try:
        text = own.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return TEMPLATES[uuid]
    return text if text.lstrip().startswith("[Nemo Action]") else TEMPLATES[uuid]


def _runtime_translations(context: MigrationContext, uuids: list[str]) -> None:
    """Compile the actions' po/ folders into ~/.local/share/locale of each user and /etc/skel."""

    helper = importlib.import_module(TRANSLATE_SPICES)
    spices = [("actions", uuid, sorted((ACTIONS / uuid / "po").glob("*.po"))) for uuid in uuids]
    spices = [spice for spice in spices if spice[2]]
    if not spices:
        return
    if not Path(helper.MSGFMT).is_file():
        context.log(f"{helper.MSGFMT} is missing (package gettext); the action windows stay in English")
        return
    compiled = helper._compile(context, spices)
    targets = [(helper.SKEL, helper.SKEL_OWNER, set())]
    for info in helper._desktop_users():
        home = Path(info.pw_dir)
        own = {uuid for _kind, uuid, _po in spices if (home / USER_ACTIONS / uuid).exists()}
        targets.append((home, (info.pw_uid, info.pw_gid), own))
    for root, owner, skip in targets:
        files = {language: {uuid: data for uuid, data in by_uuid.items() if uuid not in skip}
                 for language, by_uuid in compiled.items()}
        result = helper._install(root, owner, {language: data for language, data in files.items() if data})
        if result is None:
            context.log(f"skip {root}: its ~/{helper.LOCALE} cannot be used")
        else:
            context.log(f"{root}: {result[0]} action translations added, {result[1]} failed")


def run(context: MigrationContext) -> None:
    if not ACTIONS.is_dir():
        context.log(f"{ACTIONS} does not exist; no action to show")
        return
    written = []
    for uuid in TEMPLATES:
        folder = ACTIONS / uuid
        action = ACTIONS / f"{uuid}.nemo_action"
        if not folder.is_dir():
            context.log(f"{uuid} is not installed")
            continue
        if action.exists():
            context.log(f"{action} is already there")
            continue
        content = build_action(uuid, _template(uuid), translations(folder / "po"))
        context.write_file_if_changed(action, content)
        written.append(uuid)
    installed = [uuid for uuid in TEMPLATES if (ACTIONS / uuid).is_dir()]
    if "copy-path-to-clipboard@claudiux" in installed and not XCLIP.exists():
        try:
            context.apt_install(["xclip"], recommends=False)
        except MigrationContextError as exc:
            context.log(f"could not install xclip ({exc}); Copy path to clipboard stays hidden until it is")
    runtime = [uuid for uuid in RUNTIME_TRANSLATED if uuid in installed]
    if runtime and context.dry_run:
        context.log(f"compile the translations of {', '.join(runtime)} into each user's ~/.local/share/locale")
    elif runtime:
        _runtime_translations(context, runtime)
    if not written:
        context.log("no Nemo action file to add")
