//! Log lines on stderr, and a guard against writing the same failure every minute for hours.

use std::sync::OnceLock;

static PREFIX: OnceLock<&'static str> = OnceLock::new();

/// Sets the prefix of every line, once at start: "" for the service, whose lines the journal names already.
pub fn set_prefix(prefix: &'static str) {
    let _ = PREFIX.set(prefix);
}

/// Writes one line; use the `log!` macro.
pub fn line(message: std::fmt::Arguments) {
    eprintln!("{}{}", PREFIX.get().copied().unwrap_or(""), message);
}

/// Remembers the last message of a repeating check, so that a failure that lasts is logged once, and its end too.
#[derive(Debug, Default)]
pub struct Once {
    last: Option<String>,
}

impl Once {
    /// Logs `message` unless it is the one logged last time.
    pub fn log(&mut self, message: &str) {
        if self.last.as_deref() != Some(message) {
            log!("{message}");
            self.last = Some(message.to_string());
        }
    }

    /// Forgets the last message, logging `message` if there was one: "it works again".
    pub fn clear(&mut self, message: &str) {
        if self.last.take().is_some() && !message.is_empty() {
            log!("{message}");
        }
    }
}
