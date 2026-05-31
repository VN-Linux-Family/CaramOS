# CaramOS packages

Thư mục `packages/` chứa các Debian source package do CaramOS tự duy trì. Đây là lớp package riêng của distro, dùng để phân phối branding, cấu hình, công cụ hệ thống, metadata release và các bản vá mà upstream Ubuntu/Linux Mint không có.

> [!IMPORTANT]
> `caramos-ota` là package trung tâm. Nó không chỉ tự cập nhật chính nó, mà còn là bộ điều phối để tự động phát hiện và cập nhật các package CaramOS khác thông qua PPA và manifest OTA.

---

## 1. Mục đích của thư mục `packages/`

CaramOS là ISO remaster dựa trên Linux Mint/Ubuntu. Sau khi ISO đã phát hành, ta vẫn cần một cách để cập nhật các thành phần riêng của CaramOS mà không bắt user tải lại ISO. Thư mục này phục vụ mục tiêu đó.

Các package ở đây thường dùng để:

- Cài/cập nhật branding của CaramOS.
- Cài/cập nhật cấu hình hệ thống mặc định.
- Cài/cập nhật công cụ riêng của CaramOS.
- Cung cấp metadata để hệ thống biết đang ở release nào.
- Đẩy bản vá nhỏ qua PPA sau khi ISO đã phát hành.
- Kiểm thử pipeline build/upload PPA.

---

## 2. Nguyên lý làm việc tổng thể

```text
packages/
  ├── caramos-ota/          # bộ điều phối OTA chính
  └── package-khac/         # các package CaramOS khác

Contributor sửa package
  └── build .deb
      └── upload PPA ppa:vietnamlinuxfamily/caram-os
          └── cập nhật OTA manifest online
              └── máy người dùng chạy caramos-ota --check
                  ├── apt-get update thấy candidate version mới từ PPA
                  ├── caramos-ota tải/đọc manifest online
                  ├── caramos-ota quyết định package nào cần update
                  └── apt-get install package từ PPA khi user đồng ý
```

Điểm quan trọng:

- PPA là nơi chứa `.deb` thật sự.
- Manifest online là nơi khai báo policy update hiện tại.
- `caramos-ota` là bộ điều phối update.
- Manifest khai báo package CaramOS nào phải đạt version tối thiểu nào.
- Khi user hoặc systemd timer chạy `caramos-ota --check`, OTA lấy manifest mới, rồi so sánh version đã cài với version yêu cầu.
- Khi user đồng ý update, `caramos-ota` gọi APT để cài/nâng cấp các package đó.
- Các package khác không cần tự viết update logic riêng; chúng chỉ cần được đóng gói đúng, có trong PPA và được khai báo trong manifest.

Nói ngắn gọn: **package khác được cập nhật qua PPA, manifest online nói cần cập nhật gì, còn `caramos-ota` là thằng kiểm tra, quyết định và kích hoạt việc cập nhật đó.** Bản thân `caramos-ota` cũng là một component trong manifest, nên nếu có version mới trong PPA thì client cũ có thể tự phát hiện và tự update chính nó, miễn là schema manifest vẫn tương thích với client cũ.

> [!IMPORTANT]
> Nếu manifest chỉ nằm bên trong package `caramos-ota`, thì đúng là sẽ có vấn đề “con gà quả trứng”: muốn biết cần update gì thì phải update `caramos-ota` trước. Vì vậy mô hình đúng cho OTA lâu dài là manifest phải có bản online/trusted để máy đang chạy bản `caramos-ota` cũ vẫn phát hiện được update mới.

---

## 3. Vai trò của `caramos-ota`

`caramos-ota` là package quan trọng nhất trong `packages/`.

Nó chịu trách nhiệm:

1. Xác minh máy đang chạy đúng CaramOS.
2. Xác minh PPA/keyring CaramOS đã được cài từ ISO.
3. Chạy `apt-get update` để refresh metadata.
4. Tải manifest OTA online từ endpoint chính thức; nếu không tải được thì fallback sang manifest bundled nếu còn hợp lệ.
5. Kiểm tra các package CaramOS khác đã đạt version yêu cầu chưa.
6. Ghi state để CLI, systemd timer và desktop notifier dùng chung.
7. Hiển thị danh sách update cho user.
8. Cài update bằng APT khi user đồng ý.
9. Ghi transaction/log để debug và rollback best-effort.
10. Hiển thị desktop notifier cho user phổ thông.

