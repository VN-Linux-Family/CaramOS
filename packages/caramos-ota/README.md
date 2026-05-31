# CaramOS OTA

> **Package:** `caramos-ota`  
> **CLI:** `sudo caramos-ota`  
> **Desktop notifier:** `caramos-ota-notifier`  
> **Target OS:** CaramOS 1.x, Linux Mint 22.x / Ubuntu 24.04 LTS `noble`  
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`  
> **Language:** CLI/log in English, GUI/documentation in Vietnamese

`caramos-ota` là hệ thống cập nhật OTA riêng của CaramOS. Package này không thay thế hoàn toàn `apt upgrade` của Ubuntu/Linux Mint; nó là lớp điều phối update dành riêng cho những thành phần do CaramOS quản lý: branding, cấu hình hệ thống, package bổ sung, bản vá nhỏ, metadata release và trải nghiệm desktop.

Mục tiêu của contributor khi sửa package này là giữ cho CaramOS có thể update an toàn qua PPA trong suốt vòng đời phát hành, không làm hỏng máy người dùng, không tự ý thêm repository lạ, không chạy update nền khi chưa có xác nhận, và luôn có log/state đủ để debug.

---

## 1. Đọc nhanh cho contributor mới

Nếu bạn chỉ có vài phút, hãy nắm các điểm này trước:

1. `/usr/bin/caramos-ota` chỉ là entrypoint mỏng. Logic CLI nằm trong Python package `caramos_ota`.
2. `/usr/bin/caramos-ota-notifier` chỉ là entrypoint mỏng. Logic GUI nằm trong Python package riêng `caramos_ota_notifier`.
3. CLI là nguồn sự thật duy nhất cho update logic: detect OS, verify repo, parse manifest, chạy APT, ghi state/transaction.
4. Notifier chỉ đọc `/var/lib/caramos-ota/state.json` và gọi `pkexec /usr/bin/caramos-ota --upgrade --yes` khi user bấm cập nhật.
5. Manifest OTA nằm ở `/usr/share/caramos-ota/manifest.json` và được ship trong chính package.
6. CaramOS ISO phải cài sẵn PPA/keyring; OTA không tự thêm PPA.
7. Mọi thao tác sửa hệ thống phải fail closed nếu không xác minh được OS/repo/manifest/lock/state.
8. Không tự động cài update từ systemd timer. Timer chỉ check và ghi state để notifier hiển thị.
9. Build test bằng `dpkg-buildpackage -us -uc -b` trong thư mục này.
10. Sau khi sửa Python, luôn chạy `python3 -m py_compile` cho cả hai package Python.

---

## 2. Tại sao CaramOS cần OTA riêng

CaramOS dựa trên Linux Mint/Ubuntu nên vẫn dùng APT làm package manager chính. Tuy nhiên distro cần một lớp OTA riêng vì các thay đổi của CaramOS không chỉ là package upstream:

- Branding: wallpaper, icon, theme, Plymouth, desktop entries.
- Cấu hình distro: locale, input method, panel defaults, policy, services.
- Package do Vietnam Linux Family duy trì trong PPA.
- Release metadata để biết máy đang ở release nào của CaramOS.
- Desktop notification bằng tiếng Việt cho người dùng phổ thông.
- State/transaction/log để hỗ trợ support và rollback best-effort.

Nếu chỉ bảo user tự chạy `apt upgrade`, contributor sẽ khó kiểm soát trải nghiệm cập nhật, khó giải thích bản cập nhật gồm gì, và khó biết máy đã nhận bản update CaramOS nào. `caramos-ota` giải quyết vấn đề này bằng cách dùng APT bên dưới nhưng đặt một lớp policy/manifest/state phía trên.

---

## 3. Nguyên lý tổng thể

CaramOS OTA hoạt động theo mô hình manifest-driven update:

```text
CaramOS PPA
  └── caramos-ota package
      ├── /usr/share/caramos-ota/manifest.json
      ├── /usr/bin/caramos-ota
      ├── /usr/bin/caramos-ota-notifier
      ├── caramos_ota Python package
      └── caramos_ota_notifier Python package

Systemd timer
  └── caramos-ota --check
      ├── verify CaramOS identity
      ├── verify PPA/keyring
      ├── apt-get update
      ├── parse manifest
      ├── compare installed/candidate versions
      └── write /var/lib/caramos-ota/state.json

