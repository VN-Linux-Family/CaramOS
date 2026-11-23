# Nghiên cứu: các sản phẩm quản lý máy cho doanh nghiệp làm gì

Ngày 21/11/2026. Dùng để chọn tính năng cho CaramOS Doanh nghiệp 0.2.

## Các sản phẩm đã xem

**Microsoft Intune, Group Policy, Jamf Pro, ManageEngine Endpoint Central, Hexnode, Fleet.** Bộ khung giống nhau:
- kiểm kê máy;
- cài phần mềm, cập nhật bản vá;
- cấu hình hàng loạt, hạn chế (USB, ứng dụng, web);
- lệnh từ xa, hỗ trợ từ xa;
- báo cáo tuân thủ, nhóm máy, nhật ký thao tác.

Trên Linux phần lớn còn mỏng:
- Intune chỉ kiểm tuân thủ và chạy script.
- Jamf chỉ quản lý máy Apple.
- Endpoint Central và Hexnode làm được nhiều nhất trên Linux.

**Ubuntu Landscape, Red Hat Satellite, SUSE Manager.** Thiên về máy chủ và bản vá. Không quản lý được thiết lập màn hình làm việc.

**Univention.** Lo tài khoản, thư mục và máy in. UCS@school có phòng máy (Veyon), quy tắc internet theo tiết học, kiểm duyệt in.

**UOS (Trung Quốc), nền tảng quản lý miền 统信集中域管平台.** Gần CaramOS nhất: chính hãng làm hệ điều hành làm luôn bộ quản lý trong mạng nội bộ. Có:
- quản lý người dùng;
- kiểm kê máy, xuất báo cáo;
- chính sách tường lửa và thiết bị ngoại vi (USB lưu trữ bị chặn mặc định);
- kho ứng dụng của công ty;
- truy cập từ xa có giao diện;
- nhật ký thao tác.

**Zorin Grid.** Công bố từ 2020, đến nay vẫn "sắp ra mắt". Ngoài Trung Quốc chưa bản Linux desktop nào có bộ quản lý dùng được.

## Nhu cầu của văn phòng Việt Nam

- **Chặn Facebook, YouTube trong giờ làm, mở giờ trưa.** Hiện các công ty làm trên router (DrayTek, MikroTik).
- **Kiểm kê tài sản cho kế toán.** MISA có mẫu Excel, nhưng chưa có gì tự quét máy.
- **Tắt máy cuối ngày.** Hay dùng PowerOff trên Windows.
- **Hỗ trợ từ xa.** UltraViewer không chạy trên Linux.
- **Máy in dùng chung.** Lỗi kết nối máy in chia sẻ từ Windows rất phổ biến.
- **Chữ ký số, MISA.** Bản web (AMIS, meInvoice, ký từ xa MISA eSign, VNPT SmartCA) dùng được trên CaramOS. Công cụ ký trên máy (USB token) thì chỉ có cho Windows. Vì vậy chặn USB phải chừa token ký số, và nên có sẵn dấu trang cổng thuế, BHXH, hóa đơn điện tử.

## Pháp luật về giám sát nhân viên

Từ 1/1/2026, Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15 và Nghị định 356/2025/NĐ-CP thay Nghị định 13/2023.

- **Điều 25 khoản 3 điểm a:** chỉ được dùng biện pháp kỹ thuật "trên cơ sở người lao động biết rõ biện pháp đó".
- **Dữ liệu nhạy cảm:** dữ liệu theo dõi hành vi trên mạng và vị trí chính xác giờ là dữ liệu nhạy cảm. Doanh nghiệp nhỏ xử lý loại dữ liệu này thì mất ưu đãi 5 năm.
- **Mức phạt:** tới 3 tỷ đồng với tổ chức.

**Nguyên tắc của CaramOS: chặn, không theo dõi.**
- Không chụp màn hình lén, không ghi phím, không lưu lịch sử web, không định vị.
- Hỗ trợ từ xa chỉ khi nhân viên đồng ý, có thanh báo trên màn hình trong suốt lúc hỗ trợ.
- Máy nhân viên có trang "Máy này do công ty quản lý", nói rõ công ty quản lý gì và không xem được gì.

