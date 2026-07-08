# -*- coding: utf-8 -*-
"""
Place Details API で全医院の 電話番号・診療時間・公式URL・最新評価 を補完する。
- DBキー = place_id。全2,703院を対象（精度重視）。
- 取得fields: website / formatted_phone_number / national_phone_number /
  opening_hours(weekday_text) / rating / user_ratings_total / business_status
- 既に details_fetched=True の院はスキップ（再実行に強い）。
- 50院ごとにDB保存（チェックポイント）。失敗は1回リトライ。
使い方: python3 enrich_details.py           # 未取得のみ
        python3 enrich_details.py --force   # 全院再取得
"""
import os, sys, json, time, urllib.parse, urllib.request

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
FORCE = "--force" in sys.argv

def load_env():
    for base in (ROOT, os.path.join(ROOT, "..")):
        p = os.path.join(base, ".env")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()
KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

FIELDS = ("website,formatted_phone_number,international_phone_number,"
          "opening_hours,rating,user_ratings_total,business_status")

def fetch_details(place_id, retries=2):
    if not KEY or not place_id:
        return None
    url = (f"https://maps.googleapis.com/maps/api/place/details/json"
           f"?place_id={urllib.parse.quote(place_id)}&fields={FIELDS}&language=ja&key={KEY}")
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8"))
            status = data.get("status")
            if status == "OK":
                return data.get("result", {})
            if status in ("OVER_QUERY_LIMIT", "UNKNOWN_ERROR"):
                time.sleep(2.0); continue
            return {}  # NOT_FOUND, ZERO_RESULTS 等は空扱い
        except Exception:
            time.sleep(1.5)
    return None

def main():
    if not KEY:
        print("❌ GOOGLE_MAPS_API_KEY 未設定"); return
    db = json.load(open(DB, encoding="utf-8"))
    items = [(pid, c) for pid, c in db.items() if c.get("name")]
    total = len(items)
    todo = [x for x in items if FORCE or not x[1].get("details_fetched")]
    print("=" * 56)
    print("  Place Details 補完")
    print(f"  全 {total}院 / 対象 {len(todo)}院  FORCE={FORCE}")
    print("=" * 56, flush=True)

    done = ok = fail = 0
    got_phone = got_hours = got_url = 0
    for i, (pid, c) in enumerate(todo, 1):
        res = fetch_details(pid)
        if res is None:
            fail += 1
            print(f"  [{i}/{len(todo)}] {c.get('name','')[:22]}  ⚠️通信失敗", flush=True)
            time.sleep(0.4)
            continue
        # マージ（実データのみ上書き）
        phone = res.get("formatted_phone_number") or res.get("international_phone_number") or ""
        hours = (res.get("opening_hours") or {}).get("weekday_text", [])
        website = res.get("website", "")
        if phone:
            c["phone"] = phone; got_phone += 1
        if hours:
            c["business_hours"] = hours; got_hours += 1
        if website and "google.com/maps" not in website:
            if not c.get("url"):
                got_url += 1
            c["url"] = website
        if res.get("rating"):
            c["rating"] = res["rating"]
        if res.get("user_ratings_total") is not None:
            c["total_reviews"] = res["user_ratings_total"]
        c["business_status"] = res.get("business_status", c.get("business_status", ""))
        c["details_fetched"] = True
        ok += 1; done += 1
        mark = ("📞" if phone else "  ") + ("🕐" if hours else "  ") + ("🔗" if website else "")
        print(f"  [{i}/{len(todo)}] {c.get('name','')[:22]}  {mark}", flush=True)
        if i % 50 == 0:
            json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"    💾 {i}院保存 / 電話{got_phone} 時間{got_hours} 新URL{got_url}", flush=True)
        time.sleep(0.2)

    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("=" * 56)
    print("  ✅ 完了")
    print(f"  取得成功 {ok}院 / 通信失敗 {fail}院")
    print(f"  電話取得 {got_phone} / 診療時間 {got_hours} / 新規URL {got_url}")
    tot_phone = sum(1 for _, c in items if c.get("phone"))
    tot_hours = sum(1 for _, c in items if c.get("business_hours"))
    tot_url = sum(1 for _, c in items if c.get("url"))
    print(f"  DB累計: 電話{tot_phone}院 / 診療時間{tot_hours}院 / 公式URL{tot_url}院")
    print("=" * 56)
    try:
        import subprocess
        subprocess.run(["osascript", "-e",
            f'display notification "電話{tot_phone}・診療時間{tot_hours}院" with title "Place Details補完 完了" sound name "Glass"'], check=False)
    except Exception:
        pass

if __name__ == "__main__":
    main()
