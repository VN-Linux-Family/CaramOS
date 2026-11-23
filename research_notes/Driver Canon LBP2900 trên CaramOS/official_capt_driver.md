# Canon's official CAPT driver (v2.71) for the Canon LBP2900 / LBP2900B on Ubuntu 24.04 "noble" amd64 (CaramOS 1.3.6 = Linux Mint 22.3)

Research date: 2026-11-08. Marking: **[V]** = I checked it myself on 2026-11-08 by downloading Canon's archive from the official Canon URL and inspecting it without installing (`tar -t`, `dpkg-deb -I/-c/-e/-x`, `file`, `readelf -d`, `strings`), or by reading the Ubuntu archive indexes or the Linux Mint 22.3 base rootfs that the CaramOS build uses (`/home/dungleviet/Documents/CaramOS/build/cache`, os-release "Linux Mint 22.3 (Zena)", HWE kernel 6.14.0-37). Anything not marked [V] is what the cited source says.
Local copies for anyone who wants to check again: archive `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/official/asia-gds-0100004596-05/linux-capt-drv-v271-uken.tar.gz`, extracted tree `.../official/extract-v271/`, unpacked amd64 debs `.../official/root-v271-amd64/`, maintainer scripts `.../official/ctrl-v271/`.

## 1. Latest official version, release date, official download URLs, file, size, checksums; still available in 2026?

### Takeaway
The only current Canon Linux driver for the LBP2900/LBP2900B is **"CAPT Printer Driver for Linux V2.71"** (packages `cndrvcups-capt 2.71-1` + `cndrvcups-common 3.21-1`), dated **15 May 2017**. Nothing newer exists. On 2026-11-08 it can still be downloaded from Canon's CDN as `linux-capt-drv-v271-uken.tar.gz` (127,521,219 bytes, SHA-256 `8565a2fd…41be`). The bytes are identical to what the Arch AUR has pinned.

