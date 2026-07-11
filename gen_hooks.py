# -*- coding: utf-8 -*-
"""コラムカードのホバー用フック文言を gpt-4o-mini で一括生成 → article_hooks.json。
新開発室で決めた型（逆説・疑問中心／第一人称禁止／不安煽り禁止／総研トーン／全角15〜28字）に従う。
反復・大量生成はOpenAIに投げる原則（CLAUDE.md）に沿う。"""
import os, re, json, urllib.request

HERE = os.path.dirname(__file__)

# .env（開発室のものを再利用）
for envp in (os.path.join(HERE, "..", "開発室", ".env"), os.path.join(HERE, ".env")):
    if os.path.exists(envp):
        for line in open(envp, encoding="utf-8"):
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        break

from build_index import clean_title, cat_of  # 表示タイトルと同じ整形を使う

ART = os.path.join(HERE, "articles")
arts = []
for f in sorted(os.listdir(ART)):
    if not f.endswith(".html") or f == "index.html" or f.startswith("cat-"):
        continue
    raw = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", f[:-5])
    arts.append({"f": f, "title": clean_title(raw), "cat": cat_of(raw)})

listing = "\n".join(f'{i+1}. [{a["cat"]}] {a["title"]}  <<KEY:{a["f"]}>>' for i, a in enumerate(arts))

SYSTEM = (
    "あなたは歯科情報サイト『京都歯科総研』（研究機関トーン）の編集者です。"
    "各記事タイトルに、一覧カードのホバーで一瞬だけ出す短いフック文言を1つ作ります。"
    "狙いは『え、なんだろう』と続きを読みたくなる好奇心ギャップ。次を厳守：\n"
    "・全角15〜28字・1行・句点なしでよい\n"
    "・釣り逃げ厳禁（必ずタイトルの中身と一致する内容）\n"
    "・第一人称『私』は使わない（客観性を保つ）\n"
    "・『損をする』等の不安煽り、過度な感嘆符、絵文字、！の多用は禁止\n"
    "・落ち着いた総研トーンで、患者にとってポジティブな『知っておくと良い視点』を示す\n"
    "・逆説型（一見正しい思い込みを覆す）と、具体的な疑問型を中心に、少し余韻を残す\n"
    "出力は JSON オブジェクトのみ。キーは各行末の <<KEY:...>> の値、値はフック文言。前置き・説明は書かない。"
)

body = json.dumps({
    "model": "gpt-4o-mini",
    "temperature": 0.8,
    "response_format": {"type": "json_object"},
    "messages": [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "次の記事すべてにフックを作ってJSONで返してください。\n\n" + listing},
    ],
}).encode("utf-8")

req = urllib.request.Request(
    "https://api.openai.com/v1/chat/completions", data=body,
    headers={"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
             "Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
content = resp["choices"][0]["message"]["content"]
hooks = json.loads(content)

# キー検証：実在ファイル名のみ・値は前後空白除去
valid = {a["f"]: hooks[a["f"]].strip() for a in arts if a["f"] in hooks and hooks[a["f"]].strip()}
out = os.path.join(HERE, "article_hooks.json")
json.dump(valid, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"生成 {len(valid)}/{len(arts)} 本 → {out}")
for a in arts[:6]:
    print(" -", a["title"], "→", valid.get(a["f"], "(なし)"))
