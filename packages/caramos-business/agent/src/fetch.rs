//! HTTP to the admin, TCP 47022: the paired machine's authenticated requests: the signed policy and its files, the
//! long-poll `/wait`, the tickets, check-in, inventory, command results and help requests.
//!
//! Plain HTTP on the company LAN: the signature over the policy, not TLS, makes it trustworthy, and each file is
//! checked against the size and sha256 that the signed policy lists. Every request of the paired machine carries
//! `X-Caramos-Machine`, `X-Caramos-Time` and `X-Caramos-Mac` (PROTOCOL.md part 2); from 0.3 `GET /policy` and
//! `GET /files` do too, so that only paired, approved machines read the company's settings. A machine waiting for
//! approval gets 403 `{"error": "pending"}`, a removed one 410 (PROTOCOL.md part 3). Answers are read with limits, so
//! that a confused or hostile server can fill neither the memory nor the disk.

use std::fmt;
use std::fs::{self, OpenOptions, Permissions};
use std::io::{self, Read, Write};
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::Path;
use std::time::{Duration, Instant};

use sha2::{Digest, Sha256};

use crate::crypto::{self, SharedKeys};
use crate::policy;
use crate::protocol::{PolicyAnswer, SignedTickets, WaitAnswer, API, MAX_REQUEST_BODY};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(5);
/// For each read and write: a stalled admin fails in this time, a slow but moving download goes on.
const IO_TIMEOUT: Duration = Duration::from_secs(30);
/// One file may take this long in all (20 MiB at 35 KiB/s).
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(10 * 60);
/// The JSON of a signed policy: the policy's text (at most policy::MAX_TEXT), escaped, and the signature.
const MAX_POLICY_ANSWER: u64 = 2 * policy::MAX_TEXT as u64 + 4096;
/// The check-in's answer, `{"ok": true}`.
const MAX_SMALL_ANSWER: u64 = 64 * 1024;
/// `/wait`'s answer: at most 50 commands, each far below 64 KiB.
const MAX_WAIT_ANSWER: u64 = 4 * 1024 * 1024;
/// The admin holds `/wait` up to 50 s before it answers.
const WAIT_TIMEOUT: Duration = Duration::from_secs(80);
/// The inventory's body is at most 1 MiB.
pub const MAX_INVENTORY_BODY: usize = 1024 * 1024;
/// `/tickets`' answer: at most 50 tickets of at most 20 updates of at most 500 characters, escaped, and the signature.
const MAX_TICKETS_ANSWER: u64 = 4 * 1024 * 1024;
/// The body of a 403, read to tell "pending" apart.
const MAX_ERROR_BODY: u64 = 4096;
const USER_AGENT: &str = concat!("caramos-business-agent/", env!("CARGO_PKG_VERSION"));

/// Why a request to the admin failed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FetchError {
    /// No answer: connection refused or timed out, no route. The admin may have moved.
    Unreachable(String),
    /// An answer with an HTTP error status.
    Status(u16),
    /// 403 `{"error": "pending"}`: the machine waits for the admin's approval.
    Pending,
    /// 410: the admin removed the machine. Never trusted alone (anyone can send one): the agent fetches the policy,
    /// which then carries the signed removal notice.
    Gone,
    /// An answer that is not what the protocol says.
    Malformed(String),
    /// Writing a download on this machine failed.
    Local(String),
}

impl fmt::Display for FetchError {
    fn fmt(&self, formatter: &mut fmt::Formatter) -> fmt::Result {
        match self {
            FetchError::Unreachable(detail) => write!(formatter, "no answer: {detail}"),
            FetchError::Status(code) => write!(formatter, "HTTP status {code}"),
            FetchError::Pending => write!(formatter, "the admin has not approved this machine yet"),
            FetchError::Gone => write!(formatter, "HTTP status 410: the admin says this machine was removed"),
            FetchError::Malformed(detail) => write!(formatter, "unexpected answer: {detail}"),
            FetchError::Local(detail) => write!(formatter, "cannot write here: {detail}"),
        }
    }
}

impl std::error::Error for FetchError {}

fn local(error: io::Error) -> FetchError {
    FetchError::Local(error.to_string())
}

/// What authenticates the paired machine's requests.
#[derive(Clone, Debug)]
pub struct Auth {
    pub machine_id: String,
    pub keys: SharedKeys,
}

/// The admin at one address.
pub struct Admin {
    base: String,
    agent: ureq::Agent,
    auth: Option<Auth>,
}

fn agent_with(read_timeout: Duration) -> ureq::Agent {
    // No proxy (ureq reads none unless asked) and no redirects: the admin answers on the LAN itself.
    ureq::AgentBuilder::new()
        .timeout_connect(CONNECT_TIMEOUT)
        .timeout_read(read_timeout)
        .timeout_write(IO_TIMEOUT)
        .redirects(0)
        .user_agent(USER_AGENT)
        .build()
}

