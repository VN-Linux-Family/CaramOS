//! `power`: the scheduled shutdown and the wake-up.
//!
//! - The daemon checks the schedule every 30 s. At `time - warn_minutes` every session part shows a countdown with
//!   the postpones left; a postpone moves the shutdown for this machine and this day only.
//! - At the time: `systemctl poweroff`, or `systemctl suspend` for a laptop with `laptops: "suspend"`; `skip` leaves
//!   laptops on. A machine with no session shuts down without asking. A time that passed while the machine was off
//!   is not acted on later.
//! - With `wake`: before a scheduled shutdown the RTC alarm is set (`rtcwake -m no -t <epoch>`), and the wired
//!   NetworkManager connections get `802-3-ethernet.wake-on-lan magic` (their earlier value comes back when `wake`
//!   goes away).

use std::path::Path;
use std::time::Duration;

use super::{Managed, PowerDay, System};
use crate::clock::LocalTime;
use crate::settings::{hhmm, Laptops, Power, Shutdown, Wake};

const TOOL_TIMEOUT: Duration = Duration::from_secs(60);
/// A shutdown time this late is no longer acted on (the daemon was busy, or the machine was asleep).
const LATE: i64 = 10 * 60;

/// What the scheduler does now.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Step {
    Nothing,
    /// Ask the sessions for a countdown to the shutdown at `minute` (of today).
    Warn { minute: u32, seconds: u32, postpones_left: u32, postpone_minutes: u32 },
    /// Shut down (or suspend) now.
    Halt(Halt),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Halt {
    Poweroff,
    Suspend,
}

/// Today's state for `shutdown`, starting a new day when the date changed.
pub fn day_state<'a>(shutdown: &Shutdown, now: &LocalTime, day: &'a mut Option<PowerDay>) -> &'a mut PowerDay {
    let today = now.date();
    if day.as_ref().is_none_or(|day| day.date != today) {
        *day = Some(PowerDay { date: today, postpones: 0, minute: hhmm(&shutdown.time).unwrap_or(0), warned_for: None });
    }
    day.as_mut().expect("set above")
}

/// What to do at `now`, the scheduler having last looked at `last_check` (Unix time). `laptop` says whether this
/// machine is one.
pub fn step(shutdown: &Shutdown, now: &LocalTime, now_unix: i64, last_check: i64, day: &mut Option<PowerDay>, laptop: bool) -> Step {
    if !shutdown.days.contains(&now.weekday()) || (laptop && shutdown.laptops == Laptops::Skip) {
        return Step::Nothing;
    }
    let state = day_state(shutdown, now, day);
    let at = now.at_minute(state.minute);
    let warn_from = at - i64::from(shutdown.warn_minutes) * 60;
    if last_check < at && at <= now_unix && now_unix - at < LATE {
        return Step::Halt(if laptop && shutdown.laptops == Laptops::Suspend { Halt::Suspend } else { Halt::Poweroff });
    }
    if warn_from <= now_unix && now_unix < at && state.warned_for != Some(state.minute) {
        state.warned_for = Some(state.minute);
        return Step::Warn {
            minute: state.minute,
            seconds: (at - now_unix) as u32,
            postpones_left: shutdown.max_postpones.saturating_sub(state.postpones),
            postpone_minutes: shutdown.postpone_minutes,
        };
    }
    Step::Nothing
}

/// A user's postpone: the shutdown moves by `postpone_minutes`, for today only, while postpones are left.
pub fn postpone(shutdown: &Shutdown, now: &LocalTime, day: &mut Option<PowerDay>) -> bool {
    let state = day_state(shutdown, now, day);
    if state.postpones >= shutdown.max_postpones {
        return false;
    }
    state.postpones += 1;
    state.minute = (state.minute + shutdown.postpone_minutes).min(23 * 60 + 59);
    true
}

/// The next wake-up after `now` (Unix time), within the coming week.
pub fn next_wake(wake: &Wake, now_unix: i64) -> Option<i64> {
    let minute = hhmm(&wake.time).ok()?;
    (0..=7).find_map(|days| {
        let day = LocalTime::from_unix(now_unix + days * 86_400);
        let at = day.at_minute(minute);
        (wake.days.contains(&day.weekday()) && at > now_unix).then_some(at)
    })
}

