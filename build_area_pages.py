# -*- coding: utf-8 -*-
"""
区別ランディングページ生成（SEOの主砲）

「北区 歯医者」「難波 歯科 おすすめ」等の高ボリューム地域クエリは、従来
ランキングページのURLパラメータ（?ward=…）でしか表現できず、Googleに
別ページとしてインデックスされなかった。区ごとの静的ページを生成し、
長尾の地域検索を受け止める。

- 出力: articles/area/<slug>.html（対象区は site_config.json の ward_pages。未設定なら大阪24区）
- 内容: 区の医院数・平均口コミ等の実データ → スコア上位の医院カード →
        インタラクティブ版（shindan?ward=…）への導線 → 免責
- 法的配慮: 「データランキング」表記・条件適合度の免責・policy導線（policy.html準拠）
使い方: python3 build_area_pages.py
"""
import json
import os
import re
import html
from urllib.parse import quote

ROOT = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(ROOT, "clinic_db.json")
OUT_DIR = os.path.join(ROOT, "articles", "area")
CFG = json.load(open(os.path.join(ROOT, "site_config.json"), encoding="utf-8"))
SLUG_MAP = json.load(open(os.path.join(ROOT, "clinic_slugs.json"), encoding="utf-8"))

# 区 → (URLスラッグ, 検索されやすい地名の補足)
WARDS = {
    "北区": ("kita", "梅田・大阪駅"), "中央区": ("chuo", "心斎橋・難波"),
    "西区": ("nishi", "本町・阿波座"), "福島区": ("fukushima", "福島・野田"),
    "天王寺区": ("tennoji", "天王寺・上本町"), "阿倍野区": ("abeno", "阿倍野・昭和町"),
    "浪速区": ("naniwa", "なんば・新今宮"), "淀川区": ("yodogawa", "新大阪・十三"),
    "東淀川区": ("higashiyodogawa", "上新庄"), "都島区": ("miyakojima", "京橋・桜ノ宮"),
    "此花区": ("konohana", "西九条"), "港区": ("minato", "弁天町"),
    "大正区": ("taisho", "大正"), "西淀川区": ("nishiyodogawa", "姫島"),
    "東成区": ("higashinari", "今里・玉造"), "生野区": ("ikuno", "鶴橋・桃谷"),
    "旭区": ("asahi", "千林"), "城東区": ("joto", "蒲生・野江"),
    "鶴見区": ("tsurumi", "横堤・放出"), "住之江区": ("suminoe", "住之江・南港"),
    "住吉区": ("sumiyoshi", "我孫子・長居"), "東住吉区": ("higashisumiyoshi", "田辺・針中野"),
    "平野区": ("hirano", "平野・喜連瓜破"), "西成区": ("nishinari", "天下茶屋"),
}

# 都市固有の区は site_config.json の "ward_pages" に置く（都市トークンをコードに埋めない原則）。
# 形式: {"東灘区": ["higashinada", "住吉・御影"], ...}。未設定の都市は上の大阪の表を使う。
_cfg_wards = CFG.get("ward_pages") or {}
if _cfg_wards:
    WARDS = {k: (v[0], v[1] if len(v) > 1 else "") for k, v in _cfg_wards.items()}

TOP_N = 10

# 研究記事（build_data_report.py生成）への導線。実在するファイルのみリンクを出す
# （研究記事は大阪にしか無い想定。無いサイトでは節ごと出さず404リンクを作らない）
RESEARCH_ARTICLES = [
    ("equipment-gap", "精密機器の導入率は地域・医院でどれだけ違うか（設備データの研究）"),
    ("worktime-access", "夜間・週末に通える歯科はどれだけあるか（診療時間データの研究）"),
]


def research_links_available():
    ok = []
    for slug, label in RESEARCH_ARTICLES:
        path = os.path.join(ROOT, "articles", "research", f"{slug}.html")
        if os.path.exists(path):
            ok.append((slug, label))
        else:
            print(f"⚠️ 研究記事が見つからないためリンクを省略: articles/research/{slug}.html")
    return ok


def esc(s):
    return html.escape(str(s), quote=True)


CITY = CFG.get("city", "大阪市")   # 例: 大阪市 / 神戸市 / 京都市


def ward_of(addr):
    m = re.search(re.escape(CITY) + r'[^\d]*?区', addr or "")
    return m.group(0).replace(CITY, "") if m else ""


