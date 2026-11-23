# CaramOS Doanh nghiệp: protocol and layout (version 1)

This is the contract between the parts of the `caramos-business` package. The Python parts (admin server, root
helper, window) and the Rust agent (`agent/`) both follow it. Tests on both sides check the shared examples in
`tests/protocol-examples/`.

## Roles

- **Admin** (máy quản lý): runs the window (`caramos-business`) and `caramos-business-server.service`.
  - It keeps an Ed25519 key pair and the company's policy, and signs the policy.
  - It serves the policy and its files over HTTP on the LAN, and records what the employee machines report.
- **Employee** (máy nhân viên): runs `caramos-business-agent.service` (Rust, as root) and, in each user's session,
  `caramos-business-agent session` (Rust, as that user, from /etc/xdg/autostart).
  - The service fetches the signed policy, checks the signature against the admin key pinned at pairing, downloads
    the files, and reports back.
  - The session part applies the policy for its user: the wallpaper, and Desktop and Documents on the server.

The role is in `/etc/caramos-business/role`: `admin` or `employee`, one word and a newline. With no such file the
machine has no role yet.

## Network

| Port | Use |
|---|---|
| UDP 47021 | discovery |
| TCP 47022 | HTTP, served by the admin |

Plain HTTP on the company LAN. Integrity comes from the signature, not from TLS. Nothing secret travels except the
check-in token: each employee machine gets its own, at pairing.

### Discovery (UDP 47021)

- The employee broadcasts the datagram `CARAMOS-BUSINESS/1 DISCOVER` to 255.255.255.255:47021, from UDP port 47021
  when that port is free (from 0.2), else from any port. The answer comes from the admin's own address, which a
  firewall's connection tracking does not match to the broadcast, so a firewall on the employee must let UDP 47021 in:
  the helper allows it when the machine becomes an employee machine with ufw on, and the agent's `firewall` section
  allows it (part 2).
- The admin answers to the sender's address and port with `CARAMOS-BUSINESS/1 HERE <json>`, where `<json>` is
  `{"name": "<admin hostname>", "port": 47022, "fingerprint": "<first 16 hex digits of sha256(public key)>", "pairing": true|false}`.
- Datagrams are ASCII plus UTF-8 JSON, at most 2048 bytes. Anything else is ignored.
- An agent whose admin stopped answering at the stored address uses discovery to find the admin with the pinned
  fingerprint at its new address. That is the only discovery it does after pairing.

### HTTP (TCP 47022)

All bodies are UTF-8 JSON, except files. Request bodies are at most 64 KiB. Paths start with `/caramos-business/v1`.

| Method and path | Who | Body / answer |
|---|---|---|
| `GET /hello` | anyone | `{"name", "fingerprint", "pairing"}`, as in discovery |
| `GET /key` | anyone | `{"name": "<hostname>", "key": "<base64 of the raw 32-byte Ed25519 public key>"}` |
| `POST /register` | an employee, only while pairing is open | `{"code": "123456", "machine": MACHINE}` → `{"machine_id": "<uuid4>", "token": "<base64 of 32 random bytes>"}`. 403 when pairing is closed or the code is wrong, 400 when the body is invalid. |
| `GET /policy` | anyone | `{"policy": "<the policy as a JSON text>", "signature": "<base64 of the Ed25519 signature of the UTF-8 bytes of that text>"}` |
| `GET /files/<sha256>` | anyone | the file's bytes; 404 if the policy lists no such file |
| `POST /checkin` | a paired employee | `{"machine_id", "token", "machine": MACHINE, "policy_serial": N or null, "users": [USER_STATUS…]}` → `{"ok": true}`. 403 when the id or token is wrong. |

- The policy is sent as a string inside the JSON so that the agent checks the signature over the exact bytes it
  then parses. No canonical JSON is needed.
- `MACHINE` is `{"name": "<hostname>", "ip": "<IPv4>", "mac": "aa:bb:cc:dd:ee:ff", "edition": "cinnamon"|"xfce"|"other", "version": "<CaramOS version or empty>"}`.
  - `ip` and `mac` are the address and card of the route toward the admin.
  - `edition` is `cinnamon` when `/usr/bin/cinnamon` exists, `xfce` when `/usr/bin/xfce4-session` exists, else
    `other`.
  - `version` is `VERSION` from `/etc/caramos-release` (`VERSION="1.4.0"`).
- `USER_STATUS` is `{"user": "<login name>", "wallpaper": "applied"|"failed"|"off", "folders": "server"|"local"|"failed"|"off", "detail": "<short text, at most 200 characters>", "time": "<ISO 8601>"}`.

### Pairing code

`pairing_code(key) = int.from_bytes(sha256(b"caramos-business-pairing:" + key)[:4], "big") % 1_000_000`, written as 6
digits with leading zeros.

The admin window shows it while pairing is open. On the employee:
1. The user picks the admin in the list and types the code.
2. The employee downloads `/key` and checks the code against it. A wrong code means a wrong admin: stop.
3. It sends `/register` with the same code, which the admin checks again.
4. It pins the key.

Pairing is open for 10 minutes after the admin opens it in the window, or until it is closed.

## Policy (format 1)

```json
{
  "format": 1,
  "serial": 7,
  "issued": "2026-11-21T09:00:00+07:00",
  "admin": "may-quan-ly",
  "files": {"<sha256>": {"size": 812345, "type": "jpg"}},
  "wallpaper": {
    "default": "<sha256 or null>",
    "periods": [{"name": "Tết", "from": "01-25", "to": "02-05", "image": "<sha256>"}],
    "lock": true
  },
  "folders": {
    "share": "smb://server/share/%u",
    "tidy": true
  }
}
```

### Fields

- `serial` grows with every change the admin saves. An agent ignores a policy whose serial is lower than the one it
  has, which protects against replay.
- `files` lists every file the policy uses.
  - `type` is one of `jpg`, `png`, `webp`.
  - `size` is at most 20 MiB.
  - The agent downloads a file, checks its size and sha256, and only then uses it.
- `wallpaper` is null (the company sets no wallpaper) or an object:
  - `periods` hold dates as `MM-DD`, both ends included. A period whose `from` is after its `to` crosses New Year
    (`12-25` to `01-05`).
  - On a day in several periods, the first one listed wins. On a day in none, `default` applies; if `default` is
    null, the user's own wallpaper stays.
  - `lock`: when true, a user who changes the wallpaper gets the company's back within 30 seconds.
- `folders` is null (files stay on the machine) or an object:
  - `share` is an `smb://` URL. `%u` stands for the login name.
  - The user's Desktop and Documents become the folders `Desktop` and `Documents` in it.
  - `tidy`: files left in the local Desktop and Documents move to `Chưa sắp xếp/YYYY-MM-DD` on the server once it
    is reachable. They are moved, never deleted: the local copy goes only after the server copy is complete and of
    the same size.
- Unknown top-level keys are ignored, so that later formats can add things. An unknown `format` stops the agent
  from applying anything.

### Validation (both sides)

