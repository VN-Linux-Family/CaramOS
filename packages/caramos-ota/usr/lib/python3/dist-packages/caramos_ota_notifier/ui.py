"""GTK 3 pages of the CaramOS Update Center, the window of caramos-ota-notifier.

The look follows DESIGN.md at the root of the CaramOS repository: a plain header bar drawn by the desktop's theme,
neutral surfaces, one accent colour (forest green) for the main button and the progress bar only, the desktop's font
(Be Vietnam Pro on CaramOS) at weights 400 and 600, boxed lists, and technical words only under "Details".

The update page keeps its buttons in a bar under the scrolled body, so they stay on screen however small the window
or long the list of changes (issue #77). The status pages (updated, not updated, nothing new) centre a short text with
its buttons right under it, above the collapsed details.

The "Automatic updates" switch (caramos_ota.auto_update) is a row of a boxed list on the update page, the page saying
CaramOS is up to date, and the page of what an automatic update installed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from caramos_ota import auto_update as system_auto_update
from caramos_ota.i18n import _, localized, ngettext

from .constants import BUSY, CANCELLED, DONE, FAILED, OFFLINE
from .state import RELEASE_METADATA_NAME, change_rows, format_value, size_parts, update_versions, version_text

CARAMOS_ICON = Path("/usr/share/pixmaps/caramos-logo.png")
LOGO_SIZE = 48
STATUS_ICON_SIZE = 64
SPINNER_SIZE = 32
# GTK measures a label by Be Vietnam Pro's widest digit, about 1.45 times an average letter of Vietnamese text: 48 such
# "characters" let a line hold about 70 letters, the longest line DESIGN.md allows.
LINE_CHARS = 48
# Pango scales the font's own line height (1.35 times the size for Be Vietnam Pro): 1.1 gives paragraphs about 1.5.
PARAGRAPH_LINE_HEIGHT = 1.1

STATUS_ICONS = {
    DONE: "emblem-ok-symbolic",
    CANCELLED: "dialog-password-symbolic",
    BUSY: "emblem-synchronizing-symbolic",
    FAILED: "dialog-warning-symbolic",
}
UP_TO_DATE_ICON = "emblem-ok-symbolic"

# The colours of DESIGN.md; the buttons' and the progress trough's are the text colour at low opacity, as libadwaita.
LIGHT = {
    "accent_bg": "#2b6a44", "accent_fg": "#ffffff",
    "window": "#fafafb", "list": "#ffffff", "line": "rgba(0, 0, 0, 0.09)",
    "fg": "rgba(0, 0, 0, 0.82)", "dim": "rgba(0, 0, 0, 0.55)", "warning": "#9c6e03",
    "button": "rgba(0, 0, 0, 0.08)", "button_hover": "rgba(0, 0, 0, 0.12)", "button_active": "rgba(0, 0, 0, 0.18)",
    "trough": "rgba(0, 0, 0, 0.08)",
    "switch_off": "rgba(0, 0, 0, 0.15)", "slider": "#ffffff",
}
DARK = {
    "accent_bg": "#3a855a", "accent_fg": "#ffffff",
    "window": "#242424", "list": "#2f2f2f", "line": "rgba(255, 255, 255, 0.08)",
    "fg": "#ffffff", "dim": "rgba(255, 255, 255, 0.6)", "warning": "#f5c04a",
    "button": "rgba(255, 255, 255, 0.1)", "button_hover": "rgba(255, 255, 255, 0.15)",
    "button_active": "rgba(255, 255, 255, 0.2)",
    "trough": "rgba(255, 255, 255, 0.1)",
    "switch_off": "rgba(255, 255, 255, 0.15)", "slider": "#ffffff",
}

# Every rule is scoped to the Update Center window: the Audit tool loads the same provider for its dialog.
CSS = """
window.caramos-ota { background-color: %(window)s; color: %(fg)s; }

window.caramos-ota .uc-page label { color: %(fg)s; }
window.caramos-ota .uc-page label.uc-title { font-size: 1.8em; font-weight: 600; }
window.caramos-ota .uc-page label.uc-heading { font-size: 1.15em; font-weight: 600; }
window.caramos-ota .uc-page label.uc-row-title { font-weight: 600; }
window.caramos-ota .uc-page label.uc-dim { font-size: 0.92em; color: %(dim)s; }
window.caramos-ota .uc-page label.uc-warning { color: %(warning)s; }

