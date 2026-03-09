/* ===================================================
   固定資産税評価 WebGIS – Application Script
   国土地理院タイルマップ + 評価マイクロサービス連携
   =================================================== */

'use strict';

// -------------------------------------------------------
// 設定
// -------------------------------------------------------
const CONFIG = {
  // 空文字（相対パス）にすることで、どのPCからアクセスしても
  // WebGIS を配信している同じサーバーの /api/ へリクエストが飛ぶ。
  // nginx が /api/ → FastAPI へリバースプロキシする。
  API_BASE: '',
  MAP_CENTER: [36.0, 138.0],  // 日本中心付近
  MAP_ZOOM: 6,
  GSI_ATTRIBUTION: '© <a href="https://maps.gsi.go.jp/development/ichiran.html" target="_blank">国土地理院</a>',
};

// -------------------------------------------------------
// 国土地理院タイルレイヤー定義
// -------------------------------------------------------
const GSI_LAYERS = {
  '標準地図': L.tileLayer(
    'https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png',
    {
      attribution: CONFIG.GSI_ATTRIBUTION,
      minZoom: 2,
      maxNativeZoom: 18,  // タイル配信上限
      maxZoom: 22,        // 拡大表示上限（タイルを拡大レンダリング）
    }
  ),
  '淡色地図': L.tileLayer(
    'https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png',
    {
      attribution: CONFIG.GSI_ATTRIBUTION,
      minZoom: 2,
      maxNativeZoom: 18,
      maxZoom: 22,
    }
  ),
  '写真（シームレス）': L.tileLayer(
    'https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg',
    {
      attribution: CONFIG.GSI_ATTRIBUTION,
      minZoom: 2,
      maxNativeZoom: 18,
      maxZoom: 22,
    }
  ),
  '色別標高図': L.tileLayer(
    'https://cyberjapandata.gsi.go.jp/xyz/relief/{z}/{x}/{y}.png',
    {
      attribution: CONFIG.GSI_ATTRIBUTION,
      minZoom: 2,
      maxNativeZoom: 15,  // タイル配信上限
      maxZoom: 22,
      opacity: 0.7,
    }
  ),
};

const GSI_OVERLAYS = {
  '土地利用細分メッシュ': L.tileLayer(
    'https://cyberjapandata.gsi.go.jp/xyz/lum200k/{z}/{x}/{y}.png',
    {
      attribution: CONFIG.GSI_ATTRIBUTION,
      minZoom: 10,
      maxNativeZoom: 14,  // タイル配信上限
      maxZoom: 22,
      opacity: 0.6,
    }
  ),
};

// -------------------------------------------------------
// マップ初期化
// -------------------------------------------------------
const map = L.map('map', {
  center: CONFIG.MAP_CENTER,
  zoom: CONFIG.MAP_ZOOM,
  zoomControl: true,
  maxZoom: 22,
});

// デフォルトレイヤー (標準地図)
GSI_LAYERS['標準地図'].addTo(map);

// レイヤーコントロール
L.control.layers(GSI_LAYERS, GSI_OVERLAYS, {
  position: 'topright',
  collapsed: true,
}).addTo(map);

// スケールバー
L.control.scale({ imperial: false, position: 'bottomright' }).addTo(map);

// -------------------------------------------------------
// 描画ツール (Leaflet.draw)
// -------------------------------------------------------
const drawnItems = new L.FeatureGroup();
map.addLayer(drawnItems);

const drawControl = new L.Control.Draw({
  edit: { featureGroup: drawnItems },
  draw: {
    polygon: {
      allowIntersection: false,
      showArea: true,
      shapeOptions: { color: '#1a6e38', fillOpacity: 0.25, weight: 2 },
    },
    rectangle: {
      shapeOptions: { color: '#1a6e38', fillOpacity: 0.25, weight: 2 },
    },
    polyline: false,
    circle: false,
    circlemarker: false,
    marker: false,
  },
});

let drawingActive = false;

document.getElementById('btn-draw').addEventListener('click', () => {
  if (drawingActive) return;
  drawingActive = true;
  document.getElementById('btn-draw').classList.add('active');
  // 既存の描画を削除してからポリゴン描画開始
  drawnItems.clearLayers();
  map.addControl(drawControl);
  new L.Draw.Polygon(map, drawControl.options.draw.polygon).enable();
});

