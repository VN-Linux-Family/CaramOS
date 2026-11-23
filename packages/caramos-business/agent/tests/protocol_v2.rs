//! The version 0.2 vectors in ../tests/protocol-examples/v2 (made by make_v2.py), which the Python side's tests check
//! too: keys and derived keys, request MACs, a sealed blob, a signed format 2 policy with the effective settings of two
//! machines, invalid policies, and signed commands.

use std::fs;
use std::path::PathBuf;

use caramos_business_agent::commands::{self, Action, CommandRecord, Decision};
use caramos_business_agent::crypto::{self, SharedKeys};
use caramos_business_agent::policy;
use caramos_business_agent::protocol::{Envelope, ResultState, SignedPolicy};
use serde_json::Value;

const MACHINE_ID: &str = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";
const OTHER_MACHINE_ID: &str = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f";
/// After every vector's `issued` and before `2099-01-01`, after the expired one's `expires`.
const NOW: i64 = 1_795_300_000;

fn v2() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/protocol-examples/v2")
}

fn text(name: &str) -> String {
    fs::read_to_string(v2().join(name)).unwrap_or_else(|error| panic!("{name}: {error}"))
}

fn json(name: &str) -> Value {
    serde_json::from_str(&text(name)).unwrap()
}

fn key(keys: &Value, name: &str) -> [u8; 32] {
    crypto::decode_key32(keys[name].as_str().unwrap(), name).unwrap()
}

fn hex(bytes: &[u8]) -> String {
    crypto::hex(bytes)
}

fn machine_keys() -> SharedKeys {
    let keys = json("keys.json");
    SharedKeys::derive(&key(&keys, "machine_box_seed"), &key(&keys, "admin_box_public")).unwrap()
}

#[test]
fn box_keys_and_the_derived_keys() {
    let keys = json("keys.json");
    assert_eq!(crypto::box_public(&key(&keys, "machine_box_seed")), key(&keys, "machine_box_public"));
    assert_eq!(crypto::box_public(&key(&keys, "admin_box_seed")), key(&keys, "admin_box_public"));
    let machine = machine_keys();
    let admin = SharedKeys::derive(&key(&keys, "admin_box_seed"), &key(&keys, "machine_box_public")).unwrap();
    assert_eq!(machine, admin, "both sides derive the same keys");
    assert_eq!(hex(&machine.mac_key), keys["mac_key_hex"].as_str().unwrap());
    assert_eq!(hex(&machine.seal_key), keys["seal_key_hex"].as_str().unwrap());
    // A low-order public key would make the secret public: refused.
    assert!(SharedKeys::derive(&key(&keys, "machine_box_seed"), &[0u8; 32]).is_err());
}

#[test]
fn request_macs() {
    let keys = machine_keys();
    for name in ["mac.json", "mac-wait.json"] {
        let vector = json(name);
        let mac = keys.request_mac(
            vector["method"].as_str().unwrap(),
            vector["path"].as_str().unwrap(),
            vector["time"].as_i64().unwrap(),
            vector["body"].as_str().unwrap().as_bytes(),
        );
        assert_eq!(mac, vector["mac"].as_str().unwrap(), "{name}");
    }
    let post = json("mac.json");
    let other_time = keys.request_mac("POST", post["path"].as_str().unwrap(), 1_795_200_001, post["body"].as_str().unwrap().as_bytes());
    assert_ne!(other_time, post["mac"].as_str().unwrap());
}

#[test]
fn sealed_secrets_open_only_for_their_machine() {
    let vector = json("sealed.json");
    let keys = machine_keys();
    let sealed = vector["sealed"].as_str().unwrap();
    let plaintext: Value = serde_json::from_slice(&keys.unseal(sealed, MACHINE_ID).unwrap()).unwrap();
    assert_eq!(plaintext, vector["plaintext"]);
    assert_eq!(plaintext["wifi"]["CongTy"], "matkhau-wifi-123");
    assert!(keys.unseal(sealed, OTHER_MACHINE_ID).is_err(), "aad is the machine id");
    let mut tampered = sealed.chars().collect::<Vec<_>>();
    let last = tampered.len() - 3;
    tampered[last] = if tampered[last] == 'A' { 'B' } else { 'A' };
    assert!(keys.unseal(&tampered.into_iter().collect::<String>(), MACHINE_ID).is_err());
    assert!(keys.unseal("AAAA", MACHINE_ID).is_err());
}

