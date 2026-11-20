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
#[allow(unused_assignments)]
//! # CaramOS 2.0 UI & System Experience Suite (`caramos-ui`)
//!
//! Tối ưu thuần Rust với crate ngoài chuẩn hóa, bảo toàn 100% bản sắc UI gốc của CaramOS:
//! 1. `installer`: Trình cài đặt thân thiện người dùng cuối (tự liệt kê ổ đĩa `lsblk`, tạo tài khoản
//!    người dùng thường + mật khẩu ẩn `rpassword`, khóa cứng `root` bằng `passwd -l root`,
//!    cấu hình múi giờ/LightDM/GRUB UEFI & BIOS, kiểm định Typestate).
//! 2. `bootloader`: **Không tự vẽ hình nền** — tự tìm và tái sử dụng hình nền có sẵn trong
//!    `config/includes.chroot/usr/share/backgrounds/` (và logo `assets/CaramOS_logo.png`),
//!    chuẩn hóa sang PNG cho GRUB2 + Plymouth, giữ nguyên giao diện Cinnamon gốc của CaramOS.
//! 3. `updater`: Trình cập nhật OTA TUI truyền luồng `O(1)` RAM, xác thực SHA-256 phần cứng (`sha2`)
//!    và Rollback nguyên tử (`tempfile`), hỗ trợ chế độ `--interactive`.

use clap::{Parser, Subcommand};
use image::imageops::FilterType;
use image::{DynamicImage, ImageFormat, ImageReader};
use sha2::{Digest, Sha256};
use std::env;
use std::ffi::OsString;
use std::fmt;
use std::fs::{self, File};
use std::io::{self, BufRead, BufReader, BufWriter, Read, Write};
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
pub enum CaramUiError {
    #[error("[CLI_ERR] Tham số '{argument}' không hợp lệ: {reason}")]
    InvalidCliArgument { argument: String, reason: String },

    #[error("[VALIDATION_ERR] Trường '{field}' có giá trị '{value}' bị từ chối: {reason}")]
    ValidationFailed {
        field: &'static str,
        value: String,
        reason: &'static str,
    },

    #[error("[SECURITY_ERR] Đường dẫn '{}' bị chặn vì lý do an toàn: {reason}", path.display())]
    UnsafePath { path: PathBuf, reason: &'static str },

    #[error("[ASSET_ERR] Không tìm thấy hình nền có sẵn trong '{}'. Không tự tạo hình nền giả; hãy truyền --wallpaper <FILE> hoặc bổ sung ảnh vào thư mục backgrounds.", search_dir.display())]
    WallpaperNotFound { search_dir: PathBuf },

    #[error("[IMAGE_ERR] Không thể đọc/chuẩn hóa ảnh nền có sẵn '{}': {reason}", path.display())]
    ImageProcessingFailed { path: PathBuf, reason: String },

    #[error("[EXEC_ERR] Tiến trình hệ thống '{binary}' thất bại (mã thoát: {status_code:?}): {context}")]
    SubprocessFailed {
        binary: String,
        status_code: Option<i32>,
        context: String,
    },

    #[error("[IO_ERR] Thao tác '{context}'{} thất bại: {source}", fmt_opt_path(path))]
    IoFailure {
        context: String,
        path: Option<PathBuf>,
        #[source]
        source: io::Error,
    },

    #[error("[CRYPTO_ERR] Sai lệch mã băm SHA-256 tại '{}': kỳ vọng '{expected}', thực tế '{actual}'", target.display())]
    DigestMismatch {
        target: PathBuf,
        expected: String,
        actual: String,
    },

    #[error("[CRITICAL_OTA_ERR] Lỗi gốc ({original_err}) VÀ lỗi khôi phục tại '{}': {rollback_err}", target.display())]
    RollbackFailure {
        target: PathBuf,
        original_err: String,
        #[source]
        rollback_err: io::Error,
    },
}

// ============================================================================
// 2. BẢNG MÀU TUI TRUNG TÍNH ĐỒNG BỘ BẢN SẮC CARAMOS (INDIGO NIGHT / SAGE MIST)
// ============================================================================

const ANSI_RESET: &str = "\x1b[0m";
const ANSI_BOLD: &str = "\x1b[1m";
const ANSI_INDIGO: &str = "\x1b[38;5;75m";
const ANSI_SKY: &str = "\x1b[38;5;117m";
const ANSI_WHITE: &str = "\x1b[38;5;255m";
const ANSI_SAGE: &str = "\x1b[38;5;114m";
const ANSI_ROSE: &str = "\x1b[38;5;203m";
const ANSI_SLATE: &str = "\x1b[38;5;246m";

#[derive(Debug, Clone, Copy)]
pub struct OnboardingSlide {
    pub index: usize,
    pub total: usize,
    pub title: &'static str,
    pub subtitle: &'static str,
    pub highlights: &'static [&'static str],
}

pub const CARAMOS_TOUR_SLIDES: [OnboardingSlide; 4] = [
    OnboardingSlide {
        index: 1,
        total: 4,
        title: "NỀN TẢNG DEBIAN 13 (TRIXIE) TRỰC TIẾP",
        subtitle: "Loại bỏ hoàn toàn mô hình phái sinh chồng chéo 3 tầng",
        highlights: &[
            "• Dựng Rootfs trực tiếp từ kho Debian 13 (Trixie) bằng mmdebstrap.",
            "• Không phụ thuộc trung gian vào ISO Ubuntu hay Linux Mint.",
            "• Giảm dung lượng ảnh Live ISO và tối ưu tốc độ khởi động UEFI/BIOS.",
        ],
    },
    OnboardingSlide {
        index: 2,
        total: 4,
        title: "TÀI KHOẢN NGƯỜI DÙNG CHUẨN & AN TOÀN BỘ NHỚ",
        subtitle: "Bảo mật mặc định cho người dùng hằng ngày — khóa đăng nhập root",
        highlights: &[
            "• Tạo tài khoản người dùng cá nhân đầy đủ quyền sudo và nhóm phần cứng Desktop.",
            "• Khóa đăng nhập trực tiếp tài khoản root sau khi cài đặt hoàn tất.",
            "• Công cụ hệ thống viết bằng Rust chuẩn #![forbid(unsafe_code)].",
        ],
    },
    OnboardingSlide {
        index: 3,
        total: 4,
        title: "BẢN SẮC GIAO DIỆN CARAMOS NGUYÊN BẢN",
        subtitle: "Giữ trọn trải nghiệm Cinnamon đặc trưng của cộng đồng CaramOS",
        highlights: &[
            "• Giữ nguyên giao diện Cinnamon Delight, biểu tượng Tela Circle, con trỏ Bibata.",
            "• Giữ nguyên font Be Vietnam Pro, Island Dock, Control Center và bộ hình nền gốc.",
            "• Tái sử dụng hình nền có sẵn xuyên suốt từ GRUB2, Plymouth đến Desktop.",
        ],
    },
    OnboardingSlide {
        index: 4,
        total: 4,
        title: "CẬP NHẬT OTA NGUYÊN TỬ (ATOMIC OTA)",
        subtitle: "Xác thực mật mã SHA-256 và tự động khôi phục khi xảy ra sự cố",
        highlights: &[
            "• Băm truyền luồng O(1) RAM theo chuẩn FIPS 180-4 trước khi hoán đổi tệp.",
            "• Ghi vào vùng đệm cùng phân vùng, đồng bộ fsync và đổi tên nguyên tử.",
            "• Tự động Rollback về bản sao lưu nguyên vẹn nếu phát hiện lỗi I/O.",
        ],
    },
];

pub struct TerminalSessionGuard {
    active: bool,
}

impl TerminalSessionGuard {
    pub fn new(active: bool) -> io::Result<Self> {
        if active {
            let mut out = io::stdout().lock();
            out.write_all(ANSI_RESET.as_bytes())?;
            out.flush()?;
        }
        Ok(Self { active })
    }
}

impl Drop for TerminalSessionGuard {
    fn drop(&mut self) {
        if self.active {
            let mut out = io::stdout().lock();
            let _ = out.write_all(b"\x1b[0m\n");
            let _ = out.flush();
        }
    }
}

// ============================================================================
// 3. PHÒNG THỦ ĐẦU VÀO & KIỂU MIỀN (DOMAIN NEWTYPES)
// ============================================================================

pub fn validate_safe_path(path: &Path) -> Result<(), CaramUiError> {
    let raw = path.to_string_lossy();
    if raw.is_empty() {
        return Err(CaramUiError::UnsafePath {
            path: path.to_path_buf(),
            reason: "Đường dẫn không được để trống",
        });
    }
    if raw.contains('\0') {
        return Err(CaramUiError::UnsafePath {
            path: path.to_path_buf(),
            reason: "Đường dẫn chứa byte NULL độc hại",
        });
    }
    for comp in path.components() {
        if matches!(comp, Component::ParentDir) {
            return Err(CaramUiError::UnsafePath {
                path: path.to_path_buf(),
                reason: "Chặn hành vi leo thang thư mục qua '..' (Path Traversal)",
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
fn set_unix_mode(path: &Path, mode: u32) -> Result<(), CaramUiError> {
    fs::set_permissions(path, fs::Permissions::from_mode(mode)).map_err(|e| {
        CaramUiError::IoFailure {
            context: format!("Thiết lập quyền POSIX {:o}", mode),
            path: Some(path.to_path_buf()),
            source: e,
        }
    })
}

#[cfg(not(unix))]
fn set_unix_mode(_path: &Path, _mode: u32) -> Result<(), CaramUiError> {
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedBlockDevice(PathBuf);

impl ValidatedBlockDevice {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        let path = PathBuf::from(trimmed);
        validate_safe_path(&path)?;

        let allowed_prefixes = ["/dev/sd", "/dev/nvme", "/dev/vd", "/dev/mmcblk", "/dev/loop"];
        let has_valid_prefix = allowed_prefixes.iter().any(|p| trimmed.starts_with(p));
        if !has_valid_prefix || trimmed.len() <= 7 {
            return Err(CaramUiError::ValidationFailed {
                field: "target_disk",
                value: trimmed.to_string(),
                reason: "Thiết bị khối phải thuộc chuẩn /dev/sdX, /dev/nvmeXnY, /dev/vdX hoặc /dev/mmcblkX",
            });
        }

        let suffix = trimmed
            .get(5..)
            .ok_or_else(|| CaramUiError::ValidationFailed {
                field: "target_disk",
                value: trimmed.to_string(),
                reason: "Độ dài đường dẫn thiết bị quá ngắn",
            })?;

        if !suffix.chars().all(|c| c.is_ascii_alphanumeric()) {
            return Err(CaramUiError::ValidationFailed {
                field: "target_disk",
                value: trimmed.to_string(),
                reason: "Tên thiết bị chứa ký tự đặc biệt không hợp lệ",
            });
        }

        Ok(Self(path))
    }

    pub fn as_path(&self) -> &Path {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedFullName(String);

impl ValidatedFullName {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        if trimmed.is_empty() || trimmed.chars().count() > 64 {
            return Err(CaramUiError::ValidationFailed {
                field: "full_name",
                value: trimmed.to_string(),
                reason: "Họ tên hiển thị phải dài từ 1 đến 64 ký tự",
            });
        }
        if trimmed.contains(':') || trimmed.chars().any(char::is_control) {
            return Err(CaramUiError::ValidationFailed {
                field: "full_name",
                value: trimmed.to_string(),
                reason: "Họ tên không được chứa dấu hai chấm (:) hoặc ký tự điều khiển",
            });
        }
        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedUsername(String);

impl ValidatedUsername {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        if trimmed.is_empty() || trimmed.len() > 32 {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Độ dài tên đăng nhập phải từ 1 đến 32 ký tự",
            });
        }
        if trimmed.eq_ignore_ascii_case("root") {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Vì an toàn, CaramOS chỉ dùng tài khoản người dùng thường (cấm tạo/dùng tài khoản 'root')",
            });
        }

        let mut chars = trimmed.chars();
        let first = chars.next().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "username",
            value: String::new(),
            reason: "Tên đăng nhập rỗng",
        })?;

        if !(first.is_ascii_lowercase() || first == '_') {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Ký tự đầu tiên phải là chữ thường (a-z) hoặc gạch dưới (_)",
            });
        }

        if !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-') {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Chỉ cho phép chữ thường (a-z), chữ số (0-9), gạch dưới (_) và gạch ngang (-)",
            });
        }

        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, PartialEq, Eq)]
