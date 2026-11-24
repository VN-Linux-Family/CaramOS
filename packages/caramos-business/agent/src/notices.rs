//! The company's notice in a login (PROTOCOL.md part 2 "Transparency"; part 3, changes of 0.3.1 after the full test
//! pass): what the company manages on this machine and what it never collects. It runs in its own thread, apart from
//! the session part's rounds, which can wait minutes on a share's sign-in window: the notice must come before the
//! measures, also those the daemon applies (Law 91/2025/QH15, article 25).
//!
//! Twice a second it looks at this machine's effective settings. It opens the notice when the user was not told
//! about every section in effect (after pairing, or when the company turned on more), replaces an open one that no
//! longer lists everything, keeps what the user answered, and writes notice.json for the daemon: what the user was
//! told, an open notice counting once its window is on the screen (it wrote notice-shown when it mapped).

use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime};

use serde::{Deserialize, Serialize};

use crate::logins::{Told, NOTICE_FILE, SHOWN_FILE};
use crate::prompt;
use crate::protocol::RUNTIME_SUBDIR;
use crate::session::{managed_sections, SavedState, SessionPaths};
use crate::store::{self, Store};

/// Between two looks.
pub const STEP: Duration = Duration::from_millis(500);

/// What the user answered: the machine id and the sections the notice listed when they pressed "Đã hiểu",
/// `~/.config/caramos-business/notice-answered.json` (0.3.1 before the full test pass kept them in state.json, which
/// is read when this file is missing).
#[derive(Debug, Default, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Answered {
    #[serde(default)]
    pub notice_for: Option<String>,
    #[serde(default)]
    pub notice_sections: Vec<String>,
}

