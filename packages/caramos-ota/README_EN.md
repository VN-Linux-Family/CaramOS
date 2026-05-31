# CaramOS OTA Package — Detailed Implementation Specification

> **Package name:** `caramos-ota`  
> **Primary command:** `sudo caramos-ota`  
> **Target OS:** CaramOS 1.x, based on Linux Mint 22.x / Ubuntu 24.04 LTS `noble`  
> **Document status:** Planning/specification document before implementation  
> **Language policy:** CLI output in English, desktop notification UI in Vietnamese

---

## 1. Purpose

`caramos-ota` is the official over-the-air update package for CaramOS.

The long-term goal is simple:

```bash
sudo caramos-ota
```

A user should only need to run one package/command. The tool will:

1. Detect whether the machine is actually running CaramOS.
2. Verify that the official CaramOS package repository is configured.
3. Refresh package metadata safely.
4. Read the CaramOS OTA manifest.
5. Detect which CaramOS component packages need installation or upgrade.
6. Show a clear summary before making changes.
7. Ask for confirmation unless explicitly bypassed.
8. Install the required CaramOS update packages through APT.
9. Record logs and transaction state for status display and best-effort rollback.
10. Expose a desktop notifier so normal users can see when updates are available.

This package is **not** meant to replace Ubuntu/Mint update infrastructure entirely. It is a CaramOS-specific layer for shipping CaramOS branding, configuration, fixes, and curated component updates.

---

## 2. Confirmed Design Decisions

### 2.1 Naming

| Item | Decision |
|---|---|
| Debian package name | `caramos-ota` |
| Executable command | `caramos-ota` |
| Recommended user command | `sudo caramos-ota` |
| Alias command | None for v1 |
| GUI notifier command | `caramos-ota-notifier` |

Reasoning:

- `caramos-ota` matches the distribution name directly.
- It is more professional and less ambiguous than `caram-ota`.
- It keeps package naming consistent with future packages such as `caramos-zram-config`.

### 2.2 Language

| Surface | Language |
|---|---|
| CLI messages | English |
| `--help` output | English |
| Logs | English |
| Desktop popup/notifier | Vietnamese |
| User-facing update descriptions in GUI | Vietnamese preferred, English acceptable as fallback |

Reasoning:

- CLI English makes debugging, logs, bug reports, and packaging easier.
- GUI Vietnamese is better for the intended CaramOS desktop users.

### 2.3 Repository

| Item | Decision |
|---|---|
| PPA | `ppa:vietnamlinuxfamily/caram-os` |
| Ubuntu codename | `noble` |
| Channel in v1 | Stable only |
| Testing/dev channels | Deferred |
| PPA auto-add by OTA tool | No |
| PPA preinstalled in ISO | Yes |

`caramos-ota` must **not** silently add repositories on its own in v1. The ISO should ship the official repository and signing key. If they are missing, `caramos-ota` should stop and explain the problem.

### 2.4 Security and restrictions

| Requirement | Decision |
|---|---|
| Must run as root for CLI upgrades | Yes |
| Must reject non-CaramOS systems | Yes |
| CaramOS identity source | `/etc/caramos-release` |
| `--force` bypass | No |
| Telemetry | No |
| Concurrent runs | Blocked by lock file |
| GUI privilege escalation | `pkexec` + polkit policy |

Important principle: **fail closed**. If CaramOS identity, repository, lock acquisition, or package metadata cannot be verified, the updater should stop rather than guess.

### 2.5 Auto check and GUI notification

| Feature | Decision |
|---|---|
| Background check | systemd timer |
| Check frequency | Daily |
| Auto install | No |
| Desktop popup when update exists | Yes |
| GUI toolkit | Python 3 + GTK3 |
| GUI update execution | `pkexec caramos-ota --upgrade --yes` |

The background timer only checks. It must not install packages automatically.

---

## 3. Intended Package Layout

Repository path:

```text
packages/caramos-ota/
├── README.md
├── debian/
│   ├── changelog
│   ├── control
│   ├── install
│   ├── postinst
│   ├── rules
│   └── source/
│       └── format
├── etc/
│   └── xdg/
│       └── autostart/
│           └── caramos-ota-notifier.desktop
├── lib/
│   └── systemd/
│       └── system/
│           ├── caramos-ota-check.service
│           └── caramos-ota-check.timer
└── usr/
    ├── bin/
    │   ├── caramos-ota
    │   └── caramos-ota-notifier
    └── share/
        ├── caramos-ota/
        │   └── manifest.json
        └── polkit-1/
            └── actions/
                └── net.vietnamlinuxfamily.caramos-ota.policy
```

