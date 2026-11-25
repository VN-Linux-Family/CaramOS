# fcitx5

fcitx5 5.1.7 của Ubuntu 24.04 (`5.1.7-1build3`) thêm một bản vá, đóng gói cho PPA của CaramOS thành
`5.1.7-1build3+caramos1`: khay hệ thống hiện đúng bộ gõ đang dùng (chữ V của Lotus) ngay từ lúc đăng nhập.

## Lỗi

Trên bản Cinnamon, ngay sau khi đăng nhập, biểu tượng bộ gõ ở khay là chữ "A" (biểu tượng bàn phím), dù Lotus đã bật
và gõ Telex vẫn ra tiếng Việt. Bấm vào một ô nhập chữ thì nó mới thành "V". Bấm vào chữ "A" để bật tiếng Việt thì lại
tắt tiếng Việt thật (fcitx chuyển sang `keyboard-us`).

Nguyên nhân nằm trong fcitx5 (vẫn còn ở nhánh master của upstream, tháng 11/2026):

- Khay X11 (`XCBTrayWindow::paint`, khay mà Cinnamon hiện) vẽ biểu tượng của `lastFocusedInputContext()`: chỉ ô nhập
  chữ **đang** có con trỏ. Không ô nào có con trỏ (lúc mới đăng nhập, khi đang ở màn hình nền hay panel) thì nó vẽ
  `input-keyboard`. Menu của khay trong cùng tệp thì dùng `mostRecentInputContext()`, hàm có tính đến trạng thái dùng
  chung (`ShareInputState=All` của CaramOS).
- `ClassicUI::uiForInputContext()` bỏ qua sự kiện của ô không có con trỏ, nên đổi bộ gõ lúc không ô nào có con trỏ
  (bấm vào khay, chọn trong menu, D-Bus) thì khay không vẽ lại.

Thử sửa từ phía Cinnamon (cho ô nhập của chính Cinnamon nhận rồi nhả con trỏ lúc đăng nhập) không giữ được: mỗi lần
khay vẽ lại mà không có ô nào có con trỏ thì nó quay về "A".

## Bản vá

`caramos-tray-icon-without-focus.patch` (DEP-3), hai chỗ:

1. `src/ui/classic/xcbtraywindow.cpp`: `paint()` dùng `mostRecentInputContext()`.
2. `src/ui/classic/classicui.cpp`: sự kiện đổi bộ gõ lúc không ô nào có con trỏ vẽ lại khay ở mọi màn hình.

Đã thử trên máy ảo CaramOS 1.5.0 (Cinnamon): đăng nhập là thấy "V"; bấm thì thành "A" (tiếng Anh thật), bấm lần nữa
về "V"; gõ "vieejt" ra "việt".

## Dựng và đưa lên PPA

```
make source   # nguồn của Ubuntu 5.1.7-1build3 + bản vá → build/*.dsc, build/*_source.changes (Docker ubuntu:24.04)
make deb      # các gói .deb từ nguồn đó, để thử trên máy ảo → build/debs/
make upload   # ký (debsign) và đưa lên ppa:vietnamlinuxfamily/caram-os
```

`libclassicui.so` nằm trong gói `fcitx5-modules`.

## Đến máy người dùng

caramos-ota chỉ tự cài chính nó và các gói do migration chỉ định. Migration
`20261125090000_fcitx5_tray_shows_input_method` (bản Cinnamon) nâng các gói fcitx5 đang có trên máy lên bản này,
không cài thêm gói nào và giữ dấu "cài tự động" của chúng. ISO Cinnamon mới lấy nó từ cùng migration;
`scripts/customize.sh` dừng build nếu `fcitx5-modules` cũ hơn.

## Khi Ubuntu cập nhật fcitx5

Bản cập nhật của Ubuntu (`5.1.7-1ubuntu0.x`) xếp trên `5.1.7-1build3+caramos1`, nên apt sẽ thay gói này bằng gói của
Ubuntu và khay quay lại lỗi cũ. Khi đó dựng lại gói này trên bản của Ubuntu: sửa `UBUNTU_VERSION` và `VERSION` trong
`Makefile`, kiểm tra bản vá còn áp được, `make source upload`, rồi đổi `FIXED_VERSION` của migration trong một migration
mới.

Mỗi thứ Hai, workflow `.github/workflows/fcitx5-ubuntu.yml` chạy `tools/ubuntu-check.py`: Ubuntu có fcitx5 mới hơn `UBUNTU_VERSION` thì nó mở issue "fcitx5 của Ubuntu có bản mới".
