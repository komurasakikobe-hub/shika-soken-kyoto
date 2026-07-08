# -*- coding: utf-8 -*-
"""
医院向け「反響レポート」生成スクリプト（営業用・無料配布の入口商品）

設計思想（2026-07-09 v3）：
  商品は「情報の充実」ではなく「院長の時間」。オーナーが欲しいのは
  ①すぐ分かる結果 ②手間ゼロ ③かゆくて手が届かない仕事（採用・教育・口コミ返信など）を
  どれだけ肩代わりしてもらえるか。レポートの主役は
  「面倒だった仕事を、どれだけ短縮できるか」の提案に置く。

  さらに v3 で直した構造的な欠陥：
  - 【データのライブ検証】DBの口コミ件数が古いまま営業レポートに載る事故があった
    （たまい歯科：DB 71件 ↔ Google実際 20件。ユーザー指摘で発覚）。
    生成時に Places API から評価・口コミ件数をその場で再取得し、取得日付きで表記する。
    取得できない場合は掲載を見送る（古い数字は絶対に出さない）。
  - 【8/8問題】全項目掲載済みの医院に「伸ばせるポイント 8/8 掲載済み」の表を
    見せると"伸びしろゼロ"にしか見えない。全項目済みの場合は表自体を出さず、
    体制維持＋業務代行の提案に切り替える。
  - 【定型文バレ】毎回同じ言い回しだと自動生成と分かる。文面のキー文を複数パターン
    用意し、医院名のハッシュで安定的に出し分ける（同じ医院には常に同じ文面＝
    再送しても矛盾しない。医院が違えば文面が変わる）。

使い方：
  python3 clinic_report.py "医院名"                       # 反響数値なし版
  python3 clinic_report.py "医院名" --views 32 --clicks 3  # GA4の数値を渡す版

出力：_reports/反響レポート_<医院名>_<年月>.html
※ 医院名は部分一致で検索する。複数ヒット時は候補を表示して終了。
"""
import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "_reports"


def _load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()
GMAPS_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

# 「情報を足すとこの条件で拾われる」ベネフィット文言（患者の条件タブと対応）
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

# ── 院長業務の代行メニュー（時間削減の提案。fitで医院の状況に合うものを優先表示） ──
DELEGATION_MENU = [
    {
        "key": "review_reply",
        "title": "Google口コミへの返信文の下書き",
        "desc": "新しい口コミを毎週こちらで確認し、そのまま使える返信文をお渡しします。返信が続いている医院は、口コミを書く患者様も増えやすくなります。",
        "fit": lambda c, live: (live.get("total_reviews") or c.get("total_reviews") or 0) >= 5,
    },
    {
        "key": "recruit",
        "title": "求人原稿・採用ページの文章作成",
        "desc": "歯科衛生士・受付スタッフの募集文を、貴院の雰囲気が伝わる形でこちらが書きます。媒体ごとの出し分けもご相談いただけます。",
        "fit": lambda c, live: True,
    },
    {
        "key": "training",
        "title": "新人スタッフ向けの受付・電話対応マニュアル作成",
        "desc": "教育に割く時間がとれない院長に代わり、貴院のルールに合わせた受付・電話・キャンセル対応の手順書を作成します。",
        "fit": lambda c, live: True,
    },
    {
        "key": "blog",
        "title": "ブログ・お知らせ記事の代筆",
        "desc": "「書かなきゃと思いながら止まっている」ブログやお知らせを、月数本こちらで下書きします。院長は確認するだけです。",
        "fit": lambda c, live: bool(c.get("url")),
    },
    {
        "key": "webcopy",
        "title": "ホームページの文言・情報の改善案づくり",
        "desc": "患者様がどんな条件で医院を探しているかのデータをもとに、載せると効く情報・直すと伝わる文章を具体案でお渡しします。",
        "fit": lambda c, live: True,
    },
    {
        "key": "report",
        "title": "反響データの月次レポート",
        "desc": "当サイト経由の閲覧・公式サイトへの移動数を毎月自動でお届けします。院長が集計する手間はありません。",
        "fit": lambda c, live: True,
    },
]


def find_clinic(db: dict, query: str):
    hits = [c for c in db.values()
            if not c.get("q_excluded") and c.get("name") and query in c["name"]]
    return hits


def esc(s):
    import html
    return html.escape(str(s), quote=True)


