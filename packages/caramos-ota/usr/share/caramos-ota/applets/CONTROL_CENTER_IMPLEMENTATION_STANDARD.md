# CaramOS Control Center — Implementation Standard

> **Loại tài liệu:** Product specification + engineering standard + state matrix + test plan  
> **Baseline:** 2026-07-29
> **Target release:** CaramOS `1.0.13`
> **Phạm vi:** `caramos-control-center@caramos` trên Cinnamon
> **Ngôn ngữ:** Tiếng Việt trước; code symbol/API/DBus/command giữ nguyên tên gốc
> **Trạng thái:** `CODE COMPLETE — TEST/FIX ONLY`
>
> **Evidence hiện có:** `node --check`, `git diff --check`, 13 unit/static tests, `validate`, Cinnamon 6.6.4 reload pass.
> **Evidence còn thiếu:** `compile` bị chặn bởi root-owned `__pycache__`; full `test`, `make ship`, hardware/manual matrix và package lifecycle chưa hoàn tất.
> **Quy tắc status:** `DONE` trong inventory nghĩa code/static evidence pass; release chỉ chốt sau hardware/package gates.

Tài liệu này là checklist bắt buộc khi tiếp tục phát triển Control Center. Không đánh dấu feature `DONE` chỉ vì UI đã xuất hiện hoặc syntax pass. Mỗi feature phải có:

```text
Requirement
  → implementation
  → state/error behavior
  → test
  → evidence
  → release decision
```

---

## 1. Cách dùng tài liệu

**Cập nhật trạng thái:** 2026-07-29. Code complete, chuyển test/fix-only; release gate chưa pass.


### 1.1 Người dùng tài liệu

| Vai trò | Cách dùng |
|---|---|
| Developer | Chọn requirement theo phase, implement backend trước UI, cập nhật status và test ID. |
| Reviewer | Kiểm tra code ref, state matrix, permission, error path và evidence. |
| Release maintainer | Kiểm tra release gates, package content, migration, VM và rollback. |
| UX/accessibility reviewer | Kiểm tra keyboard, focus, labels, contrast, localization, responsive layout. |
| QA/VM tester | Chạy test matrix, ghi log/screenshot/video và điền evidence. |

### 1.2 Không được làm

- Không copy nguyên GNOME Shell Quick Settings vào Cinnamon.
- Không thay native Cinnamon applets khi Control Center chưa qua release gate.
- Không dùng widget state làm source-of-truth cho device state.
- Không coi timeout cố định là bằng chứng action thành công.
- Không nuốt lỗi backend mà vẫn hiển thị trạng thái `ON`/`CONNECTED`.
- Không thêm command, DBus service hoặc file path từ metadata/user input mà không allowlist.
- Không sửa migration đã ghi ledger trên máy người dùng; tạo migration timestamp mới cho thay đổi tiếp theo.
- Không đổi `migration.json` cho timestamp migration mới.

### 1.3 Ưu tiên

| Mức | Ý nghĩa | Quy tắc release |
|---|---|---|
| `P0` | Correctness hoặc blocker. Sai có thể làm mất control, crash applet, mất mạng, lộ secret, phá panel hoặc không recover. | Không ship production khi còn `P0` mở. |
| `P1` | Production completeness. Tính năng chính còn thiếu nhưng fallback rõ. | Có thể ship preview; production cần plan và owner. |
| `P2` | Quality/polish. Cải thiện parity, theme, tiện dụng. | Có thể defer có rationale. |
| `P3` | Future/optional. Ngoài scope bản hiện tại. | Không làm lẫn vào P0/P1. |

### 1.4 Trạng thái requirement

| Trạng thái | Nghĩa |
|---|---|
| `DONE` | Code tồn tại, behavior đúng mọi state đã khai báo, test/evidence pass. |
| `PARTIAL` | Happy path có, ít nhất một state/error/edge case còn thiếu. |
| `MISSING` | Chưa có implementation. |
| `BLOCKED` | Có requirement nhưng phụ thuộc backend/hardware/API chưa sẵn. Phải ghi workaround và owner. |
| `DEFERRED` | Chủ động để sau; phải ghi lý do, risk và release mục tiêu. |
| `N/A` | Không áp dụng cho platform/config hiện tại; phải ghi lý do. |

### 1.5 Trace ID

Mỗi requirement dùng một ID duy nhất:

- `CC-ARCH-*`: architecture/state coordinator;
- `CC-NET-*`: network/Ethernet/default route/connectivity;
- `CC-WIFI-*`: Wi-Fi/AP/secret/auth;
- `CC-VPN-*`: VPN/WireGuard;
- `CC-BT-*`: Bluetooth/BlueZ/pairing;
- `CC-AUDIO-*`: output audio;
- `CC-MIC-*`: microphone/input/privacy;
- `CC-DISPLAY-*`: brightness/display/Night Light;
- `CC-POWER-*`: battery/AC/UPS/power profile;
- `CC-SESSION-*`: lock/logout/restart/shutdown;
- `CC-UX-*`: layout/copy/feedback;
- `CC-A11Y-*`: accessibility;
- `CC-SEC-*`: security/privacy;
- `CC-PERF-*`: performance/lifecycle;
- `CC-PACK-*`: metadata/package/migration;
- `CC-TEST-*`: test/evidence/release gate.

Requirement chỉ được coi là hoàn tất khi row có đủ:

```text
ID | status | priority | code ref | test ID | evidence | owner
```

---

## 2. Source of truth và file map

### 2.1 Runtime files

| File | Vai trò | Quy tắc |
|---|---|---|
| [`applet.js`](caramos-control-center@caramos/applet.js) | Applet lifecycle, renderer, state coordinator và backend adapters hiện tại. | Không để UI tự suy đoán state từ widget. |
| [`stylesheet.css`](caramos-control-center@caramos/stylesheet.css) | Token, layout, visual states, focus và responsive styling. | Không dùng màu làm tín hiệu duy nhất. |
| [`metadata.json`](caramos-control-center@caramos/metadata.json) | UUID, name, description, version, instance policy. | Version phải đồng bộ release policy. |

### 2.2 Migration/package files

| File | Vai trò |
|---|---|
| [`migration.py`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/migration.py) | Copy applet và enable cho live desktop users. |
| [`manifest.json`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/manifest.json) | Schema-2 metadata, release `1.0.13`, release notes. |
| [`tracker-control-center.md`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/tracker-control-center.md) | Feature tracker/decision log; phải đồng bộ source thật. |
| [`migration.json`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/migration.json) | Legacy index, frozen tại `1.0.12`; không thêm timestamp ID. |
| [`registry.py`](../../../lib/python3/dist-packages/caramos_ota_update/registry.py) | Auto-discover timestamp folders và validate contract. |
| [`ledger.py`](../../../lib/python3/dist-packages/caramos_ota_update/ledger.py) | Applied-ID ledger; timestamp migration không được suy từ product version. |
| [`runner.py`](../../../lib/python3/dist-packages/caramos_ota_update/runner.py) | Resolve/run/finalize transaction. |

### 2.3 Test/tooling files

| File | Vai trò |
|---|---|
| [`test_migration_registry.py`](../../../../tests/test_migration_registry.py) | Catalog, plan, bootstrap, timestamp behavior. |
| [`test_migration_runner.py`](../../../../tests/test_migration_runner.py) | Runner batch và release finalization. |
| [`caramos-ota-testkit.sh`](../../../../tools/caramos-ota-testkit.sh) | Compile, validate, test, build `.deb`. |
| [`ship-ota-to-vm.sh`](../../../../tools/ship-ota-to-vm.sh) | Build/ship package tới VM. |
| [`vm-run-ota-e2e.sh`](../../../../tools/vm-run-ota-e2e.sh) | Install, dry-run, real migration, verify/restore. |
| [`README.md`](../../../../README.md) | OTA architecture và migration rules. |
| [`MIGRATIONS.md`](../../../../MIGRATIONS.md) | Migration authoring contract. |
| [`debian/install`](../../../../debian/install) | Package file mapping. |

> Nếu link `README.md` hoặc `MIGRATIONS.md` hiển thị dư dấu `/`, dùng path thực tế từ package root:
> `packages/caramos-ota/README.md` và `packages/caramos-ota/MIGRATIONS.md`.

---

## 3. Baseline hiện tại

### 3.1 Feature đã tồn tại trong prototype

