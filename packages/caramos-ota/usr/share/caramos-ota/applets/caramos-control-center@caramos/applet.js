const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
const Cvc = imports.gi.Cvc;
const Pango = imports.gi.Pango;
const Interfaces = imports.misc.interfaces;
const Lang = imports.lang;
const Mainloop = imports.mainloop;
const Main = imports.ui.main;
const Util = imports.misc.util;

const REFRESH_SECONDS = 15;
const WIFI_LIST_LIMIT = 7;
const BT_LIST_LIMIT = 5;
const NIGHT_LIGHT_SCHEMA = 'org.cinnamon.settings-daemon.plugins.color';
const NIGHT_LIGHT_KEY = 'night-light-enabled';
const BRIGHTNESS_BUS_NAME = 'org.cinnamon.SettingsDaemon.Power.Screen';
const POPUP_EDGE_MARGIN = 0;

function _(text) {
    return text;
}

function runCommand(argv) {
    try {
        return GLib.spawn_sync(null, argv, null, GLib.SpawnFlags.SEARCH_PATH, null);
    } catch (e) {
        global.logError(e);
        return [false, null, null, 1];
    }
}

function commandOutput(argv) {
    const [ok, stdout] = runCommand(argv);
    if (!ok || !stdout) return '';
    return imports.byteArray.toString(stdout).trim();
}

// ---------------------------------------------------------------------------
// Mock mode — for testing the Wi‑Fi/Bluetooth UX without real radios (e.g. in
// a VirtualBox VM). Enable by creating the marker file:
//     touch ~/.caramos-cc-mock
// Remove it to go back to real nmcli/bluetoothctl output. No rebuild needed.
// ---------------------------------------------------------------------------
const MOCK_MARKER = GLib.build_filenamev([GLib.get_home_dir(), '.caramos-cc-mock']);

function mockEnabled() {
    return GLib.file_test(MOCK_MARKER, GLib.FileTest.EXISTS);
}

function mockCommandOutput(argv) {
    const key = argv.join(' ');

    // --- Wi‑Fi -------------------------------------------------------------
    if (key === 'nmcli radio wifi') return 'enabled';

    // SSID:SECURITY:SIGNAL:IN-USE — covers: connected(✓), secured-unsaved
    // (password popup), secured-saved (direct connect), open (no lock),
    // strong/weak signal, long name, duplicate SSID (dedup), hidden(empty).
    if (key === 'nmcli -t -f SSID,SECURITY,SIGNAL,IN-USE device wifi list') {
        return [
            'Saigon Technology:WPA2:92:*',
            'Saigon Technology Guest:WPA2:78:',
            'FreeCoffee_OpenWifi::64:',
            'ICT1 Building:WPA2:55:',
            'DANANG SOFTWARE PARK::48:',
            'Neighbor 5G Super Long Network Name Here:WPA2:33:',
            'Saigon Technology:WPA2:20:',
            'WeakSignal_Far:WPA2:12:',
        ].join('\n');
    }

    // Saved profiles → "Saigon Technology" is saved (direct connect),
    // "ICT1 Building" is NOT (triggers password popup).
    if (key === 'nmcli -t -f NAME,TYPE connection show') {
        return [
            'Saigon Technology:802-11-wireless',
            'Wired connection 1:802-3-ethernet',
            'wt0:vpn',
        ].join('\n');
    }
    if (key === 'nmcli -t -f NAME,TYPE connection show --active') {
        return 'Saigon Technology:802-11-wireless';
    }
    if (key === 'nmcli -t -f ACTIVE,SSID device wifi') return 'yes:Saigon Technology';
    if (key === 'nmcli -t -f TYPE,STATE device') return 'wifi:connected\nethernet:unavailable';

    // --- Bluetooth ---------------------------------------------------------
    if (key === 'bluetoothctl devices') {
        return [
            'Device AA:BB:CC:11:22:33 Sony WH-1000XM4',
            'Device AA:BB:CC:44:55:66 Logitech MX Master 3',
            'Device AA:BB:CC:77:88:99 Galaxy Buds Pro',
            'Device AA:BB:CC:AA:BB:CC My Really Long Bluetooth Speaker Name',
        ].join('\n');
    }
    if (key === 'bluetoothctl devices Connected') {
        return 'Device AA:BB:CC:11:22:33 Sony WH-1000XM4';
    }
    if (key === 'bluetoothctl show') return 'Powered: yes';

    // --- busctl (blueman power status) -------------------------------------
    if (key.indexOf('GetBluetoothStatus') !== -1) return 'b true';

    return '';
}

function safeCommandOutput(argv, timeoutSeconds) {
    if (mockEnabled()) return mockCommandOutput(argv);
    const binary = argv[0];
    if (!commandExists(binary)) return '';
    if (commandExists('timeout')) {
        const timedArgv = ['timeout', String(timeoutSeconds || 1)];
        argv.forEach(arg => timedArgv.push(arg));
        return commandOutput(timedArgv);
    }
    return commandOutput(argv);
}

function commandExists(binary) {
    return GLib.find_program_in_path(binary) !== null;
}

function spawnAsync(commandLine) {
    try {
        Util.spawnCommandLine(commandLine);
    } catch (e) {
        global.logError(e);
    }
}

// Fire-and-forget spawn using an argv array so values coming from the system
// (SSID, Wi‑Fi password, Bluetooth name) are never parsed by a shell.
function spawnArgvAsync(argv) {
    try {
        GLib.spawn_async(null, argv, null, GLib.SpawnFlags.SEARCH_PATH, null);
    } catch (e) {
        global.logError(e);
    }
}

function spawnAllowed(command) {
    const allowed = {
        settings: 'cinnamon-settings',
        networkSettings: 'cinnamon-settings network',
        bluetoothSettings: 'blueman-manager',
        powerSettings: 'cinnamon-settings power',
        lock: commandExists('dm-tool') ? 'dm-tool lock' : 'cinnamon-screensaver-command --lock',
        suspend: 'systemctl suspend',
        restart: 'cinnamon-session-quit --reboot',
        poweroff: 'cinnamon-session-quit --power-off',
        logout: 'cinnamon-session-quit --logout --no-prompt',
        switchUser: 'dm-tool switch-to-greeter',
        screenshot: commandExists('flameshot') ? 'flameshot gui' : 'gnome-screenshot -i',
    };
    if (allowed[command]) Util.spawnCommandLine(allowed[command]);
}

function createIcon(iconName, styleClass) {
    return new St.Icon({ icon_name: iconName, icon_type: St.IconType.SYMBOLIC, style_class: styleClass });
}

function createTileIconSlot(iconName) {
    const slot = new St.Bin({ style_class: 'caramos-cc-tile-icon-slot' });
    const icon = createIcon(iconName, 'caramos-cc-tile-icon');
    slot.set_child(icon);
    return { slot, icon };
}

function createRoundButton(iconName, command, onClick) {
    const button = new St.Button({ style_class: 'caramos-cc-round-button', reactive: true, can_focus: true, track_hover: true });
    button.set_child(createIcon(iconName, 'caramos-cc-round-icon'));
    button.connect('clicked', () => {
        if (onClick) onClick();
        else spawnAllowed(command);
    });
    return button;
}

