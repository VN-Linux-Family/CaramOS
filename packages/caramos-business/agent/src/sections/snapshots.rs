//! `snapshots` (PROTOCOL.md part 3 "Managed snapshots"): Timeshift in rsync mode on the root file system, on the
//! company's schedule.
//!
//! - The agent writes `/etc/timeshift/timeshift.json` (an earlier file is kept in managed.json and comes back when the
//!   section goes away), then runs `timeshift --list --scripted`: any Timeshift command that loads the settings brings
//!   its cron files (`/etc/cron.d/timeshift-hourly`, `…-boot`) in line with them. Writing the file alone schedules
//!   nothing.
//! - `before_update`: the `update` command first takes a snapshot.
//! - Snapshots already taken stay: they are the machine's. User files are excluded (`/home/**`, `/root/**`).
//! - Never on a frozen machine: Timeshift mounts the root device read-write, under the overlay's feet.

use std::fs;
use std::time::Duration;

use serde_json::Value;

use super::{remove_if_present, write_if_changed, Before, Managed, System};
use crate::clock::LocalTime;
use crate::settings::{Schedule, Snapshots};

pub const SETTINGS: &str = "/etc/timeshift/timeshift.json";
pub const TIMESHIFT: &str = "/usr/bin/timeshift";
/// Where rsync snapshots of the root file system live.
pub const ROOT: &str = "/timeshift";
/// The comment of the snapshot taken before an update.
pub const COMMENT: &str = "CaramOS Doanh nghiệp";

const LIST_TIMEOUT: Duration = Duration::from_secs(5 * 60);
/// A first snapshot copies the whole system (154 s and 6.8 GB on the test VM); a slow disk takes much longer.
pub const CREATE_TIMEOUT: Duration = Duration::from_secs(3 * 3600);
const TOOL_TIMEOUT: Duration = Duration::from_secs(60);
const DU_TIMEOUT: Duration = Duration::from_secs(15 * 60);

/// Timeshift's settings for the section, in its own key order: `uuid` is the root file system's, `parent` the LUKS
/// partition's under it (or empty). The chosen level keeps `keep` snapshots; the other levels keep Timeshift's counts
/// and are off.
pub fn settings_text(snapshots: &Snapshots, uuid: &str, parent: &str) -> String {
    let flag = |level: Schedule| if snapshots.schedule == level { "true" } else { "false" }.to_string();
    let count = |level: Schedule, default: u32| if snapshots.schedule == level { snapshots.keep } else { default }.to_string();
    let pairs: [(&str, String); 18] = [
        ("backup_device_uuid", uuid.to_string()),
        ("parent_device_uuid", parent.to_string()),
        ("do_first_run", "false".to_string()),
        ("btrfs_mode", "false".to_string()),
        ("include_btrfs_home", "false".to_string()),
        ("stop_cron_emails", "true".to_string()),
        ("schedule_monthly", flag(Schedule::Monthly)),
        ("schedule_weekly", flag(Schedule::Weekly)),
        ("schedule_daily", flag(Schedule::Daily)),
        ("schedule_hourly", "false".to_string()),
        ("schedule_boot", "false".to_string()),
        ("count_monthly", count(Schedule::Monthly, 2)),
        ("count_weekly", count(Schedule::Weekly, 3)),
        ("count_daily", count(Schedule::Daily, 5)),
        ("count_hourly", "6".to_string()),
        ("count_boot", "5".to_string()),
        ("snapshot_size", "0".to_string()),
        ("snapshot_count", "0".to_string()),
    ];
    let quote = |text: &str| serde_json::to_string(text).unwrap_or_default();
    let mut text = String::from("{\n");
    for (key, value) in &pairs {
        text.push_str(&format!("  {}: {},\n", quote(key), quote(value)));
    }
    text.push_str("  \"exclude\": [\n    \"/home/**\",\n    \"/root/**\"\n  ],\n  \"exclude-apps\": []\n}\n");
    text
}

/// Whether Timeshift's file already says what `wanted` says, whatever its formatting (Timeshift may write it again).
fn same_settings(current: &str, wanted: &str) -> bool {
    match (serde_json::from_str::<Value>(current), serde_json::from_str::<Value>(wanted)) {
        (Ok(Value::Object(current)), Ok(Value::Object(wanted))) => wanted.iter().all(|(key, value)| current.get(key) == Some(value)),
        _ => false,
    }
}

/// The chain of block devices from a disk down to the one mounted at `mountpoint`, from `lsblk -J -o
/// NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS`: the disk first. None when no device is mounted there.
pub fn device_chain(lsblk: &Value, mountpoint: &str) -> Option<Vec<Value>> {
    fn walk(devices: &Value, mountpoint: &str, path: &mut Vec<Value>) -> bool {
        for device in devices.as_array().into_iter().flatten() {
            path.push(device.clone());
            let mounted = device["mountpoints"].as_array().is_some_and(|points| points.iter().any(|point| point.as_str() == Some(mountpoint)))
                || device["mountpoint"].as_str() == Some(mountpoint);
            if mounted || walk(&device["children"], mountpoint, path) {
                return true;
            }
            path.pop();
        }
        false
    }
    let mut path = Vec::new();
    walk(&lsblk["blockdevices"], mountpoint, &mut path).then_some(path)
}

