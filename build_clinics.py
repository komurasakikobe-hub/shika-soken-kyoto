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

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
OUT = os.path.join(ROOT, "articles", "clinics")
SLUG_MAP_PATH = os.path.join(ROOT, "clinic_slugs.json")
with open(SLUG_MAP_PATH, encoding="utf-8") as _f:
    SLUG_MAP = json.load(_f)  # place_id -> 一意なslug（generate_slug_map.py参照。同姓同名の医院URL衝突対策）

def nowrap_pipe(escaped_title):
    """タイトルと副題がきれいに分かれるよう、｜の直前、または？／！の直後(京都の前)で改行する"""
    import re as _re
    if "｜" in escaped_title:
        return escaped_title.replace("｜", "<br>｜", 1)
    return _re.sub(r"([？！])京都", r"\1<br>京都", escaped_title, count=1)

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

def build_jsonld(c, slug):
    """Google検索のリッチリザルト向け構造化データ（JSON-LD, schema.org/Dentist）。
    緯度経度（Nominatimで取得済み）・住所・電話・診療時間を機械可読で埋め込む。
    確認できる公開情報のみを出力し、評価の断定はしない（口コミ数値は
    aggregateRatingとしてGoogle由来の実数値のみ）。"""
    import json as _json
    data = {
        "@context": "https://schema.org",
        "@type": "Dentist",
        "name": c.get("name", ""),
        "url": f"https://shikasoken.com/articles/clinics/{slug}.html",
    }
    if c.get("address"):
        data["address"] = {"@type": "PostalAddress", "streetAddress": c["address"], "addressRegion": "京都府"}
    if c.get("latitude") and c.get("longitude"):
        data["geo"] = {"@type": "GeoCoordinates", "latitude": c["latitude"], "longitude": c["longitude"]}
    if c.get("phone"):
        data["telephone"] = c["phone"]
    hours = c.get("business_hours") or []
    if isinstance(hours, list) and hours:
        data["openingHours"] = hours[:7]
    if c.get("rating") and c.get("total_reviews"):
        data["aggregateRating"] = {
            "@type": "AggregateRating",
            "ratingValue": c["rating"],
            "reviewCount": c["total_reviews"],
        }
    return ('<script type="application/ld+json">'
            + _json.dumps(data, ensure_ascii=False)
            + "</script>")


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
    ai = c.get("ai_summary", "")
    sec_summary = (f'<div class="rr-ai"><span class="rr-ai-label">AI Analysis</span>'
                   f'<p>{esc(ai)}</p></div>') if ai else ""

    # 主要所見：口コミ特徴＋専門性タグを統合した"Key Findings"
    key = []
    key += list(c.get("reputation_tags") or [])
    key += [t for t in (c.get("specialty_tags") or []) if t not in key]
    sec_key = (f'<ul class="rr-findings">{findings(key)}</ul>{SRC_NOTE}') if key else ""

    ctype_html = f'<div class="rr-chips">{chips(c.get("clinic_type"))}</div>' if c.get("clinic_type") else ""

    pbars = bar_rows(c.get("patient_scores"), PATIENT_AXES, 100)
    sec_patient = (f'<div class="rr-bars">{pbars}</div>'
                   f'<p class="rr-note">口コミ本文の文脈をAIが7軸で定量化（100点満点・京都歯科総研 独自指標）。</p>') if pbars else ""

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
    ref = c.get("referral_to") or c.get("fit_for")
    nref = c.get("not_referral_to") or c.get("not_fit_for")
    conclusion_bits = ""
    if ref:
        conclusion_bits += (f'<p class="rr-concl-label good">この医院が向いている方</p>'
                            f'<ul class="rr-list good">{li(ref)}</ul>')
    if c.get("not_recommended_profile") or nref:
        conclusion_bits += '<p class="rr-concl-label bad">注意が必要な方</p>'
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

    return (TEMPLATE.replace("{name}", esc(name)).replace("{addr}", esc(addr))
            .replace("{catch}", catch_html).replace("{meta}", meta_html)
            .replace("{fact}", fact_html)
            .replace("{links}", links).replace("{body}", body)
            .replace("{jsonld}", build_jsonld(c, slug))
            .replace("{ogurl}", f"https://shikasoken.com/articles/clinics/{quote(slug)}.html")
            .replace("{desc}", esc((ai or name)[:110])))

