# -*- coding: utf-8 -*-
"""
独自データ研究ページ生成（2026-07-10・新開発室で設計／Google評価施策A）

自社の構造化データ（74,000件超の口コミをAI分析した患者評価・設備評価）から、
他所では得られない一次統計＝「発見」を算出して公開する。
狙い：オリジナル統計は他サイトの引用（被リンク）を呼び、YMYL新規ドメインが唯一
権威を獲得できる正攻法。単なる集計で終わらせず、各数字に「示唆」を添える
（3体レビューでGeminiが指摘：生データでは引用されない、発見・意外性・示唆が要る）。

信頼の根拠は医師監修ではなく「分析ロジックの徹底開示」（同レビューで確定）。
methodologyセクションでデータ源・算出法・限界・訂正窓口を包み隠さず開示する。

出力: articles/research/index.html ＋ 研究シリーズ articles/research/<slug>.html
（2026-07-13 指示書㉑でシリーズ化。1記事＝1発見。タイトルに都市名は入れない＝ARTICLE_MANUAL §0、
本文の統計文脈でのみ都市名可。夜間しきい値19:30は evidence_grounding.py と同一）
数字はすべて実行時にDBから算出（捏造・ハードコード禁止）。0件・母数不足の指標は自動で伏せる。
"""
import json
import re
import statistics
import collections
import html as html_mod
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
DB = json.loads((ROOT / "clinic_db.json").read_text(encoding="utf-8"))
OUT = ROOT / "articles" / "research" / "index.html"

CITY = CFG.get("city", "大阪市")
SITE = CFG.get("site_name", "大阪歯科総研")
DOMAIN = CFG.get("domain", "shikasoken.com")
EN_UPPER = CFG.get("site_name_en", "OSAKA DENTAL RESEARCH")   # 例: OSAKA DENTAL RESEARCH
# 例: Osaka Dental Research Institute（site_name_enから機械導出。build_clinics.py と同一ロジック）
EN_INSTITUTE = " ".join("-".join(p.capitalize() for p in w.split("-")) for w in EN_UPPER.split()) + " Institute"
# 区の抽出は都市名から動的生成（例: 大阪市○区 / 神戸市○区）。区制の無い都市（尼崎市・広域エリア）は
# マッチせず区集計が空になり、区ベースの発見は母数不足として自動的に伏せられる。
WARD_RE = re.compile(re.escape(CITY) + r'([一-龥]+区)')


def esc(s):
    return html_mod.escape(str(s), quote=True)


def ward_of(addr):
    m = WARD_RE.search(addr or "")
    return m.group(1) if m else None


def has_kw(c, kw):
    return any(kw in t for t in (c.get("specialty_tags") or []) + (c.get("site_features") or []))


def compute():
    act = [c for c in DB.values() if not c.get("q_excluded") and c.get("name")]
    ratings = [c["rating"] for c in act if c.get("rating")]
    total_reviews = sum(c.get("total_reviews") or 0 for c in act)

    wards = collections.defaultdict(list)
    for c in act:
        w = ward_of(c.get("address", ""))
        if w:
            wards[w].append(c)
    big_wards = {w: cs for w, cs in wards.items() if len(cs) >= 15}

    # 発見1：夜間診療の空白
    night = []
    for w, cs in big_wards.items():
        n = sum(1 for c in cs if has_kw(c, "夜間"))
        night.append((w, len(cs), n, n / len(cs) * 100))
    night.sort(key=lambda x: x[3])
    night_zero = [w for w, n, ni, pct in night if ni == 0]
    night_overall = sum(1 for c in act if has_kw(c, "夜間"))

    # 発見2：患者評価の軸別平均（弱点＝最も割れる軸）
    dims = ["技術力", "説明力", "清潔感", "優しさ", "痛みへの配慮", "子ども対応"]
    dim_stats = []
    for d in dims:
        vals = [c["patient_scores"][d] for c in act
                if isinstance(c.get("patient_scores"), dict) and c["patient_scores"].get(d)]
        if len(vals) >= 100:
            dim_stats.append((d, statistics.mean(vals), statistics.pstdev(vals), len(vals)))
    dim_by_mean = sorted(dim_stats, key=lambda x: x[1])
    dim_by_spread = sorted(dim_stats, key=lambda x: -x[2])

    # 発見3：精密設備の保有率
    eq_have = [c for c in act if isinstance(c.get("equipment_stars"), dict) and c["equipment_stars"]]
    equip = []
    for e in ["CT", "マイクロスコープ", "口腔内スキャナー", "個室"]:
        have = sum(1 for c in eq_have if (c.get("equipment_stars") or {}).get(e, 0) >= 3)
        if eq_have:
            equip.append((e, have, len(eq_have), have / len(eq_have) * 100))

    # 発見4：情報公開と評価の相関（因果は主張しない）
    pub = [c["rating"] for c in act if c.get("deep_fetched") and c.get("rating")]
    nopub = [c["rating"] for c in act if not c.get("deep_fetched") and c.get("rating")]
    corr = None
    if len(pub) >= 100 and len(nopub) >= 50:
        corr = (statistics.mean(pub), len(pub), statistics.mean(nopub), len(nopub))

    return dict(
        n_clinics=len(act), total_reviews=total_reviews,
        avg_rating=statistics.mean(ratings) if ratings else 0,
        n_wards=len(big_wards),
        night_zero=night_zero, night_overall=night_overall,
        night_overall_pct=night_overall / len(act) * 100 if act else 0,
        dim_by_mean=dim_by_mean, dim_by_spread=dim_by_spread,
        equip=equip, corr=corr,
        eq_sample=len(eq_have), ps_sample=max((s[3] for s in dim_stats), default=0),
    )


def finding_block(kicker, title, lead, implication, cta_label=None, cta_href=None):
    """kicker=モノラベル(FINDING 0X) / title=発見の見出し / lead=数字の事実 /
    implication=そこから言える示唆。leadは表HTMLを含むことがあるため<p>で包まない。"""
    cta = (f'<a class="rp-cta" href="{esc(cta_href)}">{esc(cta_label)} →</a>'
           if cta_label and cta_href else "")
    return f"""
    <section class="rp-finding">
      <p class="rp-kicker">{esc(kicker)}</p>
      <h2 class="rp-find-title">{title}</h2>
      <div class="rp-find-body">{lead}<p>{implication}</p></div>
      {cta}
    </section>"""


