const Applet = imports.ui.applet;
const PopupMenu = imports.ui.popupMenu;
const St = imports.gi.St;
const Clutter = imports.gi.Clutter;
const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;
let NM = null;
try {
    NM = imports.gi.NM;
} catch (e) {
    global.logError(e);
}
let UPowerGlib = null;
try {
    UPowerGlib = imports.gi.UPowerGlib;
} catch (e) {
    global.logError(e);
}
let Cvc = null;
try {
    Cvc = imports.gi.Cvc;
} catch (e) {
    global.logError(e);
}
const Pango = imports.gi.Pango;
const Interfaces = imports.misc.interfaces;
const Lang = imports.lang;
const Mainloop = imports.mainloop;
const Main = imports.ui.main;
const Util = imports.misc.util;

const REFRESH_SECONDS = 15;
const WIFI_LIST_LIMIT = 7;
const BT_LIST_LIMIT = 5;
const VPN_LIST_LIMIT = 7;
const NIGHT_LIGHT_SCHEMA = 'org.cinnamon.settings-daemon.plugins.color';
const NIGHT_LIGHT_KEY = 'night-light-enabled';
const BRIGHTNESS_BUS_NAME = 'org.cinnamon.SettingsDaemon.Power.Screen';
const SESSION_BUS_NAME = 'org.gnome.SessionManager';
const SESSION_OBJECT_PATH = '/org/gnome/SessionManager';
const SESSION_INTERFACE = 'org.cinnamon.SessionManager.EndSessionDialog';
const POPUP_EDGE_MARGIN = 0;
const DEBUG_MARKER = GLib.build_filenamev([GLib.get_home_dir(), '.caramos-cc-debug']);
const DEBUG_LIMIT = 240;
let debugLines = 0;

function ccDebug(topic, fields) {
    if (debugLines >= DEBUG_LIMIT || !GLib.file_test(DEBUG_MARKER, GLib.FileTest.EXISTS)) return;
    const values = [];
    try {
        Object.keys(fields || {}).forEach(key => values.push(`${key}=${fields[key]}`));
    } catch (e) { /* debug boundary */ }
    debugLines++;
    global.log(`[caramos-cc-debug:${debugLines}:${topic}] ${values.join(' ')}`);
}

function ccActorDebug(actor) {
    if (!actor) return 'null';
    try {
        return `visible:${actor.visible},reactive:${actor.reactive},focus:${actor.can_focus},class:${actor.style_class || ''}`;
    } catch (e) {
        return 'unavailable';
    }
}

function ccEventDebug(event) {
    const fields = {};
    try { fields.type = event.type(); } catch (e) { /* toolkit version */ }
    try { fields.button = event.get_button ? event.get_button() : ''; } catch (e) { /* toolkit version */ }
    try { fields.source = ccActorDebug(event.get_source()); } catch (e) { /* toolkit version */ }
    return fields;
}

function _(text) {
    return text;
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
    if (key === 'nmcli -t --escape yes -f UUID,NAME,TYPE connection show') {
        return [
            '11111111-1111-1111-1111-111111111111:wt0:vpn',
            '22222222-2222-2222-2222-222222222222:CaramOS\\: WireGuard:wireguard',
        ].join('\n');
    }
    if (key === 'nmcli -t --escape yes -f UUID,NAME,TYPE connection show --active') {
        return '22222222-2222-2222-2222-222222222222:CaramOS\\: WireGuard:wireguard';
    }
    if (key.indexOf('nmcli connection up uuid') === 0 || key.indexOf('nmcli connection down uuid') === 0) return '';
    if (key === 'nmcli -t -f ACTIVE,SSID device wifi') return 'yes:Saigon Technology';
    if (key === 'nmcli -t --escape no -f DEVICE,TYPE,STATE,CONNECTION device status') {
        return 'wlan0:wifi:connected:Saigon Technology\\nenp0s3:ethernet:disconnected:';
    }
    if (key === 'nmcli -t -f CONNECTIVITY general') return 'full';
    if (key === 'ip -o route show default') return 'default via 10.0.2.2 dev wlan0';

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

function commandExists(binary) {
    return GLib.find_program_in_path(binary) !== null;
}

function networkDeviceStateText(state) {
    const states = {
        0: _('Không xác định'),
        10: _('Không được quản lý'),
        20: _('Không khả dụng'),
        30: _('Đã ngắt kết nối'),
        40: _('Đang chuẩn bị'),
        50: _('Đang cấu hình'),
        60: _('Cần xác thực'),
        70: _('Đang lấy địa chỉ mạng'),
        80: _('Đang kiểm tra kết nối'),
        90: _('Đang hoàn tất'),
        100: _('Đã kết nối'),
        110: _('Đang ngắt kết nối'),
        120: _('Kết nối thất bại'),
    };
    if (typeof state === 'number') return states[state] || _('Không xác định');
    const normalized = String(state || '').toLowerCase();
    const textStates = {
        connected: _('Đã kết nối'),
        disconnected: _('Đã ngắt kết nối'),
        unavailable: _('Không khả dụng'),
        unmanaged: _('Không được quản lý'),
        connecting: _('Đang kết nối'),
        failed: _('Kết nối thất bại'),
    };
    return textStates[normalized] || state || _('Không xác định');
}

function networkConnectivityText(connectivity) {
    const numeric = {
        0: _('Không xác định'),
        1: _('Không có mạng'),
        2: _('Chỉ mạng cục bộ'),
        3: _('Cần đăng nhập mạng'),
        4: _('Có Internet'),
    };
    if (typeof connectivity === 'number') return numeric[connectivity] || _('Không xác định');
    const normalized = String(connectivity || '').toLowerCase();
    const text = {
        none: _('Không có mạng'),
        portal: _('Cần đăng nhập mạng'),
        limited: _('Kết nối hạn chế'),
        full: _('Có Internet'),
        unknown: _('Không xác định'),
    };
    return text[normalized] || _('Không xác định');
}

function unpackVariant(variant, fallback) {
    try {
        return variant ? variant.deep_unpack() : fallback;
    } catch (e) {
        return fallback;
    }
}

function dbusPathIsValid(path) {
    return typeof path === 'string' && path.length > 1 && path[0] === '/';
}

function nmSsidText(ssid) {
    if (!NM || !ssid) return '';
    try {
        return NM.utils_ssid_to_utf8(ssid.get_data()) || '';
    } catch (e) {
        return '';
    }
}

function nmApSecurity(accessPoint) {
    if (!NM || !accessPoint) return { key: 'unknown', secure: true, enterprise: false };
    const flags = accessPoint.flags || 0;
    const wpa = accessPoint.wpa_flags || 0;
    const rsn = accessPoint.rsn_flags || 0;
    const securityFlags = NM['80211ApSecurityFlags'];
    const apFlags = NM['80211ApFlags'];
    const enterprise = !!((wpa | rsn) & securityFlags.KEY_MGMT_802_1X);
    if (enterprise) return { key: 'enterprise', secure: true, enterprise: true };
    if (rsn !== securityFlags.NONE) return { key: 'wpa2', secure: true, enterprise: false };
    if (wpa !== securityFlags.NONE) return { key: 'wpa', secure: true, enterprise: false };
    if (flags & apFlags.PRIVACY) return { key: 'wep', secure: true, enterprise: false };
    return { key: 'open', secure: false, enterprise: false };
}

class NetworkManagerWifiBackend {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._client = null;
        this._clientSignalIds = [];
        this._deviceSignals = [];
        this._state = { available: false, hardwareEnabled: false, enabled: false, scanning: false, device: null, networks: [] };
        this._disposed = false;
        this._initialize();
    }

    _initialize() {
        if (!NM || !NM.Client) return;
        NM.Client.new_async(null, (_source, result) => {
            if (this._disposed) return;
            try {
                this._client = NM.Client.new_finish(result);
                [
                    'notify::wireless-enabled',
                    'notify::wireless-hardware-enabled',
                    'notify::state',
                    'notify::active-connections',
                    'device-added',
                    'device-removed',
                    'connection-added',
                    'connection-removed',
                ].forEach(signal => {
                    this._clientSignalIds.push(this._client.connect(signal, () => this.refresh()));
                });
                this.refresh();
            } catch (e) {
                global.logError(e);
                this._emitUnavailable();
            }
        });
    }

    _emitUnavailable() {
        this._state = { available: false, hardwareEnabled: false, enabled: false, scanning: false, device: null, networks: [] };
        this._onChanged(this._state);
    }

    _clearDeviceSignals() {
        this._deviceSignals.forEach(pair => {
            try { pair[0].disconnect(pair[1]); } catch (e) { /* disposed */ }
        });
        this._deviceSignals = [];
    }

    _watchDevice(device) {
        const current = this._deviceSignals.length ? this._deviceSignals[0][0] : null;
        if (current === device) return;
        this._clearDeviceSignals();
        if (!device) return;
        [
            'notify::state',
            'notify::active-access-point',
            'access-point-added',
            'access-point-removed',
        ].forEach(signal => {
            this._deviceSignals.push([device, device.connect(signal, () => this.refresh())]);
        });
    }

    _wifiDevice() {
        if (!this._client) return null;
        const devices = this._client.get_devices() || [];
        return devices.find(device => device.device_type === NM.DeviceType.WIFI) || null;
    }

    _networkKey(ssid, mode, security) {
        return `${ssid}\u0000${mode}\u0000${security}`;
    }

    _buildNetworks(device) {
        if (!device) return [];
        const activeAp = device.active_access_point || null;
        const connections = this._client.get_connections() || [];
        const grouped = {};
        (device.get_access_points() || []).forEach(ap => {
            const ssid = nmSsidText(ap.get_ssid());
            if (!ssid) return;
            const security = nmApSecurity(ap);
            const key = this._networkKey(ssid, ap.mode, security.key);
            if (!grouped[key]) {
                grouped[key] = {
                    ssid,
                    mode: ap.mode,
                    security: security.key,
                    secure: security.secure,
                    enterprise: security.enterprise,
                    accessPoints: [],
                    connections: [],
                    active: false,
                };
            }
            const group = grouped[key];
            group.accessPoints.push(ap);
            if (ap === activeAp) group.active = true;
            connections.forEach(connection => {
                if (group.connections.indexOf(connection) === -1 && ap.connection_valid(connection)) {
                    group.connections.push(connection);
                }
            });
        });
        const networks = Object.keys(grouped).map(key => {
            const network = grouped[key];
            network.accessPoints.sort((left, right) => {
                if ((left === activeAp) !== (right === activeAp)) return left === activeAp ? -1 : 1;
                return right.strength - left.strength;
            });
            network.bestAp = network.accessPoints[0];
            network.strength = network.bestAp ? network.bestAp.strength : 0;
            network.saved = network.connections.length > 0;
            return network;
        });
        networks.sort((left, right) => {
            if (left.active !== right.active) return left.active ? -1 : 1;
            if (left.saved !== right.saved) return left.saved ? -1 : 1;
            if (left.strength !== right.strength) return right.strength - left.strength;
            return left.ssid.localeCompare(right.ssid);
        });
        return networks;
    }

    refresh() {
        if (this._disposed || !this._client) return;
        const device = this._wifiDevice();
        this._watchDevice(device);
        this._state = {
            available: device !== null,
            hardwareEnabled: !!this._client.wireless_hardware_enabled,
            enabled: !!this._client.wireless_enabled,
            scanning: false,
            device,
            networks: this._buildNetworks(device),
        };
        this._onChanged(this._state);
    }

    snapshot() {
        return this._state;
    }

    setEnabled(enabled) {
        if (!this._client || !this._state.hardwareEnabled) return false;
        this._client.wireless_enabled = enabled;
        return true;
    }

    requestScan() {
        if (!this._state.device || !this._state.enabled) return false;
        try {
            this._state.scanning = true;
            this._onChanged(this._state);
            this._state.device.request_scan(null);
            return true;
        } catch (e) {
            global.logError(e);
            this._state.scanning = false;
            this._onChanged(this._state);
            return false;
        }
    }

    activate(network) {
        if (!this._client || !this._state.device || !network || !network.bestAp) return false;
        if (network.active) {
            const activeConnection = this._state.device.active_connection;
            if (!activeConnection) return false;
            this._client.deactivate_connection(activeConnection, null);
            return true;
        }
        const onActivated = (_client, result) => {
            try {
                this._client.activate_connection_finish(result);
            } catch (e) {
                global.logError(e);
            }
            this.refresh();
        };
        const connection = network.connections[0] || null;
        if (connection) {
            this._client.activate_connection_async(connection, this._state.device, network.bestAp.path, null, onActivated);
            return true;
        }
        if (network.secure) return false;
        const profile = new NM.SimpleConnection();
        const wireless = new NM.SettingWireless();
        wireless.set_property('ssid', network.bestAp.get_ssid());
        profile.add_setting(wireless);
        profile.add_setting(new NM.SettingConnection({
            id: network.ssid,
            autoconnect: true,
            uuid: NM.utils_uuid_generate(),
            type: NM.SETTING_WIRELESS_SETTING_NAME,
        }));
        this._client.add_and_activate_connection_async(
            profile,
            this._state.device,
            network.bestAp.path,
            null,
            (_client, result) => {
                try {
                    this._client.add_and_activate_connection_finish(result);
                } catch (e) {
                    global.logError(e);
                }
                this.refresh();
            }
        );
        return true;
    }

    dispose() {
        this._disposed = true;
        this._clearDeviceSignals();
        this._clientSignalIds.forEach(id => {
            try { this._client.disconnect(id); } catch (e) { /* disposed */ }
        });
        this._clientSignalIds = [];
        this._client = null;
    }
}