window.caramos-ota scrolledwindow.uc-body undershoot,
window.caramos-ota scrolledwindow.uc-body overshoot { background-image: none; }

window.caramos-ota .uc-list { background-color: %(list)s; border: 1px solid %(line)s; border-radius: 12px; }
window.caramos-ota .uc-row { padding: 12px 14px; }
window.caramos-ota .uc-row:not(:first-child) { border-top: 1px solid %(line)s; }

window.caramos-ota image.uc-status-icon, window.caramos-ota spinner.uc-status-icon { color: %(dim)s; }

window.caramos-ota .uc-actions { border-top: 1px solid %(line)s; padding: 12px 24px; }

window.caramos-ota button.uc-button {
  min-height: 24px; padding: 5px 14px; border: none; border-radius: 6px; -gtk-outline-radius: 6px;
  background-image: none; box-shadow: none; text-shadow: none; -gtk-icon-shadow: none;
  background-color: %(button)s; color: %(fg)s;
}
window.caramos-ota button.uc-button:hover { background-color: %(button_hover)s; }
window.caramos-ota button.uc-button:active { background-color: %(button_active)s; }
window.caramos-ota button.uc-button label { color: inherit; font-weight: 600; }
window.caramos-ota button.uc-button.suggested-action { background-color: %(accent_bg)s; color: %(accent_fg)s; }
window.caramos-ota button.uc-button.suggested-action:hover { background-color: mix(%(accent_bg)s, #ffffff, 0.1); }
window.caramos-ota button.uc-button.suggested-action:active { background-color: mix(%(accent_bg)s, #000000, 0.1); }
window.caramos-ota button.uc-button.pill { padding: 10px 32px; border-radius: 9999px; -gtk-outline-radius: 9999px; }

window.caramos-ota switch {
  border: none; border-radius: 9999px; background-image: none; box-shadow: none; color: transparent;
  background-color: %(switch_off)s;
}
window.caramos-ota switch:checked { background-color: %(accent_bg)s; }
window.caramos-ota switch slider {
  min-width: 20px; min-height: 20px; margin: 3px; border: none; border-radius: 9999px;
  background-image: none; box-shadow: none; background-color: %(slider)s;
}
window.caramos-ota switch:disabled { opacity: 0.5; }

window.caramos-ota expander.uc-details title label,
window.caramos-ota expander.uc-details title arrow { color: %(dim)s; }

window.caramos-ota progressbar.uc-progress trough,
window.caramos-ota progressbar.uc-progress progress {
  min-height: 6px; border: none; border-radius: 3px; background-image: none; box-shadow: none;
}
window.caramos-ota progressbar.uc-progress trough { background-color: %(trough)s; }
window.caramos-ota progressbar.uc-progress progress { background-color: %(accent_bg)s; }

window.caramos-ota scrolledwindow.uc-log { background-color: %(list)s; border: 1px solid %(line)s; border-radius: 8px; }
window.caramos-ota textview.uc-log-view,
window.caramos-ota textview.uc-log-view text {
  background-color: transparent; color: %(fg)s; font-family: monospace; font-size: 0.92em;
}
"""

_provider = None


def import_gtk():
    """Import GTK3 lazily so non-GUI sessions can exit quietly."""

    import gi

    # Pin Gdk and Pango too: with GTK 4 typelibs installed (the App Center needs them), an unpinned Gdk
    # loads 4.0 and GTK 3 then fails to import, so the Update Center never opened.
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gtk, Gdk, GLib


def set_caramos_icon(dialog, Gtk) -> None:
    """Use the CaramOS brand icon for OTA dialogs.

    The 512 px pixmap is too large for GTK 3 to publish as _NET_WM_ICON, which left the taskbar entry
    blank; the themed icon (or the pixmap scaled down) is published.
    """

    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon("caramos-logo"):
        dialog.set_icon_name("caramos-logo")
    elif CARAMOS_ICON.exists():
        from gi.repository import GdkPixbuf

        dialog.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_size(str(CARAMOS_ICON), 128, 128))


def prefers_dark(Gtk) -> bool:
    """True when the desktop uses a dark GTK theme (CaramOS dark mode switches to a -Dark theme)."""

    settings = Gtk.Settings.get_default()
    if settings is None:
        return False
    theme = (settings.get_property("gtk-theme-name") or "").lower()
    return bool(settings.get_property("gtk-application-prefer-dark-theme")) or "dark" in theme


def stylesheet(dark: bool) -> str:
    return CSS % (DARK if dark else LIGHT)


def apply_theme(Gtk, Gdk) -> None:
    """Style the Update Center window, and restyle it when the desktop switches between light and dark."""

    global _provider
    if _provider is None:
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            _provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        settings = Gtk.Settings.get_default()
        if settings is not None:
            for name in ("gtk-theme-name", "gtk-application-prefer-dark-theme"):
                settings.connect(f"notify::{name}", lambda *_args: _load_stylesheet(Gtk))
    _load_stylesheet(Gtk)


def _load_stylesheet(Gtk) -> None:
    _provider.load_from_data(stylesheet(prefers_dark(Gtk)).encode("utf-8"))


# What the pages say ----------------------------------------------------------------------------


def update_intro(update_info: dict[str, Any]) -> tuple[str, str]:
    """Headline and sentence of the update page.

    The version number leads when the update brings a new one. Timestamp migrations can also come without one (the
    same 1.4.0 before and after): then the headline names the version they are for.
    """

    current, target = update_versions(update_info)
    if target and target != current:
        return "CaramOS %s" % target, (_("You are using %s.") % current) if current else ""
    count = len(change_rows(update_info))
    sentence = ngettext(
        "This update has %d change for the version you have.",
        "This update has %d changes for the version you have.",
        count,
    ) % count
    if target:
        return _("An update for CaramOS %s") % target, sentence
    return _("A new CaramOS update is available"), sentence


def is_security_update(update_info: dict[str, Any]) -> bool:
    return format_value(update_info.get("severity"), "").lower() == "security"


def update_details(update_info: dict[str, Any]) -> list[tuple[str, str]]:
    """The technical facts under Details, as (name, value): the size of each part, one a line, and the channel."""

    rows = []
    names = [package.get("name") for package in update_info.get("packages") or [] if isinstance(package, dict)]
    # An update that only changes the version number has no parts to size ("Release metadata").
    version_only = bool(names) and all(name == RELEASE_METADATA_NAME for name in names)
    parts = [] if version_only else size_parts(localized(update_info, "size"))
    if parts:
        rows.append((_("Size"), "\n".join(parts)))
    channel = format_value(update_info.get("channel"), "")
    if channel:
        rows.append((_("Update channel"), channel))
    return rows


def progress_title(update_info: dict[str, Any] | None) -> str:
    current, target = update_versions(update_info or {})
    if target and target != current:
        return _("Updating to CaramOS %s") % target
    return _("Updating CaramOS")


def done_title(update_info: dict[str, Any] | None) -> str:
    current, target = update_versions(update_info or {})
    if target and target != current:
        return _("Updated to CaramOS %s") % target
    return _("CaramOS was updated")


def result_texts(outcome: str, update_info: dict[str, Any] | None, *, can_ask_for_help: bool) -> tuple[str, str]:
    """Title and text of the page shown after an update run: what happened, then what to do, a line each.

    One sentence a line: the centred text then breaks where the sentences do, not before a last lone word.
    """

    if outcome == DONE:
        return done_title(update_info), _("Some changes show after you log in again.")
    if outcome == CANCELLED:
        return _("Not updated yet"), "\n".join((
            _("Updating needs the password of an administrator account."),
            _("Click Try again and type it when asked."),
        ))
    if outcome == BUSY:
        return _("Another update is running"), "\n".join((
            _("CaramOS is already updating, in another Update Center window or in the background."),
            _("Wait until it finishes, then click Try again."),
        ))
    advice = (_("Click Ask for help to ask VNLF, with this update's log attached.") if can_ask_for_help
              else _("Open the Update Center again later to try once more."))
    return _("Could not update"), "\n".join((_("The update stopped because of an error."), advice))


def auto_update_texts() -> tuple[str, str]:
    """Title and description of the "Automatic updates" switch."""

    return _("Automatic updates"), _("New versions of CaramOS install by themselves, and you are told when they are done.")


def waiting_text(reason: str) -> str:
    """Why the last automatic try waited, under the switch of the update page ("" for none)."""

    texts = {
        system_auto_update.METERED: _("It did not update by itself this time: the connection is metered."),
        system_auto_update.BATTERY: _("It did not update by itself this time: the battery is low and the charger is "
                                      "not plugged in."),
        system_auto_update.DISK: _("It did not update by itself this time: the disk is almost full."),
        system_auto_update.APT_BUSY: _("It did not update by itself this time: another program was installing "
                                       "software."),
        system_auto_update.OTA_BUSY: _("It did not update by itself this time: another update was running."),
        system_auto_update.IN_USE: _("This update changes the desktop, so it installs by itself at the next start, "
                                     "before the login screen. This happens only once. Click Update to install it "
                                     "now."),
        system_auto_update.NO_NETWORK: _("It did not update by itself at the start: there was no network, or the "
                                         "CaramOS servers could not be reached. It tries again at the next start."),
        system_auto_update.TIME_LIMIT: _("Part of this update installed at the start; the rest installs at the next "
                                         "start. Click Update to finish it now."),
        system_auto_update.GAVE_UP: _("The last three starts did not finish this update. Click Update to install it."),
        system_auto_update.FAILED_BEFORE: _("The last automatic try did not work. Click Update to try again."),
        system_auto_update.LIVE: _("The computer runs from a USB stick, so it does not update by itself."),
        system_auto_update.OVERLAY: _("The system drive is frozen, so the computer does not update by itself."),
    }
    return texts.get(reason, "")


def auto_updated_texts(result: dict[str, Any]) -> tuple[str, str, str]:
    """Title, sentence and hint of the page of what an automatic update installed."""

    hint = _("Restart to finish.") if result.get("restart") else _("Some changes show after you log in again.")
    return done_title(result.get("update") or {}), _("CaramOS installed this update by itself."), hint


def check_failed_texts(outcome: str, *, can_ask_for_help: bool) -> tuple[str, str]:
    """Title and text of the page shown when the check for new versions did not work, one sentence a line.

    Up to 1.5.0 the Update Center said CaramOS was up to date instead: it never asked the CaramOS PPA itself.
    """

    if outcome == BUSY:
        return _("Another update is running"), "\n".join((
            _("CaramOS is already checking or updating, in another window or in the background."),
            _("Wait a moment, then click Try again."),
        ))
    if outcome == OFFLINE:
        return _("Could not check for updates"), "\n".join((
            _("The computer could not reach the CaramOS update server."),
            _("Check the internet connection, then click Try again."),
            _("On a company network, ask its administrator to allow the CaramOS update server: its address is "
              "under Details."),
        ))
    if outcome == CANCELLED:
        return _("Could not check for updates"), "\n".join((
            _("This account may not check for updates on this computer."),
            _("Ask the computer's administrator to open the Update Center."),
        ))
    advice = (_("Click Ask for help to ask VNLF, with the check's log attached.") if can_ask_for_help
              else _("Open the Update Center again later to try once more."))
    return _("Could not check for updates"), "\n".join((_("Checking stopped because of an error."), advice))


def no_update_text(status: dict[str, str] | None) -> str:
    current = version_text((status or {}).get("current_version"))
    using = (_("You are using the latest version, %s.") % current) if current else _("You are using the latest version.")
    return "\n".join((using, _("The computer checks for new versions every day.")))


# Widgets -------------------------------------------------------------------------------------------


def _box(Gtk, vertical: bool = True, spacing: int = 0, *classes: str):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for css_class in classes:
        box.get_style_context().add_class(css_class)
    return box


def _label(Gtk, text: str, *classes: str, center: bool = False, paragraph: bool = False):
    """A wrapping label whose lines stay short enough to read (LINE_CHARS)."""

    from gi.repository import Pango

    label = Gtk.Label(label=text)
    label.set_line_wrap(True)
    label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    label.set_max_width_chars(LINE_CHARS)
    label.set_xalign(0.5 if center else 0.0)
    # Not stretched across the row: the label keeps its natural width, so it wraps at LINE_CHARS.
    label.set_halign(Gtk.Align.CENTER if center else Gtk.Align.START)
    if center:
        label.set_justify(Gtk.Justification.CENTER)
    if paragraph:
        try:
            attributes = Pango.AttrList()
            attributes.insert(Pango.attr_line_height_new(PARAGRAPH_LINE_HEIGHT))
            label.set_attributes(attributes)
        except (AttributeError, TypeError):
            pass   # Pango before 1.50 has no line height
    for css_class in classes:
        label.get_style_context().add_class(css_class)
    return label


def _button(Gtk, text: str, callback, *, suggested: bool = False, pill: bool = False):
    button = Gtk.Button(label=text)
    context = button.get_style_context()
    context.add_class("uc-button")
    if suggested:
        context.add_class("suggested-action")
    if pill:
        context.add_class("pill")
    button.connect("clicked", lambda _button: callback())
    return button


def _logo(Gtk):
    """The CaramOS flower, which only the page that introduces the update shows."""

    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon("caramos-logo"):
        image = Gtk.Image.new_from_icon_name("caramos-logo", Gtk.IconSize.DIALOG)
        image.set_pixel_size(LOGO_SIZE)
        return image
    if CARAMOS_ICON.exists():
        from gi.repository import GdkPixbuf

        return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(str(CARAMOS_ICON), LOGO_SIZE, LOGO_SIZE))
    return None


def _intro(Gtk, headline: str, sentence: str):
    intro = _box(Gtk, False, 16)
    logo = _logo(Gtk)
    if logo is not None:
        logo.set_valign(Gtk.Align.CENTER)
        intro.pack_start(logo, False, False, 0)
    texts = _box(Gtk, True, 2)
    texts.set_valign(Gtk.Align.CENTER)
    texts.pack_start(_label(Gtk, headline, "uc-title"), False, False, 0)
    if sentence:
        texts.pack_start(_label(Gtk, sentence, "uc-dim", paragraph=True), False, False, 0)
    intro.pack_start(texts, True, True, 0)
    return intro


def _row(Gtk, title: str, description: str = "", *classes: str):
    row = _box(Gtk, True, 2, "uc-row")
    row.pack_start(_label(Gtk, title, "uc-row-title", *classes), False, False, 0)
    if description:
        row.pack_start(_label(Gtk, description, "uc-dim", *classes, paragraph=True), False, False, 0)
    return row


def _section(Gtk, heading: str, rows: list):
    """A heading over a boxed list."""

    section = _box(Gtk, True, 8)
    section.pack_start(_label(Gtk, heading, "uc-heading"), False, False, 0)
    boxed = _box(Gtk, True, 0, "uc-list")
    for row in rows:
        boxed.pack_start(row, False, False, 0)
    section.pack_start(boxed, False, False, 0)
    return section


def _details(Gtk, rows: list[tuple[str, str]]):
    """Technical facts in a collapsed Details expander: names in a column, their values beside them."""

    expander = Gtk.Expander(label=_("Details"))
    expander.get_style_context().add_class("uc-details")
    expander.set_spacing(8)
    grid = Gtk.Grid()
    grid.set_column_spacing(16)
    grid.set_row_spacing(6)
    for index, (name, value) in enumerate(rows):
        key = _label(Gtk, name, "uc-dim")
        key.set_line_wrap(False)
        key.set_valign(Gtk.Align.START)
        grid.attach(key, 0, index, 1, 1)
        grid.attach(_label(Gtk, value, "uc-dim", paragraph=True), 1, index, 1, 1)
    expander.add(grid)
    return expander


def _log_details(Gtk, text: str, *, fill: bool):
    """A collapsed Details expander over a read-only log; returns (box, text view).

    The log sits under the expander rather than inside it: GTK 3's expander keeps its natural height, so a log inside
    could not grow. fill: once open, the log takes the rest of the page (the progress page) instead of 180 px.
    """

    box = _box(Gtk, True, 8)
    expander = Gtk.Expander(label=_("Details"))
    expander.get_style_context().add_class("uc-details")
    scroll = Gtk.ScrolledWindow()
    scroll.get_style_context().add_class("uc-log")
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    scroll.set_vexpand(fill)
    view = Gtk.TextView()
    view.get_style_context().add_class("uc-log-view")
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(12)
    view.set_right_margin(12)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.get_buffer().set_text(text)
    view.show()
    scroll.add(view)
    # Hidden until the expander opens; the window's show_all() leaves it hidden.
    scroll.set_no_show_all(True)
    expander.connect("notify::expanded", lambda widget, _param: scroll.set_visible(widget.get_expanded()))
    box.pack_start(expander, False, False, 0)
    box.pack_start(scroll, True, True, 0)
    return box, view


def _scrolled_body(Gtk):
    """(scrolled window, body box) of a page: 24 px margins, 24 px between sections."""

    scroll = Gtk.ScrolledWindow()
    scroll.get_style_context().add_class("uc-body")
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(120)
    body = _box(Gtk, True, 24)
    for side in ("top", "bottom", "start", "end"):
        getattr(body, f"set_margin_{side}")(24)
    scroll.add(body)
    return scroll, body


def _page(Gtk, body_children: list, buttons: list, hint: str = ""):
    """A scrolled body over a fixed action bar that is always visible: the hint at the left, the buttons at the right
    with the main one last."""

    page = _box(Gtk, True, 0, "uc-page")
    scroll, body = _scrolled_body(Gtk)
    for child in body_children:
        # fill: a child that expands (the open log) gets the space; without it GTK centres the child in the space.
        body.pack_start(child, False, True, 0)
    page.pack_start(scroll, True, True, 0)

    if buttons or hint:
        bar = _box(Gtk, False, 12, "uc-actions")
        if hint:
            note = _label(Gtk, hint, "uc-dim")
            note.set_valign(Gtk.Align.CENTER)
            bar.pack_start(note, True, True, 0)
        row = _box(Gtk, False, 12)
        row.set_valign(Gtk.Align.CENTER)
        for button in buttons:
            row.pack_start(button, False, False, 0)
        bar.pack_end(row, False, False, 0)
        page.pack_end(bar, False, False, 0)
    return page


@dataclass
class AutoUpdateSwitch:
    """The "Automatic updates" switch of a page.

    on_toggle(wanted, finish) runs when the person flips it; it changes the setting (an administrator's password) and
    then calls finish(actual) with the setting as it is, which puts the switch there. note: why the last automatic try
    waited (caramos_ota.auto_update.REASONS), said under the switch.
    """

    enabled: bool
    on_toggle: Callable[[bool, Callable[[bool], Any]], Any]
    note: str = ""


def _auto_update_list(Gtk, model: AutoUpdateSwitch):
    """The switch in a boxed list (title, description, switch at the right), and the note under it."""

    title, description = auto_update_texts()
    switch = Gtk.Switch()
    switch.set_active(model.enabled)
    switch.set_valign(Gtk.Align.CENTER)
    accessible = switch.get_accessible()
    if accessible is not None:
        accessible.set_name(title)
    syncing = [False]

    def finish(actual: bool) -> bool:
        syncing[0] = True
        switch.set_active(actual)
        switch.set_state(actual)
        syncing[0] = False
        switch.set_sensitive(True)
        model.enabled = actual
        return False   # once, as a GLib idle callback

    def state_set(widget, wanted: bool) -> bool:
        if syncing[0] or wanted == model.enabled:
            return False
        widget.set_sensitive(False)
        model.on_toggle(wanted, finish)
        return True   # the switch shows the new place; its state follows once the setting is written

    switch.connect("state-set", state_set)
    row = _box(Gtk, False, 12, "uc-row")
    texts = _box(Gtk, True, 2)
    texts.pack_start(_label(Gtk, title, "uc-row-title"), False, False, 0)
    texts.pack_start(_label(Gtk, description, "uc-dim", paragraph=True), False, False, 0)
    row.pack_start(texts, True, True, 0)
    row.pack_end(switch, False, False, 0)
    boxed = _box(Gtk, True, 0, "uc-list")
    boxed.pack_start(row, False, False, 0)
    note = waiting_text(model.note) if model.enabled else ""
    if not note:
        return boxed
    section = _box(Gtk, True, 8)
    section.pack_start(boxed, False, False, 0)
    section.pack_start(_label(Gtk, note, "uc-dim", paragraph=True), False, False, 0)
    return section


def _status_page(Gtk, icon_name: str, title: str, text: str, buttons: list, detail: str = "", extra=None):
    """A centred status: a 64 px symbolic icon, the title, a sentence or two, then the buttons right under them, so
    they are on screen at the smallest window size; the details sit at the bottom. extra: a widget under the buttons
    (the switch of the page that says CaramOS is up to date), where it does not push them off a small window.
    icon_name "": a spinner instead of the icon, while the window waits for something."""

    page = _box(Gtk, True, 0, "uc-page")
    scroll, body = _scrolled_body(Gtk)
    status = _box(Gtk, True, 0)
    status.set_valign(Gtk.Align.CENTER)
    status.set_vexpand(True)
    if icon_name:
        icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        icon.set_pixel_size(STATUS_ICON_SIZE)
        icon.set_margin_bottom(24)
    else:
        # The theme's spinner is a filled disc: at the icons' 64 px it looked heavy. Smaller, in the same space, so the
        # title does not move when the result replaces it.
        icon = Gtk.Spinner()
        icon.set_size_request(SPINNER_SIZE, SPINNER_SIZE)
        icon.set_halign(Gtk.Align.CENTER)
        margin = (STATUS_ICON_SIZE - SPINNER_SIZE) // 2
        icon.set_margin_top(margin)
        icon.set_margin_bottom(24 + margin)
        icon.start()
    icon.get_style_context().add_class("uc-status-icon")
    status.pack_start(icon, False, False, 0)
    status.pack_start(_label(Gtk, title, "uc-title", center=True), False, False, 0)
    sentence = _label(Gtk, text, center=True, paragraph=True)
    sentence.set_margin_top(12)
    status.pack_start(sentence, False, False, 0)
    row = _box(Gtk, False, 12)
    row.set_halign(Gtk.Align.CENTER)
    row.set_margin_top(24)
    for button in buttons:
        row.pack_start(button, False, False, 0)
    status.pack_start(row, False, False, 0)
    if extra is not None:
        extra.set_margin_top(24)
        extra.set_halign(Gtk.Align.CENTER)
        status.pack_start(extra, False, False, 0)
    body.pack_start(status, True, True, 0)
    if detail:
        details, _view = _log_details(Gtk, detail, fill=False)
        body.pack_start(details, False, True, 0)
    page.pack_start(scroll, True, True, 0)
    return page


# Window and pages ------------------------------------------------------------------------------


def build_update_window():
    """Build the single top-level window used by every notifier state."""

    Gtk, Gdk, _glib = import_gtk()
    apply_theme(Gtk, Gdk)

    window = Gtk.Window()
    window.get_style_context().add_class("caramos-ota")
    # A plain header bar as the desktop's theme draws it; the title is the name of the app in the menu.
    header = Gtk.HeaderBar()
    header.set_show_close_button(True)
    header.set_title(_("Update Center"))
    window.set_titlebar(header)
    window.set_title(_("Update Center"))
    window.set_default_size(*_screen_dialog_size(Gdk))
    # Small enough for any laptop screen; the page bodies scroll and the action bar stays visible.
    window.set_size_request(380, 360)
    window.set_resizable(True)
    window.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(window, Gtk)

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(180)
    window.add(stack)
    return window, stack


def build_update_page(update_info: dict[str, Any], on_accept, on_close, auto_update: AutoUpdateSwitch | None = None):
    """Build the available-update page: what the update brings, the Automatic updates switch, Later and Update."""

    Gtk, _gdk, _glib = import_gtk()
    headline, sentence = update_intro(update_info)
    rows = []
    if is_security_update(update_info):
        rows.append(_row(Gtk, _("Security update"), _("It fixes a security problem. Update soon."), "uc-warning"))
    rows += [_row(Gtk, title, description) for title, description in change_rows(update_info)]
    children = [_intro(Gtk, headline, sentence), _section(Gtk, _("What's new"), rows)]
    if auto_update is not None:
        children.append(_auto_update_list(Gtk, auto_update))
    details = update_details(update_info)
    if details:
        children.append(_details(Gtk, details))
    later = _button(Gtk, _("Later"), on_close)
    buttons = [later, _button(Gtk, _("Update"), on_accept, suggested=True)]
    # The window would focus the first control in the page, the Details expander under the list, and scroll down to
    # it. Later takes the focus instead: the window can open by itself at login, while someone types elsewhere.
    later.connect("map", lambda button: button.grab_focus())
    return _page(Gtk, children, buttons, hint=_("You can keep using the computer while it updates."))


def _screen_dialog_size(Gdk, *, max_width: int = 600, max_height: int = 680) -> tuple[int, int]:
    """Default window size: comfortable on large screens, never larger than the monitor's work area."""

    width, height = 1024, 728
    display = Gdk.Display.get_default()
    monitor = None
    if display is not None:
        monitor = display.get_primary_monitor() or display.get_monitor(0)
    if monitor is not None:
        area = monitor.get_workarea()
        width, height = area.width, area.height
    return max(380, min(max_width, width - 64)), max(360, min(max_height, height - 64))


def build_progress_page(update_info: dict[str, Any] | None = None):
    """Build the progress page shown during the update: (page, progress bar, stage label, log view)."""

    Gtk, _gdk, _glib = import_gtk()
    status = _box(Gtk, True, 0)
    status.pack_start(_label(Gtk, progress_title(update_info), "uc-title"), False, False, 0)
    stage_lbl = _label(Gtk, _("Getting ready…"))
    stage_lbl.set_margin_top(4)
    status.pack_start(stage_lbl, False, False, 0)
    progress = Gtk.ProgressBar()
    progress.get_style_context().add_class("uc-progress")
    progress.set_pulse_step(0.05)
    progress.set_margin_top(16)
    status.pack_start(progress, False, False, 0)
    hint = _label(Gtk, _("Do not turn off the computer until it finishes."), "uc-dim")
    hint.set_margin_top(8)
    status.pack_start(hint, False, False, 0)

    details, log_view = _log_details(Gtk, "", fill=True)
    page = _page(Gtk, [status, details], [])
    return page, progress, stage_lbl, log_view


def build_result_page(outcome: str, detail: str, on_close, on_help=None, on_retry=None, *,
                      update_info: dict[str, Any] | None = None):
    """Build the status page shown after an update run (outcome: DONE, FAILED, CANCELLED or BUSY).

    on_help: after a failure, ask VNLF for help with the log. on_retry: run the update again, offered when
    no password was given or another update was running.
    """

    Gtk, _gdk, _glib = import_gtk()
    title, text = result_texts(outcome, update_info, can_ask_for_help=on_help is not None)
    # Close first, the action last, as Later and Update on the update page.
    buttons = [_button(Gtk, _("Close"), on_close, pill=True)]
    if on_help is not None:
        buttons.append(_button(Gtk, _("Ask for help"), on_help, pill=True))
    if on_retry is not None:
        buttons.append(_button(Gtk, _("Try again"), on_retry, suggested=True, pill=True))
    return _status_page(Gtk, STATUS_ICONS.get(outcome, STATUS_ICONS[FAILED]), title, text, buttons,
                        detail="" if outcome == DONE else detail or "")


def build_checking_page(on_close):
    """Build the page shown while the Update Center checks for new versions, a few seconds to a minute."""

    Gtk, _gdk, _glib = import_gtk()
    return _status_page(Gtk, "", _("Checking for updates…"),
                        _("The Update Center is asking the CaramOS update server for new versions."),
                        [_button(Gtk, _("Close"), on_close, pill=True)])


def build_check_failed_page(outcome: str, detail: str, on_close, on_help=None, on_retry=None):
    """Build the page shown when the check for new versions did not work (outcome: OFFLINE, BUSY, CANCELLED or
    FAILED), with the check's output under Details."""

    Gtk, _gdk, _glib = import_gtk()
    title, text = check_failed_texts(outcome, can_ask_for_help=on_help is not None)
    buttons = [_button(Gtk, _("Close"), on_close, pill=True)]
    if on_help is not None:
        buttons.append(_button(Gtk, _("Ask for help"), on_help, pill=True))
    if on_retry is not None:
        buttons.append(_button(Gtk, _("Try again"), on_retry, suggested=True, pill=True))
    icon = STATUS_ICONS[BUSY] if outcome == BUSY else STATUS_ICONS[FAILED]
    return _status_page(Gtk, icon, title, text, buttons, detail=detail or "")


def build_no_update_page(status: dict[str, str] | None, on_close, auto_update: AutoUpdateSwitch | None = None):
    """Build the page shown after a manual check finds no update, with the Automatic updates switch."""

    Gtk, _gdk, _glib = import_gtk()
    extra = _auto_update_list(Gtk, auto_update) if auto_update is not None else None
    return _status_page(Gtk, UP_TO_DATE_ICON, _("CaramOS is up to date"), no_update_text(status),
                        [_button(Gtk, _("Close"), on_close, pill=True)], extra=extra)


def build_auto_updated_page(result: dict[str, Any], on_close, auto_update: AutoUpdateSwitch | None = None):
    """Build the page of what an automatic update installed ("See what's new" in its notification): the version, the
    changes, the switch, and in the action bar whether a restart or the next login finishes it."""

    Gtk, _gdk, _glib = import_gtk()
    update_info = result.get("update") or {}
    headline, sentence, hint = auto_updated_texts(result)
    rows = [_row(Gtk, title, description) for title, description in change_rows(update_info)]
    children = [_intro(Gtk, headline, sentence), _section(Gtk, _("What's new"), rows)]
    if auto_update is not None:
        children.append(_auto_update_list(Gtk, auto_update))
    close = _button(Gtk, _("Close"), on_close)
    close.connect("map", lambda button: button.grab_focus())
    return _page(Gtk, children, [close], hint=hint)
