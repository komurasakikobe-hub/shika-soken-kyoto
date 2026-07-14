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
from thin_page_policy import is_thin, has_substantive_ai, is_placeholder_text


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
# 30秒診断のエリア事前選択に使う「この都市の有効な区」の集合。
# site_config.jsonにwardsがある都市（神戸等）はそれを使い、無い都市（京都・区なし都市）は
# WARD_SLUGSのキー（＝京都11区）にフォールバックする。区の無い市（尼崎等）は住所から区名が
# 取れず空文字になり、この集合に一致しない＝診断リンクは都市全体版になる（都市分岐ハードコードなし）。
VALID_WARDS = set(SITE_CFG.get("wards") or WARD_SLUGS.keys())
CITY_SHORT = SITE_CFG.get("city_short", SITE_CFG.get("city", ""))
N_PUBLISHED = SITE_CFG.get("stats", {}).get("clinics_published", 0)
DOMAIN = SITE_CFG.get("domain", "shikasoken.com")
CITY = SITE_CFG.get("city", "")                # 例: 京都市 / 神戸市 / 北播磨エリア
SITE_NAME = SITE_CFG.get("site_name", "")      # 例: 京都歯科総研
EN_UPPER = SITE_CFG.get("site_name_en", "")    # 例: KYOTO DENTAL RESEARCH
# 例: Kyoto Dental Research Institute（site_name_enから機械導出。ハイフン語は各パートを大文字化）
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
    return f"https://{DOMAIN}/articles/clinics/{quote(slug)}"

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
    # 研究記事への文脈リンク（1本だけ）。設備比較の行があれば設備の研究記事、
    # なければ診療時間の研究記事へ。リンク先が実在するサイトでのみ出す
    # （研究記事は現状京都のみ＝他都市では自動的に出ない。都市分岐はしない）
    research_link = ""
    r_slug = "equipment-gap" if st["eq_n"] else "worktime-access"
    if os.path.exists(os.path.join(ROOT, "articles", "research", f"{r_slug}.html")):
        r_label = "設備の傾向" if st["eq_n"] else "診療時間の傾向"
        research_link = (f'<p class="rr-lead">→ {CITY}全体での{r_label}は'
                         f'<a href="../research/{r_slug}.html">こちらの研究記事</a>で確認できます。</p>')
    return (f'<p class="rr-lead">{w}には当サイトの分析対象の歯科医院が{st["n"]}院あります。'
            f'この医院を{w}全体のデータの中に置くと、次のことが分かります。</p>'
            f'<ul class="rr-list good">{"".join(rows)}</ul>'
            f'{research_link}'
            f'<p class="rr-note">割合は当サイトが公式サイト・口コミから機械的に解析できた範囲の値です'
            f'（{w}の設備解析対象 {st["eq_n"]}院）。「未確認」は「無い」という意味ではありません。'
            f'{method_ref}データは毎月更新しています。</p>')


# ── 表示用の軟化（2026-07-14 患者向け再編集） ──
# AI要約・口コミタグに残る強い断定（専門/信頼できる/最適）を、患者向けの表示だけ弱める。
# grounding判定（scan_summary_claims等）には元文を渡す（表示層のみの変換）。
# ※根本対処はDB側のai_summary再生成だが、機械置換で法務リスクの高い定型パターンを先に消す。
_SOFTEN_PAIRS = [
    ("に特化した専門性の高い", "を重視した"),
    ("専門性の高い", "に力を入れる"),
    ("に最適です", "に合う可能性があります"),
    ("最適です", "合う可能性があります"),
    ("最適な", "有力な候補となる"),
    ("信頼できる医院", "口コミ評価の高い医院"),
    ("信頼できる", "口コミ評価の高い"),
    ("信頼度が高く", "口コミ上の評価が高く"),
    ("専門クリニック", "に注力するクリニック"),
    ("専門医院", "に注力する医院"),
    ("専門の", "に力を入れる"),
]
def soften_display_text(t):
    for a, b in _SOFTEN_PAIRS:
        t = t.replace(a, b)
    return t
# 資格の裏取りなく「専門」等を名乗るタグは表示しない（例：歯周病専門・信頼できる医院）
_NG_TAG_RE = _re.compile(r"専門|信頼|最適|[Nn]o\.?1|一番")

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
        inner = (f'<p class="rr-ev-summary">{e(soften_display_text(c.get("ai_summary", "")))}</p>'
                 f'<ul class="rr-ev-list">{rows}</ul>')
        blocks.append(('この分析文が何にもとづくか', inner))

    # 1) 口コミからの根拠
    tags = [t for t in (c.get("reputation_tags") or []) if not _NG_TAG_RE.search(str(t))]
    # 薄いページでは「公開情報が限定的」等のプレースホルダタグを出さない（Key Findingsと同方針・2026-07-13）
    if is_thin(c):
        tags = [t for t in tags if not is_placeholder_text(t)]
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
    # 2026-07-14 患者向け再編集：トグルは外側（「この分析は何にもとづくか」の折りたたみ）が
    # 担うため、ここでは中身（ブロック＋注記）だけを返す
    return body + note


