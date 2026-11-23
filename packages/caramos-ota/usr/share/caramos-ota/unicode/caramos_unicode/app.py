"""Chuyển mã sang Unicode: the command line, and the window of Files > right-click > "Chuyển mã sang Unicode".

    caramos-unicode [--from guess|tcvn3|vni|lines] FILE...   convert; print where each new file went
    caramos-unicode --gui FILE...                              the same in a small window (the Nemo action)

Every file gets a new file "<name> (Unicode).<ext>" next to it; the old file is never changed. Text without fonts
(.txt, .csv, web pages without legacy fonts) is read in the encoding legacy.guess() finds; when the guess is unsure the
window shows what the text becomes in TCVN3 and in VNI and lets the user pick, and the command line asks for --from.
"""

from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from caramos_ota.i18n import _, ngettext

from . import formats, legacy

APP_ID = "net.vietnamlinuxfamily.CaramOSUnicode"
GUESS = "guess"


def encoding_name(encoding: str | None) -> str:
    return {legacy.TCVN3: "TCVN3 (ABC)", legacy.VNI: "VNI Windows",
            formats.MIXED: _("TCVN3 and VNI")}.get(encoding or "", "")


def describe(result: formats.Result) -> str:
    """One sentence about a converted file, for the window and the command line."""

    if result.output is None:
        return result.note
    text = _("From {encoding}. The old file stays as it was.").format(encoding=encoding_name(result.encoding))
    if result.fallback:
        text += " " + _("Its folder cannot be written, so the new file is in your Documents folder.")
    return text


# ---- Command line --------------------------------------------------------------------------------------------

def run_cli(paths: list[Path], choice: str) -> int:
    status = 0
    for path in paths:
        try:
            analysis = formats.analyze(path)
            if analysis.note:
                print(f"{path}: {analysis.note}")
                continue
            if analysis.needs_choice and choice == GUESS:
                print(_("{file}: not sure whether this is TCVN3 or VNI. Run again with --from tcvn3, --from vni or "
                        "--from lines (each line on its own).").format(file=path), file=sys.stderr)
                status = 1
                continue
            result = formats.convert(path, None if choice == GUESS else choice)
        except (formats.ConversionError, OSError) as error:
            print(f"{path}: {error}", file=sys.stderr)
            status = 1
            continue
        if result.output is not None:
            print(f"{path} -> {result.output}")
            if result.fallback:
                print("  " + _("Its folder cannot be written, so the new file is in your Documents folder."))
        else:
            print(f"{path}: {result.note}")
    return status


# ---- Window --------------------------------------------------------------------------------------------------