function createHeaderPill(iconName, text, onClick) {
    const button = new St.Button({ style_class: 'caramos-cc-battery-pill', reactive: true, can_focus: true, track_hover: true });
    const row = new St.BoxLayout({ vertical: false });
    row.add_child(createIcon(iconName, 'caramos-cc-pill-icon'));
    row.add_child(new St.Label({ text, style_class: 'caramos-cc-pill-label', y_align: Clutter.ActorAlign.CENTER }));
    button.set_child(row);
    button.connect('clicked', onClick);
    return button;
}

function createSliderRow(iconName, _labelText, initialValue, onChanged) {
    const row = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-slider-row' });
    row.add_child(createIcon(iconName, 'caramos-cc-slider-icon'));

    const slider = new PopupMenu.PopupSliderMenuItem(initialValue / 100);
    slider.actor.add_style_class_name('caramos-cc-slider-item');
    slider.actor.set_x_expand(true);
    slider.connect('value-changed', (_item, value) => onChanged(Math.round(value * 100)));
    row.add_child(slider.actor);

    return { actor: row, slider, enabled: true };
}

function setSliderEnabled(row, enabled) {
    row.enabled = enabled;
    if (enabled) {
        row.actor.remove_style_class_name('caramos-cc-disabled');
    } else {
        row.actor.add_style_class_name('caramos-cc-disabled');
    }
}

function createSplitTile(iconName, title, subtitle, active, onToggle, onExpand) {
    const wrapper = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-split-wrapper', x_expand: true, x_align: Clutter.ActorAlign.FILL });
    const tile = new St.BoxLayout({
        vertical: false,
        style_class: active ? 'caramos-cc-split-tile caramos-cc-tile-active' : 'caramos-cc-split-tile',
        x_expand: true,
        x_align: Clutter.ActorAlign.FILL,
    });

    const mainButton = new St.Button({ style_class: 'caramos-cc-split-main', reactive: true, can_focus: true, track_hover: true, x_expand: true, x_align: Clutter.ActorAlign.FILL });
    const row = new St.BoxLayout({ vertical: false, x_align: Clutter.ActorAlign.FILL, x_expand: true });
    const iconSlot = createTileIconSlot(iconName);
    row.add_child(iconSlot.slot);

    const labels = new St.BoxLayout({ vertical: true, y_align: Clutter.ActorAlign.CENTER, x_align: Clutter.ActorAlign.START, x_expand: true });
    const titleLabel = new St.Label({ text: title, style_class: 'caramos-cc-tile-title', x_align: Clutter.ActorAlign.START });
    const subtitleLabel = new St.Label({ text: subtitle, style_class: 'caramos-cc-tile-subtitle', x_align: Clutter.ActorAlign.START });
    titleLabel.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    subtitleLabel.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    labels.add_child(titleLabel);
    labels.add_child(subtitleLabel);
    row.add_child(labels);
    mainButton.set_child(row);
    mainButton.connect('clicked', onToggle);

    const arrowButton = new St.Button({ style_class: 'caramos-cc-split-arrow', reactive: true, can_focus: true, track_hover: true });
    arrowButton.set_child(createIcon('pan-end-symbolic', 'caramos-cc-arrow-icon'));
    arrowButton.connect('clicked', onExpand);

    tile.add_child(mainButton);
    tile.add_child(arrowButton);
    wrapper.add_child(tile);

    return { actor: wrapper, tile, titleLabel, subtitleLabel, icon: iconSlot.icon, iconSlot: iconSlot.slot, normalIconName: iconName };
}

function createSimpleTile(iconName, title, subtitle, active, onClick) {
    const wrapper = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-split-wrapper', x_expand: true, x_align: Clutter.ActorAlign.FILL });
    const button = new St.Button({
        style_class: active ? 'caramos-cc-simple-tile caramos-cc-tile-active' : 'caramos-cc-simple-tile',
        reactive: true,
        can_focus: true,
        track_hover: true,
        x_expand: true,
        x_align: Clutter.ActorAlign.FILL,
    });
    const row = new St.BoxLayout({ vertical: false, x_align: Clutter.ActorAlign.FILL, x_expand: true });
    const iconSlot = createTileIconSlot(iconName);
    row.add_child(iconSlot.slot);
    const labels = new St.BoxLayout({ vertical: true, y_align: Clutter.ActorAlign.CENTER, x_align: Clutter.ActorAlign.START, x_expand: true });
    const titleLabel = new St.Label({ text: title, style_class: 'caramos-cc-tile-title', x_align: Clutter.ActorAlign.START });
    const subtitleLabel = new St.Label({ text: subtitle, style_class: 'caramos-cc-tile-subtitle', x_align: Clutter.ActorAlign.START });
    titleLabel.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    subtitleLabel.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    labels.add_child(titleLabel);
    labels.add_child(subtitleLabel);
    row.add_child(labels);
    button.set_child(row);
    button.connect('clicked', onClick);
    wrapper.add_child(button);
    return { actor: wrapper, tile: button, titleLabel, subtitleLabel, icon: iconSlot.icon, iconSlot: iconSlot.slot, normalIconName: iconName };
}

function createListRow(text, onClick) {
    const button = new St.Button({ style_class: 'caramos-cc-list-row', reactive: true, can_focus: true, track_hover: true, x_expand: true });
    button.set_child(new St.Label({ text, style_class: 'caramos-cc-list-label' }));
    if (onClick) button.connect('clicked', onClick);
    return button;
}

// Map a Wi‑Fi signal strength (0-100) to a symbolic network icon so the list
// looks like a real control centre instead of "NN%" text.
function wifiSignalIcon(signal, secure) {
    const s = parseInt(signal, 10);
    let level = 'weak';
    if (s >= 75) level = 'excellent';
    else if (s >= 55) level = 'good';
    else if (s >= 35) level = 'ok';
    return `network-wireless-signal-${level}${secure ? '-secure' : ''}-symbolic`;
}

// A rich list row: leading symbolic icon, label, optional trailing symbolic
// icon (e.g. a lock or a checkmark). Used by the Wi‑Fi / Bluetooth overlays.
function createIconRow(leadingIcon, text, trailingIcon, onClick) {
    const button = new St.Button({ style_class: 'caramos-cc-list-row', reactive: true, can_focus: true, track_hover: true, x_expand: true, x_align: Clutter.ActorAlign.FILL });
    const row = new St.BoxLayout({ vertical: false, x_expand: true, x_align: Clutter.ActorAlign.START });
    if (leadingIcon) row.add_child(createIcon(leadingIcon, 'caramos-cc-row-lead-icon'));
    const label = new St.Label({ text, style_class: 'caramos-cc-list-label', y_align: Clutter.ActorAlign.CENTER, x_align: Clutter.ActorAlign.START });
    label.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    row.add_child(label);
    row.add_child(new St.Widget({ x_expand: true }));
    if (trailingIcon) row.add_child(createIcon(trailingIcon, 'caramos-cc-row-trail-icon'));
    button.set_child(row);
    if (onClick) button.connect('clicked', onClick);
    return button;
}

