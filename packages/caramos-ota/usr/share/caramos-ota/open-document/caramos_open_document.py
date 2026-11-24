"""Open office documents with an office suite, or say how to get one.

CaramOS comes without an office suite: the first page of the App Center offers ONLYOFFICE, WPS Office and
LibreOffice. /usr/share/applications/x-cinnamon-mimeapps.list and xfce-mimeapps.list, the default apps of each
desktop (written from DEFAULTS below, a test keeps them the same), make those suites the default apps of Word,
Excel, PowerPoint and OpenDocument files, and this program the last one of each list, so GIO picks it only when
none of the suites is installed. It then opens the files with another installed app that
says it opens them (Gnumeric, a suite installed some other way, an app chosen with Open With), or shows a dialog:
no app on this computer opens the file yet, with buttons for the App Center and for the list of all apps.

Before, such a file went to the default app of application/zip, which .docx, .xlsx, .pptx and OpenDocument files
are: Nemo, from the ISO's ~/.config/mimeapps.list, which only showed the folder the file is in. Without that line it
would have been File Roller, which shows the parts the file is made of.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable, Sequence

from caramos_ota.i18n import _, ngettext

DESKTOP_ID = "caramos-open-document.desktop"
APP_CENTER = "caramos-app-center.desktop"

DOCUMENT = "document"
SPREADSHEET = "spreadsheet"
PRESENTATION = "presentation"

# The types an office suite opens, and what each one is. OpenDocument and the Office 2007 formats are zip files to
# GIO (application/zip is their parent type), the older Office formats are not, RTF is text to GIO.
TYPES: dict[str, str] = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DOCUMENT,  # .docx
    "application/vnd.openxmlformats-officedocument.wordprocessingml.template": DOCUMENT,  # .dotx
    "application/vnd.ms-word.document.macroEnabled.12": DOCUMENT,  # .docm
    "application/vnd.ms-word.template.macroEnabled.12": DOCUMENT,  # .dotm
    "application/msword": DOCUMENT,  # .doc
    "application/rtf": DOCUMENT,  # .rtf
    "application/vnd.oasis.opendocument.text": DOCUMENT,  # .odt
    "application/vnd.oasis.opendocument.text-template": DOCUMENT,  # .ott
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": SPREADSHEET,  # .xlsx
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template": SPREADSHEET,  # .xltx
    "application/vnd.ms-excel.sheet.macroEnabled.12": SPREADSHEET,  # .xlsm
    "application/vnd.ms-excel.sheet.binary.macroEnabled.12": SPREADSHEET,  # .xlsb
    "application/vnd.ms-excel.template.macroEnabled.12": SPREADSHEET,  # .xltm
    "application/vnd.ms-excel": SPREADSHEET,  # .xls
    "application/vnd.oasis.opendocument.spreadsheet": SPREADSHEET,  # .ods
    "application/vnd.oasis.opendocument.spreadsheet-template": SPREADSHEET,  # .ots
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": PRESENTATION,  # .pptx
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow": PRESENTATION,  # .ppsx
    "application/vnd.openxmlformats-officedocument.presentationml.template": PRESENTATION,  # .potx
    "application/vnd.ms-powerpoint.presentation.macroEnabled.12": PRESENTATION,  # .pptm
    "application/vnd.ms-powerpoint.slideshow.macroEnabled.12": PRESENTATION,  # .ppsm
    "application/vnd.ms-powerpoint": PRESENTATION,  # .ppt, .pps
    "application/vnd.oasis.opendocument.presentation": PRESENTATION,  # .odp
    "application/vnd.oasis.opendocument.presentation-template": PRESENTATION,  # .otp
}

# The App Center's suites, in its order (ONLYOFFICE is the one it picks by default), each as the App Center installs
# it and as its own website or Ubuntu packages it: the first one installed opens the file.
SUITES: dict[str, tuple[str, ...]] = {
    DOCUMENT: ("org.onlyoffice.desktopeditors.desktop", "onlyoffice-desktopeditors.desktop",
               "wps-office-wps.desktop", "org.libreoffice.LibreOffice.writer.desktop", "libreoffice-writer.desktop"),
    SPREADSHEET: ("org.onlyoffice.desktopeditors.desktop", "onlyoffice-desktopeditors.desktop",
                  "wps-office-et.desktop", "org.libreoffice.LibreOffice.calc.desktop", "libreoffice-calc.desktop"),
    PRESENTATION: ("org.onlyoffice.desktopeditors.desktop", "onlyoffice-desktopeditors.desktop",
                   "wps-office-wpp.desktop", "org.libreoffice.LibreOffice.impress.desktop",
                   "libreoffice-impress.desktop"),
}

DEFAULTS: dict[str, tuple[str, ...]] = {content_type: SUITES[kind] + (DESKTOP_ID,)
                                       for content_type, kind in TYPES.items()}

# Apps that take an office document only as the zip archive it is, or as the folder it is in.
NOT_FOR_DOCUMENTS = frozenset({
    DESKTOP_ID,
    "nemo.desktop", "thunar.desktop", "org.gnome.Nautilus.desktop", "caja.desktop", "pcmanfm.desktop",
    "org.gnome.FileRoller.desktop", "file-roller.desktop", "engrampa.desktop", "xarchiver.desktop",
    "org.kde.ark.desktop", "mount-archive.desktop",
})


def pick(apps: Iterable) -> object | None:
    """The first of these GAppInfos that opens a document itself."""

    for app in apps:
        if app.get_id() not in NOT_FOR_DOCUMENTS:
            return app
    return None


def plan(files: Sequence[tuple[object, str]], apps_for: Callable[[str], Iterable]) -> tuple[list, list]:
    """([(app, [file, ...]), ...] to launch, [(file, content type), ...] that no app opens).

    `files` are (file, content type) pairs; `apps_for(content_type)` lists the apps that say they open that type,
    the one last used with it first (Gio.AppInfo.get_recommended_for_type).
    """

    launches: dict[str, tuple[object, list]] = {}
    left: list[tuple[object, str]] = []
    for file, content_type in files:
        app = pick(apps_for(content_type))
        if app is None:
            left.append((file, content_type))
        else:
            launches.setdefault(app.get_id(), (app, []))[1].append(file)
    return list(launches.values()), left


def describe(names: Sequence[str], content_types: Sequence[str]) -> tuple[str, str]:
    """The dialog's title and text for files that no app on this computer opens."""

    count = len(names)
    if count == 1:
        title = _("No app on this computer can open this file yet")
        kind = TYPES.get(content_types[0])
        if kind == SPREADSHEET:
            what = _("“%s” is a spreadsheet.") % names[0]
        elif kind == PRESENTATION:
            what = _("“%s” is a presentation.") % names[0]
        elif kind == DOCUMENT:
            what = _("“%s” is a text document.") % names[0]
        else:
            what = _("“%s” is an office document.") % names[0]
        how = _("To open and edit it, install a free office suite from the App Center: ONLYOFFICE, WPS Office or "
                "LibreOffice.")
    else:
        title = _("No app on this computer can open these files yet")
        what = ngettext("“%(name)s” and %(count)d other file are office documents.",
                        "“%(name)s” and %(count)d other files are office documents.",
                        count - 1) % {"name": names[0], "count": count - 1}
        how = _("To open and edit them, install a free office suite from the App Center: ONLYOFFICE, WPS Office or "
                "LibreOffice.")
    return title, f"{what} {how}"


