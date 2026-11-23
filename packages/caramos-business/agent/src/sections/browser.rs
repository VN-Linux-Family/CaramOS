//! `browser`: Firefox's policies, the Chromium family's managed policy files, and the block in /etc/hosts.
//!
//! - Firefox reads one policies file: `/etc/firefox/policies/policies.json` starts as a copy of what was there
//!   before, else of Mint's `/usr/lib/firefox/distribution/policies.json`, with the company's keys added. It goes
//!   back to its earlier contents, or away, when the section stops being managed.
//! - Chromium-family browsers each read `caramos-business.json` in their managed folder. Cốc Cốc's folder is
//!   `/etc/opt/coccoc/policies/managed` (its binary holds `/etc/opt/coccoc/policies`, checked on 154.0.8037.106).
//! - Blocking: `0.0.0.0 d`, `www.d` and `m.d` between `# BEGIN caramos-business` and `# END caramos-business` in
//!   /etc/hosts, all the time or only inside `block_hours`. DNS over HTTPS is turned off in both browser families,
//!   or it would go around /etc/hosts. Nothing a user visits is ever recorded.

use std::fs;

use serde_json::{json, Map, Value};

use super::{remove_if_present, write_if_changed, Before, Managed, System};
use crate::clock::LocalTime;
use crate::settings::Browser;

pub const FIREFOX_POLICIES: &str = "/etc/firefox/policies/policies.json";
pub const FIREFOX_DISTRIBUTION: &str = "/usr/lib/firefox/distribution/policies.json";
pub const HOSTS: &str = "/etc/hosts";
const POLICY_FILE: &str = "caramos-business.json";
const BEGIN: &str = "# BEGIN caramos-business";
const END: &str = "# END caramos-business";
/// The folder the bookmarks appear in.
const BOOKMARKS_FOLDER: &str = "CaramOS Doanh nghiệp";

/// The Chromium-family browsers: name, where its program is (any of), its managed policy folder.
pub const CHROMIUM_FAMILY: [(&str, &[&str], &str); 5] = [
    ("Chrome", &["/opt/google/chrome/chrome"], "/etc/opt/chrome/policies/managed"),
    ("Chromium", &["/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/lib/chromium/chromium"], "/etc/chromium/policies/managed"),
    ("Edge", &["/opt/microsoft/msedge/msedge"], "/etc/opt/edge/policies/managed"),
    ("Brave", &["/opt/brave.com/brave/brave"], "/etc/brave/policies/managed"),
    ("Cốc Cốc", &["/opt/coccoc/browser/browser"], "/etc/opt/coccoc/policies/managed"),
];

