#![forbid(unsafe_code)]
#![deny(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::todo,
    clippy::unimplemented,
    unused_must_use
)]

//! # CaramOS 2.0 Core Build & System Orchestrator (`caramos-ctl`)
//!
//! Trình điều phối đóng gói Live ISO Debian 13 (Trixie), quản lý vòng đời gắn kết Chroot (RAII),
//! dọn dẹp di sản (`prune`), băm mật mã học SHA-256 (`hash`) và cập nhật nguyên tử (`ota-apply`).
//! Đã được đồng bộ hóa 100% với `caramos-ui` để bảo toàn tuyệt đối giao diện GRUB2/Plymouth
//! và các tệp nhị phân trong `config/includes.chroot`.

use std::env;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::marker::PhantomData;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, Stdio};

// ============================================================================
// 1. KIẾN TRÚC LỖI CHUYÊN NGHIỆP (STRUCTURED DOMAIN ERRORS)
// ============================================================================

#[derive(Debug)]
pub enum CaramCtlError {
    InvalidArgument { flag: String, reason: String },
    UnsafePath { path: PathBuf, reason: &'static str },
    IoFailure { context: String, path: Option<PathBuf>, source: io::Error },
    SubprocessFailed { binary: String, status_code: Option<i32>, stderr_hint: String },
    DigestMismatch { path: PathBuf, expected: String, actual: String },
    RollbackFailed { target: PathBuf, original_error: String, rollback_error: io::Error },
}

impl fmt::Display for CaramCtlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidArgument { flag, reason } => {
                write!(f, "[CTL_ARG_ERR] Tham số '{}' không hợp lệ: {}", flag, reason)
            }
            Self::UnsafePath { path, reason } => {
                write!(
                    f,
                    "[CTL_SECURITY_ERR] Đường dẫn '{}' bị từ chối: {}",
                    path.display(),
                    reason
                )
            }
            Self::IoFailure { context, path, source } => match path {
                Some(p) => write!(
                    f,
                    "[CTL_IO_ERR] Lỗi khi '{}' tại '{}': {}",
                    context,
                    p.display(),
                    source
                ),
                None => write!(f, "[CTL_IO_ERR] Lỗi khi '{}': {}", context, source),
            },
            Self::SubprocessFailed { binary, status_code, stderr_hint } => {
                write!(
                    f,
                    "[CTL_EXEC_ERR] Tiến trình '{}' thất bại (mã thoát: {:?}): {}",
                    binary, status_code, stderr_hint
                )
            }
            Self::DigestMismatch { path, expected, actual } => {
                write!(
                    f,
                    "[CTL_CRYPTO_ERR] Mã băm SHA-256 không khớp tại '{}': kỳ vọng '{}', thực tế '{}'",
                    path.display(),
                    expected,
                    actual
                )
            }
            Self::RollbackFailed { target, original_error, rollback_error } => {
                write!(
                    f,
                    "[CTL_CRITICAL_OTA] Lỗi gốc ({}) VÀ lỗi khôi phục tại '{}': {}",
                    original_error,
                    target.display(),
                    rollback_error
                )
            }
        }
    }
}

impl std::error::Error for CaramCtlError {}

// ============================================================================
// 2. PHÒNG THỦ ĐƯỜNG DẪN & SAO CHÉP CÂY THƯ MỤC ĐỆ QUY KHÔNG GHI ĐÈ NGƯỢC
// ============================================================================

/// Kiểm định đường dẫn an toàn, chặn Path Traversal (`..`) và ký tự NULL.
pub fn validate_safe_path(path: &Path) -> Result<(), CaramCtlError> {
    let raw = path.to_string_lossy();
    if raw.is_empty() {
        return Err(CaramCtlError::UnsafePath {
            path: path.to_path_buf(),
            reason: "Đường dẫn rỗng",
        });
    }
    if raw.contains('\0') {
        return Err(CaramCtlError::UnsafePath {
            path: path.to_path_buf(),
            reason: "Đường dẫn chứa byte NULL",
        });
    }
    for comp in path.components() {
        if matches!(comp, Component::ParentDir) {
            return Err(CaramCtlError::UnsafePath {
                path: path.to_path_buf(),
                reason: "Chặn leo thang thư mục qua '..' (Path Traversal)",
            });
        }
    }
    Ok(())
}

/// Ghi tệp tin nguyên tử thông qua vùng đệm tạm và lệnh `fs::rename` kèm `sync_all`.
pub fn atomic_write_file(target: &Path, content: &[u8]) -> Result<(), CaramCtlError> {
    validate_safe_path(target)?;
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo thư mục cha cho tệp đích".to_string(),
            path: Some(parent.to_path_buf()),
            source: e,
        })?;
    }

    let staging = target.with_extension("tmp.caramos-ctl");
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(&staging)
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Mở tệp tạm atomic_write".to_string(),
            path: Some(staging.clone()),
            source: e,
        })?;

    file.write_all(content).map_err(|e| CaramCtlError::IoFailure {
        context: "Ghi nội dung vào tệp tạm".to_string(),
        path: Some(staging.clone()),
        source: e,
    })?;

    file.sync_all().map_err(|e| CaramCtlError::IoFailure {
        context: "Đồng bộ fsync tệp tạm".to_string(),
        path: Some(staging.clone()),
        source: e,
    })?;

    drop(file);

    fs::rename(&staging, target).map_err(|e| CaramCtlError::IoFailure {
        context: "Hoán đổi nguyên tử (rename) tệp đích".to_string(),
        path: Some(target.to_path_buf()),
        source: e,
    })
}

/// Chỉ ghi tệp cấu hình mặc định nếu tệp đó CHƯA được `caramos-ui` hoặc `includes.chroot` cung cấp.
pub fn write_default_if_missing(target: &Path, default_content: &[u8]) -> Result<bool, CaramCtlError> {
    validate_safe_path(target)?;
    if target.exists() {
        return Ok(false);
    }
    atomic_write_file(target, default_content)?;
    Ok(true)
}