| Feature | Code hiện tại | Status baseline |
|---|---|---|
| Panel indicator | Network, VPN, mic-in-use, volume, battery icon/percentage. | `DONE` code; hardware evidence `BLOCKED` |
| Popup | Battery pill, screenshot, settings, lock, power, volume, mic, brightness, network/VPN/Bluetooth/Night Light. | `DONE` code |
| Volume | `Cvc.MixerControl`, default sink, mute, selector, slider debounce 90 ms, live notify. | `DONE` |
| Microphone | Default source, mute, selector, slider, recording stream count. | `DONE` |
| Brightness | Cinnamon Power DBus `GetPercentageRemote`/`SetPercentageRemote`, changed signal. | `BLOCKED` hardware |
| Night Light | `Gio.Settings` schema `org.cinnamon.settings-daemon.plugins.color`. | `DONE` |
| Wi-Fi | libnm radio/AP/profile/connect/disconnect; secured-unsaved delegates native Settings/keyring. | `BLOCKED` hardware/auth matrix |
| VPN | Async UUID profile list/actions, multi-active state and settings fallback. | `DONE` code; signal confirmation `DEFERRED` |
| Bluetooth | BlueZ Adapter1/Device1/Battery1 with owner reconnect and discovery. | `BLOCKED` hardware/pairing matrix |
| Battery | UPower DisplayDevice/BATTERY/UPS/LINE_POWER, signals and estimates. | `BLOCKED` laptop/UPS matrix |
| Power/session | Capability-gated native Cinnamon confirmation for restart/shutdown/logout; suspend/hibernate direct native backend. | `BLOCKED` destructive/cancel/inhibitor test |
| Popup positioning | Monitor bounds, right-edge alignment, retry positioning while open. | `PARTIAL` |
| Mock mode | `~/.caramos-cc-mock` canned Wi-Fi/Bluetooth output. | `PARTIAL`, dev only |

### 3.2 Known baseline mismatches

| ID | Mismatch | Ref | Priority | Required action |
|---|---|---|---:|---|
| `CC-PACK-001` | Metadata, manifest và target release đều là `1.0.13`; policy hiện theo CaramOS release version. | [`metadata.json`](caramos-control-center@caramos/metadata.json), [`manifest.json`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/manifest.json) | P0 | `DONE` cho mismatch; còn package lifecycle evidence trong inventory. |
| `CC-PACK-002` | Manifest chỉ claim active-session users, khớp migration scan `/run/user`; logged-out/new users chưa auto-enable. | Migration + manifest | P1 | `DONE` cho claim; lifecycle khác `DEFERRED`. |
| `CC-PACK-003` | Migration stage, validate, backup và `os.replace()`; restore target cũ nếu install lỗi. | [`migration.py`](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/migration.py) | P0 | `DONE`, unit test copy failure pass. |
| `CC-PACK-004` | Source/payload thiếu hoặc metadata sai raise `RuntimeError`; không silent success. | Migration + [`test_control_center_migration.py`](../../../../tests/test_control_center_migration.py) | P0 | `DONE`. |
| `CC-PACK-005` | `_append_applet()` giữ nguyên entry/order/position cũ và append exact UUID ở position mới. | Migration + migration tests | P0 | `DONE` cho single-panel policy. |
| `CC-NET-001` | Popup có Ethernet và Wi-Fi tile riêng; panel dùng NetworkManager `PrimaryConnection`. Carrier/IP details còn thiếu. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`. |
| `CC-WIFI-001` | Wi-Fi AP list dùng libnm object model và `NM.utils_ssid_to_utf8()`, không còn text `split(':')`. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`; cần hardware/fixture evidence. |
| `CC-WIFI-002` | Wi-Fi action không truyền password argv; saved/open dùng libnm, secured unsaved mở Cinnamon Settings/keyring. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`; Secret Agent nội bộ deferred. |
| `CC-BT-001` | BlueZ Adapter1/Device1 là primary; Blueman/`bluetoothctl` chỉ fallback. Owner-watch reconnect đã thêm. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`; cần hardware evidence. |
| `CC-AUDIO-001` | Cvc import/constructor có guard, no-sink/no-source disabled thật; lifecycle disconnect + close khi unload. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`; cần Cvc-unavailable test. |
| `CC-UX-001` | Disabled tile/slider set `reactive=false`, `can_focus=false`, đồng thời có visual state. | Applet + stylesheet | P0 | `DONE` cho interaction lock; error coverage còn partial. |
| `CC-DISPLAY-001` | Brightness chỉ hiện khi backend trả percentage hợp lệ; no-backlight VM ẩn row. Dark Style vẫn thiếu. | Applet + CaramOS VM evidence | P1 | `PARTIAL`. |
| `CC-POWER-001` | Desktop/no battery ẩn panel icon, label và battery pill; không hiện `--%`. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`; laptop/multiple-battery evidence còn thiếu. |
| `CC-A11Y-001` | Core icon buttons, tiles, sliders và dialogs có accessible name; role/state/screen-reader evidence còn thiếu. | [`applet.js`](caramos-control-center@caramos/applet.js) | P0 | `PARTIAL`. |

---

## 4. Product principles

### 4.1 Ba tầng giao diện

```text
Panel indicator
  Tóm tắt active route, VPN, audio, mic, battery.

Quick Settings popup
  Toggle, slider, status và action thường dùng.

Full Cinnamon Settings
  IP/DNS/802.1X, pairing nâng cao, display layout,
  per-app audio, privacy, advanced power.
```

Popup không được biến thành bản sao của toàn bộ Settings.

### 4.2 Cinnamon-native, Ubuntu-inspired UX

**Implementation target là Cinnamon.** Ubuntu chỉ là reference cho cách tổ chức Quick Settings và visual hierarchy, không phải runtime hoặc codebase mục tiêu.

Được tham khảo từ UX Ubuntu:

- visual hierarchy;
- tile/split-tile flow;
- active/inactive/pending/error states;
- popup spacing, animation, keyboard flow;
- common quick actions;
- compact status summary.

Phải dùng Cinnamon-native implementation:

- `Applet.IconApplet`/Cinnamon applet lifecycle;
- `AppletPopupMenu`, `PopupMenu`, `St`, `Clutter`, `Gio`, `Mainloop` theo API Cinnamon runtime;
- Cinnamon theme và panel geometry;
- Cinnamon Settings/D-Bus interfaces khi có;
- `Cvc.MixerControl` theo sound stack CaramOS;
- BlueZ/NetworkManager/UPower Linux system APIs cho hardware state.

Tuyệt đối không dùng:

- GNOME Shell internal classes;
- GNOME Shell private state model;
- GNOME Shell extension APIs;
- code có license không phù hợp;
- API chỉ tồn tại trên GNOME Shell.

Các Cinnamon native applets `network@cinnamon.org`, `sound@cinnamon.org`, `power@cinnamon.org` là compatibility/reference behavior. Không nhúng nguyên applet vào Control Center; reuse API/pattern sau khi kiểm tra Cinnamon version và lifecycle.

### 4.3 Backend state trước UI state

Mỗi domain phải có normalized state. Ví dụ network:

```text
UNAVAILABLE
DISABLED
IDLE
SCANNING
CONNECTING
CONNECTED
LIMITED
CAPTIVE_PORTAL
FAILED
```

UI chỉ render state. Không được coi:

```text
click toggle + đổi màu tile = action thành công
```

Action thành công chỉ sau signal/backend xác nhận.

### 4.4 Panel replacement policy

Control Center thay `network@cinnamon.org`, `sound@cinnamon.org`, `power@cinnamon.org` trên panel vì đã cover network, audio và battery status/control. Migration chỉ bỏ đúng ba UUID này bằng một lần cập nhật `enabled-applets`.

- giữ mọi applet khác và position hiện có;
- không rewrite layout hardcode hoặc dconf global;
- native Cinnamon Settings vẫn là fallback cho cấu hình nâng cao;
- format lạ thì skip, không sửa panel;
- reboot/login/upgrade và rollback vẫn là release gate.

---

## 5. Kiến trúc mục tiêu

```text
Applet shell / renderer
├── State coordinator
│   ├── immutable normalized snapshot
│   ├── action dispatch
│   ├── pending/error/retry state
│   └── lifecycle/dispose
├── Network backend       -> NetworkManager DBus/libnm
├── Bluetooth backend     -> BlueZ DBus
├── Audio backend         -> Cvc.MixerControl
├── Power backend         -> UPower DBus
├── Brightness backend    -> Cinnamon Power Screen DBus
├── Settings backend      -> Gio.Settings
└── Session actions       -> Cinnamon/systemd allowlisted actions
```

### 5.1 Backend contract

Mỗi backend phải định nghĩa:

```text
initialize()
getSnapshot()
subscribeSignals()
action(request)
  → pending
  → confirmed success OR explicit failure
retry()
reconnect()
dispose()
```

Bắt buộc:

- initial snapshot có `available` và `reason`;
- signal subscription là đường chính;
- timer chỉ làm fallback bounded refresh;
- service owner loss phải reconnect;
- action phải có correlation/pending state;
- action failure phải rollback UI hoặc re-read backend;
- dispose ngắt signal, timer, pending callback;
- UI thread không chạy blocking command;
- command fallback có timeout, argv array và allowlist;
- DBus interface/path/service phải allowlist;
- không parse output text nếu có API object model tương đương.

### 5.2 Backend priority

| Domain | Primary | Fallback | Không được làm source chính |
|---|---|---|---|
| Network | NetworkManager DBus/libnm | bounded `nmcli` argv | `split(':')` text parser production |
| Wi-Fi secret | NetworkManager Secret Agent/keyring | mở Cinnamon Network Settings | password trong argv/log |
| Bluetooth | BlueZ DBus | `bluetoothctl` argv | Blueman private API độc quyền |
| Audio | `Cvc.MixerControl`/PipeWire integration | mở Sound Settings | crash nếu Cvc thiếu |
| Power | UPower DBus | bounded `upower` read | `--%` như battery thật |
| Brightness | Cinnamon Power Screen DBus | mở Display Settings | assume laptop backlight |
| Night Light | `Gio.Settings` | mở Color Settings | show enabled khi schema thiếu |
| Session | Cinnamon/native system action | disable with reason | arbitrary shell command |

---

## 6. Master feature inventory

| ID | Nhóm | Requirement | Current | Target | Priority | Test |
|---|---|---|---|---|---:|---|
| `CC-ARCH-001` | Architecture | Normalized state coordinator | `PARTIAL` | Network/UPower/BlueZ/audio/session snapshots exist; renderer still has inline domain coordination | P0 | `CC-TEST-ARCH-001` |
| `CC-ARCH-002` | Architecture | Signal/reconnect/dispose lifecycle | `DONE` code; evidence pending | NetworkManager/BlueZ/UPower/Cvc/session lifecycle cleanup and owner/signal paths implemented | P0 | `CC-TEST-ARCH-002` |
| `CC-NET-001` | Network | Wired tile and link state | `DONE` | Ethernet tile + NetworkManager Device state, carrier/IP details and Settings handoff | P0 | `CC-TEST-NET-001` |
| `CC-NET-002` | Network | Wi-Fi + Ethernet simultaneously | `DONE` | Both shown; NetworkManager `PrimaryConnection` selects panel icon; hardware evidence remains test phase | P0 | `CC-TEST-NET-002` |
| `CC-NET-003` | Network | Connectivity quality | `DONE` | NetworkManager connectivity mapping + captive/limited handoff; hardware portal evidence remains test phase | P0 | `CC-TEST-NET-003` |
| `CC-NET-004` | Network | Multiple adapters | `DONE` | All devices, primary/default preference and deterministic ordering | P1 | `CC-TEST-NET-004` |
| `CC-NET-005` | Network | IP/DNS/link details | `DONE` | Interface/profile/carrier/speed/IP/gateway/DNS + Settings handoff | P1 | `CC-TEST-NET-005` |
| `CC-WIFI-001` | Wi-Fi | Radio state | `BLOCKED` | libnm `wireless_enabled`/`wireless_hardware_enabled` complete; hardware/rfkill evidence pending | P0 | `CC-TEST-WIFI-001` |
| `CC-WIFI-002` | Wi-Fi | Scan/AP grouping | `BLOCKED` | libnm AP objects, SSID decode/grouping implemented; hardware/SSID fixture evidence pending | P0 | `CC-TEST-WIFI-002` |
| `CC-WIFI-003` | Wi-Fi | Connect/auth/error | `BLOCKED` | Saved/open activation implemented; secured-unsaved delegates Settings/keyring; hardware auth-failure evidence pending | P0 | `CC-TEST-WIFI-003` |
| `CC-WIFI-004` | Wi-Fi | Disconnect correct profile/device | `BLOCKED` | Device active-connection object used; hardware evidence pending | P0 | `CC-TEST-WIFI-004` |
| `CC-WIFI-005` | Wi-Fi | Hidden/enterprise/WPA3 | `DEFERRED` | Native Cinnamon Settings/keyring handoff is v1 fallback; full internal UI deferred | P1 | `CC-TEST-WIFI-005` |
| `CC-WIFI-006` | Wi-Fi | Hotspot/WWAN/airplane orchestration | `DEFERRED` | Ngoài v1.0.13; captive-portal handoff đã có trong network domain | P2 | `CC-TEST-WIFI-006` |
| `CC-VPN-001` | VPN | Detect all active tunnels | `BLOCKED` | Async VPN/WireGuard profile and active-tunnel list complete; hardware evidence pending | P1 | `CC-TEST-VPN-001` |
| `CC-VPN-002` | VPN | Connect/disconnect profiles | `DEFERRED` | UUID action/pending/error complete; NetworkManager active-signal confirmation deferred | P1 | `CC-TEST-VPN-002` |
| `CC-BT-001` | Bluetooth | Adapter powered state | `BLOCKED` | BlueZ Adapter1 primary + owner reconnect complete; hardware evidence pending | P0 | `CC-TEST-BT-001` |
| `CC-BT-002` | Bluetooth | Discovery lifecycle | `BLOCKED` | BlueZ Start/StopDiscovery and object updates implemented; hardware evidence pending | P1 | `CC-TEST-BT-002` |
| `CC-BT-003` | Bluetooth | Pair/connect/disconnect | `BLOCKED` | Known Device1 connect/disconnect implemented; pairing agent/error matrix deferred/blocked | P0 | `CC-TEST-BT-003` |
| `CC-BT-004` | Bluetooth | Trust/block/forget | `DEFERRED` | Advanced device management ngoài v1.0.13 | P1 | `CC-TEST-BT-004` |
| `CC-BT-005` | Bluetooth | Device battery/class/profile | `DEFERRED` | Battery1 shown; class/profile UI ngoài v1.0.13 | P2 | `CC-TEST-BT-005` |
| `CC-AUDIO-001` | Audio | Output volume/mute | `DONE` | Cvc default sink volume/mute with stream notifications | P0 | `CC-TEST-AUDIO-001` |
| `CC-AUDIO-002` | Audio | Output device selector | `DONE` | Cvc output/input add/remove/update and `change_output`/`change_input` | P1 | `CC-TEST-AUDIO-002` |
| `CC-AUDIO-003` | Audio | Cvc unavailable fallback | `BLOCKED` | Import/constructor guarded, controls disabled and lifecycle closed; missing-Cvc fixture evidence pending | P0 | `CC-TEST-AUDIO-003` |
| `CC-MIC-001` | Mic | Input volume/mute | `DONE` code; evidence pending | Cvc default source, explicit mute and source selector | P0 | `CC-TEST-MIC-001` |
| `CC-MIC-002` | Mic | Recording privacy state | `DEFERRED` | Recording stream count/indicator implemented; app-name privacy details deferred | P1 | `CC-TEST-MIC-002` |
| `CC-DISPLAY-001` | Display | Brightness supported/absent | `BLOCKED` | Capability-gated DBus row/hide path complete; physical backlight evidence pending | P0 | `CC-TEST-DISPLAY-001` |
| `CC-DISPLAY-002` | Display | Night Light | `DONE` code; evidence pending | Gio.Settings on/off and unavailable schema path; schedule remains Settings-owned | P1 | `CC-TEST-DISPLAY-002` |
| `CC-DISPLAY-003` | Display | Dark/high contrast | `DONE` | Theme-scoped light/dark/high-contrast surfaces and focus styling | P0 | `CC-TEST-DISPLAY-003` |
| `CC-POWER-001` | Power | Battery/AC/no battery | `BLOCKED` | UPower DisplayDevice/BATTERY/UPS/LINE_POWER state complete; laptop/UPS evidence pending | P0 | `CC-TEST-POWER-001` |
| `CC-POWER-002` | Power | Estimate/low/critical | `BLOCKED` | UPower time/state/warning snapshot complete; hardware warning evidence pending | P1 | `CC-TEST-POWER-002` |
| `CC-POWER-003` | Power | Power profile | `DEFERRED` | Capability-gated future control; CaramOS VM image hiện tại không có backend/tool | P2 | `CC-TEST-POWER-003` |
| `CC-SESSION-001` | Session | Lock/restart/shutdown/etc. | `BLOCKED` | Capability gating + native Cinnamon confirmation implemented; cancel/inhibitor/destructive evidence pending | P0 | `CC-TEST-SESSION-001` |
| `CC-UX-001` | UX | Loading/error/empty/retry | `DONE` | Domain-specific disabled, pending, empty, error and settings fallback states | P0 | `CC-TEST-UX-001` |
| `CC-UX-002` | UX | Responsive/multi-monitor/orientation | `PARTIAL` | Four panel orientations + HiDPI | P1 | `CC-TEST-UX-002` |
| `CC-A11Y-001` | Accessibility | Keyboard/focus/labels | `BLOCKED` | Accessible names, ordered Escape close and focus restoration implemented; screen-reader evidence pending | P0 | `CC-TEST-A11Y-001` |
| `CC-A11Y-002` | Accessibility | Contrast/target/reduced motion | `BLOCKED` | Focus rings, high-contrast and `enable-animations` reduced-motion path implemented; visual evidence pending | P0 | `CC-TEST-A11Y-002` |
| `CC-SEC-001` | Security | Safe system actions/secrets | `DONE` | No Wi-Fi secret argv; UUID/object-path identity; argv allowlists | P0 | `CC-TEST-SEC-001` |
| `CC-PERF-001` | Performance | No UI blocking/fan-out | `DONE` | Network/BlueZ/UPower signal-driven; VPN subprocess async; no `spawn_sync` runtime path | P0 | `CC-TEST-PERF-001` |
| `CC-PACK-001` | Packaging | Atomic install/upgrade/purge | `PARTIAL` | Safe package lifecycle | P0 | `CC-TEST-PACK-001` |
| `CC-TEST-001` | QA | Full state matrix evidence | `IN PROGRESS` | Static/unit/validate/reload pass; compile/package/hardware/manual evidence pending | P0 | `CC-TEST-RELEASE-001` |
| `CC-TEST-002` | QA | Release gates | `BLOCKED` | `compile` blocked by root-owned `__pycache__`; `test`, `make ship`, package lifecycle not yet evidenced | P0 | `CC-TEST-RELEASE-002` |
| `CC-TEST-003` | QA | VM reload smoke | `DONE` | Cinnamon 6.6.4 reload pass, no new applet error in latest checkpoint | P0 | `CC-TEST-RELEASE-003` |
| `CC-TEST-004` | QA | Unit/static checks | `DONE` | 13 tests pass; `node --check`, `git diff --check` pass | P0 | `CC-TEST-RELEASE-004` |

