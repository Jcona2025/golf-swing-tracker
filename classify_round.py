"""Classify a round of Pitch & Putt from a FIT file + course data.

Usage:
    python classify_round.py <round.fit> <course.json>

Outputs:
    - Per-shot classification (pitch/chip/putt) with GPS + accel data
    - Per-hole scorecard with shot-type breakdown
    - Comparison against ground truth if provided
"""
import fitparse
import pandas as pd
import numpy as np
import json
import math
import sys
import argparse


# === CONSTANTS ===
PITCH_THRESHOLD = 4000      # peak_mag above this = pitch
PEAK_WINDOW_BEFORE = 6      # seconds to look back from marker for actual impact
PEAK_WINDOW_AFTER = 1       # seconds to look forward
GPS_BUFFER = 4              # metres beyond polygon radius for putt fallback


# === HELPER FUNCTIONS ===

def semicircles_to_degrees(v):
    return v * (180.0 / 2**31) if v is not None and not (isinstance(v, float) and math.isnan(v)) else None


def haversine_m(lat1, lon1, lat2, lon2):
    R = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def point_in_polygon(lat, lon, polygon):
    """Ray-casting algorithm. polygon = list of [lat, lon] pairs."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        yi, xi = polygon[i]   # yi=lat (Y-axis), xi=lon (X-axis)
        yj, xj = polygon[j]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def find_nearest_tee(lat, lon, holes):
    """Return (hole_number, distance_m) of the nearest tee to a point."""
    best_h, best_d = -1, 99999
    for h in holes:
        d = haversine_m(lat, lon, h["tee"]["lat"], h["tee"]["lon"])
        if d < best_d:
            best_d = d
            best_h = h["hole"]
    return best_h, best_d


def find_green(lat, lon, holes):
    """Check if a point is on any green. Returns hole number or None.

    Uses point-in-polygon first (precise), then falls back to a dynamic
    radius around the green centroid to handle GPS drift. The fallback
    radius is sqrt(polygon_area / pi) + GPS_BUFFER.
    """
    # Precise check
    for h in holes:
        if point_in_polygon(lat, lon, h["green_polygon"]):
            return h["hole"]
    # Fallback: dynamic radius from centroid
    for h in holes:
        c = h["green_centroid"]
        poly_radius = math.sqrt(h["gps_polygon_area_m2"] / math.pi)
        max_radius = poly_radius + GPS_BUFFER
        d = haversine_m(lat, lon, c["lat"], c["lon"])
        if d <= max_radius:
            return h["hole"]
    return None


# === MAIN PIPELINE ===

def load_round(fit_path):
    """Load a FIT file and return a DataFrame with GPS + accel + markers."""
    fit = fitparse.FitFile(fit_path)
    rows = [{f.name: f.value for f in r.fields} for r in fit.get_messages("record")]
    df = pd.DataFrame(rows).dropna(subset=["peak_mag"]).reset_index(drop=True)
    df["t"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    df["lat"] = df["position_lat"].apply(
        lambda v: v * (180 / 2**31) if pd.notna(v) else None
    )
    df["lon"] = df["position_long"].apply(
        lambda v: v * (180 / 2**31) if pd.notna(v) else None
    )
    return df


def extract_shots(df):
    """Extract unique shot markers with window-corrected peak features."""
    markers = (
        df[df["shot_marker"] > 0]
        .groupby("shot_marker")
        .first()
        .reset_index()
        .sort_values("t")
        .reset_index(drop=True)
    )

    shots = []
    for _, m in markers.iterrows():
        w = df[
            (df["t"] >= m["t"] - PEAK_WINDOW_BEFORE)
            & (df["t"] <= m["t"] + PEAK_WINDOW_AFTER)
        ]
        if len(w) == 0:
            continue
        peak = w.loc[w["peak_mag"].idxmax()]
        shots.append({
            "marker": int(m["shot_marker"]),
            "marker_t": m["t"],
            "peak_t": peak["t"],
            "peak_mag": peak["peak_mag"],
            "std_mag": peak["std_mag"],
            "max_jerk": peak["max_jerk"],
            "lat": m["lat"] if pd.notna(m["lat"]) else peak["lat"],
            "lon": m["lon"] if pd.notna(m["lon"]) else peak["lon"],
        })

    return pd.DataFrame(shots)


def classify_shots(sdf, holes_data):
    """Classify each shot as pitch/chip/putt and assign to a hole."""
    classes = []
    hole_assignments = []
    current_hole = -1

    for i, row in sdf.iterrows():
        on_green = find_green(row["lat"], row["lon"], holes_data)
        is_pitch = row["peak_mag"] > PITCH_THRESHOLD

        if is_pitch:
            shot_class = "pitch"
            nearest_h, _ = find_nearest_tee(row["lat"], row["lon"], holes_data)
            current_hole = nearest_h
        elif on_green is not None:
            shot_class = "putt"
        else:
            shot_class = "chip"

        classes.append(shot_class)
        hole_assignments.append(current_hole)

    sdf["class"] = classes
    sdf["hole"] = hole_assignments
    return sdf


def print_scorecard(sdf, course_name="Course", ground_truth=None):
    """Print a per-hole scorecard with shot-type breakdown."""

    def abbrev(s):
        return {"pitch": "Pi", "chip": "Ch", "putt": "Pu"}.get(s, s)

    print(f"\n{'=' * 60}")
    print(f"  SCORECARD — {course_name}")
    print(f"{'=' * 60}")

    if ground_truth:
        print(f"{'Hole':>5} {'Score':>6} {'Exp':>4} | {'Breakdown':>25} {'Expected':>25}")
        print("-" * 72)
    else:
        print(f"{'Hole':>5} {'Score':>6} | {'Breakdown':>25}")
        print("-" * 40)

    total = 0
    total_exp = 0
    correct_holes = 0
    shots_correct = 0
    shots_total = 0

    for h in range(1, 19):
        hs = sdf[sdf["hole"] == h]
        n = len(hs)
        total += n
        got_str = ",".join([abbrev(s) for s in hs["class"].values])

        if ground_truth and h in ground_truth:
            exp = ground_truth[h]
            exp_n = len(exp)
            total_exp += exp_n
            exp_str = ",".join([abbrev(s) for s in exp])
            ok = "✓" if n == exp_n else "✗"

            if n == exp_n:
                correct_holes += 1
                for e, g in zip(exp, hs["class"].values):
                    shots_total += 1
                    if e == g:
                        shots_correct += 1
            else:
                shots_total += exp_n

            print(f"  H{h:>2} {n:>5}  {exp_n:>3} | {got_str:>25} {exp_str:>25}  {ok}")
        else:
            print(f"  H{h:>2} {n:>5}  | {got_str:>25}")

    pi = (sdf["class"] == "pitch").sum()
    ch = (sdf["class"] == "chip").sum()
    pu = (sdf["class"] == "putt").sum()

    print("-" * 72 if ground_truth else "-" * 40)
    print(f"  Total: {total} shots ({pi} pitch, {ch} chip, {pu} putt)")

    if ground_truth:
        print(f"  Expected: {total_exp} shots")
        print(f"\n  Holes with correct count: {correct_holes}/18")
        print(f"  Per-shot accuracy: {shots_correct}/{shots_total} = {100 * shots_correct / shots_total:.1f}%")
        print(f"  Pitch detection: {pi}/18 = {100 * pi / 18:.0f}%")


def main():
    parser = argparse.ArgumentParser(description="Classify a Pitch & Putt round")
    parser.add_argument("fit_file", help="Path to the round FIT file")
    parser.add_argument("course_json", help="Path to the course JSON file")
    parser.add_argument("--output", default=None, help="Save classified shots to CSV")
    args = parser.parse_args()

    # Load course
    course = json.load(open(args.course_json))
    holes_data = course["holes"]
    print(f"Course: {course['name']} ({course['n_holes']} holes)")

    # Load round
    df = load_round(args.fit_file)
    duration_min = df["t"].iloc[-1] / 60
    print(f"Round: {len(df)} records, {duration_min:.1f} min")

    # Extract and classify shots
    sdf = extract_shots(df)
    print(f"Shots detected: {len(sdf)}")

    sdf = classify_shots(sdf, holes_data)

    # Print scorecard
    print_scorecard(sdf, course_name=course["name"])

    # Save CSV
    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_classified.csv"
    sdf.to_csv(output, index=False)
    print(f"\nSaved classified shots to: {output}")


if __name__ == "__main__":
    main()
