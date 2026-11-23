//! `screen_lock` (session part): the idle time before the screen locks, and locking on suspend. The keys are set
//! again when someone changes them, like the wallpaper lock, and get their earlier values back when the section goes
//! away. Only gsettings and xfconf-query: never `dconf update` under a running Cinnamon.
//!
//! - Cinnamon: `org.cinnamon.desktop.session idle-delay` (seconds), `org.cinnamon.desktop.screensaver lock-enabled
//!   true` and `lock-delay 0`; on suspend, `org.cinnamon.settings-daemon.plugins.power lock-on-suspend`.
//! - Xfce: CaramOS Xfce locks with light-locker, which locks when the screensaver starts. xfce4-power-manager's
//!   `blank-on-ac` and `blank-on-battery` (minutes) start it; light-locker's `lock-after-screensaver 1` and
//!   `late-locking false` lock a second later (0 would turn locking after the screensaver off); on suspend,
//!   `apps.light-locker lock-on-suspend` and xfce4-power-manager's `lock-screen-suspend-hibernate`.

use std::collections::BTreeMap;
use std::time::Duration;

use crate::process;
use crate::settings::ScreenLock;
use crate::wallpaper::Desktop;

const TOOL_TIMEOUT: Duration = Duration::from_secs(30);
/// What a key held before when it did not exist (xfconf): it is removed again.
const ABSENT: &str = "\u{0}absent";

/// Where a key lives.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Place {
    Gsettings { schema: &'static str, key: &'static str },
    Xfconf { channel: &'static str, property: &'static str, kind: &'static str },
}

impl Place {
    /// The key's name in state.json.
    pub fn id(&self) -> String {
        match self {
            Place::Gsettings { schema, key } => format!("gsettings:{schema}:{key}"),
            Place::Xfconf { channel, property, .. } => format!("xfconf:{channel}:{property}"),
        }
    }
}

/// The keys and their values for a section on a desktop.
pub fn keys(desktop: Desktop, lock: &ScreenLock) -> Vec<(Place, String)> {
    let gsettings = |schema, key| Place::Gsettings { schema, key };
    let xfconf = |property, kind| Place::Xfconf { channel: "xfce4-power-manager", property, kind };
    let suspend = lock.on_suspend.to_string();
    match desktop {
        Desktop::Cinnamon => vec![
            (gsettings("org.cinnamon.desktop.session", "idle-delay"), (lock.idle_minutes * 60).to_string()),
            (gsettings("org.cinnamon.desktop.screensaver", "lock-enabled"), "true".to_string()),
            (gsettings("org.cinnamon.desktop.screensaver", "lock-delay"), "0".to_string()),
            (gsettings("org.cinnamon.settings-daemon.plugins.power", "lock-on-suspend"), suspend),
        ],
        Desktop::Xfce => vec![
            (xfconf("/xfce4-power-manager/blank-on-ac", "uint"), lock.idle_minutes.to_string()),
            (xfconf("/xfce4-power-manager/blank-on-battery", "uint"), lock.idle_minutes.to_string()),
            (xfconf("/xfce4-power-manager/lock-screen-suspend-hibernate", "bool"), suspend.clone()),
            // 1 s: 0 turns light-locker's locking after the screensaver off.
            (gsettings("apps.light-locker", "lock-after-screensaver"), "1".to_string()),
            (gsettings("apps.light-locker", "late-locking"), "false".to_string()),
            (gsettings("apps.light-locker", "lock-on-suspend"), suspend),
        ],
        Desktop::Other => Vec::new(),
    }
}

/// gsettings prints `uint32 600`; the value is `600`.
pub fn plain(value: &str) -> String {
    let value = value.trim();
    value.split_once(' ').filter(|(kind, _)| kind.starts_with("uint") || kind.starts_with("int")).map_or(value, |(_, number)| number).to_string()
}

fn get(place: &Place) -> Option<String> {
    let output = match place {
        Place::Gsettings { schema, key } => process::run("gsettings", &["get", schema, key], TOOL_TIMEOUT),
        Place::Xfconf { channel, property, .. } => process::run("xfconf-query", &["-c", channel, "-p", property], TOOL_TIMEOUT),
    }
    .ok()?;
    output.success().then(|| output.stdout.trim().to_string())
}

fn set(place: &Place, value: &str) -> Result<(), String> {
    let output = match place {
        Place::Gsettings { schema, key } => process::run("gsettings", &["set", schema, key, value], TOOL_TIMEOUT),
        Place::Xfconf { channel, property, .. } if value == ABSENT => process::run("xfconf-query", &["-c", channel, "-p", property, "-r"], TOOL_TIMEOUT),
        Place::Xfconf { channel, property, kind } => process::run("xfconf-query", &["-c", channel, "-p", property, "-n", "-t", kind, "-s", value], TOOL_TIMEOUT),
    }
    .map_err(|error| error.to_string())?;
    if output.success() {
        Ok(())
    } else {
        Err(format!("{}: {}", place.id(), output.message()))
    }
}

