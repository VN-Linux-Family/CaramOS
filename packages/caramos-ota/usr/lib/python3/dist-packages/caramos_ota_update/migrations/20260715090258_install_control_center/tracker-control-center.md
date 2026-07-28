# 🧾 TRACKER — CaramOS Control Center Applet giống Ubuntu Quick Settings

> Tracker triển khai cho `20260715090258_install_control_center\`: nâng applet `caramos-control-center@caramos`
> từ menu tile tạm bợ sang trung tâm điều khiển giống Ubuntu Quick Settings.
>
> Nguyên tắc quan trọng: migration chỉ cài/thêm applet, không rewrite layout panel,
> không ghi đè dconf toàn cục, không xoá icon cũ.

---

## 🔖 1. THÔNG TIN CHUNG

| Trường | Giá trị |
| --- | --- |
| **ID** | CARAMOS-OTA-CC-001 |
| **Tên task** | Xây dựng CaramOS Control Center giống Ubuntu Quick Settings |
| **Loại** | Desktop UX / Cinnamon Applet / OTA Migration |
| **Độ ưu tiên** | High |
| **Mức ảnh hưởng** | Medium-High |
| **Trạng thái tổng thể** | Planning |
| **Người phụ trách** | dungleviet |
| **Người yêu cầu** | CaramOS maintainer |
| **Reviewer** | TBD |
| **Ngày tạo** | 2026-07-02 |
| **Cập nhật lần cuối** | 2026-07-02 |
| **Target release** | CaramOS OTA 1.0.13\ |
| **Branch / PR** | TBD |

### 1.1 Trạng thái phase

| Phase | Tên phase | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| 0 | Chốt scope và nguyên tắc an toàn | Done | Control Center là applet mới, không đụng layout panel cũ. |
| 1 | Trace Ubuntu Quick Settings / CaramOS applets | Done | Đã scan VM CaramOS và source applet Cinnamon có sẵn. |
| 2 | Thiết kế kiến trúc applet Cinnamon | In Progress | Đã chốt backend ưu tiên cho v1 an toàn. |
| 3 | Implement panel indicator gộp | In Progress | Có cụm icon pin, mic, Wi-Fi/VPN, volume; đang cần VM verify. |
| 4 | Implement popup Quick Settings | In Progress | Có sliders + tiles + fallback actions; đang giảm rủi ro network/Bluetooth. |
| 5 | Kết nối audio/mic | In Progress | Dùng `Cvc.MixerControl`, có guard khi thiếu sink/source. |
| 6 | Kết nối brightness | In Progress | Dùng DBus Cinnamon Settings Daemon Power, disabled nếu backend thiếu. |
| 7 | Kết nối Wi-Fi/VPN/network | In Progress | v1 read-only/status + mở settings; không connect/disconnect trực tiếp. |
| 8 | Kết nối power/battery/night light | In Progress | Battery qua `upower`, Night Light qua Gio.Settings. |
| 9 | Style giống Ubuntu nhưng hợp CaramOS | In Progress | Giảm màu cam, giữ cam làm active accent. |
| 10 | Packaging + migration an toàn | Todo | Migration chỉ copy applet và append entry. |
| 11 | Verification trên VM | Todo | Không mất icon cũ, applet ổn sau reboot. |

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
2. append đúng applet mới vào `org.cinnamon enabled-applets` nếu chưa có;
3. không sửa `panels-height`;
4. không sửa `panel-zone-*`;
5. không ghi `/etc/dconf/db/local.d/...` cho layout panel;
6. không xoá hoặc reorder applet cũ.

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
| Wi-Fi | v1 mở `cinnamon-settings network`, status đơn giản nếu an toàn | chỉ mở settings | `network@cinnamon.org` rất lớn, dùng `NM.Client`; full list để phase sau. |
| VPN | v1 mở network settings, status active nếu an toàn | chỉ mở settings | `network@cinnamon.org` có category `VPN/WIREGUARD`; toggle để phase sau. |
| Bluetooth | mở `blueman-manager` | disabled nếu thiếu command | VM có `bluetoothctl` và `blueman-manager`. |
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
- [x] Migration không xoá icon cũ.
- [x] Không gỡ `sound@cinnamon.org`, `network@cinnamon.org`, `power@cinnamon.org` trong v1.0.13\.

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

- [ ] Dựng panel indicator compact.
- [ ] Dựng popup quick settings giống Ubuntu.
- [ ] Dựng volume slider.
- [ ] Dựng mic slider.
- [ ] Dựng brightness slider.
- [ ] Dựng Wi-Fi/VPN/Bluetooth tiles.
- [ ] Dựng Lock/Settings/Power buttons.
- [ ] Style giống Ubuntu nhưng dùng màu CaramOS.
- [ ] Test Cinnamon không crash.

### Phase 4 — Kết nối backend ít rủi ro

- [ ] Volume output bằng `Cvc.MixerControl`.
- [ ] Microphone bằng `Cvc.MixerControl`.
- [ ] Battery percent bằng `UPowerGlib`.
- [ ] Night Light toggle bằng `Gio.Settings`.
- [ ] Brightness bằng DBus `org.cinnamon.SettingsDaemon.Power.Screen`, fallback disabled nếu không có proxy.

### Phase 5 — Network / Wi-Fi / VPN tối giản

- [x] Wi-Fi tile hiển thị trạng thái đơn giản nếu lấy được an toàn.
- [x] Wi-Fi tile mở `cinnamon-settings network`.
- [x] VPN tile hiển thị active status nếu lấy được an toàn.
- [x] VPN tile mở `cinnamon-settings network`.
- [x] Không implement Wi-Fi connect trong vòng này.
- [x] Không implement VPN connect/disconnect trong vòng này.

### Phase 6 — Packaging + migration

- [ ] Đóng gói applet files vào `.deb`.
- [ ] Migration chỉ copy applet.
- [ ] Migration append applet nếu chưa có.
- [ ] Không ghi dconf layout.
- [ ] Không reload Cinnamon cưỡng bức.

### Phase 7 — Verification

- [ ] `./tools/caramos-ota-testkit.sh compile` pass.
- [ ] `./tools/caramos-ota-testkit.sh validate` pass.
- [ ] `make ship` pass trên VM sạch.
- [ ] `make test` pass.
- [ ] Sau reboot, panel vẫn đủ icon cũ + Control Center.
- [ ] Kiểm tra `~/.xsession-errors` không có lỗi applet.

### Phase 8 — Sau v1.0.13\, nếu applet đủ ổn

- [ ] Cân nhắc full Wi-Fi list bằng `NM.Client`.
- [ ] Cân nhắc VPN list/toggle bằng `NM.Client`.
- [ ] Cân nhắc thay thế một số icon cũ, nhưng chỉ khi có migration riêng và rollback rõ.

## ✅ 6. ACCEPTANCE CRITERIA

### 6.1 Không phá hệ thống

- [ ] Không mất systray/network/sound/notifications/power/battery/calendar.
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

- [ ] Chỉ thêm `caramos-control-center@caramos` nếu chưa có.
- [ ] Không rewrite toàn bộ `enabled-applets` bằng layout hardcode.
- [ ] Nếu `enabled-applets` format lạ thì skip, không sửa.
- [ ] Dry-run không sửa hệ thống.

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
| 2026-07-03 | Stabilize applet v1: thêm guard thiếu backend, chuyển Wi-Fi/VPN/Bluetooth sang read-only/settings fallback, giảm màu cam trong style. | In Progress |

---

## 🚧 10. VIỆC CẦN LÀM NGAY TIẾP THEO

1. Review tracker và chốt scope v1.0.13\.
2. Prototype UI Quick Settings trong `applet.js`/`stylesheet.css`.
3. Kết nối backend ít rủi ro theo thứ tự: battery → Night Light → volume → mic → brightness.
4. Giữ Wi-Fi/VPN/Bluetooth ở mức tile mở settings/manager trong vòng đầu.
5. Chạy compile/validate trước khi ship vào VM.
