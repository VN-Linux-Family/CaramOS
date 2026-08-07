# Contributing Guide — CaramOS

Thank you for your interest in CaramOS! This document describes how to contribute
under the project's current **OTA-first** model.

> [Tiếng Việt](CONTRIBUTING.md) · [README](README_EN.md)

---

## Table of Contents

- [Current Status](#current-status)
- [OTA-first Architecture](#ota-first-architecture)
- [Project Structure](#project-structure)
- [Build ISO](#build-iso)
- [Developing with OTA](#developing-with-ota)
- [Contribution Workflow](#contribution-workflow)
- [Code Standards](#code-standards)
- [Bug Reports and Feature Requests](#bug-reports-and-feature-requests)

---

## Current Status

CaramOS has moved to the **CaramOS OTA** update model.

- New ISO images are still built and released.
- Machines installed with CaramOS `1.0.1` do not need to reinstall the ISO.
- Users install CaramOS Update Center, then upgrade through OTA.

Command for users currently on CaramOS `1.0.1`:

```bash
curl -fsSL https://caramos.vietnamlinuxfamily.net/install-caramos-ota.sh | sudo bash
```

After installation, users should open **CaramOS Update Center** from the Start
Menu to check and upgrade to the latest version.

> [!IMPORTANT]
> Contributors/developers should not add new system updates directly to
> `config/hooks/live/`. If a change must apply to already-installed CaramOS
> machines, write an OTA migration in `packages/caramos-ota`.

---

## OTA-first Architecture

CaramOS still uses ISO remastering, but ISO builds now include an OTA bootstrap
step:

```text
Linux Mint ISO
  → extract rootfs
  → install packages + overlay + build-time hooks
  → build/install bundled caramos-ota
  → run caramos-ota-update migrations inside rootfs
  → repack squashfs + CaramOS ISO
```

Key points:

- `scripts/config.sh` stores ISO version and base migration version.
- `CARAMOS_MIGRATION_BASE_VERSION="1.0.1"` is kept so ISO builds run the full
  migration chain from the first Open Beta release to latest.
- `scripts/ota_bootstrap.sh` builds the `caramos-ota` package, installs it into
  the rootfs, and runs migrations before repacking the ISO.
- The resulting ISO is already at the latest state in the source tree.
- OTA is the upgrade path for users already installed from older ISOs.

### Do not code new user-facing updates into hooks

`config/hooks/live/` should only be used for true build-time/bootstrap tasks.
Examples:

- preparing the rootfs environment before OTA bootstrap runs;
- actions that only make sense during ISO build;
- build system fixes, boot branding, or foundational dependencies.

If a change must reach installed user machines — for example panel settings,
dconf, Fcitx5, desktop launchers, theme, `/etc/caramos-release`, package state —
write a migration.

---

## Project Structure

```text
CaramOS/
├── build.sh                         # ISO build entry point
├── Makefile                         # make build/release/quick/docker-build...
├── scripts/                         # ISO build modules
│   ├── config.sh                    # ISO version, migration base, mirror, output
│   ├── extract.sh                   # Mount ISO + unsquashfs
│   ├── customize.sh                 # Packages + overlay + hooks + OTA bootstrap
│   ├── ota_bootstrap.sh             # Build/install OTA package and run migrations
│   ├── repack.sh                    # mksquashfs + xorriso
│   ├── boot_config.sh               # Boot menu/Plymouth branding
│   └── utils.sh                     # Logging, deps, ISO helpers
├── config/                          # ISO/rootfs bootstrap layer
│   ├── packages.txt                 # Base packages installed when building ISO
│   ├── includes.chroot/             # Overlay copied into the rootfs
│   └── hooks/live/                  # Legacy build-time hooks, avoid adding new logic
├── packages/
│   └── caramos-ota/                 # Main OTA system
│       ├── debian/changelog         # OTA package version uploaded to PPA
│       ├── usr/bin/
│       │   ├── caramos-ota          # CLI/orchestrator
│       │   ├── caramos-ota-notifier # Update Center/notifier
│       │   └── caramos-ota-update   # Migration runner
│       └── usr/lib/python3/dist-packages/
│           ├── caramos_ota/
│           ├── caramos_ota_notifier/
│           └── caramos_ota_update/migrations/
│               ├── migration.json       # frozen historical bridge
│               ├── v1_0_*/              # legacy migrations through 1.0.12
│               └── YYYYMMDDHHMMSS_name/
│                   ├── manifest.json
│                   └── migration.py
├── landing/                         # Website/landing page
├── docs/                            # Operations/release tracking docs
├── assets/                          # Logo, banner, screenshots
└── .github/workflows/               # CI/release workflow
```

Detailed OTA docs:

- [packages/README.md](packages/README.md)
- [packages/caramos-ota/README.md](packages/caramos-ota/README.md)

---

## Build ISO

### Local build

Requirements: a compatible Ubuntu/Mint/Debian machine, `sudo`, and enough free
space for rootfs and ISO artifacts.

```bash
sudo apt update
sudo apt install squashfs-tools xorriso rsync wget curl isolinux syslinux-common syslinux-utils
```

Fast dev build:

```bash
make build
```

Smaller release build:

```bash
make release
```

Build from an existing Mint ISO:

```bash
make build ISO=linuxmint-22.3-cinnamon-64bit.iso
```

During the build, `customize.sh` calls OTA bootstrap. Therefore, if you change
`packages/caramos-ota`, rebuilding the ISO will embed the new OTA package and run
migrations into the rootfs before packaging.

### Docker build

Use Docker when the host is not a compatible Ubuntu/Mint/Debian system:

```bash
make docker-build
make docker-release
```

### Fast iteration workflow

| Change type | Recommended command |
|---|---|
| Base ISO overlay/assets | `make overlay && make quick` |
| Boot menu/Plymouth | `make boot-only && make iso-only` |
| OTA migration/package | test in `packages/caramos-ota`, then `make customize-only` or `make build` |
| Release version | update `scripts/config.sh`, docs/landing according to `docs/release-version-tracking.md` |

---

## Developing with OTA

### When do you need a migration?

Create an OTA migration when a change affects already-installed CaramOS systems,
for example:

- Cinnamon panel/dconf/default app launcher changes;
- Fcitx5/Lotus, input method, or autostart fixes;
- branding, theme, icon, or wallpaper updates that should apply to existing users;
- adding/updating CaramOS-managed packages;
- changes to `/etc/caramos-release`, `/etc/lsb-release`, or `/etc/os-release`;
- one-time commands that must run on user machines after release.

Do not use hooks as a replacement for migrations in these cases.

### Files to add for an OTA migration

```text
packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/
└── YYYYMMDDHHMMSS_migration_name/
    ├── manifest.json
    ├── migration.py
    └── optional payload
```

Generate the timestamp with `date -u +%Y%m%d%H%M%S`. Schema-2 `manifest.json`
declares `release`, UI metadata, `codename`, and `channel`. `migration.py` declares
`DESCRIPTION` and `run(context)`. Do not edit `migration.json`; it is the frozen
historical bridge through `1.0.12`; timestamp migrations start with release `1.0.13`. See
[packages/caramos-ota/MIGRATIONS.md](packages/caramos-ota/MIGRATIONS.md).

### Migration rules

- Published timestamp IDs are immutable; make a new migration for follow-up fixes.
- Multiple migrations may share one `release`; the runner orders them by ID.
- Migrations must be idempotent or include explicit rerun guards.
- Do not download or execute scripts from the internet inside migrations.
- Do not download `.deb` files manually; use the configured APT/PPA path.
- Do not hardcode users such as `caram` or `mint`; detect the real desktop user.
- Do not add PPAs/keyrings in a migration unless they have been reviewed in the
  package/ISO layer.
- Log each important action with `context.log(...)`.
- `dry-run` must not mutate the system.
- User-session commands such as `systemctl --user`, `gsettings`, or `fcitx5`
  must use short timeouts and fallbacks.
- If a service/desktop component restart is needed, prefer best-effort refresh
  and tell users to logout/login when required.

### OTA tests before PR

Inside the OTA package:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

If VM testing is available:

```bash
make ship
make vm-test-cli
make vm-test-notifier
```

PR checklist:

- [ ] New migration has a unique UTC timestamp ID and clear release.
- [ ] `migration.json` is unchanged; schema-2 `manifest.json` is valid.
- [ ] `make compile`, `make validate`, `./tools/caramos-ota-testkit.sh test`, and `make build` pass.
- [ ] Upgrade from an older version was tested in a VM snapshot if possible.
- [ ] Update Center does not hang when a migration fails or a command times out.
- [ ] Logs in `/var/log/caramos-ota/` are sufficient for debugging.
- [ ] README/landing/release notes are updated if this is a new release.

---

## Contribution Workflow

1. Fork the repository.
2. Create a branch from `develop` or the branch specified by maintainers.
3. Make focused, well-scoped changes.
4. Test according to the change type.
5. Commit with a clear prefixed message.
6. Open a Pull Request and describe:
   - what changed;
   - why it is needed;
   - how it was tested;
   - whether it requires an OTA migration.

### Contribution roles

| Role | Work |
|---|---|
| Tester | Test ISO/OTA on real hardware or VMs, report issues with logs/screenshots |
| Developer | Write migrations, OTA package changes, build scripts, bug fixes |
| Designer | Wallpapers, icons, banners, branding assets |
| Writer | README, user guides, changelog, translations |

### Branches and releases

```text
main       # stable/release branch
feat/*     # new features
fix/*      # bug fixes
docs/*     # documentation
release/*  # release preparation
```

When bumping a release version, follow the checklist in
[docs/release-version-tracking.md](docs/release-version-tracking.md).

---

## Code Standards

### Commit messages

The project prefers short, easy-to-scan prefixes:

```text
[build] build scripts / Docker / CI
[config] package list, overlay, system config
[assets] logo, wallpaper, screenshot
[docs] README, guide, changelog
[ota] caramos-ota, migration, notifier, updater
[release] version bump/tag/release metadata
```

### Bash

- Use `set -e` or explicit error handling.
- Log what each block is doing.
- Do not download/run uncontrolled scripts.
- Scripts in `scripts/` should provide `--help` when runnable independently.

### Python migrations

- Prefer the standard library; avoid adding dependencies unless necessary.
- Do not hardcode usernames or home paths.
- Check that files exist before editing/removing them.
- Backup or log risky changes clearly.
- Respect `dry-run` when the context supports it.

---

## Bug Reports and Feature Requests

Create an issue at: <https://github.com/VN-Linux-Family/CaramOS/issues>

Bug reports should include:

- current CaramOS version;
- whether you are using ISO or OTA;
- steps to reproduce;
- expected result;
- relevant logs, especially `/var/log/caramos-ota/` for update issues;
- screenshots/videos for UI issues.

Feature requests should include:

- a short description;
- why the feature is needed;
- whether it affects installed users or only new ISOs;
- if it affects installed users, a proposed OTA migration approach.

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  <a href="https://github.com/VN-Linux-Family/CaramOS">github.com/VN-Linux-Family/CaramOS</a>
</p>
