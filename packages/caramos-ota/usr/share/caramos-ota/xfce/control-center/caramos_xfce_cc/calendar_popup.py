"""The clock's calendar, with lunar dates (ticket H-1178), as the calendar of CaramOS Cinnamon shows them: today at
the top with its lunar date, then the month, where every day has its lunar day under it, smaller and lighter;
"1/10" on the first day of a lunar month; the 1st and the 15th of a lunar month in red. A card like the Control
Center's, above the clock.

The arrows, the mouse wheel and the Page Up/Down keys change the month; today at the top shows this month again."""

from __future__ import annotations

import datetime

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import lunar, month  # noqa: E402
from . import widgets as w  # noqa: E402
from .i18n import _  # noqa: E402
from .popupbase import EDGE, CardPopup  # noqa: E402
from .util import command_exists, spawn  # noqa: E402

TIME_SETTINGS = ("time-admin",)  # Date and Time of gnome-system-tools, in Linux Mint's Xfce edition
CARD_WIDTH = 296  # seven 38 px days in the 12 px sides of the Control Center's card


def local(date: datetime.date) -> GLib.DateTime:
    return GLib.DateTime.new_local(date.year, date.month, date.day, 0, 0, 0)


def centered(css_class: str) -> Gtk.Label:
    label = w.styled(Gtk.Label(), css_class)
    label.set_xalign(0.5)
    return label


def arrow(icon_name: str, name: str, on_click: object) -> Gtk.Button:
    button = w.styled(Gtk.Button(), "caramos-cc-cal-arrow")
    button.add(w.icon(icon_name, 14, "caramos-cc-arrow-icon"))
    button.set_can_focus(False)
    button.get_accessible().set_name(name)
    button.connect("clicked", lambda *_: on_click())
    return button


class DayCell(Gtk.Button):
    """A day of the grid: the day of the month, and its lunar day under it."""

    def __init__(self, on_click: object) -> None:
        super().__init__()
        w.styled(self, "caramos-cc-cal-day")
        self.set_can_focus(False)
        self.date = datetime.date.min
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.set_valign(Gtk.Align.CENTER)
        self.number = centered("caramos-cc-cal-day-number")
        self.lunar = centered("caramos-cc-cal-day-lunar")
        box.pack_start(self.number, False, False, 0)
        box.pack_start(self.lunar, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: on_click(self.date))

    def set_day(self, date: datetime.date, shown_month: int, today: datetime.date, language: str) -> None:
        self.date = date
        day = lunar.of(date)
        other = date.month != shown_month
        self.number.set_text(str(date.day))
        self.lunar.set_text(lunar.cell_text(day))
        w.set_class(self, "caramos-cc-cal-other-month", other)
        w.set_class(self, "caramos-cc-cal-today", date == today)
        w.set_class(self.number, "caramos-cc-cal-weekend", month.weekend(month.weekday(date)))
        w.set_class(self.lunar, "caramos-cc-cal-mark", lunar.marked(day) and not other)
        self.get_accessible().set_name(f"{local(date).format('%A %x')}, {lunar.lunar_text(date, language)}")


