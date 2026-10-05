"""Static safety checks for CaramOS Control Center applet."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
APPLET_DIR = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos"
APPLET_JS = APPLET_DIR / "applet.js"
STYLESHEET = APPLET_DIR / "stylesheet.css"


class ControlCenterAppletStaticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APPLET_JS.read_text(encoding="utf-8")
        cls.css = STYLESHEET.read_text(encoding="utf-8")

    def test_javascript_syntax(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        subprocess.run([node, "--check", str(APPLET_JS)], check=True, capture_output=True, text=True)

    def test_no_sync_runtime_commands(self) -> None:
        self.assertNotIn("_fallbackNetworkState", self.source)
        self.assertNotIn("spawn_sync", self.source)
        self.assertNotIn("safeCommandOutput", self.source)
        self.assertNotIn("new_for_bus_sync", self.source)

    def test_wifi_actions_do_not_pass_secrets(self) -> None:
        self.assertNotRegex(self.source, r"nmcli[^\n]*(?:password|psk)")
        self.assertNotRegex(self.source, r"spawn[^\n]*network\.ssid")
        self.assertIn("network.bestAp.path", self.source)

    def test_session_actions_use_capabilities(self) -> None:
        self.assertIn("GetCapabilities", self.source)
        for capability in (
            "canSwitchUser",
            "canShutdown",
            "canRestart",
            "canSuspend",
            "canHibernate",
            "canLogout",
        ):
            self.assertIn(capability, self.source)

    def test_backend_cleanup_is_present(self) -> None:
        for backend in (
            "_networkBackend",
            "_wifiBackend",
            "_bluezBackend",
            "_powerBackend",
            "_powerProfilesBackend",
            "_sessionBackend",
        ):
            self.assertRegex(self.source, rf"if \(this\.{backend}\) \{{[\s\S]*?this\.{backend}\.dispose\(\)")

    def test_power_profiles_backend_uses_async_dbus(self) -> None:
        backend = re.search(r"class PowerProfilesBackend \{([\s\S]*?)\n\}\n\nclass SessionBackend", self.source)
        self.assertIsNotNone(backend)
        source = backend.group(1)
        for token in (
            "org.freedesktop.UPower.PowerProfiles",
            "/org/freedesktop/UPower/PowerProfiles",
            "net.hadess.PowerProfiles",
            "/net/hadess/PowerProfiles",
            "Gio.Cancellable",
            "Gio.bus_watch_name",
            "Gio.bus_unwatch_name",
            "Gio.DBusProxy.new_for_bus",
            "g-properties-changed",
            "ActiveProfile",
            "Profiles",
            "PerformanceDegraded",
            "org.freedesktop.DBus.Properties",
        ):
            self.assertIn(token, self.source)
        self.assertNotIn("powerprofilesctl", source)
        self.assertNotIn("new_for_bus_sync", source)
        self.assertNotIn("call_sync", source)

    def test_package_installs_current_applet_into_cinnamon(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertIn(
            "usr/share/caramos-ota/applets/caramos-control-center@caramos usr/share/cinnamon/applets/",
            install,
        )

    def test_power_mode_tile_and_panel_contract(self) -> None:
        for token in (
            "this._powerModeTile = createSplitTile(",
            "_('Chế độ nguồn')",
            "_('Hiệu năng')",
            "_('Cân bằng')",
            "_('Tiết kiệm pin')",
            "_toggleInlinePanel(",
            "'power-mode'",
            "_fillPowerModeList",
            "object-select-symbolic",
            "spawnAllowed('powerSettings')",
        ):
            self.assertIn(token, self.source)
        # Dark mode sits next to Night Light; Power mode has its own row and anchors its list there.
        self.assertIn("this._powerRow.add_child(this._powerModeTile.actor)", self.source)
        dark_mode_position = self.source.index("this._displayRow.add_child(this._darkModeTile.actor)")
        night_light_position = self.source.index("this._displayRow.add_child(this._nightLightTile.actor)")
        self.assertLess(dark_mode_position, night_light_position)
        rows = [
            self.source.index(f"container.add_child(this.{row})")
            for row in ("_networkRow", "_connectionsRow", "_displayRow", "_powerRow")
        ]
        self.assertEqual(sorted(rows), rows)
        self.assertRegex(self.source, r"body => this\._fillPowerModeList\(body\),\s*this\._powerRow\s*\)")
        self.assertRegex(
            self.source,
            r"createSplitTile\([\s\S]*?_\('Chế độ nguồn'\)[\s\S]*?\(\) => this\._openPowerModeOverlay\(\),[\s\S]*?\(\) => this\._openPowerModeOverlay\(\)",
        )
        self.assertRegex(self.source, r"state\.profiles\.forEach\(profile =>")
        self.assertIn("createPowerProfileRow", self.source)
        self.assertNotRegex(self.source, r"profiles:\s*\[['\"]performance")

    def test_power_profile_selection_keeps_parent_popup_open(self) -> None:
        helper = re.search(
            r"function createPowerProfileRow\(iconName, text, selected, onActivate\) \{([\s\S]*?)\n\}",
            self.source,
        )
        self.assertIsNotNone(helper)
        body = helper.group(1)
        self.assertIn("PopupMenu.PopupBaseMenuItem", body)
        self.assertIn("item.connect('activate'", body)
        self.assertIn("item.activate = function (event)", body)
        self.assertIn("this.emit('activate', event, true)", body)
        self.assertNotIn("connect('clicked'", body)

        filler = re.search(
            r"_fillPowerModeList\(body\) \{([\s\S]*?)\n    \}\n\n    _setPowerProfileActive",
            self.source,
        )
        self.assertIsNotNone(filler)
        self.assertIn("createPowerProfileRow(", filler.group(1))

    def test_power_profile_selection_closes_inline_only(self) -> None:
        method = re.search(
            r"_setPowerProfileActive\(profile\) \{([\s\S]*?)\n    \}\n\n    _onPowerProfilesStateChanged",
            self.source,
        )
        self.assertIsNotNone(method)
        body = method.group(1)
        self.assertIn("state.profiles.indexOf(profile) === -1", body)
        self.assertIn("this._inlineFocusTarget = this._powerModeTile.mainButton", body)
        self.assertIn("this._closeInlinePanel('power-profile-selected')", body)
        self.assertIn("profile !== state.activeProfile", body)
        self.assertIn("this._powerProfilesBackend.setActiveProfile(profile)", body)
        self.assertLess(
            body.index("this._closeInlinePanel('power-profile-selected')"),
            body.index("this._powerProfilesBackend.setActiveProfile(profile)"),
        )
        self.assertNotIn("this.menu.close()", body)
        self.assertNotIn("this._closeSubmenus()", body)

    def _method_body(self, name: str) -> str:
        match = re.search(rf"\n    {name}\([^)]*\) \{{([\s\S]*?)\n    \}}\n", self.source)
        self.assertIsNotNone(match, f"method {name} not found")
        return match.group(1)

    def test_every_called_private_method_is_defined(self) -> None:
        called = set(re.findall(r"this\.(_[A-Za-z0-9_]+)\(", self.source))
        defined = set(re.findall(r"^\s+(_[A-Za-z0-9_]+)\s*\([^)]*\)\s*\{", self.source, re.M))
        assigned = set(re.findall(r"this\.(_[A-Za-z0-9_]+)\s*=", self.source))
        self.assertEqual(set(), called - defined - assigned)

    def test_open_inline_lists_keep_focus_when_rebuilt(self) -> None:
        for name in (
            "_fillPowerModeList",
            "_fillWifiList",
            "_fillBluetoothList",
            "_fillVpnList",
            "_fillAudioDeviceList",
            "_onSessionStateChanged",
        ):
            body = self._method_body(name)
            self.assertIn("const restoreFocus = this._parkInlineFocus(", body, name)
            self.assertLess(body.index("this._parkInlineFocus("), body.index("destroy_all_children()"), name)
            self.assertIn("restoreFocus();", body, name)
        first = self._method_body("_focusFirstControl")
        self.assertIn("this._focusableControls(container)[0]", first)
        controls = self._method_body("_focusableControls")
        self.assertIn("stack.unshift(...actor.get_children())", controls)
        park = self._method_body("_parkInlineFocus")
        self.assertIn("body.contains(focus)", park)
        self.assertIn("this._inlineCloseButton || this.menu.actor", park)

    def test_bluetooth_list_refresh_is_coalesced(self) -> None:
        self.assertIn("const BT_LIST_REFRESH_MS = ", self.source)
        body = self._method_body("_scheduleBluetoothListRefresh")
        self.assertIn("if (this._bluetoothRefreshId) return;", body)
        self.assertIn("Mainloop.timeout_add(BT_LIST_REFRESH_MS", body)
        self.assertIn("this._bluetoothListSignature() !== this._bluetoothRenderSignature", body)
        fill = self._method_body("_fillBluetoothList")
        self.assertIn("this._bluetoothRenderSignature = this._bluetoothListSignature();", fill)

    def test_power_profiles_are_shown_in_fixed_order(self) -> None:
        self.assertIn("const POWER_PROFILE_ORDER = ['performance', 'balanced', 'power-saver'];", self.source)
        refresh = re.search(r"class PowerProfilesBackend \{[\s\S]*?\n    _refresh\(\) \{([\s\S]*?)\n    \}\n", self.source)
        self.assertIsNotNone(refresh)
        self.assertIn("POWER_PROFILE_ORDER.indexOf(profile)", refresh.group(1))
        self.assertIn("profiles.sort(", refresh.group(1))

    def test_power_profile_failure_is_shown_on_tile_and_cleared(self) -> None:
        backend = re.search(r"class PowerProfilesBackend \{([\s\S]*?)\n\}\n\nclass SessionBackend", self.source)
        self.assertIsNotNone(backend)
        source = backend.group(1)
        self.assertIn("this._setError(_('Không thể đổi chế độ nguồn'))", source)
        self.assertIn("GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, POWER_PROFILE_ERROR_SECONDS", source)
        self.assertRegex(source, r"dispose\(\) \{[\s\S]*?this\._clearErrorTimeout\(\)")
        self.assertIn("_('Không đổi được')", self._method_body("_onPowerProfilesStateChanged"))

    def test_selectable_rows_put_check_mark_at_trailing_edge(self) -> None:
        for helper_name in ("createPowerProfileRow", "createAudioDeviceRow"):
            helper = re.search(rf"function {helper_name}\([^)]*\) \{{([\s\S]*?)\n\}}", self.source)
            self.assertIsNotNone(helper, helper_name)
            self.assertIn(
                "const row = new St.BoxLayout({ vertical: false, x_expand: true, x_align: Clutter.ActorAlign.FILL });",
                helper.group(1),
                helper_name,
            )

    def test_referenced_style_classes_exist(self) -> None:
        referenced = set(re.findall(r"['\"](caramos-cc-[a-z0-9-]+)", self.source))
        defined = set(re.findall(r"\.((?:caramos-cc-)[a-z0-9-]+)", self.css))
        missing = sorted(referenced - defined)
        self.assertEqual([], missing, f"missing stylesheet classes: {missing}")

    def test_theme_and_focus_contracts_exist(self) -> None:
        for token in (
            "caramos-cc-light",
            "caramos-cc-dark",
            "caramos-cc-high-contrast",
            "Clutter.KEY_Escape",
            "grab_key_focus",
            "accessible_name",
        ):
            self.assertIn(token, self.source + self.css)

    def test_audio_notify_handlers_use_focused_sync(self) -> None:
        output = re.search(r"_readOutput\(\) \{([\s\S]*?)\n    \}\n\n    _readInput", self.source)
        input_ = re.search(r"_readInput\(\) \{([\s\S]*?)\n    \}\n\n    _onStreamAdded", self.source)
        self.assertIsNotNone(output)
        self.assertIsNotNone(input_)
        self.assertNotRegex(output.group(1), r"notify::(?:volume|is-muted)[^\n]*_refresh\(")
        self.assertNotRegex(input_.group(1), r"notify::(?:volume|is-muted)[^\n]*_refresh\(")
        self.assertIn("_scheduleAudioSync", output.group(1))
        self.assertIn("_scheduleAudioSync", input_.group(1))

    def test_audio_drag_has_pending_write_guards(self) -> None:
        for token in (
            "_audioSliderDragging",
            "_outputVolumePending",
            "_inputVolumePending",
            "_syncAudioUi",
            "_outputVolumeApplyId",
            "_inputVolumeApplyId",
        ):
            self.assertIn(token, self.source)
        self.assertRegex(self.source, r"if \(!this\._audioSliderDragging\.output && !this\._outputVolumeApplyId\)")
        self.assertRegex(self.source, r"if \(!this\._audioSliderDragging\.input && !this\._inputVolumeApplyId\)")

    def test_audio_selector_layout_and_close_focus_contracts_exist(self) -> None:
        for token in (
            "caramos-cc-audio-group",
            "caramos-cc-audio-disclosure",
            "detailsButton",
            "this._audioOutputGroup.add_child(this._volumeRow.actor)",
            "this._audioInputGroup.add_child(this._micRow.actor)",
            "this._volumeRow.detailsButton",
            "this._micRow.detailsButton",
            "this._restoreInlineFocus()",
            "button-press-event",
        ):
            self.assertIn(token, self.source + self.css)
        self.assertNotIn("createAudioSelector", self.source)
        self.assertNotIn("caramos-cc-audio-selector", self.source + self.css)
        self.assertIn("_focusFirstControl(body)", self.source)
        self.assertRegex(self.css, r"\.caramos-cc-audio-disclosure:(?:hover|focus|active|insensitive)")
        self.assertRegex(self.css, r"\.caramos-cc-inline-close:(?:hover|focus|active|insensitive)")

    def test_popup_uses_consistent_rounded_corners(self) -> None:
        popup_rule = re.search(
            r"\.menu\.caramos-cc-popup,[\s\S]*?\.menu\.caramos-cc-popup\.bottom,[\s\S]*?\{([^}]*)\}",
            self.css,
        )
        self.assertIsNotNone(popup_rule)
        self.assertIn("border-radius: 28px", popup_rule.group(1))
        for orientation in ("top", "bottom", "left", "right"):
            self.assertIn(f".menu.caramos-cc-popup.{orientation}", self.css)
        self.assertRegex(
            self.css,
            r"\.caramos-cc-popup \.popup-menu-content\s*\{[^}]*border-radius: 28px",
        )
        self.assertRegex(
            self.css,
            r"\.caramos-cc-popup-box\s*\{[^}]*border-radius: 28px",
        )
        self.assertNotIn("caramos-cc-boxpointer", self.source + self.css)

    def test_focusable_controls_do_not_show_focus_outline(self) -> None:
        focus_rule = re.search(
            r"\.caramos-cc-battery-pill:focus,[\s\S]*?\.caramos-cc-list-row:focus\s*\{([^}]*)\}",
            self.css,
        )
        self.assertIsNotNone(focus_rule)
        self.assertIn("outline: none", focus_rule.group(1))
        self.assertIn("box-shadow: none", focus_rule.group(1))
        for style_class in (
            "caramos-cc-battery-pill",
            "caramos-cc-round-button",
            "caramos-cc-slider-icon-button",
            "caramos-cc-audio-disclosure",
            "caramos-cc-simple-tile",
            "caramos-cc-split-main",
            "caramos-cc-split-arrow",
            "caramos-cc-inline-close",
            "caramos-cc-overlay-close",
            "caramos-cc-list-row",
        ):
            self.assertIn(f".{style_class}:focus", focus_rule.group(0))
        self.assertNotRegex(self.css, r"outline:\s*[1-9][0-9]*px")

    def test_inline_close_debug_is_opt_in_and_bounded(self) -> None:
        for token in (
            ".caramos-cc-debug",
            "const DEBUG_LIMIT = 240",
            "GLib.file_test(DEBUG_MARKER, GLib.FileTest.EXISTS)",
            "global.log(`[caramos-cc-debug:",
            "this._installMenuDebug()",
            "manager-capture",
            "manager-focus",
            "manager-close",
            "inline-x-press",
            "inline-x-clicked",
            "inline-x-release-after",
            "inline-close-before-destroy",
            "inline-focus-restore-start",
        ):
            self.assertIn(token, self.source)
        self.assertNotRegex(self.source, r"ccDebug\([^\n]*(?:ssid|password|deviceName)")

    def test_inline_close_button_traces_normal_click_flow(self) -> None:
        inline = re.search(
            r"_openInlinePanel\(kind, iconName, title, fillFn, anchorRow\) \{([\s\S]*?)\n    \}\n\n    _applyDim",
            self.source,
        )
        self.assertIsNotNone(inline)
        close = re.search(
            r"const closeBtn = new St\.Button\(\{ style_class: 'caramos-cc-inline-close'[\s\S]*?head\.add_child\(closeBtn\);",
            inline.group(1),
        )
        self.assertIsNotNone(close)
        self.assertIn("this._closeInlinePanel('inline-x-click')", close.group(0))
        self.assertIn("closeBtn.connect_after('button-release-event'", close.group(0))
        self.assertIn("event.get_button() === Clutter.BUTTON_PRIMARY", close.group(0))
        self.assertIn("primary ? Clutter.EVENT_STOP : Clutter.EVENT_PROPAGATE", close.group(0))

        close_method = re.search(
            r"_closeInlinePanel\(reason = 'unknown'\) \{([\s\S]*?)\n    \}\n\n    _updateThemeClassesOnce",
            self.source,
        )
        self.assertIsNotNone(close_method)
        close_body = close_method.group(1)
        self.assertIn("this._restoreInlineFocus()", close_body)
        self.assertLess(close_body.index("this._restoreInlineFocus()"), close_body.index("this._expandedPanel.destroy_all_children()"))
        self.assertNotIn("this.menu.close()", close_body)
        self.assertIn("closeBtn.connect('clicked', () => this._closeOverlay())", self.source)

    def test_audio_selection_stays_open_and_settings_closes_menu(self) -> None:
        audio = re.search(r"_fillAudioDeviceList\(body, type\) \{([\s\S]*?)\n    \}\n\n    _applyStreamVolume", self.source)
        self.assertIsNotNone(audio)
        self.assertIn("Mainloop.idle_add", self.source)
        self.assertIn("_audioDeviceRefreshIds", self.source)
        self.assertIn("createAudioDeviceRow", self.source)
        self.assertIn("PopupMenu.PopupBaseMenuItem", self.source)
        self.assertRegex(self.source, r"item\.activate = function \(event\) \{[\s\S]*?this\.emit\('activate', event, true\)")
        self.assertIn("soundSettings: 'cinnamon-settings sound'", self.source)
        self.assertIn("this.menu.close()", audio.group(1))
        self.assertIn("spawnAllowed('soundSettings')", audio.group(1))
        self.assertIn("caramos-cc-audio-pointer-selection", self.source + self.css)
        self.assertNotIn("this._closeInlinePanel();\n            spawnArgvAsync(['cinnamon-settings', 'sound'])", audio.group(1))
        self.assertRegex(self.css, r"\.caramos-cc-list-row\.caramos-cc-audio-pointer-selection:focus")
        self.assertRegex(self.css, r"\.caramos-cc-overlay-close:(?:hover|focus|active|insensitive)")


if __name__ == "__main__":
    unittest.main()
