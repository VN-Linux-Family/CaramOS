# CaramOS trên Unikorn: hiện trạng, khoảng trống và bản nháp để đăng

Ngày khảo sát: 18/11/2026. Chỉ đọc, không đăng nhập, không đăng gì.

Nguồn đối chiếu:
- **unikorn.vn:** trang sản phẩm, tab Cập nhật, Feedback, Lộ trình, Talk, bài review, bình luận, sitemap, llms.txt, trang Dành cho maker, FAQ, Quy tắc cộng đồng, bài blog về MCP, metadata OAuth.
- **Repo CaramOS** tại tag `v1.3.11`: README, các tệp manifest của migration, scripts.
- **Repo landing `CaramOSLanding`** (commit 25237ab). Trang đang chạy đã là 1.3.11.
- **GitHub Releases** của CaramOS và App Center.

Tóm tắt nhanh:
- Trên Unikorn, CaramOS vẫn ở **v1.0.20**: changelog cuối ngày 06/10/2026, mô tả viết theo góc nhìn build ISO, 4 ảnh từ thời **CaramOS 0.1**, chỉ 1 Talk (06/2026). Thực tế CaramOS đã lên **1.3.11** (17/11/2026) và là bản chính thức từ 1.3.0. Còn thiếu 12 bản phát hành.
- Bài review của đội Unikorn (02/09/2026) được ghim trên trang sản phẩm và có mấy điều không còn đúng: 1.0.16, Open Beta, Chrome/WPS/Zalo cài sẵn.
- Bản nháp trong báo cáo: 1 cập nhật thông tin sản phẩm, 12 changelog (kèm phương án gộp 1 bài), 10 Talk, 6 trả lời hoặc bình luận đăng tay.

---

## 1. Unikorn là gì và CaramOS đang hiện ra thế nào

### 1.1 Unikorn

