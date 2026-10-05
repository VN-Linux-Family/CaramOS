# CaramOS OTA — Quy trình dev/test trên VM (golden VM + snapshot)

Tài liệu này mô tả cách test `caramos-ota` trên máy ảo mà **không phải dựng lại VM sau mỗi lần thử**.

Ý tưởng: chuẩn bị một VM "sạch" đúng một lần (đã có SSH key, sudo không hỏi mật khẩu), chụp
snapshot cả đĩa lẫn RAM. Mỗi vòng test chỉ cần revert về snapshot đó (~20 giây) rồi ship bản mới.
Mọi thay đổi mà migration cũ đã ghi vào hệ thống biến mất hoàn toàn, không cần viết logic rollback.

```text
            (một lần)                                (mỗi vòng test)
create → cài/boot → bootstrap → setup → snapshot ──► reset → ship|sync → test → logs/shot
                                             ▲                                      │
                                             └──────────────────────────────────────┘
```

Tất cả lệnh dưới đây chạy trên **máy host**, trong `packages/caramos-ota`, **không dùng `sudo`**.

---

## 1. Tra nhanh

| Việc cần làm | Lệnh |
| --- | --- |
| Đưa VM về trạng thái sạch | `make vm-reset` |
| Build `.deb`, cài vào VM, chuẩn bị state update | `make ship` |
| Đẩy thẳng source vào VM, không build `.deb` | `make sync` |
| Chạy migration E2E qua CLI | `make test` |
| Mở Trung tâm cập nhật trong desktop VM | `make test-notifier` |
| Một phát: reset → ship → test → logs | `make vm-e2e` |
| Kéo state/log/journal về host | `make vm-logs` |
| Chụp màn hình VM | `make vm-shot` |
| Xem VM đang ở trạng thái nào | `make vm-status` |
| Mở shell trong VM | `make vm-ssh` |
| Test từ bản base khác | thêm `BASE=1.0.12` vào bất kỳ lệnh nào |

Mọi target `vm-*` gọi `tools/vm-dev.sh`; chạy `./tools/vm-dev.sh help` để xem đủ lệnh và cấu hình đang áp dụng.

---

## 2. Yêu cầu trên máy host

- Linux có KVM (`ls /dev/kvm`), libvirt và QEMU.
- User của bạn thuộc group `libvirt` (để gọi `virsh -c qemu:///system` không cần sudo).
- Có SSH public key trong `~/.ssh/` (`id_ed25519.pub`, `id_ecdsa.pub` hoặc `id_rsa.pub`).
- Một file ISO CaramOS của bản base, mặc định `<repo>/CaramOS-<BASE>-cinnamon-amd64.iso`.

```bash
sudo apt install qemu-kvm libvirt-daemon-system virtinst virt-viewer sshpass rsync \
                 build-essential debhelper
sudo usermod -aG libvirt "$USER"     # đăng xuất/đăng nhập lại để có hiệu lực
ls ~/.ssh/*.pub || ssh-keygen -t ed25519
```

Kiểm tra:

```bash
virsh -c qemu:///system list --all   # không được báo lỗi quyền
```

> VirtualBox và KVM không chạy song song ổn định. Nếu đang mở VM VirtualBox thì tắt nó trước.

---

## 3. Setup một lần cho mỗi bản base

Ví dụ với base `1.0.16` (mặc định). Với base khác, thêm `BASE=x.y.z` vào từng lệnh hoặc ghi vào
`vm.local.env` (mục 7).

### Bước 1 — Tạo VM

```bash
make vm-create
```

Lệnh này tạo domain libvirt `caram1.0.16` (4 CPU, 6 GB RAM, đĩa qcow2 40 GB, BIOS, mạng NAT
`default`, có kênh qemu-guest-agent) và boot từ ISO. Mở màn hình VM:

```bash
virt-viewer -c qemu:///system caram1.0.16      # hoặc dùng virt-manager
```

### Bước 2 — Chọn kiểu VM