/// Sao chép đệ quy toàn bộ cây thư mục nguồn (`src_dir`) đè lên thư mục đích (`dst_dir`),
/// bảo toàn quyền thực thi (permissions) của các tệp nhị phân như `caramos-ui` và `caramos-ctl`.
pub fn copy_directory_tree_overlay(src_dir: &Path, dst_dir: &Path) -> Result<usize, CaramCtlError> {
    validate_safe_path(src_dir)?;
    validate_safe_path(dst_dir)?;

    if !src_dir.exists() {
        return Ok(0);
    }

    fs::create_dir_all(dst_dir).map_err(|e| CaramCtlError::IoFailure {
        context: "Tạo thư mục đích khi đồng bộ overlay".to_string(),
        path: Some(dst_dir.to_path_buf()),
        source: e,
    })?;

    let mut copied_files: usize = 0;
    let entries = fs::read_dir(src_dir).map_err(|e| CaramCtlError::IoFailure {
        context: "Đọc danh mục thư mục overlay nguồn".to_string(),
        path: Some(src_dir.to_path_buf()),
        source: e,
    })?;

    for entry_res in entries {
        let entry = entry_res.map_err(|e| CaramCtlError::IoFailure {
            context: "Đọc phần tử trong thư mục overlay".to_string(),
            path: Some(src_dir.to_path_buf()),
            source: e,
        })?;

        let src_path = entry.path();
        let file_name = entry.file_name();
        let dst_path = dst_dir.join(file_name);

        let file_type = entry.file_type().map_err(|e| CaramCtlError::IoFailure {
            context: "Kiểm tra kiểu tệp overlay".to_string(),
            path: Some(src_path.clone()),
            source: e,
        })?;

        if file_type.is_dir() {
            let sub_count = copy_directory_tree_overlay(&src_path, &dst_path)?;
            copied_files = copied_files.saturating_add(sub_count);
        } else if file_type.is_file() {
            if let Some(parent) = dst_path.parent() {
                fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
                    context: "Tạo thư mục cha cho tệp overlay".to_string(),
                    path: Some(parent.to_path_buf()),
                    source: e,
                })?;
            }
            fs::copy(&src_path, &dst_path).map_err(|e| CaramCtlError::IoFailure {
                context: "Sao chép tệp overlay".to_string(),
                path: Some(dst_path.clone()),
                source: e,
            })?;

            if let Ok(meta) = fs::metadata(&src_path) {
                let _ = fs::set_permissions(&dst_path, meta.permissions());
            }
            copied_files = copied_files.saturating_add(1);
        }
    }

    Ok(copied_files)
}

// ============================================================================
// 3. KỶ LUẬT QUẢN LÝ TÀI NGUYÊN CHROOT (DETERMINISTIC RAII MOUNT GUARD)
// ============================================================================

/// RAII Guard quản lý các điểm gắn kết hệ thống ảo (`/proc`, `/sys`, `/dev`, `/dev/pts`)
/// bên trong `rootfs`. Tự động tháo gỡ (`umount -lf`) theo đúng thứ tự đảo ngược LIFO trong `Drop`.
pub struct ChrootMountGuard {
    mounted_targets: Vec<PathBuf>,
    dry_run: bool,
}

impl ChrootMountGuard {
    pub fn mount_all(rootfs: &Path, dry_run: bool) -> Result<Self, CaramCtlError> {
        validate_safe_path(rootfs)?;
        let mut guard = Self {
            mounted_targets: Vec::with_capacity(4),
            dry_run,
        };

        let mounts: [(&str, &str, &[&str]); 4] = [
            ("proc", "proc", &["-t", "proc", "proc"]),
            ("sys", "sysfs", &["-t", "sysfs", "sys"]),
            ("dev", "devtmpfs", &["--bind", "/dev"]),
            ("dev/pts", "devpts", &["--bind", "/dev/pts"]),
        ];

        for (rel_dir, _label, args) in &mounts {
            let target = rootfs.join(rel_dir);
            fs::create_dir_all(&target).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục điểm gắn kết Chroot".to_string(),
                path: Some(target.clone()),
                source: e,
            })?;

            if !dry_run {
                let mut cmd = Command::new("mount");
                for a in *args {
                    cmd.arg(a);
                }
                cmd.arg(&target);
                run_external_command(&mut cmd, "mount chroot virtualfs")?;
            }
            guard.mounted_targets.push(target);
        }

        Ok(guard)
    }
}

impl Drop for ChrootMountGuard {
    fn drop(&mut self) {
        while let Some(target) = self.mounted_targets.pop() {
            if !self.dry_run {
                let _ = Command::new("umount")
                    .arg("-lf")
                    .arg(&target)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status();
            }
        }
    }
}

/// Thực thi tiến trình hệ thống bên ngoài với kiểm soát mã thoát nghiêm ngặt.
fn run_external_command(cmd: &mut Command, context: &str) -> Result<(), CaramCtlError> {
    let prog = cmd.get_program().to_string_lossy().to_string();
    let status = cmd.status().map_err(|e| CaramCtlError::IoFailure {
        context: format!("Khởi chạy tiến trình '{}' ({})", prog, context),
        path: None,
        source: e,
    })?;

    if !status.success() {
        return Err(CaramCtlError::SubprocessFailed {
            binary: prog,
            status_code: status.code(),
            stderr_hint: format!("Bước thực thi '{}' trả về trạng thái thất bại", context),
        });
    }
    Ok(())
}

// ============================================================================
// 4. MÁY TRẠNG THÁI KIỂU TĨNH CHO PIPELINE ĐÓNG GÓI ISO (TYPESTATE BUILDER)
// ============================================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SquashfsCompression {
    Zstd,
    Xz,
}

impl SquashfsCompression {
    pub fn parse(input: &str) -> Result<Self, CaramCtlError> {
        match input.trim().to_ascii_lowercase().as_str() {
            "zstd" => Ok(Self::Zstd),
            "xz" => Ok(Self::Xz),
            other => Err(CaramCtlError::InvalidArgument {
                flag: "--compression".to_string(),
                reason: format!("Chỉ hỗ trợ 'zstd' hoặc 'xz', nhận được '{}'", other),
            }),
        }
    }
}

#[derive(Debug, Clone)]
pub struct BuildConfig {
    pub arch: String,
    pub compression: SquashfsCompression,
    pub mirror: String,
    pub work_dir: PathBuf,
    pub includes_chroot_dir: PathBuf,
    pub packages_file: PathBuf,
    pub output_iso: PathBuf,
    pub dry_run: bool,
}

pub struct StageInit;
pub struct StageRootfsBootstrapped;
pub struct StageChrootConfigured;
pub struct StageSquashfsPacked;
pub struct StageIsoFinalized;

pub struct IsoBuildPipeline<Stage> {
    config: BuildConfig,
    rootfs_dir: PathBuf,
    iso_staging_dir: PathBuf,
    _stage: PhantomData<Stage>,
}

