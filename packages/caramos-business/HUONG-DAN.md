# Hướng dẫn CaramOS Doanh nghiệp cho người quản trị

CaramOS Doanh nghiệp giúp một **máy quản lý** quản lý các **máy nhân viên** trong mạng nội bộ của công ty: hình nền, thư mục trên máy chủ, ổ dùng chung, trình duyệt, máy in, Wi-Fi, ứng dụng, lịch bật/tắt máy, USB, khóa màn hình, tường lửa, máy dùng chung, bản lưu hệ thống, phiếu hỗ trợ, tài sản và các báo cáo.

**Mọi tính năng đều tùy chọn và tắt sẵn.** Ghép máy xong, máy nhân viên vẫn giữ nguyên như cũ. Chỉ khi bạn bật một tính năng và bấm **Lưu và gửi** thì máy nhân viên mới thay đổi. Bạn bật cho cả công ty, hoặc riêng cho từng phòng ban.

## 1. Cài đặt

Trên **mọi máy** (máy quản lý và máy nhân viên):

1. Mở **App Center**, chọn mục **Doanh nghiệp**.
2. Bấm **Cài đặt** ở **CaramOS Doanh nghiệp**.

Các máy phải cùng mạng nội bộ của công ty. Nếu đã bật tường lửa (ufw), máy quản lý tự mở cổng UDP 47021 và TCP 47022, máy nhân viên tự mở cổng UDP 47021 để tìm thấy máy quản lý.

## 2. Máy quản lý

1. Mở **CaramOS Doanh nghiệp**, chọn **Máy quản lý**, rồi nhập mật khẩu.
2. Nên chọn một máy luôn bật trong giờ làm việc: máy nhân viên nhận thiết lập và thao tác từ máy này.

Chỉ người dùng được cài phần mềm trên máy (nhóm quản trị) mới mở được phần quản lý.

## 3. Thêm máy nhân viên

Có hai cách: gõ **mã ghép máy** trên từng máy, hoặc dùng **tệp ghép máy** để thêm nhiều máy một lúc.

### Bằng mã ghép máy

1. Trên máy quản lý, mở trang **Máy nhân viên**, bấm **Thêm máy**, rồi **Hiện mã ghép máy**. Màn hình hiện một mã 6 số, dùng được trong 10 phút.
2. Trên máy nhân viên, mở **CaramOS Doanh nghiệp**, chọn **Máy nhân viên**, chọn máy quản lý trong danh sách, gõ mã, bấm **Kết nối** rồi nhập mật khẩu của máy nhân viên.
3. Máy hiện trong danh sách của máy quản lý.

Mỗi lần bấm **Hiện mã ghép máy** là một mã mới. Mã không bao giờ được gửi qua mạng: hai máy chỉ dùng mã để kiểm tra lẫn nhau, nên người khác trong mạng không bắt được mã, cũng không giả làm máy quản lý được. Mỗi lần gõ sai đều bị đếm; sai 20 lần thì máy quản lý tự dừng thêm máy, để không ai đoán mò được mã.

### Bằng tệp ghép máy

Dùng khi thêm nhiều máy, hoặc cho phòng máy (xem mục 4).

1. Trên máy quản lý, ở trang **Thêm máy**, bấm **Tạo tệp ghép máy…**. Chọn phòng ban cho các máy mới (hoặc không), số ngày tệp còn dùng được (1 đến 30, mặc định 7), số máy được thêm (1 đến 500, mặc định 30), và nơi lưu tệp, ví dụ một ổ USB. Tệp có tên `caramos-business-enroll.json`.
2. Cắm ổ USB vào máy nhân viên rồi mở **CaramOS Doanh nghiệp**: cửa sổ tự tìm thấy tệp. Bấm **Ghép máy bằng tệp này…**, kiểm tra tên máy quản lý, bấm **Ghép máy** rồi nhập mật khẩu. Nếu tệp không nằm ở thư mục gốc của USB, bấm **Chọn tệp…**.
3. Máy vào thẳng phòng ban đã chọn.

