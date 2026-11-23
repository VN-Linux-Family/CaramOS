"""The licence report (PROTOCOL.md part 3, "Licence report"): each app the inventories list gets a class (free,
freeware, commercial, unknown), the register of bought licences is compared with the machines that have a matching
app, and the report says plainly what it is not: proof that every use is licensed.

An app is free when every licence id in its licence string is in FREE (OSI- or FSF-approved licences, in their Debian
short names and their SPDX forms). freeware and commercial come only from the App Center catalog, whose word wins over
a licence file."""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from . import APP_CENTER_CATALOG, protocol
from .i18n import _
from .store import read_json, write_json

REGISTER = "licences.json"
CLASSES = ("free", "freeware", "commercial", "unknown")
DISCLAIMER = ("Báo cáo này liệt kê phần mềm tìm thấy trên các máy; nó không xác nhận việc sử dụng đã đủ bản "
              "quyền.")

# Free licences: Debian short names (copyright-format 1.0) and SPDX ids, compared in lower case. Version suffixes
# with + (or-later) and the exceptions after "with" are handled by licence_ids().
FREE = {
    "gpl", "gpl-1", "gpl-2", "gpl-3", "gpl-1.0", "gpl-2.0", "gpl-3.0", "gpl-2.0-only", "gpl-2.0-or-later",
    "gpl-3.0-only", "gpl-3.0-or-later", "lgpl", "lgpl-2", "lgpl-2.1", "lgpl-3", "lgpl-2.0", "lgpl-3.0",
    "lgpl-2.0-only", "lgpl-2.0-or-later", "lgpl-2.1-only", "lgpl-2.1-or-later", "lgpl-3.0-only", "lgpl-3.0-or-later",
    "agpl", "agpl-3", "agpl-3.0", "agpl-3.0-only", "agpl-3.0-or-later", "mpl", "mpl-1.0", "mpl-1.1", "mpl-2.0",
    "apache", "apache-1.0", "apache-1.1", "apache-2.0", "bsd", "bsd-2-clause", "bsd-3-clause", "bsd-4-clause",
    "0bsd", "expat", "mit", "x11", "isc", "zlib", "libpng", "libpng-2.0", "artistic", "artistic-1.0",
    "artistic-2.0", "psf", "psf-2.0", "python", "python-2.0", "ofl", "ofl-1.0", "ofl-1.1", "sil-ofl-1.1",
    "cc0", "cc0-1.0", "unlicense", "public-domain", "publicdomain", "wtfpl", "bsl", "bsl-1.0", "boost", "epl",
    "epl-1.0", "epl-2.0", "cddl", "cddl-1.0", "cddl-1.1", "ftl", "openssl", "curl", "gfdl", "gfdl-1.2",
    "gfdl-1.3", "gfdl-1.2+", "gfdl-1.3+", "gfdl-1.3-only", "gfdl-1.3-or-later", "cc-by-3.0", "cc-by-4.0",
    "cc-by-sa-3.0", "cc-by-sa-4.0", "lppl", "lppl-1.3c", "qpl", "qpl-1.0", "ruby", "tcl", "vim", "ijg",
    "imagemagick", "freetype", "ncsa", "postgresql", "sleepycat", "w3c", "zpl-2.1", "eupl-1.1", "eupl-1.2",
    "gpl-2+", "gpl-3+", "lgpl-2+", "lgpl-2.1+", "lgpl-3+", "agpl-3+", "mpl-2.0+", "apache-2.0+",
}
NOT_IDS = {"and", "or", "with", "and/or"}


def licence_ids(expression: str) -> list[str]:
    """The licence ids of a licence string: "GPL-2+ or Artistic", "MPL-2.0 AND (MIT OR Apache-2.0)", "GPL-2 with
    OpenSSL exception" (the exception is not an id)."""

    text = (expression or "").strip().lower()
    # "with ... exception" as words; inside one name ("gpl-3+-with-bison-exception") it is part of that name.
    text = re.sub(r"(?<![\w-])with\s.*?(?=\sand\s|\sor\s|[),]|$)", " ", text)
    tokens = [token for token in re.split(r"[\s(),;|/]+", text) if token and token not in NOT_IDS]
    return tokens


# Debian's custom short names add an exception to a free licence, such as "GPL-2+-OpenSSL" (transmission) or
# "GPL-3+-with-Bison-exception": the licence before the exception decides.
EXCEPTION_WORDS = {"openssl", "exception", "with", "autoconf", "autoconf-exception", "bison", "classpath", "font", "gcc",
                   "libtool", "linking", "qt", "plugin", "special", "link"}


def free_id(token: str) -> bool:
    if token in FREE or token.rstrip("+") in FREE:
        return True
    parts = token.split("-")
    for cut in range(len(parts) - 1, 1, -1):  # the licence keeps at least its name and version: "gpl-2+"
        head, tail = "-".join(parts[:cut]), parts[cut:]
        if (head in FREE or head.rstrip("+") in FREE) and all(word in EXCEPTION_WORDS for word in tail):
            return True
    return False


def is_free(expression: str) -> bool:
    ids = licence_ids(expression)
    if not ids or expression.strip().lower() in ("unknown", "licenseref-proprietary"):
        return False
    return all(free_id(token) for token in ids)


