//! Service rounds against a stand-in admin on this machine (plain HTTP on 127.0.0.1) that checks every authenticated
//! request's MAC with the admin's side of the test keys, GETs included as from 0.3: the signed format 2 policy fetched
//! and checked, its file downloaded, this machine's effective settings written for the session parts, the system
//! sections applied (to a test folder, without commands), the check-in with health and capabilities; the commands from
//! `/wait`, open from the round that loaded the pairing; the policies that must not be stored; and 0.3's approval,
//! removal notice and tickets. The failing cases call `update` rather than a round, which would broadcast a discovery
//! on the LAN.

use std::collections::HashMap;
use std::fs;
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use caramos_business_agent::commands::Action;
use caramos_business_agent::crypto::{self, SharedKeys};
use caramos_business_agent::daemon::{self, Daemon, Failure, Fetched, Paths, Updated};
use caramos_business_agent::fetch::{Admin, Auth};
use caramos_business_agent::protocol::{Envelope, ResultState};
use caramos_business_agent::sections::System;
use caramos_business_agent::store::{AgentConfig, Store};
use ed25519_dalek::{Signer, SigningKey};
use serde_json::{json, Value};

const SHA: &str = "a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7";
const MACHINE_ID: &str = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6";

fn examples() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/protocol-examples")
}

fn example(name: &str) -> Vec<u8> {
    fs::read(examples().join(name)).unwrap()
}

fn v2(name: &str) -> Value {
    serde_json::from_slice(&example(&format!("v2/{name}"))).unwrap()
}

fn v3(name: &str) -> Value {
    serde_json::from_slice(&example(&format!("v3/{name}"))).unwrap()
}

fn key(name: &str) -> [u8; 32] {
    crypto::decode_key32(v2("keys.json")[name].as_str().unwrap(), name).unwrap()
}

/// A new folder, removed when dropped.
struct TempDir(PathBuf);

impl TempDir {
    fn new(name: &str) -> TempDir {
        static NEXT: AtomicUsize = AtomicUsize::new(0);
        let path = std::env::temp_dir().join(format!("caramos-business-it-{name}-{}-{}", std::process::id(), NEXT.fetch_add(1, Ordering::SeqCst)));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).unwrap();
        TempDir(path)
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

/// One request the stand-in admin received.
#[derive(Debug, Clone)]
struct Received {
    method: String,
    target: String,
    body: Vec<u8>,
    /// None for a request without the headers, else whether its MAC was right.
    mac_ok: Option<bool>,
}

/// How the stand-in admin sees this machine (PROTOCOL.md part 3).
#[derive(Debug, Clone)]
enum Standing {
    Approved,
    /// 403 `{"error": "pending"}` on every authenticated request.
    Pending,
    /// GET /policy answers this notice, every other authenticated request 410.
    Removed(Value),
}

/// The stand-in admin's answers to GETs: path → (status, body).
type Answers = Mutex<HashMap<String, (u16, Vec<u8>)>>;

/// The stand-in admin: fixed answers for authenticated GETs, `{"ok": true}` to authenticated POSTs, 401 to any request
/// without a right MAC but /hello.
struct FakeAdmin {
    port: u16,
    answers: Arc<Answers>,
    received: Arc<Mutex<Vec<Received>>>,
    standing: Arc<Mutex<Standing>>,
}

impl FakeAdmin {
    fn start() -> FakeAdmin {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let answers = Arc::new(Mutex::new(HashMap::new()));
        let received = Arc::new(Mutex::new(Vec::new()));
        let standing = Arc::new(Mutex::new(Standing::Approved));
        let (served, log, state) = (answers.clone(), received.clone(), standing.clone());
        let keys = SharedKeys::derive(&key("admin_box_seed"), &key("machine_box_public")).unwrap();
        thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                serve(stream, &served, &log, &keys, &state);
            }
        });
        FakeAdmin { port, answers, received, standing }
    }

    fn url(&self) -> String {
        format!("http://127.0.0.1:{}", self.port)
    }

    fn answer(&self, path: &str, body: impl Into<Vec<u8>>) {
        self.answers.lock().unwrap().insert(format!("/caramos-business/v1{path}"), (200, body.into()));
    }

    fn signed_policy(&self, policy: &str, key: &SigningKey) {
        let signature = STANDARD.encode(key.sign(policy.as_bytes()).to_bytes());
        self.answer("/policy", json!({"policy": policy, "signature": signature}).to_string());
    }

    fn stand(&self, standing: Standing) {
        *self.standing.lock().unwrap() = standing;
    }

    fn requests(&self, path: &str) -> Vec<Received> {
        self.received.lock().unwrap().iter().filter(|request| request.target.starts_with(&format!("/caramos-business/v1{path}"))).cloned().collect()
    }
}

