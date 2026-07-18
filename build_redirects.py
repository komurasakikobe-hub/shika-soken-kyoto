# -*- coding: utf-8 -*-
"""Cloudflare Pages 用 _redirects を生成する（内部ファイルの公開遮断・2026-07-13新設）。

背景：このリポジトリはサイト一式と運用スクリプトが同居しており、Cloudflare Pages は
リポジトリ内の全ファイルをそのまま配信する。CLAUDE.md・MANUAL.md・*.py・ログ等の
内部ファイルが本番URLで丸見えだったため、公開してよいものの許可リスト以外を
トップページへ301させる。

方針（許可リスト方式）：
- 公開：articles/**・assets/**・ルートの公開HTML・favicon.ico・robots.txt・sitemap.xml・
  llms.txt・clinic_db.json / clinic_slugs.json（articles/shindan/shindan.js がブラウザから
  fetchするため遮断してはならない）
- それ以外のGit管理ファイル（＝デプロイされるもの）は全て 301 → /
- 都市非依存（git ls-files から機械生成）。全9都市に丸コピーしてよい。
- ファイルを追加・削除したら再実行して _redirects を更新すること（validate_release前推奨）。
"""
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent

# 公開してよいルート直下ファイル
PUBLIC_ROOT_FILES = {
    "index.html", "about.html", "network.html", "policy.html", "teisei.html",
    "shikumi.html", "for-clinics.html", "sample-report.html", "404.html",
    "favicon.ico", "robots.txt", "sitemap.xml", "llms.txt",
    "clinic_db.json", "clinic_slugs.json",  # shindan.jsがブラウザからfetchする（遮断禁止）
    "_redirects", "_headers",
}
# 公開してよいディレクトリ（この下は原則公開。ただしBLOCKED_EXTSの内部ファイル種は遮断）
PUBLIC_DIRS = {"articles", "assets"}
# 公開ディレクトリ内でも遮断する内部ファイル種（例：articles/ARTICLE_MANUAL.md）
BLOCKED_EXTS = (".md", ".py", ".sh", ".zip", ".log")


def main() -> None:
    # -z: NUL区切り（日本語ファイル名がC風エスケープで壊れるのを防ぐ）
    files = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    files = [f for f in files if f]

    blocked_dirs = []   # トップレベルの非公開ディレクトリ（splatで丸ごと遮断）
    blocked_files = []  # ルート直下の非公開ファイル
    seen_dirs = set()
    for f in files:
        top = f.split("/", 1)[0]
        if "/" in f:
            if top in PUBLIC_DIRS:
                if f.lower().endswith(BLOCKED_EXTS):
                    blocked_files.append(f)  # 公開ディレクトリ内の内部ファイル種は個別遮断
                continue
            if top in seen_dirs:
                continue
            seen_dirs.add(top)
            blocked_dirs.append(top)
        else:
            if f in PUBLIC_ROOT_FILES:
                continue
            blocked_files.append(f)

    lines = [
        "# 内部ファイルの公開遮断（build_redirects.py が生成。手編集しない）",
        "# 許可リスト以外のGit管理ファイルをトップへ301。再生成: python3 build_redirects.py",
    ]
    for d in sorted(blocked_dirs):
        lines.append(f"/{quote(d)}/* / 301")
    for f in sorted(blocked_files):
        lines.append(f"/{quote(f)} / 301")

    out = ROOT / "_redirects"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n = len(blocked_dirs) + len(blocked_files)
    if n > 1900:
        print(f"⚠ ルール数 {n} がCloudflareの上限(静的2,000)に接近。要整理", file=sys.stderr)
    print(f"✓ _redirects 生成: ディレクトリ{len(blocked_dirs)}件＋ファイル{len(blocked_files)}件を遮断")


if __name__ == "__main__":
    main()