class CalendarPopup(CardPopup):
    def __init__(self, appearance: object) -> None:
        super().__init__(_("Calendar"), "caramos-cc-calendar")
        self.card.set_size_request(CARD_WIDTH, -1)
        self.appearance = appearance
        self.language = GLib.get_language_names()[0]
        self.first_day: int | None = None  # from the locale, the first time the calendar opens
        self.today = datetime.date.today()
        self.shown = (self.today.year, self.today.month)

        # Today: the day of the week, the date and the lunar date. A click shows this month again.
        self.home = w.styled(Gtk.Button(), "caramos-cc-cal-home")
        self.home.set_can_focus(False)
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.weekday = centered("caramos-cc-cal-weekday")
        self.date = centered("caramos-cc-cal-date")
        self.lunar = centered("caramos-cc-cal-lunar")
        # The English lunar date is longer than the month is wide: it takes two lines rather than widen the card.
        self.lunar.set_line_wrap(True)
        self.lunar.set_justify(Gtk.Justification.CENTER)
        self.lunar.set_max_width_chars(1)
        for child in (self.weekday, self.date, self.lunar):
            header.pack_start(child, False, False, 0)
        self.home.add(header)
        self.home.connect("clicked", lambda *_: self.show_month(self.today.year, self.today.month))
        self.card.pack_start(self.home, False, False, 0)

        # The month and the year, each between its arrows.
        navigation = Gtk.Box(spacing=8, homogeneous=True)
        self.month_label = centered("caramos-cc-cal-nav-label")
        self.year_label = centered("caramos-cc-cal-nav-label")
        for label, back, forward, months in (
                (self.month_label, _("Previous month"), _("Next month"), 1),
                (self.year_label, _("Previous year"), _("Next year"), 12)):
            part = Gtk.Box()
            part.pack_start(arrow("pan-start-symbolic", back, lambda m=months: self.turn(-m)), False, False, 0)
            part.pack_start(label, True, True, 0)
            part.pack_start(arrow("pan-end-symbolic", forward, lambda m=months: self.turn(m)), False, False, 0)
            navigation.pack_start(part, True, True, 0)
        self.card.pack_start(navigation, False, False, 0)

        # The days of the week, then six weeks.
        grid = Gtk.Grid(column_homogeneous=True)
        self.headings = [centered("caramos-cc-cal-heading") for _day in range(7)]
        for column, heading in enumerate(self.headings):
            grid.attach(heading, column, 0, 1, 1)
        self.cells = [DayCell(self._on_day) for _cell in range(7 * month.WEEKS)]
        for index, cell in enumerate(self.cells):
            grid.attach(cell, index % 7, 1 + index // 7, 1, 1)
        self.card.pack_start(grid, False, False, 0)

        # Date and time settings, where the system has them.
        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.footer.pack_start(w.styled(Gtk.Separator(), "caramos-cc-expand-separator"), False, False, 0)
        settings = w.styled(Gtk.Button(), "caramos-cc-cal-footer")
        settings.set_can_focus(False)
        settings.add(w.label(_("Date and Time Settings"), "caramos-cc-cal-footer-label", ellipsize=False))
        settings.connect("clicked", lambda *_: self._time_settings())
        self.footer.pack_start(settings, False, False, 0)
        self.card.pack_start(self.footer, False, False, 0)
        self.footer.show_all()
        self.footer.set_no_show_all(True)  # shown in show_popup only when the settings are there

        self.add_events(Gdk.EventMask.SCROLL_MASK)  # notches only, as the Control Center's button (indicator.py)
        self.connect("scroll-event", self._on_scroll)

    def left(self, area: Gdk.Rectangle, width: int) -> int:
        """Above the clock, centred on it, as Cinnamon opens its calendar; inside the screen."""

        middle = self._anchor[0] if self._anchor else area.x + area.width - EDGE - width // 2
        return max(area.x + EDGE, min(middle - width // 2, area.x + area.width - EDGE - width))

    def show_popup(self, anchor: tuple[int, int] | None, event_time: int = Gdk.CURRENT_TIME) -> None:
        """anchor: (middle, top) of the clock on the screen."""

        if self.first_day is None:
            self.first_day = month.locale_week_start(lunar.is_vietnamese(self.language))
            for column, heading in enumerate(self.headings):
                day = (self.first_day + column) % 7
                # 1 January 2023 was a Sunday.
                heading.set_text(local(datetime.date(2023, 1, 1 + day)).format("%a") or "")
                w.set_class(heading, "caramos-cc-cal-weekend", month.weekend(day))
        w.set_class(self, "dark", self.appearance.is_dark())
        self.show_today()
        self.show_month(self.today.year, self.today.month)
        self._anchor = anchor
        self.show_all()
        self.footer.set_visible(command_exists(TIME_SETTINGS[0]))
        self._place()

    def show_today(self) -> None:
        now = GLib.DateTime.new_now_local()
        self.today = datetime.date(now.get_year(), now.get_month(), now.get_day_of_month())
        self.weekday.set_text(now.format("%A") or "")
        if lunar.is_vietnamese(self.language):
            self.date.set_text(lunar.vietnamese_date(self.today))
        else:
            self.date.set_text(now.format("%-d %B %Y") or "")
        # The year's name on one line: "Bính Ngọ" is a name.
        name = lunar.year_name(lunar.of(self.today).year)
        self.lunar.set_text(lunar.lunar_text(self.today, self.language).replace(name, name.replace(" ", "\u00a0")))

    def show_month(self, year: int, month_number: int) -> None:
        self.shown = (year, month_number)
        first = local(datetime.date(year, month_number, 1))
        self.month_label.set_text(first.format("%B") or "")
        self.year_label.set_text(str(year))
        first_day = self.first_day if self.first_day is not None else month.MONDAY
        for cell, date in zip(self.cells, month.days(year, month_number, first_day)):
            cell.set_day(date, month_number, self.today, self.language)

    def turn(self, months: int) -> None:
        """Show the month `months` later, or earlier when negative (Gtk.Window has move())."""

        self.show_month(*month.shifted(*self.shown, months))

    def _on_day(self, date: datetime.date) -> None:
        """A day of the month before or after: show its month, as GTK's calendar does."""

        if (date.year, date.month) != self.shown:
            self.show_month(date.year, date.month)

    def _on_scroll(self, _widget: Gtk.Widget, event: Gdk.EventScroll) -> bool:
        months = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.LEFT: -1, Gdk.ScrollDirection.DOWN: 1,
                  Gdk.ScrollDirection.RIGHT: 1}.get(event.direction)
        if months:
            self.turn(months)
        return True

    def _on_key(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        months = {Gdk.KEY_Page_Up: -1, Gdk.KEY_Left: -1, Gdk.KEY_Page_Down: 1, Gdk.KEY_Right: 1}.get(event.keyval)
        if months:
            self.turn(months)
            return True
        if event.keyval == Gdk.KEY_Home:
            self.show_month(self.today.year, self.today.month)
            return True
        return super()._on_key(widget, event)

    def _time_settings(self) -> None:
        self.hide_popup()
        spawn(TIME_SETTINGS)