fn serve(stream: TcpStream, answers: &Answers, log: &Mutex<Vec<Received>>, keys: &SharedKeys, standing: &Mutex<Standing>) {
    let Ok(clone) = stream.try_clone() else {
        return;
    };
    let mut reader = BufReader::new(clone);
    let mut request = String::new();
    if reader.read_line(&mut request).unwrap_or(0) == 0 {
        return;
    }
    let mut headers = HashMap::new();
    loop {
        let mut header = String::new();
        if reader.read_line(&mut header).unwrap_or(0) == 0 || header == "\r\n" {
            break;
        }
        if let Some((name, value)) = header.split_once(':') {
            headers.insert(name.trim().to_ascii_lowercase(), value.trim().to_string());
        }
    }
    let length = headers.get("content-length").and_then(|value| value.parse().ok()).unwrap_or(0);
    let mut body = vec![0; length];
    if reader.read_exact(&mut body).is_err() {
        return;
    }
    let mut words = request.split_whitespace();
    let (method, target) = (words.next().unwrap_or_default().to_string(), words.next().unwrap_or_default().to_string());
    let mac_ok = match (headers.get("x-caramos-machine"), headers.get("x-caramos-time"), headers.get("x-caramos-mac")) {
        (Some(machine), Some(time), Some(mac)) => {
            let expected = keys.request_mac(&method, &target, time.parse().unwrap_or(0), &body);
            Some(machine == MACHINE_ID && *mac == expected)
        }
        _ => None,
    };
    log.lock().unwrap().push(Received { method: method.clone(), target: target.clone(), body, mac_ok });
    let (status, answer) = if target == "/caramos-business/v1/hello" {
        (200, br#"{"name": "may-quan-ly", "fingerprint": "56475aa75463474c", "pairing": false}"#.to_vec())
    } else if mac_ok != Some(true) {
        (401, b"{}".to_vec())
    } else {
        match standing.lock().unwrap().clone() {
            Standing::Pending => (403, br#"{"error": "pending"}"#.to_vec()),
            Standing::Removed(notice) if target == "/caramos-business/v1/policy" => (200, notice.to_string().into_bytes()),
            Standing::Removed(_) => (410, Vec::new()),
            Standing::Approved if method == "POST" => (200, br#"{"ok": true}"#.to_vec()),
            Standing::Approved => answers.lock().unwrap().get(&target).cloned().unwrap_or((404, b"{}".to_vec())),
        }
    };
    let mut stream = stream;
    let head = format!("HTTP/1.1 {status} X\r\nContent-Length: {}\r\nConnection: close\r\n\r\n", answer.len());
    let _ = stream.write_all(head.as_bytes()).and_then(|()| stream.write_all(&answer));
}

fn admin_key() -> SigningKey {
    SigningKey::from_bytes(&key("admin_sign_seed"))
}

/// agent.json (without a token) and the machine box key, as the helper writes them at pairing: from 0.3 with the
/// admin's box key, which signs the first `GET /policy`.
fn pair(dir: &Path, admin: &FakeAdmin) -> (Paths, AgentConfig) {
    let paths = Paths {
        config: dir.join("etc/agent.json"),
        box_key: dir.join("etc/agent-box.key"),
        state: dir.join("state"),
        run_user: dir.join("run/user"),
        inbox: dir.join("run/caramos-business/inbox"),
        sessions: dir.join("run/systemd/sessions"),
        os_machine_id: dir.join("etc/machine-id"),
        proc: dir.join("proc"),
    };
    fs::create_dir_all(dir.join("etc")).unwrap();
    let agent = json!({
        "admin_url": admin.url(),
        "admin_name": "may-quan-ly",
        "admin_key": v2("keys.json")["admin_sign_public"],
        "admin_box_key": v2("keys.json")["admin_box_public"],
        "fingerprint": "56475aa75463474c",
        "machine_id": MACHINE_ID
    });
    fs::write(&paths.config, agent.to_string()).unwrap();
    fs::write(&paths.box_key, key("machine_box_seed")).unwrap();
    let config = AgentConfig::load(&paths.config).unwrap().unwrap();
    (paths, config)
}

/// What signs the machine's requests.
fn auth() -> Auth {
    Auth { machine_id: MACHINE_ID.to_string(), keys: SharedKeys::derive(&key("machine_box_seed"), &key("admin_box_public")).unwrap() }
}

/// The v2 policy with another serial and, to tell them apart, another admin name.
fn policy_with_serial(serial: u64, admin_name: &str) -> String {
    let mut policy = v2("policy.json");
    policy["serial"] = serial.into();
    policy["admin"] = admin_name.into();
    serde_json::to_string_pretty(&policy).unwrap()
}

fn mode(path: &Path) -> u32 {
    fs::metadata(path).unwrap().permissions().mode() & 0o777
}

/// A test root with the files the sections read, and the accounts: lan (1001) with a group of its own.
fn system_root(dir: &Path) -> System {
    let root = dir.join("root");
    fs::create_dir_all(root.join("etc")).unwrap();
    fs::write(root.join("etc/hosts"), "127.0.0.1 localhost\n").unwrap();
    fs::write(root.join("etc/passwd"), "root:x:0:0:root:/root:/bin/bash\nlan:x:1001:1001::/home/lan:/bin/bash\nminh:x:1002:100::/home/minh:/bin/bash\n").unwrap();
    fs::write(root.join("etc/group"), "root:x:0:\nusers:x:100:\nlan:x:1001:\n").unwrap();
    System::test(&root)
}

fn updated(fetched: Result<Fetched, Failure>) -> Updated {
    match fetched {
        Ok(Fetched::Policy(updated)) => updated,
        other => panic!("{other:?}"),
    }
}

#[test]
fn a_cloned_disk_does_nothing_until_paired_again() {
    let dir = TempDir::new("clone");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    // The helper kept /etc/machine-id at pairing; this disk now has another one.
    let mut agent: Value = serde_json::from_slice(&fs::read(&paths.config).unwrap()).unwrap();
    agent["machine_id_os"] = "0123456789abcdef0123456789abcdef".into();
    fs::write(&paths.config, agent.to_string()).unwrap();
    fs::write(&paths.os_machine_id, "fedcba9876543210fedcba9876543210\n").unwrap();
    let system = system_root(&dir.0);
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);
    assert_eq!(daemon.round_now().unwrap_err(), daemon::CLONE_MESSAGE);
    assert!(admin.received.lock().unwrap().is_empty(), "nothing fetched or reported");
    assert!(!paths.state.join("effective.json").exists(), "nothing for the session parts");
    let hosts = fs::read_to_string(system.path("/etc/hosts")).unwrap();
    assert!(!hosts.contains("caramos-business"), "nothing applied: {hosts}");
    let marker: Value = serde_json::from_slice(&fs::read(paths.state.join("clone.json")).unwrap()).unwrap();
    assert_eq!(marker["this_machine"], "fedcba9876543210fedcba9876543210");
    daemon.receive(vec![]); // no current pairing: commands go nowhere

    // The machine that was paired: everything as usual, and the mark goes.
    fs::write(&paths.os_machine_id, "0123456789abcdef0123456789abcdef\n").unwrap();
    daemon.round_now().unwrap().unwrap();
    assert!(!paths.state.join("clone.json").exists());
    assert!(paths.state.join("effective.json").exists());
    assert!(!admin.requests("/checkin").is_empty());
}

#[test]
fn leave_puts_everything_back() {
    let dir = TempDir::new("leave");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);
    daemon.round_now().unwrap().unwrap();
    let profile = system.path("/etc/NetworkManager/system-connections/caramos-business-congty.nmconnection");
    assert!(profile.exists());
    fs::create_dir_all(paths.inbox.join("1000")).unwrap();
    fs::write(paths.state.join("clone.json"), "{}\n").unwrap(); // a cloned disk leaving, for "Ghép lại"

    // A session part of this user, whose last status still shows a section applied; it writes a new one, with
    // nothing applied, a moment after effective.json goes away.
    let uid = caramos_business_agent::process::uid().unwrap();
    let runtime = paths.run_user.join(uid.to_string()).join("caramos-business");
    fs::create_dir_all(&runtime).unwrap();
    fs::write(runtime.join("session.pid"), format!("{}\n", std::process::id())).unwrap();
    let status = |applied: Value| json!({"user": "lan", "wallpaper": "off", "folders": "off", "detail": "", "time": "", "applied": applied}).to_string();
    fs::write(runtime.join("status.json"), status(json!({"shares": "ok"}))).unwrap();
    let effective = paths.state.join("effective.json");
    let session_part = {
        let (runtime, effective, status) = (runtime.clone(), effective.clone(), status(json!({})));
        thread::spawn(move || {
            while effective.exists() {
                thread::sleep(std::time::Duration::from_millis(50));
            }
            thread::sleep(std::time::Duration::from_millis(300));
            fs::write(runtime.join("status.json"), status).unwrap();
        })
    };

    let left = daemon::leave(&paths, &system, std::time::Duration::from_secs(10));
    session_part.join().unwrap();
    assert!(left.failed.is_empty(), "{:?}", left.failed);
    assert!(!left.reboot_needed, "not frozen");
    assert_eq!((left.users_done.len(), left.users_late.len()), (1, 0));
    assert!(!system.path("/etc/firefox/policies/policies.json").exists());
    let hosts = fs::read_to_string(system.path("/etc/hosts")).unwrap();
    assert!(hosts.contains("127.0.0.1 localhost") && !hosts.contains("caramos-business"), "{hosts}");
    assert!(!system.path("/etc/polkit-1/rules.d/71-caramos-business-usb.rules").exists());
    assert!(!profile.exists());
    assert!(!effective.exists());
    assert!(!paths.state.join("commands.json").exists());
    assert!(!paths.state.join("clone.json").exists());
    assert!(!paths.state.join("approval.json").exists());
    assert!(!paths.inbox.exists());
    let managed: Value = serde_json::from_slice(&fs::read(paths.state.join("managed.json")).unwrap()).unwrap();
    for key in ["printers", "usb", "wifi", "chromium"] {
        assert_eq!(managed[key], json!([]), "{key}");
    }
    assert_eq!((managed["firefox"].clone(), managed["hosts"].clone(), managed["firewall"].clone()), (Value::Null, json!(false), Value::Null));

    // Nobody's session part answers: the users are named, and it ends after the wait.
    fs::write(runtime.join("status.json"), status(json!({"shares": "ok"}))).unwrap();
    let left = daemon::leave(&paths, &system, std::time::Duration::from_millis(300));
    assert_eq!((left.users_done.len(), left.users_late.len()), (0, 1));
}

/// A desktop open since before pairing, for the current user: its login in logind's files and a program of it in
/// /proc; no session part runs for it.
fn open_desktop(paths: &Paths) -> PathBuf {
    let uid = caramos_business_agent::process::uid().unwrap();
    fs::create_dir_all(&paths.sessions).unwrap();
    let login = format!("UID={uid}\nUSER=lan\nACTIVE=1\nSTATE=active\nTYPE=x11\nCLASS=user\nSEAT=seat0\nDESKTOP=cinnamon\nREALTIME=1795447874366476\n");
    fs::write(paths.sessions.join("c1"), login).unwrap();
    fs::create_dir_all(paths.proc.join("1437")).unwrap();
    fs::write(paths.proc.join("1437/environ"), "XDG_SESSION_ID=c1\0DISPLAY=:0\0XDG_CURRENT_DESKTOP=X-Cinnamon\0").unwrap();
    fs::write(paths.proc.join("1437/stat"), "1437 (caramos-evoluti) S 975 1 1 0").unwrap();
    paths.run_user.join(uid.to_string()).join("caramos-business")
}

#[test]
fn the_notice_comes_before_the_system_sections() {
    let dir = TempDir::new("notice-first");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let runtime = open_desktop(&paths);
    // The session part the daemon starts (systemd-run, which the test system only pretends to run): once effective.json
    // is written it shows the notice and says so in notice.json. The daemon's own sections must not be on before.
    let session_part = {
        let (effective, runtime, hosts) = (paths.state.join("effective.json"), runtime.clone(), system.path("/etc/hosts"));
        thread::spawn(move || {
            while !effective.exists() {
                thread::sleep(std::time::Duration::from_millis(20));
            }
            thread::sleep(std::time::Duration::from_millis(500));
            let hosts_then = fs::read_to_string(&hosts).unwrap();
            let settings: Value = serde_json::from_slice(&fs::read(&effective).unwrap()).unwrap();
            let mut sections: Vec<&String> = settings["settings"].as_object().unwrap().iter().filter(|(_, value)| !value.is_null()).map(|(key, _)| key).collect();
            sections.sort();
            fs::create_dir_all(&runtime).unwrap();
            fs::write(runtime.join("notice.json"), json!({"machine_id": MACHINE_ID, "sections": sections}).to_string()).unwrap();
            hosts_then
        })
    };
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);
    let started = std::time::Instant::now();
    daemon.round_now().unwrap().unwrap();
    let hosts_before_the_notice = session_part.join().unwrap();
    assert!(!hosts_before_the_notice.contains("caramos-business"), "the websites were blocked before the notice showed");
    assert!(fs::read_to_string(system.path("/etc/hosts")).unwrap().contains("# BEGIN caramos-business"));
    assert!(started.elapsed() < std::time::Duration::from_secs(10), "it waited for the notice only");

    // Everything in effect was told: the next round does not wait.
    let started = std::time::Instant::now();
    daemon.round_now().unwrap().unwrap();
    assert!(started.elapsed() < std::time::Duration::from_secs(5));
}

