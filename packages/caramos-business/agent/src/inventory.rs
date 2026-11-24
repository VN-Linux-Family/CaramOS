//! The inventory (PROTOCOL.md part 2 "Inventory and health"): the machine's hardware, its system and the apps a user
//! sees. Hardware comes from /sys/class/dmi/id, `dmidecode -t 17`, `lsblk -J -b`, `smartctl -j` when installed,
//! /sys/class/power_supply/BAT*, the EDIDs in /sys/class/drm/*/edid and `ip -j addr`; apps from `flatpak list --system
//! --app` and the visible /usr/share/applications/*.desktop files that deb packages own.
//!
//! From 0.3 each app names its `package`, its `licence` as the package states it and its `origin` (PROTOCOL.md part 3
//! "Licence report"): for a deb, the machine-readable `/usr/share/doc/<package>/copyright` (the `License:` of the
//! `Files: *` stanza), else the AppStream file of its desktop id, and the archive `apt-cache policy` names for the
//! installed version; for a Flatpak, its AppStream file and its remote.
//!
//! From 0.3.1 (part 3, "Changes during implementation"): a package's entries share one licence, found through any of
//! them or the package's name, then from what its copyright file says without a `Files: *` stanza (the most common
//! licence of a machine-readable file, a well-known licence in an older one); and `main` marks the entry that names
//! its package.
//!
//! Strings are at most 200 characters, lists at most 500 items, and the body at most 1 MiB.

use std::collections::BTreeMap;
use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::Duration;

use serde::Serialize;

use crate::clock::LocalTime;
use crate::crypto;
use crate::machine;
use crate::sections::System;

const MAX_TEXT: usize = 200;
const MAX_ITEMS: usize = 500;
const MAX_BODY: usize = 1024 * 1024;
const TOOL_TIMEOUT: Duration = Duration::from_secs(60);

fn clip(text: &str) -> String {
    text.trim().chars().filter(|c| !c.is_control()).take(MAX_TEXT).collect()
}

