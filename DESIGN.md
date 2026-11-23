# Giao diện ứng dụng CaramOS

Hướng dẫn chung cho các ứng dụng hệ thống của CaramOS: Update Center (Trung tâm cập nhật), App Center, và sau này Driver Check, Góp ý & hỗ trợ, Phòng máy. Áp dụng từ bản thiết kế lại ngày 21/11/2026.

## Hướng đi: là một phần của hệ thống

Đây là công cụ hệ thống, không phải trang quảng cáo. Chúng phải trông như một phần của máy, giống Cài đặt hay Tệp: bình tĩnh, gọn, đáng tin.

CaramOS chỉ hiện ở ba chỗ:
- **Màu xanh rừng** cho hành động chính.
- **Phông Be Vietnam Pro**: phông giao diện của CaramOS, làm cho tiếng Việt.
- **Logo hoa**, chỉ ở nơi ứng dụng tự giới thiệu.

Mọi thứ còn lại theo mẫu của GTK 4 và libadwaita: thanh tiêu đề trơn, nền trung tính, danh sách khung, trang trạng thái.

Điểm nhấn duy nhất là chữ: tiêu đề tiếng Việt rõ, đủ lớn, đủ dãn dòng cho dấu, viết bằng lời thường.

## Không dùng

Những thứ dưới đây làm giao diện trông như sinh ra từ mẫu có sẵn:

- Nền màu kem, thanh tiêu đề hay khối "hero" có dải màu chuyển.
- Chia mọi thứ thành thẻ bo tròn giống nhau có bóng mờ.
- Lời chào kiểu quảng cáo ("Chào mừng đến với…"), nhãn nhỏ phía trên tiêu đề ("BẢN CẬP NHẬT MỚI").
- Danh sách đánh dấu ✓ xanh và – cam; biểu tượng đứng trước mỗi câu chỉ để trang trí.
- Nhãn bo tròn khắp nơi ("Chọn một", "Đề xuất", "Flathub", "Kênh: stable").
- Chuỗi thông tin nối bằng dấu chấm giữa ("5 ứng dụng · 3 GB"). Viết thành câu: "5 ứng dụng, khoảng 3 GB".
- Tiêu đề tô xanh, chữ đậm 800 trở lên.
- Đánh số 1, 2, 3 cho những thứ không phải các bước nối tiếp.
- Từ kỹ thuật với người dùng: migration, systemd, timer, kênh stable, severity, gói, PPA. Những từ này chỉ được nằm trong phần "Chi tiết" thu gọn.

## Màu

Chỉ một màu nhấn. Các màu khác lấy từ nền tảng: libadwaita tự lo, còn ứng dụng GTK 3 dùng đúng các giá trị dưới đây.

| Vai trò | Sáng | Tối |
|---|---|---|
| Nền nút chính, mục đang chọn, thanh tiến trình | `#2b6a44` | `#3a855a` |
| Chữ trên nền nhấn | `#ffffff` | `#ffffff` |
| Liên kết, biểu tượng nhấn | `#276140` | `#8ccfa5` |
| Nền cửa sổ | `#fafafb` | `#242424` |
| Nền danh sách khung | `#ffffff` | `#2f2f2f` |
| Viền danh sách, đường kẻ | `rgba(0,0,0,0.09)` | `rgba(255,255,255,0.08)` |
| Chữ | `rgba(0,0,0,0.82)` | `#ffffff` |
| Chữ phụ | `rgba(0,0,0,0.55)` | `rgba(255,255,255,0.6)` |
| Lỗi | `#c01c28` | `#ff7b63` |
| Cảnh báo (chỉ cho cập nhật bảo mật) | `#9c6e03` | `#f5c04a` |

Với libadwaita (GTK 4), chỉ đổi màu nhấn:

```css
@define-color accent_bg_color #2b6a44;
@define-color accent_fg_color #ffffff;
@define-color accent_color #276140;
```

Trong giao diện tối, ba giá trị lần lượt là `#3a855a`, `#ffffff`, `#8ccfa5`.

## Chữ

Dùng phông của hệ thống: Be Vietnam Pro 10pt. Không đặt lại phông trong CSS của ứng dụng, chỉ đặt cỡ và độ đậm. Chỉ dùng hai độ đậm: 400 và 600.

| Vai trò | Cỡ | Đậm | Ghi chú |
|---|---|---|---|
| Tiêu đề trang | 1.8em | 600 | dãn dòng 1.25; màu chữ thường, không tô xanh |
| Tiêu đề mục | 1.15em | 600 | |
| Chữ thường | 1em | 400 | đoạn văn dãn dòng khoảng 1.5; mỗi dòng không quá 70 ký tự |
| Chữ phụ | 0.92em | 400 | màu chữ phụ |

Các lớp `.title-1` đến `.title-4` của libadwaita mặc định đậm 800. Ứng dụng CaramOS hạ xuống 600.

## Bố cục

- Lề cửa sổ 24px. Khoảng cách giữa hai mục 24px. Trong một mục, tiêu đề cách danh sách 8px.
- Danh sách khung (`boxed-list`): bo góc 12px, viền mảnh, không bóng. Mỗi dòng cách lề 12px trên dưới, 14px hai bên. Các dòng ngăn bằng đường kẻ.
- Nút theo mẫu nền tảng: bo 6px. Chỉ trang trạng thái mới dùng nút viên thuốc (`.pill`).
- Căn trái. Chỉ trang trạng thái (xong, lỗi, không có gì mới) mới căn giữa.
- Thanh hành động ở đáy: chữ gợi ý bên trái, các nút bên phải, nút chính ở ngoài cùng bên phải.

## Thành phần

**Phần giới thiệu.** Logo 48px bên trái, cạnh đó là tiêu đề trang và một câu. Chỉ đặt ở trang đầu của mỗi ứng dụng.

**Danh sách khung.** Chứa thông tin dạng hàng: ứng dụng, thay đổi, lựa chọn. Mỗi hàng gồm biểu tượng (nếu có thật), tên đậm 600, một câu mô tả màu chữ phụ, và điều khiển ở bên phải.

**Trang trạng thái.** Dùng cho các trang xong, lỗi, không có gì mới. Gồm biểu tượng symbolic 64px màu chữ phụ, tiêu đề, một hai câu, rồi các nút.

**Thông tin phụ.** Viết thành câu. Ví dụ: "Từ Flathub, khoảng 1,3 GB." hay "Đề xuất cho hầu hết mọi người."

**Chi tiết kỹ thuật.** Đặt trong một ô mở rộng "Chi tiết", thu gọn sẵn. Log được phép dùng phông monospace.

## Lời

- Viết từ phía người dùng, bằng câu thường, câu chủ động. Nút nói đúng điều sẽ xảy ra: "Cập nhật", "Cài đặt", "Để sau", "Thử lại".
- Một hành động giữ đúng một tên suốt luồng. Nút "Cập nhật" dẫn tới "Đang cập nhật…" rồi "Đã cập nhật".
- Lỗi nói rõ chuyện gì xảy ra và cách sửa, không xin lỗi, không mơ hồ.
- Trang trống chỉ ra việc có thể làm tiếp.
