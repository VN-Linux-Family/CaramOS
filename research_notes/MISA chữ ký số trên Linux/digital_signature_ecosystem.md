# Vietnamese digital signature (chữ ký số) ecosystem, 2025–2026: licensed CAs, certificate forms, legal basis, Linux support

_All pages were read on 2026-11-05, public pages only (no logins, no downloads). Labels used below: **[official]** means the CA's own site or a state body's site. **[vendor]** means a CA's marketing or help article. **[reseller/consultant]** means a third party. **[snippet]** means the claim comes from a search-result summary and I did not open the page. Legal article numbers come from hethongphapluat.com, a commercial legal portal. They match each other and the NEAC summary, but they have not been checked against vbpl.vn or Công báo._

## 1. Which providers are licensed today, and which forms (token, remote signing, SIM) does each sell?

### Takeaway
NEAC's official list of public CAs (read 2026-11-05) has **26 providers**, all marked "Đang hoạt động" (active). 25 hold a **USB Token** licence, 14 hold a **Remote Signing** (ký số từ xa) licence and 3 hold a **SIM PKI** licence (Viettel, MobiFone, New-Telecom). 7 also list a **Timestamp** service. Every CA named in the brief is on the list. Licences issued since July 2025 carry Ministry of Science and Technology numbering (…/GP-BKHCN). Older ones keep the Ministry of Information and Communications numbering (…/GP-BTTTT).

### Cited Findings

**The current licensed list.** NEAC's "CA công cộng" page has 2 pages: entries 1–20 on page 1 and 21–26 on page 2, with no page 3 ([NEAC p1](https://neac.gov.vn/vi/ca-cong-cong); [NEAC p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2)) [official]. The page shows **no "last updated" date**. It includes licences issued on 25/07/2025, so it has been updated since then. Rows as listed (dd/mm/yyyy):

