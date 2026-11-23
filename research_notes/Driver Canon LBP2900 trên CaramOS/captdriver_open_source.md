# captdriver (open-source CAPT driver) and its forks: running the Canon LBP2900 / LBP2900B on Ubuntu 24.04 "noble" (CaramOS 1.3.6) without Canon's ccpd

Legend: **[V]** = I verified it myself on 2026-11-08 (reading the code, git history, or building and running in a throwaway `ubuntu:24.04` Docker container). **[C]** = a claim made by the cited source. Unmarked = factual metadata read from the cited page/API on 2026-11-08. "lp2900" = Canon LBP2900 / LBP2900B (USB ID 04a9:2676).

## 1. Fork network: which captdriver code bases exist and what each adds

### Takeaway
The network is about 80 GitHub forks. Only about 20 have commits of their own, and only a handful matter for the LBP2900. Activity moved from **agalakhov** (the original, passively maintained since 2021) to **mounaiban** (master frozen since 2022-10-14), and in 2026 to **ValdikSS/captdriver**. ValdikSS's fork is where almost all LBP2900-relevant fixes now live. mounaiban has copied it into the branches `0.2-pr`/`0.2.1-pr`, but has not merged it into master. Several 2026 forks build on ValdikSS or mounaiban: palashkaria (persistent USB session), apocarteres (bug fixes), akbezrukov (speed), cryptoluks (an AI refactor that ROSA packages) and ershad (a status-decoding fix). There are also two LBP2900-focused derivatives outside the GitHub network: a Vietnamese installer toolkit by Bruce Nguyen, and gauravyad69/Canon-LBP2900B.