pub struct ValidatedPassword(String);

impl fmt::Debug for ValidatedPassword {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("ValidatedPassword(***)")
    }
}

impl Drop for ValidatedPassword {
    fn drop(&mut self) {
        self.0.clear();
    }
}

impl ValidatedPassword {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        if input.len() < 4 || input.len() > 128 {
            return Err(CaramUiError::ValidationFailed {
                field: "password",
                value: "***".to_string(),
                reason: "Mật khẩu phải có độ dài từ 4 đến 128 ký tự",
            });
        }
        if input.contains('\n') || input.contains('\r') || input.contains('\0') {
            return Err(CaramUiError::ValidationFailed {
                field: "password",
                value: "***".to_string(),
                reason: "Mật khẩu không được chứa ký tự xuống dòng hoặc NULL",
            });
        }
        Ok(Self(input.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedHostname(String);

impl ValidatedHostname {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        if trimmed.is_empty() || trimmed.len() > 63 {
            return Err(CaramUiError::ValidationFailed {
                field: "hostname",
                value: trimmed.to_string(),
                reason: "Hostname phải có độ dài từ 1 đến 63 ký tự",
            });
        }
        if trimmed.starts_with('-') || trimmed.ends_with('-') {
            return Err(CaramUiError::ValidationFailed {
                field: "hostname",
                value: trimmed.to_string(),
                reason: "Hostname không được bắt đầu hoặc kết thúc bằng dấu gạch ngang (-)",
            });
        }
        if !trimmed
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '-')
        {
            return Err(CaramUiError::ValidationFailed {
                field: "hostname",
                value: trimmed.to_string(),
                reason: "Hostname chỉ được chứa chữ thường (a-z), số (0-9) và dấu gạch ngang (-)",
            });
        }
        Ok(Self(trimmed.to_string()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

// ============================================================================
// 4. PHÂN HỆ 1: TRÌNH CÀI ĐẶT HỆ ĐIỀU HÀNH THÂN THIỆN USER & KHÓA ROOT (`installer`)
// ============================================================================

pub struct StageWelcome;
pub struct StageTourCompleted;
pub struct StageDiskValidated;
pub struct StageUserConfigured;
pub struct StageCommitted;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PartitionLayoutPlan {
    pub efi_partition: String,
    pub efi_size_mib: u64,
    pub root_partition: String,
    pub filesystem: &'static str,
}

pub struct AccountConfig<'a> {
    pub full_name: &'a str,
    pub username: &'a str,
    pub password: &'a str,
    pub hostname: &'a str,
    pub timezone: &'a str,
    pub autologin: bool,
}

#[derive(Debug, Clone)]
struct ValidatedAccount {
    full_name: ValidatedFullName,
    username: ValidatedUsername,
    password: ValidatedPassword,
    hostname: ValidatedHostname,
    timezone: String,
    autologin: bool,
}

#[derive(Debug, Clone)]
struct DetectedDisk {
    path: String,
    size: String,
    model: String,
}

fn discover_physical_disks() -> Vec<DetectedDisk> {
    let Ok(output) = Command::new("lsblk")
        .args(["-dn", "-o", "PATH,SIZE,TYPE,MODEL"])
        .output()
    else {
        return Vec::new();
    };
    if !output.status.success() {
        return Vec::new();
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut disks = Vec::new();
    for line in stdout.lines() {
        let mut parts = line.split_whitespace();
        let Some(path) = parts.next() else {
            continue;
        };
        let Some(size) = parts.next() else {
            continue;
        };
        let Some(dev_type) = parts.next() else {
            continue;
        };
        if dev_type != "disk" || path.starts_with("/dev/loop") {
            continue;
        }
        if ValidatedBlockDevice::parse(path).is_err() {
            continue;
        }
        let model = parts.collect::<Vec<_>>().join(" ");
        disks.push(DetectedDisk {
            path: path.to_string(),
            size: size.to_string(),
            model: if model.is_empty() {
                String::from("Ổ đĩa hệ thống")
            } else {
                model
            },
        });
    }
    disks
}

pub struct CaramInstaller<Stage> {
    target_root: PathBuf,
    dry_run: bool,
    confirm_erase_disk: bool,
    slides_viewed: usize,
    disk: Option<ValidatedBlockDevice>,
    layout: Option<PartitionLayoutPlan>,
    account: Option<ValidatedAccount>,
    _stage: PhantomData<Stage>,
}

impl CaramInstaller<StageWelcome> {
    pub fn new(
        target_root: PathBuf,
        dry_run: bool,
        confirm_erase_disk: bool,
    ) -> Result<Self, CaramUiError> {
        validate_safe_path(&target_root)?;
        Ok(Self {
            target_root,
            dry_run,
            confirm_erase_disk,
            slides_viewed: 0,
            disk: None,
            layout: None,
            account: None,
            _stage: PhantomData,
        })
    }

    pub fn run_onboarding_tour<W: Write>(
        mut self,
        writer: &mut W,
    ) -> Result<CaramInstaller<StageTourCompleted>, CaramUiError> {
        writeln!(
            writer,
            "\n{}{}==============================================================================\n\
               CARAMOS 2.0 — TRÌNH CÀI ĐẶT HỆ ĐIỀU HÀNH (DEBIAN 13 TRIXIE & RUST CORE)\n\
             =============================================================================={}",
            ANSI_BOLD, ANSI_INDIGO, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "Hiển thị tiêu đề Installer".to_string(),
            path: None,
            source: e,
        })?;

        for slide in &CARAMOS_TOUR_SLIDES {
            writeln!(
                writer,
                "\n{}{}┌─ [{}/{}] {} ──────────────────────────────────────────────────────────{}",
                ANSI_BOLD, ANSI_INDIGO, slide.index, slide.total, slide.title, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Ghi tiêu đề Slide".to_string(),
                path: None,
                source: e,
            })?;

            writeln!(writer, "{}  {}{}", ANSI_SKY, slide.subtitle, ANSI_RESET).map_err(|e| {
                CaramUiError::IoFailure {
                    context: "Ghi phụ đề Slide".to_string(),
                    path: None,
                    source: e,
                }
            })?;

            for line in slide.highlights {
                writeln!(writer, "{}  {}{}", ANSI_WHITE, line, ANSI_RESET).map_err(|e| {
                    CaramUiError::IoFailure {
                        context: "Ghi nội dung Slide".to_string(),
                        path: None,
                        source: e,
                    }
                })?;
            }

            self.slides_viewed = self.slides_viewed.saturating_add(1);
        }

        Ok(CaramInstaller {
            target_root: self.target_root,
            dry_run: self.dry_run,
            confirm_erase_disk: self.confirm_erase_disk,
            slides_viewed: self.slides_viewed,
            disk: None,
            layout: None,
            account: None,
            _stage: PhantomData,
        })
    }
}

impl CaramInstaller<StageTourCompleted> {
    pub fn select_and_validate_disk(
        self,
        device_str: &str,
    ) -> Result<CaramInstaller<StageDiskValidated>, CaramUiError> {
        let device = ValidatedBlockDevice::parse(device_str)?;
        let raw_name = device.as_path().to_string_lossy();

        let part_sep = if raw_name.starts_with("/dev/nvme")
            || raw_name.starts_with("/dev/mmcblk")
            || raw_name.starts_with("/dev/loop")
        {
            "p"
        } else {
            ""
        };

        let layout = PartitionLayoutPlan {
            efi_partition: format!("{}{}1", raw_name, part_sep),
            efi_size_mib: 512,
            root_partition: format!("{}{}2", raw_name, part_sep),
            filesystem: "ext4 (journal_checksum,noatime)",
        };

        Ok(CaramInstaller {
            target_root: self.target_root,
            dry_run: self.dry_run,
            confirm_erase_disk: self.confirm_erase_disk,
            slides_viewed: self.slides_viewed,
            disk: Some(device),
            layout: Some(layout),
            account: None,
            _stage: PhantomData,
        })
    }
}

impl CaramInstaller<StageDiskValidated> {
    pub fn configure_account(
        self,
        cfg: &AccountConfig<'_>,
    ) -> Result<CaramInstaller<StageUserConfigured>, CaramUiError> {
        let full_name = ValidatedFullName::parse(cfg.full_name)?;
        let username = ValidatedUsername::parse(cfg.username)?;
        let password = ValidatedPassword::parse(cfg.password)?;
        let hostname = ValidatedHostname::parse(cfg.hostname)?;

        let tz_trimmed = cfg.timezone.trim();
        if tz_trimmed.is_empty() || tz_trimmed.contains("..") || tz_trimmed.contains('\0') {
            return Err(CaramUiError::ValidationFailed {
                field: "timezone",
                value: tz_trimmed.to_string(),
                reason: "Múi giờ không hợp lệ hoặc chứa chuỗi leo thang thư mục",
            });
        }

        Ok(CaramInstaller {
            target_root: self.target_root,
            dry_run: self.dry_run,
            confirm_erase_disk: self.confirm_erase_disk,
            slides_viewed: self.slides_viewed,
            disk: self.disk,
            layout: self.layout,
            account: Some(ValidatedAccount {
                full_name,
                username,
                password,
                hostname,
                timezone: tz_trimmed.to_string(),
                autologin: cfg.autologin,
            }),
            _stage: PhantomData,
        })
    }
}

/// Bảo vệ tự tháo các điểm gắn kết phân vùng đích theo thứ tự ngược khi kết thúc cài đặt.
struct InstallMountGuard {
    mounts: Vec<PathBuf>,
}

impl InstallMountGuard {
    fn new() -> Self {
        Self { mounts: Vec::new() }
    }

    fn push(&mut self, target: PathBuf) {
        self.mounts.push(target);
    }
}

impl Drop for InstallMountGuard {
    fn drop(&mut self) {
        while let Some(target) = self.mounts.pop() {
            let _ = Command::new("umount")
                .arg("-R")
                .arg(target)
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
}

fn run_sys_cmd(cmd: &mut Command, context: &str) -> Result<(), CaramUiError> {
    let binary = cmd.get_program().to_string_lossy().to_string();
    let status = cmd.status().map_err(|e| CaramUiError::IoFailure {
        context: format!("Chạy '{}' ({})", binary, context),
        path: None,
        source: e,
    })?;
    if !status.success() {
        return Err(CaramUiError::SubprocessFailed {
            binary,
            status_code: status.code(),
            context: context.to_string(),
        });
    }
    Ok(())
}

/// Truyền mật khẩu an toàn qua pipe `stdin` cho `chpasswd` (không lộ trong argv/ps).
fn set_user_password_in_chroot(
    target_root: &Path,
    username: &ValidatedUsername,
    password: &ValidatedPassword,
) -> Result<(), CaramUiError> {
    let mut child = Command::new("chroot")
        .arg(target_root)
        .arg("chpasswd")
        .stdin(Stdio::piped())
        .spawn()
        .map_err(|e| CaramUiError::IoFailure {
            context: "Khởi chạy chpasswd trong hệ thống đích".to_string(),
            path: Some(target_root.to_path_buf()),
            source: e,
        })?;

    if let Some(mut stdin) = child.stdin.take() {
        writeln!(stdin, "{}:{}", username.as_str(), password.as_str()).map_err(|e| {
            CaramUiError::IoFailure {
                context: "Ghi mật khẩu qua pipe chpasswd".to_string(),
                path: None,
                source: e,
            }
        })?;
    }

    let status = child.wait().map_err(|e| CaramUiError::IoFailure {
        context: "Đợi tiến trình chpasswd hoàn tất".to_string(),
        path: None,
        source: e,
    })?;
    if !status.success() {
        return Err(CaramUiError::SubprocessFailed {
            binary: "chpasswd".to_string(),
            status_code: status.code(),
            context: "Đặt mật khẩu cho tài khoản người dùng".to_string(),
        });
    }
    Ok(())
}

/// Chỉ gán các nhóm Desktop có thật trong `/etc/group` của hệ thống đích để tránh lỗi `usermod`.
fn resolve_existing_desktop_groups(target_root: &Path) -> Vec<&'static str> {
    let desired = [
        "sudo",
        "audio",
        "video",
        "plugdev",
        "netdev",
        "bluetooth",
        "cdrom",
        "lpadmin",
    ];
    let group_file = target_root.join("etc/group");
    let Ok(content) = fs::read_to_string(&group_file) else {
        return vec!["sudo"];
    };

    let mut matched = Vec::new();
    for grp in desired {
        let prefix = format!("{}:", grp);
        if content.lines().any(|line| line.starts_with(&prefix)) {
            matched.push(grp);
        }
    }
    if matched.is_empty() {
        matched.push("sudo");
    }
    matched
}

fn configure_timezone_in_target(target_root: &Path, timezone: &str) -> Result<(), CaramUiError> {
    atomic_write_bytes(
        &target_root.join("etc/timezone"),
        format!("{}\n", timezone).as_bytes(),
    )?;

    let zoneinfo_rel = Path::new("usr/share/zoneinfo").join(timezone);
    if target_root.join(&zoneinfo_rel).is_file() {
        let localtime_path = target_root.join("etc/localtime");
        if localtime_path.symlink_metadata().is_ok() {
            let _ = fs::remove_file(&localtime_path);
        }
        #[cfg(unix)]
        {
            let target_zone = Path::new("/usr/share/zoneinfo").join(timezone);
            std::os::unix::fs::symlink(target_zone, &localtime_path).map_err(|e| {
                CaramUiError::IoFailure {
                    context: "Liên kết /etc/localtime cho múi giờ".to_string(),
                    path: Some(localtime_path),
                    source: e,
                }
            })?;
        }
    }
    Ok(())
}

fn configure_lightdm_autologin(
    target_root: &Path,
    username: &ValidatedUsername,
    autologin: bool,
) -> Result<(), CaramUiError> {
    let conf_dir = target_root.join("etc/lightdm/lightdm.conf.d");
    let live_dropin = conf_dir.join("12-autologin.conf");
    if live_dropin.exists() {
        let _ = fs::remove_file(&live_dropin);
    }

    let caramos_dropin = conf_dir.join("50-caramos-autologin.conf");
    if autologin {
        let content = format!(
            "# CaramOS Standard User Auto-Login (Never root)\n\
             [Seat:*]\n\
             autologin-user={}\n\
             autologin-user-timeout=0\n",
            username.as_str()
        );
        atomic_write_bytes(&caramos_dropin, content.as_bytes())?;
    } else if caramos_dropin.exists() {
        let _ = fs::remove_file(&caramos_dropin);
    }
    Ok(())
}

impl CaramInstaller<StageUserConfigured> {
    pub fn commit_installation<W: Write>(
        self,
        writer: &mut W,
    ) -> Result<CaramInstaller<StageCommitted>, CaramUiError> {
        let disk = self.disk.as_ref().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "disk",
            value: String::new(),
            reason: "Trạng thái thiết bị khối bị thiếu",
        })?;
        let layout = self.layout.as_ref().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "layout",
            value: String::new(),
            reason: "Sơ đồ phân vùng bị thiếu",
        })?;
        let account = self
            .account
            .as_ref()
            .ok_or_else(|| CaramUiError::ValidationFailed {
                field: "account",
                value: String::new(),
                reason: "Thông tin tài khoản người dùng bị thiếu",
            })?;

        if !self.dry_run {
            if !self.confirm_erase_disk {
                return Err(CaramUiError::ValidationFailed {
                    field: "confirm_erase_disk",
                    value: "false".to_string(),
                    reason: "Chế độ --execute yêu cầu xác nhận --confirm-erase-disk để tránh xóa nhầm ổ cứng",
                });
            }
            self.execute_live_disk_install(disk, layout, account, writer)?;
        } else {
            writeln!(
                writer,
                "\n{}{}▶ ĐANG MÔ PHỎNG KẾ HOẠCH CÀI ĐẶT CARAMOS 2.0 (DRY-RUN AN TOÀN){}",
                ANSI_BOLD, ANSI_SAGE, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "In tiêu đề dry-run cài đặt".to_string(),
                path: None,
                source: e,
            })?;

            let steps: [(u8, &str); 5] = [
                (20, "Kiểm định sơ đồ bảng phân vùng GPT & EFI (512 MiB FAT32)"),
                (45, "Kiểm định định dạng phân vùng Rootfs ext4"),
                (70, "Kiểm định giải nén Debian 13 (Trixie) Live SquashFS"),
                (85, "Kiểm định tài khoản người dùng thường (khóa root) & múi giờ"),
                (100, "Ghi biên bản cấu hình cài đặt nguyên tử (không lưu mật khẩu)"),
            ];
            for (percent, desc) in &steps {
                render_progress_bar(writer, *percent, desc)?;
            }
        }