def clinic_card(c):
    slug = SLUG_MAP.get(c.get("place_id"), "")
    href = f"../clinics/{quote(slug)}.html" if slug else "#"
    tags = "".join(f'<span class="tag">{esc(t)}</span>'
                   for t in (c.get("reputation_tags") or [])[:3])
    rating = c.get("rating") or 0
    rv = c.get("total_reviews") or 0
    ai = (c.get("ai_summary") or "")[:80]
    return f'''<a class="acard" href="{href}">
  <p class="acard-name">{esc(c.get("name",""))}</p>
  <p class="acard-meta">Google ★{rating}（{rv}件） ・ {esc(c.get("address","")[:26])}</p>
  {f'<div class="tags">{tags}</div>' if tags else ""}
  {f'<p class="acard-ai">{esc(ai)}…</p>' if ai else ""}
</a>'''


def ward_data_section(ward, clinics, research_ok):
    """この区の実データ（clinic_db.json集計）＋研究記事への文脈リンク。
    事実（件数・割合）のみを述べ、順位・優劣の断定はしない。
    研究記事が1本も実在しないサイトでは節ごと出さない。"""
    if not research_ok:
        return ""
    facts = []
    eq = [c for c in clinics if isinstance(c.get("equipment_stars"), dict) and c["equipment_stars"]]
    if eq:
        ct = sum(1 for c in eq if (c["equipment_stars"].get("CT") or 0) >= 3)
        facts.append(f"設備情報を解析できた{len(eq)}院のうち、歯科用CTの導入が公式サイト等で確認できたのは{ct}院でした。")
    night = sum(1 for c in clinics
                if any("夜間" in t for t in (c.get("specialty_tags") or []) + (c.get("site_features") or [])))
    facts.append(f"夜間診療の案内が確認できた医院は、{ward}の分析対象{len(clinics)}院のうち{night}院です。")
    facts_html = "".join(f"<p>{esc(t)}</p>" for t in facts)
    links_html = "".join(
        f'<li><a href="../research/{slug}.html">{esc(label)}</a></li>'
        for slug, label in research_ok
    )
    return (f'<h2>{esc(ward)}のデータを詳しく見る</h2>'
            f'{facts_html}'
            f'<p>こうした設備や診療時間の傾向は、市全体のデータをまとめた研究記事で背景まで確認できます。</p>'
            f'<ul class="rlinks">{links_html}</ul>'
            f'<p class="rnote">件数・割合は当サイトが公開情報から機械的に解析できた範囲の値です。「確認できなかった」は「無い」という意味ではありません。</p>')


