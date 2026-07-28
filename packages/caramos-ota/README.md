# CaramOS OTA

> **Package:** `caramos-ota`  
> **Commands:** `caramos-ota`, `caramos-ota-notifier`, `caramos-ota-update`  
> **Target:** CaramOS 1.x  
> **PPA:** `ppa:vietnamlinuxfamily/caram-os`

CaramOS OTA dùng APT/PPA làm transport, còn thay đổi hệ thống được điều phối bằng migration giống database.

## Kiến trúc

```text
caramos-ota --check
  ├── update OTA engine trước
  ├── auto-discover migration folders
  ├── đọc applied-ID ledger
  └── ghi /var/lib/caramos-ota/state.json

caramos-ota-notifier
  └── đọc state → hỏi user → pkexec caramos-ota --upgrade --yes

caramos-ota-update
  ├── resolve legacy bridge + timestamp migrations pending
  ├── chạy từng migration theo thứ tự
  ├── ghi applied ID sau mỗi bước thành công
  └── cập nhật release metadata
```

- State/UI: `/var/lib/caramos-ota/state.json`
- Applied migration ledger: `/var/lib/caramos-ota/migrations.json`
- Logs: `/var/log/caramos-ota/YYYY-MM-DD.log`
- Timer chỉ check, không tự apply migration.

## Migration mới

Contributor chỉ thêm một thư mục:

```text
caramos_ota_update/migrations/
└── 20260714143022_ten_migration/
    ├── manifest.json
    ├── migration.py
    └── payload tùy chọn
```

`manifest.json`:

```json
{
  "schema": 2,
  "release": "1.0.14",
  "codename": "noble",
  "channel": "stable",
  "severity": "normal",
  "size": "migration update",
  "title": "CaramOS có bản cập nhật mới",
  "summary": "Mô tả thay đổi.",
  "release_notes_vi": [],
  "release_notes_en": []
}
```

`migration.py`:

```python
from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Mô tả migration"


def run(context: MigrationContext) -> None:
    context.log("apply change")
```

Không sửa `migration.json`. Không khai báo `FROM_VERSION`/`TO_VERSION` cho migration mới. Nhiều migration được phép dùng cùng `release`; runner chạy theo lexical ID timestamp.

Hướng dẫn đầy đủ: [MIGRATIONS.md](MIGRATIONS.md).

## Legacy bridge

`migration.json` và các folder `v1_0_2`–`v1_0_12` giữ nguyên để máy cũ nâng cấp theo chain version. Runtime mới auto-discover cả legacy và timestamp migration. Index lịch sử frozen tại `1.0.12`; timestamp migrations bắt đầu từ release `1.0.13`.

Khi ledger được tạo lần đầu, migration legacy có target không lớn hơn version đang cài được đánh dấu applied. Timestamp migration không bao giờ được đoán applied từ product version.

## Commands

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
sudo caramos-ota --upgrade
sudo caramos-ota --upgrade --yes
sudo caramos-ota --repair

sudo caramos-ota-update --dry-run
sudo caramos-ota-update --target 1.0.14 --dry-run
sudo caramos-ota-update --target 1.0.14
```

`--dry-run` không ghi state, ledger, log hoặc sửa hệ thống.

## Failure và resume

- Registry/manifest/entrypoint lỗi: fail closed.
- Ledger chỉ ghi ID sau khi migration thành công.
- Fail giữa batch: transaction giữ `completed_migrations`, `current_migration`, lỗi và log.
- Chạy lại: applied IDs được bỏ qua; chỉ migration pending chạy tiếp.
- Filesystem migration không có rollback tự động. Dùng migration fix mới hoặc recovery riêng.

## Build và test

```bash
cd packages/caramos-ota
./tools/caramos-ota-testkit.sh compile
./tools/caramos-ota-testkit.sh validate
./tools/caramos-ota-testkit.sh test
./tools/caramos-ota-testkit.sh build-deb
```

VM:

```bash
sudo ./tools/ship-ota-to-vm.sh
# trong VM
cd /tmp/caramos-ota-e2e
sudo ./vm-run-ota-e2e.sh install-and-cli
cat /etc/caramos-release
cat /var/lib/caramos-ota/migrations.json
cat /var/lib/caramos-ota/state.json
```

## Safety rules

- Không chạy command lấy từ JSON metadata.
- Không dùng `shell=True` nếu không bắt buộc.
- Không tải `.deb` thủ công; dùng APT/PPA.
- Migration phải idempotent và tôn trọng dry-run.
- ID đã phát hành bất biến; fix tiếp bằng migration ID mới.
- Package cài qua APT; systemd timer không auto-install.