| | Cài vào đĩa (khuyên dùng) | Live session |
| --- | --- | --- |
| Cách làm | Bấm icon **Cài đặt CaramOS** trên desktop, cài xong reboot, đăng nhập | Không làm gì, dùng luôn desktop live |
| Giống máy người dùng thật | Có | Không (casper, user live, apt có nguồn cdrom) |
| Dung lượng `/` | Cả đĩa 40 GB | ~3 GB nằm trong RAM, dễ đầy khi migration cài nhiều package |
| Tốn thời gian setup | Thêm ~10 phút cài đặt | Không |

Khi cài vào đĩa, đặt username là `caram` (hoặc ghi username bạn chọn vào `REMOTE_USER` trong
`vm.local.env`).

Sau khi trình cài đặt khởi động lại, **lần đầu VM sẽ tắt hẳn** thay vì khởi động lại (cấu hình tạm của
`virt-install` cho lần boot cài đặt). Bật lại bằng `./tools/vm-dev.sh up`; các lần sau khởi động lại bình thường.

#### Cài vào đĩa tự động (không cần bấm)

Khi VM đang ở desktop live và đã qua bước 3–4 (SSH + `vm-setup`), có thể cài không cần tương tác bằng
preseed trong `tools/vm-install-preseed.cfg` (xoá `/dev/vda`, user `caram` / `caram123`, tự đăng nhập):

```bash
./tools/vm-dev.sh ssh 'cat > /tmp/caramos-preseed.cfg' < tools/vm-install-preseed.cfg
./tools/vm-dev.sh ssh 'sudo -n debconf-set-selections /tmp/caramos-preseed.cfg'
./tools/vm-dev.sh gui-bg "sudo -n --preserve-env=DISPLAY,XAUTHORITY,DBUS_SESSION_BUS_ADDRESS,XDG_RUNTIME_DIR sh -c 'WEBKIT_DISABLE_COMPOSITING_MODE=1 ubiquity --automatic gtk_ui'"
```

Theo dõi bằng `make vm-shot` (mất khoảng 30–40 phút). Khi màn hình báo *Please remove the installation
medium, then press ENTER*: `./tools/vm-dev.sh key enter`, rồi `./tools/vm-dev.sh up` khi VM đã tắt. Bản đã
cài chưa có SSH, nên làm lại bước 3 với `VM_SUDO_PROMPT=1 REMOTE_PASSWORD=caram123 make vm-bootstrap`, rồi
bước 4 và 5.

Nên đặt domain riêng cho bản cài đĩa để giữ cả VM live, ví dụ `VM_DOMAIN=caram1.0.16-disk` cho mọi lệnh
(`make vm-create`, `make vm-reset`, ...).

### Bước 3 — Bật SSH trong VM

VM mới chưa có `openssh-server`. Để script tự gõ lệnh cài vào VM:

```bash
make vm-bootstrap                       # live session
VM_SUDO_PROMPT=1 REMOTE_PASSWORD=<mật khẩu user> make vm-bootstrap   # bản cài vào đĩa
```

Script mở terminal trong VM bằng `Ctrl+Alt+T`, gõ lệnh cài `openssh-server`, đặt mật khẩu user
(mặc định `caram123`, hoặc giá trị `REMOTE_PASSWORD`) rồi chờ SSH lên. Desktop VM phải đang đăng
nhập và không khoá màn hình.

Nếu muốn làm tay, mở terminal trong VM và chạy:

```bash
sudo sh -c 'apt-get update; apt-get install -y openssh-server && echo caram:caram123 | chpasswd && systemctl enable --now ssh'
```

### Bước 4 — Cài SSH key, sudo không mật khẩu, guest agent

```bash
REMOTE_PASSWORD=caram123 make vm-setup
```

(Bỏ `REMOTE_PASSWORD` thì script sẽ hỏi mật khẩu.) Lệnh này chạy lại bao nhiêu lần cũng được, và làm
các việc sau trong VM:

- thêm public key của host vào `~/.ssh/authorized_keys`;
- tạo `/etc/sudoers.d/90-caramos-vm-dev` cho user test sudo không cần mật khẩu;
- tắt nguồn apt `cdrom:` (nếu có), cài `qemu-guest-agent` và `rsync`;
- tắt khoá màn hình và tắt màn hình khi rảnh, để ảnh chụp luôn thấy desktop.

