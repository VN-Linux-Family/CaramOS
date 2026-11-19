#![forbid(unsafe_code)]
#![deny(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::todo,
    clippy::unimplemented,
    unused_must_use
)]

//! # CaramOS 2.0 UI & System Experience Suite (`caramos-ui`)
//!
//! Cung cấp 3 phân hệ cốt lõi viết hoàn toàn bằng Rust chuẩn (`std`), đồng bộ 100% với `caramos-ctl`:
//! 1. `installer`: Trình cài đặt hệ điều hành tương tác có hình hiệu CaramOS, 4 trang giới thiệu
//!    kiến trúc Debian 13 (Trixie) & Rust Core, kiểm định ổ cứng và máy trạng thái Typestate.
//! 2. `bootloader`: Trình kết xuất đồ họa TGA 24-bit (`background.tga`), sinh giao diện
//!    GRUB2 + Plymouth và tạo biểu tượng `.desktop` cho Cinnamon Desktop trong `includes.chroot`.
//! 3. `updater`: Trình cập nhật hệ thống OTA giao diện TUI với thanh tiến trình trực quan,
//!    kiểm định SHA-256 (FIPS 180-4) và khôi phục nguyên tử (Atomic Rollback).

use std::env;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufRead, BufReader, Read, Write};
use std::marker::PhantomData;
use std::path::{Component, Path, PathBuf};

// ============================================================================
// 1. KIẾN TRÚC LỖI CHUYÊN NGHIỆP (STRUCTURED DOMAIN ERRORS)
// ============================================================================

#[derive(Debug)]
pub enum CaramUiError {
    InvalidCliArgument { argument: String, reason: String },
    ValidationFailed { field: &'static str, value: String, reason: &'static str },
    UnsafePath { path: PathBuf, reason: &'static str },
    IoFailure { context: String, path: Option<PathBuf>, source: io::Error },
    DigestMismatch { target: PathBuf, expected: String, actual: String },
    RollbackFailure { target: PathBuf, original_err: String, rollback_err: io::Error },
}

impl fmt::Display for CaramUiError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCliArgument { argument, reason } => {
                write!(f, "[CLI_ERR] Tham số '{}' không hợp lệ: {}", argument, reason)
            }
            Self::ValidationFailed { field, value, reason } => {
                write!(
                    f,
                    "[VALIDATION_ERR] Trường '{}' có giá trị '{}' bị từ chối: {}",
                    field, value, reason
                )
            }
            Self::UnsafePath { path, reason } => {
                write!(
                    f,
                    "[SECURITY_ERR] Đường dẫn '{}' bị chặn vì lý do an toàn: {}",
                    path.display(),
                    reason
                )
            }
            Self::IoFailure { context, path, source } => match path {
                Some(p) => write!(
                    f,
                    "[IO_ERR] Thao tác '{}' thất bại tại '{}': {}",
                    context,
                    p.display(),
                    source
                ),
                None => write!(f, "[IO_ERR] Thao tác '{}' thất bại: {}", context, source),
            },
            Self::DigestMismatch { target, expected, actual } => {
                write!(
                    f,
                    "[CRYPTO_ERR] Sai lệch mã băm SHA-256 tại '{}': kỳ vọng '{}', thực tế '{}'",
                    target.display(),
                    expected,
                    actual
                )
            }
            Self::RollbackFailure { target, original_err, rollback_err } => {
                write!(
                    f,
                    "[CRITICAL_OTA_ERR] Lỗi gốc ({}) VÀ lỗi khôi phục tại '{}': {}",
                    original_err,
                    target.display(),
                    rollback_err
                )
            }
        }
    }
}

impl std::error::Error for CaramUiError {}

// ============================================================================
// 2. BỘ NHẬN DIỆN THƯƠNG HIỆU & QUẢN LÝ TÀI NGUYÊN TERMINAL (RAII)
// ============================================================================

const ANSI_RESET: &str = "\x1b[0m";
const ANSI_BOLD: &str = "\x1b[1m";
const ANSI_CARAMEL: &str = "\x1b[38;5;214m";
const ANSI_AMBER: &str = "\x1b[38;5;208m";
const ANSI_CREAM: &str = "\x1b[38;5;230m";
const ANSI_EMERALD: &str = "\x1b[38;5;42m";
const ANSI_CRIMSON: &str = "\x1b[38;5;196m";
const ANSI_MUTED: &str = "\x1b[38;5;245m";
const ANSI_BG_PANEL: &str = "\x1b[48;5;235m";

pub const CARAMOS_ASCII_BANNER: &str = r#"
      ▄▄▄▄▄▄▄▄▄▄▄                                                  ▄▄▄▄▄▄▄   ▄▄▄▄▄▄▄▄▄▄▄ 
    ▄█████████████▄                                              ▄█████████▄ ███▀▀▀▀▀███ 
   ███▀         ▀███   ▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄   ▄▄▄▄▄▄▄▄▄ ███     ███ ███▄▄▄▄▄▄▄▄ 
   ███                ▀▀▀   ███  ███▀▀▀███  ▀▀▀   ███  ███▀███▀█████     ███ ▀▀▀▀▀▀▀▀███ 
   ███▄         ▄███  ▄████████  ███        ▄████████  ███ ███ █████     ███ ███▄▄▄▄▄███ 
    ▀█████████████▀  ███▄▄▄▄███  ███       ███▄▄▄▄███  ███ ███ ▀▀▀█████████▀ ███████████ 
      ▀▀▀▀▀▀▀▀▀▀▀     ▀▀▀▀▀▀▀▀▀  ▀▀▀        ▀▀▀▀▀▀▀▀▀  ▀▀▀ ▀▀▀     ▀▀▀▀▀▀▀   ▀▀▀▀▀▀▀▀▀▀▀ 
                 [ CARAMOS 2.0 — DEBIAN 13 (TRIXIE) & RUST CORE EDITION ]