#[test]
fn a_user_who_never_sees_the_notice_holds_the_settings_back_once() {
    let dir = TempDir::new("notice-late");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let runtime = open_desktop(&paths);
    // An earlier pairing's notice does not count.
    fs::create_dir_all(&runtime).unwrap();
    fs::write(runtime.join("notice.json"), r#"{"machine_id": "11111111-2222-4333-8444-555555555555", "sections": ["usb"]}"#).unwrap();
    let (worker, _queued) = mpsc::channel();
    let mut daemon = Daemon::new(paths.clone(), system.clone(), worker);
    daemon.wait_for_notice_at_most(std::time::Duration::from_millis(800));
    let started = std::time::Instant::now();
    daemon.round_now().unwrap().unwrap();
    assert!(started.elapsed() >= std::time::Duration::from_millis(800), "it waited");
    assert!(fs::read_to_string(system.path("/etc/hosts")).unwrap().contains("# BEGIN caramos-business"), "then applied");
    // The same login, still not told: the next rounds do not wait again.
    let started = std::time::Instant::now();
    daemon.round_now().unwrap().unwrap();
    assert!(started.elapsed() < std::time::Duration::from_millis(700));
    // Nobody at the machine: nothing waits.
    fs::remove_file(paths.sessions.join("c1")).unwrap();
    let started = std::time::Instant::now();
    daemon.round_now().unwrap().unwrap();
    assert!(started.elapsed() < std::time::Duration::from_millis(700));
}

#[test]
fn a_round_stores_applies_and_checks_in() {
    let dir = TempDir::new("round");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);

    let updated = daemon.round_now().unwrap().unwrap();
    assert_eq!((updated.serial, updated.changed, updated.downloaded), (12, true, 1));
    let signed = v2("signed-policy.json");
    let stored = paths.state.join("policy.json");
    assert_eq!(fs::read_to_string(&stored).unwrap(), signed["policy"].as_str().unwrap());
    assert_eq!(mode(&stored), 0o644);
    assert_eq!(fs::read(paths.state.join(format!("files/{SHA}.jpg"))).unwrap(), example(&format!("file-{SHA}")));
    // From 0.3 the policy and its files are read only by paired machines: both GETs carry a right MAC.
    for path in ["/policy", "/files/"] {
        let gets = admin.requests(path);
        assert!(!gets.is_empty() && gets.iter().all(|request| request.mac_ok == Some(true) && request.method == "GET"), "{path}");
    }

    // The session parts' copy of this machine's effective settings.
    let effective = Store::new(&paths.state).load_effective().unwrap();
    assert_eq!(effective.machine_id, MACHINE_ID);
    assert_eq!(effective.department.as_deref(), Some("ke-toan"));
    assert_eq!(Value::Object(effective.settings), v2("effective-machine.json"));
    let raw: Value = serde_json::from_slice(&fs::read(paths.state.join("effective.json")).unwrap()).unwrap();
    assert!(raw.get("remote_help_cert").is_none(), "gone from 0.3");
    assert_eq!(mode(&paths.state.join("effective.json")), 0o644);
    let approval: Value = serde_json::from_slice(&fs::read(paths.state.join("approval.json")).unwrap()).unwrap();
    assert_eq!(approval["state"], "approved", "the first policy");

    // The system sections, applied to the test root: the browser's files, the USB block of the department, the Wi-Fi
    // profile with the passphrase unsealed for this machine.
    assert!(system.path("/etc/firefox/policies/policies.json").exists());
    assert!(fs::read_to_string(system.path("/etc/hosts")).unwrap().contains("# BEGIN caramos-business"));
    assert!(system.path("/etc/polkit-1/rules.d/71-caramos-business-usb.rules").exists());
    let profile = fs::read_to_string(system.path("/etc/NetworkManager/system-connections/caramos-business-congty.nmconnection")).unwrap();
    assert!(profile.contains("\npsk=matkhau-wifi-123\n"));
    let managed: Value = serde_json::from_slice(&fs::read(paths.state.join("managed.json")).unwrap()).unwrap();
    assert_eq!(managed["printers"], json!(["caramos-may-in-tang-2"]));
    assert_eq!(mode(&paths.state.join("managed.json")), 0o600);

    // The check-in: authenticated, no token, with health and capabilities.
    let check_ins = admin.requests("/checkin");
    assert_eq!(check_ins.len(), 1);
    assert_eq!(check_ins[0].mac_ok, Some(true));
    let body: Value = serde_json::from_slice(&check_ins[0].body).unwrap();
    assert_eq!(body["machine_id"], MACHINE_ID);
    assert!(body.get("token").is_none());
    assert_eq!(body["policy_serial"], 12);
    assert_eq!(body["capabilities"], v3("health.json")["capabilities"]);
    assert_eq!(body["health"]["applied"]["browser"], "ok");
    assert_eq!(body["health"]["applied"]["usb"], "ok");
    assert_eq!(body["health"]["applied"]["wifi"], "ok");
    assert!(body["health"]["applied"]["apps"].as_str().unwrap().starts_with("failed: "), "App Center is not in the test root");
    for key in v3("health.json")["health"].as_object().unwrap().keys().filter(|key| *key != "applied") {
        assert!(body["health"].get(key).is_some(), "health.{key}");
    }
    assert_eq!(body["health"]["usb_storage"], "block");
    assert_eq!((body["health"]["frozen"].clone(), body["health"]["freeze_configured"].clone()), (json!(false), json!(false)));
    // The inventory is opt-in: the vectors' policy does not turn it on.
    assert!(admin.requests("/inventory").is_empty());

    // The next round has nothing new to store.
    let again = daemon.round_now().unwrap().unwrap();
    assert_eq!((again.serial, again.changed, again.downloaded), (12, false, 0));
}

