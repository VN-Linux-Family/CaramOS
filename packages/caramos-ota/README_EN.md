# CaramOS OTA Package

> **Package:** `caramos-ota`  
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`  
> **Target OS:** CaramOS 1.x  
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`  
> **OTA model:** version migration-driven updates

`caramos-ota` is the official OTA update package for CaramOS. It does not replace APT. It uses APT/PPA as the package transport layer, while CaramOS-specific release upgrades are coordinated through ordered version migrations.

> **Important:** The current design is no longer a package-list manifest model. The migration index should not list every package with `min_version`. It only announces the newest CaramOS release metadata, especially `release`. The real system changes live in reviewed migration code shipped by the `caramos-ota` package.

---

## 1. Quick summary for contributors

1. `caramos-ota` is the orchestrator: checks OS/repository state, fetches the manifest, writes state, and calls the updater.
2. `caramos-ota-notifier` is the desktop UI: reads state and calls `pkexec caramos-ota --upgrade --yes` after user confirmation.
3. `caramos-ota-update` is the migration runner: executes ordered migrations such as `1.0.3 -> 1.0.2`.
4. The migration index only contains release metadata: schema, channel, codename, `release`, minimum client version, and release notes.
5. Migration logic belongs in `caramos_ota_update/migrations/`.
6. Migrations should use APT/PPA for package installation. Do not download `.deb` files manually.
7. The systemd timer only checks and writes state. It must not install updates automatically.
8. If a migration fails, state and logs must be sufficient to debug or resume from the last successful version.

---

## 2. Architecture

```text
Migration index
  └── versions = [1.0.2]

caramos-ota --check
  ├── verify CaramOS identity
  ├── verify PPA/keyring
  ├── đọc migration index đóng gói
  ├── fall back to migration-local manifest if needed
  ├── compare current_version with release
  └── write /var/lib/caramos-ota/state.json

caramos-ota-notifier
  ├── read state.json
  ├── show GTK dialog when an update exists
  └── pkexec caramos-ota --upgrade --yes

caramos-ota --upgrade
  └── caramos-ota-update --target <release>
      ├── run migration 1.0.2 -> 1.0.3
      ├── persist state
      ├── run migration 1.0.3 -> 1.0.2
      └── update /etc/caramos-release
```

---

## 3. Commands

| Command | Responsibility |
|---|---|
| `caramos-ota` | Main CLI/orchestrator. Checks for updates, writes state, and calls the updater. |
| `caramos-ota-notifier` | Desktop notifier. It does not parse manifests or run APT directly. |
| `caramos-ota-update` | Root-only migration runner. Executes version-to-version migrations. |

Expected CLI surface:

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair

sudo caramos-ota-update --target 1.0.2 --dry-run
sudo caramos-ota-update --target 1.0.2
sudo caramos-ota-update --from 1.0.3 --to 1.0.2 --dry-run
```

---

## 4. Manifest

Runtime URL:

```text
caramos_ota_update/migrations/migration.json
```

Example:

```text
caramos_ota_update/migrations/migration.json
```

Migration metadata files:

```text
caramos_ota_update/migrations/migration.json
```

Source-tree path:

```text
packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json
```

Manifest v1 example:

```json
{
  "schema": 1,
  "channel": "stable",
  "codename": "noble",
  "current_series": "1.x",
  "release": "1.0.2",
  "min_client_version": "1.0.2-0caramos1",
  "release_notes_vi": [
    "Cập nhật WPS Office.",
    "Sửa cấu hình input method.",
    "Cập nhật branding CaramOS."
  ],
  "release_notes_en": [
    "Update WPS Office.",
    "Fix input method configuration.",
    "Update CaramOS branding."
  ]
}
```

Manifest rules:

- Do not include shell scripts.
- Do not include commands to execute.
- Do not include direct `.deb` download URLs.
- Do not describe per-package install actions.
- `release` must have a corresponding migration path in `caramos-ota-update`.
- If the migration index cannot be fetched, the CLI must fall back to the migration-local manifest.
- Breaking schema changes require a bridge updater rollout.

---

## 5. Migration runner

Recommended source layout:

```text
usr/lib/python3/dist-packages/
├── caramos_ota/
├── caramos_ota_notifier/
└── caramos_ota_update/
    ├── __init__.py
    ├── cli.py
    ├── runner.py
    ├── context.py
    ├── apt.py
    ├── state.py
    └── migrations/
        ├── __init__.py
        ├── v1_0_2_to_v1_0_3.py
        └── v1_0_3_to_v1_0_4.py
```

Example migration:

```python
FROM_VERSION = "1.0.3"
TO_VERSION = "1.0.2"
DESCRIPTION = "Install WPS Office and refresh Vietnamese desktop defaults"


def run(context):
    context.apt_update()
    context.apt_install([
        "wps-office",
        "fcitx5",
    ])
    context.ensure_service_enabled("fcitx5")
    context.update_release_file("1.0.2")
