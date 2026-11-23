//! What the agent keeps on disk: agent.json and the machine box key (written by the root helper at pairing), the
//! last good policy, its files and this machine's effective settings, and the atomic write that every file of the
//! agent goes through, so that no reader sees half a file.

use std::fs::{self, File, OpenOptions, Permissions};
use std::io::{self, Read, Write};
use std::net::Ipv4Addr;
use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::crypto;
use crate::policy::{self, FileEntry, Policy};

/// agent.json is small; anything bigger is not one.
const MAX_CONFIG: u64 = 64 * 1024;

/// Writes `data` to `path` atomically with `mode`: a temporary file in the same folder, fsync, then rename.
pub fn write_atomic(path: &Path, data: &[u8], mode: u32) -> io::Result<()> {
    write_atomic_owned(path, data, mode, None)
}

/// The same, with the temporary file given to `owner` (uid, gid) before it is renamed into place, so that the file
/// never appears with another owner. Only root can give files away: for anyone else `owner` is left out (tests).
pub fn write_atomic_owned(path: &Path, data: &[u8], mode: u32, owner: Option<(u32, u32)>) -> io::Result<()> {
    let dir = match path.parent() {
        Some(dir) if !dir.as_os_str().is_empty() => dir,
        _ => Path::new("."),
    };
    let name = path
        .file_name()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "the path has no file name"))?;
    let temp = dir.join(format!(".{}.{}.tmp", name.to_string_lossy(), std::process::id()));
    let _ = fs::remove_file(&temp);
    let owned = |()| match owner {
        Some((uid, gid)) if crate::process::uid() == Some(0) => std::os::unix::fs::chown(&temp, Some(uid), Some(gid)),
        _ => Ok(()),
    };
    match write_new(&temp, data, mode).and_then(owned).and_then(|()| fs::rename(&temp, path)) {
        Ok(()) => {
            if let Ok(dir) = File::open(dir) {
                let _ = dir.sync_all();
            }
            Ok(())
        }
        Err(error) => {
            let _ = fs::remove_file(&temp);
            Err(error)
        }
    }
}

fn write_new(path: &Path, data: &[u8], mode: u32) -> io::Result<()> {
    let mut file = OpenOptions::new().write(true).create_new(true).mode(mode).open(path)?;
    file.write_all(data)?;
    // The umask may have taken bits off the mode that open() used.
    file.set_permissions(Permissions::from_mode(mode))?;
    file.sync_all()
}

/// Reads a file of at most `max` bytes; a bigger one is an error, never a cut copy.
pub fn read_limited(path: &Path, max: u64) -> io::Result<Vec<u8>> {
    let mut data = Vec::new();
    File::open(path)?.take(max + 1).read_to_end(&mut data)?;
    if data.len() as u64 > max {
        return Err(io::Error::new(io::ErrorKind::InvalidData, format!("it is larger than {max} bytes")));
    }
    Ok(data)
}

/// /etc/caramos-business/agent.json: the pairing, as the root helper wrote it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AgentConfig {
    /// http://IP:PORT, where the admin answered last.
    pub admin_url: String,
    pub admin_ip: Ipv4Addr,
    pub admin_port: u16,
    pub admin_name: String,
    /// The admin key pinned at pairing: every policy must be signed with it.
    pub admin_key: [u8; 32],
    /// First 16 hex digits of sha256(admin key): how discovery finds the admin again.
    pub fingerprint: String,
    pub machine_id: String,
    /// `/etc/machine-id` when the helper paired this machine: another value now means a cloned disk.
    pub machine_id_os: Option<String>,
    /// The admin's X25519 public key as the pairing learnt it (from 0.3; PROTOCOL.md part 3, "Changes during
    /// implementation"): the machine signs its first `GET /policy` with it. Once a verified policy is stored, the
    /// policy's `admin_box_key` is used, as in part 2.
    pub admin_box_key: Option<[u8; 32]>,
}

impl AgentConfig {
    /// The pairing in `path`; Ok(None) when there is none (the machine is not paired yet).
    pub fn load(path: &Path) -> Result<Option<AgentConfig>, String> {
        let data = match read_limited(path, MAX_CONFIG) {
            Ok(data) => data,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(format!("cannot read {}: {error}", path.display())),
        };
        let text = String::from_utf8(data).map_err(|_| format!("{} is not UTF-8", path.display()))?;
        AgentConfig::parse(&text).map(Some).map_err(|error| format!("{}: {error}", path.display()))
    }

