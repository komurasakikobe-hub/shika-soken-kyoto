# -*- coding: utf-8 -*-
"""
医院向け「反響レポート」生成スクリプト（営業用・無料配布の入口商品）

京都歯科総研に掲載中の医院1院分の、
  ① 掲載状況（当サイトでどう見えているか）
  ② 公開情報の充実度診断（何が不足して表示機会を逃しているか）
  ③ サイト内での反響数値（GA4から。データが貯まるまでは手入力可）
  ④ 改善提案（→AI評判設計プランへの導線）
を1枚のHTMLレポートにする。

使い方：
  python3 clinic_report.py "医院名"                       # 反響数値なし版
  python3 clinic_report.py "医院名" --views 32 --clicks 3  # GA4の数値を渡す版

出力：_reports/反響レポート_<医院名>_<年月>.html
※ 医院名は部分一致で検索する。複数ヒット時は候補を表示して終了。
"""
import argparse
import json
import re
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "_reports"

# ランキングページ（shindan.js）のinfoLevelと同じ思想の診断項目。
# 「充実していれば患者の条件に一致しやすい＝表示機会が増える」ことを
# 医院に説明するための材料になる。
CHECK_ITEMS = [
    ("公式サイトURL",         lambda c: bool(c.get("url")),
     "患者が詳細を確認できず、送客先がなくなります"),
    ("公式サイトの深掘り解析", lambda c: bool(c.get("deep_fetched")),
     "診療方針・設備がAI分析に反映されず、条件一致で不利になります"),
    ("Google口コミ",           lambda c: (c.get("total_reviews") or 0) > 0,
     "口コミ・評判軸の評価材料がない状態です"),
    ("診療時間の掲載",         lambda c: bool(c.get("business_hours")),
     "「夜間」「土日」等の条件検索でヒットしません"),
    ("設備情報（CT・個室等）", lambda c: bool(c.get("equipment_stars")) and any((v or 0) > 0 for v in (c.get("equipment_stars") or {}).values()),
     "「精密な検査」「個室」等の希望条件で一致できません"),
    ("特徴タグ（駐車場・キッズ等）", lambda c: bool(c.get("site_features") or c.get("specialty_tags")),
     "「駐車場あり」「子ども連れ」等の条件で一致できません"),
    ("院長情報・経歴",         lambda c: bool(c.get("doctor_name") or c.get("doctor_career")),
     "「経験豊富」「専門医」を重視する患者の条件で不利になります"),
    ("料金・費用の説明",       lambda c: any("円" in t or "料金" in t or "保険" in t for t in (c.get("transparency_evidence") or [])),
     "費用を気にする患者（検索の中でも特に多い層）に選ばれにくくなります"),
]


def find_clinic(db: dict, query: str):
    hits = [c for c in db.values()
            if not c.get("q_excluded") and c.get("name") and query in c["name"]]
    return hits


def esc(s):
    import html
    return html.escape(str(s), quote=True)


