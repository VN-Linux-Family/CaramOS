# CaramOS OTA — Low-level Implementation Breakdown

> **Package:** `caramos-ota`  
> **Purpose:** Break the README design into concrete implementation tasks.  
> **Default README:** [README.md](README.md)  
> **English README:** [README_EN.md](README_EN.md)  
> **Maintainer:** Vietnam Linux Family <developer@vietnamlinuxfamily.net>

---

## 0. Scope of this plan

This file is the actionable implementation checklist for `caramos-ota`.

It is lower-level than the README and should be used while coding.

Rules:

- Implement CLI first.
- Implement GUI after CLI behavior is stable.
- Keep v1 simple and predictable.
- Do not add `jq`; use `python3` for JSON parsing/writing.
- Do not auto-install updates in the background.
- Do not support testing/dev channels in v1.
- Do not support major Ubuntu/Mint base upgrades in v1.

---

## 1. Target package tree

Final source tree should look like this:

```text
packages/caramos-ota/
├── README.md
├── README_EN.md
├── IMPLEMENTATION_PLAN.md
├── RELEASE.md                         # later, separate maintainer workflow
├── debian/
│   ├── changelog
│   ├── control
│   ├── install
│   ├── postinst
│   ├── prerm
│   ├── postrm
│   ├── rules
│   └── source/
│       └── format
├── etc/
│   ├── logrotate.d/
│   │   └── caramos-ota
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

---

## 2. Stage 0 — Prepare directories

### Tasks

- [ ] Create `packages/caramos-ota/debian/source/`.
- [ ] Create `packages/caramos-ota/usr/bin/`.
- [ ] Create `packages/caramos-ota/usr/share/caramos-ota/`.
- [ ] Create `packages/caramos-ota/usr/share/polkit-1/actions/`.
- [ ] Create `packages/caramos-ota/lib/systemd/system/`.
- [ ] Create `packages/caramos-ota/etc/xdg/autostart/`.
- [ ] Create `packages/caramos-ota/etc/logrotate.d/`.

### Done when

- [ ] All package directories exist.
- [ ] No generated build artifacts are committed inside the source tree.

---

## 3. Stage 1 — Debian packaging skeleton

### 3.1 `debian/source/format`

Create:

```text
debian/source/format
```

Content:

```text
3.0 (native)
```

Done when:

- [ ] File exists.
- [ ] Package is treated as native source package.

### 3.2 `debian/rules`

Create:

```makefile
#!/usr/bin/make -f
%:
	dh $@
```

Tasks:

- [ ] Mark executable.
- [ ] Keep minimal unless custom install logic becomes necessary.

Done when:

- [ ] `debian/rules` is executable.
- [ ] `dpkg-buildpackage` can invoke debhelper.

### 3.3 `debian/control`

Initial fields:

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
Depends: ${misc:Depends}, bash, apt, coreutils, dpkg, systemd, util-linux, python3, python3-gi, gir1.2-gtk-3.0
Description: CaramOS over-the-air update helper
 Provides a CaramOS-specific OTA update command, daily update check,
 desktop notifier, state tracking, logs, and best-effort rollback support.
```

Tasks:

- [ ] Verify actual polkit/pkexec dependency name on Ubuntu 24.04/Mint 22.
- [ ] Add the correct polkit package to `Depends`.
- [ ] Keep `Architecture: all`.
- [ ] Keep package description concise.

Done when:

- [ ] `dpkg-checkbuilddeps` reports no missing build dependencies on builder.
- [ ] Runtime dependencies cover CLI, GUI, timer, and pkexec flow.

### 3.4 `debian/changelog`

Initial version:

```text
caramos-ota (1.0.2-0caramos1) noble; urgency=medium

  * Initial CaramOS OTA updater package.

 -- Vietnam Linux Family <developer@vietnamlinuxfamily.net>  DATE
```

Tasks:

- [ ] Use valid Debian changelog date format.
- [ ] Keep distribution as `noble` for CaramOS 1.x.

Done when:

- [ ] `dpkg-parsechangelog` parses successfully.

### 3.5 `debian/install`

Should map source files to installed paths.

Expected entries:

