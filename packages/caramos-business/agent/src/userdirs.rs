//! `~/.config/user-dirs.dirs`: where XDG_DESKTOP_DIR and XDG_DOCUMENTS_DIR point. The user's own values are kept in
//! `~/.config/caramos-business/user-dirs.local` before the first change, so that they can always come back.
//!
//! Lines are `XDG_DESKTOP_DIR="$HOME/Desktop"` or `XDG_DESKTOP_DIR="/absolute/path"`, as xdg-user-dirs writes them
//! and GLib reads them; the other lines of the file are kept as they are.
//!
//! The server's folders are reached through links, `~/.local/share/caramos-business/server/Desktop` and
//! `…/Documents`, to the share's folders in the GVfs FUSE mount, and user-dirs.dirs names the links. GIO takes any
//! path under the FUSE root back to its smb:// URI and lists it through GVfs's smb backend, where xfdesktop 4.18
//! fails ("Can't do asynchronous next_files() on a file enumerator created synchronously") and shows an empty
//! desktop. Through a link outside the FUSE root, GIO sees a local folder, which the kernel's FUSE mount serves.

use std::fs;
use std::io;
use std::os::unix::fs::{symlink, PermissionsExt};
use std::path::{Path, PathBuf};

use crate::store;

pub const DESKTOP: &str = "XDG_DESKTOP_DIR";
pub const DOCUMENTS: &str = "XDG_DOCUMENTS_DIR";
const DEFAULT_DESKTOP: &str = "$HOME/Desktop";
const DEFAULT_DOCUMENTS: &str = "$HOME/Documents";
/// The folder of the links to the server's Desktop and Documents, in the home folder.
pub const SERVER_LINKS: &str = ".local/share/caramos-business/server";

/// The value of `key` in a user-dirs.dirs text, as written between its quotes. The last line wins, as in GLib.
pub fn get(text: &str, key: &str) -> Option<String> {
    let mut found = None;
    for line in text.lines().filter(|line| is_line_of(line, key)) {
        let value = line.trim().split_once('=').map(|(_, value)| value).unwrap_or_default();
        if let Some(inner) = value.strip_prefix('"').and_then(|value| value.strip_suffix('"')) {
            found = Some(inner.to_string());
        }
    }
    found
}

/// `text` with `key` set to `value`: its line replaced (any further one dropped) or one added at the end.
pub fn set(text: &str, key: &str, value: &str) -> String {
    let mut out = String::with_capacity(text.len() + 80);
    let mut done = false;
    for line in text.lines() {
        if is_line_of(line, key) {
            if !done {
                out.push_str(&format!("{key}=\"{value}\"\n"));
                done = true;
            }
            continue;
        }
        out.push_str(line);
        out.push('\n');
    }
    if !done {
        out.push_str(&format!("{key}=\"{value}\"\n"));
    }
    out
}

fn is_line_of(line: &str, key: &str) -> bool {
    line.trim_start().strip_prefix(key).is_some_and(|rest| rest.starts_with('='))
}

/// The folder a value names: `$HOME/…` is in `home`, `/…` is absolute; anything else names none.
pub fn expand(value: &str, home: &Path) -> Option<PathBuf> {
    if let Some(rest) = value.strip_prefix("$HOME") {
        if !rest.is_empty() && !rest.starts_with('/') {
            return None;
        }
        let rest = rest.trim_start_matches('/');
        return Some(if rest.is_empty() { home.to_path_buf() } else { home.join(rest) });
    }
    value.starts_with('/').then(|| PathBuf::from(value))
}

/// A folder as user-dirs.dirs writes it: `$HOME/…` inside `home`, else absolute. None for a path that cannot be
/// written there: a quote, backslash, dollar sign, backquote or line break would need escaping, which GLib does not
/// undo.
pub fn encode(path: &Path, home: &Path) -> Option<String> {
    let text = path.to_str()?;
    if !path.is_absolute() || text.contains(['"', '\\', '$', '`', '\n', '\r']) {
        return None;
    }
    match path.strip_prefix(home) {
        Ok(rest) if !rest.as_os_str().is_empty() => Some(format!("$HOME/{}", rest.to_str()?)),
        _ => Some(text.to_string()),
    }
}

