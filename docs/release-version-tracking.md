# CaramOS release/version tracker

Tài liệu này ghi lại nơi còn cần product version và nơi không được hardcode version sau khi OTA chuyển sang **schema 2 timestamp migrations**.

> Quy ước hiện tại: timestamp migration không có product version. Version sản phẩm chỉ được truyền khi maintainer đóng release bằng `make release VERSION=x.y.z`.

## Model OTA hiện tại

- Migration mới dùng thư mục timestamp lexical, ví dụ `YYYYMMDDHHMMSS_slug/`.
- Manifest schema 2 không chứa `release`, `version`, `from_version`, hoặc `to_version`.
- Runner chạy mọi timestamp migration chưa apply theo thứ tự lexical dựa trên ledger.
- Local build/validate không cần product version.
- Legacy `v1_0_2..v1_0_12` giữ nguyên để tương thích và coi như frozen.

## Khi thêm OTA migration mới

| File/vị trí | Cần làm |
|---|---|
| `packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/YYYYMMDDHHMMSS_slug/` | thêm timestamp migration mới |
| `manifest.json` schema 2 | chỉ metadata UI/log; không có `release`, `version`, `from_version`, `to_version` |
| `migration.py` | logic apply đã review |
| `packages/caramos-ota/MIGRATIONS.md` | cập nhật quy tắc nếu model đổi |
| `packages/caramos-ota/README.md` | cập nhật hướng dẫn contributor nếu flow đổi |
| `packages/caramos-ota/README_EN.md` | cập nhật bản tiếng Anh tương ứng |

Không làm:

- Không thêm legacy version folder mới kiểu `v1_0_13`.
- Không sửa legacy `v1_0_2..v1_0_12` nếu không có migration-fix bắt buộc.
- Không hardcode product version vào manifest schema 2.
- Không hardcode target release trong test local/validate.

## Local build/validate

Local workflow không nhận `VERSION`:

```bash
cd packages/caramos-ota
make compile
make validate
make build
```

VM test local cũng không nên phụ thuộc target release hardcode. Nếu cần test một case legacy frozen, ghi rõ đó là compatibility test, không dùng làm template cho migration mới.

## Release product version

Chỉ maintainer chọn product version tại thời điểm release:

```bash
cd packages/caramos-ota
make release VERSION=x.y.z
```

`VERSION=x.y.z` dùng cho package/release artifact. Nó không biến timestamp migration thành version migration.

## Số phiên bản: bản phát hành và bản sửa nóng

Owner chốt ngày 2026-11-27: **mọi thay đổi tới máy người dùng đều có số phiên bản CaramOS riêng**. Nhờ vậy người dùng, Trung tâm cập nhật và số đếm máy hằng ngày (`/api/active`) đều biết máy đang ở bản nào.

| Loại | Số CaramOS | Gói caramos-ota | Cách làm | ISO |
|---|---|---|---|---|
| Bản phát hành | `x.y.z`, ví dụ `1.5.2` | `1.5.2-0caramos1` | `make release VERSION=1.5.2` | dựng ISO, tag `v1.5.2` |
| Bản sửa nóng | `x.y.z.n`, ví dụ `1.5.2.1`, `1.5.2.2` | `1.5.2.1-0caramos1` | `make release VERSION=1.5.2.1` | không dựng ISO, tag `ota-1.5.2.1` |
| Sửa lỗi dựng gói, trên máy không đổi gì | giữ nguyên | tăng đuôi, ví dụ `1.5.2.1-0caramos2` | thêm mục changelog bằng tay, rồi `make source` và `make upload` | không |

Quy tắc:

- **Không dùng đuôi `-0caramosN` (N từ 2 trở lên) cho thay đổi tới máy người dùng.** Đuôi này chỉ dành cho lần dựng lại gói khi Launchpad dựng hỏng mà nội dung trên máy không đổi.
  - Lý do: bản 1.5.2 đã lên PPA bảy lần (`1.5.2-0caramos1` tới `0caramos7`). Máy nào cũng ghi 1.5.2, và không ai biết máy đã nhận những bản sửa nào.
  - Từ 1.0.x tới 1.4.0, mỗi lần sửa đều có số mới, ví dụ 1.3.5 lên 1.3.6, 1.3.10 lên 1.3.11.