"#;

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
        title: "NỀN TẢNG DEBIAN 13 (TRIXIE) TINH KHIẾT",
        subtitle: "Chấm dứt kỷ nguyên phái sinh chồng chéo 3 tầng nặng nề",
        highlights: &[
            "• Khởi tạo Rootfs trực tiếp từ kho Debian 13 thượng nguồn bằng mmdebstrap.",
            "• Loại bỏ hoàn toàn sự phụ thuộc vào ISO Ubuntu và Linux Mint dựng sẵn.",
            "• Giảm ~50% dung lượng ảnh ISO (chỉ còn ~1.3 GB), tối ưu tốc độ khởi động.",
        ],
    },
    OnboardingSlide {
        index: 2,
        total: 4,
        title: "TRÁI TIM RUST CORE & THIẾT QUÂN LUẬT BỘ NHỚ",
        subtitle: "An toàn bộ nhớ tuyệt đối từ tầng công cụ hệ thống đến nhân người dùng",
        highlights: &[
            "• Tích hợp sẵn uutils-coreutils, sudo-rs, ripgrep (rg) và fd-find.",
            "• Toàn bộ trình điều phối hệ thống tuân thủ #![forbid(unsafe_code)].",
            "• Loại bỏ 100% script Python và Bash dễ gãy trong quy trình vận hành cốt lõi.",
        ],
    },
    OnboardingSlide {
        index: 3,
        total: 4,
        title: "TRẢI NGHIỆM CINNAMON HIỆN ĐẠI & ÂM THANH PIPEWIRE",
        subtitle: "Giao diện thân thiện, hiệu năng đồ họa cao và độ trễ âm thanh cực thấp",
        highlights: &[
            "• Môi trường Desktop Cinnamon tinh chỉnh riêng với bộ chủ đề Caramel Dark.",
            "• Hạ tầng âm thanh PipeWire + WirePlumber thay thế hoàn toàn PulseAudio cũ.",
            "• Tương thích tốt trên cả phần cứng đời cũ lẫn máy trạm UEFI hiện đại.",
        ],
    },
    OnboardingSlide {
        index: 4,
        total: 4,
        title: "CẬP NHẬT OTA NGUYÊN TỬ (ATOMIC TRANSACTIONAL OTA)",
        subtitle: "Không bao giờ rơi vào trạng thái lỗi nửa vời khi mất mạng hoặc sập nguồn",
        highlights: &[
            "• Kiểm định mật mã học SHA-256 (chuẩn FIPS 180-4) trước mọi thay đổi.",
            "• Cơ chế Staging + Atomic Rename bảo đảm tính toàn vẹn tuyệt đối của /etc và hệ thống.",
            "• Tự động Rollback khôi phục 100% trạng thái gốc nếu phát hiện bất kỳ lỗi I/O nào.",
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
// 3. PHÒNG THỦ MẶC ĐỊNH: KIỂM ĐỊNH ĐẦU VÀO & ĐƯỜNG DẪN
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedBlockDevice(PathBuf);

impl ValidatedBlockDevice {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        let path = PathBuf::from(trimmed);
        validate_safe_path(&path)?;

        let allowed_prefixes = ["/dev/sd", "/dev/nvme", "/dev/vd", "/dev/mmcblk", "/dev/loop"];
        let has_valid_prefix = allowed_prefixes.iter().any(|prefix| trimmed.starts_with(prefix));
        if !has_valid_prefix || trimmed.len() <= 7 {
            return Err(CaramUiError::ValidationFailed {
                field: "target_disk",
                value: trimmed.to_string(),
                reason: "Thiết bị khối phải thuộc chuẩn /dev/sdX, /dev/nvmeXnY, /dev/vdX hoặc /dev/mmcblkX",
            });
        }

        let suffix = &trimmed[5..];
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
pub struct ValidatedUsername(String);

impl ValidatedUsername {
    pub fn parse(input: &str) -> Result<Self, CaramUiError> {
        let trimmed = input.trim();
        if trimmed.is_empty() || trimmed.len() > 32 {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Độ dài tên người dùng phải từ 1 đến 32 ký tự",
            });
        }
        if trimmed == "root" {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Không sử dụng tài khoản 'root' làm tài khoản người dùng Desktop mặc định",
            });
        }

        let mut chars = trimmed.chars();
        let first = chars.next().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "username",
            value: String::new(),
            reason: "Tên người dùng rỗng",
        })?;

        if !(first.is_ascii_lowercase() || first == '_') {
            return Err(CaramUiError::ValidationFailed {
                field: "username",
                value: trimmed.to_string(),
                reason: "Ký tự đầu tiên phải là chữ cái thường (a-z) hoặc dấu gạch dưới (_)",
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
// 4. PHÂN HỆ 1: TRÌNH CÀI ĐẶT HỆ ĐIỀU HÀNH TYPESTATE (`installer`)
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

pub struct CaramInstaller<Stage> {
    target_root: PathBuf,
    dry_run: bool,
    slides_viewed: usize,
    disk: Option<ValidatedBlockDevice>,
    layout: Option<PartitionLayoutPlan>,
    username: Option<ValidatedUsername>,
    hostname: Option<ValidatedHostname>,
    timezone: String,
    _stage: PhantomData<Stage>,
}

impl CaramInstaller<StageWelcome> {
    pub fn new(target_root: PathBuf, dry_run: bool) -> Result<Self, CaramUiError> {
        validate_safe_path(&target_root)?;
        Ok(Self {
            target_root,
            dry_run,
            slides_viewed: 0,
            disk: None,
            layout: None,
            username: None,
            hostname: None,
            timezone: String::from("Asia/Ho_Chi_Minh"),
            _stage: PhantomData,
        })
    }

    pub fn run_onboarding_tour<W: Write>(
        mut self,
        writer: &mut W,
    ) -> Result<CaramInstaller<StageTourCompleted>, CaramUiError> {
        writeln!(
            writer,
            "{}{}{}{}",
            ANSI_BOLD, ANSI_CARAMEL, CARAMOS_ASCII_BANNER, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "Hiển thị biểu trưng CaramOS".to_string(),
            path: None,
            source: e,
        })?;
        writeln!(
            writer,
            "{}  Chào mừng đến với Trình Cài Đặt Hệ Điều Hành CaramOS 2.0 (Pure Rust Engine){}",
            ANSI_CREAM, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "Hiển thị lời chào".to_string(),
            path: None,
            source: e,
        })?;

        for slide in &CARAMOS_TOUR_SLIDES {
            writeln!(
                writer,
                "\n{}{}╔══════════════════════════════════════════════════════════════════════════════╗{}",
                ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Ghi khung Slide giới thiệu".to_string(),
                path: None,
                source: e,
            })?;

            writeln!(
                writer,
                "{}{}║ [TRANG {}/{}] {:<65}║{}",
                ANSI_BOLD,
                ANSI_CARAMEL,
                slide.index,
                slide.total,
                slide.title,
                ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Ghi tiêu đề Slide".to_string(),
                path: None,
                source: e,
            })?;

            writeln!(
                writer,
                "{}║ {:<76} ║{}",
                ANSI_CREAM, slide.subtitle, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Ghi phụ đề Slide".to_string(),
                path: None,
                source: e,
            })?;

            writeln!(
                writer,
                "{}{}╠══════════════════════════════════════════════════════════════════════════════╣{}",
                ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Ghi đường phân cách Slide".to_string(),
                path: None,
                source: e,
            })?;

            for line in slide.highlights {
                writeln!(writer, "{}  {}{}", ANSI_BG_PANEL, line, ANSI_RESET).map_err(|e| {
                    CaramUiError::IoFailure {
                        context: "Ghi nội dung Slide".to_string(),
                        path: None,
                        source: e,
                    }
                })?;
            }

            writeln!(
                writer,
                "{}{}╚══════════════════════════════════════════════════════════════════════════════╝{}",
                ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
            )
            .map_err(|e| CaramUiError::IoFailure {
                context: "Đóng khung Slide".to_string(),
                path: None,
                source: e,
            })?;

            self.slides_viewed = self.slides_viewed.saturating_add(1);
        }

        Ok(CaramInstaller {
            target_root: self.target_root,
            dry_run: self.dry_run,
            slides_viewed: self.slides_viewed,
            disk: None,
            layout: None,
            username: None,
            hostname: None,
            timezone: self.timezone,
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
            slides_viewed: self.slides_viewed,
            disk: Some(device),
            layout: Some(layout),
            username: None,
            hostname: None,
            timezone: self.timezone,
            _stage: PhantomData,
        })
    }
}