**Ai giữ tệp cũng thêm được máy** cho tới khi tệp hết hạn hoặc hết lượt: hãy giữ tệp như giữ chìa khóa, và xóa khỏi USB khi xong việc. Danh sách tệp ở trang **Thêm máy** cho biết mỗi tệp đã thêm bao nhiêu máy; bấm **Thu hồi** để tệp thôi hoạt động ngay, các máy đã thêm vẫn ở lại. Một tệp bị dùng sai nhiều lần (20 lần) sẽ tự tắt.

### Duyệt từng máy

Bật **Duyệt từng máy mới** ở trang **Thêm máy** nếu muốn tự tay cho từng máy vào công ty. Máy mới (bằng mã hay bằng tệp) hiện ở mục **Chờ duyệt** trên trang **Máy nhân viên** và trang **Tổng quan**, kèm địa chỉ IP, địa chỉ MAC, giờ xin vào và cách ghép. Bấm **Duyệt** cho máy bạn biết, **Từ chối** cho máy lạ. Trước khi được duyệt, máy không nhận được gì từ công ty, và cửa sổ trên máy đó ghi "Đang chờ máy quản lý duyệt máy này".

## 4. Phòng máy: nhân ổ đĩa cho nhiều máy

Cho phòng máy của trường hay công ty, nơi cài một máy mẫu rồi nhân ổ đĩa (ví dụ bằng Clonezilla) sang các máy khác.

1. Trên máy quản lý, tạo một **tệp ghép máy** (mục 3) cho phòng máy. Ô **Tên máy bắt đầu bằng** cho mỗi bản sao một tên riêng: với `phong-may`, các máy có tên như `phong-may-3f2a1c`.
2. Cài đặt máy mẫu theo ý muốn: ứng dụng, máy in, tài khoản học sinh hoặc nhân viên.
3. Chép tệp ghép máy vào máy mẫu (hoặc cắm USB có tệp).
4. Trên máy mẫu, mở **CaramOS Doanh nghiệp**, chọn **Chuẩn bị tạo ảnh đĩa…**, chọn tệp ghép máy, bấm **Chuẩn bị** rồi nhập mật khẩu. Máy mẫu rời công ty (nếu đang ghép), quên danh tính của mình (việc ghép máy, mã máy, khóa SSH) và cất tệp ghép máy để các bản sao dùng.
5. **Tắt máy mẫu ngay, và đừng bật lại** trước khi nhân xong ổ đĩa: bật lên một lần là nó tự vào công ty, và các bản sao sẽ dùng chung chỗ của nó.
6. Nhân ổ đĩa sang các máy khác.
7. Bật từng máy: mỗi máy tự tạo mã máy mới, tự đặt tên, rồi tự vào công ty khi máy quản lý trả lời (máy quản lý phải đang bật). Nếu máy quản lý chưa bật, máy thử lại mỗi phút. Nếu tệp đã hết hạn hay hết lượt, cửa sổ trên máy đó báo "Tệp ghép máy đã hết hạn hoặc hết lượt: hãy ghép máy này bằng mã".

Không cần làm gì trên từng máy. Nếu đã bật **Duyệt từng máy mới**, nhớ duyệt các máy ở trang **Máy nhân viên**.

## 5. Báo cho nhân viên

Theo Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15, điều 25, người lao động phải được biết các biện pháp công ty dùng trên máy của họ.

- Hãy **báo cho nhân viên bằng văn bản** những tính năng bạn bật, ví dụ ghi vào nội quy lao động hoặc gửi thông báo nội bộ. Trang **Báo cáo an toàn** có sẵn một đoạn văn liệt kê đúng những biện pháp bạn đã bật, để dán vào nội quy lao động (mục 12).
- Trên mỗi máy nhân viên, sau khi ghép máy, mỗi người dùng thấy một thông báo nói công ty quản lý những gì. Người đang dùng máy lúc ghép thấy thông báo ngay, trước khi các thiết lập của công ty có hiệu lực; người khác thấy nó khi đăng nhập. Khi bạn bật thêm một tính năng, thông báo hiện lại. Trong cửa sổ CaramOS Doanh nghiệp luôn có trang **Máy này do công ty quản lý**, liệt kê đúng những tính năng đang bật trên máy đó.
- Công ty **không xem được**: màn hình (trừ khi nhân viên đồng ý cho hỗ trợ từ xa), những gì nhân viên gõ, các trang web họ vào, tin nhắn của họ, và tệp nằm ngoài thư mục của công ty. CaramOS Doanh nghiệp chặn, không theo dõi.

