# 🧾 TRACKER — Refactor CaramOS OTA sang mô hình Migration theo Version

> Tài liệu này là **tracker triển khai chính thức** cho việc refactor package `caramos-ota`.
>
> Mục tiêu là chuyển từ mô hình cũ:
>
> ```text
> migration index liệt kê package + min_version
> caramos-ota tự so từng package rồi apt install
> ```
>
> sang mô hình mới đơn giản và đúng bản chất OTA distro hơn:
>
> ```text
> migration index chỉ báo release
> caramos-ota check version và ghi state
> caramos-ota-update chạy migration theo từng version
> caramos-ota-notifier chỉ làm UI thông báo
> ```
>
> Tracker này phải được cập nhật sau mỗi session làm việc. Mỗi phase có checklist rõ để contributor biết đang làm tới đâu, còn thiếu gì, test gì, và khi nào được coi là xong.

---

## 🔖 1. THÔNG TIN CHUNG

| Trường | Giá trị |
| --- | --- |
| **ID** | CARAMOS-OTA-MIGRATION-001 |
| **Tên task** | Refactor CaramOS OTA sang mô hình migration theo version |
| **Loại** | Refactor / Architecture / Packaging / OTA |
| **Độ ưu tiên** | Critical |
| **Mức ảnh hưởng** | High |
| **Trạng thái tổng thể** | Implemented / Release validation |
| **Người phụ trách** | dungleviet |
| **Người yêu cầu** | CaramOS maintainer |
| **Reviewer** | TBD |
| **Ngày tạo** | 2026-06-06 |
| **Cập nhật lần cuối** | 2026-06-08 |
| **Target release** | CaramOS OTA 1.0.5 |
| **Branch / PR** | TBD |

### 1.1 Trạng thái phase

| Phase | Tên phase | Trạng thái | Ghi chú |
| --- | --- | --- | --- |
| 0 | Chốt kiến trúc và tài liệu | In Progress | README đã đổi, cần review lại toàn bộ. |
| 1 | Tạo updater skeleton | Todo | Bước code đầu tiên. |
| 2 | Implement migration runner | Todo | Core quan trọng nhất. |
| 3 | Implement context helpers | Todo | APT/file/service helpers. |
| 4 | Thêm migration đầu tiên | Todo | Migration nhỏ để test framework. |
| 5 | Refactor manifest model | Todo | Bỏ components/min_version migration release metadata. |
| 6 | Refactor check logic | Todo | Check release. |
| 7 | Refactor upgrade logic | Todo | Gọi caramos-ota-update. |
| 8 | Refactor notifier | Todo | Hiển thị version update. |
| 9 | Update packaging | Todo | debian/install/control/changelog. |
| 10 | Verification | Todo | Compile, build, VM test. |
| 11 | Rollout | Todo | PPA + migration index. |

---

## 🧠 2. BỐI CẢNH VÀ VẤN ĐỀ

### 2.1 Hiện trạng

Package `caramos-ota` hiện đang được thiết kế theo hướng manifest-driven package update:

```text
manifest.json
└── release metadata
    ├── package
    ├── min_version
    ├── required
    └── description
```

Luồng cũ:

```text
caramos-ota --check
  ├── tải manifest
  ├── đọc release metadata
  ├── dpkg-query package đã cài chưa
  ├── apt-cache policy package candidate version
  ├── so installed_version với min_version
  └── tạo danh sách package cần update

caramos-ota --upgrade
  └── apt-get install package-a package-b package-c
```

Cách này hoạt động được nếu OTA chỉ đảm bảo vài package đạt version tối thiểu. Tuy nhiên nó không phù hợp nếu CaramOS OTA cần nâng cả distro theo từng release.

---

### 2.2 Vì sao model cũ không ổn

OTA của một distro không chỉ là cài package. Một bản cập nhật CaramOS có thể cần:

- cài package mới;
- nâng package cũ;
- xóa package không còn dùng;
- sửa file cấu hình;
- migrate dữ liệu hoặc state;
- cập nhật `/etc/caramos-release`;
- enable/disable systemd service;
- sửa dconf/skel/default desktop;
- xử lý edge case riêng cho một version cũ;
- update chính package `caramos-ota`;
- dừng và resume nếu lỗi giữa chừng.

Nếu dùng manifest migration release metadata, các vấn đề xuất hiện:

| Vấn đề | Hậu quả |
| --- | --- |
| Không có thứ tự update rõ | Package/config có thể chạy sai thứ tự. |
| Manifest ngày càng phức tạp | Dễ biến thành script/config engine nguy hiểm. |
| Khó debug | Không biết lỗi thuộc release step nào. |
| Khó support máy quá cũ | Máy ở 1.0.1 lên 1.0.2 cần nhiều bước trung gian. |
| Khó update chính OTA | Nếu schema đổi, client cũ có thể không hiểu manifest mới. |
| Dễ biến OTA thành mini package manager | Trùng trách nhiệm với APT. |

