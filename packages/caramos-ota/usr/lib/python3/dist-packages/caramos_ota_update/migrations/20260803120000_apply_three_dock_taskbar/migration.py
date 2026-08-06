"""Timestamp migration for CaramOS 1.0.14: split panel applets into three zones."""

from __future__ import annotations

import ast
import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Split the CaramOS taskbar into three Cinnamon zones"

APPLET_MENU = "Cinnamenu@json"
APPLET_TASKLIST = "grouped-window-list@cinnamon.org"
OLD_CSS_MARKER = "@caramos-three-dock-taskbar"
THEME_CSS = Path("/usr/share/themes/Cinnamon-Delight/cinnamon/cinnamon.css")
APP_GROUP = Path("/usr/share/cinnamon/applets/grouped-window-list@cinnamon.org/appGroup.js")
CINNAMENU = Path("/usr/share/cinnamon/applets/Cinnamenu@json/3.2/applet.js")
BAD_DCONF_FRAGMENT = Path("/etc/dconf/db/local.d/90-caramos-three-dock-taskbar")
BAD_DCONF_HEADER = "# Managed by CaramOS OTA migration 20260803120000_apply_three_dock_taskbar"
BAD_PANEL_HEIGHT = "['1:44']"
BASELINE_PANEL_HEIGHT = "['1:32']"
PREVIOUS_DOCK_PANEL_HEIGHT = "['1:40']"
DOCK_PANEL_HEIGHT = "['1:48']"
BAD_ICON_SIZES_NORMALIZED = '[{"panelId":1,"left":22,"center":24,"right":18}]'
LEFT_DOCK_ICON_SIZES = '[{"panelId": 1, "left": 32, "right": 18}]'
SYMBOLIC_ICON_SIZES = '[{"panelId": 1, "left": 20, "center": 20, "right": 16}]'
DCONF_DEFAULT_FILES = (
    Path("/etc/dconf/db/local.d/00-caramos-theme"),
    Path("/etc/dconf/db/local.d/01-caramos-task17-panel"),
)
PANEL_DCONF_FILE = DCONF_DEFAULT_FILES[1]
CINNAMENU_SCALE_MARKER = "CaramOS dynamic panel icon scaling 20260803120000"
SYSTRAY_HOVER_MARKER = "CaramOS right-dock tray hover 20260803120000"
SYSTRAY_TARGET = Path("/usr/share/cinnamon/applets/systray@cinnamon.org/applet.js")
SYSTRAY_BUTTON_ANCHOR = "            icon.set_y_align(Clutter.ActorAlign.CENTER);\n            button.set_y_align(Clutter.ActorAlign.CENTER);\n"
CINNAMENU_PANEL_HEIGHT_ANCHOR = (
    "  on_panel_height_changed: function() {\n"
    "    this.refresh();\n"
    "  },\n"
)
CINNAMENU_ICON_SYNC_ANCHOR = (
    "    if (this.state.settings.menuIconCustom && this.state.settings.menuIcon === '') {\n"
)
RUNNING_DOT_MARKER = "CaramOS running-dot patch 20260803120000"
RUNNING_DOT_CLOSE_MARKER = "CaramOS running-dot close-state fix 20260803120000"
RUNNING_DOT_CLOSE_ANCHOR = "        this.groupState.metaWindows.splice(refWindow, 1);\n"
RUNNING_DOT_ANCHORS = (
    "        this.actor.add_child(this.label);\n",
    "        this.iconSize = iconSize;\n",
    "        this.actor.style = existingStyle + 'margin-' + direction + ':' + spacing + 'px;';\n",
    "            this.actor.height = panelHeight;\n",
    "        const iconYPadding = Math.floor(Math.max(0, allocHeight - naturalHeight) / 2);\n",
    "        const notifBadgeBox = new Clutter.ActorBox();\n",
    "                alloc.natural_size = iconNaturalSize + 6 * global.ui_scale;\n",
    "        this.iconBox.allocate(childBox, flags);\n",
    "    setActiveStatus(state) {\n",
    "        this.groupState.set({windowCount: this.groupState.metaWindows ? this.groupState.metaWindows.length : 0});\n",
)
DOCK_CSS_MARKER = "CARAMOS_20260803120000_PANEL_DOCKS"
DOCK_CSS = """/* CARAMOS_20260803120000_PANEL_DOCKS_START */
#panel {
  background-color: transparent;
}

.panelLeft {
  background-color: transparent;
  box-shadow: none;
}

.panelLeft .applet-box {
  background-color: rgba(247, 243, 233, 0.82);
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(31, 79, 50, 0.14);
  margin-top: 4px;
  margin-bottom: 4px;
}

.panelCenter {
  background-color: rgba(247, 243, 233, 0.82);
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(31, 79, 50, 0.14);
  margin-top: 4px;
  margin-bottom: 4px;
  padding-left: 0;
  padding-right: 0;
}

.panelCenter .grouped-window-list-box {
  spacing: 0;
}

.panelCenter .grouped-window-list-item-box {
  margin-left: 0;
}

.panelCenter .grouped-window-list-item-box:hover,
.panelCenter .grouped-window-list-item-box:focus {
  border-radius: 999px;
}

.panelRight {
  background-color: rgba(247, 243, 233, 0.82);
  border-radius: 999px;
  box-shadow: inset 0 0 0 1px rgba(31, 79, 50, 0.14);
  margin-top: 4px;
  margin-bottom: 4px;
}

.panelRight > .applet-box:hover,
.panelRight > .applet-box:checked,
.panelRight > .systray .applet-box:hover,
.panelRight > .systray .applet-box:checked {
  background-color: rgba(239, 230, 239, 0.69);
  border-radius: 999px;
}
.grouped-window-list-item-box.top:active,
.grouped-window-list-item-box.bottom:active,
.grouped-window-list-item-box.top:checked,
.grouped-window-list-item-box.bottom:checked {
  border-color: transparent;
}

.caramos-running-dot {
  width: 3px;
  height: 3px;
  min-width: 3px;
  min-height: 3px;
  border-radius: 999px;
  background-color: #1f9ede;
}
/* CARAMOS_20260803120000_PANEL_DOCKS_END */"""
FORBIDDEN_DOCK_CSS = (
    "border:",
    "font-size",
)


