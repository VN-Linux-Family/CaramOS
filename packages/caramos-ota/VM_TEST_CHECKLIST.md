# CaramOS OTA VM Test Checklist

Ghi chú nhanh để setup live boot VM và test `caramos-ota` sau khi remaster hoặc boot ISO mới.

Checklist này dùng cho VM test cục bộ. Các giá trị SSH bên dưới là ví dụ, không phải cấu hình bắt buộc của project.

## 0. Biến cấu hình trên máy host

Trên máy host, đặt thông tin SSH tới VM trước khi chạy các lệnh test:

```bash
export VM_SSH_HOST=127.0.0.1
export VM_SSH_PORT=2222
export VM_SSH_USER=<vm-user>
export KNOWN_HOSTS_FILE="${HOME}/.ssh/known_hosts"
```

Ví dụ live user có thể là `caram`, `mint`, hoặc user mặc định của ISO bạn đang test:

```bash
export VM_SSH_USER=caram
```

## 1. Chuẩn bị trong VM live boot

Mở terminal trong VM, cài SSH server:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

Nếu user live chưa có password hoặc cần đổi password để SSH:

```bash
passwd
```

Hoặc đổi password cho user cụ thể:

```bash
sudo passwd <vm-user>
```

Kiểm tra SSH service trong VM:

```bash
systemctl status ssh
```

## 2. Port forward từ host vào VM

Cấu hình port forward trong VirtualBox/QEMU theo dạng:

```text
Host: <host-address>:<host-port>
Guest: 22
```

Ví dụ VM local dùng port 2222:

```text
Host: 127.0.0.1:2222
Guest: 22
```

Từ máy host test SSH:

```bash
ssh -p "${VM_SSH_PORT}" "${VM_SSH_USER}@${VM_SSH_HOST}"
```

## 3. Ship OTA package từ host vào VM

Trên máy host, từ repository root:

```bash
cd packages/caramos-ota
REMOTE_USER="${VM_SSH_USER}" REMOTE_HOST="${VM_SSH_HOST}" REMOTE_PORT="${VM_SSH_PORT}" make ship
```

Nếu đang dùng đúng default local VM của `Makefile` (`REMOTE_USER=caram`, `REMOTE_HOST=127.0.0.1`, `REMOTE_PORT=2222`), có thể chạy ngắn hơn:

```bash
make ship
```

`make ship` sẽ:

- build `.deb` hiện tại
- SSH vào VM qua `REMOTE_HOST:REMOTE_PORT`
- purge bản `caramos-ota` cũ nếu có
- install bản mới vào VM
- copy testkit vào VM tại:

```text
/tmp/caramos-ota-e2e
```

> Lưu ý: `make ship` chỉ cài package/test artifacts. Nó chưa nhất thiết chạy migration test nếu chưa chạy lệnh E2E trong VM.

### Fix lỗi SSH host key changed

Nếu VM vừa rebuild/boot ISO mới, host key SSH có thể đổi. Khi chạy SSH hoặc `make ship` có thể gặp lỗi dạng:

```text
WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!
Host key for [127.0.0.1]:2222 has changed and you have requested strict checking.
Host key verification failed.
```

Xóa key cũ của port-forward VM trên máy host:

```bash
ssh-keygen -f "${KNOWN_HOSTS_FILE}" -R "[${VM_SSH_HOST}]:${VM_SSH_PORT}"
```

Sau đó thử SSH lại để nhận host key mới:

```bash
ssh -p "${VM_SSH_PORT}" "${VM_SSH_USER}@${VM_SSH_HOST}"
```

Khi SSH hỏi xác nhận fingerprint mới, nhập `yes`, rồi chạy lại:

```bash
REMOTE_USER="${VM_SSH_USER}" REMOTE_HOST="${VM_SSH_HOST}" REMOTE_PORT="${VM_SSH_PORT}" make ship
```

