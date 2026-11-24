//! The graphical logins at the machine (logind's session files), the session part of each, and what each user was
//! told (PROTOCOL.md part 3, changes of 0.3.1 after the full test pass):
//! - a session part starts from /etc/xdg/autostart at login. A machine paired in a running session (the package
//!   installed without logging out, or an enrolment) had none until the next login: no wallpaper, folders or notice,
//!   while the daemon already applied the firewall, the browser and USB rules. The daemon now starts one in each
//!   graphical login that has none, as the user, under the user's systemd (`systemd-run --user --machine=<user>@.host`),
//!   with the environment the login's own programs have;
//! - the session part writes `$XDG_RUNTIME_DIR/caramos-business/notice.json` `{"machine_id", "sections"}`: what the
//!   company's notice has told the user, on the screen now (its window wrote `notice-shown` when it mapped) or
//!   answered. The daemon applies new sections only once every user at the machine has been told about them, or after
//!   a short wait: the notice comes before the first measures (Law 91/2025/QH15, article 25).

use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::MetadataExt;
use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::protocol::RUNTIME_SUBDIR;
use crate::status;

/// The session part's file of what the user was told, in its runtime folder.
pub const NOTICE_FILE: &str = "notice.json";
/// What the notice's window writes in the same folder once it is on the screen (`caramos-business --prompt notice`).
pub const SHOWN_FILE: &str = "notice-shown";
/// The installed program.
pub const AGENT_PROGRAM: &str = "/usr/lib/caramos-business/caramos-business-agent";
/// A login younger than this gets its session part from autostart, not from the daemon.
pub const AUTOSTART_GRACE_SECONDS: i64 = 30;
/// Session managers whose autostart programs carry the login's environment.
const SESSION_MANAGERS: [&str; 3] = ["cinnamon-sessio", "xfce4-session", "gnome-session-b"];
/// Variables of the login that are the service manager's or the shell's, not the login's.
const NOT_PASSED: [&str; 12] = [
    "INVOCATION_ID",
    "JOURNAL_STREAM",
    "MANAGERPID",
    "SYSTEMD_EXEC_PID",
    "NOTIFY_SOCKET",
    "LISTEN_PID",
    "LISTEN_FDS",
    "LISTEN_FDNAMES",
    "WATCHDOG_PID",
    "WATCHDOG_USEC",
    "PWD",
    "OLDPWD",
];

/// A graphical login: logind's session id, its user, when it started (Unix time) and its desktop (`DESKTOP=`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Login {
    pub id: String,
    pub uid: u32,
    pub user: String,
    pub started: Option<i64>,
    pub desktop: String,
}

/// The graphical logins of users, open (not closing), on any seat: the login screen's own session (CLASS=greeter) and
/// text logins (ssh) are left out.
pub fn graphical(sessions_dir: &Path) -> Vec<Login> {
    let Ok(entries) = fs::read_dir(sessions_dir) else {
        return Vec::new();
    };
    let mut found: Vec<Login> = entries
        .flatten()
        // Only the session files: logind keeps a FIFO `<id>.ref` beside each, and reading one blocks.
        .filter(|entry| entry.file_type().is_ok_and(|kind| kind.is_file()) && !entry.file_name().to_string_lossy().contains('.'))
        .filter_map(|entry| {
            let id = entry.file_name().to_str()?.to_string();
            if id.is_empty() || id.len() > 64 || !id.bytes().all(|byte| byte.is_ascii_alphanumeric()) {
                return None;
            }
            let text = fs::read_to_string(entry.path()).ok()?;
            parse_login(&id, &text)
        })
        .collect();
    found.sort_by(|a, b| a.id.cmp(&b.id));
    found
}

