# CaramOS OTA

> **Package:** `caramos-ota`  
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`  
> **Target OS:** CaramOS 1.x, Linux Mint/Ubuntu base  
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`  
> **Model:** version migration-driven OTA

`caramos-ota` là hệ thống cập nhật OTA riêng của CaramOS. Nó không thay thế APT; nó dùng APT/PPA làm nền, nhưng điều phối update theo **version migration** để nâng CaramOS từ version hiện tại lên version mới một cách có thứ tự.

> [!IMPORTANT]
> Thiết kế mới không dùng manifest tổng. OTA dùng `migrations/migration.json` làm index version, còn metadata của từng lần cập nhật nằm ngay trong `migrations/vX_Y_Z/manifest.json`.

---

## 1. Đọc nhanh cho contributor

Nếu chỉ có vài phút, hãy nắm các điểm này:

1. `/usr/bin/caramos-ota` là orchestrator: check, đọc manifest, ghi state, gọi updater.
2. `/usr/bin/caramos-ota-notifier` là desktop UI: đọc state và gọi `pkexec caramos-ota --upgrade --yes`.
3. `/usr/bin/caramos-ota-update` là migration runner: chạy từng bước `FROM_VERSION -> TO_VERSION`.
4. Migration index chỉ chứa danh sách version; metadata từng update nằm trong `migrations/vX_Y_Z/manifest.json`.
5. Update logic thật nằm trong `caramos_ota_update/migrations/`.
6. Migration vẫn dùng APT để cài package; không tải `.deb` thủ công.
7. Systemd timer chỉ chạy check, không tự cài update.
8. Nếu update fail giữa chừng, state/log phải đủ rõ để chạy tiếp hoặc support.
9. Mọi thao tác sửa hệ thống phải fail closed nếu không xác minh được OS/repo/state.
10. Sau khi sửa Python, chạy `python3 -m py_compile` và test trong VM.

---

## 2. Tại sao dùng migration model

Cách manifest liệt kê từng package có vẻ linh hoạt, nhưng về lâu dài biến OTA thành mini package manager. CaramOS update thường không chỉ là “cài package X”; nó có thể gồm:

- cài/nâng package qua APT;
- xóa package cũ;
- sửa config;
- enable/disable service;
- cập nhật dconf/skel/desktop defaults;
- sửa permission;
- cập nhật `/etc/caramos-release`;
- xử lý workaround riêng cho một version cũ.

Những việc này cần thứ tự rõ ràng. Vì vậy model tốt hơn là:

```text
1.0.2 -> 1.0.3 -> 1.0.4 -> 1.0.8 -> 1.1.12
```

Mỗi bước là một migration nhỏ, review được, test được, chạy lại được ở mức an toàn nhất có thể.

---

## 3. Kiến trúc tổng thể

```text
Migration index
  └── versions = [1.0.2]

caramos-ota --check
  ├── verify CaramOS identity
  ├── verify PPA/keyring
  ├── đọc migration index đóng gói
  ├── chọn target version kế tiếp lớn hơn current_version
  ├── đọc migrations/vX_Y_Z/manifest.json
  └── write /var/lib/caramos-ota/state.json

caramos-ota-notifier
  ├── read state.json
  ├── show GTK dialog nếu có update
  └── pkexec caramos-ota --upgrade --yes

caramos-ota --upgrade
  └── caramos-ota-update --target <target_version>
      ├── run migration chain theo thứ tự
      ├── save state/log
      └── update toàn bộ version metadata
```

---

## 4. Ba command chính

### 4.1 `caramos-ota`

Command chính cho CLI và systemd timer.

Nhiệm vụ:

- check root khi cần;
- tạo log ngày trong `/var/log/caramos-ota/`;
- lấy lock `/var/lib/caramos-ota/lock`;
- đọc `/etc/caramos-release`;
- xác minh PPA/keyring;
- đọc migration index và manifest của target migration;
- ghi `available_update` vào state;
- gọi `caramos-ota-update` khi upgrade.