/// Whether this machine is a laptop: a portable chassis type, or a battery.
pub fn is_laptop(root: &Path) -> bool {
    let chassis = std::fs::read_to_string(root.join("sys/class/dmi/id/chassis_type")).unwrap_or_default();
    let portable = matches!(chassis.trim().parse::<u32>(), Ok(8 | 9 | 10 | 11 | 12 | 14 | 18 | 21 | 30 | 31 | 32));
    let battery = std::fs::read_dir(root.join("sys/class/power_supply"))
        .map(|entries| entries.flatten().any(|entry| entry.file_name().to_string_lossy().starts_with("BAT")))
        .unwrap_or(false);
    portable || battery
}

/// Wired connections' wake-on-lan for `wake` (on), or back to their earlier values (off). The RTC alarm set before
/// a shutdown is cleared when the wake-ups go away (unless `maintenance_alarm`: a frozen machine's maintenance window
/// wants it too), and forgotten once its time has passed.
pub fn apply(system: &System, power: Option<&Power>, managed: &mut Managed, now_unix: i64, maintenance_alarm: bool) -> Result<(), String> {
    let wanted = power.and_then(|power| power.wake.as_ref()).is_some();
    if wanted {
        let listing = system.check("nmcli", &["-t", "-f", "UUID,TYPE", "connection", "show"], TOOL_TIMEOUT)?;
        for uuid in listing.lines().filter_map(|line| line.strip_suffix(":802-3-ethernet")) {
            let current = system.check("nmcli", &["-g", "802-3-ethernet.wake-on-lan", "connection", "show", uuid], TOOL_TIMEOUT)?;
            let current = current.trim().to_string();
            if current.split(',').any(|flag| flag.trim() == "magic") {
                continue;
            }
            system.check("nmcli", &["connection", "modify", uuid, "802-3-ethernet.wake-on-lan", "magic"], TOOL_TIMEOUT)?;
            managed.wake_on_lan.entry(uuid.to_string()).or_insert(current);
        }
    } else {
        for (uuid, before) in std::mem::take(&mut managed.wake_on_lan) {
            let value = if before.is_empty() { "default" } else { before.as_str() };
            // A connection removed meanwhile cannot be put back; that is fine.
            let _ = system.check("nmcli", &["connection", "modify", &uuid, "802-3-ethernet.wake-on-lan", value], TOOL_TIMEOUT);
        }
    }
    if power.is_none() {
        managed.power_day = None;
    }
    if let Some(at) = managed.rtc_wake {
        if at <= now_unix {
            managed.rtc_wake = None;
        } else if !wanted && !maintenance_alarm {
            system.check("rtcwake", &["-m", "disable"], TOOL_TIMEOUT)?;
            managed.rtc_wake = None;
        }
    }
    Ok(())
}

