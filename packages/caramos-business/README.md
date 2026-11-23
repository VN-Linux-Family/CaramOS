# caramos-business (CaramOS Doanh nghiệp)

Gói cho công ty dùng CaramOS. Một **máy quản lý** quản lý các **máy nhân viên** trong mạng nội bộ: hình nền, Desktop và Tài liệu trên máy chủ, ổ dùng chung, trình duyệt (trang chủ, dấu trang, chặn trang web theo giờ, tìm kiếm an toàn), máy in, Wi-Fi, ứng dụng bắt buộc và bị cấm, lịch bật/tắt máy, USB lưu trữ, khóa màn hình, tường lửa, máy dùng chung (phiên khách, đóng băng với giờ bảo trì), bản lưu hệ thống bằng Timeshift, theo cả công ty, từng phòng ban hoặc từng máy. Có danh sách máy với tình trạng, thao tác tức thì (khóa máy, tin nhắn, khởi động lại, tắt máy, cập nhật), phiếu hỗ trợ và hỗ trợ từ xa khi nhân viên đồng ý, tài sản với lịch sử và biên bản bàn giao, báo cáo bản quyền phần mềm, báo cáo an toàn, nhật ký và sao lưu.

Máy nhân viên ghép bằng mã 6 số (kiểm tra bằng SPAKE2, mã không đi qua mạng), hoặc bằng tệp ghép máy cho nhiều máy, kể cả các bản sao ổ đĩa của phòng máy khi khởi động lần đầu; người quản trị có thể duyệt từng máy.

**Mọi tính năng đều tắt sẵn**: máy nhân viên chỉ thay đổi khi người quản trị bật một tính năng. Không bao giờ xóa tệp của nhân viên, không theo dõi lén: không chụp màn hình, không ghi phím, không lưu lịch sử web, không định vị.

Người dùng cài gói từ App Center, mục "Doanh nghiệp". Gói nằm trên PPA của CaramOS và hiện miễn phí. Hướng dẫn cho người quản trị: `HUONG-DAN.md` (cài cùng gói, ở `/usr/share/doc/caramos-business/`).

## Cách chạy

| Phần | Ngôn ngữ | Chạy ở đâu |
|---|---|---|
| Cửa sổ `caramos-business` | Python, GTK 4 / libadwaita | cả hai vai |
| `caramos-business --prompt …`, `--help-request` | Python, GTK 4 | máy nhân viên: tin nhắn, đếm ngược, hỏi đồng ý, thanh báo hỗ trợ từ xa, thông báo, nhờ IT hỗ trợ |
| `caramos-business-helper` (qua pkexec) | Python | việc cần quyền root: chọn vai, ghép máy (mã, tệp), duyệt máy, tệp ghép máy, lưu thiết lập, gửi thao tác, phiếu hỗ trợ, tài sản, bản quyền, sao lưu, khôi phục, hỗ trợ từ xa, chuẩn bị ảnh đĩa |
| `caramos-business-server.service` | Python | máy quản lý: trả lời máy nhân viên trong mạng LAN (ghép máy SPAKE2, tệp ghép máy, thiết lập, phiếu hỗ trợ), giữ kết nối chờ thao tác, gửi Wake-on-LAN (cả giờ bảo trì) |
| `caramos-business-enroll.service` | Python (helper) | bản sao ổ đĩa của phòng máy: tự ghép khi khởi động lần đầu; tắt sẵn, `prepare-image` mới bật |
| `caramos-business-agent.service` | Rust (`agent/`) | máy nhân viên: lấy thiết lập đã ký, áp dụng, báo về máy quản lý |
| `caramos-business-agent session` (autostart) | Rust | máy nhân viên, trong phiên của từng người |

Hai bên nói chuyện theo `PROTOCOL.md` (phần 2 là bản 0.2, phần 3 là bản 0.3):
- Máy quản lý ký thiết lập và thao tác bằng khóa Ed25519; máy nhân viên ghi nhớ khóa đó lúc ghép máy (mã 6 số qua SPAKE2 với `python3-spake2`, hoặc tệp ghép máy).
- Mỗi máy nhân viên có khóa X25519 riêng: mọi yêu cầu có mã HMAC (từ 0.3 cả `GET /policy` và `/files`), mật khẩu Wi-Fi và khóa hỗ trợ từ xa được mã hóa riêng cho từng máy.
- `tests/protocol-examples/` (và `v2/`, `v3/`) là dữ liệu mẫu dùng chung cho test Python và test Rust; `v3/make_v3.py` tạo lại dữ liệu của bản 0.3.
- Mẫu biên bản bàn giao `usr/share/caramos-business/templates/bien-ban-ban-giao-tai-san.docx` do `tools/make-handover-template.py` tạo ra (byte giống hệt mỗi lần chạy); test so tệp đã commit với tệp công cụ tạo.

Cài gói xong, dịch vụ chưa chạy. Chỉ khi chọn vai trong cửa sổ thì helper mới bật dịch vụ của vai đó.

## Làm việc

```bash
make test          # test Python (cần python3-spake2; test xuất Excel cần python3-openpyxl)
agent/build.sh     # dựng và test phần Rust trong container Ubuntu 24.04 (rustc-1.85, cargo-1.85)
make pot           # sau khi đổi chữ trong giao diện: cập nhật po/, rồi dịch po/vi.po
make deb           # dựng .deb trong container
make source        # gói nguồn cho PPA
make upload        # ký và đưa lên ppa:vietnamlinuxfamily/caram-os
```

Launchpad dựng gói không có mạng, nên mọi crate của Rust nằm sẵn trong `agent/vendor`.
