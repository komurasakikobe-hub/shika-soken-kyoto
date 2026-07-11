# -*- coding: utf-8 -*-
"""
アクセス拠点（バス停・高速IC）の機械取得（Overpass API・無料）

背景（2026-07-11 ユーザー指摘）：最寄駅が14kmある田舎の医院に「徒歩144〜218分相当の目安」と
表示されており、患者の参考にならない。駅が遠い医院には、患者が実際に使う目安
（最寄りバス停・高速IC・車での時間）を出す。

手作業の地理データは欠落事故のもと（ユニバーサルシティ駅事故）のため、
駅リストと同じくOverpass APIで機械取得する。

出力: access_points.json  {"bus_stops":[{name,lat,lng}...], "ics":[{name,lat,lng}...]}
使い方: python3 fetch_access_points.py   （site_config.jsonのグリッド範囲を使用）
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "access_points.json"

# 収集範囲はclinic_collector.pyのグリッドと同じbboxを使う
import re
src = (ROOT / "clinic_collector.py").read_text(encoding="utf-8")


def _grid_bounds():
    m = re.search(r'"lat_min":\s*([\d.]+).*?"lat_max":\s*([\d.]+).*?"lng_min":\s*([\d.]+).*?"lng_max":\s*([\d.]+)', src, re.DOTALL)
    if not m:
        raise RuntimeError("clinic_collector.pyからグリッド範囲を読めませんでした")
    return tuple(float(x) for x in m.groups())


def overpass(query: str) -> list:
    import urllib.parse
    url = "https://overpass-api.de/api/interpreter"
    for attempt in range(3):
        try:
            data = urllib.parse.urlencode({"data": query}).encode("utf-8")
            req = urllib.request.Request(url, data=data,
                                         headers={"User-Agent": "shikasoken-access/1.0"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode("utf-8")).get("elements", [])
        except Exception as e:
            print(f"  リトライ{attempt+1}: {e}")
            time.sleep(20)
    raise RuntimeError("Overpass API取得失敗")


def main():
    lat1, lat2, lng1, lng2 = _grid_bounds()
    # 少し広めに取る（隣接市のIC・バス停が最寄りのことがある）
    pad = 0.03
    bbox = f"{lat1-pad},{lng1-pad},{lat2+pad},{lng2+pad}"
    print(f"収集範囲 bbox: {bbox}")

    print("バス停を取得中（highway=bus_stop）...")
    stops = overpass(f'[out:json][timeout:120];node["highway"="bus_stop"]({bbox});out;')
    bus = []
    seen = set()
    for e in stops:
        name = (e.get("tags") or {}).get("name", "")
        if not name:
            continue
        key = (name, round(e["lat"], 3), round(e["lon"], 3))
        if key in seen:
            continue
        seen.add(key)
        bus.append({"name": name, "lat": e["lat"], "lng": e["lon"]})
    print(f"  バス停 {len(bus)}件")

    time.sleep(5)
    print("高速道路IC・ランプを取得中（highway=motorway_junction）...")
    ics_raw = overpass(f'[out:json][timeout:120];node["highway"="motorway_junction"]["name"]({bbox});out;')
    ics = []
    seen = set()
    for e in ics_raw:
        name = (e.get("tags") or {}).get("name", "")
        if not name or name in seen:
            continue
        seen.add(name)
        ics.append({"name": name, "lat": e["lat"], "lng": e["lon"]})
    print(f"  IC {len(ics)}件: {[i['name'] for i in ics][:10]}")

    OUT.write_text(json.dumps({"bus_stops": bus, "ics": ics}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"✅ 保存: {OUT}")


if __name__ == "__main__":
    main()
