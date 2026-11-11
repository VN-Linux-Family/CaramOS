"""Hold Ctrl and roll the mouse wheel over the apps of the Start Menu to make their icons bigger or smaller.

People coming from Windows, and from Ubuntu Kylin, resize icons with Ctrl + mouse wheel. In the Cinnamenu Start
Menu the wheel only scrolled the list, and the icon size could only be set in the applet settings. Now every notch
of Ctrl + wheel over the apps makes their icons a step bigger or smaller, about 10 % a step, at once:
- in the grid: 24, 28, 32, 36, 40, 44, 48, 54, 60, 64 (the default), 72, 80, 88, 96, 108, 120 and 128 pixels;
- in the list: 16, 20, 24 (the default), 28, 32, 40, 48, 56 and 64 pixels.
The first version had six grid sizes and applied the size once the wheel rested, so a roll jumped from the
default straight to the biggest or the smallest size (the owner: "nó chỉ có 2 mức thôi hả siêu to và siêu nhỏ,
tôi muốn nó to to ra dần nhỏ nhỏ lại dần").
The grid columns follow the icon size, so smaller icons fit more apps in a row and bigger ones fewer. Cinnamenu
kept every column at least 140 pixels wide whatever the icon size, so the number of apps in a row did not change
(the owner noticed: "to thì 3 icon 1 hàng, bé thì 4"). The minimum width is now 140 * (size + 32) / 96 pixels,
counting sizes under 24 as 24: 64 pixels, the default, keeps 140, 24 pixels gives 82 and 128 pixels 233.
The size is saved in the applet settings, where it can still be set by hand.

How the change works, and why:
- The size is set through the settings binding (`settings.appsGridIconSize = size`). That saves it without calling
  the binding's callback, which rebuilds the whole menu, and rebuilding the menu closes it.
- The icons of the existing buttons are resized in place (St.Icon.set_icon_size, the emoji's font size) and
  Cinnamenu's resizeGrid() lays the grid out again. Creating the buttons again took about 200 ms for a full menu in
  the test VM, the in-place resize about 90 ms with a change of columns. The category, the search and the scroll
  position stay as they were. A button whose icon is something else makes the buttons be created again.
- Wheel notches are counted from the up and down scroll events, as Cinnamon's window switcher does. X11 reports a
  notch twice, as such an event and as a smooth scroll event, and the first smooth event after the pointer moves
  carries no delta. Smooth events are swallowed while Ctrl is held, so the list does not scroll. Touchpads should
  step too, through the up and down events the X server emulates for each scroll step; no real touchpad has been
  tried yet.
- Notches are applied once per frame (Meta.later_add BEFORE_REDRAW), so a fast roll grows the icons step by step
  without piling up work.

Hook 0170 copies Cinnamenu from the spices repository, as it was when the ISO was built. The CaramOS 1.0.x to 1.3.3
ISOs carry Cinnamenu 5.4.14, whose apps view reaches the applet through `this.appThis` and clears itself with
clearApps(). The ISOs built after 2026-10-30 carry 5.7, with `this.applet` and clearAppsView(). Each version folder
whose apps view has the lines the change goes into, in either form, is patched, and any other is left as it is.
Cinnamenu is reloaded in the sessions of logged-in users, so the change works at once.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext

composing = importlib.import_module("caramos_ota_update.migrations.20261105120100_search_menu_while_composing.migration")

DESCRIPTION = "Ctrl + mouse wheel over the Start Menu apps changes the size of their icons"

SYSTEMD_RUNTIME = Path("/run/systemd/system")
CINNAMENU = Path("/usr/share/cinnamon/applets/Cinnamenu@json")
MARKER = "// CaramOS: Ctrl + mouse wheel over the apps"

# (the first line of the apps view constructor, how it reaches the applet, how it clears its buttons from the view)
FORMS = (
    ("class AppsView {\n    constructor(applet) {\n        this.applet = applet;\n", "applet", "clearAppsView"),
    ("class AppsView {\n    constructor(appThis) {\n        this.appThis = appThis;\n", "appThis", "clearApps"),
)
SCROLL_BOX = "        this.applicationsScrollBox.set_mouse_scrolling(true);\n"
COLUMN_WIDTH = "        const minColumnWidth = Math.max(140, this.@APP@.settings.appsGridIconSize * 1.2);\n"
CARAMOS_COLUMN_WIDTH = """\
        // CaramOS: the columns follow the icon size, so smaller icons fit more apps in a row and bigger ones
        // fewer. 64 px, the default, keeps Cinnamenu's 140 px columns; 24 px gives 82 px and 128 px 233 px.
        const minColumnWidth = Math.round(140 * (Math.max(24, this.@APP@.settings.appsGridIconSize) + 32) / 96);
