# 京都歯科総研 プロジェクト指示

大阪歯科総研（`~/Desktop/クロード/大阪歯科総研`）の横展開第2号（第1号は神戸歯科総研）。
**立ち上げ手順・ルールの正本は `~/Desktop/クロード/横展開マニュアル.md`**。
デザイン・記事・スコアリングの共通ルールは大阪版 `CLAUDE.md`／`articles/ARTICLE_MANUAL.md` に準拠する。

## サイト概要
- 対象：京都市11区（北・上京・左京・中京・東山・下京・南・右京・伏見・山科・西京）の歯科医院ポータル
- 設定の正本：`site_config.json`（Python側）＋ `assets/site-config.js`（ブラウザ側）
- 記事生成側の設定：`AI評判設計システム/client_config_kyoto.json`（使用時に client_config.json へコピー）
- ドメイン・GA4測定IDは未定（公開前にユーザーが決定）
- 収集グリッドは市街地中心（右京区京北などの山間部は対象外）

## 費用ルール（無料優先の原則）
- 医院リスト収集：Google Maps API（月次無料枠内で運用）
- AI分析：gpt-4o-mini（神戸版で切替済みのものを継承。1,500院でも100円未満）
- ジオコーディング：Nominatim（完全無料・1req/秒）
- 費用が発生しそうな操作は、まず無料の方法を調べ、無料で不可なら見積り提示→承認後に実行

## 立ち上げ進捗（2026-07-08 開始）
- [x] フォルダ作成・神戸版から複製（gpt-4o-mini切替・修正済みコードを継承）・git init
- [x] site_config.json / site-config.js を京都用に作成
- [x] kyoto_stations.py（京都市内主要駅 約90駅・11区カバー）
- [x] clinic_collector.py：区リスト11区・グリッド範囲を京都市に変更
- [x] shindan.js：AREA_KEYWORDS を京都11区に差し替え
- [x] 全ビルドスクリプト・HTMLのブランド置換（KYOTO DENTAL RESEARCH・京都府）
- [ ] データ収集（clinic_collector.py 実行中/完了確認）
- [ ] 収集後の監査（7点チェック）→ slug生成 → ジオコーディング → 最寄駅計算
- [ ] サイト生成（build_clinics → build_features → build_index → build_sitemap）
- [ ] index.html の統計数字を実数に差し替え（site_config.json の stats と一致させる）
- [ ] サムネイル画像（ChatGPT無課金ルートで京都用に発注）
- [x] client_config_kyoto.json 作成（AI評判設計システム側）
- [ ] GitHub Privateリポジトリ作成・push（ユーザー操作）
- [ ] Cloudflare Pages接続・ドメイン決定（ユーザー操作）
- [ ] GA4新プロパティ・Search Console（ユーザー操作）
- [ ] 毎日投稿 launchd（時刻は大阪9:00・神戸9:30とずらして 10:00）

## 注意（大阪版で踏んだ地雷 — 横展開マニュアル §3 の要約）
- slug衝突（generate_slug_map.py 必須）／ジオコーディング座標集約（同一座標4件以上を監査）
- 統計数字の不一致（トップページ手打ち数字とDBの実数）
- 計測タグの入れ忘れ（全ページに site-config.js + odr-track.js）
- 医療広告ガイドライン（「唯一」「No.1」等の断定禁止・順位は条件適合度である免責を明記）