impl IsoBuildPipeline<StageInit> {
    pub fn new(config: BuildConfig) -> Result<Self, CaramCtlError> {
        validate_safe_path(&config.work_dir)?;
        validate_safe_path(&config.includes_chroot_dir)?;
        validate_safe_path(&config.packages_file)?;
        validate_safe_path(&config.output_iso)?;

        let rootfs_dir = config.work_dir.join("rootfs");
        let iso_staging_dir = config.work_dir.join("iso_staging");

        fs::create_dir_all(&rootfs_dir).map_err(|e| CaramCtlError::IoFailure {
            context: "Khởi tạo thư mục rootfs".to_string(),
            path: Some(rootfs_dir.clone()),
            source: e,
        })?;
        fs::create_dir_all(&iso_staging_dir).map_err(|e| CaramCtlError::IoFailure {
            context: "Khởi tạo thư mục iso_staging".to_string(),
            path: Some(iso_staging_dir.clone()),
            source: e,
        })?;

        Ok(Self {
            config,
            rootfs_dir,
            iso_staging_dir,
            _stage: PhantomData,
        })
    }

    /// Bước 1: Khởi tạo cây hệ thống Debian 13 (`trixie`) tinh khiết từ thượng nguồn bằng `mmdebstrap`.
    pub fn bootstrap_debian_trixie<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<IsoBuildPipeline<StageRootfsBootstrapped>, CaramCtlError> {
        let packages = load_package_manifest(&self.config.packages_file)?;
        let pkg_csv = packages.join(",");

        writeln!(
            writer,
            "▶ [STAGE 1/4] Khởi tạo Rootfs Debian 13 (trixie) [Arch: {}, Gói: {}]...",
            self.config.arch,
            packages.len()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 1".to_string(),
            path: None,
            source: e,
        })?;

        if self.config.dry_run {
            writeln!(
                writer,
                "  [DRY-RUN] mmdebstrap --arch={} --include={} trixie {} {}",
                self.config.arch,
                pkg_csv,
                self.rootfs_dir.display(),
                self.config.mirror
            )
            .map_err(|e| CaramCtlError::IoFailure {
                context: "Ghi log dry-run mmdebstrap".to_string(),
                path: None,
                source: e,
            })?;
        } else {
            let mut cmd = Command::new("mmdebstrap");
            cmd.arg(format!("--arch={}", self.config.arch))
                .arg("--variant=minbase")
                .arg("--components=main,contrib,non-free,non-free-firmware")
                .arg(format!("--include={}", pkg_csv))
                .arg("trixie")
                .arg(&self.rootfs_dir)
                .arg(&self.config.mirror);
            run_external_command(&mut cmd, "mmdebstrap Debian 13 Trixie")?;
        }

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

impl IsoBuildPipeline<StageRootfsBootstrapped> {
    /// Bước 2: Khởi tạo cấu hình cơ sở VÀ áp lớp phủ `config/includes.chroot` (chứa thành phẩm của `caramos-ui`)
    /// ở bước CUỐI CÙNG để tuyệt đối không ghi đè các tệp của `caramos-ui`.
    pub fn configure_chroot_and_apply_overlay<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<IsoBuildPipeline<StageChrootConfigured>, CaramCtlError> {
        writeln!(
            writer,
            "▶ [STAGE 2/4] Cấu hình hệ thống Debian 13 & Đồng bộ giao diện caramos-ui từ '{}'...",
            self.config.includes_chroot_dir.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 2".to_string(),
            path: None,
            source: e,
        })?;

        let etc_dir = self.rootfs_dir.join("etc");
        let default_dir = etc_dir.join("default");
        fs::create_dir_all(&default_dir).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo thư mục /etc/default trong rootfs".to_string(),
            path: Some(default_dir.clone()),
            source: e,
        })?;

        // 2.1. Ghi các tệp nhận diện hệ điều hành cơ sở TRƯỚC khi áp overlay
        let os_release = "\
PRETTY_NAME=\"CaramOS 2.0 (Debian 13 Trixie — Rust Core Edition)\"\n\
NAME=\"CaramOS\"\n\
VERSION_ID=\"2.0\"\n\
VERSION=\"2.0 (Trixie)\"\n\
VERSION_CODENAME=trixie\n\
ID=caramos\n\
ID_LIKE=debian\n\
HOME_URL=\"https://github.com/LocShadowVN/CaramOS-testing\"\n";
        atomic_write_file(&etc_dir.join("os-release"), os_release.as_bytes())?;
        write_default_if_missing(&etc_dir.join("caramos-release"), b"CARAMOS_VERSION=2.0.0\n")?;
        write_default_if_missing(&etc_dir.join("hostname"), b"caramos-live\n")?;

        // Cấu hình /etc/default/grub mặc định (sẽ được giữ hoặc nâng cấp bởi overlay từ caramos-ui)
        let fallback_grub = "\
GRUB_DEFAULT=0\n\
GRUB_TIMEOUT=5\n\
GRUB_DISTRIBUTOR=\"CaramOS 2.0 (Trixie)\"\n\
GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash loglevel=3 mitigations=auto init_on_alloc=1\"\n\
GRUB_GFXMODE=1280x720x24,auto\n\
GRUB_GFXPAYLOAD_LINUX=keep\n\
GRUB_THEME=\"/boot/grub/themes/caramos/theme.txt\"\n";
        write_default_if_missing(&default_dir.join("grub"), fallback_grub.as_bytes())?;

        // 2.2. ÁP LỚP PHỦ `config/includes.chroot` SAU CÙNG (Overlay-Last Precedence)
        // Bảo đảm 100% các tệp do `caramos-ui` tạo ra (background.tga, theme.txt, caramos-ui binary,
        // plymouth theme, /etc/default/grub, .desktop launchers) có quyền ưu tiên tuyệt đối!
        let overlaid_count =
            copy_directory_tree_overlay(&self.config.includes_chroot_dir, &self.rootfs_dir)?;

        writeln!(
            writer,
            "  ✔ Đã đồng bộ nguyên vẹn {} tệp từ '{}' vào Rootfs (Zero Overwrite).",
            overlaid_count,
            self.config.includes_chroot_dir.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log số tệp overlay".to_string(),
            path: None,
            source: e,
        })?;

        // 2.3. Gắn kết hệ thống tệp ảo có bảo vệ RAII và cập nhật initramfs / Plymouth theme
        {
            let _mount_guard = ChrootMountGuard::mount_all(&self.rootfs_dir, self.config.dry_run)?;
            if !self.config.dry_run {
                let mut depmod_cmd = Command::new("chroot");
                depmod_cmd
                    .arg(&self.rootfs_dir)
                    .arg("/usr/sbin/update-initramfs")
                    .arg("-u")
                    .arg("-k")
                    .arg("all");
                run_external_command(&mut depmod_cmd, "chroot update-initramfs")?;
            }
        } // <- `_mount_guard` tự động tháo gỡ /dev/pts, /dev, /sys, /proc tại đây.

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

