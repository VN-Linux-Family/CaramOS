# Digital-signature USB tokens and Vietnamese signing tools on Linux (Ubuntu 24.04 / Linux Mint 22.3): state of practice as of 2026-11-05

Scope note: these notes cover (a) token hardware, middleware and Ubuntu 24.04 packages, (b) browser integration, (c) Vietnamese Linux user reports and Wine/VM attempts, and (d) vendor Linux packages and open-source Vietnamese signing tools. "Snippet" marks a claim that comes from a search-result summary of a page I did not open. Everything else was read from the cited page. No software was downloaded, installed or run. Package versions came from public Launchpad and packages.ubuntu.com pages.

## Q1. Which tokens sold in Vietnam work with OpenSC out of the box, which need a vendor PKCS#11 library, and is that library available for Linux x86_64 and redistributable?

### Takeaway
No Vietnamese CA (Viettel-CA, VNPT-CA, BKAV-CA, FPT-CA, MISA-CA, CA2, FastCA, VGCA and the rest) publishes a Linux PKCS#11 library or token manager. Their download pages are Windows-only, and VNPT-CA and Viettel-CA also offer macOS builds. The hardware under the CA branding is mostly OEM tokens, with Feitian ePass2003 (USB 096e:0807) the best evidenced, plus SafeNet and Bit4id for the government CA (VGCA). OpenSC's `epass2003` driver works only when the token was personalised as PKCS#15. ePass2003 tokens personalised with the Windows minidriver (MSCP) layout show up as "token not recognized" in every OpenSC release, and the upstream fix was still in review in Sept–Nov 2026. The only public report of a Vietnamese CA token working with OpenSC on Linux is one community project: FPT-CA ePass2003 on Arch, Sept–Nov 2026. OEM Linux middleware does exist (Feitian "Castle", SafeNet Authentication Client 10.9, Bit4id Universal Middleware). I found no redistribution licence for any of it, and no Vietnamese CA ships it.

### Cited Findings