Ví dụ: nếu sau này có package `caramos-branding`, `caramos-default-settings`, `caramos-wallpapers`, thì manifest của `caramos-ota` có thể khai báo:

```json
{
  "components": [
    {
      "package": "caramos-branding",
      "min_version": "1.0.3-0caramos1",
      "required": true,
      "description": "CaramOS branding assets"
    },
    {
      "package": "caramos-default-settings",
      "min_version": "1.0.2-0caramos1",
      "required": true,
      "description": "Default desktop/system settings"
    }
  ]
}
```

Khi đó `caramos-ota` sẽ tự phát hiện máy nào thiếu/chưa đủ version và đề xuất update các package này.

---

## 3.1 Manifest online và manifest bundled

Để OTA thật sự tự cập nhật được các package khác, manifest không nên chỉ nằm trong package `caramos-ota`.

Có 2 loại manifest:

| Loại manifest | Vị trí | Vai trò |
|---|---|---|
| Manifest online | Endpoint chính thức của CaramOS, ví dụ `https://caramos.vietnamlinuxfamily.net/ota/stable/noble/manifest.json` | Nguồn policy update mới nhất. Máy đang chạy `caramos-ota` cũ vẫn đọc được để biết cần update gì. |
| Manifest bundled | `packages/caramos-ota/usr/share/caramos-ota/manifest.json` và sau khi cài là `/usr/share/caramos-ota/manifest.json` | Fallback/offline baseline để CLI vẫn có schema mẫu và có thể hoạt động tối thiểu nếu endpoint tạm lỗi. |

Nguyên tắc:

- `caramos-ota --check` nên ưu tiên tải manifest online qua HTTPS.
- Nếu online manifest tải thành công và hợp lệ, dùng nó để quyết định update.
- Nếu endpoint lỗi, có thể fallback sang bundled manifest, nhưng fallback này có thể cũ.
- Manifest online chỉ chứa metadata package/version/release notes, không chứa script để chạy.
- Package binary vẫn phải đến từ PPA/APT, không tải `.deb` thủ công từ manifest.
- Manifest online cần có cơ chế trust rõ ràng. Tối thiểu là HTTPS trên domain chính thức; tốt hơn là ký manifest bằng key riêng và verify chữ ký trong `caramos-ota`.

Flow đúng:

```text
package mới hoặc version mới
  ├── upload .deb lên PPA
  └── cập nhật manifest online
      └── máy user chạy caramos-ota --check
          ├── tải manifest online
          ├── apt-get update
          ├── so installed/candidate với min_version
          └── báo update cho user
```

Bundled manifest vẫn có ích, nhưng không nên là nguồn duy nhất cho OTA lâu dài.

### 3.1.1 Cấu trúc URL manifest online

`caramos-ota` build URL manifest từ `CHANNEL` và `UBUNTU_CODENAME` trong `/etc/caramos-release`:

```text
https://caramos.vietnamlinuxfamily.net/ota/{channel}/{codename}/manifest.json
```

Ví dụ:

```text
https://caramos.vietnamlinuxfamily.net/ota/stable/noble/manifest.json
https://caramos.vietnamlinuxfamily.net/ota/beta/noble/manifest.json
https://caramos.vietnamlinuxfamily.net/ota/stable/oracular/manifest.json
```

Cấu trúc deploy trên server nên tương ứng:

```text
/ota/
├── stable/
│   ├── noble/
│   │   └── manifest.json
│   └── oracular/
│       └── manifest.json
└── beta/
    └── noble/
        └── manifest.json
```

### 3.1.2 Mẫu manifest online

Đây là mẫu manifest v1 để contributor copy khi tạo/cập nhật manifest online:

```json
{
  "schema": 1,
  "min_client_version": "1.0.2-0caramos1",
  "release": "1.0.3",
  "codename": "noble",
  "release_notes_vi": [
    "Cập nhật bộ OTA để hỗ trợ manifest online.",
    "Cập nhật branding/cấu hình CaramOS qua PPA."
  ],
  "release_notes_en": [
    "Update OTA tooling to support online manifests.",
    "Update CaramOS branding/settings through the PPA."
  ],
  "components": [
    {
      "package": "caramos-ota",
      "required": true,
      "min_version": "1.0.3-0caramos1",
      "description": "CaramOS OTA updater and desktop notifier"
    },
    {
      "package": "caramos-wallpapers",
      "required": true,
      "min_version": "1.0.0-0caramos1",
      "description": "CaramOS default wallpapers"
    },
    {
      "package": "caramos-default-settings",
      "required": true,
      "min_version": "1.0.0-0caramos1",
      "description": "CaramOS default system and desktop settings"
    }
  ]
}
```

