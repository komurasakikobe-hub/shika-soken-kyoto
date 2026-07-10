"use strict";
/* =========================================================
   サイト設定（ブラウザ側）。都市展開時はこのファイルを都市ごとに差し替える。
   site_config.json（Python側）と内容を揃えること。
   ga4MeasurementIds は [shika-sokenアカウントのID, kokedamaアカウントのID] の2枠固定。
   どちらも空文字の間、計測は無効。片方だけ設定された状態でも動く（横展開マニュアル§2-5）。
   ========================================================= */
window.ODR_CONFIG = {
  city: "京都市",
  cityShort: "京都",
  siteName: "京都歯科総研",
  ga4MeasurementIds: [
    "",  // shika-soken
    "",  // kokedama
  ],
};
