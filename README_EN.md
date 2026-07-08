<p align="center">
  <img src="assets/CaramOS_logo.png" alt="CaramOS Logo" width="250">
</p>

<h1 align="center">CaramOS</h1>

<p align="center">
  <strong>Sweet & Simple Linux — A Linux distro made for Vietnamese users</strong>
</p>

<p align="center">
  <em>Caram = Carambola — the starfruit, whose 5 points mirror the star on Vietnam's flag, a fruit tied to every Vietnamese childhood</em>
</p>

<p align="center">
  <a href="README.md">Tiếng Việt</a> · <a href="https://vietnamlinuxfamily.net">VNLF</a> · <a href="https://caramos.vietnamlinuxfamily.net">Website</a>
</p>

---

### What is CaramOS?

**CaramOS** is a Linux distribution based on **Linux Mint 22.3 Cinnamon**
(Ubuntu 24.04 LTS), designed specifically for **Vietnamese users**. The project
is still built as an **ISO remaster**, but starting with `1.0.11`, all
post-release system changes are standardized through **CaramOS OTA**.

> [!IMPORTANT]
> **Current version:** `1.0.12` — **Open Beta**.
> CaramOS has moved to an OTA update model. If you are currently running
> CaramOS `1.0.1`, install the Update Center with:
>
> ```bash
> curl -fsSL https://caramos.vietnamlinuxfamily.net/install-caramos-ota.sh | sudo bash
> ```
>
> After installation, open **CaramOS Update Center** from the Start Menu to
> upgrade your system to the latest version.

> [!NOTE]
> For developers/contributors: from now on, do not implement system changes
> directly in `config/hooks/live/` if those changes must reach already-installed
> user machines. Write migrations in `packages/caramos-ota` instead. See the OTA
> development guide: [packages/caramos-ota/README.md](packages/caramos-ota/README.md).

Our mission is to make Linux easier for Vietnamese users moving from Windows:
familiar desktop defaults, Vietnamese input ready out of the box, a browser,
office tools, and practical daily-use utilities.

### Key Features

| Feature | Description |
|---|---|
| **Linux Mint 22.3 base** | Stable Ubuntu 24.04 LTS foundation with the familiar Cinnamon desktop |
| **CaramOS branding** | Customized boot menu, Plymouth, logo, wallpaper, panel and theme |
| **Vietnamese-first defaults** | Vietnamese locale, Asia/Ho_Chi_Minh timezone and Be Vietnam Pro fonts |
| **Vietnamese input** | Fcitx5 + Lotus installed and configured by default |
| **Google Chrome** | Popular browser included out of the box |
| **WPS Office** | Office suite friendly to users migrating from Windows |
| **Zalo** | Zalo AppImage included with a desktop shortcut |
| **Cinnamon Delight + Tela/Bibata** | Modern theme, icons and cursor with a clean desktop experience |
| **Neofetch/Fastfetch identity** | CaramOS ASCII logo and synchronized OS identity/version metadata |
| **OTA updates** | `caramos-ota` delivers post-ISO updates through reviewed version migrations |
| **Flexible builds** | Fast dev builds with `lz4`, smaller release builds with `xz`, Docker supported |

<p align="center">
  <img src="assets/caramos_vietnam_banner.png" alt="CaramOS Open Beta banner" width="900">
</p>

### CaramOS Experience

From boot menu to desktop, CaramOS is consistently branded to feel friendly,
modern, and ready for Vietnamese users out of the box.

| Step | Screenshot |
|---|---|
| **1. GRUB boot menu**<br>Select the live session or start the installer. | <img src="assets/screenshots/01-grub-menu.png" alt="CaramOS GRUB boot menu" width="420"> |
| **2. Startup loading**<br>Customized Plymouth startup branding. | <img src="assets/screenshots/02-startup-loading.png" alt="CaramOS startup loading screen" width="420"> |
| **3. Desktop**<br>Cinnamon desktop with CaramOS theme, icons, panel, and wallpaper. | <img src="assets/screenshots/03-desktop.png" alt="CaramOS Cinnamon desktop" width="420"> |
| **4. Neofetch**<br>CaramOS system identity shown directly in the terminal. | <img src="assets/screenshots/04-neofetch.png" alt="CaramOS neofetch output" width="420"> |

### Installation

