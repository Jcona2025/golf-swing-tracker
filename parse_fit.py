import fitparse
import pandas as pd
import matplotlib.pyplot as plt
import sys

fit_file = sys.argv[1] if len(sys.argv) > 1 else "2026-04-05-14-26-48.fit"

fitfile = fitparse.FitFile(fit_file)

# Extract all record messages
records = []
for record in fitfile.get_messages("record"):
    row = {}
    for field in record.fields:
        row[field.name] = field.value
    records.append(row)

df = pd.DataFrame(records)

print(f"Total records: {len(df)}")
print(f"\nColumns: {list(df.columns)}")
print(f"\nFirst 5 rows:")
print(df.head())
print(f"\nLast 5 rows:")
print(df.tail())

# Check for developer fields
dev_fields = [c for c in df.columns if 'accel' in c.lower() or 'peak' in c.lower() or 'sample' in c.lower()]
print(f"\nDeveloper fields found: {dev_fields}")

if dev_fields:
    print(f"\nDeveloper field stats:")
    print(df[dev_fields].describe())
