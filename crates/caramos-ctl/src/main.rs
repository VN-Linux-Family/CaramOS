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
//! Trình điều phối đóng gói Live ISO Hybrid UEFI + Legacy BIOS nền Debian 13 (Trixie):
//! - Kiểm định công cụ host & khóa OpenPGP Debian (`debian-archive-keyring`) trước khi chạy `mmdebstrap`.
//! - Gắn kết Chroot an toàn chuẩn RAII (`ChrootMountGuard` + `ChrootPolicyRcGuard`).
//! - Đồng bộ lớp phủ bảo toàn 100% symlink & phân quyền (`walkdir`), không làm bẩn cây Git bằng binary.
//! - Biên dịch GSettings/dconf/Plymouth/initramfs trong chroot để bảo toàn bản sắc UI CaramOS.
//! - Băm SHA-256 tăng tốc phần cứng (`sha2`) & cập nhật OTA truyền luồng `O(1)` RAM (`tempfile`).

use clap::{Parser, Subcommand, ValueEnum};
use sha2::{Digest, Sha256};
use std::env;
use std::ffi::OsString;
use std::fs::{self, File};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::marker::PhantomData;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use tempfile::NamedTempFile;
use thiserror::Error;
use walkdir::WalkDir;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

// ============================================================================
// 1. KIẾN TRÚC LỖI CÓ CẤU TRÚC (STRUCTURED DOMAIN ERRORS)
// ============================================================================

fn fmt_opt_path(path: &Option<PathBuf>) -> String {
    match path {
        Some(p) => format!(" tại '{}'", p.display()),
        None => String::new(),
    }
}

#[derive(Debug, Error)]
pub enum CaramCtlError {
    #[error("[CTL_ARG_ERR] Tham số '{flag}' không hợp lệ: {reason}")]
    InvalidArgument { flag: String, reason: String },

    #[error("[CTL_SECURITY_ERR] Đường dẫn '{}' bị từ chối: {reason}", path.display())]
    UnsafePath { path: PathBuf, reason: &'static str },

    #[error("[CTL_PREREQ_ERR] Thiếu điều kiện môi trường build: {detail}")]
    MissingPrerequisite { detail: String },

    #[error("[CTL_IO_ERR] Lỗi khi '{context}'{}: {source}", fmt_opt_path(path))]
    IoFailure {
        context: String,
        path: Option<PathBuf>,
        #[source]
        source: io::Error,
    },

    #[error("[CTL_EXEC_ERR] Tiến trình '{binary}' thất bại (mã thoát: {status_code:?}): {stderr_hint}")]
    SubprocessFailed {
        binary: String,
        status_code: Option<i32>,
        stderr_hint: String,
    },

    #[error("[CTL_CRYPTO_ERR] Mã băm SHA-256 không khớp tại '{}': kỳ vọng '{expected}', thực tế '{actual}'", path.display())]
    DigestMismatch {
        path: PathBuf,
        expected: String,
        actual: String,
    },

    #[error("[CTL_CRITICAL_OTA] Lỗi gốc ({original_error}) VÀ lỗi khôi phục tại '{}': {rollback_error}", target.display())]
    RollbackFailed {
        target: PathBuf,
        original_error: String,
        #[source]
        rollback_error: io::Error,
    },
}

// ============================================================================
// 2. PHÒNG THỦ ĐƯỜNG DẪN, GHI NGUYÊN TỬ (`tempfile`) & ĐỒNG BỘ OVERLAY BẢO TOÀN SYMLINK
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

fn append_filename_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut os = OsString::from(path.as_os_str());
    os.push(suffix);
    PathBuf::from(os)
}

#[cfg(unix)]
fn set_unix_mode(path: &Path, mode: u32) -> Result<(), CaramCtlError> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).map_err(|e| {
        CaramCtlError::IoFailure {
            context: format!("Thiết lập quyền POSIX {:o}", mode),
            path: Some(path.to_path_buf()),
            source: e,
        }
    })
}

#[cfg(not(unix))]
fn set_unix_mode(_path: &Path, _mode: u32) -> Result<(), CaramCtlError> {
    Ok(())
}

pub fn atomic_write_file_with_mode(
    target: &Path,
    content: &[u8],
    mode: u32,
) -> Result<(), CaramCtlError> {
    validate_safe_path(target)?;
    let parent = target
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));

    fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
        context: "Tạo thư mục cha cho tệp đích".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;

    let mut tmp = NamedTempFile::new_in(parent).map_err(|e| CaramCtlError::IoFailure {
        context: "Khởi tạo tệp tạm nguyên tử".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;
    let tmp_path = tmp.path().to_path_buf();

    tmp.write_all(content).map_err(|e| CaramCtlError::IoFailure {
        context: "Ghi nội dung vào tệp tạm".to_string(),
        path: Some(tmp_path.clone()),
        source: e,
    })?;

    tmp.as_file()
        .sync_all()
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Đồng bộ fsync tệp tạm".to_string(),
            path: Some(tmp_path),
            source: e,
        })?;

    set_unix_mode(tmp.path(), mode)?;

    tmp.persist(target).map_err(|e| CaramCtlError::IoFailure {
        context: "Hoán đổi nguyên tử tệp đích".to_string(),
        path: Some(target.to_path_buf()),
        source: e.error,
    })?;

    Ok(())
}

pub fn atomic_write_file(target: &Path, content: &[u8]) -> Result<(), CaramCtlError> {
    atomic_write_file_with_mode(target, content, 0o644)
}