Installed system paths:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/share/caramos-ota/manifest.json
/usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy
/usr/lib/systemd/system/caramos-ota-check.service
/usr/lib/systemd/system/caramos-ota-check.timer
/etc/xdg/autostart/caramos-ota-notifier.desktop
```

Runtime paths:

```text
/var/lib/caramos-ota/state.json
/var/lib/caramos-ota/lock
/var/log/caramos-ota/YYYY-MM-DD.log
```

ISO/OS identity path:

```text
/etc/caramos-release
```

---

## 4. `/etc/caramos-release`

The updater depends on this file to confirm that it is running on CaramOS.

Example content:

```text
NAME="CaramOS"
VERSION="1.0.1"
BASE="Linux Mint 22.3"
UBUNTU_CODENAME="noble"
CHANNEL="stable"
```

Expected behavior:

- If the file is missing: stop.
- If `NAME` is not `CaramOS`: stop.
- If `UBUNTU_CODENAME` is not `noble` for CaramOS 1.x: stop.
- If `CHANNEL` is not `stable` in v1: stop or warn and stop.

This file should be added to the ISO overlay, for example:

```text
config/includes.chroot/etc/caramos-release
```

---

## 5. Repository and Signing Key

The CaramOS ISO should include the CaramOS PPA source and keyring.

Expected source entry:

```text
deb [signed-by=/usr/share/keyrings/caramos-archive-keyring.gpg] https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu/ noble main
```

Expected keyring path:

```text
/usr/share/keyrings/caramos-archive-keyring.gpg
```

`caramos-ota` should verify:

1. At least one APT source file references `ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os`.
2. The source uses `noble`.
3. The source uses `signed-by=/usr/share/keyrings/caramos-archive-keyring.gpg`.
4. The keyring file exists and is readable.

If any check fails, show a clear error and do not install anything.

---

## 6. Manifest

The manifest defines which CaramOS component packages belong to an OTA release.

Path:

```text
/usr/share/caramos-ota/manifest.json
```

Example:

```json
{
  "schema": 1,
  "release": "1.0.2",
  "codename": "noble",
  "components": [
    {
      "package": "caramos-zram-config",
      "required": true,
      "min_version": "1.0.2",
      "description": "Configure default ZRAM size to 50% of RAM"
    },
    {
      "package": "caramos-mintreport-branding",
      "required": true,
      "min_version": "1.0.2",
      "description": "Update MintReport branding for CaramOS"
    },
    {
      "package": "caramos-mintwelcome-l10n",
      "required": true,
      "min_version": "1.0.2",
      "description": "Update MintWelcome CaramOS translations"
    }
  ]
}
```

Rules:

- `schema` must be checked before parsing deeply.
- `codename` must match `/etc/caramos-release`.
- `components[].package` must be treated as data and validated against a strict package-name pattern.
- v1 strategy: install or upgrade all required packages listed in the manifest.
- Optional components can be introduced later, but v1 should keep behavior simple.

Recommended package-name validation pattern:

```text
^[a-z0-9][a-z0-9+.-]+$
```

---

## 7. State File

Path:

```text
/var/lib/caramos-ota/state.json
```

Purpose:

- Store last check time.
- Store last successful upgrade time.
- Store installed OTA release.
- Store available update summary for the GUI notifier.
- Store transaction history for `--status` and best-effort `--rollback`.

Example:

```json
{
  "last_check": "2026-05-26T16:00:00+07:00",
  "last_successful_upgrade": "2026-05-26T16:05:00+07:00",
  "installed_release": "1.0.2",
  "available_update": null,
  "transactions": [
    {
      "id": "20260526-160500",
      "timestamp": "2026-05-26T16:05:00+07:00",
      "manifest_release": "1.0.2",
      "packages": [
        {
          "name": "caramos-zram-config",
          "old_version": null,
          "new_version": "1.0.2",
          "action": "install"
        }
      ]
    }
  ]
}
```

When updates are available but not installed, `available_update` may look like this:

```json
{
  "detected_at": "2026-05-26T16:00:00+07:00",
  "release": "1.0.2",
  "current_version": "1.0.1",
  "packages": [
    {
      "name": "caramos-zram-config",
      "current_version": null,
      "available_version": "1.0.2",
      "description": "Configure default ZRAM size to 50% of RAM"
    }
  ]
}
```

File permissions should prevent normal users from editing state:

```text
owner: root
mode: 0644 or stricter
```

Because the GUI notifier reads the state as a normal desktop user, `0644` is acceptable if the file contains no sensitive data.

---

## 8. Locking and Concurrency

Multiple updater runs must not happen at the same time.

Required behavior:

- Use a lock file under `/var/lib/caramos-ota/lock`.
- Acquire it with `flock`.
- If another instance is running, exit with a friendly error.
- Use one global lock for all operations that can alter state or call APT.

Example message:

```text
Error: Another CaramOS OTA operation is already running.
Please wait for it to finish, then try again.
```

This applies to:

- Manual CLI run.
- systemd timer check.
- GUI-triggered upgrade.
- repair.
- rollback.

---

## 9. CLI Commands

### 9.1 Default command

```bash
sudo caramos-ota
```

Default behavior:

1. Check root.
2. Acquire lock.
3. Detect CaramOS.
4. Verify repository.
5. Run `apt-get update`.
6. Detect available OTA updates.
7. Show update table.
8. Ask for confirmation.
9. Install updates if confirmed.
10. Write state and logs.

### 9.2 `--check`

```bash
sudo caramos-ota --check
```

Behavior:

- Check only.
- Refresh APT metadata.
- Detect updates.
- Write `last_check` and `available_update` to state.
- Do not install anything.

This is what the systemd timer should run.

### 9.3 `--upgrade`

```bash
sudo caramos-ota --upgrade
```

Behavior:

- Explicitly perform the upgrade flow.
- Equivalent to the default command, but clearer for automation.
- Still asks for confirmation unless `--yes` is passed.

### 9.4 `--yes`

```bash
sudo caramos-ota --upgrade --yes
```

Behavior:

- Skip interactive confirmation.
- Intended for GUI `pkexec` flow or controlled automation.
- Must still perform all safety checks.

### 9.5 `--dry-run`

```bash
sudo caramos-ota --dry-run
```

Behavior:

- Show what would be installed or upgraded.
- Do not modify packages.
- Should not write a successful transaction.
- May update `last_check` if it refreshes metadata.

### 9.6 `--status`

```bash
sudo caramos-ota --status
```

Behavior:

- Show current CaramOS version.
- Show OTA tool version.
- Show last check.
- Show last successful upgrade.
- Show installed OTA release.
- Show installed OTA packages.
- Should not require package installation.

### 9.7 `--repair`

```bash
sudo caramos-ota --repair
```

Behavior:

- Intended for broken package states.
- Run safe repair commands:

```bash
dpkg --configure -a
apt-get --fix-broken install
```

Implementation detail:

- Prefer noninteractive mode only when safe.
- Log all repair output.
- Do not hide errors.

### 9.8 `--rollback`

```bash
sudo caramos-ota --rollback
```

Behavior:

- Read latest successful transaction.
- Show packages to be removed or downgraded.
- Ask for confirmation.
- Attempt rollback best-effort.
- Log every action.

Rollback policy:

- Packages that were newly installed by OTA can be removed.
- Packages that were upgraded can only be downgraded if the old version is still available in APT cache/repository.
- If a downgrade is not possible, report it clearly.

### 9.9 `--version`

```bash
caramos-ota --version
```

Behavior:

- Print tool version.
- Does not need root.

### 9.10 `--help`

```bash
caramos-ota --help
```

Behavior:

- Print usage.
- Does not need root.

---

## 10. CLI UX Examples

### Updates available

```text
╔══════════════════════════════════════════╗
║       CaramOS OTA Updater v1.0.2        ║
╚══════════════════════════════════════════╝

