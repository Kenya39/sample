'use strict';

/**
 * 固定資産税評価 WebGIS サーバー
 *
 * Express.js による単一モジュール構成。
 * 静的ファイル（WebGIS）の配信と評価 API の両方を担う。
 *
 * 起動方法:
 *   node server.js
 *   PORT=3000 node server.js  # ポート指定
 */

const express = require('express');
const path    = require('path');
const {
  evaluateLand,
  DEPTH_RATE_TABLE,
  FRONTAGE_NARROW_TABLE,
  DEPTH_LONG_TABLE,
  CORNER_ADD_RATE,
} = require('./evaluator');

const VERSION = '1.0.0';
const PORT    = process.env.PORT || 3002;

const app = express();

// リバースプロキシ（nginx / Apache / Caddy 等）経由を信頼する。
// X-Forwarded-For / X-Forwarded-Proto ヘッダーを正しく解釈するために必要。
app.set('trust proxy', true);

// -------------------------------------------------------
// ミドルウェア
// -------------------------------------------------------
app.use(express.json());

// -------------------------------------------------------
// API ルート（express.static より先に登録し確実に優先させる）
// -------------------------------------------------------

/** ヘルスチェック */
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', version: VERSION });
});

/**
 * 土地評価
 *
 * リクエストボディ (JSON):
 *   land_category   string   地目区分
 *   land_area       number   地積（㎡）
 *   zone_type       string   用途地域区分
 *   road_price      number   正面路線価（円/㎡）
 *   frontage        number?  間口距離（m）
 *   depth           number?  奥行距離（m）
 *   is_corner       bool     角地フラグ
 *   side_road_price number?  側方路線価（円/㎡）
 *   is_irregular    bool     不整形地フラグ
 *   irregular_rate  number?  不整形地補正率（0.60〜1.00）
 *   is_no_road      bool     無道路地フラグ
 *   city_plan_area  bool     都市計画区域内フラグ
 *   tax_rate        number   固定資産税率（例: 0.014）
 *   city_plan_rate  number   都市計画税率（例: 0.003）
 */
app.post('/api/evaluate', (req, res) => {
  try {
    const result = evaluateLand(req.body);
    console.log(
      `[evaluate] 地積=${result.land_area}㎡ 路線価=${result.road_price}円/㎡`
      + ` → 評価額=${result.assessed_value.toLocaleString()}円`
      + ` 固定資産税=${result.fixed_asset_tax.toLocaleString()}円/年`
    );
    res.json(result);
  } catch (err) {
    res.status(422).json({ detail: err.message });
  }
});

/** 補正率テーブル一覧 */
app.get('/api/correction-tables', (_req, res) => {
  const depthTable = DEPTH_RATE_TABLE.map(row => ({
    depth_less_than:   row[0] === Infinity ? null : row[0],
    building:          row[1],
    commercial_high:   row[2],
    commercial_normal: row[3],
    residential:       row[4],
    large_factory:     row[5],
  }));

  const frontageTable = FRONTAGE_NARROW_TABLE.map(([limit, rate]) => ({
    frontage_less_than: limit === Infinity ? null : limit,
    rate,
  }));

  const depthLongTable = DEPTH_LONG_TABLE.map(([limit, rate]) => ({
    ratio_less_than: limit === Infinity ? null : limit,
    rate,
  }));

  res.json({
    depth_correction:            depthTable,
    frontage_narrow_correction:  frontageTable,
    depth_long_correction:       depthLongTable,
    corner_addition_rates:       CORNER_ADD_RATE,
  });
});

// -------------------------------------------------------
// 静的ファイル配信（WebGIS フロントエンド）
// -------------------------------------------------------
app.use(express.static(path.join(__dirname, 'public')));

// -------------------------------------------------------
// SPA フォールバック（直接 URL アクセス対応）
// -------------------------------------------------------
app.get('*', (_req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// -------------------------------------------------------
// 起動
// -------------------------------------------------------
app.listen(PORT, () => {
  console.log(`固定資産税評価 WebGIS サーバー v${VERSION}`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  API: http://localhost:${PORT}/api/health`);
});
