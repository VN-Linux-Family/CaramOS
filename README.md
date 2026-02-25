<p align="center">
  <img src="assets/CaramOS_logo.png" alt="CaramOS Logo" width="250">
</p>

<h1 align="center">CaramOS</h1>

<p align="center">
  <strong>Sweet & Simple Linux — Hệ điều hành Linux ngọt ngào cho người Việt</strong>
</p>

<p align="center">
  <em>Caram = Carambola = Trái khế — 5 cánh như ngôi sao trên quốc kỳ, gắn liền với tuổi thơ người Việt</em>
</p>

<p align="center">
  <a href="README_EN.md">English</a> · <a href="https://vietnamlinuxfamily.net">VNLF</a> · <a href="https://caramos.vietnamlinuxfamily.net">Website</a>
</p>

<p align="center">
  Phát triển bởi: <a href="https://www.facebook.com/groups/vietnamlinuxcommunity">VNLF</a> · <a href="https://www.facebook.com/mrd.900s/">MRD</a> · <a href="https://www.facebook.com/tam.nguyet.that">Kỳ Nguyễn</a>
</p>

---

### CaramOS là gì?

**CaramOS** là bản phân phối Linux dựa trên [Linux Mint](https://linuxmint.com/), được thiết kế đặc biệt cho **người dùng Việt Nam**. Mục tiêu của CaramOS là phổ thông hoá Linux — giúp mọi người chuyển từ Windows sang Linux một cách dễ dàng, miễn phí, và hợp pháp.

> Sứ mệnh của CaramOS là **phổ thông hoá Linux** — mọi thứ được làm đơn giản nhất có thể, phần mềm cài sẵn và sẵn sàng sử dụng, đồng thời cố gắng mang những ứng dụng quen thuộc từ Windows đến cho người dùng.

### Tính năng nổi bật

| Tính năng | Mô tả |
|---|---|
| **Giao diện Chrome OS** | Sạch sẽ, hiện đại, icon tròn — đẹp ngay từ lần đầu |
| **Việt hoá 100%** | Tiếng Việt mặc định, bộ gõ fcitx5 cài sẵn, font Việt đẹp |
| **Google Chrome** | Trình duyệt quen thuộc, cài sẵn |
| **Cập nhật an toàn** | mintupdate phân loại mức độ rủi ro — không bao giờ tự update hỏng máy |
| **Backup 1 click** | Timeshift tạo snapshot — hỏng máy thì khôi phục trong 2 phút |
| **Driver tự động** | Tự phát hiện và cài driver WiFi, GPU (NVIDIA/AMD/Intel) |
| **Chia sẻ file LAN** | Warpinator — gửi file giữa các máy như AirDrop |
| **Nhẹ và nhanh** | Chạy mượt trên máy cấu hình thấp |

### Ảnh chụp màn hình

> *Sẽ cập nhật khi phát hành bản beta đầu tiên*

### Cài đặt

#### Bước 1: Tải ISO

```bash
# Sẽ cập nhật link tải khi phát hành
# CaramOS.iso          — Intel/AMD (nhẹ)
# CaramOS-nvidia.iso   — Có sẵn driver NVIDIA
```

#### Bước 2: Ghi ra USB

```bash
# Linux / macOS
sudo dd if=CaramOS.iso of=/dev/sdX bs=4M status=progress

# Hoặc dùng Balena Etcher (GUI, mọi hệ điều hành)
# https://etcher.balena.io
```

#### Bước 3: Khởi động từ USB & cài đặt

1. Khởi động lại máy, vào BIOS/UEFI (nhấn F2/F12/Del)
2. Chọn boot từ USB
3. Chọn **"Cài đặt CaramOS"**
4. Làm theo hướng dẫn trên màn hình (hoàn toàn tiếng Việt)

<!-- Caram Center — Phase 2 -->

### Công nghệ sử dụng

| Thành phần | Công nghệ |
|---|---|
| **Base** | [Linux Mint 22](https://linuxmint.com/) (Ubuntu 24.04 LTS) |
| **Desktop** | [Cinnamon](https://github.com/linuxmint/cinnamon) |
| **Login** | [SDDM](https://github.com/sddm/sddm) |
| **Build** | ISO Remaster — `sudo ./build.sh` → ISO |
| **Theme** | [ChromeOS-theme](https://github.com/vinceliuice/ChromeOS-theme) + [Tela Circle](https://github.com/vinceliuice/Tela-circle-icon-theme) + [Bibata](https://github.com/ful1e5/Bibata_Cursor) |
| **Font** | [Be Vietnam Pro](https://fonts.google.com/specimen/Be+Vietnam+Pro) |
| **Browser** | Google Chrome (cài sẵn) |
| **Input** | [fcitx5](https://fcitx-im.org/) — bộ gõ tiếng Việt |
| **Apps** | VLC, GIMP, LibreOffice, Flameshot, Nemo, xed |
| **System** | TLP, Timeshift, Warpinator, Flatpak, DKMS |

> 📖 Chi tiết kiến trúc, cấu trúc thư mục, và cách build → [CONTRIBUTING.md](CONTRIBUTING.md)

### Build ISO

```bash
sudo apt install squashfs-tools xorriso rsync wget
git clone https://github.com/VN-Linux-Family/CaramOS.git
cd CaramOS && sudo ./build.sh    # Tự tải Mint ISO + remaster + ra CaramOS.iso
```

> 📖 Hướng dẫn đầy đủ (ghi USB, test VM, build .deb) → [CONTRIBUTING.md](CONTRIBUTING.md#build-iso)

### Đóng góp

Chúng tôi hoan nghênh mọi đóng góp! Xem [CONTRIBUTING.md](CONTRIBUTING.md) để biết:
- Kiến trúc dự án & cấu trúc thư mục
- Cách build ISO & test
- Quy trình đóng góp code
- Tiêu chuẩn commit & code

### Giấy phép

CaramOS là phần mềm **mã nguồn mở** theo giấy phép [GPL-3.0](LICENSE).

### Cảm ơn

- [Linux Mint](https://linuxmint.com/) — Base distro tuyệt vời
- [VNLF (Vietnam Linux Family)](https://vietnamlinuxfamily.net) — Cộng đồng Linux Việt Nam
- [vinceliuice](https://github.com/vinceliuice) — ChromeOS-theme, Tela Circle icons
- [Bottles](https://usebottles.com/) — Chạy app Windows trên Linux
- [Lutris](https://lutris.net/) — Chạy game Windows trên Linux

---

<p align="center">
  <strong>CaramOS</strong> — Sweet & Simple Linux<br>
  Made with love by <a href="https://vietnamlinuxfamily.net">Vietnam Linux Family</a>
</p>