        let etc_dir = self.target_root.join("etc");
        fs::create_dir_all(&etc_dir).map_err(|e| CaramUiError::IoFailure {
            context: "Khởi tạo thư mục /etc đích".to_string(),
            path: Some(etc_dir.clone()),
            source: e,
        })?;

        let hostname_path = etc_dir.join("hostname");
        atomic_write_bytes(
            &hostname_path,
            format!("{}\n", account.hostname.as_str()).as_bytes(),
        )?;

        // Tuyệt đối không ghi mật khẩu vào manifest
        let manifest_path = etc_dir.join("caramos-install-manifest.conf");
        let manifest_content = format!(
            "# CaramOS 2.0 Installation Manifest (Generated by caramos-ui)\n\
             OS_NAME=\"CaramOS 2.0 (Debian 13 Trixie)\"\n\
             DRY_RUN={}\n\
             SLIDES_VIEWED={}\n\
             TARGET_DISK=\"{}\"\n\
             EFI_PARTITION=\"{}\"\n\
             EFI_SIZE_MIB={}\n\
             ROOT_PARTITION=\"{}\"\n\
             FILESYSTEM=\"{}\"\n\
             USER_FULL_NAME=\"{}\"\n\
             STANDARD_USER=\"{}\"\n\
             ROOT_LOGIN_LOCKED=true\n\
             AUTOLOGIN={}\n\
             HOSTNAME=\"{}\"\n\
             TIMEZONE=\"{}\"\n",
            self.dry_run,
            self.slides_viewed,
            disk.as_path().display(),
            layout.efi_partition,
            layout.efi_size_mib,
            layout.root_partition,
            layout.filesystem,
            account.full_name.as_str(),
            account.username.as_str(),
            account.autologin,
            account.hostname.as_str(),
            account.timezone
        );
        atomic_write_bytes(&manifest_path, manifest_content.as_bytes())?;