class BluezBackend {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._manager = null;
        this._nameWatchId = 0;
        this._generation = 0;
        this._disposed = false;
        this._objectAddedId = 0;
        this._objectRemovedId = 0;
        this._objectSignals = [];
        this._refreshId = 0;
        this._state = { available: false, adapter: null, devices: [] };
        this._nameWatchId = Gio.bus_watch_name(
            Gio.BusType.SYSTEM,
            'org.bluez',
            Gio.BusNameWatcherFlags.NONE,
            () => this._connect(),
            () => this._serviceVanished()
        );
    }

    _connect() {
        if (this._disposed || this._manager) return;
        const generation = this._generation;
        Gio.DBusObjectManagerClient.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusObjectManagerClientFlags.NONE,
            'org.bluez',
            '/',
            null,
            null,
            (_source, result) => {
                if (this._disposed || generation !== this._generation) return;
                try {
                    this._manager = Gio.DBusObjectManagerClient.new_for_bus_finish(result);
                    this._objectAddedId = this._manager.connect('object-added', () => this._scheduleRefresh());
                    this._objectRemovedId = this._manager.connect('object-removed', () => this._scheduleRefresh());
                    this._scheduleRefresh();
                } catch (e) {
                    global.logError(e);
                    this._serviceVanished();
                }
            }
        );
    }

    _serviceVanished() {
        this._generation++;
        this._clearManager();
        this._state = { available: false, adapter: null, devices: [] };
        if (!this._disposed) this._onChanged(this._state);
    }

    _clearManager() {
        this._objectSignals.forEach(pair => {
            try { pair[0].disconnect(pair[1]); } catch (e) { /* disposed */ }
        });
        this._objectSignals = [];
        if (this._manager && this._objectAddedId) this._manager.disconnect(this._objectAddedId);
        if (this._manager && this._objectRemovedId) this._manager.disconnect(this._objectRemovedId);
        this._manager = null;
        this._objectAddedId = 0;
        this._objectRemovedId = 0;
    }

    _property(proxy, name, fallback) {
        return proxy ? unpackVariant(proxy.get_cached_property(name), fallback) : fallback;
    }

    _watch(proxy) {
        if (!proxy || this._objectSignals.some(pair => pair[0] === proxy)) return;
        this._objectSignals.push([proxy, proxy.connect('g-properties-changed', () => this._scheduleRefresh())]);
    }

    _scheduleRefresh() {
        if (this._disposed || this._refreshId) return;
        this._refreshId = Mainloop.idle_add(() => {
            this._refreshId = 0;
            if (!this._disposed) this.refresh();
            return false;
        });
    }

    refresh() {
        if (!this._manager) return;
        const objects = this._manager.get_objects();
        let adapter = null;
        const devices = [];
        objects.forEach(object => {
            const adapterProxy = object.get_interface('org.bluez.Adapter1');
            if (adapterProxy && !adapter) {
                this._watch(adapterProxy);
                adapter = {
                    path: object.get_object_path(),
                    powered: this._property(adapterProxy, 'Powered', false),
                    discovering: this._property(adapterProxy, 'Discovering', false),
                    discoverable: this._property(adapterProxy, 'Discoverable', false),
                };
            }
            const deviceProxy = object.get_interface('org.bluez.Device1');
            if (!deviceProxy) return;
            this._watch(deviceProxy);
            const batteryProxy = object.get_interface('org.bluez.Battery1');
            if (batteryProxy) this._watch(batteryProxy);
            devices.push({
                path: object.get_object_path(),
                address: this._property(deviceProxy, 'Address', ''),
                name: this._property(deviceProxy, 'Alias', this._property(deviceProxy, 'Name', 'Bluetooth')),
                paired: this._property(deviceProxy, 'Paired', false),
                connected: this._property(deviceProxy, 'Connected', false),
                trusted: this._property(deviceProxy, 'Trusted', false),
                blocked: this._property(deviceProxy, 'Blocked', false),
                servicesResolved: this._property(deviceProxy, 'ServicesResolved', false),
                battery: batteryProxy ? this._property(batteryProxy, 'Percentage', null) : null,
            });
        });
        this._state = { available: adapter !== null, adapter, devices };
        this._onChanged(this._state);
    }

    snapshot() {
        return this._state;
    }

    setPowered(powered) {
        const state = this._state;
        if (!state.adapter) return false;
        try {
            Gio.DBus.system.call(
                'org.bluez',
                state.adapter.path,
                'org.freedesktop.DBus.Properties',
                'Set',
                new GLib.Variant('(ssv)', ['org.bluez.Adapter1', 'Powered', new GLib.Variant('b', powered)]),
                null,
                Gio.DBusCallFlags.NONE,
                2000,
                null,
                (_connection, result) => {
                    try { Gio.DBus.system.call_finish(result); } catch (e) { global.logError(e); }
                    this._scheduleRefresh();
                }
            );
            return true;
        } catch (e) {
            global.logError(e);
            return false;
        }
    }

    callAdapter(method) {
        const state = this._state;
        if (!state.adapter || !dbusPathIsValid(state.adapter.path)) return false;
        try {
            Gio.DBus.system.call(
                'org.bluez',
                state.adapter.path,
                'org.bluez.Adapter1',
                method,
                null,
                null,
                Gio.DBusCallFlags.NONE,
                10000,
                null,
                (_connection, result) => {
                    try {
                        Gio.DBus.system.call_finish(result);
                    } catch (e) {
                        global.logError(e);
                    }
                    this._scheduleRefresh();
                }
            );
            return true;
        } catch (e) {
            global.logError(e);
            return false;
        }
    }

    startDiscovery() {
        return this.callAdapter('StartDiscovery');
    }

    stopDiscovery() {
        return this.callAdapter('StopDiscovery');
    }

    callDevice(device, method) {
        if (!device || !dbusPathIsValid(device.path)) return false;
        try {
            Gio.DBus.system.call(
                'org.bluez',
                device.path,
                'org.bluez.Device1',
                method,
                null,
                null,
                Gio.DBusCallFlags.NONE,
                10000,
                null,
                (_connection, result) => {
                    try {
                        Gio.DBus.system.call_finish(result);
                    } catch (e) {
                        global.logError(e);
                    }
                    this._scheduleRefresh();
                }
            );
            return true;
        } catch (e) {
            global.logError(e);
            return false;
        }
    }

    dispose() {
        this._disposed = true;
        this._generation++;
        if (this._refreshId) {
            Mainloop.source_remove(this._refreshId);
            this._refreshId = 0;
        }
        this._clearManager();
        if (this._nameWatchId) {
            Gio.bus_unwatch_name(this._nameWatchId);
            this._nameWatchId = 0;
        }
    }
}

class PowerBackend {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._client = null;
        this._signals = [];
        this._deviceSignals = [];
        this._state = { available: false, devices: [], battery: null, onBattery: false };
        this._disposed = false;
        this._connect();
    }

    _connect() {
        if (!UPowerGlib || !UPowerGlib.Client) return;
        try {
            this._client = UPowerGlib.Client.new();
            this._signals.push(this._client.connect('notify::on-battery', () => this.refresh()));
            this._signals.push(this._client.connect('device-added', () => this.refresh()));
            this._signals.push(this._client.connect('device-removed', () => this.refresh()));
            this.refresh();
        } catch (e) {
            global.logError(e);
            this._state = { available: false, devices: [], battery: null, onBattery: false };
            this._onChanged(this._state);
        }
    }

    _watchDevices(devices) {
        const current = new Set(devices);
        this._deviceSignals = this._deviceSignals.filter(pair => {
            if (current.has(pair[0])) return true;
            try { pair[0].disconnect(pair[1]); } catch (e) { /* disposed */ }
            return false;
        });
        devices.forEach(device => {
            if (this._deviceSignals.some(pair => pair[0] === device)) return;
            this._deviceSignals.push([device, device.connect('notify', () => this.refresh())]);
        });
    }

    _deviceSnapshot(device) {
        return {
            path: device.get_object_path(),
            kind: device.kind,
            name: device.model || device.vendor || _('Pin'),
            present: !!device.is_present,
            percentage: Math.max(0, Math.min(100, Number(device.percentage) || 0)),
            state: device.state,
            energyRate: Number(device.energy_rate) || 0,
            timeToEmpty: Number(device.time_to_empty) || 0,
            timeToFull: Number(device.time_to_full) || 0,
            warningLevel: device.warning_level,
            icon: device.icon_name || 'battery-full-symbolic',
        };
    }

    refresh() {
        if (this._disposed || !this._client) return;
        try {
            const allDevices = this._client.get_devices() || [];
            this._watchDevices(allDevices);
            const summaries = allDevices.filter(device => {
                const isBattery = device.kind === UPowerGlib.DeviceKind.BATTERY || device.kind === UPowerGlib.DeviceKind.UPS;
                return isBattery && device.power_supply !== false;
            }).map(device => this._deviceSnapshot(device)).filter(device => device.present);
            const linePower = allDevices.filter(device => device.kind === UPowerGlib.DeviceKind.LINE_POWER).map(device => ({
                path: device.get_object_path(),
                online: !!device.online,
            }));
            const display = this._client.get_display_device();
            const displaySnapshot = display && display.is_present ? this._deviceSnapshot(display) : null;
            const fallbackBattery = summaries.find(device => device.kind === UPowerGlib.DeviceKind.BATTERY)
                || summaries.find(device => device.kind === UPowerGlib.DeviceKind.UPS)
                || null;
            this._state = {
                available: true,
                devices: summaries,
                linePower,
                battery: displaySnapshot || fallbackBattery,
                onBattery: !!this._client.on_battery,
                onAc: linePower.some(device => device.online),
            };
            this._onChanged(this._state);
        } catch (e) {
            global.logError(e);
            this._state = { available: false, devices: [], battery: null, onBattery: false };
            this._onChanged(this._state);
        }
    }

    snapshot() {
        return this._state;
    }

    dispose() {
        this._disposed = true;
        if (this._client) {
            this._signals.forEach(id => {
                try { this._client.disconnect(id); } catch (e) { /* disposed */ }
            });
        }
        this._signals = [];
        this._deviceSignals.forEach(pair => {
            try { pair[0].disconnect(pair[1]); } catch (e) { /* disposed */ }
        });
        this._deviceSignals = [];
        this._client = null;
    }
}

class SessionBackend {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._proxy = null;
        this._cancellable = new Gio.Cancellable();
        this._state = {
            available: false,
            pending: false,
            error: '',
            canSwitchUser: false,
            canShutdown: false,
            canRestart: false,
            canHybridSleep: false,
            canSuspend: false,
            canHibernate: false,
            canLogout: false,
        };
        this._connect();
    }

    _connect() {
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SESSION,
            Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            null,
            SESSION_BUS_NAME,
            SESSION_OBJECT_PATH,
            SESSION_INTERFACE,
            this._cancellable,
            (_source, result) => {
                try {
                    this._proxy = Gio.DBusProxy.new_for_bus_finish(result);
                    this.refresh();
                } catch (e) {
                    if (!this._cancellable.is_cancelled()) {
                        this._state.error = e.message;
                        this._onChanged(this._state);
                    }
                }
            }
        );
    }

    refresh() {
        if (!this._proxy) return;
        this._proxy.call(
            'GetCapabilities',
            null,
            Gio.DBusCallFlags.NONE,
            2000,
            this._cancellable,
            (proxy, result) => {
                try {
                    const reply = unpackVariant(proxy.call_finish(result), []);
                    const values = Array.isArray(reply) && reply.length === 1 && Array.isArray(reply[0]) ? reply[0] : reply;
                    this._state = {
                        available: true,
                        pending: false,
                        error: '',
                        canSwitchUser: !!values[0],
                        canShutdown: !!values[1],
                        canRestart: !!values[2],
                        canHybridSleep: !!values[3],
                        canSuspend: !!values[4],
                        canHibernate: !!values[5],
                        canLogout: !!values[6],
                    };
                    this._onChanged(this._state);
                } catch (e) {
                    if (!this._cancellable.is_cancelled()) {
                        this._state.error = e.message;
                        this._onChanged(this._state);
                    }
                }
            }
        );
    }

    snapshot() {
        return this._state;
    }

    action(method) {
        if (!this._proxy || this._state.pending) return false;
        const dialogModes = { Restart: 0, Shutdown: 1, Logout: 2, SwitchUser: 2 };
        if (Object.prototype.hasOwnProperty.call(dialogModes, method)) {
            Gio.DBus.session.call(
                'org.Cinnamon',
                '/org/Cinnamon',
                'org.Cinnamon',
                'ShowEndSessionDialog',
                new GLib.Variant('(i)', [dialogModes[method]]),
                null,
                Gio.DBusCallFlags.NONE,
                2000,
                this._cancellable,
                (_connection, result) => {
                    try {
                        Gio.DBus.session.call_finish(result);
                        this._state = { ...this._state, pending: false, error: '' };
                    } catch (e) {
                        if (this._cancellable.is_cancelled()) return;
                        this._state = { ...this._state, pending: false, error: e.message };
                    }
                    this._onChanged(this._state);
                }
            );
            this._state = { ...this._state, pending: true, error: '' };
            this._onChanged(this._state);
            return true;
        }
        this._state = { ...this._state, pending: true, error: '' };
        this._onChanged(this._state);
        this._proxy.call(
            method,
            null,
            Gio.DBusCallFlags.NONE,
            -1,
            this._cancellable,
            (proxy, result) => {
                try {
                    proxy.call_finish(result);
                    this._state = { ...this._state, pending: false, error: '' };
                } catch (e) {
                    if (this._cancellable.is_cancelled()) return;
                    this._state = { ...this._state, pending: false, error: e.message };
                }
                this._onChanged(this._state);
            }
        );
        return true;
    }

    dispose() {
        this._cancellable.cancel();
        this._proxy = null;
    }
}

class NetworkManagerBackend {
    constructor(onChanged) {
        this._onChanged = onChanged;
        this._manager = null;
        this._proxies = {};
        this._signalIds = [];
        this._nameWatchId = 0;
        this._generation = 0;
        this._refreshGeneration = 0;
        this._state = unavailableNetworkState();
        this.available = false;
        this._watchService();
    }

    _watchService() {
        try {
            this._nameWatchId = Gio.bus_watch_name(
                Gio.BusType.SYSTEM,
                'org.freedesktop.NetworkManager',
                Gio.BusNameWatcherFlags.NONE,
                () => {
                    this.available = true;
                    this._connect();
                },
                () => {
                    this.available = false;
                    this._generation++;
                    this._refreshGeneration++;
                    this._clearProxies();
                    this._state = unavailableNetworkState();
                    this._onChanged(this._state);
                }
            );
        } catch (e) {
            global.logError(e);
        }
    }

    _connect() {
        if (this._manager) {
            this.refresh();
            return;
        }
        const generation = this._generation;
        this._getProxy('/org/freedesktop/NetworkManager', 'org.freedesktop.NetworkManager', proxy => {
            if (generation !== this._generation || !this.available || !proxy) return;
            this._manager = proxy;
            this.refresh();
        });
    }

