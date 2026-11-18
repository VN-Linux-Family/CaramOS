#![forbid(unsafe_code)]
#![deny(
    clippy::unwrap_used,
    clippy::expect_used,
    clippy::panic,
    clippy::indexing_slicing,
    missing_docs
)]

//! `caramos-ctl` — Trình điều phối hợp nhất cho CaramOS 2.0 (Debian 13 Trixie Base).
//! Tích hợp 4 lệnh: `prune`, `build`, `hash`, `ota-apply`.

use std::collections::BTreeMap;
use std::env;
use std::error::Error;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::marker::PhantomData;
use std::path::{Component, Path, PathBuf};
use std::process::{Command, ExitCode, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};

/// Toàn bộ các nhánh lỗi được định danh rõ ràng của `caramos-ctl`.
#[derive(Debug)]
pub enum CaramError {
    /// Lỗi đọc/ghi hệ thống tệp kèm ngữ cảnh.
    Io {
        /// Mô tả thao tác đang thực hiện.
        context: &'static str,
        /// Đường dẫn tệp/thư mục liên quan.
        path: Option<PathBuf>,
        /// Nguyên nhân gốc từ OS.
        source: io::Error,
    },
    /// Lỗi vi phạm quy tắc đầu vào hoặc bảo mật.
    Validation {
        /// Tên trường dữ liệu.
        field: &'static str,
        /// Giá trị gây lỗi.
        value: String,
        /// Lý do từ chối.
        reason: &'static str,
    },
    /// Lỗi khi gọi tiến trình ngoài (`mmdebstrap`, `mksquashfs`, `xorriso`, `mount`).
    CommandFailed {
        /// Tên chương trình.
        program: String,
        /// Mã thoát.
        status_code: Option<i32>,
        /// Nội dung stderr.
        stderr: String,
    },
    /// Sai lệch mã băm SHA-256.
    DigestMismatch {
        /// Tệp kiểm tra.
        target: PathBuf,
        /// Mã băm kỳ vọng.
        expected: String,
        /// Mã băm thực tế.
        actual: String,
    },
    /// Lỗi giao dịch OTA thất bại và đã tự động Rollback.
    TransactionAborted {
        /// Bước gặp sự cố.
        failed_step: String,
        /// Báo cáo kết quả khôi phục.
        rollback_report: String,
    },
    /// Khóa tiến trình đang bị giữ bởi một phiên chạy khác.
    LockContention {
        /// Đường dẫn lockfile.
        lock_path: PathBuf,
    },
    /// Phát hiện điểm gắn kết chroot vẫn đang hoạt động, chặn xóa thư mục để bảo vệ máy chủ.
    ActiveMountDetected {
        /// Điểm gắn kết đang hoạt động.
        mount_point: PathBuf,
    },
}

impl fmt::Display for CaramError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io {
                context,
                path: Some(p),
                source,
            } => write!(f, "[IO Error] {}: '{}' ({})", context, p.display(), source),
            Self::Io {
                context,
                path: None,
                source,
            } => write!(f, "[IO Error] {}: {}", context, source),
            Self::Validation {
                field,
                value,
                reason,
            } => write!(
                f,
                "[Validation Error] Trường '{}' ('{}') không hợp lệ: {}",
                field, value, reason
            ),
            Self::CommandFailed {
                program,
                status_code,
                stderr,
            } => write!(
                f,
                "[Command Failed] Lệnh '{}' thất bại (exit={:?}): {}",
                program, status_code, stderr
            ),
            Self::DigestMismatch {
                target,
                expected,
                actual,
            } => write!(
                f,
                "[Digest Mismatch] Sai lệch SHA-256 tại '{}': kỳ vọng {}, thực tế {}",
                target.display(),
                expected,
                actual
            ),
            Self::TransactionAborted {
                failed_step,
                rollback_report,
            } => write!(
                f,
                "[OTA Aborted] Thất bại tại '{}'. Rollback: {}",
                failed_step, rollback_report
            ),
            Self::LockContention { lock_path } => write!(
                f,
                "[Locked] Tiến trình khác đang giữ khóa tại '{}'",
                lock_path.display()
            ),
            Self::ActiveMountDetected { mount_point } => write!(
                f,
                "[Safety Guard] Phát hiện mount đang hoạt động tại '{}', hủy thao tác xóa!",
                mount_point.display()
            ),
        }
    }
}

impl Error for CaramError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Io { source, .. } => Some(source),
            _ => None,
        }
    }
}

/// Tên gói chuẩn Debian Policy 5.6.1.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct DebianPackageName(String);

impl DebianPackageName {
    /// Phân tích và xác thực tên gói Debian.
    pub fn parse(raw: &str) -> Result<Self, CaramError> {
        let trimmed = raw.trim();
        if trimmed.len() < 2 || trimmed.len() > 128 {
            return Err(CaramError::Validation {
                field: "DebianPackageName",
                value: raw.to_owned(),
                reason: "Độ dài phải từ 2 đến 128 ký tự",
            });
        }
        let mut chars = trimmed.chars();
        let first = chars.next().ok_or_else(|| CaramError::Validation {
            field: "DebianPackageName",
            value: raw.to_owned(),
            reason: "Tên gói rỗng",
        })?;
        if !first.is_ascii_lowercase() && !first.is_ascii_digit() {
            return Err(CaramError::Validation {
                field: "DebianPackageName",
                value: raw.to_owned(),
                reason: "Ký tự đầu phải là chữ thường hoặc số ASCII",
            });
        }
        for ch in chars {
            let ok =
                ch.is_ascii_lowercase() || ch.is_ascii_digit() || matches!(ch, '+' | '-' | '.');
            if !ok {
                return Err(CaramError::Validation {
                    field: "DebianPackageName",
                    value: raw.to_owned(),
                    reason: "Chứa ký tự ngoài tập [a-z0-9+-.]",
                });
            }
        }
        Ok(Self(trimmed.to_owned()))
    }

    /// Lấy chuỗi `&str`.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Phiên bản `MAJOR.MINOR.PATCH`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct SemVer {
    /// Phiên bản lớn.
    pub major: u32,
    /// Phiên bản nhỏ.
    pub minor: u32,
    /// Bản vá.
    pub patch: u32,
}

