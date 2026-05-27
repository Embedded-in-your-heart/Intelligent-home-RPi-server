# Intelligent Home RPi Server

智能家庭控制系統的 Raspberry Pi 中央伺服器。

完整設計請參考 [`../docs/RPi-Server 開發文件.md`](../docs/RPi-Server%20開發文件.md)。

## 快速啟動

### 環境變數

複製 `.env.example` 成 `.env` 並調整（`.env` 已被 gitignore）：

```powershell
cp .env.example .env
# 編輯 .env，填入 HOME_SERVER_SECRET_KEY（或設 HOME_SERVER_DEBUG=1 略過）
```

`taskfile.yml` 會自動載入 `.env`；若直接用 `uv run` 則需手動 export
（Linux：`set -a; source .env; set +a`）。

### Windows（開發、非 BLE 測試）

```powershell
uv sync
uv run pytest
uv run python -m home_server
```

> 註：dev 環境採用 Python 3.12（`.python-version`），程式碼維持 3.11 相容以利 RPi 部署。
> 路徑含非 ASCII 字元時 3.11 的 `site.py` 會炸，因此 dev 用 3.12。

### Raspberry Pi（部署）

```bash
sudo apt install -y libglib2.0-dev libbluetooth-dev pkg-config
uv sync
uv run python -m home_server
```

BLE 掃描小工具（驗證 STM32 廣播）：

```bash
uv run python scripts/scan_ble.py 5
```

### Taskfile（推薦）

安裝 [Task](https://taskfile.dev/installation/) 之後可用 `task <name>` 跑常用指令，
會自動載入 `.env`：

```bash
task                 # 列出所有 task
task install         # uv sync
task run             # 啟動 dev server
task test            # pytest
task test:verbose    # pytest -v
task lint            # ruff check
task lint:fix        # ruff check --fix
task fmt             # ruff format
task typecheck       # mypy strict
task ci              # lint + typecheck + test
task scan -- 5       # RPi 限定：BLE 掃描 5 秒
task clean           # 清除 caches 與 dev SQLite
```

## 專案狀態

### ✅ 已完成

**Phase 1：骨架**
- uv 專案、`pyproject.toml`、目錄結構、`.gitignore`
- `config.py`（從環境變數讀取設定）、`core/logging.py`
- `db/schema.sql`（users / devices / channels / readings 四個表 + 索引 + WAL）
- `__main__.py`：可啟動空殼 Flask app，含 `/health` endpoint，自動建 DB

**Phase 2：BLE 通訊鏈結**
- `ble/interface.py`：`BLEManager` Protocol、`DiscoveredDevice`、`NotifyCallback` 型別
- `ble/parser.py`：bytes ↔ value 雙向，支援 10 種格式（uint8/int8/uint16_le|be/int16_le|be/uint32_le/int32_le/float32_le|be）
- `ble/rate_limiter.py`：per-key 限頻，可注入 fake clock 測試
- `ble/mock_manager.py`：Windows 測試與開發用，支援預設掃描結果、模擬 Notify、追蹤 writes
- `ble/bluepy_manager.py`（Linux only）：每個 peripheral 一個 worker thread + command queue + future，避免 bluepy 跨執行緒問題；CCCD 0x0001 啟用 Notify
- `scripts/scan_ble.py`：RPi 上手動驗證 BLE 掃描的小工具

**Phase 3a：DB Repository 層**
- `db/users.py`：`create / get_by_id / get_by_username / update_password`
- `db/devices.py`：`create / get_by_id / get_by_address / list_all / list_by_owner / delete`
- `db/channels.py`：`create / get_by_id / list_by_device / list_all / delete`；`Literal["controller", "display"]` 型別
- `db/readings.py`：`insert / list_by_channel (since/until/limit) / count_by_channel / delete_older_than`；時間戳統一 UTC `"YYYY-MM-DD HH:MM:SS"`
- 每個 repository 自帶領域錯誤型別（`DuplicateUsernameError` / `DeviceNotFoundError` 等）
- `tests/conftest.py`：共用 `db_conn` fixture（in-memory SQLite + schema 已套用）

**測試與品質：** 68 unit tests passing、`ruff check` 全綠。

### 🚧 進行中 / 未完成

**Phase 3b：Service 層**（規劃中）
- `services/user_service.py`：bcrypt 雜湊、註冊/登入
- `services/device_service.py`：新增裝置（觸發 BLE 連線）
- `services/channel_service.py`：頻道 CRUD、限頻寫入 reading、控制指令編碼
- **BLE 自動重連邏輯**（指數退避）放在 service 層，方便用 `MockBLEManager` 測試

**Phase 3c：認證 Blueprint**
- Flask-Login + bcrypt + Flask-WTF CSRF
- `/auth/register`、`/auth/login`、`/auth/logout`

**Phase 3d：Device / Channel CRUD Blueprint**
- `/devices`（列表、掃描、新增、刪除）
- `/devices/<id>/channels`（新增、刪除）
- 控制型頻道的 `POST /channels/<id>/write`

**Phase 3e：SocketIO + 前端**
- Flask-SocketIO（threading 模式），與 bluepy worker thread 串接
- 監控型頻道即時推播（每個頻道一個 room）
- Jinja2 + HTMX 模板、Chart.js 歷史趨勢圖

**Phase 4：整合測試與部署**
- 多 STM32 節點分散式佈署測試
- `systemd` service 安裝腳本
- RPi 上的長時間穩定性測試
