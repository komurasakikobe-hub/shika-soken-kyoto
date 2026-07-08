# -*- coding: utf-8 -*-
"""
公開対象の全医院について、URLスラッグ（articles/clinics/<slug>.html のslug部分）を
一意に確定させ、clinic_slugs.json（place_id -> slug）として出力する。

背景：医院名だけからslugを作ると、同姓同名だが別住所・別電話の医院同士でURLが衝突し、
片方のページが上書きされて消えるバグがあった（2026-07-07 監査で発見、126組・305院）。

衝突時の解決順：
  1. 区名（address内の「〜区」）を末尾に付加
  2. それでも衝突する場合（同じ区に同名医院が複数）、電話番号下4桁を付加
  3. 電話番号もない/それでも衝突する場合、place_idの末尾6文字を付加

build_clinics.py / build_features.py / articles/shindan/shindan.js は、
この clinic_slugs.json を読み込んでURLを生成する（个别にslugifyし直さない）。
"""
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "clinic_db.json"
OUT_PATH = ROOT / "clinic_slugs.json"


def base_slug(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|　\s・。、]', '_', name)[:60]


def extract_ward(address: str) -> str:
    # 「京都市」「京都府」等の地名プレフィックスを除いてから区名を抽出する
    # （そうしないと「天王寺区」が「阪市天王寺区」のように誤って切り出される）
    addr = re.sub(r'^[〒0-9\-]*\s*(京都府)?(京都市)?', '', address or "")
    m = re.search(r'([^\s０-９0-9〒\-−]{1,5}区)', addr)
    return m.group(1) if m else ""


def phone_suffix(phone: str) -> str:
    digits = re.sub(r'\D', '', phone or "")
    return digits[-4:] if len(digits) >= 4 else ""


def main():
    db = json.loads(DB_PATH.read_text(encoding="utf-8"))
    published = [(pid, v) for pid, v in db.items() if v.get("name") and not v.get("q_excluded")]

    groups = defaultdict(list)
    for pid, v in published:
        groups[base_slug(v["name"])].append((pid, v))

    result = {}
    collision_count = 0
    for base, items in groups.items():
        if len(items) == 1:
            result[items[0][0]] = base
            continue

        collision_count += 1
        # 第1段階：区名を付加
        ward_groups = defaultdict(list)
        for pid, v in items:
            ward = extract_ward(v.get("address", ""))
            candidate = f"{base}_{ward}" if ward else base
            ward_groups[candidate].append((pid, v))

        for candidate, sub_items in ward_groups.items():
            if len(sub_items) == 1:
                result[sub_items[0][0]] = candidate
                continue
            # 第2段階：電話番号下4桁を付加
            phone_groups = defaultdict(list)
            for pid, v in sub_items:
                suf = phone_suffix(v.get("phone", ""))
                cand2 = f"{candidate}_{suf}" if suf else candidate
                phone_groups[cand2].append((pid, v))
            for cand2, sub2 in phone_groups.items():
                if len(sub2) == 1:
                    result[sub2[0][0]] = cand2
                    continue
                # 第3段階：place_id末尾6文字（これで確実に一意になる）
                for pid, v in sub2:
                    result[pid] = f"{cand2}_{pid[-6:]}"

    # 検証：全slugが一意か
    slugs = list(result.values())
    assert len(slugs) == len(set(slugs)), "slugが一意になっていません"
    assert len(result) == len(published), f"件数不一致: {len(result)} != {len(published)}"

    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"公開対象: {len(published)}件")
    print(f"衝突していたベースslugグループ: {collision_count}組")
    print(f"ユニークslug: {len(set(slugs))}件（全件一意を確認）")
    print(f"出力: {OUT_PATH}")


if __name__ == "__main__":
    main()
