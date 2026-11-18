<p align="center">
  <img src="assets/CaramOS_logo.png" alt="CaramOS Logo" width="220">
</p>

# CaramOS 2.0 Testing — Debian 13 (Trixie) & Rust Core Edition

Nhánh phát triển thử nghiệm thế hệ mới (**Next-Gen Architecture**) của **CaramOS**, được tái cấu trúc toàn diện nhằm giải quyết triệt để các điểm nghẽn về hiệu năng đóng gói, dung lượng hệ thống và độ ổn định khi cập nhật OTA của bản CaramOS 1.x gốc.

---

## 1. Tại sao phải tái cấu trúc lại từ đầu? (Vấn đề của CaramOS 1.x Gốc)

Bản CaramOS 1.x gốc (`VN-Linux-Family/CaramOS`) gặp 3 hạn chế kiến trúc lớn:
1. **Phái sinh chồng chéo 3 tầng (`Debian -> Ubuntu 24.04 -> Linux Mint 22.3 -> CaramOS`):** Quá trình build phải tải file ISO Linux Mint nặng ~2.8 GB về, giải nén SquashFS (`unsquashfs`), xóa bớt file của Mint rồi đóng gói lại. Hệ thống bị phụ thuộc hoàn toàn vào chu kỳ phát hành và các gói ghim (pinned packages) của cả Ubuntu lẫn Linux Mint.
2. **Cơ chế cập nhật OTA bằng Python dễ gãy (`packages/caramos-ota`):** Sử dụng chuỗi script Python chạy tuần tự từng phiên bản (`v1_0_1` $\rightarrow$ `v1_0_2` $\rightarrow \dots \rightarrow$ `v1_3_11`) can thiệp trực tiếp vào `/etc` và `$HOME` của người dùng đang chạy. Nếu mất mạng hoặc xung đột cấu hình ở một bước giữa chừng, hệ thống rơi vào trạng thái lỗi nửa vời (*half-migrated state*) không thể tự khôi phục.
3. **Rủi ro từ hệ thống Script Bash (`build.sh` + 9 file `scripts/*.sh`):** Quản lý các điểm gắn kết ảo (`/proc`, `/sys`, `/dev`) trong chroot bằng biến toàn cục và `trap` thủ công, dễ gây rò rỉ mount point hoặc hỏng môi trường máy chủ khi tiến trình build bị ngắt đột ngột.

---

## 2. Bảng So Sánh Kiến Trúc: CaramOS 2.0 (Testing) vs. CaramOS 1.x (Gốc)

| Tiêu chí kỹ thuật | CaramOS 1.x (Bản Gốc VNLF) | CaramOS 2.0 (Bản Testing - Rust & Debian) |
| :--- | :--- | :--- |
| **Hệ điều hành Nền (Base OS)** | Linux Mint 22.3 (Phái sinh qua Ubuntu 24.04 LTS) | **Debian 13 (`trixie`)** trực tiếp từ kho thượng nguồn |
| **Phương thức Khởi tạo Rootfs** | Giải nén (`unsquashfs`) từ ISO Linux Mint dựng sẵn | Bootstrap sạch từ gốc bằng **`mmdebstrap`** |
| **Trình Điều phối Build & Hệ thống** | 10+ file Bash rời rạc (`build.sh`, `scripts/*.sh`) | **1 Binary Rust duy nhất (`caramos-ctl`)** |
| **Kiểm soát Trạng thái Build** | Biến môi trường toàn cục lỏng lẻo | **Compile-Time Typestate Pattern** (`Uninitialized` $\rightarrow$ `Bootstrapped` $\rightarrow$ `Customized` $\rightarrow$ `IsoPackaged`) |
| **An toàn Tài nguyên Chroot** | `trap cleanup_on_fail EXIT` bằng Bash | **RAII `ChrootMountGuard` & `ProcessLockGuard`** (Tự động tháo gỡ `/dev`, `/proc`, `/sys` xác định) |
| **Cơ chế Cập nhật Hệ thống (OTA)** | Chuỗi script Python tuần tự (`v1_0_1` $\rightarrow$ `v1_3_11`) | **Declarative Transactional OTA bằng Rust** (Kiểm định SHA-256 FIPS 180-4 + Tự động Rollback nguyên tử 100% nếu lỗi) |
| **Bộ Công cụ Nhân Người dùng (Userland)** | GNU Coreutils & `sudo` viết bằng C truyền thống | Tích hợp **Rust Core Stack**: `rust-coreutils` (`uutils`), `sudo-rs`, `ripgrep` (`rg`), `fd-find` |
| **Trình Cài đặt Lên Ổ cứng (Installer)** | `ubiquity` / `casper` (Đặc thù Ubuntu/Mint) | **`Calamares`** (`calamares-settings-debian`) + Hybrid GRUB (Hỗ trợ cả UEFI & Legacy BIOS) |
| **Âm thanh & Đa phương tiện** | PulseAudio cũ | **PipeWire + WirePlumber** độ trễ thấp |
| **Dung lượng ISO trung bình** | ~2.8 GB – 3.1 GB | **~1.2 GB – 1.5 GB** (Nhẹ hơn ~50%, loại bỏ hoàn toàn rác hệ thống) |
| **Độ an toàn Bộ nhớ (`caramos-ctl`)** | Không có kiểm tra kiểu tĩnh | `#![forbid(unsafe_code)]`, **Zero-Panic Policy** (Cấm `unwrap`, `expect`, `panic`) |

