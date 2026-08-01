# -*- coding: utf-8 -*-
"""
GA4 月次スナップショット → 時系列蓄積（資産化）＋ 営業資料HTML生成

「アナリティクスは資産になる」を実装するスクリプト。月1回実行すると：
  A. GA4 Data API から当ポータルの直近28日のリーチ指標（利用者数・新規・セッション・
     ページ表示・エンゲージメント・流入チャネル・上位ページ）を取得し、前28日と比較。
  B. その結果を `_reports/ga4_history.json` に日付つきで追記（＝時系列の資産。過去分は
     遡って作れないため、早く貯め始めるほど価値が上がる）。
  C. 蓄積データから「先に価値を見せる」営業資料HTML（`_reports/ga4_sales_material_<日付>.html`）を
     生成する。value-first構成：①先にポータルのリーチ実績→②成長トレンド→③掲載メリット→④窓口。

■ 認証（gsc_report.py と同じOAuth方式を流用。SA鍵は組織ポリシーで発行不可のため使わない）
  .env に以下を設定：
    GSC_OAUTH_CLIENT=/path/to/client_secret.json   ← gsc_report.py と同じデスクトップ型OAuthクライアントを再利用
    GA4_PROPERTY_IDS=123456789                      ← GA4管理→プロパティ設定の「数字ID」（プロパティIDであって
                                                       測定ID(G-XXXX)やストリームIDではない）。カンマ区切りで複数可。
                                                       先頭がこのサイトの主プロパティ（営業資料はこれで生成）。
    GA4_PROPERTY_LABELS=大阪歯科総研                 ← 任意。IDと同数・カンマ区切りのラベル（履歴の可読性用）。
  初回実行時のみブラウザが開き、Googleにログイン→アクセス許可を1回行うと
  `_reports/.ga4_token.json` に認可情報が保存され、以後は自動。
  ※事前にGCPプロジェクト（gsc_report.pyと同じ「My First Project」でよい）で
    「Google Analytics Data API」を有効化しておくこと。

■ 数値の捏造・ダミー生成は絶対禁止。APIに届かない場合はその旨を表示して静かに終了する。

手動実行：      python3 ga4_snapshot.py
中身だけ確認：  python3 ga4_snapshot.py --dry-run   （履歴追記・HTML生成をせず内容を表示）
"""
import html as _html
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS_DIR = ROOT / "_reports"
HISTORY_PATH = REPORTS_DIR / "ga4_history.json"
OAUTH_TOKEN_PATH = REPORTS_DIR / ".ga4_token.json"
OAUTH_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

WINDOW = 28          # 集計期間（日）
LAG_DAYS = 1         # 直近1日は未確定のため終端から除く
DRY_RUN = "--dry-run" in sys.argv

CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()

OAUTH_CLIENT = os.environ.get("GSC_OAUTH_CLIENT", "")
PROPERTY_IDS = [p.strip() for p in os.environ.get(
    "GA4_PROPERTY_IDS", os.environ.get("GA4_PROPERTY_ID", "")
).split(",") if p.strip()]
PROPERTY_LABELS = [s.strip() for s in os.environ.get("GA4_PROPERTY_LABELS", "").split(",") if s.strip()]

# ホスト名フィルタ：複数都市が1プロパティ内の別ストリームとして同居しているため
# （shika-soken枠=544644391に8都市が同居）、この都市のサブドメインだけに絞らないと
# 全都市を合算してしまう。site_config.json の domain を既定に使い（都市非依存）、
# GA4_HOST_FILTER で明示上書きも可能。www 有無の両方を許容する。空なら絞らない（＝従来の全体集計）。
_host = (os.environ.get("GA4_HOST_FILTER") or CFG.get("domain") or "").strip().replace("https://", "").replace("http://", "").strip("/")
HOST_FILTER = [h for h in ({_host, "www." + _host} if _host else set()) if h]

# 取得する指標（プロパティ横断で合算しない＝各プロパティ＝別サイトのため個別に扱う）
TOTAL_METRICS = [
    "totalUsers", "newUsers", "sessions", "engagedSessions",
    "screenPageViews", "averageSessionDuration", "engagementRate",
]


def esc(s) -> str:
    return _html.escape(str(s), quote=True)


def label_for(idx: int, property_id: str) -> str:
    if idx < len(PROPERTY_LABELS):
        return PROPERTY_LABELS[idx]
    if idx == 0:
        return CFG.get("site_name", property_id)
    return f"property {property_id}"