/// One round: sets what differs (remembering the earlier values in `before`), or puts the earlier values back when
/// the section is None. None when there is nothing to do or report.
pub fn apply(desktop: Desktop, lock: Option<&ScreenLock>, before: &mut BTreeMap<String, String>) -> Option<Result<(), String>> {
    let Some(lock) = lock else {
        if before.is_empty() {
            return None;
        }
        let places: Vec<Place> = keys(desktop, &ScreenLock { idle_minutes: 1, on_suspend: false }).into_iter().map(|(place, _)| place).collect();
        for (id, value) in std::mem::take(before) {
            if let Some(place) = places.iter().find(|place| place.id() == id) {
                let _ = set(place, &value);
            }
        }
        return None;
    };
    if desktop == Desktop::Other {
        return Some(Err("this desktop is neither Cinnamon nor Xfce".to_string()));
    }
    let mut errors = Vec::new();
    for (place, wanted) in keys(desktop, lock) {
        let current = get(&place);
        let missing_schema = current.is_none() && matches!(place, Place::Gsettings { .. });
        if missing_schema {
            // A key this desktop does not have (an older Cinnamon, no light-locker): nothing to set.
            continue;
        }
        if current.as_deref().map(plain).as_deref() == Some(wanted.as_str()) {
            continue;
        }
        before.entry(place.id()).or_insert_with(|| current.clone().unwrap_or_else(|| ABSENT.to_string()));
        if let Err(error) = set(&place, &wanted) {
            errors.push(error);
        }
    }
    Some(if errors.is_empty() { Ok(()) } else { Err(errors.join("; ")) })
}

/// Whether the user's screen locks by itself (PROTOCOL.md part 3 "Security report"): on Cinnamon `lock-enabled` and an
/// idle delay above 0; on Xfce light-locker running, `lock-after-screensaver` above 0 and the screen blanking on AC
/// power. None on another desktop, or when the keys cannot be read.
pub fn is_on(desktop: Desktop, uid: u32) -> Option<bool> {
    let number = |place: &Place| get(place).map(|value| plain(&value)).and_then(|value| value.parse::<i64>().ok());
    match desktop {
        Desktop::Cinnamon => {
            let enabled = get(&Place::Gsettings { schema: "org.cinnamon.desktop.screensaver", key: "lock-enabled" })?;
            let idle = number(&Place::Gsettings { schema: "org.cinnamon.desktop.session", key: "idle-delay" })?;
            Some(enabled == "true" && idle > 0)
        }
        Desktop::Xfce => {
            let after = number(&Place::Gsettings { schema: "apps.light-locker", key: "lock-after-screensaver" })?;
            // xfce4-power-manager blanks after 10 minutes on AC power while the property is not set.
            let blank = number(&Place::Xfconf { channel: "xfce4-power-manager", property: "/xfce4-power-manager/blank-on-ac", kind: "uint" }).unwrap_or(10);
            Some(runs("light-locker", uid) && after > 0 && blank > 0)
        }
        Desktop::Other => None,
    }
}

/// Whether a process named `name` of `uid` runs.
fn runs(name: &str, uid: u32) -> bool {
    use std::os::unix::fs::MetadataExt;
    let Ok(entries) = std::fs::read_dir("/proc") else {
        return false;
    };
    entries.flatten().any(|entry| {
        entry.file_name().to_str().is_some_and(|pid| pid.bytes().all(|byte| byte.is_ascii_digit()))
            && entry.metadata().is_ok_and(|metadata| metadata.uid() == uid)
            && std::fs::read_to_string(entry.path().join("comm")).is_ok_and(|comm| comm.trim() == name)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_per_desktop() {
        let lock = ScreenLock { idle_minutes: 5, on_suspend: true };
        let cinnamon = keys(Desktop::Cinnamon, &lock);
        assert_eq!(cinnamon[0], (Place::Gsettings { schema: "org.cinnamon.desktop.session", key: "idle-delay" }, "300".to_string()));
        assert!(cinnamon.iter().any(|(place, value)| place.id() == "gsettings:org.cinnamon.desktop.screensaver:lock-delay" && value == "0"));
        let xfce = keys(Desktop::Xfce, &lock);
        assert!(xfce.iter().any(|(place, value)| place.id() == "xfconf:xfce4-power-manager:/xfce4-power-manager/blank-on-ac" && value == "5"));
        assert!(xfce.iter().any(|(place, value)| place.id() == "gsettings:apps.light-locker:lock-on-suspend" && value == "true"));
        assert!(xfce.iter().any(|(place, value)| place.id() == "gsettings:apps.light-locker:lock-after-screensaver" && value == "1"));
        assert!(keys(Desktop::Other, &lock).is_empty());
        assert_eq!(plain("uint32 600"), "600");
        assert_eq!(plain("true"), "true");
        assert_eq!(plain("'zoom'"), "'zoom'");
    }
}