### Cited Findings
- Canon Asia (Canon Singapore) page: title "CAPT Printer Driver for Linux V2.71", "Last Updated 15-May-2017", "Size 121.61 MB", "Issue Number 0100459601", file name `linux-capt-drv-v271-uken.tar.gz`, file version V2.71, OS "Linux 32bit / Linux 64bit", language English. "LASER SHOT LBP2900/ 2900B" is in the supported-model list, next to LBP3300/3310/3050/3150/5050/3250/3108/3018/3500/7200Cd/6018B/5000/5300/5100/9100Cdn/7018C/3000/6300dn/6000/6200d. No checksum is published. — [Canon Asia 0100459601](https://asia.canon/en/support/0100459601)
- Canon Vietnam serves the same item: same issue number, same file name, same 121.61 MB, "15-thg 5-2017", and the disclaimer in Vietnamese. — [Canon Vietnam 0100459601](https://vn.canon/vi/support/0100459601)
- [V] The "Download" button on the Asia page (and on the Vietnam page) points to `https://pdisp01.c-wss.com/gdl/WWUFORedirectTarget.do?id=MDEwMDAwNDU5NjA1&cmp=ACB&lang=EN`. The `id` is base64 for `010000459605`, i.e. content 0100004596, revision 05. That URL answers **HTTP 302 → `https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz`**. — [Canon Asia 0100459601](https://asia.canon/en/support/0100459601); [direct file](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Response for the file on 2026-11-08: HTTP 200 over both https and http, `content-length: 127521219` (= 121.61 MiB), `content-type: application/x-gzip`, `server: AmazonS3` behind CloudFront (POP HAN50), `last-modified: Mon, 31 Mar 2025 00:59:43 GMT` (a 2025 re-upload of unchanged bytes, see the next line), `etag: "f049b13624e3d0186d8e04004af70a75-25"`. — [direct file](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Checksums of the download:
  SHA-256 `8565a2fdc4f452bb8cf97ceadadd6614d12eac73e253ac6d59e61b8abae941be`;
  MD5 `2421628aac9c6000d08c46a1204f08be`;
  SHA-512 `e8a398afbc073f1fd1eeb3b4f7806a565c1a47c4cc801208a14f42379a3ca67156b9e640010c524778df894f631e8b4399ca691454eef60e7d6174bdb87f92ce`;
  BLAKE2b `10d1b76865f2e3ea8f974191cc7967d3969ce144a03b971945eb292ec2a3e78bf40ce53b921b5cab9b1da14a218aac9b946d4526e5e4e860f5eb4ab172e4e2a2`. The BLAKE2b is **identical** to the `b2sums` entry in the AUR capt-src PKGBUILD, which uses the same `http://gdlp01.c-wss.com/gds/6/0100004596/05/…` URL. — [AUR capt-src PKGBUILD](https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=capt-src)
- [V] Build dates inside the archive: gzip header mtime "Thu May 11 07:30:30 2017"; tar members dated 2017-04-17; files inside the debs dated 2017-04-07. `changelog.Debian` top entry: "cndrvcups-capt (2.71-1) stable … Thu, 9 Mar 2017". The changelog history runs 1.50-1 (2007-04-10, "Initial Release"), 1.50-2, 1.60, 1.70, 1.80, 1.90, 2.00, 2.20, 2.30, 2.40, 2.50, 2.56, 2.60, 2.70, 2.71. — [direct file](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Archive layout, sizes in bytes:
  `32-bit_Driver/Debian/cndrvcups-capt_2.71-1_i386.deb` 9,716,256;
  `32-bit_Driver/Debian/cndrvcups-common_3.21-1_i386.deb` 15,382,368;
  `32-bit_Driver/RPM/cndrvcups-capt-2.71-1.i386.rpm` 9,879,361;
  `32-bit_Driver/RPM/cndrvcups-common-3.21-1.i386.rpm` 15,356,845;
  `64-bit_Driver/Debian/cndrvcups-capt_2.71-1_amd64.deb` 9,733,334 (SHA-256 `6f4a7a6dc38987193ca96dc8a0418c655d921528061d926464b5a751449a5137`);
  `64-bit_Driver/Debian/cndrvcups-common_3.21-1_amd64.deb` 15,389,756 (SHA-256 `e0841c7384351f63f185d3149909b176f08fb4f761fc1e63a22f8e7e343b9bf6`);
  `64-bit_Driver/RPM/…x86_64.rpm` (two files);
  `Doc/LICENSE-EN.txt` 25,836; `Doc/README-capt-2.71UK.txt` 42,884; `Doc/guide-capt-2.7xUK.tar.gz` 627,860 (HTML manual);
  `Src/cndrvcups-capt-2.71-1.tar.gz` 10,031,685 (MD5 `5c1b42719d5b6f6bbd4064dfa4f2f808`); `Src/cndrvcups-common-3.21-1.tar.gz` 17,277,148 (MD5 `b95c88bc19162653b2949581c5cf636b`). — [direct file](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- Canon Asia's LBP2900/2900B model page lists exactly one Linux item, "CAPT Printer Driver for Linux V2.71" (15 May 2017, 121.61 MB, 0100459601). The other entries are Windows CAPT drivers (R1.50 Ver.3.30, and Win98/Me packages). — [Canon Asia LBP2900 model page](https://asia.canon/en/support/LASER%20SHOT%20LBP2900__%202900B/model?type=)
- Canon Europe's i-SENSYS LBP2900 page answered HTTP 403 to both WebFetch and curl, so I could not verify it. A search-engine summary says it lists V2.71 (15 May 2017) plus older Linux CAPT 1.60, 1.80, 2.00 and 2.20 for Linux 32/64-bit. — [Canon Europe LBP2900](https://canon-europe.com/support/consumer_products/products/printers/laser/i-sensys_lbp2900.html) (unverified)
- The Canon Japan legacy page `cweb.canon.jp/drv-upd/lasershot/linux/captlinux.html` (search title "CAPT Printer Driver for Linux Ver.2.71(32bit&64bit)") no longer resolves in DNS (checked 2026-11-08). — [Canon Japan legacy URL](https://cweb.canon.jp/drv-upd/lasershot/linux/captlinux.html)
- SlackBuilds takes the two Src tarballs from a third-party mirror (`http://mirror.slackware.hr/sources/canon/cndrvcups-capt-2.71-1.tar.gz`, MD5 `5c1b42719d5b6f6bbd4064dfa4f2f808`; common MD5 `b95c88bc19162653b2949581c5cf636b`). [V] These MD5s match the Src tarballs inside Canon's archive byte for byte. — [SlackBuilds cndrvcups-capt.info](https://slackbuilds.org/slackbuilds/15.0/system/cndrvcups-capt/cndrvcups-capt.info); [SlackBuilds cndrvcups-common.info](https://slackbuilds.org/slackbuilds/15.0/system/cndrvcups-common/cndrvcups-common.info)

### Inferences
- The stable location is `gdlp01.c-wss.com/gds/6/0100004596/05/…`. It has been in AUR since the v2.71 upgrade (AUR log "2017-08-09 Upgrade to v2.71") and still serves the same bytes in 2026, but Canon moved the object to S3 on 2025-03-31. A downloader should pin size and SHA-256. It could also resolve Canon's `pdisp01…WWUFORedirectTarget.do?id=MDEwMDAwNDU5NjA1` redirect first, in case Canon moves the file again.
- "121.61 MB" on Canon's page is MiB (127,521,219 / 1,048,576 = 121.61).

### Gaps
- No Canon USA page for the LBP2900 was found. The model is a Europe/Asia "LASER SHOT / i-SENSYS" product, which I did not confirm.
- Canon Europe's page could not be fetched directly (HTTP 403), and Canon Japan's legacy host is gone. Their exact dates and file names are unverified.
- Canon publishes no checksum, so "official" integrity rests on HTTPS from Canon's CDN plus agreement with the AUR pin.

## 2. What the archive contains, inspected without installing (packages, control fields, maintainer scripts, files, 32-bit ELF, init script, PPD, captstatusui, license)

### Takeaway
[V] Each architecture has two Debian packages: `cndrvcups-common_3.21-1` and `cndrvcups-capt_2.71-1`. The **amd64 packages are hybrids**. The daemon `ccpd`, `ccpdadmin`, the CUPS backend `ccp`, the filters `pstocapt*` and the GTK2 GUIs are x86-64. But **`captfilter`, all status-monitor plugins (`captmon`, `captmon2`, `captmon*`) and Canon's core libraries are 32-bit i386 ELF**, installed in plain `/usr/lib` and `/usr/bin`. The control files declare **no i386 dependencies**. The maintainer scripts are crude: a `kill -9` loop, `chown lp.lp`, a world-writable directory, and no `update-rc.d`. There is no systemd unit and no udev rule. The LBP2900 PPD has **no `*1284DeviceID`**. The EULA allows redistribution only "on the Product", while Canon's download page forbids distribution outright.

### Cited Findings
- [V] `cndrvcups-capt_2.71-1_amd64.deb` control: `Version: 2.71-1`, `Section: net`, `Priority: optional`, `Architecture: amd64`, `Depends: libatk1.0-0 (>= 1.12.2), libc6 (>= 2.3.5-1), libgcc1 (>= 1:4.1.1-12), libglade2-0 (>= 1:2.5.1), libglib2.0-0 (>= 2.12.0), libgtk2.0-0 (>= 2.8.0), libpopt0 (>= 1.10), libstdc++6 (>= 4.1.1-12), libxml2 (>= 2.6.27), zlib1g (>= 1:1.2.1), cndrvcups-common (>= 3.21)`, `Replaces: cndrvcups-lipslx, cndrvcups-ufr2-uk, cndrvcups-ufr2-us`, `Installed-Size: 35716`, `Maintainer: CANON INC. <sup-debian@list.canon.co.jp>`. There is **no Pre-Depends, no Conflicts, no Multi-Arch**. The i386 deb is identical except `Architecture: i386` and `libc6 (>= 2.3.6-6)`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `cndrvcups-common_3.21-1_amd64.deb` control: `Depends: libc6 (>= 2.3.5-1), libglade2-0 (>= 1:2.5.1), libglib2.0-0 (>= 2.12.0), libgtk2.0-0 (>= 2.8.0), libstdc++6 (>= 4.1.1-12), cupsys | cups, gs-esp | ghostscript (>= 9.00), libcups2 | libcupsys2 (>= 1.2.7)`, `Replaces: cndrvcups-ufr2-us, cndrvcups-lipslx, cndrvcups-ufr2-uk`, `Installed-Size: 22224`, Description "Canon Printer Driver Common Modules Ver.3.21". — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Canon's own source packaging (`debian/control` inside `Src/cndrvcups-capt-2.71-1.tar.gz`) uses `Architecture: i386 amd64` and `Depends: ${shlibs:Depends}, ${misc:Depends}, cndrvcups-common (>= 3.21)`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `cndrvcups-capt` conffiles: `/etc/init.d/ccpd`, `/etc/ccpd.conf`. `cndrvcups-common` has no conffiles and no prerm. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `cndrvcups-capt` **preinst and prerm** (identical):
  ```sh
  /etc/init.d/ccpd stop > /dev/null 2>&1
  while [ `ps awx | grep -e ccpd -e captmon | grep -v grep | wc -l` -ne 0 ]
  do
  	kill -9 `ps awx | grep -e ccpd -e captmon | grep -v grep | cut -c 1-5` > /dev/null 2>&1
  	sleep 3
  done
  exit 0
  ```
  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `cndrvcups-capt` **postinst**: the old `/var/ccpd/fifo0..7` creation is commented out. The script then creates `/var/captmon` (`chown lp.lp`) and, if `/usr/share/ppd` exists, runs `ln -sf` for every `/usr/share/cups/model/CN*CAPT*.ppd` into `/usr/share/ppd/`. It calls no `update-rc.d`/`systemctl` and does not restart CUPS. **postrm** does `rm -Rf /var/captmon` and `rm -rf /usr/share/ppd/CN*CAPT*.ppd`. `cndrvcups-common` **postinst** does `mkdir -p /etc/cngplp/account; chmod 777 /etc/cngplp/account`. Its preinst and postrm contain only commented-out code. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] What `cndrvcups-capt` amd64 installs:
  - `/etc/init.d/ccpd` and `/etc/ccpd.conf`;
  - `/usr/sbin/ccpd` (54,056 B) and `/usr/sbin/ccpdadmin` (16,240 B). These are in **/usr/sbin**; the AUR build puts them in /usr/bin;
  - `/usr/bin/captfilter`, `captdrv`, `captmon`, `captmon2`, 21 model-specific `captmoncnab*/cnac*/lbp3300/lbp5000`, and `captstatusui`;
  - `/usr/lib/cups/backend/ccp` and `/usr/lib/cups/filter/pstocapt`, `pstocapt2`, `pstocapt3`;
  - **52 PPDs in `/usr/share/cups/model/`** (`CNCUPSLBP*CAPT{J,K,S}.ppd`);
  - firmware/table blobs in `/usr/share/ccpd/*.BIN`, `/usr/share/captfilter/*INK.DAT`, `/usr/share/caepcm/*.DAT`, `/usr/share/captmon*/msgtable*.xml`, `/usr/share/captemon/*.xml`;
  - `.res`/`.glade` files in `/usr/share/cngplp/`;
  - `ja/es/de/it/fr` `.mo` files;
  - libraries in `/usr/lib/`: `libcanoncapt`, `libcaptfilter`, `libuictlcapt`, `libcncaptnpm`, `libcaiocaptnet`, `libcnaccm`;
  - docs: `README-capt-2.71{US,UK,J}.txt.gz`, `LICENSE-{EN,JP}.txt.gz`, `copyright` ("License: See the LICENSE-*.txt file.").

  `cndrvcups-common` installs `/usr/bin/c3pldrv`, `cngplp`, `cnjatool`, `/usr/lib/cups/backend/cnusb`, libraries (`libcaiousb`, `libcaiowrap`, `libcanon_slim`, `libColorGear(C)`, `libcaepcm`, `libc3pl`, `libcanonc3pl`) and ICC profiles. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] ELF classes in the amd64 debs (`file` + `readelf`):
  - **32-bit i386** (interpreter `/lib/ld-linux.so.2`): `captfilter`, `captdrv`, `c3pldrv`, `captmon`, `captmon2`, all 21 `captmon*` binaries, `libcaptfilter.so.1.0.0`, `libcaiousb`, `libcaiowrap`, `libcanon_slim`, `libcaepcm`, `libc3pl`, `libColorGear`, `libColorGearC`, `libcnaccm`, `libcncaptnpm`, `libcaiocaptnet`.
  - **64-bit x86-64**: `ccpd`, `ccpdadmin`, `captstatusui`, `cngplp`, `cnjatool`, `ccp`, `cnusb`, `pstocapt`, `pstocapt2`, `pstocapt3`, `libcanoncapt`, `libcanonc3pl`, `libuictlcapt`.
  - The Src tarballs also ship prebuilt 32-bit `libs/` (and `libs64/` for ccpd/ccpdadmin), so the "source" release still contains the proprietary binaries.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Print path as read from `strings`:
  - `pstocapt` runs Ghostscript with `"%s -r%d -q -dNOPROMPT -dSAFER -sDEVICE=pgmraw -sOutputFile=- -|"` and execs `captfilter` (strings "/usr/bin", "captfilt…", "execv() error").
  - The `ccp` backend talks to the daemon ("ERROR: Can't connect to CCPD"; device listing `direct ccp "Unknown" "CAPT Printer"`).
  - `ccpd` reads `/etc/ccpd.conf` and CUPS's `printers.conf` ("%sprinters.conf", "DeviceURI", "<Printer"), refuses to run unprivileged ("%s: must be run as root"), opens the printer device path ("ccpd: DA[%d]: Printer open() path=%s fd=%d errno= %s"), and starts status-monitor plugins through a "bidi" interface ("--data-write-fd=%d", "Module Not Found !! bidiNew()").
  - [V] Ghostscript's `pgmraw` device exists in the Mint 22.3 base (`libgs.so.10.02`).

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz); [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] Default `/etc/ccpd.conf`: `CUPS_ConfigPath /etc/cups/`, commented-out `LogDirectoryPath /var/log/CCPD/`, a commented example `<Printer LBP3200> DevicePath /dev/usb/lp0 </Printer>`, and `<Ports> UI_Port 59787` / `PDATA_Port 59687`. It says "The "Printer Name" has to be identical to the CUPS printer queue name". `ccpdadmin` usage: `ccpdadmin [-p Printer-name -o Printer-dev-path]`, `ccpdadmin [-x Remove-Printer-name]`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `/etc/init.d/ccpd`:
  - **no LSB header**;
  - it first busy-waits until `ps awx | grep cupsd` finds cupsd (`sleep 3`, then `sleep 5`);
  - it detects Debian through `/sbin/start-stop-daemon` and runs `start-stop-daemon --start --quiet --oknodo --exec /usr/sbin/ccpd`;
  - stop is `start-stop-daemon --stop --quiet --oknodo --signal 15 --exec ${DAEMON}`;
  - `status` prints `pidof`;
  - `LOCKFILE=/var/lock/subsys/ccpd`.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] **LBP2900 PPD** `CNCUPSLBP2900CAPTK.ppd` (289 lines, the only LBP2900 PPD; there is no J or S variant):
  - `*FormatVersion: "4.3"`, `*FileVersion: "1.2"`, `*PCFileName: "CNL290CK.PPD"`, `*Manufacturer: "Canon"`;
  - `*Product: "(LBP2900)"`, `*ModelName: "Canon LBP2900 CAPT English"`, `*ShortNickName: "LBP2900"`, `*NickName: "Canon LBP2900 CAPT ver.1.5"`;
  - `*cupsVersion: 1.1`, `*cupsManualCopies: True`, `*cupsModelNumber: 36`;
  - `*cupsFilter: "application/vnd.cups-postscript 0 pstocapt"`, `*opbidiPlugin: "captmon2"`, `*DefaultResolution: 600`.
  - **None of the 52 PPDs has a `*1284DeviceID` line.** Filter use across them: 12 use pstocapt, 4 pstocapt2, 36 pstocapt3.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] `captstatusui` (64-bit) links `libgtk-x11-2.0.so.0`, `libgdk-x11-2.0.so.0`, `libatk-1.0.so.0`, `libgdk_pixbuf-2.0.so.0`, `libgobject/glib-2.0`, `libxml2.so.2` and `libcups.so.2`, so it is **GTK 2**. `cngplp` is GTK 2 + `libglade-2.0.so.0` with `RPATH=/usr/local/lib`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] README v2.71 says "Evaluated OS: Fedora 21 32-bit/64-bit, Ubuntu 14.10 Desktop 32-bit/64-bit", "You can register up to 16 printers to a single PC with this printer driver", and that the LBP2900 uses `CNCUPSLBP2900CAPTK.ppd`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Official install procedure (HTML guide `main_02_01.html`):
  1. `dpkg -i` common, then capt.
  2. Restart CUPS.
  3. `/usr/sbin/lpadmin -p [printer name] -m [PPD file name] -v ccp://localhost:59687 -E`; use `-P <full path>` instead of `-m` on Fedora 19 / Ubuntu 14.10.
  4. `/usr/sbin/ccpdadmin -p [Printer Name] -o [Printer Device Path]`, e.g. `-o /dev/usb/lp0`, or `-o net:<IP>`.
  5. `/etc/init.d/ccpd start`, with the note "It would be convenient to set ccpd daemon to start automatically".

  The guide states CUPS ≥ 1.1.17 is supported. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] License file `Doc/LICENSE-EN.txt`, section [1] "SOFTWARE LICENSE AGREEMENT FOR CANON'S OR ITS LICENSORS' SOFTWARE PROGRAMS". It defines "Product" as "this Canon's printer driver for Linux provided to you together with this Agreement" and "Software" as the programs in Schedule 1. **Verbatim redistribution clauses:**
  > "1.GRANT OF LICENSE — Canon grants you a personal, limited and non-exclusive license to use ("use" as used herein shall mean storing, loading, installing, accessing, executing or displaying), have used, copy, have copied, distribute and permit third parties to use and copy the Software only on the Product. You may modify the Software only for your own use and reverse engineer the same for debugging such modifications. You shall distribute the Software to any third party under the same terms and conditions as contained herein."
  > "2.RESTRICTIONS — Except as expressly granted or permitted herein, you shall not use, assign, sublicense, sell, rent, lease, loan, convey or transfer to any third party the Software."
  > "3.COPYRIGHT NOTICE — You shall not modify, remove or delete any copyright notice of Canon or its licensors contained in the Software, including any copy thereof."

  Section [2] says the Schedule 2 components are GPL v2 and "you can redistribute them and/or modify them under the terms of GPL". Section [3] puts the Schedule 3 components under an MIT-style notice "Copyright (c) 2007 Canon Inc.". — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] README Appendix schedules:
  - **Schedule 1 (proprietary Canon EULA):** `c3pldrv`, `libc3pl`, `libcaepcm`, `libcaiousb`, `libcaiowrap`, `libcanon_slim`, `libColorGear(C)`, the ICC/DAT files, `ccpd.conf`, `ccpd (daemon)`, `captdrv`, `captfilter`, `captmon`, `captmon2`, all `captmon*`, `libcaiocaptnet`, `libcaptfilter`, `libcnaccm`, `libcncaptnpm`, "ccpd (startup script for the daemon)" and `ccpdadmin`.
  - **Schedule 2 (GPL v2):** `cnusb`, `cngplp`, `cnjatool`, `ccp`, `pstocapt`, `pstocapt2`, `pstocapt3`, `captstatusui`, `libuictlcapt`, the `.mo`/`.glade` files, `func_config_capt.xml`, `*.res` and **`*.ppd`**.
  - **Schedule 3 (MIT):** `buflist.h`, `buftool.h`, `libbuftool.a`, `libcanoncapt`, `libcanonc3pl`.
  - The README ends: "Canon … and your Canon local company … will not respond to any inquiries about this Software or Related Information" ("Copyright CANON INC. 2013").

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)

