//! USER_STATUS files: the session part writes its user's status to `$XDG_RUNTIME_DIR/caramos-business/status.json`
//! after each round; the service reads every logged-in user's from /run/user/*/ for the check-in.
//!
//! The file also holds `applied`, how the session part's sections went (wallpaper, folders, shares, screen_lock), which
//! the service adds to the health report; the USER_STATUS it sends is exactly PROTOCOL.md's.

use std::collections::BTreeMap;
use std::fs::{self, OpenOptions, Permissions};
use std::io::{self, Read};
use std::os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt};
use std::path::Path;
use std::time::Duration;

use crate::process;
use crate::protocol::{truncate_chars, UserStatus, MAX_DETAIL_CHARS, RUNTIME_SUBDIR, STATUS_FILE};
use crate::store;

/// A status file is small; a bigger one is not read.
const MAX_STATUS: u64 = 4096;
/// The check-in carries at most this many users (it must stay under 64 KiB).
pub const MAX_USERS: usize = 50;

/// open(2) flags that std does not name. The service reads files in folders that users own, so it opens them
/// without following a last symlink and without blocking on a FIFO; the values differ between architectures.
#[cfg(any(target_arch = "x86_64", target_arch = "x86", target_arch = "riscv64", target_arch = "loongarch64"))]
const OPEN_FLAGS: i32 = 0o400000 | 0o4000; // O_NOFOLLOW | O_NONBLOCK
#[cfg(any(target_arch = "aarch64", target_arch = "arm", target_arch = "powerpc64", target_arch = "powerpc"))]
const OPEN_FLAGS: i32 = 0o100000 | 0o4000; // O_NOFOLLOW | O_NONBLOCK
#[cfg(not(any(
    target_arch = "x86_64",
    target_arch = "x86",
    target_arch = "riscv64",
    target_arch = "loongarch64",
    target_arch = "aarch64",
    target_arch = "arm",
    target_arch = "powerpc64",
    target_arch = "powerpc"
)))]
const OPEN_FLAGS: i32 = 0; // the checks before and after opening still apply

/// A user's status as the service reads it: USER_STATUS, how the session part's sections went, and whether the
/// user's screen locks by itself (PROTOCOL.md part 3 "Security report").
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserReport {
    pub uid: u32,
    pub status: UserStatus,
    pub applied: BTreeMap<String, String>,
    pub screen_lock_on: Option<bool>,
}

/// Writes the user's status (session part): the folder 0700, the file replaced atomically. `screen_lock_on` is left out
/// when the session cannot tell (neither Cinnamon nor Xfce).
pub fn write(runtime_dir: &Path, status: &UserStatus, applied: &BTreeMap<String, String>, screen_lock_on: Option<bool>) -> io::Result<()> {
    let dir = runtime_dir.join(RUNTIME_SUBDIR);
    fs::create_dir_all(&dir)?;
    fs::set_permissions(&dir, Permissions::from_mode(0o700))?;
    let mut value = serde_json::to_value(status).map_err(io::Error::other)?;
    value["applied"] = serde_json::json!(applied);
    if let Some(on) = screen_lock_on {
        value["screen_lock_on"] = serde_json::json!(on);
    }
    let data = serde_json::to_vec(&value).map_err(io::Error::other)?;
    store::write_atomic(&dir.join(STATUS_FILE), &data, 0o644)
}

/// The statuses of the users logged in now (service), sorted by user, at most MAX_USERS.
pub fn read_all(run_user: &Path) -> Vec<UserStatus> {
    read_reports(run_user).into_iter().map(|report| report.status).collect()
}

