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
task set-start       # RPi 限定：安裝開機自動啟動（root crontab @reboot）
task unset-start     # RPi 限定：移除開機自動啟動
task clean           # 清除 caches 與 dev SQLite
```

### 開機自動啟動（RPi）

`task set-start` 會在 **root 的 crontab** 寫入一條帶標記
（`# intelligent-home-autostart`）的 `@reboot` 項目，開機時執行
`scripts/boot_start.sh`：載入 `.env` → 重置 `hci0`（`hciconfig down/up`，
失敗不中斷）→ 用 `.venv` 內的絕對 python 啟動 server。指令可重複執行（冪等），
`task unset-start` 則精準移除該項目、不影響其他 crontab 條目。

開機輸出（stdout/stderr）會導向 `data/boot.log`。監控與讀取日誌：

```bash
tail -f data/boot.log            # 即時跟看開機啟動輸出
tail -n 50 data/boot.log         # 看最近 50 行
grep -iE "error|traceback" data/boot.log   # 只看錯誤
sudo crontab -l                  # 確認已安裝的 @reboot 項目
```

## 頻道類型

系統支援以下頻道類型與顯示行為：

| 類型 | unit 值 | 介面行為 |
|------|---------|---------|
| `display` | 數值單位（如 `°C`、`dBA`、`mg`） | Chart.js 趨勢圖＋現值／最小／最大／平均統計 |
| `display` | `0/1` | 旗標 LED 燈＋狀態文字＋觸發 toast 通知 |
| `display` | `enum:0=標籤,1=標籤,...` | 列舉徽章（enum badge），動態對應數值到標籤 |
| `controller` | `0/1` | 開／關切換器（HTMX 即時送出） |
| `controller` | 其他 | 泛用文字輸入表單（generic write form） |

### 預設頻道目錄（14 筆）

`data/channel_presets.json` 內建 14 筆預設，對應 STM32 BLE 服務：

| UUID（末段） | 標籤 | 類型 | 單位 |
|-------------|------|------|------|
| 1A220002 | 溫度 (°C) | display | °C |
| 1A220003 | 濕度 (% RH) | display | % RH |
| 1A220004 | 加速度量值 (g) | display | g |
| 1A220005 | 陀螺儀量值 (dps) | display | dps |
| 1A220006 | 異常晃動警示 | display | 0/1 |
| 1A220007 | 麥克風音量 | display | level (0–1023) |
| 1A220008 | 大聲警示 | display | 0/1 |
| 1A22F002 | LED1 開關 | controller | 0/1 |
| 1A22F003 | 控制旗標 | controller | bitmask |
| 1A22000A | 警報聲偵測 | display | 0/1 |
| 1A22000B | 音量 dB(A) | display | dBA |
| 1A22000C | 震動強度 (mg) | display | mg |
| 1A22000D | 震動偵測 | display | 0/1 |
| 1A22000E | 地震警報 | display | 0/1 |

Mock feed 模擬模式：dBA 頻道以正弦波產生浮點數、mg 頻道以隨機值模擬震動、0/1 頻道定期翻轉。

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

**Phase 3b：Service 層**
- `services/user_service.py`：bcrypt 雜湊（cost 可注入，測試用低 cost）、`register` / `authenticate`；密碼長度限制 8–72 bytes（後者避免 bcrypt 截斷）
- `services/device_service.py`：`DeviceService`（建構注入 `BLEManager`）；`scan` / `add_device`（驗證 MAC → 寫 DB → best-effort 連線，連不上仍保留裝置）/ `remove_device`（先斷線再刪除）/ `list_devices`
- `services/channel_service.py`：`ChannelService`（注入 `BLEManager` / `RateLimiter` / `on_reading` callback）；`add_channel` / `write_command`（僅 controller 型，編碼後 BLE write）/ `handle_notify`（解析 → 即時推播 callback 不限頻 → DB 寫入限頻）/ `get_history` / `list_by_device`
- 設計邊界：service 層維持純業務邏輯，BLE 操作同步呼叫介面（序列化由 `BluepyManager` 內部處理）；notify subscribe 的執行緒 wiring 與自動重連背景迴圈留待 3e

**Phase 3c：認證 Blueprint**
- `web/__init__.py`：application factory `create_app`，整合 Flask-Login + Flask-WTF CSRF
- `web/db.py`：per-request SQLite 連線（`flask.g` + `teardown_appcontext`，每執行緒專屬）
- `web/auth.py`：`/auth/register`、`/auth/login`、`/auth/logout`；`LoginUser`、`FlaskForm`（自帶 CSRF token）、`next` 參數的 open-redirect 防護
- `web/templates/`：`base` / `index` / `auth/login` / `auth/register` 陽春模板（含 CSRF）
- 已可從瀏覽器完成「註冊 → 自動登入 → 登出」全流程

**Phase 3d：Device / Channel CRUD Blueprint**
- `/devices`（列表、掃描、新增、刪除）
- `/devices/<id>/channels`（新增、刪除）
- 控制型頻道的 `POST /channels/<id>/write`

**Phase 3e：SocketIO + 前端**
- Flask-SocketIO（threading 模式），與 bluepy worker thread 串接
- 監控型頻道即時推播（每個頻道一個 room）
- Jinja2 + HTMX 模板、Chart.js 歷史趨勢圖＋統計欄位
- 頻道 widget 共用 Jinja2 macro（`_channel_widget.html`），dashboard 與裝置詳情頁共用同一套渲染邏輯

**測試與品質：** unit tests passing、`ruff check` 與 `mypy src`（strict）全綠。

### 🚧 進行中 / 未完成

**Phase 4：整合測試與部署**
- 多 STM32 節點分散式佈署測試
- `systemd` service 安裝腳本
- RPi 上的長時間穩定性測試
