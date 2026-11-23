# Making the Canon LBP2900 / LBP2900B (and other CAPT printers) work on CaramOS 1.3.6: integration options, facts they depend on, and printer-less testing

Research date: 2026-11-08. Scope: CaramOS 1.3.6 = Linux Mint 22.3 Cinnamon on Ubuntu 24.04 "noble", amd64, CUPS 2.4.7. "lp2900" = Canon LBP2900 / LBP2900B.

How local sources were used (all read-only):
- **Mint 22.3 rootfs.** "Mint 22.3 rootfs" means the unpacked base system of `linuxmint-22.3-cinnamon-64bit.iso` ("Linux Mint 22.3 "Zena" - Release amd64 20260108") kept by the CaramOS build in `build/cache/`, with its package list in `build/cache_iso/casper/filesystem.manifest`.
- **Why the base rootfs stands for CaramOS here.** CaramOS 1.3.6 adds its own packages and hooks on top. A grep of `config/packages.txt` and `config/hooks/` found nothing about printing, so the printing stack below is Mint's. Mint's CUPS has since been updated: noble-updates now carries 2.4.7-1.2ubuntu7.14 from 2026-06-15, while the rootfs has 7.9.
- **CaramOS code.** "CaramOS code" is the tree at `749c025 [build] Release 1.3.6`, with the App Center submodule at 0.2.3.
- **Canon's driver and community repos.** A parallel researcher downloaded Canon's driver into the scratchpad (`.../scratchpad/lbp2900/official/`). They also cloned the community repos (`.../scratchpad/lbp2900/installers/`). I only read text files there and ran `file`/`sha256sum`. I executed nothing from them.

## 1. USB vendor:product IDs and IEEE 1284 device IDs of the LBP2900/LBP2900B and related CAPT models

### Takeaway
- **LBP2900 and LBP2900B.** Both are USB `04a9:2676` (two independent sources). The printer reports the IEEE 1284 ID `MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900`. That string comes from a real CUPS debug log. captdriver's exact `MDL` match corroborates it.
- **The other CAPT models.** IDs come from usb.ids and from the captdriver developer's device list. Their `MDL` strings can mostly be inferred from captdriver's model table.
- **Matching PPDs today.** Neither Canon's official PPDs nor upstream captdriver's PPDs carry a `*1284DeviceID`. So today nothing can match the printer to a driver automatically.