---

### 2.3 Hướng mới

Chuyển sang mô hình migration theo version:

```text
1.0.1 -> 1.0.2 -> 1.0.3 -> 1.0.4 -> 1.0.5
```

Trong đó:

- migration index chỉ báo version mới nhất;
- `caramos-ota` chỉ check version và gọi updater;
- `caramos-ota-update` chạy migration theo thứ tự;
- migration là code được review, đóng gói và phát hành qua PPA;
- APT vẫn là nguồn cài package thật.

---

## 🎯 3. MỤC TIÊU

### 3.1 Mục tiêu chính

Sau khi hoàn tất refactor, CaramOS OTA phải có 3 command rõ ràng:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/bin/caramos-ota-update
```

Trách nhiệm:

| Command | Trách nhiệm |
| --- | --- |
| `caramos-ota` | Check version, đọc manifest, ghi state, hỏi xác nhận, gọi updater. |
| `caramos-ota-notifier` | Đọc state, hiển thị popup, gọi `pkexec caramos-ota --upgrade --yes`. |
| `caramos-ota-update` | Chạy migration theo từng version. |

---

### 3.2 Mục tiêu kỹ thuật

- Migration metadata không còn là package action list.
- Manifest chỉ chứa metadata release.
- Migration runner tìm được đường đi từ current version tới target version.
- Dry-run hoạt động và không sửa hệ thống.
- State/log đủ để debug update fail.
- Nếu migration index lỗi, fail closed.
- Nếu thiếu migration path, ưu tiên cập nhật chính `caramos-ota` từ PPA để lấy migration mới rồi chạy tiếp; chỉ fail nếu sau khi cập nhật OTA vẫn thiếu path.
- Timer không bao giờ tự install update.
- Notifier không bao giờ tự chạy APT.

---

### 3.3 Ngoài phạm vi v1

Những thứ này chưa bắt buộc trong refactor đầu tiên:

- Rollback tự động đầy đủ cho mọi migration.
- Ký manifest bằng GPG/minisign.
- Multi-channel phức tạp ngoài `stable`/`beta` cơ bản.
- GUI progress chi tiết từng migration step.
- Telemetry hoặc report lỗi tự động.
- Local package repository riêng ngoài PPA.

---

## 🧩 4. THIẾT KẾ MỚI

### 4.1 Manifest schema mới

Migration metadata dự kiến:

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

Không còn:

```json
{
  "release_notes_vi": [
    {
      "package": "...",
      "min_version": "..."
    }
  ]
}
```

---

### 4.2 Manifest URL

Runtime URL:

```text
caramos_ota_update/migrations/migration.json
```

Ví dụ:

```text
caramos_ota_update/migrations/migration.json
https://caramos.vietnamlinuxfamily.net/ota/beta/noble/manifest.json
https://caramos.vietnamlinuxfamily.net/ota/stable/oracular/manifest.json
```

Deploy layout:

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

---

### 4.3 State schema mới

State file:

```text
/var/lib/caramos-ota/state.json
```

Mẫu state:

```json
{
  "last_check": "2026-06-06T16:00:00+07:00",
  "installed_version": "1.0.3",
  "available_update": {
    "detected_at": "2026-06-06T16:00:00+07:00",
    "current_version": "1.0.3",
    "release": "1.0.2",
    "manifest_source": "caramos_ota_update/migrations/migration.json",
    "release_notes_vi": [
      "Cập nhật WPS Office."
    ],
    "release_notes_en": [
      "Update WPS Office."
    ]
  },
  "transaction": {
    "status": "failed",
    "target_version": "1.0.2",
    "current_migration": "1.0.3_to_1.0.2",
    "failed_at": "install_wps_office",
    "log": "/var/log/caramos-ota/2026-06-06.log"
  }
}
```

---

### 4.4 Cấu trúc source mới

```text
packages/caramos-ota/
├── usr/
│   ├── bin/
│   │   ├── caramos-ota
│   │   ├── caramos-ota-notifier
│   │   └── caramos-ota-update
│   ├── lib/python3/dist-packages/
│   │   ├── caramos_ota/
│   │   │   ├── __init__.py
│   │   │   ├── cli.py
│   │   │   ├── constants.py
│   │   │   ├── manifest.py
│   │   │   ├── models.py
│   │   │   ├── release.py
│   │   │   ├── repo.py
│   │   │   └── state.py
│   │   ├── caramos_ota_notifier/
│   │   │   ├── __init__.py
│   │   │   ├── app.py
│   │   │   ├── state.py
│   │   │   └── ui.py
│   │   └── caramos_ota_update/
│   │       ├── __init__.py
│   │       ├── cli.py
│   │       ├── runner.py
│   │       ├── context.py
│   │       ├── apt.py
│   │       ├── state.py
│   │       └── migrations/
│   │           ├── __init__.py
│   │           ├── v1_0_2/
│   │           │   ├── __init__.py
│   │           │   └── baseline.py                    # PR #40
│   │           ├── v1_0_3/
│   │           │   ├── __init__.py
│   │           │   └── fix_dockerfile_apt_chain.py    # PR #41
│   │           ├── v1_0_4/
│   │           │   ├── __init__.py
│   │           │   └── enable_zram_default.py         # PR #42
│   │           └── v1_0_5/
│   │               ├── __init__.py
│   │               └── mintreport_banner_branding.py  # PR #43
│   └── share/caramos-ota/
│       └── manifest.json
└── debian/
    ├── control
    ├── install
    ├── changelog
    └── rules
