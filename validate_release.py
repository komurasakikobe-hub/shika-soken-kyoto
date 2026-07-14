# -*- coding: utf-8 -*-
"""
出荷前検証ゲート（恒久回帰テスト・2026-07-12新設／Fable指示09）

push前に必ず実行する常設バリデータ。read-only（生成物・DBを一切書き換えない）。
役割分担:
  - articles/clinics/ の詳細検証 = 既存 `_validate_meo_fixes.py`（本スクリプトがサブプロセスで実行し合算）
  - それ以外のサイト全体 = 本スクリプト
チェック項目:
  G-1: 全HTMLのJSON-LD構文妥当性（json.loadsが通る／@typeがある）
  G-2: インデックス対象ページに自己参照canonicalが1本ある／canonical == og:url == JSON-LD url（存在する範囲で一致）
  G-3: aggregateRating / review markup がld+jsonに存在しない（第三者rating禁止・全ページ）
  G-4: meta description の語尾切れ・過長（clinics以外。clinicsは既存側が担当）
  G-5: sitemap.xml の全URLが実ファイルとして存在する（逆方向の薄い院混入は既存側が担当）
  G-6: 内部リンク（href/src）の実ファイル存在（神戸のリンク切れ量産事故の再発防止）
  G-7: golden構造差分 — 代表ページの「構造指紋」（headタグ構成・JSON-LDの@typeとキー集合・見出し骨格）を
       _golden/golden_structure.json と比較。テンプレ改変時に意図しない構造変化を検出する。
       データ更新（統計数字・院数）では発火しない。意図した変更なら --update-golden で更新。
実行:
  python3 validate_release.py                 # フルゲート（push前は必ずこれ）
  python3 validate_release.py --update-golden # テンプレ変更を意図して行った後にgoldenを更新
  python3 validate_release.py --skip-links    # リンク存在チェックを省略（高速確認用）
終了コード: エラーありで1（pushしないこと）／ゼロで合格。
都市固有値なし（site_config.json駆動）＝全都市へ丸コピー可（build_*5本と同思想）。
"""
import argparse, json, os, re, subprocess, sys
from html import unescape
from urllib.parse import unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

SITE_CFG = json.load(open(os.path.join(ROOT, "site_config.json"), encoding="utf-8"))
DOMAIN = SITE_CFG["domain"]
BASE = f"https://{DOMAIN}"

# 「_」始まりのdirは全て除外（backup類）。articles_index_edit_files=2026-07-04の編集作業コピー（非公開導線）
SKIP_DIRS = {".git", "node_modules", "__pycache__", "articles_index_edit_files"}
GOLDEN_PATH = os.path.join(ROOT, "_golden", "golden_structure.json")

RE_CANON = re.compile(r'<link rel="canonical" href="([^"]+)"')
RE_OGURL = re.compile(r'<meta property="og:url" content="([^"]+)"')
RE_DESC = re.compile(r'<meta name="description" content="([^"]*)"')
RE_LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
RE_ROBOTS_NOINDEX = re.compile(r'<meta name="robots" content="[^"]*noindex')
RE_META_REFRESH = re.compile(r'<meta http-equiv="refresh"', re.I)
RE_HEAD_META = re.compile(r'<meta (?:name|property)="([^"]+)"')
RE_HEADINGS = re.compile(r"<(h[12])[ >]")
RE_LINKS = re.compile(r'(?:href|src)="([^"]+)"')
RE_DESC_TAIL = re.compile(r"[。…！？）」]$")


def walk_html():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith("_")]
        for fn in filenames:
            if fn.endswith(".html"):
                yield os.path.join(dirpath, fn)


def rel(path):
    return os.path.relpath(path, ROOT)


