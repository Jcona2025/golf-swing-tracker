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
    load_round, extract_shots, classify_shots, haversine_m, apply_corrections,
)


SHOT_COLORS = {
    "pitch": "#e63946",   # red
    "chip":  "#f4a261",   # orange
    "putt":  "#2a9d8f",   # green
}


def compute_hole_stats(shots_df, course):
    """Compute per-hole and round-level stats."""
    course_by_hole = {h["hole"]: h for h in course["holes"]}
    hole_stats = {}

    for hole, hole_shots in shots_df.groupby("hole"):
        if hole < 0: continue
        hs = hole_shots.sort_values("marker_t").reset_index(drop=True)
        n_shots = len(hs)
        h_data = course_by_hole.get(int(hole))
        if not h_data: continue

        # Pitch result — distance from green centroid to where ball ended up (shot 2 position)
        pitch_to_green_m = None
        pitch_on_green = None
        if n_shots >= 2:
            shot2 = hs.iloc[1]
            c = h_data["green_centroid"]
            pitch_to_green_m = haversine_m(
                float(shot2["lat"]), float(shot2["lon"]), c["lat"], c["lon"]
            )
            # On green if shot 2 was classified as a putt (GPS inside/near green)
            pitch_on_green = (shot2["class"] == "putt")
        elif n_shots == 1:
            # Hole in one! Pitch hit the hole directly
            pitch_on_green = True
            pitch_to_green_m = 0.0

        # Putts
        putts = hs[hs["class"] == "putt"]
        chips = hs[hs["class"] == "chip"]
        n_putts = len(putts)
        n_chips = len(chips)

        # Up-and-down: missed the green with the pitch, then chipped + 1-putted (2 shots total after pitch)
        # In P&P this is: shot 1 = pitch (not on green), shot 2 = chip, shot 3 = putt (holed)
        up_and_down = (pitch_on_green is False and n_chips >= 1 and n_putts == 1)

        hole_stats[int(hole)] = {
            "n_shots": n_shots,
            "n_putts": n_putts,
            "n_chips": n_chips,
            "pitch_on_green": pitch_on_green,
            "pitch_to_green_m": round(pitch_to_green_m, 1) if pitch_to_green_m is not None else None,
            "up_and_down": up_and_down,
            "official_distance_m": h_data["distance_official_m"],
            "index": h_data["index"],
        }

    return hole_stats


def build_geojson(round_df, shots_df, course):
    features = []
    course_by_hole = {h["hole"]: h for h in course["holes"]}
    hole_stats = compute_hole_stats(shots_df, course)

    # 1. Course greens (shaded polygons) with per-hole round stats
    for h in course["holes"]:
        coords_lonlat = [[p[1], p[0]] for p in h["green_polygon"]]
        if coords_lonlat[0] != coords_lonlat[-1]:
            coords_lonlat.append(coords_lonlat[0])
        stats = hole_stats.get(h["hole"], {})
        props = {
            "kind": "green",
            "hole": h["hole"],
            "distance_m": h["distance_official_m"],
            "index": h["index"],
            "area_m2": h["area_official_m2"],
            "fill": "#7fc97f",
            "fill-opacity": 0.35,
            "stroke": "#2a9d8f",
            "stroke-width": 2,
        }
        if stats:
            props["score"] = int(stats["n_shots"])
            props["n_putts"] = int(stats["n_putts"])
            props["n_chips"] = int(stats["n_chips"])
            if stats["pitch_on_green"] is not None:
                props["pitch_on_green"] = bool(stats["pitch_on_green"])
            if stats["pitch_to_green_m"] is not None:
                props["pitch_to_green_m"] = stats["pitch_to_green_m"]
            props["up_and_down"] = bool(stats["up_and_down"])
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [coords_lonlat]},
            "properties": props,
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

        # Figure out if this is the last shot of the hole (the hole-out)
        hole_total_shots = (shots_sorted["hole"] == hole).sum()
        is_last_shot = (shot_num == hole_total_shots)

        if shot_num == 1 and hole_data:
            # Shot 1 = pitch from the tee. Show hole info + pitch result.
            props["hole_distance_m"] = hole_data["distance_official_m"]
            props["hole_index"] = hole_data["index"]
            props["green_area_m2"] = hole_data["area_official_m2"]
            stats = hole_stats.get(hole, {})
            if stats.get("pitch_on_green") is not None:
                props["pitch_on_green"] = bool(stats["pitch_on_green"])
            if stats.get("pitch_to_green_m") is not None:
                props["pitch_result_m"] = stats["pitch_to_green_m"]
            props["title"] = f"H{hole} tee &middot; {cls}"
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
            # Made vs missed for putts
            if cls == "putt":
                props["putt_made"] = bool(is_last_shot)
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
                        help="Comma-separated shot markers to exclude")
    parser.add_argument("--corrections", default=None,
                        help="JSON file of manual corrections (exclude, reclassify, insert_shots, reassign_hole)")
    args = parser.parse_args()

    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_overlay.geojson"

    # Merge --exclude-markers flag into corrections for unified handling
    corrections = None
    if args.corrections:
        corrections = json.load(open(args.corrections))
        print(f"Corrections: {args.corrections}")
    if args.exclude_markers:
        excluded = [int(m.strip()) for m in args.exclude_markers.split(",") if m.strip()]
        if corrections is None:
            corrections = {}
        corrections["exclude_markers"] = corrections.get("exclude_markers", []) + excluded
        print(f"Excluding markers (CLI): {excluded}")

    print(f"Loading {args.fit_file}...")
    df = load_round(args.fit_file)

    print(f"Loading {args.course_json}...")
    course = json.load(open(args.course_json))
    holes_data = course["holes"]

    sdf = extract_shots(df)
    # Exclude markers BEFORE classification so hole grouping isn't confused
    if corrections and corrections.get("exclude_markers"):
        sdf = sdf[~sdf["marker"].isin(corrections["exclude_markers"])].reset_index(drop=True)
    print(f"Shots detected: {len(sdf)}")
    sdf = classify_shots(sdf, holes_data)

    # Apply reclassify / reassign_hole / insert_shots corrections
    if corrections:
        # Don't double-apply exclude_markers since we already did it above
        post_corrections = {k: v for k, v in corrections.items() if k != "exclude_markers"}
        if post_corrections:
            before = len(sdf)
            sdf = apply_corrections(sdf, post_corrections)
            print(f"Post-classification corrections: {before} → {len(sdf)} shots")

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