```

---

## 🧱 5. MIGRATION CONTRACT

### 5.1 Mỗi migration file phải có

```python
FROM_VERSION = "1.0.3"
TO_VERSION = "1.0.2"
DESCRIPTION = "Install WPS Office and refresh Vietnamese input defaults"


def run(context):
    context.apt_update()
    context.apt_install(["wps-office"])
    context.update_release_file("1.0.2")
```

### 5.2 Quy tắc migration

- Chỉ nâng từ một version sang version kế tiếp.
- Không nhảy nhiều version trong một file.
- Phải log rõ từng bước quan trọng.
- Phải idempotent càng nhiều càng tốt.
- Không append config mù quáng gây duplicate.
- Không tải `.deb` thủ công từ Internet.
- Không chạy shell script remote.
- Không dùng `shell=True` với input động.
- Nếu fail, raise exception để runner dừng ngay.
- Sau khi thành công, update release file hoặc để runner update theo contract đã chốt.

### 5.3 Ví dụ migration tốt

```python
def run(context):
    context.apt_install(["fcitx5", "fcitx5-unikey"])
    context.append_line_once(
        "/etc/environment",
        "GTK_IM_MODULE=fcitx",
    )
    context.ensure_service_enabled("fcitx5")
```

### 5.4 Ví dụ migration không tốt

```python
def run(context):
    # Sai: chạy lại sẽ duplicate line.
    context.run_command(["sh", "-c", "echo GTK_IM_MODULE=fcitx >> /etc/environment"])
```

---

## 🛠️ 6. KẾ HOẠCH TRIỂN KHAI CHI TIẾT

## Phase 0 — Chốt tài liệu và contract

### Mục tiêu

Đảm bảo mọi tài liệu đều mô tả cùng một kiến trúc mới trước khi code.

### Công việc

- [x] Cập nhật [packages/README.md](file:///home/dungleviet/Documents/CaramOS/packages/README.md).
- [x] Cập nhật [caramos-ota/README.md](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/README.md).
- [x] Cập nhật [caramos-ota/README_EN.md](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/README_EN.md).
- [ ] Review lại README để loại bỏ mô tả model cũ như nguồn chính.
- [ ] Chốt manifest schema mới.
- [ ] Chốt state schema mới.
- [ ] Chốt command interface.
- [ ] Chốt migration contract.

### Acceptance criteria

- [ ] Contributor đọc README hiểu rõ 3 command chính.
- [ ] Manifest mẫu không còn `release metadata`.
- [ ] Tracker này có đủ checklist để bắt đầu implement.

---

## Phase 1 — Tạo `caramos-ota-update` skeleton

### Mục tiêu

Thêm updater mới nhưng chưa đụng sâu vào logic OTA cũ.

### Files cần tạo

- [x] `packages/caramos-ota/usr/bin/caramos-ota-update`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/__init__.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/cli.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/runner.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/context.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/apt.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/state.py`
- [x] `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/__init__.py`

### Files cần sửa

- [x] `packages/caramos-ota/debian/install`
- [ ] `packages/caramos-ota/debian/changelog`

### CLI tối thiểu

```bash
caramos-ota-update --help
caramos-ota-update --target 1.0.2 --dry-run
caramos-ota-update --from 1.0.1 --to 1.0.2 --dry-run
```

### Acceptance criteria

- [x] Entry point chạy được.
- [x] `--help` rõ ràng.
- [x] `--dry-run` chưa sửa hệ thống.
- [x] Compile Python pass.

---

## Phase 2 — Implement migration runner core

### Mục tiêu

Runner biết load migrations, tìm path, và chạy/dry-run theo thứ tự.

### Công việc

- [x] Load tất cả module trong `migrations/`.
- [x] Validate mỗi migration có `FROM_VERSION`.
- [x] Validate mỗi migration có `TO_VERSION`.
- [x] Validate mỗi migration có `DESCRIPTION`.
- [x] Validate mỗi migration có `run(context)`.
- [x] Detect duplicate `FROM_VERSION`.
- [x] Detect duplicate edge `FROM_VERSION -> TO_VERSION`.
- [x] Tìm path từ current tới target.
- [x] Fail nếu không có path.
- [x] In path khi dry-run.
- [x] Chạy migration theo thứ tự khi không dry-run.
- [ ] Ghi transaction status.

