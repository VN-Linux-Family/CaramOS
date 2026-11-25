"""Requests to VNLF: help, bug reports and feedback, with the hardware profile and Driver Check results.

The request goes as JSON to the VNLF help API (HELP_API.md in the caramos-ota source describes it). The
hardware profile is an hw-probe upload on linux-hardware.org: the request carries its link, not the logs.
Pictures and videos (prepared by media.py) are uploaded first, each straight to VNLF's storage through a
link the API gives; the request then names them. When the API cannot be reached, the window offers the
same text to copy and paste on the VNLF site. Unless the user says no ("public"), VNLF may also show the
request to its community once a moderator has reviewed it. Requests VNLF accepted are kept in the user's
state directory, so the panel applet can open them again; refresh() asks VNLF how they are doing.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import platform
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from caramos_ota.i18n import ui_language

HELP_URL = "https://vietnamlinuxfamily.net/api/caramos/help/v1"
TIMEOUT_SECONDS = 20
UPLOAD_TIMEOUT_SECONDS = 60   # without any progress, on a slow connection
SCHEMA = 1
KINDS = ("driver", "os", "bug", "feedback")   # "type" of the request
MIN_MESSAGE = 10
MAX_MESSAGE = 5000
MAX_CONTACT = 200
MAX_REPORT = 64 * 1024
RELEASE_FILE = Path("/etc/caramos-release")
HISTORY_LIMIT = 20


def help_url() -> str:
    """The API address; CARAMOS_DRIVER_CHECK_HELP_URL overrides it for testing."""

    return os.environ.get("CARAMOS_DRIVER_CHECK_HELP_URL") or HELP_URL


def caramos_version(path: Path | None = None) -> str:
    try:
        for line in (path or RELEASE_FILE).read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION="):
                return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return ""


def length(text: str) -> int:
    """Length as the API counts it: JavaScript string length, in UTF-16 code units."""

    return len(text.encode("utf-16-le")) // 2


def _cut(text: str, limit: int) -> str:
    """text shortened to at most limit UTF-16 code units, never in the middle of a character."""

    used = 0
    for index, char in enumerate(text):
        used += 2 if ord(char) > 0xFFFF else 1
        if used > limit:
            return text[:index]
    return text


def message_problem(message: str) -> str:
    """Why the message cannot be sent yet: "short", "long" or ""."""

    size = length(message.strip())
    if size < MIN_MESSAGE:
        return "short"
    if size > MAX_MESSAGE:
        return "long"
    return ""


def _json_length(value: Any) -> int:
    return length(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


# Logs whose start matters most (the computer's model, devices and settings): cut last, and from their end.
CUT_LAST = ("computer.log",)


def _with_logs(report: dict[str, Any] | None, logs: Mapping[str, str]) -> dict[str, Any]:
    """report with "logs", cut until the whole report fits the API's limit: the beginnings of the longest logs first,
    where their oldest lines are, and the end of computer.log only when the others are gone."""

    texts = dict(logs)
    base = dict(report or {})
    while texts and _json_length({**base, "logs": texts}) > MAX_REPORT:
        others = [key for key in texts if key not in CUT_LAST and len(texts[key]) >= 512]
        name = max(others or texts, key=lambda key: len(texts[key]))
        if len(texts[name]) < 512:
            texts.pop(name)
            continue
        if name in CUT_LAST:
            kept = texts[name][:len(texts[name]) * 3 // 4]
            texts[name] = (kept[:kept.rfind("\n")] if "\n" in kept else kept) + "\n…"
            continue
        cut = texts[name][len(texts[name]) // 4:]
        texts[name] = "…" + cut[cut.find("\n") + 1:] if "\n" in cut else "…" + cut
    return {**base, "logs": texts} if texts else base


def build_request(message: str, contact: str = "", probe_url: str = "", report: dict[str, Any] | None = None,
                  *, kind: str = "driver", app: str = "caramos-driver-check", kernel: str = "", live: bool = False,
                  virtual: bool = False, upload_id: str = "", attachments: Sequence[str] = (),
                  public: bool = False, logs: Mapping[str, str] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "type": kind,
        "message": _cut(message.strip(), MAX_MESSAGE),
        "contact": _cut(contact.strip(), MAX_CONTACT),
        # Whether VNLF may show the request to its community: always sent, as VNLF takes a missing one as no.
        "public": public,
        "system": {
            "caramos": caramos_version(),
            "kernel": kernel or platform.release(),
            "live": live,
            "virtual": virtual,
            "language": ui_language(),
        },
        "client": {"app": app, "version": caramos_version()},
    }
    if probe_url:
        payload["probe_url"] = probe_url
    if logs:
        # What the app logged goes with the report, which only VNLF's moderators see (HELP_API.md, "Logs").
        report = _with_logs(report, logs)
    # A report over the API's limit would get the whole request refused; the rest is worth more.
    if report is not None and length(json.dumps(report, ensure_ascii=False, separators=(",", ":"))) <= MAX_REPORT:
        payload["report"] = report
    if attachments:
        # The uploaded pictures and videos, in the order the form shows them.
        payload["upload_id"] = upload_id
        payload["attachments"] = list(attachments)
    return payload


def as_text(payload: dict[str, Any], files: Sequence[str] = (), *, with_logs: bool = False) -> str:
    """The request as a post to paste by hand when the API cannot be reached; files: the attached ones.

    with_logs adds the logs, for the form's preview: a post is public, the logs are for VNLF's team only.
    """

    lines = [payload["message"], ""]
    if payload.get("probe_url"):
        lines.append(f"Hardware (hw-probe): {payload['probe_url']}")
    system = payload.get("system", {})
    lines.append("CaramOS %s · Linux %s" % (system.get("caramos") or "?", system.get("kernel") or "?"))
    for finding in (payload.get("report") or {}).get("findings", []):
        if finding.get("level") in ("critical", "warning", "info"):
            device = f" ({finding['device']} {finding.get('device_id', '')})" if finding.get("device") else ""
            lines.append(f"- {finding['title']}{device}")
    if files:
        lines.append("Pictures and videos: " + ", ".join(files))
    if payload.get("contact"):
        lines += ["", payload["contact"]]
    logs = (payload.get("report") or {}).get("logs") or {}
    if with_logs and logs:
        lines += ["", "Logs (only the VNLF team sees them):"]
        for name, text in logs.items():
            lines += [f"--- {name} ---", text]
    return "\n".join(lines).strip() + "\n"


@dataclass(frozen=True)
class SendResult:
    ok: bool
    error: str = ""        # "", "network", "unavailable", "rate-limited", "rejected", "server"
    request_id: str = ""
    url: str = ""          # where the user can follow the request, when the API gives one
    retry_after: int = 0


def send(payload: dict[str, Any], url: str | None = None, timeout: float = TIMEOUT_SECONDS) -> SendResult:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    client = payload.get("client", {})
    request = urllib.request.Request(url or help_url(), data=body, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": f"{client.get('app') or 'caramos-driver-check'}/{client.get('version') or 'dev'}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = _json(response.read())
            return SendResult(True, request_id=str(answer.get("id") or ""), url=_https(answer.get("url")))
    except urllib.error.HTTPError as exc:
        error, retry = _failure(exc)
        return SendResult(False, error, retry_after=retry)
    except (urllib.error.URLError, OSError, TimeoutError):
        return SendResult(False, "network")


def _failure(exc: urllib.error.HTTPError) -> tuple[str, int]:
    """What an error answer of the API means, and for 429 how many seconds to wait."""

    answer = _json(exc.read() if exc.fp is not None else b"")
    if exc.code in (404, 405, 410, 501):
        return "unavailable", 0   # the API (or this part of it) is not there (yet)
    if exc.code == 429:
        try:
            return "rate-limited", int(answer.get("retry_after") or exc.headers.get("Retry-After") or 0)
        except (TypeError, ValueError):
            return "rate-limited", 0
    if 400 <= exc.code < 500:
        return "rejected", 0
    return "server", 0


# Pictures and videos -------------------------------------------------------------------------


@dataclass(frozen=True)
class UploadResult:
    ok: bool
    error: str = ""        # like SendResult
    attachment_id: str = ""
    retry_after: int = 0


def attachments_url(base: str | None = None) -> str:
    return (base or help_url()).rstrip("/") + "/attachments"


def upload(upload_id: str, path: Path, mime: str, *, duration: float = 0.0, app: str = "caramos-help",
           base: str | None = None, on_progress: Callable[[int], None] | None = None,
           timeout: float = TIMEOUT_SECONDS) -> UploadResult:
    """One prepared file: asks for an upload link, sends the file there, tells the API it is complete.

    upload_id ties the files to the request that names them; on_progress gets the bytes sent so far.
    """

    size = path.stat().st_size
    body: dict[str, Any] = {"schema": SCHEMA, "upload_id": upload_id, "mime": mime, "size": size}
    if mime.startswith("video/"):
        body["duration"] = math.floor(duration * 10) / 10   # 60.96 s is 60.9: players show 1:00
    headers = {"User-Agent": f"{app}/{caramos_version() or 'dev'}"}
    try:
        answer = _post(attachments_url(base), body, headers, timeout)
        attachment_id = str(answer.get("id") or "")
        target = answer.get("upload_url")
        if not attachment_id or not _upload_target(target):
            return UploadResult(False, "server")
        # The link is signed for these headers.
        given = answer.get("headers")
        storage = {str(name): str(value) for name, value in given.items()} if isinstance(given, dict) else {}
        if not any(name.lower() == "content-type" for name in storage):
            storage["Content-Type"] = mime
        try:
            _put(target, path, size, storage, on_progress)
        except urllib.error.HTTPError as exc:
            # The storage refused (an expired link): not an answer of the API.
            return UploadResult(False, "rejected" if 400 <= exc.code < 500 else "server")
        _post(f"{attachments_url(base)}/{urllib.parse.quote(attachment_id, safe='')}/complete",
              {"upload_id": upload_id}, headers, timeout)
    except urllib.error.HTTPError as exc:
        error, retry = _failure(exc)
        return UploadResult(False, error, retry_after=retry)
    except (urllib.error.URLError, OSError, TimeoutError):
        return UploadResult(False, "network")
    return UploadResult(True, attachment_id=attachment_id)


def _post(url: str, body: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json; charset=utf-8", "Accept": "application/json", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return _json(response.read())


def _upload_target(url: Any) -> bool:
    """Files go to https links only; plain http only to this computer (a test server)."""

    if not isinstance(url, str):
        return False
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"))


class _Reading:
    """The file as the request body, telling how much was sent."""

    def __init__(self, stream, on_progress: Callable[[int], None] | None) -> None:
        self.stream = stream
        self.on_progress = on_progress
        self.sent = 0

    def read(self, amount: int = -1) -> bytes:
        data = self.stream.read(amount)
        self.sent += len(data)
        if self.on_progress is not None and data:
            self.on_progress(self.sent)
        return data


def _put(url: str, path: Path, size: int, headers: dict[str, str],
         on_progress: Callable[[int], None] | None) -> None:
    with path.open("rb") as stream:
        # The storage link is signed for this length: no chunked upload.
        request = urllib.request.Request(url, data=_Reading(stream, on_progress), method="PUT",
                                         headers={**headers, "Content-Length": str(size)})
        with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT_SECONDS) as response:
            response.read()


def _json(data: bytes) -> dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _https(value: Any) -> str:
    """Only a https link from the API is shown (and opened) to the user."""

    return value if isinstance(value, str) and value.startswith("https://") else ""


# Requests VNLF accepted ----------------------------------------------------------------------


def history_path(environ: dict[str, str] | None = None) -> Path:
    """~/.local/state/caramos-help/requests.json; the panel applet reads the same file."""

    env = os.environ if environ is None else environ
    state = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".local/state")
    return Path(state) / "caramos-help" / "requests.json"


def sent_requests(path: Path | None = None) -> list[dict[str, Any]]:
    """Newest first: id, url (the request's page on VNLF), type, sent (ISO time), the start of the message and
    public (the user shared it with the VNLF community). Once VNLF was asked about it (refresh): status,
    replied, finished (when VNLF resolved or closed it), public_url (its page for the community) and answers
    (how many the community gave there)."""

    try:
        data = json.loads((path or history_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("requests") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict) and _https(item.get("url"))]


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """The windows and the applet's refresh change the file: one at a time (a lock on its directory)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    handle = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        os.close(handle)


def _write(path: Path, items: list[dict[str, Any]]) -> None:
    # The page link is the only key to the request: the file stays private to the user (mkstemp: 0600).
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".requests-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"requests": items[:HISTORY_LIMIT]}, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def remember(result: SendResult, payload: dict[str, Any], path: Path | None = None,
             now: datetime | None = None) -> bool:
    """Keeps an accepted request; False when it could not be written (the request was sent anyway)."""

    if not result.ok or not result.url:
        return False
    path = path or history_path()
    try:
        with _locked(path):
            kept = sent_requests(path)
            # VNLF answers a request sent twice with the first one's page, and keeps the first one's choice of
            # sharing and its status: the request is kept once, as the newest.
            first = next((item for item in kept if item.get("url") == result.url), None)
            entry = {
                **(first or {}),
                "id": result.request_id,
                "url": result.url,
                "type": payload.get("type") or "driver",
                "sent": (now or datetime.now().astimezone()).isoformat(timespec="seconds"),
                "message": _cut(" ".join(str(payload.get("message", "")).split()), 120),
                "public": (first if first is not None else payload).get("public") is True,
            }
            _write(path, [entry] + [item for item in kept if item.get("url") != result.url])
    except OSError:
        return False
    return True


