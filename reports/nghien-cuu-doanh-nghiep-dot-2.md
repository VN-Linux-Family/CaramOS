# Nghiên cứu đợt 2: doanh nghiệp còn cần gì

Ngày 22/11/2026. Đợt này nối tiếp `nghien-cuu-quan-ly-may-doanh-nghiep.md`. Dùng để chọn tính năng cho CaramOS Doanh nghiệp 0.3. Đây là nghiên cứu, không phải tư vấn pháp lý.

## Năm phát hiện quan trọng nhất

1. **Hướng dẫn của Nhà nước đã ghi tên Ubuntu.** Công văn 519/BKHCN-CĐSQG (28/01/2026) về phần mềm và cấu hình tối thiểu cho máy tính văn phòng trong hệ thống chính trị.
   - Mục hệ điều hành ghi: "Windows 11, MacOS, Ubuntu Linux,… hoặc tương đương", kèm cấu hình cho Ubuntu 24.04 LTS. CaramOS chạy trên nền này.
   - Đây là hướng dẫn, không bắt buộc.
2. **Phạt phần mềm không bản quyền đã có thật.**
   - Nghị định 341/2025 áp dụng từ 15/02/2026: tổ chức bị phạt tới 500 triệu đồng.
   - Tháng 9/2026, công an TP.HCM phạt một công ty 15 triệu đồng vì cài phần mềm lậu ở một trường học.
   - Tháng 5/2026, Bộ VHTTDL lập đoàn kiểm tra phần mềm không bản quyền.
3. **Luật An ninh mạng 116/2025 (từ 01/07/2026) và Nghị định 331/2026 (từ 19/08/2026) chạm tới cả doanh nghiệp thường.**
   - Hệ thống nội bộ có xử lý dữ liệu cá nhân thường là cấp độ 2.
   - Theo quy định cũ (Thông tư 12/2022), cấp độ 2 cần phòng mã độc, ghi nhật ký, VPN để quản trị từ xa và sao lưu.
4. **Chưa có công ty Việt Nam nào bán Linux desktop có quản lý cho doanh nghiệp.**
   - Đối thủ thật là Windows, thường là bản lậu.
   - Windows 10 đã hết hỗ trợ từ 14/10/2025, còn Windows 11 đòi TPM 2.0, nên nhiều máy văn phòng cũ không lên được.
   - Bkav, Viettel, CMC và các nhà cung cấp chữ ký số là đối tác tiềm năng, không phải đối thủ.
5. **Ba điểm phải sửa ngay** (đã giao sửa trong bản 0.2, hoặc đã sửa):
   - **Máy bị khôi phục trạng thái** (đóng băng, snapshot) có thể nhận lại lệnh cũ, ví dụ lệnh khởi động lại thành vòng lặp. Đã giao sửa: lệnh khởi động lại, tắt máy, khóa máy, tin nhắn phát ra trước lần khởi động hiện tại sẽ bị bỏ qua.
   - **Máy nhân bản từ một ổ đĩa** sẽ trông như cùng một máy. Đã giao sửa: so mã máy của hệ điều hành; nếu khác thì máy dừng áp thiết lập và mời ghép lại.
   - **Mẫu "Văn bản Word" tiếng Việt** dùng Liberation Serif 12, trong khi Nghị định 30/2020 yêu cầu Times New Roman 13–14. Đã sửa thành Times New Roman 13; lề trang vốn đã đúng.

## Đề xuất cho bản 0.3, theo thứ tự giá trị so với công sức