### Acceptance criteria

- [x] Có migration path thì runner in đúng path.
- [ ] Thiếu migration thì thử self-update `caramos-ota` trước, sau đó resolve path lại.
- [ ] Dry-run không gọi APT thật.
- [ ] Nếu migration fail, runner dừng ngay.

---

## Phase 3 — Implement context helpers

### Mục tiêu

Cung cấp API an toàn cho migration, tránh mỗi migration tự viết subprocess/file handling.

### Helpers cần có

- [x] `context.log(message)`
- [x] `context.run_command(args, allow_fail=False)`
- [x] `context.apt_update()`
- [x] `context.apt_install(packages)`
- [x] `context.apt_remove(packages)`
- [x] `context.ensure_service_enabled(service)`
- [x] `context.ensure_service_disabled(service)`
- [x] `context.write_file_if_changed(path, content)`
- [x] `context.append_line_once(path, line)`
- [x] `context.file_contains(path, text)`
- [x] `context.update_release_file(version)`
- [ ] `context.backup_file(path)` nếu sửa config nhạy cảm.

### Safety requirements

- [x] Không dùng `shell=True`.
- [x] Validate package name trước khi apt install/remove.
- [x] Validate service name trước khi systemctl.
- [x] Dry-run chỉ log action, không sửa hệ thống.
- [x] File write phải dùng encoding rõ ràng.
- [ ] Backup trước khi sửa file config quan trọng.

### Acceptance criteria

- [x] Dry-run log đúng action.
- [ ] Action thật chạy được trong VM.
- [ ] Helper chống duplicate line hoạt động.

---

## Phase 4 — Tạo migration đầu tiên

### Mục tiêu

Có migration thật nhưng nhỏ để test toàn bộ framework.

### Migration đề xuất

Mỗi PR đã merge sẽ là một version OTA riêng:

| Version | PR | Migration file |
| --- | --- | --- |
| `1.0.2` | `#40` rebuild mintwelcome `.mo` translation files for CaramOS branding | `migrations/v1_0_2/baseline.py` |
| `1.0.3` | `#41` Fix Dockerfile apt-get chain | `migrations/v1_0_3/fix_dockerfile_apt_chain.py` |
| `1.0.2` | `#42` Thêm ZRAM mặc định 50% RAM | `migrations/v1_0_4/enable_zram_default.py` |
| `1.0.2` | `#43` Change mintreport's banner logo and background color | `migrations/v1_0_5/mintreport_banner_branding.py` |

Tên folder thể hiện version đích, còn tên file chỉ cần mô tả action migration. Version edge thật vẫn được khai báo trong constants `FROM_VERSION` và `TO_VERSION` bên trong file.

Nội dung nên nhẹ:

- update release file;
- cài một package CaramOS đơn giản nếu có;
- hoặc chỉ chạy no-op + update release file trong giai đoạn framework test.

### Công việc

- [x] Tạo migration file.
- [x] Khai báo `FROM_VERSION`.
- [x] Khai báo `TO_VERSION`.
- [x] Khai báo `DESCRIPTION`.
- [x] Implement `run(context)`.
- [x] Test dry-run.
- [ ] Test thật trong VM snapshot.

### Acceptance criteria

- [x] `caramos-ota-update --target 1.0.2 --dry-run` thấy đủ chain `1.0.1 -> 1.0.2`.
- [ ] Chạy thật cập nhật version đúng.
- [ ] State/log ghi migration success.

---

## Phase 5 — Refactor manifest model

### Mục tiêu

Bỏ `release metadata` khỏi manifest model chính.

### Files dự kiến

- [models.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota/models.py)
- [manifest.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota/manifest.py)
- [manifest.json](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json)

### Công việc

- [ ] Sửa `Manifest` dataclass.
- [ ] Thêm `channel`.
- [ ] Thêm `release`.
- [ ] Giữ `codename`.
- [ ] Giữ `source`.
- [ ] Giữ `min_client_version`.
- [ ] Giữ release notes.
- [ ] Validate schema.
- [ ] Validate codename khớp release info.
- [ ] Validate channel khớp release info.
- [ ] Validate release không rỗng.
- [ ] Update migration-local manifest JSON.
- [ ] Update test offline manifest.

### Acceptance criteria

- [ ] Migration index mới parse được.
- [ ] Migration metadata local mới parse được.
- [ ] Online fail fail closed.
- [ ] Không còn cần `release metadata` cho check logic mới.

---

## Phase 6 — Refactor `caramos-ota --check`

### Mục tiêu

Check OTA dựa trên version, không dựa trên migration release metadata.

### Logic mới

```text
detect CaramOS
verify repo/keyring
read migration metadata
current = /etc/caramos-release VERSION
latest = manifest.release
if current < latest:
    state.available_update = {...}
else:
    state.available_update = null
```

### Công việc

