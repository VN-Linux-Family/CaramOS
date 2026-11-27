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
  migration này sẽ chờ đến lúc không ai mở phiên đồ họa. Từ CaramOS 1.5.2.1, nó được cài ở lần khởi động sau, trước
  màn hình đăng nhập (`caramos-ota-boot-update.service`, `auto_update.boot_run`); trong lúc chờ, Trung tâm cập nhật
  vẫn hiện bản cập nhật.

**Migration mới luôn là `"anytime"`.** Danh sách `nobody-logged-in` đã đóng ở `20261105120000_keep_lotus_settings`
(CaramOS 1.3.4): việc cập nhật lúc khởi động chỉ diễn ra một lần, với máy từ 1.3.3 trở về trước, và màn hình khởi
động hứa với người dùng như vậy (owner, 2026-11-27). Migration mới đổi cái người dùng đang nhìn thì để phần đó lại
cho lần đăng nhập sau như dưới đây.

Một migration đổi thiết lập riêng của từng người (panel, biểu tượng trên màn hình nền) vẫn là `"anytime"` được nếu nó
để phần nhìn thấy lại cho lần đăng nhập sau của người đang đăng nhập (`caramos_ota_update/deferred.py`):

- Với mỗi người dùng, gọi `deferred.wait_for_login(context, MIGRATION, STEP, username, uid)`. Khi bản cập nhật tự
  chạy và người đó đang đăng nhập, hàm này ghi bước `STEP` vào `/var/lib/caramos-ota/login-actions/<uid>.json` và
  trả `True`: migration bỏ qua người đó. Còn lại (cập nhật từ Trung tâm cập nhật, người chưa đăng nhập) nó trả
  `False` và migration đổi luôn như trước.
- `LOGIN_ACTIONS = {STEP: hàm}` trong migration: ở lần đăng nhập sau, trước khi màn hình nền khởi động,
  `/etc/X11/Xsession.d/96caramos-login-actions` gọi `hàm(session)` dưới quyền người đó (`session.gsettings(...)`,
  `session.run([...])`), mỗi bước một lần. Hàm đọc lại thiết lập lúc đó, nên thay đổi người dùng làm trong lúc chờ
  vẫn được giữ. Hàng đợi chỉ chứa tên migration và tên bước, không chứa lệnh.
- `dconf update` (dựng lại `/etc/dconf/db/local`, Cinnamon 6.6 chết khi đang chạy) lúc có người đăng nhập thì gọi
  `deferred.dconf_update_at_next_start(context)`: `caramos-ota-dconf-update.service` chạy nó ở lần khởi động sau,
  trước khi ai đăng nhập được.

Ví dụ: `20261124100000_show_desktop_button`, `20261124140000_show_trash_on_desktop`.

Thiếu trường này thì coi như `"nobody-logged-in"`, và mọi migration legacy cũng vậy. Test
`tests/test_auto_update.py` bắt mọi timestamp migration ghi rõ giá trị, và giữ danh sách các migration
`nobody-logged-in`.

## Không để dpkg hỏi

Bản cập nhật chạy không có terminal (Trung tâm cập nhật, lần kiểm tra hằng ngày, Tự động cập nhật), và bước tự cập
nhật chạy bản `caramos-ota` đang cài. Một câu hỏi của dpkg làm bản cập nhật dừng, và máy không cập nhật được nữa
(ticket H-1207: tệp cấu hình `/etc/xdg/mimeapps.list` của 1.4.0 và 1.5.0, trên máy đã có sẵn tệp cùng tên).

- Migration cài, thay hay gỡ gói bằng `context.apt_install`, `context.apt_replace`, `context.apt_remove`, không gọi
  `apt-get` trực tiếp. Các hàm này chạy với `--force-confdef --force-confold` và `DEBIAN_FRONTEND=noninteractive`:
  tệp cấu hình người dùng đã sửa được giữ nguyên.
- Gói không thêm tệp cấu hình trong `/etc` mang tên mà người dùng hay chương trình khác có thể đã tạo. Thiết lập mặc
  định của hệ thống để trong `/usr/share` khi chuẩn cho phép, ví dụ `/usr/share/applications/<desktop>-mimeapps.list`.

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
