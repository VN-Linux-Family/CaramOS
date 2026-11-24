//! The session part, `caramos-business-agent session` (the logged-in user, from /etc/xdg/autostart): applies this
//! machine's effective settings for the user (wallpaper, folders, shares, screen_lock), shows what the daemon
//! relays (messages, countdowns, remote help), and writes the user's status after each round.
//!
//! Rounds run at login, every 30 seconds, and at once when effective.json changes (its mtime is looked at every two
//! seconds, with the inbox). The part ends with its login session; a newer instance for the same user takes over from
//! an older one, such as one left from a session that ended without ending it.

use std::collections::BTreeMap;
use std::env;
use std::fs;
use std::io;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::clock::LocalTime;
use crate::folders::{Context, Folders};
use crate::inbox::{self, Inbox};
use crate::logging::{self, Once};
use crate::notices::Notices;
use crate::policy::FileEntry;
use crate::process;
use crate::prompt;
use crate::protocol::{
    truncate_chars, FoldersState, UserStatus, WallpaperState, AGENT_CONFIG, AGENT_STATE, INBOX_ROOT, MAX_DETAIL_CHARS,
    ROLE_FILE, RUNTIME_SUBDIR,
};
use crate::screenlock;
use crate::settings::{Effective, ShareLink};
use crate::shares::Shares;
use crate::status;
use crate::store::{self, EffectiveFile, Store};
use crate::wallpaper::{self, Desktop};

/// Between rounds.
pub const ROUND: Duration = Duration::from_secs(30);
/// How often effective.json's mtime, the inbox and the end of the session are looked at.
const POLL: Duration = Duration::from_secs(2);
/// The installed program, started again after an upgrade replaced it.
const AGENT_PROGRAM: &str = crate::logins::AGENT_PROGRAM;

/// What the session part remembers between logins: ~/.config/caramos-business/state.json.
#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SavedState {
    /// The company image this part set last and still wants: set again only when the wanted one changes (or, with
    /// `lock`, when the desktop shows another). None when it wants none.
    #[serde(default)]
    pub wallpaper: Option<String>,
    /// The shares (by URL, with the login name) whose Desktop got the local launchers already.
    #[serde(default)]
    pub launchers_copied: Vec<String>,
    /// The bookmark lines this part added for `shares`.
    #[serde(default)]
    pub bookmarks: Vec<String>,
    /// The screen lock keys' values before this part changed them: key id → value.
    #[serde(default)]
    pub screen_lock_before: BTreeMap<String, String>,
    /// What the user answered to the notice in 0.3.1 before the full test pass: kept as it is, and read by the notice
    /// (notices.rs) while its own notice-answered.json is missing.
    #[serde(default)]
    pub notice_for: Option<String>,
    #[serde(default)]
    pub notice_sections: Vec<String>,
}

impl SavedState {
    pub fn load(path: &Path) -> SavedState {
        store::read_limited(path, 64 * 1024)
            .ok()
            .and_then(|data| serde_json::from_slice(&data).ok())
            .unwrap_or_default()
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        if let Some(dir) = path.parent() {
            fs::create_dir_all(dir)?;
        }
        let mut data = serde_json::to_vec_pretty(self).map_err(io::Error::other)?;
        data.push(b'\n');
        store::write_atomic(path, &data, 0o644)
    }
}

pub fn main() -> ExitCode {
    logging::set_prefix("caramos-business-agent session: ");
    let ctx = match context_from_env() {
        Ok(ctx) => ctx,
        Err(error) => {
            log!("{error}");
            return ExitCode::FAILURE;
        }
    };
    let paths = SessionPaths {
        role: PathBuf::from(ROLE_FILE),
        agent_config: PathBuf::from(AGENT_CONFIG),
        inbox: PathBuf::from(INBOX_ROOT),
    };
    Session::new(ctx, Store::new(AGENT_STATE), paths).run()
}