Quy tắc khi sửa manifest:

- `schema` hiện tại giữ là `1` để client cũ còn đọc được.
- `codename` phải khớp với thư mục URL và `/etc/caramos-release`.
- `min_client_version` là version client OTA tối thiểu mà manifest này hỗ trợ.
- `components[].package` phải là tên Debian package hợp lệ.
- `components[].min_version` phải tồn tại trong PPA trước khi publish manifest.
- Luôn khai báo `caramos-ota` trong manifest để OTA có thể tự update.
- Không đưa URL tải `.deb`, shell script hoặc command vào manifest.
- Nếu đổi breaking schema, phải dùng bridge rollout trước khi publish schema mới.

---

## 3.2 Khi chính `caramos-ota` cần được cập nhật

`caramos-ota` cũng phải được xem là một package CaramOS bình thường và được khai báo trong manifest online:

```json
{
  "package": "caramos-ota",
  "min_version": "1.0.3-0caramos1",
  "required": true,
  "description": "CaramOS OTA updater"
}
```

Khi đó máy đang chạy `caramos-ota` cũ sẽ làm được luồng này:

```text
caramos-ota cũ --check
  ├── tải manifest online bằng schema nó hiểu được
  ├── thấy component caramos-ota cần >= 1.0.3-0caramos1
  ├── apt-cache thấy PPA có candidate 1.0.3-0caramos1
  └── khi user đồng ý: apt-get install caramos-ota
      └── caramos-ota mới được cài lên máy
```

Vì vậy update `caramos-ota` bình thường không phải vấn đề, miễn là manifest online vẫn giữ schema tương thích với các client cũ đang tồn tại ngoài thực tế.

### 3.2.1 Quy tắc không phá client cũ

Manifest online là hợp đồng giữa server và mọi bản `caramos-ota` đã phát hành. Không được đổi đột ngột theo kiểu client cũ đọc vào là crash hoặc không hiểu gì.

Quy tắc:

- Giữ `schema: 1` tương thích lâu nhất có thể.
- Field mới phải optional.
- Không đổi nghĩa field cũ.
- Không xóa field mà client cũ đang cần.
- Nếu cần schema mới, manifest nên có `min_client_version` hoặc publish song song endpoint cũ/mới.
- Client cũ gặp field lạ phải ignore, không crash.

### 3.2.2 Nếu cần sửa logic OTA nhưng vẫn tương thích

Ví dụ sửa bug UI, sửa normalize state, sửa cách gọi APT nhưng manifest schema không đổi.

Flow:

```text
1. Sửa code caramos-ota.
2. Build/upload caramos-ota version mới lên PPA.
3. Cập nhật manifest online: component caramos-ota min_version = version mới.
4. Client cũ đọc manifest schema cũ, thấy cần update caramos-ota.
5. Client cũ dùng APT cài caramos-ota mới.
```

Đây là flow tự update bình thường.

### 3.2.3 Nếu cần đổi breaking logic/schema

Nếu bản `caramos-ota` cũ chưa hiểu manifest mới, không được publish manifest mới ngay. Phải rollout 2 pha.

```text
Pha 1: phát hành bridge updater
  ├── caramos-ota mới vẫn hiểu schema cũ
  ├── thêm code hiểu schema mới
  ├── upload PPA
  └── manifest schema cũ yêu cầu update caramos-ota lên bản bridge

Pha 2: sau khi phần lớn máy đã lên bridge
  ├── publish manifest schema mới
  ├── bridge client đọc được schema mới
  └── các update sau dùng logic mới
```

Nếu bắt buộc hỗ trợ máy quá cũ, giữ endpoint manifest v1 song song với endpoint manifest v2:

```text
/stable/noble/manifest.v1.json   # cho client cũ
/stable/noble/manifest.v2.json   # cho client mới
```

### 3.2.4 Nếu `caramos-ota` cũ bị lỗi nặng không tải được manifest

Đây là tình huống xấu nhất. Cần có escape hatch ngoài OTA:

