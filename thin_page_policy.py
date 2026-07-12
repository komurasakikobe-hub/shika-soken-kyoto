# -*- coding: utf-8 -*-
"""
薄いページ（scaled content abuse対策）の判定ロジックの正本（2026-07-13新設）。

【なぜ】院ページの大量自動生成のうち、実データがほぼ無いページは
Googleの「スケール化されたコンテンツの不正利用」ポリシーに該当しうる
（1ページの順位ではなくドメイン全体の手動対策・インデックス削除のリスク）。
薄い院ページは ①noindex,follow を付与 ②sitemapから除外 し、
インデックス対象から外す（ページ自体は残す＝公開済みURLを404にしない。
ランキング・一覧からの掲載は従来どおり）。

【判定】ページに載る「実データの量」を機械的に点数化する。
文言（「公開情報が限定的」等の定型文）だけで判定しない＝
実データが厚い院を誤ってnoindexしない（誤爆防止）。

  +2  deep_fetched（公式サイトの深掘り解析済み）
  +2  実質的なai_summary（空でなく、かつ「情報不足」定型文でない）
  +2  口コミ20件以上（+1  5件以上）
  +1  patient_scores（口コミ7軸分析）に正の値がある
  +1  equipment_stars / doctor_stars に正の値がある
  +1  院長名・診療理念・注力治療のいずれかがある
  +1  口コミ引用（phrases）が2件以上ある

  合計 THIN_MAX_POINTS（既定2）以下 → 薄いページ。

【運用】閾値はビジネス影響が大きいため、変更はユーザー承認のもとで行う。
全都市共通ロジック（都市固有値なし）。R6（利益相反）：notable等による
例外は設けない＝全院同一の機械判定。

CLIとして実行すると現DBでの判定内訳を表示する:
  python3 thin_page_policy.py [--list]
"""
import json
import os

# 薄いページと判定する上限点（この点数以下がnoindex対象）。
# 変更時はユーザー承認＋_reports/のレポート再生成を必ずセットにする。
THIN_MAX_POINTS = 2

import re as _re

# AIが「情報不足で分析できていない」ことを示す定型文パターン。
# 完全一致の文字列だと表記ゆれ（「極めて限定的」「判断しづらい」等）をすり抜けるため
# 正規表現で判定する（2026-07-13 独立監査の指摘で拡張）。
# 実質的な分析文かどうかの判定にのみ使う（これ単独でnoindexにはしない）。
THIN_AI_MARKERS = ("公開情報が限定的", "詳細な分析ができません", "情報が限られて")  # 互換用（旧・完全一致）
_THIN_AI_RE = _re.compile(
    r"(情報が(極めて)?限定|情報が限られ|情報が少な|情報不足|"
    r"分析ができません|分析が(困難|難し)|分析(は|が)でき(ず|ない)|"
    r"判断(でき|し)(ません|づらい|かねます)|判断(が|材料が)(難し|限定的|少な)|判定不可)"
)

# deep_fetched=True でも抽出結果が空（空振り）の院がある。実際にページへ表示できる
# フィールドが取れている場合のみ「公式サイト深掘り」として加点する（監査指摘）。
_DEEP_FIELDS = ("doctor_name", "philosophy", "focus_treatments", "site_features",
                "equipment_evidence", "qualifications", "specialty_evidence", "doctor_career")


def has_substantive_ai(c):
    """ai_summaryが「実質的な分析文」か（空・情報不足定型文はFalse）"""
    ai = (c.get("ai_summary") or "").strip()
    if not ai:
        return False
    return not _THIN_AI_RE.search(ai)


def is_placeholder_text(s):
    """短文（reputation_tags等）が「情報不足プレースホルダ」か。
    薄いページの表示側でscaled content署名を出さないためのフィルタに使う
    （2026-07-13 整合性監査後の是正で追加。判定点数には影響しない）"""
    return bool(_THIN_AI_RE.search(s or ""))


def _any_pos(d):
    return isinstance(d, dict) and any((v or 0) > 0 for v in d.values())


def _deep_with_content(c):
    """公式サイト深掘りが「表示できる中身」を実際に取れているか"""
    if not c.get("deep_fetched"):
        return False
    return any(c.get(k) for k in _DEEP_FIELDS)


def content_points(c):
    """ページに載る実データ量の点数（0〜10）"""
    p = 0
    if _deep_with_content(c):
        p += 2
    if has_substantive_ai(c):
        p += 2
    r = c.get("total_reviews") or 0
    p += 2 if r >= 20 else (1 if r >= 5 else 0)
    if _any_pos(c.get("patient_scores")):
        p += 1
    if _any_pos(c.get("equipment_stars")) or _any_pos(c.get("doctor_stars")):
        p += 1
    if c.get("doctor_name") or c.get("philosophy") or c.get("focus_treatments"):
        p += 1
    if len(c.get("phrases") or []) >= 2:
        p += 1
    return p


def is_thin(c):
    """このレコードの院ページをインデックス対象から外すべきか"""
    return content_points(c) <= THIN_MAX_POINTS


def thin_slugs(root=None):
    """薄い院のslug集合を返す（build_sitemap.py等のsitemap除外用）"""
    root = root or os.path.dirname(os.path.abspath(__file__))
    db = json.load(open(os.path.join(root, "clinic_db.json"), encoding="utf-8"))
    clinics = list(db.values()) if isinstance(db, dict) else db
    slug_map = json.load(open(os.path.join(root, "clinic_slugs.json"), encoding="utf-8"))
    import re as _re

    def _slugify(name):
        return _re.sub(r'[\\/:*?"<>|　\s・。、]', "_", name)[:60]

    out = set()
    for c in clinics:
        if not c.get("name") or c.get("q_excluded"):
            continue
        if is_thin(c):
            out.add(slug_map.get(c.get("place_id"), _slugify(c["name"])))
    return out


if __name__ == "__main__":
    import sys
    root = os.path.dirname(os.path.abspath(__file__))
    db = json.load(open(os.path.join(root, "clinic_db.json"), encoding="utf-8"))
    clinics = list(db.values()) if isinstance(db, dict) else db
    pub = [c for c in clinics if c.get("name") and not c.get("q_excluded")]
    thin = [c for c in pub if is_thin(c)]
    marker = [c for c in pub if (c.get("ai_summary") or "").strip() and not has_substantive_ai(c)]
    print(f"掲載院: {len(pub)}")
    print(f"薄いページ（{THIN_MAX_POINTS}点以下・noindex対象）: {len(thin)}")
    print(f"（参考）情報不足の定型文を含むai_summary: {len(marker)}")
    from collections import Counter
    print("点数分布:", sorted(Counter(content_points(c) for c in pub).items()))
    if "--list" in sys.argv:
        for c in sorted(thin, key=lambda x: content_points(x)):
            print(f"{content_points(c)}\t{c.get('name')}\t{c.get('total_reviews') or 0}件\t{c.get('place_id','')}")
