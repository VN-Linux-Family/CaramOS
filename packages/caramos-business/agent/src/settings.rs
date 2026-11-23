//! The settings sections of policy format 2 (PROTOCOL.md part 2, "Settings sections"): their types and limits, and a
//! machine's effective settings.
//!
//! A section may appear in three layers: the policy's `settings`, the machine's department's, and the machine's own.
//! Every layer's sections are checked, so that an invalid section makes the whole policy invalid, as the admin checks
//! before signing. Unknown keys inside a section, and unknown sections, are ignored.

use std::collections::{BTreeMap, BTreeSet};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::policy::{check_share, FileEntry, Folders, MonthDay, PolicyError, Wallpaper, MAX_NAME_CHARS, MAX_PERIODS};

/// The sections this agent applies, in the order the health report lists them.
pub const SECTIONS: [&str; 13] = [
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
    "wifi",
    "shared",
    "snapshots",
];

const MAX_SHARES: usize = 20;
const MAX_BOOKMARKS: usize = 50;
const MAX_BLOCKED: usize = 500;
const MAX_RANGES: usize = 6;
const MAX_PRINTERS: usize = 20;
const MAX_APPS: usize = 50;
const MAX_WIFI: usize = 10;

fn refuse<T>(message: impl Into<String>) -> Result<T, PolicyError> {
    Err(PolicyError(message.into()))
}

/// `shares`: a folder of the company's server shown in the file manager (GTK bookmarks).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShareLink {
    pub name: String,
    pub url: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Bookmark {
    pub name: String,
    pub url: String,
}

/// `browser.block_hours`: blocking only inside the ranges, on those ISO weekdays (1 = Monday).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Hours {
    pub days: Vec<u8>,
    pub ranges: Vec<[String; 2]>,
}

impl Hours {
    /// Whether `weekday` (1-7) at `minute` of the day (0-1439) is inside a range, start included, end excluded.
    pub fn contains(&self, weekday: u8, minute: u32) -> bool {
        self.days.contains(&weekday)
            && self.ranges.iter().any(|[from, to]| match (hhmm(from), hhmm(to)) {
                (Ok(from), Ok(to)) => from <= minute && minute < to,
                _ => false,
            })
    }
}

/// `browser`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Browser {
    #[serde(default)]
    pub homepage: Option<String>,
    #[serde(default)]
    pub bookmarks: Vec<Bookmark>,
    #[serde(default)]
    pub block: Vec<String>,
    /// None blocks all the time.
    #[serde(default)]
    pub block_hours: Option<Hours>,
    #[serde(default)]
    pub safe_search: bool,
}

/// `printers`: one IPP queue.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Printer {
    pub name: String,
    pub uri: String,
    #[serde(default)]
    pub location: String,
    #[serde(default)]
    pub default: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Laptops {
    Skip,
    Suspend,
    Same,
}

/// `power.shutdown`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Shutdown {
    pub days: Vec<u8>,
    pub time: String,
    #[serde(default = "default_warn")]
    pub warn_minutes: u32,
    #[serde(default = "default_postpone")]
    pub postpone_minutes: u32,
    #[serde(default = "default_max_postpones")]
    pub max_postpones: u32,
    #[serde(default = "default_laptops")]
    pub laptops: Laptops,
}

fn default_warn() -> u32 {
    10
}

fn default_postpone() -> u32 {
    30
}

fn default_max_postpones() -> u32 {
    2
}

fn default_laptops() -> Laptops {
    Laptops::Skip
}

/// `power.wake`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Wake {
    pub days: Vec<u8>,
    pub time: String,
}

/// `power`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Power {
    #[serde(default)]
    pub shutdown: Option<Shutdown>,
    #[serde(default)]
    pub wake: Option<Wake>,
}

/// `apps`: App Center catalogue ids.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Apps {
    #[serde(default)]
    pub required: Vec<String>,
    #[serde(default)]
    pub forbidden: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum UsbStorage {
    Allow,
    ReadOnly,
    Block,
}

/// `usb`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Usb {
    pub storage: UsbStorage,
}

/// `screen_lock`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ScreenLock {
    pub idle_minutes: u32,
    #[serde(default)]
    pub on_suspend: bool,
}

/// `firewall`: only `true` is managed; turning the firewall off is not offered.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Firewall {
    #[serde(default)]
    pub enabled: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum WifiSecurity {
    WpaPsk,
    Open,
}

