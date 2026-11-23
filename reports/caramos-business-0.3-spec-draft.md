# CaramOS Doanh nghiệp 0.3: draft spec (to become PROTOCOL.md part 3)

Draft written 2026-11-22. It goes into PROTOCOL.md once the 0.2 integration pass is done. It builds on part 2: the
same signed policy, settings sections, commands, inventory, health, helper, admin window and session part. It keeps
part 2's rules:
- everything opt-in;
- no covert monitoring;
- no arbitrary commands;
- whatever the agent changes is put back when a section goes away or the machine leaves.

Order of work (the owner approved it on 2026-11-22):
1. licence report;
2. enrolment without a code, and prepare-image;
3. shared-machine mode;
4. security report;
5. helpdesk tickets;
6. asset lifecycle and handover;
7. managed snapshots.

The Windows migration kit (fonts, ND30 templates, the TCVN3/VNI converter, Remmina, the data-migration app, the
assessment script) is built separately in caramos-ota and the App Center.

## 1. Licence report

**Agent:** each `inventory.apps[]` entry gains:
- `licence`: an SPDX expression or `LicenseRef-proprietary`/`unknown`.
  - For deb packages: the machine-readable `/usr/share/doc/<pkg>/copyright` (DEP-5 `License:` of the `Files: *`
    stanza), falling back to AppStream (`appstreamcli get <id>`).
  - For Flatpak: AppStream `project_license`.
- `origin`: one of
  - `ubuntu-main`, `ubuntu-universe`, `ubuntu-restricted`, `ubuntu-multiverse`;
  - `mint`, `caramos-ppa`;
  - `third-party:<host>` (another apt repo; the host of its URI);
  - `flathub`, `local-deb` (no repo).
  - Found with `apt-cache policy <pkg>` (the origin line) or `flatpak info`.
- `package`: the deb or Flatpak id it came from.

**Classes.** The admin turns each app into one class:
- `free`: an OSI/FSF licence;
- `freeware`: proprietary, free to use. Only when the App Center catalog says so: a new catalog field `licence:
  {"class": "free|freeware|commercial", "note": {vi,en}}`, set for every catalog app, for example Chrome freeware;
  WPS: check its terms, else `unknown`;
- `commercial`: needs a bought licence;
- `unknown`.

**Register of bought licences** (admin only), in `licences.json`: `[{"id", "product", "seats", "expires", "invoice",
"note", "match": [app ids]}]`. The report compares seats with the machines that have a matching app.

**Admin page "Bản quyền phần mềm":**
- totals by class;
- apps with machine counts;
- `unknown` and `commercial` apps first;
- the register;
- export to XLSX and to PDF, with an XLSX "Báo cáo phần mềm" sheet per machine and a summary sheet with signature
  lines for "Người lập" and "Giám đốc";
- the fixed disclaimer: "Báo cáo này liệt kê phần mềm tìm thấy trên các máy; nó không xác nhận việc sử dụng đã đủ
  bản quyền."

The PDF comes from `soffice --headless --convert-to pdf` when LibreOffice is installed; otherwise only XLSX.

Inventory must be on (`inventory` section) for a machine to appear; the page says so for machines without it.

## 2. Enrolment without a code, and prepare-image

- **Enrolment file:** the admin window, under "Thêm máy", offers "Tạo tệp ghép máy". The helper writes
  `caramos-business-enroll.json` wherever the admin chooses (a USB stick):

  ```json
  {"format": 1, "admin_url": "http://IP:47022", "admin_name", "admin_key": "<b64 Ed25519>",
   "fingerprint", "department": "<id or null>", "token": "<b64 32 random bytes>", "expires": "<ISO>",
   "max_uses": 30}
  ```

  - The admin keeps only `sha256(token)`, the uses left, the expiry and the department, in `enroll-tokens.json`.
  - The admin can revoke a token.
  - The window warns that anyone holding the file can add machines until it expires or runs out.
- **On an employee machine** with caramos-business installed and no role, the window finds the file:
  - on mounted removable media (`/media/<user>/*/caramos-business-enroll.json`);
  - or the user picks it.
  - It shows the admin's name and fingerprint and asks for confirmation (and the local admin password through
    pkexec).
  - The helper's `pair-file PATH` pins `admin_key` from the file (the admin made it) and registers with
    `{"token", "machine", "box_key"}` instead of the code.
- **Server:**
  - `/register` accepts `token` while it is unexpired with uses left (each use is counted), and puts the machine in
    the token's department.
  - With "Duyệt từng máy" on (an admin option), the machine waits in a list until the admin approves it. Until then
    its check-ins get 403 "chờ duyệt".
- **`caramos-business-helper prepare-image`:** for a machine that will be cloned (computer labs, Clonezilla). It
  asks for confirmation, then deletes:
  - agent.json, agent-box.key, the agent state;
  - `/etc/machine-id` (emptied, so systemd makes a new one) and `/var/lib/dbus/machine-id`;
  - the SSH host keys (regenerated at boot by a one-shot unit);
  - and it leaves a file `/etc/caramos-business/enroll-on-boot.json` when an enrolment file is given, so each clone
    enrols itself at first boot.
  
  The window's machine page and HUONG-DAN explain the cloning flow.
- **Later, not in 0.3:** a full unattended install USB (Ubiquity `automatic-ubiquity` and preseed), which needs an
  ISO remaster on the admin machine.

## 3. Shared-machine mode

New settings section:

```json
"shared": {"guest": true, "freeze": false, "maintenance": {"days": [7], "time": "02:00"}}
```