- User/support chạy `sudo apt update && sudo apt install caramos-ota` thủ công.
- ISO mới ship sẵn bản `caramos-ota` đã sửa.
- Nếu có desktop/software updater của Mint/Ubuntu, nó vẫn có thể thấy package mới từ PPA nếu PPA đã cấu hình.

Vì vậy rule quan trọng: phần fetch manifest + parse schema cơ bản của `caramos-ota` phải cực kỳ ổn định, ít dependency, fail-safe và backward compatible.

---

## 4. Cấu trúc thư mục `packages/`

```text
packages/
├── README.md
├── caramos-ota/
│   ├── README.md
│   ├── README_EN.md
│   ├── IMPLEMENTATION_PLAN.md
│   ├── debian/
│   ├── etc/
│   ├── lib/
│   └── usr/
├── caram-os-demo/
│   ├── debian/
│   └── ...
├── caramos-ota_*.deb
├── caramos-ota_*.buildinfo
└── caramos-ota_*.changes
```

### 4.1 `README.md`

File bạn đang đọc. Đây là tài liệu cấp `packages/`, giải thích cách các package trong thư mục này phối hợp với nhau.

### 4.2 `caramos-ota/`

Source Debian package của hệ thống OTA. Đây là nơi contributor cần đọc kỹ nhất nếu muốn hiểu cơ chế update của CaramOS.

Tài liệu chi tiết:

- [caramos-ota/README.md](./caramos-ota/README.md)

### 4.3 `caram-os-demo/`

Package demo dùng để kiểm thử PPA/build pipeline. Không phải package vận hành chính của distro.

### 4.4 File `.deb`, `.buildinfo`, `.changes`

Đây là output sau khi chạy `dpkg-buildpackage`. Thông thường không nên commit các file này nếu không có lý do release rõ ràng.

---

## 5. Cấu trúc chuẩn của một package trong `packages/`

Một package Debian trong thư mục này nên có dạng:

```text
package-name/
├── README.md                  # giải thích package làm gì và cách bảo trì
├── debian/
│   ├── changelog              # version/release notes Debian
│   ├── control                # metadata + dependencies
│   ├── install                # map file source vào filesystem khi cài
│   ├── rules                  # debhelper entrypoint
│   └── source/
│       └── format
├── etc/                       # file cài vào /etc nếu có
├── lib/                       # systemd unit hoặc file /lib nếu có
└── usr/                       # command, Python package, data, icon, app desktop...
```

Không phải package nào cũng cần đủ `etc/`, `lib/`, `usr/`. Nhưng nếu có logic phức tạp, cần tách module rõ ràng, không nhét toàn bộ vào một script dài trong `/usr/bin`.

---

## 6. Package hiện có

| Package | Vai trò | Trạng thái | Tài liệu |
|---|---|---|---|
| `caramos-ota` | Bộ điều phối OTA chính. Tự check/cập nhật các package CaramOS khác dựa trên manifest và PPA. | Package vận hành thật | [caramos-ota/README.md](./caramos-ota/README.md) |
| `caram-os-demo` | Package demo để xác minh PPA/build/install flow. | Demo/testing | [caram-os-demo](./caram-os-demo/) |

---

## 7. Quy trình thêm package CaramOS mới để OTA cập nhật được

Giả sử muốn thêm package mới `caramos-wallpapers` và để OTA tự cập nhật nó về sau.

### Bước 1: Tạo source package

```text
packages/caramos-wallpapers/
├── README.md
├── debian/
│   ├── changelog
│   ├── control
│   ├── install
│   ├── rules
│   └── source/format
└── usr/share/backgrounds/caramos/
```

### Bước 2: Build package

```bash
cd packages/caramos-wallpapers
dpkg-buildpackage -us -uc -b
```

### Bước 3: Upload package lên PPA

Package phải có trong PPA `ppa:vietnamlinuxfamily/caram-os` để máy user có candidate version.

### Bước 4: Cập nhật manifest OTA online

Cập nhật manifest trên endpoint chính thức của CaramOS, ví dụ:

```text
https://caramos.vietnamlinuxfamily.net/ota/stable/noble/manifest.json
```

Thêm component:

```json
{
  "package": "caramos-wallpapers",
  "min_version": "1.0.0-0caramos1",
  "required": true,
  "description": "CaramOS default wallpapers"
}
```

Nếu repository vẫn giữ bundled manifest trong `caramos-ota`, có thể cập nhật thêm file này để làm baseline/fallback:

