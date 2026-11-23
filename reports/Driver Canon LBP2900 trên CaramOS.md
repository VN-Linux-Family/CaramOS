# Trình tải driver Canon đưa LBP2900 lên CaramOS

Hôm nay, cách ổn định nhất để chạy Canon LBP2900/LBP2900B trên CaramOS 1.3.6 là driver CAPT chính hãng bản 2.71. Đây là chiếc "lp2900" mà một doanh nghiệp 15 máy trên VNLF đang dùng, và 2.71 (15/05/2017) là bản cuối cùng Canon làm. Theo cách này, chính máy người dùng tải gói từ Canon; CaramOS kiểm SHA-256, cài nguyên vẹn, rồi bọc gói bằng các tệp tự viết: bộ thư viện i386 tối thiểu, unit systemd riêng cho `ccpd`, symlink udev cố định, tệp quirk ngăn backend `usb` của CUPS giành cổng USB, và hàng đợi `ccp://localhost:59687`. Đường này phủ cả LBP3300 mà issue #39 nêu, và người dùng đã in được bằng nó trên Ubuntu 24.04 và Mint 22.x sau vài chỉnh sửa tay. **Driver của Canon không được đưa vào PPA**, vì ba lẽ: EULA trong gói chỉ cho chuyển giao phần mềm độc quyền "only on the Product", tức nguyên gói, nguyên điều khoản, không sửa; điều khoản mà ai tải file từ trang Canon cũng phải chấp nhận thì cấm hẳn việc phân phối, sửa đổi hay "reformat"; còn Launchpad chỉ nhận giấy phép mở hoặc nội dung Canonical đã duyệt. captdriver (GPL-3+) thì hợp lệ cho PPA, không cần 32-bit và build sạch trên noble, nhưng với LBP2900 nó còn ba điểm yếu: cần bản vá backend USB của CUPS (lỗi #1461, có từ 2.4.17, trong khi noble dùng 2.4.7 và Ubuntu 26.04 vẫn là 2.4.16); dựa vào mã fork năm 2026 do LLM viết mà chính tác giả nói chưa sẵn sàng phát hành; và không hỗ trợ LBP3300. Không script cộng đồng nào dùng nguyên được. Script phổ biến nhất, do người Việt hieplpvip duy trì (209 sao, commit cuối 02/10/2020), hỏng trên noble nếu không sửa, chuyển AppArmor của cupsd sang chế độ complain và gỡ cài bằng `apt-get -y autoremove`; các toolkit năm 2026 thì mask ipp-usb, blacklist usblp, thay tệp thuộc gói CUPS hoặc mở CUPS ra LAN. Riêng gói của Canon còn chứa một vòng `kill -9` cắt sai PID trên noble, nên bộ cài phải dừng `ccpd` trước khi gọi dpkg. Hôm nay Driver Check im lặng trước một chiếc LBP2900, vì `usblp` đã nhận thiết bị. Thứ tự nên làm: mua một máy LBP2900 cũ (1,5–2,3 triệu đồng) và dạy Driver Check nhận máy CAPT theo USB ID; rồi viết công thức App Center cho driver chính hãng; sau đó mới đóng gói captdriver kèm một backend USB mang tên riêng, và chỉ cho nó làm mặc định sau khi chạy thử dài trên máy thật. Printer Application cho CUPS 3 là việc của nền kế tiếp.

*Cách đọc báo cáo: "đã kiểm chứng" là điều nhóm nghiên cứu tự kiểm tra ngày 08/11/2026. Họ tải gói của Canon từ máy chủ Canon rồi mở ra mà không cài, đọc mã nguồn và lịch sử git, build trong container `ubuntu:24.04`, đọc rootfs Mint 22.3 mà bản build CaramOS dùng, và đọc mã CaramOS tại commit `749c025`. "Theo nguồn" là điều nguồn trích dẫn nói mà chưa ai thử lại. "Suy luận" là đánh giá của báo cáo này. Không ai chạy binary của Canon hay script cài đặt cộng đồng nào; captdriver chỉ được build và chạy thử trong container. Không có máy in thật hay máy ảo nào được dùng.*

## Driver chính hãng chạy được trên noble nếu CaramOS bọc lại từ đầu đến cuối

### Bản 2.71 năm 2017 vẫn còn trên máy chủ Canon, và sẽ không có bản mới

