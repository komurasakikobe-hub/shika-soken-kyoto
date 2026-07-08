#!/usr/bin/env python3
"""
京都歯科総研 医院DB構築スクリプト（clinic_collector.py）v4.0

【設計思想 v4.0 — 2026-07-04】
  「検索に引っかかった医院を集める」→「京都市に存在する全医院を母集団にする」

  収集の考え方を根本から変更:
    旧: Text Search（検索語 × ジャンル × エリア） → 1,125院
    新: Nearby Search グリッド（座標ベース全域網羅）→ 目標2,500院以上

【収集フロー v4.0】
  Phase 1: Nearby Search グリッド — 京都市全域を800m間隔のグリッドで網羅
           type=dentist で歯科医院を全件取得（SEO・口コミ数に左右されない）
  Phase 2: Text Search 補完 — ジャンル別検索でPhase 1の漏れを補完
  Phase 3: AI評判分析 — 複数ソース統合でスコア生成

【足切りの廃止】
  評価・口コミ数による除外を廃止。
  「口コミ0件の新規院」「評価未付与の開院直後の院」も全件収録。
  AIが評価できる情報（ウェブサイト・求人・院長経歴）があれば高得点も可能。

【スコア設計 v3.0継続】
  口コミ・評判 25点 / 院長経歴 25点 / 設備 20点 / 透明性 15点 / 活動 15点

【実行方法】
  python3 clinic_collector.py          # フルスキャン（Phase1+2）
  python3 clinic_collector.py --phase1 # グリッド収集のみ
  python3 clinic_collector.py --phase2 # テキスト補完のみ
"""

import os, sys, json, time, re, urllib.request, urllib.parse
from datetime import datetime
from pathlib import Path

BASE_DIR      = Path(__file__).parent
CLINIC_DB     = BASE_DIR / "clinic_db.json"
CLINIC_DIR    = BASE_DIR / "articles" / "clinics"
GENERATOR     = Path("~/Desktop/クロード/AI評判設計システム/blog_generator.py").expanduser()

