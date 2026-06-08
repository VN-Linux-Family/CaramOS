# CaramOS packages

Thư mục `packages/` chứa các Debian source package do CaramOS tự duy trì. Đây là lớp migration riêng của distro. Với OTA, CaramOS chốt model migration theo version: các thay đổi branding/cấu hình sau phát hành nằm trong `caramos-ota-update` migrations, không tách mỗi thay đổi thành một migration riêng.

> [!IMPORTANT]
> Kiến trúc OTA mới của CaramOS là **version migration-driven OTA**: migration index chỉ báo `release`, còn việc cập nhật thật được chạy theo chuỗi migration trong `caramos-ota-update`.

---

## 1. Mục tiêu của `packages/`

CaramOS là ISO remaster dựa trên Linux Mint/Ubuntu. Sau khi phát hành ISO, ta vẫn cần cập nhật các thành phần riêng mà không bắt user tải lại ISO.

Các package trong thư mục này dùng để:

- Cài/cập nhật công cụ OTA của CaramOS.
- Cài/cập nhật branding, wallpaper, icon, theme, cấu hình desktop.
- Cài/cập nhật cấu hình hệ thống mặc định.
- Cung cấp migration để nâng CaramOS từ version này lên version khác.
- Đẩy bản vá nhỏ qua PPA sau khi ISO đã phát hành.
- Kiểm thử pipeline build/upload PPA.

---

## 2. Kiến trúc OTA mới

Thay vì manifest liệt kê từng package cần `min_version`, CaramOS OTA dùng model giống database migration:

```text
current CaramOS version
  └── migration A -> B
      └── migration B -> C
          └── migration C -> D
              └── target/latest version
```

Ba command chính:

| Command | Vai trò |
|---|---|
| `caramos-ota` | Orchestrator: check OS/repo, tải manifest, so current/latest version, ghi state, gọi updater. |
| `caramos-ota-notifier` | Desktop UI: đọc state, hiện popup, gọi `pkexec caramos-ota --upgrade --yes`. |
| `caramos-ota-update` | Migration runner: chạy từng migration version theo thứ tự. |

Flow tổng thể:

```text
Contributor sửa package hoặc migration
  └── build .deb
      └── upload PPA ppa:vietnamlinuxfamily/caram-os
          └── cập nhật migration index release
              └── máy user chạy caramos-ota --check
                  ├── tải migration index
                  ├── thấy release > current_version
                  └── ghi available_update vào state

User đồng ý update
  └── caramos-ota --upgrade
      └── caramos-ota-update --target <release>
          ├── chạy migration current -> next
          ├── ghi state sau mỗi migration thành công
          ├── chạy migration next -> target
          └── cập nhật /etc/caramos-release
```

Điểm quan trọng:

- PPA vẫn là nơi chứa `.deb` thật sự.
- Migration metadata **không chứa script**, không chứa URL tải `.deb`.
- Manifest chỉ là metadata release: `release`, release notes, schema, codename/channel.
- Logic thay đổi hệ thống nằm trong migration code đã được đóng gói, review và cài qua APT.
- `caramos-ota` không nên biến thành mini package manager.
- `caramos-ota-update` mới là nơi quyết định update từng version làm gì.

---

## 3. Vai trò của `caramos-ota`

`caramos-ota` là package trung tâm trong `packages/`.

Nó gồm 3 phần:

```text
caramos-ota package
├── /usr/bin/caramos-ota              # check + orchestrator
├── /usr/bin/caramos-ota-notifier     # desktop notifier
└── /usr/bin/caramos-ota-update       # migration runner
```

Trách nhiệm tách rõ:

### `caramos-ota`

- Xác minh máy đang chạy đúng CaramOS.
- Xác minh PPA/keyring CaramOS đã được cài từ ISO.
- Tải manifest OTA online.
- Fallback sang migration-local manifest nếu online lỗi.
- So sánh `current_version` với `release`.
- Ghi `/var/lib/caramos-ota/state.json`.
- Khi upgrade, gọi `caramos-ota-update`.
- Không tự nhét toàn bộ migration logic vào CLI chính.

### `caramos-ota-notifier`

- Chạy trong desktop session.
- Đọc state do `caramos-ota --check` ghi.
- Hiện popup tiếng Việt.
- Khi user bấm cập nhật, gọi:

```bash
pkexec /usr/bin/caramos-ota --upgrade --yes
```

Notifier không tự parse manifest, không tự chạy APT, không tự quyết định update.

### `caramos-ota-update`

