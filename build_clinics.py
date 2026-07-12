# -*- coding: utf-8 -*-
"""
医院プロフィールページを clinic_db.json から生成（AI Research Report 版 v5）。
【方針】AIの推測・分析は掲載してよいが、必ず根拠のあるデータに基づくこと。
根拠が無く空になっているフィールドは、セクションごと自動で非表示にする
（＝根拠のない断定を表示しない）。研究レポートの体裁で、軸別スコアを
可視化し、Apple風の余白で「研究機関らしさ」を前面に出す。
出力: articles/clinics/<slug>.html
"""
import os, re, json, html
from urllib.parse import quote

from evidence_grounding import (
    ground_claim, evening_hours, weekend_hours, parking_fact,
    station_walk_min, latest_closing_minutes,
    scan_summary_claims, summary_has_contradiction,
)
# 薄いページ（scaled content abuse）対策の判定正本（2026-07-13）。
# 実データが閾値未満の院ページは noindex,follow＋sitemap除外（thin_page_policy.py参照）。
from thin_page_policy import is_thin, has_substantive_ai


# 区別ランディングページへの内部リンク用（build_area_pages.pyのWARDSと対応）
WARD_SLUGS = {
    "北区":"kita","中央区":"chuo","西区":"nishi","福島区":"fukushima","天王寺区":"tennoji",
    "阿倍野区":"abeno","浪速区":"naniwa","淀川区":"yodogawa","東淀川区":"higashiyodogawa",
    "都島区":"miyakojima","此花区":"konohana","港区":"minato","大正区":"taisho",
    "西淀川区":"nishiyodogawa","東成区":"higashinari","生野区":"ikuno","旭区":"asahi",
    "城東区":"joto","鶴見区":"tsurumi","住之江区":"suminoe","住吉区":"sumiyoshi",
    "東住吉区":"higashisumiyoshi","平野区":"hirano","西成区":"nishinari",
}

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
SITE_CFG = json.load(open(os.path.join(ROOT, "site_config.json"), encoding="utf-8"))
CITY_SHORT = SITE_CFG.get("city_short", SITE_CFG.get("city", ""))
N_PUBLISHED = SITE_CFG.get("stats", {}).get("clinics_published", 0)
DOMAIN = SITE_CFG.get("domain", "shikasoken.com")
CITY = SITE_CFG.get("city", "")                # 例: 大阪市 / 神戸市 / 北播磨エリア
SITE_NAME = SITE_CFG.get("site_name", "")      # 例: 大阪歯科総研
EN_UPPER = SITE_CFG.get("site_name_en", "")    # 例: OSAKA DENTAL RESEARCH
# 例: Osaka Dental Research Institute（site_name_enから機械導出。ハイフン語は各パートを大文字化）
EN_INSTITUTE = " ".join("-".join(p.capitalize() for p in w.split("-")) for w in EN_UPPER.split()) + " Institute"
# 都道府県（構造化データのaddressRegion用）。site_config.jsonのprefは必須キー
# （新都市追加時はsite_config.jsonにprefを必ず足すこと。横展開マニュアル§4-c参照）
PREF = SITE_CFG.get("pref", "")

# schemaのtelephoneから除外する「複数院で共有されている電話番号」
# （コールトラッキング・フランチャイズ共通窓口等。NAP一貫性を壊すためschemaに入れない。
# 表示側の電話番号はこれまで通り出す）。main()で実DBから機械的に算出する。
SHARED_PHONES = set()

# データ研究ページ（build_data_report.py）を持つサイトでのみリンクを出す
# （未展開の都市サイトで404リンクを量産しない。2026-07-13）
HAS_RESEARCH = os.path.exists(os.path.join(ROOT, "articles", "research", "index.html"))
OUT = os.path.join(ROOT, "articles", "clinics")
SLUG_MAP_PATH = os.path.join(ROOT, "clinic_slugs.json")
with open(SLUG_MAP_PATH, encoding="utf-8") as _f:
    SLUG_MAP = json.load(_f)  # place_id -> 一意なslug（generate_slug_map.py参照。同姓同名の医院URL衝突対策）

def nowrap_pipe(escaped_title):
    """タイトルと副題がきれいに分かれるよう、｜の直前、または？／！の直後(都市名の前)で改行する"""
    import re as _re
    if "｜" in escaped_title:
        return escaped_title.replace("｜", "<br>｜", 1)
    return _re.sub("([？！])" + CITY_SHORT, "\\1<br>" + CITY_SHORT, escaped_title, count=1)

def esc(s):
    return html.escape(str(s), quote=True)

def slugify(name):
    return re.sub(r'[\\/:*?"<>|　\s・。、]', '_', name)[:60]

PATIENT_AXES = ["技術力","説明力","清潔感","優しさ","子ども対応","痛みへの配慮","待ち時間"]
DOCTOR_AXES  = ["専門性","研究実績","患者目線","経験"]
# AI縦掘り分析（vertical_analysis.py）の項目。根拠のある値(>0)だけ表示する。
EQUIP_KEYS = ["CT","マイクロスコープ","口腔内スキャナー","個室","駐車場","バリアフリー"]
FIT_KEYS   = ["子ども連れ","歯科が怖い人","短時間で済ませたい","自由診療も検討","保険中心"]

# ── 特徴ページ（build_features.py）へのタグ相互リンク ──
# build_features.py の EQUIP_KEYS / CATEGORIES と対応するアンカーID
EQUIP_ANCHOR = {"CT":"ct","マイクロスコープ":"micro","個室":"private","駐車場":"parking","バリアフリー":"barrier"}
SPECIALTY_ANCHOR_GROUPS = [
    ("implant", {"インプラント","インプラント治療","オールオンフォー","インプラント埋入","オールオン4","オールオン6"}, "インプラント治療を行っている医院"),
    ("ortho",   {"矯正歯科","矯正治療","歯列矯正","マウスピース矯正","小児矯正","成人矯正","ワイヤー矯正","インビザライン","裏側矯正","矯正"}, "矯正歯科に対応している医院"),
    ("kids",    {"小児歯科","小児矯正","小児予防歯科"}, "小児歯科に対応している医院"),
    ("prevent", {"予防歯科","予防処置","定期健診","クリーニング","PMTC","予防"}, "予防歯科に力を入れている医院"),
    ("esthetic",{"審美歯科","審美治療","ホワイトニング","セラミック治療","セラミック","審美"}, "審美・ホワイトニングに対応している医院"),
]

import math

def compute_metrics(c):
    """研究レポートとしての4指標：Confidence / Evidence / Research Sources / Patient Fit。
    ★評価やランキングではなく、データの充実度と根拠の強さを示す。"""
    reviews = c.get("total_reviews", 0) or 0
    deep = bool(c.get("deep_fetched"))
    tr = c.get("transparency_score")
    eq = c.get("equipment_score")

    confidence = 50
    confidence += 20 if deep else 0
    confidence += 8 if tr is not None else 0
    confidence += 8 if eq is not None else 0
    confidence += min(14, math.log10(reviews + 1) * 7)
    confidence = max(0, min(100, round(confidence)))

    evidence = "強力" if confidence >= 88 else ("良好" if confidence >= 76 else "限定的")

    ps = c.get("patient_scores") or {}
    es = c.get("equipment_stars") or {}
    tags_present = bool(c.get("specialty_tags"))
    research_sources = sum([
        1 if reviews > 0 else 0,
        1 if deep else 0,
        1 if any((v or 0) > 0 for v in ps.values()) else 0,
        1 if any((v or 0) > 0 for v in es.values()) else 0,
        1 if tags_present else 0,
    ])

    ps_vals = [v for v in ps.values() if (v or 0) > 0]
    patient_fit = round(sum(ps_vals) / len(ps_vals)) if ps_vals else None

    return {
        "confidence": confidence,
        "evidence": evidence,
        "research_sources": research_sources,
        "patient_fit": patient_fit,
    }

