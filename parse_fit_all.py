import fitparse
import sys

fit_file = sys.argv[1] if len(sys.argv) > 1 else "2026-04-05-14-26-48.fit"
fitfile = fitparse.FitFile(fit_file)

for msg in fitfile.get_messages():
    print(f"\n=== {msg.name} ===")
    for field in msg.fields:
        if field.value is not None:
            print(f"  {field.name}: {field.value}")