def make_client():
    """GA4 Data API クライアントを OAuth（ユーザー認可）で用意する。未設定・未導入なら
    案内メッセージを表示して None を返す（エラーで暴れない）。"""
    oauth_client_path = Path(OAUTH_CLIENT).expanduser() if OAUTH_CLIENT else None

    missing = []
    if not PROPERTY_IDS:
        missing.append("GA4_PROPERTY_IDS（GA4のプロパティ数字ID）")
    if not oauth_client_path or not oauth_client_path.exists():
        if OAUTH_CLIENT:
            missing.append(f"OAuthクライアントファイルが見つかりません: {OAUTH_CLIENT}")
        else:
            missing.append("GSC_OAUTH_CLIENT（gsc_report.pyと同じOAuthクライアント）")
    if missing:
        print("⏸ 未設定のためスキップ:", " ／ ".join(missing))
        print("   設定方法は ga4_snapshot.py 冒頭のコメント、または CLAUDE.md を参照")
        return None

    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    except ImportError as e:
        print(f"⏸ 必要なライブラリが未インストールです（{e.name}）。以下を実行してください：")
        print("   pip3 install google-analytics-data")
        return None
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials as UserCredentials
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        print(f"⏸ OAuth用ライブラリが未インストールです（{e.name}）。以下を実行してください：")
        print("   pip3 install google-auth-oauthlib")
        return None

    try:
        creds = None
        if OAUTH_TOKEN_PATH.exists():
            creds = UserCredentials.from_authorized_user_file(str(OAUTH_TOKEN_PATH), OAUTH_SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(oauth_client_path), OAUTH_SCOPES)
                print("🔐 ブラウザが開きます。Googleにログインしてアクセスを許可してください……")
                creds = flow.run_local_server(port=0)
            REPORTS_DIR.mkdir(exist_ok=True)
            OAUTH_TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        return BetaAnalyticsDataClient(credentials=creds)
    except Exception as e:
        print(f"❌ GA4 Data API への接続準備に失敗しました: {e}")
        return None


def _run(client, property_id, dims, mets, start, end, limit=25):
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric,
        Filter, FilterExpression,
    )
    # この都市のサブドメインだけに絞る（同居ストリームの合算を防ぐ）。
    dim_filter = None
    if HOST_FILTER:
        dim_filter = FilterExpression(
            filter=Filter(
                field_name="hostName",
                in_list_filter=Filter.InListFilter(values=HOST_FILTER),
            )
        )
    req = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start, end_date=end)],
        dimensions=[Dimension(name=d) for d in dims],
        metrics=[Metric(name=m) for m in mets],
        dimension_filter=dim_filter,
        limit=limit,
    )
    return client.run_report(req)


def fetch_totals(client, property_id, start, end) -> dict:
    res = _run(client, property_id, [], TOTAL_METRICS, start, end)
    out = {m: 0.0 for m in TOTAL_METRICS}
    for row in res.rows:  # dimensionなしなので最大1行
        for i, m in enumerate(TOTAL_METRICS):
            out[m] = float(row.metric_values[i].value or 0)
    # 整数指標は int に丸める
    for m in ("totalUsers", "newUsers", "sessions", "engagedSessions", "screenPageViews"):
        out[m] = int(round(out[m]))
    return out


def fetch_channels(client, property_id, start, end) -> dict:
    res = _run(client, property_id, ["sessionDefaultChannelGroup"], ["totalUsers"], start, end, limit=20)
    out = {}
    for row in res.rows:
        name = row.dimension_values[0].value or "(other)"
        out[name] = int(float(row.metric_values[0].value or 0))
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def fetch_top_pages(client, property_id, start, end, top_n=10):
    res = _run(client, property_id, ["pagePath"], ["screenPageViews"], start, end, limit=top_n)
    return [[row.dimension_values[0].value, int(float(row.metric_values[0].value or 0))]
            for row in res.rows]


# 成果（CV）として数えるイベント。表示回数ではなく「問い合わせにつながる行動」を追う。
# assets/odr-track.js・build_clinics.py・articles/shindan/shindan.js が送る名前と対応。
CV_EVENTS = [
    ("contact_submit",     "掲載相談フォームの送信"),
    ("contact_form_view",  "掲載相談フォームへの到達"),
    ("contact_nav",        "医院向け窓口ページへの遷移"),
    ("tel_click",          "電話リンクのタップ"),
    ("clinic_to_tel",      "医院ページからの電話"),
    ("mail_click",         "メールリンクのクリック"),
    ("clinic_to_official", "医院の公式サイトへ送客"),
    ("clinic_click",       "医院詳細を開いた"),
    ("official_click",     "ランキングから公式サイトへ"),
    ("shindan_start",      "診断に入った"),
    ("shindan_result",     "診断の結果が出た"),
]
CV_NAMES = [e for e, _ in CV_EVENTS]