| # | Tính năng | Cho ai | Công sức |
|---|---|---|---|
| 1 | **Báo cáo bản quyền phần mềm:** từng máy và cả công ty có những phần mềm nào, giấy phép gì, nguồn từ đâu; in ra có chỗ ký | mọi doanh nghiệp, trường học | nhỏ–vừa |
| 2 | **Bộ chuyển từ Windows:** xem mục dưới | khách hàng đầu tiên | vừa |
| 3 | **USB cài máy cho công ty:** cài tự động, khởi động lần đầu là tự vào công ty, không cần nhập mã. Kèm lệnh "chuẩn bị ảnh đĩa" để nhân bản cho phòng máy | 20–100 máy, phòng máy | vừa |
| 4 | **Máy dùng chung:** phiên khách, và đóng băng kiểu Deep Freeze (khởi động lại là sạch), có giờ bảo trì để cập nhật. Chỉ dùng cho máy lễ tân, thư viện, phòng máy, không bao giờ cho máy nhân viên | trường học, lễ tân | nhỏ (phiên khách), vừa–lớn (đóng băng) |
| 5 | **Khảo sát chuyển đổi:** USB chạy thử ghi báo cáo phần cứng của máy; một script cho máy Windows liệt kê phần mềm, máy in, thiết bị, tệp macro rồi gợi ý phương án | bán hàng, chạy thử | nhỏ–vừa |
| 6 | **Báo cáo an toàn máy trạm:** tường lửa, bản vá, khóa màn hình, USB, mã hóa ổ, sao lưu, trích nhật ký; kèm mẫu đoạn nội quy báo cho nhân viên theo Luật 91/2025 | doanh nghiệp nhà nước, trường học, nhà cung cấp cho công ty FDI | nhỏ |
| 7 | **Phiếu hỗ trợ:** "Nhờ IT hỗ trợ" thành phiếu có trạng thái, người xử lý, thời gian phản hồi, kèm tình trạng máy lúc báo; xuất báo cáo tháng | IT công ty, đối tác bán dịch vụ | nhỏ–vừa |
| 8 | **Vòng đời tài sản:** trạng thái trong kho, đang dùng, sửa, thanh lý; lịch sử; nhắc hết bảo hành; in biên bản bàn giao (.docx); quy trình nhân viên nghỉ việc | kế toán, nhân sự | nhỏ–vừa |
| 9 | **Snapshot hệ thống (Timeshift) có quản lý:** tự chụp trước mỗi lần cập nhật; báo snapshot gần nhất | mọi máy | nhỏ–vừa |

**Để sau:** VPN làm việc từ xa (WireGuard), sao lưu thư mục lên NAS (restic), mã hóa ổ có giữ khóa khôi phục, quét virus ClamAV tùy chọn, chế độ kiosk, cấu hình email, Google Drive và OneDrive, hạn mức in.

## Bộ chuyển từ Windows

1. **Font:**
   - Cài sẵn Times New Roman (gói `ttf-mscorefonts-installer`, đủ tiếng Việt) và Carlito (thay Calibri).
   - Cảnh báo Caladea (thay Cambria) không có tiếng Việt.
2. **Mẫu văn bản hành chính theo Nghị định 30/2020:** công văn, quyết định, tờ trình, báo cáo, thông báo, giấy mời, biên bản, biên bản bàn giao tài sản. Hiện trong menu Mới của trình quản lý tệp.
3. **"Chuyển mã sang Unicode"** khi chuột phải vào tệp TCVN3/VNI cũ. Tệp chữ dùng UVConverter, tệp Word/Excel dùng bộ chuyển OOXML. Đổi luôn font .VnTime, VNI-Times sang Times New Roman. Không phát hành kèm font cũ.
4. **Văn phòng:**
   - ONLYOFFICE mặc định cho doanh nghiệp, LibreOffice cho ODF.
   - Thử 20 tài liệu thật trước khi hứa tương thích.
   - Hàm đọc số tiền thành chữ viết bằng VBA sẽ không chạy, cần hàm thay thế.
5. **Phần mềm chỉ có cho Windows:**
   - Ưu tiên bản web.
   - Remmina (RDP) để dùng một máy hay máy chủ Windows trong công ty (MISA SME, HTKK).
   - Công thức cài máy ảo Windows.
   - Không làm Wine cho MISA hay HTKK.
6. **Trình chuyển dữ liệu từ Windows:**
   - Chép thư mục người dùng và "Zalo Received Files", dấu trang trình duyệt.
   - Thư Outlook (.pst) chuyển sang Thunderbird.
   - Chép font người dùng đã cài thêm.
   - Hỏi kiểu gõ Telex hay VNI để đặt bộ gõ cho đúng.
7. **Hướng dẫn một trang và video ngắn tiếng Việt.**

## Dịch vụ có thể cung cấp

Dịch vụ IT thuê ngoài ở Việt Nam thường gồm hỗ trợ tại chỗ định kỳ, hỗ trợ từ xa, bảo trì máy in và mạng, diệt virus, sao lưu. Hợp đồng 6–12 tháng, tính theo người hoặc theo máy mỗi tháng.