```

Migration rules:

- Each migration upgrades exactly one adjacent version step.
- Migrations should be idempotent whenever possible.
- Avoid blind config appends that duplicate lines on rerun.
- Use APT/PPA for package installation.
- Log each important step.
- Stop immediately on failure.
- Do not hide multiple releases inside one huge migration.

---

## 6. State and logs

State file:

```text
/var/lib/caramos-ota/state.json
```

Log files:

```text
/var/log/caramos-ota/YYYY-MM-DD.log
```

Suggested state shape:

```json
{
  "last_check": "2026-06-06T16:00:00+07:00",
  "installed_version": "1.0.3",
  "available_update": {
    "detected_at": "2026-06-06T16:00:00+07:00",
    "current_version": "1.0.3",
    "release": "1.0.2",
    "manifest_source": "caramos_ota_update/migrations/migration.json",
    "release_notes_vi": [],
    "release_notes_en": []
  },
  "transaction": {
    "status": "failed",
    "target_version": "1.0.2",
    "current_migration": "1.0.3_to_1.0.2",
    "failed_at": "install_wps_office",
    "log": "/var/log/caramos-ota/2026-06-06.log"
  }
}
```

---

## 7. Build and test

Compile Python:

```bash
cd packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/migrations/*.py
```

If the updater package does not exist yet in the current source tree, compile the existing paths first. Once the refactor is implemented, `caramos-ota-update` and `caramos_ota_update` must be included.

Validate manifest:

```bash
cd packages/caramos-ota
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
```

Build package:

```bash
cd packages/caramos-ota
dpkg-buildpackage -us -uc -b
```

Inspect package:

```bash
cd packages
dpkg-deb -c caramos-ota_1.0.2-0caramos1_all.deb
```

VM smoke test:

```bash
sudo apt install ./caramos-ota_1.0.2-0caramos1_all.deb
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota-update --target 1.0.2 --dry-run
```

Expected behavior:

- Non-CaramOS systems fail closed.
- `--check` does not install packages.
- `--dry-run` does not mutate the system.
- The updater prints the migration path.
- Migration index failure falls back to migration-local manifest.

---

## 8. Release workflow

Example release `1.0.2`:

```text
1. Add migration v1_0_3_to_v1_0_4.py.
2. Test migration dry-run.
3. Bump debian/changelog to 1.0.2-0caramos1.
4. Build the .deb.
5. Install locally in a VM at version 1.0.3.
6. Run caramos-ota-update --target 1.0.2 --dry-run.
7. Run caramos-ota --upgrade.
8. Verify /etc/caramos-release is now 1.0.2.
9. Upload to PPA.
10. After PPA publish, update the migration index release to 1.0.2.
11. Retest from an older VM through the migration index.
```

---

## 9. Safety rules

- Do not execute shell from manifest data.
- Avoid `shell=True`.
- Do not download `.deb` files manually from the Internet.
- Do not auto-add PPAs.
- Do not auto-install from the systemd timer.
- Validate channel/codename before accepting migration metadata.
- Bound manifest fetch timeout and size.
- Log every migration step.
- Keep migrations rerunnable as much as possible.

---

## 10. Contributor checklist

- [ ] Entrypoints under `/usr/bin` are thin wrappers.
- [ ] New migration has `FROM_VERSION`, `TO_VERSION`, and `DESCRIPTION`.
- [ ] Migration supports dry-run or uses a dry-run-aware context.
- [ ] Migration is idempotent or has explicit guards.
- [ ] Manifest `release` has a matching migration path.
- [ ] `python3 -m py_compile` passes.
- [ ] `python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json` passes.
- [ ] `dpkg-buildpackage -us -uc -b` passes.
- [ ] The `.deb` contains CLI, notifier, and updater files.
- [ ] Local VM install passes.
- [ ] `caramos-ota --check` does not install packages.
- [ ] `caramos-ota-update --dry-run` does not mutate the system.
- [ ] Migration index failure falls back to migration-local manifest.
- [ ] Breaking schema changes have a bridge rollout plan.

---

## 11. Release workflow for OTA 1.0.2 → 1.0.5

Release owner: **dungleviet**. Contributors prepare migrations, tests and PRs; the final PPA upload/release is performed by the maintainer.

### Goal

A user already running CaramOS `1.0.1` should only need:

```bash
sudo apt update
sudo apt install caramos-ota
sudo caramos-ota
```

For the desktop popup flow:

```bash
sudo apt update
sudo apt install caramos-ota
caramos-ota-notifier
```

The updater resolves and runs the full migration chain:

```text
1.0.1 → 1.0.2 → 1.0.3 → 1.0.4 → 1.0.5
```

### Package version

Publish `caramos-ota` as `1.0.5-0caramos1` or newer. The packaged migration index points to latest target `1.0.5`. Technical codename must be `wilma`; Ubuntu codename remains `noble`.

### Build and local VM test

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

Inside the VM:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
cat /etc/caramos-release
grep -E '^(VERSION|VERSION_ID|VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release
sudo add-apt-repository -y ppa:mozillateam/ppa
sudo rm -f /etc/apt/sources.list.d/*mozillateam*
sudo apt update
```

Expected result: CaramOS is `1.0.5`, `VERSION_CODENAME=wilma`, `UBUNTU_CODENAME=noble`, and `add-apt-repository` no longer fails with codename `caram`.

### PPA upload

Maintainer `dungleviet` bumps `debian/changelog`, builds a source upload and publishes it:

```bash
cd /home/dungleviet/Documents/CaramOS/packages/caramos-ota
debuild -S -sa
dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.5-0caramos1_source.changes
```

After Launchpad publishes the package, verify from a `1.0.1` VM:

```bash
sudo apt update
apt-cache policy caramos-ota
sudo apt install caramos-ota
sudo caramos-ota
```

### ISO build

The ISO release version is `CARAMOS_VERSION=1.0.5`, while the bootstrap starting point is `CARAMOS_MIGRATION_BASE_VERSION=1.0.1`. During ISO build, OTA bootstrap runs the full migration chain and the finished rootfs metadata becomes `1.0.5`.