def catalog_index(path: Path = APP_CENTER_CATALOG) -> dict[str, dict[str, Any]]:
    """The installed App Center catalog by every name an inventory may give an app under: its catalog id, its apt
    packages and its Flatpak id. Each value: {"id", "name", "class", "note": {vi, en}}."""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for app in data.get("apps", []) if isinstance(data, dict) else []:
        if not isinstance(app, dict) or not isinstance(app.get("id"), str):
            continue
        licence = app.get("licence") if isinstance(app.get("licence"), dict) else {}
        value = {"id": app["id"], "name": str(app.get("name") or app["id"]),
                 "class": licence.get("class") if licence.get("class") in CLASSES else "unknown",
                 "note": licence.get("note") if isinstance(licence.get("note"), dict) else {}}
        install = app.get("install") if isinstance(app.get("install"), dict) else {}
        names = [app["id"], install.get("flatpak"), install.get("recipe")]
        names += install.get("apt") if isinstance(install.get("apt"), list) else []
        for detect in (app.get("detect") or {}).values() if isinstance(app.get("detect"), dict) else []:
            if isinstance(detect, str):
                names.append(detect)
            elif isinstance(detect, list):
                names += [item for item in detect if isinstance(item, str)]
        for name in names:
            if isinstance(name, str) and name:
                index.setdefault(name, value)
    return index


def classify(app: dict[str, Any], index: dict[str, dict[str, Any]]) -> str:
    """An inventory app's class: the catalog's freeware or commercial first, then a free licence, else unknown."""

    known = index.get(app.get("package") or "") or index.get(app.get("id") or "")
    if known and known["class"] in ("freeware", "commercial"):
        return known["class"]
    if is_free(app.get("licence") or ""):
        return "free"
    if known and known["class"] == "free":
        return "free"
    return "unknown"


def read_register(state: Path) -> list[dict[str, Any]]:
    entries = read_json(state / REGISTER, [])
    return [entry for entry in entries if isinstance(entry, dict)] if isinstance(entries, list) else []


def write_register(state: Path, entries: list[dict[str, Any]]) -> None:
    write_json(state / REGISTER, entries)


def validate_register(value: Any) -> list[dict[str, Any]]:
    """The register as the window sends it: [{"id", "product", "seats", "expires", "invoice", "note", "match"}]."""

    if not isinstance(value, list) or len(value) > 500:
        raise protocol.ProtocolError(_("The licence list could not be read."))
    result = []
    for entry in value:
        if not isinstance(entry, dict):
            raise protocol.ProtocolError(_("The licence list could not be read."))
        entry_id = entry.get("id")
        product, seats, expires = entry.get("product"), entry.get("seats"), entry.get("expires", "")
        match = entry.get("match", [])
        ok = (isinstance(entry_id, str) and re.fullmatch(r"[a-z0-9-]{1,40}", entry_id) is not None
              and protocol._clean_text(product, 100, empty=False)  # noqa: SLF001 - the same rule
              and protocol._int(seats) and 0 <= seats <= 100000  # noqa: SLF001
              and protocol._clean_text(entry.get("invoice", ""), 100)  # noqa: SLF001
              and protocol._clean_text(entry.get("note", ""), 300, newlines=True)  # noqa: SLF001
              and isinstance(match, list) and len(match) <= 50
              and all(isinstance(item, str) and 0 < len(item) <= 100 for item in match))
        if not ok:
            raise protocol.ProtocolError(_("A licence needs a product name and a number of seats."))
        try:
            if expires:
                datetime.date.fromisoformat(expires)
        except ValueError as exc:
            raise protocol.ProtocolError(_("Write dates as day/month/year, such as 15/3/2024.")) from exc
        result.append({"id": entry_id, "product": product.strip(), "seats": seats, "expires": expires,
                       "invoice": entry.get("invoice", "").strip(), "note": entry.get("note", "").strip(),
                       "match": list(dict.fromkeys(match))})
    return result


def report(machines: dict[str, Any], inventories: dict[str, dict[str, Any] | None],
           index: dict[str, dict[str, Any]], register: list[dict[str, Any]]) -> dict[str, Any]:
    """The report: {"apps": [{"key", "name", "class", "licence", "origin", "machines": [ids]}], "totals": {class:
    number of apps}, "register": [entry + "used"], "without_inventory": [machine ids]}. Apps are grouped by package
    (or id); unknown and commercial come first, then by the number of machines."""

    apps: dict[str, dict[str, Any]] = {}
    without = []
    for machine_id in machines:
        inventory = inventories.get(machine_id)
        if not inventory:
            without.append(machine_id)
            continue
        for app in inventory.get("apps") or []:
            key = app.get("package") or app.get("id") or app.get("name")
            if not key:
                continue
            item = apps.setdefault(key, {"key": key, "name": app.get("name") or key, "class": classify(app, index),
                                         "licence": app.get("licence") or "", "origin": app.get("origin") or "",
                                         "ids": set(), "machines": []})
            item["ids"].update({app.get("id") or "", key})
            if machine_id not in item["machines"]:
                item["machines"].append(machine_id)
    order = {"unknown": 0, "commercial": 1, "freeware": 2, "free": 3}
    listed = sorted(apps.values(), key=lambda item: (order[item["class"]], -len(item["machines"]), item["name"]))
    totals = {name: sum(1 for item in listed if item["class"] == name) for name in CLASSES}
    checked = []
    for entry in register:
        wanted = set(entry.get("match") or [])
        users = set()
        for item in listed:
            if wanted & (item["ids"] | {item["key"]}):
                users.update(item["machines"])
        checked.append(dict(entry, used=len(users)))
    for item in listed:
        item["ids"] = sorted(item["ids"] - {""})
    return {"apps": listed, "totals": totals, "register": checked, "without_inventory": without}
