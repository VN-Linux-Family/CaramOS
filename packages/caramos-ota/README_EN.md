# CaramOS OTA

> **Package:** `caramos-ota`
>
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`
>
> **Target OS:** CaramOS 1.x
>
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`
>
> **Model:** schema 2 timestamp migrations + ledger

`caramos-ota` is the official OTA update system for CaramOS. It does not replace APT. It uses APT/PPA as the package transport layer, while CaramOS-specific system changes are coordinated through reviewed migrations.

> **Important:** The current model has no latest-release manifest. New migrations use timestamp IDs. Schema 2 manifests must not contain `release`, `version`, `from_version`, or `to_version`. The runner executes every unapplied timestamp migration in lexical order using the ledger.

---

## 1. Quick summary for contributors

1. `caramos-ota` is the orchestrator: checks OS/repository/state, writes state, and calls the updater.
2. `caramos-ota-notifier` is the desktop UI: reads state and calls `pkexec caramos-ota --upgrade --yes` after user confirmation.
3. `caramos-ota-update` is the migration runner: executes unapplied timestamp migrations in lexical order.
4. The ledger decides which migrations already ran; product version does not select new migrations.
5. Schema 2 manifests only hold UI/log metadata and contain no release/version/from/to fields.
6. Do not select new migrations by product version.
7. Legacy `v1_0_2..v1_0_12` migrations are compatibility-only and frozen.
8. Migrations use APT/PPA for package installation. Do not download `.deb` files manually.
9. The systemd timer only checks/prepares state. It must not apply migrations automatically.
10. Local `make compile`, `make validate`, and `make build` do not require `VERSION`. Only `make release VERSION=x.y.z` receives the product version.

---

## 2. Architecture

```text
caramos_ota_update/migrations/
  ├── v1_0_2 ... v1_0_12        # legacy compatibility, frozen
  └── YYYYMMDDHHMMSS_slug/      # schema 2 timestamp migration
      ├── manifest.json         # metadata, no release/version/from/to
      └── migration.py          # reviewed system changes

caramos-ota --check
  ├── verify CaramOS identity
  ├── verify PPA/keyring
  ├── inspect packaged migration metadata
  ├── compare timestamp IDs with ledger
  └── write /var/lib/caramos-ota/state.json

caramos-ota-notifier
  ├── read state.json
  ├── show GTK dialog when unapplied migrations exist
  └── pkexec caramos-ota --upgrade --yes

caramos-ota --upgrade
  └── caramos-ota-update
      ├── load ledger
      ├── sort unapplied timestamp IDs lexically
      ├── run each migration
      ├── record each successful ID in ledger
      └── update state/log
```

---

## 3. Commands

| Command | Responsibility |
|---|---|
| `caramos-ota` | CLI/orchestrator. Checks update state and calls the updater during upgrade. |
| `caramos-ota-notifier` | Desktop notifier. It does not parse migration logic or run APT directly. |
| `caramos-ota-update` | Root-only runner. Executes unapplied migrations using the ledger. |

Common commands:

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair
sudo caramos-ota-update --dry-run
sudo caramos-ota-update
```

---

## 4. Migration metadata

### 4.1 Layout

```text
usr/lib/python3/dist-packages/caramos_ota_update/migrations/
├── v1_0_2/ ... v1_0_12/      # legacy compatibility, frozen
└── 20260806120000_example/
    ├── manifest.json         # schema 2 metadata
    └── migration.py          # apply logic
```

### 4.2 Schema 2 manifest

```json
{
  "schema": 2,
  "title": "CaramOS update available",
  "summary": "This update applies reviewed system changes.",
  "severity": "normal",
  "release_notes_vi": [
    "Cập nhật cấu hình desktop."
  ],
  "release_notes_en": [
    "Update desktop configuration."
  ]
}
```

Rules:

- Schema 2 manifests do not contain `release`, `version`, `from_version`, or `to_version`.
- Metadata is packaged locally; runtime must not fetch control JSON from the network.
- The manifest must not contain commands, inline shell scripts, package install plans, or direct `.deb` URLs.
- Real logic lives in reviewed Python/shell migration code.
- Do not execute shell/commands from JSON metadata.
- Breaking schema changes require a bridge updater rollout.

### 4.3 Legacy migrations

`v1_0_2..v1_0_12` is the compatibility layer for the old model.

- Do not use `vX_Y_Z` as the template for new migrations.
- Do not add `v1_0_13` or any new legacy-version migration.
- Do not edit legacy migrations unless a required migration-fix exists.
- New migrations must use timestamp IDs and schema 2 manifests.

---

## 5. Migration runner and ledger

The runner must:

- discover timestamp migration directories;
- sort by lexical ID;
- skip IDs already present in the ledger;
- keep dry-run read-only and never write the ledger during dry-run;
- write state/log before and after each migration;
- record an ID in the ledger only after successful completion;
- stop immediately on failure;
- resume from the first unapplied timestamp on the next run.

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
  "last_check": "2026-08-06T16:00:00+07:00",
  "available_update": {
    "detected_at": "2026-08-06T16:00:00+07:00",
    "pending_migrations": [
      "20260806120000_example"
    ]
  },
  "transaction": {
    "status": "failed",
    "current_migration": "20260806120000_example",
    "log": "/var/log/caramos-ota/2026-08-06.log"
  }
}
```

