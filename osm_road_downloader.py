#!/usr/bin/env python3
"""
OSM道路中心線データダウンローダー

OpenStreetMapから道路データをダウンロードするツール。
都道府県・市区町村・バウンディングボックス単位でのダウンロードに対応。
GeoJSON出力、PostGIS/MariaDB格納をサポート。

使用例:
  # 都道府県単位でGeoJSONをダウンロード
  python osm_road_downloader.py --level prefecture --target 東京都

  # 市区町村単位（主要道路のみ）
  python osm_road_downloader.py --level municipality --target 千代田区 --road-type major

  # PostGISに格納
  python osm_road_downloader.py --level prefecture --target 大阪府 \\
      --output postgis --db-host localhost --db-name gisdb --db-user postgres

  # MariaDBに格納
  python osm_road_downloader.py --level prefecture --target 愛知県 \\
      --output mariadb --db-host localhost --db-name gisdb --db-user root

  # 全国を都道府県単位に分割してダウンロード
  python osm_road_downloader.py --level nationwide --output-dir ./osm_data --road-type general

  # バウンディングボックス指定（南緯,西経,北緯,東経）
  python osm_road_downloader.py --level bbox --target "35.6,139.6,35.8,139.9"
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# 日本の都道府県リスト（全国モード用）
PREFECTURES = [
    "北海道", "青森県", "岩手県", "宮城県", "秋田県",
    "山形県", "福島県", "茨城県", "栃木県", "群馬県",
    "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県",
    "富山県", "石川県", "福井県", "山梨県", "長野県",
    "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県",
    "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
    "鳥取県", "島根県", "岡山県", "広島県", "山口県",
    "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
    "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県",
    "鹿児島県", "沖縄県",
]

# 道路種別フィルタ（OSM highway タグ）
ROAD_TYPE_FILTERS: Dict[str, str] = {
    "all": (
        "motorway|motorway_link|trunk|trunk_link"
        "|primary|primary_link|secondary|secondary_link"
        "|tertiary|tertiary_link|residential|unclassified"
        "|service|living_street|pedestrian|track|road"
    ),
    "major": (
        "motorway|motorway_link|trunk|trunk_link"
        "|primary|primary_link|secondary|secondary_link"
    ),
    "general": (
        "motorway|motorway_link|trunk|trunk_link"
        "|primary|primary_link|secondary|secondary_link"
        "|tertiary|tertiary_link|residential|unclassified"
    ),
    "motorway": "motorway|motorway_link",
}

# 道路種別の日本語ラベル（GeoJSONプロパティ用）
ROAD_TYPE_LABELS: Dict[str, str] = {
    "motorway": "高速道路",
    "motorway_link": "高速道路ランプ",
    "trunk": "国道（自動車専用）",
    "trunk_link": "国道ランプ",
    "primary": "国道",
    "primary_link": "国道ランプ",
    "secondary": "都道府県道",
    "secondary_link": "都道府県道ランプ",
    "tertiary": "市町村道（主要）",
    "tertiary_link": "市町村道ランプ",
    "residential": "住宅地道路",
    "unclassified": "未分類道路",
    "service": "サービス道路",
    "living_street": "生活道路",
    "pedestrian": "歩行者専用道路",
    "track": "農道・林道",
    "road": "道路（未分類）",
}


# ---------------------------------------------------------------------------
# Overpass API クエリ
# ---------------------------------------------------------------------------

def build_overpass_query(level: str, target: str, road_filter: str) -> str:
    """Overpass APIクエリを構築する。

    Args:
        level: "prefecture" | "municipality" | "bbox"
        target: 地名（prefecture/municipality）またはbbox座標文字列
        road_filter: highway タグの正規表現パターン

    Returns:
        Overpass QL クエリ文字列
    """
    highway_filter = f'["highway"~"^({road_filter})$"]'

    if level == "prefecture":
        # 都道府県 (admin_level=4)
        return f"""[out:json][timeout:300];
area["name"="{target}"]["admin_level"="4"]->.searchArea;
(
  way{highway_filter}(area.searchArea);
);
out body;
>;
out skel qt;
"""

    if level == "municipality":
        # 市区町村 (admin_level=7 または 8)
        return f"""[out:json][timeout:300];
(
  area["name"="{target}"]["admin_level"="7"];
  area["name"="{target}"]["admin_level"="8"];
)->.searchArea;
(
  way{highway_filter}(area.searchArea);
);
out body;
>;
out skel qt;
"""

    if level == "bbox":
        # バウンディングボックス (south,west,north,east)
        parts = [p.strip() for p in target.split(",")]
        if len(parts) != 4:
            raise ValueError("bbox は '南緯,西経,北緯,東経' の形式で指定してください")
        south, west, north, east = parts
        return f"""[out:json][timeout:300];
