"""The App Center's catalogue, read for the admin window's Apps page: an app's id, name, summary and icon. The
policy's apps section names catalogue ids, which the agent installs and removes through App Center's helper."""

from __future__ import annotations

import json
import locale
from dataclasses import dataclass
from pathlib import Path

CATALOG = Path("/usr/share/caramos-app-center/catalog.json")
ICONS = Path("/usr/share/caramos-app-center/icons")


@dataclass(frozen=True)
class App:
    id: str
    name: str
    summary: str
    icon_path: Path | None
    icon_name: str


def language() -> str:
    lang = (locale.getlocale(locale.LC_MESSAGES)[0] or "") if hasattr(locale, "LC_MESSAGES") else ""
    return "vi" if lang.startswith("vi") else "en"


def load(path: Path = CATALOG, icons: Path = ICONS, lang: str | None = None) -> list[App]:
    """The catalogue's apps, in its order; [] when App Center is not installed."""

    lang = lang or language()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    apps = []
    for raw in data.get("apps", []) if isinstance(data, dict) else []:
        if not isinstance(raw, dict) or not isinstance(raw.get("id"), str):
            continue
        summary = raw.get("summary")
        text = summary.get(lang) or summary.get("en") or "" if isinstance(summary, dict) else str(summary or "")
        icon = raw.get("icon")
        apps.append(App(raw["id"], str(raw.get("name") or raw["id"]), text,
                        icons / icon if isinstance(icon, str) and icon and "/" not in icon else None,
                        str(raw.get("icon_name") or "")))
    return apps
