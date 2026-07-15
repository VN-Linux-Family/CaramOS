# Hướng dẫn đóng góp — CaramOS

Cảm ơn bạn đã quan tâm đến CaramOS! Tài liệu này mô tả cách đóng góp theo mô
hình mới của dự án: **OTA-first**.

> [README tiếng Việt](README.md) · [English](CONTRIBUTING_EN.md)

---

## Mục lục

- [Trạng thái hiện tại](#trạng-thái-hiện-tại)
- [Kiến trúc OTA-first](#kiến-trúc-ota-first)
- [Cấu trúc dự án](#cấu-trúc-dự-án)
- [Build ISO](#build-iso)
- [Phát triển với OTA](#phát-triển-với-ota)
- [Quy trình đóng góp](#quy-trình-đóng-góp)
- [Tiêu chuẩn code](#tiêu-chuẩn-code)
- [Báo lỗi và đề xuất](#báo-lỗi-và-đề-xuất)

---

## Trạng thái hiện tại

CaramOS đã chuyển sang mô hình cập nhật bằng **CaramOS OTA**.

- ISO mới vẫn được build và phát hành.
- Máy đã cài CaramOS `1.0.1` không cần cài lại ISO.
- User chỉ cần cài Trung tâm cập nhật CaramOS rồi nâng cấp qua OTA.

Lệnh dành cho user đang ở CaramOS `1.0.1`:

```bash
curl -fsSL https://caramos.vietnamlinuxfamily.net/install-caramos-ota.sh | sudo bash
```

Sau khi cài xong, user mở **Trung tâm cập nhật CaramOS** từ Start Menu để kiểm
tra và nâng hệ thống lên version mới nhất.

> [!IMPORTANT]
> Contributor/developer không nên thêm cập nhật hệ thống mới trực tiếp vào
> `config/hooks/live/`. Nếu thay đổi cần áp dụng cho máy user đã cài CaramOS,
> hãy viết OTA migration trong `packages/caramos-ota`.

---

## Kiến trúc OTA-first

CaramOS vẫn dùng ISO remaster, nhưng ISO build bây giờ có bước OTA bootstrap:

```text
Linux Mint ISO
  → extract rootfs
  → install packages + overlay + build-time hooks
  → build/install bundled caramos-ota
  → run caramos-ota-update migrations inside rootfs
  → repack squashfs + ISO CaramOS
```

Điểm quan trọng:

- `scripts/config.sh` chứa version ISO và base migration version.
- `CARAMOS_MIGRATION_BASE_VERSION="1.0.1"` được giữ để ISO build chạy đủ chain
  migration từ bản Open Beta đầu tiên tới latest.
- `scripts/ota_bootstrap.sh` build package `caramos-ota`, cài vào rootfs và chạy
  migration trước khi repack ISO.
- Kết quả ISO build ra đã là version mới nhất trong source tree.
- OTA là đường nâng cấp cho máy user đã cài từ ISO cũ.

### Không code feature mới vào hook nếu đó là cập nhật cho user

`config/hooks/live/` chỉ nên dùng cho build-time/bootstrap thật sự cần thiết.
Ví dụ:

- chuẩn bị môi trường rootfs trước khi OTA bootstrap chạy;
- thao tác chỉ có ý nghĩa trong lúc build ISO;
- fix build system, boot branding, hoặc dependency nền.

Nếu thay đổi cần tới được máy user đã cài, ví dụ panel, dconf, Fcitx5, desktop
launcher, theme, `/etc/caramos-release`, package state..., hãy viết migration.

---

## Cấu trúc dự án

```text
CaramOS/
├── build.sh                         # Entry point build ISO
├── Makefile                         # make build/release/quick/docker-build...
├── scripts/                         # Module build ISO
│   ├── config.sh                    # Version ISO, migration base, mirror, output
│   ├── extract.sh                   # Mount ISO + unsquashfs
│   ├── customize.sh                 # Packages + overlay + hooks + OTA bootstrap
│   ├── ota_bootstrap.sh             # Build/install OTA package và chạy migration
│   ├── repack.sh                    # mksquashfs + xorriso
│   ├── boot_config.sh               # Boot menu/Plymouth branding
│   └── utils.sh                     # Log, deps, ISO helpers
├── config/                          # Lớp bootstrap ISO/rootfs
│   ├── packages.txt                 # Packages nền cài khi build ISO
│   ├── includes.chroot/             # Overlay copy vào rootfs
│   └── hooks/live/                  # Hook build-time legacy, hạn chế thêm mới
├── packages/
│   └── caramos-ota/                 # Hệ thống OTA chính
│       ├── debian/changelog         # Version package upload PPA
│       ├── usr/bin/
│       │   ├── caramos-ota          # CLI/orchestrator
│       │   ├── caramos-ota-notifier # Update Center/notifier
│       │   └── caramos-ota-update   # Migration runner
│       └── usr/lib/python3/dist-packages/
│           ├── caramos_ota/
│           ├── caramos_ota_notifier/
│           └── caramos_ota_update/migrations/
│               ├── migration.json       # bridge lịch sử, không thêm entry mới
│               ├── v1_0_*/              # legacy migrations tới 1.0.13
│               └── YYYYMMDDHHMMSS_name/
│                   ├── manifest.json
│                   └── migration.py
├── landing/                         # Website/landing page
├── docs/                            # Tài liệu vận hành/release tracking
├── assets/                          # Logo, banner, screenshot
└── .github/workflows/               # CI/release workflow
```

Tài liệu OTA chi tiết nằm tại:

- [packages/README.md](packages/README.md)
- [packages/caramos-ota/README.md](packages/caramos-ota/README.md)

---

## Build ISO

### Local build

Yêu cầu: Ubuntu/Mint/Debian phù hợp, có `sudo`, đủ dung lượng cho rootfs và ISO.

```bash
sudo apt update
sudo apt install squashfs-tools xorriso rsync wget curl isolinux syslinux-common syslinux-utils
```

Build dev nhanh:

```bash
make build
```

Build release nén nhỏ hơn:

```bash
make release
```

Build từ ISO Mint có sẵn:

```bash
make build ISO=linuxmint-22.3-cinnamon-64bit.iso
```

Trong lúc build, `customize.sh` sẽ gọi OTA bootstrap. Vì vậy nếu bạn sửa
`packages/caramos-ota`, build ISO lại sẽ nhúng package OTA mới và chạy migration
vào rootfs trước khi đóng ISO.

### Docker build

Dùng Docker nếu máy không phải Ubuntu/Mint/Debian phù hợp:

```bash
make docker-build
make docker-release
```

### Workflow sửa nhanh

| Bạn sửa gì | Nên chạy gì |
|---|---|
| Overlay/asset nền ISO | `make overlay && make quick` |
| Boot menu/Plymouth | `make boot-only && make iso-only` |
| OTA migration/package | test trong `packages/caramos-ota`, rồi `make customize-only` hoặc `make build` |
| Version release | sửa `scripts/config.sh`, cập nhật docs/landing theo `docs/release-version-tracking.md` |

---

## Phát triển với OTA

### Khi nào cần migration?

Tạo OTA migration khi thay đổi ảnh hưởng tới máy đã cài CaramOS, ví dụ:

- thay đổi Cinnamon panel/dconf/default app launcher;
- sửa Fcitx5/Lotus, input method hoặc autostart;
- cập nhật branding, theme, icon, wallpaper áp dụng cho user hiện có;
- thêm/sửa package do CaramOS quản lý;
- sửa `/etc/caramos-release`, `/etc/lsb-release`, `/etc/os-release`;
- cần chạy command một lần trên máy user sau release.

Không dùng hook để thay thế migration cho các trường hợp trên.

### File cần thêm cho một OTA migration

```text
packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/
└── YYYYMMDDHHMMSS_ten_migration/
    ├── manifest.json
    ├── migration.py
    └── payload tùy chọn
```

Lấy timestamp bằng `date -u +%Y%m%d%H%M%S`. `manifest.json` schema 2 khai báo
`release`, metadata UI, `codename` và `channel`. `migration.py` khai báo
`DESCRIPTION` và `run(context)`. Không thêm entry vào `migration.json`; file đó là
bridge lịch sử tới `1.0.13`. Xem mẫu đầy đủ tại
[packages/caramos-ota/MIGRATIONS.md](packages/caramos-ota/MIGRATIONS.md).

### Quy tắc migration

- ID timestamp đã phát hành là bất biến; sửa tiếp bằng migration ID mới.
- Nhiều migration được phép cùng một `release`; runner chạy theo thứ tự ID.
- Migration phải idempotent hoặc có guard chống chạy lặp.
- Không tải/chạy script từ internet trong migration.
- Không tải `.deb` thủ công; dùng APT/PPA đã cấu hình sẵn.
- Không hardcode user như `caram` hoặc `mint`; phải tự phát hiện user desktop thật.
- Không tự thêm PPA/keyring trong migration nếu chưa được review ở package/ISO.
- Phải log rõ từng action qua `context.log(...)`.
- `dry-run` không được sửa hệ thống.
- Command user-session như `systemctl --user`, `gsettings`, `fcitx5` phải có
  timeout ngắn và fallback.
- Nếu cần restart service/desktop component, ưu tiên best-effort và báo user
  logout/login khi cần.

### Test OTA trước PR

Trong package OTA:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

Nếu có VM test:

```bash
make ship
make vm-test-cli
make vm-test-notifier
```

Checklist trước PR:

- [ ] Migration mới có ID UTC timestamp duy nhất và release rõ ràng.
- [ ] Không sửa `migration.json`; `manifest.json` schema 2 hợp lệ.
- [ ] `make compile`, `make validate`, `./tools/caramos-ota-testkit.sh test`, `make build` pass.
- [ ] Đã test upgrade từ version cũ trong VM snapshot nếu có thể.
- [ ] Update Center không treo khi migration lỗi hoặc command timeout.
- [ ] Log trong `/var/log/caramos-ota/` đủ để debug.
- [ ] README/landing/release notes được cập nhật nếu đây là release mới.

---

## Quy trình đóng góp

1. Fork repo.
2. Tạo branch từ `develop` hoặc branch được maintainer chỉ định.
3. Thực hiện thay đổi nhỏ, rõ phạm vi.
4. Test theo loại thay đổi.
5. Commit với message có prefix rõ.
6. Mở Pull Request và mô tả:
   - thay đổi gì;
   - vì sao cần thay đổi;
   - cách test;
   - có cần OTA migration không.

### Vai trò đóng góp

| Vai trò | Công việc |
|---|---|
| Tester | Test ISO/OTA trên máy thật hoặc VM, báo lỗi kèm log/ảnh |
| Developer | Viết migration, sửa package OTA, build scripts, bug fix |
| Designer | Wallpaper, icon, banner, branding assets |
| Writer | README, hướng dẫn user, changelog, bản dịch |

### Branch và release

```text
main       # nhánh ổn định/release
feat/*     # tính năng mới
fix/*      # sửa lỗi
docs/*     # tài liệu
release/*  # chuẩn bị release
```

Khi bump version release, theo dõi checklist ở
[docs/release-version-tracking.md](docs/release-version-tracking.md).

---

## Tiêu chuẩn code

### Commit message

Dự án ưu tiên prefix ngắn, dễ scan:

```text
[build] sửa build script / Docker / CI
[config] package list, overlay, system config
[assets] logo, wallpaper, screenshot
[docs] README, guide, changelog
[ota] caramos-ota, migration, notifier, updater
[release] bump version/tag/release metadata
```

### Bash

- Dùng `set -e` hoặc xử lý lỗi rõ ràng.
- Log rõ block đang làm gì.
- Không tải/chạy script không kiểm soát.
- Script trong `scripts/` nên có `--help` nếu chạy độc lập.

### Python migration

- Ưu tiên stdlib, tránh thêm dependency nếu không cần.
- Không hardcode username/home path.
- Kiểm tra tồn tại file trước khi sửa/xoá.
- Backup hoặc ghi log đủ rõ cho thay đổi rủi ro.
- Tôn trọng `dry-run` nếu context hỗ trợ.

---

## Báo lỗi và đề xuất

Tạo issue tại: <https://github.com/VN-Linux-Family/CaramOS/issues>

Báo lỗi nên có:

- version CaramOS hiện tại;
- đang dùng ISO hay OTA;
- cách tái hiện;
- kết quả mong đợi;
- log liên quan, đặc biệt `/var/log/caramos-ota/` nếu lỗi update;
- ảnh/video nếu là lỗi giao diện.

Đề xuất tính năng nên có:

- mô tả ngắn gọn;
- lý do cần tính năng;
- ảnh hưởng tới user đã cài hay chỉ ISO mới;
- nếu ảnh hưởng user đã cài, đề xuất hướng OTA migration.

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  <a href="https://github.com/VN-Linux-Family/CaramOS">github.com/VN-Linux-Family/CaramOS</a>
</p>
