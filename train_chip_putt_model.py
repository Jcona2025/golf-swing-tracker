"""Train the chip vs putt Gradient Boosting model on all labelled rounds.

Loads each round, extracts shots + ground-truth labels, adds GPS-derived
features, filters to chip/putt only, trains Gradient Boosting on the full
dataset, and pickles the trained pipeline to chip_putt_model.pkl.

Run this every time you want to refresh the model with new rounds.
"""
import pandas as pd
import numpy as np
import json
import math
import pickle

from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import GradientBoostingClassifier

from classify_round import (
    load_round, extract_shots, haversine_m, point_in_polygon, find_green,
)


FEATURE_COLS = [
    "peak_mag", "std_mag", "max_jerk",
    "peak_duration", "rise_rate", "peak_count", "pre_stillness",
    "dist_to_green", "on_green_strict", "on_green_buffer",
]


# Ground-truth labels per round (matching the ACTUAL markers, not real shot count)
ROUNDS = [
    {
        "name": "R2", "fit": "2026-04-17-18-32-26.fit", "exclude": [],
        "holes": [
            ["pitch","putt","putt"], ["pitch","putt","putt"], ["pitch","putt","putt"],
            ["pitch","chip","putt"], ["pitch","putt","putt"], ["pitch","putt","putt"],
            ["pitch","putt"], ["pitch","putt"], ["pitch","putt"],
            ["pitch","chip","putt","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","putt"],
            ["pitch","chip","putt"], ["pitch","putt","putt"],
        ],
    },
    {
        "name": "R3", "fit": "Seapoint_1-12.fit", "exclude": [37, 48, 49, 50],
        "holes": [
            ["pitch","putt","putt"], ["pitch","putt"], ["pitch","putt","putt"],
            ["pitch","chip","putt","putt"], ["pitch","putt"], ["pitch","putt"],
            ["pitch","chip","putt"], ["pitch","chip","putt"], ["pitch","putt","putt"],
            ["pitch","chip","putt"], ["pitch","chip","putt"], ["pitch","chip","putt"],
            ["pitch","putt"], ["pitch","putt"],
            ["pitch","chip","putt","putt"], ["pitch","chip","chip","putt"],
            ["pitch","chip","putt"],
        ],
    },
    {
        "name": "R4", "fit": "Seapoint-19-02-26.fit", "exclude": [33],
        "holes": [
            ["pitch","putt"], ["pitch","putt","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","putt","putt"], ["pitch","putt","putt"],
            ["pitch","putt"], ["pitch","chip","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","chip","putt"], ["pitch","putt","putt"],
            ["pitch","chip","putt"], ["pitch","putt"], ["pitch","putt"],
            ["pitch","chip","chip","putt"], ["pitch","putt","putt"], ["pitch","chip","putt"],
        ],
    },
    {
        "name": "R5", "fit": "seapoint-20-04-26.fit", "exclude": [],
        "holes": [
            ["pitch","putt"], ["pitch","putt","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","putt"], ["pitch","putt"],
            ["pitch","putt"], ["pitch","chip","putt","putt","putt"],
            ["pitch","putt","putt"], ["pitch","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","putt","putt"], ["pitch","putt"],
            ["pitch","putt","putt"], ["pitch","chip","chip"],  # H16 missing hole-out
            ["pitch","putt","putt"], ["pitch","putt","putt"],
        ],
    },
    {
        "name": "R6", "fit": "2026-04-21-07-48-24.fit", "exclude": [],
        "holes": [
            ["pitch","chip","putt","putt"], ["pitch","putt","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"], ["pitch","chip","putt"], ["pitch","chip","chip"],
            ["pitch","chip","putt"], ["pitch","chip","putt"], ["pitch","chip","putt"],
            ["pitch","chip","putt"], ["pitch","chip","putt","putt"],
            ["pitch","chip","putt"],
            ["putt","putt"],  # H13: missed pitch press
            ["pitch","putt","putt"], ["pitch","chip","putt"], ["pitch","chip","putt"],
            ["pitch","putt","putt"],
            ["pitch","putt","putt"],  # H18: missed hole-out
        ],
    },
    {
        "name": "R7", "fit": "Seapoint_round_temps.fit", "exclude": [],
        "holes": [
            ["pitch","chip","putt"], ["pitch","chip"], ["pitch","chip","putt","putt"],
            ["pitch","putt","putt"], ["pitch","chip","putt"], ["pitch","chip","putt","putt"],
            ["pitch","putt","putt"], ["pitch","putt","putt"], ["pitch","putt","putt"],
            ["pitch","chip","putt"], ["pitch","chip","putt"], ["pitch","chip","putt","putt"],
            ["pitch","chip","putt"], ["pitch","chip","putt","putt"], ["pitch","putt"],
            ["pitch","chip","putt"], ["pitch","putt","putt"], ["pitch","putt","putt"],
        ],
    },
    # R9: Killineer random holes (24 April 2026). 14 holes played; flat list
    # in marker order matches the 14 detected holes in chronological order.
    {
        "name": "R9", "fit": "Killineer-randon-holes2.fit",
        "course": "killineer.json", "exclude": [],
        "holes": [
            ["pitch","putt","putt"],         # H1
            ["pitch","chip","putt"],         # H3
            ["pitch","chip","putt"],         # H5
            ["pitch","putt"],                # H6
            ["pitch","chip","putt"],         # H7
            ["pitch","chip","putt"],         # H9
            ["pitch","putt"],                # H10
            ["pitch","putt"],                # H12
            ["pitch","putt"],                # H13
            ["pitch","chip","putt"],         # H14
            ["pitch","chip","putt"],         # H15
            ["pitch","putt"],                # H16
            ["pitch","chip","putt"],         # H17
            ["pitch","chip","putt","putt"],  # H18
        ],
    },
]


