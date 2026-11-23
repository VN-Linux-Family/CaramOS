# xfce4-caramos-plugin

Plugin thanh tác vụ Xfce của CaramOS, đóng gói cho PPA. Trên CaramOS Xfce nó giữ chỗ cho Control Center trong đảo
phải của thanh tác vụ (giữa khay hệ thống và nút Góp ý & hỗ trợ), như applet Control Center của bản Cinnamon. Control
Center vẽ ở đó cả đồng hồ, để lịch của đồng hồ hiện được âm lịch.

## Chia việc với caramos-ota

Gói này chỉ là một plugin nhỏ viết bằng C (`src/caramos-control-center.c`). Nó tạo một ô XEmbed (GtkSocket) trên
thanh tác vụ rồi chạy Control Center vào ô đó:

```text
/usr/share/caramos-ota/xfce/caramos-control-center --plug <số của ô>
```

Bản thân Control Center (đồng hồ và lịch âm, nút trên thanh tác vụ, bảng điều khiển, ô hiện mức âm lượng khi bấm phím
âm lượng) viết bằng
Python và GTK 3, nằm trong gói `caramos-ota`, ở `packages/caramos-ota/usr/share/caramos-ota/xfce/control-center/`. Nhờ
vậy, sửa Control Center chỉ cần cập nhật `caramos-ota` qua OTA như mọi thứ khác; gói này hầu như không phải đổi.

- Control Center thoát hoặc bị tắt thì plugin chạy lại sau 3 giây.
- Thanh tác vụ khởi động lại thì Control Center cũ tự thoát, và plugin mới chạy một Control Center mới.
- Plugin là plugin ngoài (`X-XFCE-Internal=false`): nếu nó lỗi, thanh tác vụ vẫn chạy.

Control Center bản Xfce tách hẳn khỏi applet Cinnamon: hai bên không dùng chung mã. Chỉ có hai thứ chung, để hai bản
nói cùng một câu và nhớ cùng một lựa chọn:

- bản dịch (`po/caramos-control-center`);
- thiết lập màu nhấn (schema `net.vietnamlinuxfamily.caramos.control-center`).

## Dùng

```bash
make deb      # dựng .deb trong container Ubuntu 24.04 (build/*.deb)
make source   # gói nguồn cho PPA
make upload   # ký và đưa lên ppa:vietnamlinuxfamily/caram-os
```

Khi dựng ISO bản Xfce, `scripts/ota_bootstrap.sh` (`install_xfce_panel_plugins`) cài gói này sau caramos-ota:

- có sẵn `build/*.deb` thì cài bản đó, để dựng thử trước khi đưa gói lên PPA;
- không có thì cài từ PPA.

Vì vậy, khi phát hành bản đầu tiên có Xfce, phải đưa gói lên PPA trước khi gắn tag (cùng lúc với
`xfce4-docklike-plugin`).

## Cấu hình liên quan

- Vị trí trên thanh tác vụ:
  `config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml` (plugin-5).
- Hình dáng nút trong đảo phải: `#caramos-cc-indicator` trong
  `packages/caramos-ota/usr/share/caramos-ota/xfce/panel-islands.css`.
- Phím âm lượng chạy `caramos-volume` (đổi âm lượng bằng `wpctl`, rồi nhờ Control Center hiện mức âm lượng):
  `xfce4-keyboard-shortcuts.xml` cùng thư mục với `xfce4-panel.xml`.
- nm-applet vẫn chạy để hỏi mật khẩu Wi-Fi và VPN, nhưng ẩn biểu tượng, vì mạng đã hiện trên nút Control Center:
  `config/includes.chroot.xfce/etc/dconf/db/local.d/03-caramos-xfce-nm-applet`.

Test: `packages/caramos-ota/tests/test_xfce_control_center.py` và `test_xfce_panel_islands.py`.