"""
GRID_VALUES = "    getGridValues() {\n"
DESTROY = "    destroy() {\n        this.appsViewSignals.disconnectAllSignals();\n"
APPS_VIEW_NEEDS = ("const Clutter = imports.gi.Clutter;", "const St = imports.gi.St;", "const ApplicationsViewMode = ",
                   "this.buttonStore = [];", "this.applicationsScrollBox.vscroll.adjustment", "\n    resizeGrid() {\n",
                   "this.icon = new St.Label({ style: 'color: white; font-size: ' +")
# What the change uses of the applet: the two settings and how the menu shows a category or a search again.
APPLET_NEEDS = (
    re.compile(r"key: 'apps-grid-icon-size',\s*value: 'appsGridIconSize'"),
    re.compile(r"key: 'apps-list-icon-size',\s*value: 'appsListIconSize'"),
    re.compile(r"key: 'applications-view-mode',\s*value: 'applicationsViewMode'"),
    re.compile(r"\n    setActiveCategory\(categoryId\) \{\n"),
    re.compile(r"\n    _onSearchTextChanged\(\) \{\n"),
    re.compile(r"this\.searchActive = true;"),
    re.compile(r"this\.previousSearchPattern = '';"),
    re.compile(r"this\.currentCategory = 'all';"),
)

CONNECT = """\
        // CaramOS: Ctrl + mouse wheel over the apps changes the size of their icons.
        this.appsViewSignals.connect(this.applicationsScrollBox, 'scroll-event',
                                        (actor, event) => this._caramosCtrlScroll(event));
"""
METHODS = """\
    // CaramOS: Ctrl + mouse wheel over the apps changes the size of their icons, a step per notch, as on Windows.
    // Notches are counted from the up and down scroll events, like Cinnamon's window switcher does: X11 reports
    // every wheel notch that way, next to smooth scroll events whose first one after the pointer moves carries no
    // delta. The smooth events are swallowed, so the list does not scroll meanwhile.
    _caramosCtrlScroll(event) {
        if ((event.get_state() & Clutter.ModifierType.CONTROL_MASK) === 0) {
            return Clutter.EVENT_PROPAGATE;
        }
        const direction = event.get_scroll_direction();
        let step;
        if (direction === Clutter.ScrollDirection.UP) {
            step = 1;
        } else if (direction === Clutter.ScrollDirection.DOWN) {
            step = -1;
        } else if (direction === Clutter.ScrollDirection.SMOOTH) {
            return Clutter.EVENT_STOP;
        } else {
            return Clutter.EVENT_PROPAGATE;
        }
        const isList = this.@APP@.settings.applicationsViewMode === ApplicationsViewMode.LIST;
        const sizes = isList ? [16, 20, 24, 28, 32, 40, 48, 56, 64]
                             : [24, 28, 32, 36, 40, 44, 48, 54, 60, 64, 72, 80, 88, 96, 108, 120, 128];
        const current = this._caramosTargetSize ||
            (isList ? this.@APP@.settings.appsListIconSize : this.@APP@.settings.appsGridIconSize);
        const next = step > 0 ? sizes.find(size => size > current)
                              : sizes.slice().reverse().find(size => size < current);
        if (next === undefined) {
            return Clutter.EVENT_STOP;
        }
        this._caramosTargetSize = next;
        if (!this._caramosResizeLater) {
            // Once per frame: a fast roll grows the icons step by step without piling up work.
            this._caramosResizeLater = imports.gi.Meta.later_add(imports.gi.Meta.LaterType.BEFORE_REDRAW, () => {
                this._caramosResizeLater = 0;
                const size = this._caramosTargetSize;
                this._caramosTargetSize = 0;
                // The binding saves the size without calling the settings callback, which rebuilds the whole menu
                // and closes it.
                this.@APP@.settings[isList ? 'appsListIconSize' : 'appsGridIconSize'] = size;
                this._caramosResizeIcons(size, isList);
                return false;
            });
        }
        return Clutter.EVENT_STOP;
    }

    // Resize the icons of the buttons in place and lay the grid out again: creating the buttons again takes
    // about twice as long, too long for every notch.
    _caramosResizeIcons(size, isList) {
        const adjustment = this.applicationsScrollBox.vscroll.adjustment;
        const room = adjustment.upper - adjustment.page_size;
        const ratio = room > 0 ? adjustment.value / room : 0;
        let other = false;
        this.buttonStore.forEach(button => {
            const icon = button ? button.icon : null;
            if (icon instanceof St.Icon) {
                icon.set_icon_size(size);
            } else if (icon instanceof St.Label) { // an emoji
                icon.set_style('color: white; font-size: ' + Math.round(size * 0.85) + 'px;');
            } else if (icon) {
                other = true;
            }
        });
        if (other) {
            this._caramosRecreateButtons();
            return;
        }
        if (!isList) {
            this.resizeGrid();
        }
        imports.gi.Meta.later_add(imports.gi.Meta.LaterType.IDLE, () => {
            adjustment.set_value(Math.max(0, ratio * (adjustment.upper - adjustment.page_size)));
            return false;
        });
    }

    _caramosRecreateButtons() {
        const adjustment = this.applicationsScrollBox.vscroll.adjustment;
        const room = adjustment.upper - adjustment.page_size;
        const ratio = room > 0 ? adjustment.value / room : 0;
        this.@CLEAR@();
        this.buttonStore.forEach(button => { if (button) button.destroy(); });
        this.buttonStore = [];
        if (this.@APP@.searchActive) {
            this.@APP@.previousSearchPattern = '';
            this.@APP@._onSearchTextChanged();
        } else {
            this.@APP@.setActiveCategory(this.@APP@.currentCategory);
        }
        imports.gi.Meta.later_add(imports.gi.Meta.LaterType.IDLE, () => {
            adjustment.set_value(Math.max(0, ratio * (adjustment.upper - adjustment.page_size)));
            return false;
        });
    }

