import fitparse
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

files = [
    ("10x45mpitch.fit", "10x 45m pitch", 10),
    ("10long chips.fit", "10x long chip", 10),
    ("1pitch 1chip 1 putt.fit", "1 pitch + 1 chip + 1 putt", 3),
    ("1Pitch and 1Putt.fit", "1 pitch + 1 putt", 2),
]

fig, axes = plt.subplots(len(files), 1, figsize=(12, 10), sharex=False)

for ax, (fname, title, n_shots) in zip(axes, files):
    fit = fitparse.FitFile(fname)
    rows = []
    for r in fit.get_messages("record"):
        row = {f.name: f.value for f in r.fields}
        rows.append(row)
    df = pd.DataFrame(rows)
    df = df.dropna(subset=["peak_mag"]).reset_index(drop=True)
    print(f"{fname}: {len(df)} rows after dropna, cols={list(df.columns)[:5]}")
    if len(df) == 0:
        continue
    t = (df["timestamp"] - df["timestamp"].iloc[0]).dt.total_seconds()
    ax.plot(t, df["peak_mag"], label="peak_mag", color="C0")
    ax.axhline(2000, color="red", linestyle="--", alpha=0.4, label="2000mg threshold")
    ax.set_title(f"{title} (expected {n_shots} shots, {len(df)}s, max={df['peak_mag'].max():.0f}mg)")
    ax.set_ylabel("mg")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(alpha=0.3)

axes[-1].set_xlabel("seconds")
plt.tight_layout()
plt.savefig("new_files_overview.png", dpi=100)
print("Saved new_files_overview.png")

# Print quick stats per file
for fname, title, n_shots in files:
    fit = fitparse.FitFile(fname)
    rows = [{f.name: f.value for f in r.fields} for r in fit.get_messages("record")]
    df = pd.DataFrame(rows).dropna(subset=["peak_mag"]).reset_index(drop=True)
    above_2000 = (df["peak_mag"] > 2000).sum()
    above_1500 = (df["peak_mag"] > 1500).sum()
    print(f"{title}: {len(df)}s, max={df['peak_mag'].max():.0f}mg, "
          f"records>1500mg={above_1500}, >2000mg={above_2000}")