---

## 7. State matrix — panel indicator

| ID | Scenario | Panel expected | Popup expected | Action | Current |
|---|---|---|---|---|---|
| `CC-NET-010` | Ethernet only, carrier up, Internet available | Wired icon, tooltip interface/Internet | Ethernet tile marked active | Open details/settings | `DONE` code; VM evidence pass |
| `CC-NET-011` | Wi-Fi only | Wi-Fi icon with signal | Wi-Fi tile + SSID | Scan/disconnect/settings | `BLOCKED` hardware |
| `CC-NET-012` | Ethernet + Wi-Fi | Show active/default route | Both devices visible | Per-device details | `BLOCKED` hardware |
| `CC-NET-013` | Ethernet link up, no IP | Wired/link limited state | Acquiring/limited text | Settings | `DONE` code; scenario evidence pending |
| `CC-NET-014` | Local network, Internet unavailable | Limited/local state | Connectivity explanation | Details/settings | `DONE` code; scenario evidence pending |
| `CC-NET-015` | Captive portal | Portal state | `Cần đăng nhập mạng` | Open portal/settings | `DONE` code; portal evidence pending |
| `CC-NET-016` | No network adapter | Offline | Empty/unavailable state | Open network settings | `DONE` code; no-device smoke pass |
| `CC-NET-017` | NetworkManager restarting | Unavailable/reconnecting state | Backend recovers on owner return | Disabled while absent | `DONE` code; restart evidence pending |
| `CC-VPN-010` | VPN active over Wi-Fi | VPN badge plus base Wi-Fi | VPN name and base device | Disconnect VPN | `BLOCKED` hardware/profile |
| `CC-VPN-011` | VPN active over Ethernet | VPN badge plus wired base | VPN and Ethernet visible | Disconnect VPN | `BLOCKED` profile evidence |
| `CC-AUDIO-010` | Volume muted | Muted icon | Slider + explicit unmute | Click mute/unmute | `DONE` code; manual evidence pending |
| `CC-MIC-010` | Microphone in use | Mic privacy indicator | Recording count; app details deferred | Open sound settings | `DEFERRED` app-details |
| `CC-POWER-010` | Laptop charging | Charging icon/percentage | Charging + estimate | Power settings | `BLOCKED` laptop hardware |
| `CC-POWER-011` | Desktop no battery | No battery indicator | No empty battery row | Power settings | `DONE`; VM no-device path |
| `CC-UX-010` | Backend unavailable | Neutral/unavailable icon | Disabled control + reason | Settings/retry | `DONE` code; domain matrix pending |

### 7.1 Network icon rule

Current `_readNetworkIcon()` check order:

```text
ethernet:connected → network-wired-symbolic
wifi:connected     → network-wireless-symbolic
other connected    → network-transmit-receive-symbolic
else               → network-offline-symbolic
```

Target rule:

1. Read NetworkManager active connections and default route.
2. Determine Internet/local connectivity separately from link carrier.
3. Panel icon represents **primary/default route**, not arbitrary first connected device.
4. Popup lists all relevant devices.
5. Ethernet + Wi-Fi does not hide either device.
6. If no default route but one link exists, show limited state, not full Internet-connected state.

---

## 8. State matrix — Network và Ethernet

### 8.1 Required network states

| State | Meaning | UI | Allowed action |
|---|---|---|---|
| `UNAVAILABLE` | NetworkManager/device API unavailable | Neutral unavailable + reason | Open Settings/retry |
| `DISABLED` | Radio/device disabled | Off state | Enable |
| `NO_CARRIER` | Ethernet cable/link absent | Cable unplugged | View details |
| `ACQUIRING` | DHCP/IP acquisition pending | Spinner + `Đang kết nối` | Cancel/retry |
| `CONNECTED` | Link + valid route/connectivity | Active state | Disconnect/details |
| `LIMITED` | Link exists, Internet unavailable | Warning state | Details/retry |
| `CAPTIVE_PORTAL` | Portal requires login | Portal state | Open browser portal |
| `FAILED` | Last action failed | Error + short reason | Retry/settings |

### 8.2 Wired behavior

Must support:

- internal Ethernet;
- USB Ethernet;
- dock Ethernet;
- multiple wired devices;
- carrier/link speed;
- IP4/IP6 config;
- default route;
- DNS status;
- connection profile;
- metered policy;
- disconnect/reconnect where permitted;
- handoff to `cinnamon-settings network`.

Không hiển thị Ethernet dưới label `Wi-Fi`.

### 8.3 Ethernet + Wi-Fi

Expected:

```text
Panel: icon của default route + optional secondary indicator.
Popup:
  Ethernet — Connected / Limited / Cable unplugged
  Wi-Fi    — SSID / signal / radio state
  VPN      — tunnel state, nếu có
Details:
  default route, IP, DNS, device names
```

Test bắt buộc:

- default route Ethernet, Wi-Fi connected;
- default route Wi-Fi, Ethernet connected;
- both connected but no default route;
- one device loses carrier;
- NetworkManager changes route while popup is open.

### 8.4 NetworkManager API target

Ưu tiên object model:

- `org.freedesktop.NetworkManager`;
- `org.freedesktop.NetworkManager.Device`;
- `org.freedesktop.NetworkManager.Device.Wired`;
- `org.freedesktop.NetworkManager.Device.Wireless`;
- `org.freedesktop.NetworkManager.Connection.Active`;
- `org.freedesktop.NetworkManager.VPN.Connection`;
- `org.freedesktop.NetworkManager.AccessPoint`;
- `org.freedesktop.NetworkManager.IP4Config`;
- `org.freedesktop.NetworkManager.IP6Config`;
- `org.freedesktop.NetworkManager.DnsManager`.

`nmcli` chỉ là fallback bounded. Không dùng raw human/table output làm canonical state.

---

## 9. State matrix — Wi-Fi

### 9.1 Required states

