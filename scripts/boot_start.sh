#!/usr/bin/env bash
set -euo pipefail
# cron has no cwd: derive the project root from the script's own location.
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"
# Load .env (cron does not run through task's dotenv; the app reads os.environ).
set -a
[ -f .env ] && . ./.env
set +a
# Reset the BLE interface just in case; a failure here must not block startup.
hciconfig hci0 down || true
hciconfig hci0 up || true
# Start via the absolute venv python (uv-managed environment).
exec "$PROJECT_DIR/.venv/bin/python3.12" -m home_server
