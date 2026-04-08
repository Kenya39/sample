'use strict';

/**
 * 固定資産税評価エンジン
 *
 * 財産評価基本通達および固定資産評価基準に準拠した
 * 土地評価額・税額の計算ロジック。
 *
 * 参考:
 *   - 国税庁「財産評価基本通達」
 *   - 総務省「固定資産評価基準」
 */

// -------------------------------------------------------
// 奥行価格補正率テーブル（財産評価基本通達 別表1）
// 列: [奥行上限(未満), ビル街, 高度商業, 普通商業, 普通住宅, 大工場]
// -------------------------------------------------------
const DEPTH_RATE_TABLE = [
  [  4,  0.80, 0.90, 0.90, 0.90, 0.85],
  [  6,  0.92, 0.92, 0.92, 0.92, 0.90],
  [  8,  0.84, 0.95, 0.95, 0.95, 0.93],
  [ 10,  0.88, 0.97, 0.97, 0.97, 0.95],
  [ 12,  0.90, 0.99, 0.99, 0.99, 0.96],
  [ 14,  0.91, 1.00, 1.00, 1.00, 0.97],
  [ 16,  0.92, 1.00, 1.00, 1.00, 0.98],
  [ 20,  0.93, 1.00, 1.00, 1.00, 0.99],
  [ 24,  0.94, 1.00, 1.00, 1.00, 1.00],
  [ 28,  0.95, 1.00, 1.00, 1.00, 1.00],
  [ 32,  0.96, 0.98, 0.98, 1.00, 1.00],
  [ 36,  0.97, 0.96, 0.96, 0.98, 1.00],
  [ 40,  0.98, 0.94, 0.94, 0.96, 1.00],
  [ 44,  0.99, 0.92, 0.92, 0.94, 1.00],
  [ 48,  1.00, 0.90, 0.91, 0.92, 1.00],
  [ 52,  1.00, 0.88, 0.90, 0.90, 1.00],
  [ 56,  1.00, 0.87, 0.89, 0.88, 0.99],
  [ 60,  1.00, 0.86, 0.88, 0.87, 0.98],
  [ 64,  1.00, 0.85, 0.87, 0.86, 0.96],
  [ 68,  1.00, 0.84, 0.86, 0.85, 0.94],
  [ 72,  1.00, 0.83, 0.85, 0.84, 0.92],
  [ 76,  1.00, 0.82, 0.84, 0.83, 0.90],
  [ 80,  1.00, 0.81, 0.83, 0.82, 0.88],
  [ 84,  1.00, 0.80, 0.82, 0.81, 0.86],
  [ 88,  1.00, 0.80, 0.81, 0.80, 0.84],
  [ 92,  1.00, 0.80, 0.80, 0.80, 0.82],
  [ 96,  1.00, 0.80, 0.80, 0.80, 0.80],
  [100,  1.00, 0.80, 0.80, 0.80, 0.80],
  [Infinity, 1.00, 0.80, 0.80, 0.80, 0.80],
];

// 用途地域 → テーブル列インデックス
const ZONE_COL = {
  building:          1,
  commercial_high:   2,
  commercial_normal: 3,
  residential:       4,
  large_factory:     5,
};

// -------------------------------------------------------
// 間口狭小補正率テーブル（財産評価基本通達 付表6）
// [間口上限(未満), 補正率]
// -------------------------------------------------------
const FRONTAGE_NARROW_TABLE = [
  [ 4,  0.85],
  [ 6,  0.90],
  [ 8,  0.95],
  [10,  0.97],
  [16,  0.98],
  [22,  0.99],
  [28,  1.00],
  [Infinity, 1.00],
];

// -------------------------------------------------------
// 奥行長大補正率テーブル（奥行/間口 比率）
// [比率上限(未満), 補正率]
// -------------------------------------------------------
const DEPTH_LONG_TABLE = [
  [2, 1.00],
  [3, 0.98],
  [4, 0.96],
  [5, 0.94],
  [6, 0.92],
  [7, 0.90],
  [Infinity, 0.88],
];

// -------------------------------------------------------
// 角地加算率（側方路線影響加算率）（財産評価基本通達 付表4）
// -------------------------------------------------------
const CORNER_ADD_RATE = {
  building:          0.10,
  commercial_high:   0.08,
  commercial_normal: 0.08,
  residential:       0.03,
  large_factory:     0.02,
};

const NO_ROAD_RATE = 0.60;

// -------------------------------------------------------
// 内部ヘルパー関数
// -------------------------------------------------------

function getDepthCorrectionRate(depthM, zone) {
  const col = ZONE_COL[zone] ?? 4;
  for (const row of DEPTH_RATE_TABLE) {
    if (depthM < row[0]) return row[col];
  }
  return DEPTH_RATE_TABLE.at(-1)[col];
}

function getFrontageNarrowRate(frontageM) {
  for (const [limit, rate] of FRONTAGE_NARROW_TABLE) {
    if (frontageM < limit) return rate;
  }
  return 1.00;
}

function getDepthLongRate(frontageM, depthM) {
  if (!frontageM || frontageM <= 0) return 1.00;
  const ratio = depthM / frontageM;
  for (const [limit, rate] of DEPTH_LONG_TABLE) {
    if (ratio < limit) return rate;
  }
  return 0.88;
}

