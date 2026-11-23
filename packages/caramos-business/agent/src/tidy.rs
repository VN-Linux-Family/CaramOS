//! `tidy` (PROTOCOL.md "Folders", step 5): what is left in the user's own Desktop and Documents moves to
//! `Chưa sắp xếp/YYYY-MM-DD` in the user's folder on the share.
//!
//! This is the user's data. A file leaves this machine only after its copy on the server is complete: it is copied
//! under a temporary name, the sizes are compared, the copy is renamed into place, and only then is the local file
//! removed. Whatever fails stays where it was. Nothing is ever overwritten: a name that is taken gets " (2)".
//!
//! What does not move:
//! - launchers (`*.desktop`): those on the local Desktop are copied to the server's Desktop instead, so that the
//!   desktop icons stay on both sides; launchers elsewhere stay where they are;
//! - hidden entries at the top of Desktop and Documents (folder settings such as `.directory`, lock files);
//! - symlinks, pipes, sockets and devices.

use std::ffi::OsStr;
use std::fs::{self, File, OpenOptions};
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::path::{Component, Path, PathBuf};

/// The folder on the share that receives what was left on the machine ("Unsorted").
pub const UNSORTED: &str = "Chưa sắp xếp";
/// At most this many errors are kept for the log.
const MAX_ERRORS: usize = 5;

/// What a tidy did.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct Report {
    pub moved: usize,
    /// Launchers copied to the server's Desktop.
    pub copied: usize,
    pub failed: usize,
    /// Every launcher of the local Desktop is on the server's Desktop now (copied, or one of its name was there).
    pub launchers_done: bool,
    /// The first errors, for the log.
    pub errors: Vec<String>,
}

impl Report {
    fn fail(&mut self, path: &Path, error: &io::Error) {
        self.failed += 1;
        if self.errors.len() < MAX_ERRORS {
            self.errors.push(format!("{}: {error}", path.display()));
        }
    }
}

/// The launchers of the local Desktop (`from`) and the server's Desktop (`to`).
#[derive(Debug, Clone)]
pub struct Launchers {
    pub from: PathBuf,
    pub to: PathBuf,
}

/// Moves what is left in `sources` into `unsorted` (`…/Chưa sắp xếp/YYYY-MM-DD`), keeping the folder structure,
/// and copies the local Desktop's launchers when `launchers` is given. `unsorted` is only created when something
/// moves into it.
pub fn tidy(sources: &[PathBuf], unsorted: &Path, launchers: Option<&Launchers>) -> Report {
    let mut report = Report::default();
    if let Some(launchers) = launchers {
        copy_launchers(launchers, &mut report);
    }
    for source in sources {
        move_tree(source, unsorted, true, &mut report);
    }
    report
}

/// Whether `dir` may be tidied: an existing real folder (not a symlink) inside the home folder, not the home folder
/// itself, and apart from the server's folder `target` (both checked on the resolved paths).
pub fn safe_source(dir: &Path, home: &Path, target: &Path) -> bool {
    if !dir.is_absolute() || dir.components().any(|part| part == Component::ParentDir) {
        return false;
    }
    if !fs::symlink_metadata(dir).is_ok_and(|metadata| metadata.is_dir()) {
        return false;
    }
    let (Ok(dir), Ok(home)) = (fs::canonicalize(dir), fs::canonicalize(home)) else {
        return false;
    };
    let target = fs::canonicalize(target).unwrap_or_else(|_| target.to_path_buf());
    dir != home && dir.starts_with(&home) && !dir.starts_with(&target) && !target.starts_with(&dir)
}

fn is_launcher(name: &OsStr) -> bool {
    name.as_bytes().ends_with(b".desktop")
}

