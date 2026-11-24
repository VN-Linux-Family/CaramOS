//! The session part's side of the relay (see relay.rs): every second it reads its inbox, acts on each entry once (a
//! prompt, in a thread of its own), and writes its answer to its outbox, where the daemon finds it. A cancel entry
//! closes the prompt of the command it names. The ids taken are remembered in the runtime folder, so that a restart
//! of the session part does not act twice.
//!
//! The inbox is read in a thread of its own (`spawn_reader`), apart from the session part's rounds: a round can wait
//! minutes (2 on the window that signs in to a share, 90 s on a server that does not answer), and 0.3.1 read the inbox
//! only between rounds, so a lock, a message or remote help waited that long.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use crate::clock;
use crate::process;
use crate::prompt::{self, NoAnswer};
use crate::protocol::{OUTBOX, RUNTIME_SUBDIR};
use crate::relay::{self, Answer, InboxEntry};
use crate::remotehelp;
use crate::store;
use crate::wallpaper::Desktop;

/// A countdown's prompt gets this long beyond its seconds before the session part gives up on it.
const COUNTDOWN_SLACK: Duration = Duration::from_secs(30);
/// How often the inbox is read.
pub const READ_EVERY: Duration = Duration::from_secs(1);
const TOOL_TIMEOUT: Duration = Duration::from_secs(30);

/// What the handlers need from the session.
#[derive(Debug, Clone)]
pub struct Context {
    pub desktop: Desktop,
    pub runtime_dir: PathBuf,
    pub session_id: Option<String>,
    /// Whether to speak Vietnamese (else English, as on CaramOS Xfce).
    pub vietnamese: bool,
}

/// A ticket's status as the user reads it.
pub fn status_label(status: &str, vietnamese: bool) -> &'static str {
    match (status, vietnamese) {
        ("new", true) => "Mới",
        ("working", true) => "Đang xử lý",
        ("waiting", true) => "Chờ bạn trả lời",
        ("done", true) => "Đã xong",
        ("new", false) => "New",
        ("working", false) => "In progress",
        ("waiting", false) => "Waiting for your reply",
        ("done", false) => "Done",
        (_, true) => "Có cập nhật",
        (_, false) => "Updated",
    }
}

/// The notification of a ticket's change: its title ("Phiếu HT-0007: Đang xử lý") and the newest text.
pub fn ticket_notification(args: &serde_json::Value, vietnamese: bool) -> Option<(String, String)> {
    let ticket = args["ticket"].as_str().filter(|ticket| ticket.starts_with("HT-") && ticket.len() <= 20)?;
    let label = status_label(args["status"].as_str().unwrap_or_default(), vietnamese);
    let title = if vietnamese { format!("Phiếu {ticket}: {label}") } else { format!("Ticket {ticket}: {label}") };
    let text: String = args["text"].as_str().unwrap_or_default().chars().take(500).collect();
    Some((title, text))
}

/// The arguments of a countdown prompt: `--action A --seconds N [--postpones-left K --postpone-minutes M]`.
pub fn countdown_options(args: &serde_json::Value) -> Option<Vec<String>> {
    let action = args["action"].as_str().filter(|action| matches!(*action, "shutdown" | "restart" | "logout" | "suspend"))?;
    let seconds = args["seconds"].as_u64()?;
    let mut options = vec!["--action".to_string(), action.to_string(), "--seconds".to_string(), seconds.to_string()];
    if let (Some(left), Some(minutes)) = (args["postpones_left"].as_u64(), args["postpone_minutes"].as_u64()) {
        if left > 0 {
            options.extend(["--postpones-left".to_string(), left.to_string(), "--postpone-minutes".to_string(), minutes.to_string()]);
        }
    }
    Some(options)
}

/// The arguments of a message prompt: `--title T --body B --admin NAME [--ack]`.
pub fn message_options(args: &serde_json::Value, admin_name: &str) -> Option<Vec<String>> {
    let mut options = vec![
        "--title".to_string(),
        args["title"].as_str()?.to_string(),
        "--body".to_string(),
        args["body"].as_str()?.to_string(),
        "--admin".to_string(),
        admin_name.to_string(),
    ];
    if args["ack"].as_bool() == Some(true) {
        options.push("--ack".to_string());
    }
    Some(options)
}