/// The user's session from the environment that the session manager gives its autostart programs.
fn context_from_env() -> Result<Context, String> {
    let uid = process::uid().ok_or("cannot tell which user this is")?;
    let home = env::var_os("HOME").map(PathBuf::from).filter(|home| home.is_absolute()).ok_or("HOME is not set")?;
    let runtime_dir = env::var_os("XDG_RUNTIME_DIR")
        .map(PathBuf::from)
        .filter(|dir| dir.is_absolute())
        .unwrap_or_else(|| PathBuf::from(format!("/run/user/{uid}")));
    let login = ["USER", "LOGNAME"]
        .iter()
        .filter_map(|name| env::var(name).ok())
        .find(|login| status::valid_login(login))
        .or_else(|| status::login_name(uid))
        .ok_or("cannot tell the login name")?;
    let desktop = Desktop::from_xdg(&env::var("XDG_CURRENT_DESKTOP").unwrap_or_default());
    let language = ["LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"]
        .iter()
        .filter_map(|name| env::var(name).ok())
        .find(|value| !value.is_empty());
    Ok(Context { home, runtime_dir, login, uid, desktop, vietnamese: vietnamese(language.as_deref()) })
}

/// Whether a locale value (LANGUAGE, LC_ALL, LC_MESSAGES or LANG) is Vietnamese; with none set, it is.
pub fn vietnamese(locale: Option<&str>) -> bool {
    locale.is_none_or(|locale| locale.starts_with("vi"))
}

/// Whether the login session that started this part ended: the session manager went away (this part got another
/// parent), or logind marks the session as closing, or forgot it.
fn session_ended(parent: u32, session_id: Option<&str>) -> bool {
    if parent > 1 && std::os::unix::process::parent_id() != parent {
        return true;
    }
    let Some(id) = session_id else {
        return false;
    };
    let sessions = Path::new("/run/systemd/sessions");
    match fs::read_to_string(sessions.join(id)) {
        Ok(text) => text.lines().any(|line| line == "STATE=closing"),
        Err(error) => error.kind() == io::ErrorKind::NotFound && sessions.is_dir(),
    }
}

/// USER_STATUS's detail: the wallpaper's and the folders' notes, at most 200 characters.
pub fn detail(wallpaper: &str, folders: &str) -> String {
    let text = match (wallpaper.is_empty(), folders.is_empty()) {
        (true, true) => String::new(),
        (false, true) => format!("wallpaper: {wallpaper}"),
        (true, false) => folders.to_string(),
        (false, false) => format!("wallpaper: {wallpaper}; {folders}"),
    };
    truncate_chars(&text, MAX_DETAIL_CHARS)
}

/// Where the session part looks for the machine's role and pairing, and its inbox.
#[derive(Debug, Clone)]
pub struct SessionPaths {
    pub role: PathBuf,
    /// Only its presence is looked at: the file is root's.
    pub agent_config: PathBuf,
    pub inbox: PathBuf,
}

/// The session part of one login.
pub struct Session {
    ctx: Context,
    store: Store,
    paths: SessionPaths,
    state_file: PathBuf,
    pid_file: PathBuf,
    saved: SavedState,
    folders: Folders,
    shares: Shares,
    /// Read in a thread of its own (`inbox::spawn_reader`): requests from the admin do not wait for a round.
    inbox: Arc<Mutex<Inbox>>,
    /// Ends the inbox's thread, which stops every handler.
    inbox_stop: Arc<AtomicBool>,
    /// The company's notice is on the screen (its own thread, notices.rs, opens and closes it).
    notice_open: Arc<AtomicBool>,
    /// Held by the notice's thread while it opens or closes a window.
    notice_step: Arc<Mutex<()>>,
    /// Ends the notice's thread, which closes an open notice.
    notice_stop: Arc<AtomicBool>,
    /// The frozen machine's notice was asked for in this login.
    frozen_told: bool,
    wallpaper_problems: Once,
    status_problems: Once,
}

impl Session {
    pub fn new(ctx: Context, store: Store, paths: SessionPaths) -> Session {
        let state_file = ctx.home.join(".config/caramos-business/state.json");
        let pid_file = ctx.runtime_dir.join(RUNTIME_SUBDIR).join("session.pid");
        Session {
            saved: SavedState::load(&state_file),
            inbox: Arc::new(Mutex::new(Inbox::new(&paths.inbox, ctx.uid, &ctx.runtime_dir))),
            inbox_stop: Arc::new(AtomicBool::new(false)),
            notice_step: Arc::new(Mutex::new(())),
            ctx,
            store,
            paths,
            state_file,
            pid_file,
            folders: Folders::new(),
            shares: Shares::default(),
            notice_open: Arc::new(AtomicBool::new(false)),
            notice_stop: Arc::new(AtomicBool::new(false)),
            frozen_told: false,
            wallpaper_problems: Once::default(),
            status_problems: Once::default(),
        }
    }

