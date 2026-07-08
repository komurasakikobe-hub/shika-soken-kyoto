# -*- coding: utf-8 -*-
"""
医院向け「反響レポート」生成スクリプト（営業用・無料配布の入口商品）

設計思想（2026-07-08 全面改訂）：
  「情報をください」を先に言うレポートは、知らないサイトからの一方的な要求にしか見えず、
  医院側に渡すメリットがない。そのため構成を逆転し、
    ① まず無料で作成済みのAI分析・キャッチコピーを見せる（＝既に価値を渡している）
    ② 近隣の同条件医院と比べた掲載状況の客観的な位置づけを見せる（競合の中の立ち位置）
    ③ 情報を追加すると"具体的にどの検索条件で拾われるようになるか"を示す（ベネフィット提示。
       「情報がないとマイナス」ではなく「あるとこう伸びる」の書き方に統一）
    ④ 反響数値（GA4があれば）
    ⑤ 窓口・AI評判設計プランへの導線
  の順にする。「無料の価値提供が先、依頼は後」を貫く。

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

# 「情報がないとこう不利」ではなく「情報を足すとこの条件で拾われる」というベネフィット文言に統一。
# 患者が実際に選ぶ条件タブ（shindan.jsのCONDITION_MAP）と対応させている。
GROWTH_ITEMS = [
    ("公式サイトURL", lambda c: bool(c.get("url")),
     "「詳しく知りたい」患者の送客先ができ、そのまま来院につながりやすくなります"),
    ("公式サイトの深掘り解析", lambda c: bool(c.get("deep_fetched")),
     "診療方針・設備がAI分析に反映され、条件が一致する患者によりマッチしやすくなります"),
    ("Google口コミ", lambda c: (c.get("total_reviews") or 0) > 0,
     "口コミは実際の来院者の信頼材料になり、初めての方の来院ハードルを下げます"),
    ("診療時間の掲載", lambda c: bool(c.get("business_hours")),
     "「土日診療」「夜間診療」で探している患者の検索結果に表示されるようになります"),
    ("設備情報（CT・個室等）", lambda c: bool(c.get("equipment_stars")) and any((v or 0) > 0 for v in (c.get("equipment_stars") or {}).values()),
     "「精密検査を受けたい」「個室希望」の条件で探している患者に表示されるようになります"),
    ("特徴タグ（駐車場・キッズ等）", lambda c: bool(c.get("site_features") or c.get("specialty_tags")),
     "「駐車場あり」「子ども連れ歓迎」の条件で探している患者に表示されるようになります"),
    ("院長情報・経歴", lambda c: bool(c.get("doctor_name") or c.get("doctor_career")),
     "「経験豊富な院長」「専門医」を重視する患者に選ばれやすくなります"),
    ("料金・費用の説明", lambda c: any("円" in t or "料金" in t or "保険" in t for t in (c.get("transparency_evidence") or [])),
     "費用を事前に知りたい患者（検索の中でも特に多い層）に選ばれやすくなります"),
]


def find_clinic(db: dict, query: str):
    hits = [c for c in db.values()
            if not c.get("q_excluded") and c.get("name") and query in c["name"]]
    return hits


def esc(s):
    import html
    return html.escape(str(s), quote=True)


def ward_of(addr):
    """近隣比較のグルーピング単位を返す。
    区がある都市：「○○市△△区」。区がない都市（尼崎・西宮・芦屋等）や
    複数市町の合成ブロック（阪神北部等）では、site_config.jsonのareasに
    列挙された市町名のいずれかにマッチさせる。それも無ければ市全体（CFG["city"]）
    を1グループとして扱う（＝掲載院全体との比較になる）。"""
    addr = addr or ""
    city = CFG.get("city", "")
    m = re.search(rf'{re.escape(city)}[^\d]*?区', addr) if city else None
    if m:
        return m.group(0)
    m = re.search(r'([^\s0-9０-９]{1,4}区)', addr)
    if m:
        return m.group(1)
    areas = CFG.get("areas") or []
    for a in areas:
        if a in addr:
            return a
    return city


def peer_stats(db: dict, c: dict):
    """同じ区の他院と比べた、貴院の客観的な立ち位置を計算する。"""
    w = ward_of(c.get("address", ""))
    if not w:
        return None
    peers = [v for v in db.values()
             if not v.get("q_excluded") and v.get("name") and ward_of(v.get("address", "")) == w]
    if len(peers) < 3:
        return None
    scores = sorted((v.get("total_score", 0) for v in peers), reverse=True)
    my_score = c.get("total_score", 0)
    rank = sum(1 for s in scores if s > my_score) + 1
    avg_reviews = sum((v.get("total_reviews") or 0) for v in peers) / len(peers)
    return {
        "ward": w,
        "n_peers": len(peers),
        "rank": rank,
        "avg_reviews": round(avg_reviews),
        "my_reviews": c.get("total_reviews") or 0,
    }


def build_report(c, db=None, views=None, clicks=None, maps=None):
    today = date.today()
    month_label = f"{today.year}年{today.month}月"
    name = c.get("name", "")

    checks = []
    ok_count = 0
    for label, pred, benefit in GROWTH_ITEMS:
        ok = bool(pred(c))
        ok_count += ok
        checks.append((label, ok, benefit))
    total = len(GROWTH_ITEMS)

    ns = c.get("nearest_station") or {}
    station = f"{ns.get('name','')}駅 徒歩圏" if ns else "—"

    # ── ① 無料で既に作成済みの分析（先に価値を見せる）──
    catchphrase = c.get("catchphrase") or ""
    ai_summary = c.get("ai_summary") or ""
    tags = c.get("reputation_tags") or []
    best_patient = c.get("best_patient_profile") or ""
    tags_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags[:5])

    showcase_html = ""
    if catchphrase or ai_summary:
        showcase_html = f"""
  <div class="showcase">
    {f'<p class="catch">「{esc(catchphrase)}」</p>' if catchphrase else ""}
    {f'<p class="summary">{esc(ai_summary)}</p>' if ai_summary else ""}
    {f'<div class="tags">{tags_html}</div>' if tags_html else ""}
    {f'<p class="fitfor"><span class="k">こんな患者様に特に向いています：</span>{esc(best_patient)}</p>' if best_patient else ""}
  </div>"""

    # ── ② 近隣区での客観的な立ち位置 ──
    peer_html = ""
    peer = peer_stats(db, c) if db is not None else None
    if peer:
        cmp_text = ("平均より多い" if peer["my_reviews"] >= peer["avg_reviews"]
                    else "平均より少ない")
        peer_html = f"""
  <div class="peer">
    <p><span class="big">{esc(peer["ward"])}内 {peer["n_peers"]}院中 {peer["rank"]}位</span>
    （公開情報にもとづく分析スコア順）</p>
    <p>口コミ件数は{esc(peer["ward"])}内の平均{peer["avg_reviews"]}件に対し、貴院は{peer["my_reviews"]}件（{cmp_text}）です。
    これは技術力の優劣ではなく、あくまで<strong>公開情報として確認できた量</strong>の比較です。</p>
  </div>"""

    # ── ③ 情報を足すとどう伸びるか（ベネフィット表） ──
    check_rows = "".join(
        f'<tr class="{ "ok" if ok else "grow" }">'
        f'<td class="mark">{"✓" if ok else "＋"}</td>'
        f'<td>{esc(label)}</td>'
        f'<td class="benefit">{"掲載済みです" if ok else esc(benefit)}</td></tr>'
        for label, ok, benefit in checks
    )
    n_growable = total - ok_count

    if views is not None:
        stats_html = f"""
  <div class="stats">
    <div class="stat"><span class="v">{views:,}</span><span class="k">当サイトでの表示回数</span></div>
    <div class="stat"><span class="v">{clicks if clicks is not None else "—"}</span><span class="k">公式サイトへの移動</span></div>
    <div class="stat"><span class="v">{maps if maps is not None else "—"}</span><span class="k">地図の表示</span></div>
  </div>
  <p class="stats-note">※ {month_label}の{esc(CFG["site_name"])}内での数値（Googleアナリティクス計測）。</p>"""
    else:
        stats_html = """
  <p class="stats-note">※ 反響数値（表示回数・クリック数）は計測を開始したところです。データが貯まり次第、次回のレポートでお伝えします。</p>"""

    if n_growable > 0:
        proposal = f"""
  <h2>次に伸ばせるポイント</h2>
  <p>上表の「＋」は不足の指摘ではなく、<strong>情報を追加すればすぐに表示機会が増える伸びしろ</strong>です。
  情報のご提供・修正はすべて<strong>無料</strong>で承っています（下記窓口まで、電話やメールで教えていただくだけで反映します）。</p>
  <p>継続的に情報設計・口コミ・AI検索対策までサポートする「AI評判設計プラン」もございます。
  ご興味があれば、このレポートをきっかけに一度お話しさせてください。</p>"""
    else:
        proposal = """
  <h2>今後のご提案</h2>
  <p>貴院の公開情報はすでに充実しています。この状態を維持しつつ、口コミ・AI検索での見え方を
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
.head .free{{display:inline-block;margin-top:12px;background:rgba(255,255,255,.14);border-radius:999px;padding:5px 14px;font-size:.76rem;}}
h2{{font-size:1.02rem;color:#1d4f47;border-left:4px solid #dd7550;padding-left:10px;margin:36px 0 14px;}}
.showcase{{background:#fff;border:1px solid #e2e8e6;border-left:4px solid #1d4f47;border-radius:12px;padding:22px 24px;}}
.showcase .catch{{font-size:1.1rem;font-weight:700;color:#1d4f47;margin:0 0 10px;}}
.showcase .summary{{font-size:.9rem;margin:0 0 14px;}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;}}
.tag{{background:#eaf2ee;color:#1d4f47;font-size:.72rem;font-weight:700;border-radius:999px;padding:4px 12px;}}
.fitfor{{font-size:.84rem;margin:0;}}
.fitfor .k{{font-weight:700;color:#1d4f47;}}
.peer{{background:#fff8f4;border:1px solid #f0ddd0;border-radius:12px;padding:18px 22px;font-size:.88rem;}}
.peer .big{{font-size:1.3rem;font-weight:700;color:#c0602f;}}
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
tr.grow .mark{{color:#c0602f;}}
.benefit{{font-size:.76rem;color:#4a5a52;}}
tr.ok .benefit{{color:#8a9ba8;}}
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
    <h1>{esc(name)} 様　無料AI分析レポート</h1>
    <p class="sub">{month_label}版 ・ {esc(CFG["site_name"])}（{esc(CFG["domain"])}）</p>
    <span class="free">掲載料・作成費、すべて無料でお渡ししています</span>
  </div>

  <h2>貴院はこう見えています（AIによる無料分析）</h2>
  <p>{esc(CFG["city"])}内の歯科医院を公開情報（Googleの口コミ・公式サイト等）からAIが分析する
  「{esc(CFG["site_name"])}」に、貴院の分析結果はすでに掲載されています（最寄駅：{esc(station)}）。
  費用は一切いただいておらず、その分析結果を先にお届けします。</p>
  {showcase_html}

  {peer_html}

  <h2>次に伸ばせるポイント<span class="level">{ok_count}/{total}項目 掲載済み</span></h2>
  <p>下表は「不足の指摘」ではなく、<strong>情報を追加すればすぐに表示機会が増える伸びしろ</strong>の一覧です。</p>
  <table>{check_rows}</table>

  {proposal}
  {stats_html}

  <div class="cta">
    <p><strong>お問い合わせ・情報の修正窓口</strong></p>
    <p>メール：{esc(CFG["contact_email"])}（件名に【医院情報修正】または【AI評判設計プラン】とご記載ください）</p>
    <p>情報のご提供・修正はすべて無料です。公開情報が充実するほど、条件が一致する患者様に表示されやすくなります。</p>
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

    html_doc = build_report(c, db, args.views, args.clicks, args.maps)
    out.write_text(html_doc, encoding="utf-8")
    print(f"✅ レポート生成: {out}")


if __name__ == "__main__":
    main()