def build_page(ward, slug, spots, clinics, research_ok=()):
    n = len(clinics)
    total_rv = sum(c.get("total_reviews") or 0 for c in clinics)
    top = sorted(clinics, key=lambda c: (-(c.get("total_score") or 0), -(c.get("total_reviews") or 0)))[:TOP_N]
    cards = "".join(clinic_card(c) for c in top)
    site = CFG["site_name"]
    domain = CFG["domain"]
    title = f"{ward}（{spots}）の歯医者・歯科医院 データランキング｜口コミ{total_rv:,}件をAI分析"
    desc = (f"{CITY}{ward}の歯科医院{n}院を、Google口コミ{total_rv:,}件と公式サイト等の公開情報からAIが分析。"
            f"公開情報の充実度と評判にもとづくデータランキングです（優劣の断定ではありません）。")
    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:site_name" content="{esc(site)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:type" content="website">
<meta property="og:url" content="https://{domain}/articles/area/{slug}">
<link rel="canonical" href="https://{domain}/articles/area/{slug}">
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Shippori+Mincho:wght@600;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<script src="../../assets/site-config.js"></script>
<script src="../../assets/odr-track.js"></script>
<script type="application/ld+json">{json.dumps({
    "@context": "https://schema.org", "@type": "CollectionPage",
    "name": title,
    "description": desc,
    "url": f"https://{domain}/articles/area/{slug}",
    "isPartOf": {"@type": "WebSite", "name": site, "url": f"https://{domain}/"},
}, ensure_ascii=False)}</script>
<style>
body{{margin:0;background:var(--odr-paper);color:var(--odr-ink);font-family:var(--odr-sans);line-height:1.9;}}
.odr-brandbar{{position:sticky;top:0;z-index:100;}}
.hero{{background:var(--odr-pine);color:#fff;padding:clamp(36px,5vw,56px) clamp(16px,4vw,40px);}}
.hero-in{{max-width:860px;margin:0 auto;}}
.kicker{{font-family:var(--odr-mono);font-size:.72rem;letter-spacing:.2em;color:var(--odr-terra);margin:0 0 12px;}}
h1{{font-size:clamp(1.25rem,3vw,1.8rem);font-weight:900;margin:0 0 12px;line-height:1.5;}}
.hero p{{color:#cfe0d8;font-size:.92rem;margin:0;}}
.stats{{display:flex;gap:24px;margin-top:20px;font-family:var(--odr-mono);}}
.stats b{{display:block;font-size:1.4rem;}}
.stats span{{font-size:.68rem;color:#9cbbae;letter-spacing:.1em;}}
main{{max-width:860px;margin:0 auto;padding:36px clamp(16px,4vw,40px) 72px;}}
h2{{font-size:1.1rem;color:var(--odr-pine);border-left:4px solid var(--odr-terra);padding-left:10px;margin:32px 0 16px;}}
.acard{{display:block;background:#fff;border:1px solid var(--odr-line);border-radius:14px;padding:18px 22px;margin-bottom:12px;text-decoration:none;color:inherit;transition:box-shadow .2s;}}
.acard:hover{{box-shadow:var(--shadow-lift);}}
.acard-name{{font-weight:700;font-size:1rem;color:var(--odr-pine);margin:0 0 4px;}}
.acard-meta{{font-size:.78rem;color:var(--odr-ink2);margin:0 0 8px;}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;}}
.tag{{background:#eaf2ee;color:var(--odr-pine);font-size:.7rem;font-weight:700;border-radius:999px;padding:3px 10px;}}
.acard-ai{{font-size:.8rem;color:var(--odr-ink2);margin:0;}}
.cta{{display:block;background:var(--odr-pine);color:#fff;text-align:center;font-weight:700;border-radius:999px;padding:15px;margin:28px 0;text-decoration:none;}}
.cta:hover{{background:var(--odr-pine-2);}}
.rlinks{{margin:0 0 8px;padding-left:1.3em;}}
.rlinks li{{margin-bottom:6px;font-size:.92rem;}}
.rlinks a{{color:var(--odr-pine);}}
.rnote{{font-size:.76rem;color:var(--odr-ink2);}}
.disc{{font-size:.76rem;color:var(--odr-ink2);border-top:1px solid var(--odr-line);padding-top:18px;margin-top:36px;}}
.disc a{{color:inherit;}}
</style>
</head>
<body>
<header class="odr-brandbar odr-scope">
  <a class="odr-sig" href="../../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">{esc(site)}<small>Osaka Dental Research Institute</small></span>
  </a>
  <nav>
    <a href="../shindan/index.html">ランキング・AI診断</a>
    <a href="../features/index.html">特徴から探す</a>
    <a href="../index.html">コラム</a>
    <a href="../../network.html">展開エリア</a>
    <a href="../../shikumi.html">医院・開業医の方へ</a>
  </nav>
</header>
<section class="hero">
  <div class="hero-in">
    <p class="kicker">AREA ANALYSIS — {esc(slug.upper())}</p>
    <h1>{esc(ward)}（{esc(spots)}）の歯医者・歯科医院<br>データランキング</h1>
    <p>{esc(CITY)}{esc(ward)}の歯科医院を、Google口コミと公式サイト等の公開情報からAIが分析。公開情報の充実度と評判にもとづく参考情報です。</p>
    <div class="stats">
      <div><b>{n}</b><span>掲載医院</span></div>
      <div><b>{total_rv:,}</b><span>分析した口コミ</span></div>
    </div>
  </div>
</section>
<main>
  <h2>{esc(ward)}の分析スコア上位{len(top)}院</h2>
  {cards}
  <a class="cta" href="../shindan/index.html?ward={quote(ward)}">症状・希望条件も選んで、{esc(ward)}の医院を絞り込む →</a>
  {ward_data_section(ward, clinics, research_ok)}
  <p class="disc">スコア・順位は公開情報（口コミ・公式サイト等）の充実度と評判分析にもとづく参考表示であり、医院の技術や治療結果の優劣を示すものではありません。順位は条件の選択で変動します。掲載順が金銭で変わることはありません。受診の判断は必ず歯科医師にご相談ください。
  掲載情報の訂正は<a href="../../teisei.html">こちら</a>／詳細は<a href="../../policy.html">運営ポリシー・免責事項</a>。</p>
</main>
</body>
</html>'''


def main():
    db = json.load(open(DB, encoding="utf-8"))
    active = [c for c in db.values() if not c.get("q_excluded") and c.get("name")]
    os.makedirs(OUT_DIR, exist_ok=True)
    research_ok = research_links_available()
    made = 0
    for ward, (slug, spots) in WARDS.items():
        clinics = [c for c in active if ward_of(c.get("address", "")) == ward]
        if len(clinics) < 3:
            continue
        html_doc = build_page(ward, slug, spots, clinics, research_ok)
        with open(os.path.join(OUT_DIR, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(html_doc)
        made += 1
    print(f"✅ 区別ランディングページ生成: {made}区 → articles/area/")


if __name__ == "__main__":
    main()
