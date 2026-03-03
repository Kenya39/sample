# 固定資産税評価 WebGIS

国土地理院が公開している地形図タイルを背景地図として使用した WebGIS と、
そこから呼び出して固定資産税の土地評価を行うマイクロサービスです。

## アーキテクチャ

```
┌────────────────────────────────────────────────────────────┐
│                      ブラウザ (WebGIS)                      │
│  ┌──────────────────────┐  ┌──────────────────────────┐    │
│  │   Leaflet.js マップ  │  │  サイドパネル（入力フォーム）│   │
│  │  国土地理院タイル     │  │  評価結果表示              │   │
│  │  標準地図/淡色/写真  │  │                            │   │
│  │  Leaflet.draw 描画   │  │                            │   │
│  └──────────────────────┘  └───────────┬────────────────┘    │
└──────────────────────────────────────── ┼──────────────────┘
                                          │ POST /api/evaluate
                                          ▼
┌──────────────────────────────────────────────────────────────┐
│              固定資産税評価マイクロサービス (FastAPI)          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  /api/health │  │ /api/evaluate│  │ /api/correction- │  │
│  │  ヘルスチェック│  │ 評価額計算  │  │    tables        │  │
│  └──────────────┘  └──────────────┘  └──────────────────┘  │
│                        evaluator.py                          │
│              財産評価基本通達に基づく補正率テーブル             │
└──────────────────────────────────────────────────────────────┘
```

## 機能

### WebGIS フロントエンド
- **国土地理院タイルマップ**: 標準地図 / 淡色地図 / 写真 / 色別標高図
- **レイヤー切り替え**: 地図種別の切り替えコントロール
- **ポリゴン描画**: Leaflet.draw を使って土地区画を描画し、Turf.js で地積を自動計算
- **フォーム入力**: 地目・路線価・間口・奥行・角地/不整形地/無道路地フラグ
- **結果表示**: 評価額・課税標準額・固定資産税・都市計画税の一覧表示

### マイクロサービス (FastAPI)
- `POST /api/evaluate` — 土地評価額・税額計算
- `GET  /api/health`   — ヘルスチェック
- `GET  /api/correction-tables` — 補正率テーブル取得
- `GET  /docs`         — Swagger UI (OpenAPI)

#### 適用している補正
| 補正項目 | 根拠 |
|---|---|
| 奥行価格補正率 | 財産評価基本通達 別表1 |
| 間口狭小補正率 | 財産評価基本通達 付表6 |
| 奥行長大補正率 | 財産評価基本通達 付表7 |
| 角地加算（側方路線影響加算率） | 財産評価基本通達 付表4 |
| 不整形地補正率 | ユーザー入力値（0.60〜1.00） |
| 無道路地補正率 | 評価額の 60% |
| 住宅用地特例 | 地方税法第349条の3の2 |

## ディレクトリ構成

```
.
├── webgis/
│   ├── index.html          # メインページ
│   ├── css/style.css       # スタイルシート
│   └── js/app.js           # アプリケーションロジック
├── microservice/
│   ├── app.py              # FastAPI アプリケーション
│   ├── models.py           # Pydantic モデル
│   ├── evaluator.py        # 評価計算エンジン
│   ├── requirements.txt    # Python 依存パッケージ
│   └── Dockerfile
├── docker-compose.yml
├── nginx.conf
└── README.md
```

## 起動方法

### Docker Compose（推奨）

```bash
docker compose up --build
```

- WebGIS: http://localhost:8080
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs

### 個別起動

```bash
# マイクロサービス
cd microservice
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000

# WebGIS（別ターミナル）
cd webgis
python -m http.server 8080
```

WebGIS を個別起動した場合は `webgis/js/app.js` の `CONFIG.API_BASE` を
`http://localhost:8000` に設定してください（デフォルト値）。

## API 使用例

```bash
curl -X POST http://localhost:8000/api/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "land_category": "residential_small",
    "land_area": 150.0,
    "zone_type": "residential",
    "road_price": 200000,
    "frontage": 8.0,
    "depth": 18.0,
    "is_corner": false,
    "is_irregular": false,
    "is_no_road": false,
    "city_plan_area": true,
    "tax_rate": 0.014,
    "city_plan_rate": 0.003
  }'
```

レスポンス例:
```json
{
  "land_area": 150.0,
  "road_price": 200000,
  "correction_factors": [
    { "name": "奥行価格補正率", "rate": 1.0 },
    { "name": "間口狭小補正率", "rate": 0.95 }
  ],
  "total_correction": 0.95,
  "assessed_value": 28500000,
  "taxable_base": 4750000,
  "reduction_label": "小規模住宅用地特例 (1/6) 適用",
  "tax_rate": 0.014,
  "fixed_asset_tax": 66500,
  "city_plan_rate": 0.003,
  "city_plan_tax": 14250
}
```

## 注意事項

- 本システムの計算結果はあくまで**概算**です。実際の固定資産税評価額・税額は
  各市区町村の評価に基づきます。
- 路線価の入力には国税庁の路線価図（https://www.rosenka.nta.go.jp/）を参照してください。
- 固定資産税評価用の路線価は相続税評価用と異なる場合があります。

## 地図データ出典

背景地図は**国土地理院**が公開するタイルデータを使用しています。

- 標準地図: `https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png`
- 淡色地図: `https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png`
- 写真: `https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg`
- 色別標高図: `https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png`

© [国土地理院](https://www.gsi.go.jp/)
