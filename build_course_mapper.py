"""Build a self-contained HTML page for tracing a course from a round's GPS trail.

The output overlays the round's GPS trail on Esri satellite imagery and
provides Leaflet draw tools for polygons (greens) and markers (tees). Each
feature is tagged with a hole number on creation. An "Export GeoJSON"
button downloads the traced features as a single GeoJSON file.

Usage:
    python build_course_mapper.py <round.fit> [--output FILE]
"""
import json
import argparse
from classify_round import load_round


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; width: 100%; height: 100vh; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  #header {
    background: #1d3557; color: white; padding: 8px 14px;
    width: 100%; height: 56px; z-index: 1000;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    display: flex; align-items: center; justify-content: space-between;
  }
  #header h1 { margin: 0; font-size: 14px; font-weight: 600; }
  #header .sub { font-size: 11px; opacity: 0.85; margin-top: 2px; }
  #header button {
    background: #2a9d8f; color: white; border: 0; padding: 8px 14px;
    border-radius: 4px; font-weight: 600; cursor: pointer; font-size: 13px;
  }
  #header button:hover { background: #21867a; }
  #map { width: 100%; height: calc(100vh - 56px); }
  #status {
    position: absolute; bottom: 14px; left: 14px; z-index: 1000;
    background: rgba(255,255,255,0.95); padding: 8px 12px; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 12px;
  }
  #status .row { margin: 2px 0; }
  .leaflet-tee-icon {
    background: #264653; color: white; border-radius: 50%;
    width: 24px !important; height: 24px !important;
    line-height: 22px; text-align: center;
    font-size: 12px; font-weight: 700;
    border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.5);
  }
  .leaflet-green-label {
    background: rgba(42,157,143,0.9); color: white; border-radius: 4px;
    padding: 2px 6px; font-size: 11px; font-weight: 700;
    border: 1px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.4);
    white-space: nowrap;
  }
  /* Shrink edit-mode vertex handles so they don't obscure the green polygon */
  .leaflet-editing-icon {
    width: 8px !important; height: 8px !important;
    margin-left: -4px !important; margin-top: -4px !important;
    border-radius: 50%;
    border: 1.5px solid #1d3557 !important;
    background: white !important;
    opacity: 0.85;
  }
</style>
</head>
<body>
<div id="header">
  <div>
    <h1>__TITLE__</h1>
    <div class="sub">Polygon = green &middot; Marker = tee &middot; You'll be asked for a hole number on each draw</div>
  </div>
  <div>
    <input type="file" id="import-file" accept=".geojson,.json" style="display:none" onchange="importGeoJSON(event)">
    <button onclick="document.getElementById('import-file').click()" style="background:#457b9d;margin-right:6px">Import GeoJSON</button>
    <button onclick="exportGeoJSON()">Export GeoJSON</button>
  </div>
</div>
<div id="map"></div>
<div id="status">
  <div class="row"><b>Drawn:</b> <span id="count-greens">0</span> greens, <span id="count-tees">0</span> tees</div>
  <div class="row" style="font-size:11px;color:#555">Click any drawn shape to edit hole number or delete.</div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
<script>
const TRAIL = __TRAIL__;
const ROUND_NAME = "__TITLE__";

const map = L.map('map', { zoomControl: true });
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
  maxZoom: 22,
  attribution: 'Tiles &copy; Esri'
}).addTo(map);

// GPS trail
if (TRAIL.length > 0) {
  const trail = L.polyline(TRAIL, { color: '#1d3557', weight: 2.5, opacity: 0.7 }).addTo(map);
  L.circleMarker(TRAIL[0], { radius: 5, color: '#fff', fillColor: '#06d6a0', fillOpacity: 1, weight: 2 })
    .addTo(map).bindTooltip('Round start', { permanent: false });
  L.circleMarker(TRAIL[TRAIL.length - 1], { radius: 5, color: '#fff', fillColor: '#ef476f', fillOpacity: 1, weight: 2 })
    .addTo(map).bindTooltip('Round end', { permanent: false });
  map.fitBounds(trail.getBounds(), { padding: [30, 30] });
} else {
  map.setView([53.76, -6.25], 17);
}

// Draw layer
const drawn = new L.FeatureGroup();
map.addLayer(drawn);

const drawControl = new L.Control.Draw({
  draw: {
    polygon: { allowIntersection: false, showArea: true,
      shapeOptions: { color: '#2a9d8f', fillColor: '#7fc97f', fillOpacity: 0.4, weight: 2 } },
    rectangle: { showArea: true,
      shapeOptions: { color: '#2a9d8f', fillColor: '#7fc97f', fillOpacity: 0.4, weight: 2 } },
    marker: true,
    polyline: false, circle: false, circlemarker: false,
  },
  edit: { featureGroup: drawn, edit: true, remove: true }
});
map.addControl(drawControl);

function teeIcon(hole) {
  return L.divIcon({
    className: 'leaflet-tee-icon',
    html: `<div>${hole}</div>`,
    iconSize: [24, 24], iconAnchor: [12, 12],
  });
}

