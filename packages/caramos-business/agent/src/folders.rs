//! Desktop and Documents on the company's server (PROTOCOL.md "Folders"), in the user's session.
//!
//! Setting up mounts the share's root with `gio mount` (through `caramos-business --connect` when it needs a
//! password), makes `Desktop` and `Documents` in the user's folder of its GVfs FUSE mount, links
//! `~/.local/share/caramos-business/server/Desktop` and `…/Documents` to them, points XDG_DESKTOP_DIR and
//! XDG_DOCUMENTS_DIR at the links (see userdirs.rs for why links) and restarts the desktop-icons program. When the
//! share cannot be reached, the user's own folders come back, a notification says so once per login, and the setup
//! is tried again every 5 minutes. It runs once per login, again when `folders` changes, when the mount goes away,
//! and when user-dirs.dirs or the links no longer point at the share.

use std::fs;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, Instant};

use crate::policy;
use crate::process;
use crate::protocol::FoldersState;
use crate::tidy::{self, Launchers};
use crate::userdirs::UserDirs;
use crate::wallpaper::Desktop;

/// gio mount gives up on a server that does not answer well before this.
const MOUNT_TIMEOUT: Duration = Duration::from_secs(90);
/// How long the password window may take (PROTOCOL.md: at most 2 minutes).
const CONNECT_WAIT: Duration = Duration::from_secs(120);
/// A share that could not be reached is tried again after this.
pub const RETRY: Duration = Duration::from_secs(5 * 60);
/// A FUSE folder that does not answer in this time counts as gone.
const PROBE_TIMEOUT: Duration = Duration::from_secs(15);
const TOOL_TIMEOUT: Duration = Duration::from_secs(20);
/// The window that asks for the share's password and can keep it in the keyring.
const CONNECT_PROGRAM: &str = "caramos-business";

/// PROTOCOL.md "Folders", step 4.
pub const UNREACHABLE_VI: &str = "Không kết nối được thư mục trên máy chủ: tạm lưu trên máy này.";
/// The same for the English edition (CaramOS Xfce runs in English).
pub const UNREACHABLE_EN: &str = "Cannot connect to the folders on the server: saving on this computer for now.";

/// A share's URL as the folders part uses it: `smb://host[:port]/share[/rest]`, `%u` replaced by the login name.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Share {
    pub host: String,
    pub port: Option<u16>,
    /// The shared folder's name, percent-decoded.
    pub share: String,
    /// The path inside it, percent-decoded, one name per folder.
    pub rest: Vec<String>,
    /// smb://host[:port]/share, as written: what `gio mount` mounts.
    root_url: String,
    /// The whole URL with the login name in it: what this user's folder is known by.
    url: String,
}

impl Share {
    /// Parses a share's URL for `login`. Stricter than the policy's checks: the host must be a host name or an IPv4
    /// address, and every folder name must be usable in a path and in user-dirs.dirs.
    pub fn parse(url: &str, login: &str) -> Result<Share, String> {
        policy::check_share(url).map_err(|error| error.0)?;
        if !valid_login(login) {
            return Err(format!("the login name {login:?} cannot be used in a path"));
        }
        let rest = &url["smb://".len()..];
        let (authority, path) = rest.split_once('/').unwrap_or((rest, ""));
        let (host, port) = match authority.rsplit_once(':') {
            Some((host, port)) => {
                let port = port.parse::<u16>().ok().filter(|port| *port > 0).ok_or("the share's port is not valid")?;
                (host, Some(port))
            }
            None => (authority, None),
        };
        if !valid_host(host) {
            return Err(format!("the share's server {host:?} is not a host name or an IPv4 address"));
        }
        let parts: Vec<String> = path.split('/').filter(|part| !part.is_empty()).map(|part| part.replace("%u", login)).collect();
        let Some((share_written, rest_written)) = parts.split_first() else {
            return Err("the share's URL names no shared folder (smb://server/share)".to_string());
        };
        let share = decode_name(share_written)?;
        let rest = rest_written.iter().map(|part| decode_name(part)).collect::<Result<Vec<_>, _>>()?;
        Ok(Share {
            host: host.to_string(),
            port,
            share,
            rest,
            root_url: format!("smb://{authority}/{share_written}"),
            url: format!("smb://{authority}/{}", parts.join("/")),
        })
    }