fn read(root: &Path, path: &str) -> String {
    fs::read_to_string(root.join(path.trim_start_matches('/'))).map(|text| clip(&text)).unwrap_or_default()
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct SystemInfo {
    pub vendor: String,
    pub product: String,
    pub serial: String,
    pub bios: String,
    pub chassis: String,
    pub boot_time: String,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Cpu {
    pub model: String,
    pub cores: u32,
    pub threads: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Module {
    pub size_mb: u64,
    #[serde(rename = "type")]
    pub kind: String,
    pub speed_mts: u32,
    pub slot: String,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Memory {
    pub total_mb: u64,
    pub modules: Vec<Module>,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Disk {
    pub name: String,
    pub model: String,
    pub serial: String,
    pub size_gb: u64,
    pub rotational: bool,
    pub transport: String,
    /// "ok", "failing" or "unknown".
    pub health: String,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Battery {
    pub name: String,
    pub design_wh: f64,
    pub full_wh: f64,
    pub health_pct: u32,
    pub cycles: u32,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Monitor {
    pub connector: String,
    pub name: String,
    pub serial: String,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Nic {
    pub name: String,
    pub mac: String,
    pub ipv4: String,
    pub wired: bool,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Os {
    pub caramos: String,
    pub edition: String,
    pub kernel: String,
}

#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct App {
    /// The desktop file's name for a deb app (`vlc.desktop`), the app id for a Flatpak.
    pub id: String,
    pub name: String,
    pub version: String,
    /// "deb" or "flatpak".
    pub source: String,
    /// The deb package that owns the desktop file, or the Flatpak app id.
    pub package: String,
    /// The licence as the package states it (Debian short names such as `GPL-2+`, or AppStream's SPDX), else
    /// "unknown".
    pub licence: String,
    /// `ubuntu-<component>`, `mint`, `caramos-ppa`, `third-party:<host>`, `local-deb`, `flathub` or
    /// `flatpak:<remote>`.
    pub origin: String,
    /// The entry that names its package (0.3.1): its desktop file is named after the package (`thunar.desktop`), or
    /// its Exec runs the package's program; at most one per package, and every Flatpak app.
    pub main: bool,
}

/// Everything but `collected` and `hash`: what the hash covers.
#[derive(Debug, Clone, Default, PartialEq, Serialize)]
pub struct Body {
    pub system: SystemInfo,
    pub cpu: Cpu,
    pub memory: Memory,
    pub disks: Vec<Disk>,
    pub batteries: Vec<Battery>,
    pub monitors: Vec<Monitor>,
    pub network: Vec<Nic>,
    pub os: Os,
    pub apps: Vec<App>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Inventory {
    pub collected: String,
    pub hash: String,
    #[serde(flatten)]
    pub body: Body,
}

impl Body {
    /// sha256 hex of the body's JSON.
    pub fn hash(&self) -> String {
        crypto::sha256_hex(&serde_json::to_vec(self).unwrap_or_default())
    }
}

/// Collects the inventory now.
pub fn collect(system: &System) -> Inventory {
    let root = system.root.as_path();
    let mut body = Body {
        system: system_info(root),
        cpu: cpu(&fs::read_to_string(root.join("proc/cpuinfo")).unwrap_or_default()),
        memory: Memory {
            total_mb: mem_total_mb(&fs::read_to_string(root.join("proc/meminfo")).unwrap_or_default()),
            modules: if system.has_any(&["/usr/sbin/dmidecode"]) {
                memory_modules(&system.run("dmidecode", &["-t", "17"], TOOL_TIMEOUT).map(|output| output.stdout).unwrap_or_default())
            } else {
                Vec::new()
            },
        },
        disks: collect_disks(system),
        batteries: batteries(root),
        monitors: monitors(root),
        network: network(system),
        os: Os {
            caramos: fs::read_to_string(root.join("etc/caramos-release")).map(|text| machine::parse_release(&text)).unwrap_or_default(),
            edition: machine::edition(root).to_string(),
            kernel: read(root, "/proc/sys/kernel/osrelease"),
        },
        apps: apps(system),
    };
    limit(&mut body);
    Inventory { collected: LocalTime::now().iso8601(), hash: body.hash(), body }
}

/// Keeps the lists within 500 items and the body within 1 MiB (apps go first: they are the longest list).
fn limit(body: &mut Body) {
    body.memory.modules.truncate(MAX_ITEMS);
    body.disks.truncate(MAX_ITEMS);
    body.batteries.truncate(MAX_ITEMS);
    body.monitors.truncate(MAX_ITEMS);
    body.network.truncate(MAX_ITEMS);
    body.apps.truncate(MAX_ITEMS);
    while serde_json::to_vec(body).map_or(0, |json| json.len()) > MAX_BODY - 1024 && !body.apps.is_empty() {
        body.apps.truncate(body.apps.len() / 2);
    }
}

/// The DMI chassis type as desktop, laptop or other.
pub fn chassis(code: &str) -> &'static str {
    match code.trim().parse::<u32>() {
        Ok(3 | 4 | 5 | 6 | 7 | 13 | 15 | 16 | 24 | 35 | 36) => "desktop",
        Ok(8 | 9 | 10 | 11 | 12 | 14 | 18 | 21 | 30 | 31 | 32) => "laptop",
        _ => "other",
    }
}

fn system_info(root: &Path) -> SystemInfo {
    let bios_version = read(root, "/sys/class/dmi/id/bios_version");
    let bios_date = read(root, "/sys/class/dmi/id/bios_date");
    let boot = fs::read_to_string(root.join("proc/stat"))
        .ok()
        .and_then(|stat| stat.lines().find_map(|line| line.strip_prefix("btime ")).and_then(|value| value.trim().parse::<i64>().ok()));
    SystemInfo {
        vendor: read(root, "/sys/class/dmi/id/sys_vendor"),
        product: read(root, "/sys/class/dmi/id/product_name"),
        serial: read(root, "/sys/class/dmi/id/product_serial"),
        bios: clip(&if bios_date.is_empty() { bios_version } else { format!("{bios_version} ({bios_date})") }),
        chassis: chassis(&read(root, "/sys/class/dmi/id/chassis_type")).to_string(),
        boot_time: boot.map(|unix| LocalTime::from_unix(unix).iso8601()).unwrap_or_default(),
    }
}

/// The CPU from /proc/cpuinfo: its model, its cores (physical id, core id pairs) and threads (processors).
pub fn cpu(cpuinfo: &str) -> Cpu {
    let mut model = String::new();
    let mut threads = 0;
    let mut cores = std::collections::BTreeSet::new();
    let (mut physical, mut cores_per_package) = (String::new(), 0u32);
    for line in cpuinfo.lines() {
        let Some((key, value)) = line.split_once(':') else {
            continue;
        };
        let (key, value) = (key.trim(), value.trim());
        match key {
            "processor" => threads += 1,
            "model name" if model.is_empty() => model = clip(value),
            "physical id" => physical = value.to_string(),
            "core id" => {
                cores.insert((physical.clone(), value.to_string()));
            }
            "cpu cores" => cores_per_package = value.parse().unwrap_or(0),
            _ => {}
        }
    }
    let cores = if !cores.is_empty() { cores.len() as u32 } else if cores_per_package > 0 { cores_per_package } else { threads };
    Cpu { model, cores, threads }
}

fn mem_total_mb(meminfo: &str) -> u64 {
    meminfo
        .lines()
        .find_map(|line| line.strip_prefix("MemTotal:"))
        .and_then(|value| value.split_whitespace().next()?.parse::<u64>().ok())
        .map_or(0, |kib| kib / 1024)
}

/// The installed memory modules from `dmidecode -t 17`.
pub fn memory_modules(dmidecode: &str) -> Vec<Module> {
    let mut modules = Vec::new();
    for block in dmidecode.split("\n\n").filter(|block| block.contains("Memory Device")) {
        let field = |name: &str| {
            block.lines().find_map(|line| line.trim().strip_prefix(name).and_then(|rest| rest.strip_prefix(':')).map(str::trim)).unwrap_or("")
        };
        let size = field("Size");
        let mut words = size.split_whitespace();
        let size_mb = match (words.next().and_then(|n| n.parse::<u64>().ok()), words.next()) {
            (Some(n), Some("GB")) => n * 1024,
            (Some(n), Some("TB")) => n * 1024 * 1024,
            (Some(n), Some("MB")) => n,
            _ => continue,
        };
        let speed = |text: &str| text.split_whitespace().next().and_then(|n| n.parse::<u32>().ok());
        modules.push(Module {
            size_mb,
            kind: clip(field("Type")),
            speed_mts: speed(field("Speed")).or_else(|| speed(field("Configured Memory Speed"))).unwrap_or(0),
            slot: clip(field("Locator")),
        });
    }
    modules
}

/// The disks from `lsblk -J -b -d`, with their health from smartctl when installed.
pub fn parse_lsblk(json: &str) -> Vec<Disk> {
    let value: serde_json::Value = serde_json::from_str(json).unwrap_or_default();
    let text = |device: &serde_json::Value, key: &str| device[key].as_str().map(clip).unwrap_or_default();
    value["blockdevices"]
        .as_array()
        .into_iter()
        .flatten()
        .filter(|device| device["type"].as_str() == Some("disk"))
        .filter(|device| !text(device, "name").starts_with("zram") && !text(device, "name").starts_with("loop"))
        .map(|device| Disk {
            name: text(device, "name"),
            model: text(device, "model"),
            serial: text(device, "serial"),
            size_gb: device["size"].as_u64().or_else(|| device["size"].as_str().and_then(|s| s.parse().ok())).map_or(0, |bytes| (bytes + 500_000_000) / 1_000_000_000),
            rotational: device["rota"].as_bool().unwrap_or_else(|| device["rota"].as_str() == Some("1")),
            transport: text(device, "tran"),
            health: "unknown".to_string(),
        })
        .collect()
}

/// The disks with their health (smartctl when installed).
pub fn collect_disks(system: &System) -> Vec<Disk> {
    let output = system.run("lsblk", &["-J", "-b", "-d", "-o", "NAME,MODEL,SERIAL,SIZE,ROTA,TRAN,TYPE"], TOOL_TIMEOUT);
    let mut disks = parse_lsblk(&output.map(|output| output.stdout).unwrap_or_default());
    if system.has_any(&["/usr/sbin/smartctl"]) {
        for disk in &mut disks {
            let device = format!("/dev/{}", disk.name);
            if let Ok(output) = system.run("smartctl", &["-j", "-H", &device], TOOL_TIMEOUT) {
                disk.health = smart_health(&output.stdout).to_string();
            }
        }
    }
    disks
}

/// "ok", "failing" or "unknown" from `smartctl -j -H`.
pub fn smart_health(json: &str) -> &'static str {
    let value: serde_json::Value = serde_json::from_str(json).unwrap_or_default();
    match value["smart_status"]["passed"].as_bool() {
        Some(true) => "ok",
        Some(false) => "failing",
        None => "unknown",
    }
}

fn number(root: &Path, path: &Path) -> Option<f64> {
    fs::read_to_string(root.join(path)).ok()?.trim().parse().ok()
}

/// The batteries, from /sys/class/power_supply/BAT*.
pub fn batteries(root: &Path) -> Vec<Battery> {
    let folder = Path::new("sys/class/power_supply");
    let Ok(entries) = fs::read_dir(root.join(folder)) else {
        return Vec::new();
    };
    let mut names: Vec<String> = entries.flatten().map(|entry| entry.file_name().to_string_lossy().into_owned()).filter(|name| name.starts_with("BAT")).collect();
    names.sort();
    names
        .into_iter()
        .filter_map(|name| {
            let dir = folder.join(&name);
            let value = |file: &str| number(root, &dir.join(file));
            let (design, full) = match (value("energy_full_design"), value("energy_full")) {
                (Some(design), Some(full)) => (design / 1e6, full / 1e6),
                _ => {
                    let volts = value("voltage_min_design")? / 1e6;
                    (value("charge_full_design")? / 1e6 * volts, value("charge_full")? / 1e6 * volts)
                }
            };
            let round = |wh: f64| (wh * 10.0).round() / 10.0;
            Some(Battery {
                name: clip(&name),
                design_wh: round(design),
                full_wh: round(full),
                health_pct: if design > 0.0 { (full / design * 100.0).round() as u32 } else { 0 },
                cycles: value("cycle_count").map_or(0, |cycles| cycles as u32),
            })
        })
        .collect()
}

/// The monitor's name and serial from its EDID's descriptors (0xFC name, 0xFF serial).
pub fn parse_edid(edid: &[u8]) -> (String, String) {
    let (mut name, mut serial) = (String::new(), String::new());
    if edid.len() < 128 {
        return (name, serial);
    }
    for offset in [54, 72, 90, 108] {
        let descriptor = &edid[offset..offset + 18];
        if descriptor[..3] != [0, 0, 0] {
            continue;
        }
        let text: String = descriptor[5..].iter().take_while(|byte| **byte != b'\n').map(|byte| *byte as char).collect();
        match descriptor[3] {
            0xFC => name = clip(&text),
            0xFF => serial = clip(&text),
            _ => {}
        }
    }
    (name, serial)
}

fn monitors(root: &Path) -> Vec<Monitor> {
    let Ok(entries) = fs::read_dir(root.join("sys/class/drm")) else {
        return Vec::new();
    };
    let mut monitors: Vec<Monitor> = entries
        .flatten()
        .filter_map(|entry| {
            let name = entry.file_name().to_string_lossy().into_owned();
            let connector = name.strip_prefix("card")?.split_once('-')?.1.to_string();
            let status = fs::read_to_string(entry.path().join("status")).unwrap_or_default();
            let edid = fs::read(entry.path().join("edid")).unwrap_or_default();
            if status.trim() != "connected" || edid.is_empty() {
                return None;
            }
            let (name, serial) = parse_edid(&edid);
            Some(Monitor { connector: clip(&connector), name, serial })
        })
        .collect();
    monitors.sort_by(|a, b| a.connector.cmp(&b.connector));
    monitors
}

/// The physical network cards, from `ip -j addr`.
fn network(system: &System) -> Vec<Nic> {
    let output = system.run("ip", &["-j", "addr"], TOOL_TIMEOUT).map(|output| output.stdout).unwrap_or_default();
    parse_ip_addr(&output, |name| {
        let dir = system.path("/sys/class/net").join(name);
        (dir.join("device").exists(), dir.join("wireless").exists())
    })
}

/// Cards from `ip -j addr`; `kind(name)` says whether a card is physical and whether it is wireless.
pub fn parse_ip_addr(json: &str, kind: impl Fn(&str) -> (bool, bool)) -> Vec<Nic> {
    let value: serde_json::Value = serde_json::from_str(json).unwrap_or_default();
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(|card| {
            let name = card["ifname"].as_str()?;
            if name == "lo" || name.contains('/') {
                return None;
            }
            let (physical, wireless) = kind(name);
            if !physical {
                return None;
            }
            let ipv4 = card["addr_info"]
                .as_array()
                .into_iter()
                .flatten()
                .find(|address| address["family"].as_str() == Some("inet"))
                .and_then(|address| address["local"].as_str())
                .unwrap_or_default();
            Some(Nic { name: clip(name), mac: clip(card["address"].as_str().unwrap_or_default()), ipv4: clip(ipv4), wired: !wireless })
        })
        .collect()
}

/// A desktop file's entry, as the inventory reads it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct DesktopEntry {
    /// `Name=`, untranslated.
    pub name: String,
    /// The program that `Exec=` runs, without its folder: `thunar` from `thunar %U`, `et` from `/usr/bin/et %F`.
    pub program: String,
    /// It has `OnlyShowIn=`: some desktops only (`gnome-system-monitor-kde.desktop`).
    pub only_show_in: bool,
}

/// A desktop file's entry when a user sees it (no NoDisplay=true, no Hidden=true).
pub fn desktop_entry(text: &str) -> Option<DesktopEntry> {
    let mut in_entry = false;
    let (mut name, mut program, mut hidden, mut only_show_in) = (None, None, false, false);
    for line in text.lines() {
        let line = line.trim();
        if line.starts_with('[') {
            in_entry = line == "[Desktop Entry]";
            continue;
        }
        if !in_entry {
            continue;
        }
        if let Some(value) = line.strip_prefix("Name=") {
            name.get_or_insert_with(|| clip(value));
        } else if let Some(value) = line.strip_prefix("Exec=") {
            program.get_or_insert_with(|| clip(&exec_program(value)));
        } else if line.starts_with("OnlyShowIn=") {
            only_show_in = true;
        } else if line == "NoDisplay=true" || line == "Hidden=true" {
            hidden = true;
        }
    }
    let name = name.filter(|_| !hidden)?;
    Some(DesktopEntry { name, program: program.unwrap_or_default(), only_show_in })
}

/// The program an `Exec=` line runs, without its folder: past `env` and its `NAME=value` words, and a program in
/// double quotes taken whole.
pub fn exec_program(exec: &str) -> String {
    let mut rest = exec.trim();
    while !rest.is_empty() {
        let (word, after) = match rest.strip_prefix('"') {
            Some(quoted) => quoted.split_once('"').unwrap_or((quoted, "")),
            None => rest.split_once(char::is_whitespace).unwrap_or((rest, "")),
        };
        rest = after.trim_start();
        let program = word.rsplit('/').next().unwrap_or(word);
        if program == "env" || (!word.starts_with('/') && word.contains('=')) {
            continue;
        }
        return program.to_string();
    }
    String::new()
}

/// The entry that names a package, by index: the one whose desktop file is named after the package (`thunar.desktop`,
/// or `org.fcitx.Fcitx5.desktop` for fcitx5), else the one whose Exec runs a program named after the package
/// (`/usr/bin/fcitx5`). Among equals, an entry for every desktop goes before an `OnlyShowIn=` one, then the first.
/// None when no entry is named after the package (wps-office: `wps-office-wps.desktop` runs `/usr/bin/wps`).
pub fn main_entry(package: &str, entries: &[(&str, &DesktopEntry)]) -> Option<usize> {
    let suffix = format!(".{}", package.to_ascii_lowercase());
    entries
        .iter()
        .enumerate()
        .filter_map(|(index, (desktop_id, entry))| {
            let stem = desktop_id.strip_suffix(".desktop").unwrap_or(desktop_id);
            let rank = if stem == package {
                0
            } else if stem.to_ascii_lowercase().ends_with(&suffix) {
                1
            } else if !entry.program.is_empty() && entry.program == package {
                2
            } else {
                return None;
            };
            Some((rank, entry.only_show_in, index))
        })
        .min()
        .map(|(_, _, index)| index)
}

/// `dpkg -S` lines: "pkg: path" or "pkg1, pkg2: path", diversions left out.
pub fn parse_dpkg_search(output: &str) -> BTreeMap<String, String> {
    output
        .lines()
        .filter(|line| !line.starts_with("diversion "))
        .filter_map(|line| line.split_once(": "))
        .filter_map(|(packages, path)| Some((path.trim().to_string(), packages.split(',').next()?.trim().split(':').next()?.to_string())))
        .collect()
}

fn apps(system: &System) -> Vec<App> {
    let mut apps = Vec::new();
    if system.has_any(&["/usr/bin/flatpak"]) {
        let output = system.run("flatpak", &["list", "--system", "--app", "--columns=application,name,version,origin"], TOOL_TIMEOUT);
        for line in output.map(|output| output.stdout).unwrap_or_default().lines() {
            let mut fields = line.split('\t');
            let Some(id) = fields.next().filter(|id| is_flatpak_id(id)) else {
                continue;
            };
            let (name, version, remote) = (fields.next().unwrap_or(""), fields.next().unwrap_or(""), fields.next().unwrap_or(""));
            apps.push(App {
                id: clip(id),
                name: clip(name),
                version: clip(version),
                source: "flatpak".into(),
                package: clip(id),
                licence: flatpak_licence(system, id).unwrap_or_else(|| UNKNOWN.to_string()),
                origin: clip(&flatpak_origin(remote)),
                main: true,
            });
        }
    }
    let visible = visible_entries(system);
    if visible.is_empty() || !system.commands {
        return apps;
    }
    let paths: Vec<&str> = visible.keys().map(String::as_str).collect();
    let mut args = vec!["-S"];
    args.extend(&paths);
    let owners = parse_dpkg_search(&system.run("dpkg", &args, TOOL_TIMEOUT).map(|output| output.stdout).unwrap_or_default());
    let names: Vec<&str> = visible.keys().filter_map(|path| owners.get(path)).map(String::as_str).collect::<std::collections::BTreeSet<_>>().into_iter().collect();
    let mut query = vec!["-W", "-f=${Package}\t${Version}\n"];
    query.extend(&names);
    let versions: BTreeMap<String, String> = system
        .run("dpkg-query", &query, TOOL_TIMEOUT)
        .map(|output| output.stdout)
        .unwrap_or_default()
        .lines()
        .filter_map(|line| line.split_once('\t'))
        .map(|(package, version)| (package.split(':').next().unwrap_or(package).to_string(), version.to_string()))
        .collect();
    let origins = apt_origins(system, &names);
    apps.extend(deb_apps(system, &visible, &owners, &versions, &origins));
    apps
}

/// The visible /usr/share/applications/*.desktop files: path → (desktop id, entry).
pub fn visible_entries(system: &System) -> BTreeMap<String, (String, DesktopEntry)> {
    let mut visible = BTreeMap::new();
    if let Ok(entries) = fs::read_dir(system.path("/usr/share/applications")) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|extension| extension == "desktop") {
                if let Some(found) = fs::read_to_string(&path).ok().as_deref().and_then(desktop_entry) {
                    let desktop_id = entry.file_name().to_string_lossy().into_owned();
                    visible.insert(format!("/usr/share/applications/{desktop_id}"), (desktop_id, found));
                }
            }
        }
    }
    visible
}

/// The deb apps: one entry per visible desktop file a package owns (`owners`: path → package, from `dpkg -S`), with
/// the package's version, origin and licence, and `main` on the entry that names the package.
pub fn deb_apps(system: &System, visible: &BTreeMap<String, (String, DesktopEntry)>, owners: &BTreeMap<String, String>, versions: &BTreeMap<String, String>, origins: &BTreeMap<String, String>) -> Vec<App> {
    // Each package's visible entries, in the order of their paths.
    let mut packages: BTreeMap<&str, Vec<(&str, &DesktopEntry)>> = BTreeMap::new();
    for (path, (desktop_id, entry)) in visible {
        if let Some(package) = owners.get(path) {
            packages.entry(package.as_str()).or_default().push((desktop_id.as_str(), entry));
        }
    }
    let appstream = appstream_licences(system);
    let mut apps = Vec::new();
    for (package, entries) in &packages {
        let main = main_entry(package, entries);
        let licence = deb_licence(system, package, entries, main, &appstream);
        let version = clip(versions.get(*package).map(String::as_str).unwrap_or_default());
        let origin = clip(origins.get(*package).map(String::as_str).unwrap_or(UNKNOWN));
        for (index, (desktop_id, entry)) in entries.iter().enumerate() {
            apps.push(App {
                id: clip(desktop_id),
                name: entry.name.clone(),
                version: version.clone(),
                source: "deb".into(),
                package: clip(package),
                licence: licence.clone(),
                origin: origin.clone(),
                main: main == Some(index),
            });
        }
    }
    apps
}

/// A deb package's licence, the same for each of its entries: what its machine-readable copyright file states for
/// `Files: *` (or in its header); else the AppStream licence of its main entry, its other entries or the package's
/// name; else what its copyright file says otherwise (`copyright_inferred`); else "unknown".
fn deb_licence(system: &System, package: &str, entries: &[(&str, &DesktopEntry)], main: Option<usize>, appstream: &BTreeMap<String, String>) -> String {
    let text = deb_copyright(system, package);
    let mut desktop_ids: Vec<&str> = main.map(|index| entries[index].0).into_iter().collect();
    desktop_ids.extend(entries.iter().map(|(desktop_id, _)| *desktop_id));
    text.as_deref()
        .and_then(copyright_licence)
        .or_else(|| appstream_for_package(appstream, package, &desktop_ids))
        .or_else(|| text.as_deref().and_then(copyright_inferred))
        .map(|licence| clip(&licence))
        .unwrap_or_else(|| UNKNOWN.to_string())
}

/// What `licence` and `origin` say when nothing tells.
pub const UNKNOWN: &str = "unknown";

/// A Flatpak application id: reverse DNS, letters, digits, `_`, `-` and dots.
fn is_flatpak_id(id: &str) -> bool {
    (3..=255).contains(&id.len()) && id.contains('.') && id.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
}

/// The origin of a Flatpak app from its remote's name.
pub fn flatpak_origin(remote: &str) -> String {
    match remote.trim() {
        "flathub" => "flathub".to_string(),
        "" => UNKNOWN.to_string(),
        other => format!("flatpak:{other}"),
    }
}

/// A Flatpak app's licence: the `<project_license>` of its AppStream file.
fn flatpak_licence(system: &System, id: &str) -> Option<String> {
    let base = system.path(&format!("/var/lib/flatpak/app/{id}/current/active/files/share"));
    ["metainfo", "appdata"]
        .iter()
        .flat_map(|folder| ["metainfo.xml", "appdata.xml"].map(|suffix| base.join(folder).join(format!("{id}.{suffix}"))))
        .find_map(|path| fs::read_to_string(path).ok())
        .and_then(|xml| appstream(&xml).0)
}

/// The most of a copyright file the inventory reads (libreoffice's is over 1 MiB; the parts it needs come first).
const MAX_COPYRIGHT: u64 = 2 * 1024 * 1024;

/// A deb package's /usr/share/doc/<package>/copyright, its first 2 MiB; bytes that are not UTF-8 (older files in
/// Latin-1) do not keep it from being read.
fn deb_copyright(system: &System, package: &str) -> Option<String> {
    if package.is_empty() || package.contains('/') || package.starts_with('.') {
        return None;
    }
    let mut data = Vec::new();
    fs::File::open(system.path(&format!("/usr/share/doc/{package}/copyright"))).ok()?.take(MAX_COPYRIGHT).read_to_end(&mut data).ok()?;
    Some(String::from_utf8_lossy(&data).into_owned())
}

/// A field of a copyright file's paragraph: its name in lower case ("" for a line of prose in an older file), the
/// first line of its value, and the whole value with its continuation lines joined by spaces.
type Field = (String, String, String);

/// A copyright file's paragraphs (separated by empty lines) and their fields. A field's name has no spaces, so
/// "Copyright Holders:" or "It was downloaded from http://…" in an older file are prose.
fn paragraphs(text: &str) -> Vec<Vec<Field>> {
    let mut found = Vec::new();
    let mut current: Vec<Field> = Vec::new();
    for line in text.lines() {
        if line.trim().is_empty() {
            if !current.is_empty() {
                found.push(std::mem::take(&mut current));
            }
        } else if line.starts_with(' ') || line.starts_with('\t') {
            if let Some((_, _, whole)) = current.last_mut() {
                whole.push(' ');
                whole.push_str(line.trim());
            }
        } else if let Some((name, value)) = line.split_once(':').filter(|(name, _)| !name.is_empty() && !name.contains(char::is_whitespace)) {
            let value = value.trim().to_string();
            current.push((name.to_ascii_lowercase(), value.clone(), value));
        } else {
            current.push((String::new(), String::new(), line.trim().to_string()));
        }
    }
    if !current.is_empty() {
        found.push(current);
    }
    found
}

fn field<'a>(paragraph: &'a [Field], name: &str) -> Option<&'a Field> {
    paragraph.iter().find(|(key, _, _)| key == name)
}

fn machine_readable(text: &str) -> bool {
    text.lines().next().is_some_and(|first| first.starts_with("Format:") && first.contains("copyright-format/1.0"))
}

/// The licence a machine-readable copyright file (its first line starts with `Format:` and holds
/// `copyright-format/1.0`) states for the whole package: the first line of the `License:` field of the stanza whose
/// `Files:` is `*`, else of its header paragraph. Field names are case-insensitive, and `Files:` may go on over
/// continuation lines ("Files:\n *", as in gnome-system-monitor's file).
pub fn copyright_licence(text: &str) -> Option<String> {
    if !machine_readable(text) {
        return None;
    }
    let paragraphs = paragraphs(text);
    let catch_all = paragraphs.iter().find(|paragraph| field(paragraph, "files").is_some_and(|(_, _, files)| files.split_whitespace().any(|pattern| pattern == "*")));
    let header = || paragraphs.first().filter(|paragraph| field(paragraph, "format").is_some() && field(paragraph, "files").is_none());
    catch_all
        .or_else(header)
        .and_then(|paragraph| field(paragraph, "license"))
        .map(|(_, licence, _)| licence.as_str())
        .filter(|licence| !licence.is_empty())
        .map(clip)
}

/// What a copyright file says of the package's licence when it states none for the whole package (0.3.1). Free
/// software only: a file that speaks of proprietary terms gives None.
/// - Machine-readable without `Files: *`: the most common licence of its `Files:` stanzas, the packaging's
///   (`debian/*`) left out; on a tie, the first (onboard: GPL-3+; mate-desktop: GPL-2+).
/// - Older files, in this order: a `Files: *` stanza in the same form (pavucontrol); the first statement of a GNU
///   licence with its version ("the GNU General Public License (version 2 or later)": GPL-2+); the most common
///   licence of the `License:` fields (xfwm4, xfce4-panel); the first /usr/share/common-licenses file it points to
///   (thunar: GPL); the text of the Apache 2.0, MIT (Expat), ISC, BSD or MPL 2.0 licence.
pub fn copyright_inferred(text: &str) -> Option<String> {
    let paragraphs = paragraphs(text);
    let stanzas: Vec<(&str, &str)> = paragraphs
        .iter()
        .filter_map(|paragraph| {
            let files = field(paragraph, "files").or_else(|| field(paragraph, "file"))?;
            let licence = field(paragraph, "license")?;
            Some((files.2.as_str(), licence.1.as_str()))
        })
        .collect();
    if machine_readable(text) {
        let licences: Vec<&str> = stanzas
            .iter()
            .filter(|(files, licence)| !licence.is_empty() && !files.split_whitespace().all(|pattern| pattern.starts_with("debian/")))
            .map(|(_, licence)| *licence)
            .collect();
        if licences.iter().any(|licence| non_free_name(licence)) {
            return None;
        }
        if let Some(licence) = most_common(&licences) {
            return Some(clip(licence));
        }
    }
    let flat = flatten(text);
    if non_free_text(&flat) {
        return None;
    }
    if let Some((_, licence)) = stanzas.iter().find(|(files, licence)| !licence.is_empty() && files.split_whitespace().any(|pattern| pattern == "*")) {
        return Some(clip(licence));
    }
    if let Some(licence) = gnu_statement(&flat) {
        return Some(licence);
    }
    let fields: Vec<&str> = paragraphs.iter().flatten().filter(|(key, value, _)| key == "license" && known_licence_name(value)).map(|(_, value, _)| value.as_str()).collect();
    if let Some(licence) = most_common(&fields) {
        return Some(clip(licence));
    }
    common_licenses_reference(text).or_else(|| permissive_text(&flat))
}

/// The item that comes most often; on a tie, the one that came first.
fn most_common<'a>(items: &[&'a str]) -> Option<&'a str> {
    let mut counted: Vec<(&str, usize, usize)> = Vec::new();
    for (index, item) in items.iter().enumerate() {
        match counted.iter_mut().find(|(seen, _, _)| seen == item) {
            Some((_, count, _)) => *count += 1,
            None => counted.push((item, 1, index)),
        }
    }
    counted.into_iter().max_by(|a, b| a.1.cmp(&b.1).then(b.2.cmp(&a.2))).map(|(item, _, _)| item)
}

