//! The policy, format 2 (PROTOCOL.md part 2 "Policy (format 2)"; part 1's `wallpaper` and `folders` keep their
//! meaning inside `settings`): parsing, the checks both sides make, and a machine's effective settings.
//!
//! The checks are the listed ones, so that the agent refuses what the admin would refuse to sign and nothing more;
//! the folders part checks a share's URL further when it uses it (folders.rs). Format 1 is refused: a 0.2 admin writes
//! only format 2.

use std::collections::BTreeMap;
use std::fmt;

use serde::Deserialize;
use serde_json::{Map, Value};

use crate::crypto;
use crate::settings::{self, Effective};

pub const FORMAT: u64 = 2;
pub const MAX_FILE_SIZE: u64 = 20 * 1024 * 1024;
pub const MAX_PERIODS: usize = 50;
pub const MAX_NAME_CHARS: usize = 60;
pub const MAX_DEPARTMENTS: usize = 50;
pub const FILE_TYPES: [&str; 3] = ["jpg", "png", "webp"];
/// The policy text is at most 1 MiB.
pub const MAX_TEXT: usize = 1024 * 1024;

/// Why a policy was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PolicyError(pub String);

impl fmt::Display for PolicyError {
    fn fmt(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl std::error::Error for PolicyError {}

fn refuse<T>(message: impl Into<String>) -> Result<T, PolicyError> {
    Err(PolicyError(message.into()))
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct FileEntry {
    pub size: u64,
    /// jpg, png or webp.
    #[serde(rename = "type")]
    pub kind: String,
}

/// The `wallpaper` section, as in part 1.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Wallpaper {
    /// The image on days that no period holds; None leaves the user's own wallpaper.
    #[serde(default)]
    pub default: Option<String>,
    #[serde(default)]
    pub periods: Vec<Period>,
    /// A user who changes the wallpaper gets the company's back within 30 seconds.
    #[serde(default)]
    pub lock: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Period {
    #[serde(default)]
    pub name: String,
    /// MM-DD, included.
    pub from: String,
    /// MM-DD, included; before `from` when the period crosses New Year.
    pub to: String,
    pub image: String,
}

/// The `folders` section, as in part 1.
#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct Folders {
    /// smb://host/share/rest, where %u stands for the login name.
    pub share: String,
    /// Move what is left in the local Desktop and Documents to the server.
    #[serde(default)]
    pub tidy: bool,
}

/// A department: its machines (`members`) take its settings over the policy's.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct Department {
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub settings: Map<String, Value>,
}

/// One machine's own settings layer, and its secrets sealed for it.
#[derive(Debug, Clone, PartialEq, Deserialize)]
pub struct MachineEntry {
    #[serde(default)]
    pub settings: Map<String, Value>,
    #[serde(default)]
    pub sealed: Option<String>,
}

/// A policy that passed `parse`. Unknown top-level keys are ignored: later formats may add some.
#[derive(Debug, Clone, PartialEq)]
pub struct Policy {
    pub serial: u64,
    /// The admin's X25519 public key: this machine's requests and secrets are keyed with it. Taken from a verified
    /// policy (or, before the first one, from agent.json, which the pairing wrote: see store.rs).
    pub admin_box_key: [u8; 32],
    pub files: BTreeMap<String, FileEntry>,
    pub settings: Map<String, Value>,
    pub departments: BTreeMap<String, Department>,
    /// machine id → department id.
    pub members: BTreeMap<String, String>,
    pub machines: BTreeMap<String, MachineEntry>,
}

/// Parses and checks a policy's JSON text. An unknown `format` is refused before anything else is read.
pub fn parse(text: &str) -> Result<Policy, PolicyError> {
    #[derive(Deserialize)]
    struct Raw {
        serial: u64,
        admin_box_key: String,
        #[serde(default)]
        files: BTreeMap<String, FileEntry>,
        #[serde(default)]
        settings: Map<String, Value>,
        #[serde(default)]
        departments: BTreeMap<String, Department>,
        #[serde(default)]
        members: BTreeMap<String, String>,
        #[serde(default)]
        machines: BTreeMap<String, MachineEntry>,
    }

    if text.len() > MAX_TEXT {
        return refuse(format!("the policy is longer than {MAX_TEXT} bytes"));
    }
    let value: Value = match serde_json::from_str(text) {
        Ok(value) => value,
        Err(error) => return refuse(format!("the policy is not JSON: {error}")),
    };
    let Some(object) = value.as_object() else {
        return refuse("the policy is not a JSON object");
    };
    match object.get("format") {
        Some(format) if format.as_u64() == Some(FORMAT) => {}
        Some(format) => return refuse(format!("unknown policy format {format} (this agent takes format {FORMAT})")),
        None => return refuse("the policy has no format"),
    }
    let raw: Raw = match serde_json::from_value(value) {
        Ok(raw) => raw,
        Err(error) => return refuse(format!("the policy is invalid: {error}")),
    };
    let admin_box_key = crypto::decode_key32(&raw.admin_box_key, "admin_box_key").map_err(PolicyError)?;
    let policy = Policy {
        serial: raw.serial,
        admin_box_key,
        files: raw.files,
        settings: raw.settings,
        departments: raw.departments,
        members: raw.members,
        machines: raw.machines,
    };
    policy.validate()?;
    Ok(policy)
}

/// A machine id: a UUID, 8-4-4-4-12 hex digits.
pub fn is_machine_id(text: &str) -> bool {
    let groups: Vec<&str> = text.split('-').collect();
    groups.len() == 5
        && groups.iter().zip([8, 4, 4, 4, 12]).all(|(group, len)| group.len() == len && group.bytes().all(|b| b.is_ascii_hexdigit()))
}

/// A department id, `[a-z0-9-]{1,32}`.
pub fn is_department_id(text: &str) -> bool {
    (1..=32).contains(&text.len()) && text.bytes().all(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9' | b'-'))
}

impl Policy {
    /// The checks of both sides, in order: the top level and the files, `settings`, the departments and their
    /// settings, the members, the machines.
    pub fn validate(&self) -> Result<(), PolicyError> {
        if self.serial < 1 {
            return refuse("the serial must be at least 1");
        }
        for (sha, file) in &self.files {
            check_sha256(sha)?;
            if file.size > MAX_FILE_SIZE {
                return refuse(format!("file {sha} is larger than 20 MiB"));
            }
            if !FILE_TYPES.contains(&file.kind.as_str()) {
                return refuse(format!("file {sha} has the unknown type {:?}", file.kind));
            }
        }
        settings::check_layer(&self.settings, &self.files, "settings")?;
        if self.departments.len() > MAX_DEPARTMENTS {
            return refuse(format!("more than {MAX_DEPARTMENTS} departments"));
        }
        for (id, department) in &self.departments {
            if !is_department_id(id) {
                return refuse(format!("{id:?} is not a department id ([a-z0-9-]{{1,32}})"));
            }
            if department.name.chars().count() > MAX_NAME_CHARS {
                return refuse(format!("department {id}: the name is longer than {MAX_NAME_CHARS} characters"));
            }
            settings::check_layer(&department.settings, &self.files, &format!("department {id}"))?;
        }
        for (machine, department) in &self.members {
            if !is_machine_id(machine) {
                return refuse(format!("members: {machine:?} is not a machine id"));
            }
            if !self.departments.contains_key(department) {
                return refuse(format!("members: machine {machine} is in the unknown department {department:?}"));
            }
        }
        for (machine, entry) in &self.machines {
            if !is_machine_id(machine) {
                return refuse(format!("machines: {machine:?} is not a machine id"));
            }
            settings::check_layer(&entry.settings, &self.files, &format!("machine {machine}"))?;
        }
        Ok(())
    }

    /// "<sha256>.<type>": the name of a listed file in the agent's files folder.
    pub fn file_name(&self, sha: &str) -> Option<String> {
        self.files.get(sha).map(|file| format!("{sha}.{}", file.kind))
    }

    /// The department `machine_id` belongs to, if any.
    pub fn department_of(&self, machine_id: &str) -> Option<&str> {
        self.members.get(machine_id).map(String::as_str).filter(|id| self.departments.contains_key(*id))
    }

    /// The machine's effective settings as JSON: `settings`, then its department's, then its own. A section in a
    /// later layer replaces the earlier one's whole; `null` turns it off; a section in no layer is not managed.
    pub fn effective_json(&self, machine_id: &str) -> Map<String, Value> {
        let mut merged = self.settings.clone();
        let department = self.department_of(machine_id).and_then(|id| self.departments.get(id));
        let layers = department.map(|department| &department.settings).into_iter().chain(self.machines.get(machine_id).map(|entry| &entry.settings));
        for layer in layers {
            for (name, value) in layer {
                merged.insert(name.clone(), value.clone());
            }
        }
        merged
    }

    /// The machine's effective settings, typed.
    pub fn effective(&self, machine_id: &str) -> Effective {
        Effective::from_json(&self.effective_json(machine_id))
    }

    /// The secrets sealed for `machine_id`, if the policy has any.
    pub fn sealed_for(&self, machine_id: &str) -> Option<&str> {
        self.machines.get(machine_id).and_then(|entry| entry.sealed.as_deref())
    }
}

/// 64 lowercase hex digits.
pub fn check_sha256(text: &str) -> Result<(), PolicyError> {
    if text.len() == 64 && text.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f')) {
        Ok(())
    } else {
        refuse(format!("{text:?} is not a sha256 (64 lowercase hex digits)"))
    }
}

/// `share` starts with smb://, has a host, and has no `..`, no `@` (no credentials in URLs) and no spaces.
pub fn check_share(share: &str) -> Result<(), PolicyError> {
    let Some(rest) = share.strip_prefix("smb://") else {
        return refuse("the share must start with smb://");
    };
    let authority = rest.split('/').next().unwrap_or_default();
    let host = match authority.rsplit_once(':') {
        Some((host, port)) if port.bytes().all(|byte| byte.is_ascii_digit()) => host,
        _ => authority,
    };
    if host.is_empty() {
        return refuse("the share has no host");
    }
    if share.contains("..") {
        return refuse("the share must not contain ..");
    }
    if share.contains('@') {
        return refuse("the share must not contain @ (no credentials in the URL)");
    }
    if share.chars().any(char::is_whitespace) {
        return refuse("the share must not contain spaces");
    }
    Ok(())
}

/// A day of the year as the periods write it, MM-DD. Ordered by month, then day.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct MonthDay {
    pub month: u8,
    pub day: u8,
}