    _getProxy(path, iface, callback) {
        if (!dbusPathIsValid(path)) {
            callback(null);
            return;
        }
        const key = `${iface}:${path}`;
        const cached = this._proxies[key];
        if (cached) {
            callback(cached);
            return;
        }
        const generation = this._generation;
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            null,
            'org.freedesktop.NetworkManager',
            path,
            iface,
            null,
            (_source, result) => {
                if (generation !== this._generation || !this.available) return;
                try {
                    const proxy = Gio.DBusProxy.new_for_bus_finish(result);
                    this._proxies[key] = proxy;
                    this._signalIds.push([proxy, proxy.connect('g-properties-changed', () => this.refresh())]);
                    callback(proxy);
                } catch (e) {
                    global.logError(e);
                    callback(null);
                }
            }
        );
    }

    _property(proxy, name, fallback) {
        return unpackVariant(proxy ? proxy.get_cached_property(name) : null, fallback);
    }

    _deviceTypeName(value) {
        if (value === 1) return 'ethernet';
        if (value === 2) return 'wifi';
        return 'other';
    }

    _normalizeAddressData(value) {
        if (!Array.isArray(value)) return [];
        return value.map(item => {
            if (!item || typeof item !== 'object') return '';
            const address = unpackVariant(item.address, item.address || '');
            const prefix = unpackVariant(item.prefix, item.prefix);
            return address ? `${address}${prefix === undefined || prefix === null ? '' : `/${prefix}`}` : '';
        }).filter(Boolean);
    }

    _normalizeNameserverData(value) {
        if (!Array.isArray(value)) return [];
        return value.map(item => {
            if (!item || typeof item !== 'object') return '';
            return unpackVariant(item.address, item.address || '');
        }).filter(Boolean);
    }

    _loadIpConfig(path, callback) {
        if (!dbusPathIsValid(path) || path === '/') {
            callback({ addresses: [], gateway: '', dns: [] });
            return;
        }
        this._getProxy(path, 'org.freedesktop.NetworkManager.IP4Config', proxy => {
            if (!proxy) {
                callback({ addresses: [], gateway: '', dns: [] });
                return;
            }
            callback({
                addresses: this._normalizeAddressData(this._property(proxy, 'AddressData', [])),
                gateway: this._property(proxy, 'Gateway', ''),
                dns: this._normalizeNameserverData(this._property(proxy, 'NameserverData', [])),
            });
        });
    }

    _loadActiveConnection(path, callback) {
        if (!dbusPathIsValid(path) || path === '/') {
            callback(null);
            return;
        }
        this._getProxy(path, 'org.freedesktop.NetworkManager.Connection.Active', proxy => {
            if (!proxy) {
                callback(null);
                return;
            }
            callback({
                id: this._property(proxy, 'Id', ''),
                type: this._property(proxy, 'Type', ''),
                vpn: this._property(proxy, 'Vpn', false),
                default: this._property(proxy, 'Default', false),
                default6: this._property(proxy, 'Default6', false),
            });
        });
    }

    _loadWiredDetails(path, type, callback) {
        if (type !== 'ethernet') {
            callback({ carrier: null, speed: 0 });
            return;
        }
        this._getProxy(path, 'org.freedesktop.NetworkManager.Device.Wired', proxy => {
            callback(proxy ? {
                carrier: this._property(proxy, 'Carrier', false),
                speed: this._property(proxy, 'Speed', 0),
            } : { carrier: null, speed: 0 });
        });
    }

    _loadDevice(path, callback) {
        this._getProxy(path, 'org.freedesktop.NetworkManager.Device', proxy => {
            if (!proxy) {
                callback(null);
                return;
            }
            const type = this._deviceTypeName(this._property(proxy, 'DeviceType', 0));
            const activePath = this._property(proxy, 'ActiveConnection', '/');
            const ip4Path = this._property(proxy, 'Ip4Config', '/');
            const stateReason = this._property(proxy, 'StateReason', [0, 0]);
            const details = { active: null, ip4: null, wired: null };
            let pending = 3;
            const finish = () => {
                pending--;
                if (pending > 0) return;
                callback({
                    path,
                    device: this._property(proxy, 'Interface', ''),
                    type,
                    state: this._property(proxy, 'State', 0),
                    stateReason: Array.isArray(stateReason) ? stateReason[1] || 0 : 0,
                    metered: this._property(proxy, 'Metered', 0),
                    active: details.active !== null,
                    activePath,
                    connection: details.active ? details.active.id : '',
                    vpn: details.active ? details.active.vpn : false,
                    default: details.active ? !!(details.active.default || details.active.default6) : false,
                    carrier: details.wired.carrier,
                    speed: details.wired.speed,
                    addresses: details.ip4.addresses,
                    gateway: details.ip4.gateway,
                    dns: details.ip4.dns,
                });
            };
            this._loadActiveConnection(activePath, value => { details.active = value; finish(); });
            this._loadIpConfig(ip4Path, value => { details.ip4 = value; finish(); });
            this._loadWiredDetails(path, type, value => { details.wired = value; finish(); });
        });
    }

    _sortDevices(devices, primaryConnection) {
        devices.sort((left, right) => {
            const leftPrimary = left.activePath === primaryConnection || left.default;
            const rightPrimary = right.activePath === primaryConnection || right.default;
            if (leftPrimary !== rightPrimary) return leftPrimary ? -1 : 1;
            if (left.active !== right.active) return left.active ? -1 : 1;
            const typeOrder = { ethernet: 0, wifi: 1, other: 2 };
            if (typeOrder[left.type] !== typeOrder[right.type]) return typeOrder[left.type] - typeOrder[right.type];
            return left.device.localeCompare(right.device);
        });
        return devices;
    }

    refresh() {
        if (!this._manager || !this.available) return;
        const manager = this._manager;
        const generation = this._generation;
        const refreshGeneration = ++this._refreshGeneration;
        manager.call(
            'GetDevices',
            null,
            Gio.DBusCallFlags.NONE,
            2000,
            null,
            (proxy, result) => {
                if (generation !== this._generation || refreshGeneration !== this._refreshGeneration || proxy !== this._manager) return;
                let paths;
                try {
                    const values = unpackVariant(proxy.call_finish(result), []);
                    paths = Array.isArray(values) && values.length === 1 && Array.isArray(values[0]) ? values[0] : values;
                } catch (e) {
                    global.logError(e);
                    return;
                }
                if (!Array.isArray(paths)) return;
                const primaryConnection = this._property(manager, 'PrimaryConnection', '/');
                const devices = [];
                let pending = paths.length;
                const publish = () => {
                    if (generation !== this._generation || refreshGeneration !== this._refreshGeneration || !this.available) return;
                    this._sortDevices(devices, primaryConnection);
                    const primary = devices.find(device => device.activePath === primaryConnection)
                        || devices.find(device => device.default)
                        || devices.find(device => device.active)
                        || null;
                    this._state = {
                        available: true,
                        devices,
                        connectivity: this._property(manager, 'Connectivity', 0),
                        primaryConnection,
                        primaryDevice: primary ? primary.device : '',
                        primary,
                    };
                    this._onChanged(this._state);
                };
                if (!pending) {
                    publish();
                    return;
                }
                paths.forEach(path => this._loadDevice(path, device => {
                    if (device) devices.push(device);
                    pending--;
                    if (!pending) publish();
                }));
            }
        );
    }

    snapshot() {
        return this._state;
    }

    _clearProxies() {
        this._signalIds.forEach(pair => {
            try { pair[0].disconnect(pair[1]); } catch (e) { /* disposed */ }
        });
        this._signalIds = [];
        this._proxies = {};
        this._manager = null;
    }

    dispose() {
        this._generation++;
        this._refreshGeneration++;
        this._clearProxies();
        this._state = unavailableNetworkState();
        this.available = false;
        if (this._nameWatchId) {
            Gio.bus_unwatch_name(this._nameWatchId);
            this._nameWatchId = 0;
        }
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

function spawnArgvChecked(argv, onComplete) {
    if (mockEnabled()) {
        Mainloop.idle_add(() => {
            onComplete(true, null);
            return false;
        });
        return;
    }
    try {
        const process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_PIPE);
        process.communicate_utf8_async(null, null, (_process, result) => {
            try {
                const [, , stderr] = process.communicate_utf8_finish(result);
                onComplete(process.get_successful(), stderr || null);
            } catch (e) {
                global.logError(e);
                onComplete(false, e.message);
            }
        });
    } catch (e) {
        global.logError(e);
        onComplete(false, e.message);
    }
}

function commandOutputAsync(argv, timeoutSeconds, onComplete) {
    if (mockEnabled()) {
        Mainloop.idle_add(() => {
            onComplete(true, mockCommandOutput(argv), null);
            return false;
        });
        return;
    }
    const timedArgv = commandExists('timeout')
        ? ['timeout', String(timeoutSeconds || 2)].concat(argv)
        : argv;
    try {
        const process = Gio.Subprocess.new(
            timedArgv,
            Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
        );
        process.communicate_utf8_async(null, null, (_process, result) => {
            try {
                const [, stdout, stderr] = process.communicate_utf8_finish(result);
                onComplete(process.get_successful(), stdout ? stdout.trim() : '', stderr || null);
            } catch (e) {
                global.logError(e);
                onComplete(false, '', e.message);
            }
        });
    } catch (e) {
        global.logError(e);
        onComplete(false, '', e.message);
    }
}

function unavailableNetworkState() {
    return {
        available: false,
        devices: [],
        connectivity: 0,
        primaryConnection: '/',
        primaryDevice: '',
        primary: null,
    };
}

function emptyNetworkState(snapshot, backend) {
    const base = snapshot || unavailableNetworkState();
    return {
        ...base,
        available: base.available !== false && !!backend && backend.available,
        source: 'networkmanager-dbus',
        primary: base.available === false ? null
            : base.devices.find(device => device.device === base.primaryDevice)
                || base.devices.find(device => device.active)
                || null,
    };
}

