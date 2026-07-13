# -*- coding: utf-8 -*-
"""
articles/index.html（歯科コラム）と各カテゴリー全記事ページ cat-*.html を生成。
ダークグリーンのヒーロー＋検索＋線画イラスト、写真サムネイル付き5列カード、
カテゴリは小さな色文字ラベル、「新着記事」「よく読まれている」等のセクション構成。
写真は articles/img/<記事ファイル名>.jpg 等があれば自動反映（無ければ淡いプレースホルダ）。
"""
import os, re, html, json
from urllib.parse import quote

def urlq(p):
    """記事ファイル名に含まれる % や ｜ 等をURLエンコードしてリンク切れ・画像非表示を防ぐ。"""
    return quote(p, safe="/")

ART = os.path.join(os.path.dirname(__file__), "articles")

# 都市固有値は site_config.json から読む（ハードコード禁止・多都市共通スクリプト）
SITE_CFG = json.load(open(os.path.join(os.path.dirname(__file__), "site_config.json"), encoding="utf-8"))
CITY = SITE_CFG.get("city", "")                # 例: 大阪市 / 神戸市 / 北播磨エリア
CITY_SHORT = SITE_CFG.get("city_short", SITE_CFG.get("city", ""))
SITE_NAME = SITE_CFG.get("site_name", "")      # 例: 大阪歯科総研
EN_UPPER = SITE_CFG.get("site_name_en", "")    # 例: OSAKA DENTAL RESEARCH
# 例: Osaka Dental Research Institute（site_name_enから機械導出。ハイフン語は各パートを大文字化）
EN_INSTITUTE = " ".join("-".join(p.capitalize() for p in w.split("-")) for w in EN_UPPER.split()) + " Institute"
DOMAIN = SITE_CFG.get("domain", "shikasoken.com")

# 表示用の投稿日（ファイル名は他所から参照されているため変更せず、
# 表示日付だけをこのマップで上書きする。2026-07-08：初期一括生成分の全記事が
# 同日「7/4」表示になっていたのを分散させるため導入した歴史的マップ。
# 【2026-07-13 ユーザー決定】既存エントリは据え置き（再変更もしない）。
# 今後、実日付と異なる表示日付を新規に追加しないこと（新規記事はファイル名の実日付のまま）
_DATES_PATH = os.path.join(os.path.dirname(__file__), "article_dates.json")
try:
    with open(_DATES_PATH, encoding="utf-8") as _f:
        ARTICLE_DATES = json.load(_f)
except FileNotFoundError:
    ARTICLE_DATES = {}

# ホバー時に出す「え、なんだろう」フック文言（記事ファイル名→短い一言）。
# 新開発室（ChatGPT＋Gemini）で作成。無ければオーバーレイは出さない。
_HOOKS_PATH = os.path.join(os.path.dirname(__file__), "article_hooks.json")
try:
    with open(_HOOKS_PATH, encoding="utf-8") as _f:
        ARTICLE_HOOKS = json.load(_f)
except FileNotFoundError:
    ARTICLE_HOOKS = {}

CAT_KW = {
    "痛み・急なトラブル": ["痛い","痛み","取れた","グラグラ","腫れ","しみる","知覚過敏","顎","親知らず","すぐ"],
    "矯正・審美": ["ホワイトニング","セラミック","銀歯","白く","矯正","歯並び","審美"],
    "インプラント": ["インプラント","根管","歯周病","入れ歯","セカンドオピニオン","CT","マイクロスコープ"],
    "予防・こども": ["予防","クリーニング","口臭","子ども","子供","こども","小児","虫歯予防","何歳"],
    "歯科医院の選び方": ["見分け方","選び方","口コミ","チェックポイント","選ぶ理由","ポイント"],
}
# カテゴリ → 文字色（小さな色ラベル用。装飾ではなく識別のための1色）
CAT_COLOR = {
    "痛み・急なトラブル": "#C85A34",
    "矯正・審美":        "#7A5AA6",
    "インプラント":      "#3B7CB8",
    "予防・こども":      "#2E9E86",
    "歯科医院の選び方":  "#2E7D5B",
    "歯科ガイド":        "#2E9E86",
    "データ研究":        "#1f4b3f",
}

# カードのメタは「○分で読める」ではなく、患者目線で読む意味が伝わる一言に（カテゴリ別）
CAT_HOOK = {
    "痛み・急なトラブル": "痛いとき、どう動くか",
    "矯正・審美":        "費用と選び方の目安",
    "インプラント":      "決める前に知りたいこと",
    "予防・こども":      "毎日のケアと予防に",
    "歯科医院の選び方":  "後悔しない選び方",
    "歯科ガイド":        "受診前に知っておきたい",
    "データ研究":        "数字で見る歯科のいま",
}