- Chạy với quyền root.
- Đọc current version và target version.
- Tìm chuỗi migration cần chạy.
- Chạy từng migration theo thứ tự.
- Ghi transaction/log sau từng bước.
- Cập nhật `/etc/caramos-release` khi migration thành công.
- Nếu lỗi, dừng ở version cuối cùng đã thành công để lần sau chạy tiếp.

---

## 4. Migration metadata và migration-local manifest

Có 2 loại manifest:

| Loại manifest | Vị trí | Vai trò |
|---|---|---|
| Migration metadata | `caramos_ota_update/migrations/migration.json` | Danh sách version migration được đóng gói. |
| Migration-local manifest | `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json` | Metadata đóng gói theo từng migration. |

### 4.1 URL manifest

`caramos-ota` build URL từ `/etc/caramos-release`:

```text
caramos_ota_update/migrations/migration.json
```

Ví dụ:

```text
caramos_ota_update/migrations/migration.json
https://caramos.vietnamlinuxfamily.net/ota/beta/noble/manifest.json
https://caramos.vietnamlinuxfamily.net/ota/stable/oracular/manifest.json
```

Cấu trúc deploy trên server:

```text
/ota/
├── stable/
│   ├── noble/
│   │   └── manifest.json
│   └── oracular/
│       └── manifest.json
└── beta/
    └── noble/
        └── manifest.json
```

### 4.2 Mẫu manifest mới

Manifest v1 theo migration model:

```json
{
  "schema": 1,
  "channel": "stable",
  "codename": "noble",
  "current_series": "1.x",
  "release": "1.0.2",
  "min_client_version": "1.0.2-0caramos1",
  "release_notes_vi": [
    "Cập nhật WPS Office.",
    "Sửa cấu hình input method.",
    "Cập nhật branding CaramOS."
  ],
  "release_notes_en": [
    "Update WPS Office.",
    "Fix input method configuration.",
    "Update CaramOS branding."
  ]
}
```

Quy tắc:

- `schema` giữ tương thích lâu nhất có thể.
- `channel` và `codename` phải khớp URL và `/etc/caramos-release`.
- `release` là target version mà migration runner có thể chạy tới.
- `min_client_version` là version tối thiểu của package `caramos-ota` có thể hiểu manifest này.
- Manifest không chứa command, shell script, URL `.deb` hoặc package action.
- Nếu cần logic mới, phát hành `caramos-ota` mới qua PPA trước, rồi mới nâng manifest.

---

## 5. Migration model

Migration là một bước nâng CaramOS từ version này sang version kế tiếp.

Ví dụ:

```text
1.0.2 -> 1.0.3
1.0.3 -> 1.0.4
1.0.4 -> 1.0.5
```

Source nên có dạng:

```text
packages/caramos-ota/
└── usr/lib/python3/dist-packages/
    └── caramos_ota_update/
        ├── __init__.py
        ├── cli.py
        ├── runner.py
        ├── context.py
        ├── apt.py
        └── migrations/
            ├── __init__.py
            ├── v1_0_2_to_v1_0_3.py
            ├── v1_0_3_to_v1_0_4.py
            └── v1_0_4_to_v1_0_5.py
```

Một migration nên khai báo rõ:

```python
FROM_VERSION = "1.0.3"
TO_VERSION = "1.0.2"
DESCRIPTION = "Install WPS Office and update Vietnamese input defaults"


def run(context):
    context.apt_install([
        "wps-office",
        "fcitx5",
    ])
    context.ensure_service_enabled("fcitx5")
    context.update_release_file("1.0.2")
```

Rule cho migration:

- Mỗi migration chỉ đi từ một version sang version kế tiếp.
- Migration phải idempotent càng nhiều càng tốt.
- Không append config mù quáng gây duplicate.
- Không tải `.deb` thủ công nếu có thể cài qua APT/PPA.
- Mỗi bước nguy hiểm phải log rõ.
- Nếu fail, dừng ngay, giữ state/log để debug.
- Không nhét nhiều release vào một migration khổng lồ.

---

## 6. Cấu trúc thư mục `packages/`

```text
packages/
├── README.md
├── caramos-ota/
│   ├── README.md
│   ├── README_EN.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── debian/
│   ├── etc/
│   ├── lib/
│   └── usr/
├── caram-os-demo/
│   ├── debian/
│   └── ...
├── *.deb
├── *.buildinfo
└── *.changes
```

### `caramos-ota/`

Source Debian package của OTA. Đây là package vận hành thật và là nơi chứa CLI, notifier, updater, migration runner.