- **`make release VERSION=1.5.2.1`** làm hai việc qua `tools/prepare-release.py`, công cụ nhận số có 2 tới 4 phần:
  - ghi `PRODUCT_VERSION` trong `caramos_ota/release_metadata.py`;
  - ghi mục changelog `1.5.2.1-0caramos1`.
- **Phía máy người dùng:**
  - Máy cập nhật xong thì `/etc/caramos-release` ghi `VERSION=1.5.2.1`, và thông báo hiện "CaramOS đã cập nhật lên 1.5.2.1".
  - dpkg xếp `1.5.2.1-0caramos1` sau mọi bản `1.5.2-0caramosN`.
- **Tag của bản sửa nóng là `ota-x.y.z.n`, không bắt đầu bằng `v`.** Tag `v*` chạy `.github/workflows/build.yml` và dựng ISO mới. Bản sửa nóng tới máy qua OTA; ISO được dựng lại ở bản phát hành tiếp theo.
- **Mỗi bản sửa nóng có một mục trong `releaseNotes` của landing** (bảng ở mục Landing page bên dưới), để người dùng và owner tra được nó sửa gì.
- **Quy trình như bản phát hành:**
  - chạy đủ test;
  - thử trên máy ảo cài từ bản mới nhất;
  - dựng gói từ một clone sạch của commit phát hành, vì cây làm việc có thể còn file chưa commit;
  - đưa lên PPA, rồi thử lại bằng bản thật từ PPA.

## Tài liệu chính cần kiểm tra khi release

| File | Cần kiểm tra |
|---|---|
| `README.md` | current version user-facing, ISO name nếu có phát hành ISO |
| `README_EN.md` | current version user-facing, ISO name nếu có phát hành ISO |
| `packages/caramos-ota/README.md` | đảm bảo local build không yêu cầu version; release dùng `make release VERSION=x.y.z` |
| `packages/caramos-ota/README_EN.md` | giống bản tiếng Việt |
| `packages/caramos-ota/MIGRATIONS.md` | schema 2 + ledger rules vẫn đúng |
| `packages/caramos-ota/VM_TEST_CHECKLIST.md` | không còn target release stale trong ví dụ test mới |
| `CONTRIBUTING.md` | contributor workflow vẫn hướng về timestamp migration |

## Version cần giữ nguyên

| File/vị trí | Version | Lý do giữ |
|---|---|---|
| `scripts/config.sh` | `CARAMOS_MIGRATION_BASE_VERSION="1.0.1"` | base bootstrap lịch sử cho ISO/rootfs |
| `install-caramos-ota.sh` | fallback `1.0.1` nếu có | bootstrap cho máy từ ISO Open Beta đầu tiên |
| legacy migrations `v1_0_2..v1_0_12` | version lịch sử | compatibility frozen |

## Landing page

Landing page nằm ở repo riêng [VN-Linux-Family/caramos-landing](https://github.com/VN-Linux-Family/caramos-landing).
Nếu release có thay đổi user-facing hoặc ISO mới, cập nhật và build lại landing page:

```bash
git clone git@github.com:VN-Linux-Family/caramos-landing.git
cd caramos-landing
yarn install
yarn build
```

| File/vị trí | Bản phát hành (có ISO) | Bản sửa nóng |
|---|---|---|
| `server/release.js` | `VERSION` mới. Link ISO trên GitHub Release và R2 dùng số này | **không đổi**: bản sửa nóng không có ISO, đổi số này là gãy link tải |
| `src/content.js` | mục mới trong `releaseNotes`, cả tiếng Việt và tiếng Anh; `whatsNew` khi có tính năng lớn | mục mới trong `releaseNotes`, cả tiếng Việt và tiếng Anh, ví dụ `['1.5.2.1', 'tiêu đề', ['điểm 1', ...]]` |
| `scripts/prerender.mjs` | `ogImage` trỏ tới ảnh xem trước link của bản mới | không đổi |
| `public/assets/` | ảnh mới phải có **tên mới**, ví dụ `og-caramos-1.5.2.jpg`: `_headers` cache `/assets/*` một năm (`immutable`), ghi đè tên cũ thì trình duyệt vẫn hiện ảnh cũ | không đổi |

Chỉ cập nhật nội dung release/user-facing. Không dùng landing page để mô tả migration internals.