#[test]
fn a_new_machine_waits_for_approval() {
    let dir = TempDir::new("approval");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v3/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    admin.answer("/tickets", example("v3/tickets.json"));
    admin.stand(Standing::Pending);
    let (paths, _) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);
    assert_eq!(daemon.round_now().unwrap_err(), daemon::PENDING_MESSAGE);
    let approval: Value = serde_json::from_slice(&fs::read(paths.state.join("approval.json")).unwrap()).unwrap();
    assert_eq!(approval["state"], "pending");
    assert!(approval["since"].as_str().unwrap().ends_with("+07:00"));
    assert_eq!(mode(&paths.state.join("approval.json")), 0o644);
    assert_eq!(admin.received.lock().unwrap().len(), 1, "only the policy was asked for");
    assert!(!paths.state.join("policy.json").exists() && !paths.state.join("effective.json").exists());
    // Asked again a minute later: the same file, the same time.
    let since = approval["since"].clone();
    assert!(daemon.round_now().is_err());
    let again: Value = serde_json::from_slice(&fs::read(paths.state.join("approval.json")).unwrap()).unwrap();
    assert_eq!(again["since"], since);

    // Approved: the first policy, the check-in, the tickets.
    admin.stand(Standing::Approved);
    let updated = daemon.round_now().unwrap().unwrap();
    assert_eq!(updated.serial, 21);
    let approval: Value = serde_json::from_slice(&fs::read(paths.state.join("approval.json")).unwrap()).unwrap();
    assert_eq!(approval["state"], "approved");
    assert_eq!(admin.requests("/checkin").len(), 1);
    let check_in: Value = serde_json::from_slice(&admin.requests("/checkin")[0].body).unwrap();
    assert_eq!(check_in["health"]["applied"]["snapshots"], "failed: Timeshift is not installed");
    assert!(check_in["health"]["applied"].get("shared").is_none(), "not this machine's");

    // The tickets of the user lan, root's with lan's own group, 0640; minh has no account here.
    assert_eq!(admin.requests("/tickets").len(), 1);
    assert!(admin.requests("/tickets")[0].mac_ok == Some(true));
    let tickets = paths.state.join("tickets");
    let file: Value = serde_json::from_slice(&fs::read(tickets.join("1001.json")).unwrap()).unwrap();
    assert_eq!(file, v3("tickets-user-lan.json"));
    assert_eq!(mode(&tickets.join("1001.json")), 0o640);
    assert_eq!(mode(&tickets), 0o755);
    assert_eq!(fs::read_to_string(tickets.join("version")).unwrap(), "7\n");
    assert_eq!(mode(&tickets.join("version")), 0o600);
    assert_eq!(fs::read_dir(&tickets).unwrap().count(), 2, "minh's tickets are dropped (no private group)");
}

