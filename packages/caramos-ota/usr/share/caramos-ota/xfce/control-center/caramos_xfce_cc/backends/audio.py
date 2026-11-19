"""Sound output and input through `pactl`, which PipeWire's pipewire-pulse answers on CaramOS.

The Cinnamon applet uses Cinnamon's Cvc library, which the Xfce edition does not have. `pactl -f json` gives the same
facts: the devices, the default ones, their volume and mute. `pactl subscribe` tells when something changes.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field

from gi.repository import Gio, GLib, GObject

from ..util import run_async

LOG = logging.getLogger("caramos-control-center")

NORM = 65536  # PulseAudio's 100 %
REFRESH_DELAY_MS = 120
RESUBSCRIBE_SECONDS = 3


def subscribe_argv(command: tuple[str, ...] = ("pactl", "subscribe")) -> list[str]:
    """`pactl subscribe`, made to end with the Control Center.

    Killed (the taskbar restarting, a crash), the Control Center used to leave it running until logout, one more for
    each restart, since libpulse ignores the SIGPIPE that its next event raises. setpriv (util-linux) has the kernel
    send it SIGTERM when its parent ends.
    """

    if shutil.which("setpriv"):
        return ["setpriv", "--pdeathsig", "TERM", "--", *command]
    return list(command)


@dataclass
class AudioDevice:
    name: str
    description: str
    volume: float  # 1.0 is 100 %
    muted: bool
    default: bool = False


@dataclass
class AudioState:
    available: bool = False
    outputs: list[AudioDevice] = field(default_factory=list)
    inputs: list[AudioDevice] = field(default_factory=list)

    def device(self, kind: str) -> AudioDevice | None:
        devices = self.outputs if kind == "output" else self.inputs
        return next((device for device in devices if device.default), devices[0] if devices else None)


def device_volume(entry: dict) -> float:
    values = [channel.get("value", 0) for channel in (entry.get("volume") or {}).values() if isinstance(channel, dict)]
    return sum(values) / len(values) / NORM if values else 0.0


def is_monitor(entry: dict) -> bool:
    """A source that only records what a sound card plays, not a microphone."""

    monitor_of = entry.get("monitor_of_sink")
    return entry.get("name", "").endswith(".monitor") or monitor_of not in (None, "", "n/a")


def parse_devices(text: str, default_name: str, inputs: bool) -> list[AudioDevice]:
    try:
        entries = json.loads(text or "[]")
    except ValueError:
        return []
    devices = []
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not entry.get("name") or inputs and is_monitor(entry):
            continue
        devices.append(AudioDevice(name=entry["name"], description=entry.get("description") or entry["name"],
                                   volume=device_volume(entry), muted=bool(entry.get("mute")),
                                   default=entry["name"] == default_name))
    return devices


def volume_icon(volume: float, muted: bool, microphone: bool = False) -> str:
    if microphone:
        level = "muted" if muted or volume <= 0 else "low" if volume < 0.34 else "medium" if volume < 0.67 else "high"
        return f"microphone-sensitivity-{level}-symbolic"
    if muted or volume <= 0:
        return "audio-volume-muted-symbolic"
    return "audio-volume-low-symbolic" if volume < 0.34 else "audio-volume-medium-symbolic" if volume < 0.67 \
        else "audio-volume-high-symbolic"


class AudioBackend(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.state = AudioState()
        self.recording = False  # an application is recording: the panel shows the microphone
        self._refresh_id = 0
        self._refreshing = False
        self._again = False
        self._pending_volume: dict[str, tuple[str, float]] = {}
        self._volume_busy: dict[str, bool] = {}
        self._subscriber: Gio.Subprocess | None = None
        self._subscribe()
        self.refresh()

    # -- reading ---------------------------------------------------------------------------------------------------

    def _subscribe(self) -> None:
        try:
            self._subscriber = Gio.Subprocess.new(subscribe_argv(), Gio.SubprocessFlags.STDOUT_PIPE)
        except GLib.Error as exc:
            LOG.warning("pactl subscribe: %s", exc.message)
            GLib.timeout_add_seconds(RESUBSCRIBE_SECONDS * 10, self._resubscribe)
            return
        stream = Gio.DataInputStream.new(self._subscriber.get_stdout_pipe())
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, stream)

    def _resubscribe(self) -> bool:
        self._subscribe()
        self.refresh()
        return False

    def _on_line(self, stream: Gio.DataInputStream, result: Gio.AsyncResult, _data: object) -> None:
        try:
            line, _length = stream.read_line_finish_utf8(result)
        except GLib.Error:
            line = None
        if line is None:  # the sound server went away: try again in a moment
            GLib.timeout_add_seconds(RESUBSCRIBE_SECONDS, self._resubscribe)
            return
        if any(word in line for word in ("sink", "source", "server", "card")):
            self.schedule_refresh()
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self._on_line, stream)

    def schedule_refresh(self) -> None:
        if not self._refresh_id:
            self._refresh_id = GLib.timeout_add(REFRESH_DELAY_MS, self._refresh_now)

    def _refresh_now(self) -> bool:
        self._refresh_id = 0
        self.refresh()
        return False

    def refresh(self) -> None:
        if self._refreshing:
            self._again = True
            return
        self._refreshing = True
        results: dict[str, str] = {}

        def step(names: list[str]) -> None:
            if not names:
                self._finish(results)
                return
            name = names[0]
            argv = ["pactl", "-f", "json"] + (["info"] if name == "info" else ["list", name])

            def done(ok: bool, out: str, _err: str) -> None:
                results[name] = out if ok else ""
                step(names[1:])

            run_async(argv, done)

        step(["info", "sinks", "sources", "source-outputs"])

    def _finish(self, results: dict[str, str]) -> None:
        self._refreshing = False
        try:
            info = json.loads(results.get("info") or "{}")
        except ValueError:
            info = {}
        if not isinstance(info, dict) or not info:
            self.state = AudioState(available=False)
        else:
            self.state = AudioState(
                available=True,
                outputs=parse_devices(results.get("sinks", ""), info.get("default_sink_name", ""), inputs=False),
                inputs=parse_devices(results.get("sources", ""), info.get("default_source_name", ""), inputs=True),
            )
        self.recording = self._recording(results.get("source-outputs", ""))
        self.emit("changed")
        if self._again:
            self._again = False
            self.refresh()

    @staticmethod
    def _recording(text: str) -> bool:
        """Whether an application (not a level meter of the sound settings) is recording."""

        try:
            outputs = json.loads(text or "[]")
        except ValueError:
            return False
        for output in outputs if isinstance(outputs, list) else []:
            props = output.get("properties", {}) if isinstance(output, dict) else {}
            if props.get("application.id") in ("org.PulseAudio.pavucontrol",):
                continue
            if props.get("stream.monitor") == "true" or str(props.get("media.name", "")).startswith("Peak detect"):
                continue
            return True
        return False

    # -- changing --------------------------------------------------------------------------------------------------

    def set_volume(self, kind: str, fraction: float) -> None:
        """Set the default device's volume; while a slider is dragged, only the newest value is sent next."""

        device = self.state.device(kind)
        if device is None:
            return
        device.volume = fraction
        self._pending_volume[kind] = (device.name, fraction)
        if not self._volume_busy.get(kind):
            self._send_volume(kind)

    def _send_volume(self, kind: str) -> None:
        name, fraction = self._pending_volume.pop(kind)
        self._volume_busy[kind] = True
        verb = "set-sink-volume" if kind == "output" else "set-source-volume"
        percent = f"{round(max(0.0, min(fraction, 1.0)) * 100)}%"

        def done(_ok: bool, _out: str, _err: str) -> None:
            self._volume_busy[kind] = False
            if kind in self._pending_volume:
                self._send_volume(kind)

        run_async(["pactl", verb, name, percent], done)

    def toggle_mute(self, kind: str) -> None:
        device = self.state.device(kind)
        if device is None:
            return
        device.muted = not device.muted
        self.emit("changed")
        verb = "set-sink-mute" if kind == "output" else "set-source-mute"
        run_async(["pactl", verb, device.name, "toggle"], lambda *_: self.schedule_refresh())

    def set_default(self, kind: str, name: str) -> None:
        verb = "set-default-sink" if kind == "output" else "set-default-source"
        run_async(["pactl", verb, name], lambda *_: self.schedule_refresh())
