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
        shot = {
            "marker": int(m["shot_marker"]),
            "marker_t": m["t"],
            "peak_t": peak["t"],
            "peak_mag": peak["peak_mag"],
            "std_mag": peak["std_mag"],
            "max_jerk": peak["max_jerk"],
            "lat": m["lat"] if pd.notna(m["lat"]) else peak["lat"],
            "lon": m["lon"] if pd.notna(m["lon"]) else peak["lon"],
        }
        # New high-res features (only present in FIT files recorded after
        # the v3 watch app update). Older files will have these as NaN.
        for feat in ["peak_duration", "rise_rate", "peak_count", "pre_stillness"]:
            shot[feat] = peak[feat] if feat in peak.index else None
        shots.append(shot)

    return pd.DataFrame(shots)


def classify_shots(sdf, holes_data):
    """Classify each shot as pitch/chip/putt and assign to a hole.

    Uses three signals:
    1. Accelerometer: peak_mag > PITCH_THRESHOLD = pitch
    2. GPS: inside green polygon/radius = putt
    3. Temporal ordering: within each hole, the sequence is always
       pitch → chip(s) → putt(s). Once a putt is detected, all
       remaining shots in the hole must also be putts. Shots before
       the first putt that aren't pitches are chips.

    This resolves the fringe ambiguity: a shot near the green edge
    that GPS calls "on green" but appears before any confirmed putt
    is reclassified as a chip (still approaching). Conversely, a shot
    GPS calls "off green" that appears after a confirmed putt stays
    as a putt (GPS noise on the green edge).
    """
    # --- Pass 1: assign holes ---
    # A new hole starts when ANY of:
    #   (a) peak_mag > PITCH_THRESHOLD — a normal wedge pitch.
    #   (b) the shot is within TEE_PROXIMITY_M of a different hole's tee
    #       AND the current hole already had a putt. Handles the case
    #       where a soft tee shot is pressed while standing at the tee.
    #   (c) the PREVIOUS shot was a strict-polygon putt, AND this shot
    #       is >30s later, AND this shot is NOT on any green. Handles
    #       soft tee shots pressed after walking to the ball — the hole
    #       is definitively complete after a strict-on-green putt, so
    #       the next off-green shot has to be a new hole's tee shot.
    #       The time-gap guard prevents a tap-in's GPS-drifted follow-up
    #       from wrongly triggering this.
    # Assumes holes are played sequentially (N → N+1) for rule (c).
    TEE_PROXIMITY_M = 8
    HOLE_TRANSITION_GAP_S = 30

    hole_assignments = []
    current_hole = -1
    current_hole_has_putt = False
    last_strict_on_green_time = None
    last_t = None

    for i, row in sdf.iterrows():
        lat, lon = row["lat"], row["lon"]
        if pd.isna(lat) or pd.isna(lon):
            hole_assignments.append(current_hole)
            continue

        new_hole = False
        new_hole_number = None

        # Rule (d): shot strictly inside a DIFFERENT hole's polygon.
        # This is the strongest signal — if the GPS puts the shot inside
        # another hole's green, we're definitively on that hole now.
        # Handles the case where a soft tee shot wasn't pressed (so we
        # missed the "pitch" signal) and the first press is the approach
        # putt already on the new hole's green.
        strict_match_hole = None
        for hd in holes_data:
            if point_in_polygon(lat, lon, hd["green_polygon"]):
                strict_match_hole = hd["hole"]
                break

        if row["peak_mag"] > PITCH_THRESHOLD:
            new_hole = True
            nearest_h, _ = find_nearest_tee(lat, lon, holes_data)
            new_hole_number = nearest_h
        elif strict_match_hole is not None and strict_match_hole != current_hole:
            new_hole = True
            new_hole_number = strict_match_hole
        elif current_hole_has_putt:
            nearest_h, nearest_d = find_nearest_tee(lat, lon, holes_data)
            if nearest_d <= TEE_PROXIMITY_M and nearest_h != current_hole:
                new_hole = True
                new_hole_number = nearest_h
        # Rule (c): after a strict-polygon putt + walk + off-green shot
        if (not new_hole
                and last_strict_on_green_time is not None
                and last_t is not None
                and (row["marker_t"] - last_strict_on_green_time) > HOLE_TRANSITION_GAP_S):
            if find_green(lat, lon, holes_data) is None:
                new_hole = True
                new_hole_number = current_hole + 1 if 1 <= current_hole < 18 else -1

        if new_hole:
            current_hole = new_hole_number
            current_hole_has_putt = False
            last_strict_on_green_time = None
        else:
            # Check if THIS shot is a putt strictly on the current hole's green
            strict_on = any(
                point_in_polygon(lat, lon, hd["green_polygon"])
                for hd in holes_data
            )
            if strict_on:
                last_strict_on_green_time = row["marker_t"]
            on_green = find_green(lat, lon, holes_data)
            if on_green == current_hole:
                current_hole_has_putt = True

        last_t = row["marker_t"]
        hole_assignments.append(current_hole)

    sdf["hole"] = hole_assignments

    # --- Pass 2: classify using forward green-start scan ---
    # In P&P the shot order is always: pitch → chip(s) → putt(s). Once the
    # player reaches the green, they stay on it until the ball is holed.
    # So we scan forward and find the FIRST shot that's strictly inside a
    # green polygon — from that point on, every shot is a putt, even if
    # GPS drifts off-green on gentle tap-ins.
    #
    # If no shot is strictly in a polygon (but some are in the centroid+
    # buffer), fall back to the generous on-green check to avoid missing
    # all putts on a hole.
    #
    # The first shot of a hole is always the tee shot (pitch), even if
    # peak_mag is below PITCH_THRESHOLD — handles soft tee shots (iron,
    # putter) on very short holes.
    for h in sdf["hole"].unique():
        if h < 0:
            continue
        hole_indices = sdf[sdf["hole"] == h].index.tolist()

        # Find the FIRST shot that starts the putting phase.
        # Prefer a STRICT polygon match (unambiguous on-green). Chips played
        # near the green often fall inside the generous centroid+buffer but
        # are outside the polygon — using strict avoids starting the putting
        # phase at a chip. If no strict polygon match exists anywhere in
        # the hole, fall back to the generous check.
        first_putt_pos = None
        for pos, idx in enumerate(hole_indices[1:], start=1):
            if sdf.at[idx, "peak_mag"] > PITCH_THRESHOLD:
                continue
            lat, lon = sdf.at[idx, "lat"], sdf.at[idx, "lon"]
            if any(point_in_polygon(lat, lon, hd["green_polygon"]) for hd in holes_data):
                first_putt_pos = pos
                break
        # Fallback: no strict polygon match found, use generous
        if first_putt_pos is None:
            for pos, idx in enumerate(hole_indices[1:], start=1):
                if sdf.at[idx, "peak_mag"] > PITCH_THRESHOLD:
                    continue
                on_green = find_green(sdf.at[idx, "lat"], sdf.at[idx, "lon"], holes_data)
                if on_green is not None:
                    first_putt_pos = pos
                    break

        for pos, idx in enumerate(hole_indices):
            if pos == 0:
                sdf.at[idx, "class"] = "pitch"
            elif sdf.at[idx, "peak_mag"] > PITCH_THRESHOLD:
                sdf.at[idx, "class"] = "pitch"
            elif first_putt_pos is not None and pos >= first_putt_pos:
                sdf.at[idx, "class"] = "putt"
            else:
                sdf.at[idx, "class"] = "chip"

        # --- Pass 3: chip safety net using new temporal features ---
        # A shot GPS-classified as putt but with a chip-like temporal
        # signature (long impact duration + zero rise rate) is likely
        # a chip played near the green fringe that GPS misclassified.
        # Only flip the FIRST putt(s) — once confirmed putting starts,
        # subsequent shots stay as putts (player is on the green).
        # Requires the new features (peak_duration + rise_rate) to be
        # populated; older FIT files are unaffected.
        for pos, idx in enumerate(hole_indices):
            if sdf.at[idx, "class"] != "putt":
                continue
            row = sdf.loc[idx]
            if pd.isna(row.get("peak_duration")) or pd.isna(row.get("rise_rate")):
                break
            chip_like = (row["peak_duration"] >= 160) and (row["rise_rate"] == 0)
            if not chip_like:
                break
            # Check if GPS was strict (on polygon) or loose (centroid fallback)
            strict_on_green = False
            for hd in holes_data:
                if point_in_polygon(row["lat"], row["lon"], hd["green_polygon"]):
                    strict_on_green = True
                    break
            if not strict_on_green:
                sdf.at[idx, "class"] = "chip"

    return sdf