```text
packages/caramos-ota/usr/share/caramos-ota/manifest.json
```

Nhưng contributor cần hiểu: **bundled manifest không đủ để máy đang chạy bản `caramos-ota` cũ biết package mới**, trừ khi bản `caramos-ota` cũ cũng biết tải manifest online.

### Bước 5: Release package liên quan

- Nếu chỉ thêm package mới và manifest online đã được cập nhật, không nhất thiết phải release `caramos-ota` chỉ để đổi bundled manifest.
- Nếu thay đổi code/schema/logic OTA, phải build/upload `caramos-ota` mới.
- Nếu muốn bundled manifest làm fallback mới hơn, cũng có thể release `caramos-ota` mới, nhưng đây không được là cơ chế duy nhất.


### Bước 6: User nhận update

Trên máy user:

```text
systemd timer hoặc user chạy caramos-ota --check
  └── tải manifest online mới
      └── thấy caramos-wallpapers chưa đạt min_version
          └── ghi available_update vào state
              └── notifier hiện popup
                  └── user bấm cập nhật
                      └── apt-get install caramos-wallpapers từ PPA
```

---

## 8. Quy trình sửa package đã có

1. Sửa source package tương ứng trong `packages/<name>/`.
2. Tăng version trong `debian/changelog`.
3. Build `.deb`.
4. Test cài local trong VM.
5. Upload PPA.
6. Nếu package đó cần được OTA đảm bảo version tối thiểu, cập nhật manifest online.
7. Nếu đổi schema/logic OTA hoặc muốn cập nhật bundled fallback, build/upload `caramos-ota`.
8. Test từ máy đang ở version cũ.

---

## 9. Compile, build và test cho contributor

Contributor không nên chỉ chạy `dpkg-buildpackage` rồi coi như xong. Với các package trong `packages/`, đặc biệt là `caramos-ota`, cần test theo nhiều lớp: syntax, package build, install local, manifest, OTA check, notifier và update path.

### 9.1 Chuẩn bị môi trường build

Khuyến nghị test trong VM CaramOS/Linux Mint 22/Ubuntu 24.04 `noble`, vì package này phụ thuộc APT, dpkg, systemd, GTK và layout filesystem Debian.

Cài tool build cơ bản:

```bash
sudo apt update
sudo apt install --yes build-essential devscripts debhelper dh-python python3 python3-gi gir1.2-gtk-3.0
```

Nếu chỉ kiểm tra nhanh source Python thì không cần cài toàn bộ GUI dependency, nhưng để test notifier thì cần `python3-gi` và GTK3.

### 9.2 Compile Python source

Chạy từ thư mục package:

```bash
cd packages/caramos-ota
python3 -m py_compile \
  usr/bin/caramos-ota \
  usr/bin/caramos-ota-notifier \
  usr/lib/python3/dist-packages/caramos_ota/*.py \
  usr/lib/python3/dist-packages/caramos_ota_notifier/*.py
```

Mục tiêu:

- Bắt lỗi syntax/import cơ bản.
- Đảm bảo entrypoint `/usr/bin` vẫn import đúng package Python.
- Đảm bảo tách module `caramos_ota` và `caramos_ota_notifier` không bị thiếu file.

### 9.3 Validate manifest JSON bundled

Manifest bundled là fallback, nên phải luôn parse được:

```bash
cd packages/caramos-ota
python3 -m json.tool usr/share/caramos-ota/manifest.json >/dev/null
```

Kiểm tra nhanh các field bắt buộc:

```bash
cd packages/caramos-ota
PYTHONPATH=usr/lib/python3/dist-packages python3 - <<'PY'
from caramos_ota.manifest import load_bundled_manifest

manifest = load_bundled_manifest()
assert manifest["schema"] == 1
assert manifest["codename"]
assert manifest["components"]
for component in manifest["components"]:
    assert component["package"]
    assert component["min_version"]
print("bundled manifest OK")
PY
```

### 9.4 Test build Debian package

Build binary package:

```bash
cd packages/caramos-ota
dpkg-buildpackage -us -uc -b
```

Output nằm ở thư mục cha `packages/`:

```text
caramos-ota_1.0.2-0caramos1_all.deb
caramos-ota_1.0.2-0caramos1_amd64.buildinfo
caramos-ota_1.0.2-0caramos1_amd64.changes
```