#[test]
fn the_signed_policy_and_the_effective_settings() {
    let keys = json("keys.json");
    let signed: SignedPolicy = serde_json::from_str(&text("signed-policy.json")).unwrap();
    crypto::verify(&key(&keys, "admin_sign_public"), signed.policy.as_bytes(), &signed.signature).unwrap();
    let parsed = policy::parse(&signed.policy).unwrap();
    assert_eq!(parsed, policy::parse(&text("policy.json")).unwrap());
    assert_eq!(parsed.serial, 12);
    assert_eq!(parsed.admin_box_key, key(&keys, "admin_box_public"));
    // From 0.3 remote help needs no certificate in the policy: a stray `remote_help_cert` is an unknown key, ignored.
    assert!(signed.policy.contains("remote_help_cert"));
    assert_eq!(parsed.department_of(MACHINE_ID), Some("ke-toan"));
    assert_eq!(parsed.department_of(OTHER_MACHINE_ID), Some("kinh-doanh"));
    assert_eq!(parsed.sealed_for(MACHINE_ID), json("sealed.json")["sealed"].as_str());
    assert_eq!(parsed.sealed_for(OTHER_MACHINE_ID), None);

    for (machine, file) in [(MACHINE_ID, "effective-machine.json"), (OTHER_MACHINE_ID, "effective-other-machine.json")] {
        let expected: serde_json::Map<String, Value> = serde_json::from_value(json(file)).unwrap();
        assert_eq!(parsed.effective_json(machine), expected, "{file}");
    }
    let effective = parsed.effective(MACHINE_ID);
    assert_eq!(effective.screen_lock.as_ref().unwrap().idle_minutes, 5, "the machine's own layer");
    assert_eq!(effective.usb.as_ref().map(|usb| usb.storage), Some(caramos_business_agent::settings::UsbStorage::Block), "the department's layer");
    assert!(effective.browser.is_some());
    assert!(!effective.inventory_enabled(), "inventory is opt-in, absent from the vectors");
    let other = parsed.effective(OTHER_MACHINE_ID);
    assert!(other.browser.is_none(), "null turns the section off");
    assert!(other.shares.is_none() && other.apps.is_none());
    // A machine in no department and with no layer of its own gets `settings`.
    let lone = parsed.effective("11111111-2222-4333-8444-555555555555");
    assert_eq!(lone.screen_lock.as_ref().unwrap().idle_minutes, 10);
}

#[test]
fn every_invalid_policy_is_refused_for_its_reason() {
    let reasons = [
        ("invalid-apps-both.json", "both required and forbidden"),
        ("invalid-browser-domain.json", "is not a domain"),
        ("invalid-browser-hours-midnight.json", "does not cross midnight"),
        ("invalid-department-id.json", "is not a department id"),
        ("invalid-format-1.json", "unknown policy format 1"),
        ("invalid-member-unknown-department.json", "unknown department"),
        ("invalid-power-warn.json", "warn_minutes"),
        ("invalid-printer-two-defaults.json", "more than one default"),
        ("invalid-printer-uri.json", "ipp://"),
        ("invalid-screen-lock.json", "idle_minutes"),
        ("invalid-share-percent-u.json", "%u"),
        ("invalid-usb-value.json", "section usb"),
        ("invalid-wifi-ssid.json", "SSID"),
    ];
    let mut listed: Vec<String> = fs::read_dir(v2())
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
}

fn envelope(name: &str) -> Envelope {
    serde_json::from_str(&text(name)).unwrap()
}