        writeln!(
            writer,
            "\n{}{}✔ HOÀN TẤT! Tài khoản đăng nhập: '{}' (Tài khoản root đã khóa).\n  Biên bản tại: '{}'{}",
            ANSI_BOLD,
            ANSI_SAGE,
            account.username.as_str(),
            manifest_path.display(),
            ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "Ghi thông báo hoàn tất cài đặt".to_string(),
            path: None,
            source: e,
        })?;

        Ok(CaramInstaller {
            target_root: self.target_root,
            dry_run: self.dry_run,
            confirm_erase_disk: self.confirm_erase_disk,
            slides_viewed: self.slides_viewed,
            disk: self.disk,
            layout: self.layout,
            account: self.account,
            _stage: PhantomData,
        })
    }

    fn execute_live_disk_install<W: Write>(
        &self,
        disk: &ValidatedBlockDevice,
        layout: &PartitionLayoutPlan,
        account: &ValidatedAccount,
        writer: &mut W,
    ) -> Result<(), CaramUiError> {
        let live_squashfs = Path::new("/run/live/medium/live/filesystem.squashfs");
        if !live_squashfs.is_file() {
            return Err(CaramUiError::IoFailure {
                context: "Chế độ --execute chỉ chạy bên trong môi trường Live ISO CaramOS (thiếu /run/live/medium/live/filesystem.squashfs)".to_string(),
                path: Some(live_squashfs.to_path_buf()),
                source: io::Error::new(io::ErrorKind::NotFound, "Missing live squashfs"),
            });
        }

        writeln!(
            writer,
            "\n{}{}▶ ĐANG CÀI ĐẶT CARAMOS 2.0 LÊN '{}' CHO NGƯỜI DÙNG '{}'{}",
            ANSI_BOLD,
            ANSI_SAGE,
            disk.as_path().display(),
            account.username.as_str(),
            ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "In tiêu đề cài đặt thực tế".to_string(),
            path: None,
            source: e,
        })?;

        render_progress_bar(writer, 15, "Tạo bảng phân vùng GPT (EFI 512MiB + Root ext4)...")?;
        run_sys_cmd(
            Command::new("parted")
                .arg("-s")
                .arg(disk.as_path())
                .arg("mklabel")
                .arg("gpt")
                .arg("mkpart")
                .arg("ESP")
                .arg("fat32")
                .arg("1MiB")
                .arg("513MiB")
                .arg("set")
                .arg("1")
                .arg("esp")
                .arg("on")
                .arg("mkpart")
                .arg("CARAMOS_ROOT")
                .arg("ext4")
                .arg("513MiB")
                .arg("100%"),
            "parted GPT layout",
        )?;

        render_progress_bar(writer, 28, "Định dạng phân vùng EFI (FAT32) & Root (ext4)...")?;
        run_sys_cmd(
            Command::new("mkfs.vfat")
                .arg("-F")
                .arg("32")
                .arg("-n")
                .arg("CARAMOS_EFI")
                .arg(&layout.efi_partition),
            "mkfs.vfat EFI",
        )?;
        run_sys_cmd(
            Command::new("mkfs.ext4")
                .arg("-F")
                .arg("-L")
                .arg("CARAMOS_ROOT")
                .arg(&layout.root_partition),
            "mkfs.ext4 root",
        )?;

        fs::create_dir_all(&self.target_root).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục gắn kết đích".to_string(),
            path: Some(self.target_root.clone()),
            source: e,
        })?;

        let mut mount_guard = InstallMountGuard::new();
        run_sys_cmd(
            Command::new("mount")
                .arg(&layout.root_partition)
                .arg(&self.target_root),
            "mount root partition",
        )?;
        mount_guard.push(self.target_root.clone());

        let efi_mount = self.target_root.join("boot/efi");
        fs::create_dir_all(&efi_mount).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục /boot/efi đích".to_string(),
            path: Some(efi_mount.clone()),
            source: e,
        })?;
        run_sys_cmd(
            Command::new("mount")
                .arg(&layout.efi_partition)
                .arg(efi_mount),
            "mount EFI partition",
        )?;

        render_progress_bar(writer, 55, "Giải nén hệ thống tệp SquashFS vào ổ đĩa đích...")?;
        run_sys_cmd(
            Command::new("unsquashfs")
                .arg("-f")
                .arg("-d")
                .arg(&self.target_root)
                .arg(live_squashfs),
            "unsquashfs live image",
        )?;

        render_progress_bar(
            writer,
            75,
            "Tạo tài khoản người dùng thường, đặt mật khẩu & khóa tài khoản root...",
        )?;
        for rel in ["dev", "proc", "sys", "run"] {
            let src = PathBuf::from("/").join(rel);
            let dst = self.target_root.join(rel);
            fs::create_dir_all(&dst).map_err(|e| CaramUiError::IoFailure {
                context: "Tạo điểm bind mount chroot cài đặt".to_string(),
                path: Some(dst.clone()),
                source: e,
            })?;
            run_sys_cmd(
                Command::new("mount").arg("--bind").arg(src).arg(dst),
                "bind mount chroot install",
            )?;
        }

        let fstab = "LABEL=CARAMOS_ROOT / ext4 errors=remount-ro,noatime 0 1\n\
                     LABEL=CARAMOS_EFI /boot/efi vfat umask=0077 0 1\n";
        atomic_write_bytes(&self.target_root.join("etc/fstab"), fstab.as_bytes())?;
        atomic_write_bytes(
            &self.target_root.join("etc/hosts"),
            format!(
                "127.0.0.1\tlocalhost\n127.0.1.1\t{}\n::1\t\tlocalhost ip6-localhost ip6-loopback\n",
                account.hostname.as_str()
            )
            .as_bytes(),
        )?;
        configure_timezone_in_target(&self.target_root, &account.timezone)?;

        // Xóa tài khoản live tạm `caram` nếu người dùng chọn tên đăng nhập khác
        if account.username.as_str() != "caram" {
            let _ = Command::new("chroot")
                .arg(&self.target_root)
                .args(["userdel", "-r", "caram"])
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }

        // Tạo tài khoản người dùng thường (không bao giờ là root)
        let user_exists = Command::new("chroot")
            .arg(&self.target_root)
            .arg("id")
            .arg("-u")
            .arg(account.username.as_str())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .map(|s| s.success())
            .unwrap_or(false);

        if !user_exists {
            run_sys_cmd(
                Command::new("chroot")
                    .arg(&self.target_root)
                    .arg("useradd")
                    .arg("-m")
                    .arg("-c")
                    .arg(account.full_name.as_str())
                    .arg("-s")
                    .arg("/bin/bash")
                    .arg(account.username.as_str()),
                "chroot useradd standard user",
            )?;
        }

        let desktop_groups = resolve_existing_desktop_groups(&self.target_root).join(",");
        run_sys_cmd(
            Command::new("chroot")
                .arg(&self.target_root)
                .arg("usermod")
                .arg("-aG")
                .arg(desktop_groups)
                .arg(account.username.as_str()),
            "chroot usermod desktop groups",
        )?;

        set_user_password_in_chroot(&self.target_root, &account.username, &account.password)?;

        // Khóa cứng tài khoản root: người dùng luôn dùng tài khoản cá nhân + sudo
        run_sys_cmd(
            Command::new("chroot")
                .arg(&self.target_root)
                .args(["passwd", "-l", "root"]),
            "chroot lock root account",
        )?;

        configure_lightdm_autologin(&self.target_root, &account.username, account.autologin)?;

        render_progress_bar(writer, 92, "Cài đặt GRUB2 Bootloader lên ổ đĩa đích...")?;
        if Path::new("/sys/firmware/efi").is_dir() {
            run_sys_cmd(
                Command::new("chroot")
                    .arg(&self.target_root)
                    .arg("grub-install")
                    .arg("--target=x86_64-efi")
                    .arg("--efi-directory=/boot/efi")
                    .arg("--bootloader-id=CaramOS")
                    .arg("--recheck"),
                "chroot grub-install UEFI",
            )?;
        } else {
            run_sys_cmd(
                Command::new("chroot")
                    .arg(&self.target_root)
                    .arg("grub-install")
                    .arg("--target=i386-pc")
                    .arg("--recheck")
                    .arg(disk.as_path()),
                "chroot grub-install Legacy BIOS",
            )?;
        }

        run_sys_cmd(
            Command::new("chroot")
                .arg(&self.target_root)
                .arg("update-grub"),
            "chroot update-grub",
        )?;
        render_progress_bar(writer, 100, "Hoàn tất ghi hệ điều hành CaramOS 2.0 lên đĩa.")?;

        Ok(())
    }
}

impl CaramInstaller<StageCommitted> {
    pub fn slides_viewed(&self) -> usize {
        self.slides_viewed
    }
}

// ============================================================================
// 5. PHÂN HỆ 2: TÁI SỬ DỤNG HÌNH NỀN CÓ SẴN CHO BOOTLOADER GRUB2 & PLYMOUTH
// ============================================================================

fn is_supported_wallpaper_ext(path: &Path) -> bool {
    let Some(ext) = path.extension().and_then(|e| e.to_str()) else {
        return false;
    };
    matches!(
        ext.to_ascii_lowercase().as_str(),
        "png" | "jpg" | "jpeg" | "webp"
    )
}

/// Tìm hình nền có sẵn của CaramOS — tuyệt đối không tự kết xuất ảnh giả.
pub fn discover_existing_wallpaper(
    explicit_wallpaper: Option<&Path>,
    search_dir: &Path,
) -> Result<PathBuf, CaramUiError> {
    if let Some(explicit) = explicit_wallpaper {
        validate_safe_path(explicit)?;
        if !explicit.is_file() {
            return Err(CaramUiError::WallpaperNotFound {
                search_dir: explicit.to_path_buf(),
            });
        }
        return Ok(explicit.to_path_buf());
    }

    validate_safe_path(search_dir)?;
    if !search_dir.is_dir() {
        return Err(CaramUiError::WallpaperNotFound {
            search_dir: search_dir.to_path_buf(),
        });
    }

    let mut candidates: Vec<PathBuf> = WalkDir::new(search_dir)
        .follow_links(true)
        .into_iter()
        .filter_map(Result::ok)
        .filter(|e| e.file_type().is_file() && is_supported_wallpaper_ext(e.path()))
        .map(|e| e.into_path())
        .collect();

    candidates.sort();

    let preferred_keywords = ["indigo", "night", "dark", "caramos"];
    for kw in preferred_keywords {
        if let Some(found) = candidates.iter().find(|p| {
            p.file_name()
                .map(|n| n.to_string_lossy().to_ascii_lowercase().contains(kw))
                .unwrap_or(false)
        }) {
            return Ok(found.clone());
        }
    }

    candidates
        .into_iter()
        .next()
        .ok_or_else(|| CaramUiError::WallpaperNotFound {
            search_dir: search_dir.to_path_buf(),
        })
}

/// Đọc hình nền có sẵn, giữ đúng tỷ lệ bằng Lanczos3 và ghi PNG RGB8 nguyên tử cho GRUB2/Plymouth.
fn stage_existing_wallpaper_png(
    src_wallpaper: &Path,
    dst_png: &Path,
    width: u16,
    height: u16,
) -> Result<(), CaramUiError> {
    if width < 64 || height < 64 || width > 3840 || height > 2160 {
        return Err(CaramUiError::ValidationFailed {
            field: "resolution",
            value: format!("{}x{}", width, height),
            reason: "Độ phân giải Bootloader phải nằm trong khoảng 64x64 đến 3840x2160",
        });
    }

    let reader = ImageReader::open(src_wallpaper)
        .map_err(|e| CaramUiError::IoFailure {
            context: "Mở tệp hình nền có sẵn".to_string(),
            path: Some(src_wallpaper.to_path_buf()),
            source: e,
        })?
        .with_guessed_format()
        .map_err(|e| CaramUiError::IoFailure {
            context: "Nhận diện định dạng hình nền có sẵn".to_string(),
            path: Some(src_wallpaper.to_path_buf()),
            source: e,
        })?;

    let decoded = reader
        .decode()
        .map_err(|e| CaramUiError::ImageProcessingFailed {
            path: src_wallpaper.to_path_buf(),
            reason: e.to_string(),
        })?;

    let target_w = u32::from(width);
    let target_h = u32::from(height);
    let fitted = if decoded.width() == target_w && decoded.height() == target_h {
        decoded
    } else {
        decoded.resize_to_fill(target_w, target_h, FilterType::Lanczos3)
    };
    let rgb_image = DynamicImage::ImageRgb8(fitted.to_rgb8());

    let parent = dst_png
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo thư mục đích ảnh Bootloader".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;

    let mut tmp = NamedTempFile::new_in(parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo tệp tạm PNG Bootloader".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;
    let tmp_path = tmp.path().to_path_buf();

    {
        let mut buf_writer = BufWriter::new(tmp.as_file_mut());
        rgb_image
            .write_to(&mut buf_writer, ImageFormat::Png)
            .map_err(|e| CaramUiError::ImageProcessingFailed {
                path: dst_png.to_path_buf(),
                reason: e.to_string(),
            })?;
        buf_writer.flush().map_err(|e| CaramUiError::IoFailure {
            context: "Xả bộ đệm PNG Bootloader".to_string(),
            path: Some(tmp_path.clone()),
            source: e,
        })?;
    }

    tmp.as_file()
        .sync_all()
        .map_err(|e| CaramUiError::IoFailure {
            context: "Đồng bộ fsync PNG Bootloader".to_string(),
            path: Some(tmp_path),
            source: e,
        })?;
    set_unix_mode(tmp.path(), 0o644)?;

    tmp.persist(dst_png).map_err(|e| CaramUiError::IoFailure {
        context: "Lưu nguyên tử ảnh PNG Bootloader".to_string(),
        path: Some(dst_png.to_path_buf()),
        source: e.error,
    })?;

    Ok(())
}

pub struct BootloaderStageConfig<'a> {
    pub output_root: &'a Path,
    pub explicit_wallpaper: Option<&'a Path>,
    pub wallpaper_search_dir: &'a Path,
    pub assets_dir: &'a Path,
    pub width: u16,
    pub height: u16,
}