def bar_rows(scores, keys, maxv):
    """0-maxv の値を横バーに。値0（根拠なし）は出さない。maxv=100 or 5。"""
    rows = ""
    for k in keys:
        raw = (scores or {}).get(k, 0) or 0
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v <= 0:
            continue
        pct = max(0, min(100, v / maxv * 100))
        disp = (str(int(v)) if maxv == 100 else f"{v:g}")
        rows += (f'<div class="rr-bar"><span class="rr-bar-k">{esc(k)}</span>'
                 f'<span class="rr-bar-track"><span class="rr-bar-fill" style="width:{pct:.0f}%"></span></span>'
                 f'<span class="rr-bar-v">{disp}{"" if maxv==100 else "/5"}</span></div>')
    return rows

def chips(tags):
    return "".join(f'<span class="rr-chip">{esc(t)}</span>' for t in (tags or []) if t)

def findings(items):
    """主要所見を✔リストで。"""
    return "".join(f'<li>{esc(x)}</li>' for x in (items or []) if x)

def li(items):
    return "".join(f"<li>{esc(x)}</li>" for x in (items or []) if x)

SRC_NOTE = ('<p class="rr-note">※ 公式サイト・Google口コミなどの公開情報にもとづく'
            'AI分析です。根拠が確認できなかった設備・特徴は表示していません。</p>')

# ── 構造化データ用ヘルパー（2026-07-13 MEO是正） ──
_DAY_EN = {"月": "Monday", "火": "Tuesday", "水": "Wednesday", "木": "Thursday",
           "金": "Friday", "土": "Saturday", "日": "Sunday"}
_HOURS_RE = re.compile(r"(\d{1,2})時(\d{1,2})分?[～〜~](\d{1,2})時(\d{1,2})分?")

def hours_to_schema(hours):
    """Google由来の日本語診療時間（例「月曜日: 9時30分～12時30分, 14時00分～18時30分」）を
    schema.orgのOpeningHoursSpecificationに変換する。定休日・解析不能行は出力しない
    （誤った時刻を出すくらいなら出さない）。"""
    specs = []
    for line in hours or []:
        line = str(line)
        day = _DAY_EN.get(line[:1])
        if not day or "定休" in line or "休診" in line:
            continue
        for m in _HOURS_RE.finditer(line):
            h1, m1, h2, m2 = (int(x) for x in m.groups())
            if not (0 <= h1 <= 23 and 0 <= h2 <= 24 and 0 <= m1 <= 59 and 0 <= m2 <= 59):
                continue
            specs.append({
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": f"https://schema.org/{day}",
                "opens": f"{h1:02d}:{m1:02d}",
                "closes": f"{h2:02d}:{m2:02d}",
            })
    return specs

_ZIP_RE = re.compile(r"〒?\s*(\d{3})[-‐－ー−]?(\d{4})\s*")
_LOCALITY_RE = re.compile(r"^([一-龥ぁ-んァ-ヶA-Za-z]+?市)?([一-龥ぁ-んァ-ヶ]+?区)?([一-龥ぁ-んァ-ヶ]+?郡[一-龥ぁ-んァ-ヶ]+?[町村])?")

def address_to_schema(addr):
    """住所文字列をPostalAddressに分解する。addressLocality=市（＋区）、
    addressRegion=都道府県、postalCode=判明分のみ（無ければ出さない＝捏造しない）。"""
    import unicodedata
    a = unicodedata.normalize("NFKC", (addr or "").strip())
    a = re.sub(r"^日本[、,]\s*", "", a)  # Google由来の「日本、〒…」表記
    out = {"@type": "PostalAddress"}
    m = _ZIP_RE.search(a)
    if m:
        out["postalCode"] = f"{m.group(1)}-{m.group(2)}"
        a = a.replace(m.group(0), "", 1).strip()
    if PREF and a.startswith(PREF):
        a = a[len(PREF):].strip()
    elif PREF and PREF in a:
        tail = a[a.index(PREF) + len(PREF):].strip()
        if len(tail) >= 6:
            # 「〒1F 〇〇県〇〇市…」のような先頭ゴミは府県名から後ろを採用する
            a = tail
        else:
            # 逆順住所（「…〇〇区 〇〇市 〇〇県」）は府県名だけ除去して全体を残す
            a = a.replace(PREF, "").strip()
    lm = _LOCALITY_RE.match(a)
    locality = "".join(g for g in lm.groups() if g) if lm else ""
    if locality:
        out["addressLocality"] = locality
        a = a[len(locality):].strip()
    else:
        # 住所の並びが崩れているレコード（例「…〇〇区 〇〇市」）から市・区だけ拾う。
        # streetAddressは崩れたまま全文を残す（下手に削って壊さない）
        mc = re.search(r"([一-龥ぁ-んァ-ヶ]{1,6}市)", a)
        mw = re.search(r"([一-龥ぁ-んァ-ヶ]{1,4}区)", a)
        guessed = (mc.group(1) if mc else "") + (mw.group(1) if mw else "")
        if guessed:
            out["addressLocality"] = guessed
    if PREF:
        out["addressRegion"] = PREF
    out["addressCountry"] = "JP"
    if a:
        out["streetAddress"] = a
    return out

def page_url_of(slug):
    """院ページの正規URL。canonical / og:url / JSON-LD url / Breadcrumb の
    4箇所すべてこの1本を使う（表記ゆれ＝重複URL候補の量産を防ぐ。2026-07-13統一）。
    日本語slugはパーセントエンコードした形を正とする。"""
    return f"https://{DOMAIN}/articles/clinics/{quote(slug)}.html"