impl IsoBuildPipeline<StageChrootConfigured> {
    /// Bước 3: Đóng gói `filesystem.squashfs`, trích xuất Kernel/Initrd và đồng bộ giao diện GRUB2 CaramOS sang `iso_staging`.
    pub fn pack_squashfs_and_stage_bootloader<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<IsoBuildPipeline<StageSquashfsPacked>, CaramCtlError> {
        writeln!(
            writer,
            "▶ [STAGE 3/4] Đóng gói SquashFS & Lan truyền giao diện GRUB2 CaramOS sang ISO Staging..."
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 3".to_string(),
            path: None,
            source: e,
        })?;

        let live_dir = self.iso_staging_dir.join("live");
        let grub_dir = self.iso_staging_dir.join("boot/grub");
        let efi_boot_dir = self.iso_staging_dir.join("EFI/boot");

        for d in [&live_dir, &grub_dir, &efi_boot_dir] {
            fs::create_dir_all(d).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục trong iso_staging".to_string(),
                path: Some(d.clone()),
                source: e,
            })?;
        }

        // 3.1. LAN TRUYỀN GIAO DIỆN BOOTLOADER (`boot/grub/themes/caramos`) SANG `iso_staging`
        // Đây là bước then chốt giúp menu GRUB của Live ISO hiển thị đúng ảnh nền TGA và theme của caramos-ui!
        let rootfs_theme_dir = self.rootfs_dir.join("boot/grub/themes/caramos");
        let iso_theme_dir = grub_dir.join("themes/caramos");
        let theme_files_copied = copy_directory_tree_overlay(&rootfs_theme_dir, &iso_theme_dir)?;

        writeln!(
            writer,
            "  ✔ Đã lan truyền {} tệp giao diện Bootloader CaramOS sang '{}'.",
            theme_files_copied,
            iso_theme_dir.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log lan truyền theme GRUB".to_string(),
            path: None,
            source: e,
        })?;

        // 3.2. Sinh tệp `iso_staging/boot/grub/grub.cfg` kích hoạt đồ họa 24-bit TGA và Theme CaramOS
        let iso_grub_cfg = r#"# CaramOS 2.0 Live ISO Graphical GRUB2 Configuration
# Synchronized with caramos-ui Bootloader Theme Engine

set default=0
set timeout=10

insmod all_video
insmod gfxterm
insmod gfxmenu
insmod tga
insmod png
insmod iso9660
insmod ext2
insmod part_gpt
insmod part_msdos

set gfxmode=1280x720x24,auto
set gfxpayload=keep
terminal_output gfxterm

if [ -f /boot/grub/themes/caramos/theme.txt ]; then
    set theme=/boot/grub/themes/caramos/theme.txt
    export theme
fi

menuentry "CaramOS 2.0 Live Desktop (Debian 13 Trixie — Rust Core Edition)" {
    linux /live/vmlinuz boot=live components quiet splash loglevel=3 mitigations=auto init_on_alloc=1
    initrd /live/initrd.img
}

menuentry "CaramOS 2.0 Interactive TUI Installer (Trình Cài Đặt Hệ Điều Hành)" {
    linux /live/vmlinuz boot=live components quiet splash caramos.mode=installer mitigations=auto init_on_alloc=1
    initrd /live/initrd.img
}

menuentry "CaramOS 2.0 Safe Graphics / Fallback Mode (nomodeset)" {
    linux /live/vmlinuz boot=live components nomodeset loglevel=4
    initrd /live/initrd.img
}
"#;
        atomic_write_file(&grub_dir.join("grub.cfg"), iso_grub_cfg.as_bytes())?;

        // 3.3. Đóng gói SquashFS với thuật toán nén Zstandard hoặc XZ
        let squashfs_target = live_dir.join("filesystem.squashfs");
        if self.config.dry_run {
            atomic_write_file(&squashfs_target, b"DRY_RUN_SQUASHFS_PLACEHOLDER")?;
            atomic_write_file(&live_dir.join("vmlinuz"), b"DRY_RUN_KERNEL_PLACEHOLDER")?;
            atomic_write_file(&live_dir.join("initrd.img"), b"DRY_RUN_INITRD_PLACEHOLDER")?;
        } else {
            copy_kernel_and_initrd(&self.rootfs_dir, &live_dir)?;

            let mut mksquash = Command::new("mksquashfs");
            mksquash
                .arg(&self.rootfs_dir)
                .arg(&squashfs_target)
                .arg("-noappend")
                .arg("-b")
                .arg("1048576");

            match self.config.compression {
                SquashfsCompression::Zstd => {
                    mksquash.arg("-comp").arg("zstd").arg("-Xcompression-level").arg("19");
                }
                SquashfsCompression::Xz => {
                    mksquash
                        .arg("-comp")
                        .arg("xz")
                        .arg("-Xbcj")
                        .arg("x86")
                        .arg("-Xdict-size")
                        .arg("100%");
                }
            }
            run_external_command(&mut mksquash, "mksquashfs rootfs")?;
        }

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

impl IsoBuildPipeline<StageSquashfsPacked> {
    /// Bước 4: Đóng gói ảnh Hybrid UEFI/BIOS ISO9660 kèm bảng băm SHA-256.
    pub fn build_hybrid_iso<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<IsoBuildPipeline<StageIsoFinalized>, CaramCtlError> {
        writeln!(
            writer,
            "▶ [STAGE 4/4] Kết xuất ảnh Hybrid UEFI/BIOS ISO tại '{}'...",
            self.config.output_iso.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 4".to_string(),
            path: None,
            source: e,
        })?;

        if let Some(parent) = self.config.output_iso.parent() {
            fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục chứa tệp ISO đầu ra".to_string(),
                path: Some(parent.to_path_buf()),
                source: e,
            })?;
        }

        if self.config.dry_run {
            atomic_write_file(&self.config.output_iso, b"DRY_RUN_CARAMOS_2_0_HYBRID_ISO")?;
        } else {
            let efi_img = self.iso_staging_dir.join("EFI/boot/bootx64.efi");
            let grub_cfg = self.iso_staging_dir.join("boot/grub/grub.cfg");

            let mut grub_standalone = Command::new("grub-mkstandalone");
            grub_standalone
                .arg("--format=x86_64-efi")
                .arg(format!("--output={}", efi_img.display()))
                .arg("--locales=")
                .arg("--fonts=")
                .arg("--modules=part_gpt part_msdos iso9660 ext2 all_video gfxterm gfxmenu tga png normal boot linux loopback")
                .arg(format!("boot/grub/grub.cfg={}", grub_cfg.display()));
            run_external_command(&mut grub_standalone, "grub-mkstandalone UEFI")?;

            let mut xorriso = Command::new("xorriso");
            xorriso
                .arg("-as")
                .arg("mkisofs")
                .arg("-iso-level")
                .arg("3")
                .arg("-full-iso9660-filenames")
                .arg("-volid")
                .arg("CARAMOS_2_0")
                .arg("-output")
                .arg(&self.config.output_iso)
                .arg(&self.iso_staging_dir);
            run_external_command(&mut xorriso, "xorriso hybrid ISO")?;
        }

        let iso_hash = compute_file_sha256(&self.config.output_iso)?;
        let sha_file = self.config.output_iso.with_extension("iso.sha256");
        let sha_line = format!(
            "{}  {}\n",
            iso_hash,
            self.config
                .output_iso
                .file_name()
                .map(|n| n.to_string_lossy())
                .unwrap_or_default()
        );
        atomic_write_file(&sha_file, sha_line.as_bytes())?;

        writeln!(
            writer,
            "✔ HOÀN TẤT ĐÓNG GÓI ISO!\n  • Đường dẫn ISO : {}\n  • Mã băm SHA-256: {}",
            self.config.output_iso.display(),
            iso_hash
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log hoàn tất ISO".to_string(),
            path: None,
            source: e,
        })?;

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

