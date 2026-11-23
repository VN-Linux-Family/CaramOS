# CaramOS Doanh nghiệp: kế hoạch bản 1

Bản nháp ngày 20/11/2026, để duyệt trước khi làm.

## Bối cảnh

Bạn TB dùng CaramOS cho văn phòng công ty, đáp ứng khoảng 90–95% nhu cầu. Bạn ấy xin thêm ba thứ:

1. **Đồng bộ hình nền** cho các dịp lễ của công ty và của nhà nước.
2. **Quản lý dữ liệu trên máy nhân viên.** Nhân viên lưu file lộn xộn, nhất là ra Desktop. Bạn ấy muốn file nào không đưa lên máy chủ thì bị xóa khi khởi động lại.
3. **Phím tắt để khóa máy, tắt máy, tìm nhanh.** Việc này **đã làm** trong hệ điều hành gốc (migration `20261120100700_windows_shortcuts`):
   - Super+L khóa máy trên cả hai bản;
   - Ctrl+Alt+Delete mở hộp đăng xuất, tắt máy;
   - phím Super mở ô tìm kiếm.

Ý 1 và ý 2 làm thành gói riêng, như bạn đề xuất.

## Hình thức

- **Một ứng dụng riêng, tên "CaramOS Doanh nghiệp"**, không nằm trong hệ điều hành gốc. Máy gia đình và trường học vẫn gọn như cũ.
- **Cài từ App Center**, ở một mục mới tên "Doanh nghiệp".
  - Gói apt `caramos-business` nằm trên PPA CaramOS. App Center đã cài được gói apt, như VLC.
  - Gói tự cập nhật như mọi gói khác.
- **Một ứng dụng, hai vai: Máy quản lý và Máy nhân viên.** Người dùng chọn vai ở lần mở đầu tiên, giống Phòng máy chọn máy giáo viên hay máy học sinh.

## Bản 1 làm gì

### 1. Ghép máy

- Máy quản lý mở trang "Thêm máy" và hiện một mã 6 số.
- Máy nhân viên tự tìm thấy máy quản lý trong mạng công ty. Người dùng nhập mã là hai máy ghép xong.
- Cách ghép giống hệt Phòng máy (`caramos_lab/pairing.py`): tìm nhau qua UDP, trao khóa qua HTTP, mã 6 số tính từ khóa. Nhờ vậy một máy lạ trong mạng không thể giả làm máy quản lý.
- Phần thêm so với Phòng máy:
  - Máy quản lý có một cặp khóa Ed25519 và ký mọi chỉ đạo nó gửi đi.
  - Máy nhân viên chỉ làm theo chỉ đạo có chữ ký đúng.

### 2. Danh sách máy

- Máy quản lý thấy từng máy nhân viên: tên máy, người đang dùng, lần cuối có mạng, phiên bản CaramOS, bản Cinnamon hay Xfce.
- Máy nhân viên tự báo về vài phút một lần.

### 3. Đồng bộ hình nền

- Máy quản lý chọn:
  - một ảnh mặc định;
  - các đợt theo ngày, ví dụ Tết từ 25/1 đến 5/2, 30/4–1/5, 2/9, ngày kỷ niệm công ty.
- Máy nhân viên tải ảnh về và đặt làm hình nền cho mọi màn hình, trên cả Cinnamon và Xfce. Cách đặt dùng lại của tính năng hình nền mỗi ngày. Hết đợt thì quay về ảnh mặc định.
- Tùy chọn khóa để nhân viên không đổi được hình nền: khóa dconf trên Cinnamon, khóa xfconf trên Xfce.

### 4. Desktop và Tài liệu nằm trên máy chủ

Mình không đề xuất xóa file chưa đưa lên máy chủ. Nhân viên quên hoặc mất điện là mất việc, và công ty chịu thiệt. Thay vào đó:

- Máy quản lý khai báo thư mục chung. Có thể là máy chủ hoặc NAS sẵn có của công ty (Samba, Windows, Synology…), hoặc chính máy quản lý nếu công ty chưa có máy chủ.
- Mỗi lần nhân viên đăng nhập, thư mục Desktop và Tài liệu của họ trỏ thẳng vào thư mục riêng của họ trên máy chủ. Lưu ra Desktop là đã lên máy chủ, máy nhân viên không giữ gì.
- Khi mất mạng lúc đăng nhập:
  - file tạm lưu ở máy, trong thư mục "Chưa lên máy chủ";
  - nhân viên nhận thông báo;
  - lần sau có mạng thì file tự chép lên máy chủ.