document.getElementById('btn-clear').addEventListener('click', () => {
  drawnItems.clearLayers();
  resetDrawState();
  document.getElementById('land-area').value = '';
  document.getElementById('area-from-map').style.display = 'none';
});

function resetDrawState() {
  drawingActive = false;
  document.getElementById('btn-draw').classList.remove('active');
  if (map.hasLayer && document.querySelector('.leaflet-draw')) {
    try { map.removeControl(drawControl); } catch (_) {}
  }
}

map.on(L.Draw.Event.CREATED, (e) => {
  drawnItems.clearLayers();
  drawnItems.addLayer(e.layer);
  resetDrawState();

  // Turf.js で面積計算
  const geojson = e.layer.toGeoJSON();
  const area = turf.area(geojson);  // m²

  const areaRounded = Math.round(area * 100) / 100;
  document.getElementById('land-area').value = areaRounded;
  document.getElementById('area-from-map').style.display = 'inline';

  // ポップアップ表示
  const center = e.layer.getBounds().getCenter();
  L.popup()
    .setLatLng(center)
    .setContent(`<div class="popup-area">${areaRounded.toLocaleString()} ㎡</div><div>地図から計算した地積</div>`)
    .openOn(map);

  // 入力タブにフォーカス
  switchTab('input');
});

// -------------------------------------------------------
// 現在地ボタン
// -------------------------------------------------------
document.getElementById('btn-locate').addEventListener('click', () => {
  map.locate({ setView: true, maxZoom: 16 });
});

map.on('locationfound', (e) => {
  L.marker(e.latlng).addTo(map)
    .bindPopup('現在地').openPopup();
});

map.on('locationerror', () => {
  alert('現在地を取得できませんでした。');
});

// -------------------------------------------------------
// タブ切り替え
// -------------------------------------------------------
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  document.querySelectorAll('.tab-content').forEach(div => {
    div.classList.toggle('active', div.id === `tab-${name}`);
  });
}

document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// -------------------------------------------------------
// フォームの動的表示制御
// -------------------------------------------------------
const isCorner    = document.getElementById('is-corner');
const isIrregular = document.getElementById('is-irregular');
const cityPlan    = document.getElementById('city-plan-area');

isCorner.addEventListener('change', () => {
  document.getElementById('side-road-row').style.display =
    isCorner.checked ? 'block' : 'none';
});

isIrregular.addEventListener('change', () => {
  document.getElementById('irregular-rate-row').style.display =
    isIrregular.checked ? 'block' : 'none';
});

cityPlan.addEventListener('change', () => {
  document.getElementById('city-plan-rate-row').style.display =
    cityPlan.checked ? 'block' : 'none';
});

// -------------------------------------------------------
// API ヘルスチェック
// -------------------------------------------------------
async function checkApiHealth() {
  const dot   = document.getElementById('status-dot');
  const label = document.getElementById('status-label');
  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/health`, { signal: AbortSignal.timeout(3000) });
    if (res.ok) {
      dot.className = 'dot dot-ok';
      label.textContent = 'API 接続済み';
    } else {
      throw new Error('API error');
    }
  } catch (_) {
    dot.className = 'dot dot-error';
    label.textContent = 'API オフライン';
  }
}

checkApiHealth();
setInterval(checkApiHealth, 30000);

// -------------------------------------------------------
// 評価フォーム送信
// -------------------------------------------------------
document.getElementById('eval-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  await submitEvaluation();
});

async function submitEvaluation() {
  const btn = document.getElementById('evaluate-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>計算中...';

  // フォーム値収集
  const payload = {
    land_category:   document.getElementById('land-category').value,
    land_area:       parseFloat(document.getElementById('land-area').value) || 0,
    address:         document.getElementById('address').value || null,
    zone_type:       document.getElementById('zone-type').value,
    road_price:      parseFloat(document.getElementById('road-price').value) || 0,
    frontage:        parseFloat(document.getElementById('frontage').value) || null,
    depth:           parseFloat(document.getElementById('depth').value) || null,
    is_corner:       document.getElementById('is-corner').checked,
    side_road_price: parseFloat(document.getElementById('side-road-price').value) || null,
    is_irregular:    document.getElementById('is-irregular').checked,
    irregular_rate:  parseFloat(document.getElementById('irregular-rate').value) || null,
    is_no_road:      document.getElementById('is-no-road').checked,
    city_plan_area:  document.getElementById('city-plan-area').checked,
    tax_rate:        parseFloat(document.getElementById('tax-rate').value) / 100,
    city_plan_rate:  parseFloat(document.getElementById('city-plan-rate').value) / 100,
  };

  // GeoJSON (描画済みの場合)
  if (drawnItems.getLayers().length > 0) {
    payload.geojson = drawnItems.toGeoJSON();
  }

  try {
    const res = await fetch(`${CONFIG.API_BASE}/api/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `APIエラー: ${res.status}`);
    }

    const data = await res.json();
    renderResult(data, payload);
    switchTab('result');

  } catch (err) {
    alert(`評価に失敗しました:\n${err.message}`);
  } finally {
    btn.disabled = false;
    btn.innerHTML = '💹 評価額を計算する';
  }
}

