# -*- coding: utf-8 -*-
"""
週次営業レポート自動送信 — 「今週、誰に営業すべきか」をメールで受け取る仕組み

毎週月曜8:30にlaunchd（com.kyotoshikasoken.salesreport）から実行され：
  ① GA4からこの7日間の医院別反響（表示・公式サイトクリック・地図・比較追加）を取得
  ② 前週と比較して「反応が伸びている医院」「送客が発生した医院」を検出
  ③ 営業優先度順に並べ、そのまま送れる営業メール文面（実数入り）を生成
  ④ 対象医院の反響レポートHTML（clinic_report.py）を添付
  ⑤ komurasaki.kobe@gmail.com へ自動送信

必要な事前設定（.envに追記。詳細はCLAUDE.md「週次営業レポート」参照）：
  GA4_PROPERTY_IDS=123456789,987654321 ← GA4管理画面のプロパティID（数字・カンマ区切りで複数可）
                                          2026-07-11〜：shika-soken/kokedama両アカウントの
                                          プロパティIDを両方書く（片方の無料枠切れに備えた冗長化）。
                                          サービスアカウントを両アカウントのプロパティに
                                          閲覧者として追加しておくこと。旧GA4_PROPERTY_ID（単数）にも後方互換
  GA4_SA_KEY=/path/to/service-account.json ← GCPサービスアカウントの鍵ファイル
  GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx  ← Gmailアプリパスワード（2段階認証必須）
  MAIL_FROM=komurasaki.kobe@gmail.com
  MAIL_TO=komurasaki.kobe@gmail.com

依存ライブラリ： pip3 install google-analytics-data
設定が未完了の間は、その旨をログに出して静かに終了する（エラーで暴れない）。

手動テスト： python3 weekly_sales_report.py --dry-run   （メール送信せず内容を表示）
"""
import json
import os
import smtplib
import ssl
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
DRY_RUN = "--dry-run" in sys.argv

# .env読み込み（簡易）
def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

load_env()

GA4_PROPERTY_IDS = [p.strip() for p in os.environ.get(
    "GA4_PROPERTY_IDS", os.environ.get("GA4_PROPERTY_ID", "")
).split(",") if p.strip()]
GA4_SA_KEY = os.environ.get("GA4_SA_KEY", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
MAIL_FROM = os.environ.get("MAIL_FROM", CFG.get("contact_email", ""))
MAIL_TO = os.environ.get("MAIL_TO", CFG.get("contact_email", ""))


def fetch_ga4_clinic_events(days_back_start: int, days_back_end: int):
    """GA4から医院別イベント数を取得。GA4_PROPERTY_IDS内の全プロパティ（shika-soken/kokedama
    両アカウント分）を横断集計し、{clinic_name: {event: count}} にマージして返す。"""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric, FilterExpression,
        Filter, FilterExpressionList,
    )
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GA4_SA_KEY
    client = BetaAnalyticsDataClient()

    out = {}
    for property_id in GA4_PROPERTY_IDS:
        req = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(
                start_date=f"{days_back_start}daysAgo",
                end_date=f"{days_back_end}daysAgo",
            )],
            dimensions=[Dimension(name="eventName"), Dimension(name="customEvent:clinic_name")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(
                or_group=FilterExpressionList(expressions=[
                    FilterExpression(filter=Filter(
                        field_name="eventName",
                        string_filter=Filter.StringFilter(value=v),
                    )) for v in ["clinic_click", "official_click", "map_click", "compare_add"]
                ])
            ),
            limit=10000,
        )
        try:
            res = client.run_report(req)
        except Exception as e:
            print(f"  ⚠️ GA4プロパティ {property_id} の取得に失敗（他プロパティは続行）: {e}")
            continue
        for row in res.rows:
            event = row.dimension_values[0].value
            clinic = row.dimension_values[1].value
            count = int(row.metric_values[0].value)
            if not clinic or clinic == "(not set)":
                continue
            out.setdefault(clinic, {})[event] = out.setdefault(clinic, {}).get(event, 0) + count
    return out


