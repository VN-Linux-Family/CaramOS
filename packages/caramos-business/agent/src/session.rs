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
use std::sync::mpsc::{self, Receiver};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::clock::LocalTime;
use crate::folders::{Context, Folders};
use crate::inbox::{self, Inbox};
use crate::logging::{self, Once};
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
const AGENT_PROGRAM: &str = "/usr/lib/caramos-business/caramos-business-agent";

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
    /// The machine id for which the user saw the notice after pairing.
    #[serde(default)]
    pub notice_for: Option<String>,
    /// The sections the company managed when the user saw the notice: it comes back when another one is turned on.
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

/// The notice on the screen: the machine id and the sections it lists, its answer, and the flag that closes it.
struct NoticeShown {
    machine_id: String,
    sections: Vec<String>,
    answer: Receiver<bool>,
    close: Arc<AtomicBool>,
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
    inbox: Inbox,
    /// The notice, while it is on the screen.
    notice: Option<NoticeShown>,
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
            inbox: Inbox::new(&paths.inbox, ctx.uid, &ctx.runtime_dir),
            ctx,
            store,
            paths,
            state_file,
            pid_file,
            folders: Folders::new(),
            shares: Shares::default(),
            notice: None,
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
        loop {
            if may_restart(restart_tried, self.inbox.busy(), self.notice.is_some(), process::program_replaced) {
                // A package upgrade replaced the program: the new one takes over this login (same process), once no
                // prompt or remote help runs, instead of the old code running until the user logs out.
                restart_tried = true;
                log!("the agent was updated; the session part starts again with the new program");
                let error = std::process::Command::new(AGENT_PROGRAM).arg("session").exec();
                log!("cannot start {AGENT_PROGRAM} session: {error}");
            }
            if session_ended(parent, session_id.as_deref()) {
                log!("the login session ended");
                self.inbox.stop_all();
                self.folders.end_of_session(&self.ctx);
                thread::sleep(Duration::from_secs(1));
                self.release();
                return ExitCode::SUCCESS;
            }
            if !self.still_ours() {
                log!("a newer session part runs for this user; this one ends");
                self.inbox.stop_all();
                return ExitCode::SUCCESS;
            }
            if self.store.is_clone() {
                // The daemon found this disk to be a clone: nothing is applied, and nothing put back either.
                if !clone_logged {
                    log!("{}", crate::daemon::CLONE_MESSAGE);
                    clone_logged = true;
                }
                self.inbox.stop_all();
                self.close_notice();
                thread::sleep(POLL);
                continue;
            }
            clone_logged = false;
            let effective = self.effective();
            if effective.is_some() {
                let context = inbox::Context {
                    desktop: self.ctx.desktop,
                    runtime_dir: self.ctx.runtime_dir.clone(),
                    session_id: session_id.clone(),
                    vietnamese: self.ctx.vietnamese,
                };
                self.inbox.poll(&context);
                self.tell_frozen(session_id.as_deref());
            } else {
                // The machine left the company (or has no policy): no prompt, notice or remote help goes on.
                self.inbox.stop_all();
                self.close_notice();
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

    /// One round: the wallpaper, the folders, the shares, the screen lock, the notice, then the status file.
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
        if let Some(file) = &file {
            self.notice_round(&file.machine_id, &managed_sections(&file.settings));
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

    /// The notice: what the company manages and what it never collects. Each user sees it after pairing, and again
    /// when the company turns on a section they were not told about (staff must know the measures used on their
    /// machines, PROTOCOL.md part 2 "Transparency").
    fn notice_round(&mut self, machine_id: &str, sections: &[String]) {
        if !needs_notice(&self.saved, machine_id, sections) {
            return;
        }
        if let Some(shown) = &self.notice {
            match shown.answer.try_recv() {
                Ok(true) => {
                    self.saved.notice_for = Some(shown.machine_id.clone());
                    self.saved.notice_sections = shown.sections.clone();
                    self.notice = None;
                }
                Ok(false) | Err(mpsc::TryRecvError::Disconnected) => self.notice = None,
                Err(mpsc::TryRecvError::Empty) => {}
            }
            return;
        }
        let (sender, answer) = mpsc::channel();
        let close = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&close);
        thread::spawn(move || {
            let _ = sender.send(prompt::ask("notice", &[], None, &flag).is_ok());
        });
        self.notice = Some(NoticeShown { machine_id: machine_id.to_string(), sections: sections.to_vec(), answer, close });
    }

    /// Closes the notice when the machine is no longer the company's: it is not answered, so it comes back if the
    /// machine is paired again.
    fn close_notice(&mut self) {
        if let Some(shown) = self.notice.take() {
            shown.close.store(true, Ordering::SeqCst);
        }
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
        match fs::read_to_string(&self.pid_file) {
            Ok(text) => text.trim() == std::process::id().to_string(),
            Err(_) => true,
        }
    }

    fn release(&self) {
        if self.still_ours() {
            let _ = fs::remove_file(&self.pid_file);
        }
    }
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

/// Whether the user is to see the notice: not yet for this pairing, or a section is on that it did not list.
pub fn needs_notice(saved: &SavedState, machine_id: &str, sections: &[String]) -> bool {
    saved.notice_for.as_deref() != Some(machine_id)
        || sections.iter().any(|section| !saved.notice_sections.contains(section))
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

    #[test]
    fn the_notice_comes_back_for_a_new_section() {
        let id = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";
        let settings: Map<String, Value> =
            serde_json::from_value(json!({"usb": {"storage": "block"}, "browser": null, "inventory": {"enabled": true}})).unwrap();
        let sections = managed_sections(&settings);
        assert_eq!(sections, ["inventory", "usb"]);
        let mut saved = SavedState::default();
        assert!(needs_notice(&saved, id, &sections), "after pairing");
        saved.notice_for = Some(id.into());
        saved.notice_sections = vec!["inventory".into(), "usb".into()];
        assert!(!needs_notice(&saved, id, &sections), "seen");
        assert!(!needs_notice(&saved, id, &sections[..1]), "a section turned off");
        assert!(needs_notice(&saved, id, &["browser".to_string(), "usb".to_string()]), "a section turned on");
        assert!(needs_notice(&saved, "11111111-2222-4333-8444-555555555555", &sections), "paired again");
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
        // The notice is not asked for in this test.
        session.saved.notice_for = Some("7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6".into());
        session.saved.notice_sections = vec!["wallpaper".into()];

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
