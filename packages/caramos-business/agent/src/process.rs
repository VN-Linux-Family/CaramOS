//! Running the desktop's own tools (gsettings, xfconf-query, gio, notify-send, ip, ...): never through a shell, always
//! with a time limit, and starting the programs that outlive the round that started them.

use std::fs;
use std::io::{self, Read};
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// At most this much of a tool's output is kept.
const MAX_OUTPUT: u64 = 1024 * 1024;

/// What a tool printed, and how it ended.
#[derive(Debug)]
pub struct Output {
    /// None when it was killed at the time limit.
    pub status: Option<ExitStatus>,
    pub stdout: String,
    pub stderr: String,
}

impl Output {
    pub fn success(&self) -> bool {
        self.status.is_some_and(|status| status.success())
    }

    /// The first line of what it said on stderr (else stdout), for logs and the status detail.
    pub fn message(&self) -> String {
        if self.status.is_none() {
            return "it did not answer in time".to_string();
        }
        let text = if self.stderr.trim().is_empty() { &self.stdout } else { &self.stderr };
        text.lines().map(str::trim).find(|line| !line.is_empty()).unwrap_or("it failed").to_string()
    }
}

/// Runs `program` with `args`, stdin from /dev/null, and kills it after `timeout`.
pub fn run(program: &str, args: &[&str], timeout: Duration) -> io::Result<Output> {
    let mut command = Command::new(program);
    command.args(args);
    run_command(command, timeout)
}

/// Runs a prepared command the same way, for one that needs its own environment.
pub fn run_command(mut command: Command, timeout: Duration) -> io::Result<Output> {
    command.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = collect(child.stdout.take());
    let stderr = collect(child.stderr.take());
    let status = wait_until(&mut child, Instant::now() + timeout)?;
    if status.is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(Output {
        status,
        stdout: stdout.join().unwrap_or_default(),
        stderr: stderr.join().unwrap_or_default(),
    })
}

/// The same with `input` written to the command's stdin, which is then closed.
pub fn run_command_with_input(mut command: Command, input: &[u8], timeout: Duration) -> io::Result<Output> {
    command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    let mut child = command.spawn()?;
    let stdout = collect(child.stdout.take());
    let stderr = collect(child.stderr.take());
    if let Some(mut stdin) = child.stdin.take() {
        let data = input.to_vec();
        // In a thread: a command that does not read its input must not block this one.
        thread::spawn(move || {
            use std::io::Write;
            let _ = stdin.write_all(&data);
        });
    }
    let status = wait_until(&mut child, Instant::now() + timeout)?;
    if status.is_none() {
        let _ = child.kill();
        let _ = child.wait();
    }
    Ok(Output {
        status,
        stdout: stdout.join().unwrap_or_default(),
        stderr: stderr.join().unwrap_or_default(),
    })
}

/// Reads a pipe to its end in a thread, so that a chatty tool never blocks on a full pipe.
fn collect<R: Read + Send + 'static>(pipe: Option<R>) -> thread::JoinHandle<String> {
    thread::spawn(move || {
        let mut bytes = Vec::new();
        if let Some(pipe) = pipe {
            let _ = pipe.take(MAX_OUTPUT).read_to_end(&mut bytes);
        }
        String::from_utf8_lossy(&bytes).into_owned()
    })
}

/// Waits for `child` until `deadline`: Some(status) when it ended, None when it still runs.
pub fn wait_until(child: &mut Child, deadline: Instant) -> io::Result<Option<ExitStatus>> {
    loop {
        if let Some(status) = child.try_wait()? {
            return Ok(Some(status));
        }
        if Instant::now() >= deadline {
            return Ok(None);
        }
        thread::sleep(Duration::from_millis(25));
    }
}

/// Starts `program` in its own process group, with no terminal I/O, for programs that keep running after this round
/// (nemo-desktop, xfdesktop). A thread waits for it, so that it never lingers as a zombie.
pub fn spawn_detached(program: &str, args: &[&str]) -> io::Result<()> {
    let mut child = Command::new(program)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()?;
    thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

/// This process's real user id, from /proc/self/status (std has no getuid).
/// Whether the running program was replaced on disk since it started (a package upgrade): Linux shows the link of
/// `/proc/self/exe` with " (deleted)" then.
pub fn program_replaced() -> bool {
    fs::read_link("/proc/self/exe").is_ok_and(|path| replaced_link(&path.to_string_lossy()))
}

pub fn replaced_link(link: &str) -> bool {
    link.ends_with(" (deleted)")
}

pub fn uid() -> Option<u32> {
    let status = fs::read_to_string("/proc/self/status").ok()?;
    let line = status.lines().find(|line| line.starts_with("Uid:"))?;
    line.split_whitespace().nth(1)?.parse().ok()
}

#[cfg(test)]
mod tests {
    #[test]
    fn a_replaced_program() {
        assert!(super::replaced_link("/usr/lib/caramos-business/caramos-business-agent (deleted)"));
        assert!(!super::replaced_link("/usr/lib/caramos-business/caramos-business-agent"));
        assert!(!super::program_replaced(), "the test program is still on disk");
    }

    use super::*;

    #[test]
    fn output_and_time_limit() {
        let output = run("sh", &["-c", "echo out; echo err >&2"], Duration::from_secs(10)).unwrap();
        assert!(output.success());
        assert_eq!(output.stdout, "out\n");
        assert_eq!(output.message(), "err");

        let started = Instant::now();
        let output = run("sleep", &["30"], Duration::from_millis(200)).unwrap();
        assert!(output.status.is_none());
        assert!(started.elapsed() < Duration::from_secs(10));
    }

    #[test]
    fn input_on_stdin() {
        let mut command = Command::new("cat");
        command.arg("-");
        let output = run_command_with_input(command, b"overlayroot=\"\"\n", Duration::from_secs(10)).unwrap();
        assert!(output.success());
        assert_eq!(output.stdout, "overlayroot=\"\"\n");
    }

    #[test]
    fn own_uid() {
        assert!(uid().is_some());
    }
}
