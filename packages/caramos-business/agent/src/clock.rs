//! Today's date and the time stamps of the status, in Vietnam's time.
//!
//! CaramOS Doanh nghiệp is for companies in Vietnam, which keeps UTC+7 all year (no daylight saving time). A fixed
//! offset gives the dates of the machine's clock without reading the time zone database.

use std::time::{SystemTime, UNIX_EPOCH};

use crate::policy::MonthDay;

/// Vietnam's offset from UTC, in seconds.
pub const OFFSET_SECONDS: i64 = 7 * 3600;

/// A moment in Vietnam's time.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct LocalTime {
    pub year: i64,
    pub month: u32,
    pub day: u32,
    pub hour: u32,
    pub minute: u32,
    pub second: u32,
}

impl LocalTime {
    pub fn now() -> LocalTime {
        let seconds = SystemTime::now().duration_since(UNIX_EPOCH).map(|elapsed| elapsed.as_secs()).unwrap_or(0);
        LocalTime::from_unix(i64::try_from(seconds).unwrap_or(0))
    }

    /// The local time of a Unix time stamp.
    pub fn from_unix(seconds: i64) -> LocalTime {
        let local = seconds + OFFSET_SECONDS;
        let (year, month, day) = civil_from_days(local.div_euclid(86_400));
        let rest = local.rem_euclid(86_400);
        LocalTime {
            year,
            month,
            day,
            hour: (rest / 3600) as u32,
            minute: (rest % 3600 / 60) as u32,
            second: (rest % 60) as u32,
        }
    }

    /// ISO 8601 with the offset, as the policy's `issued`: "2026-11-21T09:00:00+07:00".
    pub fn iso8601(&self) -> String {
        format!(
            "{}T{:02}:{:02}:{:02}+07:00",
            self.date(),
            self.hour,
            self.minute,
            self.second
        )
    }

    /// "2026-11-21": the folder of a tidy, `Chưa sắp xếp/YYYY-MM-DD`.
    pub fn date(&self) -> String {
        format!("{:04}-{:02}-{:02}", self.year, self.month, self.day)
    }

    /// The day of the year that the wallpaper periods are written in.
    pub fn month_day(&self) -> MonthDay {
        MonthDay { month: self.month as u8, day: self.day as u8 }
    }

    /// The ISO weekday, 1 = Monday to 7 = Sunday.
    pub fn weekday(&self) -> u8 {
        // 1970-01-01 was a Thursday (4).
        let days = days_from_civil(self.year, self.month, self.day);
        (days + 3).rem_euclid(7) as u8 + 1
    }

    /// Minutes since local midnight.
    pub fn minute_of_day(&self) -> u32 {
        self.hour * 60 + self.minute
    }

    /// The Unix time of `minute` (of the day) on this local date.
    pub fn at_minute(&self, minute: u32) -> i64 {
        days_from_civil(self.year, self.month, self.day) * 86_400 + i64::from(minute) * 60 - OFFSET_SECONDS
    }
}

/// When this boot started, as Unix seconds: `btime` in /proc/stat.
pub fn boot_time() -> Option<i64> {
    parse_btime(&std::fs::read_to_string("/proc/stat").ok()?)
}

/// The `btime` line of /proc/stat's text.
pub fn parse_btime(stat: &str) -> Option<i64> {
    stat.lines().find_map(|line| line.strip_prefix("btime ")).and_then(|value| value.trim().parse().ok())
}

/// The Unix time now.
pub fn unix_now() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|elapsed| elapsed.as_secs() as i64).unwrap_or(0)
}

/// The Unix time of an ISO 8601 date and time with an offset or Z, as the commands' `issued` and `expires`:
/// `2026-11-21T14:10:00+07:00`, `2026-11-21T07:10:00Z`, fractions of a second allowed.
pub fn parse_iso8601(text: &str) -> Option<i64> {
    let bytes = text.as_bytes();
    let number = |range: std::ops::Range<usize>| -> Option<i64> {
        let part = text.get(range)?;
        part.bytes().all(|byte| byte.is_ascii_digit()).then(|| part.parse().ok())?
    };
    if bytes.len() < 20 || bytes[4] != b'-' || bytes[7] != b'-' || !matches!(bytes[10], b'T' | b't' | b' ') || bytes[13] != b':' || bytes[16] != b':' {
        return None;
    }
    let (year, month, day) = (number(0..4)?, number(5..7)?, number(8..10)?);
    let (hour, minute, second) = (number(11..13)?, number(14..16)?, number(17..19)?);
    let mut rest = &text[19..];
    if let Some(fraction) = rest.strip_prefix('.') {
        let digits = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if digits == 0 {
            return None;
        }
        rest = &fraction[digits..];
    }
    let offset = match rest {
        "Z" | "z" => 0,
        _ => {
            let sign = match rest.as_bytes().first()? {
                b'+' => 1,
                b'-' => -1,
                _ => return None,
            };
            let digits = rest.get(1..)?;
            if digits.len() != 5 || digits.as_bytes()[2] != b':' {
                return None;
            }
            let hours: i64 = digits[..2].parse().ok()?;
            let minutes: i64 = digits[3..].parse().ok()?;
            sign * (hours * 3600 + minutes * 60)
        }
    };
    let valid = (1..=12).contains(&month) && (1..=31).contains(&day) && hour < 24 && minute < 60 && second < 61;
    if !valid {
        return None;
    }
    Some(days_from_civil(year, month as u32, day as u32) * 86_400 + hour * 3600 + minute * 60 + second - offset)
}

