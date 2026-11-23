//! Finding the admin again after its address changed (PROTOCOL.md "Discovery"): the only discovery the agent does
//! after pairing. An answer carrying the pinned fingerprint only names a candidate; the service moves to it only
//! after it served a policy signed with the pinned key.

use std::collections::BTreeSet;
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, UdpSocket};
use std::time::{Duration, Instant};

use crate::protocol::{self, DISCOVERY_PORT, MAX_DATAGRAM};

/// How long the agent listens for answers.
pub const LISTEN: Duration = Duration::from_millis(2500);

/// The admins with `fingerprint` that answer a broadcast on the LAN, as (IPv4 address, HTTP port).
pub fn find_admin(fingerprint: &str) -> Vec<(Ipv4Addr, u16)> {
    find_admin_at(SocketAddrV4::new(Ipv4Addr::BROADCAST, DISCOVERY_PORT), fingerprint, LISTEN)
}

/// The same, asking `target` instead of the broadcast address.
pub fn find_admin_at(target: SocketAddrV4, fingerprint: &str, listen: Duration) -> Vec<(Ipv4Addr, u16)> {
    let mut found = BTreeSet::new();
    // From discovery's own port when it is free: the firewall section lets answers in on that port only. Else any port
    // (fine without a firewall).
    let Ok(socket) = UdpSocket::bind((Ipv4Addr::UNSPECIFIED, DISCOVERY_PORT)).or_else(|_| UdpSocket::bind((Ipv4Addr::UNSPECIFIED, 0))) else {
        return Vec::new();
    };
    if socket.set_broadcast(true).is_err() || socket.set_read_timeout(Some(Duration::from_millis(100))).is_err() {
        return Vec::new();
    }
    let request = protocol::discover_datagram();
    let started = Instant::now();
    let mut sent: u32 = 0;
    // One byte more than a datagram may have, to see the ones that are too long.
    let mut buffer = [0u8; MAX_DATAGRAM + 1];
    while started.elapsed() < listen {
        // Three requests in the first second: one lost datagram does not hide the admin.
        if sent < 3 && started.elapsed() >= Duration::from_millis(400) * sent {
            let _ = socket.send_to(&request, target);
            sent += 1;
        }
        if let Ok((count, SocketAddr::V4(peer))) = socket.recv_from(&mut buffer) {
            let local_test = target.ip().is_loopback() && peer.ip().is_loopback();
            if let Some(admin) = accept(&buffer[..count], *peer.ip(), fingerprint, local_test) {
                found.insert(admin);
            }
        }
    }
    found.into_iter().collect()
}

/// The admin that `datagram` from `peer` names, when it is a valid HERE with `fingerprint` from the LAN (or from
/// this machine, for `allow_loopback`).
pub fn accept(datagram: &[u8], peer: Ipv4Addr, fingerprint: &str, allow_loopback: bool) -> Option<(Ipv4Addr, u16)> {
    let here = protocol::parse_here(datagram)?;
    let from_lan = is_lan(peer) || (allow_loopback && peer.is_loopback());
    (here.fingerprint == fingerprint && from_lan).then_some((peer, here.port))
}

/// Private and link-local IPv4 addresses: the company LAN.
pub fn is_lan(ip: Ipv4Addr) -> bool {
    ip.is_private() || ip.is_link_local()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::thread;

    const PRINT: &str = "56475aa75463474c";

    fn here(fingerprint: &str, port: u16) -> Vec<u8> {
        format!(r#"CARAMOS-BUSINESS/1 HERE {{"name": "may-quan-ly", "port": {port}, "fingerprint": "{fingerprint}", "pairing": false}}"#)
            .into_bytes()
    }

    #[test]
    fn answers_are_checked() {
        let lan = Ipv4Addr::new(192, 168, 1, 20);
        assert_eq!(accept(&here(PRINT, 47022), lan, PRINT, false), Some((lan, 47022)));
        assert_eq!(accept(&here("0000000000000000", 47022), lan, PRINT, false), None);
        assert_eq!(accept(&here(PRINT, 47022), Ipv4Addr::new(8, 8, 8, 8), PRINT, false), None);
        assert_eq!(accept(&here(PRINT, 47022), Ipv4Addr::LOCALHOST, PRINT, false), None);
        assert_eq!(accept(b"CARAMOS-BUSINESS/1 DISCOVER", lan, PRINT, false), None);
    }

    #[test]
    fn asks_and_listens() {
        // A stand-in admin on this machine: it answers DISCOVER only, once with another fingerprint, once with ours.
        let admin = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let address = match admin.local_addr().unwrap() {
            SocketAddr::V4(address) => address,
            SocketAddr::V6(_) => unreachable!(),
        };
        let responder = thread::spawn(move || {
            let mut buffer = [0u8; 4096];
            let (count, peer) = admin.recv_from(&mut buffer).unwrap();
            assert_eq!(&buffer[..count], b"CARAMOS-BUSINESS/1 DISCOVER");
            admin.send_to(&here("0123456789abcdef", 40000), peer).unwrap();
            admin.send_to(&here(PRINT, 47123), peer).unwrap();
        });
        let found = find_admin_at(address, PRINT, Duration::from_millis(800));
        responder.join().unwrap();
        assert_eq!(found, vec![(Ipv4Addr::LOCALHOST, 47123)]);
    }
}
