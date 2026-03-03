"""
固定資産税評価マイクロサービス – データモデル
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# -------------------------------------------------------
# 列挙型
# -------------------------------------------------------

class LandCategory(str, Enum):
    """地目区分"""
    RESIDENTIAL_SMALL   = "residential_small"   # 宅地・小規模住宅用地（200㎡以下）
    RESIDENTIAL_GENERAL = "residential_general"  # 宅地・一般住宅用地（200㎡超）
    COMMERCIAL          = "commercial"           # 宅地・商業用
    AGRICULTURAL        = "agricultural"         # 農地（田・畑）
    FOREST              = "forest"               # 山林
    OTHER               = "other"                # その他


class ZoneType(str, Enum):
    """用途地域区分（奥行価格補正率テーブル対応）"""
    BUILDING           = "building"           # ビル街地区
    COMMERCIAL_HIGH    = "commercial_high"    # 高度商業・繁華街地区
    COMMERCIAL_NORMAL  = "commercial_normal"  # 普通商業・併用住宅地区
    RESIDENTIAL        = "residential"        # 普通住宅・中小工場地区
    LARGE_FACTORY      = "large_factory"      # 大工場地区


# -------------------------------------------------------
# リクエスト
# -------------------------------------------------------

class EvaluationRequest(BaseModel):
    """土地評価リクエスト"""

    # 土地基本情報
    land_category: LandCategory = Field(
        default=LandCategory.RESIDENTIAL_SMALL,
        description="地目区分",
    )
    land_area: float = Field(
        gt=0,
        description="地積（㎡）",
    )
    address: Optional[str] = Field(
        default=None,
        description="所在地（任意）",
    )
    geojson: Optional[Dict[str, Any]] = Field(
        default=None,
        description="土地区画 GeoJSON（任意）",
    )

    # 路線価・地形情報
    zone_type: ZoneType = Field(
        default=ZoneType.RESIDENTIAL,
        description="用途地域区分",
    )
    road_price: float = Field(
        ge=0,
        description="正面路線価（円/㎡）",
    )
    frontage: Optional[float] = Field(
        default=None,
        ge=0,
        description="間口距離（m）",
    )
    depth: Optional[float] = Field(
        default=None,
        ge=0,
        description="奥行距離（m）",
    )
    is_corner: bool = Field(
        default=False,
        description="角地フラグ",
    )
    side_road_price: Optional[float] = Field(
        default=None,
        ge=0,
        description="側方路線価（角地の場合、円/㎡）",
    )
    is_irregular: bool = Field(
        default=False,
        description="不整形地フラグ",
    )
    irregular_rate: Optional[float] = Field(
        default=None,
        ge=0.60,
        le=1.00,
        description="不整形地補正率（0.60〜1.00、is_irregular=True の場合）",
    )
    is_no_road: bool = Field(
        default=False,
        description="無道路地フラグ",
    )

    # 都市計画・税率
    city_plan_area: bool = Field(
        default=False,
        description="都市計画区域内フラグ",
    )
    tax_rate: float = Field(
        default=0.014,
        ge=0,
        le=0.1,
        description="固定資産税率（デフォルト 1.4%）",
    )
    city_plan_rate: float = Field(
        default=0.003,
        ge=0,
        le=0.01,
        description="都市計画税率（デフォルト 0.3%）",
    )

    @field_validator("land_area")
    @classmethod
    def validate_area(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("地積は 0 より大きい値を入力してください")
        return round(v, 4)

    @field_validator("road_price")
    @classmethod
    def validate_road_price(cls, v: float) -> float:
        if v < 0:
            raise ValueError("路線価は 0 以上の値を入力してください")
        return v

    model_config = {"use_enum_values": True}


# -------------------------------------------------------
# レスポンス
# -------------------------------------------------------

class CorrectionFactor(BaseModel):
    """補正係数の内訳"""
    name: str = Field(description="補正項目名")
    rate: float = Field(description="補正率")


class EvaluationResponse(BaseModel):
    """土地評価レスポンス"""

    # 入力エコーバック
    land_area: float = Field(description="地積（㎡）")
    road_price: float = Field(description="正面路線価（円/㎡）")

    # 補正情報
    correction_factors: List[CorrectionFactor] = Field(
        description="適用した補正係数の一覧"
    )
    total_correction: float = Field(description="複合補正率")

    # 評価額
    assessed_value: float = Field(description="固定資産税評価額（円）")

    # 課税標準
    taxable_base: float = Field(description="課税標準額（円）")
    reduction_label: str = Field(description="住宅用地特例の説明")

    # 税額
    tax_rate: float = Field(description="固定資産税率")
    fixed_asset_tax: float = Field(description="固定資産税（円/年）")
    city_plan_rate: Optional[float] = Field(
        default=None, description="都市計画税率"
    )
    city_plan_tax: Optional[float] = Field(
        default=None, description="都市計画税（円/年）"
    )


class HealthResponse(BaseModel):
    status: str
    version: str