def fetch_conversions(client, property_id, start, end) -> dict:
    """CVイベントの発生回数。未計測（0件）のイベントはGA4が行を返さないため0で補う。"""
    res = _run(client, property_id, ["eventName"], ["eventCount"], start, end, limit=200)
    got = {row.dimension_values[0].value: int(float(row.metric_values[0].value or 0))
           for row in res.rows}
    return {name: got.get(name, 0) for name in CV_NAMES}


def snapshot_property(client, property_id, cur, prev) -> dict:
    """1プロパティ分の当期・前期スナップショットを組み立てて返す。"""
    return {
        "period": {"start": cur[0], "end": cur[1], "window_days": WINDOW},
        "totals": fetch_totals(client, property_id, cur[0], cur[1]),
        "totals_prev": fetch_totals(client, property_id, prev[0], prev[1]),
        "channels": fetch_channels(client, property_id, cur[0], cur[1]),
        "top_pages": fetch_top_pages(client, property_id, cur[0], cur[1]),
        "conversions": fetch_conversions(client, property_id, cur[0], cur[1]),
        "conversions_prev": fetch_conversions(client, property_id, prev[0], prev[1]),
    }


def load_history() -> dict:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"properties": {}}


def append_history(hist: dict, property_id: str, label: str, snap_date: str, snap: dict):
    """時系列に追記。同一プロパティ×同一日付は上書き（冪等）。"""
    props = hist.setdefault("properties", {})
    entry = props.setdefault(property_id, {"label": label, "snapshots": []})
    entry["label"] = label
    entry["snapshots"] = [s for s in entry["snapshots"] if s.get("date") != snap_date]
    entry["snapshots"].append({
        "date": snap_date,
        "period": snap["period"],
        "totals": snap["totals"],
        "totals_prev": snap["totals_prev"],
        "channels": snap["channels"],
        "top_pages": snap["top_pages"],
        "conversions": snap.get("conversions", {}),
        "conversions_prev": snap.get("conversions_prev", {}),
    })
    entry["snapshots"].sort(key=lambda s: s["date"])


def growth_pct(cur: int, prev: int):
    if prev <= 0:
        return None
    return (cur - prev) / prev * 100.0


def fmt_duration(sec: float) -> str:
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    return f"{m}分{s:02d}秒" if m else f"{s}秒"