    pub fn root_url(&self) -> &str {
        &self.root_url
    }

    pub fn url(&self) -> &str {
        &self.url
    }

    /// The name gvfsd-fuse gives the share's mount: `smb-share:server=<host>,share=<share>`. As GVfs makes it, the
    /// keys are in alphabetical order, server and share case-folded, and the values escaped as in a URI.
    pub fn fuse_name(&self) -> String {
        let mut name = String::from("smb-share:");
        if let Some(port) = self.port {
            name.push_str(&format!("port={port},"));
        }
        name.push_str("server=");
        name.push_str(&gvfs_escape(&self.host.to_lowercase()));
        name.push_str(",share=");
        name.push_str(&gvfs_escape(&self.share.to_lowercase()));
        name
    }

    /// `$XDG_RUNTIME_DIR/gvfs/smb-share:server=<host>,share=<share>/<rest>`: the user's folder on the share.
    pub fn fuse_path(&self, runtime_dir: &Path) -> PathBuf {
        within(runtime_dir.join("gvfs").join(self.fuse_name()), &self.rest)
    }

    /// The share's mounted folder under `gvfs`: the computed name when it is there, else an entry naming the same
    /// server and share in another spelling (case, escaping, a user or domain added).
    pub fn find_mount(&self, gvfs: &Path) -> Option<PathBuf> {
        let computed = gvfs.join(self.fuse_name());
        if probe_dir(&computed, PROBE_TIMEOUT) {
            return Some(computed);
        }
        for entry in fs::read_dir(gvfs).ok()?.flatten() {
            let name = entry.file_name();
            let Some(items) = name.to_str().and_then(|name| name.strip_prefix("smb-share:")) else {
                continue;
            };
            let value = |key: &str| {
                items.split(',').find_map(|item| item.strip_prefix(key)?.strip_prefix('=')).and_then(percent_decode)
            };
            let same = |found: Option<String>, wanted: &str| found.is_some_and(|found| found.to_lowercase() == wanted.to_lowercase());
            if same(value("server"), &self.host) && same(value("share"), &self.share) {
                return Some(entry.path());
            }
        }
        None
    }
}

fn within(mut path: PathBuf, parts: &[String]) -> PathBuf {
    for part in parts {
        path.push(part);
    }
    path
}

/// A host name (letters, digits, hyphens, dots) or an IPv4 address.
fn valid_host(host: &str) -> bool {
    !host.is_empty()
        && host.len() <= 253
        && host.split('.').all(|label| {
            !label.is_empty()
                && label.len() <= 63
                && label.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
                && !label.starts_with('-')
                && !label.ends_with('-')
        })
}

/// A login name that can go into a path.
fn valid_login(login: &str) -> bool {
    !login.is_empty()
        && login.len() <= 64
        && login != "."
        && login != ".."
        && !login.chars().any(|c| c.is_control() || matches!(c, '/' | '"' | '\\' | '$' | '`' | '%'))
}

/// One folder name of the URL, percent-decoded: not empty, not `.` or `..`, nothing that cannot be in a path or in
/// user-dirs.dirs.
fn decode_name(written: &str) -> Result<String, String> {
    let name = percent_decode(written).ok_or_else(|| format!("{written:?} is not a valid folder name"))?;
    let bad = name.is_empty()
        || name == "."
        || name == ".."
        || name.chars().any(|c| c.is_control() || matches!(c, '/' | '"' | '\\' | '$' | '`'));
    if bad {
        return Err(format!("{written:?} is not a valid folder name"));
    }
    Ok(name)
}

/// `%XX` escapes decoded; None when one is broken or the result is not UTF-8.
fn percent_decode(text: &str) -> Option<String> {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            let hex = bytes.get(index + 1..index + 3)?;
            if !hex.iter().all(u8::is_ascii_hexdigit) {
                return None;
            }
            out.push(u8::from_str_radix(std::str::from_utf8(hex).ok()?, 16).ok()?);
            index += 3;
        } else {
            out.push(bytes[index]);
            index += 1;
        }
    }
    String::from_utf8(out).ok()
}