- `guest`: a guest session on the login screen.
  - LightDM: `/etc/lightdm/lightdm.conf.d/71-caramos-business-guest.conf` with `allow-guest=true` and
    `greeter-allow-guest=true`.
  - Check that slick-greeter (Cinnamon) and the Xfce edition's greeter show it. If not, write down what is needed.
  - The guest account's home is wiped at logout by lightdm's own guest-account script.
- `freeze`: restore on reboot with `overlayroot` (package `overlayroot`, Ubuntu main): `/etc/overlayroot.local.conf`
  `overlayroot="tmpfs:swap=1,recurse=0"`.
  - Takes effect at the next boot; the window says so.
  - **Maintenance window:** at `maintenance` the daemon (the machine woken by part 2's RTC/WoL) runs `grub-reboot`
    into a one-time entry with `overlayroot=disabled`. It reboots, applies the policy, runs the CaramOS update and
    apt's security updates, then reboots frozen again.
  - The daemon's own state can't survive a frozen reboot. Part 2's rule against stale commands from before the boot
    covers that, and the policy is fetched again at each boot.
  - The session part shows a notice at each login: "Máy này tự xóa mọi thay đổi khi khởi động lại. Lưu tệp vào ổ
    dùng chung hoặc USB."
  - Refused on a machine with less than 3 GiB of RAM unless the admin ticks "Tôi hiểu".
  - Not offered with `folders` tidy: the two sections are refused together.
- Put back when the section goes away: remove both files, then reboot normally (the window says a reboot is needed).

## 4. Security report

- **New health fields** (agent):
  - `encryption`: `"luks"` when the root file system sits on a dm-crypt device (`lsblk -J -o NAME,TYPE,FSTYPE`),
    else `"none"` or `"unknown"`;
  - `last_snapshot`: ISO or null, from section 7;
  - `screen_lock_on`: bool, the effective state for the user at the screen;
  - `usb_storage`: the effective mode.
- **Admin page "Báo cáo an toàn"** (under Bảo mật):
  - a table per machine: firewall, security updates waiting and since when, reboot required, screen lock, USB
    storage, encryption, last snapshot, last seen, problems;
  - company totals;
  - an extract of the audit log for a period;
  - the standard staff-transparency paragraph to paste into the internal labour rules (Law 91/2025, art. 25(3)(a)).
  - Export to XLSX and PDF, with the disclaimer: "Báo cáo hiện trạng kỹ thuật; không phải chứng nhận đạt cấp độ an
    toàn thông tin nào."

## 5. Helpdesk tickets

Help requests become tickets: `tickets.json` on the admin.

```json
{"id": "HT-0001", "machine_id", "user", "note", "created", "status": "new|working|waiting|done",
 "assignee": "", "notes": [{"time", "by", "text"}], "first_response": null, "closed": null,
 "snapshot": {"health": {}, "inventory_summary": {}}}
```

- `/help` creates a ticket. A snapshot of the machine's health and its inventory summary is attached at that moment.
- **Admin page "Phiếu hỗ trợ":** filters by status, a detail view, status changes, notes, "Hỗ trợ từ xa" from the
  ticket, and the monthly export (XLSX: counts, median first-response time, the list).
- **Employee window:** "Yêu cầu của bạn" shows each ticket's status and the admin's public notes.
  - A note marked public is sent back through `/wait` as a `ticket` command `{"id", "status", "note"}` shown in the
    window (and a notification), so no new endpoint.
  - Internal notes stay on the admin.

## 6. Asset lifecycle and handover

- **`assets.json` gains:**
  - `status`: `in_stock|in_use|repair|disposed`;
  - `history`: `[{"time", "event", "by", "note"}]`, where `event` is `received`, `assigned`, `returned`, `repair`,
    `disposed` or `note`;
  - `holder_since`.
- **Assets without a machine** (a machine not paired, a monitor, a printer): `assets.json` may hold entries with
  `"machine_id": null` and a `kind`.
- **Overview:** warranties ending within 30 days, and machines in repair.
- **"In biên bản bàn giao":** fills the ND30 template "Biên bản bàn giao tài sản" (from the migration kit) by
  replacing placeholders in `word/document.xml`, and saves a .docx (and a PDF if LibreOffice is there).
- **"Nhân viên nghỉ việc" checklist** on the machine page, stored with the asset history:
  - return the machine;
  - archive their server folder (a manual step on the NAS);
  - remove them from the department;
  - set the asset to `in_stock`.

## 7. Managed snapshots (Timeshift)

New settings section:

```json
"snapshots": {"schedule": "daily|weekly|monthly", "keep": 3, "before_update": true}
```

- The agent writes `/etc/timeshift/timeshift.json` (rsync mode, the root device's UUID, the schedule and keep
  counts, home folders excluded) and puts back the earlier file when the section goes away.
- With `before_update`, the `update` action and the maintenance window first run `timeshift --create --comments
  "CaramOS Doanh nghiệp" --tags O`.
- Health gains `last_snapshot` and `snapshot_space_mb`. A problem is flagged when the last snapshot is older than
  twice the schedule.
- Restoring stays a local action (the Timeshift app). HUONG-DAN explains it.
- The window says plainly that snapshots are on the same disk and are not a backup.

## Capabilities and versions

- New capabilities: `licence-report`, `enroll-token`, `shared`, `snapshots`, `tickets`.
- The admin shows which machines need a newer agent for a managed section.
- Policy `format` stays 2; the new sections are optional keys.
