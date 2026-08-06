# CaramOS OTA

> **Package:** `caramos-ota`
>
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`
>
> **Target OS:** CaramOS 1.x
>
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`
>
> **Model:** schema 2 timestamp migrations + ledger

`caramos-ota` là hệ thống cập nhật OTA riêng của CaramOS. Nó không thay thế APT; nó dùng APT/PPA làm lớp vận chuyển package, còn thay đổi hệ thống CaramOS được điều phối bằng migration đã review.

> [!IMPORTANT]
> Model hiện tại không dùng manifest tổng kiểu latest release. Migration mới dùng timestamp ID. Manifest schema 2 không chứa `release`, `version`, `from_version`, hoặc `to_version`. Runner chạy mọi timestamp migration chưa apply theo thứ tự lexical dựa trên ledger.

---

## 1. Đọc nhanh cho contributor

1. `caramos-ota` là orchestrator: check OS/repo/state, ghi state, gọi updater.
2. `caramos-ota-notifier` là desktop UI: đọc state và gọi `pkexec caramos-ota --upgrade --yes` sau khi user xác nhận.
3. `caramos-ota-update` là migration runner: chạy timestamp migrations chưa apply theo thứ tự lexical.
4. Ledger quyết định migration nào đã chạy; product version không chọn migration mới.
5. Manifest schema 2 chỉ chứa metadata UI/log, không chứa release/version/from/to.
6. Không chọn migration mới bằng product version.
7. Legacy `v1_0_2..v1_0_12` chỉ để tương thích và coi như frozen.
8. Migration vẫn dùng APT/PPA để cài package; không tải `.deb` thủ công.
9. Systemd timer chỉ check/chuẩn bị state, không tự apply migration.
10. Local `make compile`, `make validate`, `make build` không cần `VERSION`. Chỉ `make release VERSION=x.y.z` nhận product version.

---

## 2. Kiến trúc tổng thể

```text
caramos_ota_update/migrations/
  ├── v1_0_2 ... v1_0_12        # legacy compatibility, frozen
  └── YYYYMMDDHHMMSS_slug/      # schema 2 timestamp migration
      ├── manifest.json         # metadata, no release/version/from/to
      └── migration.py          # reviewed system changes

caramos-ota --check
  ├── verify CaramOS identity
  ├── verify PPA/keyring
  ├── inspect packaged migration metadata
  ├── compare timestamp IDs with ledger
  └── write /var/lib/caramos-ota/state.json

caramos-ota-notifier
  ├── read state.json
  ├── show GTK dialog nếu có unapplied migration
  └── pkexec caramos-ota --upgrade --yes

caramos-ota --upgrade
  └── caramos-ota-update
      ├── load ledger
      ├── sort unapplied timestamp IDs lexically
      ├── run each migration
      ├── record each successful ID in ledger
      └── update state/log
```

---

## 3. Ba command chính

| Command | Nhiệm vụ |
|---|---|
| `caramos-ota` | CLI/orchestrator. Check update state và gọi updater khi upgrade. |
| `caramos-ota-notifier` | Desktop notifier. Không parse migration logic, không chạy APT trực tiếp. |
| `caramos-ota-update` | Root-only runner. Chạy migration chưa apply theo ledger. |

Các lệnh thường dùng:

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair
sudo caramos-ota-update --dry-run
sudo caramos-ota-update
```

---

## 4. Migration metadata

### 4.1 Layout

```text
usr/lib/python3/dist-packages/caramos_ota_update/migrations/
├── v1_0_2/ ... v1_0_12/      # legacy compatibility, frozen
└── 20260806120000_example/
    ├── manifest.json         # schema 2 metadata
    └── migration.py          # apply logic
```

### 4.2 Manifest schema 2

```json
{
  "schema": 2,
  "title": "CaramOS có bản cập nhật mới",
  "summary": "Bản cập nhật này áp dụng thay đổi hệ thống đã được review.",
  "severity": "normal",
  "release_notes_vi": [
    "Cập nhật cấu hình desktop."
  ],
  "release_notes_en": [
    "Update desktop configuration."
  ]
}
```

Quy tắc:

- Manifest schema 2 không có `release`, `version`, `from_version`, `to_version`.
- Metadata được đóng gói trong package, không tải JSON điều khiển từ mạng ở runtime.
- Manifest không chứa command, shell script inline, package install plan, hoặc URL tải `.deb`.
- Logic thật nằm trong Python/shell migration đã review.
- Không chạy shell/command lấy từ JSON metadata.
- Nếu schema breaking, phát hành bridge updater trước.

### 4.3 Legacy migrations

`v1_0_2..v1_0_12` là compatibility layer cho model cũ.

- Không dùng `vX_Y_Z` làm template cho migration mới.
- Không thêm `v1_0_13` hoặc version legacy mới.
- Không sửa legacy migration nếu không có migration-fix bắt buộc.
- Migration mới phải dùng timestamp ID và schema 2 manifest.

---

## 5. Migration runner và ledger

Runner cần:

- tìm timestamp migration directories;
- sort theo lexical ID;
- bỏ qua ID đã có trong ledger;
- chạy dry-run không sửa hệ thống và không ghi ledger;
- ghi state/log trước/sau mỗi migration;
- chỉ ghi ID vào ledger sau khi migration thành công;
- dừng ngay khi fail;
- chạy tiếp từ timestamp chưa apply đầu tiên trong lần sau.

State chính:

```text
/var/lib/caramos-ota/state.json
```

Log:

```text
/var/log/caramos-ota/YYYY-MM-DD.log
```

State nên phản ánh:

```json
{
  "last_check": "2026-08-06T16:00:00+07:00",
  "available_update": {
    "detected_at": "2026-08-06T16:00:00+07:00",
    "pending_migrations": [
      "20260806120000_example"
    ]
  },
  "transaction": {
    "status": "failed",
    "current_migration": "20260806120000_example",
    "log": "/var/log/caramos-ota/2026-08-06.log"
  }
}
```

---

## 6. Build và test local

Local build/validate không cần product version:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

Inspect package:

```bash
cd packages/caramos-ota
make inspect
```

Cần có:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/bin/caramos-ota-update
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/lib/python3/dist-packages/caramos_ota_update/
/usr/lib/python3/dist-packages/caramos_ota_update/migrations/
```

