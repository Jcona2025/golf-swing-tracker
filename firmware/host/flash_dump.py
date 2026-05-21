"""Offload the XIAO's flash log over USB Serial to a local CSV file.

Plug the XIAO into the laptop after a recording session and run:

    python flash_dump.py --port COM6 --out captures/round_2026-05-21.csv

Talks the firmware/xiao_imu_flash/ protocol:
    1. Opens the serial port.
    2. Sends 'd' to trigger dump.
    3. Reads lines until '# END_DUMP'.
    4. Writes the CSV body to the output file.
    5. Optionally sends 'e' to erase the flash for the next session.

The 3-second startup window in the firmware means: connect within ~2s
of board reset to catch it, or just let it boot into logging mode
and run this script — it'll send 'd' which the idle-mode loop also handles.
"""
import argparse
import sys
import time
from pathlib import Path

try:
    import serial
except ImportError:
    sys.exit("pyserial not installed. Run: pip install pyserial")


def detect_port_windows():
    """Best-effort port detection on Windows."""
    try:
        from serial.tools.list_ports import comports
    except ImportError:
        return None
    candidates = [p for p in comports() if "USB" in (p.description or "")]
    return candidates[0].device if candidates else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="COM port (e.g. COM6 on Windows, /dev/ttyACM0 on Linux)")
    ap.add_argument("--out", required=True, help="output CSV path")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--erase", action="store_true",
                    help="After dump, send 'e' to erase flash (frees space for next session)")
    args = ap.parse_args()

    port = args.port or detect_port_windows()
    if not port:
        sys.exit("Could not detect port. Pass --port COM6 (or the right number).")

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Opening {port} @ {args.baud}...")
    with serial.Serial(port, args.baud, timeout=5) as ser:
        # Brief settle, then trigger dump
        time.sleep(0.2)
        ser.reset_input_buffer()
        print("Sending 'd'...")
        ser.write(b'd')
        ser.flush()

        sample_count = 0
        started = False
        out_lines = []
        t0 = time.time()

        while True:
            raw = ser.readline()
            if not raw:
                # timeout; if we've seen the header, assume done
                if started and out_lines:
                    print("  (read timeout; treating as end of dump)")
                    break
                continue
            line = raw.decode(errors='replace').rstrip()

            if line.startswith("# samples="):
                started = True
                print(f"  firmware reports: {line}")
                continue
            if line.startswith("# END_DUMP"):
                print("  END_DUMP received")
                break
            if line.startswith("#"):
                # informational
                print(f"  {line}")
                continue
            if line.startswith("t_ms,"):
                # CSV header
                out_lines.append(line)
                continue
            if "," in line and started:
                out_lines.append(line)
                sample_count += 1
                if sample_count % 1000 == 0:
                    elapsed = time.time() - t0
                    rate = sample_count / elapsed if elapsed else 0
                    print(f"  {sample_count} rows ({rate:.0f}/s)")

        with open(out_path, "w") as f:
            f.write("\n".join(out_lines) + "\n")

        elapsed = time.time() - t0
        print(f"\nDone. {sample_count} samples in {elapsed:.1f}s → {out_path}")

        if args.erase:
            print("Sending 'e' to erase flash...")
            ser.write(b'e')
            ser.flush()
            time.sleep(0.5)
            # Read any response
            while ser.in_waiting:
                print("  " + ser.readline().decode(errors='replace').rstrip())


if __name__ == "__main__":
    main()
