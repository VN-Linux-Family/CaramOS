"""The results page: what works, what needs doing (with one-click fixes) and every piece of hardware."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from gi.repository import Adw, Gtk

from caramos_ota.i18n import _, ngettext

from .. import actions
from ..analysis import (
    ABSENT,
    CRITICAL,
    INFO,
    INSTALL,
    PROBLEM_LEVELS,
    REPORT,
    TIP,
    WARNING,
    Action,
    Finding,
    Report,
    kernel_version,
    area_label,
)
from .common import (
    AREA_ICONS,
    badge,
    bottom_bar,
    clamp,
    header,
    icon,
    icon_bubble,
    label,
    level_text,
    link_button,
    notes_box,
    page_box,
    pill,
    scrolled,
    section,
)


class ResultsView(Gtk.Box):
    def __init__(self, report: Report, *, came_online: bool, on_action: Callable[[Action, Finding | None], None],
                 on_install_all: Callable[[list[Action]], None], on_report: Callable[[], None],
                 on_recheck: Callable[[], None], on_close: Callable[[], None],
                 on_canon_network: Callable[[], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.report = report
        self.on_action = on_action
        self.on_canon_network = on_canon_network

        view = Adw.ToolbarView()
        bar = header(_("Driver Check"))
        recheck = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text=_("Check again"))
        recheck.connect("clicked", lambda _button: on_recheck())
        bar.pack_end(recheck)
        view.add_top_bar(bar)

        content = page_box(30)
        content.append(self._hero(report))
        if came_online and any(finding.area in {"wifi", "ethernet"} for finding in report.problems) \
                and not report.needs_connection:
            content.append(self._online_banner())
        if report.needs_connection:
            content.append(self._connect_card(report))

        number = 0
        problems = [finding for finding in report.findings if finding.level in PROBLEM_LEVELS]
        suggestions = [finding for finding in report.findings if finding.level in (INFO, TIP)]
        if problems:
            number += 1
            content.append(self._section(number, _("To do"),
                                         ngettext("%d thing", "%d things", len(problems)) % len(problems),
                                         [self._finding_card(finding) for finding in problems]))
        if suggestions:
            number += 1
            content.append(self._section(number, _("Suggestions"), _("Optional"),
                                         [self._finding_card(finding) for finding in suggestions]))
        number += 1
        content.append(self._hardware(number, report))

        page = scrolled(clamp(content))
        page.add_css_class("welcome")
        view.set_content(page)
        view.set_vexpand(True)
        self.append(view)

        report_button = pill(_("Ask for help"), on_report, icon_name="help-browser-symbolic")
        installs = list(report.installs)
        if installs:
            main = pill(ngettext("Install %d driver", "Install %d drivers", len(installs)) % len(installs),
                        lambda: on_install_all(installs), suggested=True)
        else:
            main = pill(_("Close"), on_close, suggested=True)
        self.append(bottom_bar(self._summary(report), self._detail(report), [report_button, main]))

    # Parts -----------------------------------------------------------------------------------

    @staticmethod
    def _summary(report: Report) -> str:
        if report.needs_connection:
            return _("This computer cannot get online yet")
        if report.problems:
            count = len(report.problems)
            return ngettext("%d thing needs your attention", "%d things need your attention", count) % count
        return _("All drivers are installed")

    @staticmethod
    def _detail(report: Report) -> str:
        parts = [_("Checked at %s") % datetime.now().strftime("%H:%M")]
        if report.kernel:
            parts.append("Linux %s" % kernel_version(report.kernel))
        return " · ".join(parts)

    def _hero(self, report: Report) -> Gtk.Widget:
        hero = Gtk.Box(spacing=22)
        hero.add_css_class("hero-card")
        if report.needs_connection:
            status, icon_name = "critical", "network-offline-symbolic"
            title = _("This computer cannot get online yet")
            subtitle = _("Without a working network card it cannot download drivers. Get online one of the "
                         "ways below, then install the driver.")
        elif report.problems:
            status, icon_name = "warning", "dialog-warning-symbolic"
            count = len(report.problems)
            title = ngettext("%d thing needs your attention", "%d things need your attention", count) % count
            subtitle = _("Everything else works. Follow the steps below to finish setting up this computer.")
        elif report.live:
            status, icon_name = "ok", "emblem-ok-symbolic"
            title = _("This computer works well with CaramOS")
            subtitle = _("CaramOS found drivers for all the hardware it checked. You can install it with confidence.")
        else:
            status, icon_name = "ok", "emblem-ok-symbolic"
            title = _("All drivers are installed")
            subtitle = _("CaramOS found drivers for all the hardware it checked.")
        hero.add_css_class(f"hero-{status}")
        hero.append(icon_bubble(icon_name, 40, "status-bubble", f"status-{status}"))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        texts.append(label(title, "hero-title"))
        texts.append(label(subtitle, "hero-subtitle"))
        found = [area for area in report.areas if area.level != ABSENT]
        points = [("object-select-symbolic",
                   _("Checked %(kinds)d kinds of hardware; this computer has %(found)d of them.")
                   % {"kinds": len(report.areas), "found": len(found)})]
        if report.live:
            points.append(("dialog-information-symbolic",
                           _("You are trying CaramOS from the USB stick. After installing CaramOS, Driver Check "
                             "runs again at the first login.")))
        if report.virtual:
            points.append(("dialog-information-symbolic", _("This is a virtual machine: graphics are not checked.")))
        for icon_name, text in points:
            row = Gtk.Box(spacing=8)
            row.add_css_class("hero-point")
            row.set_margin_top(4)
            image = Gtk.Image.new_from_icon_name(icon_name)
            image.set_valign(Gtk.Align.START)
            image.set_margin_top(2)
            row.append(image)
            row.append(label(text, "dim-label"))
            texts.append(row)
        hero.append(texts)
        return hero

    @staticmethod
    def _online_banner() -> Gtk.Widget:
        banner = Gtk.Box(spacing=12)
        banner.add_css_class("callout")
        banner.add_css_class("callout-ok")
        banner.append(icon("network-transmit-receive-symbolic", 20))
        banner.append(label(_("You are online now. Follow the steps below."), "callout-text"))
        return banner

    @staticmethod
    def _connect_card(report: Report) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.add_css_class("connect-card")
        card.append(label(_("How to get online"), "card-title"))
        steps = []
        if report.wired_port:
            steps.append(("network-wired-symbolic", _("Plug a network cable into the computer's network port.")))
        steps.append(("phone-symbolic", _(
            "Use your phone's internet: connect the phone with a USB cable and turn on USB tethering. "
            "Android: Settings → Hotspot & tethering → USB tethering. iPhone: turn on Personal Hotspot, "
            "connect the cable and tap Trust.")))
        if report.offline_media:
            steps.append(("drive-removable-media-symbolic", _(
                "No way to get online? Plug in the CaramOS USB stick: the Broadcom driver installs from it.")))
        for number, (icon_name, text) in enumerate(steps, 1):
            row = Gtk.Box(spacing=12)
            step = label(str(number), "step-number", wrap=False, xalign=0.5)
            step.set_valign(Gtk.Align.START)
            row.append(step)
            image = icon(icon_name, 20, "step-icon")
            image.set_valign(Gtk.Align.START)
            row.append(image)
            text_label = label(text)
            text_label.set_hexpand(True)
            row.append(text_label)
            card.append(row)
        waiting = Gtk.Box(spacing=10)
        waiting.add_css_class("waiting-row")
        spinner = Gtk.Spinner(spinning=True)
        waiting.append(spinner)
        waiting.append(label(_("Waiting for a connection… This page updates by itself."), "dim-label"))
        card.append(waiting)
        return card

    @staticmethod
    def _section(number: int, title: str, hint: str, cards: list[Gtk.Widget]) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(section(number, title, hint))
        for card in cards:
            box.append(card)
        return box

    def _finding_card(self, finding: Finding) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("issue-card")
        card.add_css_class(f"level-{finding.level}")

        top = Gtk.Box(spacing=14)
        top.append(icon_bubble(AREA_ICONS.get(finding.area, AREA_ICONS["other"]), 22, "area-bubble",
                               f"bubble-{finding.level}"))
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
        titles.append(label(finding.title, "issue-title"))
        if finding.device:
            titles.append(label("%s · %s" % (finding.device, finding.device_id), "dim-label", "issue-device",
                                selectable=True))
        top.append(titles)
        top.append(badge(_level_badge(finding.level), f"badge-{finding.level}"))
        card.append(top)

        card.append(label(finding.detail, "issue-detail"))
        if finding.notes:
            card.append(notes_box(finding.notes))

        buttons = Gtk.Box(spacing=10)
        buttons.add_css_class("issue-actions")
        first = True
        for action in finding.actions:
            if action.kind not in (INSTALL, REPORT) and not actions.available(action.kind):
                continue
            button = pill(action.label, lambda action=action: self.on_action(action, finding), suggested=first)
            if action.kind == INSTALL and not self.report.can_install(finding):
                button.set_sensitive(False)
                button.set_tooltip_text(_("Needs internet"))
            buttons.append(button)
            first = False
        if finding.link:
            buttons.append(link_button(_("This device on linux-hardware.org"), finding.link))
        if buttons.get_first_child() is not None:
            card.append(buttons)
        return card

    def _hardware(self, number: int, report: Report) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        box.append(section(number, _("Hardware on this computer"),
                           "Linux %s" % kernel_version(report.kernel) if report.kernel else ""))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True, max_children_per_line=3,
                           min_children_per_line=1, column_spacing=14, row_spacing=14)
        for area in report.areas:
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            tile.add_css_class("hw-tile")
            tile.add_css_class(f"level-{area.level}")
            row = Gtk.Box(spacing=10)
            row.append(icon(AREA_ICONS.get(area.key, AREA_ICONS["other"]), 20, "tile-icon"))
            name = label(area_label(area.key), "tile-title", wrap=False)
            name.set_hexpand(True)
            row.append(name)
            row.append(badge(level_text(area.level), f"badge-{area.level}"))
            tile.append(row)
            summary = label(area.summary, "dim-label", "tile-summary", lines=3)
            summary.set_max_width_chars(30)
            tile.append(summary)
            flow.append(tile)
        box.append(flow)
        if self.on_canon_network is not None:
            box.append(self._canon_network_row(self.on_canon_network))
        return box

    @staticmethod
    def _canon_network_row(on_add: Callable[[], None]) -> Gtk.Widget:
        """Network printers are not hardware of this computer, so the check cannot find them: the user adds one."""

        row = Gtk.Box(spacing=12)
        row.set_margin_top(4)
        row.append(icon("printer-symbolic", 20, "tile-icon"))
        text = label(_("A Canon laser printer on the office network that needs Canon's driver, such as the "
                       "LBP6300dn?"), "dim-label")
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        row.append(text)
        button = Gtk.Button(label=_("Add printer…"), valign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        button.connect("clicked", lambda _button: on_add())
        row.append(button)
        return row


def _level_badge(level: str) -> str:
    return {
        CRITICAL: _("Urgent"),
        WARNING: _("Should do"),
        INFO: _("For your information"),
        TIP: _("Tip"),
    }.get(level, level_text(level))