1. Download ISO from [caramos.vietnamlinuxfamily.net](https://caramos.vietnamlinuxfamily.net)
2. Flash to USB with [Balena Etcher](https://etcher.balena.io) or `dd`
3. Boot from USB, follow the installer

### OTA Updates

CaramOS has moved to an **OTA-first** model. New ISO images are still released,
but machines installed from older ISOs do not need to reinstall: users install
`caramos-ota`, then Update Center/OTA upgrades the system to the latest version
through a reviewed migration chain.

Users currently on CaramOS `1.0.1` should run:

```bash
curl -fsSL https://caramos.vietnamlinuxfamily.net/install-caramos-ota.sh | sudo bash
```

```text
systemd timer
  └── caramos-ota --check
      ├── updates the caramos-ota package when the repository has a newer build
      ├── resolves the migration chain
      └── writes /var/lib/caramos-ota/state.json

Update Center
  └── user confirms the update
      └── pkexec caramos-ota --upgrade --yes
          └── caramos-ota-update runs each migration
```

Important rules:

- The timer checks/prepares state; it does not open the GUI or apply migrations.
- Migrations run only after user confirmation or an explicit admin CLI command.
- System-changing logic lives in `packages/caramos-ota`, not in build hooks.
- Developers adding post-release changes must write versioned OTA migrations.
- ISO builds use the same OTA migration chain to bring the rootfs to latest.

See [packages/caramos-ota/README.md](packages/caramos-ota/README.md) for the OTA
architecture and developer workflow.

### Tech Stack

| Component | Technology / current role |
|---|---|
| **Base ISO** | Linux Mint 22.3 Cinnamon 64-bit |
| **Ubuntu base** | Ubuntu 24.04 LTS / noble |
| **Desktop** | Cinnamon + LightDM from the Linux Mint base |
| **Build method** | ISO remaster: extract → customize → OTA bootstrap → repack |
| **Build scripts** | Bash + Makefile, split into modules under `scripts/` |
| **OTA model** | `caramos-ota` version migration-driven OTA |
| **Migration runner** | `caramos-ota-update` runs `FROM_VERSION -> TO_VERSION` migrations in order |
| **Update Center** | `caramos-ota-notifier` + `pkexec caramos-ota --upgrade --yes` |
| **Developer workflow** | Post-release system changes go into `packages/caramos-ota` migrations |
| **Legacy hooks** | `config/hooks/live/` is for bootstrap/build-time foundations, not new OTA features |
| **Overlay** | `config/includes.chroot/` stores base files copied into the ISO/rootfs |
| **Dev compression** | SquashFS `lz4` |
| **Release compression** | SquashFS `xz` |
| **Theme / Icons / Cursor** | Cinnamon Delight, Tela Circle/Cinnamon Delight Icons, Bibata |
| **Font / Input Method** | Be Vietnam Pro, Fcitx5 + Lotus |
| **Popular apps** | Google Chrome, WPS Office, Zalo AppImage |

### Build ISO

When building an ISO, CaramOS does not only copy overlays/hooks and repack the
image. The build flow automatically builds the `caramos-ota` package, installs
it into the rootfs, and runs the full OTA migration chain from
`CARAMOS_MIGRATION_BASE_VERSION` to the latest version before repacking.

In short: **the ISO is built as the latest state**, while OTA is the upgrade path
for users already installed from older ISOs.

Install build dependencies on Ubuntu/Mint/Debian:

```bash
sudo apt update
sudo apt install squashfs-tools xorriso rsync wget curl isolinux syslinux-common syslinux-utils
```

Run a dev build:

```bash
make build
```

Run a release build:

```bash
make release
```

Build from an existing Mint ISO:

```bash
make build ISO=linuxmint-22.3-cinnamon-64bit.iso
```

During `customize`, the build runs:

```text
extract base ISO
  → install packages + overlay + build-time hooks
  → build/install bundled caramos-ota
  → caramos-ota-update --from "$CARAMOS_MIGRATION_BASE_VERSION" --target latest
  → repack squashfs + ISO
```

Common `make` targets:

| Command | Purpose |
|---|---|
| `make build` | Full dev build with fast `lz4` compression |
| `make release` | Release build with smaller but slower `xz` compression |
| `make prepare` | Extract the ISO/rootfs into `build/` for fast iteration |
| `make customize-only` | Run package installation, overlay copy, and chroot hooks |
| `make boot-only` | Apply only boot menu, GRUB, and Plymouth branding |
| `make overlay` | Copy only `config/includes.chroot` into the rootfs |
| `make quick` | Prepare if needed, overlay, then repack squashfs and ISO |
| `make repack` | Repack squashfs and ISO from the existing work tree |
| `make iso-only` | Recreate only the ISO from `build/custom` |
| `make shell` | Enter the `build/squashfs` chroot for manual debugging |
| `make debug-iso` | Print boot menu/Plymouth diagnostics |
| `make clean` | Remove build/cache/output ISO artifacts |
| `make docker-build` | Run a dev build inside Docker |
| `make docker-release` | Run a release build inside Docker |

Fast iteration after the first build/prepare:

- If you changed bootstrap ISO files such as wallpaper, assets or base overlay:
  run `make overlay` then `make quick`.
- If you changed OTA packages/migrations: build/test under
  [packages/caramos-ota](packages/caramos-ota/) first, then run
  `make customize-only` or rebuild the ISO so OTA bootstrap applies the
  migrations into the rootfs.
- Do not add new user-facing updates to hooks just to reach already-installed
  machines; write an OTA migration.

```bash
make customize-only
make quick
```

### Contributing

We welcome contributions! See [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md) for the
OTA-first contribution workflow.

**You can help with:**
- Bug reports and feature suggestions via [Issues](https://github.com/VN-Linux-Family/CaramOS/issues)
- Wallpaper, icon, theme, and branding design
- Testing ISO and OTA updates on different hardware or VM snapshots
- Documentation and translations
- Writing safe OTA migrations, package changes, build scripts, and base overlays

### Contributors

Thanks to everyone who has contributed to CaramOS on GitHub.

<p align="center">
  <a href="https://github.com/VN-Linux-Family/CaramOS/graphs/contributors">
    <img src="https://contrib.rocks/image?repo=VN-Linux-Family/CaramOS" alt="CaramOS GitHub contributors">
  </a>
</p>

### License

CaramOS is open-source software licensed under [GPL-3.0](LICENSE).

### Acknowledgments

- [Linux Mint](https://linuxmint.com/) — Outstanding base distribution
- [Ubuntu](https://ubuntu.com/) — Stable LTS foundation through Linux Mint
- [VNLF (Vietnam Linux Family)](https://vietnamlinuxfamily.net) — Vietnamese Linux community
- [vinceliuice](https://github.com/vinceliuice) — Tela icons and Linux desktop theming ecosystem
- Fcitx5 and Lotus contributors — Vietnamese input method support

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  Made with love by <a href="https://vietnamlinuxfamily.net">Vietnam Linux Family</a>
</p>