def fetch_filter_trends():
    """今週よく押されたフィルター（filter_select）上位を取得。GA4_PROPERTY_IDS内の
    全プロパティを横断集計してマージする。"""
    from google.analytics.data_v1beta import BetaAnalyticsDataClient
    from google.analytics.data_v1beta.types import (
        RunReportRequest, DateRange, Dimension, Metric, FilterExpression, Filter,
    )
    client = BetaAnalyticsDataClient()
    totals = {}
    for property_id in GA4_PROPERTY_IDS:
        req = RunReportRequest(
            property=f"properties/{property_id}",
            date_ranges=[DateRange(start_date="7daysAgo", end_date="1daysAgo")],
            dimensions=[Dimension(name="customEvent:filter_value")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(filter=Filter(
                field_name="eventName",
                string_filter=Filter.StringFilter(value="filter_select"),
            )),
            limit=15,
        )
        try:
            res = client.run_report(req)
        except Exception as e:
            print(f"  ⚠️ GA4プロパティ {property_id} の取得に失敗（他プロパティは続行）: {e}")
            continue
        for r in res.rows:
            v = r.dimension_values[0].value
            if v in ("", "(not set)"):
                continue
            totals[v] = totals.get(v, 0) + int(r.metric_values[0].value)
    return sorted(totals.items(), key=lambda kv: -kv[1])[:15]


def build_sales_email_draft(clinic_name: str, stats: dict, trend_note: str) -> str:
    """医院にそのまま送れる営業メールの下書きを生成（実数入り・テンプレート方式）。"""
    clicks = stats.get("official_click", 0)
    views = stats.get("clinic_click", 0)
    maps_ = stats.get("map_click", 0)
    site = CFG["site_name"]
    domain = CFG["domain"]
    return f"""件名：【{site}】{clinic_name}様の掲載ページに関するご報告（無料レポート）

{clinic_name}
ご担当者様

突然のご連絡失礼いたします。
{CFG["city"]}内の歯科医院を公開情報とAIで分析・紹介しているポータルサイト
「{site}」（https://{domain}）を運営しております、運営担当と申します。

当サイトには貴院のページを掲載しており（掲載は無料です）、
直近1週間で以下の反響がございましたのでご報告いたします。

・貴院ページの閲覧　　　：{views}回
・貴院公式サイトへの移動：{clicks}回
・地図の表示　　　　　　：{maps_}回
{trend_note}
より詳しい分析レポート（貴院がどんな条件で検索・表示されているか、
公開情報の充実度診断）を無料でお送りできます。
ご希望の場合は、本メールにご返信ください。

※掲載内容に誤りがある場合の修正も無料で承ります。
※順位・掲載順は公開情報にもとづき自動で決まるため、金銭による変更はできません。

{site} 運営
{MAIL_FROM}
"""


def main():
    today = date.today()

    # ── 設定チェック（未設定なら静かに終了） ──
    missing = []
    if not GA4_PROPERTY_ID: missing.append("GA4_PROPERTY_ID")
    if not GA4_SA_KEY or not Path(GA4_SA_KEY).exists(): missing.append("GA4_SA_KEY")
    if not GMAIL_APP_PASSWORD and not DRY_RUN: missing.append("GMAIL_APP_PASSWORD")
    if missing:
        print(f"⏸ 未設定のため送信をスキップ: {', '.join(missing)}")
        print("   設定方法は CLAUDE.md の「週次営業レポート」を参照")
        return

    try:
        this_week = fetch_ga4_clinic_events(7, 1)
        last_week = fetch_ga4_clinic_events(14, 8)
        filters_top = fetch_filter_trends()
    except Exception as e:
        print(f"❌ GA4取得エラー: {e}")
        return

    if not this_week:
        print("⏸ 今週の医院別イベントがまだありません（データ蓄積待ち）")
        return

    # ── 営業優先度：公式サイトクリック > 伸び率 > 閲覧数 ──
    def score(name):
        s = this_week.get(name, {})
        prev = last_week.get(name, {})
        clicks = s.get("official_click", 0)
        views = s.get("clinic_click", 0)
        growth = views - prev.get("clinic_click", 0)
        return clicks * 10 + max(growth, 0) * 3 + views

    ranked = sorted(this_week.keys(), key=score, reverse=True)[:5]

    # ── レポート添付（上位2院分を自動生成） ──
    attachments = []
    try:
        sys.path.insert(0, str(ROOT))
        import clinic_report
        db = json.loads((ROOT / "clinic_db.json").read_text(encoding="utf-8"))
        for name in ranked[:2]:
            hits = clinic_report.find_clinic(db, name)
            if len(hits) == 1:
                s = this_week.get(name, {})
                html_doc = clinic_report.build_report(
                    hits[0],
                    db=db,
                    views=s.get("clinic_click", 0),
                    clicks=s.get("official_click", 0),
                    maps=s.get("map_click", 0),
                )
                attachments.append((f"反響レポート_{name[:20]}.html", html_doc))
    except Exception as e:
        print(f"⚠️ レポート生成スキップ: {e}")

    # ── メール本文 ──
    lines = [f"{CFG['site_name']} 週次営業レポート（{today.isoformat()}）", ""]
    lines.append("■ 今週、営業する価値がある医院（反響順）")
    lines.append("")
    for i, name in enumerate(ranked, 1):
        s = this_week.get(name, {})
        prev = last_week.get(name, {})
        views, pv = s.get("clinic_click", 0), prev.get("clinic_click", 0)
        clicks = s.get("official_click", 0)
        trend = f"（前週{pv}回→今週{views}回に増加）" if views > pv > 0 else ""
        lines.append(f"{i}. {name}")
        lines.append(f"   閲覧{views}回 / 公式サイトへ{clicks}回 / 地図{s.get('map_click', 0)}回 {trend}")
    lines.append("")

    if filters_top:
        lines.append("■ 今週よく選ばれた条件（患者の関心）")
        for v, cnt in filters_top[:8]:
            lines.append(f"   ・{v}：{cnt}回")
        lines.append("")

    top_name = ranked[0]
    top_stats = this_week.get(top_name, {})
    tviews = top_stats.get("clinic_click", 0)
    pviews = last_week.get(top_name, {}).get("clinic_click", 0)
    trend_note = (f"・特に直近は閲覧が増えており（前週{pviews}回→今週{tviews}回）、\n"
                  f"　患者様からの関心が高まっている状況です。\n") if tviews > pviews > 0 else ""
    lines.append("■ そのまま送れる営業メール下書き（第1候補向け）")
    lines.append("─" * 40)
    lines.append(build_sales_email_draft(top_name, top_stats, trend_note))
    lines.append("─" * 40)
    lines.append("")
    lines.append("※添付：上位医院の反響レポートHTML（そのまま先方に送付可）")
    body = "\n".join(lines)

    if DRY_RUN:
        print(body)
        print(f"\n[dry-run] 添付{len(attachments)}件 / 送信先 {MAIL_TO}")
        return

    # ── Gmail送信 ──
    msg = MIMEMultipart()
    msg["Subject"] = f"【営業レポート】今週アプローチすべき医院 — {CFG['site_name']} {today.strftime('%m/%d')}"
    msg["From"] = MAIL_FROM
    msg["To"] = MAIL_TO
    msg.attach(MIMEText(body, "plain", "utf-8"))
    for fname, content in attachments:
        part = MIMEBase("text", "html", charset="utf-8")
        part.set_payload(content.encode("utf-8"))
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
        msg.attach(part)

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(MAIL_FROM, GMAIL_APP_PASSWORD)
        server.send_message(msg)
    print(f"✅ 営業レポート送信完了 → {MAIL_TO}")


if __name__ == "__main__":
    main()