Các lệnh dự kiến:

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair
```

### 4.2 `caramos-ota-notifier`

Command desktop autostart.

Nhiệm vụ:

- thoát im lặng nếu không có desktop session;
- đọc `/var/lib/caramos-ota/state.json`;
- nếu không có update thì thoát;
- hiện dialog tiếng Việt;
- khi user đồng ý, gọi:

```bash
pkexec /usr/bin/caramos-ota --upgrade --yes
```

Notifier không parse manifest, không chạy APT, không tự quyết định migration.

### 4.3 `caramos-ota-update`

Command chạy migration.

Nhiệm vụ:

- nhận `--target <version>`;
- đọc current version;
- tìm migration path;
- chạy từng migration;
- ghi transaction state;
- hỗ trợ `--dry-run`;
- fail closed nếu thiếu migration;
- cập nhật release file sau khi migration thành công.

Các lệnh dự kiến:

```bash
sudo caramos-ota-update --target 1.0.2 --dry-run
sudo caramos-ota-update --target 1.0.2
sudo caramos-ota-update --from 1.0.3 --to 1.0.4 --dry-run
```

---

## 5. Migration metadata

CaramOS OTA không dùng manifest tổng dạng “latest release”. Metadata được tách
theo mô hình giống database migration:

```text
caramos_ota_update/migrations/
├── migration.json              # index version có migration
├── v1_0_2/
│   ├── manifest.json           # mô tả update lên 1.0.2
│   ├── baseline.py             # migration implementation
│   └── apply_pr_40.sh          # payload nếu cần
└── v1_0_8/
    ├── manifest.json
    └── baseline.py
```

### 5.1 `migration.json`

File này chỉ lưu danh sách target version theo thứ tự phát hành:

```json
{
  "schema": 1,
  "versions": [
    "1.0.2",
    "1.0.3",
    "1.0.4",
    "1.0.8",
    "1.1.12"
  ]
}
```

Quy tắc resolver:

- đọc version hiện tại từ `/etc/caramos-release`;
- tìm version đầu tiên trong `versions[]` lớn hơn version hiện tại;
- nếu máy đang `1.0.4`, target kế tiếp là `1.0.8`;
- sau đó updater chạy migration chain từ version hiện tại tới target.

### 5.2 `vX_Y_Z/manifest.json`

Mỗi thư mục migration tự chứa mô tả UI/CLI của lần update đó:

```json
{
  "schema": 1,
  "version": "1.0.2",
  "from_version": "1.0.1",
  "codename": "noble",
  "channel": "stable",
  "severity": "normal",
  "size": "~53 KB + migration payload",
  "title": "CaramOS có bản cập nhật mới",
  "summary": "Bản cập nhật này sẽ chạy migration CaramOS 1.0.1 lên 1.0.2.",
  "release_notes_vi": [
    "PR #40: cập nhật MintWelcome branding sang CaramOS."
  ],
  "release_notes_en": [
    "PR #40: update MintWelcome branding to CaramOS."
  ]
}
```

### 5.3 Quy tắc metadata

- Không có manifest tổng trong `/usr/share/caramos-ota/`.
- Metadata được đóng gói trong package, không tải JSON điều khiển từ mạng ở runtime.
- `migration.json` không chứa notes, command, package list, URL tải `.deb`.
- `vX_Y_Z/manifest.json` chỉ chứa metadata hiển thị/check.
- Logic thật nằm trong Python/shell migration đã review.
- Không chạy shell/command lấy từ JSON metadata.
- Mỗi version trong `migration.json` phải có thư mục `vX_Y_Z/`.
- Mỗi thư mục target phải có `manifest.json`.
- Nếu schema breaking, phát hành bridge updater trước.

---

## 6. Migration runner

Source đề xuất:

```text
usr/lib/python3/dist-packages/
├── caramos_ota/
│   ├── cli.py
│   ├── manifest.py
│   ├── release.py
│   ├── repo.py
│   └── state.py
├── caramos_ota_notifier/
│   ├── app.py
│   ├── state.py
│   └── ui.py
└── caramos_ota_update/
    ├── __init__.py
    ├── cli.py
    ├── runner.py
    ├── context.py
    ├── apt.py
    ├── state.py
    └── migrations/
        ├── __init__.py
        ├── v1_0_2_to_v1_0_3.py
        └── v1_0_3_to_v1_0_4.py