pub fn write_default_if_missing(
    target: &Path,
    default_content: &[u8],
) -> Result<bool, CaramCtlError> {
    validate_safe_path(target)?;
    if target.symlink_metadata().is_ok() {
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
        context: "Tạo thư mục đích overlay".to_string(),
        path: Some(dst_dir.to_path_buf()),
        source: e,
    })?;

    let mut copied_entries: usize = 0;

    for entry_res in WalkDir::new(src_dir).follow_links(false) {
        let entry = entry_res.map_err(|e| CaramCtlError::IoFailure {
            context: "Duyệt cây thư mục overlay".to_string(),
            path: e.path().map(Path::to_path_buf),
            source: e
                .into_io_error()
                .unwrap_or_else(|| io::Error::other("walkdir error")),
        })?;

        if entry.depth() == 0 {
            continue;
        }

        let src_path = entry.path();
        let rel_path = src_path
            .strip_prefix(src_dir)
            .map_err(|_| CaramCtlError::UnsafePath {
                path: src_path.to_path_buf(),
                reason: "Không thể tính đường dẫn tương đối trong overlay",
            })?;
        validate_safe_path(rel_path)?;

        let dst_path = dst_dir.join(rel_path);
        let ft = entry.file_type();

        if ft.is_dir() {
            fs::create_dir_all(&dst_path).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục con overlay".to_string(),
                path: Some(dst_path.clone()),
                source: e,
            })?;
            if let Ok(meta) = fs::metadata(src_path) {
                let _ = fs::set_permissions(&dst_path, meta.permissions());
            }
        } else if ft.is_symlink() {
            let link_target = fs::read_link(src_path).map_err(|e| CaramCtlError::IoFailure {
                context: "Đọc liên kết mềm (symlink) overlay".to_string(),
                path: Some(src_path.to_path_buf()),
                source: e,
            })?;

            if let Some(parent) = dst_path.parent() {
                fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
                    context: "Tạo thư mục cha cho symlink overlay".to_string(),
                    path: Some(parent.to_path_buf()),
                    source: e,
                })?;
            }

            if let Ok(existing_meta) = dst_path.symlink_metadata() {
                if existing_meta.file_type().is_dir() {
                    fs::remove_dir_all(&dst_path).map_err(|e| CaramCtlError::IoFailure {
                        context: "Gỡ thư mục cũ trước khi tạo symlink".to_string(),
                        path: Some(dst_path.clone()),
                        source: e,
                    })?;
                } else {
                    fs::remove_file(&dst_path).map_err(|e| CaramCtlError::IoFailure {
                        context: "Gỡ tệp/symlink cũ trước khi tạo symlink".to_string(),
                        path: Some(dst_path.clone()),
                        source: e,
                    })?;
                }
            }

            #[cfg(unix)]
            std::os::unix::fs::symlink(&link_target, &dst_path).map_err(|e| {
                CaramCtlError::IoFailure {
                    context: "Tạo symlink trong rootfs".to_string(),
                    path: Some(dst_path.clone()),
                    source: e,
                }
            })?;

            copied_entries = copied_entries.saturating_add(1);
        } else if ft.is_file() {
            if let Some(parent) = dst_path.parent() {
                fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
                    context: "Tạo thư mục cha cho tệp overlay".to_string(),
                    path: Some(parent.to_path_buf()),
                    source: e,
                })?;
            }

            if dst_path
                .symlink_metadata()
                .map(|m| m.file_type().is_symlink())
                .unwrap_or(false)
            {
                fs::remove_file(&dst_path).map_err(|e| CaramCtlError::IoFailure {
                    context: "Gỡ symlink cũ trước khi sao chép tệp".to_string(),
                    path: Some(dst_path.clone()),
                    source: e,
                })?;
            }

            fs::copy(src_path, &dst_path).map_err(|e| CaramCtlError::IoFailure {
                context: "Sao chép tệp overlay".to_string(),
                path: Some(dst_path.clone()),
                source: e,
            })?;

            if let Ok(meta) = fs::metadata(src_path) {
                let _ = fs::set_permissions(&dst_path, meta.permissions());
            }
            copied_entries = copied_entries.saturating_add(1);
        }
    }

    Ok(copied_entries)
}

fn stage_binary_into_rootfs(bin_src: &Path, rootfs: &Path) -> Result<PathBuf, CaramCtlError> {
    validate_safe_path(bin_src)?;
    if !bin_src.is_file() {
        return Err(CaramCtlError::IoFailure {
            context: "Tệp thực thi --stage-bin không tồn tại".to_string(),
            path: Some(bin_src.to_path_buf()),
            source: io::Error::new(io::ErrorKind::NotFound, "Missing stage binary"),
        });
    }

    let file_name = bin_src
        .file_name()
        .ok_or_else(|| CaramCtlError::UnsafePath {
            path: bin_src.to_path_buf(),
            reason: "Đường dẫn --stage-bin không có tên tệp hợp lệ",
        })?;

    let dst_dir = rootfs.join("usr/local/bin");
    fs::create_dir_all(&dst_dir).map_err(|e| CaramCtlError::IoFailure {
        context: "Tạo /usr/local/bin trong rootfs".to_string(),
        path: Some(dst_dir.clone()),
        source: e,
    })?;

    let dst_path = dst_dir.join(file_name);
    fs::copy(bin_src, &dst_path).map_err(|e| CaramCtlError::IoFailure {
        context: "Nhúng tệp thực thi vào rootfs".to_string(),
        path: Some(dst_path.clone()),
        source: e,
    })?;
    set_unix_mode(&dst_path, 0o755)?;
    Ok(dst_path)
}

// ============================================================================
// 3. QUẢN LÝ TÀI NGUYÊN CHROOT RAII (MOUNT GUARD + POLICY-RC.D GUARD)
// ============================================================================

pub struct ChrootMountGuard {
    mounted_targets: Vec<PathBuf>,
    dry_run: bool,
}

impl ChrootMountGuard {
    pub fn mount_all(rootfs: &Path, dry_run: bool) -> Result<Self, CaramCtlError> {
        validate_safe_path(rootfs)?;
        let mut guard = Self {
            mounted_targets: Vec::with_capacity(5),
            dry_run,
        };

        let mounts: [(&str, &[&str]); 5] = [
            ("proc", &["-t", "proc", "proc"]),
            ("sys", &["-t", "sysfs", "sys"]),
            ("dev", &["--bind", "/dev"]),
            ("dev/pts", &["--bind", "/dev/pts"]),
            ("run", &["-t", "tmpfs", "tmpfs"]),
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
                let normal_ok = Command::new("umount")
                    .arg(&target)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false);

                if !normal_ok {
                    let _ = Command::new("umount")
                        .arg("-lf")
                        .arg(target)
                        .stdout(Stdio::null())
                        .stderr(Stdio::null())
                        .status();
                }
            }
        }
    }
}