Desktop session
  └── caramos-ota-notifier
      ├── read state.json
      ├── show GTK dialog if update exists
      └── run pkexec caramos-ota --upgrade --yes when user accepts
```

Điểm quan trọng: manifest chỉ nói CaramOS muốn package nào đạt tối thiểu version nào. Việc cài đặt thực tế vẫn do APT quyết định từ repository đã cấu hình. Vì vậy OTA không bypass APT, không tải binary thủ công, không tự chạy script từ Internet.

---

## 4. Luồng hoạt động chi tiết

### 4.1 Check thủ công

User hoặc systemd timer chạy:

```bash
sudo caramos-ota --check
```

Luồng:

1. Check root.
2. Tạo log ngày trong `/var/log/caramos-ota/`.
3. Lấy lock `/var/lib/caramos-ota/lock` để chặn chạy song song.
4. Đọc `/etc/caramos-release`.
5. Từ chối nếu không phải CaramOS, không phải codename `noble`, hoặc channel không phải `stable`.
6. Kiểm tra keyring `/usr/share/keyrings/caramos-archive-keyring.gpg`.
7. Kiểm tra APT source có PPA `ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os`.
8. Chạy `apt-get update -qq`.
9. Đọc `/usr/share/caramos-ota/manifest.json`.
10. Với từng component trong manifest:
    - kiểm tra package name hợp lệ;
    - lấy installed version bằng `dpkg-query`;
    - lấy candidate version bằng `apt-cache policy`;
    - dùng `dpkg --compare-versions` để so version.
11. Ghi `available_update` vào state nếu có update.
12. Ghi `last_check`.

### 4.2 Upgrade thủ công

User chạy:

```bash
sudo caramos-ota
```

hoặc:

```bash
sudo caramos-ota --upgrade
```

Luồng giống `--check`, sau đó:

1. Hiển thị danh sách package sẽ cài/nâng cấp.
2. Hỏi xác nhận, trừ khi có `--yes`.
3. Tạo transaction trong state với status `pending`.
4. Chạy `apt-get install --yes -- <packages>` bằng `subprocess.run([...], shell=False)`.
5. Nếu thành công:
   - đổi transaction status thành `success`;
   - cập nhật `installed_release`;
   - cập nhật `last_successful_upgrade`;
   - xóa `available_update`.
6. Nếu thất bại:
   - đổi transaction status thành `failed`;
   - giữ log để support;
   - gợi ý `sudo caramos-ota --repair`.

### 4.3 Check nền bằng systemd

Timer `caramos-ota-check.timer` kích hoạt `caramos-ota-check.service` mỗi ngày.

Service chỉ chạy:

```bash
/usr/bin/caramos-ota --check
```

Không được tự động cài package. Mục đích của check nền là chuẩn bị state để desktop notifier biết có update hay không.

### 4.4 Desktop notifier

Autostart chạy:

```text
/usr/bin/caramos-ota-notifier
```

Luồng:

1. Nếu không có `DISPLAY` hoặc `WAYLAND_DISPLAY`, thoát im lặng.
2. Đọc `/var/lib/caramos-ota/state.json`.
3. Nếu không có `available_update`, thoát im lặng.
4. Dựng GTK dialog theo màu CaramOS/VNLF.
5. Nếu user bấm “Để sau”, thoát.
6. Nếu user bấm “Cập nhật ngay”:
   - mở progress dialog;
   - chạy thread nền;
   - gọi `pkexec /usr/bin/caramos-ota --upgrade --yes`;
   - hiển thị kết quả.

Notifier không parse manifest, không gọi `apt-get update`, không quyết định package nào cần update. Đây là ranh giới trách nhiệm quan trọng.

### 4.5 Repair

```bash
sudo caramos-ota --repair
```

Chạy best-effort:

```bash
dpkg --configure -a
apt-get --fix-broken install --yes
```

Dùng khi upgrade bị lỗi giữa chừng hoặc APT/dpkg đang ở trạng thái broken.

### 4.6 Rollback best-effort

```bash
sudo caramos-ota --rollback
```

Rollback đọc transaction `success` mới nhất:

- Package action `install`: thử remove.
- Package action `upgrade`: thử downgrade về old version nếu APT còn version đó.

Rollback chỉ best-effort vì PPA có thể đã không còn giữ version cũ hoặc dependency graph đã thay đổi.

---

## 5. Cấu trúc thư mục source

```text
packages/caramos-ota/
├── README.md
├── README_EN.md
├── IMPLEMENTATION_PLAN.md
├── debian/
│   ├── changelog
│   ├── control
│   ├── install
│   ├── postinst
│   ├── rules
│   └── source/
│       └── format
├── etc/
│   ├── logrotate.d/
│   │   └── caramos-ota
│   └── xdg/
│       └── autostart/
│           └── caramos-ota-notifier.desktop
├── lib/
│   └── systemd/
│       └── system/
│           ├── caramos-ota-check.service
│           └── caramos-ota-check.timer
└── usr/
    ├── bin/
    │   ├── caramos-ota
    │   └── caramos-ota-notifier
    ├── lib/
    │   └── python3/
    │       └── dist-packages/
    │           ├── caramos_ota/
    │           │   ├── __init__.py
    │           │   ├── apt.py
    │           │   ├── cli.py
    │           │   ├── constants.py
    │           │   ├── errors.py
    │           │   ├── logging_utils.py
    │           │   ├── manifest.py
    │           │   ├── models.py
    │           │   ├── privilege.py
    │           │   ├── release.py
    │           │   ├── repo.py
    │           │   └── state.py
    │           └── caramos_ota_notifier/
    │               ├── __init__.py
    │               ├── app.py
    │               ├── constants.py
    │               ├── state.py
    │               └── ui.py
    └── share/
        ├── caramos-ota/
        │   └── manifest.json
        └── polkit-1/
            └── actions/
                └── net.vietnamlinuxfamily.caramos-ota.policy
