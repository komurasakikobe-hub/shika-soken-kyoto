#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llms.txt 生成器（都市・業種非依存・site_config.json 駆動・2026-07-14新設）。

AI（ChatGPT/Gemini/Claude/Perplexity等）に、このサイトの正体・主要ページ・評価方法を
正確に伝えるための /llms.txt を生成する。都市名・ドメイン・院数・業種などの固有値は
site_config.json から読むため、全都市・両業種（歯科/動物病院）で同一スクリプトが使える。

- 出力先：<サイト>/llms.txt（build_redirects.py の許可リストに含まれ本番配信される）
- 院数は clinics_published を控えめに丸めた概数（過大表示を避ける）
- リンクはローカルに実在するページのみ出力（都市間ドリフトでの死にリンクを防ぐ）
- 横展開：_rollout_sync.py の FILES に含まれ全歯科都市へ自動配布。各サイトで実行すること
  （動物サイトは別業種のため手動コピー）

使い方:
  python3 build_llms.py           # llms.txt を生成
  python3 build_llms.py --check   # 生成せず内容を表示
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 業種別の施設語（配点は歯科・動物で同一。施設名だけ変える）
FACILITY = {"歯科": "歯科医院", "動物病院": "動物病院"}
# コラムの集約先（都市サイトは本部ドメインに集約する運用のため固定）
COLUMN_HUB = {
    "歯科": "https://shikasoken.com/articles/index.html",
    "動物病院": "https://osaka.doubutsu-navi.com/articles/index.html",
}


def _approx(n):
    """院数を控えめに丸めた概数テキスト（過大表示しない）。"""
    if n >= 1000:
        return f"約{(n // 100) * 100:,}院"
    if n >= 100:
        return f"約{(n // 10) * 10}院"
    return f"{n}院"


def build(cfg):
    industry = cfg.get("industry", "歯科")
    facility = FACILITY.get(industry, "歯科医院")
    hub = COLUMN_HUB.get(industry, COLUMN_HUB["歯科"])
    domain = cfg["domain"]
    base = f"https://{domain}"
    city = cfg.get("city", "")
    name = cfg["site_name"]
    name_en = cfg.get("site_name_en", "")
    stats = cfg.get("stats", {})
    n = stats.get("clinics_published") or stats.get("clinics_analyzed") or 0

    heading = f"# {name}" + (f"（{name_en}）" if name_en else "")
    summary = (
        f"{city}内の{facility}{_approx(n)}を、Google口コミ・公式サイト等の公開情報から"
        f"AIが分析する独立系の情報メディア。掲載・分析は無料で、掲載順位が金銭で変わる"
        f"ことはない。スコア・順位は公開情報の充実度と評判分析にもとづく参考情報であり、"
        f"{facility}の優劣を断定するものではない。"
    )

    # (ラベル, ローカル実在チェック用パス（None=常時出力）, 出力URL)
    candidates = [
        ("データランキング（地域・症状・希望条件で絞り込み）",
         "articles/shindan/index.html", f"{base}/articles/shindan/index.html"),
        ("特徴から探す（設備・専門分野別）",
         "articles/features/index.html", f"{base}/articles/features/index.html"),
        ("コラム（毎日更新）", None, hub),
        ("展開エリア（関西各都市）", "network.html", f"{base}/network.html"),
        ("選定基準・評価配点", "index.html", f"{base}/index.html#criteria"),
        ("運営者情報", "about.html", f"{base}/about.html"),
        ("運営ポリシー・免責事項", "policy.html", f"{base}/policy.html"),
    ]

    lines = [heading, "", f"> {summary}", "", "## 主要ページ"]
    for label, local, url in candidates:
        if local is None or os.path.exists(os.path.join(ROOT, local)):
            lines.append(f"- [{label}]({url})")
    lines += [
        "",
        "## データについて",
        "- 評価配点：口コミ・評判25点／院長の経歴・専門性25点／設備・診療体制20点／"
        "情報公開・透明性15点／学会・症例・発信15点＋Google評価ボーナス最大8点（100点上限）",
        f"- {facility}ごとの分析ページ例：{base}/articles/clinics/（{facility}名）.html",
        f"- 掲載情報の訂正窓口：{base}/teisei.html",
        "",
    ]
    return "\n".join(lines)


def main():
    with open(os.path.join(ROOT, "site_config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    out = build(cfg)
    if "--check" in sys.argv or "--dry" in sys.argv:
        print(out)
        return
    with open(os.path.join(ROOT, "llms.txt"), "w", encoding="utf-8") as f:
        f.write(out)
    print(f"✓ {cfg['site_name']} ({cfg['domain']}) → llms.txt  [{cfg.get('industry', '')}]")


if __name__ == "__main__":
    main()