Từ đây không cần mật khẩu nữa.

### Bước 5 — Chụp snapshot nền

Đảm bảo desktop VM đang đăng nhập, đóng hết cửa sổ thừa, rồi:

```bash
make vm-snapshot
make vm-status
```

Snapshot tên `clean` lưu cả đĩa lẫn RAM (VM đứng hình ~25 giây khi lưu). Kết quả mong đợi của
`make vm-status`:

```text
Domain:    caram1.0.16 (running) on qemu:///system
Snapshots: clean
IP:        192.168.122.32
SSH:       ok (caram@192.168.122.32:22)
sudo -n:   ok
Release:   1.0.16
Package:   caramos-ota 1.0.16-0caramos1 (ii )
```

Muốn chụp lại snapshot nền (ví dụ sau khi chỉnh thêm gì đó trong VM): `FORCE=1 make vm-snapshot`.

---

## 4. Vòng lặp hằng ngày

### 4.1 Kiểm tra đầy đủ bằng gói `.deb` thật

```bash
make vm-reset        # ~20 giây: VM quay về đúng lúc chụp snapshot, desktop vẫn đang đăng nhập
make ship            # ~40 giây: build .deb, copy, cài, ghi version test, chạy caramos-ota --check
make test            # dry-run rồi chạy migration thật qua CLI
make vm-logs         # kéo log về dist-testkit/vm-logs/<thời điểm>/
```

Hoặc gộp lại: `make vm-e2e` (log vẫn được kéo về kể cả khi test fail; mã thoát là của bước test).

`make ship` ghi `/etc/caramos-release` trong VM thành `TEST_RELEASE_FROM` (mặc định trong `Makefile`)
trước khi chạy `--check`. Đổi bản nguồn giả lập: `make ship TEST_RELEASE_FROM=1.0.16`.

### 4.2 Test giao diện

```bash
make test-notifier   # cài lại .deb đã ship, chuẩn bị state, mở Trung tâm cập nhật trong desktop VM
make vm-shot         # in ra đường dẫn file PNG
```

Chạy lệnh GUI bất kỳ trong phiên desktop của VM từ host:

```bash
./tools/vm-dev.sh gui gsettings get org.cinnamon enabled-applets
./tools/vm-dev.sh gui-bg caramos-ota-notifier      # chạy nền, output ở /tmp/caramos-vm-gui.log trong VM
./tools/vm-dev.sh key enter                        # bấm phím
./tools/vm-dev.sh key ctrl+alt+t
./tools/vm-dev.sh type 'caramos-ota --status'      # gõ chữ vào cửa sổ đang focus
```

### 4.3 Lặp nhanh khi đang sửa Python/applet (không build `.deb`)

```bash
make vm-reset sync   # reset rồi rsync source đè lên bản đang cài, vài giây
./tools/vm-dev.sh ssh 'sudo caramos-ota-update --from 1.0.16 --target 1.0.16.1 --dry-run'
```

`make sync` đọc `debian/install` để biết file nào đi đâu, nên thêm đường dẫn mới vào `debian/install`
là `sync` tự theo. Sau khi copy, nó chạy `systemctl daemon-reload` và yêu cầu Cinnamon nạp lại các
applet của gói.

Giới hạn của `sync`, cần nhớ:

- Không chạy `postinst`/`prerm`, không đổi version trong dpkg. Thay đổi ở `debian/` phải test bằng `make ship`.
- Notifier đang chạy vẫn giữ code cũ: `./tools/vm-dev.sh ssh pkill -f caramos-ota-notifier` rồi mở lại.
- File bị xoá khỏi source cũng bị xoá trong VM, nhưng chỉ trong các thư mục riêng của gói.
- Trước khi mở PR luôn chạy lại bằng gói thật: `make vm-e2e`.

### 4.4 Khi nào phải reset

Reset trước mỗi lần chạy migration thật. Migration ghi ledger và sửa hệ thống, lần chạy sau sẽ không
còn là "máy 1.0.16 chưa update" nữa. Chỉ sửa giao diện notifier/applet thì `make sync` liên tục, không
cần reset.

