//! `wifi`: NetworkManager profiles `/etc/NetworkManager/system-connections/caramos-business-<slug>.nmconnection`,
//! 0600 root, for every user (`permissions=` empty), with the passphrase from the machine's sealed secrets in the file
//! (`psk-flags=0`). Profiles named `caramos-business-*` that are no longer listed are removed.

use std::collections::BTreeMap;
use std::fs;
use std::time::Duration;

use sha2::{Digest, Sha256};

use super::{remove_if_present, unique_slugs, write_if_changed, Managed, System, MANAGED_BY};
use crate::settings::{Wifi, WifiSecurity};

pub const PROFILES: &str = "/etc/NetworkManager/system-connections";
const PREFIX: &str = "caramos-business-";
const TOOL_TIMEOUT: Duration = Duration::from_secs(60);

/// A stable UUID for a network, so that NetworkManager sees the same profile at every write.
pub fn profile_uuid(ssid: &str) -> String {
    let digest = Sha256::new().chain_update(b"caramos-business-wifi:").chain_update(ssid.as_bytes()).finalize();
    let mut bytes = [0u8; 16];
    bytes.copy_from_slice(&digest[..16]);
    bytes[6] = (bytes[6] & 0x0f) | 0x50;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    let hex = crate::crypto::hex(&bytes);
    format!("{}-{}-{}-{}-{}", &hex[..8], &hex[8..12], &hex[12..16], &hex[16..20], &hex[20..])
}

/// A keyfile string value, escaped as GKeyFile reads it.
fn escape(value: &str) -> String {
    let mut out = String::new();
    for (index, c) in value.chars().enumerate() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\t' => out.push_str("\\t"),
            '\r' => out.push_str("\\r"),
            ' ' if index == 0 => out.push_str("\\s"),
            c => out.push(c),
        }
    }
    out
}

/// The SSID as keyfile text: plain when it is plain, else its bytes ("67;111;…;"), which NetworkManager also reads.
fn ssid_value(ssid: &str) -> String {
    let plain = ssid.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte));
    if plain {
        ssid.to_string()
    } else {
        ssid.bytes().fold(String::new(), |mut text, byte| {
            text.push_str(&byte.to_string());
            text.push(';');
            text
        })
    }
}

/// A WPA passphrase: 8 to 63 printable ASCII characters.
pub fn valid_passphrase(passphrase: &str) -> bool {
    (8..=63).contains(&passphrase.len()) && passphrase.bytes().all(|byte| (32..=126).contains(&byte))
}

/// The profile of one network.
pub fn profile(name: &str, network: &Wifi, passphrase: Option<&str>) -> String {
    let mut text = format!(
        "# {MANAGED_BY}\n[connection]\nid={name}\nuuid={}\ntype=wifi\npermissions=\nautoconnect=true\n\n\
         [wifi]\nmode=infrastructure\nssid={}\nhidden={}\n\n",
        profile_uuid(&network.ssid),
        ssid_value(&network.ssid),
        network.hidden
    );
    if let (WifiSecurity::WpaPsk, Some(passphrase)) = (network.security, passphrase) {
        text.push_str(&format!("[wifi-security]\nkey-mgmt=wpa-psk\npsk={}\npsk-flags=0\n\n", escape(passphrase)));
    }
    text.push_str("[ipv4]\nmethod=auto\n\n[ipv6]\naddr-gen-mode=default\nmethod=auto\n");
    text
}