/// GVfs's escaping of mount spec values (`g_mount_spec_to_string`): unreserved characters, `$&'()*+` and non-ASCII
/// UTF-8 stay, everything else becomes %XX.
fn gvfs_escape(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for c in value.chars() {
        if c.is_ascii_alphanumeric() || "-._~$&'()*+".contains(c) || !c.is_ascii() {
            out.push(c);
        } else {
            out.push_str(&format!("%{:02X}", c as u32));
        }
    }
    out
}

/// Whether `path` is a folder, asked in a thread: a FUSE folder of a server that stopped answering can hang.
fn probe_dir(path: &Path, timeout: Duration) -> bool {
    let (sender, receiver) = mpsc::channel();
    let path = path.to_path_buf();
    thread::spawn(move || {
        let _ = sender.send(path.is_dir());
    });
    receiver.recv_timeout(timeout).unwrap_or(false)
}

/// gio mount's outcome.
#[derive(Debug, PartialEq, Eq)]
pub enum Mount {
    Done,
    NeedsPassword,
    Failed(String),
}

/// Runs `gio mount <url>` with stdin closed: a share that needs a password makes it prompt, read nothing and stop.
pub fn gio_mount(url: &str) -> Mount {
    let mut command = Command::new("gio");
    // gio's own prompts in English for asked_for_password; the GVfs daemon's messages, in the session's language,
    // stay readable in UTF-8.
    command.args(["mount", url]).env("LC_ALL", "C.UTF-8");
    match process::run_command(command, MOUNT_TIMEOUT) {
        Err(error) => Mount::Failed(format!("gio: {error}")),
        Ok(output) if output.success() => Mount::Done,
        Ok(output) if asked_for_password(&output.stdout) => Mount::NeedsPassword,
        Ok(output) => Mount::Failed(output.message()),
    }
}

/// Whether gio mount prompted for credentials: "User [name]: ", "Domain [WORKGROUP]: ", "Password: ".
pub fn asked_for_password(stdout: &str) -> bool {
    stdout.lines().any(|line| {
        let line = line.trim_start();
        line.starts_with("User") || line.starts_with("Domain") || line.starts_with("Password")
    })
}

/// Why the share could not be mounted.
#[derive(Debug)]
enum MountFailure {
    /// The server did not answer.
    Unreachable(String),
    /// It needs a password and none was given.
    NoPassword,
    Failed(String),
}

/// The user's session as the folders part needs it.
#[derive(Debug, Clone)]
pub struct Context {
    pub home: PathBuf,
    pub runtime_dir: PathBuf,
    pub login: String,
    pub uid: u32,
    pub desktop: Desktop,
    /// Whether to speak Vietnamese (else English, as on CaramOS Xfce).
    pub vietnamese: bool,
}

impl Context {
    /// `$XDG_RUNTIME_DIR/gvfs`, where GVfs's FUSE daemon shows the mounts.
    pub fn gvfs_dir(&self) -> PathBuf {
        self.runtime_dir.join("gvfs")
    }

    fn user_dirs(&self) -> UserDirs {
        UserDirs::new(&self.home)
    }
}

#[derive(Debug)]
enum State {
    /// The policy has no folders.
    Off,
    /// Desktop and Documents are on the server, in `target` (the user's folder on the share).
    Server { wanted: policy::Folders, target: PathBuf, url: String },
    /// They are on this machine because of `state` and `detail`; tried again at `retry_at` (None: only when the
    /// policy changes).
    Away { wanted: policy::Folders, state: FoldersState, detail: String, retry_at: Option<Instant> },
}

/// A tidy running in its thread.
struct Tidying {
    url: String,
    copy_launchers: bool,
    thread: thread::JoinHandle<tidy::Report>,
}

/// The folders part of one login.
pub struct Folders {
    state: State,
    /// The password window started by this part, while it is open.
    connect: Option<Child>,
    /// The password window was closed without a mount: it is not opened again in this login.
    password_refused: bool,
    /// The user was told that the folders are local; once per login.
    notified: bool,
    tidying: Option<Tidying>,
    last_tidy: Option<tidy::Report>,
}

impl Default for Folders {
    fn default() -> Self {
        Folders::new()
    }
}

