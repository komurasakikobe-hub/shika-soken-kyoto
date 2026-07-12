"use strict";
/* =========================================================
   京都歯科総研 — 京都市 歯科医院データランキング
   「質問に答えて最後に結果を出す」ウィザードから、
   「条件を選ぶたびに順位が更新される」リアルタイムランキングへ変更（2026-07-08）。
   ========================================================= */

const $ = id => document.getElementById(id);

// 計測（assets/odr-track.jsが読み込まれていない環境でも落ちないよう防御）
const odrTrack = (name, params) => {
  if (typeof window.odrTrack === "function") window.odrTrack(name, params);
};

// ── エリア定義（京都市11区・住所の区名で一致） ──────
const AREA_KEYWORDS = {
  "伏見区（伏見桃山・丹波橋）": ["京都市伏見区", "伏見区"],
  "中京区（京都市役所前・烏丸御池）": ["京都市中京区", "中京区"],
  "左京区（元田中・茶山）": ["京都市左京区", "左京区"],
  "右京区（西京極・西院）": ["京都市右京区", "右京区"],
  "下京区（四条・京都）": ["京都市下京区", "下京区"],
  "山科区（椥辻・京阪山科）": ["京都市山科区", "山科区"],
  "西京区（桂・上桂）": ["京都市西京区", "西京区"],
  "北区（北大路・北野白梅町）": ["京都市北区", "北区"],
  "南区（西大路・東寺）": ["京都市南区", "南区"],
  "上京区（北野白梅町・今出川）": ["京都市上京区", "上京区"],
  "東山区（祇園四条・東福寺）": ["京都市東山区", "東山区"],
};
const WARD_LIST = [{ key: "all", label: "京都市全体" }].concat(
  Object.keys(AREA_KEYWORDS).map(k => ({ key: k, label: k.replace(/（.*）/, "") }))
);

// ── エリア一致判定（住所＋最寄駅名。単一市は最寄駅名の完全一致で判定） ──────
const AREA_MATCH_BY_STATION = false;
function matchesArea(clinic, kws) {
  if (!kws) return false;
  const stn = (clinic.nearest_station && clinic.nearest_station.name) || "";
  if (AREA_MATCH_BY_STATION) return kws.some(kw => stn === kw);
  const addr = clinic.address || "";
  return kws.some(kw => addr.includes(kw) || (stn && stn === kw));
}
function regionLabelOf(clinic) {
  for (const key in AREA_KEYWORDS) {
    if (matchesArea(clinic, AREA_KEYWORDS[key])) return key.replace(/（.*）/, "");
  }
  return "";
}

// ── 悩み・治療 ─────────────────────────────────────────────
const TREATMENT_MAP = {
  "歯が痛い":       { genres: [], evidence: ["虫歯", "痛み", "急患"] },
  "詰め物が取れた": { genres: [], evidence: ["詰め物", "被せ物"] },
  "親知らず":       { genres: ["親知らず"], evidence: ["親知らず"] },
  "歯周病":         { genres: ["歯周病"], evidence: ["歯周病", "歯茎", "歯ぐき"] },
  "予防・定期検診": { genres: ["予防歯科"], evidence: ["予防", "定期検診", "クリーニング"] },
  "ホワイトニング": { genres: ["ホワイトニング", "審美歯科"], evidence: ["ホワイトニング"] },
  "セラミック":     { genres: ["審美歯科"], evidence: ["セラミック"] },
  "歯列矯正":       { genres: ["矯正"], evidence: ["矯正"] },
  "インプラント":   { genres: ["インプラント"], evidence: ["インプラント"] },
  "入れ歯":         { genres: ["入れ歯"], evidence: ["入れ歯", "義歯"] },
  "子どもの歯":     { genres: ["小児歯科"], evidence: ["小児", "子ども", "こども"] },
  "歯医者が苦手":   { genres: [], evidence: ["無痛", "笑気", "鎮静", "カウンセリング"] },
};
const TREATMENT_LIST = Object.keys(TREATMENT_MAP);

// ── 希望条件 ───────────────────────────────────────────────
const CONDITION_MAP = {
  "駅から近い":           { station: 500 },
  "土日診療":             { tags: ["土日診療"] },
  "夜間診療":             { tags: ["夜間診療"] },
  "駐車場あり":           { tags: ["駐車場"], eq: "駐車場" },
  "個室あり":             { tags: ["個室"], eq: "個室" },
  "バリアフリー":         { tags: ["バリアフリー"], eq: "バリアフリー" },
  "説明を重視":           { ps: "説明力" },
  "痛みに配慮":           { ps: "痛みへの配慮" },
  "子ども連れに配慮":     { tags: ["キッズスペース", "小児歯科"], ps: "子ども対応" },
  "公式サイト情報が充実": { deepFetched: true },
};
const CONDITION_LIST = Object.keys(CONDITION_MAP);

// ── 状態管理（URLクエリと同期） ─────────────────────────────
// 2026-07-09：悩み・治療も複数選択可に変更（treatment→treatments）
const filters = {
  ward: "all",
  treatments: new Set(),
  conditions: new Set(),
};

let clinicDB = {};
let clinicSlugMap = {};
let allClinics = [];
let isRestoringHistory = false;

// ── データ読み込み ───────────────────────────────────────────
async function loadDB() {
  if (Object.keys(clinicDB).length > 0) return clinicDB;
  const paths = ["../../clinic_db.json", "/clinic_db.json", "../clinic_db.json", "clinic_db.json"];
  for (const u of paths) {
    try {
      const res = await fetch(u);
      if (res.ok) {
        clinicDB = await res.json();
        allClinics = Object.entries(clinicDB)
          .map(([pid, c]) => ({ ...c, place_id: c.place_id || pid }))
          .filter(c => !c.q_excluded && c.name);
        return clinicDB;
      }
    } catch (e) { /* try next path */ }
  }
  return {};
}

async function loadSlugMap() {
  if (Object.keys(clinicSlugMap).length > 0) return clinicSlugMap;
  const paths = ["../../clinic_slugs.json", "/clinic_slugs.json", "../clinic_slugs.json", "clinic_slugs.json"];
  for (const u of paths) {
    try {
      const res = await fetch(u);
      if (res.ok) {
        const data = await res.json();
        if (data && Object.keys(data).length > 0) { clinicSlugMap = data; return clinicSlugMap; }
      }
    } catch (e) { /* try next path */ }
  }
  return clinicSlugMap;
}

function clinicUrl(clinic) {
  const fallback = "../clinics/" + encodeURIComponent(clinic.name || "") + ".html";
  return (clinic.place_id && clinicSlugMap[clinic.place_id])
    ? "../clinics/" + clinicSlugMap[clinic.place_id] + ".html"
    : fallback;
}

// ── スコアリング（既存calcMatchScoreの設計を踏襲。ward/treatmentで
//    事前に絞り込んだプールに対し、希望条件をスコア加点として反映する） ──
function hasTag(clinic, keyword) {
  const tags = [...(clinic.site_features || []), ...(clinic.specialty_tags || [])];
  return tags.some(t => t.includes(keyword));
}
function qualityProxy100(clinic) {
  const r = clinic.rating || 0;
  const rv = clinic.total_reviews || 0;
  if (!r) return 40;
  return Math.max(0, Math.min(100, (r - 3.0) * 22 + Math.log(rv + 1) * 6));
}

