# -*- coding: utf-8 -*-
"""
DB品質フラグ付与（削除しない・復元可能）。
各院に以下を付与し、q_excluded=True を全ページで除外する。
  q_in_osaka : 住所に「京都市」を含む（＝京都市内）
  q_is_salon : 非歯科のホワイトニング等サロン（名称判定）
  q_is_dup   : 同名＋同住所の重複（口コミ最多の1件を残し他をTrue）
  q_excluded : 上記のいずれかで表示対象外
使い方: python3 db_quality.py            # フラグ付与して保存
        python3 db_quality.py --report   # 保存せず集計のみ
"""
import os, re, json, sys
from collections import defaultdict

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
REPORT = "--report" in sys.argv

SALON_KW = ["ホワイトニングサロン", "セルフホワイトニング", "ホワイトニング専門店",
            "ホワイトニングバー", "ホワイトニングショップ", "ホワイトニングカフェ",
            "ホワイトニングスタジオ", "ホワイトニングラボ"]
DENTAL_KW = ["歯科", "デンタル", "dental", "Dental", "DENTAL", "矯正", "口腔",
             "クリニック", "歯医者", "デンタルオフィス", "小児歯", "歯"]

def is_salon(name):
    if any(k in name for k in SALON_KW):
        return True
    # 「ホワイトニング」を含み、歯科系語を一切含まない＝サロンとみなす
    if "ホワイトニング" in name and not any(k in name for k in DENTAL_KW):
        return True
    return False

def addr_key(a):
    return re.sub(r"\s", "", a or "")[:20]

def reviews(c): return int(c.get("total_reviews", 0) or 0)
def rating(c): return float(c.get("rating", 0) or 0)

def main():
    db = json.load(open(DB, encoding="utf-8"))
    items = [(pid, c) for pid, c in db.items() if c.get("name")]

    # 重複判定（同名＋同住所プレフィックス）
    groups = defaultdict(list)
    for pid, c in items:
        groups[(c["name"], addr_key(c.get("address", "")))].append((pid, c))
    dup_pids = set()
    for k, lst in groups.items():
        if len(lst) > 1:
            lst.sort(key=lambda t: (-reviews(t[1]), -rating(t[1])))
            for pid, c in lst[1:]:
                dup_pids.add(pid)

    n_osaka = n_salon = n_dup = n_excl = 0
    for pid, c in items:
        in_osaka = "京都市" in (c.get("address") or "")
        salon = is_salon(c["name"])
        dup = pid in dup_pids
        excl = (not in_osaka) or salon or dup
        c["q_in_osaka"] = in_osaka
        c["q_is_salon"] = salon
        c["q_is_dup"] = dup
        c["q_excluded"] = excl
        if not in_osaka: n_osaka += 1
        if salon: n_salon += 1
        if dup: n_dup += 1
        if excl: n_excl += 1

    total = len(items)
    active = total - n_excl
    print("=" * 52)
    print(f"  総院数        : {total}")
    print(f"  京都市外      : {n_osaka} 院（除外）")
    print(f"  非歯科サロン  : {n_salon} 院（除外）")
    print(f"  重複          : {n_dup} 院（除外・統合）")
    print(f"  --------------")
    print(f"  ✅ 表示対象(active): {active} 院")
    print("=" * 52)

    if REPORT:
        print("（--report のため保存せず）")
        return
    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("💾 clinic_db.json にフラグを保存しました")

if __name__ == "__main__":
    main()
