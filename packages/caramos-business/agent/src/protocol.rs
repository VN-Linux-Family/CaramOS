//! What travels between the agent and the admin, and where the employee machine keeps things (PROTOCOL.md,
//! "Network" and "Files", and part 2).

use serde::{Deserialize, Serialize};

pub const DISCOVERY_PORT: u16 = 47021;
pub const HTTP_PORT: u16 = 47022;
/// Every HTTP path starts with it.
pub const API: &str = "/caramos-business/v1";
/// The first word of every discovery datagram.
pub const MAGIC: &str = "CARAMOS-BUSINESS/1";
/// Discovery datagrams are at most this long; anything longer is ignored.
pub const MAX_DATAGRAM: usize = 2048;
/// Request bodies (the check-in) are at most this long.
pub const MAX_REQUEST_BODY: usize = 64 * 1024;
/// USER_STATUS `detail` is at most this many characters.
pub const MAX_DETAIL_CHARS: usize = 200;
/// A command result's `detail` is at most this many characters.
pub const MAX_RESULT_DETAIL: usize = 300;
/// A help request's `note` is at most this many characters.
pub const MAX_HELP_NOTE: usize = 300;

/// `admin` or `employee`, one word and a newline; no file: no role yet.
pub const ROLE_FILE: &str = "/etc/caramos-business/role";
/// Written by the root helper at pairing, 0600 root.
pub const AGENT_CONFIG: &str = "/etc/caramos-business/agent.json";
/// The machine box key, X25519, raw 32 bytes, 0600 root; the helper makes it at pairing.
pub const AGENT_BOX_KEY: &str = "/etc/caramos-business/agent-box.key";
/// The daemon's commands for each user's session part, `<uid>/<id>.json`: root's, so that a user cannot point the
/// daemon's writes elsewhere (PROTOCOL.md part 2, "Relay between daemon and session part").
pub const INBOX_ROOT: &str = "/run/caramos-business/inbox";
/// In `$XDG_RUNTIME_DIR/caramos-business`: the session part's answers (`<id>.json`) and the window's help requests
/// (`help-<unix>.json`), which the daemon sends and removes.
pub const OUTBOX: &str = "outbox";
/// The last good policy (policy.json) and its files (files/<sha256>.<type>).
pub const AGENT_STATE: &str = "/var/lib/caramos-business/agent";
/// The service's unit, which the agent disables when the company removed the machine.
pub const AGENT_UNIT: &str = "caramos-business-agent.service";
/// Holds each logged-in user's $XDG_RUNTIME_DIR.
pub const RUN_USER: &str = "/run/user";
/// The session part's folder in $XDG_RUNTIME_DIR, holding status.json.
pub const RUNTIME_SUBDIR: &str = "caramos-business";
pub const STATUS_FILE: &str = "status.json";

/// `GET /policy`: the policy as a JSON text, and the base64 Ed25519 signature of exactly its UTF-8 bytes.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct SignedPolicy {
    pub policy: String,
    pub signature: String,
}

/// What a removed machine gets from `GET /policy` instead (PROTOCOL.md part 3 "Removal from the company"): the
/// removal notice as a JSON text `{"kind": "removed", "machine_id", "admin", "time"}`, signed like a command.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct SignedNotice {
    pub notice: String,
    pub signature: String,
}

/// `GET /policy`'s answer from 0.3: the signed policy, or a removed machine's notice (no `policy` key).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PolicyAnswer {
    Policy(SignedPolicy),
    Notice(SignedNotice),
}

impl PolicyAnswer {
    /// The answer's JSON: a `policy` key makes it a policy, else a `notice` key a notice.
    pub fn parse(body: &[u8]) -> Result<PolicyAnswer, String> {
        let value: serde_json::Value = serde_json::from_slice(body).map_err(|error| error.to_string())?;
        if value.get("policy").is_some() {
            serde_json::from_value(value).map(PolicyAnswer::Policy).map_err(|error| error.to_string())
        } else if value.get("notice").is_some() {
            serde_json::from_value(value).map(PolicyAnswer::Notice).map_err(|error| error.to_string())
        } else {
            Err("neither a policy nor a removal notice".to_string())
        }
    }
}

/// `GET /tickets` (PROTOCOL.md part 3 "Helpdesk tickets"): the machine's tickets as a JSON text, signed.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct SignedTickets {
    pub tickets: String,
    pub signature: String,
}