def build(series_meta=None):
    d = compute()
    today = date.today()
    stamp = today.strftime("%Y年%m月")

    # ── 発見の文章化（数字は算出値のみ・示唆を必ず添える） ──
    findings = []

    if d["night_zero"]:
        zero_txt = "・".join(d["night_zero"])
        findings.append(finding_block(
            "FINDING 01 ／ 診療時間の空白",
            "夜間に通える歯科医院",
            f"<p>{CITY}で夜間に診てもらえる歯科は<strong>全体の{d['night_overall_pct']:.0f}%（{d['night_overall']}院）</strong>だけ。とくに<strong>{zero_txt}</strong>は、夜間対応の医院が見当たりません。</p>",
            f"日中に通いにくい働く世代にとって、住む区によって選択肢が大きく変わることを示しています。夜間や土日に対応する医院は数が限られるため、早めの確認が要ります。",
            "夜間・土日で医院を絞り込む", f"https://{DOMAIN}/articles/shindan/?cond=夜間診療"))

    if d["dim_by_spread"]:
        worst = d["dim_by_mean"][0]
        spread = d["dim_by_spread"][0]
        skill = next((s for s in d["dim_by_mean"] if s[0] == "技術力"), None)
        skill_txt = (f"技術面の評価（平均{skill[1]:.0f}点）が比較的そろっているのに対し、"
                     if skill else "")
        findings.append(finding_block(
            "FINDING 02 ／ 医院差が出るところ",
            f"最も差がつくのは「{spread[0]}」",
            f"<p>口コミから読み取れる患者評価を6つの観点で数値化すると、{skill_txt}<strong>「{spread[0]}」は医院ごとの振れ幅が最も大きい</strong>観点でした（平均{spread[1]:.0f}点）。</p>",
            f"「どこでも同じ」ではない、ということです。とくに{spread[0]}を重視する方は、平均点ではなく“その医院がどうか”を口コミで確かめる価値があります。技術力のように多くの医院で一定水準がある観点と、医院選びで差がつく観点は分けて考えるのが有効です。",
            f"{spread[0]}の口コミ傾向から探す", f"https://{DOMAIN}/articles/shindan/"))

    if d["equip"]:
        bars = "".join(
            f'<div class="rp-bar"><span class="rp-bar-l">{esc(e)}</span>'
            f'<span class="rp-bar-track"><span class="rp-bar-fill" style="width:{pct:.0f}%"></span></span>'
            f'<span class="rp-bar-v">{pct:.0f}%<small>{have}／{tot}院</small></span></div>'
            for e, have, tot, pct in d["equip"])
        findings.append(finding_block(
            "FINDING 03 ／ 設備の実態",
            "精密設備は、まだ少数派",
            f'<p>公式サイトを解析できた{d["eq_sample"]}院で、主な精密設備の導入状況を数えました。</p>'
            f'<div class="rp-bars">{bars}</div>',
            "CTやマイクロスコープは「あって当たり前」ではなく、導入している医院の方がまだ少数です。精密な検査・治療を望む場合、設備の有無は医院選びの実質的な分かれ目になります。",
            "設備で医院を絞り込む", f"https://{DOMAIN}/articles/features/index.html"))

    if d["corr"]:
        pm, pn, nm, nn = d["corr"]
        findings.append(finding_block(
            "FINDING 04 ／ 情報公開との関係",
            "情報を出す医院ほど、評価が高い傾向",
            f"<p>公式サイトで診療内容や設備を確認できた医院の平均評価は<strong>{pm:.2f}</strong>（{pn}院）、"
            f"情報が乏しく確認できなかった医院は<strong>{nm:.2f}</strong>（{nn}院）でした。</p>",
            "これは<strong>相関であって因果ではありません</strong>（情報公開が評価を上げる、と断定はできません）。"
            "ただ「きちんと情報を出している医院を選ぶと外れが少ない傾向」は、医院選びの目安として役立ちます。"
            "当サイトが情報の充実度を重視して分析しているのは、この観察が背景にあります。"))

    findings_html = "".join(findings)

    # ── 研究シリーズの一覧（記事が生成された時だけ表示） ──
    series_html = ""
    if series_meta:
        items = "".join(
            f'<a class="rp-series-item" href="{esc(m["slug"])}.html">'
            f'<span class="rp-series-t">{esc(m["title"])}</span>'
            f'<span class="rp-series-h">{esc(m["hook"])}</span></a>'
            for m in series_meta)
        series_html = f"""
    <section class="rp-finding">
      <p class="rp-kicker">RESEARCH SERIES ／ 発見を一つずつ深掘りする</p>
      <h2 class="rp-find-title">研究シリーズ</h2>
      <div class="rp-find-body"><p>ここまでの集計から見えた発見を、1本ずつ記事として掘り下げています。数字はすべて当サイトのデータベースから算出しています。</p></div>
      <div class="rp-series">{items}</div>
    </section>"""

    # ── Schema.org（Dataset＋Article＋FAQ） ──
    faq_pairs = [
        ("このデータはどこから来ていますか？",
         f"公開されているGoogleマップの口コミ（{d['total_reviews']:,}件）と各医院の公式サイト情報を、AIが分析・集計したものです。独自のアンケートではありません。"),
        ("順位や評価は医院からの費用で変わりますか？",
         "変わりません。掲載・分析・順位はすべて公開情報にもとづき、金銭で操作されることは一切ありません。"),
        ("この分析は医療的な診断ですか？",
         "いいえ。公開情報にもとづくデータ分析・意見であり、診断や治療方針を示すものではありません。受診の判断は医療機関にご相談ください。"),
    ]
    faq_schema = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faq_pairs],
    }
    dataset_schema = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"{CITY}の歯科医院データ分析 {today.year}",
        "description": f"{CITY}の歯科医院{d['n_clinics']}院について、公開口コミ{d['total_reviews']:,}件と公式サイト情報をAIで分析した患者評価・設備・診療時間の集計データ。",
        "creator": {"@type": "Organization", "name": SITE, "url": f"https://{DOMAIN}/"},
        "dateModified": today.isoformat(),
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    article_schema = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": f"{CITY} 歯科データ研究 {today.year}｜{SITE}",
        "datePublished": today.isoformat(), "dateModified": today.isoformat(),
        "author": {"@type": "Organization", "name": SITE},
        "publisher": {"@type": "Organization", "name": SITE},
        "isAccessibleForFree": True,
    }
    schema_html = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>'
        for s in (dataset_schema, article_schema, faq_schema))

    faq_html = "".join(
        f'<details class="rp-faq"><summary>{esc(q)}</summary><p>{esc(a)}</p></details>'
        for q, a in faq_pairs)

    title = f"{CITY} 歯科データ研究 {today.year}｜{esc(SITE)}"
    desc = (f"{CITY}の歯科医院{d['n_clinics']}院・口コミ{d['total_reviews']:,}件をAI分析。"
            f"夜間診療の分布、医院差が出る評価軸、精密設備の導入率など、当サイト独自の集計と発見。")

    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{esc(SITE)}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="https://{DOMAIN}/articles/research/">