def parse_ld_blocks(src, relpath, errors):
    """ld+jsonブロックをパースして返す。パース不能はエラー計上。"""
    out = []
    for i, block in enumerate(RE_LD.findall(src)):
        try:
            d = json.loads(unescape(block))
        except Exception as e:
            errors.append(f"[G-1] JSON-LDパース不能: {relpath} (block {i+1}): {e}")
            continue
        for item in (d if isinstance(d, list) else [d]):
            if isinstance(item, dict):
                if not item.get("@type"):
                    errors.append(f"[G-1] JSON-LDに@typeが無い: {relpath} (block {i+1})")
                out.append(item)
    return out


def url_to_relfile(url):
    """自サイトURL → ルート相対のファイルパス（該当しなければNone）。"""
    p = urlparse(url)
    if p.netloc and p.netloc != DOMAIN:
        return None
    path = unquote(p.path)
    if path.endswith("/") or path == "":
        path += "index.html"
    elif not path.endswith(".html"):
        path += ".html"  # 拡張子なしURL（Cloudflare Pagesの308転送先）→ 実ファイルは.html
    return path.lstrip("/")


def check_page(path, args, errors, warns, is_clinic, in_sitemap):
    relpath = rel(path)
    src = open(path, encoding="utf-8").read()
    is_redirect = bool(RE_META_REFRESH.search(src))
    noindex = bool(RE_ROBOTS_NOINDEX.search(src))

    ld_items = parse_ld_blocks(src, relpath, errors)  # G-1 全ページ

    # G-3 全ページ
    joined = json.dumps(ld_items, ensure_ascii=False)
    if "aggregateRating" in joined or '"review"' in joined:
        errors.append(f"[G-3] aggregateRating/review markupが混入: {relpath}")

    # 医院ページの canonical/og/desc 詳細は _validate_meo_fixes.py の担当（重複計上しない）
    if is_clinic:
        return src, is_redirect

    # G-2: canonical（リダイレクトスタブは対象外）
    canons = RE_CANON.findall(src)
    if not is_redirect:
        if len(canons) > 1:
            errors.append(f"[G-2] canonicalが{len(canons)}本: {relpath}")
        elif not canons:
            # canonical必須なのはsitemap掲載ページ（内部文書・noindexは対象外）
            if in_sitemap and not noindex:
                errors.append(f"[G-2] sitemap掲載ページにcanonicalが無い: {relpath}")
        else:
            can = canons[0]
            if not can.startswith(BASE):
                errors.append(f"[G-2] canonicalが自ドメインでない: {relpath}: {can}")
            expect = url_to_relfile(can)
            if expect is not None and expect.replace("\\", "/") != relpath.replace(os.sep, "/"):
                errors.append(f"[G-2] canonicalが自己参照でない: {relpath} → {can}")
            og = RE_OGURL.findall(src)
            if og and og[0] != can:
                errors.append(f"[G-2] canonical≠og:url: {relpath}")
            for item in ld_items:
                u = item.get("url")
                if u and item.get("@type") in ("CollectionPage", "Article", "WebPage", "Dataset") and u != can:
                    errors.append(f"[G-2] canonical≠JSON-LD url({item.get('@type')}): {relpath}")

    # G-4: meta description（リダイレクトスタブ以外）
    if not is_redirect:
        m = RE_DESC.search(src)
        if m:
            d = unescape(m.group(1)).strip()
            if d and not RE_DESC_TAIL.search(d):
                warns.append(f"[G-4] description語尾切れの疑い: {relpath}: …{d[-25:]}")
            if len(d) > 170:
                warns.append(f"[G-4] descriptionが{len(d)}文字（170超）: {relpath}")

    return src, is_redirect


def check_links(path, src, errors, link_cache):
    """G-6: ローカル相対リンクの実ファイル存在チェック。"""
    relpath = rel(path)
    base_dir = os.path.dirname(path)
    for raw in set(RE_LINKS.findall(src)):
        href = unescape(raw)
        if href.startswith(("http://", "https://", "//", "mailto:", "tel:", "#", "data:", "javascript:")):
            continue
        target = unquote(href.split("#")[0].split("?")[0])
        if not target:
            continue
        if target.startswith("/"):
            full = os.path.join(ROOT, target.lstrip("/"))
        else:
            full = os.path.normpath(os.path.join(base_dir, target))
        if full not in link_cache:
            # 拡張子なしの正規URL（Cloudflare Pagesの308統一後の形。実ファイルは.html）も実在扱い
            link_cache[full] = (os.path.exists(full)
                                or os.path.exists(full + ".html")
                                or os.path.exists(os.path.join(full, "index.html")))
        if not link_cache[full]:
            errors.append(f"[G-6] リンク先が存在しない: {relpath} → {href}")


