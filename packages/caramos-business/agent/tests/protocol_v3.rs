//! The version 0.3 vectors in ../tests/protocol-examples/v3 (made by make_v3.py) that concern the agent: the MACs of
//! the GETs that need one from 0.3, the policy with `shared` and `snapshots` and both machines' effective settings, the
//! invalid policies, the freeze refused next to a tidy, the remote help command with its sealed key, the removal
//! notices, the tickets, the origins from `apt-cache policy`, the new inventory and health keys, the capabilities, and
//! the exact files the agent writes.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use caramos_business_agent::commands::{self, Action, CommandRecord, Decision};
use caramos_business_agent::crypto::{self, SharedKeys};
use caramos_business_agent::daemon;
use caramos_business_agent::health;
use caramos_business_agent::inventory::{self, App};
use caramos_business_agent::policy;
use caramos_business_agent::protocol::{Envelope, PolicyAnswer, SignedNotice, SignedPolicy, SignedTickets, WaitAnswer, CAPABILITIES};
use caramos_business_agent::remotehelp;
use caramos_business_agent::sections::{shared, snapshots, Managed, System};
use caramos_business_agent::settings::{Schedule, Snapshots};
use caramos_business_agent::tickets;
use serde_json::{json, Value};

const MACHINE_ID: &str = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";
const OTHER_MACHINE_ID: &str = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f";
const NOW: i64 = 1_795_400_000;

fn v3() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/protocol-examples/v3")
}

fn text(name: &str) -> String {
    fs::read_to_string(v3().join(name)).unwrap_or_else(|error| panic!("{name}: {error}"))
}

fn json(name: &str) -> Value {
    serde_json::from_str(&text(name)).unwrap()
}

fn admin_key() -> [u8; 32] {
    crypto::decode_key32(json("keys.json")["admin_sign_public"].as_str().unwrap(), "admin key").unwrap()
}

/// The machine's shared keys: v2's machine box seed with v3's admin box key (the same keys).
fn machine_keys() -> SharedKeys {
    let v2: Value = serde_json::from_str(&fs::read_to_string(v3().join("../v2/keys.json")).unwrap()).unwrap();
    let seed = crypto::decode_key32(v2["machine_box_seed"].as_str().unwrap(), "seed").unwrap();
    let admin_box = crypto::decode_key32(json("keys.json")["admin_box_public"].as_str().unwrap(), "admin box").unwrap();
    SharedKeys::derive(&seed, &admin_box).unwrap()
}

#[test]
fn macs_of_the_policy_and_its_files() {
    let keys = machine_keys();
    assert_eq!(crypto::hex(&keys.mac_key), json("keys.json")["mac_key_hex"].as_str().unwrap());
    assert_eq!(crypto::hex(&keys.seal_key), json("keys.json")["seal_key_hex"].as_str().unwrap());
    for name in ["mac-policy.json", "mac-files.json"] {
        let vector = json(name);
        let mac = keys.request_mac("GET", vector["path"].as_str().unwrap(), vector["time"].as_i64().unwrap(), b"");
        assert_eq!(mac, vector["headers"]["X-Caramos-Mac"].as_str().unwrap(), "{name}");
        assert_eq!(vector["headers"]["X-Caramos-Machine"], MACHINE_ID);
    }
}

