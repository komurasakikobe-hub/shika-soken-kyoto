# -*- coding: utf-8 -*-
"""
患者目線のアクセス情報付与（nearest_bus_stop / nearest_ic）

背景（2026-07-11 ユーザー指摘）：最寄駅14kmの医院に「徒歩144〜218分相当の目安」と
表示され参考にならない。駅が現実的な徒歩圏（1.2km以内）にない医院には、
患者が実際に使う目安（最寄りバス停・高速IC・車の時間）を出すためのデータを付与する。

- 入力: access_points.json（fetch_access_points.pyでOverpass APIから機械取得）
- 対象: q_excludedでない全院。nearest_stationのstraight_distance_mが1200m超の院に付与
       （徒歩圏の院にはバス停情報は不要＝表示もしない）
- 出力: clinic_db.jsonの各院に nearest_bus_stop {name, distance_m} / nearest_ic {name, distance_m}
- 表示ロジックは shindan.js の formatStationText / build_clinics.py 側に実装
  （データと表示を分離。表示ルールはマニュアル§8参照）

使い方: python3 build_access_info.py
"""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "clinic_db.json"
AP_PATH = ROOT / "access_points.json"

WALK_LIMIT_M = 1200  # 徒歩圏の上限（≒15分）。これを超える院に代替アクセスを付与


def dist_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def nearest(points, lat, lng):
    best, bd = None, None
    for p in points:
        d = dist_m(lat, lng, p["lat"], p["lng"])
        if bd is None or d < bd:
            best, bd = p, d
    return (best, bd) if best else (None, None)


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    ap = json.loads(AP_PATH.read_text(encoding="utf-8"))
    bus = ap.get("bus_stops", [])
    # 患者の目的地になるIC系のみ（JCT=道路同士の接続・PA/SAは除外）
    ics = [i for i in ap.get("ics", [])
           if ("IC" in i["name"] or "インター" in i["name"] or "ランプ" in i["name"]
               or "出入口" in i["name"] or "出口" in i["name"])
           and "JCT" not in i["name"] and "PA" not in i["name"] and "SA" not in i["name"]]
    print(f"バス停{len(bus)}件 / IC{len(ics)}件 を使用")

    updated = skipped = 0
    for c in db.values():
        if c.get("q_excluded") or not c.get("name"):
            continue
        lat = c.get("latitude") or c.get("lat")
        lng = c.get("longitude") or c.get("lng")
        if not lat or not lng:
            continue
        ns = c.get("nearest_station") or {}
        d_station = ns.get("straight_distance_m")
        if d_station is not None and d_station <= WALK_LIMIT_M:
            # 徒歩圏：代替アクセス不要（既存の付与があれば残すが新規付与しない）
            skipped += 1
            continue
        b, bd = nearest(bus, lat, lng)
        if b:
            c["nearest_bus_stop"] = {"name": b["name"], "distance_m": bd}
        i, idist = nearest(ics, lat, lng)
        if i:
            c["nearest_ic"] = {"name": i["name"], "distance_m": idist}
        updated += 1

    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"✅ 付与 {updated}院（徒歩圏でスキップ {skipped}院）")


if __name__ == "__main__":
    main()