/// Đọc và làm sạch danh sách gói Debian 13 từ `config/packages.txt`.
pub fn load_package_manifest(manifest_path: &Path) -> Result<Vec<String>, CaramCtlError> {
    validate_safe_path(manifest_path)?;
    if !manifest_path.exists() {
        return Ok(vec![
            String::from("linux-image-amd64"),
            String::from("live-boot"),
            String::from("systemd-sysv"),
        ]);
    }

    let file = File::open(manifest_path).map_err(|e| CaramCtlError::IoFailure {
        context: "Mở tệp danh sách gói packages.txt".to_string(),
        path: Some(manifest_path.to_path_buf()),
        source: e,
    })?;

    let reader = BufReader::new(file);
    let mut packages = Vec::new();
    for line_res in reader.lines() {
        let line = line_res.map_err(|e| CaramCtlError::IoFailure {
            context: "Đọc dòng trong packages.txt".to_string(),
            path: Some(manifest_path.to_path_buf()),
            source: e,
        })?;
        let trimmed = line.split('#').next().unwrap_or("").trim();
        if !trimmed.is_empty() {
            packages.push(trimmed.to_string());
        }
    }
    Ok(packages)
}

fn copy_kernel_and_initrd(rootfs: &Path, live_dir: &Path) -> Result<(), CaramCtlError> {
    let boot_dir = rootfs.join("boot");
    let entries = fs::read_dir(&boot_dir).map_err(|e| CaramCtlError::IoFailure {
        context: "Đọc thư mục /boot trong rootfs".to_string(),
        path: Some(boot_dir.clone()),
        source: e,
    })?;

    let mut found_kernel: Option<PathBuf> = None;
    let mut found_initrd: Option<PathBuf> = None;

    for entry_res in entries {
        let entry = entry_res.map_err(|e| CaramCtlError::IoFailure {
            context: "Duyệt tệp trong /boot".to_string(),
            path: Some(boot_dir.clone()),
            source: e,
        })?;
        let name = entry.file_name().to_string_lossy().to_string();
        if name.starts_with("vmlinuz-") {
            found_kernel = Some(entry.path());
        } else if name.starts_with("initrd.img-") {
            found_initrd = Some(entry.path());
        }
    }

    let kernel_src = found_kernel.ok_or_else(|| CaramCtlError::IoFailure {
        context: "Không tìm thấy nhân vmlinuz-* trong /boot".to_string(),
        path: Some(boot_dir.clone()),
        source: io::Error::new(io::ErrorKind::NotFound, "Missing vmlinuz"),
    })?;
    let initrd_src = found_initrd.ok_or_else(|| CaramCtlError::IoFailure {
        context: "Không tìm thấy initrd.img-* trong /boot".to_string(),
        path: Some(boot_dir),
        source: io::Error::new(io::ErrorKind::NotFound, "Missing initrd.img"),
    })?;

    fs::copy(&kernel_src, live_dir.join("vmlinuz")).map_err(|e| CaramCtlError::IoFailure {
        context: "Sao chép vmlinuz sang live/".to_string(),
        path: Some(kernel_src),
        source: e,
    })?;
    fs::copy(&initrd_src, live_dir.join("initrd.img")).map_err(|e| CaramCtlError::IoFailure {
        context: "Sao chép initrd.img sang live/".to_string(),
        path: Some(initrd_src),
        source: e,
    })?;
    Ok(())
}

// ============================================================================
// 5. DỌN DẸP DI SẢN (`prune`) — BẢO VỆ TUYỆT ĐỐI `caramos-ui` & `includes.chroot`
// ============================================================================

/// Chỉ quét và loại bỏ các tệp di sản CaramOS 1.x (`build.sh`, `scripts/`, `*.py` cũ ở gốc),
/// bảo vệ tuyệt đối `crates/caramos-ctl`, `crates/caramos-ui`, `config/includes.chroot`, `assets`, `docs`.
pub fn prune_legacy_artifacts<W: Write>(
    repo_root: &Path,
    execute: bool,
    writer: &mut W,
) -> Result<usize, CaramCtlError> {
    validate_safe_path(repo_root)?;

    let legacy_targets = [
        "build.sh",
        "install.sh",
        "update.py",
        "scripts",
        "legacy_mint",
        "ubuntu_base",
    ];

    let mut removed_count: usize = 0;

    for rel in &legacy_targets {
        let candidate = repo_root.join(rel);
        if candidate.exists() {
            if execute {
                if candidate.is_dir() {
                    fs::remove_dir_all(&candidate).map_err(|e| CaramCtlError::IoFailure {
                        context: "Xoá thư mục di sản".to_string(),
                        path: Some(candidate.clone()),
                        source: e,
                    })?;
                } else {
                    fs::remove_file(&candidate).map_err(|e| CaramCtlError::IoFailure {
                        context: "Xoá tệp di sản".to_string(),
                        path: Some(candidate.clone()),
                        source: e,
                    })?;
                }
                writeln!(writer, "  [PRUNED] Đã xoá di sản: {}", candidate.display()).map_err(
                    |e| CaramCtlError::IoFailure {
                        context: "Ghi log prune".to_string(),
                        path: None,
                        source: e,
                    },
                )?;
            } else {
                writeln!(
                    writer,
                    "  [DRY-RUN PRUNE] Sẽ xoá di sản: {}",
                    candidate.display()
                )
                .map_err(|e| CaramCtlError::IoFailure {
                    context: "Ghi log dry-run prune".to_string(),
                    path: None,
                    source: e,
                })?;
            }
            removed_count = removed_count.saturating_add(1);
        }
    }

    writeln!(
        writer,
        "✔ Hoàn tất kiểm tra di sản (Đã xử lý: {} mục; `crates/caramos-ui` & `config/includes.chroot` được bảo vệ 100%).",
        removed_count
    )
    .map_err(|e| CaramCtlError::IoFailure {
        context: "Ghi tổng kết prune".to_string(),
        path: None,
        source: e,
    })?;

    Ok(removed_count)
}

