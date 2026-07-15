"use strict";
/* =========================================================
   計測モジュール（GA4・複数プロパティ同時送信対応）。
   ODR_CONFIG.ga4MeasurementIds（配列）に設定された全IDへ、
   gtag.js経由で同一イベントを同時送信する。空文字・未設定のIDは無視。
   旧形式の単数 ga4MeasurementId（文字列）にも後方互換で対応。
   全IDが空の間は何もしない（開発中・都市展開直後でも安全に同梱できる）。

   2026-07-11：GA4アカウントの無料枠切れリスクに備え、正規アカウント
   （shika-soken）と臨時アカウント（kokedama）の両方に同時計測する方針に変更。
   片方が枠切れになってももう片方にデータが残る。詳細は横展開マニュアル§2-5参照。

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
  var raw = cfg.ga4MeasurementIds || (cfg.ga4MeasurementId ? [cfg.ga4MeasurementId] : []);
  var ids = raw.filter(function (id) { return !!id; });

  window.odrTrack = function (name, params) {
    if (!ids.length || typeof window.gtag !== "function") return;
    try { window.gtag("event", name, params || {}); } catch (e) { /* noop */ }
  };

  if (!ids.length) return;

  var s = document.createElement("script");
  s.async = true;
  s.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(ids[0]);
  document.head.appendChild(s);
  window.dataLayer = window.dataLayer || [];
  window.gtag = function () { window.dataLayer.push(arguments); };
  window.gtag("js", new Date());
  ids.forEach(function (id) { window.gtag("config", id); });
})();

/* =========================================================
   スマホ用ナビ（ハンバーガー）。全ページ共通の .odr-brandbar に
   トグルボタンを注入し、既存 <nav> をドロップダウン開閉する。
   markupは各ページ非改変。見た目は odr-ds.css（≤640px）が担当。
   グローバル汚染ゼロ・二重注入ガードあり。
   ========================================================= */
(function () {
  function initNav() {
    var bars = document.querySelectorAll(".odr-brandbar");
    for (var i = 0; i < bars.length; i++) {
      (function (bar) {
        if (bar.getAttribute("data-odr-nav") === "1") return; // 二重注入ガード
        var nav = bar.querySelector("nav");
        if (!nav) return;
        bar.setAttribute("data-odr-nav", "1");
        if (!nav.id) nav.id = "odr-nav";

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "odr-navtoggle";
        btn.setAttribute("aria-label", "メニュー");
        btn.setAttribute("aria-expanded", "false");
        btn.setAttribute("aria-controls", nav.id);
        btn.innerHTML = '<span class="odr-navtoggle-bars" aria-hidden="true"></span>';
        bar.appendChild(btn);

        function close() {
          bar.classList.remove("nav-open");
          btn.setAttribute("aria-expanded", "false");
        }
        function open() {
          bar.classList.add("nav-open");
          btn.setAttribute("aria-expanded", "true");
        }
        btn.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          bar.classList.contains("nav-open") ? close() : open();
        });
        var links = nav.querySelectorAll("a");
        for (var j = 0; j < links.length; j++) {
          links[j].addEventListener("click", close);
        }
        document.addEventListener("click", function (e) {
          if (bar.classList.contains("nav-open") && !bar.contains(e.target)) close();
        });
        document.addEventListener("keydown", function (e) {
          if (e.key === "Escape" || e.keyCode === 27) close();
        });
      })(bars[i]);
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNav);
  } else {
    initNav();
  }
})();