def choices(apps: Iterable, key: Callable[[str], object] = str.casefold) -> list:
    """The apps "Choose Another App…" lists: those in the menu that open files, by name, without the file and
    archive managers.

    GTK's own app chooser also lists apps hidden from the menu (sign-in handlers and such) and this program.
    """

    shown = [app for app in apps if app.should_show() and (app.supports_files() or app.supports_uris())
             and app.get_id() not in NOT_FOR_DOCUMENTS]
    return sorted(shown, key=lambda app: key(app.get_display_name()))


def _content_type(file) -> str:
    from gi.repository import Gio, GLib

    try:
        info = file.query_info(Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE, Gio.FileQueryInfoFlags.NONE, None)
        content_type = info.get_content_type()
        if content_type:
            return content_type
    except GLib.Error:
        pass
    guessed, _uncertain = Gio.content_type_guess(file.get_basename(), None)
    return guessed


def _display_name(file) -> str:
    from gi.repository import Gio, GLib

    try:
        info = file.query_info(Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME, Gio.FileQueryInfoFlags.NONE, None)
        return info.get_display_name()
    except GLib.Error:
        return file.get_basename() or file.get_uri()


def _launch(app, files: list) -> bool:
    from gi.repository import Gdk, GLib

    context = Gdk.Display.get_default().get_app_launch_context()
    try:
        return app.launch(files, context)
    except GLib.Error as exc:
        print(f"caramos-open-document: {app.get_id()}: {exc.message}", file=sys.stderr)
        return False


def _error(parent, text: str) -> None:
    from gi.repository import Gtk

    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.ERROR,
                               buttons=Gtk.ButtonsType.CLOSE, text=text)
    dialog.run()
    dialog.destroy()


