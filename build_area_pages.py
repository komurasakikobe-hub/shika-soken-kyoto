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

TOP_N = 15

# 診療時間の判定しきい値は evidence_grounding.py と揃える（夜間=19:30以降）
NIGHT_HHMM = (19, 30)
WEEKDAY_LABELS = ["月曜日", "火曜日", "水曜日", "木曜日", "金曜日"]

# 設備は「公開情報で確認できた」ものだけを出す（星3以上＝根拠あり扱い。0は未確認であって不在ではない）
EQUIP_MIN = 3
EQUIP_ORDER = ["CT", "マイクロスコープ", "口腔内スキャナー", "個室", "駐車場", "バリアフリー"]

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


def _hhmm(s):
    """「10時00分～19時30分」から終了時刻(h,m)を取り出す。取れなければNone。"""
    m = re.findall(r"(\d{1,2})\s*時\s*(\d{1,2})?\s*分?", s or "")
    if len(m) < 2:
        return None
    h, mi = m[-1]
    return (int(h), int(mi or 0))


def hours_facts(c):
    """診療時間から「確認できた事実」だけを返す。読めない曜日は黙って飛ばす（推測しない）。"""
    hours = c.get("business_hours")
    if isinstance(hours, str):        # 文字列で入っている事故データの防御（過去に1院あった）
        hours = [hours]
    if not isinstance(hours, list) or not hours:
        return {}
    byday = {}
    for line in hours:
        day = str(line).split(":")[0].strip()
        byday[day] = str(line)
    out = {}
    ends = []
    for d in WEEKDAY_LABELS:
        t = byday.get(d, "")
        if "定休" in t or "休" in t:
            continue
        e = _hhmm(t)
        if e:
            ends.append(e)
    if ends:
        latest = max(ends)
        out["weekday_end"] = f"{latest[0]}時" + (f"{latest[1]:02d}分" if latest[1] else "")
        out["night"] = latest >= NIGHT_HHMM
    for d, key in (("土曜日", "sat"), ("日曜日", "sun")):
        t = byday.get(d)
        if t is None:
            continue
        out[key] = not ("定休" in t or "休業" in t)
    return out


def equip_facts(c):
    st = c.get("equipment_stars")
    if not isinstance(st, dict):
        return []
    return [k for k in EQUIP_ORDER if (st.get(k) or 0) >= EQUIP_MIN]


def station_text(c):
    s = c.get("nearest_station")
    if not isinstance(s, dict) or not s.get("name"):
        return ""
    lo = s.get("estimated_walk_minutes_min")
    hi = s.get("estimated_walk_minutes_max")
    name = str(s["name"])
    if lo and hi:
        return f"{name}駅から徒歩{lo}〜{hi}分"
    return f"最寄りは{name}駅"