/// Writes the profiles of the listed networks (None removes the agent's), with the passphrases from `secrets`
/// (ssid → passphrase).
pub fn apply(system: &System, wifi: Option<&[Wifi]>, secrets: &BTreeMap<String, String>, managed: &mut Managed) -> Result<(), String> {
    let networks = wifi.unwrap_or_default();
    let folder = system.path(PROFILES);
    let mut errors = Vec::new();
    let mut wanted = Vec::new();
    let mut changed = false;
    for (slug, network) in unique_slugs(networks.iter().map(|network| network.ssid.as_str())).into_iter().zip(networks) {
        let name = format!("{PREFIX}{slug}");
        let passphrase = secrets.get(&network.ssid).map(String::as_str);
        if network.security == WifiSecurity::WpaPsk && !passphrase.is_some_and(valid_passphrase) {
            errors.push(format!("no valid passphrase for {} in the sealed secrets", network.ssid));
            continue;
        }
        let file = folder.join(format!("{name}.nmconnection"));
        match write_if_changed(&file, profile(&name, network, passphrase).as_bytes(), 0o600) {
            Ok(written) => changed |= written,
            Err(error) => errors.push(format!("{}: {error}", network.ssid)),
        }
        wanted.push(format!("{name}.nmconnection"));
    }
    let present: Vec<String> = fs::read_dir(&folder)
        .map(|entries| {
            entries
                .flatten()
                .filter_map(|entry| entry.file_name().into_string().ok())
                .filter(|name| name.starts_with(PREFIX) && name.ends_with(".nmconnection"))
                .collect()
        })
        .unwrap_or_default();
    for name in present.iter().filter(|name| !wanted.contains(name)) {
        match remove_if_present(&folder.join(name)) {
            Ok(removed) => changed |= removed,
            Err(error) => errors.push(format!("{name}: {error}")),
        }
    }
    managed.wifi = wanted;
    if changed {
        if let Err(error) = system.check("nmcli", &["connection", "reload"], TOOL_TIMEOUT) {
            errors.push(error);
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
    use crate::testutil::TempDir;

    fn network(ssid: &str, security: WifiSecurity) -> Wifi {
        Wifi { ssid: ssid.into(), security, hidden: false }
    }

    #[test]
    fn profiles() {
        let text = profile("caramos-business-congty", &network("CongTy", WifiSecurity::WpaPsk), Some("matkhau-wifi-123"));
        assert!(text.starts_with("# Managed by CaramOS Doanh nghiệp"));
        assert!(text.contains("\nid=caramos-business-congty\n"));
        assert!(text.contains("\nssid=CongTy\n"));
        assert!(text.contains("\npermissions=\n"));
        assert!(text.contains("\npsk=matkhau-wifi-123\npsk-flags=0\n"));
        assert!(!profile("x", &network("Khách", WifiSecurity::Open), None).contains("wifi-security"));
        assert!(profile("x", &network("Tầng 2", WifiSecurity::Open), None).contains("\nssid=84;225;186;167;110;103;32;50;\n"));
        assert_eq!(profile_uuid("CongTy"), profile_uuid("CongTy"));
        assert_ne!(profile_uuid("CongTy"), profile_uuid("Khach"));
        assert_eq!(escape(" a\\b"), "\\sa\\\\b");
        assert!(valid_passphrase("12345678") && !valid_passphrase("1234567") && !valid_passphrase("mật khẩu dài"));
    }

    #[test]
    fn files_follow_the_list() {
        let root = TempDir::new("wifi");
        let system = System::test(root.path());
        let mut managed = Managed::default();
        let secrets = BTreeMap::from([("CongTy".to_string(), "matkhau-wifi-123".to_string())]);
        let networks = [network("CongTy", WifiSecurity::WpaPsk), network("Khach", WifiSecurity::Open), network("Kho", WifiSecurity::WpaPsk)];
        let error = apply(&system, Some(&networks), &secrets, &mut managed).unwrap_err();
        assert!(error.contains("Kho"), "{error}");
        let file = system.path(PROFILES).join("caramos-business-congty.nmconnection");
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(&file).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(managed.wifi, ["caramos-business-congty.nmconnection", "caramos-business-khach.nmconnection"]);
        fs::write(system.path(PROFILES).join("Home.nmconnection"), "the user's own").unwrap();
        apply(&system, None, &secrets, &mut managed).unwrap();
        assert!(!file.exists());
        assert!(system.path(PROFILES).join("Home.nmconnection").exists());
    }
}