Nếu build fail, đọc log ngay tại terminal trước. Không sửa bằng cách bỏ dependency bừa khỏi `debian/control`; phải hiểu file nào cần dependency đó.

### 9.5 Kiểm tra nội dung `.deb` trước khi cài

Từ thư mục `packages/`:

```bash
dpkg-deb -c caramos-ota_1.0.2-0caramos1_all.deb
```

Cần thấy các nhóm file chính:

```text
/usr/bin/caramos-ota
/usr/bin/caramos-ota-notifier
/usr/lib/python3/dist-packages/caramos_ota/
/usr/lib/python3/dist-packages/caramos_ota_notifier/
/usr/share/caramos-ota/manifest.json
/lib/systemd/system/caramos-ota-check.service
/lib/systemd/system/caramos-ota-check.timer
/etc/xdg/autostart/caramos-ota-notifier.desktop
```

### 9.6 Test install local trong VM

Cài package vừa build:

```bash
cd packages
sudo apt install ./caramos-ota_1.0.2-0caramos1_all.deb
```

Kiểm tra command tồn tại:

```bash
command -v caramos-ota
command -v caramos-ota-notifier
caramos-ota --version
```

Kiểm tra systemd unit:

```bash
systemctl list-unit-files 'caramos-ota*'
systemctl status caramos-ota-check.timer --no-pager
```

### 9.7 Test CLI không phá hệ thống

Các lệnh dưới đây nên chạy trong VM/snapshot, không chạy trực tiếp trên máy làm việc nếu chưa chắc repo/PPA đã đúng.

```bash
sudo caramos-ota --status
sudo caramos-ota --check
sudo caramos-ota --dry-run
```

Kỳ vọng:

- Nếu là CaramOS đúng chuẩn: detect được `/etc/caramos-release`, repo/keyring, manifest.
- Nếu không phải CaramOS: fail closed với exit code `3`, không chạy APT install.
- `--check` chỉ ghi state, không cài package.
- `--dry-run` chỉ in danh sách update, không cài package.

State sau khi check:

```bash
sudo python3 -m json.tool /var/lib/caramos-ota/state.json
```

Log:

```bash
sudo tail -n 100 /var/log/caramos-ota/$(date +%F).log
```

### 9.8 Test manifest online

Với URL runtime hiện tại, `caramos-ota` sẽ build endpoint theo công thức:

```text
https://caramos.vietnamlinuxfamily.net/ota/{channel}/{codename}/manifest.json
```

Ví dụ stable/noble:

```bash
python3 - <<'PY'
from urllib.request import urlopen
url = "https://caramos.vietnamlinuxfamily.net/ota/stable/noble/manifest.json"
with urlopen(url, timeout=20) as response:
    print(response.status, response.headers.get("Content-Type"))
    print(response.read(200).decode("utf-8", errors="replace"))
PY
```

Nếu endpoint chưa deploy, `caramos-ota` phải log warning và fallback sang bundled manifest, không crash.

### 9.9 Test manifest offline/fallback

Có. Đây là test bắt buộc vì OTA không được phụ thuộc 100% vào server manifest. Khi mạng lỗi, DNS lỗi, TLS lỗi hoặc endpoint chưa deploy, client phải dùng bundled manifest ở `/usr/share/caramos-ota/manifest.json` và không được crash.

Test trực tiếp bằng source local, không cần root. Lưu ý: khi chạy từ source tree, phải trỏ `MANIFEST_FILE` về file local; nếu không Python sẽ đọc `/usr/share/caramos-ota/manifest.json` của package đã cài trên máy test.

```bash
cd packages/caramos-ota
PYTHONPATH=usr/lib/python3/dist-packages python3 - <<'PY'
from pathlib import Path

import caramos_ota.manifest as manifest_module
from caramos_ota.models import ReleaseInfo

manifest_module.MANIFEST_FILE = Path("usr/share/caramos-ota/manifest.json")
raw = manifest_module.load_bundled_manifest()
manifest = manifest_module.validate_manifest(
    raw,
    ReleaseInfo(
        name="CaramOS",
        version="1.0.2",
        codename="noble",
        channel="stable",
    ),
    "offline-test",
)

assert manifest.source == "offline-test"
assert manifest.codename == "noble"
assert manifest.components
assert any(component.package == "caramos-ota" for component in manifest.components)
print("offline bundled manifest fallback OK")
PY
```