#[test]
fn a_removal_notice_puts_everything_back() {
    let dir = TempDir::new("removal");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, config) = pair(&dir.0, &admin);
    let system = system_root(&dir.0);
    let (worker, _queued) = mpsc::channel();
    let daemon = Daemon::new(paths.clone(), system.clone(), worker);
    daemon.round_now().unwrap().unwrap();
    assert!(fs::read_to_string(system.path("/etc/hosts")).unwrap().contains("caramos-business"));

    // A notice that fails a check is ignored: another machine's, or one whose signature does not match.
    let store = Store::new(&paths.state);
    for name in ["removed-notice-other.json", "removed-notice-tampered.json"] {
        admin.stand(Standing::Removed(v3(name)));
        let failure = daemon::update(&Admin::with_auth(&admin.url(), auth()), &config, &store).unwrap_err();
        assert!(matches!(failure, Failure::BadNotice(_)), "{name}: {failure}");
        assert!(!failure.admin_proven(), "{name}");
    }
    assert!(paths.config.exists());

    // The real one: everything goes back, ufw too, the pairing goes, removed.json for the window.
    admin.stand(Standing::Removed(v3("removed-notice.json")));
    assert_eq!(daemon.round_now().unwrap_err(), daemon::REMOVED_MESSAGE);
    let hosts = fs::read_to_string(system.path("/etc/hosts")).unwrap();
    assert!(!hosts.contains("caramos-business"), "{hosts}");
    assert!(!system.path("/etc/NetworkManager/system-connections/caramos-business-congty.nmconnection").exists());
    for gone in [paths.config.clone(), paths.box_key.clone(), paths.state.join("policy.json"), paths.state.join("effective.json"),
                 paths.state.join("commands.json"), paths.state.join("approval.json"), paths.state.join("managed.json"), paths.state.join("tickets")] {
        assert!(!gone.exists(), "{}", gone.display());
    }
    let removed: Value = serde_json::from_slice(&fs::read(paths.state.join("removed.json")).unwrap()).unwrap();
    assert_eq!(removed, json!({"admin_name": "quan-ly", "time": "2026-11-23T10:00:00+07:00"}));
    assert_eq!(mode(&paths.state.join("removed.json")), 0o644);
    // Nothing reported after the notice.
    let check_ins = admin.requests("/checkin").len();
    assert_eq!(daemon.round_now().unwrap(), None, "not paired any more");
    assert_eq!(admin.requests("/checkin").len(), check_ins);
}