// -------------------------------------------------------
// 結果表示
// -------------------------------------------------------
function fmt(yen) {
  return Math.round(yen).toLocaleString('ja-JP') + ' 円';
}

function renderResult(data, payload) {
  const el = document.getElementById('result-content');
  const taxTotal = data.fixed_asset_tax + (data.city_plan_tax || 0);

  el.innerHTML = `
    <div class="result-card">
      <h3>固定資産税評価額</h3>
      <div class="result-amount">${fmt(data.assessed_value)}</div>
      <div class="result-sub">地積: ${(payload.land_area || 0).toLocaleString()} ㎡ ／ 路線価: ${(payload.road_price || 0).toLocaleString()} 円/㎡</div>
    </div>

    <div class="result-card">
      <h3>課税標準額</h3>
      <div class="result-amount" style="font-size:20px">${fmt(data.taxable_base)}</div>
      <div class="result-sub">${data.reduction_label}</div>
    </div>

    <div class="result-card accent">
      <h3>年間税額合計</h3>
      <div class="result-amount" style="color:var(--accent)">${fmt(taxTotal)}</div>
      <table class="result-table" style="margin-top:10px">
        <thead>
          <tr><th>税目</th><th>税率</th><th>税額</th></tr>
        </thead>
        <tbody>
          <tr>
            <td>固定資産税</td>
            <td>${(data.tax_rate * 100).toFixed(1)}%</td>
            <td>${fmt(data.fixed_asset_tax)}</td>
          </tr>
          ${data.city_plan_tax != null ? `<tr>
            <td>都市計画税</td>
            <td>${(data.city_plan_rate * 100).toFixed(1)}%</td>
            <td>${fmt(data.city_plan_tax)}</td>
          </tr>` : ''}
          <tr>
            <td colspan="2"><strong>合計</strong></td>
            <td>${fmt(taxTotal)}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <details style="margin-bottom:12px">
      <summary style="cursor:pointer;font-size:12px;color:var(--text-muted);padding:6px 0">▶ 計算内訳</summary>
      <table class="result-table" style="margin-top:6px">
        <thead><tr><th>補正項目</th><th>補正率</th></tr></thead>
        <tbody>
          ${data.correction_factors.map(f =>
            `<tr><td>${f.name}</td><td>${f.rate.toFixed(4)}</td></tr>`
          ).join('')}
          <tr><td><strong>複合補正率</strong></td><td><strong>${data.total_correction.toFixed(4)}</strong></td></tr>
        </tbody>
      </table>
    </details>

    <div class="result-disclaimer">
      ※ 本計算は概算であり、実際の課税額は市区町村の評価によって異なります。
      正確な評価額は所在の市区町村窓口にご確認ください。
    </div>
  `;

  document.getElementById('result-placeholder').style.display = 'none';
  el.style.display = 'block';

  // 地図上のポリゴンにポップアップ
  if (drawnItems.getLayers().length > 0) {
    const center = drawnItems.getBounds().getCenter();
    L.popup({ maxWidth: 260 })
      .setLatLng(center)
      .setContent(`
        <strong>評価額</strong>: ${fmt(data.assessed_value)}<br/>
        <strong>固定資産税</strong>: ${fmt(data.fixed_asset_tax)}/年
      `)
      .openOn(map);
  }
}

// -------------------------------------------------------
// API URL を help タブに表示（アクセス元のホストを動的に表示）
// -------------------------------------------------------
document.getElementById('api-url-display').textContent =
  window.location.origin + (CONFIG.API_BASE || '');
