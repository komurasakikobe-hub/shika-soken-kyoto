# -*- coding: utf-8 -*-
"""
AI分析の根拠判定モジュール（2026-07-11 新設・全サイト共通）

ai_summary / fit_for / not_fit_for の各主張を、DB内の実データと突き合わせて
  grounded      … 実データに根拠がある（何に基づくかの説明つき）
  inferred      … 実データに直接の記述がない＝AIによる推定
  contradicted  … 実データ（肯定的な口コミ・診療時間等）と食い違う
の3値で判定する。

使い手:
  - audit_ai_grounding.py … 全院の一括監査
  - build_clinics.py      … 医院ページの「＋根拠」パネル生成
  - articles/shindan/shindan.js … 同じロジックのJS移植版（変更時は必ず両方直すこと）
"""
import re

# ── 診療時間から導出する事実 ─────────────────────────────


def _hours_lines(clinic):
    h = clinic.get("business_hours")
    if isinstance(h, list):
        return h
    return []


def latest_closing_minutes(clinic):
    """全曜日で最も遅い閉院時刻（分単位）。不明ならNone。"""
    lines = _hours_lines(clinic)
    if not lines:
        return None
    latest = None
    for line in lines:
        for m in re.finditer(r"～\s*(\d{1,2})時(\d{2})?", line):
            hh = int(m.group(1))
            mm = int(m.group(2) or 0)
            t = hh * 60 + mm
            if latest is None or t > latest:
                latest = t
    return latest


# 夜間・救急を明示する強いシグナル（診療時間データが実態を捉えられない救急病院向け）
_NIGHT_SIGNAL_RE = re.compile(r"夜間|深夜|24時間|２４時間|救急|時間外|ナイト|エマージェンシー")


def _night_operation_signal(clinic):
    """医院名そのものに夜間/救急営業の証拠があるか（例:「◯◯夜間動物救急センター」）。
    Googleの診療時間は夜間救急の実態を欠くため、名前が救急業態を示す場合のみ事実に優先する。
    ※タグや口コミは「夜間診療」タグの付き過ぎ・否定文混入があるため対象にしない（名前限定）。"""
    return bool(_NIGHT_SIGNAL_RE.search(clinic.get("name") or ""))


def evening_hours(clinic):
    """夜間帯の診療があるか。19:30以降=True / 18:00以前=False / その間・不明=None（判定保留）。
    ただし名前・口コミに夜間/救急営業の明確な証拠があれば、時間データに関わらずTrue。"""
    if _night_operation_signal(clinic):
        return True
    latest = latest_closing_minutes(clinic)
    if latest is None:
        return None
    if latest >= 19 * 60 + 30:
        return True
    if latest <= 18 * 60:
        return False
    return None  # 18:01〜19:29 は「夜」の解釈が分かれるため断定しない


def weekend_hours(clinic):
    """土曜または日曜に診療しているか。不明ならNone。"""
    lines = _hours_lines(clinic)
    if not lines:
        return None
    for line in lines:
        if (line.startswith("土曜日") or line.startswith("日曜日")) and "定休日" not in line and "休" != line.strip()[-1:]:
            if re.search(r"\d{1,2}時", line):
                return True
    return False


def parking_fact(clinic):
    stars = clinic.get("equipment_stars") or {}
    if (stars.get("駐車場") or 0) > 0:
        return True
    corpus = "／".join((clinic.get("site_features") or []) + (clinic.get("equipment_evidence") or []))
    if "駐車" in corpus:
        return True
    return None


def station_walk_min(clinic):
    st = clinic.get("nearest_station") or {}
    return st.get("estimated_walk_minutes_min")


# ── 根拠コーパス（実データのテキスト集合） ─────────────────


def build_corpus(clinic):
    parts = []
    parts += clinic.get("phrases") or []
    parts += clinic.get("reputation_tags") or []
    parts += clinic.get("specialty_tags") or []
    parts += clinic.get("focus_treatments") or []
    parts += clinic.get("site_features") or []
    parts += clinic.get("equipment_evidence") or []
    parts += clinic.get("qualifications") or []
    for k in ("reputation_summary", "philosophy", "catchphrase", "doctor_career"):
        v = clinic.get(k)
        if v:
            parts.append(str(v))
    return "／".join(parts)