# ===== 歯科総研 ビジュアルシステム（SVG / 5色＋オレンジ・実写禁止）=====
# パレット: Deep Green #1F5D4C / Off White #F5F7F5 / Light Gray #E4E9E6
#          Silver #A9B3AE / Dental Blue #5C82A6 / Accent Orange #E5794C
_TOOTH = ('M112 62 C112 42 150 38 160 55 C170 38 208 42 208 62 '
          'C212 102 198 146 188 172 C184 183 175 183 173 172 '
          'L166 126 C163 116 157 116 154 126 L147 172 '
          'C145 183 136 183 132 172 C122 146 108 102 112 62 Z')

def _wrap(inner):
    return ('<svg viewBox="0 0 320 220" preserveAspectRatio="xMidYMid meet" '
            'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
            '<rect width="320" height="220" fill="#F5F7F5"/>' + inner + '</svg>')

SVG_PAIN = _wrap(
    f'<path d="{_TOOTH}" fill="#fff" stroke="#1F5D4C" stroke-width="2.4"/>'
    '<path d="M160 74 C158 94 160 120 160 150" fill="none" stroke="#E5794C" stroke-width="2.2" stroke-linecap="round"/>'
    '<path d="M160 92 C150 100 147 114 147 130 M160 92 C170 100 173 114 173 130" fill="none" stroke="#E5794C" stroke-width="1.5" opacity=".75" stroke-linecap="round"/>'
    '<circle cx="160" cy="74" r="4.5" fill="#E5794C"/>'
    '<path d="M236 58 l10 -10 M244 74 l14 -8 M238 92 l12 -3" stroke="#E5794C" stroke-width="2" stroke-linecap="round" opacity=".7"/>')

SVG_IMPLANT = _wrap(
    '<rect x="96" y="150" width="128" height="44" rx="16" fill="#E4E9E6"/>'
    '<path d="M132 60 C132 46 160 44 168 58 C176 44 200 48 200 62 C202 92 194 118 188 138 L146 138 C140 118 130 92 132 60 Z" fill="#fff" stroke="#1F5D4C" stroke-width="2.4"/>'
    '<rect x="150" y="130" width="20" height="58" rx="5" fill="#fff" stroke="#A9B3AE" stroke-width="2.2"/>'
    '<path d="M150 142 h20 M150 152 h20 M150 162 h20 M150 172 h20" stroke="#A9B3AE" stroke-width="1.6"/>'
    '<circle cx="160" cy="120" r="3.5" fill="#E5794C"/>')

SVG_ALIGN = _wrap(
    ''.join(f'<rect x="{x}" y="{92 - abs(i-3)*4}" width="20" height="{40 + abs(i-3)*4}" rx="8" fill="#fff" stroke="#1F5D4C" stroke-width="2.2"/>'
            for i, x in enumerate(range(84, 236, 25)))
    + '<path d="M78 96 C120 150 200 150 242 96" fill="none" stroke="#5C82A6" stroke-width="3" opacity=".55" stroke-linecap="round"/>')

SVG_PREVENT = _wrap(
    '<path d="M160 44 C186 60 214 62 214 62 C214 120 196 156 160 178 C124 156 106 120 106 62 C106 62 134 60 160 44 Z" fill="#fff" stroke="#1F5D4C" stroke-width="2.4"/>'
    '<path d="M140 108 l14 14 l28 -30" fill="none" stroke="#E5794C" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')

SVG_SELECT = _wrap(
    f'<path d="{_TOOTH}" fill="#fff" stroke="#1F5D4C" stroke-width="2.4" opacity=".9"/>'
    '<circle cx="196" cy="150" r="30" fill="#fff" stroke="#5C82A6" stroke-width="3"/>'
    '<path d="M218 172 l24 24" stroke="#5C82A6" stroke-width="4" stroke-linecap="round"/>'
    '<path d="M186 150 l7 7 l14 -15" fill="none" stroke="#E5794C" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>')

SVG_XRAY = _wrap(
    '<rect x="92" y="42" width="136" height="140" rx="14" fill="#fff" stroke="#A9B3AE" stroke-width="2" stroke-dasharray="2 7"/>'
    f'<path d="{_TOOTH}" fill="none" stroke="#5C82A6" stroke-width="2.2"/>'
    '<path d="M100 150 h120" stroke="#E5794C" stroke-width="2" opacity=".8"/>'
    '<circle cx="220" cy="150" r="3.5" fill="#E5794C"/>')

CAT_SVG = {
    "痛み・急なトラブル": SVG_PAIN,
    "矯正・審美":        SVG_ALIGN,
    "インプラント":      SVG_IMPLANT,
    "予防・こども":      SVG_PREVENT,
    "歯科医院の選び方":  SVG_SELECT,
    "歯科ガイド":        SVG_XRAY,
}

def esc(s):
    return html.escape(s, quote=True)

def cat_of(title):
    for c, kws in CAT_KW.items():
        if any(k in title for k in kws):
            return c
    return "歯科ガイド"

