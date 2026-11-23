# Vietnamese government and business e-services that need a digital signature: client software and Linux support (state as of 2026-11-05)

Source labels used below:
- **[Official]**: a document from a government agency or bank.
- **[Vendor]**: a help page from a CA (certificate authority) or software vendor (MISA, FastCA, Thái Sơn and others). These are the main practical source, because the official tax portal could not be read directly.
- **[Legal commentary]**: a law firm or legal database article.
- **[News]**: press coverage.
- **(excerpt)**: the claim comes from a search-result excerpt and the page was not opened. Treat it as lower confidence.

Research limits:
- thuedientu.gdt.gov.vn returned an error page ("Can't find the channel handler for deviceType…") to the fetch tool instead of its content ([portal](https://thuedientu.gdt.gov.vn/etaxnnt/Request)).
- Several thuvienphapluat.vn pages, extensionauditor.com and the Chrome Web Store listing did not load (403 errors or an empty render).
- Nothing was logged into, downloaded to run, or installed. Three public PDFs that the fetch tool had saved were read as text only.

## Key Question 1: Which services still need a Windows-only component today, and which work in any modern browser with remote signing or a mobile app?

### Takeaway
As of late 2026, a business's core recurring filings still depend on Windows-only client components:
- tax returns, through TCT SigningHub (needs .NET Framework 4.8/4.8.1), eSigner (Java) and the HTKK desktop app (needs .NET 3.5);
- BHXH declarations, through a Windows .exe "ứng dụng nền" plus a Chrome extension;
- customs declarations, through Windows desktop software such as Thái Sơn's ECUS5-VNACCS (the Windows part here is inferred).

Plugin-free paths do exist, but they are partial:
- Remote signing is accepted for tax returns on dichvucong.gdt.gov.vn, but not for signing attached files.
- The official BHXH flow ends in remote signing confirmed on a phone, yet the same guide still says the computer must have BHXH's signing tool installed.
- E-invoice providers offer HSM (server-side key storage) or remote signing.
- Banks are moving approvals to mobile apps: Techcombank's in-app FPT-CA signature, VCB DigiBiz Smart OTP, BIDV Direct SmartOTP.
- Logins to government portals are moving from organisation certificates to VNeID organisation accounts, which are managed in a phone app.

### Cited Findings

#### A. Tax e-filing (Cục Thuế, Ministry of Finance)

**Who runs it, and the 2025 changes**
- The tax authority now issues its notices as "Cục Thuế", for example "Ngày 03/8/2025 Cục thuế đã phát hành phần mềm HTKK 5.4.0" — [Thư viện Pháp luật](https://thuvienphapluat.vn/hoi-dap-phap-luat/huong-dan-cai-dat-phan-mem-htkk-540-chi-tiet-ra-sao-138059102.html) (excerpt).
- The e-tax systems were paused to upgrade them and convert the tax authority's code lists for the reorganisation: 12–17 March 2025 — [Thị trường Tài chính Tiền tệ](https://thitruongtaichinhtiente.vn/tam-dung-cac-he-thong-thue-dien-tu-de-nang-cap-va-chuyen-doi-cac-danh-muc-cua-co-quan-thue-66254.html) [News] (excerpt); same topic in [Đắk Lắk police PDF, 2025-03](https://congan.daklak.gov.vn/uploads/news/2025_03/nang-cap-he-thong-cntt-va-cap-nhat-danh-muc-phuc-vu-sap-xep-to-chucbo-may-cua-co-quan-thue.pdf) (title only).
- Excerpts also report that eTax, iCanhan (canhan.gdt.gov.vn) and eTax Mobile were paused from 18:00 on 27/6/2025 to 08:00 on 01/07/2025 — [hethongphapluat](https://hethongphapluat.com/phap-luat/chinh-sach-phap-luat/ke-toan-can-biet-hang-loat-thay-doi-nong-ve-thue-va-dinh-danh-dien-tu-tu-thang-72025.html) / [Thanh Tra](https://thanhtra.com.vn/tai-chinh-701717FFD/he-thong-thue-dien-tu-chinh-thuc-hoat-dong-tro-lai-tu-sang-nay-6a62520eb.html) (excerpt; which of the two said it is uncertain).

**The new tax public-service portal, dichvucong.gdt.gov.vn**
- Returns filed on thuedientu.gdt.gov.vn "sau ngày 01/07/2025" appear in the lookup on the new DVC portal. Earlier returns stay in the old e-tax lookup — [MISA help FAQ, updated 29/10/2026](https://helpact.misa.vn/?p=73319) [Vendor].
- Login is with a VNeID electronic-identity account or an e-tax account, choosing individual or business. One guide is headed "Đăng nhập Cổng DVC về thuế thay thế hệ thống Thuế điện tử" — [Kế toán An Phá](https://ketoananpha.vn/cach-dang-nhap-dich-vu-cong-thue-nha-nuoc.html) (excerpt).
- Conflict: another excerpt says thuedientu.gdt.gov.vn "remains active for returns and payments". VNeID users can be redirected to the e-tax site and must "Thực hiện đăng nhập tiếp ở trang thuế điện tử" — [MISA FAQ](https://helpact.misa.vn/?p=73319). The two systems appear to run side by side.
- What a business signs there: tax returns ("ký tờ khai trên trang dichvucong.gdt.gov.vn") — [MISA help, updated 21/01/2026](https://helpact.misa.vn/?p=73747) [Vendor]. Also attachments, supplementary returns and tax payments ([MISA: nộp tiền thuế trên DVC](https://helpact.misa.vn/?p=73793), [MISA: tờ khai bổ sung](https://helpact.misa.vn/?p=73789); titles only).

**Client requirements on dichvucong.gdt.gov.vn**
- **TCT SigningHub.** Installed from file "CKS_Client", after the user logs in, from the portal's "Trợ giúp" section. It needs .NET Framework installed first: "Chọn phiên bản 4.8 đối với máy sử dụng Windows 10" / "4.8.1 đối với máy sử dụng Windows 11" — [FastCA guide, 27/01/2026](https://fastca.vn/huong-dan-cai-dat-cau-hinh-chu-ky-so-tren-dich-vu-cong) [Vendor].
  - Its processes are "ctSignerv2" and "nSignerv2 (32bit)", and "Windows 7 / 8.1 chỉ hỗ trợ The .NET Framework 4.8" — [MISA FAQ 29/10/2026](https://helpact.misa.vn/?p=73319).
- **eSigner.** Installer "eSigner_setup". It is Java-based and needs Java 8 — [MISA FAQ](https://helpact.misa.vn/?p=73319).
  - After installing it, the taskbar shows "biểu tượng HĐĐT plugin và eSigner", so the e-invoice (HĐĐT) plugin comes with it — [MISA help 21/01/2026](https://helpact.misa.vn/?p=73747).
  - MISA also gives a second download host, igovmedia.lamdongtructuyen.vn — [same page](https://helpact.misa.vn/?p=73747).
- **iTaxViewer.** Used to check the XML of returns. On errors, users are told to reinstall "Esigner và Itaxview bản mới nhất" from the Help menu — [MISA FAQ](https://helpact.misa.vn/?p=73319).
- **Common error:** "Chưa cài đặt hoặc bật Plugin chữ ký số" — [MISA FAQ](https://helpact.misa.vn/?p=73319).
- **OS:** None of these guides mentions macOS or Linux. The only installers documented are Windows ones — [FastCA](https://fastca.vn/huong-dan-cai-dat-cau-hinh-chu-ky-so-tren-dich-vu-cong), [MISA](https://helpact.misa.vn/?p=73747).

**Client requirements on thuedientu.gdt.gov.vn (older eTax)**
- eSigner is downloaded from "thuedientu.gdt.gov.vn/etaxnnt/Request" → "[Phần mềm hỗ trợ ký điện tử eSigner]" — [Thư viện Pháp luật](https://thuvienphapluat.vn/ma-so-thue/phap-luat-thue/huong-dan-tai-va-cai-dat-phan-mem-esigner-ky-dien-tu-moi-nhat-cua-tong-cuc-thue-537983-200582.html) (excerpt).
- A troubleshooting guide tells users to "Install the latest version of eSigner Java … Uninstall and install the ESigner.Chrome.TCT extension" — [Mytour](https://mytour.vn/en/blog/bai-viet/quick-and-effective-solutions-for-fixing-errors-on-thuedientugdtgovvn.html) (excerpt).
- The e-tax site needs its own plugin, separate from the plugin of the user's CA — [Sapo](https://www.sapo.vn/blog/cai-dat-plugin-chu-ky-so) (excerpt).
- Unverified: a scanner page titled "Security Alert: Confirmed Malware" lists an "esigner-chrome-tct" extension with ID mbggglkgpncleglnljblhdajnekddmdb as no longer available — [Extension Auditor](https://www.extensionauditor.com/scan/esigner-chrome-tct-mbggglkgpncleglnljblhdajnekddmdb) (excerpt; the page returned 403 when fetched; no other source confirms it).

**HTKK (Hỗ trợ kê khai) desktop software**
- Requirements: .NET Framework 3.5. On Windows 8/10 it is enabled through "Turn Windows features on or off", or offline with "Install .NET Framework 3.5 via DISM.cmd". The first run must be done by an admin user — [Thư viện Pháp luật, HTKK 5.4.0](https://thuvienphapluat.vn/hoi-dap-phap-luat/huong-dan-cai-dat-phan-mem-htkk-540-chi-tiet-ra-sao-138059102.html) (excerpt) and an [install-guide PDF](https://cdn.thuvienphapluat.vn/phap-luat/2022-2/HQ/huongdan-caidat.pdf) (excerpt).
- Windows 11 ships .NET 4.8, but 3.5 must be added separately — [Microsoft Learn](https://learn.microsoft.com/vi-vn/dotnet/framework/install/on-windows-11) [Official].
- Release pace in 2026 (it is updated whenever forms or rules change):
  - 5.6.5 on 01/04/2026, for Thông tư 21/2026/TT-BTC — [Thư viện Pháp luật](https://thuvienphapluat.vn/banan/tin-tuc/thong-bao-nang-cap-phan-mem-htkk-phien-ban-565-moi-nhat-ngay-01042026-cua-cuc-thue-ra-sao-20974.html) (title);
  - 5.7.1, replacing 5.7.0, for Thông tư 50/2026/TT-BTC — [Thư viện Pháp luật](https://thuvienphapluat.vn/phap-luat/ho-tro-phap-luat/tai-phan-mem-htkk-571-moi-nhat-thay-the-htkk-570-dap-ung-thong-tu-502026ttbtc-link-tai-phan-mem-htk-273553.html) (title);
  - 5.7.2 on 10/07/2026 — [MISA AMIS](https://amis.misa.vn/61453/phan-mem-ho-tro-ke-khai-thue-htkk/) (title and excerpt).
- After a return is prepared, HTKK shows "Ký tệp tờ khai thành công" and the user then clicks "Nộp tờ khai" — [einvoice.vn](https://einvoice.vn/tin-tuc/huong-dan-ke-khai-thue-bang-hoa-don-dien-tu) (excerpt).

**Remote signing and mobile alternatives for tax**
- Remote signing is accepted for filing returns on the DVC tax portal. The provider named is "Chữ ký số từ xa Misa eSign".
- But "Cổng dịch vụ công chưa hỗ trợ ký hồ sơ đính kèm bằng chữ ký số từ xa", so attached files still need a USB token — [MISA FAQ 29/10/2026](https://helpact.misa.vn/?p=73319) [Vendor].
- VNPT says one SmartCA remote signature can sign "các tờ khai thuế, khai báo hải quan" across public-service portals, and its eSign gateway handled more than 43 million signing calls in 2025 — [Báo Pháp luật](https://baophapluat.vn/go-diem-nghen-cho-ky-voi-vnpt-smartca.html) [News/Vendor PR] (excerpt).
- A 2022 article says SmartCA was integrated with "iHTKK và hệ thống iTax mobile" and signs "ngay trên các thiết bị di động" without a USB token — [VNBA, 23/02/2022](https://vnba.org.vn/vi/de-dang-thuc-hien-dich-vu-cong-truc-tuyen-voi-giai-phap-ky-so-tu-xa-smartca-4305.htm) [News].
- eTax Mobile is aimed at individuals and household businesses (hộ kinh doanh). Household businesses could practise registering, declaring and paying in the app before 1/1/2026 — [Nhà Đầu Tư](https://nhadautu.vn/ho-kinh-doanh-co-the-trai-nghiem-ke-khai-thue-tren-app-etax-mobile-d101585.html), [VCCI](https://www.vcci.com.vn/tin-tuc/huong-dan-cach-ke-khai-thue-tren-app-etax-mobile-cho-ho-kinh-doanh) [News].
- Presumptive tax (thuế khoán) for household businesses was abolished, with self-declaration from 1/1/2026 — [VnEconomy](https://vneconomy.vn/cuc-thue-mo-giai-doan-thu-nghiem-thuc-hanh-cho-ho-kinh-doanh-sau-khi-xoa-bo-thue-khoan.htm) [News].
- No source was found showing that companies (doanh nghiệp) can file their returns in eTax Mobile.

#### B. E-invoices (Nghị định 123/2020, 70/2025; Thông tư 78/2021, 32/2025)

**Legal framework**
- Nghị định 70/2025/NĐ-CP was issued 20/03/2025 and took effect 01/06/2025. It amends Nghị định 123/2020 — [MISA meInvoice](https://www.meinvoice.vn/tin-tuc/31439/nghi-dinh-70-2025-nd-cp-sua-doi-nghi-dinh-123/) (excerpt); also [PwC](https://www.pwc.com/vn/vn/publications/2025/250416-changes-to-invoicing-regulations.pdf) and [EY](https://www.ey.com/content/dam/ey-unified-site/ey-com/vi-vn/technical/tax/documents/tax-alert-april-changes-to-invoicing-regulations-june.pdf) alerts (not opened).
- Thông tư 32/2025/TT-BTC was signed 31/5/2025. It replaces Thông tư 78/2021 and took effect 01/6/2025 (Article 12) — [LSVN](https://lsvn.vn/nhung-noi-dung-moi-tai-thong-tu-so-32-2025-tt-btc-ve-hoa-don-chung-tu-a158872.html) [Legal commentary] (excerpt); Thông tư 78 lapsed on 01/6/2025 — [einvoice.vn](https://einvoice.vn/tin-tuc/tong-hop-nhung-van-ban-phap-ly-ve-hoa-don-dien-tu-con-hieu-luc-2025-doanh-nghiep-can-nam-ro) (excerpt).
- Conflict: one AMIS article reportedly gives 01/07/2025 as the effective date — [MISA AMIS](https://amis.misa.vn/226143/tong-hop-6-diem-moi-cua-thong-tu-32-2025-tt-btc/) (excerpt; attribution uncertain).

**What must be signed**
- Under Nghị định 123, Article 12(2), the e-invoice format has two components: business data and digital-signature data.
- Under Article 18(2), sellers who issue e-invoices with software must sign them and send them to the buyer electronically.
- Nghị định 70 (Art. 1, items 7–8, amending Art. 10(14) and Art. 11) lists cases that need no signature:
  - the buyer's signature is not required on sales of goods and services, including to overseas customers;
  - tax-authority invoices issued per transaction need neither the seller's nor the buyer's signature;
  - supermarkets and fuel sales to non-business individuals need no buyer signature;
  - e-tickets, stamps and cards need no seller signature;
  - certain airline documents are exempt;
  - "cash-register invoices connected to tax authority data transfer" have no mandatory digital signature.
- The new signing-time rule: for invoices with a tax-authority code, the signing time and the time the invoice is sent for its code apply; for invoices without a code, the time the data is transmitted applies. Either way the deadline is no later than the next working day after issuance — [einvoice.vn (Thái Sơn), 29/04/2025](https://einvoice.vn/tin-tuc/hoa-don-dien-tu-co-bat-buoc-ky-so-theo-nghi-dinh-70-2025-nd-cp) [Vendor; it misprints one citation as "70/2023"].
- Inference: ordinary B2B VAT invoices still carry the seller's digital signature.

**hoadondientu.gdt.gov.vn (the tax authority's e-invoice portal)**
- Its signing plugin ("HĐĐT plugin") is installed together with eSigner — [MISA help](https://helpact.misa.vn/?p=73747).
- An excerpt says the e-invoice plugin is separate from the plugin used by other tax software — [Sapo / Thư viện Pháp luật results](https://www.sapo.vn/blog/cai-dat-plugin-chu-ky-so) (excerpt).

**Providers' signing paths**
- **MISA meInvoice.** Signing can use a USB token (through the "MISA KYSO" tool: "Nếu … chưa cài công cụ MISA KYSO, nhấn Tải về MISA KYSO"), a MISA eSign remote certificate, or an HSM — [MISA help](https://helpact.misa.vn/?p=75693) (excerpt).
  - MISA eSign offers both a USB token and remote signing — [meInvoice](https://www.meinvoice.vn/tin-tuc/14784/chu-ky-so-misa-esign/).
  - The meInvoice iOS app runs on Macs with macOS 11+ and Apple M1 or later — [App Store](https://apps.apple.com/app/id1460947129).
- **Viettel SInvoice.** The certificate can be set up as "HSM" or "USB-TOKEN" (CloudCA is mentioned) — [Odoo Vietnam localisation docs](https://www.odoo.com/documentation/18.0/applications/finance/fiscal_localizations/vietnam.html) (excerpt).
  - Viettel's remote-signing app is MySign — [App Store](https://apps.apple.com/mx/app/mysign/id1633019232); [Lao Động](https://news.laodong.vn/kinh-doanh/le-tao-khoa-chung-thu-so-viettel-mysign-cung-co-nen-tang-tin-cay-cho-giao-dich-so-1671704.ldo).
- **VNPT Invoice.** Named as integrated with SmartCA remote signing — [VNBA 2022](https://vnba.org.vn/vi/de-dang-thuc-hien-dich-vu-cong-truc-tuyen-voi-giai-phap-ky-so-tu-xa-smartca-4305.htm).
- **Thái Sơn E-invoice** (einvoice.vn): no signing-tool details found.
- BKAV eHoadon and EasyInvoice were not covered; see Gaps.

#### C. Social insurance e-declaration (BHXH Việt Nam)

**The official BHXH guide (PL02, undated; for the QĐ 422/QĐ-TTg one-time-benefit service)** — [BHXH PL02 PDF](https://baohiemxahoi.gov.vn/content/tintuc/Lists/News/Attachments/21626/PL02.%20H%C6%B0%E1%BB%9Bng%20d%E1%BA%ABn%20quy%20tr%C3%ACnh%20h%C6%B0%E1%BB%9Fng%20BHXH%20m%E1%BB%99t%20l%E1%BA%A7n.pdf) [Official]
- Step 1: download the "công cụ hỗ trợ ký số" from dichvucong.baohiemxahoi.gov.vn, section "Tải ứng dụng/Đăng ký & Kê khai", choosing "một trong 2 lựa chọn" (the two options are only shown in screenshots).
- Then run an installer wizard (Tiếp tục → Cài đặt → Kết thúc).
- "người tham gia phải có chữ ký số cá nhân và máy tính được cài đặt công cụ hỗ trợ ký số do BHXH Việt Nam cung cấp".
- The signing step: "Chọn Tổ chức cung cấp dịch vụ chứng thực chữ ký số và nhập thông tin tài khoản ký số từ xa", then "xác thực ký số trên thiết bị di động … (Remote Signing)".
- dichvucong.gov.vn redirects to the BHXH portal for this service.

**Client stack for organisations' registration and declarations** — [FastCA, 09/08/2023](https://fastca.vn/cai-dat-extension-ung-dung-nen-ky-so-dang-ky-ke-khaibhxh) [Vendor]
- A Chrome Web Store extension, "Vietnam Social Security Internal". Users must turn on all of its site-access toggles.
- Plus a background app: a ".exe" from "Tải ứng dụng nền cho ký số đăng ký và kê khai".
- Requirements: "Window 7 trở lên"; "Sử dụng trình duyệt web Google Chrome hoặc Cốc cốc".
- Store ID mneoaladmefdboobnffehgmbpokioffh — [Chrome Web Store](https://chromewebstore.google.com/detail/vietnam-social-security-i/mneoaladmefdboobnffehgmbpokioffh) (the listing did not render; the excerpt gives support hotline 19009068 ext. 3).

**I-VAN providers**
- **ebh.vn (Thái Sơn I-VAN, "Dịch vụ I-VAN THAISONSOFT").** The same Chrome "Extension ký số" plus "ứng dụng nền". A colleague can prepare the file and send it to the token holder, who signs it in the "EBH-Sign" desktop app ("phần mềm trình ký đã được cài đặt trên máy tính"). The token is still required — [ebh.vn, 09/08/2023](https://ebh.vn/nghiep-vu-phan-mem/khong-cam-chu-ky-so-co-the-khai-bhxh-qua-mang-duoc-khong) [Vendor].
- **EFY-eBHXH** has both desktop and web versions — [baohiemxahoidientu.vn](https://baohiemxahoidientu.vn/bhxh/so-sanh-2-phien-ban-desktop-va-website-cua-phan-mem-ke-khai-bhxh-dien-tu-ebhxh.html) (title).
- **MISA AMIS BHXH** documents signing with VNPT SmartCA remote signing — [MISA AMIS](https://amis.misa.vn/?p=158677) (title).
- xCyber Care is another provider — [xCyber](https://xcyber.vn/mien-phi-6-thang-su-dung-phan-mem-bhxh-dien-tu-xcyber-care/) (title).
- A vendor article says businesses can use either a provider's software or "phần mềm miễn phí của BHXH Việt Nam" — [MISA AMIS](https://amis.misa.vn/29024/phan-mem-ke-khai-bao-hiem-xa-hoi-mien-phi/) (excerpt). BHXH's own declaration software was not verified; see Gaps.

#### D. Customs (Cục Hải quan, Ministry of Finance)

**Systems**
- VNACCS/VCIS is the main clearance system.
- "Hệ thống thông quan điện tử phiên bản 6 (Ecus6)" is the customs authority's own backup clearance system for VNACCS/VCIS. It was officially deployed from 25/3/2025 — [Công văn 6324/CHQ-GSQL 2025 on Thư viện Pháp luật](https://thuvienphapluat.vn/cong-van/Xuat-nhap-khau/Cong-van-6324-CHQ-GSQL-2025-thu-tuc-hai-quan-he-thong-thong-quan-dien-tu-phien-ban-6-Ecus6-658734.aspx) (excerpt).
- Ecus6 moved to a cloud environment on 14/12/2025. "Đối với doanh nghiệp, địa chỉ kết nối không thay đổi" — [Tạp chí Kinh tế Tài chính, 13/12/2025](https://thuehaiquan.tapchikinhtetaichinh.vn/hai-quan-chuyen-doi-he-thong-thong-quan-dien-tu-ecus6-sang-moi-truong-dien-toan-dam-may-130837.html) [News].
- Businesses submit to Ecus6 at https://tqdtv6.customs.gov.vn. They may use free declaration software from Customs or third-party software — [Thư viện Pháp luật Ecus6 guide](https://thuvienphapluat.vn/ma-so-thue/phap-luat-thue/huong-dan-khai-hai-quan-tren-he-thong-ecus6-moi-nhat-2026-945658-224042.html) (excerpt).
- Naming caution: the customs system "Ecus6" is not Thái Sơn's ECUS product.

**Declaration software**
- Thái Sơn's ECUS5-VNACCS is a desktop client backed by SQL Server Express. A common error is "Database size exceeds the limit of 10240 MB for SQL Server Express Edition" — [BKNS](https://www.bkns.vn/?p=83129) (excerpt).
- VNPT markets SmartCA remote signing for "khai báo hải quan" — [Báo Pháp luật](https://baophapluat.vn/go-diem-nghen-cho-ky-voi-vnpt-smartca.html) (excerpt). No customs page confirming remote signing was found.

#### E. National public service portal, business registration, VNeID organisation accounts

**VNeID organisation accounts**
- Under Nghị định 69/2024/NĐ-CP, from 01/7/2025 all businesses must register an electronic-identity account (VNeID) for administrative procedures. Applying the rule for organisations "vẫn chưa được thực hiện một cách thống nhất".
- From 01/6/2026, all online immigration procedures must go through the organisation's VNeID account, and "việc sử dụng song song chứng thư số/chữ ký số của tổ chức để đăng nhập vào Cổng Dịch vụ công quốc gia … đã không còn được chấp nhận" — [KPMG Vietnam alert, June 2026](https://assets.kpmg.com/content/dam/kpmgsites/vn/pdf/2026/06/immigration-alert-on-organizational-vneid-vi.pdf.coredownload.inline.pdf) [Professional adviser].
- Another source says that from 01/07/2025 organisations must use VNeID to access the national portal (DVCQG) and eTax — [hethongphapluat](https://hethongphapluat.com/phap-luat/chinh-sach-phap-luat/ke-toan-can-biet-hang-loat-thay-doi-nong-ve-thue-va-dinh-danh-dien-tu-tu-thang-72025.html) (excerpt).
- Conflict: a LuatVietnam article calls organisation e-identity "không bắt buộc" but advisable — [LuatVietnam](https://luatvietnam.vn/hanh-chinh/dinh-danh-dien-tu-cho-doanh-nghiep-tren-vneid-570-101885-article.html) (excerpt).
- Registration: the legal representative uses their own level-2 VNeID in the phone app, chooses "Định danh tổ chức", enters the enterprise data and confirms with a passcode. Results come in the app or by SMS; one source estimates 5–15 working days — [PLO](https://plo.vn/cach-dang-ky-tai-khoan-dinh-danh-dien-tu-to-chuc-tren-ung-dung-vneid-post848652.html) (excerpt).
- A Thư viện Pháp luật topic headline refers to organisations registering "trước 30/6/2026" — [topic page](https://thuvienphapluat.vn/hoi-dap-phap-luat/chu-de/dinh-danh-dien-tu) (title only).
- No digital signature is described for creating an organisation account.

**dichvucong.gov.vn signing**
- A 2023 guide says to download "VNPT-CA Plugin (file này có thể sử dụng với bất kỳ nhà cung cấp chữ ký số nào)" through the national portal flow — [FastCA, 28/07/2023](https://fastca.vn/huong-dan-su-dung-chu-ky-so-dich-vu-cong) [Vendor].
- An excerpt says the portal lists signing software with separate Windows and Mac downloads (excerpt in search results for dichvucong.gov.vn guides; attribution uncertain).

**dangkykinhdoanh.gov.vn (business registration)**
- Nghị định 168/2025/NĐ-CP (30/6/2025; effective 01/7/2025), Article 37: online enterprise registration means the founder or enterprise "sử dụng tài khoản định danh điện tử" on the national business registration portal — [hethongphapluat, Art. 37](https://hethongphapluat.com/decree-no-168-2025-nd-cp-dated-june-30-2025-on-enterprise-registration/dieu-37) [Legal text mirror] (excerpt).
- Household businesses also register with an e-ID account (Art. 111) — [dhtaxlaw](https://www.dhtaxlaw.com.vn/thu-tuc-dang-ky-ho-kinh-doanh-qua-mang-theo-nghi-dinh-168-2025-nd-cp-chi-tiet) (excerpt).
- A commentary says the old "tài khoản đăng ký kinh doanh" login was abolished from 01/7/2025, "thay thế bằng phương thức ký số hoặc xác thực điện tử hợp lệ" — [Luật Việt An](https://luatvietan.vn/xac-thuc-dien-tu-khi-uy-quyen-dang-ky-doanh-nghiep-tu-01-07-2025.html) (excerpt).
- Conflict: a Q&A headline asks whether that account can be used until 31/12/2025 — [Thư viện Pháp luật](https://thuvienphapluat.vn/hoi-dap-phap-luat/tai-khoan-dang-ky-kinh-doanh-duoc-su-dung-den-het-ngay-31122025-dung-khong-138056172.html) (title).
- One news item reports Nghị định 296/2026/NĐ-CP (23/7/2026) amending Nghị định 168 (excerpt; not verified).
- The portal's signing tool and its OS support were not found.

#### F. Business internet banking

- **VietinBank eFAST** (online registration at eregister.vietinbank.vn) — [VietinBank PDF, Phụ lục 01, undated](https://vietinbank.vn/assets/a28f113a-d1b3-4eee-87cf-91b88364f6f9) [Official]
  - Requires a USB token from a licensed CA.
  - Install the "VNPT Plugin" from https://smartca.vnpt.vn/download and the CA's "Token Manager".
  - Then "Kiểm tra chữ ký số", where "VNPT-CA Plugin hiện lên danh sách các chứng thư số", and the user enters the token PIN.
  - A new "VietinBank eFAST One" iOS app exists — [App Store](https://apps.apple.com/us/app/-/id6753792534).
- **Techcombank Business** — [Techcombank FAQ](https://techcombank.com/khach-hang-doanh-nghiep/quan-tri-hang-ngay/ngan-hang-so/chu-ky-so/cau-hoi-thuong-gap) [Official]
  - The certificate is issued by FPT-CA ("Công ty TNHH FPT IS").
  - Registration is in the Techcombank Business app, using the citizen ID card (CCCD) and face recognition.
  - Approvers enter a 6-digit passcode.
  - From 7/9/2024 a digital signature is mandatory for disbursements, guarantees and term deposits on Techcombank Business. "chỉ cần người duyệt lệnh cuối cùng có chữ ký số".
  - Free for one year.
  - SCF/FEB documents are signed "với CA provider's website" with an OTP.
  - No USB token or plugin is mentioned.
- **VCB DigiBiz**: two approval models (one-level or two-level). Authentication is by "Smart OTP (… tích hợp ngay trên ứng dụng VCB DigiBiz) và Hard Token". These are 2021–2022 launch articles, and none mentions a digital signature — [Znews](https://znews.vn/dich-vu-ngan-hang-so-vcb-digibiz-khong-phi-giao-dich-post1282435.html), [VnExpress](https://vnexpress.net/vcb-digibiz-bo-sung-tinh-nang-4619829.html) [News] (excerpt).
- **BIDV Direct**: a new corporate digital-banking platform on web, app and ERP channels, "tích hợp SmartOTP" — [Đại biểu Nhân dân](https://daibieunhandan.vn/bidv-direct-ung-dung-so-huu-ich-danh-cho-khach-hang-to-chuc-10383802.html) [News] (excerpt); [App Store](https://apps.apple.com/app/id6746896498). BIDV's API use-case documents still refer to "BIDV iBank" — [BIDV Open API PDF, 2025-08](https://openapi.bidv.com.vn/devportal/sites/devportal.openapi.bidv.com.vn/files/2025-08/Usecase%20G%C3%B3i%20Chuy%E1%BB%83n%20ti%E1%BB%81n%20trong%20n%C6%B0%E1%BB%9Bc%20doanh%20nghi%E1%BB%87p%20%20%20K%E1%BA%BFt%20n%E1%BB%91i%20BIDV%20iBank.pdf) (title).
- **SHB** (comparison point): online registration for corporate internet banking includes downloading and installing a digital-signature plugin if the browser lacks one — [SHB PDF](https://ibanking.shb.com.vn/shb-ebank-theme/css/images/document-file/SHB_HD%20DANG%20KY%20DICH%20VU%20INTERNET%20BANKING%20KHDN%20ONLINE.pdf) (excerpt).

### Inferences
- Synthesis table, based on the findings above. "Win-only" means every documented local component is Windows-only.

| Service | Local component documented | OS documented | Plugin-free path found |
|---|---|---|---|
| Tax returns on dichvucong.gdt.gov.vn / thuedientu | TCT SigningHub (.NET 4.8/4.8.1), eSigner (Java 8) + ESigner.Chrome.TCT, iTaxViewer | Windows (7/8.1/10/11) | Remote signing for returns (MISA eSign named), not for attachments. Unknown whether SigningHub must still be installed. |
| HTKK | Desktop app needing .NET 3.5 | Windows | None found |
| hoadondientu.gdt.gov.vn | HĐĐT plugin bundled with eSigner | Windows (inferred) | Use a provider portal instead |
| E-invoice providers | MISA KYSO (token), CA plugins | VNPT-CA Plugin: Windows and macOS; others unknown | Yes: HSM or remote signing (MISA eSign, SmartCA, Viettel HSM/MySign), plus mobile apps |
| BHXH portal | Chrome extension + .exe background app | Windows 7+, Chrome or Cốc Cốc | Remote-signing step exists, but the official guide still requires the BHXH tool on the PC. EFY has a web version. |
| Customs | ECUS5-VNACCS desktop + SQL Server Express | Windows (inferred, not documented) | None found |
| dichvucong.gov.vn | VNPT-CA Plugin for signing (2023) | Windows and macOS | VNeID login (phone app); certificate login no longer accepted for some procedures from 1/6/2026 |
| dangkykinhdoanh.gov.vn | Unknown | Unknown | e-ID account route (Nghị định 168) |
| Banks | VietinBank: token + VNPT-CA Plugin + Token Manager | Windows and macOS (VNPT) | Techcombank in-app FPT-CA signature; VCB/BIDV Smart OTP apps |

- The strongest Windows lock-in is recurring tax filing (.NET-based SigningHub, plus HTKK on .NET 3.5) and customs declaration. Tax filing affects essentially every business every month or quarter.
- E-invoicing and banking are the most "Linux-ready" today, because the signing key can live on the provider's side (HSM or remote) and approval happens on a phone.
- Remote signing exists on the tax and BHXH portals, but in both cases the guides still show a local Windows helper. Even users of remote signing may therefore need Windows unless the portal's browser flow skips the helper. This was not verified.
- A few vendors (Thái Sơn across ECUS, the ebh.vn I-VAN and E-invoice; MISA across meInvoice, AMIS BHXH and eSign; VNPT across CA, plugin and BHXH) sit across several services. Their tools set the client requirements for many businesses, which makes them high-leverage contacts for asking about Linux support.
- The shift of portal logins from organisation certificates to VNeID organisation accounts removes the need for a token at login, but not at signing.

### Gaps
- Official requirement pages from the tax authority could not be read: thuedientu.gdt.gov.vn rejected the fetch, and the official requirements for eSigner and TCT SigningHub come only from vendor guides. No official statement on macOS or Linux support was found either way.
- Not found:
  - whether remote signing on dichvucong.gdt.gov.vn works without installing TCT SigningHub or eSigner;
  - the exact launch date of dichvucong.gdt.gov.vn, and whether thuedientu.gdt.gov.vn is being retired (sources conflict);
  - canhan.gdt.gov.vn requirements (individuals; presumably VNeID or OTP with no signature).
- An unverified excerpt says HTKK 5.7.6 was released 22/08/2026. It could not be tied to a page, so 5.7.2 (July 2026) is the latest confirmed version here.
- ESigner.Chrome.TCT "malware" listing: the source was unreachable and unconfirmed. Whether the official GDT extension is currently on the Chrome Web Store is unknown.
- E-invoice: the signing tools and OS support of BKAV eHoadon, EasyInvoice (SoftDreams), VNPT Invoice's own portal and Viettel SInvoice's web signing were not researched. Also unknown is whether MISA KYSO has a macOS build.
- BHXH:
  - the names of the "2 lựa chọn" in the official guide (screenshots only), and whether either is non-Windows;
  - whether BHXH's own free declaration desktop software (KBHXH) still exists in 2026, and its requirements;
  - VNPT-BHXH and other I-VANs' client requirements.
- Customs: no official or vendor page with ECUS5-VNACCS OS requirements was found (Windows is inferred from .NET/SQL Server Express); neither was FPT.VNACCS or other software, nor how Customs registers and accepts signatures (remote signing acceptance not confirmed by Customs).
- dangkykinhdoanh.gov.vn: no current guide on its signing tool or plugin was found. Whether a digital signature is still accepted as an alternative to the VNeID account after Nghị định 168/296 is unclear (sources conflict).
- Banks: no current requirements found for VCB DigiBiz digital-signature use (2026), BIDV iBank/Direct token or plugin requirements, or MB Biz at all. VietinBank's PDF is undated.

## Key Question 2: For the signing plugins these portals use, is there an official Linux or macOS build?

### Takeaway
No official Linux build was found for any portal-side signing component: TCT SigningHub, eSigner and the HĐĐT plugin for tax, BHXH's extension plus background app, HTKK, and ECUS5-VNACCS. The only component with a documented non-Windows build is the CA-side VNPT-CA Plugin. It has a macOS .pkg (v1.0.2.4) next to the Windows build (v1.0.5.0) and no Linux package on VNPT's official download page. It is the plugin cited for dichvucong.gov.vn (2023) and for VietinBank eFAST registration.

### Cited Findings
- **TCT SigningHub** (tax DVC portal): it needs .NET Framework 4.8 (Win10) or 4.8.1 (Win11), downloaded from Microsoft, before installation — [FastCA, 27/01/2026](https://fastca.vn/huong-dan-cai-dat-cau-hinh-chu-ky-so-tren-dich-vu-cong). Only Windows versions (7/8.1/10/11) are referenced — [MISA FAQ, 29/10/2026](https://helpact.misa.vn/?p=73319). No macOS or Linux installer is mentioned in either.
- **eSigner** (tax, and the HĐĐT plugin for e-invoices): "Java-based signing tool that needs Java 8" — [MISA FAQ](https://helpact.misa.vn/?p=73319). The installer is "eSigner_setup" with a Windows-style wizard — [MISA help](https://helpact.misa.vn/?p=73747). A search for an eSigner macOS installer found no official guide — [search excerpt summary; Thư viện Pháp luật eSigner 2026 page](https://thuvienphapluat.vn/ma-so-thue/phap-luat-thue/tai-phan-mem-esigner-ky-dien-tu-phien-ban-moi-nhat-2026-huong-dan-cai-dat-76290-223339.html) (403 when fetched).
- **HTKK**: needs .NET Framework 3.5 and Windows features or DISM — [Thư viện Pháp luật](https://thuvienphapluat.vn/hoi-dap-phap-luat/huong-dan-cai-dat-phan-mem-htkk-540-chi-tiet-ra-sao-138059102.html) (excerpt). No source confirming that HTKK, token signing or Wine work on Ubuntu was found (a search for Linux/Wine reports returned nothing relevant).
- **BHXH portal**: Chrome extension "Vietnam Social Security Internal" plus a ".exe" background app; "Window 7 trở lên"; Chrome or Cốc Cốc. macOS and Linux are not mentioned — [FastCA, 09/08/2023](https://fastca.vn/cai-dat-extension-ung-dung-nen-ky-so-dang-ky-ke-khaibhxh). The same stack is described by the Thái Sơn I-VAN, with no OS stated — [ebh.vn, 09/08/2023](https://ebh.vn/nghiep-vu-phan-mem/khong-cam-chu-ky-so-co-the-khai-bhxh-qua-mang-duoc-khong).
- **VNPT-CA Plugin** — [VNPT SmartCA download page](https://smartca.vnpt.vn/download) [Official]:
  - "Bộ cài phần mềm VNPT CA-Plugin (version 1.0.5.0)" (VNPT-CA Plugin_Office_Setup.exe);
  - "Bộ cài phần mềm VNPT CA-Plugin Mac OS (version 1.0.2.4)" (VNPT-CA_Plugin_macOS.pkg);
  - token drivers listed only for Windows ("Driver etoken cho hdh windows 64bit/32bit", "Driver cykentoken cho hđh windows");
  - a "Pkcs11 Admin v0.3.0" .rar;
  - a Windows-only "VNPT_CAMS_Plugin_Setup.exe";
  - no Linux, Ubuntu or .deb items, and no dates on the page.
- **MISA KYSO** (meInvoice token signing): a download is offered, but its OS builds are not stated — [MISA help](https://helpact.misa.vn/?p=75693) (excerpt).
- **Mobile and remote alternatives with non-Windows clients:**
  - meInvoice app (iOS/iPadOS, and Apple Silicon Macs on macOS 11+) — [App Store](https://apps.apple.com/app/id1460947129);
  - Viettel MySign (iOS) — [App Store](https://apps.apple.com/mx/app/mysign/id1633019232);
  - VNPT SmartCA (iOS) — [App Store](https://apps.apple.com/sg/app/vnpt-smartca/id1540522462);
  - Techcombank Business app signing with an FPT-CA certificate — [Techcombank FAQ](https://techcombank.com/khach-hang-doanh-nghiep/quan-tri-hang-ngay/ngan-hang-so/chu-ky-so/cau-hoi-thuong-gap).

### Inferences
- .NET Framework 4.8 and 3.5 are Windows-only runtimes. TCT SigningHub and HTKK therefore have no native path on Linux or macOS as distributed. Running them under Wine/Mono is unverified.
- eSigner's Java base makes cross-platform support technically plausible, but only a Windows installer is documented.
- The Chrome Web Store extensions (ESigner.Chrome.TCT, Vietnam Social Security Internal) would install in Chrome on Linux. In the documented setups, though, they only work with a Windows native helper (eSigner/HĐĐT plugin, or the BHXH background .exe), so the extension alone is not enough.
- VNPT-CA Plugin has a macOS build, so a Mac user can sign on portals that accept it (dichvucong.gov.vn as of 2023, VietinBank eFAST). Linux has no equivalent from VNPT.
- On every Windows-locked service, a Linux distribution today can offer only one of: a Windows VM or remote desktop; remote signing where the portal allows it without a local helper; or the provider/mobile route (e-invoice HSM, bank apps, eTax Mobile for household businesses).

### Gaps
- No official statement from Cục Thuế, BHXH or Cục Hải quan listing supported operating systems was found. All OS information comes from vendor and CA guides or is inferred from runtimes.
- Not found:
  - macOS or Linux builds of: TCT SigningHub, eSigner, the HĐĐT plugin, the BHXH background app, MISA KYSO, Viettel/BKAV/FPT/EasyCA token tools, ECUS;
  - whether VNPT-CA Plugin is still the plugin dichvucong.gov.vn uses in 2026, or whether VNeID-based signing has replaced it.
- No user reports (forums, GitHub) were found of Linux users signing successfully on these portals through Wine, VMs or native PKCS#11 (the standard token interface) setups. A targeted forum search, such as Voz or Tinhte, would be needed.
