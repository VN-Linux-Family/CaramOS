//! `apps`: missing `required` apps are installed and installed `forbidden` apps removed, through App Center's
//! helper, run by the daemon as root: `caramos-app-center-helper install|remove <ids>`. Which apps are installed comes
//! from App Center's own detection. This runs at most every 6 hours, or at once when the section changes; installs
//! and removals are not undone when the section goes away.

use std::collections::BTreeSet;
use std::time::Duration;

use super::{Managed, System};
use crate::settings::Apps;

pub const HELPER: &str = "/usr/lib/caramos-app-center/caramos-app-center-helper";
const EVERY: i64 = 6 * 3600;
/// The helper installs at most 40 apps per run, and removes one.
const BATCH: usize = 40;
const HELPER_TIMEOUT: Duration = Duration::from_secs(2 * 3600);
const DETECT_TIMEOUT: Duration = Duration::from_secs(120);

/// App Center's catalogue ids and the installed ones, from its own detection code.
const DETECT: &str = "import json\n\
from caramos_app_center import catalog, detect\n\
c = catalog.load_catalog(catalog.CATALOG_FILE, catalog.RECIPE_DIR)\n\
print(json.dumps({'known': sorted(c.apps), 'installed': sorted(detect.installed_apps(c))}))\n";

/// What to install and remove, given the catalogue and the installed apps.
pub fn plan(apps: &Apps, known: &BTreeSet<String>, installed: &BTreeSet<String>) -> (Vec<String>, Vec<String>, Vec<String>) {
    let unknown = apps.required.iter().chain(&apps.forbidden).filter(|id| !known.contains(*id)).cloned().collect();
    let install = apps.required.iter().filter(|id| known.contains(*id) && !installed.contains(*id)).cloned().collect();
    let remove = apps.forbidden.iter().filter(|id| known.contains(*id) && installed.contains(*id)).cloned().collect();
    (install, remove, unknown)
}

/// Runs the section when it is due; otherwise keeps the last outcome. Returns that outcome.
pub fn apply(system: &System, apps: Option<&Apps>, managed: &mut Managed, now: i64, last_outcome: Option<Result<(), String>>) -> Result<(), String> {
    let Some(apps) = apps else {
        managed.apps_section = None;
        return Ok(());
    };
    let section = serde_json::to_string(apps).unwrap_or_default();
    let due = managed.apps_section.as_deref() != Some(section.as_str()) || managed.apps_ran.is_none_or(|ran| now - ran >= EVERY);
    if !due {
        return last_outcome.unwrap_or(Ok(()));
    }
    managed.apps_ran = Some(now);
    managed.apps_section = Some(section);
    if !system.has_any(&[HELPER]) {
        return Err("App Center is not installed".to_string());
    }
    let (known, installed) = if system.commands {
        let output = system.check("python3", &["-I", "-c", DETECT], DETECT_TIMEOUT)?;
        let value: serde_json::Value = serde_json::from_str(output.trim()).map_err(|error| format!("App Center's detection: {error}"))?;
        let set = |key: &str| -> BTreeSet<String> {
            value[key].as_array().into_iter().flatten().filter_map(|id| id.as_str().map(str::to_string)).collect()
        };
        (set("known"), set("installed"))
    } else {
        (apps.required.iter().chain(&apps.forbidden).cloned().collect(), BTreeSet::new())
    };
    let (install, remove, unknown) = plan(apps, &known, &installed);
    let mut errors: Vec<String> = unknown.iter().map(|id| format!("{id} is not in App Center")).collect();
    for batch in install.chunks(BATCH) {
        let mut args = vec!["install"];
        args.extend(batch.iter().map(String::as_str));
        if let Err(error) = system.check(HELPER, &args, HELPER_TIMEOUT) {
            errors.push(format!("installing {}: {error}", batch.join(", ")));
        }
    }
    for id in &remove {
        if let Err(error) = system.check(HELPER, &["remove", id], HELPER_TIMEOUT) {
            errors.push(format!("removing {id}: {error}"));
        }
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn plans() {
        let apps = Apps { required: vec!["libreoffice".into(), "vlc".into(), "nope".into()], forbidden: vec!["discord".into(), "zoom".into()] };
        let known: BTreeSet<String> = ["libreoffice", "vlc", "discord", "zoom"].map(String::from).into();
        let installed: BTreeSet<String> = ["vlc", "zoom"].map(String::from).into();
        let (install, remove, unknown) = plan(&apps, &known, &installed);
        assert_eq!(install, ["libreoffice"]);
        assert_eq!(remove, ["zoom"]);
        assert_eq!(unknown, ["nope"]);
    }

    #[test]
    fn runs_when_due() {
        let root = crate::testutil::TempDir::new("apps");
        let system = System::test(root.path());
        let mut managed = Managed::default();
        let apps = Apps { required: vec!["vlc".into()], forbidden: vec![] };
        assert!(apply(&system, Some(&apps), &mut managed, 1000, None).unwrap_err().contains("not installed"));
        assert_eq!(managed.apps_ran, Some(1000));
        // Not due again within 6 hours for the same section: the last outcome stays.
        assert_eq!(apply(&system, Some(&apps), &mut managed, 2000, Some(Ok(()))), Ok(()));
        assert_eq!(managed.apps_ran, Some(1000));
        let other = Apps { required: vec!["zoom".into()], forbidden: vec![] };
        let _ = apply(&system, Some(&other), &mut managed, 2000, Some(Ok(())));
        assert_eq!(managed.apps_ran, Some(2000));
    }
}
