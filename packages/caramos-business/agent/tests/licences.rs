//! The licences of CaramOS 1.5.0's apps that 0.3.0 reported as unknown (PROTOCOL.md part 3, "Licence report", and its
//! 0.3.1 changes), from copyright files copied from the 1.5.0 VMs into ./copyright: the older files of Xfce, gufw and
//! pavucontrol, and the machine-readable files of onboard and mate-desktop, which have no `Files: *` stanza.

use std::fs;
use std::path::PathBuf;

use caramos_business_agent::inventory;

fn copyright(package: &str) -> String {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/copyright").join(package);
    String::from_utf8_lossy(&fs::read(&path).unwrap_or_else(|error| panic!("{}: {error}", path.display()))).into_owned()
}

#[test]
fn older_copyright_files() {
    for (package, expected) in [
        // "GNU/GPL for the others" and `/usr/share/common-licenses/GPL'.
        ("thunar", "GPL"),
        // Stanzas without a Format line: GPL and GPL-2+ 14 times each, GPL first.
        ("xfwm4", "GPL"),
        ("xfce4-panel", "GPL-2+"),
        ("xfce4-terminal", "GPL-2+"),
        // "the GNU General Public License version 2 or later", besides stanzas that mostly say GPL.
        ("xfce4-session", "GPL-2+"),
        ("xfce4-power-manager", "GPL-2+"),
        ("xfce4-dict", "GPL-2+"),
        ("thunar-volman", "GPL-2+"),
        // `Files: *` in a file without a Format line.
        ("pavucontrol", "GPL-2+"),
        ("gufw", "GPL-3+"),
    ] {
        let text = copyright(package);
        assert_eq!(inventory::copyright_licence(&text), None, "{package}: not machine-readable");
        assert_eq!(inventory::copyright_inferred(&text).as_deref(), Some(expected), "{package}");
    }
}

#[test]
fn machine_readable_files_without_files_star() {
    for (package, expected) in [("onboard", "GPL-3+"), ("mate-desktop", "GPL-2+")] {
        let text = copyright(package);
        assert_eq!(inventory::copyright_licence(&text), None, "{package}: no Files: * stanza, no licence in the header");
        assert_eq!(inventory::copyright_inferred(&text).as_deref(), Some(expected), "{package}");
    }
}