[✓] CaramOS detected: 1.0.1
[✓] Repository: ppa:vietnamlinuxfamily/caram-os
[✓] Updating package index...

Available updates:

  Package                        Current    Available
  ─────────────────────────────────────────────────────
  caramos-zram-config            (new)      1.0.2
  caramos-mintreport-branding    (new)      1.0.2
  caramos-mintwelcome-l10n       (new)      1.0.2

3 updates available.

Install these updates? [Y/n]
```

### No updates

```text
CaramOS OTA Updater v1.0.2

[✓] CaramOS detected: 1.0.1
[✓] Repository: ppa:vietnamlinuxfamily/caram-os
[✓] Updating package index...

No CaramOS OTA updates are available.
```

### Not root

```text
Error: This command requires root privileges.
Please run: sudo caramos-ota
```

### Not CaramOS

```text
Error: CaramOS not detected.
This updater can only run on CaramOS.
Missing: /etc/caramos-release
```

### Missing repository

```text
Error: CaramOS repository not found.
The CaramOS PPA should be pre-configured in /etc/apt/sources.list.d/.

Expected repository:
  deb [signed-by=/usr/share/keyrings/caramos-archive-keyring.gpg] https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu/ noble main
```

---

## 11. Desktop Notifier

Command:

```text
/usr/bin/caramos-ota-notifier
```

Technology:

- Python 3.
- GTK3 through `gi.repository`.
- Reads `/var/lib/caramos-ota/state.json`.
- Runs as the logged-in desktop user.
- Uses `pkexec` only when the user chooses to install updates.

Autostart path:

```text
/etc/xdg/autostart/caramos-ota-notifier.desktop
```

Desktop entry:

```ini
[Desktop Entry]
Type=Application
Name=CaramOS Update Notifier
Comment=Check for CaramOS OTA updates
Exec=/usr/bin/caramos-ota-notifier
Icon=system-software-update
Terminal=false
NoDisplay=true
X-GNOME-Autostart-Phase=Applications
X-GNOME-Autostart-Delay=30
```

### 11.1 Notifier flow

1. User logs in.
2. Desktop autostart launches `caramos-ota-notifier` after a short delay.
3. Notifier reads `state.json`.
4. If there is no `available_update`, exit silently.
5. If an update exists, show a Vietnamese GTK dialog.
6. Dialog lists:
   - current version,
   - new release,
   - package names,
   - package descriptions.
7. User can choose:
   - `Đóng`: close dialog, do nothing,
   - `Cập nhật`: authenticate and install.
8. If user chooses update, run:

```bash
pkexec /usr/bin/caramos-ota --upgrade --yes
```

9. Show progress/result.

### 11.2 Dialog copy — update available

```text
CaramOS - Có bản cập nhật mới

Phiên bản hiện tại: 1.0.1
Phiên bản mới:      1.0.2

Nội dung cập nhật:
• caramos-zram-config 1.0.2
  Cấu hình ZRAM mặc định 50% RAM

• caramos-mintreport-branding 1.0.2
  Cập nhật giao diện MintReport cho CaramOS

• caramos-mintwelcome-l10n 1.0.2
  Cập nhật bản dịch MintWelcome

[Đóng] [Cập nhật]
```

### 11.3 Dialog copy — success

```text
CaramOS - Cập nhật thành công!

Đã cập nhật 3 gói thành công.
Phiên bản hiện tại: 1.0.2

[Đóng]
```

### 11.4 Dialog copy — failure

```text
CaramOS - Cập nhật thất bại

