//! `printers`: IPP queues named `caramos-<slug>`, made with lpadmin. Queues named `caramos-*` that are no longer listed
//! are removed; no other queue is touched.
//!
//! `-m everywhere` asks the printer for its capabilities, so it fails for a printer that does not answer. Such a
//! printer still gets its queue, without a driver, so that it stays in the list; its state is reported, and the
//! driver is tried again once the printer answers.

use std::collections::BTreeMap;
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

use super::{unique_slugs, Managed, System};
use crate::settings::Printer;

const PREFIX: &str = "caramos-";
const LPADMIN_TIMEOUT: Duration = Duration::from_secs(120);
const TOOL_TIMEOUT: Duration = Duration::from_secs(30);
const PROBE_TIMEOUT: Duration = Duration::from_secs(3);

/// The queue names for the listed printers, in order.
pub fn queue_names(printers: &[Printer]) -> Vec<String> {
    unique_slugs(printers.iter().map(|printer| printer.name.as_str())).into_iter().map(|slug| format!("{PREFIX}{slug}")).collect()
}

/// The `caramos-*` queues CUPS has, with their device URIs, from `lpstat -v`.
pub fn parse_lpstat_devices(output: &str) -> BTreeMap<String, String> {
    output
        .lines()
        .filter_map(|line| line.strip_prefix("device for "))
        .filter_map(|rest| rest.split_once(": "))
        .filter(|(queue, _)| queue.starts_with(PREFIX))
        .map(|(queue, uri)| (queue.to_string(), uri.trim().to_string()))
        .collect()
}

/// The host and port of an ipp:// or ipps:// URI (631 when it names none).
pub fn host_port(uri: &str) -> Option<(String, u16)> {
    let rest = uri.strip_prefix("ipps://").or_else(|| uri.strip_prefix("ipp://"))?;
    let authority = rest.split(['/', '?', '#']).next()?;
    match authority.rsplit_once(':') {
        Some((host, port)) if !host.ends_with(']') || authority.starts_with('[') => {
            Some((host.trim_matches(|c| c == '[' || c == ']').to_string(), port.parse().ok()?))
        }
        _ => Some((authority.trim_matches(|c| c == '[' || c == ']').to_string(), 631)),
    }
}

/// Whether the printer answers on its IPP port.
fn answers(uri: &str) -> bool {
    let Some((host, port)) = host_port(uri) else {
        return false;
    };
    let Ok(addresses) = (host.as_str(), port).to_socket_addrs() else {
        return false;
    };
    addresses.into_iter().any(|address| TcpStream::connect_timeout(&address, PROBE_TIMEOUT).is_ok())
}

/// Applies the section (None removes the agent's queues).
pub fn apply(system: &System, printers: Option<&[Printer]>, managed: &mut Managed) -> Result<(), String> {
    let printers = printers.unwrap_or_default();
    let names = queue_names(printers);
    let existing = parse_lpstat_devices(&system.run("lpstat", &["-v"], TOOL_TIMEOUT)?.stdout);
    let mut errors = Vec::new();
    let mut pending = Vec::new();
    for (queue, printer) in names.iter().zip(printers) {
        let was_pending = managed.printers_pending.contains(queue);
        let reachable = !system.commands || answers(&printer.uri);
        let exists = existing.get(queue).is_some_and(|uri| *uri == printer.uri);
        let mut has_driver = exists && !was_pending;
        if !exists || (was_pending && reachable) {
            match make_queue(system, queue, printer, reachable) {
                Ok(with_driver) => has_driver = with_driver,
                Err(error) => {
                    errors.push(format!("{}: {error}", printer.name));
                    continue;
                }
            }
        }
        if !has_driver {
            pending.push(queue.clone());
        }
        if !reachable {
            errors.push(format!("{} does not answer", printer.name));
        }
    }
    if let Some(queue) = names.iter().zip(printers).find(|(_, printer)| printer.default).map(|(queue, _)| queue) {
        let current = system.run("lpstat", &["-d"], TOOL_TIMEOUT)?.stdout;
        if !current.trim_end().ends_with(&format!(": {queue}")) {
            if let Err(error) = system.check("lpadmin", &["-d", queue], TOOL_TIMEOUT) {
                errors.push(error);
            }
        }
    }
    for queue in existing.keys().filter(|queue| !names.contains(queue)) {
        if let Err(error) = system.check("lpadmin", &["-x", queue], TOOL_TIMEOUT) {
            errors.push(error);
        }
    }
    managed.printers = names;
    managed.printers_pending = pending;
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

/// Makes or updates a queue: driverless (`-m everywhere`) when the printer answers, else without a driver for now.
/// Whether it got the driver.
fn make_queue(system: &System, queue: &str, printer: &Printer, reachable: bool) -> Result<bool, String> {
    let plain = ["-p", queue, "-E", "-v", &printer.uri, "-D", &printer.name, "-L", &printer.location, "-o", "printer-is-shared=false"];
    if reachable {
        let mut everywhere = plain.to_vec();
        everywhere.extend(["-m", "everywhere"]);
        if system.check("lpadmin", &everywhere, LPADMIN_TIMEOUT).is_ok() {
            return Ok(true);
        }
        // It answered the probe but not IPP Everywhere: keep the queue in the list without a driver.
    }
    system.check("lpadmin", &plain, LPADMIN_TIMEOUT).map(|_| false)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn printer(name: &str, uri: &str, default: bool) -> Printer {
        Printer { name: name.into(), uri: uri.into(), location: "Tầng 2".into(), default }
    }

    #[test]
    fn names_devices_and_hosts() {
        let printers = [printer("Máy in tầng 2", "ipp://192.168.1.50/ipp/print", true), printer("Máy in tầng 2", "ipp://10.0.0.2/ipp/print", false)];
        assert_eq!(queue_names(&printers), ["caramos-may-in-tang-2", "caramos-may-in-tang-2-2"]);
        let lpstat = "device for HP_LaserJet: usb://HP/LaserJet\ndevice for caramos-may-in-tang-2: ipp://192.168.1.50/ipp/print\n";
        let devices = parse_lpstat_devices(lpstat);
        assert_eq!(devices.len(), 1);
        assert_eq!(devices["caramos-may-in-tang-2"], "ipp://192.168.1.50/ipp/print");
        assert_eq!(host_port("ipp://192.168.1.50/ipp/print"), Some(("192.168.1.50".into(), 631)));
        assert_eq!(host_port("ipps://printer.local:8631/ipp/print"), Some(("printer.local".into(), 8631)));
    }

    #[test]
    fn queues_are_tracked() {
        let root = crate::testutil::TempDir::new("printers");
        let system = System::test(root.path());
        let mut managed = Managed::default();
        apply(&system, Some(&[printer("Kế toán", "ipp://10.0.0.9/ipp/print", false)]), &mut managed).unwrap();
        assert_eq!(managed.printers, ["caramos-ke-toan"]);
        apply(&system, None, &mut managed).unwrap();
        assert!(managed.printers.is_empty());
    }
}
