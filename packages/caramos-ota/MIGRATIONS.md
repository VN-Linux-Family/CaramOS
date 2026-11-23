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
  "unattended": "anytime",
  "codename": "noble",
  "severity": "normal",
  "size": "Thiết lập desktop",
  "size_en": "Desktop settings",
  "title": "Cập nhật CaramOS",
  "summary": "Áp dụng thay đổi hệ thống đã được review.",
  "title_en": "CaramOS update",
  "summary_en": "Apply reviewed system changes.",
  "release_notes_vi": [
    "Cập nhật cấu hình desktop."
  ],
  "release_notes_en": [
    "Update desktop configuration."
  ]
}
```

Quy tắc:

- Chữ hiển thị có hai bản: `title`, `summary`, `size` bằng tiếng Việt; `title_en`, `summary_en`, `size_en` bằng
  tiếng Anh cho phiên đăng nhập không phải tiếng Việt. Trung tâm cập nhật liệt kê mỗi thay đổi bằng `title` (đậm)
  và `summary`; `size` của các migration đang chờ nằm trong mục "Chi tiết" thu gọn, mỗi phần một dòng, nên `size`
  cũng phải là tiếng Việt, dạng "Tên phần (dung lượng)", ví dụ "Thanh tác vụ (dưới 1 MB)".
- `severity` là `normal`, `feature`, `important` hoặc `security`. Người dùng chỉ thấy `security`: một dòng cảnh
  báo "Bản cập nhật bảo mật" ở đầu danh sách, khi bất kỳ migration nào đang chờ có mức này. Các mức khác chỉ chọn
  `title` đại diện cho cả bản cập nhật, dùng trong lời nhắn và nhật ký gửi kèm khi nhờ hỗ trợ.

- Không thêm `release`, `version`, `from_version`, `to_version` vào manifest schema 2.
- Không thêm command, shell script inline, URL tải `.deb`, hoặc package list điều khiển runtime vào manifest.
- Manifest chỉ phục vụ UI/log/check metadata.
- Logic thay đổi hệ thống nằm trong `migration.py` hoặc module migration đã review.
- Không chạy shell từ dữ liệu JSON.

## Tự động cập nhật: trường `unattended`

Từ bản có Tự động cập nhật (migration `20261123100000_automatic_updates`), bản cập nhật tự cài sau lần kiểm tra
hằng ngày, trong lúc người dùng có thể đang làm việc, nếu Tự động cập nhật đang bật (mặc định bật; tắt trong Trung
tâm cập nhật hoặc `sudo caramos-ota --auto-update off`). Xem `caramos_ota/auto_update.py`.

Mỗi migration phải nói nó có được chạy lúc đó không, bằng trường `unattended` trong manifest:

- `"anytime"`: chạy được cả khi có người đang dùng máy. Những gì nó đổi chỉ hiện ra từ lần đăng nhập sau, hoặc
  không nhìn thấy được (phím tắt, tệp, gói mới, mẫu tài liệu). Khi `context.unattended` là `True` (bản cập nhật tự
  chạy), migration bỏ những bước làm màn hình của người đang làm việc thay đổi ngay: tải lại applet
  (`org.Cinnamon.ReloadXlet`), khởi động Fcitx, khởi động lại Nemo, panel hay xfwm4. Thay đổi đó hiện từ lần đăng
  nhập sau. Cập nhật từ Trung tâm cập nhật (`context.unattended` là `False`) vẫn làm như trước.
- `"nobody-logged-in"`: nó đổi cái người dùng đang nhìn (dựng lại panel, đổi hình nền, khởi động lại Fcitx, xóa
  hàng đợi máy in) hoặc chạy `dconf update`, thứ Cinnamon 6.6 không chịu được khi đang chạy. Bản cập nhật tự chạy có
  migration này sẽ chờ đến lúc không ai mở phiên đồ họa; trong lúc chờ, Trung tâm cập nhật vẫn hiện bản cập nhật ở
  lần đăng nhập sau như khi tắt Tự động cập nhật.

Thiếu trường này thì coi như `"nobody-logged-in"`, và mọi migration legacy cũng vậy. Test
`tests/test_auto_update.py` bắt mọi timestamp migration ghi rõ giá trị, và giữ danh sách các migration
`nobody-logged-in`.

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
- [ ] Manifest có `unattended`; với `"anytime"`, mọi bước làm thay đổi màn hình đang mở đều bỏ qua khi
      `context.unattended` là `True`.
- [ ] Không thêm cơ chế chọn migration theo product version.
- [ ] Migration idempotent hoặc có guard rõ.
- [ ] `dry-run` không sửa hệ thống.
- [ ] `make compile` pass.
- [ ] `make validate` pass.
- [ ] `make build` pass.
- [ ] VM test chạy qua ledger, không phụ thuộc hardcoded target.
