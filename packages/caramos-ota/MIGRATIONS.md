# CaramOS OTA migrations

Tài liệu này mô tả model migration hiện tại cho `caramos-ota`.

## Model hiện tại

CaramOS OTA dùng **schema 2 timestamp migrations**:

- Mỗi migration mới là một thư mục có ID timestamp lexical, ví dụ `20260806120000_install_control_center/`.
- Runner lấy mọi timestamp migration chưa apply, sort theo tên thư mục, rồi chạy theo thứ tự lexical.
- Ledger lưu timestamp ID đã apply. Migration đã có trong ledger không chạy lại.
- Timestamp migration không có product version riêng.
- Manifest schema 2 không chứa `release`, `version`, `from_version`, hoặc `to_version`.
- Legacy migrations `v1_0_2` đến `v1_0_12` được giữ để tương thích và coi như frozen.

## Layout

```text
usr/lib/python3/dist-packages/caramos_ota_update/migrations/
├── v1_0_2/ ... v1_0_12/      # legacy compatibility, frozen
├── 20260806120000_example/
│   ├── manifest.json         # schema 2 metadata, no release/version/from/to
│   └── migration.py          # logic apply đã review
└── ...
```

## Manifest schema 2

Ví dụ:

```json
{
  "schema": 2,
  "title": "Cập nhật CaramOS",
  "summary": "Áp dụng thay đổi hệ thống đã được review.",
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

- Không thêm `release`, `version`, `from_version`, `to_version` vào manifest schema 2.
- Không thêm command, shell script inline, URL tải `.deb`, hoặc package list điều khiển runtime vào manifest.
- Manifest chỉ phục vụ UI/log/check metadata.
- Logic thay đổi hệ thống nằm trong `migration.py` hoặc module migration đã review.
- Không chạy shell từ dữ liệu JSON.

## Ledger

Runner dùng ledger để biết timestamp migration nào đã chạy thành công.

Quy tắc:

- Migration chỉ được ghi vào ledger sau khi chạy thành công.
- Nếu migration fail, ID không được ghi vào ledger.
- Lần chạy sau tiếp tục từ timestamp chưa apply đầu tiên.
- Thứ tự chạy là lexical theo ID timestamp, không theo product version.
- Timestamp ID và ledger là đủ để xác định migration chưa apply.

## Legacy compatibility

Các migration legacy `v1_0_2` đến `v1_0_12` tồn tại để hỗ trợ máy đã phát hành trước model timestamp.

Quy tắc:

- Không đổi manifest/code legacy nếu không có migration-fix bắt buộc.
- Không thêm version legacy mới kiểu `v1_0_13`.
- Migration mới phải dùng timestamp ID và schema 2 manifest.
- Tài liệu hoặc test có thể nhắc legacy `v1_0_2..v1_0_12`, nhưng không dùng chúng làm template cho migration mới.

## Build và validate

Local build/validate không cần product version:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

Release mới là lúc duy nhất cung cấp product version:

```bash
cd packages/caramos-ota
make release VERSION=x.y.z
```

Không hardcode target release vào manifest, docs test local, hoặc script validate.

## Checklist migration mới

- [ ] Thư mục migration dùng timestamp ID lexical.
- [ ] `manifest.json` dùng `schema: 2`.
- [ ] Manifest không có `release`, `version`, `from_version`, `to_version`.
- [ ] Không thêm cơ chế chọn migration theo product version.
- [ ] Migration idempotent hoặc có guard rõ.
- [ ] `dry-run` không sửa hệ thống.
- [ ] `make compile` pass.
- [ ] `make validate` pass.
- [ ] `make build` pass.
- [ ] VM test chạy qua ledger, không phụ thuộc hardcoded target.