#[test]
fn commands_from_wait_and_their_results() {
    let dir = TempDir::new("commands");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let (worker, queued) = mpsc::channel();
    let mut daemon = Daemon::new(paths.clone(), system_root(&dir.0), worker);
    // The vectors' commands were issued in November 2026: on a machine booted later (a build machine) the message and
    // the lock would be from before its boot.
    daemon.assume_boot_time(None);
    daemon.round_now().unwrap();

    let envelopes: Vec<Envelope> = [
        "command-message.json",
        "command-department.json",
        "command-other-department.json",
        "command-all.json",
        "command-expired.json",
        "command-tampered.json",
        "command-bad-action.json",
        "command-bad-args.json",
    ]
    .iter()
    .map(|name| serde_json::from_value(v2(name)).unwrap())
    .collect();
    daemon.receive(envelopes);

    let run: Vec<(u64, Action)> = queued.try_iter().map(|command| (command.seq, command.action)).collect();
    assert_eq!(run.len(), 3);
    assert_eq!((run[0].0, run[1].0, run[2].0), (41, 42, 44));
    assert_eq!(run[1].1, Action::Lock);
    assert_eq!(run[2].1, Action::Sync);
    let results: Vec<(String, ResultState)> = daemon.unsent_results().into_iter().map(|result| (result.id, result.state)).collect();
    assert_eq!(
        results,
        [
            ("00000000-0000-4000-8000-000000000043".to_string(), ResultState::Ignored),
            ("00000000-0000-4000-8000-000000000045".to_string(), ResultState::Expired),
            ("00000000-0000-4000-8000-000000000046".to_string(), ResultState::Refused),
            ("00000000-0000-4000-8000-000000000047".to_string(), ResultState::Refused),
        ]
    );
    let record: Value = serde_json::from_slice(&fs::read(paths.state.join("commands.json")).unwrap()).unwrap();
    assert_eq!(record["last_seq"], 47);
    assert_eq!(record["done"].as_array().unwrap().len(), 7, "every command but the tampered one");

    // The same envelopes again: nothing more runs or reports.
    daemon.receive(vec![serde_json::from_value(v2("command-all.json")).unwrap()]);
    assert_eq!(queued.try_iter().count(), 0);

    daemon.send_results(true);
    assert!(daemon.unsent_results().is_empty());
    let sent = admin.requests("/result");
    assert_eq!(sent.len(), 4);
    assert!(sent.iter().all(|request| request.mac_ok == Some(true) && request.method == "POST"));
    let first: Value = serde_json::from_slice(&sent[0].body).unwrap();
    assert_eq!(first["state"], "ignored");
    assert!(first["time"].as_str().unwrap().ends_with("+07:00"));

    // The remote help command of 0.3: its sealed key opens for this machine.
    daemon.receive(vec![serde_json::from_value(v3("command-remote-help.json")).unwrap()]);
    let run: Vec<Action> = queued.try_iter().map(|command| command.action).collect();
    assert!(matches!(&run[..], [Action::RemoteHelp { mode: caramos_business_agent::commands::Mode::Control, .. }]), "{run:?}");
}

