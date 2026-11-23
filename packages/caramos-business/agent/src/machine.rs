//! MACHINE of the check-in (PROTOCOL.md "HTTP"): this computer's name, its address and network card toward the
//! admin, its edition and its CaramOS version.

use std::fs;
use std::net::{IpAddr, Ipv4Addr, UdpSocket};
use std::path::Path;
use std::time::Duration;

use crate::process;
use crate::protocol::Machine;

const TOOL_TIMEOUT: Duration = Duration::from_secs(10);

/// This computer as the admin sees it, for the route toward `admin`.
pub fn describe(admin: Ipv4Addr, port: u16) -> Machine {
    let ip = address_toward(admin, port);
    Machine {
        name: hostname(),
        ip: ip.map(|ip| ip.to_string()).unwrap_or_default(),
        mac: ip.and_then(card_mac).unwrap_or_default(),
        edition: edition(Path::new("/")).to_string(),
        version: fs::read_to_string("/etc/caramos-release").map(|text| parse_release(&text)).unwrap_or_default(),
    }
}

/// The local address that the kernel picks for the route toward the admin (connecting a UDP socket sends nothing).
fn address_toward(admin: Ipv4Addr, port: u16) -> Option<Ipv4Addr> {
    let socket = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0)).ok()?;
    socket.connect((admin, port)).ok()?;
    match socket.local_addr().ok()?.ip() {
        IpAddr::V4(ip) if !ip.is_unspecified() => Some(ip),
        _ => None,
    }
}

/// The MAC address of the card that has `ip`: `ip -j -4 addr` names the card, /sys/class/net/<card>/address has it.
fn card_mac(ip: Ipv4Addr) -> Option<String> {
    let output = process::run("ip", &["-j", "-4", "addr", "show"], TOOL_TIMEOUT).ok()?;
    let card = card_with_address(&output.stdout, ip)?;
    let mac = fs::read_to_string(Path::new("/sys/class/net").join(card).join("address")).ok()?;
    let mac = mac.trim().to_ascii_lowercase();
    is_mac(&mac).then_some(mac)
}

/// The card that has `ip`, in the JSON of `ip -j -4 addr`.
pub fn card_with_address(json: &str, ip: Ipv4Addr) -> Option<String> {
    let cards: serde_json::Value = serde_json::from_str(json).ok()?;
    let wanted = ip.to_string();
    for card in cards.as_array()? {
        let has_ip = card["addr_info"]
            .as_array()
            .is_some_and(|addresses| addresses.iter().any(|address| address["local"].as_str() == Some(wanted.as_str())));
        let name = card["ifname"].as_str().unwrap_or_default();
        let name_ok = !name.is_empty() && name.len() <= 15 && !name.contains('/') && name != "." && name != "..";
        if has_ip && name_ok {
            return Some(name.to_string());
        }
    }
    None
}

/// aa:bb:cc:dd:ee:ff, lowercase, not all zeros (a card without a MAC, such as a VPN's).
pub fn is_mac(text: &str) -> bool {
    let parts: Vec<&str> = text.split(':').collect();
    parts.len() == 6
        && parts.iter().all(|part| part.len() == 2 && part.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f')))
        && text != "00:00:00:00:00:00"
}

/// The host name, as the kernel has it.
fn hostname() -> String {
    fs::read_to_string("/proc/sys/kernel/hostname")
        .or_else(|_| fs::read_to_string("/etc/hostname"))
        .map(|name| name.trim().to_string())
        .unwrap_or_default()
}

/// "cinnamon" when `<root>/usr/bin/cinnamon` exists, "xfce" with `<root>/usr/bin/xfce4-session`, else "other".
pub fn edition(root: &Path) -> &'static str {
    if root.join("usr/bin/cinnamon").exists() {
        "cinnamon"
    } else if root.join("usr/bin/xfce4-session").exists() {
        "xfce"
    } else {
        "other"
    }
}

/// `VERSION` from /etc/caramos-release (`VERSION="1.4.0"`), or "".
pub fn parse_release(text: &str) -> String {
    for line in text.lines() {
        let Some(value) = line.trim().strip_prefix("VERSION=") else {
            continue;
        };
        let value = value.trim().trim_matches(|c| c == '"' || c == '\'');
        let plain = value.len() <= 32
            && value.bytes().all(|byte| byte.is_ascii_alphanumeric() || b".+~-_".contains(&byte));
        return if plain { value.to_string() } else { String::new() };
    }
    String::new()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn release_version() {
        assert_eq!(parse_release("NAME=\"CaramOS\"\nVERSION=\"1.4.0\"\nEDITION=cinnamon\n"), "1.4.0");
        assert_eq!(parse_release("VERSION=1.3.11\n"), "1.3.11");
        assert_eq!(parse_release("VERSION=\"$(reboot)\"\n"), "");
        assert_eq!(parse_release("NAME=x\n"), "");
    }

    #[test]
    fn card_of_an_address() {
        let json = r#"[{"ifindex":1,"ifname":"lo","addr_info":[{"family":"inet","local":"127.0.0.1","prefixlen":8}]},
                       {"ifindex":2,"ifname":"enp1s0","addr_info":[{"family":"inet","local":"192.168.1.23","prefixlen":24}]},
                       {"ifindex":3,"ifname":"../../etc","addr_info":[{"family":"inet","local":"10.0.0.5","prefixlen":8}]}]"#;
        assert_eq!(card_with_address(json, Ipv4Addr::new(192, 168, 1, 23)), Some("enp1s0".to_string()));
        assert_eq!(card_with_address(json, Ipv4Addr::new(10, 0, 0, 5)), None);
        assert_eq!(card_with_address(json, Ipv4Addr::new(192, 168, 1, 99)), None);
        assert_eq!(card_with_address("not json", Ipv4Addr::LOCALHOST), None);
    }

    #[test]
    fn mac_addresses() {
        assert!(is_mac("52:54:00:12:34:56"));
        assert!(!is_mac("52:54:00:12:34"));
        assert!(!is_mac("52:54:00:12:34:5G"));
        assert!(!is_mac("00:00:00:00:00:00"));
    }

    #[test]
    fn editions() {
        let dir = crate::testutil::TempDir::new("edition");
        assert_eq!(edition(dir.path()), "other");
        fs::create_dir_all(dir.path().join("usr/bin")).unwrap();
        fs::write(dir.path().join("usr/bin/xfce4-session"), "").unwrap();
        assert_eq!(edition(dir.path()), "xfce");
        fs::write(dir.path().join("usr/bin/cinnamon"), "").unwrap();
        assert_eq!(edition(dir.path()), "cinnamon");
    }
}