function calcRankScore(clinic) {
  const ps = clinic.patient_scores || {};
  const evText = ((clinic.equipment_evidence || []).join(" ") +
                  (clinic.doctor_evidence || []).join(" ") +
                  (clinic.specialty_evidence || []).join(" ") +
                  (clinic.catchphrase || "") + (clinic.ai_summary || "")).toLowerCase();
  let score = 0;
  const matched = [];

  // ベース：口コミ評価（0-100換算）
  const r = clinic.rating || 0;
  const rv = clinic.total_reviews || 0;
  const reviewScore = Math.max(0, Math.min(100, ((r - 3) / 2) * 100 + Math.min(20, Math.log10(rv + 1) * 10) - 10));
  score += reviewScore * 0.28;

  // データ充実度（患者スコア平均。無ければ口コミからのフォールバック）
  const psVals = Object.values(ps).filter(v => typeof v === "number");
  const qualityAvg = psVals.length ? psVals.reduce((a, b) => a + b, 0) / psVals.length : qualityProxy100(clinic);
  score += qualityAvg * 0.32;

  // 治療ジャンル一致（複数選択可。選んだ悩みごとに一致を加点）
  filters.treatments.forEach(tKey => {
    const t = TREATMENT_MAP[tKey];
    if (!t) return;
    let hit = t.genres.includes(clinic.genre);
    if (!hit) hit = t.evidence.some(w => evText.includes(w.toLowerCase()));
    if (hit) { score += 22; matched.push(tKey); }
  });

  // 希望条件（複数）。
  // 注意（2026-07-08 発見・修正）：以前は「条件に合えば加点」だけで、
  // 「データ上、明確に条件を満たさない」場合も0点（中立）扱いだった。
  // そのため、全体的なデータが極端に厚い医院（口コミ・患者スコアが軒並み
  // 高い医院）が、選んだ条件を実際には満たしていなくても1位のまま
  // 動かない問題が起きていた（例：駐車場0院なのに「駐車場あり」を
  // 選んでも1位のまま）。条件を「確実に満たす／確実に満たさない／
  // データなし（中立）」の3値で判定し、満たさない場合は減点する。
  const es = clinic.equipment_stars || {};
  filters.conditions.forEach(c => {
    const cond = CONDITION_MAP[c];
    let state = "unknown"; // "yes" | "no" | "unknown"

    if (cond.tags) {
      const tagHit = cond.tags.some(k => hasTag(clinic, k));
      if (tagHit) state = "yes";
    }
    if (state === "unknown" && cond.station != null) {
      // 2026-07-08：座標ベースの最寄駅データ（Nominatimでジオコーディング済み）
      // を使い、直線距離で「駅から近い」を判定する。以前はspecialty_tagsの
      // 自由文字列頼みで全2,039院中47院しか判定できなかったが、座標データの
      // 整備により2,038院で判定可能になった。
      const dist = clinic.nearest_station?.straight_distance_m;
      if (dist != null) state = dist <= cond.station ? "yes" : "no";
    }
    if (state === "unknown" && cond.eq && es[cond.eq] != null) {
      state = es[cond.eq] >= 3 ? "yes" : "no";
    }
    if (state === "unknown" && cond.ps) {
      const raw = ps[cond.ps];
      if (raw != null) state = raw >= 60 ? "yes" : "no";
    }
    if (state === "unknown" && cond.deepFetched) {
      state = clinic.deep_fetched ? "yes" : "no";
    }

    if (state === "yes") { score += 16; matched.push(c); }
    else if (state === "no") { score -= 16; }
    // unknown（データなし）は中立のまま加減点しない
  });

  // 注目医院ボーナス（軽め。優越感を煽らないためスコアのみで表示上は特別扱いしない）
  if (clinic.notable) score += 4;

  return { score: Math.round(score * 10) / 10, matched };
}

function isWardMatch(clinic, wardKey) {
  if (!wardKey || wardKey === "all") return true;
  const kws = AREA_KEYWORDS[wardKey];
  if (!kws) return true;
  return matchesArea(clinic, kws);
}

// ── フィルタ適用後のプールを取得（地域・治療は絞り込み、
//    該当が極端に少ない場合は全体にフォールバックする） ──
function getFilteredPool() {
  let pool = allClinics;

  if (filters.ward && filters.ward !== "all") {
    const byWard = pool.filter(c => isWardMatch(c, filters.ward));
    if (byWard.length >= 3) pool = byWard;
  }

  if (filters.treatments.size) {
    const selected = Array.from(filters.treatments).map(k => TREATMENT_MAP[k]).filter(Boolean);
    const byTreatment = pool.filter(c => {
      const evText = ((c.equipment_evidence || []).join(" ") +
                      (c.doctor_evidence || []).join(" ") +
                      (c.specialty_evidence || []).join(" ") +
                      (c.catchphrase || "") + (c.ai_summary || "")).toLowerCase();
      return selected.some(t =>
        t.genres.includes(c.genre) || t.evidence.some(w => evText.includes(w.toLowerCase())));
    });
    if (byTreatment.length >= 3) pool = byTreatment;
  }

  return pool;
}

// アクセス表示テキスト（患者目線・2026-07-11 全面改修）。
// 駅が徒歩圏（1.2km以内）なら従来どおり駅基準。徒歩圏に駅がない医院は
// 「徒歩144分」のような無意味な換算をやめ、最寄りバス停→高速IC→車の順で
// 患者が実際に使う目安に切り替える（データはbuild_access_info.pyが付与）。
function formatStationText(ns, clinic) {
  const c = clinic || {};
  if (ns && ns.official_walk_minutes != null) {
    return `${ns.name}駅から徒歩${ns.official_walk_minutes}分（公式サイト）`;
  }
  const d = ns ? ns.straight_distance_m : null;
  if (d != null && d <= 600) {
    return `${ns.name}駅から約${d}m`;
  }
  if (d != null && d <= 1200) {
    return `${ns.name}駅から徒歩${ns.estimated_walk_minutes_min}〜${ns.estimated_walk_minutes_max}分相当の目安`;
  }
  // ここから徒歩圏に駅がない医院（患者が実際に使う目安に切替）
  const bus = c.nearest_bus_stop;
  if (bus && bus.distance_m != null && bus.distance_m <= 500) {
    const min = Math.max(1, Math.ceil(bus.distance_m / 80));
    return `バス停「${bus.name}」から徒歩約${min}分の目安`;
  }
  const ic = c.nearest_ic;
  if (ic && ic.distance_m != null && ic.distance_m <= 8000) {
    const min = Math.max(1, Math.ceil(ic.distance_m / 500)); // 実勢約30km/hで換算
    return `${ic.name}から車で約${min}分の目安`;
  }
  if (ns && d != null) {
    const min = Math.max(1, Math.ceil(d / 500));
    return `${ns.name}駅から車で約${min}分の目安`;
  }
  return "";
}