def _parse_applets(value: str) -> list[str] | None:
    try:
        parsed = ast.literal_eval(value.strip())
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list) or any(not isinstance(entry, str) for entry in parsed):
        return None
    return list(parsed)


def _arrange_applets(value: str) -> str | None:
    """Move only menu/task-list zones; preserve every other entry exactly."""
    entries = _parse_applets(value)
    if entries is None:
        return None
    updated: list[str] = []
    for entry in entries:
        parts = entry.split(":", 4)
        if len(parts) not in (4, 5) or parts[0] != "panel1":
            updated.append(entry)
            continue
        if parts[3] == APPLET_MENU:
            parts[1] = "left"
            parts[2] = "0"
        elif parts[3] == APPLET_TASKLIST:
            parts[1] = "center"
            parts[2] = "0"
        updated.append(":".join(parts))
    return "[" + ", ".join(repr(entry) for entry in updated) + "]"


def _replace_dconf_keys(source: str, replacements: dict[str, str]) -> str:
    """Replace keys in [org/cinnamon], preserving unrelated config."""

    lines = source.splitlines()
    section_start = None
    section_end = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "[org/cinnamon]":
            section_start = index
            continue
        if section_start is not None and index > section_start and stripped.startswith("[") and stripped.endswith("]"):
            section_end = index
            break
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        section_start = len(lines)
        lines.append("[org/cinnamon]")
        section_end = len(lines)

    found: set[str] = set()
    for index in range(section_start + 1, section_end):
        stripped = lines[index].strip()
        for key, value in replacements.items():
            if stripped.startswith(f"{key}="):
                lines[index] = f"{key}={value}"
                found.add(key)
                break
    insert_at = section_end
    for key, value in replacements.items():
        if key not in found:
            lines.insert(insert_at, f"{key}={value}")
            insert_at += 1
    return "\n".join(lines) + "\n"