def next_steps_html(c, ward_only, area_slug, tag_links):
    """回遊導線ブロック「次の一歩」（2026-07-14 指示書③）。
    医院ページを行き止まりにしないため、その医院のデータから
    地域・条件・診断・最終行動への導線を動的生成する。
    リンク先が実在するときだけ出す（404リンクを作らない）。
    新規リンクは正規URL（.htmlなし・308統一後の形）で張る。
    クリックはdata-odr-ev属性経由でGA4イベントを送る（末尾の委譲スクリプト参照）。"""
    e = esc
    items = []  # (event, filter_value, href, label, why)

    # 1) 同じ区・市町の医院一覧（区別LPが実在するサイトのみ）
    if area_slug:
        items.append(("clinic_to_area", ward_only, f"../area/{area_slug}",
                      f"{ward_only}の歯科医院一覧を見る",
                      f"同じ{ward_only}の医院を、同じ分析基準で見比べられます。"))

    # 2) 同じ特徴・設備を持つ医院（特徴ページの該当アンカーへ・最大2件）
    for anchor, label in tag_links[:2]:
        nice = label if label.endswith("医院") else f"{label}のある医院"
        items.append(("clinic_to_condition", label, f"../features/#{anchor}",
                      f"{nice}を一覧で見る",
                      f"この医院と同じ「{label}」という特徴で、他の医院と比べられます。"))

    # 3) 診療条件での比較（夜間・土日・駐車場。実データで確認できた条件のみ・最大2件）
    conds = []
    if evening_hours(c) is True:
        conds.append(("夜間診療", "仕事帰りでも通いやすい、夜間対応の医院だけで比べられます。"))
    if weekend_hours(c) is True:
        conds.append(("土日診療", "平日の受診が難しい方向けに、土日に診療する医院だけで比べられます。"))
    if parking_fact(c):
        conds.append(("駐車場あり", "お車で通いたい方向けに、駐車場のある医院だけで比べられます。"))
    for cond, why in conds[:2]:
        items.append(("clinic_to_condition", cond, f"../shindan/?cond={quote(cond)}",
                      f"「{cond}」の医院をランキングで比べる", why))

    # 4) 30秒のAI診断（この医院のエリアを事前選択した状態で開く）
    if ward_only and ward_only in VALID_WARDS:
        items.append(("clinic_to_shindan", ward_only, f"../shindan/?ward={quote(ward_only)}",
                      "30秒のAI診断で自分に合う医院を探す",
                      f"{ward_only}を選択済みの状態から、症状やご希望の条件で絞り込めます。"))
    else:
        items.append(("clinic_to_shindan", "", "../shindan/",
                      "30秒のAI診断で自分に合う医院を探す",
                      "症状・エリア・ご希望の条件から、あなたに合う医院を絞り込めます。"))

    rows = "".join(
        f'<li><a href="{e(href)}" data-odr-ev="{e(ev)}" data-odr-v="{e(v)}">'
        f'<span class="t">{e(label)}</span><span class="why">{e(why)}</span></a></li>'
        for ev, v, href, label, why in items
    )

    # 5) 最終行動（公式サイト・地図・電話。データがあるものだけ）
    final = ""
    if c.get("url"):
        final += (f'<a class="rr-btn-line" href="{e(c["url"])}" target="_blank" rel="noopener" '
                  f'data-odr-ev="clinic_to_official" data-odr-v="公式サイト">公式サイトで診療内容を確認</a>')
    if c.get("google_maps_url"):
        final += (f'<a class="rr-btn-line" href="{e(c["google_maps_url"])}" target="_blank" rel="noopener" '
                  f'data-odr-ev="clinic_to_map" data-odr-v="地図">Googleマップで場所・口コミを見る</a>')
    phone = (c.get("phone") or "").strip()
    if phone:
        final += (f'<a class="rr-btn-line" href="tel:{e(phone.replace("-",""))}" '
                  f'data-odr-ev="clinic_to_tel" data-odr-v="電話">電話で問い合わせる（{e(phone)}）</a>')
    final_html = f'<div class="rr-next-final">{final}</div>' if final else ""

    if not rows and not final_html:
        return ""
    return (f'<ul class="rr-next">{rows}</ul>{final_html}'
            f'<p class="rr-note">リンク先の一覧・比較は、当サイトが公開情報から機械的に解析できた範囲にもとづく参考情報です。</p>')