Test fallback khi online manifest lỗi bằng cách tạm override base URL trong Python process:

```bash
cd packages/caramos-ota
PYTHONPATH=usr/lib/python3/dist-packages python3 - <<'PY'
from pathlib import Path

import caramos_ota.manifest as manifest_module
from caramos_ota.models import ReleaseInfo

manifest_module.MANIFEST_BASE_URL = "https://invalid.invalid/ota"
manifest_module.MANIFEST_FILE = Path("usr/share/caramos-ota/manifest.json")
manifest = manifest_module.parse_manifest(
    ReleaseInfo(
        name="CaramOS",
        version="1.0.2",
        codename="noble",
        channel="stable",
    )
)

assert manifest.source.endswith("/usr/share/caramos-ota/manifest.json")
assert manifest.components
print("online failure -> bundled fallback OK")
PY
```

Kỳ vọng:

- Online URL lỗi không làm process crash.
- Log có warning kiểu `Online manifest unavailable, using bundled manifest`.
- Manifest fallback vẫn validate schema/codename/component.
- Component `caramos-ota` vẫn có trong fallback để client còn tự update nếu bundled manifest đủ mới.

### 9.10 Test notifier desktop

Notifier chỉ nên chạy trong desktop session có `DISPLAY` hoặc `WAYLAND_DISPLAY`.

Kiểm tra import/smoke test:

```bash
cd packages/caramos-ota
PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-notifier
```

Kỳ vọng:

- Không có desktop session: thoát im lặng hoặc không hiện dialog.
- Có `available_update` trong state: hiện dialog GTK.
- Bấm cập nhật: notifier gọi `pkexec /usr/bin/caramos-ota --upgrade --yes`, không tự parse manifest hay tự chạy APT.

### 9.11 Test update path thật

Dùng VM snapshot:

```text
1. Cài bản caramos-ota cũ.
2. Đảm bảo PPA đang trỏ đúng.
3. Upload/cài local repo có caramos-ota mới.
4. Cập nhật manifest online yêu cầu min_version mới.
5. Chạy sudo caramos-ota --check.
6. Chạy sudo caramos-ota --dry-run.
7. Chạy sudo caramos-ota --upgrade.
8. Kiểm tra caramos-ota --version đã lên version mới.
```

Nếu thay đổi schema manifest, phải test bridge rollout:

```text
client cũ -> manifest schema cũ -> update lên bridge -> manifest schema mới -> update tiếp
```

### 9.12 Test package khác được OTA quản lý

Với package mới, ví dụ `caramos-wallpapers`:

```text
1. Build caramos-wallpapers .deb.
2. Cài VM đang thiếu hoặc có version cũ.
3. Đưa version mới vào PPA/local repo.
4. Thêm component vào manifest online.
5. Chạy sudo caramos-ota --check.
6. Xác nhận package xuất hiện trong available_update.
7. Chạy sudo caramos-ota --dry-run.
8. Chạy sudo caramos-ota --upgrade.
9. Kiểm tra dpkg-query -W caramos-wallpapers.
```

### 9.13 Cleanup trước khi commit

Không commit output build và cache Python:

```bash
cd packages/caramos-ota
rm -rf usr/lib/python3/dist-packages/caramos_ota/__pycache__ \
       usr/lib/python3/dist-packages/caramos_ota_notifier/__pycache__
```

Các file thường không nên commit nếu chỉ là output local:

```text
packages/*.deb
packages/*.buildinfo
packages/*.changes
packages/*.dsc
packages/*.tar.*
```

### 9.14 Checklist tối thiểu trước khi mở PR

- [ ] `python3 -m py_compile` pass cho CLI và notifier.
- [ ] `python3 -m json.tool usr/share/caramos-ota/manifest.json` pass.
- [ ] `dpkg-buildpackage -us -uc -b` pass.
- [ ] `.deb` chứa đúng file bằng `dpkg-deb -c`.
- [ ] Cài local `.deb` trong VM pass.
- [ ] `sudo caramos-ota --status` pass hoặc fail closed đúng nếu không phải CaramOS.
- [ ] `sudo caramos-ota --check` không tự cài package.
- [ ] `sudo caramos-ota --dry-run` không tự cài package.
- [ ] Test manifest offline/fallback pass khi online endpoint lỗi.
- [ ] Manifest online đã cập nhật nếu package cần OTA quản lý.
- [ ] Nếu sửa `caramos-ota`, manifest online có component `caramos-ota` với `min_version` mới.
- [ ] Nếu đổi schema/logic breaking, đã có kế hoạch bridge rollout.
- [ ] Không commit output build/cache ngoài ý muốn.

