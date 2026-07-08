# CaramOS release/version bump tracker

Tài liệu này ghi lại các vị trí cần kiểm tra sau mỗi lần bump release CaramOS/OTA.

> Quy ước: không phải mọi dòng `1.0.1` đều cần đổi. `1.0.1` vẫn là base ISO/Open Beta và là điểm bắt đầu migration chain.

## Khi release OTA version mới

Ví dụ release mới là `1.0.12`, version trước là `1.0.11`.

### 1. Source version ISO/tag

| File | Cần đổi/kiểm tra |
|---|---|
| [scripts/config.sh](../scripts/config.sh) | bump `CARAMOS_VERSION_PATCH` hoặc major/minor tương ứng |
| [scripts/config.sh](../scripts/config.sh) | cập nhật comment ví dụ tag `vX.Y.Z` nếu có |

Giữ nguyên:

| File | Version | Lý do giữ |
|---|---|---|
| [scripts/config.sh](../scripts/config.sh) | `CARAMOS_MIGRATION_BASE_VERSION="1.0.1"` | base để build ISO chạy đủ migration chain từ đầu |
| [install-caramos-ota.sh](../install-caramos-ota.sh) | fallback `1.0.1` | bootstrap cho máy từ ISO 1.0.1 trước khi OTA nâng lên latest |
| migration cũ `v1_0_*` | version lịch sử | không sửa migration đã phát hành, trừ khi có lý do migration-fix rõ ràng |

### 2. Tài liệu chính

| File | Cần đổi/kiểm tra |
|---|---|
| [README.md](../README.md) | chỉ đổi dòng `> **Phiên bản hiện tại:** \`X.Y.Z\` — **Open Beta**.` và lệnh `sudo dd if=CaramOS-X.Y.Z-cinnamon-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync` |
| [README_EN.md](../README_EN.md) | chỉ đổi dòng `> **Current version:** \`X.Y.Z\` — **Open Beta**.` nếu bản tiếng Anh có current version |
| [packages/README.md](../packages/README.md) | release hiện tại, migration chain, command upload PPA, `CARAMOS_VERSION` |
| [packages/caramos-ota/README.md](../packages/caramos-ota/README.md) | cập nhật các dòng trong mục release workflow theo version mới; xem checklist chi tiết bên dưới |
| [packages/caramos-ota/README_EN.md](../packages/caramos-ota/README_EN.md) | giống bản tiếng Việt |

Checklist chi tiết cho [packages/caramos-ota/README.md](../packages/caramos-ota/README.md), lấy theo diff release `1.0.11 -> 1.0.12`:

- Đổi tiêu đề release workflow:

  ```diff
  - ## 13. Quy trình release OTA đến 1.0.11
  + ## 13. Quy trình release OTA đến 1.0.12
  ```

- Thêm version mới vào cuối migration chain:

  ```diff
  - 1.0.1 → ... → 1.0.10 → 1.0.11
  + 1.0.1 → ... → 1.0.10 → 1.0.11 → 1.0.12
  ```

- Đổi package version và latest target:

  ```diff
  - Package cần release qua PPA: `caramos-ota` version `1.0.11-0caramos1`.
  - Latest CaramOS migration target: `1.0.11`.
  + Package chuẩn bị release qua PPA: `caramos-ota` version `1.0.12-0caramos1`.
  + Latest CaramOS migration target trong source: `1.0.12`.
  ```

- Đổi command path local nếu docs còn hardcode máy cá nhân:

  ```diff
  - cd /home/<user>/Documents/CaramOS/packages/caramos-ota
  + cd packages/caramos-ota
  ```

- Đổi expected result trong VM:

  ```diff
  - CaramOS version: 1.0.11
  + CaramOS version: 1.0.12
  ```

- Đổi maintainer/upload command:

  ```diff
  - Maintainer `<old-maintainer>` bump `debian/changelog` lên `1.0.11-0caramos1`, build source package và upload PPA:
  + Maintainer `<maintainer>` bump `debian/changelog` lên `1.0.12-0caramos1`, build source package và upload PPA:

  - dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.11-0caramos1_source.changes
  + dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_1.0.12-0caramos1_source.changes
  ```

- Đổi expected PPA candidate:

  ```diff
  - `apt-cache policy` phải thấy candidate là `1.0.11-0caramos1` hoặc version mới hơn.
  + `apt-cache policy` phải thấy candidate là `1.0.12-0caramos1` hoặc version mới hơn.
  ```

- Đổi ISO version/output trong phần build ISO:

  ```diff
  - ISO release dùng `CARAMOS_VERSION=1.0.11` ...
  + ISO source version hiện là `CARAMOS_VERSION=1.0.12` ...

  - CaramOS-1.0.11-cinnamon-amd64.iso
  + CaramOS-1.0.12-cinnamon-amd64.iso
  ```

- Đổi câu kỳ vọng rootfs sau bootstrap:

  ```diff
  - Bên trong ISO/rootfs sau bootstrap phải là `1.0.11`, không phải `1.0.1` hay version trung gian cũ.
  + Bên trong ISO/rootfs sau bootstrap phải là `1.0.12`, không phải `1.0.1` hay version trung gian cũ.
  ```

### 3. Landing page

| File | Cần đổi/kiểm tra |
|---|---|
| [landing/src/main.jsx](../landing/src/main.jsx) | hero badge, SEO title/description, download title/lead |
| [landing/src/main.jsx](../landing/src/main.jsx) | thêm release note mới vào `releaseNotes` cho tiếng Việt và tiếng Anh |
| [landing/src/main.jsx](../landing/src/main.jsx) | cập nhật `releaseNotesLead` để range kết thúc ở version mới |

Sau khi sửa landing:

```bash
cd landing
yarn build
```
