//! The relay between the daemon and the session parts (PROTOCOL.md part 2 "Employee UI contract"):
//! - the daemon puts a verified command for a user into `/run/caramos-business/inbox/<uid>/<id>.json`: root's, with
//!   the user's own group, the folder 0750 and the files 0640, so that only that user reads them (they carry remote
//!   help keys and ticket notes; PROTOCOL.md part 3 "Inboxes and per-user files"). A user without a private group
//!   keeps part 2's 0755 and 0644;
//! - the session part acts on it and writes `$XDG_RUNTIME_DIR/caramos-business/outbox/<id>.json` `{"id", "state",
//!   "detail", "answer"}`;
//! - the daemon reads the outboxes every 2 s, combines the users' answers into one result per command, and removes
//!   the files. It also sends the help requests that the window writes there (`help-<unix>.json`).
//!
//! The inbox is root's rather than in the user's runtime folder as PROTOCOL.md first said: root never writes into a
//! folder a user controls, where a symlink swapped in at the right moment could send the write elsewhere. The session
//! part remembers the commands it took instead of renaming them.

use std::collections::BTreeMap;
use std::fs;
use std::io;
use std::os::unix::fs::{MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::commands::Ending;
use crate::protocol::{truncate_chars, ResultState, MAX_RESULT_DETAIL, OUTBOX, RUNTIME_SUBDIR};
use crate::status;
use crate::store;

/// Outbox files are small; a bigger one is not read.
const MAX_ANSWER: u64 = 16 * 1024;

/// A user whose session part runs now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UserSession {
    pub uid: u32,
    pub user: String,
}

/// What the daemon asks a session part to do.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct InboxEntry {
    /// The command's id, or the daemon's own id for a scheduled countdown.
    pub id: String,
    /// message, countdown, remote_help or cancel.
    pub action: String,
    #[serde(default)]
    pub args: Value,
    #[serde(default)]
    pub admin_name: String,
    /// Unix time after which it no longer matters.
    #[serde(default)]
    pub expires: i64,
}

/// A session part's answer.
#[derive(Debug, Clone, Default, PartialEq, Eq, Deserialize, Serialize)]
pub struct Answer {
    pub id: String,
    /// done, failed or refused.
    #[serde(default)]
    pub state: String,
    #[serde(default)]
    pub detail: String,
    /// The prompt's answer: read, closed, now, postpone, timeout, view, control, refuse.
    #[serde(default)]
    pub answer: String,
}

/// What the daemon found in the outboxes.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Outgoing {
    Answer { uid: u32, answer: Answer, path: PathBuf },
    Help { uid: u32, note: String, time: i64, path: PathBuf },
}

/// An id the relay accepts in file names: a command's UUID, `power-<date>-<minute>`, or `ticket-<HT-0007>-<n>`.
pub fn is_relay_id(id: &str) -> bool {
    (1..=64).contains(&id.len()) && id.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
}

/// The users whose session part runs: `/run/user/<uid>/caramos-business/session.pid` names a live process of that uid.
pub fn sessions(run_user: &Path) -> Vec<UserSession> {
    let Ok(entries) = fs::read_dir(run_user) else {
        return Vec::new();
    };
    let mut sessions = Vec::new();
    for entry in entries.flatten() {
        let Some(uid) = entry.file_name().to_str().and_then(|name| name.parse::<u32>().ok()) else {
            continue;
        };
        let pid_file = entry.path().join(RUNTIME_SUBDIR).join("session.pid");
        let Some(pid) = status::read_owned_file(&pid_file, uid, 64)
            .and_then(|data| String::from_utf8(data).ok())
            .and_then(|text| text.trim().parse::<u32>().ok())
        else {
            continue;
        };
        let alive = fs::metadata(format!("/proc/{pid}")).is_ok_and(|metadata| metadata.uid() == uid);
        if alive {
            let user = status::login_name(uid).unwrap_or_else(|| uid.to_string());
            sessions.push(UserSession { uid, user });
        }
    }
    sessions.sort_by_key(|session| session.uid);
    sessions
}