# How VNLF is doing on them -------------------------------------------------------------------

OPEN, IN_REVIEW, RESOLVED, CLOSED = "OPEN", "IN_REVIEW", "RESOLVED", "CLOSED"
GONE = "GONE"   # not VNLF's: the request is not on VNLF any more (a moderator removed it)
FINISHED = (RESOLVED, CLOSED, GONE)
KEEP_FINISHED_DAYS = 30   # the panel menu lists a finished request this long; the window always does
STATUS_TIMEOUT_SECONDS = 15


@dataclass(frozen=True)
class Status:
    ok: bool
    error: str = ""          # like SendResult
    status: str = ""         # OPEN, IN_REVIEW, RESOLVED, CLOSED or GONE
    replied: bool = False    # VNLF answered on the request's page
    public: bool | None = None   # shared with the community: the user can change it on the page
    public_url: str = ""     # the request's page for the community, once a moderator published it
    finished: str = ""       # when VNLF resolved or closed it (ISO time)
    answers: int = 0         # the community's answers on that page


def status_url(page: str, base: str | None = None) -> str:
    """Where the API tells how a request is doing, from the link of its page (…/caramos/help/<token>).

    VNLF's tokens are 43 characters; it refuses ones under 20 or over 64, so those are not asked about.
    """

    match = re.fullmatch(r"https://[^/?#]+/caramos/help/([A-Za-z0-9_-]{20,64})", page or "")
    return f"{(base or help_url()).rstrip('/')}/requests/{match.group(1)}" if match else ""


