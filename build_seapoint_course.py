"""Merge the original course mapping with the single-hole re-walks, and
produce the authoritative seapoint.json combining our GPS data with
official clubhouse data (distance, area, index)."""

import json
import math


# Official clubhouse data: hole -> (distance_m, area_m2, index)
OFFICIAL = {
    1:  (47, 61.58, 7),
    2:  (55, 41.39, 3),
    3:  (47, 77.79, 13),
    4:  (51, 37.25, 11),
    5:  (52, 40.93, 17),
    6:  (55, 49.67, 1),
    7:  (30, 40.00, 15),
    8:  (44, 35.28, 5),
    9:  (59, 31.18, 9),
    10: (55, 54.48, 8),
    11: (56, 29.97, 4),
    12: (56, 78.73, 12),
    13: (49, 35.67, 18),
    14: (54, 50.11, 16),
    15: (43, 50.26, 14),
    16: (59, 45.88, 2),
    17: (60, 58.15, 10),
    18: (63, 42.84, 6),
}

# Holes to override from individual re-walks
REMAPS = {1: "H01_greens.geojson",
          2: "H02_greens.geojson",
          8: "H08_greens.geojson",
          11: "H11_greens.geojson",
          12: "H12_greens.geojson"}

BASE_FILE = "Seapoint_mapping_greens.geojson"


def load_hole_features(path, hole_override=None):
    """Load a GeoJSON file and return {hole: {'tee': [lon,lat], 'green_coords': [[lon,lat], ...], 'meta': {}}}."""
    gj = json.load(open(path))
    out = {}
    for f in gj["features"]:
        h = hole_override if hole_override is not None else f["properties"]["hole"]
        out.setdefault(h, {"tee": None, "green_coords": None, "meta": {}})
        if f["properties"]["kind"] == "tee":
            out[h]["tee"] = f["geometry"]["coordinates"]
        elif f["properties"]["kind"] == "green":
            out[h]["green_coords"] = f["geometry"]["coordinates"][0]
            out[h]["meta"] = {
                k: v for k, v in f["properties"].items()
                if k not in ("hole", "kind")
            }
    return out


def polygon_area_m2(coords_lonlat):
    lats = [c[1] for c in coords_lonlat]
    lons = [c[0] for c in coords_lonlat]
    lat0 = sum(lats) / len(lats)
    x = [(lo - lons[0]) * 111000 * math.cos(math.radians(lat0)) for lo in lons]
    y = [(la - lats[0]) * 111000 for la in lats]
    n = len(x)
    a = 0
    for i in range(n):
        j = (i + 1) % n
        a += x[i] * y[j] - x[j] * y[i]
    return abs(a) / 2


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    holes = load_hole_features(BASE_FILE)
    print(f"Loaded {len(holes)} holes from {BASE_FILE}")

    for hole_num, remap_file in REMAPS.items():
        new_holes = load_hole_features(remap_file, hole_override=hole_num)
        if hole_num in new_holes:
            holes[hole_num] = new_holes[hole_num]
            print(f"  overriding H{hole_num} with {remap_file}")

    # Build the authoritative course dict
    course = {
        "name": "Seapoint",
        "source": "GPS mapping (Apr 2026) + official clubhouse data",
        "n_holes": 18,
        "holes": [],
    }

    for h in sorted(holes.keys()):
        data = holes[h]
        dist_m, area_m2_official, idx = OFFICIAL[h]
        tee_lon, tee_lat = data["tee"]
        polygon = data["green_coords"]
        centroid_lat = data["meta"].get("centroid_lat")
        centroid_lon = data["meta"].get("centroid_lon")
        gps_dist = haversine_m(tee_lat, tee_lon, centroid_lat, centroid_lon) if centroid_lat else None
        gps_area = polygon_area_m2(polygon)

        course["holes"].append({
            "hole": h,
            "index": idx,
            "distance_official_m": dist_m,
            "area_official_m2": area_m2_official,
            "tee": {"lat": tee_lat, "lon": tee_lon},
            "green_centroid": {"lat": centroid_lat, "lon": centroid_lon},
            "green_polygon": [[p[1], p[0]] for p in polygon],  # lat,lon pairs
            "gps_distance_tee_to_centroid_m": round(gps_dist, 1) if gps_dist else None,
            "gps_polygon_area_m2": round(gps_area, 1),
        })

    with open("seapoint.json", "w") as f:
        json.dump(course, f, indent=2)

    # Summary print
    print("\n=== SEAPOINT COURSE ===\n")
    print(f"{'H':>3} {'Idx':>4} {'Dist':>6} {'OffArea':>9} {'OurArea':>9} {'Ratio':>6}")
    print("-" * 42)
    tot_d, tot_a_off, tot_a_our = 0, 0, 0
    for h in course["holes"]:
        r = h["gps_polygon_area_m2"] / h["area_official_m2"]
        print(f" {h['hole']:>2} {h['index']:>4} {h['distance_official_m']:>5}m "
              f"{h['area_official_m2']:>7.1f}m² {h['gps_polygon_area_m2']:>7.1f}m² {r:>5.2f}×")
        tot_d += h["distance_official_m"]
        tot_a_off += h["area_official_m2"]
        tot_a_our += h["gps_polygon_area_m2"]
    print("-" * 42)
    print(f" total       {tot_d}m {tot_a_off:>7.1f}m² {tot_a_our:>7.1f}m² {tot_a_our/tot_a_off:>5.2f}×")

    # Also write a GeoJSON version for visualisation
    features = []
    for h in course["holes"]:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [h["tee"]["lon"], h["tee"]["lat"]]},
            "properties": {"hole": h["hole"], "kind": "tee", "index": h["index"]},
        })
        coords = [[p[1], p[0]] for p in h["green_polygon"]]  # convert back to lon,lat
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords]},
            "properties": {
                "hole": h["hole"],
                "kind": "green",
                "index": h["index"],
                "distance_m": h["distance_official_m"],
                "official_area_m2": h["area_official_m2"],
                "gps_area_m2": h["gps_polygon_area_m2"],
            },
        })

    geojson = {
        "type": "FeatureCollection",
        "name": "Seapoint",
        "features": features,
    }
    with open("Seapoint_final.geojson", "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"\nSaved:")
    print(f"  seapoint.json           — authoritative course data for the app")
    print(f"  Seapoint_final.geojson  — visualisation on geojson.io")


if __name__ == "__main__":
    main()
