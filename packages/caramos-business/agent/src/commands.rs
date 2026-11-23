//! Signed commands (PROTOCOL.md part 2 "Signed commands"): the checks before a command runs, its fixed actions, and
//! the record of the last seq and the ids run (`/var/lib/caramos-business/agent/commands.json`).
//!
//! There is no shell and no arbitrary command: an action outside the list, or with arguments outside their limits,
//! is refused even when the admin's key signed it.

use std::net::Ipv4Addr;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::clock;
use crate::crypto;
use crate::protocol::{Envelope, ResultState};
use crate::store;

/// How many ids run are remembered.
const MAX_DONE: usize = 1000;

/// The actions that act on the people at the machine (restart, shutdown, logout, lock, message, remote help) run only
/// when issued at least this long after the current boot started: one issued earlier was meant for a machine that has
/// restarted since. A machine whose state was reset or restored from a snapshot asks `/wait` from seq 0 again, and a
/// replayed `restart` would otherwise loop at every boot until it expires. The margin covers the time the machine took
/// to go down and a small clock difference with the admin.
pub const BOOT_MARGIN: i64 = 60;

/// The detail of such a command's `expired` result.
pub const BEFORE_THIS_BOOT: &str = "trước lần khởi động này";

/// Who a command is for: exactly one of the three.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Targets {
    Machines(Vec<String>),
    Departments(Vec<String>),
    All,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Mode {
    View,
    Control,
}

impl Mode {
    pub fn as_str(self) -> &'static str {
        match self {
            Mode::View => "view",
            Mode::Control => "control",
        }
    }
}

/// What ends a countdown: logging out in the session, or the machine restarting or shutting down.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Ending {
    Logout,
    Restart,
    Shutdown,
}

impl Ending {
    pub fn as_str(self) -> &'static str {
        match self {
            Ending::Logout => "logout",
            Ending::Restart => "restart",
            Ending::Shutdown => "shutdown",
        }
    }
}

/// The fixed actions, with their checked arguments.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Action {
    Sync,
    Inventory,
    Lock,
    Message { title: String, body: String, ack: bool },
    Countdown { ending: Ending, warn_seconds: u32 },
    Cancel { id: String },
    Update,
    /// `psk` is the session's pre-shared key, sealed for this machine (PROTOCOL.md part 3 "Remote help").
    RemoteHelp { admin_host: Ipv4Addr, port: u16, mode: Mode, admin_name: String, psk: String },
    UsbUnlock { minutes: u32 },
}

impl Action {
    /// Whether the action is only for the boot it was meant for (see BOOT_MARGIN). `sync`, `inventory`, `update`,
    /// `usb_unlock` and `cancel` still run within their lifetime.
    pub fn only_this_boot(&self) -> bool {
        matches!(self, Action::Countdown { .. } | Action::Lock | Action::Message { .. } | Action::RemoteHelp { .. })
    }
}

/// A command that passed every check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Command {
    pub seq: u64,
    pub id: String,
    pub targets: Targets,
    pub action: Action,
    pub issued: i64,
    pub expires: i64,
}

/// What to do with an envelope.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Decision {
    /// Run it.
    Run(Command),
    /// Do not run it, and report this result for its id (and record its seq).
    Report { seq: u64, id: String, state: ResultState, detail: String },
    /// Nothing to run and nothing to report: a bad signature (its id cannot be trusted), or an id already run.
    Skip(String),
}

/// The command as signed, before its action is checked.
#[derive(Debug, Deserialize)]
struct Raw {
    seq: u64,
    id: String,
    targets: serde_json::Map<String, Value>,
    action: String,
    #[serde(default)]
    args: serde_json::Map<String, Value>,
    issued: String,
    expires: String,
}

