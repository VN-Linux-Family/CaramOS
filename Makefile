.PHONY: build release clean docker-build docker-release docker-clean help

build:
	@echo "CaramOS Build — Dev mode (lz4, nhanh)"
	sudo ./build.sh $(ISO)

release:
	@echo "CaramOS Build — Release mode (xz, nhỏ)"
	sudo ./build.sh --release $(ISO)

clean:
	sudo ./build.sh --clean

help:
	@echo "CaramOS Build System (ISO Remaster)"
	@echo ""
	@echo "--- Local Build (Chỉ Ubuntu/Mint/Debian) ---"
	@echo "  make build                — Dev build (lz4, ~1 phút nén)"
	@echo "  make release              — Release build (xz, ~10 phút, ISO nhỏ)"
	@echo "  make clean                — Xoá build (giữ Mint ISO)"
	@echo "  Yêu cầu: sudo apt install squashfs-tools xorriso rsync wget curl isolinux"
	@echo ""
	@echo "--- Docker Build (Mọi distro/macOS/Windows) ---"
	@echo "  make docker-build         — Dev build trong Docker"
	@echo "  make docker-release       — Release build trong Docker"
	@echo "  make docker-clean         — Xoá build bằng Docker"
	@echo "  Yêu cầu: Docker + docker compose"
	@echo ""
	@echo "Tham số bổ sung (cho cả 2 loại):"
	@echo "  make [target] ISO=file.iso — Build từ ISO có sẵn"

docker-build:
	@echo "CaramOS Build — Docker Dev mode (lz4, nhanh)"
	docker compose run --rm builder sudo ./build.sh $(ISO)

docker-release:
	@echo "CaramOS Build — Docker Release mode (xz, nhỏ)"
	docker compose run --rm builder sudo ./build.sh --release $(ISO)

docker-clean:
	@echo "CaramOS Build — Docker Clean dọn dẹp"
	docker compose run --rm builder sudo ./build.sh --clean
