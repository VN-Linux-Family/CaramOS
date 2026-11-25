"""Asking VNLF for help, reporting a bug or sending feedback: the form, sending and the result pages.

Driver Check opens the form for driver help. The Feedback & Help window (help_app.py, opened from the
panel applet and the menu) lets the user choose between help, a bug report and feedback. Both windows get
the pages and their flow from HelpPages. Pictures and videos come from AttachmentsBox (attachments.py), the
list of the requests sent from this computer from RequestsPage (requests.py).
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from gi.repository import Adw, Gdk, GLib, Gtk

from caramos_ota.i18n import _, ngettext

from .. import actions, helpdesk, hwprobe, media
from ..logs import COMPUTER_LOGS, Log
from ..analysis import Report
from .attachments import AttachmentsBox
from .common import (
    append_log,
    bottom_bar,
    clamp,
    header,
    icon,
    icon_bubble,
    label,
    link_button,
    log_view,
    page_box,
    pill,
    scrolled,
)
from .report import ProbeRun
from .report import result_page as probe_result_page
from .requests import RequestsPage


@dataclass(frozen=True)
class HelpRequest:
    """What the user filled in on the form."""

    kind: str
    message: str
    contact: str
    with_probe: bool
    with_report: bool
    attachments: tuple[media.Attachment, ...] = ()
    public: bool = False   # VNLF may show it to its community
    logs: tuple[Log, ...] = ()   # what the app that opened the form logged; VNLF's team only

    def log_texts(self) -> dict[str, str]:
        return {log.name: log.text for log in self.logs}


@dataclass(frozen=True)
class Kind:
    """How the form asks for one kind of request ("type" in the API)."""

    icon: str
    name: str
    blurb: str
    question: str
    hint: str
    probe: bool | None    # the hw-probe box: ticked, not ticked, or not offered
    report: bool | None   # the box "Send this computer's details" (the Driver Check results, computer.log...): the same


def kinds() -> dict[str, Kind]:
    """Built when needed: the texts are translated once the locale is set."""

    return {
        "driver": Kind("help-browser-symbolic", _("Ask for help"), _("Something does not work and you need advice"),
                       _("What is the problem?"),
                       _("For example: “After installing CaramOS the Wi-Fi does not show any networks. I have a "
                         "network cable but the laptop has no port.”"), probe=True, report=True),
        "os": Kind("help-browser-symbolic", _("Ask for help"), _("Something does not work and you need advice"),
                   _("What is the problem?"),
                   _("For example: “Since this morning there is no sound, also with headphones. I already "
                     "restarted the computer.”"), probe=False, report=True),
        "bug": Kind("caramos-bug-symbolic", _("Report a bug"), _("CaramOS or one of its apps does something wrong"),
                    _("What went wrong?"),
                    _("For example: “The Update Center stops halfway every time I install updates, also after "
                      "a restart.”"), probe=False, report=True),
        # Feedback too: a wish ("drivers for my receipt printer") is often a question about this computer.
        "feedback": Kind("chat-symbolic", _("Send feedback"), _("An idea or a wish for CaramOS"),
                         _("What would you like to tell us?"),
                         _("For example: “I would like a quicker way to switch between Telex and VNI typing.”"),
                         probe=None, report=True),
    }


def _page(content: Gtk.Widget, bar: Gtk.Widget | None, title: str, end: Gtk.Widget | None = None) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    view = Adw.ToolbarView()
    top = header(title)
    if end is not None:
        top.pack_end(end)
    view.add_top_bar(top)
    page = scrolled(clamp(content, 860))
    page.add_css_class("welcome")
    view.set_content(page)
    view.set_vexpand(True)
    box.append(view)
    if bar is not None:
        box.append(bar)
    return box


def _point(icon_name: str, text: str) -> Gtk.Widget:
    row = Gtk.Box(spacing=8)
    row.add_css_class("hero-point")
    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_valign(Gtk.Align.START)
    image.set_margin_top(2)
    row.append(image)
    text_label = label(text, "dim-label")
    text_label.set_hexpand(True)
    row.append(text_label)
    return row


class HelpForm(Gtk.Box):
    """The form; on_send(HelpRequest) starts the request. With several kinds, cards on top choose one.

    The report may come later (set_report, ready=False until then): the Feedback & Help window reads the
    computer while the user writes, and sending waits for it. When reading it failed, the report is None
    and requests go without the Driver Check results. With on_requests, the header bar opens the requests
    sent before. An app that opens the form after a failure gives a message to start from and its logs
    (logs.py), attached unless the user unticks them.
    """

    def __init__(self, kind: str, choices: tuple[str, ...], report: Report | None, *, ready: bool = True,
                 title: str, online: bool, on_send: Callable[[HelpRequest], None],
                 on_save_probe: Callable[[], None], on_back: Callable[[], None], back_label: str,
                 on_requests: Callable[[], None] | None = None, message: str = "",
                 logs: Sequence[Log] = ()) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.kinds = kinds()
        self.kind = kind
        self.report = report
        self.ready = ready
        self.online = online
        self.on_send = on_send

        content = page_box(22)
        hero = Gtk.Box(spacing=22)
        hero.add_css_class("hero-card")
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        if len(choices) > 1:
            hero.append(icon_bubble("dialog-question-symbolic", 36, "status-bubble", "status-ok"))
            texts.append(label(_("Write to the Vietnam Linux Family community"), "hero-title"))
            texts.append(label(_("Ask for help, report a bug or share an idea. The CaramOS team and the VNLF "
                                 "community read every request."), "hero-subtitle"))
        else:
            hero.append(icon_bubble("help-browser-symbolic", 36, "status-bubble", "status-ok"))
            texts.append(label(_("Ask the VNLF community for help"), "hero-title"))
            texts.append(label(_("Describe what is wrong. Your message goes to Vietnam Linux Family together with "
                                 "this computer's hardware profile, so the people helping you see exactly which "
                                 "hardware and drivers it has."), "hero-subtitle"))
        hero.append(texts)
        content.append(hero)

        self.cards: dict[str, Gtk.ToggleButton] = {}
        if len(choices) > 1:
            row = Gtk.Box(spacing=12, homogeneous=True)
            for name in choices:
                row.append(self._kind_card(name))
            content.append(row)

        form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        form.add_css_class("issue-card")
        self.question = label("", "card-title")
        form.append(self.question)
        self.message = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, accepts_tab=False)
        self.message.add_css_class("help-message")
        self.message.set_top_margin(10)
        self.message.set_bottom_margin(10)
        self.message.set_left_margin(12)
        self.message.set_right_margin(12)
        frame = Gtk.ScrolledWindow(min_content_height=150, hscrollbar_policy=Gtk.PolicyType.NEVER)
        frame.add_css_class("help-message-frame")
        frame.set_child(self.message)
        form.append(frame)
        self.hint = label("", "dim-label", "help-hint")
        form.append(self.hint)
        self.attachments = AttachmentsBox(self._attachments_changed)
        form.append(self.attachments)

        contact_title = label(_("How can we reach you? (optional)"), "card-title")
        contact_title.set_margin_top(8)
        form.append(contact_title)
        self.contact = Gtk.Entry(placeholder_text=_("Email, Zalo number or Facebook link"))
        form.append(self.contact)
        form.append(label(_("Only the VNLF team sees it. Without it, the answer is on your request's page."),
                          "dim-label", "help-hint"))

        self.with_probe = Gtk.CheckButton(label=_("Attach the hardware profile (hw-probe: 1–2 minutes, asks for "
                                                  "your password)"))
        self.with_probe.set_margin_top(8)
        if not hwprobe.available():
            self.with_probe.set_tooltip_text(_("hw-probe is not installed. Install it with: sudo apt install hw-probe"))
        form.append(self.with_probe)
        self.probe_note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.probe_note.set_margin_start(28)
        self.probe_note.append(_point("security-high-symbolic", _(
            "The hardware profile (hw-probe) leaves out user names, the computer's name and IP addresses; serial "
            "numbers and MAC addresses are only sent as hashes.")))
        guide = link_button(_("How hw-probe works"), hwprobe.GUIDE_URL)
        guide.set_halign(Gtk.Align.START)
        self.probe_note.append(guide)
        form.append(self.probe_note)
        # Ticked for every kind: the details answer most questions without asking the person to look them up.
        self.with_report = Gtk.CheckButton(label=_("Send this computer's details"))
        form.append(self.with_report)
        self.details_note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.details_note.set_margin_start(28)
        self.details_note.append(_point("security-high-symbolic", _(
            "The hardware and its drivers, the printers, the CaramOS version, how the screen locks and the computer "
            "sleeps, and recent errors. Only the VNLF team sees them, never the community. E-mail and IP addresses, "
            "the computer's name and your user name are taken out.")))
        form.append(self.details_note)
        self.logs: tuple[Log, ...] = ()
        self.with_logs = Gtk.CheckButton(active=True)
        form.append(self.with_logs)
        self.logs_note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.logs_note.set_margin_start(28)
        self.logs_note.append(_point("security-high-symbolic", _(
            "Only the VNLF team sees the log, never the community. E-mail and IP addresses, the computer's name "
            "and your user name are taken out.")))
        form.append(self.logs_note)

        preview = Gtk.Expander(label=_("See what will be sent"))
        self.preview = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                    wrap_mode=Gtk.WrapMode.WORD_CHAR)
        self.preview.add_css_class("log-view")
        preview_frame = Gtk.ScrolledWindow(min_content_height=140)
        preview_frame.add_css_class("log-scroll")
        preview_frame.set_child(self.preview)
        preview_frame.set_margin_top(8)
        preview.set_child(preview_frame)
        preview.connect("notify::expanded", lambda *_args: self._refresh_preview())
        form.append(preview)
        # Last before Send and ticked, as VNLF asks (docs 52): a moderator reviews the request before it is public.
        self.public = Gtk.CheckButton(label=_("Let the VNLF community see it and help"), active=True)
        self.public.set_margin_top(8)
        form.append(self.public)
        public_note = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        public_note.set_margin_start(28)
        public_note.append(_point("security-high-symbolic", _("Your contact is not made public.")))
        form.append(public_note)
        content.append(form)

        self.send_button = pill(_("Send"), self._send, suggested=True, icon_name="mail-send-symbolic")
        buttons: list[Gtk.Widget] = [pill(back_label, on_back)]
        self.save_probe: Gtk.Widget | None = None
        if not online and hwprobe.available():
            self.save_probe = pill(_("Save the hardware profile"), on_save_probe)
            buttons.append(self.save_probe)
        buttons.append(self.send_button)
        self.status = label("", "dim-label", "bar-detail")
        bar = bottom_bar(title, "", buttons)
        bar.get_first_child().append(self.status)
        requests = None
        if on_requests is not None:
            requests = Gtk.Button(child=Adw.ButtonContent(icon_name="document-open-recent-symbolic",
                                                          label=_("Your requests")))
            requests.add_css_class("flat")
            requests.connect("clicked", lambda _button: on_requests())
        self.append(_page(content, bar, title, requests))

        self.message.get_buffer().connect("changed", lambda *_args: self._sync())
        self.contact.connect("changed", lambda *_args: self._refresh_preview())
        self.with_probe.connect("toggled", lambda *_args: self._refresh_preview())
        self.with_report.connect("toggled", lambda *_args: self._refresh_preview())
        self.with_logs.connect("toggled", lambda *_args: self._refresh_preview())
        start = kind if kind in choices else choices[0]
        if self.cards:
            self.cards[start].set_active(True)
        self._set_kind(start)
        self.set_context(message, logs)

    def _kind_card(self, name: str) -> Gtk.ToggleButton:
        kind = self.kinds[name]
        card = Gtk.ToggleButton()
        card.add_css_class("kind-card")
        content = Gtk.Box(spacing=12)
        image = icon(kind.icon, 24)
        image.set_valign(Gtk.Align.START)
        content.append(image)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True)
        texts.append(label(kind.name, "kind-name"))
        texts.append(label(kind.blurb, "dim-label", "kind-blurb"))
        content.append(texts)
        card.set_child(content)
        if self.cards:
            card.set_group(next(iter(self.cards.values())))
        card.connect("toggled", lambda button: button.get_active() and self._set_kind(name))
        self.cards[name] = card
        return card

    def select(self, kind: str) -> None:
        """Another kind asked for from the panel; what the user wrote stays."""

        if kind in self.cards:
            self.cards[kind].set_active(True)

    def set_context(self, message: str, logs: Sequence[Log]) -> None:
        """What an app that failed passes on: the message starts the form unless the user wrote one already."""

        buffer = self.message.get_buffer()
        if message and not self._text().strip():
            buffer.set_text(message)
        if logs:
            self.logs = tuple(logs)
            self.with_logs.set_active(True)
        self.with_logs.set_label(_("Attach the app's log (%s)") % ", ".join(log.name for log in self._app_logs()))
        self._show_logs()
        self._show_details()
        self._refresh_preview()

    def _computer_logs(self) -> tuple[Log, ...]:
        """The logs about this computer (logs.COMPUTER_LOGS): they go with its details."""

        return tuple(log for log in self.logs if log.name in COMPUTER_LOGS)

    def _app_logs(self) -> tuple[Log, ...]:
        """What an app that failed logged (the App Center, the Update Center, a driver install): a box of its own."""

        return tuple(log for log in self.logs if log.name not in COMPUTER_LOGS)

    def _logs_offered(self) -> bool:
        return bool(self._app_logs())

    def _show_logs(self) -> None:
        self.with_logs.set_visible(self._logs_offered())
        self.logs_note.set_visible(self._logs_offered())

    def _show_details(self) -> None:
        self.with_report.set_visible(self._report_offered())
        self.details_note.set_visible(self._report_offered())

    def set_report(self, report: Report | None) -> None:
        self.report = report
        self.ready = True
        self._show_details()
        self._sync()
        self._refresh_preview()

    def _report_offered(self) -> bool:
        """Every kind offers the computer's details while they are read, and once there is something to send."""

        return self.kinds[self.kind].report is not None and (
            self.report is not None or bool(self._computer_logs()) or not self.ready)

    def _set_kind(self, name: str) -> None:
        self.kind = name
        kind = self.kinds[name]
        self.question.set_label(kind.question)
        self.hint.set_label(kind.hint)
        offered = kind.probe is not None
        self.with_probe.set_visible(offered)
        self.probe_note.set_visible(offered)
        self.with_probe.set_sensitive(hwprobe.available())
        self.with_probe.set_active(bool(kind.probe) and hwprobe.available())
        if self.save_probe is not None:
            self.save_probe.set_visible(offered)
        self._show_details()
        self.with_report.set_active(bool(kind.report))
        self._show_logs()
        self._sync()
        self._refresh_preview()

    def _text(self) -> str:
        buffer = self.message.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _attachments_changed(self) -> None:
        self._sync()
        self._refresh_preview()

    def cleanup(self) -> None:
        """The form is not used any more: its pictures and videos go."""

        self.attachments.cleanup()

    def _waiting(self) -> bool:
        """Sending waits for the computer's details and for the pictures and videos."""

        return not self.ready or self.attachments.preparing() or self.attachments.recording_now()

    def _probe_wanted(self) -> bool:
        return self.with_probe.get_visible() and self.with_probe.get_active()

    def _details_wanted(self) -> bool:
        return self.with_report.get_visible() and self.with_report.get_active()

    def _report_wanted(self) -> bool:
        """The Driver Check results, part of the computer's details."""

        return self.report is not None and self._details_wanted()

    def _logs_wanted(self) -> tuple[Log, ...]:
        app = self._app_logs() if self._logs_offered() and self.with_logs.get_active() else ()
        return app + (self._computer_logs() if self._details_wanted() else ())

    def _sync(self) -> None:
        problem = helpdesk.message_problem(self._text())
        self.send_button.set_sensitive(self.online and not self._waiting() and not problem)
        if not self.online:
            if self.kinds[self.kind].probe is not None and hwprobe.available():
                self.status.set_label(_("No internet: get online first, or save the hardware profile and send it "
                                        "from another device."))
            else:
                self.status.set_label(_("No internet: connect to the internet to send it."))
        elif not self.ready:
            self.status.set_label(_("Reading this computer's details…"))
        elif problem == "short":
            self.status.set_label(_("Write a few words about the problem to send it."))
        elif problem == "long":
            self.status.set_label(_("The message is too long; keep it under 5000 characters."))
        elif self.attachments.recording_now():
            self.status.set_label(_("Recording the screen: stop it (Ctrl+Shift+Alt+R) to send the video."))
        elif self.attachments.preparing():
            self.status.set_label(_("Making the pictures and videos smaller…"))
        else:
            self.status.set_label(_("Ready to send."))

    def _refresh_preview(self) -> None:
        report = self.report
        payload = helpdesk.build_request(
            self._text() or _("(your message)"), self.contact.get_text(),
            "https://linux-hardware.org/?probe=…" if self._probe_wanted() else "",
            report.to_dict() if report is not None and self._report_wanted() else None, kind=self.kind,
            kernel=report.kernel if report else "", live=report.live if report else False,
            virtual=report.virtual if report else False,
            logs={log.name: log.text for log in self._logs_wanted()})
        self.preview.get_buffer().set_text(helpdesk.as_text(payload, file_names(self.attachments.ready()),
                                                            with_logs=True))

    def _send(self) -> None:
        if helpdesk.message_problem(self._text()) or self._waiting():
            return
        self.on_send(HelpRequest(self.kind, self._text(), self.contact.get_text(), self._probe_wanted(),
                                 self._report_wanted(), tuple(self.attachments.ready()), self.public.get_active(),
                                 self._logs_wanted()))