- `serial` is an int ≥ 1.
- `sha256` is 64 lowercase hex digits.
- `MM-DD` is a real day (`02-29` allowed).
- `name` is at most 60 characters.
- At most 50 periods.
- Every image the wallpaper uses (`default`, each period's `image`) is listed in `files`.
- `share` starts with `smb://`, has a host, and has no `..`, no `@` (no credentials in URLs) and no spaces.

## Files

### Admin

| Path | Content |
|---|---|
| `/etc/caramos-business/admin-key.pem` | Ed25519 private key, PKCS#8 PEM, 0600 root |
| `/var/lib/caramos-business/admin/policy.json` | the policy being edited (the window writes it through the helper) |
| `/var/lib/caramos-business/admin/signed-policy.json` | what `GET /policy` answers; written by the helper when the policy is saved |
| `/var/lib/caramos-business/admin/files/<sha256>` | the images |
| `/var/lib/caramos-business/admin/machines.json` | `{"<machine_id>": {"token_sha256", "machine": MACHINE, "paired", "last_seen", "policy_serial", "users": [...]}}`; the server writes it |
| `/run/caramos-business/pairing-until` | Unix time until which pairing is open; the helper writes it |

### Employee

| Path | Content |
|---|---|
| `/etc/caramos-business/agent.json` | `{"admin_url": "http://IP:47022", "admin_name", "admin_key": "<base64>", "fingerprint", "machine_id", "token"}`, 0600 root; the helper writes it at pairing |
| `/var/lib/caramos-business/agent/policy.json` | the last policy that passed the checks, as JSON (the policy object itself), 0644 |
| `/var/lib/caramos-business/agent/files/<sha256>.<type>` | the downloaded files, 0644 |
| `$XDG_RUNTIME_DIR/caramos-business/status.json` | the session part's `USER_STATUS` for its user; the service reads `/run/user/*/caramos-business/status.json` for check-ins |

## Agent timing

- **Service:** fetch at start, then every 5 minutes. On failure, retry every minute up to 5 minutes. Check in after
  each fetch.
- **Session part:** at login, then every 30 seconds, and at once when policy.json changes:
  - work out today's wallpaper and apply it if it is not the current one (with `lock`) or if the wanted image
    changed;
  - set up the folders once per login, and again when `folders` changes.

## Applying

### Wallpaper

- **Cinnamon:** `gsettings set org.cinnamon.desktop.background picture-uri 'file:///var/lib/caramos-business/agent/files/<sha>.<type>'` and `picture-options 'zoom'`.
- **Xfce:** `xfconf-query -c xfce4-desktop` sets every `/backdrop/screen*/monitor*/workspace*/last-image` that
  exists, with `image-style` 5 (zoomed). This is the same as caramos-daily-wallpaper.

### Folders

1. `gio mount` the share root (`smb://host/share`). If it needs a password, start `caramos-business --connect URL` in
   the session; it asks and can remember the password in the keyring. Wait at most 2 minutes.
2. The FUSE path is `$XDG_RUNTIME_DIR/gvfs/smb-share:server=<host>,share=<share>/<rest>`, with `%u` replaced by the
   login name. Make `Desktop` and `Documents` there.
3. Link `~/.local/share/caramos-business/server/Desktop` and `…/Documents` to them, and point `XDG_DESKTOP_DIR` and
   `XDG_DOCUMENTS_DIR` in `~/.config/user-dirs.dirs` at the links: `$HOME/.local/share/caramos-business/server/Desktop`.
   - Not at the FUSE paths themselves: GIO maps any path under the FUSE root back to its smb:// URI, and xfdesktop
     4.18 cannot list a desktop through GVfs's smb backend ("Can't do asynchronous next_files() on a file enumerator
     created synchronously", an empty desktop). Through a link outside the root, GIO sees a local folder, which the
     kernel's FUSE mount serves.
   - A link is made as a temporary link renamed into place. A real file or folder where a link goes is left as it
     is, and the folders report `failed`.
   - The values before the first change are kept in `~/.config/caramos-business/user-dirs.local`. Then restart the
     desktop-icons program: `nemo-desktop` on Cinnamon, `xfdesktop` on Xfce.
4. When the share cannot be reached:
   - put the local folders back into user-dirs.dirs (the links may stay, dangling);
   - notify the user (notify-send): "Không kết nối được thư mục trên máy chủ: tạm lưu trên máy này.";
   - report `folders: "local"`.
5. `tidy`: move files from the local Desktop and Documents into `Chưa sắp xếp/YYYY-MM-DD` on the share.
   - Launchers (`*.desktop`) are not moved, they are copied, so the desktop icons stay on both sides.
   - Copy into a temporary name, compare sizes, rename into place, then remove the local file.
   - Folders are moved file by file the same way.

## Agent

How the Rust agent reads what the sections above leave open (more in `agent/README.md`).

- **Retries:** after a failed fetch, the service retries every minute, 5 times at most, then fetches every 5 minutes
  again until one works.
- **Check-in:** after every fetch in which the admin's address served a policy signed with the pinned key, also when
  that policy was refused (invalid, or a lower serial) or a file failed; never to an address that did not prove to
  be the admin's, since the check-in names the users (from 0.2 it carries no token: see part 2). `mac` is empty when
  the card of the route has none (a VPN).
  `users[].user` is the account that owns `/run/user/<uid>`, not the name written in the file.
- **Discovery:** when the stored address gives no policy signed with the pinned key (no answer, an HTTP error, an
  answer that is not the protocol's, another key). Answers count from private and link-local IPv4 addresses with a
  port above 1024. The agent moves only to an address that serves a policy signed with the pinned key, and then
  writes its `admin_url` into agent.json, keeping the other fields and 0600.
- **Limits:** a policy text over 1 MiB is refused.
- **Role:** the session part applies the stored policy only while `/etc/caramos-business/role` says `employee`.
- **Wallpaper:** the session part remembers the image it set last, across logins; without `lock`, a user's own
  wallpaper then stays until the company's image changes.
- **Folders:**
  - GVfs case-folds server and share names: the FUSE path has them in lower case, escaped as GVfs escapes mount
    names (`%2C` for a comma); a mount under another spelling (a user or domain added) is found in
    `$XDG_RUNTIME_DIR/gvfs`.
  - An unreachable share is tried again every 5 minutes, quietly: the notification comes once per login (in English
    when the session's language is not Vietnamese, as on CaramOS Xfce). A password window closed without a mount is
    not opened again in that login. A mount that goes away during the session counts as unreachable.
  - Applied means user-dirs.dirs naming the links and the links pointing at the current FUSE paths. Every round checks
    it and sets up again when something else changed them (xdg-user-dirs-update, the user); only a change restarts
    the desktop icons. Values under the links folder, or under the FUSE root as an earlier agent wrote them, count
    as the server's when the local folders come back.
  - At the end of the session the local folders go back into user-dirs.dirs, so that the next login starts from them
    (xdg-user-dirs-update points a folder it cannot find, such as a dangling link, at the home folder).
- **Tidy:**
  - The local Desktop's launchers are copied into the server's `Desktop`, once per share and never over a file of
    the same name: that keeps the desktop icons on both sides. Launchers elsewhere stay where they are.
  - Desktop and Documents go into the same `Chưa sắp xếp/YYYY-MM-DD`, their folders kept; a name already taken gets
    ` (2)`. The dated folder is made only when something moves.
  - What stays: hidden entries at the top of Desktop and Documents, symlinks and special files, and a file that
    changed while it was copied. Only folders inside the home folder are tidied, never the home folder itself.
- **Files** no longer listed in the policy are kept: a user's wallpaper may still show one.

---

# Part 2: version 0.2

Version 0.2 turns the v1 pair (wallpaper, folders) into a small company device manager. Its scope comes from a survey
of Intune, Jamf, ManageEngine Endpoint Central, Hexnode, Fleet, Landscape, Satellite, SUSE Manager, UCS and UOS's
domain-management platform (2026-11-21). This part describes what the 0.2 code does: the Python admin, helper,
server and windows (`caramos_business/`), and the Rust agent 0.2.0 (`agent/`). "Verified" means seen on the test VMs
on 2026-11-21.

## Everything is opt-in

Nothing changes on an employee machine until the admin turns a feature on, for the whole company or for one
department. Every settings section starts absent (not managed), and the admin window shows each feature as off ("Chưa
bật: máy nhân viên giữ nguyên như hiện tại.") until the admin switches it on and saves. Presets, like the usual office
block hours, only fill the form when a feature is switched on.

Two things are always there, because the machine list needs them:
- the presence a check-in carries: name, IP, version, edition, the logged-in user names, last seen;
- `health`, a few numbers about the machine itself, without personal data.

The detailed inventory is a feature like the others (`inventory`). Commands happen only when the admin sends one.

## Changes to part 1

No 0.1 was released, so part 1 changes where part 2 says so:

- The policy's `format` becomes 2. Part 1's `wallpaper` and `folders` keep their meaning and move inside `settings`.
  A 0.2 agent refuses format 1, and a 0.2 admin writes only format 2. An admin's 0.1 `policy.json` is read as format 2
  (its wallpaper and folders become company settings); `machines.json` entries from 0.1 have no `box_key`, cannot
  authenticate and show "Cần ghép lại". On the employee, a 0.1 pairing has no `agent-box.key`: the window says
  "Máy này cần ghép lại" with a "Ghép lại" button (the helper's `leave`, then the pairing page).
- The check-in token is gone. Every request a paired employee makes is authenticated with an HMAC (see "Machine keys").
  `/register` takes the machine's box key and answers only `{"machine_id"}`. agent.json loses `token`.
- New endpoints: `/wait`, `/inventory`, `/result` and `/help`. New in the policy: departments, more settings sections,
  per-machine sealed secrets, and signed commands for instant actions.
- What never changes:
  - no shell and no arbitrary command on employee machines; only the fixed actions listed here;
  - no covert monitoring: no screenshots, keystrokes, browsing history, location or messages;
  - remote help only after the employee accepts, with a banner while it runs.

## Machine keys and request authentication

- **Admin box key:** X25519, raw 32 bytes, in `/etc/caramos-business/admin-box.key` (0600). The helper makes it with
  the admin role (and on the first change of an admin from 0.1). Its public half (base64) is the policy's
  `admin_box_key` and is in `GET /key` as `box_key`.
- **Machine box key:** X25519, raw 32 bytes, in `/etc/caramos-business/agent-box.key` (0600 root). The helper makes
  a new one at each pairing and sends its public half in `/register` as `box_key`. The admin keeps it in
  machines.json as `box_key`.
  - The agent takes the admin's box key only from a verified policy, never from `/key`: the pairing code covers only
    the Ed25519 key.
- **Shared keys:**
  - `secret = X25519(own private key, the other side's public key)`.
  - `mac_key = HKDF-SHA256(ikm=secret, salt=b"caramos-business/2", info=b"mac", length=32)`.
  - `seal_key` is the same with `info=b"seal"`.
- **Authenticated requests:** every request from a paired employee (`/checkin`, `/inventory`, `/wait`, `/result`,
  `/help`) carries:
  - `X-Caramos-Machine: <machine_id>`
  - `X-Caramos-Time: <unix seconds>`
  - `X-Caramos-Mac: <base64 HMAC-SHA256(mac_key, METHOD + "\n" + PATH_WITH_QUERY + "\n" + TIME + "\n" + hex(sha256(body)))>`

  The body is empty for GET, and PATH_WITH_QUERY is exactly the request target, for example
  `/caramos-business/v1/wait?after=4&serial=12`.
  - The admin answers 401 to an unknown machine, a wrong MAC (compared in constant time), missing headers, and a
    TIME more than one day off.
  - It records `skew = admin time - TIME` for the machine on every authenticated request (in memory) and writes it to
    `health.json` at each check-in; the health checks flag more than 120 s.
  - The wide time window is deliberate. These requests carry nothing secret and repeating one does no harm (results
    are keyed by command id), while a machine with a wrong clock must still be able to report it.
- **Sealing secrets for one machine:** `base64(nonce || ChaCha20-Poly1305(seal_key, nonce, plaintext,
  aad=machine_id as ASCII))`, with a fresh random 12-byte nonce. The plaintext is UTF-8 JSON.
- **Test vectors** are in `tests/protocol-examples/v2/`: keys, derived keys, a MAC, a sealed blob, a signed policy,
  both effective settings, signed commands and invalid policies (one error each). Both sides test against them.
  `make_v2.py` there made them.

## Policy (format 2)

```json
{
  "format": 2,
  "serial": 12,
  "issued": "2026-11-21T09:00:00+07:00",
  "admin": "may-quan-ly",
  "admin_box_key": "<base64 X25519 public key>",
  "remote_help_cert": "<PEM of the admin's TLS certificate for remote help>",
  "files": {"<sha256>": {"size": 812345, "type": "jpg"}},
  "settings": {"wallpaper": {}, "browser": {}},
  "departments": {"ke-toan": {"name": "Kế toán", "settings": {"browser": null}}},
  "members": {"<machine_id>": "ke-toan"},
  "machines": {"<machine_id>": {"settings": {}, "sealed": "<base64>"}}
}
```

- **Signed text:** the admin signs the policy as compact JSON (`separators=(",", ":")`), to stay well under 1 MiB.
  The agent verifies the text as it is; nothing depends on the formatting.
- **Departments:** a machine belongs to at most one department (`members`). A department id is `[a-z0-9-]{1,32}`; its
  `name` is 1 to 60 characters. At most 50 departments. The window makes the id from the name: accents folded (`đ` →
  `d`), other characters `-`, at most 32, then `-2`, `-3` when taken ("Kế toán" is `ke-toan`).
- **Effective settings** of a machine: start from `settings`, then its department's `settings`, then
  `machines[id].settings`.
  - A section present in a later layer replaces the whole section of the earlier one; `null` means the section is
    off for this machine.
  - A section absent from every layer is not managed: the machine keeps its own state, and whatever the agent changed
    for that section before is put back.
  - The window writes "off for the whole company" as the section absent, never `null`; `null` appears only in a
    department's or a machine's layer ("Tắt cho phòng này", "Tắt cho máy này"). A machine's own layer is edited on the
    settings pages through "Áp dụng cho" → "Một máy…".
- **`machines[id].sealed`:** the machine's secrets, sealed for it: `{"wifi": {"<ssid>": "<passphrase>"}}`, only for
  the networks in its effective settings. Later versions may add keys; unknown keys are ignored.
  - The admin keeps the passphrases in `/var/lib/caramos-business/admin/secrets.json` (0600 root,
    `{"wifi": {"<ssid>": "<passphrase>"}}`), one per SSID whatever the layer, and seals them again for every paired
    machine at each save. The window sends only the passphrases typed since the last save and shows the others as
    "Mật khẩu: đã lưu"; a `wpa-psk` network without one cannot be saved.
  - A machine that pairs after the last save, and whose effective settings have a `wpa-psk` network, makes the server
    sign the policy again (serial + 1) with its sealed secrets. That is the only time the server signs; it reads
    `admin-key.pem` as the helper does.
- **`remote_help_cert`:** a self-signed certificate the helper makes with the admin role (see "Remote help").
- **Sizes:**
  - The policy text is at most 1 MiB.
  - Images stay as in part 1, and every image any layer's wallpaper uses is listed in `files`.
  - The admin refuses to save a policy over the limit and says why.
- **A machine taken out of the company** ("Gỡ khỏi công ty") is removed from `machines.json` (with its inventory,
  asset record and health; from 0.3 an asset record the admin typed into stays, see "Changes during implementation")
  and remembered in `removed.json`; for 30 days the policy carries `machines[id].settings`
  with every section `null`, so that its agent puts everything back, then the entry goes.

### Settings sections

Every section is optional, in any layer.

| Section | Value | Limits |
|---|---|---|
| `wallpaper` | as part 1: `{"default", "periods", "lock"}` | part 1 |
| `folders` | as part 1: `{"share", "tidy"}` | part 1 |
| `shares` | `[{"name": "Kế toán", "url": "smb://nas/ketoan"}]` | ≤ 20; `name` 1–60; `url` follows part 1's share rules, without `%` |
| `browser` | `{"homepage", "bookmarks", "block", "block_hours", "safe_search"}` | see below |
| `printers` | `[{"name": "Máy in tầng 2", "uri": "ipp://192.168.1.50/ipp/print", "location": "Tầng 2", "default": true}]` | ≤ 20; `name` 1–60; `uri` (≤ 500) is `ipp://` or `ipps://` with a host and no `@`; `location` ≤ 60; at most one `default` |
| `power` | `{"shutdown": {...} or null, "wake": {...} or null}` | see below |
| `apps` | `{"required": [ids], "forbidden": [ids]}` | App Center catalogue ids `[a-z0-9-]{1,40}`, ≤ 50 each, not in both |
| `usb` | `{"storage": "allow" or "read-only" or "block"}` | |
| `screen_lock` | `{"idle_minutes": 10, "on_suspend": true}` | `idle_minutes` 1–120 |
| `firewall` | `{"enabled": true}` | only `true` is managed; turning it off is not offered |
| `inventory` | `{"enabled": true}` | the detailed inventory (hardware, apps) is sent only when this is in effect; off is `null` |
| `wifi` | `[{"ssid": "CongTy", "security": "wpa-psk" or "open", "hidden": false}]` | ≤ 10; `ssid` 1–32 bytes; a `wpa-psk` network's passphrase (8–63 printable ASCII characters) is in the machine's sealed secrets |

- **`browser`:**
  - `homepage`: an `https://` or `http://` URL with a host (≤ 2000 characters), or null.
  - `bookmarks`: `[{"name", "url"}]`, ≤ 50; `name` 1–60; `url` is http(s).
  - `block`: domains, ≤ 500: labels of `[a-z0-9-]` (1–63 characters, no hyphen at either end), at least two labels,
    at most 253 characters, no scheme, no path, not an IP address. The admin UI offers presets (social networks,
    video, games, shopping; never Zalo) that expand into domains when saved; a preset shows as chosen when the list
    holds all its domains, so they are not stored apart. A typed domain loses `https://`, the path and a leading
    `www.` or `m.`, unless what remains is a second-level suffix such as `com.vn`.
  - `block_hours`: null blocks all the time. Otherwise `{"days": [1-7, ISO weekday, 1 = Monday], "ranges":
    [["08:00", "12:00"], ["13:30", "17:30"]]}` blocks only inside the ranges on those days. At most 6 ranges;
    `HH:MM` 24-hour; a range starts before it ends, on the same day.
  - `safe_search`: bool.
- **`power`:**
  - `shutdown`: `{"days": [1-7], "time": "18:30", "warn_minutes": 10 (1-30), "postpone_minutes": 30 (5-120),
    "max_postpones": 2 (0-5), "laptops": "skip" or "suspend" or "same"}`; the agent uses these defaults for missing
    keys.
  - `wake`: `{"days": [1-7], "time": "07:45"}`.
- **What the window fills in when a section is switched on:** browser block hours 08:00–12:00 and 13:30–17:30, Monday
  to Saturday; shutdown 18:30 Monday to Saturday with the defaults above; wake 07:30; USB read-only; screen lock 10
  minutes and on suspend.
- **Unknown keys** inside a section, and unknown sections, are ignored, so that later versions can add them. An invalid
  section makes the whole policy invalid, as in part 1, and the admin checks before signing.
- **Where the admin is stricter** than the agent (it never signs these): `admin_box_key` is required (base64 of 32
  bytes); `remote_help_cert`, when present, starts with `-----BEGIN CERTIFICATE-----` and is at most 8 KiB; machine
  ids in `members` and `machines` are canonical lower-case UUIDs; day lists hold 1 to 7 different days; names (shares,
  printers, bookmarks, departments) are not blank; printer names, share URLs, SSIDs, blocked domains and the ids of
  each apps list are unique; `firewall` and `inventory` with `"enabled": false` are refused (the agent treats
  `firewall: {"enabled": false}` as not managed); a sealed blob is 28 bytes to 64 KiB once decoded.

### Applying the sections (agent)

Every system file the agent writes starts with a comment saying CaramOS Doanh nghiệp manages it, where the format
allows one. The agent removes only what it made, and puts back what it changed when a section stops being managed or
the machine leaves; what it changed is in `/var/lib/caramos-business/agent/managed.json` (0600).

The daemon applies the system sections (browser, printers, power, apps, usb, firewall, wifi). The session parts apply
the user's sections (wallpaper, folders, shares, screen_lock) from `effective.json` (see "Agent").

- **`shares`:** for each user, the session part adds a line `smb://… Name` to `~/.config/gtk-3.0/bookmarks` (Nemo and
  Thunar read it), and mounts the share at login with part 1's flow (`gio mount`, `caramos-business --connect` when
  it needs a password).
  - A share that cannot be mounted is tried again after 30 s three times (just after login the network or GVfs may
    not be ready), then every 5 minutes; it is reported as failed from its second failure in a row.
  - The lines it added are remembered in `~/.config/caramos-business/state.json`, and only those are removed.
- **`browser`:**
  - **Firefox:** `/etc/firefox/policies/policies.json`. Firefox reads only one policies file, so this one starts as a
    copy of `/usr/lib/firefox/distribution/policies.json` (Mint's, when it exists), with our keys added:
    - `Homepage` (`{"URL", "Locked": false, "StartPage": "homepage"}`);
    - `ManagedBookmarks` and `DisplayBookmarksToolbar: "always"` when there are bookmarks;
    - `DNSOverHTTPS: {"Enabled": false, "Locked": true}` (needed for the blocking below);
    - `SearchEngines` is not touched.

    When the section goes away, the file goes away if the agent made it, or goes back to its earlier contents (the
    empty `/etc/firefox/policies` folder stays). Firefox shows its own first-run page on its first launch, not the
    homepage; `OverrideFirstRunPage` is not set.
  - **Chromium family:** `caramos-business.json` in the managed policy folder of each browser that is installed:
    - Chrome: `/etc/opt/chrome/policies/managed`;
    - Chromium: `/etc/chromium/policies/managed`;
    - Edge: `/etc/opt/edge/policies/managed`;
    - Brave: `/etc/brave/policies/managed`;
    - Cốc Cốc: `/etc/opt/coccoc/policies/managed` (the binary of `coccoc-browser-stable` 154.0.8037.106 holds
      `/etc/opt/coccoc/policies`, to which Chromium adds `managed`); installed when `/opt/coccoc/browser/browser`
      exists.

    The file holds `HomepageLocation`, `HomepageIsNewTabPage: false`, `RestoreOnStartup: 4`,
    `RestoreOnStartupURLs`, `ManagedBookmarks`, `DnsOverHttpsMode: "off"`, `ForceGoogleSafeSearch` and
    `ForceYouTubeRestrict: 1` when `safe_search` is on, and `URLBlocklist` when `block` applies all the time.
  - **Blocking:** a block in `/etc/hosts` between `# BEGIN caramos-business` and `# END caramos-business`.
    - Each domain gets `0.0.0.0 d`, `0.0.0.0 www.d` and `0.0.0.0 m.d`.
    - With `block_hours`, the daemon writes or empties the block at the range edges, checking every 30 s. Firefox
      keeps names it resolved for about two minutes, so in an open Firefox a site is blocked or freed up to two
      minutes after the edge of a range.
    - Nothing a user visits is ever recorded.
- **`printers`:**
  - `lpadmin -p caramos-<slug> -E -v <uri> -m everywhere -D <name> -L <location> -o printer-is-shared=false`, and
    `lpadmin -d` for the default. `<slug>` is made from the name, ASCII, unique.
  - `-m everywhere` asks the printer for its capabilities, so it fails while the printer does not answer: the agent
    then makes the queue without a driver (`lpadmin -p … -E -v <uri>`), reports `failed: <name> does not answer` in
    `applied`, and makes it again with `-m everywhere` once the printer answers.
  - Queues named `caramos-*` that are no longer listed are removed, and no other queue is touched. The default printer
    before a `default: true` is not put back when the section goes away.
- **`power`:**
  - The daemon checks the schedule every 30 s. At `time - warn_minutes` it asks every session part to show a
    countdown, with the postpones left; any "postpone" moves the shutdown for this machine and this day only. A
    shutdown time more than 10 minutes past (the machine was off or asleep) is skipped for that day.
  - When the time comes it runs `systemctl poweroff`, or `systemctl suspend` for a laptop with `laptops: "suspend"`.
    `skip` leaves laptops on. A machine with no session shuts down without asking. A laptop is a DMI chassis type 8,
    9, 10, 11, 12, 14, 18, 21, 30, 31 or 32, or a machine with a `BAT*` power supply.
  - With `wake`, before a scheduled shutdown it sets `rtcwake -m no -t <next wake epoch>`, and it turns on
    `802-3-ethernet.wake-on-lan magic` on the wired NetworkManager connections. It clears the alarm
    (`rtcwake -m disable`) when `wake` goes away and at `leave`, and forgets it once its time passed. QEMU forgets the
    RTC alarm when a VM powers off; real boards keep it.
  - The admin server sends magic packets at the wake times to the MACs of the machines whose effective settings have
    `wake`: at the minute of `wake.time` on `wake.days`, to 255.255.255.255 ports 9 and 7, for every MAC the machine
    reported (`MACHINE.mac` and the wired cards of its inventory), once per machine and minute.
- **`apps`:**
  - Missing `required` apps are installed and installed `forbidden` apps removed, through App Center's helper, run
    by the daemon as root: `/usr/lib/caramos-app-center/caramos-app-center-helper install|remove <ids>`, installs in
    batches of 40, removals one by one, with App Center's detect module for what is installed.
  - This runs at most every 6 hours, or at once when the section changes. Results go into the health report.
  - Never undone, not even at `leave`: apps appearing or disappearing again would surprise the users.
- **`usb`:**
  - `read-only`: a udev rule in `/etc/udev/rules.d/71-caramos-business-usb.rules` that makes udisks mount USB file
    systems read-only (`UDISKS_MOUNT_OPTIONS_DEFAULTS="ro"`, `UDISKS_MOUNT_OPTIONS_ALLOW` without `rw`).
  - `block`: a polkit rule in `/etc/polkit-1/rules.d/71-caramos-business-usb.rules` that denies
    `org.freedesktop.udisks2.filesystem-mount*` for USB devices to every user.
  - Keyboards, mice, printers and signature tokens (smart-card class) keep working: only file-system mounts change.
  - `udevadm control --reload`, then `udevadm trigger --subsystem-match=block --action=change` (the reload does not
    reach disks already plugged in). Verified: a USB disk mounts read-only, `-o rw` is refused ("Mount option `rw' is
    not allowed"), and with `block` udisks answers "Not authorized to perform operation".
- **`screen_lock`:** for each user, in their session; set again when changed, like the wallpaper lock, and the earlier
  values put back when the section goes away. Never `dconf update` under a running Cinnamon.
  - Cinnamon (6.6): `org.cinnamon.desktop.session idle-delay` (seconds), `org.cinnamon.desktop.screensaver
    lock-enabled true` and `lock-delay 0`, and `org.cinnamon.settings-daemon.plugins.power lock-on-suspend` for
    `on_suspend`.
  - Xfce (CaramOS Xfce: light-locker under xfce4-power-manager): xfconf `xfce4-power-manager`
    `/xfce4-power-manager/blank-on-ac` and `/xfce4-power-manager/blank-on-battery` (uint, minutes after which the
    screen blanks) = `idle_minutes`, `/xfce4-power-manager/lock-screen-suspend-hibernate` (bool) = `on_suspend`; and
    gsettings `apps.light-locker` `lock-after-screensaver` = 1 (uint, seconds after blanking; 0 turns locking off),
    `late-locking` = false, `lock-on-suspend` = `on_suspend`.
- **`firewall`:** `ufw default deny incoming`, `ufw default allow outgoing`, `ufw allow 47021/udp` (discovery's
  answers, see part 1 "Discovery"), then `ufw --force enable`. That is the only port it opens: incoming SSH and every
  other incoming service close (the guide says so). The section going away leaves ufw on; only `leave` puts ufw back
  as it was before the agent first changed it (active or not, the default policies, from `ufw status` and
  `/etc/default/ufw`, and the 47021/udp rule removed unless it was there before, all kept in `managed.json`).
- **`wifi`:**
  - `/etc/NetworkManager/system-connections/caramos-business-<slug>.nmconnection`, 0600 root, `permissions=` empty,
    the passphrase in the file (`psk-flags=0`), then `nmcli connection reload`.
  - Profiles named `caramos-business-*` that are no longer listed are removed.

## Signed commands (instant actions)

A command travels as an envelope `{"command": "<the command as a JSON text>", "signature": "<base64 Ed25519
signature of its UTF-8 bytes>"}`, made like the policy. The command:

```json
{
  "seq": 41,
  "id": "<uuid4>",
  "targets": {"machines": ["<machine_id>"]},
  "action": "message",
  "args": {"title": "Họp 15h", "body": "Phòng họp tầng 3.", "ack": true},
  "issued": "2026-11-21T14:00:00+07:00",
  "expires": "2026-11-21T14:10:00+07:00"
}
```

- `targets` is exactly one of `{"machines": [...]}`, `{"departments": [...]}` or `{"all": true}`.
- `seq` grows by one for every command the admin makes.
- **Lifetime:** the admin signs only a command whose `expires` comes after `issued` and at most 24 h later. The agent
  does not check the lifetime, only that `expires` has not passed (the test vectors expire in 2099). The admin picks
  per action (minutes): `sync` 10, `inventory` 60, `lock` 10, `message` 240, `logout`/`restart`/`shutdown` 10,
  `cancel` 10, `update` 1440, `remote_help` 3, `usb_unlock` 30: short where an action must not happen hours later,
  when someone turns the machine on. The helper's `command` takes an optional `minutes` (1–1440).
- **Agent checks,** in this order: the signature with the pinned key; the id not already handled; that it is among
  the targets (through the effective department); `issued` and `expires` readable; `expires` not passed; `seq` higher
  than the last one it ran; `action` one of the list below with valid `args` (unknown keys in `args` are refused by
  both sides); for `restart`, `shutdown`, `logout`, `lock`, `message` and `remote_help`, `issued` not before this
  boot. It keeps `{"machine_id", "last_seq", "done": [the last 1000 ids]}` in
  `/var/lib/caramos-business/agent/commands.json` (0600); a record of another machine id starts again at 0, since a
  new pairing's admin counts from 1, and `leave` deletes it. A command is recorded (written and synced to disk)
  before it acts, so a restart or a shutdown never runs twice.
- **Not from before this boot:** a machine that was off, or restarting, when a command came must not act on it once
  it is on again, even within the lifetime: a "restart in 10 minutes" from before a power cut does not restart the
  machine after it. So the agent reports `restart`, `shutdown`, `logout`, `lock`, `message` and `remote_help` whose
  `issued` is before the boot time (`btime` in `/proc/stat`) plus 60 s as `expired` with the detail "trước lần khởi
  động này". The 60 s cover an admin clock up to a minute ahead; a command issued in the first minute after boot is
  dropped with them. `sync`, `inventory`, `update`, `usb_unlock` and `cancel` still run within their lifetime.
- **Actions:**

| `action` | `args` | What happens |
|---|---|---|
| `sync` | `{}` | fetch the policy and check in now; result "thiết lập bản 12" |
| `inventory` | `{}` | collect and send the inventory now; result "đã gửi", or `ignored` "kiểm kê chưa bật" without the section |
| `lock` | `{}` | the daemon runs `loginctl lock-sessions` (which Cinnamon 6.6 ignores) and hands the command to each session part, which runs `cinnamon-screensaver-command --lock` on Cinnamon, `xflock4` on Xfce, `loginctl lock-session` elsewhere; result "đã khóa: lan" |
| `message` | `{"title" (1–80), "body" (≤ 1000), "ack": bool}` | each logged-in user sees it; result "đã đọc: lan; chưa đọc: minh" with `ack`, else "đã hiện cho: lan, minh"; nobody logged in: `failed` "không có ai đăng nhập" |
| `logout`, `restart`, `shutdown` | `{"warn_seconds": 0-900}` | a countdown in each session, without postpones, then the action (logout through the session part; restart and shutdown through `systemctl`); results "đã đăng xuất: …", "đang khởi động lại", "đang tắt máy" |
| `cancel` | `{"id": "<command id>"}` | cancels a countdown not yet finished: that one becomes `failed` "đã hủy", the `cancel` itself `done` |
| `update` | `{}` | `caramos-ota --check` when it exists (the daily check's command), then `apt-get update` and `apt-get install --only-upgrade` of the packages `apt-get -s upgrade` takes from a `-security` suite (`--force-confdef --force-confold`, a 10-minute dpkg lock wait, at most an hour each); the result says what ran |
| `remote_help` | `{"admin_host": IPv4, "port": 1025-65535, "mode": "view" or "control", "admin_name" (≤ 64)}` | see "Remote help"; result "chạy 25 giây (control), người dùng dừng", or `refused` "người dùng từ chối" |
| `usb_unlock` | `{"minutes": 1-240}` | USB storage allowed until then, whatever `usb` says; result "USB mở đến 16:32" |

- **Results:** `POST /caramos-business/v1/result` with `{"id", "state": "done" or "failed" or "refused" or "expired"
  or "ignored", "detail" (≤ 300, Vietnamese), "time"}`, one per command per machine, sent again every 30 s until the
  admin answers 200. The admin keeps a result only for a command still in its `commands.json` and answers 200 to the
  others, so that the agent does not retry them forever.

## Long-poll channel

- **Request:** `GET /caramos-business/v1/wait?after=<last seq run>&serial=<serial of the policy it has, 0 if none>`,
  authenticated.
- **Admin:** answers at once when it holds commands for this machine with a higher seq, or when its policy serial is
  not `serial`. Otherwise it holds the request up to 50 s. The answer is always 200: `{"serial": N, "commands":
  [envelopes...]}`, oldest first, at most 50.
  - Department targets use the current policy's `members`. Commands issued before the machine paired (its
    `machines.json` `paired` time) are not delivered: a message to all from this morning is not for a machine added
    this afternoon. Expired commands are delivered, so that the agent reports `expired`.
  - It keeps the commands of the last 7 days (at most 1000) in `commands.json`.
  - It notices a new policy or new commands within a second: it watches the mtimes of `signed-policy.json` and
    `commands.json`, because the helper writes them (a watcher thread every 0.5 s, and each waiting request every
    second).
  - Each `/wait` holds a server thread for up to 50 s: fine for the hundreds of machines of a small company.
- **Agent:** keeps one `/wait` open all the time in its own thread, retrying after 10–30 s on errors. A different
  `serial` makes it fetch the policy at once, so a saved change reaches online machines in seconds. The 5-minute
  fetch stays as the fallback.

## Inventory and health

- **`POST /caramos-business/v1/inventory`** (authenticated), only while the effective settings have `inventory:
  {"enabled": true}`; otherwise the admin answers 403, which the agent counts as off, not as an error: nothing is
  retried until it is due again. The agent sends it after its first good round, when the inventory's hash changes
  (collected every 6 h), at the next round after the section comes on, and on the `inventory` command. At each save
  the admin deletes the stored inventory of every machine where the section is no longer in effect.

```json
{
  "collected": "<ISO 8601>",
  "hash": "<sha256 hex of the rest>",
  "system": {"vendor": "", "product": "", "serial": "", "bios": "", "chassis": "desktop|laptop|other", "boot_time": ""},
  "cpu": {"model": "", "cores": 4, "threads": 8},
  "memory": {"total_mb": 7834, "modules": [{"size_mb": 8192, "type": "DDR4", "speed_mts": 3200, "slot": "DIMM A1"}]},
  "disks": [{"name": "nvme0n1", "model": "", "serial": "", "size_gb": 512, "rotational": false, "transport": "nvme", "health": "ok|failing|unknown"}],
  "batteries": [{"name": "BAT0", "design_wh": 45.0, "full_wh": 38.2, "health_pct": 85, "cycles": 210}],
  "monitors": [{"connector": "HDMI-A-1", "name": "DELL P2419H", "serial": ""}],
  "network": [{"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "ipv4": "192.168.1.20", "wired": true}],
  "os": {"caramos": "1.4.0", "edition": "cinnamon|xfce|other", "kernel": ""},
  "apps": [{"id": "", "name": "", "version": "", "source": "deb|flatpak"}]
}
```

  Strings are at most 200 characters, lists at most 500 items, and the body at most 1 MiB. The admin checks types and
  enum values, makes missing keys empty or null, drops unknown keys, and stores `hash` without checking it.
  - Hardware comes from `/sys/class/dmi/id`, `dmidecode -t 17`, `lsblk -J -b`, disk health from udisks2 or
    `smartctl -j -H` (`dmidecode` and `smartctl` only when installed), `/sys/class/power_supply/BAT*`, EDIDs in
    `/sys/class/drm/*/edid` and `ip -j addr`.
  - `apps` lists only what a user sees: Flatpak apps (`flatpak list --system --app`), and deb packages that own a
    `/usr/share/applications/*.desktop` file without `NoDisplay=true`.
- **Health** is in every check-in from 0.2, collected at most every 30 min (`updates` from `apt-get -s upgrade`,
  "Inst" lines, the `-security` ones counted apart; `firewall` from `ufw status`):

```json
"health": {
  "disk_free_pct": 23, "disk_health": "ok|failing|unknown", "battery_health_pct": 81,
  "updates": {"security": 3, "other": 12}, "reboot_required": false,
  "firewall": "on|off|unknown", "caramos_version": "1.4.0", "uptime_hours": 51,
  "applied": {"<section>": "ok" or "failed: <short reason>"}
},
"capabilities": ["wallpaper", "folders", "shares", "browser", "printers", "power", "apps", "usb", "screen_lock", "firewall", "inventory", "wifi", "commands"]
```

  `battery_health_pct` is null without a battery (the admin accepts 0–200: a new battery can be above 100). The
  check-in body is part 1's, plus these two keys; `machine_id` in the body is optional and must be the header's, and
  a check-in without `health` or `capabilities` keeps the last ones. `applied` holds the daemon's sections and the
  users' (`wallpaper`, `folders`, `shares`, `screen_lock`, as "failed: <user>: …" when a user's failed).
- **Problems** the admin flags (`health.py`; the window shows them with the time each was first seen):
  - less than 10 % disk free, or a failing disk;
  - battery health under 60 %;
  - security updates waiting for more than 7 days (since the first check-in that showed some);
  - a reboot required for more than 3 days;
  - the firewall off while `firewall` is in effect;
  - clock skew over 120 s;
  - not seen for 3 days (worked out by the window, since no check-in can report it);
  - any `applied` value that is not `ok`;
  - a non-null section whose capability the agent lacks, once it reported capabilities or health.

  `health.json`: `{"<machine_id>": {"skew", "security_since", "reboot_since", "problems": {"<key>": "<first
  seen>"}}}`.

## Help requests and remote help

- **`POST /caramos-business/v1/help`** (authenticated): `{"user", "note" (≤ 300), "time"}`. An employee sends it from
  "Nhờ IT hỗ trợ" in the window. The admin keeps the open requests in `help-requests.json` (at most 3 per machine and
  200 in all, the oldest going first), shows them on Tổng quan with a desktop notification while the window is open;
  answering one is a `remote_help` command (the request is then closed and logged as answered), and closing one needs
  nothing.
- **Admin, when "Kết nối" is pressed:**
  - The window runs `vncviewer -listen 5500` (TigerVNC) as the admin user.
  - The helper starts `stunnel` as a transient systemd unit (`systemd-run --unit=caramos-business-remote-help`,
    `RuntimeMaxSec=4h`, `NoNewPrivileges`, `ProtectHome`, `PrivateTmp`), with its configuration in
    `/run/caramos-business/remote-help.conf` (0600). It accepts TLS on 0.0.0.0:5501 with
    `/etc/caramos-business/admin-tls.pem` and its key `admin-tls.key` (0600), and connects to 127.0.0.1:5500. The
    helper stops it again on "Dừng" and when the viewer exits.
  - The certificate: EC P-256, self-signed, CA:TRUE, keyUsage digitalSignature and keyCertSign, EKU serverAuth, SAN
    the host name, ten years.
  - `admin_host` is the address of the admin's route toward the employee's reported IP.
  - ufw, when on, gets 5501/tcp opened while it runs.
  - The result comes only at the end, so the window shows "Đang hỗ trợ" once a connection to local port 5500 is
    ESTABLISHED (`/proc/net/tcp`), and gives up after two minutes without one.
  - `vncviewer -listen` listens on every interface, so a plain connection to 5500 from the LAN reaches the viewer
    directly; an employee's stream still goes through TLS, and a stranger could only show their own screen. With ufw
    on, 5500 stays closed.
- **Employee, on the `remote_help` command:** the session part of the user at the screen (the active graphical session
  on seat0) asks `caramos-business --prompt consent`, and waits 70 s for it (the prompt itself answers `refuse` after
  60 s).
  - **Accepted:** it runs, as that user, from `$XDG_RUNTIME_DIR/caramos-business/remote-help/` (0700):
    - `stunnel` as a client: `client = yes`, `accept = 127.0.0.1:<free port>`, `connect = <admin_host>:<port>`,
      `verifyPeer = yes`, `CAfile` = the policy's `remote_help_cert`, `foreground = yes`, so only the admin's
      certificate is accepted. The agent waits until stunnel listens without connecting to it: a test connection
      would be forwarded and use up `vncviewer -listen`'s only connection;
    - `x11vnc -display $DISPLAY -connect_or_exit 127.0.0.1:<that port> -once -nopw -noshm -localhost -rfbport 0`,
      plus `-viewonly` in view mode. `-connect_or_exit` ends x11vnc when the connection fails or closes;
      `-localhost -rfbport 0` keeps it from listening at all;
    - `caramos-business --prompt banner` while it runs. "Dừng", the end of the connection, a `cancel` or the end of
      the session stops x11vnc and stunnel.
  - **Refused, or 60 s without an answer:** the result is `refused`, and nothing is started.
  - The result says how long it ran.
- Encryption: the employee-to-admin stream is TLS, and the employee verifies the admin's certificate. The viewer only
  ever sees the screens of employees who accepted. Verified: TLS 1.3, the admin's viewer showed the employee's
  screen, "Dừng" stopped it; another certificate was refused ("certificate verify failed").

## Employee UI contract (Rust session part → Python)

The session part runs `caramos-business --prompt KIND [options]` as the user. The program prints one JSON line
`{"answer": "..."}` and exits 0; the agent reads only that first line and closes a prompt by killing it.

| KIND | Options | Answers |
|---|---|---|
| `message` | `--title T --body B --admin NAME [--ack]` | `read`, `closed` |
| `countdown` | `--action shutdown|restart|logout|suspend --seconds N [--postpones-left K --postpone-minutes M]` | `now`, `postpone`, `timeout` |
| `consent` | `--admin NAME --mode view|control` | `view`, `control`, `refuse` (after 60 s: `refuse`) |
| `banner` | `--admin NAME --mode view|control` | `stop`; it stays until then, or until the agent ends it |
| `notice` | (none) | `ok`: the notice after pairing, saying what the company manages and what it never collects |

- The prompts are small windows that stay above the others (`_NET_WM_STATE_ABOVE` through libX11; nothing on
  Wayland). A countdown cannot be closed. Options that break the contract print an error on stderr and the kind's
  default answer (`closed`, `timeout`, `refuse`, `stop`, `ok`), exit 0. Ended by SIGTERM a prompt prints nothing.
- The notice is shown once per user and machine id (`notice_for` in `~/.config/caramos-business/state.json`). It and
  the window's page "Máy này do công ty quản lý" list "Trạng thái máy" and "Thao tác từ bộ phận IT" always, then only
  the sections in effect for this machine (from `effective.json`), then the fixed list of what the company cannot see.
- **"Nhờ IT hỗ trợ":** `caramos-business --help-request` asks for a short note, then writes
  `/run/user/<uid>/caramos-business/outbox/help-<unix>.json` (or `help-<unix>-N.json`) `{"note"}`, through a
  temporary name, the note trimmed to 300 characters. The daemon sends it to `/help` as `{"user", "note", "time"}`
  and removes the file once the admin answered 200.
- **Relay between daemon and session part:**
  - The daemon puts a verified command for a user in `/run/caramos-business/inbox/<uid>/<id>.json` (folders 0755 and
    files 0644, root's), not in `/run/user`: a root daemon writing into a folder the user owns can be sent elsewhere
    by a symlink. It empties the inboxes when it starts.
  - The session part cannot rename in root's folder, so it remembers the ids it took in
    `$XDG_RUNTIME_DIR/caramos-business/taken`, acts, and writes `/run/user/<uid>/caramos-business/outbox/<id>.json`
    `{"id", "state", "detail"}`.
  - The daemon reads the outboxes every 2 s without following symlinks (only files the user owns), sends `/result`,
    and removes the files.
  - A command for several users gives one combined result (see the actions' results).

## Agent

How the Rust agent reads what the sections above leave open (more in `agent/README.md`); part 1's "Agent" section
still holds.

- **`effective.json`:** `/var/lib/caramos-business/agent/effective.json` (0644), written by the daemon after each
  round: `{"serial", "machine_id", "department", "admin_name", "remote_help_cert", "files", "settings"}`, the settings
  already merged for this machine. The session parts and the window read only that file, so they never merge or
  read another machine's entry. A session part applies it only while the role is `employee`, agent.json exists and a
  policy is stored. Without it (the machine left, or has no policy) a session part puts back its sections and stops
  any prompt or remote help still running.
- **`status.json`** gains `"applied": {"wallpaper"|"folders"|"shares"|"screen_lock": "ok" or "failed: …"}`, which the
  daemon puts into `health.applied`.
- **`caramos-business-agent leave`**, run as root by the helper first when the machine leaves (without the network):
  1. stops `caramos-business-agent.service`, so that no round applies the policy again meanwhile;
  2. puts back what the daemon changed, from `managed.json`: Firefox's policies file removed or its earlier contents
     back, the Chromium-family files removed, the hosts block removed; the `caramos-*` queues it made; the USB rules
     and any `usb_unlock`; the `caramos-business-*` Wi-Fi profiles; wake-on-lan and the wake alarm; ufw as it was
     before the agent first changed it;
  3. removes `effective.json`, `commands.json`, `clone.json` and the inboxes; each user's session part then puts
     back their part within 2 s (bookmarks, Desktop and Documents in user-dirs.dirs, screen lock) and stops prompts
     and remote help;
  4. waits up to 15 s for each running session part to write its status again with nothing applied, and prints whose
     part is back and whose is not yet; a user who is not logged in gets their part back at their next login;
  5. exits 0 when every system part was put back, 1 otherwise (with the reasons on stderr).

  Kept: the apps, the company's last wallpaper (the helper keeps the pictures), the empty `/etc/firefox/policies`
  folder, and the links in `~/.local/share/caramos-business/server` (they dangle). "Gỡ khỏi công ty" (every section
  null for 30 days) puts back the same, except ufw, which stays on, and the pairing.

## Cloned disks

A disk copied from a paired machine (one image put on several new computers) carries its agent.json and keys, so
two machines would act as one: the same box key, the same commands, one entry at the admin.

- **Pairing** stores the machine's `/etc/machine-id` as `machine_id_os` in agent.json and in the public `admin.json`.
  A machine paired before 0.2 has none, and is never taken for a clone.
- **Daemon:** at each round, if `machine_id_os` is set and `/etc/machine-id` is no longer it, the disk was cloned onto
  another machine. The daemon then applies nothing, puts nothing back (the settings on the disk are the copied
  machine's, still the company's), sends nothing (no check-in, no inventory, no results; `sync` fails), logs "máy
  này là bản sao của máy đã ghép; hãy ghép lại" once, and writes `clone.json` (0644) `{"paired_on", "this_machine"}`
  (the two machine ids) in its state folder. Each round checks again: back on the paired machine, the mark goes.
- **Session parts** apply nothing and put nothing back while `clone.json` exists, and stop any prompt or remote help.
- **Employee window:** when `clone.json` exists, or `machine_id_os` differs from `/etc/machine-id`, it shows "Máy này là
  bản sao của một máy đã ghép" with a "Ghép lại" button. The button runs the helper's `leave` (which puts back what
  the disk holds and removes the mark), then shows the pairing page, so that the machine pairs as one of its own.
- **Admin:** a byte-for-byte copy keeps `/etc/machine-id` too, so the agent cannot see it; but the two machines check
  in by turns, from different network cards. The admin keeps, per machine, the cards it reported from (`macs`, the
  last 8, with when each was last seen) and the times it changed card (`mac_switches`, the last 8). Three changes or
  more within 30 minutes show the health problem `clone`, first in the list: "Có thể là máy nhân bản: các máy có card
  mạng … cùng báo về bằng mã của máy này. Hãy gỡ máy, rồi ghép lại từng máy." A laptop moving from its cable to Wi-Fi
  and back changes card twice.

## Admin side

- **Answers of the server:** 400 a body that is not the protocol's; 401 as in "Machine keys"; 403 `/register` while
  pairing is closed or with a wrong code (20 wrong codes close pairing), and `/inventory` when it is not on for that
  machine; 404 an unknown path; 413 a body over 64 KiB (1 MiB for `/inventory`).
- **Helper commands** (pkexec, one JSON object in and out, strict argument checks): `role admin|employee`, `pairing
  open|close`, `policy` (the window's draft on stdin with `pictures` for any layer and `wifi_passphrases`),
  `command` (`{"targets", "action", "args", "help_id"?, "minutes"?}`), `forget-machine ID`, `asset ID`,
  `help-close ID`, `remote-help start|stop`, `backup FILE`, `restore FILE`, `pair IP CODE`, `leave`. `leave` runs
  `caramos-business-agent leave` first, then disables the service and removes agent.json, `agent-box.key`,
  `policy.json`, `admin.json` and `clone.json`.
- **Admin state folder:** `/var/lib/caramos-business/admin` is `root:sudo` 0750: the window runs as the user, and
  polkit's administrators are the sudo group.
- **Pairing** writes `agent-box.key` (0600) and agent.json without a token, with `machine_id_os` (see "Cloned
  disks"); the public `agent/admin.json` (0644) holds `admin_name`, `admin_url`, `fingerprint`, `machine_id` and
  `machine_id_os`.

## Admin backup and restore

- `caramos-business-helper backup FILE`, with the passphrase (at least 8 characters) on stdin.
  - Contents: the admin's keys and certificate, and all of `/var/lib/caramos-business/admin`: a tar with
    `etc/caramos-business/{admin-key.pem, admin-box.key, admin-tls.key, admin-tls.pem}` and
    `var/lib/caramos-business/admin/…`.
  - Format: magic `CBKP1`, then a 16-byte salt, then a 12-byte nonce and the tar encrypted with AES-256-GCM under a
    key that scrypt (n=2^15, r=8, p=1) makes from the passphrase, without additional data (the key and the nonce
    cover the header).
  - The helper opens FILE as the `PKEXEC_UID` user (seteuid), so root never writes or reads a file the user could
    not.
- `caramos-business-helper restore FILE`, passphrase on stdin, on a machine without a role:
  - It writes back only those paths (no links, devices or `..`), keys 0600, and only once the whole backup opened;
    then it takes the admin role and starts the server.
  - Employee machines find it again by discovery: the pinned fingerprint is the same.

## Audit log

- `/var/lib/caramos-business/admin/audit.jsonl`, one line per change: `{"time", "user", "action", "summary",
  "details"}`.
  - `user` is the account that ran the window (from `PKEXEC_UID`); empty for the server's lines.
  - The helper writes a line for: the role taken, pairing opened or closed, settings saved (`details.changes`: which
    sections changed, for which scope), every command, a machine removed, asset details changed, a help request
    answered or closed, backup, restore.
  - The server writes a line for each registration.
- `summary` is in the writer's language (the server writes in the system's), so the window renders each line from
  `details` in the reader's language, and falls back to `summary` for lines it does not know.
- The window shows the newest 500 lines.

## Transparency

Under the Personal Data Protection Law 91/2025/QH15, article 25(3)(a), staff must know the measures used on their
machines.

- **Employee:**
  - After pairing, each user sees `--prompt notice`, and sees it again whenever the company turns on a section that
    the notice did not list (the session part keeps the listed sections in `state.json`, `notice_sections`).
  - The window's page "Máy này do công ty quản lý" lists the managed sections in effect, and always says what the
    company cannot see: the screen (unless you accept remote help), what you type, the websites you visit, your
    messages, and files outside the company's folders.
- **Admin:** the guide and a line under the machine list remind the admin to tell staff in writing, for example in
  the internal labour rules.

## Files (additions to part 1)

**Admin**

| Path | Content |
|---|---|
| `/etc/caramos-business/admin-box.key`, `admin-tls.key` | 0600 |
| `/etc/caramos-business/admin-tls.pem` | 0644 |
| `/var/lib/caramos-business/admin/` | `root:sudo` 0750 |
| `commands.json` | `{"seq": N, "commands": [envelopes]}` |
| `results.json` | `{"<command id>": {"<machine_id>": result + "received"}}` |
| `inventory/<machine_id>.json` | the last inventory |
| `assets.json` | per machine, entered by the admin: `{"asset_code", "purchase_date", "price_vnd", "warranty_until", "holder", "location", "note"}` (dates `YYYY-MM-DD`, the price in đồng) |
| `help-requests.json` | the open help requests |
| `audit.jsonl` | the audit log |
| `health.json` | per machine: skew, since when updates and a restart waited, first time each problem was seen |
| `machines.json` | each entry gains `macs` and `mac_switches` (see "Cloned disks") |
| `secrets.json` | 0600: the Wi-Fi passphrases by SSID |
| `removed.json` | the machines taken out, released for 30 days |
| `/run/caramos-business/remote-help.conf` | 0600, while remote help runs |

**Employee**

| Path | Content |
|---|---|
| `/etc/caramos-business/agent-box.key` | 0600 |
| `/var/lib/caramos-business/agent/effective.json` | 0644: this machine's effective settings, for the session parts and the window |
| `/var/lib/caramos-business/agent/commands.json` | 0600: `{"machine_id", "last_seq", "done": [ids]}` |
| `/var/lib/caramos-business/agent/managed.json` | 0600: what the daemon changed, so it can put it back: the earlier Firefox policies, queues, rules, profiles, ufw |
| `/var/lib/caramos-business/agent/clone.json` | 0644, only on a cloned disk: `{"paired_on", "this_machine"}` |
| `/etc/caramos-business/agent.json` | gains `machine_id_os`, the `/etc/machine-id` at pairing |
| `/run/caramos-business/inbox/<uid>/` | the relay's inbox (root's) |
| `$XDG_RUNTIME_DIR/caramos-business/` | `status.json`, `session.pid`, `taken`, `outbox/`, `remote-help/` |
| `~/.config/caramos-business/state.json` | per user: the wallpaper set, launchers copied, bookmarks added, screen lock values before, the notice shown and the sections it listed |

**The service unit** `caramos-business-agent.service` runs the daemon as root with `PrivateTmp=true` and
`StateDirectory`, and nothing else from systemd's hardening, each of which breaks something:

- `ProtectSystem` (any level): `/etc/hosts` is replaced by a rename in `/etc`, browser policy folders are made when a
  browser appears, NetworkManager profiles, udev and polkit rules, ufw's files; and `update` and `apps` run apt/dpkg,
  which write everywhere. Seen: the hosts block failed with "Read-only file system" under the 0.1 unit.
- `ProtectHome`: the daemon reads and removes files in `/run/user/<uid>/caramos-business/` (`yes` hides `/run/user`,
  `read-only` stops the removals).
- `ProtectKernelTunables`, `PrivateDevices`: `rtcwake` (`/dev/rtc0`, `/sys/class/rtc`), `udevadm trigger` (writes
  `uevent` in `/sys`), `smartctl` and `dmidecode` (devices).
- `ProtectKernelModules`, `NoNewPrivileges`, `RestrictSUIDSGID`: kernels and setuid packages installed by `update`
  and `apps`, and their maintainer scripts.

---

# Part 3: version 0.3

Version 0.3 adds, in the order the owner approved (2026-11-22): pairing that a LAN attacker cannot abuse, the licence
report, enrolment without a code and prepared disk images, shared machines (guest session, restore on reboot), the
security report, helpdesk tickets, asset lifecycle and handover, and managed snapshots. Its scope is the draft
`reports/caramos-business-0.3-spec-draft.md` with the coordinator's decisions of 2026-11-23. This part is the contract
for both builders: the Python side (admin server, helper, windows) and the Rust agent. "Verified" means checked on
2026-11-23: on the test VM caramxfce1.4.0 (overlayroot, GRUB, Timeshift; reverted afterwards) or in Ubuntu 24.04
containers (python3-spake2, stunnel, TigerVNC, iptables, apt-cache).

The rules of part 2 stay:
- everything is opt-in: no new feature changes a machine until the admin turns it on;
- no covert monitoring: no screens, keystrokes, browsing history, location or messages;
- no arbitrary command: only the fixed actions and sections listed;
- whatever the agent changes is put back when a section goes away, when the machine leaves, and when the company
  removes it.

## Changes to parts 1 and 2

No 0.2 was released, so these need no compatibility:

- **Pairing:** the code is random for each pairing session and checked with SPAKE2 (`/pair/start`, `/pair/finish`).
  Part 1's `pairing_code(key)`, `GET /key` and `/register` with a code are gone; `/register` now only enrols with a
  token from an enrolment file.
- **`GET /policy` and `GET /files/<sha256>`** need part 2's HMAC headers: only paired, approved machines read the
  company's settings.
- **Approval:** with "Duyệt từng máy" on, a new machine (either pairing path) waits until the admin approves it.
- **Removal:** "Gỡ khỏi công ty" sends a signed removal notice. The agent then puts back everything, ufw included, and
  forgets the pairing. Part 2's 30-day policy entry with every section `null` is gone.
- **Delivery:** `/wait` no longer delivers a command that the machine already answered.
- **Remote help:** a pre-shared key for each session (TLS 1.3 PSK) replaces the admin's certificate, and the viewer's
  port is closed to the LAN. `remote_help_cert`, `admin-tls.pem` and `admin-tls.key` are gone.
- **Inboxes** become readable only by their user (they now carry remote help keys and ticket notes).
- **Policy format stays 2.** The new sections `shared` and `snapshots` are optional, like part 2's. A 0.2 agent cannot
  fetch from a 0.3 admin (its `GET /policy` has no HMAC), so both sides upgrade together; pairings made with 0.2 keep
  working (the keys do not change).
- Health, inventory, capabilities and the employee UI contract gain fields and kinds (below).

## HTTP endpoints of 0.3

All paths start with `/caramos-business/v1`. "HMAC" means part 2's `X-Caramos-*` headers.

| Method and path | Who | Body / answer |
|---|---|---|
| `GET /hello` | anyone | part 1 |
| `POST /pair/start` | anyone, only while pairing is open | see "Pairing with a code" |
| `POST /pair/finish` | anyone, only while pairing is open | see "Pairing with a code" |
| `POST /register` | anyone holding an enrolment token | see "Enrolment file" |
| `GET /policy` | a paired, approved machine (HMAC) | part 2's signed policy; a removed machine gets its removal notice |
| `GET /files/<sha256>` | a paired, approved machine (HMAC) | part 1 |
| `GET /wait` | a paired, approved machine (HMAC) | part 2, plus `"tickets": N` |
| `GET /tickets` | a paired, approved machine (HMAC) | the machine's tickets, signed |
| `POST /checkin`, `/inventory`, `/result` | a paired, approved machine (HMAC) | part 2 |
| `POST /help` | a paired, approved machine (HMAC) | part 2's body; the answer names the ticket |

- **401:** missing or wrong HMAC, unknown machine (part 2).
- **403 `{"error": "pending"}`:** a machine waiting for approval, on every HMAC endpoint.
- **410, no body:** a removed machine, on every HMAC endpoint except `GET /policy`. The agent then fetches `/policy`
  at once; a 410 alone is never trusted (anyone can send one).

## Pairing with a code (SPAKE2)

Part 1 derived the code from the admin's public key, which `GET /key` gave to anyone. Two holes followed:
- any device on the LAN could compute the code and register while pairing was open, and then receive the Wi-Fi
  passphrases sealed for it;
- an active attacker could grind an Ed25519 key with the same code (10⁶ tries, seconds) and pose as the admin.

0.3 uses a random code and a password-authenticated key exchange, so the code itself never travels.

- **The code:** when the admin opens pairing, the helper draws `secrets.randbelow(1_000_000)`, written as 6 digits
  with leading zeros, and writes `/run/caramos-business/pairing.json` (`root:sudo` 0640, replacing part 1's
  `pairing-until`): `{"code": "482913", "until": <unix time>}`. The helper's `pairing open` answers `{"code",
  "until"}`; the window shows the code and reads the file again after a restart. Closing pairing, its 10 minutes
  running out, or 20 failed confirmations removes the file; the next opening draws a new code.
- **Library:** python3-spake2 0.8 (Ubuntu noble universe, depends on python3-hkdf), group Ed25519 (its default).
  - Employee: `SPAKE2_A(code, idA=b"caramos-business employee", idB=b"caramos-business admin")`.
  - Admin: `SPAKE2_B` with the same three arguments.
  - `code` is the six ASCII digits as bytes.
  - `start()` returns 33 bytes: the side byte `A` or `B`, then a 32-byte group element. `finish(other)` returns the
    32-byte key `K`, raises `OffSides` when given a message from its own side, and raises nothing for a wrong code
    (the keys just differ). `entropy_f=` (default `os.urandom`) takes a function of `n` returning `n` bytes: the
    test vectors fix it. Verified.
- **`POST /pair/start`** `{"msg": "<base64 of the employee's 33 bytes>"}` → 200 `{"session": "<uuid4>", "msg":
  "<base64 of the admin's 33 bytes>", "admin_name", "admin_key": "<base64 Ed25519 public key>", "admin_box_key":
  "<base64 X25519 public key>"}`.
  - 403 `{"error": "pairing closed"}` while pairing is closed.
  - 400 when `msg` is not 33 bytes starting with `A`, or `finish` raises.
  - The admin computes `K` at once and keeps `{session: K, msg_a, msg_b, started}` in memory for 60 s: at most 16
    sessions at a time and 2 per IP address (429 beyond), so that nobody can hold the pairing window alone.
- **Confirmation keys:** `k_employee = HKDF-SHA256(ikm=K, salt=b"caramos-business/3", info=b"pair employee",
  length=32)`; `k_admin` is the same with `info=b"pair admin"`.
- **Transcript `T`:** the UTF-8 bytes of `json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",",
  ":"))`, where `obj` is `{"kind": "caramos-business/3 pair", "session", "msg_a", "msg_b", "admin_name",
  "admin_key", "admin_box_key", "machine_box_key", "machine"}`. The messages and keys are the base64 strings as sent;
  `machine` is MACHINE exactly as the employee sends it, before the admin checks it.
- **`POST /pair/finish`** `{"session", "machine": MACHINE, "box_key": "<base64 X25519 public key>", "confirm":
  "<base64 HMAC-SHA256(k_employee, T)>"}`:
  - unknown or expired session: 403 `{"error": "session"}`;
  - wrong `confirm` (compared in constant time): 403 `{"error": "wrong code"}`, the session is dropped and the failure
    counts; 20 failures in one pairing session close pairing;
  - right `confirm`: the admin registers the machine (see "Approval"), writes an audit line, and answers 200
    `{"machine_id", "state": "approved" or "pending", "confirm": "<base64 HMAC-SHA256(k_admin, T + b"\n" +
    machine_id + b"\n" + state)>"}` (`machine_id` and `state` as ASCII).
- **The employee confirms first.** If the admin's confirmation came with `/pair/start`, an attacker could check one
  guess per start offline and never call `/pair/finish`, so no failure would be counted. This way a guess can only be
  tested by sending a confirmation the admin counts. An attacker posing as the admin gets one guess (one in a
  million) per pairing attempt; a passive listener learns nothing about the code.
- **Employee (helper `pair IP CODE`):**
  - It makes a new box key, runs the exchange against `http://IP:47022`, and checks the admin's `confirm`.
  - Only then does it pin `admin_key` and write agent.json, `agent-box.key`, `admin.json` and `machine_id_os` as in
    part 2 (agent.json does not change), and enable the agent. The agent keeps taking the admin's box key from the
    signed policy, as in part 2.
  - A wrong admin confirmation writes nothing: "Máy quản lý trả lời không khớp mã. Hãy kiểm tra lại máy quản lý và
    mã."; 403 wrong code: "Mã không đúng."; 403 pairing closed: "Máy quản lý chưa mở thêm máy."
  - The window no longer checks the code itself before asking for the password.
- **Test vectors:** `v3/pair-spake2.json` holds a run with fixed entropy: both messages, `K`, both confirmation keys,
  `T` and both confirmations. Both ends are Python, so the Python tests also run the two roles against each other
  through the real server, and a wrong code must end in 403 and a counted failure. The Rust agent has no part in
  pairing.

## Enrolment file

For machines added in bulk, the admin makes a file that adds machines without a code (on a USB stick, or baked into
a disk image).

- **Making it:** under "Thêm máy", "Tạo tệp ghép máy" asks for a department (or none), a lifetime (1–30 days, default
  7), a number of uses (1–500, default 30), an optional host name prefix, and where to save. The helper's
  `enroll-token create FILE` (stdin `{"department", "days", "max_uses", "hostname_prefix"}`, FILE opened as the
  `PKEXEC_UID` user as `backup` does) writes `caramos-business-enroll.json` and answers `{"token_id", "expires"}`:

  ```json
  {"format": 1, "kind": "caramos-business-enroll", "admin_url": "http://192.168.1.5:47022",
   "admin_name": "quan-ly", "admin_key": "<base64 Ed25519 public key>",
   "fingerprint": "<16 hex>", "department": "ke-toan", "department_name": "Kế toán",
   "token_id": "<16 hex>", "token": "<base64 of 32 random bytes>", "expires": "<ISO 8601>", "max_uses": 30,
   "hostname_prefix": null}
  ```

  - `department` may be null.
  - `hostname_prefix` is null or `[a-z0-9-]{1,20}`: for disk images (see "Enrolment at first boot").
  - The window warns that whoever holds the file can add machines until it expires or its uses run out, and lists the
    tokens with their uses, lifetime and a "Thu hồi" button (helper `enroll-token revoke TOKEN_ID`).
- **What the admin keeps** (it never keeps the token):
  - `enroll-tokens.json` (`root:sudo` 0640): `{"<token_id>": {"created", "by", "department", "expires", "max_uses",
    "uses", "revoked": null or ISO, "failures", "machines": [ids]}}`;
  - `enroll-keys.json` (0600 root): `{"<token_id>": "<hex of proof_key>"}`, where `proof_key =
    HKDF-SHA256(ikm=token, salt=b"caramos-business/3", info=b"enroll", length=32)`. The proof key is enough to check
    and to make proofs, so it is secret; it does not reveal the token.
- **`POST /register`** (no HMAC; pairing need not be open): `{"token_id", "time": <unix seconds>, "machine": MACHINE,
  "box_key": "<base64>", "proof": "<base64 HMAC-SHA256(proof_key, E)>"}`.
  - `E` is the UTF-8 compact JSON (sorted keys, as `T`) of `{"kind": "caramos-business/3 enroll", "token_id",
    "time", "admin_key", "machine_box_key", "machine"}`, with `admin_key` the base64 key from the file.
  - Checks: the token exists, is not revoked or expired and has uses left (else 403 `{"error": "token"}`); `time` is
    within 10 minutes of the admin's clock; the proof matches (else 403 `{"error": "proof"}`, counted in `failures`;
    20 disable the token and write an audit line); the same proof was not used in the last 20 minutes (a replay: 403
    `{"error": "proof"}`, not counted).
  - Then the admin registers the machine (see "Approval") with `via: "enroll:<token_id>"`, counts the use, puts the
    machine into the token's department (a pending machine keeps it in its entry's `department` until approval), and
    answers 200 `{"machine_id", "state", "confirm": "<base64
    HMAC-SHA256(proof_key, E + b"\n" + machine_id + b"\n" + state)>"}`.
  - A sniffed request cannot enrol another machine: the proof binds `box_key` and MACHINE, and the machine's private
    box key never travels.
  - With a department, the server adds the machine to `members` and signs the policy again (serial + 1), as part 2's
    server does for sealed secrets.
- **Employee:**
  - On a machine with the package and no role, the window looks for `/media/<user>/*/caramos-business-enroll.json`
    (one level below each mount) when it opens and when removable media appear; the user can also pick a file.
  - It shows the admin's name and fingerprint, the department name and the expiry, and asks to confirm.
  - The helper's `pair-file PATH` reads the file as the `PKEXEC_UID` user, checks `format`, `kind`, `expires` and the
    key lengths, and pins `admin_key` from the file (the admin made it).
  - It sends `/register` to `admin_url`, or, with no answer there, to the address that discovery finds for
    `fingerprint`.
  - It checks the admin's `confirm` (a stranger answering cannot make it), then writes the pairing as `pair` does.
- **Prepared disk images:** see "Enrolment at first boot".

## Approval ("Duyệt từng máy")

- An admin option, off by default: `/var/lib/caramos-business/admin/options.json` `{"approve_machines": bool}`,
  written by the helper's `options` (JSON on stdin). The switch is on the "Thêm máy" page.
- `machines.json` entries gain `"state": "pending"` or `"approved"` (absent means approved, as for 0.2 entries) and
  `"via": "code"` or `"enroll:<token_id>"`.
- With the option on, both pairing paths register the machine as `pending`. A pending machine gets 403 `{"error":
  "pending"}` on every HMAC endpoint, is left out of `members` and of the sealed secrets, and receives nothing.
- The window lists pending machines first ("Chờ duyệt": name, IP, MAC, time, path), with "Duyệt" and "Từ chối".
  - Helper `approve ID`: the state becomes `approved`; the admin signs the policy again when the machine needs sealed
    secrets or a department membership.
  - Helper `reject ID`: the entry is deleted (no removal notice: the machine never got anything); its requests then
    get 401.
  - Both are audited.
- **Agent:** it writes `/var/lib/caramos-business/agent/approval.json` (0644) `{"state": "pending" or "approved",
  "since": "<ISO>"}` when it gets 403 pending, or its first policy. While pending it asks for the policy every minute
  and does nothing else. The employee window shows "Đang chờ máy quản lý duyệt máy này" while the state is
  `pending`.

## Enrolment at first boot, and prepare-image

Both belong to the Python helper; the Rust agent has no part in them.

- **`caramos-business-helper prepare-image`**, stdin `{"enroll_file": "<path>" or null}`, from the window's machine
  page ("Chuẩn bị tạo ảnh đĩa", with a confirmation). It prepares a machine whose disk will be copied to others
  (computer labs, Clonezilla). It refuses on a frozen machine ("Hãy tắt chế độ đóng băng trước").
  1. if the machine is paired, it leaves first (part 2's `leave`), so that the image holds none of the company's
     settings;
  2. it removes `/etc/caramos-business/agent.json`, `agent-box.key` and everything in
     `/var/lib/caramos-business/agent/`;
  3. it empties `/etc/machine-id` (zero bytes, not deleted, so that systemd makes a new one at the next boot), and
     removes `/var/lib/dbus/machine-id` when it is a regular file (a link to /etc/machine-id stays);
  4. it removes `/etc/ssh/ssh_host_*` when openssh-server is installed;
  5. with an enrolment file, it checks the file, copies it to `/etc/caramos-business/enroll-on-boot.json` (0600) and
     enables `caramos-business-enroll.service`; it sets the role to `employee`.

  The window then says to shut down now and copy the disk without starting this machine again: started once, it
  would make its machine id and enrol itself, and its copies would share that pairing.
- **`caramos-business-enroll.service`** (shipped disabled; prepare-image enables it):

  ```ini
  [Unit]
  Description=CaramOS Business: enrol this machine with the company's admin machine
  ConditionPathExists=/etc/caramos-business/enroll-on-boot.json
  Wants=network-online.target
  After=network-online.target
  Before=caramos-business-agent.service
  StartLimitIntervalSec=0

  [Service]
  Type=oneshot
  ExecStart=/usr/lib/caramos-business/caramos-business-helper enroll-on-boot
  Restart=on-failure
  RestartSec=60

  [Install]
  WantedBy=multi-user.target
  ```

  `StartLimitIntervalSec=0` lets it try again every minute for as long as the admin does not answer.
  The host name is set earlier, before the login screen, by `caramos-business-hostname.service` (see "Changes
  during implementation", the end-to-end pass).
- **`caramos-business-helper enroll-on-boot`** (root only; refused under pkexec):
  - When `/etc/ssh/sshd_config` exists and a host key is missing, it runs `ssh-keygen -A` and `systemctl try-restart
    ssh.service`. Until then sshd may refuse connections, for about a minute after the first boot.
  - With `hostname_prefix`, it sets the host name to `<prefix>-<first 6 hex digits of the new machine id>` (hostnamectl,
    and the `127.0.1.1` line of /etc/hosts), so that the copies are told apart.
  - It runs `pair-file` with the stored file; `machine_id_os` is the new machine id.
  - Success: it removes `enroll-on-boot.json`, disables the unit and starts the agent.
  - 403 token (expired, used up, revoked): it gives up, writes `/var/lib/caramos-business/agent/enroll-failed.json`
    `{"time", "error"}` (0644) and disables the unit. The window shows "Tệp ghép máy đã hết hạn hoặc hết lượt: hãy ghép
    máy này bằng mã."
  - No answer: it exits 1 and systemd tries again a minute later. The window shows "Đang chờ máy quản lý để tự ghép".
- **Later, not in 0.3:** an unattended install USB (Ubiquity `automatic-ubiquity` with a preseed), which needs an ISO
  remaster on the admin machine.

## Removal from the company

- **"Gỡ khỏi công ty"** (helper `forget-machine ID`) now also signs a removal notice, and keeps the machine in
  `removed.json` for 365 days:

  ```json
  {"<machine_id>": {"time": "<ISO>", "name": "<host name>", "box_key": "<base64>",
                    "notice": {"notice": "<text>", "signature": "<base64>"}}}
  ```

  The notice text is compact JSON `{"kind": "removed", "machine_id", "admin": "<admin host name>", "time"}`, signed
  with the admin key like a command.
- **Server:** a request from a machine in `removed.json` authenticates with the kept box key. `GET /policy` answers
  200 with the stored `{"notice", "signature"}` (no `policy` key); every other HMAC endpoint answers 410. After 365
  days the entry goes and the machine gets 401. A removed machine never reads the company's current settings.
- **Agent:** an answer with `notice` instead of `policy`:
  - It verifies the signature with the pinned key, then checks `kind == "removed"` and that `machine_id` is its own.
    A notice that fails a check is logged and ignored.
  - On a valid notice it runs the leave routine of part 2's `caramos-business-agent leave`, steps 2–4, with ufw put
    back too (0.3 puts back everything on removal). On a frozen machine it runs the frozen variant instead (see
    "Leaving and removal of a frozen machine").
  - It removes agent.json, agent-box.key, `policy.json`, `effective.json`, `commands.json`, `approval.json`,
    `clone.json`, `tickets/` and `managed.json` (the last once everything is back), and writes
    `/var/lib/caramos-business/agent/removed.json` (0644) `{"admin_name", "time"}`.
  - Then it runs `systemctl disable caramos-business-agent.service` and exits 0.
- **Employee window:** with role `employee`, no agent.json and `removed.json` present, it shows the pairing page with
  this at the top: "Công ty đã gỡ máy này khỏi máy quản lý {admin_name} lúc {HH:MM} ngày {D/M}. Các thiết lập của
  công ty đã được gỡ khỏi máy." It no longer says "Đã kết nối với …". The helper's `pair` and `pair-file` remove
  `removed.json` and `enroll-failed.json`.
- **Leaving from the employee side** stays part 2's `leave`, with ufw put back as before.

## Commands: no second delivery

`/wait` leaves out every command for which `results.json` already holds a result from the asking machine. A frozen
machine's `commands.json` goes back to the disk's copy at each reboot (see "Shared machines"), so without this rule it
would run again the commands it had answered. Part 2's lifetime rules and the rule against commands from before the
boot still hold.

## Licence report

- **Agent:** each `inventory.apps[]` entry gains three keys. Strings are at most 200 characters.
  - `package`: the deb package that owns the app's `.desktop` file (`dpkg -S`), or the Flatpak app id.
  - `licence`: the licence as the package states it, else `"unknown"`.
    - deb: `/usr/share/doc/<package>/copyright` when it is machine-readable (its first line starts with `Format:` and
      holds `copyright-format/1.0`): the first line of the `License:` field of the stanza whose `Files:` is `*`. These
      are Debian short names such as `GPL-2+` or `Expat`, not always SPDX. Else the `<project_license>` of the app's
      AppStream file (`/usr/share/metainfo/*.xml`, matched by the desktop id).
    - Flatpak: the `<project_license>` of
      `/var/lib/flatpak/app/<id>/current/active/files/share/metainfo/<id>.metainfo.xml` (or `.appdata.xml`, or under
      `share/appdata/`).
  - `origin`, from one `apt-cache policy` run (its "Package files" part) and one `apt-cache policy <package…>` run for
    all deb packages. The version marked `***` is the installed one; its first source line that is not
    `/var/lib/dpkg/status` names the archive, and the "Package files" line with the same URI and `suite/component`
    gives its `release` fields (`o=` origin, `c=` component) and its `origin <host>` line. Verified on real output:
    - `o=Ubuntu` → `ubuntu-main`, `ubuntu-universe`, `ubuntu-restricted` or `ubuntu-multiverse` (from `c=`);
    - `o=linuxmint` → `mint`;
    - `o=LP-PPA-vietnamlinuxfamily-caram-os` → `caramos-ppa`;
    - any other `o=` → `third-party:<host>`, the host of the `origin` line (for example `third-party:dl.google.com`,
      whose `o=` is `Google LLC`);
    - only `/var/lib/dpkg/status` → `local-deb`;
    - Flatpak: `flathub` when the app's origin remote is named `flathub`, else `flatpak:<remote name>`.
- **Admin:** the inventory check keeps the three keys (part 2 dropped unknown keys). A machine appears only while its
  `inventory` section is on; the page names the machines without it.
- **Classes**, worked out by the admin for each app:
  - `free`: every licence id in `licence` is in the admin's list of free licences (OSI- or FSF-approved, in both their
    Debian short names and SPDX forms; the list is in `licences.py`);
  - `freeware` or `commercial`: only when the App Center catalog says so for the app's `package`;
  - else `unknown`.

  The catalog's word wins over the licence string (a deb with a free licence file can hold a proprietary app).
- **App Center catalog field:** every app gets `"licence": {"class": "free" or "freeware" or "commercial" or
  "unknown", "note": {"vi": "", "en": ""}}`. The App Center's tests check that every app has one. The admin reads
  the installed catalog, `/usr/share/caramos-app-center/catalog.json`. A first proposal, to be checked against each
  vendor's terms when the field is added:
  - free: ONLYOFFICE, LibreOffice, Brave, Firefox, Telegram, Teams for Linux, VLC, OBS Studio, RustDesk, GIMP,
    Thunderbird, Inkscape, Kdenlive, GCompris, Tux Paint, Klavaro, KTurtle, TurboWarp, Thonny, Stellarium, Remmina,
    CaramOS Doanh nghiệp;
  - freeware: Google Chrome, Cốc Cốc, Microsoft Edge, Zalo, Zoom, Discord, Microsoft Core Fonts, Obsidian;
  - commercial: GeoGebra (free only for non-commercial use);
  - unknown: WPS Office.
- **Register of bought licences** (admin only): `licences.json` `[{"id", "product", "seats", "expires", "invoice",
  "note", "match": [app ids or package names]}]`, edited through the helper's `licences` (the whole list on stdin).
  The report compares `seats` with the number of machines that have a matching app.
- **Page "Bản quyền phần mềm":**
  - totals by class, then apps with their machine counts, `unknown` and `commercial` first;
  - the register;
  - the fixed sentence: "Báo cáo này liệt kê phần mềm tìm thấy trên các máy; nó không xác nhận việc sử dụng đã đủ
    bản quyền."
  - Export to XLSX: a summary sheet with signature lines for "Người lập" and "Giám đốc", and a sheet "Báo cáo phần
    mềm" per machine.
  - Export to PDF: the XLSX converted (see "Reports as PDF").
- **Reports as PDF** (licence, security, handover): `soffice --headless --convert-to pdf --outdir DIR FILE` when
  `soffice` is on the PATH; else `flatpak run --command=soffice org.libreoffice.LibreOffice --headless --convert-to
  pdf …` when that Flatpak is installed (App Center installs LibreOffice as a Flatpak; see "Changes during
  implementation": `flatpak run org.libreoffice.LibreOffice --headless …`); else the window offers only
  the XLSX or DOCX and says why.

## Shared machines (`shared`)

```json
"shared": {"guest": true, "freeze": true, "maintenance": {"days": [7], "time": "02:00", "max_minutes": 60},
           "low_memory_ok": false}
```

| Key | Value |
|---|---|
| `guest` | bool: a guest session on the login screen |
| `freeze` | bool: everything changed on the machine is undone at reboot |
| `maintenance` | null, or `{"days": [1-7], "time": "HH:MM", "max_minutes": 15-240}`; `max_minutes` defaults to 60 |
| `low_memory_ok` | bool: the admin's "Tôi hiểu" for freezing a machine with less than 3 GiB of RAM |

- **Admin rules** (it never signs otherwise):
  - `freeze: true` needs `maintenance` (a frozen machine is updated only then);
  - for every machine, and for a machine in each department or in none, the effective settings never hold
    `shared.freeze: true` together with `folders.tidy: true`, nor together with a non-null `snapshots`;
  - the window warns about machines whose `health.memory_mb` is below 3072 while `low_memory_ok` is false.
- **What the window fills in:** guest on, freeze off, maintenance Sunday 02:00 for 60 minutes.
- **Agent rules:** it does not freeze when its effective settings also hold `folders.tidy: true` or `snapshots`, or
  when `MemTotal` is below 3 GiB without `low_memory_ok`. It reports `applied.shared: "failed: <reason>"` and applies
  the rest (`guest`).

### Guest session

- The daemon writes `/etc/lightdm/lightdm.conf.d/71-caramos-business-guest.conf`:

  ```ini
  # Managed by CaramOS Doanh nghiệp (caramos-business-agent): changes here are replaced.
  [Seat:*]
  allow-guest=true
  greeter-allow-guest=true
  ```

  It removes the file when `guest` is false or the section goes away.
- LightDM reads it when it starts: it takes effect at the next boot, and the window says so.
- The guest account and the wiping of its home at logout are LightDM's own (`guest-account` script).
- To verify at implementation, on both editions: that slick-greeter (Cinnamon) and the Xfce edition's greeter show the
  guest button, and that the script exists on CaramOS 1.4.0. When either is missing, the section reports `failed:
  <what is missing>`.

### Freeze (overlayroot)

- **On** (in an unfrozen boot, when `freeze` comes into effect):
  1. `apt-get install -y overlayroot` when it is missing (Ubuntu main; its trigger rebuilds the initramfs);
  2. it writes `/etc/grub.d/42_caramos-business-maintenance` (0755; the exact script is
     `v3/expected-42_caramos-business-maintenance`). The script adds the entry `CaramOS (bảo trì)` with id
     `caramos-business-maintenance`: the newest kernel (`readlink -f /boot/vmlinuz`, `/boot/initrd.img`), the root
     and command line of the normal entry, plus `overlayroot=disabled caramos-business.maintenance=1`;
  3. it writes `/etc/default/grub.d/71-caramos-business.cfg` with `GRUB_RECORDFAIL_TIMEOUT=0`, then runs `update-grub`;
  4. it writes `/etc/overlayroot.local.conf` `overlayroot="tmpfs:swap=1,recurse=0"`, keeping an earlier file's
     contents in `managed.json` to put back.

  It takes effect at the next boot; the window says so.
- **Verified:**
  - overlayroot's initramfs script reads `/etc/overlayroot.conf` and `/etc/overlayroot.local.conf` from the real root
    at each boot, so changing them needs no initramfs rebuild.
  - Frozen, `/` is `overlayroot` (type overlay, upper layer a tmpfs of half the RAM: 985 MB on a 2 GB machine), and
    the disk is at `/media/root-ro`, read-only. A file written while frozen was gone after the reboot.
  - GRUB's `recordfail`: GRUB saves `recordfail=1` on the disk at each boot, and the booted system clears it, but a
    frozen system clears it only in the overlay. Without `GRUB_RECORDFAIL_TIMEOUT=0`, GRUB showed its menu for 30 s
    at every frozen boot; with it, the boot went straight on.
- **Each frozen boot** (the daemon sees overlayroot on `/`):
  - it masks the update timers for this boot: `systemctl mask --runtime --now caramos-ota-check.timer apt-daily.timer
    apt-daily-upgrade.timer` (verified: they show `masked-runtime`; the masks live in /run and vanish at reboot);
  - the `apps` section waits for the maintenance boot, and the `update` command answers `ignored` "máy đang đóng
    băng: cập nhật chạy trong giờ bảo trì": an install into the overlay would be repeated at every boot;
  - the daemon's own state (`commands.json`, `managed.json`, `effective.json`) is the disk's copy again. Part 2's
    rule against commands from before the boot, the rule against a second delivery, and a fresh policy fetch cover
    that;
  - each user, at each login, gets `caramos-business --prompt frozen`: "Máy này tự xóa mọi thay đổi khi khởi động lại.
    Hãy lưu tệp vào ổ dùng chung hoặc USB."
- **Off** (the section goes away, or `freeze` becomes false):
  - On a frozen machine the daemon runs `overlayroot-chroot rm -f /etc/overlayroot.local.conf`, which removes the file
    on the disk. Verified: the next boot was unfrozen; overlayroot-chroot also printed a harmless "umount:
    /media/root-ro/proc: target is busy". The machine stays frozen until its next reboot, and the window says so.
  - In the next unfrozen boot (and in any unfrozen boot where freeze is not wanted) it removes the GRUB script and the
    `grub.d` drop-in and runs `update-grub`.
  - Never `update-grub` inside overlayroot-chroot. Verified: `grub-probe` cannot find the device there ("failed to get
    canonical path of /dev/vda3").

### Maintenance window

- **Waking:** before any shutdown the daemon sets the RTC alarm for the earliest of part 2's `wake` and the next
  maintenance time (`rtcwake -m no -t`). The admin server sends magic packets 5 minutes before `maintenance.time` on
  `maintenance.days`, as it does for `wake`, to machines whose effective settings freeze.
- **At `maintenance.time`** on a frozen machine:
  - if a graphical session is active on seat0, the daemon tries again every 15 minutes until `max_minutes` after
    the time, and then skips the day (`maintenance_result: "bỏ qua: có người đang dùng"`);
  - otherwise it runs `overlayroot-chroot grub-reboot caramos-business-maintenance`, then `systemctl reboot`.
- **Verified:** `grub-reboot` from the frozen system wrote `next_entry` only into the overlay's grubenv (lost at
  reboot, and grub-probe complained "failed to get canonical path of `overlayroot'"). `overlayroot-chroot grub-reboot
  caramos-business-maintenance` wrote it on the disk (a harmless grub-probe message about /dev/vda3); GRUB booted the
  entry once and cleared `next_entry`. A read-write remount of `/media/root-ro` was not needed.
- **The maintenance boot** is recognised from `caramos-business.maintenance=1` in `/proc/cmdline`. Verified: `/` was
  the disk's ext4, read-write, with no `/media/root-ro`. The daemon:
  1. writes `/run/nologin` ("Máy đang bảo trì, vui lòng chờ ít phút."), so that nobody logs in (LightDM and the text
     consoles use pam_nologin);
  2. arms a limit: `max_minutes` after the boot it reboots whatever is still running;
  3. fetches the policy and applies the system sections, which now persist on the disk;
  4. runs part 2's `update` steps (`caramos-ota --check`, then apt's security updates), and the `apps` section;
  5. writes `/var/lib/caramos-business/agent/maintenance.json` (0644) `{"last": "<ISO start>", "finished": "<ISO>",
     "result": "<short Vietnamese text>"}`;
  6. reboots: GRUB's default entry boots frozen again.

  When the fetched policy no longer freezes the machine, the daemon puts the freeze back (the files, `update-grub`),
  removes `/run/nologin`, and does not reboot.

### Leaving and removal of a frozen machine

Whatever is put back while frozen is lost at reboot, and the disk still holds the company's settings from the last
maintenance boot. So `caramos-business-agent leave` (run by the helper), and the daemon on a removal notice, do this
on a frozen machine:

1. `overlayroot-chroot rm -f /etc/overlayroot.local.conf`;
2. they write `/var/lib/caramos-business/agent/leave-pending.json` `{"reason": "leave" or "removed", "admin_name",
   "time"}` on the disk, through overlayroot-chroot (for example `overlayroot-chroot tee <path>` with the JSON on
   stdin);
3. the normal leave on the overlay, so that the running session is clean at once. What the helper's `leave` then
   removes (agent.json and the rest) is removed only from the overlay; the disk keeps the pairing until step 5;
4. `caramos-business-agent leave` prints `reboot needed` and exits 0, the helper answers `{"reboot": true}`, and the
   window asks for a reboot: "Máy cần khởi động lại để gỡ hẳn thiết lập của công ty.";
5. in the next, unfrozen, boot the daemon finds `leave-pending.json` before anything else and, without the network,
   runs the leave routine on the disk, removes the GRUB script and drop-in (`update-grub`) and the pairing, writes
   `removed.json` when the reason is `removed`, removes the marker, and disables itself.

## Security report

- **Health gains** (agent, collected at most every 30 minutes like part 2's):
  - `memory_mb`: `MemTotal` in MiB;
  - `encryption`: `"luks"` when the device under `/` has a `crypt` ancestor in `lsblk -J -o NAME,TYPE,MOUNTPOINTS`
    (frozen, the device mounted at `/media/root-ro`), `"none"` when it has none, `"unknown"` when lsblk fails;
  - `screen_lock_on`: the value from the status of the user at the screen (the active seat0 session), null without
    one. The session part adds `"screen_lock_on": bool` to `status.json`:
    - Cinnamon: `org.cinnamon.desktop.screensaver lock-enabled` and `org.cinnamon.desktop.session idle-delay` above 0;
    - Xfce: light-locker running, `apps.light-locker lock-after-screensaver` above 0, and `blank-on-ac` above 0;
  - `usb_storage`: `"unlocked"` while a `usb_unlock` runs, else the effective `usb.storage`, `"allow"` when not
    managed;
  - `frozen`: `/` is overlayroot now; `freeze_configured`: the agent's `overlayroot.local.conf` is on the disk
    (frozen, under `/media/root-ro`);
  - `last_maintenance` (ISO or null) and `maintenance_result` (string, ≤ 200), from `maintenance.json`;
  - `last_snapshot` (ISO or null) and `snapshot_space_mb` (int or null), see "Managed snapshots".
- **New problems** (`health.py`):
  - `snapshot_old`: `snapshots` in effect and the last snapshot older than twice its period (daily 2 days, weekly 14,
    monthly 62), or none 2 periods after the section came on;
  - `maintenance_late`: freeze in effect and no maintenance for 8 days (or none 8 days after freeze came on);
  - `freeze_pending`: `frozen` and `freeze_configured` differ for more than a day (a reboot is needed).
- **Page "Báo cáo an toàn"** (under Bảo mật):
  - a table per machine: firewall, security updates waiting and since when, reboot required, screen lock, USB storage,
    encryption, frozen, last maintenance, last snapshot, last seen, problems;
  - company totals;
  - the audit log extract for a chosen period;
  - the transparency paragraph to paste into the internal labour rules (Law 91/2025/QH15, article 25(3)(a));
  - exports to XLSX and PDF, with the fixed sentence "Báo cáo hiện trạng kỹ thuật; không phải chứng nhận đạt cấp độ
    an toàn thông tin nào."

## Helpdesk tickets

Help requests become tickets, kept on the admin in `tickets.json`:

```json
{"next": 8, "versions": {"<machine_id>": 7},
 "tickets": [{"id": "HT-0007", "machine_id": "...", "user": "lan", "note": "Máy in không in được", "created": "...",
              "status": "new", "assignee": "", "first_response": null, "closed": null,
              "notes": [{"time": "...", "by": "caram", "text": "...", "public": true, "status": "working"}],
              "snapshot": {"health": {}, "inventory_summary": {}}}]}
```

- `status` is `new`, `working`, `waiting` or `done`. Ids are `HT-` and at least 4 digits, from `next`.
- **`POST /help`** (part 2's body) creates a ticket with the machine's last health and inventory summary (model, CPU,
  memory, disks, CaramOS version) attached, and answers `{"ticket": "HT-0007", "tickets": <version>}`. Part 2's
  `help-requests.json` and its limits go; a machine may have at most 20 open tickets. Tổng quan shows the `new`
  tickets where it showed help requests, with the same notification and "Hỗ trợ" button.
- **Admin page "Phiếu hỗ trợ":**
  - filters by status, a detail view, status changes, notes (each marked public or internal), the assignee;
  - "Hỗ trợ từ xa" from a ticket (part 2's command);
  - a monthly XLSX: counts by status, the median time to the first response, and the list.

  Helper `ticket` (stdin `{"id", "status"?, "assignee"?, "note"?: {"text", "public"}}`) changes it, writes an audit
  line, sets `first_response` at the first public note or status change, sets `closed` when `done`, and increments the
  machine's version when the employee would see a difference (status, public note).
- **Why not a `ticket` command** (the draft's idea): a command lives at most 24 hours, so a machine that is off longer
  would never learn a status; a frozen machine forgets what it was told at every reboot; and the rule against a
  second delivery would not send it again. So the machine fetches its tickets instead, whenever their version moves.
- **`/wait`'s answer** gains `"tickets": N`, the machine's version (0 without tickets).
- **`GET /tickets`** (HMAC) → `{"tickets": "<text>", "signature": "<base64>"}`, signed with the admin key (the server
  signs it again for a machine when its version moves). The text is compact JSON:

  ```json
  {"kind": "tickets", "machine_id": "...", "version": 7, "issued": "...",
   "tickets": [{"id": "HT-0007", "user": "lan", "created": "...", "status": "working", "note": "...",
                "updates": [{"time": "...", "status": "working", "text": "Bên mình đang xem, chiều nay xong."}]}]}
  ```

  - It holds the open tickets and those closed in the last 30 days, at most 50.
  - `updates` are the public notes and status changes, oldest first, at most 20 per ticket; `text` is at most 500
    characters, and `status` is present when it changed.
  - Internal notes never leave the admin.
- **Agent:**
  - It fetches `/tickets` at start and whenever `/wait`'s `tickets` differs from the version it stored in
    `/var/lib/caramos-business/agent/tickets/version` (0600).
  - It verifies the signature with the pinned key and that `machine_id` is its own.
  - It writes each user's tickets to `/var/lib/caramos-business/agent/tickets/<uid>.json` (`{"version", "tickets"}`,
    only that user's), the user found by login name. Folder `root:root` 0755; file `root:<the user's primary group>`
    0640, so that it is root's and only that user can read it.
  - It writes the file only when the primary group is the user's own: the group has the user's name, /etc/group lists
    no members for it, and no other account has it as its primary group. That is CaramOS's default (adduser makes one
    group per user); for other users it logs why and writes nothing.
  - Tickets of a login name with no account here are dropped.
- **Notification:** for each ticket whose status changed or that gained updates since the user's previous file, the
  daemon puts an inbox entry `{"id": "ticket-<id>-<n>", "action": "ticket", "args": {"ticket", "status", "text"},
  "admin_name", "expires"}` (`n` counts the updates). The session part shows `notify-send` ("Phiếu HT-0007: Đang xử
  lý", the newest text) and writes no outbox answer. A frozen machine's first fetch after boot only stores (its files
  are the disk's old ones), so nobody is told the same thing at every boot.
- **Employee window "Yêu cầu của bạn":** it reads its own `tickets/<uid>.json` and shows the tickets, newest first:
  the id, the note, the status ("Mới", "Đang xử lý", "Chờ bạn trả lời", "Đã xong") and the updates. "Nhờ IT hỗ
  trợ" stays as it is; the new ticket shows once the agent has fetched it.

## Asset lifecycle and handover

- **`assets.json`:** keys are asset ids: a machine id, or `asset-<uuid4>` for things without a machine (a machine not
  paired, a monitor, a printer). Each entry gains:
  - `machine_id`: the machine id or null; `kind`: `computer`, `laptop`, `monitor`, `printer` or `other`;
  - `status`: `in_stock`, `in_use`, `repair` or `disposed`;
  - `holder_since`: a date or empty;
  - `history`: `[{"time", "event", "by", "note"}]`, where `event` is `received`, `assigned`, `returned`, `repair`,
    `disposed` or `note`; at most 200, the oldest dropped first.

  The helper's `asset ID` takes the whole entry, adds a history event when `status` or `holder` changed, and
  `asset-new` makes an entry without a machine.
- **Overview:** warranties ending within 30 days, and assets in repair.
- **"In biên bản bàn giao"** (on an asset, or on several chosen ones):
  - caramos-business ships its own template, `/usr/share/caramos-business/templates/bien-ban-ban-giao-tai-san.docx`,
    made by `tools/make-handover-template.py` in this package. It reuses the layout of caramos-ota's
    `tools/make-nd30-templates.py` (`ban_giao_tai_san`, Nghị định 30/2020 Phụ lục I), and writes byte-identical files
    that are committed. Nothing depends on caramos-ota's paths.
  - Placeholders, each the whole text of one `<w:t>` element: `{{TEN_CONG_TY}}`, `{{SO}}`, `{{NGAY}}`, `{{THANG}}`,
    `{{NAM}}`, `{{DIA_DIEM}}`, `{{BEN_GIAO}}`, `{{CHUC_VU_GIAO}}`, `{{BEN_NHAN}}`, `{{CHUC_VU_NHAN}}`, `{{LY_DO}}`.
  - The asset table has one row whose cells hold `{{STT}}`, `{{TEN_TAI_SAN}}`, `{{MA_SO}}`, `{{DON_VI}}`,
    `{{SO_LUONG}}`, `{{TINH_TRANG}}` and `{{GHI_CHU}}`. The window copies that `<w:tr>` once per asset.
  - The window fills `word/document.xml` (values XML-escaped; an empty value becomes the dotted line `…………`), asks
    for the names, titles and reason, and saves a .docx where the user chooses. It also makes a PDF when it can (see
    "Reports as PDF"). The handover is written as a history event.
- **"Nhân viên nghỉ việc"** on the machine page: a checklist kept in the asset history:
  - return the machine;
  - archive their server folder (a manual step on the NAS);
  - remove them from the department;
  - set the asset to `in_stock`.

## Managed snapshots (`snapshots`)

```json
"snapshots": {"schedule": "daily", "keep": 3, "before_update": true}
```

`schedule` is `daily`, `weekly` or `monthly`; `keep` is 1–20; `before_update` is a bool. The window fills in weekly,
3, true.

- **Agent:**
  - It writes `/etc/timeshift/timeshift.json` (exact file: `v3/expected-timeshift.json`) in rsync mode:
    - `backup_device_uuid`: the UUID of the file system on `/` (`findmnt -no UUID /`);
    - `parent_device_uuid`: the UUID of the `crypto_LUKS` partition that `/` sits on, or empty;
    - `do_first_run` false; the chosen level `true` with `count_<level>` = `keep`; every other level and
      `schedule_boot` false; `stop_cron_emails` true;
    - `exclude`: `["/home/**", "/root/**"]` (no user files).
  - An earlier file is kept in `managed.json` and put back, or the file is removed, when the section goes away.
  - Snapshots already taken stay: they are the machine's. The Timeshift app can delete them.
- **Verified:** writing `timeshift.json` alone does not schedule anything. Any Timeshift command that loads the
  settings brings its cron files in line with them; `timeshift --list` printed "Added cron task:
  /etc/cron.d/timeshift-hourly" (`0 * * * * root timeshift --check --scripted`, which takes the snapshots that are
  due and deletes those beyond the counts).
  - `schedule_boot` adds `/etc/cron.d/timeshift-boot`.
  - With every level off, or with no `timeshift.json` at all, the same command removed both files.

  So after every write or removal the agent runs `timeshift --list --scripted`.
- **`before_update`:** the `update` command first runs `timeshift --create --comments "CaramOS Doanh nghiệp" --tags O
  --scripted`. Verified headless: a first snapshot of the test VM took 154 s and 6.8 GB under `/timeshift/snapshots/`;
  later ones copy only what changed (hard links). When it fails, the update still runs and the result says "không
  chụp được bản lưu hệ thống: …".
- **Health:**
  - `last_snapshot`: the newest `created` (Unix time as a string) among `/timeshift/snapshots/*/info.json`, as ISO;
  - `snapshot_space_mb`: `du -sm /timeshift`, at most every 6 hours (half a million files take seconds).
- **Not with freeze:** Timeshift mounts the root device read-write (`/run/timeshift/<pid>/backup`, verified), which
  under overlayroot would write under the overlay's feet. The two are refused together (see "Shared machines").
- Restoring stays a local action, in the Timeshift app; the guide explains it. The window says plainly that snapshots
  are on the same disk and are not a backup.
- Timeshift missing (it ships with CaramOS) or a root file system that is not ext4: `applied.snapshots: "failed:
  …"`.

## Remote help: per-session key and a closed viewer port

Part 2 left two ways for a stranger on the LAN to show their own screen to the admin's viewer, where the admin, in
control mode, might type a password:
- `vncviewer -listen` listens on every interface (port 5500, plain);
- stunnel on 5501 accepted any TLS client.

- **TigerVNC 1.13.1** (noble) has no option to choose the listening address: `-listen [port]` binds every interface,
  and only `UseIPv4` and `UseIPv6` exist. It can connect to a Unix socket (`vncviewer [unix socket]`) but not listen
  on one. Verified from its parameter list.
- **Pre-shared key per session:**
  - At "Kết nối", the helper's `remote-help start` makes 32 random bytes and an identity `rh-<16 hex digits>`, and
    writes `/run/caramos-business/remote-help.psk` (0600) `<identity>:<64 hex digits>`.
  - stunnel then accepts on 0.0.0.0:5501 with `PSKsecrets` = that file, `ciphers = PSK`, `ciphersuites =
    TLS_AES_128_GCM_SHA256` and `sslVersionMin = TLSv1.3`, with no certificate, and connects to 127.0.0.1:5500.
  - The `remote_help` command gains `"psk": "<sealed>"`: part 2's sealing for the target machine of `{"identity",
    "key": "<64 hex>"}`. The helper's `command` reads the key from `remote-help.psk` and seals it itself, so the
    window never handles it. The command goes to one machine only (`targets.machines` with one id; the admin refuses
    other targets).
  - The agent unseals it and hands `identity` and `key` to the session part in the inbox entry.
  - The session part's stunnel client keeps part 2's `client`, `accept` and `connect` lines, and uses `PSKsecrets` (a
    0600 file in its `remote-help/` folder), `PSKidentity`, the same `ciphers`, `ciphersuites` and `sslVersionMin`,
    and no `verifyPeer` or `CAfile`.
  - The key authenticates both ends: only the admin that sealed it and the machine that unsealed it know it. So the
    policy loses `remote_help_cert`, and `effective.json` loses it too.
  - Verified with stunnel 5.72: data flowed both ways with the right key; a wrong key failed ("binder does not
    verify"); a TLS client without the key failed the handshake. `TLS_AES_256_GCM_SHA384` does not work: stunnel's
    PSK callback is SHA-256 only ("no suitable signature algorithm").
- **The viewer's port:** before starting the viewer, `remote-help start` adds
  `iptables -I INPUT -p tcp --dport 5500 ! -i lo -m comment --comment caramos-business-remote-help -j DROP`, and the
  same with `ip6tables`. `remote-help stop` deletes both, and the server deletes any rule with that comment when it
  starts.
  - Verified in a container: a connection over `lo` reached the listener; one from another machine was dropped.
  - It works whether ufw is on or off; iptables is there because ufw depends on it.
- **What remains:** while a session waits, a local process on the admin machine can still connect to 127.0.0.1:5500.
  The admin machine is the admin's own; anyone running code on it can do worse.

## Inboxes and per-user files

- `/run/caramos-business/inbox/<uid>/` becomes `root:<the user's primary group>` 0750, and its files 0640 (part 2:
  0755 and 0644, readable by every local user, which matters with guest sessions and now that entries carry remote
  help keys and ticket notes).
- The private-group rule of the ticket files applies. For a user without a private group the inbox keeps part 2's
  modes, so that commands still reach them, and the daemon logs it once; ticket files are not written for them.

## Employee UI contract additions

| KIND | Options | Answers |
|---|---|---|
| `frozen` | (none) | `ok`: the notice at each login on a frozen machine |

- The window adds "Yêu cầu của bạn", the approval, removal, enrolment-file and first-boot states above, and "Chuẩn bị
  tạo ảnh đĩa" (helper `prepare-image`).
- `notify-send` for ticket updates comes from the session part (no prompt).

## Capabilities

The check-in's `capabilities` gain `licence-report` (the three inventory keys), `shared`, `snapshots` and `tickets`.
The admin shows which machines need a newer agent for a section in effect, as part 2 does. The draft's
`enroll-token` is not a capability: enrolment is the helper's, not the agent's.

## Admin side additions

- **Helper commands:** `pairing open` answers `{"code", "until"}`; `options`; `approve ID`; `reject ID`;
  `enroll-token create FILE`; `enroll-token revoke TOKEN_ID`; `licences`; `ticket`; `asset-new`; `pair-file PATH`
  and `prepare-image` (employee); `enroll-on-boot` (root only, from the unit). `remote-help start` adds the key and the
  firewall rules. `forget-machine` signs the removal notice.
- **Audit lines:** approval and rejection, tokens made, revoked or disabled, enrolments (the server), tickets changed,
  licences changed, assets made, handovers printed.
- **Backup** holds the whole admin folder (now with `enroll-keys.json`, `tickets.json`, `licences.json`,
  `options.json`). The TLS key and certificate are gone from it.

## Files (additions to part 2)

**Admin** (in `/var/lib/caramos-business/admin/` unless a path is given)

| Path | Content |
|---|---|
| `/run/caramos-business/pairing.json` | `root:sudo` 0640: `{"code", "until"}` while pairing is open |
| `options.json` | `{"approve_machines": bool}` |
| `enroll-tokens.json` | the tokens' public details and use counts |
| `enroll-keys.json` | 0600: `{"<token_id>": "<hex proof_key>"}` |
| `machines.json` | entries gain `state` and `via` |
| `removed.json` | 365 days: `{"time", "name", "box_key", "notice"}` per removed machine |
| `tickets.json` | the tickets, `next`, and each machine's version |
| `licences.json` | the register of bought licences |
| `assets.json` | entries gain `machine_id`, `kind`, `status`, `holder_since`, `history`; ids `asset-<uuid4>` for things without a machine |
| `/run/caramos-business/remote-help.psk` | 0600 while remote help runs |
| `/usr/share/caramos-business/templates/bien-ban-ban-giao-tai-san.docx` | the handover template |

Gone: `/run/caramos-business/pairing-until`, `help-requests.json`, `/etc/caramos-business/admin-tls.key` and
`admin-tls.pem`.

**Employee**

| Path | Content |
|---|---|
| `/etc/caramos-business/enroll-on-boot.json` | 0600: the enrolment file, until the first-boot enrolment succeeded |
| `/var/lib/caramos-business/agent/approval.json` | 0644: `{"state", "since"}` |
| `/var/lib/caramos-business/agent/removed.json` | 0644: `{"admin_name", "time"}` after a removal |
| `/var/lib/caramos-business/agent/enroll-failed.json` | 0644: `{"time", "error"}` |
| `/var/lib/caramos-business/agent/maintenance.json` | 0644: `{"last", "finished", "result"}` |
| `/var/lib/caramos-business/agent/leave-pending.json` | on a frozen machine leaving or removed: `{"reason", "admin_name", "time"}` |
| `/var/lib/caramos-business/agent/tickets/` | `version` (0600) and `<uid>.json` (`root:<group>` 0640) |
| `/etc/grub.d/42_caramos-business-maintenance`, `/etc/default/grub.d/71-caramos-business.cfg`, `/etc/overlayroot.local.conf` | freeze |
| `/etc/lightdm/lightdm.conf.d/71-caramos-business-guest.conf` | guest session |
| `/etc/timeshift/timeshift.json` | snapshots |
| `/run/nologin` | during a maintenance boot |

## Test vectors (version 0.3)

`tests/protocol-examples/v3/`, made by `make_v3.py` there (run it where python3-spake2 and python3-cryptography are
installed; Ubuntu 24.04 with universe). The keys are v2's fixed test keys. Both sides test against the files that
concern them.

| File | What | Who |
|---|---|---|
| `keys.json` | v2's keys, the fingerprint, `mac_key` and `seal_key` | both |
| `pair-spake2.json` | a pairing with fixed entropy: messages, `K`, keys, `T`, both confirmations | Python |
| `enroll-file.json`, `enroll-register.json` | an enrolment file; a `/register` body with `proof_key`, `E`, the proof and the answer's confirmation | Python |
| `mac-policy.json`, `mac-files.json` | HMAC of `GET /policy` and `GET /files/<sha>` | both |
| `policy.json`, `signed-policy.json`, `effective-machine.json`, `effective-other-machine.json` | a format 2 policy with `shared` (in a department) and `snapshots` (for the company) | both |
| `invalid-*.json` | one error each in the new sections | both |
| `admin-invalid-freeze-without-maintenance.json` | valid for the agent; the admin refuses to sign a freeze without a maintenance window | Python |
| `policy-freeze-conflict.json`, `signed-policy-freeze-conflict.json` | `folders.tidy` for the company, `shared.freeze` for a department: the admin refuses to sign it; an agent in that department (the other test machine) applies everything but the freeze and reports `applied.shared` failed | both |
| `command-remote-help.json`, `remote-help-psk.json` | a signed `remote_help` with a sealed `psk`, and what it unseals to | both |
| `removed-notice.json`, `removed-notice-other.json`, `removed-notice-tampered.json` | a removal notice for the test machine, one for another machine, one tampered | Rust |
| `tickets.json`, `tickets-user-lan.json`, `wait-answer.json` | a signed `/tickets` answer, the file the agent writes for user `lan`, a `/wait` answer with `tickets` | both |
| `apt-cache-policy-sources.txt`, `apt-cache-policy-packages.txt`, `apt-origins.json` | real `apt-cache policy` output (Ubuntu, Linux Mint, the CaramOS PPA, Google's repository; `***` marks added for the last three to show installed versions) and the expected `origin` of each package | Rust |
| `inventory-apps.json`, `health.json` | examples of the new inventory and health keys | both |
| `expected-timeshift.json`, `expected-overlayroot.local.conf`, `expected-42_caramos-business-maintenance`, `expected-71-caramos-business.cfg`, `expected-lightdm-guest.conf` | the exact files the agent writes for the example policy (the GRUB script as verified on the VM; `expected-timeshift.json` for a root file system with the UUID `33113ae9-4550-4a48-a3cb-12d57f6ae6ff`) | Rust |
| `expected-grub-maintenance-entry.txt` | what `update-grub` made of the script on the test VM | both |

## Changes during implementation

The Python side, 2026-11-23. None of them changes what the agent sends, reads or writes.

- `assets.json`: the history gains the event `handover` (a handover document was printed), beside the six listed in
  "Asset lifecycle and handover"; its audit line has `"event": "handover"`.
- `enroll-tokens.json`: each record also keeps the token's `hostname_prefix`, for the window's list of tokens.
- `POST /register`: the admin takes the token's use as soon as the proof checks out, before it registers the machine,
  so that machines enrolling at the same moment cannot pass `max_uses`; `machines` gets the machine id afterwards.
- Done for the Rust agent's first entry below: `pair` and `pair-file` write `admin_box_key` into agent.json; the
  enrolment file has `admin_box_key` (`v3/enroll-file.json` regenerated by `make_v3.py`; every other v3 file came out
  byte-identical), and `pair-file` refuses a file without it.
- `enroll-on-boot` removes `enroll-on-boot.json` and disables its unit before it starts the agent, and starts it with
  `systemctl --no-block` (the unit is ordered before the agent: a blocking start waited for itself, and the unit,
  started again, enrolled the copy a second time). With socket-activated sshd (Ubuntu 24.04's default) the socket
  failed at boot while the host keys were missing: after `ssh-keygen -A` the helper runs `systemctl reset-failed` and
  restarts `ssh.socket` (or `ssh.service` where the socket is not enabled), not `try-restart ssh.service`.
- "Reports as PDF": Flathub's LibreOffice (26.8.3) has no `soffice` on its PATH, so `flatpak run --command=soffice`
  fails ("bwrap: execvp soffice"); the window runs `flatpak run org.libreoffice.LibreOffice -env:UserInstallation=…
  --headless --convert-to pdf …` (the app's own command takes soffice's options). Verified on caram1.4.0.
- Following the Rust agent's entries: the licence report counts apps and seats by `package` (one inventory entry per
  desktop file); the admin's remote help window shows the agent's `failed` or psk `refused` detail at once instead of
  "the employee refused"; "Yêu cầu của bạn" tells a user without a group of their own why their requests cannot be
  shown there; nothing in the window reads `maintenance.json` itself (the health keys carry it).

The Rust agent (0.3.0), 2026-11-23. The first entry needs the Python side; the others say how the agent reads the
contract, and what the admin and the window see from it.

- **agent.json gains `admin_box_key`** (base64 of the admin's 32-byte X25519 public key). From 0.3 the machine's very
  first request, `GET /policy`, carries the HMAC, whose key needs the admin's box key; part 2 had the agent take that
  key only from a verified policy, which a newly paired machine cannot fetch yet. The agent uses agent.json's
  `admin_box_key` until it has stored a verified policy, then the policy's, as before. Pairings made with 0.2 have a
  stored policy and keep working without it. **Python:** the helper's `pair` writes it from `/pair/start`'s
  `admin_box_key` (`T` covers it, so the admin's confirmation vouches for it); for `pair-file`, the enrolment file
  gains `admin_box_key` (written by `enroll-token create`, checked by `pair-file` as base64 of 32 bytes, copied into
  agent.json). Without it the agent logs "this machine cannot sign its requests (no machine key, or no admin box key
  yet): pair it again" and never reaches the admin. (Done on the Python side: `client.agent_config`.)
- **A user without a private group** keeps part 2's inbox modes for messages, locks and countdowns, but gets neither
  a ticket notification nor a remote help session: their key would sit in a file every local user can read. Remote
  help to such a user is `failed` "<user> không có nhóm riêng: khóa hỗ trợ từ xa không được để nơi người khác đọc
  được". `remote_help` without `psk` is `refused` ("args.psk is missing").
- **"Someone at the machine"** (the maintenance window, `screen_lock_on`) is a graphical user session on seat0 in
  logind's files (`CLASS=user`, not closing), active or not. LightDM's greeter alone is nobody. light-locker locks
  the screen by switching to a greeter session while the user's session stays `online`: that is someone (verified on
  the Xfce VM, where the 06:00 window was skipped at 06:45 while the user's screen was locked). Remote help still goes
  only to the active user session. The agent reads only logind's session files, never the `<id>.ref` FIFOs beside
  them (0.2 read every entry, and a read of a FIFO blocks).
- **Inventory `apps[].id`** of a deb app is the desktop file's name (`vlc.desktop`), one entry per visible desktop
  file, as in `inventory-apps.json`; `package` is the package (0.2 sent one entry per package, with the package as
  `id`). **Python:** count licences and seats by `package`.
- **`origin` of an installed version that its archive no longer has** (an update is waiting; 45 of 107 apps on the
  CaramOS 1.3.10 test VM, Firefox and Cinnamon among them, show only `/var/lib/dpkg/status` for the installed version)
  is the origin of the candidate version's archive. `local-deb` stays for a package that no archive has.
- **`removed.json`:** `admin_name` is the notice's `admin` (agent.json's `admin_name` when that is empty) and `time`
  the notice's `time`: when the company removed the machine, which may be days before a machine that was off saw it.
- **`maintenance.json`** may also hold `tried` (ISO): when the frozen machine last restarted into the maintenance
  entry. A restart that did not reach the maintenance boot is then not tried again in the same window, and the next
  frozen boot sets `result` to "lỗi: máy không khởi động vào chế độ bảo trì". The maintenance boot writes `{"last":
  <start>, "finished": null, "result": "đang bảo trì"}` when it starts, and the full record when it ends. A skipped
  day changes only `result`: `last` and `finished` stay as they were (null before the first maintenance). Other
  results: "hết giờ bảo trì: khởi động lại khi chưa xong" (the time limit), "đã thôi đóng băng" (the fetched policy no
  longer freezes the machine: no restart), "lỗi: GRUB chưa có mục bảo trì", "lỗi: grub-reboot: …". On a frozen machine
  the file is written in the overlay and on the disk (`overlayroot-chroot tee`). **Python:** read `last`, `finished`
  (may be null) and `result`; ignore other keys.
- **`applied` on a frozen machine** has no `apps`: apps wait for the maintenance boot, whose `maintenance_result`
  says how they went. A freeze refused (`folders.tidy`, `snapshots`, memory) also puts back a freeze configured
  earlier, from the next boot. With `snapshots` in effect on a frozen machine (only if an admin signed that conflict),
  `applied.snapshots` is "failed: no snapshots while the machine is frozen".
- **Timeshift:** `timeshift --list --scripted` exits 1 before the first snapshot ("No snapshots found") although it
  did add its cron file; the agent ignores its status and checks that `/etc/cron.d/timeshift-hourly` exists.
  Timeshift also writes `timeshift.json` itself (after `--create`, in its own formatting), so the agent compares the
  settings' values, not the bytes. When the section goes away on a machine that had no `timeshift.json` before, the
  agent removes the file and the same command then copies Timeshift's own `default.json` (no schedule, first-run
  wizard on) as `timeshift.json`: the machine is as Timeshift leaves any machine that never had settings. Verified on
  the Cinnamon VM: Timeshift's cron took the weekly snapshot at 03:00, the `update` command's snapshot came before
  the updates, and the cron file went with the section.
- **A frozen machine removed by notice** also removes the pairing and writes `removed.json` in the overlay, so that
  the window shows the removal at once; the disk follows at the next, unfrozen, boot (step 5).

The joint end-to-end pass with the 0.3.0 .deb, 2026-11-23. Bugs found on the VMs and fixed, with tests:

- **`caramos-business-hostname.service`** (new, shipped disabled; `prepare-image` enables it with the enrolment
  unit, `enroll-on-boot` disables both): a oneshot ordered `Before=display-manager.service
  systemd-user-sessions.service caramos-business-enroll.service`, with the same `ConditionPathExists`, that runs the
  helper's new `enroll-hostname` (root only, refused under pkexec): it sets the host name from `enroll-on-boot.json`
  and does nothing else. Before, the enrolment unit set the name after `network-online.target`, which comes about when
  LightDM starts its X server: the name changed 2 s after LightDM started, the X cookie was filed under the old name,
  every program of the autologin session got "Authorization required", and both copies showed a black screen until
  their next boot. `enroll-on-boot` still sets the name (for disks prepared with 0.3.0) but calls `hostnamectl` only
  when the name differs. Verified with a copy of a disk prepared with the fix: the name was set 1.4 s before LightDM
  started, and the desktop came up at the first boot.
- **`/wait` answers early when the machine's tickets version moved** (the server alone; nothing the agent sends or
  reads changes). The server's snapshot also watches `tickets.json`; it remembers the version each machine's last
  answer carried and answers at once when it differs (the first wait after the server starts only sets the mark: the
  agent fetches its tickets when it starts). A public note took 46 s to reach the employee (the end of the long poll);
  now 0.22 s from the admin's write to the employee's `tickets/<uid>.json`.
- **The session part starts again with an upgraded program only while no notice is open** (as for prompts and remote
  help): the new program knows nothing of the open notice and opened a second one beside it (two "Máy này do công ty
  quản lý" windows after two agent updates; the old one could no longer answer and stayed a zombie).
- **Report PDFs:** every sheet prints one A4 page wide (`fitToWidth`); the "Nội quy" sheet of the security report,
  portrait and 120 characters wide, lost its right edge in the PDF. Its column is now 90 wide.
- **Licence classes:** a Debian licence name with an exception after a free id (`GPL-2+-OpenSSL`, `GPL-2+ with
  OpenSSL exception`) counts as free; 0.3.0 left them unknown. **Agent:** a DEP-5 `Files:` field folded over several
  lines (`Files: *\n src/*`, gnome-system-monitor) is read whole; 0.3.0 found no `Files: *` stanza there.
- **Security report:** "Khóa màn hình" says "Chưa rõ" when `screen_lock_on` is not reported, not "Bật".
- **The same computer pairing again** (same MAC; part 1) also keeps its department and drops the old entry's
  inventory and health files, besides moving its asset record (0.3.0 left the new entry without a department and kept
  orphan inventories that the backup carried).
- **A machine taken out of the company keeps its asset record** when the admin typed anything into it (any part 2
  field, or a history): it becomes a thing without a machine, `asset-<uuid4>` with `machine_id` null and `name` the
  machine's host name, and its history gains a `note` "Đã gỡ khỏi công ty." by the admin who removed it. An empty
  record still goes. 0.3.0 dropped the record with the pairing, and with it the holder, the handover and the leaver's
  steps, which is what IT needs after an employee leaves (seen on the removed caramos-disk).
- **The machine page's asset section** is built again after each save (its history and leaver steps showed nothing
  new until the window was reopened), keeping the scroll position. Toasts move above the save bar while it shows (a
  refused save's toast covered "Hoàn tác" and "Lưu và gửi").
- **Leaving or removal of a frozen machine, the login after the restart:** the session part treats a machine with
  `leave-pending.json` as unmanaged (no effective settings, no notice), and closes an open notice, unanswered, as
  soon as the machine is no longer managed (removed, left, or a clone). 0.3.0 opened "Máy này do công ty quản lý …
  từ máy ?" at the first login after a frozen machine left, before the daemon had finished leaving.
- **The window's "Công ty đã gỡ máy này" on a frozen machine** (with `leave-pending.json`) says to restart and has a
  "Khởi động lại" button; it said the settings had been taken off while the disk still held them.
- **An admin restored from an older backup catches up with its machines** (part 2, "Admin backup and restore"; the
  server alone). Machines refuse a policy whose serial is not above the one they stored, and a backup made before the
  last saves has a lower serial: on the VMs both employees refused the restored admin's policy ("its serial 35 is
  lower than that of the stored policy, 38") and would have refused every save until the serial passed 38. Now a
  check-in whose `policy_serial` is above the admin's (by at most 10000) makes the server sign the same settings again
  with that serial + 1, with an audit line `settings` (`changes` empty, `reason: "catch-up"`, `serial`, `behind`). The
  machines take it at their next `/wait`. The restored admin's settings are the backup's: what was saved after the
  backup is gone, as the guide says.
