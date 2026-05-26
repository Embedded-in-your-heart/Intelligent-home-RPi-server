# Intelligent Home RPi Server

智能家庭控制系統的 Raspberry Pi 中央伺服器。

完整設計請參考 [`../docs/RPi-Server 開發文件.md`](../docs/RPi-Server%20開發文件.md)。

## 快速啟動

### Windows（開發、非 BLE 測試）

```powershell
uv sync
uv run pytest
uv run python -m home_server
```

### Raspberry Pi（部署）

```bash
sudo apt install -y libglib2.0-dev libbluetooth-dev pkg-config
uv sync
uv run python -m home_server
```

## 專案狀態

Phase 1（骨架）。