    /// Parses and checks agent.json's text.
    pub fn parse(text: &str) -> Result<AgentConfig, String> {
        #[derive(Deserialize)]
        struct Fields {
            admin_url: String,
            #[serde(default)]
            admin_name: String,
            admin_key: String,
            #[serde(default)]
            fingerprint: String,
            machine_id: String,
            #[serde(default)]
            machine_id_os: Option<String>,
            #[serde(default)]
            admin_box_key: Option<String>,
        }

        let fields: Fields = serde_json::from_str(text).map_err(|error| format!("not a valid agent.json: {error}"))?;
        let (admin_ip, admin_port) = parse_admin_url(&fields.admin_url)
            .ok_or_else(|| format!("admin_url {:?} is not http://IP:PORT", fields.admin_url))?;
        let admin_key = crypto::decode_key(&fields.admin_key)?;
        let fingerprint = crypto::fingerprint(&admin_key);
        if !fields.fingerprint.is_empty() && fields.fingerprint != fingerprint {
            return Err("its fingerprint does not match its admin_key".to_string());
        }
        if !policy::is_machine_id(&fields.machine_id) {
            return Err("its machine_id is not a UUID".to_string());
        }
        if fields.machine_id_os.as_deref().is_some_and(|value| !is_os_machine_id(value)) {
            return Err("its machine_id_os is not a machine id".to_string());
        }
        let admin_box_key = match fields.admin_box_key.as_deref() {
            Some(text) => Some(crypto::decode_key32(text, "its admin_box_key")?),
            None => None,
        };
        Ok(AgentConfig {
            admin_url: admin_url(admin_ip, admin_port),
            admin_ip,
            admin_port,
            admin_name: fields.admin_name,
            admin_key,
            fingerprint,
            machine_id: fields.machine_id,
            machine_id_os: fields.machine_id_os,
            admin_box_key,
        })
    }
}

/// The path of the operating system's machine id.
pub const OS_MACHINE_ID: &str = "/etc/machine-id";

/// Whether a text is a machine id as in `/etc/machine-id`: 32 lower-case hex digits.
pub fn is_os_machine_id(value: &str) -> bool {
    value.len() == 32 && value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// The operating system's machine id in `path` (`/etc/machine-id`), when it is one.
pub fn read_os_machine_id(path: &Path) -> Option<String> {
    let data = read_limited(path, 128).ok()?;
    let value = String::from_utf8(data).ok()?.trim().to_string();
    is_os_machine_id(&value).then_some(value)
}

/// What the saved pairing says about this machine: None when it is the machine that was paired (or when that
/// cannot be told: no `machine_id_os` in agent.json, no readable `/etc/machine-id`), else the clone's two ids.
pub fn cloned(config: &AgentConfig, os_machine_id: &Path) -> Option<(String, String)> {
    let paired_on = config.machine_id_os.as_deref()?;
    let here = read_os_machine_id(os_machine_id)?;
    (here != paired_on).then(|| (paired_on.to_string(), here))
}

/// The machine box key: X25519, the raw 32 bytes of the private key in `/etc/caramos-business/agent-box.key` (0600
/// root), made by the helper at pairing. Ok(None) when there is none.
pub fn load_box_key(path: &Path) -> Result<Option<[u8; 32]>, String> {
    match read_limited(path, 64) {
        Ok(data) => <[u8; 32]>::try_from(data.as_slice())
            .map(Some)
            .map_err(|_| format!("{} does not hold a 32-byte key", path.display())),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("cannot read {}: {error}", path.display())),
    }
}

/// `/var/lib/caramos-business/agent/effective.json`: this machine's effective settings, which the daemon writes for
/// the session parts (they cannot read agent.json, so they cannot pick their machine's layers out of the policy).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct EffectiveFile {
    pub serial: u64,
    pub machine_id: String,
    #[serde(default)]
    pub department: Option<String>,
    #[serde(default)]
    pub admin_name: String,
    /// The listed files, for the wallpaper's paths.
    #[serde(default)]
    pub files: Map<String, Value>,
    pub settings: Map<String, Value>,
}