| ID | State | Expected |
|---|---|---|
| `CC-WIFI-010` | Adapter absent | Hide/disable Wi-Fi controls, explain `Không có thiết bị Wi-Fi`. |
| `CC-WIFI-011` | Radio off | Off state, enable action. |
| `CC-WIFI-012` | rfkill/airplane | Blocked state, explain owner; do not pretend radio toggled. |
| `CC-WIFI-013` | Scanning | Spinner/list stale badge; no duplicate scan processes. |
| `CC-WIFI-014` | Connected | SSID, signal, security, active marker. |
| `CC-WIFI-015` | Connecting | Pending row, action locked, backend confirmation required. |
| `CC-WIFI-016` | Auth failed | Error and retry password flow. |
| `CC-WIFI-017` | No IP/limited | Connected-to-AP but limited state. |
| `CC-WIFI-018` | Hidden SSID | Explicit SSID/security flow or Settings fallback. |
| `CC-WIFI-019` | Enterprise/802.1X | Secret Agent or Settings fallback; never generic WPA password only. |
| `CC-WIFI-020` | Captive portal | `Cần đăng nhập`, open portal. |

### 9.2 Input cases

Parser/integration test phải cover:

- SSID có dấu `:`;
- SSID có `\\`;
- SSID Unicode/Vietnamese;
- SSID có whitespace đầu/cuối;
- SSID dài;
- hidden SSID;
- duplicate SSID trên nhiều BSSID;
- same profile name with different UUID;
- WPA2/WPA3/802.1X;
- wrong password;
- AP disappears during click.

Current code dùng libnm `NM.Client`, `NM.DeviceWifi`/AccessPoint objects và `NM.utils_ssid_to_utf8()`; không còn parse AP list bằng `split(':')`. SSID/BSSID grouping ưu tiên active AP rồi strongest signal. Phần còn thiếu: hardware fixture cho SSID edge cases, state-reason mapping và full hidden/enterprise flow.

### 9.3 Secret rules

- Không truyền password qua shell.
- Không ghi password vào log.
- Không đưa password vào mock output.
- Không giữ password lâu hơn lifetime dialog/action.
- Ưu tiên NetworkManager Secret Agent/keyring.
- Nếu fallback `nmcli` bắt buộc chứa secret trong argv, phải đánh dấu `BLOCKED` cho production và dùng Settings fallback.

### 9.4 Connection result

Không làm:

```text
click → tile orange → sleep 2s → assume connected
```

Phải làm:

```text
click
→ state CONNECTING
→ wait NetworkManager active/failed signal
→ CONNECTED hoặc FAILED
→ render confirmed state
```

---

## 10. State matrix — VPN/WireGuard

| Scenario | Expected |
|---|---|
| No VPN profile | Tile `Không có VPN`, link Settings. |
| One saved profile | Profile name + connect action. |
| Multiple profiles | List all, active marker, UUID-backed actions. |
| Active VPN | Name, tunnel type, disconnect. |
| Multiple active tunnels | List all; không chỉ lấy dòng đầu. |
| Connecting | Spinner/pending, lock duplicate clicks. |
| Failed | Error + retry + Settings. |
| Base link lost | VPN becomes degraded/disconnected with cause. |
| WireGuard | Explicit type and same pending/error model. |
| Split tunnel | Details link; không giả định VPN route toàn bộ traffic. |

Current implementation liệt kê saved VPN/WireGuard profiles, đánh dấu mọi active tunnel, và connect/disconnect bằng UUID. Main tile ngắt tunnel khi chỉ có một active tunnel; khi có nhiều tunnel, mở danh sách để tránh ngắt nhầm. NetworkManager owner loss chuyển control sang unavailable và owner reacquire tạo lại backend proxy. Backend vẫn dùng bounded `nmcli` cho profile/actions; confirmation hiện dựa process result + refresh thay vì NetworkManager active-connection signal. Status `PARTIAL/P1`.

---

## 11. State matrix — Bluetooth

### 11.1 BlueZ target

Primary API:

- `org.bluez.Adapter1.Powered`;
- `org.bluez.Adapter1.Discoverable`;
- `org.bluez.Adapter1.Discovering`;
- `StartDiscovery()`/`StopDiscovery()`;
- `SetDiscoveryFilter()`;
- `org.bluez.Device1.Paired`;
- `Connected`;
- `Trusted`;
- `Blocked`;
- `ServicesResolved`;
- `Connect()`/`Disconnect()`/`Pair()`/`CancelPairing()`;
- `org.bluez.Battery1.Percentage` khi có.

Blueman private API chỉ dùng fallback khi capability được kiểm tra và không phải source-of-truth.

### 11.2 Device states

| State | UI | Action |
|---|---|---|
| Adapter absent | `Không khả dụng` | Settings only |
| Powered off | Off | Power on |
| Discovering | Spinner/stop scan | Stop |
| Paired/disconnected | Device row | Connect |
| Connecting | Row pending | Cancel nếu API hỗ trợ |
| Connected | Checkmark + device type | Disconnect |
| Pairing | Pairing dialog/agent | Confirm/cancel |
| Auth failed | Error/retry | Pair again |
| Blocked | Blocked badge | Unblock/Settings |
| Trusted | Trusted marker | Untrust/details |
| Battery available | Percentage | Details |

Không để tile trông active nếu `bluetoothctl`/BlueZ action fail.

---

## 12. State matrix — Audio và Microphone

### 12.1 Audio output

Must support:

- no sound daemon;
- no default sink;
- default sink changed externally;
- multiple output devices;
- speakers/headphones/HDMI/Bluetooth;
- hotplug;
- mute/unmute;
- volume slider;
- device selector;
- live signal update;
- error/disabled state;
- Cvc constructor failure.

`Cvc.MixerControl` thiếu không được làm applet crash. Disable riêng audio domain, hiển thị reason và link Sound Settings.

### 12.2 Microphone

Must support:

- no source;
- input volume;
- input mute;
- input device selector;
- recording app indicator;
- source disappears while recording;
- Bluetooth headset input profile;
- privacy link if available;
- hard-disable reactive input khi source absent.

Không dùng số lượng recording stream làm thay thế hoàn toàn privacy state. `recordingAppsNum` chỉ là signal phụ.

### 12.3 Media

MPRIS/player controls là `P2`:

- không làm vỡ audio controls nếu player không có;
- play/pause/next/previous chỉ hiện khi player hỗ trợ;
- không block popup để query player;
- không ghi title/artist dài làm vỡ layout;
- ưu tiên Sound Settings nếu player API unavailable.

---

## 13. State matrix — Brightness, Display, Night Light, Theme

### 13.1 Brightness

| Scenario | Expected |
|---|---|
| Internal backlight available | Slider active, current value from DBus. |
| Desktop/no backlight | Hide row hoặc disabled non-reactive, reason. |
| External monitor only | Open Display Settings; không giả vờ slider hoạt động. |
| DBus proxy unavailable | Disabled + Settings fallback. |
| Get error | Loading/error, không dùng default 50 như real state. |
| Set pending | Slider pending, coalesce rapid changes. |
| Set failed | Re-read backend, show failure, restore confirmed value. |
| Multiple displays | Explicit display policy; không đổi nhầm màn hình. |

### 13.2 Night Light/Dark Style

- Night Light schema missing → unavailable, not off.
- Toggle confirmed by settings signal/readback.
- Schedule belongs in Color Settings unless full schedule support exists.
- Dark/light toggle phải dùng theme/dconf policy nhất quán.
- Surface, text, border, icon và focus token phải theme-aware.
- High contrast không được phá active/pending/error distinction.

Current applet có Night Light nhưng chưa có Dark Style. Power Mode cũng chưa có.

---

## 14. State matrix — Battery, AC, UPS, Power Profile

### 14.1 Battery visibility

| Hardware/state | Expected |
|---|---|
| Laptop battery present | Battery icon/percentage; charging/discharging/full. |
| Desktop no battery | Ẩn battery pill/row; không show `--%`. |
| Multiple batteries | Aggregate policy hoặc list rõ. |
| UPS | Distinguish UPS from internal battery. |
| UPower unavailable | Hide/neutral with Settings fallback. |
| Sysfs fallback | Chỉ dùng khi object model unavailable, mark data source/staleness. |

### 14.2 Power states

- AC plugged/unplugged;
- charging/pending-charge/fully-charged/discharging;
- time-to-empty/time-to-full nếu UPower cung cấp;
- low/critical threshold theo native policy;
- suspend/hibernate capability;
- power profile availability/active/error;
- power profile action confirmed by backend;
- no forced shutdown riêng ngoài native system policy.

---

## 15. Session và power actions

Actions:

- Lock;
- Suspend;
- Hibernate nếu supported;
- Restart;
- Shutdown;
- Logout;
- Switch user;
- Settings;
- Screenshot.

