# -*- coding: utf-8 -*-
"""
掲載院の評価・口コミ件数の月次リフレッシュ

背景：サイトの口コミ件数・評価は収集時点で凍結されており、放置すると実際のGoogle上の
数字とズレていく（たまい歯科：DB71件↔実際20件の事故）。Places APIから
rating / user_ratings_total だけを軽量に再取得し、DBと表示を最新に保つ。

- 対象：q_excludedでない掲載院のみ（大阪なら約2,000件）
- APIコスト：1院1コール。Maps APIの月次無料枠がリセットされる毎月1日の実行を想定
  （launchd: com.osakashikasoken.reviewrefresh が毎月1日 4:00 に実行）
- 50院ごとにDB保存（チェックポイント）。実行後は build_clinics.py 等での再生成が必要
  （launchd側で本スクリプト→再生成→git push まで行う）

使い方: python3 refresh_reviews.py           # 全掲載院
        python3 refresh_reviews.py --limit 20 # テスト
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "clinic_db.json"
LIMIT = None
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])


def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


load_env()
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")


def fetch(place_id: str):
    url = ("https://maps.googleapis.com/maps/api/place/details/json"
           f"?place_id={urllib.parse.quote(place_id)}"
           "&fields=rating,user_ratings_total,business_status&language=ja&key=" + KEY)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                d = json.loads(r.read().decode("utf-8"))
            if d.get("status") == "OK":
                return d.get("result", {})
            if d.get("status") in ("OVER_QUERY_LIMIT", "UNKNOWN_ERROR") and attempt < 2:
                time.sleep(10 * (attempt + 1))
                continue
            return None
        except Exception:
            if attempt < 2:
                time.sleep(5)
                continue
            return None


def main():
    if not KEY:
        print("❌ GOOGLE_MAPS_API_KEY が未設定です")
        return
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    targets = [(pid, c) for pid, c in db.items()
               if not c.get("q_excluded") and c.get("name")
               and str(pid).startswith("ChIJ")]
    if LIMIT:
        targets = targets[:LIMIT]
    today = date.today().isoformat()
    print(f"評価・口コミ件数リフレッシュ 対象 {len(targets)}院（{today}）")

    updated = closed = failed = 0
    for i, (pid, c) in enumerate(targets, 1):
        res = fetch(pid)
        if res is None:
            failed += 1
        else:
            old_rv = c.get("total_reviews")
            c["rating"] = res.get("rating", c.get("rating"))
            c["total_reviews"] = res.get("user_ratings_total", c.get("total_reviews"))
            c["reviews_refreshed"] = today
            if res.get("business_status") == "CLOSED_PERMANENTLY":
                # 閉業検知：即除外はせず要確認フラグ（誤検知対策）。監査時に確認する
                c["q_maybe_closed"] = True
                closed += 1
            if c["total_reviews"] != old_rv:
                updated += 1
        if i % 50 == 0:
            DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {i}/{len(targets)} 保存（件数変化 {updated}・閉業疑い {closed}・失敗 {failed}）")
        time.sleep(0.15)

    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 完了：件数変化 {updated}院 / 閉業疑い {closed}院 / 取得失敗 {failed}院")
    if closed:
        print("⚠️ 閉業疑い（q_maybe_closed=True）の医院があります。確認のうえdb_quality等で除外してください。")


if __name__ == "__main__":
    main()