---

## 6. Local build and test

Local build/validate does not need product version:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

Inspect package:

```bash
cd packages/caramos-ota
make inspect
```

Required package contents:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/bin/caramos-ota-update
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/lib/python3/dist-packages/caramos_ota_update/
/usr/lib/python3/dist-packages/caramos_ota_update/migrations/
```

Quick VM test:

```bash
cd packages/caramos-ota
make ship
make test
make test-notifier
```

Expected behavior:

- Non-CaramOS systems fail closed.
- `--check` does not install packages.
- `--dry-run` does not mutate the system and does not write the ledger.
- The updater prints timestamp migrations it will run.
- Migration failures fail closed and never guess a target.

---

## 7. OTA release workflow

1. Create a new timestamp migration directory, for example `YYYYMMDDHHMMSS_slug/`.
2. Add a schema 2 `manifest.json` with no `release`, `version`, `from_version`, or `to_version`.
3. Add reviewed migration logic.
4. Run local compile/validate/build without `VERSION`.
5. Test the ledger flow in a VM.
6. The maintainer chooses product version at release time.
7. Build and upload the release package with:

```bash
cd packages/caramos-ota
make release VERSION=x.y.z
```

8. After PPA publication, test install/upgrade from an old VM or machine.

Product version only appears in the release command and published artifacts. Do not hardcode product version into schema 2 migrations or local validation.

---

## 8. Repair and rollback

### Repair

```bash
sudo caramos-ota --repair
```

Best-effort repair commands:

```bash
dpkg --configure -a
apt-get --fix-broken install --yes
```

### Rollback

Rollback should not promise too much in v1. Migrations can edit config, install/remove packages, or change state. Prefer:

- clear transaction logs;
- APT/dpkg repair;
- resume from the last successful migration according to the ledger;
- manual support when a migration fails.

If true rollback is required, each migration needs its own tested `rollback(context)`.

---

## 9. Security / safety rules

- Do not execute shell from JSON metadata.
- Avoid `shell=True` unless required.
- Do not download `.deb` files manually from the Internet.
- Do not auto-add PPAs.
- Do not auto-install from the systemd timer.
- Log every migration step.
- Keep migrations rerunnable as much as possible.
- Package installation must go through APT/PPA.
- Write ledger entries only after successful migration completion.

---

## 10. Contributor checklist

- [ ] `/usr/bin/*` entrypoints are thin wrappers.
- [ ] New migration uses a lexical timestamp ID.
- [ ] Schema 2 manifest has no `release`, `version`, `from_version`, or `to_version`.
- [ ] Do not add product-version-based migration selection.
- [ ] Legacy `v1_0_2..v1_0_12` remains untouched unless a required migration-fix exists.
- [ ] Migration supports dry-run or uses a dry-run-aware context.
- [ ] Migration is idempotent or has explicit guards.
- [ ] `make compile` passes.
- [ ] `make validate` passes.
- [ ] `make build` passes.
- [ ] The `.deb` contains CLI, notifier, updater, and migrations.
- [ ] Local VM install passes.
- [ ] `caramos-ota --check` does not install packages.
- [ ] `caramos-ota-update --dry-run` does not mutate the system.
- [ ] Migration failure fails closed and never guesses a target.
- [ ] Real release uses `make release VERSION=x.y.z`.

---

## 11. Summary

```text
caramos-ota
  = check + state + updater call

caramos-ota-notifier
  = desktop UI

caramos-ota-update
  = timestamp migration runner

schema 2 manifest
  = UI/log metadata, no release/version/from/to

ledger
  = source of truth for applied migrations

PPA/APT
  = package transport
```

To ship a new OTA, add a schema 2 timestamp migration, test local/VM without passing a version, then let the maintainer run `make release VERSION=x.y.z` for the product release.