- [ ] Tách hoặc đổi `detect_updates` cũ.
- [ ] Dùng version compare đáng tin cậy.
- [ ] Ghi `installed_version`.
- [ ] Ghi `available_update.current_version`.
- [ ] Ghi `available_update.release`.
- [ ] Ghi `manifest_source`.
- [ ] Ghi release notes.
- [ ] Không chạy install.
- [ ] Không tạo migration release metadata.

### Acceptance criteria

- [ ] `sudo caramos-ota --check` chỉ ghi state.
- [ ] State có latest/current version.
- [ ] Không còn báo update theo migration release metadata.

---

## Phase 7 — Refactor `caramos-ota --upgrade`

### Mục tiêu

CLI chính gọi updater thay vì tự cài package.

### Logic mới

```text
caramos-ota --upgrade
  ├── check/fetch latest target
  ├── hỏi xác nhận nếu thiếu --yes
  └── subprocess.run(["/usr/bin/caramos-ota-update", "--target", latest])
```

### Công việc

- [ ] Lấy target từ state hoặc manifest.
- [ ] Confirm user.
- [ ] Gọi updater với `shell=False`.
- [ ] Với dry-run, thêm `--dry-run`.
- [ ] Propagate exit code.
- [ ] Log command gọi updater.
- [ ] Gợi ý repair nếu updater fail.

### Acceptance criteria

- [ ] `caramos-ota --upgrade --yes` gọi updater.
- [ ] `caramos-ota --dry-run` không sửa hệ thống.
- [ ] Updater fail thì CLI chính báo rõ.

---

## Phase 8 — Refactor notifier

### Mục tiêu

Notifier hiển thị version update, không hiển thị migration release metadata.

### Công việc

- [ ] Update state parser.
- [ ] Hiển thị `current_version -> release`.
- [ ] Hiển thị release notes tiếng Việt.
- [ ] Bỏ phụ thuộc `packages[]`.
- [ ] Giữ `pkexec /usr/bin/caramos-ota --upgrade --yes`.
- [ ] Test không có display thì thoát im lặng.
- [ ] Test có update thì hiện dialog.

### Acceptance criteria

- [ ] Popup hiển thị version target đúng.
- [ ] Release notes hiển thị đúng.
- [ ] Button update gọi CLI chính.

---

## Phase 9 — Packaging

### Công việc

- [ ] Update `debian/install`.
- [ ] Update `debian/control` nếu cần dependency mới.
- [ ] Update `debian/changelog`.
- [ ] Đảm bảo executable bit cho `/usr/bin/caramos-ota-update`.
- [ ] Đảm bảo `.deb` chứa updater package.
- [ ] Đảm bảo postinst/systemd không bị ảnh hưởng.

### Kiểm tra `.deb`

```bash
dpkg-deb -c caramos-ota_*.deb
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
```

---

## Phase 10 — Verification

### Compile

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

### Manifest

```bash
python3 -m json.tool usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json >/dev/null
```

### Build

```bash
dpkg-buildpackage -us -uc -b
```

### Install VM

```bash
sudo apt install ./caramos-ota_*.deb
```

### CLI smoke test

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota-update --target 1.0.2 --dry-run
```

### Migration real test

```text
1. Snapshot VM.
2. Đặt VM ở current version cũ.
3. Cài package mới.
4. Chạy dry-run.
5. Chạy upgrade thật.
6. Kiểm tra /etc/caramos-release.
7. Kiểm tra state/log.
8. Reboot nếu migration liên quan service/session.
```

---

## 🔐 7. SECURITY / SAFETY CHECKLIST

- [ ] Manifest không chứa command.
- [ ] Manifest không chứa script.
- [ ] Manifest không chứa URL `.deb`.
- [ ] Không execute dữ liệu từ manifest.
- [ ] Không dùng `shell=True` với input động.
- [ ] Validate package name trước khi APT.
- [ ] Validate service name trước khi systemctl.
- [ ] Validate channel/codename trước khi build URL.
- [ ] Network fetch có timeout.
- [ ] Network fetch có max size.
- [ ] Online fail fail closed.
- [ ] Timer không auto-install.
- [ ] Notifier không chạy APT trực tiếp.
- [ ] Migration log rõ từng bước.
- [ ] Migration có guard chống duplicate config.

---

## 🚀 8. ROLLOUT PLAN

### 8.1 Nếu chưa có user production dùng OTA cũ

Có thể rollout thẳng:

```text
1. Merge refactor.
2. Build caramos-ota mới.
3. Test VM.
4. Upload PPA.
5. Publish manifest schema mới.
6. Test từ VM bản cũ.
```

### 8.2 Nếu đã có user dùng client cũ

Cần bridge rollout:

```text
Pha 1:
  - phát hành caramos-ota bridge
  - bridge vẫn hiểu manifest cũ
  - bridge có updater mới
  - manifest cũ yêu cầu update caramos-ota lên bridge