/// `inventory`: the detailed inventory is sent only while this is on (PROTOCOL.md part 2 "Everything is opt-in").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InventorySection {
    pub enabled: bool,
}

/// `wifi`: one network; a `wpa-psk` network's passphrase is in the machine's sealed secrets.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Wifi {
    pub ssid: String,
    pub security: WifiSecurity,
    #[serde(default)]
    pub hidden: bool,
}

/// `shared.maintenance`: when a frozen machine boots once without the freeze to take its updates (PROTOCOL.md part 3
/// "Maintenance window").
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Maintenance {
    pub days: Vec<u8>,
    pub time: String,
    #[serde(default = "default_max_minutes")]
    pub max_minutes: u32,
}

fn default_max_minutes() -> u32 {
    60
}

/// `shared` (PROTOCOL.md part 3 "Shared machines"): a guest session on the login screen, and the freeze that undoes every
/// change at reboot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Shared {
    #[serde(default)]
    pub guest: bool,
    #[serde(default)]
    pub freeze: bool,
    /// None: a frozen machine is never updated.
    #[serde(default)]
    pub maintenance: Option<Maintenance>,
    /// The admin's "Tôi hiểu" for freezing a machine with less than 3 GiB of RAM.
    #[serde(default)]
    pub low_memory_ok: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Schedule {
    Daily,
    Weekly,
    Monthly,
}

impl Schedule {
    pub fn as_str(self) -> &'static str {
        match self {
            Schedule::Daily => "daily",
            Schedule::Weekly => "weekly",
            Schedule::Monthly => "monthly",
        }
    }
}

/// `snapshots` (PROTOCOL.md part 3 "Managed snapshots"): Timeshift's schedule.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Snapshots {
    pub schedule: Schedule,
    pub keep: u32,
    #[serde(default)]
    pub before_update: bool,
}

/// `HH:MM`, 24-hour, as minutes of the day.
pub fn hhmm(text: &str) -> Result<u32, PolicyError> {
    let bytes = text.as_bytes();
    let digit = |index: usize| bytes.get(index).filter(|byte| byte.is_ascii_digit()).map(|byte| u32::from(byte - b'0'));
    if bytes.len() == 5 && bytes[2] == b':' {
        if let (Some(h1), Some(h2), Some(m1), Some(m2)) = (digit(0), digit(1), digit(3), digit(4)) {
            let (hour, minute) = (h1 * 10 + h2, m1 * 10 + m2);
            if hour < 24 && minute < 60 {
                return Ok(hour * 60 + minute);
            }
        }
    }
    refuse(format!("{text:?} is not a time written HH:MM"))
}

fn check_days(days: &[u8], what: &str) -> Result<(), PolicyError> {
    if let Some(day) = days.iter().find(|day| !(1..=7).contains(*day)) {
        return refuse(format!("{what}: {day} is not an ISO weekday (1 = Monday to 7)"));
    }
    Ok(())
}

fn check_name(name: &str, what: &str) -> Result<(), PolicyError> {
    if name.chars().count() > MAX_NAME_CHARS {
        return refuse(format!("{what}: a name is longer than {MAX_NAME_CHARS} characters"));
    }
    Ok(())
}

/// An `http://` or `https://` URL with a host, and no spaces or control characters.
pub fn is_http_url(url: &str) -> bool {
    let Some(rest) = url.strip_prefix("https://").or_else(|| url.strip_prefix("http://")) else {
        return false;
    };
    let host = rest.split(['/', '?', '#']).next().unwrap_or_default();
    let host = host.rsplit_once('@').map_or(host, |(_, host)| host);
    let host = host.split(':').next().unwrap_or_default();
    !host.is_empty() && !url.chars().any(|c| c.is_whitespace() || c.is_control())
}