def source_reason(clinic, hit):
    """根拠理由の文面。分析した口コミの規模（件数）を添えて、
    『1件の口コミ』に見えないようにする。件数不明のときは規模に触れない。"""
    n = clinic.get("total_reviews") or 0
    if n >= 20:
        return f"口コミ{n}件と公式サイトを分析し、「{hit}」への言及を確認しています"
    if n > 0:
        return f"口コミ{n}件と公式サイトの記載から「{hit}」を確認しています"
    return f"公式サイトと口コミの記載から「{hit}」を確認しています"


# ── キーワード群 ─────────────────────────────────────────

# 施術・ニーズ系（コーパスに肯定的記述があるかで判定。否定主張と衝突したら contradicted）
_TOPIC_KEYWORDS = [
    "ホワイトニング", "インプラント", "矯正", "予防", "小児", "子ども", "子供", "キッズ",
    "審美", "セラミック", "入れ歯", "義歯", "親知らず", "歯周病", "クリーニング",
    "猫", "犬", "エキゾチック", "うさぎ", "鳥", "手術", "腫瘍", "皮膚", "眼科",
]
# 属性系（コーパス一致で grounded にするが、否定主張でも contradicted にはしない）
_ATTR_KEYWORDS = [
    "女性", "高齢", "バリアフリー", "個室", "ベビーカー", "託児",
    "丁寧", "優しい", "痛くない", "痛みに配慮", "清潔",
]
# 「早さ」系（短期間・急ぎ）: コーパスに肯定記述があれば、否定主張は contradicted
_SPEED_RE = re.compile(r"短期間|短時間|スピーディ|すぐに|即日|早く終|早かった")

# 同義語（主張の語 → コーパスで探す語の一覧）
_SYNONYMS = {
    "子ども": ["子ども", "子供", "小児", "キッズ", "お子さま", "お子様"],
    "子供": ["子ども", "子供", "小児", "キッズ", "お子さま", "お子様"],
    "小児": ["子ども", "子供", "小児", "キッズ", "お子さま", "お子様"],
    "キッズ": ["子ども", "子供", "小児", "キッズ", "お子さま", "お子様"],
    "矯正": ["矯正", "インビザライン", "マウスピース"],
    "入れ歯": ["入れ歯", "義歯", "デンチャー"],
    "義歯": ["入れ歯", "義歯", "デンチャー"],
    "予防": ["予防", "クリーニング", "定期検診", "メンテナンス"],
}


