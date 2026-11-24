# fastfetch

fastfetch 2.71.0 đóng gói cho PPA của CaramOS, có logo CaramOS (ticket H-1203: thay neofetch đã ngừng phát triển
bằng fastfetch, có art ASCII của CaramOS).

## Vì sao cần gói này

Ubuntu 24.04 không có fastfetch; nó chỉ có từ Ubuntu 25.04 (Debian 13 có 2.40.4). Gói Debian 2.71.0+dfsg-1 không dựng
được trên 24.04 như nguyên bản: nó dùng libyyjson-dev của hệ thống, mà libyyjson-dev cũng chỉ có từ 25.04.

neofetch 7.1.0 vẫn có sẵn trên CaramOS (từ ảnh gốc của Linux Mint, ở cả hai bản), kèm wrapper
`/usr/local/bin/neofetch` vẽ logo CaramOS (hook `0200-caramos-debrand`). Upstream neofetch đã lưu trữ repo từ
tháng 4/2024.

## Nguồn

- **Upstream:** archive của tag `2.71.0` trên GitHub (upstream không phát hành tarball nguồn riêng). `Makefile` ghim
  SHA-256 của tarball.
- **Đóng gói:** lấy từ gói Debian 2.71.0+dfsg-1 (Hiago De Franco, Maytham Alsudany), đổi ba chỗ:
  - dùng tarball upstream nguyên vẹn, giữ `src/3rdparty` (yyjson, libsixel, AMD ADL SDK: MIT; widecharwidth:
    public domain), và dựng yyjson kèm theo thay cho libyyjson-dev (`debian/rules`);
  - thêm `debian/caramos/`: logo `caramos.txt` (vào `/usr/share/fastfetch/logos/`) và cấu hình mặc định
    `config.jsonc` (vào `/etc/xdg/fastfetch/`);
  - Maintainer, `debian/watch`; bỏ `gbp.conf` và `salsa-ci.yml` của Debian.
- **Giấy phép:** fastfetch MIT; logo và cấu hình CaramOS GPL-3+ như repo (`debian/copyright`).

## Logo CaramOS

Không cần vá fastfetch. fastfetch đọc `fastfetch/config.jsonc` đầu tiên nó tìm thấy trong `~/.config`, rồi
`$XDG_CONFIG_DIRS`, `/etc/xdg`, `/etc`; tệp của gói nằm ở `/etc/xdg/fastfetch/config.jsonc`:

- logo: `/usr/share/fastfetch/logos/caramos.txt`, trái khế 42x18 lấy từ
  `config/includes.chroot/usr/share/caramos/ascii-logo.txt`; vòng tròn cam `#f9a825`, khế trắng, viền cam nhạt;
- tiêu đề (user@máy) màu cam, tên mục màu xanh CaramOS `#3a855a`;
- danh sách mục là danh sách mặc định của fastfetch (cấu hình không có `modules` thì chỉ hiện logo).

Không có tệp này, fastfetch trên CaramOS vẽ logo Ubuntu: nó không có logo CaramOS và lấy chữ đầu của ID_LIKE trong
`/etc/os-release`. Dòng OS thì không cần gì thêm: fastfetch in PRETTY_NAME, "CaramOS 1.5.0 Xfce x86_64".

Người dùng muốn cấu hình riêng thì chép tệp này sang `~/.config/fastfetch/config.jsonc` rồi sửa; tệp ở đó thay hẳn
tệp hệ thống.

## Dùng

```bash
make deb      # dựng .deb trong container Ubuntu 24.04 không có mạng, như máy dựng của Launchpad (build/*.deb)
make source   # gói nguồn cho PPA
make upload   # ký và đưa lên ppa:vietnamlinuxfamily/caram-os
```

`make deb` cài build-deps vào một image cục bộ (`caramos-fastfetch-builddeps:noble`, có mạng), rồi dựng gói trong
image đó với `--network none`. Bộ test của upstream (20 test, `BUILD_TESTS=ON`) chạy trong lúc dựng.

## Đưa vào CaramOS

- Migration `20261124130000_install_fastfetch` của caramos-ota cài `fastfetch` trên cả hai bản (như
  `20261122100000_carlito_font`: cài không được thì ghi log rồi đi tiếp). ISO chạy mọi migration lúc dựng
  (`scripts/ota_bootstrap.sh`, sau khi nguồn PPA đã vào rootfs), nên migration này lo cả ISO mới lẫn máy đã cài.
  Không có trong `config/packages.txt`: danh sách đó được cài trước khi có nguồn PPA.
- `scripts/customize.sh` dừng bản dựng ISO khi sau các migration máy chưa có `fastfetch`. Vì vậy khi phát hành, gói
  này phải lên PPA trước khi dựng ISO (như các plugin Xfce): `make -C packages/fastfetch source upload`, rồi đợi bản
  noble amd64 có trong Packages.xz của PPA.
- neofetch giữ nguyên, kèm wrapper `/usr/local/bin/neofetch` của hook `0200-caramos-debrand`. Hook không còn phần
  wrapper `/usr/local/bin/fastfetch`: phần đó chưa bao giờ chạy, và nếu chạy thì `--logo` của nó sẽ thay logo trong
  cấu hình của gói.
