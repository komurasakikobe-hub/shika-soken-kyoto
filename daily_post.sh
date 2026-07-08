#!/bin/zsh
# 京都歯科総研 — 毎日投稿バッチ
# launchd（com.kyotoshikasoken.dailypost.plist）から毎日呼び出される。
# 1. AI評判設計システムのkeyword_survey.pyでキーワード調査
# 2. blog_generator.pyでその日のテーマ1本を記事化
# 3. article_dates.jsonに今日の日付を登録
# 4. build_index.pyで一覧ページを再生成
# 5. git commit & push（Cloudflare Pagesが自動デプロイ）
#
# 手動で試す場合：zsh daily_post.sh

set -e
set -o pipefail

SITE_DIR="/Users/komurasakishoutaira/Desktop/クロード/京都歯科総研"
SURVEY_DIR="/Users/komurasakishoutaira/Desktop/クロード/AI評判設計システム"
LOG_DIR="$SITE_DIR/_daily_post_logs"
TODAY=$(date +%Y-%m-%d)
LOG_FILE="$LOG_DIR/$TODAY.log"

mkdir -p "$LOG_DIR"
exec > "$LOG_FILE" 2>&1

echo "===== 京都歯科総研 毎日投稿バッチ開始 $(date) ====="

# APIキーを読み込む
set -a
source "$SITE_DIR/.env"
set +a

# ── 1. キーワード調査 ──
echo "--- keyword_survey.py 実行 ---"
cd "$SURVEY_DIR"
python3 keyword_survey.py

if [ ! -f "$SURVEY_DIR/survey_result.json" ]; then
  echo "❌ survey_result.json が生成されませんでした。中断します。"
  exit 1
fi

# ── 2. 今日書く記事テーマを1本選ぶ（先頭のテーマ） ──
THEME=$(python3 -c "
import json
d = json.load(open('$SURVEY_DIR/survey_result.json'))
themes = d.get('blog_themes', [])
print(themes[0] if themes else '')
")

if [ -z "$THEME" ]; then
  echo "❌ 記事テーマが取得できませんでした。中断します。"
  exit 1
fi
echo "--- 今日のテーマ: $THEME ---"

# ── 3. 記事生成 ──
echo "--- blog_generator.py 実行 ---"
python3 blog_generator.py "$THEME"

# ── 4. 今日生成された記事ファイルを特定し、article_dates.jsonに登録 ──
cd "$SITE_DIR"
NEW_FILE=$(ls -t articles/${TODAY}_*.html 2>/dev/null | head -1)
if [ -z "$NEW_FILE" ]; then
  echo "❌ 生成された記事ファイルが見つかりません。中断します。"
  exit 1
fi
NEW_FILENAME=$(basename "$NEW_FILE")
echo "--- 生成された記事: $NEW_FILENAME ---"

python3 -c "
import json
p = 'article_dates.json'
d = json.load(open(p, encoding='utf-8'))
d['$NEW_FILENAME'] = '$TODAY'
json.dump(d, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
"

# ── 5. サイト一覧・サイトマップを再生成 ──
echo "--- build_index.py 実行 ---"
python3 build_index.py
echo "--- build_sitemap.py 実行（新記事をsitemap.xmlに反映） ---"
python3 build_sitemap.py

# ── 6. git commit & push ──
echo "--- git commit & push ---"
git add articles/ article_dates.json clinic_db.json sitemap.xml 2>/dev/null || true
git commit -m "$(cat <<EOF
毎日投稿: ${NEW_FILENAME%.html}

キーワード調査（keyword_survey.py）→記事生成（blog_generator.py）の
自動パイプラインによる投稿。

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
git push

echo "===== 完了 $(date) ====="