TEMPLATE = '''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{name}｜京都歯科総研 AI Research Report</title>
<meta name="description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="京都歯科総研">
<meta property="og:title" content="{name}｜京都歯科総研 AI Research Report">
<meta property="og:description" content="{desc}">
<meta property="og:url" content="{ogurl}">
<meta name="twitter:card" content="summary">
{jsonld}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@400;500;700&family=Roboto+Mono:wght@500&display=swap" rel="stylesheet">
<style>
:root{--pine:#1f4b3f;--terra:#d98b5f;--paper:#f6f8f7;--ink:#1c2b25;--ink2:#5c6d66;--line:#e4ebe7;--mono:'Roboto Mono',monospace;}
*{box-sizing:border-box;}
body{margin:0;font-family:'Noto Sans JP','Hiragino Kaku Gothic ProN',sans-serif;color:var(--ink);background:var(--paper);-webkit-font-smoothing:antialiased;line-height:1.8;}
a{color:inherit;}
.rr-nav{background:var(--pine);color:#fff;padding:0 clamp(20px,4vw,40px);height:64px;display:flex;align-items:center;justify-content:space-between;}
.rr-nav .logo{font-weight:700;text-decoration:none;}
.rr-nav .logo small{display:block;font-size:.58rem;letter-spacing:.16em;color:#9cbbae;font-weight:400;}
.rr-nav .back{font-size:.82rem;color:#cfe0d8;text-decoration:none;}
/* ── レポートヘッダー ── */
.rr-hero{background:var(--pine);color:#fff;padding:clamp(30px,5vw,56px) clamp(20px,4vw,40px) clamp(40px,5vw,60px);}
.rr-hero-in{max-width:860px;margin:0 auto;}
.rr-tag{display:inline-flex;align-items:center;gap:8px;font-family:var(--mono);font-size:.7rem;letter-spacing:.22em;color:var(--terra);border:1px solid rgba(217,139,95,.5);border-radius:999px;padding:5px 14px;margin-bottom:20px;}
.rr-tag::before{content:"";width:6px;height:6px;border-radius:50%;background:var(--terra);}
.rr-name{font-size:clamp(1.6rem,3.4vw,2.3rem);font-weight:700;margin:0 0 10px;line-height:1.35;}
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
<script src="../assets/site-config.js"></script>
<script src="../assets/odr-track.js"></script>
</head>
<body>
<header class="rr-nav">
  <a class="logo" href="../../index.html">京都歯科総研<small>KYOTO DENTAL RESEARCH</small></a>
  <a class="back" href="../features/index.html">← 特徴から探す</a>
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
    <p class="rr-cta-s">症状・エリア・ご希望から、AIが京都市内 約2,050院を無料でマッチングします。</p>
    <div class="rr-cta-btns">
      <a class="rr-cta-btn" href="../shindan/index.html">AI診断を受ける（無料）</a>
      <a class="rr-cta-btn ghost" href="../features/index.html">特徴から探す</a>
    </div>
  </section>
</main>
<footer class="rr-foot">
  <div class="in">当レポートのAI分析（サマリー・各スコア等）は、Googleマップの口コミや各医院公式サイト等の公開情報をもとに京都歯科総研が独自に生成した参考情報です。根拠となる情報がない項目は表示していません。診断・治療方針の決定を目的としたものではなく、受診の判断は必ず歯科医師にご相談ください。<br>© 京都歯科総研 KYOTO DENTAL RESEARCH</div>
</footer>
</body>
</html>'''

def main():
    db = json.load(open(DB, encoding="utf-8"))
    clinics = list(db.values()) if isinstance(db, dict) else db
    os.makedirs(OUT, exist_ok=True)
    n = 0
    valid = set()
    for c in clinics:
        name = c.get("name")
        if not name:
            continue
        if c.get("q_excluded"):   # 京都市外・サロン・重複は生成しない（品質フラグ）
            continue
        slug = SLUG_MAP.get(c.get("place_id"), slugify(name))  # 衝突対策済みの一意なslugを使用
        valid.add(slug)
        open(os.path.join(OUT, slug + ".html"), "w", encoding="utf-8").write(build_page(c, slug))
        n += 1
    # 現DBに対応しないオーファンページを削除
    import glob
    removed = 0
    for f in glob.glob(os.path.join(OUT, "*.html")):
        if os.path.basename(f)[:-5] not in valid:
            os.remove(f); removed += 1
    print(f"✅ 医院AI Research Report 生成: {n}院 / オーファン削除: {removed}")

if __name__ == "__main__":
    main()
