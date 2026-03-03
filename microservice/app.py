"""
固定資産税評価マイクロサービス
FastAPI アプリケーション

起動方法:
    uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from evaluator import evaluate_land
from models import EvaluationRequest, EvaluationResponse, HealthResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

VERSION = "1.0.0"


# -------------------------------------------------------
# アプリケーション
# -------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("固定資産税評価マイクロサービス 起動 (v%s)", VERSION)
    yield
    logger.info("サービス停止")


app = FastAPI(
    title="固定資産税評価マイクロサービス",
    description=(
        "国土地理院 WebGIS と連携し、土地の固定資産税評価額および税額を計算するAPIです。\n\n"
        "## 主な機能\n"
        "- 宅地（路線価方式）・農地・山林の評価額計算\n"
        "- 奥行価格補正・間口狭小補正・角地加算・不整形地補正の適用\n"
        "- 住宅用地特例（小規模 1/6、一般 1/3）の自動適用\n"
        "- 固定資産税・都市計画税の計算\n\n"
        "## 参考法令\n"
        "- 地方税法第349条\n"
        "- 固定資産評価基準（総務省告示）\n"
        "- 財産評価基本通達（国税庁）"
    ),
    version=VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS（WebGIS フロントエンドからの呼び出しを許可）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 本番環境では適切なオリジンに制限すること
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# -------------------------------------------------------
# ルーター
# -------------------------------------------------------

@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="ヘルスチェック",
    tags=["システム"],
)
async def health_check() -> HealthResponse:
    """サービスの稼働状態を確認します。"""
    return HealthResponse(status="ok", version=VERSION)


@app.post(
    "/api/evaluate",
    response_model=EvaluationResponse,
    summary="土地の固定資産税評価",
    tags=["評価"],
)
async def evaluate(req: EvaluationRequest) -> EvaluationResponse:
    """
    土地情報を受け取り、固定資産税評価額および税額を返します。

    ### 計算フロー

    1. **路線価 × 奥行価格補正率** で単位地積当たりの評価単価を算出
    2. **間口狭小補正・奥行長大補正・角地加算・不整形地補正・無道路地補正** を適用
    3. 評価単価 × 地積 = **評価額**
    4. 住宅用地特例（地目区分に応じて 1/6 または 1/3）を適用し **課税標準額** を算出
    5. 課税標準額 × 税率 = **固定資産税額**
    6. 都市計画区域内の場合、課税標準額 × 都市計画税率 = **都市計画税額**
    """
    logger.info(
        "評価リクエスト: 地目=%s 地積=%.2f㎡ 路線価=%.0f円/㎡",
        req.land_category,
        req.land_area,
        req.road_price,
    )
    try:
        result = evaluate_land(req)
        logger.info(
            "評価完了: 評価額=%.0f円 固定資産税=%.0f円/年",
            result.assessed_value,
            result.fixed_asset_tax,
        )
        return result
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("評価処理中にエラーが発生しました")
        raise HTTPException(status_code=500, detail="評価処理中にエラーが発生しました") from exc


@app.get(
    "/api/correction-tables",
    summary="補正率テーブル取得",
    tags=["評価"],
)
async def get_correction_tables() -> dict:
    """
    評価計算に使用する補正率テーブルの一覧を返します。

    - 奥行価格補正率テーブル（用途地域別）
    - 間口狭小補正率テーブル
    - 奥行長大補正率テーブル
    - 角地加算率テーブル（用途地域別）
    """
    from evaluator import (
        _CORNER_ADD_RATE,
        _DEPTH_LONG_TABLE,
        _DEPTH_RATE_TABLE,
        _FRONTAGE_NARROW_TABLE,
    )

    depth_table = []
    for row in _DEPTH_RATE_TABLE:
        depth_table.append({
            "depth_less_than": row[0] if row[0] != float("inf") else None,
            "building": row[1],
            "commercial_high": row[2],
            "commercial_normal": row[3],
            "residential": row[4],
            "large_factory": row[5],
        })

    frontage_table = [
        {"frontage_less_than": r[0] if r[0] != float("inf") else None, "rate": r[1]}
        for r in _FRONTAGE_NARROW_TABLE
    ]

    depth_long_table = [
        {"ratio_less_than": r[0] if r[0] != float("inf") else None, "rate": r[1]}
        for r in _DEPTH_LONG_TABLE
    ]

    return {
        "depth_correction": depth_table,
        "frontage_narrow_correction": frontage_table,
        "depth_long_correction": depth_long_table,
        "corner_addition_rates": _CORNER_ADD_RATE,
    }


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service": "固定資産税評価マイクロサービス",
        "version": VERSION,
        "docs": "/docs",
        "health": "/api/health",
    }
