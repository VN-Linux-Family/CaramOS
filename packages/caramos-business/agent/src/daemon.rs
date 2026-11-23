//! The service, `caramos-business-agent daemon` (root, systemd): keeps the stored policy in step with the admin's,
//! applies the system sections, runs the signed commands, and reports back.
//!
//! Threads:
//! - the main loop: a round at start and every 5 minutes (after a failed round, every minute for 5 minutes): fetch
//!   and check the policy (finding the admin again by discovery if its address stopped giving a policy signed with
//!   the pinned key), write this machine's effective settings for the session parts, apply the system sections,
//!   check in, and send the inventory when it is on and due;
//! - `/wait`: one long-poll open all the time. Another serial makes it run a round at once, another tickets version
//!   fetches the tickets; the commands it brings are checked and handed to the worker;
//! - the worker runs the commands one after another;
//! - the relay reads the session parts' answers and the help requests every 2 s, and sends the results;
//! - the scheduler checks the block hours, the power schedule, a `usb_unlock` and a frozen machine's maintenance
//!   window every 30 s.
//!
//! From 0.3 (PROTOCOL.md part 3): a machine waiting for the admin's approval asks for the policy every minute and does
//! nothing else; a signed removal notice puts everything back, forgets the pairing and disables the service; a frozen
//! machine masks the update timers for each boot and restarts into its maintenance entry at the maintenance time; the
//! maintenance boot updates the disk and restarts frozen; a frozen machine's leave finishes in its next unfrozen boot.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use serde_json::{json, Value};

use crate::accounts;
use crate::clock::{self, LocalTime};
use crate::commands::{self, Action, Command, CommandRecord, Decision, Ending};
use crate::crypto::{self, SharedKeys};
use crate::discovery;
use crate::fetch::{Admin, Auth, FetchError};
use crate::health;
use crate::inventory;
use crate::logging::{self, Once};
use crate::machine;
use crate::policy::{self, Policy};
use crate::protocol::{
    CheckIn, CommandResult, Envelope, HelpRequest, Machine, PolicyAnswer, ResultState, SignedNotice, UserStatus,
    AGENT_BOX_KEY, AGENT_CONFIG, AGENT_STATE, AGENT_UNIT, CAPABILITIES, INBOX_ROOT, MAX_HELP_NOTE, MAX_REQUEST_BODY,
    MAX_RESULT_DETAIL, RUN_USER,
};
use crate::relay::{self, InboxEntry, Outgoing, Pending, Purpose};
use crate::sections::shared::{self, MaintenanceRecord};
use crate::sections::{self, apps, browser, firewall, power, printers, snapshots, usb, wifi, Managed, System};
use crate::settings::{Effective, UsbStorage};
use crate::status::{self, UserReport};
use crate::store::{self, AgentConfig, EffectiveFile, Store};
use crate::tickets;

/// Between good rounds.
pub const INTERVAL: Duration = Duration::from_secs(5 * 60);
/// After a failed round, and while the machine is not paired or waits for approval.
pub const RETRY: Duration = Duration::from_secs(60);
/// Failed rounds that are retried after RETRY before INTERVAL applies again: 5 minutes of retries.
pub const RETRIES: u32 = 5;
const RELAY_EVERY: Duration = Duration::from_secs(2);
const SCHEDULE_EVERY: Duration = Duration::from_secs(30);
const INVENTORY_EVERY: Duration = Duration::from_secs(6 * 3600);
const RESULT_RETRY: Duration = Duration::from_secs(30);
/// `du -sm /timeshift` at most this often: half a million files take seconds.
const SNAPSHOT_SPACE_EVERY: Duration = Duration::from_secs(6 * 3600);
/// How long a cancel entry stays in an inbox for the session part to see it.
const CANCEL_STAYS: i64 = 20;
/// A ticket's notification waits this long in the inbox of a user who is not logged in.
const TICKET_NOTICE_STAYS: i64 = 24 * 3600;
const TOOL_TIMEOUT: Duration = Duration::from_secs(60);
const UPDATE_TIMEOUT: Duration = Duration::from_secs(3600);
/// The maintenance boot waits this long for the admin before it goes on with the stored policy.
const MAINTENANCE_WAITS_FOR_ADMIN: Duration = Duration::from_secs(5 * 60);

/// The `update` command's answer on a frozen machine.
pub const FROZEN_UPDATE: &str = "máy đang đóng băng: cập nhật chạy trong giờ bảo trì";
/// The maintenance window's result when someone used the machine all through it.
pub const MAINTENANCE_SKIPPED: &str = "bỏ qua: có người đang dùng";

/// Where the service reads and writes; the tests use temporary folders.
#[derive(Debug, Clone)]
pub struct Paths {
    pub config: PathBuf,
    pub box_key: PathBuf,
    pub state: PathBuf,
    pub run_user: PathBuf,
    pub inbox: PathBuf,
    /// logind's session files, for the user at the screen.
    pub sessions: PathBuf,
    /// The operating system's machine id, to notice a cloned disk.
    pub os_machine_id: PathBuf,
}

impl Paths {
    pub fn system() -> Paths {
        Paths {
            config: AGENT_CONFIG.into(),
            box_key: AGENT_BOX_KEY.into(),
            state: AGENT_STATE.into(),
            run_user: RUN_USER.into(),
            inbox: INBOX_ROOT.into(),
            sessions: "/run/systemd/sessions".into(),
            os_machine_id: store::OS_MACHINE_ID.into(),
        }
    }
}

/// The wait after a round: INTERVAL after a good one, RETRY after the first RETRIES failed ones in a row.
pub fn wait_after(failures_in_a_row: u32) -> Duration {
    if failures_in_a_row == 0 || failures_in_a_row > RETRIES {
        INTERVAL
    } else {
        RETRY
    }
}

/// Why a round could not bring the stored policy up to date.
#[derive(Debug)]
pub enum Failure {
    /// The admin's address gave no signed policy.
    Fetch(FetchError),
    /// It gave a policy that is not signed with the pinned key.
    BadSignature(String),
    /// The signed policy is refused: invalid, of an unknown format, or older than the stored one.
    Refused(String),
    /// A removal notice that fails a check: logged and ignored.
    BadNotice(String),
    /// A listed file could not be downloaded or did not match.
    File(String, FetchError),
    /// Storing on this machine failed.
    Local(String),
}

impl Failure {
    /// Whether the admin may be elsewhere: its address gave no policy signed with the pinned key.
    pub fn admin_may_have_moved(&self) -> bool {
        matches!(self, Failure::Fetch(error) if *error != FetchError::Gone) || matches!(self, Failure::BadSignature(_))
    }

    /// Whether the address proved to be the admin's (it served a policy signed with the pinned key), so that the
    /// machine's authenticated requests may go there.
    pub fn admin_proven(&self) -> bool {
        !self.admin_may_have_moved() && !matches!(self, Failure::BadNotice(_) | Failure::Fetch(_))
    }
}

impl std::fmt::Display for Failure {
    fn fmt(&self, formatter: &mut std::fmt::Formatter) -> std::fmt::Result {
        match self {
            Failure::Fetch(error) => write!(formatter, "cannot get the policy: {error}"),
            Failure::BadSignature(error) => write!(formatter, "policy refused: {error}"),
            Failure::Refused(error) => write!(formatter, "policy refused: {error}"),
            Failure::BadNotice(error) => write!(formatter, "removal notice ignored: {error}"),
            Failure::File(sha, error) => write!(formatter, "file {sha}: {error}"),
            Failure::Local(error) => write!(formatter, "cannot store the policy: {error}"),
        }
    }
}

/// What a good round did.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Updated {
    pub serial: u64,
    /// A new policy was stored.
    pub changed: bool,
    /// Files downloaded.
    pub downloaded: usize,
}

/// The company removed this machine: a removal notice signed with the pinned key, for this machine.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Removal {
    /// The admin's host name, as the notice names it.
    pub admin_name: String,
    /// When the company removed the machine (the notice's time).
    pub time: String,
}

/// What `GET /policy` brought.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Fetched {
    Policy(Updated),
    /// 403 pending: the admin has not approved the machine yet.
    Pending,
    Removed(Removal),
}

/// Checks a removal notice: the signature with the pinned key, then `kind` and the machine id.
pub fn check_notice(notice: &SignedNotice, admin_key: &[u8; 32], machine_id: &str) -> Result<Removal, String> {
    crypto::verify(admin_key, notice.notice.as_bytes(), &notice.signature)?;
    let value: Value = serde_json::from_str(&notice.notice).map_err(|error| format!("the notice is not JSON: {error}"))?;
    if value["kind"].as_str() != Some("removed") {
        return Err("the signed text is not a removal notice".to_string());
    }
    if value["machine_id"].as_str() != Some(machine_id) {
        return Err("the removal notice is another machine's".to_string());
    }
    let time = value["time"].as_str().filter(|time| clock::parse_iso8601(time).is_some()).map_or_else(|| LocalTime::now().iso8601(), str::to_string);
    Ok(Removal { admin_name: value["admin"].as_str().unwrap_or_default().chars().take(253).collect(), time })
}

/// Brings the stored policy up to date from `admin`, whose requests are signed with the machine's keys.
pub fn update(admin: &Admin, config: &AgentConfig, store: &Store) -> Result<Fetched, Failure> {
    let signed = match admin.signed_policy() {
        Ok(PolicyAnswer::Policy(signed)) => signed,
        Ok(PolicyAnswer::Notice(notice)) => {
            return check_notice(&notice, &config.admin_key, &config.machine_id).map(Fetched::Removed).map_err(Failure::BadNotice);
        }
        Err(FetchError::Pending) => return Ok(Fetched::Pending),
        Err(error) => return Err(Failure::Fetch(error)),
    };
    crypto::verify(&config.admin_key, signed.policy.as_bytes(), &signed.signature).map_err(Failure::BadSignature)?;
    let policy = policy::parse(&signed.policy).map_err(|error| Failure::Refused(error.to_string()))?;
    let stored = store.load();
    if let Some((_, stored)) = &stored {
        if policy.serial < stored.serial {
            return Err(Failure::Refused(format!(
                "its serial {} is lower than that of the stored policy, {}",
                policy.serial, stored.serial
            )));
        }
    }
    store.create_dirs().map_err(|error| Failure::Local(error.to_string()))?;
    let mut downloaded = 0;
    for (sha, file) in &policy.files {
        if !store.has_file(sha, file) {
            admin.download(sha, file.size, &store.file_path(sha, file)).map_err(|error| Failure::File(sha.clone(), error))?;
            downloaded += 1;
        }
    }
    let changed = stored.as_ref().map(|(text, _)| text.as_str()) != Some(signed.policy.as_str());
    if changed {
        store.save(&signed.policy).map_err(|error| Failure::Local(error.to_string()))?;
        log!("stored policy {} from {}", policy.serial, admin.base());
    }
    Ok(Fetched::Policy(Updated { serial: policy.serial, changed, downloaded }))
}

/// The admin at a new address: one that answers the discovery broadcast with the pinned fingerprint and serves a
/// policy (or this machine's removal notice) signed with the pinned key.
fn find_moved_admin(config: &AgentConfig, auth: &Auth) -> Option<(std::net::Ipv4Addr, u16)> {
    discovery::find_admin(&config.fingerprint).into_iter().find(|(ip, port)| {
        let url = store::admin_url(*ip, *port);
        url != config.admin_url && serves_signed_policy(&url, &config.admin_key, auth)
    })
}