/// Chặn các daemon tự khởi chạy bên trong chroot khi cài đặt/cập nhật, tự dọn sạch khi Drop.
struct ChrootPolicyRcGuard {
    path: Option<PathBuf>,
}

impl ChrootPolicyRcGuard {
    fn install(rootfs: &Path, dry_run: bool) -> Result<Self, CaramCtlError> {
        if dry_run {
            return Ok(Self { path: None });
        }
        let policy_path = rootfs.join("usr/sbin/policy-rc.d");
        if policy_path.exists() {
            return Ok(Self { path: None });
        }
        atomic_write_file_with_mode(&policy_path, b"#!/bin/sh\nexit 101\n", 0o755)?;
        Ok(Self {
            path: Some(policy_path),
        })
    }
}

impl Drop for ChrootPolicyRcGuard {
    fn drop(&mut self) {
        if let Some(ref p) = self.path {
            let _ = fs::remove_file(p);
        }
    }
}

fn find_in_path(binary: &str) -> Option<PathBuf> {
    let path_var = env::var_os("PATH")?;
    for dir in env::split_paths(&path_var) {
        let candidate = dir.join(binary);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn resolve_debian_keyring() -> Option<PathBuf> {
    let candidates = [
        "/usr/share/keyrings/debian-archive-keyring.gpg",
        "/usr/share/keyrings/debian-archive-keyring.pgp",
    ];
    for path_str in candidates {
        let p = PathBuf::from(path_str);
        if p.is_file() {
            return Some(p);
        }
    }
    None
}

fn check_host_prerequisites(
    arch: &str,
    custom_keyring: Option<&Path>,
) -> Result<PathBuf, CaramCtlError> {
    let uid_out = Command::new("id")
        .arg("-u")
        .output()
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Kiểm tra quyền root bằng id -u".to_string(),
            path: None,
            source: e,
        })?;
    let uid_str = String::from_utf8_lossy(&uid_out.stdout);
    if uid_str.trim() != "0" {
        return Err(CaramCtlError::MissingPrerequisite {
            detail: "Cần quyền root (chạy qua `sudo make build`) để chạy mmdebstrap và mount chroot."
                .to_string(),
        });
    }

    let required_bins = [
        "mmdebstrap",
        "mksquashfs",
        "grub-mkrescue",
        "xorriso",
        "mformat",
        "chroot",
        "mount",
        "umount",
    ];

    let mut missing = Vec::new();
    for bin in required_bins {
        if find_in_path(bin).is_none() {
            missing.push(bin);
        }
    }

    if !missing.is_empty() {
        return Err(CaramCtlError::MissingPrerequisite {
            detail: format!(
                "Thiếu công cụ host: [{}]. Cài đặt nhanh trên Debian/Ubuntu:\n  sudo apt update && sudo apt install -y mmdebstrap debian-archive-keyring squashfs-tools grub-common grub-pc-bin grub-efi-amd64-bin mtools xorriso",
                missing.join(", ")
            ),
        });
    }

    let keyring = match custom_keyring {
        Some(path) => {
            if !path.is_file() {
                return Err(CaramCtlError::MissingPrerequisite {
                    detail: format!(
                        "Tệp keyring chỉ định '{}' không tồn tại.",
                        path.display()
                    ),
                });
            }
            path.to_path_buf()
        }
        None => resolve_debian_keyring().ok_or_else(|| CaramCtlError::MissingPrerequisite {
            detail: "Thiếu khóa ký kho gói Debian (/usr/share/keyrings/debian-archive-keyring.gpg hoặc .pgp). Cài đặt:\n  sudo apt-get update && sudo apt-get install -y debian-archive-keyring".to_string(),
        })?,
    };

    if arch == "amd64" {
        let has_efi = Path::new("/usr/lib/grub/x86_64-efi").is_dir();
        let has_bios = Path::new("/usr/lib/grub/i386-pc").is_dir();
        if !has_efi || !has_bios {
            return Err(CaramCtlError::MissingPrerequisite {
                detail: format!(
                    "Thiếu mô-đun GRUB để tạo Hybrid UEFI+BIOS ISO (x86_64-efi: {}, i386-pc: {}). Cài đặt:\n  sudo apt install -y grub-pc-bin grub-efi-amd64-bin mtools xorriso",
                    has_efi, has_bios
                ),
            });
        }
    }

    Ok(keyring)
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

fn run_chroot_if_present(
    rootfs: &Path,
    chroot_bin: &str,
    args: &[&str],
    context: &str,
) -> Result<bool, CaramCtlError> {
    let rel_bin = chroot_bin.trim_start_matches('/');
    if !rootfs.join(rel_bin).exists() {
        return Ok(false);
    }
    let mut cmd = Command::new("chroot");
    cmd.env("DEBIAN_FRONTEND", "noninteractive")
        .env("LC_ALL", "C.UTF-8")
        .arg(rootfs)
        .arg(chroot_bin);
    for a in args {
        cmd.arg(a);
    }
    run_external_command(&mut cmd, context)?;
    Ok(true)
}

// ============================================================================
// 4. PIPELINE ĐÓNG GÓI LIVE ISO HYBRID UEFI/BIOS (TYPESTATE BUILDER)
// ============================================================================

pub const DEFAULT_ISO_FILENAME: &str = "CaramOS-2.0.0-debian-trixie-amd64.iso";

#[derive(Debug, Clone, Copy, PartialEq, Eq, ValueEnum)]
pub enum SquashfsCompression {
    #[value(alias = "fast-zstd")]
    Zstd,
    #[value(alias = "release-xz")]
    Xz,
}

#[derive(Debug, Clone)]
pub struct BuildConfig {
    pub arch: String,
    pub compression: SquashfsCompression,
    pub mirror: String,
    pub keyring: Option<PathBuf>,
    pub work_dir: PathBuf,
    pub includes_chroot_dir: PathBuf,
    pub extra_overlays: Vec<PathBuf>,
    pub stage_bins: Vec<PathBuf>,
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
        if let Some(ref kr) = config.keyring {
            validate_safe_path(kr)?;
        }
        for overlay in &config.extra_overlays {
            validate_safe_path(overlay)?;
        }
        for bin in &config.stage_bins {
            validate_safe_path(bin)?;
        }

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
        let packages = load_package_manifest(&self.config.packages_file, self.config.dry_run)?;
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
                "  [DRY-RUN] mmdebstrap --arch={} --keyring=<debian-archive-keyring> --include={} trixie {} {}",
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
            let keyring =
                check_host_prerequisites(&self.config.arch, self.config.keyring.as_deref())?;

            let mut cmd = Command::new("mmdebstrap");
            cmd.arg(format!("--arch={}", self.config.arch))
                .arg("--variant=minbase")
                .arg("--components=main,contrib,non-free,non-free-firmware")
                .arg(format!("--keyring={}", keyring.display()))
                .arg("--aptopt=Acquire::Retries \"3\"")
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
            "▶ [STAGE 2/4] Cấu hình Debian 13 Live & Áp lớp phủ UI CaramOS từ '{}'...",
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
PRETTY_NAME=\"CaramOS 2.0 (Debian 13 Trixie)\"\n\
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

        let default_hosts = "\
127.0.0.1\tlocalhost\n\
127.0.1.1\tcaramos-live\n\
::1\t\tlocalhost ip6-localhost ip6-loopback\n\
ff02::1\t\tip6-allnodes\n\
ff02::2\t\tip6-allrouters\n";
        write_default_if_missing(&etc_dir.join("hosts"), default_hosts.as_bytes())?;

        let fallback_grub = "\
GRUB_DEFAULT=0\n\
GRUB_TIMEOUT=5\n\
GRUB_DISTRIBUTOR=\"CaramOS\"\n\
GRUB_CMDLINE_LINUX_DEFAULT=\"quiet splash loglevel=3 mitigations=auto init_on_alloc=1\"\n\
GRUB_GFXMODE=1280x720x24,auto\n\
GRUB_GFXPAYLOAD_LINUX=keep\n\
GRUB_THEME=\"/boot/grub/themes/caramos/theme.txt\"\n";
        write_default_if_missing(&default_dir.join("grub"), fallback_grub.as_bytes())?;

        let primary_count =
            copy_directory_tree_overlay(&self.config.includes_chroot_dir, &self.rootfs_dir)?;
        writeln!(
            writer,
            "  ✔ Đã đồng bộ {} mục (tệp + symlink) từ '{}' vào Rootfs.",
            primary_count,
            self.config.includes_chroot_dir.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log overlay chính".to_string(),
            path: None,
            source: e,
        })?;

        for extra in &self.config.extra_overlays {
            if extra.exists() {
                let extra_count = copy_directory_tree_overlay(extra, &self.rootfs_dir)?;
                writeln!(
                    writer,
                    "  ✔ Đã đồng bộ {} mục từ extra-overlay '{}'.",
                    extra_count,
                    extra.display()
                )
                .map_err(|e| CaramCtlError::IoFailure {
                    context: "Ghi log extra overlay".to_string(),
                    path: None,
                    source: e,
                })?;
            }
        }

        for bin in &self.config.stage_bins {
            let installed = stage_binary_into_rootfs(bin, &self.rootfs_dir)?;
            writeln!(
                writer,
                "  ✔ Đã cài đặt binary '{}' -> '{}'.",
                bin.display(),
                installed.display()
            )
            .map_err(|e| CaramCtlError::IoFailure {
                context: "Ghi log stage-bin".to_string(),
                path: None,
                source: e,
            })?;
        }

        {
            let _mount_guard = ChrootMountGuard::mount_all(&self.rootfs_dir, self.config.dry_run)?;
            let _policy_guard =
                ChrootPolicyRcGuard::install(&self.rootfs_dir, self.config.dry_run)?;

            if !self.config.dry_run {
                if self.rootfs_dir.join("usr/share/glib-2.0/schemas").is_dir() {
                    let _ = run_chroot_if_present(
                        &self.rootfs_dir,
                        "/usr/bin/glib-compile-schemas",
                        &["/usr/share/glib-2.0/schemas"],
                        "chroot glib-compile-schemas",
                    )?;
                }

                if self.rootfs_dir.join("etc/dconf/db").is_dir() {
                    let _ = run_chroot_if_present(
                        &self.rootfs_dir,
                        "/usr/bin/dconf",
                        &["update"],
                        "chroot dconf update",
                    )?;
                }

                if self
                    .rootfs_dir
                    .join("usr/share/plymouth/themes/caramos/caramos.plymouth")
                    .is_file()
                {
                    let _ = run_chroot_if_present(
                        &self.rootfs_dir,
                        "/usr/sbin/plymouth-set-default-theme",
                        &["caramos"],
                        "chroot plymouth-set-default-theme",
                    )?;
                }

                let ran_initramfs = run_chroot_if_present(
                    &self.rootfs_dir,
                    "/usr/sbin/update-initramfs",
                    &["-u", "-k", "all"],
                    "chroot update-initramfs",
                )?;
                if !ran_initramfs {
                    writeln!(
                        writer,
                        "  ⚠ Cảnh báo: Không tìm thấy /usr/sbin/update-initramfs trong rootfs."
                    )
                    .map_err(|e| CaramCtlError::IoFailure {
                        context: "Ghi cảnh báo update-initramfs".to_string(),
                        path: None,
                        source: e,
                    })?;
                }
            }
        }

        if !self.config.dry_run {
            cleanup_rootfs_before_squashfs(&self.rootfs_dir)?;
        }

        Ok(IsoBuildPipeline {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _stage: PhantomData,
        })
    }
}