// -------------------------------------------------------
// メイン評価関数
// -------------------------------------------------------

/**
 * 土地の固定資産税評価額・税額を計算して返す。
 *
 * @param {object} req - 評価リクエストオブジェクト
 * @returns {object} 評価レスポンスオブジェクト
 * @throws {Error} 入力値が不正な場合
 */
function evaluateLand(req) {
  if (!req.land_area || req.land_area <= 0) {
    throw new Error('地積は 0 より大きい値を入力してください');
  }
  if (req.road_price == null || req.road_price < 0) {
    throw new Error('路線価は 0 以上の値を入力してください');
  }

  const factors = [];

  // 1. 奥行価格補正率
  let depthRate = 1.00;
  if (req.depth && req.depth > 0) {
    depthRate = getDepthCorrectionRate(req.depth, req.zone_type);
    factors.push({ name: '奥行価格補正率', rate: depthRate });
  }

  // 2. 間口狭小補正率 × 奥行長大補正率
  let frontageRate = 1.00;
  let depthLongRate = 1.00;
  if (req.frontage && req.frontage > 0) {
    frontageRate = getFrontageNarrowRate(req.frontage);
    if (frontageRate < 1.00) {
      factors.push({ name: '間口狭小補正率', rate: frontageRate });
    }
    if (req.depth && req.depth > 0) {
      depthLongRate = getDepthLongRate(req.frontage, req.depth);
      if (depthLongRate < 1.00) {
        factors.push({ name: '奥行長大補正率', rate: depthLongRate });
      }
    }
  }

  // 3. 角地加算（側方路線影響加算）
  let cornerAdd = 0.00;
  if (req.is_corner && req.side_road_price && req.side_road_price > 0) {
    const addRate = CORNER_ADD_RATE[req.zone_type] ?? 0.03;
    cornerAdd = req.side_road_price * depthRate * addRate;
    factors.push({ name: `角地加算（側方路線影響加算率 ${addRate.toFixed(2)}）`, rate: addRate });
  }

  // 4. 不整形地補正率
  let irregularRate = 1.00;
  if (req.is_irregular) {
    irregularRate = req.irregular_rate ?? 0.90;
    factors.push({ name: '不整形地補正率', rate: irregularRate });
  }

  // 5. 無道路地補正率
  let noRoadRate = 1.00;
  if (req.is_no_road) {
    noRoadRate = NO_ROAD_RATE;
    factors.push({ name: '無道路地補正率', rate: noRoadRate });
  }

  // 6. 評価額計算
  let assessedValue;
  let combinedMult;

  if (req.land_category === 'agricultural' || req.land_category === 'forest') {
    // 農地・山林: 路線価を素地価格として 0.40 を乗じる（簡易計算）
    const landRatio = 0.40;
    factors.push({ name: '農地・山林 評価率', rate: landRatio });
    assessedValue = req.road_price * landRatio * req.land_area;
    combinedMult = landRatio;
  } else {
    const unitPrice = req.road_price * depthRate + cornerAdd;
    combinedMult = frontageRate * depthLongRate * irregularRate * noRoadRate;
    assessedValue = unitPrice * combinedMult * req.land_area;
  }

  const totalCorrection = depthRate * combinedMult;

  if (factors.length === 0) {
    factors.push({ name: '（補正なし）', rate: 1.00 });
  }

  // 7. 住宅用地特例（課税標準の軽減）
  let taxableBase;
  let reductionLabel;

  switch (req.land_category) {
    case 'residential_small':
      taxableBase = assessedValue / 6.0;
      reductionLabel = '小規模住宅用地特例 (1/6) 適用';
      break;
    case 'residential_general':
      taxableBase = assessedValue / 3.0;
      reductionLabel = '一般住宅用地特例 (1/3) 適用';
      break;
    default:
      taxableBase = assessedValue;
      reductionLabel = '住宅用地特例なし（非住宅用地）';
  }

  // 8. 税額計算
  const taxRate = req.tax_rate ?? 0.014;
  const fixedAssetTax = taxableBase * taxRate;

  let cityPlanTax = null;
  let cityPlanRate = null;
  if (req.city_plan_area) {
    cityPlanRate = req.city_plan_rate ?? 0.003;
    cityPlanTax = taxableBase * cityPlanRate;
  }

  return {
    land_area:          req.land_area,
    road_price:         req.road_price,
    correction_factors: factors,
    total_correction:   totalCorrection,
    assessed_value:     Math.round(assessedValue),
    taxable_base:       Math.round(taxableBase),
    reduction_label:    reductionLabel,
    tax_rate:           taxRate,
    fixed_asset_tax:    Math.round(fixedAssetTax),
    city_plan_rate:     cityPlanRate,
    city_plan_tax:      cityPlanTax !== null ? Math.round(cityPlanTax) : null,
  };
}

module.exports = {
  evaluateLand,
  DEPTH_RATE_TABLE,
  FRONTAGE_NARROW_TABLE,
  DEPTH_LONG_TABLE,
  CORNER_ADD_RATE,
};