def add_gps_features(sdf, course):
    """Add dist_to_green, on_green_strict, on_green_buffer per shot."""
    dists, strict, buffer = [], [], []
    for _, row in sdf.iterrows():
        lat, lon = row["lat"], row["lon"]
        dists.append(min(
            haversine_m(lat, lon, h["green_centroid"]["lat"], h["green_centroid"]["lon"])
            for h in course["holes"]
        ))
        s = any(point_in_polygon(lat, lon, h["green_polygon"]) for h in course["holes"])
        strict.append(1 if s else 0)
        b = False
        for h in course["holes"]:
            c = h["green_centroid"]
            r = math.sqrt(h["gps_polygon_area_m2"] / math.pi) + 4
            if haversine_m(lat, lon, c["lat"], c["lon"]) <= r:
                b = True
                break
        buffer.append(1 if b else 0)
    sdf = sdf.copy()
    sdf["dist_to_green"] = dists
    sdf["on_green_strict"] = strict
    sdf["on_green_buffer"] = buffer
    return sdf


def main():
    print("Loading course data...")
    courses = {
        "seapoint.json": json.load(open("seapoint.json")),
        "killineer.json": json.load(open("killineer.json")),
    }

    all_rows = []
    for r in ROUNDS:
        course = courses[r.get("course", "seapoint.json")]
        df = load_round(r["fit"])
        sdf = extract_shots(df)
        sdf = sdf[~sdf["marker"].isin(r["exclude"])].reset_index(drop=True)
        sdf["label"] = [s for hole in r["holes"] for s in hole]
        sdf["round"] = r["name"]
        sdf = add_gps_features(sdf, course)
        all_rows.append(sdf)
        print(f"  {r['name']}: {len(sdf)} shots ({(sdf['label']=='chip').sum()} chips, "
              f"{(sdf['label']=='putt').sum()} putts, {(sdf['label']=='pitch').sum()} pitches)")

    data = pd.concat(all_rows, ignore_index=True)
    # Train on chip + putt only (pitches are solved by peak_mag rule)
    cp = data[data["label"].isin(["chip", "putt"])].reset_index(drop=True)
    print(f"\nTraining set: {len(cp)} samples ({(cp['label']=='chip').sum()} chips, "
          f"{(cp['label']=='putt').sum()} putts)")

    X = cp[FEATURE_COLS].values
    y = (cp["label"] == "chip").astype(int).values  # 1=chip, 0=putt

    # Train Gradient Boosting (the winner from chip_putt_classifier.ipynb)
    model = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=42)),
    ])
    model.fit(X, y)

    # Training accuracy
    y_pred = model.predict(X)
    train_acc = (y_pred == y).mean()
    print(f"Training accuracy: {train_acc:.1%} (note: LOROCV accuracy ~86% is the realistic number)")

    # Save the model + feature list
    artifact = {
        "model": model,
        "feature_cols": FEATURE_COLS,
        "n_training_rounds": len(ROUNDS),
        "n_training_samples": len(cp),
        "n_chips": int((cp["label"] == "chip").sum()),
        "n_putts": int((cp["label"] == "putt").sum()),
    }
    with open("chip_putt_model.pkl", "wb") as f:
        pickle.dump(artifact, f)
    print(f"\nSaved chip_putt_model.pkl")
    print(f"  Trained on {artifact['n_training_rounds']} rounds, {artifact['n_training_samples']} samples")
    print(f"  ({artifact['n_chips']} chips, {artifact['n_putts']} putts)")


if __name__ == "__main__":
    main()