impl Folders {
    pub fn new() -> Folders {
        Folders { state: State::Off, connect: None, password_refused: false, notified: false, tidying: None, last_tidy: None }
    }

    /// One round: sets the folders up, keeps them, or falls back to the local ones. `launchers_copied` lists the
    /// shares (by URL) whose Desktop already got the local launchers; `today` is YYYY-MM-DD.
    pub fn round(
        &mut self,
        wanted: Option<&policy::Folders>,
        ctx: &Context,
        today: &str,
        launchers_copied: &mut Vec<String>,
    ) -> (FoldersState, String) {
        self.finish_tidy(launchers_copied);
        // A password window closed since the last round: after a mount, the next setup finds the mount before it
        // would ask; without one, the user said no, and is not asked again in this login.
        if let Some(connect) = &mut self.connect {
            if !matches!(connect.try_wait(), Ok(None)) {
                self.connect = None;
                self.password_refused = true;
            }
        }
        let Some(wanted) = wanted else {
            let user_dirs = ctx.user_dirs();
            if !matches!(self.state, State::Off) || user_dirs.needs_restore(&ctx.gvfs_dir()) {
                self.restore_local(ctx);
            }
            self.state = State::Off;
            return (FoldersState::Off, String::new());
        };
        let set_up_again = match &self.state {
            State::Server { wanted: was, target, .. } if was == wanted => {
                if probe_dir(target, PROBE_TIMEOUT) {
                    // Set up again when something else changed user-dirs.dirs or the links (xdg-user-dirs-update,
                    // the user): applied means both point at the share.
                    !ctx.user_dirs().points_at_server(&target.join("Desktop"), &target.join("Documents"))
                } else {
                    self.state = self.fall_back(ctx, wanted, FoldersState::Local, "the share is no longer reachable".into());
                    false
                }
            }
            State::Away { wanted: was, retry_at, .. } if was == wanted => retry_at.is_some_and(|at| Instant::now() >= at),
            _ => true,
        };
        if set_up_again {
            self.state = self.set_up(wanted, ctx, today, launchers_copied);
        }
        self.report()
    }

    /// The state and detail for USER_STATUS.
    fn report(&self) -> (FoldersState, String) {
        match &self.state {
            State::Off => (FoldersState::Off, String::new()),
            State::Server { url, .. } => {
                let mut detail = format!("Desktop and Documents on {url}");
                if self.tidying.is_some() {
                    detail.push_str("; tidying");
                } else if let Some(report) = self.last_tidy.as_ref().filter(|report| report.moved + report.failed > 0) {
                    detail.push_str(&format!("; tidy moved {} files", report.moved));
                    if report.failed > 0 {
                        detail.push_str(&format!(", {} could not move", report.failed));
                    }
                }
                (FoldersState::Server, detail)
            }
            State::Away { state, detail, .. } => (*state, detail.clone()),
        }
    }

    /// Whether a tidy ended since the last round (the status then has news).
    pub fn tidy_finished(&self) -> bool {
        self.tidying.as_ref().is_some_and(|tidying| tidying.thread.is_finished())
    }

    fn set_up(
        &mut self,
        wanted: &policy::Folders,
        ctx: &Context,
        today: &str,
        launchers_copied: &[String],
    ) -> State {
        let share = match Share::parse(&wanted.share, &ctx.login) {
            Ok(share) => share,
            Err(error) => return self.fall_back(ctx, wanted, FoldersState::Failed, error),
        };
        let mount = match self.mount(&share, ctx) {
            Ok(mount) => mount,
            Err(MountFailure::Unreachable(error)) => {
                return self.fall_back(ctx, wanted, FoldersState::Local, format!("{} cannot be reached: {error}", share.root_url()))
            }
            Err(MountFailure::NoPassword) => {
                return self.fall_back(ctx, wanted, FoldersState::Local, format!("no password for {}", share.root_url()))
            }
            Err(MountFailure::Failed(error)) => return self.fall_back(ctx, wanted, FoldersState::Failed, error),
        };
        let target = within(mount, &share.rest);
        let desktop = target.join("Desktop");
        let documents = target.join("Documents");
        if let Err(error) = fs::create_dir_all(&desktop).and_then(|()| fs::create_dir_all(&documents)) {
            let detail = format!("cannot make Desktop and Documents in {}: {error}", share.url());
            return self.fall_back(ctx, wanted, FoldersState::Failed, detail);
        }
        let user_dirs = ctx.user_dirs();
        let pointed =
            user_dirs.backup_once(&ctx.gvfs_dir()).and_then(|()| user_dirs.point_at_server(&desktop, &documents));
        match pointed {
            Ok(changed) => {
                log!("Desktop and Documents are on {}", share.url());
                if changed {
                    restart_desktop_icons(ctx.desktop, ctx.uid);
                }
            }
            Err(error) => {
                let detail = format!("cannot point Desktop and Documents at {}: {error}", share.url());
                return self.fall_back(ctx, wanted, FoldersState::Failed, detail);
            }
        }
        if wanted.tidy {
            self.start_tidy(ctx, &share, &target, today, launchers_copied);
        }
        State::Server { wanted: wanted.clone(), target, url: share.url().to_string() }
    }

