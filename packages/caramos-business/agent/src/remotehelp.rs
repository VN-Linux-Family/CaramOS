//! Remote help, in the session of the user at the screen (PROTOCOL.md part 2 "Help requests and remote help", and
//! part 3 "Remote help: per-session key and a closed viewer port"):
//! 1. `caramos-business --prompt consent`: nothing happens unless the user accepts (60 s without an answer refuses);
//! 2. `stunnel` as a client: TLS 1.3 with the session's pre-shared key (the daemon unsealed it from the command) to the
//!    admin's `<admin_host>:<port>`, and a local port for x11vnc. The key authenticates both ends: only the admin that
//!    sealed it and this machine know it;
//! 3. `x11vnc -connect` through it to the admin's listening viewer, view-only unless the user allowed control;
//! 4. `caramos-business --prompt banner` while it runs. "Dừng", the viewer leaving or the end of the session stops
//!    x11vnc and stunnel. The result says how long it ran.

use std::fs;
use std::net::{Ipv4Addr, TcpListener};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::prompt::{self, NoAnswer, Prompt};
use crate::relay::Answer;

const CONSENT_TIMEOUT: Duration = Duration::from_secs(70);
const STUNNEL_READY: Duration = Duration::from_secs(10);

/// The stunnel client configuration: TLS 1.3 with the session's pre-shared key, no certificate (stunnel's PSK callback
/// works with SHA-256 suites only).
pub fn stunnel_config(local_port: u16, admin_host: Ipv4Addr, admin_port: u16, psk_file: &Path, identity: &str) -> String {
    format!(
        "; CaramOS Doanh nghiệp remote help (client), made for one session.\n\
         foreground = yes\n\
         pid =\n\
         [remote-help]\n\
         client = yes\n\
         accept = 127.0.0.1:{local_port}\n\
         connect = {admin_host}:{admin_port}\n\
         PSKsecrets = {}\n\
         PSKidentity = {identity}\n\
         ciphers = PSK\n\
         ciphersuites = TLS_AES_128_GCM_SHA256\n\
         sslVersionMin = TLSv1.3\n",
        psk_file.display()
    )
}

/// The line of stunnel's PSKsecrets file: `<identity>:<64 hex digits>`.
pub fn psk_line(identity: &str, key: &str) -> String {
    format!("{identity}:{key}\n")
}

/// The session's key from the inbox entry: an identity `rh-<16 hex>` and 64 hex digits.
pub fn psk_from(args: &Value) -> Option<(String, String)> {
    let hex = |text: &str, len: usize| text.len() == len && text.bytes().all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'));
    let identity = args["psk_identity"].as_str().filter(|identity| identity.strip_prefix("rh-").is_some_and(|digits| hex(digits, 16)))?;
    let key = args["psk_key"].as_str().filter(|key| hex(key, 64))?;
    Some((identity.to_string(), key.to_string()))
}

/// x11vnc's arguments: a reverse connection to the local stunnel port (x11vnc quits if it fails), once, listening on
/// no port of its own, view-only unless control was allowed.
pub fn x11vnc_args(display: &str, local_port: u16, control: bool) -> Vec<String> {
    let mut args = vec![
        "-display".to_string(),
        display.to_string(),
        "-connect_or_exit".to_string(),
        format!("127.0.0.1:{local_port}"),
        "-once".to_string(),
        "-nopw".to_string(),
        "-noshm".to_string(),
        "-localhost".to_string(),
        "-rfbport".to_string(),
        "0".to_string(),
    ];
    if !control {
        args.push("-viewonly".to_string());
    }
    args
}

/// "chạy 12 phút" or "chạy 40 giây".
pub fn ran_for(elapsed: Duration) -> String {
    let seconds = elapsed.as_secs();
    if seconds < 60 {
        format!("chạy {seconds} giây")
    } else {
        format!("chạy {} phút", (seconds + 30) / 60)
    }
}

