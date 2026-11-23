//! Applying the daemon's sections (PROTOCOL.md part 2 "Applying the sections (agent)"): browser, printers, power,
//! apps, usb, firewall and wifi, and from 0.3 shared and snapshots (part 3). The session part applies wallpaper,
//! folders, shares and screen_lock for each user.
//!
//! Every system file the agent writes starts with a comment saying CaramOS Doanh nghiệp manages it, where the
//! format allows one. The agent removes only what it made and puts back what it changed when a section stops being
//! managed (or is off), keeping what it needs for that in `managed.json`.

pub mod apps;
pub mod browser;
pub mod firewall;
pub mod power;
pub mod printers;
pub mod shared;
pub mod snapshots;
pub mod usb;
pub mod wifi;

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::process::{self, Output};
use crate::store;

/// The first line of the files the agent writes, where the format allows a comment.
pub const MANAGED_BY: &str = "Managed by CaramOS Doanh nghiệp (caramos-business-agent): changes here are replaced.";

/// The system the sections act on: `/` and its commands, or a test folder where commands only pretend.
#[derive(Debug, Clone)]
pub struct System {
    pub root: PathBuf,
    /// Run lpadmin, ufw, nmcli, udevadm and the like; tests leave them out.
    pub commands: bool,
}

impl System {
    pub fn real() -> System {
        System { root: PathBuf::from("/"), commands: true }
    }

    /// A test system under `root`, without commands.
    pub fn test(root: &Path) -> System {
        System { root: root.to_path_buf(), commands: false }
    }

    /// An absolute system path under the root.
    pub fn path(&self, absolute: &str) -> PathBuf {
        self.root.join(absolute.trim_start_matches('/'))
    }

    /// Runs a command (never through a shell) with LC_ALL=C.UTF-8, so that its output can be read (in English,
    /// whatever LANGUAGE says, with names such as "Máy in tầng 2" kept whole); a test system pretends it worked and
    /// printed nothing.
    pub fn run(&self, program: &str, args: &[&str], timeout: Duration) -> Result<Output, String> {
        if !self.commands {
            return Ok(Output { status: success_status(), stdout: String::new(), stderr: String::new() });
        }
        let mut command = std::process::Command::new(program);
        command.args(args).env("LC_ALL", "C.UTF-8");
        process::run_command(command, timeout).map_err(|error| format!("{program}: {error}"))
    }

    /// The same, with `input` on the command's stdin (`overlayroot-chroot tee`).
    pub fn run_input(&self, program: &str, args: &[&str], input: &[u8], timeout: Duration) -> Result<Output, String> {
        if !self.commands {
            return Ok(Output { status: success_status(), stdout: String::new(), stderr: String::new() });
        }
        let mut command = std::process::Command::new(program);
        command.args(args).env("LC_ALL", "C.UTF-8");
        process::run_command_with_input(command, input, timeout).map_err(|error| format!("{program}: {error}"))
    }

    /// Runs a command and turns a failure into its message.
    pub fn check(&self, program: &str, args: &[&str], timeout: Duration) -> Result<String, String> {
        let output = self.run(program, args, timeout)?;
        if output.success() {
            Ok(output.stdout)
        } else {
            Err(format!("{program}: {}", output.message()))
        }
    }

    /// Whether a program is installed (one of the paths exists).
    pub fn has_any(&self, paths: &[&str]) -> bool {
        paths.iter().any(|path| self.path(path).exists())
    }
}

/// An exit status that says success, for the test system's pretend commands.
fn success_status() -> Option<std::process::ExitStatus> {
    use std::os::unix::process::ExitStatusExt;
    Some(std::process::ExitStatus::from_raw(0))
}

/// Writes `data` to a system file when it differs (atomically, with `mode`), making its folder. Whether it changed.
pub fn write_if_changed(path: &Path, data: &[u8], mode: u32) -> io::Result<bool> {
    if fs::read(path).is_ok_and(|old| old == data) {
        return Ok(false);
    }
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    store::write_atomic(path, data, mode)?;
    Ok(true)
}