pub fn build_caramos_bootloader_theme<W: Write>(
    cfg: &BootloaderStageConfig<'_>,
    writer: &mut W,
) -> Result<PathBuf, CaramUiError> {
    validate_safe_path(cfg.output_root)?;
    validate_safe_path(cfg.assets_dir)?;

    let source_wallpaper =
        discover_existing_wallpaper(cfg.explicit_wallpaper, cfg.wallpaper_search_dir)?;

    let grub_theme_dir = cfg.output_root.join("boot/grub/themes/caramos");
    let plymouth_dir = cfg.output_root.join("usr/share/plymouth/themes/caramos");
    let etc_default_dir = cfg.output_root.join("etc/default");
    let applications_dir = cfg.output_root.join("usr/share/applications");

    for dir in [&grub_theme_dir, &plymouth_dir, &etc_default_dir, &applications_dir] {
        fs::create_dir_all(dir).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục Bootloader & Desktop".to_string(),
            path: Some(dir.clone()),
            source: e,
        })?;
    }

    let grub_bg_path = grub_theme_dir.join("background.png");
    stage_existing_wallpaper_png(&source_wallpaper, &grub_bg_path, cfg.width, cfg.height)?;

    let plymouth_bg_path = plymouth_dir.join("background.png");
    fs::copy(&grub_bg_path, &plymouth_bg_path).map_err(|e| CaramUiError::IoFailure {
        context: "Sao chép ảnh nền sang Plymouth theme".to_string(),
        path: Some(plymouth_bg_path.clone()),
        source: e,
    })?;
    set_unix_mode(&plymouth_bg_path, 0o644)?;

    let logo_src = cfg.assets_dir.join("CaramOS_logo.png");
    let has_logo = if logo_src.is_file() {
        let logo_dst = plymouth_dir.join("logo.png");
        fs::copy(&logo_src, &logo_dst).map_err(|e| CaramUiError::IoFailure {
            context: "Sao chép logo CaramOS sang Plymouth".to_string(),
            path: Some(logo_dst.clone()),
            source: e,
        })?;
        set_unix_mode(&logo_dst, 0o644)?;
        true
    } else {
        false
    };

    let grub_theme_txt = r##"# CaramOS Official GRUB2 Bootloader Theme
# Reuses existing CaramOS wallpaper & neutral Indigo Night / Sage Mist palette

title-text: ""
desktop-image: "background.png"
desktop-color: "#0F172A"

+ label {
    top = 10%
    left = 10%
    width = 80%
    height = 36
    text = "CaramOS 2.0  |  Debian 13 (Trixie)"
    color = "#F8FAFC"
    align = "center"
}

+ boot_menu {
    left = 18%
    top = 28%
    width = 64%
    height = 46%
    item_color = "#CBD5E1"
    selected_item_color = "#38BDF8"
    item_height = 32
    item_padding = 8
    item_spacing = 6
    scrollbar = true
    scrollbar_width = 6
    scrollbar_thumb = "#38BDF8"
}

+ progress_bar {
    id = "__timeout__"
    left = 18%
    top = 80%
    width = 64%
    height = 18
    fg_color = "#38BDF8"
    bg_color = "#1E293B"
    border_color = "#475569"
    text_color = "#F8FAFC"
    text = "@TIMEOUT_NOTIFICATION_LONG@"
}

+ label {
    top = 89%
    left = 10%
    width = 80%
    height = 24
    text = "[↑/↓] Chọn hệ thống   |   [Enter] Khởi động   |   [E] Chỉnh tham số"
    color = "#94A3B8"
    align = "center"
}
"##;
    let theme_txt_path = grub_theme_dir.join("theme.txt");
    atomic_write_bytes(&theme_txt_path, grub_theme_txt.as_bytes())?;

    let plymouth_conf = r#"[Plymouth Theme]
Name=CaramOS Boot Splash
Description=Official CaramOS Boot Splash using existing CaramOS wallpaper and logo
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/caramos
ScriptFile=/usr/share/plymouth/themes/caramos/caramos.script
"#;
    atomic_write_bytes(&plymouth_dir.join("caramos.plymouth"), plymouth_conf.as_bytes())?;

    let plymouth_script = if has_logo {
        r#"bg_img = Image("background.png");
scaled_bg = bg_img.Scale(Window.GetWidth(), Window.GetHeight());
bg_sprite = Sprite(scaled_bg);
bg_sprite.SetZ(-100);

logo_img = Image("logo.png");
logo_sprite = Sprite(logo_img);
logo_sprite.SetX(Window.GetWidth() / 2 - logo_img.GetWidth() / 2);
logo_sprite.SetY(Window.GetHeight() / 2 - logo_img.GetHeight() / 2);
logo_sprite.SetZ(10);
"#
    } else {
        r#"bg_img = Image("background.png");
scaled_bg = bg_img.Scale(Window.GetWidth(), Window.GetHeight());
bg_sprite = Sprite(scaled_bg);
bg_sprite.SetZ(-100);
"#
    };
    atomic_write_bytes(&plymouth_dir.join("caramos.script"), plymouth_script.as_bytes())?;

    let grub_default = format!(
        r#"# CaramOS 2.0 GRUB2 Configuration
GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="CaramOS"
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 mitigations=auto init_on_alloc=1"
GRUB_CMDLINE_LINUX=""
GRUB_GFXMODE={}x{}x24,auto
GRUB_GFXPAYLOAD_LINUX=keep
GRUB_THEME="/boot/grub/themes/caramos/theme.txt"
"#,
        cfg.width, cfg.height
    );
    let grub_default_path = etc_default_dir.join("grub");
    atomic_write_bytes(&grub_default_path, grub_default.as_bytes())?;

    let installer_desktop = r#"[Desktop Entry]
Type=Application
Version=1.0
Name=Install CaramOS 2.0
Name[vi]=Cài đặt Hệ điều hành CaramOS 2.0
Comment=Install CaramOS 2.0 with Standard User Account Setup
Comment[vi]=Cài đặt CaramOS 2.0 lên máy tính và thiết lập tài khoản người dùng
Exec=sudo /usr/local/bin/caramos-ui installer --interactive --execute --target-root /mnt/caramos-target
Icon=system-software-install
Terminal=true
Categories=System;Settings;
"#;
    atomic_write_bytes(
        &applications_dir.join("caramos-installer.desktop"),
        installer_desktop.as_bytes(),
    )?;

    let updater_desktop = r#"[Desktop Entry]
Type=Application
Version=1.0
Name=CaramOS Transactional Updater (OTA)
Name[vi]=Trung tâm Cập nhật Hệ thống CaramOS (OTA)
Comment=SHA-256 Verified Atomic System Updater
Comment[vi]=Cập nhật hệ thống nguyên tử có kiểm định SHA-256
Exec=sudo /usr/local/bin/caramos-ui updater --interactive
Icon=system-software-update
Terminal=true
Categories=System;Settings;
"#;
    atomic_write_bytes(
        &applications_dir.join("caramos-updater.desktop"),
        updater_desktop.as_bytes(),
    )?;

    writeln!(
        writer,
        "{}{}✔ Đã chuẩn bị giao diện Bootloader CaramOS từ hình nền có sẵn:{}",
        ANSI_BOLD, ANSI_SAGE, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "In kết quả Bootloader".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(writer, "  • Hình nền gốc       : {}", source_wallpaper.display()).map_err(|e| {
        CaramUiError::IoFailure {
            context: "In đường dẫn hình nền gốc".to_string(),
            path: None,
            source: e,
        }
    })?;
    writeln!(writer, "  • Ảnh GRUB2 PNG      : {}", grub_bg_path.display()).map_err(|e| {
        CaramUiError::IoFailure {
            context: "In đường dẫn PNG".to_string(),
            path: None,
            source: e,
        }
    })?;
    writeln!(writer, "  • Cấu hình GRUB2     : {}", theme_txt_path.display()).map_err(|e| {
        CaramUiError::IoFailure {
            context: "In đường dẫn theme.txt".to_string(),
            path: None,
            source: e,
        }
    })?;

    Ok(source_wallpaper)
}

// ============================================================================
// 6. PHÂN HỆ 3: TRÌNH CẬP NHẬT OTA TUI TRUYỀN LUỒNG (`sha2` + `tempfile`)
// ============================================================================