Tài liệu chi tiết:

- [caramos-ota/README.md](./caramos-ota/README.md)

### `caram-os-demo/`

Package demo dùng để kiểm thử PPA/build/install flow. Không phải package vận hành chính của distro.

### Output build

Các file `.deb`, `.buildinfo`, `.changes` là output của `dpkg-buildpackage`. Không nên commit nếu không có lý do release rõ ràng.

---

## 7. Thêm update CaramOS mới

Giả sử muốn nâng CaramOS từ `1.0.3` lên `1.0.2`.

### Bước 1: Thêm migration

Tạo file:

```text
packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/v1_0_3_to_v1_0_4.py
```

Migration chứa các action cần thiết:

- cài/nâng package qua APT;
- xóa package cũ nếu cần;
- sửa config;
- enable/disable service;
- cập nhật branding;
- cập nhật `/etc/caramos-release` sau khi thành công.

### Bước 2: Tăng version `caramos-ota`

Sửa:

```text
packages/caramos-ota/debian/changelog
```

Ví dụ:

```text
caramos-ota (1.0.2-0caramos1) noble; urgency=medium
```

### Bước 3: Build và test

```bash
cd packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/migrations/*.py

dpkg-buildpackage -us -uc -b
```

### Bước 4: Upload PPA

Upload `caramos-ota` mới lên:

```text
ppa:vietnamlinuxfamily/caram-os
```

### Bước 5: Cập nhật migration index

Sau khi PPA publish xong, đổi:

```json
{
  "release": "1.0.2",
  "min_client_version": "1.0.2-0caramos1"
}
```

Nếu client cũ chưa hiểu migration model, cần bridge rollout: phát hành bản bridge trước, manifest cũ yêu cầu update lên bridge, sau đó mới publish manifest mới.

---

## 8. Compile, build và test cho contributor

### 8.1 Chuẩn bị môi trường

Test tốt nhất trong VM CaramOS/Linux Mint 22/Ubuntu 24.04.

```bash
sudo apt update
sudo apt install --yes build-essential devscripts debhelper dh-python python3 python3-gi gir1.2-gtk-3.0
```

### 8.2 Compile Python

```bash
cd packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/migrations/*.py
```

Nếu package update module chưa tồn tại trong source hiện tại, compile các path đang có trước; khi refactor xong phải thêm `caramos_ota_update` vào checklist.

### 8.3 Validate manifest bundled

```bash
cd packages/caramos-ota
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
```

Manifest migration model cần có:

```text
schema
channel
codename
release
release_notes_vi/release_notes_en
```

### 8.4 Build Debian package

```bash
cd packages/caramos-ota
dpkg-buildpackage -us -uc -b
```

Output nằm ở thư mục cha `packages/`.

### 8.5 Inspect `.deb`

```bash
cd packages
dpkg-deb -c caramos-ota_1.0.2-0caramos1_all.deb
```

Cần thấy:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/bin/caramos-ota-update
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/lib/python3/dist-packages/caramos_ota_update/
caramos_ota_update/migrations/migration.json
/lib/systemd/system/caramos-ota-check.service
/lib/systemd/system/caramos-ota-check.timer
/etc/xdg/autostart/caramos-ota-notifier.desktop
```

### 8.6 Test install local trong VM

```bash
cd packages
sudo apt install ./caramos-ota_1.0.2-0caramos1_all.deb
```

Kiểm tra:

```bash
command -v caramos-ota
command -v caramos-ota-notifier
command -v caramos-ota-update
caramos-ota --version
```

### 8.7 Test check/update

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota-update --target 1.0.2 --dry-run
```

Kỳ vọng:

- `--check` không cài package.
- `--dry-run` không sửa hệ thống.
- Nếu không phải CaramOS, fail closed.
- Nếu migration index lỗi, fail closed và log rõ lỗi.
- Updater in đúng migration path cần chạy.

### 8.8 Test offline manifest

```bash
cd packages/caramos-ota
PYTHONPATH=usr/lib/python3/dist-packages python3 - <<'PY'
from pathlib import Path
import json

path = Path("usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json")
manifest = json.loads(path.read_text(encoding="utf-8"))
assert manifest["schema"] == 1
assert manifest["codename"]
assert manifest["release"]
print("migration-local manifest OK")
PY
```

### 8.9 Test migration thật trong VM snapshot

