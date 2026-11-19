"""Night Light for Xfce: warmer screen colours through XRandR gamma ramps.

Cinnamon has Night Light in its settings daemon; Xfce has nothing like it. This sets each screen's gamma ramp to a
warm white (about 4500 K), as Redshift does in its one-shot mode, and restores it when turned off. The choice is kept
in the xfconf channel caramos-control-center and applied again at login and when screens change.
"""

from __future__ import annotations

import ctypes
import logging
import math

from gi.repository import GLib

LOG = logging.getLogger("caramos-control-center")

CHANNEL = "caramos-control-center"
PROPERTY = "/night-light"
TEMPERATURE = 4500


def white_point(kelvin: int) -> tuple[float, float, float]:
    """The colour of a blackbody at that temperature, scaled so that 6500 K is white (1, 1, 1)."""

    def rgb(k: int) -> tuple[float, float, float]:
        t = k / 100
        red = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
        green = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
        blue = 255.0 if t >= 66 else 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
        return tuple(min(max(c, 0.0), 255.0) / 255 for c in (red, green, blue))  # type: ignore[return-value]

    warm, white = rgb(kelvin), rgb(6500)
    return tuple(min(w / n, 1.0) if n else 1.0 for w, n in zip(warm, white))  # type: ignore[return-value]


class _ScreenResources(ctypes.Structure):
    _fields_ = [("timestamp", ctypes.c_ulong), ("configTimestamp", ctypes.c_ulong), ("ncrtc", ctypes.c_int),
                ("crtcs", ctypes.POINTER(ctypes.c_ulong)), ("noutput", ctypes.c_int),
                ("outputs", ctypes.POINTER(ctypes.c_ulong)), ("nmode", ctypes.c_int), ("modes", ctypes.c_void_p)]


class _Gamma(ctypes.Structure):
    _fields_ = [("size", ctypes.c_int), ("red", ctypes.POINTER(ctypes.c_ushort)),
                ("green", ctypes.POINTER(ctypes.c_ushort)), ("blue", ctypes.POINTER(ctypes.c_ushort))]


def set_gamma(multipliers: tuple[float, float, float]) -> bool:
    """Give every CRTC of the X display a linear ramp scaled by (red, green, blue)."""

    try:
        x11 = ctypes.CDLL("libX11.so.6")
        xrandr = ctypes.CDLL("libXrandr.so.2")
    except OSError as exc:
        LOG.warning("night light: %s", exc)
        return False
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xrandr.XRRGetScreenResourcesCurrent.restype = ctypes.POINTER(_ScreenResources)
    xrandr.XRRGetScreenResourcesCurrent.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xrandr.XRRFreeScreenResources.argtypes = [ctypes.POINTER(_ScreenResources)]
    xrandr.XRRGetCrtcGammaSize.restype = ctypes.c_int
    xrandr.XRRGetCrtcGammaSize.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xrandr.XRRAllocGamma.restype = ctypes.POINTER(_Gamma)
    xrandr.XRRAllocGamma.argtypes = [ctypes.c_int]
    xrandr.XRRSetCrtcGamma.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_Gamma)]
    xrandr.XRRFreeGamma.argtypes = [ctypes.POINTER(_Gamma)]

    display = x11.XOpenDisplay(None)
    if not display:
        return False
    try:
        resources = xrandr.XRRGetScreenResourcesCurrent(display, x11.XDefaultRootWindow(display))
        if not resources:
            return False
        try:
            for index in range(resources.contents.ncrtc):
                crtc = resources.contents.crtcs[index]
                size = xrandr.XRRGetCrtcGammaSize(display, crtc)
                if size <= 1:
                    continue
                gamma = xrandr.XRRAllocGamma(size)
                for i in range(size):
                    level = i / (size - 1) * 65535
                    gamma.contents.red[i] = int(level * multipliers[0])
                    gamma.contents.green[i] = int(level * multipliers[1])
                    gamma.contents.blue[i] = int(level * multipliers[2])
                xrandr.XRRSetCrtcGamma(display, crtc, gamma)
                xrandr.XRRFreeGamma(gamma)
        finally:
            xrandr.XRRFreeScreenResources(resources)
        x11.XFlush(display)
        return True
    finally:
        x11.XCloseDisplay(display)


class NightLight:
    def __init__(self) -> None:
        self.channel = None
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.channel = Xfconf.Channel.get(CHANNEL)
        except (ImportError, ValueError, GLib.Error) as exc:
            LOG.warning("night light settings: %s", exc)

    @property
    def enabled(self) -> bool:
        return bool(self.channel and self.channel.get_bool(PROPERTY, False))

    def set_enabled(self, enabled: bool) -> None:
        if self.channel is not None:
            self.channel.set_bool(PROPERTY, enabled)
        set_gamma(white_point(TEMPERATURE) if enabled else (1.0, 1.0, 1.0))

    def apply(self) -> None:
        """At login and when screens change. Off, the ramps are left alone (a colour profile may have set them)."""

        if self.enabled:
            set_gamma(white_point(TEMPERATURE))