---

## 5. Debug

### Log

`make vm-logs` tạo thư mục `dist-testkit/vm-logs/<YYYYmmdd-HHMMSS>/`:

| File | Nội dung |
| --- | --- |
| `var-lib-caramos-ota/` | `state.json`, `migrations.json` (ledger) |
| `var-log-caramos-ota/` | log của từng lần chạy OTA |
| `journal-ota.txt` | các dòng journal có `caramos-ota` |
| `journal-boot.txt` | 4000 dòng journal cuối của lần boot hiện tại |
| `xsession-errors.txt` | lỗi của Cinnamon/applet (JS exception nằm ở đây) |
| `apt-history.txt`, `apt-term.txt`, `dpkg.txt` | apt/dpkg đã làm gì |
| `systemd.txt`, `failed-units.txt` | trạng thái timer/service OTA, unit lỗi |
| `package.txt`, `release.txt` | version gói đang cài, các file release |
| `enabled-applets.txt` | applet đang bật trên panel |
| `gui-command.txt` | output của lệnh chạy bằng `gui-bg` (ví dụ notifier) |

### Màn hình và chuột

```bash
make vm-shot                                   # chụp, in đường dẫn PNG
./tools/vm-dev.sh click 1250 775               # click trái tại toạ độ pixel của ảnh chụp
./tools/vm-dev.sh click 640 400 right          # click phải
./tools/vm-dev.sh key esc                      # đóng popup
```

Ví dụ mở Control Center trên panel: chụp màn hình, lấy toạ độ icon ở góc phải dưới, `click` vào đó,
rồi chụp lại. Click đi qua chuột ảo của QEMU nên không cần cài gì trong VM.


`make vm-shot` chụp qua hypervisor nên chụp được cả màn hình đăng nhập, Plymouth, màn hình đen.
Ảnh nằm ở `dist-testkit/vm-shots/`. Chỉ định tên file: `./tools/vm-dev.sh shot /tmp/a.png`.

### Khi SSH chết

Migration làm hỏng mạng hoặc sshd thì vẫn chạy lệnh root qua qemu-guest-agent:

```bash
./tools/vm-dev.sh agent-exec 'systemctl status ssh --no-pager; ip -br addr'
```

Sau đó `make vm-reset` để quay về trạng thái tốt.

### Làm việc với AI agent (Claude Code...)

Agent chạy được toàn bộ vòng lặp mà không cần người copy-paste: `make vm-e2e`, đọc
`dist-testkit/vm-logs/`, xem ảnh từ `make vm-shot`, bấm nút bằng `vm-dev.sh click`/`key`. Chỉ cần VM đã
setup xong ở mục 3 và `make vm-status` báo `SSH: ok`, `sudo -n: ok`.

---

## 6. Nhiều bản base

Mỗi bản base là một domain riêng `caram<BASE>` với snapshot `clean` riêng:

```bash
make vm-create BASE=1.0.12             # cần CaramOS-1.0.12-cinnamon-amd64.iso ở gốc repo
make vm-bootstrap BASE=1.0.12
REMOTE_PASSWORD=caram123 make vm-setup BASE=1.0.12
make vm-snapshot BASE=1.0.12

make vm-e2e BASE=1.0.12 TEST_RELEASE_FROM=1.0.12
```

Cũng có thể giữ nhiều snapshot trên một VM, ví dụ một snapshot sau khi đã ship:

```bash
./tools/vm-dev.sh snapshot shipped
./tools/vm-dev.sh reset shipped
./tools/vm-dev.sh snapshots
```

Nhiều VM chạy cùng lúc tốn RAM (6 GB mỗi máy). Tắt máy không dùng và bật lại khi cần:

```bash
BASE=1.0.12 ./tools/vm-dev.sh down
BASE=1.0.12 ./tools/vm-dev.sh up      # hoặc make vm-reset BASE=1.0.12, revert sẽ tự bật máy
```

---

## 7. Cấu hình

Thứ tự ưu tiên: tham số dòng lệnh/biến môi trường → `vm.local.env` → mặc định.