#[test]
fn the_long_poll_opens_once_a_round_loaded_the_pairing() {
    // The long-poll channel starts with the service, before the first round loads the pairing. 0.3.1 then looked
    // again only after 30 s: after each start of the service and each pairing, the admin's requests waited that long.
    let dir = TempDir::new("wait-starts");
    let admin = FakeAdmin::start();
    admin.answer("/policy", example("v2/signed-policy.json"));
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, _) = pair(&dir.0, &admin);
    let (worker, _queued) = mpsc::channel();
    let daemon = Arc::new(Daemon::new(paths, system_root(&dir.0), worker));
    let channel = Arc::clone(&daemon);
    thread::spawn(move || channel.wait_loop());
    thread::sleep(std::time::Duration::from_millis(1500));
    assert!(admin.requests("/wait").is_empty(), "no pairing loaded yet");
    daemon.round_now().unwrap();
    let opened = (0..30).any(|_| {
        thread::sleep(std::time::Duration::from_millis(100));
        !admin.requests("/wait").is_empty()
    });
    assert!(opened, "the long-poll opened within 3 s of the round that loaded the pairing");
}

#[test]
fn a_lower_serial_is_ignored_and_a_higher_one_stored() {
    let dir = TempDir::new("serial");
    let admin = FakeAdmin::start();
    admin.answer(&format!("/files/{SHA}"), example(&format!("file-{SHA}")));
    let (paths, config) = pair(&dir.0, &admin);
    let store = Store::new(&paths.state);
    let key = admin_key();
    let fetch = || daemon::update(&Admin::with_auth(&admin.url(), auth()), &config, &store);

    admin.signed_policy(&policy_with_serial(7, "seven"), &key);
    assert!(updated(fetch()).changed);

    admin.signed_policy(&policy_with_serial(6, "six"), &key);
    let refused = fetch().unwrap_err();
    assert!(matches!(refused, Failure::Refused(_)), "{refused}");
    assert!(!refused.admin_may_have_moved());
    assert_eq!(store.load().unwrap().1.serial, 7);

    // The same serial again is not lower.
    admin.signed_policy(&policy_with_serial(7, "seven again"), &key);
    assert!(updated(fetch()).changed);

    admin.signed_policy(&policy_with_serial(8, "eight"), &key);
    let eight = updated(fetch());
    assert_eq!((eight.serial, eight.changed), (8, true));
    assert!(store.load().unwrap().0.contains("\"eight\""));
}

