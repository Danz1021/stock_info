#!/bin/zsh
# ── 自動安裝與設定 crontab ────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=$(which python3)
PIP=$(which pip3)

echo "📦 安裝 Python 套件..."
$PIP install -r "$SCRIPT_DIR/requirements.txt" -q

echo ""
echo "📋 複製 .env 設定檔..."
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
  echo "  ✅ 已建立 .env，請編輯填入 Telegram 設定："
  echo "     open '$SCRIPT_DIR/.env'"
else
  echo "  ℹ️  .env 已存在，跳過。"
fi

echo ""
echo "⏰ 設定 crontab（每 15 分鐘，週一到週五 09:00~13:30 台股盤中 + 全天加密貨幣）..."

CRON_LINE="*/15 * * * * $PYTHON $SCRIPT_DIR/tracker.py >> $SCRIPT_DIR/cron.log 2>&1"

# 避免重複加入
(crontab -l 2>/dev/null | grep -v "tracker.py"; echo "$CRON_LINE") | crontab -

echo "  ✅ crontab 已設定："
echo "     $CRON_LINE"
echo ""
echo "📌 驗證 crontab："
crontab -l | grep tracker.py

echo ""
echo "🚀 立即測試執行（請先填好 .env）："
echo "   $PYTHON $SCRIPT_DIR/tracker.py"