## 6. Phòng ban

Ở trang **Phòng ban**, bấm **Thêm phòng ban** (ví dụ Kế toán, Kinh doanh, Kho), rồi **Chọn máy** cho từng phòng. Mỗi máy thuộc nhiều nhất một phòng.

Ở mỗi trang thiết lập, ô **Áp dụng cho** ở trên cùng cho chọn **Cả công ty**, một phòng ban, hoặc **Một máy**. Với một phòng ban, mỗi mục có ba lựa chọn:

- **Dùng thiết lập của công ty**;
- **Riêng cho phòng này**: ví dụ phòng Kế toán chặn USB, phòng Kinh doanh được vào mạng xã hội;
- **Tắt cho phòng này**: máy của phòng giữ nguyên như hiện tại.

Thiết lập riêng cho một máy (ví dụ máy xách tay của giám đốc) được ưu tiên hơn thiết lập của phòng và công ty.

Mọi thay đổi chỉ có hiệu lực khi bấm **Lưu và gửi** ở thanh dưới cùng. Máy đang bật nhận trong vài giây, máy đang tắt nhận khi bật lên.

## 7. Các tính năng

**Hình nền.** Một ảnh cho ngày thường, ảnh riêng cho ngày lễ (ghi ngày/tháng, lặp lại mỗi năm; Tết Âm lịch nhớ sửa ngày mỗi năm), và có thể không cho nhân viên đổi.

**Thư mục.** Desktop và Tài liệu của mỗi nhân viên nằm trong thư mục của họ trên máy chủ hoặc NAS (SMB), ví dụ `smb://nas.congty.local/nhanvien/%u`; `%u` là tên đăng nhập. Trên NAS, tạo cho mỗi nhân viên một thư mục mang đúng tên đăng nhập và một tài khoản. Tệp còn trên máy được chuyển vào `Chưa sắp xếp/<ngày>` trên máy chủ, **không tệp nào bị xóa**.

**Ổ dùng chung.** Các thư mục chung (ví dụ `smb://nas/ketoan`) hiện sẵn ở cột bên của trình quản lý tệp.

**Trình duyệt.** Cho Firefox, Chrome, Chromium, Cốc Cốc, Edge và Brave:
- trang chủ và dấu trang của công ty (có gợi ý Thuế điện tử, Hóa đơn điện tử, Bảo hiểm xã hội);
- chặn trang web: chọn nhóm Mạng xã hội, Video, Trò chơi, Mua sắm, hoặc gõ thêm từng trang. **Zalo không bao giờ nằm trong các nhóm này**;
- chặn luôn, hoặc chỉ trong giờ làm việc. Bấm **Giờ hành chính** để điền 8:00–12:00 và 13:30–17:30, thứ Hai đến thứ Bảy;
- tìm kiếm an toàn cho Google, Bing và YouTube.

**Máy in.** Bấm **Tìm trong mạng** để tìm máy in, hoặc **Thêm…** rồi gõ địa chỉ IP. Chọn một máy in mặc định.

**Wi-Fi.** Tên mạng, kiểu bảo mật và mật khẩu. Mật khẩu được mã hóa riêng cho từng máy và **không hiện lại** sau khi lưu (chỉ ghi "đã lưu"). Muốn đổi thì bấm **Đổi mật khẩu**.

**Ứng dụng.** Chọn từ danh mục của App Center: ứng dụng **bắt buộc cài** (máy thiếu sẽ được cài) và **không được cài** (máy có sẽ bị gỡ).