Nếu `known_hosts` bị hỏng (`not a valid known_hosts file`, `invalid line`), ưu tiên mở file và xóa dòng lỗi cùng các dòng tương ứng với host/port VM test. Chỉ reset toàn bộ file trên máy dev/test dùng một lần, sau khi backup:

```bash
cp "${KNOWN_HOSTS_FILE}" "${KNOWN_HOSTS_FILE}.bak"
: > "${KNOWN_HOSTS_FILE}"
chmod 600 "${KNOWN_HOSTS_FILE}"
```

> Không reset toàn bộ `known_hosts` trên máy có nhiều server quan trọng nếu chưa kiểm tra nội dung file.

## 4. Chạy test OTA trong VM qua SSH

SSH vào VM:

```bash
ssh -p "${VM_SSH_PORT}" "${VM_SSH_USER}@${VM_SSH_HOST}"
```

Vào testkit:

```bash
cd /tmp/caramos-ota-e2e
```

Chạy full default test:

```bash
make test
```

Hoặc chạy migration cụ thể, ví dụ `1.0.7 -> 1.0.8`:

```bash
sudo TEST_RELEASE_FROM=1.0.7 TEST_RELEASE_TARGET=1.0.8 ./vm-run-ota-e2e.sh install-and-cli
```

Ví dụ test `1.0.6 -> 1.0.7`:

```bash
sudo TEST_RELEASE_FROM=1.0.6 TEST_RELEASE_TARGET=1.0.7 ./vm-run-ota-e2e.sh install-and-cli
```

## 5. Test notifier GUI

Lệnh này nên chạy trong terminal của desktop VM, không phải SSH:

```bash
cd /tmp/caramos-ota-e2e
make test-notifier
```

## 6. Kiểm tra state OTA

Trong VM:

```bash
sudo caramos-ota status
```

Hoặc xem state file:

```bash
sudo cat /var/lib/caramos-ota/state.json
```

Expected sau khi test `1.0.8`:

```text
installed_release: 1.0.8
```

## 7. Kiểm tra UI sau migration 1.0.8

Sau migration `1.0.8`, kiểm tra:

- Panel có Software Manager được ghim.
- Thứ tự pinned apps nếu đủ package:

```text
Settings -> WPS Office -> Chrome -> Software Manager
```

- Nếu WPS/Chrome không tồn tại, migration sẽ tự bỏ qua `.desktop` bị thiếu.
- Desktop có icon Software Manager:

```text
~/Desktop/mintinstall.desktop
```

Nếu desktop icons bị mất trong live session, khôi phục nhanh:

```bash
gsettings set org.nemo.desktop show-desktop-icons true
nemo-desktop &
```

Nếu vẫn chưa hiện:

```bash
nemo -q
nemo-desktop &
```

## 8. Cài OTA từ GitHub/PPA bootstrap nếu cần

Nếu có bootstrap script public trên GitHub, command dự kiến sẽ là dạng:

```bash
curl -fsSL https://raw.githubusercontent.com/VN-Linux-Family/CaramOS/main/packages/caramos-ota/tools/install-ota.sh | sudo bash
```

> Cần xác nhận file `tools/install-ota.sh` có tồn tại/public trước khi dùng. Trong flow dev hiện tại, ưu tiên dùng `make ship` để test package local nhanh hơn.

## 9. Flow tóm tắt nhanh

Host:

```bash
cd packages/caramos-ota
REMOTE_USER="${VM_SSH_USER}" REMOTE_HOST="${VM_SSH_HOST}" REMOTE_PORT="${VM_SSH_PORT}" make ship
```

VM SSH:

```bash
cd /tmp/caramos-ota-e2e
sudo TEST_RELEASE_FROM=1.0.7 TEST_RELEASE_TARGET=1.0.8 ./vm-run-ota-e2e.sh install-and-cli
sudo caramos-ota status
```

VM desktop terminal nếu test GUI:

```bash
cd /tmp/caramos-ota-e2e
make test-notifier
```