pub fn compute_file_sha256(path: &Path) -> Result<String, CaramUiError> {
    validate_safe_path(path)?;
    let mut file = File::open(path).map_err(|e| CaramUiError::IoFailure {
        context: "Mở tệp để tính SHA-256".to_string(),
        path: Some(path.to_path_buf()),
        source: e,
    })?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65_536];
    loop {
        let n = file.read(&mut buf).map_err(|e| CaramUiError::IoFailure {
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

pub struct OtaUpdateRequest<'a> {
    pub root_dir: &'a Path,
    pub relative_target: &'a Path,
    pub payload_path: &'a Path,
    pub expected_sha256: &'a str,
    pub new_version: &'a str,
    pub channel: &'a str,
}

pub fn run_ota_updater_ui<W: Write>(
    req: &OtaUpdateRequest<'_>,
    writer: &mut W,
) -> Result<(), CaramUiError> {
    validate_safe_path(req.root_dir)?;
    validate_safe_path(req.relative_target)?;
    validate_safe_path(req.payload_path)?;

    if req.relative_target.is_absolute() {
        return Err(CaramUiError::UnsafePath {
            path: req.relative_target.to_path_buf(),
            reason: "Đường dẫn tệp đích trong root_dir phải là đường dẫn tương đối",
        });
    }

    let expected_clean = req.expected_sha256.trim().to_ascii_lowercase();
    if expected_clean.len() != 64 || !expected_clean.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(CaramUiError::ValidationFailed {
            field: "expected_sha256",
            value: req.expected_sha256.to_string(),
            reason: "Mã băm SHA-256 kỳ vọng phải gồm đúng 64 ký tự hex",
        });
    }

    let target_full_path = req.root_dir.join(req.relative_target);
    let short_digest = expected_clean.get(..16).unwrap_or(expected_clean.as_str());

    writeln!(
        writer,
        "\n{}{}==============================================================================\n\
               CARAMOS 2.0 — TRUNG TÂM CẬP NHẬT HỆ THỐNG NGUYÊN TỬ (OTA)\n\
         =============================================================================={}",
        ANSI_BOLD, ANSI_INDIGO, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ tiêu đề TUI Updater".to_string(),
        path: None,
        source: e,
    })?;

    writeln!(
        writer,
        "{}  • Kênh phân phối : {}{}{}\n  \
           • Phiên bản đích : {}{}{}\n  \
           • Tệp cập nhật   : {}\n  \
           • Chữ ký SHA-256 : {}...{}\n",
        ANSI_WHITE,
        ANSI_BOLD,
        req.channel,
        ANSI_WHITE,
        ANSI_SAGE,
        req.new_version,
        ANSI_WHITE,
        target_full_path.display(),
        short_digest,
        ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Hiển thị thông số gói OTA".to_string(),
        path: None,
        source: e,
    })?;

    let target_parent = target_full_path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or(req.root_dir);
    fs::create_dir_all(target_parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo thư mục cha cho tệp đích OTA".to_string(),
        path: Some(target_parent.to_path_buf()),
        source: e,
    })?;

    render_progress_bar(
        writer,
        35,
        "Truyền luồng Payload vào vùng đệm & đối chiếu SHA-256...",
    )?;

    let mut src_file = File::open(req.payload_path).map_err(|e| CaramUiError::IoFailure {
        context: "Mở tệp payload OTA".to_string(),
        path: Some(req.payload_path.to_path_buf()),
        source: e,
    })?;
    let mut staging = NamedTempFile::new_in(target_parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo tệp vùng đệm Staging OTA".to_string(),
        path: Some(target_parent.to_path_buf()),
        source: e,
    })?;
    let staging_path = staging.path().to_path_buf();

    let mut hasher = Sha256::new();
    let mut buf = [0u8; 65_536];
    loop {
        let n = src_file.read(&mut buf).map_err(|e| CaramUiError::IoFailure {
            context: "Đọc luồng gói Payload OTA".to_string(),
            path: Some(req.payload_path.to_path_buf()),
            source: e,
        })?;
        if n == 0 {
            break;
        }
        if let Some(chunk) = buf.get(..n) {
            hasher.update(chunk);
            staging.write_all(chunk).map_err(|e| CaramUiError::IoFailure {
                context: "Ghi luồng dữ liệu vào tệp đệm OTA".to_string(),
                path: Some(staging_path.clone()),
                source: e,
            })?;
        }
    }

    let actual_sha256 = hex::encode(hasher.finalize());
    if actual_sha256 != expected_clean {
        writeln!(
            writer,
            "\n{}{}✖ CẢNH BÁO BẢO MẬT: Sai lệch SHA-256! Đã hủy giao dịch nguyên tử.{}",
            ANSI_BOLD, ANSI_ROSE, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "In cảnh báo sai lệch SHA-256".to_string(),
            path: None,
            source: e,
        })?;
        return Err(CaramUiError::DigestMismatch {
            target: req.payload_path.to_path_buf(),
            expected: expected_clean,
            actual: actual_sha256,
        });
    }

    staging
        .as_file()
        .sync_all()
        .map_err(|e| CaramUiError::IoFailure {
            context: "Đồng bộ fsync vùng đệm OTA".to_string(),
            path: Some(staging_path),
            source: e,
        })?;

    if let Ok(orig_meta) = fs::metadata(&target_full_path) {
        let _ = fs::set_permissions(staging.path(), orig_meta.permissions());
    } else {
        set_unix_mode(staging.path(), 0o644)?;
    }

    render_progress_bar(writer, 65, "Tạo điểm khôi phục nguyên tử (Atomic Backup)...")?;
    let backup_path = append_filename_suffix(&target_full_path, ".caramos-ota.bak");
    let had_existing_target = target_full_path.exists();

    if had_existing_target {
        fs::copy(&target_full_path, &backup_path).map_err(|e| CaramUiError::IoFailure {
            context: "Sao lưu tệp gốc trước khi nâng cấp".to_string(),
            path: Some(backup_path.clone()),
            source: e,
        })?;
    }

    render_progress_bar(writer, 85, "Hoán đổi nguyên tử tệp đích...")?;
    if let Err(persist_err) = staging.persist(&target_full_path) {
        let io_err = persist_err.error;
        if had_existing_target && backup_path.exists() {
            if let Err(rb_err) = fs::rename(&backup_path, &target_full_path) {
                return Err(CaramUiError::RollbackFailure {
                    target: target_full_path,
                    original_err: io_err.to_string(),
                    rollback_err: rb_err,
                });
            }
        }
        return Err(CaramUiError::IoFailure {
            context: "Hoán đổi nguyên tử tệp đích OTA".to_string(),
            path: Some(target_full_path),
            source: io_err,
        });
    }

    render_progress_bar(writer, 100, "Hậu kiểm SHA-256 & Dọn dẹp bản sao lưu...")?;
    let committed_sha256 = compute_file_sha256(&target_full_path)?;
    if committed_sha256 != expected_clean {
        if had_existing_target && backup_path.exists() {
            let _ = fs::rename(&backup_path, &target_full_path);
        }
        return Err(CaramUiError::DigestMismatch {
            target: target_full_path,
            expected: expected_clean,
            actual: committed_sha256,
        });
    }

    if backup_path.exists() {
        let _ = fs::remove_file(&backup_path);
    }

    writeln!(
        writer,
        "\n{}{}✔ CẬP NHẬT HỆ THỐNG THÀNH CÔNG LÊN PHIÊN BẢN {}! (SHA-256 Verified){}",
        ANSI_BOLD, ANSI_SAGE, req.new_version, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Ghi thông báo hoàn tất OTA".to_string(),
        path: None,
        source: e,
    })?;

    Ok(())
}

// ============================================================================
// 7. HỖ TRỢ HIỂN THỊ TUI, NHẬP LIỆU THÂN THIỆN & GHI TỆP NGUYÊN TỬ
// ============================================================================

pub fn render_progress_bar<W: Write>(
    writer: &mut W,
    percentage: u8,
    label: &str,
) -> Result<(), CaramUiError> {
    let clamped = percentage.min(100);
    let total_blocks: usize = 28;
    let filled_blocks = (usize::from(clamped).saturating_mul(total_blocks)) / 100;
    let empty_blocks = total_blocks.saturating_sub(filled_blocks);

    let filled_str = "█".repeat(filled_blocks);
    let empty_str = "░".repeat(empty_blocks);

    writeln!(
        writer,
        "  {}[{}{}{}{}] {:>3}%{}  {}",
        ANSI_BOLD, ANSI_INDIGO, filled_str, ANSI_SLATE, empty_str, clamped, ANSI_RESET, label
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ thanh tiến trình TUI".to_string(),
        path: None,
        source: e,
    })
}

fn atomic_write_bytes(target_path: &Path, content: &[u8]) -> Result<(), CaramUiError> {
    validate_safe_path(target_path)?;
    let parent = target_path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::create_dir_all(parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo thư mục cha cho tệp đích".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;

    let mut tmp = NamedTempFile::new_in(parent).map_err(|e| CaramUiError::IoFailure {
        context: "Tạo tệp vùng đệm nguyên tử".to_string(),
        path: Some(parent.to_path_buf()),
        source: e,
    })?;
    let tmp_path = tmp.path().to_path_buf();

    tmp.write_all(content).map_err(|e| CaramUiError::IoFailure {
        context: "Ghi dữ liệu vào vùng đệm".to_string(),
        path: Some(tmp_path.clone()),
        source: e,
    })?;
    tmp.as_file()
        .sync_all()
        .map_err(|e| CaramUiError::IoFailure {
            context: "Đồng bộ fsync vùng đệm".to_string(),
            path: Some(tmp_path),
            source: e,
        })?;
    set_unix_mode(tmp.path(), 0o644)?;

    tmp.persist(target_path).map_err(|e| CaramUiError::IoFailure {
        context: "Hoán đổi nguyên tử tệp đích".to_string(),
        path: Some(target_path.to_path_buf()),
        source: e.error,
    })?;
    Ok(())
}

fn prompt_line_with_default(prompt: &str, default_val: &str) -> Result<String, CaramUiError> {
    let mut out = io::stdout().lock();
    write!(
        out,
        "{}{}  ? {}{} [Mặc định: {}{}{}]: ",
        ANSI_BOLD, ANSI_SKY, prompt, ANSI_RESET, ANSI_INDIGO, default_val, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Hiển thị lời nhắc nhập liệu".to_string(),
        path: None,
        source: e,
    })?;
    out.flush().map_err(|e| CaramUiError::IoFailure {
        context: "Xả bộ đệm stdout".to_string(),
        path: None,
        source: e,
    })?;

    let stdin = io::stdin();
    let mut reader = BufReader::new(stdin.lock());
    let mut line = String::new();
    reader.read_line(&mut line).map_err(|e| CaramUiError::IoFailure {
        context: "Đọc dữ liệu từ bàn phím".to_string(),
        path: None,
        source: e,
    })?;

    let trimmed = line.trim();
    if trimmed.is_empty() {
        Ok(default_val.to_string())
    } else {
        Ok(trimmed.to_string())
    }
}

fn prompt_yes_no(prompt: &str, default_yes: bool) -> Result<bool, CaramUiError> {
    let default_hint = if default_yes { "Y/n" } else { "y/N" };
    let ans = prompt_line_with_default(prompt, default_hint)?;
    let lower = ans.trim().to_ascii_lowercase();
    if lower == "y/n" || lower.is_empty() {
        return Ok(default_yes);
    }
    Ok(matches!(lower.as_str(), "y" | "yes" | "c" | "co" | "có"))
}

fn prompt_disk_friendly(default_disk: &str) -> Result<String, CaramUiError> {
    let disks = discover_physical_disks();
    let mut out = io::stdout().lock();
    writeln!(
        out,
        "\n{}{}── BƯỚC 1: CHỌN Ổ ĐĨA CÀI ĐẶT CARAMOS 2.0 ──────────────────────────────────{}",
        ANSI_BOLD, ANSI_INDIGO, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "In tiêu đề chọn ổ đĩa".to_string(),
        path: None,
        source: e,
    })?;

    if !disks.is_empty() {
        for (i, d) in disks.iter().enumerate() {
            writeln!(
                out,
                "  {}[{}]{} {:<15} | {:<8} | {}",
                ANSI_BOLD,
                i.saturating_add(1),
                ANSI_RESET,
                d.path,
                d.size,
                d.model
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "In danh sách ổ đĩa".to_string(),
                path: None,
                source: e,
            })?;
        }
    } else {
        writeln!(
            out,
            "  {}Không quét được ổ cứng vật lý (chế độ thử nghiệm). Nhập thủ công đường dẫn thiết bị.{}",
            ANSI_SLATE, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "In gợi ý chọn ổ đĩa".to_string(),
            path: None,
            source: e,
        })?;
    }
    drop(out);

    let effective_default = disks
        .first()
        .map(|d| d.path.as_str())
        .unwrap_or(default_disk);

    loop {
        let input = prompt_line_with_default(
            "Nhập số thứ tự ổ đĩa hoặc đường dẫn (vd: 1 hoặc /dev/sda)",
            effective_default,
        )?;
        let candidate = if let Ok(num) = input.parse::<usize>() {
            if let Some(idx) = num.checked_sub(1) {
                if let Some(found) = disks.get(idx) {
                    found.path.clone()
                } else {
                    let mut err_out = io::stdout().lock();
                    let _ = writeln!(
                        err_out,
                        "  {}✖ Số thứ tự không nằm trong danh sách. Hãy nhập lại.{}",
                        ANSI_ROSE, ANSI_RESET
                    );
                    continue;
                }
            } else {
                input
            }
        } else {
            input
        };

        match ValidatedBlockDevice::parse(&candidate) {
            Ok(_) => return Ok(candidate),
            Err(err) => {
                let mut err_out = io::stdout().lock();
                let _ = writeln!(err_out, "  {}✖ {}{}", ANSI_ROSE, err, ANSI_RESET);
            }
        }
    }
}