/// Days since 1970-01-01 of a Gregorian date (Howard Hinnant's `days_from_civil`).
fn days_from_civil(year: i64, month: u32, day: u32) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let year_of_era = year.rem_euclid(400);
    let month = i64::from(month);
    let day_of_year = (153 * (if month > 2 { month - 3 } else { month + 9 }) + 2) / 5 + i64::from(day) - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

/// The Gregorian (year, month, day) of a count of days since 1970-01-01 (Howard Hinnant's `civil_from_days`).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let day_of_era = z.rem_euclid(146_097);
    let year_of_era = (day_of_era - day_of_era / 1460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let shifted_month = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * shifted_month + 2) / 5 + 1) as u32;
    let month = if shifted_month < 10 { shifted_month + 3 } else { shifted_month - 9 } as u32;
    let year = year_of_era + era * 400 + i64::from(month <= 2);
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unix_epoch_is_seven_in_the_morning() {
        let time = LocalTime::from_unix(0);
        assert_eq!(time.iso8601(), "1970-01-01T07:00:00+07:00");
    }

    #[test]
    fn new_year_comes_seven_hours_before_utc() {
        // 2024-12-31T17:00:00Z
        let time = LocalTime::from_unix(1_735_664_400);
        assert_eq!(time.iso8601(), "2025-01-01T00:00:00+07:00");
        assert_eq!(LocalTime::from_unix(1_735_664_399).date(), "2024-12-31");
    }

    #[test]
    fn leap_day() {
        // 2024-02-29T00:00:00Z
        let time = LocalTime::from_unix(1_709_164_800);
        assert_eq!(time.date(), "2024-02-29");
        assert_eq!(time.month_day(), MonthDay { month: 2, day: 29 });
        // 2100 is not a leap year: 2100-02-28T17:00:00Z is March 1st in Vietnam.
        assert_eq!(LocalTime::from_unix(4_107_517_200).date(), "2100-03-01");
    }

    #[test]
    fn iso8601_times() {
        assert_eq!(parse_iso8601("2026-11-21T14:10:00+07:00"), Some(1_795_245_000));
        assert_eq!(parse_iso8601("2026-11-21T07:10:00Z"), Some(1_795_245_000));
        assert_eq!(parse_iso8601("2026-11-21T07:10:00.250Z"), Some(1_795_245_000));
        assert_eq!(parse_iso8601("1970-01-01T00:00:00Z"), Some(0));
        for bad in ["2026-11-21", "2026-11-21T14:10:00", "2026-13-01T00:00:00Z", "2026-11-21T14:10:00+7", "x"] {
            assert_eq!(parse_iso8601(bad), None, "{bad}");
        }
        let time = LocalTime::from_unix(1_795_245_000);
        assert_eq!(time.iso8601(), "2026-11-21T14:10:00+07:00");
        assert_eq!(parse_iso8601(&time.iso8601()), Some(1_795_245_000));
    }

    #[test]
    fn weekdays_and_minutes() {
        // 2026-11-21 is a Saturday, 2026-11-23 a Monday.
        assert_eq!(LocalTime::from_unix(1_795_245_000).weekday(), 6);
        assert_eq!(LocalTime::from_unix(1_795_245_000 + 2 * 86_400).weekday(), 1);
        assert_eq!(LocalTime::from_unix(1_795_245_000 + 86_400).weekday(), 7);
        let time = LocalTime::from_unix(1_795_245_000);
        assert_eq!(time.minute_of_day(), 14 * 60 + 10);
        assert_eq!(time.at_minute(14 * 60 + 10), 1_795_245_000);
        assert_eq!(time.at_minute(18 * 60 + 30), 1_795_245_000 + 260 * 60);
    }
}
