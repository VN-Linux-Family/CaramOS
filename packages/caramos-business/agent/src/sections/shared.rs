//! `shared` (PROTOCOL.md part 3 "Shared machines"): a guest session on the login screen, and the freeze that undoes
//! every change at reboot, with its maintenance window.
//!
//! - **Guest:** `/etc/lightdm/lightdm.conf.d/71-caramos-business-guest.conf` lets LightDM offer its guest account
//!   (LightDM's own `guest-account` script makes it and wipes its home at logout). It takes effect when LightDM starts.
//! - **Freeze on**, in an unfrozen boot: overlayroot installed, the GRUB maintenance entry
//!   (`/etc/grub.d/42_caramos-business-maintenance`) and `GRUB_RECORDFAIL_TIMEOUT=0`, `update-grub`, then
//!   `/etc/overlayroot.local.conf`. The next boot is frozen: `/` is an overlay on a tmpfs, the disk read-only at
//!   `/media/root-ro`.
//! - **Freeze off:** frozen, `overlayroot-chroot rm -f /etc/overlayroot.local.conf` takes the file off the disk (the
//!   machine stays frozen until it restarts); in an unfrozen boot the files go and `update-grub` runs. `update-grub`
//!   never runs inside overlayroot-chroot (grub-probe cannot find the device there).
//! - **Maintenance:** at `maintenance.time` a frozen machine nobody uses restarts once into the entry
//!   (`overlayroot-chroot grub-reboot`, which writes GRUB's `next_entry` on the disk); that boot is recognised from
//!   `caramos-business.maintenance=1` on the kernel command line. The daemon runs it (daemon.rs).
//!
//! The agent does not freeze a machine whose settings also tidy its folders or take snapshots, nor one with less than
//! 3 GiB of RAM without `low_memory_ok`.

use std::fs;
use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::{remove_if_present, write_if_changed, Before, Managed, System, MANAGED_BY};
use crate::clock::LocalTime;
use crate::settings::{hhmm, Effective, Maintenance, Shared};

pub const GUEST_CONF: &str = "/etc/lightdm/lightdm.conf.d/71-caramos-business-guest.conf";
/// LightDM's script that makes the guest account and removes it at logout.
pub const GUEST_ACCOUNT: &str = "/usr/sbin/guest-account";
pub const LIGHTDM: &str = "/usr/sbin/lightdm";
pub const GRUB_SCRIPT: &str = "/etc/grub.d/42_caramos-business-maintenance";
pub const GRUB_DROP_IN: &str = "/etc/default/grub.d/71-caramos-business.cfg";
pub const OVERLAYROOT_CONF: &str = "/etc/overlayroot.local.conf";
pub const OVERLAYROOT_CHROOT: &str = "/usr/sbin/overlayroot-chroot";
/// Where a frozen machine shows its disk, read-only.
pub const LOWER: &str = "/media/root-ro";
/// The GRUB entry's id.
pub const MAINTENANCE_ENTRY: &str = "caramos-business-maintenance";
/// On the kernel command line of the maintenance boot.
pub const MAINTENANCE_ARG: &str = "caramos-business.maintenance=1";
/// pam_nologin keeps everyone but root from logging in while it exists.
pub const NOLOGIN: &str = "/run/nologin";
pub const NOLOGIN_TEXT: &str = "Máy đang bảo trì, vui lòng chờ ít phút.\n";
/// A frozen machine keeps every change in RAM: below this it needs the admin's `low_memory_ok`.
pub const MIN_MEMORY_MB: u64 = 3072;
/// The update timers, masked for each frozen boot: an install into the overlay would be repeated at every boot.
pub const UPDATE_TIMERS: [&str; 3] = ["caramos-ota-check.timer", "apt-daily.timer", "apt-daily-upgrade.timer"];
/// A maintenance window is tried again this often while someone uses the machine.
pub const RETRY_EVERY: i64 = 15 * 60;

const TOOL_TIMEOUT: Duration = Duration::from_secs(120);
const UPDATE_GRUB_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const INSTALL_TIMEOUT: Duration = Duration::from_secs(30 * 60);