/// The session part's inbox and outbox.
pub struct Inbox {
    root: PathBuf,
    uid: u32,
    outbox: PathBuf,
    taken_file: PathBuf,
    taken: BTreeSet<String>,
    running: Arc<Mutex<BTreeMap<String, Arc<AtomicBool>>>>,
}

impl Inbox {
    pub fn new(root: &Path, uid: u32, runtime_dir: &Path) -> Inbox {
        let folder = runtime_dir.join(RUNTIME_SUBDIR);
        let taken_file = folder.join("taken");
        let taken = fs::read_to_string(&taken_file).map(|text| text.lines().map(str::to_string).collect()).unwrap_or_default();
        Inbox { root: root.to_path_buf(), uid, outbox: folder.join(OUTBOX), taken_file, taken, running: Arc::default() }
    }

    /// Acts on the new entries, closes the cancelled prompts, and forgets the entries the daemon withdrew.
    pub fn poll(&mut self, context: &Context) {
        let entries = relay::inbox(&self.root, self.uid);
        let now = clock::unix_now();
        let mut changed = false;
        for entry in &entries {
            if entry.action == "cancel" {
                if let Some(target) = entry.args["id"].as_str() {
                    if let Some(flag) = self.running.lock().unwrap_or_else(|p| p.into_inner()).get(target) {
                        flag.store(true, Ordering::SeqCst);
                    }
                }
                continue;
            }
            if self.taken.contains(&entry.id) || (entry.expires > 0 && now > entry.expires) {
                continue;
            }
            self.taken.insert(entry.id.clone());
            changed = true;
            self.start(entry.clone(), context.clone());
        }
        // The daemon took its entries back: their ids are free to forget.
        let present: BTreeSet<&String> = entries.iter().map(|entry| &entry.id).collect();
        let running = self.running.lock().unwrap_or_else(|p| p.into_inner()).keys().cloned().collect::<BTreeSet<_>>();
        let before = self.taken.len();
        self.taken.retain(|id| present.contains(id) || running.contains(id));
        changed |= self.taken.len() != before;
        if changed {
            let text = self.taken.iter().fold(String::new(), |text, id| text + id + "\n");
            let _ = store::write_atomic(&self.taken_file, text.as_bytes(), 0o600);
        }
    }

    /// Whether a prompt or remote help is running.
    pub fn busy(&self) -> bool {
        !self.running.lock().unwrap_or_else(|p| p.into_inner()).is_empty()
    }

    /// Stops every running handler (the end of the session).
    pub fn stop_all(&self) {
        for flag in self.running.lock().unwrap_or_else(|p| p.into_inner()).values() {
            flag.store(true, Ordering::SeqCst);
        }
    }
}

/// A lock that a panicked thread does not poison for the others.
pub fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

/// Reads `inbox` every second in a thread of its own while `managed()` says the machine is the company's, and stops
/// every handler while it is not (it left, it is leaving, it is a clone). It ends, stopping them too, at `stop` or
/// once `ours()` says the login is no longer this session part's (a newer part took it over, or the login ended),
/// also while the part's round still waits: two parts never take the same request. Whoever holds the inbox's lock
/// keeps it from starting anything (the session part, before it starts again with an upgraded program).
pub fn spawn_reader(
    inbox: Arc<Mutex<Inbox>>,
    context: Context,
    managed: impl Fn() -> bool + Send + 'static,
    ours: impl Fn() -> bool + Send + 'static,
    stop: Arc<AtomicBool>,
) -> thread::JoinHandle<()> {
    thread::Builder::new()
        .name("inbox".into())
        .spawn(move || {
            while !stop.load(Ordering::SeqCst) {
                {
                    let mut inbox = lock(&inbox);
                    if !ours() {
                        break;
                    }
                    if managed() {
                        inbox.poll(&context);
                    } else {
                        inbox.stop_all();
                    }
                }
                thread::sleep(READ_EVERY);
            }
            lock(&inbox).stop_all();
        })
        .expect("a thread")
}