/// Whether `link` is a symlink to `target`: false when it is missing or points elsewhere, an error when a real file
/// or folder has its name (this part never replaces one).
fn is_link_to(link: &Path, target: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(link) {
        Ok(metadata) if metadata.file_type().is_symlink() => Ok(fs::read_link(link)? == target),
        Ok(_) => Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            format!("{} is a real file or folder, not a link; it is left as it is", link.display()),
        )),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

/// Makes `link` a symlink to `target`, atomically: a temporary link beside it, renamed into place. A link that
/// points at `target` already stays as it is; a real file or folder of that name is an error and stays too.
/// Whether the link changed.
fn point_link(link: &Path, target: &Path) -> io::Result<bool> {
    if is_link_to(link, target)? {
        return Ok(false);
    }
    let invalid = || io::Error::new(io::ErrorKind::InvalidInput, "the link has no folder or name");
    let dir = link.parent().ok_or_else(invalid)?;
    let name = link.file_name().ok_or_else(invalid)?;
    fs::create_dir_all(dir)?;
    let temp = dir.join(format!(".{}.{}.tmp", name.to_string_lossy(), std::process::id()));
    let _ = fs::remove_file(&temp);
    symlink(target, &temp)?;
    if let Err(error) = fs::rename(&temp, link) {
        let _ = fs::remove_file(&temp);
        return Err(error);
    }
    Ok(true)
}

/// One user's user-dirs.dirs, the backup of the user's own Desktop and Documents, and the links to the server's.
#[derive(Debug, Clone)]
pub struct UserDirs {
    home: PathBuf,
    file: PathBuf,
    backup: PathBuf,
}

impl UserDirs {
    pub fn new(home: &Path) -> UserDirs {
        UserDirs {
            home: home.to_path_buf(),
            file: home.join(".config/user-dirs.dirs"),
            backup: home.join(".config/caramos-business/user-dirs.local"),
        }
    }

    pub fn file(&self) -> &Path {
        &self.file
    }

    pub fn backup(&self) -> &Path {
        &self.backup
    }

    /// The text of user-dirs.dirs; empty when there is none yet.
    fn read(&self) -> io::Result<String> {
        match fs::read_to_string(&self.file) {
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(String::new()),
            other => other,
        }
    }

    /// The links to the server's Desktop and Documents: `~/.local/share/caramos-business/server/Desktop` and
    /// `…/Documents`.
    pub fn server_links(&self) -> (PathBuf, PathBuf) {
        let dir = self.home.join(SERVER_LINKS);
        (dir.join("Desktop"), dir.join("Documents"))
    }

    /// A value that names one of the user's own folders: not the server's (among the links to it, or in `gvfs`, the
    /// FUSE root, where an earlier version pointed straight), and not the home folder itself (where
    /// xdg-user-dirs-update points a folder it cannot find).
    fn own(&self, value: Option<String>, gvfs: &Path) -> Option<String> {
        let value = value?;
        let path = expand(&value, &self.home)?;
        let server = path.starts_with(gvfs) || path.starts_with(self.home.join(SERVER_LINKS));
        (path != self.home && !server).then_some(value)
    }

    /// The user's own Desktop and Documents values: from the backup, else from user-dirs.dirs while they are the
    /// user's own, else the defaults ~/Desktop and ~/Documents.
    pub fn local_values(&self, gvfs: &Path) -> (String, String) {
        let backup = fs::read_to_string(&self.backup).unwrap_or_default();
        let current = self.read().unwrap_or_default();
        let pick = |key: &str, default: &str| {
            self.own(get(&backup, key), gvfs)
                .or_else(|| self.own(get(&current, key), gvfs))
                .unwrap_or_else(|| default.to_string())
        };
        (pick(DESKTOP, DEFAULT_DESKTOP), pick(DOCUMENTS, DEFAULT_DOCUMENTS))
    }

    /// The user's own Desktop and Documents folders.
    pub fn local_dirs(&self, gvfs: &Path) -> (PathBuf, PathBuf) {
        let (desktop, documents) = self.local_values(gvfs);
        let expand_or = |value: &str, default: &str| {
            expand(value, &self.home).unwrap_or_else(|| self.home.join(default))
        };
        (expand_or(&desktop, "Desktop"), expand_or(&documents, "Documents"))
    }