    fn run(&mut self) -> ExitCode {
        if let Err(error) = self.claim() {
            log!("cannot write {}: {error}", self.pid_file.display());
        }
        let parent = std::os::unix::process::parent_id();
        let session_id = env::var("XDG_SESSION_ID")
            .ok()
            .filter(|id| !id.is_empty() && id.len() <= 64 && id.bytes().all(|byte| byte.is_ascii_alphanumeric()));
        let mut last_mtime: Option<SystemTime> = None;
        let mut next_round = Instant::now();
        let mut clone_logged = false;
        let mut restart_tried = false;
        self.start_threads(session_id.clone(), parent);
        loop {
            if !restart_tried && process::program_replaced() {
                // A package upgrade replaced the program: the new one takes over this login (same process), once no
                // prompt or remote help runs, instead of the old code running until the user logs out. The other
                // threads' locks are held to the end, so that neither starts a window meanwhile.
                let _notice = inbox::lock(&self.notice_step);
                let requests = inbox::lock(&self.inbox);
                if may_restart(restart_tried, requests.busy(), self.notice_open.load(Ordering::SeqCst), || true) {
                    restart_tried = true;
                    log!("the agent was updated; the session part starts again with the new program");
                    let error = std::process::Command::new(AGENT_PROGRAM).arg("session").exec();
                    log!("cannot start {AGENT_PROGRAM} session: {error}");
                }
            }
            if session_ended(parent, session_id.as_deref()) {
                log!("the login session ended");
                self.inbox_stop.store(true, Ordering::SeqCst);
                inbox::lock(&self.inbox).stop_all();
                self.notice_stop.store(true, Ordering::SeqCst);
                self.folders.end_of_session(&self.ctx);
                thread::sleep(Duration::from_secs(1));
                self.release();
                return ExitCode::SUCCESS;
            }
            if !self.still_ours() {
                log!("a newer session part runs for this user; this one ends");
                self.inbox_stop.store(true, Ordering::SeqCst);
                inbox::lock(&self.inbox).stop_all();
                // Its notice too: the newer part shows it while the user has not answered it (not two side by side).
                self.notice_stop.store(true, Ordering::SeqCst);
                thread::sleep(Duration::from_secs(1));
                return ExitCode::SUCCESS;
            }
            if self.store.is_clone() {
                // The daemon found this disk to be a clone: nothing is applied, and nothing put back either, but the
                // user's own Desktop and Documents (the server's links lead nowhere on a clone).
                if !clone_logged {
                    log!("{}", crate::daemon::CLONE_MESSAGE);
                    clone_logged = true;
                    next_round = Instant::now();
                }
                if Instant::now() >= next_round {
                    self.folders.put_back_local(&self.ctx);
                    next_round = Instant::now() + ROUND;
                }
                // No prompt or remote help goes on: the inbox's thread sees the clone too.
                thread::sleep(POLL);
                continue;
            }
            if clone_logged {
                next_round = Instant::now(); // paired here again: a round at once
            }
            clone_logged = false;
            // Requests from the admin and the notice have threads of their own, which stop what they opened once the
            // machine is no longer the company's (left, removed, leaving, a clone).
            if self.effective().is_some() {
                self.tell_frozen(session_id.as_deref());
            }
            let mtime = fs::metadata(self.store.effective_path()).and_then(|metadata| metadata.modified()).ok();
            if Instant::now() >= next_round || mtime != last_mtime || self.folders.tidy_finished() {
                last_mtime = mtime;
                self.round();
                next_round = Instant::now() + ROUND;
            }
            thread::sleep(POLL);
        }
    }