```text
usr/bin/caramos-ota usr/bin/
usr/bin/caramos-ota-notifier usr/bin/
usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json usr/share/caramos-ota/
usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy usr/share/polkit-1/actions/
lib/systemd/system/caramos-ota-check.service lib/systemd/system/
lib/systemd/system/caramos-ota-check.timer lib/systemd/system/
etc/xdg/autostart/caramos-ota-notifier.desktop etc/xdg/autostart/
etc/logrotate.d/caramos-ota etc/logrotate.d/
```

Done when:

- [ ] `dpkg-deb -c` shows files in correct installed locations.

### 3.6 Maintainer scripts

Create:

- [ ] `debian/postinst`
- [ ] `debian/prerm`
- [ ] `debian/postrm`

Expected behavior:

- `postinst configure`:
  - [ ] create `/var/lib/caramos-ota`.
  - [ ] create `/var/log/caramos-ota`.
  - [ ] ensure root ownership.
  - [ ] reload systemd.
  - [ ] enable/start `caramos-ota-check.timer`.
- `prerm remove`:
  - [ ] stop/disable timer if systemd exists.
- `postrm purge`:
  - [ ] remove `/var/lib/caramos-ota`.
  - [ ] keep `/var/log/caramos-ota` for debug/audit.
  - [ ] reload systemd.

Done when:

- [ ] install/remove/purge flows do not fail if systemd is unavailable.
- [ ] scripts use `set -e` and guard non-critical commands with `|| true` only where appropriate.

---

## 4. Stage 2 — Manifest

Create:

```text
usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json
```

Initial v1 content:

```json
{
  "schema": 1,
  "release": "1.0.2",
  "codename": "noble",
  "release_notes_vi": [
    "Cải thiện cấu hình ZRAM mặc định.",
    "Cập nhật branding MintReport cho CaramOS.",
    "Cập nhật bản dịch MintWelcome cho CaramOS."
  ],
  "release_notes_en": [
    "Improve default ZRAM configuration.",
    "Update MintReport branding for CaramOS.",
    "Update MintWelcome translations for CaramOS."
  ],
  "release_notes_vi": [
    {
      "package": "migration 1.0.3→1.0.2",
      "required": true,
      "min_version": "1.0.2-0caramos1",
      "description": "Configure default ZRAM size to 50% of RAM"
    },
    {
      "package": "migration 1.0.2→1.0.2",
      "required": true,
      "min_version": "1.0.2-0caramos1",
      "description": "Update MintReport branding for CaramOS"
    },
    {
      "package": "migration 1.0.1→1.0.2",
      "required": true,
      "min_version": "1.0.2-0caramos1",
      "description": "Update MintWelcome translations for CaramOS"
    }
  ]
}
```

Tasks:

- [ ] Validate JSON syntax.
- [ ] Keep `schema: 1`.
- [ ] Keep `codename: noble` for CaramOS 1.x.
- [ ] Use `1.0.2-0caramos1` for component `min_version`.

Done when:

- [ ] `python3 -m json.tool manifest.json` passes.

---

## 5. Stage 3 — CLI foundation: `usr/bin/caramos-ota`

### 5.1 File basics

Tasks:

- [ ] Create executable Bash script.
- [ ] Use shebang `#!/usr/bin/env bash`.
- [ ] Use `set -euo pipefail`.
- [ ] Define constants:
  - [ ] `TOOL_VERSION="1.0.2-0caramos1"`
  - [ ] `STATE_DIR="/var/lib/caramos-ota"`
  - [ ] `STATE_FILE="/var/lib/caramos-ota/state.json"`
  - [ ] `LOCK_FILE="/var/lib/caramos-ota/lock"`
  - [ ] `LOG_DIR="/var/log/caramos-ota"`
  - [ ] `MIGRATION_INDEX="caramos_ota_update/migrations/migration.json"`
  - [ ] `RELEASE_FILE="/etc/caramos-release"`

Done when:

- [ ] `bash -n usr/bin/caramos-ota` passes.
- [ ] Script is executable.

### 5.2 CLI parser

Supported options:

