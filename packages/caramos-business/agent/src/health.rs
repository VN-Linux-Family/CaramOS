//! Health, in every check-in (PROTOCOL.md part 2 "Inventory and health"): disk space and health, battery health,
//! waiting updates, a reboot required, the firewall, the version, the uptime, and how each managed section applied.
//! It is collected at most every 30 minutes; `applied` is always the latest.
//!
//! From 0.3 (part 3 "Security report") it adds the memory and the disk encryption (with the slow part), and at each
//! check-in the screen lock of the user at the screen, USB storage, the freeze, the last maintenance and snapshot.

use std::collections::BTreeMap;
use std::fs;
use std::time::Duration;

use serde_json::{json, Value};

use crate::inventory;
use crate::machine;
use crate::sections::{firewall, shared, snapshots, System};

const TOOL_TIMEOUT: Duration = Duration::from_secs(120);
/// Health is collected at most this often.
pub const EVERY: Duration = Duration::from_secs(30 * 60);

/// Upgradable packages from `apt-get -s upgrade`: (security, other). A package counts as a security update when an
/// `-security` suite offers it.
pub fn count_updates(simulation: &str) -> (u32, u32) {
    let mut counts = (0, 0);
    for line in simulation.lines().filter(|line| line.starts_with("Inst ")) {
        if line.contains("-security") {
            counts.0 += 1;
        } else {
            counts.1 += 1;
        }
    }
    counts
}

/// Free space on / in percent, from `stat -f -c '%a %b' /` (blocks available to users, blocks in all).
pub fn free_percent(stat: &str) -> Option<u32> {
    let mut numbers = stat.split_whitespace().map(|number| number.parse::<u64>().ok());
    let (available, total) = (numbers.next()??, numbers.next()??);
    (total > 0).then(|| ((available * 100 + total / 2) / total) as u32)
}

/// The worst disk health: failing if one fails, ok if all are ok, else unknown.
pub fn worst_disk(disks: &[inventory::Disk]) -> &'static str {
    if disks.iter().any(|disk| disk.health == "failing") {
        "failing"
    } else if !disks.is_empty() && disks.iter().all(|disk| disk.health == "ok") {
        "ok"
    } else {
        "unknown"
    }
}

/// "luks" when the device mounted at `mountpoint` sits on a `crypt` device, "none" when not, "unknown" when lsblk
/// failed or names no device there.
pub fn encryption(lsblk: Option<&Value>, mountpoint: &str) -> &'static str {
    match lsblk.and_then(|lsblk| snapshots::device_chain(lsblk, mountpoint)) {
        Some(chain) if chain.iter().any(|device| device["type"].as_str() == Some("crypt")) => "luks",
        Some(_) => "none",
        None => "unknown",
    }
}

/// What 0.3 adds to the health at each check-in.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct Security {
    /// The status of the user at the screen says the screen locks by itself; None without a user at the screen.
    pub screen_lock_on: Option<bool>,
    /// "unlocked", "allow", "read-only" or "block".
    pub usb_storage: String,
    /// `/` is overlayroot now.
    pub frozen: bool,
    /// The agent's overlayroot.local.conf is on the disk.
    pub freeze_configured: bool,
    pub last_maintenance: Option<String>,
    pub maintenance_result: String,
    pub last_snapshot: Option<String>,
    pub snapshot_space_mb: Option<u64>,
}

/// The health with the 0.3 keys of each check-in.
pub fn with_security(mut health: Value, security: &Security) -> Value {
    if let Some(object) = health.as_object_mut() {
        let result: String = security.maintenance_result.chars().take(200).collect();
        for (key, value) in [
            ("screen_lock_on", json!(security.screen_lock_on)),
            ("usb_storage", json!(security.usb_storage)),
            ("frozen", json!(security.frozen)),
            ("freeze_configured", json!(security.freeze_configured)),
            ("last_maintenance", json!(security.last_maintenance)),
            ("maintenance_result", json!(result)),
            ("last_snapshot", json!(security.last_snapshot)),
            ("snapshot_space_mb", json!(security.snapshot_space_mb)),
        ] {
            object.insert(key.to_string(), value);
        }
    }
    health
}