fn cleanup_rootfs_before_squashfs(rootfs: &Path) -> Result<(), CaramCtlError> {
    let apt_archives = rootfs.join("var/cache/apt/archives");
    if let Ok(entries) = fs::read_dir(&apt_archives) {
        for entry in entries.flatten() {
            let p = entry.path();
            if p.is_file() && p.extension().and_then(|e| e.to_str()) == Some("deb") {
                let _ = fs::remove_file(p);
            }
        }
    }

    let machine_id = rootfs.join("etc/machine-id");
    if machine_id.exists() {
        atomic_write_file(&machine_id, b"")?;
    }
    let dbus_machine_id = rootfs.join("var/lib/dbus/machine-id");
    if dbus_machine_id.symlink_metadata().is_ok() {
        let _ = fs::remove_file(dbus_machine_id);
    }

    Ok(())
}

impl IsoBuildPipeline<StageChrootConfigured> {
    pub fn pack_squashfs_and_stage_bootloader<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<IsoBuildPipeline<StageSquashfsPacked>, CaramCtlError> {
        writeln!(
            writer,
            "▶ [STAGE 3/4] Đóng gói SquashFS & Chuẩn bị GRUB2 Hybrid Staging..."
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 3".to_string(),
            path: None,
            source: e,
        })?;

