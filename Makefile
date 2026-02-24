.PHONY: build clean help

build:
	@echo "CaramOS Build — Remaster từ Linux Mint"
	@echo ""
	@echo "Usage:"
	@echo "  sudo ./build.sh                    # Tự tải và build"
	@echo "  sudo ./build.sh /path/to/mint.iso  # Dùng ISO có sẵn"
	sudo ./build.sh $(ISO)

clean:
	sudo ./build.sh --clean

help:
	@echo "CaramOS Build System (ISO Remaster)"
	@echo ""
	@echo "  make build              — Build CaramOS ISO (tự tải Mint ISO)"
	@echo "  make build ISO=file.iso — Build từ ISO có sẵn"
	@echo "  make clean              — Xoá build artifacts"
	@echo "  make help               — Hiển thị trợ giúp"
	@echo ""
	@echo "Yêu cầu:"
	@echo "  sudo apt install squashfs-tools xorriso rsync wget"