/// The UUID of the LUKS partition the device mounted at `mountpoint` sits on, or "".
pub fn luks_parent(lsblk: &Value, mountpoint: &str) -> String {
    device_chain(lsblk, mountpoint)
        .and_then(|chain| chain.iter().rev().find(|device| device["fstype"].as_str() == Some("crypto_LUKS")).and_then(|device| device["uuid"].as_str().map(str::to_string)))
        .unwrap_or_default()
}

/// `lsblk -J -o NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS`, parsed.
pub fn lsblk(system: &System) -> Result<Value, String> {
    let output = system.check("lsblk", &["-J", "-o", "NAME,TYPE,FSTYPE,UUID,MOUNTPOINTS"], TOOL_TIMEOUT)?;
    serde_json::from_str(&output).map_err(|error| format!("lsblk: {error}"))
}

/// Applies the section (not on a frozen machine), or puts Timeshift's settings back when it is None.
pub fn apply(system: &System, snapshots: Option<&Snapshots>, managed: &mut Managed, frozen: bool) -> Result<(), String> {
    let Some(snapshots) = snapshots else {
        return put_back(system, managed);
    };
    if frozen {
        return Err("no snapshots while the machine is frozen".to_string());
    }
    if !system.has_any(&[TIMESHIFT]) {
        return Err("Timeshift is not installed".to_string());
    }
    let (kind, uuid) = if system.commands {
        let output = system.check("findmnt", &["-n", "-o", "FSTYPE,UUID", "/"], TOOL_TIMEOUT)?;
        let mut words = output.split_whitespace();
        (words.next().unwrap_or_default().to_string(), words.next().unwrap_or_default().to_string())
    } else {
        ("ext4".to_string(), "00000000-0000-4000-8000-000000000000".to_string())
    };
    if kind != "ext4" {
        return Err(format!("the root file system is {kind}, not ext4"));
    }
    if uuid.is_empty() {
        return Err("the root file system has no UUID".to_string());
    }
    let parent = if system.commands { luks_parent(&lsblk(system)?, "/") } else { String::new() };
    let wanted = settings_text(snapshots, &uuid, &parent);
    let path = system.path(SETTINGS);
    let current = fs::read_to_string(&path).ok();
    if current.as_deref().is_some_and(|current| same_settings(current, &wanted)) {
        // In line already, unless the cron file went away.
        return if !system.commands || system.path(CRON_FILE).exists() { Ok(()) } else { sync_cron(system, Some(true)) };
    }
    if managed.timeshift.is_none() {
        managed.timeshift = Some(Before { existed: current.is_some(), contents: current });
    }
    write_if_changed(&path, wanted.as_bytes(), 0o644).map_err(|error| format!("{SETTINGS}: {error}"))?;
    sync_cron(system, Some(true))
}

/// Timeshift's settings as they were before the agent, then its cron files in line with them.
pub fn put_back(system: &System, managed: &mut Managed) -> Result<(), String> {
    let Some(before) = managed.timeshift.clone() else {
        return Ok(());
    };
    let path = system.path(SETTINGS);
    match before.contents.filter(|_| before.existed) {
        Some(contents) => write_if_changed(&path, contents.as_bytes(), 0o644).map(|_| ()),
        None => remove_if_present(&path).map(|_| ()),
    }
    .map_err(|error| format!("{SETTINGS}: {error}"))?;
    if system.has_any(&[TIMESHIFT]) {
        sync_cron(system, None)?;
    }
    managed.timeshift = None;
    Ok(())
}

/// Timeshift's cron file for a schedule.
pub const CRON_FILE: &str = "/etc/cron.d/timeshift-hourly";

/// `timeshift --list --scripted`: Timeshift adds or removes its cron files to match its settings. It exits 1 with "No
/// snapshots found" before the first snapshot, so its status says nothing: `scheduled` says whether the cron file is to
/// be there afterwards, and its absence is the failure.
fn sync_cron(system: &System, scheduled: Option<bool>) -> Result<(), String> {
    let output = system.run("timeshift", &["--list", "--scripted"], LIST_TIMEOUT)?;
    if output.status.is_none() {
        return Err("timeshift --list did not answer in time".to_string());
    }
    if system.commands && scheduled == Some(true) && !system.path(CRON_FILE).exists() {
        return Err(format!("timeshift did not add {CRON_FILE}: {}", output.message()));
    }
    Ok(())
}

/// The snapshot before an update: `timeshift --create --comments "CaramOS Doanh nghiệp" --tags O --scripted`.
pub fn create(system: &System) -> Result<(), String> {
    system.check("timeshift", &["--create", "--comments", COMMENT, "--tags", "O", "--scripted"], CREATE_TIMEOUT).map(|_| ())
}

