# MISA JSC business software: client requirements and Linux compatibility (researched 2026-11-05)

How to read the sources: [MISA official] means a MISA help page, product page or document. [Gov/press] means a government site or a news article. [Third-party] means another vendor or a guide. [User report] means a forum post. "fetched" means the page was opened and read. "search excerpt" means the fact was seen only in a search-result summary, and the page was not opened, so treat it with more caution. A page date is the "Cập nhật" (updated) or publication date shown on the page. Nothing was logged into, downloaded or installed.

## 1. MISA SME (desktop accounting): OS and components, web or remote access, Wine

### Takeaway
MISA SME is a Windows-only client–server desktop application that stores its data in Microsoft SQL Server (users say SQL Server Express). MISA publishes no support for macOS, Linux or Wine, and offers no web client for SME; it sends browser users to AMIS Kế toán instead. From 1/10/2026 MISA no longer sells the one-time-payment desktop licence to new customers; the annual-subscription SME is still sold. I found no report of SME running under Wine.

### Cited Findings
- [MISA official, fetched] The download page is titled "Tải miễn phí phần mềm MISA SME 2026" (footer © 1994–2026). Minimum hardware: "CPU Intel Core i3 hoặc cao hơn", RAM "2GB hoặc cao hơn", disk "5GB trống hoặc nhiều hơn", display "Độ phân giải 1024×768 hoặc tốt hơn", plus a sound card or speakers (for tutorial videos) and an A4 printer — [sme.misa.vn/download](https://sme.misa.vn/download/)
- [MISA official, fetched] The same page lists these operating systems under "Hệ điều hành": Windows 7 SP1, Windows 8/8.1, Windows 10, and Windows Server 2008 SP2, 2008 R2, 2012, 2012 R2, 2016 and 2019. It says SME "được cài đặt và sử dụng tốt trên hệ điều hành Windows 7 SP1 (64bit), Bộ vi xử lý CPU Intel Core i3, RAM 4GB, Đĩa cứng trống 10 GB". Windows 11 does not appear in the list as extracted. The page gives no .NET or SQL Server version and says nothing about macOS, Linux, Wine, cloud or remote access — [sme.misa.vn/download](https://sme.misa.vn/download/)
- [MISA official, search excerpt] A download guide from the SME.NET 2019–2021 era describes the client–server architecture: one data server running SQL Server is shared by the whole system and several workstations connect to it; one machine can be both server and workstation. It gives a minimum of a Dual Core 1.0 GHz CPU, 1 GB RAM, 5 GB disk and 1024×768, lists Windows 7 SP1 through Windows Server 2012 R2, and advises lowering Windows UAC to "Never notify" before installing — [sme.misa.vn/62759](https://sme.misa.vn/62759/huong-dan-tai-phan-mem-ke-toan-mien-phi/)
- [MISA official, search-result titles] The product was named "MISA SME.NET" in releases up to about 2021 (for example "MISA SME.NET 2020 R7") and "MISA SME 2023" later — [sme.misa.vn/64076](https://sme.misa.vn/64076/sap-ra-mat-phan-mem-ke-toan-misa-sme-net-2020-r7-de-dang-ket-noi-voi-co-quan-thue-tang-them-mau-hoa-don-dien-tu); [sme.misa.vn/223659](https://sme.misa.vn/223659/dung-thu-va-cai-dat-phan-mem-ke-toan-misa-sme/)
- [Gov site, fetched] An English neac.gov.vn article titled "Instructions for installing digital signature MISA-CA" (posted 24/12/2021) is actually about installing MISA SME together with Microsoft SQL Server. Its screenshots are labelled "SQL 2018", and it says that if SQL is not running the user must start the SQL service through services.msc (Windows+R). No token driver is mentioned — [neac.gov.vn](https://neac.gov.vn/en/news/detail/instructions-for-installing-digital-signature-misa-ca-222.htm)
- [MISA official, fetched] The SME 2023 installation guide (14/07/2023) says the installer is sent by email and extracts itself. The user picks the data drive ("Lựa chọn ổ chứa dữ liệu cài đặt phần mềm") and an installation type, then "Nhấn “Cài đặt” để bắt đầu tiến trình cài đặt phần mềm MISA SME 2023". For browser use it points to AMIS Kế toán: "Nếu anh/chị muốn sử dụng phần mềm kế toán ngay trên trình duyệt, không cần tải bộ cài hay cấu hình máy chủ" — [sme.misa.vn/223659](https://sme.misa.vn/223659/dung-thu-va-cai-dat-phan-mem-ke-toan-misa-sme/)
- [MISA official, fetched] Notice dated 10/08/2026, "[THÔNG BÁO] Về việc ngừng cung cấp sản phẩm MISA SME Bản trả phí 1 lần (Desktop)" — [sme.misa.vn/349227](https://sme.misa.vn/349227/thong-bao-ve-viec-ngung-cung-cap-san-pham-misa-sme-ban-tra-phi-1-lan-desktop/):
  - "MISA sẽ ngừng cung cấp mới sản phẩm MISA SME bản trả phí 1 lần (Desktop)" from 1/10/2026.
  - Existing customers "vẫn có thể tiếp tục sử dụng phần mềm bình thường", keep support and maintenance "theo chính sách hiện hành", and "Không bắt buộc phải chuyển đổi ngay".
  - For annual-subscription customers MISA "chưa thay đổi chính sách bán hàng bản trả phí hàng năm", but it recommends moving to AMIS Kế toán Online.
  - MISA offers "Miễn phí công cụ chuyển đổi dữ liệu từ MISA SME bản trả phí 1 lần (Desktop)", plus switching incentives and free training.
  - The notice contrasts automatic updates online with desktop users installing updates by hand. It does not promise future regulatory updates for the desktop edition.
- [MISA official, fetched] MISA's list of USB-token problems includes an SME signing error: "Không thể thực hiện ký điện tử. Vui lòng kiểm tra lại kết nối với USB Token". This shows SME signs with a USB token plugged into the local PC — [helpesign.misa.vn](https://helpesign.misa.vn/article-categories/cac-van-de-thuong-gap-khi-ky-usb-token/)
- [App Store, search excerpt] The "MISA SME" iOS app is described as the mobile app of MISA SME.NET. It is an iPad companion, not a macOS desktop build — [App Store](https://apps.apple.com/us/app/id1444700674)
- [User report, search excerpt] In voz.vn threads asking for advice on a MISA server, one member writes "Cái Misa chạy SQL Express, mà bản Express nó giới hạn nhiều thứ nên hiệu năng không cao", and another says MISA uses fairly old SQL technology and has moved to a web version. I did not open the threads, so I have not checked which thread each quote comes from — [voz.vn thread 735475](https://voz.vn/t/can-tu-van-may-chu-misa.735475/); [voz.vn thread 615724](https://voz.vn/t/xin-tu-van-may-chu-cho-phan-mem-ke-toan-chi-phi-4x-trieu.615724/)

### Inferences
- The "SME.NET" name, the SQL Server back end and the Windows-only install steps point to a .NET Framework desktop client with a local or LAN SQL Server (Express) instance. Neither part is documented to work under Wine.
- On Linux, the realistic choices are:
  - a Windows virtual machine (for example KVM/virt-manager or VirtualBox, with USB passthrough when a token is used), or
  - remote desktop (RDP, for example with Remmina) to a Windows PC or server that runs SME.
- Wine is untested and would have to handle .NET Framework, SQL Server connectivity and USB-token signing all at once, so the risk is high.
- In SME's client–server model, a Linux PC could at most be the workstation. MISA's installer sets up the data server on Windows. Microsoft does ship SQL Server for Linux, but nothing suggests MISA supports it (speculative).
- New one-time desktop licences are not sold after 1/10/2026, and MISA is pushing AMIS Kế toán Online. So for new MISA customers, Linux support is mostly a question about AMIS in the browser. Existing SME users will need a Windows VM or RDP.

### Gaps
- No MISA page found states which SQL Server version or edition (or instance name) SME 2025/2026 installs, or which .NET Framework version it needs. "SQL 2018" on the NEAC page does not match any SQL Server release name (the releases are 2016, 2017, 2019, 2022, 2025), so it is probably a mistake.
- I found no statement on whether SME 2026 officially supports Windows 11.
- I found no official web client or remote-access option for SME. I saw only marketing-level claims about working "from anywhere" and did not verify them.
- I found no WineHQ AppDB entry and no forum or blog report of SME (or MISA KYSO) under Wine or Proton. Searches covered general Vietnamese queries, WineHQ-related pages, and voz.vn and tinhte.vn.

## 2. MISA AMIS Kế toán (cloud accounting): supported browsers and what must be installed locally

### Takeaway
AMIS Kế toán runs in the browser. MISA officially lists Windows 7 or later and macOS desktops, plus tablets and phones, with mainstream browsers (Chrome, Firefox, Cốc Cốc, Opera, Safari, Edge). It never lists Linux. The accounting work needs nothing installed. Signing with a USB token needs the Windows-only MISA KYSO tool, which runs in the tray (MISA.KySo_Setup_latest.exe), and a newer report-printing tool is also an .exe. The two ways to sign without a token are MISA eSign remote signing and a provider's HSM.

### Cited Findings
- [MISA official, fetched] "Cấu hình máy tính để sử dụng phần mềm AMIS Kế toán" (Cập nhật 29/10/2025) — [helpact.misa.vn](https://helpact.misa.vn/kb/cau-hinh-may-tinh-de-su-dung-phan-mem-amis-ke-toan/):
  - Desktop operating system: minimum "Win 7, Mac OS", recommended "Win 10 trở lên".
  - Desktop browsers, minimum: Chrome 87+, Firefox 78+, Cốc Cốc 87+, Opera 65+, Safari 13+, Edge 88+. The "recommended" column lists lower versions (Chrome 75+, Firefox 67+, Cốc Cốc 75+), which contradicts the minimum column.
  - Tablets and phones: Chrome 75+, Firefox 67+, latest Safari, and 1366×768 or better.
  - Desktop hardware: Core i3 and "RAM>=8GB". Screen minimum 1366×768 at 13.3", recommended 1920×1080 at 21.5".
  - Bandwidth (minimum/recommended): under 15 computers 80/100 Mbps; 15–30 computers 100/120 Mbps; over 30 computers 120/200 Mbps.
  - The page mentions no plugin, KYSO, print tool, token driver or .NET, and no Linux.
- [MISA official, fetched] "Phần mềm AMIS Kế toán có sử dụng được trên Macbook, ipad, máy tính bảng không?" (Cập nhật 24/10/2025) says AMIS is "sử dụng được trên mọi thiết bị: máy tính WINDOW, MACBOOK, máy tính bảng mà không cần cài đặt". Browsers: Chrome 75+, Firefox 67+, Cốc Cốc 75+, Opera 65+, latest Safari. No Mac limitations are listed and Linux is not mentioned — [helpact.misa.vn](https://helpact.misa.vn/kb/phan-mem-amis-ke-toan-co-su-dung-duoc-tren-macbook-ipad-may-tinh-bang-khong/)
- [MISA official, fetched] "Thiết lập ký số" (Cập nhật 23/09/2026) — [helpact.misa.vn](https://helpact.misa.vn/kb/thiet_lap_ky_so/):
  - It offers three signing methods under Các tiện ích và thiết lập > Thiết lập ký số:
    1. "Sử dụng MISA eSign để ký các tài liệu": the user enters connection details that MISA provides.
    2. "Sử dụng USB ký số, chứng thư số để ký các tài liệu": the token must be valid and not revoked.
    3. "HSM server": needs an HSM account from the service provider.
  - For USB: insert the token, click "Tải về MISA KYSO" to get the installer MISA.KySo_Setup_latest.exe, then Tiếp tục → Cài đặt → Hoàn thành.
  - MISA KYSO then runs automatically after installation and after every restart.
- [MISA official, fetched] KYSO troubleshooting page "Phát hành hóa đơn chương trình báo MISA KYSO đã cũ" (Cập nhật 23/09/2026; filed under release R40 of 05/11/2022) — [helpact.misa.vn/?p=22872](https://helpact.misa.vn/?p=22872):
  - KYSO is downloaded from "Quản lý hóa đơn\Kết nối meInvoice" > "TẢI MISA KYSO". The user double-clicks the file to extract it, installs, and restarts.
  - "công cụ MISA KYSO sẽ tự động chạy", with an icon at the bottom-right of the screen. Updating: right-click the icon > "Thiết lập" > "Kiểm tra cập nhật" > "Cập nhật ngay". Reinstalling: Control Panel > Programs and Features.
  - An outdated version shows the warning "Công cụ MISA KYSO đã cũ".
  - All steps are Windows-specific. There is no OS list and nothing on how KYSO talks to the browser (no port or WebSocket details).
- [MISA official, search excerpt] "Bổ sung trình in báo cáo trên AMIS Kế toán": a newer report-printing tool is installed from a downloaded .exe, and Edge may warn when downloading it. Reports can also be exported to Excel or PDF or sent through Zalo. MISA added the tool because printing in the browser "trước đây không đáp ứng được" — [helpact.misa.vn](https://helpact.misa.vn/kb/bo-sung-trinh-in-bao-cao-tren-amis-ke-toan/)
- [MISA official, fetched] Document-signing guide (Cập nhật 16/03/2026) — [helpact.misa.vn/?p=78269](https://helpact.misa.vn/?p=78269):
  - With a USB token, PDFs are signed in Adobe Acrobat Reader DC (Tools > Certificates > Digitally Sign; "Nhập mã PIN của USB Token, nhấn OK để hoàn tất ký số"). Word and Excel files are signed through File > Info > Protect Document > Add a Digital Signature.
  - With MISA eSign, files are uploaded to the web app esignapp.misa.vn and the signature is placed there. The user then confirms in the MISA eSign phone app within 60 seconds (Face ID or Touch ID).
  - Remote signing accepts PDF, DOC/DOCX, XLS/XLSX, PPT/PPTX and JPG/PNG.

### Inferences
- The core of AMIS Kế toán should work in Chrome or Firefox on Linux Mint, because MISA lists those browsers and they run on Linux. Linux is still not an officially supported OS, so MISA support may refuse Linux-specific problems. Cốc Cốc also has a Linux build (general knowledge, not checked here).
- Every feature that needs a local helper is Windows-only according to MISA's documentation: USB-token signing through MISA KYSO and the .exe print tool. On Linux, the signing options that work are MISA eSign remote signing (approved on a phone) and a provider HSM. The guide's way of signing PDFs with a token uses Adobe Acrobat Reader DC, which has no current Linux version (general knowledge: Adobe dropped Linux Reader after 9.x).
- MISA lists macOS as supported for AMIS but documents KYSO only as a Windows .exe. Mac users may therefore have the same token problem, which would make remote signing MISA's de facto cross-platform answer (unconfirmed).

### Gaps
- I found no evidence either way on whether a macOS or other non-Windows build of MISA KYSO exists.
- MISA does not document how KYSO talks to the web app (a localhost port, a WebSocket or a custom URL scheme). That decides whether a Linux replacement or bridge is even possible.
- Unclear whether the .exe print tool is needed for any statutory output, or is only a convenience next to PDF and Excel export.
- A search summary mentioned an "AMIS WeSign" app for signing accounting documents linked to AMIS Kế toán. I could not verify it or tie it to a page.

## 3. MISA meInvoice (hoá đơn điện tử): how invoices are signed, the signing tool and its OS

### Takeaway
meInvoice invoices, whether issued from AMIS Kế toán or from meInvoice, can be signed in three ways:
- with a USB token through the Windows-only MISA KYSO tool;
- with MISA eSign remote signing, approved in the MISA eSign phone app (up to 50 invoices per approval);
- with an HSM account.

MISA's own e-invoice remote-signing guide still tells users to "Cài đặt MISA KYSO" before issuing. That contradicts the mTax guide, which says remote signing needs no tool. This has to be tested before anyone claims e-invoicing works on Linux.

### Cited Findings
- [MISA official, fetched] "Ký số hóa đơn điện tử từ xa với MISA eSign" (Cập nhật 07/09/2026) — [helpact.misa.vn](https://helpact.misa.vn/kb/ky-so-hoa-don-dien-tu-tu-xa-voi-misa-esign/):
  - Setup in AMIS: Thiết lập ký số > MISA eSign ("Sử dụng MISA eSign để ký các tài liệu"). The user enters the connection details sent after purchase, enters an authenticator OTP if the MISA ID has two-factor login, and picks a certificate if there are several.
  - Phone setup: install MISA eSign from the App Store or CH Play, log in, and register the device with an SMS OTP. Biometrics are Face ID or Touch ID on iOS, and Touch ID or a PIN on Android ("không đáp ứng FaceID trên điện thoại Android").
  - After "Phát hành HĐ": "Mở ứng dụng MISA eSign trên thiết bị xác thực đã đăng ký và nhấn Đồng ý để xác nhận ký hóa đơn điện tử". Also: "anh/chị không được đóng giao diện chờ xác thực ký hóa đơn điện tử trên phần mềm".
  - Invoice statuses: "Đã ký, Chưa ký, Từ chối xác thực".
  - "Phần mềm cho phép ký số hàng loạt tối đa cho 1 lần ký là 50 hóa đơn".
  - Phones: "Hệ điều hành: Android 5.0 trở lên, iOS 11 trở lên".
- [MISA official, fetched] The same page, under heading "2.8 Ký số phát hành hóa đơn điện tử", says: "Lưu ý: Trước khi phát hành hóa đơn, anh/chị cần: … Cài đặt MISA KYSO. Xem hướng dẫn [Tại đây]". The page never says that no tool is needed and does not limit the KYSO note to USB tokens — [helpact.misa.vn](https://helpact.misa.vn/kb/ky-so-hoa-don-dien-tu-tu-xa-voi-misa-esign/). By contrast, for MISA eSign the mTax guide says "Không cần cài đặt thêm bất kỳ công cụ nào." — [helpact.misa.vn](https://helpact.misa.vn/kb/nop-to-khai-thue-truc-tuyen-qua-mtax/)
- [MISA official, fetched] A help page on signing with a USB token directly in meInvoice (Cập nhật 07/08/2026) says "Máy tính của người mua phải chạy công cụ MISA KYSO và cắm USB Token của đơn vị vào máy tính". A buyer who does not use meInvoice or lacks KYSO clicks "Tải về MISA KYSO" — [helpact.misa.vn/?p=75693](https://helpact.misa.vn/?p=75693)
- [MISA official, fetched] The MISA KYSO installer is MISA.KySo_Setup_latest.exe. It starts automatically at boot, shows a tray-area icon and is uninstalled through the Windows Control Panel — [Thiết lập ký số](https://helpact.misa.vn/kb/thiet_lap_ky_so/); [KYSO đã cũ](https://helpact.misa.vn/?p=22872)
- [MISA official, fetched] meInvoice USB-token errors that MISA lists: "System.Security.Cryptography.CryptographicException: The keyset is not defined." and "The operation requires a smart card, but no smart card is curently in the device" — [helpesign.misa.vn](https://helpesign.misa.vn/article-categories/cac-van-de-thuong-gap-khi-ky-usb-token/)
- [MISA official, fetched] HSM signing is offered in Thiết lập ký số with an account from the provider — [helpact.misa.vn](https://helpact.misa.vn/kb/thiet_lap_ky_so/)
- [MISA marketing, search excerpt] "Doanh nghiệp cũng có thể sử dụng chữ ký số từ xa MISA eSign để tích hợp trực tiếp vào MISA meInvoice để phát hành hóa đơn mà không cần cắm USB Token" — [meinvoice.vn/?p=7442](https://www.meinvoice.vn/?p=7442). meInvoice also "tích hợp miễn phí với tất cả các chữ ký số hợp lệ trên thị trường" — [meinvoice.vn](https://www.meinvoice.vn/tin-tuc/8854/chu-ky-so-dung-tren-phan-mem-hoa-don-dien-tu-misa-meinvoice/)
- [MISA official, search excerpt] A MISA article (AMIS Thuế TNCN context) says a frozen signing form can be caused by MISA KYSO installed on drive C hanging; the fix is to uninstall it and reinstall it on another drive — [meinvoice.vn/?p=37617](https://www.meinvoice.vn/?p=37617)

### Inferences
- The error messages are .NET Framework and Windows CryptoAPI or smart-card errors ("keyset", "smart card"). That points to KYSO, or the component it uses, being a .NET program that reads the Windows certificate store and the token's Windows driver (CSP/minidriver). Such components rarely work under Wine, so USB-token e-invoice signing on Linux should be treated as unsupported. The fallback is a Windows VM with USB passthrough.
- Remote signing (MISA eSign) and HSM signing take place on the server. If the KYSO note in section 2.8 is just left over from the USB-token instructions, issuing invoices from a Linux browser with MISA eSign should work. If KYSO really is required, for example for some local processing, Linux is blocked. Only a hands-on test (for example with a trial account) can settle this.
- A buyer who must sign with a USB token, such as on minutes (biên bản), also needs KYSO on Windows.

### Gaps
- I found no system-requirements page for meInvoice used on its own (browser or OS list). The AMIS Kế toán list is the closest official statement.
- MISA does not publish KYSO's supported Windows versions or prerequisites (.NET version, token driver).
- I did not find whether meInvoice used on its own supports any other local signer, such as a token vendor's browser plugin.

## 4. MISA eSign / MISA-CA: licence, certificate forms, how signing works, desktop software

### Takeaway
MISA has been a licensed public digital-signature CA, under the name MISA-CA, since its licence was handed over at NEAC (then part of Bộ Thông tin và Truyền thông) on 29/5/2019. Its current certification practice statement (CPS), version 1.7 of March 2026, operates under the 2023 Law on Electronic Transactions and Decree 23/2025/NĐ-CP, and names Bộ Khoa học và Công nghệ (NEAC – RootCA) as the competent authority.

MISA mainly sells remote-signing certificates:
- the keys are kept in an HSM;
- each signature is approved in the MISA eSign phone app with biometrics, a PIN or an OTP;
- documents are signed on the web at esignapp.misa.vn.

MISA has also issued "MISA eSign USB Token" certificates, which are managed with the Windows tool MISA Token Manager. Remote signing needs no desktop software, so it is the most Linux-friendly option.

### Cited Findings
- [MISA official, fetched] "Lễ trao giấy phép cung cấp dịch vụ chứng thực chữ ký số công cộng cho Công ty Cổ phần MISA" was held on 29/5/2019 at "Trung tâm Chứng thực điện tử Quốc gia, Bộ Thông tin và Truyền thông". The article is dated 13/02/2020 and gives no licence number or validity period — [meinvoice.vn](https://www.meinvoice.vn/tin-tuc/3506/misa-duoc-cap-phep-cung-cap-dich-vu-chu-ky-so/)
- [Press, fetched] Article dated 26/05/2020 — [giaoduc.net.vn](https://giaoduc.net.vn/misa-cam-ket-nhanh-chong-hoan-thien-giai-phap-misa-esign-post209684.gd):
  - On 21/5/2020 NEAC sent letter 216/NEAC-TĐPC asking MISA to stop providing remote-signing certification.
  - Background: NEAC's letter 190/NEAC-TĐPC of 7/5/2020 concerned mobile and remote signing, and MISA filed its technical documents on 12/5/2020.
  - MISA said launching early "khó tránh khỏi một số sơ suất về vấn đề pháp lý" and promised "MISA cam kết sẽ hoàn thiện giải pháp MISA ESIGN nhanh chóng đáp ứng đầy đủ các yêu cầu kỹ thuật theo quy định".
  - MISA told customers "Doanh nghiệp đã mua cứ yên tâm sử dụng cho đến khi có thông báo chính thức" and offered refunds on request.
- [Press, search excerpt] Báo Pháp Luật reported that NEAC said MISA-CA had issued 2,583 remote-signing certificates and asked MISA to stop this model. I could not confirm the article date (probably May 2020) — [doanhnhan.baophapluat.vn](https://doanhnhan.baophapluat.vn/hon-2500-khach-hang-dung-chu-ky-so-tu-xa-co-the-bi-dung-dich-vu-29824.html)
- [MISA official, fetched PDF; text extracted with pdftotext] CPS "Quy chế chứng thực – Dịch vụ chứng thực chữ ký số công cộng từ xa MISA-CA", "Phiên bản 1.7". The file title is "Tháng 03.2026 Quy chế chứng thực_remote signing_ver 1.7_Final", uploaded under /2026/04/ — [esign.misa.vn CPS v1.7](https://esign.misa.vn/wp-content/uploads/2026/04/MISA-CA_Quy-che-chung-thuc_remote-signing_ver-1.7-1.pdf):
  - Legal basis: it complies with "Luật Giao dịch điện tử ngày 22 tháng 6 năm 2023, Nghị định số 23/2025/NĐ-CP ngày 21 tháng 02 năm 2025 của Chính phủ quy định về chữ ký điện tử và dịch vụ tin cậy".
  - It follows RFC 3647 and Thông tư 16/2019/TT-BTTTT of 05/12/2019 on the "mô hình ký số trên thiết bị di động và ký số từ xa".
  - Authority: "Bộ Khoa học và công nghệ (Trung tâm Chứng thực điện tử quốc gia – RootCA) là cơ quan có thẩm quyền quyết định tính hợp pháp của Quy chế chứng thực này". Section 1.3.1, however, still describes NEAC as "trực thuộc Bộ Thông tin và Truyền thông", so the document is internally inconsistent.
  - Certificates are issued to individuals and organisations "thông qua thiết bị tạo chữ ký đảm bảo (QSCD)", with 2048- or 4096-bit keys. Key pairs are generated in an "HSM CP5", and the private key "sẽ lưu trong thiết bị phần cứng an toàn HSM".
  - Activating the private key: "việc kích hoạt khóa bí mật yêu cầu có tài khoản đăng nhập, mã PIN bảo vệ, sinh trắc học hoặc mã OTP gửi về số điện thoại, email của khách hàng". After 5 wrong username, password or OTP entries in a row, the Remote QSCD account is locked.
  - Registration and confirmation go through "ứng dụng mobile", including live face video.
  - It describes a pilot with RAR Center for the "Cổng ký số từ xa tập trung trên nền tảng định danh và xác thực điện tử VneID".
- [MISA official, fetched] "Cấp bù chứng thư số từ xa" (Cập nhật 05/10/2026) — [helpact.misa.vn](https://helpact.misa.vn/kb/cap-bu-chung-thu-so-tu-xa/):
  - Under Nghị định 23/2025/NĐ-CP, a subscriber certificate may last at most three years and may not outlive the MISA CA certificate, which expires on 03/12/2026. MISA therefore issues free replacement certificates so that signing continues until the end of the paid term.
  - Users get a notice through the MISA eSign app, email or Zalo. They tick "Tôi xác nhận thông tin CTS là chính xác và chịu trách nhiệm về thông tin này" and then "Nhập mã OTP".
  - No computer software is mentioned.
- [MISA official, fetched] "Compensate for MISA eSign USB Token digital certificate" (undated, © 1994–2026) — [esign.misa.vn/?p=10545](https://esign.misa.vn/?p=10545):
  - A free MISA CA programme extends USB-token certificates whose term shows "November 20, 2024".
  - Steps: "Download and install the latest MISA Token Manager" (misa_tokenmanager_setup.exe), keep the token plugged in with a stable network connection, and confirm the certificate details in MISA Token Manager.
  - The new certificate must then be registered again on public systems: Tax, BHXH, Customs, State Treasury, the National Public Service Portal, National Bidding, the National Single Window and Business Registration.
- [MISA official, search-result title] A purchase agreement for USB tokens, "ThoaThuanMuaHang_eSign_USB_Token.pdf", exists — [personalagreement.misa.vn](https://personalagreement.misa.vn/files/terms-of-purchase/293afadb-0ba4-4603-852d-79cbcfac2268/vi/ThoaThuanMuaHang_eSign_USB_Token.pdf)
- [MISA official, fetched] Web signing at esignapp.misa.vn: the user uploads the file, places the signature and confirms in the app within 60 seconds. Accepted formats are PDF, Word, Excel, PowerPoint, JPG and PNG — [helpact.misa.vn/?p=78269](https://helpact.misa.vn/?p=78269)
- [MISA official, fetched] The phone app needs Android 5.0+ or iOS 11+. Devices are registered with an OTP and use biometrics (or a PIN on Android) — [helpact.misa.vn](https://helpact.misa.vn/kb/ky-so-hoa-don-dien-tu-tu-xa-voi-misa-esign/)
- [App Store, search excerpt] The MISA eSign iOS app is "Designed for iPad". On a Mac it needs macOS 11.0 or later and an Apple M1 chip or later, i.e. the iPad app running on Apple Silicon. One review complains of "không tìm thấy chứng thư số" — [App Store](https://apps.apple.com/vn/app/misa-esign/id1586580978)
- [MISA official, search excerpt] "Tính năng ký phiên được thiết lập bắt buộc phải thực hiện ở app MISA eSign trên điện thoại", meaning session signing must be set up in the phone app — [helpact.misa.vn](https://helpact.misa.vn/kb/thiet-lap-tinh-nang-ky-phien-tren-ung-dung-chu-ky-so-misa-esign/)
- [Press, search excerpt] On 15/6/2023 the Cục Thương mại điện tử và Kinh tế số of Bộ Công Thương gave MISA a registration certificate for electronic-contract certification services. This is separate from the CA licence — [doanhnhan.baophapluat.vn](https://doanhnhan.baophapluat.vn/bo-cong-thuong-trao-giay-xac-nhan-cung-cap-dich-vu-chung-thuc-hop-dong-dien-tu-cho-misa-52119.html)

### Inferences
- The CPS replacing Bộ TT&TT with Bộ Khoa học và Công nghệ fits the 2025 merger of the two ministries (background knowledge, not sourced in this research). NEAC is still the RootCA.
- MISA eSign remote signing is the strongest option for Linux desktops. The key stays in MISA's HSM, approval happens on a phone, and documents are signed in a web app, so no desktop software is required. The one open question is the KYSO note in the e-invoice guide (see section 3).
- The MISA eSign USB Token needs MISA Token Manager (.exe), at least to renew or manage certificates. Whether the token can sign on Linux through a standard PKCS#11 driver (OpenSC or the vendor's) depends on the token hardware, which MISA does not name. This is speculative.
- The MISA CA certificate expires on 03/12/2026, about a month after this research. Remote-signing users must accept the replacement certificate in the app, and systems that registered the old certificate (tax, BHXH) may need it registered again. This affects every OS, not only Linux.

### Gaps
- I did not find MISA-CA's licence number, its validity period, or whether it was renewed or re-licensed under Decree 23/2025. CPS v1.7 shows the service is still operating but cites no licence number.
- MISA does not say what hardware or vendor is behind the "MISA eSign USB Token", or whether MISA Token Manager exists for macOS or Linux. A search for "MISA Token Manager" macOS found nothing.
- Unclear whether MISA-CA still sells new USB-token certificates in 2026, because CPS v1.7 covers only remote signing.
- I found no document saying that NEAC's 2020 stop request was formally lifted. The later CPS versions and continued sales suggest it was resolved.

## 5. MISA mTax, AMIS BHXH and bank connections: what they need locally

### Takeaway
- **mTax** (filing tax returns from AMIS Kế toán) needs MISA KYSO with a USB token, but MISA says it needs no tool at all with MISA eSign.
- **AMIS BHXH** (social insurance filings) supports USB tokens, MISA eSign and VNPT SmartCA remote signing; MISA does not document what local tool the USB route uses.
- **Bank connections** in AMIS run between MISA's servers and the banks, partly through JetPay BankHub. MISA documents no local software for them.

### Cited Findings
- [MISA official, fetched] "Nộp tờ khai thuế trực tuyến qua mTax" (Cập nhật 05/08/2026) — [helpact.misa.vn](https://helpact.misa.vn/kb/nop-to-khai-thue-truc-tuyen-qua-mtax/):
  - USB token: "Cần phải cài đặt công cụ ký số MISA KYSO phiên bản mới nhất".
  - MISA eSign: "Không cần cài đặt thêm bất kỳ công cụ nào."
  - Before filing, the business must stop using other e-tax service providers and register for MISA's. mTax cannot be used alongside the tax authority's Thuế điện tử or Dịch vụ công.
  - Steps: Thuế > Khai thuế > Kết nối MISA MTAX, enter the mTax account, then "Nộp tờ khai" or "Nộp tờ khai qua MTAX".
  - No OS or browser requirements are given.
- [MISA official, search excerpt, old] Older MTAX.VN guidance (around 2013–2016) said "Bạn cũng cần cài chương trình Java Plugin để có thể nộp tờ khai qua mtax.vn". The current guide above replaces it — [sme.misa.vn/19746](https://sme.misa.vn/19746/nhung-dieu-can-biet-ve-dich-vu-khai-thue-qua-mang-mtax-vn-cua-misa/)
- [MISA official, fetched] The AMIS BHXH feature page lists signing with USB Token, with "chữ ký số từ xa MISA eSign", and says "AMIS BHXH đã kết nối thành công Chữ ký số từ xa VNPT SmartCA". It also describes tools that suggest entries for forms 600, 601 and 605 (registering, deregistering and changing job titles). It names no local tool and no OS or browser requirements; the only date visible is 10/09/2024 — [amis.misa.vn](https://amis.misa.vn/tinh-nang-moi-san-pham/tinh-nang-amis-bhxh/)
- [MISA official, search-result title] "[AMIS BHXH] KÝ SỐ BẰNG CHỮ KÝ SỐ TỪ XA VNPT SmartCA" (not opened) — [amis.misa.vn/158677](https://amis.misa.vn/158677/amis-bhxh-ky-so-bang-chu-ky-so-tu-xa-vnpt-smartca/)
- [Third-party, search excerpt; another vendor's BHXH software, not MISA] For BHXH e-filing with a USB token, the token driver must be fully installed and the PIN entered. A browser signing plugin is needed when signing in the browser — [ebh.vn](https://ebh.vn/bao-hiem-xa-hoi-dien-tu/huong-dan-chi-tiet-cach-ke-khai-bao-hiem-xa-hoi-nhanh-nhat)
- [MISA official, fetched] "Ngân hàng điện tử" (Cập nhật 09/09/2026) — [helpact.misa.vn](https://helpact.misa.vn/kb/ngan-hang-dien-tu/):
  - Banks supporting payment orders, balances and history ("Quản lý chi và thông tin tài khoản"): VietinBank, Vietcombank, Techcombank, BIDV, MB, SHB, MSB, OCB, ACB, TPBank, VPBank.
  - Banks supporting only balance-change notifications: Sacombank, BIDV, PVcomBank, LPBank, MSB, VietinBank, Vietcombank, MB, ACB, TPBank, VPBank. These "chỉ hỗ trợ nhận biến động số dư, không hỗ trợ lập lệnh chi tiền".
  - Users "Lập và phê duyệt lệnh chuyển tiền trực tuyến sau khi đã kết nối ngân hàng".
  - JetPay BankHub is referenced; the OCB guide is hosted on help.jetpay.vn.
  - The page names no software or plugin to install, no approval mechanism, and no OS or browser.
- [MISA official, search excerpt] A Vietcombank connection needs a Vietcombank DigiBiz account linked to JetPay BankHub. VPBank needs JetPay BankHub registered on VPBank NeoBiz — [Vietcombank guide](https://helpact.misa.vn/kb/ket_noi_voi_ngan_hang_dien_tu_vietcombank/); [VPBank guide](https://helpact.misa.vn/kb/ket-noi-ngan-hang-dien-tu-vpbank/)

### Inferences
- mTax with MISA eSign and the bank connections work between servers, so they should work from a Linux browser. mTax with a USB token goes through KYSO, which is Windows-only.
- Payment orders are probably authorised by the bank's own method (OTP or the bank's app in DigiBiz or NeoBiz) rather than a MISA tool. This is unconfirmed.
- AMIS BHXH probably uses MISA KYSO for USB-token signing, as other AMIS modules do. This is unconfirmed. Remote signing with MISA eSign or VNPT SmartCA avoids local software.

### Gaps
- AMIS BHXH: I did not find how USB-token signing is done locally (KYSO or another tool) or how it connects to the BHXH system (I-VAN details).
- I did not find requirements for the standalone MISA mTax web app (outside AMIS).
- None of the MISA pages I read describe how payment orders are approved (OTP, bank token or digital signature).

## 6. MISA documentation that mentions Linux, Ubuntu or macOS

### Takeaway
No MISA page I found mentions Linux or Ubuntu. macOS appears only for the browser-based AMIS Kế toán and, indirectly, for the iPad version of MISA eSign running on Apple Silicon Macs. Every local MISA component I found is a Windows .exe with Windows-only instructions: SME, MISA KYSO, the AMIS print tool and MISA Token Manager. I found no user reports of MISA products being used on Linux, either in the browser or under Wine.

### Cited Findings
- [MISA official, fetched] AMIS Kế toán lists "Win 7, Mac OS" as the minimum OS — [helpact.misa.vn](https://helpact.misa.vn/kb/cau-hinh-may-tinh-de-su-dung-phan-mem-amis-ke-toan/). It runs on "máy tính WINDOW, MACBOOK, máy tính bảng mà không cần cài đặt" — [helpact.misa.vn](https://helpact.misa.vn/kb/phan-mem-amis-ke-toan-co-su-dung-duoc-tren-macbook-ipad-may-tinh-bang-khong/)
- [MISA official, fetched/search] The AMIS Kế toán help centre has tags for "macbook", "ios", "ipad" and "android", but none for Linux in the results. The macbook tag lists only the article above — [helpact.misa.vn tag macbook](https://helpact.misa.vn/article-tags/macbook/)
- [MISA official] The local components are all Windows-only:
  - MISA.KySo_Setup_latest.exe — [Thiết lập ký số](https://helpact.misa.vn/kb/thiet_lap_ky_so/) (fetched)
  - misa_tokenmanager_setup.exe — [esign.misa.vn/?p=10545](https://esign.misa.vn/?p=10545) (fetched)
  - SME's OS list, which contains only Windows — [sme.misa.vn/download](https://sme.misa.vn/download/) (fetched)
  - the .exe print tool — [helpact.misa.vn](https://helpact.misa.vn/kb/bo-sung-trinh-in-bao-cao-tren-amis-ke-toan/) (search excerpt)
- [App Store, search excerpt] On a Mac, MISA eSign runs only as the iPad app on Apple Silicon (macOS 11+, M1+) — [App Store](https://apps.apple.com/us/app/misa-esign/id1586580978)
- [User report, search excerpt] In a voz.vn thread asking for advice on a MISA server, the asker wanted a Linux server without a GUI. The excerpt shows no answer about running MISA on Linux — [voz.vn thread 735475](https://voz.vn/t/can-tu-van-may-chu-misa.735475/)

### Inferences
- The only OS-independent route MISA supports is AMIS (in the browser) plus MISA eSign remote signing (on a phone). For CaramOS this means:
  - make Chrome and Firefox (and possibly Cốc Cốc) work well, with Vietnamese fonts and good PDF and Excel handling;
  - push MISA eSign or an HSM for signing;
  - document a Windows VM (virt-manager or GNOME Boxes with USB passthrough) or RDP route for SME and for USB-token signing through KYSO.
- A Linux-native signer compatible with KYSO would mean reverse-engineering MISA's undocumented link between the browser and KYSO. That brings support and possibly legal risks (speculative).

### Gaps
- MISA makes no statement about Linux at all, neither "supported" nor "unsupported". Only MISA support can answer this.
- I found no tests or reports of AMIS, meInvoice or esignapp in Linux browsers, for example whether a user-agent check blocks Linux.
- I found no Wine or Proton reports for SME, MISA KYSO or MISA Token Manager. The voz.vn and tinhte.vn results found nothing relevant.