impl MonthDay {
    /// "MM-DD" naming a real day; 02-29 is one.
    pub fn parse(text: &str) -> Result<MonthDay, PolicyError> {
        let bytes = text.as_bytes();
        let digits = |pair: &[u8]| -> Option<u8> {
            match pair {
                [tens @ b'0'..=b'9', ones @ b'0'..=b'9'] => Some((tens - b'0') * 10 + (ones - b'0')),
                _ => None,
            }
        };
        if bytes.len() == 5 && bytes[2] == b'-' {
            if let (Some(month), Some(day)) = (digits(&bytes[..2]), digits(&bytes[3..])) {
                let last = match month {
                    2 => 29,
                    4 | 6 | 9 | 11 => 30,
                    _ => 31,
                };
                if (1..=12).contains(&month) && (1..=last).contains(&day) {
                    return Ok(MonthDay { month, day });
                }
            }
        }
        refuse(format!("{text:?} is not a day written MM-DD"))
    }
}

impl Period {
    /// Whether `day` is in the period, both ends included. A period whose `from` is after its `to` crosses New
    /// Year: 12-25 to 01-05 holds the last week of the year and the first days of the next.
    pub fn contains(&self, day: MonthDay) -> bool {
        let (Ok(from), Ok(to)) = (MonthDay::parse(&self.from), MonthDay::parse(&self.to)) else {
            return false;
        };
        if from <= to {
            from <= day && day <= to
        } else {
            day >= from || day <= to
        }
    }
}