def _updated_dconf_defaults(path: Path, source: str) -> str:
    replacements = {
        "panels-height": DOCK_PANEL_HEIGHT,
        "panel-zone-icon-sizes": repr(LEFT_DOCK_ICON_SIZES),
        "panel-zone-symbolic-icon-sizes": repr(SYMBOLIC_ICON_SIZES),
    }
    if path == PANEL_DCONF_FILE:
        current_enabled = None
        in_section = False
        for line in source.splitlines():
            stripped = line.strip()
            if stripped == "[org/cinnamon]":
                in_section = True
                continue
            if in_section and stripped.startswith("[") and stripped.endswith("]"):
                break
            if in_section and stripped.startswith("enabled-applets="):
                current_enabled = stripped.split("=", 1)[1].strip()
                break
        if current_enabled is not None:
            arranged = _arrange_applets(current_enabled)
            if arranged is None:
                raise RuntimeError(f"unexpected enabled-applets format in {path}")
            replacements["enabled-applets"] = arranged
    return _replace_dconf_keys(source, replacements)


def _atomic_write_text(path: Path, content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        staging.write_text(content, encoding="utf-8")
        staging.chmod(mode)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _update_system_defaults(context: MigrationContext) -> bool:
    changed = False
    for path in DCONF_DEFAULT_FILES:
        if path.is_symlink():
            raise RuntimeError(f"dconf defaults must not be a symlink: {path}")
        if path.exists() and not path.is_file():
            raise RuntimeError(f"dconf defaults must be a regular file: {path}")
        source = path.read_text(encoding="utf-8") if path.exists() else ""
        updated = _updated_dconf_defaults(path, source)
        if updated == source:
            continue
        context.log(f"update three-dock system defaults: {path}")
        changed = True
        if not context.dry_run:
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            _atomic_write_text(path, updated, mode)
    return changed


def _remove_old_css(context: MigrationContext) -> bool:
    if not THEME_CSS.exists():
        return False
    if THEME_CSS.is_symlink() or not THEME_CSS.is_file():
        raise RuntimeError(f"Cinnamon theme target requires regular file: {THEME_CSS}")
    current = THEME_CSS.read_text(encoding="utf-8")
    start_marker = f"/* {OLD_CSS_MARKER}:start */"
    end_marker = f"/* {OLD_CSS_MARKER}:end */"
    if start_marker not in current and end_marker not in current:
        return False
    if start_marker not in current or end_marker not in current:
        raise RuntimeError("old taskbar CSS marker block is malformed")
    start = current.index(start_marker)
    end = current.index(end_marker, start) + len(end_marker)
    updated = (current[:start] + current[end:]).strip() + "\n"
    context.log(f"remove all previous taskbar CSS: {THEME_CSS}")
    if context.dry_run:
        return True

    staging = Path(tempfile.mkstemp(prefix=".caramos-taskbar-clean-", dir=THEME_CSS.parent)[1])
    backup = THEME_CSS.with_name(THEME_CSS.name + ".caramos-taskbar-clean-backup")
    try:
        staging.write_text(updated, encoding="utf-8")
        staging.chmod(0o644)
        shutil.copy2(THEME_CSS, backup)
        os.replace(staging, THEME_CSS)
    except Exception:
        staging.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, THEME_CSS)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return True


def _build_theme_with_docks(current: str, *, running_dot: bool = True) -> str:
    css = DOCK_CSS
    if not running_dot:
        dot_start = css.index(".grouped-window-list-item-box.top:active,")
        dot_end = css.index(f"/* {DOCK_CSS_MARKER}_END */")
        css = css[:dot_start] + css[dot_end:]
    if any(token in css for token in FORBIDDEN_DOCK_CSS):
        raise RuntimeError("dock CSS contains layout or panel-content properties")
    start_marker = f"/* {DOCK_CSS_MARKER}_START */"
    end_marker = f"/* {DOCK_CSS_MARKER}_END */"
    if start_marker in current or end_marker in current:
        if start_marker not in current or end_marker not in current:
            raise RuntimeError("dock CSS marker block is malformed")
        start = current.index(start_marker)
        end = current.index(end_marker, start) + len(end_marker)
        base = (current[:start] + current[end:]).strip()
    else:
        base = current.rstrip()
    return base + "\n\n" + css + "\n"