Pha 2:
  - publish manifest schema mới
  - bridge client đọc release
  - update tiếp bằng migration model
```

---

## 🧪 9. TEST CASES CỤ THỂ

| ID | Test | Expected |
| --- | --- | --- |
| TC-001 | `caramos-ota-update --help` | In help, exit 0. |
| TC-002 | `caramos-ota-update --from 1.0.1 --target 1.0.2 --dry-run` | In đủ chain `1.0.1 -> 1.0.1 -> 1.0.2 -> 1.0.3 -> 1.0.4 -> 1.0.5`, không sửa hệ thống. |
| TC-003 | Thiếu migration path | Thử update `caramos-ota` từ PPA để lấy migration mới; nếu vẫn thiếu thì mới fail rõ. |
| TC-004 | Migration metadata OK | Đọc migration index. |
| TC-005 | Migration metadata DNS fail | Fail closed, không đoán target. |
| TC-006 | Migration index invalid JSON | Fail closed. |
| TC-007 | `caramos-ota --check` | Ghi state, không install. |
| TC-008 | `caramos-ota --upgrade --yes` | Gọi updater đúng target. |
| TC-009 | Notifier có update | Hiện version current -> latest. |
| TC-010 | Notifier không có display | Thoát im lặng. |
| TC-011 | Migration fail giữa chừng | State transaction failed, log có lỗi. |
| TC-012 | Chạy lại sau fail | Bắt đầu từ version cuối thành công hoặc fail rõ. |
| TC-013 | Timer chạy | Chỉ check, không install. |

---

## 📋 10. WORK LOG

| Ngày | Session | Việc đã làm | Kết quả | Bước tiếp theo |
| --- | --- | --- | --- | --- |
| 2026-06-06 | Planning | Chốt chuyển sang migration model | Đồng ý hướng mới | Viết tracker chi tiết |
| 2026-06-06 | Docs | Cập nhật README cấp packages và caramos-ota | Docs đổi sang migration model | Review docs + implement skeleton |
| 2026-06-06 | Tracker | Viết tracker tiếng Việt chi tiết | Đã chốt contract trước khi code | Bắt đầu Phase 1 |
| 2026-06-06 | Phase 1 | Tạo `caramos-ota-update`, package `caramos_ota_update`, runner/context/migration skeleton, update `debian/install`; thêm migration chain theo 4 PR: `#40 -> 1.0.2`, `#41 -> 1.0.3`, `#42 -> 1.0.2`, `#43 -> 1.0.2`; thêm `tools/caramos-ota-testkit.sh` để bundle/test trên VM CaramOS | Compile pass, `--help` pass, dry-run path `1.0.1 -> 1.0.2` pass, source testkit bundle pass, live VM xác nhận app chào mừng đổi text sang CaramOS cho `1.0.2` | Test idempotency `1.0.2` + implement migration thật cho `1.0.2`/`1.0.2` |

---

## ✅ 11. FINAL ACCEPTANCE CRITERIA

Task này chỉ được coi là xong khi:

- [ ] `caramos-ota-update` tồn tại và được package vào `.deb`.
- [ ] Migration runner load được migrations.
- [ ] Runner tìm path từ current tới target.
- [ ] Runner dry-run không sửa hệ thống.
- [ ] Nếu thiếu migration path, hệ thống thử self-update `caramos-ota` trước khi fail.
- [ ] Manifest model mới dùng `release`.
- [ ] `caramos-ota --check` không còn build package min_version list.
- [ ] `caramos-ota --upgrade` gọi updater.
- [ ] Notifier đọc state mới và hiển thị version update.
- [ ] Build `.deb` pass.
- [ ] Install local trong VM pass.
- [ ] Update thật trong VM pass.
- [ ] Migration index fail fail closed.
- [ ] State/log đủ rõ để support migration fail.
- [ ] README và tracker khớp code thật sau refactor.

---

## ✅ 12. QUYẾT ĐỊNH ĐÃ CHỐT TRƯỚC KHI CODE

Các quyết định dưới đây là contract triển khai. Khi code, nếu gặp mâu thuẫn thì ưu tiên phần này.

### 12.1 Nguồn version hiện tại

- `current_version` lấy từ `VERSION` trong `/etc/caramos-release`.
- `CHANNEL` và `UBUNTU_CODENAME` cũng lấy từ `/etc/caramos-release` để accept migration metadata.
- Sau khi migration thành công, version trong `/etc/caramos-release` phải được nâng ngay.

Ví dụ:

```text
NAME="CaramOS"
VERSION="1.0.3"
CHANNEL="stable"
UBUNTU_CODENAME="noble"
```

### 12.2 Ai cập nhật `/etc/caramos-release`

- Runner là nơi chịu trách nhiệm cập nhật `VERSION` sau mỗi migration thành công.
- Migration không nên tự cập nhật release file nếu không có lý do đặc biệt.
- Điều này tránh việc contributor quên nâng version sau migration.