/// A text in lower case, its runs of whitespace as single spaces.
fn flatten(text: &str) -> String {
    text.split_whitespace().collect::<Vec<_>>().join(" ").to_lowercase()
}

/// Whether `word` is in `text` as a word of its own (not inside a longer word).
fn has_word(text: &str, word: &str) -> bool {
    let is_word_char = |c: char| c.is_alphanumeric();
    text.match_indices(word).any(|(at, _)| {
        !text[..at].chars().next_back().is_some_and(is_word_char) && !text[at + word.len()..].chars().next().is_some_and(is_word_char)
    })
}

/// A licence name of a machine-readable file that says the files are not free software.
fn non_free_name(licence: &str) -> bool {
    let lower = licence.to_ascii_lowercase();
    ["proprietary", "non-free", "nonfree", "noncommercial", "non-commercial", "eula", "freeware", "shareware", "all-rights-reserved"].iter().any(|word| lower.contains(word))
}

/// An older copyright file (flattened) that speaks of proprietary terms. The GPL and LGPL texts speak of
/// "proprietary programs", "proprietary applications" and "non-free programs": those do not count.
fn non_free_text(flat: &str) -> bool {
    const WORDS: [&str; 10] = ["end user license agreement", "end-user license agreement", "end user licence agreement", "end-user licence agreement", "eula", "freeware", "shareware", "non-commercial", "noncommercial", "all-rights-reserved"];
    let stated = |word: &str, harmless: &[&str]| {
        flat.match_indices(word).any(|(at, _)| {
            let after = &flat[at + word.len()..];
            !flat[..at].chars().next_back().is_some_and(char::is_alphanumeric)
                && !after.chars().next().is_some_and(char::is_alphanumeric)
                && !harmless.iter().any(|next| after.starts_with(next))
        })
    };
    WORDS.iter().any(|word| has_word(flat, word)) || stated("proprietary", &[" program", " application"]) || stated("non-free", &[" program"]) || stated("nonfree", &[" program"])
}