impl Inbox {
    fn start(&self, entry: InboxEntry, context: Context) {
        let cancel = Arc::new(AtomicBool::new(false));
        self.running.lock().unwrap_or_else(|p| p.into_inner()).insert(entry.id.clone(), Arc::clone(&cancel));
        let running = Arc::clone(&self.running);
        let outbox = self.outbox.clone();
        thread::spawn(move || {
            // A ticket's notification needs no answer (PROTOCOL.md part 3 "Helpdesk tickets").
            if let Some(answer) = handle(&entry, &context, &cancel) {
                if let Err(error) = write_answer(&outbox, &answer) {
                    log!("cannot write the answer to {}: {error}", entry.id);
                }
            }
            running.lock().unwrap_or_else(|p| p.into_inner()).remove(&entry.id);
        });
    }
}

/// Writes an answer into the outbox (the folder 0700, the file replaced atomically).
pub fn write_answer(outbox: &Path, answer: &Answer) -> std::io::Result<()> {
    fs::create_dir_all(outbox)?;
    fs::set_permissions(outbox, fs::Permissions::from_mode(0o700))?;
    let data = serde_json::to_vec(answer).map_err(std::io::Error::other)?;
    store::write_atomic(&outbox.join(format!("{}.json", answer.id)), &data, 0o644)
}

fn reply(id: &str, state: &str, detail: impl Into<String>, given: &str) -> Answer {
    Answer { id: id.to_string(), state: state.to_string(), detail: detail.into(), answer: given.to_string() }
}

/// Acts on one entry and says how it went (nothing for a ticket's notification).
fn handle(entry: &InboxEntry, context: &Context, cancel: &AtomicBool) -> Option<Answer> {
    let id = entry.id.as_str();
    if entry.action == "ticket" {
        if let Some((title, text)) = ticket_notification(&entry.args, context.vietnamese) {
            let mut args = vec!["--app-name=CaramOS Doanh nghiệp", "--icon=help-browser", title.as_str()];
            if !text.is_empty() {
                args.push(text.as_str());
            }
            if let Err(error) = process::run("notify-send", &args, TOOL_TIMEOUT) {
                log!("notify-send: {error}");
            }
        }
        return None;
    }
    Some(match entry.action.as_str() {
        "message" => {
            let Some(options) = message_options(&entry.args, &entry.admin_name) else {
                return Some(reply(id, "failed", "invalid message", ""));
            };
            match prompt::ask("message", &options, None, cancel) {
                Ok(given) => reply(id, "done", "", &given),
                Err(NoAnswer::Cancelled) | Err(NoAnswer::Timeout) => reply(id, "done", "", "closed"),
                Err(NoAnswer::Failed(error)) => reply(id, "failed", error, ""),
            }
        }
        "countdown" => {
            let Some(options) = countdown_options(&entry.args) else {
                return Some(reply(id, "failed", "invalid countdown", ""));
            };
            let seconds = entry.args["seconds"].as_u64().unwrap_or(0);
            let given = match prompt::ask("countdown", &options, Some(Duration::from_secs(seconds) + COUNTDOWN_SLACK), cancel) {
                Ok(given) => given,
                Err(NoAnswer::Cancelled) => return Some(reply(id, "done", "cancelled", "cancelled")),
                // No window (the program missing or failing): the countdown still runs out.
                Err(NoAnswer::Timeout) | Err(NoAnswer::Failed(_)) => {
                    let waited = Duration::from_secs(seconds);
                    if !sleep_unless(waited, cancel) {
                        return Some(reply(id, "done", "cancelled", "cancelled"));
                    }
                    "timeout".to_string()
                }
            };
            if entry.args["action"].as_str() == Some("logout") && given != "postpone" {
                // Answer first: the logout ends this process.
                let answer = reply(id, "done", "", &given);
                let outbox = context.runtime_dir.join(RUNTIME_SUBDIR).join(OUTBOX);
                let _ = write_answer(&outbox, &answer);
                thread::sleep(Duration::from_secs(3));
                logout(context);
                return Some(answer);
            }
            reply(id, "done", "", &given)
        }
        "lock" => match lock_screen(context) {
            Ok(()) => reply(id, "done", "", "locked"),
            Err(error) => reply(id, "failed", error, ""),
        },
        "remote_help" => remotehelp::run(id, &entry.args, &entry.admin_name, &context.runtime_dir, cancel),
        other => reply(id, "failed", format!("unknown action {other}"), ""),
    })
}