impl Answered {
    pub fn load(path: &Path, older: &Path) -> Answered {
        match store::read_limited(path, 64 * 1024) {
            Ok(data) => serde_json::from_slice(&data).unwrap_or_default(),
            Err(_) => {
                let saved = SavedState::load(older);
                Answered { notice_for: saved.notice_for, notice_sections: saved.notice_sections }
            }
        }
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

/// The notice on the screen: the machine id and the sections it lists, when it was started, its answer, and the flag
/// that closes it.
pub struct NoticeShown {
    machine_id: String,
    sections: Vec<String>,
    started: SystemTime,
    answer: Receiver<bool>,
    close: Arc<AtomicBool>,
}

/// The notice of one login, in its own thread.
pub struct Notices {
    runtime_dir: PathBuf,
    answered_file: PathBuf,
    store: Store,
    paths: SessionPaths,
    answered: Answered,
    shown: Option<NoticeShown>,
    /// What notice.json says now, as last written.
    told_written: Option<Told>,
    /// effective.json's mtime at the last look, and what it gave: (machine id, sections), or None.
    seen: Option<(Option<SystemTime>, Option<(String, Vec<String>)>)>,
    /// Whether a notice is on the screen, for the session part (it does not start again with an upgraded program then).
    open: Arc<AtomicBool>,
    /// Opens the window: `caramos-business --prompt notice`; tests give another.
    ask: fn(Arc<AtomicBool>) -> bool,
}

impl Notices {
    pub fn new(home: &Path, runtime_dir: &Path, store: Store, paths: SessionPaths, open: Arc<AtomicBool>) -> Notices {
        let config = home.join(".config/caramos-business");
        let answered_file = config.join("notice-answered.json");
        Notices {
            answered: Answered::load(&answered_file, &config.join("state.json")),
            runtime_dir: runtime_dir.to_path_buf(),
            answered_file,
            store,
            paths,
            shown: None,
            told_written: None,
            seen: None,
            open,
            ask: ask_with_window,
        }
    }

    /// Runs in its own thread until `stop`, or until `ours()` says the login is no longer this session part's (a newer
    /// part, which shows the notice, took it over; or the login ended), also while the part's round still waits; then
    /// closes an open notice, unanswered (it comes back at the next login), and leaves notice.json to the newer part.
    /// Each look holds `step_lock`: whoever holds it keeps the notice from opening a window (the session part, before it
    /// starts again with an upgraded program).
    pub fn spawn(mut self, step_lock: Arc<Mutex<()>>, stop: Arc<AtomicBool>, ours: impl Fn() -> bool + Send + 'static) -> thread::JoinHandle<()> {
        thread::Builder::new()
            .name("notice".into())
            .spawn(move || {
                while !stop.load(Ordering::SeqCst) {
                    {
                        let _step = crate::inbox::lock(&step_lock);
                        if !ours() {
                            break;
                        }
                        self.step();
                    }
                    thread::sleep(STEP);
                }
                let _step = crate::inbox::lock(&step_lock);
                self.close();
            })
            .expect("a thread")
    }

    /// One look: the notice opened, replaced, answered or closed as the effective settings say, and notice.json.
    pub fn step(&mut self) {
        match self.managed() {
            None => {
                // Not the company's (left, removed, leaving, a clone): no notice; it comes back if paired again.
                self.close();
                self.write_told(None);
            }
            Some((machine_id, sections)) => {
                if needs_notice(&self.answered, &machine_id, &sections) {
                    self.notice_step(&machine_id, &sections);
                }
                let shown_at = fs::metadata(self.runtime_dir.join(RUNTIME_SUBDIR).join(SHOWN_FILE)).and_then(|metadata| metadata.modified()).ok();
                let told = told(&self.answered, self.shown.as_ref(), &machine_id, shown_at);
                self.write_told(told);
            }
        }
        self.open.store(self.shown.is_some(), Ordering::SeqCst);
    }

    /// The machine id and the sections in effect while this is a paired employee machine with a policy, not leaving
    /// and not a clone (as the session part's `effective`); effective.json is read again only when it changed.
    fn managed(&mut self) -> Option<(String, Vec<String>)> {
        if !crate::session::managed_here(&self.paths, &self.store) {
            return None;
        }
        let mtime = fs::metadata(self.store.effective_path()).and_then(|metadata| metadata.modified()).ok();
        if self.seen.as_ref().is_none_or(|(at, _)| *at != mtime) {
            let found = self.store.load_effective().map(|file| (file.machine_id.clone(), managed_sections(&file.settings)));
            self.seen = Some((mtime, found));
        }
        self.seen.as_ref().and_then(|(_, found)| found.clone())
    }

    fn notice_step(&mut self, machine_id: &str, sections: &[String]) {
        if let Some(shown) = self.shown.take() {
            match shown.answer.try_recv() {
                Ok(true) => {
                    self.answered = Answered { notice_for: Some(shown.machine_id.clone()), notice_sections: shown.sections.clone() };
                    if let Err(error) = self.answered.save(&self.answered_file) {
                        log!("cannot write {}: {error}", self.answered_file.display());
                    }
                    return;
                }
                // Closed without an answer: it opens again at the next look.
                Ok(false) | Err(mpsc::TryRecvError::Disconnected) => return,
                Err(mpsc::TryRecvError::Empty) => {
                    if lists_everything(&shown, machine_id, sections) {
                        self.shown = Some(shown);
                        return;
                    }
                    // The company turned on more while it was open: a new window lists everything now (it reads
                    // effective.json when it starts); 0.3.1 kept the old one until it was answered.
                    shown.close.store(true, Ordering::SeqCst);
                }
            }
        }
        let (sender, answer) = mpsc::channel();
        let close = Arc::new(AtomicBool::new(false));
        let flag = Arc::clone(&close);
        let ask = self.ask;
        thread::spawn(move || {
            let _ = sender.send(ask(flag));
        });
        self.shown = Some(NoticeShown { machine_id: machine_id.to_string(), sections: sections.to_vec(), started: SystemTime::now(), answer, close });
    }

    /// Writes notice.json when what the user was told changed (None: removes it).
    fn write_told(&mut self, told: Option<Told>) {
        if self.told_written == told {
            return;
        }
        let path = self.runtime_dir.join(RUNTIME_SUBDIR).join(NOTICE_FILE);
        match write_notice_file(&path, told.as_ref()) {
            Ok(()) => self.told_written = told,
            Err(error) => log!("cannot write {}: {error}", path.display()),
        }
    }

    /// Closes the notice on the screen, unanswered.
    fn close(&mut self) {
        if let Some(shown) = self.shown.take() {
            shown.close.store(true, Ordering::SeqCst);
        }
        self.open.store(false, Ordering::SeqCst);
    }
}

/// `caramos-business --prompt notice`: whether the user answered it.
fn ask_with_window(close: Arc<AtomicBool>) -> bool {
    prompt::ask("notice", &[], None, &close).is_ok()
}

/// notice.json (0644, in the 0700 runtime folder) with what the user was told; None removes it.
pub fn write_notice_file(path: &Path, told: Option<&Told>) -> io::Result<()> {
    match told {
        Some(told) => {
            if let Some(dir) = path.parent() {
                fs::create_dir_all(dir)?;
            }
            store::write_atomic(path, &serde_json::to_vec(told).map_err(io::Error::other)?, 0o644)
        }
        None => match fs::remove_file(path) {
            Err(error) if error.kind() != io::ErrorKind::NotFound => Err(error),
            _ => Ok(()),
        },
    }
}

/// Whether the notice on the screen lists every section now in effect, for this pairing.
pub fn lists_everything(shown: &NoticeShown, machine_id: &str, sections: &[String]) -> bool {
    shown.machine_id == machine_id && sections.iter().all(|section| shown.sections.contains(section))
}

/// A file's time comes from the kernel's coarse clock, a few milliseconds behind `SystemTime::now()`.
const FILE_CLOCK_SLACK: Duration = Duration::from_millis(50);

/// What the user was told for this pairing: the notice on the screen now, once its window wrote notice-shown
/// (`shown_at`) after it started, else the one they answered. None when they saw none for this machine id.
pub fn told(answered: &Answered, shown: Option<&NoticeShown>, machine_id: &str, shown_at: Option<SystemTime>) -> Option<Told> {
    if let Some(shown) = shown.filter(|shown| shown_at.is_some_and(|at| at + FILE_CLOCK_SLACK >= shown.started)) {
        return Some(Told { machine_id: shown.machine_id.clone(), sections: shown.sections.clone() });
    }
    (answered.notice_for.as_deref() == Some(machine_id))
        .then(|| Told { machine_id: machine_id.to_string(), sections: answered.notice_sections.clone() })
}

/// Whether the user is to see the notice: not yet for this pairing, or a section is on that it did not list.
pub fn needs_notice(answered: &Answered, machine_id: &str, sections: &[String]) -> bool {
    answered.notice_for.as_deref() != Some(machine_id) || sections.iter().any(|section| !answered.notice_sections.contains(section))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::EffectiveFile;
    use crate::testutil::TempDir;
    use serde_json::{json, Map, Value};

    const ID: &str = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";

    fn strings(names: &[&str]) -> Vec<String> {
        names.iter().map(|name| name.to_string()).collect()
    }

    #[test]
    fn the_notice_comes_back_for_a_new_section() {
        let settings: Map<String, Value> =
            serde_json::from_value(json!({"usb": {"storage": "block"}, "browser": null, "inventory": {"enabled": true}})).unwrap();
        let sections = managed_sections(&settings);
        assert_eq!(sections, ["inventory", "usb"]);
        let mut answered = Answered::default();
        assert!(needs_notice(&answered, ID, &sections), "after pairing");
        answered.notice_for = Some(ID.into());
        answered.notice_sections = strings(&["inventory", "usb"]);
        assert!(!needs_notice(&answered, ID, &sections), "seen");
        assert!(!needs_notice(&answered, ID, &sections[..1]), "a section turned off");
        assert!(needs_notice(&answered, ID, &strings(&["browser", "usb"])), "a section turned on");
        assert!(needs_notice(&answered, "11111111-2222-4333-8444-555555555555", &sections), "paired again");
    }

    #[test]
    fn what_the_user_was_told() {
        let mut answered = Answered::default();
        assert_eq!(told(&answered, None, ID, None), None, "no notice yet");
        let (_sender, answer) = mpsc::channel();
        let started = SystemTime::now();
        let shown = NoticeShown { machine_id: ID.into(), sections: strings(&["firewall", "usb"]), started, answer, close: Arc::new(AtomicBool::new(false)) };
        assert_eq!(told(&answered, Some(&shown), ID, None), None, "started, not on the screen yet");
        assert_eq!(told(&answered, Some(&shown), ID, Some(started - Duration::from_secs(60))), None, "an earlier notice's window");
        let on_screen = told(&answered, Some(&shown), ID, Some(started + Duration::from_millis(900))).unwrap();
        assert!(on_screen.covers(ID, &strings(&["firewall", "usb"])), "on the screen counts: the measures may follow");
        answered.notice_for = Some(ID.into());
        answered.notice_sections = strings(&["usb"]);
        assert_eq!(told(&answered, None, ID, None), Some(Told { machine_id: ID.into(), sections: strings(&["usb"]) }), "answered");
        assert_eq!(told(&answered, Some(&shown), ID, None), Some(Told { machine_id: ID.into(), sections: strings(&["usb"]) }), "a new one opening");
        assert_eq!(told(&answered, None, "11111111-2222-4333-8444-555555555555", None), None, "an earlier pairing");
        assert!(lists_everything(&shown, ID, &strings(&["usb"])));
        assert!(!lists_everything(&shown, ID, &strings(&["snapshots", "usb"])), "turned on while it was open");
        assert!(!lists_everything(&shown, "11111111-2222-4333-8444-555555555555", &strings(&["usb"])));
    }

    #[test]
    fn the_notice_file() {
        let root = TempDir::new("notice-file");
        let path = root.path().join("caramos-business/notice.json");
        let told = Told { machine_id: ID.into(), sections: strings(&["usb"]) };
        write_notice_file(&path, Some(&told)).unwrap();
        assert_eq!(serde_json::from_slice::<Told>(&fs::read(&path).unwrap()).unwrap(), told);
        write_notice_file(&path, None).unwrap();
        assert!(!path.exists());
        write_notice_file(&path, None).unwrap(); // no file: nothing to remove
    }

    #[test]
    fn answers_of_0_3_1_are_kept() {
        let root = TempDir::new("notice-answered");
        let config = root.path().join(".config/caramos-business");
        fs::create_dir_all(&config).unwrap();
        fs::write(config.join("state.json"), format!(r#"{{"wallpaper": null, "notice_for": "{ID}", "notice_sections": ["usb"]}}"#)).unwrap();
        let older = Answered::load(&config.join("notice-answered.json"), &config.join("state.json"));
        assert_eq!(older, Answered { notice_for: Some(ID.into()), notice_sections: strings(&["usb"]) });
        let newer = Answered { notice_for: Some(ID.into()), notice_sections: strings(&["firewall", "usb"]) };
        newer.save(&config.join("notice-answered.json")).unwrap();
        assert_eq!(Answered::load(&config.join("notice-answered.json"), &config.join("state.json")), newer);
    }

    /// A paired employee machine in a test folder, with its effective settings.
    fn managed_machine(root: &Path, settings: Value) -> (Store, SessionPaths) {
        let store = Store::new(root.join("state"));
        let paths = SessionPaths { role: root.join("role"), agent_config: root.join("agent.json"), inbox: root.join("inbox") };
        fs::write(&paths.role, "employee\n").unwrap();
        fs::write(&paths.agent_config, "{}").unwrap();
        store.save("{}").unwrap();
        let effective = EffectiveFile {
            serial: 2,
            machine_id: ID.into(),
            department: None,
            admin_name: "quan-ly".into(),
            files: Map::new(),
            settings: serde_json::from_value(settings).unwrap(),
        };
        store.save_effective(&effective).unwrap();
        (store, paths)
    }

    fn answer_now(_close: Arc<AtomicBool>) -> bool {
        true
    }

    fn never_answer(close: Arc<AtomicBool>) -> bool {
        while !close.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(10));
        }
        false
    }

    #[test]
    fn the_notice_follows_the_settings() {
        let root = TempDir::new("notices");
        let (store, paths) = managed_machine(root.path(), json!({"usb": {"storage": "block"}, "browser": null}));
        let open = Arc::new(AtomicBool::new(false));
        let runtime = root.path().join("run");
        let mut notices = Notices::new(&root.path().join("home"), &runtime, store.clone(), paths.clone(), Arc::clone(&open));
        notices.ask = never_answer;
        let notice_json = runtime.join("caramos-business/notice.json");

        // Paired: the notice opens; it does not count before its window is on the screen.
        notices.step();
        assert!(open.load(Ordering::SeqCst));
        assert!(!notice_json.exists());
        fs::create_dir_all(runtime.join("caramos-business")).unwrap();
        fs::write(runtime.join("caramos-business/notice-shown"), "1\n").unwrap();
        notices.step();
        let told: Told = serde_json::from_slice(&fs::read(&notice_json).unwrap()).unwrap();
        assert_eq!(told, Told { machine_id: ID.into(), sections: strings(&["usb"]) });

        // The company turns on the firewall while it is open: a new one lists it, and counts once it is shown.
        let first = notices.shown.as_ref().map(|shown| Arc::clone(&shown.close)).unwrap();
        let mut more = store.load_effective().unwrap();
        more.settings.insert("firewall".into(), json!({"enabled": true}));
        thread::sleep(Duration::from_millis(20)); // another mtime
        store.save_effective(&more).unwrap();
        notices.seen = None;
        notices.step();
        assert!(first.load(Ordering::SeqCst), "the old window is closed");
        assert_eq!(notices.shown.as_ref().unwrap().sections, strings(&["firewall", "usb"]));
        thread::sleep(Duration::from_millis(20));
        fs::write(runtime.join("caramos-business/notice-shown"), "2\n").unwrap();
        notices.step();
        let told: Told = serde_json::from_slice(&fs::read(&notice_json).unwrap()).unwrap();
        assert_eq!(told.sections, strings(&["firewall", "usb"]));

        // Answered: kept in notice-answered.json, no window, still told.
        notices.ask = answer_now;
        notices.close();
        notices.step(); // opens one that answers at once
        thread::sleep(Duration::from_millis(50));
        notices.step();
        assert!(!open.load(Ordering::SeqCst));
        let answered: Answered = serde_json::from_slice(&fs::read(root.path().join("home/.config/caramos-business/notice-answered.json")).unwrap()).unwrap();
        assert_eq!(answered.notice_sections, strings(&["firewall", "usb"]));
        assert!(notice_json.exists());

        // A clone, or a machine that left: no notice and no notice.json.
        fs::write(store.clone_path(), "{}\n").unwrap();
        notices.step();
        assert!(!notice_json.exists());
        fs::remove_file(store.clone_path()).unwrap();
        notices.step();
        assert!(notice_json.exists());
        fs::write(&paths.role, "admin\n").unwrap();
        notices.step();
        assert!(!notice_json.exists());
    }

    #[test]
    fn a_newer_part_takes_the_notice_over() {
        // The login is no longer this part's while its round still waits: its notice closes, and notice.json, which
        // the newer part writes, stays.
        let root = TempDir::new("notice-takeover");
        let (store, paths) = managed_machine(root.path(), json!({"usb": {"storage": "block"}}));
        let open = Arc::new(AtomicBool::new(false));
        let runtime = root.path().join("run");
        let mut notices = Notices::new(&root.path().join("home"), &runtime, store, paths, Arc::clone(&open));
        notices.ask = never_answer;
        fs::create_dir_all(runtime.join("caramos-business")).unwrap();
        fs::write(runtime.join("caramos-business/notice-shown"), "1\n").unwrap();
        let ours = Arc::new(AtomicBool::new(true));
        let flag = Arc::clone(&ours);
        let thread = notices.spawn(Arc::new(Mutex::new(())), Arc::new(AtomicBool::new(false)), move || flag.load(Ordering::SeqCst));
        let notice_json = runtime.join("caramos-business/notice.json");
        let told = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            notice_json.exists()
        });
        assert!(told && open.load(Ordering::SeqCst));
        ours.store(false, Ordering::SeqCst);
        let ended = (0..40).any(|_| {
            thread::sleep(Duration::from_millis(100));
            thread.is_finished()
        });
        assert!(ended);
        assert!(!open.load(Ordering::SeqCst), "the window is closed");
        assert!(notice_json.exists(), "the newer part's notice.json is not removed");
    }
}