#[test]
fn the_policy_with_shared_machines_and_snapshots() {
    let signed: SignedPolicy = serde_json::from_str(&text("signed-policy.json")).unwrap();
    crypto::verify(&admin_key(), signed.policy.as_bytes(), &signed.signature).unwrap();
    assert!(matches!(PolicyAnswer::parse(text("signed-policy.json").as_bytes()).unwrap(), PolicyAnswer::Policy(_)));
    let parsed = policy::parse(&signed.policy).unwrap();
    assert_eq!(parsed, policy::parse(&text("policy.json")).unwrap());
    assert_eq!(parsed.serial, 21);
    for (machine, file) in [(MACHINE_ID, "effective-machine.json"), (OTHER_MACHINE_ID, "effective-other-machine.json")] {
        let expected: serde_json::Map<String, Value> = serde_json::from_value(json(file)).unwrap();
        assert_eq!(parsed.effective_json(machine), expected, "{file}");
    }
    let ours = parsed.effective(MACHINE_ID);
    assert_eq!(ours.snapshots, Some(Snapshots { schedule: Schedule::Weekly, keep: 3, before_update: true }));
    assert!(ours.shared.is_none());
    let lab = parsed.effective(OTHER_MACHINE_ID);
    assert!(lab.snapshots.is_none(), "null in the department");
    let shared = lab.shared.clone().unwrap();
    assert!(shared.guest && shared.freeze && !shared.low_memory_ok);
    let maintenance = shared.maintenance.clone().unwrap();
    assert_eq!((maintenance.days, maintenance.time.as_str(), maintenance.max_minutes), (vec![7], "02:00", 60));
    assert!(lab.in_effect().contains("shared") && ours.in_effect().contains("snapshots"));
    // Frozen with enough memory: nothing stands in the way; below 3 GiB without "Tôi hiểu" the freeze is refused.
    assert_eq!(shared::refusal(&shared, &lab, 4096), None);
    assert!(shared::refusal(&shared, &lab, 1968).is_some());
}

#[test]
fn every_invalid_policy_is_refused_for_its_reason() {
    let reasons = [
        ("invalid-shared-freeze-type.json", "section shared"),
        ("invalid-shared-maintenance-days.json", "ISO weekday"),
        ("invalid-shared-maintenance-time.json", "HH:MM"),
        ("invalid-shared-max-minutes.json", "max_minutes"),
        ("invalid-snapshots-before-update.json", "section snapshots"),
        ("invalid-snapshots-keep.json", "keep must be 1 to 20"),
        ("invalid-snapshots-schedule.json", "section snapshots"),
    ];
    let mut listed: Vec<String> = fs::read_dir(v3())
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .filter(|name| name.starts_with("invalid-"))
        .collect();
    listed.sort();
    let mut expected: Vec<String> = reasons.iter().map(|(name, _)| name.to_string()).collect();
    expected.sort();
    assert_eq!(listed, expected, "a reason for every invalid vector");
    for (name, reason) in reasons {
        let error = policy::parse(&text(name)).expect_err(name);
        assert!(error.0.contains(reason), "{name}: {error}");
    }
    // The admin refuses to sign a freeze without a maintenance window; the agent takes it (never updated).
    let parsed = policy::parse(&text("admin-invalid-freeze-without-maintenance.json")).unwrap();
    let lab = parsed.effective(OTHER_MACHINE_ID).shared.unwrap();
    assert!(lab.freeze && lab.maintenance.is_none());
}

