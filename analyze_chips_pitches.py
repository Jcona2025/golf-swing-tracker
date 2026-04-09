"""Compare 10 long chips vs 10x 45m pitches - find chip signature."""
import fitparse
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import find_peaks


def load(fname):
    fit = fitparse.FitFile(fname)
    rows = [{f.name: f.value for f in r.fields} for r in fit.get_messages("record")]
    df = pd.DataFrame(rows).dropna(subset=["peak_mag"]).reset_index(drop=True)
    df["t"] = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    return df


chips = load("10long chips.fit")
pitches = load("10x45mpitch.fit")

print(f"CHIPS: {len(chips)}s")
print(chips[["peak_mag", "peak_x", "peak_y", "peak_z"]].describe())
print()
print(f"PITCHES: {len(pitches)}s")
print(pitches[["peak_mag", "peak_x", "peak_y", "peak_z"]].describe())

# Plot 4-row figure: chips peak_mag, chips per-axis, pitches peak_mag, pitches per-axis
fig, axes = plt.subplots(4, 1, figsize=(14, 12))

# Chips peak_mag
ax = axes[0]
ax.plot(chips["t"], chips["peak_mag"], color="C0", marker="o", markersize=3)
ax.axhline(1500, color="orange", ls="--", alpha=0.5, label="1500mg")
ax.axhline(2000, color="red", ls="--", alpha=0.5, label="2000mg")
ax.set_title(f"10 long chips - peak_mag (max={chips['peak_mag'].max():.0f}mg)")
ax.set_ylabel("mg")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

# Chips per-axis
ax = axes[1]
for col, c in [("peak_x", "C1"), ("peak_y", "C2"), ("peak_z", "C3")]:
    ax.plot(chips["t"], chips[col], label=col, color=c, alpha=0.8)
ax.set_title("10 long chips - per-axis peaks")
ax.set_ylabel("mg")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

# Pitches peak_mag
ax = axes[2]
ax.plot(pitches["t"], pitches["peak_mag"], color="C0", marker="o", markersize=2)
ax.axhline(1500, color="orange", ls="--", alpha=0.5)
ax.axhline(2000, color="red", ls="--", alpha=0.5)
ax.set_title(f"10x 45m pitches - peak_mag (max={pitches['peak_mag'].max():.0f}mg)")
ax.set_ylabel("mg")
ax.grid(alpha=0.3)

# Pitches per-axis
ax = axes[3]
for col, c in [("peak_x", "C1"), ("peak_y", "C2"), ("peak_z", "C3")]:
    ax.plot(pitches["t"], pitches[col], label=col, color=c, alpha=0.8)
ax.set_title("10x 45m pitches - per-axis peaks")
ax.set_ylabel("mg")
ax.set_xlabel("seconds")
ax.legend(fontsize=8)
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig("chips_vs_pitches.png", dpi=100)
print("\nSaved chips_vs_pitches.png")

# Try segmentation on each
print("\n=== Segmentation experiments ===")
for name, df in [("CHIPS", chips), ("PITCHES", pitches)]:
    print(f"\n{name}:")
    for thr in [1200, 1500, 1800, 2000, 2500, 3000]:
        # Count clusters: contiguous runs above threshold separated by >= 2 records below
        above = df["peak_mag"].values > thr
        # Count rising edges
        edges = np.sum((above[1:]) & (~above[:-1]))
        if above[0]:
            edges += 1
        print(f"  threshold={thr}mg: {above.sum()} records above, {edges} rising edges (clusters)")
    # find_peaks with distance
    for dist in [2, 3, 4]:
        peaks, _ = find_peaks(df["peak_mag"].values, height=1200, distance=dist)
        print(f"  find_peaks(height=1200, distance={dist}s): {len(peaks)} peaks")