/// Applies the section, or puts things back when it is None. `now` decides the block during `block_hours`.
pub fn apply(system: &System, browser: Option<&Browser>, managed: &mut Managed, now: &LocalTime) -> Result<(), String> {
    let mut errors = Vec::new();
    if let Err(error) = firefox(system, browser, managed) {
        errors.push(format!("Firefox: {error}"));
    }
    if let Err(error) = chromium(system, browser, managed) {
        errors.push(error);
    }
    if let Err(error) = block(system, browser, managed, now) {
        errors.push(format!("/etc/hosts: {error}"));
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

/// The company's keys added to a Firefox policies document.
pub fn firefox_policies(base: Value, browser: &Browser) -> Value {
    let mut document = match base {
        Value::Object(object) => object,
        _ => Map::new(),
    };
    let policies = document.entry("policies").or_insert_with(|| json!({}));
    if !policies.is_object() {
        *policies = json!({});
    }
    let policies = policies.as_object_mut().expect("policies is an object");
    if let Some(homepage) = &browser.homepage {
        policies.insert("Homepage".into(), json!({"URL": homepage, "Locked": false, "StartPage": "homepage"}));
    }
    if !browser.bookmarks.is_empty() {
        policies.insert("ManagedBookmarks".into(), bookmarks(browser));
        policies.insert("DisplayBookmarksToolbar".into(), json!("always"));
    }
    policies.insert("DNSOverHTTPS".into(), json!({"Enabled": false, "Locked": true}));
    Value::Object(document)
}

/// Managed bookmarks, in the form both Firefox and Chromium read.
fn bookmarks(browser: &Browser) -> Value {
    let mut list = vec![json!({"toplevel_name": BOOKMARKS_FOLDER})];
    list.extend(browser.bookmarks.iter().map(|bookmark| json!({"name": bookmark.name, "url": bookmark.url})));
    Value::Array(list)
}

fn firefox(system: &System, browser: Option<&Browser>, managed: &mut Managed) -> Result<(), String> {
    let path = system.path(FIREFOX_POLICIES);
    let Some(browser) = browser else {
        // Put back what was there before the agent's first write.
        if let Some(before) = managed.firefox.take() {
            let restored = match (&before.existed, &before.contents) {
                (true, Some(contents)) => write_if_changed(&path, contents.as_bytes(), 0o644).map(|_| ()),
                _ => remove_if_present(&path).map(|_| ()),
            };
            if let Err(error) = restored {
                managed.firefox = Some(before);
                return Err(error.to_string());
            }
        }
        return Ok(());
    };
    if managed.firefox.is_none() {
        let contents = fs::read_to_string(&path).ok();
        managed.firefox = Some(Before { existed: contents.is_some(), contents });
    }
    let before = managed.firefox.as_ref().expect("recorded above");
    let base_text = if before.existed { before.contents.clone() } else { fs::read_to_string(system.path(FIREFOX_DISTRIBUTION)).ok() };
    let base = base_text.and_then(|text| serde_json::from_str(&text).ok()).unwrap_or_else(|| json!({}));
    let mut text = serde_json::to_string_pretty(&firefox_policies(base, browser)).map_err(|error| error.to_string())?;
    text.push('\n');
    write_if_changed(&path, text.as_bytes(), 0o644).map(|_| ()).map_err(|error| error.to_string())
}

/// The Chromium family's managed policies for the section.
pub fn chromium_policies(browser: &Browser) -> Value {
    let mut policies = Map::new();
    if let Some(homepage) = &browser.homepage {
        policies.insert("HomepageLocation".into(), json!(homepage));
        policies.insert("HomepageIsNewTabPage".into(), json!(false));
        policies.insert("RestoreOnStartup".into(), json!(4));
        policies.insert("RestoreOnStartupURLs".into(), json!([homepage]));
    }
    if !browser.bookmarks.is_empty() {
        policies.insert("ManagedBookmarks".into(), bookmarks(browser));
    }
    policies.insert("DnsOverHttpsMode".into(), json!("off"));
    if browser.safe_search {
        policies.insert("ForceGoogleSafeSearch".into(), json!(true));
        policies.insert("ForceYouTubeRestrict".into(), json!(1));
    }
    if browser.block_hours.is_none() && !browser.block.is_empty() {
        policies.insert("URLBlocklist".into(), json!(browser.block));
    }
    Value::Object(policies)
}

fn chromium(system: &System, browser: Option<&Browser>, managed: &mut Managed) -> Result<(), String> {
    let mut errors = Vec::new();
    let mut written = Vec::new();
    if let Some(browser) = browser {
        let mut text = serde_json::to_string_pretty(&chromium_policies(browser)).map_err(|error| error.to_string())?;
        text.push('\n');
        for (name, programs, folder) in CHROMIUM_FAMILY {
            if !system.has_any(programs) {
                continue;
            }
            let file = format!("{folder}/{POLICY_FILE}");
            match write_if_changed(&system.path(&file), text.as_bytes(), 0o644) {
                Ok(_) => written.push(file),
                Err(error) => errors.push(format!("{name}: {error}")),
            }
        }
    }
    // Files the agent wrote that are no longer wanted (the section went away, the browser left).
    for file in managed.chromium.clone() {
        if !written.contains(&file) {
            if let Err(error) = remove_if_present(&system.path(&file)) {
                errors.push(format!("{file}: {error}"));
                written.push(file);
            }
        }
    }
    managed.chromium = written;
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

/// The domains to block now: None removes the block, an empty list leaves it empty (outside `block_hours`).
pub fn blocked_now(browser: Option<&Browser>, now: &LocalTime) -> Option<Vec<String>> {
    let browser = browser?;
    let active = match &browser.block_hours {
        None => true,
        Some(hours) => hours.contains(now.weekday(), now.minute_of_day()),
    };
    Some(if active { browser.block.clone() } else { Vec::new() })
}

/// /etc/hosts with the agent's block set to `domains` (None: no block), the other lines kept as they are.
pub fn hosts_text(current: &str, domains: Option<&[String]>) -> String {
    let mut out = String::with_capacity(current.len() + 256);
    let mut inside = false;
    for line in current.lines() {
        if line.trim() == BEGIN {
            inside = true;
            continue;
        }
        if inside {
            if line.trim() == END {
                inside = false;
            }
            continue;
        }
        out.push_str(line);
        out.push('\n');
    }
    if let Some(domains) = domains {
        out.push_str(BEGIN);
        out.push('\n');
        out.push_str("# ");
        out.push_str(super::MANAGED_BY);
        out.push('\n');
        for domain in domains {
            for name in [domain.clone(), format!("www.{domain}"), format!("m.{domain}")] {
                out.push_str("0.0.0.0 ");
                out.push_str(&name);
                out.push('\n');
            }
        }
        out.push_str(END);
        out.push('\n');
    }
    out
}

/// Writes or empties the block for `now`; the scheduler calls this every 30 s for `block_hours`.
pub fn block(system: &System, browser: Option<&Browser>, managed: &mut Managed, now: &LocalTime) -> Result<(), String> {
    let path = system.path(HOSTS);
    let current = fs::read_to_string(&path).map_err(|error| error.to_string())?;
    let domains = blocked_now(browser, now);
    if domains.is_none() && !managed.hosts && !current.contains(BEGIN) {
        return Ok(());
    }
    let text = hosts_text(&current, domains.as_deref());
    write_if_changed(&path, text.as_bytes(), 0o644).map_err(|error| error.to_string())?;
    managed.hosts = domains.is_some();
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::settings::{Bookmark, Hours};
    use crate::testutil::TempDir;

    fn browser(hours: Option<Hours>) -> Browser {
        Browser {
            homepage: Some("https://amis.misa.vn".into()),
            bookmarks: vec![Bookmark { name: "Thuế điện tử".into(), url: "https://thuedientu.gdt.gov.vn".into() }],
            block: vec!["facebook.com".into(), "tiktok.com".into()],
            block_hours: hours,
            safe_search: true,
        }
    }

    fn work_hours() -> Hours {
        Hours { days: vec![1, 2, 3, 4, 5, 6], ranges: vec![["08:00".into(), "12:00".into()], ["13:30".into(), "17:30".into()]] }
    }

    #[test]
    fn firefox_keeps_mints_policies_and_adds_ours() {
        let mint = json!({"policies": {"DisableTelemetry": true, "SearchEngines": {"Default": "DuckDuckGo"}}});
        let policies = firefox_policies(mint, &browser(None));
        assert_eq!(policies["policies"]["DisableTelemetry"], true);
        assert_eq!(policies["policies"]["SearchEngines"]["Default"], "DuckDuckGo");
        assert_eq!(policies["policies"]["Homepage"]["URL"], "https://amis.misa.vn");
        assert_eq!(policies["policies"]["Homepage"]["StartPage"], "homepage");
        assert_eq!(policies["policies"]["ManagedBookmarks"][1]["url"], "https://thuedientu.gdt.gov.vn");
        assert_eq!(policies["policies"]["DisplayBookmarksToolbar"], "always");
        assert_eq!(policies["policies"]["DNSOverHTTPS"], json!({"Enabled": false, "Locked": true}));
    }

    #[test]
    fn chromium_blocklist_only_when_blocking_all_the_time() {
        let all_day = chromium_policies(&browser(None));
        assert_eq!(all_day["URLBlocklist"], json!(["facebook.com", "tiktok.com"]));
        assert_eq!(all_day["RestoreOnStartup"], 4);
        assert_eq!(all_day["ForceYouTubeRestrict"], 1);
        assert_eq!(all_day["DnsOverHttpsMode"], "off");
        assert!(chromium_policies(&browser(Some(work_hours()))).get("URLBlocklist").is_none());
    }

    #[test]
    fn hosts_block_follows_the_hours() {
        let hosts = "127.0.0.1 localhost\n127.0.1.1 caramos-disk\n";
        let with = hosts_text(hosts, Some(&["facebook.com".to_string()]));
        assert!(with.starts_with(hosts));
        assert!(with.contains("0.0.0.0 facebook.com\n0.0.0.0 www.facebook.com\n0.0.0.0 m.facebook.com\n"));
        assert_eq!(hosts_text(&with, None), hosts);
        let empty = hosts_text(&with, Some(&[]));
        assert!(empty.contains(BEGIN) && !empty.contains("facebook"));
        assert_eq!(hosts_text(&empty, Some(&["facebook.com".to_string()])), with);

        // 2026-11-23 12:00 in Vietnam, a Monday.
        let monday_noon = LocalTime::from_unix(1_795_410_000);
        assert_eq!((monday_noon.weekday(), monday_noon.minute_of_day()), (1, 12 * 60));
        let hours = browser(Some(work_hours()));
        assert_eq!(blocked_now(Some(&hours), &monday_noon), Some(vec![]));
        let monday_ten = LocalTime::from_unix(1_795_410_000 - 2 * 3600);
        assert_eq!(blocked_now(Some(&hours), &monday_ten).unwrap().len(), 2);
        assert_eq!(blocked_now(None, &monday_ten), None);
    }

    #[test]
    fn files_are_written_and_put_back() {
        let root = TempDir::new("browser");
        let system = System::test(root.path());
        fs::create_dir_all(root.path().join("etc")).unwrap();
        fs::write(root.path().join("etc/hosts"), "127.0.0.1 localhost\n").unwrap();
        fs::create_dir_all(root.path().join("usr/lib/firefox/distribution")).unwrap();
        fs::write(root.path().join(FIREFOX_DISTRIBUTION.trim_start_matches('/')), r#"{"policies": {"DisableAppUpdate": true}}"#).unwrap();
        fs::create_dir_all(root.path().join("opt/coccoc/browser")).unwrap();
        fs::write(root.path().join("opt/coccoc/browser/browser"), "").unwrap();
        let mut managed = Managed::default();
        let now = LocalTime::from_unix(1_795_410_000 - 2 * 3600);

        apply(&system, Some(&browser(Some(work_hours()))), &mut managed, &now).unwrap();
        let firefox: Value = serde_json::from_str(&fs::read_to_string(system.path(FIREFOX_POLICIES)).unwrap()).unwrap();
        assert_eq!(firefox["policies"]["DisableAppUpdate"], true);
        assert_eq!(firefox["policies"]["Homepage"]["URL"], "https://amis.misa.vn");
        assert_eq!(managed.chromium, ["/etc/opt/coccoc/policies/managed/caramos-business.json"]);
        assert!(system.path("/etc/opt/coccoc/policies/managed/caramos-business.json").exists());
        assert!(!system.path("/etc/opt/chrome/policies/managed/caramos-business.json").exists());
        assert!(fs::read_to_string(system.path(HOSTS)).unwrap().contains("0.0.0.0 tiktok.com"));
        assert_eq!(managed.firefox, Some(Before { existed: false, contents: None }));

        apply(&system, None, &mut managed, &now).unwrap();
        assert!(!system.path(FIREFOX_POLICIES).exists());
        assert!(!system.path("/etc/opt/coccoc/policies/managed/caramos-business.json").exists());
        assert_eq!(fs::read_to_string(system.path(HOSTS)).unwrap(), "127.0.0.1 localhost\n");
        assert_eq!(managed, Managed::default());

        // A policies file that was there before comes back as it was.
        fs::create_dir_all(system.path("/etc/firefox/policies")).unwrap();
        fs::write(system.path(FIREFOX_POLICIES), r#"{"policies": {"BlockAboutConfig": true}}"#).unwrap();
        apply(&system, Some(&browser(None)), &mut managed, &now).unwrap();
        let firefox: Value = serde_json::from_str(&fs::read_to_string(system.path(FIREFOX_POLICIES)).unwrap()).unwrap();
        assert_eq!(firefox["policies"]["BlockAboutConfig"], true);
        assert!(firefox["policies"].get("DisableAppUpdate").is_none());
        apply(&system, None, &mut managed, &now).unwrap();
        assert_eq!(fs::read_to_string(system.path(FIREFOX_POLICIES)).unwrap(), r#"{"policies": {"BlockAboutConfig": true}}"#);
    }
}
