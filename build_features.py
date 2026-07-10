# -*- coding: utf-8 -*-
"""
特徴別カテゴリページを clinic_db.json から生成（Netflix方式・1ページ）。
【厳守：訴訟リスク回避 — これは「ランキング」ではない】
- 順位（1位/2位/3位）・★ランク・「おすすめ」「ランキング」表記は一切しない。
- 各カテゴリは「確認できた事実」を軸にする（例：CT設備がある医院／インプラント治療を行っている医院）。
- AIの推測で優劣を付けない。並びは客観事実（口コミ件数）のみで、順位番号は表示しない。
- 根拠データを持つ院のみ掲載。専門判定は“完全一致タグ”のみ（部分一致の誤検出を排除）。
- 各ページに「公開情報およびAI分析にもとづく参考情報であり、優劣を示すものではありません」を明記。
出力: articles/features/index.html
検証: python3 build_features.py --verify
"""
import os, re, json, html, sys

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
SITE_CFG = json.load(open(os.path.join(ROOT, "site_config.json"), encoding="utf-8"))
CITY_SHORT = SITE_CFG.get("city_short", SITE_CFG.get("city", ""))
N_PUBLISHED = SITE_CFG.get("stats", {}).get("clinics_published", 0)
OUT = os.path.join(ROOT, "articles", "features")
CAP = 24          # 1カテゴリの表示上限（Netflix行）
VERIFY = "--verify" in sys.argv
SLUG_MAP_PATH = os.path.join(ROOT, "clinic_slugs.json")
with open(SLUG_MAP_PATH, encoding="utf-8") as _f:
    SLUG_MAP = json.load(_f)  # place_id -> 一意なslug（同姓同名の医院URL衝突対策）

def esc(s): return html.escape(str(s), quote=True)
def nowrap_pipe(escaped_title):
    """タイトルと副題がきれいに分かれるよう、｜の直前、または？／！の直後(京都の前)で改行する"""
    import re as _re
    if "｜" in escaped_title:
        return escaped_title.replace("｜", "<br>｜", 1)
    return _re.sub(r"([？！])京都", r"\1<br>京都", escaped_title, count=1)
def slugify(name): return re.sub(r'[\\/:*?"<>|　\s・。、]', '_', name)[:60]

def ward(addr):
    m = re.search(r'京都市\s*([^\s0-9０-９]{1,4}区)', addr or "")
    if m: return "京都市" + m.group(1)
    m = re.search(r'([^\s0-9０-９]{1,4}区)', addr or "")
    return m.group(1) if m else ""

def rating(c): return float(c.get("rating", 0) or 0)
def reviews(c): return int(c.get("total_reviews", 0) or 0)
def eqv(c, k): return int((c.get("equipment_stars") or {}).get(k, 0) or 0)
def fitv(c, k): return int((c.get("patient_fit") or {}).get(k, 0) or 0)
def tags(c): return set(c.get("specialty_tags") or [])

# 確認できた設備（値>0）をチップ用に
EQUIP_KEYS = ["CT", "マイクロスコープ", "口腔内スキャナー", "個室", "駐車場", "バリアフリー"]
def confirmed_equip(c): return [k for k in EQUIP_KEYS if eqv(c, k) > 0]

# 専門は“完全一致タグ”のみ（"矯正中…"等の部分一致を拾わない）
IMPLANT = {"インプラント", "インプラント治療", "オールオンフォー", "インプラント埋入", "オールオン4", "オールオン6"}
ORTHO   = {"矯正歯科", "矯正治療", "歯列矯正", "マウスピース矯正", "小児矯正", "成人矯正", "ワイヤー矯正", "インビザライン", "裏側矯正", "矯正"}
KIDS    = {"小児歯科", "小児矯正", "小児予防歯科"}
PREVENT = {"予防歯科", "予防処置", "定期健診", "クリーニング", "PMTC", "予防"}
ESTHE   = {"審美歯科", "審美治療", "ホワイトニング", "セラミック治療", "セラミック", "審美"}