Đã xảy ra lỗi khi cập nhật.
Vui lòng thử lại hoặc chạy:
  sudo caramos-ota --repair

Chi tiết lỗi được ghi tại:
  /var/log/caramos-ota/YYYY-MM-DD.log

[Đóng]
```

---

## 12. Polkit Policy

Path:

```text
/usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy
```

Draft:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC
 "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN"
 "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="net.vietnamlinuxfamily.caramos-ota.upgrade">
    <description>Run CaramOS OTA upgrade</description>
    <message>Authentication is required to install CaramOS updates</message>
    <icon_name>system-software-update</icon_name>
    <defaults>
      <allow_any>auth_admin</allow_any>
      <allow_inactive>auth_admin</allow_inactive>
      <allow_active>auth_admin</allow_active>
    </defaults>
    <annotate key="org.freedesktop.policykit.exec.path">/usr/bin/caramos-ota</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
```

Security note:

- The policy must only allow `/usr/bin/caramos-ota`.
- The CLI must validate arguments itself.
- Do not allow arbitrary shell execution through pkexec.

---

## 13. systemd Timer

Timer path:

```text
/usr/lib/systemd/system/caramos-ota-check.timer
```

Draft:

```ini
[Unit]
Description=CaramOS OTA daily check

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
```

Service path:

```text
/usr/lib/systemd/system/caramos-ota-check.service
```

Draft:

```ini
[Unit]
Description=CaramOS OTA check for updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/caramos-ota --check
```

Post-install behavior:

- Reload systemd daemon.
- Enable timer.
- Start timer.

Example maintainer script behavior:

```bash
systemctl daemon-reload || true
systemctl enable --now caramos-ota-check.timer || true
```

For Debian packages, this should be integrated carefully through maintainer scripts or debhelper where appropriate.

---

## 14. Component Packages for OTA 1.0.2

The first OTA release is expected to ship separate component packages. `caramos-ota` coordinates them but should not contain all unrelated payload files itself.

### 14.1 `caramos-zram-config`

Goal:

- Configure default ZRAM size to 50% of RAM.

Need to confirm during implementation:

- Which service/config controls ZRAM on the current CaramOS base.
- Whether the target file is owned by another package.
- Whether `Replaces`/`Breaks` is needed.

### 14.2 `caramos-mintreport-branding`

Goal:

- Update MintReport branding for CaramOS.

Need to confirm during implementation:

- Exact asset paths.
- Exact file owner using `dpkg -S`.
- Whether replacement conflicts with Linux Mint packages.

### 14.3 `caramos-mintwelcome-l10n`

Goal:

- Update MintWelcome localization/translation files.

Need to confirm during implementation:

- Source `.po` files.
- Generated `.mo` paths.
- Build process for translations.
- File ownership and package conflict rules.

---

## 15. Debian Packaging Notes

Expected `debian/control` fields:

```debcontrol
Source: caramos-ota
Section: admin
Priority: optional
Maintainer: Vietnam Linux Family <developer@vietnamlinuxfamily.net>
Standards-Version: 4.6.2
Build-Depends: debhelper-compat (= 13)
Rules-Requires-Root: no

Package: caramos-ota
Architecture: all
Depends: ${misc:Depends}, bash, apt, coreutils, dpkg, systemd, policykit-1, python3, python3-gi, gir1.2-gtk-3.0
Description: CaramOS over-the-air update helper
 Provides a CaramOS-specific OTA update command, daily update check,
 desktop notifier, state tracking, logs, and best-effort rollback support.
```

Notes:

- `Architecture: all` is appropriate if scripts and data are architecture-independent.
- `policykit-1` package naming may need confirmation on Ubuntu 24.04/Mint 22.
- `python3-gi` and `gir1.2-gtk-3.0` are needed for the GTK notifier.
- If the notifier is split later, GUI dependencies can move to a separate package, but v1 keeps one package for simplicity.

Expected `debian/source/format`:

```text
3.0 (native)
```

Expected `debian/rules`:

```makefile
#!/usr/bin/make -f
%:
	dh $@
```

---

## 16. Implementation Safety Rules

### 16.1 Shell safety

The main CLI should use strict shell behavior:

```bash
set -euo pipefail
```

Care is needed because `set -e` can behave unexpectedly in conditionals and pipelines. Every command expected to fail sometimes should be handled intentionally.

### 16.2 Input validation

Validate:

- CLI options.
- Manifest schema.
- Manifest package names.
- Manifest release string.
- Codename.
- State file shape before trusting it.

Never pass unvalidated package names to APT commands.

### 16.3 APT invocation

Prefer argument arrays in Bash.

Good pattern:

```bash
apt-get install --yes -- "${packages[@]}"
```

Avoid constructing a command string and evaluating it.

Never use `eval`.

### 16.4 Logging

Logs should go to:

```text
/var/log/caramos-ota/YYYY-MM-DD.log
```

Log:

- command start/end,
- version,
- detected OS info,
- repository check result,
- APT update result,
- selected packages,
- transaction id,
- failures.

Do not log:

- passwords,
- authentication tokens,
- unrelated environment variables,
- full user environment.

### 16.5 GUI rendering

The GUI must treat state file content as untrusted data.

For GTK labels:

- Do not use markup unless strictly needed.
- If markup is used, escape all dynamic text.
- Prefer plain text labels for package names and descriptions.

