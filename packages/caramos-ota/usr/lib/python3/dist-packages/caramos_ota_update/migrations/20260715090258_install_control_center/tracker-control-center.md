# 🧾 TRACKER — CaramOS Control Center Applet giống Ubuntu Quick Settings

> Tracker triển khai cho `20260715090258_install_control_center\`: nâng applet `caramos-control-center@caramos`
> từ menu tile tạm bợ sang trung tâm điều khiển giống Ubuntu Quick Settings.
>
> Nguyên tắc quan trọng: migration cài Control Center và bỏ đúng ba applet mặc định
> `network@cinnamon.org`, `sound@cinnamon.org`, `power@cinnamon.org`; không rewrite
> layout panel, không ghi đè dconf toàn cục, giữ nguyên mọi applet khác và position hiện có.

---

## 🔖 1. THÔNG TIN CHUNG

| Trường | Giá trị |
| --- | --- |
| **ID** | CARAMOS-OTA-CC-001 |
| **Tên task** | Xây dựng CaramOS Control Center giống Ubuntu Quick Settings |
| **Loại** | Desktop UX / Cinnamon Applet / OTA Migration |
| **Độ ưu tiên** | High |
| **Mức ảnh hưởng** | Medium-High |
| **Trạng thái tổng thể** | Code Complete — chuyển sang test/fix-only |
| **Người phụ trách** | dungleviet |
| **Người yêu cầu** | CaramOS maintainer |
| **Reviewer** | TBD |
| **Ngày tạo** | 2026-07-02 |
| **Cập nhật lần cuối** | 2026-07-29 |
| **Target release** | CaramOS OTA 1.0.13\ |
| **Branch / PR** | TBD |

### 1.1 Trạng thái phase

| Phase | Tên phase | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| 0 | Chốt scope và nguyên tắc an toàn | Done | Control Center thay đúng network/sound/power; giữ applet và layout còn lại. |
| 1 | Trace Ubuntu Quick Settings / CaramOS applets | Done | Đã scan VM CaramOS và source applet Cinnamon có sẵn. |
| 2 | Thiết kế kiến trúc applet Cinnamon | Done | Backend contract và lifecycle đã chốt cho v1.0.13. |
| 3 | Implement panel indicator gộp | Done | Cụm network/VPN/mic/volume/battery reload pass trên Cinnamon 6.6.4. |
| 4 | Implement popup Quick Settings | Done | Sliders, tiles, inline details, empty/error fallback code complete. |
| 5 | Kết nối audio/mic | Done | Cvc volume/mute, output/input selector, hotplug signals và no-device guard. |
| 6 | Kết nối brightness | Blocked | Code DBus + capability gating xong; VM không có backlight thật. |
| 7 | Kết nối Wi-Fi/VPN/network | Blocked | NetworkManager details/libnm/async VPN xong; hardware/auth/captive matrix còn cần test. |
| 8 | Kết nối power/battery/night light | Blocked | UPower signals/estimate/AC/UPS summary xong; laptop/UPS thật còn cần test. |
| 9 | Style giống Ubuntu nhưng hợp CaramOS | Blocked | Light/dark/high-contrast/focus code xong; visual/a11y matrix còn cần test. |
| 10 | Packaging + migration an toàn | Blocked | Atomic/fail-closed + unit tests pass; full `.deb` lifecycle chưa chạy. |
| 11 | Verification trên VM | In Progress | Reload pass; static/unit pass; chuyển sang test/fix-only. |

---

## 🧠 2. BỐI CẢNH VÀ VẤN ĐỀ

### 2.1 Hiện trạng

Applet hiện tại chỉ là menu tĩnh gồm các tile mở settings/app riêng lẻ. Nó chưa có giá trị như Control Center thật vì:

- không hiển thị trạng thái hiện tại;
- không điều khiển nhanh volume/mic/brightness;
- không gom indicator trên panel;
- không có submenu Wi-Fi/VPN/Bluetooth;
- UX chưa giống Ubuntu Quick Settings.

### 2.2 Yêu cầu mới

Làm Control Center giống Ubuntu Quick Settings:

- Trên panel gom một cụm indicator gồm pin, loa, mic, Wi-Fi/network, VPN, Bluetooth nếu ổn định.
- Click cụm indicator sẽ mở popup.
- Popup có slider loa, mic, ánh sáng.
- Popup có tile/submenu Wi-Fi, VPN, Bluetooth.
- Popup có Power Mode, Night Light/Dark Style nếu hỗ trợ.
- Popup có Lock, Settings, Power.

### 2.3 Bài học từ lỗi trước

Không được dùng migration để cấu hình lại toàn bộ panel.

Migration `20260715090258_install_control_center\` chỉ được phép:

1. copy applet vào `/usr/share/cinnamon/applets/`;
2. atomically bỏ đúng `network@cinnamon.org`, `sound@cinnamon.org`, `power@cinnamon.org` và append Control Center nếu chưa có;
3. giữ nguyên text, thứ tự và position của mọi applet khác;
4. không sửa `panels-height`;
5. không sửa `panel-zone-*`;
6. không ghi `/etc/dconf/db/local.d/...` cho layout panel;
7. không reload Cinnamon cưỡng bức.

---

## 🎯 3. MỤC TIÊU

```text
Panel indicator compact
└── Popup Quick Settings
    ├── Battery pill/status
    ├── Volume slider
    ├── Microphone slider
    ├── Brightness slider
    ├── Wi-Fi tile + submenu
    ├── VPN tile + submenu
    ├── Bluetooth tile
    ├── Power mode
    ├── Night Light / Dark Style
    └── Lock / Settings / Power
