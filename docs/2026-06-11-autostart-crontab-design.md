# 開機自動啟動：`task set-start` / `task unset-start`

日期：2026-06-11

## 目標

讓 RPi 在開機時自動啟動 home_server，並在啟動前重置 BLE 介面以防萬一。
透過 go-task 提供 `set-start`（安裝）與 `unset-start`（移除）兩個指令，兩者皆冪等。

## 背景與限制

- 現有 `run` task 為 `sudo -E .venv/bin/python3.12 -m home_server`，啟動本來就需要 root
  （bluepy 操作 HCI 需要權限）。因此自動啟動採用 **root 的 crontab**。
- cron 環境沒有 cwd、沒有 PATH、不會走 taskfile 的 `dotenv` 機制。app 直接讀
  `os.environ`，故開機流程必須自行 `source .env`，且所有路徑須為絕對路徑。
- 採用 uv 管理的 venv，啟動須用 venv 內的絕對 python（`.venv/bin/python3.12`），
  不可依賴 PATH 中的 `uv` 或 `python`。

## 設計

### 1. `scripts/boot_start.sh`（新增，開機 wrapper）

```sh
#!/usr/bin/env bash
set -euo pipefail
# cron 無 cwd：由腳本自身位置推導專案根目錄
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
# 載入 .env（cron 不走 task 的 dotenv；app 直接讀 os.environ）
set -a
[ -f .env ] && . ./.env
set +a
# 重置 BLE 介面以防萬一；失敗不中斷啟動
hciconfig hci0 down || true
hciconfig hci0 up   || true
# 用 venv 內絕對 python 啟動（考量 uv 環境）
exec "$PROJECT_DIR/.venv/bin/python3.12" -m home_server
```

- stdout/stderr 的重導向由 crontab 端負責（見下），wrapper 本身不處理 log。
- `hciconfig down/up` 以 `|| true` 包住，介面不存在或已關時不影響後續啟動。

### 2. `taskfile.yml` 新增 `set-start`

行為：
1. `chmod +x scripts/boot_start.sh`
2. 計算絕對路徑：`ROOT="$(pwd)"`、`BOOT="$ROOT/scripts/boot_start.sh"`、
   `LOG="$ROOT/data/boot.log"`。
3. 冪等取代：取現有 `sudo crontab -l`（可能為空），以標記註解
   `# intelligent-home-autostart` 過濾掉舊的自動啟動行，再附加新行後寫回
   `sudo crontab -`：

   ```
   @reboot <BOOT> >> <LOG> 2>&1 # intelligent-home-autostart
   ```

log 導向專案 `data/boot.log`，與現有 `data/` 慣例一致。

### 3. `taskfile.yml` 新增 `unset-start`

行為：取 `sudo crontab -l`，過濾掉帶 `# intelligent-home-autostart` 標記的行後寫回。
- 若過濾後為空 → `sudo crontab -r`（移除整份 crontab）。
- 原本就沒有該行時，安靜結束、不報錯（冪等）。

## 標記註解

`# intelligent-home-autostart` 作為唯一識別，讓 `set-start` 可安全重複執行、
`unset-start` 可精準移除，且不影響使用者 crontab 中的其他既有條目。

## 測試 / 驗證

此為 shell + crontab 部署腳本，無單元測試。驗證方式（於 RPi 上）：
1. `task set-start` → `sudo crontab -l` 應見單一帶標記的 `@reboot` 行。
2. 再次 `task set-start` → 仍只有一行（冪等）。
3. 重開機 → 服務自動啟動，`data/boot.log` 有輸出。
4. `task unset-start` → `sudo crontab -l` 不再有該行；重複執行不報錯。

## 不做（YAGNI）

- 不支援可設定的 hci 介面編號（寫死 hci0，RPi 內建藍牙慣例）。
- 不改用 systemd unit（維持與現有 sudo + task 流程一致）。