/// Sleeps `duration` unless `cancel` comes first; whether it slept to the end.
fn sleep_unless(duration: Duration, cancel: &AtomicBool) -> bool {
    let end = std::time::Instant::now() + duration;
    while std::time::Instant::now() < end {
        if cancel.load(Ordering::SeqCst) {
            return false;
        }
        thread::sleep(Duration::from_millis(500));
    }
    true
}

/// Locks the screen the desktop's own way (Cinnamon 6.6 does not follow logind's lock), else logind's.
fn lock_screen(context: &Context) -> Result<(), String> {
    let output = match (context.desktop, &context.session_id) {
        (Desktop::Cinnamon, _) => process::run("cinnamon-screensaver-command", &["--lock"], TOOL_TIMEOUT),
        (Desktop::Xfce, _) => process::run("xflock4", &[], TOOL_TIMEOUT),
        (Desktop::Other, Some(session)) => process::run("loginctl", &["lock-session", session], TOOL_TIMEOUT),
        (Desktop::Other, None) => return Err("no way to lock this desktop".to_string()),
    }
    .map_err(|error| error.to_string())?;
    if output.success() {
        Ok(())
    } else {
        Err(output.message())
    }
}

/// Logs the user out: the desktop's own way, else logind's.
fn logout(context: &Context) {
    let done = match context.desktop {
        Desktop::Cinnamon => process::run("cinnamon-session-quit", &["--logout", "--no-prompt"], TOOL_TIMEOUT),
        Desktop::Xfce => process::run("xfce4-session-logout", &["--logout", "--fast"], TOOL_TIMEOUT),
        Desktop::Other => process::run("false", &[], TOOL_TIMEOUT),
    }
    .is_ok_and(|output| output.success());
    if !done {
        if let Some(session) = &context.session_id {
            let _ = process::run("loginctl", &["terminate-session", session], TOOL_TIMEOUT);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn prompt_options() {
        assert_eq!(
            countdown_options(&json!({"action": "shutdown", "seconds": 600, "postpones_left": 2, "postpone_minutes": 30})).unwrap(),
            ["--action", "shutdown", "--seconds", "600", "--postpones-left", "2", "--postpone-minutes", "30"]
        );
        assert_eq!(countdown_options(&json!({"action": "restart", "seconds": 60})).unwrap(), ["--action", "restart", "--seconds", "60"]);
        assert_eq!(countdown_options(&json!({"action": "rm -rf", "seconds": 60})), None);
        assert_eq!(
            message_options(&json!({"title": "Họp 15h", "body": "Phòng họp tầng 3.", "ack": true}), "IT").unwrap(),
            ["--title", "Họp 15h", "--body", "Phòng họp tầng 3.", "--admin", "IT", "--ack"]
        );
    }

    #[test]
    fn ticket_notifications() {
        let args = json!({"ticket": "HT-0007", "status": "working", "text": "Bên mình đang xem, chiều nay xong."});
        assert_eq!(ticket_notification(&args, true).unwrap(), ("Phiếu HT-0007: Đang xử lý".to_string(), "Bên mình đang xem, chiều nay xong.".to_string()));
        assert_eq!(ticket_notification(&args, false).unwrap().0, "Ticket HT-0007: In progress");
        assert_eq!(ticket_notification(&json!({"ticket": "rm -rf", "status": "done"}), true), None);
        assert_eq!(status_label("waiting", true), "Chờ bạn trả lời");
    }

    #[test]
    fn the_reader_acts_on_its_own_and_stops_what_it_started() {
        let root = crate::testutil::TempDir::new("inbox-reader");
        let uid = crate::process::uid().unwrap();
        let runtime = root.path().join("run");
        let inbox = Arc::new(Mutex::new(Inbox::new(&root.path().join("inbox"), uid, &runtime)));
        let context = Context { desktop: Desktop::Other, runtime_dir: runtime.clone(), session_id: None, vietnamese: true };
        let managed = Arc::new(AtomicBool::new(true));
        let stop = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&managed);
        let reader = spawn_reader(Arc::clone(&inbox), context, move || flag.load(Ordering::SeqCst), || true, Arc::clone(&stop));
        // A shutdown countdown: without its window (no caramos-business here) it still runs out, cancellably.
        let id = "00000000-0000-4000-8000-000000000062";
        let entry = InboxEntry { id: id.into(), action: "countdown".into(), args: json!({"action": "shutdown", "seconds": 60}), admin_name: "IT".into(), expires: 0 };
        relay::deliver(&root.path().join("inbox"), uid, None, &entry).unwrap();
        let busy = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            lock(&inbox).busy()
        });
        assert!(busy, "taken within the reader's second, by itself");
        // The machine leaves the company: what the reader started stops.
        managed.store(false, Ordering::SeqCst);
        let answer = runtime.join("caramos-business/outbox").join(format!("{id}.json"));
        let answered = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            answer.exists()
        });
        assert!(answered);
        let written: Answer = serde_json::from_slice(&fs::read(&answer).unwrap()).unwrap();
        assert_eq!((written.state.as_str(), written.answer.as_str()), ("done", "cancelled"));
        stop.store(true, Ordering::SeqCst);
        reader.join().unwrap();
    }

    #[test]
    fn the_reader_ends_when_the_login_is_no_longer_its() {
        // A newer session part took the login over (or the login ended) while this part's round still waits: this
        // reader stops what it started and takes nothing more, so that two parts never act on the same request.
        let root = crate::testutil::TempDir::new("inbox-takeover");
        let uid = crate::process::uid().unwrap();
        let runtime = root.path().join("run");
        let inbox = Arc::new(Mutex::new(Inbox::new(&root.path().join("inbox"), uid, &runtime)));
        let context = Context { desktop: Desktop::Other, runtime_dir: runtime.clone(), session_id: None, vietnamese: true };
        let ours = Arc::new(AtomicBool::new(true));
        let flag = Arc::clone(&ours);
        let reader = spawn_reader(Arc::clone(&inbox), context, || true, move || flag.load(Ordering::SeqCst), Arc::new(AtomicBool::new(false)));
        let first = "00000000-0000-4000-8000-000000000063";
        let entry = InboxEntry { id: first.into(), action: "countdown".into(), args: json!({"action": "shutdown", "seconds": 60}), admin_name: "IT".into(), expires: 0 };
        relay::deliver(&root.path().join("inbox"), uid, None, &entry).unwrap();
        let busy = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            lock(&inbox).busy()
        });
        assert!(busy);
        ours.store(false, Ordering::SeqCst);
        let ended = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            reader.is_finished()
        });
        assert!(ended, "the reader ends within its second");
        let outbox = runtime.join("caramos-business/outbox");
        let answer = outbox.join(format!("{first}.json"));
        let answered = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            answer.exists()
        });
        assert!(answered, "what it started stops");
        let written: Answer = serde_json::from_slice(&fs::read(&answer).unwrap()).unwrap();
        assert_eq!((written.state.as_str(), written.answer.as_str()), ("done", "cancelled"));
        // A request after the takeover is the newer part's.
        let second = "00000000-0000-4000-8000-000000000064";
        let entry = InboxEntry { id: second.into(), action: "lock".into(), args: json!({}), admin_name: "IT".into(), expires: 0 };
        relay::deliver(&root.path().join("inbox"), uid, None, &entry).unwrap();
        thread::sleep(READ_EVERY + Duration::from_millis(500));
        assert!(!outbox.join(format!("{second}.json")).exists());
        assert!(!lock(&inbox).taken.contains(second));
        reader.join().unwrap();
    }

    #[test]
    fn answers_go_to_the_outbox() {
        let root = crate::testutil::TempDir::new("outbox");
        let outbox = root.path().join("outbox");
        write_answer(&outbox, &reply("00000000-0000-4000-8000-000000000041", "done", "", "read")).unwrap();
        let written: Answer = serde_json::from_slice(&fs::read(outbox.join("00000000-0000-4000-8000-000000000041.json")).unwrap()).unwrap();
        assert_eq!(written.answer, "read");
    }
}