impl CaramInstaller<StageDiskValidated> {
    pub fn configure_account(
        self,
        username_str: &str,
        hostname_str: &str,
        timezone_str: &str,
    ) -> Result<CaramInstaller<StageUserConfigured>, CaramUiError> {
        let username = ValidatedUsername::parse(username_str)?;
        let hostname = ValidatedHostname::parse(hostname_str)?;

        let tz_trimmed = timezone_str.trim();
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
            slides_viewed: self.slides_viewed,
            disk: self.disk,
            layout: self.layout,
            username: Some(username),
            hostname: Some(hostname),
            timezone: tz_trimmed.to_string(),
            _stage: PhantomData,
        })
    }
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
        let username = self.username.as_ref().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "username",
            value: String::new(),
            reason: "Tên người dùng bị thiếu",
        })?;
        let hostname = self.hostname.as_ref().ok_or_else(|| CaramUiError::ValidationFailed {
            field: "hostname",
            value: String::new(),
            reason: "Hostname bị thiếu",
        })?;

        writeln!(
            writer,
            "\n{}{}▶ ĐANG THỰC THI TIẾN TRÌNH CÀI ĐẶT CARAMOS 2.0 (CHẾ ĐỘ: {}){}",
            ANSI_BOLD,
            ANSI_EMERALD,
            if self.dry_run { "DRY-RUN AN TOÀN" } else { "GHI THỰC TẾ" },
            ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "In tiêu đề thực thi cài đặt".to_string(),
            path: None,
            source: e,
        })?;

        let steps = [
            (20, "Khởi tạo bảng phân vùng GPT & Phân vùng EFI (512 MiB FAT32)"),
            (45, "Định dạng phân vùng Rootfs với chuẩn ext4 (noatime, journal_checksum)"),
            (70, "Triển khai hệ thống tệp Debian 13 (Trixie) & Rust Core Stack"),
            (85, "Khởi tạo tài khoản quản trị sudo-rs, cấu hình Hostname & Locale"),
            (100, "Tích hợp giao diện Bootloader GRUB2 CaramOS & Hoàn tất đồng bộ I/O"),
        ];

        for (percent, desc) in &steps {
            render_progress_bar(writer, *percent, desc)?;
        }

        let etc_dir = self.target_root.join("etc");
        fs::create_dir_all(&etc_dir).map_err(|e| CaramUiError::IoFailure {
            context: "Khởi tạo thư mục /etc đích".to_string(),
            path: Some(etc_dir.clone()),
            source: e,
        })?;

        let hostname_path = etc_dir.join("hostname");
        atomic_write_bytes(&hostname_path, format!("{}\n", hostname.as_str()).as_bytes())?;

        let manifest_path = etc_dir.join("caramos-install-manifest.conf");
        let manifest_content = format!(
            "# CaramOS 2.0 Installation Manifest (Generated by caramos-ui)\n\
             OS_NAME=\"CaramOS 2.0 (Debian 13 Trixie - Rust Core Edition)\"\n\
             DRY_RUN={}\n\
             SLIDES_VIEWED={}\n\
             TARGET_DISK=\"{}\"\n\
             EFI_PARTITION=\"{}\"\n\
             ROOT_PARTITION=\"{}\"\n\
             FILESYSTEM=\"{}\"\n\
             ADMIN_USER=\"{}\"\n\
             HOSTNAME=\"{}\"\n\
             TIMEZONE=\"{}\"\n\
             PRIVILEGE_ENGINE=\"sudo-rs\"\n\
             COREUTILS_ENGINE=\"uutils-coreutils\"\n",
            self.dry_run,
            self.slides_viewed,
            disk.as_path().display(),
            layout.efi_partition,
            layout.root_partition,
            layout.filesystem,
            username.as_str(),
            hostname.as_str(),
            self.timezone
        );
        atomic_write_bytes(&manifest_path, manifest_content.as_bytes())?;

        writeln!(
            writer,
            "\n{}{}✔ CÀI ĐẶT HOÀN TẤT! Biên bản hệ thống đã được ghi tại: '{}'{}",
            ANSI_BOLD,
            ANSI_EMERALD,
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
            slides_viewed: self.slides_viewed,
            disk: self.disk,
            layout: self.layout,
            username: self.username,
            hostname: self.hostname,
            timezone: self.timezone,
            _stage: PhantomData,
        })
    }
}

