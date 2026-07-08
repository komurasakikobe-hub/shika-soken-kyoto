# -*- coding: utf-8 -*-
"""
Nominatim（OpenStreetMap、無料）で clinic_db.json 全院の緯度経度を取得し、
各医院レコードに "lat" / "lng" フィールドとして保存する。

利用規約遵守のため、1リクエスト/秒に制限（Nominatim Usage Policy）。
2,039院の処理には約35〜40分かかる。

使い方：
  python3 geocode_clinics.py
  → clinic_db.json を直接更新する（実行前に念のためバックアップを作成する）
  → 既に lat/lng が入っている医院はスキップするので、中断しても再実行で続きから進む
"""
import json
import re
import time
import unicodedata
import urllib.request
import urllib.parse
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "clinic_db.json"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "OsakaShikaSoken/1.0 (contact: komurasaki.kobe@gmail.com)"


def _query_nominatim(q: str):
    params = urllib.parse.urlencode({
        "q": q, "format": "json", "limit": 1, "countrycodes": "jp",
    })
    url = f"{NOMINATIM_URL}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
        if data:
            return float(data[0]["lat"]), float(data[0]["lon"])
    return None


def geocode(address: str):
    """住所から緯度経度を取得。番地レベルで見つからない場合は丁目→区の順に
    段階的に精度を落として再試行する（Nominatimは日本の番地レベル情報が
    手薄で、フルの住所ではヒットしないことが多いため）。
    失敗時はNoneを返す。"""
    if not address:
        return None
    norm = unicodedata.normalize("NFKC", address)
    norm = norm.replace("〒", "").strip()
    norm = re.sub(r"^\d{3}-?\d{4}\s*", "", norm)  # 郵便番号除去

    candidates = [norm]
    m = re.match(r"(.+?\d+丁目)", norm)
    if m:
        candidates.append(m.group(1))
    # 区レベルへのフォールバック。旧正規表現 r"(.+?[市区])" は「大阪市」の
    # "市"の字だけで止まってしまい、全区が"大阪市"という同一の粗い問い合わせに
    # 丸められて座標が衝突するバグがあった（2026-07-08 発見・修正）。
    # 「区」で終わる区名までを確実に含めて切り出す。
    m2 = re.search(r"京都市[^\d]*?区", norm)
    if m2:
        candidates.append(m2.group(0))

    for i, q in enumerate(candidates):
        try:
            result = _query_nominatim(q)
        except Exception as e:
            print(f"  ⚠️ エラー: {q[:30]}... -> {e}")
            result = None
        if result:
            return result
        if i < len(candidates) - 1:
            time.sleep(1.05)  # フォールバック再試行も1req/秒を守る
    return None


def main():
    backup_path = ROOT / f"_backups/clinic_db.backup_before_geocode_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup_path.parent.mkdir(exist_ok=True)
    shutil.copy(DB_PATH, backup_path)
    print(f"バックアップ作成: {backup_path.name}")

    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    items = [(pid, c) for pid, c in db.items() if not c.get("q_excluded") and c.get("name")]
    total = len(items)
    print(f"対象: {total}院")

    def has_coord(c):
        # build_nearest_station.py が lat/lng → latitude/longitude にリネームするため、
        # どちらの形式でも「座標あり」と判定する（2026-07-09：リネーム後に全件を
        # Nominatimへ再問い合わせしてしまう無駄を修正）
        return (c.get("lat") and c.get("lng")) or (c.get("latitude") and c.get("longitude"))

    done = sum(1 for _, c in items if has_coord(c))
    print(f"既に緯度経度あり: {done}院（スキップ）")

    processed = 0
    failed = 0
    for i, (pid, c) in enumerate(items, 1):
        if has_coord(c):
            continue
        addr = c.get("address", "")
        result = geocode(addr)
        if result:
            c["lat"], c["lng"] = result
            processed += 1
        else:
            failed += 1
        if i % 50 == 0 or i == total:
            print(f"[{i}/{total}] 処理済み={processed} 失敗={failed}")
            DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(1.05)  # Nominatim利用規約: 1req/秒以下

    DB_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完了: {processed}院に緯度経度を追加、{failed}院は取得失敗")


if __name__ == "__main__":
    main()
