"""Files copied on the Xfce Desktop paste in Files (Nemo) (ticket H-1204).

The Desktop of the Xfce edition is xfdesktop 4.18, and Files is Nemo. They pass copied files through the clipboard as
x-special/gnome-copied-files: "copy" or "cut", then the files' URIs, one per line. xfdesktop ends each URI with
"\\r\\n" (the line end of text/uri-list), while Nemo splits the list at "\\n" only: each file keeps a "\\r" at the end
of its name, and the paste fails with 'There was an error getting information about "Test.docx"' for a file
"/home/…/Desktop/Test.docx\\r" that does not exist. Thunar and Nemo write "\\n" alone. xfdesktop does too since 4.20.1
(commit 07028b76, xfdesktop#378), but Ubuntu 24.04 has 4.18.1; Nemo 6.6 still splits at "\\n" alone.

This watches the clipboard of the session. When its owner offers copied files whose list has a "\\r", it reads the
list once and offers the same files itself, with plain line ends: Nemo then pastes them (a copy, or a move after Cut),
and xfdesktop and Thunar still paste them, as they read either form. Text pasted elsewhere gets the files' paths, as
Thunar and Nemo give. Any other clipboard content is left alone, and so is everything after the next copy.
"""

from __future__ import annotations

import logging

from gi.repository import Gdk, Gio, Gtk

LOG = logging.getLogger("caramos-control-center")

COPIED_FILES = "x-special/gnome-copied-files"
URI_LIST = "text/uri-list"
TEXT = ("UTF8_STRING", "text/plain;charset=utf-8", "text/plain", "STRING", "TEXT", "COMPOUND_TEXT")
TARGETS = (COPIED_FILES, URI_LIST, *TEXT)


def fixed_list(data: bytes | None) -> tuple[str, list[str]] | None:
    """("copy" or "cut", the URIs) of a copied-files list written with "\\r\\n"; None when it has no "\\r" (nothing to
    fix) or is not such a list."""

    try:
        text = (data or b"").decode("utf-8")
    except UnicodeDecodeError:
        return None
    if "\r" not in text:
        return None
    lines = [line.strip("\r") for line in text.split("\n")]
    action, uris = lines[0], [line for line in lines[1:] if line]
    if action not in ("copy", "cut") or not uris:
        return None
    return action, uris


def copied_files(action: str, uris: list[str]) -> bytes:
    """The list as Nemo and Thunar write it: no line end after the last URI."""

    return "\n".join([action, *uris]).encode("utf-8")


def paths(uris: list[str]) -> str:
    """The files as text: their paths, or what GIO shows for a place that has none, one per line."""

    return "\n".join(Gio.File.new_for_uri(uri).get_parse_name() for uri in uris)


class CopiedFilesFix:
    """Offers copied files with a "\\r" in their list again, without it."""

    def __init__(self) -> None:
        self.offer: tuple[str, list[str]] | None = None
        self.clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.widget = Gtk.Invisible()
        for info, target in enumerate(TARGETS):
            Gtk.selection_add_target(self.widget, Gdk.SELECTION_CLIPBOARD, Gdk.Atom.intern(target, False), info)
        self.widget.connect("selection-get", self._on_selection_get)
        self.widget.connect("selection-clear-event", self._on_selection_clear)
        self.clipboard.connect("owner-change", self._on_owner_change)

    def _owns_clipboard(self) -> bool:
        window = self.widget.get_window()
        return window is not None and Gdk.selection_owner_get(Gdk.SELECTION_CLIPBOARD) == window

    def _on_owner_change(self, clipboard: Gtk.Clipboard, _event: object) -> None:
        if self._owns_clipboard():
            return
        clipboard.request_targets(self._on_targets)

    def _on_targets(self, clipboard: Gtk.Clipboard, atoms: list | None, *_args: object) -> None:
        if any(atom.name() == COPIED_FILES for atom in atoms or []):
            clipboard.request_contents(Gdk.Atom.intern(COPIED_FILES, False), self._on_copied_files)

    def _on_copied_files(self, _clipboard: Gtk.Clipboard, selection: Gtk.SelectionData, *_args: object) -> None:
        offer = fixed_list(selection.get_data() if selection.get_length() > 0 else None)
        if offer is None:
            return
        self.offer = offer
        if not Gtk.selection_owner_set(self.widget, Gdk.SELECTION_CLIPBOARD, self._server_time()):
            self.offer = None
            LOG.warning("copied files: could not take the clipboard")
            return
        LOG.info("copied files: offered %d with plain line ends", len(offer[1]))

    def _server_time(self) -> int:
        """A real time for the selection, as GTK's own clipboard takes (CurrentTime confuses clipboard managers)."""

        self.widget.realize()
        try:
            import gi

            gi.require_version("GdkX11", "3.0")
            from gi.repository import GdkX11

            return GdkX11.x11_get_server_time(self.widget.get_window())
        except (ImportError, ValueError, TypeError):
            return Gdk.CURRENT_TIME

    def _on_selection_get(self, _widget: Gtk.Widget, selection: Gtk.SelectionData, info: int, _time: int) -> None:
        if self.offer is None:
            return
        action, uris = self.offer
        target = TARGETS[info] if 0 <= info < len(TARGETS) else ""
        if target == COPIED_FILES:
            selection.set(selection.get_target(), 8, copied_files(action, uris))
        elif target == URI_LIST:
            selection.set_uris(uris)
        else:
            selection.set_text(paths(uris), -1)

    def _on_selection_clear(self, _widget: Gtk.Widget, _event: object) -> bool:
        self.offer = None  # someone copied something else
        return False