    /// Keeps the user's own values in the backup, the first time only.
    pub fn backup_once(&self, gvfs: &Path) -> io::Result<()> {
        if fs::symlink_metadata(&self.backup).is_ok() {
            return Ok(());
        }
        let current = self.read()?;
        let desktop = self.own(get(&current, DESKTOP), gvfs).unwrap_or_else(|| DEFAULT_DESKTOP.to_string());
        let documents = self.own(get(&current, DOCUMENTS), gvfs).unwrap_or_else(|| DEFAULT_DOCUMENTS.to_string());
        let text = format!(
            "# Desktop and Documents before CaramOS Doanh nghiệp put them on the server; they come back from here.\n\
             {DESKTOP}=\"{desktop}\"\n{DOCUMENTS}=\"{documents}\"\n"
        );
        if let Some(dir) = self.backup.parent() {
            fs::create_dir_all(dir)?;
        }
        store::write_atomic(&self.backup, text.as_bytes(), 0o644)
    }

    /// Points Desktop and Documents at the server's `desktop` and `documents` (in the FUSE mount): the links first,
    /// then user-dirs.dirs, which names the links (`$HOME/.local/share/caramos-business/server/Desktop`). Both link
    /// names are checked before anything changes: a real file or folder in a link's place is an error, and then
    /// nothing changes. Whether anything changed.
    pub fn point_at_server(&self, desktop: &Path, documents: &Path) -> io::Result<bool> {
        let (desktop_link, documents_link) = self.server_links();
        is_link_to(&desktop_link, desktop)?;
        is_link_to(&documents_link, documents)?;
        let mut changed = point_link(&desktop_link, desktop)?;
        changed |= point_link(&documents_link, documents)?;
        changed |= self.point_at(&desktop_link, &documents_link)?;
        Ok(changed)
    }

    /// Whether Desktop and Documents are on the server's `desktop` and `documents` now ("applied"): user-dirs.dirs
    /// names the links, and the links point at these folders.
    pub fn points_at_server(&self, desktop: &Path, documents: &Path) -> bool {
        let (desktop_link, documents_link) = self.server_links();
        let text = self.read().unwrap_or_default();
        let names = |key: &str, link: &Path| {
            get(&text, key).and_then(|value| expand(&value, &self.home)).is_some_and(|path| path == link)
        };
        names(DESKTOP, &desktop_link)
            && names(DOCUMENTS, &documents_link)
            && is_link_to(&desktop_link, desktop).unwrap_or(false)
            && is_link_to(&documents_link, documents).unwrap_or(false)
    }

    /// Points Desktop and Documents at these folders in user-dirs.dirs. Whether it changed.
    fn point_at(&self, desktop: &Path, documents: &Path) -> io::Result<bool> {
        let unusable = || io::Error::new(io::ErrorKind::InvalidInput, "the folder's path cannot go into user-dirs.dirs");
        let desktop = encode(desktop, &self.home).ok_or_else(unusable)?;
        let documents = encode(documents, &self.home).ok_or_else(unusable)?;
        self.write_values(&desktop, &documents)
    }

    /// Puts the user's own values back where Desktop or Documents point at the server, or at the home folder (as
    /// xdg-user-dirs-update leaves a server folder it could not find at login). Other values are the user's and stay;
    /// a missing user-dirs.dirs stays missing. Whether user-dirs.dirs changed.
    pub fn restore(&self, gvfs: &Path) -> io::Result<bool> {
        let text = match fs::read_to_string(&self.file) {
            Ok(text) => text,
            Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(false),
            Err(error) => return Err(error),
        };
        let (desktop, documents) = self.local_values(gvfs);
        let mut changed = text.clone();
        for (key, own) in [(DESKTOP, desktop), (DOCUMENTS, documents)] {
            if get(&changed, key).is_some_and(|value| self.own(Some(value), gvfs).is_none()) {
                changed = set(&changed, key, &own);
            }
        }
        self.write_text(&text, &changed)
    }

    /// Whether `restore` has something to do: Desktop or Documents point at the server or at the home folder, after
    /// this part changed them (the backup exists).
    pub fn needs_restore(&self, gvfs: &Path) -> bool {
        if fs::symlink_metadata(&self.backup).is_err() {
            return false;
        }
        let current = self.read().unwrap_or_default();
        [DESKTOP, DOCUMENTS].iter().any(|key| get(&current, key).is_some_and(|value| self.own(Some(value), gvfs).is_none()))
    }