/// Whether `url` serves a policy, or a removal notice, signed with `key` (the request signed with `auth`).
pub fn serves_signed_policy(url: &str, key: &[u8; 32], auth: &Auth) -> bool {
    match Admin::with_auth(url, auth.clone()).signed_policy() {
        Ok(PolicyAnswer::Policy(signed)) => crypto::verify(key, signed.policy.as_bytes(), &signed.signature).is_ok(),
        Ok(PolicyAnswer::Notice(notice)) => crypto::verify(key, notice.notice.as_bytes(), &notice.signature).is_ok(),
        Err(_) => false,
    }
}

/// The check-in's JSON, at most 64 KiB: users are left out from the end until it fits.
pub fn check_in_body(config: &AgentConfig, machine: &Machine, serial: Option<u64>, mut users: Vec<UserStatus>, health: &Value) -> Vec<u8> {
    loop {
        let body = CheckIn {
            machine_id: &config.machine_id,
            machine,
            policy_serial: serial,
            users: &users,
            health,
            capabilities: &CAPABILITIES,
        };
        let json = serde_json::to_vec(&body).unwrap_or_default();
        if json.len() <= MAX_REQUEST_BODY || users.is_empty() {
            return json;
        }
        users.pop();
    }
}

/// The keys that sign the machine's requests: its own box key, and the admin's from the stored policy, or before the
/// first policy from agent.json (the pairing wrote it).
pub fn shared_keys(config: &AgentConfig, box_key: Option<[u8; 32]>, policy: Option<&Policy>) -> Option<SharedKeys> {
    let admin_box = policy.map(|policy| policy.admin_box_key).or(config.admin_box_key)?;
    SharedKeys::derive(&box_key?, &admin_box).ok()
}

/// The pairing, the stored policy and what follows from them.
#[derive(Debug, Clone)]
pub struct Current {
    pub config: AgentConfig,
    pub policy: Option<Policy>,
    pub effective: Effective,
    pub keys: Option<SharedKeys>,
}

impl Current {
    /// From agent.json (already read), the machine box key and the stored policy.
    pub fn load(config: AgentConfig, box_key: Option<[u8; 32]>, store: &Store) -> Current {
        let policy = store.load().map(|(_, policy)| policy);
        let effective = policy.as_ref().map(|policy| policy.effective(&config.machine_id)).unwrap_or_default();
        let keys = shared_keys(&config, box_key, policy.as_ref());
        Current { config, policy, effective, keys }
    }

    /// What signs the machine's requests, when it has its box key and the admin's.
    pub fn auth(&self) -> Option<Auth> {
        self.keys.clone().map(|keys| Auth { machine_id: self.config.machine_id.clone(), keys })
    }

    /// The admin, for authenticated requests.
    pub fn admin(&self) -> Option<Admin> {
        Some(Admin::with_auth(&self.config.admin_url, self.auth()?))
    }

    pub fn department(&self) -> Option<String> {
        self.policy.as_ref()?.department_of(&self.config.machine_id).map(str::to_string)
    }

    pub fn serial(&self) -> u64 {
        self.policy.as_ref().map_or(0, |policy| policy.serial)
    }

    /// The Wi-Fi passphrases sealed for this machine: ssid → passphrase.
    pub fn wifi_secrets(&self) -> Result<BTreeMap<String, String>, String> {
        let Some(sealed) = self.policy.as_ref().and_then(|policy| policy.sealed_for(&self.config.machine_id)) else {
            return Ok(BTreeMap::new());
        };
        let keys = self.keys.as_ref().ok_or("this machine has no box key to open its secrets")?;
        let plaintext = keys.unseal(sealed, &self.config.machine_id)?;
        let value: Value = serde_json::from_slice(&plaintext).map_err(|_| "the sealed secrets are not JSON".to_string())?;
        Ok(value["wifi"]
            .as_object()
            .into_iter()
            .flatten()
            .filter_map(|(ssid, passphrase)| Some((ssid.clone(), passphrase.as_str()?.to_string())))
            .collect())
    }

    /// The remote help session's key, sealed for this machine: (identity, 64 hex digits).
    pub fn remote_help_key(&self, sealed: &str) -> Result<(String, String), String> {
        let keys = self.keys.as_ref().ok_or("this machine has no box key")?;
        let plaintext = keys.unseal(sealed, &self.config.machine_id)?;
        let value: Value = serde_json::from_slice(&plaintext).map_err(|_| "the sealed key is not JSON".to_string())?;
        let identity = value["identity"].as_str().unwrap_or_default();
        let key = value["key"].as_str().unwrap_or_default();
        let hex = |text: &str, len: usize| text.len() == len && text.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'));
        if !identity.strip_prefix("rh-").is_some_and(|digits| hex(digits, 16)) || !hex(key, 64) {
            return Err("the sealed key is not an identity and a 32-byte key".to_string());
        }
        Ok((identity.to_string(), key.to_string()))
    }

    /// The effective settings file for the session parts.
    fn effective_file(&self) -> Option<EffectiveFile> {
        let policy = self.policy.as_ref()?;
        let files = policy
            .files
            .iter()
            .map(|(sha, file)| (sha.clone(), json!({"size": file.size, "type": file.kind})))
            .collect();
        Some(EffectiveFile {
            serial: policy.serial,
            machine_id: self.config.machine_id.clone(),
            department: self.department(),
            admin_name: self.config.admin_name.clone(),
            files,
            settings: policy.effective_json(&self.config.machine_id),
        })
    }
}

/// How a round went.
enum Round {
    NotPaired,
    Problem(String),
    /// This disk is a clone of the paired machine: nothing is applied, put back or reported.
    Clone,
    /// The admin has not approved the machine yet: nothing else is done.
    Pending,
    /// The company removed the machine: everything was put back, the pairing is gone, the service disabled. The daemon
    /// exits.
    Removed,
    Done(Result<Updated, String>),
}

/// What the daemon and the session parts log on a cloned disk (PROTOCOL.md part 2 "Cloned disks").
pub const CLONE_MESSAGE: &str = "máy này là bản sao của máy đã ghép; hãy ghép lại";
/// What `round_now` says for a machine waiting for approval.
pub const PENDING_MESSAGE: &str = "the admin has not approved this machine yet";
/// What `round_now` says once the company removed the machine.
pub const REMOVED_MESSAGE: &str = "the company removed this machine";

/// The inventory's bookkeeping.
#[derive(Debug, Default)]
struct InventoryState {
    collected: Option<Instant>,
    sent_hash: Option<String>,
    /// It was off at the last look (not in effect here, or the admin answered 403): sent at once when it comes on.
    off: bool,
}

/// What became of the inventory.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum InventoryOutcome {
    Sent,
    NotDue,
    /// Not in this machine's effective settings, or not in the admin's (403: its policy is newer than ours).
    Off,
}

/// Results not sent yet.
#[derive(Debug, Default)]
struct Results {
    queue: Vec<CommandResult>,
    next_try: Option<Instant>,
}

/// One logger per topic, so that a failure that lasts is logged once.
#[derive(Debug, Default)]
struct Logs {
    rounds: Once,
    check_ins: Once,
    wait: Once,
    results: Once,
    box_key: Once,
    help: Once,
    tickets: Once,
    approval: Once,
    maintenance: Once,
}

/// What the threads share.
pub struct Daemon {
    pub paths: Paths,
    pub store: Store,
    pub system: System,
    worker: Sender<Command>,
    update_lock: Mutex<()>,
    current: Mutex<Option<Current>>,
    record: Mutex<CommandRecord>,
    outstanding: Mutex<Vec<Pending>>,
    withdraw_later: Mutex<Vec<(u32, String, i64)>>,
    results: Mutex<Results>,
    managed: Mutex<Managed>,
    applied: Mutex<BTreeMap<String, String>>,
    health: Mutex<Option<(Instant, Value)>>,
    snapshot_space: Mutex<Option<(Instant, Option<u64>)>>,
    inventory: Mutex<InventoryState>,
    apps_outcome: Mutex<Option<Result<(), String>>>,
    logs: Mutex<Logs>,
    /// When this boot started (`btime`): commands for the people at the machine issued before it are not run.
    boot_time: Option<i64>,
    /// This boot is frozen: `/` is overlayroot.
    pub frozen: bool,
    /// This is a frozen machine's maintenance boot (`caramos-business.maintenance=1`).
    pub maintenance_boot: bool,
    /// A round is wanted at once: a 410 came, which only the policy can confirm.
    fetch_now: AtomicBool,
    /// Rounds that brought a policy, in this run.
    good_rounds: AtomicU64,
    /// The version of the tickets stored in `tickets/version`.
    tickets_version: Mutex<u64>,
    /// The tickets were fetched once in this run (on a frozen machine the first fetch only stores).
    tickets_fetched: AtomicBool,
    /// The tickets are to be fetched at the next good round.
    tickets_due: AtomicBool,
    maintenance_day: Mutex<shared::MaintenanceDay>,
    /// The maintenance boot's work is not finished: its time limit restarts the machine.
    maintenance_running: AtomicBool,
    /// uid → the user's private group, or None (their inbox stays readable by all, PROTOCOL.md part 3).
    private_groups: Mutex<BTreeMap<u32, Option<u32>>>,
}

/// The body of one of the daemon's threads.
type Loop = fn(Arc<Daemon>);

/// A lock that a panicked thread does not poison for the others.
fn lock<T>(mutex: &Mutex<T>) -> MutexGuard<'_, T> {
    mutex.lock().unwrap_or_else(|poisoned| poisoned.into_inner())
}

pub fn main() -> ExitCode {
    logging::set_prefix("");
    log!("caramos-business-agent {} started", env!("CARGO_PKG_VERSION"));
    let paths = Paths::system();
    // What waited for answers lived in the last run's memory: its inbox entries would wait for nothing.
    let _ = std::fs::remove_dir_all(&paths.inbox);
    let system = System::real();
    // A frozen machine that left or was removed finishes in its next unfrozen boot, before anything else and without
    // the network (PROTOCOL.md part 3 "Leaving and removal of a frozen machine").
    if Store::new(&paths.state).leave_pending_path().exists() {
        return finish_pending_leave(&paths, &system);
    }
    let (worker, queued) = mpsc::channel();
    let daemon = Arc::new(Daemon::new(paths, system, worker));
    if daemon.frozen {
        log!("this boot is frozen: changes are undone at the next restart");
        if let Err(error) = shared::mask_update_timers(&daemon.system) {
            log!("cannot mask the update timers: {error}");
        }
        daemon.note_missed_maintenance();
    }
    if daemon.maintenance_boot {
        let maintenance = Arc::clone(&daemon);
        thread::Builder::new().name("maintenance".into()).spawn(move || maintenance.maintenance_loop()).expect("a thread");
    }
    let threads: [(&str, Loop); 3] = [("wait", Daemon::wait_loop), ("relay", Daemon::relay_loop), ("scheduler", Daemon::scheduler_loop)];
    for (name, body) in threads {
        let daemon = Arc::clone(&daemon);
        thread::Builder::new().name(name.into()).spawn(move || body(daemon)).expect("a thread");
    }
    let worker_daemon = Arc::clone(&daemon);
    thread::Builder::new().name("worker".into()).spawn(move || worker_daemon.worker_loop(queued)).expect("a thread");
    daemon.main_loop()
}

/// How long `leave` waits for the session parts to put back the users' part.
pub const LEAVE_WAIT: Duration = Duration::from_secs(15);

/// What `leave` did.
#[derive(Debug, Default)]
pub struct Left {
    /// What could not be put back, with why.
    pub failed: Vec<String>,
    /// The users whose session part put back their part (bookmarks, Desktop and Documents, screen lock).
    pub users_done: Vec<String>,
    /// The users whose session part did not do it in time: it does at its next round, or at their next login.
    pub users_late: Vec<String>,
    /// The machine is frozen: what was put back holds until the restart, which finishes the leave on the disk.
    pub reboot_needed: bool,
}

