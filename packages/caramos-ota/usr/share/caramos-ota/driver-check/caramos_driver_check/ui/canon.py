"""Canon's printer driver: the terms Canon asks everyone who downloads it to accept, and the form for a network printer.

The terms are Canon's own words: English as on Canon Asia's download page, and in the Vietnamese catalog the text
Canon Vietnam shows on the same page (https://vn.canon/vi/support/0100459601, both read on 2026-11-11).
"""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from caramos_ota.i18n import _

from .. import canon_capt
from .common import label, link_button

ACCEPT = "accept"
CANCEL = "cancel"
CONTINUE = "continue"
FIRST_CHOICE = "LBP6300"   # the LBP6300dn, the office printer this form was made for


def canon_terms() -> list[str]:
    """The disclaimer of Canon's download page, paragraph by paragraph as Canon shows it."""

    return [
        _("All software, programs (including but not limited to drivers), files, documents, manuals, instructions "
          "or any other materials (collectively, “Content”) are made available on this site on an \"as is\" "
          "basis."),
        _("Canon Singapore Pte. Ltd., and its affiliate companies (“Canon”) make no guarantee of any kind with "
          "regard to the Content, expressly disclaims all warranties, expressed or implied (including, without "
          "limitation, implied warranties of merchantability, fitness for a particular purpose and "
          "non-infringement) and shall not be responsible for updating, correcting or supporting the Content."),
        _("Canon reserves all relevant title, ownership and intellectual property rights in the Content. You may "
          "download and use the Content solely for your personal, non-commercial use and at your own risks. Canon "
          "shall not be held liable for any damages whatsoever in connection with the Content, (including, without "
          "limitation, indirect, consequential, exemplary or incidental damages)."),
        _("You shall not distribute, assign, license, sell, rent, broadcast, transmit, publish or transfer the "
          "Content to any other party. You shall also not (and shall not let others) reproduce, modify, reformat, "
          "disassemble, decompile or otherwise reverse engineer or create derivative works from the Content, in "
          "whole or in part."),
        _("You agree not to send or bring the Content out of the country/region where you originally obtained it to "
          "other countries/regions without any required authorization of the applicable governments and/or in "
          "violation of any laws, restrictions and regulations."),
        _("By proceeding to downloading the Content, you agree to be bound by the above as well as all laws and "
          "regulations applicable to your download and use of the Content."),
    ]


def ask_terms(parent: Gtk.Widget, on_accept: Callable[[], None]) -> None:
    """Canon's terms, before anything is downloaded; on_accept runs only when the user agrees."""

    dialog = Adw.AlertDialog(
        heading=_("Canon's terms"),
        body=_("Driver Check downloads Canon's CAPT printer driver for Linux (version 2.71, about 120 MB) from "
               "Canon's website and installs it as Canon made it. Canon asks everyone who downloads it to accept "
               "these terms:"),
    )
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    terms = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    terms.set_margin_start(4)
    terms.set_margin_end(4)
    for paragraph in canon_terms():
        terms.append(label(paragraph, "dim-label", selectable=True))
    scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, min_content_height=220,
                                  max_content_height=320, propagate_natural_height=True)
    scroller.add_css_class("card")
    scroller.set_child(terms)
    box.append(scroller)
    box.append(label(_("The driver also comes with Canon's software licence agreement, kept on this computer as "
                       "%s.") % (canon_capt.STATE_DIR / "LICENSE-EN.txt"), "dim-label"))
    page = link_button(_("Canon's download page"), canon_capt.TERMS_PAGE)
    page.set_halign(Gtk.Align.START)
    box.append(page)
    dialog.set_extra_child(box)
    dialog.add_response(CANCEL, _("Cancel"))
    dialog.add_response(ACCEPT, _("Agree and download"))
    dialog.set_response_appearance(ACCEPT, Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response(CANCEL)
    dialog.set_close_response(CANCEL)
    dialog.connect("response", lambda _dialog, response: on_accept() if response == ACCEPT else None)
    dialog.present(parent)


def network_models() -> list[canon_capt.Model]:
    """Models with a network port first, the others after, each group by name."""

    models = sorted(canon_capt.MODELS.values(), key=lambda model: model.name)
    return [model for model in models if model.network] + [model for model in models if not model.network]


def ask_network_printer(parent: Gtk.Widget, on_continue: Callable[[str, str], None]) -> None:
    """The model and address of a Canon network printer: on_continue(model key, IPv4 address)."""

    dialog = Adw.AlertDialog(
        heading=_("Add a Canon printer on the network"),
        body=_("For Canon laser printers that need Canon's CAPT driver and are plugged into the office network, "
               "such as the LBP6300dn. Driver Check sets up Canon's driver and a print queue for the printer."),
    )
    models = network_models()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(label(_("Printer model"), "heading"))
    choice = Gtk.DropDown.new_from_strings([f"Canon {model.name}" for model in models])
    choice.set_selected(next((index for index, model in enumerate(models) if model.key == FIRST_CHOICE), 0))
    box.append(choice)
    box.append(label(_("The printer's address (IPv4)"), "heading"))
    entry = Gtk.Entry(placeholder_text="192.168.1.50", input_purpose=Gtk.InputPurpose.FREE_FORM,
                      activates_default=True)
    box.append(entry)
    hint = label(_("Ask whoever looks after the office network, or print the printer's network settings page "
                   "(see the printer's manual). A printer that gets a new address every day needs a fixed one."),
                 "dim-label")
    box.append(hint)
    dialog.set_extra_child(box)
    dialog.add_response(CANCEL, _("Cancel"))
    dialog.add_response(CONTINUE, _("Continue"))
    dialog.set_response_appearance(CONTINUE, Adw.ResponseAppearance.SUGGESTED)
    dialog.set_response_enabled(CONTINUE, False)
    dialog.set_default_response(CONTINUE)
    dialog.set_close_response(CANCEL)

    def address() -> str:
        try:
            return canon_capt.valid_address(entry.get_text())
        except ValueError:
            return ""

    entry.connect("changed", lambda _entry: dialog.set_response_enabled(CONTINUE, bool(address())))

    def respond(_dialog, response: str) -> None:
        if response == CONTINUE and address():
            on_continue(models[choice.get_selected()].key, address())

    dialog.connect("response", respond)
    dialog.present(parent)
