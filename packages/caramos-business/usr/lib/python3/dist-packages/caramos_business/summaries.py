"""One sentence per settings section, for the admin: what a scope uses ("Dùng thiết lập của công ty: …"), what a
machine has in effect and where from, and the department list. Apart from GTK so that it can be tested."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from . import health, presets, protocol, text
from .i18n import _, ngettext


def summary(section: str, value: Any) -> str:
    """What a section's value does, in a sentence; for null, that it is off."""

    if value is None:
        return _("Off.")
    if section == "wallpaper":
        parts = [_("a picture for every day") if value.get("default") else _("no picture for every day")]
        periods = len(value.get("periods") or [])
        if periods:
            parts.append(ngettext("%d special period", "%d special periods", periods) % periods)
        if value.get("lock"):
            parts.append(_("locked"))
        return text.sentence(parts)
    if section == "folders":
        return _("Desktop and Documents in %s.") % value.get("share", "")
    if section == "shares":
        names = ", ".join(share.get("name", "") for share in value)
        return _("Shared drives: %s.") % names if names else _("No shared drive yet.")
    if section == "browser":
        block = value.get("block") or []
        chosen, extra = presets.chosen(block)
        parts = []
        if value.get("homepage"):
            parts.append(_("home page %s") % value["homepage"])
        if value.get("bookmarks"):
            count = len(value["bookmarks"])
            parts.append(ngettext("%d bookmark", "%d bookmarks", count) % count)
        if block:
            what = ", ".join([presets.title(item).lower() for item in chosen] +
                             ([ngettext("%d other website", "%d other websites", len(extra)) % len(extra)]
                              if extra else []))
            hours = value.get("block_hours")
            parts.append(_("blocks %(what)s during working hours") % {"what": what} if hours else
                         _("blocks %(what)s all the time") % {"what": what})
        if value.get("safe_search"):
            parts.append(_("safe search"))
        return text.sentence(parts) if parts else _("On, with nothing set yet.")
    if section == "printers":
        names = ", ".join(printer.get("name", "") for printer in value)
        return _("Printers: %s.") % names if names else _("No printer yet.")
    if section == "power":
        parts = []
        if value.get("shutdown"):
            shutdown = value["shutdown"]
            parts.append(_("shuts down at %(time)s, %(days)s") % {"time": shutdown["time"],
                                                                "days": text.days_text(shutdown["days"])})
        if value.get("wake"):
            wake = value["wake"]
            parts.append(_("turns on at %(time)s, %(days)s") % {"time": wake["time"],
                                                                  "days": text.days_text(wake["days"])})
        return text.sentence(parts) if parts else _("On, with no time set.")
    if section == "apps":
        required, forbidden = len(value.get("required") or []), len(value.get("forbidden") or [])
        if not required and not forbidden:
            return _("No app chosen yet.")
        return _("%(required)s required, %(forbidden)s forbidden.") % {
            "required": ngettext("%d app", "%d apps", required) % required,
            "forbidden": ngettext("%d app", "%d apps", forbidden) % forbidden}
    if section == "usb":
        return {"allow": _("USB storage allowed."), "read-only": _("USB storage read-only."),
                "block": _("USB storage blocked.")}.get(value.get("storage"), "")
    if section == "screen_lock":
        minutes = value.get("idle_minutes", 0)
        return ngettext("Locks after %d minute.", "Locks after %d minutes.", minutes) % minutes
    if section == "firewall":
        return _("Firewall on.")
    if section == "inventory":
        return _("Machines send their inventory.")
    if section == "wifi":
        names = ", ".join(network.get("ssid", "") for network in value)
        return _("Networks: %s.") % names if names else _("No network yet.")
    if section == "shared":
        parts = [_("a guest session") if value.get("guest") else _("no guest session")]
        if value.get("freeze"):
            parts.append(_("frozen"))
        maintenance = value.get("maintenance")
        if value.get("freeze") and maintenance:
            parts.append(_("maintenance at %(time)s, %(days)s") % {"time": maintenance["time"],
                                                                  "days": text.days_text(maintenance["days"])})
        return text.sentence(parts)
    if section == "snapshots":
        schedule = {"daily": _("every day"), "weekly": _("every week"), "monthly": _("every month")}.get(
            value.get("schedule"), "")
        keep = value.get("keep", 0)
        parts = [_("a system snapshot %s") % schedule, ngettext("%d kept", "%d kept", keep) % keep]
        if value.get("before_update"):
            parts.append(_("one before each update"))
        return text.sentence(parts)
    return ""


def action_title(action: str) -> str:
    return {"sync": _("Sync now"), "inventory": _("Take inventory again"), "lock": _("Lock"),
            "message": _("Send a message"), "logout": _("Log out"), "restart": _("Restart"),
            "shutdown": _("Shut down"), "cancel": _("Cancel"), "update": _("Update"),
            "remote_help": _("Remote help"), "usb_unlock": _("Allow USB for a while")}.get(action, action)