### Inferences
- The amd64 control file has no i386 dependencies because Canon built it with `${shlibs:Depends}`. `dpkg-shlibdeps` only resolved the 64-bit ELF files. So `dpkg -i`/`apt install ./…amd64.deb` "succeeds" on a machine without 32-bit libraries, but `captfilter` and `captmon2` then cannot even start: the missing `/lib/ld-linux.so.2` gives an exec "No such file or directory".
- **Dangerous maintainer scripts on modern Ubuntu, verified by reading the code plus the ps format.** Mint 22.3 / noble set `kernel.pid_max = 4194304` (`/usr/lib/sysctl.d/50-pid-max.conf`, [V]). `ps awx` then right-aligns the PID in a 7-character column, so `cut -c 1-5` returns a truncated number. [V] on Ubuntu 24.04.4, PID 629433 became " 6294". If any process matches `ccpd` or `captmon` during preinst/prerm, the script sends `kill -9` to **wrong, unrelated PIDs**. It can also loop forever if the real process survives. The regex matches any command line containing "ccpd" or "captmon", e.g. an editor on `/etc/ccpd.conf`, `journalctl -u ccpd`, or a CaramOS helper whose path contains "ccpd". A CaramOS installer must stop ccpd and captmon* cleanly **before** dpkg runs, and must never have "ccpd"/"captmon" in its own command line.
- `chown lp.lp` still works on coreutils 9.4 but prints a deprecation warning. `chmod 777 /etc/cngplp/account` creates a world-writable directory, which is a minor local-security smell.
- The PPDs live only in `/usr/share/cups/model` and have no 1284 Device ID. CUPS and system-config-printer therefore cannot auto-match the LBP2900 to the CAPT PPD, and the queue has to be created by hand (or by a CaramOS script) with the `ccp://` URI.