### 16.6 Privilege boundaries

- Notifier runs as user.
- CLI runs as root.
- Notifier must not edit system files.
- Notifier should only read `state.json` and spawn `pkexec`.
- CLI must perform all security checks even when invoked from GUI.

---

## 17. Error Handling Policy

General rule: show a short friendly error, log detailed context.

| Error | User-facing behavior |
|---|---|
| Not root | Tell user to run `sudo caramos-ota` |
| Not CaramOS | Refuse to run |
| Missing repository | Refuse and show expected repo |
| Missing keyring | Refuse and show expected key path |
| APT update failed | Stop, log details |
| Package unavailable | Stop, show package name |
| Broken dpkg state | Stop, suggest `sudo caramos-ota --repair` |
| Lock already held | Stop, tell user another operation is running |
| Rollback incomplete | Report which packages failed |
| GUI cannot read state | Exit silently or show no update, depending on context |

---

## 18. Testing Checklist

### 18.1 Static checks

- `shellcheck usr/bin/caramos-ota`
- `bash -n usr/bin/caramos-ota`
- `python3 -m py_compile usr/bin/caramos-ota-notifier`
- `desktop-file-validate etc/xdg/autostart/caramos-ota-notifier.desktop`
- Validate XML policy with an XML parser.

### 18.2 Package build checks

From `packages/caramos-ota`:

```bash
dpkg-buildpackage -us -uc
```

Then inspect package:

```bash
dpkg-deb -c ../caramos-ota_VERSION_all.deb
dpkg-deb -I ../caramos-ota_VERSION_all.deb
```

### 18.3 CLI behavior tests

Test cases:

1. `caramos-ota --help` works without root.
2. `caramos-ota --version` works without root.
3. `caramos-ota --check` without root gives a clear error.
4. `sudo caramos-ota --check` on CaramOS succeeds.
5. Missing `/etc/caramos-release` refuses to run.
6. Wrong `NAME` refuses to run.
7. Wrong codename refuses to run.
8. Missing PPA refuses to run.
9. Missing keyring refuses to run.
10. No updates available exits cleanly.
11. Updates available are displayed correctly.
12. User answers `n`, no packages are installed.
13. User answers `Y`, packages are installed.
14. `--yes` skips confirmation.
15. `--dry-run` does not install packages.
16. `--status` prints state.
17. `--repair` runs repair flow.
18. `--rollback` asks for confirmation and logs result.
19. Two simultaneous runs cannot both proceed.

### 18.4 GUI tests

1. No `available_update`: notifier exits silently.
2. Valid `available_update`: dialog appears.
3. Dialog displays Vietnamese text correctly.
4. Long package descriptions do not break layout.
5. `Đóng` closes without installing.
6. `Cập nhật` triggers pkexec.
7. Authentication cancel is handled cleanly.
8. Successful update shows success dialog.
9. Failed update shows repair suggestion.
10. Malformed state file does not crash the notifier.

### 18.5 systemd tests

```bash
systemctl status caramos-ota-check.timer
systemctl list-timers | grep caramos-ota
systemctl start caramos-ota-check.service
journalctl -u caramos-ota-check.service
```

Expected:

- Timer is enabled.
- Timer runs daily.
- Service exits successfully when no update is available.
- Service logs clear errors when network/repository is unavailable.

### 18.6 ISO integration tests

1. Add `caramos-ota` to `config/packages.txt`.
2. Add `/etc/caramos-release` to overlay.
3. Add PPA source list and keyring to overlay.
4. Build ISO.
5. Boot fresh VM.
6. Confirm `caramos-ota --version` works.
7. Confirm timer is enabled.
8. Confirm notifier autostarts after login.
9. Confirm `sudo caramos-ota --check` works.
10. Confirm updates install from PPA.

---

## 19. Implementation Phases

### Phase 1 — Prerequisites

1. Create `config/includes.chroot/etc/caramos-release`.
2. Add CaramOS PPA source list to ISO overlay.
3. Add CaramOS PPA keyring to ISO overlay.
4. Confirm Launchpad PPA package publishing flow.
5. Confirm package versions for the first OTA release.

### Phase 2 — Component packages

1. Create `caramos-zram-config`.
2. Create `caramos-mintreport-branding`.
3. Create `caramos-mintwelcome-l10n`.
4. Build each package locally.
5. Install each package in a VM.
6. Check file ownership conflicts.
7. Add `Replaces`/`Breaks` only where required.

### Phase 3 — `caramos-ota`

1. Create Debian package skeleton.
2. Implement `usr/bin/caramos-ota`.
3. Implement `usr/bin/caramos-ota-notifier`.
4. Add `manifest.json`.
5. Add systemd timer/service.
6. Add autostart desktop entry.
7. Add polkit policy.
8. Add maintainer scripts.
9. Build `.deb`.
10. Install locally and test.

### Phase 4 — PPA upload

1. Build source packages.
2. Sign/upload to Launchpad PPA.
3. Wait for build and publish.
4. Test install from PPA on fresh VM.

### Phase 5 — ISO integration

1. Add the OTA package and repository config to the ISO build.
2. Build a fresh CaramOS ISO.
3. Install in VM.
4. Verify daily check, GUI notifier, and manual CLI flow.

---

## 20. Open Questions Before Coding

These should be confirmed before implementation starts:

1. Exact maintainer name and email for `debian/control`.
2. Exact first OTA version: likely `1.0.2`.
3. Whether `caramos-ota` package version should always match CaramOS OTA release version.
4. Exact PPA signing key export process and keyring file source.
5. Whether all GUI text should be Vietnamese only or bilingual.
6. Whether state file should keep unlimited transactions or only the latest N entries.
7. Whether `--rollback` should be hidden/advanced because rollback is best-effort.
8. Whether `--check` should require root, or allow non-root check with limited behavior.
9. Whether GUI notifier should remind every login or suppress repeated prompts for the same release.
10. Whether update descriptions should live in local manifest only or be fetched from package metadata later.

Recommended v1 answers if no further decision is made:

1. Use Vietnam Linux Family maintainer identity.
2. Use `1.0.2`.
3. Match package version to OTA release version.
4. Export Launchpad/PPA public key into `/usr/share/keyrings/caramos-archive-keyring.gpg`.
5. GUI Vietnamese, CLI English.
6. Keep latest 20 transactions.
7. Keep `--rollback`, but clearly label it best-effort.
8. Require root for `--check` because it runs `apt-get update` and writes state.
9. Remind once per day after timer check.
10. Use local manifest in v1.

---

## 21. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| OTA package overwrites files from Mint packages | Check `dpkg -S`; use `Replaces`/`Breaks` only when needed |
| PPA not available | Stop cleanly and log details |
| PPA package not published yet | Show no update or package unavailable; do not crash |
| Broken APT/dpkg state | Stop and suggest `sudo caramos-ota --repair` |
| Rollback cannot fully restore old version | Best-effort rollback with explicit reporting |
| GUI runs privileged operations unsafely | GUI only calls `pkexec /usr/bin/caramos-ota --upgrade --yes`; CLI revalidates everything |
| Two updater instances conflict | Use `flock` lock file |
| Malformed manifest/state causes script errors | Validate JSON/schema and fail closed |
| User runs on Ubuntu/Mint | Require `/etc/caramos-release` |
| Daily timer runs without internet | Fail gracefully, log, retry next day |

---

## 22. Definition of Done

`caramos-ota` v1 is considered ready when:

- `caramos-ota` package builds successfully.
- The package installs cleanly on CaramOS.
- `sudo caramos-ota` performs check, confirmation, install, state update, and logging.
- `sudo caramos-ota --check` writes update state for the GUI.
- `sudo caramos-ota --status` shows useful information.
- `sudo caramos-ota --repair` handles broken package states as documented.
- `sudo caramos-ota --rollback` performs best-effort rollback or explains why it cannot.
- Desktop notifier appears only when updates are available.
- Desktop notifier can trigger update through pkexec.
- systemd timer runs daily.
- Non-CaramOS systems are rejected.
- Concurrent runs are blocked.
- First OTA component packages are published in the PPA.
- Fresh ISO install can receive updates through the OTA flow.

---

## 23. Additional Confirmed Design Decisions

### 23.1 Non-goals in v1

In v1, `caramos-ota` is **not** intended to replace the whole system update stack.

Specifically:

- It does not replace `apt upgrade`.
- It does not replace Linux Mint Update Manager.
- It only manages CaramOS-specific updates.
- It does not silently install updates in the background.
- It does not support testing/dev channels.
- It does not perform major Ubuntu/Mint base upgrades.
- It does not guarantee perfect 100% rollback.

### 23.2 Architecture overview

Main flow:

```text
systemd timer
    ↓ daily
/usr/bin/caramos-ota --check
    ↓ writes
/var/lib/caramos-ota/state.json
    ↓ read by desktop session
/usr/bin/caramos-ota-notifier
    ↓ user clicks "Cập nhật"
pkexec /usr/bin/caramos-ota --upgrade --yes
    ↓
APT + official CaramOS PPA
    ↓
state.json + /var/log/caramos-ota/YYYY-MM-DD.log
```

Component responsibilities:

| Component | Responsibility |
|---|---|
| `caramos-ota` | Main root CLI for check/install/repair/rollback |
| `caramos-ota-notifier` | User-session GUI; reads state and calls `pkexec` |
| systemd timer | Checks daily, never installs packages |
| manifest | Defines packages in an OTA release |
| state file | Stores check/update/transaction state |
| log file | Debugging and failure audit trail |
| PPA | Official package source |

### 23.3 State data flow

`state.json` is the bridge between the CLI, timer, and GUI.

Rules:

- `caramos-ota --check` writes `last_check`.
- If updates are available, `--check` writes `available_update`.
- If no update is available, `available_update` is set to `null`.
- The GUI notifier only reads `available_update`.
- The GUI must not modify state by itself.
- After a successful upgrade, the CLI clears `available_update`.
- After a failed upgrade, the CLI records a `failed` transaction and keeps detailed logs.
- When the user clicks `Đóng` in the GUI, no suppress state is written.
- If the update is still available tomorrow, the popup appears again.

### 23.4 Exit codes

The CLI should use stable exit codes so systemd and automation can understand results.

| Code | Meaning |
|---|---|
| `0` | Success, including no-update cases |
| `1` | Generic unclassified error |
| `2` | Root privileges required |
| `3` | Not CaramOS or invalid `/etc/caramos-release` |
| `4` | Missing/invalid repository or keyring |
| `5` | APT/dpkg error |
| `6` | Manifest/state error or parse failure |
| `7` | Lock already held by another process |
| `8` | User cancelled |