/// A `License:` value of an older file that names a licence (and not "see below" or the like).
fn known_licence_name(value: &str) -> bool {
    const FAMILIES: [&str; 24] = [
        "gpl", "lgpl", "agpl", "bsd", "mit", "expat", "apache", "mpl", "artistic", "isc", "zlib", "public-domain", "cc0", "cc-by", "x11", "psf", "python", "ofl", "gfdl", "unlicense", "bsl", "boost", "epl", "wtfpl",
    ];
    let lower = value.trim().to_ascii_lowercase();
    FAMILIES.iter().any(|family| lower.starts_with(family))
}

/// The first statement of a GNU licence with its version in a flattened text, as a Debian short name: "GPL-2+" from
/// "the gnu general public license as published by the free software foundation; either version 2 of the license,
/// or (at your option) any later version", "LGPL-2.1+", "GPL-3". A sentence about the Debian packaging does not
/// count; nor does a name without a version ("the complete text of the gnu general public license can be found in
/// /usr/share/common-licenses/gpl-2").
pub fn gnu_statement(flat: &str) -> Option<String> {
    const NAMES: [(&str, &str); 4] = [("gnu lesser general public licen", "LGPL"), ("gnu library general public licen", "LGPL"), ("gnu affero general public licen", "AGPL"), ("gnu general public licen", "GPL")];
    let mut found: Vec<(usize, &str, usize)> = NAMES.iter().flat_map(|(name, family)| flat.match_indices(name).map(move |(at, _)| (at, *family, at + name.len()))).collect();
    found.sort();
    for (at, family, end) in found {
        let start = flat[..at].rfind(". ").map_or(0, |dot| dot + 2);
        let sentence = sentence_from(&flat[end..]);
        if flat[start..at].contains("packaging") || sentence.contains("packaging") {
            continue;
        }
        if let Some((version, later)) = version_in(sentence) {
            return Some(format!("{family}-{version}{}", if later { "+" } else { "" }));
        }
    }
    None
}

/// A flattened text up to the end of its first sentence (a full stop before a space, or the end), at most 300
/// bytes. "2.1" and "inc.," do not end it.
fn sentence_from(text: &str) -> &str {
    let mut end = text.len().min(300);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    let text = &text[..end];
    match text.find(". ") {
        Some(stop) => &text[..stop],
        None => text.strip_suffix('.').unwrap_or(text),
    }
}