    /// The threads of the login besides the rounds: the company's notice (notices.rs) and the inbox (inbox.rs), so that
    /// neither waits for a round, which can wait minutes on a share's sign-in window. Both end by themselves once the
    /// login is no longer this part's (a newer part's pid file, or the login ended; `parent` as in run()), as the
    /// main loop would only after its round.
    fn start_threads(&mut self, session_id: Option<String>, parent: u32) -> (thread::JoinHandle<()>, thread::JoinHandle<()>) {
        let ours = {
            let (pid_file, session_id) = (self.pid_file.clone(), session_id.clone());
            move || names_this_process(&pid_file) && !session_ended(parent, session_id.as_deref())
        };
        let notice = Notices::new(&self.ctx.home, &self.ctx.runtime_dir, self.store.clone(), self.paths.clone(), Arc::clone(&self.notice_open))
            .spawn(Arc::clone(&self.notice_step), Arc::clone(&self.notice_stop), ours.clone());
        let context = inbox::Context {
            desktop: self.ctx.desktop,
            runtime_dir: self.ctx.runtime_dir.clone(),
            session_id,
            vietnamese: self.ctx.vietnamese,
        };
        let (paths, store) = (self.paths.clone(), self.store.clone());
        let reader = inbox::spawn_reader(Arc::clone(&self.inbox), context, move || managed_here(&paths, &store), ours, Arc::clone(&self.inbox_stop));
        (notice, reader)
    }

    /// On a frozen machine, each user at each login: `caramos-business --prompt frozen` ("Máy này tự xóa mọi thay đổi khi
    /// khởi động lại…", PROTOCOL.md part 3 "Freeze"). The login is told once, even when this part starts again in it
    /// (an upgrade): the login session's id is kept in the runtime folder.
    fn tell_frozen(&mut self, session_id: Option<&str>) {
        if self.frozen_told {
            return;
        }
        self.frozen_told = true;
        if !crate::sections::shared::frozen_in(&fs::read_to_string("/proc/self/mounts").unwrap_or_default()) {
            return;
        }
        let marker = self.ctx.runtime_dir.join(RUNTIME_SUBDIR).join("frozen-told");
        let login = session_id.unwrap_or("login").to_string();
        if fs::read_to_string(&marker).is_ok_and(|told| told.trim() == login) {
            return;
        }
        let _ = store::write_atomic(&marker, format!("{login}\n").as_bytes(), 0o600);
        thread::spawn(|| {
            let never = AtomicBool::new(false);
            let _ = prompt::ask("frozen", &[], None, &never);
        });
    }

    /// This machine's effective settings, on a paired employee machine only: after leaving the company, settings left
    /// behind apply no more.
    fn effective(&self) -> Option<EffectiveFile> {
        let role = fs::read_to_string(&self.paths.role).unwrap_or_default();
        if role.trim() != "employee" || !self.paths.agent_config.exists() || !self.store.policy_path().exists() {
            return None;
        }
        // A machine that left while frozen finishes leaving at the next boot: its disk still holds the pairing and the
        // policy until the daemon is done, and the login must not show the company's notice meanwhile (it did, with
        // "từ máy ?", on the copy that left).
        if self.store.leave_pending_path().exists() {
            return None;
        }
        self.store.load_effective()
    }