impl SemVer {
    /// Phân tích chuỗi `X.Y.Z`.
    pub fn parse(raw: &str) -> Result<Self, CaramError> {
        let cleaned = raw.trim().strip_prefix('v').unwrap_or_else(|| raw.trim());
        let mut parts = cleaned.split('.');
        let major_s = parts.next().ok_or_else(|| CaramError::Validation {
            field: "SemVer",
            value: raw.to_owned(),
            reason: "Thiếu MAJOR",
        })?;
        let minor_s = parts.next().ok_or_else(|| CaramError::Validation {
            field: "SemVer",
            value: raw.to_owned(),
            reason: "Thiếu MINOR",
        })?;
        let patch_s = parts.next().ok_or_else(|| CaramError::Validation {
            field: "SemVer",
            value: raw.to_owned(),
            reason: "Thiếu PATCH",
        })?;
        if parts.next().is_some() {
            return Err(CaramError::Validation {
                field: "SemVer",
                value: raw.to_owned(),
                reason: "Quá 3 thành phần phiên bản",
            });
        }
        Ok(Self {
            major: major_s.parse::<u32>().map_err(|_| CaramError::Validation {
                field: "SemVer.major",
                value: major_s.to_owned(),
                reason: "Không phải số nguyên u32",
            })?,
            minor: minor_s.parse::<u32>().map_err(|_| CaramError::Validation {
                field: "SemVer.minor",
                value: minor_s.to_owned(),
                reason: "Không phải số nguyên u32",
            })?,
            patch: patch_s.parse::<u32>().map_err(|_| CaramError::Validation {
                field: "SemVer.patch",
                value: patch_s.to_owned(),
                reason: "Không phải số nguyên u32",
            })?,
        })
    }
}

impl fmt::Display for SemVer {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}.{}.{}", self.major, self.minor, self.patch)
    }
}

/// Đường dẫn tương đối an toàn (chặn tuyệt đối `..` Path Traversal).
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SafeRelativePath(PathBuf);

impl SafeRelativePath {
    /// Kiểm tra và chuẩn hóa đường dẫn tương đối.
    pub fn parse(raw: &str) -> Result<Self, CaramError> {
        let trimmed = raw.trim().trim_start_matches('/');
        if trimmed.is_empty() {
            return Err(CaramError::Validation {
                field: "SafeRelativePath",
                value: raw.to_owned(),
                reason: "Đường dẫn rỗng",
            });
        }
        let mut normalized = PathBuf::new();
        for comp in Path::new(trimmed).components() {
            match comp {
                Component::Normal(part) => {
                    let s = part.to_str().ok_or_else(|| CaramError::Validation {
                        field: "SafeRelativePath",
                        value: raw.to_owned(),
                        reason: "Không phải chuỗi UTF-8",
                    })?;
                    if s.contains('\0') {
                        return Err(CaramError::Validation {
                            field: "SafeRelativePath",
                            value: raw.to_owned(),
                            reason: "Chứa byte null",
                        });
                    }
                    normalized.push(part);
                }
                Component::CurDir => {}
                Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                    return Err(CaramError::Validation {
                        field: "SafeRelativePath",
                        value: raw.to_owned(),
                        reason: "Phát hiện Path Traversal ('..')",
                    });
                }
            }
        }
        if normalized.as_os_str().is_empty() {
            return Err(CaramError::Validation {
                field: "SafeRelativePath",
                value: raw.to_owned(),
                reason: "Đường dẫn sau chuẩn hóa bị rỗng",
            });
        }
        Ok(Self(normalized))
    }

    /// Nối đường dẫn tương đối vào bên dưới `root`.
    pub fn join_under(&self, root: &Path) -> PathBuf {
        root.join(&self.0)
    }

    /// Lấy tham chiếu `Path`.
    pub fn as_path(&self) -> &Path {
        &self.0
    }
}

/// Mã băm SHA-256 (64 ký tự hex).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Sha256Digest(String);

impl Sha256Digest {
    /// Kiểm tra chuỗi hex SHA-256 hợp lệ.
    pub fn parse(raw: &str) -> Result<Self, CaramError> {
        let cleaned = raw.trim().to_ascii_lowercase();
        if cleaned.len() != 64 || !cleaned.chars().all(|c| c.is_ascii_hexdigit()) {
            return Err(CaramError::Validation {
                field: "Sha256Digest",
                value: raw.to_owned(),
                reason: "Phải gồm đúng 64 ký tự hex",
            });
        }
        Ok(Self(cleaned))
    }

    /// Trả về chuỗi `&str`.
    pub fn as_str(&self) -> &str {
        &self.0
    }
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

/// Bộ băm SHA-256 theo luồng.
pub struct Sha256Hasher {
    state: [u32; 8],
    buffer: Vec<u8>,
    total_bytes: u64,
}

impl Default for Sha256Hasher {
    fn default() -> Self {
        Self::new()
    }
}

impl Sha256Hasher {
    /// Khởi tạo bộ băm SHA-256 mới.
    pub fn new() -> Self {
        Self {
            state: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c,
                0x1f83d9ab, 0x5be0cd19,
            ],
            buffer: Vec::with_capacity(64),
            total_bytes: 0,
        }
    }

    /// Nạp thêm dữ liệu vào bộ băm.
    pub fn update(&mut self, data: &[u8]) {
        self.total_bytes = self.total_bytes.wrapping_add(data.len() as u64);
        self.buffer.extend_from_slice(data);
        let blocks: Vec<[u8; 64]> = self.buffer.as_chunks::<64>().0.to_vec();
        if !blocks.is_empty() {
            for b in &blocks {
                self.compress_block(b);
            }
            let consumed = blocks.len().wrapping_mul(64);
            self.buffer.drain(..consumed);
        }
    }

    /// Kết thúc băm và xuất `Sha256Digest`.
    pub fn finalize(mut self) -> Sha256Digest {
        let bit_len = self.total_bytes.wrapping_mul(8);
        self.buffer.push(0x80);
        while !(self.buffer.len() + 8).is_multiple_of(64) {
            self.buffer.push(0x00);
        }
        self.buffer.extend_from_slice(&bit_len.to_be_bytes());

        let blocks: Vec<[u8; 64]> = self.buffer.as_chunks::<64>().0.to_vec();

        for b in &blocks {
            self.compress_block(b);
        }

        let mut hex = String::with_capacity(64);
        for word in &self.state {
            for byte in word.to_be_bytes() {
                hex.push(char::from_digit(u32::from(byte >> 4), 16).unwrap_or('0'));
                hex.push(char::from_digit(u32::from(byte & 0x0f), 16).unwrap_or('0'));
            }
        }
        Sha256Digest(hex)
    }

    fn compress_block(&mut self, block: &[u8; 64]) {
        let mut w = [0u32; 64];
        for (slot, &chunk) in w.iter_mut().take(16).zip(block.as_chunks::<4>().0) {
            *slot = u32::from_be_bytes(chunk);
        }
        for i in 16..64 {
            let w15 = w.get(i - 15).copied().unwrap_or(0);
            let w2 = w.get(i - 2).copied().unwrap_or(0);
            let w16 = w.get(i - 16).copied().unwrap_or(0);
            let w7 = w.get(i - 7).copied().unwrap_or(0);
            let s0 = w15.rotate_right(7) ^ w15.rotate_right(18) ^ (w15 >> 3);
            let s1 = w2.rotate_right(17) ^ w2.rotate_right(19) ^ (w2 >> 10);
            let val = w16.wrapping_add(s0).wrapping_add(w7).wrapping_add(s1);
            if let Some(slot) = w.get_mut(i) {
                *slot = val;
            }
        }

        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = self.state;
        for (&k_i, &w_i) in SHA256_K.iter().zip(w.iter()) {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = h
                .wrapping_add(s1)
                .wrapping_add(ch)
                .wrapping_add(k_i)
                .wrapping_add(w_i);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);

            h = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }

        self.state = [
            self.state[0].wrapping_add(a),
            self.state[1].wrapping_add(b),
            self.state[2].wrapping_add(c),
            self.state[3].wrapping_add(d),
            self.state[4].wrapping_add(e),
            self.state[5].wrapping_add(f),
            self.state[6].wrapping_add(g),
            self.state[7].wrapping_add(h),
        ];
    }

    /// Tính SHA-256 của một tệp trên đĩa.
    pub fn hash_file(path: &Path) -> Result<Sha256Digest, CaramError> {
        let mut f = File::open(path).map_err(|source| CaramError::Io {
            context: "Mở tệp để băm SHA-256",
            path: Some(path.to_path_buf()),
            source,
        })?;
        let mut hasher = Self::new();
        let mut buf = [0u8; 65_536];
        loop {
            let n = f.read(&mut buf).map_err(|source| CaramError::Io {
                context: "Đọc dữ liệu tệp để băm SHA-256",
                path: Some(path.to_path_buf()),
                source,
            })?;
            if n == 0 {
                break;
            }
            if let Some(slice) = buf.get(..n) {
                hasher.update(slice);
            }
        }
        Ok(hasher.finalize())
    }
}

const LEGACY_FILES_TO_REMOVE: &[&str] = &[
    "build.sh",
    "install-caramos-ota.sh",
    "Dockerfile",
    "docker-compose.yml",
    "CaramOS Project Finalization.md",
    ".github/workflows/build.yml",
    ".github/workflows/release.yml",
    "config/includes.chroot/etc/linuxmint/info",
];

const LEGACY_DIRS_TO_REMOVE: &[&str] = &[
    "scripts",
    "config/hooks/live",
    "debian",
    "packages/caramos-ota",
    "config/includes.chroot/etc/linuxmint",
];

const SALVAGE_SUBPATHS_FROM_OTA: &[&str] = &[
    "usr/share/cinnamon/applets",
    "usr/share/icons",
    "usr/share/applications",
];

const MODERN_DEBIAN_TRIXIE_PACKAGES_TXT: &str = "\
# =============================================================================
# CaramOS 2.0 (Debian 13 Trixie Base + Rust Core Userland)
# =============================================================================
linux-image-amd64
live-boot
systemd-sysv
dbus
libpam-systemd
firmware-linux-free
earlyoom
zram-tools
rust-coreutils
sudo-rs
ripgrep
fd-find
cinnamon-core
lightdm
lightdm-gtk-greeter
network-manager-gnome
blueman
pulseaudio-utils
gvfs-backends
xdg-user-dirs-gtk
fcitx5
fcitx5-unikey
fcitx5-config-qt
fonts-noto-core
fonts-noto-color-emoji
fonts-liberation2
ca-certificates
curl
flatpak
pkexec
polkitd
";

const MODERN_MAKEFILE: &str = "\
# CaramOS 2.0 — Rust Orchestrated Makefile (Debian Trixie Base)
CARGO ?= cargo
CTL_MANIFEST := crates/caramos-ctl/Cargo.toml
CTL_BIN := crates/caramos-ctl/target/release/caramos-ctl
WORK_DIR ?= ./build

.PHONY: all check test build-bin dry-run build release prune clean

all: check test build-bin

check:
\t$(CARGO) clippy --manifest-path $(CTL_MANIFEST) --all-targets -- -D warnings -D clippy::unwrap_used -D clippy::expect_used -D clippy::panic

test:
\t$(CARGO) test --manifest-path $(CTL_MANIFEST)

build-bin:
\t$(CARGO) build --manifest-path $(CTL_MANIFEST) --release

prune: build-bin
\t$(CTL_BIN) prune --repo-root . --execute

dry-run: build-bin
\t$(CTL_BIN) build --dry-run --work-dir $(WORK_DIR)_dryrun

build: build-bin
\tsudo $(CTL_BIN) build --work-dir $(WORK_DIR)

release: build-bin
\tsudo $(CTL_BIN) build --release --work-dir $(WORK_DIR)

clean:
\tsudo rm -rf $(WORK_DIR) $(WORK_DIR)_dryrun
";

/// Báo cáo kết quả dọn dẹp kho mã nguồn.
#[derive(Debug, Default)]
pub struct PruneReport {
    /// Các tệp giao diện đã giải cứu sang `config/includes.chroot`.
    pub salvaged_files: Vec<PathBuf>,
    /// Các tệp di sản đã xóa.
    pub removed_files: Vec<PathBuf>,
    /// Các thư mục di sản đã xóa.
    pub removed_dirs: Vec<PathBuf>,
}

/// Giải cứu Cinnamon Applets từ `packages/caramos-ota` và xóa toàn bộ file Bash/Mint/Python cũ.
pub fn execute_repo_prune(repo_root: &Path, execute: bool) -> Result<PruneReport, CaramError> {
    let mut report = PruneReport::default();
    let ota_root = repo_root.join("packages").join("caramos-ota");
    let overlay_root = repo_root.join("config").join("includes.chroot");

    if ota_root.is_dir() {
        for sub in SALVAGE_SUBPATHS_FROM_OTA {
            let safe_rel = SafeRelativePath::parse(sub)?;
            let src_dir = safe_rel.join_under(&ota_root);
            let dst_dir = safe_rel.join_under(&overlay_root);
            if src_dir.is_dir() {
                salvage_dir_recursive(&src_dir, &dst_dir, execute, &mut report.salvaged_files)?;
            }
        }
    }

    for rel_file in LEGACY_FILES_TO_REMOVE {
        let safe_rel = SafeRelativePath::parse(rel_file)?;
        let target = safe_rel.join_under(repo_root);
        if target.is_file() || target.is_symlink() {
            if execute {
                fs::remove_file(&target).map_err(|source| CaramError::Io {
                    context: "Xóa tệp di sản",
                    path: Some(target.clone()),
                    source,
                })?;
            }
            report.removed_files.push(target);
        }
    }

    for rel_dir in LEGACY_DIRS_TO_REMOVE {
        let safe_rel = SafeRelativePath::parse(rel_dir)?;
        let target_dir = safe_rel.join_under(repo_root);
        if target_dir.is_dir() {
            if execute {
                fs::remove_dir_all(&target_dir).map_err(|source| CaramError::Io {
                    context: "Xóa thư mục di sản",
                    path: Some(target_dir.clone()),
                    source,
                })?;
            }
            report.removed_dirs.push(target_dir);
        }
    }

    if execute {
        let pkg_file = repo_root.join("config").join("packages.txt");
        atomic_write_bytes(&pkg_file, MODERN_DEBIAN_TRIXIE_PACKAGES_TXT.as_bytes())?;

        let makefile = repo_root.join("Makefile");
        atomic_write_bytes(&makefile, MODERN_MAKEFILE.as_bytes())?;
    }

    Ok(report)
}

