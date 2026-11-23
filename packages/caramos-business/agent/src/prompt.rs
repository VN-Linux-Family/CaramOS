//! The employee UI (PROTOCOL.md part 2 "Employee UI contract"): the session part runs `caramos-business --prompt KIND
//! [options]` as the user; the program prints one JSON line `{"answer": "..."}` and exits 0.
//!
//! | KIND | answers |
//! |---|---|
//! | message | read, closed |
//! | countdown | now, postpone, timeout |
//! | consent | view, control, refuse (after 60 s: refuse) |
//! | banner | stop |
//! | notice | ok |
//! | frozen | ok (part 3: at each login on a frozen machine) |

use std::io::{BufRead, BufReader, Read};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

/// The window's program.
pub const PROGRAM: &str = "caramos-business";

/// The answers each kind may give.
pub fn answers(kind: &str) -> &'static [&'static str] {
    match kind {
        "message" => &["read", "closed"],
        "countdown" => &["now", "postpone", "timeout"],
        "consent" => &["view", "control", "refuse"],
        "banner" => &["stop"],
        "notice" | "frozen" => &["ok"],
        _ => &[],
    }
}

/// The answer in the program's line `{"answer": "..."}`, when it is one the kind may give.
pub fn parse_answer(kind: &str, line: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(line.trim()).ok()?;
    let answer = value["answer"].as_str()?;
    answers(kind).contains(&answer).then(|| answer.to_string())
}

/// A prompt on the user's screen.
pub struct Prompt {
    kind: String,
    child: Child,
    line: Receiver<String>,
}

/// Why a prompt gave no answer.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum NoAnswer {
    /// It ran out of time.
    Timeout,
    /// The agent stopped it (a cancel, the end of the session).
    Cancelled,
    /// It could not run, or ended without a valid answer.
    Failed(String),
}

impl Prompt {
    /// Starts `caramos-business --prompt <kind> <options>` (never through a shell).
    pub fn start(kind: &str, options: &[String]) -> Result<Prompt, NoAnswer> {
        let mut child = Command::new(PROGRAM)
            .arg("--prompt")
            .arg(kind)
            .args(options)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| NoAnswer::Failed(format!("{PROGRAM} --prompt {kind}: {error}")))?;
        let stdout = child.stdout.take().expect("stdout is piped");
        let (sender, line) = mpsc::channel();
        thread::spawn(move || {
            let mut first = String::new();
            if BufReader::new(stdout).take(4096).read_line(&mut first).is_ok() {
                let _ = sender.send(first);
            }
        });
        Ok(Prompt { kind: kind.to_string(), child, line })
    }

    /// Waits for the answer until `limit` passes or `cancel` is set; then the prompt is closed.
    pub fn wait(mut self, limit: Option<Duration>, cancel: &AtomicBool) -> Result<String, NoAnswer> {
        let deadline = limit.map(|limit| Instant::now() + limit);
        loop {
            if cancel.load(Ordering::SeqCst) {
                self.close();
                return Err(NoAnswer::Cancelled);
            }
            if deadline.is_some_and(|deadline| Instant::now() >= deadline) {
                self.close();
                return Err(NoAnswer::Timeout);
            }
            match self.line.recv_timeout(Duration::from_millis(250)) {
                Ok(line) => {
                    let _ = self.child.wait();
                    return parse_answer(&self.kind, &line)
                        .ok_or_else(|| NoAnswer::Failed(format!("{PROGRAM} --prompt {} gave no valid answer", self.kind)));
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => {
                    let _ = self.child.wait();
                    return Err(NoAnswer::Failed(format!("{PROGRAM} --prompt {} ended without an answer", self.kind)));
                }
                Err(mpsc::RecvTimeoutError::Timeout) => {}
            }
        }
    }

    /// Whether it ended already.
    pub fn finished(&mut self) -> bool {
        !matches!(self.child.try_wait(), Ok(None))
    }

    /// The answer if it came, without waiting.
    pub fn try_answer(&mut self) -> Option<String> {
        self.line.try_recv().ok().and_then(|line| parse_answer(&self.kind, &line))
    }

    /// Closes the prompt.
    pub fn close(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

/// Runs a prompt to its answer.
pub fn ask(kind: &str, options: &[String], limit: Option<Duration>, cancel: &AtomicBool) -> Result<String, NoAnswer> {
    Prompt::start(kind, options)?.wait(limit, cancel)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn answers_are_checked() {
        assert_eq!(parse_answer("message", r#"{"answer":"read"}"#), Some("read".into()));
        assert_eq!(parse_answer("countdown", "{\"answer\": \"postpone\"}\n"), Some("postpone".into()));
        assert_eq!(parse_answer("consent", r#"{"answer":"read"}"#), None);
        assert_eq!(parse_answer("notice", "ok"), None);
        assert_eq!(parse_answer("banner", r#"{"answer":"stop","extra":1}"#), Some("stop".into()));
    }
}