/// MACHINE: how the admin sees this computer.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct Machine {
    pub name: String,
    /// The address of the route toward the admin.
    pub ip: String,
    /// The network card of that route.
    pub mac: String,
    /// "cinnamon", "xfce" or "other".
    pub edition: String,
    /// The CaramOS version, or empty.
    pub version: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum WallpaperState {
    Applied,
    Failed,
    Off,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum FoldersState {
    Server,
    Local,
    Failed,
    Off,
}

/// USER_STATUS: what the session part did for its user, written after each round and sent with the check-in.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UserStatus {
    pub user: String,
    pub wallpaper: WallpaperState,
    pub folders: FoldersState,
    pub detail: String,
    /// ISO 8601.
    pub time: String,
}

/// `POST /checkin`: part 1's body without the token (requests are authenticated now), plus health and capabilities.
#[derive(Debug, Serialize)]
pub struct CheckIn<'a> {
    pub machine_id: &'a str,
    pub machine: &'a Machine,
    pub policy_serial: Option<u64>,
    pub users: &'a [UserStatus],
    pub health: &'a serde_json::Value,
    pub capabilities: &'a [&'a str],
}

/// What the agent can do, for the check-in: the sections it applies, commands and inventory (part 2), and from 0.3
/// the licence keys of the inventory, shared machines, snapshots and tickets (PROTOCOL.md part 3 "Capabilities").
pub const CAPABILITIES: [&str; 17] = [
    "wallpaper",
    "folders",
    "shares",
    "browser",
    "printers",
    "power",
    "apps",
    "usb",
    "screen_lock",
    "firewall",
    "inventory",
    "wifi",
    "commands",
    "licence-report",
    "shared",
    "snapshots",
    "tickets",
];

/// The signed envelope of a policy or a command: the JSON text, and the base64 Ed25519 signature of its bytes.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Envelope {
    pub command: String,
    pub signature: String,
}

/// `GET /wait`'s answer: the admin's policy serial, the commands for this machine after `after`, oldest first, and
/// from 0.3 the version of the machine's tickets (0 without tickets).
#[derive(Debug, Clone, Deserialize)]
pub struct WaitAnswer {
    pub serial: u64,
    #[serde(default)]
    pub commands: Vec<Envelope>,
    #[serde(default)]
    pub tickets: u64,
}

/// A command's outcome on this machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResultState {
    Done,
    Failed,
    Refused,
    Expired,
    Ignored,
}

/// `POST /result`: one per command per machine.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CommandResult {
    pub id: String,
    pub state: ResultState,
    pub detail: String,
    pub time: String,
}

/// `POST /help`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct HelpRequest {
    pub user: String,
    pub note: String,
    pub time: String,
}

/// The datagram the agent broadcasts to UDP 47021.
pub fn discover_datagram() -> Vec<u8> {
    format!("{MAGIC} DISCOVER").into_bytes()
}

/// An admin's answer to the discovery broadcast.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Here {
    pub name: String,
    pub port: u16,
    /// First 16 hex digits of sha256(admin key).
    pub fingerprint: String,
    pub pairing: bool,
}

/// Parses `CARAMOS-BUSINESS/1 HERE <json>`. Anything else, or anything invalid in it, is None: ignored.
pub fn parse_here(datagram: &[u8]) -> Option<Here> {
    #[derive(Deserialize)]
    struct Fields {
        name: String,
        port: u64,
        fingerprint: String,
        pairing: bool,
    }

    if datagram.len() > MAX_DATAGRAM {
        return None;
    }
    let text = std::str::from_utf8(datagram).ok()?;
    let json = text.strip_prefix(MAGIC)?.strip_prefix(" HERE ")?;
    let fields: Fields = serde_json::from_str(json).ok()?;
    let port = u16::try_from(fields.port).ok().filter(|port| *port > 1024)?;
    let name_ok = !fields.name.is_empty()
        && fields.name.chars().count() <= 253
        && !fields.name.chars().any(char::is_control);
    if !name_ok || !is_fingerprint(&fields.fingerprint) {
        return None;
    }
    Some(Here { name: fields.name, port, fingerprint: fields.fingerprint, pairing: fields.pairing })
}