function refreshStatus() {
  let g = 0, t = 0;
  drawn.eachLayer(l => {
    if (l.feature && l.feature.properties.kind === 'green') g++;
    else if (l.feature && l.feature.properties.kind === 'tee') t++;
  });
  document.getElementById('count-greens').textContent = g;
  document.getElementById('count-tees').textContent = t;
}

function attachLayer(layer, kind, hole) {
  layer.feature = layer.feature || { type: 'Feature', properties: {} };
  layer.feature.properties.kind = kind;
  layer.feature.properties.hole = hole;
  if (kind === 'tee') {
    layer.setIcon(teeIcon(hole));
  } else if (kind === 'green') {
    layer.bindTooltip(`H${hole} green`, { permanent: true, direction: 'center', className: 'leaflet-green-label' });
  }
  layer.on('click', () => {
    const newHole = prompt(`Hole number for this ${kind} (or "delete" to remove):`, layer.feature.properties.hole);
    if (newHole === null) return;
    if (newHole.toLowerCase() === 'delete') {
      drawn.removeLayer(layer);
      refreshStatus();
      return;
    }
    const n = parseInt(newHole, 10);
    if (Number.isNaN(n) || n < 1 || n > 18) { alert('Enter 1-18'); return; }
    attachLayer(layer, kind, n);
  });
  drawn.addLayer(layer);
}

map.on(L.Draw.Event.CREATED, (e) => {
  const kind = (e.layerType === 'polygon' || e.layerType === 'rectangle') ? 'green' : 'tee';
  const promptMsg = kind === 'green' ? 'Hole number for this green:' : 'Hole number for this tee:';
  const ans = prompt(promptMsg, '');
  const n = parseInt(ans, 10);
  if (Number.isNaN(n) || n < 1 || n > 18) {
    alert('Skipped — hole number must be 1-18.');
    return;
  }
  let layer = e.layer;
  // Rectangles only allow corner-drag edits. Convert to a real polygon so
  // editing exposes midpoint handles (you can add/move arbitrary vertices).
  if (e.layerType === 'rectangle') {
    const latlngs = layer.getLatLngs()[0];
    layer = L.polygon(latlngs, {
      color: '#2a9d8f', fillColor: '#7fc97f', fillOpacity: 0.4, weight: 2
    });
  }
  attachLayer(layer, kind, n);
  refreshStatus();
});

map.on('draw:deleted', refreshStatus);
map.on('draw:edited', refreshStatus);

// Hide green labels during edit mode so they don't obscure vertex handles
map.on('draw:editstart', () => {
  drawn.eachLayer(l => { if (l.getTooltip && l.getTooltip()) l.closeTooltip(); });
});
map.on('draw:editstop', () => {
  drawn.eachLayer(l => { if (l.getTooltip && l.getTooltip()) l.openTooltip(); });
});

function importGeoJSON(event) {
  const file = event.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    let gj;
    try { gj = JSON.parse(e.target.result); }
    catch { alert('Could not parse GeoJSON.'); return; }
    let imported = 0;
    (gj.features || []).forEach(f => {
      const p = f.properties || {};
      const hole = parseInt(p.hole, 10);
      if (Number.isNaN(hole)) return;
      const t = f.geometry.type;
      if (t === 'Polygon') {
        const latlngs = f.geometry.coordinates[0].map(c => [c[1], c[0]]);
        const layer = L.polygon(latlngs, {
          color: '#2a9d8f', fillColor: '#7fc97f', fillOpacity: 0.4, weight: 2
        });
        attachLayer(layer, 'green', hole);
        imported++;
      } else if (t === 'Point') {
        const layer = L.marker([f.geometry.coordinates[1], f.geometry.coordinates[0]]);
        attachLayer(layer, 'tee', hole);
        imported++;
      }
    });
    refreshStatus();
    event.target.value = '';
    alert(`Imported ${imported} feature(s).`);
  };
  reader.readAsText(file);
}

function exportGeoJSON() {
  const features = [];
  drawn.eachLayer(layer => {
    const gj = layer.toGeoJSON();
    gj.properties = layer.feature.properties;
    features.push(gj);
  });
  if (features.length === 0) { alert('Nothing drawn yet.'); return; }
  const out = { type: 'FeatureCollection', name: ROUND_NAME + ' course mapping', features };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = ROUND_NAME.replace(/[^a-zA-Z0-9_-]/g, '_') + '_mapped.geojson';
  a.click();
  URL.revokeObjectURL(url);
}
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fit_file")
    parser.add_argument("--title", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    print(f"Loading {args.fit_file}...")
    df = load_round(args.fit_file)
    trail = df.dropna(subset=["lat", "lon"])[["lat", "lon"]].values.tolist()
    print(f"  {len(trail)} GPS points")

    base = args.fit_file.rsplit(".", 1)[0]
    title = args.title or base.replace("_", " ")
    output = args.output or base + "_mapper.html"

    html = (HTML_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__TRAIL__", json.dumps(trail)))

    with open(output, "w") as f:
        f.write(html)

    print(f"\nSaved: {output}")
    print("Open in a browser, trace greens (polygons) + tees (markers), then click 'Export GeoJSON'.")


if __name__ == "__main__":
    main()