Rules:

- Action label dùng verb cụ thể: `Khởi động lại`, `Tắt máy`, `Đăng xuất`.
- Destructive action cần native confirmation hoặc undo-equivalent.
- Cancel đứng trước affirmative button trong dialog.
- Focus ban đầu vào control an toàn/primary theo context.
- Không chạy action nếu capability thiếu; button disabled + reason.
- Exit code/failure phải báo; không close UI như thể thành công.
- Inhibitors/unsaved work nên defer cho native session dialog.
- `systemctl`/`cinnamon-session-quit`/`dm-tool` chỉ nằm trong allowlist.

---

## 16. UX standard

### 16.1 Tile anatomy

```text
[ icon ] [ title       ] [ subtitle/state ] [ optional arrow ]
```

- Title: tên feature, ngắn.
- Subtitle: state thật, không lặp title.
- Arrow: mở details/list, không phải toggle.
- Main body: toggle/action chính.
- Split tile: main action và details action phải có label/accessibility khác nhau.
- Disabled: opacity + text/reason + non-reactive.
- Pending: spinner/pending text + lock duplicate action.
- Error: error icon/text + retry/settings.

### 16.2 Feedback

Mọi async action phải có:

```text
idle → pending → confirmed success
                 ↘ failed + retry
```

Không dùng delay để giả lập success.

### 16.3 Empty states

Empty state phải trả lời:

1. Có gì xảy ra?
2. Vì sao?
3. Người dùng làm gì tiếp?

Ví dụ:

```text
Không có thiết bị Bluetooth.
Bật Bluetooth hoặc mở Cài đặt Bluetooth để ghép thiết bị.
```

### 16.4 Layout

Test:

- panel top/bottom/left/right;
- primary/secondary monitor;
- monitor nhỏ;
- 100/125/150/200% scale;
- long Vietnamese/English labels;
- high contrast;
- popup không vượt monitor;
- keyboard focus không bị popup/subpanel che.

### 16.5 Theme

Không hardcode popup luôn light. Dùng token/state mapping cho:

- surface;
- text primary/secondary;
- border;
- active accent;
- disabled;
- pending;
- error/warning;
- focus;
- icon.

CaramOS orange có thể là accent, không được là tín hiệu duy nhất cho active/error.

### 16.6 Localization

- `_()` phải kết nối gettext thật khi production localization được bật.
- Mọi user-facing string có Vietnamese và English path.
- Test chuỗi dài, dấu tiếng Việt, fallback English.
- Không cắt mất nghĩa khi ellipsize; thêm tooltip/details.
- Không dịch code symbol, DBus interface, command và migration ID.

---

## 17. Accessibility standard

Accessibility áp dụng trực tiếp trên Cinnamon toolkit và applet lifecycle của CaramOS. GNOME HIG chỉ được dùng làm checklist UX tổng quát; không dùng GNOME Shell API hoặc GNOME-specific implementation. WCAG 2.2 cung cấp tiêu chí đo lường cho keyboard, focus, contrast, target size và status message.

### 17.1 Keyboard

- Mở popup bằng panel click và keyboard shortcut nếu có.
- Tab/Shift+Tab đi qua mọi interactive control.
- Enter/Space kích hoạt đúng action.
- Escape đóng dialog trước, subpanel sau, popup cuối.
- Không có keyboard trap.
- Focus trở về control mở subpanel khi subpanel đóng.
- Password input nhận focus có chủ đích.
- Slider hỗ trợ arrow/Home/End theo toolkit.

### 17.2 Accessible name/role/state

Mọi icon-only button phải có:

- accessible name;
- role đúng;
- state (`checked`, `disabled`, `busy`, `expanded`) nếu có;
- label không phụ thuộc icon shape/màu.

Status change phải announce mà không cướp focus:

```text
Wi-Fi đang kết nối
Wi-Fi đã kết nối
Kết nối Wi-Fi thất bại
```

### 17.3 Visual accessibility

Mục tiêu:

- text contrast tối thiểu `4.5:1` cho text thường;
- text lớn tối thiểu `3:1`;
- non-text control/focus tối thiểu `3:1`;
- focus ring nhìn thấy trên cả light/dark/high contrast;
- target tương tác tối thiểu `24×24` CSS px; mục tiêu desktop `32–40` px;
- không dùng màu là thông tin duy nhất;
- disabled vẫn phân biệt được nhưng không dùng opacity đến mức không đọc được;
- animation có reduced-motion path.

### 17.4 Assistive technology

Test với:

- keyboard only;
- screen reader nếu môi trường hỗ trợ;
- large text;
- high contrast;
- on-screen keyboard;
- display-off/low-vision simulation.

---

## 18. Security và privacy standard

### 18.1 Command execution

Được phép:

- argv array;
- command allowlist;
- fixed binary/path policy;
- timeout/bounded execution;
- exit code kiểm tra;
- stderr không chứa secret được log.

Không được phép:

- `eval`;
- shell interpolation với SSID/password/device name;
- `shell=True`;
- command lấy từ JSON/metadata/user input;
- `echo password` vào log;
- dùng SSID làm connection ID khi UUID/profile ID có sẵn.

### 18.2 DBus

- Allowlist service/interface/object path/method.
- Validate property type/range trước render.
- Owner loss phải chuyển state `UNAVAILABLE/RECONNECTING`.
- Không assume service tồn tại vì package có thể chạy trên desktop khác.

### 18.3 Secrets

- Password chỉ sống trong dialog/action lifetime.
- Không ghi secret vào ledger, log, mock, crash report.
- Ưu tiên NetworkManager Secret Agent/keyring.
- Không truyền Wi-Fi password trong process argv cho production.

### 18.4 Migration install safety

- Source path fixed.
- Target type/ownership/symlink check.
- Stage temporary directory trong cùng filesystem.
- Validate required `applet.js`, `metadata.json`, `stylesheet.css`.
- Atomic rename hoặc restore backup khi failure.
- Source missing/copy incomplete phải fail migration.
- Ledger chỉ mark sau migration success.
- Dry-run không tạo/xóa/sửa file hoặc dconf.

---

## 19. Performance và lifecycle

### 19.1 UI thread

Không gọi `GLib.spawn_sync` cho refresh thường xuyên. Nếu fallback command bắt buộc:

- dùng async subprocess;
- timeout;
- coalesce duplicate requests;
- không chạy toàn bộ domain mỗi 15 giây nếu không đổi;
- hiển thị stale/pending thay vì block.

### 19.2 Signal/timer policy

- Signal-driven first.
- Timer fallback có interval/backoff.
- Mỗi timer có owner và cleanup path.
- Không tạo timer mới mỗi click mà không remove timer cũ.
- Service restart phải reconnect.
- Applet removed phải disconnect toàn bộ Cvc/GSettings/DBus signals.

### 19.3 Action concurrency

- Một action radio pending thì khóa toggle tương ứng.
- Slider gom thay đổi nhanh và commit final value.
- Không để hai connect/disconnect cùng domain chạy chồng.
- Action fail phải unlock control.
- Popup đóng không được hủy ngầm action nguy hiểm; action phải có lifecycle rõ.

### 19.4 Budget mục tiêu

| Metric | Mục tiêu |
|---|---:|
| Popup first render | `<150 ms` không có backend block |
| Initial backend snapshot | UI không block; state loading hiện trong `<100 ms` |
| Normal refresh | Không spawn fan-out toàn domain mỗi tick |
| Slider update | Debounce khoảng `50–100 ms`, configurable |
| Device list | Giới hạn row visible, pagination/details cho list lớn |
| Timer leak | `0` sau remove/reload applet |

---

## 20. Packaging và migration standard

### 20.1 Version policy

- `metadata.json` version phải có policy rõ: package version, applet version hoặc release version.
- Migration release và applet metadata hiện đều là `1.0.13`; policy dùng CaramOS release version.
- Tracker, manifest, changelog, applet metadata và test target không được mâu thuẫn.

### 20.2 User lifecycle

Phải phân biệt:

| User state | Expected |
|---|---|
| Live desktop user | Có thể apply `gsettings` qua session bus. |
| Existing logged-out user | Apply default/profile hoặc ghi deferred; không giả vờ đã enable. |
| New user | Default profile path hoặc release note nói rõ không hỗ trợ. |
| Multiple sessions | Apply từng session hợp lệ, log user-safe. |
| No session | Migration vẫn install payload; enable deferred theo policy. |

### 20.3 Panel list policy