def file_names(attachments: Sequence[media.Attachment]) -> list[str]:
    return [f"{attachment.path.name} ({GLib.format_size(attachment.size)})" for attachment in attachments]


class HelpSend:
    """Uploads the hardware profile when asked and the pictures and videos, then sends the request; builds
    the progress page.

    A probe_url from an earlier attempt is used again instead of running hw-probe a second time, and so are
    the files uploads (prepared path: attachment id) has. When hw-probe or an upload fails, nothing is
    sent: on_probe_failed and on_upload_failed let the user decide.
    """

    def __init__(self, report: Report | None, request: HelpRequest, *, title: str, app: str, probe_url: str = "",
                 upload_id: str = "", uploads: dict[str, str] | None = None,
                 on_sent: Callable[[helpdesk.SendResult, dict], None],
                 on_probe_failed: Callable[[hwprobe.ProbeResult], None],
                 on_upload_failed: Callable[[helpdesk.UploadResult], None]) -> None:
        self.report = report
        self.request = request
        self.app = app
        self.probe_url = probe_url if request.with_probe else ""
        self.upload_id = upload_id or str(uuid.uuid4())
        self.uploads = {} if uploads is None else uploads
        self.on_sent = on_sent
        self.on_probe_failed = on_probe_failed
        self.on_upload_failed = on_upload_failed
        self.uploading = False
        self.pulse = 0
        probing = request.with_probe and not self.probe_url
        content = page_box(12)
        content.append(label(_("Sending your request…"), "step-title"))
        self.stage = label(_("Collecting hardware information…") if probing else _("Sending to VNLF…"),
                           "stage-label")
        content.append(self.stage)
        self.progress = Gtk.ProgressBar()
        self.progress.add_css_class("overall")
        self.progress.set_margin_top(10)
        self.progress.set_pulse_step(0.04)
        content.append(self.progress)
        details, self.log = log_view()
        content.append(details)
        self.page = _page(content, None, title)

    def start(self) -> None:
        self.pulse = GLib.timeout_add(120, lambda: (self.uploading or self.progress.pulse(), True)[1])
        threading.Thread(target=self._work, daemon=True).start()

    def _work(self) -> None:
        request = self.request
        probe_url = self.probe_url
        if request.with_probe and not probe_url:
            probe = hwprobe.upload(lambda line: GLib.idle_add(lambda: (append_log(self.log, line), False)[1]))
            if not probe.ok:
                GLib.idle_add(self._finish, self.on_probe_failed, probe)
                return
            probe_url = probe.url
            GLib.idle_add(self._stage, _("Sending to VNLF…"))
        attachments = self._upload(request.attachments) if request.attachments else []
        if attachments is None:
            return
        report = self.report
        payload = helpdesk.build_request(
            request.message, request.contact, probe_url,
            report.to_dict() if report is not None and request.with_report else None, kind=request.kind,
            app=self.app, kernel=report.kernel if report else "", live=report.live if report else False,
            virtual=report.virtual if report else False, upload_id=self.upload_id, attachments=attachments,
            public=request.public, logs=request.log_texts())
        GLib.idle_add(self._finish, self.on_sent, helpdesk.send(payload), payload)

    def _upload(self, files: Sequence[media.Attachment]) -> list[str] | None:
        """The attachment ids in the form's order; None when an upload failed (on_upload_failed was called)."""

        total = sum(attachment.size for attachment in files) or 1
        done = 0
        ids: list[str] = []
        for number, attachment in enumerate(files, 1):
            known = self.uploads.get(str(attachment.path))
            if known is None:
                GLib.idle_add(self._stage, _("Uploading the pictures and videos (%(number)d of %(count)d)…")
                              % {"number": number, "count": len(files)}, done / total)
                shown = [0.0]

                def progress(sent: int, before: int = done) -> None:
                    fraction = (before + sent) / total
                    if fraction - shown[0] >= 0.01:
                        shown[0] = fraction
                        GLib.idle_add(self._fraction, fraction)

                result = helpdesk.upload(self.upload_id, attachment.path, attachment.mime,
                                         duration=attachment.duration, app=self.app, on_progress=progress)
                if not result.ok:
                    GLib.idle_add(self._finish, self.on_upload_failed, result)
                    return None
                known = result.attachment_id
                self.uploads[str(attachment.path)] = known
            ids.append(known)
            done += attachment.size
        GLib.idle_add(self._stage, _("Sending to VNLF…"))
        return ids

    def _stage(self, text: str, fraction: float | None = None) -> bool:
        self.stage.set_label(text)
        self.uploading = fraction is not None
        if fraction is not None:
            self.progress.set_fraction(fraction)
        return False

    def _fraction(self, fraction: float) -> bool:
        if self.uploading:
            self.progress.set_fraction(fraction)
        return False

    def _finish(self, callback, *args) -> bool:
        GLib.source_remove(self.pulse)
        callback(*args)
        return False