- [ ] no option: check then upgrade with confirmation.
- [ ] `--check`
- [ ] `--upgrade`
- [ ] `--yes`
- [ ] `--dry-run`
- [ ] `--status`
- [ ] `--repair`
- [ ] `--rollback`
- [ ] `--version`
- [ ] `--help`

Rules:

- [ ] Unknown option exits with code `1`.
- [ ] `--help` and `--version` do not require root.
- [ ] Mutually incompatible options are rejected.
- [ ] `--yes` only makes sense with default upgrade flow or `--upgrade`.

Done when:

- [ ] Every supported option has a defined code path.
- [ ] Unknown options are handled cleanly.

### 5.3 Exit codes

Implement constants:

```bash
EXIT_OK=0
EXIT_ERROR=1
EXIT_NOT_ROOT=2
EXIT_NOT_CARAMOS=3
EXIT_REPO=4
EXIT_APT=5
EXIT_STATE=6
EXIT_LOCK=7
EXIT_CANCEL=8
```

Done when:

- [ ] Major failure paths use the documented exit code.

### 5.4 Logging

Tasks:

- [ ] Create log directory if missing.
- [ ] Log file format: `/var/log/caramos-ota/YYYY-MM-DD.log`.
- [ ] Implement `log_info`, `log_warn`, `log_error`.
- [ ] Format each line:

```text
ISO_TIMESTAMP [LEVEL] message
```

Rules:

- [ ] Do not log passwords/tokens/full environment.
- [ ] Log start/end of each operation.
- [ ] Log APT failures with enough detail.

Done when:

- [ ] Running any root command creates a dated log file.

### 5.5 Root check

Rules:

- [ ] Required for all commands except `--help` and `--version`.
- [ ] Non-root exits with code `2`.
- [ ] Message suggests `sudo caramos-ota`.

Done when:

- [ ] `caramos-ota --help` works as user.
- [ ] `caramos-ota --version` works as user.
- [ ] `caramos-ota --check` as user exits code `2`.

### 5.6 Locking

Tasks:

- [ ] Ensure `/var/lib/caramos-ota` exists.
- [ ] Open lock file descriptor.
- [ ] Acquire with `flock -n`.
- [ ] Exit code `7` if lock unavailable.

Rules:

- [ ] Use one global lock for check/upgrade/repair/rollback.
- [ ] Do not acquire lock for `--help` or `--version`.

Done when:

- [ ] Two simultaneous root runs cannot both proceed.

### 5.7 CaramOS detection

Tasks:

- [ ] Check `/etc/caramos-release` exists.
- [ ] Source/parse known key-value fields safely.
- [ ] Require `NAME="CaramOS"`.
- [ ] Require `UBUNTU_CODENAME="noble"` in v1.
- [ ] Require or warn on `CHANNEL="stable"`.

Done when:

- [ ] Missing file exits code `3`.
- [ ] Wrong OS exits code `3`.
- [ ] Valid file proceeds.

### 5.8 Repository/keyring verification

Tasks:

- [ ] Check `/usr/share/keyrings/caramos-archive-keyring.gpg` exists and is readable.
- [ ] Search APT sources for `ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os`.
- [ ] Verify `noble` appears in the matching source.
- [ ] Verify `signed-by=/usr/share/keyrings/caramos-archive-keyring.gpg` appears.

Error behavior:

- [ ] Missing keyring: show exact missing path.
- [ ] Missing source: show expected source entry.
- [ ] Wrong codename/source: show what was expected.
- [ ] Exit code `4`.

Done when:

- [ ] User knows exactly what is missing.

---

## 6. Stage 4 — JSON helpers through Python 3

Do not add `jq`.

### 6.1 Manifest reader

Implement helper using `python3` to:

- [ ] Load manifest JSON.
- [ ] Validate `schema == 1`.
- [ ] Validate `release` is string.
- [ ] Validate `codename == noble`.
- [ ] Validate `components` is list.
- [ ] Validate package names with regex:

```text
^[a-z0-9][a-z0-9+.-]+$
```

Output format for Bash:

- [ ] Prefer TSV lines for packages:

```text
package<TAB>min_version<TAB>description
```

Done when:

- [ ] Malformed manifest exits code `6`.
- [ ] Valid manifest produces deterministic migration release metadata.

### 6.2 State initialization

Initial state:

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

