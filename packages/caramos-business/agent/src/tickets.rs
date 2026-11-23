//! Helpdesk tickets on the employee machine (PROTOCOL.md part 3 "Helpdesk tickets"): the daemon fetches the machine's
//! signed tickets (at start, and whenever `/wait` shows another version), checks the signature with the pinned key and
//! that they are this machine's, and writes each user's own tickets to `tickets/<uid>.json`: root's with the user's
//! private group, 0640, so that only that user reads them. A user whose primary group is not their own gets no file;
//! tickets of a login name with no account here are dropped.
//!
//! A ticket whose status changed or that gained updates since the user's previous file becomes a notification in the
//! user's session (an inbox entry, daemon.rs).

use std::collections::BTreeMap;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use serde_json::{json, Value};

use crate::accounts::{self, Account};
use crate::crypto;
use crate::protocol::SignedTickets;
use crate::sections::System;
use crate::store;

/// The `version` file in the tickets folder (0600).
pub const VERSION_FILE: &str = "version";
/// A user's file is small: 50 tickets of 20 updates of 500 characters at most.
const MAX_USER_FILE: u64 = 2 * 1024 * 1024;

/// A verified ticket list.
#[derive(Debug, Clone, PartialEq)]
pub struct TicketList {
    pub version: u64,
    pub tickets: Vec<Value>,
}

/// Checks a `/tickets` answer: the signature with the pinned key, `kind`, and that it is this machine's.
pub fn verify(signed: &SignedTickets, admin_key: &[u8; 32], machine_id: &str) -> Result<TicketList, String> {
    crypto::verify(admin_key, signed.tickets.as_bytes(), &signed.signature).map_err(|error| format!("tickets refused: {error}"))?;
    let value: Value = serde_json::from_str(&signed.tickets).map_err(|error| format!("the tickets are not JSON: {error}"))?;
    if value["kind"].as_str() != Some("tickets") {
        return Err("the signed text is not a ticket list".to_string());
    }
    if value["machine_id"].as_str() != Some(machine_id) {
        return Err("the tickets are another machine's".to_string());
    }
    let version = value["version"].as_u64().ok_or("the tickets have no version")?;
    let tickets = value["tickets"].as_array().cloned().ok_or("the tickets have no list")?;
    Ok(TicketList { version, tickets: tickets.into_iter().filter(valid).collect() })
}

/// A ticket the agent can show: an object with a string id `HT-` and digits, a user, a status and a list of updates.
fn valid(ticket: &Value) -> bool {
    let id_ok = ticket["id"].as_str().is_some_and(|id| id.strip_prefix("HT-").is_some_and(|digits| (4..=12).contains(&digits.len()) && digits.bytes().all(|b| b.is_ascii_digit())));
    id_ok && ticket["user"].is_string() && ticket["status"].is_string() && (ticket["updates"].is_array() || ticket.get("updates").is_none())
}

/// Each login name's tickets, in the list's order.
pub fn by_user(tickets: &[Value]) -> BTreeMap<String, Vec<Value>> {
    let mut users: BTreeMap<String, Vec<Value>> = BTreeMap::new();
    for ticket in tickets {
        if let Some(user) = ticket["user"].as_str() {
            users.entry(user.to_string()).or_default().push(ticket.clone());
        }
    }
    users
}

/// A ticket to tell its user about.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Change {
    pub ticket: String,
    pub status: String,
    /// The newest update's text.
    pub text: String,
    /// How many updates the ticket has: the notification's id is `ticket-<id>-<count>`.
    pub count: usize,
}

impl Change {
    pub fn relay_id(&self) -> String {
        format!("ticket-{}-{}", self.ticket, self.count)
    }
}

fn updates(ticket: &Value) -> &[Value] {
    ticket["updates"].as_array().map_or(&[], Vec::as_slice)
}

/// The tickets whose status changed or that gained updates since `previous` (the user's last file). A ticket that is
/// new to the file is told about only when it already has updates (the user just asked; IT answered before the agent
/// fetched).
pub fn changes(previous: &[Value], current: &[Value]) -> Vec<Change> {
    current
        .iter()
        .filter_map(|ticket| {
            let id = ticket["id"].as_str()?;
            let status = ticket["status"].as_str().unwrap_or_default();
            let count = updates(ticket).len();
            let changed = match previous.iter().find(|old| old["id"].as_str() == Some(id)) {
                Some(old) => old["status"].as_str() != Some(status) || count > updates(old).len(),
                None => count > 0,
            };
            changed.then(|| Change {
                ticket: id.to_string(),
                status: status.to_string(),
                text: updates(ticket).last().and_then(|update| update["text"].as_str()).unwrap_or_default().chars().take(500).collect(),
                count,
            })
        })
        .collect()
}

/// A user's file: `{"version", "tickets"}`, only theirs.
pub fn user_file(version: u64, tickets: &[Value]) -> String {
    let mut text = serde_json::to_string_pretty(&json!({"version": version, "tickets": tickets})).unwrap_or_default();
    text.push('\n');
    text
}

/// What storing a ticket list did.
#[derive(Debug, Default)]
pub struct Stored {
    /// The users whose file was written.
    pub users: Vec<String>,
    /// What to tell whom: the account, its private gid, the change.
    pub changes: Vec<(Account, u32, Change)>,
    /// Why some tickets were not stored (logged).
    pub problems: Vec<String>,
}

/// The stored version, 0 without one.
pub fn stored_version(dir: &Path) -> u64 {
    fs::read_to_string(dir.join(VERSION_FILE)).ok().and_then(|text| text.trim().parse().ok()).unwrap_or(0)
}

