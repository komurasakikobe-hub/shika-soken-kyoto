# -*- coding: utf-8 -*-
"""
記事のサムネイル写真を「サムネイル画像/顎関節/」配下の症状別フォルダから自動で選び、
左上の連番バッジと右端の継ぎ目線を除去したうえで articles/img/<記事ファイル名>.png に配置する。

使い方：
  記事を新規生成した後、このスクリプトを実行するだけでよい。
  python3 assign_thumbnails.py
  → articles/ 内の記事のうち、articles/img/<slug>.png がまだ無いものにだけ写真を割り当てる
  → 割り当て後、build_index.py を自動実行してカードに反映する

写真を使い切った場合や新しいカテゴリを追加した場合は、
CATEGORY_FOLDERS 辞書と KEYWORD_MAP の対応を追記すること（下記参照）。
"""
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
SRC_ROOT = ROOT / "サムネイル画像"
ARTICLES = ROOT / "articles"
IMG_DIR = ARTICLES / "img"

# タイトルに含まれるキーワード → サムネイル画像のフォルダ名（サムネイル画像/顎関節/配下）
# 上から順にチェックし、最初にマッチしたフォルダを採用する（複数キーワードに当てはまる場合は上が優先）
KEYWORD_MAP = [
    (["顎関節", "顎が痛"], "顎関節"),
    (["親知らず"], "親知らず"),
    (["詰め物", "被せ物", "銀歯", "セラミック", "取れた", "欠けた", "割れた"], "詰め物, 被せ物, 取れた, 欠けた, 割れた, クラック"),
    (["歯周病", "歯ぐき", "歯茎", "グラグラ", "腫れ"], "歯周病, 歯ぐき, 歯茎, 腫れ, 出血, 歯周ポケット"),
    (["知覚過敏", "根管治療", "歯が痛い", "神経"], "歯の構造, エナメル質, 象牙質, 歯髄, 基礎知識"),
    (["入れ歯", "義歯"], "入れ歯, 義歯, 部分入れ歯, 総入れ歯"),
    (["口臭", "におい", "口が臭い"], "口臭, 口のにおい, 口が臭い"),
    (["セカンドオピニオン", "他院", "比較"], "セカンドオピニオン, 他院, 相談, 比較"),
    (["マウスピース矯正", "インビザライン", "アライナー"], "マウスピース矯正, インビザライン, 透明, アライナー"),
    (["矯正", "歯並び"], "ワイヤー矯正, ブラケット, 歯列矯正"),
    (["インプラント", "CT", "マイクロスコープ", "設備", "スキャナー"], "設備, CT, マイクロスコープ, 口腔内スキャナー, 個室"),
    (["インプラント"], "インプラント, 費用, 料金, 人工歯根"),
    (["ホワイトニング", "白く", "着色", "黄ばみ"], "ホワイトニング, 歯を白く, 着色, 黄ばみ, 白い歯"),
    (["小児歯科", "子ども", "子供", "こども"], "小児歯科, 子ども, こども, 子供, 乳歯, 虫歯予防"),
    (["クリーニング", "歯石"], "クリーニング, 歯石, 歯石取り, スケーリング, PMTC"),
    (["予防歯科", "定期検診", "メンテナンス", "虫歯予防"], "予防歯科, 定期検診, メンテナンス, 虫歯予防"),
    (["フッ素"], "フッ素, フッ素塗布, コーティング, 予防"),
    (["レントゲン", "X線"], "レントゲン, X線, 診断, 検査"),
    (["見分け方", "選び方", "口コミ", "チェックポイント"], "歯科医院の選び方, 良い歯科医院, 見分け方, 選び方, チェックポイント"),
]
FALLBACK_FOLDER = "歯の構造, エナメル質, 象牙質, 歯髄, 基礎知識"

# ── 画像クリーニング（左上の連番バッジ／右端の継ぎ目線を除去） ──
NUMBER_BOX = (0, 60, 0, 50)   # x0, x1, y0, y1
EDGE_CLEAN_FROM_X = 372       # このx座標以降を、直前の列で塗りつぶす


def clean_thumbnail(arr: np.ndarray) -> np.ndarray:
    arr = arr.copy()
    x0, x1, y0, y1 = NUMBER_BOX
    w = x1 - x0
    sample_x0 = x1 + 8
    sample_x1 = min(arr.shape[1], sample_x0 + 8)
    if sample_x1 > sample_x0:
        col = arr[y0:y1, sample_x0:sample_x1].mean(axis=1)
        fill = np.repeat(col[:, np.newaxis, :], w, axis=1).astype(np.uint8)
        arr[y0:y1, x0:x1] = fill

    width = arr.shape[1]
    if EDGE_CLEAN_FROM_X < width:
        clean_col = arr[:, EDGE_CLEAN_FROM_X - 1:EDGE_CLEAN_FROM_X]
        fill = np.repeat(clean_col, width - EDGE_CLEAN_FROM_X, axis=1)
        arr[:, EDGE_CLEAN_FROM_X:width] = fill
    return arr


def pick_folder(title: str) -> str:
    for keywords, folder in KEYWORD_MAP:
        if any(k in title for k in keywords):
            return folder
    return FALLBACK_FOLDER


def list_folder_images(folder_name: str):
    folder = SRC_ROOT / folder_name
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.suffix.lower() in (".png", ".jpg", ".jpeg")])


def main():
    used_log = ROOT / "_thumbnail_usage.txt"
    used = set(used_log.read_text(encoding="utf-8").splitlines()) if used_log.exists() else set()

    articles = sorted(ARTICLES.glob("2026-*.html")) + sorted(ARTICLES.glob("202[0-9]-*.html"))
    articles = sorted(set(articles))

    assigned = 0
    for f in articles:
        slug = f.stem
        dst = IMG_DIR / f"{slug}.png"
        if dst.exists():
            continue

        html = f.read_text(encoding="utf-8")
        title_m = re.search(r"<h1>(.*?)</h1>", html, re.S)
        title = re.sub(r"<[^>]+>", "", title_m.group(1)) if title_m else slug

        folder = pick_folder(title)
        candidates = list_folder_images(folder)
        candidates = [c for c in candidates if str(c) not in used] or list_folder_images(folder)
        if not candidates:
            print(f"⚠️ 写真フォルダが見つからない/空: {folder} ({f.name})")
            continue

        src = candidates[0]
        used.add(str(src))

        im = Image.open(src).convert("RGB")
        arr = np.array(im)
        arr = clean_thumbnail(arr)
        Image.fromarray(arr).save(dst)
        print(f"✅ {f.name} <- {folder} / {src.name}")
        assigned += 1

    used_log.write_text("\n".join(sorted(used)), encoding="utf-8")

    if assigned:
        subprocess.run([sys.executable, str(ROOT / "build_index.py")], check=True)
        print(f"完了：{assigned}件のサムネイルを割り当て、build_index.pyを再実行しました")
    else:
        print("新規に割り当てる記事はありませんでした")


if __name__ == "__main__":
    main()