(
  way{highway_filter}({south},{west},{north},{east});
);
out body;
>;
out skel qt;
"""

    raise ValueError(f"不明なレベル: {level}")


def download_osm_data(query: str, max_retries: int = 3) -> Optional[Dict]:
    """Overpass APIにクエリを送信してデータを取得する。"""
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": "OSMRoadDownloader/1.0",
    }

    for attempt in range(max_retries):
        try:
            logger.info(f"Overpass APIへリクエスト送信 (試行 {attempt + 1}/{max_retries})")
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers=headers,
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()
            element_count = len(data.get("elements", []))
            logger.info(f"取得要素数: {element_count:,}")
            return data

        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code
            if status == 429:
                wait = 60 * (attempt + 1)
                logger.warning(f"レート制限 (429)。{wait}秒待機します...")
                time.sleep(wait)
            elif status == 504:
                logger.error("サーバータイムアウト (504)。クエリが重すぎます。道路種別を絞るか範囲を小さくしてください。")
                return None
            else:
                logger.error(f"HTTPエラー {status}: {exc}")
                return None

        except requests.exceptions.Timeout:
            logger.warning("タイムアウト。リトライします...")

        except requests.exceptions.RequestException as exc:
            logger.error(f"リクエストエラー: {exc}")

        if attempt < max_retries - 1:
            wait = 2 ** attempt * 5
            logger.info(f"{wait}秒後にリトライします...")
            time.sleep(wait)

    return None


# ---------------------------------------------------------------------------
# OSM JSON → GeoJSON 変換
# ---------------------------------------------------------------------------

def osm_to_geojson(osm_data: Dict) -> Dict:
    """Overpass JSON レスポンスを GeoJSON FeatureCollection に変換する。"""
    elements = osm_data.get("elements", [])

    # ノード座標マップ (id -> (lon, lat))
    nodes: Dict[int, tuple] = {}
    for elem in elements:
        if elem["type"] == "node":
            nodes[elem["id"]] = (elem["lon"], elem["lat"])

    features: List[Dict] = []
    skipped = 0

    for elem in elements:
        if elem["type"] != "way":
            continue

        coords = [nodes[nid] for nid in elem.get("nodes", []) if nid in nodes]
        if len(coords) < 2:
            skipped += 1
            continue

        tags = elem.get("tags", {})
        highway = tags.get("highway", "unknown")

        features.append({
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": coords,
            },
            "properties": {
                "osm_id": elem["id"],
                "highway": highway,
                "highway_label": ROAD_TYPE_LABELS.get(highway, highway),
                "name": tags.get("name", ""),
                "name_en": tags.get("name:en", ""),
                "ref": tags.get("ref", ""),
                "lanes": tags.get("lanes", ""),
                "maxspeed": tags.get("maxspeed", ""),
                "surface": tags.get("surface", ""),
                "oneway": tags.get("oneway", ""),
            },
        })

    if skipped:
        logger.debug(f"座標不足のため {skipped} 件をスキップ")
    logger.info(f"GeoJSON変換完了: {len(features):,} 本の道路")

    return {"type": "FeatureCollection", "features": features}


def save_geojson(geojson: Dict, filepath: str) -> None:
    """GeoJSON をファイルに保存する。"""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(geojson, fh, ensure_ascii=False, separators=(",", ":"))
    size_mb = path.stat().st_size / 1024 / 1024
    logger.info(f"GeoJSON保存: {path} ({size_mb:.2f} MB)")


# ---------------------------------------------------------------------------
# PostGIS 格納
# ---------------------------------------------------------------------------

def load_to_postgis(
    geojson: Dict,
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    table: str,
    schema: str = "public",
) -> None:
    """GeoJSON データを PostGIS テーブルに格納する。"""
    try:
        import psycopg2
        from psycopg2.extras import execute_values
    except ImportError:
        logger.error("psycopg2 が見つかりません。'pip install psycopg2-binary' でインストールしてください。")
        sys.exit(1)

    conn_params: Dict[str, Any] = {
        "host": host, "port": port, "dbname": dbname, "user": user,
    }
    if password:
        conn_params["password"] = password

    conn = psycopg2.connect(**conn_params)
    cur = conn.cursor()
    full_table = f"{schema}.{table}"

    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {full_table} (
                id          BIGSERIAL PRIMARY KEY,
                osm_id      BIGINT,
                highway     VARCHAR(50),
                highway_label VARCHAR(100),
                name        TEXT,
                name_en     TEXT,
                ref         VARCHAR(50),
                lanes       VARCHAR(20),
                maxspeed    VARCHAR(20),
                surface     VARCHAR(50),
                oneway      VARCHAR(10),
                geom        GEOMETRY(LineString, 4326)
            );
        """)
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS {table}_geom_idx
            ON {full_table} USING GIST (geom);
        """)

        features = geojson.get("features", [])
        logger.info(f"PostGISへ {len(features):,} 件挿入中...")

        batch_size = 1000
        for i in range(0, len(features), batch_size):
            batch = features[i : i + batch_size]
            values = []
            for feat in batch:
                p = feat["properties"]
                coord_str = ", ".join(
                    f"{lon} {lat}" for lon, lat in feat["geometry"]["coordinates"]
                )
                ewkt = f"SRID=4326;LINESTRING({coord_str})"
                values.append((
                    p.get("osm_id"), p.get("highway", ""), p.get("highway_label", ""),
                    p.get("name", ""), p.get("name_en", ""), p.get("ref", ""),
                    p.get("lanes", ""), p.get("maxspeed", ""),
                    p.get("surface", ""), p.get("oneway", ""), ewkt,
                ))

            execute_values(
                cur,
                f"""INSERT INTO {full_table}
                    (osm_id, highway, highway_label, name, name_en, ref,
                     lanes, maxspeed, surface, oneway, geom)
                    VALUES %s""",
                values,
                template="(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromEWKT(%s))",
            )
            conn.commit()
            logger.info(f"  {min(i + batch_size, len(features)):,}/{len(features):,} 件完了")

        logger.info(f"PostGIS格納完了: {full_table}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# MariaDB 格納
# ---------------------------------------------------------------------------

def load_to_mariadb(
    geojson: Dict,
    host: str,
    port: int,
    dbname: str,
    user: str,
    password: str,
    table: str,
) -> None:
    """GeoJSON データを MariaDB テーブルに格納する。"""
    try:
        import mysql.connector
    except ImportError:
        logger.error("mysql-connector-python が見つかりません。'pip install mysql-connector-python' でインストールしてください。")
        sys.exit(1)

    conn = mysql.connector.connect(
        host=host, port=port, database=dbname,
        user=user, password=password or "",
    )
    cur = conn.cursor()

    try:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS `{table}` (
                id            BIGINT AUTO_INCREMENT PRIMARY KEY,
                osm_id        BIGINT,
                highway       VARCHAR(50),
                highway_label VARCHAR(100),
                name          TEXT,
                name_en       TEXT,
                ref           VARCHAR(50),
                lanes         VARCHAR(20),
                maxspeed      VARCHAR(20),
                surface       VARCHAR(50),
                oneway        VARCHAR(10),
                geom          LINESTRING NOT NULL SRID 4326,
                SPATIAL INDEX (geom)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)

        features = geojson.get("features", [])
        logger.info(f"MariaDBへ {len(features):,} 件挿入中...")

        batch_size = 500
        for i in range(0, len(features), batch_size):
            batch = features[i : i + batch_size]
            for feat in batch:
                p = feat["properties"]
                coord_str = ", ".join(
                    f"{lon} {lat}" for lon, lat in feat["geometry"]["coordinates"]
                )
                wkt = f"LINESTRING({coord_str})"
                cur.execute(
                    f"""INSERT INTO `{table}`
                        (osm_id, highway, highway_label, name, name_en, ref,
                         lanes, maxspeed, surface, oneway, geom)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,ST_GeomFromText(%s,4326))""",
                    (
                        p.get("osm_id"), p.get("highway", ""), p.get("highway_label", ""),
                        p.get("name", ""), p.get("name_en", ""), p.get("ref", ""),
                        p.get("lanes", ""), p.get("maxspeed", ""),
                        p.get("surface", ""), p.get("oneway", ""), wkt,
                    ),
                )
            conn.commit()
            logger.info(f"  {min(i + batch_size, len(features)):,}/{len(features):,} 件完了")

        logger.info(f"MariaDB格納完了: {table}")

    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


# ---------------------------------------------------------------------------
# メイン処理
# ---------------------------------------------------------------------------

def process_target(
    level: str,
    target: str,
    road_type: str,
    output: str,
    output_file: Optional[str] = None,
    output_dir: Optional[str] = None,
    db_params: Optional[Dict] = None,
) -> bool:
    """1ターゲット分のダウンロード・変換・出力を実行する。"""
    road_filter = ROAD_TYPE_FILTERS[road_type]
    logger.info(f"=== {target} の道路データをダウンロード ===")

    query = build_overpass_query(level, target, road_filter)
    logger.debug(f"Overpassクエリ:\n{query}")

    osm_data = download_osm_data(query)
    if not osm_data:
        logger.error(f"{target}: データ取得失敗")
        return False
    if not osm_data.get("elements"):
        logger.warning(f"{target}: 要素なし（地名が正しくない可能性があります）")
        return False

    geojson = osm_to_geojson(osm_data)

    if output in ("geojson", "both"):
        if output_file:
            save_geojson(geojson, output_file)
        else:
            safe_name = target.replace("/", "_").replace("\\", "_")
            out_dir = output_dir or "."
            save_geojson(geojson, os.path.join(out_dir, f"{safe_name}_roads.geojson"))

    if output in ("postgis", "both") and db_params:
        load_to_postgis(
            geojson,
            host=db_params["host"],
            port=db_params["port"],
            dbname=db_params["dbname"],
            user=db_params["user"],
            password=db_params.get("password", ""),
            table=db_params["table"],
            schema=db_params.get("schema", "public"),
        )

    if output == "mariadb" and db_params:
        load_to_mariadb(
            geojson,
            host=db_params["host"],
            port=db_params["port"],
            dbname=db_params["dbname"],
            user=db_params["user"],
            password=db_params.get("password", ""),
            table=db_params["table"],
        )

    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenStreetMapから道路中心線データをダウンロードするツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--level",
        choices=["prefecture", "municipality", "nationwide", "bbox"],
        required=True,
        help="ダウンロード粒度",
    )
    parser.add_argument(
        "--target",
        help="対象地名（prefecture/municipality）またはbbox座標（南,西,北,東）",
    )
    parser.add_argument(
        "--road-type",
        choices=list(ROAD_TYPE_FILTERS.keys()),
        default="general",
        help="道路種別フィルタ: all=全道路, major=主要道路, general=一般道, motorway=高速 (default: general)",
    )
    parser.add_argument(
        "--output",
        choices=["geojson", "postgis", "mariadb", "both"],
        default="geojson",
        help="出力形式 (default: geojson)",
    )
    parser.add_argument("--output-file", help="GeoJSON出力ファイルパス")
    parser.add_argument(
        "--output-dir",
        default="./osm_data",
        help="GeoJSON出力ディレクトリ（nationwide時 / default: ./osm_data）",
    )

    db = parser.add_argument_group("データベース接続オプション")
    db.add_argument("--db-host", default="localhost", help="ホスト (default: localhost)")
    db.add_argument(
        "--db-port", type=int, default=0,
        help="ポート (default: PostGIS=5432, MariaDB=3306)",
    )
    db.add_argument("--db-name", default="gisdb", help="DB名 (default: gisdb)")
    db.add_argument("--db-user", help="ユーザー名")
    db.add_argument("--db-password", default="", help="パスワード")
    db.add_argument("--db-table", default="osm_roads", help="テーブル名 (default: osm_roads)")
    db.add_argument("--db-schema", default="public", help="スキーマ名 (default: public, PostGISのみ)")

    parser.add_argument(
        "--delay", type=float, default=5.0,
        help="全国一括時の都道府県間の待機秒数 (default: 5.0)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="詳細ログ")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.level != "nationwide" and not args.target:
        parser.error("--level が nationwide 以外の場合は --target が必要です")

    # DB パラメータ組み立て
    db_params: Optional[Dict] = None
    if args.output in ("postgis", "mariadb", "both"):
        if not args.db_user:
            parser.error("データベース出力には --db-user が必要です")

        port = args.db_port
        if port == 0:
            port = 3306 if args.output == "mariadb" else 5432

        db_params = {
            "host": args.db_host,
            "port": port,
            "dbname": args.db_name,
            "user": args.db_user,
            "password": args.db_password,
            "table": args.db_table,
            "schema": args.db_schema,
        }

    # 全国モード
    if args.level == "nationwide":
        logger.info(f"全国 {len(PREFECTURES)} 都道府県のデータをダウンロードします")
        logger.info(f"道路種別: {args.road_type}  出力先: {args.output_dir}")
        success, failures = 0, []

        for i, pref in enumerate(PREFECTURES, 1):
            logger.info(f"[{i}/{len(PREFECTURES)}] {pref}")
            ok = process_target(
                level="prefecture",
                target=pref,
                road_type=args.road_type,
                output=args.output,
                output_dir=args.output_dir,
                db_params=db_params,
            )
            if ok:
                success += 1
            else:
                failures.append(pref)

            if i < len(PREFECTURES):
                logger.info(f"{args.delay}秒待機...")
                time.sleep(args.delay)

        logger.info(f"\n=== 完了: {success}/{len(PREFECTURES)} 成功 ===")
        if failures:
            logger.warning(f"失敗した都道府県: {', '.join(failures)}")
        return

    # 単一ターゲットモード
    process_target(
        level=args.level,
        target=args.target,
        road_type=args.road_type,
        output=args.output,
        output_file=args.output_file,
        output_dir=args.output_dir,
        db_params=db_params,
    )


if __name__ == "__main__":
    main()