/// What the agent changed for the freeze, kept in managed.json.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct FreezeBefore {
    /// `/etc/overlayroot.local.conf` before the agent first wrote it.
    #[serde(default)]
    pub overlayroot: Before,
    /// The agent installed overlayroot (it stays installed: without its configuration it does nothing).
    #[serde(default)]
    pub installed_overlayroot: bool,
}

/// The guest session's LightDM file.
pub fn guest_conf() -> String {
    format!("# {MANAGED_BY}\n[Seat:*]\nallow-guest=true\ngreeter-allow-guest=true\n")
}

/// `/etc/overlayroot.local.conf`: the whole root file system in a tmpfs overlay, swap allowed, the other mounts left
/// as they are.
pub fn overlayroot_conf() -> String {
    format!("# {MANAGED_BY}\noverlayroot=\"tmpfs:swap=1,recurse=0\"\n")
}

/// `/etc/default/grub.d/71-caramos-business.cfg`.
pub fn grub_drop_in() -> String {
    format!(
        "# {MANAGED_BY}\n# A frozen machine cannot clear GRUB's recordfail, which would show the menu for 30 s at every boot.\n\
         GRUB_RECORDFAIL_TIMEOUT=0\n"
    )
}

/// `/etc/grub.d/42_caramos-business-maintenance` (0755), as verified on the test VM: the entry `CaramOS (bảo trì)`
/// with the newest kernel, the normal entry's root and command line, plus `overlayroot=disabled` and the maintenance
/// mark.
pub fn grub_script() -> &'static str {
    r#"#!/bin/sh
# Managed by CaramOS Doanh nghiệp (caramos-business-agent): the one-time maintenance entry of shared-machine mode.
set -e
prefix="/usr"
exec_prefix="/usr"
datarootdir="/usr/share"
. "$datarootdir/grub/grub-mkconfig_lib"
kernel=$(readlink -f /boot/vmlinuz) || exit 0
initrd=$(readlink -f /boot/initrd.img) || exit 0
[ -f "$kernel" ] && [ -f "$initrd" ] || exit 0
if [ "x${GRUB_DEVICE_UUID}" = "x" ] || [ "x${GRUB_DISABLE_LINUX_UUID}" = "xtrue" ]; then
  root_arg="root=${GRUB_DEVICE}"
else
  root_arg="root=UUID=${GRUB_DEVICE_UUID}"
fi
echo "menuentry 'CaramOS (bảo trì)' --class gnu-linux --id caramos-business-maintenance {"
prepare_grub_to_access_device "${GRUB_DEVICE_BOOT}" | sed -e "s/^/\t/"
printf "\tlinux\t%s %s ro %s %s overlayroot=disabled caramos-business.maintenance=1\n" "$(make_system_path_relative_to_its_root "$kernel")" "$root_arg" "${GRUB_CMDLINE_LINUX}" "${GRUB_CMDLINE_LINUX_DEFAULT}"
printf "\tinitrd\t%s\n" "$(make_system_path_relative_to_its_root "$initrd")"
echo "}"
"#
}

/// Whether `/` is overlayroot now, from the text of /proc/self/mounts: the last mount on `/` is an overlay named
/// overlayroot.
pub fn frozen_in(mounts: &str) -> bool {
    mounts
        .lines()
        .filter_map(|line| {
            let fields: Vec<&str> = line.split_whitespace().collect();
            (fields.len() >= 3 && fields[1] == "/").then(|| (fields[0], fields[2]))
        })
        .last()
        .is_some_and(|(source, kind)| source == "overlayroot" && kind == "overlay")
}

/// Whether this boot is frozen.
pub fn is_frozen(system: &System) -> bool {
    frozen_in(&fs::read_to_string(system.path("/proc/self/mounts")).unwrap_or_default())
}