/// A domain to block: `[a-z0-9.-]`, lower case, no scheme, no path.
pub fn is_block_domain(domain: &str) -> bool {
    (1..=253).contains(&domain.len())
        && domain.bytes().all(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9' | b'.' | b'-'))
}

/// An App Center catalogue id, `[a-z0-9-]{1,40}`.
pub fn is_app_id(id: &str) -> bool {
    (1..=40).contains(&id.len()) && id.bytes().all(|byte| matches!(byte, b'a'..=b'z' | b'0'..=b'9' | b'-'))
}

/// `ipp://` or `ipps://` with a host and no `@`.
pub fn is_printer_uri(uri: &str) -> bool {
    let Some(rest) = uri.strip_prefix("ipps://").or_else(|| uri.strip_prefix("ipp://")) else {
        return false;
    };
    let host = rest.split(['/', '?', '#']).next().unwrap_or_default();
    let host = host.strip_prefix('[').map_or_else(|| host.split(':').next().unwrap_or_default(), |v6| v6);
    !host.is_empty() && !uri.contains('@') && !uri.chars().any(|c| c.is_whitespace() || c.is_control())
}

fn parse<T: DeserializeOwned>(name: &str, value: &Value) -> Result<T, PolicyError> {
    serde_json::from_value(value.clone()).map_err(|error| PolicyError(format!("section {name}: {error}")))
}

/// Checks one layer (`settings`, a department's or a machine's): every section present and not null. `files` is the
/// policy's, which must list every image a wallpaper uses.
pub fn check_layer(layer: &Map<String, Value>, files: &BTreeMap<String, FileEntry>, where_: &str) -> Result<(), PolicyError> {
    for (name, value) in layer {
        if value.is_null() {
            continue;
        }
        check_section(name, value, files).map_err(|error| PolicyError(format!("{where_}: {}", error.0)))?;
    }
    Ok(())
}

/// Checks one section's value against the limits of the table.
pub fn check_section(name: &str, value: &Value, files: &BTreeMap<String, FileEntry>) -> Result<(), PolicyError> {
    match name {
        "wallpaper" => check_wallpaper(&parse::<Wallpaper>(name, value)?, files),
        "folders" => check_share(&parse::<Folders>(name, value)?.share),
        "shares" => {
            let shares: Vec<ShareLink> = parse(name, value)?;
            if shares.len() > MAX_SHARES {
                return refuse(format!("shares: more than {MAX_SHARES}"));
            }
            for share in &shares {
                check_name(&share.name, "shares")?;
                check_share(&share.url)?;
                if share.url.contains("%u") {
                    return refuse(format!("shares: {:?} uses %u, which only folders may", share.url));
                }
            }
            Ok(())
        }
        "browser" => check_browser(&parse(name, value)?),
        "printers" => {
            let printers: Vec<Printer> = parse(name, value)?;
            if printers.len() > MAX_PRINTERS {
                return refuse(format!("printers: more than {MAX_PRINTERS}"));
            }
            if let Some(printer) = printers.iter().find(|printer| !is_printer_uri(&printer.uri)) {
                return refuse(format!("printers: {:?} is not an ipp:// or ipps:// URI with a host", printer.uri));
            }
            if printers.iter().filter(|printer| printer.default).count() > 1 {
                return refuse("printers: more than one default");
            }
            Ok(())
        }
        "power" => check_power(&parse(name, value)?),
        "apps" => {
            let apps: Apps = parse(name, value)?;
            for (list, what) in [(&apps.required, "required"), (&apps.forbidden, "forbidden")] {
                if list.len() > MAX_APPS {
                    return refuse(format!("apps: more than {MAX_APPS} {what}"));
                }
                if let Some(id) = list.iter().find(|id| !is_app_id(id)) {
                    return refuse(format!("apps: {id:?} is not an App Center id"));
                }
            }
            if let Some(id) = apps.required.iter().find(|id| apps.forbidden.contains(id)) {
                return refuse(format!("apps: {id} is both required and forbidden"));
            }
            Ok(())
        }
        "usb" => parse::<Usb>(name, value).map(|_| ()),
        "screen_lock" => {
            let lock: ScreenLock = parse(name, value)?;
            if !(1..=120).contains(&lock.idle_minutes) {
                return refuse("screen_lock: idle_minutes must be 1 to 120");
            }
            Ok(())
        }
        "firewall" => parse::<Firewall>(name, value).map(|_| ()),
        "inventory" => parse::<InventorySection>(name, value).map(|_| ()),
        "shared" => {
            let shared: Shared = parse(name, value)?;
            if let Some(maintenance) = &shared.maintenance {
                check_days(&maintenance.days, "shared maintenance")?;
                hhmm(&maintenance.time)?;
                if !(15..=240).contains(&maintenance.max_minutes) {
                    return refuse("shared: maintenance max_minutes must be 15 to 240");
                }
            }
            Ok(())
        }
        "snapshots" => {
            let snapshots: Snapshots = parse(name, value)?;
            if !(1..=20).contains(&snapshots.keep) {
                return refuse("snapshots: keep must be 1 to 20");
            }
            Ok(())
        }
        "wifi" => {
            let networks: Vec<Wifi> = parse(name, value)?;
            if networks.len() > MAX_WIFI {
                return refuse(format!("wifi: more than {MAX_WIFI} networks"));
            }
            if let Some(network) = networks.iter().find(|network| !(1..=32).contains(&network.ssid.len())) {
                return refuse(format!("wifi: the SSID {:?} is not 1 to 32 bytes", network.ssid));
            }
            Ok(())
        }
        // Later versions may add sections.
        _ => Ok(()),
    }
}

fn check_wallpaper(wallpaper: &Wallpaper, files: &BTreeMap<String, FileEntry>) -> Result<(), PolicyError> {
    if wallpaper.periods.len() > MAX_PERIODS {
        return refuse(format!("wallpaper: more than {MAX_PERIODS} periods"));
    }
    let listed = |sha: &str| -> Result<(), PolicyError> {
        crate::policy::check_sha256(sha)?;
        if !files.contains_key(sha) {
            return refuse(format!("wallpaper: the image {sha} is not listed in files"));
        }
        Ok(())
    };
    if let Some(image) = &wallpaper.default {
        listed(image)?;
    }
    for period in &wallpaper.periods {
        check_name(&period.name, "wallpaper")?;
        MonthDay::parse(&period.from)?;
        MonthDay::parse(&period.to)?;
        listed(&period.image)?;
    }
    Ok(())
}

fn check_browser(browser: &Browser) -> Result<(), PolicyError> {
    if let Some(homepage) = &browser.homepage {
        if !is_http_url(homepage) {
            return refuse(format!("browser: the homepage {homepage:?} is not an http(s) URL"));
        }
    }
    if browser.bookmarks.len() > MAX_BOOKMARKS {
        return refuse(format!("browser: more than {MAX_BOOKMARKS} bookmarks"));
    }
    for bookmark in &browser.bookmarks {
        check_name(&bookmark.name, "browser bookmarks")?;
        if !is_http_url(&bookmark.url) {
            return refuse(format!("browser: the bookmark {:?} is not an http(s) URL", bookmark.url));
        }
    }
    if browser.block.len() > MAX_BLOCKED {
        return refuse(format!("browser: more than {MAX_BLOCKED} blocked domains"));
    }
    if let Some(domain) = browser.block.iter().find(|domain| !is_block_domain(domain)) {
        return refuse(format!("browser: {domain:?} is not a domain (lower case, no scheme, no path)"));
    }
    if let Some(hours) = &browser.block_hours {
        check_days(&hours.days, "browser block_hours")?;
        if hours.ranges.len() > MAX_RANGES {
            return refuse(format!("browser: more than {MAX_RANGES} block_hours ranges"));
        }
        for [from, to] in &hours.ranges {
            if hhmm(from)? >= hhmm(to)? {
                return refuse(format!("browser: the range {from}-{to} ends before it starts (a range does not cross midnight)"));
            }
        }
    }
    Ok(())
}

fn check_power(power: &Power) -> Result<(), PolicyError> {
    if let Some(shutdown) = &power.shutdown {
        check_days(&shutdown.days, "power shutdown")?;
        hhmm(&shutdown.time)?;
        let ranges = [
            (shutdown.warn_minutes, 1, 30, "warn_minutes"),
            (shutdown.postpone_minutes, 5, 120, "postpone_minutes"),
            (shutdown.max_postpones, 0, 5, "max_postpones"),
        ];
        for (value, low, high, what) in ranges {
            if !(low..=high).contains(&value) {
                return refuse(format!("power: {what} must be {low} to {high}"));
            }
        }
    }
    if let Some(wake) = &power.wake {
        check_days(&wake.days, "power wake")?;
        hhmm(&wake.time)?;
    }
    Ok(())
}

/// A machine's settings after merging the layers: None for a section that is not managed or is off (null), which
/// the agent treats alike: it puts back what it changed.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Effective {
    pub wallpaper: Option<Wallpaper>,
    pub folders: Option<Folders>,
    pub shares: Option<Vec<ShareLink>>,
    pub browser: Option<Browser>,
    pub printers: Option<Vec<Printer>>,
    pub power: Option<Power>,
    pub apps: Option<Apps>,
    pub usb: Option<Usb>,
    pub screen_lock: Option<ScreenLock>,
    pub firewall: Option<Firewall>,
    pub wifi: Option<Vec<Wifi>>,
    pub inventory: Option<InventorySection>,
    pub shared: Option<Shared>,
    pub snapshots: Option<Snapshots>,
}