| Dịch vụ | Cho ai | Cần gì từ mình |
|---|---|---|
| Khảo sát chuyển đổi miễn phí | doanh nghiệp đang cân nhắc | tính năng 5 và 1, mẫu báo cáo |
| Chạy thử 2–5 máy trong 2–4 tuần | công ty 10–100 máy | USB cài, danh sách kiểm tra, kênh góp ý |
| Ngày chuyển đổi qua đối tác IT địa phương | khách hàng đầu tiên | bộ chuyển đổi, đào tạo và chứng nhận đối tác |
| Video đào tạo tiếng Việt cho nhân viên và người quản trị | nhân viên, giáo viên | làm video |
| Hợp đồng hỗ trợ do đối tác vận hành, có báo cáo sức khỏe hằng tháng | doanh nghiệp nhỏ và vừa | tính năng 6 và 7 |
| Dựng máy chủ Windows cho MISA SME, HTKK | phòng kế toán | tài liệu hướng dẫn, lưu ý bản quyền |
| Danh sách máy chạy tốt, bán máy cài sẵn CaramOS qua cửa hàng | người mua máy văn phòng cũ | phòng thử máy, dữ liệu Kiểm tra driver |
| Gói phòng máy trường học | trường học | tính năng 4, Phòng máy |
| Bộ hồ sơ tuân thủ | doanh nghiệp nhà nước, nhà cung cấp FDI | tính năng 1 và 6, kèm lời miễn trừ |

Nên đi theo mô hình đối tác: đào tạo các công ty IT địa phương đang bán dịch vụ hằng tháng, thay vì tự chạy bộ phận hỗ trợ.

## Không làm

- Không tự làm phần mềm diệt virus hay EDR.
- Không ghi "đạt chuẩn" hay "đủ bản quyền" trong báo cáo.
- Không phát hành kèm font Microsoft, VNI, TCVN3; không gợi ý "RDP Wrapper".
- Không làm Wine cho MISA hay HTKK; không dịch ngược plugin token.
- Không đóng băng máy nhân viên.
- Không xóa máy từ xa, không theo dõi lén.
- Chưa làm PXE, máy chủ ảnh đĩa, quản lý in tập trung, bảng điều khiển trên đám mây.
- Không công bố tính năng trước khi có.

## Chưa xác minh

- Biện pháp chi tiết của Nghị định 331/2026.
- Hiệu lực năm 2026 của Thông tư 08/2010 và Thông tư 20/2014.
- Times New Roman và các hàm Excel trong ONLYOFFICE.
- Phiên khách trên màn hình đăng nhập của CaramOS.
- Điều khoản dùng thương mại của WPS bản Linux.
- Mức giá dịch vụ tại Việt Nam.

## Nguồn chính

- Công văn 519/BKHCN-CĐSQG: https://vpubnd.daklak.gov.vn/CMS/Content/VanBan/2026/02.2026/519.BKHCN-CDSQG%20HD.pdf
- Phạt phần mềm lậu 09/2026: https://tienphong.vn/cai-phan-mem-trai-phep-bi-phat-15-trieu-dong-post1877778.tpo
- Nghị định 341/2025: https://luatvietnam.vn/tin-van-ban-moi/tu-15-02-2026-vi-pham-hanh-chinh-ve-quyen-tac-gia-quyen-lien-quan-phat-toi-da-500-trieu-dong-186-106310-article.html
- Đoàn kiểm tra 05/2026: https://hatinh.gov.vn/vi/bai-viet/lap-doan-kiem-tra-doanh-nghiep-dung-phan-mem-lau
- Nghị định 331/2026: https://moc.gov.vn/vn/tin-tuc/1305/96479/bien-phap-bao-ve-an-ninh-mang-doi-voi-he-thong-thong-tin.aspx
- Thông tư 12/2022: https://www.qtsc.com.vn/uploads/files/2022/09/06/12_2022_TT-BTTTT.pdf
- Thông tư 20/2014: https://caselaw.vn/van-ban-phap-luat/264293-thong-tu-20-2014-tt-btttt-ve-san-pham-phan-mem-nguon-mo-duoc-uu-tien-mua-sam-su-dung-trong-co-quan-to-chuc-nha-nuoc-do-bo-truong-bo-thong-tin-va-truyen-thong-ban-hanh
- Nghị định 30/2020, thể thức văn bản: https://luatvietnam.vn/hanh-chinh/the-thuc-van-ban-570-94255-article.html
- Windows 10 hết hỗ trợ: https://www.microsoft.com/vi-vn/windows/end-of-support
- Ransomware tại Việt Nam năm 2024: https://vietnamnet.vn/en/over-155-000-computers-in-vietnam-hit-by-ransomware-attacks-in-2024-2384268.html
- UVConverter: https://www.unikey.org/source.html
- Deep Freeze: https://fptshop.com.vn/tin-tuc/danh-gia/deep-freeze-enterprise-188531
- Biên bản bàn giao tài sản: https://amis.misa.vn/33907/bien-ban-ban-giao-tai-san/
