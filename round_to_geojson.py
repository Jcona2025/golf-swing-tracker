"""Export a round + course to a single GeoJSON for visualisation.

Overlays:
- Green polygons (from course)
- Tee markers (from course)
- Full GPS trail of the round (LineString)
- Shot markers colour-coded by classification (pitch/chip/putt)

Usage:
    python round_to_geojson.py <round.fit> <course.json> [--output FILE]
"""
import fitparse
import pandas as pd
import json
import math
import argparse
from classify_round import (
    load_round, extract_shots, classify_shots,
)


SHOT_COLORS = {
    "pitch": "#e63946",   # red
    "chip":  "#f4a261",   # orange
    "putt":  "#2a9d8f",   # green
}


def build_geojson(round_df, shots_df, course):
    features = []

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
                "fill": "#7fc97f",
                "fill-opacity": 0.35,
                "stroke": "#2a9d8f",
                "stroke-width": 2,
            },
        })

    # 2. Tee markers
    for h in course["holes"]:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [h["tee"]["lon"], h["tee"]["lat"]],
            },
            "properties": {
                "kind": "tee",
                "hole": h["hole"],
                "distance_m": h["distance_official_m"],
                "marker-color": "#264653",
                "marker-symbol": str(h["hole"]),
                "marker-size": "small",
                "title": f"H{h['hole']} tee ({h['distance_official_m']}m)",
            },
        })

    # 3. Full GPS trail
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

    # 4. Shot markers — numbered per hole (1, 2, 3... restarts each hole)
    shots_sorted = shots_df.sort_values("marker_t").reset_index(drop=True)
    shot_in_hole = {}
    for _, s in shots_sorted.iterrows():
        if pd.isna(s["lat"]) or pd.isna(s["lon"]):
            continue
        hole = int(s["hole"])
        shot_in_hole[hole] = shot_in_hole.get(hole, 0) + 1
        shot_num = shot_in_hole[hole]

        cls = s["class"]
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [s["lon"], s["lat"]],
            },
            "properties": {
                "kind": "shot",
                "hole": hole,
                "shot_num_in_hole": shot_num,
                "shot_class": cls,
                "marker_global": int(s["marker"]),
                "peak_mag": round(float(s["peak_mag"]), 0),
                "marker-color": SHOT_COLORS.get(cls, "#888888"),
                "marker-symbol": str(shot_num),
                "marker-size": "medium",
                "title": f"H{hole} shot {shot_num} — {cls} ({round(float(s['peak_mag']))}mg)",
            },
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
    args = parser.parse_args()

    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_overlay.geojson"

    print(f"Loading {args.fit_file}...")
    df = load_round(args.fit_file)

    print(f"Loading {args.course_json}...")
    course = json.load(open(args.course_json))
    holes_data = course["holes"]

    sdf = extract_shots(df)
    print(f"Shots detected: {len(sdf)}")
    sdf = classify_shots(sdf, holes_data)

    # Stats
    n_pitch = (sdf["class"] == "pitch").sum()
    n_chip = (sdf["class"] == "chip").sum()
    n_putt = (sdf["class"] == "putt").sum()
    print(f"  {n_pitch} pitch, {n_chip} chip, {n_putt} putt")

    geojson = build_geojson(df, sdf, course)

    with open(output, "w") as f:
        json.dump(geojson, f, indent=2)

    print(f"\nSaved: {output}")
    print(f"Upload to https://geojson.io/ to visualise")
    print(f"  — Green polygons = course greens")
    print(f"  — Dark line = your GPS walking trail")
    print(f"  — Red dots = pitches, Orange = chips, Green = putts")


if __name__ == "__main__":
    main()