impl Wallpaper {
    /// Today's image: that of the first period holding `today`, else `default`. None leaves the user's own.
    pub fn image_for(&self, today: MonthDay) -> Option<&str> {
        match self.periods.iter().find(|period| period.contains(today)) {
            Some(period) => Some(&period.image),
            None => self.default.as_deref(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const A: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    const B: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
    const C: &str = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc";
    /// The admin box key of the test vectors.
    const BOX: &str = "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ=";

    fn day(text: &str) -> MonthDay {
        MonthDay::parse(text).unwrap()
    }

    fn period(from: &str, to: &str, image: &str) -> Period {
        Period { name: String::new(), from: from.into(), to: to.into(), image: image.into() }
    }

    #[test]
    fn month_days() {
        assert_eq!(day("02-29"), MonthDay { month: 2, day: 29 });
        assert_eq!(day("12-31"), MonthDay { month: 12, day: 31 });
        for bad in ["02-30", "04-31", "13-01", "00-10", "01-00", "1-05", "01-5", "01/05", "0a-01", "", "01-055"] {
            assert!(MonthDay::parse(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn first_period_wins_then_default() {
        let wallpaper = Wallpaper {
            default: Some(C.into()),
            periods: vec![period("01-25", "02-05", A), period("02-01", "02-10", B)],
            lock: false,
        };
        assert_eq!(wallpaper.image_for(day("01-25")), Some(A));
        assert_eq!(wallpaper.image_for(day("02-03")), Some(A));
        assert_eq!(wallpaper.image_for(day("02-06")), Some(B));
        assert_eq!(wallpaper.image_for(day("02-10")), Some(B));
        assert_eq!(wallpaper.image_for(day("02-11")), Some(C));
        assert_eq!(wallpaper.image_for(day("01-24")), Some(C));
    }

    #[test]
    fn period_across_new_year() {
        let wallpaper = Wallpaper { default: None, periods: vec![period("12-25", "01-05", A)], lock: true };
        for inside in ["12-25", "12-31", "01-01", "01-05"] {
            assert_eq!(wallpaper.image_for(day(inside)), Some(A), "{inside}");
        }
        // No default: the user's own wallpaper stays.
        for outside in ["12-24", "01-06", "06-15"] {
            assert_eq!(wallpaper.image_for(day(outside)), None, "{outside}");
        }
    }

    #[test]
    fn leap_day_periods() {
        let only_leap_day = period("02-29", "02-29", A);
        assert!(only_leap_day.contains(day("02-29")));
        assert!(!only_leap_day.contains(day("02-28")));
        assert!(!only_leap_day.contains(day("03-01")));
        let around = period("02-28", "03-01", B);
        assert!(around.contains(day("02-29")));
        // In a year without 02-29, a period starting on it starts in effect on 03-01.
        let from_leap_day = period("02-29", "03-05", C);
        assert!(!from_leap_day.contains(day("02-28")));
        assert!(from_leap_day.contains(day("03-01")));
        let across_new_year_to_leap_day = period("12-01", "02-29", A);
        assert!(across_new_year_to_leap_day.contains(day("02-29")));
        assert!(!across_new_year_to_leap_day.contains(day("03-01")));
    }

    #[test]
    fn share_rules() {
        for good in ["smb://nas/share", "smb://nas.congty.local/nhanvien/%u", "smb://192.168.1.5:445/data", "smb://nas"] {
            assert!(check_share(good).is_ok(), "{good}");
        }
        for bad in [
            "http://nas/share",
            "smb:///share",
            "smb://:445/share",
            "smb://nas/a/../b",
            "smb://user:pw@nas/share",
            "smb://nas/my share",
            "smb://nas/tab\there",
            "SMB://nas/share",
        ] {
            assert!(check_share(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn null_parts_and_unknown_keys() {
        let policy = parse(&format!(
            r#"{{"format": 2, "serial": 3, "admin_box_key": "{BOX}", "files": {{}}, "settings": {{"wallpaper": null, "folders": null}}, "later": [1]}}"#
        ))
        .unwrap();
        assert_eq!(policy.serial, 3);
        assert_eq!(policy.effective("7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6"), Effective::default());
        for bad in [
            format!(r#"{{"format": 2, "serial": 1.5, "admin_box_key": "{BOX}"}}"#),
            format!(r#"{{"format": 2, "serial": -1, "admin_box_key": "{BOX}"}}"#),
            r#"{"format": 2, "serial": 1}"#.to_string(),
            r#"{"format": 2, "serial": 1, "admin_box_key": "AAAA"}"#.to_string(),
            format!(r#"{{"format": 1, "serial": 1, "admin_box_key": "{BOX}"}}"#),
            format!(r#"{{"format": "2", "serial": 1, "admin_box_key": "{BOX}"}}"#),
            r#"{"serial": 1}"#.to_string(),
            r#"[1]"#.to_string(),
        ] {
            assert!(parse(&bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn limits() {
        let files = format!(r#"{{"{A}": {{"size": 20971520, "type": "png"}}}}"#);
        let with_files = |files: &str| format!(r#"{{"format": 2, "serial": 1, "admin_box_key": "{BOX}", "files": {files}}}"#);
        assert!(parse(&with_files(&files)).is_ok());
        assert!(parse(&with_files(&format!(r#"{{"{A}": {{"size": 20971521, "type": "png"}}}}"#))).is_err());

        let period = |name: &str| format!(r#"{{"name": "{name}", "from": "01-01", "to": "01-02", "image": "{A}"}}"#);
        let with = |periods: Vec<String>| {
            format!(
                r#"{{"format": 2, "serial": 1, "admin_box_key": "{BOX}", "files": {files}, "settings": {{"wallpaper": {{"default": null, "periods": [{}], "lock": false}}}}}}"#,
                periods.join(",")
            )
        };
        assert!(parse(&with(vec![period(&"ế".repeat(60)); 50])).is_ok());
        assert!(parse(&with(vec![period("x"); 51])).is_err());
        assert!(parse(&with(vec![period(&"ế".repeat(61))])).is_err());

        let departments = |count: usize| {
            let list: Vec<String> = (0..count).map(|i| format!(r#""d{i}": {{"name": "x", "settings": {{}}}}"#)).collect();
            format!(r#"{{"format": 2, "serial": 1, "admin_box_key": "{BOX}", "departments": {{{}}}}}"#, list.join(","))
        };
        assert!(parse(&departments(50)).is_ok());
        assert!(parse(&departments(51)).is_err());
    }
}