/// `caramos-business-agent leave` (root): the machine leaves the company. The helper runs it first, before it
/// disables the service and deletes the pairing and the policy. It stops the service, so that no round applies the
/// policy again meanwhile, then puts everything back (see `leave`). Nothing in it uses the network. On a frozen machine
/// it first takes the freeze and a leave marker onto the disk, and prints `reboot needed`: the next, unfrozen, boot
/// finishes on the disk.
pub fn leave_main() -> ExitCode {
    let system = System::real();
    if let Err(error) = system.check("systemctl", &["stop", AGENT_UNIT], Duration::from_secs(60)) {
        eprintln!("cannot stop {AGENT_UNIT}: {error}");
    }
    let paths = Paths::system();
    let frozen = shared::is_frozen(&system);
    if frozen {
        let admin_name = AgentConfig::load(&paths.config).ok().flatten().map(|config| config.admin_name).unwrap_or_default();
        if let Err(error) = prepare_frozen_leave(&paths, &system, "leave", &admin_name, &LocalTime::now().iso8601()) {
            eprintln!("this frozen machine cannot keep the leave: {error}");
            return ExitCode::FAILURE;
        }
    }
    let left = leave(&paths, &system, LEAVE_WAIT);
    for failure in &left.failed {
        eprintln!("{failure}");
    }
    if !left.users_done.is_empty() {
        println!("put back for {}", left.users_done.join(", "));
    }
    if !left.users_late.is_empty() {
        println!("not yet put back for {} (at their next round or login)", left.users_late.join(", "));
    }
    if left.reboot_needed {
        println!("reboot needed");
        return ExitCode::SUCCESS;
    }
    if left.failed.is_empty() {
        println!("put back what CaramOS Doanh nghiệp changed");
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

/// Steps 1 and 2 of a frozen machine's leave or removal: the freeze off the disk (`overlayroot-chroot`), and
/// `leave-pending.json` written on the disk, so that the next boot is unfrozen and finishes there. `time` is when the
/// machine left, or when the company removed it.
pub fn prepare_frozen_leave(paths: &Paths, system: &System, reason: &str, admin_name: &str, time: &str) -> Result<(), String> {
    let store = Store::new(&paths.state);
    let mut managed = Managed::load(&store.managed_path());
    shared::apply(system, None, &Effective::default(), &mut managed, true)?;
    let marker = json!({"reason": reason, "admin_name": admin_name, "time": time});
    let text = format!("{marker}\n");
    let path = store.leave_pending_path();
    let absolute = path.to_string_lossy().into_owned();
    shared::chroot_write(system, &absolute, &text)?;
    // Also in the overlay, for this boot.
    store::write_atomic(&path, text.as_bytes(), 0o644).map_err(|error| format!("{absolute}: {error}"))
}

/// Puts back what the daemon changed: the browser policies and the hosts block, the print queues, the USB rules and
/// any `usb_unlock`, the Wi-Fi profiles, wake-on-lan and the wake alarm, ufw as it was before the agent first changed
/// it, the guest session, Timeshift's settings and the freeze. On a frozen machine the freeze and Timeshift are left
/// to the next unfrozen boot. Apps installed or removed for `apps` stay as they are. The failures, with why.
pub fn put_back_system(system: &System, managed: &mut Managed, frozen: bool) -> Vec<String> {
    let now = LocalTime::now();
    let unix = clock::unix_now();
    let mut failed = Vec::new();
    let mut check = |name: &str, result: Result<(), String>| {
        if let Err(error) = result {
            failed.push(format!("{name}: {error}"));
        }
    };
    check("browser", browser::apply(system, None, managed, &now));
    if !managed.printers.is_empty() {
        check("printers", printers::apply(system, None, managed));
    }
    managed.usb_unlock_until = None;
    check("usb", usb::apply(system, None, managed, unix));
    check("wifi", wifi::apply(system, None, &BTreeMap::new(), managed));
    check("power", power::apply(system, None, managed, unix, false));
    check("firewall", firewall::put_back(system, managed));
    if frozen {
        // Only the guest file in the overlay; the freeze went off the disk in prepare_frozen_leave.
        let _ = sections::remove_if_present(&system.path(shared::GUEST_CONF));
    } else {
        check("shared", shared::apply(system, None, &Effective::default(), managed, false));
        check("snapshots", snapshots::put_back(system, managed));
    }
    failed
}

/// Puts everything back (`put_back_system`), then removes effective.json, commands.json, the approval, the tickets,
/// the clone mark and the inboxes: without effective.json each user's session part puts back their part at its next
/// poll (2 s), and stops any prompt or remote help; it is done once its status is written again with nothing applied,
/// which this waits up to `wait` to see.
pub fn leave(paths: &Paths, system: &System, wait: Duration) -> Left {
    let store = Store::new(&paths.state);
    let mut managed = Managed::load(&store.managed_path());
    let frozen = shared::is_frozen(system);
    let mut left = Left { reboot_needed: frozen, ..Left::default() };
    left.failed = put_back_system(system, &mut managed, frozen);
    if store.managed_path().exists() {
        if let Err(error) = managed.save(&store.managed_path()) {
            left.failed.push(format!("managed.json: {error}"));
        }
    }

    let removed_at = SystemTime::now();
    for path in [store.effective_path(), store.commands_path(), store.approval_path(), store.maintenance_path()] {
        let _ = std::fs::remove_file(path);
    }
    let _ = std::fs::remove_dir_all(store.tickets_dir());
    store.unmark_clone(); // a cloned disk leaves too ("Ghép lại"): its session parts would wait for the mark otherwise
    let _ = std::fs::remove_dir_all(&paths.inbox);
    let mut waiting = relay::sessions(&paths.run_user);
    let deadline = Instant::now() + wait;
    loop {
        waiting.retain(|session| {
            let done = put_back_by(&paths.run_user, session.uid, removed_at);
            if done {
                left.users_done.push(session.user.clone());
            }
            !done
        });
        if waiting.is_empty() || Instant::now() >= deadline {
            break;
        }
        thread::sleep(Duration::from_millis(250));
    }
    left.users_late = waiting.into_iter().map(|session| session.user).collect();
    left
}

/// After a leave or a removal: the pairing goes (agent.json, the machine key, the stored policy and what follows), and
/// managed.json once everything was put back.
fn forget_pairing(paths: &Paths, store: &Store, everything_back: bool) {
    let _ = std::fs::remove_file(&paths.config);
    let _ = std::fs::remove_file(&paths.box_key);
    store.remove_pairing_state();
    if everything_back {
        let _ = std::fs::remove_file(store.managed_path());
    }
}

/// Writes removed.json (0644): `{"admin_name", "time"}`, for the window.
fn write_removed(store: &Store, removal: &Removal) {
    let data = json!({"admin_name": removal.admin_name, "time": removal.time});
    if let Err(error) = store.create_dirs().and_then(|()| store::write_atomic(&store.removed_path(), format!("{data}\n").as_bytes(), 0o644)) {
        log!("cannot write {}: {error}", store.removed_path().display());
    }
}

/// Step 5 of a frozen machine's leave or removal, in the next unfrozen boot: the leave routine on the disk, the GRUB
/// entry and the pairing gone, removed.json when the company removed it, the marker gone, the service disabled.
pub fn finish_pending_leave(paths: &Paths, system: &System) -> ExitCode {
    let store = Store::new(&paths.state);
    let marker: Value = store::read_limited(&store.leave_pending_path(), 64 * 1024)
        .ok()
        .and_then(|data| serde_json::from_slice(&data).ok())
        .unwrap_or_default();
    let reason = marker["reason"].as_str().unwrap_or("leave").to_string();
    let admin_name = marker["admin_name"].as_str().unwrap_or_default().to_string();
    if shared::is_frozen(system) {
        // The freeze is still on the disk (overlayroot-chroot failed, or the file came back): take it off again and keep
        // this boot clean; the next boot finishes.
        log!("the machine left the company but is still frozen: taking the freeze off the disk again");
        let time = marker["time"].as_str().map_or_else(|| LocalTime::now().iso8601(), str::to_string);
        if let Err(error) = prepare_frozen_leave(paths, system, &reason, &admin_name, &time) {
            log!("{error}");
        }
        let _ = leave(paths, system, Duration::ZERO);
        forget_pairing(paths, &store, false);
        let _ = system.check("systemctl", &["disable", AGENT_UNIT], TOOL_TIMEOUT);
        return ExitCode::SUCCESS;
    }
    log!("finishing the {reason} of this machine, which was frozen, on its disk");
    let left = leave(paths, system, Duration::ZERO);
    for failure in &left.failed {
        log!("putting back: {failure}");
    }
    forget_pairing(paths, &store, left.failed.is_empty());
    if reason == "removed" {
        let time = marker["time"].as_str().unwrap_or_default().to_string();
        write_removed(&store, &Removal { admin_name, time });
    }
    let _ = std::fs::remove_file(store.leave_pending_path());
    if let Err(error) = system.check("systemctl", &["disable", AGENT_UNIT], TOOL_TIMEOUT) {
        log!("{error}");
    }
    log!("CaramOS Doanh nghiệp's settings are off this machine");
    ExitCode::SUCCESS
}

/// Whether a user's session part wrote its status since `since`, with no section applied.
fn put_back_by(run_user: &Path, uid: u32, since: SystemTime) -> bool {
    let file = run_user.join(uid.to_string()).join(crate::protocol::RUNTIME_SUBDIR).join("status.json");
    let fresh = std::fs::metadata(&file).and_then(|metadata| metadata.modified()).is_ok_and(|mtime| mtime > since);
    fresh && status::read_owned_file(&file, uid, 64 * 1024).is_some_and(|data| status::parse_applied(&data).is_empty())
}

impl Daemon {
    pub fn new(paths: Paths, system: System, worker: Sender<Command>) -> Daemon {
        let store = Store::new(&paths.state);
        let frozen = shared::is_frozen(&system);
        let maintenance_boot = !frozen && shared::is_maintenance_boot(&system);
        Daemon {
            record: Mutex::new(CommandRecord::load(&store.commands_path())),
            managed: Mutex::new(Managed::load(&store.managed_path())),
            tickets_version: Mutex::new(tickets::stored_version(&store.tickets_dir())),
            paths,
            store,
            system,
            worker,
            update_lock: Mutex::new(()),
            current: Mutex::new(None),
            outstanding: Mutex::new(Vec::new()),
            withdraw_later: Mutex::new(Vec::new()),
            results: Mutex::new(Results::default()),
            applied: Mutex::new(BTreeMap::new()),
            health: Mutex::new(None),
            snapshot_space: Mutex::new(None),
            inventory: Mutex::new(InventoryState::default()),
            apps_outcome: Mutex::new(None),
            logs: Mutex::new(Logs::default()),
            boot_time: clock::boot_time(),
            frozen,
            maintenance_boot,
            fetch_now: AtomicBool::new(false),
            good_rounds: AtomicU64::new(0),
            tickets_fetched: AtomicBool::new(false),
            tickets_due: AtomicBool::new(true),
            maintenance_day: Mutex::new(shared::MaintenanceDay::default()),
            maintenance_running: AtomicBool::new(false),
            private_groups: Mutex::new(BTreeMap::new()),
        }
    }

    fn current(&self) -> Option<Current> {
        lock(&self.current).clone()
    }

    /// For tests: the boot time that decides which commands are from before this boot (the machine's own otherwise,
    /// which a test cannot choose).
    pub fn assume_boot_time(&mut self, boot_time: Option<i64>) {
        self.boot_time = boot_time;
    }

    fn main_loop(&self) -> ExitCode {
        let mut failures: u32 = 0;
        let mut unpaired_logged = false;
        let mut clone_logged = false;
        loop {
            self.fetch_now.store(false, Ordering::SeqCst);
            let round = self.round();
            if !matches!(round, Round::Clone) {
                clone_logged = false;
            }
            let wait = match round {
                Round::Removed => return ExitCode::SUCCESS,
                Round::Clone => {
                    if !clone_logged {
                        log!("{CLONE_MESSAGE}");
                        clone_logged = true;
                    }
                    RETRY
                }
                Round::NotPaired => {
                    if !unpaired_logged {
                        log!("{} does not exist: this machine is not paired yet; looking again every minute", self.paths.config.display());
                        unpaired_logged = true;
                    }
                    RETRY
                }
                Round::Pending => RETRY,
                Round::Problem(error) => {
                    unpaired_logged = false;
                    lock(&self.logs).rounds.log(&error);
                    RETRY
                }
                Round::Done(outcome) => {
                    unpaired_logged = false;
                    match outcome {
                        Ok(_) => {
                            lock(&self.logs).rounds.clear("the policy is up to date again");
                            failures = 0;
                        }
                        Err(error) => {
                            lock(&self.logs).rounds.log(&error);
                            failures = failures.saturating_add(1);
                        }
                    }
                    wait_after(failures)
                }
            };
            // A 410 from another thread asks for a round at once.
            let until = Instant::now() + wait;
            while Instant::now() < until && !self.fetch_now.load(Ordering::SeqCst) {
                thread::sleep(Duration::from_secs(1));
            }
        }
    }

    /// One round now, for tests and tools: Ok(None) when the machine is not paired.
    pub fn round_now(&self) -> Result<Option<Updated>, String> {
        match self.round() {
            Round::NotPaired => Ok(None),
            Round::Problem(error) => Err(error),
            Round::Clone => Err(CLONE_MESSAGE.to_string()),
            Round::Pending => Err(PENDING_MESSAGE.to_string()),
            Round::Removed => Err(REMOVED_MESSAGE.to_string()),
            Round::Done(outcome) => outcome.map(Some),
        }
    }

    /// The results not sent yet.
    pub fn unsent_results(&self) -> Vec<CommandResult> {
        lock(&self.results).queue.clone()
    }

    /// A 410 came: only the policy can say whether the machine was removed.
    fn gone(&self) {
        self.fetch_now.store(true, Ordering::SeqCst);
    }

    /// One round, under the update lock: update, effective settings, sections, check-in, inventory, tickets.
    fn round(&self) -> Round {
        let _guard = lock(&self.update_lock);
        let mut config = match AgentConfig::load(&self.paths.config) {
            Ok(Some(config)) => config,
            Ok(None) => return Round::NotPaired,
            Err(error) => return Round::Problem(error),
        };
        // A disk cloned from a paired machine carries its pairing: acting on it would make every clone one machine.
        // Nothing is applied, put back or reported until the clone is paired again.
        if let Some((paired_on, here)) = store::cloned(&config, &self.paths.os_machine_id) {
            *lock(&self.current) = None;
            if let Err(error) = self.store.mark_clone(&paired_on, &here) {
                log!("cannot write {}: {error}", self.store.clone_path().display());
            }
            return Round::Clone;
        }
        self.store.unmark_clone();
        let box_key = match store::load_box_key(&self.paths.box_key) {
            Ok(Some(key)) => {
                lock(&self.logs).box_key.clear("");
                Some(key)
            }
            Ok(None) => {
                lock(&self.logs).box_key.log(&format!("{} does not exist: the machine cannot sign its requests; pair it again", self.paths.box_key.display()));
                None
            }
            Err(error) => {
                lock(&self.logs).box_key.log(&error);
                None
            }
        };
        // From 0.3 every request but /hello is signed, the policy's too.
        let stored = self.store.load().map(|(_, policy)| policy);
        let Some(keys) = shared_keys(&config, box_key, stored.as_ref()) else {
            *lock(&self.current) = Some(Current::load(config, box_key, &self.store));
            return Round::Problem("this machine cannot sign its requests (no machine key, or no admin box key yet): pair it again".to_string());
        };
        let auth = Auth { machine_id: config.machine_id.clone(), keys };
        let mut admin = Admin::with_auth(&config.admin_url, auth.clone());
        let mut outcome = update(&admin, &config, &self.store);
        if outcome.as_ref().is_err_and(Failure::admin_may_have_moved) {
            if let Some((ip, port)) = find_moved_admin(&config, &auth) {
                let url = store::admin_url(ip, port);
                log!("the admin {} answers at {url} now (it was at {})", config.admin_name, config.admin_url);
                if let Err(error) = store::save_admin_url(&self.paths.config, &url) {
                    log!("{error}");
                }
                config.admin_url = url;
                config.admin_ip = ip;
                config.admin_port = port;
                admin = Admin::with_auth(&config.admin_url, auth.clone());
                outcome = update(&admin, &config, &self.store);
            }
        }
        let now = LocalTime::now().iso8601();
        match &outcome {
            Ok(Fetched::Pending) => {
                *lock(&self.current) = None;
                if let Err(error) = self.store.mark_approval("pending", &now) {
                    log!("cannot write {}: {error}", self.store.approval_path().display());
                }
                lock(&self.logs).approval.log("waiting for the admin to approve this machine; asking again every minute");
                return Round::Pending;
            }
            Ok(Fetched::Removed(removal)) => {
                let removal = removal.clone();
                return self.remove_from_company(&config, &removal);
            }
            Ok(Fetched::Policy(_)) => {
                lock(&self.logs).approval.clear("");
                if let Ok(true) = self.store.mark_approval("approved", &now) {
                    log!("the admin approved this machine");
                }
            }
            Err(Failure::BadNotice(error)) => log!("a removal notice was ignored: {error}"),
            Err(Failure::Fetch(FetchError::Gone)) => {}
            Err(_) => {}
        }
        let outcome = outcome.map(|fetched| match fetched {
            Fetched::Policy(updated) => updated,
            Fetched::Pending | Fetched::Removed(_) => unreachable!("handled above"),
        });
        let proven = outcome.as_ref().map_or_else(Failure::admin_proven, |_| true);
        let current = Current::load(config, box_key, &self.store);
        *lock(&self.current) = Some(current.clone());
        match current.effective_file() {
            Some(file) => {
                if let Err(error) = self.store.save_effective(&file) {
                    log!("cannot write {}: {error}", self.store.effective_path().display());
                }
            }
            None => {
                let _ = std::fs::remove_file(self.store.effective_path());
            }
        }
        if current.policy.is_some() {
            self.apply_sections(&current);
        }
        if proven {
            self.check_in(&current);
            if let Err(error) = self.inventory(&current, false) {
                log!("inventory: {error}");
            }
        }
        if outcome.is_ok() {
            self.good_rounds.fetch_add(1, Ordering::SeqCst);
            if self.tickets_due.swap(false, Ordering::SeqCst) {
                self.fetch_tickets(&current);
            }
        }
        Round::Done(outcome.map_err(|failure| failure.to_string()))
    }

    /// A valid removal notice (PROTOCOL.md part 3 "Removal from the company"): the leave routine with ufw too (on a
    /// frozen machine its frozen variant), the pairing forgotten, removed.json, the service disabled.
    fn remove_from_company(&self, config: &AgentConfig, removal: &Removal) -> Round {
        log!("the company removed this machine from the admin {} at {}: putting everything back", removal.admin_name, removal.time);
        *lock(&self.current) = None;
        // No scheduler step may apply anything again meanwhile.
        let _managed = lock(&self.managed);
        let admin_name = if removal.admin_name.is_empty() { config.admin_name.clone() } else { removal.admin_name.clone() };
        let removal = Removal { admin_name: admin_name.clone(), time: removal.time.clone() };
        if self.frozen {
            if let Err(error) = prepare_frozen_leave(&self.paths, &self.system, "removed", &admin_name, &removal.time) {
                log!("the frozen machine cannot keep the removal on its disk: {error}");
            }
        }
        let left = leave(&self.paths, &self.system, LEAVE_WAIT);
        for failure in &left.failed {
            log!("putting back: {failure}");
        }
        if !left.users_late.is_empty() {
            log!("not yet put back for {} (at their next login)", left.users_late.join(", "));
        }
        forget_pairing(&self.paths, &self.store, left.failed.is_empty() && !self.frozen);
        write_removed(&self.store, &removal);
        if let Err(error) = self.system.check("systemctl", &["disable", AGENT_UNIT], TOOL_TIMEOUT) {
            log!("{error}");
        }
        if self.frozen {
            log!("the machine is frozen: the next restart takes the company's settings off its disk");
        }
        Round::Removed
    }

    /// The user's private group, for their inbox; None (logged once) when they have none.
    fn private_group(&self, uid: u32) -> Option<u32> {
        let mut groups = lock(&self.private_groups);
        if let Some(known) = groups.get(&uid) {
            return *known;
        }
        let group = match accounts::by_uid(&self.system, uid) {
            Some(account) => match accounts::private_group(&self.system, &account) {
                Ok(gid) => Some(gid),
                Err(why) => {
                    log!("{why}: its inbox stays readable by all users");
                    None
                }
            },
            None => {
                log!("uid {uid} has no account: its inbox stays readable by all users");
                None
            }
        };
        groups.insert(uid, group);
        group
    }

    /// The effective freeze of this machine, when it is in effect here (not refused).
    fn freeze_in_effect<'a>(&self, effective: &'a Effective) -> Option<&'a crate::settings::Shared> {
        effective.shared.as_ref().filter(|shared| shared.freeze && shared::refusal(shared, effective, shared::memory_mb(&self.system)).is_none())
    }

    /// Applies the system sections for the effective settings, putting back those that went away.
    fn apply_sections(&self, current: &Current) {
        let mut managed = lock(&self.managed);
        let before = managed.clone();
        let effective = &current.effective;
        let now = LocalTime::now();
        let unix = clock::unix_now();
        let mut applied = BTreeMap::new();
        let mut note = |name: &str, on: bool, result: Result<(), String>| {
            if on {
                applied.insert(name.to_string(), sections::outcome(&result));
            } else if let Err(error) = result {
                log!("putting {name} back: {error}");
            }
        };
        note("browser", effective.browser.is_some(), browser::apply(&self.system, effective.browser.as_ref(), &mut managed, &now));
        if effective.printers.is_some() || !managed.printers.is_empty() {
            note("printers", effective.printers.is_some(), printers::apply(&self.system, effective.printers.as_deref(), &mut managed));
        }
        note("usb", effective.usb.is_some(), usb::apply(&self.system, effective.usb.as_ref(), &mut managed, unix));
        if effective.firewall.is_some() {
            note("firewall", true, firewall::apply(&self.system, effective.firewall.as_ref(), &mut managed));
        }
        if effective.wifi.is_some() || !managed.wifi.is_empty() {
            let result = current.wifi_secrets().and_then(|secrets| wifi::apply(&self.system, effective.wifi.as_deref(), &secrets, &mut managed));
            note("wifi", effective.wifi.is_some(), result);
        }
        let maintenance_alarm = self.freeze_in_effect(effective).is_some_and(|shared| shared.maintenance.is_some());
        if effective.power.is_some() || !managed.wake_on_lan.is_empty() || managed.power_day.is_some() || managed.rtc_wake.is_some() {
            note("power", effective.power.is_some(), power::apply(&self.system, effective.power.as_ref(), &mut managed, unix, maintenance_alarm));
        }
        // A frozen machine installs and removes apps only in its maintenance boot: an install into the overlay would be
        // repeated at every boot.
        if !self.frozen && (effective.apps.is_some() || managed.apps_section.is_some()) {
            let last = lock(&self.apps_outcome).clone();
            let result = apps::apply(&self.system, effective.apps.as_ref(), &mut managed, unix, last);
            *lock(&self.apps_outcome) = Some(result.clone());
            note("apps", effective.apps.is_some(), result);
        }
        note("shared", effective.shared.is_some(), shared::apply(&self.system, effective.shared.as_ref(), effective, &mut managed, self.frozen));
        if effective.snapshots.is_some() || (managed.timeshift.is_some() && !self.frozen) {
            note("snapshots", effective.snapshots.is_some(), snapshots::apply(&self.system, effective.snapshots.as_ref(), &mut managed, self.frozen));
        }
        if *managed != before {
            if let Err(error) = managed.save(&self.store.managed_path()) {
                log!("cannot write {}: {error}", self.store.managed_path().display());
            }
        }
        *lock(&self.applied) = applied;
    }

    /// The health for the check-in: collected at most every 30 minutes, with the latest outcomes of the sections in
    /// effect (the session part's sections from the users' status files) and 0.3's keys of each check-in.
    fn health(&self, current: &Current, reports: &[UserReport]) -> Value {
        let base = {
            let mut cache = lock(&self.health);
            if cache.as_ref().is_none_or(|(at, _)| at.elapsed() >= health::EVERY) {
                *cache = Some((Instant::now(), health::collect(&self.system)));
            }
            cache.as_ref().map(|(_, health)| health.clone()).unwrap_or_default()
        };
        let mut applied = lock(&self.applied).clone();
        let in_effect = current.effective.in_effect();
        for section in ["wallpaper", "folders", "shares", "screen_lock"] {
            if !in_effect.contains(section) {
                continue;
            }
            let outcomes: Vec<(&str, &String)> = reports
                .iter()
                .filter_map(|report| report.applied.get(section).map(|outcome| (report.status.user.as_str(), outcome)))
                .collect();
            let failed = outcomes.iter().find(|(_, outcome)| outcome.starts_with("failed"));
            let value = match failed {
                Some((user, outcome)) => format!("failed: {user}: {}", outcome.trim_start_matches("failed: ")),
                None if !outcomes.is_empty() => "ok".to_string(),
                None => continue,
            };
            applied.insert(section.to_string(), value);
        }
        let at_screen = relay::seat_user(&self.paths.sessions);
        let usb_storage = {
            let managed = lock(&self.managed);
            if managed.usb_unlock_until.is_some_and(|until| clock::unix_now() < until) {
                "unlocked".to_string()
            } else {
                match current.effective.usb.as_ref().map(|usb| usb.storage) {
                    Some(UsbStorage::ReadOnly) => "read-only".to_string(),
                    Some(UsbStorage::Block) => "block".to_string(),
                    Some(UsbStorage::Allow) | None => "allow".to_string(),
                }
            }
        };
        let record = MaintenanceRecord::load(&self.store.maintenance_path());
        let security = health::Security {
            screen_lock_on: at_screen.and_then(|uid| reports.iter().find(|report| report.uid == uid)).and_then(|report| report.screen_lock_on),
            usb_storage,
            frozen: self.frozen,
            freeze_configured: shared::freeze_configured(&self.system, self.frozen),
            last_maintenance: record.last.clone(),
            maintenance_result: record.result.clone(),
            last_snapshot: snapshots::last_snapshot(&self.system),
            snapshot_space_mb: self.snapshot_space(),
        };
        health::with_security(health::with_applied(base, &applied), &security)
    }

    /// `du -sm /timeshift`, at most every 6 hours.
    fn snapshot_space(&self) -> Option<u64> {
        let mut cache = lock(&self.snapshot_space);
        if cache.as_ref().is_none_or(|(at, _)| at.elapsed() >= SNAPSHOT_SPACE_EVERY) {
            *cache = Some((Instant::now(), snapshots::space_mb(&self.system)));
        }
        cache.as_ref().and_then(|(_, space)| *space)
    }

    fn check_in(&self, current: &Current) {
        let Some(admin) = current.admin() else {
            return;
        };
        let machine = machine::describe(current.config.admin_ip, current.config.admin_port);
        let reports = status::read_reports(&self.paths.run_user);
        let users: Vec<UserStatus> = reports.iter().map(|report| report.status.clone()).collect();
        let health = self.health(current, &reports);
        let body = check_in_body(&current.config, &machine, current.policy.as_ref().map(|policy| policy.serial), users, &health);
        let outcome = admin.check_in(&body);
        if outcome == Err(FetchError::Gone) {
            self.gone();
        }
        let mut logs = lock(&self.logs);
        match outcome {
            Ok(()) => logs.check_ins.clear("check-in works again"),
            Err(FetchError::Status(401)) => logs.check_ins.log("check-in refused (401): the admin does not know this machine's key; pair it again"),
            Err(error) => logs.check_ins.log(&format!("check-in failed: {error}")),
        }
    }

    /// Sends the inventory when it is on and due (or `forced`, for the command). Off is not an error: the admin
    /// answers 403 while the inventory is not in its effective settings for this machine, which happens when its
    /// policy is newer than the one here; it is not tried again until it is due.
    fn inventory(&self, current: &Current, forced: bool) -> Result<InventoryOutcome, String> {
        let mut state = lock(&self.inventory);
        if !current.effective.inventory_enabled() {
            state.off = true;
            return Ok(InventoryOutcome::Off);
        }
        let due = forced || state.off || state.collected.is_none_or(|at| at.elapsed() >= INVENTORY_EVERY);
        if !due {
            return Ok(InventoryOutcome::NotDue);
        }
        let collected = inventory::collect(&self.system);
        state.collected = Some(Instant::now());
        if !forced && !state.off && state.sent_hash.as_deref() == Some(collected.hash.as_str()) {
            return Ok(InventoryOutcome::NotDue);
        }
        let admin = current.admin().ok_or("the machine cannot sign its requests yet")?;
        let body = serde_json::to_vec(&collected).map_err(|error| error.to_string())?;
        match admin.inventory(&body) {
            Ok(()) => {
                state.off = false;
                state.sent_hash = Some(collected.hash);
                Ok(InventoryOutcome::Sent)
            }
            Err(FetchError::Status(403)) => {
                state.off = true;
                state.sent_hash = None;
                Ok(InventoryOutcome::Off)
            }
            Err(FetchError::Gone) => {
                self.gone();
                Err(FetchError::Gone.to_string())
            }
            Err(error) => Err(error.to_string()),
        }
    }

    /// Fetches the machine's tickets, checks them, writes each user's file and tells the users what changed (not at
    /// the first fetch of a frozen boot, whose files are the disk's old ones).
    fn fetch_tickets(&self, current: &Current) {
        let Some(admin) = current.admin() else {
            return;
        };
        let fetched = admin.tickets().map_err(|error| {
            if error == FetchError::Gone {
                self.gone();
            }
            format!("tickets: {error}")
        });
        let list = fetched.and_then(|signed| tickets::verify(&signed, &current.config.admin_key, &current.config.machine_id));
        let list = match list {
            Ok(list) => list,
            Err(error) => {
                self.tickets_due.store(true, Ordering::SeqCst);
                lock(&self.logs).tickets.log(&error);
                return;
            }
        };
        let first = !self.tickets_fetched.swap(true, Ordering::SeqCst);
        let tell = !(self.frozen && first);
        match tickets::store(&self.system, &self.store.tickets_dir(), &list, tell) {
            Ok(stored) => {
                lock(&self.logs).tickets.clear("");
                for problem in &stored.problems {
                    lock(&self.logs).tickets.log(problem);
                }
                *lock(&self.tickets_version) = list.version;
                let expires = clock::unix_now() + TICKET_NOTICE_STAYS;
                for (account, gid, change) in stored.changes {
                    let entry = InboxEntry {
                        id: change.relay_id(),
                        action: "ticket".to_string(),
                        args: json!({"ticket": change.ticket, "status": change.status, "text": change.text}),
                        admin_name: current.config.admin_name.clone(),
                        expires,
                    };
                    match relay::deliver(&self.paths.inbox, account.uid, Some(gid), &entry) {
                        Ok(()) => lock(&self.withdraw_later).push((account.uid, entry.id.clone(), expires)),
                        Err(error) => log!("cannot tell {} about {}: {error}", account.name, change.ticket),
                    }
                }
            }
            Err(error) => {
                self.tickets_due.store(true, Ordering::SeqCst);
                lock(&self.logs).tickets.log(&format!("tickets: {error}"));
            }
        }
    }

    /// The long-poll channel: one `/wait` open all the time.
    fn wait_loop(self: Arc<Self>) {
        let mut tries: u64 = 0;
        loop {
            let Some(current) = self.current() else {
                thread::sleep(Duration::from_secs(30));
                continue;
            };
            let Some(admin) = current.admin() else {
                thread::sleep(Duration::from_secs(30));
                continue;
            };
            let after = self.record_for(&current.config.machine_id).last_seq;
            let serial = current.serial();
            match admin.wait(after, serial) {
                Ok(answer) => {
                    lock(&self.logs).wait.clear("the long-poll channel works again");
                    if answer.serial != serial {
                        // A round now, before the commands: they may target the machine through its new department.
                        if matches!(self.round(), Round::Removed) {
                            std::process::exit(0);
                        }
                        if self.current().map_or(0, |current| current.serial()) != answer.serial {
                            // The admin's policy was refused here: do not ask again at once.
                            thread::sleep(Duration::from_secs(30));
                        }
                    }
                    if answer.tickets != *lock(&self.tickets_version) || self.tickets_due.swap(false, Ordering::SeqCst) {
                        if let Some(current) = self.current() {
                            self.fetch_tickets(&current);
                        }
                    }
                    if !answer.commands.is_empty() {
                        self.receive(answer.commands);
                    }
                }
                Err(error @ (FetchError::Gone | FetchError::Pending)) => {
                    // Only the policy says whether the machine was removed, or still waits for approval.
                    lock(&self.logs).wait.log(&format!("long-poll: {error}"));
                    if matches!(self.round(), Round::Removed) {
                        std::process::exit(0);
                    }
                    thread::sleep(Duration::from_secs(30));
                }
                Err(error) => {
                    lock(&self.logs).wait.log(&format!("long-poll: {error}"));
                    tries += 1;
                    thread::sleep(Duration::from_secs(10 + (u64::from(std::process::id()) + tries * 7) % 21));
                }
            }
        }
    }

    /// Checks the commands from `/wait`, oldest first, and hands those to run to the worker.
    pub fn receive(&self, envelopes: Vec<Envelope>) {
        let Some(current) = self.current() else {
            return;
        };
        let department = current.department();
        for envelope in envelopes {
            let mut record = self.record_for(&current.config.machine_id);
            let decision = commands::decide(&envelope, &current.config.admin_key, &current.config.machine_id,
                                            department.as_deref(), &record, clock::unix_now(), self.boot_time);
            match decision {
                Decision::Skip(why) => log!("{why}"),
                Decision::Report { seq, id, state, detail } => {
                    record.record(seq, &id);
                    let _ = record.save(&self.store.commands_path());
                    drop(record);
                    log!("command {id}: {} ({detail})", state_name(state));
                    self.report(&id, state, &detail);
                }
                Decision::Run(command) => {
                    // Recorded before it acts, so that a restart or a shutdown never runs twice.
                    record.record(command.seq, &command.id);
                    if let Err(error) = record.save(&self.store.commands_path()) {
                        log!("cannot write {}: {error}", self.store.commands_path().display());
                    }
                    drop(record);
                    let _ = self.worker.send(command);
                }
            }
        }
    }

    /// The command record of this pairing: another machine id's record starts again (a new admin counts from 1).
    fn record_for(&self, machine_id: &str) -> MutexGuard<'_, CommandRecord> {
        let mut record = lock(&self.record);
        if record.adopt(machine_id) {
            if let Err(error) = record.save(&self.store.commands_path()) {
                log!("cannot write {}: {error}", self.store.commands_path().display());
            }
        }
        record
    }

    fn worker_loop(self: Arc<Self>, queued: Receiver<Command>) {
        for command in queued {
            log!("command {} ({})", command.id, action_name(&command.action));
            self.execute(command);
        }
    }

    /// Runs one command, or delivers it to the session parts and waits for them in the relay.
    fn execute(&self, command: Command) {
        let current = self.current();
        let admin_name = current.as_ref().map(|current| current.config.admin_name.clone()).unwrap_or_default();
        match command.action.clone() {
            Action::Sync => {
                let outcome = match self.round() {
                    Round::Done(Ok(updated)) => Ok(format!("thiết lập bản {}", updated.serial)),
                    Round::Done(Err(error)) | Round::Problem(error) => Err(error),
                    Round::NotPaired => Err("not paired".to_string()),
                    Round::Clone => Err(CLONE_MESSAGE.to_string()),
                    Round::Pending => Err(PENDING_MESSAGE.to_string()),
                    Round::Removed => std::process::exit(0),
                };
                self.report_outcome(&command.id, outcome);
            }
            Action::Inventory => {
                let Some(current) = current else {
                    return self.report(&command.id, ResultState::Failed, "no policy yet");
                };
                match self.inventory(&current, true) {
                    Ok(InventoryOutcome::Off) => self.report(&command.id, ResultState::Ignored, "kiểm kê chưa bật"),
                    outcome => self.report_outcome(&command.id, outcome.map(|_| "đã gửi".to_string())),
                }
            }
            Action::Lock => {
                // logind's lock for the desktops that follow it; Cinnamon 6.6 does not, so each session part also locks
                // its screen with the desktop's own command.
                let _ = self.system.run("loginctl", &["lock-sessions"], TOOL_TIMEOUT);
                let sessions = relay::sessions(&self.paths.run_user);
                self.deliver(&sessions, &command.id, "lock", json!({}), &admin_name, command.expires);
                self.wait_for(Pending::new(&command.id, Purpose::Lock, &sessions, clock::unix_now() + 30));
            }
            Action::Update => {
                if self.frozen {
                    return self.report(&command.id, ResultState::Ignored, FROZEN_UPDATE);
                }
                let effective = current.map(|current| current.effective).unwrap_or_default();
                let outcome = self.update_with_snapshot(&effective);
                self.report_outcome(&command.id, outcome);
            }
            Action::UsbUnlock { minutes } => {
                let until = clock::unix_now() + i64::from(minutes) * 60;
                let effective = current.map(|current| current.effective).unwrap_or_default();
                let mut managed = lock(&self.managed);
                managed.usb_unlock_until = Some(until);
                let outcome = usb::apply(&self.system, effective.usb.as_ref(), &mut managed, clock::unix_now());
                let _ = managed.save(&self.store.managed_path());
                let at = LocalTime::from_unix(until);
                self.report_outcome(&command.id, outcome.map(|()| format!("USB mở đến {:02}:{:02}", at.hour, at.minute)));
            }
            Action::Cancel { id } => {
                let mut outstanding = lock(&self.outstanding);
                let target = outstanding.iter_mut().find(|pending| pending.id == id && matches!(pending.purpose, Purpose::Countdown { .. }));
                match target {
                    Some(pending) => {
                        pending.cancelled = true;
                        let users: Vec<u32> = pending.users.keys().copied().collect();
                        drop(outstanding);
                        self.deliver_cancel(&users, &command.id, &id, command.expires);
                        self.report(&command.id, ResultState::Done, "đã hủy");
                    }
                    None => {
                        drop(outstanding);
                        self.report(&command.id, ResultState::Ignored, "không có gì để hủy");
                    }
                }
            }
            Action::Message { title, body, ack } => {
                let sessions = relay::sessions(&self.paths.run_user);
                let args = json!({"title": title, "body": body, "ack": ack});
                self.deliver(&sessions, &command.id, "message", args, &admin_name, command.expires);
                self.wait_for(Pending::new(&command.id, Purpose::Message { ack }, &sessions, command.expires));
            }
            Action::Countdown { ending, warn_seconds } => {
                let sessions = relay::sessions(&self.paths.run_user);
                if sessions.is_empty() {
                    // Nobody to warn: the action now.
                    return self.finish(Pending::new(&command.id, Purpose::Countdown { ending }, &sessions, 0));
                }
                let args = json!({"action": ending.as_str(), "seconds": warn_seconds});
                self.deliver(&sessions, &command.id, "countdown", args, &admin_name, command.expires);
                let deadline = clock::unix_now() + i64::from(warn_seconds) + 5;
                self.wait_for(Pending::new(&command.id, Purpose::Countdown { ending }, &sessions, deadline));
            }
            Action::RemoteHelp { admin_host, port, mode, admin_name: viewer, psk } => {
                let Some(uid) = relay::active_uid(&self.paths.sessions) else {
                    return self.report(&command.id, ResultState::Failed, "không có ai ở máy");
                };
                let sessions: Vec<_> = relay::sessions(&self.paths.run_user).into_iter().filter(|session| session.uid == uid).collect();
                let Some(session) = sessions.first() else {
                    return self.report(&command.id, ResultState::Failed, "phần trong phiên của người dùng chưa chạy");
                };
                let key = current.as_ref().ok_or_else(|| "no policy yet".to_string()).and_then(|current| current.remote_help_key(&psk));
                let (identity, key) = match key {
                    Ok(pair) => pair,
                    Err(error) => return self.report(&command.id, ResultState::Failed, &format!("không mở được khóa hỗ trợ từ xa: {error}")),
                };
                // The key goes only into an inbox that nobody else can read.
                if self.private_group(uid).is_none() {
                    let detail = format!("{} không có nhóm riêng: khóa hỗ trợ từ xa không được để nơi người khác đọc được", session.user);
                    return self.report(&command.id, ResultState::Failed, &detail);
                }
                let args = json!({"admin_host": admin_host.to_string(), "port": port, "mode": mode.as_str(), "admin_name": viewer,
                                  "psk_identity": identity, "psk_key": key});
                self.deliver(&sessions, &command.id, "remote_help", args, &admin_name, command.expires);
                self.wait_for(Pending::new(&command.id, Purpose::RemoteHelp, &sessions, command.expires));
            }
        }
    }

    fn deliver(&self, sessions: &[relay::UserSession], id: &str, action: &str, args: Value, admin_name: &str, expires: i64) {
        let entry = InboxEntry { id: id.to_string(), action: action.to_string(), args, admin_name: admin_name.to_string(), expires };
        for session in sessions {
            let group = self.private_group(session.uid);
            if let Err(error) = relay::deliver(&self.paths.inbox, session.uid, group, &entry) {
                log!("cannot deliver {id} to {}: {error}", session.user);
            }
        }
    }

    /// Tells the session parts to close the prompt of `target`.
    fn deliver_cancel(&self, uids: &[u32], id: &str, target: &str, expires: i64) {
        let entry = InboxEntry { id: id.to_string(), action: "cancel".to_string(), args: json!({"id": target}), admin_name: String::new(), expires };
        for uid in uids {
            let group = self.private_group(*uid);
            if relay::deliver(&self.paths.inbox, *uid, group, &entry).is_ok() {
                lock(&self.withdraw_later).push((*uid, id.to_string(), clock::unix_now() + CANCEL_STAYS));
            }
        }
    }

    fn wait_for(&self, pending: Pending) {
        if pending.complete() {
            self.finish(pending);
        } else {
            lock(&self.outstanding).push(pending);
        }
    }

    /// A waiting command is over: its entries leave the inboxes, its result goes out, and a countdown's action runs.
    fn finish(&self, pending: Pending) {
        for uid in pending.users.keys() {
            relay::withdraw(&self.paths.inbox, *uid, &pending.id);
        }
        if let Purpose::PowerWarning { .. } = pending.purpose {
            self.power_answers(&pending);
            return;
        }
        let (state, detail) = pending.summary();
        log!("command {}: {} ({detail})", pending.id, state_name(state));
        self.report(&pending.id, state, &detail);
        if let (Purpose::Countdown { ending }, false) = (&pending.purpose, pending.cancelled) {
            let verb = match ending {
                Ending::Restart => "reboot",
                Ending::Shutdown => "poweroff",
                // The session parts log out by themselves.
                Ending::Logout => return,
            };
            if *ending == Ending::Shutdown {
                self.arm_wake_alarm();
            }
            self.send_results(true);
            if let Err(error) = self.system.check("systemctl", &[verb], TOOL_TIMEOUT) {
                log!("systemctl {verb}: {error}");
            }
        }
    }

    /// Before any shutdown: the RTC alarm for the earliest of `power.wake` and a frozen machine's next maintenance
    /// time (PROTOCOL.md part 3 "Maintenance window").
    fn arm_wake_alarm(&self) {
        let Some(current) = self.current() else {
            return;
        };
        let unix = clock::unix_now();
        let wake = current.effective.power.as_ref().and_then(|power| power.wake.clone());
        let maintenance = self
            .freeze_in_effect(&current.effective)
            .and_then(|shared| shared.maintenance.as_ref())
            .and_then(|maintenance| shared::next_maintenance(maintenance, unix));
        if wake.is_none() && maintenance.is_none() {
            return;
        }
        let mut managed = lock(&self.managed);
        match power::set_wake_alarm(&self.system, wake.as_ref(), maintenance, unix, &mut managed) {
            Ok(()) => {
                let _ = managed.save(&self.store.managed_path());
            }
            Err(error) => log!("rtcwake: {error}"),
        }
    }

    /// The answers to a scheduled shutdown's countdown: a postpone moves it, "now" from everyone brings it forward.
    fn power_answers(&self, pending: &Pending) {
        if self.current().and_then(|current| current.effective.power?.shutdown).is_none() {
            return;
        }
        let everyone_now = !pending.users.is_empty() && pending.users.keys().all(|uid| pending.answers.get(uid).is_some_and(|answer| answer.answer == "now"));
        if everyone_now {
            log!("everyone asked to shut down now");
            self.arm_wake_alarm();
            self.halt(power::Halt::Poweroff);
        }
    }

    /// Handles one session part's answer as it comes (the relay calls this).
    fn answer(&self, uid: u32, answer: relay::Answer) {
        let mut outstanding = lock(&self.outstanding);
        let Some(index) = outstanding.iter().position(|pending| pending.id == answer.id && pending.users.contains_key(&uid)) else {
            return;
        };
        let postpone = answer.answer == "postpone";
        outstanding[index].answers.insert(uid, answer);
        if let Purpose::PowerWarning { .. } = outstanding[index].purpose {
            if postpone {
                let pending = outstanding.remove(index);
                drop(outstanding);
                self.postpone(&pending);
                return;
            }
        }
        if outstanding[index].complete() {
            let pending = outstanding.remove(index);
            drop(outstanding);
            self.finish(pending);
        }
    }

    /// A user postponed the scheduled shutdown: it moves, and the other sessions' countdowns close.
    fn postpone(&self, pending: &Pending) {
        let Some(shutdown) = self.current().and_then(|current| current.effective.power?.shutdown) else {
            return;
        };
        let now = LocalTime::now();
        let mut managed = lock(&self.managed);
        if power::postpone(&shutdown, &now, &mut managed.power_day) {
            let minute = managed.power_day.as_ref().map_or(0, |day| day.minute);
            log!("the scheduled shutdown moved to {:02}:{:02}", minute / 60, minute % 60);
            let _ = managed.save(&self.store.managed_path());
        }
        drop(managed);
        for uid in pending.users.keys() {
            relay::withdraw(&self.paths.inbox, *uid, &pending.id);
        }
        let others: Vec<u32> = pending.users.keys().filter(|uid| !pending.answers.contains_key(uid)).copied().collect();
        self.deliver_cancel(&others, &format!("{}-x", pending.id), &pending.id, clock::unix_now() + 60);
    }

    fn halt(&self, halt: power::Halt) {
        self.send_results(true);
        let verb = match halt {
            power::Halt::Poweroff => "poweroff",
            power::Halt::Suspend => "suspend",
        };
        log!("scheduled {verb}");
        if let Err(error) = self.system.check("systemctl", &[verb], TOOL_TIMEOUT) {
            log!("systemctl {verb}: {error}");
        }
    }

    fn report(&self, id: &str, state: ResultState, detail: &str) {
        let result = CommandResult {
            id: id.to_string(),
            state,
            detail: crate::protocol::truncate_chars(detail, MAX_RESULT_DETAIL),
            time: LocalTime::now().iso8601(),
        };
        lock(&self.results).queue.push(result);
    }

    fn report_outcome(&self, id: &str, outcome: Result<String, String>) {
        match outcome {
            Ok(detail) => self.report(id, ResultState::Done, &detail),
            Err(error) => self.report(id, ResultState::Failed, &error),
        }
    }

    /// Sends the results waiting; `now` ignores the pause after a failure (before a shutdown).
    pub fn send_results(&self, now: bool) {
        let queue = {
            let mut results = lock(&self.results);
            if results.queue.is_empty() || (!now && results.next_try.is_some_and(|at| Instant::now() < at)) {
                return;
            }
            std::mem::take(&mut results.queue)
        };
        let Some(admin) = self.current().and_then(|current| current.admin()) else {
            lock(&self.results).queue.splice(0..0, queue);
            return;
        };
        let mut unsent = Vec::new();
        let mut failed = None;
        for result in queue {
            if failed.is_some() {
                unsent.push(result);
                continue;
            }
            match admin.result(&serde_json::to_vec(&result).unwrap_or_default()) {
                Ok(()) => {}
                Err(error) => {
                    if error == FetchError::Gone {
                        self.gone();
                    }
                    failed = Some(error.to_string());
                    unsent.push(result);
                }
            }
        }
        let mut results = lock(&self.results);
        results.queue.splice(0..0, unsent);
        results.next_try = failed.as_ref().map(|_| Instant::now() + RESULT_RETRY);
        drop(results);
        let mut logs = lock(&self.logs);
        match failed {
            Some(error) => logs.results.log(&format!("results: {error}")),
            None => logs.results.clear("results go out again"),
        }
    }

    /// Every 2 s: the session parts' answers and the help requests, the commands that are over, the results.
    fn relay_loop(self: Arc<Self>) {
        loop {
            thread::sleep(RELAY_EVERY);
            for item in relay::read_outboxes(&self.paths.run_user) {
                match item {
                    Outgoing::Answer { uid, answer, path } => {
                        relay::remove_from_outbox(&self.paths.run_user, uid, &path);
                        self.answer(uid, answer);
                    }
                    Outgoing::Help { uid, note, time, path } => {
                        if self.send_help(uid, &note, time) {
                            relay::remove_from_outbox(&self.paths.run_user, uid, &path);
                        }
                    }
                }
            }
            let now = clock::unix_now();
            let waiting = !lock(&self.outstanding).is_empty();
            let alive: Vec<u32> = if waiting { relay::sessions(&self.paths.run_user).iter().map(|session| session.uid).collect() } else { Vec::new() };
            let over: Vec<Pending> = {
                let mut outstanding = lock(&self.outstanding);
                // A user who logged out answers nothing more.
                for pending in outstanding.iter_mut() {
                    pending.users.retain(|uid, _| alive.contains(uid) || pending.answers.contains_key(uid));
                }
                let (over, waiting): (Vec<Pending>, Vec<Pending>) = std::mem::take(&mut *outstanding).into_iter().partition(|pending| pending.complete() || now >= pending.deadline);
                *outstanding = waiting;
                over
            };
            for pending in over {
                self.finish(pending);
            }
            lock(&self.withdraw_later).retain(|(uid, id, at)| {
                if now >= *at {
                    relay::withdraw(&self.paths.inbox, *uid, id);
                    false
                } else {
                    true
                }
            });
            self.send_results(false);
        }
    }

    /// Sends a help request from the window; whether the admin took it. Its answer names the ticket made: another
    /// tickets version fetches the tickets, so that the window shows the new one.
    fn send_help(&self, uid: u32, note: &str, time: i64) -> bool {
        let Some(current) = self.current() else {
            return false;
        };
        let Some(admin) = current.admin() else {
            return false;
        };
        let request = HelpRequest {
            user: status::login_name(uid).unwrap_or_else(|| uid.to_string()),
            note: crate::protocol::truncate_chars(note, MAX_HELP_NOTE),
            time: LocalTime::from_unix(time).iso8601(),
        };
        let outcome = admin.help(&serde_json::to_vec(&request).unwrap_or_default());
        let version = match outcome {
            Ok(answer) => {
                lock(&self.logs).help.clear("");
                log!("help request from {} sent{}", request.user, answer["ticket"].as_str().map(|id| format!(": ticket {id}")).unwrap_or_default());
                answer["tickets"].as_u64()
            }
            Err(error) => {
                if error == FetchError::Gone {
                    self.gone();
                }
                lock(&self.logs).help.log(&format!("help request: {error}"));
                return false;
            }
        };
        if version.is_some_and(|version| version != *lock(&self.tickets_version)) {
            self.fetch_tickets(&current);
        }
        true
    }

    /// Every 30 s: the block hours, a `usb_unlock` that ended, the power schedule, and a frozen machine's maintenance
    /// window.
    fn scheduler_loop(self: Arc<Self>) {
        let mut last_check = clock::unix_now();
        loop {
            thread::sleep(SCHEDULE_EVERY);
            let Some(current) = self.current() else {
                continue;
            };
            let now = LocalTime::now();
            let unix = clock::unix_now();
            let effective = &current.effective;
            let mut managed = lock(&self.managed);
            let before = managed.clone();
            if effective.browser.as_ref().is_some_and(|browser| browser.block_hours.is_some()) {
                if let Err(error) = browser::block(&self.system, effective.browser.as_ref(), &mut managed, &now) {
                    log!("browser block: {error}");
                }
            }
            if managed.usb_unlock_until.is_some_and(|until| unix >= until) {
                log!("usb_unlock ended");
                if let Err(error) = usb::apply(&self.system, effective.usb.as_ref(), &mut managed, unix) {
                    log!("usb: {error}");
                }
            }
            let mut halt = None;
            if let Some(power_section) = &effective.power {
                if let Some(shutdown) = &power_section.shutdown {
                    let laptop = power::is_laptop(&self.system.root);
                    match power::step(shutdown, &now, unix, last_check, &mut managed.power_day, laptop) {
                        power::Step::Nothing => {}
                        power::Step::Warn { minute, seconds, postpones_left, postpone_minutes } => {
                            let sessions = relay::sessions(&self.paths.run_user);
                            if !sessions.is_empty() {
                                let id = format!("power-{}-{:04}", now.date().replace('-', ""), minute);
                                let halt_action = if laptop && shutdown.laptops == crate::settings::Laptops::Suspend { "suspend" } else { "shutdown" };
                                let args = json!({"action": halt_action, "seconds": seconds, "postpones_left": postpones_left, "postpone_minutes": postpone_minutes});
                                drop(managed);
                                self.deliver(&sessions, &id, "countdown", args, &current.config.admin_name, unix + i64::from(seconds));
                                lock(&self.outstanding).push(Pending::new(&id, Purpose::PowerWarning { minute }, &sessions, unix + i64::from(seconds)));
                                managed = lock(&self.managed);
                            }
                        }
                        power::Step::Halt(kind) => halt = Some(kind),
                    }
                }
            }
            if *managed != before {
                let _ = managed.save(&self.store.managed_path());
            }
            drop(managed);
            last_check = unix;
            if let Some(kind) = halt {
                if kind == power::Halt::Poweroff {
                    self.arm_wake_alarm();
                }
                self.halt(kind);
            }
            if self.frozen {
                self.maintenance_step(effective, &now, unix);
            }
        }
    }

    /// On a frozen machine: the maintenance window. Nobody at the screen at the time: a restart into the maintenance
    /// entry; someone there: tried again every 15 minutes, then the day is skipped.
    fn maintenance_step(&self, effective: &Effective, now: &LocalTime, unix: i64) {
        let Some(maintenance) = self.freeze_in_effect(effective).and_then(|shared| shared.maintenance.clone()) else {
            return;
        };
        let record = MaintenanceRecord::load(&self.store.maintenance_path());
        let someone = relay::seat_user(&self.paths.sessions).is_some();
        let step = shared::step(&maintenance, now, unix, record.done(), someone, &mut lock(&self.maintenance_day));
        match step {
            shared::Step::Nothing => {}
            shared::Step::Skip => {
                log!("maintenance window skipped: someone used the machine all through it");
                self.record_maintenance(&MaintenanceRecord { result: MAINTENANCE_SKIPPED.to_string(), ..record });
            }
            shared::Step::Restart => self.restart_into_maintenance(record),
        }
    }

    /// Writes maintenance.json on a frozen machine: in the overlay for this boot, and on the disk.
    fn record_maintenance(&self, record: &MaintenanceRecord) {
        let text = record.text();
        let path = self.store.maintenance_path();
        if let Err(error) = store::write_atomic(&path, text.as_bytes(), 0o644) {
            log!("cannot write {}: {error}", path.display());
        }
        if self.frozen {
            if let Err(error) = shared::chroot_write(&self.system, &path.to_string_lossy(), &text) {
                lock(&self.logs).maintenance.log(&error);
            }
        }
    }

    /// The frozen machine restarts into the maintenance entry: `overlayroot-chroot grub-reboot` writes GRUB's
    /// `next_entry` on the disk (a plain grub-reboot writes it only into the overlay).
    fn restart_into_maintenance(&self, record: MaintenanceRecord) {
        let disk_or_live = |absolute: &str| {
            [shared::on_disk(&self.system, absolute, true), self.system.path(absolute)]
                .iter()
                .any(|path| std::fs::read_to_string(path).is_ok_and(|text| text.contains(shared::MAINTENANCE_ENTRY)))
        };
        if self.system.commands && !disk_or_live("/boot/grub/grub.cfg") {
            log!("no maintenance entry in GRUB's menu on the disk: maintenance skipped");
            lock(&self.maintenance_day).skipped = true;
            self.record_maintenance(&MaintenanceRecord { result: "lỗi: GRUB chưa có mục bảo trì".to_string(), ..record });
            return;
        }
        let tried = MaintenanceRecord { tried: Some(LocalTime::now().iso8601()), ..record.clone() };
        self.record_maintenance(&tried);
        let output = self.system.run(shared::OVERLAYROOT_CHROOT, &["grub-reboot", shared::MAINTENANCE_ENTRY], Duration::from_secs(120));
        if self.system.commands && !disk_or_live("/boot/grub/grubenv") {
            let why = output.map(|output| output.message()).unwrap_or_else(|error| error);
            log!("overlayroot-chroot grub-reboot did not set the maintenance entry: {why}");
            lock(&self.maintenance_day).skipped = true;
            self.record_maintenance(&MaintenanceRecord { result: format!("lỗi: grub-reboot: {why}"), ..tried });
            return;
        }
        log!("maintenance window: restarting into the maintenance entry");
        self.send_results(true);
        if let Err(error) = self.system.check("systemctl", &["reboot"], TOOL_TIMEOUT) {
            log!("systemctl reboot: {error}");
        }
    }

    /// At the start of a frozen boot: a restart into the maintenance entry that did not lead to a maintenance boot
    /// (`tried` after `last`) is recorded as failed, so that the admin sees it.
    fn note_missed_maintenance(&self) {
        let record = MaintenanceRecord::load(&self.store.maintenance_path());
        let time = |value: &Option<String>| value.as_deref().and_then(clock::parse_iso8601);
        let missed = match (time(&record.tried), time(&record.last)) {
            (Some(tried), Some(last)) => tried > last,
            (Some(_), None) => true,
            _ => false,
        };
        if missed && !record.result.starts_with("lỗi") {
            log!("the last restart into maintenance did not reach the maintenance boot");
            self.record_maintenance(&MaintenanceRecord { result: "lỗi: máy không khởi động vào chế độ bảo trì".to_string(), ..record });
        }
    }

    /// The maintenance boot (PROTOCOL.md part 3 "Maintenance window"): nobody logs in (/run/nologin), a time limit, the
    /// policy fetched and the system sections applied on the disk, the updates and apps, maintenance.json, then a
    /// restart into the frozen system. When the policy no longer freezes the machine, the round put the freeze back:
    /// no restart.
    fn maintenance_loop(self: Arc<Self>) {
        let started = LocalTime::now().iso8601();
        log!("maintenance boot: nobody logs in until it is over");
        if let Err(error) = std::fs::write(self.system.path(shared::NOLOGIN), shared::NOLOGIN_TEXT) {
            log!("cannot write {}: {error}", shared::NOLOGIN);
        }
        self.maintenance_running.store(true, Ordering::SeqCst);
        let previous = MaintenanceRecord::load(&self.store.maintenance_path());
        self.record_maintenance(&MaintenanceRecord { last: Some(started.clone()), finished: None, result: "đang bảo trì".to_string(), tried: previous.tried.clone() });
        {
            let daemon = Arc::clone(&self);
            let started = started.clone();
            let boot = self.boot_time.unwrap_or_else(clock::unix_now);
            thread::spawn(move || daemon.maintenance_limit(boot, started));
        }
        let waited = Instant::now();
        while self.good_rounds.load(Ordering::SeqCst) == 0 && waited.elapsed() < MAINTENANCE_WAITS_FOR_ADMIN {
            thread::sleep(Duration::from_secs(5));
        }
        let _round = lock(&self.update_lock);
        let Some(current) = self.current() else {
            log!("maintenance boot without a pairing: nothing to do");
            return self.end_maintenance_without_restart(&started, "không có thiết lập");
        };
        if self.freeze_in_effect(&current.effective).is_none() {
            log!("the policy no longer freezes this machine: the freeze was put back; no restart");
            return self.end_maintenance_without_restart(&started, "đã thôi đóng băng");
        }
        drop(_round);
        let mut parts = Vec::new();
        let mut command = std::process::Command::new("dpkg");
        command.args(["--configure", "-a", "--force-confdef", "--force-confold"]).env("DEBIAN_FRONTEND", "noninteractive").env("LC_ALL", "C");
        if self.system.commands {
            if let Ok(output) = crate::process::run_command(command, UPDATE_TIMEOUT) {
                if !output.success() {
                    log!("dpkg --configure -a: {}", output.message());
                }
            }
        }
        match self.update_with_snapshot(&current.effective) {
            Ok(detail) => parts.push(format!("cập nhật: {detail}")),
            Err(error) => parts.push(format!("lỗi cập nhật: {error}")),
        }
        if current.effective.apps.is_some() {
            match lock(&self.apps_outcome).clone() {
                Some(Ok(())) => parts.push("ứng dụng: xong".to_string()),
                Some(Err(error)) => parts.push(format!("ứng dụng: {error}")),
                None => {}
            }
        }
        if !self.maintenance_running.swap(false, Ordering::SeqCst) {
            return; // the time limit came first
        }
        let result: String = parts.join("; ").chars().take(200).collect();
        log!("maintenance done: {result}");
        self.record_maintenance(&MaintenanceRecord { last: Some(started), finished: Some(LocalTime::now().iso8601()), result, tried: previous.tried });
        self.send_results(true);
        if let Err(error) = self.system.check("systemctl", &["reboot"], TOOL_TIMEOUT) {
            log!("systemctl reboot: {error}");
        }
    }

    fn end_maintenance_without_restart(&self, started: &str, result: &str) {
        self.maintenance_running.store(false, Ordering::SeqCst);
        let _ = std::fs::remove_file(self.system.path(shared::NOLOGIN));
        let previous = MaintenanceRecord::load(&self.store.maintenance_path());
        self.record_maintenance(&MaintenanceRecord {
            last: Some(started.to_string()),
            finished: Some(LocalTime::now().iso8601()),
            result: result.to_string(),
            tried: previous.tried,
        });
    }

    /// The window's `max_minutes`: from the current settings, which the first round of the maintenance boot brings;
    /// before that from the policy on the disk, which may be older than the one that started the maintenance (a frozen
    /// machine stores newer policies only in its overlay).
    fn maintenance_minutes(&self) -> u32 {
        let from = |effective: Effective| effective.shared.and_then(|shared| shared.maintenance).map(|maintenance| maintenance.max_minutes);
        self.current()
            .and_then(|current| from(current.effective))
            .or_else(|| {
                let config = AgentConfig::load(&self.paths.config).ok().flatten()?;
                from(self.store.load()?.1.effective(&config.machine_id))
            })
            .unwrap_or(60)
    }

    /// The maintenance boot's time limit: `max_minutes` after the boot (`boot`, Unix time) it restarts whatever still
    /// runs.
    fn maintenance_limit(&self, boot: i64, started: String) {
        let mut announced = None;
        loop {
            if !self.maintenance_running.load(Ordering::SeqCst) {
                return;
            }
            let deadline = boot + i64::from(self.maintenance_minutes()) * 60;
            if announced != Some(deadline) {
                let at = LocalTime::from_unix(deadline);
                log!("the maintenance boot ends by {:02}:{:02} at the latest", at.hour, at.minute);
                announced = Some(deadline);
            }
            if clock::unix_now() >= deadline {
                break;
            }
            thread::sleep(Duration::from_secs(10));
        }
        if !self.maintenance_running.swap(false, Ordering::SeqCst) {
            return;
        }
        log!("the maintenance window's time is over: restarting");
        let previous = MaintenanceRecord::load(&self.store.maintenance_path());
        self.record_maintenance(&MaintenanceRecord {
            last: Some(started),
            finished: Some(LocalTime::now().iso8601()),
            result: "hết giờ bảo trì: khởi động lại khi chưa xong".to_string(),
            tried: previous.tried,
        });
        let _ = self.system.check("systemctl", &["reboot"], TOOL_TIMEOUT);
    }

    /// The `update` action with `snapshots.before_update`: a Timeshift snapshot first; when it fails, the update still
    /// runs and the result says why there is no snapshot.
    fn update_with_snapshot(&self, effective: &Effective) -> Result<String, String> {
        let mut notes = Vec::new();
        if effective.snapshots.as_ref().is_some_and(|snapshots| snapshots.before_update) && !self.frozen {
            match snapshots::create(&self.system) {
                Ok(()) => notes.push("đã chụp bản lưu hệ thống".to_string()),
                Err(error) => notes.push(format!("không chụp được bản lưu hệ thống: {error}")),
            }
        }
        let with_notes = |text: String| if notes.is_empty() { text } else { format!("{}; {text}", notes.join("; ")) };
        let outcome = self.update_system();
        // The next check-in shows the updates as they are now, not as the last collection saw them.
        *lock(&self.health) = None;
        match outcome {
            Ok(detail) => Ok(with_notes(detail)),
            Err(error) => Err(with_notes(error)),
        }
    }

    /// The `update` action: the CaramOS update as the daily OTA check runs it, then apt's security updates.
    fn update_system(&self) -> Result<String, String> {
        let mut ran = Vec::new();
        if self.system.has_any(&["/usr/bin/caramos-ota"]) {
            match self.system.check("caramos-ota", &["--check"], UPDATE_TIMEOUT) {
                Ok(_) => ran.push("caramos-ota --check: ok".to_string()),
                Err(error) => ran.push(format!("caramos-ota --check: {error}")),
            }
        }
        if !self.system.commands {
            ran.push("no security updates".to_string());
            return Ok(ran.join("; "));
        }
        let apt = |args: &[&str]| -> Result<String, String> {
            let mut command = std::process::Command::new("apt-get");
            command.args(args).env("LC_ALL", "C").env("DEBIAN_FRONTEND", "noninteractive");
            let output = crate::process::run_command(command, UPDATE_TIMEOUT).map_err(|error| format!("apt-get: {error}"))?;
            if output.success() {
                Ok(output.stdout)
            } else {
                Err(format!("apt-get {}: {}", args.last().unwrap_or(&""), output.message()))
            }
        };
        apt(&["-o", "DPkg::Lock::Timeout=600", "update"])?;
        let simulation = apt(&["-s", "-o", "Debug::NoLocking=1", "upgrade"])?;
        let packages = security_packages(&simulation);
        if packages.is_empty() {
            ran.push("no security updates".to_string());
        } else {
            let mut args = vec!["-y", "-o", "DPkg::Lock::Timeout=600", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold", "install", "--only-upgrade"];
            args.extend(packages.iter().map(String::as_str));
            apt(&args)?;
            ran.push(format!("{} security updates installed", packages.len()));
        }
        Ok(ran.join("; "))
    }
}