impl CaramInstaller<StageCommitted> {
    pub fn slides_viewed(&self) -> usize {
        self.slides_viewed
    }
}

// ============================================================================
// 5. PHÂN HỆ 2: TRÌNH SINH GIAO DIỆN BOOTLOADER GRUB2, PLYMOUTH & DESKTOP SHORTCUTS
// ============================================================================

pub fn generate_caramos_tga_wallpaper(
    width: u16,
    height: u16,
) -> Result<Vec<u8>, CaramUiError> {
    if width < 64 || height < 64 || width > 3840 || height > 2160 {
        return Err(CaramUiError::ValidationFailed {
            field: "resolution",
            value: format!("{}x{}", width, height),
            reason: "Độ phân giải ảnh TGA Bootloader phải nằm trong khoảng 64x64 đến 3840x2160",
        });
    }

    let pixel_count = usize::from(width).saturating_mul(usize::from(height));
    let data_size = pixel_count.saturating_mul(3);
    let mut buffer = Vec::with_capacity(18_usize.saturating_add(data_size));

    let w_le = width.to_le_bytes();
    let h_le = height.to_le_bytes();
    let header: [u8; 18] = [
        0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0, 0, w_le[0], w_le[1], h_le[0], h_le[1], 24, 0x20,
    ];
    buffer.extend_from_slice(&header);

    let center_x = i32::from(width) / 2;
    let center_y = i32::from(height) / 2;
    let emblem_radius = i32::from(width.min(height)) / 6;
    let inner_radius = (emblem_radius.saturating_mul(3)) / 4;

    for y in 0..i32::from(height) {
        for x in 0..i32::from(width) {
            let dx = (x - center_x).abs();
            let dy = (y - center_y).abs();
            let hex_dist = dx.saturating_add(dy / 2);

            let (r, g, b) = if hex_dist <= emblem_radius && hex_dist >= inner_radius && dy <= emblem_radius {
                (245_u8, 158_u8, 11_u8)
            } else if hex_dist < inner_radius / 2 && dy < inner_radius / 2 {
                (217_u8, 119_u8, 6_u8)
            } else {
                let grad_y = (y.saturating_mul(24)) / i32::from(height).max(1);
                let grad_x = (x.saturating_mul(12)) / i32::from(width).max(1);
                let base_r = 20_u8.saturating_add(u8::try_from(grad_y).unwrap_or(0));
                let base_g = 16_u8.saturating_add(u8::try_from(grad_y / 2).unwrap_or(0));
                let base_b = 14_u8.saturating_add(u8::try_from(grad_x / 2).unwrap_or(0));
                (base_r, base_g, base_b)
            };

            buffer.push(b);
            buffer.push(g);
            buffer.push(r);
        }
    }

    Ok(buffer)
}

/// Sinh toàn bộ bộ giao diện Bootloader GRUB2, Plymouth Splash, `/etc/default/grub`
/// VÀ các biểu tượng `.desktop` cho Cinnamon Desktop trong `output_root` (`config/includes.chroot`).
pub fn build_caramos_bootloader_theme<W: Write>(
    output_root: &Path,
    width: u16,
    height: u16,
    writer: &mut W,
) -> Result<(), CaramUiError> {
    validate_safe_path(output_root)?;

    let grub_theme_dir = output_root.join("boot/grub/themes/caramos");
    let plymouth_dir = output_root.join("usr/share/plymouth/themes/caramos");
    let etc_default_dir = output_root.join("etc/default");
    let applications_dir = output_root.join("usr/share/applications");

    for dir in [&grub_theme_dir, &plymouth_dir, &etc_default_dir, &applications_dir] {
        fs::create_dir_all(dir).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục giao diện Bootloader & Desktop".to_string(),
            path: Some(dir.clone()),
            source: e,
        })?;
    }

    // 1. Kết xuất ảnh nền TGA 24-bit có biểu tượng CaramOS
    let tga_bytes = generate_caramos_tga_wallpaper(width, height)?;
    let tga_path = grub_theme_dir.join("background.tga");
    atomic_write_bytes(&tga_path, &tga_bytes)?;

    // 2. Sinh tệp cấu hình giao diện đồ họa GRUB2 (theme.txt)
    let grub_theme_txt = r#"# CaramOS 2.0 Official GRUB2 Bootloader Theme
# Generated deterministically by caramos-ui (Pure Rust)

title-text: "CaramOS 2.0 — Debian 13 (Trixie) & Rust Core Edition"
title-color: "#F59E0B"
desktop-image: "background.tga"
desktop-color: "#14110F"
terminal-box: "terminal_box_*.png"

+ label {
    top = 12%
    left = 10%
    width = 80%
    height = 36
    text = "CARAMOS 2.0  |  MEMORY-SAFE LINUX ENVIRONMENT"
    color = "#FEF3C7"
    align = "center"
}

+ boot_menu {
    left = 15%
    top = 28%
    width = 70%
    height = 48%
    item_color = "#D6D3D1"
    selected_item_color = "#F59E0B"
    item_height = 32
    item_padding = 8
    item_spacing = 6
    scrollbar = true
    scrollbar_width = 6
    scrollbar_thumb = "#F59E0B"
}

+ progress_bar {
    id = "__timeout__"
    left = 15%
    top = 82%
    width = 70%
    height = 20
    fg_color = "#F59E0B"
    bg_color = "#292524"
    border_color = "#78716C"
    text_color = "#FEF3C7"
    text = "@TIMEOUT_NOTIFICATION_LONG@"
}

+ label {
    top = 90%
    left = 10%
    width = 80%
    height = 24
    text = "[Phím mũi tên ↑/↓] Chọn nhân khởi động   |   [Enter] Khởi động   |   [E] Tuỳ chỉnh tham số"
    color = "#A8A29E"
    align = "center"
}
"#;
    let theme_txt_path = grub_theme_dir.join("theme.txt");
    atomic_write_bytes(&theme_txt_path, grub_theme_txt.as_bytes())?;

    // 3. Sinh cấu hình Plymouth Boot Splash
    let plymouth_conf = r#"[Plymouth Theme]