/// The licence version a sentence names after a GNU licence's name, and whether later versions may be used:
/// "version 2", "(version 2 or later)", "v3 or later", "either version 2.1 of the license, or (at your option) any
/// later version".
fn version_in(sentence: &str) -> Option<(&'static str, bool)> {
    let mut at = 0;
    for word in sentence.split(' ') {
        let next = (at + word.len() + 1).min(sentence.len());
        let bare = word.trim_start_matches(['(', '[']);
        let number_at = if matches!(bare.trim_end_matches([',', ';', ':']), "version" | "v" | "v.") {
            Some(next)
        } else {
            bare.strip_prefix('v').filter(|rest| rest.starts_with(|c: char| c.is_ascii_digit())).map(|rest| at + word.len() - rest.len())
        };
        at = next;
        let Some(number_at) = number_at else {
            continue;
        };
        let tail = sentence[number_at..].trim_start_matches('(');
        let digits = tail[..tail.find(|c: char| !c.is_ascii_digit() && c != '.').unwrap_or(tail.len())].trim_end_matches('.');
        let version = match digits {
            "1" | "1.0" => "1",
            "2" | "2.0" => "2",
            "2.1" => "2.1",
            "3" | "3.0" => "3",
            _ => continue,
        };
        let after = &tail[digits.len()..];
        let later = after.starts_with('+') || ["or later", "or any later", "any later version", "or newer", "or above", "or higher", "and later"].iter().any(|phrase| after.contains(phrase));
        return Some((version, later));
    }
    None
}

/// The licence of the first /usr/share/common-licenses file a text points to (a licence for programs before one for
/// documentation): "GPL-2" from "can be found in `/usr/share/common-licenses/GPL-2'". Debian's BSD file is the
/// 3-clause licence.
pub fn common_licenses_reference(text: &str) -> Option<String> {
    const KNOWN: [&str; 17] = ["Apache-2.0", "Artistic", "BSD", "CC0-1.0", "GFDL", "GFDL-1.2", "GFDL-1.3", "GPL", "GPL-1", "GPL-2", "GPL-3", "LGPL", "LGPL-2", "LGPL-2.1", "LGPL-3", "MPL-1.1", "MPL-2.0"];
    const MARKER: &str = "/usr/share/common-licenses/";
    let found: Vec<&str> = text
        .match_indices(MARKER)
        .filter_map(|(at, _)| {
            let after = &text[at + MARKER.len()..];
            let name = &after[..after.find(|c: char| !(c.is_ascii_alphanumeric() || c == '.' || c == '-')).unwrap_or(after.len())];
            let name = name.trim_end_matches('.');
            KNOWN.iter().find(|known| known.eq_ignore_ascii_case(name)).map(|known| if *known == "BSD" { "BSD-3-clause" } else { *known })
        })
        .collect();
    found.iter().find(|name| !name.starts_with("GFDL") && !name.starts_with("CC0")).or(found.first()).map(|name| name.to_string())
}

/// The licence whose well-known text a flattened copyright file holds: Apache 2.0, MIT (Debian's Expat), ISC, BSD
/// (2-, 3- or 4-clause) or MPL 2.0.
fn permissive_text(flat: &str) -> Option<String> {
    let any = |phrases: &[&str]| phrases.iter().any(|phrase| flat.contains(phrase));
    let licence = if any(&["apache license, version 2.0", "apache license version 2.0", "apache license 2.0"]) {
        "Apache-2.0"
    } else if any(&["permission is hereby granted, free of charge, to any person obtaining a copy"]) {
        "Expat"
    } else if any(&["permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted", "permission to use, copy, modify, and distribute this software for any purpose with or without fee is hereby granted"]) {
        "ISC"
    } else if any(&["redistribution and use in source and binary forms, with or without modification, are permitted"]) {
        if flat.contains("advertising materials") {
            "BSD-4-clause"
        } else if flat.contains("neither the name") {
            "BSD-3-clause"
        } else {
            "BSD-2-clause"
        }
    } else if any(&["mozilla public license, v. 2.0", "mozilla public license, version 2.0", "mozilla public license version 2.0"]) {
        "MPL-2.0"
    } else {
        return None;
    };
    Some(licence.to_string())
}

/// The text of every `<tag>` (or `<tag attributes>`) element in an XML text, with the five XML entities decoded.
fn elements(xml: &str, tag: &str, attribute: Option<&str>) -> Vec<String> {
    let mut found = Vec::new();
    let open = format!("<{tag}");
    let close = format!("</{tag}>");
    let mut rest = xml;
    while let Some(start) = rest.find(&open) {
        let after = &rest[start + open.len()..];
        let Some(end_of_tag) = after.find('>') else {
            break;
        };
        let attributes = &after[..end_of_tag];
        let name_ends = attributes.is_empty() || attributes.starts_with(char::is_whitespace);
        let body = &after[end_of_tag + 1..];
        let Some(end) = body.find(&close) else {
            break;
        };
        if name_ends && !attributes.ends_with('/') && attribute.is_none_or(|wanted| attributes.contains(wanted)) {
            let text = body[..end].trim().replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&");
            found.push(text);
        }
        rest = &body[end..];
    }
    found
}

/// An AppStream file's `<project_license>`, and the desktop ids it describes: its `<id>` and its
/// `<launchable type="desktop-id">` entries.
pub fn appstream(xml: &str) -> (Option<String>, Vec<String>) {
    let licence = elements(xml, "project_license", None).into_iter().next().filter(|licence| !licence.is_empty());
    let mut ids: Vec<String> = elements(xml, "id", None).into_iter().take(1).collect();
    ids.extend(elements(xml, "launchable", Some("desktop-id")));
    (licence, ids)
}

/// Desktop id or AppStream id → licence, from /usr/share/metainfo and /usr/share/appdata.
fn appstream_licences(system: &System) -> BTreeMap<String, String> {
    let mut licences = BTreeMap::new();
    for folder in ["/usr/share/metainfo", "/usr/share/appdata"] {
        let Ok(entries) = fs::read_dir(system.path(folder)) else {
            continue;
        };
        for entry in entries.flatten() {
            if !entry.file_name().to_string_lossy().ends_with(".xml") {
                continue;
            }
            let Ok(data) = crate::store::read_limited(&entry.path(), 1024 * 1024) else {
                continue;
            };
            let (Some(licence), ids) = appstream(&String::from_utf8_lossy(&data)) else {
                continue;
            };
            for id in ids {
                licences.entry(id).or_insert_with(|| licence.clone());
            }
        }
    }
    licences
}

/// The AppStream licence of a desktop id: a component whose launchable or id is it, or whose id is it without
/// `.desktop`.
pub fn appstream_for(licences: &BTreeMap<String, String>, desktop_id: &str) -> Option<String> {
    licences.get(desktop_id).or_else(|| licences.get(desktop_id.trim_end_matches(".desktop"))).cloned()
}

/// The AppStream licence of a deb package: that of one of its desktop ids, in the order given (its main entry
/// first), else of a component whose id, without `.desktop`, is the package's name or ends with `.<package>`, in any
/// case (`xfce4-power-manager.desktop` for xfce4-power-manager, whose entry is `xfce4-power-manager-settings.desktop`;
/// `org.xfce.Thunar` for thunar).
pub fn appstream_for_package(licences: &BTreeMap<String, String>, package: &str, desktop_ids: &[&str]) -> Option<String> {
    desktop_ids.iter().find_map(|desktop_id| appstream_for(licences, desktop_id)).or_else(|| {
        let wanted = package.to_ascii_lowercase();
        let suffix = format!(".{wanted}");
        licences
            .iter()
            .find(|(id, _)| {
                let id = id.to_ascii_lowercase();
                let id = id.strip_suffix(".desktop").unwrap_or(&id);
                id == wanted || id.ends_with(&suffix)
            })
            .map(|(_, licence)| licence.clone())
    })
}

/// An archive of `apt-cache policy`'s "Package files": its `o=` and `c=`, and the host of its `origin` line.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Archive {
    pub origin: String,
    pub component: String,
    pub host: String,
}

/// The "Package files" part of `apt-cache policy`: (URI, suite/component) → its archive.
pub fn package_files(text: &str) -> BTreeMap<(String, String), Archive> {
    let mut archives = BTreeMap::new();
    let mut current: Option<((String, String), Archive)> = None;
    let mut inside = false;
    for line in text.lines() {
        if line.starts_with("Package files:") {
            inside = true;
            continue;
        }
        if !inside {
            continue;
        }
        if !line.starts_with(' ') {
            break;
        }
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.first().is_some_and(|word| word.parse::<i64>().is_ok()) {
            if let Some((key, archive)) = current.take() {
                archives.insert(key, archive);
            }
            if words.len() >= 3 {
                current = Some(((words[1].to_string(), words[2].to_string()), Archive::default()));
            }
        } else if let Some(release) = line.trim().strip_prefix("release ") {
            if let Some((_, archive)) = current.as_mut() {
                for field in release.split(',') {
                    match field.split_once('=') {
                        Some(("o", value)) => archive.origin = value.to_string(),
                        Some(("c", value)) => archive.component = value.to_string(),
                        _ => {}
                    }
                }
            }
        } else if let Some(host) = line.trim().strip_prefix("origin ") {
            if let Some((_, archive)) = current.as_mut() {
                archive.host = host.trim().to_string();
            }
        }
    }
    if let Some((key, archive)) = current {
        archives.insert(key, archive);
    }
    archives
}