/// The newest snapshot's time (`created`, Unix time as a string, in `<ROOT>/snapshots/*/info.json`), as ISO 8601.
pub fn last_snapshot(system: &System) -> Option<String> {
    let entries = fs::read_dir(system.path(&format!("{ROOT}/snapshots"))).ok()?;
    entries
        .flatten()
        .filter_map(|entry| {
            let data = crate::store::read_limited(&entry.path().join("info.json"), 64 * 1024).ok()?;
            let value: Value = serde_json::from_slice(&data).ok()?;
            value["created"].as_str().and_then(|text| text.trim().parse::<i64>().ok()).or_else(|| value["created"].as_i64())
        })
        .max()
        .map(|unix| LocalTime::from_unix(unix).iso8601())
}

/// The space the snapshots take, `du -sm /timeshift`, when there are some.
pub fn space_mb(system: &System) -> Option<u64> {
    if !system.path(ROOT).is_dir() {
        return None;
    }
    let output = system.check("du", &["-sm", ROOT], DU_TIMEOUT).ok()?;
    output.split_whitespace().next()?.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn settings_for_each_schedule() {
        let daily = settings_text(&Snapshots { schedule: Schedule::Daily, keep: 7, before_update: false }, "u", "p");
        let value: Value = serde_json::from_str(&daily).unwrap();
        assert_eq!((value["schedule_daily"].clone(), value["count_daily"].clone()), (json!("true"), json!("7")));
        assert_eq!((value["schedule_weekly"].clone(), value["count_weekly"].clone()), (json!("false"), json!("3")));
        assert_eq!(value["parent_device_uuid"], "p");
        assert_eq!(value["exclude"], json!(["/home/**", "/root/**"]));
        assert!(same_settings(&serde_json::to_string(&value).unwrap(), &daily), "Timeshift's own formatting is the same");
        let monthly = settings_text(&Snapshots { schedule: Schedule::Monthly, keep: 1, before_update: true }, "u", "");
        assert!(!same_settings(&monthly, &daily));
    }

    #[test]
    fn devices_under_the_root() {
        let lsblk = json!({"blockdevices": [
            {"name": "vda", "type": "disk", "fstype": null, "uuid": null, "mountpoints": [null], "children": [
                {"name": "vda2", "type": "part", "fstype": "vfat", "uuid": "AAAA-BBBB", "mountpoints": ["/boot/efi"]},
                {"name": "vda3", "type": "part", "fstype": "crypto_LUKS", "uuid": "1d0e9a5c-luks", "mountpoints": [null], "children": [
                    {"name": "luks-1d0e", "type": "crypt", "fstype": "ext4", "uuid": "root-uuid", "mountpoints": ["/"]}]}]}]});
        let chain = device_chain(&lsblk, "/").unwrap();
        let names: Vec<&str> = chain.iter().map(|device| device["name"].as_str().unwrap()).collect();
        assert_eq!(names, ["vda", "vda3", "luks-1d0e"]);
        assert_eq!(luks_parent(&lsblk, "/"), "1d0e9a5c-luks");
        assert_eq!(luks_parent(&lsblk, "/boot/efi"), "");
        assert!(device_chain(&lsblk, "/media/root-ro").is_none());
    }

    #[test]
    fn put_back_and_history() {
        let root = crate::testutil::TempDir::new("snapshots");
        let system = System::test(root.path());
        let mut managed = Managed::default();
        let section = Snapshots { schedule: Schedule::Weekly, keep: 3, before_update: true };
        assert_eq!(apply(&system, Some(&section), &mut managed, false).unwrap_err(), "Timeshift is not installed");
        fs::create_dir_all(root.path().join("usr/bin")).unwrap();
        fs::write(root.path().join("usr/bin/timeshift"), "").unwrap();
        assert!(apply(&system, Some(&section), &mut managed, true).unwrap_err().contains("frozen"));
        apply(&system, Some(&section), &mut managed, false).unwrap();
        assert!(system.path(SETTINGS).exists());
        assert_eq!(managed.timeshift, Some(Before { existed: false, contents: None }));
        apply(&system, None, &mut managed, false).unwrap();
        assert!(!system.path(SETTINGS).exists());
        assert_eq!(managed.timeshift, None);

        assert_eq!(last_snapshot(&system), None);
        for (name, created) in [("2026-11-22_02-00-01", "1795200000"), ("2026-11-23_01-02-55", "1795370575")] {
            let dir = root.path().join("timeshift/snapshots").join(name);
            fs::create_dir_all(&dir).unwrap();
            fs::write(dir.join("info.json"), format!("{{\"created\" : \"{created}\", \"tags\" : \"O\"}}")).unwrap();
        }
        assert_eq!(last_snapshot(&system).as_deref(), Some("2026-11-23T01:02:55+07:00"));
    }
}