Với LBP2900/2900B, Canon chỉ có đúng một driver Linux: **"CAPT Printer Driver for Linux V2.71"**, mã 0100459601, ghi "Last Updated 15-May-2017", dung lượng 121,61 MB. "LASER SHOT LBP2900/ 2900B" có trong danh sách máy hỗ trợ ([Canon Asia, cập nhật 15/05/2017](https://asia.canon/en/support/0100459601)). Canon Việt Nam phục vụ đúng mục này, kèm điều khoản bằng tiếng Việt ([Canon Việt Nam](https://vn.canon/vi/support/0100459601)). Trang mẫu máy không liệt kê driver UFR II, Generic Plus hay driver Linux nào khác ([Canon Asia, trang LBP2900](https://asia.canon/en/support/LASER%20SHOT%20LBP2900__%202900B/model?type=)).

Nút tải chuyển hướng tới `gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz`. Ngày 08/11/2026, tệp này trả HTTP 200, dài **127.521.219 byte**, có `last-modified` 31/03/2025 (Canon tải lại lên S3 nhưng nội dung không đổi), SHA-256 `8565a2fdc4f452bb8cf97ceadadd6614d12eac73e253ac6d59e61b8abae941be` (đã kiểm chứng) ([tệp của Canon](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)). Mã BLAKE2b của tệp trùng hệt mã mà gói AUR `capt-src` đã ghim từ khi lên 2.71 năm 2017 ([AUR capt-src PKGBUILD](https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=capt-src)). Canon không công bố checksum nào, nên tính toàn vẹn "chính thức" chỉ dựa vào HTTPS từ CDN của Canon cộng với sự trùng khớp đó.

Changelog trong gói chạy từ bản 1.50 (10/04/2007) tới 2.71 (09/03/2017). README ghi hệ điều hành được đánh giá là "Fedora 21… Ubuntu 14.10", và Canon tuyên bố sẽ "not respond to any inquiries about this Software" (đã kiểm chứng trong gói). Ngày 11/06/2020, người bảo trì AUR đã cảnh báo rằng driver năm 2017 này khó sống lâu khi GCC bỏ dần những thứ nó dùng ([AUR capt-src, bình luận](https://aur.archlinux.org/packages/capt-src)). Vậy CaramOS phải coi đây là phần mềm bị bỏ rơi cần bọc lại, không phải một upstream còn bảo trì.

### Gói "64-bit" vẫn chạy phần lõi bằng mã 32-bit mà không khai báo

Mỗi kiến trúc có hai gói: `cndrvcups-common_3.21-1` và `cndrvcups-capt_2.71-1`. **Gói amd64 là gói lai.** `ccpd`, `ccpdadmin`, backend `ccp`, các bộ lọc `pstocapt*` và giao diện GTK2 là x86-64. Còn `captfilter`, `captmon2`, mọi plugin `captmon*` và các thư viện lõi của Canon là ELF i386 32-bit (đã kiểm chứng bằng `file` và `readelf`) ([tệp của Canon](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)).

Tệp control chỉ khai phụ thuộc amd64. Canon dùng `${shlibs:Depends}`, và công cụ đóng gói chỉ phân giải các ELF 64-bit. Trên noble mọi phụ thuộc amd64 đó đều thỏa: các gói t64 khai `Provides` tên cũ, còn `libglade2-0` nằm trong universe (đã kiểm chứng trên chỉ mục Ubuntu) ([Ubuntu noble/universe amd64](http://archive.ubuntu.com/ubuntu/dists/noble/universe/binary-amd64/Packages.xz)). Hệ quả là `dpkg -i` vẫn "thành công" trên máy chưa có thư viện 32-bit, rồi `captfilter` và `captmon2` không chạy nổi vì thiếu `/lib/ld-linux.so.2` (suy luận từ cấu trúc gói). Đây đúng là kiểu "hàng đợi Ready mà không in" mà các diễn đàn hay kể.

PPD của LBP2900 khai `*opbidiPlugin: "captmon2"`. Với đường in đó, bộ i386 thật sự cần là **`libc6:i386 libpopt0:i386 libxml2:i386`**, kéo theo `libicu74`, `liblzma5` và `zlib1g` bản i386. Các mẫu khác cần thêm `libstdc++6:i386 libgcc-s1:i386`. Cả chuỗi i386 tốn khoảng **16 MB tải và 54,6 MB khi cài**, hai phần ba trong số đó là `libicu74:i386`. Hai gói Canon cài thêm khoảng 58 MB (đã kiểm chứng trên chỉ mục i386 của noble) ([Ubuntu noble-updates/main i386](http://archive.ubuntu.com/ubuntu/dists/noble-updates/main/binary-i386/Packages.xz)). Rootfs Mint 22.3 đã bật sẵn kiến trúc i386 nhưng chưa cài gói i386 nào, và chưa có `libglade2-0` (đã kiểm chứng) ([rootfs Mint 22.3](file:///home/dungleviet/Documents/CaramOS/build/cache)).

`captstatusui` là 64-bit, nên không binary nào cần GTK, ATK, Cairo hay Pango bản i386. Các gói GTK/Pango `:i386` mà script cộng đồng cố cài là thừa. Chính chúng gây ra lỗi `libpango1.0-0:i386` nổi tiếng trên 24.04 (suy luận từ phân tích ELF).

### Script bảo trì của Canon có thể giết nhầm tiến trình trên noble

`preinst` và `prerm` của `cndrvcups-capt` chạy vòng lặp ``kill -9 `ps awx | grep -e ccpd -e captmon | grep -v grep | cut -c 1-5` `` cho tới khi không còn dòng nào khớp (đã kiểm chứng trong gói) ([tệp của Canon](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)). Noble đặt `kernel.pid_max = 4194304`, nên `ps awx` in cột PID rộng 7 ký tự canh phải, và `cut -c 1-5` cắt sai. Trên Ubuntu 24.04.4, PID 629433 bị cắt thành " 6294" (đã kiểm chứng).

Khi gỡ, nâng cấp hay cài lại gói mà có tiến trình khớp chuỗi `ccpd` hay `captmon`, script chạy bằng quyền root sẽ **gửi `kill -9` tới những PID không liên quan**. Nếu `ccpd` thật vẫn sống, vòng lặp có thể chạy mãi. Biểu thức lọc còn khớp bất kỳ dòng lệnh nào chứa hai chuỗi đó, chẳng hạn một trình soạn thảo đang mở `/etc/ccpd.conf` (suy luận từ mã và định dạng `ps`). Issue hieplpvip #26 trên Mint 22.2 khớp với kịch bản này: cài đặt treo ở bước "cndrvcups-capt pre-installation script". Nhưng nguyên nhân chưa được xác nhận ([hieplpvip #26, 11/09/2025](https://github.com/hieplpvip/ubuntu_canon_printer/issues/26)).

Gói còn tạo `/etc/cngplp/account` với `chmod 777` và dùng cú pháp `chown lp.lp` kiểu cũ. Từ đó có hai yêu cầu cho bộ cài của CaramOS. Một là dừng sạch `ccpd` và `captmon*` trước khi gọi dpkg. Hai là không bao giờ để chuỗi "ccpd" hay "captmon" xuất hiện trong dòng lệnh của chính nó.

### `ccpd`, `usblp` và trình dò của CUPS giành nhau một cổng USB

`ccpd` không dùng libusb. Nó mở thiết bị ký tự `/dev/usb/lpN` do module `usblp` tạo, theo `DevicePath` đăng ký bằng `ccpdadmin -o`. Chính hướng dẫn của Canon thừa nhận số cổng có thể đổi tùy thứ tự cắm hay bật máy (đã kiểm chứng trong gói). Trên Mint 22.3, `usblp` có sẵn (`CONFIG_USB_PRINTER=m`), và không tệp modprobe hay luật udev nào chặn nó (đã kiểm chứng) ([rootfs Mint 22.3](file:///home/dungleviet/Documents/CaramOS/build/cache)).

Rắc rối là backend `usb` (libusb) của CUPS 2.4.7 tách `usblp` ra mỗi khi dò hay dùng thiết bị. Luật `70-printers.rules` của `system-config-printer-udev` lại kích hoạt việc dò ở mỗi lần cắm máy in. Issue OpenPrinting/cups #80 (mở 27/01/2021) mô tả đúng chuyện này với máy CAPT ("usblp0: removed"), và đề xuất dòng quirk `0x04a9 0x2676 blacklist` cho LBP2900. Michael Sweet đóng issue ngày 17/09/2021, gợi ý dùng một tệp quirk riêng trong `/usr/share/cups/usb` nhưng nói "No guarantees that this will solve the problem". Các bình luận năm 2025 cho biết tệp như vậy dập được thông báo "No drivers found" ([OpenPrinting/cups #80](https://github.com/OpenPrinting/cups/issues/80)). Arch Wiki (bản sửa 20/12/2025) khuyên đúng hai biện pháp: một tệp quirk riêng, và một symlink udev cố định theo VID/PID/serial thay cho `/dev/usb/lp0` ([Arch Wiki, Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT)). Tệp quirk mà noble cài sẵn không có dòng nào cho máy CAPT (đã kiểm chứng).

Cả 52 PPD của Canon đều không có `*1284DeviceID`. Vì thế CUPS không tự ghép được máy với driver, và hàng đợi phải tạo bằng tay với URI `ccp://localhost:59687` (đã kiểm chứng). Lỗi kinh điển là hàng đợi tự tạo với URI `usb://Canon/LBP2900?serial=…` cùng PPD CAPT: hàng đợi này bỏ qua `ccpd` và kẹt mãi ở "Processing" ([Launchpad #1940125, 16/08/2021](https://bugs.launchpad.net/ubuntu/+source/cups/+bug/1940125)).

Về cổng, hướng dẫn và `ccpd.conf` của Canon dùng `PDATA_Port 59687` cho hàng đợi, còn 59787 là cổng của status monitor. Arch Wiki và vài người dùng Mint lại báo 59787 chạy được ([Mint forum t=332788](https://forums.linuxmint.com/viewtopic.php?t=332788)). CaramOS nên theo tài liệu của Canon. AppArmor không phải vật cản nếu tệp nằm đúng chỗ: hồ sơ cupsd của noble chạy mọi thứ trong `/usr/lib/cups/backend/*` và `/usr/lib/cups/filter/**` dưới hồ sơ con `third_party`, gần như không hạn chế (đã kiểm chứng bằng cách đọc hồ sơ; chưa thử lúc chạy). Vì thế lệnh `aa-complain /usr/sbin/cupsd` mà nhiều script dùng là không cần.

### Không có unit systemd nên "khởi động lại là mất máy in"

Gói chỉ có `/etc/init.d/ccpd` kiểu SysV. Script này không có header LSB, chờ bận tới khi `ps` thấy `cupsd`, và postinst không bật nó lúc khởi động (đã kiểm chứng). README của Canon bảo người dùng tự thêm vào `rc.local`. Noble dùng systemd 255, nên `systemctl start ccpd` vẫn chạy được qua `systemd-sysv-generator`. Nhưng systemd 259 đã ghi thành phần này là "deprecated and scheduled for removal", dự kiến gỡ ở v260 cùng `rc.local` generator ([systemd 259, systemd-sysv-generator(8)](https://www.freedesktop.org/software/systemd/man/259/systemd-sysv-generator.html); [linuxiac](https://linuxiac.com/systemd-259-released-with-major-changes-ahead-of-legacy-sysv-removal/)).

Đây là nguồn của lời than phổ biến nhất ở mọi diễn đàn. Bài tinhte năm 2018 gọi lỗi thường gặp nhất là "không thể in sau khi khởi động lại PC" ([tinhte.vn, 22/04/2018](https://tinhte.vn/thread/cai-driver-may-in-dong-canon-lbp-cho-ubuntu.2787611/)). Người dùng Mint 20 kể đôi khi phải khởi động lại `ccpd` sau mỗi lần bật máy ([Mint forum t=332788](https://forums.linuxmint.com/viewtopic.php?t=332788)). Arch thì tự đóng gói một unit riêng (`Type=forking`, `After=cups.service`, `WantedBy=printer.target`) ([AUR ccpd.service](https://aur.archlinux.org/cgit/aur.git/plain/ccpd.service?h=capt-src)).

Khi được sửa đủ các điểm trên, driver này **in được thật trên noble**:

| Ngày | Môi trường | Điều người dùng đã làm | Nguồn |
|---|---|---|---|
| 03/09/2024 | Ubuntu 24.04 | Câu trả lời được chấp nhận trên Ask Ubuntu | [A1525400](https://askubuntu.com/a/1525400) |
| 15/06/2024 | Ubuntu 24.04 | Đổi tên gói pango, tự khởi động lại `ccpd` | [hieplpvip #24](https://github.com/hieplpvip/ubuntu_canon_printer/issues/24) |
| 22/10/2025 | Mint 22.2 | Đổi tên gói pango | [hieplpvip #27](https://github.com/hieplpvip/ubuntu_canon_printer/issues/27) |
| 22/07/2026 | Ubuntu 24.04, máy LBP-1120 | Bỏ dòng pango khỏi script | [forum.ubuntu.ru #659](https://forum.ubuntu.ru/index.php?topic=189049.645) |

Điểm yếu còn lại nằm ở tương lai. Ubuntu 26.04 bỏ `libxml2` (thay bằng `libxml2-16`), và cả 25.10 lẫn 26.04 đều không còn `libglade2-0` ([resolute/libxml2-16](https://packages.ubuntu.com/resolute/libxml2-16); [resolute/libglade2-0](https://packages.ubuntu.com/resolute/libglade2-0)). Arch đã vấp đúng những chuyện này. Soname libxml2 đổi ngày 06/05/2025. Ngày 09/04/2026, người dùng phát hiện `ccpd` rò file descriptor khi cứ thử nạp lại một thư viện ICU bị thiếu ([AUR capt-src, bình luận](https://aur.archlinux.org/packages/capt-src)). Status monitor `captstatusui` thì là GTK2 và chỉ có bản dịch ja/es/de/it/fr, không có tiếng Việt (đã kiểm chứng).

## captdriver sạch giấy phép nhưng chưa đủ tin cậy cho LBP2900 trên noble

### Năm 2026 trọng tâm phát triển dời từ agalakhov sang ValdikSS

captdriver là một bộ lọc CUPS duy nhất, `rastertocapt`, kiêm luôn vai trò port monitor. Nó ghi dữ liệu qua backend `usb` của CUPS và đọc phản hồi của máy in qua side channel và back channel. Vì thế nó không cần `ccpd`, `/dev/usb/lp0` hay thư viện 32-bit ([captdriver wiki](https://github.com/mounaiban/captdriver/wiki)). Mạng fork có khoảng 80 kho, chừng 20 kho có commit riêng (đã kiểm chứng bằng `git ls-remote`). Bản gốc agalakhov chỉ còn "passively maintained" từ 30/11/2021, commit cuối ngày 08/10/2022 ([agalakhov README](https://github.com/agalakhov/captdriver/blob/master/README)). Master của mounaiban đứng yên từ 14/10/2022, và thẻ cuối là `0.1.4-m5` ngày 16/11/2020.

Gần như mọi bản sửa liên quan tới LBP2900 nay nằm ở **ValdikSS/captdriver**, tạo 19/05/2026, với 48 commit từ 17/05 tới 06/06/2026 ([ValdikSS README](https://github.com/ValdikSS/captdriver/blob/test/README.md)). Fork này sửa kích thước giấy, lệch trang từ trang thứ hai và chậm trước trang đầu. Nó cũng in được trang lớn hơn RAM máy in nhờ chế độ streaming. README nói thẳng rằng "all the code has been written by LLM assistant", rằng muốn chạy ổn phải có CUPS 2.4.17 trở lên, và rằng kẹt giấy, mở nắp hay thiếu hộp mực sẽ làm bộ lọc dừng và phải in lại.

Theo bình luận ngày 03/06/2026, tác giả có LBP3000 và LBP6000 chứ không có LBP2900 ([agalakhov #31](https://github.com/agalakhov/captdriver/issues/31#issuecomment-4613190710)). Ngày 16/06/2026 ông xin đừng đóng gói fork vì "my version is not ready for the release yet". Ngày 13/08/2026 ông gọi mã LLM viết là "pretty nasty… It works though, not perfect, but pretty ok" ([mounaiban #8, 16/06/2026](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4714536714); [mounaiban #8, 13/08/2026](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5281082555)).

mounaiban đã chép công việc này vào nhánh `0.2.1-pr` ngày 13/08/2026. Nhánh này khác ValdikSS chủ yếu ở phần chú thích, và mounaiban hứa sẽ hợp nhất vào master rồi gửi PR cho agalakhov ([mounaiban #8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5280818961)). ValdikSS thì nói bản hoàn chỉnh sẽ lên kho OpenPrinting, nhưng `OpenPrinting/captdriver` chưa tồn tại ngày 08/11/2026 (đã kiểm chứng). Các bản phân phối đang đóng gói snapshot cũ từ 2020–2023 (AUR, Gentoo GURU, nixpkgs, ALT, OpenMandriva), hoặc fork AI của cryptoluks (ROSA). Debian và Ubuntu không có gói nào, Launchpad không có PPA captdriver, và chưa ai đóng gói nhánh ValdikSS ([Repology captdriver](https://repology.org/project/captdriver/versions); [Launchpad, tìm PPA "captdriver"](https://launchpad.net/ubuntu/+ppas?name_filter=captdriver)).

### LBP2900 được ghi "WORKS", nhưng lỗi treo kéo dài từ 2014

Mọi nhánh đều đăng ký `LBP2900` ở mức WORKS (đã kiểm chứng). Wiki liệt kê nó chạy trên Manjaro, Void và Ubuntu ARMv7, nhưng cũng thừa nhận "two significant issues": tương thích với giao diện CUPS-libusb, và độ trễ dài giữa các trang ([captdriver wiki](https://github.com/mounaiban/captdriver/wiki)). Issue "Rendering completed - Stuck" mở từ 24/12/2014 với một máy LBP2900B trên Ubuntu 14.04; lúc đó phải tắt bật máy in mới hết ([agalakhov #7](https://github.com/agalakhov/captdriver/issues/7)). "Rendering completed" là thông điệp cuối của bộ lọc Ghostscript. Hàng đợi treo ở đó nghĩa là treo *sau* bước raster, trong `rastertocapt` hoặc backend (đã kiểm chứng trong container).

Năm 2026, nguyên nhân chính được lần ra ở backend USB của CUPS. darkvision77 báo lỗi tranh chấp DRAIN_OUTPUT ngày 28/12/2025 ([OpenPrinting/cups #1461](https://github.com/OpenPrinting/cups/issues/1461)). PR #1500 của ValdikSS được hợp nhất vào nhánh 2.4.x ngày 04/03/2026 ([PR #1500](https://github.com/OpenPrinting/cups/pull/1500)). **CUPS 2.4.17 (17/04/2026)** ghi "Fixed DRAIN_OUTPUT race condition", và bản 2.4.x mới nhất là 2.4.20 ngày 05/10/2026 ([CUPS CHANGES.md](https://github.com/OpenPrinting/cups/blob/2.4.x/CHANGES.md)).

Ubuntu chưa nhận bản sửa. Noble dùng `2.4.7-1.2ubuntu7.14`, còn 26.04 và 26.10 dừng ở 2.4.16, và changelog của cả ba không nhắc #1461 (đã kiểm chứng) ([packages.ubuntu.com, cups-daemon](https://packages.ubuntu.com/search?keywords=cups-daemon&searchon=names&exact=1&suite=all&section=all)). mounaiban còn cho biết bản CUPS 2.4.18 dạng Snap không chạy với captdriver ([mounaiban #8, 13/08/2026](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5280818961)). Chuỗi ba commit vá áp được vào mã nguồn cups của noble (lệch dòng nhưng không lỗi) và build ra một `backend/usb` hoàn chỉnh trong container (đã kiểm chứng; chưa thử với máy in). Một người dùng LBP2900 báo bản ValdikSS chạy với CUPS mới thì "working great" ([mounaiban #8, 14/06/2026](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4701986539)). Nhưng đó là một báo cáo đơn lẻ.

Ngay cả khi có CUPS mới, LBP2900 vẫn còn ba rủi ro riêng.

Thứ nhất là lỗi giải mã trạng thái mà ershad báo ngày 30/10/2026: mã truyền kích thước phản hồi gồm cả 4 byte header vào `decode_status()`. Lỗi này **vẫn có trong mã ValdikSS năm 2026** (đã kiểm chứng) ([mounaiban PR #55](https://github.com/mounaiban/captdriver/pull/55)).

Thứ hai, suluoniu cho rằng LBP2900 không bao giờ bật bit `XSTATUS_CHNG`, nên mã upstream thăm dò mãi mà không gửi lệnh in (theo nguồn; thử trên Raspberry Pi 4 với Ubuntu 26.10) ([suluoniu README, 01/11/2026](https://github.com/suluoniu/captdriver-lbp2900/blob/f7107828725647cf925f9eb0df05c61b6069d49c/README.md)).

Thứ ba, cũng là nghiêm trọng nhất, là tuyên bố trong toolkit của Bruce Nguyen. Theo đó, fork ValdikSS "reliably wedges" động cơ in của LBP2900 đúng ở lệnh in thứ năm kể từ khi bật máy, với lỗi `ReserveUnit failed (0x8c)`. Nguyên nhân được nêu là backend `usb://` mở và đóng phiên USB theo từng lệnh. Toolkit nói chỉ một daemon giữ phiên USB lâu dài (`captd`) mới chữa được, với kết quả "58 jobs in one power-on session with zero wedges" ([captd README, 07/2026](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/captd-persistent-daemon/README.md)).

Tuyên bố thứ ba đến từ một nhà phát triển, có mã kèm theo, nhưng chưa ai xác nhận độc lập. palashkaria đã mang nó sang nhánh ValdikSS ngày 05/11/2026, và chỉ thử với một máy LBP2900 trên Debian 13 ([palashkaria ee4186a](https://github.com/palashkaria/captdriver/commit/ee4186affae34a7e2da89291da2a7906a7311f2f)). Phần mã daemon gốc từ toolkit, `captd.c` và `capt-backend.c`, **không có giấy phép**: kho không có tệp LICENSE, tệp không có header (đã kiểm chứng) ([GitHub API](https://api.github.com/repos/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit)). Vì thế CaramOS chưa được phân phối phần mã này.

### Đóng gói thì dễ, khó là báo trạng thái và tự nhận driver

Phần build không có gì đáng lo. Mọi nhánh chính (agalakhov, mounaiban master, `0.2.1-pr`, ValdikSS, apocarteres, ershad) build sạch trên Ubuntu 24.04 với GCC 13.3 và 14.2, chỉ vài cảnh báo, và binary chỉ liên kết `libcups.so.2` (đã kiểm chứng). Cái khó nằm ở chỗ khác. `make install` đặt `rastertocapt` vào `/usr/local/bin`, nơi hồ sơ AppArmor của cupsd trên noble chỉ cho đọc chứ không cho chạy. Đó đúng là lỗi `apparmor="DENIED"` đã gặp trên Debian 13 ([mounaiban #50, 24/02/2026](https://github.com/mounaiban/captdriver/issues/50)). PPD thì phải sinh với `LC_ALL=C`, nếu không sẽ gặp lỗi "CAPT: no pages in job" ([AUR captdriver-git, 15/01/2024](https://aur.archlinux.org/packages/captdriver-git)).

Không nhánh nào phát dòng `STATE:` chuẩn của CUPS, nên giao diện không thể báo "hết giấy" hay "kẹt giấy" bằng bất kỳ ngôn ngữ nào. ValdikSS chỉ ghi chuyện hết giấy ở dòng `DEBUG:`, và mọi lỗi người dùng thấy đều là chuỗi tiếng Anh như "ERROR: CAPT: unable to communicate with printer" (đã kiểm chứng).

PPD cũng không có `*1284DeviceID`. Trong một cupsd thử nghiệm, `lpinfo --device-id` với chuỗi ID thật của LBP2900 trả `client-error-not-found`. Bộ so khớp mờ của cupshelpers thì vẫn chọn đúng PPD captdriver, với trạng thái 0 cho `MDL:LBP2900` và trạng thái 1 (lệch mẫu) cho `LBP2900B` (đã kiểm chứng).

Bản in nhạt là phàn nàn có thật. Một người dùng LBP2900 đã quay về driver Canon, vì driver đó có độ đậm 1–5 và in "exactly the same as… on Windows" ([mounaiban #33, bình luận 19/11/2024](https://github.com/mounaiban/captdriver/issues/33)). ValdikSS đã thêm tùy chọn "Darkness", mặc định 7, vào PPD (đã kiểm chứng).

Cuối cùng, bộ lọc không chạy được khi thiếu máy in. Việc đầu tiên nó làm là hỏi backend chuỗi IEEE 1284, và thoát với "unable to communicate with printer" nếu không có (đã kiểm chứng với `cupsfilter`). Vì vậy chưa thể kiểm thử đầu cuối khi chưa có phần cứng hoặc bộ giả lập.

| Tiêu chí | Driver Canon CAPT 2.71 | captdriver (nhánh ValdikSS / `0.2.1-pr`) |
|---|---|---|
| Giấy phép | Phần lõi độc quyền (Schedule 1), không được vào PPA | GPL-3+, hợp lệ cho PPA |
| Cập nhật gần nhất | 15/05/2017, không còn bảo trì | 06/06/2026 (ValdikSS), 13/08/2026 (`0.2.1-pr`); không có bản phát hành nào từ 2020 |
| Thành phần 32-bit | Có: `captfilter`, `captmon2`, thư viện lõi (i386 ~16 MB tải, ~55 MB cài) | Không |
| Đường tới máy in | CUPS → backend `ccp` → `ccpd` → `/dev/usb/lpN` (`usblp`) | `rastertocapt` → backend `usb` (libusb) của CUPS |
| Cần bản vá CUPS #1461 | Không | Có (CUPS ≥ 2.4.17; noble có 2.4.7) |
| Dịch vụ nền | `ccpd` 64-bit chạy bằng root, không có unit systemd | Không cần (trừ chế độ `captd` tùy chọn) |
| Mẫu máy | ~30 mẫu, gồm LBP2900/2900B, LBP3300, LBP6020 | LBP2900 và LBP3010/3018/3050 (WORKS); LBP3000, 3100/3108/3150, 6000/6018 (thử nghiệm); không có LBP3300, LBP6020 |
| Báo hết giấy, kẹt giấy | `captstatusui` (GTK2, không có tiếng Việt) | Không phát `STATE:`; kẹt giấy là hủy lệnh |
| Tự nhận driver khi cắm | Không; hàng đợi `ccp://` phải tạo bằng tay | cupshelpers khớp theo tên với `MDL:LBP2900`; chưa có `*1284DeviceID` |
| Báo cáo trên Ubuntu 24.04 / Mint 22.x | Nhiều người in được sau khi sửa script (2024–2026) | Rời rạc; chưa ai công bố chạy thử nhiều lệnh có hệ thống |
| Nền Ubuntu 26.04 | Hỏng nếu không tự cấp `libxml2.so.2` i386 và `libglade2-0` | Vẫn cần bản vá CUPS (26.04 có 2.4.16) |
| CUPS 3 | Khó có tương lai: dựa vào PPD và một daemon đọc thẳng `printers.conf` (suy luận) | Có thể bọc thành Printer Application |

## Không script cộng đồng nào dùng nguyên được, kể cả script người Việt phổ biến nhất

### Script của hieplpvip là chuẩn trên thực tế và hỏng trên noble

Ngày 08/11/2026, tìm kiếm GitHub trả về 35 kho cho từ "lbp2900" và 53 kho cho "canon capt". Nhưng chỉ có một trình cài cho Ubuntu được dùng rộng rãi: **hieplpvip/ubuntu_canon_printer**, 209 sao, 103 fork, commit cuối ngày 02/10/2020, không có giấy phép ([GitHub search](https://api.github.com/search/repositories?q=lbp2900&sort=stars&order=desc)). Header của script ghi "Version 3.3 updated on September 13, 2019… Translated into English and modified by @hieplpvip". Tức đây là bản dịch script của người dùng coden trên diễn đàn ubuntu.ru ([canon_lbp_setup.sh @2084954](https://github.com/hieplpvip/ubuntu_canon_printer/blob/2084954b00195d8ffbaeb06f3b4d9dd3a0c41430/canon_lbp_setup.sh)). Người duy trì nhiều khả năng là Lê Bảo Hiệp, tác giả bài tinhte năm 2018 trỏ tới chính kho này, nên trình cài LBP2900 phổ biến nhất có gốc Việt. Hai liên kết Google Drive của bản gốc tiếng Nga nay trả 404 ([help.ubuntu.ru/wiki/canon_capt](https://help.ubuntu.ru/wiki/canon_capt)), nên kho này gần như là bản còn sống duy nhất của dòng script đó.

Script có hai điểm tốt. Các tệp .deb nó commit **trùng từng byte với gói của Canon** (đã kiểm chứng), và nó tạo symlink udev theo số serial để tên thiết bị cố định.

Điểm hỏng thì nhiều hơn:

| Vấn đề | Chi tiết |
|---|---|
| Không cài nổi trên noble | Dòng 270 cài `libpango1.0-0:i386`, gói không tồn tại trên noble, và script không chạy `dpkg --add-architecture i386` (đã kiểm chứng bằng chỉ mục gói, không chạy). Ba PR sửa đúng các lỗi đó, trong đó có #30 của tác giả Việt Dương Linh (08/09/2026), nhưng đều chưa được hợp nhất; PR cuối được hợp nhất là #4 năm 2020 ([hieplpvip PR #30](https://github.com/hieplpvip/ubuntu_canon_printer/pull/30)) |
| Hạ AppArmor | Chạy `aa-complain /usr/sbin/cupsd` (dòng 263–265) |
| Ghi đè conffile | Ghi đè `/etc/init.d/ccpd` mà không sao lưu |
| Không kiểm hash | Tải .deb qua đường chuyển hướng của tên kho cũ |
| Lối tắt đặt sai chỗ | Đặt lên `/root/Desktop`, vì đọc thư mục người dùng sau khi đã `sudo` ([hieplpvip #11](https://github.com/hieplpvip/ubuntu_canon_printer/issues/11)) |
| Lặp vô hạn | Chờ cho đủ hai tiến trình `ccpd` |
| Gỡ cài nguy hiểm | Dùng `apt-get -y autoremove` (dòng 119); một người dùng nói lệnh này đã "wiped out EVERYTHING on my machine - Xorg, dns" ([hieplpvip #16, 21/02/2023](https://github.com/hieplpvip/ubuntu_canon_printer/issues/16)) |

Câu trả lời được chấp nhận cho câu hỏi về Ubuntu 24.04 trên Ask Ubuntu (câu hỏi có 7.340 lượt xem) vẫn dựa trên script này, cộng thêm việc đổi tên gói pango và bật `ccpd.service` ([Ask Ubuntu Q1525297, 02/09/2024](https://askubuntu.com/questions/1525297)).

### Lứa công cụ năm 2026 có ý hay nhưng đụng vào toàn hệ thống

Từ giữa 2026 xuất hiện một loạt kho nhỏ, nhiều kho của người Việt. Mỗi kho một kiểu, và chưa kho nào có chỗ đứng (0–19 sao). Toolkit tiếng Việt của brucenguyen1102 (tạo 08/07/2026, script dài 1.970 dòng) build nhánh ValdikSS tại HEAD mà không ghim commit. Nó **thay tệp `/usr/lib/cups/backend/usb` thuộc gói cups-daemon** (có sao lưu và lệnh khôi phục) và mask `ipp-usb`. Nó blacklist `usblp` với lựa chọn mặc định là có, dù chính script cảnh báo việc đó ảnh hưởng mọi máy in USB. Nó còn đặt `LogLevel debug` vĩnh viễn và mở CUPS ra LAN. README của toolkit nhắc tới một GitHub Action làm mới tarball hằng ngày và hai tệp, nhưng cả ba đều không có trong kho ([may-in-lbp2900.sh @4b8c50c](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/4b8c50cfd0bc67423fa68409d9f1141df857fae5/may-in-lbp2900.sh); [README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/4b8c50cfd0bc67423fa68409d9f1141df857fae5/README.md)).

Các kho khác lặp lại những mẫu nguy hiểm khác nhau. beautifulmind tải `libicu74` và `libxml2` qua http rồi `dpkg -i`, bỏ qua chữ ký APT. giddammit-crypto dùng `curl` nối thẳng vào `bash` từ một máy chủ bên thứ ba, kèm `dpkg --force-all`. digital-enterprise-projects bật `FileDevice Yes` và chạy `cupsctl --share-printers --remote-any`. truclk dựng container Docker với mật khẩu root cứng `Printer!` và `Allow all`. vnojiovn chọn máy in USB đầu tiên bất kể hãng, và bọc lệnh build trong `|| true`. rossey cài một binary `rastertocapt` dựng sẵn không rõ nguồn.

Ngay cả những kho làm tốt cũng còn vết. ataoua-sudo lấy thư viện i386 qua APT có `signed-by`, dùng `dpkg-divert` gỡ được, và đặt tên unit là `canon-ccpd.service` để tránh xung đột với script SysV. Nhưng nó vẫn chạy `aa-complain` và có đường lui `--force-depends` ([ataoua-sudo lib/canon.sh](https://github.com/ataoua-sudo/canon-lbp-setup/blob/ca42f38745832e23482ffe0f5cb349d7c6550e2f/lib/canon.sh)). sanhos95 có mẫu đóng gói tốt nhất: một gói `printer-driver-captdriver` với PPD có Device ID, bộ lọc là tệp thật trong `/usr/lib/cups/filter`, và postinst tự tạo hoặc sửa hàng đợi. Nhưng bản phát hành của nó build trên ubuntu-22.04 và không ký ([sanhos95 setup-queues](https://github.com/sanhos95/canon-capt-linux-driver/blob/95f5d55b9a4091650762dcdeee599ce060db7bf0/packaging/setup-queues)).

| Kho (commit cuối) | Cách làm | Vấn đề chính | CaramOS nên học |
|---|---|---|---|
| hieplpvip/ubuntu_canon_printer (02/10/2020, 209 sao) | Canon 2.71, .deb commit sẵn | Hỏng trên noble; `aa-complain`; ghi đè conffile; không kiểm hash; `autoremove` | Symlink udev theo serial |
| tutaecos-vn (31/05/2026, fork của YouTuber TuTaEcos) | Canon 2.71, gỡ bớt Depends rồi đóng gói lại | Vẫn `aa-complain` và `autoremove`; sửa gói của Canon | Bộ i386 tối thiểu |
| brucenguyen1102 toolkit (24/07/2026, 19 sao) | ValdikSS + `captd` + backend `usb` đã vá | Thay tệp của gói cups; mask ipp-usb; blacklist usblp; mở LAN; không ghim mã; không giấy phép | Sao lưu và khôi phục |
| ataoua-sudo/canon-lbp-setup (19/10/2026) | Driver mở cho 2900/3000, driver Canon cho mẫu khác | `aa-complain`; `--force-depends` | Unit tên riêng, APT `signed-by`, `dpkg-divert`, tắt autosuspend USB |
| sanhos95/canon-capt-linux-driver (04/11/2026) | Gói `printer-driver-captdriver` | Bản phát hành không ký, build trên 22.04 | Mẫu gói, PPD có Device ID, `setup-queues` |
| digital-enterprise-projects/LBP2900 (23/08/2026) | mounaiban + bản vá ghi thẳng ra thiết bị | `FileDevice Yes`, `--remote-any` | Build ghim commit, kèm tệp `.sha256` |
| giddammit-crypto (01/10/2026) | Canon 2.71 cho Astra Linux | `curl` nối thẳng vào `bash`; `--force-all`; cổng 59787; luật udev cho mọi thiết bị Canon | Không có gì |
| beautifulmind/lbp2900 (20/04/2026) | Canon 2.71 qua một fork | Tải http rồi `dpkg -i`; gói giả `libglade2-0` | Không có gì |

### Hướng dẫn tiếng Việt vẫn xoay quanh bài tinhte năm 2018

Hệ sinh thái tiếng Việt xoay quanh bài "CÀI DRIVER MÁY IN DÒNG CANON LBP CHO UBUNTU" của Lê Bảo Hiệp (22/04/2018). Bài này nói LBP2900 rất phổ biến ở Việt Nam vì máy và mực rẻ, rồi chỉ người đọc tới script kể trên. Một bình luận năm 2023 tóm tắt: "Canon 2900 trên Ubuntu 18.04 là tốt nhất, còn với bản 22.04 và 22.10 thì thua. Cài xong hoạ may in test duoc 1 lần rồi què luôn" ([tinhte.vn](https://tinhte.vn/thread/cai-driver-may-in-dong-canon-lbp-cho-ubuntu.2787611/)).

Video của TuTaEcos (25/08/2024) dặn chưa cắm cáp USB cho tới khi chạy xong lệnh, và trỏ người dùng 24.04 sang fork riêng ([YouTube, TuTaEcos](https://www.youtube.com/watch?v=BwKxpXYpiNA)). Các video năm 2026 phần lớn không có mô tả. Một video "Cài Máy In Canon Trên Mint OS" thực ra nói về Canon 6030, một mẫu UFR II LT chứ không phải CAPT ([YouTube, Dzung Vu, 08/07/2026](https://www.youtube.com/watch?v=IAYO6Nhm9GY)).

Trên voz.vn, một câu hỏi năm 2022 về LBP2900 trên Ubuntu không có lời giải ([voz.vn t.626249](https://voz.vn/t/giup-do-cai-driver-canon-lbp-2900-tren-ubuntu.626249/)). Một chủ đề năm 2023 về máy chủ in thì cho thấy nhu cầu thật của văn phòng: chia sẻ một chiếc 2900 qua LAN. Ở đó có người nhận xét rằng CUPS "chỉ in ổn định cho giấy A4, in giấy A5 cực chuối" ([voz.vn t.810006](https://voz.vn/t/vao-choi-he-dieu-hanh-tam-10mb-lam-server-hay-may-chu-luu-tru-print-server-canon-2900-nao-anh-em-oiii-d.810006/)). Hướng dẫn Raspberry Pi của namvu.net (25/07/2021) mở CUPS bằng `Allow all` cho cả `/admin` ([namvu.net](https://namvu.net/2021/07/setup-a-family-printer-with-a-raspberry-pi-1-and-canon-lbp-2900/)). README của Huylighting (18/10/2026) đã liệt kê CaramOS trong các hệ được hỗ trợ ([Huylighting README](https://github.com/Huylighting/Linux-Print-server/blob/1536a9f8436e6315f5444d2ba172aff3a441f23c/README.md)).

Các nguồn kinh điển mà hướng dẫn cũ dẫn tới đã chết. Trang Canon CAPT trên help.ubuntu.com nay chuyển tới một trang wiki trống, và bản lưu trữ tự ghi "Do not use them as documentation" ([ubuntu/wiki-archives](https://github.com/ubuntu/wiki-archives)). ubuntuforums.org không phân giải được DNS từ máy nghiên cứu ngày 08/11/2026. Ngay chủ đề HOWTO hơn một triệu lượt xem trên forum.ubuntu.ru nay cũng mở đầu bằng liên kết tới captdriver ([forum.ubuntu.ru topic 189049](https://forum.ubuntu.ru/index.php?topic=189049.0)). Khoảng trống này là cơ hội của CaramOS. Một con đường do CaramOS bảo trì, bằng tiếng Việt, có thể thay những chỉ dẫn vốn đã hỏng trên noble nếu không sửa tay.

## Giấy phép Canon chặn đường PPA, dù EULA cho chuyển giao bản nguyên vẹn

### Canon có hai văn bản, và chúng nói hai điều khác nhau

Hai ghi chú nghiên cứu bất đồng ở câu hỏi EULA có cho phân phối lại bản nguyên vẹn hay không. Câu trả lời nằm ở chỗ Canon có hai văn bản chứ không phải một. EULA trong gói (`Doc/LICENSE-EN.txt`, đã kiểm chứng trong gói) định nghĩa "Product" là "this Canon's printer driver for Linux provided to you together with this Agreement", và "Software" là các chương trình trong Schedule 1 ([tệp của Canon](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)). Điều 1 và điều 2 viết:

> "Canon grants you a personal, limited and non-exclusive license to use…, have used, copy, have copied, distribute and permit third parties to use and copy the Software only on the Product. You may modify the Software only for your own use… You shall distribute the Software to any third party under the same terms and conditions as contained herein."
>
> "Except as expressly granted or permitted herein, you shall not use, assign, sublicense, sell, rent, lease, loan, convey or transfer to any third party the Software."

Schedule 1 là phần độc quyền, và nó chứa đúng những thứ không thể thiếu: `ccpd`, `ccpdadmin`, `captfilter`, `captmon*`, các thư viện lõi, `ccpd.conf` và script khởi động. Schedule 2 (GPL v2) gồm backend `ccp`, `pstocapt*`, `captstatusui`, `cngplp`, `cnusb` và các PPD. Schedule 3 (kiểu MIT) gồm `libcanoncapt`, `libcanonc3pl` và `buftool`.

Văn bản thứ hai là điều khoản trên trang tải. Người dùng phải chấp nhận nó thì mới tải được ([Canon Asia](https://asia.canon/en/support/0100459601)):

> "You may download and use the Content solely for your personal, non-commercial use… You shall not distribute, assign, license, sell, rent, broadcast, transmit, publish or transfer the Content to any other party. You shall also not… reproduce, modify, reformat… or create derivative works from the Content… By proceeding to downloading the Content, you agree to be bound by the above."

Trang Canon Việt Nam có cùng nội dung: tải về "chỉ cho mục đích sử dụng cá nhân, phi thương mại", và "Bạn không được phân phối, chuyển nhượng, cấp phép, bán, cho thuê…" ([Canon Việt Nam](https://vn.canon/vi/support/0100459601)). Phía Launchpad, nội dung được lên PPA nếu "approved by Canonical or released under a license" thuộc nhóm OSI, FSF, DFSG, tuân thủ chính sách giấy phép main/restricted của Ubuntu, hoặc một số giấy phép Creative Commons. Giấy phép khác phải hỏi đội Launchpad trước khi tải lên ([Launchpad policies](https://ubuntu.com/docs/launchpad/user/reference/launchpad-and-community/legal/launchpad-policies/)).

### Quyền hẹp trong EULA bị ba lớp chặn chồng lên

Nếu đọc riêng EULA, ghi chú tích hợp đúng một phần. "Product" là nguyên gói driver kèm thỏa thuận, nên cụm "only on the Product" cho phép chuyển phần mềm độc quyền cho người khác **chỉ khi nó đi trong nguyên gói của Canon, kèm nguyên điều khoản, không thu tiền** ("sell" bị cấm) và không sửa đổi. Nhưng quyền hẹp đó bị ba lớp chặn lại.

Thứ nhất, mọi cách đóng gói có ích cho CaramOS đều là sửa đổi: thêm phụ thuộc i386, sửa vòng `kill -9`, nhét unit systemd vào gói. EULA chỉ cho sửa "for your own use", còn điều khoản tải cấm "reformat" và "derivative works".

Thứ hai, người duy trì CaramOS chỉ có được tarball bằng cách tải từ trang Canon, tức là đã đồng ý "shall not distribute… publish… the Content". Hai văn bản mâu thuẫn nhau, và trong những gì được trích, không văn bản nào có điều khoản ưu tiên. Cách đọc thận trọng là văn bản chặt hơn trói buộc người tải.

Thứ ba, Launchpad chỉ nhận gói nguồn, nên binary độc quyền phải nằm trong gói nguồn và chính Launchpad sẽ phân phối nó. Ngay tarball `Src/` của Canon cũng chứa thư viện 32-bit dựng sẵn (đã kiểm chứng). Mà EULA của Canon không thuộc nhóm giấy phép nào Launchpad nhận nếu không có Canonical duyệt.

Kết luận: **CaramOS không được đưa driver Canon lên PPA, dù nguyên bản hay đã đóng gói lại, và cũng không nên tự mirror tarball trên máy chủ hay GitHub của mình.** Phần GPL (Schedule 2) thì được phân phối theo GPL v2, nhưng vô dụng nếu thiếu `ccpd` và `captfilter`.

| Hình thức | EULA trong gói | Điều khoản tải | Launchpad | Kết luận |
|---|---|---|---|---|
| Đưa nguyên gói của Canon lên PPA | Có thể cho, nếu nguyên gói, kèm EULA, không thu tiền | Cấm | Ngoài danh sách; cần Canonical duyệt | Không |
| Đóng gói lại (thêm Depends i386, sửa script, thêm unit) rồi đưa lên PPA | Cấm (chỉ được sửa "for your own use") | Cấm ("reformat", "derivative works") | Như trên | Không |
| Mirror tarball nguyên vẹn trên máy chủ hay GitHub của CaramOS | Có thể cho | Cấm | Không liên quan | Không nên |
| Chỉ phân phối phần GPL (Schedule 2) | Cho, theo GPL v2 | Mâu thuẫn ("publish") | Hợp lệ | Hợp lệ nhưng vô dụng |
| Máy người dùng tự tải từ Canon, CaramOS kiểm hash và cài nguyên vẹn | Người dùng nhận giấy phép trực tiếp | Người dùng tự chấp nhận | Gói của CaramOS chỉ chứa mã CaramOS | Nên làm |

### Trình tải là đường hợp lệ, và đã có tiền lệ

Con đường hợp lệ là trình tải. Máy người dùng tải tarball thẳng từ Canon khi người dùng yêu cầu. Người dùng tự đọc và tự chấp nhận điều khoản của Canon. CaramOS kiểm kích thước và SHA-256, rồi cài hai gói amd64 mà không sửa. Mọi "lớp bọc" đều là tệp CaramOS tự viết, nên được nằm trong PPA hoặc App Center.

Tiền lệ có sẵn. Ubuntu có `ttf-mscorefonts-installer` trong multiverse, một gói nhỏ tải phông của Microsoft lúc cài ([packages.ubuntu.com](https://packages.ubuntu.com/noble/ttf-mscorefonts-installer)). AUR `capt-src` (80 phiếu, có từ 29/08/2010) tải đúng tarball này từ URL của Canon trên máy người dùng, kiểm `b2sums`, và cài kèm `LICENSE-EN.txt` ([AUR capt-src](https://aur.archlinux.org/packages/capt-src)). SlackBuilds cũng chỉ là script build, nhưng nó lấy tarball mã nguồn của Canon từ một mirror bên thứ ba (`mirror.slackware.hr`), giống từng byte với bản của Canon ([SlackBuilds cndrvcups-capt.info](https://slackbuilds.org/slackbuilds/15.0/system/cndrvcups-capt/cndrvcups-capt.info)).

Cũng có phản ví dụ cần nói rõ. ROSA đưa `cndrvcups-capt` 2.71 vào kho của họ ([Repology cndrvcups-capt](https://repology.org/api/v1/project/cndrvcups-capt)). PPA `michael-gruz/canon` trên Launchpad vẫn công khai `cndrvcups-capt` 2.20, đóng gói lại cho Ubuntu 10.04–11.04 và tải lên năm 2011 (đã kiểm chứng qua API Launchpad ngày 08/11/2026) ([Launchpad, michael-gruz/canon](https://launchpad.net/~michael-gruz/+archive/ubuntu/canon/+packages)). Các ví dụ này cho thấy việc đó làm được về kỹ thuật và có thể tồn tại lâu mà không ai gỡ. Nhưng chúng không chứng minh là được phép, và chưa ai kiểm tra cơ sở của họ.

Công thức `ms-fonts` của App Center hiện chấp nhận EULA thay người dùng ("CaramOS accepts it here for the user who chose the fonts") ([recipes/ms-fonts](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/usr/share/caramos-app-center/recipes/ms-fonts)). Với Canon, điều khoản tải trói buộc chính người tải. Vì vậy công thức nên hiện nguyên văn EULA và điều khoản tải, rồi chờ người dùng bấm đồng ý (suy luận).

### Những điểm pháp lý vẫn còn bỏ ngỏ

Báo cáo không có ý kiến luật sư, không có tuyên bố nào của Canon về việc phân phối lại, và chưa phân tích luật Việt Nam. Vì thế vẫn còn bảy điểm chưa chắc:

| Điểm chưa chắc | Vì sao còn bỏ ngỏ |
|---|---|
| Quan hệ giữa EULA và điều khoản tải | Một tòa án có thể cho rằng EULA điều chỉnh phần mềm, còn điều khoản trên trang chỉ điều chỉnh hành vi tải. Theo cách hiểu đó, mirror tarball nguyên vẹn có thể hợp lệ. |
| Cụm "personal, non-commercial use" với doanh nghiệp | Đọc theo nghĩa đen, điều khoản loại trừ cả doanh nghiệp như công ty 15 máy trên VNLF. Gần như chắc chắn Canon không định cấm văn phòng dùng driver máy in văn phòng, nhưng văn bản ghi như vậy. Rủi ro này rơi vào từng người dùng, có CaramOS hay không (suy luận). |
| Cơ sở của ROSA và của PPA `michael-gruz` | Chưa ai kiểm tra. Bản 2.20 năm 2011 cũng có thể đi kèm điều khoản khác. |
| Nhóm giấy phép "main/restricted" của Launchpad | Chưa ai đối chiếu với EULA của Canon. Kể cả nếu qua được, điều khoản tải vẫn còn đó. |
| Đường xin phép Canon | Cách sạch duy nhất để tự phân phối tệp của Canon là có văn bản cho phép của Canon Singapore (bên đăng trang Asia) hoặc Canon Marketing Việt Nam, cộng sự chấp thuận của Launchpad. Cả hai đều khó nhanh. |
| Nguồn gốc mã captdriver năm 2026 | README của ValdikSS nói công việc năm 2026 dựa trên dịch ngược `captmon2` và `captfilter` của Canon, điều mà điều khoản tải cấm. Nhưng mã đó không phải mã của Canon, và captdriver đã được nixpkgs, Gentoo GURU, ALT, ROSA, OpenMandriva đóng gói nhiều năm, nên rủi ro cho CaramOS có vẻ thấp (suy luận). |
| Giấy phép của bản sao backend USB | Nếu CaramOS đóng gói một bản sao backend `usb` đã vá, bản sao phải theo giấy phép CUPS. Ghi chú nói đó là Apache-2.0 kèm ngoại lệ, nhưng chưa ai đọc văn bản. |

## CaramOS nên xây gì, xếp theo công sức và giá trị

Mỗi script cộng đồng sửa một khớp nối và làm gãy khớp khác. CaramOS thì sở hữu cả chuỗi. Driver Check phát hiện phần cứng. App Center cài phần mềm có giấy phép riêng, và phát hành độc lập qua GitHub Release có ký, được kiểm tra trong lần OTA hằng ngày. PPA chứa phần GPL và lớp bọc. OTA lo phân phối và sửa chữa.

Nhu cầu cũng có thật. Issue #39 "tích hợp driver máy in canon 2900 3300" mở ngày 20/05/2026, vẫn nằm trong Backlog, và bình luận duy nhất (13/10/2026) viết "Tích hợp như nào ms là vấn đề" ([CaramOS #39](https://github.com/VN-Linux-Family/CaramOS/issues/39)). Một doanh nghiệp hai cơ sở, khoảng 15 máy, muốn cài CaramOS và đang dùng "canon lp2900" ([VNLF, 28/10/2026](https://vietnamlinuxfamily.net/a/chao-anh-chi-a-hien-tai-ben-em-kinh-doanh-thuong-mai-hien)). Máy đã ngừng kinh doanh ở Thế Giới Di Động sau 1,4 nghìn lượt bán ([thegioididong.com](https://www.thegioididong.com/may-in/may-in-laser-canon-lbp2900)), nhưng vẫn được mua bán cũ rất nhiều với giá khoảng 1,5–2,3 triệu đồng ([Chợ Tốt, Q4 TP.HCM](https://www.chotot.com/mua-ban-do-dung-van-phong-quan-4-tp-ho-chi-minh/133910578.htm)).

### Có máy in thật trước khi viết phần khó

Mọi khuyến nghị dưới đây đều cần ít nhất một lần chạm phần cứng thật. Vì thế việc rẻ nhất mà cũng đáng nhất là **mua một chiếc LBP2900 cũ**. HACOM từng niêm yết máy cũ có bảo hành ba tháng giá 1.599.000 đồng, nay hết hàng ([hacom.vn](https://hacom.vn/may-in-canon-2900-cu-xuoc-khong-vo-hop)). Chợ Tốt còn nhiều tin rao. Nếu muốn đóng trọn issue #39 thì mua thêm một LBP3300. Nên mời doanh nghiệp trên VNLF làm người dùng thử.

Lần cắm đầu tiên cần ghi lại bốn thứ:

| Việc cần ghi | Để trả lời câu hỏi gì |
|---|---|
| `lsusb -v` | Lớp giao diện có đúng 07/01/02 như giả định không, và máy có số serial dùng được cho udev không |
| Chuỗi IEEE 1284 của một máy 2900B | Chuỗi này hiện mới được giả định là giống 2900 |
| Điều CaramOS 1.3.6 làm khi cắm máy | Hiện thông báo "Missing printer driver" của `csd-printer`, hay tự tạo hàng đợi với một driver PostScript không liên quan như sanhos95 kể trên Mint 22 ([sanhos95 README](https://github.com/sanhos95/canon-capt-linux-driver)) |
| Bản ghi `usbmon` khi in bằng driver Canon | Làm dữ liệu chuẩn cho kiểm thử về sau |

### Driver Check đang im lặng trước LBP2900

`_other()` trong Driver Check chỉ báo một thiết bị USB khi không giao diện chuẩn nào của nó có driver. Lớp máy in `07` lại nằm trong `USB_STANDARD_CLASSES`. Vì `usblp` đã nhận giao diện máy in, một chiếc LBP2900 hoàn toàn vô hình với Driver Check (đã kiểm chứng bằng đọc mã) ([analysis.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/analysis.py); [hardware.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/hardware.py)).

Phần sửa nằm gọn trong kiến trúc hiện có. Thêm một bảng ID máy in CAPT (vendor `04a9`) vào `knowledge.py`, tệp vốn được giữ nhỏ có chủ đích. Thêm một vùng `printer` vào `AREAS`, và một bước `_printers()` chạy trước `_other()`. ID `2676` của LBP2900/2900B được hai nguồn độc lập xác nhận: usb.ids, và một `lsusb` thật trên LBP2900B năm 2012 ([Launchpad Answers #196221](https://answers.launchpad.net/ubuntu/+source/cups/+question/196221)). Các ID khác lấy từ usb.ids (bản 26/06/2026) và danh sách của studycapt, mà danh sách này có thể đã chép từ usb.ids ([usb.ids](http://www.linux-usb.org/usb.ids); [mounaiban/studycapt](https://github.com/mounaiban/studycapt)).

| USB ID | Mẫu (theo usb.ids) | captdriver | Driver Canon 2.71 |
|---|---|---|---|
| `04a9:2676` | LBP2900 / LBP2900B | WORKS | Có |
| `04a9:267e` | LBP3300 | Không | Có |
| `04a9:26da` | LBP3010/3018/3050 | WORKS | Có |
| `04a9:266a` | LBP3000 | Thử nghiệm | Có |
| `04a9:26db` | LBP3100/3108/3150 | Thử nghiệm | Có |
| `04a9:271a` | LBP6000/6018 | Thử nghiệm | Có |
| `04a9:2771` | LBP6020 | Không | Có |

Khi chưa có driver, Driver Check nên báo bằng tiếng Việt, chẳng hạn "Máy in Canon LBP2900 cần driver CAPT". Hành động đi kèm dẫn tới công thức App Center cho driver Canon, hoặc tới gói captdriver khi gói này đã được kiểm chứng. Khi driver đã có, Driver Check kiểm xem hàng đợi đã đúng chưa (`ccp://` với PPD Canon, hoặc PPD captdriver), và đề xuất "Sửa máy in" nếu hàng đợi bị tạo sai.

Driver Check cũng nên tìm dấu vết các script cộng đồng để lại, rồi đề xuất khôi phục. Đó là cupsd đang ở chế độ complain (`aa-status`), `ipp-usb` bị mask, tệp của gói cups bị thay (`dpkg --verify cups-daemon`), `LogLevel debug` để vĩnh viễn, và dòng blacklist `usblp`. Lời giải thích hiện có về dòng blacklist phải được xử lý riêng cho máy CAPT.

Driver Check chỉ chạy lúc đăng nhập hoặc khi được mở. Vì thế máy in cắm sau đó cần một cú hích, chẳng hạn một luật udev dùng `SYSTEMD_WANTS`, hoặc tận dụng thông báo sẵn có của `csd-printer`. `SystemReader(root=…)` đã cho dựng cây sysfs giả, nên cả phần này kiểm thử được mà không cần máy in. Công sức thấp, khoảng vài ngày (suy luận), và phát hành qua bản caramos-ota kế tiếp.

### Công thức App Center cho driver chính hãng là đường nhanh nhất để đóng issue #39

App Center đã có cơ chế `recipe`. Đó là script chạy bằng root qua pkexec, kèm các hàm `download` (HTTPS, có thử lại và tải tiếp), `install_deb` và `remove_packages`. Bài kiểm thử chặn URL `http://`, và công thức Zalo đã có tiền lệ kiểm SHA-256 ([common.sh](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/usr/share/caramos-app-center/recipes/lib/common.sh); [App Center README](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/README.md)). App Center không phát hiện phần cứng, nên nếu đứng một mình, thẻ máy in sẽ hiện cho mọi người. Vì vậy Driver Check nên là cửa vào, còn công thức là động cơ cài đặt. Công thức nên đặt tên như `canon-capt`, để tránh hai chuỗi "ccpd" và "captmon", và làm theo trình tự sau (thiết kế đề xuất, chưa thử):

| Bước | Việc | Lý do |
|---|---|---|
| 1 | Hiện nguyên văn EULA và điều khoản tải của Canon, chờ người dùng đồng ý | Điều khoản trói buộc chính người tải |
| 2 | Tải từ trang chuyển hướng của Canon (`pdisp01…WWUFORedirectTarget.do?id=MDEwMDAwNDU5NjA1`) hoặc URL `gdlp01` qua HTTPS; kiểm 127.521.219 byte và SHA-256 | Canon có thể dời tệp; mã ghim biến thay đổi âm thầm thành lỗi rõ ràng |
| 3 | Dừng sạch `ccpd` và `captmon*` | Tránh vòng `kill -9` cắt sai PID |
| 4 | Cài `libc6:i386 libpopt0:i386 libxml2:i386 zlib1g:i386 libstdc++6:i386 libgcc-s1:i386`, `libglade2-0` và hai gói amd64 của Canon qua APT, không sửa gói | Đủ cho phần lõi 32-bit; giữ nguyên gói như giấy phép đòi hỏi |
| 5 | Unit systemd tên riêng: `Type=forking`, `ExecStart=/usr/sbin/ccpd`, `After=`/`Wants=cups.service`, `Restart=on-failure`, `WantedBy=multi-user.target printer.target`; cố ý vô hiệu đường SysV thay vì ghi đè `/etc/init.d/ccpd` | Tên riêng tránh lỗi "Default-Start contains no runlevels" mà ataoua-sudo ghi lại |
| 6 | Luật udev tạo symlink cố định, ví dụ `/dev/usb/lbp2900`, theo VID/PID và serial, gắn `TAG+="systemd"` và `SYSTEMD_WANTS` để khởi động lại dịch vụ khi nút thiết bị xuất hiện lại | Thay cho `RUN+=systemctl` và cho `/dev/usb/lp0` dễ đổi số |
| 7 | Tệp `/usr/share/cups/usb/caramos-capt.usb-quirks` với `0x04a9 0x2676 blacklist` và các ID CAPT khác | Backend `usb` không tách `usblp` và không tự tạo hàng đợi `usb://` |
| 8 | `lpadmin -p LBP2900 -P /usr/share/cups/model/CNCUPSLBP2900CAPTK.ppd -v ccp://localhost:59687 -E`, rồi `ccpdadmin -p LBP2900 -o /dev/usb/lbp2900` | `ccpd.conf` đòi cùng một tên hàng đợi; cổng 59687 theo tài liệu Canon |
| 9 | Xóa mọi hàng đợi `usb://` của thiết bị, đặt khổ A4, tùy chọn thêm lối tắt `captstatusui` | Dọn hàng đợi sai mà udev có thể đã tạo |

Khi gỡ, công thức xóa hàng đợi, chạy `ccpdadmin -x`, purge hai gói và gỡ lớp bọc, không gọi `autoremove`. Không bao giờ chạy `aa-complain`; chỉ thêm một luật AppArmor cục bộ hẹp nếu thật sự thấy bị từ chối. `ccpd` chạy bằng root và, theo `ccpd.conf`, dùng hai cổng 59687 và 59787. Cần kiểm bằng `ss -ltnp` xem nó chỉ nghe trên loopback hay nghe ra mạng (chưa kiểm chứng), vì một daemon đóng mã từ 2017 nghe trên LAN là điều không nên để mặc định.

Công sức ở mức trung bình, khoảng 1–2 tuần kể cả thử trong VM, còn bước cuối cần máy thật (suy luận). Giá trị cao, vì đường này phủ LBP2900/2900B, LBP3300 và khoảng 30 mẫu khác. Bản sửa, chẳng hạn khi Canon đổi URL, đi theo bản phát hành App Center chứ không phải chờ bản CaramOS.

### Gói captdriver trong PPA cần một backend USB mang tên riêng

Gói `printer-driver-captdriver` nên lấy nhánh `0.2.1-pr` ở commit `f2d2da8` (hoặc master sau khi mounaiban hợp nhất), cộng PR #55. `debian/copyright` ghi tên Alexey Galakhov (2013), Alexei Gordeev (2016), Moses Chong (2020–2022), Vitaliy Tomin và những người đóng góp năm 2026, tất cả theo GPL-3+. Bộ lọc nằm trong `/usr/lib/cups/filter`. PPD sinh với `LC_ALL=C` và có `*1284DeviceID: "MFG:Canon;MDL:LBP2900;CMD:CAPT;"` cùng các dòng tương tự cho mẫu khác, không đưa trường `VER` hay `DES` vào.

Gói nên có thêm một header `Modaliases:` khớp `usb:v04A9p2676…`. Helper của Driver Check chỉ cài gói nào vừa được ubuntu-drivers khớp với phần cứng, vừa nằm trong `ONE_CLICK` (đã kiểm chứng bằng đọc mã) ([helper.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/helper.py)). Nhờ header này cộng một dòng thêm vào `ONE_CLICK`, gói đi qua đường cài một chạm sẵn có mà không cần thêm logic tin cậy mới. Gói cũng nên phát các dòng `STATE:` chuẩn (`media-empty-error`, `media-jam-error`, `door-open-error`), để CUPS và màn hình nền tự dịch thông báo. Cuối cùng, gói nên đặt sẵn `printer-error-policy` và kèm một script `setup-queues` kiểu sanhos95 để tạo hoặc sửa hàng đợi.

Với lỗi #1461, CaramOS có ba lựa chọn:

| Lựa chọn | Hệ quả | Đánh giá |
|---|---|---|
| Build lại cả cups trong PPA | Che bản vá bảo mật của Ubuntu. CaramOS phải hợp nhất lại mỗi lần noble cập nhật cups (đã tới `ubuntu7.14`), nếu không bản của Ubuntu sẽ âm thầm đè mất bản sửa | Không nên |
| Ghi đè hoặc `dpkg-divert` backend `usb` gốc | Ghi đè thì bị bản cập nhật kế tiếp gỡ mất; divert thì đóng băng luôn các bản vá bảo mật | Không nên |
| Bản sao `usb-libusb.c` cộng PR #1500, đặt thành backend riêng (ví dụ lược đồ `captusb://`; phải sửa chút mã vì backend gốc in URI `usb://`), kèm quirk blacklist các ID CAPT cho backend gốc | Cách captppd đã làm với `captusb://` và `capt.usb-quirks` ([darkvision77/captppd](https://github.com/darkvision77/captppd)); CaramOS chỉ phải theo dõi bản vá bảo mật cho một tệp | **Nên làm** |

Song song, nên gửi yêu cầu SRU lên Launchpad để noble (và 26.04) nhận bản vá #1461. Nếu được chấp nhận thì bỏ bản sao. Còn một điều chưa thử: `udev-configure-printer` có chịu tạo hàng đợi với URI `captusb://` hay không. Nếu không, `setup-queues` là đường lui.

Chế độ `captd` giữ phiên USB chỉ nên thêm khi hai điều kiện cùng đúng. Một là lỗi treo ở lệnh thứ năm tái hiện được trên máy của CaramOS. Hai là Bruce Nguyen (người Việt, liên hệ được qua GitHub) cấp quyền GPL-3+ cho mã daemon; nếu không thì phải tự viết lại. Gói chỉ nên làm mặc định cho LBP2900 sau một đợt chạy thử dài trên cùng một máy, so với driver Canon. Đợt thử gồm 30–60 lệnh in: lệnh đầu tiên sau khi bật máy, hết giấy giữa chừng, lệch Letter/A4, PDF phức tạp, hủy giữa trang, và đánh thức máy khỏi chế độ ngủ. Công sức ở mức trung bình đến cao, khoảng 2–4 tuần cộng thời gian thử (suy luận). Giá trị dài hạn cao: không cần 32-bit, cắm là chạy, và là đường duy nhất sang CUPS 3.

### Hàng đợi tự tạo và chia sẻ máy in trong văn phòng

Đọc mã Mint 22.3 cho thấy chuỗi sự kiện khi cắm máy in ([udev-add-printer](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/udev-add-printer)). `usblp` nhận máy, rồi `configure-printer@` chạy. `udev-add-printer` hỏi cupshelpers và chỉ tạo hàng đợi khi khớp chính xác (trạng thái 0). Sau đó nó gọi `NewPrinter` của `csd-printer`. Bước này hoặc hiện "Missing printer driver", hoặc tự cấu hình qua `GetBestDrivers`; nhánh nào xảy ra thì chưa thử. Với gói captdriver có `*1284DeviceID`, việc khớp chính xác sẽ tự tạo hàng đợi tên "LBP2900". Với driver Canon thì ngược lại: phải chặn việc tự tạo hàng đợi bằng quirk, và để công thức tự tạo hàng đợi `ccp://`.

Nhu cầu đặc trưng của văn phòng Việt Nam là chia sẻ một chiếc 2900 cho cả phòng. CaramOS nên có lựa chọn chủ động kiểu "Chia sẻ máy in này trong mạng nội bộ". Lựa chọn này chỉ mở cho LAN: không `--remote-any`, không `Allow all`, không bật debug vĩnh viễn.

Máy Windows nên thêm hàng đợi CUPS qua IPP với driver IPP có sẵn của Windows. Không nên dùng driver CAPT của Canon trỏ vào hàng đợi CUPS, vì cách đó kẹt ở "Sending data to printer" ([agalakhov #36, 30/12/2025](https://github.com/agalakhov/captdriver/issues/36#issuecomment-3699579108); [agalakhov #17, 16/02/2018](https://github.com/agalakhov/captdriver/issues/17)). Các script `.bat` và `.ps1` trong toolkit của Bruce Nguyen là mẫu tham khảo.

Cần thử riêng việc in mẫu biểu khổ A5, theo phàn nàn trên voz. Cũng cần xác nhận khổ mặc định của CaramOS là A4, vì lệch Letter/A4 từng gây trang trắng và kẹt lệnh ([agalakhov #56, 01/10/2022](https://github.com/agalakhov/captdriver/issues/56#issuecomment-1264366085)). Một bài trên VNLF cho rằng bản cập nhật Windows 10/11 mới làm hỏng việc in trên máy CAPT ([VNLF, 30/10/2026](https://vietnamlinuxfamily.net/a/hom-qua-moi-biet-la-neu-update-windows-10-11-len-moi-nhat)). Nếu đúng, một máy chủ in chạy CaramOS càng có giá, nhưng chưa có nguồn gốc nào xác nhận chuyện này.

### Bốn tầng kiểm thử khi chưa có máy in

Phần lớn việc kiểm thử làm được trước khi có máy. Chỉ những gì chạm tới giấy và động cơ in mới phải chờ máy thật.

| Tầng | Cần gì | Chứng minh được | Không chứng minh được |
|---|---|---|---|
| 1. CI, container | Không cần phần cứng | Build, `cupstestppd`, có `*1284DeviceID` đúng MDL, cupshelpers trả trạng thái 0 trong một cupsd tạm, Driver Check với sysfs giả, App Center với helper giả | Mọi thứ sau bước raster |
| 2. Backend giả | Harness Python giữ fd 3 làm back channel và fd 4 làm side channel, trả chuỗi 1284 ID và phản hồi CAPT soạn sẵn | Đường raster và nén của `rastertocapt`; giải mã đầu ra bằng `captdefilter` hoặc `captstream.py` rồi so với ảnh chuẩn | Hành vi thật của máy; độ trung thực phụ thuộc phản hồi soạn sẵn |
| 3. VM tích hợp | Máy in thật chuyển vào VM (QEMU `usb-host` hoặc usbip), hoặc gadget `g_printer` trên một bo có USB OTG như Pi Zero, vì kernel Ubuntu không có `dummy_hcd` | Cả chuỗi cắm máy: `70-printers.rules`, `configure-printer@`, `udev-add-printer`, `csd-printer`, Driver Check, không sinh hàng đợi trùng | In thật, nếu gadget chưa có bộ trả lời CAPT |
| 4. Bản ghi tham chiếu | Một máy LBP2900, `usbmon` và Wireshark với `capt.lua` | Dữ liệu thật cho tầng 2 | Không áp dụng |

Nguồn cho bảng: [captdriver](https://github.com/mounaiban/captdriver), [studycapt](https://github.com/mounaiban/studycapt), [QEMU USB](https://www.qemu.org/docs/master/system/devices/usb.html), [kernel gadget_printer](https://docs.kernel.org/usb/gadget_printer.html).

studycapt có một mẹo đáng giá: đường ống `gs -sDEVICE=pgmraw … | captfilter … | captstream.py` chạy `captfilter` 32-bit của Canon mà không cần máy in. Nhờ đó có thể kiểm ngay trên CaramOS rằng bộ thư viện i386 tối thiểu đủ để phần lõi của Canon nạp và chạy. Ở tầng 3, dự án dùng lại được vòng VM libvirt và snapshot đang dùng để thử OTA, chỉ cần chuyển USB của máy in vào VM. Chỉ máy thật mới chứng minh được chất lượng bản in và độ đậm, tốc độ và độ trễ giữa trang, phục hồi khi hết giấy, kẹt giấy hay mở nắp, hành vi qua nhiều lệnh liên tiếp (lỗi lệnh thứ năm), đánh thức khỏi chế độ ngủ, và khác biệt giữa LBP2900 với LBP2900B.

### CUPS 3 và Printer Application là việc của nền kế tiếp

Bài nói của OpenPrinting ngày 29/08/2026 nêu lộ trình như sau ([talk-openprinting-2026.pdf](https://events.canonical.com/event/154/contributions/1013/attachments/535/865/talk-openprinting-2026.pdf)). CUPS 2.5 beta1 ra "in the coming weeks". Các thành phần CUPS 3 phát hành xong vào khoảng tháng 1–2/2027. Ubuntu có thể chuyển hẳn sang CUPS 3 ở bản 27.10, còn bản 27.04 thì rất sát mốc đó. Hỗ trợ PPD sẽ bị gỡ, nên máy in cũ cần Printer Application.

`lpadmin` của noble cũng đã cảnh báo "Printer drivers are deprecated and will stop working in a future version of CUPS" (đã kiểm chứng). Mint ghim `snapd` ở mức -10 ([nosnap.pref](file:///home/dungleviet/Documents/CaramOS/build/cache/etc/apt/preferences.d/nosnap.pref)), nên CaramOS sẽ phải đóng gói Printer Application dạng .deb. pappl-retrofit hỗ trợ bộ lọc và backend dùng side channel và back channel, nhưng tự nhận "Some drivers may not work in the different environment" ([OpenPrinting/pappl-retrofit](https://github.com/OpenPrinting/pappl-retrofit)).

Driver Canon khó qua được bước chuyển này. Nó dựa trên PPD, trên một daemon đọc thẳng `printers.conf` của CUPS, và trên các thành phần 32-bit không thể build lại. captdriver thì về nguyên tắc bọc được (suy luận). Việc này tốn công và chưa cần trên noble, nên chỉ xem lại khi CaramOS rời noble. Trong lúc chờ, những phần CaramOS làm cho captdriver (`*1284DeviceID`, `STATE:`, các sửa đóng gói) nên được gửi ngược lên mounaiban, hoặc lên OpenPrinting khi ValdikSS chuyển kho, để CaramOS không phải gánh một fork riêng.

### Bảng xếp hạng việc cần làm

Các ước lượng công sức trong bảng là suy luận, chưa ai đo.

| Thứ tự | Việc | Công sức | Giá trị | Điều kiện, rủi ro |
|---|---|---|---|---|
| 1 | Mua LBP2900 cũ; ghi `lsusb -v`, chuỗi 1284 ID, hành vi khi cắm vào CaramOS 1.3.6, bản ghi `usbmon`; mời doanh nghiệp VNLF thử | Rất thấp (1–2 ngày, ~1,5–2,3 triệu đồng) | Rất cao: mở khóa mọi kiểm thử | Cần thêm LBP3300 để đóng trọn #39 |
| 2 | Driver Check nhận máy CAPT theo USB ID, thông báo tiếng Việt, kiểm hàng đợi, dọn dấu vết script cũ, kiểm thử với sysfs giả | Thấp (vài ngày) | Cao: biến "im lặng" thành chỉ dẫn | Phát hành qua caramos-ota |
| 3 | Công thức App Center `canon-capt`: tải từ Canon, ghim SHA-256, hiện giấy phép, i386 tối thiểu, unit riêng, symlink udev, quirk, hàng đợi `ccp://`; Driver Check làm cửa vào | Trung bình (1–2 tuần) | Cao: LBP2900, LBP3300 và ~30 mẫu; đóng được #39 | Binary 2017 chạy bằng root; cần i386; hỏng trên nền 26.04 nếu thiếu thư viện bù |
| 4 | Bài hướng dẫn tiếng Việt trên VNLF thay các script cũ, trỏ tới công thức | Thấp (1 ngày) | Trung bình | Viết sau việc 3 |
| 5 | `printer-driver-captdriver` trong PPA: `0.2.1-pr` + PR #55, `*1284DeviceID`, `STATE:`, `Modaliases`, backend `captusb` có vá #1461, `setup-queues` | Trung bình đến cao (2–4 tuần + chạy thử dài) | Cao về lâu dài | Chỉ làm mặc định sau 30–60 lệnh thử; `captd` cần quyền GPL từ Bruce Nguyen |
| 6 | Chia sẻ máy in chủ động, chỉ trong LAN, kèm hướng dẫn Windows qua IPP; thử khổ A5 | Trung bình | Cao với doanh nghiệp | Phụ thuộc việc 3 hoặc 5 |
| 7 | Gửi ngược `*1284DeviceID`, `STATE:`, sửa đóng gói lên upstream; yêu cầu SRU #1461 cho noble | Thấp đến trung bình | Trung bình: giảm gánh bảo trì | Phụ thuộc upstream và Ubuntu |
| 8 | Printer Application cho CUPS 3 | Cao | Thấp ở thời điểm này | Xem lại khi đổi nền (Ubuntu 27.04/27.10 theo lộ trình OpenPrinting) |

## Điều đã kiểm chứng, điều mới là suy luận và câu hỏi còn mở

Bảng dưới gom các nhận định chính theo mức chắc chắn. "Đã kiểm chứng" là kiểm tra trực tiếp ngày 08/11/2026, không chạy binary nào của Canon hay script cài đặt cộng đồng nào. "Theo nguồn" là một hay vài nguồn nói mà chưa ai thử lại. "Suy luận" là đánh giá của báo cáo. Bản tải về của Canon và các bản clone dùng khi nghiên cứu nằm trong `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/`. Đây là thư mục tạm, có thể bị dọn bất cứ lúc nào.

| Mức | Nhận định |
|---|---|
| Đã kiểm chứng | Tarball 2.71 vẫn tải được từ Canon (127.521.219 byte, SHA-256 `8565a2fd…41be`); trùng với mã ghim của AUR và với các .deb mà script cộng đồng commit |
| Đã kiểm chứng | Gói amd64 có phần lõi i386 nhưng không khai phụ thuộc i386; bộ i386 tối thiểu cho LBP2900 là `libc6`, `libpopt0`, `libxml2` |
| Đã kiểm chứng | Vòng `kill -9 … cut -c 1-5` trong `preinst`/`prerm` cắt sai PID trên noble (chưa ghi nhận sự cố thật) |
| Đã kiểm chứng | Gói Canon không có unit systemd và không tự bật `ccpd`; PPD của Canon và của captdriver đều không có `*1284DeviceID` |
| Đã kiểm chứng | Mint 22.3: `usblp` có sẵn, không bị chặn; i386 đã bật; tệp quirk của CUPS không có dòng CAPT; AppArmor cho chạy tệp trong `/usr/lib/cups/{backend,filter}`, không cho chạy trong `/usr/local` |
| Đã kiểm chứng | CUPS của noble (`2.4.7-1.2ubuntu7.14`), 26.04 và 26.10 chưa có bản vá #1461; bản vá áp và build được trên mã noble (chưa thử với máy in) |
| Đã kiểm chứng | Mọi nhánh captdriver chính build sạch với GCC 13/14; bộ lọc không chạy được khi thiếu máy in; lỗi của PR #55 còn trong mã 2026; không nhánh nào phát `STATE:` |
| Đã kiểm chứng | cupshelpers chọn PPD captdriver cho `MDL:LBP2900` với trạng thái 0; `lpinfo --device-id` thì không tìm thấy |
| Đã kiểm chứng | Driver Check không báo gì khi `usblp` nhận máy in; helper chỉ cài gói vừa được ubuntu-drivers khớp vừa nằm trong `ONE_CLICK` |
| Đã kiểm chứng | Script hieplpvip đòi một gói không có trên noble (đọc mã và chỉ mục, không chạy); toolkit của Bruce Nguyen không có giấy phép; PPA `michael-gruz/canon` vẫn công khai `cndrvcups-capt` 2.20 từ năm 2011 |
| Theo nguồn | Nhiều người in được bằng driver Canon trên Ubuntu 24.04 và Mint 22.x sau khi sửa script (2024–2026) |
| Theo nguồn | Treo ở lệnh thứ năm và cách chữa bằng `captd` (một nhà phát triển, 07/2026); LBP2900 không bật `XSTATUS_CHNG` (suluoniu) |
| Theo nguồn | Fork ValdikSS cộng CUPS mới chạy tốt với LBP2900 (một báo cáo, 14/06/2026); tác giả fork không có LBP2900 (theo bình luận 03/06/2026) |
| Theo nguồn | Cổng 59787 cũng chạy được; Mint 22 tự chọn driver PostScript sai (sanhos95); CUPS in khổ A5 kém (voz, 2023); bản cập nhật Windows mới làm hỏng việc in CAPT (VNLF, chưa có nguồn gốc) |
| Suy luận | Quirk `blacklist` ngăn backend `usb` tách `usblp` và ngăn hàng đợi `usb://` tự tạo (Michael Sweet: "No guarantees") |
| Suy luận | Luật udev tạo symlink cộng unit tên riêng xử lý được rút cáp, cắm lại và đánh thức máy; thư viện 32-bit của Canon trong `/usr/lib` được trình nạp i386 tìm thấy (cần kiểm bằng `ldd`) |
| Suy luận | Một backend riêng tên `captusb` tốt hơn build lại cups; driver Canon không sống được sang CUPS 3; các ước lượng công sức |

Còn bảy câu hỏi mở, mỗi câu cần một việc cụ thể mới trả lời được:

| Câu hỏi mở | Cách trả lời |
|---|---|
| EULA và điều khoản tải tương tác ra sao, và chữ "phi thương mại" có chạm tới doanh nghiệp không | Ý kiến luật sư, hoặc câu trả lời bằng văn bản của Canon |
| Bộ mô tả giao diện USB, số serial và chuỗi 1284 ID của LBP2900B | Chỉ biết được khi có máy |
| CaramOS 1.3.6 hôm nay làm gì khi cắm máy | Cắm thử trên bản hiện tại |
| `udev-configure-printer` có chọn URI `captusb://` không | Thử sau khi có backend riêng |
| `ccpd` nghe trên địa chỉ nào | Chạy `ss -ltnp` sau khi cài |
| Vòng `kill -9` của Canon đã gây sự cố thật chưa | Hiện chưa có báo cáo nào xác nhận |
| Bản dịch tiếng Việt của CUPS cho các trạng thái chuẩn đã đủ chưa | Kiểm danh mục dịch của CUPS |

## Kết luận

Chuyện LBP2900 trên Linux chưa bao giờ đơn thuần là "thiếu driver". Có bốn khớp nối phải ăn khớp cùng lúc: ai được phép tải phần mềm, ai giữ cổng USB (`usblp` hay libusb), ai khởi động và khởi động lại daemon, và CUPS nhận ra máy bằng gì (1284 ID và URI). Mỗi script cộng đồng sửa một khớp và làm gãy khớp khác. Script phổ biến nhất, do một người Việt dịch từ bản tiếng Nga, đã đứng yên từ 2020 trong khi người dùng vẫn phải tự sửa tay. Chỉ một bản phân phối mới sửa được cả bốn khớp cùng lúc. CaramOS lại có sẵn đủ bốn công cụ tương ứng: Driver Check để thấy máy, App Center để tải phần mềm có giấy phép riêng và sửa nhanh, PPA cho phần mã mở, OTA để giao và để dọn dẹp. Nhờ vậy CaramOS có thể trở thành con đường được bảo trì, bằng tiếng Việt, mà hệ sinh thái này đang thiếu.

Hai đường driver có khung thời gian ngược nhau. Driver Canon dùng được ngay, nhưng là một cây cầu có hạn: nó gãy ở nền 26.04 nếu thiếu thư viện bù, và không qua được CUPS 3. captdriver thì chưa sẵn sàng, nhưng là đường duy nhất sang thế hệ in kế tiếp. Vì thế nên xây cây cầu trước, nhưng đổ công kiểm thử (backend giả, bản ghi `usbmon`, gadget) vào captdriver, vì công sức đó còn dùng lại được cho LBP3010, LBP6000 và các mẫu khác. Bản vá #1461 có ở upstream từ tháng 4/2026 mà chưa vào bản Ubuntu nào, kể cả 26.04. Điều đó cho thấy CaramOS không thể ngồi chờ Ubuntu. Nhưng một backend mang tên riêng cộng một yêu cầu SRU giữ cho CaramOS khỏi phải tự bảo trì cả CUPS. Nút thắt thật của cả kế hoạch không nằm ở mã mà ở phần cứng: một máy in cũ giá chừng hai triệu đồng, cộng một doanh nghiệp 15 máy sẵn lòng thử, sẽ mở khóa mọi bước còn lại.