```

---

## 6. Vai trò từng phần

### 6.1 `usr/bin/`

| File | Vai trò |
|---|---|
| `usr/bin/caramos-ota` | Entrypoint mỏng cho CLI. Import `caramos_ota.cli.main`. |
| `usr/bin/caramos-ota-notifier` | Entrypoint mỏng cho desktop notifier. Import `caramos_ota_notifier.app.main`. |

Không nhét logic lớn vào `/usr/bin`. File trong đây nên nhỏ để systemd, polkit, autostart và user có command ổn định, còn logic nằm trong package Python có cấu trúc rõ.

### 6.2 `caramos_ota` package

| Module | Vai trò |
|---|---|
| `cli.py` | Parse argument, route action, điều phối check/upgrade/status/repair/rollback. |
| `apt.py` | Tất cả thao tác APT/dpkg: update, detect version, install, remove, downgrade, repair. |
| `manifest.py` | Đọc và validate manifest OTA. Validate package name. |
| `state.py` | Đọc/ghi `/var/lib/caramos-ota/state.json`, transaction, atomic save. |
| `release.py` | Đọc và validate `/etc/caramos-release`. |
| `repo.py` | Verify keyring và PPA source. |
| `privilege.py` | Check root và giữ lock file. |
| `logging_utils.py` | Log ngày, timestamp, helper in status. |
| `models.py` | Dataclass cho release, manifest component, update package. |
| `constants.py` | Version, path, exit code, pattern. |
| `errors.py` | Exception user-facing có exit code. |

### 6.3 `caramos_ota_notifier` package

| Module | Vai trò |
|---|---|
| `app.py` | Main flow GUI: check display, đọc state, mở dialog, gọi pkexec, quản lý thread/progress. |
| `state.py` | Đọc state theo quyền user desktop và normalize data cho UI. |
| `ui.py` | GTK3 dialogs, CSS theme, update/progress/result dialog. |
| `constants.py` | Command path, `pkexec`, timeout. |

### 6.4 `usr/share/caramos-ota/manifest.json`

Manifest là policy update hiện tại của CaramOS. Package `caramos-ota` ship manifest này để CLI biết release nào cần package nào.

### 6.5 `lib/systemd/system/`

| Unit | Vai trò |
|---|---|
| `caramos-ota-check.service` | Chạy check một lần. |
| `caramos-ota-check.timer` | Lên lịch check hằng ngày. |

### 6.6 `etc/xdg/autostart/`

`caramos-ota-notifier.desktop` giúp desktop session tự chạy notifier cho user.

### 6.7 `usr/share/polkit-1/actions/`

Polkit policy cho phép GUI gọi update qua `pkexec` theo policy hệ thống.

### 6.8 `etc/logrotate.d/`

Cấu hình rotate log cho `/var/log/caramos-ota/*.log`.

### 6.9 `debian/`

Debian packaging metadata:

| File | Vai trò |
|---|---|
| `control` | Dependency, metadata package. |
| `install` | Map source file vào path trong `.deb`. |
| `postinst` | Enable/start timer sau install. |
| `rules` | Debhelper build entry. |
| `changelog` | Version Debian/PPA. |
| `source/format` | Source package format. |

---

## 7. File runtime trên hệ thống người dùng

```text
/var/lib/caramos-ota/
├── state.json
└── lock

/var/log/caramos-ota/
└── YYYY-MM-DD.log
```

### 7.1 `state.json`

State dùng để CLI, systemd check và notifier giao tiếp với nhau.

Ví dụ:

```json
{
  "schema": 1,
  "last_check": "2026-05-31T22:00:00+07:00",
  "last_successful_upgrade": null,
  "installed_release": null,
  "available_update": {
    "detected_at": "2026-05-31T22:00:00+07:00",
    "release": "1.0.2",
    "current_version": "1.0.1",
    "release_notes_vi": [
      "Cập nhật cấu hình hệ thống CaramOS",
      "Cải thiện trải nghiệm desktop"
    ],
    "release_notes_en": [],
    "packages": [
      {
        "name": "caramos-ota",
        "current_version": "1.0.1-0caramos1",
        "available_version": "1.0.2-0caramos1",
        "description": "CaramOS OTA updater"
      }
    ]
  },
  "transactions": []
}
```

Quy tắc:

- `schema` hiện tại là `1`.
- Ghi state bằng file tạm rồi `os.replace` để tránh JSON hỏng giữa chừng.
- Permission state là `0644` để notifier chạy dưới user desktop đọc được.
- Chỉ root/CLI ghi state.
- Notifier chỉ đọc state.

### 7.2 Lock file

`/var/lib/caramos-ota/lock` được giữ bằng `fcntl.flock` để tránh hai OTA operation chạy song song.

Nếu lock đang bị giữ, CLI thoát với exit code `7`.

### 7.3 Log

Log nằm trong `/var/log/caramos-ota/YYYY-MM-DD.log`.

Log cần đủ để support biết:

- Action nào được chạy.
- Repo/keyring có hợp lệ không.
- APT command nào được gọi.
- Transaction nào thành công/thất bại.
- Lỗi cụ thể ở bước nào.

---

## 8. Manifest OTA

Manifest được cài vào:

```text
/usr/share/caramos-ota/manifest.json
```

Schema v1 tối thiểu:

```json
{
  "schema": 1,
  "release": "1.0.2",
  "codename": "noble",
  "release_notes_vi": [
    "Cập nhật thành phần hệ thống CaramOS"
  ],
  "release_notes_en": [
    "Update CaramOS system components"
  ],
  "components": [
    {
      "package": "caramos-ota",
      "min_version": "1.0.2-0caramos1",
      "required": true,
      "description": "CaramOS OTA updater"
    }
  ]
}
```

### 8.1 Ý nghĩa field

| Field | Bắt buộc | Ý nghĩa |
|---|---:|---|
| `schema` | Có | Version schema. Hiện tại phải là `1`. |
| `release` | Có | Release OTA/CaramOS mà manifest đại diện. |
| `codename` | Có | Ubuntu codename. v1 chỉ `noble`. |
| `release_notes_vi` | Không | Ghi chú update tiếng Việt cho GUI. |
| `release_notes_en` | Không | Ghi chú update tiếng Anh fallback/CLI. |
| `components` | Có | Danh sách package CaramOS cần đạt version tối thiểu. |
| `components[].package` | Có | Tên package Debian. |
| `components[].min_version` | Có | Version tối thiểu cần có. |
| `components[].required` | Không | Nếu `true`, thiếu package/candidate là lỗi. |
| `components[].description` | Không | Mô tả ngắn cho UI/log. |

### 8.2 Quy tắc sửa manifest

- Package name phải match allow-list `^[a-z0-9][a-z0-9+.-]+$`.
- Không đưa shell syntax, URL script, hoặc command vào manifest.
- Không dùng manifest để chạy code tùy ý.
- `min_version` phải là version có thật trong PPA hoặc sẽ có khi release.
- Nếu thêm component `required: true`, phải chắc chắn package có candidate trong PPA.
- Release notes nên ngắn, rõ, tiếng Việt thân thiện.

### 8.3 Vì sao manifest ship trong package

v1 ship manifest trong `caramos-ota` để đơn giản và an toàn:

- Không cần network fetch ngoài APT.
- Manifest đi qua cùng chuỗi tin cậy với `.deb` từ PPA.
- Dễ debug: contributor thấy manifest ngay trong source.
- Không cần thêm signing/verification riêng cho remote metadata.

Nhược điểm: để thay đổi manifest phải release package mới. Đây là chấp nhận được trong v1.

---

## 9. Repository, keyring và nhận diện CaramOS

### 9.1 `/etc/caramos-release`

CLI chỉ chạy nếu file này tồn tại và hợp lệ.

Ví dụ:

```text
NAME="CaramOS"
VERSION="1.0"
UBUNTU_CODENAME="noble"
CHANNEL="stable"
```

Điều kiện v1:

- `NAME=CaramOS`
- `UBUNTU_CODENAME=noble`
- `CHANNEL=stable`

Nếu sai, OTA dừng. Không có `--force` trong v1.

### 9.2 PPA

PPA chính thức:

```text
ppa:vietnamlinuxfamily/caram-os
```

Source expected:

```text
deb [signed-by=/usr/share/keyrings/caramos-archive-keyring.gpg] https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu/ noble main
```

### 9.3 Keyring

Keyring expected:

```text
/usr/share/keyrings/caramos-archive-keyring.gpg
```

OTA không tự thêm PPA/keyring. ISO phải cài sẵn để tránh hành vi tự sửa trust root của hệ thống.

---

## 10. Command reference

### 10.1 `sudo caramos-ota`

Default action: check + upgrade nếu có update.

### 10.2 `sudo caramos-ota --check`

Check update, ghi state, không cài package.

### 10.3 `sudo caramos-ota --upgrade`

Rõ nghĩa hơn default. Check rồi cài update nếu có.

### 10.4 `sudo caramos-ota --yes`

Không hỏi confirm. Dùng cho GUI qua `pkexec`.

### 10.5 `sudo caramos-ota --dry-run`

Hiển thị package sẽ update, không cài.

### 10.6 `sudo caramos-ota --status`

In trạng thái OTA hiện tại: last check, last upgrade, installed release, transaction mới nhất.

### 10.7 `sudo caramos-ota --repair`

Chạy repair APT/dpkg best-effort.

### 10.8 `sudo caramos-ota --rollback`

Rollback transaction success mới nhất best-effort.

### 10.9 `caramos-ota --version`

In version tool.

---

## 11. Exit codes

| Code | Ý nghĩa |
|---:|---|
| `0` | Thành công hoặc không có update. |
| `1` | Lỗi chung. |
| `2` | Cần root. |
| `3` | Không phải CaramOS hoặc CaramOS không được hỗ trợ. |
| `4` | Lỗi repo/keyring. |
| `5` | Lỗi APT/dpkg. |
| `6` | Lỗi manifest/state. |
| `7` | Operation khác đang chạy. |
| `8` | User hủy. |

Giữ exit code ổn định để systemd, GUI và script support có thể xử lý.

---

## 12. Bảo mật và nguyên tắc fail-closed

### 12.1 Không dùng shell string

Mọi lệnh hệ thống phải gọi bằng list argument:

```python
subprocess.run(["apt-get", "install", "--yes", "--", *packages], check=False)
```

Không dùng:

```python
subprocess.run("apt-get install " + package, shell=True)
```

### 12.2 Validate input

Phải validate:

- CLI option bằng `argparse`.
- Manifest schema.
- Package name.
- CaramOS identity.
- Codename/channel.
- PPA/keyring.
- State schema.

### 12.3 Ranh giới quyền

- CLI chạy root khi check/upgrade/status/repair/rollback trong v1.
- Notifier chạy user desktop.
- Notifier chỉ nâng quyền qua `pkexec` khi user bấm update.
- Notifier không được ghi state root-owned.

### 12.4 Không remote code execution

Không thiết kế manifest/hook để tải script và chạy. Mọi update phải đi qua package Debian trong PPA.

### 12.5 Log không chứa bí mật

Hiện OTA không xử lý token/password. Nếu sau này thêm endpoint hoặc auth, không log secret.

---

## 13. Build và test cho contributor

### 13.1 Static check

```bash
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py

desktop-file-validate etc/xdg/autostart/caramos-ota-notifier.desktop
```

### 13.2 Build `.deb`

```bash
dpkg-buildpackage -us -uc -b
```

Output nằm ở thư mục cha:

```text
../caramos-ota_VERSION_all.deb
../caramos-ota_VERSION_amd64.buildinfo
../caramos-ota_VERSION_amd64.changes
```

### 13.3 Cài local để test

```bash
sudo apt install ./../caramos-ota_1.0.2-0caramos1_all.deb
```

hoặc:

```bash
sudo dpkg -i ../caramos-ota_1.0.2-0caramos1_all.deb
sudo apt-get --fix-broken install
```

### 13.4 Test CLI cơ bản

```bash
caramos-ota --version
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
```

### 13.5 Test notifier

Trong desktop session:

```bash
caramos-ota-notifier
```

Nếu không có update trong state, notifier thoát im lặng. Để test UI, có thể tạm tạo state trên máy test/VM, nhưng không commit state đó.

### 13.6 Test systemd timer

```bash
systemctl status caramos-ota-check.timer --no-pager
sudo systemctl start caramos-ota-check.service
journalctl -u caramos-ota-check.service --no-pager -n 100
```

### 13.7 Test package contents

Sau build:

```bash
dpkg-deb -c ../caramos-ota_1.0.2-0caramos1_all.deb
```

Cần thấy:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/share/caramos-ota/manifest.json
/lib/systemd/system/caramos-ota-check.service
/lib/systemd/system/caramos-ota-check.timer
/etc/xdg/autostart/caramos-ota-notifier.desktop
```

---

## 14. Quy trình cập nhật/release OTA

### 14.1 Khi chỉ sửa code OTA

1. Sửa code trong `caramos_ota` hoặc `caramos_ota_notifier`.
2. Update `debian/changelog` tăng version.
3. Chạy static check.
4. Build `.deb`.
5. Cài local trong VM CaramOS.
6. Test command liên quan.
7. Upload PPA.

### 14.2 Khi thêm package CaramOS mới vào OTA

1. Đảm bảo package mới đã build và có trong PPA.
2. Thêm component vào `usr/share/caramos-ota/manifest.json`.
3. Set `required` đúng:
   - `true` nếu thiếu package là lỗi release;
   - `false` nếu package optional.
4. Update release notes.
5. Build `caramos-ota` mới.
6. Test trên VM đang ở version cũ.
7. Chạy `sudo caramos-ota --check` để xem detect.
8. Chạy `sudo caramos-ota --dry-run`.
9. Chạy `sudo caramos-ota --upgrade`.
10. Kiểm tra `--status` và state.

### 14.3 Khi đổi UI notifier

1. Sửa `caramos_ota_notifier/ui.py`.
2. Giữ màu đồng bộ với website CaramOS/VNLF:
   - Green: `#1f4f32`
   - Secondary green: `#2f7048`
   - Cream: `#f7f3e9`
   - Card: `#fffdf7`
3. UI mặc định phải gọn trong màn hình, không quá dài.
4. Nội dung chi tiết dài nên dùng scroll/tooltip, không đẩy dialog quá cao.
5. Test trong VM desktop.

### 14.4 Khi đổi dependency

1. Sửa `debian/control`.
2. Giải thích lý do trong changelog/PR.
3. Ưu tiên package có sẵn trong Ubuntu 24.04/Mint 22.
4. Không thêm dependency nặng nếu chỉ phục vụ UI phụ.
5. Nếu GUI dependency ngày càng lớn, cân nhắc tách Debian package riêng cho notifier.

---

## 15. Policy cho contributor

### 15.1 Không phá update path

Trước khi merge, tự hỏi:

- Máy đang ở bản cũ có update lên bản mới được không?
- Nếu manifest sai, CLI có dừng an toàn không?
- Nếu PPA thiếu package, thông báo có rõ không?
- Nếu update fail giữa chừng, user có repair path không?
- Nếu GUI fail, CLI vẫn dùng được không?

### 15.2 Backward compatibility state

Nếu đổi state schema:

1. Tăng schema.
2. Viết migration hoặc reset có backup.
3. Không crash notifier khi gặp state cũ.
4. Document thay đổi trong README.

### 15.3 Không làm GUI thành nguồn quyết định

GUI chỉ hiển thị và gọi CLI. Không copy logic APT/detect update sang GUI.

### 15.4 Không chạy nền nguy hiểm

Systemd timer không được cài package tự động trong v1.

### 15.5 Không làm silent failure khi user cần biết

- Notifier được phép thoát im lặng khi không có GUI hoặc không có update.
- CLI không được nuốt lỗi quan trọng.
- Lỗi repo/keyring/manifest/APT phải có message rõ.

---

## 16. Troubleshooting

### 16.1 `Unable to locate package caramos-ota`

Nguyên nhân thường gặp:

- Package chưa upload PPA.
- PPA source thiếu/sai codename.
- APT cache chưa update.

Kiểm tra:

```bash
apt-cache policy caramos-ota
apt-cache policy caram-os-demo
```

### 16.2 Notifier không hiện

Kiểm tra:

```bash
cat /var/lib/caramos-ota/state.json
```

Điều kiện để notifier hiện:

- Có desktop session (`DISPLAY` hoặc `WAYLAND_DISPLAY`).
- State schema là `1`.
- `available_update` là object.
- `available_update.packages` là list không rỗng.

### 16.3 Notifier crash vì package entry sai type

Notifier phải normalize package entry. Nếu state cũ có package là string, GUI vẫn không được crash.

### 16.4 `pkexec` không chạy

Kiểm tra:

```bash
which pkexec
ls /usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy
```

### 16.5 APT/dpkg bị broken

Chạy:

```bash
sudo caramos-ota --repair
```

### 16.6 Có process OTA khác đang chạy

CLI thoát exit code `7`. Kiểm tra timer/service hoặc process đang chạy.

---

## 17. Những gì không làm trong v1

- Không tự thêm PPA/keyring.
- Không tự động cài update từ timer.
- Không remote fetch manifest ngoài APT.
- Không telemetry.
- Không full rollback guarantee.
- Không support channel khác ngoài `stable`.
- Không support codename khác ngoài `noble`.
- Không có `--force` bypass identity/repo checks.

---

## 18. Roadmap sau v1

Các hướng có thể làm sau:

- Tách Debian package riêng `caramos-ota-notifier` để CLI-only install nhẹ hơn.
- Hỗ trợ non-root `--status` và có thể non-root `--check` read-only nếu thiết kế lại state/cache.
- Hỗ trợ channel `testing`/`dev` có kiểm soát.
- Thêm migration state schema.
- Thêm integration test bằng container/VM.
- Thêm screenshot test hoặc manual UI checklist cho notifier.
- Thêm signed remote metadata nếu sau này cần manifest ngoài package.

---

## 19. Maintainer checklist trước khi upload PPA

- [ ] `debian/changelog` đã tăng version đúng.
- [ ] `python3 -m py_compile` pass cho cả CLI và notifier package.
- [ ] `desktop-file-validate` pass.
- [ ] `dpkg-buildpackage -us -uc -b` pass.
- [ ] `.deb` chứa đúng hai Python package namespace.
- [ ] `sudo apt install ./caramos-ota_*.deb` pass trong VM.
- [ ] `caramos-ota --version` đúng version.
- [ ] `sudo caramos-ota --check` không crash.
- [ ] `sudo caramos-ota --dry-run` hiển thị đúng.
- [ ] `sudo caramos-ota --status` đọc state đúng.
- [ ] `caramos-ota-notifier` không crash khi không có update.
- [ ] GUI hiển thị gọn, đúng màu CaramOS/VNLF khi có update.
- [ ] Timer enabled sau install.
- [ ] Logrotate file được cài.
- [ ] Không có `.deb`, `.buildinfo`, `.changes`, `__pycache__` bị commit nhầm.

---

## 20. Tóm tắt ranh giới quan trọng

```text
caramos_ota
  = core OTA policy + CLI + APT + manifest + state writer

caramos_ota_notifier
  = desktop UX + state reader + pkexec launcher

APT/PPA
  = nguồn package thật sự

manifest.json
  = danh sách package/version tối thiểu CaramOS muốn đạt

state.json
  = giao tiếp giữa check nền, CLI status và notifier
```

Nếu contributor giữ đúng ranh giới này, package sẽ dễ bảo trì, dễ debug và an toàn hơn cho người dùng CaramOS.
