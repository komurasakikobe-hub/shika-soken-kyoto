#!/bin/zsh
# 京都歯科総研 — 評価・口コミ件数の月次リフレッシュ＋サイト再生成＋公開
# launchd（com.osakashikasoken.reviewrefresh）から毎月1日 4:04 に実行
set -e
set -o pipefail
SITE_DIR="/Users/komurasakishoutaira/Desktop/クロード/京都歯科総研"
LOG_DIR="$SITE_DIR/_daily_post_logs"
mkdir -p "$LOG_DIR"
exec > "$LOG_DIR/reviewrefresh_$(date +%Y-%m).log" 2>&1
cd "$SITE_DIR"
set -a; source .env; set +a

echo "===== 口コミ件数リフレッシュ $(date) ====="
python3 refresh_reviews.py
python3 build_clinics.py
python3 build_features.py
python3 build_sitemap.py
git add clinic_db.json articles/ sitemap.xml
git commit -m "月次リフレッシュ: 掲載院の評価・口コミ件数をGoogle最新値に更新

Co-Authored-By: Claude (automated) <noreply@anthropic.com>" || echo "変更なし"
git push
# 公開はshika-sokenリポジトリのkyotoブランチから行われる（Cloudflare Pages接続先）
git push https://github.com/komurasakikobe-hub/shika-soken.git main:kyoto
echo "===== 完了 $(date) ====="
