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
CITY = SITE_CFG.get("city", "")                # 例: 大阪市 / 神戸市 / 北播磨エリア
SITE_NAME = SITE_CFG.get("site_name", "")      # 例: 大阪歯科総研
EN_UPPER = SITE_CFG.get("site_name_en", "")    # 例: OSAKA DENTAL RESEARCH
# 例: Osaka Dental Research Institute（site_name_enから機械導出。ハイフン語は各パートを大文字化）
EN_INSTITUTE = " ".join("-".join(p.capitalize() for p in w.split("-")) for w in EN_UPPER.split()) + " Institute"
OUT = os.path.join(ROOT, "articles", "features")
CAP = 48          # 1カテゴリの表示上限（Netflix行）。地域・条件で絞り込むため母数を多めに
# コラム棚と同じホバー矢印（左右チェブロン）
FARROW_L = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>'
FARROW_R = '<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'
VERIFY = "--verify" in sys.argv
SLUG_MAP_PATH = os.path.join(ROOT, "clinic_slugs.json")
with open(SLUG_MAP_PATH, encoding="utf-8") as _f:
    SLUG_MAP = json.load(_f)  # place_id -> 一意なslug（同姓同名の医院URL衝突対策）

def esc(s): return html.escape(str(s), quote=True)
def nowrap_pipe(escaped_title):
    """タイトルと副題がきれいに分かれるよう、｜の直前、または？／！の直後(都市名の前)で改行する"""
    import re as _re
    if "｜" in escaped_title:
        return escaped_title.replace("｜", "<br>｜", 1)
    return _re.sub("([？！])" + CITY_SHORT, "\\1<br>" + CITY_SHORT, escaped_title, count=1)
def slugify(name): return re.sub(r'[\\/:*?"<>|　\s・。、]', '_', name)[:60]

def ward(addr):
    m = re.search(CITY + r'\s*([^\s0-9０-９区]{1,3}区)', addr or "")
    if m: return CITY + m.group(1)
    m = re.search(r'([^\s0-9０-９区]{1,3}区)', addr or "")
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

# カテゴリ → 関連記事（記事本文の内容と合致するもののみ。無理に全カテゴリを埋めない）
# 2026-07-10 コラム全都市共通化：記事は地名除去のうえ存置（URL＝ファイル名は旧のまま）。
# タイトル表示は地名除去後のものを使う。内容が実際に合致するカテゴリのみ登録（無理に全カテゴリを埋めない）。
CATEGORY_ARTICLES = {
    "ct":       [(f"2026-07-04_CTとマイクロスコープがある{CITY_SHORT}の歯科を選ぶ理由.html", "CTとマイクロスコープがある歯科が重要な理由"),
                 (f"2026-07-04_根管治療が上手い{CITY_SHORT}の歯科医院を見分ける方法.html", "根管治療が上手い歯科の見分け方｜専門医の選び方")],
    "micro":    [(f"2026-07-04_CTとマイクロスコープがある{CITY_SHORT}の歯科を選ぶ理由.html", "CTとマイクロスコープがある歯科が重要な理由"),
                 (f"2026-07-04_根管治療が上手い{CITY_SHORT}の歯科医院を見分ける方法.html", "根管治療が上手い歯科の見分け方｜専門医の選び方")],
    "implant":  [(f"2026-07-04_{CITY_SHORT}のインプラント費用とリスクを正しく理解する.html", "インプラント｜費用相場とリスクを正しく理解する")],
    "ortho":    [(f"2026-07-04_{CITY_SHORT}で矯正は何歳から？選び方を徹底解説.html", "矯正は何歳から？マウスピース・ワイヤーの選び方"),
                 (f"2026-07-04_歯並びが気になったら｜{CITY_SHORT}で矯正相談すべきタイミング.html", "歯並びが気になる方へ｜矯正相談するベストタイミング")],
    "kids":     [(f"2026-07-04_子どもの虫歯予防｜{CITY_SHORT}の小児歯科はいつから？.html", "子どもの虫歯予防｜小児歯科にいつから通うべきか"),
                 (f"2026-07-04_{CITY_SHORT}で矯正は何歳から？選び方を徹底解説.html", "矯正は何歳から？マウスピース・ワイヤーの選び方")],
    "prevent":  [(f"2026-07-04_予防歯科クリーニングの頻度とメリット｜{CITY}版.html", "予防歯科のクリーニング頻度とメリット"),
                 (f"2026-07-04_子どもの虫歯予防｜{CITY_SHORT}の小児歯科はいつから？.html", "子どもの虫歯予防｜小児歯科にいつから通うべきか")],
    "esthetic": [(f"2026-07-04_{CITY_SHORT}ホワイトニング｜種類・費用・選び方を徹底比較.html", "ホワイトニング｜種類・選び方・費用比較ガイド"),
                 (f"2026-07-04_銀歯を白くしたい！{CITY_SHORT}でセラミック治療の費用と方法.html", "銀歯を白くしたい方へ｜セラミック費用と方法を解説")],
    "kids_fit": [(f"2026-07-04_子どもの虫歯予防｜{CITY_SHORT}の小児歯科はいつから？.html", "子どもの虫歯予防｜小児歯科にいつから通うべきか")],
}