Name=CaramOS 2.0 Caramel Splash
Description=Official Boot Splash for CaramOS 2.0 (Debian 13 Trixie & Rust Core)
ModuleName=script

[script]
ImageDir=/usr/share/plymouth/themes/caramos
ScriptFile=/usr/share/plymouth/themes/caramos/caramos.script
"#;
    atomic_write_bytes(&plymouth_dir.join("caramos.plymouth"), plymouth_conf.as_bytes())?;

    let plymouth_script = r#"Window.SetBackgroundTopColor(0.08, 0.07, 0.06);
Window.SetBackgroundBottomColor(0.16, 0.13, 0.11);
message_sprite = Sprite();
message_sprite.SetPosition(Window.GetWidth() / 2 - 180, Window.GetHeight() / 2, 10000);
"#;
    atomic_write_bytes(&plymouth_dir.join("caramos.script"), plymouth_script.as_bytes())?;

    // 4. Sinh cấu hình /etc/default/grub (Được `caramos-ctl` bảo toàn 100% nhờ cơ chế Overlay-Last)
    let grub_default = format!(
        r#"# CaramOS 2.0 Hardened GRUB2 Configuration (Generated by caramos-ui)
GRUB_DEFAULT=0
GRUB_TIMEOUT=5
GRUB_DISTRIBUTOR="CaramOS 2.0 (Trixie)"
GRUB_CMDLINE_LINUX_DEFAULT="quiet splash loglevel=3 mitigations=auto init_on_alloc=1"
GRUB_CMDLINE_LINUX=""
GRUB_GFXMODE={}x{}x24,auto
GRUB_GFXPAYLOAD_LINUX=keep
GRUB_THEME="/boot/grub/themes/caramos/theme.txt"
"#,
        width, height
    );
    let grub_default_path = etc_default_dir.join("grub");
    atomic_write_bytes(&grub_default_path, grub_default.as_bytes())?;

    // 5. Sinh biểu tượng Desktop (.desktop) cho Trình cài đặt và Trình cập nhật OTA trên Cinnamon
    let installer_desktop = r#"[Desktop Entry]
Type=Application
Version=1.0
Name=Install CaramOS 2.0
Name[vi]=Cài đặt Hệ điều hành CaramOS 2.0
Comment=Pure-Rust Interactive OS Installer with Architecture Tour
Comment[vi]=Trình cài đặt CaramOS 2.0 có giới thiệu kiến trúc Debian 13 & Rust Core
Exec=/usr/local/bin/caramos-ui installer --interactive --execute
Icon=system-software-install
Terminal=true
Categories=System;Settings;
"#;
    let installer_desktop_path = applications_dir.join("caramos-installer.desktop");
    atomic_write_bytes(&installer_desktop_path, installer_desktop.as_bytes())?;

    let updater_desktop = r#"[Desktop Entry]
