"""What an employee is told about the company's management of their machine (PROTOCOL.md part 2, "Transparency";
Personal Data Protection Law 91/2025/QH15, article 25): the features in effect for this machine, in plain words, and
what the company never sees. The notice after pairing and the window's page "Máy này do công ty quản lý" both use it.

Only what is in effect is listed: every feature is opt-in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AGENT_STATE, health, protocol, text
from .i18n import _, ngettext


def stored_settings(state: Path = AGENT_STATE) -> tuple[dict[str, Any], str]:
    """This machine's effective settings and the admin's name: from the agent's effective.json (the daemon writes it
    after each round, already merged for this machine), else worked out from the stored policy."""

    try:
        effective = json.loads((state / "effective.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        effective = None
    if isinstance(effective, dict) and isinstance(effective.get("settings"), dict):
        return effective["settings"], str(effective.get("admin_name") or "")
    try:
        policy = json.loads((state / "policy.json").read_text(encoding="utf-8"))
        info = json.loads((state / "admin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, ""
    if not isinstance(policy, dict) or not isinstance(info, dict):
        return {}, ""
    machine_id = info.get("machine_id")
    settings = protocol.effective_settings(policy, machine_id) if isinstance(machine_id, str) else \
        policy.get("settings") or {}
    return settings, str(policy.get("admin") or info.get("admin_name") or "")


def _browser(value: dict[str, Any]) -> str:
    parts = []
    if value.get("homepage"):
        parts.append(_("sets the home page"))
    if value.get("bookmarks"):
        parts.append(_("adds the company's bookmarks"))
    block = value.get("block") or []
    if block:
        hours = value.get("block_hours")
        if hours:
            parts.append(ngettext("blocks %(count)d website during working hours (%(days)s)",
                                  "blocks %(count)d websites during working hours (%(days)s)", len(block))
                         % {"count": len(block), "days": text.days_text(hours.get("days") or [])})
        else:
            parts.append(ngettext("blocks %d website", "blocks %d websites", len(block)) % len(block))
    if value.get("safe_search"):
        parts.append(_("turns on safe search"))
    if not parts:
        return _("The company manages the browsers' settings.")
    return _("The company %s.") % text.join_sentence(parts)


def _power(value: dict[str, Any]) -> str:
    parts = []
    shutdown = value.get("shutdown")
    if shutdown:
        parts.append(_("The machine shuts down at %(time)s (%(days)s); you are warned %(warn)d minutes before and "
                       "can postpone.") % {"time": shutdown["time"], "days": text.days_text(shutdown["days"]),
                                          "warn": shutdown.get("warn_minutes", 10)})
    wake = value.get("wake")
    if wake:
        parts.append(_("It turns on by itself at %(time)s (%(days)s).") % {"time": wake["time"],
                                                                          "days": text.days_text(wake["days"])})
    return " ".join(parts) or _("The company manages when the machine turns on and off.")


def _describe(section: str, value: Any) -> str:
    if section == "wallpaper":
        return _("The company sets the wallpaper; you cannot change it.") if value.get("lock") else \
            _("The company sets the wallpaper.")
    if section == "folders":
        return _("Your Desktop and Documents are kept on the company's server.")
    if section == "shares":
        names = ", ".join(share.get("name", "") for share in value)
        return _("The company's shared drives are in your file manager: %s.") % names if names else \
            _("The company manages the shared drives.")
    if section == "browser":
        return _browser(value)
    if section == "printers":
        names = ", ".join(printer.get("name", "") for printer in value)
        return _("The company's printers are set up: %s.") % names if names else _("The company manages the printers.")
    if section == "power":
        return _power(value)
    if section == "apps":
        return _("Some apps are installed for you, and some may not be installed.")
    if section == "usb":
        return {"allow": _("USB drives work as usual."),
                "read-only": _("USB drives can be read but not written to."),
                "block": _("USB drives do not open. Keyboards, mice, printers and signing tokens still work.")
                }.get(value.get("storage"), "")
    if section == "screen_lock":
        return ngettext("The screen locks after %d minute without use.",
                        "The screen locks after %d minutes without use.", value["idle_minutes"]) % value["idle_minutes"]
    if section == "firewall":
        return _("The firewall is on: other machines cannot connect to this one.")
    if section == "inventory":
        return _("The machine sends its hardware and its list of apps to the company's IT, for the asset list.")
    if section == "wifi":
        names = ", ".join(network.get("ssid", "") for network in value)
        return _("The machine connects to the company's Wi-Fi: %s.") % names
    if section == "shared":
        parts = []
        if value.get("guest"):
            parts.append(_("The login screen has a guest session, whose files are deleted when the guest logs out."))
        if value.get("freeze"):
            parts.append(_("The machine is frozen: every change on it is undone when it restarts. Keep your files on "
                           "the company's server or on a USB drive."))
            maintenance = value.get("maintenance")
            if maintenance:
                parts.append(_("It takes its updates at %(time)s, %(days)s.") % {
                    "time": maintenance["time"], "days": text.days_text(maintenance["days"])})
        return " ".join(parts)
    if section == "snapshots":
        return _("The machine keeps snapshots of its system, not of your files, to undo a broken update.")
    return ""


def managed_items(settings: dict[str, Any]) -> list[tuple[str, str]]:
    """[(title, sentence)] for every feature in effect, in a fixed order."""

    items = []
    for section in protocol.SECTIONS:
        value = settings.get(section)
        if value is None:
            continue
        sentence = _describe(section, value)
        if sentence:
            items.append((health.section_title(section), sentence))
    return items


def always_items() -> list[tuple[str, str]]:
    """What every paired machine does, whatever is turned on."""

    return [(_("Machine status"), _("The machine tells the company its name, who is logged in, its CaramOS version "
                                    "and a few numbers about its health: disk space, battery, waiting updates.")),
            (_("Actions from IT"), _("IT can lock the machine, send a message, restart or shut it down when needed; "
                                     "you are always told first. Remote help starts only if you accept."))]


def never_items() -> list[str]:
    """What the company cannot see (the same list everywhere)."""

    return [_("Your screen, unless you accept remote help"), _("What you type"), _("The websites you visit"),
            _("Your messages"), _("Your files outside the company's folders")]