/// Whether this is the maintenance boot: the mark on the kernel command line.
pub fn is_maintenance_boot(system: &System) -> bool {
    fs::read_to_string(system.path("/proc/cmdline")).is_ok_and(|cmdline| cmdline.split_whitespace().any(|word| word == MAINTENANCE_ARG))
}

/// `MemTotal` in MiB.
pub fn memory_mb(system: &System) -> u64 {
    let meminfo = fs::read_to_string(system.path("/proc/meminfo")).unwrap_or_default();
    meminfo
        .lines()
        .find_map(|line| line.strip_prefix("MemTotal:"))
        .and_then(|value| value.split_whitespace().next()?.parse::<u64>().ok())
        .map_or(0, |kib| kib / 1024)
}

/// A path on the disk: under /media/root-ro on a frozen machine.
pub fn on_disk(system: &System, absolute: &str, frozen: bool) -> std::path::PathBuf {
    if frozen {
        system.path(&format!("{LOWER}{absolute}"))
    } else {
        system.path(absolute)
    }
}

/// Whether the agent's overlayroot.local.conf is on the disk: the next boot is frozen.
pub fn freeze_configured(system: &System, frozen: bool) -> bool {
    fs::read_to_string(on_disk(system, OVERLAYROOT_CONF, frozen)).is_ok_and(|text| text == overlayroot_conf())
}

/// Why the freeze that `shared` asks for is not used here, if it is not.
pub fn refusal(shared: &Shared, effective: &Effective, memory_mb: u64) -> Option<String> {
    if !shared.freeze {
        return None;
    }
    if effective.folders.as_ref().is_some_and(|folders| folders.tidy) {
        return Some("no freeze while folders.tidy is on".to_string());
    }
    if effective.snapshots.is_some() {
        return Some("no freeze while snapshots are on".to_string());
    }
    if memory_mb < MIN_MEMORY_MB && !shared.low_memory_ok {
        return Some(format!("no freeze with {memory_mb} MiB of RAM (less than 3 GiB) without low_memory_ok"));
    }
    None
}

/// Applies the section for this boot, or puts back what it changed when it is None (`frozen`: this boot is).
pub fn apply(system: &System, shared: Option<&Shared>, effective: &Effective, managed: &mut Managed, frozen: bool) -> Result<(), String> {
    let mut errors = Vec::new();
    if let Err(error) = guest(system, shared.is_some_and(|shared| shared.guest), managed) {
        errors.push(error);
    }
    let refused = shared.and_then(|shared| refusal(shared, effective, memory_mb(system)));
    let wanted = shared.is_some_and(|shared| shared.freeze) && refused.is_none();
    if let Some(reason) = refused {
        errors.push(reason);
    }
    let freeze = if wanted { freeze_on(system, managed, frozen) } else { freeze_off(system, managed, frozen) };
    if let Err(error) = freeze {
        errors.push(error);
    }
    if errors.is_empty() {
        Ok(())
    } else {
        Err(errors.join("; "))
    }
}

/// The guest session's file, when LightDM and its guest-account script are there.
fn guest(system: &System, wanted: bool, managed: &mut Managed) -> Result<(), String> {
    let path = system.path(GUEST_CONF);
    if !wanted {
        remove_if_present(&path).map_err(|error| format!("{GUEST_CONF}: {error}"))?;
        managed.guest = false;
        return Ok(());
    }
    let missing: Vec<&str> = [(LIGHTDM, "LightDM"), (GUEST_ACCOUNT, "LightDM's guest-account script")]
        .iter()
        .filter(|(file, _)| !system.path(file).exists())
        .map(|(_, what)| *what)
        .collect();
    if !missing.is_empty() {
        let _ = remove_if_present(&path);
        managed.guest = false;
        return Err(format!("no guest session: {} missing", missing.join(" and ")));
    }
    write_if_changed(&path, guest_conf().as_bytes(), 0o644).map_err(|error| format!("{GUEST_CONF}: {error}"))?;
    managed.guest = true;
    Ok(())
}

