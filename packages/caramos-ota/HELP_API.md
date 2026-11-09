# VNLF help API for CaramOS

CaramOS sends help requests, bug reports and feedback to Vietnam Linux Family:

- **Driver Check** (`caramos-driver-check`), button "Nhờ giúp đỡ": the user's message, the link to their
  hardware profile on linux-hardware.org (an `hw-probe` upload) and the Driver Check results.
- **Feedback & Help** (`caramos-help`, "Góp ý & hỗ trợ"), opened from the question mark in the panel
  (applet `caramos-help@caramos`) and from the menu: help (`os`), a bug report (`bug`) or feedback
  (`feedback`), with the hardware profile and the Driver Check results when the user ticks them.

Both can attach up to five pictures or videos (screenshots, screen recordings, files): see
[Pictures and videos](#pictures-and-videos). When the **App Center** or the **Update Center** fails, its "Ask for
help" button opens Feedback & Help with a bug report started and what the app logged attached: see
[Logs](#logs). Live on vietnamlinuxfamily.net since 2026-10-14, like the
rest of this document unless it says otherwise.

Unless the user unticks it, VNLF may also publish a request for its community, after a moderator has
reviewed it: see [Sharing with the community](#sharing-with-the-community).

This document is the contract; the client is
`usr/share/caramos-ota/driver-check/caramos_driver_check/helpdesk.py`. VNLF implements it in
`apps/api/src/modules/caramos-help.ts` of vnlf-social (docs 51, sharing in docs 52).

## Request

```
POST https://vietnamlinuxfamily.net/api/caramos/help/v1
Content-Type: application/json; charset=utf-8
Accept: application/json
User-Agent: <client.app>/<CaramOS version>
```

```json
{
  "schema": 1,
  "type": "driver",
  "message": "Cài xong CaramOS thì Wi-Fi không thấy mạng nào…",
  "contact": "Zalo 0901 234 567",
  "public": true,
  "probe_url": "https://linux-hardware.org/?probe=1d2b3e4f5a",
  "report": {
    "areas": [{"key": "wifi", "level": "critical", "summary": "Broadcom BCM4360 802.11ac Wireless Network Adapter"}],
    "findings": [{"key": "wifi:broadcom:pci:14e4:43a0", "area": "wifi", "level": "critical",
                  "title": "Wi-Fi cần driver Broadcom", "detail": "…", "device": "Broadcom BCM4360 …",
                  "device_id": "PCI 14e4:43a0", "link": "https://linux-hardware.org/?id=pci:14e4-43a0-106b-0117",
                  "actions": [], "connect_help": true, "offline_media": true, "notes": []}],
    "connected": false, "live": false, "virtual": false, "kernel": "6.14.0-37-generic", "wired_port": true
  },
  "system": {"caramos": "1.0.22", "kernel": "6.14.0-37-generic", "live": false, "virtual": false, "language": "vi"},
  "client": {"app": "caramos-driver-check", "version": "1.0.22"},
  "upload_id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
  "attachments": ["0b2f6c1e-5d1a-4c8e-9a1f-2f4e8d7c6b5a", "7c9e6679-7425-40de-944b-e07fc1f90ae7"]
}
```

| Field | Required | Notes |
|---|---|---|
| `"schema"` | yes | `1`. A later, incompatible body gets a new number and a new URL (`/v2`). |
| `"type"` | no | `driver` (Driver Check), `os` (help), `bug`, `feedback`. CaramOS always sends it. Without it VNLF takes `driver` for `caramos-driver-check` and `os` for other apps. |
| `"message"` | yes | The user's text, 10 to 5000 characters after trimming. Vietnamese or English. |
| `"contact"` | no | Free text, at most 200 characters: email, phone/Zalo number or Facebook link. Can be empty. **Personal data: only moderators see it, never published.** |
| `"public"` | no | `true` when "Cho cộng đồng VNLF xem để cùng giúp" is ticked (it is by default), `false` when the user unticked it. CaramOS always sends it; missing or `null` means `false` (versions that never asked). Anything else is 422. See [Sharing with the community](#sharing-with-the-community). |
| `"probe_url"` | no | Link to the user's `hw-probe -all -upload`: only `https://linux-hardware.org/…` (or `www.`). Missing when the user unticked it, or hw-probe failed and the user chose to send without it. |
| `"report"` | no | The Driver Check report, the same JSON as `caramos-driver-check --json`, at most 64 KB. Missing when the user unticked it (and for feedback); the app leaves out a bigger one. It may carry `"logs"`: see [Logs](#logs). |
| `"system"` | yes | CaramOS version, kernel release, live USB session, virtual machine, UI language. |
| `"client"` | yes | `"app"`: `caramos-driver-check` or `caramos-help`; `"version"`: the CaramOS version. |
| `"upload_id"` | with `attachments` | The UUID the files were uploaded with (below). |
| `"attachments"` | no | Ids of the uploaded pictures and videos, at most 5, in the order the form shows them. Missing without files. |

Lengths are counted like JavaScript strings (UTF-16 code units: an emoji counts 2). The body stays well
under 128 KB; the server refuses anything bigger with 413.

## Responses

| Status | Body | What the app does |
|---|---|---|
| 201 | `{"id": "H-1042", "url": "https://vietnamlinuxfamily.net/caramos/help/<token>"}` | "Đã gửi yêu cầu": the id and a "Theo dõi yêu cầu" button for `url` (only `https://` links are shown). |
| 200 | the same `id` and `url` as the first time | The same message from the same address within 30 minutes (the app sending again after a timeout): no second ticket, not counted against the limit. Shown like 201. |
| 400, 413, 422 | `{"error": "invalid", "message": "…"}` | "VNLF không nhận yêu cầu này", offers to copy and post by hand. |
| 404, 405, 410, 501 | anything | "Dịch vụ chưa sẵn sàng", offers to copy and post by hand. |
| 429 | `{"error": "rate_limited", "retry_after": 600}` and a `Retry-After` header (seconds) | "Bạn vừa gửi nhiều yêu cầu, thử lại sau N phút". Production allows 5 requests an hour and 20 a day per address. |
| 503 | `{"error": "unavailable", "message": "…"}` | The limiter is down: "Máy chủ VNLF đang lỗi, thử lại sau", offers to copy and post by hand. |
| other 5xx, no connection, timeout (20 s) | anything | "Máy chủ VNLF đang lỗi" / "Không kết nối được", offers to copy and post by hand. |

## Logs

When an install or a removal fails in the App Center, or an update fails in the Update Center, the page that
says so has an "Ask for help" button ("Nhờ giúp đỡ"). It saves what the app logged and opens Feedback & Help:

```
caramos-help --type bug --message "App Center chưa cài được Zalo." --log ~/.cache/caramos-app-center/install-failure.log
caramos-help --type bug --message "Trung tâm cập nhật không cài được bản cập nhật “…”." --log ~/.cache/caramos-ota/update-failure.log
```

The form starts with that message (the user adds to it) and a ticked "Kèm nhật ký của ứng dụng (…)" box. The
App Center's log has, for each app that failed, its id and install method, the reason shown and the end of the
helper's output (apt-get, flatpak or the recipe). The Update Center's log has the output of `caramos-ota
--upgrade` and the end of the day's `/var/log/caramos-ota/*.log`.

Driver Check's page for a failed driver install has the same button. Its form starts with "Kiểm tra driver
chưa cài được <package>." (for example `printer-driver-captdriver`) and carries `driver-install.log`: the
package, the error code and what the helper printed.

Every request from Driver Check and Feedback & Help also carries `system.log` and, when Driver Check ran,
`driver-check.log`. When the computer has a USB printer or a print queue, it carries `printer.log` too
(`caramos_driver_check/printers.py`). CUPS logs to its own `error_log` rather than the journal, so without it a
printer that does not print leaves no trace. `printer.log` has:
- the printing packages and the Canon CAPT drivers installed;
- the USB printers with their IEEE 1284 id;
- the queues of USB printers, with their driver, state, CUPS's message and jobs. Network queues are only
  counted;
- this boot's lines of the automatic printer setup;
- the end of CUPS's `error_log`, without cupsd's chatter with its clients.

Serial numbers and document names (job titles) are taken out as well.

Before anything is shown or sent (`caramos_driver_check/logs.py`), each log loses e-mail and IP addresses, MAC
addresses, `password=`/`token=`-style values, the home folder, the computer's name and the user's login name,
and keeps its last 24 KB. The request carries them inside the report, so they need nothing new from VNLF:

```json
"report": {"areas": [], "findings": [], "logs": {"install-failure.log": "App Center 0.2.2: install failed at …"}}
```

`"logs"` maps a file name to its text. With the Driver Check results the logs are cut from their start until the
whole report fits its 64 KB. Like the rest of the report they are for VNLF's moderators only: never on the
request's page, never on the community page, and never in the text the app offers to post by hand.

## Pictures and videos

The form takes up to five pictures or videos ("Ảnh hoặc video"): a screenshot (Flameshot, with the user's
marks and blurs), a screen recording (Cinnamon's Ctrl+Shift+Alt+R, attached once it stops) or files the
user picks or drops on the form. The app prepares every file before anything is sent
(`caramos_driver_check/media.py`):

| | What VNLF receives |
|---|---|
| Pictures | `image/webp`, at most 2560×1600 pixels' worth (4.1 megapixels; the long side at most 4096). Lossless while that is 1 MB or less, so screenshots keep sharp text; else quality 82 (photos). An animated GIF up to 10 MB stays `image/gif`. EXIF, XMP and colour profiles are removed: phone photos store where they were taken. |
| Videos | `video/mp4`, H.264 + AAC, **at most 60 seconds** (the app refuses longer ones), at most 1920 pixels on the long side and 30 frames a second, about 2 Mbit/s: at most ~16 MB for a minute, a screen recording far less. Metadata (place, time, title) is removed. |

Each file goes straight to VNLF's storage, before the request, once the user pressed Send:

1. `POST /api/caramos/help/v1/attachments`

   ```json
   {"schema": 1, "upload_id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", "mime": "video/mp4", "size": 3145728, "duration": 42.5}
   ```

   `upload_id` is a UUID (v4) the app makes for the form; it ties the files to the request. `duration`
   (seconds) comes with videos only. The answer:

   ```json
   {"id": "7c9e6679-7425-40de-944b-e07fc1f90ae7", "upload_url": "https://…", "headers": {"content-type": "video/mp4"}, "expires_in": 600}
   ```

2. `PUT <upload_url>`: the file as the body, with the `headers` given and `Content-Length: <size>` (never
   chunked). The app uploads to `https://` links only.
3. `POST /api/caramos/help/v1/attachments/<id>/complete` with `{"upload_id": "…"}` →
   `200 {"id": "…", "status": "READY"}`.
4. The request (`POST /api/caramos/help/v1`) names the files: `"upload_id"` and `"attachments"`.

The request goes only when every file is READY. When the user tries again, files already uploaded are
not uploaded again (same `upload_id`, same ids).

| Status of steps 1 and 3 | Body | What the app does |
|---|---|---|
| 200, 201 | as above | The next step. |
| 400, 409, 413, 415, 422 | `{"error": "invalid", "message": "…"}` | "VNLF did not accept one of the files", and the choice: try again, send the request without the files, or go back. |
| 404, 405, 410, 501 | anything | "VNLF does not take pictures and videos from CaramOS yet", with the same choice. This is what the app shows until VNLF has these endpoints. |
| 429 | `{"error": "rate_limited", "retry_after": 3600}` and `Retry-After` | "You sent many pictures and videos today. Try again in N minutes", with the same choice. |
| 503, other 5xx, no connection | anything | "The VNLF server has a problem right now" / "Could not reach VNLF", with the same choice. |

A failing `PUT` (an expired link, a storage error) is handled like these: a 4xx like 400, a 5xx like 503.

### What the server checks

- `mime`: `image/webp`, `image/jpeg`, `image/png` or `image/gif` up to 10 MB; `video/mp4` or `video/webm`
  up to 50 MB with a `duration` under 61 seconds (players show at most 1:00; the app sends it cut to a
  tenth of a second).
- At most 5 files per `upload_id`, all from the address (IP hash) that uploaded the first one.
- Limits per address, suggested: 25 files and 150 MB a day, answered with 429 and `retry_after`; 503
  `unavailable` when the limiter is down, like the request.
- `complete`: the stored object has the size and type announced, else 400 (as for web feedback).
- The request: every id in `attachments` is READY, belongs to `upload_id` and the same address and is not
  attached to another request; else 422 and no ticket is created.
- The same request again within 30 minutes (the 200 answer): files of the same `upload_id` that are not
  attached yet are attached to the first ticket.
- Files not attached to a request within 24 hours are deleted.

### Where the files show

- Moderators see them with the ticket, like the attachments of web feedback (`feedback-admin-media`).
- The request's page `/caramos/help/<token>` says how many pictures and videos came with it but does not
  show them: anyone with the link can open the page. `GET /requests/<token>` may add
  `"attachments": {"images": 2, "videos": 1}`.
- A request shared with the community shows them on its public page, except any a moderator hides: see
  [Sharing with the community](#sharing-with-the-community).

### Built at VNLF

Web feedback has most of it (`apps/api/src/modules/feedback.ts`: `/api/v1/feedback/assets/presign` and
`…/complete`, the `feedback_assets` table, the private R2 bucket, `validateFeedbackMedia`, the upload
quota), and CaramOS tickets are `product_feedback` rows like web feedback:

1. `POST /api/caramos/help/v1/attachments` and `POST /api/caramos/help/v1/attachments/:id/complete` as
   above: guests by IP hash, `upload_id` in place of `clientSubmissionId`, no `kind` (the request's type
   is not known yet), refusals as `{error, message}` like the request.
2. `POST /api/caramos/help/v1` takes `upload_id` and `attachments` and links the files to the new ticket
   (`feedback_assets.feedback_id`, `position` = the order of the list) in the same transaction.
3. A job deleting files that were not attached within 24 hours.
4. Optional: the number of pictures and videos on the request's page and in the status `GET`.

## Sharing with the community

VNLF docs 52. **Production (since 2026-10-14)** takes and keeps `"public"`; there `public.url` stays `null` and
`answers` is missing. **Built on the VNLF dev stack (2026-10-14), not deployed yet:** the moderators' review,
the public pages under "Hỗ trợ CaramOS" (`https://vietnamlinuxfamily.net/caramos`), members' answers and the
sender's buttons on the tracking page.

**The form.** Both apps have a checkbox right above Send, **ticked by default**:

```
[x] Cho cộng đồng VNLF xem để cùng giúp
    Thông tin liên hệ không công khai.
```

**The request.** `"public"` (schema 1, same URL) is `true` when the box is ticked and `false` when the user
unticked it. Missing means `false`: versions that never asked the user leave it out. It must be a boolean (or
`null`); anything else is 422 with
`{"error": "invalid", "message": "Lựa chọn chia sẻ với cộng đồng không hợp lệ."}`. A repeated request (the
200 answer) keeps the choice of the first one.

**What happens next.**

- A VNLF moderator reviews every shared request before it is public: edits out personal data, may hide a
  picture or video, then publishes it on `https://vietnamlinuxfamily.net/caramos/H-1042`.
- Members answer and mark answers "Hữu ích". The sender (or a moderator) accepts the one that helped, which
  marks the request resolved.
- Never public: the contact, the IP address, the tracking token, the full report JSON and the original text.
- Public: the message (as reviewed), **the pictures and videos** (except any a moderator hides), the Driver
  Check findings and the hw-probe link (a moderator can hide either), the CaramOS version and kernel, VNLF's
  reply and the answers. The sender shows as "Người dùng CaramOS".

**`GET /api/caramos/help/v1/requests/<token>`** also returns:

```json
"public": {"consent": true, "url": "https://vietnamlinuxfamily.net/caramos/H-1042"},
"answers": [{"id": "01a1…", "content": "…", "votes": 3, "accepted": true, "author": "Dũng Lê", "createdAt": "2026-10-14T09:01:11.000Z"}]
```

- `url` is `null` until a moderator publishes the request, and again after it is taken down or the sender
  stops sharing.
- `answers` lists the answers on the public page, the accepted one first, then by votes; it is `[]` while the
  request is not published. `author` is the member's display name.

**Changing one's mind and accepting an answer.** The tracking page (`url` of the first answer) has the buttons.
The same calls work with the token from the tracking link and no account; errors use the usual
`{"error", "message"}` shape and an unknown token is 404.

```
POST /api/caramos/help/v1/requests/<token>/sharing   {"public": false}       → 200 {"consent": false, "url": null}
POST /api/caramos/help/v1/requests/<token>/sharing   {"public": true}        → 200 {"consent": true, "url": null | "<public url>"}
POST /api/caramos/help/v1/requests/<token>/accept    {"answer_id": "<id>"}   → 200 {"accepted": "<id>"}
POST /api/caramos/help/v1/requests/<token>/accept    {"answer_id": null}     → 200 {"accepted": null}
```

- Stopping takes the public page down at once. Sharing again puts the request back in the moderators' queue.
- `"public"` that is not a boolean is 422 "Lựa chọn chia sẻ với cộng đồng không hợp lệ.". An `answer_id` that
  is not an answer on the public page (or a request that is not published) is 422 "Không tìm thấy câu trả lời
  này trong yêu cầu.".

**In CaramOS.**

- The apps send `"public": true` or `false` with every request. The form says under the pictures and videos
  that they are published with a shared request after review, and the "Đã gửi yêu cầu" page says that VNLF
  publishes a shared request after review.
- The choice is kept with the request and follows `public.consent` of the status (below), so a change made on
  the tracking page shows too. The panel applet says "Đã chia sẻ với cộng đồng" under a shared request, and
  "Có N câu trả lời từ cộng đồng" in its place once there are answers. Clicking the request opens the tracking
  page, where the user accepts an answer.
- The window's list of requests links to `public.url` ("Trang cộng đồng").
- New answers from the community get a notification, like VNLF's reply.
- CaramOS does not call `…/sharing` or `…/accept`: the tracking page has the buttons, and the app does not keep
  the user's choice of answer.

## Following a request

`url` is the request's page on vietnamlinuxfamily.net: the message, the Driver Check results and VNLF's
answer ("Phản hồi từ VNLF"), without the contact. Anyone with the link can read it, so the app shows it
only to the user. The app keeps each accepted request in `~/.local/state/caramos-help/requests.json`
(`id`, `url`, `type`, `sent`, the start of the message, `public`: shared with the community; mode 0600,
newest first, at most 20).

**The status.** `caramos-help --refresh` asks `GET /api/caramos/help/v1/requests/<token>` (the token is the
last part of `url`, `User-Agent: caramos-help/<CaramOS version>`) how the requests are doing:

- When: the panel applet runs it a minute after login and then every 30 minutes, only while the file lists
  requests. The window's list asks too when it opens.
- Which: every request except closed ones, removed ones and ones resolved more than 30 days ago. A user
  with five open requests makes ten small `GET`s an hour.
- What CaramOS reads: `status` (`OPEN`, `IN_REVIEW`, `RESOLVED`, `CLOSED`); `reply`, where any text means
  VNLF answered; `public.consent` and `public.url`; how many `answers` there are; `resolvedAt` (else
  `updatedAt`) of a resolved or closed request. 404 with `{"error": "not_found"}` means VNLF removed the
  request. Any other answer changes nothing.
- What it keeps with the request: `status` (`GONE` once VNLF removed it), `replied`, `public`,
  `public_url`, `answers` (the number) and `finished`.

**What the user sees.**

- The panel applet lists the last five requests with VNLF's word on each: "VNLF đã trả lời", "VNLF đang
  xem", "Đã xử lý", "Đã đóng" or "Không còn trên VNLF", then "Có N câu trả lời từ cộng đồng" or "Đã chia sẻ
  với cộng đồng". Finished ones are lighter and leave the menu 30 days after VNLF finished them. When some
  are not shown, "Xem tất cả N yêu cầu" opens the whole list in the Feedback & Help window
  (`caramos-help --requests`); the form's header bar has it too ("Yêu cầu của bạn").
- A new answer gets a notification ("VNLF đã trả lời yêu cầu H-1042 của bạn", "Cộng đồng đã trả lời yêu
  cầu H-1042 của bạn") whose button opens the request's page; answers to several requests get one
  notification that opens the list.

## Testing the apps against a test server

```
CARAMOS_DRIVER_CHECK_HELP_URL=http://127.0.0.1:8765/help caramos-help
CARAMOS_DRIVER_CHECK_HELP_URL=http://127.0.0.1:8765/help caramos-driver-check
```

The test server answers `…/help/attachments` and `…/help/requests/<token>` too and may give
`http://127.0.0.1…` upload links (plain http is allowed to this computer only). `caramos-help --refresh`
and the window's list ask the same server when started with that variable. `tests/test_driver_check_help.py`
runs the client against a local server for every answer above.