### Gaps
- I did not inspect the `.rpm` variants beyond listing them, or every `.res`/XML data file.
- I did not run any binary, so runtime behaviour (e.g. how ccpd reacts when the device node disappears) is inferred from `strings`/sources, not observed.

## 3. Which 32-bit (i386) libraries the amd64 packages need, and whether each is installable on noble via multiarch

### Takeaway
Every amd64 dependency in Canon's control files is satisfiable on noble. The renamed time_t-64 libraries provide the old names (`libgtk2.0-0t64` Provides `libgtk2.0-0 (= …)`, etc.), and `libglade2-0` comes from universe. The 32-bit parts additionally need **`libc6:i386`, `libpopt0:i386`, `libxml2:i386` (+ `zlib1g`, `liblzma5`, `libicu74` i386), `libstdc++6:i386`, `libgcc-s1:i386`**. All are in noble's i386 archive (main). No GTK i386 is needed because the GUIs are 64-bit. Mint 22.3 already has the i386 architecture enabled but installs no i386 package.

### Cited Findings
- [V] Union of `NEEDED` over all 32-bit ELF files in the amd64 debs:
  - from libc6: `libc.so.6` (37), `libdl.so.2` (30), `libpthread.so.0` (26), `libm.so.6` (26), `librt.so.1` (2);
  - `libxml2.so.2` (23), `libz.so.1` (21), `libstdc++.so.6` (18), `libgcc_s.so.1` (16), `libpopt.so.0` (5);
  - plus Canon's own 32-bit libraries (`libcaiowrap.so.1`, `libcanon_slim.so.1.0.0`, `libcaepcm.so.1`, `libcncaptnpm.so.2`).

  For the LBP2900 path:
  - `captfilter` → `libpopt.so.0 libc.so.6`;
  - `captmon2` (the PPD's `*opbidiPlugin`) → `libxml2.so.2 libpthread.so.0 libpopt.so.0 libdl.so.2 libc.so.6`;
  - `libcaptfilter.so` → `libcaepcm.so.1 libcanon_slim.so.1.0.0 libm.so.6 libc.so.6`;
  - `libcaepcm` → `libm libdl libpthread librt libc`;
  - `libColorGear*` → `libstdc++.so.6`.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Noble **i386** availability in the Ubuntu archive indexes, read 2026-11-08 (noble-updates InRelease Date "Sun, 08 Nov 2026 2:39:31 UTC"):
  - `libc6` 2.39-0ubuntu8.9 (Depends libgcc-s1);
  - `libpopt0` 1.19+dfsg-1build1 (release pocket only);
  - `libxml2` 2.9.14+dfsg-1.3ubuntu3.10 (Depends `libc6, libicu74 (>= 74.1-1~), liblzma5, zlib1g`);
  - `zlib1g` 1:1.3.dfsg-3.1ubuntu2.3;
  - `libstdc++6` 14.2.0-4ubuntu2~24.04.1;
  - `libgcc-s1` 14.2.0-4ubuntu2~24.04.1 (Provides `libgcc1 (= 1:14.2.0-4ubuntu2~24.04.1)`).

  All are `Multi-Arch: same`. `libglade2-0` does **not** exist for i386 in noble, which only matters for the pure-i386 debs. — [Ubuntu archive noble/main/binary-i386](http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-i386/Packages.xz); [noble-updates/main/binary-i386](http://archive.ubuntu.com/ubuntu/dists/noble-updates/main/binary-i386/Packages.xz)
- [V] `libc6:i386` ships `/usr/lib/ld-linux.so.2` (and `/usr/lib/i386-linux-gnu/ld-linux.so.2`), which is the interpreter the 32-bit Canon binaries request as `/lib/ld-linux.so.2` (via the /lib → /usr/lib merge). — [packages.ubuntu.com libc6 i386 filelist](https://packages.ubuntu.com/noble/i386/libc6/filelist)
- [V] How the **amd64** control fields resolve on noble:
  - `libatk1.0-0` ← `libatk1.0-0t64` 2.52.0-1build1 "Provides libatk1.0-0 (= 2.52.0-1build1)";
  - `libglib2.0-0` ← `libglib2.0-0t64` 2.80.0-6ubuntu3.10;
  - `libgtk2.0-0` ← `libgtk2.0-0t64` 2.24.33-4ubuntu1.1;
  - `libcups2` ← `libcups2t64` 2.4.7-1.2ubuntu7.14;
  - `libgcc1` ← `libgcc-s1` (versioned Provides with epoch 1:);
  - `libglade2-0` 1:2.6.4-2.4build2 is a real package **in universe**;
  - `libpopt0` 1.19+dfsg-1build1, `libstdc++6` 14.2.0-4ubuntu2~24.04.1, `libxml2` 2.9.14+dfsg-1.3ubuntu3.10, `zlib1g` 1:1.3.dfsg-3.1ubuntu2.3;
  - `cups` 2.4.7-1.2ubuntu7.14 and `ghostscript` 10.02.1~dfsg1-0ubuntu7.10 (satisfies `>= 9.00`).
  - `cupsys`, `gs-esp` and `libcupsys2` do not exist, but they only appear as alternatives.

  — [Ubuntu archive noble/main/binary-amd64](http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-amd64/Packages.xz); [noble/universe/binary-amd64](http://archive.ubuntu.com/ubuntu/dists/noble/universe/binary-amd64/Packages.xz)
- [V] Linux Mint 22.3 base (CaramOS build input): `/var/lib/dpkg/arch` = `amd64`, `i386`, so i386 multiarch is already enabled. **No** `Architecture: i386` package is installed. `libglade2-0` is not installed; `libgtk2.0-0t64` and `libpopt0` (amd64) are. — [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] Canon's own README lists the extra packages per release. Ubuntu 12.04 64-bit: `apt-get install libglade2-0`, `apt-get install ia32-libs`, `apt-get install libpopt0:i386`. **Ubuntu 14.04/14.10 64-bit:** `apt-get install libglade2-0`, `apt-get install libxml2:i386`, `apt-get install libstdc++6:i386`, `apt-get install libpopt0:i386`. Fedora 64-bit gets the matching `glibc.i686 libgcc.i686 libstdc++.i686 popt.i686 libxml2.i686`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- Arch packages the same driver with `depends_x86_64=('lib32-libxml2-legacy' 'lib32-popt' 'lib32-gcc-libs' 'lib32-libcups' 'lib32-glibc')`. When Arch moved to a libxml2 with a new soname, users needed "libxml2-legacy" plus a `libxml2.so.2` symlink or rebuilds (comments 2025-05-06). On 2026-04-09 a user had to rebuild `lib32-libxml2-legacy` after libicu went from 76 to 78. — [AUR capt-src PKGBUILD](https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=capt-src); [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)

### Inferences
- Recommended i386 set for CaramOS:
  `apt install libc6:i386 libpopt0:i386 libxml2:i386 zlib1g:i386 libstdc++6:i386 libgcc-s1:i386`.
  `libicu74:i386` and `liblzma5:i386` come in through libxml2. libstdc++6/libgcc-s1 are needed by `libColorGear*` and the colour `captmon*`, and Canon's README lists libstdc++6:i386, so include them. Also `libglade2-0` (amd64, universe).
- [V] Size of that i386 chain, from the noble i386 index `Installed-Size`/`Size` fields:
  - libc6 12,294 KB; libicu74 74.2-1ubuntu3.1 36,167 KB; libstdc++6 3,118 KB; libxml2 2,026 KB; liblzma5 394 KB; libgcc-s1 235 KB; zlib1g 158 KB; libpopt0 120 KB; gcc-14-base 113 KB;
  - total about **16.0 MB to download and 54.6 MB installed**, about two thirds of it libicu74:i386.
  - Canon's two amd64 debs add `Installed-Size` 35,716 + 22,224 KB (about 58 MB).

  — [Ubuntu archive noble-updates/main/binary-i386](http://archive.ubuntu.com/ubuntu/dists/noble-updates/main/binary-i386/Packages.xz)
- The 32-bit Canon `.so` files sit in `/usr/lib`. The i386 loader and `ldconfig` look in `/usr/lib` (the generic library directory), so they should be found without extra config. This is untested and must be verified in a VM with `ldd`/`LD_DEBUG`.
- Future risk: once Ubuntu (a later CaramOS base) moves libxml2 to the 2.14+ soname, `captmon2`/`captmon` lose `libxml2.so.2` (the Arch experience above). This is not an issue on noble, which stays on 2.9.14 for its lifetime. I did not check what Ubuntu 26.04 ships.

### Gaps
- Not tested at runtime: whether every `dlopen()`ed library (e.g. `libcaptfilter`, `libcanon_slim`, the ColorGear libraries) loads under noble's i386 glibc 2.39.
- I did not quantify the exact download and disk size of the i386 dependency chain.

## 4. How ccpd reaches the printer (/dev/usb/lp0 via usblp vs the CUPS usb backend); usblp on noble; the lp0/lp1 problem and udev symlinks

### Takeaway
`ccpd` does not use libusb. It `open()`s the kernel **usblp** character device configured with `ccpdadmin -o /dev/usb/lpN` (`DevicePath` in `/etc/ccpd.conf`). On noble/Mint 22.3, usblp is **not blacklisted**: the module is shipped (`CONFIG_USB_PRINTER=m`) and no modprobe.d or udev file mentions it. However, the **CUPS usb backend (libusb) detaches usblp** whenever it probes or uses the device. Mint's `system-config-printer-udev` triggers such probes on every USB printer hotplug, which produces "usblp0: removed" and breaks ccpd. Known fixes: tell CUPS's usb backend to ignore the printer with a quirks file (`0x04a9 0x2676 blacklist`), give ccpd a stable udev symlink instead of `/dev/usb/lp0`, and never use auto-created `usb://` queues.

### Cited Findings
- [V] `ccpd` contains "DevicePath" and "ccpd: DA[%d]: Printer open() path=%s fd=%d errno= %s". The default ccpd.conf comment reads: "if … the printer is connected to the USB port "/dev/usb/lp0"…". — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Canon guide: "`/usr/sbin/ccpdadmin -p LBP5000 -o /dev/usb/lp0` … NOTE Depending on the distribution you are using, "/dev/usblp*" may be displayed in [Printer Device Path]. If multiple printers are simultaneously connected by USB cables, the port numbers for [Printer Device Path] registered first may be changed depending on the order of turning the power ON and so on. In this case, you need to register [Printer Device Path] again or match the port numbers by adjusting the order of plug-in or turning the power ON." — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Canon README v2.71 on the Ubuntu 11.10 era: "the communication with a USB connected printer may not be established if "usblp" is not lauched … [Avoidance plan 1] … `# sudo modprobe usblp` [Avoidance plan 2] Remove the "blacklist usblp" line from the /etc/modprobe.d/blacklist-cups-usblp.conf file". The README also says: "If you want to use multiple printers with the same device path (such as /dev/usb/lp0) on a USB connection, exit the ccpd daemon, and then add a printer when you switch the connection." — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Mint 22.3 base (HWE kernel 6.14.0-37-generic): `CONFIG_USB_PRINTER=m`; `usblp.ko.zst` present; **no line mentioning `usblp`** in `/etc/modprobe.d/` or `/usr/lib/modprobe.d/`; no udev rule mentioning `usblp` or `usb/lp`. The host Ubuntu 24.04.4 with kernel 6.8 is the same. — [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] Noble CUPS 2.4.7 usb backend (`/usr/lib/cups/backend/usb`) strings: `libusb_detach_kernel_driver`, `libusb_attach_kernel_driver`, `DEBUG: Failed to detach "usblp" module from %04x:%04x`, `DEBUG: Failed to re-attach "usblp" kernel module`, `usb-no-reattach`, `DEBUG: Loading USB quirks from "%s".`
  The quirks file header (`/usr/share/cups/usb/org.cups.usb-quirks`) defines these keywords: `blacklist` ("The printer is not functional with the USB backend"), `delay-close`, `no-reattach` ("Do no re-attach usblp kernel module after printing"), `soft-reset`, `unidir`, `usb-init`, `vendor-class`, `whitelist`.
  The shipped file has **no Canon CAPT entries**; the only Canon lines are PIXMA/MP `unidir`. — [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] Mint 22.3 base ships `system-config-printer-udev`. Its `70-printers.rules`:
  `ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ENV{ID_USB_INTERFACES}=="*:0701??:*", ENV{ID_USB_INTERFACES}!="*:070104:*", TAG+="systemd", ENV{SYSTEMD_WANTS}="configure-printer@usb-$env{BUSNUM}-$env{DEVNUM}.service"`
  This runs `udev-configure-printer` on every USB printer-class hotplug. — [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] `usb.ids`: Canon `04a9:2676` = "LBP2900". — local `/usr/share/misc/usb.ids` (hwdata); also in the CUPS #80 list below.
- OpenPrinting/cups **issue #80** "Cups attempts to probe, configure unsupported Canon CAPT USB printers":
  - Opened 2021-01-27 by chris-bainbridge against Debian cups 2.3.3op1-7. CAPT printers need Canon's driver, which uses the legacy `/dev/usb/lp0`. CUPS creates a non-functional queue and probes the device, which causes a disconnect ("usblp0: removed"); `lpinfo`/`lpstat` also triggered a disconnect.
  - He proposed quirks lines including "`# Canon, Inc. LBP2900/LBP2900B Printer` `0x04a9 0x2676 blacklist`" (27 IDs, LBP810 0x260a … LBP9100C 0x26ea).
  - Michael Sweet: blacklisting "is not the solution … First, the Canon driver needs to be fixed to actually work with CUPS and not work around it". He closed the issue 2021-09-17, suggesting a separate quirks file in `/usr/share/cups/usb`, "No guarantees that this will solve the problem."
  - Later comments (2025-05-12, 2025-11-14/15) report using such a file (e.g. `p700.usb-quirks`) to stop "No drivers found" pop-ups, as a separate file so package updates do not overwrite it.

  — [OpenPrinting/cups #80](https://github.com/OpenPrinting/cups/issues/80)
- Debian bug #980973 (same reporter, filed 2021-01-24 against cups 2.3.3op1-7; proposed `0x04a9 0x26da blacklist` for LBP3010/3018/3050) was closed 2022-08-16 as "Completed upstream". It does not mention the LBP2900, cups-browsed or udev-configure-printer. — [Debian #980973](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=980973)
- Arch Wiki "Canon CAPT" (last revisions 2025-12-20):
  - "Conflict with CUPS: To prevent CUPS from accessing our CAPT-only printer (and confusing the firmware with multiple setup requests over USB), a list of unsupported VID/PID pairs may be added into /usr/share/cups/usb/. A new file (e. g. capt-printers.usb-quirks) may be created to prevent the list from getting overwritten by CUPS updates."
  - "Collisions with other printers: Other printers connected to the computer may create their own /dev/usb/lpN entries, possibly even before your Canon printer is enumerated and initialized … A symlink to the USB device can be created automatically by Udev based on the USB VID/PID and (optionally) the serial number". The example is `/etc/udev/rules.d/50-canon.rules`: `SUBSYSTEMS=="usb", ATTRS{idVendor}=="04a9", ATTRS{idProduct}=="271c", ATTRS{serial}=="0000A2BARL02", SYMLINK+="usb/lbp7010c"`, followed by `ccpdadmin -p LBP7010C -o /dev/usb/lbp7010c` (source: Arch BBS 204625, "/dev/usb/lp1 is used instead of /dev/usb/lp0").

  — [Arch Wiki Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT)
- Arch Wiki says to use `ccp://localhost:59787` and "If port 59787 does not work, try port 59687". **This contradicts Canon's guide and ccpd.conf**: the queue URI is `ccp://localhost:59687` (PDATA_Port); 59787 is the status-monitor UI_Port. — [Arch Wiki Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT); contradicted by [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- Launchpad bug #1940125 (2021-08-16, Ubuntu 20.04, cups 2.3.1): an LBP2900 queue with `usb://Canon/LBP2900?serial=…` and the "Canon LBP2900 CAPT ver.1.5" PPD. "It shows either 'Processing' or 'Pending' and no paper is printed". Status New, no maintainer reply. This is the classic wrong-URI setup, where the queue bypasses ccpd. — [LP #1940125](https://bugs.launchpad.net/ubuntu/+source/cups/+bug/1940125)

### Inferences
- What to expect on CaramOS when an LBP2900 is plugged in or switched on:
  1. The kernel binds usblp, which creates `/dev/usb/lp0`.
  2. `70-printers.rules` starts `configure-printer@…`, and `udev-configure-printer` asks CUPS to enumerate devices.
  3. The CUPS usb backend detaches usblp to read the device ID ("usblp0: removed") and re-attaches it.
  4. The device node disappears and comes back. If ccpd is holding the old fd, it may come back as `lp1`.
  5. The desktop may also show a "missing driver" notification, or an auto-created `usb://` queue may appear.

  Mitigations to test in a VM with USB passthrough:
  - ship `/usr/share/cups/usb/caramos-capt.usb-quirks` with `0x04a9 0x2676 blacklist`, optionally for all CAPT IDs from CUPS #80;
  - add a udev rule creating a stable `/dev/usb/lbp2900` symlink. Matching the usblp node itself is probably cleaner than the Arch example, e.g. `SUBSYSTEM=="usbmisc", KERNEL=="lp*", ATTRS{idVendor}=="04a9", ATTRS{idProduct}=="2676", SYMLINK+="usb/lbp2900"` (this is my guess and needs a test);
  - run `ccpdadmin -p <queue> -o /dev/usb/lbp2900`;
  - delete any `usb://` queue for the device;
  - create the queue with `-v ccp://localhost:59687`.
- The CUPS `blacklist` quirk should also stop the usb backend from reporting the device, so udev-configure-printer and the GUI should no longer try to auto-add it. This is inferred from the keyword's documented meaning and the 2025 reports in #80, not tested.
- Ubuntu's cupsd AppArmor profile is no obstacle. [V] In the Mint 22.3 base, `/usr/lib/cups/backend/* Cx -> third_party` and `/usr/lib/cups/filter/** Cxr -> third_party`, and the `third_party` subprofile grants `file, capability, network, dbus, signal, ptrace, unix` ("third party backends, filters, and drivers get relatively no restrictions"). ccpd itself runs unconfined from init.

### Gaps
- I did not confirm the LBP2900's exact USB interface class/subclass/protocol (expected 07/01/0x, which is what `70-printers.rules` and systemd's printer rules match), nor whether it exposes a serial number usable in udev rules. This needs `lsusb -v` on real hardware.
- There are no hardware or VM tests of the quirks + symlink combination on CUPS 2.4.7. Michael Sweet's "No guarantees" stands.

## 5. systemd: official unit? How guides start ccpd at boot on 20.04/22.04/24.04; known races

### Takeaway
Canon ships **no systemd unit**, only a SysV `/etc/init.d/ccpd` without an LSB header, and the postinst never enables it. On noble (systemd 255), `systemctl start ccpd` works through `systemd-sysv-generator`, but ccpd does not start at boot unless rc links (`update-rc.d`), `rc.local` or a native unit are added. Canon's README recommends `rc.local`. Arch ships its own native unit. systemd 259 deprecates both the SysV generator and the rc.local generator, with removal planned for v260, so a native unit is the durable choice. Races come from the init script's busy-wait for cupsd, ccpd opening the device node only at start, and USB re-enumeration (probe, replug, suspend).

### Cited Findings
- [V] The deb contains only `/etc/init.d/ccpd` (no LSB header) and lists it as a conffile. The postinst has no `update-rc.d`, `systemctl enable` or `invoke-rc.d`. — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] README §4 "Auto startup setting procedure for ccpd daemon":
  - "<For a distribution with a /etc/rc.local file> … add the '/etc/init.d/ccpd start' command to the /etc/rc.local file."
  - "<For a distribution with a /sbin/insserv command> … add the following comments … `### BEGIN INIT INFO` `# Provides: ccpd` `# Required-Start: $local_fs $remote_fs $syslog $network $named` `# Should-Start: $ALL` … `# Default-Start: 3 5` … and execute the 'insserv ccpd' command."
  - "<For a distribution with a /usr/bin/systemctl command> … create a /etc/rc.local file … `#!/bin/sh` `/etc/init.d/ccpd start` … `# chmod 777 /etc/rc.d/rc.local`". The text contains Canon's typo "/erc/rc.d/rc.local"; the path shown is Fedora-style.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] README cautions:
  - "About starting the ccpd: … Starting ccpd (via systemctl): Failed to start ccpd.service: Unit ccpd.service failed to load: No such file or directory. If an error occurs, execute … `# systemctl daemon-reload`".
  - "About restarting the ccpd for Ubuntu 12.04/14.04/14.10 … the ccpd may not restart even if the following command is executed … `/etc/init.d/ccpd restart` … first enter the ccpd stop command, and then wait a little before entering the ccpd start command."

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- [V] Noble ships systemd 255.4-1ubuntu8.18 (noble-updates). The Mint 22.3 base contains `/usr/lib/systemd/system-generators/systemd-sysv-generator` and `systemd-rc-local-generator`, and has **no `/etc/rc.local`**. `insserv` is not in noble main or universe. — [Ubuntu archive noble-updates/main/binary-amd64](http://archive.ubuntu.com/ubuntu/dists/noble-updates/main/binary-amd64/Packages.xz); [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- [V] systemd's udev rules in the Mint 22.3 base pull in `printer.target` when a printer appears: `SUBSYSTEM=="usb", KERNEL=="lp*", TAG+="systemd", ENV{SYSTEMD_WANTS}+="printer.target"`, and the same for printer-class USB devices (`ID_USB_INTERFACES=="*:0701??:*"`) and `SUBSYSTEM=="printer"`. — [Mint 22.3 base rootfs](/home/dungleviet/Documents/CaramOS/build/cache)
- Arch's native unit (shipped by AUR capt-src):
  ```ini
  [Unit]
  Description=Canon CAPT daemon
  Requires=cups.service
  After=cups.service
  [Service]
  Type=forking
  ExecStart=/usr/bin/ccpd
  [Install]
  WantedBy=printer.target
  ```
  The post-install notes say to add the user to `lp`, `lpadmin -p LBP2900 -m CNCUPSLBP2900CAPTK.ppd -v ccp://localhost:59687 -E`, `ccpdadmin -p LBP2900 -o /dev/usb/lp0`, `systemctl enable ccpd.service`, and "Check you have two instances of ccpd in memory". The AUR git log shows "2020-11-21 Adapted to new cups.service". — [AUR ccpd.service](https://aur.archlinux.org/cgit/aur.git/plain/ccpd.service?h=capt-src); [AUR capt-src.install](https://aur.archlinux.org/cgit/aur.git/plain/capt-src.install?h=capt-src); [AUR capt-src log](https://aur.archlinux.org/cgit/aur.git/log/?h=capt-src)
- systemd 259 man page for systemd-sysv-generator: "Note: this component is deprecated and scheduled for removal. Please replace remaining SysV init scripts with native unit files." Release coverage of v259 says SysV support is deprecated with removal planned for v260, and names `systemd-rc-local-generator`, `systemd-sysv-generator` and `systemd-sysv-install`. — [systemd 259 systemd-sysv-generator(8)](https://www.freedesktop.org/software/systemd/man/259/systemd-sysv-generator.html); [linuxiac, systemd 259 released](https://linuxiac.com/systemd-259-released-with-major-changes-ahead-of-legacy-sysv-removal/)
- AUR comment 2026-04-09 (steamer25) on debugging a dead ccpd: `systemctl start ccpd.service && … strace … --attach <both ccpd PIDs>`. "When it tries and fails to load e.g., /usr/lib32/libicuuc.so.76, the file descriptor seems to get leaked and never closes. The process seems to just keep trying and retrying to load the library until … too many unclosed file requests". Workaround: add `LimitNOFILE=4096` to the unit while debugging. — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)

### Inferences
- Do not rely on the SysV script for CaramOS. Ship a native `ccpd.service` owned by CaramOS's helper package:
  - `ExecStart=/usr/sbin/ccpd` (Debian path) with `Type=forking` (ccpd forks; "two instances");
  - `After=cups.service`, `Wants=cups.service`;
  - `Restart=on-failure`;
  - `WantedBy=multi-user.target printer.target`.

  This avoids the init script's `ps | grep cupsd` busy-wait, which blocks forever if cupsd is not running yet (e.g. socket-activated). A `udev`/`systemd` hook that restarts ccpd when the LBP2900 node (re)appears covers replug and resume, because ccpd only opens `DevicePath` when it starts and does not notice a recreated node. That last point is inferred from the strings and from the user reports of having to restart ccpd; it is not observed.
- With no LSB header, `update-rc.d ccpd defaults` probably warns about missing LSB tags but still creates links. I did not test this.

### Gaps
- No primary source documents ccpd's behaviour across suspend/resume on 22.04/24.04. The forum reports I found are indirect (the Ubuntu Forums archive no longer resolves).
- I did not test systemd-sysv-generator's unit for this script on noble (ordering, timeouts).

## 6. Known failures on Ubuntu 22.04/24.04 and Linux Mint 21/22, with fixes and dated sources

### Takeaway
Most failures fall into a few root causes:
1. Missing i386 libraries, so captfilter/captmon2 cannot run.
2. ccpd not running: never enabled at boot, or crashed.
3. A wrong queue: an auto-created `usb://` URI instead of `ccp://localhost:59687`, or a duplicate queue.
4. A wrong or changing device path (`/dev/usb/lp0` vs lp1, or usblp being detached by CUPS probing).
5. Library or ghostscript regressions on rolling distros.

I found very few dated, LBP2900-specific primary sources for Ubuntu 22.04/24.04 or Mint 21/22. The Ubuntu community wiki pages and the Ubuntu Forums are no longer reachable.

### Cited Findings
- Jobs stuck in "Processing"/"Pending" with nothing printed, on an LBP2900 with the CAPT PPD but device URI `usb://Canon/LBP2900?serial=…`; CupsErrorLog shows "Stopping unresponsive job." (Ubuntu 20.04, 2021-08-16, unanswered). — [LP #1940125](https://bugs.launchpad.net/ubuntu/+source/cups/+bug/1940125)
- CUPS probing (`lpinfo`, `lpstat`, auto queue creation) disconnects the printer from usblp ("usblp0: removed"). The suggested workaround is a CUPS usb-quirks `blacklist` file (2021–2025). — [OpenPrinting/cups #80](https://github.com/OpenPrinting/cups/issues/80); [Debian #980973](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=980973)
- `/dev/usb/lp1` gets used instead of `/dev/usb/lp0` when other printers are present. Fix: a udev symlink by VID/PID/serial plus `ccpdadmin -o /dev/usb/<name>` (Arch Wiki, revised 2025-12-20). — [Arch Wiki Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT)
- The Arch Wiki notes "Installing CAPT printers via the CUPS web interface may not work" (linking an Ask Ubuntu answer) and says to use the CLI tools instead. — [Arch Wiki Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT)
- CUPS warns on every `lpadmin -m` with a PPD driver: "lpadmin: Printer drivers are deprecated and will stop working in a future version of CUPS." (AUR comment 2019-10-06). CUPS's plan for legacy drivers is printer applications (Michael Sweet, quoted in an AUR comment 2020-01-09). — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- On a source build, `captstatusui` failed with "Error: No specified Printer". The fix was to add `#include <cups/ppd.h>` to `statusui/src/uimain.c` (kaztai 2019-06-06; "works fine now with LBP2900", rsteube 2019-08-04). Canon's prebuilt amd64 binary is a different build; I did not check whether it is affected. — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- Ghostscript regression: "The printer lbp6020 stopped working … try downgrade ghostscript to 9.52-1" (AUR, 2020-09-29). Noble ships ghostscript 10.02.1, and I found no report tying 10.x to CAPT failures. — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- After a libxml2 upgrade (Arch, 2025-05-06), capt-src "no longer works". Fix: `libxml2-legacy` plus `ln -s /usr/lib32/libxml2.so /usr/lib32/libxml2.so.2`, or rebuild libglade/capt-src. — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- ccpd silently retries a missing library and leaks fds (Arch, 2026-04-09). Debug with strace and `LimitNOFILE=4096`. — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- Canon's README lists Ubuntu-specific cautions up to 14.10:
  - "If you cannot browse the IP address of localhost, you cannot start Status Monitor. Modify "/etc/hosts"…";
  - "If 15 or more characters are specified for the host name of Linux, the printer status may not display properly in Status Monitor";
  - "If you use the Cancel Job key on the printer unit to cancel jobs, the jobs from CUPS may not be cleared … delete the jobs using the CUPS interface";
  - deb upgrades from ≤ 2.60 need `dpkg -i --force-overwrite`.

  — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- The AUR maintainer warned on 2020-06-11: "Do not expect this driver to work in the near future if Canon doesn't release a new version soon. This driver is from 2017 and the GCC environment started deprecating a lot of stuff used by this driver." — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- The Ubuntu community pages that guides cite (`help.ubuntu.com/community/CanonCaptPrinterDriver`, `…/CanonCaptDrv190`) now redirect to wiki.ubuntu.com and return "page does not exist / search the wiki archives" (checked 2026-11-08). — [help.ubuntu.com CanonCaptDrv190](https://help.ubuntu.com/community/CanonCaptDrv190)

### Inferences
- Two of these root causes are verified properties of the package, not hearsay: the missing i386 dependencies, and "ccpd not started at boot" (no enablement in postinst). Both explain the common "queue Ready but nothing prints" and "ccpd not running" reports. A CaramOS integration should fix them by construction: install the i386 libraries, add a native unit, create the queue with the `ccp://` URI, add the udev symlink and the CUPS quirk.
- Whether jobs hang after the first one on a correct setup could not be tied to a root cause. Candidates are the usblp detach/re-enumeration from CUPS probes, and captmon2 failing because of missing 32-bit libraries. Both should be tested in the VM with a real LBP2900 passed through.

### Gaps
- I found no reachable, dated Linux Mint forum thread for Mint 21/22 with an LBP2900 and the official driver. A search for "forums.linuxmint.com LBP2900 Mint 21/22" surfaced none.
- No Ask Ubuntu Q&A specific to 22.04/24.04 was verified.
- Ubuntu Forums (ubuntuforums.org) did not resolve in DNS on 2026-11-08, so threads cited by other guides could not be checked.
- I found no Canon FAQ for the LBP2900 on Linux.

## 7. Does Canon publish any newer Linux driver that covers the LBP2900 (UFR II / Generic Plus / other)?

### Takeaway
No. For the LBP2900/2900B, Canon's support site lists only "CAPT Printer Driver for Linux V2.71" (2017) for Linux. No UFR II, Generic Plus or other Linux driver is offered for this model. The only newer Linux options for this printer are community open-source drivers, outside this note's scope.

### Cited Findings
- Canon Asia LBP2900/2900B model page: the single Linux item is CAPT V2.71 (15 May 2017). "UFR II / Generic Plus / other Linux drivers: None are listed for this model". — [Canon Asia LBP2900 model page](https://asia.canon/en/support/LASER%20SHOT%20LBP2900__%202900B/model?type=)
- Canon Europe's page reportedly lists V2.71 and older CAPT versions only. — [Canon Europe LBP2900](https://canon-europe.com/support/consumer_products/products/printers/laser/i-sensys_lbp2900.html) (search-engine summary; direct fetch returned 403)
- Canon's v2.71 support statement: Canon and the local Canon company "will not respond to any inquiries about this Software or Related Information". — [Canon Asia 0100459601](https://asia.canon/en/support/0100459601)
- AUR maintainers note that CAPT and UFR II are different driver families: "cndrvcups-lb … provide the UFR II drivers for Canon printers, which is different from the CAPT drivers". Each targets a specific `cndrvcups-common` version (CAPT 2.71 → common 3.21), so they conflict when installed together (2022-07-17). — [AUR capt-src comments](https://aur.archlinux.org/packages/capt-src)
- Out of scope, pointers only:
  - nixpkgs `canon-capt` 0.1.4.2-GxB is the open-source `mounaiban/captdriver` (`rastertocapt` filter, `CanonLBP-2900-3000.ppd`), not Canon's driver;
  - AUR `captdriver-git` r170 (last modified 2024-01-16);
  - AUR `canon-lbp2900-capt` 0.3.3-1 (GPL-3.0-or-later, upstream github.com/gauravyad69/Canon-LBP2900B, last modified 2026-11-05).

  — [nixpkgs canon-capt package.nix](https://raw.githubusercontent.com/NixOS/nixpkgs/master/pkgs/by-name/ca/canon-capt/package.nix); [AUR RPC info](https://aur.archlinux.org/rpc/v5/info?arg[]=capt-src&arg[]=captdriver-git&arg[]=canon-lbp2900-capt)

### Inferences
- Canon's Linux CAPT line has effectively been frozen since 2017: no release in more than 9 years, no 64-bit-clean filter, and GTK2 GUIs. CaramOS should treat it as abandonware that has to be wrapped, not as a maintained upstream.

### Gaps
- I did not check Canon's current UFR II / Generic Plus Linux driver supported-model lists directly. "No LBP2900" rests on the LBP2900 model page.

## 8. License: may CaramOS's PPA (ppa:vietnamlinuxfamily/caram-os) redistribute Canon's packages? If not, what is the legal way, and what do other distros do?

### Takeaway
**Not safely.**
- Canon's download terms allow only "personal, non-commercial use" and forbid distributing, publishing or reformatting the content.
- The shipped EULA allows copying and distribution only "on the Product" under Canon's own terms, with no sublicensing, so it is not an open-source license.
- Launchpad PPA policy accepts only OSI/FSF/DFSG-type licenses unless Canonical approves.
- The GPL/MIT parts can be redistributed, but they are useless without the proprietary Schedule-1 binaries (`ccpd`, `captfilter`, `captmon*`, Canon's libraries).

The legal pattern is a **downloader/installer** that fetches the archive from Canon's own URL on the user's machine at install time, checks the SHA-256, shows Canon's license, and installs it. Debian's `ttf-mscorefonts-installer` works this way. CaramOS can ship its own glue (systemd unit, udev rule, CUPS quirk, i386 dependencies) under its own license, in the PPA or as an App Center recipe.

### Cited Findings
- Canon Asia (Canon Singapore Pte. Ltd.) download disclaimer, verbatim, which the user must accept to download:
  > "Canon reserves all relevant title, ownership and intellectual property rights in the Content. You may download and use the Content solely for your personal, non-commercial use and at your own risks. … You shall not distribute, assign, license, sell, rent, broadcast, transmit, publish or transfer the Content to any other party. You shall also not (and shall not let others) reproduce, modify, reformat, disassemble, decompile or otherwise reverse engineer or create derivative works from the Content, in whole or in part. You agree not to send or bring the Content out of the country/region where you originally obtained it to other countries/regions without any required authorization of the applicable governments and/or in violation of any laws, restrictions and regulations. By proceeding to downloading the Content, you agree to be bound by the above as well as all laws and regulations applicable to your download and use of the Content."
  
  The same page states that "All software, programs (including but not limited to drivers), files … ("Content") are made available on this site on an "as is" basis." — [Canon Asia 0100459601](https://asia.canon/en/support/0100459601)
- Canon Vietnam carries the same terms in Vietnamese: "Bạn có thể tải xuống và sử dụng Nội dung chỉ cho mục đích sử dụng cá nhân, phi thương mại" and "Bạn không được phân phối, chuyển nhượng, cấp phép, bán, cho thuê…". — [Canon Vietnam 0100459601](https://vn.canon/vi/support/0100459601)
- [V] EULA §1/§2 (verbatim in Q2): a "personal, limited and non-exclusive license to … copy, have copied, distribute and permit third parties to use and copy the Software only on the Product … You shall distribute the Software to any third party under the same terms and conditions as contained herein", and "you shall not use, assign, sublicense, sell, rent, lease, loan, convey or transfer to any third party the Software". Schedule 2 (GPL v2) covers `ccp`, `pstocapt*`, `captstatusui`, `cngplp`, `cnusb`, `*.ppd`; Schedule 3 (MIT) covers `libcanoncapt`, `libcanonc3pl`, `buftool`. Everything else, including `ccpd`, `ccpdadmin`, `captfilter`, `captmon*`, Canon's libraries, `ccpd.conf` and the init script, is Schedule 1 (proprietary). — [Canon archive](https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz)
- Launchpad policy: "Content may be hosted in a Personal Package Archive ("PPA") on Launchpad if it is approved by Canonical or released under a license which falls under one or more of the following: …". The list covers OSI Approved, FSF Approved, DFSG Compliant, Ubuntu main/restricted license-policy compliant, and select Creative Commons. For other licenses, contact the Launchpad team "before uploading it"; Canonical may "refuse, or remove" non-conforming content. — [Launchpad policies](https://ubuntu.com/docs/launchpad/user/reference/launchpad-and-community/legal/launchpad-policies/)
- [V] No Canon CAPT driver package (`cndrvcups*` or similar) exists in Ubuntu noble main, universe or multiverse (amd64 indexes searched 2026-11-08). — [Ubuntu archive noble multiverse amd64](http://archive.ubuntu.com/ubuntu/dists/noble/multiverse/binary-amd64/Packages.xz)
- Downloader precedent in noble: `ttf-mscorefonts-installer` 3.8.1ubuntu1, Section `multiverse/x11`, "Installer for Microsoft TrueType core fonts", Depends `wget, ca-certificates, cabextract, xfonts-utils, update-notifier-common`. It is a tiny package that downloads the non-redistributable files at install time. — [packages.ubuntu.com noble ttf-mscorefonts-installer](https://packages.ubuntu.com/noble/ttf-mscorefonts-installer); [V] noble multiverse index
- What other distros do:
  - **Arch:** no official package. The AUR `capt-src` (license `custom`, 80 votes, first submitted 2010-08-29, last modified 2026-06-11) is a build recipe that downloads the archive from Canon's URL on the user's machine, checks `b2sums`, builds the GPL parts, installs Canon's prebuilt proprietary binaries plus Arch's own `ccpd.service`, and installs Canon's `LICENSE-EN.txt` to `/usr/share/licenses/capt-src/`.
  - An AUR comment (2018-09-14) suggests converting Canon's debs locally with `debtap`.
  - **Slackware:** SlackBuilds `system/cndrvcups-capt` 2.71 is a build script. Its source URL is a third-party mirror, byte-identical to Canon's Src tarballs, and its README notes "parts that are binary only and compiled on a 32bit system".
  - **ROSA Linux** (rosa_2019_1, rosa_13) packages `cndrvcups-capt` 2.71 in its repositories (license field "See the LICENSE*.txt file.").
  - **NixOS:** only the open-source captdriver under the name `canon-capt`.
  - **Fedora:** Repology shows no CAPT package.

  — [AUR capt-src PKGBUILD](https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD?h=capt-src); [AUR capt-src](https://aur.archlinux.org/packages/capt-src); [SlackBuilds cndrvcups-capt](https://slackbuilds.org/repository/15.0/system/cndrvcups-capt/); [Repology cndrvcups-capt](https://repology.org/api/v1/project/cndrvcups-capt); [Repology canon-capt](https://repology.org/api/v1/project/canon-capt)

### Inferences
- **The PPA should not contain Canon's binaries or Canon's debs**, repackaged or not. Launchpad accepts source uploads only, so the proprietary binaries would have to sit inside a source package, and Launchpad would then redistribute them. Canon's terms do not grant that (no sublicensing, personal non-commercial download terms). The license is not on Launchpad's accepted list. Repackaging (adding i386 Depends, a systemd unit, fixing maintainer scripts) is "modify/reformat/create derivative works", which the download terms forbid; the EULA only allows modification "for your own use". The two Canon texts conflict: the EULA permits distribution "only on the Product", the website forbids distribution. The conservative reading governs.
- The legally safer design, which is my inference and not legal advice:
  1. A CaramOS package in the PPA (e.g. `caramos-capt-installer`, avoiding "ccpd"/"captmon" in names and paths because of Canon's kill loop) that contains only CaramOS-authored files:
     - Depends on the i386 libraries and `libglade2-0`;
     - a native `ccpd.service`;
     - a udev symlink rule;
     - `/usr/share/cups/usb/caramos-capt.usb-quirks`;
     - a helper that, after an explicit user action, downloads `https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz` (or follows Canon's `pdisp01` redirect), checks size 127,521,219 and SHA-256 `8565a2fd…41be`, shows `Doc/LICENSE-EN.txt` and Canon's download disclaimer for acceptance, installs the two amd64 debs locally, then runs `lpadmin -v ccp://localhost:59687` and `ccpdadmin` to create the queue.
  2. Or an App Center recipe doing the same. Each user then gets the software directly from Canon under Canon's terms, as AUR and SlackBuilds users do.
- To ship Canon's files in the PPA, CaramOS would need written permission from Canon (Canon Singapore or Canon Marketing Vietnam) **and** Launchpad approval. Neither is likely to be quick.
- The GPL'd Schedule-2 sources (`Src/` tarballs) could be redistributed, e.g. a patched `captstatusui`. That gains nothing without Schedule-1 `ccpd`/`captfilter`, and the website terms still say "shall not … publish … the Content", so this should not be done either without clarification.

### Gaps
- No Canon statement or FAQ on third-party/distribution redistribution of the Linux CAPT driver was found. No legal opinion was obtained; Vietnam-specific law was not analysed.
- I did not confirm from the msttcorefonts source how `ttf-mscorefonts-installer` handles EULA acceptance (debconf), because packages.ubuntu.com's page does not show it.
- I did not check how ROSA justifies redistribution (non-free repository, or a permission from Canon).