def _install_dock_shell_css(context: MigrationContext, *, running_dot: bool = True) -> bool:
    if THEME_CSS.is_symlink() or not THEME_CSS.is_file():
        raise RuntimeError(f"Cinnamon theme target requires regular file: {THEME_CSS}")
    current = THEME_CSS.read_text(encoding="utf-8")
    updated = _build_theme_with_docks(current, running_dot=running_dot)
    if updated == current:
        context.log(f"three dock shells already installed: {THEME_CSS}")
        return False
    context.log(f"install three paint-only dock shells: {THEME_CSS}")
    if context.dry_run:
        return True

    staging = Path(tempfile.mkstemp(prefix=".caramos-dock-shell-", dir=THEME_CSS.parent)[1])
    backup = THEME_CSS.with_name(THEME_CSS.name + ".caramos-dock-shell-backup")
    try:
        staging.write_text(updated, encoding="utf-8")
        staging.chmod(0o644)
        shutil.copy2(THEME_CSS, backup)
        os.replace(staging, THEME_CSS)
        installed = THEME_CSS.read_text(encoding="utf-8")
        if installed.count(f"/* {DOCK_CSS_MARKER}_START */") != 1:
            raise RuntimeError("installed dock CSS failed validation")
        if installed.count(f"/* {DOCK_CSS_MARKER}_END */") != 1:
            raise RuntimeError("installed dock CSS failed validation")
    except Exception:
        staging.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, THEME_CSS)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return True


def _add_running_dot_close_state(current: str) -> str | None:
    if RUNNING_DOT_CLOSE_MARKER in current:
        return current
    if current.count(RUNNING_DOT_CLOSE_ANCHOR) != 1:
        return None
    return current.replace(
        RUNNING_DOT_CLOSE_ANCHOR,
        RUNNING_DOT_CLOSE_ANCHOR
        + "\n"
        + f"        // {RUNNING_DOT_CLOSE_MARKER}\n"
        + "        this.runningDot.visible = this.groupState.metaWindows.length > 0 && this.state.isHorizontal;\n",
        1,
    )


def _build_app_group_with_running_dot(current: str) -> str | None:
    if RUNNING_DOT_MARKER in current:
        return _add_running_dot_close_state(current)
    if any(current.count(anchor) != 1 for anchor in RUNNING_DOT_ANCHORS):
        return None

    actor_anchor = RUNNING_DOT_ANCHORS[0]
    current = current.replace(
        actor_anchor,
        actor_anchor
        + "\n"
        + f"        // {RUNNING_DOT_MARKER}\n"
        + "        this.runningDot = new St.Widget({\n"
        + "            style_class: 'caramos-running-dot',\n"
        + "            reactive: false,\n"
        + "            visible: this.groupState.metaWindows.length > 0\n"
        + "        });\n"
        + "        this.actor.add_child(this.runningDot);\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[1],
        "        this.iconSize = this.state.isHorizontal ? 32 * global.ui_scale : iconSize;\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[2],
        "        this.actor.style = existingStyle + 'margin-' + direction + ':0px;';\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[3],
        "            this.actor.height = 40 * global.ui_scale;\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[4],
        "        const iconYPadding = Math.floor(Math.max(0, allocHeight - naturalHeight) / 2) + global.ui_scale;\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[5],
        RUNNING_DOT_ANCHORS[5] + "        const runningDotBox = new Clutter.ActorBox();\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[6],
        "                alloc.natural_size = iconNaturalSize + 16 * global.ui_scale;\n",
    )
    current = current.replace(
        RUNNING_DOT_ANCHORS[7],
        RUNNING_DOT_ANCHORS[7]
        + "\n"
        + "        const dotSize = 3 * global.ui_scale;\n"
        + "        runningDotBox.x1 = box.x1 + Math.floor((allocWidth - dotSize) / 2);\n"
        + "        runningDotBox.x2 = runningDotBox.x1 + dotSize;\n"
        + "        runningDotBox.y2 = box.y2;\n"
        + "        runningDotBox.y1 = runningDotBox.y2 - dotSize;\n"
        + "        this.runningDot.allocate(runningDotBox, flags);\n",
        1,
    )
    old_active = (
        "    setActiveStatus(state) {\n"
        "        if (state && !this.actor.has_style_pseudo_class('active')) {\n"
        "            this.actor.add_style_pseudo_class('active');\n"
        "        } else {\n"
        "            this.actor.remove_style_pseudo_class('active');\n"
        "        }\n"
        "    }\n"
    )
    if current.count(old_active) != 1:
        return None
    current = current.replace(old_active, old_active)
    window_count_anchor = RUNNING_DOT_ANCHORS[9]
    current = current.replace(
        window_count_anchor,
        window_count_anchor
        + "\n"
        + "        this.runningDot.visible = this.groupState.windowCount > 0 && this.state.isHorizontal;\n",
        1,
    )
    return _add_running_dot_close_state(current)


