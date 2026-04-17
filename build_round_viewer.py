"""Build a self-contained HTML viewer for a round overlay GeoJSON.

The output is a single .html file that embeds the GeoJSON data and
renders a clean mobile-friendly map using Leaflet. Open it in any
browser or host it on GitHub Pages / a gist.
"""
import json
import sys
import argparse


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; width: 100%; height: 100vh; overflow: hidden;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
  #header {
    background: #1d3557; color: white; padding: 10px 14px;
    width: 100%; height: 54px; z-index: 1000;
    box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  }
  #header h1 { margin: 0; font-size: 16px; font-weight: 600; }
  #header .stats { font-size: 12px; opacity: 0.85; margin-top: 2px; }
  #map { width: 100%; height: calc(100vh - 54px); }
  #legend {
    position: absolute; bottom: 20px; left: 10px; z-index: 1000;
    background: rgba(255,255,255,0.95); padding: 8px 10px; border-radius: 6px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 12px;
  }
  #legend .item { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
  #legend .dot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid #222; }
  .shot-popup { font-size: 13px; }
  .shot-popup b { display: block; margin-bottom: 2px; }
  .leaflet-div-icon-tee {
    background: #264653; color: white; border-radius: 50%;
    width: 22px !important; height: 22px !important;
    line-height: 22px; text-align: center;
    font-size: 11px; font-weight: 600;
    border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.4);
  }
  .leaflet-div-icon-shot {
    border-radius: 50%; width: 20px !important; height: 20px !important;
    line-height: 18px; text-align: center;
    font-size: 10px; font-weight: 700; color: white;
    border: 2px solid white; box-shadow: 0 1px 3px rgba(0,0,0,0.4);
  }
</style>
</head>
<body>
<div id="header">
  <h1>__TITLE__</h1>
  <div class="stats">__STATS__</div>
</div>
<div id="map"></div>
<div id="legend">
  <div class="item"><span class="dot" style="background:#e63946"></span>Pitch</div>
  <div class="item"><span class="dot" style="background:#f4a261"></span>Chip</div>
  <div class="item"><span class="dot" style="background:#2a9d8f"></span>Putt</div>
  <div class="item" style="font-size:10px;color:#666;margin-top:4px">Shot 1 = tee shot</div>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const GEOJSON = __GEOJSON__;
const SHOT_COLORS = { pitch: '#e63946', chip: '#f4a261', putt: '#2a9d8f' };

const map = L.map('map', { zoomControl: true, attributionControl: true });

// Esri World Imagery (free, high-res satellite)
L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
  maxZoom: 22,
  attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community'
}).addTo(map);

const bounds = [];
const layers = L.featureGroup();

GEOJSON.features.forEach(f => {
  const g = f.geometry;
  const p = f.properties || {};

  if (g.type === 'Polygon' && p.kind === 'green') {
    const coords = g.coordinates[0].map(c => [c[1], c[0]]);
    bounds.push(...coords);
    const areaStr = p.area_m2 ? `${p.area_m2.toFixed(1)}m&sup2;` : '';
    const idxStr = p.index ? ` (idx ${p.index})` : '';
    L.polygon(coords, {
      color: '#2a9d8f', weight: 2, fillColor: '#7fc97f', fillOpacity: 0.35
    }).addTo(layers).bindPopup(
      `<div class="shot-popup"><b>Hole ${p.hole} green</b>` +
      `Hole: ${p.distance_m}m${idxStr}<br>` +
      `Green area: ${areaStr}</div>`
    );
  } else if (g.type === 'LineString' && p.kind === 'gps_trail') {
    const coords = g.coordinates.map(c => [c[1], c[0]]);
    L.polyline(coords, { color: '#1d3557', weight: 2, opacity: 0.55 }).addTo(layers);
  } else if (g.type === 'Point' && p.kind === 'shot') {
    const color = SHOT_COLORS[p.shot_class] || '#888';
    const icon = L.divIcon({
      className: 'leaflet-div-icon-shot',
      html: `<div style="background:${color};width:100%;height:100%;border-radius:50%;display:flex;align-items:center;justify-content:center">${p.shot_num_in_hole}</div>`
    });

    // Build popup content based on shot type + available data
    let popup = `<div class="shot-popup"><b>H${p.hole} shot ${p.shot_num_in_hole} — ${p.shot_class}</b>`;
    if (p.shot_num_in_hole === 1 && p.hole_distance_m !== undefined) {
      popup += `Hole: ${p.hole_distance_m}m (index ${p.hole_index})<br>`;
      popup += `Green area: ${p.green_area_m2.toFixed(1)}m&sup2;<br>`;
    } else {
      if (p.dist_from_prev_m !== undefined) {
        popup += `Travel: ${p.dist_from_prev_m}m from previous shot<br>`;
      }
      if (p.dist_to_green_m !== undefined) {
        popup += `To green: ${p.dist_to_green_m}m<br>`;
      }
    }
    popup += `<hr style="margin:4px 0;border:0;border-top:1px solid #ddd">`;
    popup += `<span style="font-size:11px;color:#666">`;
    popup += `peak_mag: ${p.peak_mag}mg`;
    if (p.peak_duration !== undefined) popup += ` &middot; dur: ${p.peak_duration}ms`;
    if (p.rise_rate !== undefined) popup += `<br>rise_rate: ${p.rise_rate}mg/ms`;
    if (p.peak_count !== undefined) popup += ` &middot; peaks: ${p.peak_count}`;
    if (p.pre_stillness !== undefined) popup += `<br>pre_stillness: ${p.pre_stillness}mg`;
    popup += `</span></div>`;

    L.marker([g.coordinates[1], g.coordinates[0]], { icon }).addTo(layers)
      .bindPopup(popup);
  }
});

layers.addTo(map);
if (bounds.length > 0) { map.fitBounds(bounds, { padding: [40, 40] }); }
else { map.setView([53.76, -6.25], 17); }
</script>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("overlay_geojson", help="Round overlay GeoJSON file")
    parser.add_argument("--title", default=None, help="Page title")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    geojson = json.load(open(args.overlay_geojson))

    # Stats
    n_pitch = sum(1 for f in geojson["features"] if f["properties"].get("shot_class") == "pitch")
    n_chip  = sum(1 for f in geojson["features"] if f["properties"].get("shot_class") == "chip")
    n_putt  = sum(1 for f in geojson["features"] if f["properties"].get("shot_class") == "putt")
    total = n_pitch + n_chip + n_putt

    title = args.title or geojson.get("name", "Round overlay")
    stats = f"Score: {total} &middot; {n_pitch} pitches, {n_chip} chips, {n_putt} putts"

    html = (HTML_TEMPLATE
            .replace("__TITLE__", title)
            .replace("__STATS__", stats)
            .replace("__GEOJSON__", json.dumps(geojson)))

    output = args.output or args.overlay_geojson.rsplit(".", 1)[0] + ".html"
    with open(output, "w") as f:
        f.write(html)

    print(f"Saved: {output}")
    print(f"  {total} shots ({n_pitch} pitch, {n_chip} chip, {n_putt} putt)")
    print(f"\nTo host as a public URL, upload to a gist and share via htmlpreview.github.io,")
    print(f"or push to a public GitHub Pages repo.")


if __name__ == "__main__":
    main()
