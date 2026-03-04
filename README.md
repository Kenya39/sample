# OSM道路中心線データダウンローダー

OpenStreetMapから道路の中心線データをダウンロードするPythonツール。
都道府県・市区町村・バウンディングボックス単位でのダウンロードに対応し、GeoJSON出力・PostGIS/MariaDB格納・Leafletビューアを提供します。

---

## ファイル構成

| ファイル | 説明 |
|---|---|
| `osm_road_downloader.py` | メインスクリプト（CLI） |
| `requirements.txt` | Python依存パッケージ |
| `leaflet_road_viewer.html` | Leafletベースのブラウザビューア |

---

## セットアップ

```bash
pip install -r requirements.txt
```

PostGIS格納を使用する場合:
```bash
pip install psycopg2-binary
```

MariaDB格納を使用する場合:
```bash
pip install mysql-connector-python
```

---

## 使用方法

### 基本オプション

| オプション | 説明 | デフォルト |
|---|---|---|
| `--level` | ダウンロード粒度（prefecture / municipality / nationwide / bbox） | 必須 |
| `--target` | 対象地名またはbbox座標 | 必須（nationwide以外） |
| `--road-type` | 道路種別（all / major / general / motorway） | `general` |
| `--output` | 出力形式（geojson / postgis / mariadb / both） | `geojson` |
| `--output-file` | GeoJSON出力ファイルパス | 自動命名 |
| `--output-dir` | GeoJSON出力ディレクトリ | `./osm_data` |

### 道路種別フィルタ

| キー | 対象道路 |
|---|---|
| `motorway` | 高速道路のみ |
| `major` | 高速道路・国道・都道府県道 |
| `general` | 上記＋市町村道・住宅地道路・未分類（**デフォルト**） |
| `all` | 歩道・農道・自転車道を含む全道路 |

---

## 使用例

### GeoJSONダウンロード

```bash
# 都道府県単位
python osm_road_downloader.py --level prefecture --target 東京都

# 市区町村単位（主要道路のみ）
python osm_road_downloader.py --level municipality --target 千代田区 --road-type major

# バウンディングボックス指定（南緯,西経,北緯,東経）
python osm_road_downloader.py --level bbox --target "35.6,139.6,35.8,139.9"

# 出力ファイル名を指定
python osm_road_downloader.py --level prefecture --target 大阪府 --output-file osaka.geojson
```

### 全国一括ダウンロード（都道府県ごとに分割）

```bash
python osm_road_downloader.py --level nationwide --road-type general --output-dir ./osm_data
```

> **注意**: Overpass APIのレート制限により、都道府県間に5秒の待機を挟みます。
> `--delay` オプションで待機時間を変更できます。

---

### PostGISへの格納

```bash
# テーブル: public.osm_roads（自動作成）
python osm_road_downloader.py \
    --level prefecture --target 神奈川県 \
    --output postgis \
    --db-host localhost --db-port 5432 \
    --db-name gisdb --db-user postgres --db-password secret

# GeoJSONにも同時保存（both）
python osm_road_downloader.py \
    --level prefecture --target 神奈川県 \
    --output both \
    --db-host localhost --db-name gisdb --db-user postgres
```

PostGISで作成されるテーブル:
```sql
CREATE TABLE public.osm_roads (
    id            BIGSERIAL PRIMARY KEY,
    osm_id        BIGINT,
    highway       VARCHAR(50),     -- motorway, primary, secondary ...
    highway_label VARCHAR(100),    -- 日本語ラベル
    name          TEXT,
    name_en       TEXT,
    ref           VARCHAR(50),     -- 路線番号
    lanes         VARCHAR(20),
    maxspeed      VARCHAR(20),
    surface       VARCHAR(50),
    oneway        VARCHAR(10),
    geom          GEOMETRY(LineString, 4326)
);
```

QGISでの接続: **レイヤ → レイヤを追加 → PostGISレイヤを追加**

---

### MariaDBへの格納

```bash
python osm_road_downloader.py \
    --level prefecture --target 愛知県 \
    --output mariadb \
    --db-host localhost --db-port 3306 \
    --db-name gisdb --db-user root --db-password secret
```

MariaDB要件:
- MariaDB 10.2以降（SRID対応）
- `GEOMETRY` カラムに空間インデックスを自動作成

MariaDBでの空間クエリ例:
```sql
-- 指定バウンディングボックス内の国道を検索
SELECT name, ref, ST_AsText(geom)
FROM osm_roads
WHERE highway IN ('primary', 'trunk')
  AND ST_Within(geom, ST_GeomFromText(
      'POLYGON((136 35, 137 35, 137 36, 136 36, 136 35))', 4326));
```

---

## QGISでの表示

### GeoJSONを読み込む

1. **レイヤ → レイヤを追加 → ベクタレイヤを追加**
2. `*.geojson` ファイルを選択
3. CRS: `EPSG:4326`（WGS84）

### スタイル設定（道路種別で色分け）

1. レイヤを右クリック → **プロパティ → シンボロジ**
2. **分類** を選択、列に `highway` を指定
3. **分類** ボタンをクリックして色分けを適用

### PostGISレイヤを追加する

1. **レイヤ → レイヤを追加 → PostGISレイヤを追加**
2. 接続情報を入力して接続
3. `osm_roads` テーブルを選択して追加

---

## Leafletビューアの使い方

`leaflet_road_viewer.html` をブラウザで開く。

| 機能 | 操作 |
|---|---|
| GeoJSONを開く | サイドバーのファイル選択 → 読み込む |
| ドラッグ＆ドロップ | ブラウザ画面にGeoJSONファイルをドロップ |
| URLから読み込む | URLを入力 → 取得して読み込む |
| 道路種別の表示切替 | 凡例のアイテムをクリック |
| 属性の確認 | 地図上の道路をクリック |

---

## データソース

- **OpenStreetMap** (https://www.openstreetmap.org/)
  - ライセンス: ODbL (Open Database License)
  - クレジット表記: © OpenStreetMap contributors
- **Overpass API** (https://overpass-api.de/)
  - 利用に際してはAPIの利用規約に従ってください
  - 大量取得の場合はOverpass APIサーバーに負荷をかけないようご注意ください

---

## 注意事項

- Overpass APIは無料の公共サービスです。大量リクエストは避け、`--delay` で待機時間を設けてください。
- 全国一括ダウンロード（`--level nationwide`）には長時間かかります。
- `--road-type all` は容量が非常に大きくなります。`major` または `general` の使用を推奨します。
- データは WGS84 (EPSG:4326) 座標系で保存されます。