def clean_title(t):
    """タイトルから冗長な都市名を除去（サイト名で自明のため）"""
    t = re.sub("^【" + CITY + "?】\\s*", "", t)
    t = t.replace("｜" + CITY + "版", "").replace("｜" + CITY_SHORT + "版", "")
    t = t.replace(CITY_SHORT + "で使える", "使える")
    t = t.replace(CITY_SHORT + "で知る", "")
    t = t.replace(CITY_SHORT + "のインプラント", "インプラント")
    t = t.replace(CITY_SHORT + "ホワイトニング", "ホワイトニング")
    t = t.replace(CITY_SHORT + "の", "").replace(CITY_SHORT + "で", "").replace(CITY_SHORT, "")
    t = re.sub(r"｜\s*(市版|版)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

def nowrap_pipe(escaped_title):
    """esc()済みのタイトルに対して、｜直後で改行され孤立しないようnowrapを挿入"""
    return re.sub(r"(.)｜(.)", r'\1<span style="white-space:nowrap">｜\2</span>', escaped_title, count=1)

def scan_research():
    """articles/research/ の研究シリーズ記事をglobで自動検出して棚用の行にする。
    0件（ディレクトリ無し含む）なら空リスト＝棚ごと出さないフェイルセーフ。
    タイトル・日付は生成済みHTMLのJSON-LD/<title>から機械抽出（都市名ハードコードなし）。"""
    rdir = os.path.join(ART, "research")
    if not os.path.isdir(rdir):
        return []
    rows = []
    for f in sorted(os.listdir(rdir)):
        if not f.endswith(".html"):
            continue
        t = open(os.path.join(rdir, f), encoding="utf-8").read()
        m = re.search(r'"headline":\s*"([^"]+)"', t)
        if not m:
            m = re.search(r"<title>([^<｜|]+)", t)
        title = m.group(1).strip() if m else f[:-5]
        dm = re.search(r'"datePublished":\s*"(\d{4})-(\d{2})-(\d{2})"', t)
        row = {"f": "research/" + f, "title": title, "raw": title, "cat": "データ研究",
               "date": f"{dm.group(1)}.{dm.group(2)}.{dm.group(3)}" if dm else "",
               "sort_date": "-".join(dm.groups()) if dm else "", "rt": 0, "img": None}
        if f == "index.html":
            row["title"] = "データ研究トップ｜独自集計でみる歯科のいま"
            row["raw"] = row["title"]
            rows.insert(0, row)  # 研究トップは棚の先頭
        else:
            rows.append(row)
    top = [r for r in rows if r["f"].endswith("/index.html")]
    arts = sorted((r for r in rows if not r["f"].endswith("/index.html")),
                  key=lambda a: a["sort_date"], reverse=True)
    return top + arts


def scan():
    rows = []
    for f in sorted(os.listdir(ART), reverse=True):
        if not f.endswith(".html") or f == "index.html" or f.startswith("cat-"):
            continue
        t = open(os.path.join(ART, f), encoding="utf-8").read()
        title = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", f[:-5])
        if f in ARTICLE_DATES:
            y, mo, d = ARTICLE_DATES[f].split("-")
            date = f"{y}.{mo}.{d}"
        else:
            m = re.match(r"(\d{4})-(\d{2})-(\d{2})_", f)
            date = f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""
        chars = len(re.sub(r"<[^>]+>", "", t))
        rt = max(4, round(chars / 550))
        slug = f[:-5]
        img = None
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if os.path.exists(os.path.join(ART, "img", slug + ext)):
                img = "img/" + slug + ext; break
        rows.append({"f": f, "title": clean_title(title), "raw": title, "cat": cat_of(title),
                     "date": date, "sort_date": ARTICLE_DATES.get(f, ""), "rt": rt, "img": img})
    rows.sort(key=lambda a: a["sort_date"], reverse=True)
    return rows

CLOCK = '<svg class="ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>'
ARROW = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14M13 6l6 6-6 6"/></svg>'
ARROW_LEFT = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg>'
ARROW_RIGHT_BIG = '<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"/></svg>'

def cover(a):
    hook = ARTICLE_HOOKS.get(a["f"], "")
    hk = f'<span class="c-hook">{esc(hook)}</span>' if hook else ""
    if a.get("img"):
        return f'<span class="c-cover" style="background-image:url({urlq(a["img"])})">{hk}</span>'
    return f'<span class="c-cover c-cover-ph">{hk}</span>'

def card(a):
    col = CAT_COLOR.get(a["cat"], "#2E7D5B")
    return f'''      <a class="card" href="{urlq(a['f'])}">
        {cover(a)}
        <span class="c-body">
          <span class="c-cat" style="color:{col}">{esc(a['cat'])}</span>
          <span class="c-title">{esc(a['title'])}</span>
          <span class="c-meta"><span class="c-rt">{esc(CAT_HOOK.get(a['cat'], "受診前に知っておきたい"))}</span><span class="c-date">{esc(a['date'])}</span></span>
        </span>
      </a>'''

def soon_card(title):
    return f'''      <div class="card card-soon">
        <span class="c-cover c-cover-ph"></span>
        <span class="c-body">
          <span class="c-cat">準備中</span>
          <span class="c-title">{esc(title)}</span>
        </span>
      </div>'''

def section(title, sub, shown, href, new=False, pad=None, n=20):
    # Netflix風の横スクロール棚にするため「すべて見る」リンクは廃止し、
    # 代わりに棚の中によりの多くのカードを流し込む（スクロールで全件たどれる）
    cards = "\n".join(card(a) for a in shown[:n])
    if pad:
        cards += ("\n" if cards else "") + "\n".join(soon_card(t) for t in pad[:n - len(shown[:n])])
    badge = '<span class="new-badge">NEW</span>' if new else ""
    subhtml = f'<p class="sec-sub">{esc(sub)}</p>' if sub else ""
    sec_id = href.replace("cat-", "sec-").replace(".html", "")
    return f'''  <section class="sec" id="{sec_id}">
    <div class="sec-head">
      <div class="sec-head-l"><h2>{esc(title)}{badge}</h2>{subhtml}</div>
    </div>
    <div class="row-wrap">
      <button type="button" class="row-arrow row-arrow--prev" aria-label="前へ" onclick="rowScroll(this,-1)">{ARROW_LEFT}</button>
      <div class="row">
{cards}
      </div>
      <button type="button" class="row-arrow row-arrow--next" aria-label="次へ" onclick="rowScroll(this,1)">{ARROW_RIGHT_BIG}</button>
    </div>
  </section>'''

def build_cat_page(title, sub, arts, pad=None, href=""):
    cards = "\n".join(card(a) for a in arts)
    if pad:
        cards += ("\n" if cards else "") + "\n".join(soon_card(t) for t in pad)
    return (CAT_TEMPLATE.replace("{title}", esc(title)).replace("{sub}", esc(sub))
            .replace("{href}", href)
            .replace("{count}", str(len(arts))).replace("{cards}", cards)
            .replace("{SITE_NAME}", SITE_NAME).replace("{EN_INSTITUTE}", EN_INSTITUTE)
            .replace("{EN_UPPER}", EN_UPPER).replace("{CITY_SHORT}", CITY_SHORT)
            .replace("{DOMAIN}", DOMAIN))

def build():
    rows = scan()
    by = {}
    for a in rows:
        by.setdefault(a["cat"], []).append(a)

    def find(kw):
        return next((a for a in rows if kw in a["raw"]), None)

    def pick(kws):
        out, seen = [], set()
        for kw in kws:
            a = find(kw)
            if a and a["f"] not in seen:
                out.append(a); seen.add(a["f"])
        return out

    trend = pick([CITY_SHORT + "のインプラント費用", "歯周病治療の専門性", CITY_SHORT + "ホワイトニング",
                  "子どもの虫歯予防", "歯のクリーニング"])
    # キュレーション分を先頭に、残りを新着順で後ろに足して棚を満たす。
    # これで他の行（新着・急な痛み等）と同じように横スクロール＆右端が見切れる。
    _seen = {a["f"] for a in trend}
    trend += [a for a in rows if a["f"] not in _seen]
    select_all = by.get("歯科医院の選び方", []) + by.get("歯科ガイド", [])

    specs = [
        ("新着記事", "", rows, "latest", rows, True, None),
        ("よく読まれている記事", "", trend, "popular", rows, False, None),
        ("急な痛み・トラブル", "", by.get("痛み・急なトラブル", []), "pain", by.get("痛み・急なトラブル", []), False, None),
        ("インプラント", "", by.get("インプラント", []), "implant", by.get("インプラント", []), False, None),
        ("矯正・審美", "", by.get("矯正・審美", []), "cosmetic", by.get("矯正・審美", []), False, None),
        ("予防・こどものケア", "", by.get("予防・こども", []), "prevention", by.get("予防・こども", []), False, None),
        ("歯科医院の選び方", "", select_all, "select", select_all, False, None),
    ]

    sections = ""
    for title, sub, shown, slug, full, new, pad in specs:
        href = f"cat-{slug}.html"
        sections += ("\n" if sections else "") + section(title, sub, shown, href, new=new, pad=pad)
        open(os.path.join(ART, href), "w", encoding="utf-8").write(
            build_cat_page(title, sub if sub else title, full, pad=pad, href=href))

    # 研究シリーズの棚（articles/research/ の実ファイルを自動検出。0件なら棚ごと出さない）
    research = scan_research()
    research_tab = ""
    if research:
        sections += "\n" + section("研究シリーズ", "独自データの集計から見えた発見", research,
                                   "cat-research.html")
        research_tab = '\n    <a href="#sec-research">研究シリーズ</a>'

    # 新着記事の上に置くジャンプ用タブ（各セクションへスムーススクロール）
    tabs = ('  <nav class="col-tabs" aria-label="カテゴリ">\n'
            + "\n".join(f'    <a href="#sec-{slug}">{esc(title)}</a>'
                        for title, sub, shown, slug, full, new, pad in specs)
            + research_tab
            + '\n  </nav>')

    return (TEMPLATE.replace("{sections}", tabs + "\n" + sections)
            .replace("{SITE_NAME}", SITE_NAME).replace("{EN_INSTITUTE}", EN_INSTITUTE)
            .replace("{EN_UPPER}", EN_UPPER).replace("{CITY_SHORT}", CITY_SHORT)
            .replace("{DOMAIN}", DOMAIN))

# ================= CSS =================
STYLE = '''<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Noto+Sans+JP:wght@400;500;700&family=Shippori+Mincho:wght@600;700&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../assets/odr-ds.css">
<style>
:root{--ink:#1d1d1f;--ink-2:#565d5a;--ink-3:#8b928e;--line:#ECECEC;--paper:#fff;
  --pine:#1f4b3f;--pine-2:#2e6a58;--accent:#E5794C;}  /* ODR-DSと統一 */
*{box-sizing:border-box;}
body{margin:0;font-family:'Inter','Noto Sans JP','Hiragino Kaku Gothic ProN',sans-serif;
  color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility;}
a{text-decoration:none;color:inherit;}
.wrap-x{max-width:1440px;margin:0 auto;padding:0 clamp(14px,2.2vw,34px);}

/* ---- Nav：全ページ共通のodr-brandbar（assets/odr-ds.css）を使用。ページ固有CSSは持たない ---- */

/* ---- Hero ---- */
.hero{position:relative;overflow:hidden;color:#fff;zoom:1.05;
  background:
    radial-gradient(72% 105% at 82% 44%,rgba(62,139,113,.30) 0%,rgba(36,102,84,.16) 42%,transparent 72%),
    radial-gradient(54% 86% at 12% 36%,rgba(0,22,18,.26) 0%,transparent 72%),
    linear-gradient(105deg,#082f27 0%,#0d3a30 34%,#12483b 62%,#1b5d4c 100%);}
.hero::before{
  content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
  background:
    linear-gradient(90deg,rgba(4,31,25,.52) 0%,rgba(4,31,25,.22) 31%,rgba(4,31,25,0) 58%),
    radial-gradient(46% 78% at 78% 48%,rgba(92,169,141,.08),transparent 74%);
}
.hero-in{position:relative;z-index:2;padding:clamp(48px,7vw,84px) 0 clamp(40px,5vw,60px);max-width:620px;}
.hero .eyebrow{font-family:'Inter';font-size:.72rem;font-weight:600;letter-spacing:.22em;color:var(--accent);margin:0 0 18px;}
.hero h1{font-family:'Shippori Mincho',serif;font-weight:700;font-size:clamp(1.95rem,4.3vw,2.9rem);line-height:1.25;letter-spacing:.01em;margin:0 0 20px;}
.hero .lead{font-size:1rem;line-height:1.9;color:#d5e4dd;margin:0 0 30px;font-weight:400;}
.search{display:flex;align-items:center;gap:10px;max-width:400px;
  background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:13px 20px;}
.search svg{color:#bcd2c9;flex-shrink:0;}
.search input{flex:1;background:transparent;border:none;outline:none;color:#fff;font:inherit;font-size:.92rem;}
.search input::placeholder{color:#a7c1b6;}
.hero-art{position:absolute;right:clamp(-30px,-1vw,10px);top:50%;transform:translateY(-50%);z-index:1;
  width:min(38vw,440px);opacity:.32;pointer-events:none;}
@media(max-width:820px){.hero-art{display:none;}.hero-in{max-width:none;}}

/* ===== Clinical Guide hero: gradient only ===== */
.hero::after{display:none!important;}
.hero-art{display:none!important;}

/* ===== Globe star field ===== */
.hero-globe-stars{
  position:absolute;
  right:clamp(52px,5vw,92px);
  top:50%;
  transform:translateY(-50%);
  width:min(47vw,620px);
  height:88%;
  pointer-events:none;
  z-index:1;
}
.hero-globe-stars span{
  position:absolute;
  left:var(--x);
  top:var(--y);
  width:var(--s);
  height:var(--s);
  border-radius:50%;
  background:rgba(255,235,189,.96);
  box-shadow:
    0 0 4px rgba(255,225,156,.82),
    0 0 10px rgba(231,190,118,.48),
    0 0 18px rgba(105,213,178,.18);
  opacity:var(--o,.82);
}
.hero-globe-stars span::before,
.hero-globe-stars span::after{
  content:"";
  position:absolute;
  left:50%;top:50%;
  transform:translate(-50%,-50%);
  background:rgba(255,235,196,.38);
  border-radius:999px;
}
.hero-globe-stars span::before{width:calc(var(--s) * 5.2);height:1px;}
.hero-globe-stars span::after{width:1px;height:calc(var(--s) * 5.2);}
.hero-globe-stars .dot::before,
.hero-globe-stars .dot::after{display:none;}
@media(max-width:1200px){
  .hero-globe-stars{right:24px;width:min(48vw,540px);}
}
@media(max-width:980px){
  .hero-globe-stars{right:4px;width:min(49vw,440px);opacity:.72;}
}
@media(max-width:820px){
  .hero-globe-stars{display:none;}
}

/* ===== Final hero alignment / globe glow ===== */
@media (min-width: 981px){
  .hero-in{
    margin-left:clamp(34px,3.4vw,58px);
  }
}
@media (min-width: 821px) and (max-width: 980px){
  .hero-in{margin-left:24px;}
}

/* ---- Sections ---- */
html{scroll-behavior:smooth;}
main.wrap-x{padding-top:clamp(15px,2.1vw,23px);padding-bottom:90px;}
/* 新着記事の上のジャンプ用タブ */
.col-tabs{display:flex;gap:8px;overflow-x:auto;margin:0 0 clamp(15px,2.25vw,24px);padding-bottom:6px;scrollbar-width:none;}
.col-tabs::-webkit-scrollbar{display:none;}
.col-tabs a{flex:0 0 auto;font-size:.84rem;font-weight:600;color:var(--ink-2);background:#FDF4EE;
  padding:8px 15px;border:1px solid var(--accent);border-radius:999px;white-space:nowrap;
  transition:background .15s,color .15s,border-color .15s;}
.col-tabs a:hover{background:var(--accent);color:#fff;border-color:var(--accent);}
.sec{margin:0 0 clamp(10px,1.5vw,16px);scroll-margin-top:84px;}
.sec-head{display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin:0 0 8px;}
.sec-head h2{font-size:1.16rem;font-weight:700;margin:0;letter-spacing:.01em;display:inline-flex;align-items:center;gap:10px;}
.new-badge{font-family:'Inter';font-size:.62rem;font-weight:700;letter-spacing:.05em;color:var(--accent);
  border:1px solid #f0c6b2;border-radius:5px;padding:2px 6px;}
.sec-sub{font-size:.84rem;color:var(--ink-3);margin:6px 0 0;}
.sec-all{font-size:.82rem;font-weight:500;color:var(--pine-2);display:inline-flex;align-items:center;gap:5px;transition:gap .15s;white-space:nowrap;}
.sec-all:hover{gap:9px;}

/* Netflix風の横スクロール棚（全画面幅で共通） */
.row{
  display:flex;justify-content:flex-start;gap:14px;overflow-x:auto;scroll-snap-type:x proximity;
  padding-top:12px;padding-bottom:16px;margin:-12px calc(-1*clamp(14px,2.2vw,34px)) 0 0;
  padding-left:0;padding-right:clamp(14px,2.2vw,34px);
  scrollbar-width:thin;
}
.row>*{flex:0 0 auto;width:min(250px,80vw);scroll-snap-align:start;}
.row::-webkit-scrollbar{height:6px;}
.row::-webkit-scrollbar-thumb{background:var(--line);border-radius:3px;}
.row::-webkit-scrollbar-thumb:hover{background:var(--ink-3);}

/* Netflix風：ホバーで矢印を表示、クリックで横スクロール */
.row-wrap{position:relative;}
.row-arrow{
  position:absolute;top:0;bottom:10px;width:56px;z-index:2;
  display:flex;align-items:center;justify-content:center;
  border:none;background:transparent;color:var(--ink,#222);cursor:pointer;
  opacity:0;transition:opacity .2s;
}
.row-arrow svg{
  background:#fff;border-radius:50%;padding:9px;width:40px;height:40px;box-sizing:border-box;
  box-shadow:0 2px 10px rgba(20,20,25,.18);transition:transform .18s ease;
}
.row-arrow:hover svg{transform:scale(1.18);}
.row-wrap:hover .row-arrow{opacity:1;}
.row-arrow--prev{left:0;justify-content:flex-start;padding-left:8px;}
.row-arrow--next{right:0;justify-content:flex-end;padding-right:8px;}
@media(hover:none){.row-arrow{display:none;}}  /* タッチデバイスは手動スワイプのみ */
.cat-all-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:24px;margin-top:2rem;}

/* ---- Card ---- */
.card{position:relative;display:flex;flex-direction:column;background:#fff;border:1px solid var(--line);border-radius:14px;
  overflow:hidden;transition:border-color .2s,box-shadow .2s,transform .2s;}
.card:hover{border-color:#e0e0dd;box-shadow:0 16px 38px rgba(20,20,25,.14);transform:translateY(-4px) scale(1.045);z-index:4;}
.c-cover{position:relative;display:block;aspect-ratio:16/9;background-size:cover;background-position:center;background-color:#eef1ef;overflow:hidden;border-radius:14px 14px 0 0;}
.c-cover-ph{background:linear-gradient(135deg,#eef2f0,#e3e9e6);}
/* ホバーで出る「え、なんだろう」フック（カバー下部にふわっと） */
.c-hook{position:absolute;left:0;right:0;bottom:0;padding:14px 12px 10px;
  background:linear-gradient(to top,rgba(12,28,22,.9) 12%,rgba(12,28,22,.55) 55%,transparent);
  color:#fff;font-size:.8rem;font-weight:600;line-height:1.5;letter-spacing:.01em;
  opacity:0;transform:translateY(8px);transition:opacity .22s ease,transform .22s ease;pointer-events:none;}
.card:hover .c-hook{opacity:1;transform:translateY(0);}
@media(hover:none){.c-hook{display:none;}}
.c-body{padding:12px 14px 13px;display:flex;flex-direction:column;gap:7px;flex:1;}
.c-cat{font-size:.68rem;font-weight:700;letter-spacing:.02em;}
.c-title{font-size:.92rem;font-weight:500;line-height:1.5;color:var(--ink);letter-spacing:.005em;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}
.c-meta{margin-top:auto;padding-top:4px;display:flex;align-items:center;justify-content:space-between;
  font-family:'Inter';font-size:.7rem;color:var(--ink-3);}
.c-rt{display:inline-flex;align-items:center;gap:5px;}
.c-rt .ic{opacity:.75;}
.card-soon{border-style:dashed;}
.card-soon:hover{border-color:var(--line);box-shadow:none;transform:none;}
.card-soon .c-cat{color:var(--ink-3);}
.card-soon .c-title{color:var(--ink-3);font-weight:400;}

html.text-lg .c-title{font-size:1.1rem;}
html.text-xl .c-title{font-size:1.2rem;}

/* ---- Footer ---- */
.site-footer{background:#f7f8f7;border-top:1px solid var(--line);padding:52px 0 34px;margin-top:20px;}
.foot-name{font-weight:700;font-size:1rem;margin:0 0 10px;}
.foot-note{font-size:.82rem;color:var(--ink-3);line-height:1.9;max-width:640px;margin:0 0 18px;}
.foot-copy{font-family:'Inter';font-size:.74rem;color:var(--ink-3);border-top:1px solid var(--line);padding-top:16px;margin:0;}

/* ===== 改行・可読性の共通ルール（改行マニュアル v1.0） ===== */
h1,h2,h3,h4,h5,p,li,dd,figcaption,td,th,
.lead,.sec-lead,.step-desc,.cta-sub,.hero-sub,.hero .lead,.hero p{
  line-break:strict;      /* 日本語の禁則処理 */
  text-wrap:pretty;       /* 1文字残り・不自然に短い最終行を自動回避 */
}
h1,h2,h3{ text-wrap:balance; }   /* 見出しは各行の長さを均等に */
</style>'''

ART_SVG = '''<svg class="hero-art" viewBox="0 0 440 320" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <g stroke="#cfe3da" stroke-width="1.4" fill="none" opacity="0.9">
    <path d="M220 84 C170 58 96 58 46 82 L46 250 C96 226 170 226 220 252 C270 226 344 226 394 250 L394 82 C344 58 270 58 220 84 Z"/>
    <path d="M220 84 L220 252"/>
    <path d="M74 108 C112 96 156 96 196 112 M74 140 C112 128 156 128 196 144 M74 172 C112 160 156 160 196 176"/>
    <path d="M244 112 C284 96 328 96 366 108 M244 144 C284 128 328 128 366 140"/>
    <path d="M300 150 C300 138 322 138 322 150 C324 176 330 188 320 196 C314 200 308 200 302 196 C292 188 298 176 300 150 Z"/>
    <circle cx="330" cy="196" r="20"/><path d="M344 210 L360 226"/>
  </g>
</svg>'''

NAV = '''<header class="odr-brandbar odr-scope">
  <a class="odr-sig" href="../index.html">
    <span class="odr-sig-mark">ODR</span>
    <span class="odr-sig-name">{SITE_NAME}<small>{EN_INSTITUTE}</small></span>
  </a>
  <nav>
    <a href="shindan/index.html">ランキング・AI診断</a>
    <a href="features/index.html">特徴から探す</a>
    <a class="on" href="index.html">コラム</a>
    <a href="../network.html">展開エリア</a>
    <a href="../shikumi.html">医院・開業医の方へ</a>
  </nav>
</header>'''

FOOTER = '''<footer class="site-footer">
  <div class="wrap-x">
    <p class="foot-name">{SITE_NAME}</p>
    <p class="foot-note">当サイトの情報は歯医者選びの一般的な参考情報であり、診断や治療方針の決定を目的としたものではありません。症状やお悩みについては、必ず歯科医師にご相談ください。詳細は<a href="../policy.html" style="color:inherit;text-decoration:underline;">運営ポリシー・免責事項</a>をご覧ください。</p>
    <p class="foot-copy">© {SITE_NAME} {EN_UPPER}</p>
  </div>
</footer>
<script>
var si=document.getElementById('search');
if(si){si.addEventListener('input',function(){
  var q=si.value.trim().toLowerCase();
  document.querySelectorAll('.sec').forEach(function(sec){
    var hit=0;
    sec.querySelectorAll('.card').forEach(function(c){
      var on=!q||(c.textContent.toLowerCase().indexOf(q)>=0);
      c.style.display=on?'':'none'; if(on&&!c.classList.contains('card-soon'))hit++;
    });
    sec.style.display=(!q||hit>0)?'':'none';
  });
});}

function rowScroll(btn, dir){
  var row = btn.parentElement.querySelector('.row');
  if(!row) return;
  var amount = row.clientWidth * 0.9;
  row.scrollBy({left: dir * amount, behavior: 'smooth'});
}
</script>'''

TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>歯科コラム | {SITE_NAME}</title>
<meta name="description" content="症状や治療の基礎知識、歯科医院の選び方まで。{CITY_SHORT}で後悔しない歯科選びに役立つ情報をお届けします。">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="歯科コラム | {SITE_NAME}">
<meta property="og:description" content="症状や治療の基礎知識、歯科医院の選び方まで。{CITY_SHORT}で後悔しない歯科選びに役立つ情報をお届けします。">
<meta property="og:url" content="https://{DOMAIN}/articles/index.html">
<link rel="canonical" href="https://{DOMAIN}/articles/index.html">
<meta name="twitter:card" content="summary">
''' + STYLE + '''
<script src="../assets/site-config.js"></script>
<script src="../assets/odr-track.js"></script>
</head>
<body>
''' + NAV + '''
<section class="hero">
  <div class="wrap-x">
    <div class="hero-in">
      <p class="eyebrow">CLINICAL GUIDE</p>
      <h1>歯科医院選びに、確かな知識を。</h1>
      <p class="lead">正しい知識は、納得できる歯科医院選びにつながります。<br>{SITE_NAME}では、症状・治療・医院選びに役立つ情報を、<br>口コミや公開情報、AI分析の視点から整理しています。</p>
      <div class="search">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>
        <input id="search" type="text" placeholder="症状・治療名で探す" aria-label="記事を検索">
      </div>
    </div>
  </div>

  <div class="hero-globe-stars" aria-hidden="true">
    <span style="--x:6%;--y:16%;--s:3px;--o:.74"></span>
    <span class="dot" style="--x:14%;--y:29%;--s:2px;--o:.58"></span>
    <span style="--x:22%;--y:9%;--s:2px;--o:.68"></span>
    <span class="dot" style="--x:31%;--y:21%;--s:3px;--o:.55"></span>
    <span style="--x:43%;--y:7%;--s:4px;--o:.88"></span>
    <span class="dot" style="--x:56%;--y:15%;--s:2px;--o:.54"></span>
    <span style="--x:68%;--y:5%;--s:3px;--o:.75"></span>
    <span class="dot" style="--x:80%;--y:20%;--s:2px;--o:.60"></span>
    <span style="--x:91%;--y:10%;--s:3px;--o:.82"></span>
    <span class="dot" style="--x:10%;--y:48%;--s:2px;--o:.50"></span>
    <span style="--x:18%;--y:62%;--s:3px;--o:.72"></span>
    <span class="dot" style="--x:30%;--y:75%;--s:2px;--o:.58"></span>
    <span style="--x:47%;--y:86%;--s:3px;--o:.78"></span>
    <span class="dot" style="--x:59%;--y:71%;--s:2px;--o:.55"></span>
    <span style="--x:73%;--y:81%;--s:4px;--o:.84"></span>
    <span class="dot" style="--x:86%;--y:69%;--s:2px;--o:.60"></span>
    <span style="--x:95%;--y:55%;--s:3px;--o:.76"></span>
    <span class="dot" style="--x:38%;--y:45%;--s:2px;--o:.44"></span>
    <span style="--x:83%;--y:39%;--s:3px;--o:.68"></span>
  </div>
</section>

<main class="wrap-x">
{sections}
</main>
''' + FOOTER + '''
</body>
</html>'''

CAT_TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} | {SITE_NAME} コラム</title>
<meta name="description" content="{title}に関する{CITY_SHORT}の歯科コラム記事一覧。">
<link rel="canonical" href="https://{DOMAIN}/articles/{href}">
''' + STYLE + '''
<script src="../assets/site-config.js"></script>
<script src="../assets/odr-track.js"></script>
</head>
<body>
''' + NAV + '''
<section class="hero">
  ''' + ART_SVG + '''
  <div class="wrap-x">
    <div class="hero-in">
      <p class="eyebrow">CLINICAL GUIDE</p>
      <h1>{title}</h1>
      <p class="lead">{sub}（全{count}件）</p>
    </div>
  </div>
</section>
<main class="wrap-x">
  <div class="cat-all-grid">
{cards}
  </div>
</main>
''' + FOOTER + '''
</body>
</html>'''

if __name__ == "__main__":
    open(os.path.join(ART, "index.html"), "w", encoding="utf-8").write(build())
    print("✅ articles/index.html と各カテゴリーページ(cat-*.html)を再生成しました")