def _choose_app(parent, name: str):
    """The app the user picks to open the file `name` with, or None."""

    from gi.repository import Gio, GLib, Gtk

    apps = choices(Gio.AppInfo.get_all(), key=lambda text: GLib.utf8_collate_key(text, -1))
    dialog = Gtk.Dialog(title=_("Choose an App"), transient_for=parent, modal=True, destroy_with_parent=True)
    dialog.set_default_size(440, 520)
    cancel = dialog.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
    dialog.add_button(_("Open"), Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
    label = Gtk.Label(label=_("Open “%s” with:") % name, xalign=0)
    label.set_line_wrap(True)
    body.pack_start(label, False, False, 0)
    rows = Gtk.ListBox()
    rows.set_selection_mode(Gtk.SelectionMode.SINGLE)  # nothing picked until the user picks
    for app in apps:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin=6)
        icon = app.get_icon()
        if icon is not None:
            image = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.LARGE_TOOLBAR)
        else:
            image = Gtk.Image.new_from_icon_name("application-x-executable", Gtk.IconSize.LARGE_TOOLBAR)
        image.set_pixel_size(24)  # an icon given as a picture file would show at its own size
        row.pack_start(image, False, False, 0)
        row.pack_start(Gtk.Label(label=app.get_display_name(), xalign=0), True, True, 0)
        rows.add(row)
    rows.connect("row-selected", lambda _rows, row: dialog.set_response_sensitive(Gtk.ResponseType.OK,
                                                                                  row is not None))
    rows.connect("row-activated", lambda _rows, _row: dialog.response(Gtk.ResponseType.OK))
    scrolled = Gtk.ScrolledWindow(vexpand=True, shadow_type=Gtk.ShadowType.IN)
    scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scrolled.add(rows)
    body.pack_start(scrolled, True, True, 0)
    dialog.get_content_area().pack_start(body, True, True, 0)
    dialog.show_all()
    # The list took the focus and picked its first app: nothing is picked until the user picks.
    rows.unselect_all()
    cancel.grab_focus()
    chosen = None
    if dialog.run() == Gtk.ResponseType.OK:
        row = rows.get_selected_row()
        if row is not None:
            chosen = apps[row.get_index()]
    dialog.destroy()
    return chosen


RESPONSE_APP_CENTER = 1
RESPONSE_OTHER_APP = 2


def _ask(files: list, content_types: list[str]) -> None:
    """The dialog for files that no app opens: the App Center, another app, or nothing."""

    from gi.repository import Gio, Gtk

    names = [_display_name(file) for file in files]
    title, text = describe(names, content_types)
    app_center = Gio.DesktopAppInfo.new(APP_CENTER)
    dialog = Gtk.MessageDialog(message_type=Gtk.MessageType.OTHER, buttons=Gtk.ButtonsType.NONE, text=title,
                               secondary_text=text)
    dialog.set_title(_("Office Suite"))
    dialog.set_icon_name("applications-office")
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.add_button(_("Choose Another App…"), RESPONSE_OTHER_APP)
    if app_center is not None:
        button = dialog.add_button(_("Open App Center"), RESPONSE_APP_CENTER)
        button.get_style_context().add_class("suggested-action")
        dialog.set_default_response(RESPONSE_APP_CENTER)
    while True:
        response = dialog.run()
        if response == RESPONSE_APP_CENTER:
            if _launch(app_center, []):
                break
            _error(dialog, _("Could not open the App Center."))
        elif response == RESPONSE_OTHER_APP:
            chosen = _choose_app(dialog, names[0])
            if chosen is None:
                continue
            if _launch(chosen, files):
                break
            _error(dialog, _("Could not open “%(file)s” with %(app)s.") % {"file": names[0],
                                                                          "app": chosen.get_display_name()})
        else:
            break
    dialog.destroy()


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: caramos-open-document FILE...", file=sys.stderr)
        return 2

    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gio, GLib, Gtk

    GLib.set_prgname("caramos-open-document")
    GLib.set_application_name(_("Office Suite"))
    if not Gtk.init_check(None)[0]:
        print("caramos-open-document: cannot open the display", file=sys.stderr)
        return 1
    files = [(file, _content_type(file)) for file in (Gio.File.new_for_commandline_arg(arg) for arg in args)]
    launches, left = plan(files, Gio.AppInfo.get_recommended_for_type)
    failed = []
    for app, app_files in launches:
        if not _launch(app, app_files):
            failed += [(file, content_type) for file, content_type in files if file in app_files]
    left += failed
    if not left:
        # No window of ours: end the launch feedback the file manager started for this program.
        Gdk.notify_startup_complete()
        return 0
    _ask([file for file, _type in left], [content_type for _file, content_type in left])
    return 0
