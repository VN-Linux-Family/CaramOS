//! The shared examples of part 1 in ../tests/protocol-examples, which the Python side's tests check too. The key, its
//! fingerprint and pairing code, and the signature are unchanged in 0.2; format 1 itself is refused now.

use std::fs;
use std::path::PathBuf;

use caramos_business_agent::crypto;
use caramos_business_agent::policy::{self, MonthDay};
use caramos_business_agent::protocol::SignedPolicy;
use ed25519_dalek::SigningKey;

const SHA: &str = "a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7";

fn examples() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/protocol-examples")
}

fn example(name: &str) -> String {
    fs::read_to_string(examples().join(name)).unwrap_or_else(|error| panic!("{name}: {error}"))
}

fn signed(name: &str) -> SignedPolicy {
    serde_json::from_str(&example(name)).unwrap()
}

/// test-key.json: the seed and public key in base64, the fingerprint and the pairing code.
struct TestKey {
    seed: [u8; 32],
    public: [u8; 32],
    fingerprint: String,
    pairing_code: String,
}

fn test_key() -> TestKey {
    let fields: serde_json::Value = serde_json::from_str(&example("test-key.json")).unwrap();
    let text = |name: &str| fields[name].as_str().unwrap().to_string();
    TestKey {
        seed: crypto::decode_key(&text("seed")).unwrap(),
        public: crypto::decode_key(&text("public")).unwrap(),
        fingerprint: text("fingerprint"),
        pairing_code: text("pairing_code"),
    }
}

#[test]
fn the_test_key_has_its_fingerprint_and_pairing_code() {
    let key = test_key();
    assert_eq!(SigningKey::from_bytes(&key.seed).verifying_key().to_bytes(), key.public);
    assert_eq!(crypto::fingerprint(&key.public), key.fingerprint);
    assert_eq!(key.fingerprint, "56475aa75463474c");
    assert_eq!(crypto::pairing_code(&key.public), key.pairing_code);
    assert_eq!(key.pairing_code, "432387");
}

#[test]
fn the_signed_policy_verifies_with_the_test_key() {
    let key = test_key();
    let good = signed("signed-policy.json");
    crypto::verify(&key.public, good.policy.as_bytes(), &good.signature).unwrap();
    // What was signed is policy.json.
    assert_eq!(good.policy, example("policy.json").trim_end());
}

#[test]
fn the_tampered_policy_does_not_verify() {
    let key = test_key();
    let tampered = signed("signed-policy-tampered.json");
    assert!(crypto::verify(&key.public, tampered.policy.as_bytes(), &tampered.signature).is_err());
    // Nor does the good one with another key, or with a signature of the wrong length.
    let good = signed("signed-policy.json");
    let other = SigningKey::from_bytes(&[7; 32]).verifying_key().to_bytes();
    assert!(crypto::verify(&other, good.policy.as_bytes(), &good.signature).is_err());
    assert!(crypto::verify(&key.public, good.policy.as_bytes(), "AAAA").is_err());
}

#[test]
fn format_1_is_refused_now() {
    let error = policy::parse(&example("policy.json")).unwrap_err();
    assert!(error.0.contains("unknown policy format 1"), "{error}");
    // Its sections keep their meaning inside format 2's settings.
    let part1: serde_json::Value = serde_json::from_str(&example("policy.json")).unwrap();
    let format2 = serde_json::json!({
        "format": 2, "serial": 7, "admin_box_key": "NYBy1jZYgNGu6jKa35EhODhR7SGijjt16WXQ0s0WYlQ=",
        "files": part1["files"], "settings": {"wallpaper": part1["wallpaper"], "folders": part1["folders"]}
    });
    let policy = policy::parse(&format2.to_string()).unwrap();
    assert_eq!(policy.file_name(SHA).as_deref(), Some(&*format!("{SHA}.jpg")));
    let effective = policy.effective("7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6");
    let wallpaper = effective.wallpaper.as_ref().unwrap();
    assert!(wallpaper.lock);
    // Tết, 12-25 to 01-05, then the default.
    assert_eq!(wallpaper.image_for(MonthDay::parse("01-01").unwrap()), Some(SHA));
    assert_eq!(wallpaper.image_for(MonthDay::parse("06-01").unwrap()), Some(SHA));
    let folders = effective.folders.as_ref().unwrap();
    assert_eq!(folders.share, "smb://nas.congty.local/nhanvien/%u");
    assert!(folders.tidy);
}

#[test]
fn every_invalid_example_is_refused() {
    let mut names: Vec<String> = fs::read_dir(examples())
        .unwrap()
        .map(|entry| entry.unwrap().file_name().into_string().unwrap())
        .filter(|name| name.starts_with("invalid-") && name.ends_with(".json"))
        .collect();
    names.sort();
    assert!(names.len() >= 9, "only {names:?}");
    for name in names {
        let error = policy::parse(&example(&name)).expect_err(&name);
        println!("{name}: {error}");
    }
}

#[test]
fn the_listed_file_has_its_sha256_and_size() {
    let part1: serde_json::Value = serde_json::from_str(&example("policy.json")).unwrap();
    for (sha, file) in part1["files"].as_object().unwrap() {
        let data = fs::read(examples().join(format!("file-{sha}"))).unwrap();
        assert_eq!(crypto::sha256_hex(&data), *sha);
        assert_eq!(data.len() as u64, file["size"].as_u64().unwrap());
    }
}