/// The same with each user's `applied` map.
pub fn read_reports(run_user: &Path) -> Vec<UserReport> {
    let Ok(entries) = fs::read_dir(run_user) else {
        return Vec::new();
    };
    let mut statuses = Vec::new();
    for entry in entries.flatten() {
        let Some(uid) = entry.file_name().to_str().and_then(|name| name.parse::<u32>().ok()) else {
            continue;
        };
        let path = entry.path().join(RUNTIME_SUBDIR).join(STATUS_FILE);
        let Some(data) = read_owned_file(&path, uid, MAX_STATUS) else {
            continue;
        };
        if let Some(status) = parse(&data, login_name(uid)) {
            statuses.push(UserReport { uid, status, applied: parse_applied(&data), screen_lock_on: parse_screen_lock_on(&data) });
        }
    }
    statuses.sort_by(|a, b| a.status.user.cmp(&b.status.user));
    statuses.truncate(MAX_USERS);
    statuses
}

/// The `applied` map of a status file: section → "ok" or "failed: …", only the session part's sections.
pub fn parse_applied(data: &[u8]) -> BTreeMap<String, String> {
    let value: serde_json::Value = serde_json::from_slice(data).unwrap_or_default();
    value["applied"]
        .as_object()
        .into_iter()
        .flatten()
        .filter(|(section, _)| matches!(section.as_str(), "wallpaper" | "folders" | "shares" | "screen_lock"))
        .filter_map(|(section, outcome)| Some((section.clone(), truncate_chars(outcome.as_str()?, 150))))
        .filter(|(_, outcome)| outcome == "ok" || outcome.starts_with("failed: "))
        .collect()
}

/// The `screen_lock_on` of a status file, when it says.
pub fn parse_screen_lock_on(data: &[u8]) -> Option<bool> {
    serde_json::from_slice::<serde_json::Value>(data).ok()?.get("screen_lock_on")?.as_bool()
}

/// A status as the check-in sends it. The user is the owner of the file's folder (`account`, from the uid) when
/// that is known, so that nobody reports for another user; the detail is cut to 200 characters. None for a file that
/// is not a valid status.
pub fn parse(data: &[u8], account: Option<String>) -> Option<UserStatus> {
    let status: UserStatus = serde_json::from_slice(data).ok()?;
    let user = account.or_else(|| valid_login(&status.user).then(|| status.user.clone()))?;
    let time_ok = (1..=40).contains(&status.time.len())
        && status.time.bytes().all(|byte| byte.is_ascii_digit() || b"-:+.TZ".contains(&byte));
    if !time_ok {
        return None;
    }
    let detail: String = status.detail.chars().map(|c| if c.is_control() { ' ' } else { c }).collect();
    Some(UserStatus { user, detail: truncate_chars(&detail, MAX_DETAIL_CHARS), ..status })
}

/// A login name that can be shown as it is.
pub fn valid_login(name: &str) -> bool {
    (1..=64).contains(&name.chars().count()) && !name.chars().any(|c| c.is_control() || c == ':' || c == '/')
}

/// The login name of `uid` from the system's user database (local users and directory users alike).
pub fn login_name(uid: u32) -> Option<String> {
    let output = process::run("getent", &["passwd", &uid.to_string()], Duration::from_secs(10)).ok()?;
    if !output.success() {
        return None;
    }
    let name = output.stdout.split(':').next()?.trim().to_string();
    valid_login(&name).then_some(name)
}

