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
is built as an **ISO remaster**: extract the official Linux Mint ISO, customize
the root filesystem with packages/overlays/hooks, then repack it as CaramOS.

> [!IMPORTANT]
> **Current ISO version:** `1.0.1` — **Open Beta**.  
> **Latest OTA update target:** `1.0.10` via `caramos-ota`.
> CaramOS is currently in open beta to gather feedback from the community.
> We warmly welcome suggestions, bug reports, UI/package improvements,
> installation feedback, and ideas that make CaramOS friendlier for Vietnamese
> users and the wider Linux community.

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

CaramOS uses the `caramos-ota` package for updates after an ISO has shipped. An
installed machine can start from ISO version `1.0.1` and later move to a newer
CaramOS version such as `1.0.10` through an ordered migration chain.

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
- System-changing logic lives in `packages/caramos-ota`, not in documentation.
- Developers adding post-release changes must write versioned OTA migrations.

See [packages/caramos-ota/README.md](packages/caramos-ota/README.md) for the OTA
architecture and developer workflow.

### Tech Stack

| Component | Technology |
|---|---|
| **Base ISO** | Linux Mint 22.3 Cinnamon 64-bit |
| **Ubuntu base** | Ubuntu 24.04 LTS / noble |
| **Desktop** | Cinnamon |
| **Display manager** | LightDM from the Linux Mint base |
| **Build method** | ISO remaster: extract → customize → repack |
| **Build scripts** | Bash + Makefile |
| **Dev compression** | SquashFS `lz4` |
| **Release compression** | SquashFS `xz` |
| **Theme** | Cinnamon Delight |
| **Icons** | Tela circle / Cinnamon Delight Icons |
| **Cursor** | Bibata |
| **Font** | Be Vietnam Pro |
| **Input Method** | Fcitx5 + Lotus |
| **Browser** | Google Chrome |
| **Office** | WPS Office |
| **Chat** | Zalo AppImage |
| **OTA** | `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update` |

### Build ISO

Install build dependencies on Ubuntu/Mint/Debian:

```bash
sudo apt install squashfs-tools xorriso rsync wget curl isolinux syslinux-common
```

Clone the repository and run a dev build:

```bash
git clone git@github.com:VN-Linux-Family/CaramOS.git
cd CaramOS
make build
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

Fast boot splash iteration:

```bash
make boot-only
make iso-only
```

Fast overlay/theme/app configuration iteration:

```bash
make customize-only
make quick
```

### Contributing

We welcome contributions! See [CONTRIBUTING_EN.md](CONTRIBUTING_EN.md) for guidelines.

1. Fork this repo
2. Create a new branch (`git checkout -b feature/my-feature`)
3. Commit changes (`git commit -m 'Add new feature'`)
4. Push to branch (`git push origin feature/my-feature`)
5. Create a Pull Request

**You can help with:**
- Bug reports and feature suggestions via [Issues](https://github.com/VN-Linux-Family/CaramOS/issues)
- Wallpaper, icon, theme, and branding design
- Testing ISO and OTA updates on different hardware or VM snapshots
- Documentation and translations
- Writing safe hooks, overlays, package changes, and OTA migrations

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