- Có tùy chọn "Dọn Desktop khi khởi động lại". Tùy chọn này chỉ **chuyển** file còn nằm ở máy lên thư mục "Chưa sắp xếp" trên máy chủ, không bao giờ xóa.

## Kỹ thuật

| Phần | Cách làm |
|---|---|
| Phần chạy nền trên máy nhân viên | **Rust.** Chạy suốt ngày và nhận dữ liệu qua mạng, nên cần nhẹ (vài MB RAM) và an toàn bộ nhớ. Gồm một dịch vụ hệ thống (systemd) và một phần nhỏ trong phiên người dùng để đặt hình nền và thư mục. |
| Giao diện (máy quản lý, trang ghép máy) | **Python + GTK4/libadwaita**, như App Center, Driver Check, Phòng máy. Dùng chung giao diện, bản dịch, và cách tự chọn bộ vẽ cairo vừa làm. |
| Liên lạc | Máy quản lý phục vụ chỉ đạo và ảnh qua HTTP trong mạng LAN, có ký. Máy nhân viên lấy về lúc đăng nhập, sau đó 5 phút một lần. |
| Đóng gói | Một gói nguồn `caramos-business` trên PPA. Phần Rust dựng bằng `rustc-1.85` và `cargo-1.85` có sẵn trên Ubuntu 24.04. Thư viện Rust đóng kèm trong gói nguồn, vì Launchpad dựng gói không có mạng. |
| App Center | Thêm danh mục "Doanh nghiệp" và mục "CaramOS Doanh nghiệp", cài bằng apt. Cần ra một bản App Center mới. |

**Giới hạn an toàn của bản 1:** máy nhân viên chỉ nhận hai loại chỉ đạo, hình nền và thư mục. Không có chỉ đạo "chạy lệnh tùy ý".

## Các bước và thời gian (ước lượng)

1. Khung gói, ghép máy, danh sách máy, chạy được trên VM cả hai bản: khoảng 1 tuần.
2. Đồng bộ hình nền và khóa hình nền: 3–4 ngày.
3. Desktop và Tài liệu trên máy chủ, kèm cách xử lý khi mất mạng: 1–2 tuần. Đây là phần khó nhất, cần thử với NAS thật.
4. Đóng gói PPA (Rust), mục App Center, hướng dẫn cho người quản trị: 3–4 ngày.

Tổng cộng khoảng 3–4 tuần là có bản 1 cho công ty bạn TB dùng thử. Bước 1 và 2 không cần chờ câu trả lời của bạn TB, làm được ngay.

## Cần hỏi bạn TB

1. Công ty có bao nhiêu máy, dùng bản Cinnamon hay Xfce?
2. Đã có máy chủ hoặc NAS chưa, loại gì (Windows Server, Synology, TrueNAS…)? Mỗi nhân viên có tài khoản riêng trên đó không?
3. Có cần khóa không cho nhân viên đổi hình nền không?
4. Nhân viên có hay mang laptop ra ngoài, rời mạng công ty, không? Câu này quyết định cách xử lý khi mất mạng.

## Rủi ro

- **Thư mục trên máy chủ** phụ thuộc mạng và máy chủ: máy chủ chậm thì mở file chậm. Cần thử với hệ thống thật của bạn TB.
- **Bảo mật:** kênh từ máy quản lý tới máy nhân viên phải có chữ ký. Bản 1 cố ý chỉ có hai loại chỉ đạo.
- **Hỗ trợ:** doanh nghiệp cần có người để liên hệ khi lỗi. Gói này có thể đi kèm dịch vụ hỗ trợ; việc này bạn quyết.

## Sau bản 1

- khóa cài đặt (USB, cài phần mềm);
- cài app hàng loạt từ App Center;
- xem màn hình máy nhân viên (Veyon, như Phòng máy);
- báo cáo;
- chữ ký số và MISA.