    /// The share's FUSE folder, mounting the share first if needed.
    fn mount(&mut self, share: &Share, ctx: &Context) -> Result<PathBuf, MountFailure> {
        let gvfs = ctx.gvfs_dir();
        if let Some(mount) = share.find_mount(&gvfs) {
            return Ok(mount);
        }
        match gio_mount(share.root_url()) {
            Mount::Done => wait_for(|| share.find_mount(&gvfs), Duration::from_secs(10))
                .ok_or_else(|| MountFailure::Failed(format!("{} is mounted but not in {}", share.root_url(), gvfs.display()))),
            Mount::Failed(error) => Err(MountFailure::Unreachable(error)),
            Mount::NeedsPassword => self.ask_password(share, &gvfs),
        }
    }

    /// Opens `caramos-business --connect <url>`, which asks for the password and mounts, and waits for the mount
    /// at most 2 minutes. A window still open then stays open: a later round picks up its mount.
    fn ask_password(&mut self, share: &Share, gvfs: &Path) -> Result<PathBuf, MountFailure> {
        if self.password_refused {
            return Err(MountFailure::NoPassword);
        }
        if self.connect.is_none() {
            let started = Command::new(CONNECT_PROGRAM)
                .arg("--connect")
                .arg(share.root_url())
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .process_group(0)
                .spawn();
            match started {
                Ok(child) => self.connect = Some(child),
                Err(error) => return Err(MountFailure::Failed(format!("cannot start {CONNECT_PROGRAM} --connect: {error}"))),
            }
        }
        let deadline = Instant::now() + CONNECT_WAIT;
        loop {
            if let Some(mount) = share.find_mount(gvfs) {
                return Ok(mount);
            }
            let closed = self.connect.as_mut().is_none_or(|child| !matches!(child.try_wait(), Ok(None)));
            if closed {
                self.connect = None;
                // Closed without mounting: cancelled, or the password was wrong.
                if let Some(mount) = wait_for(|| share.find_mount(gvfs), Duration::from_secs(3)) {
                    return Ok(mount);
                }
                self.password_refused = true;
                return Err(MountFailure::NoPassword);
            }
            if Instant::now() >= deadline {
                return Err(MountFailure::NoPassword);
            }
            thread::sleep(Duration::from_secs(1));
        }
    }

    /// Puts the user's own folders back and says so once per login. The setup is tried again after RETRY, except
    /// for a share's URL that this machine cannot use, which only a new policy changes.
    fn fall_back(&mut self, ctx: &Context, wanted: &policy::Folders, state: FoldersState, detail: String) -> State {
        log!("Desktop and Documents stay on this machine: {detail}");
        self.restore_local(ctx);
        if !self.notified {
            notify(ctx);
            self.notified = true;
        }
        let parse_error = Share::parse(&wanted.share, &ctx.login).is_err();
        let retry_at = (!parse_error).then(|| Instant::now() + RETRY);
        State::Away { wanted: wanted.clone(), state, detail, retry_at }
    }