Cấu hình riêng của từng dev đặt trong `packages/caramos-ota/vm.local.env` (đã git-ignore):

```bash
cp vm.local.env.example vm.local.env
```

| Biến | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `BASE` | `1.0.16` | Bản CaramOS làm nền |
| `VM_DOMAIN` | `caram<BASE>` | Tên domain libvirt |
| `VM_SNAPSHOT` | `clean` | Snapshot dùng cho `vm-snapshot`/`vm-reset` |
| `REMOTE_USER` | `caram` | User trong VM |
| `REMOTE_HOST` | rỗng | Rỗng = hỏi libvirt IP của `VM_DOMAIN`. Đặt giá trị = SSH thẳng tới host đó |
| `REMOTE_PORT` | `22` | Cổng SSH |
| `REMOTE_PASSWORD` | rỗng | Chỉ dùng trước khi `vm-setup` cài key, hoặc cho VM live dùng một lần |
| `VM_ISO` | `<repo>/CaramOS-<BASE>-cinnamon-amd64.iso` | ISO cho `vm-create` |
| `VM_MEMORY_MB` / `VM_CPUS` / `VM_DISK_GB` | `6144` / `4` / `40` | Cấu hình máy cho `vm-create` |
| `VM_SSH_PUBKEY` | key đầu tiên tìm thấy trong `~/.ssh` | Public key cài vào VM |
| `VM_TERMINAL_WAIT` | `15` | Số giây `vm-bootstrap` chờ terminal mở trước khi gõ |
| `VM_SUDO_PROMPT` | `0` | `1` nếu `sudo` trong VM hỏi mật khẩu (bản cài vào đĩa) khi `vm-bootstrap` |
| `VM_KEEP_OTA_TIMER` | `0` | `1` để `vm-reset` không chặn `caramos-ota-check.service` (mục 9) |
| `VIRSH_URI` | `qemu:///system` | Kết nối libvirt |
| `TEST_RELEASE_FROM` | xem `Makefile` | Version ghi vào `/etc/caramos-release` trước khi `--check` |

### VM không nằm trên libvirt

`ship`, `sync`, `test`, `vm-logs`, `vm-ssh` chỉ cần SSH, nên vẫn dùng được với VirtualBox
port-forward hay máy thật:

```bash
REMOTE_HOST=127.0.0.1 REMOTE_PORT=2222 make ship
```

Các lệnh `vm-create`, `vm-snapshot`, `vm-reset`, `vm-shot`, `key`, `type`, `click`, `agent-exec` cần libvirt.
Với VirtualBox, tự chụp/khôi phục snapshot bằng `VBoxManage snapshot`.

---

## 8. Lỗi thường gặp

**`debian/ contains build output owned by another user`** khi `make ship`/`make build`
Thư mục build còn file của root, do lần build ISO (`sudo make build` ở gốc repo) để lại. Sửa một lần:

```bash
sudo chown -R "$(id -un):$(id -gn)" packages/caramos-ota packages/caramos-ota_*
```

Đừng chạy `sudo make ship`: root không có SSH key đã cài vào VM.

**`cannot find an IP for libvirt domain`**
VM chưa boot xong hoặc chưa có mạng. Xem `make vm-shot`. Kiểm tra mạng libvirt:
`virsh -c qemu:///system net-list` phải có `default` ở trạng thái `active`
(`virsh -c qemu:///system net-start default`).

**`SSH: not reachable with the host key`**
Chưa chạy `make vm-bootstrap` / `make vm-setup`, hoặc snapshot được chụp trước khi setup. Setup lại
rồi `FORCE=1 make vm-snapshot`.

**`passwordless sudo is not available`**
Chạy `make vm-setup`.

**`make vm-bootstrap` gõ thiếu chữ đầu dòng lệnh**
Terminal mở chậm hơn thời gian chờ. Bấm `Ctrl+C` trong VM (`./tools/vm-dev.sh key ctrl+c`) rồi chạy
lại với `VM_TERMINAL_WAIT=30`.