/// "http://IP:PORT", the only form the helper and discovery write (a trailing slash is allowed).
pub fn parse_admin_url(url: &str) -> Option<(Ipv4Addr, u16)> {
    let rest = url.strip_prefix("http://")?;
    let rest = rest.strip_suffix('/').unwrap_or(rest);
    let (host, port) = rest.split_once(':')?;
    let ip: Ipv4Addr = host.parse().ok()?;
    if ip.is_unspecified() || ip.is_broadcast() || ip.is_multicast() {
        return None;
    }
    if port.is_empty() || port.len() > 5 || !port.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    let port: u16 = port.parse().ok().filter(|port| *port > 0)?;
    Some((ip, port))
}

pub fn admin_url(ip: Ipv4Addr, port: u16) -> String {
    format!("http://{ip}:{port}")
}

/// Writes `url` as agent.json's admin_url, keeping its other fields as they are and its mode, 0600.
pub fn save_admin_url(path: &Path, url: &str) -> Result<(), String> {
    let data = read_limited(path, MAX_CONFIG).map_err(|error| format!("cannot read {}: {error}", path.display()))?;
    let mut value: serde_json::Value =
        serde_json::from_slice(&data).map_err(|error| format!("{} is not JSON: {error}", path.display()))?;
    let object = value.as_object_mut().ok_or_else(|| format!("{} is not a JSON object", path.display()))?;
    object.insert("admin_url".to_string(), serde_json::Value::String(url.to_string()));
    let mut text = serde_json::to_string_pretty(&value).map_err(|error| error.to_string())?;
    text.push('\n');
    write_atomic(path, text.as_bytes(), 0o600).map_err(|error| format!("cannot write {}: {error}", path.display()))
}

/// /var/lib/caramos-business/agent: the last policy that passed the checks, and its files.
#[derive(Debug, Clone)]
pub struct Store {
    dir: PathBuf,
}

impl Store {
    pub fn new(dir: impl Into<PathBuf>) -> Store {
        Store { dir: dir.into() }
    }

    pub fn policy_path(&self) -> PathBuf {
        self.dir.join("policy.json")
    }

    pub fn files_dir(&self) -> PathBuf {
        self.dir.join("files")
    }

    pub fn effective_path(&self) -> PathBuf {
        self.dir.join("effective.json")
    }

    /// What the daemon changed on the system, to put it back (PROTOCOL.md part 2 "Files").
    pub fn managed_path(&self) -> PathBuf {
        self.dir.join("managed.json")
    }

    /// The last command seq and the ids run (PROTOCOL.md part 2 "Signed commands").
    pub fn commands_path(&self) -> PathBuf {
        self.dir.join("commands.json")
    }

    /// Present while the daemon found this disk to be a clone of the paired machine (PROTOCOL.md part 2 "Cloned
    /// disks"): the session parts and the window read it; nothing is applied or reported meanwhile.
    pub fn clone_path(&self) -> PathBuf {
        self.dir.join("clone.json")
    }

    /// `{"state": "pending" or "approved", "since"}` (0644, PROTOCOL.md part 3 "Approval"), for the window.
    pub fn approval_path(&self) -> PathBuf {
        self.dir.join("approval.json")
    }

    /// `{"admin_name", "time"}` (0644) after the company removed the machine, for the window.
    pub fn removed_path(&self) -> PathBuf {
        self.dir.join("removed.json")
    }

    /// `{"last", "finished", "result"}` (0644): the last maintenance boot of a frozen machine.
    pub fn maintenance_path(&self) -> PathBuf {
        self.dir.join("maintenance.json")
    }

    /// `{"reason", "admin_name", "time"}`: a frozen machine left or was removed; the next unfrozen boot finishes.
    pub fn leave_pending_path(&self) -> PathBuf {
        self.dir.join("leave-pending.json")
    }

    /// The users' tickets, `<uid>.json`, and `version` (PROTOCOL.md part 3 "Helpdesk tickets").
    pub fn tickets_dir(&self) -> PathBuf {
        self.dir.join("tickets")
    }

