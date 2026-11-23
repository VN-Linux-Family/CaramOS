//! The company wallpaper in the user's session (PROTOCOL.md "Wallpaper"): gsettings on Cinnamon, xfconf-query on
//! Xfce, the way caramos-daily-wallpaper sets it.

use std::path::Path;
use std::time::Duration;

use crate::process;

const TOOL_TIMEOUT: Duration = Duration::from_secs(30);
const CINNAMON_BACKGROUND: &str = "org.cinnamon.desktop.background";
const CINNAMON_SLIDESHOW: &str = "org.cinnamon.desktop.background.slideshow";
const XFCE_CHANNEL: &str = "xfce4-desktop";
/// xfdesktop's image-style "zoomed", as Cinnamon's picture-options 'zoom'.
const XFCE_ZOOMED: &str = "5";

/// The desktop of the session, from XDG_CURRENT_DESKTOP.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Desktop {
    Cinnamon,
    Xfce,
    Other,
}

impl Desktop {
    /// XDG_CURRENT_DESKTOP is a colon-separated list: X-Cinnamon (or Cinnamon), XFCE.
    pub fn from_xdg(value: &str) -> Desktop {
        for name in value.split(':') {
            match name.trim().to_ascii_lowercase().as_str() {
                "x-cinnamon" | "cinnamon" => return Desktop::Cinnamon,
                "xfce" => return Desktop::Xfce,
                _ => {}
            }
        }
        Desktop::Other
    }
}

/// Whether the desktop shows `image` now: Cinnamon's picture-uri, or every Xfce monitor and workspace.
pub fn shows(desktop: Desktop, image: &Path) -> Result<bool, String> {
    match desktop {
        Desktop::Cinnamon => Ok(gsettings_get(CINNAMON_BACKGROUND, "picture-uri")? == file_uri(image)),
        Desktop::Xfce => {
            let wanted = image.to_string_lossy();
            let images = xfce_images()?;
            Ok(!images.is_empty() && images.iter().all(|(_, value)| *value == wanted))
        }
        Desktop::Other => Err("this desktop is neither Cinnamon nor Xfce".to_string()),
    }
}

/// Shows `image`, zoomed. On Cinnamon a running slideshow is turned off, or it would replace the picture.
pub fn set(desktop: Desktop, image: &Path) -> Result<(), String> {
    match desktop {
        Desktop::Cinnamon => {
            if gsettings_get(CINNAMON_SLIDESHOW, "slideshow-enabled").is_ok_and(|value| value == "true") {
                gsettings_set(CINNAMON_SLIDESHOW, "slideshow-enabled", "false")?;
            }
            gsettings_set(CINNAMON_BACKGROUND, "picture-uri", &gvariant_string(&file_uri(image)))?;
            gsettings_set(CINNAMON_BACKGROUND, "picture-options", "'zoom'")
        }
        Desktop::Xfce => {
            let path = image.to_str().ok_or("the image's path is not UTF-8")?;
            let images = xfce_images()?;
            if images.is_empty() {
                return Err("Xfce has no desktop picture settings (/backdrop/…/last-image) yet".to_string());
            }
            for (property, _) in &images {
                xfconf_set(property, "string", path)?;
                let style = format!("{}image-style", property.trim_end_matches("last-image"));
                xfconf_set(&style, "int", XFCE_ZOOMED)?;
            }
            Ok(())
        }
        Desktop::Other => Err("this desktop is neither Cinnamon nor Xfce".to_string()),
    }
}

fn gsettings_get(schema: &str, key: &str) -> Result<String, String> {
    let output = process::run("gsettings", &["get", schema, key], TOOL_TIMEOUT)
        .map_err(|error| format!("gsettings: {error}"))?;
    if !output.success() {
        return Err(format!("gsettings get {schema} {key}: {}", output.message()));
    }
    Ok(parse_gvariant_string(output.stdout.trim()))
}

fn gsettings_set(schema: &str, key: &str, value: &str) -> Result<(), String> {
    let output = process::run("gsettings", &["set", schema, key, value], TOOL_TIMEOUT)
        .map_err(|error| format!("gsettings: {error}"))?;
    if !output.success() {
        return Err(format!("gsettings set {schema} {key}: {}", output.message()));
    }
    Ok(())
}

/// The text of a GVariant string as gsettings prints it ('…' with \' and \\), or the text as it is (true, 42).
pub fn parse_gvariant_string(text: &str) -> String {
    let quoted = text.len() >= 2
        && ((text.starts_with('\'') && text.ends_with('\'')) || (text.starts_with('"') && text.ends_with('"')));
    if !quoted {
        return text.to_string();
    }
    let mut value = String::with_capacity(text.len());
    let mut chars = text[1..text.len() - 1].chars();
    while let Some(c) = chars.next() {
        if c == '\\' {
            if let Some(next) = chars.next() {
                value.push(next);
            }
        } else {
            value.push(c);
        }
    }
    value
}

/// A GVariant string literal of `value`, for `gsettings set`.
pub fn gvariant_string(value: &str) -> String {
    format!("'{}'", value.replace('\\', "\\\\").replace('\'', "\\'"))
}