fn copy_launchers(launchers: &Launchers, report: &mut Report) {
    let entries = match fs::read_dir(&launchers.from) {
        Ok(entries) => entries,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            report.launchers_done = true;
            return;
        }
        Err(error) => {
            report.fail(&launchers.from, &error);
            return;
        }
    };
    let mut all_there = true;
    for entry in entries.flatten() {
        let name = entry.file_name();
        if !is_launcher(&name) || !entry.file_type().is_ok_and(|kind| kind.is_file()) {
            continue;
        }
        let dest = launchers.to.join(&name);
        if fs::symlink_metadata(&dest).is_ok() {
            continue;
        }
        match transfer(&entry.path(), &dest, false, &copy_contents) {
            Ok(_) => report.copied += 1,
            Err(error) => {
                all_there = false;
                report.fail(&entry.path(), &error);
            }
        }
    }
    report.launchers_done = all_there;
}

/// Moves the entries of `dir` into `dest`, file by file; a folder left empty moves too (made on the server, then
/// removed here).
fn move_tree(dir: &Path, dest: &Path, top: bool, report: &mut Report) {
    let entries = match fs::read_dir(dir) {
        Ok(entries) => entries,
        Err(error) => {
            if error.kind() != io::ErrorKind::NotFound {
                report.fail(dir, &error);
            }
            return;
        }
    };
    let mut entries: Vec<fs::DirEntry> = entries.flatten().collect();
    entries.sort_by_key(|entry| entry.file_name());
    for entry in entries {
        let name = entry.file_name();
        // The entry's own type: a symlink is a symlink here, never what it points at.
        let Ok(kind) = entry.file_type() else {
            continue;
        };
        if top && name.as_bytes().starts_with(b".") {
            continue;
        }
        let path = entry.path();
        if kind.is_dir() {
            let inner = dest.join(&name);
            move_tree(&path, &inner, false, report);
            let now_empty = fs::read_dir(&path).is_ok_and(|mut rest| rest.next().is_none());
            if now_empty && fs::create_dir_all(&inner).is_ok() {
                // remove_dir only removes an empty folder.
                let _ = fs::remove_dir(&path);
            }
        } else if kind.is_file() && !is_launcher(&name) {
            match transfer(&path, &dest.join(&name), true, &copy_contents) {
                Ok(_) => report.moved += 1,
                Err(error) => report.fail(&path, &error),
            }
        }
    }
}

/// Moves one file to `dest`, or to a free name beside it. The local file stays when anything fails.
pub fn move_file(src: &Path, dest: &Path) -> io::Result<PathBuf> {
    transfer(src, dest, true, &copy_contents)
}

/// Copies `src` to `dest` (or a free name beside it): into a temporary name first, sizes compared, then renamed into
/// place. With `remove_source`, the local file is removed after that, unless it changed meanwhile. Returns where
/// the copy is.
pub(crate) fn transfer(
    src: &Path,
    dest: &Path,
    remove_source: bool,
    copy: &dyn Fn(&Path, &Path) -> io::Result<()>,
) -> io::Result<PathBuf> {
    let before = fs::symlink_metadata(src)?;
    if !before.file_type().is_file() {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "not a regular file"));
    }
    let dir = dest.parent().ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "no destination folder"))?;
    let name = dest.file_name().ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "no destination name"))?;
    fs::create_dir_all(dir)?;
    let temp = dir.join(format!(".{}.caramos-business-{}.part", name.to_string_lossy(), std::process::id()));
    let placed = (|| {
        copy(src, &temp)?;
        let copied = fs::symlink_metadata(&temp)?.len();
        if copied != before.len() {
            return Err(io::Error::other(format!("the copy has {copied} of {} bytes", before.len())));
        }
        let now = fs::symlink_metadata(src)?;
        if now.len() != before.len() || now.modified().ok() != before.modified().ok() {
            return Err(io::Error::other("the file changed while it was copied"));
        }
        let placed = free_name(dest)?;
        fs::rename(&temp, &placed)?;
        let arrived = fs::symlink_metadata(&placed)?.len();
        if arrived != before.len() {
            return Err(io::Error::other(format!("the copy in place has {arrived} of {} bytes", before.len())));
        }
        Ok(placed)
    })();
    let placed = match placed {
        Ok(placed) => placed,
        Err(error) => {
            let _ = fs::remove_file(&temp);
            return Err(error);
        }
    };
    if remove_source {
        let now = fs::symlink_metadata(src)?;
        if now.len() != before.len() || now.modified().ok() != before.modified().ok() {
            return Err(io::Error::other("the file changed after it was copied; it stays here too"));
        }
        fs::remove_file(src)?;
    }
    Ok(placed)
}

