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
     card_impression … 医院カードが画面に表示された {clinic_name, rank}（CTRの分母）
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
   表示回数（Impression）計測。[data-odr-impression] を持つ要素が
   画面に入ったら、その属性値をイベント名として一度だけ送信する。
   医院カード（ランキング）の「表示回数」＝クリック率(CTR)の分母を取るための汎用計測。
   医院名・順位・フィルタ値は data-name / data-rank / data-filter から拾う。
   動的に描画される要素にも対応：描画後に window.odrObserveImpressions() を
   呼べば、未監視の要素だけを追加で監視する（二重監視・二重送信ガードあり）。
   IntersectionObserver 非対応環境・GA4未設定時は安全に無効化。
   ========================================================= */
(function () {
  if (typeof IntersectionObserver !== "function") {
    window.odrObserveImpressions = function () {};
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    for (var i = 0; i < entries.length; i++) {
      var en = entries[i];
      if (!en.isIntersecting) continue;
      var el = en.target;
      io.unobserve(el);
      if (el.getAttribute("data-odr-seen") === "1") continue; // 一度だけ送信
      el.setAttribute("data-odr-seen", "1");
      var name = el.getAttribute("data-odr-impression") || "impression";
      var params = {};
      if (el.dataset.name) params.clinic_name = el.dataset.name;
      if (el.dataset.rank) params.rank = Number(el.dataset.rank) || 0;
      if (el.dataset.filter) params.filter_value = el.dataset.filter;
      if (typeof window.odrTrack === "function") window.odrTrack(name, params);
    }
  }, { threshold: 0.5 });

  window.odrObserveImpressions = function () {
    var els = document.querySelectorAll("[data-odr-impression]:not([data-odr-obs])");
    for (var i = 0; i < els.length; i++) {
      els[i].setAttribute("data-odr-obs", "1"); // 二重監視ガード
      io.observe(els[i]);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", window.odrObserveImpressions);
  } else {
    window.odrObserveImpressions();
  }
})();

/* =========================================================
   成果（CV）計測。ページ表示だけでは事業の成果が分からないため、
   「問い合わせにつながる行動」を全ページ共通で拾う（2026-08-01追加）。

     tel_click         … 電話番号リンクのタップ {filter_value:番号種別}
     mail_click        … メールアドレスリンクのクリック {filter_value:宛先}
     contact_nav       … 医院向け窓口（for-clinics / teisei）への遷移 {filter_value:遷移元}
     contact_form_view … 問い合わせフォームが画面に入った＝到達 {filter_value:フォーム名}
     contact_submit    … 送信完了（各ページのフォーム側から明示的に呼ぶ）

   パラメータは既存の登録済みカスタムディメンション（clinic_name / filter_value）
   だけを使う。新しいディメンションを登録しなくてもGA4の探索で内訳が見られる。

   ★二重計上を避ける設計：医院ページは自前の [data-odr-ev] 委譲スクリプトを
   持ち、電話・公式・地図を clinic_to_* として送っている。そのためこの共通処理は
   [data-odr-ev] を持つ要素には一切触れない（医院ページの電話は clinic_to_tel の
   まま・ここでは重ねて送らない）。
   ========================================================= */
(function () {
  function track(name, label) {
    if (typeof window.odrTrack !== "function") return;
    window.odrTrack(name, label ? { filter_value: label } : {});
  }

  /* 掲載相談の窓口ページ。都市・業種が変わってもファイル名は共通のため名前で判定する */
  function contactPageLabel(href) {
    if (/for-clinics(\.html)?(\?|#|$)/.test(href)) return "掲載相談の窓口";
    if (/teisei(\.html)?(\?|#|$)/.test(href)) return "情報の修正依頼";
    return "";
  }

  document.addEventListener("click", function (ev) {
    var a = ev.target && ev.target.closest ? ev.target.closest("a[href]") : null;
    if (!a) return;
    /* 医院ページ等の専用計測が付いている要素はそちらに任せる（二重計上の防止） */
    if (a.hasAttribute("data-odr-ev")) return;

    var href = a.getAttribute("href") || "";
    if (/^tel:/i.test(href)) {
      track("tel_click", a.closest(".rr-sticky") ? "追従バー" : "本文");
      return;
    }
    if (/^mailto:/i.test(href)) {
      /* 個人情報を送らない：宛先が運営の窓口アドレス（info@等の役職アドレス）の時だけ
         その名前を送り、それ以外は宛先を伏せる。件名・本文のクエリも送らない。 */
      var to = href.replace(/^mailto:/i, "").split("?")[0];
      var local = to.split("@")[0].toLowerCase();
      var isRole = /^(info|contact|support|office|admin|inquiry)$/.test(local);
      track("mail_click", isRole ? to : "その他の宛先");
      return;
    }
    var label = contactPageLabel(href);
    if (label) {
      /* どのページから窓口へ入ったかが分かるとCVの入口が特定できる */
      var from = (location.pathname.split("/").filter(Boolean).pop() || "トップ").replace(/\.html$/, "");
      track("contact_nav", label + "←" + decodeURIComponent(from));
    }
  }, true);

  /* フォーム到達（表示された時点で1回だけ）。送信率＝送信÷到達の分母になる */
  function watchForms() {
    if (typeof IntersectionObserver !== "function") return;
    var forms = document.querySelectorAll("form[id]:not([data-odr-formobs])");
    if (!forms.length) return;
    var io = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (!entries[i].isIntersecting) continue;
        var f = entries[i].target;
        io.unobserve(f);
        if (f.getAttribute("data-odr-formseen") === "1") continue;
        f.setAttribute("data-odr-formseen", "1");
        track("contact_form_view", f.id);
      }
    }, { threshold: 0.3 });
    for (var i = 0; i < forms.length; i++) {
      forms[i].setAttribute("data-odr-formobs", "1");
      io.observe(forms[i]);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", watchForms);
  } else {
    watchForms();
  }
  /* 動的に描画されるフォームにも使えるよう外部へ公開 */
  window.odrObserveForms = watchForms;
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