// ============================================================================
// 6. MẬT MÃ HỌC SHA-256 (FIPS 180-4) & CẬP NHẬT NGUYÊN TỬ (`hash` & `ota-apply`)
// ============================================================================

pub struct Sha256Hasher {
    state: [u32; 8],
    buffer: [u8; 64],
    buffer_len: usize,
    total_bits: u64,
}

const SHA256_K: [u32; 64] = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
];

impl Default for Sha256Hasher {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256Hasher {
    pub fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
            ],
            buffer: [0u8; 64],
            buffer_len: 0,
            total_bits: 0,
        }
    }

    pub fn update(&mut self, data: &[u8]) {
        let mut offset = 0;
        self.total_bits = self.total_bits.wrapping_add((data.len() as u64).wrapping_mul(8));

        while offset < data.len() {
            let space = 64_usize.saturating_sub(self.buffer_len);
            let take = space.min(data.len().saturating_sub(offset));
            self.buffer[self.buffer_len..self.buffer_len.saturating_add(take)]
                .copy_from_slice(&data[offset..offset.saturating_add(take)]);
            self.buffer_len = self.buffer_len.saturating_add(take);
            offset = offset.saturating_add(take);

            if self.buffer_len == 64 {
                let block = self.buffer;
                self.compress_block(&block);
                self.buffer_len = 0;
            }
        }
    }

    pub fn finalize_hex(mut self) -> String {
        let mut pad = [0u8; 128];
        pad[0] = 0x80;
        let pad_len = if self.buffer_len < 56 {
            56_usize.saturating_sub(self.buffer_len)
        } else {
            120_usize.saturating_sub(self.buffer_len)
        };
        let total_bits_be = self.total_bits.to_be_bytes();
        let saved_bits = self.total_bits;
        self.update(&pad[..pad_len]);
        self.total_bits = saved_bits;
        self.update(&total_bits_be);

        let mut out = String::with_capacity(64);
        for word in &self.state {
            for b in word.to_be_bytes() {
                let _ = fmt::Write::write_fmt(&mut out, format_args!("{:02x}", b));
            }
        }
        out
    }

    fn compress_block(&mut self, block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for (i, chunk) in block.chunks_exact(4).enumerate() {
            if let Ok(arr) = <[u8; 4]>::try_from(chunk) {
                w[i] = u32::from_be_bytes(arr);
            }
        }
        for i in 16..64 {
            let s0 = w[i - 15].rotate_right(7) ^ w[i - 15].rotate_right(18) ^ (w[i - 15] >> 3);
            let s1 = w[i - 2].rotate_right(17) ^ w[i - 2].rotate_right(19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16]
                .wrapping_add(s0)
                .wrapping_add(w[i - 7])
                .wrapping_add(s1);
        }

        let mut a = self.state[0];
        let mut b = self.state[1];
        let mut c = self.state[2];
        let mut d = self.state[3];
        let mut e = self.state[4];
        let mut f = self.state[5];
        let mut g = self.state[6];
        let mut h = self.state[7];

        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let temp1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(SHA256_K[i])
                .wrapping_add(w[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let temp2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        self.state[0] = self.state[0].wrapping_add(a);
        self.state[1] = self.state[1].wrapping_add(b);
        self.state[2] = self.state[2].wrapping_add(c);
        self.state[3] = self.state[3].wrapping_add(d);
        self.state[4] = self.state[4].wrapping_add(e);
        self.state[5] = self.state[5].wrapping_add(f);
        self.state[6] = self.state[6].wrapping_add(g);
        self.state[7] = self.state[7].wrapping_add(h);
    }
}

pub fn compute_file_sha256(path: &Path) -> Result<String, CaramCtlError> {
    validate_safe_path(path)?;
    let mut file = File::open(path).map_err(|e| CaramCtlError::IoFailure {
        context: "Mở tệp để băm SHA-256".to_string(),
        path: Some(path.to_path_buf()),
        source: e,
    })?;
    let mut hasher = Sha256Hasher::new();
    let mut buf = [0u8; 8192];
    loop {
        let n = file.read(&mut buf).map_err(|e| CaramCtlError::IoFailure {
            context: "Đọc luồng dữ liệu SHA-256".to_string(),
            path: Some(path.to_path_buf()),
            source: e,
        })?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    Ok(hasher.finalize_hex())
}

pub fn apply_atomic_ota(
    root_dir: &Path,
    relative_target: &Path,
    payload_path: &Path,
    expected_sha256: &str,
    new_version: &str,
) -> Result<(), CaramCtlError> {
    validate_safe_path(root_dir)?;
    validate_safe_path(relative_target)?;
    validate_safe_path(payload_path)?;

    if relative_target.is_absolute() {
        return Err(CaramCtlError::UnsafePath {
            path: relative_target.to_path_buf(),
            reason: "Đường dẫn --target phải là đường dẫn tương đối bên trong --root",
        });
    }

    let expected_norm = expected_sha256.trim().to_ascii_lowercase();
    let actual_payload_hash = compute_file_sha256(payload_path)?;
    if actual_payload_hash != expected_norm {
        return Err(CaramCtlError::DigestMismatch {
            path: payload_path.to_path_buf(),
            expected: expected_norm,
            actual: actual_payload_hash,
        });
    }

    let target_full = root_dir.join(relative_target);
    let backup_path = target_full.with_extension("caramos-ctl.bak");
    let had_original = target_full.exists();

    if had_original {
        fs::copy(&target_full, &backup_path).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo bản sao lưu nguyên tử trước khi OTA".to_string(),
            path: Some(backup_path.clone()),
            source: e,
        })?;
    }

    let payload_bytes = fs::read(payload_path).map_err(|e| CaramCtlError::IoFailure {
        context: "Đọc dữ liệu gói Payload OTA".to_string(),
        path: Some(payload_path.to_path_buf()),
        source: e,
    })?;

    if let Err(write_err) = atomic_write_file(&target_full, &payload_bytes) {
        if had_original && backup_path.exists() {
            if let Err(rb_err) = fs::rename(&backup_path, &target_full) {
                return Err(CaramCtlError::RollbackFailed {
                    target: target_full,
                    original_error: write_err.to_string(),
                    rollback_error: rb_err,
                });
            }
        }
        return Err(write_err);
    }

    let release_file = root_dir.join("etc/caramos-release");
    let _ = atomic_write_file(
        &release_file,
        format!("CARAMOS_VERSION={}\n", new_version.trim()).as_bytes(),
    );

    if backup_path.exists() {
        let _ = fs::remove_file(&backup_path);
    }

    Ok(())
}