def structure_fingerprint(path):
    """G-7: 構造指紋（データでなくテンプレ構造だけを写し取る）。"""
    src = open(path, encoding="utf-8").read()
    metas = sorted(set(RE_HEAD_META.findall(src)))
    ld = []
    for block in RE_LD.findall(src):
        try:
            d = json.loads(unescape(block))
        except Exception:
            ld.append({"@type": "<parse-error>", "keys": []})
            continue
        for item in (d if isinstance(d, list) else [d]):
            if isinstance(item, dict):
                ld.append({"@type": item.get("@type"), "keys": sorted(item.keys())})
    ld.sort(key=lambda x: str(x["@type"]))
    return {
        "meta_names": metas,
        "has_canonical": bool(RE_CANON.search(src)),
        "jsonld": ld,
        "headings": RE_HEADINGS.findall(src)[:20],
    }


def golden_samples():
    """代表サンプル（存在するものだけ対象。都市非依存の相対パス）。"""
    cands = ["index.html", "shikumi.html", "policy.html",
             "articles/features/index.html", "articles/shindan/index.html"]
    # 医院ページ: 厚い院・薄い院を1件ずつ（名前順で決定的に選ぶ）
    clinics_dir = os.path.join(ROOT, "articles", "clinics")
    if os.path.isdir(clinics_dir):
        thick = thin = None
        for fn in sorted(os.listdir(clinics_dir)):
            if not fn.endswith(".html"):
                continue
            src = open(os.path.join(clinics_dir, fn), encoding="utf-8").read()
            if RE_ROBOTS_NOINDEX.search(src):
                thin = thin or f"articles/clinics/{fn}"
            else:
                thick = thick or f"articles/clinics/{fn}"
            if thick and thin:
                break
        cands += [p for p in (thick, thin) if p]
    # area: 名前順で先頭1件
    area_dir = os.path.join(ROOT, "articles", "area")
    if os.path.isdir(area_dir):
        pages = sorted(f for f in os.listdir(area_dir) if f.endswith(".html"))
        if pages:
            cands.append(f"articles/area/{pages[0]}")
    return [c for c in cands if os.path.exists(os.path.join(ROOT, c))]


