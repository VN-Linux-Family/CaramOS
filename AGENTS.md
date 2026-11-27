# CaramOS - Bản phân phối Linux (ISO Remaster)

## Tổng quan dự án

CaramOS là bản phân phối Linux dựa trên Linux Mint 22 (Ubuntu 24.04 LTS), thiết kế cho người dùng Việt Nam. Phương pháp build: ISO Remaster — giải nén ISO gốc → tùy biến (packages, overlay, hooks) → đóng gói lại (squashfs + xorriso).

## Cấu trúc dự án

```
./
├── build.sh              # Script build chính (điểm khởi đầu)
├── Makefile              # Các target build
├── scripts/              # Các module build
│   ├── config.sh         # Version, mirror, cấu hình output
│   ├── utils.sh          # Log, kiểm tra root, cài deps, tải ISO
│   ├── extract.sh        # Mount ISO + rsync + unsquashfs
│   ├── customize.sh      # Chroot + packages + overlay + hooks
│   ├── repack.sh         # mksquashfs + xorriso → ISO
│   ├── boot_config.sh    # Boot menu + Plymouth branding
│   ├── overlay.sh        # Copy includes.chroot vào rootfs
│   ├── chroot_shell.sh   # Debug chroot
│   └── debug_iso.sh      # Kiểm tra boot splash/Plymouth
├── packages/
│   ├── caramos-ota/      # Gói OTA: migration, Update Center, Control Center
│   └── caramos-app-center/  # Git submodule VN-Linux-Family/CaramOS-app-center (App Center)
├── config/
│   ├── packages.txt      # Packages cần thêm (flameshot, vlc...)
│   ├── hooks/live/       # Hooks chạy bên trong chroot
│   │   └── NNNN-ten.hook.chroot  # Đặt tên theo thứ tự ưu tiên (0100, 0200...)
│   └── includes.chroot/  # Overlay files copy vào rootfs
│       ├── etc/          # dconf, lightdm, skel, locale, hostname
│       └── usr/share/    # applications, backgrounds, icons, themes
├── docker-compose.yml    # Cấu hình Docker builder
├── Dockerfile            # Ubuntu 24.04 base cho containerized build
└── assets/              # Logo, banner images
```

## Lệnh build

### Build Local (Chỉ Ubuntu/Mint/Debian)

- `make build` — Build dev đầy đủ (nén lz4, nhanh)
- `make release` — Build release (nén xz, ISO nhỏ hơn)
- `make prepare` — Giải nén ISO ra build/ để sửa/test nhanh
- `make quick` — Prepare nếu cần → overlay → repack (lặp nhanh)
- `make overlay` — Chỉ copy includes.chroot vào rootfs
- `make customize-only` — Chạy packages + overlay + hooks
- `make repack` — Repack squashfs + ISO từ work tree có sẵn
- `make iso-only` — Tạo lại ISO chỉ từ build/custom
- `make shell` — Vào chroot build/squashfs để debug thủ công
- `make boot-only` — Chỉ áp dụng boot config + Plymouth branding
- `make clean` — Xóa toàn bộ build/cache/output (giữ source ISO)

### Build Docker (Mọi hệ điều hành)

- `make docker-build` — Build dev trong Docker container
- `make docker-release` — Build release trong Docker container
- `make docker-clean` — Clean build qua Docker

### Debug

- `make debug-iso` — Kiểm tra trạng thái boot menu/Plymouth
- `make debug-iso ISO=ten_file.iso` — Kiểm tra ISO cụ thể

### Tham số

- `make build ISO=linuxmint-22.3-cinnamon-64bit.iso` — Build từ ISO có sẵn

## Quy trình build

```
1. extract.sh     Mount source ISO → rsync filesystem → unsquashfs
   → build/squashfs/ (base chỉ đọc)
   → build/custom/ (work tree)

2. customize.sh   chroot vào build/custom/
   → Cài packages từ config/packages.txt
   → Copy overlay từ config/includes.chroot/
   → Chạy các script hooks trong config/hooks/live/

3. repack.sh      mksquashfs build/custom/ → build/CaramOS.sfs
   → xorriso → CaramOS-VERSION-cinnamon-amd64.iso
```