Tasks:

- [ ] Create state file if missing.
- [ ] Validate existing state has `schema: 1`.
- [ ] If corrupt, back up to `state.json.corrupt.TIMESTAMP` and create fresh state.
- [ ] Keep root ownership.
- [ ] Mode `0644` so GUI can read.

Done when:

- [ ] GUI user can read state.
- [ ] Normal user cannot edit state.

### 6.3 State writer functions

Implement Python-backed operations:

- [ ] Update `last_check`.
- [ ] Set `available_update` object.
- [ ] Clear `available_update`.
- [ ] Add transaction.
- [ ] Update transaction status.
- [ ] Set `last_successful_upgrade`.
- [ ] Set `installed_release`.
- [ ] Keep latest 20 transactions.

Done when:

- [ ] State writes are atomic enough for v1.
- [ ] JSON remains pretty/valid after each write.

---

## 7. Stage 5 — Check/update detection

### 7.1 `apt-get update`

Tasks:

- [ ] Run `apt-get update` during `--check`, default flow, and `--upgrade`.
- [ ] Log output or error summary.
- [ ] Exit code `5` on failure.

Done when:

- [ ] Offline/repo failure gives a clear CLI message and log entry.

### 7.2 Installed version detection

For each package:

- [ ] Use `dpkg-query -W -f='${Version}' PACKAGE`.
- [ ] If not installed, current version is `null` or `(new)`.

Done when:

- [ ] Missing package is treated as install candidate, not fatal by itself.

### 7.3 Candidate version detection

For each package:

- [ ] Use `apt-cache policy PACKAGE`.
- [ ] Extract `Candidate`.
- [ ] If candidate is `(none)`, treat as unavailable.

Done when:

- [ ] Missing PPA package is reported before any install starts.

### 7.4 Version comparison

For each package:

- [ ] Use `dpkg --compare-versions`.
- [ ] Update needed if current missing.
- [ ] Update needed if current `< min_version`.
- [ ] Candidate must be `>= min_version`.

Done when:

- [ ] The update list is correct and deterministic.

### 7.5 Write `available_update`

When updates exist:

- [ ] Write `available_update.detected_at`.
- [ ] Write `available_update.release`.
- [ ] Write `available_update.current_version` from `/etc/caramos-release`.
- [ ] Write migration release metadata with current/candidate/description.
- [ ] Include `release_notes_vi` and `release_notes_en`.

When no updates:

- [ ] Clear `available_update`.

Done when:

- [ ] GUI notifier can display update details from state only.

---

## 8. Stage 6 — Upgrade flow

### 8.1 Summary display

Before install:

- [ ] Print package table.
- [ ] Show current version.
- [ ] Show target release.
- [ ] Show release notes if available.

Done when:

- [ ] User can understand exactly what will change.

### 8.2 Confirmation

Rules:

- [ ] Ask `Install these updates? [Y/n]` unless `--yes`.
- [ ] `n` exits code `8`.
- [ ] Empty answer means yes.

Done when:

- [ ] User can cancel before APT install starts.

### 8.3 Transaction start

Before APT install:

- [ ] Create transaction with `status: pending`.
- [ ] Record `started_at`.
- [ ] Record package old/new/action.

Done when:

- [ ] A failed install still leaves useful transaction info.

### 8.4 APT install

Tasks:

- [ ] Build Bash array of validated package names.
- [ ] Run:

```bash
apt-get install --yes -- "${packages[@]}"
```

Rules:

- [ ] Never use `eval`.
- [ ] Never install package names not validated from manifest.
- [ ] On failure, transaction becomes `failed`.
- [ ] On success, transaction becomes `success`.

Done when:

- [ ] Package install succeeds from PPA in VM.

### 8.5 Success handling

On success:

- [ ] Clear `available_update`.
- [ ] Set `last_successful_upgrade`.
- [ ] Set `installed_release`.
- [ ] Print success summary.

Done when:

- [ ] `--status` reflects the new installed release.

### 8.6 Failure handling

On failure:

- [ ] Mark transaction `failed`.
- [ ] Tell user to run `sudo caramos-ota --repair`.
- [ ] Show log path.
- [ ] Exit code `5`.