    /// Points Desktop and Documents at the user's own folders again, restarting the desktop icons if that changed.
    fn restore_local(&self, ctx: &Context) {
        match ctx.user_dirs().restore(&ctx.gvfs_dir()) {
            Ok(true) => restart_desktop_icons(ctx.desktop, ctx.uid),
            Ok(false) => {}
            Err(error) => log!("cannot put the local Desktop and Documents back: {error}"),
        }
    }

    /// At the end of the login: the user's own folders back in user-dirs.dirs, so that the next login starts from
    /// them (xdg-user-dirs-update would point a missing server folder at the home folder).
    pub fn end_of_session(&self, ctx: &Context) {
        if ctx.user_dirs().needs_restore(&ctx.gvfs_dir()) {
            if let Err(error) = ctx.user_dirs().restore(&ctx.gvfs_dir()) {
                log!("cannot put the local Desktop and Documents back: {error}");
            }
        }
    }

    fn start_tidy(&mut self, ctx: &Context, share: &Share, target: &Path, today: &str, launchers_copied: &[String]) {
        if self.tidying.is_some() {
            return;
        }
        let (desktop, documents) = ctx.user_dirs().local_dirs(&ctx.gvfs_dir());
        let mut sources = vec![desktop.clone()];
        if documents != desktop {
            sources.push(documents);
        }
        sources.retain(|source| tidy::safe_source(source, &ctx.home, target));
        let copy_launchers = !launchers_copied.iter().any(|url| url == share.url()) && sources.contains(&desktop);
        let launchers = copy_launchers.then(|| Launchers { from: desktop, to: target.join("Desktop") });
        let unsorted = target.join(tidy::UNSORTED).join(today);
        let thread = thread::spawn(move || tidy::tidy(&sources, &unsorted, launchers.as_ref()));
        self.tidying = Some(Tidying { url: share.url().to_string(), copy_launchers, thread });
    }

    fn finish_tidy(&mut self, launchers_copied: &mut Vec<String>) {
        if !self.tidy_finished() {
            return;
        }
        let Some(tidying) = self.tidying.take() else {
            return;
        };
        let Ok(report) = tidying.thread.join() else {
            log!("the tidy stopped unexpectedly; nothing more was moved");
            return;
        };
        if report.moved + report.copied + report.failed > 0 {
            log!(
                "tidy: {} files moved to {}, {} launchers copied, {} could not move",
                report.moved,
                tidy::UNSORTED,
                report.copied,
                report.failed
            );
            for error in &report.errors {
                log!("tidy: {error}");
            }
        }
        if tidying.copy_launchers && report.launchers_done && !launchers_copied.contains(&tidying.url) {
            launchers_copied.push(tidying.url);
        }
        self.last_tidy = Some(report);
    }
}

/// `found()` as soon as it gives something, or None after `limit`.
fn wait_for<T>(found: impl Fn() -> Option<T>, limit: Duration) -> Option<T> {
    let deadline = Instant::now() + limit;
    loop {
        if let Some(value) = found() {
            return Some(value);
        }
        if Instant::now() >= deadline {
            return None;
        }
        thread::sleep(Duration::from_millis(500));
    }
}

/// Restarts the desktop-icons program so that it shows the new Desktop: GLib reads user-dirs.dirs once per
/// program. Only when it runs, since the user may have turned the desktop icons off.
pub fn restart_desktop_icons(desktop: Desktop, uid: u32) {
    let program = match desktop {
        Desktop::Cinnamon => "nemo-desktop",
        Desktop::Xfce => "xfdesktop",
        Desktop::Other => return,
    };
    let uid = uid.to_string();
    let running = || process::run("pgrep", &["-u", &uid, "-x", program], TOOL_TIMEOUT).is_ok_and(|output| output.success());
    if !running() {
        return;
    }
    let _ = process::run(program, &["--quit"], TOOL_TIMEOUT);
    if wait_for(|| (!running()).then_some(()), Duration::from_secs(5)).is_none() {
        let _ = process::run("pkill", &["-u", &uid, "-x", program], TOOL_TIMEOUT);
        let _ = wait_for(|| (!running()).then_some(()), Duration::from_secs(3));
    }
    // Cinnamon's session may have started it again already; a second one then just ends.
    match process::spawn_detached(program, &[]) {
        Ok(()) => log!("restarted {program}"),
        Err(error) => log!("cannot start {program}: {error}"),
    }
}