# ── 患者向け再編集レイアウト（2026-07-14 全面改修）ヘルパー ──
# 「研究レポートを読むページ」から「患者が判断できる比較ページ」への再編集。
# 方針（試作 articles/clinics/_prototype_リベ大… でユーザー承認済み 2026-07-14）：
#  ・断定（専門/信頼できる/最適）を使わない。「案内しています」「確認できます」「比較候補」の語調
#  ・患者スコアは数値バーでなく「言及傾向（多い/やや多い/評価が分かれる）」で表示。
#    数値（言及指数）は「この分析は何にもとづくか」の折りたたみで開示（透明性は維持）
#  ・診療時間は表形式＋出典（Googleビジネスプロフィール）＋最終確認日＋「要確認」を必ず添える
#  ・英字指標（Confidence/Patient Fit等）はヒーローから撤去し「情報充実度」として分析根拠内で開示
#    （「92%＝分析が正しい確率」という誤読を避ける）
#  ・折りたたみは見出し＋要約を常時可視・中身はDOMに残す（SEO・被引用を壊さない）
#  ・データが薄い医院は各セクションが自動非表示になり簡素なページに落ちる（＝3段テンプレの自動分岐。
#    薄いページのnoindex/定型空文の扱いはthin_page_policy.pyの既存ルールのまま）

# 口コミ7軸の患者向け表記（「技術力85」等が医療技術そのものの採点と誤読されるのを避ける）
AXIS_PATIENT_LABEL = {
    "技術力": "治療内容への肯定的な言及",
    "説明力": "説明の丁寧さ",
    "清潔感": "清潔感",
    "優しさ": "スタッフ対応の良さ",
    "子ども対応": "子どもへの対応",
    "痛みへの配慮": "痛みへの配慮",
    "待ち時間": "待ち時間",
}
AXIS_SHORT = {
    "技術力": "治療内容", "説明力": "説明の丁寧さ", "清潔感": "清潔感",
    "優しさ": "スタッフ対応", "子ども対応": "子どもへの対応",
    "痛みへの配慮": "痛みへの配慮", "待ち時間": "待ち時間",
}
AXIS_QUOTE = {
    "技術力": "治療内容への評価が高い", "説明力": "説明が丁寧", "清潔感": "清潔",
    "優しさ": "対応がやさしい", "子ども対応": "子どもへの対応が良い",
    "痛みへの配慮": "痛みに配慮してくれる", "待ち時間": "待ち時間が短い",
}

def trend_word(v):
    """言及指数→患者向けの傾向語。区分の基準は分析根拠の折りたたみで開示する。"""
    if v >= 80:
        return ("多い", "")
    if v >= 76:
        return ("やや多い", "")
    return ("評価が分かれる", " mixed")

def hours_rows(hours):
    """Google由来の日本語診療時間を（曜日ラベル, 時間帯タプル）の行リストに変換。
    連続する同一時間帯の曜日は「月〜金」のようにまとめる。1行でも解析不能なら
    None（表を出さず従来の文字列表示にフォールバック＝誤った表を出さない）。"""
    day_order = []
    for line in hours[:7]:
        line = str(line)
        d = line[:1]
        if d not in _DAY_EN:
            return None
        if "定休" in line or "休診" in line:
            day_order.append((d, ()))
            continue
        spans = tuple(
            f"{int(h1)}:{int(m1):02d}〜{int(h2)}:{int(m2):02d}"
            for h1, m1, h2, m2 in _HOURS_RE.findall(line)
        )
        if not spans:
            return None
        day_order.append((d, spans))
    if not day_order:
        return None
    rows = []
    for d, spans in day_order:
        if rows and rows[-1][1] == spans:
            rows[-1][0].append(d)
        else:
            rows.append(([d], spans))
    return [(days[0] if len(days) == 1 else f"{days[0]}〜{days[-1]}", spans)
            for days, spans in rows]

def hours_table_html(hours):
    """診療時間の表。全曜日が2枠（午前/午後）なら3列、そうでなければ2列で出す。"""
    rows = hours_rows(hours) if hours else None
    if not rows or all(not s for _, s in rows):
        return ""
    two = all(len(s) in (0, 2) for _, s in rows) and any(len(s) == 2 for _, s in rows)
    if two:
        head = "<tr><th>曜日</th><th>午前</th><th>午後</th></tr>"
        body = ""
        for label, spans in rows:
            if not spans:
                body += f'<tr><th>{esc(label)}</th><td colspan="2">休診</td></tr>'
            else:
                body += f'<tr><th>{esc(label)}</th><td>{esc(spans[0])}</td><td>{esc(spans[1])}</td></tr>'
    else:
        head = "<tr><th>曜日</th><th>診療時間</th></tr>"
        body = "".join(
            f'<tr><th>{esc(label)}</th><td>{"休診" if not spans else esc("、".join(spans))}</td></tr>'
            for label, spans in rows
        )
    return f'<table class="rr-hours"><thead>{head}</thead><tbody>{body}</tbody></table>'

def hours_note_html(c, analyzed):
    """診療時間の注記：夜間有無の事実＋出典＋最終確認日＋要確認（矛盾・誤認対策の要）。"""
    ev = evening_hours(c)
    bits = []
    if ev is False:
        bits.append("<strong>18時以降の診療は確認できませんでした。</strong>")
    elif ev is True:
        latest = latest_closing_minutes(c)
        if latest:
            bits.append(f"<strong>{latest // 60}時{latest % 60:02d}分まで（夜間帯）の診療の表示があります。</strong>")
    src = "出典：Googleビジネスプロフィール掲載の診療時間"
    if analyzed:
        src += f"（最終確認日：{esc(str(analyzed))}）"
    bits.append(src + "。")
    bits.append("診療時間は変更される場合があります。<strong>受診前に必ず公式サイト・電話でご確認ください。</strong>")
    return '<p class="rr-hours-note">' + "<br>".join(bits) + "</p>"