def _build_systray_hover(current: str) -> str | None:
    if SYSTRAY_HOVER_MARKER in current:
        return current
    if current.count(SYSTRAY_BUTTON_ANCHOR) != 1:
        return None
    return current.replace(
        SYSTRAY_BUTTON_ANCHOR,
        "            icon.set_y_align(Clutter.ActorAlign.CENTER);\n"
        + f"            // {SYSTRAY_HOVER_MARKER}\n"
        + "            button.set_y_align(Clutter.ActorAlign.FILL);\n",
        1,
    )


def _install_systray_hover(context: MigrationContext) -> bool | None:
    if SYSTRAY_TARGET.is_symlink() or not SYSTRAY_TARGET.is_file():
        context.log(f"warning: systray target is not a regular file: {SYSTRAY_TARGET}")
        return None
    current = SYSTRAY_TARGET.read_text(encoding="utf-8")
    updated = _build_systray_hover(current)
    if updated is None:
        context.log("warning: systray does not match expected anchors; keep native hover")
        return None
    if updated == current:
        context.log(f"right-dock tray hover already installed: {SYSTRAY_TARGET}")
        return False
    context.log(f"install full-height right-dock tray hover: {SYSTRAY_TARGET}")
    if context.dry_run:
        return True

    staging = Path(tempfile.mkstemp(prefix=".caramos-systray-hover-", dir=SYSTRAY_TARGET.parent)[1])
    backup = SYSTRAY_TARGET.with_name(SYSTRAY_TARGET.name + ".caramos-hover-backup")
    try:
        staging.write_text(updated, encoding="utf-8")
        staging.chmod(0o644)
        shutil.copy2(SYSTRAY_TARGET, backup)
        os.replace(staging, SYSTRAY_TARGET)
        if SYSTRAY_TARGET.read_text(encoding="utf-8").count(SYSTRAY_HOVER_MARKER) != 1:
            raise RuntimeError("installed systray hover patch failed validation")
    except Exception:
        staging.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, SYSTRAY_TARGET)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return True


def _build_cinnamenu_dynamic_scale(current: str) -> str | None:
    if CINNAMENU_SCALE_MARKER in current:
        return current
    if current.count(CINNAMENU_PANEL_HEIGHT_ANCHOR) != 1:
        return None
    if current.count(CINNAMENU_ICON_SYNC_ANCHOR) != 1:
        return None
    panel_height_replacement = (
        "  on_panel_height_changed: function() {\n"
        f"    // {CINNAMENU_SCALE_MARKER}\n"
        "    this._updateIconAndLabel();\n"
        "    this.refresh();\n"
        "  },\n"
    )
    icon_sync = (
        "    const panelHeight = this.panel && this.panel.actor ? this.panel.actor.height : this._panelHeight;\n"
        "    const horizontal = this.orientation === St.Side.TOP || this.orientation === St.Side.BOTTOM;\n"
        "    if (horizontal && panelHeight > 16 && this._applet_icon) {\n"
        "      this._applet_icon.icon_size = panelHeight - 16;\n"
        "    }\n\n"
    )
    current = current.replace(CINNAMENU_PANEL_HEIGHT_ANCHOR, panel_height_replacement)
    return current.replace(CINNAMENU_ICON_SYNC_ANCHOR, icon_sync + CINNAMENU_ICON_SYNC_ANCHOR)