fn unix_now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|elapsed| elapsed.as_secs() as i64)
        .unwrap_or(0)
}

impl Admin {
    /// `base` is http://IP:PORT, as agent.json and discovery give it.
    pub fn new(base: &str) -> Admin {
        Admin { base: base.trim_end_matches('/').to_string(), agent: agent_with(IO_TIMEOUT), auth: None }
    }

    /// The same, for the paired machine's authenticated requests.
    pub fn with_auth(base: &str, auth: Auth) -> Admin {
        Admin { auth: Some(auth), ..Admin::new(base) }
    }

    pub fn base(&self) -> &str {
        &self.base
    }

    /// `GET /policy` (authenticated): the signed policy, or a removed machine's notice. The caller checks the
    /// signature.
    pub fn signed_policy(&self) -> Result<PolicyAnswer, FetchError> {
        let body = read_body(self.get("/policy", &self.agent)?, MAX_POLICY_ANSWER)?;
        PolicyAnswer::parse(&body).map_err(|error| FetchError::Malformed(format!("GET /policy: {error}")))
    }

    /// `GET /tickets` (authenticated): the machine's tickets, signed. The caller checks the signature.
    pub fn tickets(&self) -> Result<SignedTickets, FetchError> {
        let body = read_body(self.get("/tickets", &self.agent)?, MAX_TICKETS_ANSWER)?;
        serde_json::from_slice(&body).map_err(|error| FetchError::Malformed(format!("GET /tickets: {error}")))
    }

    /// An authenticated GET of `path` (under the API), as the paired machine.
    fn get(&self, path: &str, agent: &ureq::Agent) -> Result<ureq::Response, FetchError> {
        let target = format!("{API}{path}");
        answer(self.signed(agent.get(&format!("{}{target}", self.base)), "GET", &target, b"")?.call())
    }

    /// `GET /files/<sha>` (authenticated) into `dest`: written beside it under a temporary name, checked for its size
    /// and sha256, made 0644, and only then renamed into place.
    pub fn download(&self, sha: &str, size: u64, dest: &Path) -> Result<(), FetchError> {
        let started = Instant::now();
        policy::check_sha256(sha).map_err(|error| FetchError::Malformed(error.0))?;
        let response = self.get(&format!("/files/{sha}"), &self.agent)?;
        if let Some(length) = response.header("Content-Length").and_then(|value| value.trim().parse::<u64>().ok()) {
            if length != size {
                return Err(FetchError::Malformed(format!("the admin sends {length} bytes, the policy lists {size}")));
            }
        }
        let temp = dest.with_file_name(format!(".{sha}.{}.part", std::process::id()));
        let result = receive(response.into_reader(), &temp, size, started).and_then(|digest| {
            if digest != sha {
                return Err(FetchError::Malformed(format!("its sha256 is {digest}")));
            }
            fs::rename(&temp, dest).map_err(local)
        });
        if result.is_err() {
            let _ = fs::remove_file(&temp);
        }
        result
    }

    /// `POST /checkin` with a prepared JSON body (at most 64 KiB).
    pub fn check_in(&self, body: &[u8]) -> Result<(), FetchError> {
        self.post("/checkin", body, MAX_REQUEST_BODY)
    }

    /// `POST /inventory` (at most 1 MiB).
    pub fn inventory(&self, body: &[u8]) -> Result<(), FetchError> {
        self.post("/inventory", body, MAX_INVENTORY_BODY)
    }

    /// `POST /result`.
    pub fn result(&self, body: &[u8]) -> Result<(), FetchError> {
        self.post("/result", body, MAX_REQUEST_BODY)
    }

    /// `POST /help`: the answer names the ticket made, `{"ticket", "tickets": <version>}` from 0.3.
    pub fn help(&self, body: &[u8]) -> Result<serde_json::Value, FetchError> {
        let answer = self.post_answer("/help", body, MAX_REQUEST_BODY)?;
        Ok(serde_json::from_slice(&answer).unwrap_or_default())
    }

    /// `GET /wait?after=<last seq run>&serial=<serial of the stored policy, 0 if none>`: the admin answers at once
    /// when it holds newer commands or another serial, else after up to 50 s.
    pub fn wait(&self, after: u64, serial: u64) -> Result<WaitAnswer, FetchError> {
        let body = read_body(self.get(&format!("/wait?after={after}&serial={serial}"), &agent_with(WAIT_TIMEOUT))?, MAX_WAIT_ANSWER)?;
        serde_json::from_slice(&body).map_err(|error| FetchError::Malformed(format!("GET /wait: {error}")))
    }