impl Effective {
    /// The typed sections of a merged layer (sections were checked with the policy, so a failure means none).
    pub fn from_json(merged: &Map<String, Value>) -> Effective {
        fn section<T: DeserializeOwned>(merged: &Map<String, Value>, name: &str) -> Option<T> {
            merged.get(name).filter(|value| !value.is_null()).and_then(|value| serde_json::from_value(value.clone()).ok())
        }
        Effective {
            wallpaper: section(merged, "wallpaper"),
            folders: section(merged, "folders"),
            shares: section(merged, "shares"),
            browser: section(merged, "browser"),
            printers: section(merged, "printers"),
            power: section(merged, "power"),
            apps: section(merged, "apps"),
            usb: section(merged, "usb"),
            screen_lock: section(merged, "screen_lock"),
            firewall: section(merged, "firewall"),
            wifi: section(merged, "wifi"),
            inventory: section(merged, "inventory"),
            shared: section(merged, "shared"),
            snapshots: section(merged, "snapshots"),
        }
    }

    /// Whether the detailed inventory may be sent: `inventory.enabled` in effect.
    pub fn inventory_enabled(&self) -> bool {
        self.inventory.as_ref().is_some_and(|inventory| inventory.enabled)
    }

    /// The names of the sections in effect (managed and not off).
    pub fn in_effect(&self) -> BTreeSet<&'static str> {
        let present = [
            self.wallpaper.is_some(),
            self.folders.is_some(),
            self.shares.is_some(),
            self.browser.is_some(),
            self.printers.is_some(),
            self.power.is_some(),
            self.apps.is_some(),
            self.usb.is_some(),
            self.screen_lock.is_some(),
            self.firewall.is_some(),
            self.wifi.is_some(),
            self.shared.is_some(),
            self.snapshots.is_some(),
        ];
        SECTIONS.iter().zip(present).filter(|(_, on)| *on).map(|(name, _)| *name).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn check(name: &str, value: Value) -> Result<(), PolicyError> {
        check_section(name, &value, &BTreeMap::new())
    }

