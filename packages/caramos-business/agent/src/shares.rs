//! `shares` (session part): the company's server folders in the file manager. Each gets a line `smb://… Name` in
//! `~/.config/gtk-3.0/bookmarks` (Nemo and Thunar read it) and is mounted at login with part 1's flow (`gio mount`,
//! `caramos-business --connect` when it needs a password). A share that cannot be reached is tried again every 5
//! minutes, and reported until it mounts. The lines the agent added are remembered in state.json, and only those are
//! removed.

use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::folders::{self, Mount, Share};
use crate::settings::ShareLink;
use crate::store;

/// The bookmark line of a share.
pub fn line(share: &ShareLink) -> String {
    format!("{} {}", share.url, share.name)
}

/// The bookmarks with the `wanted` lines present, and the agent's `previous` lines that are no longer wanted gone;
/// the user's own lines stay as they are, in their order.
pub fn bookmarks_text(current: &str, previous: &[String], wanted: &[String]) -> String {
    let mut lines: Vec<&str> = current.lines().filter(|line| !previous.iter().any(|ours| ours == line) || wanted.iter().any(|want| want == line)).collect();
    for want in wanted {
        if !lines.iter().any(|line| line == want) {
            lines.push(want);
        }
    }
    let mut text = lines.join("\n");
    if !text.is_empty() {
        text.push('\n');
    }
    text
}

/// A share that could not be mounted is tried again after this.
const RETRY: Duration = Duration::from_secs(5 * 60);
/// The first tries after a failure come sooner: just after login the network or GVfs may not be ready yet.
const FIRST_RETRY: Duration = Duration::from_secs(30);
const FIRST_RETRIES: u32 = 3;

/// When to try a share again after `failures` failed tries in a row.
pub fn retry_after(failures: u32) -> Duration {
    if failures <= FIRST_RETRIES { FIRST_RETRY } else { RETRY }
}

/// Whether a share that failed `failures` times in a row is reported: one failure may be the login's race.
pub fn reported(failures: u32) -> bool {
    failures >= 2
}

/// The shares' bookmarks and mounts in one login.
#[derive(Debug, Default)]
pub struct Shares {
    /// The shares tried this login: when to try again (None: mounted, or a password window was opened).
    tried: BTreeMap<String, Option<Instant>>,
    /// Failed tries in a row, by share.
    failures: BTreeMap<String, u32>,
    /// Why a share could not be mounted, until it can.
    failed: BTreeMap<String, String>,
}

impl Shares {
    /// One round. `ours` holds the lines the agent added (state.json). None when the section is not managed.
    pub fn round(&mut self, shares: Option<&[ShareLink]>, home: &Path, login: &str, gvfs: &Path, ours: &mut Vec<String>) -> Option<Result<(), String>> {
        let wanted: Vec<String> = shares.unwrap_or_default().iter().map(line).collect();
        if shares.is_none() && ours.is_empty() {
            return None;
        }
        let file = home.join(".config/gtk-3.0/bookmarks");
        let current = fs::read_to_string(&file).unwrap_or_default();
        let text = bookmarks_text(&current, ours, &wanted);
        let mut errors = Vec::new();
        if text != current {
            let written = file.parent().map_or(Ok(()), fs::create_dir_all).and_then(|()| store::write_atomic(&file, text.as_bytes(), 0o644));
            if let Err(error) = written {
                errors.push(format!("{}: {error}", file.display()));
            }
        }
        *ours = wanted;
        let shares = shares?;
        let now = Instant::now();
        self.failed.retain(|url, _| shares.iter().any(|share| share.url == *url));
        for share in shares {
            let due = match self.tried.get(&share.url) {
                None => true,
                Some(retry) => retry.is_some_and(|at| now >= at),
            };
            if !due {
                continue;
            }
            match mount(share, login, gvfs) {
                Ok(()) => {
                    self.tried.insert(share.url.clone(), None);
                    self.failures.remove(&share.url);
                    self.failed.remove(&share.url);
                }
                Err(error) => {
                    let failures = self.failures.get(&share.url).copied().unwrap_or(0) + 1;
                    self.failures.insert(share.url.clone(), failures);
                    self.tried.insert(share.url.clone(), Some(now + retry_after(failures)));
                    if reported(failures) {
                        self.failed.insert(share.url.clone(), format!("{}: {error}", share.name));
                    }
                }
            }
        }
        errors.extend(self.failed.values().cloned());
        Some(if errors.is_empty() { Ok(()) } else { Err(errors.join("; ")) })
    }
}

/// Mounts a share's root at login, asking for a password through the window when it needs one (without waiting).
fn mount(share: &ShareLink, login: &str, gvfs: &Path) -> Result<(), String> {
    let parsed = Share::parse(&share.url, login)?;
    if parsed.find_mount(gvfs).is_some() {
        return Ok(());
    }
    match folders::gio_mount(parsed.root_url()) {
        Mount::Done => Ok(()),
        Mount::NeedsPassword => Command::new(crate::prompt::PROGRAM)
            .arg("--connect")
            .arg(parsed.root_url())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map(|_| ())
            .map_err(|error| format!("{} --connect: {error}", crate::prompt::PROGRAM)),
        Mount::Failed(error) => Err(format!("cannot be reached: {error}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_failed_share_is_tried_again_soon_and_reported_from_the_second_failure() {
        assert_eq!((retry_after(1), retry_after(3), retry_after(4)), (FIRST_RETRY, FIRST_RETRY, RETRY));
        assert!(!reported(1));
        assert!(reported(2));
    }

    #[test]
    fn only_the_agents_lines_change() {
        let mine = "file:///home/lan/Music Nhạc\nsmb://nas/ketoan Kế toán\n";
        let wanted = vec!["smb://nas/ketoan Kế toán".to_string(), "smb://nas/chung Chung".to_string()];
        let text = bookmarks_text("file:///home/lan/Music Nhạc\n", &[], &wanted);
        assert_eq!(text, "file:///home/lan/Music Nhạc\nsmb://nas/ketoan Kế toán\nsmb://nas/chung Chung\n");
        assert_eq!(bookmarks_text(&text, &wanted, &wanted), text);
        assert_eq!(bookmarks_text(&text, &wanted, &wanted[..1]), mine);
        assert_eq!(bookmarks_text(mine, &wanted[..1], &[]), "file:///home/lan/Music Nhạc\n");
        assert_eq!(line(&ShareLink { name: "Kế toán".into(), url: "smb://nas/ketoan".into() }), "smb://nas/ketoan Kế toán");
    }
}