Done when:

- [ ] User has clear next step after failure.

---

## 9. Stage 7 — Other CLI commands

### 9.1 `--status`

Show:

- [ ] CaramOS version.
- [ ] OTA tool version.
- [ ] Last check.
- [ ] Last successful upgrade.
- [ ] Installed release.
- [ ] Available update summary, if any.
- [ ] Latest transaction summary.

Done when:

- [ ] Useful for debugging without reading JSON manually.

### 9.2 `--dry-run`

Behavior:

- [ ] Run checks and detection.
- [ ] Show what would be installed.
- [ ] Do not install.
- [ ] Do not write success transaction.

Done when:

- [ ] Safe to run repeatedly.

### 9.3 `--repair`

Run:

```bash
dpkg --configure -a
apt-get --fix-broken install
```

Tasks:

- [ ] Log output.
- [ ] Exit code `5` if repair fails.
- [ ] Print clear result.

Done when:

- [ ] Broken dpkg state has a documented repair path.

### 9.4 `--rollback`

Behavior:

- [ ] Read latest `success` transaction.
- [ ] Show packages to remove/downgrade.
- [ ] Ask confirmation.
- [ ] Roll back in reverse package order.
- [ ] Remove packages that were newly installed.
- [ ] Downgrade upgraded packages only if old version is available.
- [ ] Mark transaction `rolled_back` if rollback completes sufficiently.
- [ ] Report packages that could not be rolled back.

Done when:

- [ ] Rollback is clearly best-effort.

---

## 10. Stage 8 — systemd timer/service

### 10.1 Service

Create:

```text
lib/systemd/system/caramos-ota-check.service
```

Content:

```ini
[Unit]
Description=CaramOS OTA check for updates
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/caramos-ota --check
```

Done when:

- [ ] `systemctl start caramos-ota-check.service` runs check.

### 10.2 Timer

Create:

```text
lib/systemd/system/caramos-ota-check.timer
```

Content:

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

Done when:

- [ ] Timer is enabled after package install.
- [ ] Timer appears in `systemctl list-timers`.

---

## 11. Stage 9 — logrotate

Create:

```text
etc/logrotate.d/caramos-ota
```

Suggested content:

```text
/var/log/caramos-ota/*.log {
    daily
    rotate 14
    compress
    missingok
    notifempty
    create 0640 root adm
}
```

Done when:

- [ ] Logrotate config validates.
- [ ] Old logs are rotated and compressed.

---

## 12. Stage 10 — polkit policy

Create:

```text
usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy
```

Tasks:

- [ ] Allow only `/usr/bin/caramos-ota`.
- [ ] Allow GUI auth.
- [ ] Use admin authentication.
- [ ] Do not allow arbitrary command execution.

Done when:

- [ ] `pkexec /usr/bin/caramos-ota --upgrade --yes` prompts for auth and runs.

---

## 13. Stage 11 — autostart desktop entry

Create:

```text
etc/xdg/autostart/caramos-ota-notifier.desktop
```

Content:

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

Done when:

- [ ] `desktop-file-validate` passes.
- [ ] Notifier starts after desktop login.

---

## 14. Stage 12 — GUI notifier

### 14.1 File basics

Create:

```text
usr/bin/caramos-ota-notifier
```

Tasks:

- [ ] Use Python 3.
- [ ] Import GTK3 via `gi.repository`.
- [ ] Read `/var/lib/caramos-ota/state.json`.
- [ ] Exit silently if no valid `available_update`.
- [ ] Treat state content as untrusted.

Done when:

- [ ] `python3 -m py_compile usr/bin/caramos-ota-notifier` passes.

### 14.2 Update available dialog

Show:

- [ ] Title: `CaramOS - Có bản cập nhật mới`.
- [ ] Current version.
- [ ] New release.
- [ ] Vietnamese release notes.
- [ ] Migration release metadata.
- [ ] Buttons: `Đóng`, `Cập nhật`.

Rules:

- [ ] Do not use unsafe markup for dynamic text.
- [ ] Long content should scroll or wrap.

Done when:

- [ ] User can understand update content before installing.

### 14.3 Update execution

When user clicks `Cập nhật`:

- [ ] Run `pkexec /usr/bin/caramos-ota --upgrade --yes`.
- [ ] Show indeterminate progress bar/spinner.
- [ ] Do not show a real Cancel button after APT starts.
- [ ] Tell user not to turn off the machine.

Done when:

- [ ] GUI can trigger CLI update through pkexec.

### 14.4 Result dialogs

On success:

- [ ] Show success message.
- [ ] Mention updated release if known.

On failure:

- [ ] Show failure message.
- [ ] Suggest `sudo caramos-ota --repair`.
- [ ] Show log path.

Done when:

- [ ] User has clear result and recovery instruction.

---

## 15. Stage 13 — Static validation

Run from `packages/caramos-ota`:

```bash
bash -n usr/bin/caramos-ota
python3 -m py_compile usr/bin/caramos-ota-notifier
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json
```

Optional if tools are installed:

```bash
shellcheck usr/bin/caramos-ota
desktop-file-validate etc/xdg/autostart/caramos-ota-notifier.desktop
```

Done when:

- [ ] Mandatory checks pass.
- [ ] Optional checks pass or known warnings are documented.

---

## 16. Stage 14 — Build package

Run from `packages/caramos-ota`:

```bash
dpkg-buildpackage -us -uc
```

Inspect result:

```bash
dpkg-deb -c ../caramos-ota_1.0.2-0caramos1_all.deb
dpkg-deb -I ../caramos-ota_1.0.2-0caramos1_all.deb
```

Done when:

- [ ] Build succeeds.
- [ ] Installed file paths are correct.
- [ ] Dependencies look correct.

---

## 17. Stage 15 — Local install test

On a VM/test system:

```bash
sudo apt install ./caramos-ota_1.0.2-0caramos1_all.deb
```

Test:

- [ ] `caramos-ota --help`
- [ ] `caramos-ota --version`
- [ ] `sudo caramos-ota --status`
- [ ] `sudo caramos-ota --check`
- [ ] systemd timer status
- [ ] log file creation
- [ ] state file creation

Done when:

- [ ] Package installs cleanly.
- [ ] Timer is enabled.
- [ ] State/log directories exist.

---

## 18. Stage 16 — Negative tests

Test failure behavior:

- [ ] Missing `/etc/caramos-release` exits code `3`.
- [ ] Wrong `NAME` exits code `3`.
- [ ] Wrong codename exits code `3`.
- [ ] Missing keyring exits code `4` and names missing keyring.
- [ ] Missing PPA source exits code `4` and shows expected source.
- [ ] Malformed manifest exits code `6`.
- [ ] Corrupt state gets backed up and regenerated.
- [ ] Concurrent runs: one exits code `7`.
- [ ] Offline APT failure exits code `5`.

Done when:

- [ ] Failure messages are specific and actionable.
- [ ] Logs contain enough detail.

---

## 19. Stage 17 — OTA update test with component packages

Prerequisite:

- [ ] Component packages exist in local repo or PPA:
  - [ ] `migration 1.0.3→1.0.2`
  - [ ] `migration 1.0.2→1.0.2`
  - [ ] `migration 1.0.1→1.0.2`

Test flow:

- [ ] Fresh CaramOS 1.0.1 VM.
- [ ] PPA configured.
- [ ] Keyring installed.
- [ ] Install `caramos-ota`.
- [ ] Run `sudo caramos-ota --check`.
- [ ] Verify `available_update` in state.
- [ ] Run `sudo caramos-ota`.
- [ ] Confirm install.
- [ ] Verify transaction `success`.
- [ ] Verify `installed_release: 1.0.2`.
- [ ] Verify `sudo caramos-ota --status`.

Done when:

- [ ] Fresh VM can receive OTA successfully.

---

## 20. Stage 18 — GUI test

Setup:

- [ ] Have valid `available_update` in state.
- [ ] Login to desktop session.

Test:

- [ ] Notifier starts from autostart.
- [ ] Dialog is Vietnamese.
- [ ] Release notes appear.
- [ ] Migration release metadata appears.
- [ ] `Đóng` closes without state mutation.
- [ ] `Cập nhật` triggers pkexec.
- [ ] Indeterminate progress appears.
- [ ] Success dialog appears on success.
- [ ] Failure dialog suggests `sudo caramos-ota --repair`.