def _variant(name: str, salt: str, options: list) -> str:
    """医院名＋用途ごとに安定して文面パターンを出し分ける。
    同じ医院には常に同じ文面（再送で矛盾しない）、医院が違えば別の文面。"""
    h = int(hashlib.md5((name + salt).encode("utf-8")).hexdigest(), 16)
    return options[h % len(options)]


def fetch_live_google(place_id: str):
    """Places APIから評価・口コミ件数をその場で取得する。
    営業レポートに古い数字を載せないための必須ステップ（2026-07-09導入）。
    取得失敗時はNoneを返し、呼び出し側は口コミ数値の掲載自体を見送る。"""
    if not GMAPS_KEY or not place_id or not place_id.startswith("ChIJ"):
        return None
    url = ("https://maps.googleapis.com/maps/api/place/details/json"
           f"?place_id={urllib.parse.quote(place_id)}"
           "&fields=rating,user_ratings_total&language=ja&key=" + GMAPS_KEY)
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        if data.get("status") != "OK":
            return None
        res = data.get("result", {})
        if res.get("user_ratings_total") is None:
            return None
        return {
            "rating": res.get("rating"),
            "total_reviews": res.get("user_ratings_total"),
            "fetched": date.today().isoformat(),
        }
    except Exception:
        return None


def ward_of(addr):
    """近隣比較のグルーピング単位を返す。
    区がある都市：「○○市△△区」。区がない都市・複数市町ブロックでは
    site_config.jsonのareasの市町名、それも無ければ市全体を1グループとする。"""
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
    """同じ区（または市町）の他院と比べた客観的な立ち位置。"""
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
    return {"ward": w, "n_peers": len(peers), "rank": rank}