/// `dest`, or `name (2).ext`, `name (3).ext`… when it is taken: nothing on the server is overwritten.
fn free_name(dest: &Path) -> io::Result<PathBuf> {
    if fs::symlink_metadata(dest).is_err() {
        return Ok(dest.to_path_buf());
    }
    let stem = dest.file_stem().map(|stem| stem.to_string_lossy().into_owned()).unwrap_or_default();
    let extension = dest.extension().map(|extension| format!(".{}", extension.to_string_lossy())).unwrap_or_default();
    for number in 2..1000 {
        let candidate = dest.with_file_name(format!("{stem} ({number}){extension}"));
        if fs::symlink_metadata(&candidate).is_err() {
            return Ok(candidate);
        }
    }
    Err(io::Error::new(io::ErrorKind::AlreadyExists, "no free name"))
}

/// Copies the bytes into a new file, then keeps the modification time and the permission bits where the share lets
/// it (an SMB share may refuse either; the copy counts all the same).
fn copy_contents(src: &Path, temp: &Path) -> io::Result<()> {
    let mut input = File::open(src)?;
    let mut output = OpenOptions::new().write(true).create_new(true).open(temp)?;
    io::copy(&mut input, &mut output)?;
    output.sync_all()?;
    let metadata = input.metadata()?;
    if let Ok(modified) = metadata.modified() {
        let _ = output.set_modified(modified);
    }
    let _ = output.set_permissions(metadata.permissions());
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::testutil::TempDir;
    use std::io::Write;

    fn write(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, text).unwrap();
    }

    #[test]
    fn move_copies_compares_renames_then_removes() {
        let dir = TempDir::new("move");
        let src = dir.path().join("local/báo cáo.odt");
        write(&src, "the report");
        let dest = dir.path().join("server/Chưa sắp xếp/2026-11-21/báo cáo.odt");
        let placed = move_file(&src, &dest).unwrap();
        assert_eq!(placed, dest);
        assert_eq!(fs::read_to_string(&dest).unwrap(), "the report");
        assert!(!src.exists());
        // No temporary file is left.
        assert_eq!(fs::read_dir(dest.parent().unwrap()).unwrap().count(), 1);
    }

    #[test]
    fn taken_names_get_a_number() {
        let dir = TempDir::new("names");
        let dest = dir.path().join("server/a.txt");
        write(&dest, "already there");
        let src = dir.path().join("local/a.txt");
        write(&src, "new");
        assert_eq!(move_file(&src, &dest).unwrap(), dir.path().join("server/a (2).txt"));
        assert_eq!(fs::read_to_string(&dest).unwrap(), "already there");
        write(&src, "newer");
        assert_eq!(move_file(&src, &dest).unwrap(), dir.path().join("server/a (3).txt"));
    }

    #[test]
    fn a_failed_copy_keeps_the_source() {
        let dir = TempDir::new("failed-copy");
        let src = dir.path().join("local/data.xlsx");
        write(&src, "0123456789");

        // The destination folder cannot be made: a file stands where it should be.
        write(&dir.path().join("server"), "not a folder");
        assert!(move_file(&src, &dir.path().join("server/data.xlsx")).is_err());
        assert_eq!(fs::read_to_string(&src).unwrap(), "0123456789");

        // The copy breaks off half way: the sizes differ, the partial copy goes, the source stays.
        let half = |from: &Path, to: &Path| -> io::Result<()> {
            let data = fs::read(from)?;
            let mut file = OpenOptions::new().write(true).create_new(true).open(to)?;
            file.write_all(&data[..data.len() / 2])
        };
        let dest = dir.path().join("server2/data.xlsx");
        assert!(transfer(&src, &dest, true, &half).is_err());
        assert_eq!(fs::read_to_string(&src).unwrap(), "0123456789");
        assert!(!dest.exists());
        assert_eq!(fs::read_dir(dir.path().join("server2")).unwrap().count(), 0);

        // The copy fails outright.
        let broken = |_: &Path, _: &Path| -> io::Result<()> { Err(io::Error::other("disk full")) };
        assert!(transfer(&src, &dest, true, &broken).is_err());
        assert_eq!(fs::read_to_string(&src).unwrap(), "0123456789");
        assert!(!dest.exists());
    }

    #[test]
    fn tidy_moves_files_and_folders_and_copies_launchers() {
        let dir = TempDir::new("tidy");
        let home = dir.path().join("home");
        let desktop = home.join("Desktop");
        let documents = home.join("Documents");
        let target = dir.path().join("server/lan");
        write(&desktop.join("notes.txt"), "notes");
        write(&desktop.join("zalo.desktop"), "[Desktop Entry]");
        write(&desktop.join(".directory"), "settings");
        write(&desktop.join("Dự án/plan.odt"), "plan");
        write(&desktop.join("Dự án/.git/HEAD"), "ref");
        write(&documents.join("hop-dong.pdf"), "contract");
        write(&documents.join("notes.txt"), "other notes");
        fs::create_dir_all(documents.join("empty")).unwrap();
        std::os::unix::fs::symlink("/etc", desktop.join("link")).unwrap();
        fs::create_dir_all(&target).unwrap();

        assert!(safe_source(&desktop, &home, &target));
        assert!(!safe_source(&home, &home, &target));
        assert!(!safe_source(&desktop.join("link"), &home, &target));
        assert!(!safe_source(&home.join("Desktop/../.."), &home, &target));

        let unsorted = target.join(UNSORTED).join("2026-11-21");
        let launchers = Launchers { from: desktop.clone(), to: target.join("Desktop") };
        let report = tidy(&[desktop.clone(), documents.clone()], &unsorted, Some(&launchers));
        assert_eq!(report.failed, 0, "{:?}", report.errors);
        assert_eq!(report.moved, 5);
        assert_eq!(report.copied, 1);
        assert!(report.launchers_done);

        assert_eq!(fs::read_to_string(unsorted.join("notes.txt")).unwrap(), "notes");
        assert_eq!(fs::read_to_string(unsorted.join("notes (2).txt")).unwrap(), "other notes");
        assert_eq!(fs::read_to_string(unsorted.join("Dự án/plan.odt")).unwrap(), "plan");
        assert_eq!(fs::read_to_string(unsorted.join("Dự án/.git/HEAD")).unwrap(), "ref");
        assert_eq!(fs::read_to_string(unsorted.join("hop-dong.pdf")).unwrap(), "contract");
        assert!(unsorted.join("empty").is_dir());
        assert_eq!(fs::read_to_string(target.join("Desktop/zalo.desktop")).unwrap(), "[Desktop Entry]");

        // Left here: the launcher, the hidden settings file and the symlink; the emptied folders are gone.
        let mut left: Vec<String> =
            fs::read_dir(&desktop).unwrap().map(|entry| entry.unwrap().file_name().into_string().unwrap()).collect();
        left.sort();
        assert_eq!(left, [".directory", "link", "zalo.desktop"]);
        assert_eq!(fs::read_dir(&documents).unwrap().count(), 0);
        assert!(!unsorted.join("link").exists());

        // A second tidy finds nothing to move and makes no new folder.
        let again = target.join(UNSORTED).join("2026-11-22");
        let report = tidy(&[desktop.clone(), documents.clone()], &again, Some(&launchers));
        assert_eq!((report.moved, report.copied, report.failed), (0, 0, 0));
        assert!(!again.exists());
    }
}