Done when:

- [ ] GUI flow works for normal desktop user.

---

## 21. Stage 19 — Rollback test

Test:

- [ ] Install OTA update successfully.
- [ ] Run `sudo caramos-ota --rollback`.
- [ ] Confirm rollback.
- [ ] Verify newly installed packages are removed.
- [ ] Verify downgraded packages are attempted only when old version exists.
- [ ] Verify transaction status changes to `rolled_back` or reports partial rollback.

Done when:

- [ ] Rollback behavior is clearly best-effort and safe.

---

## 22. Stage 20 — ISO integration

Repository-level tasks:

- [ ] Add `caramos-ota` to `config/packages.txt`.
- [ ] Add `/etc/caramos-release` to `config/includes.chroot/etc/caramos-release`.
- [ ] Add PPA source list to overlay.
- [ ] Add keyring to overlay.
- [ ] Build ISO.
- [ ] Boot/install fresh VM.

Validation:

- [ ] `caramos-ota --version` works.
- [ ] Timer is enabled after install.
- [ ] Notifier autostarts.
- [ ] `sudo caramos-ota --check` works.
- [ ] OTA package update installs from PPA.

Done when:

- [ ] Fresh ISO install can receive CaramOS OTA update.

---

## 23. Implementation order recommendation

Recommended order:

1. Stage 0 — directories.
2. Stage 1 — Debian skeleton.
3. Stage 2 — manifest.
4. Stage 3 — CLI foundation.
5. Stage 4 — JSON helpers.
6. Stage 5 — check/update detection.
7. Stage 6 — upgrade flow.
8. Stage 7 — status/repair/rollback.
9. Stage 8–13 — systemd/logrotate/polkit/autostart/GUI/static checks.
10. Stage 14–21 — build, install, negative, OTA, GUI, rollback, ISO tests.

Do not start GUI before CLI state/check/upgrade behavior is stable.

---

## 24. First coding milestone

The first milestone should produce a package that can do:

```bash
caramos-ota --help
caramos-ota --version
sudo caramos-ota --status
sudo caramos-ota --check
```

Without implementing full GUI yet.

Milestone 1 acceptance:

- [ ] Package skeleton exists.
- [ ] CLI parses options.
- [ ] Logging works.
- [ ] Locking works.
- [ ] CaramOS detection works.
- [ ] Repository/keyring verification works.
- [ ] Manifest parsing works.
- [ ] State init/write works.
- [ ] `--check` writes `available_update` or clears it.

---

## 25. Notes for future files

Create later:

```text
packages/caramos-ota/RELEASE.md
```

Purpose:

- Maintainer release workflow.
- Version bump checklist.
- PPA upload checklist.
- Launchpad publish verification.
- VM release validation.


---

## Current release plan: CaramOS OTA 1.0.5

Release owner: **dungleviet**.

This implementation is now migration-driven and targets the release chain from existing CaramOS `1.0.1` installations to latest `1.0.5`. The released `caramos-ota` package must contain migrations and manifests for:

```text
1.0.1 → 1.0.2
1.0.2 → 1.0.3
1.0.3 → 1.0.4
1.0.4 → 1.0.5
```

End-user commands after the PPA package is published:

```bash
sudo apt update
sudo apt install caramos-ota
sudo caramos-ota
```

Maintainer release commands:

```bash
cd /home/dungleviet/Documents/CaramOS/packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/migrations/*/*.py
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
dpkg-buildpackage -us -uc -b
sudo ./tools/ship-ota-to-vm.sh
```

PPA release is performed by **dungleviet** after bumping `debian/changelog` to `1.0.5-0caramos1`:

```bash
debuild -S -sa
dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.5-0caramos1_source.changes
```

Validation must include:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
cat /etc/caramos-release
grep -E '^(VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release
sudo add-apt-repository -y ppa:mozillateam/ppa
sudo rm -f /etc/apt/sources.list.d/*mozillateam*
sudo apt update
```

Expected final metadata: CaramOS `1.0.5`, `VERSION_CODENAME=wilma`, `UBUNTU_CODENAME=noble`.