Unikorn (https://unikorn.vn) là nơi maker Việt ra mắt sản phẩm công nghệ, giống Product Hunt. Theo https://unikorn.vn/llms.txt, trang có khoảng 2.069 sản phẩm, 12.164 người dùng và 147 danh mục. Người dùng clap (bình chọn có trọng số 1.0x–6.0x theo level), bình luận và đánh giá sao. Sản phẩm xếp hạng theo ngày, tuần, tháng, năm và mọi thời gian (giờ Việt Nam).

Các loại nội dung gắn với một sản phẩm:

| Loại | Địa chỉ | Trường chính |
|---|---|---|
| Trang sản phẩm | `/p/{slug}` | tên, tagline, mô tả (rich text), logo, ảnh, video, nút Truy cập (URL), liên kết (Facebook, GitHub, website...), danh mục, thẻ, công nghệ, maker |
| Cập nhật (changelog) | `/p/{slug}/updates` | `title`, `content` (HTML), `versionTag`, `images`, `contributorIds`, `feedbackIds`; ngày đăng là lúc đăng |
| Feedback | `/p/{slug}/feedback` | báo lỗi, đề xuất, góp ý; người dùng bình chọn; maker gán trạng thái và mức ưu tiên |
| Lộ trình | `/p/{slug}/roadmap` | dựng từ trạng thái feedback (Đang xem xét, Sắp tới, Đang thực hiện); feedback xong thì rời lộ trình |
| Talk | `/t/{slug}/...` | tiêu đề, nội dung, ảnh bìa, thẻ (Thảo luận, Thông báo, Góp ý, Hỏi đáp, Báo lỗi hoặc thẻ tự đặt) |
| Đánh giá & bình luận | trên trang sản phẩm | đánh giá có sao và tiêu đề, bình luận, trả lời |
| Khác | | bộ sưu tập, Blog và Reviews do đội Unikorn viết, Contests, bảng xếp hạng, badge nhúng |

Changelog hoạt động thế nào:
- Khi đăng, gắn các feedback đã xử lý thì chúng tự chuyển sang "đã xong".
- Người đã clap, bình luận hoặc theo dõi sản phẩm nhận thông báo. CaramOS có 223 người theo dõi cập nhật.
- Phiên bản hiện cạnh tên sản phẩm lấy từ `versionTag` của changelog mới nhất.

MCP, theo bài blog 25/10/2026, trang Dành cho maker và FAQ:
- Địa chỉ `https://unikorn.vn/api/mcp`, dùng OAuth. Metadata ở `/.well-known/oauth-authorization-server` và `/.well-known/oauth-protected-resource`. Scope là `account:read account:write posts:write`, có đăng ký client động.
- Chỉ dành cho maker có sản phẩm đã duyệt. AI Agent đọc được dữ liệu Unikorn và, khi được cho phép, có thể:
  - đăng Talk;
  - đăng changelog;
  - gửi sản phẩm mới;
  - sửa thông tin sản phẩm của mình. Sửa sản phẩm vẫn qua bước duyệt như trên web.
- Các trang này không nhắc tới bình luận, trả lời bình luận hay đổi trạng thái feedback qua MCP. Vì vậy các bản nháp loại đó để ở mục "đăng tay".

Luật cần giữ khi đăng (Quy tắc cộng đồng, áp dụng cả với nội dung đăng qua MCP):
- 5.2: không dán link sản phẩm vào bình luận của sản phẩm khác hay Talk không liên quan.
- 5.3: không đăng cùng một nội dung quảng bá ở nhiều nơi.
- 5.4: Talk là để thảo luận, bài chỉ quảng cáo có thể bị gỡ.
- Talk đăng qua AI Agent chỉ được tính điểm một số bài mỗi ngày (tăng theo level). Đăng hàng loạt có thể bị báo cáo.
- 2.3: người có liên quan tới sản phẩm nên nói rõ khi bình luận.

### 1.2 CaramOS trên Unikorn hôm nay (18/11/2026)

**Trang sản phẩm: https://unikorn.vn/p/caramos** (product id `10e9fcdf-6914-4940-89c2-67a3765a64d9`)
- Phiên bản hiển thị **v1.0.20**. Tagline: "Linux OS cho người Việt phát triển bởi cộng đồng".
- Mô tả hiện tại, nguyên văn:
  > CaramOS là bản phân phối Linux dựa trên Linux Mint 22.3 Cinnamon (Ubuntu 24.04 LTS), được thiết kế đặc biệt cho người dùng Việt Nam. Dự án được build theo hướng ISO remaster: bung ISO Linux Mint gốc, tuỳ biến rootfs bằng packages/overlay/hooks, rồi đóng gói lại thành ISO CaramOS.
  >
  > Mục tiêu của CaramOS là phổ thông hoá Linux — giúp người dùng Việt chuyển từ Windows sang Linux dễ hơn, có sẵn giao diện thân thiện, bộ gõ tiếng Việt, trình duyệt, ứng dụng văn phòng và các tiện ích quen thuộc.
- 4 ảnh, đều từ CaramOS 0.1 (05/2026):
  - menu khởi động "Welcome to CaramOS 0.1 64-bit";
  - logo lúc khởi động;
  - neofetch ghi "CaramOS 0.1 Cinnamon";
  - màn hình chính hoa sen, có Chrome, WPS Office, Zalo ngoài Desktop.
- Nút Truy cập: https://caramos.vietnamlinuxfamily.net/ (đúng). Liên kết: Facebook (nhóm vietnamlinuxcommunity), GitHub (VN-Linux-Family/CaramOS), VNLF.
- Danh mục: Tiện ích dev. Thẻ: linux, os. Công nghệ: Bash. Có trong 1 bộ sưu tập.
- Ra mắt 19/05/2026. Huy hiệu: #1 Ngày 19/05, #1 Tuần 24/05, #1 Tháng 05/2026.
- Số liệu: 518 điểm (hạng #7 theo trang), 206 clap, 6.335 lượt xem, 29 đánh giá đều 5 sao, 23 bình luận (104 nếu tính cả trả lời), 223 người theo dõi cập nhật.

**Cập nhật: https://unikorn.vn/p/caramos/updates** (8 mục):

| versionTag | Tiêu đề | Ngày đăng | Ảnh |
|---|---|---|---|
| v1.0.20 | fix lỗi chuyển ngôn ngữ | 06/10/2026 | 0 |
| v.1.0.19 | fix lỗi boot và grub | 06/10/2026 | 0 |
| v1.0.18 | Add dark mode và fix 1 số lỗi trong core | 06/10/2026 | 1 |
| 1.0.16 | Thêm Control center, sửa wallpaper CaramOS brand, sửa task bar 3 island docks | 06/08/2026 | 1 |
| v1.0.10 | Phát hành CaramOs-OTA | 26/06/2026 | 1 |
| v1.0.4 | fix source name từ caram -> mint,ubuntu | 08/06/2026 | 0 |
| V1.0.3 | Nâng cấp Zram | 23/05/2026 | 0 |
| v1.0.2 | Thay đổi brand mint -> caram ở app welcome | 21/05/2026 | 4 |

**Feedback / Lộ trình:** có 4 mục, 3 mục đã xong. Mục còn mở đang ở cột "Sắp tới":
- đề xuất cài LibreOffice thay vì WPS;
- feedback #4, id `594e8e62-c156-4f24-b1f5-dd727c4798a9`;
- 3 lượt bình chọn, nhiều nhất trong các feedback; gửi 08/06/2026; trạng thái PLANNED.

**Talk:** chỉ 1 bài, "Quanh tôi quá nhiều người vẫn đang dùng Windows lậu" (10/06/2026, 4 thích, 4 trả lời): https://unikorn.vn/t/caramos/quanh-toi-qua-nhieu-nguoi-van-da

**Bài review của đội Unikorn** (02/09/2026, 1.627 lượt xem, 3 bình luận): https://unikorn.vn/reviews/caramos-ban-linux-thuan-viet-co-dang-de-ban-roi-windows
- Thanh thông báo trên trang sản phẩm dẫn tới bài này.
- Bài ghi:
  - phiên bản 1.0.16, dòng 1.0.x là "Open Beta";
  - Chrome, WPS Office, Zalo cài sẵn;
  - Zalo lỗi gửi file 2–3 MB;
  - góp ý thay WPS bằng LibreOffice;
  - SourceForge tải chậm;
  - cấu hình tối thiểu "CPU 2 nhân, RAM 4 GB, 30 GB".
- Maker không sửa được bài này.

**Bình luận còn bỏ ngỏ** (không ghi tên):
- Bình luận ngày 26/10/2026 nhắc lại chuyện tải SourceForge chậm, chưa ai trả lời.
- Hỏi về DingTalk (19/05), chưa trả lời. Không có gì đã phát hành để trả lời.
- Đánh giá 21/05 góp ý nên có tiếng Anh. Việc này đã xong từ 1.0.20.
- Trong bài review có câu hỏi về ARM64 và maker đã trả lời. Chưa phát hành nên không nhắc.

**Cập nhật gần nhất trên Unikorn:**
- changelog v1.0.20, 06/10/2026 lúc 10:29;
- Talk 10/06/2026;
- trả lời gần nhất của maker 05/11/2026 (trong bài review).

### 1.3 Đã xem được và chưa xem được

Đã xem được, không cần đăng nhập: mọi trang kể trên. Tab Cập nhật, Feedback và bình luận được trang tải sau, nên mình đọc qua chính các địa chỉ JSON công khai mà trang gọi (chỉ đọc), ví dụ `/api/products/{id}/changelog`, `/feedback`, `/comments`.

Chưa xem được:
- **Danh sách công cụ MCP:** gọi `/api/mcp` không có token thì nhận 401.
- **Bảng điều khiển maker:** giới hạn độ dài trong form, tình trạng chờ duyệt, thống kê.
- **Nội dung riêng:** changelog nháp nếu có, tin nhắn, thông báo.

Dữ liệu thô: `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/unikorn/web/`

---

## 2. Khoảng trống so với thực tế

Ngày phát hành các bản thiếu trên Unikorn:

| Bản | Ngày |
|---|---|
| 1.3.0 | 16/10 |
| 1.3.1 | 17/10 |
| 1.3.2 | 19/10 |
| 1.3.3 | 22/10 |
| 1.3.4 | 05/11 |
| 1.3.5 | 06/11 |
| 1.3.6 | 07/11 |
| 1.3.7 | 09/11 |
| 1.3.8 | 11/11 |
| 1.3.9 | 12/11 |
| 1.3.10 | 17/11 |
| 1.3.11 | 17/11 |

| Mục | Trên Unikorn | Thực tế | Bản nháp |
|---|---|---|---|
| Phiên bản | v1.0.20 | 1.3.11, thiếu 12 bản | 3.2 |
| Trạng thái | review ghi "Open Beta" | bản chính thức từ 1.3.0 | 3.1, 3.2, R5 |
| Mô tả | về cách build ISO, không nêu tính năng | App Center, Kiểm tra driver, Trung tâm cập nhật, Control Center, Góp ý & hỗ trợ, máy in Canon, nhẹ hơn Mint, có tiếng Anh | 3.1 |
| Ứng dụng có sẵn | Chrome, WPS, Zalo cài sẵn | ISO chỉ có Firefox; còn lại chọn trong App Center (ONLYOFFICE chọn sẵn, có WPS, LibreOffice) | 3.1, C1, T2 |
| Ảnh | 4 ảnh CaramOS 0.1 | ảnh 1.3 trên landing | 3.1 |
| Feedback LibreOffice | PLANNED | cài một nút trong App Center từ 1.3.0 | C1, R1 |
| Danh mục | Tiện ích dev | hệ điều hành cho người dùng phổ thông | 3.1 (tùy chọn) |
| Thẻ | linux, os | thêm open-source, tieng-viet, mien-phi, made-in-vietnam, desktop (đều đã có trên Unikorn) | 3.1 |
| Công nghệ | Bash | Bash, Python, GTK 4, libadwaita, JavaScript | 3.1 |
| versionTag cũ | "v.1.0.19", "V1.0.3", "1.0.16" | dạng vX.Y.Z như tag GitHub | dùng vX.Y.Z; sửa tag cũ nếu MCP cho (tùy chọn) |
| Cấu hình tối thiểu | review ghi RAM 4 GB, 30 GB | 64-bit, RAM 2 GB (khuyên 4 GB), ổ trống 20 GB, USB 4 GB | 3.1, R5 |
| Talk | 1 bài từ tháng 6 | chưa có bài nào về 1.3.x | T1–T10 |
| Bình luận | câu hỏi tải chậm chưa trả lời | ISO 2,8 GB; máy đã cài không cần tải lại | R2 |
| Ảnh 1.3.11 | | chưa có ảnh ô Màu nhấn hay thư mục Việt Nam mỗi ngày; ảnh Control Center trên landing chụp trước khi có Màu nhấn | nên chụp mới (tùy chọn) |

Không cần đăng lại các bản Open Beta 1.0.5–1.0.15. Nội dung chính đã có trong các mục v1.0.10 và 1.0.16, và ghi chú đầy đủ có trên landing.

---

## 3. Bản nháp, theo thứ tự đăng

### 3.0 Thứ tự và nhịp đăng

Ngày 1:
1. Sửa thông tin sản phẩm (3.1). Phần này chờ Unikorn duyệt.
2. Đăng 12 changelog từ v1.3.0 tới v1.3.11, để v1.3.11 là mục mới nhất và hiện cạnh tên sản phẩm.
   - Gắn feedback #4 vào v1.3.0 nếu bạn đồng ý đánh dấu nó xong.
   - Mỗi changelog gửi thông báo tới 223 người. Muốn ít thông báo hơn thì dùng phương án B.
3. Đăng T1, sau khi đã có changelog.
4. Đăng tay R1–R6 nếu MCP không làm được.

Ngày 2–10: mỗi ngày một Talk, T2 tới T10. Bài nào cũng kết bằng một câu hỏi thật, để giữ tinh thần "Talk là để thảo luận".

Định dạng:
- Bản nháp viết dạng văn bản thường, gạch đầu dòng "- ".
- Nếu MCP nhận HTML, đổi đoạn thành `<p>`, danh sách thành `<ul><li>`.
- Ngày đăng changelog là ngày bạn đăng, nên câu đầu mỗi bài ghi ngày phát hành thật.

Ảnh gợi ý đều có ở `https://caramos.vietnamlinuxfamily.net/assets/screenshots/<tệp>`. Mình đã kiểm tra, đều trả 200. Tệp gốc ở `/home/dungleviet/Documents/CaramOS/CaramOSLanding/public/assets/screenshots/`.

### 3.1 Cập nhật thông tin sản phẩm

**Tên:** giữ "CaramOS".

**Tagline:** giữ như cũ. Tùy chọn:
```text
Hệ điều hành Linux miễn phí cho người Việt, cài ứng dụng và driver bằng một nút
```

**Mô tả (bản đầy đủ, trả lời đủ 6 ý Unikorn yêu cầu):**
```text
CaramOS là hệ điều hành Linux miễn phí, mã nguồn mở (GPL-3.0), làm riêng cho người dùng Việt Nam. CaramOS dựa trên Linux Mint 22.3 Cinnamon và Ubuntu 24.04 LTS, được cập nhật bảo mật đến năm 2029. Bản mới nhất là 1.3.11 (17/11/2026). Từ bản 1.3.0, CaramOS là bản phát hành chính thức; các bản 1.0.x trước đó là Open Beta.

CaramOS giải quyết việc gì
Nhiều người muốn rời Windows nhưng ngại phải tự cài bộ gõ, tìm phần mềm, dò driver. CaramOS làm sẵn những việc đó để bạn dùng máy hằng ngày mà không phải mở Terminal.

Tính năng chính
- Tiếng Việt từ đầu: giao diện, múi giờ, định dạng ngày giờ Việt Nam; bộ gõ Fcitx5 + Lotus bật sẵn (Telex mặc định, có VNI), Ctrl+Shift để chuyển Anh/Việt. Cần tiếng Anh thì đổi trong Cài đặt > Ngôn ngữ, cả hệ thống theo.
- App Center: lần đăng nhập đầu tiên, bạn chọn bộ văn phòng (ONLYOFFICE, WPS Office, LibreOffice), trình duyệt (Chrome, Cốc Cốc, Edge, Brave, Firefox), Zalo, Telegram, Zoom, Teams for Linux, Discord, font Microsoft, VLC, OBS Studio, RustDesk, GIMP, Thunderbird. CaramOS tải và cài giúp; mỗi ứng dụng ghi rõ ưu, nhược điểm, dung lượng và nguồn cài.
- Kiểm tra driver: chạy thử từ USB là biết máy có hợp không, trước khi cài. Kiểm tra Wi-Fi, mạng dây, đồ họa, âm thanh, Bluetooth, webcam, đầu đọc vân tay; cài driver NVIDIA và Wi-Fi Broadcom bằng một nút. Máy in laser Canon dùng CAPT (LBP2900, LBP3300, LBP6300dn...) cũng được cài driver giúp, kể cả máy in qua mạng LAN.
- Trung tâm cập nhật: máy cài từ bản cũ lên được bản mới nhất mà không cài lại, không mất dữ liệu. Không có gì tự cài khi bạn chưa bấm Cập nhật ngay.
- Control Center: âm lượng, Wi-Fi, Bluetooth, VPN, chế độ tối, ánh sáng đêm, chế độ nguồn, màu nhấn, độ sáng và pin trong một bảng ở góc phải thanh tác vụ.
- Góp ý & hỗ trợ: dấu hỏi trên thanh tác vụ để nhờ cộng đồng Vietnam Linux Family giúp, báo lỗi hoặc góp ý, kèm ảnh chụp màn hình và hồ sơ phần cứng nếu bạn đồng ý.
- Quen tay như Windows: thanh tác vụ ba đảo (Start Menu bên trái, ứng dụng ở giữa, khay hệ thống bên phải), Start Menu tìm ứng dụng bằng tiếng Việt và gõ không dấu vẫn ra, PrtSc hoặc Win+Shift+S để chụp màn hình. Có hình nền Việt Nam mỗi ngày nếu bạn chọn.
- Nhẹ: máy rảnh dùng khoảng 865 MiB RAM, Linux Mint 22.3 gốc dùng 941 MiB (đo trên cùng một máy ảo); earlyoom đóng ứng dụng tốn RAM nhất thay vì để máy treo; ISO 2,8 GB.

Ai nên dùng
Người dùng phổ thông, dân văn phòng, gia đình, người có máy cũ cần chạy nhẹ, và bạn nào muốn thử Linux mà không phải tự cấu hình nhiều.

Bắt đầu thế nào
Máy 64-bit (UEFI hoặc BIOS), RAM từ 2 GB (khuyên dùng 4 GB), ổ trống từ 20 GB, USB từ 4 GB. Tải ISO ở trang chủ, ghi ra USB bằng balenaEtcher, Ventoy hoặc Rufus, chạy thử rồi mở Cài đặt CaramOS trên Desktop. Máy đang dùng CaramOS 1.0.2 trở lên chỉ cần bấm Cập nhật ngay trong Trung tâm cập nhật.

Khác gì cài thẳng Linux Mint hay Ubuntu
CaramOS giữ nguyên nền Linux Mint và Ubuntu LTS cùng kho phần mềm của chúng, rồi làm sẵn những việc người dùng Việt hay phải tự làm: bộ gõ cấu hình sẵn, chọn ứng dụng quen thuộc trong một trang, Kiểm tra driver (cả máy in Canon), cập nhật không cần cài lại, và kênh hỏi đáp bằng tiếng Việt ngay trên máy. CaramOS do cộng đồng Vietnam Linux Family phát triển công khai trên GitHub.

Trang chủ và ghi chú phát hành: https://caramos.vietnamlinuxfamily.net
Mã nguồn: https://github.com/VN-Linux-Family/CaramOS
```

**Mô tả (bản ngắn, nếu form giới hạn):**
```text
CaramOS là hệ điều hành Linux miễn phí, mã nguồn mở cho người Việt, dựa trên Linux Mint 22.3 Cinnamon và Ubuntu 24.04 LTS (cập nhật bảo mật đến 2029). Bản mới nhất 1.3.11 có sẵn tiếng Việt và bộ gõ Fcitx5 + Lotus; App Center để chọn và cài ONLYOFFICE, WPS Office, LibreOffice, Chrome, Zalo, Zoom...; Kiểm tra driver cho biết máy có hợp không ngay khi chạy thử từ USB và cài driver NVIDIA, Wi-Fi Broadcom, máy in Canon giúp bạn; Trung tâm cập nhật nâng cấp không cần cài lại; Control Center và Góp ý & hỗ trợ ngay trên thanh tác vụ. Nhẹ hơn Linux Mint gốc, không treo khi hết RAM. Cần máy 64-bit, RAM từ 2 GB. Tải tại https://caramos.vietnamlinuxfamily.net
```

**Ảnh (thay cả 4 ảnh cũ):**
1. `first-login.webp` — Lần đăng nhập đầu tiên: App Center và Kiểm tra driver
2. `desktop-dark.webp` — Chế độ tối và Control Center
3. `app-center.webp` — App Center: chọn bộ văn phòng
4. `driver-check.webp` — Kiểm tra driver
5. `printer-canon-driver-check.webp` — Cài driver máy in Canon
6. `update-center-131.webp` — Trung tâm cập nhật
7. `help-form.webp` — Góp ý & hỗ trợ
8. `boot-menu-131.webp` — Menu khởi động

**Thẻ:** linux, os, open-source, tieng-viet, mien-phi, made-in-vietnam, desktop.

**Công nghệ:** Bash, Python, GTK 4, libadwaita, JavaScript.

**Danh mục (tùy chọn):** đổi "Tiện ích dev" sang "Desktop Utilities" hoặc "Tối ưu hệ thống" (nơi Spark Linux đang nằm). Đổi có thể phải duyệt lại.

**Liên kết:** giữ nguyên. Nếu form có ô thì thêm Telegram https://t.me/vietnamlinuxfamily và Discord https://discord.gg/gVAJDUMC2n.

### 3.2 Changelog (đăng v1.3.0 trước, v1.3.11 sau cùng)

#### C1. v1.3.0
- **versionTag:** `v1.3.0`
- **Tiêu đề:** Bản phát hành chính thức đầu tiên: App Center, Kiểm tra driver, Góp ý & hỗ trợ
- **Ảnh:** `first-login.webp`
- **Gắn feedback (nếu đồng ý):** #4
```text
Phát hành ngày 16/10/2026. Đây là bản phát hành chính thức đầu tiên của CaramOS; các bản 1.0.x trước đó là Open Beta.

- App Center: lần đăng nhập đầu tiên, bạn chọn bộ văn phòng (ONLYOFFICE, WPS Office, LibreOffice), trình duyệt (Chrome, Cốc Cốc, Edge, Brave, Firefox), ứng dụng liên lạc (Zalo, Telegram, Zoom, Teams for Linux, Discord) và tiện ích (font Microsoft, VLC, OBS Studio, RustDesk, GIMP, Thunderbird). Bấm Cài một lần rồi dùng máy bình thường trong lúc CaramOS tải và cài. Gỡ ứng dụng ngay trên thẻ của nó.
- LibreOffice, góp ý được bình chọn nhiều nhất ở mục Feedback, giờ cài bằng một nút trong App Center. ISO mới không cài sẵn WPS Office, Chrome và Zalo nữa; máy cập nhật từ bản cũ vẫn giữ các ứng dụng đang có.
- Kiểm tra driver: kiểm tra Wi-Fi, mạng dây, đồ họa, âm thanh, Bluetooth, webcam và đầu đọc vân tay; cài driver NVIDIA và Wi-Fi Broadcom bằng một nút, đúng bản Ubuntu khuyên dùng cho máy. Ứng dụng tự mở khi chạy thử từ USB và ở lần đăng nhập đầu tiên, nên bạn biết máy có hợp với CaramOS không trước khi cài.
- Góp ý & hỗ trợ: dấu hỏi ở góc phải thanh tác vụ để nhờ giúp đỡ, báo lỗi hoặc góp ý tới cộng đồng Vietnam Linux Family, kèm ảnh hoặc video; theo dõi tình trạng và nhận thông báo khi có câu trả lời.
- Trung tâm cập nhật được thiết kế lại, nút Cập nhật ngay luôn nằm ở đáy cửa sổ.
- Nhẹ hơn Linux Mint 22.3 gốc: ít dịch vụ nền và ít RAM hơn; earlyoom đóng ứng dụng tốn RAM nhất thay vì để cả máy đơ. ISO còn 2,8 GB.
- CopyQ không còn tự chạy khi đăng nhập; bỏ 14 màu biểu tượng không dùng, giải phóng khoảng 1,1 GB ổ đĩa.

Máy đang dùng CaramOS nhận các thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C2. v1.3.1
- **versionTag:** `v1.3.1`
- **Tiêu đề:** Start Menu và Trung tâm cập nhật toàn tiếng Việt
- **Ảnh:** `start-menu-131.webp`
```text
Phát hành ngày 17/10/2026.

- Start Menu hiện "Tất cả ứng dụng", "Biểu tượng cảm xúc" thay cho chữ tiếng Anh. Applet thời tiết và các tiện ích mở rộng đi kèm cũng theo ngôn ngữ của máy, từ lần đăng nhập sau.
- Trung tâm cập nhật: dòng dung lượng của bản cập nhật không còn lẫn chữ tiếng Anh.
- App Center 0.2.1: thẻ Zalo ghi "Gói cộng đồng", vì bản Zalo cho Linux này do cộng đồng đóng gói chứ không phải do Zalo phát hành.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C3. v1.3.2
- **versionTag:** `v1.3.2`
- **Tiêu đề:** Zalo gọi thoại, gọi video ngay trên Linux; thanh tác vụ gọn lại
```text
Phát hành ngày 19/10/2026.

- Zalo cho Linux bản mới (26.10.11) gọi thoại, gọi video ngay trên Linux, không cần Wine nên mở nhanh hơn. App Center 0.2.2 cài bản này. Máy đã có Zalo do CaramOS hoặc App Center cài thì được Trung tâm cập nhật đổi sang: Zalo tải ngầm, tự thử lại mỗi ngày nếu mạng chập chờn, tin nhắn và tài khoản giữ nguyên.
- Sau khi Linux Mint cập nhật Cinnamon 6.6.9, biểu tượng giữa thanh tác vụ to ra, tràn khỏi khung. Giờ chúng nằm gọn lại, và từ nay CaramOS tự sửa lại mỗi khi Cinnamon được cập nhật.
- Kiểm tra driver không còn làm đứng máy cũ khi chạy thử từ USB, và nói rõ vì sao loa, micro, camera chưa chạy trên máy tính bảng chip Intel Atom.
- App Center hay Trung tâm cập nhật cài không được thì nút Nhờ giúp đỡ gửi yêu cầu kèm nhật ký lỗi. Chỉ đội VNLF xem được nhật ký, thông tin cá nhân được xoá trước khi gửi.
- Trình cài đặt không còn dừng ngay khi mở, và không còn khoá việc cài phần mềm khác trong phiên chạy thử.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C4. v1.3.3
- **versionTag:** `v1.3.3`
- **Tiêu đề:** Gõ được tiếng Việt ngay khi đăng nhập
- **Ảnh:** `installer-lotus.webp`
```text
Phát hành ngày 22/10/2026.

- Trên một số máy mới cài CaramOS 1.3 và khi chạy thử từ USB, bộ gõ Lotus không tự chạy: khay hệ thống không có chữ V và gõ Telex chỉ ra chữ không dấu. Giờ bộ gõ tự chạy mỗi lần đăng nhập.
- Máy đang bị lỗi này chỉ cần bấm Cập nhật ngay trong Trung tâm cập nhật là gõ được liền, không cần đăng nhập lại.
- Ctrl+Shift vẫn chuyển giữa tiếng Việt (V) và tiếng Anh (A); cài đặt bộ gõ của bạn được giữ nguyên.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C5. v1.3.4
- **versionTag:** `v1.3.4`
- **Tiêu đề:** Bộ gõ giữ cài đặt, Start Menu nhanh hơn, cập nhật không bị chặn
```text
Phát hành ngày 05/11/2026.

- Cài đặt bộ gõ Lotus bạn chọn (Telex hay VNI, chế độ gõ, kiểm tra chính tả, phím tắt) không còn bị đặt lại mỗi lần đăng nhập. Mỗi phiên bắt đầu ở tiếng Việt (V); bấm Ctrl+Shift để chuyển sang tiếng Anh.
- Ô tìm kiếm của Start Menu ra kết quả ngay khi đang gõ tiếng Việt, kể cả chữ có dấu.
- Tìm tệp trong Start Menu không còn làm đơ máy, kể cả trên ổ cứng HDD hay khi có Google Drive gắn trong thư mục Home.
- Trung tâm cập nhật không còn bị chặn bởi một nguồn phần mềm hỏng do chương trình khác thêm vào, hay một gói cài dở như bản Lotus 3.5.6 lỗi hoặc driver NVIDIA 470.
- Kiểm tra driver đề xuất driver NVIDIA 580 thay cho 470 (bản 470 không chạy được trên nhân Linux 6.14 trở lên), và nói rõ khi driver đồ họa bị tắt bởi nomodeset hay blacklist.
- App Center 0.2.3 cài được ứng dụng khi máy còn gói cài dở, chờ trình cài CaramOS khi chạy thử từ USB, và tải tiếp WPS Office khi máy chủ ngắt giữa chừng.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C6. v1.3.5
- **versionTag:** `v1.3.5`
- **Tiêu đề:** Cài driver NVIDIA bằng Kiểm tra driver chạy được trở lại
- **Ảnh:** `driver-check.webp`
```text
Phát hành ngày 06/11/2026.

- Từ 1.3.0, Kiểm tra driver làm lần cài driver NVIDIA dừng giữa chừng: sau khi khởi động lại, máy không có driver đồ họa và màn hình chỉ còn 1024×768. Bản 1.3.5 sửa lỗi này.
- Máy đã bị như vậy được bản cập nhật tự sửa. Nếu cần sửa tay: mở Terminal, chạy sudo dpkg --configure -a rồi khởi động lại.
- Trước khi cài, Kiểm tra driver xem ổ đĩa còn đủ chỗ không và nói rõ cần dọn bao nhiêu, ở đâu. Driver NVIDIA có thể kéo theo nhân Linux mới, khi đó phải tải về khoảng 1 GB.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C7. v1.3.6
- **versionTag:** `v1.3.6`
- **Tiêu đề:** Trung tâm cập nhật không còn đứng hình khi cập nhật dài
- **Ảnh:** `update-progress.webp`
```text
Phát hành ngày 07/11/2026.

- Lần cập nhật hoàn tất một driver NVIDIA bị cài dở in ra khoảng 49.000 dòng nhật ký, và cửa sổ Trung tâm cập nhật từng đứng hơn 15 phút. Giờ chừng đó dòng hiện ra trong chưa tới một giây.
- Khung nhật ký luôn cuộn tới dòng mới nhất; trang kết quả vẫn có đủ nhật ký.
- Máy đang ở bản cũ hơn 1.3.6 thì lần cập nhật này vẫn chạy trong cửa sổ của bản đang dùng. Nếu máy có driver NVIDIA cài dở, nên chạy sudo dpkg --configure -a trước; nếu cửa sổ đứng thì cứ để nó chạy xong, đừng tắt máy.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C8. v1.3.7
- **versionTag:** `v1.3.7`
- **Tiêu đề:** Máy in Canon LBP2900 cài driver bằng một nút
```text
Phát hành ngày 09/11/2026.

- Cắm máy in vào là có thông báo "Máy in chưa có driver". Bấm Xem chi tiết rồi Cài driver máy in, máy in tự được thiết lập. Trước đây hệ thống gán cho các máy in Canon dùng CAPT một driver PostScript không hợp: lệnh in báo xong mà máy không ra giấy.
- Driver là captdriver, mã nguồn mở. Theo captdriver, LBP2900/LBP2900B và LBP3010/LBP3018/LBP3050 chạy được; LBP3000, LBP3100 và LBP6000 mới ở mức thử nghiệm. Các máy Canon CAPT khác cần driver của Canon (có từ bản 1.3.9).
- Cài driver không được thì màn hình báo lỗi có nút Nhờ giúp đỡ, kèm nhật ký cài đặt. Máy có máy in thì yêu cầu giúp đỡ tự kèm nhật ký máy in, đã bỏ số serial và tên tài liệu.
- Rút máy in hay USB Wi-Fi ra không còn bị báo nhầm "Đã xử lý xong vấn đề phần cứng".

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C9. v1.3.8
- **versionTag:** `v1.3.8`
- **Tiêu đề:** Giữ Ctrl rồi lăn chuột để phóng to, thu nhỏ icon trong Start Menu
```text
Phát hành ngày 11/11/2026.

- Như trên Windows: mở Start Menu, giữ Ctrl rồi lăn chuột trên danh sách ứng dụng. Lăn lên thì icon to dần, lăn xuống thì nhỏ dần, mỗi nấc một chút.
- Icon nhỏ thì mỗi hàng xếp được nhiều ứng dụng hơn (tới 7), icon to thì ít hơn. Cỡ mặc định vẫn như cũ.
- Start Menu vẫn mở, giữ nguyên mục hay kết quả tìm kiếm đang xem, và nhớ cỡ bạn chọn cho lần sau. Áp dụng ngay, không cần đăng nhập lại.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C10. v1.3.9
- **versionTag:** `v1.3.9`
- **Tiêu đề:** Driver Canon chính hãng cho LBP6300dn và các máy CAPT khác; PrtSc chụp màn hình
- **Ảnh:** `printer-canon-driver-check.webp`
```text
Phát hành ngày 12/11/2026.

- Kiểm tra driver cài driver chính hãng của Canon cho các máy in Canon dùng CAPT mà captdriver chưa chạy được, như LBP6300dn, LBP3300, LBP5000, LBP6200, LBP7200C. Máy cắm USB: cắm vào là có thông báo, bấm Cài driver của Canon, đồng ý điều khoản của Canon, khoảng một phút sau máy in đã sẵn sàng.
- Máy in qua mạng LAN: trong Kiểm tra driver bấm Thêm máy in…, chọn mẫu máy rồi nhập địa chỉ IP của máy in.
- Driver được tải thẳng từ máy chủ của Canon và kiểm tra trước khi cài. CaramOS lo hàng đợi in, cho dịch vụ in tự chạy khi bật máy, rút ra cắm lại vẫn in được, và chặn máy khác trong mạng kết nối vào dịch vụ in. Điều khoản của Canon cho phép dùng cho mục đích cá nhân, phi thương mại.
- Bấm PrtSc hoặc Win+Shift+S để chụp màn hình (trước đây hai phím này không có tác dụng): kéo chọn vùng, Ctrl+C để chép ảnh rồi dán vào Zalo hay Messenger, Ctrl+S để lưu vào thư mục Ảnh.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C11. v1.3.10
- **versionTag:** `v1.3.10`
- **Tiêu đề:** Trung tâm cập nhật báo đúng lý do, Kiểm tra driver bớt báo nhầm
```text
Phát hành ngày 17/11/2026.

- Lỡ đóng ô nhập mật khẩu khi cập nhật, Trung tâm cập nhật không còn báo "Cập nhật thất bại" mà báo "Chưa cập nhật", kèm nút Thử lại.
- Bấm cập nhật khi máy đang tự cập nhật, hay khi đang mở một cửa sổ cập nhật khác, bạn sẽ thấy "Đang có một lần cập nhật khác": đợi lần đó xong rồi bấm Thử lại.
- Máy in Canon cắm USB mà máy tính không giao tiếp được (cáp lỏng, cổng USB hỏng, cắm qua hub) được báo "Máy in chưa kết nối được" kèm cách đổi cổng, đổi cáp, thay vì đề xuất một driver rồi cài không được.
- Laptop dùng card đồ họa Intel GM45 (Mobile 4 Series) không còn bị báo nhầm là card đồ họa chưa có driver.

Máy đang dùng CaramOS nhận thay đổi này qua Trung tâm cập nhật: bấm Cập nhật ngay, không cần cài lại.
```

#### C12. v1.3.11 (đăng sau cùng)
- **versionTag:** `v1.3.11`
- **Tiêu đề:** Hình nền Việt Nam mỗi ngày, chọn màu nhấn cho Control Center
- **Ảnh:** chưa có. Nên chụp mới ô Màu nhấn hoặc thư mục Việt Nam mỗi ngày.
```text
Phát hành ngày 17/11/2026. Đây là bản mới nhất.

- Hình nền Việt Nam mỗi ngày, làm theo góp ý của người dùng: mở Cài đặt hệ thống > Hình nền, bấm thư mục Việt Nam mỗi ngày rồi chọn một ảnh. Từ đó mỗi ngày hình nền là một ảnh mới về thiên nhiên, cảnh đẹp, công trình của Việt Nam. Bộ ảnh có 45 ảnh từ Wikimedia Commons, giấy phép tự do, tên ảnh ghi tác giả và giấy phép. Mỗi ngày máy tải một ảnh khoảng 1 MB vào thư mục này, trừ khi đang dùng mạng được đặt là có giới hạn dung lượng (như phát Wi-Fi từ điện thoại); hình nền chỉ đổi theo khi bạn đã chọn một ảnh trong thư mục. Chọn hình nền khác là thôi đổi.
- Control Center có ô Màu nhấn, cũng từ góp ý của người dùng: 8 màu có sẵn (Cam, Xanh dương, Xanh ngọc, Xanh lá, Tím, Hồng, Đỏ, Xám), theo chủ đề hệ thống, hoặc bấm Màu khác… để tự chọn màu bất kỳ. Máy cập nhật lên 1.3.11 thấy ô này từ lần đăng nhập sau.
- Máy khởi động mà không vào được màn hình làm việc (màn hình đen, đứng máy) thì lần bật sau menu khởi động tự hiện 30 giây, có mục Advanced options để vào chế độ khôi phục.
- Tệp: bấm chuột phải vào tệp hay thư mục có thêm Sao chép đường dẫn vào clipboard và Tạo lối tắt trên màn hình. Ảnh thu nhỏ hiện cả với tệp trên điện thoại, ổ mạng và Google Drive.
- USB cài đặt: menu khởi động đếm ngược 10 giây, chữ to hơn, hướng dẫn phím bằng tiếng Việt (máy bật Secure Boot vẫn dùng chữ nhỏ mặc định).
- Lệnh sudo apt update không còn hiện dòng báo i386 của bộ gõ Lotus. Dòng đó chỉ là thông báo, máy không có lỗi gì.

Máy đang dùng CaramOS 1.0.2 trở lên: mở Trung tâm cập nhật, bấm Cập nhật ngay, không cần cài lại.
Cài mới: tải ISO 1.3.11 (2,8 GB) tại https://sourceforge.net/projects/caramos/files/v1.3.11/CaramOS-1.3.11-cinnamon-amd64.iso/download và kiểm tra bằng SHA256SUMS tại https://github.com/VN-Linux-Family/CaramOS/releases/download/v1.3.11/SHA256SUMS
Ghi chú phát hành đầy đủ: https://caramos.vietnamlinuxfamily.net/#release-notes
```

#### Phương án B: một changelog gộp, thay cho C1–C12 (chỉ gửi một thông báo)
- **versionTag:** `v1.3.11`
- **Tiêu đề:** Từ 1.3.0 tới 1.3.11: bản chính thức và các bản cập nhật sau đó
- **Gắn feedback (nếu đồng ý):** #4
```text
CaramOS 1.3.0 (16/10/2026) là bản phát hành chính thức đầu tiên; các bản 1.0.x trước đó là Open Beta. Tóm tắt từng bản:

- 1.3.0 (16/10): App Center để chọn và cài ứng dụng (ONLYOFFICE, WPS Office, LibreOffice, Chrome, Zalo, Zoom...), ISO không còn cài sẵn WPS Office, Chrome, Zalo; Kiểm tra driver, cài driver NVIDIA và Wi-Fi Broadcom bằng một nút; Góp ý & hỗ trợ trên thanh tác vụ; nhẹ hơn Linux Mint gốc, earlyoom chống treo máy, ISO 2,8 GB.
- 1.3.1 (17/10): Start Menu và Trung tâm cập nhật toàn tiếng Việt.
- 1.3.2 (19/10): Zalo cho Linux gọi thoại, gọi video không cần Wine; thanh tác vụ gọn lại sau bản cập nhật Cinnamon; nút Nhờ giúp đỡ kèm nhật ký lỗi.
- 1.3.3 (22/10): bộ gõ Lotus tự chạy mỗi lần đăng nhập.
- 1.3.4 (05/11): bộ gõ giữ cài đặt của bạn; Start Menu tìm nhanh, không làm đơ máy; Trung tâm cập nhật không bị nguồn phần mềm hỏng chặn; đề xuất driver NVIDIA 580.
- 1.3.5 (06/11): sửa lỗi cài driver NVIDIA dừng giữa chừng; xem dung lượng ổ đĩa trước khi cài.
- 1.3.6 (07/11): Trung tâm cập nhật không còn đứng hình khi nhật ký dài.
- 1.3.7 (09/11): máy in Canon LBP2900 cài driver bằng một nút (captdriver).
- 1.3.8 (11/11): giữ Ctrl rồi lăn chuột để đổi cỡ icon Start Menu.
- 1.3.9 (12/11): driver Canon chính hãng cho LBP6300dn và các máy CAPT khác, cả máy in qua mạng LAN; PrtSc và Win+Shift+S chụp màn hình.
- 1.3.10 (17/11): Trung tâm cập nhật báo đúng lý do; Kiểm tra driver bớt báo nhầm.
- 1.3.11 (17/11): hình nền Việt Nam mỗi ngày, màu nhấn cho Control Center, menu khởi động tự hiện sau lần khởi động lỗi, Sao chép đường dẫn và Tạo lối tắt trong menu chuột phải của Tệp.

Máy đang dùng CaramOS 1.0.2 trở lên: mở Trung tâm cập nhật, bấm Cập nhật ngay. Cài mới: https://caramos.vietnamlinuxfamily.net (ghi chú phát hành đầy đủ ở mục Release note).
```
Nếu dùng phương án B, sửa câu thứ hai của T1 thành: "Bọn mình vừa thêm bản tóm tắt các bản đó vào tab Cập nhật."

### 3.3 Talk (mỗi ngày một bài, trong t/caramos)

#### T1 (ngày 1, sau các changelog)
- **Tiêu đề:** CaramOS đã lên 1.3.11: những gì thay đổi từ bản Open Beta
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `first-login.webp`
```text
Chào cả nhà,

Trang CaramOS trên Unikorn dừng ở bản 1.0.20 từ đầu tháng 10, trong khi bọn mình đã phát hành thêm 12 bản, tới 1.3.11 ngày 17/11/2026. Bọn mình vừa bổ sung đủ các bản đó vào tab Cập nhật. Bài này tóm tắt cho bạn nào lâu rồi chưa ghé.

Từ 1.3.0 (16/10/2026), CaramOS là bản phát hành chính thức; các bản 1.0.x trước đó là Open Beta. Những thay đổi lớn nhất:

- App Center: lần đăng nhập đầu tiên, bạn chọn bộ văn phòng, trình duyệt, Zalo, Zoom, font Microsoft..., CaramOS tải và cài giúp. ISO không còn cài sẵn WPS Office, Chrome và Zalo. LibreOffice, góp ý được bình chọn nhiều nhất ở mục Feedback, giờ cài bằng một nút.
- Kiểm tra driver: chạy thử từ USB là biết máy có hợp không. Cài driver NVIDIA và Wi-Fi Broadcom bằng một nút; máy in laser Canon dùng CAPT (LBP2900, LBP6300dn...) cũng được cài driver giúp.
- Góp ý & hỗ trợ: dấu hỏi ở góc phải thanh tác vụ để hỏi cộng đồng Vietnam Linux Family ngay trên máy.
- Nhẹ hơn Linux Mint 22.3 gốc: máy rảnh dùng khoảng 865 MiB RAM so với 941 MiB, không treo khi hết RAM nhờ earlyoom, ISO còn 2,8 GB.
- Bộ gõ Lotus tự chạy mỗi lần đăng nhập và giữ cài đặt Telex hay VNI của bạn.
- Bản 1.3.11 có hình nền Việt Nam mỗi ngày và ô Màu nhấn trong Control Center, cả hai đều từ góp ý của người dùng.

Máy đang dùng CaramOS 1.0.2 trở lên không cần cài lại: mở Trung tâm cập nhật, bấm Cập nhật ngay. Cài mới thì tải ISO ở https://caramos.vietnamlinuxfamily.net, ở đó có ghi chú phát hành của từng bản. Mã nguồn: https://github.com/VN-Linux-Family/CaramOS

Bọn mình muốn hỏi: nếu bạn đã thử CaramOS, điều gì còn khiến bạn chưa dùng nó làm máy chính? Bọn mình đọc hết các bình luận.
```

#### T2 (ngày 2)
- **Tiêu đề:** Vì sao CaramOS thôi cài sẵn WPS, Chrome và Zalo
- **Thẻ:** Thảo luận, Góp ý
- **Ảnh bìa:** `app-center.webp`
```text
Các bản CaramOS đầu tiên cài sẵn Chrome, WPS Office và Zalo. Góp ý được bình chọn nhiều nhất ở mục Feedback trên Unikorn lại là LibreOffice, và có bạn dùng CaramOS cho công ty nhỏ kể phải cài LibreOffice thay cho WPS để yên tâm về bản quyền. Cài sẵn một bộ cố định thì ai không dùng cũng phải gỡ ra, còn ai cần thứ khác lại phải tự đi tìm.

Nên từ bản 1.3.0, CaramOS có App Center. Lần đăng nhập đầu tiên, App Center mở ra một trang chia theo nhóm:

- Bộ văn phòng: ONLYOFFICE, WPS Office, LibreOffice.
- Trình duyệt: Google Chrome, Cốc Cốc, Microsoft Edge, Brave (Firefox có sẵn).
- Liên lạc và họp trực tuyến: Zalo (gọi thoại, gọi video được), Telegram, Zoom, Teams for Linux, Discord.
- Tiện ích: font Microsoft (Times New Roman, Arial... để mở file Word không lệch chữ), VLC, OBS Studio, RustDesk, GIMP, Thunderbird.

Bộ đề xuất đã được chọn sẵn (ONLYOFFICE, Chrome, Zalo, font Microsoft, VLC); bạn bỏ hay thêm tùy ý rồi bấm Cài một lần, và cứ dùng máy bình thường trong lúc CaramOS tải và cài. Mỗi ứng dụng ghi rõ ưu, nhược điểm, dung lượng và nguồn cài (Flathub, kho Ubuntu hay gói tải về). Thẻ Zalo ghi "Gói cộng đồng", vì bản Zalo cho Linux này do cộng đồng đóng gói, không phải do Zalo phát hành. Ứng dụng đã cài có nút Gỡ cài đặt ngay trên thẻ, và nút Xem thêm dẫn tới kho ứng dụng https://apps.vietnamlinuxfamily.net khi bạn cần thứ khác.

App Center là một dự án riêng, mã nguồn ở https://github.com/VN-Linux-Family/CaramOS-app-center. Máy tự cập nhật App Center trong lần kiểm tra hằng ngày, sau khi kiểm tra chữ ký của bản phát hành. Máy cập nhật từ bản 1.0.x vẫn giữ các ứng dụng đang có, và có thêm biểu tượng App Center trên Desktop.

Bạn đang dùng bộ văn phòng nào trên Linux, và đã gặp file nào mở ra bị lệch định dạng chưa? Bọn mình dùng những chia sẻ này để ghi ưu, nhược điểm trên thẻ ứng dụng cho sát hơn.
```

#### T3 (ngày 3)
- **Tiêu đề:** Chạy thử CaramOS từ USB để biết máy có hợp với Linux không
- **Thẻ:** Thảo luận, Hỏi đáp
- **Ảnh bìa:** `driver-check.webp`
```text
Trước khi cài Linux, ai cũng muốn biết: máy mình có chạy được không? Cài xong mới biết Wi-Fi không lên hay màn hình chỉ còn độ phân giải thấp thì đã muộn.

Từ bản 1.3.0, CaramOS có Kiểm tra driver. Khi bạn chạy thử CaramOS từ USB, ứng dụng này tự mở và kiểm tra máy trước cả khi cài:

- Wi-Fi, mạng dây, card đồ họa, âm thanh, Bluetooth, webcam, đầu đọc vân tay và máy in Canon dùng CAPT.
- Giải thích từng trường hợp bằng lời dễ hiểu: nhân Linux chưa có driver, driver vừa cài cần khởi động lại, driver bị chặn (blacklist, Secure Boot), hay thiếu firmware.
- Cài driver NVIDIA và Wi-Fi Broadcom bằng một nút, đúng bản Ubuntu khuyên dùng cho máy. Với card NVIDIA đời cũ, nó đề xuất driver 580 thay cho 470, vì bản 470 không chạy được trên nhân Linux 6.14 trở lên.
- Thiếu driver mạng nên chưa vào được Internet: nó chỉ cách vào mạng bằng dây LAN, bằng điện thoại cắm cáp USB, hoặc cài driver Broadcom ngay từ USB cài CaramOS.
- Trước khi cài driver, nó xem ổ đĩa còn đủ chỗ không và nói rõ cần dọn bao nhiêu.

Sau khi cài CaramOS, Kiểm tra driver chạy lại một lần ở lần đăng nhập đầu tiên, rồi chỉ lên tiếng khi có vấn đề mới, ví dụ khi bạn cắm một máy in cần driver. Không tự xử lý được thì nút Nhờ giúp đỡ gửi lời nhắn kèm hồ sơ phần cứng tới cộng đồng Vietnam Linux Family, nếu bạn đồng ý. Hồ sơ này không có tên người dùng, tên máy hay địa chỉ IP.

Tải CaramOS để chạy thử: https://caramos.vietnamlinuxfamily.net

Máy của bạn từng có linh kiện nào không chạy trên Linux? Bạn kể tên máy hoặc linh kiện, bọn mình sẽ xem Kiểm tra driver đã nhận ra trường hợp đó chưa.
```

#### T4 (ngày 4)
- **Tiêu đề:** Máy in laser Canon trên Linux: CaramOS cài driver giúp bạn, và bọn mình cần người thử máy thật
- **Thẻ:** Thảo luận, Góp ý
- **Ảnh bìa:** `printer-canon-driver-check.webp`
```text
Máy in laser Canon dùng CAPT như LBP2900, LBP3300 hay LBP6300dn có mặt ở rất nhiều văn phòng và gia đình, nhưng vốn khó cài trên Linux: hệ thống thường gán nhầm một driver không hợp, lệnh in báo xong mà máy không ra giấy.

Trong tháng 11, CaramOS có ba thay đổi cho các máy này:

- Bản 1.3.7: cắm LBP2900 vào là có thông báo "Máy in chưa có driver", bấm cài là xong. Driver là captdriver, mã nguồn mở. Theo captdriver, LBP2900/LBP2900B và LBP3010/LBP3018/LBP3050 chạy được; LBP3000, LBP3100 và LBP6000 mới ở mức thử nghiệm.
- Bản 1.3.9: các máy Canon CAPT khác (LBP6300dn, LBP3300, LBP5000, LBP6200, LBP7200C...) dùng driver chính hãng của Canon. Kiểm tra driver tải driver thẳng từ máy chủ của Canon sau khi bạn đồng ý điều khoản của Canon, kiểm tra rồi cài, tạo hàng đợi in, và cho dịch vụ in tự chạy khi bật máy. Máy in qua mạng LAN thì bấm Thêm máy in…, chọn mẫu máy và nhập địa chỉ IP. Lưu ý: điều khoản của Canon chỉ cho phép dùng cho mục đích cá nhân, phi thương mại.
- Bản 1.3.10: cáp lỏng, cổng USB hỏng hay cắm qua hub thì được báo "Máy in chưa kết nối được" kèm cách xử lý, thay vì đề xuất một driver rồi cài không được.

Máy in phun Canon PIXMA hay máy in hãng khác dùng driver có sẵn trong CaramOS: mở Máy in trong menu để thêm máy. Các máy LBP810, LBP3600, LBP5200 chưa được hỗ trợ. Danh sách đầy đủ: https://caramos.vietnamlinuxfamily.net/#printers

Bọn mình không có đủ các dòng máy để thử hết, nên rất cần bạn nào có máy in Canon LBP giúp một tay: cắm vào, cài driver, in thử một trang, rồi kể lại kết quả ở đây hoặc qua nút dấu hỏi trên thanh tác vụ. Bạn đang dùng máy in nào ở nhà hay ở văn phòng?
```

#### T5 (ngày 5)
- **Tiêu đề:** Cập nhật CaramOS không cần cài lại: máy cài từ bản 1.0 vẫn lên được 1.3.11
- **Thẻ:** Thảo luận
- **Ảnh bìa:** `update-center-131.webp`
```text
Từ những ngày đầu đã có bạn hỏi: có bản mới thì phải cài lại máy à? Không cần. Máy cài CaramOS từ bản nào cũng lên được bản mới nhất qua Trung tâm cập nhật, không cài lại và không mất dữ liệu.

Cách nó chạy:

- Mỗi ngày CaramOS kiểm tra một lần. Có bản mới thì Trung tâm cập nhật báo phiên bản hiện tại, phiên bản mới và từng thay đổi sẽ được áp dụng.
- Không có gì tự cài khi bạn chưa đồng ý: bấm Cập nhật ngay khi tiện, hoặc Để sau.
- Thứ bạn đã tự chỉnh được giữ nguyên: hình nền bạn tự chọn, bộ màu biểu tượng, applet bạn đã gỡ khỏi thanh tác vụ.

Mấy bản gần đây làm cho việc cập nhật ít trục trặc hơn:

- 1.3.4: không còn bị chặn bởi một nguồn phần mềm hỏng do chương trình khác thêm vào, hay một gói cài dở.
- 1.3.6: cửa sổ không còn đứng hình khi bản cập nhật in ra rất nhiều dòng nhật ký.
- 1.3.10: lỡ đóng ô nhập mật khẩu thì báo "Chưa cập nhật" kèm nút Thử lại, thay vì "Cập nhật thất bại".

Muốn lên bản mới ngay, không chờ thông báo, bạn mở Terminal và chạy:
sudo caramos-ota --upgrade --yes

Máy còn ở bản 1.0.1 (chưa có Trung tâm cập nhật) thì chạy lệnh này một lần, rồi mở Trung tâm cập nhật CaramOS từ Start Menu:
curl -fsSL https://caramos.vietnamlinuxfamily.net/install-caramos-ota.sh | sudo bash

Bạn đã cập nhật CaramOS qua Trung tâm cập nhật chưa? Có bước nào khó hiểu hay thông báo nào làm bạn lo không? Bạn kể để bọn mình biết chỗ cần sửa.
```

#### T6 (ngày 6)
- **Tiêu đề:** Máy cũ, RAM ít: CaramOS làm gì để chạy nhẹ và không treo khi hết RAM
- **Thẻ:** Thảo luận
- **Ảnh bìa:** không cần
```text
Nhiều bạn cài Linux để cứu một chiếc máy cũ, nên bọn mình đo CaramOS với Linux Mint 22.3 Cinnamon gốc trên cùng một máy ảo (4 nhân, 6 GB RAM), 5 phút sau khi khởi động:

- RAM khi máy rảnh: CaramOS 865 MiB, Linux Mint 22.3 gốc 941 MiB.
- ISO cài đặt: CaramOS 2,8 GB, Linux Mint 22.3 3,1 GB, dù CaramOS có thêm App Center, Kiểm tra driver và Góp ý & hỗ trợ.

Phần RAM bớt được đến từ những việc nhỏ:

- Các dịch vụ nền của Cinnamon và Flameshot không nạp OpenGL khi không cần.
- Bộ gõ không khởi động các dịch vụ portal thừa; đăng nhập không khởi động lại bộ gõ khi cấu hình không đổi.
- Dịch vụ nhắc lịch chỉ chạy khi bạn có sự kiện, việc cần làm hoặc tài khoản lịch.
- Tắt dịch vụ gửi báo cáo lỗi nhân cho Ubuntu, vốn làm chậm khởi động.
- CopyQ (lịch sử clipboard) không tự chạy nữa, bớt khoảng 45 MB RAM; cần thì mở từ menu.
- Bỏ 14 màu thừa của bộ biểu tượng, giải phóng khoảng 1,1 GB ổ đĩa.

Quan trọng hơn con số là chuyện máy treo. Khi RAM và swap gần hết, CaramOS dùng earlyoom để đóng ứng dụng tốn RAM nhất, thay vì để cả máy đứng hình. Trên máy thử với ổ cứng chậm, Linux Mint gốc đơ hơn 30 phút trong tình huống này, còn CaramOS không lần nào đứng hình.

Cấu hình tối thiểu: máy 64-bit, RAM 2 GB (khuyên dùng 4 GB), ổ trống 20 GB. Tải tại https://caramos.vietnamlinuxfamily.net

Bạn đang chạy Linux trên máy nào, RAM bao nhiêu? Nếu thấy chỗ nào còn chậm, bạn kể cụ thể (đang mở ứng dụng gì, lúc nào) để bọn mình đo lại.
```

#### T7 (ngày 7)
- **Tiêu đề:** Gõ tiếng Việt trên CaramOS: những gì bọn mình đã sửa trong bộ gõ
- **Thẻ:** Thảo luận, tieng-viet
- **Ảnh bìa:** `installer-lotus.webp`
```text
Bộ gõ là thứ người dùng Việt chạm vào đầu tiên, nên bọn mình sửa nó khá nhiều trong mấy tháng qua. CaramOS dùng Fcitx5 với bộ gõ Lotus, bật sẵn từ lúc cài:

- Mặc định Telex, có VNI và các kiểu gõ phổ biến khác.
- Ctrl+Shift để chuyển tiếng Việt (V) và tiếng Anh (A); phím ` (dưới Esc) mở menu đổi kiểu gõ.
- Ứng dụng cài từ Flathub vẫn gõ tiếng Việt và dùng font của hệ thống bình thường.

Những lỗi đã sửa qua các bản:

- 1.0.20: dịch vụ bật Lotus không còn làm kẹt quá trình khởi động.
- 1.3.3: trên một số máy mới cài và khi chạy thử từ USB, bộ gõ không tự chạy nên chỉ gõ ra chữ không dấu. Giờ bộ gõ tự chạy mỗi lần đăng nhập.
- 1.3.4: cài đặt bạn chọn (Telex hay VNI, chế độ gõ, kiểm tra chính tả, phím tắt) không còn bị đặt lại mỗi lần đăng nhập, và mỗi phiên bắt đầu ở tiếng Việt. Ô tìm kiếm Start Menu ra kết quả ngay khi đang gõ tiếng Việt có dấu.
- 1.3.11: lệnh sudo apt update thôi hiện dòng báo i386 của kho Lotus, dòng trông như báo lỗi dù máy không sao.

Máy đang dùng CaramOS nhận các bản sửa này qua Trung tâm cập nhật, không cần cài lại.

Bạn gõ Telex hay VNI? Có ứng dụng nào gõ tiếng Việt còn lỗi (mất chữ, nhảy dấu, gõ không được) không? Bạn ghi tên ứng dụng và cách nó lỗi giúp bọn mình.
```

#### T8 (ngày 8)
- **Tiêu đề:** Những thói quen từ Windows mà CaramOS giữ lại
- **Thẻ:** Thảo luận, Góp ý
- **Ảnh bìa:** `island-dock.webp`
```text
Chuyển từ Windows sang, cái khó thường không phải Linux mà là mất những thao tác đã quen tay. Đây là những thói quen CaramOS giữ lại hoặc làm cho giống:

- Thanh tác vụ: nút Start bên trái, ứng dụng ghim và đang mở ở giữa, khay hệ thống, bộ gõ, đồng hồ bên phải.
- Start Menu tìm ứng dụng bằng tiếng Việt, gõ không dấu vẫn ra. Giữ Ctrl rồi lăn chuột để phóng to, thu nhỏ icon (từ 1.3.8).
- PrtSc hoặc Win+Shift+S để chụp màn hình: kéo chọn vùng, Ctrl+C rồi dán thẳng vào Zalo, Messenger hay Word (từ 1.3.9).
- Bấm chuột phải vào tệp hay thư mục để Sao chép đường dẫn, hoặc Tạo lối tắt trên màn hình (từ 1.3.11).
- Bấm góc phải thanh tác vụ là có Control Center: âm lượng, Wi-Fi, Bluetooth, độ sáng, pin, chế độ tối, chế độ nguồn, giống bảng cài đặt nhanh trên Windows.
- Máy khởi động lỗi (màn hình đen, đứng máy) thì lần bật sau menu khởi động tự hiện, có mục vào chế độ khôi phục (từ 1.3.11).

Máy đang dùng CaramOS nhận các thay đổi này qua Trung tâm cập nhật. Tải bản mới nhất: https://caramos.vietnamlinuxfamily.net

Thói quen nào từ Windows bạn còn thấy thiếu khi dùng CaramOS hay Linux nói chung? Bạn cứ kể, kể cả những thứ nhỏ.
```

#### T9 (ngày 9)
- **Tiêu đề:** Mỗi ngày một ảnh Việt Nam làm hình nền, và màu nhấn tự chọn
- **Thẻ:** Thảo luận
- **Ảnh bìa:** chưa có. Nên chụp mới.
```text
Hai thay đổi trong CaramOS 1.3.11 (17/11/2026) đều đến từ góp ý của người dùng.

Hình nền Việt Nam mỗi ngày
- Mở Cài đặt hệ thống > Hình nền, bấm thư mục Việt Nam mỗi ngày rồi chọn một ảnh. Từ đó mỗi ngày hình nền là một ảnh mới về thiên nhiên, cảnh đẹp, công trình của Việt Nam.
- Bộ ảnh hiện có 45 ảnh từ Wikimedia Commons, đều có giấy phép tự do; tên ảnh ghi tác giả và giấy phép.
- Mỗi ngày máy tải một ảnh mới khoảng 1 MB vào thư mục này, trừ khi đang dùng mạng được đặt là có giới hạn dung lượng.
- Hình nền chỉ đổi theo khi bạn đã chọn một ảnh trong thư mục. Chọn hình nền khác là thôi đổi.

Màu nhấn cho Control Center
- Control Center (góc phải thanh tác vụ) có ô Màu nhấn: Cam, Xanh dương, Xanh ngọc, Xanh lá, Tím, Hồng, Đỏ, Xám, theo chủ đề hệ thống, hoặc bấm Màu khác… để tự chọn màu bất kỳ.
- Máy cập nhật lên 1.3.11 thấy ô này từ lần đăng nhập sau.

Máy đang dùng CaramOS: mở Trung tâm cập nhật, bấm Cập nhật ngay. Cài mới: https://caramos.vietnamlinuxfamily.net

Bạn thích để hình nền cố định hay đổi mỗi ngày? Nếu đã bật thử, ảnh nào bạn thấy đẹp nhất?
```

#### T10 (ngày 10)
- **Tiêu đề:** Gặp lỗi trên CaramOS thì hỏi ở đâu: nút dấu hỏi trên thanh tác vụ
- **Thẻ:** Thảo luận, Hỏi đáp
- **Ảnh bìa:** `help-form.webp`
```text
Người mới dùng Linux hay bí ở chỗ không biết hỏi ai, hỏi thế nào cho người khác hiểu. Từ bản 1.3.0, CaramOS có Góp ý & hỗ trợ: dấu hỏi ở góc phải thanh tác vụ.

- Chọn Nhờ giúp đỡ khi có gì đó không chạy, Báo lỗi khi CaramOS hay một ứng dụng chạy sai, Góp ý khi bạn có ý tưởng.
- Kèm ảnh chụp màn hình (làm mờ được chỗ riêng tư), video quay màn hình tối đa 1 phút, hoặc ảnh, video có sẵn trong máy. Ảnh và video được nén nhỏ và bỏ thông tin vị trí trước khi gửi.
- Nếu bạn đồng ý, yêu cầu kèm hồ sơ phần cứng và kết quả Kiểm tra driver, để người giúp thấy đúng máy của bạn. Hồ sơ phần cứng không có tên người dùng, tên máy và địa chỉ IP.
- Yêu cầu được chia sẻ để cộng đồng cùng giúp, bỏ tick nếu không muốn. VNLF duyệt trước khi đăng; thông tin liên hệ của bạn không công khai.
- Menu của dấu hỏi cho biết yêu cầu nào VNLF đang xem, đã trả lời hay đã xử lý xong. Có câu trả lời mới thì CaramOS gửi thông báo.

Nếu bạn thích hỏi ở nơi đông người hơn, cộng đồng Vietnam Linux Family có nhóm Facebook (https://www.facebook.com/groups/vietnamlinuxcommunity), Telegram (https://t.me/vietnamlinuxfamily) và Discord (https://discord.gg/gVAJDUMC2n).

Bạn thường hỏi về Linux ở đâu, và điều gì làm bạn ngại hỏi? Bọn mình muốn nút dấu hỏi này dễ dùng với cả người chưa từng hỏi trên diễn đàn.
```

### 3.4 Trả lời và bình luận (đăng tay nếu MCP không làm được)

**R1. Trả lời feedback #4 (LibreOffice)**, tại https://unikorn.vn/p/caramos/feedback
```text
Cảm ơn bạn đã góp ý, và cảm ơn các bạn đã bình chọn cho mục này. Từ CaramOS 1.3.0 (16/10/2026), ISO không cài sẵn WPS Office nữa. Lần đăng nhập đầu tiên, App Center mở ra để bạn chọn bộ văn phòng: ONLYOFFICE (được chọn sẵn), WPS Office hoặc LibreOffice, bấm Cài là CaramOS tải và cài giúp. Máy đang dùng bản cũ thì cập nhật qua Trung tâm cập nhật, rồi mở App Center trên Desktop để cài LibreOffice. Bọn mình đánh dấu mục này là đã xong.
```

**R2. Trả lời bình luận 26/10/2026 về tải chậm** (trong chuỗi về SourceForge)
```text
Cảm ơn bạn đã nhắc. ISO CaramOS để trên SourceForge vì GitHub giới hạn dung lượng mỗi tệp đính kèm. Nếu tải chậm, trên trang tải của SourceForge bạn có thể chọn máy chủ (mirror) khác. Từ bản 1.3.0, ISO cũng nhỏ lại còn 2,8 GB. Máy đã cài CaramOS thì không cần tải ISO nữa: Trung tâm cập nhật đưa máy lên bản mới nhất. Tải xong, bạn kiểm tra tệp bằng SHA256SUMS: https://github.com/VN-Linux-Family/CaramOS/releases/download/v1.3.11/SHA256SUMS
```

**R3. Trả lời đánh giá 21/05/2026 góp ý nên có tiếng Anh**
```text
Cập nhật cho bạn: từ bản 1.0.20, ngôn ngữ bạn chọn trong Cài đặt > Ngôn ngữ được áp dụng cho cả hệ thống, máy cài bằng tiếng Anh không còn bị chèn tiếng Việt. Các ứng dụng riêng của CaramOS (App Center, Kiểm tra driver, Trung tâm cập nhật, Control Center, Góp ý & hỗ trợ) cũng hiện tiếng Anh khi máy dùng tiếng Anh.
```

**R4. Trả lời trong Talk cũ** "Quanh tôi quá nhiều người vẫn đang dùng Windows lậu"
```text
Cập nhật sau 5 tháng: CaramOS đã lên 1.3.11 và là bản phát hành chính thức từ 1.3.0. Máy mới cài có App Center để chọn bộ văn phòng (ONLYOFFICE, LibreOffice, WPS Office), trình duyệt và Zalo, và có Kiểm tra driver để biết máy có hợp không ngay khi chạy thử từ USB. Ai muốn thử: https://caramos.vietnamlinuxfamily.net
```

**R5. Bình luận vào bài review của Unikorn**, tại https://unikorn.vn/reviews/caramos-ban-linux-thuan-viet-co-dang-de-ban-roi-windows
```text
Bọn mình là nhóm làm CaramOS, cảm ơn Unikorn đã viết bài này. Từ lúc bài đăng (02/09/2026), CaramOS đã đổi khá nhiều, xin cập nhật để bạn đọc khỏi nhầm:
- Bản mới nhất là 1.3.11 (17/11/2026). Từ 1.3.0 (16/10/2026), CaramOS là bản phát hành chính thức, không còn là Open Beta.
- ISO không còn cài sẵn Chrome, WPS Office và Zalo. Lần đăng nhập đầu tiên, App Center cho bạn chọn bộ văn phòng (ONLYOFFICE, WPS Office hoặc LibreOffice), trình duyệt, Zalo và các ứng dụng khác rồi cài giúp.
- Có thêm Kiểm tra driver (biết máy có hợp không ngay khi chạy thử từ USB, cài driver NVIDIA, Wi-Fi Broadcom và máy in Canon dùng CAPT), Góp ý & hỗ trợ ngay trên thanh tác vụ, và nhiều bản sửa cho bộ gõ Lotus.
- Cấu hình tối thiểu theo trang chủ: máy 64-bit, RAM 2 GB (khuyên dùng 4 GB), ổ trống 20 GB.
Ghi chú phát hành từng bản: https://caramos.vietnamlinuxfamily.net/#release-notes
```

**R6 (tùy chọn). Nhờ đội Unikorn cập nhật bài review**, gửi qua https://unikorn.vn/p/unikorn/feedback hoặc email liên hệ của Unikorn
```text
Chào đội Unikorn, bọn mình là nhóm làm CaramOS. Cảm ơn bài review "CaramOS: bản Linux thuần Việt có đáng để bạn rời Windows?" (02/09/2026). Từ đó tới nay CaramOS đã đổi nhiều: bản mới nhất là 1.3.11 (17/11/2026), bản chính thức từ 1.3.0 (không còn Open Beta), Chrome, WPS Office và Zalo không còn cài sẵn mà chọn trong App Center (có cả LibreOffice và ONLYOFFICE), cấu hình tối thiểu là RAM 2 GB và ổ trống 20 GB. Nếu tiện, đội có thể cập nhật bảng thông tin trong bài giúp bọn mình không? Ghi chú phát hành: https://caramos.vietnamlinuxfamily.net/#release-notes
```

### 3.5 Những gì cố ý không đưa vào

- **Việc chưa phát hành:** bản Xfce, 1.4.0, công cụ phòng máy, Veyon/Epoptes, Control Center cho Xfce, menu Tệp > Mới > Thư mục, ARM64, chạy .exe, ứng dụng Android.
- **Thông tin riêng tư:** không tên người dùng, email, số hay nội dung yêu cầu hỗ trợ. Chỗ ghi "từ góp ý của người dùng" không nêu ai, qua kênh nào.
- **Lỗi Zalo gửi file 2–3 MB:** không tìm thấy bằng chứng đã sửa trong ghi chú phát hành, nên không nhắc.

---

## 4. Điểm chưa chắc

1. **MCP:** chưa xem được danh sách công cụ. Chưa biết nó nhận HTML hay Markdown, ảnh theo URL, `feedbackIds`, hay đặt ngày đăng lùi được không. Nếu đặt được ngày thì dùng ngày thật ở mục 2. R1–R6 có lẽ phải đăng tay.
2. **Thông báo:** 12 changelog gửi 12 thông báo tới 223 người; phương án B chỉ gửi một. Bạn chọn.
3. **Feedback LibreOffice:** người góp ý muốn LibreOffice có sẵn. Hiện LibreOffice cài một nút, còn ONLYOFFICE mới là bộ chọn sẵn. Đánh dấu "đã xong" hay không là bạn quyết.
4. **Máy in Canon:** landing ghi "cắm vào là in", nhưng theo ghi chú nội bộ, việc in thật trên LBP2900 và các máy CAPT khác chưa được thử trên máy thật. Bản nháp chỉ nói Kiểm tra driver cài driver và tạo hàng đợi in, và T4 nhờ người có máy thật thử. Nếu đã có người xác nhận in được thì viết mạnh hơn được.
5. **Danh mục và tagline:** đổi hay không đều là tùy chọn; đổi danh mục có thể phải duyệt lại.
6. **Độ dài mô tả:** chưa rõ giới hạn của form; đã kèm bản ngắn.
7. **Mẹo chọn mirror (R2):** đây là cách SourceForge vẫn cho làm, mình chưa thử lại hôm nay.
8. **Ảnh 1.3.11:** chưa có ảnh ô Màu nhấn và thư mục Việt Nam mỗi ngày. Ảnh Control Center trên landing chụp trước khi có Màu nhấn.
9. **Giới hạn Talk:** Unikorn không công bố mỗi level được tính điểm bao nhiêu Talk mỗi ngày. Đăng một bài mỗi ngày cho an toàn.
10. **Bản 1.0.21:** commit "[build] Release 1.0.21" có trong git nhưng không có tag, GitHub Release hay mục trên landing. Coi là chưa phát hành, không nhắc.
11. **Số đo:** 865 so với 941 MiB, ISO 2,8 so với 3,1 GB, "đơ hơn 30 phút" đều lấy từ README tại tag v1.3.11. Mình không đo lại.

---

## 5. Quyết định của owner (18/11/2026) và Talk theo từng phiên bản

Owner đã chọn:
- **Changelog:** đăng 12 bài riêng, từ v1.3.0 tới v1.3.11 (phương án A, không gộp).
- **Feedback #4 (LibreOffice):** đánh dấu đã xong, bằng cách gắn vào changelog v1.3.0 (`feedbackIds`); trả lời R1 trên web.
- **Talk:** mỗi phiên bản một bài (12 bài V0–V11 dưới đây), thay cho T1–T10 theo chủ đề. Mỗi bài kể bối cảnh, không chép lại changelog, và kết bằng một câu hỏi thật (quy tắc 5.3, 5.4).

Nhịp đăng đề xuất:
- Unikorn chỉ tính điểm vài Talk do AI Agent đăng mỗi ngày, và đăng hàng loạt có thể bị báo cáo.
- Vì vậy nên đăng 2 Talk mỗi ngày, trong 6 ngày, trừ khi owner bảo đăng hết một lần.
- Ngày 1:
  1. sửa thông tin sản phẩm (3.1);
  2. đăng 12 changelog theo thứ tự v1.3.0 → v1.3.11;
  3. đăng V0 và V1.
- Ngày 2 đến 6: V2–V3, V4–V5, V6–V7, V8–V9, V10–V11.
- R1–R6 đăng tay trên web nếu MCP không làm được.

### V0. v1.3.0
- **Tiêu đề:** CaramOS 1.3.0: bản chính thức đầu tiên, và vì sao bọn mình thôi cài sẵn ứng dụng
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `first-login.webp`
```text
Chào cả nhà,

Ngày 16/10/2026 bọn mình phát hành CaramOS 1.3.0, bản chính thức đầu tiên sau loạt Open Beta 1.0.x. Từng thay đổi có trong tab Cập nhật; bài này kể vì sao bản này khác hẳn trước.

Các bản Open Beta cài sẵn Chrome, WPS Office và Zalo. Nhưng mỗi người cần một bộ khác nhau, và góp ý được bình chọn nhiều nhất ở mục Feedback lại là LibreOffice. Nên từ 1.3.0, lần đăng nhập đầu tiên App Center mở ra để bạn tự chọn bộ văn phòng (ONLYOFFICE, WPS Office, LibreOffice), trình duyệt, Zalo, Zoom, font Microsoft…, rồi CaramOS tải và cài giúp. Máy cập nhật từ bản cũ vẫn giữ các ứng dụng đang có.

Bản này cũng có Kiểm tra driver: chạy thử CaramOS từ USB là biết Wi-Fi, card đồ họa, âm thanh, webcam có chạy không, trước khi cài; driver NVIDIA và Wi-Fi Broadcom cài bằng một nút. Và dấu hỏi ở góc phải thanh tác vụ để bạn hỏi cộng đồng Vietnam Linux Family ngay trên máy.

Máy đang dùng CaramOS chỉ cần mở Trung tâm cập nhật, bấm Cập nhật ngay, không cần cài lại.

Bạn đang dùng bộ văn phòng nào trên Linux? Nếu đã mở App Center, bạn thấy còn thiếu ứng dụng quen thuộc nào?
```

### V1. v1.3.1
- **Tiêu đề:** CaramOS 1.3.1: Start Menu và Trung tâm cập nhật nói tiếng Việt
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `start-menu-131.webp`
```text
Bản 1.3.1 (17/10/2026) nhỏ thôi, nhưng là thứ bạn nhìn thấy mỗi ngày: Start Menu hiện "Tất cả ứng dụng", "Biểu tượng cảm xúc" thay cho chữ tiếng Anh, applet thời tiết và các tiện ích đi kèm theo ngôn ngữ của máy từ lần đăng nhập sau, và dòng dung lượng trong Trung tâm cập nhật không còn lẫn tiếng Anh.

Trong App Center 0.2.1, thẻ Zalo ghi "Gói cộng đồng": bản Zalo cho Linux này do cộng đồng đóng gói, không phải do Zalo phát hành. Bọn mình muốn bạn biết điều đó trước khi bấm cài.

Bạn còn gặp chỗ nào trên CaramOS hiện tiếng Anh lẫn tiếng Việt không? Chụp màn hình gửi ở đây, hoặc qua dấu hỏi trên thanh tác vụ, giúp bọn mình nhé.
```

### V2. v1.3.2
- **Tiêu đề:** CaramOS 1.3.2: Zalo gọi được ngay trên Linux
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** không cần
```text
Bản 1.3.2 (19/10/2026) đến cùng Zalo cho Linux bản mới (26.10.11): gọi thoại, gọi video được ngay trên Linux, không cần Wine nên mở nhanh hơn. App Center 0.2.2 cài bản này. Máy đã có Zalo do CaramOS hoặc App Center cài thì được đổi sang bản mới, tin nhắn và tài khoản giữ nguyên.

Bản này còn sửa thanh tác vụ: sau khi Linux Mint cập nhật Cinnamon 6.6.9, biểu tượng ở giữa to ra, tràn khỏi khung; giờ chúng nằm gọn lại, và CaramOS tự chỉnh mỗi khi Cinnamon được cập nhật. Kiểm tra driver cũng không còn làm đứng máy cũ khi chạy thử từ USB.

Bạn đã gọi Zalo trên CaramOS chưa? Âm thanh và camera có ổn không?
```

### V3. v1.3.3
- **Tiêu đề:** CaramOS 1.3.3: gõ được tiếng Việt ngay khi đăng nhập
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `installer-lotus.webp`
```text
Đây là lỗi bọn mình thấy áy náy nhất trong loạt 1.3: trên một số máy mới cài 1.3.0–1.3.2 và khi chạy thử từ USB, bộ gõ Lotus không tự chạy, khay hệ thống không có chữ V và gõ Telex chỉ ra chữ không dấu.

Bản 1.3.3 (22/10/2026) sửa việc này: bộ gõ tự chạy mỗi lần đăng nhập. Máy đang bị lỗi chỉ cần bấm Cập nhật ngay trong Trung tâm cập nhật là gõ được liền, không cần đăng nhập lại. Ctrl+Shift vẫn chuyển giữa V và A, cài đặt bộ gõ của bạn giữ nguyên.

Cảm ơn các bạn đã báo lỗi sớm. Nếu máy bạn cập nhật rồi mà vẫn gõ không dấu, bạn cho bọn mình biết máy và phiên bản đang dùng nhé.
```

### V4. v1.3.4
- **Tiêu đề:** CaramOS 1.3.4: những bản sửa từ báo lỗi của người dùng
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** không cần
```text
Bản 1.3.4 (05/11/2026) gom nhiều bản sửa từ những báo lỗi gửi qua dấu hỏi trên thanh tác vụ. Mấy điều bạn sẽ thấy rõ nhất:

- Cài đặt bộ gõ bạn chọn (Telex hay VNI, kiểm tra chính tả, phím tắt) không còn bị đặt lại mỗi lần đăng nhập.
- Start Menu ra kết quả ngay khi đang gõ tiếng Việt có dấu, và tìm tệp không còn làm đơ máy, kể cả trên ổ HDD hay khi có Google Drive gắn trong thư mục Home.
- Trung tâm cập nhật không còn bị chặn vì một nguồn phần mềm hỏng do chương trình khác thêm vào, hay một gói cài dở.

Danh sách đầy đủ có trong tab Cập nhật. Bọn mình đọc từng yêu cầu gửi về. Nếu bạn từng báo lỗi mà chưa thấy sửa, nhắc lại ở đây giúp bọn mình nhé.
```

### V5. v1.3.5
- **Tiêu đề:** CaramOS 1.3.5: cài driver NVIDIA chạy được trở lại
- **Thẻ:** Thông báo, Hỏi đáp
- **Ảnh bìa:** `driver-check.webp`
```text
Từ 1.3.0, cài driver NVIDIA bằng Kiểm tra driver có thể dừng giữa chừng: khởi động lại thì máy không có driver đồ họa và màn hình chỉ còn 1024×768. Bản 1.3.5 (06/11/2026) sửa lỗi này, và máy đã bị như vậy được bản cập nhật tự sửa. Nếu cần sửa tay: mở Terminal, chạy sudo dpkg --configure -a rồi khởi động lại.

Bọn mình cũng thêm một bước trước khi cài: Kiểm tra driver xem ổ đĩa còn đủ chỗ không và nói rõ cần dọn bao nhiêu, ở đâu. Driver NVIDIA có thể kéo theo nhân Linux mới, khi đó phải tải khoảng 1 GB.

Máy bạn dùng card NVIDIA nào? Cài driver trên CaramOS có suôn sẻ không?
```

### V6. v1.3.6
- **Tiêu đề:** CaramOS 1.3.6: Trung tâm cập nhật không còn đứng hình
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `update-progress.webp`
```text
Một lần cập nhật hoàn tất driver NVIDIA bị cài dở in ra khoảng 49.000 dòng nhật ký, và cửa sổ Trung tâm cập nhật từng đứng hơn 15 phút. Bản 1.3.6 (07/11/2026) hiện chừng đó dòng trong chưa tới một giây, và khung nhật ký luôn cuộn tới dòng mới nhất.

Lưu ý nhỏ: máy còn ở bản cũ hơn 1.3.6 thì lần cập nhật này vẫn chạy trong cửa sổ của bản đang dùng. Nếu cửa sổ đứng, cứ để nó chạy xong, đừng tắt máy.

Bạn có gặp lần cập nhật nào lâu bất thường không? Kể lại giúp bọn mình nhé.
```

### V7. v1.3.7
- **Tiêu đề:** CaramOS 1.3.7: máy in Canon LBP2900 cắm vào là cài driver
- **Thẻ:** Thông báo, Thảo luận, Góp ý
- **Ảnh bìa:** `printer-canon-driver-check.webp` (tùy chọn)
- **Lưu ý cho owner:** câu cuối nói thật là bọn mình mới thử bằng máy in giả lập, chưa có máy LBP2900 thật. Bỏ câu đó nếu không muốn nhắc.
```text
Canon LBP2900 có mặt ở rất nhiều văn phòng và gia đình, nhưng trên Linux hay bị gán nhầm một driver không hợp: lệnh in báo xong mà máy không ra giấy.

Từ bản 1.3.7 (09/11/2026), cắm máy in vào là có thông báo "Máy in chưa có driver". Bấm Xem chi tiết rồi Cài driver máy in, máy in tự được thiết lập. Driver là captdriver, mã nguồn mở; theo captdriver, LBP2900/LBP2900B và LBP3010/LBP3018/LBP3050 chạy được, còn LBP3000, LBP3100, LBP6000 mới ở mức thử nghiệm.

Bọn mình mới thử bằng một máy in giả lập, chưa có máy thật để in. Nếu bạn có LBP2900, cắm vào, cài driver, in thử một trang rồi kể lại kết quả ở đây giúp bọn mình nhé.
```

### V8. v1.3.8
- **Tiêu đề:** CaramOS 1.3.8: giữ Ctrl rồi lăn chuột để đổi cỡ icon Start Menu
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** không cần
```text
Một thao tác quen tay từ Windows, có từ bản 1.3.8 (11/11/2026): mở Start Menu, giữ Ctrl rồi lăn chuột trên danh sách ứng dụng. Lăn lên thì icon to dần, lăn xuống thì nhỏ dần; icon nhỏ thì mỗi hàng xếp được tới 7 ứng dụng. Start Menu vẫn mở nguyên chỗ bạn đang xem, và nhớ cỡ bạn chọn cho lần sau.

Bạn thích icon Start Menu to hay nhỏ? Còn thao tác nào từ Windows bạn muốn CaramOS có?
```

### V9. v1.3.9
- **Tiêu đề:** CaramOS 1.3.9: driver Canon chính hãng cho LBP6300dn, và PrtSc chụp được màn hình
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** `printer-canon-driver-check.webp`
```text
Bản 1.3.9 (12/11/2026) có hai thay đổi.

Các máy in Canon dùng CAPT mà captdriver chưa chạy được, như LBP6300dn, LBP3300, LBP5000, LBP6200, LBP7200C, giờ được Kiểm tra driver cài driver chính hãng của Canon: tải thẳng từ máy chủ của Canon sau khi bạn đồng ý điều khoản, kiểm tra rồi cài và tạo hàng đợi in. Máy in qua mạng LAN thì bấm Thêm máy in…, chọn mẫu máy rồi nhập địa chỉ IP. Điều khoản của Canon chỉ cho phép dùng cho mục đích cá nhân, phi thương mại.

Và PrtSc hoặc Win+Shift+S giờ chụp được màn hình (trước đây hai phím này không có tác dụng): kéo chọn vùng, Ctrl+C rồi dán thẳng vào Zalo hay Messenger.

Văn phòng bạn đang dùng máy in Canon nào? Nếu bạn in thử được (hay không được), kể lại giúp bọn mình nhé.
```

### V10. v1.3.10
- **Tiêu đề:** CaramOS 1.3.10: thông báo nói đúng chuyện hơn
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** không cần
```text
Bản 1.3.10 (17/11/2026) sửa mấy thông báo làm người dùng lo không cần thiết:

- Lỡ đóng ô nhập mật khẩu khi cập nhật, Trung tâm cập nhật báo "Chưa cập nhật" kèm nút Thử lại, thay vì "Cập nhật thất bại".
- Đang có một lần cập nhật khác chạy thì bạn thấy "Đang có một lần cập nhật khác" và chỉ cần đợi.
- Máy in Canon cắm USB mà máy tính không giao tiếp được (cáp lỏng, cổng hỏng, cắm qua hub) được báo "Máy in chưa kết nối được" kèm cách xử lý.
- Laptop dùng card đồ họa Intel GM45 không còn bị báo nhầm là chưa có driver.

Có thông báo nào trên CaramOS từng làm bạn hoang mang không? Bọn mình muốn thông báo nào cũng nói đúng chuyện và chỉ cách làm tiếp.
```

### V11. v1.3.11
- **Tiêu đề:** CaramOS 1.3.11: mỗi ngày một ảnh Việt Nam làm hình nền, và màu nhấn tự chọn
- **Thẻ:** Thông báo, Thảo luận
- **Ảnh bìa:** chưa có; nên chụp mới ô Màu nhấn hoặc thư mục Việt Nam mỗi ngày
```text
Hai thay đổi chính trong CaramOS 1.3.11 (17/11/2026) đều đến từ góp ý của người dùng.

Hình nền Việt Nam mỗi ngày: mở Cài đặt hệ thống > Hình nền, bấm thư mục Việt Nam mỗi ngày rồi chọn một ảnh. Từ đó mỗi ngày hình nền là một ảnh mới về thiên nhiên, cảnh đẹp, công trình của Việt Nam, trong bộ 45 ảnh từ Wikimedia Commons có giấy phép tự do. Chọn hình nền khác là thôi đổi.

Màu nhấn: Control Center có ô Màu nhấn với 8 màu có sẵn, theo chủ đề hệ thống, hoặc Màu khác… để tự chọn. Máy cập nhật lên 1.3.11 thấy ô này từ lần đăng nhập sau.

Máy đang dùng CaramOS: mở Trung tâm cập nhật, bấm Cập nhật ngay. Cài mới: https://caramos.vietnamlinuxfamily.net

Bạn thích để hình nền cố định hay đổi mỗi ngày? Nếu đã thử, ảnh nào bạn thấy đẹp nhất?
```