**Lịch bật/tắt máy.** Tắt máy vào giờ đã đặt: trước giờ tắt, người đang dùng máy thấy đồng hồ đếm ngược và có thể hoãn vài lần; máy không ai đăng nhập thì tắt luôn; máy xách tay có thể để nguyên, cho ngủ hoặc tắt. Bật máy theo lịch: máy tự hẹn giờ bật trước khi tắt, và máy quản lý gửi tín hiệu Wake-on-LAN qua dây mạng (máy quản lý phải đang bật; một số máy cần bật Wake-on-LAN trong BIOS).

**Bảo mật.**
- USB lưu trữ: cho phép, chỉ đọc, hoặc chặn. Bàn phím, chuột, máy in và **token chữ ký số vẫn dùng được**. Khi cần, mở USB tạm thời cho một máy ở trang của máy đó.
- Tự khóa màn hình sau một số phút không dùng.
- Bật tường lửa: máy khác không kết nối vào máy nhân viên được, kể cả SSH hay thư mục chia sẻ trên máy nhân viên; vào mạng, in ấn vẫn bình thường.

**Kiểm kê tự động** (ở trang Máy nhân viên). Khi bật, máy gửi cấu hình phần cứng, số serial, ổ đĩa, pin, màn hình và danh sách ứng dụng, để làm danh sách tài sản và báo cáo bản quyền phần mềm. Khi tắt, máy chỉ gửi tên máy, người đang dùng và vài con số về tình trạng máy.

**Máy dùng chung.** Cho máy nhiều người cùng dùng: phòng máy, phòng họp, quầy lễ tân.
- **Phiên khách**: màn hình đăng nhập có thêm phiên khách, ai cũng vào được mà không cần tài khoản; tệp của khách bị xóa khi khách đăng xuất.
- **Đóng băng máy**: mọi thay đổi trên máy (tệp, thiết lập, ứng dụng cài thêm) bị xóa khi khởi động lại, nên máy luôn sạch như lúc đóng băng. Bật hay tắt đều có hiệu lực từ lần khởi động lại tới. Mỗi khi có người đăng nhập, máy nhắc: "Máy này tự xóa mọi thay đổi khi khởi động lại. Hãy lưu tệp vào ổ dùng chung hoặc USB."
- **Giờ bảo trì** (bắt buộc khi đóng băng): máy đóng băng chỉ nhận bản cập nhật và ứng dụng của công ty vào giờ này, ví dụ 2:00 sáng Chủ nhật. Đến giờ, máy quản lý đánh thức máy, máy khởi động lại ở chế độ bảo trì, cập nhật, rồi khởi động lại và đóng băng như cũ. Trong lúc bảo trì không ai đăng nhập được. Nếu có người đang dùng máy, máy thử lại mỗi 15 phút, quá thời gian bảo trì thì bỏ qua hôm đó. Máy quản lý nên bật vào giờ bảo trì.
- Máy dưới 3 GB bộ nhớ không đóng băng, trừ khi bật **Vẫn đóng băng máy có dưới 3 GB bộ nhớ**: khi đóng băng, mọi thay đổi nằm trong bộ nhớ nên máy ít bộ nhớ có thể chậm.
- Không bật được đóng băng cùng lúc với **Bản lưu hệ thống**, hay với việc dọn Màn hình nền và Tài liệu lên máy chủ: khi lưu sẽ bị từ chối.

**Bản lưu hệ thống.** Máy tự chụp bản lưu của hệ thống bằng Timeshift, hằng ngày, hằng tuần hoặc hằng tháng, giữ lại một số bản (mặc định 3), và chụp thêm một bản trước mỗi lần cập nhật. Khi một bản cập nhật làm hỏng máy, bạn quay lại bản lưu trước đó.
- **Bản lưu nằm trên cùng ổ đĩa với hệ thống, không phải bản sao lưu**: ổ đĩa hỏng thì mất luôn các bản lưu. Bản lưu chỉ gồm hệ thống, không gồm tệp của mọi người: hãy để tệp trên máy chủ và sao lưu ở nơi khác.
- Bản lưu đầu tiên chiếm chỗ gần bằng hệ thống (khoảng 7 GB); các bản sau chỉ thêm phần thay đổi. Trang **Báo cáo an toàn** cho biết bản lưu gần nhất và dung lượng của từng máy.
- **Quay lại một bản lưu** (làm ngay trên máy đó): mở ứng dụng **Timeshift** trong menu, nhập mật khẩu, chọn bản lưu theo ngày giờ, bấm **Restore** (Khôi phục), giữ nguyên lựa chọn ổ đĩa và bấm **Next** cho tới khi máy khởi động lại. Nếu máy không vào được nữa, khởi động bằng USB cài CaramOS, mở Timeshift ở đó và làm như trên.
- Tắt tính năng này thì máy thôi chụp, nhưng các bản lưu đã có vẫn còn; muốn xóa thì xóa trong Timeshift.