class CaramOSControlCenterApplet extends Applet.IconApplet {
    constructor(metadata, orientation, panelHeight, instanceId) {
        super(orientation, panelHeight, instanceId);
        this.set_applet_tooltip(_('Trung tâm điều khiển CaramOS'));
        this.actor.add_style_class_name('caramos-cc-panel-button');

        this._volumeNorm = 65536;
        this._volumeMax = this._volumeNorm;
        this._output = null;
        this._input = null;
        this._outputVolumeChangedId = 0;
        this._inputVolumeChangedId = 0;
        this._outputMutedChangedId = 0;
        this._inputMutedChangedId = 0;
        this._streams = [];
        this._recordingAppsNum = 0;
        this._outputVolumeApplyId = 0;
        this._inputVolumeApplyId = 0;
        this._outputVolumePending = null;
        this._inputVolumePending = null;
        this._updatingSliders = false;
        this._brightnessProxy = null;
        this._brightnessReady = false;
        this._brightnessChanging = false;
        this._powerMenuVisible = false;
        this._bluetoothPowered = null;
        this._bluetoothSignalId = 0;

        this._nightLightSettings = null;
        try {
            this._nightLightSettings = Gio.Settings.new(NIGHT_LIGHT_SCHEMA);
        } catch (e) {
            global.logError(e);
        }

        this._control = new Cvc.MixerControl({ name: 'CaramOS Control Center' });
        this._control.connect('state-changed', () => this._onMixerStateChanged());
        this._control.connect('active-output-update', () => this._readOutput());
        this._control.connect('active-input-update', () => this._readInput());
        this._control.connect('stream-added', (...args) => this._onStreamAdded(...args));
        this._control.connect('stream-removed', (...args) => this._onStreamRemoved(...args));
        this._volumeNorm = this._control.get_vol_max_norm();
        this._volumeMax = this._volumeNorm;

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menu.actor.add_style_class_name('caramos-cc-popup');
        if (this.menu.box) this.menu.box.add_style_class_name('caramos-cc-popup-box');
        this.menu._calculatePosition = () => this._calculateMenuPosition();
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (open) this._alignMenuToRightEdge();
        });
        this.menuManager.addMenu(this.menu);

        this._buildPanelIndicator();
        this._buildMenu();
        this._control.open();
        this._initBrightness();
        this._watchBluetoothStatus();
        this._refresh();
        this._refreshId = Mainloop.timeout_add_seconds(REFRESH_SECONDS, () => {
            this._refresh();
            return true;
        });
    }

    on_applet_removed_from_panel() {
        if (this._refreshId) {
            Mainloop.source_remove(this._refreshId);
            this._refreshId = 0;
        }
        if (this._bluetoothSignalId) {
            Gio.DBus.session.signal_unsubscribe(this._bluetoothSignalId);
            this._bluetoothSignalId = 0;
        }
        if (this._outputVolumeApplyId) Mainloop.source_remove(this._outputVolumeApplyId);
        if (this._inputVolumeApplyId) Mainloop.source_remove(this._inputVolumeApplyId);
        if (this._menuAlignId) Mainloop.source_remove(this._menuAlignId);
        this._outputVolumeApplyId = 0;
        this._inputVolumeApplyId = 0;
        this._menuAlignId = 0;
        [this._wifiTile, this._bluetoothTile, this._nightLightTile].forEach(tile => {
            if (tile) this._setTileLoading(tile, false);
        });
    }

    on_applet_clicked() {
        this._closeSubmenus();
        this.menu.toggle();
        Mainloop.idle_add(() => {
            this._refresh();
            this._alignMenuToRightEdge();
            return false;
        });
    }

    _alignMenuToRightEdge() {
        if (!this.menu || !this.menu.actor || !this.menu.isOpen) return;

        this._positionMenuSurface();
        Mainloop.idle_add(() => {
            this._positionMenuSurface();
            return false;
        });
        if (this._menuAlignId) Mainloop.source_remove(this._menuAlignId);
        this._menuAlignTicks = 0;
        this._menuAlignId = Mainloop.timeout_add(80, () => {
            if (!this.menu || !this.menu.isOpen || this._menuAlignTicks >= 12) {
                this._menuAlignId = 0;
                return false;
            }
            this._menuAlignTicks++;
            this._positionMenuSurface();
            return true;
        });
    }

    _positionMenuSurface() {
        try {
            if (!this.menu || !this.menu.actor || !this.menu.isOpen) return;
            const [x, y] = this._calculateMenuPosition();
            this.menu.actor.set_position(x, y);
        } catch (e) {
            global.logError(e);
        }
    }

    _calculateMenuPosition() {
        const actor = this.menu.actor;
        if (!actor.visible && this.menu.box) this.menu.box.show();

        const [minWidth, minHeight, natWidth, natHeight] = actor.get_preferred_size();
        let monitor = Main.layoutManager.primaryMonitor;
        if (this.actor && Main.layoutManager.findMonitorForActor) {
            monitor = Main.layoutManager.findMonitorForActor(this.actor) || monitor;
        }
        if (!monitor) return [actor.x, actor.y];

        let x1 = monitor.x;
        let x2 = monitor.x + monitor.width;
        let y1 = monitor.y;
        let y2 = monitor.y + monitor.height;
        if (Main.panelManager && Main.panelManager.getPanelsInMonitor && monitor.index !== undefined) {
            const panels = Main.panelManager.getPanelsInMonitor(monitor.index);
            panels.forEach(panel => {
                if (!panel.getIsVisible || !panel.getIsVisible()) return;
                switch (panel.panelPosition) {
                    case 0:
                        y1 += panel.actor.height;
                        break;
                    case 1:
                        y2 -= panel.actor.height;
                        break;
                    case 2:
                        x1 += panel.actor.width;
                        break;
                    case 3:
                        x2 -= panel.actor.width;
                        break;
                }
            });
        }

        const sourceBox = this.actor.get_transformed_position ? this.actor.get_transformed_position() : [x2, y2];
        const sourceY = sourceBox[1] || y2;
        const menuWidth = natWidth || actor.width || minWidth;
        const menuHeight = natHeight || actor.height || minHeight;
        const x = Math.max(x1, x2 - menuWidth - POPUP_EDGE_MARGIN);
        const y = Math.max(y1, Math.min(sourceY - menuHeight, y2 - menuHeight));
        return [Math.round(x), Math.round(y)];
    }

    _buildPanelIndicator() {
        const box = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-indicator' });
        this._panelNetworkIcon = createIcon('network-wireless-symbolic', 'caramos-cc-panel-icon');
        this._panelVpnIcon = createIcon('network-vpn-symbolic', 'caramos-cc-panel-icon');
        this._panelMicIcon = createIcon('microphone-sensitivity-high-symbolic', 'caramos-cc-panel-icon');
        this._panelVolumeIcon = createIcon('audio-volume-high-symbolic', 'caramos-cc-panel-icon');
        this._panelBatteryIcon = createIcon('battery-full-symbolic', 'caramos-cc-panel-icon');
        this._panelBatteryLabel = new St.Label({
            text: '--%',
            style_class: 'caramos-cc-panel-battery',
            y_align: Clutter.ActorAlign.CENTER,
        });

        box.add_child(this._panelNetworkIcon);
        box.add_child(this._panelVpnIcon);
        box.add_child(this._panelMicIcon);
        box.add_child(this._panelVolumeIcon);
        box.add_child(this._panelBatteryIcon);
        box.add_child(this._panelBatteryLabel);
        this.actor.add_child(box);
    }

    _buildMenu() {
        this.menu.removeAll();
        const section = new PopupMenu.PopupMenuSection();

        // Stack: main content + modal layer. Wi‑Fi/Bluetooth lists are inline
        // expansions inside the panel; modal overlay is only for dialogs.
        const root = new St.Widget({ layout_manager: new Clutter.BinLayout(), x_expand: true, y_expand: true });

        const container = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-container', x_expand: true, y_expand: true });

        const header = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-header' });
        this._batteryPill = createHeaderPill('battery-full-symbolic', '--%', () => spawnAllowed('powerSettings'));
        header.add_child(this._batteryPill);
        header.add_child(new St.Widget({ x_expand: true }));
        header.add_child(createRoundButton('camera-photo-symbolic', 'screenshot'));
        header.add_child(createRoundButton('preferences-system-symbolic', 'settings'));
        header.add_child(createRoundButton('system-lock-screen-symbolic', 'lock'));
        header.add_child(createRoundButton('system-shutdown-symbolic', null, () => this._openPowerOverlay()));
        this._header = header;
        container.add_child(header);

        this._volumeRow = createSliderRow('audio-volume-high-symbolic', 'Âm lượng', 50, value => {
            if (!this._updatingSliders) this._setStreamVolume(this._output, value);
        });
        this._micRow = createSliderRow('microphone-sensitivity-high-symbolic', 'Mic', 50, value => {
            if (!this._updatingSliders) this._setStreamVolume(this._input, value);
        });
        this._brightnessRow = createSliderRow('display-brightness-symbolic', 'Ánh sáng', 50, value => this._setBrightness(value));
        container.add_child(this._volumeRow.actor);
        container.add_child(this._micRow.actor);
        container.add_child(this._brightnessRow.actor);

        this._wifiTile = createSplitTile('network-wireless-symbolic', _('Wi‑Fi'), _('Đang kiểm tra'), true, () => this._toggleWifi(), () => this._openWifiOverlay());
        this._vpnTile = createSimpleTile('network-vpn-symbolic', _('VPN'), _('Chưa kết nối'), false, () => this._toggleVpn());
        this._wifiRow = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-grid-row', x_expand: true, x_align: Clutter.ActorAlign.FILL });
        this._wifiRow.add_child(this._wifiTile.actor);
        this._wifiRow.add_child(this._vpnTile.actor);

        this._bluetoothTile = createSplitTile('bluetooth-symbolic', _('Bluetooth'), _('Đang kiểm tra'), false, () => this._toggleBluetooth(), () => this._openBluetoothOverlay());
        this._nightLightTile = createSimpleTile('night-light-symbolic', _('Ánh sáng đêm'), _('Bật/tắt Night Light'), false, () => this._toggleNightLight());
        this._bluetoothRow = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-grid-row', x_expand: true, x_align: Clutter.ActorAlign.FILL });
        this._bluetoothRow.add_child(this._bluetoothTile.actor);
        this._bluetoothRow.add_child(this._nightLightTile.actor);

        container.add_child(this._wifiRow);
        container.add_child(this._bluetoothRow);

        this._container = container;
        this._expandedPanel = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-expanded-panel', x_expand: true });
        this._expandedPanel.hide();

        root.add_child(container);
        root.add_child(this._buildOverlay());

        section.actor.add_child(root);
        this.menu.addMenuItem(section);
    }

    // The overlay layer: a dim, click-to-dismiss backdrop with a centred card.
    // _openOverlay() fills the card; _closeOverlay() hides the whole layer.
    _buildOverlay() {
        this._overlay = new St.Widget({ layout_manager: new Clutter.BinLayout(), x_expand: true, y_expand: true });
        this._overlay.hide();

        const backdrop = new St.Button({ style_class: 'caramos-cc-overlay-backdrop', x_expand: true, y_expand: true });
        backdrop.connect('clicked', () => this._closeOverlay());
        this._overlay.add_child(backdrop);

        this._overlayCard = new St.BoxLayout({
            vertical: true,
            style_class: 'caramos-cc-overlay-card',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._overlay.add_child(this._overlayCard);
        return this._overlay;
    }

    // Open the overlay with a titled card. fillFn(listBox) populates the body.
    _openOverlay(iconName, title, fillFn) {
        this._overlayCard.destroy_all_children();

        const head = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-overlay-head' });
        head.add_child(createIcon(iconName, 'caramos-cc-overlay-head-icon'));
        head.add_child(new St.Label({ text: title, style_class: 'caramos-cc-overlay-title', y_align: Clutter.ActorAlign.CENTER }));
        head.add_child(new St.Widget({ x_expand: true }));
        const closeBtn = new St.Button({ style_class: 'caramos-cc-overlay-close', reactive: true, can_focus: true, track_hover: true });
        closeBtn.set_child(createIcon('window-close-symbolic', 'caramos-cc-overlay-close-icon'));
        closeBtn.connect('clicked', () => this._closeOverlay());
        head.add_child(closeBtn);
        this._overlayCard.add_child(head);

        const body = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-overlay-body' });
        this._overlayCard.add_child(body);
        this._overlayBody = body;
        fillFn(body);

        this._overlay.show();
    }

    _closeOverlay() {
        if (this._overlay) this._overlay.hide();
        this._overlayBody = null;
        this._wifiPasswordSsid = null;
    }

    _toggleInlinePanel(kind, iconName, title, fillFn, anchorRow) {
        if (this._expandedKind === kind && this._expandedPanel && this._expandedPanel.visible) {
            this._closeInlinePanel();
            return;
        }
        this._openInlinePanel(kind, iconName, title, fillFn, anchorRow);
    }

    _openInlinePanel(kind, iconName, title, fillFn, anchorRow) {
        if (!this._expandedPanel || !this._container || !anchorRow) return;
        this._expandedPanel.destroy_all_children();
        this._expandedKind = kind;

        const card = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-card', x_expand: true });
        const head = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-inline-head' });
        head.add_child(createIcon(iconName, 'caramos-cc-inline-head-icon'));
        head.add_child(new St.Label({ text: title, style_class: 'caramos-cc-inline-title', y_align: Clutter.ActorAlign.CENTER }));
        head.add_child(new St.Widget({ x_expand: true }));
        const closeBtn = new St.Button({ style_class: 'caramos-cc-inline-close', reactive: true, can_focus: true, track_hover: true });
        closeBtn.set_child(createIcon('window-close-symbolic', 'caramos-cc-inline-close-icon'));
        closeBtn.connect('clicked', () => this._closeInlinePanel());
        head.add_child(closeBtn);
        card.add_child(head);

        const body = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-body', x_expand: true });
        card.add_child(body);
        this._expandedBody = body;
        this._expandedPanel.add_child(card);

        // Re-parent expandedPanel to sit immediately below the anchor row.
        const parent = this._expandedPanel.get_parent();
        if (parent) parent.remove_child(this._expandedPanel);
        const children = this._container.get_children();
        const anchorIdx = children.indexOf(anchorRow);
        if (anchorIdx >= 0) {
            this._container.insert_child_at_index(this._expandedPanel, anchorIdx + 1);
        } else {
            this._container.add_child(this._expandedPanel);
        }

        this._anchorRow = anchorRow;
        fillFn(body);

        // Entrance animation: fade + slight slide down.
        this._expandedPanel.opacity = 0;
        this._expandedPanel.set_translation(0, -6, 0);
        this._expandedPanel.show();
        this._expandedPanel.ease({
            opacity: 255,
            translation_y: 0,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        this._applyDim(true);
    }

    _closeInlinePanel() {
        if (!this._expandedPanel || !this._expandedPanel.visible) {
            this._expandedBody = null;
            this._expandedKind = null;
            this._anchorRow = null;
            return;
        }
        this._applyDim(false);
        this._expandedPanel.ease({
            opacity: 0,
            translation_y: -6,
            duration: 140,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                this._expandedPanel.destroy_all_children();
                this._expandedPanel.hide();
                this._expandedPanel.set_translation(0, 0, 0);
                this._expandedPanel.opacity = 255;
            },
        });
        this._expandedBody = null;
        this._expandedKind = null;
        this._anchorRow = null;
    }

    _applyDim(dim) {
        if (!this._container) return;
        const anchor = this._anchorRow;
        const duration = 180;
        const mode = Clutter.AnimationMode.EASE_OUT_QUAD;
        this._container.get_children().forEach(child => {
            const shouldStayBright = !dim || child === anchor || child === this._expandedPanel;
            child.ease({ opacity: shouldStayBright ? 255 : 128, duration, mode });
        });
    }

    _returnToWifiInlinePanel() {
        this._closeOverlay();
        this._openInlinePanel('wifi', 'network-wireless-symbolic', _('Wi‑Fi'), body => this._fillWifiList(body), this._wifiRow);
    }

    _openPowerOverlay() {
        this._toggleInlinePanel('power', 'system-shutdown-symbolic', _('Nguồn'),
            body => this._fillPowerList(body), this._header);
    }

    _fillPowerList(body) {
        body.add_child(createIconRow('media-playback-pause-symbolic', _('Tạm ngưng'), null, () => this._runPowerAction('suspend')));
        body.add_child(createIconRow('view-refresh-symbolic', _('Khởi động lại…'), null, () => this._runPowerAction('restart')));
        body.add_child(createIconRow('system-shutdown-symbolic', _('Tắt máy…'), null, () => this._runPowerAction('poweroff')));
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        body.add_child(createIconRow('system-log-out-symbolic', _('Đăng xuất'), null, () => this._runPowerAction('logout')));
        body.add_child(createIconRow('system-users-symbolic', _('Chuyển người dùng…'), null, () => this._runPowerAction('switchUser')));
    }

    _closeSubmenus() {
        if (this._menuAlignId) {
            Mainloop.source_remove(this._menuAlignId);
            this._menuAlignId = 0;
        }
        this._closeOverlay();
        this._closeInlinePanel();
    }

    _runPowerAction(action) {
        this._closeInlinePanel();
        spawnAllowed(action);
    }

    _applyStreamVolume(stream, value) {
        if (!stream || !this._volumeNorm) return;
        const volume = Math.round(this._volumeNorm * value / 100);
        stream.volume = Math.max(0, Math.min(this._volumeMax, volume));
        stream.push_volume();
        if (stream.is_muted && value > 0) stream.change_is_muted(false);
    }

    _setStreamVolume(stream, value) {
        if (!stream || !this._volumeNorm) return;
        const isOutput = stream === this._output;
        const sourceKey = isOutput ? '_outputVolumeApplyId' : '_inputVolumeApplyId';
        const pendingKey = isOutput ? '_outputVolumePending' : '_inputVolumePending';

        this[pendingKey] = value;

        if (this[sourceKey]) {
            Mainloop.source_remove(this[sourceKey]);
            this[sourceKey] = 0;
        }

        this[sourceKey] = Mainloop.timeout_add(90, () => {
            const pending = this[pendingKey];
            this[pendingKey] = null;
            this[sourceKey] = 0;
            this._applyStreamVolume(stream, pending);
            return false;
        });
    }

    _streamPercent(stream) {
        if (!stream || stream.is_muted || !this._volumeNorm) return 0;
        return Math.max(0, Math.min(100, Math.round(stream.volume / this._volumeNorm * 100)));
    }

    _volumeIconName(percent, muted) {
        if (muted || percent <= 0) return 'audio-volume-muted-symbolic';
        if (percent < 34) return 'audio-volume-low-symbolic';
        if (percent < 67) return 'audio-volume-medium-symbolic';
        return 'audio-volume-high-symbolic';
    }

    _onMixerStateChanged() {
        if (this._control.get_state() === Cvc.MixerControlState.READY) {
            this._readOutput();
            this._readInput();
            this._refresh();
        }
    }

    _readOutput() {
        if (this._output && this._outputVolumeChangedId) this._output.disconnect(this._outputVolumeChangedId);
        if (this._output && this._outputMutedChangedId) this._output.disconnect(this._outputMutedChangedId);
        this._outputVolumeChangedId = 0;
        this._outputMutedChangedId = 0;
        this._output = this._control.get_default_sink();
        if (this._output) {
            this._outputVolumeChangedId = this._output.connect('notify::volume', () => this._refresh());
            this._outputMutedChangedId = this._output.connect('notify::is-muted', () => this._refresh());
        }
    }

    _readInput() {
        if (this._input && this._inputVolumeChangedId) this._input.disconnect(this._inputVolumeChangedId);
        if (this._input && this._inputMutedChangedId) this._input.disconnect(this._inputMutedChangedId);
        this._inputVolumeChangedId = 0;
        this._inputMutedChangedId = 0;
        this._input = this._control.get_default_source();
        if (this._input) {
            this._inputVolumeChangedId = this._input.connect('notify::volume', () => this._refresh());
            this._inputMutedChangedId = this._input.connect('notify::is-muted', () => this._refresh());
        }
    }

    _onStreamAdded(control, id) {
        const stream = control.lookup_stream_id(id);
        if (stream instanceof Cvc.MixerSourceOutput) {
            this._streams.push({ id, type: 'SourceOutput' });
            this._recordingAppsNum++;
            this._refresh();
        }
    }

    _onStreamRemoved(control, id) {
        for (let i = 0; i < this._streams.length; i++) {
            if (this._streams[i].id === id) {
                if (this._streams[i].type === 'SourceOutput') {
                    this._recordingAppsNum = Math.max(0, this._recordingAppsNum - 1);
                }
                this._streams.splice(i, 1);
                this._refresh();
                break;
            }
        }
    }

    _initBrightness() {
        try {
            Interfaces.getDBusProxyAsync(BRIGHTNESS_BUS_NAME, Lang.bind(this, function (proxy, error) {
                if (error || !proxy) {
                    this._disableBrightness();
                    return;
                }
                this._brightnessProxy = proxy;
                this._brightnessProxy.GetPercentageRemote(Lang.bind(this, function (value, getError) {
                    if (getError) {
                        this._disableBrightness();
                        return;
                    }
                    this._brightnessReady = true;
                    this._updateBrightness(value);
                    this._brightnessProxy.connectSignal('Changed', () => this._readBrightness());
                }));
            }));
        } catch (e) {
            global.logError(e);
            this._disableBrightness();
        }
    }

    _disableBrightness() {
        this._brightnessReady = false;
        if (this._brightnessRow) {
            setSliderEnabled(this._brightnessRow, false);
        }
    }

    _readBrightness() {
        if (!this._brightnessReady || !this._brightnessProxy || this._brightnessChanging) return;
        this._brightnessProxy.GetPercentageRemote(Lang.bind(this, function (value, error) {
            if (!error) this._updateBrightness(value);
        }));
    }

    _updateBrightness(value) {
        const percent = Math.max(0, Math.min(100, Math.round(value)));
        setSliderEnabled(this._brightnessRow, true);
        this._brightnessRow.slider.setValue(percent / 100);
    }

    _setBrightness(value) {
        if (!this._brightnessReady || !this._brightnessProxy) {
            this._disableBrightness();
            return;
        }
        this._brightnessChanging = true;
        const percent = Math.max(0, Math.min(100, value));
        this._brightnessProxy.SetPercentageRemote(percent, Lang.bind(this, function () {
            this._brightnessChanging = false;
            this._updateBrightness(percent);
        }));
    }

    _setTileLoading(tile, loading) {
        if (!tile.iconSlot) return;
        const frames = ['◐', '◓', '◑', '◒'];
        if (loading) {
            if (!tile.loadingLabel) {
                tile.loadingLabel = new St.Label({ text: frames[0], style_class: 'caramos-cc-loading-label' });
            }
            tile.iconSlot.set_child(tile.loadingLabel);
            if (!tile.loadingId) {
                tile.loadingFrame = 0;
                tile.loadingId = Mainloop.timeout_add(100, () => {
                    tile.loadingFrame = (tile.loadingFrame + 1) % frames.length;
                    tile.loadingLabel.set_text(frames[tile.loadingFrame]);
                    return true;
                });
            }
        } else {
            if (tile.loadingId) {
                Mainloop.source_remove(tile.loadingId);
                tile.loadingId = 0;
            }
            tile.loadingFrame = 0;
            tile.iconSlot.set_child(tile.icon);
            tile.icon.set_icon_name(tile.normalIconName);
        }
    }

    _setSplitTileState(tile, active, loading) {
        tile.tile.set_style_class_name(`caramos-cc-split-tile${active ? ' caramos-cc-tile-active' : ''}${loading ? ' caramos-cc-loading' : ''}`);
        this._setTileLoading(tile, loading);
    }

    _setSimpleTileState(tile, active, loading) {
        tile.tile.set_style_class_name(`caramos-cc-simple-tile${active ? ' caramos-cc-tile-active' : ''}${loading ? ' caramos-cc-loading' : ''}`);
        this._setTileLoading(tile, loading);
    }

    _toggleNightLight() {
        if (!this._nightLightSettings) return;
        const enabled = this._nightLightSettings.get_boolean(NIGHT_LIGHT_KEY);
        const target = !enabled;
        this._setSimpleTileState(this._nightLightTile, target, true);
        this._nightLightSettings.set_boolean(NIGHT_LIGHT_KEY, target);
        Mainloop.timeout_add_seconds(1, () => {
            this._refresh();
            return false;
        });
    }

    _openSettings(command) {
        if (this.menu && this.menu.isOpen) this.menu.close();
        spawnAllowed(command);
    }

    _toggleWifi() {
        if (!commandExists('nmcli')) {
            this._openSettings('networkSettings');
            return;
        }
        const enabled = safeCommandOutput(['nmcli', 'radio', 'wifi'], 1) === 'enabled';
        const target = !enabled;
        this._setSplitTileState(this._wifiTile, target, true);
        spawnAsync(`nmcli radio wifi ${target ? 'on' : 'off'}`);
        Mainloop.timeout_add_seconds(1, () => {
            this._refresh();
            return false;
        });
    }

    _setBluetoothUi(powered) {
        this._bluetoothPowered = powered;
        if (!this._bluetoothTile) return;
        this._bluetoothTile.subtitleLabel.set_text(powered ? _('Bật') : _('Tắt'));
        this._setSplitTileState(this._bluetoothTile, powered, false);
    }

    _watchBluetoothStatus() {
        try {
            this._bluetoothSignalId = Gio.DBus.session.signal_subscribe(
                'org.blueman.Applet',
                'org.blueman.Applet',
                'BluetoothStatusChanged',
                '/org/blueman/Applet',
                null,
                Gio.DBusSignalFlags.NONE,
                (_connection, _sender, _objectPath, _interfaceName, _signalName, parameters) => {
                    const unpacked = parameters.deep_unpack();
                    if (unpacked.length > 0) this._setBluetoothUi(!!unpacked[0]);
                }
            );
        } catch (e) {
            global.logError(e);
        }
    }

    _bluemanBluetoothPowered() {
        if (!commandExists('busctl')) return null;
        const status = safeCommandOutput([
            'busctl', '--user', 'call',
            'org.blueman.Applet',
            '/org/blueman/Applet',
            'org.blueman.Applet',
            'GetBluetoothStatus',
        ], 1);
        if (status.indexOf('true') !== -1) return true;
        if (status.indexOf('false') !== -1) return false;
        return null;
    }

    _bluetoothTargetState() {
        const powered = this._bluemanBluetoothPowered();
        if (powered !== null) return !powered;
        const state = safeCommandOutput(['bluetoothctl', 'show'], 1);
        return state.indexOf('Powered: yes') === -1;
    }

    _refreshBluetoothSoon() {
        Mainloop.timeout_add_seconds(1, () => {
            this._refresh();
            return false;
        });
    }

    _toggleBluetooth() {
        const target = this._bluetoothTargetState();
        this._setSplitTileState(this._bluetoothTile, target, true);
        spawnAsync(`busctl --user call org.blueman.Applet /org/blueman/Applet org.blueman.Applet SetBluetoothStatus b ${target ? 'true' : 'false'}`);
        this._refreshBluetoothSoon();
    }

    _toggleVpn() {
        this._openSettings('networkSettings');
    }

    _openWifiOverlay() {
        this._toggleInlinePanel('wifi', 'network-wireless-symbolic', _('Wi‑Fi'), body => this._fillWifiList(body), this._wifiRow);
    }

    _openBluetoothOverlay() {
        this._toggleInlinePanel('bluetooth', 'bluetooth-symbolic', _('Bluetooth'), body => this._fillBluetoothList(body), this._bluetoothRow);
    }

    _savedWifiProfiles() {
        // Names of saved 802-11-wireless connection profiles, so we know which
        // networks can be joined without asking for a password again.
        const output = safeCommandOutput(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show'], 2);
        const saved = {};
        output.split('\n').forEach(line => {
            const idx = line.lastIndexOf(':');
            if (idx === -1) return;
            const name = line.slice(0, idx);
            const type = line.slice(idx + 1);
            if (type === '802-11-wireless') saved[name] = true;
        });
        return saved;
    }

    _fillWifiList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();
        this._wifiPasswordSsid = null;

        const output = safeCommandOutput(['nmcli', '-t', '-f', 'SSID,SECURITY,SIGNAL,IN-USE', 'device', 'wifi', 'list'], 4);
        const rows = output.split('\n').filter(line => line.trim());
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });

        if (!rows.length) {
            list.add_child(new St.Label({ text: _('Không thấy mạng Wi‑Fi'), style_class: 'caramos-cc-expand-empty' }));
        } else {
            const saved = this._savedWifiProfiles();
            const seen = {};
            let shown = 0;
            for (let i = 0; i < rows.length && shown < WIFI_LIST_LIMIT; i++) {
                const parts = rows[i].split(':');
                const ssid = parts[0] || '';
                const secure = parts[1] || '';
                const signal = parts[2] || '0';
                const active = parts[3] === '*';
                if (!ssid || seen[ssid]) continue;
                seen[ssid] = true;
                shown++;
                const trailing = active ? 'object-select-symbolic' : null;
                list.add_child(createIconRow(wifiSignalIcon(signal, !!secure), ssid, trailing, () => {
                    this._onWifiRowClicked(ssid, !!secure, active, !!saved[ssid]);
                }));
            }
        }
        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        body.add_child(createIconRow('preferences-system-symbolic', _('Mở cài đặt mạng'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('networkSettings');
        }));
    }

    _onWifiRowClicked(ssid, secure, active, saved) {
        if (active) {
            // Already connected → disconnect this network.
            spawnArgvAsync(['nmcli', 'connection', 'down', 'id', ssid]);
            this._setSplitTileState(this._wifiTile, false, true);
            this._closeInlinePanel();
            this._refreshWifiListSoon();
            return;
        }
        if (!secure || saved) {
            // Open network, or a profile with a stored secret → connect directly.
            this._connectWifi(ssid, null);
            return;
        }
        // Secured and no saved profile → centred password dialog.
        this._showWifiPasswordDialog(ssid);
    }

    _showWifiPasswordDialog(ssid) {
        this._openOverlay('network-wireless-symbolic', _('Nhập mật khẩu'), body => {
            body.add_child(new St.Label({ text: ssid, style_class: 'caramos-cc-password-ssid' }));

            const entry = new St.Entry({ style_class: 'caramos-cc-password-entry', hint_text: _('Mật khẩu'), can_focus: true, x_expand: true });
            const clutterText = entry.get_clutter_text();
            clutterText.set_password_char('●');
            body.add_child(entry);

            let visible = false;
            const showRow = new St.Button({ style_class: 'caramos-cc-password-show', reactive: true, can_focus: true, track_hover: true });
            const showBox = new St.BoxLayout({ vertical: false });
            const showIcon = createIcon('view-reveal-symbolic', 'caramos-cc-row-lead-icon');
            showBox.add_child(showIcon);
            showBox.add_child(new St.Label({ text: _('Hiện mật khẩu'), style_class: 'caramos-cc-list-label', y_align: Clutter.ActorAlign.CENTER }));
            showRow.set_child(showBox);
            showRow.connect('clicked', () => {
                visible = !visible;
                clutterText.set_password_char(visible ? 0 : '●');
                showIcon.set_icon_name(visible ? 'view-conceal-symbolic' : 'view-reveal-symbolic');
            });
            body.add_child(showRow);

            const actions = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-dialog-actions' });
            const cancelBtn = new St.Button({ style_class: 'caramos-cc-dialog-btn', reactive: true, can_focus: true, track_hover: true, x_expand: true });
            cancelBtn.set_child(new St.Label({ text: _('Hủy'), style_class: 'caramos-cc-list-label' }));
            cancelBtn.connect('clicked', () => this._returnToWifiInlinePanel());
            const joinBtn = new St.Button({ style_class: 'caramos-cc-dialog-btn caramos-cc-dialog-btn-primary', reactive: true, can_focus: true, track_hover: true, x_expand: true });
            joinBtn.set_child(new St.Label({ text: _('Kết nối'), style_class: 'caramos-cc-list-label' }));
            const submit = () => {
                const pw = entry.get_text();
                if (pw && pw.length) this._connectWifi(ssid, pw);
            };
            joinBtn.connect('clicked', submit);
            clutterText.connect('activate', submit);
            clutterText.connect('key-press-event', (_a, event) => {
                if (event.get_key_symbol() === Clutter.KEY_Escape) {
                    this._returnToWifiInlinePanel();
                    return Clutter.EVENT_STOP;
                }
                return Clutter.EVENT_PROPAGATE;
            });
            actions.add_child(cancelBtn);
            actions.add_child(joinBtn);
            body.add_child(actions);

            Mainloop.idle_add(() => {
                global.stage.set_key_focus(clutterText);
                return false;
            });
        });
    }

    _connectWifi(ssid, password) {
        const argv = ['nmcli', 'device', 'wifi', 'connect', ssid];
        if (password) {
            argv.push('password');
            argv.push(password);
        }
        spawnArgvAsync(argv);
        this._setSplitTileState(this._wifiTile, true, true);
        this._closeOverlay();
        this._closeInlinePanel();
        this._refreshWifiListSoon();
    }

    _refreshWifiListSoon() {
        Mainloop.timeout_add_seconds(2, () => {
            this._refresh();
            return false;
        });
    }

    _connectedBluetoothMacs() {
        // MAC addresses currently connected, so we can flag them in the list.
        const output = safeCommandOutput(['bluetoothctl', 'devices', 'Connected'], 2);
        const macs = {};
        output.split('\n').forEach(line => {
            const match = line.match(/^Device\s+([0-9A-F:]+)\s+/i);
            if (match) macs[match[1].toUpperCase()] = true;
        });
        return macs;
    }

    _fillBluetoothList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();

        const output = safeCommandOutput(['bluetoothctl', 'devices'], 2);
        const rows = output.split('\n').filter(line => line.trim());
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });

        if (!rows.length) {
            list.add_child(new St.Label({
                text: _('Không có thiết bị khả dụng hoặc đã kết nối'),
                style_class: 'caramos-cc-expand-empty',
            }));
        } else {
            const connected = this._connectedBluetoothMacs();
            let shown = 0;
            for (let i = 0; i < rows.length && shown < BT_LIST_LIMIT; i++) {
                const match = rows[i].match(/^Device\s+([0-9A-F:]+)\s+(.+)$/i);
                if (!match) continue;
                shown++;
                const mac = match[1].toUpperCase();
                const name = match[2];
                const isConnected = !!connected[mac];
                list.add_child(createIconRow(
                    'bluetooth-symbolic',
                    name,
                    isConnected ? 'object-select-symbolic' : null,
                    () => this._onBluetoothRowClicked(mac, isConnected)
                ));
            }
        }

        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        body.add_child(createIconRow('preferences-system-symbolic', _('Cài đặt Bluetooth'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('bluetoothSettings');
        }));
    }

    _onBluetoothRowClicked(mac, isConnected) {
        spawnArgvAsync(['bluetoothctl', isConnected ? 'disconnect' : 'connect', mac]);
        Mainloop.timeout_add_seconds(2, () => {
            if (this._expandedKind === 'bluetooth' && this._expandedBody) this._fillBluetoothList(this._expandedBody);
            return false;
        });
    }

    _activeVpnName() {
        const output = safeCommandOutput(['nmcli', '-t', '-f', 'NAME,TYPE', 'connection', 'show', '--active'], 2);
        const row = output.split('\n').find(line => line.indexOf(':vpn') !== -1 || line.indexOf(':wireguard') !== -1);
        return row ? row.split(':')[0] : '';
    }

    _refresh() {
        const battery = this._readBatteryStatus();
        this._panelBatteryLabel.set_text(battery.percentText);
        this._panelBatteryIcon.set_gicon(Gio.icon_new_for_string(battery.icon));
        this._panelNetworkIcon.set_icon_name(this._readNetworkIcon());
        if (this._batteryPill) {
            this._batteryPill.get_child().get_children()[0].set_gicon(Gio.icon_new_for_string(battery.icon));
            this._batteryPill.get_child().get_children()[1].set_text(battery.percentText);
        }

        const volume = this._streamPercent(this._output);
        const mic = this._streamPercent(this._input);
        this._panelVolumeIcon.set_icon_name(this._volumeIconName(volume, this._output && this._output.is_muted));
        setSliderEnabled(this._volumeRow, this._output !== null);
        setSliderEnabled(this._micRow, this._input !== null);
        this._updatingSliders = true;
        if (!this._outputVolumeApplyId) {
            this._volumeRow.slider.setValue(volume / 100);
        }
        if (!this._inputVolumeApplyId) {
            this._micRow.slider.setValue(mic / 100);
        }
        this._updatingSliders = false;

        if (this._recordingAppsNum > 0) this._panelMicIcon.show();
        else this._panelMicIcon.hide();

        const hasNmcli = commandExists('nmcli');
        const wifiEnabled = hasNmcli && safeCommandOutput(['nmcli', 'radio', 'wifi'], 1) === 'enabled';
        const activeWifi = hasNmcli ? safeCommandOutput(['nmcli', '-t', '-f', 'ACTIVE,SSID', 'device', 'wifi'], 1).split('\n').find(line => line.indexOf('yes:') === 0) : '';
        const wifiName = activeWifi ? activeWifi.replace('yes:', '') : (hasNmcli ? (wifiEnabled ? _('Bật') : _('Tắt')) : _('Không khả dụng'));
        this._wifiTile.subtitleLabel.set_text(wifiName || _('Bật'));
        this._setSplitTileState(this._wifiTile, wifiEnabled, false);

        const activeVpn = hasNmcli ? this._activeVpnName() : '';
        this._vpnTile.subtitleLabel.set_text(hasNmcli ? (activeVpn || _('Chưa kết nối')) : _('Không khả dụng'));
        this._setSimpleTileState(this._vpnTile, !!activeVpn, false);
        if (activeVpn) this._panelVpnIcon.show();
        else this._panelVpnIcon.hide();

        const bluemanPowered = this._bluemanBluetoothPowered();
        const hasBluetooth = bluemanPowered !== null || commandExists('bluetoothctl');
        const btState = bluemanPowered === null && hasBluetooth ? safeCommandOutput(['bluetoothctl', 'show'], 1) : '';
        const btPowered = bluemanPowered !== null ? bluemanPowered : btState.indexOf('Powered: yes') !== -1;
        if (hasBluetooth) {
            this._setBluetoothUi(btPowered);
        } else {
            this._bluetoothTile.subtitleLabel.set_text(_('Không khả dụng'));
            this._setSplitTileState(this._bluetoothTile, false, false);
        }

        if (this._nightLightSettings) {
            const enabled = this._nightLightSettings.get_boolean(NIGHT_LIGHT_KEY);
            this._nightLightTile.subtitleLabel.set_text(enabled ? _('Đang bật') : _('Đang tắt'));
            this._setSimpleTileState(this._nightLightTile, enabled, false);
        } else {
            this._nightLightTile.subtitleLabel.set_text(_('Không khả dụng'));
            this._setSimpleTileState(this._nightLightTile, false, false);
        }
    }

    _readNetworkIcon() {
        const output = safeCommandOutput(['nmcli', '-t', '-f', 'TYPE,STATE', 'device'], 1);
        const rows = output.split('\n');
        if (rows.some(line => line === 'ethernet:connected')) return 'network-wired-symbolic';
        if (rows.some(line => line === 'wifi:connected')) return 'network-wireless-symbolic';
        if (rows.some(line => line.endsWith(':connected'))) return 'network-transmit-receive-symbolic';
        return 'network-offline-symbolic';
    }

    _batteryIconName(percent, charging) {
        if (charging) {
            if (percent <= 10) return 'battery-caution-charging-symbolic';
            if (percent <= 30) return 'battery-low-charging-symbolic';
            if (percent <= 60) return 'battery-good-charging-symbolic';
            if (percent <= 90) return 'battery-good-charging-symbolic';
            return 'battery-full-charging-symbolic';
        }
        if (percent <= 10) return 'battery-empty-symbolic';
        if (percent <= 30) return 'battery-low-symbolic';
        if (percent <= 60) return 'battery-good-symbolic';
        if (percent <= 90) return 'battery-good-symbolic';
        return 'battery-full-symbolic';
    }

    _readBatteryStatus() {
        const output = safeCommandOutput(['upower', '-i', '/org/freedesktop/UPower/devices/DisplayDevice'], 1);
        const percentMatch = output.match(/percentage:\s*(\d+)%/);
        const stateMatch = output.match(/state:\s*(\S+)/);
        const charging = stateMatch ? ['charging', 'pending-charge', 'fully-charged'].indexOf(stateMatch[1]) !== -1 : output.indexOf('-charging-symbolic') !== -1;
        let percent = percentMatch ? parseInt(percentMatch[1], 10) : -1;

        // Some live/VM sessions do not expose UPower DisplayDevice properly.
        // Fall back to kernel power_supply capacity so the panel does not show --%.
        if (percent < 0) percent = this._readBatteryPercentFromSysfs();

        return {
            percentText: percent >= 0 ? `${percent}%` : '--%',
            icon: this._batteryIconName(percent >= 0 ? percent : 0, charging),
        };
    }

    _readBatteryPercentFromSysfs() {
        const names = ['BAT0', 'BAT1', 'BAT2', 'CMB0'];
        for (let i = 0; i < names.length; i++) {
            const path = `/sys/class/power_supply/${names[i]}/capacity`;
            try {
                const [ok, bytes] = GLib.file_get_contents(path);
                if (!ok || !bytes) continue;
                const text = imports.byteArray.toString(bytes).trim();
                const value = parseInt(text, 10);
                if (!isNaN(value)) return Math.max(0, Math.min(100, value));
            } catch (e) {
                // Keep trying other common battery names.
            }
        }
        return -1;
    }
}

function main(metadata, orientation, panelHeight, instanceId) {
    return new CaramOSControlCenterApplet(metadata, orientation, panelHeight, instanceId);
}