def clinic_card(c, rank=None):
    """区ページの医院1件。すべて clinic_db.json の実データだけで組み立てる。
    根拠のない推定（fit_for等のAI推定属性）は出さない（2026-07-12の根拠開示方針）。"""
    slug = SLUG_MAP.get(c.get("place_id"), "")
    href = f"../clinics/{quote(slug)}.html" if slug else "#"
    rating = c.get("rating") or 0
    rv = c.get("total_reviews") or 0

    facts = []
    st = station_text(c)
    if st:
        facts.append(("アクセス", st))
    h = hours_facts(c)
    if h.get("weekday_end"):
        line = f"平日は{h['weekday_end']}まで"
        if h.get("night"):
            line += "（夜の時間帯まで診療）"
        facts.append(("診療時間", line))
    week = []
    if h.get("sat") is True:
        week.append("土曜あり")
    if h.get("sat") is False:
        week.append("土曜休み")
    if h.get("sun") is True:
        week.append("日曜あり")
    if week:
        facts.append(("土日", "・".join(week)))
    eq = equip_facts(c)
    if eq:
        facts.append(("公開情報で確認できた設備", "・".join(eq)))
    ft = [t for t in (c.get("focus_treatments") or []) if t][:4]
    if ft:
        facts.append(("力を入れている治療", "・".join(ft)))
    if c.get("doctor_name"):
        facts.append(("院長", str(c["doctor_name"])))
    if c.get("phone"):
        facts.append(("電話", str(c["phone"])))
    if c.get("url"):
        facts.append(("公式サイト", "あり"))

    rows = "".join(
        f'<div class="afact"><dt>{esc(k)}</dt><dd>{esc(v)}</dd></div>' for k, v in facts
    )
    tags = "".join(f'<span class="tag">{esc(t)}</span>'
                   for t in (c.get("reputation_tags") or [])[:5])
    ai = (c.get("ai_summary") or "").strip()
    phil = (c.get("philosophy") or "").strip()
    rk = f'<span class="arank">{rank}</span>' if rank else ""
    return f'''<article class="acard">
  <a class="acard-head" href="{href}">
    {rk}
    <p class="acard-name">{esc(c.get("name",""))}</p>
    <p class="acard-meta">Google ★{rating}（口コミ{rv:,}件） ・ {esc(c.get("address","")[:34])}</p>
  </a>
  {f'<div class="tags">{tags}</div>' if tags else ""}
  {f'<dl class="afacts">{rows}</dl>' if rows else ""}
  {f'<p class="acard-ai">{esc(ai)}</p>' if ai else ""}
  {f'<p class="acard-phil">院の方針として「{esc(phil)}」を掲げています。</p>' if phil else ""}
  <a class="acard-more" href="{href}">{esc(c.get("name",""))}の分析を詳しく見る →</a>
</article>'''


def area_lead(ward, clinics):
    """区の概況。数字はすべてビルド時にDBから数える（手打ちしない）。"""
    n = len(clinics)
    rated = [c for c in clinics if (c.get("total_reviews") or 0) > 0]
    rv = sum(c.get("total_reviews") or 0 for c in clinics)
    deep = sum(1 for c in clinics if c.get("deep_fetched"))
    sts = {}
    for c in clinics:
        s = c.get("nearest_station")
        if isinstance(s, dict) and s.get("name"):
            sts[s["name"]] = sts.get(s["name"], 0) + 1
    top_st = sorted(sts.items(), key=lambda x: -x[1])[:3]
    st_txt = ("最寄り駅で見ると"
              + "、".join(f"{k}駅が{v}院" for k, v in top_st) + "です。") if top_st else ""
    return (
        f"<p>{esc(CITY)}{esc(ward)}で分析対象にしている歯科医院は{n}院です。"
        f"このうち{len(rated)}院にGoogleの口コミがあり、合計{rv:,}件を読み取りました。"
        f"公式サイトまで解析できたのは{deep}院です。{esc(st_txt)}</p>"
        f"<p>ここから先は、診療時間・最寄り駅・公開情報で確認できた設備といった"
        f"「調べれば分かること」を医院ごとに並べています。"
        f"通いやすさは人によって違うので、順番はあくまで参考にしてください。</p>"
    )


def ward_stats(clinics):
    """区内で何院が何を満たすかを数える。表示にも下のFAQにも同じ数字を使う。"""
    n = len(clinics)
    hs = [hours_facts(c) for c in clinics]
    s = {
        "n": n,
        "night": sum(1 for h in hs if h.get("night")),
        "sat": sum(1 for h in hs if h.get("sat") is True),
        "sun": sum(1 for h in hs if h.get("sun") is True),
        "hours_known": sum(1 for h in hs if h),
        "deep": sum(1 for c in clinics if c.get("deep_fetched")),
    }
    eqd = [c for c in clinics if isinstance(c.get("equipment_stars"), dict) and c["equipment_stars"]]
    s["equip_known"] = len(eqd)
    for k in EQUIP_ORDER:
        s[k] = sum(1 for c in eqd if (c["equipment_stars"].get(k) or 0) >= EQUIP_MIN)
    return s


