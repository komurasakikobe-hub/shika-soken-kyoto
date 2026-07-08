# -*- coding: utf-8 -*-
"""
公式サイト深掘り：URLがある医院の公式サイト(トップ＋院長/医師紹介ページ)を読み込み、
明記されている事実のみをAI抽出して clinic_db.json に書き戻す（推測は入れない）。
抽出：院長名 / 経歴 / 資格・学会 / 設備 / 力を入れる治療 / 特徴 / 診療理念
- deep_fetched=True でスキップ（再実行に強い）。20院ごと保存。
使い方: python3 deepdive_sites.py         # 未処理のみ
        python3 deepdive_sites.py --force
        python3 deepdive_sites.py --limit 30   # 先行テスト
"""
import os, sys, re, json, time, html, urllib.request, urllib.parse

ROOT = os.path.dirname(__file__)
DB = os.path.join(ROOT, "clinic_db.json")
FORCE = "--force" in sys.argv
LIMIT = None
if "--limit" in sys.argv:
    LIMIT = int(sys.argv[sys.argv.index("--limit") + 1])

def load_env():
    paths = [os.path.join(ROOT, ".env"),
             os.path.expanduser("~/Desktop/クロード/開発室/.env")]
    for p in paths:
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
load_env()
OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
PROFILE_KW = ["院長", "医師", "ドクター", "doctor", "staff", "greeting", "message",
              "about", "profile", "clinic", "concept", "gaiyou", "外来", "紹介"]