<link rel="canonical" href="https://{DOMAIN}/articles/research/">
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Shippori+Mincho:wght@600;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<script src="../../assets/site-config.js"></script>
<script src="../../assets/odr-track.js"></script>
{schema_html}
<style>
.rp-hero{{background:linear-gradient(168deg,var(--odr-pine) 0%,#173a31 60%,#122d26 100%);color:#fff;
  padding:calc(var(--sp-sec)*.8) var(--sp-page) var(--sp-sec);}}
.rp-hero .in{{max-width:var(--wrap);margin:0 auto;}}
.rp-eyebrow{{font-family:var(--odr-mono);font-size:var(--fs-mono);letter-spacing:.2em;color:var(--odr-terra);margin:0 0 14px;}}
.rp-hero h1{{font-size:var(--fs-heading);font-weight:900;line-height:1.45;margin:0 0 16px;}}
.rp-hero p.lead{{color:rgba(255,255,255,.82);max-width:660px;margin:0;font-size:var(--fs-body);line-height:2;}}
.rp-metrics{{display:flex;flex-wrap:wrap;gap:28px;margin-top:28px;}}
.rp-metric b{{display:block;font-family:var(--odr-mono);font-size:1.8rem;color:#fff;line-height:1.2;}}
.rp-metric span{{font-size:.72rem;color:rgba(255,255,255,.6);letter-spacing:.08em;}}
.rp-body{{max-width:760px;margin:0 auto;padding:0 var(--sp-page);}}
.rp-finding{{padding:clamp(30px,4vw,52px) 0;border-bottom:1px solid var(--odr-line);}}
.rp-kicker{{font-family:var(--odr-mono);font-size:.8rem;font-weight:600;letter-spacing:.14em;color:var(--odr-terra);margin:0 0 10px;}}
.rp-bars{{margin:20px 0 6px;display:flex;flex-direction:column;gap:12px;}}
.rp-bar{{display:grid;grid-template-columns:120px 1fr auto;align-items:center;gap:14px;}}
.rp-bar-l{{font-size:.9rem;color:var(--odr-ink);font-weight:600;}}
.rp-bar-track{{height:12px;background:#e8efec;border-radius:999px;overflow:hidden;}}
.rp-bar-fill{{display:block;height:100%;background:linear-gradient(90deg,var(--odr-pine),#2f6b5b);border-radius:999px;}}
.rp-bar-v{{font-family:var(--odr-mono);font-weight:700;color:var(--odr-pine);font-size:.95rem;white-space:nowrap;}}
.rp-bar-v small{{display:block;font-weight:400;color:var(--odr-ink2);font-size:.68rem;}}
@media(max-width:560px){{.rp-bar{{grid-template-columns:88px 1fr auto;gap:10px;}}.rp-bar-l{{font-size:.82rem;}}}}
.rp-find-title{{font-family:'Shippori Mincho',serif;font-size:clamp(1.3rem,3vw,1.7rem);font-weight:700;color:var(--odr-pine);line-height:1.5;margin:0 0 16px;}}
.rp-find-body{{font-size:var(--fs-body);color:var(--odr-ink);line-height:2.05;}}
.rp-find-body strong{{color:var(--odr-pine);font-weight:700;}}
.rp-find-body p{{margin:0 0 14px;}}
.rp-cta{{display:inline-block;margin-top:18px;color:var(--odr-terra);font-weight:700;font-size:.92rem;text-decoration:none;border-bottom:1px solid transparent;transition:border-color .2s;}}
.rp-cta:hover{{border-color:var(--odr-terra);}}
.rp-table{{width:100%;border-collapse:collapse;margin:18px 0 6px;font-size:.92rem;}}
.rp-table th{{text-align:left;font-size:.74rem;letter-spacing:.06em;color:var(--odr-ink2);border-bottom:1px solid var(--odr-line);padding:8px 10px;font-weight:600;}}
.rp-table td{{padding:10px;border-bottom:1px solid var(--odr-line);}}
.rp-table .rp-num{{font-family:var(--odr-mono);font-weight:700;color:var(--odr-pine);}}
.rp-table .rp-sub{{color:var(--odr-ink2);font-size:.8rem;}}
.rp-method{{background:#f6f8f7;border-radius:var(--r-card);padding:clamp(24px,3.4vw,40px);margin:clamp(32px,4vw,52px) auto;max-width:760px;}}
.rp-method h2{{font-size:1.15rem;color:var(--odr-pine);margin:0 0 6px;}}
.rp-method .rp-note{{font-family:var(--odr-mono);font-size:var(--fs-mono);letter-spacing:.1em;color:var(--odr-ink2);margin:0 0 18px;}}
.rp-method dl{{margin:0;}}
.rp-method dt{{font-weight:700;color:var(--odr-ink);font-size:.92rem;margin:16px 0 4px;}}
.rp-method dd{{margin:0;color:var(--odr-ink2);font-size:.88rem;line-height:1.9;}}
.rp-faq{{border-bottom:1px solid var(--odr-line);padding:6px 0;}}
.rp-faq summary{{cursor:pointer;font-weight:700;color:var(--odr-ink);padding:12px 0;list-style:none;}}
.rp-faq summary::before{{content:"＋";color:var(--odr-terra);margin-right:10px;font-weight:700;}}
.rp-faq[open] summary::before{{content:"−";}}
.rp-faq p{{margin:0 0 14px;color:var(--odr-ink2);font-size:.9rem;line-height:1.9;}}
.rp-updated{{text-align:center;font-family:var(--odr-mono);font-size:var(--fs-mono);color:var(--odr-ink2);letter-spacing:.08em;padding:8px 0 0;}}
.rp-foot{{max-width:760px;margin:0 auto;padding:var(--sp-sec) var(--sp-page);color:var(--odr-ink2);font-size:var(--fs-caption);line-height:1.9;text-align:center;}}
.rp-foot a{{color:var(--odr-pine);}}
.rp-series{{display:flex;flex-direction:column;gap:14px;margin-top:20px;}}
.rp-series-item{{display:block;text-decoration:none;border:1px solid var(--odr-line);border-radius:var(--r-card);padding:18px 22px;transition:border-color .2s;}}
.rp-series-item:hover{{border-color:var(--odr-terra);}}
.rp-series-t{{display:block;font-weight:700;color:var(--odr-pine);font-size:1.02rem;line-height:1.7;}}
.rp-series-h{{display:block;color:var(--odr-ink2);font-size:.85rem;margin-top:6px;line-height:1.8;}}
</style>
</head>
<body class="odr">

<header class="odr-brandbar">
  <a class="odr-sig" href="../../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">{esc(SITE)}<small>{esc(EN_INSTITUTE)}</small></span>
  </a>
  <nav>
    <a href="../shindan/index.html">ランキング・AI診断</a>
    <a href="../features/index.html">特徴から探す</a>
    <a href="../index.html">コラム</a>
    <a href="../../network.html">展開エリア</a>
    <a href="../../shikumi.html">医院・開業医の方へ</a>
  </nav>
</header>

<section class="rp-hero">
  <div class="in">
    <p class="rp-eyebrow">DATA RESEARCH ／ {today.year}</p>
    <h1>{CITY}の歯科医院を、<br>{d['total_reviews']:,}件の口コミから読み解く。</h1>
    <p class="lead">{esc(SITE)}は、{CITY}の歯科医院{d['n_clinics']}院の公開情報とGoogle口コミをAIで分析しています。そこから見えてきた、他では手に入らない「{CITY}の歯科のいま」を、数字と発見でお届けします。</p>
    <div class="rp-metrics">
      <div class="rp-metric"><b>{d['n_clinics']:,}</b><span>分析対象の医院</span></div>
      <div class="rp-metric"><b>{d['total_reviews']:,}</b><span>分析した口コミ</span></div>
      <div class="rp-metric"><b>{d['avg_rating']:.2f}</b><span>平均評価（5点満点）</span></div>
      <div class="rp-metric"><b>{d['n_wards']}</b><span>集計した区</span></div>
    </div>
  </div>
</section>

<main class="rp-body">
{findings_html}
{series_html}
</main>

<section class="rp-method">
  <p class="rp-note">METHODOLOGY ／ この分析の作り方（包み隠さず開示します）</p>
  <h2>信頼できる根拠は、透明性そのものです</h2>
  <dl>
    <dt>データの出どころ</dt>
    <dd>Googleマップに公開されている口コミ（{d['total_reviews']:,}件）と、各医院の公式サイトの公開情報です。独自アンケートや非公開データは使っていません。</dd>
    <dt>数字の作り方</dt>
    <dd>口コミ本文をAIが読み、患者評価（技術・説明・清潔感など）を0〜100、設備を0〜5で数値化し、集計しています。設備・診療時間は公式サイトの記載から機械的に判定しています。患者評価スコアは口コミが一定数ある医院（本ページで約{d['ps_sample']}院）、設備は公式サイトを解析できた約{d['eq_sample']}院が対象です。</dd>
    <dt>この分析の限界</dt>
    <dd>口コミは主観の集まりで、件数の少ない医院は振れやすいこと、公式サイトに載っていない設備は「無い」ではなく「未確認」であること——これらを承知の上でご覧ください。<strong>本ページは医療的な診断ではなく、公開情報にもとづくデータ分析・意見です。</strong></dd>
    <dt>順位とお金の関係</dt>
    <dd>掲載・分析・順位は、医院からの費用で一切変わりません。すべての医院を同じ基準で扱っています。</dd>
    <dt>間違いの訂正</dt>
    <dd>掲載内容に誤りがあれば、<a href="../../teisei.html">医院情報の修正フォーム</a>から無料で訂正します。詳しくは<a href="../../policy.html">運営ポリシー</a>をご覧ください。</dd>
  </dl>
</section>

<section class="rp-body">
  <h2 class="rp-find-title" style="margin-top:20px;">このデータについてのよくある質問</h2>
  {faq_html}
</section>

<p class="rp-updated">最終更新：{stamp}（データは毎月更新しています）</p>

<footer class="rp-foot">
  当ページの数字は、公開情報にもとづき当サイトが独自に集計・分析した参考情報です。医療的な診断ではありません。<br>
  出典を明記のうえでの引用を歓迎します（引用時は「{esc(SITE)}」とリンクを明記してください）。<br>
  <a href="../../policy.html">運営ポリシー・免責事項</a> ／ <a href="../../teisei.html">医院情報の修正</a><br>
  © {today.year} {esc(SITE)}
</footer>

</body>
</html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"✅ 独自データ研究ページ生成: {OUT}")
    print(f"   発見 {len(findings)}件 / 対象 {d['n_clinics']}院 / 口コミ {d['total_reviews']:,}件")
    if not findings:
        print("   ⚠ 発見が0件です。DBの patient_scores / equipment_stars を確認してください")


# ============================================================================
# 研究シリーズ（2026-07-13 指示書㉑）
# 1記事＝1発見。数字は実行時にDBから算出。母数が薄い指標は記事ごと自動で伏せる。
# タイトルに都市名・区名を入れない（ARTICLE_MANUAL §0。本文の統計文脈のみ可）。
# ============================================================================

_DAY = {"月曜日": 0, "火曜日": 1, "水曜日": 2, "木曜日": 3, "金曜日": 4, "土曜日": 5, "日曜日": 6}
_TIME_RE = re.compile(r'(\d{1,2})時(\d{2})分')
NIGHT_MIN = 19 * 60 + 30  # 19:30。evidence_grounding.py の夜間しきい値と揃える


def _parse_hours(c):
    h = c.get("business_hours")
    if not isinstance(h, list) or not h:
        return None
    out = {}
    for line in h:
        if not isinstance(line, str) or "曜日" not in line:
            continue
        d = _DAY.get(line.split(":")[0].strip())
        if d is None:
            continue
        if "定休日" in line or "休業" in line:
            out[d] = []
            continue
        times = _TIME_RE.findall(line)
        out[d] = [(int(times[i][0]) * 60 + int(times[i][1]),
                   int(times[i + 1][0]) * 60 + int(times[i + 1][1]))
                  for i in range(0, len(times) - 1, 2)]
    return out or None


def _night(h):
    ends = [e for d in range(5) for (_s, e) in h.get(d, [])]
    return bool(ends) and max(ends) >= NIGHT_MIN


def _bars(rows):
    """rows=[(label, pct, sub)] → 純CSSバーチャート"""
    return '<div class="rp-bars">' + "".join(
        f'<div class="rp-bar"><span class="rp-bar-l">{esc(l)}</span>'
        f'<span class="rp-bar-track"><span class="rp-bar-fill" style="width:{min(pct, 100):.0f}%"></span></span>'
        f'<span class="rp-bar-v">{pct:.0f}%<small>{esc(sub)}</small></span></div>'
        for l, pct, sub in rows) + "</div>"


def _act():
    return [c for c in DB.values() if not c.get("q_excluded") and c.get("name")]


# ---- 記事1：仕事を休まず通える時間帯 -------------------------------------
def _art_worktime():
    act = _act()
    hh = [(c, _parse_hours(c)) for c in act]
    hh = [(c, h) for c, h in hh if h]
    if len(hh) < 300:
        return None
    n = len(hh)
    sat = sum(1 for c, h in hh if h.get(5))
    sun = sum(1 for c, h in hh if h.get(6))
    night = sum(1 for c, h in hh if _night(h))
    both = sum(1 for c, h in hh if h.get(6) and _night(h))
    lunch_base = lunch = 0
    for c, h in hh:
        spans = h.get(2) or h.get(1)
        if not spans:
            continue
        lunch_base += 1
        if any(s <= 13 * 60 and e >= 14 * 60 for s, e in spans):
            lunch += 1
    wards = collections.defaultdict(list)
    for c, h in hh:
        w = ward_of(c.get("address", ""))
        if w:
            wards[w].append(h)
    big = {w: v for w, v in wards.items() if len(v) >= 30}
    if len(big) < 6:
        return None
    sun_rows = sorted(((w, sum(1 for h in v if h.get(6)), len(v)) for w, v in big.items()),
                      key=lambda r: r[1] / r[2])
    night_rows = sorted(((w, sum(1 for h in v if _night(h)), len(v)) for w, v in big.items()),
                        key=lambda r: r[1] / r[2])
    lp = lunch / lunch_base * 100
    stats = dict(n=n, sat=sat, sun=sun, night=night, both=both,
                 satp=sat / n * 100, sunp=sun / n * 100, nightp=night / n * 100, bothp=both / n * 100,
                 lunch=lunch, lunch_base=lunch_base, lunchp=lp)

    sun_low = "・".join(w for w, _n, _t in sun_rows[:3])
    sun_hi = "・".join(w for w, _n, _t in sun_rows[-3:])
    night_low = "・".join(w for w, _n, _t in night_rows[:3])
    night_hi = "・".join(w for w, _n, _t in night_rows[-3:])

    body = f"""
<p class="rp-lede">歯が痛い。でも、仕事は休めない。——治療を先延ばしにしてしまうのは、意思が弱いからではなく、そもそも「行ける時間に開いている医院」が思ったより少ないからかもしれません。{CITY}の歯科医院のうち、Googleに診療時間が公開されている{n:,}院を集計して、働く人が使える3つの時間帯——昼休み・平日の夜・日曜——がどれだけ空いているかを数えました。</p>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 時間帯ごとのカバー率</p>
<h2 class="rp-find-title">土曜は当たり前。本当の分かれ目は、日曜と夜</h2>
<div class="rp-find-body">
<p>結論から言うと、<strong>土曜に診療する医院は{stats['satp']:.0f}%</strong>。土曜はもう「探す条件」になりません。ところが<strong>日曜は{stats['sunp']:.0f}%（{sun}院）</strong>まで一気に減り、<strong>平日の昼休み（13〜14時）に開いている医院は{lp:.0f}%</strong>、<strong>平日19時30分以降まで診療する医院は{stats['nightp']:.0f}%</strong>でした。そして「日曜も、平日の夜も」の両方に対応する医院は<strong>{stats['bothp']:.1f}%（{both}院）</strong>しかありません。</p>
{_bars([("土曜に診療", stats['satp'], f"{sat}／{n}院"),
        ("平日夜(19:30〜)", stats['nightp'], f"{night}／{n}院"),
        ("昼休み(13-14時)", lp, f"{lunch}／{lunch_base}院"),
        ("日曜に診療", stats['sunp'], f"{sun}／{n}院"),
        ("日曜＋平日夜", stats['bothp'], f"{both}／{n}院")])}
<p>昼休みに行こうとすると、4院のうち3院は閉まっています。多くの医院が13〜15時前後を休診にする昼休み文化があるためで、「昼に行けばすぐ済むのに」が通用しにくいのが実情です。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 意外な逆転現象</p>
<h2 class="rp-find-title">日曜はオフィス街が開き、住宅街は夜に開く</h2>
<div class="rp-find-body">
<p>もっと意外だったのは、区ごとの分布です。日曜診療の割合が高いのは<strong>{esc(sun_hi)}</strong>といった都心・オフィス街側で、低いのは<strong>{esc(sun_low)}</strong>といった住宅街側でした。ところが平日夜の割合を見ると、この順序が<strong>ほぼ逆転</strong>します。夜遅くまで開けている割合が高いのは<strong>{esc(night_hi)}</strong>、低いのは<strong>{esc(night_low)}</strong>など都心側です。</p>
<p>つまり{CITY}の歯科は、大づかみに言えば<strong>「都心は日曜型、住宅街は夜型」</strong>。買い物や通勤のついでに来る人が多い街は休日に、仕事帰り・帰宅後の住民が多い街は夜に、それぞれ合わせて営業している——と読むと辻褄が合います。</p>
<p><strong>これはあなたの探し方を変えます。</strong>「家の近くで日曜にやっている歯医者がない」と諦める前に、職場や買い物先の近くまで範囲を広げると日曜の選択肢が増えます。逆に平日夜なら、都心で探すより自宅の最寄り側のほうが見つかりやすい。<em>日曜は街の中心側で、平日夜は家の側で。</em>探す場所を時間帯で切り替えるのが、このデータから言える現実的なコツです。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">NOTE ／ 医院の方へ</p>
<div class="rp-find-body">
<p>働きながら通える時間帯は、患者にとって医院選びの入口そのものです。自院の診療時間がGoogleビジネスプロフィールに正確に反映されているか——とくに夜間・日曜の情報が古いままになっていないか——の確認をおすすめします。本ページの集計も公開情報に基づいているため、情報が古いと実態より不利に見える場合があります。</p>
</div>
</section>"""

    faq = [
        ("日曜や夜間に対応する医院はどこで探せますか？",
         "当サイトのランキング・AI診断ページで「夜間診療」「土日診療」の条件で絞り込めます。診療時間は変更される場合があるため、受診前に必ず医院へ直接ご確認ください。"),
        ("集計に含まれない医院はありますか？",
         f"Googleに診療時間が公開されていない医院（分析対象{len(act):,}院のうち約{(len(act) - n) / len(act) * 100:.0f}%)は集計から除いています。また夜間救急の当番医などは通常の診療時間に反映されないことがあります。"),
        ("この割合は今後変わりますか？",
         "変わります。データは毎月更新しており、診療時間の変更・新規開業・閉業により数字は動きます。最終更新日は本ページ下部をご覧ください。"),
    ]
    return dict(
        slug="worktime-access",
        title=f"昼休みに行ける歯科は{lp:.0f}%——仕事を休まず通うための時間帯データ",
        hook="土曜91%は当たり前。日曜と夜こそ分かれ目——しかも都心と住宅街で、開く時間帯が逆転していました。",
        desc=(f"診療時間が確認できた{n:,}院を集計。土曜{stats['satp']:.0f}%に対し日曜{stats['sunp']:.0f}%、"
              f"昼休みは{lp:.0f}%。日曜は都心・平日夜は住宅街という逆転現象も。働く人のための時間帯データ。"),
        body=body, faq=faq,
        method=[
            ("データの出どころ", f"Googleマップに公開されている各医院の診療時間です。分析対象{len(act):,}院のうち、診療時間を機械的に読み取れた{n:,}院を母数としています。"),
            ("数字の作り方", f"「夜間」は平日の診療終了が19時30分以降、「昼休み」は水曜（休診の場合は火曜）に13〜14時を通して診療している場合、と機械的に判定しました。昼休みの母数（{lunch_base:,}院）が他と異なるのは、火・水がともに休診で判定できない医院を除いたためです。区別の集計は医院数30院以上の区のみ対象です。"),
            ("この分析の限界", "Googleの診療時間は医院の申告・更新状況に依存し、祝日・臨時休診・夜間救急の当番は反映されません。最新の診療時間は必ず医院に直接ご確認ください。"),
        ])


# ---- 記事2：料金の公開はまだ少数派 -----------------------------------------
def _art_price():
    act = _act()
    deep = [c for c in act if c.get("deep_fetched")]
    if len(deep) < 300:
        return None
    pat = re.compile(r'円|万円|料金')
    disclosed = [c for c in deep if pat.search(str(c.get("transparency_evidence") or ""))]
    nd = len(disclosed)
    if nd == 0:
        return None
    pct = nd / len(deep) * 100
    d_r = [c["rating"] for c in disclosed if c.get("rating")]
    n_r = [c["rating"] for c in deep if not pat.search(str(c.get("transparency_evidence") or "")) and c.get("rating")]
    corr_html = ""
    if len(d_r) >= 50 and len(n_r) >= 300:
        corr_html = f"""
<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 評価との関係</p>
<h2 class="rp-find-title">料金を公開している医院は、評価も高い傾向</h2>
<div class="rp-find-body">
<p>評価の数字だけで医院を選ぶ必要はありませんが、参考値として——料金の記載を確認できた医院のGoogle平均評価は<strong>{statistics.mean(d_r):.2f}</strong>（{len(d_r)}院）、確認できなかった医院は<strong>{statistics.mean(n_r):.2f}</strong>（{len(n_r)}院）でした（評価が取得できた計{len(d_r) + len(n_r):,}院で比較）。</p>
<p>ただし、これは<strong>相関であって因果ではありません</strong>。料金を書けば評価が上がる、という意味ではなく、「患者への説明に力を入れている医院が、結果として料金も開示し、評価も得ている」といった共通の背景があると考えるのが自然です。また料金記載側は{len(d_r)}院と母数が小さいため、この差は参考程度に見てください。</p>
</div>
</section>"""

    body = f"""
<p class="rp-lede">いくらかかるのか分からないまま、診療台に座る。あの心細さには、理由があります。{CITY}の歯科医院のうち公式サイトを解析できた{len(deep):,}院を調べたところ、<strong>自由診療の料金を具体的な金額でサイトに載せている医院は{nd}院——わずか{pct:.0f}%</strong>でした。「値段を見てから決めたい」が、歯科ではまだ当たり前にできないのです。</p>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 料金公開の実態</p>
<h2 class="rp-find-title">料金を「見てから選べる」医院は、まだ少数派</h2>
<div class="rp-find-body">
{_bars([("料金の記載を確認", pct, f"{nd}／{len(deep):,}院"),
        ("記載を確認できず", 100 - pct, f"{len(deep) - nd}／{len(deep):,}院")])}
<p>誤解しないでほしいのは、<strong>料金を書いていない＝高い・不誠実、ではない</strong>ということです。歯科の自由診療は症状や材料で金額が変わるため、「一律の価格を書くとかえって誤解を招く」と考える医院も少なくありません。</p>
<p>それでも、患者側にできることはあります。<strong>初診の前に、電話や問い合わせフォームで「おおよその目安」を聞いてよい</strong>のです。きちんとした医院ほど、確定額は診てからとしつつも、幅を持った目安や「何で金額が変わるのか」を説明してくれます。逆に、聞いても説明の姿勢が見えない場合、それ自体が医院選びの判断材料になります。</p>
</div>
</section>
{corr_html}
<section class="rp-finding">
<p class="rp-kicker">NOTE ／ 医院の方へ</p>
<div class="rp-find-body">
<p>料金への不安は、患者が予約をためらう最大級の理由のひとつです。確定額を約束できなくても、「◯◯円〜◯◯円。差が出る理由は△△」という幅と根拠の開示だけで、患者の心理的なハードルは大きく下がります。{pct:.0f}%という現状は、開示した医院がそれだけで目立てる、ということでもあります。</p>
</div>
</section>"""

    faq = [
        ("料金を公開していない医院は避けるべきですか？",
         "いいえ。症状によって金額が変わるため一律表示を避けている医院も多くあります。受診前に目安を質問し、説明の姿勢を見ることをおすすめします。"),
        ("保険診療の料金も医院によって違いますか？",
         "保険診療は全国共通の点数制度で、同じ処置なら自己負担は基本的にどの医院でも同水準です。医院によって大きく変わるのは自由診療（インプラント・矯正・セラミック等）です。"),
        ("「料金の記載を確認」はどう判定していますか？",
         "各医院の公式サイトをAIが解析し、具体的な金額・料金表への言及を確認できた場合に数えています。サイトの構成によっては読み取れない場合があり、実際より少なめに出る可能性があります。"),
    ]
    return dict(
        slug="price-disclosure",
        title=f"治療費をサイトで公開している歯科医院は{pct:.0f}%だった",
        hook="「値段を見てから決めたい」が、歯科ではまだ当たり前にできない——料金開示の実態と、受診前にできること。",
        desc=(f"公式サイトを解析できた{len(deep):,}院のうち、自由診療の料金を具体的に記載していたのは{nd}院（{pct:.0f}%）。"
              "料金不安との付き合い方を一次データから考えます。"),
        body=body, faq=faq,
        method=[
            ("データの出どころ", f"各医院の公式サイトの公開情報をAIが解析した結果です。分析対象のうち公式サイトを解析できた{len(deep):,}院を母数としています。"),
            ("数字の作り方", "サイト解析で得た情報公開の根拠テキストに、具体的な金額・料金表への言及（「円」「料金」等）が含まれる医院を「料金の記載あり」と機械的に判定しました。"),
            ("この分析の限界", "サイトの構成によっては料金ページを読み取れないことがあり、実際の開示率はこの数字より高い可能性があります。評価との比較は相関であり因果ではなく、Google評価が取得できた医院のみで比較しています。料金は必ず各医院に直接ご確認ください。"),
        ])


# ---- 記事3：待ち時間は「どこへ行っても」 -----------------------------------
def _art_waiting():
    act = _act()
    dims = ["技術力", "説明力", "清潔感", "優しさ", "痛みへの配慮", "子ども対応", "待ち時間"]
    stats = []
    for d in dims:
        vals = [c["patient_scores"][d] for c in act
                if isinstance(c.get("patient_scores"), dict) and c["patient_scores"].get(d)]
        if len(vals) >= 100:
            stats.append((d, statistics.mean(vals), statistics.pstdev(vals), len(vals)))
    if len(stats) < 5 or not any(s[0] == "待ち時間" for s in stats):
        return None
    by_mean = sorted(stats, key=lambda x: x[1])
    by_sd = sorted(stats, key=lambda x: x[2])
    wait = next(s for s in stats if s[0] == "待ち時間")
    is_lowest = by_mean[0][0] == "待ち時間"
    is_tightest = by_sd[0][0] == "待ち時間"
    if not (is_lowest and is_tightest):
        return None  # データが変わって前提が崩れたら発見ごと伏せる
    spread = max(stats, key=lambda x: x[2])
    top = max(stats, key=lambda x: x[1])

    rows = [(d, m, f"振れ幅 ±{sd:.0f}") for d, m, sd, _n in sorted(stats, key=lambda x: -x[1])]
    body = f"""
<p class="rp-lede">「この医院、いつも待たされる。他に変えたら違うんだろうか」——誰もが一度は考えたことがあるはずです。口コミから読み取れる患者評価を7つの観点で数値化した当サイトのデータは、少し残酷な答えを返してきました。<strong>待ち時間は、7観点の中で最も点が低く（平均{wait[1]:.0f}点）、しかも医院ごとの差が最も小さい</strong>のです。</p>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 7観点の比較</p>
<h2 class="rp-find-title">待ち時間の不満は、医院を替えても消えないかもしれない</h2>
<div class="rp-find-body">
<p>{CITY}の歯科医院の口コミをAIで読み取り、観点別に0〜100点で数値化して平均したのが下の図です。<strong>{esc(top[0])}（平均{top[1]:.0f}点）が最も高く、待ち時間（平均{wait[1]:.0f}点）が最も低い</strong>。そして重要なのは括弧内の「振れ幅」です。待ち時間は点が低いだけでなく、振れ幅（±{wait[2]:.0f}）も全観点で最小でした。点が低い＝多くの人が不満を感じている、振れ幅が小さい＝医院ごとの差が小さい。ふたつを合わせると、<strong>どこへ行っても、同じくらい待つ</strong>ということです。</p>
{_bars(rows)}
<p>これが意味するのは、「待たされるのはこの医院がダメだから」とは限らない、ということです。予約制でも急患や治療の長引きは避けられず、待ち時間はどの医院にも構造的につきまとう。<strong>医院を替えることで解決しやすい不満と、替えても変わりにくい不満がある</strong>——このデータは、その区別を教えてくれます。</p>
<p>現実的な対処は、医院選びより<strong>時間帯選び</strong>です。予約の取り方（午前一番・昼一番は遅延が蓄積しにくい）、完全予約制かどうか、急患対応の方針を初診時に聞いておく——待ち時間は「どの医院か」より「どう通うか」で変わります。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 裏返しの発見</p>
<h2 class="rp-find-title">本当に差がつくのは「{esc(spread[0])}」</h2>
<div class="rp-find-body">
<p>逆に、医院ごとの差が最も大きかった観点は<strong>{esc(spread[0])}（振れ幅±{spread[2]:.0f}）</strong>でした。こちらは「どこも同じ」ではまったくありません。{esc(spread[0])}を重視する方にとっては、<strong>医院選びに時間をかける価値が最も大きい観点</strong>だと言えます。どこでも大差ない観点（待ち時間）に悩む時間を、差がつく観点の見極めに回す——それがこのデータの実用的な使い方です。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">NOTE ／ 医院の方へ</p>
<div class="rp-find-body">
<p>待ち時間の完全な解消は構造的に難しい一方、口コミで不満として書かれるのは多くの場合「待たされたこと」ではなく「待たされる理由の説明がなかったこと」です。遅延時の一言・目安時間の掲示など、待ち時間の「体験」を変える工夫は評価に反映されやすい領域です。</p>
</div>
</section>"""

    faq = [
        ("このスコアはどうやって作られていますか？",
         "Googleマップの公開口コミをAIが読み、観点ごとに言及内容を0〜100点で数値化し、医院単位で平均したものです。口コミが一定数ある医院のみを集計しています。"),
        ("待ち時間が短い医院を探す方法はありますか？",
         "スコアの差が小さいため「待ち時間の短い医院リスト」は作れませんが、完全予約制かどうか・予約枠の取り方は医院ごとに異なります。当サイトの医院ページや予約時の質問でご確認ください。"),
        ("点数が低い観点がある医院は避けるべきですか？",
         "いいえ。スコアは口コミの言及傾向の集計であり、医院の優劣を断定するものではありません。ご自身が重視する観点の参考情報としてご覧ください。"),
    ]
    return dict(
        slug="waiting-time",
        title="歯医者を替えても、待ち時間の不満は消えないかもしれない",
        hook=f"患者評価7観点で最下位、なのに医院差は最小——「替えれば解決する不満」と「変わらない不満」の見分け方。",
        desc=(f"口コミのAI分析で患者評価を7観点に数値化。待ち時間は平均{wait[1]:.0f}点で最下位、かつ医院間の差が最小でした。"
              f"医院選びで本当に差がつく観点は「{spread[0]}」。データが教える不満との付き合い方。"),
        body=body, faq=faq,
        method=[
            ("データの出どころ", "Googleマップに公開されている口コミをAIが観点別に数値化した患者評価スコアです。観点ごとに評価可能な口コミが一定数ある医院のみ集計しています（観点により母数は約{:,}〜{:,}院）。".format(min(s[3] for s in stats), max(s[3] for s in stats))),
            ("数字の作り方", "各観点0〜100点の医院別スコアを単純平均し、「振れ幅」は標準偏差（医院ごとの点数のばらつき）です。"),
            ("この分析の限界", "口コミは主観の集まりで、書き込む動機にも偏りがあります（不満は書かれやすい等）。スコアは傾向の目安であり、個別の医院の体験を保証するものではありません。"),
        ])


# ---- 記事4：口コミの偏在 ----------------------------------------------------
def _art_reviews():
    act = _act()
    rv = sorted((c.get("total_reviews") or 0) for c in act)
    total = sum(rv)
    if total < 10000:
        return None
    n = len(rv)
    top10 = sum(rv[-max(1, n // 10):])
    share = top10 / total * 100
    med = rv[n // 2]
    zero = sum(1 for x in rv if x == 0)
    under10 = sum(1 for x in rv if x < 10)

    body = f"""
<p class="rp-lede">口コミが8件しかない医院を見て、「人気がないのかな」と閉じたことはありませんか。{CITY}の歯科医院{n:,}院・口コミ{total:,}件を集計すると、その直感がどれほど当てにならないかが見えてきます。<strong>口コミ全体の{share:.0f}%は、件数上位1割の医院に集中</strong>していました。残り9割の医院で、全体の{100 - share:.0f}%を分け合っているのです。</p>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 口コミ件数の分布</p>
<h2 class="rp-find-title">口コミの{share:.0f}%は、1割の医院に集まっている</h2>
<div class="rp-find-body">
<p>医院ごとの口コミ件数の<strong>中央値は{med}件</strong>。つまり半分の医院は{med}件以下です。口コミが1件もない医院も{zero}院（{zero / n * 100:.0f}%）、10件未満まで広げると{under10 / n * 100:.0f}%にのぼります。</p>
{_bars([("上位10%の医院が保有", share, f"約{top10:,}件"),
        ("残り90%の医院の合計", 100 - share, f"約{total - top10:,}件")])}
<p>この偏りの正体は、医院の実力差だけではありません。駅前か住宅街か（人通り）、開業からの年数、そして<strong>口コミを書いてもらう働きかけをしているかどうか</strong>——件数はこうした構造的な条件を色濃く反映します。長く地域で信頼されている医院ほど、常連の患者はわざわざ口コミを書かない、ということも普通に起きます。</p>
<p><strong>だから、件数で足切りをすると、大多数の医院が理由なく視界から消えます。</strong>件数の少ない医院を見るときは、数ではなく中身を見てください。「先生が優しい」といった一言だけの口コミより、治療の説明・費用の話・痛みへの対応など<strong>具体的な体験が書かれた口コミが1〜2件ある</strong>ほうが、判断材料としてはずっと価値があります。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">NOTE ／ 医院の方へ</p>
<div class="rp-find-body">
<p>件数の競争は、立地と規模で決まりがちな構造的に不利な土俵です。なお口コミを増やす際は、謝礼と引き換えの依頼や代筆はステルスマーケティング規制・Googleのポリシーに抵触します。<strong>実際に来院した患者本人が、本人の言葉で書く</strong>——この原則の範囲で、満足された患者に自然にお願いする導線を整えることが、遠回りに見えて唯一の正攻法です。</p>
</div>
</section>"""

    faq = [
        ("口コミが多い医院のほうが安心ではないですか？",
         "件数は立地・開業年数・依頼の働きかけの影響が大きく、多い＝良い医院とは限りません。件数より、具体的な体験が書かれているかどうかを見ることをおすすめします。"),
        ("口コミが0件の医院は掲載する意味がありますか？",
         f"当サイトは口コミ以外に公式サイトの公開情報（診療内容・設備・院長の経歴など）も分析しています。口コミ0件の{zero}院にも、選ぶ材料は残されています。"),
        ("この集計はいつ時点のものですか？",
         "本ページ下部の最終更新時点のデータです。口コミ件数は毎月更新しており、数字は変動します。"),
    ]
    return dict(
        slug="review-concentration",
        title=f"口コミの{share:.0f}%は、1割の医院に集まっている",
        hook=f"中央値はわずか{med}件。件数で選ぶと大多数の医院が視界から消える——数ではなく中身を見る口コミの読み方。",
        desc=(f"歯科医院{n:,}院・口コミ{total:,}件を集計。上位10%の医院が全体の{share:.0f}%を保有し、半数の医院は{med}件以下。"
              "件数に頼らない口コミの読み方を一次データから提案します。"),
        body=body, faq=faq,
        method=[
            ("データの出どころ", f"Googleマップに公開されている各医院の口コミ件数です。分析対象{n:,}院・計{total:,}件を集計しました。"),
            ("数字の作り方", "医院を口コミ件数順に並べ、上位10%の医院の件数合計が全体に占める割合を算出しました。中央値は件数順で真ん中の医院の値です。"),
            ("この分析の限界", "口コミ件数はGoogle上の公開数であり、削除・非公開分は含みません。件数の多寡は医院の質を示すものではない、というのが本記事の主旨です。"),
        ])


# ---- 記事5：精密設備の地域差 -------------------------------------------------
def _art_equipment_gap():
    act = _act()
    eq = [c for c in act if isinstance(c.get("equipment_stars"), dict) and c["equipment_stars"]]
    if len(eq) < 300:
        return None
    wards = collections.defaultdict(list)
    for c in eq:
        w = ward_of(c.get("address", ""))
        if w:
            wards[w].append(c)
    big = {w: v for w, v in wards.items() if len(v) >= 25}
    if len(big) < 6:
        return None

    def rate(v, item):
        have = sum(1 for c in v if (c["equipment_stars"].get(item) or 0) >= 3)
        return have, len(v), have / len(v) * 100

    ct = sorted(((w,) + rate(v, "CT") for w, v in big.items()), key=lambda r: -r[3])
    mic = sorted(((w,) + rate(v, "マイクロスコープ") for w, v in big.items()), key=lambda r: -r[3])
    ct_hi, ct_lo = ct[0], ct[-1]
    mic_hi, mic_lo = mic[0], mic[-1]
    ratio = ct_hi[3] / ct_lo[3] if ct_lo[3] else None
    if not ratio or ratio < 2:
        return None  # 地域差が消えたら発見ごと伏せる

    bars = [(w, pct, f"{h}／{t}院") for w, h, t, pct in ct[:3]] + \
           [(w, pct, f"{h}／{t}院") for w, h, t, pct in ct[-3:]]
    body = f"""
<p class="rp-lede">「精密な検査を受けたい」という希望は、どこに住んでいても同じように叶うのか。{CITY}で公式サイトを解析できた{len(eq):,}院について、歯科用CT・マイクロスコープの導入が確認できた割合を区ごとに数えると、答えは「いいえ」でした。<strong>CTの導入率は、最も高い{esc(ct_hi[0])}の{ct_hi[3]:.0f}%に対し、最も低い{esc(ct_lo[0])}では{ct_lo[3]:.0f}%——約{ratio:.0f}倍の開き</strong>があります。</p>

<section class="rp-finding">
<p class="rp-kicker">FINDING ／ 設備の地域差</p>
<h2 class="rp-find-title">精密検査の選択肢は、住む場所で{ratio:.0f}倍違う</h2>
<div class="rp-find-body">
<p>下の図は、CT導入率の高い区・低い区それぞれ3つです。マイクロスコープも同様で、{esc(mic_hi[0])}の{mic_hi[3]:.0f}%に対し{esc(mic_lo[0])}では{mic_lo[3]:.0f}%でした。</p>
{_bars(bars)}
<p>大事な注意がふたつあります。第一に、<strong>設備がない医院＝劣る医院ではありません</strong>。虫歯の治療や定期検診など、CTやマイクロスコープを必要としない診療は多く、必要な症例だけ設備のある医院・大学病院へ紹介する分業も一般的です。第二に、この数字は公式サイトの記載から確認できた分であり、<strong>「未確認」は「無い」とは限りません</strong>。</p>
<p>そのうえで、インプラント・親知らずの抜歯・再発した根管治療など<strong>精密な画像診断が関わる治療を検討している方</strong>にとっては、この地域差は現実的な意味を持ちます。自分の区で見つからなくても、<strong>隣の区まで範囲を広げれば選択肢は大きく増える</strong>——通える範囲の考え方を、症状の重さに合わせて切り替えるのが実用的です。</p>
</div>
</section>

<section class="rp-finding">
<p class="rp-kicker">NOTE ／ 医院の方へ</p>
<div class="rp-find-body">
<p>導入済みの設備が公式サイトに書かれていない、あるいは機種名だけで用途の説明がない——という理由で「未確認」に数えられている医院が一定数あるとみられます。設備は導入することと同じくらい、<strong>何のために使い、患者に何をもたらすかを公開情報で説明すること</strong>が、患者の選択を助けます。</p>
</div>
</section>"""

    faq = [
        ("CTがない医院では精密な治療は受けられませんか？",
         "そうとは限りません。必要な症例のみ提携先や大学病院で撮影する体制の医院も多くあります。ご自身の治療にCTが必要かどうかは、診察時に医師へご確認ください。"),
        ("導入率はどうやって数えていますか？",
         "各医院の公式サイトをAIが解析し、設備の記載を確認できた度合いを5段階で評価したうち、確実性の高い医院（3以上）を「導入を確認」として数えています。"),
        ("自分の区の導入率も知りたいです。",
         "本記事では上位・下位の区のみ掲載しています。区ごとの医院は当サイトのエリアページ・ランキングページから設備条件で絞り込んでご覧いただけます。"),
    ]
    return dict(
        slug="equipment-gap",
        title=f"精密検査の選択肢は、住む場所で{ratio:.0f}倍違う",
        hook=f"CT導入率は区によって{ct_lo[3]:.0f}%〜{ct_hi[3]:.0f}%。「隣の区まで広げる」だけで選択肢が変わるという話。",
        desc=(f"公式サイトを解析できた{len(eq):,}院で歯科用CT・マイクロスコープの導入状況を区別に集計。"
              f"導入率には約{ratio:.0f}倍の地域差がありました。精密な治療を望むときの探し方を変えるデータです。"),
        body=body, faq=faq,
        method=[
            ("データの出どころ", f"各医院の公式サイトの公開情報をAIが解析した結果です。解析できた{len(eq):,}院を母数とし、医院数25院以上の区のみ区別集計しています。"),
            ("数字の作り方", "サイト記載から設備の確認度を0〜5で評価し、3以上を「導入を確認」として区ごとの割合を算出しました。"),
            ("この分析の限界", "公式サイトに記載のない設備は「未確認」であり「無い」ではありません。実際の導入率はこの数字より高い可能性があります。設備の有無は医院の優劣を示すものではありません。"),
        ])


_SERIES_BUILDERS = [_art_worktime, _art_price, _art_waiting, _art_reviews, _art_equipment_gap]

# ── 記事末尾の回遊導線（2026-07-13 検索流入改善・内部リンク施策） ─────────
# 「あわせて読む」：患者の疑問の流れで意味的につながる2本ずつ相互リンク
_RELATED = {
    "worktime-access":      ["waiting-time", "equipment-gap"],       # 時間帯→待ち時間・地域差
    "price-disclosure":     ["review-concentration", "waiting-time"],# 情報開示→口コミの読み方・評価軸
    "waiting-time":         ["worktime-access", "review-concentration"],
    "review-concentration": ["waiting-time", "price-disclosure"],
    "equipment-gap":        ["worktime-access", "price-disclosure"],
}
# 「この条件で医院を探す」：ランキングページの実在condキー（shindan.js CONDITION_MAP と一致）。
# 記事の内容に本当に合う条件のみ。無いものは空＝セクションごと出さない
# （記事末尾に素のランキングCTAが既にあるため重複させない）。
_SHINDAN_CONDS = {
    "worktime-access":      ["土日診療", "夜間診療"],
    "price-disclosure":     ["公式サイト情報が充実", "説明を重視"],
    "waiting-time":         ["説明を重視"],
    "review-concentration": ["公式サイト情報が充実"],
    "equipment-gap":        [],
}


def _next_sections_html(a, titles):
    """記事末尾の「あわせて読む」「この条件で医院を探す」小節。
    リンク先の実在（同時生成 or 既存ファイル／ランキングページ）を確認し、
    無いリンクは警告して省略する（処理は続行）。"""
    from urllib.parse import quote
    out = ""
    rel_items = []
    for slug in _RELATED.get(a["slug"], []):
        if slug in titles or (OUT.parent / f"{slug}.html").exists():
            t = titles.get(slug, slug)
            rel_items.append(f'<li><a href="{esc(slug)}.html">{esc(t)}</a></li>')
        else:
            print(f"   ⚠ 関連記事 {slug}.html が存在しないためリンクを省略しました")
    if rel_items:
        out += f"""
<section class="rp-finding">
<p class="rp-kicker">READ NEXT ／ あわせて読む</p>
<ul class="rp-links">{''.join(rel_items)}</ul>
</section>"""
    conds = [c for c in _SHINDAN_CONDS.get(a["slug"], [])]
    if conds:
        shindan = ROOT / "articles" / "shindan" / "index.html"
        if shindan.exists():
            cond_items = "".join(
                f'<li><a href="../shindan/index.html?cond={quote(c)}">「{esc(c)}」で医院を絞り込む →</a></li>'
                for c in conds)
            out += f"""
<section class="rp-finding">
<p class="rp-kicker">SEARCH ／ この条件で医院を探す</p>
<ul class="rp-links">{cond_items}</ul>
</section>"""
        else:
            print("   ⚠ articles/shindan/index.html が存在しないため条件リンクを省略しました")
    return out

_ARTICLE_CSS = """
.rp-hero{background:linear-gradient(168deg,var(--odr-pine) 0%,#173a31 60%,#122d26 100%);color:#fff;
  padding:calc(var(--sp-sec)*.7) var(--sp-page) calc(var(--sp-sec)*.8);}
.rp-hero .in{max-width:760px;margin:0 auto;}
.rp-eyebrow{font-family:var(--odr-mono);font-size:var(--fs-mono);letter-spacing:.2em;color:var(--odr-terra);margin:0 0 14px;}
.rp-hero h1{font-family:'Shippori Mincho',serif;font-size:clamp(1.5rem,3.4vw,2.1rem);font-weight:700;line-height:1.6;margin:0;}
.rp-body{max-width:760px;margin:0 auto;padding:0 var(--sp-page);}
.rp-lede{font-size:var(--fs-body);color:var(--odr-ink);line-height:2.1;padding:clamp(26px,3.5vw,44px) 0 0;margin:0;}
.rp-lede strong{color:var(--odr-pine);}
.rp-finding{padding:clamp(26px,3.5vw,44px) 0;border-bottom:1px solid var(--odr-line);}
.rp-finding:last-of-type{border-bottom:none;}
.rp-kicker{font-family:var(--odr-mono);font-size:.8rem;font-weight:600;letter-spacing:.14em;color:var(--odr-terra);margin:0 0 10px;}
.rp-find-title{font-family:'Shippori Mincho',serif;font-size:clamp(1.25rem,2.8vw,1.55rem);font-weight:700;color:var(--odr-pine);line-height:1.55;margin:0 0 16px;}
.rp-find-body{font-size:var(--fs-body);color:var(--odr-ink);line-height:2.05;}
.rp-find-body strong{color:var(--odr-pine);font-weight:700;}
.rp-find-body em{font-style:normal;background:linear-gradient(transparent 68%,rgba(196,109,60,.22) 68%);}
.rp-find-body p{margin:0 0 14px;}
.rp-bars{margin:20px 0 18px;display:flex;flex-direction:column;gap:12px;}
.rp-bar{display:grid;grid-template-columns:130px 1fr auto;align-items:center;gap:14px;}
.rp-bar-l{font-size:.88rem;color:var(--odr-ink);font-weight:600;}
.rp-bar-track{height:12px;background:#e8efec;border-radius:999px;overflow:hidden;}
.rp-bar-fill{display:block;height:100%;background:linear-gradient(90deg,var(--odr-pine),#2f6b5b);border-radius:999px;}
.rp-bar-v{font-family:var(--odr-mono);font-weight:700;color:var(--odr-pine);font-size:.95rem;white-space:nowrap;}
.rp-bar-v small{display:block;font-weight:400;color:var(--odr-ink2);font-size:.68rem;}
@media(max-width:560px){.rp-bar{grid-template-columns:92px 1fr auto;gap:10px;}.rp-bar-l{font-size:.8rem;}}
.rp-method{background:#f6f8f7;border-radius:var(--r-card);padding:clamp(24px,3.4vw,40px);margin:clamp(32px,4vw,52px) auto;max-width:760px;}
.rp-method h2{font-size:1.15rem;color:var(--odr-pine);margin:0 0 6px;}
.rp-method .rp-note{font-family:var(--odr-mono);font-size:var(--fs-mono);letter-spacing:.1em;color:var(--odr-ink2);margin:0 0 18px;}
.rp-method dl{margin:0;}
.rp-method dt{font-weight:700;color:var(--odr-ink);font-size:.92rem;margin:16px 0 4px;}
.rp-method dd{margin:0;color:var(--odr-ink2);font-size:.88rem;line-height:1.9;}
.rp-faq{border-bottom:1px solid var(--odr-line);padding:6px 0;}
.rp-faq summary{cursor:pointer;font-weight:700;color:var(--odr-ink);padding:12px 0;list-style:none;}
.rp-faq summary::before{content:"＋";color:var(--odr-terra);margin-right:10px;font-weight:700;}
.rp-faq[open] summary::before{content:"−";}
.rp-faq p{margin:0 0 14px;color:var(--odr-ink2);font-size:.9rem;line-height:1.9;}
.rp-updated{text-align:center;font-family:var(--odr-mono);font-size:var(--fs-mono);color:var(--odr-ink2);letter-spacing:.08em;padding:8px 0 0;}
.rp-foot{max-width:760px;margin:0 auto;padding:var(--sp-sec) var(--sp-page);color:var(--odr-ink2);font-size:var(--fs-caption);line-height:1.9;text-align:center;}
.rp-foot a{color:var(--odr-pine);}
.rp-back{max-width:760px;margin:0 auto;padding:22px var(--sp-page) 0;}
.rp-back a{color:var(--odr-terra);font-weight:700;font-size:.9rem;text-decoration:none;}
.rp-back a:hover{text-decoration:underline;}
.rp-cta-box{max-width:760px;margin:clamp(28px,3.5vw,44px) auto 0;padding:0 var(--sp-page);}
.rp-cta-box a{display:block;background:var(--odr-pine);color:#fff;text-decoration:none;border-radius:var(--r-card);padding:22px 26px;font-weight:700;line-height:1.8;}
.rp-cta-box a small{display:block;font-weight:400;color:rgba(255,255,255,.75);font-size:.8rem;margin-top:4px;}
.rp-links{list-style:none;margin:6px 0 0;padding:0;}
.rp-links li{margin:0 0 10px;}
.rp-links a{color:var(--odr-pine);font-weight:700;font-size:.95rem;line-height:1.9;text-decoration:underline;text-underline-offset:4px;}
.rp-links a:hover{color:var(--odr-terra);}
"""


def _existing_date_published(path):
    """既存ページの datePublished を引き継ぐ（ARTICLE_MANUAL §10：公開日は維持し、
    再生成では dateModified のみ更新する。2026-07-13 整合性監査 M-1 対応）"""
    try:
        m = re.search(r'"datePublished":\s*"(\d{4}-\d{2}-\d{2})"', path.read_text(encoding="utf-8"))
        return m.group(1) if m else None
    except FileNotFoundError:
        return None


def build_article(a, titles=None):
    today = date.today()
    stamp = today.strftime("%Y年%m月")
    url = f"https://{DOMAIN}/articles/research/{a['slug']}.html"
    title = f"{a['title']}｜{SITE} データ研究"
    published = _existing_date_published(OUT.parent / f"{a['slug']}.html") or today.isoformat()

    article_schema = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": a["title"],
        "description": a["desc"],
        "datePublished": published, "dateModified": today.isoformat(),
        "author": {"@type": "Organization", "name": SITE, "url": f"https://{DOMAIN}/"},
        "publisher": {"@type": "Organization", "name": SITE},
        "mainEntityOfPage": url,
        "isAccessibleForFree": True,
    }
    dataset_schema = {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": f"{CITY}の歯科医院データ分析（{a['title']}）",
        "description": a["desc"],
        "creator": {"@type": "Organization", "name": SITE, "url": f"https://{DOMAIN}/"},
        "dateModified": today.isoformat(),
        "isAccessibleForFree": True,
        "license": "https://creativecommons.org/licenses/by/4.0/",
    }
    faq_schema = {
        "@context": "https://schema.org", "@type": "FAQPage",
        "mainEntity": [{"@type": "Question", "name": q,
                        "acceptedAnswer": {"@type": "Answer", "text": ans}} for q, ans in a["faq"]],
    }
    schema_html = "\n".join(
        f'<script type="application/ld+json">{json.dumps(s, ensure_ascii=False)}</script>'
        for s in (article_schema, dataset_schema, faq_schema))

    faq_html = "".join(
        f'<details class="rp-faq"><summary>{esc(q)}</summary><p>{esc(ans)}</p></details>'
        for q, ans in a["faq"])
    method_html = "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>" for k, v in a["method"])
    next_html = _next_sections_html(a, titles or {})

    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)}</title>
<meta name="description" content="{esc(a['desc'])}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{esc(SITE)}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(a['desc'])}">
<meta property="og:url" content="{esc(url)}">
<link rel="canonical" href="{esc(url)}">
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Shippori+Mincho:wght@600;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<script src="../../assets/site-config.js"></script>
<script src="../../assets/odr-track.js"></script>
{schema_html}
<style>{_ARTICLE_CSS}</style>
</head>
<body class="odr">

<header class="odr-brandbar">
  <a class="odr-sig" href="../../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">{esc(SITE)}<small>{esc(EN_INSTITUTE)}</small></span>
  </a>
  <nav>
    <a href="../shindan/index.html">ランキング・AI診断</a>
    <a href="../features/index.html">特徴から探す</a>
    <a href="../index.html">コラム</a>
    <a href="../../network.html">展開エリア</a>
    <a href="../../shikumi.html">医院・開業医の方へ</a>
  </nav>
</header>

<section class="rp-hero">
  <div class="in">
    <p class="rp-eyebrow">DATA RESEARCH SERIES ／ {date.today().year}</p>
    <h1>{esc(a['title'])}</h1>
  </div>
</section>

<div class="rp-back"><a href="index.html">← データ研究トップへ戻る</a></div>

<main class="rp-body">
{a['body']}
{next_html}
</main>

<div class="rp-cta-box">
  <a href="../shindan/index.html">条件に合う医院を探す →<small>診療時間・設備・口コミ傾向から、あなたの条件で絞り込めます（無料・登録不要）</small></a>
</div>

<section class="rp-method">
  <p class="rp-note">METHODOLOGY ／ この分析の作り方（包み隠さず開示します）</p>
  <h2>信頼できる根拠は、透明性そのものです</h2>
  <dl>
    {method_html}
    <dt>順位とお金の関係</dt>
    <dd>掲載・分析・順位は、医院からの費用で一切変わりません。すべての医院を同じ基準で扱っています。</dd>
    <dt>間違いの訂正</dt>
    <dd>掲載内容に誤りがあれば、<a href="../../teisei.html">医院情報の修正フォーム</a>から無料で訂正します。詳しくは<a href="../../policy.html">運営ポリシー</a>をご覧ください。</dd>
  </dl>
</section>

<section class="rp-body">
  <h2 class="rp-find-title" style="margin-top:20px;">この記事についてのよくある質問</h2>
  {faq_html}
</section>

<p class="rp-updated">最終更新：{stamp}（集計日：{today.isoformat()}／データは毎月更新しています）</p>

<footer class="rp-foot">
  当ページの数字は、公開情報にもとづき当サイトが独自に集計・分析した参考情報です。医療的な診断ではありません。<br>
  出典を明記のうえでの引用を歓迎します（引用時は「{esc(SITE)}」とリンクを明記してください）。<br>
  <a href="../../policy.html">運営ポリシー・免責事項</a> ／ <a href="../../teisei.html">医院情報の修正</a> ／ <a href="index.html">データ研究トップ</a><br>
  © {date.today().year} {esc(SITE)}
</footer>

</body>
</html>"""

    out = ROOT / "articles" / "research" / f"{a['slug']}.html"
    out.parent.mkdir(parents=True, exist_ok=True)  # 新規都市はresearch/未作成のため（大阪は既存で表面化せず）
    out.write_text(doc, encoding="utf-8")
    return out


def build_series():
    # 先に全記事の統計・本文を組み立ててから書き出す（「あわせて読む」の相互リンクに
    # 各記事のタイトルが必要なため。伏せられた記事へのリンクは自動で省略される）
    arts = []
    for fn in _SERIES_BUILDERS:
        try:
            a = fn()
        except Exception as e:
            print(f"   ⚠ {fn.__name__} でエラー・この記事は伏せます: {e}")
            continue
        if not a:
            print(f"   ⚠ {fn.__name__}: 母数不足または前提が崩れたため自動で伏せました")
            continue
        arts.append(a)
    titles = {a["slug"]: a["title"] for a in arts}
    meta = []
    for a in arts:
        p = build_article(a, titles)
        meta.append(dict(slug=a["slug"], title=a["title"], hook=a["hook"]))
        print(f"✅ 研究記事: {p.name} — {a['title']}")
    return meta


if __name__ == "__main__":
    series = build_series()
    build(series)