#### Token families sold by Vietnamese CAs and the PKCS#11 modules they use on Windows
- Viettel-CA's official download page lists USB token drivers by generation: "USB Token Driver v1/v2 (patch)", "USB Token Hồng Tiễn V1", "USB Token V2…V5", "USB Token Secure V0" and "Plugin hỗ trợ đấu nối cho USB V6". It also lists Token Manager V2/V4/V5/V6 (V6 updated 31/10/2023), a "Token Manager V6 for MacOS" and "Phần mềm fix lỗi smartcard (CCID) for Token V4/V5". The page has no Linux, Ubuntu or .deb build and no Linux driver, and it names no OEM token model (ePass2003, SafeNet, Bit4id). — [Viettel-CA Tải về](https://viettel-ca.vn/tai-ve)
- VNPT-CA's download page offers "VNPT-CA Token Manager" for Windows x64, Mac x64 and Mac ARM64 (file timestamps 31/12/2025), plus "Driver Token v8" (22/08/2022), "DRIVER ETOKEN CHO HDH WINDOWS 64BIT/32BIT" and "DRIVER CYKENTOKEN CHO HĐH WINDOWS" (both 10/05/2019). It has no Linux, Ubuntu or .deb item and names no OEM model. — [VNPT-CA download page](https://vnpt-ca.vn/download-page)
- BkavCA's download page offers only Windows-style files (.exe/.zip): Bkav CA Token Manager, a Java 8u121 i586 plug-in, HTKK, iTaxViewer and CT SigningHub 1.1. It has no .deb, .dmg or .pkg and names no token hardware model. — [Bkav CA Tải về](https://bkavca.vn/tai-ve)
- Viettel's S-Invoice e-invoice guide lists the USB tokens its signing tool supports without manual configuration: Viettel-CA v1–v6, FPT-CA v2–v5, BKAV-CA v1–v2, Safe-CA v1–v2, Vina-CA v1/v3/v5, VNPT-CA v6/v8/v10, NewCA v4 and CA2 (no version given). For other tokens, the user copies the CA's DLL from `C:\Windows\System32` into `token.properties`. The page's examples are `efy-ca_v1.dll` and `efy-ca_v5_s.dll`. The page is undated; its URL path says 2020/11. — [sinvoice.vn guide](https://www.sinvoice.vn/2020/11/hdsd-cac-buoc-kiem-tra-ky-usb-token.html)
- The open-source Windows bridge hSignerBridge (MIT; repo created 2026-04-17, last push 2026-10-13) has a lookup table of Windows PKCS#11 DLLs for Vietnamese CA tokens in `src/Pkcs11KeyProvider.cs`. It lists: `viettel-ca.dll`, `viettel-ca_v1.dll`…`viettel-ca_v6.dll`; `vnpt-ca_v34.dll`, `vnpt-ca_v4.dll`, `vnpt-ca_csp11.dll`, `vnpt-ca_cl_v1.dll`, `vnptca_p11_v8.dll`, `vnptca_p11_v10.dll`; `fpt-ca.dll`, `fpt-ca_v4.dll`, `fpt-ca_v5.dll`; `BkavCA.dll`, `BkavCAv2S.dll`; `CA2_v34.dll`, `CA2_csp11.dll`; `misaca_csp11_v2.dll`; `ncca_csp11_v1.dll`; `newca_v4.dll`; `Safe-ca_v1.dll`, `Safe-ca_v2.dll`; `vina-ca_v1/v3/v5.dll`; `efy-ca_v1.dll`; `fca_v1.dll` (FastCA). Generic OEM modules in the same table: `eps2003csp11.dll` and `eps2003csp11v2.dll` (Feitian ePass2003), `ShuttleCsp11_3003.dll`, `eTPKCS11.dll` (SafeNet), `IDPrimePKCS1164.dll`, `bit4xpki.dll` (Bit4id), `acospkcs11.dll`, `WDPKCS.dll`. — [hSignerBridge Pkcs11KeyProvider.cs](https://github.com/haoquangviet/hSignerBridge/blob/HEAD/src/Pkcs11KeyProvider.cs); repo metadata from [GitHub API](https://api.github.com/repos/haoquangviet/hSignerBridge)
- hSignerBridge's README lists the tokens tested on Windows and the provider each one presents: ePass2003 → "EnterSafe CSP"; SafeNet eToken → SafeNet CSP/KSP; VNPT-CA → "VNPT-CA SmartCard CSP"; Viettel-CA V6 → Viettel-CA CSP/KSP, or PKCS#11 `viettel-ca_v6.dll` when a PIN is passed; FastCA → PKCS#11 `fca_v1.dll`. When no CA module matches, it falls back to OpenSC. — [hSignerBridge README](https://github.com/haoquangviet/hSignerBridge). Release v1.4.0 adds a PIN field and signing "qua PKCS#11 của hãng", tested on real Viettel-CA and FastCA tokens (snippet). — [hSignerBridge v1.4.0](https://github.com/haoquangviet/hSignerBridge/releases/tag/v1.4.0)
- `eps2003csp11.dll` is described as part of the "escsp11" library developed by EnterSafe and signed by Feitian Technologies (snippet). — [freefixer eps2003csp11.dll](https://www.freefixer.com/library/file/eps2003csp11.dll-262862/)
- FPT-CA tokens are Feitian ePass2003, according to the Linux community project fpt-signing-linux. It uses the OpenSC `epass2003` driver "over CCID/PC/SC" with module `/usr/lib/opensc-pkcs11.so` (Arch path). — [letieu/fpt-signing-linux](https://github.com/letieu/fpt-signing-linux)
- VGCA (Ban Cơ yếu Chính phủ, government CA): third-party guides say the older VGCA01 token uses the SafeNet Authentication Client driver and newer tokens use Bit4id drivers (snippet). — [hotrokyso: phần mềm cần cài](https://hotrokyso.com/cac-phan-mem-ky-so-can-phai-cai-dat-doi-voi-may-tinh-moi/), [hotrokyso: USB E-Token VGCA](https://hotrokyso.com/cai-dat-usb-e-token-v1/). A university helpdesk guide names the "Bit4ID" token driver and the vSignPDF signing tool (snippet). — [CTU helpdesk](https://helpdesk.ctu.edu.vn/vi/blog/huong-dan-su-dung-chu-ky-so-usb-token)

#### OpenSC support status for these tokens (2026)
- The OpenSC "Supported hardware" wiki page (last edited 2026-08-12) lists Feitian ePass2003, Feitian ePass3000, the Feitian PKI token, the Feitian FTCOSPK01C card and the Aladdin eToken Pro as supported. ACS ACOS5 is listed as unsupported. SafeNet eToken 5110/5300, the IDPrime family and Bit4id are not on the page. — [OpenSC wiki: Supported hardware](https://github.com/OpenSC/OpenSC/wiki/Supported-hardware-(smart-cards-and-USB-tokens))
- The OpenSC ePass2003 page (last edited 2024-05-07) says: "The driver of ePass2003 in OpenSC is called 'epass2003'." Tokens ship with default transport keys. Some users hit "Failed to erase card: Security status not satisfied"; the fix is Feitian's fix tool (x86/x64/armhf), see OpenSC #1803. — [OpenSC wiki: Feitian ePass2003](https://github.com/OpenSC/OpenSC/wiki/Feitian-ePass2003)
- OpenSC issue #3834 (opened 2026-09-19, open) is the key blocker for tokens personalised on Windows. The reporter writes: "Some FEITIAN ePass2003 tokens are not PKCS#15 cards, so OpenSC cannot use them." These tokens use a Microsoft minidriver (MSCP) layout with no DF 5015. Symptoms: `pkcs15-tool --list-certificates` → "PKCS#15 binding failed: Unsupported card", and `pkcs11-tool -L` → "Slot 0 (0x0): Feitian ePass2003 … (token not recognized)". USB ID 096e:0807, ATR `3b:9f:95:81:31:fe:9f:00:66:46:53:05:01:00:11:71:df:00:00:00:00:00:13`. "Reinitializing the token as PKCS#15 would erase the personalization and its certificates." The vendor PKCS#11 module works in Firefox. Maintainer Frank Morgner (2026-09-20): "Your approach sounds reasonable." The fix is PR #3835, "Add PKCS#15 emulator for MSCP-personalized ePass2003" (opened 2026-09-21, still open). The issue names no CA. — [OpenSC #3834](https://github.com/OpenSC/OpenSC/issues/3834), [OpenSC PR #3835](https://github.com/OpenSC/OpenSC/pull/3835)
- OpenSC issue #3878, "Feitian ePass2003 seems to not work on Linux, again" (opened 2026-10-14, open). The reporter is on Ubuntu 26.04 with OpenSC 0.27.0 rc1, where `pkcs15-init --create-pkcs15` fails with "Security status not satisfied"; initialisation worked on 0.25.0 rc1. A second reporter, with a BioPass variant (096E:0807), found that 0.26.1 works and 0.27.1 fails (PKCS#11 login `CKR_USER_NOT_LOGGED_IN`). The bisect points to commit fa313a8, "Removed internal caching for current EF/DF". The fix is PR #3892 (open). The maintainer noted that the Feitian vendor contact "has been unresponsive". — [OpenSC #3878](https://github.com/OpenSC/OpenSC/issues/3878), [PR #3892](https://github.com/OpenSC/OpenSC/pull/3892)
- Other ePass2003 issues opened in 2026, from a GitHub issue search:
  - #3900, "SM response with `87 81 01` fails to decode since 5ebb04ded (0.26.1 accepted it)" (2026-10-26, open)
  - #3920, "first signature through the Windows minidriver fails with 'wrong PIN'" (2026-11-02, open)
  - #3693, "epass2003 token login with SM fails since May 6" (closed 2026-05-28 via PR #3694)
  - #3544, "ePass2003 InitPIN failed" (2026-01-07 to 2026-01-29)
  - Sources: [OpenSC #3900](https://github.com/OpenSC/OpenSC/issues/3900), [#3920](https://github.com/OpenSC/OpenSC/issues/3920), [#3693](https://github.com/OpenSC/OpenSC/issues/3693), [#3544](https://github.com/OpenSC/OpenSC/issues/3544)
- The one confirmed Linux success with a Vietnamese CA token is the fpt-signing-linux README. It shows the FPT-CA ePass2003 detected with `opensc-tool -l`, `pkcs11-tool -L` and `pkcs11-tool --login -O`, and signing PDF/XML through OpenSC on Arch Linux. Repo created 2026-09-24, last push 2026-11-03, 0 stars, no licence file, no releases. — [letieu/fpt-signing-linux](https://github.com/letieu/fpt-signing-linux); metadata from [GitHub API](https://api.github.com/repos/letieu/fpt-signing-linux)

#### OEM Linux middleware (vendor PKCS#11 libraries)
- **Feitian ePass2003 "Castle" middleware for Linux.** A 2021-08-16 gist (Brazilian "Soluti ePass2003") installs `ePass2003-Castle-20141128.tar.gz`, obtained from a Google Drive link. Steps: run `x86_64/config/config.sh`, copy `libcastle.so.1.0.0` to `/usr/lib`, and link the `pkimanager_admin` tool. Chrome: `modutil -dbdir sql:.pki/nssdb/ -add "Soluti ePass2003" -libfile /usr/lib/libcastle.so.1.0.0`. Firefox: load `/usr/lib/libcastle.so.1.0.0` under Security Devices. The gist states no licence or redistribution terms. The tarball is dated 2014. — [alexishida gist](https://gist.github.com/alexishida/b00c805ba77f682952e11da98576909f). Indian DSC vendors also host "ePass2003 Drivers for Linux" x64/i386 (snippet; unofficial mirrors). — [radiumbox ePass/HYP2003 Linux](https://www.radiumbox.com/download/etoken-linux)
- **SafeNet Authentication Client (SAC) 10.9 for Linux.** Thales announced it on 2025-01-13: Debian support, external PIN-pad reader support, IDPrime 940B FIDO, and blocking conversion of unmanaged cards to managed (snippet). — [Thales announcement](https://data-protection-updates.gemalto.com/2025/01/13/safenet-authentication-client-sac-10-9-for-linux-and-safenet-authentication-client-sac-10-8-for-sdk-release-announcement/)
- Sources disagree on which Ubuntu releases SAC 10.9 supports (all snippets):
  - DigiCert: the 10.9 Linux GA supports Ubuntu 22.04 and 24.04.1, Debian 12.8 and Fedora 41. — [DigiCert KB](https://knowledge.digicert.com/general-information/how-to-download-safenet-authentication-client)
  - Sectigo: lists only Ubuntu 20.04/22.04, with the 10.9 GA Linux package dated 2025-12-11. — [Sectigo KB](https://www.sectigo.com/knowledge-base/detail/SafeNet-Authentication-Client-Download-for-Sectigo-Certificates-on-eToken)
  - GlobalSign: offers an "Ubuntu 24.04.4 v10.9" package. — [GlobalSign SafeNet drivers](https://support.globalsign.com/digital-certificates/manage-safeNet-eToken/safenet-drivers)
  - Arch AUR `sac-core` 10.9.6885-1 repackages the GlobalSign Ubuntu 24.04.4 zip for "eToken 5110/5300 & IDPrime". — [AUR sac-core](https://aur.archlinux.org/packages/sac-core?O=20)
  - Distribution is through CA partners' support portals; I found no public redistribution licence.
- **Bit4id Universal Middleware for Linux.** It ships as a `.deb` inside a zip and installs `/usr/lib/bit4id/libbit4xpki.so`; no extra reader driver is needed if PC/SC drivers are present (Catalan government AOC manual, snippet). — [AOC Bit4id per a Linux](https://suport-tcat.aoc.cat/hc/en-gb/articles/15108093608349-Manual-de-Bit4id-per-a-Linux). AUR has `bit4id-xpki` 1.4.10.682-2, and users with old cards may need `bit4id-ipki` (snippet). — [AUR bit4id-xpki](https://aur.archlinux.org/packages/bit4id-xpki), [AUR bit4id-ipki](https://aur.archlinux.org/packages/bit4id-ipki). Ubuntu's own snap tutorial uses `libbit4xpki.so` as its example vendor driver. — [Ubuntu Discourse: smart cards in snapped browsers](https://discourse.ubuntu.com/t/enable-smart-cards-in-snapped-browsers/57471)

#### USB vendor:product IDs (from usb.ids, version 2026.06.26) — [linux-usb.org usb.ids](http://www.linux-usb.org/usb.ids)
- Feitian (096e): 0807 ePass2003; 0702 ePass3003; 0703 ePass3003Auto; 0401 ePass3000; 0309 ePass3000GM; 0005 ePass2000; 0305 ePass2000Auto; 0802 ePass2000 (G&D STARCOS SPK 2.4); 0801 Token; 085a Multipass FIDO.
- Aladdin Knowledge Systems / SafeNet (0529): 0620 "Token JC"; 0600 eToken Pro 64k (4.2); 050c/0514 eToken Pro v4.x; 03xx/04xx eToken R1/R2. Aladdin R.D. (JaCarta) is 24dc.
- Bit4id (25dd): 1101 miniLector-s; 1201 cryptokey; 2321 CKey4; 2341 tokenME FIPS v3; 2351/2354/2362 Digital DNA Key; 2371 TokenME EVO v2; 3111 miniLector EVO; 3211 miniLector AIR EVO.
- ACS (072f): 90cc ACR38 SmartCard Reader; 9000 ACR38 AC1038; b100 ACR39U; b101 ACR39K; b102 ACR39T; b103 ACR39F; b106 ACOS5T2; b200 ACOS5T1; 2200 ACR122U.
- Gemalto (08e6) and Thales (142a, 1799) vendor entries also exist.
- The ePass2003 ID 096e:0807 is confirmed in two 2026 OpenSC reports, including a BioPass fingerprint variant. — [OpenSC #3834](https://github.com/OpenSC/OpenSC/issues/3834), [OpenSC #3878](https://github.com/OpenSC/OpenSC/issues/3878)

#### Ubuntu 24.04 (noble) packages and versions
All from Launchpad publishing records, read 2026-11-05.
- opensc / opensc-pkcs11 (universe): 0.25.0~rc1-1ubuntu0.2 in noble-updates/noble-security (published 2026-02-25); the release pocket has 0.25.0~rc1-1build2 (2024-04-04). Newer series: plucky 0.26.1-1 (2025-03-24), questing 0.26.1-3 (2025-09-08), resolute/26.04 0.27.0~rc1-1 (2026-02-28). — [packages.ubuntu.com noble/opensc](https://packages.ubuntu.com/noble/opensc), [Launchpad opensc](https://launchpad.net/ubuntu/+source/opensc)
- pcsc-lite / pcscd (main): 2.0.3-1build1. — [Launchpad pcsc-lite](https://launchpad.net/ubuntu/+source/pcsc-lite)
- ccid / libccid (universe in noble): 1.5.5-1. — [Launchpad ccid](https://launchpad.net/ubuntu/+source/ccid)
- p11-kit / p11-kit-modules (main): 0.25.3-4ubuntu2.2 in noble-updates/security (2026-08-27). — [Launchpad p11-kit](https://launchpad.net/ubuntu/+source/p11-kit)
- nss / libnss3, libnss3-tools (main): 2:3.98-1ubuntu0.3 in noble-updates/security (2026-10-21). — [Launchpad nss](https://launchpad.net/ubuntu/+source/nss)
- File lists (noble, amd64):
  - `opensc-pkcs11` ships `/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so` (also under `…/pkcs11/`), `onepin-opensc-pkcs11.so`, `pkcs11-spy.so` and the p11-kit registration `/usr/share/p11-kit/modules/opensc-pkcs11.module`. — [opensc-pkcs11 filelist](https://packages.ubuntu.com/noble/amd64/opensc-pkcs11/filelist)
  - `p11-kit-modules` ships `/usr/lib/x86_64-linux-gnu/p11-kit-proxy.so`, `pkcs11/p11-kit-client.so` and `pkcs11/p11-kit-trust.so`. — [p11-kit-modules filelist](https://packages.ubuntu.com/noble/amd64/p11-kit-modules/filelist)
  - `libnss3-tools` ships `/usr/bin/modutil`, `certutil` and `pk12util`. — [libnss3-tools filelist](https://packages.ubuntu.com/noble/amd64/libnss3-tools/filelist)
  - `pcscd` ships `pcscd.service` plus `pcscd.socket` (socket activation). — [pcscd filelist](https://packages.ubuntu.com/noble/amd64/pcscd/filelist)
  - `libccid` ships `/usr/lib/pcsc/drivers/ifd-ccid.bundle/Contents/{Info.plist,Linux/libccid.so}` and `/usr/lib/udev/rules.d/92-libccid.rules`. — [libccid filelist](https://packages.ubuntu.com/noble/amd64/libccid/filelist)
- CaramOS today: `config/packages.txt` lists none of opensc, pcscd, libccid, p11-kit or libnss3-tools, and no file under `config/` or `packages/caramos-ota/` mentions opensc, pcscd, pkcs11 or SecurityDevices (local grep of the CaramOS repo, 2026-11-05). — /home/dungleviet/Documents/CaramOS/config/packages.txt

### Inferences
- Vietnamese CA tokens look like rebranded OEM tokens with CA-specific middleware, one PKCS#11 DLL per token generation (`viettel-ca_v1…v6`, `vnptca_p11_v8/v10`, `fpt-ca_v4/v5` and so on). The Feitian ePass2003 is confirmed only for FPT-CA. The other OEMs are guesses from the generic DLLs in hSignerBridge's fallback list (Feitian, SafeNet, Bit4id, ACS, and probably Watchdata for `WDPKCS.dll`).
- Two signals suggest some VNPT-CA and Viettel-CA tokens use a Windows minidriver/CSP personalisation, which OpenSC cannot read until PR #3835 lands: hSignerBridge reports provider names like "VNPT-CA SmartCard CSP" and "Viettel-CA CSP/KSP", and #3834 describes MSCP-layout ePass2003 tokens. This is unconfirmed for any specific CA; no source tied #3834 to a Vietnamese CA.
- "Works with OpenSC out of the box" is therefore realistic only for:
  - (i) FPT-CA ePass2003 tokens, per one community report;
  - (ii) any ePass2003 the CA personalised as PKCS#15;
  - (iii) after PR #3835 merges and is backported, probably MSCP-personalised ePass2003 tokens too.
- Ubuntu 24.04's OpenSC 0.25.0~rc1 predates the 0.27-line regressions (#3878, #3900), so it is the safer base today. It also lacks the MSCP emulator, so a CaramOS backport would be needed once #3835 merges, and that backport would need the #3892/#3900 fixes.
- SafeNet-based tokens (VGCA01, possibly VNPT's "DRIVER ETOKEN") would need Thales SAC (`libeToken.so`). SAC has an Ubuntu 24.04 build, but it is proprietary and handed out by CA partners, so CaramOS would install it from an App Center recipe at most, not ship it. The same applies to Bit4id middleware for newer VGCA tokens, and to the Feitian Castle library, which has no stated licence.
- USB ID detection alone cannot identify the CA, or tell whether OpenSC will read the token: 096e:0807 is shared by every ePass2003 worldwide (Brazil, India, Vietnam). Driver Check could follow a USB-ID match with a PC/SC probe that reads the certificate issuer CN (e.g. "Viettel-CA", "VNPT-CA"). The "token not recognized" / "Unsupported card" strings from #3834 would flag MSCP-layout tokens.
- libccid and opensc are in Ubuntu's universe component on noble. Mint's default sources include Ubuntu universe, so this is not a blocker. That is general knowledge, not checked in this session.

### Gaps
- No public lsusb/ATR dumps for Vietnamese-branded tokens (Viettel-CA V1–V6, "Hồng Tiễn", VNPT-CA v6/v8/v10, "CykenToken", BKAV v1/v2, CA2, MISA-CA, EasyCA, NewCA, Safe-CA, Vina-CA). Their USB IDs and OEMs are undocumented beyond FPT-CA = ePass2003.
- EasyCA does not appear in hSignerBridge's DLL table, and I found no hardware information for EasyCA or MISA-CA beyond `misaca_csp11_v2.dll`. Whether `ncca_csp11_v1.dll` belongs to Nacencomm (CA2's operator) is unverified.
- Not verified this session: whether OpenSC's IDPrime driver covers eToken 5110 CC/FIPS. The supported-hardware page does not list it.
- I found no redistribution or licence terms for Feitian Castle, SafeNet SAC or Bit4id middleware, and no Vietnamese CA statement on Linux support.
- The VGCA download page (ca.gov.vn/tai-phan-mem) returned ECONNRESET, so the absence of a VGCA Linux build rests on third-party guides only.
- The CCID driver's supported-reader list could not be parsed (raw file 404, HTML grep failed), so per-model libccid support for these tokens is unconfirmed. fpt-signing-linux does state that ePass2003 runs over CCID/PC/SC.

## Q2. What exactly must be installed and configured so that Firefox and Chrome on Ubuntu 24.04 can use a token for signing and TLS client auth?

### Takeaway
On deb browsers, which is what Mint uses (Firefox .deb from Mint, Chrome .deb from Google), the documented recipe has three parts:
1. Install `pcscd` + `libccid` + `opensc-pkcs11` (and `opensc` for tools), or a vendor PKCS#11 `.so`, plus `libnss3-tools`.
2. Register the module with Firefox, either in Settings → Security Devices or system-wide through the Firefox `SecurityDevices` enterprise policy in `/etc/firefox/policies/policies.json` (Add/Delete form since Firefox 114).
3. Register it per user in Chrome/Chromium's NSS database with `modutil -dbdir sql:$HOME/.pki/nssdb -add …`.

`p11-kit-proxy.so` can stand in for the individual module so that every p11-kit-registered module shows up. Snap browsers need extra steps and still fail for some vendor modules; that matters little on Mint. Chrome's Local Network Access prompt (Chrome 141+) now gates the localhost-based signing plugins that Vietnamese portals use.

### Cited Findings

#### Packages and services
- Ubuntu's smart-card tutorial: if OpenSC supports the card, no separate driver is needed; otherwise install the vendor driver (example `/usr/lib/libbit4xpki.so`). Chromium needs `sudo apt install libnss3-tools` and then `modutil -dbdir sql:.pki/nssdb/ -add "OpenSC" -libfile /usr/lib/x86_64-linux-gnu/opensc-pkcs11.so`; a vendor module is added the same way, e.g. `-add "Bit4id" -libfile …/libbit4xpki.so`. The tutorial covers "smart-card authentication and signing". Posted 2025-03-19 by Marek Suchánek, reply 2025-03-26; it says it has since been replaced by a guide in the product documentation. — [Ubuntu Discourse tutorial](https://discourse.ubuntu.com/t/enable-smart-cards-in-snapped-browsers/57471)
- The fpt-signing-linux setup, on Arch, installs pcsclite, ccid and opensc, enables `pcscd`, and verifies with `opensc-tool -l`, `pkcs11-tool -L` and `pkcs11-tool --login -O`. — [letieu/fpt-signing-linux](https://github.com/letieu/fpt-signing-linux)
- Ubuntu module paths: `/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so` and `/usr/lib/x86_64-linux-gnu/p11-kit-proxy.so`. `pcscd` is socket-activated (`pcscd.socket`). — [opensc-pkcs11 filelist](https://packages.ubuntu.com/noble/amd64/opensc-pkcs11/filelist), [p11-kit-modules filelist](https://packages.ubuntu.com/noble/amd64/p11-kit-modules/filelist), [pcscd filelist](https://packages.ubuntu.com/noble/amd64/pcscd/filelist)

#### Firefox (deb)
- Manual route: Settings → Privacy & Security → Security Devices → Load → enter the module filename. The tutorial gives `/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so` and says: "Do not use the Browse button." That warning is snap-specific, because the file picker rewrites the path. — [Ubuntu Discourse tutorial](https://discourse.ubuntu.com/t/enable-smart-cards-in-snapped-browsers/57471)
- Policy route (system-wide): policy `SecurityDevices`, "Add or delete PKCS #11 modules", with `{"policies": {"SecurityDevices": {"Add": {"NAME_OF_DEVICE_TO_ADD": "PATH_TO_LIBRARY_FOR_DEVICE"}, "Delete": ["NAME_OF_DEVICE_TO_DELETE"]}}}`. The docs give its compatibility as "Firefox 114, Firefox ESR 112.12". The older flat form, "SecurityDevices (Deprecated)", dates from Firefox 64 / ESR 60.4. On Linux, `policies.json` goes in `firefox/distribution` under the install directory, "or you can specify system-wide policy by placing the file in `/etc/firefox/policies`". — [Mozilla policy-templates docs](https://github.com/mozilla/policy-templates/blob/master/docs/index.md) (also at [mozilla.github.io/policy-templates](https://mozilla.github.io/policy-templates/))
- `ImportEnterpriseRoots` (trusting the OS certificate store): "This policy only works on Windows and macOS. For Linux discussion, see bug 1600509." — [Mozilla policy-templates](https://mozilla.github.io/policy-templates/)

#### Chrome / Chromium (deb)
- Chrome and Chromium on Linux find modules through the per-user NSS database `sql:$HOME/.pki/nssdb`, where `modutil` registers them. — [Ubuntu Discourse tutorial](https://discourse.ubuntu.com/t/enable-smart-cards-in-snapped-browsers/57471); same pattern for a vendor module in the [ePass2003 gist](https://gist.github.com/alexishida/b00c805ba77f682952e11da98576909f) (`modutil -dbdir sql:.pki/nssdb/ -add "Soluti ePass2003" -libfile /usr/lib/libcastle.so.1.0.0`, then `modutil … -list`)

#### p11-kit proxy
- The p11-kit proxy module "acts like a normal PKCS#11 module, but internally loads a preconfigured set of PKCS#11 modules", exposes each of their slots, and "can be loaded by crypto libraries like NSS and behaves as expected". — [p11-kit manual: sharing](https://p11-glue.github.io/p11-glue/p11-kit/manual/sharing.html)
- On Ubuntu, `opensc-pkcs11` registers itself with p11-kit through `/usr/share/p11-kit/modules/opensc-pkcs11.module`. — [opensc-pkcs11 filelist](https://packages.ubuntu.com/noble/amd64/opensc-pkcs11/filelist)

#### Snap and Flatpak
- LP #1967632, "[snap] apparmor denied when trying to load pkcs11 module for smart card authentication", opened 2022-04-02. Its tasks were still Confirmed (firefox snap) and Triaged (firefox and chromium-browser in Ubuntu) at the last update on 2026-06-15; it concerns vendor modules blocked by AppArmor `file_mmap`. — [LP #1967632](https://bugs.launchpad.net/bugs/1967632)
- LP #2089141, "Opensc smart cards do not work in the snapped browsers": Fix Released for firefox (2024-11-20) and chromium-browser (2024-11-25). — [LP #2089141](https://bugs.launchpad.net/ubuntu/+source/chromium-browser/+bug/2089141)
- Snap steps from the tutorial (2025-03-19):
  - Connect pcscd: `sudo snap connect firefox:pcscd` or `sudo snap connect chromium:pcscd`.
  - Copy vendor `.so` files into `~/snap/firefox/common/` or `~/snap/chromium/common/`.
  - Debug a vendor module with `snap run --shell firefox -c ldd …`.
  - Third-party drivers are "experimental and unsupported".
  - Source: [Ubuntu Discourse tutorial](https://discourse.ubuntu.com/t/enable-smart-cards-in-snapped-browsers/57471)
- A later Ubuntu Community Hub thread reports the same `file_mmap` denial on Ubuntu 26.04 with Firefox 151, with the path rewritten under `/run/user/…/doc/` by the document portal (snippet; about mid-2026). — [Ubuntu Community Hub thread](https://discourse.ubuntu.com/t/firefox-snap-cannot-load-pkcs-11-modules-opensc-dnie-due-to-apparmor-file-mmap-denial/84009). Upstream: [Mozilla bug 1734371](https://bugzilla.mozilla.org/show_bug.cgi?id=1734371) (snippet)
- The Flathub Chrome tracker has a related issue (not read). — [flathub/com.google.Chrome#209](https://github.com/flathub/com.google.Chrome/issues/209)

#### Chrome Local Network Access (affects localhost signing plugins)
- Chrome's Local Network Access defines a `loopback-network` permission for requests from a public origin to `localhost`, `127.0.0.1` or `[::1]`. `ws://` WebSocket connections to loopback are "gated by the permission prompt". The guide's advice for companion apps is to run a loopback service, request it with `targetAddressSpace: 'loopback'`, and show remediation UI on failure. — [Chrome LNA guide](https://developer.chrome.com/docs/modern-web-guidance/guides/security/local-network-access)
- Chrome 141 shipped on 2025-09-30 with the LNA prompt. Admins can allowlist page origins with the `LocalNetworkAccessAllowedForUrls` policy (vendor docs, snippet). — [Beyond Identity: Chrome v141 LNA prompt](https://support.beyondidentity.com/hc/en-us/articles/40664638786455-Managing-the-Chrome-v141-local-network-access-prompt)
- hSignerBridge: "Chrome/Edge 141+ block WebSocket to localhost", so it uses HTTPS `POST /rpc`. Users must grant "Local network access", and a public domain pointing to 127.0.0.1 does not bypass this. — [hSignerBridge README](https://github.com/haoquangviet/hSignerBridge)
- Vietnamese e-tax support pages fix the "Chưa bật plugin chữ ký số" error by changing a Chrome flag related to Local Network Access Checks and relaunching. This comes from a search-result summary covering pages such as eca.com.vn; the exact page and date were not confirmed. — [eca.com.vn](https://eca.com.vn/tin-tuc/sua-loi-chua-bat-plugin-chu-ky-so-tren-trang-thue-dien-tu)

### Inferences
- A minimal CaramOS recipe for OpenSC-readable tokens, not tested on hardware:
  1. `apt install pcscd libccid opensc opensc-pkcs11 libnss3-tools`.
  2. Ship `/etc/firefox/policies/policies.json` with `"SecurityDevices": {"Add": {"OpenSC": "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so"}}`, or point it at `p11-kit-proxy.so`. Mint's Firefox is far newer than 114, so the Add/Delete form applies.
  3. For Chrome/Chromium, run `modutil -dbdir sql:$HOME/.pki/nssdb -add …` per user, e.g. in a first-login or caramos-ota migration step, and optionally pre-seed `/etc/skel/.pki/nssdb`.
- "ESR 112.12" in Mozilla's compatibility line matches no real ESR branch (the ESRs are 102 and 115); it is probably a typo for 102.12.
- Because `ImportEnterpriseRoots` does not work on Linux, Firefox must get any Vietnamese CA root or intermediate certificates the sites need from Firefox's own policies (`Certificates` → `Install`) or its NSS DB, not from the OS store. The tokens usually carry the chain too; not verified.
- Registering `p11-kit-proxy.so` once in each browser would let App Center vendor-driver recipes add modules by dropping a `.module` file, without touching browser configuration. Two risks: the same token appears twice if both proxy and OpenSC are registered, and vendor modules that misbehave under p11-kit would affect every consumer. The p11-kit page I read did not state the configuration directories; Ubuntu's own `.module` path is verified.
- Not verified: the Mozilla docs do not say whether `/etc/firefox/policies/policies.json` overrides a `distribution/policies.json` that Mint may ship; if both exist, CaramOS must check which one wins.
- I found no Chrome enterprise policy for registering PKCS#11 modules on Linux, so per-user NSS DB edits look unavoidable for Chrome. modutil generally warns against changing the DB while the browser runs, which is general knowledge, not verified here.
- For TLS client auth, nothing beyond module registration is needed in either browser; Chrome shows its client-certificate picker from NSS. This is general knowledge, not tested. No Vietnamese portal using TLS client-certificate login was found; they sign through plugins.
- Because the LNA prompt gates localhost plugins, CaramOS could ship a Chrome managed policy (`/etc/opt/chrome/policies/managed/*.json`) that allowlists the main Vietnamese portals (tax, social insurance, e-invoice, public services) under `LocalNetworkAccessAllowedForUrls`. That only matters if a Linux-capable local signing service exists. The policy name comes from a vendor source and should be checked against Chrome's policy list.

### Gaps
- Not checked: whether Linux Mint 22.3 already installs pcscd, libccid or opensc by default. There was no extracted rootfs under `build/` in the repo.
- The Flatpak status (Chrome and Firefox on Flathub with pcscd and PKCS#11) is unverified; flathub issue #209 was not read.
- No source covers how NSS-based browsers behave with proprietary Vietnamese CA modules on Linux, because none exist.

## Q3. Which Vietnamese signing plugins/extensions have a Linux native host, and how are they installed?

### Takeaway
None of the official ones. VNPT-CA Plugin, Viettel-CA Signer Plugin / Token Manager / MySign Desktop, BKAV tools, the tax authority's eSigner, VGCA Sign Service and Thái Sơn's e-invoice extension all target Windows, some also macOS. The only Linux-native Vietnamese signing helper found is fpt-signing-linux (Sept–Nov 2026): a community Node.js daemon on `127.0.0.1:35317` for FPT-CA ePass2003 tokens, with no licence. Most Vietnamese plugins are localhost WebSocket/HTTP services, not WebExtension native-messaging hosts. Thái Sơn's "Einvoice Signing" is an exception, using the native host `com.tsd.einvoice`.

### Cited Findings
- **VNPT-CA Plugin.** The product page says "Cài đặt dễ dàng trên các nền tảng Windows, Mac OS". It offers VNPTCA-Plugin 1.0.2.7 (Windows) and VNPTCA-Plugin Mac OS 1.0.1.0, and does not mention Linux or how the plugin works. — [kyso.vnpt-ca.vn](https://kyso.vnpt-ca.vn/). Version history: 1.0.0.9 (06/02/2018), 1.0.1.8 (20/08/2020), 1.0.1.9 (27/10/2020), 1.0.2.1 (30/03/2022), 1.0.2.2 (13/07/2022), 1.0.2.7 (26/02/2024). — [VNPT-CA plugin versions](https://kyso.vnpt-ca.vn/Authen/PluginVersion?product=2)
- **Viettel-CA.** The download page has "Viettel CA Signer Plugin 1.1.0.0", "ViettelCA Plugin Signer", "ESigner 1.0.8" (tax), "Signofline" (PDF), "kyofflinexml" (XML), Java runtimes for tax and VNACCS, Token Manager V6 for macOS, and "Mysign Desktop bản MacOS ver 1.7.2" (`mysigndesktop_macos_1.7.2_r260913.zip`). It names no Linux build, browser extension or native host. — [Viettel-CA Tải về](https://viettel-ca.vn/tai-ve). The MySign Desktop manual v1.4.3, whose file name suggests 2024-12-26, states "Hệ điều hành hỗ trợ: Windows" (snippet). — [MySign Desktop HDSD (UTT mirror)](https://itc.utt.edu.vn/wp-content/uploads/2025/03/HDSD_VTT_PMVT_QT06_20009_CA_Windows_1.4.3_241226.pdf). The macOS 1.7.2 build now on the download page supersedes that Windows-only statement. Neither source mentions Linux.
- **Tax authority eSigner (thuedientu.gdt.gov.vn).** Guides describe installing eSigner (1.0.8 / 1.0.9 / 1.1.0) and the browser add-on "ESigner.chrome.TCT". The installed program is `C:\Program Files (x86)\eSigner Java\eSigner.exe`. No Linux instructions were found (snippets). — [vin-hoadon.com](https://www.vin-hoadon.com/blog/18/huong-dan-xuat-hoa-don-gtgt-giam-10-phan-tram-xuong-8-phan-tram), [dtechvn.com eSigner 1.0.9 (2022-09-23)](https://www.dtechvn.com/phan-mem-esigner-1-0-9-23-09-2022-moi-nhat-cho-trang-thue-dien-tu-thuedientu-gdt-gov-vn.html), [Viettel-CA eTax tool guide](https://viettel-ca.vn/ho-tro/viettelca/huong-dan-su-dung/huong-dan-cai-dat-cong-cu-ky-so-tren-he-thong-etax-cua-tong-cuc-thue-)
- **VGCA (government).** VGCA Sign Service 2.0.42.0 is listed as the latest version, with the download portal at `mpki2.ca.gov.vn/downloads-vgca` (snippet). — [tinhocungdung.edu.vn](https://www.tinhocungdung.edu.vn/p/download-ung-dung.html). Installation guides use `VGCASignServiceSetup.msi`, vSignPDF and VGCA Token Manager, all Windows (snippets). — [huuthuan.net](https://huuthuan.net/cach-cai-dat-chu-ky-so-vgca.html), [hotrokyso.com](https://hotrokyso.com/phan-mem-ky-so-tu-ban-co-yeu/)
- **BKAV.** Windows tools only: Token Manager, CT SigningHub 1.1, Java 8u121 i586. — [Bkav CA Tải về](https://bkavca.vn/tai-ve)
- **Thái Sơn "Einvoice Signing" Chrome extension.** ID `jedojckniofllhnphffhlhhobpiloaok`, v2.0.7, about 100K users, "Plugin cài đặt vào trình duyệt Chrome/Cốc Cốc". It "Communicates with native messaging host (com.tsd.einvoice) to access USB token hardware", has permissions `nativeMessaging` and `scripting`, and targets einvoice.vn and einvoice.com.vn. The host's OS support is not documented. — [ExtScope listing](https://extscope.org/extension/jedojckniofllhnphffhlhhobpiloaok)
- **Community, Linux: fpt-signing-linux.** It is "extracted from the FPT USB Signing Tool" and runs "không cần Electron hay máy ảo Windows". An Express server listens on `http://127.0.0.1:35317`, the target sites are "các cổng thuế / hóa đơn điện tử FPT e-Invoice" in Chrome, Firefox and Brave, and a CLI `node cli-sign.js` produces PDF (PAdES / PKCS#7 detached) and XML (XMLDSig) signatures. Installation is git clone + `npm install` + an optional systemd user unit `fpt-signing.service`. The PIN is set in `config.json` or `TOKEN_PIN`; the example stores it in plain text. No licence, 0 stars, no releases. — [letieu/fpt-signing-linux](https://github.com/letieu/fpt-signing-linux)
- **Community, Windows only: hSignerBridge** (MIT; Pkcs11Interop 5.3.0, Apache-2.0). It needs .NET 8 Desktop Runtime, listens on `wss://localhost:9505`, falls back to `ws://localhost:9506` or HTTPS `POST /rpc`, uses a self-signed root CA, and is embedded on web pages via `pdfsignclient.js`. No Linux build. — [hSignerBridge](https://github.com/haoquangviet/hSignerBridge)
- **Native-messaging manifest locations on Linux:**
  - Chrome: `/etc/opt/chrome/native-messaging-hosts/<name>.json` (system), `~/.config/google-chrome/NativeMessagingHosts/` (user).
  - Chromium: `/etc/chromium/native-messaging-hosts/`, `~/.config/chromium/NativeMessagingHosts/`.
  - Sources: [Chrome native messaging docs](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging)
  - Firefox: `/usr/lib/mozilla/native-messaging-hosts/<name>.json`, `/usr/lib64/mozilla/native-messaging-hosts/<name>.json`, `~/.mozilla/native-messaging-hosts/<name>.json`. — [MDN Native manifests](https://developer.mozilla.org/en-US/docs/Mozilla/Add-ons/WebExtensions/Native_manifests)

### Inferences
- Most Vietnamese portal integrations talk to a local service (WebSocket/HTTP on localhost), so a Linux replacement has to mimic each vendor's local API: port, message format, TLS certificate. fpt-signing-linux does this for FPT only. A WebExtension native host would not help, because the portals' JavaScript expects the local service.
- eSigner for the tax portal is a Java program. A Linux port with SunPKCS11 plus OpenSC or a vendor `.so` looks technically plausible, but none exists publicly.
- For an App Center, the only installable Vietnamese item found is fpt-signing-linux. It has no licence (default copyright, so CaramOS may not redistribute it) and stores the PIN in plain text. At most it could be pointed to, not packaged.
- If a vendor ever ships a Linux host, the App Center recipe would drop its manifest into the three system paths above and a `.module` file for p11-kit.

### Gaps
- Not determined: the local ports and protocols used by the VNPT-CA Plugin, the Viettel-CA Signer Plugin, VGCA Sign Service and eSigner; none of the pages read documents them.
- Not found: whether Thái Sơn's `com.tsd.einvoice` host has any non-Windows build.
- Not found: any Linux build of MISA's signing tools (MISA eSign / meInvoice plugin) or of the CA2, EasyCA, NewCA and FastCA plugins; their download pages were not read.
- Not confirmed: whether the newer eTax portal or the social-insurance and public-services portals accept remote signing (SmartCA/MySign) with no desktop helper, which would make them usable from Linux.

## Q4. What do Vietnamese Linux users report as the remaining blockers?

### Takeaway
Public Vietnamese reports are scarce and mostly old. I found nothing on voz.vn, tinhte.vn or viblo.asia after 2013 about signing on Linux; the conversation likely lives in Facebook and Zalo groups, which are not searchable. The documented blockers are:
- Windows-only CA middleware and plugins;
- Java- and .NET-based tax tools: HTKK under Wine half-worked in 2010 and then froze; no recent success reports;
- tokens personalised in a layout OpenSC cannot read, plus OpenSC 0.27 regressions;
- snap confinement, irrelevant on Mint;
- Chrome's 2025 localhost restrictions, which also hit Windows users.

Remote signing (VNPT SmartCA, Viettel MySign, MISA eSign, Bkav RS) is the CAs' token-free path, but whether it works from a Linux browser without a desktop helper is unconfirmed.

### Cited Findings
- **HTKK on Ubuntu 10.04 with Wine 1.2 (blog post, 2010-05-25).** Registering `fpSpru70.ocx` failed. After a reinstall HTKK opened, but entering the tax ID (MST) froze the UI without an error. The author's verdict: it runs fine on Windows "chỉ có điều nó chưa chịu chạy trên Linux thông qua Wine" (snippet). — [zxc232.wordpress.com](https://zxc232.wordpress.com/2010/05/25/th%E1%BB%AD-ch%E1%BA%A1y-ph%E1%BA%A7n-m%E1%BB%81m-h%E1%BB%97-tr%E1%BB%A3-ke-khai-thu%E1%BA%BF-tren-ubuntu-10-04/)
- **Webketoan forum, HTKK 1.3.1.** On Ubuntu with Wine it installs but does not run, and another user notes the tax authority only ships Windows software (snippet; thread date not shown, HTKK 1.3.1 era). — [webketoan thread](https://webketoan.com/threads/58184-phan-mem-htkk-phien-ban-1-3-1-chay-duoc-tren-nhung-os-nao/)
- **Tinhte thread.** A member claims to have run HTKK on Linux via Wine, without details (snippet). — [tinhte.vn thread p.4](https://tinhte.vn/thread/thu-thuat-cai-dat-ung-dung-game-win-tren-linux.1718278/page-4)
- **Current HTKK distribution.** BkavCA's page still bundles HTKK as a zip; the link file is v4.5.7, though the title says 3.8.6. CA pages also still bundle Java 7/8 runtimes for tax and customs signing (Viettel-CA: Java 8u121, 7u80, JDK 6u37/6u45 for VNACCS). — [Bkav CA Tải về](https://bkavca.vn/tai-ve), [Viettel-CA Tải về](https://viettel-ca.vn/tai-ve)
- **Java is a recurring failure cause even on Windows.** MISA says the "Tệp tờ khai chưa được ký điện tử" error usually comes from a missing or incompatible Java (snippet). — [MISA eSign: lỗi chữ ký số](https://esign.misa.vn/336/loi-khi-su-dung-chu-ky-so/)
- **Token readability on Linux.** Covered under Q1: MSCP-personalised ePass2003 tokens are unreadable in OpenSC (#3834, Sept 2026); 0.27.x has regressions (#3878, #3900, Oct 2026); Feitian's vendor contact is unresponsive (#3878). — [OpenSC #3834](https://github.com/OpenSC/OpenSC/issues/3834), [OpenSC #3878](https://github.com/OpenSC/OpenSC/issues/3878)
- **The one Linux success story** (FPT-CA ePass2003, OpenSC, Arch) needed a reverse-engineered daemon in place of FPT's Electron tool. — [letieu/fpt-signing-linux](https://github.com/letieu/fpt-signing-linux)
- **Chrome 141+ Local Network Access** breaks localhost signing plugins until the user grants permission or flips a flag; Vietnamese support pages already document this. — [hSignerBridge README](https://github.com/haoquangviet/hSignerBridge), [eca.com.vn](https://eca.com.vn/tin-tuc/sua-loi-chua-bat-plugin-chu-ky-so-tren-trang-thue-dien-tu) (snippet)
- **Remote signing exists and is token-free:**
  - VNPT publishes a "VNPT SmartCA RS CPS" (05/12/2025). — [VNPT-CA download page](https://vnpt-ca.vn/download-page)
  - Viettel-CA publishes "Remote Signing 2023" certificate bundles and a MySign app. — [Viettel-CA Tải về](https://viettel-ca.vn/tai-ve)
  - BkavCA lists an "RS 2022–2027" certificate. — [Bkav CA Tải về](https://bkavca.vn/tai-ve)
  - VNPT SmartCA is marketed as needing no token or HSM on the customer side (snippet). — [accgroup.vn SmartCA](https://accgroup.vn/vnpt-chu-ky-so-tu-xa)
  - MISA markets eSign as signing e-invoices from a smartphone without a USB token (snippet). — [meinvoice.vn tag](https://www.meinvoice.vn/wp-tag/chu-ky-so-khong-can-usb-token/)
  - A 2020 headline: "Vietnam announces first digital signature without USB token" (title only; not opened). — [VTV English, 2020-02-18](https://english.vtv.vn/news/vietnam-announces-first-digital-signature-without-usb-token-20200218172436484.htm)

### Inferences
- The realistic order of options for a CaramOS user today:
  1. Remote signing, where the portal or the e-invoice vendor supports it in the browser.
  2. OpenSC with a PKCS#15-personalised ePass2003 for tools that take a PKCS#11 module or NSS (LibreOffice/Okular PDF signing, Firefox/Chrome TLS). Vietnamese portals still need their vendor's localhost plugin, which does not exist on Linux.
  3. A Windows VM with USB passthrough for HTKK, ECUS, MISA SME and CA token managers. This is untested here and no reports were found.
- Wine looks like a poor bet: the only concrete HTKK report (2010) failed at data entry, and modern HTKK, ECUS and MISA SME depend on .NET, SQL Server (for ECUS and MISA SME) and the vendor CSP/KSP middleware, which Wine's smart-card stack would have to bridge. This is general knowledge, not tested.
- Driver Check messaging should not promise that a token will work after OpenSC is installed. It should separate "token detected and readable", "token detected but not readable (MSCP layout) — use remote signing or a VM", and "vendor driver required (SafeNet/Bit4id)".

### Gaps
- No reports from 2014–2026 by Vietnamese users signing tax filings, e-invoices or social-insurance declarations on Ubuntu or Mint turned up via web search. voz, tinhte and viblo searches returned unrelated results.
- No reports of ECUS, MISA SME.NET or CA token managers under Wine or in a Windows VM, with or without USB passthrough, were found.
- Not confirmed: whether the tax portal's newer eTax flow, BHXH declaration portals (e.g. VNPT-BHXH, iBHXH) and dichvucong.gov.vn work from Linux with remote signing; this needs hands-on testing.
- No official statement from any Vietnamese CA on Linux support or plans was found.