Flow:

```text
run migration 1.0.2 -> 1.0.3
  └── success
      └── runner set VERSION=1.0.3

run migration 1.0.3 -> 1.0.2
  └── success
      └── runner set VERSION=1.0.2
```

### 12.3 Format version

- Manifest `release` dùng version CaramOS thuần, ví dụ `1.0.2`.
- Debian package vẫn dùng version packaging, ví dụ `1.0.2-0caramos1`.
- So sánh version có thể dùng `dpkg --compare-versions` để tránh tự parse sai.

### 12.4 Thứ tự migration phải chính xác

Migration phải chạy theo đúng chuỗi version liền kề.

Ví dụ nếu máy đang `1.0.1` và latest là `1.0.2`, runner phải tự tìm và chạy tuần tự:

```text
1.0.1 -> 1.0.2
1.0.2 -> 1.0.3
1.0.3 -> 1.0.2
```

Không được giả định user luôn ở version gần latest.

### 12.5 Thiếu migration ở giữa thì ưu tiên cập nhật OTA trước

Nếu máy đang `1.0.1`, latest là `1.0.2`, nhưng package `caramos-ota` hiện tại chỉ có:

```text
1.0.3 -> 1.0.2
```

thì không được dừng ngay. Trường hợp này có thể đơn giản là client OTA đang quá cũ và chưa ship đủ migration. Runner/orchestrator phải ưu tiên cập nhật chính bộ OTA trước để lấy migration mới hơn.

Flow đúng:

```text
current = 1.0.1
target = 1.0.2
runner không tìm thấy path đầy đủ
  ├── apt-get update
  ├── apt-get install --only-upgrade caramos-ota
  ├── ghi state: ota_self_updated / requires_resume
  └── chạy lại hoặc yêu cầu chạy lại caramos-ota-update
      └── resolve path lại với migration mới
```

Sau khi OTA mới đã được cài, runner phải thử resolve path lại. Nếu lúc này có đủ migration:

```text
1.0.1 -> 1.0.2
1.0.2 -> 1.0.3
1.0.3 -> 1.0.2
```

thì chạy update bình thường.

Chỉ fail nếu sau khi đã update `caramos-ota` mà vẫn không có path đầy đủ, hoặc PPA không có bản `caramos-ota` mới hơn.

Fail message lúc đó phải rõ:

```text
Không tìm thấy migration path từ 1.0.1 tới 1.0.2 sau khi đã cập nhật caramos-ota.
Thiếu migration: 1.0.1 -> 1.0.2 hoặc 1.0.2 -> 1.0.3.
```

Không được nhảy thẳng, không được đoán, không được update nửa vời.

### 12.6 Rollback v1

- V1 chưa làm rollback tự động đầy đủ.
- Ưu tiên: repair APT/dpkg, transaction log rõ, resume từ version cuối thành công.
- Nếu sau này cần rollback thật, mỗi migration có thể thêm optional `rollback(context)` và test riêng.

### 12.7 Dry-run

Dry-run tuyệt đối không sửa hệ thống:

- không `apt-get install`;
- không `apt-get remove`;
- không ghi `/etc/caramos-release`;
- không sửa file config;
- không enable/disable service;
- chỉ in/log các action dự kiến.

### 12.8 State timing

Runner phải ghi state theo từng bước:

```text
trước migration:
  transaction.status = running
  transaction.current_migration = 1.0.2_to_1.0.3

sau migration success:
  installed_version = 1.0.3
  transaction.status = running hoặc success nếu đã tới target

nếu fail:
  transaction.status = failed
  transaction.current_migration = migration đang lỗi
  transaction.failed_at/message/log = thông tin lỗi
```

### 12.9 Ưu tiên self-update của OTA

Nếu một bản update cần nâng chính `caramos-ota`, `caramos-ota-notifier` hoặc `caramos-ota-update`, thì phải ưu tiên update bộ OTA trước.

Quy tắc:

```text
1. Migration phát hiện cần update OTA package.
2. Cài/nâng `caramos-ota` trước qua APT.
3. Ghi state rằng OTA đã được cập nhật hoặc cần chạy lại nếu cần.
4. Các migration còn lại xử lý sau khi OTA mới đã sẵn sàng.
```

Lý do:

- Nếu logic updater/notifier cũ có bug, phải đưa bản sửa lên trước.
- Các thay đổi phức tạp phía sau nên để OTA mới xử lý.
- Tránh client cũ chạy migration mới mà nó không hiểu đầy đủ.

Implementation đã chốt: dùng **re-exec tự động** để user không phải chạy lại thủ công.

Flow:

```text
caramos-ota --upgrade --yes
  ├── apt-get update
  ├── apt-get install --only-upgrade caramos-ota
  ├── nếu caramos-ota vừa được nâng version:
  │   └── exec lại /usr/bin/caramos-ota --upgrade --yes --skip-self-update
  └── process mới gọi caramos-ota-update --target <release>
```