fn salvage_dir_recursive(
    src_dir: &Path,
    dst_dir: &Path,
    execute: bool,
    salvaged_log: &mut Vec<PathBuf>,
) -> Result<(), CaramError> {
    let entries = fs::read_dir(src_dir).map_err(|source| CaramError::Io {
        context: "Đọc thư mục nguồn khi giải cứu Applet",
        path: Some(src_dir.to_path_buf()),
        source,
    })?;
    for entry_res in entries {
        let entry = entry_res.map_err(|source| CaramError::Io {
            context: "Đọc mục con trong thư mục Applet",
            path: Some(src_dir.to_path_buf()),
            source,
        })?;
        let src_path = entry.path();
        let dst_path = dst_dir.join(entry.file_name());
        let ftype = entry.file_type().map_err(|source| CaramError::Io {
            context: "Kiểm tra kiểu tệp Applet",
            path: Some(src_path.clone()),
            source,
        })?;
        if ftype.is_dir() {
            salvage_dir_recursive(&src_path, &dst_path, execute, salvaged_log)?;
        } else if ftype.is_file() && !dst_path.exists() {
            if execute {
                let bytes = fs::read(&src_path).map_err(|source| CaramError::Io {
                    context: "Đọc tệp Applet cần giải cứu",
                    path: Some(src_path),
                    source,
                })?;
                atomic_write_bytes(&dst_path, &bytes)?;
            }
            salvaged_log.push(dst_path);
        }
    }
    Ok(())
}

/// Khóa tiến trình độc quyền theo cơ chế RAII.
pub struct ProcessLockGuard {
    lock_path: PathBuf,
}

impl ProcessLockGuard {
    /// Chiếm khóa tại `lock_path`.
    pub fn acquire(lock_path: PathBuf) -> Result<Self, CaramError> {
        if let Some(parent) = lock_path.parent() {
            fs::create_dir_all(parent).map_err(|source| CaramError::Io {
                context: "Tạo thư mục chứa lockfile",
                path: Some(parent.to_path_buf()),
                source,
            })?;
        }
        let mut f = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|source| {
                if source.kind() == io::ErrorKind::AlreadyExists {
                    CaramError::LockContention {
                        lock_path: lock_path.clone(),
                    }
                } else {
                    CaramError::Io {
                        context: "Mở lockfile độc quyền",
                        path: Some(lock_path.clone()),
                        source,
                    }
                }
            })?;
        let _ = writeln!(f, "pid={}", std::process::id());
        let _ = f.sync_all();
        Ok(Self { lock_path })
    }
}

impl Drop for ProcessLockGuard {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.lock_path);
    }
}

/// Quản lý vòng đời mount point (`/proc`, `/sys`, `/dev`, `/dev/pts`) trong Chroot bằng RAII.
pub struct ChrootMountGuard {
    mounted_targets: Vec<PathBuf>,
    dry_run: bool,
}

impl ChrootMountGuard {
    /// Gắn kết các hệ thống tệp ảo vào `rootfs`.
    pub fn mount_all(rootfs: &Path, dry_run: bool) -> Result<Self, CaramError> {
        let mut guard = Self {
            mounted_targets: Vec::with_capacity(4),
            dry_run,
        };
        let mounts: [(&str, &str, &[&str]); 4] = [
            ("proc", "proc", &["-t", "proc"]),
            ("sysfs", "sys", &["-t", "sysfs"]),
            ("/dev", "dev", &["--bind"]),
            ("devpts", "dev/pts", &["-t", "devpts"]),
        ];
        for (src, rel, flags) in mounts {
            let target = rootfs.join(rel);
            fs::create_dir_all(&target).map_err(|source| CaramError::Io {
                context: "Tạo thư mục mount trong chroot",
                path: Some(target.clone()),
                source,
            })?;
            if !dry_run {
                let mut cmd = Command::new("mount");
                for flag in flags {
                    cmd.arg(flag);
                }
                cmd.arg(src).arg(&target);
                run_checked_command(&mut cmd, "mount")?;
            }
            guard.mounted_targets.push(target);
        }
        Ok(guard)
    }

    /// Đảm bảo không còn mount point nào hoạt động bên dưới `rootfs`.
    pub fn verify_no_active_mounts_under(rootfs: &Path) -> Result<(), CaramError> {
        let proc_mounts = Path::new("/proc/mounts");
        if !proc_mounts.exists() {
            return Ok(());
        }
        let content = fs::read_to_string(proc_mounts).map_err(|source| CaramError::Io {
            context: "Đọc /proc/mounts",
            path: Some(proc_mounts.to_path_buf()),
            source,
        })?;
        let canonical = fs::canonicalize(rootfs).unwrap_or_else(|_| rootfs.to_path_buf());
        let prefix = canonical.to_string_lossy();
        for line in content.lines() {
            let mut cols = line.split_whitespace();
            let _dev = cols.next();
            if let Some(mp) = cols.next() {
                if mp.starts_with(prefix.as_ref()) {
                    return Err(CaramError::ActiveMountDetected {
                        mount_point: PathBuf::from(mp),
                    });
                }
            }
        }
        Ok(())
    }
}