/// One session file, when it is a user's open graphical login.
pub fn parse_login(id: &str, text: &str) -> Option<Login> {
    let value = |key: &str| text.lines().find_map(|line| line.strip_prefix(key)?.strip_prefix('='));
    let graphical = matches!(value("TYPE"), Some("x11" | "wayland"));
    let user_class = value("CLASS").is_none_or(|class| class == "user");
    let open = matches!(value("STATE"), Some("active" | "online") | None);
    if !(graphical && user_class && open) {
        return None;
    }
    let uid: u32 = value("UID")?.parse().ok()?;
    let user = value("USER").filter(|user| status::valid_login(user)).map(str::to_string).or_else(|| status::login_name(uid))?;
    let started = value("REALTIME").and_then(|micros| micros.parse::<i64>().ok()).map(|micros| micros / 1_000_000);
    Some(Login { id: id.to_string(), uid, user, started, desktop: value("DESKTOP").unwrap_or_default().to_string() })
}

/// What the notice told a user: the machine id it was for, and the sections it listed.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Told {
    pub machine_id: String,
    pub sections: Vec<String>,
}

impl Told {
    /// Whether it covers every one of `sections` for this machine id.
    pub fn covers(&self, machine_id: &str, sections: &[String]) -> bool {
        self.machine_id == machine_id && sections.iter().all(|section| self.sections.contains(section))
    }
}

/// What a user's session part says the user was told (`notice.json` in their runtime folder), read as root in a folder
/// the user owns (no symlink, the user's own file, small).
pub fn told(run_user: &Path, uid: u32) -> Option<Told> {
    let path = run_user.join(uid.to_string()).join(RUNTIME_SUBDIR).join(NOTICE_FILE);
    let data = status::read_owned_file(&path, uid, 4096)?;
    let told: Told = serde_json::from_slice(&data).ok()?;
    let name_ok = |text: &str, max: usize| !text.is_empty() && text.len() <= max && text.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_');
    (name_ok(&told.machine_id, 64) && told.sections.len() <= 64 && told.sections.iter().all(|section| name_ok(section, 32))).then_some(told)
}

/// The environment of a login's own programs, to start its session part with: that of a program of the user whose
/// `XDG_SESSION_ID` is the login's and that has a display, best one that the session manager started (as autostart
/// starts the session part; the session manager's own environment lacks what it sets for its children, such as
/// `XDG_CURRENT_DESKTOP`). None when no such program is found.
pub fn environment(proc_root: &Path, login: &Login) -> Option<BTreeMap<String, String>> {
    let entries = fs::read_dir(proc_root).ok()?;
    let mut best: Option<(u32, u32, BTreeMap<String, String>)> = None;
    for entry in entries.flatten() {
        let Some(pid) = entry.file_name().to_str().and_then(|name| name.parse::<u32>().ok()) else {
            continue;
        };
        let dir = entry.path();
        if fs::metadata(&dir).map_or(true, |metadata| metadata.uid() != login.uid) {
            continue;
        }
        let Ok(raw) = fs::read(dir.join("environ")) else {
            continue;
        };
        if raw.len() > 256 * 1024 {
            continue;
        }
        let variables = parse_environ(&raw);
        if variables.get("XDG_SESSION_ID").map(String::as_str) != Some(login.id.as_str()) || !variables.contains_key("DISPLAY") && !variables.contains_key("WAYLAND_DISPLAY") {
            continue;
        }
        let parent_is_manager = parent_of(&dir)
            .and_then(|parent| fs::read_to_string(proc_root.join(parent.to_string()).join("comm")).ok())
            .is_some_and(|comm| SESSION_MANAGERS.contains(&comm.trim()));
        let score = u32::from(variables.contains_key("XDG_CURRENT_DESKTOP")) * 2 + u32::from(parent_is_manager);
        let better = match &best {
            None => true,
            Some((best_score, best_pid, _)) => score > *best_score || (score == *best_score && pid < *best_pid),
        };
        if better {
            best = Some((score, pid, variables));
        }
    }
    let (_, _, mut variables) = best?;
    variables.retain(|name, _| !NOT_PASSED.contains(&name.as_str()));
    if !variables.contains_key("XDG_CURRENT_DESKTOP") {
        // As the login's session file names it (DESKTOP=cinnamon or xfce).
        let desktop = match login.desktop.as_str() {
            "cinnamon" => "X-Cinnamon",
            "xfce" => "XFCE",
            _ => "",
        };
        if !desktop.is_empty() {
            variables.insert("XDG_CURRENT_DESKTOP".to_string(), desktop.to_string());
        }
    }
    Some(variables)
}