/// Checks an envelope for this machine: the signature with the pinned key, that the machine is among the targets
/// (through its department in the current policy), that it has not expired, that its seq is higher than the last
/// one run, that its action and arguments are valid, and, for the actions only for one boot, that it was issued
/// after the current boot (`boot_time`, Unix seconds, when known) started.
pub fn decide(
    envelope: &Envelope,
    admin_key: &[u8; 32],
    machine_id: &str,
    department: Option<&str>,
    record: &CommandRecord,
    now: i64,
    boot_time: Option<i64>,
) -> Decision {
    if let Err(error) = crypto::verify(admin_key, envelope.command.as_bytes(), &envelope.signature) {
        return Decision::Skip(format!("a command was refused: {error}"));
    }
    let raw: Raw = match serde_json::from_str(&envelope.command) {
        Ok(raw) => raw,
        Err(error) => return Decision::Skip(format!("a signed command is not valid JSON: {error}")),
    };
    if !crate::policy::is_machine_id(&raw.id) {
        return Decision::Skip(format!("a signed command has the invalid id {:?}", raw.id));
    }
    if record.done.contains(&raw.id) {
        return Decision::Skip(format!("command {} ran already", raw.id));
    }
    let report = |state, detail: String| Decision::Report { seq: raw.seq, id: raw.id.clone(), state, detail };
    let targets = match parse_targets(&raw.targets) {
        Ok(targets) => targets,
        Err(error) => return report(ResultState::Refused, error),
    };
    let ours = match &targets {
        Targets::Machines(machines) => machines.iter().any(|id| id == machine_id),
        Targets::Departments(departments) => department.is_some_and(|ours| departments.iter().any(|id| id == ours)),
        Targets::All => true,
    };
    if !ours {
        return report(ResultState::Ignored, "this machine is not among the command's targets".to_string());
    }
    let (Some(issued), Some(expires)) = (clock::parse_iso8601(&raw.issued), clock::parse_iso8601(&raw.expires)) else {
        return report(ResultState::Refused, "issued or expires is not an ISO 8601 time".to_string());
    };
    // "expires is at most 24 h after issued" is how the admin makes commands; the agent checks only that it has not
    // passed (the shared test commands expire in 2099).
    if now > expires {
        return report(ResultState::Expired, format!("the command expired at {}", raw.expires));
    }
    if raw.seq <= record.last_seq {
        return report(ResultState::Ignored, format!("seq {} is not after the last one run, {}", raw.seq, record.last_seq));
    }
    let action = match parse_action(&raw.action, &raw.args) {
        Ok(action) => action,
        Err(error) => return report(ResultState::Refused, error),
    };
    if action.only_this_boot() && boot_time.is_some_and(|boot| issued < boot + BOOT_MARGIN) {
        return report(ResultState::Expired, BEFORE_THIS_BOOT.to_string());
    }
    Decision::Run(Command { seq: raw.seq, id: raw.id, targets, action, issued, expires })
}

fn parse_targets(targets: &serde_json::Map<String, Value>) -> Result<Targets, String> {
    let ids = |value: &Value| -> Result<Vec<String>, String> {
        let list = value.as_array().ok_or("targets must list ids")?;
        list.iter().map(|id| id.as_str().map(str::to_string).ok_or_else(|| "targets must list ids".to_string())).collect()
    };
    match (targets.len(), targets.iter().next()) {
        (1, Some((key, value))) if key == "machines" => Ok(Targets::Machines(ids(value)?)),
        (1, Some((key, value))) if key == "departments" => Ok(Targets::Departments(ids(value)?)),
        (1, Some((key, value))) if key == "all" && value.as_bool() == Some(true) => Ok(Targets::All),
        _ => Err("targets must be exactly one of machines, departments or all".to_string()),
    }
}

fn text(args: &serde_json::Map<String, Value>, key: &str, max: usize) -> Result<String, String> {
    let value = args.get(key).and_then(Value::as_str).ok_or(format!("args.{key} is missing"))?;
    if value.chars().count() > max {
        return Err(format!("args.{key} is longer than {max} characters"));
    }
    Ok(value.to_string())
}

fn number(args: &serde_json::Map<String, Value>, key: &str, low: u64, high: u64) -> Result<u64, String> {
    let value = args.get(key).and_then(Value::as_u64).ok_or(format!("args.{key} is missing"))?;
    if !(low..=high).contains(&value) {
        return Err(format!("args.{key} must be {low} to {high}"));
    }
    Ok(value)
}