def fetch_status(page: str, base: str | None = None, timeout: float = STATUS_TIMEOUT_SECONDS) -> Status:
    url = status_url(page, base)
    if not url:
        return Status(False, "rejected")
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": f"caramos-help/{caramos_version() or 'dev'}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            answer = _json(response.read())
    except urllib.error.HTTPError as exc:
        # VNLF's own "not found" for this request, not an address without the API.
        if exc.code == 404 and _json(exc.read() if exc.fp is not None else b"").get("error") == "not_found":
            return Status(True, status=GONE)
        return Status(False, _failure(exc)[0])
    except (urllib.error.URLError, OSError, TimeoutError):
        return Status(False, "network")
    status = answer.get("status")
    if status not in (OPEN, IN_REVIEW, RESOLVED, CLOSED):
        return Status(False, "server")
    shared = answer.get("public") if isinstance(answer.get("public"), dict) else {}
    reply = answer.get("reply")
    finished = (answer.get("resolvedAt") or answer.get("updatedAt")) if status in (RESOLVED, CLOSED) else ""
    answers = answer.get("answers") if isinstance(answer.get("answers"), list) else []   # [] until published
    return Status(True, status=status, replied=isinstance(reply, str) and bool(reply.strip()),
                  public=shared["consent"] if isinstance(shared.get("consent"), bool) else None,
                  public_url=_https(shared.get("url")), finished=finished if isinstance(finished, str) else "",
                  answers=sum(isinstance(item, dict) for item in answers))