def _install_cinnamenu_dynamic_scale(context: MigrationContext) -> bool | None:
    if CINNAMENU.is_symlink() or not CINNAMENU.is_file():
        context.log(f"warning: Cinnamenu target is not a regular file: {CINNAMENU}")
        return None
    current = CINNAMENU.read_text(encoding="utf-8")
    updated = _build_cinnamenu_dynamic_scale(current)
    if updated is None:
        context.log("warning: Cinnamenu does not match expected anchors; keep native scaling")
        return None
    if updated == current:
        context.log(f"dynamic Cinnamenu scaling already installed: {CINNAMENU}")
        return False
    context.log(f"install dynamic Cinnamenu panel scaling: {CINNAMENU}")
    if context.dry_run:
        return True

    staging = Path(tempfile.mkstemp(prefix=".caramos-cinnamenu-scale-", dir=CINNAMENU.parent)[1])
    backup = CINNAMENU.with_name(CINNAMENU.name + ".caramos-dynamic-scale-backup")
    try:
        staging.write_text(updated, encoding="utf-8")
        staging.chmod(0o644)
        shutil.copy2(CINNAMENU, backup)
        os.replace(staging, CINNAMENU)
        if CINNAMENU.read_text(encoding="utf-8").count(CINNAMENU_SCALE_MARKER) != 1:
            raise RuntimeError("installed Cinnamenu scaling patch failed validation")
    except Exception:
        staging.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, CINNAMENU)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return True


def _install_running_dot(context: MigrationContext) -> bool | None:
    if APP_GROUP.is_symlink() or not APP_GROUP.is_file():
        context.log(f"warning: grouped-window-list target is not a regular file: {APP_GROUP}")
        return None
    current = APP_GROUP.read_text(encoding="utf-8")
    updated = _build_app_group_with_running_dot(current)
    if updated is None:
        context.log("warning: grouped-window-list does not match Cinnamon 6.6 anchors; keep underline")
        return None
    if updated == current:
        context.log(f"running dot already installed: {APP_GROUP}")
        return False
    context.log(f"install running dot actor: {APP_GROUP}")
    if context.dry_run:
        return True

    staging = Path(tempfile.mkstemp(prefix=".caramos-running-dot-", dir=APP_GROUP.parent)[1])
    backup = APP_GROUP.with_name(APP_GROUP.name + ".caramos-running-dot-backup")
    try:
        staging.write_text(updated, encoding="utf-8")
        staging.chmod(0o644)
        shutil.copy2(APP_GROUP, backup)
        os.replace(staging, APP_GROUP)
        installed = APP_GROUP.read_text(encoding="utf-8")
        if installed.count(RUNNING_DOT_MARKER) != 1:
            raise RuntimeError("installed running dot patch failed validation")
        if installed.count(RUNNING_DOT_CLOSE_MARKER) != 1:
            raise RuntimeError("installed running dot close-state fix failed validation")
    except Exception:
        staging.unlink(missing_ok=True)
        if backup.exists():
            shutil.copy2(backup, APP_GROUP)
        raise
    finally:
        staging.unlink(missing_ok=True)
    return True


def _remove_bad_dconf(context: MigrationContext) -> bool:
    if not BAD_DCONF_FRAGMENT.is_file() or BAD_DCONF_FRAGMENT.is_symlink():
        return False
    content = BAD_DCONF_FRAGMENT.read_text(encoding="utf-8")
    if not content.startswith(BAD_DCONF_HEADER + "\n"):
        return False
    context.log(f"remove previous taskbar dconf overrides: {BAD_DCONF_FRAGMENT}")
    if context.dry_run:
        return True
    BAD_DCONF_FRAGMENT.unlink()
    return True


def _session_environment(uid: int, home: Path) -> dict[str, str] | None:
    runtime_dir = Path(f"/run/user/{uid}")
    if not runtime_dir.exists():
        return None
    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XAUTHORITY": str(home / ".Xauthority"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        }
    )
    return env


def _live_desktop_users() -> list[tuple[str, int, Path]]:
    users: list[tuple[str, int, Path]] = []
    runtime_root = Path("/run/user")
    if not runtime_root.exists():
        return users
    for runtime_dir in runtime_root.iterdir():
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        uid = int(runtime_dir.name)
        try:
            info = pwd.getpwuid(uid)
        except KeyError:
            continue
        if uid >= 1000 and info.pw_dir not in ("", "/nonexistent"):
            users.append((info.pw_name, uid, Path(info.pw_dir)))
    return users