/// A graphical user session on seat0 in logind's files: (uid, active). The login screen's own session (CLASS=greeter,
/// also light-locker's lock screen) is nobody's.
fn seat0_user_sessions(sessions_dir: &Path) -> Vec<(u32, bool)> {
    let Ok(entries) = fs::read_dir(sessions_dir) else {
        return Vec::new();
    };
    entries
        .flatten()
        // Only the session files: logind keeps a FIFO `<id>.ref` beside each, and reading one blocks.
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_file()) && !entry.file_name().to_string_lossy().contains('.'))
        .filter_map(|entry| {
            let text = fs::read_to_string(entry.path()).ok()?;
            let value = |key: &str| text.lines().find_map(|line| line.strip_prefix(key)?.strip_prefix('='));
            let graphical = matches!(value("TYPE"), Some("x11" | "wayland"));
            let user = value("CLASS").is_none_or(|class| class == "user");
            let open = value("STATE").is_none_or(|state| state != "closing");
            (value("SEAT") == Some("seat0") && graphical && user && open).then(|| Some((value("UID")?.parse().ok()?, value("ACTIVE") == Some("1"))))?
        })
        .collect()
}

/// The uid of the active graphical session on seat0 (the user at the screen), from logind's session files. With only
/// the login screen's session on the screen, nobody is at the machine.
pub fn active_uid(sessions_dir: &Path) -> Option<u32> {
    seat0_user_sessions(sessions_dir).into_iter().find_map(|(uid, active)| active.then_some(uid))
}

/// The user of seat0: the active session's, else one whose screen is locked by light-locker (its lock screen is a
/// greeter session, the user's session stays "online"). Someone is using the machine while there is one.
pub fn seat_user(sessions_dir: &Path) -> Option<u32> {
    let sessions = seat0_user_sessions(sessions_dir);
    active_uid(sessions_dir).or_else(|| sessions.first().map(|(uid, _)| *uid))
}

/// Puts an entry into a user's inbox, `<inbox_root>/<uid>/<id>.json`, root's. With `group`, the user's private
/// group, the folder is `root:<group>` 0750 and the file 0640; without, both are readable by all (0755, 0644).
pub fn deliver(inbox_root: &Path, uid: u32, group: Option<u32>, entry: &InboxEntry) -> io::Result<()> {
    if !is_relay_id(&entry.id) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid id"));
    }
    let dir = inbox_root.join(uid.to_string());
    fs::create_dir_all(&dir)?;
    fs::set_permissions(inbox_root, fs::Permissions::from_mode(0o755))?;
    let as_root = crate::process::uid() == Some(0);
    match group {
        Some(gid) => {
            if as_root {
                std::os::unix::fs::chown(&dir, Some(0), Some(gid))?;
            }
            fs::set_permissions(&dir, fs::Permissions::from_mode(0o750))?;
        }
        None => {
            if as_root {
                std::os::unix::fs::chown(&dir, Some(0), Some(0))?;
            }
            fs::set_permissions(&dir, fs::Permissions::from_mode(0o755))?;
        }
    }
    let data = serde_json::to_vec(entry).map_err(io::Error::other)?;
    let path = dir.join(format!("{}.json", entry.id));
    match group {
        Some(gid) => store::write_atomic_owned(&path, &data, 0o640, Some((0, gid))),
        None => store::write_atomic(&path, &data, 0o644),
    }
}

/// Takes an entry out of a user's inbox (done, cancelled or expired).
pub fn withdraw(inbox_root: &Path, uid: u32, id: &str) {
    if is_relay_id(id) {
        let _ = fs::remove_file(inbox_root.join(uid.to_string()).join(format!("{id}.json")));
    }
}

/// The entries in a user's inbox (the session part's side).
pub fn inbox(inbox_root: &Path, uid: u32) -> Vec<InboxEntry> {
    let Ok(entries) = fs::read_dir(inbox_root.join(uid.to_string())) else {
        return Vec::new();
    };
    let mut found: Vec<InboxEntry> = entries
        .flatten()
        .filter(|entry| entry.file_name().to_string_lossy().ends_with(".json"))
        .filter_map(|entry| store::read_limited(&entry.path(), MAX_ANSWER).ok())
        .filter_map(|data| serde_json::from_slice::<InboxEntry>(&data).ok())
        .filter(|entry| is_relay_id(&entry.id))
        .collect();
    found.sort_by(|a, b| a.id.cmp(&b.id));
    found
}

/// A user's outbox folder when it is a real folder that user owns (not a symlink).
fn outbox_dir(run_user: &Path, uid: u32) -> Option<PathBuf> {
    let base = run_user.join(uid.to_string()).join(RUNTIME_SUBDIR);
    let dir = base.join(OUTBOX);
    for path in [&base, &dir] {
        let metadata = fs::symlink_metadata(path).ok()?;
        if !metadata.is_dir() || metadata.uid() != uid {
            return None;
        }
    }
    Some(dir)
}

