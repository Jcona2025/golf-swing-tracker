"""Build killineer.json from the user's satellite-traced Killineer map."""
import json, math, re

# Official data from the clubhouse: hole -> (distance_m, index, par)
OFFICIAL = {
    1:  (45, 18, 3), 2:  (50, 5, 3),  3:  (55, 13, 3), 4:  (60, 3, 3),
    5:  (36, 17, 3), 6:  (43, 6, 3),  7:  (57, 7, 3),  8:  (42, 9, 3),
    9:  (48, 11, 3), 10: (49, 8, 3),  11: (45, 12, 3), 12: (49, 10, 3),
    13: (60, 4, 3),  14: (44, 14, 3), 15: (66, 1, 3),  16: (29, 15, 3),
    17: (40, 16, 3), 18: (68, 2, 3),
}


def polygon_area_m2(coords_latlon):
    lats = [c[0] for c in coords_latlon]
    lons = [c[1] for c in coords_latlon]
    lat0 = sum(lats) / len(lats)
    x = [(lo - lons[0]) * 111000 * math.cos(math.radians(lat0)) for lo in lons]
    y = [(la - lats[0]) * 111000 for la in lats]
    n = len(x)
    a = sum(x[i]*y[(i+1)%n] - x[(i+1)%n]*y[i] for i in range(n))
    return abs(a) / 2


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(a))


def extract_hole_num(props):
    for k in props:
        m = re.search(r"(\d+)", k)
        if m: return int(m.group(1))
    return None


gj = json.load(open("Killineer-mapped-full.geojson"))
tees = {}
greens = {}

for f in gj["features"]:
    props = f.get("properties", {})
    hole = extract_hole_num(props)
    if hole is None: continue
    if f["geometry"]["type"] == "Point":
        lon, lat = f["geometry"]["coordinates"]
        tees[hole] = (lat, lon)
    elif f["geometry"]["type"] == "Polygon":
        coords = f["geometry"]["coordinates"][0]
        greens[hole] = [[c[1], c[0]] for c in coords]  # [lat, lon]

course = {
    "name": "Killineer",
    "mapping_method": "satellite_trace",
    "source": "geojson.io satellite tracing + clubhouse distance/index data",
    "n_holes": 18,
    "total_distance_official_m": 886,
    "holes": [],
}

print(f'{"H":>3} {"Dist":>6} {"Idx":>4} {"OurDist":>8} {"Area":>8}')
print('-' * 36)
for h in range(1, 19):
    dist, idx, par = OFFICIAL[h]
    tee_lat, tee_lon = tees[h]
    poly = greens[h]
    lats = [p[0] for p in poly]; lons = [p[1] for p in poly]
    clat, clon = sum(lats)/len(lats), sum(lons)/len(lons)
    area = polygon_area_m2(poly)
    gps_dist = haversine_m(tee_lat, tee_lon, clat, clon)
    course["holes"].append({
        "hole": h,
        "index": idx,
        "distance_official_m": dist,
        "tee": {"lat": round(tee_lat, 7), "lon": round(tee_lon, 7)},
        "green_centroid": {"lat": round(clat, 7), "lon": round(clon, 7)},
        "green_polygon": [[round(p[0], 7), round(p[1], 7)] for p in poly],
        "gps_distance_tee_to_centroid_m": round(gps_dist, 1),
        "gps_polygon_area_m2": round(area, 1),
    })
    print(f"  H{h:>2} {dist:>5}m {idx:>3} {gps_dist:>6.1f}m {area:>6.1f}m²")

with open("killineer.json", "w") as f:
    json.dump(course, f, indent=2)
print(f"\nSaved killineer.json with {len(course['holes'])} holes")