// 口コミ傾向：patient_scores（口コミ由来の項目別スコア）を、断定しない
// 「傾向」の言葉に変換して表示する（2026-07-08 実装。星の平均より実用的、
// かつ「高評価」と断定しない方針）。
const TREND_PHRASES = [
  ["説明力",       75, "説明が分かりやすいという声"],
  ["痛みへの配慮", 75, "痛みへの配慮に関する肯定的な内容"],
  ["優しさ",       80, "スタッフ対応への肯定的な内容"],
  ["清潔感",       80, "院内の清潔さに関する言及"],
  ["子ども対応",   75, "子どもへの対応に関する言及"],
];
function reviewTrendsHTML(clinic) {
  const ps = clinic.patient_scores || {};
  const items = [];
  for (const [key, min, phrase] of TREND_PHRASES) {
    if (typeof ps[key] === "number" && ps[key] >= min) items.push(phrase);
    if (items.length >= 3) break;
  }
  if (!items.length) return "";
  return `<div class="rk-trend">
    <p class="rk-trend-label">口コミで確認された傾向</p>
    <ul class="rk-trend-list">${items.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
  </div>`;
}

// ═══ AI ANALYSIS「＋根拠」パネル（2026-07-11新設） ═══════════════
// evidence_grounding.py のJS移植版。ロジックを変更する場合は必ずPython側と両方直すこと。
const EV_TOPICS = ["ホワイトニング","インプラント","矯正","予防","小児","子ども","子供","キッズ",
  "審美","セラミック","入れ歯","義歯","親知らず","歯周病","クリーニング",
  "猫","犬","エキゾチック","うさぎ","鳥","手術","腫瘍","皮膚","眼科"];
const EV_ATTRS = ["女性","高齢","バリアフリー","個室","ベビーカー","託児",
  "丁寧","優しい","痛くない","痛みに配慮","清潔"];
const EV_SYNONYMS = {
  "子ども":["子ども","子供","小児","キッズ","お子さま","お子様"],
  "子供":["子ども","子供","小児","キッズ","お子さま","お子様"],
  "小児":["子ども","子供","小児","キッズ","お子さま","お子様"],
  "キッズ":["子ども","子供","小児","キッズ","お子さま","お子様"],
  "矯正":["矯正","インビザライン","マウスピース"],
  "入れ歯":["入れ歯","義歯","デンチャー"],
  "義歯":["入れ歯","義歯","デンチャー"],
  "予防":["予防","クリーニング","定期検診","メンテナンス"],
};
const EV_SPEED_RE = /短期間|短時間|スピーディ|すぐに|即日|早く終|早かった/;
const EV_CLAUSE_SPLIT_RE = /[。、！？\n]|一方で?|ただし|しかし|なお|また|ものの|反面/;
const EV_NEG_CLAUSE_RE = /他院|不向き|向いてい?ま?せ?ん|向かない|おすすめしません|お勧めしません|適しません|検討をお勧め|検討をおすすめ|難しい|できません|対応していません|注意が必要|には合わない|は避け/;
const EV_SUMMARY_TERMS = [...EV_TOPICS, ...EV_ATTRS,
  "夜","夜間","土日","週末","駅","駐車","車で","急","短期間","短時間",
  "怖","不安","痛み","安心","丁寧","説明","清潔","通いやすい","アクセス"];

function evScanSummaryClaims(text, c) {
  if (!text) return [];
  const out = [], seen = new Set();
  for (const seg of String(text).split(EV_CLAUSE_SPLIT_RE)) {
    const clause = (seg || "").trim();
    if (!clause) continue;
    const negative = EV_NEG_CLAUSE_RE.test(clause);
    for (const term of EV_SUMMARY_TERMS) {
      if (clause.includes(term)) {
        const [verdict, basis] = evGroundClaim(term, c, negative);
        const key = term + "|" + verdict + "|" + negative;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ clause, term, verdict, basis, negative });
      }
    }
  }
  return out;
}

function evLatestClosing(c) {
  const lines = Array.isArray(c.business_hours) ? c.business_hours : [];
  if (!lines.length) return null;
  let latest = null;
  for (const line of lines) {
    for (const m of line.matchAll(/～\s*(\d{1,2})時(\d{2})?/g)) {
      const t = parseInt(m[1], 10) * 60 + parseInt(m[2] || "0", 10);
      if (latest === null || t > latest) latest = t;
    }
  }
  return latest;
}
const EV_NIGHT_SIGNAL_RE = /夜間|深夜|24時間|２４時間|救急|時間外|ナイト|エマージェンシー/;
function evNightSignal(c) {
  // 医院名が夜間/救急業態を示す場合、診療時間データより優先（Python版と同一ロジック）
  return EV_NIGHT_SIGNAL_RE.test(c.name || "");
}
function evEvening(c) {
  if (evNightSignal(c)) return true;
  const latest = evLatestClosing(c);
  if (latest === null) return null;
  if (latest >= 19 * 60 + 30) return true;
  if (latest <= 18 * 60) return false;
  return null;
}
function evWeekend(c) {
  const lines = Array.isArray(c.business_hours) ? c.business_hours : [];
  if (!lines.length) return null;
  for (const line of lines) {
    if ((line.startsWith("土曜日") || line.startsWith("日曜日")) &&
        !line.includes("定休日") && /\d{1,2}時/.test(line)) return true;
  }
  return false;
}
function evParking(c) {
  const stars = c.equipment_stars || {};
  if ((stars["駐車場"] || 0) > 0) return true;
  const s = [...(c.site_features || []), ...(c.equipment_evidence || [])].join("／");
  return s.includes("駐車") ? true : null;
}
function evStationWalk(c) {
  const st = c.nearest_station || {};
  return (st.estimated_walk_minutes_min === undefined || st.estimated_walk_minutes_min === null)
    ? null : st.estimated_walk_minutes_min;
}
function evCorpus(c) {
  const parts = [
    ...(c.phrases || []), ...(c.reputation_tags || []), ...(c.specialty_tags || []),
    ...(c.focus_treatments || []), ...(c.site_features || []),
    ...(c.equipment_evidence || []), ...(c.qualifications || []),
  ];
  for (const k of ["reputation_summary", "philosophy", "catchphrase", "doctor_career"]) {
    if (c[k]) parts.push(String(c[k]));
  }
  return parts.join("／");
}
function evGroundClaim(claim, c, negative) {
  const corpus = evCorpus(c);
  if (claim.includes("夜")) {
    const ev = evEvening(c);
    if (ev === null) {
      const latest = evLatestClosing(c);
      if (latest === null) return ["inferred", "診療時間の公開情報が十分でないため、傾向からのAI推定です"];
      return ["inferred", `最終受付が${Math.floor(latest / 60)}時台のため夜間の解釈は断定できず、AIが推定しています`];
    }
    if (negative) return !ev ? ["grounded", "診療時間より（夜間帯の診療なし）"]
                             : ["contradicted", "診療時間では夜間帯の診療あり"];
    return ev ? ["grounded", "診療時間より（夜間帯の診療あり）"]
              : ["contradicted", "診療時間では夜間帯の診療なし"];
  }
  if (claim.includes("土日") || claim.includes("週末") || claim.includes("休日")) {
    const wk = evWeekend(c);
    if (wk === null) return ["inferred", "診療時間の公開情報が十分でないため、傾向からのAI推定です"];
    if (negative) return !wk ? ["grounded", "診療時間より（土日の診療なし）"]
                             : ["contradicted", "診療時間では土日診療あり"];
    return wk ? ["grounded", "診療時間より（土日の診療あり）"]
              : ["contradicted", "診療時間では土日の診療なし"];
  }
  if (claim.includes("駅")) {
    const walk = evStationWalk(c);
    if (walk === null) return ["inferred", "最寄駅の情報が十分でないため、傾向からのAI推定です"];
    if (negative) return walk >= 12 ? ["grounded", `最寄駅から徒歩約${walk}分〜（直線距離からの推計）`]
                                    : ["contradicted", `最寄駅から徒歩約${walk}分〜と近い`];
    return walk <= 8 ? ["grounded", `最寄駅から徒歩約${walk}分〜（直線距離からの推計）`]
                     : ["inferred", `最寄駅から徒歩約${walk}分〜（AIによる推定）`];
  }
  if (claim.includes("駐車") || claim.includes("車で")) {
    if (evParking(c)) return negative ? ["contradicted", "駐車場ありの記載を確認"]
                                      : ["grounded", "公式サイト等で駐車場を確認"];
    return ["inferred", "駐車場の公開情報が確認できないため、傾向からのAI推定です"];
  }
  if (/急|短期間|短時間|すぐ/.test(claim)) {
    const m = corpus.match(EV_SPEED_RE);
    if (m && negative) return ["contradicted", `口コミに「${m[0]}」等の肯定的な記述あり`];
    if (m) return ["grounded", srcReason(c, m[0])];
    return ["inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"];
  }
  const negatedTopic = claim.includes("以外") || claim.includes("よりも");
  for (const kw of EV_TOPICS) {
    if (claim.includes(kw)) {
      if (negatedTopic) return ["inferred", "表現の解釈が分かれるため、断定せずAIが推定しています"];
      const hit = (EV_SYNONYMS[kw] || [kw]).find(s => corpus.includes(s));
      if (hit) return negative ? ["contradicted", `口コミ・公式サイトに「${hit}」の肯定的な記述あり`]
                               : ["grounded", srcReason(c, hit)];
      return ["inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"];
    }
  }
  for (const kw of EV_ATTRS) {
    if (claim.includes(kw)) {
      if (corpus.includes(kw)) return ["grounded", srcReason(c, kw)];
      return ["inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"];
    }
  }
  const ps = c.patient_scores || {};
  if (/怖|不安|痛み/.test(claim)) {
    const score = ps["痛みへの配慮"] || ps["優しさ"];
    if (score && score >= 75) return ["grounded", `口コミ全体を分析した『痛みへの配慮・優しさ』スコア ${score}／100 にもとづく傾向です`];
    return ["inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"];
  }
  const skip = ["したい", "希望", "重視", "中心", "検討", "通え", "都合", "治療", "診療", "対応", "な人", "たい人"];
  for (const m of claim.matchAll(/[ぁ-んァ-ヶ一-龠a-zA-Z]{2,}/g)) {
    const token = m[0];
    if (skip.includes(token)) continue;
    if (corpus.includes(token)) return ["grounded", srcReason(c, token)];
  }
  return ["inferred", "公開情報に個別の記載はありませんが、分析全体からAIが総合的に判断した見立てです"];
}