```

Migration mẫu:

```python
FROM_VERSION = "1.0.3"
TO_VERSION = "1.0.4"
DESCRIPTION = "Install WPS Office and refresh Vietnamese desktop defaults"


def run(context):
    context.apt_update()
    context.apt_install([
        "wps-office",
        "fcitx5",
    ])
    context.ensure_service_enabled("fcitx5")
    context.update_release_file("1.0.4")
```

Runner cần:

- sort migration theo `FROM_VERSION`/`TO_VERSION`;
- tìm path từ current tới target;
- không nhảy version nếu thiếu migration;
- chạy dry-run không sửa hệ thống;
- ghi state trước/sau mỗi migration;
- log từng step;
- dừng ngay khi fail.

---

## 7. State và transaction

State chính:

```text
/var/lib/caramos-ota/state.json
```

Log:

```text
/var/log/caramos-ota/YYYY-MM-DD.log
```

State nên có dạng:

```json
{
  "last_check": "2026-06-06T16:00:00+07:00",
  "installed_version": "1.0.3",
  "available_update": {
    "detected_at": "2026-06-06T16:00:00+07:00",
    "current_version": "1.0.3",
    "release": "1.0.2",
    "migration_manifest_source": "caramos_ota_update/migrations/migration.json",
    "release_notes_vi": [],
    "release_notes_en": []
  },
  "transaction": {
    "status": "failed",
    "target_version": "1.0.4",
    "current_migration": "1.0.3_to_1.0.4",
    "failed_at": "install_wps_office",
    "log": "/var/log/caramos-ota/2026-06-06.log"
  }
}
```

Rule:

- `--check` chỉ ghi state, không install.
- `--upgrade` tạo transaction.
- Sau mỗi migration thành công, cập nhật installed/current version.
- Nếu fail, giữ transaction failed để support.
- Lần sau có thể chạy tiếp từ version cuối đã success.

---

## 8. Systemd và desktop flow

Timer:

```text
caramos-ota-check.timer
  └── caramos-ota-check.service
      └── /usr/bin/caramos-ota --check
```

Không auto-install từ timer.

Desktop:

```text
/ect/xdg/autostart/caramos-ota-notifier.desktop
  └── /usr/bin/caramos-ota-notifier
```

Notifier đọc state và hỏi user trước khi gọi upgrade.

---

## 9. Build và test

### 9.1 Compile Python

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

Nếu `caramos-ota-update` hoặc `caramos_ota_update` chưa tồn tại trong source hiện tại, compile phần đang có trước; khi refactor xong phải đưa updater vào lệnh này.

### 9.2 Validate manifest

```bash
cd packages/caramos-ota
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
```

Test field migration model:

```bash
python3 - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json").read_text(encoding="utf-8"))
assert manifest["schema"] == 1
assert manifest["codename"]
assert manifest["release"]
print("manifest OK")
PY
```

### 9.3 Build Debian package

```bash
cd packages/caramos-ota
dpkg-buildpackage -us -uc -b
```

### 9.4 Inspect package

```bash
cd packages
dpkg-deb -c caramos-ota_1.0.4-0caramos1_all.deb
```

Cần có:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/bin/caramos-ota-update
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/lib/python3/dist-packages/caramos_ota_update/
caramos_ota_update/migrations/migration.json
```

### 9.5 Test trong VM bằng combo ổn định

Có 2 combo chính: một combo chạy hết migration CLI và một combo test UI notifier.

#### Combo A — ship từ máy dev

Chạy trên máy dev:

```bash
cd /home/dungleviet/Documents/CaramOS/packages/caramos-ota
sudo ./tools/ship-ota-to-vm.sh
```

Lệnh này sẽ:

- build `.deb` mới;
- xóa sạch `/tmp/caramos-ota-e2e` trên VM;
- copy `.deb` và test runner mới qua VM;
- purge OTA cũ trên VM;
- cài OTA mới vào VM.

#### Combo B — chạy hết migration CLI trong VM