def build_sales_material_html(label: str, snap: dict, history_points) -> str:
    """value-first の営業資料。実データのみ描画（捏造なし・欠損は非表示）。"""
    t, p = snap["totals"], snap["totals_prev"]
    per = snap["period"]
    site = CFG.get("site_name", "")
    domain = CFG.get("domain", "")
    contact = CFG.get("contact_email", "")

    def kpi(labeltxt, cur, prev, is_int=True):
        g = growth_pct(cur, prev)
        trend = ""
        if g is not None:
            arrow = "▲" if g > 0 else ("▼" if g < 0 else "－")
            color = "#1f7a4d" if g > 0 else ("#a33" if g < 0 else "#666")
            trend = f'<div style="font-size:12px;color:{color};margin-top:2px">前期比 {arrow}{abs(g):.0f}%</div>'
        val = f"{int(cur):,}" if is_int else f"{cur}"
        return (f'<div style="flex:1 1 130px;background:#fff;border:1px solid #e6e0d6;border-radius:10px;'
                f'padding:14px 16px;text-align:center">'
                f'<div style="font-size:12px;color:#6b6152;letter-spacing:.04em">{esc(labeltxt)}</div>'
                f'<div style="font-size:26px;font-weight:700;color:#1f4b3f;margin-top:4px">{val}</div>{trend}</div>')

    kpis = "".join([
        kpi("利用者数（28日）", t["totalUsers"], p["totalUsers"]),
        kpi("新規利用者", t["newUsers"], p["newUsers"]),
        kpi("セッション", t["sessions"], p["sessions"]),
        kpi("ページ表示", t["screenPageViews"], p["screenPageViews"]),
    ])

    # 成長トレンド（履歴が2点以上あるときだけ・棒グラフ）
    trend_block = ""
    pts = [(d, v) for d, v in history_points if v is not None]
    if len(pts) >= 2:
        mx = max(v for _, v in pts) or 1
        bars = ""
        for d, v in pts[-8:]:
            h = max(4, int(v / mx * 90))
            bars += (f'<div style="flex:1;display:flex;flex-direction:column;justify-content:flex-end;'
                     f'align-items:center;gap:4px">'
                     f'<div style="font-size:11px;color:#1f4b3f;font-weight:600">{v:,}</div>'
                     f'<div style="width:70%;height:{h}px;background:#2e6b52;border-radius:4px 4px 0 0"></div>'
                     f'<div style="font-size:10px;color:#8a8172">{esc(d[5:])}</div></div>')
        first, last = pts[0][1], pts[-1][1]
        g = growth_pct(last, first)
        head = (f'この{len(pts)}回の記録で利用者数は <b>{first:,} → {last:,}</b>'
                + (f'（<b>{"+" if g and g>=0 else ""}{g:.0f}%</b>）' if g is not None else "") + " と推移しています。")
        trend_block = (
            f'<h2 style="font-size:16px;color:#1f4b3f;margin:26px 0 8px">成長トレンド</h2>'
            f'<p style="font-size:13px;color:#555;margin:0 0 10px">{head}</p>'
            f'<div style="display:flex;align-items:flex-end;gap:8px;height:130px;'
            f'background:#faf7f1;border:1px solid #eee6d9;border-radius:10px;padding:12px 14px">{bars}</div>')

    # 流入チャネル
    ch = snap["channels"]
    ch_rows = "".join(
        f'<tr><td style="padding:5px 10px;border-bottom:1px solid #f0ece3">{esc(k)}</td>'
        f'<td style="padding:5px 10px;border-bottom:1px solid #f0ece3;text-align:right">{v:,}</td></tr>'
        for k, v in list(ch.items())[:6]
    )
    ch_block = (
        f'<h2 style="font-size:16px;color:#1f4b3f;margin:26px 0 8px">利用者はどこから来ているか</h2>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px">'
        f'<tr><th style="text-align:left;padding:5px 10px;color:#6b6152">チャネル</th>'
        f'<th style="text-align:right;padding:5px 10px;color:#6b6152">利用者数</th></tr>{ch_rows}</table>'
    ) if ch else ""

    # 成果（CV）：ページ表示ではなく「問い合わせにつながった行動」。前期比つき。
    cv = snap.get("conversions") or {}
    cvp = snap.get("conversions_prev") or {}
    cv_rows = "".join(
        f'<tr><td style="padding:5px 10px;border-bottom:1px solid #f0ece3">{esc(ja)}</td>'
        f'<td style="padding:5px 10px;border-bottom:1px solid #f0ece3;text-align:right">{cv.get(name,0):,}</td>'
        f'<td style="padding:5px 10px;border-bottom:1px solid #f0ece3;text-align:right;color:#8a8172">'
        f'{("前期 " + format(cvp.get(name,0), ",")) if cvp else "—"}</td></tr>'
        for name, ja in CV_EVENTS if cv.get(name, 0) or cvp.get(name, 0)
    )
    cv_block = (
        f'<h2 style="font-size:16px;color:#1f4b3f;margin:26px 0 8px">問い合わせにつながった行動</h2>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px">'
        f'<tr><th style="text-align:left;padding:5px 10px;color:#6b6152">行動</th>'
        f'<th style="text-align:right;padding:5px 10px;color:#6b6152">今期</th>'
        f'<th style="text-align:right;padding:5px 10px;color:#6b6152">比較</th></tr>{cv_rows}</table>'
        f'<p style="font-size:11px;color:#8a8172;margin:6px 0 0">'
        f'※ 電話・公式サイト・地図への遷移はサイト内で観測できる範囲の数値です。'
        f'遷移後に実際の来院・予約に至ったかまでは計測していません。</p>'
    ) if cv_rows else ""

    eng = t["engagementRate"] * 100 if t["engagementRate"] <= 1 else t["engagementRate"]
    dur = fmt_duration(t["averageSessionDuration"])

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(site)}｜月次リーチ・レポート（サンプル）</title>
<style>body{{margin:0;font-family:'Zen Kaku Gothic New','Hiragino Sans',sans-serif;color:#222;background:#f3efe7}}
.wrap{{max-width:720px;margin:0 auto;padding:28px 20px}}.card{{background:#fdfbf7;border:1px solid #e6e0d6;border-radius:16px;padding:26px 26px}}</style>
</head><body><div class="wrap"><div class="card">
<div style="font-size:12px;letter-spacing:.14em;color:#8a8172">MONTHLY REACH REPORT</div>
<h1 style="font-size:22px;color:#1f4b3f;margin:6px 0 4px">{esc(site)}の掲載リーチ状況</h1>
<div style="font-size:12px;color:#8a8172;margin-bottom:18px">集計期間：{esc(per['start'])} 〜 {esc(per['end'])}（直近{per['window_days']}日）／出典：Google Analytics 4</div>

<p style="font-size:14px;line-height:1.9;color:#444;margin:0 0 16px">
{esc(site)}（<a href="https://{esc(domain)}" style="color:#1f4b3f">{esc(domain)}</a>）は、公開情報とAIで地域の歯科医院を分析・紹介する無料ポータルです。
直近{per['window_days']}日で、以下の患者・生活者にご利用いただきました。<b>貴院ページはこの母集団の中に露出しています。</b></p>

<div style="display:flex;flex-wrap:wrap;gap:10px">{kpis}</div>
<p style="font-size:12px;color:#777;margin:10px 0 0">平均滞在 {esc(dur)} ／ エンゲージメント率 {eng:.0f}%</p>

{trend_block}
{ch_block}
{cv_block}

<h2 style="font-size:16px;color:#1f4b3f;margin:26px 0 8px">掲載を活かすには</h2>
<p style="font-size:14px;line-height:1.9;color:#444;margin:0 0 8px">
掲載は無料です。貴院ページの公開情報（診療時間・設備・診療方針など）を充実させると、
この利用者が条件で絞り込んだときに貴院が該当・表示されやすくなり、上記のリーチをより取り込めます。
より詳しい貴院単位の反響レポート（何回表示され、公式サイトへ何回移動したか）も無料でお送りできます。</p>

<div style="background:#f4f0e8;border-radius:10px;padding:14px 16px;margin-top:14px;font-size:13px;color:#555">
お問い合わせ・掲載情報の無料修正：<b>{esc(contact)}</b><br>
※掲載順は公開情報にもとづき自動で決まり、金銭による変更はできません。
</div>
<div style="font-size:11px;color:#9a9182;margin-top:16px">このレポートは実測データから自動生成したサンプルです。数値は集計期間のGA4実測値です。</div>
</div></div></body></html>"""


def main():
    client = make_client()
    if client is None:
        return

    end = date.today() - timedelta(days=LAG_DAYS)
    start = end - timedelta(days=WINDOW - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=WINDOW - 1)
    cur = (start.isoformat(), end.isoformat())
    prev = (prev_start.isoformat(), prev_end.isoformat())
    snap_date = date.today().isoformat()

    hist = load_history()
    primary_snap = None
    primary_label = None

    for idx, pid in enumerate(PROPERTY_IDS):
        label = label_for(idx, pid)
        try:
            snap = snapshot_property(client, pid, cur, prev)
        except Exception as e:
            print(f"  ⚠️ プロパティ {pid}（{label}）の取得に失敗（他は続行）: {e}")
            continue
        t = snap["totals"]
        print(f"■ {label}（property {pid}）  {cur[0]}〜{cur[1]}")
        print(f"   利用者{t['totalUsers']:,} / 新規{t['newUsers']:,} / セッション{t['sessions']:,} / "
              f"ページ表示{t['screenPageViews']:,}")
        g = growth_pct(t["totalUsers"], snap["totals_prev"]["totalUsers"])
        if g is not None:
            print(f"   前期比（利用者）：{'+' if g>=0 else ''}{g:.0f}%")
        if not DRY_RUN:
            append_history(hist, pid, label, snap_date, snap)
        if idx == 0:
            primary_snap, primary_label = snap, label

    if primary_snap is None:
        print("⏸ 取得できたプロパティがありませんでした（設定またはAPI権限を確認してください）")
        return

    if DRY_RUN:
        print("\n[dry-run] 履歴追記・HTML生成はスキップしました")
        return

    REPORTS_DIR.mkdir(exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 時系列に追記: {HISTORY_PATH}")

    # 主プロパティの履歴から利用者数の推移を渡して営業資料を生成
    primary_id = PROPERTY_IDS[0]
    points = [(s["date"], s["totals"].get("totalUsers"))
              for s in hist["properties"][primary_id]["snapshots"]]
    material = build_sales_material_html(primary_label, primary_snap, points)
    out = REPORTS_DIR / f"ga4_sales_material_{snap_date}.html"
    out.write_text(material, encoding="utf-8")
    print(f"✅ 営業資料を生成: {out}")


if __name__ == "__main__":
    main()