VM test nhanh:

```bash
cd packages/caramos-ota
make ship
make test
make test-notifier
```

Kỳ vọng chung:

- Không phải CaramOS thì fail closed.
- `--check` không install package.
- `--dry-run` không sửa hệ thống và không ghi ledger.
- Updater in danh sách timestamp migration sẽ chạy.
- Migration lỗi thì fail closed, không đoán target.

---

## 7. Quy trình release OTA mới

1. Tạo timestamp migration mới, ví dụ `YYYYMMDDHHMMSS_slug/`.
2. Thêm `manifest.json` schema 2, không có `release`, `version`, `from_version`, `to_version`.
3. Thêm logic migration đã review.
4. Chạy local compile/validate/build không truyền `VERSION`.
5. Test VM bằng ledger flow.
6. Maintainer chọn product version tại thời điểm release.
7. Chạy release package bằng:

```bash
cd packages/caramos-ota
make release VERSION=x.y.z
```

8. Sau khi PPA publish, test install/upgrade từ VM hoặc máy cũ.

Product version chỉ xuất hiện ở release command và artifact phát hành. Không hardcode product version vào migration schema 2 hoặc local validate.

---

## 8. Repair và rollback

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

Rollback không nên hứa quá nhiều trong v1. Migration có thể sửa config, xóa/cài package hoặc thay đổi state. Ưu tiên:

- transaction log rõ;
- repair APT/dpkg;
- chạy tiếp từ migration cuối thành công theo ledger;
- support thủ công nếu migration fail.

Nếu cần rollback thật, mỗi migration phải có `rollback(context)` riêng và được test riêng.

---

## 9. Security / safety rules

- Không chạy shell với input từ JSON metadata.
- Không dùng `shell=True` nếu không bắt buộc.
- Không tải `.deb` thủ công từ Internet.
- Không tự thêm PPA.
- Không tự install từ timer.
- Migration phải log rõ từng action.
- Migration phải tránh duplicate config khi chạy lại.
- Package install phải đi qua APT/PPA.
- Ledger chỉ ghi sau khi migration thành công.

---

## 10. Contributor checklist

- [ ] Entry point `/usr/bin/*` mỏng, logic nằm trong package Python.
- [ ] Migration mới có timestamp ID lexical.
- [ ] Manifest schema 2 không có `release`, `version`, `from_version`, `to_version`.
- [ ] Không thêm cơ chế chọn migration theo product version.
- [ ] Legacy `v1_0_2..v1_0_12` không bị sửa nếu không có migration-fix bắt buộc.
- [ ] Migration có dry-run hoặc context hỗ trợ dry-run.
- [ ] Migration idempotent hoặc có guard rõ.
- [ ] `make compile` pass.
- [ ] `make validate` pass.
- [ ] `make build` pass.
- [ ] `.deb` chứa đủ CLI, notifier, updater, migrations.
- [ ] Test install local trong VM pass.
- [ ] `caramos-ota --check` không tự cài package.
- [ ] `caramos-ota-update --dry-run` không sửa hệ thống.
- [ ] Migration lỗi thì fail closed, không đoán target.
- [ ] Release thật dùng `make release VERSION=x.y.z`.

---

## 11. Tóm tắt

```text
caramos-ota
  = check + state + gọi updater

caramos-ota-notifier
  = desktop UI

caramos-ota-update
  = timestamp migration runner

schema 2 manifest
  = UI/log metadata, no release/version/from/to

ledger
  = nguồn sự thật cho migration đã apply

PPA/APT
  = nguồn package thật
```

Muốn phát hành OTA mới thì thêm timestamp migration schema 2, test local/VM không truyền version, rồi maintainer chạy `make release VERSION=x.y.z` khi đóng product release.
