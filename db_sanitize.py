# -*- coding: utf-8 -*-
"""
clinic_db.json の再発防止サニタイザ。
1) genre に検索キーワード文字列が混入した医院を「一般歯科」に中立化
2) 何のシグナル（Google口コミ件数・phrases・sources）も無い医院のAI評価を消去
   （＝根拠のないAI断定を残さない）
単体実行: python3 db_sanitize.py
generate.py から記事生成後に自動呼び出しされる。
"""
import json, os

CLEAN_GENRES = {"インプラント","矯正","ホワイトニング","親知らず","小児歯科","根管治療",
                "審美歯科","入れ歯","歯周病","予防歯科","一般歯科","虫歯治療",
                "歯のクリーニング","無痛治療","セラミック","マウスピース矯正","訪問歯科"}

AI_TEXT  = ["ai_summary","catchphrase","best_patient_profile","not_recommended_profile","reputation_summary"]
AI_LIST  = ["reputation_tags","referral_to","not_referral_to","fit_for","not_fit_for"]
AI_DICT  = ["patient_scores","doctor_stars","workplace_stars","case_analysis"]

def _signal(x):
    return (x.get("total_reviews") or 0) > 0 or bool(x.get("phrases")) or (x.get("sources_analyzed") or 0) > 0

def sanitize(db: dict):
    genre_fixed = 0
    ai_cleared = 0
    for x in db.values():
        if not x.get("name"):
            continue
        # 1) キーワードgenreの中立化
        g = x.get("genre", "")
        if g and g not in CLEAN_GENRES and len(g) > 8:
            x["genre"] = "一般歯科"
            genre_fixed += 1
        # 2) ノーシグナル医院の根拠なきAI評価を消去
        if not _signal(x):
            touched = False
            for f in AI_TEXT:
                if x.get(f):
                    x[f] = ""; touched = True
            for f in AI_LIST:
                if x.get(f):
                    x[f] = []; touched = True
            for f in AI_DICT:
                if x.get(f):
                    x[f] = {}; touched = True
            if touched:
                ai_cleared += 1
    return genre_fixed, ai_cleared

def run(path):
    if not os.path.exists(path):
        return
    db = json.load(open(path, encoding="utf-8"))
    gf, ac = sanitize(db)
    json.dump(db, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"  🧹 サニタイズ: genre中立化 {gf}院 / 根拠なきAI評価クリア {ac}院")

if __name__ == "__main__":
    run(os.path.join(os.path.dirname(__file__), "clinic_db.json"))