## 8. Thao tác tức thì

Ở trang của một máy: **Khóa máy**, **Gửi tin nhắn** (có thể yêu cầu bấm "Đã đọc"), **Khởi động lại**, **Tắt máy** (có báo trước), **Cập nhật**, **Mở USB tạm thời**, **Kiểm kê lại**. Nút **Thao tác hàng loạt** ở trang Máy nhân viên làm cho mọi máy hoặc một phòng ban.

Máy đang bật làm trong vài giây. Kết quả hiện ở **Thao tác gần đây** trên trang của máy. Máy đang tắt thì khi bật lên sẽ không khóa, không hiện tin nhắn, không khởi động lại hay tắt theo thao tác gửi lúc nó tắt; cập nhật, mở USB và kiểm kê thì vẫn làm nếu chưa hết hạn.

## 9. Phiếu hỗ trợ và hỗ trợ từ xa

- Nhân viên bấm **Nhờ IT hỗ trợ** trong cửa sổ CaramOS Doanh nghiệp và viết vài chữ. Yêu cầu thành một **phiếu hỗ trợ** (ví dụ HT-0007), hiện ở trang **Tổng quan** và trang **Phiếu hỗ trợ**, kèm thông báo trên màn hình máy quản lý. Phiếu ghi sẵn tình trạng và cấu hình của máy lúc gửi.
- Ở trang **Phiếu hỗ trợ**, mở một phiếu để đổi **trạng thái** (Mới, Đang xử lý, Chờ nhân viên trả lời, Đã xong), ghi **người xử lý**, và thêm **ghi chú**. Ghi chú có bật **Nhân viên thấy ghi chú này** sẽ được gửi tới máy của nhân viên; ghi chú nội bộ chỉ ở máy quản lý.
- Nhân viên xem phiếu của mình ở mục **Yêu cầu của bạn** trong cửa sổ CaramOS Doanh nghiệp, và nhận thông báo khi phiếu đổi trạng thái hay có câu trả lời.
- **Báo cáo tháng…** xuất tệp Excel: số phiếu theo trạng thái, thời gian trả lời đầu tiên, và danh sách phiếu.
- **Hỗ trợ từ xa**: bấm ở trang của phiếu, ở trang **Tổng quan** hoặc trang của máy, chọn **Xem và điều khiển** hoặc **Chỉ xem**. Nhân viên được hỏi trước và có một phút để đồng ý; trong lúc hỗ trợ, máy của họ luôn hiện một cửa sổ nhỏ có nút **Dừng**.
- Mỗi lần hỗ trợ từ xa dùng một khóa riêng, chỉ máy quản lý và máy được hỗ trợ biết; đường truyền được mã hóa, và máy khác trong mạng không chen vào cửa sổ xem màn hình được.

## 10. Tình trạng máy

Trang **Tổng quan** đếm máy đang bật, không bật và **cần xem**. Máy cần xem khi: ổ đĩa sắp đầy hoặc sắp hỏng, pin chai, bản vá bảo mật chờ quá 7 ngày, cần khởi động lại quá 3 ngày, tường lửa bị tắt, đồng hồ lệch, lâu không bật, một thiết lập không áp dụng được, bản lưu hệ thống quá cũ, máy đóng băng hơn 8 ngày chưa được bảo trì, máy cần khởi động lại để bắt đầu hay thôi đóng băng, hoặc **có thể là máy nhân bản** (hai máy cùng báo về bằng mã của một máy: xem mục 14).

