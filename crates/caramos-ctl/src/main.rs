#![forbid(unsafe_code)]
#![deny(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::todo,
    clippy::unimplemented,
    clippy::indexing_slicing,
    unreachable_patterns,
    unused_must_use
)]

//! # CaramOS 2.0 Core Build & System Orchestrator (`caramos-ctl`)
//!
//! Trình điều phối đóng gói Live ISO Debian 13 (Trixie), quản lý vòng đời gắn kết Chroot (RAII),
//! giải cứu Applet & dọn dẹp di sản (`prune`), băm mật mã học SHA-256 (`hash`) và cập nhật nguyên tử (`ota-apply`).

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
// 2. PHÒNG THỦ ĐƯỜNG DẪN & SAO CHÉP CÂY THƯ MỤC ĐỆ QUY (OVERLAY-LAST)
// ============================================================================

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

pub fn write_default_if_missing(target: &Path, default_content: &[u8]) -> Result<bool, CaramCtlError> {
    validate_safe_path(target)?;
    if target.exists() {
        return Ok(false);
    }
    atomic_write_file(target, default_content)?;
    Ok(true)
}

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
            let sub_count: usize = copy_directory_tree_overlay(&src_path, &dst_path)?;
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

        let mounts: [(&str, &[&str]); 4] = [
            ("proc", &["-t", "proc", "proc"]),
            ("sys", &["-t", "sysfs", "sys"]),
            ("dev", &["--bind", "/dev"]),
            ("dev/pts", &["--bind", "/dev/pts"]),
        ];

        for (rel_dir, args) in &mounts {
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

pub const DEFAULT_ISO_FILENAME: &str = "CaramOS-2.0.0-debian-trixie-amd64.iso";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SquashfsCompression {
    Zstd,
    Xz,
}

impl SquashfsCompression {
    pub fn parse(input: &str) -> Result<Self, CaramCtlError> {
        match input.trim().to_ascii_lowercase().as_str() {
            "zstd" | "fast-zstd" => Ok(Self::Zstd),
            "xz" | "release-xz" => Ok(Self::Xz),
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

        let os_release = "\
PRETTY_NAME=\"CaramOS 2.0 (Debian 13 Trixie — Rust Core Edition)\"\n\
NAME=\"CaramOS\"\n\
VERSION_ID=\"2.0.0\"\n\
VERSION=\"2.0.0 (Trixie)\"\n\
VERSION_CODENAME=trixie\n\
ID=caramos\n\
ID_LIKE=debian\n\
HOME_URL=\"https://github.com/LocShadowVN/CaramOS-testing\"\n";
        atomic_write_file(&etc_dir.join("os-release"), os_release.as_bytes())?;
        write_default_if_missing(&etc_dir.join("caramos-release"), b"CARAMOS_VERSION=2.0.0\n")?;
        write_default_if_missing(&etc_dir.join("hostname"), b"caramos-live\n")?;

        let fallback_grub = "\
GRUB_DEFAULT=0\n\
GRUB_TIMEOUT=5\n\
GRUB_DISTRIBUTOR=\"CaramOS 2.0 (Trixie)\"\n\
GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash loglevel=3 mitigations=auto init_on_alloc=1\"\n\
GRUB_GFXMODE=1280x720x24,auto\n\
GRUB_GFXPAYLOAD_LINUX=keep\n\
GRUB_THEME=\"/boot/grub/themes/caramos/theme.txt\"\n";
        write_default_if_missing(&default_dir.join("grub"), fallback_grub.as_bytes())?;

        // Áp lớp phủ `config/includes.chroot` sau cùng (Overlay-Last Precedence)
        let overlaid_count: usize =
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
        }

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

impl IsoBuildPipeline<StageChrootConfigured> {
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

        let rootfs_theme_dir = self.rootfs_dir.join("boot/grub/themes/caramos");
        let iso_theme_dir = grub_dir.join("themes/caramos");
        let theme_files_copied: usize = copy_directory_tree_overlay(&rootfs_theme_dir, &iso_theme_dir)?;

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
            atomic_write_file(&self.config.output_iso, b"DRY_RUN_CARAMOS_2_0_0_HYBRID_ISO")?;
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
// 5. GIẢI CỨU APPLET & DỌN DẸP DI SẢN (`prune`)
// ============================================================================

pub fn prune_legacy_artifacts<W: Write>(
    repo_root: &Path,
    execute: bool,
    writer: &mut W,
) -> Result<usize, CaramCtlError> {
    validate_safe_path(repo_root)?;

    let legacy_applets = repo_root.join("packages/caramos-ota/usr/share/cinnamon/applets");
    let target_applets = repo_root.join("config/includes.chroot/usr/share/cinnamon/applets");
    if legacy_applets.exists() && execute {
        let salvaged: usize = copy_directory_tree_overlay(&legacy_applets, &target_applets)?;
        writeln!(
            writer,
            "  [SALVAGED] Đã giải cứu {} tệp Cinnamon Applet sang '{}'.",
            salvaged,
            target_applets.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log giải cứu applet".to_string(),
            path: None,
            source: e,
        })?;
    }

    let legacy_targets = [
        "build.sh",
        "install.sh",
        "install-caramos-ota.sh",
        "update.py",
        "scripts",
        "packages/caramos-ota",
        "config/hooks/live",
        "debian",
        "Dockerfile",
        "docker-compose.yml",
        "CaramOS Project Finalization.md",
        ".github/workflows/build.yml",
        ".github/workflows/release.yml",
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
        "✔ Hoàn tất kiểm tra di sản (Đã xử lý: {} mục; `crates/caramos-ctl`, `crates/caramos-ui` & `config/includes.chroot` được bảo vệ 100%).",
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
// 6. MẬT MÃ HỌC SHA-256 (FIPS 180-4) ĐỊNH KIỂU TƯỜNG MINH (`usize` / `u32` / `u64`)
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
        let added_bits: u64 = (data.len() as u64).wrapping_mul(8);
        self.total_bits = self.total_bits.wrapping_add(added_bits);

        for &byte in data {
            if let Some(slot) = self.buffer.get_mut(self.buffer_len) {
                *slot = byte;
            }
            self.buffer_len = self.buffer_len.saturating_add(1);

            if self.buffer_len == 64 {
                let block = self.buffer;
                self.compress_block(&block);
                self.buffer_len = 0;
            }
        }
    }

    pub fn finalize_hex(mut self) -> String {
        let saved_bits: u64 = self.total_bits;
        self.update(&[0x80]);
        while self.buffer_len != 56 {
            self.update(&[0x00]);
        }
        let total_bits_be: [u8; 8] = saved_bits.to_be_bytes();
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
            if let (Ok(arr), Some(slot)) = (<[u8; 4]>::try_from(chunk), w.get_mut(i)) {
                *slot = u32::from_be_bytes(arr);
            }
        }

        for i in 16_usize..64_usize {
            let idx_15: usize = i.saturating_sub(15);
            let idx_2: usize = i.saturating_sub(2);
            let idx_16: usize = i.saturating_sub(16);
            let idx_7: usize = i.saturating_sub(7);

            let w_15: u32 = w.get(idx_15).copied().unwrap_or(0);
            let w_2: u32 = w.get(idx_2).copied().unwrap_or(0);
            let w_16: u32 = w.get(idx_16).copied().unwrap_or(0);
            let w_7: u32 = w.get(idx_7).copied().unwrap_or(0);

            let s0: u32 = w_15.rotate_right(7) ^ w_15.rotate_right(18) ^ (w_15 >> 3);
            let s1: u32 = w_2.rotate_right(17) ^ w_2.rotate_right(19) ^ (w_2 >> 10);
            let val: u32 = w_16.wrapping_add(s0).wrapping_add(w_7).wrapping_add(s1);
            if let Some(slot) = w.get_mut(i) {
                *slot = val;
            }
        }

        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = self.state;

        for i in 0_usize..64_usize {
            let k_i: u32 = SHA256_K.get(i).copied().unwrap_or(0);
            let w_i: u32 = w.get(i).copied().unwrap_or(0);

            let s1: u32 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch: u32 = (e & f) ^ ((!e) & g);
            let temp1: u32 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(k_i)
                .wrapping_add(w_i);
            let s0: u32 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj: u32 = (a & b) ^ (a & c) ^ (b & c);
            let temp2: u32 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(temp1);
            d = c;
            c = b;
            b = a;
            a = temp1.wrapping_add(temp2);
        }

        let [s0, s1, s2, s3, s4, s5, s6, s7] = self.state;
        self.state = [
            s0.wrapping_add(a),
            s1.wrapping_add(b),
            s2.wrapping_add(c),
            s3.wrapping_add(d),
            s4.wrapping_add(e),
            s5.wrapping_add(f),
            s6.wrapping_add(g),
            s7.wrapping_add(h),
        ];
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
        let n: usize = file.read(&mut buf).map_err(|e| CaramCtlError::IoFailure {
            context: "Đọc luồng dữ liệu SHA-256".to_string(),
            path: Some(path.to_path_buf()),
            source: e,
        })?;
        if n == 0 {
            break;
        }
        if let Some(chunk) = buf.get(..n) {
            hasher.update(chunk);
        }
    }
    Ok(hasher.finalize_hex())
}

/// Cấu trúc đóng gói yêu cầu cập nhật OTA nguyên tử.
pub struct OtaApplyRequest<'a> {
    pub root_dir: &'a Path,
    pub relative_target: &'a Path,
    pub payload_path: &'a Path,
    pub expected_sha256: &'a str,
    pub new_version: &'a str,
}

pub fn apply_atomic_ota(req: &OtaApplyRequest<'_>) -> Result<(), CaramCtlError> {
    validate_safe_path(req.root_dir)?;
    validate_safe_path(req.relative_target)?;
    validate_safe_path(req.payload_path)?;

    if req.relative_target.is_absolute() {
        return Err(CaramCtlError::UnsafePath {
            path: req.relative_target.to_path_buf(),
            reason: "Đường dẫn --target phải là đường dẫn tương đối bên trong --root",
        });
    }

    let expected_norm = req.expected_sha256.trim().to_ascii_lowercase();
    let actual_payload_hash = compute_file_sha256(req.payload_path)?;
    if actual_payload_hash != expected_norm {
        return Err(CaramCtlError::DigestMismatch {
            path: req.payload_path.to_path_buf(),
            expected: expected_norm,
            actual: actual_payload_hash,
        });
    }

    let target_full = req.root_dir.join(req.relative_target);
    let backup_path = target_full.with_extension("caramos-ctl.bak");
    let had_original = target_full.exists();

    if had_original {
        fs::copy(&target_full, &backup_path).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo bản sao lưu nguyên tử trước khi OTA".to_string(),
            path: Some(backup_path.clone()),
            source: e,
        })?;
    }

    let payload_bytes = fs::read(req.payload_path).map_err(|e| CaramCtlError::IoFailure {
        context: "Đọc dữ liệu gói Payload OTA".to_string(),
        path: Some(req.payload_path.to_path_buf()),
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

    let release_file = req.root_dir.join("etc/caramos-release");
    let _ = atomic_write_file(
        &release_file,
        format!("CARAMOS_VERSION={}\n", req.new_version.trim()).as_bytes(),
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
        None | Some("--help") | Some("-h") | Some("help") => {
            writeln!(
                stdout,
                "CaramOS 2.0 Core System Controller (caramos-ctl)\n\
                 Sử dụng:\n  \
                   caramos-ctl prune --repo-root <DIR> [--execute]\n  \
                   caramos-ctl build [--arch amd64] [--compression zstd|xz] [--release] [--work-dir <DIR>] [--output-iso <PATH>] [--dry-run]\n  \
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
        Some(cmd) => cmd,
    };

    match subcommand {
        "prune" => {
            let mut repo_root = PathBuf::from(".");
            let mut execute = false;
            let mut idx: usize = 2;
            while let Some(arg) = args.get(idx).map(String::as_str) {
                match arg {
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
            let default_work = PathBuf::from("./build");
            let mut config = BuildConfig {
                arch: String::from("amd64"),
                compression: SquashfsCompression::Zstd,
                mirror: String::from("https://deb.debian.org/debian"),
                output_iso: default_work.join(DEFAULT_ISO_FILENAME),
                work_dir: default_work,
                includes_chroot_dir: PathBuf::from("./config/includes.chroot"),
                packages_file: PathBuf::from("./config/packages.txt"),
                dry_run: false,
            };
            let mut custom_output_iso = false;

            let mut idx: usize = 2;
            while let Some(arg) = args.get(idx).map(String::as_str) {
                match arg {
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
                    "--release" => {
                        config.compression = SquashfsCompression::Xz;
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
                        if !custom_output_iso {
                            config.output_iso = config.work_dir.join(DEFAULT_ISO_FILENAME);
                        }
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
                        custom_output_iso = true;
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

            let mut idx: usize = 2;
            while let Some(arg) = args.get(idx).map(String::as_str) {
                match arg {
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

            let req = OtaApplyRequest {
                root_dir: &r,
                relative_target: &t,
                payload_path: &p,
                expected_sha256: &s,
                new_version: &version,
            };
            apply_atomic_ota(&req)?;
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
// 8. KIỂM CHỨNG ĐƠN VỊ (BAO GỒM KIỂM THỬ CHỐNG GHI ĐÈ & SHA-256 FIPS 180-4)
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

    #[test]
    fn test_sha256_fips_180_4_vectors() {
        let mut h_empty = Sha256Hasher::new();
        h_empty.update(b"");
        assert_eq!(
            h_empty.finalize_hex(),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );

        let mut h_abc = Sha256Hasher::new();
        h_abc.update(b"abc");
        assert_eq!(
            h_abc.finalize_hex(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn test_overlay_and_bootloader_theme_not_overwritten() -> Result<(), CaramCtlError> {
        let temp_base = make_temp_dir("no_overwrite")?;
        let includes_dir = temp_base.join("config/includes.chroot");
        let work_dir = temp_base.join("build");
        let pkg_file = temp_base.join("config/packages.txt");

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
            output_iso: work_dir.join(DEFAULT_ISO_FILENAME),
            work_dir: work_dir.clone(),
            includes_chroot_dir: includes_dir,
            packages_file: pkg_file,
            dry_run: true,
        };

        let mut log = Vec::new();
        let p = IsoBuildPipeline::new(cfg)?;
        let p = p.bootstrap_debian_trixie(&mut log)?;
        let p = p.configure_chroot_and_apply_overlay(&mut log)?;
        let p = p.pack_squashfs_and_stage_bootloader(&mut log)?;
        let _p = p.build_hybrid_iso(&mut log)?;

        let rootfs_grub = fs::read_to_string(work_dir.join("rootfs/etc/default/grub")).map_err(|e| {
            CaramCtlError::IoFailure {
                context: "Đọc rootfs/etc/default/grub".to_string(),
                path: None,
                source: e,
            }
        })?;
        assert!(rootfs_grub.contains("CUSTOM_UI_MARKER=1"));

        let rootfs_ui_bin = fs::read(work_dir.join("rootfs/usr/local/bin/caramos-ui")).map_err(|e| {
            CaramCtlError::IoFailure {
                context: "Đọc rootfs/usr/local/bin/caramos-ui".to_string(),
                path: None,
                source: e,
            }
        })?;
        assert_eq!(rootfs_ui_bin, b"ELF_CARAMOS_UI_BINARY");

        let staged_tga = fs::read(work_dir.join("iso_staging/boot/grub/themes/caramos/background.tga"))
            .map_err(|e| CaramCtlError::IoFailure {
                context: "Đọc staged background.tga".to_string(),
                path: None,
                source: e,
            })?;
        assert_eq!(staged_tga, tga_dummy_bytes);

        assert!(work_dir.join(DEFAULT_ISO_FILENAME).exists());

        let _ = fs::remove_dir_all(&temp_base);
        Ok(())
    }
}