/// The freeze from the next boot on.
fn freeze_on(system: &System, managed: &mut Managed, frozen: bool) -> Result<(), String> {
    if frozen {
        // Turned off and on again within one frozen boot: the file goes back on the disk (the GRUB entry stayed).
        if freeze_configured(system, true) {
            return Ok(());
        }
        return chroot_write(system, OVERLAYROOT_CONF, &overlayroot_conf()).map(|_| ());
    }
    if !system.has_any(&[OVERLAYROOT_CHROOT]) {
        let mut command = std::process::Command::new("apt-get");
        command
            .args(["-y", "-q", "-o", "DPkg::Lock::Timeout=600", "install", "overlayroot"])
            .env("LC_ALL", "C")
            .env("DEBIAN_FRONTEND", "noninteractive");
        if system.commands {
            let output = crate::process::run_command(command, INSTALL_TIMEOUT).map_err(|error| format!("apt-get: {error}"))?;
            if !output.success() {
                return Err(format!("cannot install overlayroot: {}", output.message()));
            }
        }
        managed.freeze.get_or_insert_with(FreezeBefore::default).installed_overlayroot = true;
    }
    let script = write_if_changed(&system.path(GRUB_SCRIPT), grub_script().as_bytes(), 0o755).map_err(|error| format!("{GRUB_SCRIPT}: {error}"))?;
    let drop_in = write_if_changed(&system.path(GRUB_DROP_IN), grub_drop_in().as_bytes(), 0o644).map_err(|error| format!("{GRUB_DROP_IN}: {error}"))?;
    if script || drop_in {
        system.check("update-grub", &[], UPDATE_GRUB_TIMEOUT)?;
    }
    let conf = system.path(OVERLAYROOT_CONF);
    let current = fs::read_to_string(&conf).ok();
    if current.as_deref() != Some(overlayroot_conf().as_str()) {
        let state = managed.freeze.get_or_insert_with(FreezeBefore::default);
        if !state.overlayroot.existed && state.overlayroot.contents.is_none() {
            state.overlayroot = Before { existed: current.is_some(), contents: current };
        }
        write_if_changed(&conf, overlayroot_conf().as_bytes(), 0o644).map_err(|error| format!("{OVERLAYROOT_CONF}: {error}"))?;
    }
    Ok(())
}

/// No freeze: frozen, the file leaves the disk through overlayroot-chroot (the machine is frozen until it restarts);
/// unfrozen, the file and the GRUB entry go, with `update-grub`.
fn freeze_off(system: &System, managed: &mut Managed, frozen: bool) -> Result<(), String> {
    let earlier = managed.freeze.as_ref().and_then(|state| state.overlayroot.existed.then(|| state.overlayroot.contents.clone()).flatten());
    if frozen {
        if !freeze_configured(system, true) {
            return Ok(());
        }
        match &earlier {
            Some(contents) => {
                chroot_write(system, OVERLAYROOT_CONF, contents)?;
            }
            None => {
                // overlayroot-chroot may complain about /media/root-ro/proc on the way out: what counts is the file.
                let _ = system.run(OVERLAYROOT_CHROOT, &["rm", "-f", OVERLAYROOT_CONF], TOOL_TIMEOUT);
            }
        }
        if system.commands && freeze_configured(system, true) {
            return Err(format!("overlayroot-chroot could not take {OVERLAYROOT_CONF} off the disk"));
        }
        return Ok(());
    }
    let conf = system.path(OVERLAYROOT_CONF);
    if fs::read_to_string(&conf).is_ok_and(|text| text == overlayroot_conf()) {
        match &earlier {
            Some(contents) => write_if_changed(&conf, contents.as_bytes(), 0o644).map(|_| ()),
            None => remove_if_present(&conf).map(|_| ()),
        }
        .map_err(|error| format!("{OVERLAYROOT_CONF}: {error}"))?;
    }
    let script = remove_if_present(&system.path(GRUB_SCRIPT)).map_err(|error| format!("{GRUB_SCRIPT}: {error}"))?;
    let drop_in = remove_if_present(&system.path(GRUB_DROP_IN)).map_err(|error| format!("{GRUB_DROP_IN}: {error}"))?;
    if script || drop_in {
        system.check("update-grub", &[], UPDATE_GRUB_TIMEOUT)?;
    }
    managed.freeze = None;
    Ok(())
}