### 23.5 Versioning policy

v1 convention:

| Item | Version format |
|---|---|
| Manifest release | `1.0.2` |
| Debian package version | `1.0.2-0caramos1` |
| Component package version | Same version line, for example `1.0.2-0caramos1` |
| Displayed CaramOS release | `1.0.2` |

Example:

```text
manifest release:              1.0.2
caramos-ota Debian version:    1.0.2-0caramos1
caramos-zram-config version:   1.0.2-0caramos1
```

`-0caramos1` is the Debian revision used for CaramOS packaging.

### 23.6 Package update selection algorithm

Package selection flow:

1. Read `/usr/share/caramos-ota/manifest.json`.
2. Validate `schema`, `release`, and `codename`.
3. Validate each package name with an allow-list regex.
4. For each package:
   - read installed version with `dpkg-query`,
   - read candidate version with `apt-cache policy`,
   - compare versions with `dpkg --compare-versions`,
   - if not installed or lower than `min_version`, add to update list.
5. If the candidate version is missing or lower than `min_version`, stop and report the missing package clearly.
6. Install only when all required packages are valid.
7. Invoke APT with argument arrays, never by constructing command strings.

Recommended package-name validation pattern:

```text
^[a-z0-9][a-z0-9+.-]+$
```

### 23.7 Transaction model

Every upgrade should create an explicit transaction.

Transaction statuses:

| Status | Meaning |
|---|---|
| `pending` | Started but not completed |
| `success` | Upgrade completed successfully |
| `failed` | Upgrade failed or was interrupted |
| `rolled_back` | Transaction was rolled back best-effort |

Example transaction:

```json
{
  "id": "20260526-160500",
  "status": "success",
  "started_at": "2026-05-26T16:05:00+07:00",
  "finished_at": "2026-05-26T16:06:10+07:00",
  "manifest_release": "1.0.2",
  "packages": [
    {
      "name": "caramos-zram-config",
      "old_version": null,
      "new_version": "1.0.2-0caramos1",
      "action": "install"
    }
  ]
}
```

Rollback uses the latest successful transaction and processes packages in reverse order.

### 23.8 Configuration policy

v1 has **no separate config file** such as `/etc/caramos-ota/config`.

Reasons:

- Reduce the risk of users breaking repository/channel settings.
- Keep behavior predictable.
- Important values are controlled by the package and ISO.

If configuration is added later, it should only expose safe options such as log level or reminder policy.

### 23.9 Logging format and logrotate

Logs use a text format. Each line contains an ISO timestamp, level, and message.

Example:

```text
2026-05-26T17:00:00+07:00 [INFO] Starting caramos-ota 1.0.2-0caramos1
2026-05-26T17:00:01+07:00 [INFO] CaramOS detected: 1.0.1 noble stable
2026-05-26T17:00:03+07:00 [ERROR] Missing repository keyring: /usr/share/keyrings/caramos-archive-keyring.gpg
```

Add logrotate config:

```text
/etc/logrotate.d/caramos-ota
```

Recommended policy:

- Keep 14 days or 14 files.
- Rotate daily.
- Compress old logs.
- Do not fail if the log file does not exist yet.

### 23.10 Privacy policy

v1 privacy commitments:

- No telemetry.
- No machine ID upload.
- No package list/user data upload to a custom server.
- No user data collection through the GUI.
- No passwords/tokens/full environment in logs.
- Network access only goes through configured APT/PPA sources.

### 23.11 Minimal threat model

| Threat | Mitigation |
|---|---|
| Package name injection | Validate allow-list regex before calling APT |
| Fake/tampered PPA repository | Require `signed-by` keyring and APT signature verification |
| GUI/pkexec abuse | Policy only allows `/usr/bin/caramos-ota`; CLI validates args |
| Normal user modifies state | State is root-owned; validate schema when reading |
| Broken/tampered manifest | Validate schema/codename/package names and fail closed |
| Two instances run at once | Use a global `flock` lock |
| APT/dpkg interruption | Transaction status plus `--repair` |

### 23.12 Dependency groups

Dependencies should be documented by group.

CLI runtime:

- `bash`
- `apt`
- `dpkg`
- `coreutils`
- `util-linux` for `flock`
- `systemd`

GUI runtime:

- `python3`
- `python3-gi`
- `gir1.2-gtk-3.0`
- `pkexec`/the matching polkit package on Ubuntu 24.04

Build-time:

- `debhelper-compat (= 13)`
- `dpkg-dev`

Test/validation:

- `shellcheck`
- `desktop-file-utils`
- XML parser/linter

### 23.13 Maintainer release workflow

README only keeps a short note. The detailed workflow will live in:

```text
packages/caramos-ota/RELEASE.md
```

README should link to `RELEASE.md` after that file is created.

Planned `RELEASE.md` contents:

1. Bump version.
2. Update manifest.
3. Update changelog.
4. Build package.
5. Upload to PPA.
6. Wait for Launchpad publishing.
7. Test in VM.
8. Integrate into ISO if needed.

### 23.14 Release notes in manifest

The manifest should include bilingual release notes.

Example:

```json
{
  "schema": 1,
  "release": "1.0.2",
  "codename": "noble",
  "release_notes_vi": [
    "Cải thiện cấu hình ZRAM mặc định.",
    "Cập nhật branding MintReport cho CaramOS."
  ],
  "release_notes_en": [
    "Improve default ZRAM configuration.",
    "Update MintReport branding for CaramOS."
  ],
  "components": []
}
```

The GUI prefers `release_notes_vi`. The CLI may use `release_notes_en`.

### 23.15 GUI update progress

Once APT has started, the GUI has **no real Cancel button**.

Reasons:

- Cancelling APT mid-operation can leave dpkg in a broken state.
- Recovery is possible, but users should not be encouraged to interrupt the update.

The GUI should display:

```text
Đang cập nhật CaramOS...
Vui lòng không tắt máy hoặc đóng tiến trình cập nhật.
```

If the update fails, instruct the user to run:

```bash
sudo caramos-ota --repair
```

### 23.16 Network/offline behavior

When offline or when the PPA is temporarily unavailable:

- CLI shows a clear error and writes detailed logs.
- The systemd timer only logs the error and does not show a GUI popup for background check failures.
- The next scheduled check retries.
- Do not retry too many times in one check run.
- Respect existing APT proxy/network configuration.

### 23.17 Compatibility matrix

| CaramOS | Base | Ubuntu codename | Status |
|---|---|---|---|
| `1.0.x` | Linux Mint 22.x | `noble` | Supported |
| `2.x` | TBD | TBD | Future |
| Ubuntu/Mint that is not CaramOS | Any | Any | Unsupported |

### 23.18 Uninstall behavior

On package remove:

- Stop/disable the timer.
- Keep state in `/var/lib/caramos-ota`.
- Keep logs in `/var/log/caramos-ota`.

On package purge:

- Remove `/var/lib/caramos-ota`.
- Remove config/package-owned files.
- Policy for `/var/log/caramos-ota` will be decided later; default should keep logs for debugging unless there is a reason to remove them.

### 23.19 Recovery scenarios

At minimum, v1 must clearly handle interrupted APT/dpkg states.

Recommended user-facing message:

```text
The package database appears to be interrupted or broken.
Please run:
  sudo caramos-ota --repair
```

`--repair` runs:

```bash
dpkg --configure -a
apt-get --fix-broken install
```

Other scenarios should be logged and handled by failing closed.

### 23.20 Final implementation decisions before coding

Additional decisions confirmed before coding starts:

| Item | Decision |
|---|---|
| Maintainer email | `developer@vietnamlinuxfamily.net` |
| JSON handling | Use `python3`; do not add a `jq` dependency in v1 |
| GUI progress | Use an indeterminate progress bar/spinner; do not parse detailed APT progress in v1 |
| `--check` non-root mode | Defer; v1 still prioritizes root because it runs `apt-get update` and writes state |
| State schema | Add `"schema": 1` to `state.json` |
| Purge log policy | Keep `/var/log/caramos-ota` on purge for debugging/audit purposes |

Additional explanation:

- **GPG/keyring:** the ISO still needs to ship `/usr/share/keyrings/caramos-archive-keyring.gpg`. The Launchpad/PPA key export process belongs to PPA/ISO integration and does not block CLI implementation.
- **Polkit package:** the exact polkit dependency name on Ubuntu 24.04/Mint 22 will be verified while writing `debian/control`; the design requires working `pkexec` support.
- **State schema:** the state file should start like this:

```json
{
  "schema": 1,
  "last_check": null,
  "last_successful_upgrade": null,
  "installed_release": null,
  "available_update": null,
  "transactions": []
}
```

---

### 23.21 Acceptance criteria in Given/When/Then format

#### Fresh VM with update available

```text
Given a fresh CaramOS 1.0.1 VM
And the official CaramOS PPA is configured
And OTA release 1.0.2 is available
When the user runs sudo caramos-ota
Then the tool lists all required update packages
And asks for confirmation
And installs packages after confirmation
And writes a success transaction
And --status reports installed_release 1.0.2
```

#### No updates available

```text
Given a CaramOS VM already on the latest OTA release
When the user runs sudo caramos-ota --check
Then the tool exits with code 0
And reports no updates available
And clears available_update in state.json
```

#### GUI notifier

```text
Given state.json contains available_update
When the desktop user logs in
Then caramos-ota-notifier shows a Vietnamese update dialog
And clicking Cập nhật runs pkexec caramos-ota --upgrade --yes
```

#### Not CaramOS

```text
Given a Linux Mint or Ubuntu system without /etc/caramos-release
When the user runs sudo caramos-ota
Then the tool exits with code 3
And refuses to install anything
```

#### Best-effort rollback

```text
Given the latest transaction completed successfully
When the user runs sudo caramos-ota --rollback
Then the tool shows affected packages
And asks for confirmation
And attempts rollback in reverse transaction order
And reports any package that cannot be rolled back
```

---

## 24. Short Summary

`caramos-ota` will be the single official CaramOS update entry point.

For users:

```bash
sudo caramos-ota
```

For desktop users:

- CaramOS checks daily.
- If an update exists, a Vietnamese popup appears.
- The user can read what changed and click update.

For maintainers:

- Updates are shipped as normal Debian packages through the official CaramOS PPA.
- `caramos-ota` coordinates detection, UX, logs, state, and rollback.
- The implementation remains transparent, scriptable, and compatible with Ubuntu/Mint packaging practices.