/// The packages an `-security` suite offers, from `apt-get -s upgrade`.
pub fn security_packages(simulation: &str) -> Vec<String> {
    simulation
        .lines()
        .filter(|line| line.starts_with("Inst ") && line.contains("-security"))
        .filter_map(|line| line.split_whitespace().nth(1).map(str::to_string))
        .collect()
}

fn state_name(state: ResultState) -> &'static str {
    match state {
        ResultState::Done => "done",
        ResultState::Failed => "failed",
        ResultState::Refused => "refused",
        ResultState::Expired => "expired",
        ResultState::Ignored => "ignored",
    }
}

fn action_name(action: &Action) -> &'static str {
    match action {
        Action::Sync => "sync",
        Action::Inventory => "inventory",
        Action::Lock => "lock",
        Action::Message { .. } => "message",
        Action::Countdown { ending, .. } => ending.as_str(),
        Action::Cancel { .. } => "cancel",
        Action::Update => "update",
        Action::RemoteHelp { .. } => "remote_help",
        Action::UsbUnlock { .. } => "usb_unlock",
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timing() {
        assert_eq!(wait_after(0), INTERVAL);
        for failures in 1..=RETRIES {
            assert_eq!(wait_after(failures), RETRY);
        }
        assert_eq!(wait_after(RETRIES + 1), INTERVAL);
        assert_eq!(wait_after(u32::MAX), INTERVAL);
    }

    #[test]
    fn security_updates_to_install() {
        let simulation = "Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n\
                          Inst firefox [146.0] (147.0 linuxmint:22/zena [amd64])\n";
        assert_eq!(security_packages(simulation), ["libc6"]);
    }

    #[test]
    fn failures_that_move_the_admin() {
        assert!(Failure::Fetch(FetchError::Unreachable("x".into())).admin_may_have_moved());
        assert!(!Failure::Fetch(FetchError::Gone).admin_may_have_moved(), "a 410 is the admin's claim, not a move");
        assert!(!Failure::Fetch(FetchError::Gone).admin_proven(), "and proves nothing");
        assert!(!Failure::BadNotice("x".into()).admin_proven());
        assert!(Failure::Refused("x".into()).admin_proven());
        assert!(Failure::File("a".into(), FetchError::Status(404)).admin_proven());
    }
}
