import fitparse
import pandas as pd
import matplotlib.pyplot as plt
import sys

fit_file = sys.argv[1] if len(sys.argv) > 1 else "2026-04-05-14-35-12.fit"

fitfile = fitparse.FitFile(fit_file)

records = []
for record in fitfile.get_messages("record"):
    row = {}
    for field in record.fields:
        row[field.name] = field.value
    records.append(row)

df = pd.DataFrame(records)
df['elapsed'] = range(len(df))

fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

# Plot individual axes
axes[0].plot(df['elapsed'], df['peak_accel_x'], label='X', alpha=0.8)
axes[0].plot(df['elapsed'], df['peak_accel_y'], label='Y', alpha=0.8)
axes[0].plot(df['elapsed'], df['peak_accel_z'], label='Z', alpha=0.8)
axes[0].set_ylabel('Peak Acceleration (mg)')
axes[0].set_title('Peak Accelerometer Readings Per Second')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Plot magnitude
axes[1].plot(df['elapsed'], df['peak_magnitude'], color='red', linewidth=2)
axes[1].set_ylabel('Peak Magnitude (mg)')
axes[1].set_xlabel('Time (seconds)')
axes[1].set_title('Peak Acceleration Magnitude')
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('accel_plot.png', dpi=150)
print(f"Plot saved to accel_plot.png")
plt.close()