def fold_html(title, sub, body):
    """折りたたみ。見出し＋要約は常時可視・中身はDOMに残す（SEO・被引用を壊さない）。"""
    if not body:
        return ""
    return ('<div class="rr-fold"><button type="button" class="rr-fold-btn" aria-expanded="false" data-fold>'
            f'<span>{title}<span class="sub">{sub}</span></span><span class="mk">＋</span></button>'
            f'<div class="rr-fold-body" hidden>{body}</div></div>')


def build_page(c, slug=""):
    name   = c.get("name", "")
    addr   = c.get("address", "")
    rating = c.get("rating", 0) or 0
    reviews= c.get("total_reviews", 0) or 0
    url    = c.get("url", "")
    maps   = c.get("google_maps_url", "")
    phone  = c.get("phone") or ""
    hours  = c.get("business_hours") or []
    if isinstance(hours, str):   # データ不整合対策：文字列は1件のリストとして扱う
        hours = [hours] if hours else []
    genre  = c.get("genre", "")
    analyzed = c.get("last_analyzed", "")

    # 区の判定（ヒーロー要約・回遊導線・descで共用）
    m_ward = re.search(CITY + r'[^\d]*?区', addr or "")
    ward_txt = m_ward.group(0) if m_ward else CITY
    ward_paren = f"（{ward_txt}）"
    ward_only = ward_txt.replace(CITY, "")
    area_slug = WARD_SLUGS.get(ward_only)
    # 区別LPが実在するサイトでのみリンクを出す（404リンクを量産しない）
    if area_slug and not os.path.exists(os.path.join(ROOT, "articles", "area", f"{area_slug}.html")):
        area_slug = None

    deep = bool(c.get("deep_fetched"))
    focus_list = [t for t in (c.get("focus_treatments") or []) if t] if deep else []
    focus = focus_list[0] if focus_list else ""
    ps = c.get("patient_scores") or {}
    strong_axes = [k for k in PATIENT_AXES if (ps.get(k) or 0) >= 80]
    weak_axes   = [k for k in PATIENT_AXES if 0 < (ps.get(k) or 0) <= 75]
    equip_stars = c.get("equipment_stars") or {}
    ev_night = evening_hours(c)
    sun = any(str(l)[:1] == "日" and "休" not in str(l) for l in hours)
    sat = any(str(l)[:1] == "土" and "休" not in str(l) for l in hours)

    # ── ヒーロー：患者向け要約（断定しない・実データからの機械導出のみ） ──
    if focus:
        hero_summary = f"{focus}を重視して歯科を探している方の、比較候補になり得る医院です。"
    elif genre and genre != "一般歯科":
        hero_summary = f"{genre}を中心とする医院として、公開情報とAI分析をまとめた参考ページです。"
    else:
        hero_summary = f"{ward_txt}で歯科を探している方向けに、公開情報とAI分析をまとめた参考ページです。"
    facts_bits = []
    if rating and reviews:
        facts_bits.append(f"Google評価 {rating}（口コミ{reviews}件）")
    if strong_axes:
        facts_bits.append("・".join(AXIS_SHORT[k] for k in strong_axes[:2]) + "に関する肯定的な投稿が多く見られます")
    hero_facts = f'<p class="rr-summary-facts">{esc("／".join(facts_bits))}</p>' if facts_bits else ""

    chip_items = []
    if focus:
        chip_items.append(f"公式サイトで{focus}を詳しく案内")
    if rating and reviews >= 10:
        chip_items.append(f"口コミ評価 {rating}")
    elif reviews:
        chip_items.append(f"口コミ {reviews}件")
    if sun:
        chip_items.append("日曜診療の表示あり（要確認）")
    elif sat:
        chip_items.append("土曜診療の表示あり（要確認）")
    elif ev_night is True:
        chip_items.append("夜間帯の診療の表示あり（要確認）")
    hchips = ('<div class="rr-hchips">'
              + "".join(f'<span class="rr-hchip">{esc(t)}</span>' for t in chip_items[:3])
              + '</div>') if chip_items else ""

    links = ""
    if url:
        links += (f'<a class="rr-btn primary" href="{esc(url)}" target="_blank" rel="noopener" '
                  f'data-odr-ev="clinic_to_official" data-odr-v="公式サイト">公式サイトで確認</a>')
    if maps:
        links += (f'<a class="rr-btn" href="{esc(maps)}" target="_blank" rel="noopener" '
                  f'data-odr-ev="clinic_to_map" data-odr-v="地図">地図・口コミを見る</a>')
    if area_slug:
        links += (f'<a class="rr-btn" href="../area/{area_slug}" '
                  f'data-odr-ev="clinic_to_area" data-odr-v="{esc(ward_only)}">同じ{esc(ward_only)}の医院と比較</a>')

    # スマホ下部固定CTA（公式｜地図｜比較。データがあるものだけ）
    st = ""
    if url:
        st += (f'<a class="s-official" href="{esc(url)}" target="_blank" rel="noopener" '
               f'data-odr-ev="clinic_to_official" data-odr-v="公式サイト">公式サイト</a>')
    if maps:
        st += (f'<a class="s-map" href="{esc(maps)}" target="_blank" rel="noopener" '
               f'data-odr-ev="clinic_to_map" data-odr-v="地図">地図・口コミ</a>')
    if area_slug:
        st += (f'<a class="s-cmp" href="../area/{area_slug}" data-odr-ev="clinic_to_area" '
               f'data-odr-v="{esc(ward_only)}">比較</a>')
    else:
        st += ('<a class="s-cmp" href="../shindan/" data-odr-ev="clinic_to_shindan" '
               'data-odr-v="">診断</a>')
    sticky = f'<div class="rr-sticky">{st}</div>' if (url or maps) else ""

    # ── ①この医院の特徴（特徴＋向いている方＋「判断できない項目」の折りたたみ） ──
    # 根拠のある項目だけを表示（AIの当て推量は出さない・従来ルール踏襲）
    ref  = [x for x in (c.get("referral_to") or c.get("fit_for") or []) if ground_claim(x, c)[0] == "grounded"]
    nref = [x for x in (c.get("not_referral_to") or c.get("not_fit_for") or []) if ground_claim(x, c, negative=True)[0] == "grounded"]
    feats = []
    if focus_list:
        feats.append("公式サイトで" + "・".join(focus_list[:3]) + "を詳しく案内しています")
    if strong_axes:
        feats.append("口コミでは「" + "」「".join(AXIS_QUOTE[k] for k in strong_axes[:3]) + "」といった内容が多く確認できます")
    if sun:
        feats.append("日曜診療の表示があります（変更の可能性があるため公式サイトで要確認）")
    elif sat:
        feats.append("土曜診療の表示があります（変更の可能性があるため公式サイトで要確認）")
    if ev_night is True:
        feats.append("夜間帯の診療の表示があります（変更の可能性があるため公式サイトで要確認）")
    eq_ok = [k for k in EQUIP_KEYS if (equip_stars.get(k) or 0) >= 3]
    if eq_ok:
        feats.append("公式サイトで" + "・".join(("歯科用CT" if k == "CT" else k) for k in eq_ok) + "の記載を確認しています")
    elif parking_fact(c):
        feats.append("駐車場の案内があります")
    feats_html = ('<ul class="rr-list plain">' + "".join(f"<li>{esc(x)}</li>" for x in feats[:5]) + "</ul>") if feats else ""
    ref_html = ('<p class="rr-subhead">向いている可能性がある方</p><ul class="rr-list good">' + li([soften_display_text(x) for x in ref]) + "</ul>") if ref else ""
    unknown = []
    if ev_night is False:
        unknown.append("18時以降（夜間）の診療 … 公開情報では確認できませんでした")
    if deep:
        eq_un = [("歯科用CT" if k == "CT" else k) for k in ("CT", "マイクロスコープ") if (equip_stars.get(k) or 0) < 3]
        if eq_un:
            unknown.append("・".join(eq_un) + " … 公式サイト上では確認できませんでした")
    for x in nref:
        unknown.append(f"{soften_display_text(x)} … 該当する方は受診前に医院へご確認ください")
    unknown_html = ""
    if unknown:
        u_body = ("<ul>" + "".join(f"<li>{esc(x)}</li>" for x in unknown) + "</ul>"
                  "<p>※「確認できませんでした」は「無い」という意味ではありません。"
                  "実際の対応可否は公式サイト・電話でご確認ください。</p>")
        unknown_html = fold_html("公開情報だけでは判断できない項目",
                                 "夜間診療・設備など、受診前に医院へ確認したい項目です。", u_body)
    sec_glance = ""
    if feats_html or ref_html:
        sec_glance = (f'<div class="rr-panel">{feats_html}{ref_html}</div>{unknown_html}'
                      '<p class="rr-note">※ 公開情報（公式サイト・Google口コミ）から機械的に確認できた範囲です。</p>')
    elif unknown_html:
        sec_glance = unknown_html

    # ── ②診療時間・場所（前半に配置・表形式・出典と最終確認日つき） ──
    h_table = hours_table_html(hours)
    info_rows = ""
    shinryo = "／".join([x for x in [genre] + list(c.get("clinic_type") or []) if x])
    if addr:
        info_rows += f'<tr><th>所在地</th><td>{esc(addr)}</td></tr>'
    ns = c.get("nearest_station") or {}
    walk = station_walk_min(c)
    if ns.get("name") and walk is not None and walk <= 20:
        info_rows += f'<tr><th>最寄駅</th><td>{esc(ns["name"])}駅（徒歩約{walk}分〜・直線距離からの推計）</td></tr>'
    if shinryo:
        info_rows += f'<tr><th>診療</th><td>{esc(shinryo)}</td></tr>'
    if phone:
        info_rows += f'<tr><th>電話</th><td>{esc(phone)}</td></tr>'
    if hours and not h_table:
        # 表にできない形式は従来どおり文字列で（誤った表を出すより安全）
        info_rows += f'<tr><th>診療時間</th><td>{esc(" / ".join(str(x) for x in hours[:7]))}</td></tr>'
    info_html = f'<table class="rr-info">{info_rows}</table>' if info_rows else ""
    map_link = (f'<a class="rr-maplink" href="{esc(maps)}" target="_blank" rel="noopener" '
                f'data-odr-ev="clinic_to_map" data-odr-v="地図">Googleマップで場所・口コミを見る</a>') if maps else ""
    sec_access = ""
    if h_table or info_html:
        sec_access = h_table + (hours_note_html(c, analyzed) if h_table else "") + info_html + map_link

    # ── ③口コミから見える傾向（数値バー廃止→傾向表。指数は分析根拠で開示） ──
    trend_rows = ""
    for k in PATIENT_AXES:
        v = ps.get(k) or 0
        if v <= 0:
            continue
        word, cls = trend_word(v)
        trend_rows += f'<tr><td>{esc(AXIS_PATIENT_LABEL[k])}</td><td class="v{cls}">{word}</td></tr>'
    sec_reviews = ""
    if trend_rows and reviews:
        s = ""
        if strong_axes:
            s += "口コミでは「" + "」「".join(AXIS_QUOTE[k] for k in strong_axes[:3]) + "」といった内容が多く確認できました。"
        if weak_axes:
            s += "一方で、" + "・".join(AXIS_SHORT[k] for k in weak_axes[:2]) + "については評価が分かれています。"
        s += f"（Google口コミ{reviews}件をAIが分析）"
        sec_reviews = (f'<p class="rr-review-text">{esc(s)}</p>'
                       '<table class="rr-trend"><thead><tr><th>口コミで多く見られた内容</th><th>傾向</th></tr></thead>'
                       f'<tbody>{trend_rows}</tbody></table>'
                       '<p class="rr-note">※「傾向」は口コミ本文にその話題の肯定的な言及がどの程度あったかを'
                       'AIが分類したもので、医院の医療技術そのものを採点したものではありません。'
                       '分類の目安（言及指数）は下の「この分析は何にもとづくか」で開示しています。</p>')

    # 診療理念・注力治療（実データのみ・従来どおり）
    care_bits = ""
    if c.get("philosophy"):
        care_bits += f'<p class="rr-quote">「{esc(c["philosophy"])}」</p>'
    if c.get("focus_treatments"):
        care_bits += f'<div class="rr-chips">{chips(c.get("focus_treatments"))}</div>'
    sec_policy = care_bits

    # 院長プロフィール（事実情報のみ。旧「院長評価」の星バーは採点誤読のため廃止）
    doc = ""
    if c.get("doctor_name"):
        doc += f'<p class="rr-docname">院長　{esc(c["doctor_name"])}</p>'
    if c.get("doctor_career"):
        doc += f'<p class="rr-lead">{esc(c["doctor_career"])}</p>'
    if c.get("qualifications"):
        doc += f'<ul class="rr-quals">{li(c.get("qualifications"))}</ul>'
    sec_doc = doc

    # 特徴ページ（features/index.html）へのタグ相互リンク
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

    # ── ④この分析は何にもとづくか（根拠開示＋言及指数＋情報充実度。折りたたみ） ──
    # 薄いページでは定型空文のAI要約を出さない（従来ルール踏襲）
    ai = c.get("ai_summary", "")
    if is_thin(c) and not has_substantive_ai(c):
        ai = ""
    m = compute_metrics(c)
    ev_body = evidence_panel_html(c) if ai else ""
    meth = ""
    idx_txt = "・".join(f"{AXIS_PATIENT_LABEL[k]} {int(ps[k])}" for k in PATIENT_AXES if (ps.get(k) or 0) > 0)
    if idx_txt:
        meth += ("<p><strong>傾向の分類方法：</strong>口コミ本文の文脈をAIが話題ごとに定量化した"
                 f"「言及指数」（100点満点：{esc(idx_txt)}）を「多い（80以上）／やや多い（76〜79）／"
                 "評価が分かれる（75以下または肯定否定が混在）」に区分しています。"
                 "医療技術そのものの評価ではありません。</p>")
    meth += (f"<p><strong>情報充実度：</strong>{m['confidence']}/100"
             "（この医院の分析に使えた公開情報の量と一致度の指標です。分析が正しい確率ではありません）。"
             f"参照データ源 {m['research_sources']}種類。</p>")
    meth += ("<p><strong>限界：</strong>本分析は公開情報にもとづく意見・論評であり、"
             "医療上の判断や治療結果を保証するものではありません。"
             "根拠が確認できなかった設備・特徴は表示していません。</p>")
    sub_bits = []
    if reviews:
        sub_bits.append(f"Google口コミ{reviews}件")
    if deep:
        sub_bits.append("公式サイト")
    sub = ("・".join(sub_bits) + "を分析" if sub_bits else "公開情報を分析")
    if analyzed:
        sub += f"（分析日 {analyzed}）"
    sub += "。何が事実で何がAI推定かを開示しています。"
    sec_method = fold_html("使用データ・確認日・分類方法・情報充実度を見る", esc(sub), ev_body + meth)
    if sec_method:
        # 分析根拠の折りたたみはセクション先頭に置くため上マージンを消す
        sec_method = sec_method.replace('<div class="rr-fold">', '<div class="rr-fold" style="margin-top:0;">', 1)

    # ── セクション出力（番号なし・空セクションは自動非表示＝データ量に応じた自動分岐） ──
    ordered = [
        ("この医院の特徴",           "At a glance",    sec_glance),
        ("診療時間・場所",           "Hours & Access", sec_access),
        ("口コミから見える傾向",     "Reviews",        sec_reviews),
        ("地域の中で見る",           "In the area",    area_context_html(c)),
        ("診療理念・注力治療",       "",               sec_policy),
        ("院長プロフィール",         "",               sec_doc),
        ("該当する特徴",             "",               sec_tags),
        ("関連する研究レポート",     "",               sec_related),
        ("この分析は何にもとづくか", "Methodology",    sec_method),
        ("次にすること",             "Next",           next_steps_html(c, ward_only, area_slug, tag_links)),
    ]
    body = ""
    for ja, en, inner in ordered:
        if not inner:
            continue
        en_html = f'<span class="rr-sec-en">{esc(en)}</span>' if en else ""
        body += (f'<section class="rr-sec"><div class="rr-sec-h">{en_html}'
                 f'<h2>{esc(ja)}</h2></div>{inner}</section>')

    area_link = (f'<a class="rr-cta-btn ghost" href="../area/{area_slug}.html">{ward_only}の医院一覧</a>'
                 if area_slug else "")

    # meta description：機械導出の要約のみを使う（AI要約の強い断定をdescに残さない・2026-07-14）
    desc = f"{name}（{ward_txt}）の口コミ・評判をAIが分析。{hero_summary}"
    if rating and reviews:
        desc += f"Google評価{rating}・口コミ{reviews}件。"
    desc += "診療時間・地図・公式サイトへの導線も掲載。"

    # 薄いページはnoindex,follow（インデックス対象から除外・リンクは辿らせる）
    robots_meta = ('<meta name="robots" content="noindex,follow">\n'
                   if is_thin(c) else "")

    return (TEMPLATE.replace("{name}", esc(name)).replace("{addr}", esc(addr))
            .replace("{summary}", esc(hero_summary))
            .replace("{facts}", hero_facts)
            .replace("{hchips}", hchips)
            .replace("{sticky}", sticky)
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
/* ── 次の一歩（回遊導線・2026-07-14 指示書③） ── */
.rr-next{margin:0;padding:0;list-style:none;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.rr-next li{border-bottom:1px solid var(--line);}
.rr-next li:last-child{border-bottom:none;}
.rr-next a{display:block;padding:14px 20px;text-decoration:none;transition:background .15s;}
.rr-next a:hover{background:rgba(31,75,63,.04);}
.rr-next .t{display:block;font-weight:700;color:var(--pine);font-size:.95rem;}
.rr-next .t::after{content:"→";margin-left:8px;color:var(--terra);font-weight:500;}
.rr-next .why{display:block;font-size:.8rem;color:var(--ink2);margin-top:3px;line-height:1.7;}
.rr-next-final{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;}
.rr-btn-line{display:inline-block;padding:10px 20px;border:1px solid var(--pine);border-radius:8px;font-size:.86rem;font-weight:500;color:var(--pine);text-decoration:none;background:#fff;}
.rr-btn-line:hover{background:var(--pine);color:#fff;}
/* ── 患者向け再編集（2026-07-14 全面改修） ── */
.rr-summary{color:#eaf3ee;font-size:1.06rem;font-weight:500;margin:0 0 6px;line-height:1.7;}
.rr-summary-facts{color:#cfe0d8;font-size:.9rem;margin:0 0 18px;}
.rr-hchips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px;}
.rr-hchip{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.22);border-radius:999px;padding:6px 15px;font-size:.84rem;font-weight:500;color:#fff;}
.rr-sec-h{display:block;}
.rr-sec-h h2{padding-left:12px;border-left:4px solid var(--pine);font-size:1.28rem;}
.rr-panel{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 24px;box-shadow:0 4px 20px rgba(20,50,40,.04);}
.rr-subhead{font-size:.95rem;font-weight:700;color:var(--pine);margin:22px 0 10px;}
.rr-list.plain li{padding:10px 0 10px 20px;border-bottom:1px solid var(--line);}
.rr-list.plain li:last-child{border-bottom:none;}
.rr-list.plain li::before{content:"–";position:absolute;left:0;top:10px;color:var(--ink2);}
.rr-hours{width:100%;border-collapse:collapse;font-size:.94rem;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.rr-hours th,.rr-hours td{padding:12px 16px;border-bottom:1px solid var(--line);text-align:left;}
.rr-hours thead th{background:#fbfcfb;color:var(--ink2);font-weight:500;font-size:.82rem;}
.rr-hours tbody th{width:96px;color:var(--ink2);font-weight:500;background:#fbfcfb;}
.rr-hours tr:last-child th,.rr-hours tr:last-child td{border-bottom:none;}
.rr-hours-note{margin:12px 0 0;padding:12px 16px;background:#faf8f5;border-left:3px solid var(--terra);border-radius:0 8px 8px 0;font-size:.84rem;line-height:1.8;color:#3d4643;}
.rr-hours-note strong{color:#2c3532;}
.rr-maplink{display:inline-block;margin-top:14px;padding:10px 20px;border:1px solid var(--pine);border-radius:8px;font-size:.86rem;font-weight:500;color:var(--pine);text-decoration:none;background:#fff;}
.rr-maplink:hover{background:var(--pine);color:#fff;}
.rr-review-text{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 24px;font-size:.98rem;line-height:1.9;margin:0 0 16px;}
.rr-trend{width:100%;border-collapse:collapse;font-size:.94rem;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;}
.rr-trend th,.rr-trend td{padding:12px 18px;border-bottom:1px solid var(--line);text-align:left;}
.rr-trend thead th{background:#fbfcfb;color:var(--ink2);font-weight:500;font-size:.82rem;}
.rr-trend tr:last-child th,.rr-trend tr:last-child td{border-bottom:none;}
.rr-trend td.v{width:130px;font-weight:700;color:var(--pine);}
.rr-trend td.v.mixed{color:var(--terra);}
.rr-fold{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;margin-top:16px;}
.rr-fold-btn{width:100%;text-align:left;background:none;border:none;padding:18px 22px;font-family:inherit;font-size:1rem;font-weight:700;color:var(--pine);cursor:pointer;display:flex;justify-content:space-between;align-items:center;gap:12px;}
.rr-fold-btn .sub{display:block;font-size:.8rem;font-weight:400;color:var(--ink2);margin-top:4px;line-height:1.6;}
.rr-fold-btn .mk{flex-shrink:0;color:var(--terra);font-weight:700;}
.rr-fold-body{padding:0 22px 20px;font-size:.9rem;line-height:1.85;color:#3d4643;}
.rr-fold-body p{margin:0 0 10px;}
.rr-fold-body ul{margin:0 0 10px;padding-left:20px;}
.rr-sticky{position:fixed;left:0;right:0;bottom:0;z-index:40;display:none;background:#fff;border-top:1px solid var(--line);box-shadow:0 -4px 16px rgba(20,50,40,.08);padding:8px 10px;gap:8px;}
.rr-sticky a{flex:1;text-align:center;padding:11px 4px;border-radius:8px;font-size:.82rem;font-weight:700;text-decoration:none;}
.rr-sticky .s-official{background:var(--terra);color:#fff;}
.rr-sticky .s-map,.rr-sticky .s-cmp{background:#fff;color:var(--pine);border:1px solid var(--pine);}
@media(max-width:760px){.rr-sticky{display:flex;}body{padding-bottom:72px;}}
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
<body data-clinic="{name}">
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
    <p class="rr-address">{addr}</p>
    <p class="rr-summary">{summary}</p>
    {facts}
    {hchips}
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
{sticky}
<script>
/* 折りたたみ（見出し＋要約は常時可視・中身はDOMに残す＝SEOを壊さない） */
document.addEventListener("click",function(ev){
  var b=ev.target.closest("[data-fold]"); if(!b)return;
  var panel=b.nextElementSibling;
  var open=b.getAttribute("aria-expanded")==="true";
  b.setAttribute("aria-expanded",open?"false":"true");
  if(panel)panel.hidden=open;
  var mk=b.querySelector(".mk"); if(mk)mk.textContent=open?"＋":"−";
});
/* 回遊導線のGA4計測（クリック委譲・2026-07-14 指示書③）。
   イベント名 clinic_to_area / clinic_to_condition / clinic_to_shindan /
   clinic_to_official / clinic_to_map / clinic_to_tel。
   パラメータは既存規約に合わせ clinic_name / filter_value を使う。 */
document.addEventListener("click",function(ev){
  var a=ev.target.closest("[data-odr-ev]"); if(!a||typeof window.odrTrack!=="function")return;
  window.odrTrack(a.getAttribute("data-odr-ev"),
    {clinic_name:document.body.getAttribute("data-clinic")||"",
     filter_value:a.getAttribute("data-odr-v")||""});
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