## 11. Tài sản

Trang **Tài sản** liệt kê mọi máy của công ty và cả những tài sản không phải máy đã ghép: màn hình, máy in, máy chưa ghép. Bấm **Thêm tài sản…** để thêm những thứ đó.

- Mỗi tài sản có **loại**, **trạng thái** (Trong kho, Đang dùng, Đang sửa, Đã thanh lý), **người dùng** và **dùng từ ngày**, mã tài sản, ngày mua, giá, bảo hành, vị trí, ghi chú. Thông tin của một máy cũng sửa được ở trang của máy đó.
- **Lịch sử**: mỗi lần đổi trạng thái hay người dùng đều được ghi lại, kèm người làm và giờ; bạn có thể thêm ghi chú vào lịch sử.
- Trang **Tổng quan** nhắc các tài sản **sắp hết bảo hành** (trong 30 ngày) và các tài sản **đang sửa**.
- **In biên bản bàn giao…**: ở một tài sản, hoặc đánh dấu nhiều tài sản trong danh sách rồi bấm nút ở trên. Điền tên công ty, số biên bản, địa điểm, người giao, người nhận, chức vụ và lý do, rồi chọn nơi lưu. Bạn nhận tệp Word theo mẫu Nghị định 30/2020, và tệp PDF nếu máy có LibreOffice. Ô nào để trống thành dòng chấm để điền tay; cột tình trạng để trống, ghi lúc bàn giao. Việc in biên bản được ghi vào lịch sử của tài sản.
- **Nhân viên nghỉ việc** (ở trang của máy): đánh dấu từng việc khi làm xong: thu lại máy, lưu trữ thư mục của họ trên máy chủ (làm trên NAS), đưa họ ra khỏi phòng ban, nhập kho máy (tình trạng của máy chuyển thành **Trong kho**).
- Ở trang **Máy nhân viên**, **Xuất danh sách tài sản** cho tệp Excel theo mẫu biên bản kiểm kê, hoặc CSV. Bật **Kiểm kê tự động** để có cả cấu hình và số serial.

## 12. Báo cáo

### Bản quyền phần mềm

Trang **Bản quyền phần mềm** liệt kê các ứng dụng tìm thấy trên các máy (cần bật **Kiểm kê tự động**), chia theo loại giấy phép:
- **Phần mềm tự do**: mã nguồn mở, công ty được dùng;
- **Miễn phí**: miễn phí nhưng mã nguồn đóng, theo điều khoản của hãng (ví dụ Chrome, Zalo, Zoom);
- **Thương mại**: công ty cần mua bản quyền (ví dụ GeoGebra khi dùng trong công ty);
- **Chưa rõ**: chưa xác định được, hãy hỏi lại hãng.

Ở mục **Bản quyền công ty đã mua**, bấm **Thêm bản quyền…** để nhập các bản quyền trên hóa đơn: tên sản phẩm, số máy được dùng, ngày hết hạn, số hóa đơn và ứng dụng tương ứng. Báo cáo so số máy được dùng với số máy đang có ứng dụng đó, và báo khi thiếu bản quyền. Bấm **Xuất Excel…** hoặc **Xuất PDF…** để có báo cáo có chỗ ký cho người lập và giám đốc, kèm một trang cho mỗi máy.

Báo cáo này liệt kê phần mềm tìm thấy trên các máy; nó không xác nhận việc sử dụng đã đủ bản quyền.

### Báo cáo an toàn

Trang **Báo cáo an toàn** cho biết, theo lần báo gần nhất của từng máy: tường lửa, bản vá bảo mật đang chờ và từ ngày nào, cần khởi động lại, khóa màn hình, USB lưu trữ, mã hóa ổ đĩa, đóng băng, lần bảo trì và bản lưu hệ thống gần nhất, lần cuối thấy máy và các vấn đề cần xem; cùng số liệu cho cả công ty.