    #[test]
    fn times_and_hours() {
        assert_eq!(hhmm("00:00").unwrap(), 0);
        assert_eq!(hhmm("23:59").unwrap(), 1439);
        for bad in ["24:00", "7:45", "07:60", "0745", "07:4a", ""] {
            assert!(hhmm(bad).is_err(), "{bad}");
        }
        let hours = Hours { days: vec![1, 2, 3, 4, 5, 6], ranges: vec![["08:00".into(), "12:00".into()], ["13:30".into(), "17:30".into()]] };
        assert!(hours.contains(1, 8 * 60));
        assert!(hours.contains(6, 17 * 60 + 29));
        assert!(!hours.contains(6, 17 * 60 + 30));
        assert!(!hours.contains(3, 12 * 60 + 15));
        assert!(!hours.contains(7, 9 * 60));
    }

    #[test]
    fn urls_domains_and_ids() {
        assert!(is_http_url("https://amis.misa.vn"));
        assert!(is_http_url("http://192.168.1.5:8080/x?y=1"));
        assert!(!is_http_url("https://"));
        assert!(!is_http_url("ftp://x"));
        assert!(!is_http_url("https://a b"));
        assert!(is_block_domain("facebook.com"));
        assert!(!is_block_domain("Facebook.com"));
        assert!(!is_block_domain("https://facebook.com/x"));
        assert!(is_printer_uri("ipp://192.168.1.50/ipp/print"));
        assert!(is_printer_uri("ipps://printer.local:631/ipp/print"));
        assert!(!is_printer_uri("socket://192.168.1.50:9100"));
        assert!(!is_printer_uri("ipp://user@host/ipp"));
        assert!(!is_printer_uri("ipp:///ipp/print"));
        assert!(is_app_id("libreoffice"));
        assert!(!is_app_id("LibreOffice"));
        assert!(!is_app_id(&"a".repeat(41)));
    }