function srcReason(c, hit){
  const n = c.total_reviews || 0;
  if (n >= 20) return `口コミ${n}件と公式サイトを分析し、「${hit}」への言及を確認しています`;
  if (n > 0)   return `口コミ${n}件と公式サイトの記載から「${hit}」を確認しています`;
  return `公式サイトと口コミの記載から「${hit}」を確認しています`;
}

function evidencePanelHTML(c) {
  const blocks = [];
  // 0) 分析文の主張ごとの根拠（最重要）
  const claims = evScanSummaryClaims(c.ai_summary || "", c);
  if (claims.length) {
    let rows = "";
    for (const x of claims) {
      const badge = x.verdict === "grounded" ? '<span class="rk-ev-badge ok">根拠あり</span>'
        : x.verdict === "contradicted" ? '<span class="rk-ev-badge bad">要確認</span>'
        : '<span class="rk-ev-badge guess">AIによる推定</span>';
      const ctx = x.negative ? "（注意点として）" : "";
      rows += `<li><span class="rk-ev-term">「${esc(x.term)}」${ctx}</span>${badge}<span class="rk-ev-basis">${esc(x.basis)}</span></li>`;
    }
    blocks.push(["この分析文が何にもとづくか",
      `<p class="rk-ev-summary">${esc(c.ai_summary || "")}</p><ul class="rk-ev-list">${rows}</ul>`]);
  }
  const tags = c.reputation_tags || [];
  const phrases = (c.phrases || []).slice(0, 3);
  if (tags.length || phrases.length) {
    let inner = "";
    if (tags.length) inner += `<p class="rk-ev-line"><span class="rk-ev-k">口コミ分析で抽出されたタグ</span>${tags.map(t => `<span class="rk-ev-tag">${esc(t)}</span>`).join("")}</p>`;
    if (phrases.length) inner += `<p class="rk-ev-k">実際の口コミからの引用</p>` +
      phrases.map(p => `<blockquote class="rk-ev-quote">「${esc(p)}」</blockquote>`).join("");
    const meta = [];
    if (c.total_reviews) meta.push(`口コミ${c.total_reviews}件を分析`);
    if (c.sources_analyzed) meta.push(`解析ソース${c.sources_analyzed}種類`);
    if (c.last_analyzed) meta.push(`分析日 ${esc(String(c.last_analyzed))}`);
    if (meta.length) inner += `<p class="rk-ev-meta">${meta.join(" ・ ")}</p>`;
    blocks.push(["口コミからの根拠", inner]);
  }
  if (c.deep_fetched) {
    const parts = [];
    if ((c.focus_treatments || []).length) parts.push("注力分野: " + c.focus_treatments.map(esc).join("・"));
    if ((c.equipment_evidence || []).length) parts.push("設備の記載: " + c.equipment_evidence.map(esc).join("・"));
    if ((c.site_features || []).length) parts.push("サイト記載の特徴: " + c.site_features.map(esc).join("・"));
    if (parts.length) blocks.push(["公式サイトからの根拠", parts.map(p => `<p class="rk-ev-line">${p}</p>`).join("")]);
  }
  const facts = [];
  const evn = evEvening(c), latest = evLatestClosing(c);
  if (evn === true) facts.push(latest !== null
    ? `夜間帯の診療あり（最終 ${Math.floor(latest / 60)}時${String(latest % 60).padStart(2, "0")}分まで）`
    : "夜間・救急の診療あり（医院名・区分に基づく）");
  else if (evn === false) facts.push("夜間帯の診療なし（18時までに終了）");
  const wk = evWeekend(c);
  if (wk === true) facts.push("土日いずれかの診療あり");
  else if (wk === false) facts.push("土日の診療なし");
  if (evParking(c)) facts.push("駐車場あり");
  const walk = evStationWalk(c);
  if (walk !== null) facts.push(`最寄駅から徒歩約${walk}分〜（直線距離からの推計）`);
  if (facts.length) blocks.push(["診療時間・立地からの事実", facts.map(f => `<p class="rk-ev-line">${esc(f)}</p>`).join("")]);
  let rows = "";
  for (const [kind, label] of [["fit_for", "向いている"], ["not_fit_for", "注意"]]) {
    for (const item of (c[kind] || [])) {
      const [verdict, basis] = evGroundClaim(item, c, kind === "not_fit_for");
      if (verdict !== "grounded") continue;  // 根拠のないAI推定・矛盾は出さない
      rows += `<li><span class="rk-ev-kind">${label}</span>「${esc(item)}」<span class="rk-ev-badge ok">根拠あり</span><span class="rk-ev-basis">${esc(basis)}</span></li>`;
    }
  }
  if (rows) blocks.push(["「向いている方・注意点」の判定内訳", `<ul class="rk-ev-list">${rows}</ul>`]);
  if (!blocks.length) return "";
  const body = blocks.map(([t, inner]) => `<div class="rk-ev-block"><p class="rk-ev-h">${t}</p>${inner}</div>`).join("");
  const note = '<p class="rk-ev-note">「根拠あり」は口コミ・公式サイト・診療時間等の公開データに対応する記述が確認できたもの、「AIによる推定」は直接の記述がなくAIが総合的に推測したものです。本分析は公開情報に基づく意見・論評であり、医療上の判断や治療結果を保証するものではありません。</p>';
  return `<button type="button" class="rk-ev-toggle" aria-expanded="false">＋根拠を見る</button><div class="rk-ev-panel" hidden>${body}${note}</div>`;
}