/// The answers and help requests waiting in the users' outboxes. Files are read as root with the checks of status.rs
/// (a regular file owned by that user, no symlink, small).
pub fn read_outboxes(run_user: &Path) -> Vec<Outgoing> {
    #[derive(Deserialize)]
    struct Help {
        #[serde(default)]
        note: String,
    }
    let Ok(users) = fs::read_dir(run_user) else {
        return Vec::new();
    };
    let mut found = Vec::new();
    for user in users.flatten() {
        let Some(uid) = user.file_name().to_str().and_then(|name| name.parse::<u32>().ok()) else {
            continue;
        };
        let Some(dir) = outbox_dir(run_user, uid) else {
            continue;
        };
        let Ok(entries) = fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let Some(stem) = name.strip_suffix(".json") else {
                continue;
            };
            let path = entry.path();
            let Some(data) = status::read_owned_file(&path, uid, MAX_ANSWER) else {
                continue;
            };
            if let Some(time) = stem.strip_prefix("help-").and_then(|unix| unix.parse::<i64>().ok()) {
                if let Ok(help) = serde_json::from_slice::<Help>(&data) {
                    found.push(Outgoing::Help { uid, note: help.note, time, path });
                }
            } else if is_relay_id(stem) {
                if let Ok(answer) = serde_json::from_slice::<Answer>(&data) {
                    if answer.id == stem {
                        found.push(Outgoing::Answer { uid, answer, path });
                    }
                }
            }
        }
    }
    found
}

/// Removes a file from a user's outbox, after checking that its folder is still that user's real folder.
pub fn remove_from_outbox(run_user: &Path, uid: u32, path: &Path) {
    if let Some(dir) = outbox_dir(run_user, uid) {
        if path.parent() == Some(dir.as_path()) {
            let _ = fs::remove_file(path);
        }
    }
}

/// What a waiting command is for.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Purpose {
    Lock,
    Message { ack: bool },
    Countdown { ending: Ending },
    RemoteHelp,
    /// The scheduled shutdown's countdown for the shutdown at `minute` of the day.
    PowerWarning { minute: u32 },
}

/// A command delivered to session parts, waiting for their answers.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Pending {
    pub id: String,
    pub purpose: Purpose,
    /// uid → login name of the users it was delivered to.
    pub users: BTreeMap<u32, String>,
    pub answers: BTreeMap<u32, Answer>,
    /// Unix time when it ends with the answers it has.
    pub deadline: i64,
    pub cancelled: bool,
}

impl Pending {
    pub fn new(id: &str, purpose: Purpose, sessions: &[UserSession], deadline: i64) -> Pending {
        Pending {
            id: id.to_string(),
            purpose,
            users: sessions.iter().map(|session| (session.uid, session.user.clone())).collect(),
            answers: BTreeMap::new(),
            deadline,
            cancelled: false,
        }
    }

    /// Every user answered, or it was cancelled.
    pub fn complete(&self) -> bool {
        self.cancelled || self.users.keys().all(|uid| self.answers.contains_key(uid))
    }

    fn names_where(&self, wanted: impl Fn(&Answer) -> bool) -> Vec<String> {
        self.users
            .iter()
            .filter(|(uid, _)| self.answers.get(uid).is_some_and(&wanted))
            .map(|(_, name)| name.clone())
            .collect()
    }

