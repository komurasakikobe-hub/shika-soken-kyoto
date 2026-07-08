"use strict";
/* =========================================================
   計測モジュール（GA4）。ODR_CONFIG.ga4MeasurementId が設定されていれば
   gtag.js を読み込み、odrTrack(name, params) でカスタムイベントを送る。
   未設定の間は何もしない（開発中・都市展開直後でも安全に同梱できる）。

   計測するイベント（ランキングページ）:
     filter_select   … フィルター選択 {filter_type, filter_value}
     clinic_click    … 医院詳細クリック {clinic_name, rank}
     official_click  … 公式サイトクリック {clinic_name, rank}
     map_click       … 地図クリック {clinic_name, rank}
     compare_add     … 比較に追加 {clinic_name}
     compare_view    … 比較表を表示 {count}
   これらが「どんな患者が・どの条件で・どの医院に興味を持ったか」の
   一次データになり、医院向けレポート/AI評判設計プランの営業材料になる。
   ========================================================= */
(function () {
  var cfg = window.ODR_CONFIG || {};
  var gaId = cfg.ga4MeasurementId || "";

  window.odrTrack = function (name, params) {
    if (!gaId || typeof window.gtag !== "function") return;
    try { window.gtag("event", name, params || {}); } catch (e) { /* noop */ }
  };

  if (!gaId) return;

  var s = document.createElement("script");
  s.async = true;
  s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(gaId);
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag("js", new Date());
  window.gtag("config", gaId);
})();