def ground_claim(claim, clinic, negative=False):
    """主張1件を判定して (verdict, basis) を返す。
    negative=True は not_fit_for（〜な人には向かない）側の主張。"""
    corpus = build_corpus(clinic)

    # 1) 夜間
    if "夜" in claim:
        ev = evening_hours(clinic)
        if ev is None:
            latest = latest_closing_minutes(clinic)
            if latest is None:
                return "inferred", "診療時間の公開情報が十分でないため、傾向からのAI推定です"
            return "inferred", f"最終受付が{latest // 60}時台のため夜間の解釈は断定できず、AIが推定しています"
        if negative:
            return ("grounded", "診療時間より（平日18時台までに終了・夜間帯の診療なし）") if not ev \
                else ("contradicted", "診療時間では夜間帯の診療あり")
        return ("grounded", "診療時間より（夜間帯の診療あり）") if ev \
            else ("contradicted", "診療時間では夜間帯の診療なし")

    # 2) 土日
    if "土日" in claim or "週末" in claim or "休日" in claim:
        wk = weekend_hours(clinic)
        if wk is None:
            return "inferred", "診療時間の公開情報が十分でないため、傾向からのAI推定です"
        if negative:
            return ("grounded", "診療時間より（土日の診療なし）") if not wk \
                else ("contradicted", "診療時間では土日診療あり")
        return ("grounded", "診療時間より（土日の診療あり）") if wk \
            else ("contradicted", "診療時間では土日の診療なし")

    # 3) 駅近
    if "駅" in claim:
        walk = station_walk_min(clinic)
        if walk is None:
            return "inferred", "最寄駅の情報が十分でないため、傾向からのAI推定です"
        if negative:  # 「駅近を重視する人には不向き」等
            return ("grounded", f"最寄駅から徒歩約{walk}分〜（直線距離からの推計）") if walk >= 12 \
                else ("contradicted", f"最寄駅から徒歩約{walk}分〜と近い")
        return ("grounded", f"最寄駅から徒歩約{walk}分〜（直線距離からの推計）") if walk <= 8 \
            else ("inferred", f"最寄駅から徒歩約{walk}分〜（AIによる推定）")

    # 4) 駐車場・車
    if "駐車" in claim or "車で" in claim:
        pk = parking_fact(clinic)
        if pk:
            return ("contradicted", "駐車場ありの記載を確認") if negative \
                else ("grounded", "公式サイト等で駐車場を確認")
        return "inferred", "駐車場の公開情報が確認できないため、傾向からのAI推定です"

    # 5) 早さ（急いで・短期間）
    if re.search(r"急|短期間|短時間|すぐ", claim):
        m = _SPEED_RE.search(corpus)
        if m and negative:
            return "contradicted", f"口コミに「{m.group(0)}」等の肯定的な記述あり"
        if m:
            return "grounded", source_reason(clinic, m.group(0))
        return "inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"

    # 6) 施術・ニーズ系キーワード
    #    「〜以外」「〜より」等の否定・比較を含む主張は語の単純一致では判定できないため推定扱い
    negated_topic = ("以外" in claim) or ("よりも" in claim)
    for kw in _TOPIC_KEYWORDS:
        if kw in claim:
            if negated_topic:
                return "inferred", "表現の解釈が分かれるため、断定せずAIが推定しています"
            hit = next((s for s in _SYNONYMS.get(kw, [kw]) if s in corpus), None)
            if hit:
                if negative:
                    return "contradicted", f"口コミ・公式サイトに「{hit}」の肯定的な記述あり"
                return "grounded", source_reason(clinic, hit)
            return "inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"

    # 7) 属性系キーワード
    for kw in _ATTR_KEYWORDS:
        if kw in claim:
            if kw in corpus:
                return "grounded", source_reason(clinic, kw)
            return "inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"

    # 8) 患者スコア由来（怖がり・痛み）
    ps = clinic.get("patient_scores") or {}
    if re.search(r"怖|不安|痛み", claim):
        score = ps.get("痛みへの配慮") or ps.get("優しさ")
        if score and score >= 75:
            return "grounded", f"口コミ全体を分析した『痛みへの配慮・優しさ』スコア {score}／100 にもとづく傾向です"
        return "inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"

    # 9) 汎用: 主張中の2文字以上の語がコーパスにあるか
    for token in re.findall(r"[ぁ-んァ-ヶ一-龠a-zA-Z]{2,}", claim):
        if token in ("したい", "希望", "重視", "中心", "検討", "通え", "都合", "治療", "診療", "対応", "な人", "たい人"):
            continue
        if token in corpus:
            return "grounded", source_reason(clinic, token)

    return "inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"


# ═══ 自由文（AI ANALYSIS本文）の一文単位の根拠分解 ══════════════════
# ai_summary のような自由文を「主張の句」に割り、各句をポジ/ネガ文脈込みで
# grounding する。患者が読む文章そのものを検証可能にするのが目的。

# 句の区切り（読点・接続・逆接）
_CLAUSE_SPLIT_RE = re.compile(r"[。、！？\n]|一方で?|ただし|しかし|なお|また|ものの|反面")
# 「注意・不向き」寄りの句を示すシグナル
_NEG_CLAUSE_RE = re.compile(
    r"他院|他の医院|ほかの医院|他の病院|別の医院|別の病院|"
    r"不向き|向いてい?ま?せ?ん|向かない|おすすめしません|お勧めしません|"
    r"適しません|検討.{0,6}(お勧め|おすすめ|検討ください)|難しい|できません|"
    r"対応していません|注意が必要|には合わない|は避け|には不便|とは言えません")