    /// One round: the wallpaper, the folders, the shares, the screen lock, then the status file. The notice has its own
    /// thread (notices.rs).
    pub fn round(&mut self) -> UserStatus {
        let file = self.effective();
        let effective = file.as_ref().map(|file| Effective::from_json(&file.settings)).unwrap_or_default();
        let files = file.as_ref().map(|file| file.files.clone()).unwrap_or_default();
        let now = LocalTime::now();
        let before = self.saved.clone();
        let mut applied = BTreeMap::new();

        let (wallpaper, wallpaper_detail) = self.wallpaper_round(effective.wallpaper.as_ref(), &files, now);
        if effective.wallpaper.is_some() {
            applied.insert("wallpaper".to_string(), outcome(wallpaper == WallpaperState::Failed, &wallpaper_detail));
        }
        let (folders, folders_detail) =
            self.folders.round(effective.folders.as_ref(), &self.ctx, &now.date(), &mut self.saved.launchers_copied);
        if effective.folders.is_some() {
            applied.insert("folders".to_string(), outcome(folders == FoldersState::Failed, &folders_detail));
        }
        let shares: Option<&[ShareLink]> = effective.shares.as_deref();
        if let Some(result) = self.shares.round(shares, &self.ctx.home, &self.ctx.login, &self.ctx.gvfs_dir(), &mut self.saved.bookmarks) {
            if shares.is_some() {
                applied.insert("shares".to_string(), crate::sections::outcome(&result));
            }
        }
        if let Some(result) = screenlock::apply(self.ctx.desktop, effective.screen_lock.as_ref(), &mut self.saved.screen_lock_before) {
            if effective.screen_lock.is_some() {
                applied.insert("screen_lock".to_string(), crate::sections::outcome(&result));
            }
        }
        if self.saved != before {
            if let Err(error) = self.saved.save(&self.state_file) {
                log!("cannot write {}: {error}", self.state_file.display());
            }
        }
        let status = UserStatus {
            user: self.ctx.login.clone(),
            wallpaper,
            folders,
            detail: detail(&wallpaper_detail, &folders_detail),
            time: now.iso8601(),
        };
        let screen_lock_on = screenlock::is_on(self.ctx.desktop, self.ctx.uid);
        match status::write(&self.ctx.runtime_dir, &status, &applied, screen_lock_on) {
            Ok(()) => self.status_problems.clear(""),
            Err(error) => self.status_problems.log(&format!("cannot write the status: {error}")),
        }
        status
    }

    /// Today's company image, applied when the wanted image changed or, with `lock`, when the desktop shows another.
    fn wallpaper_round(&mut self, wallpaper: Option<&crate::policy::Wallpaper>, files: &Map<String, Value>, now: LocalTime) -> (WallpaperState, String) {
        let wanted = wallpaper.and_then(|wallpaper| wallpaper.image_for(now.month_day()));
        let (Some(wallpaper), Some(sha)) = (wallpaper, wanted) else {
            // Nothing to show today: the user's own wallpaper stays, and the next company image is set when it comes.
            self.saved.wallpaper = None;
            let detail = if wallpaper.is_some() { "no company wallpaper today" } else { "" };
            return (WallpaperState::Off, detail.to_string());
        };
        let Some(file) = files.get(sha).and_then(|file| serde_json::from_value::<FileEntry>(file.clone()).ok()) else {
            return (WallpaperState::Failed, format!("{sha} is not listed in the policy"));
        };
        let image = self.store.file_path(sha, &file);
        if !image.is_file() {
            return (WallpaperState::Failed, format!("{} is not downloaded yet", image.display()));
        }
        let desktop = self.ctx.desktop;
        let changed = self.saved.wallpaper.as_deref() != Some(sha);
        let apply = if changed {
            Ok(true)
        } else if wallpaper.lock {
            wallpaper::shows(desktop, &image).map(|shows| !shows)
        } else {
            Ok(false)
        };
        match apply.and_then(|apply| if apply { wallpaper::set(desktop, &image).map(|()| true) } else { Ok(false) }) {
            Ok(applied) => {
                if applied {
                    log!("wallpaper: {}", image.display());
                    self.saved.wallpaper = Some(sha.to_string());
                }
                self.wallpaper_problems.clear("");
                (WallpaperState::Applied, String::new())
            }
            Err(error) => {
                self.wallpaper_problems.log(&format!("wallpaper: {error}"));
                (WallpaperState::Failed, error)
            }
        }
    }

    /// Makes this the user's session part: its pid in `$XDG_RUNTIME_DIR/caramos-business/session.pid`.
    fn claim(&self) -> io::Result<()> {
        if let Some(dir) = self.pid_file.parent() {
            fs::create_dir_all(dir)?;
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(dir, fs::Permissions::from_mode(0o700))?;
        }
        store::write_atomic(&self.pid_file, format!("{}\n", std::process::id()).as_bytes(), 0o644)
    }

    /// Whether the pid file still names this process (a newer instance writes its own).
    fn still_ours(&self) -> bool {
        names_this_process(&self.pid_file)
    }

    fn release(&self) {
        if self.still_ours() {
            let _ = fs::remove_file(&self.pid_file);
        }
    }
}