fn prompt_confirmed_password() -> Result<String, CaramUiError> {
    loop {
        let p1 = rpassword::prompt_password("  ? Nhập mật khẩu đăng nhập (ẩn khi gõ, tối thiểu 4 ký tự): ")
            .map_err(|e| CaramUiError::IoFailure {
                context: "Đọc mật khẩu ẩn từ terminal".to_string(),
                path: None,
                source: e,
            })?;

        if let Err(err) = ValidatedPassword::parse(&p1) {
            let mut out = io::stdout().lock();
            let _ = writeln!(out, "  {}✖ {}{}", ANSI_ROSE, err, ANSI_RESET);
            continue;
        }

        let p2 = rpassword::prompt_password("  ? Nhập lại mật khẩu để xác nhận: ").map_err(|e| {
            CaramUiError::IoFailure {
                context: "Đọc mật khẩu xác nhận từ terminal".to_string(),
                path: None,
                source: e,
            }
        })?;

        if p1 == p2 {
            return Ok(p1);
        }

        let mut out = io::stdout().lock();
        let _ = writeln!(
            out,
            "  {}✖ Hai lần nhập mật khẩu không khớp. Hãy nhập lại.{}",
            ANSI_ROSE, ANSI_RESET
        );
    }
}

// ============================================================================
// 8. GIAO DIỆN DÒNG LỆNH CHUẨN HÓA (`clap`)
// ============================================================================

#[derive(Debug, Parser)]
#[command(
    name = "caramos-ui",
    version,
    about = "CaramOS 2.0 Rust Installer, Bootloader Theme Stager (Reuses Existing Wallpapers), and Atomic OTA TUI"
)]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Debug, Subcommand)]
enum Commands {
    /// Trình cài đặt CaramOS 2.0 thân thiện người dùng (tạo user thường, khóa root)
    Installer {
        #[arg(long, default_value = "./build/installer_target")]
        target_root: PathBuf,
        #[arg(long, default_value = "/dev/nvme0n1")]
        disk: String,
        #[arg(long, default_value = "CaramOS User")]
        full_name: String,
        #[arg(long, default_value = "caram")]
        user: String,
        #[arg(long)]
        password: Option<String>,
        #[arg(long, default_value = "caramos-workstation")]
        hostname: String,
        #[arg(long, default_value = "Asia/Ho_Chi_Minh")]
        timezone: String,
        #[arg(long)]
        autologin: bool,
        #[arg(long)]
        interactive: bool,
        #[arg(long)]
        execute: bool,
        #[arg(long)]
        dry_run: bool,
        #[arg(long)]
        confirm_erase_disk: bool,
    },
    /// Chuẩn bị giao diện GRUB2 & Plymouth từ hình nền CaramOS có sẵn (không tự tạo ảnh nền)
    Bootloader {
        #[arg(long, default_value = "./build/ui_overlay")]
        output_root: PathBuf,
        #[arg(long)]
        wallpaper: Option<PathBuf>,
        #[arg(long, default_value = "./config/includes.chroot/usr/share/backgrounds")]
        wallpaper_search_dir: PathBuf,
        #[arg(long, default_value = "./assets")]
        assets_dir: PathBuf,
        #[arg(long, default_value_t = 1280)]
        width: u16,
        #[arg(long, default_value_t = 720)]
        height: u16,
    },
    /// Bảng điều khiển cập nhật OTA TUI kèm xác thực SHA-256 & Rollback nguyên tử
    Updater {
        #[arg(long)]
        root: Option<PathBuf>,
        #[arg(long)]
        target: Option<PathBuf>,
        #[arg(long)]
        payload: Option<PathBuf>,
        #[arg(long)]
        sha256: Option<String>,
        #[arg(long, default_value = "2.0.1")]
        version: String,
        #[arg(long, default_value = "stable")]
        channel: String,
        #[arg(long)]
        interactive: bool,
    },
}

pub fn run_cli(args: &[String]) -> Result<(), CaramUiError> {
    let _guard = TerminalSessionGuard::new(true).map_err(|e| CaramUiError::IoFailure {
        context: "Khởi tạo phiên Terminal".to_string(),
        path: None,
        source: e,
    })?;

    let mut stdout = io::stdout().lock();

    let cli = match Cli::try_parse_from(args) {
        Ok(parsed) => parsed,
        Err(err) => {
            if matches!(
                err.kind(),
                clap::error::ErrorKind::DisplayHelp | clap::error::ErrorKind::DisplayVersion
            ) {
                write!(stdout, "{}", err).map_err(|e| CaramUiError::IoFailure {
                    context: "In hướng dẫn sử dụng".to_string(),
                    path: None,
                    source: e,
                })?;
                return Ok(());
            }
            return Err(CaramUiError::InvalidCliArgument {
                argument: "cli".to_string(),
                reason: err.to_string(),
            });
        }
    };

    match cli.command {
        Commands::Installer {
            target_root,
            mut disk,
            mut full_name,
            mut user,
            password,
            mut hostname,
            mut timezone,
            mut autologin,
            interactive,
            execute,
            dry_run,
            mut confirm_erase_disk,
        } => {
            let effective_dry_run = dry_run || !execute;
            let mut effective_password = if let Some(p) = password {
                p
            } else if effective_dry_run && !interactive {
                String::from("dryrun-placeholder")
            } else {
                String::new()
            };

            let welcome = CaramInstaller::new(target_root, effective_dry_run, confirm_erase_disk)?;
            let mut tour = welcome.run_onboarding_tour(&mut stdout)?;

            if interactive {
                drop(stdout);
                disk = prompt_disk_friendly(&disk)?;

                {
                    let mut out = io::stdout().lock();
                    let _ = writeln!(
                        out,
                        "\n{}{}── BƯỚC 2: TẠO TÀI KHOẢN NGƯỜI DÙNG (KHÔNG DÙNG ROOT) ──────────────────────{}",
                        ANSI_BOLD, ANSI_INDIGO, ANSI_RESET
                    );
                }

                loop {
                    full_name = prompt_line_with_default("Họ và tên hiển thị", &full_name)?;
                    match ValidatedFullName::parse(&full_name) {
                        Ok(_) => break,
                        Err(err) => {
                            let mut out = io::stdout().lock();
                            let _ = writeln!(out, "  {}✖ {}{}", ANSI_ROSE, err, ANSI_RESET);
                        }
                    }
                }

                loop {
                    user = prompt_line_with_default(
                        "Tên đăng nhập cá nhân (chữ thường, không dùng root)",
                        &user,
                    )?;
                    match ValidatedUsername::parse(&user) {
                        Ok(_) => break,
                        Err(err) => {
                            let mut out = io::stdout().lock();
                            let _ = writeln!(out, "  {}✖ {}{}", ANSI_ROSE, err, ANSI_RESET);
                        }
                    }
                }

                effective_password = prompt_confirmed_password()?;

                loop {
                    hostname = prompt_line_with_default("Tên máy tính (Hostname)", &hostname)?;
                    match ValidatedHostname::parse(&hostname) {
                        Ok(_) => break,
                        Err(err) => {
                            let mut out = io::stdout().lock();
                            let _ = writeln!(out, "  {}✖ {}{}", ANSI_ROSE, err, ANSI_RESET);
                        }
                    }
                }

                timezone = prompt_line_with_default("Múi giờ hệ thống", &timezone)?;
                autologin = prompt_yes_no(
                    "Bật tự động đăng nhập thẳng vào Desktop cho tài khoản này?",
                    autologin,
                )?;

                {
                    let mut out = io::stdout().lock();
                    let _ = writeln!(
                        out,
                        "\n{}{}── TÓM TẮT CẤU HÌNH CÀI ĐẶT CARAMOS 2.0 ────────────────────────────────────{}\n  \
                         • Chế độ         : {}\n  \
                         • Ổ đĩa đích     : {}\n  \
                         • Họ tên         : {}\n  \
                         • Tài khoản      : {} (Người dùng thường + quyền sudo)\n  \
                         • Tài khoản root : ĐÃ KHÓA (không đăng nhập bằng root)\n  \
                         • Tự đăng nhập   : {}\n  \
                         • Tên máy tính   : {}\n  \
                         • Múi giờ        : {}",
                        ANSI_BOLD,
                        ANSI_INDIGO,
                        ANSI_RESET,
                        if effective_dry_run {
                            "MÔ PHỎNG AN TOÀN (DRY-RUN)"
                        } else {
                            "CÀI ĐẶT THẬT LÊN Ổ ĐĨA"
                        },
                        disk,
                        full_name,
                        user,
                        if autologin { "Bật" } else { "Tắt (hỏi mật khẩu)" },
                        hostname,
                        timezone
                    );
                }

                if !effective_dry_run && !confirm_erase_disk {
                    let confirm_txt = prompt_line_with_default(
                        "CẢNH BÁO: Toàn bộ dữ liệu trên ổ đĩa trên sẽ bị xóa! Gõ 'CAI DAT' để tiếp tục",
                        "HUY",
                    )?;
                    if confirm_txt.trim() == "CAI DAT" {
                        confirm_erase_disk = true;
                        tour.confirm_erase_disk = true;
                    } else {
                        return Err(CaramUiError::ValidationFailed {
                            field: "confirm_erase_disk",
                            value: confirm_txt,
                            reason: "Người dùng đã hủy quá trình cài đặt an toàn",
                        });
                    }
                }

                stdout = io::stdout().lock();
            } else if !effective_dry_run && effective_password.is_empty() {
                return Err(CaramUiError::InvalidCliArgument {
                    argument: "--password".to_string(),
                    reason: "Chế độ --execute không tương tác bắt buộc phải cung cấp --password cho tài khoản người dùng".to_string(),
                });
            }

            let disk_stage = tour.select_and_validate_disk(&disk)?;
            let acct_cfg = AccountConfig {
                full_name: &full_name,
                username: &user,
                password: &effective_password,
                hostname: &hostname,
                timezone: &timezone,
                autologin,
            };
            let user_stage = disk_stage.configure_account(&acct_cfg)?;
            let _committed = user_stage.commit_installation(&mut stdout)?;
            Ok(())
        }
        Commands::Bootloader {
            output_root,
            wallpaper,
            wallpaper_search_dir,
            assets_dir,
            width,
            height,
        } => {
            let cfg = BootloaderStageConfig {
                output_root: &output_root,
                explicit_wallpaper: wallpaper.as_deref(),
                wallpaper_search_dir: &wallpaper_search_dir,
                assets_dir: &assets_dir,
                width,
                height,
            };
            let _ = build_caramos_bootloader_theme(&cfg, &mut stdout)?;
            Ok(())
        }
        Commands::Updater {
            mut root,
            mut target,
            mut payload,
            mut sha256,
            mut version,
            mut channel,
            interactive,
        } => {
            if interactive {
                drop(stdout);
                if root.is_none() {
                    root = Some(PathBuf::from(prompt_line_with_default(
                        "Thư mục gốc hệ thống (--root)",
                        "/",
                    )?));
                }
                if target.is_none() {
                    target = Some(PathBuf::from(prompt_line_with_default(
                        "Đường dẫn tương đối tệp đích (--target)",
                        "etc/caramos-release",
                    )?));
                }
                if payload.is_none() {
                    payload = Some(PathBuf::from(prompt_line_with_default(
                        "Đường dẫn tệp gói cập nhật (--payload)",
                        "",
                    )?));
                }
                if sha256.is_none() {
                    sha256 = Some(prompt_line_with_default(
                        "Mã băm SHA-256 kỳ vọng (64 hex)",
                        "",
                    )?);
                }
                version = prompt_line_with_default("Phiên bản đích", &version)?;
                channel = prompt_line_with_default("Kênh cập nhật", &channel)?;
                stdout = io::stdout().lock();
            }

            let root_dir = root.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--root".to_string(),
                reason: "Bắt buộc cung cấp --root <DIR>".to_string(),
            })?;
            let rel_target = target.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--target".to_string(),
                reason: "Bắt buộc cung cấp --target <REL_PATH>".to_string(),
            })?;
            let payload_path = payload.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--payload".to_string(),
                reason: "Bắt buộc cung cấp --payload <FILE>".to_string(),
            })?;
            let expected_sha256 = sha256.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--sha256".to_string(),
                reason: "Bắt buộc cung cấp --sha256 <HEX_64>".to_string(),
            })?;

            let req = OtaUpdateRequest {
                root_dir: &root_dir,
                relative_target: &rel_target,
                payload_path: &payload_path,
                expected_sha256: &expected_sha256,
                new_version: &version,
                channel: &channel,
            };
            run_ota_updater_ui(&req, &mut stdout)
        }
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = env::args().collect();
    match run_cli(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "{}{}✖ {}{}", ANSI_BOLD, ANSI_ROSE, err, ANSI_RESET);
            ExitCode::from(1)
        }
    }
}