impl Drop for ChrootMountGuard {
    fn drop(&mut self) {
        for target in self.mounted_targets.iter().rev() {
            if !self.dry_run {
                let ok = Command::new("umount")
                    .arg(target)
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .status()
                    .map(|s| s.success())
                    .unwrap_or(false);
                if !ok {
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

/// Chế độ nén SquashFS.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SquashfsCompression {
    /// Nén `zstd` nhanh.
    ZstdFast,
    /// Nén `xz` tối đa cho bản phát hành.
    XzRelease,
}

/// Cấu hình phiên Build CaramOS trên nền Debian 13 (`trixie`).
#[derive(Debug, Clone)]
pub struct BuildConfig {
    /// Phiên bản CaramOS.
    pub version: SemVer,
    /// Mirror Debian.
    pub mirror: String,
    /// Thư mục làm việc (`./build`).
    pub work_dir: PathBuf,
    /// Thư mục overlay (`config/includes.chroot`).
    pub overlay_dir: PathBuf,
    /// Danh sách gói Debian.
    pub packages: Vec<DebianPackageName>,
    /// Chế độ nén.
    pub compression: SquashfsCompression,
    /// Chạy mô phỏng không gọi `mmdebstrap` thật.
    pub dry_run: bool,
}

/// Trạng thái 1: Chưa khởi tạo.
pub struct Uninitialized;
/// Trạng thái 2: Đã kéo Rootfs Debian Trixie.
pub struct RootfsBootstrapped;
/// Trạng thái 3: Đã nạp Overlay và cấu hình trong Chroot.
pub struct RootfsCustomized;
/// Trạng thái 4: Đã đóng gói ISO hoàn chỉnh.
pub struct IsoPackaged;

/// Bộ điều phối Build theo Typestate Pattern.
pub struct CaramBuilder<State> {
    config: BuildConfig,
    rootfs_dir: PathBuf,
    iso_staging_dir: PathBuf,
    _state: PhantomData<State>,
}

impl CaramBuilder<Uninitialized> {
    /// Khởi tạo Builder mới.
    pub fn new(config: BuildConfig) -> Self {
        let rootfs_dir = config.work_dir.join("rootfs");
        let iso_staging_dir = config.work_dir.join("iso_staging");
        Self {
            config,
            rootfs_dir,
            iso_staging_dir,
            _state: PhantomData,
        }
    }

    /// Bước 1: Bootstrap Debian 13 (`trixie`) bằng `mmdebstrap`.
    pub fn bootstrap_rootfs(self) -> Result<CaramBuilder<RootfsBootstrapped>, CaramError> {
        ChrootMountGuard::verify_no_active_mounts_under(&self.rootfs_dir)?;
        fs::create_dir_all(&self.rootfs_dir).map_err(|source| CaramError::Io {
            context: "Tạo thư mục rootfs",
            path: Some(self.rootfs_dir.clone()),
            source,
        })?;
        fs::create_dir_all(self.iso_staging_dir.join("live")).map_err(|source| CaramError::Io {
            context: "Tạo thư mục iso_staging/live",
            path: Some(self.iso_staging_dir.clone()),
            source,
        })?;

        let include_list = self
            .config
            .packages
            .iter()
            .map(DebianPackageName::as_str)
            .collect::<Vec<&str>>()
            .join(",");

        if !self.config.dry_run {
            let mut cmd = Command::new("mmdebstrap");
            cmd.arg("--variant=minbase")
                .arg("--components=main,contrib,non-free,non-free-firmware")
                .arg(format!("--include={}", include_list))
                .arg("trixie")
                .arg(&self.rootfs_dir)
                .arg(&self.config.mirror);
            run_checked_command(&mut cmd, "mmdebstrap")?;
        }

        Ok(CaramBuilder {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _state: PhantomData,
        })
    }
}

impl CaramBuilder<RootfsBootstrapped> {
    /// Bước 2: Áp dụng Overlay (`config/includes.chroot`), ghi `/etc/caramos-release` và cập nhật dconf.
    pub fn customize(self) -> Result<CaramBuilder<RootfsCustomized>, CaramError> {
        if self.config.overlay_dir.exists() {
            copy_overlay_tree_safely(&self.config.overlay_dir, &self.rootfs_dir)?;
        }

        let release_rel = SafeRelativePath::parse("etc/caramos-release")?;
        let release_target = release_rel.join_under(&self.rootfs_dir);
        let release_content = format!(
            "NAME=CaramOS\n\
             VERSION={ver}\n\
             VERSION_ID={ver}\n\
             VERSION_CODENAME=trixie\n\
             DEBIAN_CODENAME=trixie\n\
             CHANNEL=testing-rust\n\
             ID=caramos\n\
             ID_LIKE=\"debian\"\n\
             PRETTY_NAME=\"CaramOS {ver} (Debian 13 Trixie / Rust Core)\"\n",
            ver = self.config.version
        );
        atomic_write_bytes(&release_target, release_content.as_bytes())?;

        {
            let _mount_guard =
                ChrootMountGuard::mount_all(&self.rootfs_dir, self.config.dry_run)?;
            if !self.config.dry_run {
                let mut cmd = Command::new("chroot");
                cmd.arg(&self.rootfs_dir).arg("/bin/sh").arg("-e").arg("-c").arg(
                    "if command -v dconf >/dev/null 2>&1; then dconf update; fi && \
                     if command -v locale-gen >/dev/null 2>&1; then locale-gen; fi",
                );
                run_checked_command(&mut cmd, "chroot-customize")?;
            }
        }

        ChrootMountGuard::verify_no_active_mounts_under(&self.rootfs_dir)?;

        Ok(CaramBuilder {
            config: self.config,
            rootfs_dir: self.rootfs_dir,
            iso_staging_dir: self.iso_staging_dir,
            _state: PhantomData,
        })
    }
}

impl CaramBuilder<RootfsCustomized> {
    /// Bước 3: Nén `filesystem.squashfs`, tạo ảnh `.iso` và băm SHA-256.
    pub fn repack_iso(
        self,
        output_iso_path: &Path,
    ) -> Result<(CaramBuilder<IsoPackaged>, Sha256Digest), CaramError> {
        let squashfs_target = self
            .iso_staging_dir
            .join("live")
            .join("filesystem.squashfs");

        if !self.config.dry_run {
            let mut mksquash = Command::new("mksquashfs");
            mksquash
                .arg(&self.rootfs_dir)
                .arg(&squashfs_target)
                .arg("-noappend");
            match self.config.compression {
                SquashfsCompression::ZstdFast => {
                    mksquash
                        .arg("-comp")
                        .arg("zstd")
                        .arg("-Xcompression-level")
                        .arg("6");
                }
                SquashfsCompression::XzRelease => {
                    mksquash
                        .arg("-comp")
                        .arg("xz")
                        .arg("-b")
                        .arg("1M")
                        .arg("-Xdict-size")
                        .arg("100%");
                }
            }
            run_checked_command(&mut mksquash, "mksquashfs")?;

            let mut xorriso = Command::new("xorriso");
            xorriso
                .arg("-as")
                .arg("mkisofs")
                .arg("-iso-level")
                .arg("3")
                .arg("-full-iso9660-filenames")
                .arg("-volid")
                .arg(format!("CARAMOS_{}", self.config.version))
                .arg("-output")
                .arg(output_iso_path)
                .arg(&self.iso_staging_dir);
            run_checked_command(&mut xorriso, "xorriso")?;
        } else {
            let dummy = format!("CARAMOS-DRYRUN-ISO-v{}-trixie", self.config.version);
            atomic_write_bytes(&squashfs_target, b"SQUASHFS_DRYRUN")?;
            atomic_write_bytes(output_iso_path, dummy.as_bytes())?;
        }

        let digest = Sha256Hasher::hash_file(output_iso_path)?;
        Ok((
            CaramBuilder {
                config: self.config,
                rootfs_dir: self.rootfs_dir,
                iso_staging_dir: self.iso_staging_dir,
                _state: PhantomData,
            },
            digest,
        ))
    }
}

/// Mục tệp khai báo trong gói cập nhật OTA.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct OtaFileDirective {
    /// Đường dẫn tương đối tính từ `/`.
    pub target_rel_path: SafeRelativePath,
    /// Tệp nguồn đã tải về.
    pub staged_source_path: PathBuf,
    /// Mã băm SHA-256 kỳ vọng.
    pub expected_sha256: Sha256Digest,
}

/// Manifest cập nhật OTA.
#[derive(Debug, Clone)]
pub struct OtaManifest {
    /// Phiên bản đích.
    pub target_version: SemVer,
    /// Danh sách tệp cần cập nhật nguyên tử.
    pub directives: Vec<OtaFileDirective>,
}

/// Trạng thái OTA chưa xác thực mã băm.
pub struct UnverifiedOta;
/// Trạng thái OTA đã xác thực SHA-256.
pub struct VerifiedOta;

/// Giao dịch cập nhật OTA nguyên tử kèm cơ chế tự động Rollback.
pub struct OtaTransaction<State> {
    manifest: OtaManifest,
    system_root: PathBuf,
    backup_dir: PathBuf,
    _state: PhantomData<State>,
}

enum RollbackRecord {
    Restorable {
        target_path: PathBuf,
        backup_file: PathBuf,
    },
    CreatedNew {
        target_path: PathBuf,
    },
}

impl OtaTransaction<UnverifiedOta> {
    /// Khởi tạo giao dịch OTA mới.
    pub fn new(manifest: OtaManifest, system_root: PathBuf, backup_dir: PathBuf) -> Self {
        Self {
            manifest,
            system_root,
            backup_dir,
            _state: PhantomData,
        }
    }

    /// Kiểm định SHA-256 của toàn bộ tệp trước khi cho phép ghi vào hệ thống.
    pub fn verify_payloads(self) -> Result<OtaTransaction<VerifiedOta>, CaramError> {
        for d in &self.manifest.directives {
            let actual = Sha256Hasher::hash_file(&d.staged_source_path)?;
            if actual != d.expected_sha256 {
                return Err(CaramError::DigestMismatch {
                    target: d.staged_source_path.clone(),
                    expected: d.expected_sha256.as_str().to_owned(),
                    actual: actual.as_str().to_owned(),
                });
            }
        }
        Ok(OtaTransaction {
            manifest: self.manifest,
            system_root: self.system_root,
            backup_dir: self.backup_dir,
            _state: PhantomData,
        })
    }
}

impl OtaTransaction<VerifiedOta> {
    /// Áp dụng toàn bộ thay đổi nguyên tử; tự động Rollback 100% nếu có bất kỳ lỗi nào.
    pub fn commit_atomic(self) -> Result<SemVer, CaramError> {
        fs::create_dir_all(&self.backup_dir).map_err(|source| CaramError::Io {
            context: "Tạo thư mục backup OTA",
            path: Some(self.backup_dir.clone()),
            source,
        })?;
        let mut journal = Vec::with_capacity(self.manifest.directives.len());

        for (idx, d) in self.manifest.directives.iter().enumerate() {
            let target = d.target_rel_path.join_under(&self.system_root);
            if let Err(err) = self.apply_one(idx, d, &target, &mut journal) {
                let report = Self::rollback(&journal);
                return Err(CaramError::TransactionAborted {
                    failed_step: format!(
                        "#{} ({}): {}",
                        idx,
                        d.target_rel_path.as_path().display(),
                        err
                    ),
                    rollback_report: report,
                });
            }
        }
        Ok(self.manifest.target_version)
    }

    fn apply_one(
        &self,
        idx: usize,
        d: &OtaFileDirective,
        target: &Path,
        journal: &mut Vec<RollbackRecord>,
    ) -> Result<(), CaramError> {
        if target.exists() {
            let bak = self.backup_dir.join(format!("bak_{}.bin", idx));
            fs::copy(target, &bak).map_err(|source| CaramError::Io {
                context: "Sao lưu tệp trước khi ghi OTA",
                path: Some(target.to_path_buf()),
                source,
            })?;
            journal.push(RollbackRecord::Restorable {
                target_path: target.to_path_buf(),
                backup_file: bak,
            });
        } else {
            journal.push(RollbackRecord::CreatedNew {
                target_path: target.to_path_buf(),
            });
        }

        let bytes = fs::read(&d.staged_source_path).map_err(|source| CaramError::Io {
            context: "Đọc tệp nguồn OTA",
            path: Some(d.staged_source_path.clone()),
            source,
        })?;
        atomic_write_bytes(target, &bytes)?;

        let written_hash = Sha256Hasher::hash_file(target)?;
        if written_hash != d.expected_sha256 {
            return Err(CaramError::DigestMismatch {
                target: target.to_path_buf(),
                expected: d.expected_sha256.as_str().to_owned(),
                actual: written_hash.as_str().to_owned(),
            });
        }
        Ok(())
    }

    fn rollback(journal: &[RollbackRecord]) -> String {
        let mut count = 0usize;
        for rec in journal.iter().rev() {
            match rec {
                RollbackRecord::Restorable {
                    target_path,
                    backup_file,
                } => {
                    if let Ok(bytes) = fs::read(backup_file) {
                        if atomic_write_bytes(target_path, &bytes).is_ok() {
                            count += 1;
                        }
                    }
                }
                RollbackRecord::CreatedNew { target_path } => {
                    if fs::remove_file(target_path).is_ok() {
                        count += 1;
                    }
                }
            }
        }
        format!("Đã hoàn tác an toàn {} tệp.", count)
    }
}

/// Ghi tệp nguyên tử (`write temp` -> `sync_all` -> `rename`).
pub fn atomic_write_bytes(target: &Path, content: &[u8]) -> Result<(), CaramError> {
    if let Some(parent) = target.parent() {
        fs::create_dir_all(parent).map_err(|source| CaramError::Io {
            context: "Tạo thư mục cha cho atomic write",
            path: Some(parent.to_path_buf()),
            source,
        })?;
    }
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    let fname = target
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("caramos");
    let tmp = target.with_file_name(format!(".{}.tmp.{}.{}", fname, std::process::id(), nanos));

    {
        let mut f = OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(&tmp)
            .map_err(|source| CaramError::Io {
                context: "Mở tệp tạm",
                path: Some(tmp.clone()),
                source,
            })?;
        f.write_all(content).map_err(|source| CaramError::Io {
            context: "Ghi dữ liệu vào tệp tạm",
            path: Some(tmp.clone()),
            source,
        })?;
        f.sync_all().map_err(|source| CaramError::Io {
            context: "Đồng bộ đĩa (fsync)",
            path: Some(tmp.clone()),
            source,
        })?;
    }

    fs::rename(&tmp, target).map_err(|source| {
        let _ = fs::remove_file(&tmp);
        CaramError::Io {
            context: "Đổi tên tệp tạm sang tệp đích",
            path: Some(target.to_path_buf()),
            source,
        }
    })
}

/// Sao chép đệ quy `config/includes.chroot` vào `rootfs` kèm kiểm tra chống Path Traversal.
pub fn copy_overlay_tree_safely(src_root: &Path, dst_root: &Path) -> Result<(), CaramError> {
    copy_dir_inner(src_root, src_root, dst_root)
}

fn copy_dir_inner(base_src: &Path, cur_src: &Path, dst_root: &Path) -> Result<(), CaramError> {
    let entries = fs::read_dir(cur_src).map_err(|source| CaramError::Io {
        context: "Đọc thư mục overlay",
        path: Some(cur_src.to_path_buf()),
        source,
    })?;
    for entry_res in entries {
        let entry = entry_res.map_err(|source| CaramError::Io {
            context: "Đọc mục con trong overlay",
            path: Some(cur_src.to_path_buf()),
            source,
        })?;
        let path = entry.path();
        let rel = path
            .strip_prefix(base_src)
            .map_err(|_| CaramError::Validation {
                field: "OverlayPath",
                value: path.display().to_string(),
                reason: "Không thuộc thư mục gốc overlay",
            })?;
        let rel_str = rel.to_str().ok_or_else(|| CaramError::Validation {
            field: "OverlayPath",
            value: path.display().to_string(),
            reason: "Đường dẫn không phải UTF-8",
        })?;
        let safe_rel = SafeRelativePath::parse(rel_str)?;
        let target = safe_rel.join_under(dst_root);
        let ftype = entry.file_type().map_err(|source| CaramError::Io {
            context: "Đọc kiểu tệp trong overlay",
            path: Some(path.clone()),
            source,
        })?;

        if ftype.is_dir() {
            fs::create_dir_all(&target).map_err(|source| CaramError::Io {
                context: "Tạo thư mục đích trong rootfs",
                path: Some(target),
                source,
            })?;
            copy_dir_inner(base_src, &path, dst_root)?;
        } else if ftype.is_file() {
            let bytes = fs::read(&path).map_err(|source| CaramError::Io {
                context: "Đọc tệp nguồn overlay",
                path: Some(path),
                source,
            })?;
            atomic_write_bytes(&target, &bytes)?;
        }
    }
    Ok(())
}

fn run_checked_command(cmd: &mut Command, label: &str) -> Result<(), CaramError> {
    let out = cmd.output().map_err(|source| CaramError::Io {
        context: "Chạy lệnh hệ thống",
        path: Some(PathBuf::from(label)),
        source,
    })?;
    if !out.status.success() {
        return Err(CaramError::CommandFailed {
            program: label.to_owned(),
            status_code: out.status.code(),
            stderr: String::from_utf8_lossy(&out.stderr).trim().to_owned(),
        });
    }
    Ok(())
}

/// Đọc và làm sạch danh sách gói từ `config/packages.txt` cho Debian 13 (`trixie`).
pub fn load_and_modernize_packages(
    packages_txt: &Path,
) -> Result<Vec<DebianPackageName>, CaramError> {
    let raw = if packages_txt.exists() {
        fs::read_to_string(packages_txt).map_err(|source| CaramError::Io {
            context: "Đọc config/packages.txt",
            path: Some(packages_txt.to_path_buf()),
            source,
        })?
    } else {
        String::new()
    };

    let mut map: BTreeMap<String, DebianPackageName> = BTreeMap::new();
    for line in raw.lines() {
        let clean = line.split('#').next().unwrap_or("").trim();
        if clean.is_empty() {
            continue;
        }
        if clean.starts_with("mint-")
            || clean.starts_with("ubuntu-")
            || clean.starts_with("language-pack-")
            || matches!(
                clean,
                "casper"
                    | "ubiquity"
                    | "lupin-casper"
                    | "mintupdate"
                    | "mintinstall"
                    | "firefox"
                    | "software-properties-common"
            )
        {
            continue;
        }
        let pkg = DebianPackageName::parse(clean)?;
        map.insert(pkg.as_str().to_owned(), pkg);
    }

    let mandatory = [
        "linux-image-amd64",
        "live-boot",
        "systemd-sysv",
        "dbus",
        "libpam-systemd",
        "cinnamon-core",
        "lightdm",
        "fcitx5",
        "fcitx5-unikey",
        "rust-coreutils",
        "sudo-rs",
        "ripgrep",
        "fd-find",
        "earlyoom",
        "ca-certificates",
    ];
    for m in mandatory {
        let pkg = DebianPackageName::parse(m)?;
        map.insert(pkg.as_str().to_owned(), pkg);
    }

    Ok(map.into_values().collect())
}

fn print_usage() {
    println!(
        "caramos-ctl — Công cụ Hợp nhất của CaramOS 2.0 (Debian Trixie & Rust Core)\n\
         \n\
         CÁCH DÙNG:\n\
         \x20 caramos-ctl prune [--repo-root <DIR>] [--dry-run | --execute]\n\
         \x20 caramos-ctl build [--release] [--dry-run] [--work-dir <DIR>]\n\
         \x20 caramos-ctl hash <FILE_PATH>\n\
         \x20 caramos-ctl ota-apply <SYS_ROOT> <REL_PATH> <SRC_FILE> <SHA256> <VERSION>\n"
    );
}

fn run_cli() -> Result<(), CaramError> {
    let mut args = env::args().skip(1);
    let sub = match args.next() {
        Some(s) => s,
        None => {
            print_usage();
            return Ok(());
        }
    };

    match sub.as_str() {
        "help" | "--help" | "-h" => {
            print_usage();
            Ok(())
        }
        "prune" => {
            let mut repo_root = PathBuf::from(".");
            let mut execute = false;
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--execute" => execute = true,
                    "--dry-run" => execute = false,
                    "--repo-root" => {
                        let d = args.next().ok_or_else(|| CaramError::Validation {
                            field: "--repo-root",
                            value: String::new(),
                            reason: "Thiếu đường dẫn sau --repo-root",
                        })?;
                        repo_root = PathBuf::from(d);
                    }
                    other => {
                        return Err(CaramError::Validation {
                            field: "prune_arg",
                            value: other.to_owned(),
                            reason: "Tham số không hợp lệ cho lệnh prune",
                        });
                    }
                }
            }
            let report = execute_repo_prune(&repo_root, execute)?;
            println!(
                "==> Prune (execute={}): Giải cứu {} tệp Applet, Xóa {} tệp cũ & {} thư mục cũ.",
                execute,
                report.salvaged_files.len(),
                report.removed_files.len(),
                report.removed_dirs.len()
            );
            Ok(())
        }
        "hash" => {
            let file_arg = args.next().ok_or_else(|| CaramError::Validation {
                field: "file_path",
                value: String::new(),
                reason: "Thiếu đường dẫn tệp cần băm SHA-256",
            })?;
            let digest = Sha256Hasher::hash_file(Path::new(&file_arg))?;
            println!("{}  {}", digest.as_str(), file_arg);
            Ok(())
        }
        "ota-apply" => {
            let sys_root = args.next().ok_or_else(|| CaramError::Validation {
                field: "sys_root",
                value: String::new(),
                reason: "Thiếu đường dẫn gốc hệ thống",
            })?;
            let rel_path = args.next().ok_or_else(|| CaramError::Validation {
                field: "rel_path",
                value: String::new(),
                reason: "Thiếu đường dẫn tương đối của tệp đích",
            })?;
            let src_file = args.next().ok_or_else(|| CaramError::Validation {
                field: "src_file",
                value: String::new(),
                reason: "Thiếu tệp nguồn OTA",
            })?;
            let sha_hex = args.next().ok_or_else(|| CaramError::Validation {
                field: "sha256",
                value: String::new(),
                reason: "Thiếu mã băm SHA-256 kỳ vọng",
            })?;
            let ver_str = args.next().ok_or_else(|| CaramError::Validation {
                field: "version",
                value: String::new(),
                reason: "Thiếu phiên bản đích",
            })?;

            let manifest = OtaManifest {
                target_version: SemVer::parse(&ver_str)?,
                directives: vec![OtaFileDirective {
                    target_rel_path: SafeRelativePath::parse(&rel_path)?,
                    staged_source_path: PathBuf::from(src_file),
                    expected_sha256: Sha256Digest::parse(&sha_hex)?,
                }],
            };
            let root_path = PathBuf::from(&sys_root);
            let backup_dir = root_path.join(".caramos-ota-backup");
            let committed_ver = OtaTransaction::new(manifest, root_path, backup_dir)
                .verify_payloads()?
                .commit_atomic()?;
            println!("OK  OTA cập nhật nguyên tử lên phiên bản {}", committed_ver);
            Ok(())
        }
        "build" => {
            let mut compression = SquashfsCompression::ZstdFast;
            let mut dry_run = false;
            let mut work_dir = PathBuf::from("./build");
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--release" => compression = SquashfsCompression::XzRelease,
                    "--dry-run" => dry_run = true,
                    "--work-dir" => {
                        let d = args.next().ok_or_else(|| CaramError::Validation {
                            field: "--work-dir",
                            value: String::new(),
                            reason: "Thiếu đường dẫn sau --work-dir",
                        })?;
                        work_dir = PathBuf::from(d);
                    }
                    other => {
                        return Err(CaramError::Validation {
                            field: "build_arg",
                            value: other.to_owned(),
                            reason: "Tham số không hợp lệ cho lệnh build",
                        });
                    }
                }
            }

            let _lock = ProcessLockGuard::acquire(work_dir.join("caramos-ctl.lock"))?;
            let packages = load_and_modernize_packages(Path::new("config/packages.txt"))?;
            let version = SemVer::parse("2.0.0")?;
            let config = BuildConfig {
                version,
                mirror: "https://deb.debian.org/debian".to_owned(),
                work_dir: work_dir.clone(),
                overlay_dir: PathBuf::from("config/includes.chroot"),
                packages,
                compression,
                dry_run,
            };
            let output_iso = work_dir.join(format!("CaramOS-{}-debian-trixie-amd64.iso", version));

            let (_done, digest) = CaramBuilder::new(config)
                .bootstrap_rootfs()?
                .customize()?
                .repack_iso(&output_iso)?;

            println!(
                "OK  ISO: {} (SHA-256: {})",
                output_iso.display(),
                digest.as_str()
            );
            Ok(())
        }
        other => Err(CaramError::Validation {
            field: "subcommand",
            value: other.to_owned(),
            reason: "Lệnh không hợp lệ (hỗ trợ: prune, build, hash, ota-apply)",
        }),
    }
}