document.addEventListener("click", ev => {
  const b = ev.target.closest(".rk-ev-toggle");
  if (!b) return;
  const p = b.nextElementSibling;
  const open = b.getAttribute("aria-expanded") === "true";
  b.setAttribute("aria-expanded", open ? "false" : "true");
  b.textContent = open ? "＋根拠を見る" : "－根拠を閉じる";
  if (p) p.hidden = open;
});

// 情報確認度：公開情報がどれだけ確認できたか（医院の優劣ではない）。
// 情報が薄い医院は「悪い」ではなく「判断材料が少ない」と表示する。
// この区別は医院側への情報整備提案（営業）にもそのまま使える。
function infoLevel(clinic) {
  let n = 0;
  if (clinic.url) n++;
  if (clinic.deep_fetched) n++;
  if ((clinic.total_reviews || 0) > 0) n++;
  if (clinic.patient_scores && Object.values(clinic.patient_scores).some(v => v > 0)) n++;
  if (clinic.equipment_stars && Object.values(clinic.equipment_stars).some(v => v > 0)) n++;
  if ((clinic.specialty_tags || []).length || (clinic.site_features || []).length) n++;
  if (clinic.business_hours && clinic.business_hours.length) n++;
  if (n >= 6) return { label: "公開情報：充実", cls: "hi" };
  if (n >= 4) return { label: "公開情報：標準", cls: "mid" };
  return { label: "公開情報：少なめ", cls: "low" };
}

// ── 比較機能 ─────────────────────────────────────────────
const compareSet = new Map(); // pid -> clinic
const COMPARE_MAX = 3;

function toggleCompare(clinic) {
  const pid = clinic.place_id || "";
  if (compareSet.has(pid)) {
    compareSet.delete(pid);
  } else {
    if (compareSet.size >= COMPARE_MAX) return;
    compareSet.set(pid, clinic);
    odrTrack("compare_add", { clinic_name: clinic.name || "" });
  }
  renderCompareTray();
  document.querySelectorAll(".rk-compare-toggle").forEach(btn => {
    if (btn.dataset.pid !== pid) return;
    btn.textContent = compareSet.has(pid) ? "比較リストから外す" : "比較に追加";
    btn.classList.toggle("on", compareSet.has(pid));
  });
}

function renderCompareTray() {
  const tray = $("compareTray");
  const chips = $("compareChips");
  if (!tray || !chips) return;
  if (compareSet.size === 0) { tray.hidden = true; return; }
  tray.hidden = false;
  chips.innerHTML = Array.from(compareSet.values()).map(c =>
    `<span class="rk-compare-chip">${esc(c.name || "")}<button type="button" data-pid="${esc(c.place_id || "")}" aria-label="外す">×</button></span>`
  ).join("");
  chips.querySelectorAll("button").forEach(btn => {
    btn.addEventListener("click", () => {
      const c = compareSet.get(btn.dataset.pid);
      if (c) toggleCompare(c);
    });
  });
}

function compareValue(c, kind) {
  const ns = c.nearest_station;
  const tags = [...(c.site_features || []), ...(c.specialty_tags || [])];
  const es = c.equipment_stars || {};
  switch (kind) {
    case "station": return ns ? `${ns.name}駅` : "—";
    case "dist": return formatStationText(ns, c) || "—";
    case "weekend": {
      const sat = tags.some(t => t.includes("土日診療") || t.includes("土曜"));
      const night = tags.some(t => t.includes("夜間診療"));
      const parts = [];
      if (sat) parts.push("土日案内あり");
      if (night) parts.push("夜間案内あり");
      return parts.length ? parts.join("・") : "記載なし";
    }
    case "parking": return es["駐車場"] >= 3 || tags.some(t => t.includes("駐車場")) ? "案内あり" : "記載なし";
    case "private": return es["個室"] >= 3 || tags.some(t => t.includes("個室")) ? "案内あり" : "記載なし";
    case "rating": return c.rating ? `${c.rating.toFixed(1)}（${c.total_reviews || 0}件）` : "—";
    case "info": return infoLevel(c).label.replace("公開情報：", "");
    default: return "—";
  }
}

function showCompareTable() {
  const wrap = $("compareTableWrap");
  const overlay = $("compareOverlay");
  if (!wrap || !overlay || compareSet.size === 0) return;
  const clinics = Array.from(compareSet.values());
  odrTrack("compare_view", { count: clinics.length });
  const rows = [
    ["最寄駅", "station"], ["駅からの距離", "dist"], ["土日・夜間", "weekend"],
    ["駐車場", "parking"], ["個室", "private"], ["Google口コミ", "rating"], ["公開情報の量", "info"],
  ];
  wrap.innerHTML = `<table class="rk-compare-table">
    <thead><tr><th></th>${clinics.map(c => `<th><a href="${esc(clinicUrl(c))}">${esc(c.name || "")}</a></th>`).join("")}</tr></thead>
    <tbody>${rows.map(([label, kind]) =>
      `<tr><th>${label}</th>${clinics.map(c => `<td>${esc(compareValue(c, kind))}</td>`).join("")}</tr>`
    ).join("")}</tbody>
  </table>`;
  overlay.hidden = false;
}

// ── 区内順位（2026-07-09 ②）：現在のフィルタと同じスコアで
//    区ごとの順位を算出し、カードに「区内○位」を表示する ──────
let wardRankMap = new Map(); // pid -> { ward, rank, total }
function computeWardRanks() {
  wardRankMap = new Map();
  const groups = new Map();
  allClinics.forEach(c => {
    const w = regionLabelOf(c);
    if (!w) return;
    if (!groups.has(w)) groups.set(w, []);
    groups.get(w).push({ pid: c.place_id || "", score: calcRankScore(c).score });
  });
  groups.forEach((arr, w) => {
    arr.sort((a, b) => b.score - a.score);
    arr.forEach((e, i) => wardRankMap.set(e.pid, { ward: w, rank: i + 1, total: arr.length }));
  });
}

// ── レンダリング（FLIPアニメーション付き） ──────────────────
const PRIZE = { 1: ["金賞", "GOLD"], 2: ["銀賞", "SILVER"], 3: ["銅賞", "BRONZE"] };

