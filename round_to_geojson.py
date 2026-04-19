"""Export a round + course to a single GeoJSON for visualisation.

Overlays:
- Green polygons (from course, with hole stats in popup)
- Full GPS trail of the round (LineString)
- Shot markers colour-coded by classification (pitch/chip/putt)
  - Shot 1 of each hole snaps to the tee position for visual cleanliness
  - Popups show hole distance, shot distance, distance to green, peak_mag, features

Usage:
    python round_to_geojson.py <round.fit> <course.json> [--output FILE]
"""
import pandas as pd
import json
import argparse
from classify_round import (
    load_round, extract_shots, classify_shots, haversine_m,
)


SHOT_COLORS = {
    "pitch": "#e63946",   # red
    "chip":  "#f4a261",   # orange
    "putt":  "#2a9d8f",   # green
}


def build_geojson(round_df, shots_df, course):
    features = []
    course_by_hole = {h["hole"]: h for h in course["holes"]}

    # 1. Course greens (shaded polygons)
    for h in course["holes"]:
        coords_lonlat = [[p[1], p[0]] for p in h["green_polygon"]]
        if coords_lonlat[0] != coords_lonlat[-1]:
            coords_lonlat.append(coords_lonlat[0])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords_lonlat]},
            "properties": {
                "kind": "green",
                "hole": h["hole"],
                "distance_m": h["distance_official_m"],
                "index": h["index"],
                "area_m2": h["area_official_m2"],
                "fill": "#7fc97f",
                "fill-opacity": 0.35,
                "stroke": "#2a9d8f",
                "stroke-width": 2,
            },
        })

    # 2. Full GPS trail
    trail = round_df.dropna(subset=["lat", "lon"])
    trail_coords = [[row["lon"], row["lat"]] for _, row in trail.iterrows()]
    features.append({
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": trail_coords},
        "properties": {
            "kind": "gps_trail",
            "stroke": "#1d3557",
            "stroke-width": 2,
            "stroke-opacity": 0.6,
        },
    })

    # 3. Shot markers — numbered per hole; shot 1 snaps to tee
    shots_sorted = shots_df.sort_values("marker_t").reset_index(drop=True)
    shot_in_hole = {}
    prev_shot_by_hole = {}
    for _, s in shots_sorted.iterrows():
        if pd.isna(s["lat"]) or pd.isna(s["lon"]):
            continue
        hole = int(s["hole"])
        shot_in_hole[hole] = shot_in_hole.get(hole, 0) + 1
        shot_num = shot_in_hole[hole]
        cls = s["class"]
        hole_data = course_by_hole.get(hole)

        # Shot 1 (the pitch) snaps to the tee for visual cleanliness
        if shot_num == 1 and hole_data:
            lat = hole_data["tee"]["lat"]
            lon = hole_data["tee"]["lon"]
        else:
            lat = float(s["lat"])
            lon = float(s["lon"])

        props = {
            "kind": "shot",
            "hole": hole,
            "shot_num_in_hole": shot_num,
            "shot_class": cls,
            "marker_global": int(s["marker"]),
            "peak_mag": round(float(s["peak_mag"]), 0),
            "marker-color": SHOT_COLORS.get(cls, "#888888"),
            "marker-symbol": str(shot_num),
            "marker-size": "medium",
        }

        # New high-res features if present
        for f in ["peak_duration", "rise_rate", "peak_count", "pre_stillness"]:
            v = s.get(f)
            if pd.notna(v):
                props[f] = round(float(v), 1)

        if shot_num == 1 and hole_data:
            # Shot 1 = pitch from the tee. Show hole info.
            props["hole_distance_m"] = hole_data["distance_official_m"]
            props["hole_index"] = hole_data["index"]
            props["green_area_m2"] = hole_data["area_official_m2"]
            props["title"] = (f"H{hole} tee &middot; {cls} &middot; "
                              f"{hole_data['distance_official_m']}m")
        else:
            # Later shots: distance from previous shot + distance to green centroid
            prev = prev_shot_by_hole.get(hole)
            if prev is not None:
                dist_from_prev = haversine_m(prev[0], prev[1], float(s["lat"]), float(s["lon"]))
                props["dist_from_prev_m"] = round(dist_from_prev, 1)
            if hole_data:
                c = hole_data["green_centroid"]
                dist_to_green = haversine_m(float(s["lat"]), float(s["lon"]), c["lat"], c["lon"])
                props["dist_to_green_m"] = round(dist_to_green, 1)
            props["title"] = f"H{hole} shot {shot_num} &middot; {cls}"

        prev_shot_by_hole[hole] = (float(s["lat"]), float(s["lon"]))

        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })

    return {
        "type": "FeatureCollection",
        "name": f"{course['name']} round overlay",
        "features": features,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("fit_file")
    parser.add_argument("course_json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--exclude-markers", default=None,
                        help="Comma-separated shot markers to exclude (e.g. temp holes, accidental presses)")
    args = parser.parse_args()

    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_overlay.geojson"

    excluded = set()
    if args.exclude_markers:
        excluded = {int(m.strip()) for m in args.exclude_markers.split(",") if m.strip()}
        print(f"Excluding markers: {sorted(excluded)}")

    print(f"Loading {args.fit_file}...")
    df = load_round(args.fit_file)

    print(f"Loading {args.course_json}...")
    course = json.load(open(args.course_json))
    holes_data = course["holes"]

    sdf = extract_shots(df)
    if excluded:
        sdf = sdf[~sdf["marker"].isin(excluded)].reset_index(drop=True)
    print(f"Shots detected: {len(sdf)}")
    sdf = classify_shots(sdf, holes_data)

    n_pitch = (sdf["class"] == "pitch").sum()
    n_chip = (sdf["class"] == "chip").sum()
    n_putt = (sdf["class"] == "putt").sum()
    print(f"  {n_pitch} pitch, {n_chip} chip, {n_putt} putt")

    geojson = build_geojson(df, sdf, course)

    with open(output, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"\nSaved: {output}")


if __name__ == "__main__":
    main()