```

### 3.1 Mục tiêu kỹ thuật

- Applet chạy ổn trên Cinnamon của CaramOS/Linux Mint 22 base.
- Không crash GJS/Cinnamon.
- Không phá panel hiện có.
- Có graceful fallback nếu thiếu API hoặc command.
- UI cập nhật trạng thái định kỳ nhẹ.
- Không hardcode cấu hình riêng của một máy test.

### 3.2 Ngoài phạm vi v1

- Không viết daemon riêng nếu chưa cần.
- Không thay NetworkManager UI đầy đủ.
- Không implement full GNOME Shell Quick Settings internals.
- Không ép mọi máy phải có brightness/mic/VPN nếu phần cứng không hỗ trợ.
- Không sửa global Cinnamon layout.

---

## 🧩 4. THIẾT KẾ DỰ KIẾN

| File | Vai trò |
| --- | --- |
| `usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js` | Logic applet Cinnamon/GJS |
| `usr/share/caramos-ota/applets/caramos-control-center@caramos/stylesheet.css` | Style popup/panel |
| `usr/share/caramos-ota/applets/caramos-control-center@caramos/metadata.json` | Metadata Cinnamon applet |
| `usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center\/migration.py` | Cài applet tối thiểu |

### 4.1 Nguyên tắc applet.js

- Không subclass trực tiếp `St.Button` theo kiểu gây lỗi GType.
- Tạo UI bằng factory functions.
- Không shell command với input người dùng không validate.
- Command cố định, allow-list rõ ràng.
- Poll interval vừa phải, ví dụ 2-5 giây cho status nhẹ.

### 4.2 Backend control sau scan VM

Kết quả scan read-only trong CaramOS VM cho thấy không nên nhúng nguyên applet có sẵn vào Control Center. Các applet Cinnamon hiện hữu có lifecycle/menu/actor riêng, nếu instantiate bên trong applet khác dễ double signal, conflict actor/menu hoặc crash Cinnamon. Hướng an toàn là reuse pattern/API nội bộ có chọn lọc.

| Tính năng | Backend chọn cho v1 | Fallback | Ghi chú scan |
| --- | --- | --- | --- |
| Volume output | `Cvc.MixerControl` giống `sound@cinnamon.org` | mở `cinnamon-settings sound` | `sound@cinnamon.org` có `VolumeSlider`, `get_default_sink()`, `stream.push_volume()`. |
| Microphone | `Cvc.MixerControl` giống `sound@cinnamon.org` | disabled nếu không có source | `sound@cinnamon.org` có `_inputVolumeSection`, `get_default_source()`. |
| Brightness | DBus `org.cinnamon.SettingsDaemon.Power.Screen` | disabled/mở `cinnamon-settings display` | `brightnessctl` không có trong VM; `power@cinnamon.org` dùng `GetPercentageRemote/SetPercentageRemote`. |
| Battery | `UPowerGlib` | `upower`/ẩn nếu không có pin | VM có `/org/freedesktop/UPower/devices/battery_BAT0`. |
| Night Light | `Gio.Settings` schema `org.cinnamon.settings-daemon.plugins.color` | mở settings | key: `night-light-enabled`. |
| Wi-Fi | libnm `NM.Client`, AP objects và active connection | `cinnamon-settings network` cho secured-unsaved/enterprise/hidden | Reuse API/pattern từ `network@cinnamon.org`; không parse `nmcli` text. |
| VPN | async bounded `nmcli` profile query/action theo UUID | mở network settings | Multi-profile VPN/WireGuard; background refresh không kích spinner. |
| Bluetooth | BlueZ Adapter1/Device1/Battery1 | `blueman-manager`/`bluetoothctl` fallback | Owner watch reconnect; pairing agent vẫn deferred. |
| Lock | `cinnamon-screensaver-command --lock` | disabled nếu thiếu command | command cố định, không nhận input user. |
| Power | `cinnamon-session-quit --power-off` | disabled nếu thiếu command | command cố định, không nhận input user. |

### 4.3 UX tham khảo Ubuntu 24.04

Cần trace từ máy Ubuntu hiện tại:

- layout cụm indicator trên top bar;
- popup width/spacing/radius;
- pill button selected/disabled states;
- slider style;
- arrow submenu pattern;
- cách hiển thị battery percent;
- cách gom Wi-Fi/VPN/volume/mic.

Không copy code GNOME Shell nếu license/API không phù hợp; chỉ tham khảo UX và hành vi.

---

## 🛠️ 5. KẾ HOẠCH TRIỂN KHAI

### Phase 0 — Chốt scope an toàn

- [x] Applet chỉ bổ sung Control Center, không thay panel layout.
- [x] Migration không ghi dconf defaults.
- [x] Migration bỏ đúng icon `sound@cinnamon.org`, `network@cinnamon.org`, `power@cinnamon.org` đã được Control Center thay thế.
- [x] Mọi applet khác giữ nguyên thứ tự và position.

### Phase 1 — Scan CaramOS applets hiện có

- [x] Đọc `org.cinnamon enabled-applets` trên VM sạch.
- [x] Xác nhận panel cũ có `systray`, `network`, `sound`, `notifications`, `power`, `calendar`.
- [x] Scan source `sound@cinnamon.org`.
- [x] Scan source `power@cinnamon.org`.
- [x] Scan source `nightlight@cinnamon.org`.
- [x] Scan source `network@cinnamon.org`.
- [x] Xác nhận command/backend có sẵn: `pactl`, `nmcli`, `bluetoothctl`, `blueman-manager`, `upower`, `gdbus`, `busctl`.
- [x] Xác nhận `brightnessctl` và `powerprofilesctl` không có trong VM.

### Phase 2 — Thiết kế backend v1 an toàn

- [x] Không nhúng nguyên applet Cinnamon có sẵn.
- [x] Reuse pattern/API từ `sound@cinnamon.org` cho volume/mic.
- [x] Reuse pattern/API từ `power@cinnamon.org` cho brightness/battery.
- [x] Reuse `Gio.Settings` từ `nightlight@cinnamon.org` cho Night Light.
- [x] Để Wi-Fi/VPN full submenu sang phase sau vì `network@cinnamon.org` quá lớn/rủi ro.

### Phase 3 — Prototype UI Quick Settings

- [x] Dựng panel indicator compact.
- [x] Dựng popup quick settings giống Ubuntu.
- [x] Dựng volume slider.
- [x] Dựng mic slider.
- [x] Dựng brightness slider capability-gated.
- [x] Dựng Wi-Fi/VPN/Bluetooth tiles và inline lists.
- [x] Dựng Lock/Settings/Power buttons.
- [x] Style giống Ubuntu nhưng dùng màu CaramOS.
- [x] Reload applet trên Cinnamon 6.6.4 không có lỗi mới.

### Phase 4 — Kết nối backend ít rủi ro

- [x] Volume output bằng `Cvc.MixerControl`.
- [x] Microphone bằng `Cvc.MixerControl`.
- [x] Battery percent bằng UPower command + sysfs fallback; UPower DBus còn roadmap.
- [x] Night Light toggle bằng `Gio.Settings`.
- [x] Brightness bằng DBus `org.cinnamon.SettingsDaemon.Power.Screen`, ẩn nếu no-backlight/proxy.

### Phase 5 — Network / Wi-Fi / VPN

- [x] Wi-Fi radio/AP/SSID state dùng libnm `NM.Client` object model.
- [x] Wi-Fi scan dùng `request_scan()` và AP signals.
- [x] Saved/open Wi-Fi action dùng libnm connection/AP objects.
- [x] Secured-unsaved/enterprise/hidden mở native Cinnamon Settings/keyring flow.
- [x] Disconnect Wi-Fi dùng active connection object, không SSID text.
- [x] VPN/WireGuard list nhiều profile, action theo UUID và async refresh.
- [x] Ethernet/multiple-adapter details, default route, IP/gateway/DNS/carrier/speed.
- [x] Captive/limited connectivity state và native browser/settings handoff.
- [ ] BLOCKED — Wi-Fi hardware/SSID edge-case/auth-failure matrix.
- [ ] DEFERRED — VPN confirmation bằng NetworkManager active-connection signal; v1 dùng bounded async refresh.

### Phase 6 — Packaging + migration

- [ ] Đóng gói applet files vào `.deb`.
- [x] Migration cài applet bằng staging, validate và restore khi lỗi.
- [x] Migration atomically bỏ stock network/sound/power và append Control Center nếu chưa có.
- [x] Không ghi dconf layout.
- [x] Không reload Cinnamon cưỡng bức.

### Phase 7 — Verification

- [ ] `./tools/caramos-ota-testkit.sh compile` pass.
- [ ] `./tools/caramos-ota-testkit.sh validate` pass.
- [ ] `make ship` pass trên VM sạch.
- [ ] `make test` pass.
- [ ] Sau reboot, panel có Control Center, không còn stock network/sound/power, applet khác giữ nguyên.
- [ ] Kiểm tra `~/.xsession-errors` không có lỗi applet.

### Phase 8 — Sau v1.0.13\, nếu applet đủ ổn

- [ ] Cân nhắc full Wi-Fi list bằng `NM.Client`.
- [ ] Cân nhắc VPN list/toggle bằng `NM.Client`.
- [x] Stock network/sound/power đã được thay trong migration Control Center đang phát triển; không đụng icon khác.

## ✅ 6. ACCEPTANCE CRITERIA

### 6.1 Không phá hệ thống

- [ ] Chỉ mất stock network/sound/power; systray/notifications/calendar/custom applet giữ nguyên.
- [ ] Không đổi chiều cao panel.
- [ ] Không đổi icon size panel toàn cục.

### 6.2 Applet mới có giá trị thật

- [ ] Có panel indicator gộp.
- [ ] Popup giống Ubuntu Quick Settings về cấu trúc.
- [ ] Volume slider hoạt động.
- [ ] Mic slider hoạt động hoặc disabled rõ ràng.
- [ ] Brightness slider hoạt động hoặc disabled rõ ràng.
- [ ] Wi-Fi/VPN hiển thị trạng thái thật.
- [ ] Lock/Settings/Power hoạt động.

### 6.3 Migration an toàn

- [x] Chỉ thêm `caramos-control-center@caramos` nếu chưa có.
- [x] Bỏ đúng UUID stock network/sound/power bằng một lần `gsettings set`.
- [x] Không rewrite toàn bộ `enabled-applets` bằng layout hardcode.
- [x] Nếu `enabled-applets` format lạ thì skip, không sửa.
- [x] Dry-run không sửa hệ thống.

---

## 🧪 7. LỆNH TEST DỰ KIẾN

```bash
./tools/caramos-ota-testkit.sh compile
./tools/caramos-ota-testkit.sh validate
make ship
```

Trong VM:

```bash
cd /tmp/caramos-ota-e2e
make test
gsettings get org.cinnamon enabled-applets
tail -n 200 ~/.xsession-errors
```

Kiểm tra không có:

```text
Failed to evaluate 'main' function on applet
Could not create applet object
Tried to construct an object without a GType
```

---

## 🧯 8. ROLLBACK PLAN

Nếu applet gây lỗi, chỉ xoá riêng entry:

```text
caramos-control-center@caramos
```

Không reset toàn bộ layout.

Có thể xoá applet files:

```bash
sudo rm -rf /usr/share/cinnamon/applets/caramos-control-center@caramos
```

Reload Cinnamon thủ công nếu cần:

```bash
nohup cinnamon --replace >/tmp/cinnamon-replace.log 2>&1 &
```

---

## 📝 9. SESSION LOG

| Ngày | Nội dung | Trạng thái |
| --- | --- | --- |
| 2026-07-02 | Tạo tracker cho Control Center giống Ubuntu Quick Settings. | Planning |
| 2026-07-02 | Scan CaramOS VM: panel cũ có `systray`, `network`, `sound`, `notifications`, `power`, `calendar`; backend có `pactl`, `nmcli`, `bluetoothctl`, `blueman-manager`, `upower`; không có `brightnessctl`, `powerprofilesctl`. | Done |
| 2026-07-02 | Scan source Cinnamon applets: chọn `Cvc.MixerControl` cho volume/mic, Cinnamon Power DBus + `UPowerGlib` cho brightness/battery, `Gio.Settings` cho Night Light; Wi-Fi/VPN full submenu để phase sau. | Done |
| 2026-07-03 | Stabilize applet v1: thêm guard thiếu backend, chuyển Wi-Fi/VPN/Bluetooth sang read-only/settings fallback, giảm màu cam trong style. | Done |
| 2026-07-29 | Thêm NetworkManager/BlueZ state, async VPN, libnm Wi-Fi AP/actions, brightness capability gating, lifecycle cleanup và migration atomic/fail-closed. Reload pass trên Cinnamon 6.6.4; VM không có Wi-Fi/backlight hardware. | In Progress |
| 2026-07-29 | Code freeze: Ethernet/multi-adapter details, UPower signal backend, audio mute/selectors, session capability/native confirmation, theme/a11y/focus, static tests. `node --check`, `git diff --check`, 13 unit/static tests và VM reload pass. | Code Complete |

---

## 🚧 10. VIỆC CẦN LÀM NGAY TIẾP THEO

Feature freeze. Chỉ test/fix:

1. Chạy `compile`, `validate`, package content và full `.deb` lifecycle.
2. Test hardware matrix: Wi-Fi/auth/captive portal, Bluetooth, laptop battery/backlight/UPS, audio hotplug.
3. Test session cancel/inhibitor/logout/restart/shutdown; không tự kích hoạt destructive action trong smoke tự động.
4. Test keyboard/screen reader/high-contrast/large text, bốn orientation, multi-monitor/HiDPI.
5. Mọi lỗi mới ghi test/evidence rồi fix; không thêm feature P2/optional vào v1.0.13\.
