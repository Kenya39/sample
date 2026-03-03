"""
固定資産税評価エンジン

財産評価基本通達および固定資産評価基準に準拠した
土地評価額・税額の計算ロジック。

参考:
  - 国税庁「財産評価基本通達」
  - 総務省「固定資産評価基準」
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from models import (
    CorrectionFactor,
    EvaluationRequest,
    EvaluationResponse,
    LandCategory,
    ZoneType,
)


# -------------------------------------------------------
# 奥行価格補正率テーブル
# 出典: 財産評価基本通達 別表1
# 行: 奥行距離区分（m）  列: 用途地域区分
# -------------------------------------------------------
#  (奥行上限（未満）, ビル街, 高度商業, 普通商業, 普通住宅, 大工場)
_DEPTH_RATE_TABLE: List[Tuple[float, float, float, float, float, float]] = [
    (  4,  0.80, 0.90, 0.90, 0.90, 0.85),
    (  6,  0.92, 0.92, 0.92, 0.92, 0.90),
    (  8,  0.84, 0.95, 0.95, 0.95, 0.93),
    ( 10,  0.88, 0.97, 0.97, 0.97, 0.95),
    ( 12,  0.90, 0.99, 0.99, 0.99, 0.96),
    ( 14,  0.91, 1.00, 1.00, 1.00, 0.97),
    ( 16,  0.92, 1.00, 1.00, 1.00, 0.98),
    ( 20,  0.93, 1.00, 1.00, 1.00, 0.99),
    ( 24,  0.94, 1.00, 1.00, 1.00, 1.00),
    ( 28,  0.95, 1.00, 1.00, 1.00, 1.00),
    ( 32,  0.96, 0.98, 0.98, 1.00, 1.00),
    ( 36,  0.97, 0.96, 0.96, 0.98, 1.00),
    ( 40,  0.98, 0.94, 0.94, 0.96, 1.00),
    ( 44,  0.99, 0.92, 0.92, 0.94, 1.00),
    ( 48,  1.00, 0.90, 0.91, 0.92, 1.00),
    ( 52,  1.00, 0.88, 0.90, 0.90, 1.00),
    ( 56,  1.00, 0.87, 0.89, 0.88, 0.99),
    ( 60,  1.00, 0.86, 0.88, 0.87, 0.98),
    ( 64,  1.00, 0.85, 0.87, 0.86, 0.96),
    ( 68,  1.00, 0.84, 0.86, 0.85, 0.94),
    ( 72,  1.00, 0.83, 0.85, 0.84, 0.92),
    ( 76,  1.00, 0.82, 0.84, 0.83, 0.90),
    ( 80,  1.00, 0.81, 0.83, 0.82, 0.88),
    ( 84,  1.00, 0.80, 0.82, 0.81, 0.86),
    ( 88,  1.00, 0.80, 0.81, 0.80, 0.84),
    ( 92,  1.00, 0.80, 0.80, 0.80, 0.82),
    ( 96,  1.00, 0.80, 0.80, 0.80, 0.80),
    (100,  1.00, 0.80, 0.80, 0.80, 0.80),
    (float('inf'), 1.00, 0.80, 0.80, 0.80, 0.80),
]

# ZoneType → テーブル列インデックス
_ZONE_COL: dict[str, int] = {
    ZoneType.BUILDING:          1,
    ZoneType.COMMERCIAL_HIGH:   2,
    ZoneType.COMMERCIAL_NORMAL: 3,
    ZoneType.RESIDENTIAL:       4,
    ZoneType.LARGE_FACTORY:     5,
}


def _depth_correction_rate(depth_m: float, zone: str) -> float:
    """奥行価格補正率を返す"""
    col = _ZONE_COL.get(zone, 4)
    for row in _DEPTH_RATE_TABLE:
        if depth_m < row[0]:
            return row[col]
    return _DEPTH_RATE_TABLE[-1][col]


# -------------------------------------------------------
# 間口狭小補正率テーブル
# 出典: 財産評価基本通達 付表6
# -------------------------------------------------------
#  (間口上限（未満）, 補正率)
_FRONTAGE_NARROW_TABLE: List[Tuple[float, float]] = [
    ( 4,  0.85),
    ( 6,  0.90),
    ( 8,  0.95),
    (10,  0.97),
    (16,  0.98),
    (22,  0.99),
    (28,  1.00),
    (float('inf'), 1.00),
]


def _frontage_narrow_rate(frontage_m: float) -> float:
    """間口狭小補正率を返す"""
    for limit, rate in _FRONTAGE_NARROW_TABLE:
        if frontage_m < limit:
            return rate
    return 1.00


# -------------------------------------------------------
# 奥行長大補正率テーブル
# 奥行 / 間口 比率に基づく補正
# -------------------------------------------------------
#  (奥行/間口 比上限（未満）, 補正率)
_DEPTH_LONG_TABLE: List[Tuple[float, float]] = [
    ( 2,  1.00),
    ( 3,  0.98),
    ( 4,  0.96),
    ( 5,  0.94),
    ( 6,  0.92),
    ( 7,  0.90),
    (float('inf'), 0.88),
]


def _depth_long_rate(frontage_m: float, depth_m: float) -> float:
    """奥行長大補正率を返す"""
    if frontage_m <= 0:
        return 1.00
    ratio = depth_m / frontage_m
    for limit, rate in _DEPTH_LONG_TABLE:
        if ratio < limit:
            return rate
    return 0.88


# -------------------------------------------------------
# 角地加算率（側方路線影響加算率）
# 出典: 財産評価基本通達 付表4
# -------------------------------------------------------
_CORNER_ADD_RATE: dict[str, float] = {
    ZoneType.BUILDING:          0.10,
    ZoneType.COMMERCIAL_HIGH:   0.08,
    ZoneType.COMMERCIAL_NORMAL: 0.08,
    ZoneType.RESIDENTIAL:       0.03,
    ZoneType.LARGE_FACTORY:     0.02,
}


def _corner_addition_rate(zone: str) -> float:
    return _CORNER_ADD_RATE.get(zone, 0.03)


# -------------------------------------------------------
# 無道路地補正率
# -------------------------------------------------------
_NO_ROAD_RATE = 0.60  # 原則として評価額の 60%


# -------------------------------------------------------
# メイン評価関数
# -------------------------------------------------------

def evaluate_land(req: EvaluationRequest) -> EvaluationResponse:
    """
    土地の固定資産税評価額・税額を計算して返す。

    宅地（路線価方式）:
        評価額 = 正面路線価 × 奥行価格補正率 × 各種補正率 × 地積

    農地・山林:
        簡易評価（路線価を素地価格として利用）

    住宅用地特例:
        小規模（≤200㎡）: 課税標準 = 評価額 × 1/6
        一般 (>200㎡):   課税標準 = 評価額 × 1/3
        商業・非住宅:     課税標準 = 評価額
    """
    factors: List[CorrectionFactor] = []

    # --------------------------------------------------
    # 1. 正面路線価 × 奥行価格補正率
    # --------------------------------------------------
    depth_rate = 1.00
    if req.depth and req.depth > 0:
        depth_rate = _depth_correction_rate(req.depth, req.zone_type)
        factors.append(CorrectionFactor(name="奥行価格補正率", rate=depth_rate))

    # --------------------------------------------------
    # 2. 間口狭小補正率 × 奥行長大補正率
    # --------------------------------------------------
    frontage_rate = 1.00
    depth_long_rate = 1.00
    if req.frontage and req.frontage > 0:
        frontage_rate = _frontage_narrow_rate(req.frontage)
        if frontage_rate < 1.00:
            factors.append(CorrectionFactor(name="間口狭小補正率", rate=frontage_rate))

        if req.depth and req.depth > 0:
            depth_long_rate = _depth_long_rate(req.frontage, req.depth)
            if depth_long_rate < 1.00:
                factors.append(CorrectionFactor(name="奥行長大補正率", rate=depth_long_rate))

    # --------------------------------------------------
    # 3. 角地加算（側方路線影響加算）
    # --------------------------------------------------
    corner_add = 0.00
    if req.is_corner and req.side_road_price and req.side_road_price > 0:
        add_rate = _corner_addition_rate(req.zone_type)
        # 側方路線価 × 奥行補正率 × 加算率 で加算額を決定
        side_depth_rate = depth_rate  # 奥行は共通とみなす
        corner_add = req.side_road_price * side_depth_rate * add_rate
        factors.append(CorrectionFactor(
            name=f"角地加算（側方路線影響加算率 {add_rate:.2f}）",
            rate=add_rate,
        ))

    # --------------------------------------------------
    # 4. 不整形地補正率
    # --------------------------------------------------
    irregular_rate = 1.00
    if req.is_irregular:
        irregular_rate = req.irregular_rate if req.irregular_rate else 0.90
        factors.append(CorrectionFactor(name="不整形地補正率", rate=irregular_rate))

    # --------------------------------------------------
    # 5. 無道路地補正率
    # --------------------------------------------------
    no_road_rate = 1.00
    if req.is_no_road:
        no_road_rate = _NO_ROAD_RATE
        factors.append(CorrectionFactor(name="無道路地補正率", rate=no_road_rate))

    # --------------------------------------------------
    # 6. 評価額計算
    # --------------------------------------------------
    # 路線価は 千円/㎡ 単位の場合もあるが、ここでは 円/㎡ 入力を前提とする
    unit_price = (
        req.road_price * depth_rate
        + corner_add
    )
    # 間口・奥行長大・不整形・無道路補正を乗算
    combined_mult = frontage_rate * depth_long_rate * irregular_rate * no_road_rate

    # 農地・山林の場合は路線価を素地価格として直接利用（簡易計算）
    if req.land_category in (LandCategory.AGRICULTURAL, LandCategory.FOREST):
        # 農地等の評価率は概ね 30〜50% を乗じる（ここでは 0.40 をデフォルト）
        land_ratio = 0.40
        factors.append(CorrectionFactor(name="農地・山林 評価率", rate=land_ratio))
        assessed_value = req.road_price * land_ratio * req.land_area
        combined_mult = land_ratio
    else:
        assessed_value = unit_price * combined_mult * req.land_area

    # 複合補正率（小数点以下4桁）
    total_correction = depth_rate * combined_mult
    if not factors:
        factors.append(CorrectionFactor(name="（補正なし）", rate=1.00))

    # --------------------------------------------------
    # 7. 住宅用地特例（課税標準の軽減）
    # --------------------------------------------------
    category = req.land_category

    if category == LandCategory.RESIDENTIAL_SMALL:
        # 小規模住宅用地（200㎡以下）: 1/6
        taxable_base = assessed_value / 6.0
        reduction_label = "小規模住宅用地特例 (1/6) 適用"
    elif category == LandCategory.RESIDENTIAL_GENERAL:
        # 一般住宅用地（200㎡超）: 1/3
        taxable_base = assessed_value / 3.0
        reduction_label = "一般住宅用地特例 (1/3) 適用"
    else:
        taxable_base = assessed_value
        reduction_label = "住宅用地特例なし（非住宅用地）"

    # --------------------------------------------------
    # 8. 税額計算
    # --------------------------------------------------
    fixed_asset_tax = taxable_base * req.tax_rate

    city_plan_tax: Optional[float] = None
    city_plan_rate: Optional[float] = None
    if req.city_plan_area:
        city_plan_rate = req.city_plan_rate
        city_plan_tax = taxable_base * city_plan_rate

    return EvaluationResponse(
        land_area=req.land_area,
        road_price=req.road_price,
        correction_factors=factors,
        total_correction=total_correction,
        assessed_value=round(assessed_value, 0),
        taxable_base=round(taxable_base, 0),
        reduction_label=reduction_label,
        tax_rate=req.tax_rate,
        fixed_asset_tax=round(fixed_asset_tax, 0),
        city_plan_rate=city_plan_rate,
        city_plan_tax=round(city_plan_tax, 0) if city_plan_tax is not None else None,
    )