/// Each package's archive, from `apt-cache policy <packages>`: the first source line under the installed version
/// (marked `***`) that is not /var/lib/dpkg/status, as (URI, suite/component). When only /var/lib/dpkg/status has the
/// installed version, an update is waiting or the .deb was installed by hand: the candidate version's archive is the
/// package's then, and None means that no archive has the package (a .deb installed by hand).
pub fn installed_sources(text: &str) -> BTreeMap<String, Option<(String, String)>> {
    struct Version {
        name: String,
        installed: bool,
        source: Option<(String, String)>,
    }
    fn decide(candidate: &Option<String>, versions: &[Version]) -> Option<(String, String)> {
        let installed = versions.iter().find(|version| version.installed)?;
        installed.source.clone().or_else(|| {
            let candidate = candidate.as_deref()?;
            versions.iter().find(|version| version.name == candidate).and_then(|version| version.source.clone())
        })
    }
    let mut sources = BTreeMap::new();
    let mut package: Option<String> = None;
    let mut candidate: Option<String> = None;
    let mut versions: Vec<Version> = Vec::new();
    let mut finish = |package: &mut Option<String>, candidate: &mut Option<String>, versions: &mut Vec<Version>| {
        if let Some(name) = package.take() {
            if versions.iter().any(|version| version.installed) {
                sources.insert(name, decide(candidate, versions));
            }
        }
        *candidate = None;
        versions.clear();
    };
    for line in text.lines() {
        if !line.starts_with(' ') {
            finish(&mut package, &mut candidate, &mut versions);
            package = line.strip_suffix(':').map(|name| name.split(':').next().unwrap_or(name).to_string());
            continue;
        }
        if package.is_none() {
            continue;
        }
        let words: Vec<&str> = line.split_whitespace().collect();
        if let Some(value) = line.trim().strip_prefix("Candidate:") {
            candidate = Some(value.trim().to_string()).filter(|value| value != "(none)");
        } else if let Some(rest) = line.strip_prefix(" *** ") {
            versions.push(Version { name: rest.split_whitespace().next().unwrap_or_default().to_string(), installed: true, source: None });
        } else if line.starts_with("     ") && !line.starts_with("        ") && words.len() == 2 {
            // A version line: "     <version> <priority>", five spaces; a source line has eight.
            versions.push(Version { name: words[0].to_string(), installed: false, source: None });
        } else if line.starts_with("        ") && words.len() >= 3 && words[0].parse::<i64>().is_ok() {
            if let Some(version) = versions.last_mut() {
                version.source.get_or_insert_with(|| (words[1].to_string(), words[2].to_string()));
            }
        }
    }
    finish(&mut package, &mut candidate, &mut versions);
    sources
}

/// The origin name of an installed version's archive (None: only /var/lib/dpkg/status).
pub fn origin_name(source: Option<&(String, String)>, archives: &BTreeMap<(String, String), Archive>) -> String {
    let Some(source) = source else {
        return "local-deb".to_string();
    };
    let host_of = |uri: &str| uri.split("://").nth(1).and_then(|rest| rest.split('/').next()).unwrap_or_default().to_string();
    match archives.get(source) {
        Some(archive) if archive.origin == "Ubuntu" => format!("ubuntu-{}", archive.component),
        Some(archive) if archive.origin == "linuxmint" => "mint".to_string(),
        Some(archive) if archive.origin == "LP-PPA-vietnamlinuxfamily-caram-os" => "caramos-ppa".to_string(),
        Some(archive) if !archive.host.is_empty() => format!("third-party:{}", archive.host),
        _ => format!("third-party:{}", host_of(&source.0)),
    }
}

