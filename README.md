# Golf Swing Tracker

A Garmin Connect IQ app for the Forerunner 255 that records wrist accelerometer data during golf shots, paired with a Python ML pipeline that classifies shot types from the recorded data.

## Project Structure

- `source/` — Monkey C source for the Connect IQ app (`SwingLoggerApp`, `SwingLoggerView`, `SwingLoggerDelegate`)
- `manifest.xml`, `monkey.jungle` — Build configuration
- `resources/` — App icon and string resources
- `analysis_*.ipynb` — Jupyter notebooks for data analysis and ML
- `parse_fit.py`, `plot_fit.py` — Helper scripts for FIT file parsing
- `*.fit` — Recorded training data (putts and pitch shots)

## How It Works

1. **On the watch:** App samples the accelerometer at 25 Hz internally and writes 8 features per second (peak/min/mean/std magnitude, max jerk, peak X/Y/Z) into a FIT activity file via custom developer fields.
2. **Off the watch:** FIT files are pulled from `GARMIN/ACTIVITY/` over USB.
3. **In Python:** Notebooks parse the FIT files with `fitparse`, segment strokes with `scipy.signal.find_peaks`, and train sklearn classifiers (Random Forest, Gradient Boosting, SVM, LogReg, KNN) with grid search.

## Building the App

```bash
export CIQ_HOME="$HOME/.Garmin/ConnectIQ/Sdks/connectiq-sdk-lin-9.1.0-2026-03-09-6a872a80b"
java -jar "$CIQ_HOME/bin/monkeybrains.jar" \
  -o SwingLogger.prg \
  -f monkey.jungle \
  -y ~/connectiq_dev_key.der \
  -d fr255 \
  -w
```

Copy `SwingLogger.prg` to the watch's `GARMIN/APPS/` folder via USB.
