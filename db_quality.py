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
# 美容予約サイト（歯科医院は基本的に掲載しない）のドメインが公式URLに使われている場合はサロンとみなす
# （2026-07-09 発見：「Whitening salon bright」等、英語表記のため名称キーワードだけでは
#  検出できなかったサロンが name-only 判定をすり抜けていた）
SALON_URL_KW = ["beauty.hotpepper.jp", "beauty.rakuten.co.jp", "salon.beauty"]

def is_salon(name, url=""):
    name_lower = name.lower()
    if any(k in name for k in SALON_KW):
        return True
    # 「ホワイトニング」「whitening」を含み、歯科系語を一切含まない＝サロンとみなす
    # （英語表記 whitening は大文字小文字を区別せず判定する）
    has_whitening = "ホワイトニング" in name or "whitening" in name_lower
    if has_whitening and not any(k in name for k in DENTAL_KW):
        return True
    if url and any(k in url for k in SALON_URL_KW):
        return True
    return False

def addr_key(a):
    # 郵便番号・都道府県名の有無で表記が揺れると同一住所でも別キーになってしまう
    # （2026-07-09 発見：「〒554-0024大阪府大阪市此花区...」と「大阪市此花区...」が
    #  別グループ扱いになり、同一ビルの重複医院が検出されなかった）ため、
    # 郵便番号・都道府県を除去してから先頭を比較する。
    a = re.sub(r"^〒?\d{3}-?\d{4}\s*", "", a or "")
    a = re.sub(r"^(大阪府|兵庫県|京都府|奈良県|滋賀県|和歌山県)", "", a)
    return re.sub(r"\s", "", a)[:20]

def phone_key(p):
    digits = re.sub(r"\D", "", p or "")
    return digits if len(digits) >= 9 else None

def reviews(c): return int(c.get("total_reviews", 0) or 0)
def rating(c): return float(c.get("rating", 0) or 0)

def main():
    db = json.load(open(DB, encoding="utf-8"))
    items = [(pid, c) for pid, c in db.items() if c.get("name")]

    # 重複判定：①同名＋同住所プレフィックス ②同名＋同電話番号（住所の表記揺れに強い）
    groups = defaultdict(list)
    for pid, c in items:
        groups[(c["name"], addr_key(c.get("address", "")))].append((pid, c))
        pk = phone_key(c.get("phone", ""))
        if pk:
            groups[(c["name"], "tel:" + pk)].append((pid, c))
    dup_pids = set()
    for k, lst in groups.items():
        # 同じ院が住所キー・電話キーの両方に登録されるため、pidで一意化してから判定
        uniq = {pid: c for pid, c in lst}
        lst = list(uniq.items())
        if len(lst) > 1:
            lst.sort(key=lambda t: (-reviews(t[1]), -rating(t[1])))
            for pid, c in lst[1:]:
                dup_pids.add(pid)

    n_osaka = n_salon = n_dup = n_excl = 0
    for pid, c in items:
        in_osaka = "京都市" in (c.get("address") or "")
        salon = is_salon(c["name"], c.get("url", ""))
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