"""
CLEANUP = """\
        if (this._caramosResizeLater) {
            imports.gi.Meta.later_remove(this._caramosResizeLater);
            this._caramosResizeLater = 0;
        }
"""


def patched(appsview: str, applet: str) -> str | None:
    """appsview.js with the change; None when the apps view or the applet is not one of the two known forms."""

    forms = [(app, clear) for constructor, app, clear in FORMS if appsview.count(constructor) == 1]
    if len(forms) != 1 or appsview.count("class AppsView {") != 1:
        return None
    app, clear = forms[0]
    view = appsview[appsview.index("class AppsView {"):]
    if f"\n    {clear}() {{\n" not in view:
        return None
    for anchor in (SCROLL_BOX, GRID_VALUES, DESTROY):
        if appsview.count(anchor) != 1 or view.count(anchor) != 1:
            return None
    if not all(need in appsview for need in APPS_VIEW_NEEDS):
        return None
    if not all(len(pattern.findall(applet)) >= 1 for pattern in APPLET_NEEDS):
        return None
    column_width = COLUMN_WIDTH.replace("@APP@", app)
    if appsview.count(column_width) != 1 or view.count(column_width) != 1:
        return None
    methods = METHODS.replace("@APP@", app).replace("@CLEAR@", clear)
    result = appsview.replace(column_width, CARAMOS_COLUMN_WIDTH.replace("@APP@", app))
    result = result.replace(SCROLL_BOX, SCROLL_BOX + CONNECT)
    result = result.replace(GRID_VALUES, methods + GRID_VALUES)
    return result.replace(DESTROY, DESTROY + CLEANUP)


def patch_folder(context: MigrationContext, folder: Path) -> bool:
    appsview_path, applet_path = folder / "appsview.js", folder / "applet.js"
    if not (appsview_path.is_file() and applet_path.is_file()) or appsview_path.is_symlink():
        return False
    appsview = appsview_path.read_text(encoding="utf-8")
    if MARKER in appsview:
        context.log(f"Ctrl + mouse wheel already resizes the icons of {folder}")
        return False
    result = patched(appsview, applet_path.read_text(encoding="utf-8"))
    if result is None:
        context.log(f"{folder} is another Cinnamenu version; leave it as it is")
        return False
    context.log(f"let Ctrl + mouse wheel resize the icons of {folder}")
    if not context.dry_run:
        composing._write(appsview_path, result)
    return True


def run(context: MigrationContext) -> None:
    if not CINNAMENU.is_dir():
        context.log(f"{CINNAMENU} is not installed")
        return
    changed = False
    for folder in sorted(path for path in CINNAMENU.iterdir() if path.is_dir() and not path.is_symlink()):
        changed = patch_folder(context, folder) or changed
    if changed and not context.dry_run and SYSTEMD_RUNTIME.is_dir():
        composing._reload_in_sessions(context)