    fn write_values(&self, desktop: &str, documents: &str) -> io::Result<bool> {
        let text = self.read()?;
        let changed = set(&set(&text, DESKTOP, desktop), DOCUMENTS, documents);
        self.write_text(&text, &changed)
    }

    /// Writes `changed` over `text` (what the file holds now) when they differ, keeping the file's mode.
    fn write_text(&self, text: &str, changed: &str) -> io::Result<bool> {
        if changed == text {
            return Ok(false);
        }
        let mode = fs::metadata(&self.file).map(|metadata| metadata.permissions().mode() & 0o777).unwrap_or(0o644);
        if let Some(dir) = self.file.parent() {
            fs::create_dir_all(dir)?;
        }
        store::write_atomic(&self.file, changed.as_bytes(), mode)?;
        Ok(true)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;

    const SAMPLE: &str = "# This file is written by xdg-user-dirs-update\n\
                          XDG_DESKTOP_DIR=\"$HOME/Desktop\"\n\
                          XDG_DOWNLOAD_DIR=\"$HOME/Downloads\"\n\
                          XDG_DOCUMENTS_DIR=\"$HOME/Tài liệu\"\n\
                          XDG_MUSIC_DIR=\"/data/Music\"\n";

    #[test]
    fn values_are_read_and_replaced() {
        assert_eq!(get(SAMPLE, DESKTOP).as_deref(), Some("$HOME/Desktop"));
        assert_eq!(get(SAMPLE, DOCUMENTS).as_deref(), Some("$HOME/Tài liệu"));
        assert_eq!(get(SAMPLE, "XDG_PICTURES_DIR"), None);
        assert_eq!(get("# XDG_DESKTOP_DIR=\"/x\"\n", DESKTOP), None);

        let changed = set(SAMPLE, DESKTOP, "/run/user/1000/gvfs/x/Desktop");
        assert_eq!(get(&changed, DESKTOP).as_deref(), Some("/run/user/1000/gvfs/x/Desktop"));
        assert_eq!(changed.lines().count(), SAMPLE.lines().count());
        assert!(changed.contains("XDG_MUSIC_DIR=\"/data/Music\"\n"));
        assert!(changed.starts_with("# This file is written by xdg-user-dirs-update\n"));
        let added = set("XDG_MUSIC_DIR=\"$HOME/Music\"\n", DOCUMENTS, "$HOME/Documents");
        assert_eq!(added, "XDG_MUSIC_DIR=\"$HOME/Music\"\nXDG_DOCUMENTS_DIR=\"$HOME/Documents\"\n");
    }

    #[test]
    fn paths_and_values() {
        let home = Path::new("/home/lan");
        assert_eq!(expand("$HOME/Desktop", home), Some(PathBuf::from("/home/lan/Desktop")));
        assert_eq!(expand("$HOME/", home), Some(PathBuf::from("/home/lan")));
        assert_eq!(expand("/srv/x", home), Some(PathBuf::from("/srv/x")));
        assert_eq!(expand("$HOMEX/a", home), None);
        assert_eq!(expand("relative", home), None);
        assert_eq!(encode(Path::new("/home/lan/Desktop"), home).as_deref(), Some("$HOME/Desktop"));
        let server = Path::new("/run/user/1000/gvfs/smb-share:server=nas,share=nhanvien/lan/Desktop");
        assert_eq!(encode(server, home).as_deref(), server.to_str());
        assert_eq!(encode(Path::new("/run/user/1000/gvfs/smb-share:server=nas,share=c$/x"), home), None);
        assert_eq!(encode(Path::new("/tmp/a\"b"), home), None);
    }

    #[test]
    fn rewrite_with_one_backup_and_restore() {
        let home = TempDir::new("userdirs");
        let gvfs = Path::new("/run/user/1000/gvfs");
        let dirs = UserDirs::new(home.path());
        fs::create_dir_all(home.path().join(".config")).unwrap();
        fs::write(dirs.file(), SAMPLE).unwrap();

        dirs.backup_once(gvfs).unwrap();
        let backup = fs::read_to_string(dirs.backup()).unwrap();
        assert_eq!(get(&backup, DESKTOP).as_deref(), Some("$HOME/Desktop"));
        assert_eq!(get(&backup, DOCUMENTS).as_deref(), Some("$HOME/Tài liệu"));

        let desktop = gvfs.join("smb-share:server=nas,share=nhanvien/lan/Desktop");
        let documents = gvfs.join("smb-share:server=nas,share=nhanvien/lan/Documents");
        assert!(!dirs.points_at_server(&desktop, &documents));
        assert!(dirs.point_at_server(&desktop, &documents).unwrap());
        // Applied: user-dirs.dirs names the links, the links name the FUSE folders; a second time changes nothing.
        assert!(dirs.points_at_server(&desktop, &documents));
        assert!(!dirs.point_at_server(&desktop, &documents).unwrap());
        let text = fs::read_to_string(dirs.file()).unwrap();
        assert_eq!(get(&text, DESKTOP).as_deref(), Some("$HOME/.local/share/caramos-business/server/Desktop"));
        assert_eq!(get(&text, DOCUMENTS).as_deref(), Some("$HOME/.local/share/caramos-business/server/Documents"));
        assert_eq!(get(&text, "XDG_DOWNLOAD_DIR").as_deref(), Some("$HOME/Downloads"));
        let links = home.path().join(".local/share/caramos-business/server");
        assert_eq!(fs::read_link(links.join("Desktop")).unwrap(), desktop);
        assert_eq!(fs::read_link(links.join("Documents")).unwrap(), documents);
        assert!(dirs.needs_restore(gvfs));

        // A second backup keeps the first values, even though user-dirs.dirs points at the server now.
        dirs.backup_once(gvfs).unwrap();
        assert_eq!(fs::read_to_string(dirs.backup()).unwrap(), backup);

        // The share cannot be reached: the user's own values come back; the links stay, dangling.
        assert!(dirs.restore(gvfs).unwrap());
        assert_eq!(fs::read_to_string(dirs.file()).unwrap(), SAMPLE);
        assert!(!dirs.needs_restore(gvfs));
        assert!(!dirs.points_at_server(&desktop, &documents));
        assert!(fs::symlink_metadata(links.join("Desktop")).unwrap().file_type().is_symlink());
        assert_eq!(
            dirs.local_dirs(gvfs),
            (home.path().join("Desktop"), home.path().join("Tài liệu"))
        );
    }

    #[test]
    fn links_are_replaced_atomically_when_the_mount_changes() {
        let home = TempDir::new("userdirs-links");
        let dirs = UserDirs::new(home.path());
        let old = PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas,share=old/lan/Desktop");
        let new = PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas,share=new/lan/Desktop");
        let documents = PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas,share=new/lan/Documents");
        // No user-dirs.dirs yet: it is made.
        assert!(dirs.point_at_server(&old, &documents).unwrap());
        let before = fs::read_to_string(dirs.file()).unwrap();

        // Another share: the link follows it, user-dirs.dirs (naming the links) stays as it is.
        assert!(!dirs.points_at_server(&new, &documents));
        assert!(dirs.point_at_server(&new, &documents).unwrap());
        assert_eq!(fs::read_link(dirs.server_links().0).unwrap(), new);
        assert_eq!(fs::read_to_string(dirs.file()).unwrap(), before);
        assert!(dirs.points_at_server(&new, &documents));

        // No temporary link is left beside them.
        let mut names: Vec<String> = fs::read_dir(home.path().join(SERVER_LINKS))
            .unwrap()
            .map(|entry| entry.unwrap().file_name().into_string().unwrap())
            .collect();
        names.sort();
        assert_eq!(names, ["Desktop", "Documents"]);
    }

    #[test]
    fn a_real_folder_or_file_is_never_replaced_by_a_link() {
        let home = TempDir::new("userdirs-real");
        let dirs = UserDirs::new(home.path());
        fs::create_dir_all(home.path().join(".config")).unwrap();
        fs::write(dirs.file(), SAMPLE).unwrap();
        let desktop = PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas,share=s/lan/Desktop");
        let documents = PathBuf::from("/run/user/1000/gvfs/smb-share:server=nas,share=s/lan/Documents");
        let (desktop_link, documents_link) = dirs.server_links();

        // A real folder, with a file in it, where the Desktop link goes: refused, and nothing changes.
        fs::create_dir_all(&desktop_link).unwrap();
        fs::write(desktop_link.join("keep.txt"), "mine").unwrap();
        let error = dirs.point_at_server(&desktop, &documents).unwrap_err();
        assert!(error.to_string().contains("not a link"), "{error}");
        assert_eq!(fs::read_to_string(desktop_link.join("keep.txt")).unwrap(), "mine");
        assert!(fs::symlink_metadata(&documents_link).is_err());
        assert_eq!(fs::read_to_string(dirs.file()).unwrap(), SAMPLE);

        // A real file where the Documents link goes: the same.
        fs::remove_dir_all(&desktop_link).unwrap();
        fs::write(&documents_link, "a file").unwrap();
        assert!(dirs.point_at_server(&desktop, &documents).is_err());
        assert_eq!(fs::read_to_string(&documents_link).unwrap(), "a file");
        assert!(fs::symlink_metadata(&desktop_link).is_err());
        assert_eq!(fs::read_to_string(dirs.file()).unwrap(), SAMPLE);
        assert!(!dirs.points_at_server(&desktop, &documents));
    }

    #[test]
    fn values_pointing_at_the_server_or_home_are_not_the_users_own() {
        let home = TempDir::new("userdirs-reset");
        let gvfs = Path::new("/run/user/1000/gvfs");
        let dirs = UserDirs::new(home.path());
        fs::create_dir_all(home.path().join(".config")).unwrap();
        // As left by a session that ended on the server, then by xdg-user-dirs-update, which points a folder it
        // cannot find at the home folder.
        fs::write(
            dirs.file(),
            "XDG_DESKTOP_DIR=\"/run/user/1000/gvfs/smb-share:server=nas,share=s/Desktop\"\nXDG_DOCUMENTS_DIR=\"$HOME/\"\n",
        )
        .unwrap();
        dirs.backup_once(gvfs).unwrap();
        let backup = fs::read_to_string(dirs.backup()).unwrap();
        assert_eq!(get(&backup, DESKTOP).as_deref(), Some("$HOME/Desktop"));
        assert_eq!(get(&backup, DOCUMENTS).as_deref(), Some("$HOME/Documents"));

        // The links to the server are the server's too.
        fs::remove_file(dirs.backup()).unwrap();
        fs::write(
            dirs.file(),
            "XDG_DESKTOP_DIR=\"$HOME/.local/share/caramos-business/server/Desktop\"\nXDG_DOCUMENTS_DIR=\"$HOME/Docs\"\n",
        )
        .unwrap();
        dirs.backup_once(gvfs).unwrap();
        let backup = fs::read_to_string(dirs.backup()).unwrap();
        assert_eq!(get(&backup, DESKTOP).as_deref(), Some("$HOME/Desktop"));
        assert_eq!(get(&backup, DOCUMENTS).as_deref(), Some("$HOME/Docs"));
    }

    #[test]
    fn restore_touches_only_what_points_at_the_server_or_home() {
        let home = TempDir::new("userdirs-restore");
        let gvfs = Path::new("/run/user/1000/gvfs");
        let dirs = UserDirs::new(home.path());

        // No user-dirs.dirs: nothing to restore, and none is made.
        assert!(!dirs.restore(gvfs).unwrap());
        assert!(!dirs.file().exists());

        fs::create_dir_all(home.path().join(".config")).unwrap();
        fs::write(dirs.file(), "XDG_DESKTOP_DIR=\"$HOME/Màn hình\"\nXDG_DOCUMENTS_DIR=\"$HOME/Tài liệu\"\n").unwrap();
        // Nothing changed by this part yet: nothing to restore.
        assert!(!dirs.needs_restore(gvfs));
        dirs.backup_once(gvfs).unwrap();

        // xdg-user-dirs-update reset Desktop to the home folder; the user moved Documents elsewhere themselves.
        fs::write(dirs.file(), "XDG_DESKTOP_DIR=\"$HOME/\"\nXDG_DOCUMENTS_DIR=\"/data/Docs\"\n").unwrap();
        assert!(dirs.needs_restore(gvfs));
        assert!(dirs.restore(gvfs).unwrap());
        assert_eq!(
            fs::read_to_string(dirs.file()).unwrap(),
            "XDG_DESKTOP_DIR=\"$HOME/Màn hình\"\nXDG_DOCUMENTS_DIR=\"/data/Docs\"\n"
        );
        assert!(!dirs.needs_restore(gvfs));
        assert!(!dirs.restore(gvfs).unwrap());
    }
}