/// The action and its arguments, checked against the table.
pub fn parse_action(action: &str, args: &serde_json::Map<String, Value>) -> Result<Action, String> {
    let countdown = |ending| Ok(Action::Countdown { ending, warn_seconds: number(args, "warn_seconds", 0, 900)? as u32 });
    match action {
        "sync" => Ok(Action::Sync),
        "inventory" => Ok(Action::Inventory),
        "lock" => Ok(Action::Lock),
        "update" => Ok(Action::Update),
        "message" => Ok(Action::Message {
            title: text(args, "title", 80)?,
            body: text(args, "body", 1000)?,
            ack: args.get("ack").and_then(Value::as_bool).unwrap_or(false),
        }),
        "logout" => countdown(Ending::Logout),
        "restart" => countdown(Ending::Restart),
        "shutdown" => countdown(Ending::Shutdown),
        "cancel" => {
            let id = text(args, "id", 36)?;
            if !crate::policy::is_machine_id(&id) {
                return Err("args.id is not a command id".to_string());
            }
            Ok(Action::Cancel { id })
        }
        "remote_help" => {
            let admin_host: Ipv4Addr =
                text(args, "admin_host", 15)?.parse().map_err(|_| "args.admin_host is not an IPv4 address".to_string())?;
            let mode = match text(args, "mode", 7)?.as_str() {
                "view" => Mode::View,
                "control" => Mode::Control,
                _ => return Err("args.mode must be view or control".to_string()),
            };
            Ok(Action::RemoteHelp {
                admin_host,
                port: number(args, "port", 1025, 65535)? as u16,
                mode,
                admin_name: text(args, "admin_name", 64)?,
                // A sealed {"identity", "key"}: base64 of a nonce, the JSON and the tag; far below 1000 characters.
                psk: text(args, "psk", 1000)?,
            })
        }
        "usb_unlock" => Ok(Action::UsbUnlock { minutes: number(args, "minutes", 1, 240)? as u32 }),
        other => Err(format!("{other:?} is not an action this agent runs")),
    }
}

/// `commands.json`: the last seq run and the ids run, newest last, for one pairing (its machine id).
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandRecord {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub machine_id: Option<String>,
    #[serde(default)]
    pub last_seq: u64,
    #[serde(default)]
    pub done: Vec<String>,
}

impl CommandRecord {
    pub fn load(path: &Path) -> CommandRecord {
        store::read_limited(path, 1024 * 1024)
            .ok()
            .and_then(|data| serde_json::from_slice(&data).ok())
            .unwrap_or_default()
    }

    /// Makes this the record of the pairing with `machine_id`. Another pairing's record starts again, since another
    /// admin counts its seqs from 1. Whether it changed.
    pub fn adopt(&mut self, machine_id: &str) -> bool {
        if self.machine_id.as_deref() == Some(machine_id) {
            return false;
        }
        if self.machine_id.is_some() {
            *self = CommandRecord::default();
        }
        self.machine_id = Some(machine_id.to_string());
        true
    }

    /// Records a command as handled (before it acts, so that a restart or shutdown never runs twice).
    pub fn record(&mut self, seq: u64, id: &str) {
        self.last_seq = self.last_seq.max(seq);
        if !self.done.iter().any(|done| done == id) {
            self.done.push(id.to_string());
        }
        let excess = self.done.len().saturating_sub(MAX_DONE);
        self.done.drain(..excess);
    }

    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        let data = serde_json::to_vec(self).map_err(std::io::Error::other)?;
        store::write_atomic(path, &data, 0o600)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn args(value: Value) -> serde_json::Map<String, Value> {
        value.as_object().unwrap().clone()
    }

    #[test]
    fn a_new_pairing_starts_a_new_record() {
        let mut record = CommandRecord { machine_id: None, last_seq: 41, done: vec!["a".into()] };
        // A record from before the machine id was kept is this pairing's.
        assert!(record.adopt("7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6"));
        assert_eq!(record.last_seq, 41);
        assert!(!record.adopt("7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6"));
        assert!(record.adopt("0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"));
        assert_eq!((record.last_seq, record.done.len()), (0, 0));
        assert_eq!(record.machine_id.as_deref(), Some("0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"));
    }

    #[test]
    fn action_arguments() {
        assert_eq!(parse_action("lock", &args(json!({}))), Ok(Action::Lock));
        assert!(parse_action("shell", &args(json!({"run": "id"}))).is_err());
        assert!(parse_action("message", &args(json!({"title": "x".repeat(81), "body": "", "ack": true}))).is_err());
        assert!(parse_action("message", &args(json!({"title": "t", "body": "b".repeat(1001)}))).is_err());
        assert_eq!(
            parse_action("shutdown", &args(json!({"warn_seconds": 900}))),
            Ok(Action::Countdown { ending: Ending::Shutdown, warn_seconds: 900 })
        );
        assert!(parse_action("restart", &args(json!({"warn_seconds": 901}))).is_err());
        assert!(parse_action("usb_unlock", &args(json!({"minutes": 0}))).is_err());
        assert!(parse_action("usb_unlock", &args(json!({"minutes": 240}))).is_ok());
        let help = |host: &str, port: u64, mode: &str| {
            parse_action("remote_help", &args(json!({"admin_host": host, "port": port, "mode": mode, "admin_name": "IT", "psk": "c2VhbGVk"})))
        };
        assert!(help("192.168.1.10", 5501, "control").is_ok());
        assert!(parse_action("remote_help", &args(json!({"admin_host": "192.168.1.10", "port": 5501, "mode": "view", "admin_name": "IT"}))).is_err(), "no psk");
        assert!(help("192.168.1.10", 1024, "view").is_err());
        assert!(help("may-quan-ly", 5501, "view").is_err());
        assert!(help("192.168.1.10", 5501, "admin").is_err());
        assert!(parse_action("cancel", &args(json!({"id": "00000000-0000-4000-8000-000000000041"}))).is_ok());
        assert!(parse_action("cancel", &args(json!({"id": "x"}))).is_err());
    }