```text
1. Cài ISO hoặc VM ở version cũ.
2. Cài/PPA publish caramos-ota mới có migration.
3. Cập nhật manifest release.
4. Chạy sudo caramos-ota --check.
5. Chạy sudo caramos-ota-update --target <version> --dry-run.
6. Chạy sudo caramos-ota --upgrade.
7. Kiểm tra /etc/caramos-release đã lên version mới.
8. Kiểm tra log/state không báo failed.
```

### 8.10 Cleanup trước khi commit

Không commit output build/cache:

```bash
find packages -name '__pycache__' -type d -prune -exec rm -rf {} +
rm -f packages/*.deb packages/*.buildinfo packages/*.changes packages/*.dsc packages/*.tar.*
```

---

## 9. Quy ước version

Package CaramOS nên dùng suffix rõ ràng:

```text
1.0.2-0caramos1
```

Ý nghĩa:

- `1.0.2`: version CaramOS/OTA nội bộ.
- `0caramos1`: Debian packaging revision dành cho CaramOS.

Khi upload PPA, version mới phải lớn hơn version cũ theo Debian version comparison.

---

## 10. Policy cho contributor

- Không nhét toàn bộ logic vào một file `/usr/bin` dài.
- CLI entrypoint chỉ nên mỏng, logic nằm trong Python package.
- Update hệ thống phải chạy qua migration rõ version.
- Migration phải idempotent càng nhiều càng tốt.
- Không tự thêm PPA trong OTA; PPA/keyring phải đến từ ISO.
- Không tải `.deb` thủ công từ manifest.
- Không chạy script từ Internet.
- Không auto-install từ systemd timer.
- Luôn test trong VM/snapshot trước khi release.

---

## 11. Checklist trước khi release OTA

- [ ] Migration mới có `FROM_VERSION` và `TO_VERSION` rõ ràng.
- [ ] Migration chạy được dry-run.
- [ ] Migration idempotent hoặc có guard chống chạy lặp.
- [ ] `python3 -m py_compile` pass.
- [ ] `dpkg-buildpackage -us -uc -b` pass.
- [ ] `.deb` chứa `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`.
- [ ] Cài local `.deb` trong VM pass.
- [ ] `caramos-ota --check` không tự cài package.
- [ ] `caramos-ota-update --dry-run` không sửa hệ thống.
- [ ] Migration metadata `release` trỏ tới version có migration tương ứng.
- [ ] Offline/migration-local manifest vẫn parse được.
- [ ] Nếu đổi schema, đã có bridge rollout.
- [ ] Không commit output build/cache ngoài ý muốn.

---

## 12. Tóm tắt

```text
caramos-ota
  = check + state + gọi updater

caramos-ota-notifier
  = UI desktop + gọi caramos-ota

caramos-ota-update
  = migration runner theo version

migration index
  = release + release notes + min_client_version

PPA
  = nơi chứa package .deb thật
```

Nói ngắn gọn: **CaramOS OTA không còn là package manifest manager; nó là hệ thống nâng version CaramOS bằng migration có thứ tự.**

---

## 13. Release hiện tại: `caramos-ota` 1.0.5

Người release PPA: **dungleviet**.

Mục tiêu release hiện tại là để máy CaramOS `1.0.1` cài `caramos-ota` rồi tự nâng lên `1.0.5`:

```bash
sudo apt update
sudo apt install caramos-ota
sudo caramos-ota
```

Chuỗi migration được đóng gói trong `caramos-ota`:

```text
1.0.1 → 1.0.2 → 1.0.3 → 1.0.4 → 1.0.5
```

Checklist release nhanh:

```bash
cd /home/dungleviet/Documents/CaramOS/packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py \
  usr/lib/python3/dist-packages/caramos_ota_update/migrations/*/*.py
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
dpkg-buildpackage -us -uc -b
sudo ./tools/ship-ota-to-vm.sh
```

Trong VM test:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
grep -E '^(VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release
sudo add-apt-repository -y ppa:mozillateam/ppa
sudo rm -f /etc/apt/sources.list.d/*mozillateam*
sudo apt update
```

Upload PPA sau khi bump `debian/changelog` lên `1.0.5-0caramos1`:

```bash
debuild -S -sa
dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.5-0caramos1_source.changes
```

Sau khi PPA publish, kiểm tra candidate:

```bash
sudo apt update
apt-cache policy caramos-ota
```

ISO build dùng `CARAMOS_VERSION=1.0.5` cho tên ISO, và `CARAMOS_MIGRATION_BASE_VERSION=1.0.1` để OTA bootstrap chạy đủ migration chain trong rootfs.
