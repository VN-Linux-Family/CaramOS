# Contributing Guide — CaramOS

Thank you for your interest in CaramOS! This document describes the project architecture, how to build the ISO, development workflow, and how to contribute.

> [Tiếng Việt](CONTRIBUTING.md) · [README](README_EN.md)

---

## Table of Contents

- [Project Architecture](#project-architecture)
- [Build ISO](#build-iso)
- [How to Contribute](#how-to-contribute)
- [Development Workflow](#development-workflow)
- [Code Standards](#code-standards)
- [Bug Reports & Feature Requests](#bug-reports--feature-requests)

---

## Project Architecture

CaramOS = **Linux Mint** + **CaramOS customization**.

Built by **remastering the official Mint ISO**: extract → chroot → customize → repack.

```
Linux Mint ISO (Cinnamon 22)
     ↓ extract + chroot
+ Install extra packages  (config/packages.txt)
+ Copy overlay files      (config/includes.chroot/)
+ Run hooks               (config/hooks/live/)
     ↓ mksquashfs + xorriso
= CaramOS ISO
```

### Directory Structure

```
CaramOS/
├── build.sh                               # Entry point — orchestrates build
├── Makefile                               # make build / clean
│
├── scripts/                               # Build modules
│   ├── config.sh                          # Version, mirror, output config
│   ├── utils.sh                           # Logging, root check, auto-install deps
│   ├── extract.sh                         # Mount ISO + unsquashfs
│   ├── customize.sh                       # Chroot + packages + overlay + hooks
│   └── repack.sh                          # mksquashfs + xorriso → ISO
│
├── config/
│   ├── packages.txt                       # Extra packages to install
│   ├── hooks/live/
│   │   └── 0100-caramos-setup.hook.chroot # Chrome, theme, icons, cursor, locale
│   └── includes.chroot/                   # Overlay → / (copied into filesystem)
│       ├── etc/sddm.conf.d/              # SDDM login screen
│       ├── etc/skel/.config/              # Default user config
│       └── usr/share/                     # Dconf, wallpapers, pixmaps
│
├── debian/                                # Debian packaging → .deb
├── README.md, CONTRIBUTING.md, LICENSE
└── .gitignore
```

### Build Flow — What Each Script Does

| Script | What it does |
|---|---|
| `build.sh` | Entry point — calls scripts below |
| `scripts/config.sh` | Config: Mint version, mirror, ISO output name |
| `scripts/utils.sh` | Colored logging, root check, auto-install deps, find/download ISO |
| `scripts/extract.sh` | Mount ISO → rsync → unsquashfs filesystem |
| `scripts/customize.sh` | Chroot → install packages.txt → copy overlay → run hooks → cleanup |
| `scripts/repack.sh` | mksquashfs → xorriso → bootable ISO (UEFI + Legacy) |

---

## Build ISO

### Requirements

- Machine running **Ubuntu 22.04+** or **Linux Mint 21+**
- About **15 GB** free disk space
- Internet connection (first run downloads ~2.5GB Mint ISO)

### Build

```bash
# 1. Install tools (first time only)
sudo apt install squashfs-tools xorriso rsync wget

# 2. Clone repo
git clone https://github.com/VN-Linux-Family/CaramOS.git
cd CaramOS

# 3. Build — single command, auto-downloads Mint ISO + remasters
sudo ./build.sh

# Or use an existing Mint ISO:
sudo ./build.sh /path/to/linuxmint-22-cinnamon-64bit.iso
```

Wait **15-30 minutes** → `CaramOS-0.1-cinnamon-amd64.iso` is created.

### Write to USB

```bash
sudo dd if=CaramOS-*.iso of=/dev/sdX bs=4M status=progress
```

### Test in VM

```bash
qemu-system-x86_64 -m 4G -cdrom CaramOS-*.iso -boot d -enable-kvm
```

### Clean up

```bash
sudo ./build.sh --clean
```

---

## How to Contribute

| Role | Tasks | Requirements |
|---|---|---|
| **Tester** | Test ISO on different hardware | A computer to test on |
| **Designer** | Wallpapers, icons, themes | Graphic design skills |
| **Developer** | Scripts, hooks, configs | Bash |
| **Writer** | Documentation, translations | Good Vietnamese/English writing |

### Contribution Workflow

1. **Fork** → **Clone** → **Branch** → **Commit** → **Push** → **Pull Request**

### Pull Request Rules

- 1 PR = 1 feature or 1 bug fix
- Clearly describe what and why
- Test before creating PR

---

## Development Workflow

### Branch Strategy

```
main            ← Stable, release ISOs
├── develop     ← Main development
├── feature/*   ← New features
├── fix/*       ← Bug fixes
└── release/*   ← Release preparation
```

---

## Code Standards

### Commit Messages — [Conventional Commits](https://www.conventionalcommits.org/)

```
feat:     new feature
fix:      bug fix
docs:     documentation
chore:    build, config
brand:    wallpaper, logo, theme
```

### Bash (hook scripts)

```bash
#!/bin/bash
set -e

echo "[CaramOS] Installing..."
apt-get install -y package-name
```

---

## Bug Reports & Feature Requests

Create an [Issue on GitHub](https://github.com/VN-Linux-Family/CaramOS/issues):

**Bug report:** Description → Steps to reproduce → Expected result → System info

**Feature request:** Description → Reason → Proposed solution

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  <a href="https://github.com/VN-Linux-Family/CaramOS">github.com/VN-Linux-Family/CaramOS</a>
</p>