    /// A command signed with a fresh key, for the boot tests.
    fn signed(action: &str, args: Value, issued: &str) -> (Envelope, [u8; 32]) {
        use ed25519_dalek::{Signer, SigningKey};
        let key = SigningKey::from_bytes(&[7u8; 32]);
        let text = json!({"seq": 9, "id": "00000000-0000-4000-8000-000000000009", "targets": {"all": true},
                          "action": action, "args": args, "issued": issued, "expires": "2099-01-01T00:00:00+07:00"})
            .to_string();
        let signature = base64::Engine::encode(&base64::engine::general_purpose::STANDARD, key.sign(text.as_bytes()).to_bytes());
        (Envelope { command: text, signature }, key.verifying_key().to_bytes())
    }

    #[test]
    fn commands_from_before_this_boot() {
        // The machine started at 2026-11-21T14:00:00+07:00 (Unix 1795244400).
        let boot = clock::parse_iso8601("2026-11-21T14:00:00+07:00");
        let now = boot.unwrap() + 3600;
        let decide_one = |action: &str, args: Value, issued: &str| {
            let (envelope, key) = signed(action, args, issued);
            decide(&envelope, &key, "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6", None, &CommandRecord::default(), now, boot)
        };
        let before = "2026-11-21T13:55:00+07:00";
        let in_margin = "2026-11-21T14:00:30+07:00";
        let after = "2026-11-21T14:05:00+07:00";
        let stale = |decision: Decision| {
            matches!(decision, Decision::Report { state: ResultState::Expired, ref detail, .. } if detail == BEFORE_THIS_BOOT)
        };
        for (action, args) in [("restart", json!({"warn_seconds": 60})), ("shutdown", json!({"warn_seconds": 0})),
                               ("logout", json!({"warn_seconds": 0})), ("lock", json!({})),
                               ("message", json!({"title": "t", "body": "", "ack": false})),
                               ("remote_help", json!({"admin_host": "10.0.0.2", "port": 5501, "mode": "view", "admin_name": "", "psk": "c2VhbGVk"}))] {
            assert!(stale(decide_one(action, args.clone(), before)), "{action} from before this boot");
            assert!(stale(decide_one(action, args.clone(), in_margin)), "{action} within the margin");
            assert!(matches!(decide_one(action, args, after), Decision::Run(_)), "{action} after this boot");
        }
        for (action, args) in [("sync", json!({})), ("inventory", json!({})), ("update", json!({})),
                               ("usb_unlock", json!({"minutes": 30})),
                               ("cancel", json!({"id": "00000000-0000-4000-8000-000000000041"}))] {
            assert!(matches!(decide_one(action, args, before), Decision::Run(_)), "{action} still runs");
        }
        // Without a known boot time nothing is held back.
        let (envelope, key) = signed("restart", json!({"warn_seconds": 0}), before);
        let unknown = decide(&envelope, &key, "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6", None, &CommandRecord::default(), now, None);
        assert!(matches!(unknown, Decision::Run(_)));
    }

    #[test]
    fn boot_time_from_proc_stat() {
        let stat = "cpu  1 2 3\nintr 5\nbtime 1795244400\nprocesses 99\n";
        assert_eq!(clock::parse_btime(stat), Some(1_795_244_400));
        assert_eq!(clock::parse_btime("cpu 1\n"), None);
        assert!(clock::boot_time().is_some_and(|boot| boot > 1_600_000_000), "this machine's boot time");
    }

    #[test]
    fn record_keeps_the_newest_ids() {
        let mut record = CommandRecord::default();
        for seq in 1..=1005u64 {
            record.record(seq, &format!("{seq:08}-0000-4000-8000-000000000000"));
        }
        assert_eq!(record.last_seq, 1005);
        assert_eq!(record.done.len(), MAX_DONE);
        assert_eq!(record.done[0], "00000006-0000-4000-8000-000000000000");
        record.record(3, "x");
        assert_eq!(record.last_seq, 1005);
    }
}
