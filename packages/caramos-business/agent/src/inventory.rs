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
//! Strings are at most 200 characters, lists at most 500 items, and the body at most 1 MiB.

use std::collections::BTreeMap;
use std::fs;
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

/// A desktop file's Name and whether a user sees it (no NoDisplay=true, no Hidden=true).
pub fn desktop_entry(text: &str) -> Option<String> {
    let mut in_entry = false;
    let (mut name, mut hidden) = (None, false);
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
        } else if line == "NoDisplay=true" || line == "Hidden=true" {
            hidden = true;
        }
    }
    name.filter(|_| !hidden)
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
            });
        }
    }
    let folder = system.path("/usr/share/applications");
    // Desktop file path → (desktop id, name).
    let mut visible: BTreeMap<String, (String, String)> = BTreeMap::new();
    if let Ok(entries) = fs::read_dir(&folder) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().is_some_and(|extension| extension == "desktop") {
                if let Some(name) = fs::read_to_string(&path).ok().as_deref().and_then(desktop_entry) {
                    let desktop_id = entry.file_name().to_string_lossy().into_owned();
                    visible.insert(format!("/usr/share/applications/{desktop_id}"), (desktop_id, name));
                }
            }
        }
    }
    if visible.is_empty() || !system.commands {
        return apps;
    }
    let paths: Vec<&str> = visible.keys().map(String::as_str).collect();
    let mut args = vec!["-S"];
    args.extend(&paths);
    let owners = parse_dpkg_search(&system.run("dpkg", &args, TOOL_TIMEOUT).map(|output| output.stdout).unwrap_or_default());
    let packages: std::collections::BTreeSet<&String> = visible.keys().filter_map(|path| owners.get(path)).collect();
    let mut query = vec!["-W", "-f=${Package}\t${Version}\n"];
    query.extend(packages.iter().map(|package| package.as_str()));
    let versions: BTreeMap<String, String> = system
        .run("dpkg-query", &query, TOOL_TIMEOUT)
        .map(|output| output.stdout)
        .unwrap_or_default()
        .lines()
        .filter_map(|line| line.split_once('\t'))
        .map(|(package, version)| (package.split(':').next().unwrap_or(package).to_string(), version.to_string()))
        .collect();
    let origins = apt_origins(system, &packages.iter().map(|package| package.as_str()).collect::<Vec<_>>());
    let appstream = appstream_licences(system);
    let mut copyright: BTreeMap<String, Option<String>> = BTreeMap::new();
    for (path, (desktop_id, name)) in &visible {
        let Some(package) = owners.get(path) else {
            continue;
        };
        let stated = copyright.entry(package.clone()).or_insert_with(|| deb_copyright_licence(system, package)).clone();
        let licence = stated.or_else(|| appstream_for(&appstream, desktop_id)).unwrap_or_else(|| UNKNOWN.to_string());
        apps.push(App {
            id: clip(desktop_id),
            name: name.clone(),
            version: clip(versions.get(package).map(String::as_str).unwrap_or_default()),
            source: "deb".into(),
            package: clip(package),
            licence: clip(&licence),
            origin: clip(origins.get(package).map(String::as_str).unwrap_or(UNKNOWN)),
        });
    }
    apps
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

/// The licence of a deb package's machine-readable copyright file, for `Files: *`.
fn deb_copyright_licence(system: &System, package: &str) -> Option<String> {
    if package.is_empty() || package.contains('/') || package.starts_with('.') {
        return None;
    }
    let text = fs::read_to_string(system.path(&format!("/usr/share/doc/{package}/copyright"))).ok()?;
    copyright_licence(&text)
}

/// The first line of the `License:` field of the stanza whose `Files:` is `*`, in a machine-readable copyright file
/// (its first line starts with `Format:` and holds `copyright-format/1.0`). Field names are case-insensitive.
pub fn copyright_licence(text: &str) -> Option<String> {
    let first = text.lines().next()?;
    if !first.starts_with("Format:") || !first.contains("copyright-format/1.0") {
        return None;
    }
    let mut files: Option<String> = None;
    let mut licence: Option<String> = None;
    let mut last_key = String::new();
    for line in text.lines().chain(std::iter::once("")) {
        if line.trim().is_empty() {
            // `Files:` holds whitespace-separated patterns, which may go on continuation lines ("Files:\n *", as in
            // gnome-system-monitor's file).
            if files.as_deref().is_some_and(|files| files.split_whitespace().any(|pattern| pattern == "*")) {
                return licence.filter(|licence| !licence.is_empty()).map(|licence| clip(&licence));
            }
            files = None;
            licence = None;
            last_key.clear();
            continue;
        }
        if line.starts_with(' ') || line.starts_with('\t') {
            if last_key == "files" {
                if let Some(files) = files.as_mut() {
                    files.push(' ');
                    files.push_str(line.trim());
                }
            }
            continue;
        }
        if let Some((key, value)) = line.split_once(':') {
            last_key = key.trim().to_ascii_lowercase();
            match last_key.as_str() {
                "files" => files = Some(value.trim().to_string()),
                "license" => licence = Some(value.trim().to_string()),
                _ => {}
            }
        }
    }
    None
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

        assert_eq!(desktop_entry("[Desktop Entry]\nName=VLC\nName[vi]=VLC\nExec=vlc\n"), Some("VLC".into()));
        assert_eq!(desktop_entry("[Desktop Entry]\nName=Helper\nNoDisplay=true\n"), None);
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