def fetch(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA,
              "Accept-Language": "ja,en;q=0.8"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read(700000)  # 上限0.7MB
        for enc in ("utf-8", "cp932", "euc-jp"):
            try:
                return raw.decode(enc, errors="ignore")
            except Exception:
                continue
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""

def to_text(h):
    h = re.sub(r"<script[\s\S]*?</script>", " ", h, flags=re.I)
    h = re.sub(r"<style[\s\S]*?</style>", " ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = html.unescape(h)
    h = re.sub(r"\s+", " ", h)
    return h.strip()

def find_profile(homepage_html, base):
    best = None
    for m in re.finditer(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>(.*?)</a>',
                         homepage_html, re.I | re.S):
        href, text = m.group(1), to_text(m.group(2))
        blob = (href + " " + text).lower()
        if any(k.lower() in blob for k in PROFILE_KW):
            u = urllib.parse.urljoin(base, href)
            if u.startswith("http") and u != base:
                best = u
                if any(k in blob for k in ["院長", "医師", "greeting", "doctor"]):
                    return u  # 院長系を最優先
    return best

def _openai_chat(prompt, retries=2):
    body = json.dumps({"model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0}).encode()
    for _ in range(retries):
        try:
            req = urllib.request.Request("https://api.openai.com/v1/chat/completions",
                data=body, headers={"Authorization": "Bearer " + OPENAI_KEY,
                                    "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            if "429" in str(e) or "rate" in str(e).lower():
                time.sleep(3.0); continue
            print(f"    ⚠️ AI:{str(e)[:80]}", flush=True)
            return ""
    return ""

def analyze(name, text):
    if not OPENAI_KEY or not text:
        return {}
    text = text[:7000]
    try:
        prompt = f"""次は歯科医院「{name}」の公式サイトの本文です。
明記されている事実だけを抽出してください。記載が無い項目は必ず空にし、推測・創作は禁止です。

本文:
{text}

JSONのみ出力:
{{
  "doctor_name": "院長の氏名（明記があれば。なければ空）",
  "doctor_career": "院長の経歴・出身校・勤務歴（明記のみ・80字以内・なければ空）",
  "qualifications": ["資格・所属学会など明記されたもの（無ければ空配列）"],
  "equipment": ["設備で明記されているもの（例: CT, マイクロスコープ, 口腔内スキャナー, ラバーダム, セレック, 位相差顕微鏡 等。無ければ空配列）"],
  "focus_treatments": ["専門・力を入れていると明記された治療（無ければ空配列）"],
  "features": ["特徴として明記（例: 個室, 感染対策, キッズスペース, バリアフリー, 駐車場, 夜間診療, 土日診療, 女性医師 等。無ければ空配列）"],
  "philosophy": "診療理念・方針（明記があれば40字以内・なければ空）"
}}"""
        raw = _openai_chat(prompt)
        m = re.search(r"\{[\s\S]*\}", raw or "")
        if m:
            return json.loads(m.group())
    except Exception as e:
        print(f"    ⚠️ parse:{str(e)[:60]}", flush=True)
    return {}

def main():
    if not OPENAI_KEY:
        print("❌ OPENAI_API_KEY 未設定"); return
    db = json.load(open(DB, encoding="utf-8"))
    targets = [(pid, c) for pid, c in db.items()
               if c.get("name") and c.get("url")
               and (FORCE or not c.get("deep_fetched"))]
    if LIMIT:
        targets = targets[:LIMIT]
    print("=" * 56)
    print(f"  公式サイト深掘り  対象 {len(targets)}院  FORCE={FORCE}"
          + (f"  LIMIT={LIMIT}" if LIMIT else ""))
    print("=" * 56, flush=True)

    done = ok = nofetch = 0
    got_dr = got_eq = 0
    for i, (pid, c) in enumerate(targets, 1):
        url = c["url"]
        home = fetch(url)
        if not home:
            c["deep_fetched"] = True; c["deep_status"] = "fetch_fail"
            nofetch += 1
            print(f"  [{i}/{len(targets)}] {c['name'][:20]}  ✗取得失敗", flush=True)
            time.sleep(0.3); continue
        text = to_text(home)
        prof = find_profile(home, url)
        if prof:
            ptext = to_text(fetch(prof))
            if ptext:
                text = (ptext + "  " + text)  # 院長ページを優先的に前へ
        res = analyze(c["name"], text)
        if res:
            if res.get("doctor_name"):
                c["doctor_name"] = res["doctor_name"]; got_dr += 1
            if res.get("doctor_career"):
                c["doctor_career"] = res["doctor_career"]
            if res.get("qualifications"):
                c["qualifications"] = res["qualifications"]
            if res.get("equipment"):
                c["equipment_evidence"] = res["equipment"]; got_eq += 1
            if res.get("focus_treatments"):
                c["focus_treatments"] = res["focus_treatments"]
            if res.get("features"):
                c["site_features"] = res["features"]
            if res.get("philosophy"):
                c["philosophy"] = res["philosophy"]
            # 公式サイトを1ソースとして加算
            c["sources_analyzed"] = (c.get("sources_analyzed") or 0) + 1
            c["deep_source"] = "official_site"
            ok += 1
        c["deep_fetched"] = True
        c["deep_status"] = "ok" if res else "no_extract"
        done += 1
        mark = ("👤" if res.get("doctor_name") else "  ") + ("🦷" if res.get("equipment") else "")
        print(f"  [{i}/{len(targets)}] {c['name'][:20]}  {mark}", flush=True)
        if i % 20 == 0:
            json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
            print(f"    💾 {i}院保存 / 院長{got_dr} 設備{got_eq}", flush=True)
        time.sleep(0.25)

    json.dump(db, open(DB, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    allv = list(db.values())
    print("=" * 56)
    print(f"  ✅ 完了  抽出成功{ok} / 取得失敗{nofetch}")
    print(f"  院長名あり {sum(1 for x in allv if x.get('doctor_name'))}院 / "
          f"設備あり {sum(1 for x in allv if x.get('equipment_evidence'))}院")
    print("=" * 56)
    try:
        import subprocess
        subprocess.run(["osascript", "-e",
            f'display notification "院長{got_dr}・設備{got_eq}院を抽出" with title "公式サイト深掘り 完了" sound name "Glass"'], check=False)
    except Exception:
        pass

if __name__ == "__main__":
    main()