## Quy ước

### Hook Files

- Vị trí: `config/hooks/live/`
- Đặt tên: `NNNN-ten.hook.chroot` (prefix 4 số thứ tự)
- Thứ tự thực thi: Tăng dần theo số (0100, 0200, 0900...)
- Ví dụ: `0100-caramos-setup.hook.chroot`

### Bash Scripts

- Dùng `set -e` để xử lý lỗi
- Tất cả scripts trong `scripts/` đều có thể chạy độc lập với `--help`

### Cấu hình Version

- Chỉnh sửa `scripts/config.sh` để thay đổi: MINT_VERSION, CARAMOS_VERSION, MIRROR, OUTPUT_ISO
- Nén mặc định: lz4 (dev nhanh), xz cho release
- Bản sửa nóng tới máy người dùng có số CaramOS mới dạng `x.y.z.n`, ví dụ `make release VERSION=1.5.2.1`, và không dựng ISO. Không chỉ tăng đuôi `-0caramosN`: đuôi này chỉ dành cho lần dựng lại gói mà trên máy không đổi gì. Chi tiết trong [docs/release-version-tracking.md](docs/release-version-tracking.md).

### Output

- ISO output: `CaramOS-${CARAMOS_VERSION}-cinnamon-amd64.iso`
- Build artifacts: thư mục `./build/`
- Source ISO được giữ nguyên trong cache/ sau khi extract

## Lưu ý quan trọng

### Yêu cầu

- Build cần **sudo/root** (mount, chroot, loop operations)
- Build local: Ubuntu 24.04/Mint 22/Debian base
- Build Docker hoạt động trên mọi hệ điều hành (macOS, Windows, mọi distro Linux)

### Khuyến nghị dùng Docker

Dùng Docker để build nếu không dùng Ubuntu 24.04:

```bash
docker compose up --build builder
# hoặc đơn giản:
make docker-build
```

### CI/CD

GitHub Actions workflow trong `.github/workflows/build.yml` build trên Ubuntu 24.04 runners.

### App Center (submodule)

- `packages/caramos-app-center` là git submodule của repo riêng `VN-Linux-Family/CaramOS-app-center`, có version riêng và phát hành bằng GitHub Release, không qua PPA (`make -C packages/caramos-app-center release VERSION=x`, rồi push tag; workflow ký `latest.json` bằng chìa App Center).
- Clone: `git clone --recurse-submodules ...` hoặc `git submodule update --init`. Build ISO dựng gói từ submodule (`scripts/ota_bootstrap.sh`).
- Sửa App Center: commit + push trong submodule trước, rồi commit con trỏ submodule trong CaramOS.
- `caramos-ota` (`caramos_ota/app_center.py`) cài và cập nhật App Center từ GitHub Release trong lần kiểm tra OTA hằng ngày, sau khi kiểm tra chữ ký bằng chìa `usr/share/caramos-ota/keys/caramos-app-center-release.gpg`.

### Git Workflow

- Định dạng commit: prefix `[build]`, `[config]`, `[assets]`, `[docs]`
- AGENTS.md: Commit lên Git để team share context
- Không cần .claudeignore — project không phải TypeScript/Node.js

## Đóng góp

Để xem hướng dẫn chi tiết về đóng góp (kiến trúc, thêm packages, tạo hooks, sửa overlay, quy trình test), xem [CONTRIBUTING.md](CONTRIBUTING.md).

Bảng tra nhanh:

| Task                      | Vị trí                                   | Hành động                              |
| ------------------------- | ---------------------------------------- | -------------------------------------- |
| Thêm package              | `config/packages.txt`                    | Sửa file, sau đó `make customize-only` |
| Tạo hook mới              | `config/hooks/live/NNNN-ten.hook.chroot` | Xem các hook có sẵn để lấy template    |
| Sửa config hệ thống       | `config/includes.chroot/etc/`            | Sửa, sau đó `make overlay`             |
| Sửa theme/icons           | `config/includes.chroot/usr/share/`      | Sửa, sau đó `make overlay`             |
| Test toàn bộ sau thay đổi | —                                        | `make quick && test in VM`             |
| Debug trong chroot        | —                                        | `make shell`                           |