/// The notification of step 4.
fn notify(ctx: &Context) {
    let message = if ctx.vietnamese { UNREACHABLE_VI } else { UNREACHABLE_EN };
    let _ = process::run(
        "notify-send",
        &["--app-name=CaramOS Doanh nghiệp", "--icon=folder-remote", message],
        TOOL_TIMEOUT,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    #[test]
    fn fuse_path_of_the_example_policy() {
        let share = Share::parse("smb://nas.congty.local/nhanvien/%u", "lan").unwrap();
        assert_eq!(share.root_url(), "smb://nas.congty.local/nhanvien");
        assert_eq!(share.url(), "smb://nas.congty.local/nhanvien/lan");
        assert_eq!(
            share.fuse_path(Path::new("/run/user/1000")),
            PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas.congty.local,share=nhanvien/lan")
        );
    }

    #[test]
    fn fuse_names() {
        let path = |url: &str, login: &str| Share::parse(url, login).unwrap().fuse_path(Path::new("/run/user/1001"));
        // GVfs case-folds server and share names; the rest keeps its case.
        assert_eq!(
            path("smb://NAS/KeToan/Phong%20Ke%20Toan/%u", "Binh"),
            PathBuf::from("/run/user/1001/gvfs/smb-share:server=nas,share=ketoan/Phong Ke Toan/Binh")
        );
        // A home share named after the user, an IPv4 address with a port, a share name with reserved characters.
        assert_eq!(path("smb://10.0.0.5/%u", "lan"), PathBuf::from("/run/user/1001/gvfs/smb-share:server=10.0.0.5,share=lan"));
        assert_eq!(
            path("smb://10.0.0.5:4445/data/", "lan"),
            PathBuf::from("/run/user/1001/gvfs/smb-share:port=4445,server=10.0.0.5,share=data")
        );
        assert_eq!(
            path("smb://nas/a%2Cb%3Dc/x", "lan"),
            PathBuf::from("/run/user/1001/gvfs/smb-share:server=nas,share=a%2Cb%3Dc/x")
        );
        assert_eq!(
            path("smb://nas/t%C3%A0i-li%E1%BB%87u", "lan"),
            PathBuf::from("/run/user/1001/gvfs/smb-share:server=nas,share=tài-liệu")
        );
    }

    #[test]
    fn shares_this_machine_cannot_use() {
        for (url, login) in [
            ("smb://nas", "lan"),
            ("smb://nas/", "lan"),
            ("smb://[::1]/share", "lan"),
            ("smb://nas_server/share", "lan"),
            ("smb://nas/share/%2E%2E", "lan"),
            ("smb://nas/share/a%2Fb", "lan"),
            ("smb://nas/share/%ZZ", "lan"),
            ("smb://nas/share/%u", "a\"b"),
            ("smb://nas/c$/x", "lan"),
            ("smb://nas:0/share", "lan"),
            ("http://nas/share", "lan"),
        ] {
            assert!(Share::parse(url, login).is_err(), "{url} {login}");
        }
    }

    #[test]
    fn mounts_are_found_in_any_spelling() {
        let runtime = TempDir::new("gvfs");
        let gvfs = runtime.path().join("gvfs");
        let share = Share::parse("smb://NAS.local/Data/%u", "lan").unwrap();
        assert_eq!(share.find_mount(&gvfs), None);
        fs::create_dir_all(gvfs.join("smb-share:domain=CONGTY,server=NAS.local,share=Data,user=lan")).unwrap();
        assert_eq!(
            share.find_mount(&gvfs),
            Some(gvfs.join("smb-share:domain=CONGTY,server=NAS.local,share=Data,user=lan"))
        );
        fs::create_dir_all(gvfs.join("smb-share:server=nas.local,share=data")).unwrap();
        assert_eq!(share.find_mount(&gvfs), Some(gvfs.join("smb-share:server=nas.local,share=data")));
    }

    #[test]
    fn password_prompts() {
        assert!(asked_for_password("Authentication Required\nEnter user and password for share “s” on “nas”:\nUser [lan]: \n"));
        assert!(asked_for_password("Password required for share s on nas\nPassword: \n"));
        assert!(!asked_for_password(""));
    }
}