### Cited Findings
**Network size and how I mapped it**
- agalakhov/captdriver: created 2013-09-15, 171 stars, `network_count` 80, `open_issues_count` 22, GPL-3.0. Its last `pushed_at` is 2022-11-20 — [GitHub API](https://api.github.com/repos/agalakhov/captdriver).
- mounaiban/captdriver: created 2018-04-22, 144 stars, 30 forks, `open_issues_count` 21, last push 2026-08-13 — [GitHub API](https://api.github.com/repos/mounaiban/captdriver).
- [V] Method:
  - Listed all forks with the API (48 direct forks of agalakhov, 31 of mounaiban (the repo page says 30), 1 each of ValdikSS and jayantsinha).
  - Ran `git ls-remote` on every fork.
  - Fetched each fork whose branch heads were not in agalakhov or mounaiban, and listed its own commits.
- [V] 20 forks have commits of their own. One listed fork, nasbeginner/captdriver, could not be reached with git on 2026-11-08 — [forks API](https://api.github.com/repos/agalakhov/captdriver/forks?per_page=100), [mounaiban forks API](https://api.github.com/repos/mounaiban/captdriver/forks?per_page=100).

**agalakhov/captdriver (original)**
- Last master commit: 175f8ff, 2022-10-08 (merge of mounaiban's PR #57, "Code cleanups").
- README note added 2021-11-30: the project is "only passively maintained since I don't own any LBP printers anymore… Please look at https://github.com/mounaiban/captdriver for more actual version" — [README](https://github.com/agalakhov/captdriver/blob/master/README), [commit ae80832](https://github.com/agalakhov/captdriver/commit/ae80832a1303b7722b924377e35f4007d0887372).
- Issues: 21 open / 5 closed. PRs: 1 open / 34 closed (22 merged) — [issues API](https://api.github.com/repos/agalakhov/captdriver/issues?state=all&per_page=100).
- [V] Registered models, in `src/prn_lbp2900.c` (identical in every tree I checked):
  - `LBP2900` WORKS
  - `LBP3000` EXPERIMENTAL
  - `LBP3010/LBP3018/LBP3050` WORKS
  - `LBP3100/LBP3108/LBP3150` EXPERIMENTAL
  - `LBP6000/LBP6018` EXPERIMENTAL

  — [prn_lbp2900.c](https://github.com/agalakhov/captdriver/blob/master/src/prn_lbp2900.c).
- [V] PPDs: precompiled `Canon-LBP2900.ppd` and `Canon-LBP3000.ppd` are committed. `make ppd` generates `CanonLBP-2900-3000.ppd` and `CanonLBP-3010-3018-3050.ppd` from `src/canon-lbp.drv`.

**mounaiban/captdriver**
- master: last commit 6271924, 2022-10-14, version 0.1.4.1. Tags run from `0.1.1-m1` to `0.1.4-m5` (2020-11-16).
- `0.1.4.2-GxB` (2023-01-18): BSD support, plus saper's "Respect cups-config --ldflags".
- `0.2-pr` (committed 2026-08-12) and `0.2.1-pr` (2026-08-13): ValdikSS's 2026 work.
- [V] `0.2.1-pr` is rebased on agalakhov master so it can be sent as a PR to the original.
- [V] Its `src/` differs from ValdikSS/test mostly by removed comments and blank lines.

  — [branch 0.2.1-pr](https://github.com/mounaiban/captdriver/tree/0.2.1-pr), [master](https://github.com/mounaiban/captdriver).
- Issues: 20 open / 13 closed. PRs: 1 open / 12 closed (7 merged). Gaps in the numbering are GitHub Discussions such as #12 and #52 — [issues API](https://api.github.com/repos/mounaiban/captdriver/issues?state=all&per_page=100).
- Documentation lives in the wiki, last edited 2026-05-21 — [wiki](https://github.com/mounaiban/captdriver/wiki).
- [C] mounaiban, 2026-08-13: "I finally got the chance to test @ValdikSS' enhancements and so far it's looking promising… all the fixes are also available under the 0.2.1-pr branch… If all goes well, I will merge the changes into my master branch, and even file a pull request to Alexey's original repo." — [mou#8 comment](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5280818961).

**ValdikSS/captdriver (the 2026 LBP2900/LBP3000/LBP6000 rework)**
- Created 2026-05-19. 13 stars, 1 fork. Issues are disabled. Branches `test` = `val` = 892f320.
- [V] 48 commits on top of mounaiban master, dated 2026-05-17 to 2026-06-06. The last is 892f320, "Github Actions: add build CUPS USB backend with anti-race patch" — [commit](https://github.com/ValdikSS/captdriver/commit/892f320c019974a5b737e000fcc2c8582264a131).
- [C] README lists what it fixes:
  - "Incorrect paper dimensions"
  - "Shifted printing after the first page"
  - "Slow printing and delay before first print"
  - "Inability to print pages larger than printer's RAM amount (streaming mode)"
  - "Proper error and interal state handling"
- [C] README flaw: "Does not continue printing after paper jams, no cartridge/opened door — filter terminates, you'll need to reprint manually."
- [C] README requirement: "To make it work reliably, **you have to use CUPS v2.4.17+**, as it includes the fix for USB race condition."
- [C] README on provenance: the work is based on reverse engineering of Canon's `captmon2`/`captfilter` Linux binaries and on Windows XP USB dumps, "however all the code has been written by LLM assistant from my documentation, experiments and observations."

  — [README](https://github.com/ValdikSS/captdriver/blob/test/README.md).
- Key LBP2900 commits [V]:
  - LBP2900 now uses the LBP3000 job prologue: f2d3bd2, "Let's try to use LBP3000 job prologue for LBP2900, it should work", 2026-05-20.
  - Paper dimensions and margins: e867cd0.
  - Page-end flag in the last Hi-SCoA band: aed4511, 463366c.
  - Out-of-paper on the first page: ad0d4cd.
  - Large-page streaming: e32c2b6.
  - ReserveUnit failures, jams, open door: 27eba48.

  — [f2d3bd2](https://github.com/ValdikSS/captdriver/commit/f2d3bd2c5f5d771cb7ffd780114522d39d932eef), [e867cd0](https://github.com/ValdikSS/captdriver/commit/e867cd07ae433346e8ce28774af34afc49fcbf7a), [aed4511](https://github.com/ValdikSS/captdriver/commit/aed451197a1a64b863f486180683ea4afa939688), [ad0d4cd](https://github.com/ValdikSS/captdriver/commit/ad0d4cd536ac23f7d8dc1fbcba2a19d173761b7f), [27eba48](https://github.com/ValdikSS/captdriver/commit/27eba4829934ccc5dc296b927c84931ba5f73f56).
- [V] The PPD source gains an LBP6000 model, a "Darkness" option (default 7) for LBP2900/3000, and `*Manufacturer "Canon"` instead of "Canon Inc". It drops the "Manual Duplex" option from the LBP2900/3000 group — [canon-lbp.drv](https://github.com/ValdikSS/captdriver/blob/test/src/canon-lbp.drv).
- [C] ValdikSS, 2026-06-16, when asked to point nixpkgs at his fork: "Please don't, my version is not ready for the release yet. When it's done, it will be on openprinting repo." — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4714536714).
- [V] github.com/OpenPrinting/captdriver did not exist on 2026-11-08: `git ls-remote` asked for credentials.
- [C] ValdikSS, 2026-08-13: "The LLM wrote a pretty nasty code which I don't have time to rewrite right now… the sending page operation should not be 'blocking'… but instead everything should be status polling-based… It works though, not perfect, but pretty ok." — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5281082555).
- [C] ValdikSS owns an LBP3000 and an LBP6000 (2026-06-03) and asked for donations to buy an LBP2900 (2026-05-16) — [aga#31](https://github.com/agalakhov/captdriver/issues/31#issuecomment-4613190710), [aga#31](https://github.com/agalakhov/captdriver/issues/31#issuecomment-4467635224).

**palashkaria/captdriver** (fork of ValdikSS; created 2026-11-04; 0 stars)
- Branch `val` = ValdikSS val plus one commit: ee4186a, 2026-11-05, "Add persistent LBP2900 USB transport and fix drain acknowledgement ordering" (25 files, +1652 lines).
- It adds:
  - `captd`, a daemon that keeps the USB session open across jobs.
  - A `capt:` CUPS backend.
  - A systemd unit.
  - `--enable-persistent-usb`.
  - A hardware-free regression test.

  — [commit ee4186a](https://github.com/palashkaria/captdriver/commit/ee4186affae34a7e2da89291da2a7906a7311f2f), [README](https://github.com/palashkaria/captdriver/blob/val/README.md).
- [C] Testing: "The persistent path has been exercised with a USB Canon LBP2900 on x86-64 Debian 13… Other printer models have not been validated."

**apocarteres/captdriver** (9 commits, 2026-09-10/11, on mounaiban master; some co-authored by "Claude Opus 5")
- Fixes reply buffer handling (uninitialized size, header accounting, bounds).
- Uses `cupsPageSizeName` for the page size code.
- Corrects the LBP2900/3000 Envelope media code (6, not 5).
- Exposes Darkness for LBP2900/3000.
- Fixes the sigaction branch, which had never compiled.
- Takes `line_size` from `cupsBytesPerLine` and un-swaps the margins.
- Adds a Docker build script and a `pstopdf-fast` server-side filter: [C] a macOS PostScript job dropped from ~630 s to ~6 s.

— [4b5d41c](https://github.com/apocarteres/captdriver/commit/4b5d41c96b1452ea0663e2694676d3ecce8d591a), [6901363](https://github.com/apocarteres/captdriver/commit/6901363624c4a66378d941d16d5a82444a3913cf), [c05a280](https://github.com/apocarteres/captdriver/commit/c05a2808de4e3928027e26af7a435aa7993ec6d1).

**akbezrukov/captdriver** (9 commits, 2026-06-02, on mounaiban master)
- Faster Hi-SCoA compression.
- Polling every 150 ms instead of `sleep(1)`.
- An LBP2900 fix: sleep before re-polling NOPAPER+PRINTING. [C] Before the fix it produced "thousands of 'no paper' debug lines per second".
- Band compression in a pthread pool. [C] About 3.86× faster on a Cortex-A7.
- A `gstoraster-fast` filter, an Ansible playbook for an "lbp2900 print-server", and a Russian README.

— [3e72914](https://github.com/akbezrukov/captdriver/commit/3e72914778a52e674fcf5fe6966f0907d42b46f3), [aec0826](https://github.com/akbezrukov/captdriver/commit/aec082694f8989ec22ee658000f24a13dd36c28f).

**cryptoluks/captdriver** (15 commits, 2026-02-24..28, mostly authored by "Claude")
- Adaptive polling, and pipelined multi-page printing (does not wait for `page_out`).
- LINESIZE taken from `cupsRowFeed`; HISCOA_EOB_LAST on the last band.
- Signal-handler fix, flake.nix, and LBP6000/6018 status set to "Works".
- ROSA packages this fork.

— [a411641](https://github.com/cryptoluks/captdriver/commit/a4116411e24970ec3284daf0611cedcea5532fd2), [51a9b67](https://github.com/cryptoluks/captdriver/commit/51a9b67016df6f1557d024e9bdd6f0acfa4d3cca).

**ershad/captdriver** (1 commit, 2026-10-30, based on agalakhov master)
- "Decode status replies by payload size, not total reply size", open as [mounaiban PR #55](https://github.com/mounaiban/captdriver/pull/55) (details in section 2).

**Smaller forks with their own commits** (none adds LBP2900 features unless noted)
- raphael-kliyanage: 0.2-pr plus CodeQL, "ci: add build from ValdikSS" and a buffer-overflow fix, 2026-09-01 — [e6c9255](https://github.com/raphael-kliyanage/captdriver/commit/e6c9255834039447516e51b401ff1486a2a117fd).
- isiddharthasharma/captdriver-raspberrypi: a one-step Raspberry Pi install script, 2026-11-07 — [47f0d0f](https://github.com/isiddharthasharma/captdriver-raspberrypi/commit/47f0d0faacc75d7c9a37cb11573434dde6dfc351).
- buildit: 6 automated "WegaCodeReviewer" CWE fixes, 2026-06-19 — [fe80cdd](https://github.com/buildit/captdriver/commit/fe80cdda479ee9a164736110bac6a6e5990d883c).
- HardNorth: a macOS fix, 2025-09-27; PR mou#47 closed unmerged — [6ed1c75](https://github.com/HardNorth/captdriver/commit/6ed1c7581a4ae5c9b0c3e99924cfa532ec70c704).
- loskutov: a faster MSB search, 2025-10-24. PR mou#48 was closed on 2026-05-19 because `__builtin_clz` is not portable — [mou#48](https://github.com/mounaiban/captdriver/pull/48#issuecomment-4486945093).
- ousui: a Debian binary-package layout (DEBIAN/control, prebuilt `rastertocapt`, PPDs in `/usr/share/cups/model`), 2023-02-24 — [ecbc6f7](https://github.com/ousui/captdriver/commit/ecbc6f717e8cbefecfe354aba6530f3b38bcfbbe).
- saper: cups-config ldflags and no `-std=c99`, 2022-12-25 (merged into GxB).
- ra1nst0rm3d: SCoA/LBP1120 experiments 2020–2022; origin of the BCD() fix.
- alex-eri: registers "LBP6020" with LBP3000 ops, 2020-09-14 — [c2313ab](https://github.com/alex-eri/captdriver/commit/c2313ab5b662fdf535a43bc5e765e8efad800dbf).
- jekader (README, 2020), vmuthukrish (README, 2022), eu4you (LBP3000 PPD, 2024), HighwayStar (2013 job-end tweak), Limych (whitesource bot, 2020).

**LBP2900 derivatives outside the GitHub fork network**
- brucenguyen1102/Canon-LBP2900-CAPT-Toolkit:
  - Vietnamese-language; created 2026-07-08, last push 2026-07-24; 19 stars, 11 forks; **no license file**.
  - Targets Ubuntu noble and Linux Mint.
  - Bundles ValdikSS val, a CUPS #1461 patch and a `captd` persistent daemon.

  — [repo](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit), [GitHub API](https://api.github.com/repos/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit).
- gauravyad69/Canon-LBP2900B:
  - A GitHub fork of a 2019 LBP2900B copy of agalakhov's code; 13 stars.
  - Releases v0.3.0–v0.3.3; v0.3.3 dated 2026-11-05.
  - Shipped on the AUR as `canon-lbp2900-capt` 0.3.3, GPL-3.0-or-later.

  — [repo](https://github.com/gauravyad69/Canon-LBP2900B), [PKGBUILD](https://github.com/gauravyad69/Canon-LBP2900B/blob/master/PKGBUILD).
- darkvision77/captppd (ValdikSS helped with it) supports only CAPT v1 / SCoA printers (LBP800/810/1120/1210/3200), **not the LBP2900**. It runs as a libusb CUPS backend (`captusb://`) — [captppd README](https://github.com/darkvision77/captppd).

### Inferences
- Which tree is "the" captdriver now depends on whom you ask:
  - mounaiban master is the newest released-in-distros base.
  - ValdikSS val (≈ mounaiban `0.2.1-pr`) is the functional state of the art.
  - palashkaria and the Bruce Nguyen toolkit are the only trees that target the reported "job-5 wedge" on the LBP2900.
- The 2026 forks are heavily LLM-assisted (ValdikSS, cryptoluks, apocarteres). Any of them needs real-printer regression testing before shipping.

### Gaps
- I did not compare every one of the 81 listed forks' tags. Forks that contain only rewritten history (force-pushes) of known commits would not show up in my "own commits" list.
- Discussions are not returned by the REST API. I only saw #12 and #52 by title.

## 2. LBP2900 / LBP2900B: support status, known problems and dates

### Takeaway
Every tree marks the LBP2900 as `WORKS`, and many users print with it. But the old code (agalakhov/mounaiban master) had long-standing faults:
- jobs stuck at "Rendering completed";
- the first page fine, then the job stops, or later pages are shifted;
- slow, page-by-page printing;
- needing to re-plug or power-cycle.

In 2026 the main cause was traced to a race in the CUPS libusb backend, fixed upstream in CUPS 2.4.17 (2026-04-17). ValdikSS's fork fixed geometry, streaming and first-page out-of-paper. Remaining LBP2900-specific risks:
- a reported "5th job since power-on" engine wedge (fixed only with a persistent USB session daemon);
- a status-decoding bug (PR #55);
- abort, not recovery, on jam/door/cartridge errors.

### Cited Findings
**Official status**
- [V] `register_printer("LBP2900", lbp2900_ops.ops, WORKS)` appears in agalakhov, mounaiban, 0.2.1-pr, ValdikSS, palashkaria, apocarteres, akbezrukov and cryptoluks — [prn_lbp2900.c (mounaiban)](https://github.com/mounaiban/captdriver/blob/master/src/prn_lbp2900.c).
- The wiki defines `WORKING` as "accurate output, with a level of performance and reliability suitable for end-user daily use" — [Printer Support Levels](https://github.com/mounaiban/captdriver/wiki/TESTING:-Printer-Support-Levels).
- The mounaiban wiki lists the LBP2900 as working on:
  - x86-64 Manjaro and Void Linux;
  - ARMv7 Ubuntu 19.10, 20.04.2 and 22.04.

  It also says the driver has "two significant issues: the compatibility issues with the CUPS-libusb interface and long delays between pages" — [wiki Home](https://github.com/mounaiban/captdriver/wiki).
- Discussion #12 (2022-01-23): "Works perfectly on Void Linux with LBP 2900" — [discussion #12](https://github.com/mounaiban/captdriver/discussions/12).
- [C] AUR maintainer mistersmee (2025-05-06): "it works, I use it daily with a LBP2900B" — [AUR captdriver-git](https://aur.archlinux.org/packages/captdriver-git).
- [C] LBP2900 on loongarch64 "works!!!", 2026-10-24 — [mou#54](https://github.com/mounaiban/captdriver/issues/54).
- [C] With ValdikSS's build and a newer CUPS, LBP2900 "It's working great for me — the bug I used to see was probably in CUPS, and it seems to have been fixed in a newer version." (2026-06-14) — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4701986539).

**Identity of the printer**
- The LBP2900 reports the device ID `MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900` (CUPS log, 2021-11-30) — [aga#37](https://github.com/agalakhov/captdriver/issues/37).
- USB ID 0x04a9 0x2676 (2022-09-26) — [aga#7](https://github.com/agalakhov/captdriver/issues/7#issuecomment-1257796827).

**"Rendering completed — stuck" (agalakhov #7, since 2014-12-24)**
- [C] The original report: "Sometimes, the printing get stuck with the message 'Rendering completed'… fixed by turning the printer off and on" (Ubuntu 14.04, LBP 2900B) — [aga#7](https://github.com/agalakhov/captdriver/issues/7).
- [C] nerk (2020-10-19): "after the first print job, lpinfo -v no longer show the Canon printer URI. I have to pull and reconnect the USB cable" — [aga#7](https://github.com/agalakhov/captdriver/issues/7#issuecomment-712408044).
- [C] ValdikSS (2025-12-29): "This bug has been debugged and filled to CUPS developers: https://github.com/OpenPrinting/cups/issues/1461" — [aga#7](https://github.com/agalakhov/captdriver/issues/7#issuecomment-3695202159).
- [V] "Rendering completed" is the last INFO message of the cups-filters Ghostscript filter (`INFO: cfFilterGhostscript: Rendering completed`), seen in my container run. A queue showing it is therefore hanging *after* rasterization, in `rastertocapt` or the backend.
- [C] Platform-dependent failures:
  - mou#8 (2024-01-15): LBP2900 failed on 32-bit Raspberry Pi OS but printed multiple jobs on 64-bit Pi OS, Debian, Manjaro and Ubuntu — [comment](https://github.com/mounaiban/captdriver/issues/8#issuecomment-1892427538).
  - VinhNgT (2024-10-21): "i need to power the raspberrypi on first and then power the printer" — [comment](https://github.com/mounaiban/captdriver/issues/8#issuecomment-2427164594).

**First page fine, then stops / shifted pages / blank pages**
- [C] hrj (2014-08-13): in a two-page job "the first page printed but the second page didn't print at all"; a reprint was "shifted to the left by about an inch". Agalakhov: "I'm aware of this problem… Looks like I misunderstood some of the state flags" — [aga#4](https://github.com/agalakhov/captdriver/issues/4#issuecomment-52061233).
- [C] andrey-verenya (2022-09-25, Ubuntu Server 22.04): multi-page jobs "sometimes an empty page is printed… the button lights up red (blinks)"; jobs hang at "Processing page 3…" or "Rendering completed".
  - mounaiban blamed page settings: US Letter in the app with A4 sheets.
  - The reporter: with Letter "started printing without this error…" (2022-10-01).

  — [aga#56](https://github.com/agalakhov/captdriver/issues/56#issuecomment-1264366085).
- [C] ValdikSS (2026-05-20) on why the old code shifted pages:
  - "The margins in PPD are (slightly) incorrect".
  - The margin calculation code is wrong.
  - "The driver does not send 'page end' flag in HI-SCoA raster data, which results in next page shift, each additional printed page adds a shift".

  — [mou#29](https://github.com/mounaiban/captdriver/issues/29#issuecomment-4500983657).
- [C] Margins are also swapped height/width in the driver header (2026-06-03) — [mou#29](https://github.com/mounaiban/captdriver/issues/29#issuecomment-4615007355).

**Slow printing / delays between pages**
- [C] mounaiban opened #7 "Complex pages are slow to start" on 2020-12-12. ValdikSS (2026-05-14) found three causes:
  - Ghostscript is slow with transparency (pdftopdf patches in libcupsfilters PR #147).
  - Ghostscript's `cups` device has no multithreading.
  - "captdriver sends data page-by-page into printer, and waits until the page is fully printed before sending another one".

  — [mou#7](https://github.com/mounaiban/captdriver/issues/7#issuecomment-4454937618).
- [C] ValdikSS (2026-05-20), "Now it supports page streaming… the second page is uploaded in advance… mounaiban and agalakhov versions simply fail to print anything in this case" — [mou#7](https://github.com/mounaiban/captdriver/issues/7#issuecomment-4501026561).
- [C] and-fed (2025-01-19): LBP2900 on 64-bit Gentoo "worked fine with exception for slow page printing" — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-2600810173).

**Paper-out / jam / door**
- [V] Old code: agalakhov's 2013 commits "paper out handling (not yet working)" and "Reset after paper out" — [history](https://github.com/agalakhov/captdriver/commits/master).
- [V] ValdikSS: "Fix out-of-paper on the first page" and "Continue after out-of-paper" (ad0d4cd, 27eba48).
- [V] In ValdikSS's code the out-of-paper path logs only `DEBUG:` lines such as "out-of-paper: waiting for user to insert paper".
- [C] Jams, open door or a missing cartridge terminate the filter ("you'll need to reprint manually") — [README](https://github.com/ValdikSS/captdriver/blob/test/README.md).

**"Job 5" engine wedge on the LBP2900 (2026)**
- [C] Bruce Nguyen's toolkit (root-caused 2026-07-14 with usbmon captures of Canon's official Linux driver): the ValdikSS fork "reliably wedges the Canon LBP2900's print engine — `CAPT: ReserveUnit failed (0x8c) after error recovery — aborting` — on exactly the 5th print job since power-on, requiring a physical power cycle".
- [C] Their explanation: the CUPS `usb://` backend opens and closes USB per job, while Canon drivers keep one session.
- [C] Fix: `captd` plus a `capt:` backend plus protocol changes:
  - `SetJobInfo2` heartbeat about every 500 ms;
  - `GetExtendedStatus` twice before every `ReserveUnit`;
  - corrected payload bytes;
  - a reply-stream resync instead of `exit(1)`.
- [C] Result: "58 jobs in one power-on session with zero wedges". A follow-up desync bug "killed ~1 job in 8 before the fix".

— [captd README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/captd-persistent-daemon/README.md).
- palashkaria carried these changes onto ValdikSS val on 2026-11-05 — [PROVENANCE](https://github.com/palashkaria/captdriver/blob/val/docs/PROVENANCE.md).

**Status-decoding bug affecting the LBP2900**
- [C] ershad (2026-10-30): `download_status()` passes a reply size that includes the 4-byte header to `decode_status()`, so counters such as `page_decoding` are read from leftover or uninitialized bytes.
  - On macOS with an LBP2900, master "fires page 0 and the printer never feeds paper"; the fix makes the job complete.
  - On 0.2.1-pr, `lbp2900_page_epilogue()` "still waits on page_decoding and page_printing after basic-status reads".
  - "The endless A0 E0 loops reported on 32-bit ARM in #3 and #8 may have the same cause, but I haven't verified that."

  — [PR #55](https://github.com/mounaiban/captdriver/pull/55).
- [V] In ValdikSS/test, `capt_sendrecv()` copies the payload from `capt_iobuf + 4` but returns `*reply_size = capt_iosize`, the total including the header. `download_status()` passes that size to `decode_status()` unchanged. The bug is present in the 2026 code — [capt-command.c](https://github.com/ValdikSS/captdriver/blob/test/src/capt-command.c), [capt-status.c](https://github.com/ValdikSS/captdriver/blob/test/src/capt-status.c).

**Other LBP2900 reports**
- [C] Blurry output came from Firefox/pdf.js rasterizing, not the driver (2020-11-25) — [aga#35](https://github.com/agalakhov/captdriver/issues/35#issuecomment-734148657).
- [C] Low density (mou#33, 2024-01-14). ValdikSS (2026-05-14) blames the dithering and points to new libcupsfilters algorithms (PR #92) — [mou#33](https://github.com/mounaiban/captdriver/issues/33#issuecomment-4454687801).
- [C] Raspberry Pi Zero W 32-bit LBP2900B: "CAPT:Unable to communicate with printer" (2025-01-19) — [mou#43](https://github.com/mounaiban/captdriver/issues/43).

### Inferences
- The LBP2900B seems to report `MDL:LBP2900`. The driver needs an exact `MDL` string match (`find_ops()` uses `strcmp`) and only registers "LBP2900", yet several LBP2900B owners report printing (aga#7, aga#17, aga#35, AUR maintainer). If the 2900B reported a different `MDL`, `rastertocapt` would stop with "unknown printer".
- For CaramOS on noble, the historical "stuck/needs re-plug" symptoms are expected to persist with the stock CUPS 2.4.7 backend. The fix is in CUPS ≥2.4.17 only (section 3).
- The "job 5" wedge is a serious claim. It comes from one developer (with code), and nobody has independently confirmed it. CaramOS should reproduce it with a real LBP2900 before choosing the persistent-daemon design.

### Gaps
- No public, systematic multi-job test on an LBP2900 with ValdikSS val plus CUPS ≥2.4.17 but *without* captd. It is unknown whether the job-5 wedge appears there too.
- First-job-after-power-on behaviour of the 2026 code is not documented beyond the toolkit's claims.
- I could not test anything on real hardware; no printer was available.

## 3. How captdriver talks to the printer: CUPS usb backend, libusb, usblp, ccpd, and automatic driver selection

### Takeaway
captdriver is a single CUPS filter, `rastertocapt`, that also acts as the port monitor.
- It uses the stock CUPS `usb` backend (libusb). It writes to stdout and uses the CUPS side channel (`GET_DEVICE_ID`, `DRAIN_OUTPUT`) and back channel to read replies.
- It needs no ccpd, no `/dev/usb/lp0`, no 32-bit libraries.
- The CUPS backend detaches `usblp` per job and re-attaches it afterwards.

Its PPDs have **no `*1284DeviceID`**:
- CUPS's own device-ID lookup does not find the driver.
- system-config-printer's fuzzy matcher (cupshelpers) does pick it for MDL "LBP2900".

The DRAIN_OUTPUT race (CUPS #1461) in the libusb backend is fixed only in CUPS 2.4.17+. noble ships 2.4.7, and Ubuntu 26.04/26.10 still ship 2.4.16.

### Cited Findings
**How the filter talks to the printer**
- [V] `src/capt-command.c` (mounaiban master and ValdikSS):
  - writes chunks with `fwrite(..., stdout)` + `fflush`;
  - then calls `cupsSideChannelDoRequest(CUPS_SC_CMD_DRAIN_OUTPUT, …, 1.0)`;
  - reads replies with `cupsBackChannelRead(…, 15.0)`;
  - gets the device ID with `CUPS_SC_CMD_GET_DEVICE_ID`.

  — [capt-command.c](https://github.com/ValdikSS/captdriver/blob/test/src/capt-command.c).
- The wiki: "In CUPS terminology, captdriver acts both as a filter and a port monitor… as required by CAPT's full-time bi-directional operation" — [wiki Home](https://github.com/mounaiban/captdriver/wiki).
- [C] agalakhov (2018-02-16): "The LBPxxx series sends the data in small chunks and expects a reply from the server after each chunk… make sure the whole processing is done on the machine that acts as a print server, and no bidirectional protocol is forwarded through the network" — [aga#17](https://github.com/agalakhov/captdriver/issues/17).

**The CUPS backend race (#1461)**
- [C] darkvision77 opened OpenPrinting/cups #1461 on 2025-12-28: "Race condition in CUPS USB backend with bi-dir communication". The backend can process the filter's data before `DRAIN_OUTPUT`, then block in `select()` forever, so the filter's side-channel request times out — [cups#1461](https://github.com/OpenPrinting/cups/issues/1461).
- ValdikSS's PR #1500 ("libusb backend: attempt to fix DRAIN_OUTPUT race condition. Fixes #1461") was merged into 2.4.x on 2026-03-04 (merge ca92bf7) and mirrored to master by 2026-03-09 (commit 7dc51eebf) — [PR #1500](https://github.com/OpenPrinting/cups/pull/1500), [commit ca92bf7](https://github.com/OpenPrinting/cups/commit/ca92bf7fcf18e6e055c63ff701934b5d74b5d80d).
- CUPS changelog: v2.4.17 (2026-04-17) "Fixed DRAIN_OUTPUT race condition (Issue #1461)". The current release is v2.4.20 (2026-10-05) — [CHANGES.md 2.4.x](https://github.com/OpenPrinting/cups/blob/2.4.x/CHANGES.md).

**CUPS versions in Ubuntu**
- [V] Ubuntu cups-daemon versions:
  - noble: 2.4.7-1.2ubuntu7.14 (also in noble-updates);
  - resolute 26.04 LTS: 2.4.16-1ubuntu1.3;
  - stonking 26.10: 2.4.16-1ubuntu3.

  — [packages.ubuntu.com](https://packages.ubuntu.com/search?keywords=cups-daemon&searchon=names&exact=1&suite=all&section=all).
- [V] The noble 7.14 changelog (2026-06-11), installed in my container, has no "1461"/"drain" entry.
- [V] The 26.04/26.10 changelogs have none either — [cups 2.4.16-1ubuntu3 changelog](https://changelogs.ubuntu.com/changelogs/pool/main/c/cups/cups_2.4.16-1ubuntu3/changelog), [2.4.16-1ubuntu1.3](https://changelogs.ubuntu.com/changelogs/pool/main/c/cups/cups_2.4.16-1ubuntu1.3/changelog).
- [C] mounaiban (2026-08-13): "the official CUPS APT package is stuck at 2.4.16… There's 2.4.18 available on Snap, but it doesn't work with captdriver" — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5280818961).

**Backporting the fix to noble**
- [V] ValdikSS's CI builds a patched `usb` backend: `apt source cups` on ubuntu-latest, `wget …/ca92bf7….patch`, `patch -p1`, `./configure`, `make`, copy `backend/usb` — [build.yml](https://github.com/ValdikSS/captdriver/blob/test/.github/workflows/build.yml).
- [V] I applied that patch series to noble's `cups 2.4.7-1.2ubuntu7.14` source in a container:
  - It is 3 commits by ValdikSS, 2026-02-26.
  - All hunks apply with offsets. A single `--dry-run` reports one failure only because patch 2 depends on patch 1.
  - `apt-get build-dep cups` and a full build succeed and produce `backend/usb` (107 KB, links libusb-1.0 and libcups.so.2).
  - Not tested against a printer.
- [C] The Bruce Nguyen toolkit does the same on noble/Mint, then **overwrites the dpkg-owned `/usr/lib/cups/backend/usb`** (with a backup) — [may-in-lbp2900.sh](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/may-in-lbp2900.sh).

**usblp and ccpd**
- [V] CUPS 2.4.7 `backend/usb-libusb.c` gets "the 'usblp' kernel module out of the way" with `libusb_detach_kernel_driver()`. It re-attaches it after the job unless the `no-reattach` quirk is set (`USB_QUIRK_NO_REATTACH`) — [usb-libusb.c v2.4.7](https://github.com/OpenPrinting/cups/blob/v2.4.7/backend/usb-libusb.c).
- [V] noble's `/usr/share/cups/usb/org.cups.usb-quirks` has no entry for 04a9:2676. Its only Canon entries are inkjets, and one cites captdriver issue #7 for the MP240.
- [C] A `no-reattach` quirk for 0x04a9 0x2676 was suggested in 2020-03 (LBP3000), then retracted by mounaiban on 2020-03-26. It did not help an LBP2900 on Pi OS (2022-09-26) — [aga#7](https://github.com/agalakhov/captdriver/issues/7#issuecomment-604221791), [aga#7](https://github.com/agalakhov/captdriver/issues/7#issuecomment-1257796827).
- [C] The toolkit stops and masks `ipp-usb`, unloads `usblp`, and optionally writes `/etc/modprobe.d/blacklist-usblp.conf`. It warns that this affects all usblp printers — [may-in-lbp2900.sh](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/may-in-lbp2900.sh).
- Canon's proprietary path instead registers `/dev/usb/lp0` with `ccpdadmin` and runs `ccpd.service`. The Arch Wiki calls captdriver an "open source CAPT driver in early alpha stage not described here" (page last edited 2025-12-20) — [Arch Wiki Canon CAPT](https://wiki.archlinux.org/title/Canon_CAPT).

**The persistent-session alternative**
- [C] palashkaria/the toolkit add a `capt:` backend that talks to a `captd` daemon over `/run/captd/lbp2900.sock`. The daemon "holds one USB connection open across jobs" and "explicitly selects USB vendor/product 04a9:2676". "The `capt:` path… bypasses that [CUPS USB] backend" — [palashkaria README](https://github.com/palashkaria/captdriver/blob/val/README.md).

**Automatic driver selection**
- [V] The PPDs built from every tree contain no `*1284DeviceID`. They do contain:
  - `*NickName: "Canon LBP2900/LBP3000 r2c, 0.1.4"` (ValdikSS-based), or "Canon Inc …" (agalakhov/mounaiban);
  - `*DefaultPageSize: A4`;
  - `*cupsFilter: "application/vnd.cups-raster 1 rastertocapt"`.

  — [canon-lbp.drv](https://github.com/ValdikSS/captdriver/blob/test/src/canon-lbp.drv).
- [V] With the PPDs in `/usr/share/ppd/captdriver/` and cupsd running in a noble container:
  - `lpinfo --device-id 'MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900' -m` returns `client-error-not-found`.
  - `lpinfo --make-and-model 'Canon LBP2900' -m` returns the captdriver PPD (and "IPP Everywhere").
  - cupshelpers `getPPDNameFromDeviceID('Canon','LBP2900',…)` returns `(0, 'lsb/usr/captdriver/CanonLBP-2900-3000.ppd')`, i.e. STATUS_SUCCESS.
  - For MDL `LBP2900B` it returns status 1 (model mismatch) with the same PPD.
- [V] noble's `lpadmin` prints "Printer drivers are deprecated and will stop working in a future version of CUPS" when given a PPD.
- [V] noble's AppArmor profile `/etc/apparmor.d/usr.sbin.cupsd` allows `/usr/lib/cups/filter/** Cxr -> third_party`, but only `/usr/local/** rm` (no exec).
- [C] This matches Debian 13's AppArmor denial of `/usr/local/bin/rastertocapt` (2026-02-24) — [mou#50](https://github.com/mounaiban/captdriver/issues/50).

### Inferences
- With captdriver CaramOS can drop the 32-bit ccpd stack and the usblp/ccpd conflicts. In exchange, reliability becomes a CUPS-backend problem: it needs either a patched `usb` backend for noble or a separate persistent `capt:` backend.
- Overwriting `/usr/lib/cups/backend/usb` as the toolkit does would be reverted by the next noble cups security update (the latest one is dated 2026-06-11). A CaramOS package should instead use one of:
  - a rebuilt `cups` in the CaramOS PPA;
  - a `dpkg-divert`;
  - a separately named backend. CUPS selects backends by URI scheme, and the libusb backend prints `usb://` URIs, so a renamed copy needs code changes.
- Adding `Attribute "1284DeviceID" "" "MFG:Canon;MDL:LBP2900;CMD:CAPT;"` (plus the LBP3000 equivalent) to the `.drv` would probably let CUPS, and tools that rely on device-ID matching, select the driver automatically.

### Gaps
- Whether CaramOS 1.3.6 ships system-config-printer-udev / automatic USB queue creation, and which matcher Cinnamon's printer tool uses, was not checked. The integration researcher may cover it.
- Whether `ipp-usb` really interferes with the LBP2900 is unproven. The printer has no IPP-over-USB interface, so it probably does not.

## 4. Building on noble: dependencies, steps, compiler results, and an offline filter-chain test

### Takeaway
[V] All main trees build cleanly on Ubuntu 24.04 with GCC 13.3 and GCC 14.2: agalakhov, mounaiban master, 0.2.1-pr, ValdikSS, apocarteres and ershad. There are only a few warnings and no errors.
- Build: `autoreconf -fi && ./configure && make && make ppd`.
- Dependencies: `build-essential autoconf automake libcups2-dev cups-ppdc`, plus `pkgconf libusb-1.0-0-dev` for palashkaria's persistent mode.
- The filter cannot be exercised without a printer. It exits immediately with "ERROR: CAPT: unable to communicate with printer", because it first asks the backend for the printer's IEEE-1284 ID.

### Cited Findings
**Environment and build logs**
- [V] Container `ubuntu:24.04`:
  - gcc 13.3.0-6ubuntu2~24.04.1 and gcc-14 14.2.0-4ubuntu2~24.04.1;
  - autoconf 2.71, automake 1.16.5;
  - libcups2-dev and cups-ppdc 2.4.7-1.2ubuntu7.14, cups-filters 2.0.0-0ubuntu4.1, ghostscript 10.02.1~dfsg1-0ubuntu7.10.
- Logs are in `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/captdriver/out1/` (builds), `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/captdriver/out2/` and `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/captdriver/out4/` (filter tests), and `/tmp/claude-1001/-home-dungleviet-Documents-CaramOS/7fcec692-0b55-4439-920f-d4de90fcfa16/scratchpad/lbp2900/captdriver/out3/` (CUPS patch).

**Build results, `autoreconf -fi && ./configure CC=… && make`** (warning counts are GCC 13 / GCC 14)

| Tree | Commit | GCC 13 / 14 warnings |
|---|---|---|
| agalakhov master | 175f8ff | 1 / 0 |
| mounaiban master | 6271924 | 1 / 0 |
| mounaiban 0.2.1-pr | f2d2da8 | 4 / 3 |
| ValdikSS test | 892f320 | 4 / 3 |
| apocarteres | 4b5d41c | 1 / 0 |
| ershad | 258a161 | 4 / 3 |

- [V] The one shared warning is `hiscoa-compress.c:157: 'best_cmd' may be used uninitialized` (GCC 13 only).
- [V] The ValdikSS-based trees add `unused parameter 'state'` and unused `lbp2900_job_prologue`/`lbp6000_job_prologue`. That fits the LBP2900 now using the LBP3000 prologue.
- [V] There were no errors with GCC 14, so no implicit-declaration or incompatible-pointer problems.
- [V] The project sets `AM_CFLAGS = -std=c99 -Wall -Wextra -pedantic` — [src/Makefile.am](https://github.com/ValdikSS/captdriver/blob/test/src/Makefile.am).

**palashkaria and tests**
- [V] palashkaria ee4186a fails at configure (`syntax error near unexpected token LIBUSB`) unless `pkg-config`/pkgconf is installed, because `PKG_CHECK_MODULES` is not defined.
- [V] With `pkgconf libusb-1.0-0-dev` and `./configure --enable-persistent-usb` it builds with 14 warnings (unused functions, ignored `fread`/`fscanf` results).
- [V] Its `make check` runs `test-backend-drain.py`: "PASS: drain ordering and 4 KB frame limit (4 bytes)… (4097 bytes)", TOTAL 1 PASS 1.
- [V] In the other trees `make check` only builds the helper programs `captdefilter` and `test-hiscoa`; no tests run.

**Dependencies and install layout**
- [V] The binary links only `libcups.so.2`. On CUPS 2.4, `cups-config --image --libs` gives `-lcups`, so `libcupsimage2-dev` is not needed.
- [V] `make ppd` (`LC_ALL=C ppdc src/canon-lbp.drv -d ./ppd`) produces `CanonLBP-2900-3000.ppd` and `CanonLBP-3010-3018-3050.ppd`; ValdikSS-based trees also produce `CanonLBP-6000.ppd`.
- [V] mounaiban/ValdikSS `make install` puts `rastertocapt` in `$(bindir)` (`/usr/local/bin`), not in the CUPS filter directory: `bin_PROGRAMS = rastertocapt`.
- The wiki tells users to `cp -p /usr/local/bin/rastertocapt $(cups-config --serverbin)/filter/` — [wiki: Installing on GNU/Linux](https://github.com/mounaiban/captdriver/wiki/Installing-captdriver-on-GNU-Linux).
- palashkaria and gauravyad69 install to `cups-config --serverbin` and honour `DESTDIR` — [palashkaria README](https://github.com/palashkaria/captdriver/blob/val/README.md), [gauravyad69 README](https://github.com/gauravyad69/Canon-LBP2900B).
- The wiki's Debian build environment is `apt install build-essential automake libcups2-dev` (verified there on Debian 10, Ubuntu 19.10, Xubuntu 18.04.1, Zorin OS) — [wiki: Debian build env](https://github.com/mounaiban/captdriver/wiki/Preparing-the-Build-Environment-on-Debian).

**PPD generation and locale**
- [C] AUR user socialolive (2024-01-15): LBP2900 jobs failed with "CAPT: no pages in job" because the PPD was "incorrectly generated". Using `make ppd` instead of plain `ppdc -v -d . src/canon-lbp.drv` fixed it; "Difference seems to be related to LC_ALL=C" — [AUR captdriver-git](https://aur.archlinux.org/packages/captdriver-git).
- [C] ValdikSS links this to a CUPS ppdc fix, commit 0f381a0 (2026-05-20) — [mou#32](https://github.com/mounaiban/captdriver/issues/32#issuecomment-4501206594).

**Offline filter-chain test**
- [V] `cupsfilter -p CanonLBP-2900-3000.ppd -m application/vnd.cups-raster test2.pdf` works on a two-page A4 PDF: exit 0, about 8 MB of CUPS raster, through cups-filters 2.0 "universal" (pdftopdf, then Ghostscript).
- [V] The full chain, `cupsfilter -p … -m printer/foo -e test2.pdf`:
  1. `universal` → `rastertocapt` starts and prints `DEBUG: CAPT: rastertocapt started`.
  2. It prints `ERROR: CAPT: unable to communicate with printer`.
  3. It stops with status 1 after about 0.14 s.
  4. Ghostscript then reports `Unable to open raster stream - : Broken pipe`, and cupsfilter exits 1 with 0 bytes of output.

  Running `PPD=… rastertocapt 1 user title 1 "" file.ras` directly gives the same error and exit 1. The behaviour is identical for mounaiban master, 0.2.1-pr, agalakhov and ValdikSS.
- [V] The cause in the code is `capt_identify()`. It asks the backend over the side channel for the device ID and finds the ops by `MDL:`. With no backend present, the filter stops there — [printer.c](https://github.com/ValdikSS/captdriver/blob/test/src/printer.c).

### Inferences
- Packaging on noble is easy at the build level. The real work is:
  - install paths: `/usr/lib/cups/filter/rastertocapt` and `/usr/share/ppd/captdriver/*.ppd` (or `/usr/share/cups/model`);
  - forcing `LC_ALL=C` for ppdc;
  - optionally a patched `usb` backend or the `captd` daemon.
- Regression testing without hardware would need a CAPT printer emulator behind a fake backend. None exists for `rastertocapt`; palashkaria's test only checks its own backend's drain ordering.

### Gaps
- ARM64 and i386 builds were not tried (amd64 only).
- No print output could be produced or decoded offline. `captdefilter` exists, but `rastertocapt` never emits data without a backend.

## 5. License, copyright holders, and what it means for a PPA package

### Takeaway
captdriver is GPL-3.0-or-later, and none of it is proprietary Canon code. That is fine for a Launchpad PPA, as long as the source package ships COPYING and a correct `debian/copyright`. The licensing blocker is the Bruce Nguyen toolkit's persistent-daemon code (`captd.c`, `capt-backend.c`). It carries no license, and palashkaria imported it as-is.

### Cited Findings
- [V] `COPYING` is the GNU GPL Version 3 text.
- [V] All 18 source headers in ValdikSS/test say "Licensed under the GNU General Public License Version 3… either version 3 of the License, or (at your option) any later version".
- [V] Copyright lines:
  - "Copyright (C) 2013 Alexey Galakhov" (18 files);
  - "Copyright (C) 2016 Alexei Gordeev <KP1533TM2@gmail.com>" (1 file);
  - the PPD source says `Copyright "(C)2020 Moses Chong"`.
- [V] AUTHORS lists Alexey Galakhov and Vitaliy Tomin, "Based on the reverse-engineering done by Nicolas Boichat, Benoit Bolsee".

  — [ValdikSS tree](https://github.com/ValdikSS/captdriver/tree/test), [agalakhov](https://github.com/agalakhov/captdriver).
- GitHub detects the license of both agalakhov and mounaiban as GPL-3.0 — [API](https://api.github.com/repos/mounaiban/captdriver).
- [C] The mounaiban wiki: "This is unofficial software not endorsed or authorised by Canon Inc." — [README.md](https://github.com/mounaiban/captdriver/blob/master/README.md).
- [C] ValdikSS's README says the 2026 code "has been written by LLM assistant" — [README](https://github.com/ValdikSS/captdriver/blob/test/README.md).
- [C] palashkaria's PROVENANCE says it imported `captd.c` and `capt-backend.c` plus six driver files from the toolkit, and that "The toolkit did not include a separate license file at the imported revision" — [PROVENANCE](https://github.com/palashkaria/captdriver/blob/val/docs/PROVENANCE.md).
- [V] The toolkit repo has no LICENSE/COPYING file, and `captd.c` has no license header. GitHub reports no license for the toolkit — [API](https://api.github.com/repos/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit).
- The AUR `canon-lbp2900-capt` PKGBUILD declares `license=('GPL-3.0-or-later')` — [PKGBUILD](https://github.com/gauravyad69/Canon-LBP2900B/blob/master/PKGBUILD).

### Inferences
- `debian/copyright` for a CaramOS package should name at least Alexey Galakhov (2013), Alexei Gordeev (2016), Moses Chong/mounaiban (2020–2022), Vitaliy Tomin, and the 2026 contributors (ValdikSS, plus ershad/apocarteres if their patches are used), all under GPL-3+.
- The toolkit's modified driver files are derived from GPL-3+ files, so they must be GPL. The new files `captd.c` and `capt-backend.c` have no license grant. CaramOS should get written GPL-3+ permission from Bruce Nguyen, who is Vietnamese and reachable on GitHub, before shipping palashkaria's persistent mode. Otherwise it should reimplement them.
- A CUPS backend patch taken from OpenPrinting is under CUPS's Apache-2.0 (with exceptions). That is compatible with redistributing a patched cups in a PPA.

### Gaps
- I did not check Launchpad's PPA terms text or Debian ftp-master policy on LLM-generated code.
- The CUPS license statement was not fetched in this session. It comes from general knowledge and should be checked if it matters.

## 6. Packaging elsewhere

### Takeaway
There is **no captdriver package in Debian or Ubuntu**, in any suite through 27.04 "tenacious", and **no Launchpad PPA named captdriver**. Where it is packaged (AUR, Gentoo GURU, LiGurOS, nixpkgs, ALT, ROSA, OpenMandriva), it is built from old mounaiban snapshots (0.1.4-m5 or the 2023 GxB branch). The exceptions are ROSA (the cryptoluks AI fork) and AUR `canon-lbp2900-capt` (gauravyad69, 2026-11-05). Nobody packages ValdikSS's 2026 fork yet.

### Cited Findings
**Arch User Repository**
- `captdriver-git` r170.6271924-1 (mounaiban master): maintainer mistersmee, 9 votes, last modified 2024-01-16, "(not stable, formerly foo2capt)".
- Comments:
  - [C] LBP2900B daily use (2025-05-06).
  - LBP3010, LBP3050 and LBP6000B reports work (2025–2026).
  - LBP2900 "no pages in job" fixed by `make ppd` (2024-01-15).

  — [AUR captdriver-git](https://aur.archlinux.org/packages/captdriver-git), [AUR RPC](https://aur.archlinux.org/rpc/v5/search/capt?by=name).
- `canon-lbp2900-capt` 0.3.3-1 (gauravyad69, modified 2026-11-05, 0 votes): "CUPS driver for Canon LBP2900/LBP3000 CAPT printers (reverse-engineered)"; `provides`/`conflicts` captdriver.
- `captppd` 1.0.0 (CAPT v1 only, 2026-01-22).
- `capt-src` 2.71 (Canon's proprietary driver, 80 votes).

— [AUR canon-lbp2900-capt](https://aur.archlinux.org/packages/canon-lbp2900-capt).

**Gentoo GURU / LiGurOS**
- `net-print/captdriver` 0.1.4. The ebuild (Copyright 2025) fetches mounaiban tag `0.1.4-m5`, which is commit d920628 of 2020-11-16.
- It runs `ppdc -v -d . src/canon-lbp.drv`, without `LC_ALL=C`.
- It installs the filter into `$(cups-config --serverbin)/filter` and the PPDs into `/usr/share/ppd`.
- Maintainer: Nguyen Dinh Dang Duong <dangduong31205@gmail.com>.

— [repology captdriver](https://repology.org/project/captdriver/versions), [GURU ebuild](https://github.com/gentoo/guru/blob/master/net-print/captdriver/captdriver-0.1.4.ebuild), [metadata.xml](https://github.com/gentoo/guru/blob/master/net-print/captdriver/metadata.xml).

**nixpkgs**
- `canon-capt` 0.1.4.2-GxB: rev 8ecc3cd (mounaiban 0.1.4.2-GxB, 2023-01-18), maintainer cryptoluks.
- Installs `lib/cups/filter/rastertocapt` and `share/cups/model/canon/*.ppd`.
- In nix 24.05 through 26.05 and unstable.

— [package.nix](https://github.com/NixOS/nixpkgs/blob/master/pkgs/by-name/ca/canon-capt/package.nix), [repology canon-capt](https://repology.org/project/canon-capt/versions).

**ALT Linux p11/Sisyphus**
- `printer-driver-foo2capt` 0.1.4.2-alt1.git_2_8ecc3cd (same GxB commit), maintainer ruslandh@altlinux.org, GPL-3.0-or-later — [repology](https://repology.org/project/printer-driver-foo2capt/versions).

**ROSA 2019.1/13**
- `cups-drivers-captdriver` 0.1.4.2-1.git51a9b6.3, i.e. cryptoluks master 51a9b67 (2026-02-28): "Driver for Canon CAPT printers LBP2900/3000/3010/3100/3108/3150/6000/6018".
- ROSA also ships `captppd` and `libcapt`.

— [repology cups-drivers-captdriver](https://repology.org/project/cups-drivers-captdriver/versions).

**OpenMandriva**
- 6.0/rolling/cooker, in the "unsupported" repo: `cups-drivers-captdriver` 0.1.4-0.20231218git.1, maintainer bero.
- [C] hgkamath maps this snapshot to mounaiban 711d4a5, dated 2020-11-16 (2025-10-30).

— [repology](https://repology.org/project/cups-drivers-captdriver/versions), [mou#49](https://github.com/mounaiban/captdriver/issues/49).

**Mageia, PCLinuxOS, ROSA, OpenMandriva: `cups-drivers-capt` 0.1**
- This is a separate "capt" 0.1 package, and probably not captdriver — [repology cups-drivers-capt](https://repology.org/project/cups-drivers-capt/versions).

**Places with nothing found**
- Ubuntu: packages.ubuntu.com, searching all suites (jammy … resolute, stonking, tenacious), says "Sorry, your search gave no results" — [packages.ubuntu.com](https://packages.ubuntu.com/search?keywords=captdriver&searchon=names&suite=all&section=all).
- Debian: repology lists no Debian package, and packages.debian.org returned an empty page to my fetch — [repology](https://repology.org/project/captdriver/versions).
- Launchpad: "No matching Personal Package Archive for 'captdriver'". PPAs matching "capt" (michael-gruz/canon and its forks) are for Canon's proprietary drivers — [Launchpad PPA search](https://launchpad.net/ubuntu/+ppas?name_filter=captdriver).
- Fedora COPR: an API search for "captdriver" returned 0 projects — [COPR API](https://copr.fedorainfracloud.org/api_3/project/search?query=captdriver).
- Guix: no gnuguix entry in repology for captdriver or canon-capt.

**Reference packaging and installers**
- The toolkit is an interactive installer for noble/Mint (Vietnamese UI), not a package — [README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/README.md).
- ousui's 2023 branch has a prebuilt `.deb` tree — [ecbc6f7](https://github.com/ousui/captdriver/commit/ecbc6f717e8cbefecfe354aba6530f3b38bcfbbe).

### Inferences
- A CaramOS `printer-driver-captdriver` (Debian naming) would be the first Debian-format source package.
- The nixpkgs and Gentoo recipes are the best references for install paths. The Gentoo recipe is also a cautionary example for missing `LC_ALL=C`.
- Because downstreams pin 2020–2023 snapshots, their "it works" reports say little about the 2026 code.

### Gaps
- openSUSE OBS could not be checked: software.opensuse.org returned a bot-check page.
- AUR comments mentioning the LBP2900 are few; I saw all 10 comments on captdriver-git.

## 7. What needs fixing or improving for everyday use in Vietnamese offices

### Takeaway
To be office-grade on CaramOS (noble), a captdriver package needs:
1. **Reliable multi-job operation.** Backport the CUPS #1461 fix to noble's 2.4.7 backend (shown to apply and build), and decide whether the LBP2900 "job-5 wedge" needs the persistent `captd` session.
2. **The status-decoding fix** (PR #55) and graceful handling of bad replies.
3. **Real status reporting.** Today no tree emits standard CUPS printer-state-reasons, so the GUI cannot say "out of paper" or "paper jam", in Vietnamese or any language.
4. **Automatic driver selection** (`*1284DeviceID`).
5. **Correct install paths for AppArmor**, and PPDs generated under `LC_ALL=C`.
6. **A4 consistency.** The PPD already defaults to A4; applications should match it.
7. **Clear recovery after jams.**

### Cited Findings
**Reliability**
- [C] CUPS ≥2.4.17 is needed "to make it work reliably" (ValdikSS README, 2026). [V] noble has 2.4.7 without the fix, and the fix applies to noble's source (section 3) — [README](https://github.com/ValdikSS/captdriver/blob/test/README.md).
- [C] The LBP2900 "job 5" wedge and the persistent-session fix: "58 jobs in one power-on session with zero wedges" (toolkit, 2026-07-14/22) — [captd README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/captd-persistent-daemon/README.md).
- [C] palashkaria recovery notes: "An already-wedged engine may need one physical power cycle… Paper jams, an open cover or a missing cartridge may still require clearing the physical problem and reprinting". It suggests `-o printer-error-policy=stop-printer` — [README](https://github.com/palashkaria/captdriver/blob/val/README.md).
- [V] `capt_sendrecv()` calls `exit(1)` on "bad reply from printer" in ValdikSS/test.
- [C] Users see this as `CAPT: bad reply from printer, expected A1 A1 xx xx xx xx, got 30 2A 01 01 F0 FF` (LBP3000, Debian 13, 2026-02-24); afterwards only the first print works — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-3955116042).
- [C] The toolkit replaces the `exit(1)` with a bounded resync — [captd README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/captd-persistent-daemon/README.md).
- [C] PR #55 fixes the status decoding that hangs LBP2900 jobs — [PR #55](https://github.com/mounaiban/captdriver/pull/55).

**Status reporting and error messages**
- [V] mounaiban master and ValdikSS/test contain no `"STATE:"` lines, i.e. no standard CUPS printer-state-reasons.
  - ValdikSS reports out-of-paper only through `DEBUG:` lines.
  - User-visible errors are English-only strings such as "ERROR: CAPT: unable to communicate with printer", "ERROR: CAPT: no pages in job" and "ERROR: CAPT: fatal printer error: %s (Eng=0x%04x) — aborting".
  - palashkaria defines a custom reason `com.captdriver.engine-wedged` in `capt-status.h`, but I found no code that emits it.

  — [prn_lbp2900.c](https://github.com/ValdikSS/captdriver/blob/test/src/prn_lbp2900.c), [capt-status.h (palashkaria)](https://github.com/palashkaria/captdriver/blob/val/src/capt-status.h).
- [C] A Debian 13 user would like jam guidance "like the official windows driver detected the paper jam, and it has given instructions about how to fix it" (2026-02-28) — [mou#8](https://github.com/mounaiban/captdriver/issues/8).

**A4 and page geometry**
- [V] All PPDs default to A4 (`*DefaultPageSize: A4`, 61 page sizes) — [canon-lbp.drv](https://github.com/ValdikSS/captdriver/blob/test/src/canon-lbp.drv).
- [C] Letter-vs-A4 mismatches caused blank pages and stuck jobs on the LBP2900 (2022-10-01) — [aga#56](https://github.com/agalakhov/captdriver/issues/56#issuecomment-1264366085).
- [C] The 2026 margin and page-end fixes exist only in ValdikSS/0.2.1-pr — [mou#29](https://github.com/mounaiban/captdriver/issues/29#issuecomment-4500983657).

**Installation details**
- [C] The AppArmor denial for filters under `/usr/local` (Debian 13, 2026-02-24) — [mou#50](https://github.com/mounaiban/captdriver/issues/50).
- [V] noble's profile only lets filters execute from `/usr/lib/cups/filter/**`.
- [C] The PPD locale issue: AUR comment (2024-01-15) — [AUR](https://aur.archlinux.org/packages/captdriver-git).

**Speed and quality**
- [C] ValdikSS added page streaming (2026-05-20) — [mou#7](https://github.com/mounaiban/captdriver/issues/7#issuecomment-4501026561).
- [C] akbezrukov added parallel compression (2026-06-02) — [aec0826](https://github.com/akbezrukov/captdriver/commit/aec082694f8989ec22ee658000f24a13dd36c28f).
- [C] mounaiban says the structural bottleneck is that captdriver needs a full uncompressed raster from Ghostscript, and a Ghostscript device is "part of the master plan" (2026-05-19) — [mou#48](https://github.com/mounaiban/captdriver/pull/48#issuecomment-4486945093).
- [C] Print density: the dithering is unsuited to laser printers, and the libcupsfilters foo2zjs algorithm needs PPD integration (2026-05-14) — [mou#33](https://github.com/mounaiban/captdriver/issues/33#issuecomment-4454687801).

**Manual duplex**
- [V] The mounaiban master PPD has `captManualDuplex`; ValdikSS's does not.
- [C] Manual duplex "not working on Debian 13": no prompt appears and the job vanishes after page 1 (2026-02-24) — [mou#51](https://github.com/mounaiban/captdriver/issues/51).
- [C] ValdikSS wants to implement "proper manual duplex printing" (2026-08-13) — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5281082555).

**Sharing to Windows PCs (common in VN offices)**
- [C] Windows clients that use Canon's Windows CAPT driver against a CUPS share get stuck at "Sending data to printer" (2018-02-16, 2025-12-30) — [aga#36](https://github.com/agalakhov/captdriver/issues/36#issuecomment-3699579108), [aga#17](https://github.com/agalakhov/captdriver/issues/17).
- [C] One user fixed it with Apple Bonjour Print Services, so the CUPS share was used independent of the Canon driver (2020-10-20) — [aga#7](https://github.com/agalakhov/captdriver/issues/7).
- [C] The toolkit ships `.bat`/`.ps1` scripts that add the CUPS queue via IPP with Windows' built-in driver — [README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/README.md).

**Future risk**
- [V] noble's `lpadmin` warns that PPD "Printer drivers are deprecated and will stop working in a future version of CUPS".

### Inferences
- Priority fixes for a CaramOS package:
  1. Patched noble `usb` backend, or the `captd`/`capt:` path after hardware validation.
  2. PR #55 plus a resync on bad replies.
  3. Emit `STATE: +media-empty-error`, `+media-jam-error`, `+door-open-error` and `+toner-empty-*` from the existing status bits. CUPS and desktop tools translate these standard keywords, which yields Vietnamese messages for free.
  4. `*1284DeviceID` in the `.drv`.
  5. Install to `/usr/lib/cups/filter`; build PPDs with `LC_ALL=C`.
  6. Ship a queue default `printer-error-policy` (`retry-job`, or `stop-printer` plus a notification) and A4 `/etc/papersize`.
  7. A one-click "reset printer" helper (USB reset), as in the toolkit.
- For networks, document that Windows clients should add the CUPS queue as an IPP printer with the generic Microsoft IPP class driver, never Canon's CAPT driver.

### Gaps
- No data on how the LBP2900 behaves with Vietnamese-locale applications (LibreOffice, WPS, Chrome) beyond the generic Letter/A4 issue.
- Whether CUPS's Vietnamese translations of the standard state reasons are complete was not checked.

## 8. Which captdriver code base CaramOS should package (overall assessment)

### Takeaway
For the LBP2900 on noble, the best base is the **ValdikSS 2026 line**, taken as mounaiban's `0.2.1-pr`, which has the same code with LLM comments trimmed and is staged for upstreaming, or as ValdikSS `val`. Pin a commit and add:
1. ershad's PR #55;
2. a noble backport of the CUPS #1461 USB-backend fix;
3. CaramOS packaging fixes (install path, `LC_ALL=C` PPDs, `*1284DeviceID`).

Treat palashkaria's persistent `captd` mode (2026-11-05) as a candidate. Ship it only after reproducing the "job 5" wedge on a real LBP2900 and getting a GPL grant for the toolkit-derived daemon code. mounaiban master (2022) is what other distros ship, but it carries all the known LBP2900 bugs. Every option is "experimental-grade": no tree has been released or tagged since 2020.

### Cited Findings
- [C] ValdikSS fork: fixes paper dimensions, page shift after page 1, slow start, streaming, error handling. It needs CUPS 2.4.17+ and is "not ready for the release yet". The author calls the code "pretty nasty" but says "It works though… pretty ok" — [README](https://github.com/ValdikSS/captdriver/blob/test/README.md), [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4714536714), [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5281082555).
- [C] mounaiban plans to merge 0.2.1-pr into master and PR it to agalakhov (2026-08-13) — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-5280818961).
- [V] 0.2.1-pr and ValdikSS/test build identically on noble (4/3 warnings, no errors). The src diff between them is essentially comments.
- [C] LBP2900 success with ValdikSS's build plus newer CUPS (2026-06-14) — [mou#8](https://github.com/mounaiban/captdriver/issues/8#issuecomment-4701986539).
- [C] The LBP2900 job-5 wedge with ValdikSS val, fixed only by the persistent session (toolkit, 2026-07) — [captd README](https://github.com/brucenguyen1102/Canon-LBP2900-CAPT-Toolkit/blob/main/captd-persistent-daemon/README.md).
- palashkaria/val packages that fix on top of ValdikSS val (2026-11-05) — [commit](https://github.com/palashkaria/captdriver/commit/ee4186affae34a7e2da89291da2a7906a7311f2f).
- [V] palashkaria's persistent build and hardware-free test pass on noble.
- [V] mounaiban master still has the swapped-margin and no-page-end-flag code that ValdikSS fixed, and the status-decoding bug — [mou#29](https://github.com/mounaiban/captdriver/issues/29#issuecomment-4615007355), [PR #55](https://github.com/mounaiban/captdriver/pull/55).
- [V] The last tag in mounaiban is `0.1.4-m5` (2020-11-16). agalakhov has no tags.

### Inferences
- Recommended plan:
  1. Package `0.2.1-pr` @ f2d2da8, or a later merged master, as `printer-driver-captdriver` in the CaramOS PPA, plus PR #55.
  2. Ship a rebuilt noble `cups` 2.4.7 with PR #1500 (ca92bf7) in the same PPA, so the stock `usb://` path works.
  3. Run a 30–60 job soak test on a real LBP2900/2900B, including power-on/first-job, out-of-paper mid-job, Letter/A4 mismatches and complex PDFs.
  4. If the job-5 wedge reproduces, adopt palashkaria's `--enable-persistent-usb` (`captd` + `capt:`), after clarifying the license with Bruce Nguyen.
  5. Follow the move to OpenPrinting that ValdikSS announced and rebase when it happens.
- Not recommended:
  - cryptoluks: an AI refactor of the old base, without the 2026 protocol work.
  - gauravyad69: an independent fork; good for AUR users but diverged.
  - akbezrukov: speed only.

  They are useful as sources of individual patches (for example the parallel compression, or apocarteres' reply-buffer/Envelope/Darkness fixes).

### Gaps
- None of the candidate trees has published, reproducible LBP2900 test results.
- The choice between the stock-backend path and the persistent-daemon path cannot be settled without hardware tests on CaramOS itself.