def probe_failed_page(probe: hwprobe.ProbeResult, *, title: str, on_back: Callable[[], None],
                      on_retry: Callable[[], None], on_send_without: Callable[[], None]) -> Gtk.Widget:
    """hw-probe did not finish and nothing was sent: the user decides whether to send without the profile."""

    content = page_box(18)
    content.append(icon_bubble("dialog-warning-symbolic", 40, "status-bubble", "status-warning"))
    content.append(label(_("The hardware profile was not made"), "hero-title", xalign=0.5))
    if probe.refused:
        reason = _("hw-probe needs your password to read the hardware, and the password was not entered.")
    else:
        reason = _("hw-probe stopped before it was done. Check the internet connection and try again.")
    content.append(label(reason, "hero-subtitle", xalign=0.5))
    content.append(label(_("Your request has not been sent yet. Try again, or send it without the hardware "
                           "profile."), "dim-label", xalign=0.5))
    if probe.output and not probe.refused:
        details, _view = log_view(probe.output)
        content.append(details)
    bar = bottom_bar(_("Not sent yet"), "", [pill(_("Back"), on_back), pill(_("Send without it"), on_send_without),
                                             pill(_("Try again"), on_retry, suggested=True)])
    return _page(content, bar, title)


def upload_failed_page(result: helpdesk.UploadResult, *, title: str, on_back: Callable[[], None],
                       on_retry: Callable[[], None], on_send_without: Callable[[], None]) -> Gtk.Widget:
    """A picture or video could not be uploaded and nothing was sent: the user decides how to go on."""

    content = page_box(18)
    content.append(icon_bubble("dialog-warning-symbolic", 40, "status-bubble", "status-warning"))
    content.append(label(_("The pictures and videos were not sent"), "hero-title", xalign=0.5))
    if result.error == "unavailable":
        reason = _("VNLF does not take pictures and videos from CaramOS yet.")
    elif result.error == "network":
        reason = _("Could not reach VNLF. Check the internet connection and try again.")
    elif result.error == "rate-limited":
        minutes = max(1, (result.retry_after + 59) // 60) if result.retry_after else 60
        reason = _("You sent many pictures and videos today. Try again in %d minutes.") % minutes
    elif result.error == "rejected":
        reason = _("VNLF did not accept one of the files.")
    else:
        reason = _("The VNLF server has a problem right now. Try again later.")
    content.append(label(reason, "hero-subtitle", xalign=0.5))
    content.append(label(_("Your request has not been sent yet. Try again, or send it without the pictures and "
                           "videos."), "dim-label", xalign=0.5))
    bar = bottom_bar(_("Not sent yet"), "", [pill(_("Back"), on_back), pill(_("Send without them"), on_send_without),
                                             pill(_("Try again"), on_retry, suggested=True)])
    return _page(content, bar, title)


def _error_text(result: helpdesk.SendResult) -> str:
    if result.error == "network":
        return _("Could not reach VNLF. Check the internet connection, or post the request yourself below.")
    if result.error == "rate-limited":
        minutes = max(1, (result.retry_after + 59) // 60) if result.retry_after else 10
        return _("You sent several requests in a short time. Try again in %d minutes.") % minutes
    if result.error == "unavailable":
        return _("The VNLF help service is not available yet. You can post the request yourself below.")
    if result.error == "rejected":
        return _("VNLF did not accept the request. You can post it yourself below.")
    return _("The VNLF server has a problem right now. Try again later, or post the request yourself below.")


def result_page(result: helpdesk.SendResult, payload: dict, *, title: str, done_label: str,
                on_done: Callable[[], None], on_back: Callable[[], None],
                on_retry: Callable[[], None], files: Sequence[media.Attachment] = ()) -> Gtk.Widget:
    content = page_box(18)
    if result.ok:
        content.append(icon_bubble("emblem-ok-symbolic", 40, "status-bubble", "status-ok"))
        content.append(label(_("Your request was sent"), "hero-title", xalign=0.5))
        content.append(label(_("VNLF answers on your request's page. You can open it again any time from Feedback "
                               "& Help (the question mark in the panel)."), "hero-subtitle", xalign=0.5))
        if payload.get("contact"):
            content.append(label(_("They may also contact you at: %s") % payload["contact"], "dim-label",
                                 xalign=0.5))
        if payload.get("attachments"):
            count = len(payload["attachments"])
            content.append(label(ngettext("With %d picture or video.", "With %d pictures or videos.", count) % count,
                                 "dim-label", xalign=0.5))
        if payload.get("public"):
            content.append(label(_("Shared with the VNLF community: it is published once VNLF has reviewed it."),
                                 "dim-label", xalign=0.5))
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card.add_css_class("issue-card")
        if result.request_id:
            card.append(label(_("Request number: %s") % result.request_id, "status-value", xalign=0.5,
                              selectable=True))
        if result.url:
            row = Gtk.Box(spacing=10, halign=Gtk.Align.CENTER)
            row.append(pill(_("Follow your request"), lambda: actions.open_url(result.url), suggested=True,
                            icon_name="web-browser-symbolic"))
            card.append(row)
        if card.get_first_child() is not None:
            content.append(card)
        bar = bottom_bar(_("Request sent"), "", [pill(done_label, on_done, suggested=True)])
        return _page(content, bar, title)

    content.append(icon_bubble("dialog-warning-symbolic", 40, "status-bubble", "status-warning"))
    content.append(label(_("The request was not sent"), "hero-title", xalign=0.5))
    content.append(label(_error_text(result), "hero-subtitle", xalign=0.5))
    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    card.add_css_class("issue-card")
    card.append(label(_("Post it yourself"), "card-title"))
    card.append(label(_("Copy the request and paste it as a new post on vietnamlinuxfamily.net, or in the VNLF "
                        "Facebook group, Telegram or Discord."), "dim-label"))
    text = helpdesk.as_text(payload, file_names(files))
    row = Gtk.Box(spacing=10)
    copy = pill(_("Copy the request"), lambda: _copy(copy, text), suggested=True, icon_name="edit-copy-symbolic")
    row.append(copy)
    row.append(pill(_("Open VNLF"), lambda: actions.open_url(hwprobe.VNLF_URL)))
    if files:
        # Made smaller and without metadata: the files to add to the post.
        folder = str(files[0].path.parent)
        row.append(pill(_("Open the pictures and videos"), lambda: actions.open_path(folder),
                        icon_name="folder-open-symbolic"))
    card.append(row)
    content.append(card)
    bar = bottom_bar(_("Not sent"), "", [pill(_("Back"), on_back), pill(_("Try again"), on_retry, suggested=True)])
    return _page(content, bar, title)


def _copy(button: Gtk.Button, text: str) -> None:
    Gdk.Display.get_default().get_clipboard().set(text)
    child = button.get_child()
    if isinstance(child, Gtk.Box) and isinstance(child.get_last_child(), Gtk.Label):
        child.get_last_child().set_label(_("Copied"))


class HelpPages:
    """The help pages of a window and the way between them: form, sending, hw-probe trouble, result.

    The window has a Gtk.Stack `stack` behind _set_page(name, widget) and a `busy` flag. It sets the
    class attributes below, gives the computer's report in help_report() (None while it is read) and
    the connection in help_online(), and decides in leave_help() where the form's Back button leads.
    """

    help_choices: tuple[str, ...] = ("driver",)
    help_app = "caramos-driver-check"
    help_form: HelpForm | None = None
    help_probe_url = ""   # the hw-probe upload of the open form, used again when it is sent again
    help_upload_id = ""   # ties the uploaded pictures and videos of the open form to its request
    help_uploads: dict[str, str] | None = None   # prepared file: its attachment id, used again likewise
    help_message = ""     # the message a new form starts with (an app that failed opened the window)
    help_logs: tuple[Log, ...] = ()   # and the logs it attaches

    def help_title(self) -> str:
        return _("Ask for help")

    def help_back_label(self) -> str:
        return _("Back")

    def help_done_label(self) -> str:
        return _("Back to Driver Check")

    def help_report_ready(self) -> bool:
        """False while the window still reads the computer."""

        return True

    def show_help(self, kind: str) -> None:
        if self.busy:
            return
        self.help_cleanup()
        self.help_probe_url = ""
        self.help_upload_id = str(uuid.uuid4())
        self.help_uploads = {}
        self.help_form = HelpForm(kind, self.help_choices, self.help_report(), ready=self.help_report_ready(),
                                  title=self.help_title(), online=self.help_online(), on_send=self._send_help,
                                  on_save_probe=self._save_probe, on_back=self.leave_help,
                                  back_label=self.help_back_label(),
                                  on_requests=self.show_requests if helpdesk.sent_requests() else None,
                                  message=self.help_message, logs=self.help_logs)
        self._set_page("help", self.help_form)

    def show_requests(self) -> None:
        """The requests sent from this computer, with what VNLF says about them now."""

        if self.busy:
            return
        page = RequestsPage(on_back=self._back_to_help)
        self._set_page("requests", page)
        page.refresh()

    def _send_help(self, request: HelpRequest) -> None:
        self.busy = True
        if self.help_uploads is None:
            self.help_uploads = {}
        run = HelpSend(self.help_report(), request, title=self.help_title(), app=self.help_app,
                       probe_url=self.help_probe_url, upload_id=self.help_upload_id, uploads=self.help_uploads,
                       on_sent=lambda result, payload: self._help_sent(request, result, payload),
                       on_probe_failed=lambda probe: self._help_probe_failed(request, probe),
                       on_upload_failed=lambda result: self._help_upload_failed(request, result))
        self._set_page("help-send", run.page)
        run.start()

    def _help_probe_failed(self, request: HelpRequest, probe: hwprobe.ProbeResult) -> None:
        self.busy = False
        page = probe_failed_page(probe, title=self.help_title(), on_back=self._back_to_help,
                                 on_retry=lambda: self._send_help(request),
                                 on_send_without=lambda: self._send_help(replace(request, with_probe=False)))
        self._set_page("help-result", page)

    def _help_upload_failed(self, request: HelpRequest, result: helpdesk.UploadResult) -> None:
        self.busy = False
        page = upload_failed_page(result, title=self.help_title(), on_back=self._back_to_help,
                                  on_retry=lambda: self._send_help(request),
                                  on_send_without=lambda: self._send_help(replace(request, attachments=())))
        self._set_page("help-result", page)

    def _help_sent(self, request: HelpRequest, result: helpdesk.SendResult, payload: dict) -> None:
        self.busy = False
        if payload.get("probe_url"):
            self.help_probe_url = payload["probe_url"]
        if result.ok:
            helpdesk.remember(result, payload)
            # The next request starts from an empty form; the pictures and videos are with VNLF now.
            form = self.stack.get_child_by_name("help")
            if form is not None:
                self.stack.remove(form)
            self.help_cleanup()
            self.help_form = None
            self.help_message, self.help_logs = "", ()
        page = result_page(result, payload, title=self.help_title(), done_label=self.help_done_label(),
                           on_done=self.leave_help, on_back=self._back_to_help,
                           on_retry=lambda: self._send_help(request), files=request.attachments)
        self._set_page("help-result", page)

    def help_cleanup(self) -> None:
        """Before the form goes (a new one, the window closes): its pictures and videos are removed."""

        if self.help_form is not None:
            self.help_form.cleanup()

    def _back_to_help(self) -> None:
        if self.stack.get_child_by_name("help") is not None:
            self.stack.set_visible_child_name("help")
        else:
            self.show_help(self.help_choices[0])

    def _save_probe(self) -> None:
        """Offline: hw-probe saves the profile to send from another device."""

        self.busy = True
        run = ProbeRun(False, on_finished=self._probe_saved)
        self._set_page("probe", run.page)
        run.start()

    def _probe_saved(self, result: hwprobe.ProbeResult) -> None:
        self.busy = False
        page = probe_result_page(result, on_back=self._back_to_help, on_retry=self._save_probe)
        self._set_page("probe-result", page)