Type=Application
Version=1.0
Name=CaramOS Transactional Updater (OTA)
Name[vi]=Trung tâm Cập nhật Hệ thống CaramOS (OTA)
Comment=FIPS 180-4 SHA-256 Verified Atomic System Updater
Comment[vi]=Cập nhật hệ thống nguyên tử có kiểm định mã băm SHA-256
Exec=/usr/local/bin/caramos-ui --help
Icon=system-software-update
Terminal=true
Categories=System;Settings;
"#;
    let updater_desktop_path = applications_dir.join("caramos-updater.desktop");
    atomic_write_bytes(&updater_desktop_path, updater_desktop.as_bytes())?;

    writeln!(
        writer,
        "{}{}✔ Đã kết xuất thành công giao diện Bootloader & Biểu tượng Desktop CaramOS 2.0:{}",
        ANSI_BOLD, ANSI_EMERALD, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "In kết quả sinh Bootloader".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(writer, "  • Ảnh nền TGA 24-bit : {}", tga_path.display()).map_err(|e| {
        CaramUiError::IoFailure {
            context: "In đường dẫn TGA".to_string(),
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
    writeln!(writer, "  • Mặc định Hệ thống  : {}", grub_default_path.display()).map_err(|e| {
        CaramUiError::IoFailure {
            context: "In đường dẫn /etc/default/grub".to_string(),
            path: None,
            source: e,
        }
    })?;
    writeln!(
        writer,
        "  • Desktop Launchers  : {}, {}",
        installer_desktop_path.display(),
        updater_desktop_path.display()
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "In đường dẫn .desktop".to_string(),
        path: None,
        source: e,
    })?;

    Ok(())
}

// ============================================================================
// 6. PHÂN HỆ 3: TRÌNH CẬP NHẬT HỆ THỐNG CÓ GIAO DIỆN TUI (`updater`)
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

pub fn compute_file_sha256(path: &Path) -> Result<String, CaramUiError> {
    let mut file = File::open(path).map_err(|e| CaramUiError::IoFailure {
        context: "Mở tệp để tính SHA-256".to_string(),
        path: Some(path.to_path_buf()),
        source: e,
    })?;
    let mut hasher = Sha256Hasher::new();
    let mut buf = [0u8; 8192];
    loop {
        let n = file.read(&mut buf).map_err(|e| CaramUiError::IoFailure {
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

pub fn run_ota_updater_ui<W: Write>(
    root_dir: &Path,
    relative_target: &Path,
    payload_path: &Path,
    expected_sha256: &str,
    new_version: &str,
    channel: &str,
    writer: &mut W,
) -> Result<(), CaramUiError> {
    validate_safe_path(root_dir)?;
    validate_safe_path(relative_target)?;
    validate_safe_path(payload_path)?;

    if relative_target.is_absolute() {
        return Err(CaramUiError::UnsafePath {
            path: relative_target.to_path_buf(),
            reason: "Đường dẫn tệp đích trong root_dir phải là đường dẫn tương đối",
        });
    }

    let expected_clean = expected_sha256.trim().to_ascii_lowercase();
    if expected_clean.len() != 64 || !expected_clean.chars().all(|c| c.is_ascii_hexdigit()) {
        return Err(CaramUiError::ValidationFailed {
            field: "expected_sha256",
            value: expected_sha256.to_string(),
            reason: "Mã băm SHA-256 kỳ vọng phải gồm đúng 64 ký tự thập lục phân (hex)",
        });
    }

    let target_full_path = root_dir.join(relative_target);

    writeln!(
        writer,
        "\n{}{}╔══════════════════════════════════════════════════════════════════════════════╗{}",
        ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ khung TUI Updater".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(
        writer,
        "{}{}║          CARAMOS 2.0 — TRUNG TÂM CẬP NHẬT HỆ THỐNG NGUYÊN TỬ (OTA)           ║{}",
        ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ tiêu đề TUI Updater".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(
        writer,
        "{}{}╠══════════════════════════════════════════════════════════════════════════════╣{}",
        ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ vạch ngăn TUI Updater".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(
        writer,
        "{}  • Kênh phân phối (Channel) : {}{}{}\n  \
           • Phiên bản đích           : {}{}{}\n  \
           • Tệp hệ thống cập nhật    : {}\n  \
           • Chuẩn toàn vẹn mật mã    : FIPS 180-4 SHA-256 ({}...){}",
        ANSI_CREAM,
        ANSI_BOLD,
        channel,
        ANSI_CREAM,
        ANSI_EMERALD,
        new_version,
        ANSI_CREAM,
        target_full_path.display(),
        &expected_clean[..16],
        ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Hiển thị thông số gói OTA".to_string(),
        path: None,
        source: e,
    })?;
    writeln!(
        writer,
        "{}{}╚══════════════════════════════════════════════════════════════════════════════╝{}\n",
        ANSI_BOLD, ANSI_CARAMEL, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Đóng khung TUI Updater".to_string(),
        path: None,
        source: e,
    })?;

    render_progress_bar(writer, 25, "Đang tính toán và đối chiếu chữ ký băm SHA-256...")?;
    let actual_sha256 = compute_file_sha256(payload_path)?;
    if actual_sha256 != expected_clean {
        writeln!(
            writer,
            "\n{}{}✖ CẢNH BÁO BẢO MẬT: Phát hiện sai lệch SHA-256! Huỷ bỏ giao dịch ngay lập tức.{}",
            ANSI_BOLD, ANSI_CRIMSON, ANSI_RESET
        )
        .map_err(|e| CaramUiError::IoFailure {
            context: "In cảnh báo sai lệch SHA-256".to_string(),
            path: None,
            source: e,
        })?;
        return Err(CaramUiError::DigestMismatch {
            target: payload_path.to_path_buf(),
            expected: expected_clean,
            actual: actual_sha256,
        });
    }

    render_progress_bar(writer, 55, "Khởi tạo điểm khôi phục nguyên tử (Atomic Backup Snapshot)...")?;
    if let Some(parent) = target_full_path.parent() {
        fs::create_dir_all(parent).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục cha cho tệp đích OTA".to_string(),
            path: Some(parent.to_path_buf()),
            source: e,
        })?;
    }

    let backup_path = target_full_path.with_extension("caramos-ota.bak");
    let staging_path = target_full_path.with_extension("caramos-ota.staging");
    let had_existing_target = target_full_path.exists();

    if had_existing_target {
        fs::copy(&target_full_path, &backup_path).map_err(|e| CaramUiError::IoFailure {
            context: "Sao lưu tệp hệ thống trước khi nâng cấp".to_string(),
            path: Some(backup_path.clone()),
            source: e,
        })?;
    }

    render_progress_bar(writer, 80, "Đang nạp gói cập nhật vào vùng đệm Staging & đồng bộ I/O...")?;
    let payload_bytes = fs::read(payload_path).map_err(|e| CaramUiError::IoFailure {
        context: "Đọc nội dung gói Payload".to_string(),
        path: Some(payload_path.to_path_buf()),
        source: e,
    })?;

    if let Err(staging_err) = atomic_write_to_staging_and_rename(&staging_path, &target_full_path, &payload_bytes) {
        if had_existing_target && backup_path.exists() {
            if let Err(rb_err) = fs::rename(&backup_path, &target_full_path) {
                return Err(CaramUiError::RollbackFailure {
                    target: target_full_path,
                    original_err: staging_err.to_string(),
                    rollback_err: rb_err,
                });
            }
        }
        return Err(staging_err);
    }

    render_progress_bar(writer, 100, "Xác thực hậu kiểm (Post-Commit Verification) & Dọn dẹp...")?;
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
        ANSI_BOLD, ANSI_EMERALD, new_version, ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Ghi thông báo hoàn tất OTA".to_string(),
        path: None,
        source: e,
    })?;

    Ok(())
}

// ============================================================================
// 7. CÁC HÀM HỖ TRỢ HIỂN THỊ TUI & GHI TỆP NGUYÊN TỬ
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
        ANSI_BOLD,
        ANSI_CARAMEL,
        filled_str,
        ANSI_MUTED,
        empty_str,
        clamped,
        ANSI_RESET,
        label
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "Vẽ thanh tiến trình TUI".to_string(),
        path: None,
        source: e,
    })
}

fn atomic_write_bytes(target_path: &Path, content: &[u8]) -> Result<(), CaramUiError> {
    let staging_path = target_path.with_extension("tmp.caramos");
    atomic_write_to_staging_and_rename(&staging_path, target_path, content)
}

fn atomic_write_to_staging_and_rename(
    staging_path: &Path,
    target_path: &Path,
    content: &[u8],
) -> Result<(), CaramUiError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create(true)
        .truncate(true)
        .open(staging_path)
        .map_err(|e| CaramUiError::IoFailure {
            context: "Mở tệp vùng đệm Staging".to_string(),
            path: Some(staging_path.to_path_buf()),
            source: e,
        })?;

    file.write_all(content).map_err(|e| CaramUiError::IoFailure {
        context: "Ghi dữ liệu vào vùng đệm Staging".to_string(),
        path: Some(staging_path.to_path_buf()),
        source: e,
    })?;

    file.sync_all().map_err(|e| CaramUiError::IoFailure {
        context: "Đồng bộ fsync vùng đệm Staging xuống đĩa".to_string(),
        path: Some(staging_path.to_path_buf()),
        source: e,
    })?;

    drop(file);

    fs::rename(staging_path, target_path).map_err(|e| CaramUiError::IoFailure {
        context: "Hoán đổi nguyên tử (atomic rename) tệp đích".to_string(),
        path: Some(target_path.to_path_buf()),
        source: e,
    })
}

