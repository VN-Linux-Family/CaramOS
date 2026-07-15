# CaramOS OTA migrations

Migration mới dùng ID theo UTC timestamp và được tự discover. Contributor chỉ thêm một thư mục; không sửa `migration.json`.

## Tạo migration

Lấy timestamp UTC:

```bash
date -u +%Y%m%d%H%M%S
```

Tạo thư mục:

```text
usr/lib/python3/dist-packages/caramos_ota_update/migrations/
└── 20260714143022_ten_migration/
    ├── manifest.json
    ├── migration.py
    └── payload tùy chọn
```

Tên phải khớp:

```text
YYYYMMDDHHMMSS_ten_snake_case
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
  "summary": "Mô tả ngắn thay đổi.",
  "release_notes_vi": [
    "Chi tiết tiếng Việt."
  ],
  "release_notes_en": [
    "English details."
  ]
}
```

`migration.py`:

```python
from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Mô tả migration"


def run(context: MigrationContext) -> None:
    context.log("apply change")
```

Không khai báo `FROM_VERSION`, `TO_VERSION` hoặc ID trong Python. ID lấy từ tên thư mục; release lấy từ manifest. Nhiều migration được phép cùng `release`.

## Cơ chế chạy

- Registry scan mọi thư mục migration khi package chạy.
- Timestamp migrations chạy theo lexical ID, tương đương thứ tự UTC timestamp.
- `/var/lib/caramos-ota/migrations.json` lưu migration ID đã apply.
- Migration đã apply không chạy lại.
- Migration thêm muộn cho release hiện tại vẫn được nhận là pending.
- Ledger chỉ ghi ID sau khi `run()` thành công. Nếu batch fail, lần sau resume phần chưa apply.
- `migration.json` và `v1_0_*` là bridge lịch sử, frozen tại `1.0.13`.

## Quy tắc

- ID đã phát hành bất biến; không rename hoặc sửa migration cũ. Tạo ID mới để sửa tiếp.
- Migration phải idempotent và dùng `MigrationContext` cho dry-run-aware operations.
- Không chạy command từ JSON, không dùng `shell=True`, không tải `.deb` thủ công.
- Dùng `Path(__file__).parent` cho payload nằm cạnh `migration.py`.
- `--dry-run` không được ghi state, ledger, log hoặc sửa hệ thống.

## Kiểm tra

```bash
cd packages/caramos-ota
./tools/caramos-ota-testkit.sh compile
./tools/caramos-ota-testkit.sh validate
./tools/caramos-ota-testkit.sh test
./tools/caramos-ota-testkit.sh build-deb
```

`validate` fail closed khi tên folder, manifest, entrypoint hoặc legacy chain sai.