def _run_as_user(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _normalize_json_setting(value: str) -> str:
    return "".join(value.strip().strip("'").split())


def _reset_previous_override(context: MigrationContext, user: str, env: dict[str, str], key: str) -> None:
    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", key])
    if current.returncode != 0:
        return
    bad = current.stdout.strip() == BAD_PANEL_HEIGHT if key == "panels-height" else (
        _normalize_json_setting(current.stdout) == BAD_ICON_SIZES_NORMALIZED
    )
    if not bad:
        return
    result = _run_as_user(user, env, ["gsettings", "reset", "org.cinnamon", key])
    if result.returncode == 0:
        context.log(f"remove previous taskbar override {key} for live user: {user}")


def _set_left_dock_icon_size(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "panel-zone-icon-sizes"])
    if current.returncode != 0:
        return
    normalized = _normalize_json_setting(current.stdout)
    known = {
        '[{"panelId":1,"right":18}]',
        '[{"panelId":1,"left":20,"center":20,"right":20}]',
        BAD_ICON_SIZES_NORMALIZED,
        _normalize_json_setting(repr(LEFT_DOCK_ICON_SIZES)),
        _normalize_json_setting(LEFT_DOCK_ICON_SIZES),
    }
    if normalized not in known:
        context.log(f"kept custom panel icon sizes for live user: {user}")
        return
    if normalized == _normalize_json_setting(LEFT_DOCK_ICON_SIZES):
        return
    result = _run_as_user(
        user,
        env,
        [
            "gsettings",
            "set",
            "org.cinnamon",
            "panel-zone-icon-sizes",
            repr(LEFT_DOCK_ICON_SIZES),
        ],
    )
    if result.returncode == 0:
        context.log(f"set native 32px left-zone icon size: {user}")


def _set_dock_panel_height(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "panels-height"])
    if current.returncode != 0:
        return
    if current.stdout.strip() not in (
        BASELINE_PANEL_HEIGHT,
        PREVIOUS_DOCK_PANEL_HEIGHT,
        BAD_PANEL_HEIGHT,
        DOCK_PANEL_HEIGHT,
    ):
        context.log(f"kept custom panel height for live user: {user}")
        return
    if current.stdout.strip() == DOCK_PANEL_HEIGHT:
        return
    result = _run_as_user(
        user,
        env,
        ["gsettings", "set", "org.cinnamon", "panels-height", DOCK_PANEL_HEIGHT],
    )
    if result.returncode == 0:
        context.log(f"set 48px panel height for 8px center-dock insets: {user}")


def _apply_layout(context: MigrationContext, user: str, uid: int, home: Path) -> None:
    env = _session_environment(uid, home)
    if env is None:
        return
    _reset_previous_override(context, user, env, "panel-zone-symbolic-icon-sizes")
    _set_left_dock_icon_size(context, user, env)
    _set_dock_panel_height(context, user, env)
    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0:
        context.log(f"warning: could not read enabled applets for {user}: {current.stderr.strip()}")
        return
    updated = _arrange_applets(current.stdout)
    if updated is None:
        context.log(f"warning: unexpected enabled-applets format for {user}; keep unchanged")
        return
    if updated == current.stdout.strip():
        context.log(f"three-zone applet layout already active for live user: {user}")
        return
    result = _run_as_user(user, env, ["gsettings", "set", "org.cinnamon", "enabled-applets", updated])
    if result.returncode == 0:
        context.log(f"split menu, applications, and status applets into three zones for live user: {user}")


def run(context: MigrationContext) -> None:
    """Remove previous styling and only split applets across panel zones."""
    if context.dry_run:
        context.log("[dry-run] remove all previous taskbar CSS and applet patches")
        context.log("[dry-run] remove previous taskbar panel-setting overrides")
        _update_system_defaults(context)
        context.log("[dry-run] move only Start Menu left and grouped-window-list center")
        context.log("[dry-run] install paint-only shells for left, center, and right zones")
        context.log("[dry-run] normalize right-dock system, tray, and Control Center hover")
        return

    _remove_old_css(context)
    _install_cinnamenu_dynamic_scale(context)
    _install_systray_hover(context)
    running_dot_result = _install_running_dot(context)
    dconf_changed = _remove_bad_dconf(context)
    dconf_changed = _update_system_defaults(context) or dconf_changed
    live_users = _live_desktop_users()
    for user, uid, home in live_users:
        _apply_layout(context, user, uid, home)
    if dconf_changed:
        context.run_command(["dconf", "update"], allow_fail=True)
    dock_css_changed = _install_dock_shell_css(
        context,
        running_dot=running_dot_result is not None,
    )
    if dock_css_changed:
        context.log("three dock shells apply after next Cinnamon login")
    if running_dot_result:
        context.log("running dot applies after next Cinnamon login")
