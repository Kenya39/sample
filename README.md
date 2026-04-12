# 固定資産税評価 WebGIS

国土地理院が公開している地形図タイルを背景地図として使用した WebGIS と、
固定資産税の土地評価を行う API を **Node.js 単一モジュール**で提供するサーバーです。

## アーキテクチャ

```
┌──────────────────────────────────────────────────────┐
│                    ブラウザ (WebGIS)                   │
│  Leaflet.js + 国土地理院タイル + Leaflet.draw          │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP (同一オリジン)
                       ▼
┌──────────────────────────────────────────────────────┐
│         Node.js + Express  (server.js)                │
│                                                      │
│  GET  /              → public/index.html             │
│  GET  /api/health    → ヘルスチェック                 │
│  POST /api/evaluate  → evaluator.js で評価額計算      │
│  GET  /api/correction-tables → 補正率テーブル          │
└──────────────────────────────────────────────────────┘
```

## ディレクトリ構成

```
.
├── server.js           # Express サーバー（静的配信 + API）
├── evaluator.js        # 固定資産税評価計算エンジン
├── package.json
├── Dockerfile
├── docker-compose.yml
└── public/             # WebGIS フロントエンド（静的ファイル）
    ├── index.html
    ├── css/style.css
    └── js/app.js
```

## 起動方法

### Node.js 直接起動

```bash
npm install
node server.js
# または開発時（ファイル変更で自動再起動）
npm run dev
```

アクセス: http://localhost:3002

### Docker Compose

```bash
docker compose up --build
```

アクセス: http://localhost:3002

### ポート変更

```bash
PORT=3000 node server.js
```

## API 仕様

### GET /api/health

```json
{ "status": "ok", "version": "1.0.0" }
```

### POST /api/evaluate

リクエスト例:

```bash
curl -X POST http://localhost:3002/api/evaluate \
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
  "land_area": 150,
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

## 適用している補正（財産評価基本通達準拠）

| 補正項目 | 根拠 |
|---|---|
| 奥行価格補正率 | 別表1 |
| 間口狭小補正率 | 付表6 |
| 奥行長大補正率 | 付表7 |
| 角地加算（側方路線影響加算率） | 付表4 |
| 不整形地補正率 | ユーザー入力（0.60〜1.00） |
| 無道路地補正率 | 評価額 × 0.60 |
| 住宅用地特例 | 地方税法第349条の3の2 |

## 地図データ出典

© [国土地理院](https://www.gsi.go.jp/)
