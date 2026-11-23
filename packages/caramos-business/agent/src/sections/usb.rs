//! `usb`: USB storage read-only (a udev rule that makes udisks mount it read-only) or blocked (a polkit rule that
//! denies mounting it to every user). Keyboards, mice, printers and signature tokens (smart cards) keep working: only
//! file-system mounts change. `usb_unlock` allows USB storage until a time, whatever the section says.

use std::time::Duration;

use super::{remove_if_present, write_if_changed, Managed, System, MANAGED_BY};
use crate::settings::{Usb, UsbStorage};

pub const UDEV_RULE: &str = "/etc/udev/rules.d/71-caramos-business-usb.rules";
pub const POLKIT_RULE: &str = "/etc/polkit-1/rules.d/71-caramos-business-usb.rules";
const TOOL_TIMEOUT: Duration = Duration::from_secs(60);

/// udisks2 reads these udev properties of a block device: read-only by default, and `rw` not among the options a user
/// may ask for (udisks' own generic list, without rw; the per-file-system lists add uid= and the like).
pub fn udev_rule() -> String {
    format!(
        "# {MANAGED_BY}\n\
         # USB storage mounts read-only.\n\
         SUBSYSTEM==\"block\", SUBSYSTEMS==\"usb\", ENV{{UDISKS_MOUNT_OPTIONS_DEFAULTS}}=\"ro\", \
         ENV{{UDISKS_MOUNT_OPTIONS_ALLOW}}=\"exec,noexec,nodev,nosuid,atime,noatime,nodiratime,relatime,strictatime,lazytime,ro,sync,dirsync,noload,acl,nosymfollow\"\n"
    )
}

/// polkit denies udisks' mount actions for drives on the USB bus, to every user.
pub fn polkit_rule() -> String {
    format!(
        "// {MANAGED_BY}\n\
         // USB storage cannot be mounted.\n\
         polkit.addRule(function(action, subject) {{\n\
         \x20   if (action.id.indexOf(\"org.freedesktop.udisks2.filesystem-mount\") === 0 &&\n\
         \x20       action.lookup(\"drive.removable.bus\") === \"usb\") {{\n\
         \x20       return polkit.Result.NO;\n\
         \x20   }}\n\
         }});\n"
    )
}

/// What the section means now: an unexpired `usb_unlock` allows USB storage.
pub fn storage_now(usb: Option<&Usb>, managed: &Managed, now: i64) -> UsbStorage {
    if managed.usb_unlock_until.is_some_and(|until| now < until) {
        return UsbStorage::Allow;
    }
    usb.map_or(UsbStorage::Allow, |usb| usb.storage)
}

/// Writes or removes the rules for the section at `now`.
pub fn apply(system: &System, usb: Option<&Usb>, managed: &mut Managed, now: i64) -> Result<(), String> {
    if managed.usb_unlock_until.is_some_and(|until| now >= until) {
        managed.usb_unlock_until = None;
    }
    let storage = storage_now(usb, managed, now);
    let (udev, polkit) = match storage {
        UsbStorage::ReadOnly => (Some(udev_rule()), None),
        UsbStorage::Block => (None, Some(polkit_rule())),
        UsbStorage::Allow => (None, None),
    };
    let mut written = Vec::new();
    let mut udev_changed = false;
    for (file, text) in [(UDEV_RULE, udev), (POLKIT_RULE, polkit)] {
        let path = system.path(file);
        let changed = match text {
            Some(text) => {
                written.push(file.to_string());
                write_if_changed(&path, text.as_bytes(), 0o644)
            }
            None => remove_if_present(&path),
        }
        .map_err(|error| format!("{file}: {error}"))?;
        udev_changed |= changed && file == UDEV_RULE;
    }
    managed.usb = written;
    if udev_changed {
        // polkit reads its rules again by itself; udev needs telling, and the devices already plugged in a change event.
        system.check("udevadm", &["control", "--reload"], TOOL_TIMEOUT)?;
        system.check("udevadm", &["trigger", "--subsystem-match=block", "--action=change"], TOOL_TIMEOUT)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    #[test]
    fn rules_follow_the_section_and_the_unlock() {
        let root = TempDir::new("usb");
        let system = System::test(root.path());
        let mut managed = Managed::default();
        let read_only = Usb { storage: UsbStorage::ReadOnly };
        apply(&system, Some(&read_only), &mut managed, 100).unwrap();
        let rule = std::fs::read_to_string(system.path(UDEV_RULE)).unwrap();
        assert!(rule.starts_with("# Managed by CaramOS Doanh nghiệp"));
        assert!(rule.contains("UDISKS_MOUNT_OPTIONS_DEFAULTS}=\"ro\""));
        assert!(!rule.contains(",rw,"));
        assert!(!system.path(POLKIT_RULE).exists());

        apply(&system, Some(&Usb { storage: UsbStorage::Block }), &mut managed, 100).unwrap();
        assert!(!system.path(UDEV_RULE).exists());
        assert!(std::fs::read_to_string(system.path(POLKIT_RULE)).unwrap().contains("drive.removable.bus"));
        assert_eq!(managed.usb, [POLKIT_RULE]);

        managed.usb_unlock_until = Some(200);
        apply(&system, Some(&Usb { storage: UsbStorage::Block }), &mut managed, 150).unwrap();
        assert!(!system.path(POLKIT_RULE).exists());
        apply(&system, Some(&Usb { storage: UsbStorage::Block }), &mut managed, 200).unwrap();
        assert!(system.path(POLKIT_RULE).exists());
        assert_eq!(managed.usb_unlock_until, None);

        apply(&system, None, &mut managed, 300).unwrap();
        assert!(!system.path(POLKIT_RULE).exists() && !system.path(UDEV_RULE).exists());
        assert!(managed.usb.is_empty());
    }
}