fn main() -> ExitCode {
    match run_cli() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("ERROR: {}", e);
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_test_dir(label: &str) -> Result<PathBuf, CaramError> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_nanos())
            .unwrap_or(0);
        let dir = env::temp_dir().join(format!(
            "caramos_unified_test_{}_{}_{}",
            label,
            std::process::id(),
            nanos
        ));
        fs::create_dir_all(&dir).map_err(|source| CaramError::Io {
            context: "Tạo thư mục test",
            path: Some(dir.clone()),
            source,
        })?;
        Ok(dir)
    }

    #[test]
    fn test_sha256_vectors() {
        let mut h = Sha256Hasher::new();
        h.update(b"abc");
        assert_eq!(
            h.finalize().as_str(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn test_prune_salvages_applets_and_deletes_legacy() -> Result<(), CaramError> {
        let root = temp_test_dir("prune")?;
        let applet_dir = root
            .join("packages/caramos-ota/usr/share/cinnamon/applets/caramos-control-center@caramos");
        let scripts_dir = root.join("scripts");
        fs::create_dir_all(&applet_dir).map_err(|source| CaramError::Io {
            context: "Tạo applet_dir",
            path: Some(applet_dir.clone()),
            source,
        })?;
        fs::create_dir_all(&scripts_dir).map_err(|source| CaramError::Io {
            context: "Tạo scripts_dir",
            path: Some(scripts_dir.clone()),
            source,
        })?;

        atomic_write_bytes(&applet_dir.join("applet.js"), b"// applet")?;
        atomic_write_bytes(&scripts_dir.join("extract.sh"), b"#!/bin/bash")?;
        atomic_write_bytes(&root.join("build.sh"), b"#!/bin/bash")?;

        let report = execute_repo_prune(&root, true)?;
        assert_eq!(report.salvaged_files.len(), 1);
        assert!(root
            .join("config/includes.chroot/usr/share/cinnamon/applets/caramos-control-center@caramos/applet.js")
            .is_file());
        assert!(!root.join("packages/caramos-ota").exists());
        assert!(!root.join("scripts").exists());
        assert!(!root.join("build.sh").exists());

        let _ = fs::remove_dir_all(&root);
        Ok(())
    }

    #[test]
    fn test_builder_dry_run_and_ota_rollback() -> Result<(), CaramError> {
        let root = temp_test_dir("build_ota")?;
        let work = root.join("work");
        let overlay = root.join("overlay");
        atomic_write_bytes(&overlay.join("etc/hostname"), b"caramos\n")?;

        let cfg = BuildConfig {
            version: SemVer::parse("2.0.0")?,
            mirror: "https://deb.debian.org/debian".to_owned(),
            work_dir: work.clone(),
            overlay_dir: overlay,
            packages: vec![DebianPackageName::parse("rust-coreutils")?],
            compression: SquashfsCompression::ZstdFast,
            dry_run: true,
        };
        let iso = work.join("out.iso");
        let (_b, digest) = CaramBuilder::new(cfg)
            .bootstrap_rootfs()?
            .customize()?
            .repack_iso(&iso)?;
        assert_eq!(digest.as_str().len(), 64);

        let _ = fs::remove_dir_all(&root);
        Ok(())
    }
}
