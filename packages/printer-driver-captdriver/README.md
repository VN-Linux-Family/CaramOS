# printer-driver-captdriver

Driver mã nguồn mở cho máy in laser Canon dùng giao thức CAPT (LBP2900/LBP2900B và cùng họ), đóng gói cho PPA của
CaramOS. Gói chỉ gồm một bộ lọc CUPS (`rastertocapt`) và các PPD, không cần daemon hay thư viện 32-bit như driver của
Canon.

| Mẫu máy | USB ID | captdriver |
|---|---|---|
| LBP2900 / LBP2900B | `04a9:2676` | Chạy được |
| LBP3010 / LBP3018 / LBP3050 | `04a9:26da` | Chạy được |
| LBP3000 | `04a9:266a` | Thử nghiệm |
| LBP3100 / LBP3108 / LBP3150 | `04a9:26db` | Thử nghiệm |
| LBP6000 / LBP6018 | `04a9:271a` | Thử nghiệm |

Các máy CAPT khác (LBP3300, LBP6020...) chỉ chạy với driver của Canon. Giấy phép của Canon không cho đưa driver đó lên
PPA.

## Vì sao cần gói này

Trên CaramOS 1.3.6, cắm LBP2900 vào thì bước tự cấu hình máy in (`udev-configure-printer`) không tìm thấy PPD nào khớp.
Nó tạo hàng in với driver HP Designjet PostScript, rồi gửi PostScript vào máy in. CUPS báo in xong nhưng máy không ra
giấy, và Driver Check cũng không báo gì. Lỗi này được thấy bằng máy in ảo ngày 08/11/2026.

## Nguồn và bản vá