/// Collects the health now, without `applied` and the keys of each check-in.
pub fn collect(system: &System) -> Value {
    let root = system.root.as_path();
    let disk_free = system.run("stat", &["-f", "-c", "%a %b", "/"], TOOL_TIMEOUT).ok().and_then(|output| free_percent(&output.stdout));
    let disks = inventory::collect_disks(system);
    let battery = inventory::batteries(root).iter().map(|battery| battery.health_pct).min();
    let (security, other) = system
        .run("apt-get", &["-s", "-o", "Debug::NoLocking=1", "upgrade"], TOOL_TIMEOUT)
        .map(|output| count_updates(&output.stdout))
        .unwrap_or((0, 0));
    let uptime = fs::read_to_string(root.join("proc/uptime"))
        .ok()
        .and_then(|text| text.split_whitespace().next()?.parse::<f64>().ok())
        .map_or(0, |seconds| (seconds / 3600.0) as u64);
    let frozen = shared::is_frozen(system);
    let lsblk = snapshots::lsblk(system).ok();
    let root_device = if frozen { shared::LOWER } else { "/" };
    json!({
        "memory_mb": shared::memory_mb(system),
        "encryption": encryption(lsblk.as_ref(), root_device),
        "disk_free_pct": disk_free,
        "disk_health": worst_disk(&disks),
        "battery_health_pct": battery,
        "updates": {"security": security, "other": other},
        "reboot_required": root.join("var/run/reboot-required").exists() || root.join("run/reboot-required").exists(),
        "firewall": firewall::status(system),
        "caramos_version": fs::read_to_string(root.join("etc/caramos-release")).map(|text| machine::parse_release(&text)).unwrap_or_default(),
        "uptime_hours": uptime,
    })
}

/// The health with the latest `applied`.
pub fn with_applied(mut health: Value, applied: &BTreeMap<String, String>) -> Value {
    if let Some(object) = health.as_object_mut() {
        object.insert("applied".to_string(), json!(applied));
    }
    health
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn updates_free_space_and_disks() {
        let simulation = "Reading package lists...\n\
            Inst libc6 [2.39-0ubuntu8.3] (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates, Ubuntu:24.04/noble-security [amd64])\n\
            Inst firefox [146.0] (147.0 linuxmint:22/zena [amd64])\n\
            Conf libc6 (2.39-0ubuntu8.4 Ubuntu:24.04/noble-updates [amd64])\n";
        assert_eq!(count_updates(simulation), (1, 1));
        assert_eq!(free_percent("2300 10000\n"), Some(23));
        assert_eq!(free_percent("x"), None);
        let disk = |health: &str| inventory::Disk { health: health.into(), ..inventory::Disk::default() };
        assert_eq!(worst_disk(&[disk("ok"), disk("ok")]), "ok");
        assert_eq!(worst_disk(&[disk("ok"), disk("unknown")]), "unknown");
        assert_eq!(worst_disk(&[disk("failing"), disk("ok")]), "failing");
        assert_eq!(worst_disk(&[]), "unknown");
        let applied = BTreeMap::from([("browser".to_string(), "ok".to_string())]);
        assert_eq!(with_applied(json!({"uptime_hours": 1}), &applied)["applied"]["browser"], "ok");
    }

    #[test]
    fn encryption_from_lsblk() {
        let plain = json!({"blockdevices": [{"name": "vda", "type": "disk", "mountpoints": [null], "children": [
            {"name": "vda3", "type": "part", "mountpoints": ["/"]}]}]});
        assert_eq!(encryption(Some(&plain), "/"), "none");
        let luks = json!({"blockdevices": [{"name": "nvme0n1", "type": "disk", "mountpoints": [null], "children": [
            {"name": "nvme0n1p3", "type": "part", "mountpoints": [null], "children": [
                {"name": "dm_crypt-0", "type": "crypt", "mountpoints": [null], "children": [
                    {"name": "vgmint-root", "type": "lvm", "mountpoints": ["/"]}]}]}]}]});
        assert_eq!(encryption(Some(&luks), "/"), "luks");
        let frozen = json!({"blockdevices": [{"name": "vda", "type": "disk", "mountpoints": [null], "children": [
            {"name": "vda3", "type": "part", "mountpoints": ["/media/root-ro"]}]}]});
        assert_eq!(encryption(Some(&frozen), "/media/root-ro"), "none");
        assert_eq!(encryption(Some(&frozen), "/"), "unknown");
        assert_eq!(encryption(None, "/"), "unknown");
    }
}