**apt báo `Release file ... is not valid yet`**
Đồng hồ VM bị lùi về lúc chụp snapshot. `make vm-reset` đã tự chỉnh giờ; nếu revert bằng
virt-manager thì chạy `./tools/vm-dev.sh ssh "sudo date -u -s @$(date -u +%s)"`.

**`make vm-shot` ra ảnh đen**
Desktop chưa lên xong, hoặc màn hình đã tắt vì snapshot chụp trước khi `vm-setup` tắt chế độ tắt màn
hình. Bấm một phím: `./tools/vm-dev.sh key shift`.

**`vm-dev.sh down` không tắt được VM live**
Khi tắt, live session dừng ở màn *Please remove the installation medium, then press ENTER*
(xem bằng `make vm-shot`). Nhấn `./tools/vm-dev.sh key enter` là VM tắt. VM cài vào đĩa không bị.

**Muốn xoá hẳn VM để làm lại**

```bash
virsh -c qemu:///system destroy caram1.0.16
virsh -c qemu:///system undefine caram1.0.16 --snapshots-metadata --remove-all-storage
```

---

## 9. Những điều cần biết về snapshot

- Snapshot nằm trong file qcow2 của VM trên máy bạn, không chia sẻ được qua git. Mỗi dev tự setup
  theo mục 3 (khoảng 15 phút nếu cài vào đĩa).
- Sau khi revert, đồng hồ VM nhảy tới giờ hiện tại nên `caramos-ota-check.timer` (daily, `Persistent=true`)
  đến hạn ngay. Lần cài `.deb` tiếp theo, postinst khởi động lại timer, timer chạy `caramos-ota --check`,
  và bước check tự cập nhật `caramos-ota` từ PPA đè lên bản đang test, đồng thời giữ lock OTA làm
  `make test` báo `Another CaramOS OTA operation is already running`. Vì vậy `make vm-reset` mask
  `caramos-ota-check.service` trong `/run` (mất sau lần revert/reboot sau) và dừng timer. Lệnh CLI
  `caramos-ota --check` vẫn chạy bình thường. Cần test chính timer/service thì chạy
  `VM_KEEP_OTA_TIMER=1 make vm-reset`.
- Snapshot kèm RAM phụ thuộc CPU host (`host-passthrough`). Đổi máy host thì chụp lại.
- VM dùng BIOS, không dùng UEFI, vì snapshot nội bộ của libvirt 10 không hỗ trợ VM UEFI đang chạy.
  Cần test UEFI/Secure Boot thì dùng VM khác.
- `vm-setup` có thay đổi VM so với bản cài nguyên gốc: thêm `openssh-server`, `qemu-guest-agent`,
  `rsync`, file sudoers, tắt khoá màn hình. Nếu migration của bạn đụng tới đúng mấy thứ này, hãy
  kiểm tra thêm trên một VM chưa qua `vm-setup`.
- Các tool SSH tới VM với `StrictHostKeyChecking=no` và không ghi `known_hosts`, vì VM test đổi host
  key sau mỗi lần cài lại. Chỉ trỏ `REMOTE_HOST` tới máy test.

---

## 10. File liên quan

| File | Vai trò |
| --- | --- |
| `tools/vm-dev.sh` | Toàn bộ lệnh `vm-*`, `sync`, `logs`, `shot`, `gui`, `key`, `type`, `click` |
| `tools/vm-common.sh` | Cấu hình + helper SSH dùng chung (tìm IP qua libvirt, `vm_ssh`, `vm_scp`) |
| `tools/ship-ota-to-vm.sh` | Build `.deb` và cài vào VM (`make ship`) |
| `tools/vm-run-ota-e2e.sh` | Script chạy **bên trong** VM (install, prepare-check, install-and-cli) |
| `tools/Makefile.vm` | Makefile được copy vào VM tại `/tmp/caramos-ota-e2e/` |
| `tools/vm-install-preseed.cfg` | Preseed cài CaramOS vào đĩa tự động trong VM test |
| `vm.local.env.example` | Mẫu cấu hình riêng của dev |
| `VM_TEST_CHECKLIST.md` | Checklist kiểm tra thủ công + flow live-boot cũ |