        let live_dir = self.iso_staging_dir.join("live");
        let grub_dir = self.iso_staging_dir.join("boot/grub");
        let grub_fonts_dir = grub_dir.join("fonts");
        let disk_dir = self.iso_staging_dir.join(".disk");

        for d in [&live_dir, &grub_dir, &grub_fonts_dir, &disk_dir] {
            fs::create_dir_all(d).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục trong iso_staging".to_string(),
                path: Some(d.clone()),
                source: e,
            })?;
        }

        atomic_write_file(
            &disk_dir.join("info"),
            format!("CaramOS 2.0 (Debian 13 Trixie — {})\n", self.config.arch).as_bytes(),
        )?;
        atomic_write_file(&disk_dir.join("caramos-iso"), b"CARAMOS_2_0\n")?;

        let rootfs_theme_dir = self.rootfs_dir.join("boot/grub/themes/caramos");
        let iso_theme_dir = grub_dir.join("themes/caramos");
        let theme_files_copied = copy_directory_tree_overlay(&rootfs_theme_dir, &iso_theme_dir)?;

        let font_candidates = [
            self.rootfs_dir.join("usr/share/grub/unicode.pf2"),
            PathBuf::from("/usr/share/grub/unicode.pf2"),
        ];
        for font_src in &font_candidates {
            if font_src.is_file() {
                let _ = fs::copy(font_src, grub_fonts_dir.join("unicode.pf2"));
                break;
            }
        }

        writeln!(
            writer,
            "  ✔ Đã lan truyền {} mục giao diện Bootloader CaramOS sang '{}'.",
            theme_files_copied,
            iso_theme_dir.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log lan truyền theme GRUB".to_string(),
            path: None,
            source: e,
        })?;

        let iso_grub_cfg = r#"# CaramOS 2.0 Live ISO Graphical GRUB2 Configuration (UEFI & Legacy BIOS)

set default=0
set timeout=10

search --no-floppy --set=root --file /.disk/caramos-iso

insmod all_video
insmod gfxterm
insmod gfxmenu
insmod font
insmod png
insmod jpeg
insmod tga
insmod iso9660
insmod ext2
insmod part_gpt
insmod part_msdos

if [ -f /boot/grub/fonts/unicode.pf2 ]; then
    loadfont /boot/grub/fonts/unicode.pf2
else
    loadfont unicode
fi

set gfxmode=1280x720x24,auto
set gfxpayload=keep
terminal_output gfxterm

if [ -f /boot/grub/themes/caramos/theme.txt ]; then
    set theme=/boot/grub/themes/caramos/theme.txt
    export theme
fi

menuentry "CaramOS 2.0 Live Desktop (Debian 13 Trixie)" {
    linux /live/vmlinuz boot=live components quiet splash locales=vi_VN.UTF-8,en_US.UTF-8 username=caram hostname=caramos-live loglevel=3 mitigations=auto init_on_alloc=1
    initrd /live/initrd.img
}

menuentry "CaramOS 2.0 Interactive Installer (Trình Cài Đặt)" {
    linux /live/vmlinuz boot=live components quiet splash locales=vi_VN.UTF-8,en_US.UTF-8 username=caram hostname=caramos-live caramos.mode=installer mitigations=auto init_on_alloc=1
    initrd /live/initrd.img
}

menuentry "CaramOS 2.0 Safe Graphics / Fallback Mode (nomodeset)" {
    linux /live/vmlinuz boot=live components nomodeset locales=vi_VN.UTF-8,en_US.UTF-8 username=caram hostname=caramos-live loglevel=4
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
                .arg(squashfs_target)
                .arg("-noappend")
                .arg("-b")
                .arg("1048576");

            match self.config.compression {
                SquashfsCompression::Zstd => {
                    mksquash
                        .arg("-comp")
                        .arg("zstd")
                        .arg("-Xcompression-level")
                        .arg("19");
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

            mksquash
                .arg("-wildcards")
                .arg("-e")
                .arg("proc/*")
                .arg("sys/*")
                .arg("dev/*")
                .arg("run/*")
                .arg("tmp/*")
                .arg("var/cache/apt/archives/*.deb");

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
            "▶ [STAGE 4/4] Kết xuất ảnh Hybrid UEFI + Legacy BIOS ISO tại '{}'...",
            self.config.output_iso.display()
        )
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Ghi log Stage 4".to_string(),
            path: None,
            source: e,
        })?;

        if let Some(parent) = self
            .config
            .output_iso
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
        {
            fs::create_dir_all(parent).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục chứa tệp ISO đầu ra".to_string(),
                path: Some(parent.to_path_buf()),
                source: e,
            })?;
        }

        if self.config.dry_run {
            atomic_write_file(&self.config.output_iso, b"DRY_RUN_CARAMOS_2_0_0_HYBRID_ISO")?;
        } else {
            if self.config.output_iso.exists() {
                fs::remove_file(&self.config.output_iso).map_err(|e| CaramCtlError::IoFailure {
                    context: "Xóa ảnh ISO cũ trước khi xuất bản mới".to_string(),
                    path: Some(self.config.output_iso.clone()),
                    source: e,
                })?;
            }

            let mut mkrescue = Command::new("grub-mkrescue");
            mkrescue
                .arg("-o")
                .arg(&self.config.output_iso)
                .arg(&self.iso_staging_dir)
                .arg("--")
                .arg("-volid")
                .arg("CARAMOS_2_0");
            run_external_command(&mut mkrescue, "grub-mkrescue Hybrid UEFI/BIOS ISO")?;
        }

        let iso_hash = compute_file_sha256(&self.config.output_iso)?;
        let sha_file = append_filename_suffix(&self.config.output_iso, ".sha256");
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
            "✔ HOÀN TẤT ĐÓNG GÓI ISO HYBRID UEFI/BIOS!\n  • Đường dẫn ISO : {}\n  • Tệp SHA-256   : {}\n  • Mã băm SHA-256: {}",
            self.config.output_iso.display(),
            sha_file.display(),
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