def build_report(c, views=None, clicks=None, maps=None):
    today = date.today()
    month_label = f"{today.year}年{today.month}月"
    name = c.get("name", "")

    checks = []
    ok_count = 0
    for label, pred, risk in CHECK_ITEMS:
        ok = bool(pred(c))
        ok_count += ok
        checks.append((label, ok, risk))
    total = len(CHECK_ITEMS)
    level = "充実" if ok_count >= 7 else ("標準" if ok_count >= 5 else "不足")

    ns = c.get("nearest_station") or {}
    station = f"{ns.get('name','')}駅 徒歩圏" if ns else "—"

    check_rows = "".join(
        f'<tr class="{ "ok" if ok else "ng" }">'
        f'<td class="mark">{"✓" if ok else "×"}</td>'
        f'<td>{esc(label)}</td>'
        f'<td class="risk">{"" if ok else esc(risk)}</td></tr>'
        for label, ok, risk in checks
    )

    if views is not None:
        stats_html = f"""
  <div class="stats">
    <div class="stat"><span class="v">{views:,}</span><span class="k">当サイトでの表示回数</span></div>
    <div class="stat"><span class="v">{clicks if clicks is not None else "—"}</span><span class="k">公式サイトへの移動</span></div>
    <div class="stat"><span class="v">{maps if maps is not None else "—"}</span><span class="k">地図の表示</span></div>
  </div>
  <p class="stats-note">※ {month_label}の京都歯科総研内での数値（Googleアナリティクス計測）。</p>"""
    else:
        stats_html = """
  <p class="stats-note">※ 反響数値（表示回数・クリック数）は計測を開始したところです。翌月のレポートから掲載します。</p>"""

    missing = [(label, risk) for label, ok, risk in checks if not ok]
    if missing:
        proposal = f"""
  <h2>改善のご提案</h2>
  <p>上記の「×」の項目は、貴院の実力とは関係なく、<strong>公開情報が確認できなかった</strong>ことを意味します。
  当サイトのランキングは患者が選んだ条件との一致で表示順が決まるため、情報が確認できないと
  本来一致するはずの条件でも表示機会を逃します。</p>
  <p>情報の掲載・修正は<strong>無料</strong>です。まずは公式サイトや当サイトへの情報提供で改善できます。
  さらに、公開情報の設計から口コミ・AI検索対策までを継続的に行う
  「AI評判設計プラン」もご用意しています。お気軽にご相談ください。</p>"""
    else:
        proposal = """
  <h2>今後のご提案</h2>
  <p>貴院の公開情報は充実しています。この状態を維持しつつ、口コミ・AI検索での見え方を
  定点観測する「AI評判設計プラン」で、さらに選ばれやすい状態を作ることができます。</p>"""

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>反響レポート｜{esc(name)}｜{esc(CFG["site_name"])}</title>
<style>
body{{margin:0;font-family:'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;background:#f4f7f6;color:#1c2b25;line-height:1.9;}}
.wrap{{max-width:720px;margin:0 auto;padding:40px 24px 64px;}}
.head{{background:#1d4f47;color:#fff;border-radius:14px;padding:28px 32px;margin-bottom:28px;}}
.head .brand{{font-size:.72rem;letter-spacing:.18em;color:rgba(255,255,255,.6);margin:0 0 10px;}}
.head h1{{font-size:1.25rem;margin:0 0 6px;}}
.head .sub{{font-size:.82rem;color:rgba(255,255,255,.75);margin:0;}}
h2{{font-size:1.02rem;color:#1d4f47;border-left:4px solid #dd7550;padding-left:10px;margin:36px 0 14px;}}
.stats{{display:flex;gap:12px;margin:16px 0 8px;}}
.stat{{flex:1;background:#fff;border:1px solid #e2e8e6;border-radius:12px;padding:16px;text-align:center;}}
.stat .v{{display:block;font-size:1.6rem;font-weight:700;color:#1d4f47;}}
.stat .k{{font-size:.72rem;color:#8a9ba8;}}
.stats-note{{font-size:.74rem;color:#8a9ba8;}}
table{{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;border:1px solid #e2e8e6;}}
td{{padding:10px 14px;border-bottom:1px solid #eef2f1;font-size:.86rem;vertical-align:top;}}
tr:last-child td{{border-bottom:none;}}
.mark{{width:28px;font-weight:700;text-align:center;}}
tr.ok .mark{{color:#2b6c61;}}
tr.ng .mark{{color:#c0392b;}}
.risk{{font-size:.76rem;color:#8a5a4a;}}
.level{{display:inline-block;background:#e8f4f0;color:#1d4f47;font-weight:700;border-radius:999px;padding:4px 16px;font-size:.84rem;margin-left:8px;}}
.cta{{background:#fff;border:1px solid #e2e8e6;border-radius:12px;padding:20px 24px;margin-top:28px;}}
.cta p{{margin:6px 0;font-size:.86rem;}}
.foot{{font-size:.72rem;color:#8a9ba8;margin-top:36px;line-height:1.8;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <p class="brand">{esc(CFG["site_name_en"])} — CLINIC REPORT</p>
    <h1>{esc(name)} 様　反響レポート</h1>
    <p class="sub">{month_label}版 ・ {esc(CFG["site_name"])}（{esc(CFG["domain"])}）</p>
  </div>

  <h2>掲載状況</h2>
  <p>{esc(CFG["city"])}内の歯科医院を条件別に並び替えられる当サイトの「データランキング」に、
  貴院は現在掲載されています（最寄駅：{esc(station)}）。掲載・分析はすべて公開情報に
  もとづいており、掲載料はいただいていません。</p>
  {stats_html}

  <h2>公開情報の充実度診断<span class="level">{ok_count}/{total}項目 ・ {level}</span></h2>
  <p>患者が選んだ条件（地域・症状・希望条件）と貴院が一致するかは、確認できた公開情報で決まります。</p>
  <table>{check_rows}</table>

  {proposal}

  <div class="cta">
    <p><strong>お問い合わせ・情報の修正窓口</strong></p>
    <p>メール：{esc(CFG["contact_email"])}（件名に【医院情報修正】または【AI評判設計プラン】とご記載ください）</p>
    <p>修正のご依頼で掲載順位を直接変更することはできませんが、公開情報が充実するほど、患者の条件に一致しやすくなります。</p>
  </div>

  <p class="foot">本レポートは{esc(CFG["site_name"])}が公開情報（Google口コミ・公式サイト等）をもとに独自に作成した参考資料です。
  医院の技術や治療結果の優劣を評価するものではありません。掲載内容に誤りがある場合は上記窓口までご連絡ください。</p>
</div>
</body>
</html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="医院名（部分一致）")
    ap.add_argument("--views", type=int, default=None, help="当サイトでの表示回数（GA4）")
    ap.add_argument("--clicks", type=int, default=None, help="公式サイトクリック数（GA4）")
    ap.add_argument("--maps", type=int, default=None, help="地図クリック数（GA4）")
    args = ap.parse_args()

    db = json.loads((ROOT / "clinic_db.json").read_text(encoding="utf-8"))
    hits = find_clinic(db, args.name)
    if not hits:
        print(f"❌ 「{args.name}」に一致する医院が見つかりません")
        return
    if len(hits) > 1:
        print(f"⚠️ {len(hits)}件ヒットしました。より具体的な名前で指定してください：")
        for c in hits[:10]:
            print("  -", c["name"], "|", c.get("address", "")[:30])
        return

    c = hits[0]
    OUT_DIR.mkdir(exist_ok=True)
    today = date.today()
    safe = re.sub(r'[\\/:*?"<>|]', "", c["name"])[:30]
    out = OUT_DIR / f"反響レポート_{safe}_{today.year}年{today.month}月.html"
    out.write_text(build_report(c, args.views, args.clicks, args.maps), encoding="utf-8")
    print(f"✅ レポート生成: {out}")


if __name__ == "__main__":
    main()
