# Máy in ảo Canon LBP2900 (`vlbp2900.py`)

Ngày 08/11/2026. Dùng để thử driver LBP2900 trên CaramOS khi không có máy in thật.

## Nó là gì

- **Một chương trình Python chỉ dùng thư viện chuẩn, tự xưng là LBP2900 qua USB/IP.**
  - Kernel Ubuntu không có `dummy_hcd`, nhưng có `vhci-hcd`.
  - VM thấy một máy in vừa cắm vào: `04a9:2676 Canon, Inc. LBP2900`, lớp máy in 7/1/2, đúng chuỗi IEEE 1284.
  - `usblp` tạo `/dev/usb/lp0`, backend USB của CUPS thấy `usb://Canon/LBP2900?serial=0000A1B2C3D4`.
- **Trả lời các lệnh CAPT như máy thật**, dựa trên SPECS của captdriver và độ dài câu trả lời đo từ bản ghi USB của một máy LBP2900B thật (repo gauravyad69).
- **Lưu mỗi trang driver gửi tới (`page-NNN.capt`), giải nén Hi-SCoA rồi xuất PNG** (`page-NNN.png` và bản thu nhỏ `-preview.png`).
  - Bộ giải nén khớp từng byte với bộ nén của captdriver: kiểm bằng `harness.c` và `check_decoder.py`, 20 dải, 868.000 byte.

## Chạy trong VM test

```sh
sudo modprobe vhci-hcd
python3 vlbp2900.py serve &            # nhật ký và trang in ở /tmp/vlbp2900/
sudo python3 vlbp2900.py attach        # "cắm" máy in; in ra số cổng vhci
sudo python3 vlbp2900.py detach <cổng> # "rút" máy in
python3 vlbp2900.py render /tmp/vlbp2900/page-001   # giải nén lại một trang
```

- **Chế độ trạng thái** (biến `VLBP_STATUS`):
  - `hybrid` (mặc định): bit trạng thái theo cách captdriver đọc, câu trả lời GetInputStatus "có giấy" lấy từ bản ghi thật.
  - Ba chế độ còn lại `specs`, `capture` và `jobactive` dùng để thử nghiệm.
- **Đừng dừng bằng `pkill -f`**: mẫu tìm có thể khớp luôn shell SSH. Hãy dùng PID trong `/tmp/vlbp2900/server.pid`.

## Kết quả ngày 08/11/2026 (VM caram1.3.3, kernel 6.14, CUPS 2.4.7)

1. **Cắm máy vào là hệ thống tự tạo hàng in sai driver.**
   - Chuỗi tự cấu hình: `udev-configure-printer`, `udev-add-printer`, rồi `csd-printer` và `cups-pk-helper`.
   - Nó tạo hàng in "LBP2900" với PPD **HP Designjet T920 PostScript** (Status 3 = không tìm thấy driver).
   - Nó gửi ngay lệnh in "Automatic configuration" (PostScript) tới máy in.
   - In thử qua hàng in đó: PostScript mã hoá ASCII85 kèm `@PJL EOJ` đi thẳng vào máy CAPT, CUPS vẫn báo in xong. Máy thật sẽ không ra giấy.
   - Driver Check không báo gì: so sánh `caramos-driver-check --json` trước và sau khi cắm không khác.
2. **captdriver 0.2.1-pr in đúng hoàn toàn.**
   - Đi qua backend USB của CUPS 2.4.7 gốc (chưa có bản vá #1461), in trang test CUPS.
   - Trang giải nén ra đúng (`ket-qua/captdriver-trang-test.png`): 98 dải, 4736×6827 điểm.
   - Lỗi #1461 không xuất hiện, nhưng máy ảo trả lời tức thì, còn máy thật chậm hơn.
3. **Driver Canon 2.71 cài được nhưng chưa in được trên máy ảo.**
   - **Lúc cài:** `preinst` treo vô hạn khi có bất kỳ tiến trình nào mang chữ "ccpd" hoặc "captmon" trong dòng lệnh.
     - Lỗi nằm ở `cut -c 1-5`: PID 5287 bị cắt thành "52", nên lệnh `kill -9` trúng `[kworker/R-writeback]`.
     - Với PID 6 chữ số, lệnh này sẽ giết nhầm một tiến trình người dùng.
   - **Sau khi cài:**
     - `ccpd` không được bật khi khởi động máy (`systemd-sysv-install is-enabled ccpd` báo disabled).
     - `/etc/init.d/ccpd stop; start` có race: `stop` không chờ tiến trình cũ thoát, nên `start` không làm gì.
   - **Lúc in:**
     - `ccpd` chỉ giữ máy khi trạng thái rảnh là `0x41`.
     - Chuỗi lệnh đi tới GoOnline và SetLEDStatus(0x16) hai lần, rồi `captmon2` (32-bit) chờ một điều kiện nội bộ.
     - Cùng lúc đó `ccpd` quay vòng khoảng 400 yêu cầu IPP Get-Jobs mỗi giây (`ket-qua/canon-2.71/`).
     - Đã thử 4 biến thể trạng thái nhưng không gỡ được.
   - **Cần một bản ghi USB của driver Linux Canon in một trang trên máy LBP2900 thật** (usbmon và Wireshark, khoảng 15 phút) để bổ sung cho máy ảo.

## Máy ảo không chứng minh được

- Cơ khí và thời gian thật: kéo giấy, kẹt giấy, hết giấy, nhiệt sấy.
- Máy treo do dữ liệu cũ (lỗi ReserveUnit 0x8c trong ghi chú của Bruce Nguyen).
- USB tự ngắt khi tiết kiệm điện, và chất lượng in thật.
- Các lỗi phụ thuộc thời gian như #1461 cần thêm độ trễ giống máy thật, hoặc thử trên máy thật.