| # | Provider (CA brand) | Licence – service type | Issued | Expires | Website | Src |
|---|---|---|---|---|---|---|
| 1 | Bkav (BkavCA) | 356/GP-BKHCN – USB Token; 20/GP-BTTTT – Remote Signing | 25/07/2025; 13/01/2023 | 18/03/2035; 22/05/2032 | bkavca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 2 | Nacencomm (CA2) | 375/GP-BTTTT – USB Token; 604/GP-BTTTT – Remote Signing; also Timestamp | 28/08/2020; 28/12/2022 | 27/08/2030; 27/12/2032 | cavn.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 3 | CMC (CMC-CA) | 186/GP-BTTTT – USB Token; 12/GP-BTTTT – Remote Signing | 16/05/2019; 13/01/2025 | 15/05/2029; 12/01/2035 | cmc.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 4 | Softdreams (EasyCA) | 61/GP-BTTTT – USB Token; 82/GP-BTTTT – Remote Signing | 21/02/2020; 14/03/2023 | 20/02/2030; 13/03/2033 | easyca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 5 | Thái Sơn (eCA) | 234/GP-BTTTT – USB Token | 10/05/2022 | 09/05/2032 | eca.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 6 | EFY Việt Nam (EFY-CA) | 381/GP-BTTTT – USB Token | 05/04/2018 (as listed) | 04/04/2033 | efyca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 7 | FastCA | 16/GP-BTTTT – USB Token | 12/01/2023 | 20/07/2030 | fastca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 8 | FPT IS (FPT-CA) | 439/GP-BTTTT – USB Token; 440/GP-BTTTT – Remote Signing; also Timestamp | 24/11/2023 (both) | 12/10/2030; 08/12/2031 | link text fpt-ca.com.vn, target dichvudientu.fpt.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 9 | Hilo (T-Van Hilo) | 690/GP-BTTTT – USB Token | 25/10/2021 | 24/10/2031 | hilo.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 10 | ICORP (I-CA) | 245/GP-BTTTT – USB Token | 19/05/2022 | 31/08/2031 | i-ca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 11 | Intrust (IntrustCA) | 266/GP-BTTTT – Remote Signing only; also Timestamp | 01/08/2023 | 31/07/2033 | intrustca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 12 | L.C.S (LCS-CA) | 495/GP-BTTTT – USB Token | 12/11/2019 | 11/11/2029 | lcs.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 13 | Mắt Bão (MatbaoCA) | 340/GP-BTTTT – USB Token; 396/GP-BTTTT – Remote Signing | 07/07/2022; 27/12/2024 | 06/07/2032; 27/12/2034 | matbao.net | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 14 | MISA (MISA-CA / MISA eSign) | 184/GP-BTTTT – USB Token; 696/GP-BTTTT – Remote Signing | 16/05/2019; 28/10/2021 | 15/05/2029; 27/10/2031 | misaca.vn, esign.misa.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 15 | MK (Công nghệ cao MK) | 355/GP-BKHCN – USB Token **and** Remote Signing | 25/07/2025 | 24/07/2035 | none listed | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 16 | MobiFone | 691/GP-BTTTT – USB Token; 379/GP-BTTTT – SIM PKI; 85/GP-BTTTT – Remote Signing | 25/10/2021; 13/12/2024; 27/02/2025 | 25/10/2031; 12/12/2034; 27/02/2035 | it.mobifone.vn (link target itc.mobifone.vn) | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 17 | NCCA (NC-CA) | 83/GP-BTTTT – USB Token | 17/03/2023 | 16/09/2029 | nc-ca.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 18 | New-Telecom (NewTel-CA) | 516/GP-BTTTT – USB Token **and** SIM PKI | 10/08/2021 | 09/08/2031 | newtel-ca.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 19 | Visnam | 689/GP-BTTTT – USB Token | 25/10/2021 | 24/10/2031 | visnam.com | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 20 | Chứng số an toàn (Safe-CA) | 15/GP-BTTTT – USB Token | 12/01/2023 | 26/08/2031 | safecert.com.vn | [p1](https://neac.gov.vn/vi/ca-cong-cong) |
| 21 | Chữ ký số VI NA (SmartSign) | 29/GP-BTTTT – USB Token | 20/01/2022 | 04/11/2031 | smartsign.com.vn | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |
| 22 | SAVIS (TrustCA) | 10/GP-BTTTT – USB Token; 697/GP-BTTTT – Remote Signing; also Timestamp | 08/01/2019; 28/10/2021 | 07/01/2029; 27/10/2031 | trustca.vn | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |
| 23 | Tổng Công ty Viễn thông Viettel (Viettel-CA, MySign) | 132/GP-BTTTT – USB Token; 363/GP-BTTTT – Remote Signing; 134/GP-BTTTT – SIM PKI; also Timestamp | 16/03/2022; 20/07/2022; 16/03/2022 | 28/09/2030; 19/07/2032; 18/11/2031 | viettel-ca.vn | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |
| 24 | Giải pháp Thanh toán Việt Nam (VNPAY) | 244/GP-BTTTT – USB Token; 250/GP-BTTTT – Remote Signing; also Timestamp | 06/09/2024; 24/07/2023 | 05/09/2034; 23/07/2033 | vnpay.vn | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |
| 25 | Tập đoàn VNPT (VNPT-CA, VNPT SmartCA) | 576/GP-BTTTT – USB Token; 698/GP-BTTTT – Remote Signing; also Timestamp | 31/12/2019; 28/10/2021 | 15/09/2029; 27/10/2031 | vnpt-ca.vn; smartca.vnpt.vn (remote signing) | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |
| 26 | TNHH Tư vấn – Thương mại Khánh Linh (WGroup) | 95/GP-BTTTT – USB Token | 10/02/2022 | 09/02/2032 | wgroup.vn | [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2) |

**Earlier lists, for context.**
- The 2019 MIC list (article dated 13/06/2019) has 12 providers with licence numbers that have since changed. Examples: VNPT-CA 595/GP-BTTTT (27/11/2017), Viettel-CA 498/GP-BTTTT (28/9/2015), BKAV-CA 57/GP-BTTTT (17/3/2015, 10-year term), FPT-CA 527/GP-BTTTT, CA2 425/GP-BTTTT, NEWTEL-CA 225/GP-BTTTT, SAFE-CA 424/GP-BTTTT, Smartsign 496/GP-BTTTT, EFY-CA 153/GP-BTTTT, TrustCA 10/GP-BTTTT, MISA-CA 184/GP-BTTTT and CMC-CA 186/GP-BTTTT. The page is now hosted on the merged ministry's site ([mst.gov.vn](https://mst.gov.vn/danh-sach-cac-doanh-nghiep-da-duoc-cap-giay-phep-dich-vu-chung-thuc-chu-ky-so-cong-cong-197116271.htm)) [official, historical].
- An older NEAC article was titled "Việt Nam đã có 14 nhà cung cấp dịch vụ chứng thực chữ ký số công cộng" ([dichvucong.neac.gov.vn](https://dichvucong.neac.gov.vn/tin-tuc-trung-tam/viet-nam-da-co-14-nha-cung-cap-dich-vu-chung-thuc-chu-ky-so-cong-cong)) [official, undated, snippet].
- A NEAC news item reports a working session with SAWACO, the HCMC water utility. It names 8 public CAs that attended: VNPT-CA, CMC-CA, EasyCA, MISA-CA, BkavCA, CA2, IntrustCA and MatbaoCA. The search summary dated it 11/10/2026 ([NEAC](https://neac.gov.vn/vi/tin-tuc-su-kien/detail/neac-phoi-hop-cung-sawaco-va-cac-ca-cong-cong-thuc-day-ung-dung-chu-ky-so-trong-dich-vu-truc-tuyen-902.htm)) [official, snippet].

**Remote-signing products (official pages unless marked).**
- **VNPT SmartCA:** NEAC lists smartca.vnpt.vn as VNPT's remote-signing site ([NEAC p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2)). VNPT's download page has a "VNPT SmartCA RS CPS" (file dated 02/06/2022) and links to the iOS app "vnpt-SmartCA" and the Android app `com.vnptit.vnpt_kyso_v2` ([smartca.vnpt.vn/download](https://smartca.vnpt.vn/download)).
- Press reports say that since 09/2025 citizens can create a VNPT SmartCA personal certificate and a free signing package for the National Public Service Portal inside the VNeID app ([mekongasean.vn](https://mekongasean.vn/khoi-tao-chu-ky-so-ca-nhan-vnpt-smartca-ngay-tren-vneid-34983.html)) [snippet]. They also say NEAC published SmartCA's service certificate for 2026–2031 ([vneconomy.vn](https://vneconomy.vn/vnpt-smartca-duoc-gia-han-chung-thu-so-den-2031-cung-co-niem-tin-khach-hang-so.htm)) [snippet].
- **Viettel MySign:** Viettel-CA's download page lists MySign Desktop for Windows 1.7.3 (`mysign_desktop_windows_1.7.3_r260913.zip`), MySign Desktop for macOS 1.7.2 (`mysigndesktop_macos_1.7.2_r260913.zip`), and MySign Android (`mysign.apk`) and iOS apps. It also has a "Remote Signing" CA certificate issued 26/09/2023 ([viettel-ca.vn/tai-ve](https://viettel-ca.vn/tai-ve)).
- **Bkav Remote Signing:** It has its own site, which now redirects from remotesigning.bkavca.vn to remotesigning.bkav.com. Its mobile apps are "Bkav Remote Signing (BRS)" and "Pitagon – Bkav Remote Signing", described as signing XML and PDF documents ([remotesigning.bkavca.vn/pitagon](https://remotesigning.bkavca.vn/pitagon)) [snippet].
- **MISA eSign:** a free MISA JSC app for iPhone and iPad that also runs on Apple-silicon Macs (macOS 11+, M1 or later) ([App Store](https://apps.apple.com/vn/app/misa-esign/id1586580978)). MISA's launch material calls it "ký số kiểu mới không cần USB token, có thể ký trên mobile" (a new way to sign: no USB token, can sign on mobile) ([amis.misa.vn](https://amis.misa.vn/72461/nhan-video-tai-lieu-le-ra-mat-chu-ky-so-tu-xa-misa-esign-ky-so-kieu-moi-khong-can-usb-token-co-the-ky-tren-mobile/)) [vendor].
- **EasyCA:** an App Store app by Softdreams for iPhone, iPad and Apple-silicon Macs (macOS 11+). It is described as certificate-list management plus eKYC (liveness and face matching) ([App Store](https://apps.apple.com/se/app/easyca/id6502670861)) [snippet].

**SIM PKI / mobile PKI.**
- Only Viettel (134/GP-BTTTT), MobiFone (379/GP-BTTTT, 13/12/2024) and New-Telecom (516/GP-BTTTT) hold SIM PKI licences ([NEAC p1](https://neac.gov.vn/vi/ca-cong-cong); [p2](https://neac.gov.vn/vi/ca-cong-cong?pageIndex=2)).
- Viettel's FAQ gives minimum and recommended phone versions for "SIM CA": iOS 12 / Android 7 minimum, iOS 14+ / Android 11+ recommended. It says subscribers need a plan and device that support SMS: "Thuê bao di động sử dụng giải pháp SIM CA cần sử dụng các gói dịch vụ di động và thiết bị di động hỗ trợ gửi, nhận tin nhắn SMS" ([viettel-ca.vn FAQ](https://viettel-ca.vn/ho-tro/viettelca/cau-hoi-thuong-gap)) [official, undated].

### Inferences
- NEAC's three service labels appear to map one-to-one onto the three models in Điều 26.1 of Nghị định 23/2025 (see Q2): "USB Token" is (a) hardware key storage, "SIM PKI" is (b) mobile device, and "Remote Signing" is (c) ký số từ xa. Every major CA except Intrust sells tokens. Remote signing is now offered by all the large players: VNPT, Viettel, FPT, MISA, Bkav, CA2, EasyCA, CMC, SAVIS, VNPAY and MobiFone.
- Bkav's old 10-year licence 57/GP-BTTTT ran out on 17/03/2025. The new 356/GP-BKHCN, issued 25/07/2025, expires 18/03/2035, which suggests a continuous renewal under the new ministry. This is my inference from the dates.
- Timeline of remote-signing licences: the first three were issued on 28/10/2021 (MISA 696, SAVIS 697, VNPT 698). Then came Viettel (20/07/2022), CA2 (28/12/2022), Bkav (13/01/2023), EasyCA (14/03/2023), VNPAY (24/07/2023), Intrust (01/08/2023), FPT (24/11/2023), Mắt Bão (27/12/2024), CMC (13/01/2025), MobiFone (27/02/2025) and MK (25/07/2025), per the NEAC rows above.

### Gaps
- NEAC shows no update date and no suspended or revoked entries. I could not check whether any provider was dropped from the list in 2025–2026. The MIC/MST 2019 list and the current list differ only in providers added, not removed, but I did not compare them systematically.
- I did not verify which forms each CA actually markets **to businesses** (as opposed to the licence types), or their prices.
- I did not verify the remote-signing product names for FPT, CA2, CMC, SAVIS, VNPAY, MobiFone, Mắt Bão, Intrust and MK.

## 2. Is remote signing now a full legal equivalent of a token signature for tax, invoices, social insurance and customs? Since when? (legal basis and authority)

### Takeaway
In law, yes. Under Luật Giao dịch điện tử 2023 (effective 01/07/2024), every **chữ ký số** (digital signature) has the same legal value as the signer's handwritten signature. Nghị định 23/2025/NĐ-CP (issued 21/02/2025, effective **10/04/2025**) replaces Nghị định 130/2018 and 48/2024 and names **ký số từ xa** as one of three models of public digital signature service, alongside hardware tokens and mobile devices. So a remote signature from a licensed CA is a chữ ký số công cộng on the same legal footing as a token signature. The decree has said so explicitly since 10/04/2025, and remote-signing licences have existed since 28/10/2021. Whether each agency's system accepts it is a separate, practical question. CA guides show remote signing used on eTax. I found **no official statement** from the tax, social-insurance or customs authorities, and customs (VNACCS) is the least clear.

### Cited Findings

**Luật Giao dịch điện tử 2023 (Luật số 20/2023/QH15)**
- Adopted 22/06/2023, effective 01/07/2024 ([Điều 22](https://hethongphapluat.com/luat-giao-dich-dien-tu-2023/dieu-22)).
- Điều 22.1 sorts electronic signatures by scope of use into three kinds ([Điều 22](https://hethongphapluat.com/luat-giao-dich-dien-tu-2023/dieu-22)):
  - **chữ ký điện tử chuyên dùng**: "do cơ quan, tổ chức tạo lập, sử dụng riêng cho hoạt động của cơ quan, tổ chức đó" (created by an agency or organization for its own activities only);
  - **chữ ký số công cộng**: a digital signature used in public activity, guaranteed by a public digital signature certificate;
  - **chữ ký số chuyên dùng công vụ**: a digital signature for official government duties, guaranteed by an official-duty certificate.
- Điều 22.3 sets the requirements for a chữ ký số ([Điều 22](https://hethongphapluat.com/luat-giao-dich-dien-tu-2023/dieu-22)):
  - it confirms the signer and the signer's approval of the data message;
  - "Mọi thay đổi đối với thông điệp dữ liệu sau thời điểm ký đều có thể bị phát hiện" (any change to the message after signing can be detected);
  - it is guaranteed by a certificate (public signatures by a public CA's certificate);
  - the signature-creation means must keep the signature-creation data from being disclosed or used to forge, and must not alter the data being signed.
- Điều 23 ([Điều 23](https://hethongphapluat.com/luat-giao-dich-dien-tu-2023/dieu-23)):
  - (1) "Chữ ký điện tử không bị phủ nhận giá trị pháp lý chỉ vì được thể hiện dưới dạng chữ ký điện tử." (An e-signature is not denied legal value just because it is electronic.)
  - (2) "Chữ ký điện tử chuyên dùng bảo đảm an toàn hoặc chữ ký số có giá trị pháp lý tương đương chữ ký của cá nhân đó trong văn bản giấy." (A secure specialized e-signature or a digital signature has the same legal value as the person's signature on paper.)
  - (3) Where a law requires a document to be confirmed by an agency or organization, a data message signed with that organization's chữ ký điện tử chuyên dùng bảo đảm an toàn or chữ ký số meets the requirement. This is the electronic counterpart of the stamp/seal requirement.
- **Terminology:** the law's term is "chữ ký điện tử chuyên dùng bảo đảm an toàn" (secure specialized e-signature). NEAC's summary of Nghị định 23 does not use a bare "chữ ký điện tử an toàn" ([NEAC](https://neac.gov.vn/vi/tin-tuc-su-kien/detail/nhung-quy-dinh-moi-ve-chu-ky-dien-tu-va-dich-vu-tin-cay-646.htm)).

**Nghị định 23/2025/NĐ-CP on electronic signatures and trust services**
- NEAC's article was published 10/04/2025. It says the Government issued the decree on 21/02/2025: "Nghị định này có hiệu lực từ ngày 10/4/2025". The decree has 4 chapters and 48 articles. It does not cover chữ ký số chuyên dùng công vụ ([NEAC](https://neac.gov.vn/vi/tin-tuc-su-kien/detail/nhung-quy-dinh-moi-ve-chu-ky-dien-tu-va-dich-vu-tin-cay-646.htm)) [official]. The Government policy portal also published it ([xaydungchinhsach.chinhphu.vn](https://xaydungchinhsach.chinhphu.vn/nghi-dinh-so-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay-119250225073330307.htm)) [official, not opened].
- **Repeal (Điều 46):** khoản 1 says the decree "có hiệu lực thi hành từ ngày 10 tháng 4 năm 2025" (takes effect 10 April 2025). Khoản 2 says **Nghị định 130/2018/NĐ-CP and Nghị định 48/2024/NĐ-CP "hết hiệu lực"** (cease to have effect) from that date, except for the cases in Điều 47 ([full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay)).
- **Điều 3 definitions** ([full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay)):
  - "Ký số" (signing) is "đưa khóa bí mật vào một chương trình phần mềm để tự động tạo và gắn chữ ký số" (feeding the private key into software that automatically creates and attaches the digital signature).
  - "Phương tiện lưu khóa bí mật" (key storage means) "là phương tiện chứa khóa bí mật của thuê bao" (is the means that holds the subscriber's private key).
  - Điều 3 has no separate definition of "ký số từ xa".
- **Điều 12:** a chữ ký số công cộng is a signature "được bảo đảm bởi chứng thư chữ ký số công cộng" (guaranteed by a public digital signature certificate) that meets Điều 22.3 of the law ([full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay)).
- **Điều 26.1, the three service models** for chữ ký số công cộng ([full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay)):
  - (a) signing on "các phương tiện lưu khóa bí mật bằng thiết bị phần cứng" (hardware key storage);
  - (b) signing "trên thiết bị di động" (on a mobile device);
  - (c) signing "từ xa" (remote).
  - The text does not name USB token, SIM or HSM.
- **Remote-signing rules:**
  - Điều 37.4: a remote-signing provider may store the subscriber's private key and "phải bảo đảm sử dụng các phương thức an toàn để lưu trữ" (must use secure storage methods).
  - Điều 18.3.c: each key pair must be generated "ngẫu nhiên và đúng một lần duy nhất" (randomly, exactly once).
  - Điều 18.3.i: "Hệ thống thông tin cung cấp dịch vụ đặt tại Việt Nam" (the service's information systems must be located in Vietnam).
  - Điều 37.5.a: the provider must notify the subscriber at once if the key shows signs of exposure.
  - Điều 45.6: the subscriber must report a lost or misused key "trong thời gian 24 giờ" (within 24 hours).
  - Sources: [full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay).
- **Certificate lifetimes (Điều 7):**
  - a public digital signature certificate is valid "tối đa là 03 năm" (3 years at most);
  - a public CA's own certificate is valid up to 10 years;
  - per NEAC's summary, the national root certificate is valid 25 years and timestamp and data-message certificates up to 5 years.
  - Sources: [full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay); [NEAC](https://neac.gov.vn/vi/tin-tuc-su-kien/detail/nhung-quy-dinh-moi-ve-chu-ky-dien-tu-va-dich-vu-tin-cay-646.htm).
- **Transitional rules (Điều 47)** ([full text](https://hethongphapluat.com/nghi-dinh-23-2025-nd-cp-quy-dinh-ve-chu-ky-dien-tu-va-dich-vu-tin-cay)):
  - khoản 4: existing public CAs must review and upgrade their systems and staff "trong vòng 02 năm kể từ ngày Nghị định này có hiệu lực thi hành" (within 2 years of the effective date);
  - khoản 5: certificates issued under an old licence are issued once, for no longer than the licence's remaining term and at most 5 years;
  - **khoản 6: application software that integrates digital signing must be upgraded to meet Điều 17 within 2 years.**
- **Trust services:** NEAC's summary names three trust services: timestamping (cấp dấu thời gian), data-message certification (chứng thực thông điệp dữ liệu) and public digital signature certification ([NEAC](https://neac.gov.vn/vi/tin-tuc-su-kien/detail/nhung-quy-dinh-moi-ve-chu-ky-dien-tu-va-dich-vu-tin-cay-646.htm)).

**Implementing circulars (Bộ KH&CN, 2025)** [titles and snippets only, not read in full]
- Thông tư 16/2025/TT-BKHCN: model certification practice statement ([thuvienphapluat EN](https://thuvienphapluat.vn/van-ban/Cong-nghe-thong-tin/Circular-16-2025-TT-BKHCN-model-authentication-regulations-674303.aspx?tab=1)).
- Thông tư 17/2025/TT-BKHCN: technical requirements for interconnection between CAs and NEAC. Snippets give its date as 04/09/2025 or 05/09/2025, and one says it takes effect 05/09/2025 ([hcc.nghean.gov.vn](https://hcc.nghean.gov.vn/laws/detail/Trang-chu-Thong-tu-so-17-2025-TT-BKHCN-cua-Bo-Khoa-hoc-va-Cong-nghe-Quy-dinh-yeu-cau-ky-thuat-phuc-vu-lien-thong-voi-Trung-tam-Chung-thuc-dien-tu-quoc-gia-1929/)).
- Thông tư 28/2025/TT-BKHCN: the information format of digital signature certificates ([vbpl.vn attachment](https://vbpl.vn/TW/Lists/vbpq/Attachments/185049/THONG%20TU%2028%202025.doc)).

**Authority after the 2025 merger**
- The two ministries were merged "nguyên trạng" (as they stood), and the merged Bộ Khoa học và Công nghệ (Ministry of Science and Technology) began operating on **1/3/2025** ([VOV](https://vov.vn/chinh-tri/hop-nhat-nguyen-trang-bo-thong-tin-va-truyen-thong-voi-bo-khoa-hoc-va-cong-nghe-post1141446.vov); [VOV](https://vov.vn/chinh-tri/bo-khoa-hoc-va-cong-nghe-cong-bo-cap-truong-25-don-vi-dau-moi-sau-hop-nhat-post1159374.vov)) [snippet].
- Search snippets add that:
  - Nghị định 55/2025/NĐ-CP sets the merged ministry's functions from 1/3/2025;
  - Minister Nguyễn Mạnh Hùng was approved as Minister of Science and Technology on 18/2/2025;
  - units such as the former MIC's Cục An toàn thông tin ended operations.
  - Source: [mekongasean.vn](https://mekongasean.vn/quy-dinh-moi-ve-co-cau-to-chuc-cua-bo-khoa-hoc-va-cong-nghe-38852.html) [snippet; attribution to that exact page is uncertain].
- **NEAC (Trung tâm Chứng thực điện tử quốc gia)** now sits under Bộ KH&CN. Its functions are set by **Quyết định 155/QĐ-BKHCN of 03/03/2025**, which replaces Quyết định 26/QĐ-BTTTT of 16/01/2023 ([caselaw.vn](https://caselaw.vn/van-ban-phap-luat/507248-quyet-dinh-so-155-qd-bkhcn-ngay-03-03-2025-cua-bo-truong-bo-khoa-hoc-va-cong-nghe-quy-dinh-chuc-nang-nhiem-vu-quyen-han-va-co-cau-to-chuc-cua-trung-tam-chung-thuc-dien-tu-quoc-gia)) [title and snippet]. A legal-advice site describes NEAC as a public service unit (đơn vị sự nghiệp công lập) under Bộ KH&CN that also operates the national root certification service [snippet].
- Bộ KH&CN now issues CA licences. The two licences issued on 25/07/2025 carry "GP-BKHCN" numbers (Bkav 356, MK 355). Licences up to 27/02/2025 carry "GP-BTTTT" numbers ([NEAC p1](https://neac.gov.vn/vi/ca-cong-cong)).

**Remote signing in agency systems (practice)**
- **Tax (eTax):** Bkav's official remote-signing guide list has a section "Nộp tờ khai, khai thuế trên eTax" (filing tax returns on eTax) with these guides ([remotesigning.bkav.com](https://remotesigning.bkav.com/list-bkav-remotesigning/-/danh-sach-huong-dan/2)) [vendor]:
  - "Bài RMS02: Hướng dẫn cập nhật thông tin Chữ ký số từ xa lên hệ thống Thuế điện tử - eTax" (updating remote-signature details on eTax);
  - "Bài RMS03: Hướng dẫn Nộp tờ khai Thuế trên hệ thống Thuế điện tử - eTax bằng chữ ký số từ xa Bkav Remote Signing" (filing a tax return on eTax with Bkav Remote Signing);
  - "Bài RMS04: Hướng dẫn Lập giấy nộp tiền trên hệ thống Thuế điện tử ETAX bằng chữ ký số từ xa" (preparing a tax payment slip on eTax with remote signing).
  - The page shows no dates.
- MISA has a guide "[AMIS Thuế TNCN] KÝ NỘP TỜ KHAI BẰNG CHỮ KÝ SỐ TỪ XA MISA ESIGN" (signing and filing personal income tax returns with MISA eSign remote signing) ([amis.misa.vn](https://amis.misa.vn/159149/amis-thue-tncn-ky-nop-to-khai-bang-chu-ky-so-tu-xa-misa-esign/)) [vendor, title].
- **Social insurance (BHXH):** a consultant's guide covers updating the digital signature on the BHXH portal after a renewal or a change of provider ([aztax.com.vn](https://aztax.com.vn/cap-nhat-chu-ky-so-tren-gddt-bhxh/)) [consultant, snippet]. I found nothing official on remote signing for BHXH.
- **Customs (VNACCS/VCIS):** Viettel-CA's official guides cover registering a certificate with VNACCS-VCIS and getting the "4 thông số" (four parameters) for e-customs, in a token context ([viettel-ca.vn](https://viettel-ca.vn/ho-tro/viettelca/huong-dan-su-dung/huong-dan-dang-ky-he-thong-vnaccs-vcis)). FastCA, itself a licensed CA, says the certificate used for tax can be used for customs once it is registered with VNACCS ([fastca.vn](https://fastca.vn/quy-trinh-trien-khai-chu-ky-so/)) [vendor, snippet]. **No source I found says VNACCS accepts remote-signing certificates.**
- **Tax-portal signing helper:** the tax authority distributes its own local signing program. Bkav's download page lists "Phần mềm ký số điện tử CT SigningHub 1.1" as a Windows `.exe` ([bkavca.vn/tai-ve](https://bkavca.vn/tai-ve)). MISA has an article on downloading "TCT SigningHub" from the tax e-services site ([esign.misa.vn](https://esign.misa.vn/12613/tct-signinghub/)) [vendor, title]. An older tax tool, "eSigner", is also documented ([thuvienphapluat](https://thuvienphapluat.vn/ma-so-thue/phap-luat-thue/huong-dan-tai-va-cai-dat-phan-mem-esigner-ky-dien-tu-moi-nhat-cua-tong-cuc-thue-537983-200582.html)) [title].

### Inferences
- **Legal equivalence.** Điều 23.2 attaches handwritten-signature equivalence to any "chữ ký số", without regard to where the key is stored. Điều 26.1.c of Nghị định 23/2025 makes remote signing one of the three models of chữ ký số công cộng. From **10/04/2025**, a remote signature from a licensed CA is therefore legally equal to a token signature for every use, including tax, e-invoices, social insurance and customs. Before then, the Ministry was already licensing remote signing, from **28/10/2021**, so these signatures were treated as public digital signatures in practice.
- **What still differs is integration, not law.** Each agency portal has to support the CA's remote-signing flow or API. eTax evidently does: CA guides describe registering remote-signing certificates there. Customs is uncertain.
- **Deadlines that matter to CaramOS.** Existing CAs must finish upgrading their systems by **10/04/2027** (Điều 47.4). Software that "integrates digital signing" must meet Điều 17, also by about 10/04/2027 (Điều 47.6). If CaramOS ships or recommends its own signing or verification software, Điều 17 may apply to it.
- **Remote signing does not remove desktop dependencies.** It frees users from token drivers, but the official desktop clients I saw (MySign Desktop, TCT SigningHub) are Windows or macOS only (see Q3).

### Gaps
- I did not read the text of **Điều 17** (requirements for software that integrates digital signing). It is important for CaramOS.
- I could not check whether Nghị định 130/2018 or 48/2024 explicitly provided for remote signing before 2025. I did not read either text.
- I found no official notice from the tax authority, Vietnam Social Security or the customs authority on accepting remote signing. As background knowledge I have not checked here: the tax and customs general departments were reorganized in 2025 (Tổng cục → Cục under the Ministry of Finance). The writer should confirm current agency names before using them.
- I could not confirm the number of the National Assembly resolution behind the merger (often cited as Nghị quyết 176/2025/QH15). It did not appear in my results.
- hethongphapluat.com is a commercial portal and its metadata looked unreliable (it listed "Quốc hội" as issuer). Article numbers should be checked against vbpl.vn or Công báo.

## 3. For each major CA, is there an official Linux driver, middleware or plugin? (and macOS)

### Takeaway
None of the official download pages for VNPT-CA, Viettel-CA or Bkav-CA (read 2026-11-05) offers a Linux or Ubuntu build of a token driver, token manager, PKCS#11 library or signing plugin. VNPT and Viettel do offer **macOS** builds; Bkav lists only Windows `.exe` files. The only Linux mention I found is an undated Viettel-CA FAQ table that lists **Ubuntu 10 (minimum) / Ubuntu 12+ (recommended)** as a supported OS for USB Token, and Viettel's download page has no Linux file to back it up. I found no official Linux build from FPT-CA, MISA or EasyCA. Their Apple-side support is iPad apps that also run on Apple-silicon Macs.

### Cited Findings

**VNPT-CA / SmartCA** ([smartca.vnpt.vn/download](https://smartca.vnpt.vn/download)) [official; the page is undated, so dates come from file names]
- Plugins:
  - "Bộ cài phần mềm VNPT CA-Plugin (version 1.0.5.0)": `VNPT-CA Plugin_Office_Setup.exe`, Windows.
  - "Bộ cài phần mềm VNPT CA-Plugin Mac OS (version 1.0.2.4)": `VNPT-CA_Plugin_macOS.pkg`.
  - "Bộ cài plugin CAMS": `VNPT_CAMS_Plugin_Setup.exe`.
- Token drivers:
  - "Driver etoken cho hdh windows 64bit" and "… 32bit" (10/05/2019);
  - "Driver Token v8" (`.exe`, 22/08/2022);
  - "Driver cykentoken cho hđh windows" (10/05/2019);
  - "Hướng dẫn cài đặt Driver Token" (20/08/2021).
- Tools: "Pkcs11 Admin v0.3.0" (`.rar`, 31/07/2019, platform not stated).
- Integration documents: "Giới thiệu giải pháp VNPT-CA Plugin" and "Giới thiệu giải pháp VNPT-CA SignServer".
- **No item is labelled Linux or Ubuntu.**
- A third-party download site claims "VNPT-CA Token Manager" supports Linux ([updatestar](https://vnpt-ca-token-manager.updatestar.com/)) [reseller/aggregator, unverified]. VNPT's own page does not back this up.

**Viettel-CA / MySign** ([viettel-ca.vn/tai-ve](https://viettel-ca.vn/tai-ve)) [official]
- macOS: "Bộ phần mềm Token Manager V6 cho MacOS" and "Bộ cài đặt Mysign Desktop bản MacOS ver 1.7.2". Windows: MySign Desktop 1.7.3.
- Token Manager V2/V4/V5/V6 are each labelled "update 31/10/2023" (adds auto-renewal); platform not stated.
- Plugins:
  - "Phần mềm Viettel CA Signer Plugin 1.1.0.0";
  - "Bộ cài đặt ViettelCA Plugin Signer";
  - "Plugin ký số hỗ trợ USB Token phiên bản V2, V4, V5, V6" (`tai_lieu_tich_hop_plugin.zip`, an integration package);
  - "Plugin hỗ trợ đấu nối cho USB V6";
  - "Plugin TMS V5".
- Drivers and fixes:
  - "Phần mềm Driver USBToken v1/v2";
  - "Phần mềm fix lỗi smartcard thiết bị Token V4, V5" (`ccid.rar`);
  - a "KBNN" (State Treasury) signing plugin;
  - "ESigner 1.0.8" for tax e-filing;
  - "Fix môi trường" (environment repair) tools for tax and customs;
  - JDK builds compatible with VNACCS.
- Bundled runtimes: Java 6, 7 and 8 and Firefox 46/47.
- **No Linux, Ubuntu or PKCS#11 `.so` item.**
- Viettel-CA's FAQ has a requirements table, undated, with footer "© … 2018" ([FAQ](https://viettel-ca.vn/ho-tro/viettelca/cau-hoi-thuong-gap)) [official]:

  | USB Token | Minimum | Recommended |
  |---|---|---|
  | Windows | Windows 8 | Windows 10 trở lên (and later) |
  | macOS | macOS Sierra 10.12 | macOS Catalina 10.15 trở lên |
  | Linux | Ubuntu 10 | Ubuntu 12 trở lên |

  It disclaims responsibility for environments below the minimum. The search engine's metadata put the page at roughly 1,860 days old, about 2021 [snippet].

**Bkav-CA** ([bkavca.vn/tai-ve](https://bkavca.vn/tai-ve)) [official]
- All listed software is Windows `.exe`: BViewer, Java Plug-in 8u121 i586, Adobe Reader, iTaxViewer and "Phần mềm ký số điện tử CT SigningHub 1.1".
- "Bkav CA Token Manager – Phần mềm quản lý Chữ ký số" (token management, signing and PIN change) links to bkavca.vn/tk with no platform stated.
- **No Linux or macOS build** and no dates.
- NEAC's install guide for BkavCA describes installing BkavCA Token Manager (BTM), which "sẽ tự động cập nhật các thành phần còn thiếu" (automatically updates missing components) in a Windows-style flow ([NEAC EN](https://neac.gov.vn/en/news/detail/instructions-for-installing-digital-signature-bkavca-226.htm)) [official, snippet]. Other Bkav guides require "BkavCA Signer Plugin" [snippet].
- Bkav Remote Signing on a computer: the guide list names no desktop plugin and gives no OS requirements ([remotesigning.bkav.com](https://remotesigning.bkav.com/list-bkav-remotesigning/-/danh-sach-huong-dan/2)).

**FPT-CA**
- I found no official download page.
- An installation guide for "FPTeSignPlugin" (version 01.26) is hosted by ICORP/I-CA, another licensed CA. It describes a Windows "Run" flow ([i-ca.vn PDF](https://i-ca.vn/downloads/Huong%20dan%20cai%20dat%20thu%20vien%20FPTeSignPlugin_01.26_1.pdf)) [snippet].

**MISA-CA / MISA eSign**
- MISA eSign is an iPhone/iPad app that runs on Macs with macOS 11+ and Apple M1 or later ([App Store](https://apps.apple.com/vn/app/misa-esign/id1586580978)). I found no Linux build.
- MISA help articles cover Windows installers ("Setup.exe", "MISA KYSO") and USB-token activation ([helpesign.misa.vn](https://helpesign.misa.vn/knowledge-base/4-cai-dat-va-kich-hoat-usb-token/)) [vendor, snippet].
- One MISA article says Foxit Reader 9.5.0+ runs on "Windows, Mac hay Linux" and can sign PDFs with a USB token ([esign.misa.vn](https://esign.misa.vn/2573/foxit-reader-chu-ky-so-pdf/)) [vendor, snippet]. That is a claim about Foxit, not a MISA Linux product.
- Note: MISA is the focus of this report folder. Other notes may cover MISA in more depth.

**EasyCA (Softdreams)**
- NEAC's setup guide describes a Windows flow: plug in the token, run the installer, open the EasyCA software and enter an 8-character PIN ([NEAC EN](https://neac.gov.vn/en/news/detail/tools/easy-ca-digital-sign-setup-instructions-208.htm)) [official, snippet].
- A third-party extension-analysis site describes a Chrome extension that connects Softdreams web apps such as EasyInvoice to local hardware tokens. It uses a native-messaging host `com.tokensign` and is built on the open-source **chrome-token-signing** project. The site says it could not verify how the host behaves or which OSes it supports ([extscope.org](https://extscope.org/zh/extension/bkfagmnjmfjalbbaiphoiiafghlknpog)) [third-party].

**Generic Linux building blocks (not Vietnam-specific)**
- OpenSC implements the PKCS#11 API, so Firefox and Thunderbird can use tokens through it ([Launchpad opensc](https://launchpad.net/ubuntu/+source/opensc)). A DigiCert guide's Ubuntu setup installs `opensc`, `opensc-pkcs11` and `pcscd` [snippet].
- A gist shows a vendor PKCS#11 module on Ubuntu: SafeSign for GD StarSign tokens at `/usr/lib/libaetpkss.so` ([gist](https://gist.github.com/alexishida/ed6a3b71a7adf4b4b83df7ca0369e087)). This is not a Vietnamese CA.

### Inferences
- From the official pages, a Vietnamese CA desktop stack usually has four parts:
  1. a token middleware or driver (CSP/PKCS#11, Windows `.exe`);
  2. a **local "signing plugin"** that web portals call, for example VNPT-CA Plugin, Viettel CA Signer Plugin, BkavCA Signer Plugin or FPTeSignPlugin;
  3. a token-manager GUI;
  4. agency helpers such as TCT SigningHub, eSigner, Java runtimes or the KBNN plugin.

  Linux needs all four layers. Today only macOS gets the vendor-built versions (VNPT and Viettel).
- The Ubuntu row in Viettel's FAQ probably refers to the token itself working through a standard smart-card stack rather than to a shipped Viettel Linux package. I found no such package, so I treat it as unconfirmed.
- chrome-token-signing, the base of EasyCA's extension, is an open-source project originally from Estonia's Open eID. That suggests the native-messaging approach is portable to Linux. This is an inference, not checked against Softdreams.

### Gaps
- I did not check the download pages of CA2/Nacencomm (cavn.vn), SmartSign, Safe-CA, NewTel-CA, CMC, Mắt Bão, VNPAY, MobiFone, EFY, Thái Sơn or FastCA for Linux builds.
- I found no FPT-CA official download page and could not determine FPT's remote-signing desktop client.
- I could not tell whether any CA supplies a Linux PKCS#11 `.so` on request, outside its public pages. Contacting CA support was out of scope.
- I could not determine the platform of VNPT's "Pkcs11 Admin v0.3.0" or "Driver Token v8", or of Viettel's Token Manager V2–V5 and "Driver USBToken v1/v2".

## 4. Which token hardware models are common, and are they standard PKCS#11/CCID devices?

### Takeaway
The official CA pages name tokens only by the CA's own labels: Viettel "USB Token V2–V6", "Hồng Tiễn V1" and "Secure V0"; VNPT "etoken", "cykentoken", "Token AN" and "Driver Token v8"; Bkav none. So I could **not** confirm from official sources which OEM models (Feitian ePass2003, SafeNet eToken, Bit4id or others) each CA ships. The usual candidates are standard PKCS#11 smart-card tokens with Linux paths: OpenSC has an `epass2003` driver, and Thales lists Linux support for the SafeNet eToken 5110. Compatibility still has to be tested on real Vietnamese tokens.

### Cited Findings
- **Viettel-CA token labels:** USB Token V2, V3, V4, V5, V6 (each with its own installer), "USB Token Hồng Tiễn V1" and "USB Token Secure V0". It offers a "Phần mềm fix lỗi smartcard thiết bị Token V4, V5" (file `ccid.rar`) and a "PM khắc phục lỗi CD" fix ([viettel-ca.vn/tai-ve](https://viettel-ca.vn/tai-ve)) [official]. A reseller guide says a virtual CD drive containing the installer appears when the token is plugged in ([giaiphapdoanhnghiepviettel.vn](https://giaiphapdoanhnghiepviettel.vn/huong-dan-cai-dat-chu-ky-so-viettel-ca-token)) [reseller, snippet]. The FAQ names no manufacturer, chip, or FIPS/CC rating ([FAQ](https://viettel-ca.vn/ho-tro/viettelca/cau-hoi-thuong-gap)).
- **VNPT-CA labels:** separate drivers for "etoken" (Windows 32/64-bit), "cykentoken", a "Driver Token v8", and an unlock guide for "Token AN" ([smartca.vnpt.vn/download](https://smartca.vnpt.vn/download)) [official].
- **Bkav-CA:** the download page names no token models ([bkavca.vn/tai-ve](https://bkavca.vn/tai-ve)).
- **Feitian ePass2003:**
  - OpenSC has a dedicated driver called "epass2003", and the token can be set up with standard OpenSC tools such as `pkcs15-init` ([OpenSC wiki](https://github.com/OpenSC/OpenSC/wiki/Feitian-ePass2003)).
  - A Launchpad bug says support arrived in OpenSC 0.13 while Ubuntu then shipped 0.12; the fix was later released ([Launchpad #1176305](https://bugs.launchpad.net/bugs/1176305)).
  - An OpenSC issue reports that a newer ePass2003 batch fails to initialize ("Failed to create PKCS #15 meta structure: Card command failed"). The reporter warns that signing also fails. Its current status is unknown ([OpenSC #3034](https://github.com/OpenSC/OpenSC/issues/3034)) [snippet].
  - A FIPS certificate record covers "ePass2003 Token and ePass2003Auto Token" ([sec-certs](https://sec-certs.org/fips/2851eb1b0839402a)) [snippet; FIPS 140-2 Level 3 per summary].
  - A token reseller says Feitian supplies Linux and macOS drivers alongside Windows CSP drivers ([microcosm](https://microcosm.com/pdf/pki-tokens)) [reseller, snippet].
- **SafeNet eToken 5110 (Thales):** the product brief lists 5110+, 5110+ FIPS and 5110+ CC variants, about 73–80 KB of memory, and Windows, macOS and Linux support ([Thales brief, 2022-09](https://cpl.thalesgroup.com/sites/default/files/content/product_briefs/field_document/2022-09/safenet-etoken-5110-pb.pdf)) [official OEM, snippet].
- OpenSC's documentation, as summarized in a search snippet, says many CCID-compliant USB tokens need no proprietary driver ([OpenSC wiki, Aladdin eToken PRO](https://www.github.com/OpenSC/OpenSC/wiki/Aladdin-eToken-PRO)) [snippet].

### Inferences
- VNPT's "Driver etoken" label matches SafeNet/Aladdin eToken naming. Viettel's "fix lỗi smartcard … (ccid.rar)" for V4/V5 suggests those tokens are USB CCID smart-card devices. Both readings come from file labels only.
- The quickest way to identify the OEM is to plug in each CA's token and read the USB VID:PID with `lsusb`. From my background knowledge, not checked here: Feitian is VID 0x096e and SafeNet/Aladdin is 0x0529. Then check OpenSC's `opensc-tool -n` and `pkcs11-tool -L`.
- Even if a token is CCID and OpenSC-compatible, a CA may use a custom applet, a non-PKCS#15 layout or a vendor-only PKCS#11 module, as the ePass2003 batch issue shows. The CA's own Windows/macOS middleware may then be the only supported path. CaramOS would need a hardware test matrix covering at least VNPT, Viettel, Bkav, FPT, MISA and EasyCA tokens.

### Gaps
- No official source names the OEM token model for any Vietnamese CA. Bit4id did not appear in any source.
- I did not determine which token "versions" (Viettel V2–V6 and so on) are still being issued in 2025–2026.
- I did not find whether NEAC or Bộ KH&CN keeps a list of approved key-storage devices (thiết bị lưu khóa bí mật) or required certifications such as FIPS 140-2 L3 or CC EAL4+ under the new circulars.