/// NAME=value pairs of a /proc environ file; names that a shell could not name are left out.
pub fn parse_environ(raw: &[u8]) -> BTreeMap<String, String> {
    raw.split(|byte| *byte == 0)
        .filter_map(|item| {
            let text = std::str::from_utf8(item).ok()?;
            let (name, value) = text.split_once('=')?;
            let valid = !name.is_empty()
                && name.len() <= 128
                && !name.starts_with(|c: char| c.is_ascii_digit())
                && name.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'_');
            (valid && value.len() <= 16 * 1024).then(|| (name.to_string(), value.to_string()))
        })
        .collect()
}

fn parent_of(dir: &Path) -> Option<u32> {
    let stat = fs::read_to_string(dir.join("stat")).ok()?;
    // pid (comm) state ppid ...: comm may hold spaces and brackets, so read after the last ')'.
    stat.rsplit_once(')')?.1.split_whitespace().nth(1)?.parse().ok()
}

/// The command that starts a login's session part as its user, under the user's systemd (so that it outlives neither
/// the user's logins nor a restart of the service, which would kill a child of its own): a transient unit
/// `caramos-business-session-<login>-<unix>`.
pub fn start_command(login: &Login, environment: &BTreeMap<String, String>, now: i64) -> Vec<String> {
    let mut command = vec![
        "--user".to_string(),
        format!("--machine={}@.host", login.user),
        "--quiet".to_string(),
        "--collect".to_string(),
        format!("--unit=caramos-business-session-{}-{now}", login.id),
        "--description=CaramOS Business, started in a login that was open at pairing".to_string(),
    ];
    for (name, value) in environment {
        command.push(format!("--setenv={name}={value}"));
    }
    command.push(AGENT_PROGRAM.to_string());
    command.push("session".to_string());
    command
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    const CINNAMON: &str = "# This is private data. Do not parse.\nUID=1000\nUSER=caram\nACTIVE=1\nIS_DISPLAY=1\nSTATE=active\n\
                            REMOTE=0\nTYPE=x11\nCLASS=user\nSEAT=seat0\nDISPLAY=:0\nSERVICE=lightdm-autologin\n\
                            DESKTOP=cinnamon\nVTNR=7\nLEADER=950\nREALTIME=1795447874366476\n";

    #[test]
    fn graphical_logins_only() {
        let login = parse_login("c1", CINNAMON).unwrap();
        assert_eq!(login, Login { id: "c1".into(), uid: 1000, user: "caram".into(), started: Some(1795447874), desktop: "cinnamon".into() });
        let ssh = CINNAMON.replace("TYPE=x11", "TYPE=tty");
        assert_eq!(parse_login("17", &ssh), None, "a text login");
        assert_eq!(parse_login("c2", &CINNAMON.replace("CLASS=user", "CLASS=greeter")), None, "the login screen");
        assert_eq!(parse_login("c1", &CINNAMON.replace("STATE=active", "STATE=closing")), None, "a login that ends");
        assert!(parse_login("c1", &CINNAMON.replace("STATE=active", "STATE=online")).is_some(), "locked by light-locker");

        let dir = TempDir::new("logins");
        fs::write(dir.path().join("c1"), CINNAMON).unwrap();
        fs::write(dir.path().join("17"), ssh).unwrap();
        fs::write(dir.path().join("c1.ref"), "").unwrap();
        assert_eq!(graphical(dir.path()).iter().map(|login| login.id.as_str()).collect::<Vec<_>>(), ["c1"]);
        assert!(graphical(&dir.path().join("none")).is_empty());
    }

    #[test]
    fn what_a_user_was_told() {
        let run_user = TempDir::new("told");
        let uid = crate::process::uid().unwrap();
        let folder = run_user.path().join(uid.to_string()).join(RUNTIME_SUBDIR);
        fs::create_dir_all(&folder).unwrap();
        assert_eq!(told(run_user.path(), uid), None);
        let id = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";
        fs::write(folder.join(NOTICE_FILE), format!(r#"{{"machine_id": "{id}", "sections": ["browser", "usb"]}}"#)).unwrap();
        let read = told(run_user.path(), uid).unwrap();
        let sections = |names: &[&str]| names.iter().map(|name| name.to_string()).collect::<Vec<_>>();
        assert!(read.covers(id, &sections(&["usb"])));
        assert!(read.covers(id, &sections(&["browser", "usb"])));
        assert!(!read.covers(id, &sections(&["browser", "firewall"])), "a section it did not list");
        assert!(!read.covers("11111111-2222-4333-8444-555555555555", &sections(&["usb"])), "another pairing");
        fs::write(folder.join(NOTICE_FILE), r#"{"machine_id": "../x", "sections": []}"#).unwrap();
        assert_eq!(told(run_user.path(), uid), None, "not a machine id");
        assert_eq!(told(run_user.path(), uid + 1), None, "another user's folder");
    }

    #[test]
    fn the_environment_of_the_logins_programs() {
        let proc_root = TempDir::new("proc");
        let uid = crate::process::uid().unwrap();
        let login = Login { id: "c1".into(), uid, user: "caram".into(), started: None, desktop: "cinnamon".into() };
        let process = |pid: u32, ppid: u32, comm: &str, environ: &str| {
            let dir = proc_root.path().join(pid.to_string());
            fs::create_dir_all(&dir).unwrap();
            fs::write(dir.join("comm"), format!("{comm}\n")).unwrap();
            fs::write(dir.join("stat"), format!("{pid} ({comm}) S {ppid} {pid} {pid} 0")).unwrap();
            fs::write(dir.join("environ"), environ.replace(' ', "\0")).unwrap();
        };
        assert_eq!(environment(proc_root.path(), &login), None, "no program of the login");
        // The session manager itself: the login's id and display, but not what it sets for its children.
        process(975, 950, "cinnamon-sessio", "XDG_SESSION_ID=c1 DISPLAY=:0 HOME=/home/caram LANG=vi_VN");
        let found = environment(proc_root.path(), &login).unwrap();
        assert_eq!(found.get("XDG_CURRENT_DESKTOP").map(String::as_str), Some("X-Cinnamon"), "from the session file");
        // A program it started has the rest; another login's program, and an ssh shell, are not looked at.
        process(1437, 975, "caramos-evoluti", "XDG_SESSION_ID=c1 DISPLAY=:0 XDG_CURRENT_DESKTOP=X-Cinnamon INVOCATION_ID=x 1BAD=y");
        process(2000, 1, "xterm", "XDG_SESSION_ID=c2 DISPLAY=:1 XDG_CURRENT_DESKTOP=XFCE");
        process(2001, 4330, "bash", "XDG_SESSION_ID=c1 HOME=/home/caram");
        let found = environment(proc_root.path(), &login).unwrap();
        assert_eq!(found.get("XDG_CURRENT_DESKTOP").map(String::as_str), Some("X-Cinnamon"));
        assert!(!found.contains_key("INVOCATION_ID") && !found.contains_key("1BAD"), "{found:?}");
        assert!(!found.contains_key("HOME"), "the autostart program's, not the manager's: {found:?}");

        let command = start_command(&login, &found, 1795500000);
        assert_eq!(&command[..5], ["--user", "--machine=caram@.host", "--quiet", "--collect", "--unit=caramos-business-session-c1-1795500000"]);
        assert!(command.contains(&"--setenv=XDG_SESSION_ID=c1".to_string()));
        assert_eq!(&command[command.len() - 2..], [AGENT_PROGRAM, "session"]);
    }
}