# 句の中から根拠判定にかける「主張語」を拾うための語彙（トピック・属性・状況）
_SUMMARY_TERMS = (
    _TOPIC_KEYWORDS + _ATTR_KEYWORDS +
    ["夜", "夜間", "土日", "週末", "駅", "駐車", "車で", "急", "短期間", "短時間",
     "怖", "不安", "痛み", "安心", "丁寧", "説明", "清潔", "通いやすい", "アクセス"]
)


def split_clauses(text):
    """自由文を句に割る。空句は捨てる。"""
    if not text:
        return []
    return [seg.strip() for seg in _CLAUSE_SPLIT_RE.split(str(text)) if seg and seg.strip()]


# 文が「その機能は無い／対象外」と主張していることを示す語
_ABSENCE_RE = re.compile(r"ない|なし|行っていな|対応していな|できな|不可|休診|除く|限る|のみ")

# 事実照合できる機能語 → (事実を返す関数, 表示名)
_FACT_TERMS = {
    "夜": (evening_hours, "夜間帯の診療"),
    "夜間": (evening_hours, "夜間帯の診療"),
    "土日": (weekend_hours, "土日の診療"),
    "週末": (weekend_hours, "土日の診療"),
    "駐車": (parking_fact, "駐車場"),
}


def _eval_fact_term(term, clause, clinic):
    """機能語について、文が主張する極性（あり/なし）と実データを突き合わせる。
    戻り: (verdict, basis)。事実不明ならNoneを返して呼び出し側で通常処理に回す。"""
    fn, disp = _FACT_TERMS[term]
    fact = fn(clinic)  # True=あり / False=なし / None=不明
    if fact is None:
        return None
    # 文が「無い・対象外」と言っているか（絶対値の否定 or 不向き文脈）
    asserts_absent = bool(_ABSENCE_RE.search(clause)) or bool(_NEG_CLAUSE_RE.search(clause))
    if asserts_absent:
        if fact:  # 実際は「あり」なのに「無い/対象外」と書いている
            return "contradicted", f"実データでは{disp}あり（本文の記述と食い違い）"
        return "grounded", f"実データでも{disp}なし（本文の記述と一致）"
    else:  # 文は「あり」と主張
        if fact:
            return "grounded", f"実データでも{disp}あり（本文の記述と一致）"
        return "contradicted", f"実データでは{disp}なし（本文の記述と食い違い）"


def scan_summary_claims(text, clinic):
    """AI ANALYSIS本文を句ごとに分解し、含まれる主張語それぞれを根拠判定する。
    機能語（夜間・土日・駐車）は文の極性（あり/なし）を読み取って照合する。
    返り値: [{"clause","term","verdict","basis","negative"}]"""
    out = []
    seen = set()
    for clause in split_clauses(text):
        negative = bool(_NEG_CLAUSE_RE.search(clause))
        for term in _SUMMARY_TERMS:
            if term not in clause:
                continue
            if term in _FACT_TERMS:
                res = _eval_fact_term(term, clause, clinic)
                if res is None:
                    verdict, basis = "inferred", f"{_FACT_TERMS[term][1]}の情報なし（AIによる推定）"
                else:
                    verdict, basis = res
            else:
                verdict, basis = ground_claim(term, clinic, negative=negative)
            key = (term, verdict, negative)
            if key in seen:
                continue
            seen.add(key)
            out.append({"clause": clause, "term": term, "verdict": verdict,
                        "basis": basis, "negative": negative})
    return out


def summary_has_contradiction(text, clinic):
    """AI ANALYSIS本文が実データと矛盾する主張を含むか。"""
    return any(x["verdict"] == "contradicted" for x in scan_summary_claims(text, clinic))
