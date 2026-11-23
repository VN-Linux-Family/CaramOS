//! caramos-business-agent: the employee machine's side of CaramOS Doanh nghiệp (see ../PROTOCOL.md: part 2 for 0.2,
//! part 3 for 0.3).
//!
//! One binary with two parts:
//! - `daemon` runs as root under systemd. It fetches the admin's signed policy, checks it against the admin key
//!   pinned at pairing, applies the system sections, runs the signed commands, and reports back (check-in, health,
//!   inventory, results, help requests), its requests authenticated with the machine's box key.
//! - `session` runs as the logged-in user, from /etc/xdg/autostart. It applies the user's sections (wallpaper,
//!   folders, shares, screen_lock), shows the messages, countdowns and remote help the daemon relays, and writes the
//!   user's status for the check-in.
//!
//! And `leave` (root), which the helper runs when the machine leaves the company: everything the agent changed goes
//! back (daemon.rs).

/// A log line on stderr: the journal for the service, ~/.xsession-errors for the session part.
macro_rules! log {
    ($($arg:tt)*) => {
        $crate::logging::line(format_args!($($arg)*))
    };
}

pub mod accounts;
pub mod clock;
pub mod commands;
pub mod crypto;
pub mod daemon;
pub mod discovery;
pub mod fetch;
pub mod folders;
pub mod health;
pub mod inbox;
pub mod inventory;
pub mod logging;
pub mod machine;
pub mod policy;
pub mod process;
pub mod prompt;
pub mod protocol;
pub mod relay;
pub mod remotehelp;
pub mod screenlock;
pub mod sections;
pub mod session;
pub mod settings;
pub mod shares;
pub mod status;
pub mod store;
pub mod tickets;
pub mod tidy;
pub mod userdirs;
pub mod wallpaper;

#[cfg(test)]
mod testutil;