def build_window(app, paths: list[Path]):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk, Pango

    def label(text: str, *classes: str, xalign: float = 0.0, wrap: bool = True) -> Gtk.Label:
        widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        for name in classes:
            widget.add_css_class(name)
        return widget

    class Window(Adw.ApplicationWindow):
        def __init__(self) -> None:
            super().__init__(application=app, title=_("Convert to Unicode"), default_width=560, default_height=520)
            self.set_size_request(360, 360)
            self.view = Adw.ToolbarView()
            self.view.add_top_bar(Adw.HeaderBar())
            self.set_content(self.view)
            self.paths = paths
            self.choices: dict[Path, str | None] = {}
            self.pending: list[formats.Analysis] = []
            self.notes: dict[Path, str] = {}
            self.busy(_("Reading the files…"))
            threading.Thread(target=self.analyze, daemon=True).start()

        # ---- pages ----------------------------------------------------------------------------------------

        def busy(self, text: str) -> None:
            page = Adw.StatusPage(title=text)
            spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
            page.set_child(spinner)
            self.view.set_content(page)

        def analyze(self) -> None:
            analyses = []
            for path in self.paths:
                try:
                    analyses.append(formats.analyze(path))
                except OSError as error:
                    analyses.append(formats.Analysis(path, note=str(error)))
            GLib.idle_add(self.analyzed, analyses)

        def analyzed(self, analyses: list[formats.Analysis]) -> bool:
            for analysis in analyses:
                if analysis.note:
                    self.notes[analysis.source] = analysis.note
                elif analysis.needs_choice:
                    self.pending.append(analysis)
                else:
                    self.choices[analysis.source] = None
            self.next_choice()
            return False

        def next_choice(self) -> None:
            if self.pending:
                self.ask(self.pending.pop(0))
                return
            self.busy(_("Converting…"))
            threading.Thread(target=self.convert, daemon=True).start()

        def ask(self, analysis: formats.Analysis) -> None:
            """Which encoding the text reads in, shown with what the start of the text becomes in each."""

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=24, margin_bottom=24,
                          margin_start=24, margin_end=24)
            title = label(_("Which encoding is this file in?"), "page-title")
            title.set_margin_bottom(4)
            box.append(title)
            box.append(label(_("“{name}” has old Vietnamese text, but it is not clear whether it is TCVN3 or VNI. "
                               "Choose the line that reads as Vietnamese.").format(name=analysis.source.name)))
            group = Adw.PreferencesGroup(margin_top=16)
            first = None
            buttons: dict[str, Gtk.CheckButton] = {}
            guessed = analysis.guess.encoding if analysis.guess else None
            rows = [(legacy.TCVN3, "TCVN3 (ABC)", analysis.samples.get(legacy.TCVN3, "")),
                    (legacy.VNI, "VNI Windows", analysis.samples.get(legacy.VNI, "")),
                    (formats.LINES, _("Line by line"), _("For a file with both kinds of text: each line is read the "
                                                         "way it makes sense."))]
            for key, title_text, subtitle in rows:
                check = Gtk.CheckButton(group=first, valign=Gtk.Align.CENTER)
                first = first or check
                row = Adw.ActionRow(title=title_text, subtitle=subtitle, activatable_widget=check)
                row.set_subtitle_lines(3)
                row.add_suffix(check)
                group.add(row)
                buttons[key] = check
            buttons.get(guessed or legacy.TCVN3, buttons[legacy.TCVN3]).set_active(True)
            box.append(group)
            scroller = Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=640, child=box), vexpand=True,
                                          hscrollbar_policy=Gtk.PolicyType.NEVER)
            cancel = Gtk.Button(label=_("Skip this file"))
            go = Gtk.Button(label=_("Convert"))
            go.add_css_class("suggested-action")

            def chosen(*_args) -> None:
                key = next(name for name, check in buttons.items() if check.get_active())
                self.choices[analysis.source] = key
                self.next_choice()

            def skipped(*_args) -> None:
                self.notes[analysis.source] = _("Skipped.")
                self.next_choice()

            go.connect("clicked", chosen)
            cancel.connect("clicked", skipped)
            self.view.set_content(self.with_bar(scroller, _("The old file stays as it was."), [cancel, go]))

        def with_bar(self, content: Gtk.Widget, hint: str, buttons: list[Gtk.Button]) -> Gtk.Widget:
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.append(content)
            outer.append(Gtk.Separator())
            bar = Gtk.Box(spacing=12)
            bar.add_css_class("action-bar")
            text = label(hint, "dim-label")
            text.set_hexpand(True)
            text.set_valign(Gtk.Align.CENTER)
            bar.append(text)
            for button in buttons:
                bar.append(button)
            outer.append(bar)
            return outer

        def convert(self) -> None:
            results = []
            for path in self.paths:
                if path in self.notes:
                    results.append(formats.Result(path, note=self.notes[path]))
                    continue
                try:
                    results.append(formats.convert(path, self.choices.get(path)))
                except (formats.ConversionError, OSError) as error:
                    results.append(formats.Result(path, note=str(error)))
            GLib.idle_add(self.done, results)

        def done(self, results: list[formats.Result]) -> bool:
            written = [result for result in results if result.output is not None]
            if written:
                title = _("Converted to Unicode")
                description = ngettext("The new file is next to the old one, with “(Unicode)” in its name.",
                                       "The new files are next to the old ones, with “(Unicode)” in their names.",
                                       len(written))
                icon = "emblem-ok-symbolic"
            else:
                title = _("Nothing was converted")
                description = _("Each file says why below.")
                icon = "dialog-information-symbolic"
            page = Adw.StatusPage(title=title, description=description, icon_name=icon)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            group = Adw.PreferencesGroup()
            for result in results:
                name = result.output.name if result.output else result.source.name
                row = Adw.ActionRow(title=GLib.markup_escape_text(name), subtitle=GLib.markup_escape_text(
                    describe(result)))
                row.set_subtitle_lines(4)
                group.add(row)
            content.append(Adw.Clamp(maximum_size=520, child=group))
            buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            if len(written) == 1:
                folder = Gtk.Button(label=_("Show in folder"))
                folder.add_css_class("pill")
                folder.connect("clicked", lambda *_a: self.show_items([written[0].output]))
                open_file = Gtk.Button(label=_("Open file"))
                open_file.add_css_class("pill")
                open_file.add_css_class("suggested-action")
                open_file.connect("clicked", lambda *_a: self.open_file(written[0].output))
                buttons.append(folder)
                buttons.append(open_file)
            else:
                if written:
                    folder = Gtk.Button(label=_("Show in folder"))
                    folder.add_css_class("pill")
                    folder.connect("clicked", lambda *_a: self.show_items([result.output for result in written]))
                    buttons.append(folder)
                close = Gtk.Button(label=_("Done"))
                close.add_css_class("pill")
                close.add_css_class("suggested-action")
                close.connect("clicked", lambda *_a: self.close())
                buttons.append(close)
            content.append(buttons)
            page.set_child(content)
            self.view.set_content(page)
            return False

        # ---- after ----------------------------------------------------------------------------------------

        def show_items(self, files: list[Path]) -> None:
            """Files (Nemo) with the new files selected; the folder alone when that does not work."""

            uris = [Gio.File.new_for_path(str(path)).get_uri() for path in files]
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
                bus.call_sync("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                              "org.freedesktop.FileManager1", "ShowItems", GLib.Variant("(ass)", (uris, "")),
                              None, Gio.DBusCallFlags.NONE, 5000, None)
            except GLib.Error:
                Gtk.FileLauncher.new(Gio.File.new_for_path(str(files[0].parent))).launch(self, None, None, None)

        def open_file(self, path: Path) -> None:
            Gtk.FileLauncher.new(Gio.File.new_for_path(str(path))).launch(self, None, None, None)

    return Window()


def open_window(paths: list[Path]) -> int:
    from caramos_ota import adw_style, gtk_renderer

    gtk_renderer.apply()  # cairo where OpenGL would run on the CPU
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib

    GLib.set_prgname("caramos-unicode")
    GLib.set_application_name(_("Convert to Unicode"))
    application = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app) -> None:
        adw_style.apply()
        build_window(app, paths).present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-unicode", description=_("Convert old Vietnamese TCVN3 and VNI text "
                                                                           "to Unicode, into new files."))
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    parser.add_argument("--from", dest="choice", default=GUESS,
                        choices=(GUESS, legacy.TCVN3, legacy.VNI, formats.LINES),
                        help=_("the encoding of text without fonts (default: guess)"))
    parser.add_argument("--gui", action="store_true", help=_("show a window (for the Files action)"))
    args = parser.parse_args(argv)
    paths = [path.expanduser().absolute() for path in args.files]
    if args.gui:
        return open_window(paths)
    return run_cli(paths, args.choice)