/// Writes each user's tickets into `dir` (root:root 0755): `<uid>.json`, root's with the user's private group, 0640.
/// The files of users who have no ticket now go. With `tell`, the changes since each user's previous file are returned
/// to be told; a user without a previous file is not told (it would repeat everything once). Then the version file.
pub fn store(system: &System, dir: &Path, list: &TicketList, tell: bool) -> Result<Stored, String> {
    fs::create_dir_all(dir).map_err(|error| format!("{}: {error}", dir.display()))?;
    fs::set_permissions(dir, fs::Permissions::from_mode(0o755)).map_err(|error| format!("{}: {error}", dir.display()))?;
    let mut stored = Stored::default();
    let mut kept: Vec<String> = Vec::new();
    for (user, tickets) in by_user(&list.tickets) {
        let Some(account) = accounts::by_name(system, &user) else {
            stored.problems.push(format!("tickets of {user}: no such account here"));
            continue;
        };
        let gid = match accounts::private_group(system, &account) {
            Ok(gid) => gid,
            Err(why) => {
                stored.problems.push(format!("no ticket file for {why}"));
                continue;
            }
        };
        let path = dir.join(format!("{}.json", account.uid));
        let previous: Option<Vec<Value>> = store::read_limited(&path, MAX_USER_FILE)
            .ok()
            .and_then(|data| serde_json::from_slice::<Value>(&data).ok())
            .and_then(|value| value["tickets"].as_array().cloned());
        store::write_atomic_owned(&path, user_file(list.version, &tickets).as_bytes(), 0o640, Some((0, gid)))
            .map_err(|error| format!("{}: {error}", path.display()))?;
        kept.push(format!("{}.json", account.uid));
        if let (true, Some(previous)) = (tell, &previous) {
            for change in changes(previous, &tickets) {
                stored.changes.push((account.clone(), gid, change));
            }
        }
        stored.users.push(user);
    }
    if let Ok(entries) = fs::read_dir(dir) {
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            let numeric = name.strip_suffix(".json").is_some_and(|uid| !uid.is_empty() && uid.bytes().all(|b| b.is_ascii_digit()));
            if numeric && !kept.contains(&name) {
                let _ = fs::remove_file(entry.path());
            }
        }
    }
    store::write_atomic(&dir.join(VERSION_FILE), format!("{}\n", list.version).as_bytes(), 0o600)
        .map_err(|error| format!("{}: {error}", dir.join(VERSION_FILE).display()))?;
    Ok(stored)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ticket(id: &str, user: &str, status: &str, updates: usize) -> Value {
        let list: Vec<Value> = (0..updates).map(|n| json!({"time": "", "status": status, "text": format!("cập nhật {n}")})).collect();
        json!({"id": id, "user": user, "created": "", "status": status, "note": "x", "updates": list})
    }

    #[test]
    fn what_to_tell() {
        let before = [ticket("HT-0007", "lan", "new", 0), ticket("HT-0006", "lan", "working", 1)];
        let after = [ticket("HT-0007", "lan", "working", 1), ticket("HT-0006", "lan", "working", 1), ticket("HT-0008", "lan", "new", 0), ticket("HT-0009", "lan", "done", 2)];
        let told = changes(&before, &after);
        assert_eq!(told.len(), 2);
        assert_eq!(told[0], Change { ticket: "HT-0007".into(), status: "working".into(), text: "cập nhật 0".into(), count: 1 });
        assert_eq!(told[0].relay_id(), "ticket-HT-0007-1");
        assert_eq!((told[1].ticket.as_str(), told[1].count, told[1].text.as_str()), ("HT-0009", 2, "cập nhật 1"));
        assert!(changes(&after, &after).is_empty());
    }

    #[test]
    fn files_per_user() {
        let root = crate::testutil::TempDir::new("tickets");
        fs::create_dir_all(root.path().join("etc")).unwrap();
        fs::write(root.path().join("etc/passwd"), "lan:x:1001:1001::/home/lan:/bin/bash\nminh:x:1002:100::/home/minh:/bin/bash\n").unwrap();
        fs::write(root.path().join("etc/group"), "users:x:100:\nlan:x:1001:\n").unwrap();
        let system = System::test(root.path());
        let dir = root.path().join("state/tickets");
        let list = TicketList { version: 3, tickets: vec![ticket("HT-0001", "lan", "new", 0), ticket("HT-0002", "minh", "new", 0), ticket("HT-0003", "khach", "new", 0)] };
        let stored = store(&system, &dir, &list, true).unwrap();
        assert_eq!(stored.users, ["lan"]);
        assert!(stored.changes.is_empty(), "no previous file: nothing told");
        assert_eq!(stored.problems.len(), 2, "{:?}", stored.problems);
        let mode = |path: &Path| fs::metadata(path).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode(&dir.join("1001.json")), 0o640);
        assert_eq!(mode(&dir.join(VERSION_FILE)), 0o600);
        assert_eq!(mode(&dir), 0o755);
        assert_eq!(stored_version(&dir), 3);
        let list = TicketList { version: 4, tickets: vec![ticket("HT-0001", "lan", "working", 1)] };
        let stored = store(&system, &dir, &list, true).unwrap();
        assert_eq!(stored.changes.len(), 1);
        assert_eq!((stored.changes[0].0.uid, stored.changes[0].1), (1001, 1001));
        // lan has no ticket any more: the file goes.
        store(&system, &dir, &TicketList { version: 5, tickets: vec![] }, true).unwrap();
        assert!(!dir.join("1001.json").exists());
        assert_eq!(stored_version(&dir), 5);
    }
}
