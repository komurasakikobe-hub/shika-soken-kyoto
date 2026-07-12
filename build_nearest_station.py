# -*- coding: utf-8 -*-
"""
座標(lat/lng)を latitude/longitude にリネームし、station.pyの駅リストと
Haversine式で最寄駅を計算して nearest_station を構築する。

・座標のある医院のみ対象（座標のない医院は再ジオコーディングしない）
・specialty_tags/site_features内の「○○駅徒歩○分」等の公式記載があれば
  official_walk_minutes / official_walk_source として保持し、座標推定より
  優先する
・座標からの推定は calculation_type: "straight_distance_estimate" として
  明記し、直線距離であることを断定しない
"""
import importlib
import json
import math
import re
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "clinic_db.json"

# 駅リストは都市ごとのモジュール（例: osaka_stations / kobe_stations）。
# モジュール名は site_config.json の stations_module から読む（ハードコード禁止）。
_CFG = json.loads((ROOT / "site_config.json").read_text(encoding="utf-8"))
STATIONS = importlib.import_module(_CFG["stations_module"]).STATIONS

WALK_METERS_PER_MIN = 80  # 不動産表示の慣習（分速80m）


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_station(lat, lng):
    best = None
    best_dist = None
    for name, operator, line, slat, slng in STATIONS:
        d = haversine_m(lat, lng, slat, slng)
        if best_dist is None or d < best_dist:
            best_dist = d
            best = (name, operator, line, slat, slng)
    if not best:
        return None
    name, operator, line, slat, slng = best
    walk_min = best_dist / WALK_METERS_PER_MIN
    return {
        "name": name,
        "operator": operator,
        "line": line,
        "latitude": slat,
        "longitude": slng,
        "straight_distance_m": round(best_dist),
        "estimated_walk_minutes_min": max(1, round(walk_min * 0.8)),
        "estimated_walk_minutes_max": round(walk_min * 1.2) + 1,
        "calculation_type": "straight_distance_estimate",
        "official_walk_minutes": None,
        "official_walk_source": None,
        "confidence": "high" if best_dist <= 1200 else ("medium" if best_dist <= 3000 else "low"),
    }


def extract_official_walk(clinic):
    """specialty_tags/site_featuresから「○○駅徒歩○分」等の公式記載を抽出する。
    見つかった場合は (station_name, minutes, source_text) を返す。"""
    texts = list(clinic.get("specialty_tags") or []) + list(clinic.get("site_features") or [])
    for t in texts:
        m = re.search(r"([一-龥ぁ-んァ-ヶA-Za-z0-9]+駅)[から]*[^0-9]{0,6}徒歩\s*([0-9]+)\s*分", t)
        if m:
            return m.group(1), int(m.group(2)), t
    return None


def main():
    backup_path = ROOT / f"_backups/clinic_db.backup_before_station_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup_path.parent.mkdir(exist_ok=True)
    shutil.copy(DB_PATH, backup_path)
    print(f"バックアップ作成: {backup_path.name}")

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))

    renamed = 0
    stationed = 0
    official_found = 0
    for pid, c in db.items():
        if c.get("q_excluded") or not c.get("name"):
            continue
        lat = c.get("lat")
        lng = c.get("lng")
        if lat and lng and not c.get("latitude"):
            c["latitude"] = lat
            c["longitude"] = lng
            c["location_source"] = "geocoding"
            del c["lat"]
            del c["lng"]
            renamed += 1

        if c.get("latitude") and c.get("longitude"):
            ns = find_nearest_station(c["latitude"], c["longitude"])
            official = extract_official_walk(c)
            if official:
                st_name, minutes, source_text = official
                # 公式記載の駅名が、座標から計算した最寄駅と食い違う場合がある
                # （マーケティング文言で少し離れた主要駅を挙げているケース等）。
                # 公式記載がある場合は、その駅をSTATIONSリストから引いて
                # nearest_stationを差し替える（座標計算より公式情報を優先）。
                match = next((s for s in STATIONS if s[0] == st_name or st_name.rstrip("駅") in s[0]), None)
                if match:
                    name, operator, line, slat, slng = match
                    dist = haversine_m(c["latitude"], c["longitude"], slat, slng)
                    ns = {
                        "name": name, "operator": operator, "line": line,
                        "latitude": slat, "longitude": slng,
                        "straight_distance_m": round(dist),
                        "estimated_walk_minutes_min": minutes,
                        "estimated_walk_minutes_max": minutes,
                        "calculation_type": "straight_distance_estimate",
                        "official_walk_minutes": minutes,
                        "official_walk_source": source_text,
                        "confidence": "high",
                    }
                elif ns:
                    ns["official_walk_minutes"] = minutes
                    ns["official_walk_source"] = source_text
                official_found += 1
            if ns:
                c["nearest_station"] = ns
                stationed += 1

    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"latitude/longitudeへリネーム: {renamed}院")
    print(f"nearest_station付与: {stationed}院")
    print(f"公式「駅徒歩◯分」記載を検出: {official_found}院")


if __name__ == "__main__":
    main()