function spawnAllowed(command) {
    const allowed = {
        settings: 'cinnamon-settings',
        soundSettings: 'cinnamon-settings sound',
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

function setAccessibleName(actor, name) {
    if (!actor || !name) return;
    try {
        actor.accessible_name = name;
        if (actor.get_accessible) actor.get_accessible().set_name(name);
    } catch (e) {
        // Cinnamon versions differ in exposed accessibility APIs.
    }
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

function createRoundButton(iconName, command, onClick, accessibleName) {
    const button = new St.Button({ style_class: 'caramos-cc-round-button', reactive: true, can_focus: true, track_hover: true });
    setAccessibleName(button, accessibleName || command || iconName);
    button.set_child(createIcon(iconName, 'caramos-cc-round-icon'));
    button.connect('clicked', () => {
        if (onClick) onClick();
        else spawnAllowed(command);
    });
    return button;
}

function createHeaderPill(iconName, text, onClick) {
    const button = new St.Button({ style_class: 'caramos-cc-battery-pill', reactive: true, can_focus: true, track_hover: true });
    setAccessibleName(button, _('Trạng thái pin và nguồn điện'));
    const row = new St.BoxLayout({ vertical: false });
    row.add_child(createIcon(iconName, 'caramos-cc-pill-icon'));
    row.add_child(new St.Label({ text, style_class: 'caramos-cc-pill-label', y_align: Clutter.ActorAlign.CENTER }));
    button.set_child(row);
    button.connect('clicked', onClick);
    return button;
}

function createSliderRow(iconName, labelText, initialValue, onChanged, onIconClicked, onDragChanged, onDetails) {
    const row = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-slider-row' });
    setAccessibleName(row, labelText);
    const iconButton = new St.Button({
        style_class: 'caramos-cc-slider-icon-button',
        reactive: !!onIconClicked,
        can_focus: !!onIconClicked,
        track_hover: !!onIconClicked,
    });
    const icon = createIcon(iconName, 'caramos-cc-slider-icon');
    iconButton.set_child(icon);
    setAccessibleName(iconButton, `${_('Bật hoặc tắt tiếng')} ${labelText}`);
    if (onIconClicked) iconButton.connect('clicked', onIconClicked);
    row.add_child(iconButton);

    const slider = new PopupMenu.PopupSliderMenuItem(initialValue / 100);
    setAccessibleName(slider.actor, labelText);
    slider.actor.add_style_class_name('caramos-cc-slider-item');
    slider.actor.set_x_expand(true);
    slider.connect('value-changed', (_item, value) => onChanged(Math.round(value * 100)));
    if (onDragChanged) {
        slider.connect('drag-begin', () => onDragChanged(true));
        slider.connect('drag-end', () => onDragChanged(false));
    }
    row.add_child(slider.actor);

    let detailsButton = null;
    if (onDetails) {
        detailsButton = new St.Button({
            style_class: 'caramos-cc-audio-disclosure',
            reactive: true,
            can_focus: true,
            track_hover: true,
        });
        setAccessibleName(detailsButton, `${_('Mở chi tiết')} ${labelText}`);
        detailsButton.set_child(createIcon('pan-end-symbolic', 'caramos-cc-audio-disclosure-icon'));
        detailsButton.connect('clicked', onDetails);
        row.add_child(detailsButton);
    }

    return { actor: row, slider, icon, iconButton, detailsButton, enabled: true };
}

function setSliderEnabled(row, enabled) {
    row.enabled = enabled;
    row.actor.reactive = enabled;
    row.actor.can_focus = enabled;
    row.slider.actor.reactive = enabled;
    row.slider.actor.can_focus = enabled;
    if (row.detailsButton) {
        row.detailsButton.reactive = enabled;
        row.detailsButton.can_focus = enabled;
    }
    if (enabled) {
        row.actor.remove_style_class_name('caramos-cc-disabled');
    } else {
        row.actor.add_style_class_name('caramos-cc-disabled');
    }
}

function setTileEnabled(tile, enabled) {
    tile.enabled = enabled;
    const controls = [tile.button, tile.mainButton, tile.arrowButton].filter(Boolean);
    controls.forEach(control => {
        control.reactive = enabled;
        control.can_focus = enabled;
    });
    if (enabled) {
        tile.tile.remove_style_class_name('caramos-cc-disabled');
    } else {
        tile.tile.add_style_class_name('caramos-cc-disabled');
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
    setAccessibleName(mainButton, `${title}: ${subtitle}`);
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
    setAccessibleName(arrowButton, `${_('Mở chi tiết')} ${title}`);
    arrowButton.set_child(createIcon('pan-end-symbolic', 'caramos-cc-arrow-icon'));
    arrowButton.connect('clicked', onExpand);

    tile.add_child(mainButton);
    tile.add_child(arrowButton);
    wrapper.add_child(tile);

    return {
        actor: wrapper,
        tile,
        mainButton,
        arrowButton,
        titleLabel,
        subtitleLabel,
        icon: iconSlot.icon,
        iconSlot: iconSlot.slot,
        normalIconName: iconName,
        enabled: true,
    };
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
    setAccessibleName(button, `${title}: ${subtitle}`);
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
    return {
        actor: wrapper,
        tile: button,
        button,
        titleLabel,
        subtitleLabel,
        icon: iconSlot.icon,
        iconSlot: iconSlot.slot,
        normalIconName: iconName,
        enabled: true,
    };
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
    setAccessibleName(button, text);
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

// Audio rows own pointer/key activation so release events never reach the parent popup.
function createAudioDeviceRow(iconName, text, selected, onClick) {
    const item = new PopupMenu.PopupBaseMenuItem({ activate: true, focusOnHover: false });
    item.actor.set_style_class_name('popup-menu-item caramos-cc-list-row caramos-cc-audio-device-row');
    setAccessibleName(item.actor, text);
    const row = new St.BoxLayout({ vertical: false, x_expand: true, x_align: Clutter.ActorAlign.START });
    row.add_child(createIcon(iconName, 'caramos-cc-row-lead-icon'));
    const label = new St.Label({ text, style_class: 'caramos-cc-list-label', y_align: Clutter.ActorAlign.CENTER, x_align: Clutter.ActorAlign.START });
    label.clutter_text.set_ellipsize(Pango.EllipsizeMode.END);
    row.add_child(label);
    row.add_child(new St.Widget({ x_expand: true }));
    const marker = createIcon('object-select-symbolic', 'caramos-cc-row-trail-icon');
    marker.visible = !!selected;
    row.add_child(marker);
    item.addActor(row, { expand: true, span: -1 });
    item.connect('activate', () => {
        if (onClick) onClick();
    });
    item.activate = function (event) {
        this.emit('activate', event, true);
    };
    return item;
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
        this._audioSliderDragging = { output: false, input: false };
        this._audioSyncId = 0;
        this._updatingSliders = false;
        this._brightnessProxy = null;
        this._brightnessSignalId = 0;
        this._brightnessReady = false;
        this._brightnessRequestGeneration = 0;
        this._brightnessWriteGeneration = 0;
        this._brightnessSliderDragging = false;
        this._brightnessPending = null;
        this._brightnessApplyId = 0;
        this._brightnessSyncId = 0;
        this._brightnessInFlight = false;
        this._powerMenuVisible = false;
        this._bluetoothPowered = null;
        this._bluetoothSignalId = 0;
        this._bluetoothRefreshId = 0;
        this._bluetoothRenderSignature = '';
        this._inlineCloseButton = null;
        this._bluezBackend = new BluezBackend(state => this._onBluezStateChanged(state));
        this._bluezState = this._bluezBackend.snapshot();
        this._networkBackend = new NetworkManagerBackend(state => this._onNetworkStateChanged(state));
        this._networkState = null;
        this._wifiBackend = new NetworkManagerWifiBackend(state => this._onWifiStateChanged(state));
        this._wifiState = this._wifiBackend.snapshot();
        this._wifiPendingTarget = null;
        this._powerBackend = null;
        this._powerState = { available: false, devices: [], battery: null, onBattery: false };
        this._sessionBackend = null;
        this._sessionState = { available: false, pending: false, error: '' };
        this._audioDevices = { output: [], input: [] };
        this._activeAudioDeviceIds = { output: -1, input: -1 };
        this._audioDeviceRefreshIds = { output: 0, input: 0 };
        this._audioPointerSelection = { output: false, input: false };
        this._audioPointerDeviceIds = { output: -1, input: -1 };
        this._vpnState = { available: false, loading: false, profiles: [], error: '' };
        this._vpnActionPending = false;
        this._vpnRefreshId = 0;
        this._vpnPeriodicRefreshId = 0;
        this._vpnQueryGeneration = 0;
        this._vpnQueryInFlight = false;
        this._vpnRefreshQueued = false;
        this._vpnInitialized = false;
        this._oneShotIds = [];
        this._inlineAnimationGeneration = 0;
        this._removed = false;
        this._focusOpener = null;
        this._inlineFocusTarget = null;
        this._reducedMotion = false;
        this._themeSettings = null;
        this._themeSettingsSignalId = 0;
        try {
            this._themeSettings = Gio.Settings.new('org.cinnamon.desktop.interface');
            this._themeSettingsSignalId = this._themeSettings.connect('changed', () => {
                this._reducedMotion = !this._themeSettings.get_boolean('enable-animations');
                this._updateThemeClasses();
            });
            this._reducedMotion = !this._themeSettings.get_boolean('enable-animations');
        } catch (e) {
            global.logError(e);
        }

        this._nightLightSettings = null;
        try {
            this._nightLightSettings = Gio.Settings.new(NIGHT_LIGHT_SCHEMA);
        } catch (e) {
            global.logError(e);
        }

        this._control = null;
        this._controlSignalIds = [];
        this._audioAvailable = false;
        try {
            if (!Cvc || !Cvc.MixerControl) throw new Error('Cvc.MixerControl is unavailable');
            this._control = new Cvc.MixerControl({ name: 'CaramOS Control Center' });
            this._controlSignalIds.push(this._control.connect('state-changed', () => this._onMixerStateChanged()));
            this._controlSignalIds.push(this._control.connect('active-output-update', (_control, id) => this._onAudioDeviceUpdate('output', id)));
            this._controlSignalIds.push(this._control.connect('active-input-update', (_control, id) => this._onAudioDeviceUpdate('input', id)));
            this._controlSignalIds.push(this._control.connect('output-added', (_control, id) => this._onAudioDeviceAdded('output', id)));
            this._controlSignalIds.push(this._control.connect('output-removed', (_control, id) => this._onAudioDeviceRemoved('output', id)));
            this._controlSignalIds.push(this._control.connect('input-added', (_control, id) => this._onAudioDeviceAdded('input', id)));
            this._controlSignalIds.push(this._control.connect('input-removed', (_control, id) => this._onAudioDeviceRemoved('input', id)));
            this._controlSignalIds.push(this._control.connect('stream-added', (...args) => this._onStreamAdded(...args)));
            this._controlSignalIds.push(this._control.connect('stream-removed', (...args) => this._onStreamRemoved(...args)));
            this._volumeNorm = this._control.get_vol_max_norm();
            this._volumeMax = this._volumeNorm;
            this._audioAvailable = true;
        } catch (e) {
            global.logError(e);
        }

        this.menuManager = new PopupMenu.PopupMenuManager(this);
        this.menu = new Applet.AppletPopupMenu(this, orientation);
        this.menu.actor.add_style_class_name('caramos-cc-popup');
        if (this.menu.box) this.menu.box.add_style_class_name('caramos-cc-popup-box');
        this.menu._calculatePosition = () => this._calculateMenuPosition();
        this.menu.connect('open-state-changed', (_menu, open) => {
            ccDebug('parent-open-state', {
                open,
                menuOpen: this.menu.isOpen,
                kind: this._expandedKind,
                inlineVisible: !!(this._expandedPanel && this._expandedPanel.visible),
                focus: ccActorDebug(global.stage.key_focus),
            });
            if (open) {
                this._focusOpener = global.stage.get_key_focus();
                this._alignMenuToRightEdge();
                this._addOneShot(1, () => this._focusFirstControl(this._container));
            } else {
                this._restoreFocus();
            }
        });
        this.menu.actor.connect('key-press-event', (_actor, event) => this._onMenuKeyPress(event));
        this.menuManager.addMenu(this.menu);
        this._installMenuDebug();

        this._buildPanelIndicator();
        this._buildMenu();
        this._updateThemeClasses();
        this._powerBackend = new PowerBackend(state => this._onPowerStateChanged(state));
        this._powerState = this._powerBackend.snapshot();
        this._sessionBackend = new SessionBackend(state => this._onSessionStateChanged(state));
        this._sessionState = this._sessionBackend.snapshot();
        if (this._control) this._control.open();
        this._initBrightness();
        this._watchBluetoothStatus();
        this._refresh();
        this._refreshVpnState(true);
        this._refreshId = Mainloop.timeout_add_seconds(REFRESH_SECONDS, () => {
            this._refresh();
            return true;
        });
        this._vpnPeriodicRefreshId = Mainloop.timeout_add_seconds(REFRESH_SECONDS, () => {
            this._refreshVpnState();
            return true;
        });
    }

    _installMenuDebug() {
        if (this._menuDebugInstalled || !GLib.file_test(DEBUG_MARKER, GLib.FileTest.EXISTS)) return;
        this._menuDebugInstalled = true;

        const wrap = (name, topic, beforeFields) => {
            const original = this.menuManager[name];
            if (typeof original !== 'function') {
                ccDebug('manager-wrap-skip', { name });
                return;
            }
            this.menuManager[name] = (...args) => {
                const wasOpen = !!this.menu.isOpen;
                ccDebug(`${topic}-before`, beforeFields ? beforeFields(args) : { menuOpen: wasOpen });
                const result = original.apply(this.menuManager, args);
                ccDebug(`${topic}-after`, { menuOpen: this.menu.isOpen, closed: wasOpen && !this.menu.isOpen, result });
                return result;
            };
        };

        wrap('_onEventCapture', 'manager-capture', args => ({
            ...ccEventDebug(args[1]),
            menuOpen: this.menu.isOpen,
            kind: this._expandedKind,
            focus: ccActorDebug(global.stage.key_focus),
        }));
        wrap('_onKeyFocusChanged', 'manager-focus', () => ({
            menuOpen: this.menu.isOpen,
            kind: this._expandedKind,
            focus: ccActorDebug(global.stage.key_focus),
        }));
        wrap('_closeMenu', 'manager-close', () => ({
            menuOpen: this.menu.isOpen,
            kind: this._expandedKind,
            focus: ccActorDebug(global.stage.key_focus),
        }));
    }

    on_applet_removed_from_panel() {
        this._removed = true;
        this._vpnQueryGeneration++;
        this._brightnessRequestGeneration++;
        if (this._refreshId) {
            Mainloop.source_remove(this._refreshId);
            this._refreshId = 0;
        }
        if (this._vpnPeriodicRefreshId) {
            Mainloop.source_remove(this._vpnPeriodicRefreshId);
            this._vpnPeriodicRefreshId = 0;
        }
        if (this._bluetoothSignalId) {
            Gio.DBus.session.signal_unsubscribe(this._bluetoothSignalId);
            this._bluetoothSignalId = 0;
        }
        if (this._networkBackend) {
            this._networkBackend.dispose();
            this._networkBackend = null;
        }
        if (this._wifiBackend) {
            this._wifiBackend.dispose();
            this._wifiBackend = null;
        }
        if (this._powerBackend) {
            this._powerBackend.dispose();
            this._powerBackend = null;
        }
        if (this._themeSettings && this._themeSettingsSignalId) {
            try { this._themeSettings.disconnect(this._themeSettingsSignalId); } catch (e) { /* disposed */ }
        }
        this._themeSettingsSignalId = 0;
        this._themeSettings = null;
        if (this._sessionBackend) {
            this._sessionBackend.dispose();
            this._sessionBackend = null;
        }
        if (this._bluezBackend) {
            const state = this._bluezBackend.snapshot();
            if (state && state.adapter && state.adapter.discovering) this._bluezBackend.stopDiscovery();
            this._bluezBackend.dispose();
            this._bluezBackend = null;
        }
        if (this._output && this._outputVolumeChangedId) this._output.disconnect(this._outputVolumeChangedId);
        if (this._output && this._outputMutedChangedId) this._output.disconnect(this._outputMutedChangedId);
        if (this._input && this._inputVolumeChangedId) this._input.disconnect(this._inputVolumeChangedId);
        if (this._input && this._inputMutedChangedId) this._input.disconnect(this._inputMutedChangedId);
        this._outputVolumeChangedId = 0;
        this._outputMutedChangedId = 0;
        this._inputVolumeChangedId = 0;
        this._inputMutedChangedId = 0;
        this._output = null;
        this._input = null;
        if (this._control) {
            this._controlSignalIds.forEach(id => {
                try { this._control.disconnect(id); } catch (e) { /* disposed */ }
            });
            this._controlSignalIds = [];
            try { this._control.close(); } catch (e) { global.logError(e); }
            this._control = null;
        }
        if (this._brightnessProxy && this._brightnessSignalId) {
            try { this._brightnessProxy.disconnectSignal(this._brightnessSignalId); } catch (e) { /* disposed */ }
        }
        this._brightnessSignalId = 0;
        this._brightnessProxy = null;
        this._brightnessReady = false;
        if (this._outputVolumeApplyId) Mainloop.source_remove(this._outputVolumeApplyId);
        if (this._inputVolumeApplyId) Mainloop.source_remove(this._inputVolumeApplyId);
        if (this._audioSyncId) Mainloop.source_remove(this._audioSyncId);
        if (this._brightnessApplyId) Mainloop.source_remove(this._brightnessApplyId);
        if (this._brightnessSyncId) Mainloop.source_remove(this._brightnessSyncId);
        if (this._bluetoothRefreshId) Mainloop.source_remove(this._bluetoothRefreshId);
        Object.keys(this._audioDeviceRefreshIds).forEach(type => {
            if (this._audioDeviceRefreshIds[type]) Mainloop.source_remove(this._audioDeviceRefreshIds[type]);
            this._audioDeviceRefreshIds[type] = 0;
        });
        if (this._menuAlignId) Mainloop.source_remove(this._menuAlignId);
        if (this._vpnRefreshId) Mainloop.source_remove(this._vpnRefreshId);
        this._oneShotIds.forEach(id => Mainloop.source_remove(id));
        this._oneShotIds = [];
        this._outputVolumeApplyId = 0;
        this._inputVolumeApplyId = 0;
        this._audioSyncId = 0;
        this._brightnessApplyId = 0;
        this._brightnessSyncId = 0;
        this._brightnessPending = null;
        this._brightnessInFlight = false;
        this._bluetoothRefreshId = 0;
        this._inlineCloseButton = null;
        this._menuAlignId = 0;
        this._inlineFocusTarget = null;
        this._vpnRefreshId = 0;
        [this._wifiTile, this._bluetoothTile, this._nightLightTile].forEach(tile => {
            if (tile) this._setTileLoading(tile, false);
        });
    }

    _addOneShot(delayMs, callback) {
        const id = Mainloop.timeout_add(delayMs, () => {
            const index = this._oneShotIds.indexOf(id);
            if (index !== -1) this._oneShotIds.splice(index, 1);
            if (this._removed) return false;
            callback();
            return false;
        });
        this._oneShotIds.push(id);
        return id;
    }

    on_applet_clicked() {
        ccDebug('applet-click', { menuOpen: this.menu.isOpen, kind: this._expandedKind });
        this._closeSubmenus();
        ccDebug('menu-toggle-explicit', { menuOpen: this.menu.isOpen });
        this.menu.toggle();
        this._addOneShot(1, () => {
            this._refresh();
            this._alignMenuToRightEdge();
        });
    }

    _alignMenuToRightEdge() {
        if (!this.menu || !this.menu.actor || !this.menu.isOpen) return;

        this._positionMenuSurface();
        this._addOneShot(1, () => this._positionMenuSurface());
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
        header.add_child(createRoundButton('camera-photo-symbolic', 'screenshot', null, _('Chụp màn hình')));
        header.add_child(createRoundButton('preferences-system-symbolic', 'settings', null, _('Mở cài đặt hệ thống')));
        header.add_child(createRoundButton('system-lock-screen-symbolic', 'lock', null, _('Khóa màn hình')));
        header.add_child(createRoundButton('system-shutdown-symbolic', null, () => this._openPowerOverlay(), _('Mở menu nguồn')));
        this._header = header;
        container.add_child(header);

        this._volumeRow = createSliderRow('audio-volume-high-symbolic', 'Âm lượng', 50, value => {
            if (!this._updatingSliders) this._setStreamVolume(this._output, value);
        }, () => this._toggleStreamMute(this._output), dragging => this._setAudioSliderDragging('output', dragging),
        () => this._openAudioOverlay('output'));
        this._volumeRow.detailsButton.connect('button-press-event', () => {
            this._audioPointerSelection.output = true;
            return Clutter.EVENT_PROPAGATE;
        });
        this._micRow = createSliderRow('microphone-sensitivity-high-symbolic', 'Mic', 50, value => {
            if (!this._updatingSliders) this._setStreamVolume(this._input, value);
        }, () => this._toggleStreamMute(this._input), dragging => this._setAudioSliderDragging('input', dragging),
        () => this._openAudioOverlay('input'));
        this._micRow.detailsButton.connect('button-press-event', () => {
            this._audioPointerSelection.input = true;
            return Clutter.EVENT_PROPAGATE;
        });
        this._volumeRow.detailsButton.connect('key-press-event', () => {
            this._audioPointerSelection.output = false;
            return Clutter.EVENT_PROPAGATE;
        });
        this._micRow.detailsButton.connect('key-press-event', () => {
            this._audioPointerSelection.input = false;
            return Clutter.EVENT_PROPAGATE;
        });
        this._brightnessRow = createSliderRow(
            'display-brightness-symbolic',
            'Ánh sáng',
            50,
            value => {
                if (!this._updatingSliders) this._setBrightness(value);
            },
            null,
            dragging => this._setBrightnessSliderDragging(dragging)
        );
        this._brightnessRow.actor.hide();

        this._audioOutputGroup = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-audio-group', x_expand: true });
        this._audioOutputGroup.add_child(this._volumeRow.actor);
        container.add_child(this._audioOutputGroup);

        this._audioInputGroup = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-audio-group', x_expand: true });
        this._audioInputGroup.add_child(this._micRow.actor);
        container.add_child(this._audioInputGroup);
        container.add_child(this._brightnessRow.actor);

        this._ethernetTile = createSplitTile('network-wired-symbolic', _('Mạng dây'), _('Đang kiểm tra'), false, () => this._openSettings('networkSettings'), () => this._openEthernetOverlay());
        this._wifiTile = createSplitTile('network-wireless-symbolic', _('Wi‑Fi'), _('Đang kiểm tra'), true, () => this._toggleWifi(), () => this._openWifiOverlay());
        this._networkRow = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-grid-row', x_expand: true, x_align: Clutter.ActorAlign.FILL });
        this._networkRow.add_child(this._ethernetTile.actor);
        this._networkRow.add_child(this._wifiTile.actor);

        this._vpnTile = createSplitTile('network-vpn-symbolic', _('VPN'), _('Chưa kết nối'), false, () => this._toggleVpn(), () => this._openVpnOverlay());
        this._bluetoothTile = createSplitTile('bluetooth-symbolic', _('Bluetooth'), _('Đang kiểm tra'), false, () => this._toggleBluetooth(), () => this._openBluetoothOverlay());
        this._connectionsRow = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-grid-row', x_expand: true, x_align: Clutter.ActorAlign.FILL });
        this._connectionsRow.add_child(this._vpnTile.actor);
        this._connectionsRow.add_child(this._bluetoothTile.actor);

        this._nightLightTile = createSimpleTile('night-light-symbolic', _('Ánh sáng đêm'), _('Bật/tắt Night Light'), false, () => this._toggleNightLight());
        this._displayRow = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-grid-row', x_expand: true, x_align: Clutter.ActorAlign.FILL });
        this._displayRow.add_child(this._nightLightTile.actor);

        container.add_child(this._networkRow);
        container.add_child(this._connectionsRow);
        container.add_child(this._displayRow);

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
        this._focusOpener = global.stage.get_key_focus() || this._focusOpener;
        this._overlayCard.destroy_all_children();

        const head = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-overlay-head' });
        head.add_child(createIcon(iconName, 'caramos-cc-overlay-head-icon'));
        head.add_child(new St.Label({ text: title, style_class: 'caramos-cc-overlay-title', y_align: Clutter.ActorAlign.CENTER }));
        head.add_child(new St.Widget({ x_expand: true }));
        const closeBtn = new St.Button({ style_class: 'caramos-cc-overlay-close', reactive: true, can_focus: true, track_hover: true });
        setAccessibleName(closeBtn, _('Đóng hộp thoại'));
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
        this._restoreFocus();
    }

    _focusFirstControl(container) {
        if (!container || !container.get_children) return;
        const stack = container.get_children().slice();
        while (stack.length) {
            const actor = stack.shift();
            if (actor.can_focus && actor.reactive && actor.visible) {
                try { actor.grab_key_focus(); } catch (e) { /* toolkit version */ }
                return;
            }
            if (actor.get_children) stack.push(...actor.get_children());
        }
    }

    _restoreInlineFocus() {
        const target = this._inlineFocusTarget;
        this._inlineFocusTarget = null;
        ccDebug('inline-focus-restore-start', {
            target: ccActorDebug(target),
            menuOpen: !!(this.menu && this.menu.isOpen),
            current: ccActorDebug(global.stage.key_focus),
        });
        if (target && target.visible && target.can_focus && target.reactive) {
            try { target.grab_key_focus(); } catch (e) { /* toolkit version */ }
            ccDebug('inline-focus-restore-target', { current: ccActorDebug(global.stage.key_focus) });
            return;
        }
        if (this.menu && this.menu.actor && this.menu.isOpen) {
            try { this.menu.actor.grab_key_focus(); } catch (e) { /* toolkit version */ }
            ccDebug('inline-focus-restore-menu', { current: ccActorDebug(global.stage.key_focus) });
        }
    }

    _restoreFocus() {
        const opener = this._focusOpener;
        this._focusOpener = null;
        if (opener && opener.visible && opener.can_focus) {
            try { opener.grab_key_focus(); } catch (e) { /* toolkit version */ }
        }
    }

    _onMenuKeyPress(event) {
        const symbol = event.get_key_symbol();
        if (symbol === Clutter.KEY_Escape) {
            if (this._overlay && this._overlay.visible) {
                this._closeOverlay();
            } else if (this._expandedPanel && this._expandedPanel.visible) {
                this._closeInlinePanel();
            } else if (this.menu && this.menu.isOpen) {
                ccDebug('menu-close-explicit-escape', { kind: this._expandedKind });
                this.menu.close();
            }
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _updateThemeClasses() {
        if (!this.menu || !this.menu.actor) return;
        const actor = this.menu.actor;
        ['caramos-cc-light', 'caramos-cc-dark', 'caramos-cc-high-contrast'].forEach(name => actor.remove_style_class_name(name));
        let themeName = '';
        let highContrast = false;
        try {
            themeName = this._themeSettings ? this._themeSettings.get_string('gtk-theme') : '';
            highContrast = this._themeSettings ? this._themeSettings.get_boolean('high-contrast') : false;
        } catch (e) { /* schema variation */ }
        const dark = /dark/i.test(themeName);
        actor.add_style_class_name(dark ? 'caramos-cc-dark' : 'caramos-cc-light');
        if (highContrast || /high.?contrast/i.test(themeName)) actor.add_style_class_name('caramos-cc-high-contrast');
    }

    _applyMotion(actor, params) {
        if (!actor || !params) return;
        if (this._reducedMotion) {
            if (params.opacity !== undefined) actor.opacity = params.opacity;
            if (params.translation_y !== undefined) actor.translation_y = params.translation_y;
            if (params.onComplete) params.onComplete();
            return;
        }
        actor.ease(params);
    }

    _closeInlinePanel(reason = 'unknown') {
        ccDebug('inline-close-start', {
            reason,
            kind: this._expandedKind,
            visible: !!(this._expandedPanel && this._expandedPanel.visible),
            focus: ccActorDebug(global.stage.key_focus),
        });
        if (!this._expandedPanel || !this._expandedPanel.visible) {
            ccDebug('inline-close-noop', { reason });
            this._expandedBody = null;
            this._expandedKind = null;
            this._anchorRow = null;
            return;
        }
        this._applyDim(false);
        const closingKind = this._expandedKind;
        const animationGeneration = ++this._inlineAnimationGeneration;
        this._expandedPanel.remove_all_transitions();
        this._applyMotion(this._expandedPanel, {
            opacity: 0,
            translation_y: -6,
            duration: 140,
            mode: Clutter.AnimationMode.EASE_IN_QUAD,
            onComplete: () => {
                if (this._removed || animationGeneration !== this._inlineAnimationGeneration) return;
                ccDebug('inline-close-before-destroy', {
                    reason,
                    kind: closingKind,
                    focus: ccActorDebug(global.stage.key_focus),
                });
                this._restoreInlineFocus();
                ccDebug('inline-close-focus-transferred', { focus: ccActorDebug(global.stage.key_focus) });
                this._expandedPanel.destroy_all_children();
                this._expandedPanel.hide();
                this._expandedPanel.set_translation(0, 0, 0);
                this._expandedPanel.opacity = 255;
                ccDebug('inline-close-complete', { menuOpen: this.menu.isOpen, focus: ccActorDebug(global.stage.key_focus) });
            },
        });
        this._expandedBody = null;
        this._expandedKind = null;
        this._anchorRow = null;
        this._inlineCloseButton = null;
        this._bluetoothRenderSignature = '';
        if (this._bluetoothRefreshId) {
            Mainloop.source_remove(this._bluetoothRefreshId);
            this._bluetoothRefreshId = 0;
        }
    }

    _updateThemeClassesOnce() {
        this._updateThemeClasses();
    }

    _toggleInlinePanel(kind, iconName, title, fillFn, anchorRow) {
        if (this._expandedKind === kind && this._expandedPanel && this._expandedPanel.visible) {
            this._closeInlinePanel();
            return;
        }
        this._openInlinePanel(kind, iconName, title, fillFn, anchorRow);
    }

    _openInlinePanel(kind, iconName, title, fillFn, anchorRow) {
        ccDebug('inline-open', { kind, focus: ccActorDebug(global.stage.key_focus), anchor: ccActorDebug(anchorRow) });
        if (!this._expandedPanel || !this._container || !anchorRow) return;
        this._inlineFocusTarget = anchorRow === this._audioOutputGroup ? this._volumeRow.detailsButton
            : anchorRow === this._audioInputGroup ? this._micRow.detailsButton : anchorRow;
        this._inlineAnimationGeneration++;
        this._expandedPanel.remove_all_transitions();
        this._expandedPanel.destroy_all_children();
        this._expandedKind = kind;

        const card = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-card', x_expand: true });
        const head = new St.BoxLayout({ vertical: false, style_class: 'caramos-cc-inline-head' });
        head.add_child(createIcon(iconName, 'caramos-cc-inline-head-icon'));
        head.add_child(new St.Label({ text: title, style_class: 'caramos-cc-inline-title', y_align: Clutter.ActorAlign.CENTER }));
        head.add_child(new St.Widget({ x_expand: true }));
        const closeBtn = new St.Button({ style_class: 'caramos-cc-inline-close', reactive: true, can_focus: true, track_hover: true });
        setAccessibleName(closeBtn, `${_('Đóng')} ${title}`);
        closeBtn.set_child(createIcon('window-close-symbolic', 'caramos-cc-inline-close-icon'));
        closeBtn.connect('button-press-event', (_actor, event) => {
            ccDebug('inline-x-press', { kind: this._expandedKind, ...ccEventDebug(event), focus: ccActorDebug(global.stage.key_focus) });
            return Clutter.EVENT_PROPAGATE;
        });
        closeBtn.connect('clicked', () => {
            ccDebug('inline-x-clicked', { kind: this._expandedKind, focus: ccActorDebug(global.stage.key_focus) });
            this._closeInlinePanel('inline-x-click');
        });
        closeBtn.connect_after('button-release-event', (_actor, event) => {
            const primary = event.get_button && event.get_button() === Clutter.BUTTON_PRIMARY;
            ccDebug('inline-x-release-after', { kind: this._expandedKind, primary, ...ccEventDebug(event) });
            return primary ? Clutter.EVENT_STOP : Clutter.EVENT_PROPAGATE;
        });
        this._inlineCloseButton = closeBtn;
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
        this._applyMotion(this._expandedPanel, {
            opacity: 255,
            translation_y: 0,
            duration: 180,
            mode: Clutter.AnimationMode.EASE_OUT_QUAD,
        });
        this._applyDim(true);
        this._addOneShot(1, () => {
            if (kind.indexOf('audio-') === 0) {
                try { this.menu.actor.grab_key_focus(); } catch (e) { /* toolkit version */ }
            } else {
                this._focusFirstControl(body);
            }
        });
    }

    _applyDim(dim) {
        if (!this._container) return;
        const anchor = this._anchorRow;
        const duration = 180;
        const mode = Clutter.AnimationMode.EASE_OUT_QUAD;
        this._container.get_children().forEach(child => {
            const shouldStayBright = !dim || child === anchor || child === this._expandedPanel;
            this._applyMotion(child, { opacity: shouldStayBright ? 255 : 128, duration, mode });
        });
    }

    _returnToWifiInlinePanel() {
        this._closeOverlay();
        this._openInlinePanel('wifi', 'network-wireless-symbolic', _('Wi‑Fi'), body => this._fillWifiList(body), this._networkRow);
    }

    _openPowerOverlay() {
        this._toggleInlinePanel('power', 'system-shutdown-symbolic', _('Nguồn'),
            body => this._fillPowerList(body), this._header);
    }

    _addSessionAction(body, icon, label, method, capability) {
        if (!capability) return;
        body.add_child(createIconRow(icon, label, null, () => this._runSessionAction(method)));
    }

    _fillPowerList(body) {
        const state = this._sessionState || {};
        if (state.error) {
            body.add_child(new St.Label({ text: state.error, style_class: 'caramos-cc-expand-empty' }));
        }
        if (!state.available) {
            body.add_child(new St.Label({ text: _('Dịch vụ phiên không khả dụng'), style_class: 'caramos-cc-expand-empty' }));
            return;
        }
        if (state.pending) {
            body.add_child(new St.Label({ text: _('Đang xử lý…'), style_class: 'caramos-cc-expand-empty' }));
        }
        this._addSessionAction(body, 'media-playback-pause-symbolic', _('Tạm ngưng'), 'Suspend', state.canSuspend);
        this._addSessionAction(body, 'weather-clear-night-symbolic', _('Ngủ đông'), 'Hibernate', state.canHibernate);
        this._addSessionAction(body, 'view-refresh-symbolic', _('Khởi động lại…'), 'Restart', state.canRestart);
        this._addSessionAction(body, 'system-shutdown-symbolic', _('Tắt máy…'), 'Shutdown', state.canShutdown);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        this._addSessionAction(body, 'system-log-out-symbolic', _('Đăng xuất…'), 'Logout', state.canLogout);
        this._addSessionAction(body, 'system-users-symbolic', _('Chuyển người dùng…'), 'SwitchUser', state.canSwitchUser);
    }

    _closeSubmenus() {
        ccDebug('close-submenus', { menuOpen: !!(this.menu && this.menu.isOpen), kind: this._expandedKind });
        if (this._menuAlignId) {
            Mainloop.source_remove(this._menuAlignId);
            this._menuAlignId = 0;
        }
        this._closeOverlay();
        if (this._bluezBackend) {
            const state = this._bluezBackend.snapshot();
            if (state && state.adapter && state.adapter.discovering) this._bluezBackend.stopDiscovery();
        }
        this._closeInlinePanel();
    }

    _runSessionAction(method) {
        if (!this._sessionBackend || !this._sessionBackend.action(method)) return;
        this._closeInlinePanel();
    }

    _onSessionStateChanged(state) {
        this._sessionState = state;
        if (this._expandedKind === 'power' && this._expandedBody) {
            this._expandedBody.destroy_all_children();
            this._fillPowerList(this._expandedBody);
        }
    }

    _toggleStreamMute(stream) {
        if (!stream) return;
        stream.change_is_muted(!stream.is_muted);
    }

    _audioDevice(type, id) {
        if (!this._control) return null;
        try {
            return this._control[`lookup_${type}_id`](id);
        } catch (e) {
            return null;
        }
    }

    _onAudioDeviceAdded(type, id) {
        const device = this._audioDevice(type, id);
        if (!device || this._audioDevices[type].some(info => info.id === id)) return;
        this._audioDevices[type].push({
            id,
            description: device.description || device.origin || (type === 'output' ? _('Thiết bị phát') : _('Thiết bị thu')),
            origin: device.origin || '',
        });
        this._audioDevices[type].sort((left, right) => left.description.localeCompare(right.description));
        this._refreshAudioDeviceUi(type);
    }

    _onAudioDeviceRemoved(type, id) {
        this._audioDevices[type] = this._audioDevices[type].filter(info => info.id !== id);
        this._refreshAudioDeviceUi(type);
    }

    _refreshAudioDeviceUi(type) {
        const row = type === 'output' ? this._volumeRow : this._micRow;
        const button = row && row.detailsButton;
        if (button) {
            const enabled = this._audioAvailable && this._audioDevices[type].length > 0;
            button.reactive = enabled;
            button.can_focus = enabled;
            if (enabled) button.remove_style_class_name('caramos-cc-disabled');
            else button.add_style_class_name('caramos-cc-disabled');
        }
        if (this._expandedKind !== `audio-${type}` || !this._expandedBody) return;
        if (this._audioDeviceRefreshIds[type]) return;
        this._audioDeviceRefreshIds[type] = Mainloop.idle_add(() => {
            this._audioDeviceRefreshIds[type] = 0;
            if (!this._removed && this._expandedKind === `audio-${type}` && this._expandedBody) {
                this._fillAudioDeviceList(this._expandedBody, type);
            }
            return false;
        });
    }

    _onAudioDeviceUpdate(type, id) {
        this._activeAudioDeviceIds[type] = typeof id === 'number' ? id : -1;
        if (type === 'output') this._readOutput();
        else this._readInput();
        this._refreshAudioDeviceUi(type);
    }

    _openAudioOverlay(type) {
        const output = type === 'output';
        this._toggleInlinePanel(
            `audio-${type}`,
            output ? 'audio-speakers-symbolic' : 'audio-input-microphone-symbolic',
            output ? _('Thiết bị phát âm thanh') : _('Thiết bị thu âm'),
            body => this._fillAudioDeviceList(body, type),
            output ? this._audioOutputGroup : this._audioInputGroup
        );
    }

    _fillAudioDeviceList(body, type) {
        body.destroy_all_children();
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });
        const devices = this._audioDevices[type] || [];
        const activeId = this._activeAudioDeviceIds[type];
        if (!devices.length) {
            list.add_child(new St.Label({ text: _('Không có thiết bị âm thanh'), style_class: 'caramos-cc-expand-empty' }));
        } else {
            devices.forEach(info => {
                const activate = () => {
                    const device = this._audioDevice(type, info.id);
                    if (device) this._control[`change_${type}`](device);
                };
                const item = createAudioDeviceRow(
                    type === 'output' ? 'audio-speakers-symbolic' : 'audio-input-microphone-symbolic',
                    info.origin ? `${info.description} · ${info.origin}` : info.description,
                    info.id === activeId,
                    activate
                );
                if (this._audioPointerSelection[type] && this._audioPointerDeviceIds[type] === info.id) {
                    item.actor.add_style_class_name('caramos-cc-audio-pointer-selection');
                }
                item.actor.connect('button-press-event', () => {
                    this._audioPointerSelection[type] = true;
                    this._audioPointerDeviceIds[type] = info.id;
                    item.actor.add_style_class_name('caramos-cc-audio-pointer-selection');
                    return Clutter.EVENT_PROPAGATE;
                });
                item.actor.connect('key-press-event', () => {
                    this._audioPointerSelection[type] = false;
                    this._audioPointerDeviceIds[type] = -1;
                    item.actor.remove_style_class_name('caramos-cc-audio-pointer-selection');
                    return Clutter.EVENT_PROPAGATE;
                });
                list.add_child(item.actor);
            });
        }
        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        body.add_child(createIconRow('preferences-desktop-sound-symbolic', _('Mở cài đặt âm thanh'), null, () => {
            this._closeSubmenus();
            ccDebug('menu-close-explicit-sound-settings', { menuOpen: !!(this.menu && this.menu.isOpen) });
            if (this.menu && this.menu.isOpen) this.menu.close();
            this._addOneShot(1, () => spawnAllowed('soundSettings'));
        }));
    }

    _applyStreamVolume(stream, value) {
        if (!stream || !this._volumeNorm) return;
        const volume = Math.round(this._volumeNorm * value / 100);
        stream.volume = Math.max(0, Math.min(this._volumeMax, volume));
        stream.push_volume();
        if (stream.is_muted && value > 0) stream.change_is_muted(false);
    }

    _setAudioSliderDragging(type, dragging) {
        this._audioSliderDragging[type] = dragging;
        if (!dragging) this._scheduleAudioSync();
    }

    _scheduleAudioSync() {
        if (this._audioSyncId) return;
        this._audioSyncId = Mainloop.timeout_add(120, () => {
            this._audioSyncId = 0;
            this._syncAudioUi();
            return false;
        });
    }

    _syncAudioUi() {
        if (this._removed) return;
        const output = this._output;
        const input = this._input;
        const volume = this._streamPercent(output);
        const mic = this._streamPercent(input);
        this._panelVolumeIcon.set_icon_name(this._volumeIconName(volume, output && output.is_muted));
        this._volumeRow.icon.set_icon_name(this._volumeIconName(volume, output && output.is_muted));
        this._micRow.icon.set_icon_name(input && input.is_muted
            ? 'microphone-sensitivity-muted-symbolic' : 'microphone-sensitivity-high-symbolic');
        if (!this._audioSliderDragging.output && !this._outputVolumeApplyId) {
            const displayedVolume = this._outputVolumePending === null ? volume : this._outputVolumePending;
            this._updatingSliders = true;
            this._volumeRow.slider.setValue(displayedVolume / 100);
            this._updatingSliders = false;
            this._outputVolumePending = null;
        }
        if (!this._audioSliderDragging.input && !this._inputVolumeApplyId) {
            const displayedMic = this._inputVolumePending === null ? mic : this._inputVolumePending;
            this._updatingSliders = true;
            this._micRow.slider.setValue(displayedMic / 100);
            this._updatingSliders = false;
            this._inputVolumePending = null;
        }
    }

    _setStreamVolume(stream, value) {
        if (!stream || !this._volumeNorm) return;
        const isOutput = stream === this._output;
        const sourceKey = isOutput ? '_outputVolumeApplyId' : '_inputVolumeApplyId';
        const pendingKey = isOutput ? '_outputVolumePending' : '_inputVolumePending';

        this[pendingKey] = value;
        if (this[sourceKey]) Mainloop.source_remove(this[sourceKey]);
        this[sourceKey] = Mainloop.timeout_add(90, () => {
            const pending = this[pendingKey];
            this[sourceKey] = 0;
            this._applyStreamVolume(stream, pending);
            this._scheduleAudioSync();
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
            this._audioAvailable = true;
            this._readOutput();
            this._readInput();
            this._refresh();
        } else {
            this._audioAvailable = false;
            this._audioDevices = { output: [], input: [] };
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
            this._outputVolumeChangedId = this._output.connect('notify::volume', () => this._scheduleAudioSync());
            this._outputMutedChangedId = this._output.connect('notify::is-muted', () => this._scheduleAudioSync());
        }
        this._syncAudioUi();
    }

    _readInput() {
        if (this._input && this._inputVolumeChangedId) this._input.disconnect(this._inputVolumeChangedId);
        if (this._input && this._inputMutedChangedId) this._input.disconnect(this._inputMutedChangedId);
        this._inputVolumeChangedId = 0;
        this._inputMutedChangedId = 0;
        this._input = this._control.get_default_source();
        if (this._input) {
            this._inputVolumeChangedId = this._input.connect('notify::volume', () => this._scheduleAudioSync());
            this._inputMutedChangedId = this._input.connect('notify::is-muted', () => this._scheduleAudioSync());
        }
        this._syncAudioUi();
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
        const generation = ++this._brightnessRequestGeneration;
        try {
            Interfaces.getDBusProxyAsync(BRIGHTNESS_BUS_NAME, Lang.bind(this, function (proxy, error) {
                if (this._removed || generation !== this._brightnessRequestGeneration) return;
                if (error || !proxy) {
                    this._disableBrightness();
                    return;
                }
                this._brightnessProxy = proxy;
                this._brightnessProxy.GetPercentageRemote(Lang.bind(this, function (value, getError) {
                    if (this._removed || generation !== this._brightnessRequestGeneration) return;
                    if (getError) {
                        this._disableBrightness();
                        return;
                    }
                    this._brightnessReady = true;
                    this._updateBrightness(value);
                    this._brightnessSignalId = this._brightnessProxy.connectSignal('Changed', () => this._readBrightness());
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
            this._brightnessRow.actor.hide();
        }
    }

    _readBrightness() {
        if (this._removed || !this._brightnessReady || !this._brightnessProxy) return;
        if (this._brightnessSliderDragging || this._brightnessApplyId || this._brightnessInFlight) {
            this._scheduleBrightnessSync();
            return;
        }
        const generation = this._brightnessWriteGeneration;
        this._brightnessProxy.GetPercentageRemote(Lang.bind(this, function (value, error) {
            if (this._removed || error || generation !== this._brightnessWriteGeneration) return;
            this._brightnessPending = null;
            this._updateBrightness(value);
        }));
    }

    _updateBrightness(value) {
        const numericValue = Number(value);
        if (!Number.isFinite(numericValue) || numericValue < 0) {
            this._disableBrightness();
            return;
        }
        const percent = Math.max(0, Math.min(100, Math.round(numericValue)));
        setSliderEnabled(this._brightnessRow, true);
        this._brightnessRow.actor.show();
        if (this._brightnessSliderDragging || this._brightnessApplyId || this._brightnessInFlight || this._brightnessPending !== null) return;
        this._updatingSliders = true;
        this._brightnessRow.slider.setValue(percent / 100);
        this._updatingSliders = false;
    }

    _setBrightnessSliderDragging(dragging) {
        this._brightnessSliderDragging = dragging;
        if (!dragging) this._scheduleBrightnessSync();
    }

    _scheduleBrightnessSync() {
        if (this._brightnessSyncId) Mainloop.source_remove(this._brightnessSyncId);
        this._brightnessSyncId = Mainloop.timeout_add(140, () => {
            this._brightnessSyncId = 0;
            if (!this._brightnessSliderDragging && !this._brightnessApplyId && !this._brightnessInFlight) this._readBrightness();
            return false;
        });
    }

    _setBrightness(value) {
        if (!this._brightnessReady || !this._brightnessProxy) {
            this._disableBrightness();
            return;
        }
        const percent = Math.max(0, Math.min(100, Math.round(value)));
        this._brightnessPending = percent;
        const generation = ++this._brightnessWriteGeneration;
        if (this._brightnessApplyId) Mainloop.source_remove(this._brightnessApplyId);
        this._brightnessApplyId = Mainloop.timeout_add(90, () => {
            this._brightnessApplyId = 0;
            if (this._removed || generation !== this._brightnessWriteGeneration || !this._brightnessProxy) return false;
            this._brightnessInFlight = true;
            this._brightnessProxy.SetPercentageRemote(percent, Lang.bind(this, function (_result, error) {
                if (this._removed || generation !== this._brightnessWriteGeneration) return;
                this._brightnessInFlight = false;
                if (error) global.logError(error);
                this._scheduleBrightnessSync();
            }));
            return false;
        });
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
        tile.tile.set_style_class_name(
            `caramos-cc-split-tile${active ? ' caramos-cc-tile-active' : ''}${loading ? ' caramos-cc-loading' : ''}${tile.enabled === false ? ' caramos-cc-disabled' : ''}`
        );
        this._setTileLoading(tile, loading);
    }

    _setSimpleTileState(tile, active, loading) {
        tile.tile.set_style_class_name(
            `caramos-cc-simple-tile${active ? ' caramos-cc-tile-active' : ''}${loading ? ' caramos-cc-loading' : ''}${tile.enabled === false ? ' caramos-cc-disabled' : ''}`
        );
        this._setTileLoading(tile, loading);
    }

    _toggleNightLight() {
        if (!this._nightLightSettings) return;
        const enabled = this._nightLightSettings.get_boolean(NIGHT_LIGHT_KEY);
        const target = !enabled;
        this._setSimpleTileState(this._nightLightTile, target, true);
        this._nightLightSettings.set_boolean(NIGHT_LIGHT_KEY, target);
        this._addOneShot(1000, () => this._refresh());
    }

    _openSettings(command) {
        ccDebug('menu-close-explicit-open-settings', { menuOpen: !!(this.menu && this.menu.isOpen) });
        if (this.menu && this.menu.isOpen) this.menu.close();
        spawnAllowed(command);
    }

    _toggleWifi() {
        const state = this._wifiBackend ? this._wifiBackend.snapshot() : null;
        if (!state || !state.available || !state.hardwareEnabled) {
            this._openSettings('networkSettings');
            return;
        }
        const target = !state.enabled;
        this._wifiPendingTarget = target;
        this._wifiTile.subtitleLabel.set_text(target ? _('Bật') : _('Tắt'));
        this._setSplitTileState(this._wifiTile, target, true);
        if (!this._wifiBackend.setEnabled(target)) {
            this._wifiPendingTarget = null;
            this._onWifiStateChanged(state);
        }
    }

    _onWifiStateChanged(state) {
        this._wifiState = state;
        if (!this._wifiTile) return;
        if (this._wifiPendingTarget !== null && state.enabled === this._wifiPendingTarget) this._wifiPendingTarget = null;
        const active = state.networks.find(network => network.active) || null;
        const pending = this._wifiPendingTarget !== null;
        const renderedEnabled = pending ? this._wifiPendingTarget : state.enabled;
        setTileEnabled(this._wifiTile, state.available && state.hardwareEnabled);
        this._wifiTile.subtitleLabel.set_text(
            !state.available ? _('Không có thiết bị')
                : !state.hardwareEnabled ? _('Bị chặn bởi phần cứng')
                    : pending ? (this._wifiPendingTarget ? _('Bật') : _('Tắt'))
                        : !state.enabled ? _('Tắt')
                            : active ? active.ssid : _('Bật')
        );
        this._setSplitTileState(
            this._wifiTile,
            !!(state.available && state.hardwareEnabled && renderedEnabled),
            pending || state.scanning
        );
        if (this._expandedKind === 'wifi' && this._expandedBody) this._fillWifiList(this._expandedBody);
    }

    _onBluezStateChanged(state) {
        this._bluezState = state;
        if (!this._bluetoothTile) return;
        const powered = !!(state.available && state.adapter && state.adapter.powered);
        setTileEnabled(this._bluetoothTile, state.available);
        this._setBluetoothUi(powered);
        if (this._expandedKind === 'bluetooth' && this._expandedBody) this._scheduleBluetoothListRefresh();
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

    _toggleBluetooth() {
        const bluezState = this._bluezBackend ? this._bluezBackend.snapshot() : null;
        if (bluezState && bluezState.available && bluezState.adapter) {
            const target = !bluezState.adapter.powered;
            this._bluetoothTile.subtitleLabel.set_text(target ? _('Bật') : _('Tắt'));
            this._setSplitTileState(this._bluetoothTile, target, true);
            if (!this._bluezBackend.setPowered(target)) {
                this._setBluetoothUi(bluezState.adapter.powered);
            }
            return;
        }
        this._openSettings('bluetoothSettings');
    }

    _normalizeVpnType(type) {
        const normalized = String(type || '').toLowerCase();
        if (normalized === 'wireguard') return 'wireguard';
        if (normalized === 'vpn') return 'vpn';
        return '';
    }

    _parseVpnState(activeOutput, savedOutput) {
        const activeByUuid = {};
        activeOutput.split('\n').forEach(line => {
            const fields = this._splitNmcliEscaped(line);
            const type = this._normalizeVpnType(fields[2]);
            if (!type || !fields[0]) return;
            activeByUuid[fields[0]] = true;
        });

        const profiles = [];
        savedOutput.split('\n').forEach(line => {
            const fields = this._splitNmcliEscaped(line);
            const type = this._normalizeVpnType(fields[2]);
            if (!type || !fields[0]) return;
            profiles.push({
                uuid: fields[0],
                name: fields[1] || _('VPN'),
                type,
                active: !!activeByUuid[fields[0]],
            });
        });
        profiles.sort((left, right) => {
            if (left.active !== right.active) return left.active ? -1 : 1;
            return left.name.localeCompare(right.name);
        });
        return profiles;
    }

    _queryVpnState(showLoading) {
        const networkAvailable = this._networkBackend && this._networkBackend.available;
        if (!networkAvailable || !commandExists('nmcli')) {
            this._vpnQueryGeneration++;
            this._vpnQueryInFlight = false;
            this._vpnRefreshQueued = false;
            this._setVpnUi({ available: false, loading: false, profiles: [], error: '' });
            return;
        }
        if (this._vpnQueryInFlight) {
            this._vpnRefreshQueued = true;
            return;
        }

        const generation = ++this._vpnQueryGeneration;
        this._vpnQueryInFlight = true;
        this._setVpnUi({ ...this._vpnState, available: true, loading: showLoading === true });
        commandOutputAsync([
            'nmcli', '-t', '--escape', 'yes', '-f', 'UUID,NAME,TYPE', 'connection', 'show', '--active'
        ], 2, (activeOk, activeOutput, activeError) => {
            if (this._removed || generation !== this._vpnQueryGeneration) return;
            if (!activeOk) {
                this._finishVpnQuery(generation, null, activeError);
                return;
            }
            commandOutputAsync([
                'nmcli', '-t', '--escape', 'yes', '-f', 'UUID,NAME,TYPE', 'connection', 'show'
            ], 2, (savedOk, savedOutput, savedError) => {
                if (this._removed || generation !== this._vpnQueryGeneration) return;
                const profiles = savedOk ? this._parseVpnState(activeOutput, savedOutput) : null;
                this._finishVpnQuery(generation, profiles, savedError);
            });
        });
    }

    _finishVpnQuery(generation, profiles, error) {
        if (this._removed || generation !== this._vpnQueryGeneration) return;
        this._vpnQueryInFlight = false;
        const networkAvailable = this._networkBackend && this._networkBackend.available;
        this._setVpnUi({
            available: !!networkAvailable,
            loading: false,
            profiles: profiles || [],
            error: profiles ? '' : error || _('Không thể đọc trạng thái VPN'),
        });
        if (this._vpnRefreshQueued) {
            this._vpnRefreshQueued = false;
            this._queryVpnState(false);
        }
    }

    _splitNmcliEscaped(line) {
        const fields = [];
        let value = '';
        let escaped = false;
        for (let i = 0; i < String(line || '').length; i++) {
            const character = line[i];
            if (escaped) {
                value += character;
                escaped = false;
            } else if (character === '\\') {
                escaped = true;
            } else if (character === ':') {
                fields.push(value);
                value = '';
            } else {
                value += character;
            }
        }
        if (escaped) value += '\\';
        fields.push(value);
        return fields;
    }

    _setVpnUi(state) {
        if (this._vpnState && this._vpnState.error && !state.error) state.error = this._vpnState.error;
        this._vpnState = state;
        if (!this._vpnTile) return;
        const active = state.profiles.filter(profile => profile.active);
        setTileEnabled(this._vpnTile, state.available);
        this._vpnTile.subtitleLabel.set_text(
            !state.available ? _('Không khả dụng')
                : active.length === 1 ? active[0].name
                    : active.length > 1 ? _(`${active.length} kết nối đang hoạt động`)
                        : state.profiles.length ? _('Chưa kết nối') : _('Không có cấu hình')
        );
        this._setSplitTileState(this._vpnTile, active.length > 0, this._vpnActionPending || state.loading);
        if (active.length) this._panelVpnIcon.show();
        else this._panelVpnIcon.hide();
        if (this._expandedKind === 'vpn' && this._expandedBody) this._fillVpnList(this._expandedBody);
    }

    _refreshVpnState(showLoading) {
        this._queryVpnState(showLoading === true);
    }

    _toggleVpn() {
        if (!this._vpnState.available) {
            this._openSettings('networkSettings');
            return;
        }
        const active = this._vpnState.profiles.filter(profile => profile.active);
        if (active.length === 1) {
            this._setVpnProfileActive(active[0], false);
            return;
        }
        if (active.length > 1) {
            this._openVpnOverlay();
            return;
        }
        this._openVpnOverlay();
    }

    _setVpnProfileActive(profile, active) {
        if (!profile || !profile.uuid || this._vpnActionPending) return;
        this._vpnActionPending = true;
        this._setSplitTileState(this._vpnTile, active, true);
        spawnArgvChecked(['nmcli', 'connection', active ? 'up' : 'down', 'uuid', profile.uuid], (success, error) => {
            this._vpnActionPending = false;
            this._vpnState.error = success ? '' : error || _('Không thể thay đổi VPN');
            this._refreshVpnState();
            if (success) this._scheduleVpnRefresh();
        });
    }

    _scheduleVpnRefresh() {
        if (this._vpnRefreshId) Mainloop.source_remove(this._vpnRefreshId);
        this._vpnRefreshId = Mainloop.timeout_add_seconds(1, () => {
            this._vpnRefreshId = 0;
            this._refreshVpnState();
            return false;
        });
    }

    _vpnProfileSubtitle(profile) {
        return profile.active
            ? profile.type === 'wireguard' ? _('WireGuard đang hoạt động') : _('Đang hoạt động')
            : profile.type === 'wireguard' ? _('WireGuard') : _('Đã ngắt kết nối');
    }

    _fillVpnList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();
        const state = this._vpnState;
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });
        if (!state.available) {
            list.add_child(new St.Label({ text: _('NetworkManager không khả dụng'), style_class: 'caramos-cc-expand-empty' }));
        } else if (state.loading && !state.profiles.length) {
            list.add_child(new St.Label({ text: _('Đang đọc cấu hình VPN…'), style_class: 'caramos-cc-expand-empty' }));
        } else if (state.error) {
            list.add_child(new St.Label({ text: state.error, style_class: 'caramos-cc-expand-empty' }));
            list.add_child(createIconRow('view-refresh-symbolic', _('Thử lại'), null, () => this._refreshVpnState()));
        } else if (!state.profiles.length) {
            list.add_child(new St.Label({ text: _('Không có cấu hình VPN'), style_class: 'caramos-cc-expand-empty' }));
        } else {
            state.profiles.slice(0, VPN_LIST_LIMIT).forEach(profile => {
                const button = createIconRow(
                    profile.type === 'wireguard' ? 'network-vpn-symbolic' : 'network-vpn-symbolic',
                    `${profile.name} · ${this._vpnProfileSubtitle(profile)}`,
                    profile.active ? 'object-select-symbolic' : null,
                    () => this._setVpnProfileActive(profile, !profile.active)
                );
                list.add_child(button);
            });
        }
        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        body.add_child(createIconRow('preferences-system-symbolic', _('Mở cài đặt VPN'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('networkSettings');
        }));
    }

    _openVpnOverlay() {
        this._toggleInlinePanel('vpn', 'network-vpn-symbolic', _('VPN'), body => this._fillVpnList(body), this._connectionsRow);
    }

    _openEthernetOverlay() {
        this._toggleInlinePanel('ethernet', 'network-wired-symbolic', _('Mạng dây'), body => {
            this._fillEthernetList(body);
        }, this._networkRow);
    }

    _networkDetailText(label, value) {
        return value ? `${label}: ${value}` : '';
    }

    _fillEthernetList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();
        const state = this._readNetworkState();
        const devices = state.devices.filter(device => device.type === 'ethernet');
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });
        if (!state.available) {
            list.add_child(new St.Label({ text: _('NetworkManager không khả dụng'), style_class: 'caramos-cc-expand-empty' }));
        } else if (!devices.length) {
            list.add_child(new St.Label({ text: _('Không có thiết bị mạng dây'), style_class: 'caramos-cc-expand-empty' }));
        } else {
            devices.forEach(device => {
                const marker = device.device === state.defaultDevice ? _(' · tuyến mặc định') : '';
                list.add_child(createIconRow(
                    device.active ? 'network-wired-symbolic' : 'network-wired-disconnected-symbolic',
                    `${device.device || _('Mạng dây')}${marker}`,
                    device.active ? 'object-select-symbolic' : null,
                    () => this._openSettings('networkSettings')
                ));
                const lines = [
                    this._networkDetailText(_('Trạng thái'), networkDeviceStateText(device.state)),
                    this._networkDetailText(_('Cấu hình'), device.connection),
                    this._networkDetailText(_('Liên kết'), device.carrier === null ? '' : device.carrier ? _('Có tín hiệu') : _('Mất tín hiệu')),
                    this._networkDetailText(_('Tốc độ'), device.speed ? `${device.speed} Mb/s` : ''),
                    this._networkDetailText(_('Địa chỉ'), device.addresses.join(', ')),
                    this._networkDetailText(_('Cổng mạng'), device.gateway),
                    this._networkDetailText(_('DNS'), device.dns.join(', ')),
                ].filter(Boolean);
                if (lines.length) {
                    list.add_child(new St.Label({
                        text: lines.join('\n'),
                        style_class: 'caramos-cc-expand-empty',
                        x_align: Clutter.ActorAlign.START,
                    }));
                }
            });
        }
        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        if (state.connectivity === 2 || state.connectivity === 3) {
            body.add_child(createIconRow('web-browser-symbolic', _('Mở trang đăng nhập mạng'), null, () => {
                this._closeInlinePanel();
                spawnArgvAsync(['xdg-open', 'http://nmcheck.gnome.org/']);
            }));
        }
        body.add_child(createIconRow('preferences-system-symbolic', _('Mở cài đặt mạng'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('networkSettings');
        }));
    }

    _openWifiOverlay() {
        this._toggleInlinePanel('wifi', 'network-wireless-symbolic', _('Wi‑Fi'), body => {
            if (this._wifiBackend) this._wifiBackend.requestScan();
            this._fillWifiList(body);
        }, this._networkRow);
    }

    _openBluetoothOverlay() {
        this._toggleInlinePanel('bluetooth', 'bluetooth-symbolic', _('Bluetooth'), body => {
            const state = this._bluezBackend ? this._bluezBackend.snapshot() : null;
            if (state && state.available && state.adapter && state.adapter.powered && !state.adapter.discovering) {
                this._bluezBackend.startDiscovery();
            }
            this._fillBluetoothList(body);
        }, this._connectionsRow);
    }

    _fillWifiList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();

        const state = this._wifiBackend ? this._wifiBackend.snapshot() : null;
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });
        if (!state || !state.available) {
            list.add_child(new St.Label({ text: _('Không có thiết bị Wi‑Fi'), style_class: 'caramos-cc-expand-empty' }));
        } else if (!state.hardwareEnabled) {
            list.add_child(new St.Label({ text: _('Wi‑Fi bị chặn bởi phần cứng'), style_class: 'caramos-cc-expand-empty' }));
        } else if (!state.enabled) {
            list.add_child(new St.Label({ text: _('Wi‑Fi đang tắt'), style_class: 'caramos-cc-expand-empty' }));
        } else if (!state.networks.length) {
            list.add_child(new St.Label({
                text: state.scanning ? _('Đang tìm mạng Wi‑Fi…') : _('Không thấy mạng Wi‑Fi'),
                style_class: 'caramos-cc-expand-empty',
            }));
        } else {
            state.networks.slice(0, WIFI_LIST_LIMIT).forEach(network => {
                list.add_child(createIconRow(
                    wifiSignalIcon(network.strength, network.secure),
                    network.ssid,
                    network.active ? 'object-select-symbolic' : null,
                    () => this._onWifiNetworkClicked(network)
                ));
            });
        }
        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        if (state && state.available && state.enabled) {
            body.add_child(createIconRow('view-refresh-symbolic', _('Tìm lại mạng Wi‑Fi'), null, () => {
                if (this._wifiBackend) this._wifiBackend.requestScan();
            }));
        }
        body.add_child(createIconRow('preferences-system-symbolic', _('Mở cài đặt mạng'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('networkSettings');
        }));
    }

    _onWifiNetworkClicked(network) {
        if (!this._wifiBackend || !network) return;
        if (!network.active && network.secure && !network.saved) {
            this._closeInlinePanel();
            this._openSettings('networkSettings');
            return;
        }
        this._wifiActionPending = true;
        this._setSplitTileState(this._wifiTile, !network.active, true);
        if (!this._wifiBackend.activate(network)) {
            this._wifiPendingTarget = null;
            this._openSettings('networkSettings');
        }
    }

    _fillBluetoothList(body) {
        body = body || this._expandedBody;
        if (!body) return;
        body.destroy_all_children();

        const bluezState = this._bluezBackend ? this._bluezBackend.snapshot() : null;
        const bluezDevices = bluezState && bluezState.available ? bluezState.devices : [];
        const list = new St.BoxLayout({ vertical: true, style_class: 'caramos-cc-inline-list' });
        if (bluezState && bluezState.adapter && bluezState.adapter.discovering) {
            list.add_child(new St.Label({
                text: _('Đang tìm thiết bị Bluetooth…'),
                style_class: 'caramos-cc-expand-empty',
            }));
        }

        if (bluezDevices.length) {
            bluezDevices.slice(0, BT_LIST_LIMIT).forEach(device => {
                const label = device.battery === null ? device.name : `${device.name} · ${device.battery}%`;
                list.add_child(createIconRow(
                    'bluetooth-symbolic',
                    label,
                    device.connected ? 'object-select-symbolic' : null,
                    () => this._onBluezDeviceClicked(device)
                ));
            });
        } else {
            list.add_child(new St.Label({
                text: bluezState && bluezState.available
                    ? _('Không có thiết bị khả dụng hoặc đã kết nối')
                    : _('BlueZ không khả dụng; mở cài đặt Bluetooth'),
                style_class: 'caramos-cc-expand-empty',
            }));
        }

        body.add_child(list);
        body.add_child(new St.Widget({ style_class: 'caramos-cc-expand-separator' }));
        const discovering = !!(bluezState && bluezState.adapter && bluezState.adapter.discovering);
        body.add_child(createIconRow(
            discovering ? 'media-playback-stop-symbolic' : 'view-refresh-symbolic',
            discovering ? _('Dừng tìm thiết bị') : _('Tìm thiết bị mới'),
            null,
            () => {
                if (!this._bluezBackend) return;
                if (discovering) this._bluezBackend.stopDiscovery();
                else this._bluezBackend.startDiscovery();
            }
        ));
        body.add_child(createIconRow('preferences-system-symbolic', _('Cài đặt Bluetooth'), null, () => {
            this._closeInlinePanel();
            spawnAllowed('bluetoothSettings');
        }));
    }

    _onBluezDeviceClicked(device) {
        if (!this._bluezBackend) return;
        this._bluezBackend.callDevice(device, device.connected ? 'Disconnect' : 'Connect');
    }

    _refresh() {
        const battery = this._readBatteryStatus();
        const networkState = this._renderNetworkState();
        if (battery.available) {
            this._panelBatteryLabel.set_text(battery.percentText);
            this._panelBatteryIcon.set_gicon(Gio.icon_new_for_string(battery.icon));
            this._panelBatteryLabel.show();
            this._panelBatteryIcon.show();
            if (this._batteryPill) {
                this._batteryPill.get_child().get_children()[0].set_gicon(Gio.icon_new_for_string(battery.icon));
                this._updateBatteryUi(this._powerState.battery);
                this._batteryPill.show();
            }
        } else {
            this._panelBatteryLabel.hide();
            this._panelBatteryIcon.hide();
            if (this._batteryPill) this._batteryPill.hide();
        }

        const volume = this._streamPercent(this._output);
        const mic = this._streamPercent(this._input);
        setSliderEnabled(this._volumeRow, this._audioAvailable && this._output !== null);
        setSliderEnabled(this._micRow, this._audioAvailable && this._input !== null);
        this._refreshAudioDeviceUi('output');
        this._refreshAudioDeviceUi('input');
        this._syncAudioUi();
        if (this._audioSliderDragging.output || this._audioSliderDragging.input) {
            // Keep local drag position stable while backend emits Cvc notifications.
        } else {
            this._scheduleAudioSync();
        }

        if (this._recordingAppsNum > 0) this._panelMicIcon.show();
        else this._panelMicIcon.hide();

        const bluezState = this._bluezBackend ? this._bluezBackend.snapshot() : null;
        const hasBluetooth = !!(bluezState && bluezState.available && bluezState.adapter);
        setTileEnabled(this._bluetoothTile, hasBluetooth);
        if (hasBluetooth) {
            this._setBluetoothUi(!!bluezState.adapter.powered);
        } else {
            this._bluetoothTile.subtitleLabel.set_text(_('Không khả dụng'));
            this._setSplitTileState(this._bluetoothTile, false, false);
        }

        setTileEnabled(this._nightLightTile, this._nightLightSettings !== null);
        if (this._nightLightSettings) {
            const enabled = this._nightLightSettings.get_boolean(NIGHT_LIGHT_KEY);
            this._nightLightTile.subtitleLabel.set_text(enabled ? _('Đang bật') : _('Đang tắt'));
            this._setSimpleTileState(this._nightLightTile, enabled, false);
        } else {
            this._nightLightTile.subtitleLabel.set_text(_('Không khả dụng'));
            this._setSimpleTileState(this._nightLightTile, false, false);
        }
    }

    _onNetworkStateChanged(state) {
        this._networkState = state;
        if (this._ethernetTile && this._wifiTile) this._renderNetworkState();
        if (this._vpnTile) this._refreshVpnState();
    }

    _renderNetworkState() {
        const networkState = this._readNetworkState();
        this._panelNetworkIcon.set_icon_name(
            !networkState.primary ? 'network-offline-symbolic'
                : networkState.primary.type === 'ethernet' ? 'network-wired-symbolic'
                    : networkState.primary.type === 'wifi' ? 'network-wireless-symbolic'
                        : 'network-transmit-receive-symbolic'
        );
        this._updateNetworkTiles(networkState);
        return networkState;
    }

    _networkDeviceConnected(device) {
        if (!device) return false;
        return device.state === 'connected' || device.state === 100;
    }

    _readNetworkState() {
        const snapshot = this._networkBackend ? this._networkBackend.snapshot() : null;
        const base = emptyNetworkState(snapshot, this._networkBackend);
        base.devices = Array.isArray(base.devices) ? base.devices : [];
        base.ethernetDevices = base.devices.filter(device => device.type === 'ethernet');
        base.wifiDevices = base.devices.filter(device => device.type === 'wifi');
        base.ethernet = base.ethernetDevices[0] || null;
        base.wifi = base.wifiDevices[0] || null;
        base.defaultDevice = base.primaryDevice || (base.primary ? base.primary.device : '');
        return base;
    }

    _readNetworkIcon() {
        const state = this._readNetworkState();
        if (!state.primary) return 'network-offline-symbolic';
        if (state.primary.type === 'ethernet') return 'network-wired-symbolic';
        if (state.primary.type === 'wifi') return 'network-wireless-symbolic';
        return 'network-transmit-receive-symbolic';
    }

    _updateNetworkTiles(state) {
        const ethernetAvailable = state.available && !!state.ethernet;
        const wifiAvailable = state.available && !!state.wifi;
        const ethernetConnected = ethernetAvailable && this._networkDeviceConnected(state.ethernet);
        const wifiConnected = wifiAvailable && this._networkDeviceConnected(state.wifi);

        setTileEnabled(this._ethernetTile, ethernetAvailable);
        this._ethernetTile.subtitleLabel.set_text(
            !state.available ? _('Không khả dụng')
                : !ethernetAvailable ? _('Không có thiết bị')
                    : ethernetConnected ? (state.defaultDevice === state.ethernet.device ? _('Đang dùng Internet') : networkDeviceStateText(state.ethernet.state))
                        : networkDeviceStateText(state.ethernet.state)
        );
        if (state.connectivity && state.connectivity !== 4 && ethernetConnected) {
            this._ethernetTile.subtitleLabel.set_text(networkConnectivityText(state.connectivity));
        }
        this._setSplitTileState(this._ethernetTile, ethernetConnected, false);

        if (!this._wifiBackend || !this._wifiBackend.snapshot().available) {
            setTileEnabled(this._wifiTile, wifiAvailable);
            const wifiName = wifiAvailable && state.wifi.connection ? state.wifi.connection : '';
            this._wifiTile.subtitleLabel.set_text(
                !state.available ? _('Không khả dụng')
                    : !wifiAvailable ? _('Không có thiết bị')
                        : wifiConnected ? (wifiName || networkDeviceStateText(state.wifi.state))
                            : networkDeviceStateText(state.wifi.state)
            );
            if (state.connectivity && state.connectivity !== 4 && wifiConnected && state.defaultDevice === state.wifi.device) {
                this._wifiTile.subtitleLabel.set_text(networkConnectivityText(state.connectivity));
            }
            this._setSplitTileState(this._wifiTile, wifiConnected, false);
        }
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
        const power = this._powerState;
        if (power && power.available && power.battery) {
            const battery = power.battery;
            const charging = [
                UPowerGlib && UPowerGlib.DeviceState ? UPowerGlib.DeviceState.CHARGING : 1,
                UPowerGlib && UPowerGlib.DeviceState ? UPowerGlib.DeviceState.PENDING_CHARGE : 5,
                UPowerGlib && UPowerGlib.DeviceState ? UPowerGlib.DeviceState.FULLY_CHARGED : 4,
            ].indexOf(battery.state) !== -1;
            const percent = Math.round(battery.percentage);
            return {
                available: true,
                percentText: `${percent}%`,
                icon: this._batteryIconName(percent, charging),
            };
        }
        return { available: false, percentText: '', icon: '' };
    }

    _onPowerStateChanged(state) {
        this._powerState = state;
        this._refresh();
    }

    _batteryEstimateText(battery) {
        if (!battery) return '';
        const seconds = battery.state === (UPowerGlib && UPowerGlib.DeviceState ? UPowerGlib.DeviceState.CHARGING : 1)
            ? battery.timeToFull : battery.timeToEmpty;
        if (!seconds || seconds < 60) return '';
        const minutes = Math.round(seconds / 60);
        const hours = Math.floor(minutes / 60);
        return hours ? `${hours}h ${minutes % 60}m` : `${minutes}m`;
    }

    _updateBatteryUi(battery) {
        if (!battery || !this._batteryPill) return;
        const estimate = this._batteryEstimateText(battery);
        const text = estimate ? `${Math.round(battery.percentage)}% · ${estimate}` : `${Math.round(battery.percentage)}%`;
        this._batteryPill.get_child().get_children()[1].set_text(text);
        const deviceCount = this._powerState && this._powerState.devices ? this._powerState.devices.length : 0;
        const source = battery.kind === (UPowerGlib && UPowerGlib.DeviceKind ? UPowerGlib.DeviceKind.UPS : 3)
            ? _('UPS') : deviceCount > 1 ? _(`${deviceCount} thiết bị nguồn`) : _('Pin');
        setAccessibleName(this._batteryPill, `${source}: ${text}`);
    }

}

function main(metadata, orientation, panelHeight, instanceId) {
    return new CaramOSControlCenterApplet(metadata, orientation, panelHeight, instanceId);
}