def targets_text(targets: dict[str, Any], department_name: Callable[[str], str], machine_names: list[str]) -> str:
    if targets.get("all"):
        return _("all machines")
    if "departments" in targets:
        return _("department %s") % ", ".join(department_name(key) for key in targets["departments"])
    return ", ".join(machine_names)


def scope_text(scope: str, department_name: Callable[[str], str], machine_name: Callable[[str], str]) -> str:
    """A scope inside a sentence: "cả công ty", "phòng Kế toán", "máy kt-01"."""

    if scope == "company":
        return _("the whole company")
    kind, _sep, key = scope.partition(":")
    if kind == "department":
        return _("department %s") % department_name(key)
    return _("machine %s") % machine_name(key)


def audit_text(line: dict[str, Any], department_name: Callable[[str], str],
               machine_name: Callable[[str], str]) -> str:
    """An audit line in the reader's language, from its details; its summary when the details do not say enough
    (the summary is in the language of whoever wrote the line: the server writes in the system's)."""

    details = line.get("details") or {}
    action = line.get("action")
    try:
        if action == "register":
            if details.get("pairing") == "pending":
                return _("%(name)s asks to join the company (%(ip)s).") % {"name": details["name"], "ip": details["ip"]}
            return _("%(name)s joined the company (%(ip)s).") % {"name": details["name"], "ip": details["ip"]}
        if action == "options":
            return _("Each new machine now waits for approval.") if details["approve_machines"] else \
                _("New machines join without approval.")
        if action == "approve":
            return _("%s was approved and joined the company.") % details["name"]
        if action == "reject":
            return _("%s was turned away.") % details["name"]
        if action == "enroll-token":
            if details["token"] == "created":
                return _("An enrolment file was made: %(uses)d machines, until %(until)s.") % {
                    "uses": details["max_uses"], "until": text.vn_date(details["expires"][:10])}
            if details["token"] == "disabled":
                return _("An enrolment file was turned off after too many wrong requests.")
            return _("An enrolment file was withdrawn.")
        if action == "licences":
            return _("The list of bought licences was changed (%d entries).") % details["count"]
        if action == "ticket":
            ticket = details["ticket"]
            if details.get("note") == "public":
                return _("Ticket %s: a note for the employee.") % ticket
            if details.get("note") == "internal":
                return _("Ticket %s: an internal note.") % ticket
            if details.get("status"):
                titles = dict(zip(protocol.TICKET_STATES, (_("New"), _("Being handled"), _("Waiting for the employee"),
                                                          _("Finished"))))
                return _("Ticket %(ticket)s: %(status)s.") % {"ticket": ticket,
                                                               "status": titles.get(details["status"], details["status"])}
            if "assignee" in details:
                return _("Ticket %(ticket)s: handled by %(name)s.") % {"ticket": ticket,
                                                                       "name": details["assignee"] or "—"}
            return _("Ticket %s was changed.") % ticket
        if action == "pairing":
            if details.get("reason") == "wrong codes":
                return _("Adding machines stopped by itself after 20 wrong codes.")
            return _("Adding machines opened for 10 minutes.") if details["pairing"] == "open" else \
                _("Adding machines closed.")
        if action == "settings":
            changes = details["changes"]
            if details.get("reason") == "catch-up":
                return _("The settings were signed again as version %(new)d: a machine had a newer version (this "
                         "admin machine was restored from an older backup).") % {"new": details["serial"]}
            if not changes:
                return _("Settings saved without changes.")
            parts = []
            for scope, section in changes:
                if section == "departments":
                    parts.append(_("the departments"))
                elif section == "members":
                    parts.append(_("who is in which department"))
                else:
                    where = scope_text(scope, department_name, machine_name)
                    parts.append(f"{health.section_title(section)} ({where})")
            return _("Settings saved: %s.") % ", ".join(parts)
        if action == "command":
            title = action_title(details["command"])
            if details["command"] == "message" and details.get("args", {}).get("title"):
                title = f"{title} “{details['args']['title']}”"
            return f"{title}: {targets_text(details['targets'], department_name, details.get('names') or [])}."
        if action == "forget":
            return _("%s was taken out of the company.") % details["name"]
        if action == "asset":
            if details.get("event") == "handover":
                return _("A handover document was printed for %s.") % details["name"]
            if details.get("event") == "added":
                return _("The asset %s was added.") % details["name"]
            return _("The asset details of %s were changed.") % details["name"]
        if action == "help":
            if details["outcome"] == "answered":
                return _("A help request was answered with remote help.")
            return _("A help request from %s was closed.") % details["name"]
        if action == "backup":
            return _("A backup was made: %s.") % details["file"]
        if action == "restore":
            return _("This machine took over as the admin machine from a backup.")
        if action == "role":
            return _("This machine became the admin machine.")
    except (KeyError, TypeError, AttributeError, ValueError):
        pass
    return str(line.get("summary", ""))