/// Each package's origin, from one `apt-cache policy` and one `apt-cache policy <packages>`.
fn apt_origins(system: &System, packages: &[&str]) -> BTreeMap<String, String> {
    if packages.is_empty() {
        return BTreeMap::new();
    }
    let Ok(files) = system.check("apt-cache", &["policy"], TOOL_TIMEOUT) else {
        return BTreeMap::new();
    };
    let mut args = vec!["policy"];
    args.extend(packages);
    let Ok(policy) = system.check("apt-cache", &args, TOOL_TIMEOUT) else {
        return BTreeMap::new();
    };
    let archives = package_files(&files);
    installed_sources(&policy).into_iter().map(|(package, source)| (package, origin_name(source.as_ref(), &archives))).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cpu_and_memory() {
        let cpuinfo = "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i5-8250U\nphysical id\t: 0\ncore id\t\t: 0\n\n\
                       processor\t: 1\nmodel name\t: Intel(R) Core(TM) i5-8250U\nphysical id\t: 0\ncore id\t\t: 0\n\n\
                       processor\t: 2\nphysical id\t: 0\ncore id\t\t: 1\n";
        assert_eq!(cpu(cpuinfo), Cpu { model: "Intel(R) Core(TM) i5-8250U".into(), cores: 2, threads: 3 });
        let dmidecode = "Handle 0x1100, DMI type 17, 40 bytes\nMemory Device\n\tSize: 8 GB\n\tLocator: DIMM A1\n\tType: DDR4\n\tSpeed: 3200 MT/s\n\n\
                         Handle 0x1101, DMI type 17, 40 bytes\nMemory Device\n\tSize: No Module Installed\n\tLocator: DIMM A2\n";
        assert_eq!(memory_modules(dmidecode), [Module { size_mb: 8192, kind: "DDR4".into(), speed_mts: 3200, slot: "DIMM A1".into() }]);
        assert_eq!(mem_total_mb("MemTotal:        8022356 kB\n"), 7834);
        assert_eq!(chassis("10"), "laptop");
        assert_eq!(chassis("3"), "desktop");
        assert_eq!(chassis("1"), "other");
    }

    #[test]
    fn disks_and_health() {
        let lsblk = r#"{"blockdevices": [{"name": "nvme0n1", "model": "Samsung SSD 970", "serial": "S1", "size": 512110190592, "rota": false, "tran": "nvme", "type": "disk"},
                                         {"name": "zram0", "size": 1000, "rota": false, "type": "disk"}, {"name": "sr0", "type": "rom"}]}"#;
        let disks = parse_lsblk(lsblk);
        assert_eq!(disks.len(), 1);
        assert_eq!((disks[0].size_gb, disks[0].rotational, disks[0].transport.as_str()), (512, false, "nvme"));
        assert_eq!(smart_health(r#"{"smart_status": {"passed": true}}"#), "ok");
        assert_eq!(smart_health(r#"{"smart_status": {"passed": false}}"#), "failing");
        assert_eq!(smart_health("not json"), "unknown");
    }

    #[test]
    fn batteries_monitors_network_and_apps() {
        let root = crate::testutil::TempDir::new("inventory");
        let bat = root.path().join("sys/class/power_supply/BAT0");
        fs::create_dir_all(&bat).unwrap();
        fs::write(bat.join("energy_full_design"), "45000000\n").unwrap();
        fs::write(bat.join("energy_full"), "38200000\n").unwrap();
        fs::write(bat.join("cycle_count"), "210\n").unwrap();
        assert_eq!(batteries(root.path()), [Battery { name: "BAT0".into(), design_wh: 45.0, full_wh: 38.2, health_pct: 85, cycles: 210 }]);

        let mut edid = vec![0u8; 128];
        edid[54..59].copy_from_slice(&[0, 0, 0, 0xFC, 0]);
        edid[59..72].copy_from_slice(b"DELL P2419H\n ");
        edid[72..77].copy_from_slice(&[0, 0, 0, 0xFF, 0]);
        edid[77..90].copy_from_slice(b"CN0ABC123\n   ");
        assert_eq!(parse_edid(&edid), ("DELL P2419H".to_string(), "CN0ABC123".to_string()));

        let ip = r#"[{"ifname": "lo", "address": "00:00:00:00:00:00"}, {"ifname": "enp3s0", "address": "aa:bb:cc:dd:ee:ff",
                     "addr_info": [{"family": "inet6", "local": "fe80::1"}, {"family": "inet", "local": "192.168.1.20"}]},
                     {"ifname": "docker0", "address": "02:42:00:00:00:01"}]"#;
        let cards = parse_ip_addr(ip, |name| (name != "docker0", false));
        assert_eq!(cards, [Nic { name: "enp3s0".into(), mac: "aa:bb:cc:dd:ee:ff".into(), ipv4: "192.168.1.20".into(), wired: true }]);

        assert_eq!(desktop_entry("[Desktop Entry]\nName=VLC\nName[vi]=VLC\nExec=vlc --started-from-file %U\n"), Some(DesktopEntry { name: "VLC".into(), program: "vlc".into(), only_show_in: false }));
        assert_eq!(desktop_entry("[Desktop Entry]\nName=Helper\nNoDisplay=true\n"), None);
        assert!(desktop_entry("[Desktop Entry]\nName=GNOME System Monitor\nExec=gnome-system-monitor\nOnlyShowIn=KDE;\n").unwrap().only_show_in);
        let owners = parse_dpkg_search("vlc-bin: /usr/share/applications/vlc.desktop\ndiversion by x from: /y\nlibreoffice-writer, libreoffice-core: /usr/share/applications/w.desktop\n");
        assert_eq!(owners["/usr/share/applications/vlc.desktop"], "vlc-bin");
        assert_eq!(owners["/usr/share/applications/w.desktop"], "libreoffice-writer");
    }

    #[test]
    fn licences_from_copyright_and_appstream() {
        let dep5 = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nUpstream-Name: vlc\n\n\
                    Files: debian/*\nCopyright: x\nLicense: GPL-2+\n\nFiles: *\nCopyright: VideoLAN\nlicense: GPL-2+\n The text.\n .\n More.\n\n\
                    Files: modules/*\nLicense: LGPL-2.1+\n";
        assert_eq!(copyright_licence(dep5).as_deref(), Some("GPL-2+"));
        assert_eq!(copyright_licence("This package was debianized by someone.\nLicense: GPL\n"), None, "not machine-readable");
        assert_eq!(copyright_licence("Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\nFiles: src/*\nLicense: MIT\n"), None);
        // gnome-system-monitor 46 (verified on the CaramOS 1.3.10 VM): the patterns of `Files:` on a continuation line.
        let folded = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nComment:\n The text.\n\n\
                      Files:\n *\nCopyright:\n  2001-2018 Free Software Foundation, Inc.\nLicense: GPL-2+\n\n\
                      Files:\n src/legacy/gsm_color_button.*\nLicense: GPL-2+\n";
        assert_eq!(copyright_licence(folded).as_deref(), Some("GPL-2+"));
        let folded_other = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\n\nFiles:\n src/*\n data/*\nLicense: MIT\n";
        assert_eq!(copyright_licence(folded_other), None, "no catch-all stanza");
        let xml = r#"<?xml version="1.0"?><component type="desktop-application"><id>org.videolan.vlc</id>
                     <metadata_license>CC0-1.0</metadata_license><project_license>GPL-2.0+ AND LGPL-2.1+</project_license>
                     <launchable type="desktop-id">vlc.desktop</launchable><provides><id>x</id></provides></component>"#;
        let (licence, ids) = appstream(xml);
        assert_eq!(licence.as_deref(), Some("GPL-2.0+ AND LGPL-2.1+"));
        assert_eq!(ids, ["org.videolan.vlc", "vlc.desktop"]);
        let licences = BTreeMap::from([("vlc.desktop".to_string(), "GPL-2.0+".to_string()), ("org.gnome.Calculator".to_string(), "GPL-3.0+".to_string())]);
        assert_eq!(appstream_for(&licences, "vlc.desktop").as_deref(), Some("GPL-2.0+"));
        assert_eq!(appstream_for(&licences, "org.gnome.Calculator.desktop").as_deref(), Some("GPL-3.0+"));
        assert_eq!(appstream_for(&licences, "nemo.desktop"), None);
        assert_eq!(flatpak_origin("flathub"), "flathub");
        assert_eq!(flatpak_origin("fedora"), "flatpak:fedora");
        assert!(is_flatpak_id("org.libreoffice.LibreOffice") && !is_flatpak_id("../x") && !is_flatpak_id("Application ID"));
    }

    #[test]
    fn the_entry_that_names_a_package() {
        assert_eq!(exec_program("thunar %U"), "thunar");
        assert_eq!(exec_program("/usr/bin/et %F"), "et");
        assert_eq!(exec_program("env WEBKIT_DISABLE_COMPOSITING_MODE=1 cinnamon-settings"), "cinnamon-settings");
        assert_eq!(exec_program("\"/opt/My App/my-app\" %U"), "my-app");
        assert_eq!(exec_program("LANG=C xfce4-terminal"), "xfce4-terminal");
        assert_eq!(exec_program(""), "");
        let entry = |name: &str, program: &str| DesktopEntry { name: name.into(), program: program.into(), only_show_in: false };
        // Seen on CaramOS 1.5.0 (Xfce): 0.3.0 named thunar after its first entry, "Bulk Rename".
        let (bulk, thunar) = (entry("Bulk Rename", "thunar"), entry("Thunar File Manager", "thunar"));
        assert_eq!(main_entry("thunar", &[("thunar-bulk-rename.desktop", &bulk), ("thunar.desktop", &thunar)]), Some(1));
        // WPS Office: five entries, none named after wps-office and none running it.
        let wps: Vec<DesktopEntry> = [("WPS Spreadsheets", "et"), ("WPS PDF", "wpspdf"), ("WPS Office", "wps"), ("WPS Presentation", "wpp"), ("WPS Writer", "wps")].iter().map(|(name, program)| entry(name, program)).collect();
        let ids = ["wps-office-et.desktop", "wps-office-pdf.desktop", "wps-office-prometheus.desktop", "wps-office-wpp.desktop", "wps-office-wps.desktop"];
        let wps_entries: Vec<(&str, &DesktopEntry)> = ids.iter().copied().zip(wps.iter()).collect();
        assert_eq!(main_entry("wps-office", &wps_entries), None);
        // A reverse-DNS desktop id, in another case; an Exec named after the package.
        let (configtool, fcitx) = (entry("Fcitx 5 Configuration", "fcitx5-configtool"), entry("Fcitx 5", "fcitx5"));
        assert_eq!(main_entry("fcitx5", &[("fcitx5-configtool.desktop", &configtool), ("org.fcitx.Fcitx5.desktop", &fcitx)]), Some(1));
        let (manager, settings) = (entry("Bluetooth Manager", "blueman-manager"), entry("Session and Startup", "xfce4-session-settings"));
        assert_eq!(main_entry("blueman", &[("blueman-manager.desktop", &manager)]), None);
        assert_eq!(main_entry("xfce4-session", &[("xfce-session-settings.desktop", &settings)]), None);
        // Both run gnome-system-monitor: the one for every desktop wins over OnlyShowIn=KDE.
        let kde = DesktopEntry { only_show_in: true, ..entry("GNOME System Monitor", "gnome-system-monitor") };
        let monitor = entry("System Monitor", "gnome-system-monitor");
        assert_eq!(main_entry("gnome-system-monitor", &[("gnome-system-monitor-kde.desktop", &kde), ("org.gnome.SystemMonitor.desktop", &monitor)]), Some(1));
    }

    #[test]
    fn licences_of_older_copyright_files() {
        let inferred = |text: &str| copyright_inferred(text);
        // A GNU licence stated with its version wins over the files it points to.
        assert_eq!(inferred("This package was debianized by someone.\n\nYou are free to distribute this software under the terms of\nthe GNU General Public License (version 2 or later).\nOn Debian systems, the complete text of the GNU General Public\nLicense can be found in the file `/usr/share/common-licenses/GPL'\n").as_deref(), Some("GPL-2+"));
        assert_eq!(inferred("Copyright: 2010 X\n\nThis library is free software; you can redistribute it and/or\nmodify it under the terms of the GNU Lesser General Public\nLicense as published by the Free Software Foundation; either\nversion 2.1 of the License, or (at your option) any later version.\n").as_deref(), Some("LGPL-2.1+"));
        assert_eq!(inferred("It is licensed under the GNU General Public License v3 or later.\n").as_deref(), Some("GPL-3+"));
        assert_eq!(inferred("This program is free software: you can redistribute it under the terms of the GNU General Public License, version 3.\n").as_deref(), Some("GPL-3"));
        assert_eq!(inferred("Licensed under the GNU Library General Public License version 2.\n").as_deref(), Some("LGPL-2"));
        // Only a pointer to /usr/share/common-licenses; a licence for programs before one for documentation.
        assert_eq!(inferred("Upstream: x\n\nOn Debian systems, see /usr/share/common-licenses/GPL-2.\n").as_deref(), Some("GPL-2"));
        assert_eq!(inferred("Docs: /usr/share/common-licenses/GFDL-1.2, code: /usr/share/common-licenses/LGPL-2.1\n").as_deref(), Some("LGPL-2.1"));
        assert_eq!(inferred("See `/usr/share/common-licenses/BSD'.\n").as_deref(), Some("BSD-3-clause"));
        assert_eq!(inferred("The manual is in /usr/share/common-licenses/GFDL-1.3.\n").as_deref(), Some("GFDL-1.3"));
        // A sentence about the Debian packaging does not name the package's licence.
        assert_eq!(inferred("The Debian packaging is licensed under the GNU General Public License version 2 or later.\n\nPermission is hereby granted, free of charge, to any person obtaining a copy of this software, to deal in the Software without restriction.\n").as_deref(), Some("Expat"));
        // The permissive licences by their text.
        let bsd = "Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:\n1. Redistributions of source code must retain the above copyright notice.\n2. Redistributions in binary form must reproduce the above copyright notice.\n";
        assert_eq!(inferred(bsd).as_deref(), Some("BSD-2-clause"));
        assert_eq!(inferred(&format!("{bsd}3. Neither the name of the author nor the names of its contributors may be used to endorse products.\n")).as_deref(), Some("BSD-3-clause"));
        assert_eq!(inferred("Licensed under the Apache License, Version 2.0 (the \"License\");\n").as_deref(), Some("Apache-2.0"));
        assert_eq!(inferred("Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted.\n").as_deref(), Some("ISC"));
        assert_eq!(inferred("This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.\n").as_deref(), Some("MPL-2.0"));
        // Nothing reliable: unknown.
        assert_eq!(inferred("Copyright 2024 Example Ltd. All rights reserved.\n"), None);
        assert_eq!(inferred("This package was debianized by someone.\nLicense: see the website\n"), None);
        assert_eq!(inferred("The GNU General Public License can be found in the source tarball.\n"), None, "a name without a version or a file");
        assert_eq!(inferred(""), None);
        // Proprietary terms make it unknown, whatever free licence a bundled part has; the GPL's own words do not.
        assert_eq!(inferred("Example Viewer is proprietary software of Example Ltd.\nIt includes zlib, see /usr/share/common-licenses/GPL-2.\n"), None);
        assert_eq!(inferred("Use of this software is governed by the End User License Agreement.\nThe GNU General Public License version 2 applies to the bundled libfoo.\n"), None);
        assert_eq!(inferred("Distributed as freeware.\n/usr/share/common-licenses/GPL\n"), None);
        assert_eq!(inferred("Under the GNU General Public License version 2. This General Public License does not permit incorporating your program into proprietary programs.\n").as_deref(), Some("GPL-2"));
        assert_eq!(inferred("Under the GNU Lesser General Public License version 2.1, which permits linking those libraries into non-free programs.\n").as_deref(), Some("LGPL-2.1"));
    }

    #[test]
    fn licences_of_machine_readable_files_without_a_catch_all() {
        let format = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nUpstream-Name: x\n\n";
        // The most common licence of the stanzas, the packaging's left out; a tie goes to the first.
        let text = format!("{format}Files: src/a.c\nLicense: LGPL-2+\n\nFiles: src/b.c\nLicense: GPL-2+\n\nFiles: tools/*\nLicense: GPL-2+\n\nFiles: debian/*\nLicense: Expat\n\nFiles: debian/patches/*\n debian/rules\nLicense: Expat\n\nFiles: po/*\nLicense: LGPL-2+\n\nLicense: GPL-2+\n The text.\n");
        assert_eq!(copyright_licence(&text), None);
        assert_eq!(copyright_inferred(&text).as_deref(), Some("LGPL-2+"), "LGPL-2+ and GPL-2+ twice each; LGPL-2+ came first");
        let more = format!("{format}Files: src/a.c\nLicense: LGPL-2+\n\nFiles: src/b.c\nLicense: GPL-2+\n\nFiles: tools/*\nLicense: GPL-2+\n");
        assert_eq!(copyright_inferred(&more).as_deref(), Some("GPL-2+"));
        // A stanza with proprietary files makes the package unknown.
        let firmware = format!("{format}Files: src/*\nLicense: GPL-2+\n\nFiles: src/more/*\nLicense: GPL-2+\n\nFiles: firmware/*\nLicense: proprietary\n");
        assert_eq!(copyright_inferred(&firmware), None);
        // The header paragraph's License is the package's (copyright-format 1.0).
        let header = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nUpstream-Name: x\nLicense: MPL-2.0\n\nFiles: src/*\nLicense: MPL-2.0\n";
        assert_eq!(copyright_licence(header).as_deref(), Some("MPL-2.0"));
        // `Files: *` wins over the header, as in 0.3.0.
        let both = "Format: https://www.debian.org/doc/packaging-manuals/copyright-format/1.0/\nLicense: GPL-2+\n\nFiles: *\nLicense: GPL-3+\n";
        assert_eq!(copyright_licence(both).as_deref(), Some("GPL-3+"));
    }

    #[test]
    fn the_deb_apps_of_a_package_share_its_licence() {
        let root = crate::testutil::TempDir::new("deb-apps");
        let system = System::test(root.path());
        let write = |path: &str, text: &str| {
            let path = system.path(path);
            fs::create_dir_all(path.parent().unwrap()).unwrap();
            fs::write(path, text).unwrap();
        };
        write("/usr/share/applications/thunar.desktop", "[Desktop Entry]\nName=Thunar File Manager\nExec=thunar %U\n");
        write("/usr/share/applications/thunar-bulk-rename.desktop", "[Desktop Entry]\nName=Bulk Rename\nExec=thunar --bulk-rename %F\n");
        write("/usr/share/applications/thunar-settings.desktop", "[Desktop Entry]\nName=File Manager Settings\nExec=thunar-settings\nNoDisplay=true\n");
        // Its AppStream id is org.xfce.Thunar, not the desktop id: found through the package's name.
        write("/usr/share/metainfo/org.xfce.thunar.appdata.xml", "<component type=\"desktop\"><id type=\"desktop\">org.xfce.Thunar</id><project_license>GPL-2.0</project_license></component>");
        write("/usr/share/doc/thunar/copyright", "This package was debianized by someone.\n\nOn Debian systems, the complete text of the GNU General Public\nLicense can be found in the file `/usr/share/common-licenses/GPL'\n");
        write("/usr/share/applications/xfce4-power-manager-settings.desktop", "[Desktop Entry]\nName=Power Manager\nExec=xfce4-power-manager-settings\n");
        write("/usr/share/doc/xfce4-power-manager/copyright", "This package was debianized by someone.\n\nYou are free to distribute this software under the terms of\nthe GNU General Public License (version 2 or later).\n");
        // Latin-1 bytes in an older file: read all the same.
        let mut latin1 = b"Copyright \xa9 2006 Andr\xe9\n\nThe GNU General Public License, version 2 or any later version, applies.\n".to_vec();
        latin1.extend_from_slice(b"\n");
        let path = system.path("/usr/share/doc/xfce4-dict/copyright");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, latin1).unwrap();
        write("/usr/share/applications/xfce4-dict.desktop", "[Desktop Entry]\nName=Dictionary\nExec=xfce4-dict\n");
        write("/usr/share/applications/wps-office-wps.desktop", "[Desktop Entry]\nName=WPS Writer\nExec=/usr/bin/wps %U\n");
        write("/usr/share/applications/wps-office-et.desktop", "[Desktop Entry]\nName=WPS Spreadsheets\nExec=/usr/bin/et %F\n");
        write("/usr/share/applications/handmade.desktop", "[Desktop Entry]\nName=Made by hand\nExec=handmade\n");
        let visible = visible_entries(&system);
        assert_eq!(visible.len(), 7, "thunar-settings.desktop is hidden");
        let owners: BTreeMap<String, String> = [
            ("thunar.desktop", "thunar"),
            ("thunar-bulk-rename.desktop", "thunar"),
            ("xfce4-power-manager-settings.desktop", "xfce4-power-manager"),
            ("xfce4-dict.desktop", "xfce4-dict"),
            ("wps-office-wps.desktop", "wps-office"),
            ("wps-office-et.desktop", "wps-office"),
        ]
        .iter()
        .map(|(id, package)| (format!("/usr/share/applications/{id}"), package.to_string()))
        .collect();
        let versions = BTreeMap::from([("thunar".to_string(), "4.18.8-1".to_string())]);
        let origins = BTreeMap::from([("wps-office".to_string(), "local-deb".to_string())]);
        let apps = deb_apps(&system, &visible, &owners, &versions, &origins);
        let found: Vec<(&str, &str, &str, bool)> = apps.iter().map(|app| (app.id.as_str(), app.package.as_str(), app.licence.as_str(), app.main)).collect();
        assert_eq!(
            found,
            [
                ("thunar-bulk-rename.desktop", "thunar", "GPL-2.0", false),
                ("thunar.desktop", "thunar", "GPL-2.0", true),
                ("wps-office-et.desktop", "wps-office", "unknown", false),
                ("wps-office-wps.desktop", "wps-office", "unknown", false),
                ("xfce4-dict.desktop", "xfce4-dict", "GPL-2+", true),
                ("xfce4-power-manager-settings.desktop", "xfce4-power-manager", "GPL-2+", false),
            ],
            "the desktop file that no package owns is left out"
        );
        assert_eq!((apps[0].version.as_str(), apps[0].origin.as_str(), apps[2].origin.as_str()), ("4.18.8-1", UNKNOWN, "local-deb"));
        assert_eq!(appstream_for_package(&BTreeMap::from([("xfce4-power-manager.desktop".to_string(), "GPL-2.0+".to_string())]), "xfce4-power-manager", &["xfce4-power-manager-settings.desktop"]).as_deref(), Some("GPL-2.0+"));
        assert_eq!(appstream_for_package(&BTreeMap::from([("org.example.xfce4-dict-helper".to_string(), "MIT".to_string())]), "dict", &[]), None, "a dot must come before the package's name");
    }

    #[test]
    fn an_update_waiting_keeps_the_archive() {
        // Seen on a CaramOS 1.3.10 machine: the installed Firefox is no longer in Mint's archive, which has a newer one;
        // Ubuntu's transitional package (epoch 1) is listed first but is not the candidate.
        let policy = "firefox:\n  Installed: 146.0.1+linuxmint1+zena\n  Candidate: 160.0.1+linuxmint1\n  Version table:\n\
                      \x20    1:1snap1-0ubuntu5 500\n        500 http://archive.ubuntu.com/ubuntu noble/main amd64 Packages\n\
                      \x20    160.0.1+linuxmint1 700\n        700 http://packages.linuxmint.com zena/upstream amd64 Packages\n\
                      \x20*** 146.0.1+linuxmint1+zena 100\n        100 /var/lib/dpkg/status\n\
                      handmade:\n  Installed: 1.0\n  Candidate: 1.0\n  Version table:\n *** 1.0 100\n        100 /var/lib/dpkg/status\n\
                      gone:\n  Installed: (none)\n  Candidate: 2.0\n  Version table:\n     2.0 500\n        500 http://x.example/ubuntu noble/main amd64 Packages\n";
        let sources = installed_sources(policy);
        assert_eq!(sources["firefox"], Some(("http://packages.linuxmint.com".to_string(), "zena/upstream".to_string())));
        assert_eq!(sources["handmade"], None);
        assert!(!sources.contains_key("gone"), "not installed");
    }

    #[test]
    fn hash_covers_the_body_only() {
        let body = Body { cpu: Cpu { model: "x".into(), cores: 1, threads: 2 }, ..Body::default() };
        let one = Inventory { collected: "a".into(), hash: body.hash(), body: body.clone() };
        let two = Inventory { collected: "b".into(), hash: body.hash(), body };
        assert_eq!(one.hash, two.hash);
        let json = serde_json::to_value(&one).unwrap();
        assert_eq!(json["cpu"]["threads"], 2);
        assert!(json.get("body").is_none());
        assert_eq!(json["memory"]["modules"], serde_json::json!([]));
    }
}