Cần có guard flag để tránh loop:

```text
--skip-self-update
```

Rule:

- Lần chạy đầu được phép self-update OTA.
- Sau khi self-update thành công, phải re-exec sang binary/code mới.
- Lần chạy sau với `--skip-self-update` không được tự update OTA lần nữa.
- Nếu re-exec fail, ghi transaction failed và báo lỗi rõ.
- User/notifier không phải bấm lại hay chạy lại lệnh thủ công.

### 12.10 Tracker là nguồn theo dõi chính

- Mọi phase phải update tracker sau khi làm.
- Nếu đổi contract, phải sửa tracker trước hoặc cùng lúc với code.
- README giải thích kiến trúc; tracker theo dõi tiến độ triển khai.

### 12.11 Self-update OTA thuộc trách nhiệm của `caramos-ota`

Self-update của bộ OTA phải nằm trong orchestrator chính:

```text
caramos-ota --upgrade
  ├── self-update caramos-ota nếu PPA có bản mới
  ├── re-exec /usr/bin/caramos-ota --upgrade --yes --skip-self-update
  └── gọi caramos-ota-update --target <release>
```

`caramos-ota-update` không chịu trách nhiệm tự update chính package OTA. Updater chỉ chạy migration chain.

### 12.12 `--skip-self-update` là guard chống loop

Sau khi re-exec, process mới chạy với:

```text
--skip-self-update
```

Nếu lúc này vẫn thiếu migration path:

- không self-update lần nữa;
- không loop;
- fail rõ;
- ghi transaction failed;
- báo đây là lỗi release/maintainer hoặc PPA chưa có package đúng.

### 12.13 Migration không tự update `caramos-ota`

Migration bình thường không được tự cài/nâng:

```text
caramos-ota
caramos-ota-notifier
caramos-ota-update
```

Việc update bộ OTA là trách nhiệm của `caramos-ota --upgrade` trước khi gọi migration runner.

Chỉ được phá rule này nếu có migration đặc biệt được ghi rõ trong tracker/release note và đã có test riêng, nhưng mặc định là **không**.

---

## 🧭 13. NEXT ACTION

Bước làm ngay tiếp theo:

```text
Phase 1 — Tạo caramos-ota-update skeleton
```

Checklist thực thi ngay:

- [ ] Tạo `/usr/bin/caramos-ota-update`.
- [ ] Tạo folder `caramos_ota_update/`.
- [ ] Tạo `cli.py` parse `--target`, `--from`, `--to`, `--dry-run`.
- [ ] Tạo `runner.py` skeleton.
- [ ] Tạo `context.py` skeleton.
- [ ] Tạo `migrations/__init__.py`.
- [ ] Update `debian/install`.
- [ ] Chạy compile.

Lệnh kiểm tra sau Phase 1:

```bash
cd packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota-update \
  usr/lib/python3/dist-packages/caramos_ota_update/*.py

PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-update --help
PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-update --from 1.0.1 --target 1.0.2 --dry-run
```
---

## ✅ Release tracker — OTA 1.0.2 → 1.0.5

| Trường | Giá trị |
| --- | --- |
| Người release | dungleviet |
| Package | caramos-ota |
| Debian version cần publish | 1.0.5-0caramos1 |
| PPA | ppa:vietnamlinuxfamily/caram-os |
| Source user version | CaramOS 1.0.1 |
| Target version | CaramOS 1.0.5 |
| Technical codename | wilma |
| Ubuntu codename | noble |

### Migration chain

```text
1.0.1 → 1.0.2  MintWelcome branding
1.0.2 → 1.0.3  default ZRAM
1.0.3 → 1.0.4  MintReport banner branding
1.0.4 → 1.0.5  technical codename fix: caram → wilma
```

### User command after PPA release

```bash
sudo apt update
sudo apt install caramos-ota
sudo caramos-ota
```

Desktop popup flow:

```bash
sudo apt update
sudo apt install caramos-ota
caramos-ota-notifier
```

### Maintainer release checklist

- [ ] `debian/changelog` bumped to `1.0.5-0caramos1`.
- [ ] `migration.json` contains `1.0.2`, `1.0.3`, `1.0.4`, `1.0.5`.
- [ ] Every `v1_0_X/` migration directory has `__init__.py`, `manifest.json`, and migration code.
- [ ] Python compile passes.
- [ ] Local `.deb` build passes.
- [ ] VM E2E `install-and-cli` passes from `1.0.1` to `1.0.5`.
- [ ] `add-apt-repository ppa:mozillateam/ppa` no longer fails with codename `caram`.
- [ ] PPA upload done by `dungleviet`.
- [ ] `apt-cache policy caramos-ota` shows candidate `1.0.5-0caramos1` or newer.
- [ ] User command path verified.

### Maintainer commands

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

PPA upload:

```bash
debuild -S -sa
dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.5-0caramos1_source.changes
```