/// Before a shutdown: the RTC alarm for the earliest of the next wake-up and `maintenance`, the next maintenance time
/// of a frozen machine (PROTOCOL.md part 3 "Maintenance window").
pub fn set_wake_alarm(system: &System, wake: Option<&Wake>, maintenance: Option<i64>, now_unix: i64, managed: &mut Managed) -> Result<(), String> {
    let next = wake.and_then(|wake| next_wake(wake, now_unix));
    let Some(at) = [next, maintenance].into_iter().flatten().filter(|at| *at > now_unix).min() else {
        return Ok(());
    };
    system.check("rtcwake", &["-m", "no", "-t", &at.to_string()], TOOL_TIMEOUT)?;
    managed.rtc_wake = Some(at);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn shutdown(laptops: Laptops) -> Shutdown {
        Shutdown { days: vec![1, 2, 3, 4, 5, 6], time: "18:30".into(), warn_minutes: 10, postpone_minutes: 30, max_postpones: 2, laptops }
    }

    /// 2026-11-23 (a Monday) at HH:MM in Vietnam.
    fn monday(hour: i64, minute: i64) -> (LocalTime, i64) {
        let unix = 1_795_410_000 - 12 * 3600 + hour * 3600 + minute * 60;
        (LocalTime::from_unix(unix), unix)
    }

    #[test]
    fn warning_then_halt() {
        let plan = shutdown(Laptops::Skip);
        let mut day = None;
        let (now, unix) = monday(18, 19);
        assert_eq!(step(&plan, &now, unix, unix - 30, &mut day, false), Step::Nothing);
        let (now, unix) = monday(18, 20);
        assert_eq!(
            step(&plan, &now, unix, unix - 30, &mut day, false),
            Step::Warn { minute: 18 * 60 + 30, seconds: 600, postpones_left: 2, postpone_minutes: 30 }
        );
        let (now, unix) = monday(18, 21);
        assert_eq!(step(&plan, &now, unix, unix - 30, &mut day, false), Step::Nothing, "warned once");
        let (now, unix) = monday(18, 30);
        assert_eq!(step(&plan, &now, unix, unix - 30, &mut day, false), Step::Halt(Halt::Poweroff));
        // A laptop with "skip" stays on; with "suspend" it sleeps.
        let mut day = None;
        assert_eq!(step(&plan, &now, unix, unix - 30, &mut day, true), Step::Nothing);
        assert_eq!(step(&shutdown(Laptops::Suspend), &now, unix, unix - 30, &mut None, true), Step::Halt(Halt::Suspend));
    }

    #[test]
    fn postpones_and_missed_times() {
        let plan = shutdown(Laptops::Same);
        let mut day = None;
        let (now, unix) = monday(18, 25);
        assert!(postpone(&plan, &now, &mut day));
        assert!(postpone(&plan, &now, &mut day));
        assert!(!postpone(&plan, &now, &mut day), "only two postpones");
        assert_eq!(day.as_ref().unwrap().minute, 19 * 60 + 30);
        let (now, unix2) = monday(18, 30);
        assert_eq!(step(&plan, &now, unix2, unix, &mut day, false), Step::Nothing, "moved to 19:30");
        let (now, unix3) = monday(19, 30);
        assert_eq!(step(&plan, &now, unix3, unix3 - 30, &mut day, false), Step::Halt(Halt::Poweroff));
        // Started at 20:00, after the time: nothing.
        let (now, unix4) = monday(20, 0);
        assert_eq!(step(&shutdown(Laptops::Same), &now, unix4, unix4, &mut None, false), Step::Nothing);
        // Sunday is not a shutdown day.
        let sunday = LocalTime::from_unix(unix4 - 86_400);
        assert_eq!(step(&plan, &sunday, unix4 - 86_400, unix4 - 86_430, &mut None, false), Step::Nothing);
    }

    #[test]
    fn next_wake_up() {
        let wake = Wake { days: vec![1, 2, 3, 4, 5, 6], time: "07:45".into() };
        let (_, unix) = monday(18, 30);
        let tuesday = next_wake(&wake, unix).unwrap();
        assert_eq!(LocalTime::from_unix(tuesday).iso8601(), "2026-11-24T07:45:00+07:00");
        // Saturday evening: the next one is Monday.
        let saturday = unix - 2 * 86_400;
        let next = next_wake(&wake, saturday).unwrap();
        assert_eq!(LocalTime::from_unix(next).iso8601(), "2026-11-23T07:45:00+07:00");
    }

    #[test]
    fn the_wake_alarm_goes_with_the_wake_ups() {
        let root = crate::testutil::TempDir::new("power");
        let system = System::test(root.path());
        let (_, unix) = monday(18, 30);
        let wake = Power { shutdown: None, wake: Some(Wake { days: vec![1, 2, 3, 4, 5, 6], time: "07:45".into() }) };
        let mut managed = Managed { rtc_wake: Some(unix + 3_600), ..Managed::default() };
        apply(&system, Some(&wake), &mut managed, unix, false).unwrap();
        assert_eq!(managed.rtc_wake, Some(unix + 3_600), "still wanted");
        apply(&system, Some(&wake), &mut managed, unix + 7_200, false).unwrap();
        assert_eq!(managed.rtc_wake, None, "passed");
        managed.rtc_wake = Some(unix + 3_600);
        apply(&system, Some(&Power { shutdown: None, wake: None }), &mut managed, unix, false).unwrap();
        assert_eq!(managed.rtc_wake, None, "the wake-ups went away");
        managed.rtc_wake = Some(unix + 3_600);
        apply(&system, None, &mut managed, unix, true).unwrap();
        assert_eq!(managed.rtc_wake, Some(unix + 3_600), "a frozen machine's maintenance window keeps it");
        apply(&system, None, &mut managed, unix, false).unwrap();
        assert_eq!(managed.rtc_wake, None, "the section went away");
        // The earliest of the wake-up and the maintenance time.
        let Some(Wake { .. }) = wake.wake.as_ref() else { unreachable!() };
        set_wake_alarm(&system, wake.wake.as_ref(), Some(unix + 600), unix, &mut managed).unwrap();
        assert_eq!(managed.rtc_wake, Some(unix + 600));
        set_wake_alarm(&system, wake.wake.as_ref(), None, unix, &mut managed).unwrap();
        assert_eq!(managed.rtc_wake, next_wake(wake.wake.as_ref().unwrap(), unix));
    }
}
