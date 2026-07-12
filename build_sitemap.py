# -*- coding: utf-8 -*-
"""
sitemap.xml と robots.txt を生成する。

対象：
  - トップ・固定ページ（index.html / network.html / shikumi.html / for-clinics.html / teisei.html）
  - articles/ 直下の記事・一覧・カテゴリページ
  - articles/features/ / articles/shindan/
  - articles/clinics/ の全医院ページ（ここが検索流入の主戦場）

ドメインは site_config.json から読む（多都市展開時に差し替えるだけで済むように）。
新しい記事・医院ページを追加したら再実行すること（daily_post.sh にも組み込み済み）。
"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
BASE = f"https://{CFG['domain']}"

# 記事の表示用日付（article_dates.json優先。無ければファイル名の日付）
try:
    ARTICLE_DATES = json.loads((ROOT / "article_dates.json").read_text(encoding="utf-8"))
except FileNotFoundError:
    ARTICLE_DATES = {}


def url_entry(path: str, lastmod: str = "", priority: str = "0.5") -> str:
    loc = BASE + "/" + quote(path, safe="/-_.~")
    lm = f"\n    <lastmod>{lastmod}</lastmod>" if lastmod else ""
    return f"""  <url>
    <loc>{loc}</loc>{lm}
    <priority>{priority}</priority>
  </url>"""


def main():
    today = date.today().isoformat()
    entries = []

    # ── 固定ページ ──
    entries.append(url_entry("", today, "1.0"))
    entries.append(url_entry("articles/shindan/", today, "0.9"))
    if (ROOT / "articles" / "research" / "index.html").exists():
        entries.append(url_entry("articles/research/", today, "0.8"))  # 独自データ研究ページ（大阪のみ。build_data_report.py未展開の都市では実ファイルが無いため除外）
        # 研究シリーズ記事（build_data_report.py生成。lastmodは実ファイル更新日＝月次リフレッシュの正直な鮮度シグナル）
        for f in sorted((ROOT / "articles" / "research").glob("*.html")):
            if f.name == "index.html":
                continue
            lastmod = date.fromtimestamp(f.stat().st_mtime).isoformat()
            entries.append(url_entry(f"articles/research/{f.name}", lastmod, "0.7"))
    entries.append(url_entry("articles/index.html", today, "0.8"))
    entries.append(url_entry("articles/features/index.html", today, "0.7"))
    entries.append(url_entry("network.html", priority="0.5"))
    entries.append(url_entry("shikumi.html", priority="0.4"))
    entries.append(url_entry("for-clinics.html", priority="0.4"))
    entries.append(url_entry("teisei.html", priority="0.3"))
    entries.append(url_entry("policy.html", priority="0.3"))
    if (ROOT / "about.html").exists():
        entries.append(url_entry("about.html", priority="0.3"))  # 運営者情報（E-E-A-T）

    # ── カテゴリページ ──
    for f in sorted((ROOT / "articles" / "area").glob("*.html")):
        entries.append(url_entry(f"articles/area/{f.name}", today, "0.8"))

    for f in sorted((ROOT / "articles").glob("cat-*.html")):
        entries.append(url_entry(f"articles/{f.name}", today, "0.5"))

    # ── 記事 ──
    for f in sorted((ROOT / "articles").glob("202?-??-??_*.html")):
        lastmod = ARTICLE_DATES.get(f.name)
        if not lastmod:
            m = re.match(r"(\d{4}-\d{2}-\d{2})_", f.name)
            lastmod = m.group(1) if m else ""
        entries.append(url_entry(f"articles/{f.name}", lastmod, "0.7"))

    # ── 医院ページ（検索流入の主戦場） ──
    # 薄いページ（実データが閾値未満・noindex対象）はsitemapに載せない
    # （scaled content abuse対策。判定の正本は thin_page_policy.py。2026-07-13）
    try:
        from thin_page_policy import thin_slugs
        skip = thin_slugs(str(ROOT))
    except Exception as e:
        print(f"⚠ thin_page_policy 読み込み失敗（全院を掲載します）: {e}")
        skip = set()
    n_skipped = 0
    for f in sorted((ROOT / "articles" / "clinics").glob("*.html")):
        if f.name[:-5] in skip:
            n_skipped += 1
            continue
        # lastmod=再生成日（月次リフレッシュで実データが変わるたび更新される＝正直な鮮度シグナル）
        from datetime import date as _d
        lastmod = _d.fromtimestamp(f.stat().st_mtime).isoformat()
        entries.append(url_entry(f"articles/clinics/{f.name}", lastmod, "0.6"))
    if n_skipped:
        print(f"   薄いページのsitemap除外: {n_skipped}件")

    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    (ROOT / "sitemap.xml").write_text(sitemap, encoding="utf-8")

    robots = f"""User-agent: *
Allow: /

Sitemap: {BASE}/sitemap.xml
"""
    (ROOT / "robots.txt").write_text(robots, encoding="utf-8")

    print(f"✅ sitemap.xml 生成: {len(entries)} URL")
    print(f"✅ robots.txt 生成")


if __name__ == "__main__":
    main()