def build_jsonld(c, slug):
    """Google検索のリッチリザルト向け構造化データ（JSON-LD, schema.org/Dentist）。
    緯度経度（Nominatimで取得済み）・住所・電話・診療時間を機械可読で埋め込む。
    ※2026-07-10：aggregateRatingを撤去。Googleの規約ではLocalBusiness系の
    レビュー評価は「自サイトで直接収集したもの」に限られ、Googleマップ由来の
    評価のマークアップは規約違反（手動対策の火種）のため。表示テキストとしての
    口コミ数値は問題ない（マークアップしないだけ）。第一者（自社収集）の実口コミを
    持たない限り、aggregateRating/reviewは今後も入れないこと。
    ※2026-07-13：openingHoursを日本語文からOpeningHoursSpecification正規形に変更。
    住所をPostalAddressに分解（locality/postalCode）。複数院で共有される電話番号
    （トラッキング・共通窓口）はNAP汚染のためtelephoneに入れない。publisherに運営者
    (Organization)を宣言してエンティティの一貫性を出す。"""
    import json as _json
    page_url = page_url_of(slug)
    data = {
        "@context": "https://schema.org",
        "@type": "Dentist",
        "name": c.get("name", ""),
        "url": page_url,
    }
    if c.get("address"):
        data["address"] = address_to_schema(c["address"])
    if c.get("latitude") and c.get("longitude"):
        data["geo"] = {"@type": "GeoCoordinates", "latitude": c["latitude"], "longitude": c["longitude"]}
    phone = (c.get("phone") or "").strip()
    if phone and phone not in SHARED_PHONES:
        data["telephone"] = phone
    hours = c.get("business_hours") or []
    if isinstance(hours, list) and hours:
        specs = hours_to_schema(hours[:7])
        if specs:
            data["openingHoursSpecification"] = specs
    site_name = SITE_NAME
    domain = DOMAIN
    data["publisher"] = {
        "@type": "Organization",
        "name": site_name,
        "url": f"https://{domain}/",
    }

    # 2026-07-10（Google評価施策E2）：パンくず＋データ由来のFAQをJSON-LDで宣言。
    # FAQリッチリザルトは一般サイト対象外だが、AI検索の回答抽出には効く
    # （調査：FAQ形式は関連クエリでの引用率が高い）。回答はDBの事実のみ・断定しない。
    breadcrumb = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": site_name, "item": f"https://{domain}/"},
            {"@type": "ListItem", "position": 2, "name": "医院分析", "item": f"https://{domain}/articles/features/index.html"},
            {"@type": "ListItem", "position": 3, "name": c.get("name", ""), "item": page_url},
        ],
    }
    faqs = []
    hours = c.get("business_hours") or []
    if isinstance(hours, str):
        hours = [hours] if hours else []
    if hours:
        faqs.append((f'{c.get("name","")}の診療時間は？',
                     " / ".join(hours[:7]) + "（変更される場合があります。受診前に医院へご確認ください）"))
    # アクセスFAQ（患者目線・2026-07-11改修）：駅が徒歩圏(1.2km)ならこれまで通り。
    # 徒歩圏に駅がない医院は、患者が実際に使う目安（バス停→IC→車）に切り替える。
    ns = c.get("nearest_station") or {}
    if ns.get("name"):
        dist = ns.get("straight_distance_m")
        if dist is not None and dist > 1200:
            bus = c.get("nearest_bus_stop") or {}
            ic = c.get("nearest_ic") or {}
            if bus.get("name") and (bus.get("distance_m") or 9999) <= 500:
                mins = max(1, -(-bus["distance_m"] // 80))
                faqs.append((f'{c.get("name","")}へのアクセスは？',
                             f'バス停「{bus["name"]}」から徒歩約{mins}分の目安です（当サイト算出）。お車の場合は駐車場の有無を医院にご確認ください。'))
            elif ic.get("name") and (ic.get("distance_m") or 99999) <= 8000:
                mins = max(1, -(-ic["distance_m"] // 500))
                faqs.append((f'{c.get("name","")}へのアクセスは？',
                             f'{ic["name"]}から車で約{mins}分の目安です（当サイト算出）。駐車場の有無は医院にご確認ください。'))
            else:
                mins = max(1, -(-dist // 500))
                faqs.append((f'{c.get("name","")}へのアクセスは？',
                             f'{ns["name"]}駅から車で約{mins}分の目安です（当サイト算出）。'))
        else:
            dist_txt = f"（直線距離 約{dist}m・当サイト算出の目安）" if dist else ""
            faqs.append((f'{c.get("name","")}の最寄駅は？', f'{ns["name"]}駅{dist_txt}です。'))
    es = c.get("equipment_stars") or {}
    eq_list = [k for k in ("CT", "マイクロスコープ", "口腔内スキャナー", "個室") if (es.get(k) or 0) >= 3]
    if eq_list:
        faqs.append((f'{c.get("name","")}の設備は？',
                     "公式サイトの記載から " + "・".join(eq_list) + " が確認できています（当サイト解析時点）。"))
    out = ('<script type="application/ld+json">' + _json.dumps(data, ensure_ascii=False) + "</script>"
           + '<script type="application/ld+json">' + _json.dumps(breadcrumb, ensure_ascii=False) + "</script>")
    if len(faqs) >= 2:
        faq_schema = {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in faqs],
        }
        out += '<script type="application/ld+json">' + _json.dumps(faq_schema, ensure_ascii=False) + "</script>"
    return out


# ── 区別データ集計（2026-07-10 Google評価施策E1：Area Context） ──
# 各医院ページに「その医院×その区」でしか作れない一意の統計文脈を挿入する。
# 量産テンプレページの「薄さ」を一次データの文脈で反転させるのが狙い。
# 順位・優劣は出さない（設備・対応の事実と区内割合のみ＝法務安全）。
import re as _re
_WARD_STATS = {}

def _ward_key(addr):
    m = _re.search(CITY + r'([一-龥]+区)', addr or "")
    return m.group(1) if m else None

def _has_night(c):
    return any("夜間" in t for t in (c.get("specialty_tags") or []) + (c.get("site_features") or []))

def compute_ward_stats(clinics):
    """区ごとの 医院数・CT/マイクロスコープ導入率・夜間対応率を事前集計"""
    global _WARD_STATS
    groups = {}
    for c in clinics:
        if c.get("q_excluded") or not c.get("name"):
            continue
        w = _ward_key(c.get("address", ""))
        if not w:
            continue
        groups.setdefault(w, []).append(c)
    for w, cs in groups.items():
        eq = [c for c in cs if isinstance(c.get("equipment_stars"), dict) and c["equipment_stars"]]
        _WARD_STATS[w] = {
            "n": len(cs),
            "eq_n": len(eq),
            "ct": sum(1 for c in eq if (c["equipment_stars"].get("CT") or 0) >= 3),
            "micro": sum(1 for c in eq if (c["equipment_stars"].get("マイクロスコープ") or 0) >= 3),
            "night": sum(1 for c in cs if _has_night(c)),
        }

def area_context_html(c):
    """区内データ比較ブロック。区の集計が薄い場合は出さない（誤誘導防止）"""
    w = _ward_key(c.get("address", ""))
    st = _WARD_STATS.get(w)
    if not st or st["n"] < 15 or st["eq_n"] < 10:
        return ""
    es = c.get("equipment_stars") or {}
    rows = []
    def stat(label, has, rate, unit="の医院で導入を確認"):
        if has:
            return (f"<li><strong>{label}：この医院は導入を確認。</strong>"
                    f"{w}では{rate:.0f}%{unit}（当サイト解析分）。導入院はまだ少数派です</li>")
        return (f"<li>{label}：公式サイトでは確認できませんでした（未確認）。"
                f"{w}では{rate:.0f}%{unit}</li>")
    if st["eq_n"]:
        rows.append(stat("歯科用CT", (es.get("CT") or 0) >= 3, st["ct"] / st["eq_n"] * 100))
        rows.append(stat("マイクロスコープ", (es.get("マイクロスコープ") or 0) >= 3, st["micro"] / st["eq_n"] * 100))
    night_rate = st["night"] / st["n"] * 100
    if _has_night(c):
        rows.append(f"<li><strong>夜間診療：案内あり。</strong>{w}で夜間対応を案内しているのは{night_rate:.0f}%と貴重な存在です</li>")
    else:
        rows.append(f"<li>夜間診療：案内は確認できませんでした。{w}では{night_rate:.0f}%の医院が夜間対応を案内しています</li>")
    method_ref = ('集計の方法は<a href="../research/index.html">データ研究ページ</a>をご覧ください。'
                  if HAS_RESEARCH else
                  '集計・編集の方針は<a href="../../policy.html#editorial">運営ポリシー</a>をご覧ください。')
    return (f'<p class="rr-lead">{w}には当サイトの分析対象の歯科医院が{st["n"]}院あります。'
            f'この医院を{w}全体のデータの中に置くと、次のことが分かります。</p>'
            f'<ul class="rr-list good">{"".join(rows)}</ul>'
            f'<p class="rr-note">割合は当サイトが公式サイト・口コミから機械的に解析できた範囲の値です'
            f'（{w}の設備解析対象 {st["eq_n"]}院）。「未確認」は「無い」という意味ではありません。'
            f'{method_ref}データは毎月更新しています。</p>')

def evidence_panel_html(c):
    """AI Analysis の「＋根拠」パネル。判断の元になった実データを開示する（2026-07-11新設）。
    患者・院長・オーナーが「AIはなぜそう言ったのか」を検証できるようにするのが目的。"""
    e = esc
    blocks = []

    # 0) 分析文（AI ANALYSIS本文）の主張ごとの根拠 ─ 最重要セクション
    #    要約の一文一文を「根拠あり／AI推定」に分解して示す。矛盾は表示せず修正で消す前提。
    claims = scan_summary_claims(c.get("ai_summary", ""), c)
    if claims:
        rows = ""
        for x in claims:
            v = x["verdict"]
            if v == "grounded":
                badge = '<span class="rr-ev-badge ok">根拠あり</span>'
            elif v == "contradicted":
                badge = '<span class="rr-ev-badge bad">要確認</span>'
            else:
                badge = '<span class="rr-ev-badge guess">AIによる推定</span>'
            ctx = '（注意点として）' if x["negative"] else ''
            rows += (f'<li><span class="rr-ev-term">「{e(x["term"])}」{ctx}</span>{badge}'
                     f'<span class="rr-ev-basis">{e(x["basis"])}</span></li>')
        inner = (f'<p class="rr-ev-summary">{e(c.get("ai_summary", ""))}</p>'
                 f'<ul class="rr-ev-list">{rows}</ul>')
        blocks.append(('この分析文が何にもとづくか', inner))

    # 1) 口コミからの根拠
    tags = c.get("reputation_tags") or []
    phrases = (c.get("phrases") or [])[:3]
    if tags or phrases:
        inner = ""
        if tags:
            inner += '<p class="rr-ev-line"><span class="rr-ev-k">口コミ分析で抽出されたタグ</span>' + \
                     "".join(f'<span class="rr-ev-tag">{e(t)}</span>' for t in tags) + "</p>"
        if phrases:
            inner += '<p class="rr-ev-k">実際の口コミからの引用</p>' + \
                     "".join(f'<blockquote class="rr-ev-quote">「{e(p)}」</blockquote>' for p in phrases)
        meta = []
        if c.get("total_reviews"):
            meta.append(f'口コミ{c["total_reviews"]}件を分析')
        if c.get("sources_analyzed"):
            meta.append(f'解析ソース{c["sources_analyzed"]}種類')
        if c.get("last_analyzed"):
            meta.append(f'分析日 {e(str(c["last_analyzed"]))}')
        if meta:
            inner += f'<p class="rr-ev-meta">{" ・ ".join(meta)}</p>'
        blocks.append(('口コミからの根拠', inner))

    # 2) 公式サイトからの根拠（深掘り解析済みの場合のみ）
    if c.get("deep_fetched"):
        parts = []
        if c.get("focus_treatments"):
            parts.append("注力分野: " + "・".join(map(e, c["focus_treatments"])))
        if c.get("equipment_evidence"):
            parts.append("設備の記載: " + "・".join(map(e, c["equipment_evidence"])))
        if c.get("site_features"):
            parts.append("サイト記載の特徴: " + "・".join(map(e, c["site_features"])))
        if parts:
            blocks.append(('公式サイトからの根拠',
                           "".join(f'<p class="rr-ev-line">{p}</p>' for p in parts)))

    # 3) 診療時間・立地からの根拠（機械的に導出した事実）
    facts = []
    ev_night = evening_hours(c)
    latest = latest_closing_minutes(c)
    if ev_night is True:
        if latest is not None:
            facts.append(f"夜間帯の診療あり（最終 {latest // 60}時{latest % 60:02d}分まで）")
        else:
            facts.append("夜間・救急の診療あり（医院名・区分に基づく）")
    elif ev_night is False:
        facts.append("夜間帯の診療なし（18時までに終了）")
    wk = weekend_hours(c)
    if wk is True:
        facts.append("土日いずれかの診療あり")
    elif wk is False:
        facts.append("土日の診療なし")
    if parking_fact(c):
        facts.append("駐車場あり")
    # 立地の事実（患者目線・2026-07-11）：駅が徒歩圏(1.2km)なら徒歩、超えたらバス停/IC/車の目安
    ns_f = c.get("nearest_station") or {}
    d_f = ns_f.get("straight_distance_m")
    if ns_f.get("name") and d_f is not None and d_f > 1200:
        bus_f = c.get("nearest_bus_stop") or {}
        ic_f = c.get("nearest_ic") or {}
        if bus_f.get("name") and (bus_f.get("distance_m") or 9999) <= 500:
            facts.append(f'バス停「{bus_f["name"]}」から徒歩約{max(1, -(-bus_f["distance_m"]//80))}分（当サイト算出の目安）')
        elif ic_f.get("name") and (ic_f.get("distance_m") or 99999) <= 8000:
            facts.append(f'{ic_f["name"]}から車で約{max(1, -(-ic_f["distance_m"]//500))}分（当サイト算出の目安）')
        else:
            facts.append(f'最寄駅から車で約{max(1, -(-d_f//500))}分（当サイト算出の目安）')
    else:
        walk = station_walk_min(c)
        if walk is not None:
            facts.append(f"最寄駅から徒歩約{walk}分〜（直線距離からの推計）")
    if facts:
        blocks.append(('診療時間・立地からの事実',
                       "".join(f'<p class="rr-ev-line">{e(f)}</p>' for f in facts)))

    # 4) 「向いている方・注意点」それぞれの判定根拠
    rows = ""
    for kind, label in (("fit_for", "向いている"), ("not_fit_for", "注意")):
        for item in (c.get(kind) or []):
            verdict, basis = ground_claim(item, c, negative=(kind == "not_fit_for"))
            if verdict != "grounded":
                continue  # 根拠のないAI推定・矛盾は「判定内訳」に出さない
            rows += (f'<li><span class="rr-ev-kind">{label}</span>「{e(item)}」'
                     f'<span class="rr-ev-badge ok">根拠あり</span>'
                     f'<span class="rr-ev-basis">{e(basis)}</span></li>')
    if rows:
        blocks.append(('「向いている方・注意点」の判定内訳', f'<ul class="rr-ev-list">{rows}</ul>'))

    if not blocks:
        return ""

    body = "".join(f'<div class="rr-ev-block"><p class="rr-ev-h">{title}</p>{inner}</div>'
                   for title, inner in blocks)
    note = ('<p class="rr-ev-note">「根拠あり」は口コミ・公式サイト・診療時間等の公開データに'
            '対応する記述が確認できたもの、「AIによる推定」は直接の記述がなくAIが総合的に'
            '推測したものです。本分析は公開情報に基づく意見・論評であり、医療上の判断や'
            '治療結果を保証するものではありません。</p>')
    return ('<button type="button" class="rr-ev-toggle" aria-expanded="false">＋根拠を見る</button>'
            f'<div class="rr-ev-panel" hidden>{body}{note}</div>')


def build_page(c, slug=""):
    name   = c.get("name", "")
    catch  = c.get("catchphrase", "")
    addr   = c.get("address", "")
    rating = c.get("rating", 0) or 0
    reviews= c.get("total_reviews", 0) or 0
    url    = c.get("url", "")
    maps   = c.get("google_maps_url", "")
    phone  = c.get("phone") or ""
    hours  = c.get("business_hours") or []
    if isinstance(hours, str):   # データ不整合対策：文字列で入っている場合は1件のリストとして扱う（文字単位に分割されるバグを防ぐ）
        hours = [hours] if hours else []
    genre  = c.get("genre", "")
    analyzed = c.get("last_analyzed", "")
    sources  = c.get("sources_analyzed", 0) or 0

    catch_html = f'<p class="rr-catch">{esc(catch)}</p>' if catch else ""

    # 研究レポートの4指標（Confidence / Evidence / Research Sources / Patient Fit）
    # ★評価やランキングではなく、根拠の強さを示す
    m = compute_metrics(c)
    metric_items = [
        ("Confidence", f'{m["confidence"]}%'),
        ("Evidence", m["evidence"]),
        ("Research Sources", str(m["research_sources"])),
    ]
    if m["patient_fit"] is not None:
        metric_items.append(("Patient Fit", f'{m["patient_fit"]}%'))
    metric_html = "".join(
        f'<div class="rr-metric"><span class="rr-metric-v">{esc(v)}</span>'
        f'<span class="rr-metric-k">{esc(k)}</span></div>'
        for k, v in metric_items
    )
    meta_html = f'<div class="rr-hmeta">{metric_html}</div>'

    # 事実情報（口コミ件数・分析日）は控えめな注記として残す
    fact_bits = []
    if rating:
        fact_bits.append(f'Google口コミ {esc(rating)}（{esc(reviews)}件）')
    if analyzed:
        fact_bits.append(f'分析日 {esc(analyzed)}')
    fact_html = f'<p class="rr-fact">{" ・ ".join(fact_bits)}</p>' if fact_bits else ""

    links = ""
    if url:
        links += f'<a class="rr-btn primary" href="{esc(url)}" target="_blank" rel="noopener">公式サイト</a>'
    if maps:
        links += f'<a class="rr-btn" href="{esc(maps)}" target="_blank" rel="noopener">Googleマップ</a>'

    # ── 各セクションの中身を組み立て（空はNone扱いで非表示・自動連番） ──
    # 薄いページ（実データが閾値未満）では「公開情報が限定的…」等の定型空文を
    # 本番URLに出さない（scaled contentの署名になるため。2026-07-13）
    ai = c.get("ai_summary", "")
    if is_thin(c) and not has_substantive_ai(c):
        ai = ""
    sec_summary = (f'<div class="rr-ai"><span class="rr-ai-label">AI Analysis</span>'
                   f'<p>{esc(ai)}</p>{evidence_panel_html(c)}</div>') if ai else ""

    # 主要所見：口コミ特徴＋専門性タグを統合した"Key Findings"
    key = []
    key += list(c.get("reputation_tags") or [])
    key += [t for t in (c.get("specialty_tags") or []) if t not in key]
    sec_key = (f'<ul class="rr-findings">{findings(key)}</ul>{SRC_NOTE}') if key else ""

    ctype_html = f'<div class="rr-chips">{chips(c.get("clinic_type"))}</div>' if c.get("clinic_type") else ""

    pbars = bar_rows(c.get("patient_scores"), PATIENT_AXES, 100)
    sec_patient = (f'<div class="rr-bars">{pbars}</div>'
                   f'<p class="rr-note">口コミ本文の文脈をAIが7軸で定量化（100点満点・{SITE_NAME} 独自指標）。</p>') if pbars else ""

    dbars = bar_rows(c.get("doctor_stars"), DOCTOR_AXES, 5)
    sec_doctor = (f'<div class="rr-bars">{dbars}</div>{SRC_NOTE}') if dbars else ""

    ebars = bar_rows(c.get("equipment_stars"), EQUIP_KEYS, 5)
    sec_equip = (f'<div class="rr-bars">{ebars}</div>{SRC_NOTE}') if ebars else ""

    fbars = bar_rows(c.get("patient_fit"), FIT_KEYS, 5)
    fit_lead = f'<p class="rr-lead">{esc(c["best_patient_profile"])}</p>' if c.get("best_patient_profile") else ""
    sec_fit = (fit_lead + (f'<div class="rr-bars">{fbars}</div>' if fbars else "") + (SRC_NOTE if fbars else "")) if (fbars or fit_lead) else ""

    # 診療理念・注力治療
    care_bits = ""
    if c.get("philosophy"):
        care_bits += f'<p class="rr-quote">「{esc(c["philosophy"])}」</p>'
    if c.get("focus_treatments"):
        care_bits += f'<div class="rr-chips">{chips(c.get("focus_treatments"))}</div>'
    sec_policy = care_bits

    # 院長プロフィール
    doc = ""
    if c.get("doctor_name"):
        doc += f'<p class="rr-docname">院長　{esc(c["doctor_name"])}</p>'
    if c.get("doctor_career"):
        doc += f'<p class="rr-lead">{esc(c["doctor_career"])}</p>'
    if c.get("qualifications"):
        doc += f'<ul class="rr-quals">{li(c.get("qualifications"))}</ul>'
    sec_doc = doc

    # 結論：向いている方／注意が必要な方を1つにまとめ、レポート冒頭で提示する
    # 根拠のある項目だけを「向いている方・注意点」に表示（AIの当て推量＝女性・高齢者等は出さない）
    ref = [x for x in (c.get("referral_to") or c.get("fit_for") or []) if ground_claim(x, c)[0] == "grounded"]
    nref = [x for x in (c.get("not_referral_to") or c.get("not_fit_for") or []) if ground_claim(x, c, negative=True)[0] == "grounded"]
    conclusion_bits = ""
    if ref:
        conclusion_bits += (f'<p class="rr-concl-label good">この医院が向いている方</p>'
                            f'<ul class="rr-list good">{li(ref)}</ul>')
    if c.get("not_recommended_profile") or nref:
        conclusion_bits += '<p class="rr-concl-label bad">受診前に確認したい点（AI分析による参考情報）</p>'
        if c.get("not_recommended_profile"):
            conclusion_bits += f'<p class="rr-lead">{esc(c["not_recommended_profile"])}</p>'
        if nref:
            conclusion_bits += f'<ul class="rr-list bad">{li(nref)}</ul>'
    sec_conclusion = conclusion_bits

    info_rows = ""
    if genre:  info_rows += f'<tr><th>診療</th><td>{esc(genre)}</td></tr>'
    if addr:   info_rows += f'<tr><th>所在地</th><td>{esc(addr)}</td></tr>'
    if phone:  info_rows += f'<tr><th>電話</th><td>{esc(phone)}</td></tr>'
    if hours:  info_rows += f'<tr><th>診療時間</th><td>{esc(" / ".join(hours[:7]))}</td></tr>'
    info_html = f'<table class="rr-info">{info_rows}</table>' if info_rows else ""

    # 特徴ページ（features/index.html）へのタグ相互リンク
    equip_stars = c.get("equipment_stars") or {}
    spec_tags = set(c.get("specialty_tags") or [])
    tag_links = []
    for key, anchor in EQUIP_ANCHOR.items():
        if int(equip_stars.get(key, 0) or 0) > 0:
            tag_links.append((anchor, key))
    for anchor, group, label in SPECIALTY_ANCHOR_GROUPS:
        if spec_tags & group:
            tag_links.append((anchor, label))
    if "女性医師" in spec_tags:
        tag_links.append(("female", "女性医師が在籍する医院"))
    tag_links_html = "".join(
        f'<a class="rr-tag-link" href="../features/index.html#{a}">{esc(l)}</a>'
        for a, l in tag_links
    )
    sec_tags = f'<div class="rr-chips">{tag_links_html}</div>' if tag_links else ""

    # 関連記事（RELATED REPORTS）
    linked = c.get("linked_articles") or []
    rel_items = "".join(
        f'<li><a class="rr-related-link" href="../{esc(a.get("filename") if isinstance(a, dict) else a)}">'
        f'{nowrap_pipe(esc(a.get("title") if isinstance(a, dict) else a))}</a></li>'
        for a in linked[:6]
    )
    sec_related = f'<ul class="rr-related-list">{rel_items}</ul>' if rel_items else ""

    # ── 連番セクション（結論→根拠→詳細の順。中身のあるものだけ番号を振って出力） ──
    ordered = [
        ("結論",                  "Conclusion",         sec_conclusion),
        ("分析サマリー",          "Analysis Summary",  sec_summary),
        ("主要所見",              "Key Findings",      sec_key),
        ("患者体験の分析",        "Patient Experience",sec_patient),
        ("院長評価",              "Doctor Assessment", sec_doctor),
        ("設備の充実度",          "Facilities",        sec_equip),
        ("地域の中で見る",        "Area Context",      area_context_html(c)),
        ("適合する患者像",        "Patient Fit",       sec_fit),
        ("医院タイプ",            "Clinic Type",       ctype_html),
        ("診療理念・注力治療",    "Philosophy & Focus",sec_policy),
        ("院長プロフィール",      "Director",          sec_doc),
        ("該当する特徴",          "Feature Tags",       sec_tags),
        ("基本情報",              "Facility Data",     info_html),
        ("関連する研究レポート",  "Related Reports",   sec_related),
    ]
    body, n = "", 0
    for ja, en, inner in ordered:
        if not inner:
            continue
        n += 1
        body += (f'<section class="rr-sec">'
                 f'<div class="rr-sec-h"><span class="rr-sec-n">{n:02d}</span>'
                 f'<div><span class="rr-sec-en">{esc(en)}</span>'
                 f'<h2>{esc(ja)}</h2></div></div>{inner}</section>')

    m_ward = re.search(CITY + r'[^\d]*?区', addr or "")
    ward_txt = m_ward.group(0) if m_ward else CITY
    ward_paren = f"（{ward_txt}）"
    ward_only = ward_txt.replace(CITY, "")
    area_slug = WARD_SLUGS.get(ward_only)
    # 区別LPが実在するサイトでのみリンクを出す（エリアページ未作成の都市で
    # 404リンクを量産しない。2026-07-13・神戸で実在バグ確認）
    if area_slug and not os.path.exists(os.path.join(ROOT, "articles", "area", f"{area_slug}.html")):
        area_slug = None
    area_link = (f'<a class="rr-cta-btn ghost" href="../area/{area_slug}.html">{ward_only}の医院一覧</a>'
                 if area_slug else "")

    # meta description：文の途中で切らない（語尾切れ対策 2026-07-13）。
    # 90字以内で最後の「。」まで採用し、句点が無ければ「…」を付ける。
    desc_ai = (ai or "").strip()
    if len(desc_ai) > 90:
        cut = desc_ai[:90]
        pos = cut.rfind("。")
        desc_ai = cut[:pos + 1] if pos >= 20 else cut.rstrip("、,") + "…"
    desc = f"{name}（{ward_txt}）の口コミ・評判をAIが分析。" + desc_ai

    # 薄いページはnoindex,follow（インデックス対象から除外・リンクは辿らせる）
    robots_meta = ('<meta name="robots" content="noindex,follow">\n'
                   if is_thin(c) else "")

    return (TEMPLATE.replace("{name}", esc(name)).replace("{addr}", esc(addr))
            .replace("{catch}", catch_html).replace("{meta}", meta_html)
            .replace("{fact}", fact_html)
            .replace("{links}", links).replace("{body}", body)
            .replace("{jsonld}", build_jsonld(c, slug))
            .replace("{robots}", robots_meta)
            .replace("{ogurl}", page_url_of(slug))
            .replace("{desc}", esc(desc))
            .replace("{ward_paren}", esc(ward_paren))
            .replace("{area_link}", area_link)
            .replace("{research_foot}",
                     '・<a href="../research/index.html" style="color:inherit;text-decoration:underline;">データ研究ページ</a>'
                     if HAS_RESEARCH else "")
            .replace("{SITE_NAME}", SITE_NAME).replace("{EN_INSTITUTE}", EN_INSTITUTE).replace("{EN_UPPER}", EN_UPPER)
            .replace("{CITY_SHORT}", CITY_SHORT).replace("{N_PUBLISHED:,}", f"{N_PUBLISHED:,}"))

TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name}の口コミ・評判・AI分析{ward_paren}｜{SITE_NAME}</title>
<meta name="description" content="{desc}">
{robots}<link rel="canonical" href="{ogurl}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="{SITE_NAME}">
<meta property="og:title" content="{name}の口コミ・評判・AI分析{ward_paren}｜{SITE_NAME}">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{ogurl}">
<meta name="twitter:card" content="summary">
{jsonld}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Zen+Kaku+Gothic+New:wght@400;500;700;900&family=Shippori+Mincho:wght@600;700&family=Roboto+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="../../assets/odr-ds.css">
<style>
:root{--pine:#1f4b3f;--terra:#d98b5f;--paper:#f6f8f7;--ink:#1c2b25;--ink2:#5c6d66;--line:#e4ebe7;--mono:'Roboto Mono',monospace;}
*{box-sizing:border-box;}
body{margin:0;font-family:'Noto Sans JP','Hiragino Kaku Gothic ProN',sans-serif;color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased;line-height:1.8;}
a{color:inherit;}
.rr-nav{background:var(--pine);color:#fff;padding:0 clamp(20px,4vw,40px);height:64px;display:flex;align-items:center;justify-content:space-between;}
.rr-nav .logo{font-weight:700;text-decoration:none;font-family:'Zen Kaku Gothic New','Hiragino Kaku Gothic ProN',sans-serif;font-size:.98rem;letter-spacing:.02em;}
.rr-nav .logo small{display:block;font-size:.58rem;letter-spacing:.16em;color:#9cbbae;font-weight:400;}
.rr-nav .back{font-size:.82rem;color:#cfe0d8;text-decoration:none;}
.rr-navlinks{display:flex;gap:22px;align-items:center;}
.rr-navlinks a{font-size:.84rem;color:#cfe0d8;text-decoration:none;white-space:nowrap;transition:color .15s;}
.rr-navlinks a:hover{color:#fff;}
@media(max-width:820px){.rr-navlinks{display:none;}}
/* ── レポートヘッダー ── */
.rr-hero{background:var(--pine);color:#fff;padding:clamp(30px,5vw,56px) clamp(20px,4vw,40px) clamp(40px,5vw,60px);}
.rr-hero-in{max-width:860px;margin:0 auto;}
.rr-tag{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-size:.7rem;letter-spacing:.22em;color:var(--terra);border:1px solid rgba(217,139,95,.5);border-radius:999px;padding:5px 14px;margin-bottom:20px;}
.rr-tag::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--terra);}
.rr-name{font-family:'Shippori Mincho',serif;font-size:clamp(1.6rem,3.4vw,2.3rem);font-weight:700;margin:0 0 10px;line-height:1.35;}
.rr-catch{color:#d6e6df;font-size:1.02rem;margin:0 0 14px;}
.rr-address{color:#a9c6bb;font-size:.86rem;margin:0 0 18px;}
.rr-hmeta{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:1px;background:rgba(255,255,255,.14);border-radius:12px;overflow:hidden;margin-bottom:14px;}
.rr-metric{background:rgba(255,255,255,.06);padding:14px 10px;text-align:center;}
.rr-metric-v{display:block;font-family:var(--mono);font-weight:700;font-size:1.05rem;color:#fff;}
.rr-metric-k{display:block;font-family:var(--mono);font-size:.6rem;letter-spacing:.08em;text-transform:uppercase;color:#a9c6bb;margin-top:4px;}
.rr-fact{color:#8fae9f;font-size:.74rem;margin:0 0 22px;}
.rr-links{display:flex;gap:12px;flex-wrap:wrap;}
.rr-btn{display:inline-block;padding:11px 24px;border-radius:8px;font-size:.86rem;font-weight:500;text-decoration:none;border:1px solid rgba(255,255,255,.4);color:#fff;}
.rr-btn.primary{background:var(--terra);border-color:var(--terra);font-weight:700;}
.rr-btn:hover{opacity:.92;}
/* ── 本文 ── */
main{max-width:860px;margin:0 auto;padding:clamp(36px,5vw,64px) clamp(20px,4vw,40px) 80px;}
.rr-sec{margin:0 0 clamp(44px,6vw,68px);}
.rr-sec-h{display:flex;align-items:flex-start;gap:16px;margin:0 0 22px;}
.rr-sec-n{font-family:var(--mono);font-size:.9rem;color:var(--terra);font-weight:500;padding-top:3px;min-width:26px;}
.rr-sec-en{display:block;font-family:var(--mono);font-size:.64rem;letter-spacing:.2em;color:var(--ink2);text-transform:uppercase;}
.rr-sec-h h2{font-size:1.24rem;font-weight:700;color:var(--pine);margin:2px 0 0;}
/* AI要約カード（Apple Intelligence 風） */
.rr-ai{position:relative;background:#fff;border-radius:14px;padding:24px 26px;border:1px solid var(--line);box-shadow:0 4px 24px rgba(20,50,40,.05);overflow:hidden;}
.rr-ai::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:linear-gradient(180deg,var(--terra),var(--pine));}
.rr-ai-label{display:inline-block;font-family:var(--mono);font-size:.62rem;letter-spacing:.2em;color:var(--terra);margin-bottom:8px;}
.rr-ai p{margin:0;font-size:1.02rem;line-height:1.9;}
/* ＋根拠パネル（2026-07-11） */
.rr-ev-toggle{margin-top:14px;background:none;border:1px solid var(--line);border-radius:999px;
  padding:7px 16px;font-size:.8rem;color:var(--pine);cursor:pointer;font-family:inherit;}
.rr-ev-toggle:hover{border-color:var(--pine);background:rgba(31,75,63,.04);}
.rr-ev-toggle[aria-expanded="true"]{background:var(--pine);color:#fff;border-color:var(--pine);}
.rr-ev-panel{margin-top:16px;border-top:1px dashed var(--line);padding-top:16px;}
.rr-ev-block{margin-bottom:16px;}
.rr-ev-h{font-family:var(--mono);font-size:.68rem;letter-spacing:.14em;color:var(--terra);margin:0 0 8px;}
.rr-ev-line{margin:0 0 6px;font-size:.85rem;line-height:1.8;color:#3d4643;}
.rr-ev-k{display:block;font-size:.78rem;color:#6b7570;margin:0 0 6px;}
.rr-ev-tag{display:inline-block;background:rgba(31,75,63,.07);border-radius:999px;
  padding:3px 12px;font-size:.78rem;color:var(--pine);margin:0 6px 6px 0;}
.rr-ev-quote{margin:0 0 8px;padding:8px 14px;border-left:3px solid var(--terra);
  background:#faf8f5;font-size:.85rem;line-height:1.8;color:#3d4643;}
.rr-ev-meta{margin:4px 0 0;font-size:.72rem;color:#8b928e;}
.rr-ev-list{list-style:none;margin:0;padding:0;}
.rr-ev-list li{padding:8px 0;border-bottom:1px solid #f0f0ee;font-size:.85rem;line-height:1.7;}
.rr-ev-list li:last-child{border-bottom:none;}
.rr-ev-kind{display:inline-block;font-size:.68rem;color:#8b928e;margin-right:6px;
  border:1px solid var(--line);border-radius:4px;padding:1px 6px;}
.rr-ev-badge{display:inline-block;font-size:.68rem;border-radius:4px;padding:2px 8px;margin-left:8px;}
.rr-ev-badge.ok{background:rgba(31,75,63,.1);color:var(--pine);}
.rr-ev-badge.guess{background:#f3ede2;color:#8a6d3b;}
.rr-ev-badge.bad{background:#fbe9e7;color:#b23c17;}
.rr-ev-basis{display:block;font-size:.76rem;color:#6b7570;margin-top:3px;}
.rr-ev-summary{margin:0 0 12px;padding:12px 14px;background:#f7f9f8;border-radius:10px;
  font-size:.9rem;line-height:1.85;color:#2c3532;}
.rr-ev-term{font-weight:600;color:#2c3532;}
.rr-ev-note{margin:8px 0 0;font-size:.72rem;line-height:1.8;color:#8b928e;}
/* Key Findings */
.rr-findings{margin:0;padding:0;list-style:none;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;}
.rr-findings li{position:relative;padding:12px 16px 12px 40px;background:#fff;border:1px solid var(--line);border-radius:10px;font-size:.92rem;font-weight:500;}
.rr-findings li::before{content:"✓";position:absolute;left:15px;top:11px;color:#2e8c6a;font-weight:700;}
/* バー */
.rr-bars{display:flex;flex-direction:column;gap:14px;background:#fff;border:1px solid var(--line);border-radius:14px;padding:24px 26px;}
.rr-bar{display:grid;grid-template-columns:120px 1fr 48px;align-items:center;gap:14px;font-size:.88rem;}
.rr-bar-k{color:var(--ink2);}
.rr-bar-track{height:9px;background:#eef3f1;border-radius:6px;overflow:hidden;}
.rr-bar-fill{display:block;height:100%;background:linear-gradient(90deg,var(--pine),#2e6a58);border-radius:6px;transition:width .6s ease;}
.rr-bar-v{font-weight:700;color:var(--pine);text-align:right;font-family:var(--mono);font-size:.82rem;}
/* チップ */
.rr-chips{display:flex;flex-wrap:wrap;gap:9px;}
.rr-chip{background:#eaf1ee;color:var(--pine);border:1px solid var(--line);border-radius:999px;padding:6px 16px;font-size:.83rem;font-weight:500;}
.rr-tag-link{background:#eaf1ee;color:var(--pine);border:1px solid var(--line);border-radius:999px;padding:6px 16px;font-size:.83rem;font-weight:500;text-decoration:none;transition:background .15s;}
.rr-tag-link:hover{background:var(--terra);color:#fff;border-color:var(--terra);}
.rr-related-list{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:2px;}
.rr-related-list li{border-top:1px solid var(--line);}
.rr-related-list li:first-child{border-top:none;}
.rr-related-link{display:flex;align-items:center;gap:8px;padding:12px 2px;font-size:.92rem;font-weight:600;color:var(--pine);text-decoration:none;}
.rr-related-link:hover{text-decoration:underline;}
.rr-related-link::before{content:"📄";flex-shrink:0;}
/* リード・引用・リスト */
.rr-lead{font-size:.98rem;color:var(--ink);margin:0 0 14px;}
.rr-quote{font-size:1.08rem;color:var(--pine);font-weight:500;margin:0 0 16px;padding-left:16px;border-left:3px solid var(--terra);line-height:1.8;}
.rr-docname{font-size:1.05rem;font-weight:700;color:var(--pine);margin:0 0 8px;}
.rr-quals{margin:14px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:7px;}
.rr-quals li{position:relative;padding-left:22px;font-size:.9rem;color:var(--ink2);}
.rr-quals li::before{content:"◆";position:absolute;left:0;color:var(--terra);font-size:.7rem;top:4px;}
.rr-list{margin:0;padding:0;list-style:none;display:flex;flex-direction:column;gap:9px;}
.rr-list li{position:relative;padding-left:26px;font-size:.95rem;}
.rr-list.good li::before{content:"✓";position:absolute;left:0;color:#2e8c6a;font-weight:700;}
.rr-list.bad li::before{content:"！";position:absolute;left:0;color:var(--terra);font-weight:700;}
.rr-concl-label{font-size:.72rem;font-weight:700;letter-spacing:.04em;margin:0 0 10px;}
.rr-concl-label.good{color:#2e8c6a;}
.rr-concl-label.bad{color:var(--terra);}
.rr-concl-label:not(:first-child){margin-top:20px;}
.rr-note{color:var(--ink2);font-size:.76rem;margin:14px 0 0;line-height:1.75;}
/* 基本情報テーブル */
.rr-info{width:100%;border-collapse:collapse;font-size:.92rem;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.rr-info th{text-align:left;color:var(--ink2);font-weight:500;width:110px;padding:14px 20px;vertical-align:top;border-bottom:1px solid var(--line);background:#fbfcfb;}
.rr-info td{padding:14px 20px;border-bottom:1px solid var(--line);}
.rr-info tr:last-child th,.rr-info tr:last-child td{border-bottom:none;}
/* CTA */
.rr-cta{background:var(--pine);border-radius:18px;padding:40px 30px;text-align:center;margin:8px 0 16px;}
.rr-cta-t{color:#fff;font-size:1.3rem;font-weight:700;margin:0 0 8px;}
.rr-cta-s{color:#cfe0d8;font-size:.92rem;margin:0 0 22px;}
.rr-cta-btns{display:flex;gap:12px;justify-content:center;flex-wrap:wrap;}
.rr-cta-btn{display:inline-block;background:var(--terra);color:#fff;font-weight:700;padding:14px 32px;border-radius:10px;text-decoration:none;font-size:.95rem;}
.rr-cta-btn.ghost{background:transparent;border:1px solid rgba(255,255,255,.5);}
.rr-cta-btn:hover{opacity:.93;}
/* フッター */
.rr-foot{border-top:1px solid var(--line);padding:32px clamp(20px,4vw,40px);color:var(--ink2);font-size:.78rem;line-height:1.9;}
.rr-foot .in{max-width:860px;margin:0 auto;}
@media(max-width:560px){.rr-bar{grid-template-columns:92px 1fr 42px;gap:10px;}}
/* ── Research Flow（パンくず） ── */
.rf-crumb{max-width:860px;margin:14px auto 0;padding:0 clamp(20px,4vw,40px);display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-family:var(--mono);font-size:.72rem;letter-spacing:.02em;}
.rf-crumb a{color:var(--ink2);text-decoration:none;}
.rf-crumb a:hover{color:var(--pine);text-decoration:underline;}
.rf-crumb .rf-sep{color:var(--line);}
.rf-crumb .rf-current{color:var(--terra);font-weight:700;}
</style>
<script src="../../assets/site-config.js"></script>
<script src="../../assets/odr-track.js"></script>
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
  <a href="../features/index.html">Clinic Analysis</a>
  <span class="rf-sep">/</span>
  <span class="rf-current">{name}</span>
</nav>
<section class="rr-hero">
  <div class="rr-hero-in">
    <span class="rr-tag">AI RESEARCH REPORT</span>
    <h1 class="rr-name">{name}</h1>
    {catch}
    <p class="rr-address">{addr}</p>
    {meta}
    {fact}
    <div class="rr-links">{links}</div>
  </div>
</section>
<main>
{body}
  <section class="rr-cta">
    <p class="rr-cta-t">あなたに合う歯科医院は？</p>
    <p class="rr-cta-s">症状・エリア・ご希望から、AIが{CITY_SHORT}市内 約{N_PUBLISHED:,}院を無料でマッチングします。</p>
    <div class="rr-cta-btns">
      <a class="rr-cta-btn" href="../shindan/index.html">AI診断を受ける（無料）</a>
      <a class="rr-cta-btn ghost" href="../features/index.html">特徴から探す</a>
      {area_link}
    </div>
  </section>
</main>
<footer class="rr-foot">
  <div class="in">当レポートのAI分析（サマリー・各スコア等）は、Googleマップの口コミや各医院公式サイト等の公開情報をもとに{SITE_NAME}が独自に生成した参考情報です。根拠となる情報がない項目は表示していません。診断・治療方針の決定を目的としたものではなく、受診の判断は必ず歯科医師にご相談ください。掲載内容の訂正は<a href="../../teisei.html" style="color:inherit;text-decoration:underline;">こちら</a>、免責事項の詳細は<a href="../../policy.html" style="color:inherit;text-decoration:underline;">運営ポリシー</a>をご覧ください。運営者と分析手法（データ源・算出方法・限界）は<a href="../../about.html" style="color:inherit;text-decoration:underline;">運営者情報</a>{research_foot}で開示しています。<br>© {SITE_NAME} {EN_UPPER}</div>
</footer>
<script>
document.addEventListener("click",function(ev){
  var b=ev.target.closest(".rr-ev-toggle"); if(!b)return;
  var p=b.nextElementSibling; var open=b.getAttribute("aria-expanded")==="true";
  b.setAttribute("aria-expanded",open?"false":"true");
  b.textContent=open?"＋根拠を見る":"－根拠を閉じる";
  if(p)p.hidden=open;
});
</script>
</body>
</html>'''

def compute_shared_phones(clinics):
    """掲載院の中で2院以上が同じ電話番号を使っているものを洗い出す
    （フランチャイズ共通窓口・コールトラッキング番号）。schemaのtelephoneには入れない。"""
    from collections import Counter
    cnt = Counter()
    for c in clinics:
        if not c.get("name") or c.get("q_excluded"):
            continue
        p = (c.get("phone") or "").strip()
        if p:
            cnt[p] += 1
    return {p for p, n in cnt.items() if n >= 2}

def main():
    db = json.load(open(DB, encoding="utf-8"))
    clinics = list(db.values()) if isinstance(db, dict) else db
    compute_ward_stats(clinics)  # Area Context用の区別集計
    SHARED_PHONES.clear()
    SHARED_PHONES.update(compute_shared_phones(clinics))  # NAP：共有番号はschemaに入れない
    os.makedirs(OUT, exist_ok=True)
    n = 0
    n_thin = 0
    valid = set()
    for c in clinics:
        name = c.get("name")
        if not name:
            continue
        if c.get("q_excluded"):   # 対象エリア外・サロン・重複は生成しない（品質フラグ）
            continue
        slug = SLUG_MAP.get(c.get("place_id"), slugify(name))  # 衝突対策済みの一意なslugを使用
        valid.add(slug)
        if is_thin(c):
            n_thin += 1
        open(os.path.join(OUT, slug + ".html"), "w", encoding="utf-8").write(build_page(c, slug))
        n += 1
    # 現DBに対応しないオーファンページを削除
    import glob
    removed = 0
    for f in glob.glob(os.path.join(OUT, "*.html")):
        if os.path.basename(f)[:-5] not in valid:
            os.remove(f); removed += 1
    print(f"✅ 医院AI Research Report 生成: {n}院 / オーファン削除: {removed}")
    print(f"   うち薄いページ（noindex,follow付与・sitemap除外対象）: {n_thin}院 / 共有電話番号（schema除外）: {len(SHARED_PHONES)}種")

if __name__ == "__main__":
    main()