def ward_condition_section(ward, s):
    """条件で絞りたい人向けの実数。断定せず「確認できた範囲」であることを毎回添える。"""
    rows = [
        ("19時30分以降も診療している", s["night"], s["hours_known"]),
        ("土曜日に診療している", s["sat"], s["hours_known"]),
        ("日曜日に診療している", s["sun"], s["hours_known"]),
        ("歯科用CTの導入を確認できた", s["CT"], s["equip_known"]),
        ("個室の案内を確認できた", s["個室"], s["equip_known"]),
        ("駐車場の案内を確認できた", s["駐車場"], s["equip_known"]),
        ("バリアフリーの案内を確認できた", s["バリアフリー"], s["equip_known"]),
    ]
    body = "".join(
        f'<div class="crow"><span class="clabel">{esc(lab)}</span>'
        f'<span class="cval"><b>{v}</b>院 <small>／確認できた{d}院中</small></span></div>'
        for lab, v, d in rows if d
    )
    return (f'<h2>{esc(ward)}で条件から絞る</h2>'
            f'<p>夜間や土日に通えるか、駐車場があるかは、医院選びで最初に効いてくる条件です。'
            f'{esc(ward)}の分析対象{s["n"]}院について、公開情報から確認できた数を並べます。</p>'
            f'<div class="ctable">{body}</div>'
            f'<p class="rnote">分母は、その項目を公開情報から判定できた医院数です。'
            f'「確認できなかった」は「無い」という意味ではありません。'
            f'最新の診療時間は必ず医院にご確認ください。</p>')


def faq_items(ward, s):
    """データから答えられる問いだけをFAQにする（答えられない問いは作らない）。"""
    items = []
    if s["hours_known"]:
        items.append((
            f"{ward}で夜おそくまで診てもらえる歯医者はありますか。",
            f"診療時間を確認できた{s['hours_known']}院のうち、19時30分以降も診療しているのは{s['night']}院でした。"
        ))
        items.append((
            f"{ward}で土日に通える歯医者はありますか。",
            f"土曜日に診療しているのが{s['sat']}院、日曜日が{s['sun']}院です（診療時間を確認できた{s['hours_known']}院中）。"
        ))
    if s["equip_known"]:
        items.append((
            f"{ward}で歯科用CTのある歯医者を知りたいです。",
            f"設備の情報を解析できた{s['equip_known']}院のうち、歯科用CTの導入を確認できたのは{s['CT']}院です。"
            f"確認できなかった医院に無いという意味ではないため、気になる場合は直接お問い合わせください。"
        ))
    items.append((
        "この順番はどうやって決めているのですか。",
        "口コミの内容、院長情報、設備、情報公開の度合い、活動状況を配点にして機械的に並べています。"
        "掲載順が金銭で変わることはありません。治療の優劣を示すものでもありません。"
    ))
    return items


def faq_section(items):
    body = "".join(
        f'<details class="faq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>'
        for q, a in items
    )
    return f'<h2>よくある質問</h2>{body}'


def ward_data_section(ward, clinics, research_ok):
    """市全体のデータ研究記事への文脈リンク。研究記事が実在しないサイトでは節ごと出さない。"""
    if not research_ok:
        return ""
    links_html = "".join(
        f'<li><a href="../research/{slug}.html">{esc(label)}</a></li>'
        for slug, label in research_ok
    )
    return (f'<h2>{esc(ward)}のデータを詳しく見る</h2>'
            f'<p>設備や診療時間の傾向は、市全体のデータをまとめた研究記事で背景まで確認できます。</p>'
            f'<ul class="rlinks">{links_html}</ul>')