def _time(value: Any) -> datetime | None:
    try:
        when = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo is not None else None


def listed(item: dict[str, Any], now: datetime | None = None) -> bool:
    """False for a request VNLF finished more than KEEP_FINISHED_DAYS ago: the panel menu leaves it out."""

    if item.get("status") not in FINISHED:
        return True
    when = _time(item.get("finished"))
    return when is None or (now or datetime.now().astimezone()) - when <= timedelta(days=KEEP_FINISHED_DAYS)


def _to_check(item: dict[str, Any], now: datetime) -> bool:
    # A closed or removed request does not change any more; a resolved one may still get an answer.
    return item.get("status") not in (CLOSED, GONE) and listed(item, now)


@dataclass(frozen=True)
class News:
    """A request VNLF or its community answered since the last refresh."""

    request: dict[str, Any]
    reply: bool = False      # VNLF answered
    answers: int = 0         # new answers from the community


@dataclass(frozen=True)
class Refresh:
    checked: int = 0         # requests VNLF was asked about
    failed: int = 0          # of those, the ones it could not tell about (no connection, an error)
    news: tuple[News, ...] = ()


def refresh(path: Path | None = None, *, base: str | None = None, now: datetime | None = None,
            fetch: Callable[[str, str | None], Status] = fetch_status) -> Refresh:
    """Asks VNLF how the unfinished requests are doing and keeps what it says with them; news: the requests
    VNLF or the community answered since the last time."""

    path = path or history_path()
    now = now or datetime.now().astimezone()
    pages = [item["url"] for item in sent_requests(path) if _to_check(item, now)]
    if not pages:
        return Refresh()
    statuses = {page: fetch(page, base) for page in pages}   # not locked while waiting for VNLF
    news = []
    try:
        with _locked(path):
            items = sent_requests(path)   # with the requests sent in the meantime
            for item in items:
                status = statuses.get(item["url"])
                if status is None or not status.ok:
                    continue
                reply = status.replied and item.get("replied") is not True
                had = item.get("answers") if isinstance(item.get("answers"), int) else 0
                item["status"] = status.status
                item["replied"] = status.replied
                if status.public is not None:
                    item["public"] = status.public
                if status.public_url:
                    item["public_url"] = status.public_url
                else:
                    item.pop("public_url", None)
                if status.answers:
                    item["answers"] = status.answers
                else:
                    item.pop("answers", None)
                if status.status == GONE:
                    item.setdefault("finished", now.isoformat(timespec="seconds"))
                elif status.finished:
                    item["finished"] = status.finished
                else:
                    item.pop("finished", None)
                if reply or status.answers > had:
                    news.append(News(item, reply, max(0, status.answers - had)))
            _write(path, items)
    except OSError:
        pass   # shown as it was; the next refresh asks again
    return Refresh(len(statuses), sum(not status.ok for status in statuses.values()), tuple(news))
