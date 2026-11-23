//! `firewall`: ufw on, denying incoming and allowing outgoing connections. Only `true` is managed: the agent never
//! turns the firewall off while the machine is in the company. It opens one port, UDP 47021, where discovery's answers
//! come in (discovery sends from that port: an answer to a broadcast comes from the admin's own address, which ufw's
//! connection tracking does not match, so without the rule a moved admin could not be found). What ufw was like before
//! the agent first changed it is kept in managed.json, and put back only when the machine leaves
//! (`caramos-business-agent leave`).

use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::{Managed, System};
use crate::settings::Firewall;

/// ufw before the agent first changed it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FirewallBefore {
    pub active: bool,
    /// The default policies in ufw's words: "deny", "allow" or "reject".
    pub incoming: String,
    pub outgoing: String,
    /// Whether ufw allowed UDP 47021 already (then leaving keeps the rule).
    #[serde(default)]
    pub discovery_rule: bool,
}

/// The rule for discovery's answers, in ufw's words.
const DISCOVERY_RULE: &str = "47021/udp";

/// A policy of /etc/default/ufw (DROP, ACCEPT, REJECT) in ufw's words.
fn policy_word(value: &str) -> Option<&'static str> {
    match value.trim().trim_matches('"') {
        "DROP" => Some("deny"),
        "ACCEPT" => Some("allow"),
        "REJECT" => Some("reject"),
        _ => None,
    }
}

/// The default incoming and outgoing policies in /etc/default/ufw's text.
pub fn default_policies(text: &str) -> (Option<&'static str>, Option<&'static str>) {
    let find = |key: &str| text.lines().find_map(|line| line.trim().strip_prefix(key)?.strip_prefix('=').and_then(policy_word));
    (find("DEFAULT_INPUT_POLICY"), find("DEFAULT_OUTPUT_POLICY"))
}

const UFW_TIMEOUT: Duration = Duration::from_secs(120);

/// "on", "off" or "unknown", from `ufw status`, for the health report.
pub fn status(system: &System) -> &'static str {
    match system.run("ufw", &["status"], UFW_TIMEOUT) {
        Ok(output) if output.stdout.contains("Status: active") => "on",
        Ok(output) if output.stdout.contains("Status: inactive") => "off",
        _ => "unknown",
    }
}

/// Whether `ufw status verbose` shows ufw on with the wanted defaults and discovery's port open.
pub fn is_as_wanted(verbose: &str) -> bool {
    verbose.contains("Status: active") && verbose.contains("deny (incoming)") && verbose.contains("allow (outgoing)")
        && has_discovery_rule(verbose)
}

/// Whether `ufw status` (or `ufw show added`, for a ufw that is off) lists the rule allowing UDP 47021 in.
pub fn has_discovery_rule(text: &str) -> bool {
    text.lines().any(|line| {
        let words: Vec<&str> = line.split_whitespace().collect();
        let allows = words.windows(2).any(|pair| pair == ["ALLOW", "IN"]) || words.first() == Some(&"ufw") && words.contains(&"allow");
        allows && words.iter().any(|word| *word == DISCOVERY_RULE) && !line.contains("(v6)")
    })
}

pub fn apply(system: &System, firewall: Option<&Firewall>, managed: &mut Managed) -> Result<(), String> {
    if !firewall.is_some_and(|firewall| firewall.enabled) {
        return Ok(());
    }
    let verbose = system.check("ufw", &["status", "verbose"], UFW_TIMEOUT)?;
    if system.commands && is_as_wanted(&verbose) {
        return Ok(());
    }
    if managed.firewall.is_none() {
        let (incoming, outgoing) = default_policies(&std::fs::read_to_string(system.path("/etc/default/ufw")).unwrap_or_default());
        // ufw lists the rules it holds while off with `show added`.
        let added = system.run("ufw", &["show", "added"], UFW_TIMEOUT).map(|output| output.stdout).unwrap_or_default();
        managed.firewall = Some(FirewallBefore {
            active: verbose.contains("Status: active"),
            incoming: incoming.unwrap_or("deny").to_string(),
            outgoing: outgoing.unwrap_or("allow").to_string(),
            discovery_rule: has_discovery_rule(&verbose) || has_discovery_rule(&added),
        });
    }
    system.check("ufw", &["default", "deny", "incoming"], UFW_TIMEOUT)?;
    system.check("ufw", &["default", "allow", "outgoing"], UFW_TIMEOUT)?;
    system.check("ufw", &["allow", DISCOVERY_RULE, "comment", "CaramOS Doanh nghiep: discovery answers"], UFW_TIMEOUT)?;
    system.check("ufw", &["--force", "enable"], UFW_TIMEOUT)?;
    Ok(())
}