- **Upstream:** [mounaiban/captdriver](https://github.com/mounaiban/captdriver), nhánh `0.2.1-pr`, commit
  `f2d2da8` (13/08/2026).
  - Nhánh này chứa các bản sửa năm 2026 của ValdikSS, được chép sang để gửi lên upstream.
  - `Makefile` ghim commit đó và SHA-256 của orig tarball. Giấy phép: GPL-3+.
- **`debian/patches/0001`:** [PR #55](https://github.com/mounaiban/captdriver/pull/55) của Ershad Kunnakkadan, chưa được
  merge.
  - Bản vá giải mã trạng thái theo kích thước payload.
  - Trước đó bộ đếm trang lấy phải byte cũ hoặc rác, có thể làm lệnh in không bao giờ ra giấy.
- **`debian/patches/0002`:** bản vá của CaramOS, đã gửi upstream thành
  [PR #56](https://github.com/mounaiban/captdriver/pull/56). Nội dung bản vá giống hệt PR.
  - Mỗi PPD có `*1284DeviceID` đúng chuỗi `MDL` mà captdriver so khớp.
  - Không có device ID thì hệ thống chỉ so được tên model. Theo tên, LBP2900 và LBP3010 vẫn khớp đúng. Nhưng LBP3000
    bị gán nhầm PPD của LBP3010, mà số loại giấy trong PPD này mang nghĩa khác. Còn LBP3100 và LBP6000 thì không tìm
    được driver.
  - LBP3000 và LBP3100 có PPD riêng.
  - Tên model của PPD LBP3010 và LBP3100 được rút ngắn, để `ShortNickName` không quá 31 ký tự và qua được
    `cupstestppd`.
- **`debian/rules`:**
  - cài bộ lọc vào `/usr/lib/cups/filter`, chỗ duy nhất AppArmor của noble cho cupsd chạy bộ lọc;
  - dựng PPD với `LC_ALL=C`;
  - kiểm `ShortNickName` và device ID của các PPD sau khi dựng.

## Gói làm gì trên máy

- `debian/control` có header `Modaliases`, nên ubuntu-drivers khớp được gói với máy in đang cắm. Nhờ đó Driver Check
  cài nó bằng helper sẵn có (`ONE_CLICK`), không cần thêm logic tin cậy mới.
- Sau khi cài, postinst chạy `/usr/lib/printer-driver-captdriver/setup-printers`:
  - Hàng in của máy CAPT đang dùng driver khác (hàng in sai tạo trước đây) được chuyển sang PPD captdriver đúng mẫu
    máy.
  - Máy in đang cắm mà chưa có hàng in được dựng qua đúng bước tự cấu hình của hệ thống
    (`configure-printer@.service`). Bước này giờ tìm ra captdriver theo device ID, với Status 0, tức là khớp chính xác.
- Bên `caramos-ota` có các phần đi kèm:
  - `usr/lib/udev/rules.d/71-caramos-capt-printers.rules` bỏ qua bước tự cấu hình cho máy CAPT khi chưa có driver hợp.
    Nhờ vậy không còn hàng in sai và máy in không bị gửi PostScript.
  - Cũng luật đó nhờ systemd của người dùng chạy `caramos-driver-check-hotplug.service`
    (`usr/lib/systemd/user/`). Nhờ vậy vừa cắm máy in vào là desktop hiện thông báo "Máy in chưa có driver" với nút
    "Xem chi tiết".
    - Mỗi máy in chỉ được báo một lần.
    - Rút máy in ra không bị tính là đã sửa xong, nên lần đăng nhập sau không báo "Đã xử lý xong vấn đề phần cứng".
    - Máy in cắm sẵn trước khi đăng nhập thì được báo ở lần kiểm tra lúc đăng nhập.
  - Driver Check (mở từ thông báo hoặc từ menu) có thẻ "Máy in chưa có driver" và nút "Cài driver máy in".
  - Có lỗi thì người dùng gửi về qua "Nhờ giúp đỡ", vào cùng hệ thống yêu cầu như các lỗi khác:
    - Màn hình cài driver thất bại có nút này, giống App Center và Trung tâm cập nhật. Yêu cầu kèm
      `driver-install.log`, là những gì helper in ra.
    - Mọi yêu cầu từ máy có máy in USB hoặc hàng in đều kèm `printer.log`, kể cả khi cài xong mà in không ra
      (`caramos-ota/HELP_API.md`, mục "Logs").
- **Danh sách USB ID phải khớp ở 4 chỗ:**
  - `knowledge.py` của Driver Check (`CAPT_PRINTERS`, `CAPTDRIVER_MODELS`);
  - luật udev ở trên;
  - `Modaliases` trong `debian/control`;
  - `PRODUCTS` trong `debian/setup-printers`.

  `tests/test_driver_check_printers.py` của caramos-ota chỉ kiểm hai chỗ đầu.

## Build và kiểm thử

```sh
make orig     # lấy upstream đúng commit, tạo orig tarball, kiểm SHA-256
make deb      # build .deb trong container ubuntu:24.04 (Docker, không cần sudo) -> build/
make test     # cupstestppd cho 5 PPD, rồi hỏi CUPS chọn PPD nào cho device ID của từng mẫu máy
make source   # gói nguồn cho PPA -> build/*.dsc, build/*_source.changes
make upload   # ký rồi dput lên ppa:vietnamlinuxfamily/caram-os
make check-upstream   # upstream có gì mới so với lần duyệt trước (mục "Bảo trì")
make bump             # nâng lên commit mới của upstream
```

**Khi phát hành:**

- Gói này phải có trên PPA cùng lúc với bản `caramos-ota` có Driver Check mới. Nếu chưa có, nút cài trong Driver Check
  sẽ bị helper từ chối.
- Lần đầu upload kèm orig tarball (`-sa`).
- Sau khi Launchpad xuất bản, kiểm `Packages.xz` của PPA xem mục `printer-driver-captdriver` có dòng `Modaliases:`
  không.

## Thử bằng máy in ảo (không cần máy thật)

`tests/vlbp2900.py` là một máy LBP2900 ảo chạy qua USB/IP. Kernel Ubuntu không có `dummy_hcd` nhưng có `vhci-hcd`.

- **Máy ảo trông như máy thật:** USB ID, lớp máy in 7/1/2 và chuỗi IEEE 1284 đều giống.
- **Nó trả lời lệnh CAPT** theo đặc tả của captdriver và độ dài câu trả lời đo từ bản ghi USB của một máy LBP2900B thật.
- **Trang in nhận được** được giải nén ra PNG để xem bằng mắt.

Trong VM test, chạy:

```sh
sudo modprobe vhci-hcd
python3 vlbp2900.py serve &                  # nhật ký và trang in ở /tmp/vlbp2900/
sudo python3 vlbp2900.py attach              # "cắm" máy in
sudo python3 vlbp2900.py detach <cổng>       # "rút": cổng có trạng thái 006 trong /sys/devices/platform/vhci_hcd.0/status
```

**Kết quả ngày 09/11/2026** (VM caram1.3.3, kernel 6.14, CUPS 2.4.7; `caramos-ota` bản thử có luật udev và Driver Check
mới):

| Tình huống | Kết quả |
|---|---|
| Cắm máy khi chưa có driver | Thông báo "Máy in chưa có driver" hiện ngay lúc cắm. Không có hàng in nào được tạo, máy in không nhận PostScript. |
| Bấm "Xem chi tiết", rồi "Cài driver máy in" trên giao diện | Driver Check mở ra và vẫn mở sau khi dịch vụ thông báo kết thúc. Hộp nhập mật khẩu hiện ra, rồi báo "Đã cài xong driver". Hàng in "LBP2900" tự được tạo với `CanonLBP-2900-3000.ppd`. Trang test CUPS in ra đúng: 4736×6827 điểm. Kết quả hiện "Máy in: Hoạt động". |
| Cài bằng helper chạy với sudo (`apt-get update`, ubuntu-drivers khớp `Modaliases`, `apt-get install`) | Hàng in tự được tạo với Status 0, tức là khớp chính xác. Trang test in ra đúng: 98 dải. |
| Máy đã có hàng in sai (HP Designjet T920 PostScript) từ trước | Lúc cài gói, postinst chuyển hàng in sang captdriver. In được, và Driver Check báo máy in ổn. |
| Rút máy in rồi đăng nhập lại | Không có thông báo nào; Driver Check vẫn nhớ máy in. |
| Gỡ driver rồi cắm lại máy in | Dịch vụ chạy nhưng không báo lần hai, và không tạo hàng in. |
| Rút máy, xoá hàng in, cắm lại khi đã có driver | Bước tự cấu hình của hệ thống tạo lại hàng in với captdriver, Status 0. |

Máy ảo trả lời tức thì và không có cơ khí. Vì thế nó không thay được máy thật ở các mặt sau: kéo giấy, kẹt giấy, hết
giấy, độ đậm, các lỗi phụ thuộc thời gian (CUPS #1461), và tuyên bố "máy treo ở lệnh in thứ năm".

## Thử trên máy in thật

Cần: một máy LBP2900 hoặc LBP2900B, một máy chạy CaramOS 1.3.6, và hai gói thử
(`caramos-ota_*+lbp*_all.deb` và `printer-driver-captdriver_*_amd64.deb`) hoặc bản đã lên PPA.

1. **Trước khi cài gì:**
   - Cắm máy in, chạy `lsusb -d 04a9:` và `cat /sys/class/usbmisc/lp*/device/ieee1284_id`, rồi chép kết quả lại.
   - Với CaramOS 1.3.6 gốc, chạy `lpstat -v` và ghi lại hàng in được tự tạo.
2. **Cài `caramos-ota` bản thử, rút máy in ra rồi cắm lại.**
   - Góc màn hình phải hiện ngay thông báo "Máy in chưa có driver".
   - `lpstat -v` không được có hàng in mới.
   - Bấm "Xem chi tiết": Kiểm tra driver phải mở ra với thẻ "Máy in chưa có driver".
3. **Bấm "Cài driver máy in" rồi nhập mật khẩu.** Sau khi cài xong, `lpstat -v` phải có hàng in dùng
   "Canon LBP2900/LBP3000 r2c".
4. **In thử, ghi lại lệnh nào ra giấy, chậm, hỏng hoặc treo:**
   - trang test CUPS;
   - một PDF nhiều trang và một trang Word hoặc LibreOffice khổ A4;
   - 10 lệnh in liên tiếp ngay sau khi bật máy in (kiểm tuyên bố treo ở lệnh thứ năm, lỗi `ReserveUnit failed 0x8c`);
   - hết giấy giữa chừng, rồi nạp giấy lại;
   - huỷ một lệnh khi đang in, rồi in lệnh tiếp theo;
   - in sau khi máy in đã nghỉ (ngủ) một lúc;
   - so độ đậm với khi in từ Windows.
5. **Gửi lại qua "Nhờ giúp đỡ"** (trong Kiểm tra driver, hoặc dấu ? ở góc phải panel):
   - Ghi kết quả từng bước vào lời nhắn và kèm ảnh trang in.
   - Nhật ký máy in `printer.log` tự được đính kèm. Nó gồm máy in, hàng in, lệnh in và cuối `error_log` của CUPS,
     đã bỏ số serial và tên tài liệu.
   - Bật `sudo cupsctl --debug-logging` trước khi in để nhật ký đủ chi tiết. Gửi xong thì tắt bằng
     `sudo cupsctl --no-debug-logging`.
6. **Nếu được, ghi dữ liệu USB khi in**, để chỉnh máy in ảo cho giống máy thật:

   ```sh
   sudo apt install tcpdump && sudo modprobe usbmon
   lsusb -d 04a9:                               # Bus 003 ... -> usbmon3
   sudo tcpdump -i usbmon3 -w lbp2900.pcap     # in một trang, chờ xong rồi Ctrl+C
   ```

   tcpdump ghi mọi thiết bị trên cùng bus, kể cả bàn phím, nên đừng gõ mật khẩu trong lúc ghi. Gửi file qua kênh riêng,
   không đăng công khai.

## Bảo trì: khi upstream thay đổi

Gói ghim đúng một commit của upstream (`UPSTREAM_COMMIT` trong `Makefile`). GitHub có đổi gì thì người dùng CaramOS
vẫn dùng bản đã kiểm, cho tới khi mình chủ động nâng lên. Không có gì tự cập nhật theo upstream, và cũng không có gì
tự hỏng theo upstream.

**Theo dõi:** `make check-upstream` so upstream với lần duyệt trước, lưu trong `upstream-refs.txt`.

- Lệnh này xem:
  - nhánh đang ghim;
  - commit, nhánh, thẻ và pull request mới ở mounaiban, ValdikSS và agalakhov;
  - kho `OpenPrinting/captdriver` có xuất hiện chưa. ValdikSS nói bản hoàn chỉnh sẽ lên đó.
- Không có gì mới thì lệnh thoát 0. Có thay đổi thì nó in từng thay đổi kèm link GitHub và thoát 1 (make báo
  `Error 1`). Không đọc được GitHub thì thoát 2.
- Xem xong mọi thay đổi thì chạy `make record-upstream`, rồi commit `upstream-refs.txt`.

**Tự chạy mỗi tuần:** GitHub Actions (`.github/workflows/captdriver-upstream.yml`) chạy lệnh trên vào mỗi sáng thứ Hai.
- Có thay đổi thì nó mở issue "captdriver upstream có thay đổi" trên repo CaramOS.
- Nếu issue đó còn mở thì nó thêm bình luận, nhưng chỉ khi báo cáo khác lần trước.
- Không đọc được GitHub thì lần chạy báo lỗi.
- Muốn chạy ngay thì vào tab Actions, chọn "Run workflow". Trước mỗi lần phát hành CaramOS cũng nên chạy
  `make check-upstream` trên máy.

**Thấy gì thì làm gì:**

| Thay đổi | Việc cần làm |
|---|---|
| `0.2.1-pr` có commit mới | Đọc thay đổi qua link compare, rồi `make bump`. |
| mounaiban hợp nhất vào master hoặc gắn thẻ, ví dụ `0.2.1` | `make bump BRANCH=master COMMIT=<commit của thẻ> NEW_VERSION=0.2.1` |
| Kho `OpenPrinting/captdriver` xuất hiện | So với nhánh đang dùng. Nếu chuyển sang: `make bump URL=https://github.com/OpenPrinting/captdriver.git BRANCH=<nhánh>` |
| PR #55 được merge | `make bump` báo 0001 là "already upstream": xoá nó khỏi `debian/patches/series`. |
| PR #56 (bản vá 0002 của mình) được merge | Như trên với 0002. Nếu upstream yêu cầu sửa: sửa trên nhánh `ppd-1284-device-id` của fork `mrd9999/captdriver`, rồi chép lại vào 0002. |
| Upstream thêm mẫu máy hoặc đổi chuỗi `MDL` | Sửa 0002 và 4 danh sách USB ID (mục "Gói làm gì trên máy"). Cần cả bản `caramos-ota` mới. |
| Pull request mới có bản sửa đáng lấy | Đọc kỹ giấy phép, người viết và mẫu máy đã thử. Lấy về thành `debian/patches/000N-...patch` có header DEP-3. |
| Nhánh bị xoá hoặc bị force-push | Bản đã lên PPA không ảnh hưởng, vì Launchpad giữ orig tarball. Chọn commit khác để bám. Có thể fork về VN-Linux-Family làm bản lưu (hỏi chủ dự án trước). |

**Nâng lên một commit mới:**

1. `make check-upstream`, rồi đọc các thay đổi.
2. `make bump`. Mặc định lệnh này lấy commit mới nhất của nhánh đang ghim; muốn chọn khác thì dùng `COMMIT`,
   `BRANCH`, `URL`, `NEW_VERSION`. Lệnh sẽ:
   - tạo orig tarball mới;
   - cập nhật `UPSTREAM_*` và `ORIG_SHA256` trong `Makefile`;
   - thêm mục changelog `0.2.1~git<ngày>.<commit>-0caramos1`;
   - báo từng bản vá: còn áp được, đã có trong upstream, hay cần sửa lại.
3. Sửa bản vá nếu cần, và ghi việc đó vào `debian/changelog`, ví dụ "Drop 0001, merged upstream".
   - Bản vá không áp được thì clone upstream ở commit mới, sửa tay phần còn cần, rồi
     `git diff > debian/patches/000N-....patch`.
   - Giữ header DEP-3 (Description, Origin, Forwarded, Last-Update).
4. `make deb test`.
5. Thử bằng máy in ảo trong VM như mục trên: cắm máy, cài driver, in trang test.
6. `make source upload`.
7. Người dùng nhận bản mới qua Trình quản lý cập nhật như mọi gói từ PPA. Không cần phát hành `caramos-ota`, trừ khi
   danh sách mẫu máy thay đổi.
8. `make record-upstream`, rồi commit.

Nếu upstream nhận bản vá 0002, mỗi lần nâng cấp sẽ nhẹ hơn (mục dưới).

## Việc tiếp theo

- **Lỗi #1461 của CUPS:** nếu máy thật in chậm, ngắt quãng hoặc treo giữa trang, thì làm backend `captusb` riêng. Đó là
  một bản sao của `usb-libusb.c` (CUPS 2.4.7 của noble) có thêm bản vá PR #1500, theo hướng trong báo cáo nghiên cứu.
- **Lỗi treo ở lệnh in thứ năm:** chế độ giữ phiên USB (`captd`) chỉ thêm khi lỗi tái hiện được trên máy thật, và khi
  mã đó có giấy phép GPL.
- **Theo dõi [PR #56](https://github.com/mounaiban/captdriver/pull/56)** (bản vá 0002, mở ngày 09/11/2026 từ fork
  `mrd9999/captdriver`). Nếu upstream yêu cầu sửa thì sửa trên nhánh `ppd-1284-device-id` của fork, rồi chép lại vào
  0002. Khi PR được merge, `make bump` sẽ báo 0002 là "already upstream".