- Không duplicate UUID.
- Không match UUID bằng substring không chính xác.
- Không reorder unrelated entries.
- Không assume chỉ có `panel1:right` nếu product yêu cầu multiple panels.
- Preserve user customizations.
- Nếu format unknown: skip safely + log reason.
- Test calendar present/absent, malformed list, multiple right entries, applet already present.

### 20.4 Upgrade/purge

- Package source path `/usr/share/caramos-ota/applets/...` phải có ownership rõ.
- Target `/usr/share/cinnamon/applets/...` phải có install/upgrade/purge policy rõ.
- Upgrade không để stale files.
- Purge không xóa user-owned unrelated files.
- Rollback không reset toàn bộ panel.
- Applet version update phải test Cinnamon reload/reboot.

---

## 21. Test strategy

### 21.1 Static/unit gate

Trạng thái hiện tại:

| Gate | Result | Evidence/note |
|---|---|---|
| `node --check` | `PASS` | Applet syntax valid. |
| `git diff --check` | `PASS` | No whitespace errors. |
| Control Center unit/static | `PASS` | 13 tests. |
| `validate` | `PASS` | 12 migrations; latest release `1.0.13`. |
| Cinnamon 6.6.4 reload | `PASS` | Latest checkpoint loaded applet, no new applet error. |
| `compile` | `BLOCKED` | Root-owned `usr/**/__pycache__` prevents bytecode output. |
| Full testkit `test` | `PENDING` | Run after compile ownership fix. |
| `make ship` / `.deb` audit | `PENDING` | No release evidence yet. |
| Hardware/manual matrix | `PENDING` | Wi-Fi/Bluetooth/power/backlight/audio/session/a11y. |

Chạy từ `packages/caramos-ota`:

```bash
./tools/caramos-ota-testkit.sh compile
./tools/caramos-ota-testkit.sh validate
./tools/caramos-ota-testkit.sh test
node --check usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js
python3 -m json.tool usr/share/caramos-ota/applets/caramos-control-center@caramos/metadata.json >/dev/null
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/manifest.json >/dev/null
git diff --check
```

### 21.2 Unit cases cần thêm

- `_append_applet()` UUID exact match.
- Applet already present → no change.
- Calendar present/absent.
- Existing unrelated applets preserve order.
- Multiple right entries.
- malformed `enabled-applets`.
- multiple panel policy.
- source missing → migration fails, not applied.
- atomic copy success.
- atomic copy failure → old target survives.
- dry-run → no filesystem/dconf mutation.
- no live user → payload install/deferred policy đúng.

### 21.3 Backend contract fixtures

Fake/mock states phải cover:

- service unavailable;
- owner lost/reconnected;
- device appears/disappears;
- action pending;
- action success;
- action error;
- duplicate action;
- multiple devices;
- stale cache;
- malformed/escaped names;
- values out of range.

Mock mode không chỉ trả happy path. Marker `~/.caramos-cc-mock` phải dev-only và không được là production source.

### 21.4 VM/hardware matrix

| ID | Setup | Expected |
|---|---|---|
| `CC-TEST-VM-001` | Ethernet only | Wired tile/icon, no Wi-Fi claim. |
| `CC-TEST-VM-002` | Wi-Fi only | SSID/signal/connect flow. |
| `CC-TEST-VM-003` | Ethernet + Wi-Fi | Both visible, default route correct. |
| `CC-TEST-VM-004` | Offline | Empty/limited state, no crash. |
| `CC-TEST-VM-005` | Captive portal | Portal CTA or explicit deferred fallback. |
| `CC-TEST-VM-006` | VPN/WireGuard | Active tunnel name/state. |
| `CC-TEST-VM-007` | SSID Unicode/colon | Correct list/connect, no split corruption. |
| `CC-TEST-VM-008` | Wrong Wi-Fi password | Error/retry, no false connected state. |
| `CC-TEST-VM-009` | No Bluetooth | Disabled/unavailable, applet survives. |
| `CC-TEST-VM-010` | Pair/connect BT | BlueZ state and error handling. |
| `CC-TEST-VM-011` | No microphone | Row hidden/disabled and non-reactive. |
| `CC-TEST-VM-012` | Multiple audio devices | Selector/hotplug. |
| `CC-TEST-VM-013` | Laptop charging/discharging | Correct power text/icon. |
| `CC-TEST-VM-014` | Desktop/no battery | No `--%` battery UI. |
| `CC-TEST-VM-015` | Brightness absent | Disabled/Settings fallback. |
| `CC-TEST-VM-016` | Dark/high contrast | Contrast/focus/readability. |
| `CC-TEST-VM-017` | Panel all orientations | Popup placement correct. |
| `CC-TEST-VM-018` | Multi-monitor/HiDPI | Bounds/scale/focus correct. |
| `CC-TEST-VM-019` | Reboot/login | Applet loads without GJS errors. |
| `CC-TEST-VM-020` | New user/logged-out user | Behavior matches migration claim. |
| `CC-TEST-VM-021` | Rerun migration | No duplicate/overwrite/custom layout loss. |
| `CC-TEST-VM-022` | Package upgrade/purge | Ownership and cleanup correct. |

### 21.5 Evidence format

Mỗi test ghi:

```text
Test ID:
Date/time:
Tester:
Host/VM image:
Hardware/backend:
Setup commands:
Steps:
Expected:
Actual:
Result: PASS / FAIL / BLOCKED
Logs:
Screenshots/video:
Issue/commit:
Notes:
```

---

## 22. Roadmap implementation

### Phase 0 — Spec/baseline

**Entry:** Prototype tồn tại, tracker drift.  
**Tasks:**

- `CC-ARCH-001`: freeze normalized state model.
- `CC-PACK-001..005`: resolve version, user claim, atomic install, fail-closed, panel policy.
- Update tracker so status matches actual code.

**Exit:** Baseline matrix approved; no contradictory claim.

### Phase 1 — P0 install safety

**Tasks:**

- atomic stage/validate/rename;
- source missing raises failure;
- exact UUID/panel preservation;
- live/logged-out/new user policy;
- migration unit tests;
- dry-run proof.

**Exit:** `.deb` install failure cannot silently mark applied or destroy old applet.

### Phase 2 — P0 backend foundation

**Tasks:**

- state coordinator;
- async action model;
- signal subscription/reconnect;
- dispose/timer ownership;
- normalized availability/error states;
- no UI blocking.

**Exit:** Each domain survives missing daemon/service restart without applet crash.

### Phase 3 — P0 network correctness

**Tasks:**

- NetworkManager DBus/libnm adapter;
- Ethernet tile/default route;
- wired + Wi-Fi simultaneous;
- connectivity/limited/captive portal state;
- Wi-Fi escaped SSID/AP grouping;
- Secret Agent/keyring path;
- confirmed action/error/retry.

**Exit:** Network matrix `CC-TEST-VM-001..008` pass.

### Phase 4 — P0 Bluetooth/audio/power absence

**Tasks:**

- BlueZ Adapter1/Device1;
- Cvc guard and output/input absence states;
- no battery/UPower restart;
- no mic/no sink hard-disable;
- pending/error rollback.

**Exit:** No-device matrix pass; no crash in Cinnamon logs.

### Phase 5 — P0 UX/accessibility/theme

**Tasks:**

- accessible name/role/state;
- keyboard-only flow;
- focus visibility;
- dark/high contrast tokens;
- responsive/multi-monitor/orientation;
- real gettext path;
- reduced motion.

**Exit:** Accessibility and visual gates pass.

### Phase 6 — P1 completeness

- output/input device selectors;
- VPN connect/disconnect;
- Bluetooth pairing/trust/forget;
- battery estimate/AC/power profiles;
- Night Light schedule/settings handoff;
- details pages without popup bloat.

### Phase 7 — P2/P3 polish

- hotspot/client count;
- DND/notifications integration;
- Bluetooth device battery/type;
- MPRIS/media;
- external monitor brightness;
- advanced network details.

### Phase 8 — Release hardening (`IN PROGRESS`)

Code phase đã freeze. Remaining work:

- full VM/hardware matrix;
- reboot/new-user/upgrade/purge;
- package content audit;
- compile ownership fix;
- tracker/manifest/changelog sync;
- rollback evidence;
- release signoff.

---

## 23. Definition of Done

### 23.1 Feature DoD

- [ ] Requirement ID assigned.
- [ ] Priority assigned.
- [ ] Current status updated.
- [ ] Backend source-of-truth selected.
- [ ] Normal states defined.
- [ ] Missing/unavailable/error/pending states defined.
- [ ] Action success confirmed by backend.
- [ ] Action failure restores truthful UI.
- [ ] Keyboard path tested.
- [ ] Accessible name/state added.
- [ ] Localization strings added.
- [ ] Unit/contract test added.
- [ ] VM/manual evidence added.
- [ ] Tracker updated.