def apply_corrections(sdf, corrections):
    """Apply manual corrections to a classified shots DataFrame.

    corrections dict schema:
      exclude_markers: list of marker numbers to drop (double-presses, noise)
      reclassify:  list of {marker, class} to override shot class
      reassign_hole: list of {marker, hole} to move a shot to a specific hole
      insert_shots: list of {hole, position, class} to add a missing shot
                    (position = 1-indexed within the hole; class = pitch/chip/putt)

    Returns a new DataFrame with the corrections applied.
    """
    if not corrections:
        return sdf

    # 1. Drop excluded markers
    if corrections.get("exclude_markers"):
        sdf = sdf[~sdf["marker"].isin(corrections["exclude_markers"])].reset_index(drop=True)

    # 2. Reclassify shots
    for rc in corrections.get("reclassify", []):
        mask = sdf["marker"] == rc["marker"]
        if mask.any():
            sdf.loc[mask, "class"] = rc["class"]

    # 3. Reassign shots to a different hole
    for ra in corrections.get("reassign_hole", []):
        mask = sdf["marker"] == ra["marker"]
        if mask.any():
            sdf.loc[mask, "hole"] = ra["hole"]

    # 4. Insert synthetic shots for missed presses
    #    Position is 1-indexed within the hole. A synthetic shot gets a
    #    fake marker number (>= 10000) so it can't conflict with real ones.
    fake_marker = 10000
    for ins in corrections.get("insert_shots", []):
        hole = ins["hole"]
        position = ins.get("position", 1)
        shot_class = ins["class"]
        hole_mask = sdf["hole"] == hole
        hole_rows = sdf[hole_mask].sort_values("marker_t").reset_index(drop=True)

        # Pick a plausible timestamp: between neighbours if possible
        if position <= 1:
            t_new = hole_rows["marker_t"].iloc[0] - 30 if len(hole_rows) > 0 else 0
        elif position > len(hole_rows):
            t_new = hole_rows["marker_t"].iloc[-1] + 30
        else:
            t_new = (hole_rows["marker_t"].iloc[position - 2] + hole_rows["marker_t"].iloc[position - 1]) / 2

        # Pick a plausible location: centroid of surrounding shots
        if len(hole_rows) > 0:
            lat_new = hole_rows["lat"].mean()
            lon_new = hole_rows["lon"].mean()
        else:
            lat_new, lon_new = None, None

        new_row = {col: None for col in sdf.columns}
        new_row.update({
            "marker": fake_marker,
            "marker_t": t_new,
            "peak_t": t_new,
            "peak_mag": 0.0,
            "std_mag": 0.0,
            "max_jerk": 0.0,
            "lat": lat_new,
            "lon": lon_new,
            "hole": hole,
            "class": shot_class,
            "synthetic": True,
        })
        fake_marker += 1
        sdf = pd.concat([sdf, pd.DataFrame([new_row])], ignore_index=True)

    # Re-sort by time so per-hole shot ordering is correct
    sdf = sdf.sort_values(["hole", "marker_t"]).reset_index(drop=True)
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
    parser.add_argument("--corrections", default=None,
                        help="Optional JSON file of manual corrections to apply")
    args = parser.parse_args()

    # Load course
    course = json.load(open(args.course_json))
    holes_data = course["holes"]
    print(f"Course: {course['name']} ({course['n_holes']} holes)")

    # Load corrections if specified
    corrections = None
    if args.corrections:
        corrections = json.load(open(args.corrections))
        print(f"Corrections: {args.corrections}")

    # Load round
    df = load_round(args.fit_file)
    duration_min = df["t"].iloc[-1] / 60
    print(f"Round: {len(df)} records, {duration_min:.1f} min")

    # Extract and classify shots
    sdf = extract_shots(df)
    print(f"Shots detected: {len(sdf)}")

    sdf = classify_shots(sdf, holes_data)

    # Apply corrections (after classification, before output)
    if corrections:
        before = len(sdf)
        sdf = apply_corrections(sdf, corrections)
        print(f"Applied corrections: {before} → {len(sdf)} shots")

    # Print scorecard
    print_scorecard(sdf, course_name=course["name"])

    # Save CSV
    output = args.output or args.fit_file.rsplit(".", 1)[0] + "_classified.csv"
    sdf.to_csv(output, index=False)
    print(f"\nSaved classified shots to: {output}")


if __name__ == "__main__":
    main()