#[test]
fn policies_that_must_not_be_stored() {
    let dir = TempDir::new("refused");
    let admin = FakeAdmin::start();
    let (paths, config) = pair(&dir.0, &admin);
    let store = Store::new(&paths.state);
    let fetch = || daemon::update(&Admin::with_auth(&admin.url(), auth()), &config, &store);

    // Nothing answers yet: the admin may have moved.
    let failure = fetch().unwrap_err();
    assert!(failure.admin_may_have_moved(), "{failure}");

    // Without the MAC, a 0.3 admin does not hand out the policy.
    admin.signed_policy(&policy_with_serial(9, "nine"), &admin_key());
    assert!(matches!(daemon::update(&Admin::new(&admin.url()), &config, &store).unwrap_err(), Failure::Fetch(_)));

    // Signed with another key.
    admin.signed_policy(&policy_with_serial(9, "impostor"), &SigningKey::from_bytes(&[9; 32]));
    let failure = fetch().unwrap_err();
    assert!(matches!(failure, Failure::BadSignature(_)), "{failure}");
    assert!(failure.admin_may_have_moved());

    // Signed with the right key, but format 1, or invalid.
    for name in ["invalid-format-1.json", "invalid-printer-uri.json"] {
        let invalid = String::from_utf8(example(&format!("v2/{name}"))).unwrap();
        admin.signed_policy(&invalid, &admin_key());
        assert!(matches!(fetch().unwrap_err(), Failure::Refused(_)), "{name}");
    }

    // Valid, but its file is not the one listed: same size, other bytes.
    admin.signed_policy(&policy_with_serial(12, "twelve"), &admin_key());
    admin.answer(&format!("/files/{SHA}"), "this is not the file it claims!".as_bytes().to_vec());
    assert!(matches!(fetch().unwrap_err(), Failure::File(..)));

    assert!(store.load().is_none());
    let files = paths.state.join("files");
    assert_eq!(fs::read_dir(&files).map(|entries| entries.count()).unwrap_or(0), 0, "no file, no partial download");
}
