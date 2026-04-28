"""Build macbride.json from Macbride_full_mapped.geojson.

No official scorecard data yet — distances are computed from tee→green
centroid haversine, par defaults to 3, and stroke index defaults to hole
number. Update this script with official values when available.
"""
import json
import math


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def polygon_area_m2(coords_latlon):
    lats = [c[0] for c in coords_latlon]
    lons = [c[1] for c in coords_latlon]
    lat0 = sum(lats) / len(lats)
    x = [(lo - lons[0]) * 111000 * math.cos(math.radians(lat0)) for lo in lons]
    y = [(la - lats[0]) * 111000 for la in lats]
    n = len(x)
    a = sum(x[i]*y[(i+1) % n] - x[(i+1) % n]*y[i] for i in range(n))
    return abs(a) / 2


gj = json.load(open('Macbride_full_mapped.geojson'))

tees = {}
greens = {}

for f in gj['features']:
    p = f.get('properties', {})
    h = p.get('hole')
    k = p.get('kind')
    if h is None or k is None:
        continue
    g = f['geometry']
    if k == 'tee' and g['type'] == 'Point':
        lon, lat = g['coordinates']
        tees[int(h)] = (lat, lon)
    elif k == 'green' and g['type'] == 'Polygon':
        coords = [[c[1], c[0]] for c in g['coordinates'][0]]
        # Drop closing point if duplicate
        if coords[0] == coords[-1]:
            coords = coords[:-1]
        greens[int(h)] = coords

holes = []
for h in sorted(set(tees) & set(greens)):
    poly = greens[h]
    centroid_lat = sum(c[0] for c in poly) / len(poly)
    centroid_lon = sum(c[1] for c in poly) / len(poly)
    tee_lat, tee_lon = tees[h]
    gps_dist = haversine_m(tee_lat, tee_lon, centroid_lat, centroid_lon)
    area = polygon_area_m2(poly)

    closed_poly = poly + [poly[0]]

    holes.append({
        "hole": h,
        "index": h,                     # placeholder until scorecard available
        "distance_official_m": round(gps_dist),  # placeholder: GPS-derived
        "par": 3,
        "tee": {"lat": tee_lat, "lon": tee_lon},
        "green_centroid": {"lat": centroid_lat, "lon": centroid_lon},
        "green_polygon": closed_poly,
        "gps_distance_tee_to_centroid_m": round(gps_dist, 1),
        "gps_polygon_area_m2": round(area, 1),
    })

course = {
    "name": "Macbride",
    "mapping_method": "satellite_trace_with_round_overlay",
    "source": "build_course_mapper.py traced over Macbride_full.fit GPS trail",
    "scorecard_available": False,
    "n_holes": len(holes),
    "total_distance_official_m": sum(h["distance_official_m"] for h in holes),
    "holes": holes,
}

with open('macbride.json', 'w') as f:
    json.dump(course, f, indent=2)

print(f"Built macbride.json with {len(holes)} holes")
print(f"  Total GPS-derived distance: {course['total_distance_official_m']}m")
print(f"  Per-hole tee→green: " +
      ", ".join(f"H{h['hole']}={h['distance_official_m']}m" for h in holes))
