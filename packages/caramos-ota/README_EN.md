# CaramOS OTA

> **Package:** `caramos-ota`  
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`  
> **Target:** CaramOS 1.x  
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`

CaramOS OTA uses APT/PPA as transport and database-style migrations for system changes.

## Architecture

```text
caramos-ota --check
  ├── update the OTA engine first
  ├── auto-discover migration folders
  ├── read the applied-ID ledger
  └── write /var/lib/caramos-ota/state.json

caramos-ota-notifier
  └── read state → ask user → pkexec caramos-ota --upgrade --yes

caramos-ota-update
  ├── resolve legacy bridge + pending timestamp migrations
  ├── run migrations in deterministic order
  ├── record each ID after successful execution
  └── update release metadata
```

- UI state: `/var/lib/caramos-ota/state.json`
- Applied migration ledger: `/var/lib/caramos-ota/migrations.json`
- Logs: `/var/log/caramos-ota/YYYY-MM-DD.log`
- Systemd timer checks only; it never applies migrations automatically.

## New migrations

Contributors only add one directory:

```text
caramos_ota_update/migrations/
└── 20260714143022_migration_name/
    ├── manifest.json
    ├── migration.py
    └── optional payload
```

Schema-2 `manifest.json` declares `release`, `codename`, `channel`, and UI metadata. `migration.py` declares `DESCRIPTION` and `run(context)`. Do not edit `migration.json` or declare `FROM_VERSION`/`TO_VERSION` for new migrations.

Multiple migrations may share one release. Runner orders them lexically by timestamp ID. Full guide: [MIGRATIONS.md](MIGRATIONS.md).

## Legacy bridge

`migration.json` and `v1_0_2` through `v1_0_12` remain as historical compatibility bridge. Runtime auto-discovers both legacy and timestamp migrations. Historical index is frozen at `1.0.12`; timestamp migrations start with release `1.0.13`.

Initial ledger bootstrap marks legacy migrations at or below installed version as applied. Timestamp migrations are never inferred from product version.

## Commands

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair

sudo caramos-ota-update --dry-run
sudo caramos-ota-update --target 1.0.14 --dry-run
sudo caramos-ota-update --target 1.0.14
```

Dry-run does not write state, ledger, logs, or system files.

## Failure and resume

- Invalid registry, metadata, or entrypoint fails closed.
- Ledger records an ID only after successful execution.
- Failed batches retain completed/current migration IDs and log path.
- Rerun skips applied IDs and resumes pending work.
- Filesystem migrations have no generic automatic rollback; ship a new migration or use migration-specific recovery.

## Build and test

```bash
cd packages/caramos-ota
./tools/caramos-ota-testkit.sh compile
./tools/caramos-ota-testkit.sh validate
./tools/caramos-ota-testkit.sh test
./tools/caramos-ota-testkit.sh build-deb
```

## Safety

- Never execute commands from manifest JSON.
- Avoid `shell=True`.
- Install packages through APT/PPA; do not download `.deb` files manually.
- Migrations must be idempotent and dry-run aware.
- Published IDs are immutable; use a new migration for follow-up fixes.
- Timer never auto-installs updates.