/// The bytes of `path` when it is a regular file owned by `uid` of at most `max` bytes. The service reads it as
/// root in a folder that the user controls: the checks are made before opening and again on the open file, which
/// is opened without following a last symlink and without blocking.
pub fn read_owned_file(path: &Path, uid: u32, max: u64) -> Option<Vec<u8>> {
    let before = fs::symlink_metadata(path).ok()?;
    if !before.file_type().is_file() || before.uid() != uid || before.len() > max {
        return None;
    }
    let file = OpenOptions::new().read(true).custom_flags(OPEN_FLAGS).open(path).ok()?;
    let after = file.metadata().ok()?;
    if !after.file_type().is_file() || after.uid() != uid || after.dev() != before.dev() || after.ino() != before.ino()
    {
        return None;
    }
    let mut data = Vec::new();
    file.take(max + 1).read_to_end(&mut data).ok()?;
    (data.len() as u64 <= max).then_some(data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::protocol::{FoldersState, WallpaperState};
    use crate::testutil::TempDir;

    fn status(user: &str, detail: &str) -> UserStatus {
        UserStatus {
            user: user.into(),
            wallpaper: WallpaperState::Applied,
            folders: FoldersState::Server,
            detail: detail.into(),
            time: "2026-11-21T09:00:00+07:00".into(),
        }
    }

    #[test]
    fn written_and_read_back() {
        let run_user = TempDir::new("run-user");
        let uid = process::uid().unwrap();
        let runtime = run_user.path().join(uid.to_string());
        let applied = BTreeMap::from([("screen_lock".to_string(), "ok".to_string()), ("browser".to_string(), "ok".to_string())]);
        write(&runtime, &status("lan", "ok"), &applied, Some(true)).unwrap();
        let read = read_owned_file(&runtime.join(RUNTIME_SUBDIR).join(STATUS_FILE), uid, MAX_STATUS).unwrap();
        assert_eq!(parse(&read, None), Some(status("lan", "ok")));
        assert_eq!(parse_screen_lock_on(&read), Some(true));
        let reports = read_reports(run_user.path());
        assert_eq!((reports[0].uid, reports[0].screen_lock_on), (uid, Some(true)));
        write(&runtime, &status("lan", "ok"), &applied, None).unwrap();
        let read = read_owned_file(&runtime.join(RUNTIME_SUBDIR).join(STATUS_FILE), uid, MAX_STATUS).unwrap();
        assert_eq!(parse_screen_lock_on(&read), None, "unknown on this desktop");
        // Only the session part's sections count.
        assert_eq!(parse_applied(&read), BTreeMap::from([("screen_lock".to_string(), "ok".to_string())]));
        // The account of the folder's uid wins over the name in the file.
        assert_eq!(parse(&read, Some("binh".into())).unwrap().user, "binh");
        // Another uid's folder: the file is not that user's.
        assert_eq!(read_owned_file(&runtime.join(RUNTIME_SUBDIR).join(STATUS_FILE), uid + 1, MAX_STATUS), None);
    }

    #[test]
    fn symlinks_and_odd_files_are_not_read() {
        let dir = TempDir::new("status-links");
        let uid = process::uid().unwrap();
        let target = dir.path().join("secret.json");
        fs::write(&target, serde_json::to_vec(&status("lan", "")).unwrap()).unwrap();
        let link = dir.path().join("status.json");
        std::os::unix::fs::symlink(&target, &link).unwrap();
        assert_eq!(read_owned_file(&link, uid, MAX_STATUS), None);
        assert_eq!(read_owned_file(dir.path(), uid, MAX_STATUS), None);
        fs::write(&target, vec![b' '; 5000]).unwrap();
        assert_eq!(read_owned_file(&target, uid, MAX_STATUS), None);
    }

    #[test]
    fn statuses_are_cleaned() {
        let long = "x".repeat(300);
        let parsed = parse(&serde_json::to_vec(&status("lan", &long)).unwrap(), None).unwrap();
        assert_eq!(parsed.detail.chars().count(), 200);
        let parsed = parse(&serde_json::to_vec(&status("lan", "a\nb")).unwrap(), None).unwrap();
        assert_eq!(parsed.detail, "a b");
        assert_eq!(parse(&serde_json::to_vec(&status("bad/user", "")).unwrap(), None), None);
        let mut odd_time = status("lan", "");
        odd_time.time = "<script>".into();
        assert_eq!(parse(&serde_json::to_vec(&odd_time).unwrap(), None), None);
        assert_eq!(parse(br#"{"user": "lan", "wallpaper": "maybe", "folders": "off", "detail": "", "time": "1"}"#, None), None);
    }
}