/// 16 lowercase hex digits.
pub fn is_fingerprint(text: &str) -> bool {
    text.len() == 16 && text.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

/// `text` cut to at most `max` characters (not bytes, so never inside a character).
pub fn truncate_chars(text: &str, max: usize) -> String {
    text.chars().take(max).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn discover_datagram_text() {
        assert_eq!(discover_datagram(), b"CARAMOS-BUSINESS/1 DISCOVER");
    }

    #[test]
    fn here_datagram() {
        let datagram =
            br#"CARAMOS-BUSINESS/1 HERE {"name": "may-quan-ly", "port": 47022, "fingerprint": "56475aa75463474c", "pairing": false}"#;
        let here = parse_here(datagram).unwrap();
        assert_eq!(
            here,
            Here {
                name: "may-quan-ly".into(),
                port: 47022,
                fingerprint: "56475aa75463474c".into(),
                pairing: false
            }
        );
        // Later formats may add keys.
        let extra = br#"CARAMOS-BUSINESS/1 HERE {"name": "a", "port": 47022, "fingerprint": "56475aa75463474c", "pairing": true, "x": 1}"#;
        assert!(parse_here(extra).unwrap().pairing);
    }

    #[test]
    fn other_datagrams_are_ignored() {
        let good = r#"{"name": "a", "port": 47022, "fingerprint": "56475aa75463474c", "pairing": false}"#;
        let cases: Vec<Vec<u8>> = vec![
            b"CARAMOS-BUSINESS/1 DISCOVER".to_vec(),
            format!("CARAMOS-LAB/1 HERE {good}").into_bytes(),
            format!("CARAMOS-BUSINESS/2 HERE {good}").into_bytes(),
            format!("CARAMOS-BUSINESS/1 HELLO {good}").into_bytes(),
            b"CARAMOS-BUSINESS/1 HERE not json".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"a\", \"port\": 47022, \"fingerprint\": \"56475AA75463474C\", \"pairing\": false}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"a\", \"port\": 47022, \"fingerprint\": \"56475aa7\", \"pairing\": false}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"a\", \"port\": 80, \"fingerprint\": \"56475aa75463474c\", \"pairing\": false}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"a\", \"port\": 70000, \"fingerprint\": \"56475aa75463474c\", \"pairing\": false}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"\", \"port\": 47022, \"fingerprint\": \"56475aa75463474c\", \"pairing\": false}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE {\"name\": \"a\", \"port\": 47022, \"fingerprint\": \"56475aa75463474c\"}".to_vec(),
            b"CARAMOS-BUSINESS/1 HERE [1]".to_vec(),
            vec![0xff, 0xfe, b' ', b'x'],
        ];
        for case in &cases {
            assert_eq!(parse_here(case), None, "{}", String::from_utf8_lossy(case));
        }
        let mut long = format!("CARAMOS-BUSINESS/1 HERE {good}").into_bytes();
        long.extend(std::iter::repeat_n(b' ', MAX_DATAGRAM));
        assert_eq!(parse_here(&long), None);
    }

    #[test]
    fn policy_or_notice() {
        let policy = PolicyAnswer::parse(br#"{"policy": "{}", "signature": "c2ln"}"#).unwrap();
        assert!(matches!(policy, PolicyAnswer::Policy(SignedPolicy { ref policy, .. }) if policy == "{}"));
        let notice = PolicyAnswer::parse(br#"{"notice": "{}", "signature": "c2ln"}"#).unwrap();
        assert!(matches!(notice, PolicyAnswer::Notice(_)));
        assert!(PolicyAnswer::parse(br#"{"signature": "c2ln"}"#).is_err());
        assert!(PolicyAnswer::parse(br#"{"notice": 1, "signature": "c2ln"}"#).is_err());
        let wait: WaitAnswer = serde_json::from_str(r#"{"serial": 4, "commands": []}"#).unwrap();
        assert_eq!(wait.tickets, 0, "a missing version is 0");
    }

    #[test]
    fn user_status_json() {
        let status = UserStatus {
            user: "lan".into(),
            wallpaper: WallpaperState::Applied,
            folders: FoldersState::Local,
            detail: String::new(),
            time: "2026-11-21T09:00:00+07:00".into(),
        };
        let json = serde_json::to_value(&status).unwrap();
        assert_eq!(json["wallpaper"], "applied");
        assert_eq!(json["folders"], "local");
        assert_eq!(serde_json::from_value::<UserStatus>(json).unwrap(), status);
    }
}