/// Whether `pid_file` names this process, or is missing (a newer session part writes its own).
fn names_this_process(pid_file: &Path) -> bool {
    match fs::read_to_string(pid_file) {
        Ok(text) => text.trim() == std::process::id().to_string(),
        Err(_) => true,
    }
}

/// Whether this is a paired employee machine with effective settings, not leaving and not a clone: the session
/// part's threads act for the company only then (as `Session::effective`, without reading the settings).
pub fn managed_here(paths: &SessionPaths, store: &Store) -> bool {
    let role = fs::read_to_string(&paths.role).unwrap_or_default();
    role.trim() == "employee"
        && paths.agent_config.exists()
        && store.policy_path().exists()
        && store.effective_path().exists()
        && !store.leave_pending_path().exists()
        && !store.is_clone()
}

/// The sections the effective settings turn on (not null), sorted.
pub fn managed_sections(settings: &Map<String, Value>) -> Vec<String> {
    let mut sections: Vec<String> = settings.iter().filter(|(_, value)| !value.is_null()).map(|(key, _)| key.clone()).collect();
    sections.sort();
    sections
}

/// Whether the session part may start again with the upgraded program: once, and only while nothing it opened is on
/// the screen. An open notice counts: the new program knows nothing of it and would open a second one beside it (seen
/// in the 0.3 end-to-end pass: two "Máy này do công ty quản lý" windows after the agent was updated twice).
fn may_restart(tried: bool, busy: bool, notice_open: bool, replaced: impl FnOnce() -> bool) -> bool {
    !tried && !busy && !notice_open && replaced()
}