/// file:// URI of a path, percent-encoding what is not plain.
pub fn file_uri(path: &Path) -> String {
    let mut uri = String::from("file://");
    for byte in path.to_string_lossy().bytes() {
        if byte.is_ascii_alphanumeric() || b"/-._~".contains(&byte) {
            uri.push(byte as char);
        } else {
            uri.push_str(&format!("%{byte:02X}"));
        }
    }
    uri
}

/// The Xfce desktop's pictures: (property, path) for each monitor and workspace.
fn xfce_images() -> Result<Vec<(String, String)>, String> {
    let output = process::run("xfconf-query", &["-c", XFCE_CHANNEL, "-lv"], TOOL_TIMEOUT)
        .map_err(|error| format!("xfconf-query: {error}"))?;
    if !output.success() {
        return Err(format!("xfconf-query -c {XFCE_CHANNEL}: {}", output.message()));
    }
    Ok(last_images(&output.stdout))
}

fn xfconf_set(property: &str, kind: &str, value: &str) -> Result<(), String> {
    let args = ["-c", XFCE_CHANNEL, "-p", property, "-n", "-t", kind, "-s", value];
    let output = process::run("xfconf-query", &args, TOOL_TIMEOUT).map_err(|error| format!("xfconf-query: {error}"))?;
    if !output.success() {
        return Err(format!("xfconf-query -p {property}: {}", output.message()));
    }
    Ok(())
}

/// The `last-image` properties and their values in the output of `xfconf-query -c xfce4-desktop -lv`
/// ("<property> <value>" per line).
pub fn last_images(listing: &str) -> Vec<(String, String)> {
    listing
        .lines()
        .filter_map(|line| {
            let line = line.trim_end();
            let (name, value) = match line.split_once(char::is_whitespace) {
                Some((name, value)) => (name, value.trim_start()),
                None => (line, ""),
            };
            is_last_image(name).then(|| (name.to_string(), value.to_string()))
        })
        .collect()
}

/// `/backdrop/screen<N>/monitor<NAME>[/workspace<N>]/last-image`, as caramos-daily-wallpaper matches them.
pub fn is_last_image(name: &str) -> bool {
    /// What follows at least one digit at the start of `text`.
    fn digits_then(text: &str) -> Option<&str> {
        let count = text.bytes().take_while(u8::is_ascii_digit).count();
        (count > 0).then(|| &text[count..])
    }
    let Some(rest) = name.strip_prefix("/backdrop/screen").and_then(digits_then) else {
        return false;
    };
    let Some((monitor, rest)) = rest.strip_prefix("/monitor").and_then(|rest| rest.split_once('/')) else {
        return false;
    };
    if monitor.is_empty() {
        return false;
    }
    rest == "last-image"
        || rest.strip_prefix("workspace").and_then(digits_then).is_some_and(|rest| rest == "/last-image")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktops() {
        assert_eq!(Desktop::from_xdg("X-Cinnamon"), Desktop::Cinnamon);
        assert_eq!(Desktop::from_xdg("Cinnamon"), Desktop::Cinnamon);
        assert_eq!(Desktop::from_xdg("XFCE"), Desktop::Xfce);
        assert_eq!(Desktop::from_xdg("ubuntu:GNOME"), Desktop::Other);
        assert_eq!(Desktop::from_xdg(""), Desktop::Other);
    }

    #[test]
    fn xfce_properties() {
        for good in [
            "/backdrop/screen0/monitor0/last-image",
            "/backdrop/screen0/monitorVirtual-1/workspace0/last-image",
            "/backdrop/screen1/monitoreDP-1/workspace12/last-image",
        ] {
            assert!(is_last_image(good), "{good}");
        }
        for bad in [
            "/backdrop/screen0/monitor/last-image",
            "/backdrop/screen/monitor0/last-image",
            "/backdrop/screen0/monitor0/workspace/last-image",
            "/backdrop/screen0/monitor0/workspace0/image-style",
            "/backdrop/screen0/monitor0/last-image/x",
            "/backdrop/screen0/monitor0/last-single-image",
        ] {
            assert!(!is_last_image(bad), "{bad}");
        }
        let listing = "/backdrop/screen0/monitor0/image-path                  /usr/share/a.jpg\n\
                       /backdrop/screen0/monitor0/last-image                  /usr/share/backgrounds/My Photo.jpg\n\
                       /backdrop/screen0/monitorVirtual-1/workspace0/last-image /x.png\n\
                       /desktop-icons/icon-size                               48\n";
        assert_eq!(
            last_images(listing),
            [
                ("/backdrop/screen0/monitor0/last-image".to_string(), "/usr/share/backgrounds/My Photo.jpg".to_string()),
                ("/backdrop/screen0/monitorVirtual-1/workspace0/last-image".to_string(), "/x.png".to_string()),
            ]
        );
    }

    #[test]
    fn gsettings_values() {
        assert_eq!(parse_gvariant_string("'file:///a/b.jpg'"), "file:///a/b.jpg");
        assert_eq!(parse_gvariant_string(r"'it\'s'"), "it's");
        assert_eq!(parse_gvariant_string("true"), "true");
        assert_eq!(gvariant_string("it's"), r"'it\'s'");
        let path = Path::new("/var/lib/caramos-business/agent/files/a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7.jpg");
        assert_eq!(file_uri(path), format!("file://{}", path.display()));
        assert_eq!(file_uri(Path::new("/a b/ả.jpg")), "file:///a%20b/%E1%BA%A3.jpg");
    }
}