def build_page(ward, slug, spots, clinics, research_ok=()):
    n = len(clinics)
    total_rv = sum(c.get("total_reviews") or 0 for c in clinics)
    top = sorted(clinics, key=lambda c: (-(c.get("total_score") or 0), -(c.get("total_reviews") or 0)))[:TOP_N]
    cards = "".join(clinic_card(c, i + 1) for i, c in enumerate(top))
    stats = ward_stats(clinics)
    faqs = faq_items(ward, stats)
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
<meta property="og:image" content="https://{domain}/assets/ogp.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
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
<script type="application/ld+json">{json.dumps({
    "@context": "https://schema.org", "@type": "FAQPage",
    "mainEntity": [
        {"@type": "Question", "name": q,
         "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs
    ],
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
.acard{{display:block;background:#fff;border:1px solid var(--odr-line);border-radius:14px;padding:18px 22px;margin-bottom:14px;color:inherit;}}
.acard-head{{display:block;text-decoration:none;color:inherit;position:relative;}}
.acard-name{{font-weight:700;font-size:1.02rem;color:var(--odr-pine);margin:0 0 4px;padding-right:34px;}}
.acard-meta{{font-size:.78rem;color:var(--odr-ink2);margin:0 0 8px;}}
.arank{{position:absolute;right:0;top:0;font-family:var(--odr-mono);font-size:.78rem;color:var(--odr-terra);border:1px solid var(--odr-line);border-radius:8px;padding:1px 8px;}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;}}
.tag{{background:#eaf2ee;color:var(--odr-pine);font-size:.7rem;font-weight:700;border-radius:999px;padding:3px 10px;}}
.afacts{{margin:0 0 10px;padding:12px 14px;background:#fafbfa;border:1px solid var(--odr-line);border-radius:10px;}}
.afact{{display:flex;gap:10px;font-size:.8rem;padding:3px 0;}}
.afact dt{{flex:0 0 9.5em;color:var(--odr-ink2);}}
.afact dd{{margin:0;flex:1;word-break:auto-phrase;}}
.acard-ai{{font-size:.84rem;color:var(--odr-ink);margin:0 0 6px;word-break:auto-phrase;}}
.acard-phil{{font-size:.8rem;color:var(--odr-ink2);margin:0 0 8px;}}
.acard-more{{font-size:.8rem;color:var(--odr-pine);font-weight:700;text-decoration:none;}}
.acard-more:hover{{text-decoration:underline;}}
.lead p{{font-size:.92rem;margin:0 0 12px;word-break:auto-phrase;}}
.ctable{{background:#fff;border:1px solid var(--odr-line);border-radius:12px;padding:6px 16px;margin-bottom:10px;}}
.crow{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:9px 0;border-bottom:1px solid var(--odr-line);font-size:.86rem;}}
.crow:last-child{{border-bottom:none;}}
.cval{{white-space:nowrap;font-family:var(--odr-mono);}}
.cval b{{font-size:1.05rem;color:var(--odr-pine);}}
.cval small{{color:var(--odr-ink2);font-size:.72rem;}}
.faq{{background:#fff;border:1px solid var(--odr-line);border-radius:10px;padding:12px 16px;margin-bottom:8px;}}
.faq summary{{cursor:pointer;font-weight:700;font-size:.9rem;color:var(--odr-pine);}}
.faq p{{font-size:.86rem;color:var(--odr-ink2);margin:10px 0 0;word-break:auto-phrase;}}
@media(max-width:760px){{.afact{{flex-direction:column;gap:2px;}}.afact dt{{flex:none;font-size:.74rem;}}.crow{{flex-direction:column;gap:2px;}}}}
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
  <div class="lead">{area_lead(ward, clinics)}</div>
  <h2>{esc(ward)}の分析スコア上位{len(top)}院</h2>
  {cards}
  <a class="cta" href="../shindan/index.html?ward={quote(ward)}">症状・希望条件も選んで、{esc(ward)}の医院を絞り込む →</a>
  {ward_condition_section(ward, stats)}
  {faq_section(faqs)}
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