// ============================================================================
// 7. ĐIỀU PHỐI DÒNG LỆNH (CLI ENTRYPOINT)
// ============================================================================

pub fn run_cli(args: &[String]) -> Result<(), CaramCtlError> {
    let mut stdout = io::stdout().lock();
    let subcommand = match args.get(1).map(String::as_str) {
        Some(cmd) => cmd,
        None | Some("--help") | Some("-h") | Some("help") => {
            writeln!(
                stdout,
                "CaramOS 2.0 Core System Controller (caramos-ctl)\n\
                 Sử dụng:\n  \
                   caramos-ctl prune --repo-root <DIR> [--execute]\n  \
                   caramos-ctl build [--arch amd64] [--compression zstd|xz] [--work-dir <DIR>] [--output-iso <PATH>] [--dry-run]\n  \
                   caramos-ctl hash <FILE_PATH>\n  \
                   caramos-ctl ota-apply --root <DIR> --target <REL_PATH> --payload <FILE> --sha256 <HEX> --version <VER>"
            )
            .map_err(|e| CaramCtlError::IoFailure {
                context: "In trợ giúp CLI".to_string(),
                path: None,
                source: e,
            })?;
            return Ok(());
        }
    };

    match subcommand {
        "prune" => {
            let mut repo_root = PathBuf::from(".");
            let mut execute = false;
            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--repo-root" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--repo-root".to_string(),
                            reason: "Thiếu đường dẫn thư mục gốc".to_string(),
                        })?;
                        repo_root = PathBuf::from(val);
                    }
                    "--execute" => execute = true,
                    other => {
                        return Err(CaramCtlError::InvalidArgument {
                            flag: other.to_string(),
                            reason: "Tham số không hợp lệ cho lệnh prune".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }
            prune_legacy_artifacts(&repo_root, execute, &mut stdout)?;
            Ok(())
        }
        "build" => {
            let mut config = BuildConfig {
                arch: String::from("amd64"),
                compression: SquashfsCompression::Zstd,
                mirror: String::from("https://deb.debian.org/debian"),
                work_dir: PathBuf::from("./build"),
                includes_chroot_dir: PathBuf::from("./config/includes.chroot"),
                packages_file: PathBuf::from("./config/packages.txt"),
                output_iso: PathBuf::from("./build/caramos-2.0-trixie-amd64.iso"),
                dry_run: false,
            };

            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--arch" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--arch".to_string(),
                            reason: "Thiếu kiến trúc CPU".to_string(),
                        })?;
                        config.arch.clone_from(val);
                    }
                    "--compression" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--compression".to_string(),
                            reason: "Thiếu thuật toán nén (zstd|xz)".to_string(),
                        })?;
                        config.compression = SquashfsCompression::parse(val)?;
                    }
                    "--mirror" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--mirror".to_string(),
                            reason: "Thiếu URL Debian mirror".to_string(),
                        })?;
                        config.mirror.clone_from(val);
                    }
                    "--work-dir" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--work-dir".to_string(),
                            reason: "Thiếu thư mục làm việc".to_string(),
                        })?;
                        config.work_dir = PathBuf::from(val);
                        config.output_iso = config.work_dir.join("caramos-2.0-trixie-amd64.iso");
                    }
                    "--includes-chroot" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--includes-chroot".to_string(),
                            reason: "Thiếu đường dẫn includes.chroot".to_string(),
                        })?;
                        config.includes_chroot_dir = PathBuf::from(val);
                    }
                    "--output-iso" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--output-iso".to_string(),
                            reason: "Thiếu đường dẫn tệp ISO đầu ra".to_string(),
                        })?;
                        config.output_iso = PathBuf::from(val);
                    }
                    "--dry-run" => config.dry_run = true,
                    other => {
                        return Err(CaramCtlError::InvalidArgument {
                            flag: other.to_string(),
                            reason: "Tham số không hợp lệ cho lệnh build".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }

            let pipeline = IsoBuildPipeline::new(config)?;
            let pipeline = pipeline.bootstrap_debian_trixie(&mut stdout)?;
            let pipeline = pipeline.configure_chroot_and_apply_overlay(&mut stdout)?;
            let pipeline = pipeline.pack_squashfs_and_stage_bootloader(&mut stdout)?;
            let _finalized = pipeline.build_hybrid_iso(&mut stdout)?;
            Ok(())
        }
        "hash" => {
            let file_arg = args.get(2).ok_or_else(|| CaramCtlError::InvalidArgument {
                flag: "<FILE_PATH>".to_string(),
                reason: "Thiếu đường dẫn tệp cần tính mã băm SHA-256".to_string(),
            })?;
            let path = PathBuf::from(file_arg);
            let digest = compute_file_sha256(&path)?;
            writeln!(stdout, "{}  {}", digest, path.display()).map_err(|e| {
                CaramCtlError::IoFailure {
                    context: "In mã băm SHA-256".to_string(),
                    path: None,
                    source: e,
                }
            })?;
            Ok(())
        }
        "ota-apply" => {
            let mut root_dir: Option<PathBuf> = None;
            let mut target_rel: Option<PathBuf> = None;
            let mut payload: Option<PathBuf> = None;
            let mut sha256: Option<String> = None;
            let mut version = String::from("2.0.1");

            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--root" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--root".to_string(),
                            reason: "Thiếu đường dẫn root".to_string(),
                        })?;
                        root_dir = Some(PathBuf::from(val));
                    }
                    "--target" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--target".to_string(),
                            reason: "Thiếu đường dẫn tương đối target".to_string(),
                        })?;
                        target_rel = Some(PathBuf::from(val));
                    }
                    "--payload" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--payload".to_string(),
                            reason: "Thiếu đường dẫn payload".to_string(),
                        })?;
                        payload = Some(PathBuf::from(val));
                    }
                    "--sha256" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--sha256".to_string(),
                            reason: "Thiếu mã băm SHA-256".to_string(),
                        })?;
                        sha256 = Some(val.clone());
                    }
                    "--version" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramCtlError::InvalidArgument {
                            flag: "--version".to_string(),
                            reason: "Thiếu phiên bản".to_string(),
                        })?;
                        version.clone_from(val);
                    }
                    other => {
                        return Err(CaramCtlError::InvalidArgument {
                            flag: other.to_string(),
                            reason: "Tham số không hợp lệ cho ota-apply".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }

            let r = root_dir.ok_or_else(|| CaramCtlError::InvalidArgument {
                flag: "--root".to_string(),
                reason: "Bắt buộc".to_string(),
            })?;
            let t = target_rel.ok_or_else(|| CaramCtlError::InvalidArgument {
                flag: "--target".to_string(),
                reason: "Bắt buộc".to_string(),
            })?;
            let p = payload.ok_or_else(|| CaramCtlError::InvalidArgument {
                flag: "--payload".to_string(),
                reason: "Bắt buộc".to_string(),
            })?;
            let s = sha256.ok_or_else(|| CaramCtlError::InvalidArgument {
                flag: "--sha256".to_string(),
                reason: "Bắt buộc".to_string(),
            })?;

            apply_atomic_ota(&r, &t, &p, &s, &version)?;
            writeln!(
                stdout,
                "✔ Đã áp dụng bản cập nhật OTA nguyên tử lên phiên bản {}.",
                version
            )
            .map_err(|e| CaramCtlError::IoFailure {
                context: "In kết quả OTA".to_string(),
                path: None,
                source: e,
            })?;
            Ok(())
        }
        unknown => Err(CaramCtlError::InvalidArgument {
            flag: unknown.to_string(),
            reason: "Lệnh không tồn tại (hỗ trợ: prune, build, hash, ota-apply)".to_string(),
        }),
    }
}