GMAPS_KEY     = os.environ.get("GOOGLE_MAPS_API_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_KEY    = os.environ.get("OPENAI_API_KEY", "")

CLEAN_GENRES = {
    "インプラント", "矯正", "ホワイトニング", "親知らず",
    "小児歯科", "根管治療", "審美歯科", "入れ歯", "歯周病", "予防歯科",
    "一般歯科", "虫歯治療", "歯のクリーニング",
    "無痛治療", "セラミック", "マウスピース矯正", "訪問歯科",
}

GENRES = [
    "インプラント", "矯正", "ホワイトニング", "親知らず",
    "小児歯科", "根管治療", "審美歯科", "入れ歯", "歯周病", "予防歯科",
    "一般歯科", "虫歯治療", "歯のクリーニング",
    "無痛治療", "セラミック", "マウスピース矯正", "訪問歯科",
]

AREAS = [
    "京都市北区", "京都市上京区", "京都市左京区", "京都市中京区",
    "京都市東山区", "京都市下京区", "京都市南区", "京都市右京区",
    "京都市伏見区", "京都市山科区", "京都市西京区",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; KyotoDentalResearch/1.0)"}


# ─────────────────────────────────────────────
# DB読み書き
# ─────────────────────────────────────────────
def load_db() -> dict:
    if CLINIC_DB.exists():
        try:
            return json.loads(CLINIC_DB.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}

def save_db(db: dict):
    CLINIC_DB.write_text(
        json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ─────────────────────────────────────────────
# テキスト取得ユーティリティ
# ─────────────────────────────────────────────
def fetch_text(url: str, limit: int = 5000) -> str:
    """URLのHTMLをテキストとして取得（タグ除去）"""
    if not url or "google.com/maps" in url:
        return ""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        raw = re.sub(r'<script[^>]*>.*?</script>', ' ', raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r'<style[^>]*>.*?</style>',  ' ', raw, flags=re.DOTALL | re.IGNORECASE)
        raw = re.sub(r'<[^>]+>', ' ', raw)
        raw = re.sub(r'\s+', ' ', raw).strip()
        return raw[:limit]
    except Exception:
        return ""


def find_subpages(base_url: str, html_raw: str = "") -> list:
    """
    公式サイトから「患者の声」「症例」「ブログ」「院長紹介」「求人」
    ページのURLを抽出する。
    """
    if not base_url:
        return []
    keywords = [
        "患者", "声", "口コミ", "症例", "case", "ブログ", "blog",
        "院長", "doctor", "about", "recruit", "求人", "スタッフ",
        "staff", "review", "testimonial",
    ]
    try:
        req = urllib.request.Request(base_url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=8) as r:
            raw = r.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    # href 抽出
    hrefs = re.findall(r'href=["\']([^"\'#?]+)["\']', raw, re.IGNORECASE)
    found = []
    base_domain = re.match(r'https?://[^/]+', base_url)
    domain = base_domain.group() if base_domain else ""

    for href in hrefs:
        href_lower = href.lower()
        if any(kw in href_lower for kw in keywords):
            if href.startswith("http"):
                found.append(href)
            elif href.startswith("/"):
                found.append(domain + href)

    # 重複除去・上位5件
    seen = set()
    unique = []
    for u in found:
        if u not in seen and u != base_url:
            seen.add(u)
            unique.append(u)
    return unique[:5]


# ─────────────────────────────────────────────
# 評判収集：複数ソースから公開テキストを集める
# ─────────────────────────────────────────────
def collect_reputation_sources(name: str, website: str, google_phrases: list) -> dict:
    """
    複数ソースから医院の評判情報を収集する。

    返り値:
        {
            "google_reviews": [...],   # Google口コミフレーズ
            "website_main": "...",     # 公式サイトTOP
            "website_sub": "...",      # 患者の声・症例・ブログ等
            "epark": "...",            # EPARK歯科
            "caloo": "...",            # Caloo
            "recruit": "...",          # 求人ページ（職場環境の指標）
            "sources_count": 3,        # 取得できたソース数
        }
    """
    result = {
        "google_reviews": google_phrases,
        "website_main":   "",
        "website_sub":    "",
        "epark":          "",
        "caloo":          "",
        "recruit":        "",
        "sources_count":  0,
    }

    # ① 公式サイト TOP
    if website and "google.com/maps" not in website:
        main_text = fetch_text(website, 4000)
        if main_text:
            result["website_main"] = main_text
            result["sources_count"] += 1

            # ① サブページ（患者の声・症例・ブログ・求人）
            subpages = find_subpages(website)
            sub_texts = []
            for url in subpages:
                t = fetch_text(url, 2000)
                if t:
                    if any(kw in url.lower() for kw in ["recruit", "求人", "staff", "スタッフ"]):
                        result["recruit"] += t[:1500]
                    else:
                        sub_texts.append(t[:1000])
            if sub_texts:
                result["website_sub"] = "\n---\n".join(sub_texts)
                result["sources_count"] += 1
            if result["recruit"]:
                result["sources_count"] += 1

    # ② EPARK歯科（公開検索ページ）
    try:
        encoded = urllib.parse.quote(name)
        epark_url = f"https://www.epark.jp/clinics/search/?keyword={encoded}&pref=27"
        epark_text = fetch_text(epark_url, 3000)
        if name[:4] in epark_text:  # 医院名が含まれている場合のみ
            result["epark"] = epark_text
            result["sources_count"] += 1
    except Exception:
        pass

    # ③ Caloo（公開検索ページ）
    try:
        encoded = urllib.parse.quote(name)
        caloo_url = f"https://caloo.jp/hospitals/search?q={encoded}&pref=27"
        caloo_text = fetch_text(caloo_url, 3000)
        if name[:4] in caloo_text:
            result["caloo"] = caloo_text
            result["sources_count"] += 1
    except Exception:
        pass

    return result


def extract_phrases_from_reviews(reviews: list) -> list:
    """Place Details の reviews から口コミフレーズを抽出"""
    phrases = []
    for rv in reviews[:5]:
        text = rv.get("text", "").strip()
        if not text:
            continue
        sentence = re.split(r'[。\n]', text)[0].strip()
        if 10 <= len(sentence) <= 80:
            phrases.append(sentence)
    return phrases[:5]


# ─────────────────────────────────────────────
# AI統合分析：評判サマリー + 専門性スコア
# ─────────────────────────────────────────────
def analyze_reputation_and_expertise(
    name: str, genre: str, sources: dict
) -> dict:
    """
    複数ソースの公開情報をAIが統合分析。

    【評価軸 v3.0】
    口コミ・評判       25点: マルチソース評判（Google+EPARK+Caloo+SNS言及）
    院長経歴・専門性   25点: 学会・資格・前職・症例数
    設備・診療体制     20点: CT・マイクロ・笑気・個室・バリアフリー等
    情報公開・透明性   15点: 料金・担当医・治療方針の公開度
    学会・症例・発信   15点: 症例写真・ブログ頻度・学会発表・求人評判
    """
    empty = {
        # 評判（25点）
        "reputation_score": 0,
        "reputation_tags":  [],
        "reputation_summary": "",
        # 患者体験7軸スコア（各100点）
        "patient_scores": {
            "技術力": 0, "説明力": 0, "清潔感": 0, "優しさ": 0,
            "子ども対応": 0, "痛みへの配慮": 0, "待ち時間": 0
        },
        # 院長（25点）
        "doctor_score": 0,
        "doctor_name":  "",
        "doctor_career": "",
        "doctor_evidence": [],
        "doctor_stars": {"専門性": 0, "研究実績": 0, "患者目線": 0, "経験": 0},
        # 症例分析
        "case_analysis": {
            "has_cases": False, "difficult_cases": [], "parts": [], "techniques": []
        },
        # 設備（20点）
        "equipment_score": 0,
        "equipment_evidence": [],
        # 透明性（15点）
        "transparency_score": 0,
        "transparency_evidence": [],
        # 学会・症例・発信（15点）
        "activity_score": 0,
        "activity_evidence": [],
        # 職場環境★評価
        "workplace_stars": {"教育制度": 0, "働きやすさ": 0, "衛生士定着率": 0, "スタッフ教育": 0},
        "workplace_quality": "",
        # 患者適合分析
        "fit_for": [],
        "not_fit_for": [],
        "best_patient_profile": "",
        "not_recommended_profile": "",
        # 総合
        "notable": False,
        "notable_reason": "",
        "catchphrase": "",
    }

    if not ANTHROPIC_KEY:
        return empty

    # 分析テキストを構築
    sections = []

    if sources.get("google_reviews"):
        reviews_text = "\n".join(f"・{r}" for r in sources["google_reviews"])
        sections.append(f"【Google口コミ（第三者）】\n{reviews_text}")

    if sources.get("epark"):
        sections.append(f"【EPARK歯科（第三者サイト）】\n{sources['epark'][:1500]}")

    if sources.get("caloo"):
        sections.append(f"【Caloo（第三者医療サイト）】\n{sources['caloo'][:1500]}")

    if sources.get("website_main"):
        sections.append(f"【公式サイト TOP】\n{sources['website_main'][:2000]}")

    if sources.get("website_sub"):
        sections.append(f"【公式サイト サブページ（患者の声・症例等）】\n{sources['website_sub'][:2000]}")

    if sources.get("recruit"):
        sections.append(f"【求人ページ（職場環境の指標）】\n{sources['recruit'][:1000]}")

    if not sections:
        return empty

    combined_text = "\n\n".join(sections)
    sources_count = sources.get("sources_count", 1)

    try:
        # 費用ルール（無料優先の原則）：大量・反復のAI分析は gpt-4o-mini に投げる。
        # 1院あたり$0.0005前後、1,500院でも100円未満。品質が要る記事生成等はClaudeのまま。
        prompt = f"""あなたは日本一の歯科コンサルタントです。
「{name}」について、以下の{sources_count}つの公開情報ソースを統合分析してください。

{combined_text}

【分析ルール】
- 実際に書かれている情報のみを根拠にする（推測・補完禁止）
- 情報がない項目はスコア0・空配列・空文字にする
- 第三者口コミ（Google・EPARK・Caloo）は公式サイトより信頼度が高い
- notable=trueは総合的に「京都歯科総研が強く推薦できる医院」と判断できる場合のみ

JSONのみ出力（コメント・説明文不要）:
{{
  "reputation_score": 0〜25,
  "reputation_tags": ["タグ1（15文字以内）", "タグ2", "タグ3"],
  "reputation_summary": "公開情報を統合した評判サマリー（80文字以内・患者視点）",

  "patient_scores": {{
    "技術力": 0〜100,
    "説明力": 0〜100,
    "清潔感": 0〜100,
    "優しさ": 0〜100,
    "子ども対応": 0〜100,
    "痛みへの配慮": 0〜100,
    "待ち時間": 0〜100
  }},

  "doctor_score": 0〜25,
  "doctor_name": "院長名（不明なら空文字）",
  "doctor_career": "経歴1行（不明なら空文字）",
  "doctor_evidence": ["根拠1（40文字以内）", "根拠2"],
  "doctor_stars": {{
    "専門性": 0〜5,
    "研究実績": 0〜5,
    "患者目線": 0〜5,
    "経験": 0〜5
  }},

  "case_analysis": {{
    "has_cases": true/false,
    "difficult_cases": ["難症例の種類（例: 骨造成, All-on-4）"],
    "parts": ["前歯", "奥歯" など対応部位],
    "techniques": ["GBR", "即日インプラント" など術式]
  }},

  "equipment_score": 0〜20,
  "equipment_evidence": ["根拠1（40文字以内）", "根拠2"],
  "equipment_stars": {{
    "CT": 0〜5,
    "マイクロスコープ": 0〜5,
    "口腔内スキャナー": 0〜5,
    "個室": 0〜5,
    "駐車場": 0〜5,
    "バリアフリー": 0〜5
  }},

  "transparency_score": 0〜15,
  "transparency_evidence": ["根拠1（40文字以内）"],

  "activity_score": 0〜15,
  "activity_evidence": ["根拠1（40文字以内）", "根拠2"],

  "workplace_stars": {{
    "教育制度": 0〜5,
    "働きやすさ": 0〜5,
    "衛生士定着率": 0〜5,
    "スタッフ教育": 0〜5
  }},
  "workplace_quality": "求人から読み取れる職場環境（40文字以内・情報なければ空）",

  "fit_for": ["子ども", "女性", "高齢者", "インプラント", "忙しい人", "歯科恐怖症" などから該当するもの],
  "patient_fit": {{
    "子ども連れ": 0〜5,
    "歯科が怖い人": 0〜5,
    "短時間で済ませたい": 0〜5,
    "自由診療も検討": 0〜5,
    "保険中心": 0〜5
  }},
  "specialty_tags": ["インプラント", "矯正歯科", "小児歯科", "予防歯科", "審美歯科", "個室", "駐車場", "バリアフリー", "キッズルーム" など根拠のあるもののみ（完全一致の単語で。推測での追加は禁止）],
  "not_fit_for": ["夜しか通えない人", "駐車場必須", "急患希望" などの具体的に不向きな患者像],
  "best_patient_profile": "この医院で120%満足する患者像（50文字以内・具体的に）",
  "not_recommended_profile": "この医院をおすすめしない患者像（50文字以内・具体的に）",

  "notable": true または false,
  "notable_reason": "推薦理由1文（なければ空）",
  "catchphrase": "この医院を一言で表すキャッチフレーズ（20文字以内）",

  "ai_summary": "【AI総評】この医院は〜という方に向いています。一方、〜な方には他院も検討をお勧めします。（患者が読む文章・80〜120文字）",
  "referral_to": ["歯医者が怖い人", "小さな子どもがいる人" など、友人に紹介したい患者タイプ（3〜5個・15文字以内）],
  "not_referral_to": ["夜9時以降しか通えない人", "駅近を最優先する人" など、他院を勧める患者タイプ（2〜3個・20文字以内）]
}}"""

        body = json.dumps({
            "model": "gpt-4o-mini",
            "max_tokens": 1500,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {OPENAI_KEY}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as res:
            data = json.loads(res.read().decode("utf-8"))
        raw_r = data["choices"][0]["message"]["content"].strip()
        m = re.search(r'\{.*\}', raw_r, re.DOTALL)
        if m:
            result = json.loads(m.group())
            return result
    except Exception as e:
        pass
    return empty


def calc_total_score(analysis: dict, rating: float, total_rv: int) -> dict:
    """
    v3.0 スコア計算

    口コミ・評判    25点
    院長経歴        25点
    設備・体制      20点
    透明性          15点
    学会・症例・発信 15点
    合計           100点

    + Google評価ボーナス（最大10点補正）
    """
    import math

    rep_s  = min(analysis.get("reputation_score",  0), 25)
    doc_s  = min(analysis.get("doctor_score",       0), 25)
    eq_s   = min(analysis.get("equipment_score",    0), 20)
    tr_s   = min(analysis.get("transparency_score", 0), 15)
    act_s  = min(analysis.get("activity_score",     0), 15)

    base = rep_s + doc_s + eq_s + tr_s + act_s  # 最大100点

    # Google評価ボーナス（口コミが少ない場合も評価を補正）
    google_bonus = 0
    if rating >= 4.5 and total_rv >= 50:
        google_bonus = 8
    elif rating >= 4.3 and total_rv >= 20:
        google_bonus = 5
    elif rating >= 4.0 and total_rv >= 5:
        google_bonus = 2

    total = min(base + google_bonus, 100)

    return {
        "reputation_score":   rep_s,
        "doctor_score":       doc_s,
        "equipment_score":    eq_s,
        "transparency_score": tr_s,
        "activity_score":     act_s,
        "google_bonus":       google_bonus,
        "total_score":        total,
        # 後方互換
        "clinic_score":       min(eq_s + tr_s, 55),
        "current":            min(round(base / 100 * 100), 100),
        "potential":          min(round((doc_s / 25 * 60) + (eq_s / 20 * 40)), 100),
    }


# ─────────────────────────────────────────────
# Google Places API
# ─────────────────────────────────────────────

# 京都市のグリッド範囲（市域が広く山地を多く含むため大阪市よりやや広め。
# 医院は市街地に集中するのでヒットしないグリッド点はAPI1回で済む）
OSAKA_GRID = {
    "lat_min": 34.870,
    "lat_max": 35.120,
    "lng_min": 135.560,
    "lng_max": 135.880,
    "step":    0.008,   # 約880m間隔（半径600mと重複させて漏れを防ぐ）
    "radius":  600,     # Nearby Search 半径（m）
}

def generate_grid_points() -> list:
    """京都市全域のグリッド座標リストを生成"""
    g = OSAKA_GRID
    points = []
    lat = g["lat_min"]
    while lat <= g["lat_max"]:
        lng = g["lng_min"]
        while lng <= g["lng_max"]:
            points.append((round(lat, 4), round(lng, 4)))
            lng += g["step"]
        lat += g["step"]
    return points


def nearby_search(lat: float, lng: float, radius: int = 600) -> list:
    """Nearby Search で指定座標周辺の歯科医院を全件取得"""
    if not GMAPS_KEY:
        return []
    results = []
    url = (
        f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}&radius={radius}&type=dentist"
        f"&language=ja&key={GMAPS_KEY}"
    )
    for page in range(3):
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8"))
            results.extend(data.get("results", []))
            token = data.get("next_page_token")
            if not token:
                break
            time.sleep(2.5)
            url = (
                f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
                f"?pagetoken={token}&key={GMAPS_KEY}"
            )
        except Exception as e:
            print(f"    ⚠️  Nearby Searchエラー: {e}")
            break
    return results


def text_search_clinics(query_word: str, area: str) -> list:
    """Text Search（ジャンル補完用）"""
    if not GMAPS_KEY:
        return []
    query   = urllib.parse.quote(f"{query_word} 歯科 {area}")
    results = []
    url     = (
        f"https://maps.googleapis.com/maps/api/place/textsearch/json"
        f"?query={query}&language=ja&region=jp&key={GMAPS_KEY}"
    )
    for page in range(2):  # 補完なので最大2ページ
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                data = json.loads(r.read().decode("utf-8"))
            results.extend(data.get("results", []))
            token = data.get("next_page_token")
            if not token:
                break
            time.sleep(2.5)
            url = (
                f"https://maps.googleapis.com/maps/api/place/textsearch/json"
                f"?pagetoken={token}&key={GMAPS_KEY}"
            )
        except Exception as e:
            print(f"    ⚠️  検索エラー: {e}")
            break
    return results


def get_place_details(place_id: str) -> dict:
    if not GMAPS_KEY or not place_id:
        return {}
    pid    = urllib.parse.quote(place_id)
    fields = (
        "website,formatted_phone_number,"
        "opening_hours,reviews,rating,user_ratings_total,business_status"
    )
    url = (
        f"https://maps.googleapis.com/maps/api/place/details/json"
        f"?place_id={pid}&fields={fields}&language=ja&key={GMAPS_KEY}"
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            result = json.loads(r.read().decode("utf-8")).get("result", {})
        hours_obj = result.get("opening_hours", {})
        result["weekday_text"] = hours_obj.get("weekday_text", [])
        result["phone"] = result.get("formatted_phone_number") or ""
        return result
    except Exception:
        return {}


# ─────────────────────────────────────────────
# プロフィールページ生成
# ─────────────────────────────────────────────
def build_profile_page(entry: dict):
    try:
        import sys as _sys
        _sys.path.insert(0, str(GENERATOR.parent))
        import blog_generator as bg
        html = bg._build_clinic_profile_html(entry)
        slug = re.sub(r'[\\/:*?"<>|　\s・。、]', '_', entry["name"])[:60]
        out  = CLINIC_DIR / f"{slug}.html"
        CLINIC_DIR.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        return out.name
    except Exception as e:
        return f"スキップ({e})"


# ─────────────────────────────────────────────
# 医院エントリの処理（共通）
# ─────────────────────────────────────────────
def process_place(p: dict, db: dict, today: str, default_genre: str = "一般歯科") -> bool:
    """
    1件の Places 結果をDBに追加・更新する。
    返り値: True=追加/更新, False=スキップ
    """
    place_id = p.get("place_id", "")
    name     = p.get("name", "")

    # 足切りは「医院名なし」と「閉業」だけ
    if not place_id or not name:
        return False
    status = p.get("business_status", "OPERATIONAL")
    if status == "CLOSED_PERMANENTLY":
        return False

    rating   = p.get("rating", 0)
    total_rv = p.get("user_ratings_total", 0)
    address  = p.get("formatted_address", p.get("vicinity", ""))
    geo      = p.get("geometry", {}).get("location", {})
    lat      = geo.get("lat", 0)
    lng      = geo.get("lng", 0)

    existing      = db.get(place_id, {})
    last_analyzed = existing.get("last_analyzed", "")

    # 14日以内にAI分析済みならスキップ（ただし新スキーマ未移行の医院は再分析する）
    if last_analyzed and existing.get("total_score", 0) > 0 and "equipment_stars" in existing:
        try:
            days_ago = (datetime.now() - datetime.strptime(last_analyzed, "%Y-%m-%d")).days
            if days_ago < 14:
                return False
        except Exception:
            pass

    # Place Details
    details  = get_place_details(place_id)
    website  = details.get("website", "") or existing.get("url", "")
    phone    = details.get("phone", "")    or existing.get("phone", "")
    hours    = details.get("weekday_text", []) or existing.get("business_hours", [])
    reviews  = details.get("reviews", [])
    phrases  = extract_phrases_from_reviews(reviews) or existing.get("phrases", [])
    rating   = details.get("rating", rating) or rating
    total_rv = details.get("user_ratings_total", total_rv) or total_rv

    maps_url = (
        f"https://www.google.com/maps/search/?api=1"
        f"&query={urllib.parse.quote(name)}&query_place_id={place_id}"
    )

    # ジャンル保護
    existing_genre = existing.get("genre", "")
    final_genre    = existing_genre if existing_genre in CLEAN_GENRES else default_genre

    # 評判収集 → AI分析
    print(f"    ▶ {name[:22]}（★{rating}・{total_rv}件）", end="  ", flush=True)
    sources  = collect_reputation_sources(name, website, phrases)
    analysis = analyze_reputation_and_expertise(name, final_genre, sources)
    scores   = calc_total_score(analysis, rating, total_rv)

    addr_clean = re.sub(r'^〒\d{3}-\d{4}\s*', '', address)
    addr_clean = re.sub(r'^(京都府|大阪府|兵庫県)', '', addr_clean).strip()

    entry = {
        "place_id":        place_id,
        "name":            name,
        "address":         addr_clean,
        "lat":             lat or existing.get("lat", 0),
        "lng":             lng or existing.get("lng", 0),
        "phone":           phone,
        "url":             website if website and "google.com/maps" not in website else "",
        "google_maps_url": maps_url,
        "rating":          rating,
        "total_reviews":   total_rv,
        "business_hours":  hours,
        "genre":           final_genre,
        # スコア
        "total_score":        scores["total_score"],
        "reputation_score":   scores["reputation_score"],
        "doctor_score":       scores["doctor_score"],
        "equipment_score":    scores["equipment_score"],
        "transparency_score": scores["transparency_score"],
        "activity_score":     scores["activity_score"],
        "google_bonus":       scores["google_bonus"],
        "clinic_score":       scores["clinic_score"],
        "current":            scores["current"],
        "potential":          scores["potential"],
        # 評判
        "reputation_tags":    analysis.get("reputation_tags", []),
        "reputation_summary": analysis.get("reputation_summary", ""),
        "phrases":            phrases,
        "sources_analyzed":   sources.get("sources_count", 0),
        "patient_scores":     analysis.get("patient_scores", {}),
        # 院長
        "doctor_name":     analysis.get("doctor_name")  or existing.get("doctor_name", ""),
        "doctor_career":   analysis.get("doctor_career") or existing.get("doctor_career", ""),
        "doctor_evidence": analysis.get("doctor_evidence", []),
        "doctor_stars":    analysis.get("doctor_stars", {}),
        # 症例
        "case_analysis":   analysis.get("case_analysis", {}),
        # 設備・透明性・活動
        "equipment_stars":       analysis.get("equipment_stars", {}),
        "equipment_evidence":    analysis.get("equipment_evidence", []),
        "transparency_evidence": analysis.get("transparency_evidence", []),
        "activity_evidence":     analysis.get("activity_evidence", []),
        # 職場
        "workplace_stars":   analysis.get("workplace_stars", {}),
        "workplace_quality": analysis.get("workplace_quality", ""),
        # 患者適合
        "fit_for":                 analysis.get("fit_for", []),
        "patient_fit":             analysis.get("patient_fit", {}),
        "specialty_tags":          analysis.get("specialty_tags", []),
        "not_fit_for":             analysis.get("not_fit_for", []),
        "best_patient_profile":    analysis.get("best_patient_profile", ""),
        "not_recommended_profile": analysis.get("not_recommended_profile", ""),
        "referral_to":             analysis.get("referral_to", []),
        "not_referral_to":         analysis.get("not_referral_to", []),
        "ai_summary":              analysis.get("ai_summary", ""),
        # 注目
        "notable":        analysis.get("notable", False) or existing.get("notable", False),
        "notable_reason": analysis.get("notable_reason") or existing.get("notable_reason", ""),
        "catchphrase":    analysis.get("catchphrase")    or existing.get("catchphrase", ""),
        # 管理
        "label":           existing.get("label", "一般枠"),
        "linked_articles": existing.get("linked_articles", []),
        "last_analyzed":   today,
    }
    db[place_id] = entry

    src_mark = f"📡{sources['sources_count']}ソース"
    notable_mark = " ⭐" if entry["notable"] else ""
    print(f"総合{scores['total_score']}点 {src_mark}{notable_mark}")
    time.sleep(0.4)
    return True


# ─────────────────────────────────────────────
# メイン収集処理
# ─────────────────────────────────────────────
def collect(run_phase1: bool = True, run_phase2: bool = True):
    db    = load_db()
    today = datetime.now().strftime("%Y-%m-%d")

    grid_points = generate_grid_points()

    print(f"\n{'='*60}")
    print(f"  京都歯科総研 医院DB構築 v4.0  {today}")
    print(f"  設計思想: 全院網羅（Nearby Search グリッド）+ AI評判生成")
    print(f"  グリッド数: {len(grid_points)}点（間隔{OSAKA_GRID['step']}度・半径{OSAKA_GRID['radius']}m）")
    print(f"  現在のDB  : {len(db)}院")
    print(f"  足切り    : 閉業のみ（評価・口コミ数での除外なし）")
    print(f"{'='*60}\n")

    total_new = 0

    # ══ Phase 1: Nearby Search グリッド ══════════════════════
    if run_phase1:
        print(f"【Phase 1】Nearby Search グリッド — 京都市全域を座標で網羅")
        print(f"  目標: 検索順位・SEOに依存せず存在する全医院を取得\n")

        for i, (lat, lng) in enumerate(grid_points, 1):
            print(f"  🔲 [{i:3d}/{len(grid_points)}] ({lat}, {lng})", end=" ", flush=True)
            places = nearby_search(lat, lng, OSAKA_GRID["radius"])

            # 新規のみカウント（既存はスキップ分）
            new_in_grid = [p for p in places if p.get("place_id") not in db]
            print(f"→ {len(places)}件（新規: {len(new_in_grid)}院）")

            for p in places:
                added = process_place(p, db, today, "一般歯科")
                if added:
                    total_new += 1

            # 20グリッドごとに保存
            if i % 20 == 0:
                save_db(db)
                print(f"\n  💾 {i}グリッド完了・DB保存: {len(db)}院\n")

        save_db(db)
        print(f"\n  ✅ Phase 1 完了: DB {len(db)}院（新規/更新 {total_new}院）\n")

    # ══ Phase 2: Text Search 補完 ════════════════════════════
    if run_phase2:
        print(f"【Phase 2】Text Search 補完 — ジャンル別で漏れを補完")
        # Phase1で取れない専門院をジャンル × 主要エリアで補完
        supplement_queries = [
            "インプラント専門", "矯正専門", "根管治療専門",
            "審美歯科", "訪問歯科", "障害者歯科",
        ]
        major_areas = ["京都市中京区", "京都市下京区", "京都市伏見区",
                       "京都市右京区", "京都市左京区", "京都市山科区"]

        phase2_new = 0
        for q in supplement_queries:
            for area in major_areas:
                places = text_search_clinics(q, area)
                for p in places:
                    if p.get("place_id") not in db:
                        added = process_place(p, db, today, q.replace("専門", ""))
                        if added:
                            phase2_new += 1

        save_db(db)
        total_new += phase2_new
        print(f"\n  ✅ Phase 2 完了: 追加 {phase2_new}院\n")

    # 最終レポート
    all_c = list(db.values())
    print(f"\n{'='*60}")
    print(f"  ✅ 収集完了 v4.0")
    print(f"  DB総院数      : {len(db)}院")
    print(f"  新規/更新     : {total_new}院")
    print(f"  AI分析済み    : {sum(1 for c in all_c if c.get('total_score',0)>0)}院")
    print(f"  AI総評あり    : {sum(1 for c in all_c if c.get('ai_summary'))}院")
    print(f"  評判タグあり  : {sum(1 for c in all_c if c.get('reputation_tags'))}院")
    print(f"  電話番号      : {sum(1 for c in all_c if c.get('phone'))}院")
    print(f"  ウェブサイト  : {sum(1 for c in all_c if c.get('url'))}院")
    print(f"  notable院     : {sum(1 for c in all_c if c.get('notable'))}院")
    grid_pts = generate_grid_points()
    print(f"  グリッド数    : {len(grid_pts)}点（推定カバレッジ: 京都市全域）")
    print(f"{'='*60}")

    try:
        import subprocess
        subprocess.run([
            "osascript", "-e",
            f'display notification "DB:{len(db)}院 新規:{total_new}院" '
            f'with title "京都歯科総研 DB更新完了 v4.0" sound name "Glass"'
        ], check=False)
    except Exception:
        pass


if __name__ == "__main__":
    if not GMAPS_KEY:
        print("❌ GOOGLE_MAPS_API_KEY が未設定です")
        sys.exit(1)

    phase1 = "--phase2" not in sys.argv
    phase2 = "--phase1" not in sys.argv
    collect(run_phase1=phase1, run_phase2=phase2)