## CaramOS Doanh nghiệp 0.2 làm gì

1. **Phòng ban.** Thiết lập riêng cho từng phòng: Kế toán có ổ chung riêng và chặn USB, phòng Kinh doanh được mở Facebook…
2. **Kiểm kê tài sản.** Máy tự gửi cấu hình, số serial, ổ cứng và sức khỏe ổ, pin, màn hình, ứng dụng. Người quản trị nhập mã tài sản, ngày mua, giá, bảo hành, người dùng, vị trí. Xuất Excel theo kiểu biên bản kiểm kê.
3. **Trình duyệt.** Trang chủ, dấu trang của công ty, chặn trang web theo giờ, tìm kiếm an toàn. Áp cho Firefox, Chrome, Cốc Cốc, Edge, Brave.
4. **Máy in.** Cài máy in mạng cho mọi máy, có nút tìm máy in trong mạng.
5. **Ổ dùng chung** hiện sẵn trong trình quản lý tệp.
6. **Lịch tắt và bật máy.** Báo trước, cho hoãn; bật lại buổi sáng (hẹn giờ trong máy và Wake-on-LAN).
7. **Lệnh tức thì** (tới máy trong vài giây): khóa máy, gửi tin nhắn có xác nhận "đã đọc", đăng xuất, khởi động lại, tắt máy, cập nhật, kiểm kê lại.
8. **Hỗ trợ từ xa có đồng ý.** Nút "Nhờ IT hỗ trợ" trên máy nhân viên. Đường truyền được mã hóa.
9. **Bảo mật.** USB lưu trữ: cho phép, chỉ đọc, hoặc chặn (bàn phím, chuột, máy in, token ký số vẫn dùng được); mở tạm thời. Tự khóa màn hình. Bật tường lửa.
10. **Ứng dụng.** Bắt buộc cài, cấm cài, lấy từ danh mục App Center.
11. **Wi-Fi công ty** cho laptop. Mật khẩu Wi-Fi được mã hóa riêng cho từng máy.
12. **Sức khỏe máy.** Ổ sắp đầy hoặc sắp hỏng, pin chai, bản vá bảo mật chờ lâu, đồng hồ lệch, máy lâu không bật.
13. **Nhật ký thao tác; sao lưu và khôi phục máy quản lý.** Máy quản lý hỏng thì khôi phục sang máy khác, không phải ghép lại từng máy.
14. **Bảo mật đường truyền.** Mỗi máy có khóa riêng; mọi yêu cầu có mã xác thực, không gửi mật khẩu dạng rõ.

**Để sau:**
- tài khoản IT riêng trên mỗi máy, kiểu LAPS (bỏ quyền admin của nhân viên);
- vào miền AD;
- bộ nhớ đệm cập nhật trong mạng LAN;
- kho ứng dụng "công ty cho phép";
- in tem QR tài sản;
- báo cáo giờ bật máy.

**Không làm:** theo dõi lén, định vị, xóa máy từ xa, chạy lệnh tùy ý trên máy nhân viên.

## Nguồn chính

- Intune: https://learn.microsoft.com/en-us/intune/fundamentals/platform-guide-linux
- Endpoint Central: https://www.manageengine.com/products/desktop-central/linux-comparison-matrix.html
- Hexnode: https://www.hexnode.com/uem/platform/linux-device-management/
- Fleet: https://fleetdm.com/linux
- Landscape: https://ubuntu.com/landscape/docs/explanation/features/
- UOS: https://uniontech.com/uploads/files/2024/0415/Jvi6AlbL7ZmsswD9sa6A81QvZFy6IitagkJtmZ5v.pdf
- Zorin Grid: https://zorin.com/grid/
- UltraViewer cho Linux: https://www.ultraviewer.net/EN/200000268-ultraviewer-for-linux.html
- Luật BVDLCN điều 25: https://hethongphapluat.com/luat-bao-ve-du-lieu-ca-nhan-2025/dieu-25
- Nghị định 356/2025: https://www.tilleke.com/insights/new-decree-provides-guidance-for-vietnams-personal-data-protection-law
