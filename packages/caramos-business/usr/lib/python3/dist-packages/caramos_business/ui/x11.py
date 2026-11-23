"""Keeping a window above the others on X11: GTK 4 has no call for it, so the window's _NET_WM_STATE gets
_NET_WM_STATE_ABOVE through libX11 (both Cinnamon's Muffin and Xfwm honour it). Nothing happens on Wayland or without
libX11: the prompt then is an ordinary window."""

from __future__ import annotations

import ctypes
import ctypes.util
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk  # noqa: E402

_NET_WM_STATE_ADD = 1
CLIENT_MESSAGE = 33
SUBSTRUCTURE_MASK = (1 << 19) | (1 << 20)  # SubstructureNotifyMask | SubstructureRedirectMask
XA_ATOM = 4
PROP_MODE_REPLACE = 0


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _Event(ctypes.Union):
    _fields_ = [("client", _ClientMessage), ("pad", ctypes.c_long * 24)]


def _xid(window: Gtk.Window) -> int | None:
    surface = window.get_surface()
    if surface is None:
        return None
    try:
        gi.require_version("GdkX11", "4.0")
        from gi.repository import GdkX11
    except (ImportError, ValueError):
        return None
    if not isinstance(surface, GdkX11.X11Surface):
        return None
    return surface.get_xid()


def _libx11() -> Any:
    name = ctypes.util.find_library("X11")
    if not name:
        return None
    lib = ctypes.CDLL(name)
    lib.XOpenDisplay.restype = ctypes.c_void_p
    lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    lib.XInternAtom.restype = ctypes.c_ulong
    lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    lib.XDefaultRootWindow.restype = ctypes.c_ulong
    lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    lib.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.POINTER(_Event)]
    lib.XChangeProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
    lib.XFlush.argtypes = [ctypes.c_void_p]
    lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    return lib


def keep_above(window: Gtk.Window, mapped: bool) -> bool:
    """Asks the window manager to keep the window above the others. Before the window is mapped this sets the state
    property; after, it sends the EWMH client message. Whether it could."""

    xid = _xid(window)
    if xid is None:
        return False
    try:
        lib = _libx11()
        if lib is None:
            return False
        display = lib.XOpenDisplay(None)
        if not display:
            return False
        try:
            state = lib.XInternAtom(display, b"_NET_WM_STATE", 0)
            above = lib.XInternAtom(display, b"_NET_WM_STATE_ABOVE", 0)
            if not mapped:
                atoms = (ctypes.c_ulong * 1)(above)
                lib.XChangeProperty(display, xid, state, XA_ATOM, 32, PROP_MODE_REPLACE, atoms, 1)
            else:
                event = _Event()
                event.client.type = CLIENT_MESSAGE
                event.client.send_event = 1
                event.client.window = xid
                event.client.message_type = state
                event.client.format = 32
                event.client.data[0] = _NET_WM_STATE_ADD
                event.client.data[1] = above
                event.client.data[2] = 0
                event.client.data[3] = 1  # from a normal application
                lib.XSendEvent(display, lib.XDefaultRootWindow(display), 0, SUBSTRUCTURE_MASK, ctypes.byref(event))
            lib.XFlush(display)
        finally:
            lib.XCloseDisplay(display)
    except (OSError, AttributeError, ctypes.ArgumentError):
        return False
    return True


def stay_above(window: Gtk.Window) -> None:
    """Keeps a window above the others from when it is shown."""

    def mapped(widget: Gtk.Window) -> None:
        keep_above(widget, mapped=True)
        # Again once the window manager has taken the window: a message for a window it does not manage yet is lost.
        GLib.timeout_add(300, lambda: keep_above(widget, mapped=True) and False)

    window.connect("realize", lambda widget: keep_above(widget, mapped=False))
    window.connect("map", mapped)