/// A finished session's detail: how long it ran, the mode in English in brackets, and how it ended ("chạy 19 giây
/// (control), người dùng dừng"). The admin shows "(control)" and "(view)" in its reader's language (PROTOCOL.md part 3,
/// "Changes during implementation", 0.3.1).
pub fn done_detail(elapsed: Duration, mode: &str, ending: &str) -> String {
    format!("{} ({mode}), {ending}", ran_for(elapsed))
}

fn answer(id: &str, state: &str, detail: impl Into<String>, given: &str) -> Answer {
    Answer { id: id.to_string(), state: state.to_string(), detail: detail.into(), answer: given.to_string() }
}

fn program(names: &[&str]) -> Option<PathBuf> {
    names.iter().map(|name| Path::new("/usr/bin").join(name)).find(|path| path.exists())
}

fn stop(child: &mut Option<Child>) {
    if let Some(child) = child.as_mut() {
        let _ = child.kill();
        let _ = child.wait();
    }
    *child = None;
}

/// Runs one remote help session for the command `id` with its `args`, and says how it went.
pub fn run(id: &str, args: &Value, admin_name: &str, runtime_dir: &Path, cancel: &AtomicBool) -> Answer {
    let host: Option<Ipv4Addr> = args["admin_host"].as_str().and_then(|host| host.parse().ok());
    let port = args["port"].as_u64().and_then(|port| u16::try_from(port).ok()).filter(|port| *port > 1024);
    let (Some(host), Some(port), Some((identity, key))) = (host, port, psk_from(args)) else {
        return answer(id, "failed", "lệnh hỗ trợ từ xa không hợp lệ", "");
    };
    let viewer = args["admin_name"].as_str().filter(|name| !name.is_empty()).unwrap_or(admin_name);
    let asked = args["mode"].as_str().unwrap_or("view");
    let options = vec!["--admin".to_string(), viewer.to_string(), "--mode".to_string(), asked.to_string()];
    let given = match prompt::ask("consent", &options, Some(CONSENT_TIMEOUT), cancel) {
        Ok(given) => given,
        Err(NoAnswer::Timeout) => return answer(id, "refused", "không trả lời trong 60 giây", "refuse"),
        Err(NoAnswer::Cancelled) => return answer(id, "failed", "phiên đã kết thúc", ""),
        Err(NoAnswer::Failed(error)) => return answer(id, "failed", error, ""),
    };
    if given == "refuse" {
        return answer(id, "refused", "người dùng từ chối", "refuse");
    }
    // Control only if both asked for it and allowed it.
    let control = given == "control" && asked == "control";
    let mode = if control { "control" } else { "view" };
    let (Some(stunnel), Some(x11vnc)) = (program(&["stunnel4", "stunnel"]), program(&["x11vnc"])) else {
        return answer(id, "failed", "máy này chưa cài stunnel4 hoặc x11vnc", &given);
    };
    let Ok(display) = std::env::var("DISPLAY") else {
        return answer(id, "failed", "phiên này không có DISPLAY", &given);
    };
    let dir = runtime_dir.join("caramos-business/remote-help");
    let psk_file = dir.join("psk.txt");
    let prepared = fs::create_dir_all(&dir)
        .and_then(|()| fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)))
        .and_then(|()| crate::store::write_atomic(&psk_file, psk_line(&identity, &key).as_bytes(), 0o600));
    if let Err(error) = prepared {
        let _ = fs::remove_dir_all(&dir);
        return answer(id, "failed", format!("{}: {error}", dir.display()), &given);
    }
    let Ok(local_port) = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).and_then(|listener| listener.local_addr()).map(|address| address.port()) else {
        let _ = fs::remove_dir_all(&dir);
        return answer(id, "failed", "không có cổng cục bộ trống", &given);
    };
    if let Err(error) = fs::write(dir.join("stunnel.conf"), stunnel_config(local_port, host, port, &psk_file, &identity)) {
        let _ = fs::remove_dir_all(&dir);
        return answer(id, "failed", error.to_string(), &given);
    }
    let started = Instant::now();
    let mut tunnel = Command::new(&stunnel).arg(dir.join("stunnel.conf")).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().ok();
    // Ready once stunnel holds the port. Never connect to find out: that would open a tunnel to the admin's viewer,
    // which takes one connection.
    let ready = Instant::now() + STUNNEL_READY;
    while TcpListener::bind((Ipv4Addr::LOCALHOST, local_port)).is_ok() {
        if Instant::now() >= ready || tunnel.as_mut().is_none_or(|child| !matches!(child.try_wait(), Ok(None))) {
            stop(&mut tunnel);
            let _ = fs::remove_dir_all(&dir);
            return answer(id, "failed", "stunnel không chạy được", &given);
        }
        thread::sleep(Duration::from_millis(200));
    }
    let mut vnc = Command::new(&x11vnc).args(x11vnc_args(&display, local_port, control)).stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn().ok();
    let banner_options = vec!["--admin".to_string(), viewer.to_string(), "--mode".to_string(), mode.to_string()];
    let mut banner = Prompt::start("banner", &banner_options).ok();
    let mut connected = false;
    let ending = loop {
        if cancel.load(Ordering::SeqCst) {
            break "phiên đã kết thúc";
        }
        if banner.as_mut().is_some_and(|banner| banner.try_answer().is_some() || banner.finished()) {
            break "người dùng dừng";
        }
        match vnc.as_mut().map(|child| child.try_wait()) {
            Some(Ok(None)) => {}
            _ => break if connected { "bên quản lý đã đóng" } else { "không kết nối được tới máy quản lý" },
        }
        // x11vnc keeps running only once the viewer took the connection.
        connected |= started.elapsed() > Duration::from_secs(5);
        thread::sleep(Duration::from_millis(500));
    };
    if let Some(banner) = banner.as_mut() {
        banner.close();
    }
    stop(&mut vnc);
    stop(&mut tunnel);
    let _ = fs::remove_dir_all(&dir);
    let elapsed = started.elapsed();
    if connected {
        answer(id, "done", done_detail(elapsed, mode, ending), &given)
    } else {
        answer(id, "failed", ending, &given)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn configuration() {
        let config = stunnel_config(40123, Ipv4Addr::new(192, 168, 1, 10), 5501, Path::new("/run/user/1000/caramos-business/remote-help/psk.txt"), "rh-0123456789abcdef");
        assert!(config.contains("client = yes\n"));
        assert!(config.contains("accept = 127.0.0.1:40123\n"));
        assert!(config.contains("connect = 192.168.1.10:5501\n"));
        assert!(config.contains("PSKsecrets = /run/user/1000/caramos-business/remote-help/psk.txt\n"));
        assert!(config.contains("PSKidentity = rh-0123456789abcdef\n"));
        assert!(config.contains("ciphers = PSK\nciphersuites = TLS_AES_128_GCM_SHA256\nsslVersionMin = TLSv1.3\n"));
        assert!(!config.contains("verifyPeer") && !config.contains("CAfile"));
        let args = serde_json::json!({"psk_identity": "rh-0123456789abcdef", "psk_key": "20".repeat(32)});
        let (identity, key) = psk_from(&args).unwrap();
        assert_eq!(psk_line(&identity, &key), format!("rh-0123456789abcdef:{}\n", "20".repeat(32)));
        assert_eq!(psk_from(&serde_json::json!({"psk_identity": "x", "psk_key": "20".repeat(32)})), None);
        assert_eq!(x11vnc_args(":0", 40123, false).last().unwrap(), "-viewonly");
        assert!(!x11vnc_args(":0", 40123, true).contains(&"-viewonly".to_string()));
        assert_eq!(ran_for(Duration::from_secs(40)), "chạy 40 giây");
        assert_eq!(ran_for(Duration::from_secs(12 * 60 + 10)), "chạy 12 phút");
        assert_eq!(done_detail(Duration::from_secs(19), "control", "người dùng dừng"), "chạy 19 giây (control), người dùng dừng");
        assert_eq!(done_detail(Duration::from_secs(150), "view", "bên quản lý đã đóng"), "chạy 3 phút (view), bên quản lý đã đóng");
    }
}