fn main() -> std::process::ExitCode {
    let args: Vec<String> = env::args().collect();
    match run_cli(&args) {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(e) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "✖ {}", e);
            std::process::ExitCode::from(1)
        }
    }
}

// ============================================================================
// 8. KIỂM CHỨNG ĐƠN VỊ (BAO GỒM KIỂM THỬ CHỐNG GHI ĐÈ `caramos-ui`)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn make_temp_dir(label: &str) -> Result<PathBuf, CaramCtlError> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = env::temp_dir().join(format!("caramos_ctl_test_{}_{}", label, nanos));
        fs::create_dir_all(&dir).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo thư mục test".to_string(),
            path: Some(dir.clone()),
            source: e,
        })?;
        Ok(dir)
    }

    /// Kiểm thử hồi quy quan trọng: Chứng minh 100% rằng các tệp do `caramos-ui` sinh ra trong
    /// `config/includes.chroot` KHÔNG BAO GIỜ bị `caramos-ctl` ghi đè, và được lan truyền
    /// đầy đủ sang cả `rootfs` lẫn `iso_staging/boot/grub/themes/caramos`.
    #[test]
    fn test_overlay_and_bootloader_theme_not_overwritten() -> Result<(), CaramCtlError> {
        let temp_base = make_temp_dir("no_overwrite")?;
        let includes_dir = temp_base.join("config/includes.chroot");
        let work_dir = temp_base.join("build");
        let pkg_file = temp_base.join("config/packages.txt");

        // Giả lập các tệp do `caramos-ui bootloader` và `Makefile` tạo trong `config/includes.chroot`
        let custom_grub_default = includes_dir.join("etc/default/grub");
        let custom_grub_content = b"GRUB_THEME=\"/boot/grub/themes/caramos/theme.txt\"\nCUSTOM_UI_MARKER=1\n";
        atomic_write_file(&custom_grub_default, custom_grub_content)?;

        let theme_tga = includes_dir.join("boot/grub/themes/caramos/background.tga");
        let tga_dummy_bytes = b"TRUEVISION_TGA_CARAMOS_UI_WALLPAPER";
        atomic_write_file(&theme_tga, tga_dummy_bytes)?;

        let theme_txt = includes_dir.join("boot/grub/themes/caramos/theme.txt");
        atomic_write_file(&theme_txt, b"title-text: \"CaramOS 2.0 Custom UI\"")?;

        let ui_bin = includes_dir.join("usr/local/bin/caramos-ui");
        atomic_write_file(&ui_bin, b"ELF_CARAMOS_UI_BINARY")?;

        atomic_write_file(&pkg_file, b"linux-image-amd64\nlive-boot\n")?;

        let cfg = BuildConfig {
            arch: String::from("amd64"),
            compression: SquashfsCompression::Zstd,
            mirror: String::from("https://deb.debian.org/debian"),
            work_dir: work_dir.clone(),
            includes_chroot_dir: includes_dir,
            packages_file: pkg_file,
            output_iso: work_dir.join("caramos-test.iso"),
            dry_run: true,
        };

        let mut log = Vec::new();
        let p = IsoBuildPipeline::new(cfg)?;
        let p = p.bootstrap_debian_trixie(&mut log)?;
        let p = p.configure_chroot_and_apply_overlay(&mut log)?;
        let p = p.pack_squashfs_and_stage_bootloader(&mut log)?;
        let _p = p.build_hybrid_iso(&mut log)?;

        // 1. Xác minh `/etc/default/grub` của `caramos-ui` trong `rootfs` được giữ nguyên vẹn, KHÔNG bị ghi đè!
        let rootfs_grub = fs::read_to_string(work_dir.join("rootfs/etc/default/grub")).map_err(|e| {
            CaramCtlError::IoFailure {
                context: "Đọc rootfs/etc/default/grub".to_string(),
                path: None,
                source: e,
            }
        })?;
        assert!(rootfs_grub.contains("CUSTOM_UI_MARKER=1"));

        // 2. Xác minh tệp thực thi `caramos-ui` nằm nguyên vẹn trong `rootfs/usr/local/bin/caramos-ui`
        let rootfs_ui_bin = fs::read(work_dir.join("rootfs/usr/local/bin/caramos-ui")).map_err(|e| {
            CaramCtlError::IoFailure {
                context: "Đọc rootfs/usr/local/bin/caramos-ui".to_string(),
                path: None,
                source: e,
            }
        })?;
        assert_eq!(rootfs_ui_bin, b"ELF_CARAMOS_UI_BINARY");

        // 3. Xác minh `background.tga` và `theme.txt` đã được lan truyền sang `iso_staging/boot/grub/themes/caramos/`
        let staged_tga = fs::read(work_dir.join("iso_staging/boot/grub/themes/caramos/background.tga"))
            .map_err(|e| CaramCtlError::IoFailure {
                context: "Đọc staged background.tga".to_string(),
                path: None,
                source: e,
            })?;
        assert_eq!(staged_tga, tga_dummy_bytes);

        let staged_grub_cfg = fs::read_to_string(work_dir.join("iso_staging/boot/grub/grub.cfg"))
            .map_err(|e| CaramCtlError::IoFailure {
                context: "Đọc staged grub.cfg".to_string(),
                path: None,
                source: e,
            })?;
        assert!(staged_grub_cfg.contains("set theme=/boot/grub/themes/caramos/theme.txt"));
        assert!(staged_grub_cfg.contains("insmod tga"));

        let _ = fs::remove_dir_all(&temp_base);
        Ok(())
    }
}