/// A section's outcome for the health report.
fn outcome(failed: bool, detail: &str) -> String {
    if failed {
        format!("failed: {}", truncate_chars(detail, 120))
    } else {
        "ok".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;
    use serde_json::json;

    const SHA: &str = "a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7";

    #[test]
    fn restart_waits_for_open_windows() {
        assert!(may_restart(false, false, false, || true));
        assert!(!may_restart(false, false, true, || true), "an open notice would be shown twice");
        assert!(!may_restart(false, true, false, || true), "a prompt or remote help runs");
        assert!(!may_restart(true, false, false, || true), "tried once already");
        assert!(!may_restart(false, false, false, || false), "the program is the same");
        assert!(!may_restart(false, false, true, || panic!("not looked at while a window is open")));
    }

    #[test]
    fn details_and_languages() {
        assert_eq!(detail("", ""), "");
        assert_eq!(detail("x", ""), "wallpaper: x");
        assert_eq!(detail("", "y"), "y");
        assert_eq!(detail("x", "y"), "wallpaper: x; y");
        assert_eq!(detail(&"é".repeat(300), "").chars().count(), 200);
        assert!(vietnamese(Some("vi_VN.UTF-8")));
        assert!(vietnamese(Some("vi:en")));
        assert!(!vietnamese(Some("en_US.UTF-8")));
        assert!(vietnamese(None));
    }

    /// A session part of a paired machine whose share for Desktop and Documents asks for a password, with the sign-in
    /// window open for good: a round waits `wait` on it. Its threads run, as run() starts them.
    fn waiting_on_sign_in(root: &Path, wait: Duration) -> (Session, Context, SessionPaths, (thread::JoinHandle<()>, thread::JoinHandle<()>)) {
        use crate::folders::Mount;
        use std::os::unix::fs::PermissionsExt;

        let store = Store::new(root.join("state"));
        let uid = process::uid().unwrap();
        let ctx = Context { home: root.join("home"), runtime_dir: root.join("run"), login: "lan".into(), uid, desktop: Desktop::Other, vietnamese: true };
        let paths = SessionPaths { role: root.join("role"), agent_config: root.join("agent.json"), inbox: root.join("inbox") };
        fs::write(&paths.role, "employee\n").unwrap();
        fs::write(&paths.agent_config, "{}").unwrap();
        store.save("{}").unwrap();
        let id = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";
        let folders = json!({"folders": {"share": "smb://nas.congty.local/nhanvien/%u", "tidy": false}});
        let effective = EffectiveFile { serial: 3, machine_id: id.into(), department: None, admin_name: "quan-ly".into(), files: Map::new(), settings: serde_json::from_value(folders).unwrap() };
        store.save_effective(&effective).unwrap();
        // The user was told about the folders already: no notice window in these tests.
        let config = ctx.home.join(".config/caramos-business");
        fs::create_dir_all(&config).unwrap();
        fs::write(config.join("notice-answered.json"), format!(r#"{{"notice_for": "{id}", "notice_sections": ["folders"]}}"#)).unwrap();
        // The share asks for a password, and the sign-in window stays open.
        let sign_in = root.join("sign-in");
        fs::write(&sign_in, "#!/bin/sh\nsleep 30\n").unwrap();
        fs::set_permissions(&sign_in, fs::Permissions::from_mode(0o755)).unwrap();
        let mut session = Session::new(ctx.clone(), store, paths.clone());
        session.folders.mounter = |_| Mount::NeedsPassword;
        session.folders.connect_program = sign_in;
        session.folders.connect_wait = wait;
        let threads = session.start_threads(None, std::os::unix::process::parent_id());
        (session, ctx, paths, threads)
    }

    /// Stops what waiting_on_sign_in started.
    fn stop_waiting(mut session: Session) {
        session.inbox_stop.store(true, Ordering::SeqCst);
        session.notice_stop.store(true, Ordering::SeqCst);
        if let Some(mut window) = session.folders.connect.take() {
            let _ = window.kill();
            let _ = window.wait();
        }
    }

    #[test]
    fn requests_go_through_while_the_sign_in_window_waits() {
        // 0.3.1 read the inbox between rounds: while the window that signs in to the company's share was open, a round
        // waited up to 2 minutes for the share, and a lock, a message or remote help from the admin waited with it.
        use crate::relay::{Answer, InboxEntry};

        let root = TempDir::new("sign-in-wait");
        let (mut session, ctx, paths, _threads) = waiting_on_sign_in(root.path(), Duration::from_secs(6));
        // The admin locks the machine a moment after the round started waiting on the window.
        let request = "00000000-0000-4000-8000-000000000061";
        let (inbox_root, uid) = (paths.inbox.clone(), ctx.uid);
        let admin = thread::spawn(move || {
            thread::sleep(Duration::from_millis(500));
            let entry = InboxEntry { id: request.into(), action: "lock".into(), args: json!({}), admin_name: "quan-ly".into(), expires: 0 };
            crate::relay::deliver(&inbox_root, uid, None, &entry).unwrap();
        });
        let started = SystemTime::now();
        let status = session.round();
        let round_took = started.elapsed().unwrap();
        admin.join().unwrap();
        assert!(round_took >= Duration::from_secs(5), "the round waited on the sign-in window: {round_took:?}");
        assert_eq!(status.folders, FoldersState::Local, "the window is still open: {}", status.detail);
        let answer = ctx.runtime_dir.join("caramos-business/outbox").join(format!("{request}.json"));
        let answered = fs::metadata(&answer).unwrap().modified().unwrap().duration_since(started).unwrap();
        assert!(answered < Duration::from_secs(3), "the lock was answered after {answered:?}, while the round still waited");
        let reply: Answer = serde_json::from_slice(&fs::read(&answer).unwrap()).unwrap();
        assert_eq!(reply.state, "failed", "a test has no desktop to lock: {}", reply.detail);
        stop_waiting(session);
    }

    #[test]
    fn a_newer_part_takes_the_requests_while_this_one_waits() {
        // A newer session part takes the login over (the user logged in again) while this part's round waits on the
        // sign-in window: this part's threads end at once and leave the requests to the newer part, not both acting.
        use crate::relay::InboxEntry;

        let root = TempDir::new("sign-in-takeover");
        let (mut session, ctx, paths, (notice, reader)) = waiting_on_sign_in(root.path(), Duration::from_secs(5));
        let request = "00000000-0000-4000-8000-000000000065";
        let (inbox_root, uid, pid_file) = (paths.inbox.clone(), ctx.uid, session.pid_file.clone());
        let newer = thread::spawn(move || {
            thread::sleep(Duration::from_millis(500));
            fs::create_dir_all(pid_file.parent().unwrap()).unwrap();
            fs::write(&pid_file, format!("{}\n", std::process::id() + 1)).unwrap();
            thread::sleep(Duration::from_millis(1500));
            let entry = InboxEntry { id: request.into(), action: "lock".into(), args: json!({}), admin_name: "quan-ly".into(), expires: 0 };
            crate::relay::deliver(&inbox_root, uid, None, &entry).unwrap();
        });
        let status = session.round();
        newer.join().unwrap();
        assert_eq!(status.folders, FoldersState::Local, "the round still waited: {}", status.detail);
        assert!(notice.is_finished() && reader.is_finished(), "both threads ended while the round waited");
        let answer = ctx.runtime_dir.join("caramos-business/outbox").join(format!("{request}.json"));
        assert!(!answer.exists(), "the request delivered after the takeover is the newer part's");
        stop_waiting(session);
    }

    #[test]
    fn a_round_writes_the_status() {
        let root = TempDir::new("session");
        let state = root.path().join("state");
        let store = Store::new(&state);
        let ctx = Context {
            home: root.path().join("home"),
            runtime_dir: root.path().join("run"),
            login: "lan".into(),
            uid: process::uid().unwrap(),
            // Neither Cinnamon nor Xfce: no desktop tool runs in the test.
            desktop: Desktop::Other,
            vietnamese: true,
        };
        let paths = SessionPaths { role: root.path().join("role"), agent_config: root.path().join("agent.json"), inbox: root.path().join("inbox") };
        fs::write(&paths.role, "employee\n").unwrap();
        fs::write(&paths.agent_config, "{}").unwrap();
        let mut session = Session::new(ctx, store.clone(), paths.clone());

        // No policy: nothing to do.
        let status = session.round();
        assert_eq!((status.wallpaper, status.folders), (WallpaperState::Off, FoldersState::Off));
        let written: UserStatus =
            serde_json::from_slice(&fs::read(root.path().join("run/caramos-business/status.json")).unwrap()).unwrap();
        assert_eq!(written, status);

        // Effective settings whose image is every day's: on this desktop it cannot be applied, and the status says so.
        store.save("{}").unwrap();
        let effective = EffectiveFile {
            serial: 2,
            machine_id: "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6".into(),
            department: None,
            admin_name: "may-quan-ly".into(),
            files: serde_json::from_value(json!({SHA: {"size": 31, "type": "jpg"}})).unwrap(),
            settings: serde_json::from_value(json!({"wallpaper": {"default": null, "periods": [{"name": "all", "from": "01-01", "to": "12-31", "image": SHA}], "lock": true}})).unwrap(),
        };
        store.save_effective(&effective).unwrap();
        let status = session.round();
        assert_eq!(status.wallpaper, WallpaperState::Failed);
        assert!(status.detail.contains("not downloaded"), "{}", status.detail);
        fs::write(state.join(format!("files/{SHA}.jpg")), "not really a jpeg, a test file\n").unwrap();
        let status = session.round();
        assert_eq!(status.wallpaper, WallpaperState::Failed);
        assert!(status.detail.contains("neither Cinnamon nor Xfce"), "{}", status.detail);
        assert_eq!(status.user, "lan");
        let applied = status::parse_applied(&fs::read(root.path().join("run/caramos-business/status.json")).unwrap());
        assert!(applied["wallpaper"].starts_with("failed: "));

        // No longer an employee machine: the settings left behind are not applied.
        fs::write(&paths.role, "admin\n").unwrap();
        let status = session.round();
        assert_eq!((status.wallpaper, status.folders), (WallpaperState::Off, FoldersState::Off));
        fs::write(&paths.role, "employee\n").unwrap();
        assert_eq!(session.round().wallpaper, WallpaperState::Failed, "an employee machine again");
        // Left while frozen: until the next boot finishes leaving, the disk's pairing and policy apply no more.
        fs::write(store.leave_pending_path(), r#"{"reason": "leave", "admin_name": "quan-ly", "time": ""}"#).unwrap();
        assert_eq!(session.round().wallpaper, WallpaperState::Off);
        fs::remove_file(store.leave_pending_path()).unwrap();
        fs::remove_file(&paths.agent_config).unwrap();
        assert_eq!(session.round().wallpaper, WallpaperState::Off);
    }
}