    /// The command's one result for this machine (several users' answers combined).
    pub fn summary(&self) -> (ResultState, String) {
        if self.cancelled {
            return (ResultState::Failed, "đã hủy".to_string());
        }
        let (state, detail) = match &self.purpose {
            Purpose::Lock => {
                let locked = self.names_where(|answer| answer.state == "done");
                let failed = self.names_where(|answer| answer.state != "done");
                match (locked.is_empty(), failed.is_empty()) {
                    (true, true) if self.users.is_empty() => (ResultState::Done, "không có ai đăng nhập".to_string()),
                    (_, true) => (ResultState::Done, format!("đã khóa: {}", locked.join(", "))),
                    (true, false) => (ResultState::Failed, format!("không khóa được: {}", failed.join(", "))),
                    (false, false) => (ResultState::Done, format!("đã khóa: {}; không khóa được: {}", locked.join(", "), failed.join(", "))),
                }
            }
            Purpose::Message { ack } => {
                if self.users.is_empty() {
                    (ResultState::Failed, "không có ai đăng nhập".to_string())
                } else if *ack {
                    let read = self.names_where(|answer| answer.answer == "read");
                    let unread = self.names_where(|answer| answer.answer != "read");
                    let missing: Vec<String> = self.users.iter().filter(|(uid, _)| !self.answers.contains_key(uid)).map(|(_, name)| name.clone()).collect();
                    let mut detail = format!("đã đọc: {}", if read.is_empty() { "chưa ai".to_string() } else { read.join(", ") });
                    let not_read: Vec<String> = unread.into_iter().chain(missing).collect();
                    if !not_read.is_empty() {
                        detail.push_str(&format!("; chưa đọc: {}", not_read.join(", ")));
                    }
                    (ResultState::Done, detail)
                } else {
                    (ResultState::Done, format!("đã hiện cho: {}", self.users.values().cloned().collect::<Vec<_>>().join(", ")))
                }
            }
            Purpose::Countdown { ending } => {
                let names: Vec<String> = self.users.values().cloned().collect();
                let detail = match ending {
                    Ending::Logout if names.is_empty() => "không có ai đăng nhập".to_string(),
                    Ending::Logout => format!("đã đăng xuất: {}", names.join(", ")),
                    Ending::Restart => "đang khởi động lại".to_string(),
                    Ending::Shutdown => "đang tắt máy".to_string(),
                };
                (ResultState::Done, detail)
            }
            Purpose::RemoteHelp => match self.answers.values().next() {
                Some(answer) => {
                    let state = match answer.state.as_str() {
                        "done" => ResultState::Done,
                        "refused" => ResultState::Refused,
                        _ => ResultState::Failed,
                    };
                    (state, answer.detail.clone())
                }
                None => (ResultState::Failed, "không có trả lời".to_string()),
            },
            Purpose::PowerWarning { .. } => (ResultState::Done, String::new()),
        };
        (state, truncate_chars(&detail, MAX_RESULT_DETAIL))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    fn session(uid: u32, user: &str) -> UserSession {
        UserSession { uid, user: user.into() }
    }

    fn answer(id: &str, answer: &str) -> Answer {
        Answer { id: id.into(), state: "done".into(), detail: String::new(), answer: answer.into() }
    }

    #[test]
    fn combined_results() {
        let id = "00000000-0000-4000-8000-000000000041";
        let mut pending = Pending::new(id, Purpose::Message { ack: true }, &[session(1000, "minh"), session(1001, "lan"), session(1002, "binh")], 0);
        pending.answers.insert(1000, answer(id, "read"));
        pending.answers.insert(1001, answer(id, "read"));
        assert!(!pending.complete());
        pending.answers.insert(1002, answer(id, "closed"));
        assert!(pending.complete());
        assert_eq!(pending.summary(), (ResultState::Done, "đã đọc: minh, lan; chưa đọc: binh".to_string()));
        let nobody = Pending::new(id, Purpose::Message { ack: false }, &[], 0);
        assert!(nobody.complete());
        assert_eq!(nobody.summary().0, ResultState::Failed);
        let mut help = Pending::new(id, Purpose::RemoteHelp, &[session(1000, "minh")], 0);
        help.answers.insert(1000, Answer { id: id.into(), state: "refused".into(), detail: "từ chối".into(), answer: "refuse".into() });
        assert_eq!(help.summary(), (ResultState::Refused, "từ chối".to_string()));
        let mut lock = Pending::new(id, Purpose::Lock, &[session(1000, "minh"), session(1001, "lan")], 0);
        lock.answers.insert(1000, answer(id, "locked"));
        lock.answers.insert(1001, Answer { id: id.into(), state: "failed".into(), detail: "x".into(), answer: String::new() });
        assert_eq!(lock.summary(), (ResultState::Done, "đã khóa: minh; không khóa được: lan".to_string()));
        assert_eq!(Pending::new(id, Purpose::Lock, &[], 0).summary(), (ResultState::Done, "không có ai đăng nhập".to_string()));
        let mut cancelled = Pending::new(id, Purpose::Countdown { ending: Ending::Shutdown }, &[session(1000, "minh")], 0);
        cancelled.cancelled = true;
        assert!(cancelled.complete());
        assert_eq!(cancelled.summary(), (ResultState::Failed, "đã hủy".to_string()));
    }

    #[test]
    fn inbox_and_outbox() {
        let root = TempDir::new("relay");
        let inbox_root = root.path().join("run/caramos-business/inbox");
        let uid = crate::process::uid().unwrap();
        let entry = InboxEntry { id: "00000000-0000-4000-8000-000000000041".into(), action: "message".into(), args: serde_json::json!({"title": "Họp"}), admin_name: "IT".into(), expires: 9 };
        deliver(&inbox_root, uid, None, &entry).unwrap();
        assert_eq!(inbox(&inbox_root, uid), [entry.clone()]);
        let mode = |path: &Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(&inbox_root.join(uid.to_string())), 0o755, "no private group: part 2's modes");
        assert!(deliver(&inbox_root, uid, None, &InboxEntry { id: "../x".into(), ..entry.clone() }).is_err());
        withdraw(&inbox_root, uid, &entry.id);
        assert!(inbox(&inbox_root, uid).is_empty());
        // With the user's own group: only that user reads the folder and its files.
        let gid = fs::metadata(root.path()).unwrap().gid();
        let ticket = InboxEntry { id: "ticket-HT-0007-1".into(), action: "ticket".into(), ..entry.clone() };
        deliver(&inbox_root, uid, Some(gid), &ticket).unwrap();
        assert_eq!(mode(&inbox_root.join(uid.to_string())), 0o750);
        assert_eq!(mode(&inbox_root.join(uid.to_string()).join("ticket-HT-0007-1.json")), 0o640);
        assert_eq!(mode(&inbox_root), 0o755);
        assert_eq!(inbox(&inbox_root, uid), [ticket.clone()]);
        withdraw(&inbox_root, uid, &ticket.id);

        let run_user = root.path().join("run/user");
        let outbox = run_user.join(uid.to_string()).join("caramos-business/outbox");
        fs::create_dir_all(&outbox).unwrap();
        fs::write(outbox.join(format!("{}.json", entry.id)), serde_json::to_vec(&answer(&entry.id, "read")).unwrap()).unwrap();
        fs::write(outbox.join("help-1795245000.json"), r#"{"note": "Máy in không in được"}"#).unwrap();
        fs::write(outbox.join("other.txt"), "x").unwrap();
        let mut found = read_outboxes(&run_user);
        found.sort_by_key(|item| matches!(item, Outgoing::Help { .. }));
        assert_eq!(found.len(), 2);
        assert!(matches!(&found[0], Outgoing::Answer { answer, .. } if answer.answer == "read"));
        assert!(matches!(&found[1], Outgoing::Help { note, time: 1_795_245_000, .. } if note == "Máy in không in được"));
        if let Outgoing::Help { path, .. } = &found[1] {
            remove_from_outbox(&run_user, uid, path);
            assert!(!path.exists());
        }
    }

    #[test]
    fn the_user_at_the_screen() {
        let root = TempDir::new("logind");
        fs::write(root.path().join("2"), "UID=1000\nUSER=lan\nACTIVE=1\nSTATE=active\nTYPE=x11\nSEAT=seat0\n").unwrap();
        fs::write(root.path().join("c1"), "UID=117\nUSER=lightdm\nACTIVE=0\nTYPE=x11\nSEAT=seat0\n").unwrap();
        assert_eq!(active_uid(root.path()), Some(1000));
        fs::write(root.path().join("2"), "UID=1000\nACTIVE=1\nTYPE=tty\nSEAT=seat0\n").unwrap();
        assert_eq!(active_uid(root.path()), None);
        // The login screen alone: nobody at the machine.
        fs::remove_file(root.path().join("2")).unwrap();
        fs::write(root.path().join("c1"), "UID=117\nUSER=lightdm\nACTIVE=1\nTYPE=x11\nCLASS=greeter\nSEAT=seat0\n").unwrap();
        assert_eq!(active_uid(root.path()), None);
        assert_eq!(seat_user(root.path()), None);
        // A screen locked by light-locker: its lock screen is a greeter session, the user's session is only online.
        fs::write(root.path().join("4"), "UID=1002\nUSER=minh\nACTIVE=0\nSTATE=online\nTYPE=x11\nCLASS=user\nSEAT=seat0\n").unwrap();
        assert_eq!(active_uid(root.path()), None);
        assert_eq!(seat_user(root.path()), Some(1002));
        fs::write(root.path().join("3"), "UID=1001\nUSER=lan\nACTIVE=1\nTYPE=x11\nCLASS=user\nSEAT=seat0\n").unwrap();
        assert_eq!(active_uid(root.path()), Some(1001));
        assert_eq!(seat_user(root.path()), Some(1001));
        // logind's FIFOs beside the files are never opened (reading one would block).
        std::process::Command::new("mkfifo").arg(root.path().join("3.ref")).status().unwrap();
        assert_eq!(active_uid(root.path()), Some(1001));
    }
}