### Cited Findings
- **Canon IDs in usb.ids (version 2026.06.26), vendor 04a9:** 260a LBP810, 260e LBP-2000, 2617 LBP1210, 262b "LaserShot LBP-1120 Printer", 2631 LASER CLASS 700, 2633 LASERCLASS 500, 2636 LBP3200, 2654 LBP3600, 2657 LBP3210, 266a LBP3000, **2676 LBP2900**, 2679 LBP5000, 267e LBP3300, 2688 LBP3460, 268b LBP3500, 26a1 LBP5300, 26a4 LBP5100, 26b9 LBP3310, 26ba LBP5050, **26da LBP3010/LBP3018/LBP3050**, **26db LBP3100/LBP3108/LBP3150**, 26ea LBP9100C, 26f1 LBP7200C, 26ff LBP6300, **271a LBP6000**, 271b LBP6200, 271c LBP7010C/7018C, 2736 I-SENSYS MF4550d, **2771 LBP6020**, 2796 LBP6230/6240. On 2026-11-08 the HTTPS certificate of www.linux-usb.org did not match, so the file was fetched over HTTP. — [linux-usb.org usb.ids](http://www.linux-usb.org/usb.ids)
- **The captdriver developer's device list** (studycapt `docs/capt-lbp-devices.json`, commit 2026-08-12) has the same IDs for 260a, 2617, 262b, 2636, 2654, 2657, 266a, 2676, 2679, 267e, 268b, 26a1, 26a4, 26b9, 26ba, 26da, 26db, 26ea, 26f1, 26ff (LBP6300dn), 271a, 271b, 271c and 2771. It adds 266e LBP5200, which usb.ids does not list. — [mounaiban/studycapt](https://github.com/mounaiban/studycapt) (local clone `.../installers/mounaiban__studycapt/repo/docs/capt-lbp-devices.json`)
- **CAPT v1 IDs in captppd** (darkvision77/captppd v1.0.0, 2026-01-21). Its `dist/capt.usb-quirks` lists 0x04a9 0x260a LBP810, 0x262b LBP1120, 0x2617 LBP1210 and 0x2636 LBP3200, each marked "blacklist" for the stock CUPS usb backend. — [darkvision77/captppd](https://github.com/darkvision77/captppd)
- **A real LBP2900B on Ubuntu 12.04** shows `Bus 001 Device 007: ID 04a9:2676 Canon, Inc. CAPT Device` in lsusb (question asked 2012-05-06). This is independent hardware evidence that the LBP2900B uses 04a9:2676. It also shows that older usb.ids named the product "CAPT Device". — [Launchpad Answers #196221](https://answers.launchpad.net/ubuntu/+source/cups/+question/196221)
- **A Vietnamese toolkit (2026-07-24)** names "Canon LBP2900 / LBP2900B" with "vendor:product `04a9:2676`". — [brucenguyen1102/Canon-LBP2900-CAPT-Toolkit README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit)
- **A 2008 Fedora list post (search snippet only).** The search snippet says it shows dmesg with "Canon CAPT USB Device", idVendor=04a9 idProduct=2676 and `usblp1: error -32 reading printer status`. The page could not be fetched (DNS failure), so this is unverified. — [fedora-list 2008-06](https://listman.redhat.com/archives/fedora-list/2008-June/303044.html)
- **Name shown on Mint 22.3.** The rootfs hwdb maps `usb:v04A9p2676*` to `ID_MODEL_FROM_DATABASE=LBP2900`. — [Mint 22.3 rootfs: 20-usb-vendor-model.hwdb](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/hwdb.d/20-usb-vendor-model.hwdb)
- **The real IEEE 1284 ID of an LBP2900**, from a CUPS debug log posted in a captdriver issue on 2021-11-30, is `MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900`. — [agalakhov/captdriver issue #37](https://github.com/agalakhov/captdriver/issues/37)
- **How captdriver identifies the model.** It asks the CUPS backend for the device ID, takes the `MDL`/`MODEL` field and compares it exactly (`strcmp`) with its registered names, quitting with "unknown printer" if none matches. Registered names and states:
  - `"LBP2900"`: WORKS
  - `"LBP3000"`: EXPERIMENTAL
  - `"LBP3010/LBP3018/LBP3050"`: WORKS
  - `"LBP3100/LBP3108/LBP3150"`: EXPERIMENTAL
  - `"LBP6000/LBP6018"`: EXPERIMENTAL

  — [mounaiban/captdriver src/printer.c and src/prn_lbp2900.c](https://github.com/mounaiban/captdriver) (master 6271924, 2022-10-14)
- **captppd's device ID strings for CAPT v1:**
  - `MFG:Canon;MDL:LBP-810;CMD:CAPT;VER:1.0;CLS:PRINTER;DES:Canon LBP-810`
  - `MFG:Canon;MDL:LASER SHOT LBP-1120;CMD:CAPT;VER:1.0;CLS:PRINTER;DES:Canon LASER SHOT LBP-1120`
  - `MFG:Canon;MDL:LBP3200;CMD:CAPT;VER:1.0;CLS:PRINTER;DES:Canon LBP3200`
  - LBP-800 is marked "assumed from LBP810" and LBP1210 is "TODO".
  - Its tests also accept variants such as `MDL:LBP 3200` and `VER:2.0`.

  — [darkvision77/captppd ppd/captppd.drv, tests/PrinterInfoTest.cpp](https://github.com/darkvision77/captppd)
- **Canon's official v2.71 PPD for the LBP2900** (`CNCUPSLBP2900CAPTK.ppd`) has `*Product: "(LBP2900)"`, `*ModelName: "Canon LBP2900 CAPT English"`, `*NickName: "Canon LBP2900 CAPT ver.1.5"` and filter `application/vnd.cups-postscript 0 pstocapt`. None of the official v2.71 PPDs contains `*1284DeviceID`. — [Canon linux-capt-drv-v271-uken, local extract](file:///tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/official/root-v271-amd64/usr/share/cups/model/CNCUPSLBP2900CAPTK.ppd)
- **Upstream captdriver PPDs.** The PPD source `canon-lbp.drv` has no `1284DeviceID`. It builds one PPD for "LBP2900/LBP3000 r2c" (`CanonLBP-2900-3000.ppd`) and one for "LBP3010/LBP3018/LBP3050 r2c". There is no LBP6000 PPD in it. The older PPDs in agalakhov's repo ("Canon Inc LBP2900/LBP3010 r2c", "Canon Inc LBP3000 r2c") have no device ID either. — [mounaiban/captdriver src/canon-lbp.drv](https://github.com/mounaiban/captdriver); [agalakhov/captdriver](https://github.com/agalakhov/captdriver) (175f8ff, 2022-10-08)
- **A packaged captdriver with device IDs** (sanhos95, 2026-11-04). Its packaging generates per-model PPDs with `*1284DeviceID: "MFG:Canon;MDL:{mdl};CMD:CAPT;"` for `LBP2900`, `LBP3010/LBP3018/LBP3050` and `LBP6000/LBP6018`. It lists LBP2900 and LBP2900B as the same supported model. — [sanhos95/canon-capt-linux-driver packaging/mkppd.py and README](https://github.com/sanhos95/canon-capt-linux-driver)

### Inferences
- **IDs confirmed by two or more sources.** These have two or more listings: 2676 (usb.ids plus independent real lsusb/dmesg), 260a, 262b, 2617, 2636 (usb.ids, studycapt, captppd), and 266a, 26da, 26db, 271a, 2771, 267e (usb.ids plus studycapt). studycapt may have copied usb.ids, so for the second group "two sources" is weaker than truly independent confirmation.
- **The LBP2900 and LBP2900B share 04a9:2676** (Launchpad 2012 plus the Vietnamese toolkit). Canon ships one "LBP2900/2900B" driver. One USB ID rule therefore covers both.
- **MDL strings for the other models.** For LBP3010/3018/3050 the MDL is very likely exactly `LBP3010/LBP3018/LBP3050`, because captdriver marks it WORKS on an exact match. LBP6000/6018 is likely `LBP6000/LBP6018` (sanhos95 reports success on a real LBP6000 with Mint 22). The ID string pattern is `MFG:Canon;MDL:<model>;CMD:CAPT;VER:x;CLS:PRINTER;DES:Canon <model>`.
- **Writing `*1284DeviceID` lines.** These should carry at least `MFG:Canon;MDL:<exact MDL>;CMD:CAPT;`. They should not use the `DES` or `VER` fields, which vary by firmware.
- **LBP6018.** It probably has no ID of its own: it shares 271a with the LBP6000, going by the combined MDL. This is unverified.

### Gaps
- **Real device ID strings still missing.** No real-printer log was found for LBP3000, LBP3100/3108/3150, LBP3300, LBP6020 or LBP1210, nor for the LBP2900B itself (assumed identical to the LBP2900).
- **linux-hardware.org.** It returned HTTP 429 twice for `usb:04a9-2676`, so I have no probe counts or interface descriptors from it.
- **Exact interface descriptor.** I found no primary lsusb -v dump confirming the LBP2900's bInterfaceClass/SubClass/Protocol. It is assumed to be 07/01/02 (bidirectional printer), since captdriver relies on the bidirectional channel.

## 2. What happens on noble / Linux Mint 22.3 when such a printer is plugged in

### Takeaway
- **Plugging in starts automatic setup but cannot match a driver.** On Mint 22.3 / CaramOS the kernel binds `usblp`, which no package blacklists. system-config-printer-udev's rule then starts `configure-printer@…`, which reads the 1284 ID and asks cupshelpers for an exactly matching PPD. No installed PPD matches CAPT, so no correct queue is created.
- **What the user sees instead.** Cinnamon's `csd-printer` receives the "new printer" call and can show "Missing printer driver" or try its own automatic setup. A field report from Mint 22 says this picks an unrelated PostScript driver.
- **Services that play no part.** ipp-usb and cups-browsed are not involved.
- **Driver Check is silent.** Because `usblp` binds, the printer counts as "working" in today's check.

### Cited Findings
- **Printing packages in the Mint 22.3 manifest (20260108):**
  - CUPS: `cups 2.4.7-1.2ubuntu7.9`, `cups-daemon`, `cups-browsed 2.0.0-0ubuntu10.3`, `cups-filters 2.0.0-0ubuntu4.1`
  - IPP over USB: `ipp-usb 0.9.24-0ubuntu3.3`
  - Printer tool: `system-config-printer`, `system-config-printer-common`, `system-config-printer-udev 1.5.18-1ubuntu9`, `python3-cupshelpers`
  - Package management and USB: `packagekit 1.2.8+mint2+xia`, `libusb-1.0-0 1.0.27`
  - PPD collections: `foomatic-db-compressed-ppds` and `openprinting-ppds 20230202-1`
  - Drivers: hplip 3.23.12 and printer-driver-brlaser, c2esp, foo2zjs, gutenprint, hpcups, m2300w, min12xxw, pnm2ppa, postscript-hp, ptouch, pxljr, sag-gdi, splix

  `filesystem.manifest-remove` lists none of these. There is no CAPT driver. — [Mint 22.3 filesystem.manifest](file:///home/dungleviet/Documents/CaramOS/build/cache_iso/casper/filesystem.manifest)
- **No CAPT driver package exists in Ubuntu.** packages.ubuntu.com has no captdriver or printer-driver-capt in jammy, noble, resolute, stonking or tenacious (searched 2026-11-08). — [packages.ubuntu.com search "capt"](https://packages.ubuntu.com/search?keywords=capt&searchon=names&suite=all&section=all)
- **usblp is present and not blacklisted.** The Mint 22.3 kernel 6.14.0-37-generic ships `kernel/drivers/usb/class/usblp.ko.zst` (`CONFIG_USB_PRINTER=m`). No file in `/etc/modprobe.d` or `/usr/lib/modprobe.d` mentions usblp. — [Mint 22.3 rootfs modprobe.d](file:///home/dungleviet/Documents/CaramOS/build/cache/etc/modprobe.d/), [boot config](file:///home/dungleviet/Documents/CaramOS/build/cache/boot/config-6.14.0-37-generic)
- **The udev rule** `70-printers.rules` (system-config-printer-udev) does the following:
  - On add, for a usb_device with an interface matching `*:0701??:*` but not `*:070104:*`, it sets `TAG+="systemd", ENV{SYSTEMD_WANTS}="configure-printer@usb-$env{BUSNUM}-$env{DEVNUM}.service"`.
  - On remove, it runs `udev-configure-printer remove`.
  - Its comments map 7/1/1 to the usb backend (one-way), 7/1/2 to the usb backend (two-way), 7/1/3 to the hp backend and 7/1/4 to ipp-usb.

  — [Mint 22.3 rootfs 70-printers.rules](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/rules.d/70-printers.rules)
- **The service** `configure-printer@.service` runs `/lib/udev/udev-configure-printer add "%i"` with `Requires=cups.socket`. The `udev-configure-printer` binary contains strings for libusb control transfers, `ieee1284_id`, `/usblp%s`, `device-id` and `udev-add-printer`. — [configure-printer@.service](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/systemd/system/configure-printer@.service), [udev-configure-printer](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/udev-configure-printer)
- **What `udev-add-printer` does, in order:**
  - It calls `com.redhat.PrinterDriversInstaller.InstallDrivers(MFG, MDL, CMD)`.
  - It asks `cupshelpers` `getPPDNameFromDeviceID(MFG, MDL, DES, CMD, uri)` for a driver.
  - It creates a queue only when the status is 0, an exact match. The queue name is MDL with `/` and spaces replaced by `-`.
  - In every case it then calls `com.redhat.NewPrinterNotification.NewPrinter(status, name, MFG, MDL, DES, CMD)`.

  — [Mint 22.3 rootfs udev-add-printer](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/udev-add-printer)
- **How cupshelpers grades a match.** Status codes are SUCCESS 0, MODEL_MISMATCH 1, GENERIC_DRIVER 2 and NO_DRIVER 3. With no fit at all it falls back to `textonly.ppd`, then `postscript.ppd`, and otherwise "choosing any" (the first PPD). Neither textonly.ppd nor postscript.ppd exists under `/usr/share/ppd` or `/usr/share/cups/model` in the rootfs. — [cupshelpers/ppds.py](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/python3/dist-packages/cupshelpers/ppds.py)
- **Cinnamon's `csd-printer`** (cinnamon-settings-daemon) owns `com.redhat.NewPrinterNotification` and `com.redhat.PrinterDriversInstaller`. Its strings include:
  - Notification texts: "Missing printer driver", "No printer driver for %s.", "No driver for this printer.", "Configuring new printer", "AutoConfigure"
  - PackageKit: `InstallPrinterDrivers` and `org.freedesktop.PackageKit.Modify`
  - Queue setup through `org.fedoraproject.Config.Printing`: `GetBestDrivers`, `PrinterAdd`, `PrinterSetEnabled`, `PrinterSetAcceptJobs`

  `csd-print-notifications` has "Printer added" and "There is a missing print filter for printer '%s'." — [csd-printer](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/libexec/csd-printer), [csd-print-notifications](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/libexec/csd-print-notifications)
- **No session-bus provider of `org.freedesktop.PackageKit`.** None exists in `/usr/share/dbus-1/services`; only the system service `org.freedesktop.PackageKit.service` is present. — [Mint 22.3 rootfs dbus-1](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/share/dbus-1/)
- **The system-config-printer tray applet does not run in Cinnamon.** Its autostart entry has `NotShowIn=KDE;GNOME;Cinnamon;LXDE;Unity;`. — [print-applet.desktop](file:///home/dungleviet/Documents/CaramOS/build/cache/etc/xdg/autostart/print-applet.desktop)
- **The printer tool's own fallback.** In the New Printer dialog, system-config-printer queries OpenPrinting when there is "No exact driver match" (`nextNPTab`, `OpenPrintingRequest`). It can install a found driver package through PackageKit (`install-printerdriver`). — [newprinter.py lines ~976, 1663–1681](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/share/system-config-printer/newprinter.py)
- **ipp-usb's udev rule** `71-ipp-usb.rules` only fires for interface `*:070104:*` (IPP-over-USB) and for HP's `ff0901`. — [71-ipp-usb.rules](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/rules.d/71-ipp-usb.rules)
- **cups-browsed's only active setting** is `BrowseRemoteProtocols dnssd`. — [cups-browsed.conf](file:///home/dungleviet/Documents/CaramOS/build/cache/etc/cups/cups-browsed.conf)
- **How the CUPS 2.4.7 libusb backend works:**
  - If `usblp` is bound it detaches it (`libusb_detach_kernel_driver`) and reattaches it after the job, unless the `no-reattach` quirk is set.
  - It answers the side-channel commands `GET_DEVICE_ID`, `DRAIN_OUTPUT`, `GET_BIDI` and `GET_STATE`, and runs a backchannel read thread.
  - It loads quirks from every file in `/usr/share/cups/usb`.

  — [OpenPrinting/cups v2.4.7 backend/usb-libusb.c](https://github.com/OpenPrinting/cups/blob/v2.4.7/backend/usb-libusb.c) (lines ~725, 1144–1224, 1471–1476, 1715–1872)
- **Noble has no quirk for any CAPT printer.** Its `org.cups.usb-quirks` has no entry for 04a9:2676 or any LBP. The Canon entries are PIXMA/MP models (`unidir`), MF4150 (`no-reattach`) and SELPHY (`blacklist`). — [org.cups.usb-quirks](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/share/cups/usb/org.cups.usb-quirks)
- **A known race in the CUPS USB backend.** It was reported on 2025-12-28 (OpenPrinting/cups#1461, "Race condition in CUPS USB backend with bi-dir communication"; a CAPT filter was the trigger) and closed on 2026-03-09. The fix (PR #1500) was merged into 2.4.x and master, with milestone v2.5. — [OpenPrinting/cups#1461](https://github.com/OpenPrinting/cups/issues/1461)
- **The fix has not reached Ubuntu.** No noble CUPS changelog entry up to 2.4.7-1.2ubuntu7.14 (2026-06-15) mentions #1461 or a USB race fix. resolute (26.04) has 2.4.16-1ubuntu1.3 and stonking/tenacious have 2.4.16-1ubuntu3. — [Launchpad cups changelog](https://launchpad.net/ubuntu/+source/cups/+changelog)
- **Field report from a real Mint 22 + LBP6000 setup (sanhos95, 2026-11-04).** It names three problems:
  - "The upstream PPDs have no IEEE 1284 Device ID, so when the printer is plugged in, Linux Mint's automatic printer setup can't match it and picks an unrelated PostScript driver … jobs hang at Sending data to printer."
  - AppArmor blocks a filter left in `/usr/local` (exit 113).
  - A VirtualBox USB filter can capture the printer.

  — [sanhos95/canon-capt-linux-driver README](https://github.com/sanhos95/canon-capt-linux-driver)
- **Field notes tested on Ubuntu 26.10 (suluoniu, 2026-11-01).** They say that "`usblp` must not hold the device. Blacklist it". They say a stray quirks backup containing `0x04a9 0x2676 unidir` "kills the back-channel". They also note that Ubuntu runs cupsd with `IdleExitTimeout 60` plus socket activation. — [suluoniu/captdriver-lbp2900 README](https://github.com/suluoniu/captdriver-lbp2900)
- **How Driver Check treats USB devices today.** `USB_STANDARD_CLASSES` includes `"07"` (printer). `_other()` reports a USB device only when none of its standard-class interfaces has a driver bound. If a matching module exists but is blacklisted, `_explain()` tells the user that "Its driver (%s) is turned off by a 'blacklist %s' line in %s. Remove that line…". — [hardware.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/hardware.py), [analysis.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/analysis.py)

### Inferences
- **What should happen at plug-in, step by step** (from the code above; not yet tested with a device or emulator):
  1. usblp binds and creates `/dev/usb/lp0`.
  2. `configure-printer@usb-B-D.service` starts and reads `ieee1284_id`.
  3. CUPS lists `usb://Canon/LBP2900?serial=…`.
  4. `udev-add-printer` finds no exact PPD, so it creates no queue and calls `NewPrinter(status≠0, …)` on csd-printer.
  5. csd-printer either shows "Missing printer driver" or autoconfigures with `GetBestDrivers`. The second path would explain the field report of an unrelated (PostScript or "any") driver being chosen. Which one happens should be checked in a VM, see §5.
- **PackageKit route.** The driver-install route through `InstallPrinterDrivers` (PackageKit session interface) probably has no provider on Mint, so nothing installs a driver automatically.
- **ipp-usb and cups-browsed play no part.** The LBP2900 (launched 2007) has no IPP-over-USB interface, and cups-browsed only handles DNS-SD network printers.
- **Two consequences of the usblp question:**
  - With stock settings usblp binds, so Driver Check sees the printer interface as having a driver and shows nothing for an unusable CAPT printer.
  - If CaramOS followed suggestions to blacklist usblp, Driver Check would start telling users to remove that blacklist line. Any CAPT integration has to special-case this.
- **Stock-CUPS captdriver will be slow.** Noble's CUPS lacks the #1461 fix. captdriver sends `DRAIN_OUTPUT` after each 4096-byte chunk and keeps going on a 1-second timeout ("output already empty, not drained", seen in `capt-command.c`). So captdriver on stock noble CUPS will probably print slowly or with odd delays, consistent with the wiki's "long delays between pages".

### Gaps
- No live test was possible: no printer, and the host's libvirt VMs were off-limits. The csd-printer branch (notification or auto-setup) and which fallback PPD gets picked are inferred from strings and code, not observed.
- I did not open Linux Mint's documentation on printers, so it is not known whether Mint documents CAPT printers.

## 3. Integration options (a)–(e): effort, risks, maintenance, user experience

### Takeaway
- **Best user experience for the LBP2900/LBP3010/LBP6000 family: option (a).** Ship captdriver as `printer-driver-captdriver` in the CaramOS PPA with per-model `*1284DeviceID` PPDs. The standard udev → udev-configure-printer path then creates the queue automatically.
  - On noble it also needs a USB-backend fix for cups#1461, best shipped as a separately named backend rather than a rebuilt `cups`.
- **For models captdriver does not cover** (notably the **LBP3300** named in CaramOS issue #39), only Canon's official driver works. Its licence allows unmodified redistribution, but Launchpad's terms keep it out of a public PPA. So it fits a downloader (option b) triggered by Driver Check (option c).
- **Later options.** (d) Printer Applications are the long-term CUPS 3 path, not needed on a noble base. (e) A custom udev rule is only needed for the official driver's `ccpd` or for repairing queues.

### Cited Findings
- **(a) captdriver itself.**
  - It is GPLv3 and "unofficial software not endorsed or authorised by Canon". — [mounaiban/captdriver README](https://github.com/mounaiban/captdriver)
  - The wiki (edited 2026-05-19) lists combinations "found to work": LBP2900 (x86-64 Manjaro, Void; ARMv7 Ubuntu 19.10/20.04.2/22.04), LBP3000, LBP3010, LBP3100/3108/3150 (inferred; use the 3010 PPD) and LBP6000/6018 (Kubuntu, Issue #11). It states "two significant issues": compatibility problems with the CUPS-libusb interface and long delays between pages. — [captdriver wiki](https://github.com/mounaiban/captdriver/wiki)
- **(a) ValdikSS fork** (GPL-3.0). It fixes:
  - wrong paper dimensions
  - shifted printing after page 1
  - slow printing and the delay before the first print
  - pages larger than the printer's RAM ("streaming mode")
  - error and state handling

  It "requires CUPS v2.4.17+" because of the USB race fix. It cannot resume after a jam, open door or missing cartridge, and supports LBP2900, LBP3000 and LBP6000. — [ValdikSS/captdriver](https://github.com/ValdikSS/captdriver) (fetched 2026-11-08; commit date not shown)
- **(a) A ready-made precedent.** sanhos95's repo (2026-11-04) already builds `printer-driver-captdriver_…_amd64.deb` "with a double click". It uses captdriver plus muxoc/captdriver-lbp6000, ships PPDs with Device IDs, installs the filter as a real file (because of AppArmor) and adds a `setup-queues` script that repairs existing queues with `lpadmin`. It reports:
  - Working: LBP2900/2900B, LBP3010/3018/3050, LBP6000/6018/6000B (tested on Mint 22)
  - Experimental: LBP3000, LBP3100/3108/3150
  - Not supported: LBP6020, LBP6030, LBP7010C and the colour models

  — [sanhos95/canon-capt-linux-driver](https://github.com/sanhos95/canon-capt-linux-driver)
- **(a) Community claims of other bugs.**
  - A Vietnamese toolkit (2026-07-24) patches the CUPS USB backend for cups#1461 (patches by ValdikSS dated 2026-02-26). It also claims an engine hang at exactly the 5th job after power-on (`ReserveUnit failed 0x8c`), which it works around with a persistent daemon. — [brucenguyen1102/Canon-LBP2900-CAPT-Toolkit](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit)
  - suluoniu reports a backchannel desync after a cancelled job ("bad reply from printer, expected A1 A1…"). — [suluoniu/captdriver-lbp2900](https://github.com/suluoniu/captdriver-lbp2900)
- **(a) Hosting.** The CaramOS PPA is `ppa:vietnamlinuxfamily/caram-os`, as configured by caramos-ota. — [caramos_ota/constants.py, repo.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota/constants.py)
- **(a) Launchpad allows PPA content** "approved by Canonical" or under OSI-, FSF- or DFSG-approved licences, Ubuntu main/restricted-compliant licences, or the listed Creative Commons licences. Other licences need approval through the Launchpad users list (page undated, © 2026). — [Launchpad terms of service](https://canonical.com/legal/launchpad-terms-of-service)
- **(b) Canon licence** (`LICENSE-EN.txt` in v2.71):
  - Canon grants "a personal, limited and non-exclusive license to use …, have used, copy, have copied, distribute and permit third parties to use and copy the Software only on the Product".
  - "You may modify the Software only for your own use".
  - "You shall distribute the Software to any third party under the same terms".
  - Otherwise there is no right to "sublicense, sell, rent, lease, loan, convey or transfer".
  - GPLv2 components are listed separately.

  — [Canon LICENSE-EN.txt (local extract)](file:///tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/official/extract-v271/linux-capt-drv-v271-uken/Doc/LICENSE-EN.txt)
- **(b) The official download** `linux-capt-drv-v271-uken.tar.gz` (Canon Asia, ID 0100004596-05):
  - Served from S3/CloudFront: 127,521,219 bytes, Last-Modified 2025-03-31, SHA-256 `8565a2fdc4f452bb8cf97ceadadd6614d12eac73e253ac6d59e61b8abae941be`.
  - It contains cndrvcups-common 3.21 and cndrvcups-capt 2.71 debs for amd64 and i386, with control files dated 2017-04-07.
  - In the amd64 package `ccpd` is x86-64 but `captfilter` is a 32-bit i386 ELF.
  - Model PPDs: LBP1120, 1210, 2900, 3000, 3050, 3100, 3150, 3200, 3210, 3250, **3300**, 3310, 3500, 3600, 5000, 5050, 5100, 5300, 6018, **6020**, 6200, 6300(n), 6310, 6340, 7010C, 7018C, 7200C, 7210C, 9100C, 9200C.

  — [local download headers](file:///tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/official/asia-gds-0100004596-05/headers.txt), [extracted debs](file:///tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/official/root-v271-amd64/)
- **(b) A common community hotplug rule** for Canon's driver is a udev rule `SUBSYSTEM=="usb", ATTRS{idVendor}=="04a9", ATTRS{idProduct}=="2676", ACTION=="add", RUN+="/bin/systemctl restart ccpd.service"`. — [Siddharth903/Ubuntu_CanonLBP2900_Printer_fixed README](https://github.com/Siddharth903/Ubuntu_CanonLBP2900_Printer_fixed) (2025-09-01). Other community installers in the local clones also restart ccpd (e.g. [ethicalvulnlab/canon-capt-linux](https://github.com/ethicalvulnlab/canon-capt-linux), [brucenguyen1102/Canon-LBP2900-CAPT-Toolkit](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit)).
- **(d) pappl-retrofit** "Even more complex filters and backends which use the side and back channel communication are supported". The Legacy Printer Application "uses the (classically installed) CUPS backends … by default". "Naturally only PPDs work for which the appropriate CUPS filters are available". "Some drivers may not work in the different environment". It needs libcups ≥ 2.2, PAPPL ≥ 1.3, libcupsfilters and libppd, and can be packaged as a Snap. — [OpenPrinting/pappl-retrofit](https://github.com/OpenPrinting/pappl-retrofit) (fetched 2026-11-08)
- **(d) OpenPrinting plans** (talk at Opportunity Open Source 4.0, 2026-08-29):
  - CUPS 2.5 beta1 "in the coming weeks".
  - CUPS 3.x: libcups3 3.0.1 is stable; "Printer Applications required for legacy printers"; "To be removed: PPD support, Kerberos support"; "All components to be released up to January/February 2027"; "Switchover in possible in e. g. Ubuntu 27.10 (27.04 very close after release)".
  - Setup tools should list "discovered non-driverless USB/network printers" with a "Button to see list of Printer Applications supporting the printer … available in Snap Store (look-up service on OpenPrinting)", while "Do not remove support for permanent CUPS queues and classic drivers".
  - Funding: Sovereign Tech Fund, Oct 2025 – Dec 2026.

  — [talk-openprinting-2026.pdf](https://events.canonical.com/event/154/contributions/1013/attachments/535/865/talk-openprinting-2026.pdf)
- **(d) Earlier signals (search summaries only, not opened).** The 2025 OpenPrinting talk targeted Ubuntu 26.10 rather than 26.04 for the switchover. — [talk-openprinting-2025.pdf](https://events.canonical.com/event/134/contributions/751/attachments/411/661/talk-openprinting-2025.pdf). The Register reported on 2025-08-04 that Canonical had laid off OpenPrinting lead Till Kamppeter. — [The Register](https://www.theregister.com/2025/08/04/canonical_drops_openprinting_lead/)
- **(d) Mint blocks snapd.** It ships `/etc/apt/preferences.d/nosnap.pref` pinning `snapd` to -10. — [nosnap.pref](file:///home/dungleviet/Documents/CaramOS/build/cache/etc/apt/preferences.d/nosnap.pref)
- **(e) The existing rule already detects printers.** `70-printers.rules` uses `ENV{SYSTEMD_WANTS}` with a templated service rather than a long-running `RUN+=`, which is the model for any extra rule. — [70-printers.rules](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/udev/rules.d/70-printers.rules)

### Inferences
These are assessments, not verified facts.

- **(a) printer-driver-captdriver in the CaramOS PPA.** Best user experience for LBP2900/2900B, LBP3010/3018/3050 and LBP6000/6018.
  - *What to build:*
    1. A source package from a pinned fork, probably ValdikSS for the fixes plus the LBP6000 support sanhos95 merged. Re-check each fork's licence and state before choosing.
    2. Per-model PPDs with `*1284DeviceID` (`MFG:Canon;MDL:LBP2900;CMD:CAPT;` and so on). The drv `Attribute "1284DeviceID" "" "…"` directive works, as captppd shows.
    3. The filter in `/usr/lib/cups/filter`, which AppArmor allows.
    4. A fix for cups#1461 on noble's 2.4.7, in one of two ways:
       - *Preferred:* ship a renamed copy of CUPS's `usb-libusb.c` with PR #1500 as its own backend (e.g. `captusb`). Add a quirks file that blacklists the CAPT IDs for the stock `usb` backend, so only the fixed backend offers them. captppd uses the same pattern.
       - *Alternative:* rebuild `cups` in the PPA. This shadows Ubuntu's security updates, so every USN would have to be re-merged. Not recommended.
    5. A `Modaliases:` header (see option c) so ubuntu-drivers can see it.
  - *Expected result:* plug in → `udev-add-printer` finds an exact match (status 0) → queue "LBP2900" → Cinnamon shows "Printer added". The CAPT IDs must come from real devices.
  - *Effort:* medium, roughly 1–2 weeks of packaging and backend work plus real-printer testing.
  - *Risks:* a reverse-engineered driver, with no resume after a jam, cancel desync and the claimed job-5 hang. A backend copy is code CaramOS must patch for security itself. It covers only some models: no LBP3300 or LBP6020.
  - *Maintenance:* low churn, but CaramOS becomes the de facto maintainer of the fork.
  - *Legal:* clean (GPLv3 fits Launchpad's terms).
- **(b) Downloader for Canon's official driver.** Covers far more models, including the LBP3300 and LBP6020.
  - *Legal:* the licence seems to allow redistributing the unmodified package under Canon's terms. It does not allow distributing modified binaries. Canon's licence is none of Launchpad's accepted kinds, so the public PPA cannot host it without Canonical's approval.
  - *Design:* an App Center recipe or a Driver Check action that downloads from Canon over HTTPS, checks the pinned SHA-256 and installs the Canon debs unchanged. It then enables i386 multiarch, because `captfilter` is 32-bit, and configures `ccpd` (`ccpdadmin`, an `lpadmin` queue on `ccp://…` with the Canon PPD).
  - *Also needed:* keep the stock usb backend and udev auto-setup from creating a competing queue, for example with a usb-quirks blacklist, plus a udev hotplug restart for ccpd.
  - *Effort:* medium.
  - *Risks:* 2017-era closed binaries, i386 libraries on every such machine, ccpd fragility (covered by other researchers), and Canon URL changes. The SHA-256 pin turns a silent change into a clear failure.
  - *User experience:* "a few clicks", plus a ~128 MB download.
- **(c) Driver Check detects the printer and offers the install.** The best way to deliver (a) and/or (b) in a few clicks. The code is already shaped for it (§4). Its value is that it explains a printer that is currently invisible to the user and offers the right fix. It can also repair a queue that was set up with the wrong driver.
- **(d) captdriver Printer Application** (pappl-retrofit, maybe a Snap).
  - *Why it matters:* future-proof for CUPS 3 and portable across distributions.
  - *Why not now:* CaramOS on noble keeps CUPS 2.4 with PPD support. Mint blocks snapd, so it would have to be a .deb anyway. Whether the side-channel calls `rastertocapt` makes (`GET_DEVICE_ID`, `DRAIN_OUTPUT`) work in pappl-retrofit's emulated environment is plausible from the README but unproven.
  - *Effort:* high now, low priority. Revisit when CaramOS moves to a base with CUPS 3, which on OpenPrinting's plan is not before Ubuntu 27.04/27.10.
- **(e) Custom udev rule plus lpadmin helper.**
  - *Not needed for (a):* with 1284-ID PPDs the stock rule already does the work.
  - *Useful for:* (1) the official driver, to restart or attach ccpd on replug through `SYSTEMD_WANTS`; (2) repairing a queue created with a wrong PPD before the driver was installed, the problem sanhos95's `setup-queues` exists to fix; (3) telling the user to open Driver Check.
  - *Risks:* races with `configure-printer@` and csd-printer's autoconfigure, which could create duplicate queues.

### Gaps
- Whether `udev-configure-printer` would pick a `captusb://` URI over `usb://` when both backends list the device is untested. Its matching logic in the C source was not reviewed.
- No lawyer's reading of Canon's licence. "Only on the Product" is ambiguous, so whether CaramOS may mirror the unmodified tarball is open.
- The fork state (ValdikSS commit dates, muxoc/captdriver-lbp6000) was not checked in detail, to save GitHub requests.

## 4. Grounding options (b) and (c) in the CaramOS code: where a USB printer check and an install action fit

### Takeaway
- **Driver Check already has the pieces:** sysfs USB scan, a small knowledge table, findings with actions, and a privileged pkexec helper that installs packages only after re-checking them against ubuntu-drivers' hardware match.
- **A CAPT printer check fits as** a `knowledge.py` table plus an `analysis.py` area. The install goes through the existing `INSTALL` action if the PPA package carries a `Modaliases:` header and is added to `ONE_CLICK`.
- **The App Center can host an official-driver recipe** with its existing `recipe` mechanism. It has no hardware detection, so Driver Check should be what offers it.

### Cited Findings
- **Driver Check reads hardware from sysfs and the udev database without root**, "so the check can run at every login". `SystemReader(root=…)` lets tests build a fake system tree. `usb_devices()` reads `idVendor`, `idProduct`, the interfaces (class, subclass, protocol, bound driver, modalias) and a name from `ID_MODEL_FROM_DATABASE`. — [hardware.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/hardware.py)
- **`knowledge.py` is "Kept small on purpose".** It holds what the kernel cannot tell: Broadcom Wi-Fi, NVIDIA, Intel IPU cameras and fingerprint readers, as predicates on `Device` such as `broadcom_wifi()`, `nvidia_gpu()` and `fingerprint_like()`, plus frozensets of IDs. — [knowledge.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/knowledge.py)
- **How `analysis.py` reports.** It has areas `AREAS = ("wifi", "ethernet", "graphics", "audio", "bluetooth", "camera", "fingerprint", "other")` and levels `absent/ok/tip/info/warning/critical`. `Finding` has `actions` of kind `install`, `driver-manager`, `update-manager`, `reboot`, `wifi-on`, `fingerprints` or `report`; an install action carries a `target` such as `"nvidia:580-open"` or a package name. `report()` calls `_network()`, `_graphics()`, `_audio()`, `_bluetooth()`, `_camera()`, `_fingerprint()`, `_other()` and `_other_proposals()`. `_other_proposals()` turns ubuntu-drivers proposals into a TIP "Recommended driver for %s" with `Action(INSTALL, …, proposal.target)`. — [analysis.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/analysis.py)
- **How `drivers.py` proposes installs.** `ONE_CLICK = ("nvidia-driver-*", "bcmwl*", "broadcom-sta-dkms", "virtualbox-guest*", "open-vm-tools*")`, and `ON_INSTALL_MEDIA` lists packages on the CaramOS USB stick. `wanted(snapshot)` runs the slow UbuntuDrivers lookup only for NVIDIA, Broadcom Wi-Fi without a driver, or VirtualBox/VMware. `proposals_from()` reads `UbuntuDrivers.detect.system_device_drivers()`. — [drivers.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/drivers.py)
- **The privileged helper** (`caramos-driver-check-helper install <target>…`, through pkexec) works like this:
  - It "does not trust the caller". Targets must match `TARGET_RE`, with at most 4 per run.
  - `plan()` refuses any target that is not in `detect.system_driver_packages(cache)` and is not `one_click(target)`.
  - It runs `apt-get update` and `install` with JSON-lines progress (`stage`, `progress`, `log`, `space`, `done`) and a disk-space check.
  - Offline, it can install from the live USB through `mintdrivers-add-live-media`.

  — [helper.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-ota/usr/share/caramos-ota/driver-check/caramos_driver_check/helper.py)
- **How ubuntu-drivers matches packages to hardware.** `system_modaliases()` walks `/sys/devices` and reads every `modalias` file, USB interfaces included. `_apt_cache_modalias_map()` builds a "bus -> modalias -> [package]" map from each package's `Modaliases` header for any bus prefix ("pci" or "usb"), for native-arch or "all" packages. `system_driver_packages()` returns matching packages with `free` and `from_distro` flags. — [UbuntuDrivers/detect.py](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/python3/dist-packages/UbuntuDrivers/detect.py)
- **Linux Mint's Driver Manager uses the same detection** (`from UbuntuDrivers import detect`). — [mintdrivers.py](file:///home/dungleviet/Documents/CaramOS/build/cache/usr/lib/linuxmint/mintdrivers/mintdrivers.py)
- **App Center catalog and recipes:**
  - Install methods are `("flatpak", "recipe", "apt", "preinstalled")`, and detection keys are `("deb", "zalo_flavour")`.
  - Recipes live in `usr/share/caramos-app-center/recipes/<name>` and are run as root with `install` or `remove` by the pkexec helper, which only accepts catalog IDs matching `^[a-z0-9][a-z0-9-]{0,40}$`.
  - `recipes/lib/common.sh` provides `progress`, a resumable `download` (curl with retries) and `install_deb`/`remove_packages`.
  - Tests block `http://` URLs, and the Zalo recipe checks a published SHA-256.
  - App Center releases go out as signed GitHub releases that CaramOS machines pick up in the daily OTA check, without a new CaramOS release.

  — [App Center README](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/README.md), [catalog.py](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/usr/lib/python3/dist-packages/caramos_app_center/catalog.py), [common.sh](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/usr/share/caramos-app-center/recipes/lib/common.sh)
- **A precedent recipe** for a vendor licence: `ms-fonts` preseeds the EULA (`debconf-set-selections`) and installs `ttf-mscorefonts-installer`. — [recipes/ms-fonts](file:///home/dungleviet/Documents/CaramOS/packages/caramos-app-center/usr/share/caramos-app-center/recipes/ms-fonts)

### Inferences
- **(c) Concrete changes in Driver Check** (design sketch, not code):
  1. **`knowledge.py`:** add `CAPT_PRINTERS = {"2676": "LBP2900/2900B", "266a": "LBP3000", "26da": "LBP3010/3018/3050", "26db": "LBP3100/3108/3150", "271a": "LBP6000/6018", "267e": "LBP3300", "2771": "LBP6020", …}`, a `CAPTDRIVER_MODELS` subset and a predicate `capt_printer(device)` (vendor `04a9` plus a product in the table). `hardware.py` needs no change: the name will be "Canon LBP2900" from hwdb.
  2. **`analysis.py`:** add a `"printer"` area to `AREAS` and `area_label()` (not in `ALWAYS_SHOWN`), and a `_printers()` step in `report()`, before `_other()`. `_other()` should skip CAPT devices.
     - *Driver missing:* show a WARNING such as "Máy in Canon LBP2900 chưa có driver" with `Action(INSTALL, _("Install the printer driver"), "printer-driver-captdriver")` for captdriver models.
     - *Models only Canon's driver supports:* show an action that starts the official-driver install (below).
     - *Driver already installed:* check that a CUPS queue exists and uses the right PPD, as the user (`lpstat -v` / `lpoptions`, or python3-cups). Show a TIP when it works, or a "Repair printer" action when a queue was set up with a wrong PPD, the case reported on Mint 22.
     - *usblp blacklisted:* special-case the usblp "blacklist" explanation so it is not shown for CAPT printers when the chosen driver blacklists usblp.
  3. **`drivers.py`:** add `"printer-driver-captdriver"` to `ONE_CLICK`, and a `wanted()` reason ("Canon CAPT printer 04a9:2676") so the UbuntuDrivers lookup runs. To install from the CaramOS USB stick offline, add the package to `ON_INSTALL_MEDIA` and put the deb in the ISO's pool.
  4. **The package in the PPA** carries a header such as `Modaliases: captdriver(usb:v04A9p2676d*dc*dsc*dp*ic07isc01ip*in*, usb:v04A9p26DAd*…, usb:v04A9p271Ad*…)`.
     - `helper.plan()` then accepts the target with no new trust logic: ubuntu-drivers re-derives it from sysfs as root.
     - Mint's Driver Manager would list it too.
     - Alternative: a ubuntu-drivers detect plugin.
  5. **Official driver (b):** a new helper target kind, e.g. `canon-capt:<model>`. The helper re-reads sysfs for a USB device in a root-owned table and then runs a fixed root-owned script. That script could be the App Center recipe; its download, SHA-256 and `install_deb` logic can be reused. This means more new code and a new security review than step 4.
  6. **Hotplug:** Driver Check runs at login or when opened. A printer plugged in later needs a trigger, for example a udev `SYSTEMD_WANTS` user notification or csd-printer's existing "Missing printer driver" notification.
- **(b) In the App Center:** a `recipe` entry in category `tools` (e.g. id `canon-capt-official`, `detect: {"deb": "cndrvcups-capt"}`, a cons line about the closed 32-bit Canon driver).
  - *What the recipe does:* downloads `linux-capt-drv-v271-uken.tar.gz`, checks the SHA-256, installs both debs unchanged and configures ccpd and the queue.
  - *Fit:* the App Center is an app picker with no hardware detection, so a printer-driver card would show to everyone. Use the recipe as the install engine, and let Driver Check be what users see.
  - *Updates:* fixing the recipe needs only an App Center release.

### Gaps
- `notify.py`, `state.py` and the UI files were not read in detail, so how a new area or finding appears (icons, texts, "install all") is not mapped.
- It is not known whether CaramOS's live ISO pool can carry extra debs for `mintdrivers-add-live-media`.

## 5. Testing without the physical printer

### Takeaway
- **Without hardware:**
  - Building, PPD generation, device-ID matching (cupshelpers against a cupsd in a container) and Driver Check logic (fake sysfs tree) can all be tested.
  - The CAPT data CaramOS's packages produce can be decoded and compared with tools from captdriver and studycapt.
- **What hardware-less tests cannot do:**
  - `cupsfilter` with the `file:` backend cannot run captdriver end to end. `rastertocapt` needs a live side channel and back channel: device ID, DRAIN, printer status.
  - A FIFO is unlikely to satisfy `ccpd`, which waits for printer status.
- **Testing the whole plug-in flow** needs either the real printer (QEMU passthrough, or usbip from another machine) or an emulated USB printer gadget. Mint's kernel has the printer gadget but no `dummy_hcd`.

### Cited Findings
- **How `rastertocapt` depends on the CUPS backend:**
  - `capt_identify()` calls `cupsSideChannelDoRequest(CUPS_SC_CMD_GET_DEVICE_ID, …, 60.0)` and exits with "unable to communicate with printer" if that fails.
  - Every write of up to 4096 bytes is followed by `CUPS_SC_CMD_DRAIN_OUTPUT` with a 1.0 s timeout. On a timeout it only logs "output already empty, not drained".
  - Replies are read with `cupsBackChannelRead(…, 15.0)`, exiting with "no reply from printer".

  — [mounaiban/captdriver src/capt-command.c](https://github.com/mounaiban/captdriver)
- **captdriver's own tests** build `captdefilter` and `test-hiscoa` (`check_PROGRAMS`). `captdefilter` writes the decoded pages of a CAPT stream as PBM (`P4`) images. — [mounaiban/captdriver tests/](https://github.com/mounaiban/captdriver)
- **captdriver's Essential Test Suite** (wiki edited 2020-09-20) runs on a physical printer: document/envelope coverage, toner save, minimum print speed, multi-page, multi-job, cancel and out-of-paper resume. — [Testing: Essential Tests](https://github.com/mounaiban/captdriver/wiki/Testing%3A-Essential-Tests)
- **studycapt (2026-08-12) provides:**
  - `capt.lua`, a Wireshark dissector for CAPT over USB that registers 0x04a92676 as LBP2900
  - `captstream.py`, which extracts pages from CAPT job files or streams to PBM
  - a pipeline `gs -sDEVICE=pgmraw … | captfilter --CNTblModel=0 --Resolution=600 | ./captstream.py extract …` that decodes the output of Canon's own `captfilter`
  - `autoinstall-ubuntu` files for VMs "used in studying CAPT-related software and debugging captdriver"

  — [mounaiban/studycapt](https://github.com/mounaiban/studycapt)
- **QEMU** has no emulated USB printer among its USB device models. `usb-host` passes through a host device by `vendorid`/`productid` or `hostbus`/`hostaddr`, needs root or device permissions, and is "experimental … QEMU will slow down when using it". — [QEMU USB emulation docs](https://www.qemu.org/docs/master/system/devices/usb.html) (fetched 2026-11-08)
- **USB modules in Mint 22.3's kernel config:**
  - Present as modules: `CONFIG_USB_G_PRINTER=m`, `CONFIG_USB_F_PRINTER=m`, `CONFIG_USB_CONFIGFS_F_PRINTER=y`, `CONFIG_USBIP_CORE=m`, `CONFIG_USBIP_VHCI_HCD=m`, `CONFIG_USB_MON=m`.
  - Missing: `# CONFIG_USB_DUMMY_HCD is not set`.
  - The files `g_printer`, `usb_f_printer`, `usbip-host`, `vhci-hcd` and `usbmon` are present.

  — [Mint 22.3 boot config](file:///home/dungleviet/Documents/CaramOS/build/cache/boot/config-6.14.0-37-generic)
- **The kernel printer gadget (`g_printer`)** takes `idVendor`, `idProduct`, `bcdDevice`, `iManufacturer`, `iProduct`, `iSerialNum` and `iPNPstring` ("The PNP ID string used for this printer"). Userspace reads print data from `/dev/g_printer` and writes replies to it, and sets the status byte with `GADGET_SET_PRINTER_STATUS`. — [Linux kernel docs: gadget_printer](https://docs.kernel.org/usb/gadget_printer.html) (fetched 2026-11-08)

### Inferences
- **Level 1: CI or container, no hardware, all automatable.**
  1. Build the package, run `make check` (captdefilter, HiSCoA round trip), and run `cupstestppd` on each PPD. Assert that `*1284DeviceID` is present with the exact MDL strings from §1.
  2. Start a throwaway `cupsd` with the PPDs installed. Call `cupshelpers.ppds.PPDs(c.getPPDs()).getPPDNameFromDeviceID("Canon", "LBP2900", "Canon LBP2900", ["CAPT"], "usb://Canon/LBP2900")` and assert status 0 with the captdriver PPD. Repeat for `LBP3010/LBP3018/LBP3050` and `LBP6000/LBP6018`.
  3. Driver Check unit tests with a fake sysfs (`SystemReader(root=tmp)`): add a USB device with `idVendor=04a9`, `idProduct=2676`, interface `07/01/02` and driver `usblp`. Assert the new finding and action, and assert it stays quiet once a matching queue exists. App Center: `make test` with the fake helper.
- **Level 2: fake printer, no hardware.**
  - Write a small Python harness that starts `rastertocapt` with fd 3 as the back channel and fd 4 as a side-channel socketpair, answers `GET_DEVICE_ID` with the LBP2900 string, and returns canned CAPT status replies.
  - Capture the CAPT output, decode it with `captdefilter` or `captstream.py`, and compare the pages with golden PBMs of a test PDF.
  - This catches regressions in the raster and compression path. Its fidelity depends on how realistic the canned replies are, ideally recorded from a real printer (Level 4).
  - The same harness can test the official driver's `captfilter` stage alone, as in the studycapt pipeline.
- **Level 3: VM integration, with an emulated or remote device.**
  - **Real printer elsewhere:** usbip from a machine that has the printer (`usbip-host` on that side, `vhci-hcd` in the test VM) or QEMU `usb-host` passthrough. Expect timing to suffer over the network.
  - **Emulated printer:** a USB gadget with `g_printer idVendor=0x04a9 idProduct=0x2676 iPNPstring="MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900"`. It needs a device controller: a board with USB OTG (e.g. Raspberry Pi Zero) plugged into the test machine, or a test kernel built with `dummy_hcd`, which Ubuntu's kernel lacks.
  - **What an emulated gadget can prove:** the full plug-in chain. That means `70-printers.rules`, `configure-printer@`, `udev-add-printer` getting an exact match, csd-printer's notification or autoconfigure, queue naming, Driver Check detection, and that no duplicate or wrong queue appears.
  - **What it needs:** a userspace CAPT responder on `/dev/g_printer`.
  - **Baseline first:** measure what happens today with no driver installed, to confirm or refute the "unrelated PostScript driver" field report (§2).
- **Level 4: reference capture.** Anyone who owns an LBP2900 can record real sessions with `usbmon` and Wireshark plus `capt.lua`, under Canon's Windows or Linux driver and under captdriver. These give realistic replies for the Level 2 harness and golden streams.
- **Only the real printer can prove:**
  - actual print output (alignment, toner density, paper sizes)
  - printing speed and delays between pages, including whether the #1461 fix matters
  - recovery from paper-out, jam and open door, and cancel mid-page (desync)
  - many consecutive jobs (the claimed 5th-job hang) and wake from power save
  - how usblp re-attach after each job interacts with the printer
  - firmware differences (`VER:` field), and LBP2900B versus LBP2900

### Gaps
- No existing open-source CAPT printer emulator, and no USB/IP userspace device that emulates a printer, was found or verified. One would have to be written.
- Whether Canon's `ccpd` can be driven against a FIFO, a pty or a fake `/dev/usb/lp0` was not tested. Parallel research on the official driver may cover this.

## 6. Demand evidence: how common the LBP2900 is in Vietnam, and CaramOS/VNLF requests

### Takeaway
- **Direct demand from the CaramOS community:**
  - CaramOS issue #39 ("tích hợp driver máy in canon 2900 3300"), open since 2026-05-20.
  - A VNLF post on 2026-10-28 from a business planning ~15 CaramOS machines that uses a "canon lp2900".
  - A VNLF post on 2026-10-30 about CAPT printing breaking on updated Windows (unverified).
- **Market.** The LBP2900 is discontinued at big retailers, but it is still sold. Imported or remaining new units cost about 3.8–4.2 million VND. A busy used market on Chợ Tốt prices it at about 1.5–2.3 million VND. Buyers are small offices, shops and households.

### Cited Findings
- **CaramOS issue #39**, "tích hợp driver máy in canon 2900 3300", is open. It was created 2026-05-20 by mrd9999 with no body and sits in Backlog on the CaramOS Board. Its one comment (dryfish09, 2026-10-13) reads "Tích hợp như nào ms là vấn đề." A search of the repo's issues for printer/canon/2900/"máy in" returned only this issue. — [VN-Linux-Family/CaramOS#39](https://github.com/VN-Linux-Family/CaramOS/issues/39)
- **VNLF post, 2026-10-28** (buituan261, "tuấn bùi"): "hiện tại bên em kinh doanh thương mại. hiện tại có 2 cơ sở tổng khoảng 15 máy tính muốn cài caramos… em đang dùng máy in ricohn mp 6055, canon lp2900, canon mf24…". The excerpt is from the public search API. — [VNLF post](https://vietnamlinuxfamily.net/a/chao-anh-chi-a-hien-tai-ben-em-kinh-doanh-thuong-mai-hien); [VNLF search API](https://vietnamlinuxfamily.net/api/v1/search?q=2900)
- **VNLF post, 2026-10-30** (hmtheboy154, "Huy Minh"): "nếu update Windows 10/11 lên mới nhất thì sẽ không thể in được trên máy in Canon LBP2900/3300.... thực ra là tất cả máy in Canon dùng driver CAPT nói chung luôn do Microsoft vá mấy cái lỗ hổng liên qu[an]…". A web search found no corroboration of this Windows claim. — [VNLF post](https://vietnamlinuxfamily.net/a/hom-qua-moi-biet-la-neu-update-windows-10-11-len-moi-nhat)
- **VNLF article, 2026-10-12** by mrd9999, "CÁCH NHANH NHẤT ĐỂ BIẾT MÁY BẠN ĐANG THIẾU DRIVER NÀO", also matched the "máy in" search. Its content was not inspected. Searches for "printer" returned nothing, and "LBP" returned only the 2026-10-30 post. — [VNLF search API](https://vietnamlinuxfamily.net/api/v1/search?q=LBP)
- **The owner's local CaramOS notes have no printer topic.** The memory notes on the 2026-10-18 and 2026-11-05 ticket batches (H-1039…H-1111) do not mention printers, Canon or CUPS (local grep). — [memory dir](file:///home/dungleviet/.claude/projects/-home-dungleviet-Documents-CaramOS/memory/)
- **Thế Giới Di Động** marks the "Máy in laser trắng đen đơn năng Canon LBP2900" as "NGƯNG KINH DOANH" (discontinued). It shows 1.4k sold and 116 ratings (4.9/5), launch year 2007, and Windows XP–10 only (fetched 2026-11-08). — [thegioididong.com](https://www.thegioididong.com/may-in/may-in-laser-canon-lbp2900)
- **HACOM sells a used unit:** "Máy In Canon 2900 - Cũ xước (Không vỏ hộp)" at 1,599,000 VND (listed price 3,999,000), with a 3-month warranty. The page's price data is valid from 2025-08-10, and the product is marked discontinued / out of stock. — [hacom.vn](https://hacom.vn/may-in-canon-2900-cu-xuoc-khong-vo-hop)
- **Hoàng Hà Mobile article, 2026-01-20** ("Máy in Canon LBP2900: Đánh giá chi tiết, có còn đáng mua không?"). It recommends the printer for small offices ("văn phòng nhỏ"), shops ("cửa hàng") and households. It says Linux works "through CUPS", which in practice needs a driver, and that macOS is not supported. — [hoanghamobile.com](https://hoanghamobile.com/tin-tuc/may-in-canon-lbp2900/)
- **Prices from search summaries only (pages not opened):**
  - meta.vn lists an imported unit at 4,190,000đ, in stock, and another at 3,920,000đ marked stopped. — [meta.vn](https://meta.vn/may-in-laser-canon-lbp-2900-hang-nhap-khau-p114216)
  - A Hoàng Hà Mobile price guide (2025) gives 3.9–4.2 million VND for a new genuine unit (exact URL not confirmed).
  - Chợ Tốt has many used LBP2900 listings at about 1.5–2.3 million VND, for example Quận 4, TP.HCM at 1.5M with "685 sold", Tân An (Long An) at 1.85M and Bình Thủy (Cần Thơ) at 1.85M with a 3-month warranty. — [Chợ Tốt Q4](https://www.chotot.com/mua-ban-do-dung-van-phong-quan-4-tp-ho-chi-minh/133910578.htm), [Chợ Tốt Long An](https://www.chotot.com/mua-ban-thanh-pho-tan-an-long-an/133851678.htm), [Chợ Tốt Cần Thơ](https://www.chotot.com/mua-ban-quan-binh-thuy-can-tho/132784921.htm)
- **Tinhte (search summary, date unknown):** "Các máy in thuộc dòng Canon LBP rất phổ biến ở Việt Nam, nhất là LBP2900". The thread says Ubuntu 18.04 worked best and 22.04/22.10 worse. — [tinhte.vn thread 2787611](https://tinhte.vn/thread/cai-driver-may-in-dong-canon-lbp-cho-ubuntu.2787611/)
- **Many grassroots repos, mostly Vietnamese, for running the LBP2900 on Linux are active** (last commits in the local clones):
  - [brucenguyen1102/Canon-LBP2900-CAPT-Toolkit](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit), 2026-07-24
  - [digital-enterprise-projects/LBP2900](https://github.com/digital-enterprise-projects/LBP2900), 2026-08-23
  - [vnojiovn/CanonLBP2900](https://github.com/vnojiovn/CanonLBP2900), 2026-06-17
  - [Huylighting/Linux-Print-server](https://github.com/Huylighting/Linux-Print-server), 2026-10-18
  - [thetrung/Driver_Canon_LBP2900_Linux](https://github.com/thetrung/Driver_Canon_LBP2900_Linux), 2025-11-04
  - [TranPhuong319/ToolDriverPrinter](https://github.com/TranPhuong319/ToolDriverPrinter), 2025-02-17
  - Outside Vietnam: [sanhos95/canon-capt-linux-driver](https://github.com/sanhos95/canon-capt-linux-driver), 2026-11-04 (Ukrainian/English); [suluoniu/captdriver-lbp2900](https://github.com/suluoniu/captdriver-lbp2900), 2026-11-01 (Chinese/English)

### Inferences
- **Why demand is real for CaramOS.** CaramOS targets Vietnamese users moving off Windows. The LBP2900 is a ~2007 model still sold new or imported, and traded heavily used at ~1.5–2.3M VND. Offices and shops that would adopt CaramOS will often already own one. The business on VNLF (15 machines, two sites) is a concrete case.
- **The LBP3300 matters too.** The owner's issue names the 3300 (04a9:267e), which only Canon's official driver supports. A captdriver-only solution would not close issue #39.
- **Windows trouble could add pressure.** If the community claim that recent Windows updates break CAPT printing is true, it would increase demand, but it is unverified.

### Gaps
- There are no sales volumes or installed-base numbers for Vietnam. Shop pages give only counts such as "1.4k sold" at one retailer, and Chợ Tốt listing dates were not visible.
- The VNLF site search needs JavaScript. I used the public `/api/v1/search` endpoint, which returns excerpts only, so the full posts and replies were not read. Private CaramOS help tickets (H-xxxx) were not searched; that would need the owner's cookie, which was not used.
- The Windows-update claim (2026-10-30) has no primary source, such as a Microsoft KB or Canon notice.