    /// An authenticated POST of a JSON body of at most `max` bytes.
    fn post(&self, path: &str, body: &[u8], max: usize) -> Result<(), FetchError> {
        self.post_answer(path, body, max).map(|_| ())
    }

    /// The same, returning the answer's body.
    fn post_answer(&self, path: &str, body: &[u8], max: usize) -> Result<Vec<u8>, FetchError> {
        if body.len() > max {
            return Err(FetchError::Malformed(format!("the body of {path} is larger than {max} bytes")));
        }
        let target = format!("{API}{path}");
        let request = self.agent.post(&format!("{}{target}", self.base)).set("Content-Type", "application/json");
        let response = answer(self.signed(request, "POST", &target, body)?.send_bytes(body))?;
        read_body(response, MAX_SMALL_ANSWER)
    }

    /// Adds the machine's id, the time and the MAC of the request.
    fn signed(&self, request: ureq::Request, method: &str, target: &str, body: &[u8]) -> Result<ureq::Request, FetchError> {
        let auth = self.auth.as_ref().ok_or_else(|| FetchError::Local("the machine has no keys to sign its request".to_string()))?;
        let time = unix_now();
        let mac = auth.keys.request_mac(method, target, time, body);
        Ok(request
            .set("X-Caramos-Machine", &auth.machine_id)
            .set("X-Caramos-Time", &time.to_string())
            .set("X-Caramos-Mac", &mac))
    }
}

/// Sorts ureq's outcome into the agent's: an HTTP error status (403 pending and 410 apart), no answer at all, or
/// something that is not HTTP.
fn answer(result: Result<ureq::Response, ureq::Error>) -> Result<ureq::Response, FetchError> {
    match result {
        Ok(response) if response.status() == 200 => Ok(response),
        Ok(response) => Err(status_error(response.status(), response)),
        Err(ureq::Error::Status(code, response)) => Err(status_error(code, response)),
        Err(ureq::Error::Transport(transport)) => match transport.kind() {
            ureq::ErrorKind::BadStatus | ureq::ErrorKind::BadHeader => {
                Err(FetchError::Malformed(transport.to_string()))
            }
            _ => Err(FetchError::Unreachable(transport.to_string())),
        },
    }
}

/// The error for an answer with status `code`: a 403 whose body says `{"error": "pending"}` is the wait for
/// approval, a 410 the admin's claim that the machine was removed.
fn status_error(code: u16, response: ureq::Response) -> FetchError {
    match code {
        403 => {
            let body = read_body(response, MAX_ERROR_BODY).unwrap_or_default();
            let value: serde_json::Value = serde_json::from_slice(&body).unwrap_or_default();
            if value["error"].as_str() == Some("pending") {
                FetchError::Pending
            } else {
                FetchError::Status(403)
            }
        }
        410 => FetchError::Gone,
        _ => FetchError::Status(code),
    }
}

/// The whole body, if it is at most `max` bytes.
fn read_body(response: ureq::Response, max: u64) -> Result<Vec<u8>, FetchError> {
    let mut body = Vec::new();
    response
        .into_reader()
        .take(max + 1)
        .read_to_end(&mut body)
        .map_err(|error| FetchError::Unreachable(format!("the answer broke off: {error}")))?;
    if body.len() as u64 > max {
        return Err(FetchError::Malformed(format!("the answer is longer than {max} bytes")));
    }
    Ok(body)
}

/// Writes exactly `size` bytes from `reader` into `temp` and returns their sha256.
fn receive(mut reader: impl Read, temp: &Path, size: u64, started: Instant) -> Result<String, FetchError> {
    let mut file = OpenOptions::new().write(true).create(true).truncate(true).mode(0o644).open(temp).map_err(local)?;
    let mut hasher = Sha256::new();
    let mut total: u64 = 0;
    let mut buffer = vec![0u8; 64 * 1024];
    loop {
        if started.elapsed() > DOWNLOAD_TIMEOUT {
            return Err(FetchError::Unreachable("the download took too long".to_string()));
        }
        let count = match reader.read(&mut buffer) {
            Ok(0) => break,
            Ok(count) => count,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(FetchError::Unreachable(format!("the download broke off: {error}"))),
        };
        total += count as u64;
        if total > size {
            return Err(FetchError::Malformed(format!("the file is larger than the {size} bytes the policy lists")));
        }
        hasher.update(&buffer[..count]);
        file.write_all(&buffer[..count]).map_err(local)?;
    }
    if total != size {
        return Err(FetchError::Malformed(format!("the file has {total} bytes, the policy lists {size}")));
    }
    file.set_permissions(Permissions::from_mode(0o644)).map_err(local)?;
    file.sync_all().map_err(local)?;
    Ok(crypto::hex(&hasher.finalize()))
}