    #[test]
    fn section_limits() {
        assert!(check("screen_lock", json!({"idle_minutes": 120, "on_suspend": false})).is_ok());
        assert!(check("screen_lock", json!({"idle_minutes": 121})).is_err());
        assert!(check("usb", json!({"storage": "block"})).is_ok());
        assert!(check("usb", json!({"storage": "maybe"})).is_err());
        assert!(check("wifi", json!([{"ssid": "Tầng 2 – khách", "security": "open"}])).is_ok());
        assert!(check("wifi", json!([{"ssid": "", "security": "open"}])).is_err());
        assert!(check("wifi", json!([{"ssid": "x", "security": "wep"}])).is_err());
        let power = |warn: u32, postpone: u32, max: u32| {
            json!({"shutdown": {"days": [1], "time": "18:30", "warn_minutes": warn, "postpone_minutes": postpone, "max_postpones": max, "laptops": "same"}, "wake": null})
        };
        assert!(check("power", power(30, 120, 5)).is_ok());
        assert!(check("power", power(0, 30, 2)).is_err());
        assert!(check("power", power(10, 4, 2)).is_err());
        assert!(check("power", power(10, 30, 6)).is_err());
        assert!(check("power", json!({"shutdown": {"days": [8], "time": "18:30"}})).is_err());
        assert!(check("shares", json!([{"name": "Kế toán", "url": "smb://nas/ketoan"}])).is_ok());
        assert!(check("shares", json!([{"name": "x", "url": "smb://nas/%u"}])).is_err());
        assert!(check("apps", json!({"required": ["vlc"], "forbidden": ["discord"]})).is_ok());
        assert!(check("browser", json!({"homepage": null, "bookmarks": [], "block": [], "block_hours": null, "safe_search": false})).is_ok());
        assert!(check("browser", json!({"block_hours": {"days": [1], "ranges": [["08:00", "08:00"]]}})).is_err());
        let seven = vec![json!(["08:00", "09:00"]); 7];
        assert!(check("browser", json!({"block_hours": {"days": [1], "ranges": seven}})).is_err());
        assert!(check("firewall", json!({"enabled": true})).is_ok());
        assert!(check("inventory", json!({"enabled": false})).is_ok());
        assert!(check("inventory", json!({})).is_err());
        assert!(check("inventory", json!({"enabled": "yes"})).is_err());
        assert!(check("later-section", json!({"anything": 1})).is_ok());
        assert!(check("shared", json!({"guest": true})).is_ok(), "the other keys have defaults");
        assert!(check("shared", json!({"freeze": true, "maintenance": {"days": [7], "time": "02:00"}})).is_ok());
        assert!(check("shared", json!({"maintenance": {"days": [7], "time": "02:00", "max_minutes": 241}})).is_err());
        assert!(check("snapshots", json!({"schedule": "monthly", "keep": 20})).is_ok());
        assert!(check("snapshots", json!({"schedule": "weekly", "keep": 21})).is_err());
        assert!(check("snapshots", json!({"keep": 3})).is_err(), "no schedule");
    }

    #[test]
    fn effective_sections() {
        let merged: Map<String, Value> = serde_json::from_value(json!({
            "usb": {"storage": "read-only"}, "browser": null, "screen_lock": {"idle_minutes": 5, "on_suspend": true}
        }))
        .unwrap();
        let effective = Effective::from_json(&merged);
        assert_eq!(effective.usb, Some(Usb { storage: UsbStorage::ReadOnly }));
        assert_eq!(effective.browser, None);
        assert_eq!(effective.in_effect(), BTreeSet::from(["screen_lock", "usb"]));
        assert!(!effective.inventory_enabled());
        let on: Map<String, Value> = serde_json::from_value(json!({"inventory": {"enabled": true}})).unwrap();
        assert!(Effective::from_json(&on).inventory_enabled());
        let off: Map<String, Value> = serde_json::from_value(json!({"inventory": {"enabled": false}})).unwrap();
        assert!(!Effective::from_json(&off).inventory_enabled());
        let null: Map<String, Value> = serde_json::from_value(json!({"inventory": null})).unwrap();
        assert!(!Effective::from_json(&null).inventory_enabled());
    }
}