def diff_fingerprint(name, old, new, diffs):
    for key in ("meta_names", "has_canonical", "headings"):
        if old.get(key) != new.get(key):
            diffs.append(f"[G-7] {name}: {key} が変化: {old.get(key)} → {new.get(key)}")
    old_ld = {str(x["@type"]): x["keys"] for x in old.get("jsonld", [])}
    new_ld = {str(x["@type"]): x["keys"] for x in new.get("jsonld", [])}
    for t in sorted(set(old_ld) | set(new_ld)):
        if t not in new_ld:
            diffs.append(f"[G-7] {name}: JSON-LD {t} が消失")
        elif t not in old_ld:
            diffs.append(f"[G-7] {name}: JSON-LD {t} が新規追加")
        elif old_ld[t] != new_ld[t]:
            gone = set(old_ld[t]) - set(new_ld[t])
            added = set(new_ld[t]) - set(old_ld[t])
            diffs.append(f"[G-7] {name}: JSON-LD {t} のキー変化: -{sorted(gone)} +{sorted(added)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-golden", action="store_true")
    ap.add_argument("--skip-links", action="store_true")
    args = ap.parse_args()

    errors, warns = [], []
    link_cache = {}
    clinics_prefix = os.path.join(ROOT, "articles", "clinics") + os.sep

    # G-5: sitemapの全URL → 実ファイル存在（先に読み、canonical必須判定にも使う）
    sitemap_path = os.path.join(ROOT, "sitemap.xml")
    n_sm = 0
    sitemap_files = set()
    if os.path.exists(sitemap_path):
        sm = open(sitemap_path, encoding="utf-8").read()
        for loc in re.findall(r"<loc>([^<]+)</loc>", sm):
            n_sm += 1
            relfile = url_to_relfile(loc.strip())
            if relfile is None:
                errors.append(f"[G-5] sitemapに他ドメインURL: {loc}")
            else:
                sitemap_files.add(relfile)
                if not os.path.exists(os.path.join(ROOT, relfile)):
                    errors.append(f"[G-5] sitemap URLの実ファイルが無い: {loc}")
    else:
        errors.append("[G-5] sitemap.xml が存在しない")

    n_pages = 0
    for path in walk_html():
        n_pages += 1
        is_clinic = path.startswith(clinics_prefix)
        in_sitemap = rel(path).replace(os.sep, "/") in sitemap_files
        src, is_redirect = check_page(path, args, errors, warns, is_clinic, in_sitemap)
        if not args.skip_links and not is_redirect:
            check_links(path, src, errors, link_cache)

    # G-7: golden構造差分
    samples = golden_samples()
    current = {name: structure_fingerprint(os.path.join(ROOT, name)) for name in samples}
    if args.update_golden:
        os.makedirs(os.path.dirname(GOLDEN_PATH), exist_ok=True)
        json.dump(current, open(GOLDEN_PATH, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
        print(f"golden更新: {rel(GOLDEN_PATH)}（{len(current)}サンプル）")
    elif os.path.exists(GOLDEN_PATH):
        golden = json.load(open(GOLDEN_PATH, encoding="utf-8"))
        diffs = []
        for name in sorted(set(golden) | set(current)):
            if name not in current:
                diffs.append(f"[G-7] goldenサンプルが現物に無い: {name}")
            elif name not in golden:
                warns.append(f"[G-7] golden未登録のサンプル（--update-goldenで登録）: {name}")
            else:
                diff_fingerprint(name, golden[name], current[name], diffs)
        errors.extend(diffs)
    else:
        warns.append("[G-7] goldenが未作成（初回は --update-golden で作成すること）")

    # 医院ページ詳細 = 既存バリデータをそのまま実行して合算
    meo_rc = None
    meo_script = os.path.join(ROOT, "_validate_meo_fixes.py")
    if os.path.exists(meo_script):
        print("--- _validate_meo_fixes.py（医院ページ詳細） ---")
        meo_rc = subprocess.run([sys.executable, meo_script], cwd=ROOT).returncode
        print("--- ここまで既存バリデータ出力 ---\n")
        if meo_rc != 0:
            errors.append(f"[MEO] _validate_meo_fixes.py がエラー終了（rc={meo_rc}）詳細は上の出力")
    else:
        warns.append("[MEO] _validate_meo_fixes.py が無い（医院ページ詳細検証はスキップ）")

    print(f"検証ページ数: {n_pages} / sitemap URL: {n_sm} / goldenサンプル: {len(samples)}")
    print(f"\nエラー: {len(errors)}")
    for e in errors[:40]:
        print("  ✗", e)
    if len(errors) > 40:
        print(f"  …他{len(errors)-40}件")
    print(f"警告: {len(warns)}")
    for w in warns[:20]:
        print("  ⚠", w)

    report = {"domain": DOMAIN, "pages": n_pages, "sitemap_urls": n_sm,
              "errors": errors, "warns": warns, "meo_rc": meo_rc}
    os.makedirs(os.path.join(ROOT, "_reports"), exist_ok=True)
    json.dump(report, open(os.path.join(ROOT, "_reports", "validate_release_last.json"),
                           "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nレポート: _reports/validate_release_last.json")
    print("判定:", "✗ 不合格（pushしないこと）" if errors else "✓ 合格")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