fn prompt_line_with_default(prompt: &str, default_val: &str) -> Result<String, CaramUiError> {
    let mut out = io::stdout().lock();
    write!(
        out,
        "{}{}  ? {}{} [Mặc định: {}{}{}]: ",
        ANSI_BOLD, ANSI_AMBER, prompt, ANSI_RESET, ANSI_CARAMEL, default_val, ANSI_RESET
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

// ============================================================================
// 8. ĐIỀU PHỐI DÒNG LỆNH (CLI ENTRYPOINT)
// ============================================================================

fn print_usage<W: Write>(writer: &mut W) -> Result<(), CaramUiError> {
    writeln!(
        writer,
        "{}{}{}{}\n\
         {}CÁCH SỬ DỤNG:{} caramos-ui <PHÂN_HỆ> [THAM_SỐ...]\n\n\
         {}CÁC PHÂN HỆ CỐT LÕI:{}\n  \
           {}1. installer{}   Trình cài đặt CaramOS 2.0 có hình hiệu giới thiệu & kiểm định Typestate\n     \
              Cú pháp: caramos-ui installer [--target-root <DIR>] [--disk <DEV>] [--user <NAME>]\n                                    \
              [--hostname <HOST>] [--timezone <TZ>] [--interactive] [--execute]\n\n  \
           {}2. bootloader{}  Trình kết xuất ảnh nền TGA 24-bit, sinh giao diện GRUB2/Plymouth & Desktop Shortcuts\n     \
              Cú pháp: caramos-ui bootloader --output-root <DIR> [--width <PX>] [--height <PX>]\n\n  \
           {}3. updater{}     Bảng điều khiển cập nhật OTA giao diện TUI kèm kiểm định SHA-256 & Rollback\n     \
              Cú pháp: caramos-ui updater --root <DIR> --target <REL_PATH> --payload <FILE>\n                                 \
              --sha256 <HEX_64> --version <VER> [--channel <stable|testing>]",
        ANSI_BOLD,
        ANSI_CARAMEL,
        CARAMOS_ASCII_BANNER,
        ANSI_RESET,
        ANSI_BOLD,
        ANSI_RESET,
        ANSI_BOLD,
        ANSI_RESET,
        ANSI_EMERALD,
        ANSI_RESET,
        ANSI_EMERALD,
        ANSI_RESET,
        ANSI_EMERALD,
        ANSI_RESET
    )
    .map_err(|e| CaramUiError::IoFailure {
        context: "In hướng dẫn sử dụng".to_string(),
        path: None,
        source: e,
    })
}

pub fn run_cli(args: &[String]) -> Result<(), CaramUiError> {
    let _guard = TerminalSessionGuard::new(true).map_err(|e| CaramUiError::IoFailure {
        context: "Khởi tạo phiên Terminal".to_string(),
        path: None,
        source: e,
    })?;

    let mut stdout = io::stdout().lock();

    let subcommand = match args.get(1).map(String::as_str) {
        Some(cmd) => cmd,
        None | Some("--help") | Some("-h") | Some("help") => {
            return print_usage(&mut stdout);
        }
    };

    match subcommand {
        "installer" => {
            let mut target_root = PathBuf::from("./build/installer_target");
            let mut disk = String::from("/dev/nvme0n1");
            let mut user = String::from("caram");
            let mut hostname = String::from("caramos-workstation");
            let mut timezone = String::from("Asia/Ho_Chi_Minh");
            let mut dry_run = true;
            let mut interactive = false;

            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--target-root" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--target-root".to_string(),
                            reason: "Thiếu đường dẫn thư mục gốc".to_string(),
                        })?;
                        target_root = PathBuf::from(val);
                    }
                    "--disk" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--disk".to_string(),
                            reason: "Thiếu đường dẫn thiết bị khối (ví dụ: /dev/sda)".to_string(),
                        })?;
                        disk.clone_from(val);
                    }
                    "--user" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--user".to_string(),
                            reason: "Thiếu tên tài khoản người dùng".to_string(),
                        })?;
                        user.clone_from(val);
                    }
                    "--hostname" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--hostname".to_string(),
                            reason: "Thiếu tên máy trạm (hostname)".to_string(),
                        })?;
                        hostname.clone_from(val);
                    }
                    "--timezone" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--timezone".to_string(),
                            reason: "Thiếu múi giờ hệ thống".to_string(),
                        })?;
                        timezone.clone_from(val);
                    }
                    "--execute" => {
                        dry_run = false;
                    }
                    "--dry-run" => {
                        dry_run = true;
                    }
                    "--interactive" => {
                        interactive = true;
                    }
                    other => {
                        return Err(CaramUiError::InvalidCliArgument {
                            argument: other.to_string(),
                            reason: "Tham số không được nhận diện trong phân hệ installer".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }

            let welcome_stage = CaramInstaller::new(target_root, dry_run)?;
            let tour_stage = welcome_stage.run_onboarding_tour(&mut stdout)?;

            if interactive {
                drop(stdout);
                disk = prompt_line_with_default("Chọn ổ cứng cài đặt CaramOS", &disk)?;
                user = prompt_line_with_default("Nhập tên tài khoản quản trị (sudo-rs)", &user)?;
                hostname = prompt_line_with_default("Nhập tên máy tính (Hostname)", &hostname)?;
                timezone = prompt_line_with_default("Nhập múi giờ hệ thống", &timezone)?;
                stdout = io::stdout().lock();
            }

            let disk_stage = tour_stage.select_and_validate_disk(&disk)?;
            let user_stage = disk_stage.configure_account(&user, &hostname, &timezone)?;
            let _committed = user_stage.commit_installation(&mut stdout)?;
            Ok(())
        }
        "bootloader" => {
            let mut output_root = PathBuf::from("./config/includes.chroot");
            let mut width: u16 = 1280;
            let mut height: u16 = 720;

            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--output-root" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--output-root".to_string(),
                            reason: "Thiếu đường dẫn thư mục đích".to_string(),
                        })?;
                        output_root = PathBuf::from(val);
                    }
                    "--width" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--width".to_string(),
                            reason: "Thiếu chiều rộng ảnh TGA".to_string(),
                        })?;
                        width = val.parse::<u16>().map_err(|_| CaramUiError::InvalidCliArgument {
                            argument: "--width".to_string(),
                            reason: "Chiều rộng phải là số nguyên dương (u16)".to_string(),
                        })?;
                    }
                    "--height" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--height".to_string(),
                            reason: "Thiếu chiều cao ảnh TGA".to_string(),
                        })?;
                        height = val.parse::<u16>().map_err(|_| CaramUiError::InvalidCliArgument {
                            argument: "--height".to_string(),
                            reason: "Chiều cao phải là số nguyên dương (u16)".to_string(),
                        })?;
                    }
                    other => {
                        return Err(CaramUiError::InvalidCliArgument {
                            argument: other.to_string(),
                            reason: "Tham số không được nhận diện trong phân hệ bootloader".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }

            build_caramos_bootloader_theme(&output_root, width, height, &mut stdout)
        }
        "updater" => {
            let mut root_dir: Option<PathBuf> = None;
            let mut rel_target: Option<PathBuf> = None;
            let mut payload_path: Option<PathBuf> = None;
            let mut expected_sha256: Option<String> = None;
            let mut version = String::from("2.0.1");
            let mut channel = String::from("stable");

            let mut idx = 2;
            while idx < args.len() {
                match args[idx].as_str() {
                    "--root" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--root".to_string(),
                            reason: "Thiếu thư mục gốc hệ thống".to_string(),
                        })?;
                        root_dir = Some(PathBuf::from(val));
                    }
                    "--target" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--target".to_string(),
                            reason: "Thiếu đường dẫn tương đối của tệp cần cập nhật".to_string(),
                        })?;
                        rel_target = Some(PathBuf::from(val));
                    }
                    "--payload" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--payload".to_string(),
                            reason: "Thiếu đường dẫn tệp gói cập nhật mới".to_string(),
                        })?;
                        payload_path = Some(PathBuf::from(val));
                    }
                    "--sha256" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--sha256".to_string(),
                            reason: "Thiếu chuỗi mã băm SHA-256 kỳ vọng".to_string(),
                        })?;
                        expected_sha256 = Some(val.clone());
                    }
                    "--version" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--version".to_string(),
                            reason: "Thiếu chuỗi phiên bản mới".to_string(),
                        })?;
                        version.clone_from(val);
                    }
                    "--channel" => {
                        idx = idx.saturating_add(1);
                        let val = args.get(idx).ok_or_else(|| CaramUiError::InvalidCliArgument {
                            argument: "--channel".to_string(),
                            reason: "Thiếu tên kênh cập nhật (stable/testing)".to_string(),
                        })?;
                        channel.clone_from(val);
                    }
                    other => {
                        return Err(CaramUiError::InvalidCliArgument {
                            argument: other.to_string(),
                            reason: "Tham số không được nhận diện trong phân hệ updater".to_string(),
                        });
                    }
                }
                idx = idx.saturating_add(1);
            }

            let root = root_dir.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--root".to_string(),
                reason: "Bắt buộc phải cung cấp --root <DIR>".to_string(),
            })?;
            let target = rel_target.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--target".to_string(),
                reason: "Bắt buộc phải cung cấp --target <REL_PATH>".to_string(),
            })?;
            let payload = payload_path.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--payload".to_string(),
                reason: "Bắt buộc phải cung cấp --payload <FILE>".to_string(),
            })?;
            let sha256 = expected_sha256.ok_or_else(|| CaramUiError::InvalidCliArgument {
                argument: "--sha256".to_string(),
                reason: "Bắt buộc phải cung cấp --sha256 <HEX_64>".to_string(),
            })?;

            run_ota_updater_ui(&root, &target, &payload, &sha256, &version, &channel, &mut stdout)
        }
        unknown => Err(CaramUiError::InvalidCliArgument {
            argument: unknown.to_string(),
            reason: "Phân hệ không tồn tại. Hãy dùng: installer, bootloader, hoặc updater".to_string(),
        }),
    }
}