Chạy trên VM sau khi đã ship:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
```

Lệnh này mặc định reset test version về `1.0.1` rồi chạy full chain hiện tại
tới target mặc định của test runner, ví dụ:

```text
1.0.1 -> 1.0.2 -> 1.0.3
```

Sau khi chạy xong, kiểm tra nhanh:

```bash
cat /etc/caramos-release
zramctl
swapon --show
free -h
```

Kỳ vọng với target `1.0.3`:

- `/etc/caramos-release` có `VERSION="1.0.3"`;
- `zramctl` có `/dev/zram0`;
- `swapon --show` có `/dev/zram0`.

#### Combo C — test UI notifier có update

Dùng combo này khi muốn thấy popup báo **có bản cập nhật**. Không chạy
`install-and-cli` trước, vì command đó update xong rồi thì UI sẽ báo
“CaramOS đã được cập nhật”.

Chạy trên VM sau khi đã ship:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh prepare-check
./vm-run-ota-e2e.sh notifier
```

Flow này sẽ:

- reset VM về test version cũ;
- chạy `caramos-ota --check` để ghi state có update;
- mở `caramos-ota-notifier` trong desktop session.

Nếu sau đó muốn chạy migration thật, dùng lại Combo B:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
```

Kỳ vọng chung:

- Không phải CaramOS thì fail closed.
- `--check` không install.
- `--dry-run` không sửa hệ thống.
- Updater in migration path.
- Migration index lỗi thì fail closed, không đoán target.

---

## 10. Quy trình release OTA mới

Ví dụ release `1.0.4`:

```text
1. Tạo migration v1_0_3_to_v1_0_4.py.
2. Test migration dry-run.
3. Tăng debian/changelog lên 1.0.4-0caramos1.
4. Build .deb.
5. Cài local trong VM ở version 1.0.3.
6. Chạy caramos-ota-update --target 1.0.4 --dry-run.
7. Chạy caramos-ota --upgrade.
8. Kiểm tra /etc/caramos-release đã là 1.0.4.
9. Upload PPA.
10. Sau khi PPA publish, thêm target version vào `migration.json` và tạo `vX_Y_Z/manifest.json`.
11. Test lại từ VM version cũ qua migration index.
```

---

## 11. Rollback và repair

### Repair

```bash
sudo caramos-ota --repair
```

Chạy best-effort:

```bash
dpkg --configure -a
apt-get --fix-broken install --yes
```

### Rollback

Rollback version migration không nên hứa quá nhiều trong v1. Vì migration có thể sửa config, xóa/cài package hoặc thay đổi state. V1 nên ưu tiên:

- transaction log rõ;
- repair APT/dpkg;
- chạy tiếp từ migration cuối thành công;
- support thủ công nếu migration fail.

Nếu cần rollback thật, mỗi migration phải có `rollback(context)` riêng và được test riêng.

---

## 12. Security / safety rules

- Không chạy shell với input từ JSON metadata.
- Không dùng `shell=True` nếu không bắt buộc.
- Không tải `.deb` thủ công từ Internet.
- Không tự thêm PPA.
- Không tự install từ timer.
- Validate channel/codename trước khi chấp nhận metadata migration.
- Migration phải log rõ từng action.
- Migration phải tránh duplicate config khi chạy lại.
- Package install phải đi qua APT.

---

## 13. Contributor checklist

- [ ] Entry point `/usr/bin/*` mỏng, logic nằm trong package Python.
- [ ] Migration mới có `FROM_VERSION`, `TO_VERSION`, `DESCRIPTION`.
- [ ] Migration có dry-run hoặc context hỗ trợ dry-run.
- [ ] Migration idempotent hoặc có guard rõ.
- [ ] Manifest `release` có migration path tương ứng.
- [ ] `python3 -m py_compile` pass.
- [ ] `python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json` pass.
- [ ] `dpkg-buildpackage -us -uc -b` pass.
- [ ] `.deb` chứa đủ CLI, notifier, updater.
- [ ] Test install local trong VM pass.
- [ ] `caramos-ota --check` không tự cài package.
- [ ] `caramos-ota-update --dry-run` không sửa hệ thống.
- [ ] Migration index lỗi thì fail closed, không đoán target.
- [ ] Nếu đổi schema, có bridge rollout.

---

## 14. Tóm tắt

```text
caramos-ota
  = check + state + gọi updater

caramos-ota-notifier
  = desktop UI

caramos-ota-update
  = migration runner

manifest
  = release + release notes

PPA/APT
  = nguồn package thật
```

Thiết kế này đơn giản hơn cho contributor: muốn phát hành OTA mới thì **thêm migration version mới**, tạo `vX_Y_Z/manifest.json`, test migration, upload package, rồi thêm version vào `migration.json`.

---

## 13. Quy trình release OTA đến 1.0.12

Người release chính: **dungleviet**. Contributor chỉ chuẩn bị migration, test và PR; người upload PPA/release cuối cùng là maintainer.

### 13.1 Mục tiêu release

User đang ở CaramOS `1.0.1` chỉ cần cài `caramos-ota` rồi chạy updater:

```bash
sudo apt update
sudo apt install caramos-ota
sudo caramos-ota
```

Nếu muốn popup GUI thay vì CLI:

```bash
sudo apt update
sudo apt install caramos-ota
caramos-ota-notifier
```

`caramos-ota` sẽ tự resolve migration chain theo `migration.json`. Chain trong source hiện là:

```text
1.0.1 → 1.0.2 → 1.0.3 → 1.0.4 → 1.0.5 → 1.0.6 → 1.0.7 → 1.0.8 → 1.0.9 → 1.0.10 → 1.0.11 → 1.0.12
```

### 13.2 Version hiện tại

- Package chuẩn bị release qua PPA: `caramos-ota` version `1.0.12-0caramos1`.
- Latest CaramOS migration target trong source: `1.0.12`.
- Current release target là `1.0.12`.
- Technical codename phải là Linux Mint codename: `wilma`.
- Ubuntu codename giữ là `noble`.

### 13.3 Trước khi upload PPA

```bash
cd packages/caramos-ota
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
```

### 13.4 Test trong VM trước release

Ship package local vào VM test:

```bash
cd packages/caramos-ota
sudo ./tools/ship-ota-to-vm.sh
```

Trong VM, test cạnh migration mới:

```bash
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
```

Kiểm tra sau update:

```bash
cat /etc/caramos-release
grep -E '^(VERSION|VERSION_ID|VERSION_CODENAME|UBUNTU_CODENAME)=' /etc/os-release
grep -E '^DISTRIB_CODENAME=' /etc/lsb-release
grep -E '^CODENAME=' /etc/linuxmint/info
zramctl
swapon --show
sudo add-apt-repository -y ppa:mozillateam/ppa
sudo rm -f /etc/apt/sources.list.d/*mozillateam*
sudo apt update
```

Kỳ vọng:

```text
CaramOS version: 1.0.12
VERSION_CODENAME=wilma
UBUNTU_CODENAME=noble
DISTRIB_CODENAME=wilma
CODENAME=wilma
add-apt-repository không còn báo OS codename 'caram'
```

### 13.5 Upload release

Maintainer `mrd9999` bump `debian/changelog` lên `1.0.12-0caramos1`, build source package và upload PPA:

```bash
cd packages/caramos-ota
debuild -S -sa
dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.12-0caramos1_source.changes
```

Sau khi Launchpad publish xong, test từ máy/VM `1.0.1`:

```bash
sudo apt update
apt-cache policy caramos-ota
sudo apt install caramos-ota
sudo caramos-ota
```

`apt-cache policy` phải thấy candidate là `1.0.12-0caramos1` hoặc version mới hơn.

### 13.6 Build ISO sau release OTA

ISO source version hiện là `CARAMOS_VERSION=1.0.12`; rootfs vẫn bootstrap từ `CARAMOS_MIGRATION_BASE_VERSION=1.0.1` để chạy đủ chain OTA trong lúc build.

```bash
make build
# hoặc release nhỏ hơn:
make release
```

Kỳ vọng ISO output sau cutover:

```text
CaramOS-1.0.12-cinnamon-amd64.iso
```

Bên trong ISO/rootfs sau bootstrap phải là `1.0.12`, không phải `1.0.1` hay version trung gian cũ.