def select(V, pred):
    xs = [c for c in V if pred(c)]
    # 並びは客観事実（口コミ件数）のみ。順位は付けない。
    xs.sort(key=lambda c: (-reviews(c), -rating(c), c["name"]))
    return xs

def main():
    db = json.load(open(DB, encoding="utf-8"))
    # 品質フラグで除外（対象エリア外・サロン・重複）
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
        conds = confirmed_equip(c)  # 絞り込み用の全条件
        return (f'<a class="fcard" data-ward="{esc(w)}" data-cond="{esc(" ".join(conds))}" '
                f'href="../clinics/{esc(slug)}.html">'
                f'<span class="fc-name">{esc(c["name"])}</span>'
                f'{area}{rate}{chips_html}</a>')

    sections = ""
    for cid, title, lead, xs in data:
        if not xs:
            continue
        cards = "".join(card(c) for c in xs[:CAP])
        more = f'<p class="frow-more">ほか、確認できた医院は{CITY}内に全{len(xs)}院あります（口コミ件数の多い順に表示）。</p>' if len(xs) > CAP else f'<p class="frow-more">{CITY}内で確認できた {len(xs)}院（口コミ件数の多い順）。</p>'
        related = CATEGORY_ARTICLES.get(cid, [])
        related_html = ""
        if related:
            links = "".join(f'<a class="fsec-article" href="../{fn}">{nowrap_pipe(esc(t))}</a>' for fn, t in related)
            related_html = f'<div class="fsec-articles"><span class="fsec-articles-k">関連する研究レポート</span>{links}</div>'
        sections += (f'<section class="fsec" id="{cid}">'
                     f'<h2 class="fsec-t">{esc(title)}</h2>'
                     f'<p class="fsec-l">{esc(lead)}</p>'
                     f'<div class="frow-wrap">'
                     f'<button type="button" class="frow-arrow frow-arrow--prev" aria-label="前へ" onclick="frowScroll(this,-1)">{FARROW_L}</button>'
                     f'<div class="frow">{cards}</div>'
                     f'<button type="button" class="frow-arrow frow-arrow--next" aria-label="次へ" onclick="frowScroll(this,1)">{FARROW_R}</button>'
                     f'</div>{more}{related_html}</section>')

    # 右サイドの絞り込み用：表示カードに含まれる区を頻度順に集める
    from collections import Counter
    _wc = Counter()
    for _cid, _t, _l, _xs in data:
        for _c in _xs[:CAP]:
            _w = ward(_c.get("address", ""))
            if _w:
                _wc[_w] += 1
    ward_chips = ('<button type="button" class="ff-chip ff-ward on" data-ward="">すべて</button>'
                  + "".join(f'<button type="button" class="ff-chip ff-ward" data-ward="{esc(w)}">{esc(w.replace(CITY, ""))}</button>'
                            for w, _ in _wc.most_common()))
    cond_chips = "".join(f'<button type="button" class="ff-chip ff-cond" data-cond="{esc(k)}">{esc(k)}</button>'
                         for k in EQUIP_KEYS)
    filter_html = (
        '<div class="ff-inner">'
        '<p class="ff-title">条件でしぼり込む</p>'
        '<p class="ff-h">地域</p>'
        f'<div class="ff-chips">{ward_chips}</div>'
        '<p class="ff-h">こだわり条件</p>'
        f'<div class="ff-chips">{cond_chips}</div>'
        '<button type="button" class="ff-reset" id="ffReset">条件をリセット</button>'
        '<p class="ff-empty" id="ffEmpty" hidden>選んだ条件に合う掲載医院が見つかりませんでした。条件を減らしてお試しください。</p>'
        '</div>')

    # ブランド共通の研究データ（実集計・論文メタ用）
    n_clinics = len(V)
    n_reviews = sum(reviews(c) for c in V)
    updated = max((c.get("last_analyzed") for c in V if c.get("last_analyzed")), default="").replace("-", ".")
    os.makedirs(OUT, exist_ok=True)
    html_out = (TEMPLATE.replace("{sections}", sections)
                .replace("{filter}", filter_html)
                .replace("{n_clinics}", f"{n_clinics:,}")
                .replace("{n_reviews}", f"{n_reviews:,}")
                .replace("{updated}", updated)
                .replace("{CANONICAL}", f"https://{SITE_CFG.get('domain','shikasoken.com')}/articles/features/index.html")
                .replace("{SITE_NAME}", SITE_NAME).replace("{EN_INSTITUTE}", EN_INSTITUTE).replace("{CITY}", CITY)
                .replace("{CITY_SHORT}", CITY_SHORT).replace("{N_PUBLISHED:,}", f"{N_PUBLISHED:,}"))
    open(os.path.join(OUT, "index.html"), "w", encoding="utf-8").write(html_out)
    total = sum(len(xs) for _, _, _, xs in data)
    print(f"✅ 特徴別カテゴリページ生成: {sum(1 for _,_,_,xs in data if xs)}カテゴリ / のべ{total}院 → {OUT}/index.html")

TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>特徴から探す｜{SITE_NAME}</title>
<meta name="description" content="{CITY}内の歯科医院を、CT設備・対応治療・子ども連れへの配慮など、確認できた特徴ごとに一覧。公開情報およびAI分析にもとづく参考情報です。">
<link rel="canonical" href="{CANONICAL}">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Shippori+Mincho:wght@600;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<style>
:root{--pine:#1f4b3f;--terra:#d98b5f;--paper:#f6f8f7;--ink:#1c2b25;--ink2:#586962;--line:#e4ebe7;}
*{box-sizing:border-box;}
body{margin:0;font-family:var(--odr-sans);color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased;line-height:1.8;}
a{color:inherit;text-decoration:none;}
.rf-crumb{max-width:1440px;margin:14px auto 0;padding:0 clamp(24px,4vw,56px);display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-family:var(--odr-mono);font-size:.72rem;letter-spacing:.02em;}
.rf-crumb a{color:var(--odr-ink2);text-decoration:none;}
.rf-crumb a:hover{color:var(--odr-pine);text-decoration:underline;}
.rf-crumb .rf-sep{color:var(--odr-silver);}
.rf-crumb .rf-current{color:var(--odr-terra);font-weight:700;}
.f-hero{background:var(--pine);color:#fff;padding:clamp(34px,5vw,60px) clamp(24px,4vw,56px) clamp(30px,4vw,44px);}
.f-hero-in{max-width:1440px;margin:0 auto;}
.f-hero h1{font-family:'Shippori Mincho',serif;font-size:var(--fs-heading);font-weight:700;margin:18px 0 12px;line-height:1.35;}
.f-hero p{color:#d6e6df;font-size:.98rem;margin:0 0 22px;max-width:var(--wrap-read);}
/* 2カラム：本文＋右の絞り込みフィルター */
.f-layout{max-width:1440px;margin:0 auto;padding:0 clamp(24px,4vw,56px);display:grid;grid-template-columns:1fr 258px;gap:36px;align-items:start;}
.f-main{min-width:0;padding:clamp(24px,3vw,40px) 0 72px;}
.f-filter{position:sticky;top:16px;margin-top:clamp(24px,3vw,40px);background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px;}
.ff-title{font-size:.92rem;font-weight:700;color:var(--pine);margin:0 0 6px;}
.ff-h{font-family:'Roboto Mono',monospace;font-size:.64rem;letter-spacing:.1em;color:var(--ink2);text-transform:uppercase;margin:14px 0 8px;}
.ff-chips{display:flex;flex-wrap:wrap;gap:6px;max-height:196px;overflow-y:auto;}
.ff-chip{font-size:.76rem;font-weight:600;color:var(--ink2);background:#fff;border:1px solid var(--line);border-radius:999px;padding:6px 12px;cursor:pointer;font-family:inherit;transition:background .15s,color .15s,border-color .15s;}
.ff-chip:hover{border-color:var(--pine);color:var(--pine);}
.ff-chip.on{background:var(--pine);color:#fff;border-color:var(--pine);}
.ff-reset{margin-top:16px;width:100%;font-size:.78rem;font-weight:600;color:var(--ink2);background:none;border:1px solid var(--line);border-radius:8px;padding:8px;cursor:pointer;font-family:inherit;transition:border-color .15s,color .15s;}
.ff-reset:hover{border-color:var(--terra);color:var(--terra);}
.ff-empty{margin:14px 0 0;font-size:.78rem;color:var(--terra);line-height:1.7;}
@media(max-width:900px){
  .f-layout{grid-template-columns:1fr;gap:0;}
  .f-filter{position:static;margin:14px 0 6px;order:-1;}
  .ff-chips{max-height:none;}
}
.fsec{margin:0 0 22px;}
.fsec-t{font-size:1.14rem;font-weight:700;color:var(--pine);margin:0 0 4px;}
.fsec-l{color:var(--ink2);font-size:.86rem;margin:0 0 14px;}
/* コラム棚と同じNetflix風：右端で見切れ（右bleed）＋ホバー矢印 */
.frow-wrap{position:relative;}
.frow{display:flex;gap:12px;overflow-x:auto;padding-bottom:8px;-webkit-overflow-scrolling:touch;scroll-snap-type:x proximity;
  margin:0;padding-right:0;scrollbar-width:thin;}
.frow-arrow{position:absolute;top:0;bottom:8px;width:52px;z-index:2;display:flex;align-items:center;justify-content:center;
  border:none;background:transparent;color:var(--ink,#222);cursor:pointer;opacity:0;transition:opacity .2s;}
.frow-arrow svg{background:#fff;border-radius:50%;padding:9px;width:38px;height:38px;box-sizing:border-box;
  box-shadow:0 2px 10px rgba(20,20,25,.18);transition:transform .18s ease;}
.frow-arrow:hover svg{transform:scale(1.16);}
.frow-wrap:hover .frow-arrow{opacity:1;}
.frow-arrow--prev{left:0;justify-content:flex-start;padding-left:6px;}
.frow-arrow--next{right:0;justify-content:flex-end;padding-right:6px;}
@media(hover:none){.frow-arrow{display:none;}}
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
<script>
function frowScroll(btn, dir){
  var row = btn.parentElement.querySelector('.frow');
  if(!row) return;
  row.scrollBy({left: dir * row.clientWidth * 0.9, behavior:'smooth'});
}
</script>
</head>
<body>
<header class="odr-brandbar">
  <a class="odr-sig" href="../../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">{SITE_NAME}<small>{EN_INSTITUTE}</small></span>
  </a>
  <nav>
    <a href="../shindan/index.html">ランキング・AI診断</a>
    <a href="../features/index.html">特徴から探す</a>
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
    <h1>AI分析から見た、{CITY_SHORT}の歯科医院の特徴</h1>
    <p>確認できた設備・対応治療・配慮などの特徴ごとに、{CITY}内の歯科医院を整理しました。順位付けはしていません。</p>
    <div class="odr-meta on-dark">
      <dl><dt>分析対象</dt><dd>{n_clinics}院</dd></dl>
      <dl><dt>分析した口コミ</dt><dd>{n_reviews}件</dd></dl>
      <dl><dt>Sources</dt><dd>Google・公式・症例・求人</dd></dl>
      <dl><dt>Updated</dt><dd>{updated}</dd></dl>
    </div>
  </div>
</section>
<div class="f-layout">
<main class="f-main">
  {sections}
  <div class="f-note">
    <strong>掲載内容について（必ずお読みください）</strong><br>
    掲載内容は、<strong>公開情報（Googleマップ・各医院の公式サイト等）およびAI分析にもとづく参考情報であり、優劣を示すものではありません</strong>。
    各カテゴリは「確認できた事実」を軸にした整理であり、掲載順は口コミ件数など客観的な情報にもとづくもので、医院の優劣・おすすめ順位ではありません。
    実際には設備や対応があっても、公開情報に記載がない医院は掲載されていない場合があります（＝掲載がないことは「設備・対応がない」ことを意味しません）。
    料金・診療内容・設備の詳細は各医院へ直接ご確認ください。受診の判断は必ず歯科医師にご相談ください。
  </div>
  <div class="odr-meta" style="margin:28px 0 0;border:1px solid var(--line);border-radius:var(--r-card);padding:20px 24px;background:#fff;">
    <dl><dt>Research Note</dt><dd style="color:var(--terra);">{SITE_NAME} 編集部</dd></dl>
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
<aside class="f-filter">{filter}</aside>
</div>
<script>
(function(){
  var selWard="", selConds=new Set();
  function apply(){
    document.querySelectorAll('.fcard').forEach(function(card){
      var w=card.getAttribute('data-ward')||"";
      var cond=(card.getAttribute('data-cond')||"").split(" ");
      var okW=!selWard||w===selWard, okC=true;
      selConds.forEach(function(c){ if(cond.indexOf(c)<0) okC=false; });
      card.style.display=(okW&&okC)?"":"none";
    });
    document.querySelectorAll('.fsec').forEach(function(sec){
      var visible=Array.prototype.filter.call(sec.querySelectorAll('.fcard'),function(c){return c.style.display!=="none";}).length;
      sec.style.display=visible?"":"none";
    });
    var any=Array.prototype.some.call(document.querySelectorAll('.fsec'),function(s){return s.style.display!=="none";});
    var emp=document.getElementById('ffEmpty'); if(emp) emp.hidden=any;
  }
  function reset(){
    selWard=""; selConds.clear();
    document.querySelectorAll('.ff-ward').forEach(function(x){x.classList.toggle('on',x.getAttribute('data-ward')==="");});
    document.querySelectorAll('.ff-cond').forEach(function(x){x.classList.remove('on');});
    apply();
  }
  document.addEventListener('click',function(e){
    var r=e.target.closest('#ffReset'); if(r){reset();return;}
    var b=e.target.closest('.ff-chip'); if(!b) return;
    if(b.classList.contains('ff-ward')){
      document.querySelectorAll('.ff-ward').forEach(function(x){x.classList.remove('on');});
      b.classList.add('on'); selWard=b.getAttribute('data-ward')||"";
    } else if(b.classList.contains('ff-cond')){
      b.classList.toggle('on');
      var c=b.getAttribute('data-cond');
      if(b.classList.contains('on')) selConds.add(c); else selConds.delete(c);
    }
    apply();
  });
})();
</script>
</body>
</html>'''

if __name__ == "__main__":
    main()