    /// Writes approval.json when the state changed (the time is kept while the state stays). Whether it wrote.
    pub fn mark_approval(&self, state: &str, since: &str) -> io::Result<bool> {
        let current = read_limited(&self.approval_path(), 4096).ok().and_then(|data| serde_json::from_slice::<Value>(&data).ok());
        if current.as_ref().and_then(|value| value["state"].as_str()) == Some(state) {
            return Ok(false);
        }
        self.create_dirs()?;
        let data = serde_json::json!({"state": state, "since": since}).to_string();
        write_atomic(&self.approval_path(), format!("{data}\n").as_bytes(), 0o644)?;
        Ok(true)
    }

    /// The pairing's files in the state folder, for a machine that left or was removed: the stored policy and what
    /// follows from it, the command record, the approval, the clone mark, the tickets and the public admin.json.
    /// managed.json goes separately, once everything is back.
    pub fn remove_pairing_state(&self) {
        for name in ["policy.json", "effective.json", "commands.json", "approval.json", "clone.json", "admin.json", "maintenance.json"] {
            let _ = fs::remove_file(self.dir.join(name));
        }
        let _ = fs::remove_dir_all(self.tickets_dir());
    }

    /// Marks the disk as a clone: `{"paired_on", "this_machine"}` (the two `/etc/machine-id` values), 0644.
    pub fn mark_clone(&self, paired_on: &str, this_machine: &str) -> io::Result<()> {
        if self.clone_path().exists() {
            return Ok(());
        }
        self.create_dirs()?;
        let data = serde_json::json!({"paired_on": paired_on, "this_machine": this_machine}).to_string();
        write_atomic(&self.clone_path(), format!("{data}\n").as_bytes(), 0o644)
    }

    pub fn unmark_clone(&self) {
        let _ = fs::remove_file(self.clone_path());
    }

    pub fn is_clone(&self) -> bool {
        self.clone_path().exists()
    }

    /// This machine's effective settings as the daemon wrote them last; None without a policy.
    pub fn load_effective(&self) -> Option<EffectiveFile> {
        let data = read_limited(&self.effective_path(), policy::MAX_TEXT as u64).ok()?;
        serde_json::from_slice(&data).ok()
    }

    /// Writes this machine's effective settings, readable by all (they hold no secrets).
    pub fn save_effective(&self, effective: &EffectiveFile) -> io::Result<()> {
        self.create_dirs()?;
        let mut data = serde_json::to_vec_pretty(effective).map_err(io::Error::other)?;
        data.push(b'\n');
        if fs::read(self.effective_path()).is_ok_and(|old| old == data) {
            return Ok(());
        }
        write_atomic(&self.effective_path(), &data, 0o644)
    }

    /// files/<sha256>.<type>: both parts were checked with the policy, so the name is always plain.
    pub fn file_path(&self, sha: &str, file: &FileEntry) -> PathBuf {
        self.files_dir().join(format!("{sha}.{}", file.kind))
    }

    /// The stored policy, as its text and parsed. None when there is none, or when it no longer passes the checks.
    pub fn load(&self) -> Option<(String, Policy)> {
        let data = read_limited(&self.policy_path(), policy::MAX_TEXT as u64).ok()?;
        let text = String::from_utf8(data).ok()?;
        let policy = policy::parse(&text).ok()?;
        Some((text, policy))
    }

    /// Stores the text of a policy that passed the checks, readable by all (0644).
    pub fn save(&self, text: &str) -> io::Result<()> {
        self.create_dirs()?;
        write_atomic(&self.policy_path(), text.as_bytes(), 0o644)
    }

    /// Whether a listed file is in place with its size. The download checked its sha256 before renaming it into
    /// place, and only root writes here.
    pub fn has_file(&self, sha: &str, file: &FileEntry) -> bool {
        fs::symlink_metadata(self.file_path(sha, file))
            .is_ok_and(|metadata| metadata.is_file() && metadata.len() == file.size)
    }

