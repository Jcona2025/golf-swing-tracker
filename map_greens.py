"""Extract green polygons from a mapping FIT file.

Usage:
    python map_greens.py <fit_file> [--course-name NAME]

Input: FIT file with shot_marker presses (odd = tee, even = perimeter start).
Output: GeoJSON with tee points and green polygons keyed by hole number.
"""
import fitparse
import pandas as pd
import numpy as np
import json
import sys
import argparse
import math


def semicircles_to_degrees(v):
    return v * (180.0 / 2**31) if v is not None else None


def load_fit_gps(path):
    fit = fitparse.FitFile(path)
    rows = [{f.name: f.value for f in r.fields} for r in fit.get_messages("record")]
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["position_lat", "position_long"]).reset_index(drop=True)
    df["lat"] = df["position_lat"].apply(semicircles_to_degrees)
    df["lon"] = df["position_long"].apply(semicircles_to_degrees)
    return df


def extract_markers(df):
    if "shot_marker" not in df.columns:
        return pd.DataFrame()
    markers = df[df["shot_marker"] > 0].copy()
    unique = markers.groupby("shot_marker").first().reset_index()
    return unique.sort_values("timestamp").reset_index(drop=True)


def segment_by_markers(df, markers):
    """Split the GPS trail into per-hole segments.

    Presses alternate: odd (1, 3, 5, ...) = tee, even (2, 4, 6, ...) = perimeter start.
    Each hole = {tee_point: (lat,lon), perimeter_points: [(lat,lon), ...]}.
    The perimeter for hole N runs from its perimeter-start press until the next tee press
    (which is the start of hole N+1), or to end-of-recording for the last hole.
    """
    holes = []
    n_presses = len(markers)
    n_holes = n_presses // 2  # need tee + perimeter for each hole

    for i in range(n_holes):
        tee_marker = markers.iloc[i * 2]
        perim_marker = markers.iloc[i * 2 + 1]

        # GPS points of the perimeter walk: from perimeter-start press to the next tee press
        perim_start_t = perim_marker["timestamp"]
        if i * 2 + 2 < n_presses:
            perim_end_t = markers.iloc[i * 2 + 2]["timestamp"]
        else:
            perim_end_t = df["timestamp"].iloc[-1] + pd.Timedelta(seconds=1)

        perim_mask = (df["timestamp"] >= perim_start_t) & (df["timestamp"] < perim_end_t)
        perim_df = df[perim_mask]
        raw_points = list(zip(perim_df["lat"].values, perim_df["lon"].values))
        trimmed_points = trim_to_loop(raw_points)

        holes.append({
            "hole": i + 1,
            "tee_lat": semicircles_to_degrees(tee_marker["position_lat"]),
            "tee_lon": semicircles_to_degrees(tee_marker["position_long"]),
            "perimeter_points": trimmed_points,
            "raw_n_points": len(raw_points),
        })

    return holes, (n_presses % 2 != 0)


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def trim_to_loop(points, return_threshold_m=8.0, min_loop_dist_m=10.0):
    """Trim a perimeter walk down to just the loop(s) — drop the walk to the next tee.

    A perimeter loop returns near its starting point. The walk to the next tee does not.
    We find the LAST time the track is within return_threshold_m of the starting point
    (after having gone at least min_loop_dist_m away), and cut there.
    """
    if len(points) < 5:
        return points

    start_lat, start_lon = points[0]
    distances = [haversine_m(start_lat, start_lon, p[0], p[1]) for p in points]

    went_far = False
    last_return_idx = 0
    for i, d in enumerate(distances):
        if d > min_loop_dist_m:
            went_far = True
        if went_far and d <= return_threshold_m:
            last_return_idx = i

    if last_return_idx > 0 and last_return_idx < len(points) - 1:
        return points[:last_return_idx + 1]
    return points


def polygon_centroid(points):
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    return (sum(lats) / len(lats), sum(lons) / len(lons))


def polygon_extent(points):
    if not points:
        return 0, 0
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    ns = (max(lats) - min(lats)) * 111000
    ew = (max(lons) - min(lons)) * 111000 * math.cos(math.radians(sum(lats) / len(lats)))
    return ns, ew


def concave_hull(points, alpha=0.0005):
    """Build a simple polygon from GPS points. Uses convex hull as fallback
    (concave hull needs shapely/alphashape; keeping deps minimal here).
    """
    from scipy.spatial import ConvexHull
    if len(points) < 3:
        return points
    pts = np.array(points)
    try:
        hull = ConvexHull(pts)
        return [tuple(pts[i]) for i in hull.vertices] + [tuple(pts[hull.vertices[0]])]
    except Exception:
        return points


def build_geojson(holes, course_name="Unknown"):
    features = []
    for h in holes:
        # Tee point feature
        if h["tee_lat"] is not None and h["tee_lon"] is not None:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [h["tee_lon"], h["tee_lat"]]},
                "properties": {"hole": h["hole"], "kind": "tee"},
            })

        perim = h["perimeter_points"]
        if len(perim) >= 3:
            hull = concave_hull(perim)
            coords = [[lon, lat] for lat, lon in hull]
            # Close the polygon
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            centroid = polygon_centroid(hull)
            ns, ew = polygon_extent(hull)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [coords]},
                "properties": {
                    "hole": h["hole"],
                    "kind": "green",
                    "n_points": len(perim),
                    "centroid_lat": centroid[0],
                    "centroid_lon": centroid[1],
                    "extent_ns_m": round(ns, 1),
                    "extent_ew_m": round(ew, 1),
                },
            })

    return {
        "type": "FeatureCollection",
        "name": course_name,
        "features": features,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fit_file")
    parser.add_argument("--course-name", default="Course")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_greens.geojson"

    print(f"Loading {args.fit_file}...")
    df = load_fit_gps(args.fit_file)
    print(f"  {len(df)} GPS-tagged records")

    markers = extract_markers(df)
    print(f"  {len(markers)} shot markers")
    if len(markers) == 0:
        print("ERROR: no shot markers found in file.")
        sys.exit(1)

    holes, leftover = segment_by_markers(df, markers)
    if leftover:
        print(f"WARNING: odd number of markers ({len(markers)}) — last press has no paired perimeter.")

    print(f"\nExtracted {len(holes)} holes:")
    for h in holes:
        n = len(h["perimeter_points"])
        if n >= 3:
            ns, ew = polygon_extent(h["perimeter_points"])
            raw_n = h.get("raw_n_points", n)
            trimmed_note = f" (trimmed from {raw_n})" if raw_n != n else ""
            print(f"  Hole {h['hole']}: tee=({h['tee_lat']:.6f}, {h['tee_lon']:.6f})  "
                  f"perimeter={n} pts{trimmed_note}  extent={ns:.1f}×{ew:.1f}m")
        else:
            print(f"  Hole {h['hole']}: tee=({h['tee_lat']:.6f}, {h['tee_lon']:.6f})  "
                  f"perimeter={n} pts (TOO FEW — need ≥3)")

    geojson = build_geojson(holes, course_name=args.course_name)
    with open(output, "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"\nSaved GeoJSON to: {output}")
    print(f"\nTo visualise: upload the file to https://geojson.io/")


if __name__ == "__main__":
    main()