#[test]
fn no_freeze_next_to_a_tidy() {
    let signed: SignedPolicy = serde_json::from_str(&text("signed-policy-freeze-conflict.json")).unwrap();
    crypto::verify(&admin_key(), signed.policy.as_bytes(), &signed.signature).unwrap();
    let parsed = policy::parse(&signed.policy).unwrap();
    assert_eq!(parsed, policy::parse(&text("policy-freeze-conflict.json")).unwrap());
    let lab = parsed.effective(OTHER_MACHINE_ID);
    let wanted = lab.shared.clone().unwrap();
    assert!(shared::refusal(&wanted, &lab, 8192).unwrap().contains("folders.tidy"));
    // Applied in a test root: the guest session is set up, the freeze is not, and `applied.shared` says why.
    let root = std::env::temp_dir().join(format!("caramos-business-v3-conflict-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(root.join("usr/sbin")).unwrap();
    fs::write(root.join("usr/sbin/lightdm"), "").unwrap();
    fs::write(root.join("usr/sbin/guest-account"), "").unwrap();
    let system = System::test(&root);
    let mut managed = Managed::default();
    let result = shared::apply(&system, lab.shared.as_ref(), &lab, &mut managed, false);
    assert!(caramos_business_agent::sections::outcome(&result).starts_with("failed: no freeze while folders.tidy is on"), "{result:?}");
    assert_eq!(fs::read_to_string(system.path(shared::GUEST_CONF)).unwrap(), text("expected-lightdm-guest.conf"));
    assert!(!system.path(shared::OVERLAYROOT_CONF).exists() && !system.path(shared::GRUB_SCRIPT).exists());
    fs::remove_dir_all(&root).unwrap();
}

#[test]
fn remote_help_with_a_sealed_key() {
    let envelope: Envelope = serde_json::from_str(&text("command-remote-help.json")).unwrap();
    let decision = commands::decide(&envelope, &admin_key(), MACHINE_ID, Some("ke-toan"), &CommandRecord::default(), NOW, None);
    let Decision::Run(command) = decision else {
        panic!("{decision:?}");
    };
    let Action::RemoteHelp { admin_host, port, mode, admin_name, psk } = command.action else {
        panic!("not remote help");
    };
    assert_eq!((admin_host.to_string(), port, mode.as_str(), admin_name.as_str()), ("192.168.1.5".to_string(), 5501, "control", "quan-ly"));
    let vector = json("remote-help-psk.json");
    let plaintext: Value = serde_json::from_slice(&machine_keys().unseal(&psk, MACHINE_ID).unwrap()).unwrap();
    assert_eq!(plaintext, vector["plaintext"]);
    assert!(machine_keys().unseal(&psk, OTHER_MACHINE_ID).is_err(), "sealed for this machine only");
    let args = json!({"psk_identity": plaintext["identity"], "psk_key": plaintext["key"]});
    let (identity, key) = remotehelp::psk_from(&args).unwrap();
    assert_eq!(remotehelp::psk_line(&identity, &key), format!("{}\n", vector["psk_file_line"].as_str().unwrap()));
    // The daemon's side: the same key from the stored pairing.
    let config = caramos_business_agent::store::AgentConfig::parse(&json!({
        "admin_url": "http://192.168.1.5:47022", "admin_name": "quan-ly", "admin_key": json("keys.json")["admin_sign_public"],
        "machine_id": MACHINE_ID}).to_string()).unwrap();
    let current = daemon::Current { config, policy: None, effective: Default::default(), keys: Some(machine_keys()) };
    assert_eq!(current.remote_help_key(&psk).unwrap(), (identity, key));
}

#[test]
fn removal_notices() {
    let notice = |name: &str| -> SignedNotice {
        match PolicyAnswer::parse(text(name).as_bytes()).unwrap() {
            PolicyAnswer::Notice(notice) => notice,
            PolicyAnswer::Policy(_) => panic!("{name} is a policy"),
        }
    };
    let removal = daemon::check_notice(&notice("removed-notice.json"), &admin_key(), MACHINE_ID).unwrap();
    assert_eq!(removal, daemon::Removal { admin_name: "quan-ly".into(), time: "2026-11-23T10:00:00+07:00".into() });
    assert!(daemon::check_notice(&notice("removed-notice-other.json"), &admin_key(), MACHINE_ID).unwrap_err().contains("another machine"));
    assert!(daemon::check_notice(&notice("removed-notice-other.json"), &admin_key(), OTHER_MACHINE_ID).is_ok());
    assert!(daemon::check_notice(&notice("removed-notice-tampered.json"), &admin_key(), MACHINE_ID).unwrap_err().contains("signature"));
}

#[test]
fn tickets_for_one_user() {
    let signed: SignedTickets = serde_json::from_str(&text("tickets.json")).unwrap();
    let list = tickets::verify(&signed, &admin_key(), MACHINE_ID).unwrap();
    assert_eq!(list.version, 7);
    assert!(tickets::verify(&signed, &admin_key(), OTHER_MACHINE_ID).unwrap_err().contains("another machine"));
    let users = tickets::by_user(&list.tickets);
    let lan: Value = serde_json::from_str(&tickets::user_file(list.version, &users["lan"])).unwrap();
    assert_eq!(lan, json("tickets-user-lan.json"));
    assert_eq!(users["minh"].len(), 1);
    let wait: WaitAnswer = serde_json::from_str(&text("wait-answer.json")).unwrap();
    assert_eq!((wait.serial, wait.tickets, wait.commands.len()), (21, 7, 0));
    // HT-0007 moved from new to working with its first update: that is what lan is told.
    let before = [json!({"id": "HT-0007", "user": "lan", "status": "new", "updates": []})];
    let told = tickets::changes(&before, &users["lan"]);
    assert_eq!(told.len(), 1);
    assert_eq!((told[0].relay_id().as_str(), told[0].status.as_str(), told[0].text.as_str()), ("ticket-HT-0007-1", "working", "Bên mình đang xem, chiều nay xong."));
}

#[test]
fn origins_from_apt_cache_policy() {
    let archives = inventory::package_files(&text("apt-cache-policy-sources.txt"));
    let sources = inventory::installed_sources(&text("apt-cache-policy-packages.txt"));
    let origins: BTreeMap<String, String> = sources.iter().map(|(package, source)| (package.clone(), inventory::origin_name(source.as_ref(), &archives))).collect();
    let expected: BTreeMap<String, String> = serde_json::from_value(json("apt-origins.json")).unwrap();
    assert_eq!(origins, expected);
}

#[test]
fn inventory_apps_and_health_keys() {
    let thunar = |id: &str, name: &str, main: bool| App {
        id: id.into(),
        name: name.into(),
        version: "4.18.8-1build3".into(),
        source: "deb".into(),
        package: "thunar".into(),
        licence: "GPL-2.0".into(),
        origin: "mint".into(),
        main,
    };
    let apps = vec![
        App { id: "vlc.desktop".into(), name: "VLC".into(), version: "3.0.20-3build6".into(), source: "deb".into(), package: "vlc".into(), licence: "GPL-2+".into(), origin: "ubuntu-universe".into(), main: true },
        App {
            id: "google-chrome.desktop".into(),
            name: "Google Chrome".into(),
            version: "158.0.8127.36-1".into(),
            source: "deb".into(),
            package: "google-chrome-stable".into(),
            licence: "unknown".into(),
            origin: "third-party:dl.google.com".into(),
            main: true,
        },
        App {
            id: "org.libreoffice.LibreOffice".into(),
            name: "LibreOffice".into(),
            version: "25.8.3.2".into(),
            source: "flatpak".into(),
            package: "org.libreoffice.LibreOffice".into(),
            licence: "MPL-2.0".into(),
            origin: "flathub".into(),
            main: true,
        },
        thunar("thunar-bulk-rename.desktop", "Bulk Rename", false),
        thunar("thunar.desktop", "Thunar File Manager", true),
    ];
    assert_eq!(json!({"apps": apps}), json("inventory-apps.json"));

    let vector = json("health.json");
    let dynamic = ["applied", "screen_lock_on", "usb_storage", "frozen", "freeze_configured", "last_maintenance", "maintenance_result", "last_snapshot", "snapshot_space_mb"];
    let mut base = vector["health"].clone();
    for key in dynamic {
        base.as_object_mut().unwrap().remove(key);
    }
    let applied = BTreeMap::from([("shared".to_string(), "ok".to_string()), ("snapshots".to_string(), "ok".to_string())]);
    let security = health::Security {
        screen_lock_on: Some(true),
        usb_storage: "block".into(),
        frozen: false,
        freeze_configured: false,
        last_maintenance: None,
        maintenance_result: String::new(),
        maintenance_steps: None,
        last_snapshot: Some("2026-11-23T01:02:55+07:00".into()),
        snapshot_space_mb: Some(6780),
    };
    assert_eq!(health::with_security(health::with_applied(base, &applied), &security), vector["health"]);
    assert_eq!(json!(CAPABILITIES), vector["capabilities"]);
}

#[test]
fn the_files_the_agent_writes() {
    let section = Snapshots { schedule: Schedule::Weekly, keep: 3, before_update: true };
    assert_eq!(snapshots::settings_text(&section, "33113ae9-4550-4a48-a3cb-12d57f6ae6ff", ""), text("expected-timeshift.json"));
    assert_eq!(shared::overlayroot_conf(), text("expected-overlayroot.local.conf"));
    assert_eq!(shared::grub_drop_in(), text("expected-71-caramos-business.cfg"));
    assert_eq!(shared::guest_conf(), text("expected-lightdm-guest.conf"));
    assert_eq!(shared::grub_script(), text("expected-42_caramos-business-maintenance"));
    // The entry update-grub made of the script on the test VM carries the maintenance mark and id the agent looks for.
    let entry = text("expected-grub-maintenance-entry.txt");
    assert!(entry.contains(&format!("--id {}", shared::MAINTENANCE_ENTRY)) && entry.contains(shared::MAINTENANCE_ARG));
    assert!(entry.contains("overlayroot=disabled"));
}