### 23.2 Applet release candidate gate

Current decision: **NOT READY FOR RELEASE**. Code complete; test/package evidence incomplete.

- [ ] No P0 open.
- [ ] No unowned P1.
- [ ] Ethernet and Wi-Fi behavior correct independently and together.
- [ ] VPN state does not hide base network state.
- [ ] No battery/no mic/no Bluetooth/no audio daemon states do not crash.
- [ ] Dark/light/high contrast pass.
- [ ] Keyboard/screen reader pass.
- [ ] Popup placement pass on all panel orientations.
- [ ] No stale timer/signal after applet removal.
- [ ] No secrets in argv/log.
- [ ] `node --check` pass.
- [ ] OTA compile/validate/unit pass.
- [ ] `.deb` content pass.
- [ ] VM install/dry-run/real/rerun/reboot pass.

### 23.3 Migration/package gate

- [ ] Source applet files exist.
- [ ] `metadata.json` valid and version policy resolved.
- [ ] Atomic install tested.
- [ ] Copy failure preserves old target.
- [ ] Source missing fails transaction.
- [ ] Existing custom panel entries preserved.
- [ ] User lifecycle claim matches code.
- [ ] Dry-run no mutation.
- [ ] Ledger records timestamp ID only after success.
- [ ] Purge/upgrade ownership documented.
- [ ] `.deb` contains intended applet/migration and no `v1_0_13`.

---

## 24. Traceability working templates

### 24.1 Requirement row

```markdown
| ID | Requirement | Current | Target | Priority | Code ref | Test ID | Evidence | Owner | Status |
|---|---|---|---|---:|---|---|---|---|---|
| CC-NET-000 | ... | MISSING | ... | P0 | ... | CC-TEST-NET-000 | ... | ... | ... |
```

### 24.2 State transition

```markdown
| Current | Trigger | Pending | Backend confirmation | Success UI | Error UI | Retry |
|---|---|---|---|---|---|---|
| IDLE | User action | CONNECTING | Active signal | CONNECTED | FAILED + reason | Yes |
```

### 24.3 Backend contract

```markdown
### Backend: <name>

- Primary API:
- Fallback:
- Availability check:
- Snapshot:
- Signals:
- Actions:
- Pending state:
- Success confirmation:
- Failure mapping:
- Reconnect:
- Dispose:
- Security constraints:
- Test fixtures:
```

### 24.4 Evidence row

```markdown
| Test ID | Setup | Steps | Expected | Actual | Result | Evidence path | Date | Issue |
|---|---|---|---|---|---|---|---|---|
```

### 24.5 Deferred item

```markdown
| ID | Deferred feature | Reason | Current fallback | Risk | Owner | Target release | Exit condition |
|---|---|---|---|---|---|---|---|
```

---

## 25. References

### 25.1 Local project references

- [OTA README](../../../../README.md)
- [Migration guide](../../../../MIGRATIONS.md)
- [Current applet](caramos-control-center@caramos/applet.js)
- [Current stylesheet](caramos-control-center@caramos/stylesheet.css)
- [Applet metadata](caramos-control-center@caramos/metadata.json)
- [Control Center migration](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/migration.py)
- [Control Center manifest](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/manifest.json)
- [Control Center tracker](../../../lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/tracker-control-center.md)
- [Registry tests](../../../../tests/test_migration_registry.py)
- [Runner tests](../../../../tests/test_migration_runner.py)
- [OTA testkit](../../../../tools/caramos-ota-testkit.sh)
- [VM ship script](../../../../tools/ship-ota-to-vm.sh)
- [VM runner](../../../../tools/vm-run-ota-e2e.sh)
- [Debian install map](../../../../debian/install)

### 25.2 UX/accessibility references

- [Cinnamon spices repository](https://github.com/linuxmint/cinnamon-spices) — UUID, applet packaging và Cinnamon-compatible patterns.
- [Cinnamon source repository](https://github.com/linuxmint/cinnamon) — applet/runtime API reference; kiểm tra đúng Cinnamon version trước khi dùng.
- [GNOME HIG — Guidelines](https://developer.gnome.org/hig/guidelines.html) — chỉ tham khảo UX writing, feedback và control semantics; không phải implementation target.
- [GNOME HIG — Accessibility](https://developer.gnome.org/hig/guidelines/accessibility.html) — checklist tổng quát; map vào Cinnamon/St/Clutter thực tế.
- [GNOME HIG — Switches](https://developer.gnome.org/hig/patterns/controls/switches.html) — semantics switch/feedback; không dùng GNOME Shell API.
- [GNOME HIG — Dialogs](https://developer.gnome.org/hig/patterns/feedback/dialogs.html) — confirmation/focus/button wording; không dùng GNOME Shell API.
- [WCAG 2.2](https://www.w3.org/TR/WCAG22/) — tiêu chí đo lường accessibility độc lập desktop shell.

GNOME links ở trên chỉ là UX/accessibility reference. Code phải chạy bằng Cinnamon applet API và Linux desktop backends của CaramOS.

### 25.3 Cinnamon/runtime references

- [Cinnamon spices](https://github.com/linuxmint/cinnamon-spices)
- [Cinnamon](https://github.com/linuxmint/cinnamon)
- Local Cinnamon applet UUIDs: `network@cinnamon.org`, `sound@cinnamon.org`, `power@cinnamon.org`
- Local CaramOS implementation: [applet.js](caramos-control-center@caramos/applet.js)
- Local CaramOS styles: [stylesheet.css](caramos-control-center@caramos/stylesheet.css)
- Local CaramOS metadata: [metadata.json](caramos-control-center@caramos/metadata.json)

### 25.4 Official backend references

- [NetworkManager D-Bus API](https://networkmanager.dev/docs/api/latest/spec.html)
- [BlueZ Adapter1 API](https://bluez.readthedocs.io/en/latest/adapter-api/)
- [BlueZ Device1 API](https://bluez.readthedocs.io/en/latest/device-api/)
- [BlueZ Battery1 API](https://bluez.readthedocs.io/en/latest/battery-api/)

Ubuntu/GNOME references ở trên chỉ là UX/backend design reference. Chúng không thay thế Cinnamon runtime contract và không cho phép copy code không kiểm tra license.

---

## 26. Current release status and next actions

Feature freeze đã bật. Không thêm tile hoặc feature mới cho v1.0.13. Chỉ test/fix.

### Đã xác nhận

- [x] `node --check` applet pass.
- [x] `git diff --check` pass.
- [x] 13 unit/static tests pass.
- [x] `./tools/caramos-ota-testkit.sh validate` pass.
- [x] Cinnamon 6.6.4 VM reload pass; latest checkpoint không có applet error mới.
- [x] Migration atomic/fail-closed/append-preserve tests pass.

### Cần làm trước release

1. [ ] Sửa compile cache ownership: `usr/**/__pycache__` đang `root:root`; chạy lại `./tools/caramos-ota-testkit.sh compile`.
2. [ ] Chạy `./tools/caramos-ota-testkit.sh test`.
3. [ ] Chạy `make ship` và audit `.deb` content.
4. [ ] Chạy install/dry-run/real migration/rerun/reboot/purge/rollback.
5. [ ] Test Wi-Fi hardware, SSID edge cases, auth failure, captive portal.
6. [ ] Test Bluetooth discovery/connect/disconnect/pairing.
7. [ ] Test laptop battery, AC, low/critical, backlight, UPS/multiple devices.
8. [ ] Test audio hotplug, multiple sink/source, Cvc unavailable.
9. [ ] Test session cancel/inhibitor/logout/restart/shutdown; destructive actions manual only.
10. [ ] Test keyboard, Escape/focus restore, screen reader, dark/high-contrast, large text.
11. [ ] Test four panel orientations, multi-monitor and HiDPI.
12. [ ] Record evidence per `CC-TEST-*`; release only when no unowned P0/P1 remains.

### Explicitly deferred

- NetworkManager Secret Agent/password UI nội bộ.
- Hidden/enterprise/802.1X full UI.
- VPN active-connection signal confirmation.
- Bluetooth pairing agent/trust/block/forget.
- Hotspot/WWAN/airplane orchestration.
- Power Profiles, MPRIS/DND/notification history, DDC brightness.

**Quy tắc:** Mọi lỗi mới tạo test/evidence rồi fix. Không đánh dấu release pass chỉ từ syntax hoặc VM reload.