# カテゴリ定義：(id, タイトル, 説明, 条件関数)。すべて「確認できた事実」ベース。
CATEGORIES = [
    ("ct",       "CT設備がある医院",                     "歯科用CTの導入が公式サイト等で確認できた医院です。",           lambda c: eqv(c, "CT") > 0),
    ("micro",    "マイクロスコープがある医院",           "マイクロスコープの導入が確認できた医院です。",                 lambda c: eqv(c, "マイクロスコープ") > 0),
    ("private",  "個室診療のある医院",                   "個室での診療が確認できた医院です。",                           lambda c: eqv(c, "個室") > 0),
    ("parking",  "駐車場のある医院",                     "駐車場の用意が確認できた医院です。",                           lambda c: eqv(c, "駐車場") > 0),
    ("barrier",  "バリアフリー対応の医院",               "バリアフリー対応が確認できた医院です。",                       lambda c: eqv(c, "バリアフリー") > 0),
    ("implant",  "インプラント治療を行っている医院",     "インプラント治療への対応が公式情報から確認できた医院です。",   lambda c: bool(tags(c) & IMPLANT)),
    ("ortho",    "矯正歯科に対応している医院",           "矯正歯科への対応が公式情報から確認できた医院です。",           lambda c: bool(tags(c) & ORTHO)),
    ("kids",     "小児歯科に対応している医院",           "小児歯科への対応が公式情報から確認できた医院です。",           lambda c: bool(tags(c) & KIDS)),
    ("prevent",  "予防歯科に力を入れている医院",         "予防歯科への取り組みが公式情報から確認できた医院です。",       lambda c: bool(tags(c) & PREVENT)),
    ("esthetic", "審美・ホワイトニングに対応している医院", "審美・ホワイトニングへの対応が公式情報から確認できた医院です。", lambda c: bool(tags(c) & ESTHE)),
    ("kids_fit", "子ども連れに配慮した設備・情報が確認できた医院", "キッズスペースや小児対応など、子ども連れへの配慮がAI分析で確認できた医院です。", lambda c: fitv(c, "子ども連れ") >= 4),
    ("fear_fit", "歯科が怖い方への配慮が確認できた医院", "痛みへの配慮・個室・丁寧な説明など、歯科が苦手な方への配慮がAI分析で確認できた医院です。", lambda c: fitv(c, "歯科が怖い人") >= 4),
    ("female",   "女性医師が在籍する医院",               "女性医師の在籍が公式情報から確認できた医院です。",             lambda c: "女性医師" in tags(c)),
]

# カテゴリ → 関連記事：コラムは全都市共通で shikasoken.com/articles/ に集約済み（横展開マニュアル§8）。
# 都市サイトにはローカル記事が存在しないため空にする（リンク切れ防止）。
CATEGORY_ARTICLES = {}


def select(V, pred):
    xs = [c for c in V if pred(c)]
    # 並びは客観事実（口コミ件数）のみ。順位は付けない。
    xs.sort(key=lambda c: (-reviews(c), -rating(c), c["name"]))
    return xs

def main():
    db = json.load(open(DB, encoding="utf-8"))
    # 品質フラグで除外（京都市外・サロン・重複）
    V = [c for c in (db.values() if isinstance(db, dict) else db)
         if c.get("name") and not c.get("q_excluded")]

    data = [(cid, title, lead, select(V, pred)) for cid, title, lead, pred in CATEGORIES]

    if VERIFY:
        for cid, title, lead, xs in data:
            print(f"\n=== {title}  （該当 {len(xs)}院）===")
            for c in xs[:5]:
                eq = "／".join(confirmed_equip(c)) or "―"
                print(f"  ・{c['name']} | {ward(c.get('address',''))} | Google★{rating(c)}（{reviews(c)}件）| 設備:{eq}")
        return

    def card(c):
        slug = SLUG_MAP.get(c.get("place_id"), slugify(c["name"]))
        w = ward(c.get("address", ""))
        rate = f'<span class="fc-rate">★{rating(c)}<small>（{reviews(c)}件）</small></span>' if rating(c) else ""
        chips = "".join(f'<span class="fc-chip">{esc(x)}</span>' for x in confirmed_equip(c)[:4])
        chips_html = f'<div class="fc-chips">{chips}</div>' if chips else ""
        area = f'<span class="fc-area">{esc(w)}</span>' if w else ""
        return (f'<a class="fcard" href="../clinics/{esc(slug)}.html">'
                f'<span class="fc-name">{esc(c["name"])}</span>'
                f'{area}{rate}{chips_html}</a>')

    sections = ""
    for cid, title, lead, xs in data:
        if not xs:
            continue
        cards = "".join(card(c) for c in xs[:CAP])
        more = f'<p class="frow-more">ほか、確認できた医院は京都市内に全{len(xs)}院あります（口コミ件数の多い順に表示）。</p>' if len(xs) > CAP else f'<p class="frow-more">京都市内で確認できた {len(xs)}院（口コミ件数の多い順）。</p>'
        related = CATEGORY_ARTICLES.get(cid, [])
        related_html = ""
        if related:
            links = "".join(f'<a class="fsec-article" href="../{fn}">{nowrap_pipe(esc(t))}</a>' for fn, t in related)
            related_html = f'<div class="fsec-articles"><span class="fsec-articles-k">関連する研究レポート</span>{links}</div>'
        sections += (f'<section class="fsec" id="{cid}">'
                     f'<h2 class="fsec-t">{esc(title)}</h2>'
                     f'<p class="fsec-l">{esc(lead)}</p>'
                     f'<div class="frow">{cards}</div>{more}{related_html}</section>')

    # ブランド共通の研究データ（実集計・論文メタ用）
    n_clinics = len(V)
    n_reviews = sum(reviews(c) for c in V)
    updated = max((c.get("last_analyzed") for c in V if c.get("last_analyzed")), default="").replace("-", ".")
    os.makedirs(OUT, exist_ok=True)
    html_out = (TEMPLATE.replace("{sections}", sections)
                .replace("{n_clinics}", f"{n_clinics:,}")
                .replace("{n_reviews}", f"{n_reviews:,}")
                .replace("{updated}", updated)
                .replace("{CITY_SHORT}", CITY_SHORT).replace("{N_PUBLISHED:,}", f"{N_PUBLISHED:,}"))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html_out)
    total = sum(len(xs) for _, _, _, xs in data)
    print(f"✅ 特徴別カテゴリページ生成: {sum(1 for _,_,_,xs in data if xs)}カテゴリ / のべ{total}院 → {OUT}/index.html")

TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>特徴から探す｜京都歯科総研</title>
<meta name="description" content="京都市内の歯科医院を、CT設備・対応治療・子ども連れへの配慮など、確認できた特徴ごとに一覧。公開情報およびAI分析にもとづく参考情報です。">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<style>
:root{--pine:#1f4b3f;--terra:#d98b5f;--paper:#f6f8f7;--ink:#1c2b25;--ink2:#586962;--line:#e4ebe7;}
*{box-sizing:border-box;}
body{margin:0;font-family:var(--odr-sans);color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased;line-height:1.8;}
a{color:inherit;text-decoration:none;}
.rf-crumb{max-width:1040px;margin:14px auto 0;padding:0 clamp(20px,4vw,40px);display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-family:var(--odr-mono);font-size:.72rem;letter-spacing:.02em;}
.rf-crumb a{color:var(--odr-ink2);text-decoration:none;}
.rf-crumb a:hover{color:var(--odr-pine);text-decoration:underline;}
.rf-crumb .rf-sep{color:var(--odr-silver);}
.rf-crumb .rf-current{color:var(--odr-terra);font-weight:700;}
.f-hero{background:var(--pine);color:#fff;padding:clamp(34px,5vw,60px) clamp(20px,4vw,40px) clamp(30px,4vw,44px);}
.f-hero-in{max-width:1040px;margin:0 auto;}
.f-hero h1{font-size:var(--fs-heading);font-weight:700;margin:18px 0 12px;line-height:1.35;}
.f-hero p{color:#d6e6df;font-size:.98rem;margin:0 0 22px;max-width:var(--wrap-read);}
main{max-width:1040px;margin:0 auto;padding:clamp(24px,3vw,40px) clamp(16px,4vw,40px) 72px;}
.fsec{margin:0 0 40px;}
.fsec-t{font-size:1.14rem;font-weight:700;color:var(--pine);margin:0 0 4px;}
.fsec-l{color:var(--ink2);font-size:.86rem;margin:0 0 14px;}
.frow{display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;-webkit-overflow-scrolling:touch;scroll-snap-type:x proximity;}
.fcard{flex:0 0 auto;width:186px;background:#fff;border:1px solid var(--line);border-radius:12px;padding:14px 15px;scroll-snap-align:start;transition:border-color .15s,transform .15s;display:flex;flex-direction:column;gap:5px;}
.fcard:hover{border-color:var(--pine);transform:translateY(-2px);}
.fc-name{font-weight:700;color:var(--pine);font-size:.9rem;line-height:1.45;}
.fc-area{color:var(--ink2);font-size:.74rem;}
.fc-rate{color:var(--terra);font-weight:700;font-size:.82rem;}
.fc-rate small{color:var(--ink2);font-weight:400;font-size:.7rem;}
.fc-chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:2px;}
.fc-chip{background:#eaf1ee;color:var(--pine);border-radius:6px;padding:1px 7px;font-size:.66rem;}
.frow-more{color:var(--ink2);font-size:.76rem;margin:8px 2px 0;}
.fsec-articles{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:14px 2px 0;padding-top:14px;border-top:1px solid var(--line);}
.fsec-articles-k{font-family:var(--odr-mono);font-size:.68rem;letter-spacing:.06em;color:var(--ink2);}
.fsec-article{font-size:.8rem;color:var(--pine);background:#eaf1ee;border-radius:8px;padding:5px 12px;text-decoration:none;font-weight:600;}
.fsec-article:hover{background:var(--pine);color:#fff;}
.f-note{background:#fff;border:1px solid var(--line);border-left:3px solid var(--terra);border-radius:12px;padding:18px 20px;color:var(--ink2);font-size:.82rem;line-height:1.85;margin:8px 0 0;}
.f-note strong{color:var(--pine);}
.f-cta{background:var(--pine);border-radius:16px;padding:32px 24px;text-align:center;margin:26px 0 0;}
.f-cta p{color:#cfe0d8;font-size:.9rem;margin:0 0 16px;}
.f-cta a{display:inline-block;background:var(--terra);color:#fff;font-weight:700;padding:13px 30px;border-radius:10px;font-size:.94rem;}
/* 改行マニュアル v1.0 */
h1,h2,h3,p,li{line-break:strict;text-wrap:pretty;}
</style>
<script src="../../assets/site-config.js"></script>
<script src="../../assets/odr-track.js"></script>
</head>
<body>
<header class="odr-brandbar">
  <a class="odr-sig" href="../../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">京都歯科総研<small>Kyoto Dental Research</small></span>
  </a>
  <nav>
    <a href="../shindan/index.html">ランキング&amp;AI診断</a>
    <a href="../../index.html">トップ</a>
    <a href="../index.html">コラム</a>
    <a href="../../network.html">展開エリア</a>
    <a href="../../shikumi.html">医院・開業医の方へ</a>
  </nav>
</header>
<nav class="rf-crumb" aria-label="パンくずリスト">
  <a href="../../index.html">Research Database</a>
  <span class="rf-sep">/</span>
  <span class="rf-current">Clinic Analysis</span>
</nav>
<section class="f-hero">
  <div class="f-hero-in">
    <span class="odr-kicker pill">FEATURE REPORT</span>
    <h1>AI分析から見た、京都の歯科医院の特徴</h1>
    <p>確認できた設備・対応治療・配慮などの特徴ごとに、京都市内の歯科医院を整理しました。順位付けはしていません。</p>
    <div class="odr-meta on-dark">
      <dl><dt>分析対象</dt><dd>{n_clinics}院</dd></dl>
      <dl><dt>分析した口コミ</dt><dd>{n_reviews}件</dd></dl>
      <dl><dt>Sources</dt><dd>Google・公式・症例・求人</dd></dl>
      <dl><dt>Updated</dt><dd>{updated}</dd></dl>
    </div>
  </div>
</section>
<main>
  {sections}
  <div class="f-note">
    <strong>掲載内容について（必ずお読みください）</strong><br>
    掲載内容は、<strong>公開情報（Googleマップ・各医院の公式サイト等）およびAI分析にもとづく参考情報であり、優劣を示すものではありません</strong>。
    各カテゴリは「確認できた事実」を軸にした整理であり、掲載順は口コミ件数など客観的な情報にもとづくもので、医院の優劣・おすすめ順位ではありません。
    実際には設備や対応があっても、公開情報に記載がない医院は掲載されていない場合があります（＝掲載がないことは「設備・対応がない」ことを意味しません）。
    料金・診療内容・設備の詳細は各医院へ直接ご確認ください。受診の判断は必ず歯科医師にご相談ください。
  </div>
  <div class="odr-meta" style="margin:28px 0 0;border:1px solid var(--line);border-radius:var(--r-card);padding:20px 24px;background:#fff;">
    <dl><dt>Research Note</dt><dd style="color:var(--terra);">京都歯科総研 編集部</dd></dl>
    <dl><dt>分析手法</dt><dd>AI分析 ＋ 人による監修</dd></dl>
    <dl><dt>Confidence</dt><dd>確認できた事実のみ掲載</dd></dl>
    <dl><dt>Updated</dt><dd>{updated}</dd></dl>
  </div>
  <div class="odr-cta" style="margin-top:26px;">
    <p class="t">条件から、あなたに合う歯科医院へ</p>
    <p class="s">ご希望の条件をもとに、{CITY_SHORT}市内 約{N_PUBLISHED:,}院からAIが無料でご案内します。</p>
    <div class="odr-cta-btns">
      <a class="odr-btn" href="../shindan/index.html">AI診断を受ける（無料）</a>
      <a class="odr-btn ghost" href="../../index.html">トップへ戻る</a>
    </div>
  </div>
</main>
</body>
</html>'''

if __name__ == "__main__":
    main()