// ============================================================================
// 9. KIỂM CHỨNG ĐƠN VỊ (NON-ROOT USER, PASSWORD MASKING, ZERO PROCEDURAL BG)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use image::RgbImage;
    use tempfile::TempDir;

    #[test]
    fn test_path_traversal_defense() {
        assert!(validate_safe_path(Path::new("/tmp/safe_dir")).is_ok());
        assert!(validate_safe_path(Path::new("etc/caramos-release")).is_ok());
        assert!(validate_safe_path(Path::new("../etc/passwd")).is_err());
        assert!(validate_safe_path(Path::new("/var/lib/../../etc/shadow")).is_err());
        assert!(validate_safe_path(Path::new("")).is_err());
    }

    #[test]
    fn test_domain_types_validation_forbids_root_account() {
        assert!(ValidatedBlockDevice::parse("/dev/nvme0n1").is_ok());
        assert!(ValidatedBlockDevice::parse("/dev/sda").is_ok());
        assert!(ValidatedBlockDevice::parse("/dev/null").is_err());
        assert!(ValidatedBlockDevice::parse("/dev/sda;rm -rf /").is_err());

        assert!(ValidatedFullName::parse("Nguyễn Văn An").is_ok());
        assert!(ValidatedFullName::parse("bad:name").is_err());

        assert!(ValidatedUsername::parse("caram_user1").is_ok());
        assert!(ValidatedUsername::parse("root").is_err());
        assert!(ValidatedUsername::parse("ROOT").is_err());
        assert!(ValidatedUsername::parse("123invalid").is_err());

        assert!(ValidatedPassword::parse("123").is_err());
        assert!(ValidatedPassword::parse("caramos-2026").is_ok());

        assert!(ValidatedHostname::parse("caramos-2-trixie").is_ok());
        assert!(ValidatedHostname::parse("-invalid-start").is_err());
    }

    #[test]
    fn test_typestate_installer_standard_user_and_root_locked() -> Result<(), CaramUiError> {
        let temp_root = TempDir::new().map_err(|e| CaramUiError::IoFailure {
            context: "Tạo TempDir test installer".to_string(),
            path: None,
            source: e,
        })?;
        let mut output_log = Vec::new();

        let acct = AccountConfig {
            full_name: "Lộc CaramOS",
            username: "locshadow",
            password: "secret-password",
            hostname: "caramos-trixie",
            timezone: "Asia/Ho_Chi_Minh",
            autologin: true,
        };

        let installer = CaramInstaller::new(temp_root.path().to_path_buf(), true, false)?;
        let installer = installer.run_onboarding_tour(&mut output_log)?;
        let installer = installer.select_and_validate_disk("/dev/nvme0n1")?;
        let installer = installer.configure_account(&acct)?;
        let committed = installer.commit_installation(&mut output_log)?;
        assert_eq!(committed.slides_viewed(), 4);

        let manifest_path = temp_root.path().join("etc/caramos-install-manifest.conf");
        let manifest_text =
            fs::read_to_string(&manifest_path).map_err(|e| CaramUiError::IoFailure {
                context: "Đọc manifest kiểm thử".to_string(),
                path: Some(manifest_path),
                source: e,
            })?;
        assert!(manifest_text.contains("STANDARD_USER=\"locshadow\""));
        assert!(manifest_text.contains("ROOT_LOGIN_LOCKED=true"));
        assert!(!manifest_text.contains("secret-password"));

        let unconfirmed = CaramInstaller::new(temp_root.path().to_path_buf(), false, false)?
            .run_onboarding_tour(&mut output_log)?
            .select_and_validate_disk("/dev/nvme0n1")?
            .configure_account(&acct)?;
        assert!(unconfirmed.commit_installation(&mut output_log).is_err());

        Ok(())
    }

    #[test]
    fn test_bootloader_reuses_existing_wallpaper_without_procedural_generation(
    ) -> Result<(), CaramUiError> {
        let temp_base = TempDir::new().map_err(|e| CaramUiError::IoFailure {
            context: "Tạo TempDir test bootloader".to_string(),
            path: None,
            source: e,
        })?;
        let bg_dir = temp_base.path().join("backgrounds");
        let assets_dir = temp_base.path().join("assets");
        let out_dir = temp_base.path().join("overlay");
        fs::create_dir_all(&bg_dir).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục backgrounds test".to_string(),
            path: Some(bg_dir.clone()),
            source: e,
        })?;
        fs::create_dir_all(&assets_dir).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục assets test".to_string(),
            path: Some(assets_dir.clone()),
            source: e,
        })?;

        let mut log = Vec::new();

        let empty_cfg = BootloaderStageConfig {
            output_root: &out_dir,
            explicit_wallpaper: None,
            wallpaper_search_dir: &bg_dir,
            assets_dir: &assets_dir,
            width: 320,
            height: 240,
        };
        assert!(build_caramos_bootloader_theme(&empty_cfg, &mut log).is_err());

        let existing_bg = bg_dir.join("caramos-indigo-night.png");
        let fixture_img = RgbImage::from_pixel(64, 64, image::Rgb([15, 23, 42]));
        fixture_img
            .save_with_format(&existing_bg, ImageFormat::Png)
            .map_err(|e| CaramUiError::ImageProcessingFailed {
                path: existing_bg.clone(),
                reason: e.to_string(),
            })?;

        let valid_cfg = BootloaderStageConfig {
            output_root: &out_dir,
            explicit_wallpaper: None,
            wallpaper_search_dir: &bg_dir,
            assets_dir: &assets_dir,
            width: 320,
            height: 240,
        };
        let selected = build_caramos_bootloader_theme(&valid_cfg, &mut log)?;
        assert_eq!(selected, existing_bg);

        let staged_png = out_dir.join("boot/grub/themes/caramos/background.png");
        assert!(staged_png.is_file());
        assert!(!out_dir.join("boot/grub/themes/caramos/background.tga").exists());

        let decoded = ImageReader::open(&staged_png)
            .map_err(|e| CaramUiError::IoFailure {
                context: "Mở PNG kết quả".to_string(),
                path: Some(staged_png),
                source: e,
            })?
            .decode()
            .map_err(|e| CaramUiError::ImageProcessingFailed {
                path: out_dir.join("boot/grub/themes/caramos/background.png"),
                reason: e.to_string(),
            })?;
        assert_eq!(decoded.width(), 320);
        assert_eq!(decoded.height(), 240);

        Ok(())
    }

    #[test]
    fn test_streaming_ota_updater_success_and_reject_bad_hash() -> Result<(), CaramUiError> {
        let temp_root = TempDir::new().map_err(|e| CaramUiError::IoFailure {
            context: "Tạo TempDir test OTA".to_string(),
            path: None,
            source: e,
        })?;
        let target_rel = Path::new("etc/caramos-release");
        let target_full = temp_root.path().join(target_rel);
        atomic_write_bytes(&target_full, b"CARAMOS_VERSION=2.0.0\n")?;

        let payload_path = temp_root.path().join("payload_2_0_1.dat");
        atomic_write_bytes(&payload_path, b"CARAMOS_VERSION=2.0.1\n")?;
        let valid_hash = compute_file_sha256(&payload_path)?;
        let mut log = Vec::new();

        let bad_req = OtaUpdateRequest {
            root_dir: temp_root.path(),
            relative_target: target_rel,
            payload_path: &payload_path,
            expected_sha256: "0000000000000000000000000000000000000000000000000000000000000000",
            new_version: "2.0.1",
            channel: "stable",
        };
        assert!(run_ota_updater_ui(&bad_req, &mut log).is_err());

        let ok_req = OtaUpdateRequest {
            root_dir: temp_root.path(),
            relative_target: target_rel,
            payload_path: &payload_path,
            expected_sha256: &valid_hash,
            new_version: "2.0.1",
            channel: "stable",
        };
        run_ota_updater_ui(&ok_req, &mut log)?;

        let updated = fs::read_to_string(&target_full).map_err(|e| CaramUiError::IoFailure {
            context: "Đọc tệp sau OTA thành công".to_string(),
            path: Some(target_full),
            source: e,
        })?;
        assert_eq!(updated, "CARAMOS_VERSION=2.0.1\n");

        Ok(())
    }
}