- Chọn **Khoảng thời gian** để kèm phần trích nhật ký quản trị vào báo cáo.
- Mục **Đoạn đưa vào nội quy lao động** có sẵn một đoạn văn liệt kê đúng những biện pháp kỹ thuật bạn đã bật, theo điểm a khoản 3 Điều 25 Luật Bảo vệ dữ liệu cá nhân 91/2025/QH15. Bấm **Sao chép** rồi dán vào nội quy lao động.
- **Xuất Excel…** hoặc **Xuất PDF…** cho báo cáo có chỗ ký, phần trích nhật ký và đoạn nội quy.

Đây là báo cáo hiện trạng kỹ thuật; không phải chứng nhận đạt cấp độ an toàn thông tin nào.

**Tạo PDF** cần LibreOffice: cài từ App Center. Nếu chưa có, hãy xuất Excel rồi in ra PDF từ LibreOffice.

## 13. Nhật ký và sao lưu

- **Nhật ký** ghi mọi thay đổi: ai làm, lúc nào.
- **Sao lưu**: tạo bản sao lưu có mật khẩu và cất ở nơi an toàn. Bản sao lưu gồm cả phiếu hỗ trợ, tài sản, bản quyền đã mua và tệp ghép máy. Nếu máy quản lý hỏng, cài CaramOS Doanh nghiệp trên máy khác, chọn **Khôi phục máy quản lý từ bản sao lưu**: các máy nhân viên tự tìm thấy máy mới, không phải ghép lại. Mất mật khẩu thì không mở được bản sao lưu.

## 14. Bỏ một máy

- **Trên máy quản lý**: ở trang của máy, bấm **Gỡ khỏi công ty**. Máy nhận một thông báo có chữ ký của máy quản lý, tự trả lại mọi thứ như trước khi ghép (kể cả tường lửa), rồi thôi nhận thiết lập. Cửa sổ trên máy đó ghi: "Công ty đã gỡ máy này khỏi máy quản lý … lúc … ngày …". Máy đang tắt sẽ nhận thông báo khi bật lên (trong vòng một năm).
- **Trên máy nhân viên**: bấm **Rời máy quản lý của công ty**. Desktop và Tài liệu trở về máy, tệp trên máy chủ vẫn ở đó.
- **Máy đang đóng băng**: khi rời hay bị gỡ, máy cần **khởi động lại một lần** để gỡ hẳn thiết lập của công ty; cửa sổ sẽ nhắc.
- **Máy được sao ổ đĩa từ một máy đã ghép** (nhân bản, không qua **Chuẩn bị tạo ảnh đĩa**): máy mới không làm gì cho công ty (Desktop và Tài liệu của người dùng trở về thư mục trên máy), và cửa sổ CaramOS Doanh nghiệp trên đó báo là bản sao, với nút **Ghép lại**: bấm rồi ghép như một máy mới. Nếu bản sao giống hệt đến từng byte, máy nhân viên không tự nhận ra được, nhưng máy quản lý báo **có thể là máy nhân bản**: gỡ máy đó khỏi công ty, rồi trên từng máy bấm **Rời máy quản lý của công ty** và ghép lại. Lần sau, hãy nhân ổ đĩa theo mục 4.

## 15. An toàn

- Máy quản lý ký mọi thiết lập và thao tác bằng khóa riêng. Máy nhân viên chỉ làm theo những gì có chữ ký đúng của máy quản lý đã ghép.
- Mã ghép máy không đi qua mạng, và tệp ghép máy chỉ dùng được cho máy gửi nó: người nghe trộm trong mạng không lấy được gì để thêm máy của mình.
- Mỗi máy nhân viên có khóa riêng; mọi yêu cầu nó gửi đều có mã xác thực. Chỉ máy đã ghép (và đã duyệt, nếu bật duyệt) mới đọc được thiết lập và ảnh của công ty.
- Một thao tác máy đã làm xong sẽ không được gửi lại, kể cả với máy đóng băng.
- Máy quản lý **không** chạy được lệnh tùy ý trên máy nhân viên: chỉ những thao tác có sẵn ở trên.