#[test]
fn commands_from_before_this_boot() {
    // The shared commands were issued at 2026-11-21T14:00:00+07:00. On a machine that started after that, the
    // message and the lock were meant for an earlier boot; the sync still runs.
    let keys = json("keys.json");
    let boot = caramos_business_agent::clock::parse_iso8601("2026-11-21T14:30:00+07:00");
    let empty = CommandRecord::default();
    let decide_after_boot = |name: &str| {
        commands::decide(&envelope(name), &key(&keys, "admin_sign_public"), MACHINE_ID, Some("ke-toan"), &empty, NOW, boot)
    };
    for name in ["command-message.json", "command-department.json"] {
        match decide_after_boot(name) {
            Decision::Report { state, detail, .. } => {
                assert_eq!(state, ResultState::Expired, "{name}");
                assert_eq!(detail, commands::BEFORE_THIS_BOOT, "{name}");
            }
            other => panic!("{name}: {other:?}"),
        }
    }
    assert!(matches!(decide_after_boot("command-all.json"), Decision::Run(command) if command.action == Action::Sync));
}

fn decide(name: &str, machine: &str, department: Option<&str>, record: &CommandRecord) -> Decision {
    let keys = json("keys.json");
    commands::decide(&envelope(name), &key(&keys, "admin_sign_public"), machine, department, record, NOW, None)
}

fn state_of(decision: &Decision) -> Option<ResultState> {
    match decision {
        Decision::Report { state, .. } => Some(*state),
        _ => None,
    }
}

#[test]
fn signed_commands() {
    let empty = CommandRecord::default();
    let (ours, theirs) = ((MACHINE_ID, Some("ke-toan")), (OTHER_MACHINE_ID, Some("kinh-doanh")));

    match decide("command-message.json", ours.0, ours.1, &empty) {
        Decision::Run(command) => {
            assert_eq!(command.seq, 41);
            assert_eq!(command.action, Action::Message { title: "Họp 15h".into(), body: "Phòng họp tầng 3.".into(), ack: true });
        }
        other => panic!("{other:?}"),
    }
    assert_eq!(state_of(&decide("command-message.json", theirs.0, theirs.1, &empty)), Some(ResultState::Ignored));

    assert!(matches!(decide("command-department.json", ours.0, ours.1, &empty), Decision::Run(command) if command.action == Action::Lock));
    assert_eq!(state_of(&decide("command-department.json", theirs.0, theirs.1, &empty)), Some(ResultState::Ignored));
    assert_eq!(state_of(&decide("command-other-department.json", ours.0, ours.1, &empty)), Some(ResultState::Ignored));
    assert!(matches!(decide("command-other-department.json", theirs.0, theirs.1, &empty), Decision::Run(_)));
    // Without a department, a department's command is not for the machine.
    assert_eq!(state_of(&decide("command-department.json", ours.0, None, &empty)), Some(ResultState::Ignored));

    for machine in [ours, theirs] {
        assert!(matches!(decide("command-all.json", machine.0, machine.1, &empty), Decision::Run(command) if command.action == Action::Sync));
    }
    assert_eq!(state_of(&decide("command-expired.json", ours.0, ours.1, &empty)), Some(ResultState::Expired));
    assert!(matches!(decide("command-tampered.json", ours.0, ours.1, &empty), Decision::Skip(_)));
    assert_eq!(state_of(&decide("command-bad-action.json", ours.0, ours.1, &empty)), Some(ResultState::Refused));
    assert_eq!(state_of(&decide("command-bad-args.json", ours.0, ours.1, &empty)), Some(ResultState::Refused));

    // The seq must grow; an id already run is skipped without a second result.
    let mut record = CommandRecord::default();
    record.record(44, "00000000-0000-4000-8000-000000000044");
    assert_eq!(state_of(&decide("command-message.json", ours.0, ours.1, &record)), Some(ResultState::Ignored));
    assert!(matches!(decide("command-all.json", ours.0, ours.1, &record), Decision::Skip(_)));

    // Another key does not sign for the admin.
    let other_key = crypto::box_public(&[7u8; 32]);
    assert!(matches!(commands::decide(&envelope("command-all.json"), &other_key, ours.0, ours.1, &empty, NOW, None), Decision::Skip(_)));
}