pub fn load_package_manifest(
    manifest_path: &Path,
    allow_fallback: bool,
) -> Result<Vec<String>, CaramCtlError> {
    validate_safe_path(manifest_path)?;
    if !manifest_path.exists() {
        if allow_fallback {
            return Ok(vec![
                String::from("linux-image-amd64"),
                String::from("live-boot"),
                String::from("live-config"),
                String::from("live-config-systemd"),
                String::from("systemd-sysv"),
            ]);
        }
        return Err(CaramCtlError::IoFailure {
            context: "Không tìm thấy tệp danh sách gói packages.txt".to_string(),
            path: Some(manifest_path.to_path_buf()),
            source: io::Error::new(io::ErrorKind::NotFound, "Missing packages.txt"),
        });
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
            for token in trimmed.split_whitespace() {
                packages.push(token.to_string());
            }
        }
    }

    if packages.is_empty() {
        return Err(CaramCtlError::InvalidArgument {
            flag: "--packages-file".to_string(),
            reason: "Tệp danh sách gói rỗng".to_string(),
        });
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

    let mut kernels: Vec<(String, PathBuf)> = Vec::new();
    let mut initrds: Vec<(String, PathBuf)> = Vec::new();

    for entry_res in entries {
        let entry = entry_res.map_err(|e| CaramCtlError::IoFailure {
            context: "Duyệt tệp trong /boot".to_string(),
            path: Some(boot_dir.clone()),
            source: e,
        })?;
        let name = entry.file_name().to_string_lossy().to_string();
        let path = entry.path();
        if let Some(ver) = name.strip_prefix("vmlinuz-") {
            kernels.push((ver.to_string(), path));
        } else if let Some(ver) = name.strip_prefix("initrd.img-") {
            initrds.push((ver.to_string(), path));
        }
    }

    kernels.sort_by(|a, b| a.0.cmp(&b.0));
    initrds.sort_by(|a, b| a.0.cmp(&b.0));

    let (kernel_ver, kernel_src) = kernels.pop().ok_or_else(|| CaramCtlError::IoFailure {
        context: "Không tìm thấy nhân vmlinuz-* trong /boot".to_string(),
        path: Some(boot_dir.clone()),
        source: io::Error::new(io::ErrorKind::NotFound, "Missing vmlinuz"),
    })?;

    let initrd_src = initrds
        .iter()
        .find(|(ver, _)| ver == &kernel_ver)
        .map(|(_, p)| p.clone())
        .or_else(|| initrds.pop().map(|(_, p)| p))
        .ok_or_else(|| CaramCtlError::IoFailure {
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
        let salvaged = copy_directory_tree_overlay(&legacy_applets, &target_applets)?;
        writeln!(
            writer,
            "  [SALVAGED] Đã giải cứu {} mục Cinnamon Applet sang '{}'.",
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
        "✔ Hoàn tất kiểm tra di sản (Đã xử lý: {} mục; `crates/`, `assets/` & `config/includes.chroot` được bảo vệ 100%).",
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
// 6. SHA-256 TĂNG TỐC PHẦN CỨNG (`sha2`) & OTA NGUYÊN TỬ TRUYỀN LUỒNG `O(1)` RAM
// ============================================================================

pub fn compute_file_sha256(path: &Path) -> Result<String, CaramCtlError> {
    validate_safe_path(path)?;
    let mut file = File::open(path).map_err(|e| CaramCtlError::IoFailure {
        context: "Mở tệp để băm SHA-256".to_string(),
        path: Some(path.to_path_buf()),
        source: e,
    })?;

    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65_536];
    loop {
        let n = file.read(&mut buf).map_err(|e| CaramCtlError::IoFailure {
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
    Ok(hex::encode(hasher.finalize()))
}

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
    if expected_norm.len() != 64 || !expected_norm.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(CaramCtlError::InvalidArgument {
            flag: "--sha256".to_string(),
            reason: "Chuỗi SHA-256 phải gồm đúng 64 ký tự hex".to_string(),
        });
    }

    let target_full = req.root_dir.join(req.relative_target);
    let target_parent = target_full
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(req.root_dir);
    fs::create_dir_all(target_parent).map_err(|e| CaramCtlError::IoFailure {
        context: "Tạo thư mục cha cho tệp đích OTA".to_string(),
        path: Some(target_parent.to_path_buf()),
        source: e,
    })?;

    let mut src_file = File::open(req.payload_path).map_err(|e| CaramCtlError::IoFailure {
        context: "Mở tệp payload OTA".to_string(),
        path: Some(req.payload_path.to_path_buf()),
        source: e,
    })?;
    let mut staging = NamedTempFile::new_in(target_parent).map_err(|e| CaramCtlError::IoFailure {
        context: "Tạo tệp vùng đệm OTA".to_string(),
        path: Some(target_parent.to_path_buf()),
        source: e,
    })?;
    let staging_path = staging.path().to_path_buf();

    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65_536];
    loop {
        let n = src_file.read(&mut buf).map_err(|e| CaramCtlError::IoFailure {
            context: "Đọc luồng payload OTA".to_string(),
            path: Some(req.payload_path.to_path_buf()),
            source: e,
        })?;
        if n == 0 {
            break;
        }
        if let Some(chunk) = buf.get(..n) {
            hasher.update(chunk);
            staging.write_all(chunk).map_err(|e| CaramCtlError::IoFailure {
                context: "Ghi luồng vào tệp đệm OTA".to_string(),
                path: Some(staging_path.clone()),
                source: e,
            })?;
        }
    }

    let actual_payload_hash = hex::encode(hasher.finalize());
    if actual_payload_hash != expected_norm {
        return Err(CaramCtlError::DigestMismatch {
            path: req.payload_path.to_path_buf(),
            expected: expected_norm,
            actual: actual_payload_hash,
        });
    }

    staging
        .as_file()
        .sync_all()
        .map_err(|e| CaramCtlError::IoFailure {
            context: "Đồng bộ fsync vùng đệm OTA".to_string(),
            path: Some(staging_path),
            source: e,
        })?;

    if let Ok(orig_meta) = fs::metadata(&target_full) {
        let _ = fs::set_permissions(staging.path(), orig_meta.permissions());
    } else {
        set_unix_mode(staging.path(), 0o644)?;
    }

    let backup_path = append_filename_suffix(&target_full, ".caramos-ctl.bak");
    let had_original = target_full.exists();
    if had_original {
        fs::copy(&target_full, &backup_path).map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo bản sao lưu nguyên tử trước khi OTA".to_string(),
            path: Some(backup_path.clone()),
            source: e,
        })?;
    }

    if let Err(persist_err) = staging.persist(&target_full) {
        let io_err = persist_err.error;
        if had_original && backup_path.exists() {
            if let Err(rb_err) = fs::rename(&backup_path, &target_full) {
                return Err(CaramCtlError::RollbackFailed {
                    target: target_full,
                    original_error: io_err.to_string(),
                    rollback_error: rb_err,
                });
            }
        }
        return Err(CaramCtlError::IoFailure {
            context: "Hoán đổi nguyên tử tệp đích OTA".to_string(),
            path: Some(target_full),
            source: io_err,
        });
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
// 7. GIAO DIỆN DÒNG LỆNH CHUẨN HÓA (`clap`)
// ============================================================================

#[derive(Debug, Parser)]
#[command(
    name = "caramos-ctl",
    version,
    about = "CaramOS 2.0 Core System Controller & Hybrid Debian 13 (Trixie) ISO Builder"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Giải cứu Cinnamon Applet & dọn dẹp script di sản
    Prune {
        #[arg(long, default_value = ".")]
        repo_root: PathBuf,
        #[arg(long)]
        execute: bool,
    },
    /// Đóng gói Live ISO Hybrid UEFI/BIOS nền Debian 13 (Trixie)
    Build {
        #[arg(long, default_value = "amd64")]
        arch: String,
        #[arg(long, value_enum, default_value_t = SquashfsCompression::Zstd)]
        compression: SquashfsCompression,
        #[arg(long)]
        release: bool,
        #[arg(long, default_value = "https://deb.debian.org/debian")]
        mirror: String,
        #[arg(long)]
        keyring: Option<PathBuf>,
        #[arg(long, default_value = "./build")]
        work_dir: PathBuf,
        #[arg(long, default_value = "./config/includes.chroot")]
        includes_chroot: PathBuf,
        #[arg(long = "extra-overlay")]
        extra_overlays: Vec<PathBuf>,
        #[arg(long = "stage-bin")]
        stage_bins: Vec<PathBuf>,
        #[arg(long, default_value = "./config/packages.txt")]
        packages_file: PathBuf,
        #[arg(long)]
        output_iso: Option<PathBuf>,
        #[arg(long)]
        dry_run: bool,
    },
    /// Tính mã băm SHA-256 (FIPS 180-4) của tệp
    Hash { file_path: PathBuf },
    /// Áp dụng cập nhật OTA nguyên tử kèm xác thực SHA-256 & Rollback
    OtaApply {
        #[arg(long)]
        root: PathBuf,
        #[arg(long)]
        target: PathBuf,
        #[arg(long)]
        payload: PathBuf,
        #[arg(long)]
        sha256: String,
        #[arg(long, default_value = "2.0.1")]
        version: String,
    },
}

pub fn run_cli(args: &[String]) -> Result<(), CaramCtlError> {
    let mut stdout = io::stdout().lock();

    let cli = match Cli::try_parse_from(args) {
        Ok(parsed) => parsed,
        Err(err) => {
            if matches!(
                err.kind(),
                clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion
            ) {
                write!(stdout, "{}", err).map_err(|e| CaramCtlError::IoFailure {
                    context: "In trợ giúp CLI".to_string(),
                    path: None,
                    source: e,
                })?;
                return Ok(());
            }
            return Err(CaramCtlError::InvalidArgument {
                flag: "cli".to_string(),
                reason: err.to_string(),
            });
        }
    };

    match cli.command {
        Commands::Prune { repo_root, execute } => {
            prune_legacy_artifacts(&repo_root, execute, &mut stdout)?;
            Ok(())
        }
        Commands::Build {
            arch,
            compression,
            release,
            mirror,
            keyring,
            work_dir,
            includes_chroot,
            extra_overlays,
            stage_bins,
            packages_file,
            output_iso,
            dry_run,
        } => {
            let final_compression = if release {
                SquashfsCompression::Xz
            } else {
                compression
            };
            let final_output = output_iso.unwrap_or_else(|| work_dir.join(DEFAULT_ISO_FILENAME));

            let config = BuildConfig {
                arch,
                compression: final_compression,
                mirror,
                keyring,
                work_dir,
                includes_chroot_dir: includes_chroot,
                extra_overlays,
                stage_bins,
                packages_file,
                output_iso: final_output,
                dry_run,
            };

            let pipeline = IsoBuildPipeline::new(config)?;
            let pipeline = pipeline.bootstrap_debian_trixie(&mut stdout)?;
            let pipeline = pipeline.configure_chroot_and_apply_overlay(&mut stdout)?;
            let pipeline = pipeline.pack_squashfs_and_stage_bootloader(&mut stdout)?;
            let _finalized = pipeline.build_hybrid_iso(&mut stdout)?;
            Ok(())
        }
        Commands::Hash { file_path } => {
            let digest = compute_file_sha256(&file_path)?;
            writeln!(stdout, "{}  {}", digest, file_path.display()).map_err(|e| {
                CaramCtlError::IoFailure {
                    context: "In mã băm SHA-256".to_string(),
                    path: None,
                    source: e,
                }
            })?;
            Ok(())
        }
        Commands::OtaApply {
            root,
            target,
            payload,
            sha256,
            version,
        } => {
            let req = OtaApplyRequest {
                root_dir: &root,
                relative_target: &target,
                payload_path: &payload,
                expected_sha256: &sha256,
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
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    match run_cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "✖ {}", e);
            ExitCode::from(1)
        }
    }
}

// ============================================================================
// 8. KIỂM CHỨNG ĐƠN VỊ (SHA-256, SYMLINK OVERLAY, STAGE-BIN & HYBRID GRUB)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn test_sha256_fips_180_4_vectors() -> Result<(), CaramCtlError> {
        let dir = TempDir::new().map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo TempDir test SHA-256".to_string(),
            path: None,
            source: e,
        })?;
        let empty_file = dir.path().join("empty.bin");
        let abc_file = dir.path().join("abc.bin");
        atomic_write_file(&empty_file, b"")?;
        atomic_write_file(&abc_file, b"abc")?;

        assert_eq!(
            compute_file_sha256(&empty_file)?,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            compute_file_sha256(&abc_file)?,
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        Ok(())
    }

    #[test]
    fn test_overlay_preserves_symlinks_and_stages_bins_cleanly() -> Result<(), CaramCtlError> {
        let temp_base = TempDir::new().map_err(|e| CaramCtlError::IoFailure {
            context: "Tạo TempDir test pipeline".to_string(),
            path: None,
            source: e,
        })?;
        let includes_dir = temp_base.path().join("config/includes.chroot");
        let ui_overlay = temp_base.path().join("build/ui_overlay");
        let work_dir = temp_base.path().join("build");
        let pkg_file = temp_base.path().join("config/packages.txt");
        let fake_ui_bin = temp_base.path().join("caramos-ui");

        let bg_real = includes_dir.join("usr/share/backgrounds/caramos/indigo-night.png");
        atomic_write_file(&bg_real, b"CARAMOS_EXISTING_WALLPAPER_PNG")?;

        #[cfg(unix)]
        {
            let icon_dir = includes_dir.join("usr/share/icons/Tela-circle");
            fs::create_dir_all(&icon_dir).map_err(|e| CaramCtlError::IoFailure {
                context: "Tạo thư mục icon test".to_string(),
                path: Some(icon_dir.clone()),
                source: e,
            })?;
            atomic_write_file(&icon_dir.join("target.svg"), b"<svg/>")?;
            std::os::unix::fs::symlink("target.svg", icon_dir.join("link.svg")).map_err(|e| {
                CaramCtlError::IoFailure {
                    context: "Tạo symlink test".to_string(),
                    path: None,
                    source: e,
                }
            })?;
        }

        let theme_png = ui_overlay.join("boot/grub/themes/caramos/background.png");
        atomic_write_file(&theme_png, b"EXISTING_PNG_REUSED_FOR_GRUB")?;
        atomic_write_file(
            &ui_overlay.join("boot/grub/themes/caramos/theme.txt"),
            b"desktop-image: \"background.png\"\n",
        )?;

        atomic_write_file(&fake_ui_bin, b"ELF_CARAMOS_UI_BINARY")?;
        atomic_write_file(&pkg_file, b"linux-image-amd64\nlive-boot\n")?;

        let cfg = BuildConfig {
            arch: String::from("amd64"),
            compression: SquashfsCompression::Zstd,
            mirror: String::from("https://deb.debian.org/debian"),
            keyring: None,
            output_iso: work_dir.join(DEFAULT_ISO_FILENAME),
            work_dir: work_dir.clone(),
            includes_chroot_dir: includes_dir,
            extra_overlays: vec![ui_overlay],
            stage_bins: vec![fake_ui_bin],
            packages_file: pkg_file,
            dry_run: true,
        };

        let mut log = Vec::new();
        let p = IsoBuildPipeline::new(cfg)?;
        let p = p.bootstrap_debian_trixie(&mut log)?;
        let p = p.configure_chroot_and_apply_overlay(&mut log)?;
        let p = p.pack_squashfs_and_stage_bootloader(&mut log)?;
        let _p = p.build_hybrid_iso(&mut log)?;

        assert!(work_dir.join("rootfs/usr/local/bin/caramos-ui").is_file());
        assert!(work_dir.join("iso_staging/.disk/caramos-iso").is_file());
        assert!(work_dir
            .join("iso_staging/boot/grub/themes/caramos/background.png")
            .is_file());

        #[cfg(unix)]
        {
            let staged_link = work_dir.join("rootfs/usr/share/icons/Tela-circle/link.svg");
            let meta = staged_link.symlink_metadata().map_err(|e| CaramCtlError::IoFailure {
                context: "Kiểm tra symlink trong rootfs".to_string(),
                path: Some(staged_link),
                source: e,
            })?;
            assert!(meta.file_type().is_symlink());
        }

        assert!(work_dir.join(DEFAULT_ISO_FILENAME).is_file());
        assert!(work_dir
            .join(format!("{}.sha256", DEFAULT_ISO_FILENAME))
            .is_file());

        Ok(())
    }
}
