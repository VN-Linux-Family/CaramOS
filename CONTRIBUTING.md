# Hướng dẫn đóng góp — CaramOS

Cảm ơn bạn đã quan tâm đến CaramOS! Tài liệu này mô tả kiến trúc dự án, cách build ISO, quy trình phát triển, và cách đóng góp.

> [README tiếng Việt](README.md) · [English](CONTRIBUTING_EN.md)

---

## Mục lục

- [Kiến trúc dự án](#kiến-trúc-dự-án)
- [Build ISO](#build-iso)
- [Cách đóng góp](#cách-đóng-góp)
- [Quy trình phát triển](#quy-trình-phát-triển)
- [Tiêu chuẩn code](#tiêu-chuẩn-code)
- [Báo lỗi & đề xuất](#báo-lỗi--đề-xuất)

---

## Kiến trúc dự án

CaramOS = **Linux Mint** + **CaramOS customization**.

Build bằng cách **remaster ISO Mint gốc**: extract → chroot → tuỳ biến → đóng gói ISO mới.

```
Linux Mint ISO (Cinnamon 22)
     ↓ extract + chroot
+ Cài thêm packages    (config/packages.txt)
+ Copy overlay files    (config/includes.chroot/)
+ Chạy hooks            (config/hooks/live/)
     ↓ mksquashfs + xorriso
= CaramOS ISO
```

### Cấu trúc thư mục

```
CaramOS/
├── build.sh                               # Entry point — điều phối build
├── Makefile                               # make build / clean
│
├── scripts/                               # Build modules
│   ├── config.sh                          # Version, mirror, output config
│   ├── utils.sh                           # Log, check root, cài deps, tìm ISO
│   ├── extract.sh                         # Mount ISO + unsquashfs
│   ├── customize.sh                       # Chroot + packages + overlay + hooks
│   └── repack.sh                          # mksquashfs + xorriso → ISO
│
├── config/
│   ├── packages.txt                       # Package CẦN THÊM (Mint ISO đã có hầu hết)
│   ├── hooks/live/
│   │   └── 0100-caramos-setup.hook.chroot # Chrome, theme, icon, cursor, locale
│   └── includes.chroot/                   # Overlay → / (copy vào filesystem)
│       ├── etc/sddm.conf.d/              # SDDM login screen
│       ├── etc/skel/.config/              # Config mặc định user mới
│       │   ├── cinnamon/                  # Panel layout Chrome OS
│       │   ├── fcitx5/                    # Bộ gõ tiếng Việt
│       │   ├── autostart/                 # Flameshot screenshot
│       │   └── mimeapps.list              # Chrome mặc định
│       └── usr/share/
│           ├── glib-2.0/schemas/          # Dconf (theme, icon, font...)
│           ├── backgrounds/caramos/       # Hình nền
│           └── pixmaps/                   # Logo
│
├── debian/                                # Debian packaging → .deb
├── README.md, CONTRIBUTING.md, LICENSE
└── .gitignore
```

### Build flow — script nào làm gì

| Script | Làm gì |
|---|---|
| `build.sh` | Entry point — gọi các script bên dưới |
| `scripts/config.sh` | Cấu hình: Mint version, mirror, tên ISO output |
| `scripts/utils.sh` | Log màu, check root, tự cài deps, tìm/tải ISO |
| `scripts/extract.sh` | Mount ISO → rsync → unsquashfs filesystem |
| `scripts/customize.sh` | Chroot → cài packages.txt → copy overlay → chạy hooks → dọn dẹp |
| `scripts/repack.sh` | mksquashfs → xorriso → ISO bootable (UEFI + Legacy) |

### Hook — Chạy gì trong chroot

**`0100-caramos-setup.hook.chroot`:**
- Cài Google Chrome (.deb)
- Cài ChromeOS GTK theme, Tela Circle icons, Bibata cursor
- Gỡ bloatware (Thunderbird, Hexchat...)
- Set Vietnamese locale + cài Be Vietnam Pro font
- Compile dconf schemas

### Overlay — File nào đi đâu

| Trong repo | Đích trên ISO |
|---|---|
| `config/includes.chroot/etc/sddm.conf.d/` | `/etc/sddm.conf.d/` |
| `config/includes.chroot/etc/skel/` | `/etc/skel/` |
| `config/includes.chroot/usr/share/glib-2.0/schemas/` | `/usr/share/glib-2.0/schemas/` |
| `config/includes.chroot/usr/share/backgrounds/` | `/usr/share/backgrounds/` |

---

## Build ISO

### Yêu cầu

#### Cách 1: Máy thật (Chỉ hỗ trợ Ubuntu/Mint)
- Máy chạy **Ubuntu 22.04+** hoặc **Linux Mint 21+**
- Khoảng **15 GB** dung lượng trống
- Mạng internet

#### Cách 2: Qua Docker (Mọi hệ điều hành như macOS, Windows, Arch...)
- Cài sẵn **Docker** và plugin **docker compose**
- Không cần cài thêm dependencies nào khác

### Cách Build

Clone repo về máy:
```bash
git clone https://github.com/VN-Linux-Family/CaramOS.git
cd CaramOS
```

#### Build Local (Ubuntu/Mint)

```bash
# 1. Cài công cụ (lần đầu)
sudo apt install squashfs-tools xorriso rsync wget curl isolinux

# 2. Build Dev (Nén lz4 nhanh, ISO to ~3.5GB)
make build

# HOẶC Build Release (Nén xz chậm, ISO nhỏ ~2.5GB)
make release
```

#### Build bằng Docker (Mọi OS)

```bash
# Lần đầu chạy sẽ tự build image
make docker-build       # Build Dev mode (lz4)
make docker-release     # Build Release mode (xz)
```

Chờ **1-10 phút** (tuỳ chọn nén lz4/xz) → ra file `CaramOS-X.X-cinnamon-amd64.iso`

### Ghi USB

```bash
sudo dd if=CaramOS-*.iso of=/dev/sdX bs=4M status=progress
# Hoặc dùng Balena Etcher (GUI)
```

### Test trong VM

```bash
qemu-system-x86_64 -m 4G -cdrom CaramOS-*.iso -boot d -enable-kvm
# Hoặc dùng VirtualBox / GNOME Boxes
```

### Dọn dẹp

```bash
sudo ./build.sh --clean
```

---

## Cách đóng góp

### Bạn có thể giúp gì?

| Vai trò | Công việc | Yêu cầu |
|---|---|---|
| **Tester** | Test ISO trên nhiều loại máy, báo lỗi | Có máy tính để test |
| **Designer** | Wallpaper, icon, theme, branding | Biết thiết kế đồ hoạ |
| **Developer** | Script, hook, config | Bash |
| **Writer** | Tài liệu hướng dẫn, dịch thuật | Viết tiếng Việt/Anh tốt |

### Quy trình đóng góp code

1. **Fork** repo → **Clone** → **Tạo branch** → **Commit** → **Push** → **Pull Request**

### Quy tắc Pull Request

- 1 PR = 1 tính năng hoặc 1 bug fix
- Mô tả rõ PR làm gì và tại sao
- Đảm bảo đã test trước khi tạo PR

---

## Quy trình phát triển

### Branch strategy

```
main            ← Bản ổn định, build ISO phát hành
├── develop     ← Nhánh phát triển chính
├── feature/*   ← Tính năng mới
├── fix/*       ← Sửa lỗi
└── release/*   ← Chuẩn bị phát hành
```

### Versioning — Semantic Versioning

```
CaramOS X.Y.Z
X = Major   Y = Minor   Z = Patch
```

---

## Tiêu chuẩn code

### Commit message — [Conventional Commits](https://www.conventionalcommits.org/)

```
feat:     tính năng mới
fix:      sửa lỗi
docs:     tài liệu
chore:    build, config
brand:    wallpaper, logo, theme
```

### Bash (hook scripts)

```bash
#!/bin/bash
set -e

# Comment giải thích mỗi block
echo "[CaramOS] Installing..."
apt-get install -y package-name
```

---

## Báo lỗi & đề xuất

Tạo [Issue trên GitHub](https://github.com/VN-Linux-Family/CaramOS/issues):

**Báo lỗi:** Mô tả lỗi → Cách tái hiện → Kết quả mong đợi → Thông tin hệ thống → Log/ảnh

**Đề xuất tính năng:** Mô tả → Lý do → Giải pháp đề xuất

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  <a href="https://github.com/VN-Linux-Family/CaramOS">github.com/VN-Linux-Family/CaramOS</a>
</p>
