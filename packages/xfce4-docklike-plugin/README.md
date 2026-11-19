# xfce4-docklike-plugin

Docklike Taskbar, đóng gói cho PPA của CaramOS. Trên CaramOS Xfce nó là đảo giữa của thanh tác vụ: ứng dụng ghim
và đang chạy, gộp theo ứng dụng, có chấm báo đang chạy, như danh sách cửa sổ ở đảo giữa của bản Cinnamon.

## Vì sao cần gói này

Ubuntu 24.04 không có gói này; nó chỉ có từ Ubuntu 25.04 và Debian 13. Bản 0.4.3 của Debian cần libxfce4windowing
4.19.4, còn Ubuntu 24.04 có 4.19.3. Vì vậy CaramOS dùng bản 0.4.2: bản này dùng libwnck như phần còn lại của Xfce 4.18.

## Nguồn

- **Upstream:** tarball phát hành `xfce4-docklike-plugin-0.4.2.tar.bz2` từ archive.xfce.org. `Makefile` ghim SHA-256
  của tarball.
- **Kiểm chứng nguồn:** mã viết tay trong `src/` của tarball trùng với tag `xfce4-docklike-plugin-0.4.2` trên
  gitlab.xfce.org. Archive của tag đó có SHA-256 mà FreeBSD ports đã ghi (`94229e9a…`, commit `2f999a13`).
- **Đóng gói:** lấy từ gói Debian 0.4.3-1 của Kirill Rekhov, bỏ libxfce4windowing. Giấy phép: GPL-3.

## Dùng

```bash
make deb      # dựng .deb trong container Ubuntu 24.04 (build/*.deb)
make source   # gói nguồn cho PPA
make upload   # ký và đưa lên ppa:vietnamlinuxfamily/caram-os
```

Khi dựng ISO bản Xfce, `scripts/ota_bootstrap.sh` (`install_xfce_panel_plugins`) cài gói này sau caramos-ota. Nếu có sẵn
`build/*.deb` thì cài bản đó, để dựng thử trước khi gói lên PPA; nếu không thì cài từ PPA. Vì vậy, khi phát hành bản
đầu tiên có Xfce, phải đưa gói lên PPA trước khi gắn tag.

Cấu hình mặc định (ứng dụng ghim, chấm báo) nằm ở
`config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/panel/docklike.rc`. Hình đảo nằm ở
`packages/caramos-ota/usr/share/caramos-ota/xfce/panel-islands.css`.