---

## 10. Quy ước version

Package CaramOS nên dùng suffix rõ ràng, ví dụ:

```text
1.0.2-0caramos1
```

Ý nghĩa gợi ý:

- `1.0.2`: version upstream/nội bộ của package.
- `0caramos1`: revision dành cho CaramOS packaging/PPA.

Khi upload PPA, version mới phải lớn hơn version đã có theo Debian version comparison.

---

## 11. Quy ước dependency

- Ưu tiên dependency có sẵn trong Ubuntu 24.04/Mint 22.
- Không thêm dependency nặng nếu chỉ để làm việc nhỏ.
- Nếu package chỉ là data/config, giữ dependency tối thiểu.
- Nếu package có Python code, tránh dependency ngoài stdlib khi không thật sự cần.
- Nếu thêm GUI dependency, cân nhắc có cần tách package GUI riêng không.

---

## 12. Quy ước tài liệu cho mỗi package

Mỗi package vận hành thật nên có `README.md` riêng, ít nhất giải thích:

- Package làm gì.
- Nó được cài vào path nào.
- Nó có service/timer/autostart không.
- Nó có file runtime không.
- Nó tương tác với `caramos-ota` thế nào.
- Cách build/test.
- Cách release/update qua PPA.
- Rủi ro bảo mật hoặc rủi ro phá update path.

`caramos-ota` đã có tài liệu chi tiết tại:

- [caramos-ota/README.md](./caramos-ota/README.md)

---

## 13. Nguyên tắc an toàn khi sửa package

- Không tự tải và chạy script từ Internet.
- Không tự thêm repository/keyring trong package runtime nếu không có thiết kế rõ.
- Không ghi đè config người dùng nếu không cần thiết.
- Không để postinst làm việc nguy hiểm hoặc không idempotent.
- Không cho systemd timer tự động cài package nếu user chưa đồng ý.
- Không nhét logic dài vào `/usr/bin`; hãy tách thành module/package.
- Không để GUI quyết định logic update; GUI chỉ hiển thị và gọi CLI.
- Không phá compatibility với máy đã cài bản ISO cũ.

---

## 14. Checklist trước khi merge package mới/sửa package

- [ ] Package có `debian/changelog` đúng version.
- [ ] `dpkg-buildpackage -us -uc -b` pass.
- [ ] Cài local `.deb` trong VM pass.
- [ ] File được cài đúng path theo `debian/install`.
- [ ] Dependency trong `debian/control` hợp lý.
- [ ] Nếu package cần OTA quản lý, manifest online đã cập nhật.
- [ ] Nếu package đó là `caramos-ota`, manifest online đã khai báo `caramos-ota` như một component cần `min_version` mới.
- [ ] Nếu manifest schema/logic OTA đổi, đã có kế hoạch bridge/two-phase rollout, không làm client cũ gãy.
- [ ] Update path từ version cũ đã test.
- [ ] Không commit nhầm `.deb`, `.buildinfo`, `.changes`, `__pycache__`.

---

## 15. Tóm tắt ngắn

```text
packages/
  = nơi chứa Debian source package riêng của CaramOS

caramos-ota/
  = bộ điều phối OTA chính
  = tự cập nhật chính nó nếu được khai báo trong manifest online
  = đọc manifest online, fallback bundled nếu cần
  = check/cập nhật các package CaramOS khác qua PPA
  = ghi state/log/transaction
  = cung cấp desktop notifier

package khác/
  = chỉ cần đóng gói đúng, upload PPA, và được khai báo trong manifest nếu muốn OTA quản lý
```

Nếu contributor muốn thêm thứ gì đó có thể cập nhật sau khi ISO phát hành, hãy nghĩ theo luồng:

```text
package mới -> upload PPA -> cập nhật manifest online -> user nhận update qua OTA
```

Nếu thay đổi chính `caramos-ota` nhưng vẫn giữ schema tương thích, hãy upload `caramos-ota` mới lên PPA rồi khai báo chính `caramos-ota` trong manifest online với `min_version` mới. Nếu thay đổi breaking schema/logic, phải rollout 2 pha bằng bridge updater.
