//! Helpers for the unit tests.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

static NEXT: AtomicUsize = AtomicUsize::new(0);

/// A new folder under the system's temporary folder, removed with all it holds when dropped.
pub struct TempDir(PathBuf);

impl TempDir {
    pub fn new(name: &str) -> TempDir {
        let unique = NEXT.fetch_add(1, Ordering::SeqCst);
        let path = std::env::temp_dir().join(format!("caramos-business-{name}-{}-{unique}", std::process::id()));
        let _ = std::fs::remove_dir_all(&path);
        std::fs::create_dir_all(&path).expect("a temporary folder");
        TempDir(path)
    }

    pub fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for TempDir {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