def build_report(c, db=None, views=None, clicks=None, maps=None):
    today = date.today()
    month_label = f"{today.year}年{today.month}月"
    name = c.get("name", "")

    # ── データのライブ検証（古い口コミ数を絶対に載せない） ──
    live = fetch_live_google(c.get("place_id", "")) or {}
    live_ok = live.get("total_reviews") is not None
    if live_ok:
        # DBにも反映しておく（次回以降の分析も正しい数字を使う）
        c["rating"] = live["rating"]
        c["total_reviews"] = live["total_reviews"]

    checks = []
    ok_count = 0
    for label, pred, benefit in GROWTH_ITEMS:
        ok = bool(pred(c))
        ok_count += ok
        checks.append((label, ok, benefit))
    total = len(GROWTH_ITEMS)
    n_growable = total - ok_count

    ns = c.get("nearest_station") or {}
    station = f"{ns.get('name','')}駅 徒歩圏" if ns else "—"

    # ── ① 無料で既に作成済みの分析（先に価値を見せる。導入文はパターン出し分け） ──
    catchphrase = c.get("catchphrase") or ""
    ai_summary = c.get("ai_summary") or ""
    tags = c.get("reputation_tags") or []
    best_patient = c.get("best_patient_profile") or ""
    tags_html = "".join(f'<span class="tag">{esc(t)}</span>' for t in tags[:5])

    intro = _variant(name, "intro", [
        f"{esc(CFG['city'])}の歯科医院を公開情報からAIが分析する「{esc(CFG['site_name'])}」に、貴院の分析結果はすでに掲載されています（最寄駅：{esc(station)}）。費用は一切いただいておらず、その結果を先にお届けします。",
        f"「{esc(CFG['site_name'])}」は、{esc(CFG['city'])}の歯科医院をGoogleの口コミや公式サイト等の公開情報から分析している研究サイトです。貴院の分析はすでに完了しており（最寄駅：{esc(station)}）、掲載・分析とも無料です。まずその中身をご覧ください。",
        f"貴院の公開情報（口コミ・公式サイト等）をAIで分析した結果を、先にお渡しします。「{esc(CFG['site_name'])}」への掲載・分析はすべて無料で、貴院側の作業は一切発生していません（最寄駅：{esc(station)}）。",
    ])

    showcase_html = ""
    if catchphrase or ai_summary:
        showcase_html = f"""
  <div class="showcase">
    {f'<p class="catch">「{esc(catchphrase)}」</p>' if catchphrase else ""}
    {f'<p class="summary">{esc(ai_summary)}</p>' if ai_summary else ""}
    {f'<div class="tags">{tags_html}</div>' if tags_html else ""}
    {f'<p class="fitfor"><span class="k">こんな患者様に特に向いています：</span>{esc(best_patient)}</p>' if best_patient else ""}
  </div>"""

    # ── ② 立ち位置（口コミ数値はライブ検証済みのときだけ、取得日付きで載せる） ──
    peer_html = ""
    peer = peer_stats(db, c) if db is not None else None
    if peer:
        review_line = ""
        if live_ok:
            review_line = (f"<p>Googleマップ上の貴院の評価は<strong>★{live['rating']}・口コミ{live['total_reviews']}件</strong>"
                           f"（{today.month}月{today.day}日にこちらで確認した時点の数字です）。</p>")
        peer_html = f"""
  <div class="peer">
    <p><span class="big">{esc(peer["ward"])}内 {peer["n_peers"]}院中 {peer["rank"]}位</span>
    （公開情報にもとづく分析スコア順）</p>
    {review_line}
    <p class="peer-note">順位は公開情報の充実度と評判分析によるもので、技術力の優劣を示すものではありません。</p>
  </div>"""

    # ── ③ 伸びしろ or 仕上がっている宣言（全項目済みのときチェック表は出さない） ──
    if n_growable > 0:
        grow_intro = _variant(name, "grow", [
            "下表は「不足の指摘」ではなく、<strong>情報を追加すればすぐに表示機会が増える伸びしろ</strong>の一覧です。",
            "以下は、貴院がまだ取りこぼしている<strong>検索条件との接点</strong>です。情報をいただければ、反映はこちらで行います。",
            "あと少しの情報で、いま貴院が表示されていない検索条件にも載るようになります。<strong>追加作業はすべてこちらで代行します。</strong>",
        ])
        check_rows = "".join(
            f'<tr class="{ "ok" if ok else "grow" }">'
            f'<td class="mark">{"✓" if ok else "＋"}</td>'
            f'<td>{esc(label)}</td>'
            f'<td class="benefit">{"掲載済みです" if ok else esc(benefit)}</td></tr>'
            for label, ok, benefit in checks
        )
        growth_html = f"""
  <h2>次に伸ばせるポイント<span class="level">{ok_count}/{total}項目 掲載済み</span></h2>
  <p>{grow_intro}</p>
  <table>{check_rows}</table>"""
    else:
        done_line = _variant(name, "done", [
            "貴院の情報発信は、当サイトの分析項目すべてで確認が取れており、この地域では最上位の仕上がりです。ここから先は「情報を増やす」より、<strong>院長の手を空ける</strong>フェーズだと考えています。",
            "分析項目はすべて掲載済みで、情報発信としてはこの地域でも数少ない完成度です。次にご提案したいのは、情報ではなく<strong>院長の時間</strong>を増やすことです。",
        ])
        growth_html = f"""
  <h2>情報発信の現在地</h2>
  <p>{done_line}</p>"""

    # ── ④ 院長業務の代行提案（このレポートの主役。医院の状況に合うものを優先） ──
    fitting = [m for m in DELEGATION_MENU if m["fit"](c, live)]
    rot = int(hashlib.md5(name.encode()).hexdigest(), 16) % max(len(fitting), 1)
    fitting = fitting[rot:] + fitting[:rot]
    menu_items = fitting[:4]
    menu_html = "".join(
        f'<div class="dlg-item"><p class="dlg-t">{esc(m["title"])}</p><p class="dlg-d">{esc(m["desc"])}</p></div>'
        for m in menu_items
    )
    dlg_intro = _variant(name, "dlg", [
        "診療の合間にやらざるを得なかった仕事を、こちらに移せます。院長は本業の治療に集中してください。",
        "「やらなきゃと思いながら後回しになっている仕事」を、こちらが巻き取ります。いずれも院長は最後に確認するだけの形にします。",
        "採用・教育・情報発信——診療以外の仕事に時間を取られていませんか。以下は、こちらで肩代わりできる業務の例です。",
    ])
    delegation_html = f"""
  <h2>院長がやらなくていいことを、増やしませんか</h2>
  <p>{dlg_intro}</p>
  <div class="dlg-grid">{menu_html}</div>
  <p class="dlg-note">上記は「AI評判設計プラン」でお引き受けしている業務の一部です。単発のご相談も歓迎です。</p>"""

    # ── 反響数値 ──
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

    live_note = ("Googleの評価・口コミ件数は本レポート作成日にPlaces APIで取得した時点値です。"
                 if live_ok else
                 "Googleの評価・口コミ件数は作成時点で再取得できなかったため、本レポートには掲載していません。")

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>無料AI分析レポート｜{esc(name)}｜{esc(CFG["site_name"])}</title>
<style>
body{{margin:0;font-family:'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif;background:#f4f7f6;color:#1c2b25;line-height:1.9;}}
.wrap{{max-width:720px;margin:0 auto;padding:40px 24px 64px;}}
.head{{background:#1f4b3f;color:#fff;border-radius:14px;padding:28px 32px;margin-bottom:28px;}}
.head .brand{{font-size:.72rem;letter-spacing:.18em;color:rgba(255,255,255,.6);margin:0 0 10px;}}
.head h1{{font-size:1.25rem;margin:0 0 6px;}}
.head .sub{{font-size:.82rem;color:rgba(255,255,255,.75);margin:0;}}
.head .free{{display:inline-block;margin-top:12px;background:rgba(255,255,255,.14);border-radius:999px;padding:5px 14px;font-size:.76rem;}}
h2{{font-size:1.02rem;color:#1f4b3f;border-left:4px solid #dd7550;padding-left:10px;margin:36px 0 14px;}}
.showcase{{background:#fff;border:1px solid #e2e8e6;border-left:4px solid #1f4b3f;border-radius:12px;padding:22px 24px;}}
.showcase .catch{{font-size:1.1rem;font-weight:700;color:#1f4b3f;margin:0 0 10px;}}
.showcase .summary{{font-size:.9rem;margin:0 0 14px;}}
.tags{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:12px;}}
.tag{{background:#eaf2ee;color:#1f4b3f;font-size:.72rem;font-weight:700;border-radius:999px;padding:4px 12px;}}
.fitfor{{font-size:.84rem;margin:0;}}
.fitfor .k{{font-weight:700;color:#1f4b3f;}}
.peer{{background:#fff8f4;border:1px solid #f0ddd0;border-radius:12px;padding:18px 22px;font-size:.88rem;margin-top:16px;}}
.peer .big{{font-size:1.3rem;font-weight:700;color:#c0602f;}}
.peer-note{{font-size:.74rem;color:#8a9ba8;margin-bottom:0;}}
.stats{{display:flex;gap:12px;margin:16px 0 8px;}}
.stat{{flex:1;background:#fff;border:1px solid #e2e8e6;border-radius:12px;padding:16px;text-align:center;}}
.stat .v{{display:block;font-size:1.6rem;font-weight:700;color:#1f4b3f;}}
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
.level{{display:inline-block;background:#e8f4f0;color:#1f4b3f;font-weight:700;border-radius:999px;padding:4px 16px;font-size:.84rem;margin-left:8px;}}
.dlg-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
@media(max-width:560px){{.dlg-grid{{grid-template-columns:1fr;}}}}
.dlg-item{{background:#fff;border:1px solid #e2e8e6;border-radius:12px;padding:16px 18px;}}
.dlg-t{{font-weight:700;color:#1f4b3f;font-size:.88rem;margin:0 0 6px;}}
.dlg-d{{font-size:.78rem;color:#4a5a52;margin:0;}}
.dlg-note{{font-size:.76rem;color:#8a9ba8;}}
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
  <p>{intro}</p>
  {showcase_html}
  {peer_html}

  {growth_html}

  {delegation_html}
  {stats_html}

  <div class="cta">
    <p><strong>お問い合わせ・情報の修正窓口</strong></p>
    <p>メール：{esc(CFG["contact_email"])}（件名に【医院情報修正】または【AI評判設計プラン】とご記載ください）</p>
    <p>情報のご提供・修正、上記業務のご相談はすべてこの窓口で承ります。</p>
  </div>

  <p class="foot">本レポートは{esc(CFG["site_name"])}が公開情報（Google口コミ・公式サイト等）をもとに独自に作成した参考資料です。
  医院の技術や治療結果の優劣を評価するものではありません。掲載内容に誤りがある場合は上記窓口までご連絡ください。
  {live_note}</p>
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

    # ライブ検証でDB側の評価・口コミ数も更新されたため保存する
    (ROOT / "clinic_db.json").write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ レポート生成: {out}")


if __name__ == "__main__":
    main()