/// Removes a file the agent made; a missing one is fine. Whether it was there.
pub fn remove_if_present(path: &Path) -> io::Result<bool> {
    match fs::remove_file(path) {
        Ok(()) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// The ASCII slug of a name, for queue and profile names: Vietnamese letters lose their marks ("Máy in tầng 2" →
/// "may-in-tang-2"), anything else becomes a hyphen. Never empty.
pub fn slug(name: &str) -> String {
    let mut out = String::new();
    for c in name.chars().flat_map(char::to_lowercase) {
        let plain = fold(c);
        if plain.is_ascii_alphanumeric() {
            out.push(plain);
        } else if !out.ends_with('-') && !out.is_empty() {
            out.push('-');
        }
    }
    let out: String = out.trim_matches('-').chars().take(40).collect();
    let out = out.trim_end_matches('-').to_string();
    if out.is_empty() {
        "x".to_string()
    } else {
        out
    }
}

/// Unique slugs for a list of names, in order: a repeated slug gets "-2", "-3"…
pub fn unique_slugs<'a>(names: impl IntoIterator<Item = &'a str>) -> Vec<String> {
    let mut seen: BTreeMap<String, usize> = BTreeMap::new();
    let mut slugs = Vec::new();
    for name in names {
        let base = slug(name);
        let count = seen.entry(base.clone()).or_insert(0);
        *count += 1;
        slugs.push(if *count == 1 { base } else { format!("{base}-{count}") });
    }
    slugs
}

/// A lower-case letter without its Vietnamese or Latin-1 marks.
fn fold(c: char) -> char {
    const GROUPS: [(&str, char); 7] = [
        ("àáảãạăằắẳẵặâầấẩẫậäå", 'a'),
        ("èéẻẽẹêềếểễệë", 'e'),
        ("ìíỉĩịïî", 'i'),
        ("òóỏõọôồốổỗộơờớởỡợöø", 'o'),
        ("ùúủũụưừứửữựüû", 'u'),
        ("ỳýỷỹỵÿ", 'y'),
        ("đ", 'd'),
    ];
    if c.is_ascii() {
        return c;
    }
    GROUPS.iter().find(|(letters, _)| letters.contains(c)).map_or('-', |(_, plain)| *plain)
}

/// What the daemon changed on the system, so that it can put it back: `managed.json`, 0600 root.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Managed {
    /// Set once the agent wrote Firefox's policies: what was there before.
    #[serde(default)]
    pub firefox: Option<Before>,
    /// The Chromium-family policy files the agent wrote.
    #[serde(default)]
    pub chromium: Vec<String>,
    /// The agent's block is in /etc/hosts.
    #[serde(default)]
    pub hosts: bool,
    /// The print queues the agent made.
    #[serde(default)]
    pub printers: Vec<String>,
    /// The queues made without a driver because the printer did not answer: the driver is tried again later.
    #[serde(default)]
    pub printers_pending: Vec<String>,
    /// The USB rule files the agent wrote.
    #[serde(default)]
    pub usb: Vec<String>,
    /// `usb_unlock`: USB storage allowed until this Unix time, whatever `usb` says.
    #[serde(default)]
    pub usb_unlock_until: Option<i64>,
    /// ufw before the agent first changed it, put back when the machine leaves (the agent never turns ufw off while
    /// the machine is in the company).
    #[serde(default)]
    pub firewall: Option<firewall::FirewallBefore>,
    /// The Wi-Fi profiles the agent wrote.
    #[serde(default)]
    pub wifi: Vec<String>,
    /// Wired NetworkManager connections whose wake-on-lan the agent changed: uuid → the earlier value.
    #[serde(default)]
    pub wake_on_lan: BTreeMap<String, String>,
    /// The RTC wake alarm the agent set last (Unix time).
    #[serde(default)]
    pub rtc_wake: Option<i64>,
    /// Today's scheduled shutdown: its date, the postpones used, the minute it is at now.
    #[serde(default)]
    pub power_day: Option<PowerDay>,
    /// When the apps section ran last (Unix time), and the section it ran for, to run at once when it changes.
    #[serde(default)]
    pub apps_ran: Option<i64>,
    #[serde(default)]
    pub apps_section: Option<String>,
    /// The guest session's LightDM file is the agent's (`shared.guest`).
    #[serde(default)]
    pub guest: bool,
    /// What the freeze changed (`shared.freeze`): the earlier overlayroot.local.conf.
    #[serde(default)]
    pub freeze: Option<shared::FreezeBefore>,
    /// Timeshift's settings before the agent first wrote them (`snapshots`).
    #[serde(default)]
    pub timeshift: Option<Before>,
}

/// A file as it was before the agent first wrote it.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Before {
    pub existed: bool,
    #[serde(default)]
    pub contents: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct PowerDay {
    /// YYYY-MM-DD.
    pub date: String,
    pub postpones: u32,
    /// The minute of the day the shutdown is at, after postpones.
    pub minute: u32,
    /// The countdown was asked for this minute already.
    #[serde(default)]
    pub warned_for: Option<u32>,
}

impl Managed {
    pub fn load(path: &Path) -> Managed {
        store::read_limited(path, 4 * 1024 * 1024)
            .ok()
            .and_then(|data| serde_json::from_slice(&data).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        let mut data = serde_json::to_vec_pretty(self).map_err(io::Error::other)?;
        data.push(b'\n');
        write_if_changed(path, &data, 0o600).map(|_| ())
    }
}

/// The outcome of a section for the health report: "ok" or "failed: <short reason>".
pub fn outcome(result: &Result<(), String>) -> String {
    match result {
        Ok(()) => "ok".to_string(),
        Err(error) => format!("failed: {}", crate::protocol::truncate_chars(error, 120)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slugs() {
        assert_eq!(slug("Máy in tầng 2"), "may-in-tang-2");
        assert_eq!(slug("Phòng Kế toán – Đà Nẵng"), "phong-ke-toan-da-nang");
        assert_eq!(slug("CongTy"), "congty");
        assert_eq!(slug("!!!"), "x");
        assert_eq!(slug(&"ạ".repeat(60)).len(), 40);
        assert_eq!(unique_slugs(["A b", "a-b", "Máy"]), ["a-b", "a-b-2", "may"]);
    }

    #[test]
    fn files_are_written_once_and_removed() {
        let dir = crate::testutil::TempDir::new("sections");
        let path = dir.path().join("etc/x/file");
        assert!(write_if_changed(&path, b"one", 0o644).unwrap());
        assert!(!write_if_changed(&path, b"one", 0o644).unwrap());
        assert!(write_if_changed(&path, b"two", 0o644).unwrap());
        assert!(remove_if_present(&path).unwrap());
        assert!(!remove_if_present(&path).unwrap());
        let system = System::test(dir.path());
        assert_eq!(system.path("/etc/hosts"), dir.path().join("etc/hosts"));
        assert!(system.run("lpadmin", &["-x", "x"], Duration::from_secs(1)).unwrap().success());
    }
}