    /// The folders, 0755: the session part of every user reads them.
    pub fn create_dirs(&self) -> io::Result<()> {
        let files = self.files_dir();
        fs::create_dir_all(&files)?;
        fs::set_permissions(&self.dir, Permissions::from_mode(0o755))?;
        fs::set_permissions(&files, Permissions::from_mode(0o755))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    const KEY: &str = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=";

    fn config_json(url: &str, fingerprint: &str) -> String {
        format!(
            r#"{{"admin_url": "{url}", "admin_name": "may-quan-ly", "admin_key": "{KEY}", "fingerprint": "{fingerprint}",
                "machine_id": "0f8fad5b-d9cb-469f-a165-70867728950e", "paired": "kept"}}"#
        )
    }

    #[test]
    fn admin_urls() {
        assert_eq!(parse_admin_url("http://192.168.1.10:47022"), Some(([192, 168, 1, 10].into(), 47022)));
        assert_eq!(parse_admin_url("http://192.168.1.10:47022/"), Some(([192, 168, 1, 10].into(), 47022)));
        for bad in [
            "https://192.168.1.10:47022",
            "http://192.168.1.10",
            "http://may-quan-ly:47022",
            "http://192.168.1.10:0",
            "http://192.168.1.10:+80",
            "http://192.168.1.10:47022/x",
            "http://0.0.0.0:47022",
            "http://255.255.255.255:47022",
        ] {
            assert_eq!(parse_admin_url(bad), None, "{bad}");
        }
    }

    #[test]
    fn agent_json() {
        let config = AgentConfig::parse(&config_json("http://192.168.1.10:47022", "56475aa75463474c")).unwrap();
        assert_eq!(config.fingerprint, "56475aa75463474c");
        assert_eq!(config.admin_port, 47022);
        assert!(AgentConfig::parse(&config_json("http://192.168.1.10:47022", "0000000000000000")).is_err());
        assert!(AgentConfig::parse(&config_json("ftp://x", "")).is_err());
    }

    #[test]
    fn admin_url_update_keeps_the_rest() {
        let dir = std::env::temp_dir().join(format!("caramos-business-store-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("agent.json");
        write_atomic(&path, config_json("http://192.168.1.10:47022", "").as_bytes(), 0o600).unwrap();
        save_admin_url(&path, "http://192.168.1.77:47022").unwrap();
        let config = AgentConfig::load(&path).unwrap().unwrap();
        assert_eq!(config.admin_url, "http://192.168.1.77:47022");
        assert_eq!(config.machine_id, "0f8fad5b-d9cb-469f-a165-70867728950e");
        let value: serde_json::Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        assert_eq!(value["paired"], "kept");
        assert_eq!(fs::metadata(&path).unwrap().permissions().mode() & 0o777, 0o600);
        assert_eq!(AgentConfig::load(&dir.join("missing.json")), Ok(None));
    }

    #[test]
    fn a_cloned_disk_is_noticed() {
        let root = TempDir::new("clone");
        let dir = root.path();
        let machine_id = dir.join("machine-id");
        let config_with = |os: Option<&str>| {
            let mut value: serde_json::Value = serde_json::from_str(&config_json("http://192.168.1.10:47022", "56475aa75463474c")).unwrap();
            if let Some(os) = os {
                value["machine_id_os"] = os.into();
            }
            AgentConfig::parse(&value.to_string())
        };
        let paired = config_with(Some("0123456789abcdef0123456789abcdef")).unwrap();
        fs::write(&machine_id, "0123456789abcdef0123456789abcdef\n").unwrap();
        assert_eq!(cloned(&paired, &machine_id), None, "the machine that was paired");
        fs::write(&machine_id, "fedcba9876543210fedcba9876543210\n").unwrap();
        assert_eq!(cloned(&paired, &machine_id), Some(("0123456789abcdef0123456789abcdef".into(), "fedcba9876543210fedcba9876543210".into())));
        assert_eq!(cloned(&config_with(None).unwrap(), &machine_id), None, "paired before machine_id_os was kept");
        assert_eq!(cloned(&paired, &dir.join("missing")), None);
        assert!(config_with(Some("not-a-machine-id")).is_err());
        let store = Store::new(dir.join("state"));
        assert!(!store.is_clone());
        store.mark_clone("0123456789abcdef0123456789abcdef", "fedcba9876543210fedcba9876543210").unwrap();
        assert!(store.is_clone());
        store.unmark_clone();
        assert!(!store.is_clone());
        fs::remove_dir_all(dir).unwrap();
    }
}