---

## 3. Cấu trúc Kho Mã Nguồn Tối Giản

Toàn bộ các script Bash, Dockerfile cũ và thư mục Python OTA rườm rà đã được loại bỏ hoàn toàn. Kho mã nguồn hiện chỉ gồm:

```text
CaramOS-testing/
├── .github/
│   └── workflows/
│       └── ci.yml                  # Pipeline CI/CD tự động: Dọn di sản -> Kiểm định Clippy/Test -> Xuất ISO
├── config/
│   ├── includes.chroot/            # Giao diện Cinnamon, Themes, Icons, Applets & Cấu hình mặc định
│   └── packages.txt                # Danh sách gói chuẩn hóa cho Debian 13 (Trixie) & Rust Core
├── crates/
│   └── caramos-ctl/                # Trái tim điều phối hệ thống viết bằng Rust thuần (Zero External Crate Deps)
│       ├── Cargo.toml
│       └── src/
│           └── main.rs             # Hợp nhất 4 phân hệ: prune, build, hash (SHA-256), ota-apply
├── packages/
│   └── caramos-app-center/         # Kho ứng dụng đồ họa cho người dùng cuối
└── Makefile                        # Giao diện lệnh tắt gọi trực tiếp vào caramos-ctl
```

---

## 4. Hướng dẫn Sử dụng & Đóng gói ISO

### 4.1. Build Tự động trên Đám mây (GitHub Actions)
Không cần máy tính cấu hình mạnh:
1. Vào tab **Actions** trên kho GitHub này.
2. Chọn workflow **CaramOS Auto-Prune & Debian Trixie CI** $\rightarrow$ bấm **Run workflow**.
3. Chọn chế độ nén:
   - `fast-zstd`: Nén nhanh bằng thuật toán Zstandard để kiểm thử.
   - `release-xz`: Nén tối đa bằng thuật toán XZ Dictionary 100% cho bản phát hành chính thức.
4. Khi tiến trình hoàn tất, tải tệp `CaramOS-2.0.0-debian-trixie-amd64-iso` tại mục **Artifacts** để ghi ra USB (bằng Ventoy / Rufus / BalenaEtcher) hoặc chạy trên máy ảo (VirtualBox / QEMU / VMware).

### 4.2. Build Trực tiếp trên Máy Cục bộ (Debian / Ubuntu)

1. **Cài đặt các gói công cụ đóng gói hệ thống:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y \
     cargo rustc clippy rustfmt \
     mmdebstrap debian-archive-keyring \
     squashfs-tools xorriso \
     grub-common grub-pc-bin grub-efi-amd64-bin mtools
   ```

2. **Kiểm chứng mã nguồn Rust (Unit Tests & Static Analysis):**
   ```bash
   make check
   make test
   ```

3. **Đóng gói file ISO CaramOS 2.0:**
   ```bash
   # Build bản thử nghiệm nhanh (nén zstd):
   make build

   # Hoặc build bản phát hành nén tối đa (nén xz):
   make release
   ```
   Ảnh ISO đầu ra và mã kiểm tra toàn vẹn sẽ nằm tại `./build/CaramOS-2.0.0-debian-trixie-amd64.iso`.

---

## 5. Các Lệnh Cốt lõi của `caramos-ctl`

```bash
# 1. Tự động giải cứu Cinnamon Applets và dọn sạch các file di sản cũ:
./crates/caramos-ctl/target/release/caramos-ctl prune --repo-root . --execute

# 2. Chạy mô phỏng toàn bộ quy trình tạo Rootfs & ISO không cần quyền root:
./crates/caramos-ctl/target/release/caramos-ctl build --dry-run --work-dir ./build_test

# 3. Tính mã băm mật mã học SHA-256 (FIPS 180-4) của tệp bất kỳ:
./crates/caramos-ctl/target/release/caramos-ctl hash ./build/CaramOS-2.0.0-debian-trixie-amd64.iso

# 4. Thực thi giao dịch cập nhật OTA nguyên tử (tự động Rollback nếu sai lệch SHA-256 hoặc lỗi I/O):
sudo ./crates/caramos-ctl/target/release/caramos-ctl ota-apply / etc/caramos-release ./payload.new <SHA256_HEX> 2.0.1
```

---

## 6. Giấy phép (License)

Dự án được phân phối dưới giấy phép nguồn mở **GNU General Public License v3.0 (GPL-3.0-only)**.