function cardHTML(clinic, rank, matched) {
  const addr = clinic.address || "";
  const ward = regionLabelOf(clinic);
  const stationText = formatStationText(clinic.nearest_station, clinic);
  const info = infoLevel(clinic);
  const rating = clinic.rating ? clinic.rating.toFixed(1) : "—";
  const reviews = clinic.total_reviews || 0;
  const genre = clinic.genre || "";
  const tags = (clinic.specialty_tags || clinic.site_features || []).slice(0, 4);
  const summary = clinic.ai_summary || clinic.catchphrase || "";
  const url = clinicUrl(clinic);
  const official = clinic.url || "";
  const mapUrl = clinic.google_maps_url || ("https://www.google.com/maps/search/?api=1&query=" + encodeURIComponent((clinic.name || "") + " " + addr));

  const matchHTML = matched.length
    ? `<div class="rk-match">
        <p class="rk-match-label">今回の条件との一致</p>
        <ul class="rk-match-list">${matched.map(m => `<li>${esc(m)}</li>`).join("")}</ul>
      </div>`
    : "";

  const wr = wardRankMap.get(clinic.place_id || "");
  const wardHTML = wr
    ? `<span class="rk-ward-rank">${esc(wr.ward)} ${wr.rank}位<small>／${wr.total}院</small></span>`
    : esc(ward);
  const prizeHTML = rank <= 3
    ? `<span class="rk-prize rk-prize-${rank}"><span class="ja">${PRIZE[rank][0]}</span><span class="en">${PRIZE[rank][1]}</span></span>`
    : "";

  return `
  <article class="rk-card" data-pid="${esc(clinic.place_id || "")}"${rank <= 3 ? ` data-top="${rank}"` : ""}>
    <div class="rk-card-rank"><span class="num">${String(rank).padStart(2, "0")}</span><span class="unit">位</span>${prizeHTML}</div>
    <div class="rk-card-body">
      <h3 class="rk-card-name"><a href="${esc(url)}">${esc(clinic.name || "")}</a></h3>
      <p class="rk-card-meta">${wardHTML}${stationText ? "・" + esc(stationText) : ""}</p>
      <p class="rk-card-rating">Google ${rating}${reviews ? ` / 口コミ${reviews}件` : ""}${genre ? ` · ${esc(genre)}` : ""}</p>
      ${tags.length ? `<div class="rk-card-tags">${tags.map(t => `<span>${esc(t)}</span>`).join("")}</div>` : ""}
      ${matchHTML}
      ${reviewTrendsHTML(clinic)}
      ${summary ? `<div class="rk-ai"><p class="rk-ai-label">AI ANALYSIS</p><p class="rk-ai-text">${esc(summary)}</p>${evidencePanelHTML(clinic)}</div>` : ""}
      ${info.cls === "low" ? `<p class="rk-info-note">公開情報が少ないため、条件との一致を十分に判定できません。</p>` : ""}
      <div class="rk-card-foot">
        <span class="rk-info-badge rk-info-${info.cls}">${info.label}</span>
      </div>
      <div class="rk-card-links">
        <a href="${esc(url)}" data-track="clinic_click" data-name="${esc(clinic.name || "")}" data-rank="${rank}">医院詳細を見る</a>
        ${official ? `<a href="${esc(official)}" target="_blank" rel="noopener" data-track="official_click" data-name="${esc(clinic.name || "")}" data-rank="${rank}">公式サイト</a>` : ""}
        <a href="${esc(mapUrl)}" target="_blank" rel="noopener" data-track="map_click" data-name="${esc(clinic.name || "")}" data-rank="${rank}">地図</a>
        <button type="button" class="rk-compare-toggle${compareSet.has(clinic.place_id || "") ? " on" : ""}" data-pid="${esc(clinic.place_id || "")}">${compareSet.has(clinic.place_id || "") ? "比較リストから外す" : "比較に追加"}</button>
      </div>
    </div>
  </article>`;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ── 数字のカウントアップ（2026-07-09 ④）：条件を選ぶたびに
//    サイドパネルの数字がぐるぐる変わって見えるアニメーション ──
function rollNumber(el, to, fmt) {
  if (!el) return;
  const from = Number(el.dataset.val || 0);
  el.dataset.val = to;
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || from === to) {
    el.textContent = fmt(to);
    return;
  }
  const t0 = performance.now(), dur = 650;
  const step = now => {
    const p = Math.min(1, (now - t0) / dur);
    const eased = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(Math.round(from + (to - from) * eased));
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

let lastTop = []; // 症状検索（③）の提案表示が直近の上位を参照する

function renderRanking() {
  const container = $("rankList");
  // 全件表示時（数百〜千件超）は並び替えアニメーションを省略して描画を軽くする
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches ||
                       container.querySelectorAll(".rk-card").length > 200;

  const prevRects = new Map();
  if (!reduceMotion) {
    container.querySelectorAll(".rk-card").forEach(el => {
      prevRects.set(el.dataset.pid, el.getBoundingClientRect());
    });
  }
  const prevIds = new Set(prevRects.keys());

  computeWardRanks();
  const pool = getFilteredPool();
  const scored = pool.map(c => ({ clinic: c, ...calcRankScore(c) }));
  scored.sort((a, b) => b.score - a.score);
  // 地名・悩み・希望条件のどれか1つでも選ばれていたら全件を表示する
  // （50件で打ち切らない・2026-07-10）。未選択の初期表示のみ上位50件。
  const hasFilter = filters.ward !== "all" || filters.treatments.size > 0 || filters.conditions.size > 0;
  const top = hasFilter ? scored : scored.slice(0, 50);
  lastTop = top;

  rollNumber($("resultCount"), top.length, n => `${n}院を表示（データランキング）`);
  rollNumber($("matchedCount"), pool.length, n => `${n.toLocaleString()}院`);

  if (top.length === 0) {
    container.innerHTML = `<div class="rk-empty">該当する医院が見つかりませんでした。条件を変更してみてください。</div>`;
    return;
  }

  container.innerHTML = top.map((t, i) => cardHTML(t.clinic, i + 1, t.matched)).join("");

  if (reduceMotion || top.length > 200) return;

  container.querySelectorAll(".rk-card").forEach(el => {
    const pid = el.dataset.pid;
    if (!prevIds.has(pid)) {
      el.classList.add("rk-card-enter");
      requestAnimationFrame(() => requestAnimationFrame(() => el.classList.remove("rk-card-enter")));
      return;
    }
    const prevRect = prevRects.get(pid);
    const newRect = el.getBoundingClientRect();
    const dy = prevRect.top - newRect.top;
    if (Math.abs(dy) < 1) return;
    el.style.transition = "none";
    el.style.transform = `translateY(${dy}px)`;
    requestAnimationFrame(() => {
      el.style.transition = "transform 380ms cubic-bezier(.4,0,.2,1)";
      el.style.transform = "translateY(0)";
    });
  });
}

// ── フィルタUI構築 ───────────────────────────────────────────
function buildFilterChips(containerEl, items, getKey, getLabel, isActive, onClick) {
  containerEl.innerHTML = items.map(item => {
    const key = getKey(item);
    const label = getLabel(item);
    return `<button type="button" class="rk-chip${isActive(item) ? " on" : ""}" data-key="${esc(key)}">${esc(label)}</button>`;
  }).join("");
  containerEl.querySelectorAll(".rk-chip").forEach((btn, i) => {
    btn.addEventListener("click", () => onClick(items[i]));
  });
}

function renderFilterUI() {
  buildFilterChips($("filterWard"), WARD_LIST,
    w => w.key, w => w.label,
    w => filters.ward === w.key,
    w => { filters.ward = w.key; odrTrack("filter_select", { filter_type: "ward", filter_value: w.label }); onFilterChange(); });

  buildFilterChips($("filterTreatment"), TREATMENT_LIST,
    t => t, t => t,
    t => filters.treatments.has(t),
    t => {
      if (filters.treatments.has(t)) filters.treatments.delete(t);
      else filters.treatments.add(t);
      odrTrack("filter_select", { filter_type: "treatment", filter_value: t });
      onFilterChange();
    });

  buildFilterChips($("filterCondition"), CONDITION_LIST,
    c => c, c => c,
    c => filters.conditions.has(c),
    c => {
      if (filters.conditions.has(c)) filters.conditions.delete(c);
      else filters.conditions.add(c);
      odrTrack("filter_select", { filter_type: "condition", filter_value: c });
      onFilterChange();
    });
}

function renderCurrentFilterPanel() {
  const chips = [];
  if (filters.ward && filters.ward !== "all") {
    chips.push(WARD_LIST.find(w => w.key === filters.ward)?.label);
  }
  filters.treatments.forEach(t => chips.push(t));
  filters.conditions.forEach(c => chips.push(c));

  const panel = $("currentFilterPanel");
  if (chips.length === 0) {
    panel.innerHTML = `<p class="rk-panel-empty">京都市全体・総合データ順</p>`;
  } else {
    panel.innerHTML = `<div class="rk-panel-chips">${chips.map(c => `<span>${esc(c)}</span>`).join("")}</div>`;
  }
}

// ── URL状態管理 ───────────────────────────────────────────
const WARD_TO_QS = {};
Object.keys(AREA_KEYWORDS).forEach(k => {
  const romajiLike = k.replace(/（.*）/, "");
  WARD_TO_QS[k] = romajiLike;
});
const QS_TO_WARD = {};
Object.entries(WARD_TO_QS).forEach(([full, short]) => { QS_TO_WARD[short] = full; });

function syncURL(push) {
  const params = new URLSearchParams();
  if (filters.ward && filters.ward !== "all") params.set("ward", WARD_TO_QS[filters.ward] || filters.ward);
  if (filters.treatments.size) params.set("treatment", Array.from(filters.treatments).join(","));
  if (filters.conditions.size) params.set("cond", Array.from(filters.conditions).join(","));
  const qs = params.toString();
  const url = qs ? `?${qs}` : location.pathname;
  if (isRestoringHistory) return;
  try {
    if (push) history.pushState({ filters: serializeFilters() }, "", url);
    else history.replaceState({ filters: serializeFilters() }, "", url);
  } catch (e) { /* 一部環境（file://等）ではURL更新できないことがあるが致命的ではない */ }
}

function serializeFilters() {
  return { ward: filters.ward, treatments: Array.from(filters.treatments), conditions: Array.from(filters.conditions) };
}
function applySerializedFilters(s) {
  filters.ward = (s && s.ward) || "all";
  // 旧形式（treatment: 単一文字列）の履歴とも互換を保つ
  const ts = (s && (s.treatments || (s.treatment ? [s.treatment] : []))) || [];
  filters.treatments = new Set(ts.filter(t => TREATMENT_MAP[t]));
  filters.conditions = new Set((s && s.conditions) || []);
}

function parseFiltersFromURL() {
  const params = new URLSearchParams(location.search);
  const wardShort = params.get("ward");
  filters.ward = wardShort ? (QS_TO_WARD[wardShort] || "all") : "all";
  // カンマ区切りで複数指定可。既存の単一指定リンク（記事CTA等）もそのまま動く
  const treatment = params.get("treatment");
  filters.treatments = new Set(treatment ? treatment.split(",").filter(t => TREATMENT_MAP[t]) : []);
  const cond = params.get("cond");
  filters.conditions = new Set(cond ? cond.split(",").filter(Boolean) : []);
}

window.addEventListener("popstate", e => {
  isRestoringHistory = true;
  applySerializedFilters(e.state ? e.state.filters : null);
  renderFilterUI();
  renderCurrentFilterPanel();
  renderRanking();
  isRestoringHistory = false;
});

function onFilterChange() {
  renderFilterUI();
  renderCurrentFilterPanel();
  renderRanking();
  syncURL(true);
}

// ── モバイル用「条件を変更」ボタン ────────────────────────────
function initMobileCta() {
  const btn = $("mobileFilterBtn");
  if (!btn) return;
  btn.addEventListener("click", () => {
    document.querySelector(".rk-filters").scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

// ── カード内クリックの委譲（計測・比較トグル。カードは再描画されるため
//    個別にリスナーを張らず、親コンテナで一括処理する） ──────────────
function initCardDelegation() {
  const list = $("rankList");
  if (!list) return;
  list.addEventListener("click", e => {
    const link = e.target.closest("a[data-track]");
    if (link) {
      odrTrack(link.dataset.track, { clinic_name: link.dataset.name || "", rank: Number(link.dataset.rank) || 0 });
      return;
    }
    const btn = e.target.closest(".rk-compare-toggle");
    if (btn) {
      const clinic = allClinics.find(c => (c.place_id || "") === btn.dataset.pid);
      if (clinic) toggleCompare(clinic);
    }
  });
}

function initCompareUI() {
  const showBtn = $("compareShowBtn");
  const closeBtn = $("compareCloseBtn");
  const overlay = $("compareOverlay");
  if (showBtn) showBtn.addEventListener("click", showCompareTable);
  if (closeBtn) closeBtn.addEventListener("click", () => { overlay.hidden = true; });
  if (overlay) overlay.addEventListener("click", e => { if (e.target === overlay) overlay.hidden = true; });
}

// ── 症状テキスト検索（2026-07-09 ③）─────────────────────────
// 「右の犬歯が3日前からしみる」のような自由文から、通院条件
// （症状カテゴリ・希望条件・地域）を読み取ってランキングに反映し、
// 上位医院を「なぜ選んだか」の根拠つきで提案する。
// ※医療診断は行わない。読み取るのはあくまで「探す条件」であり、
//   その旨を結果に必ず明記する（policy.htmlの方針に準拠）。
const SYMPTOM_RULES = [
  { re: /しみ|知覚過敏/, treat: "歯が痛い", read: "「しみる」→ むし歯・知覚過敏への対応情報がある医院を優先", kw: ["知覚過敏", "しみ", "虫歯"] },
  { re: /痛(い|み|む|く)|ズキ|うず|激痛|虫歯|むし歯|う蝕/, treat: "歯が痛い", read: "痛み・むし歯の訴え → 急な痛み・むし歯治療の対応情報を優先", kw: ["痛み", "虫歯", "急患"] },
  { re: /詰め物|かぶせ|被せ|銀歯|取れ|欠け|割れ/, treat: "詰め物が取れた", read: "詰め物・被せ物のトラブル → 補綴治療の情報を優先", kw: ["詰め物", "被せ物", "セラミック"] },
  { re: /セラミック|審美/, treat: "セラミック", read: "セラミック・見た目の相談 → 審美補綴の対応情報を優先", kw: ["セラミック", "審美"] },
  { re: /親知らず|親不知/, treat: "親知らず", read: "親知らず → 抜歯・口腔外科系の対応情報を優先", kw: ["親知らず", "抜歯"] },
  { re: /歯周病|歯槽膿漏|歯茎|歯ぐき|歯肉|出血|血が出|腫れ|口臭|ぐらつ|ぐらぐら|グラグラ/, treat: "歯周病", read: "歯ぐき・腫れ・口臭など → 歯周病治療の情報を優先", kw: ["歯周病", "歯茎", "歯ぐき"] },
  { re: /白く|黄ば|着色|ステイン|ホワイトニング/, treat: "ホワイトニング", read: "歯の色の悩み → ホワイトニング対応の医院を優先", kw: ["ホワイトニング"] },
  { re: /歯並び|矯正|ガタガタ|出っ歯|受け口|マウスピース|インビザ/, treat: "歯列矯正", read: "歯並びの相談 → 矯正歯科の情報を優先", kw: ["矯正"] },
  { re: /インプラント/, treat: "インプラント", read: "インプラント → 対応実績の情報を優先", kw: ["インプラント"] },
  { re: /入れ歯|義歯|ブリッジ/, treat: "入れ歯", read: "入れ歯・義歯 → 補綴対応の情報を優先", kw: ["入れ歯", "義歯"] },
  { re: /子ども|子供|こども|小児|息子|娘/, treat: "子どもの歯", read: "お子さんの受診 → 小児歯科の情報を優先", kw: ["小児", "子ども"] },
  { re: /怖|苦手|緊張|トラウマ|不安/, treat: "歯医者が苦手", read: "通院への不安 → 痛みや不安への配慮の情報を優先", kw: ["無痛", "笑気", "カウンセリング"] },
  { re: /クリーニング|歯石|検診|予防/, treat: "予防・定期検診", read: "予防・検診の希望 → 予防歯科の情報を優先", kw: ["予防", "定期検診"] },
];
const SYMPTOM_COND_RULES = [
  { re: /夜|仕事帰り|遅い時間|残業/, cond: "夜間診療", read: "夜しか行けない → 夜間診療の案内がある医院を優先" },
  { re: /土日|週末|土曜|日曜/, cond: "土日診療", read: "週末の通院希望 → 土日診療の案内がある医院を優先" },
  { re: /車で|駐車/, cond: "駐車場あり", read: "車での通院 → 駐車場の案内がある医院を優先" },
  { re: /子連れ|ベビーカー|赤ちゃん/, cond: "子ども連れに配慮", read: "お子さん連れ → キッズ対応の案内がある医院を優先" },
  { re: /痛くない|無痛/, cond: "痛みに配慮", read: "痛みが不安 → 痛みへの配慮の評判がある医院を優先" },
];
const URGENT_RE = /今日中|今すぐ|激痛|眠れない|我慢できない|耐えられない/;

function parseSymptomText(text) {
  const treatments = new Set();
  const conditions = new Set();
  const readings = [];
  const kws = [];
  SYMPTOM_RULES.forEach(r => {
    if (r.re.test(text) && !treatments.has(r.treat)) {
      treatments.add(r.treat);
      readings.push(r.read);
      kws.push(...r.kw);
    }
  });
  SYMPTOM_COND_RULES.forEach(r => {
    if (r.re.test(text) && !conditions.has(r.cond)) {
      conditions.add(r.cond);
      readings.push(r.read);
    }
  });
  let ward = null;
  outer: for (const [key, keywords] of Object.entries(AREA_KEYWORDS)) {
    for (const kw of keywords) {
      if (text.includes(kw)) { ward = key; readings.push(`地名「${kw}」→ ${key.replace(/（.*）/, "")}で絞り込み`); break outer; }
    }
  }
  return { treatments, conditions, ward, readings, kws, urgent: URGENT_RE.test(text) };
}

// 提案の根拠：一致した条件＋医院の公開情報からの引用＋口コミ実数
function symptomReasons(item, parsed) {
  const c = item.clinic;
  const reasons = [];
  if (item.matched.length) reasons.push(`読み取った条件との一致：${item.matched.join("・")}`);
  const evPool = [...(c.specialty_evidence || []), ...(c.equipment_evidence || []), ...(c.doctor_evidence || [])];
  const quote = evPool.find(e => parsed.kws.some(k => e.includes(k)));
  if (quote) reasons.push(`公式サイトの記載：「${quote.length > 48 ? quote.slice(0, 48) + "…" : quote}」`);
  if (c.rating) reasons.push(`Google口コミ ${c.rating.toFixed(1)}（${c.total_reviews || 0}件）`);
  const st = formatStationText(c.nearest_station, c);
  if (st) reasons.push(st);
  const wr = wardRankMap.get(c.place_id || "");
  if (wr) reasons.push(`${wr.ward}内 ${wr.rank}位／${wr.total}院`);
  return reasons;
}

function runSymptomSearch() {
  const input = $("symptomInput");
  const result = $("symptomResult");
  if (!input || !result) return;
  const text = input.value.trim();
  if (!text) return;
  const parsed = parseSymptomText(text);
  odrTrack("symptom_search", { query: text.slice(0, 80) });

  if (parsed.treatments.size === 0 && parsed.conditions.size === 0 && !parsed.ward) {
    result.hidden = false;
    result.innerHTML = `<p class="rk-symptom-miss">症状を読み取れませんでした。「しみる」「腫れた」「詰め物が取れた」など、症状や希望の言葉を入れてみてください。</p>`;
    return;
  }

  // 読み取った条件をフィルタに反映（ランキング全体も連動して並び替わる）
  if (parsed.ward) filters.ward = parsed.ward;
  filters.treatments = new Set(parsed.treatments);
  parsed.conditions.forEach(c => filters.conditions.add(c));
  renderFilterUI();
  renderCurrentFilterPanel();
  renderRanking();
  syncURL(true);

  const top3 = lastTop.slice(0, 3);
  const cards = top3.map((item, i) => {
    const c = item.clinic;
    const reasons = symptomReasons(item, parsed);
    return `<div class="rk-sym-clinic">
      <p class="rk-sym-rank"><span class="rk-prize rk-prize-${i + 1}"><span class="ja">${PRIZE[i + 1][0]}</span></span><a href="${esc(clinicUrl(c))}">${esc(c.name || "")}</a></p>
      <ul class="rk-sym-reasons">${reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    </div>`;
  }).join("");

  result.hidden = false;
  result.innerHTML = `
    <p class="rk-sym-head">AIが読み取った条件</p>
    <ul class="rk-sym-read">${parsed.readings.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    ${parsed.urgent ? `<p class="rk-sym-urgent">強い痛み・急ぎの場合は、順位に関わらず、まずお近くの医院に電話して当日の対応可否をご確認ください。</p>` : ""}
    <p class="rk-sym-head">この条件での上位提案</p>
    ${cards || `<p class="rk-symptom-miss">該当する医院が見つかりませんでした。</p>`}
    <p class="rk-sym-note">※これは医療診断ではありません。入力文から「探す条件」を読み取り、各医院の公開情報と照合した参考情報です。症状がある場合は早めの受診をおすすめします。</p>`;
  result.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function initSymptomSearch() {
  const btn = $("symptomBtn");
  const input = $("symptomInput");
  if (!btn || !input) return;
  btn.addEventListener("click", runSymptomSearch);
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) runSymptomSearch();
  });
}

// ── 初期化 ───────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  parseFiltersFromURL();
  try { history.replaceState({ filters: serializeFilters() }, "", location.pathname + location.search); } catch (e) { /* noop */ }
  renderFilterUI();
  renderCurrentFilterPanel();
  initMobileCta();
  initCardDelegation();
  initCompareUI();
  initSymptomSearch();

  await loadDB();
  await loadSlugMap();
  renderRanking();
});
