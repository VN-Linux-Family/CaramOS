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

Nếu release có thay đổi user-facing hoặc ISO mới, kiểm tra landing page:

```bash
cd landing
yarn build
```

Chỉ cập nhật nội dung release/user-facing. Không dùng landing page để mô tả migration internals.