/// Writes `contents` to `absolute` on the disk of a frozen machine: `overlayroot-chroot tee <path>` with the text on
/// stdin. Whether it worked.
pub fn chroot_write(system: &System, absolute: &str, contents: &str) -> Result<(), String> {
    let output = system.run_input(OVERLAYROOT_CHROOT, &["tee", absolute], contents.as_bytes(), TOOL_TIMEOUT)?;
    let written = !system.commands || fs::read_to_string(system.path(&format!("{LOWER}{absolute}"))).is_ok_and(|text| text == contents);
    if written {
        Ok(())
    } else {
        Err(format!("overlayroot-chroot tee {absolute}: {}", output.message()))
    }
}

/// Masks the update timers for this boot (frozen): the masks live in /run and go at the next boot.
pub fn mask_update_timers(system: &System) -> Result<(), String> {
    let mut args = vec!["mask", "--runtime", "--now"];
    args.extend(UPDATE_TIMERS);
    system.check("systemctl", &args, TOOL_TIMEOUT).map(|_| ())
}

/// The maintenance window of `now`'s day, [start, end) in Unix time, when it is a maintenance day.
pub fn window(maintenance: &Maintenance, now: &LocalTime) -> Option<(i64, i64)> {
    if !maintenance.days.contains(&now.weekday()) {
        return None;
    }
    let start = now.at_minute(hhmm(&maintenance.time).ok()?);
    Some((start, start + i64::from(maintenance.max_minutes) * 60))
}

/// The next maintenance time after `now` (Unix time), within the coming week: for the RTC alarm.
pub fn next_maintenance(maintenance: &Maintenance, now_unix: i64) -> Option<i64> {
    let minute = hhmm(&maintenance.time).ok()?;
    (0..=7).find_map(|days| {
        let day = LocalTime::from_unix(now_unix + days * 86_400);
        let at = day.at_minute(minute);
        (maintenance.days.contains(&day.weekday()) && at > now_unix).then_some(at)
    })
}

/// What happened to today's window, in this boot.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct MaintenanceDay {
    pub date: String,
    /// The next try while someone uses the machine.
    pub next_try: Option<i64>,
    /// Given up for today.
    pub skipped: bool,
}

/// What the scheduler does about the maintenance window now.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Step {
    Nothing,
    /// Restart into the maintenance entry.
    Restart,
    /// Someone used the machine all through the window: skip the day.
    Skip,
}

/// The maintenance window's step at `now`. `done` is the Unix time of the last maintenance boot's start or of the last
/// restart into it (maintenance.json): a window already done or tried is not tried again; `someone` says whether a
/// user is at the screen.
pub fn step(maintenance: &Maintenance, now: &LocalTime, now_unix: i64, done: Option<i64>, someone: bool, day: &mut MaintenanceDay) -> Step {
    let Some((start, end)) = window(maintenance, now) else {
        return Step::Nothing;
    };
    if now_unix < start || now_unix >= end || done.is_some_and(|done| done >= start) {
        return Step::Nothing;
    }
    if day.date != now.date() {
        *day = MaintenanceDay { date: now.date(), next_try: None, skipped: false };
    }
    if day.skipped || day.next_try.is_some_and(|at| now_unix < at) {
        return Step::Nothing;
    }
    if !someone {
        return Step::Restart;
    }
    let next = day.next_try.unwrap_or(start).max(start) + RETRY_EVERY;
    let next = if next <= now_unix { now_unix + RETRY_EVERY } else { next };
    if next >= end {
        day.skipped = true;
        return Step::Skip;
    }
    day.next_try = Some(next);
    Step::Nothing
}