fn main() -> std::process::ExitCode {
    let args: Vec<String> = env::args().collect();
    match run_cli(&args) {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(err) => {
            let mut stderr = io::stderr().lock();
            let _ = writeln!(stderr, "{}{}✖ {}{}", ANSI_BOLD, ANSI_CRIMSON, err, ANSI_RESET);
            std::process::ExitCode::from(1)
        }
    }
}

// ============================================================================
// 9. KIỂM CHỨNG ĐƠN VỊ & TRƯỜNG HỢP BIÊN (VERIFICATION & UNIT TESTS)
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn create_unique_temp_dir(test_name: &str) -> Result<PathBuf, CaramUiError> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = env::temp_dir().join(format!("caramos_ui_test_{}_{}", test_name, nanos));
        fs::create_dir_all(&dir).map_err(|e| CaramUiError::IoFailure {
            context: "Tạo thư mục tạm cho Unit Test".to_string(),
            path: Some(dir.clone()),
            source: e,
        })?;
        Ok(dir)
    }

    #[test]
    fn test_bootloader_generates_tga_grub_and_desktop_files() -> Result<(), CaramUiError> {
        let temp_root = create_unique_temp_dir("bootloader_full")?;
        let mut log = Vec::new();

        build_caramos_bootloader_theme(&temp_root, 320, 240, &mut log)?;

        assert!(temp_root.join("boot/grub/themes/caramos/background.tga").exists());
        assert!(temp_root.join("boot/grub/themes/caramos/theme.txt").exists());
        assert!(temp_root.join("etc/default/grub").exists());
        assert!(temp_root.join("usr/share/applications/caramos-installer.desktop").exists());
        assert!(temp_root.join("usr/share/applications/caramos-updater.desktop").exists());

        let _ = fs::remove_dir_all(&temp_root);
        Ok(())
    }
}
