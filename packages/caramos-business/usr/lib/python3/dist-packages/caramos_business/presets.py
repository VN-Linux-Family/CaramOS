"""The browser's block presets (PROTOCOL.md part 2, "browser"): curated lists of domains that the admin window offers
and expands into the policy's block list when it saves.

Zalo is never in a preset: Vietnamese companies work on it. Only the sites themselves are listed (each domain also
blocks www. and m.), not content networks that other sites embed. The window shows a preset as chosen when the block
list holds all of its domains, so changing a list here shows older policies with the missing ones unchosen."""

from __future__ import annotations

import encodings.idna
import re

from . import protocol
from .i18n import _

PRESETS: dict[str, tuple[str, ...]] = {
    "social": ("facebook.com", "fb.com", "messenger.com", "instagram.com", "threads.net", "tiktok.com",
               "twitter.com", "x.com", "reddit.com", "pinterest.com", "snapchat.com", "tumblr.com"),
    "video": ("youtube.com", "youtu.be", "netflix.com", "fptplay.vn", "vieon.vn", "tv360.vn", "galaxyplay.vn",
              "iq.com", "wetv.vip", "bilibili.tv", "twitch.tv", "dailymotion.com"),
    "games": ("roblox.com", "poki.com", "crazygames.com", "y8.com", "miniclip.com", "friv.com", "steampowered.com",
              "steamcommunity.com", "epicgames.com", "garena.vn", "zingplay.com", "gamevui.vn"),
    "shopping": ("shopee.vn", "lazada.vn", "tiki.vn", "sendo.vn", "temu.com", "aliexpress.com", "taobao.com",
                 "1688.com", "amazon.com", "ebay.com", "shein.com"),
}
ORDER = ("social", "video", "games", "shopping")
SECOND_LEVEL = {"com", "net", "org", "edu", "gov", "co", "ac", "info", "biz", "name", "pro", "int", "health"}

# The office hours most Vietnamese companies keep: 8:00 to 12:00 and 13:30 to 17:30, Monday to Saturday.
OFFICE_HOURS = {"days": [1, 2, 3, 4, 5, 6], "ranges": [["08:00", "12:00"], ["13:30", "17:30"]]}


def title(preset: str) -> str:
    return {"social": _("Social networks"), "video": _("Video"), "games": _("Games"),
            "shopping": _("Shopping")}[preset]


def chosen(block: list[str]) -> tuple[list[str], list[str]]:
    """The presets a block list holds whole, and the domains of no chosen preset (typed by the admin)."""

    domains = set(block)
    presets = [preset for preset in ORDER if set(PRESETS[preset]) <= domains]
    covered = {domain for preset in presets for domain in PRESETS[preset]}
    return presets, [domain for domain in block if domain not in covered]


def expand(presets: list[str], extra: list[str]) -> list[str]:
    """The block list: the presets' domains, then the extra ones, each once."""

    found: list[str] = []
    for preset in ORDER:
        if preset in presets:
            found.extend(PRESETS[preset])
    found.extend(extra)
    return list(dict.fromkeys(found))


def normalize_domain(text: str) -> str | None:
    """What an admin types ("https://www.Facebook.com/abc", "bóng đá.vn") as the domain to block, or None."""

    value = text.strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)
    value = re.split(r"[/?#:]", value, maxsplit=1)[0].strip(".")
    for prefix in ("www.", "m."):
        rest = value[len(prefix):].split(".")
        # "www.facebook.com" blocks facebook.com, but "www.com.vn" stays: com.vn would block every .com.vn site in
        # Chrome's URLBlocklist.
        if value.startswith(prefix) and len(rest) >= 2 and not (len(rest) == 2 and rest[0] in SECOND_LEVEL):
            value = ".".join(rest)
    try:
        value = ".".join(encodings.idna.ToASCII(label).decode("ascii") if any(ord(c) > 127 for c in label) else label
                         for label in value.split("."))
    except UnicodeError:
        return None
    return value if protocol.valid_domain(value) else None