/// `maintenance.json` (PROTOCOL.md part 3): the last maintenance boot's start and end and its result; `tried`, the
/// last restart into it, keeps a frozen machine whose maintenance boot did not happen from restarting again and again
/// in the same window.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct MaintenanceRecord {
    #[serde(default)]
    pub last: Option<String>,
    #[serde(default)]
    pub finished: Option<String>,
    #[serde(default)]
    pub result: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tried: Option<String>,
}

impl MaintenanceRecord {
    pub fn load(path: &std::path::Path) -> MaintenanceRecord {
        crate::store::read_limited(path, 64 * 1024).ok().and_then(|data| serde_json::from_slice(&data).ok()).unwrap_or_default()
    }

    /// The Unix time of the last start, or of the last try when it is later: what `step` takes as done.
    pub fn done(&self) -> Option<i64> {
        let time = |value: &Option<String>| value.as_deref().and_then(crate::clock::parse_iso8601);
        match (time(&self.last), time(&self.tried)) {
            (Some(last), Some(tried)) => Some(last.max(tried)),
            (last, tried) => last.or(tried),
        }
    }

    pub fn text(&self) -> String {
        let mut text = serde_json::to_string(self).unwrap_or_default();
        text.push('\n');
        text
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::policy::Folders;

    #[test]
    fn frozen_from_the_mounts() {
        let frozen = "sysfs /sys sysfs rw 0 0\n/dev/vda3 /media/root-ro ext4 ro,relatime 0 0\n\
                      overlayroot / overlay rw,relatime,lowerdir=/media/root-ro,upperdir=/media/root-rw/overlay 0 0\n";
        assert!(frozen_in(frozen));
        assert!(!frozen_in("/dev/vda3 / ext4 rw,relatime 0 0\n"));
        assert!(!frozen_in("overlay / overlay rw 0 0\n"), "an overlay that is not overlayroot's (a container)");
    }

    #[test]
    fn refusals() {
        let shared = Shared { guest: true, freeze: true, maintenance: None, low_memory_ok: false };
        let none = Effective::default();
        assert_eq!(refusal(&shared, &none, 4096), None);
        assert!(refusal(&shared, &none, 1968).unwrap().contains("1968 MiB"));
        assert_eq!(refusal(&Shared { low_memory_ok: true, ..shared.clone() }, &none, 1968), None);
        let tidy = Effective { folders: Some(Folders { share: "smb://nas/x".into(), tidy: true }), ..Effective::default() };
        assert!(refusal(&shared, &tidy, 4096).unwrap().contains("folders.tidy"));
        assert_eq!(refusal(&Shared { freeze: false, ..shared }, &tidy, 1024), None, "no freeze asked");
    }

    #[test]
    fn freeze_on_and_off_in_a_test_root() {
        let root = crate::testutil::TempDir::new("shared");
        let system = System::test(root.path());
        fs::create_dir_all(root.path().join("usr/sbin")).unwrap();
        fs::write(root.path().join("usr/sbin/lightdm"), "").unwrap();
        let mut managed = Managed::default();
        let shared = Shared { guest: true, freeze: true, maintenance: None, low_memory_ok: true };
        // No guest-account script: the guest session is reported missing, the freeze is still set up.
        let error = apply(&system, Some(&shared), &Effective::default(), &mut managed, false).unwrap_err();
        assert!(error.contains("guest-account script missing"), "{error}");
        assert!(!system.path(GUEST_CONF).exists());
        fs::write(root.path().join("usr/sbin/guest-account"), "").unwrap();
        apply(&system, Some(&shared), &Effective::default(), &mut managed, false).unwrap();
        assert_eq!(fs::read_to_string(system.path(GUEST_CONF)).unwrap(), guest_conf());
        assert_eq!(fs::read_to_string(system.path(GRUB_SCRIPT)).unwrap(), grub_script());
        assert_eq!(fs::read_to_string(system.path(GRUB_DROP_IN)).unwrap(), grub_drop_in());
        assert!(freeze_configured(&system, false));
        use std::os::unix::fs::PermissionsExt;
        assert_eq!(fs::metadata(system.path(GRUB_SCRIPT)).unwrap().permissions().mode() & 0o777, 0o755);
        assert_eq!(managed.freeze, Some(FreezeBefore { overlayroot: Before { existed: false, contents: None }, installed_overlayroot: true }));
        assert!(managed.guest);
        // The section goes away in an unfrozen boot: everything goes.
        apply(&system, None, &Effective::default(), &mut managed, false).unwrap();
        for file in [GUEST_CONF, GRUB_SCRIPT, GRUB_DROP_IN, OVERLAYROOT_CONF] {
            assert!(!system.path(file).exists(), "{file}");
        }
        assert_eq!((managed.freeze.clone(), managed.guest), (None, false));
        // An earlier file of the machine's own comes back.
        fs::write(system.path(OVERLAYROOT_CONF), "overlayroot=\"\"\n").unwrap();
        apply(&system, Some(&shared), &Effective::default(), &mut managed, false).unwrap();
        apply(&system, Some(&Shared { freeze: false, ..shared.clone() }), &Effective::default(), &mut managed, false).unwrap();
        assert_eq!(fs::read_to_string(system.path(OVERLAYROOT_CONF)).unwrap(), "overlayroot=\"\"\n");
        assert!(system.path(GUEST_CONF).exists(), "guest stays on");
    }

    #[test]
    fn maintenance_window() {
        let maintenance = Maintenance { days: vec![7], time: "02:00".into(), max_minutes: 60 };
        // 2026-11-29 is a Sunday; 02:00 in Vietnam.
        let start = crate::clock::parse_iso8601("2026-11-29T02:00:00+07:00").unwrap();
        let at = |minutes: i64| (LocalTime::from_unix(start + minutes * 60), start + minutes * 60);
        let mut day = MaintenanceDay::default();
        let (now, unix) = at(-1);
        assert_eq!(step(&maintenance, &now, unix, None, false, &mut day), Step::Nothing, "before the window");
        let (now, unix) = at(0);
        assert_eq!(step(&maintenance, &now, unix, None, false, &mut day), Step::Restart);
        assert_eq!(step(&maintenance, &now, unix, Some(start + 30), false, &mut day), Step::Nothing, "done in this window");
        // Someone at the screen: tries at 02:15, 02:30, 02:45, then skips.
        let mut day = MaintenanceDay::default();
        let (now, unix) = at(0);
        assert_eq!(step(&maintenance, &now, unix, None, true, &mut day), Step::Nothing);
        assert_eq!(day.next_try, Some(start + 15 * 60));
        let (now, unix) = at(10);
        assert_eq!(step(&maintenance, &now, unix, None, false, &mut day), Step::Nothing, "waits for the next try");
        let (now, unix) = at(15);
        assert_eq!(step(&maintenance, &now, unix, None, true, &mut day), Step::Nothing);
        let (now, unix) = at(30);
        assert_eq!(step(&maintenance, &now, unix, None, true, &mut day), Step::Nothing);
        let (now, unix) = at(45);
        assert_eq!(step(&maintenance, &now, unix, None, true, &mut day), Step::Skip);
        let (now, unix) = at(50);
        assert_eq!(step(&maintenance, &now, unix, None, false, &mut day), Step::Nothing, "skipped for today");
        let (now, unix) = at(60);
        assert_eq!(step(&maintenance, &now, unix, None, false, &mut MaintenanceDay::default()), Step::Nothing, "after the window");
        // Monday is not a maintenance day; the next one is the Sunday after.
        let (monday, monday_unix) = at(24 * 60);
        assert_eq!(window(&maintenance, &monday), None);
        assert_eq!(next_maintenance(&maintenance, monday_unix), Some(start + 7 * 86_400));
        assert_eq!(next_maintenance(&maintenance, start - 60), Some(start));
        let record = MaintenanceRecord { last: Some("2026-11-29T02:03:00+07:00".into()), tried: Some("2026-11-29T02:01:00+07:00".into()), ..MaintenanceRecord::default() };
        assert_eq!(record.done(), Some(start + 180));
    }
}