/// When the machine leaves: ufw as it was before the agent first changed it.
pub fn put_back(system: &System, managed: &mut Managed) -> Result<(), String> {
    let Some(before) = managed.firewall.clone() else {
        return Ok(());
    };
    for (policy, direction) in [(&before.incoming, "incoming"), (&before.outgoing, "outgoing")] {
        if matches!(policy.as_str(), "deny" | "allow" | "reject") {
            system.check("ufw", &["default", policy, direction], UFW_TIMEOUT)?;
        }
    }
    if !before.discovery_rule {
        system.check("ufw", &["delete", "allow", DISCOVERY_RULE], UFW_TIMEOUT)?;
    }
    if !before.active {
        system.check("ufw", &["disable"], UFW_TIMEOUT)?;
    }
    managed.firewall = None;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ufw_status() {
        let on = "Status: active\nLogging: on (low)\nDefault: deny (incoming), allow (outgoing), disabled (routed)\n";
        assert!(!is_as_wanted(on), "discovery's port is not open");
        let open = format!("{on}\nTo                         Action      From\n--                         ------      ----\n47021/udp                  ALLOW IN    Anywhere                   # CaramOS Doanh nghiep: discovery answers\n47021/udp (v6)             ALLOW IN    Anywhere (v6)\n");
        assert!(is_as_wanted(&open));
        assert!(has_discovery_rule("Added user rules (see 'ufw status' for running firewall):\nufw allow 47021/udp comment 'x'\n"));
        assert!(!has_discovery_rule("47021/udp (v6)             ALLOW IN    Anywhere (v6)\n"));
        assert!(!has_discovery_rule("47021/tcp                  ALLOW IN    Anywhere\n"));
        assert!(!is_as_wanted("Status: inactive\n"));
        assert!(!is_as_wanted("Status: active\nDefault: allow (incoming), allow (outgoing), disabled (routed)\n"));
    }

    #[test]
    fn the_earlier_state_is_kept_and_put_back_at_leave() {
        let defaults = "IPV6=yes\nDEFAULT_INPUT_POLICY=\"ACCEPT\"\nDEFAULT_OUTPUT_POLICY=\"ACCEPT\"\nDEFAULT_FORWARD_POLICY=\"DROP\"\n";
        assert_eq!(default_policies(defaults), (Some("allow"), Some("allow")));
        assert_eq!(default_policies("DEFAULT_INPUT_POLICY=\"DROP\"\nDEFAULT_OUTPUT_POLICY=\"REJECT\"\n"), (Some("deny"), Some("reject")));
        assert_eq!(default_policies("DEFAULT_INPUT_POLICY=\"rm -rf\"\n"), (None, None));

        let root = crate::testutil::TempDir::new("firewall");
        std::fs::create_dir_all(root.path().join("etc/default")).unwrap();
        std::fs::write(root.path().join("etc/default/ufw"), defaults).unwrap();
        let system = System::test(root.path());
        let mut managed = Managed::default();
        apply(&system, Some(&Firewall { enabled: true }), &mut managed).unwrap();
        // The test system answers every command with nothing: ufw looked off.
        let before = FirewallBefore { active: false, incoming: "allow".into(), outgoing: "allow".into(), discovery_rule: false };
        assert_eq!(managed.firewall, Some(before.clone()));
        // A later change keeps the first earlier state; the section going away keeps ufw on.
        std::fs::write(root.path().join("etc/default/ufw"), "DEFAULT_INPUT_POLICY=\"DROP\"\n").unwrap();
        apply(&system, Some(&Firewall { enabled: true }), &mut managed).unwrap();
        apply(&system, None, &mut managed).unwrap();
        assert_eq!(managed.firewall, Some(before));
        put_back(&system, &mut managed).unwrap();
        assert_eq!(managed.firewall, None);
    }
}
