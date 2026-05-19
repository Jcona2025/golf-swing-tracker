"""BLE receiver for the SwingLogger IMU stream.

Pairs with a XIAO running firmware/xiao_imu_ble/, subscribes to the IMU
notify characteristic, decodes the 16-byte packets, and writes CSV.

Usage (run from Windows PowerShell — WSL doesn't have native BLE):
    pip install bleak
    python ble_capture.py [--out swings.csv] [--seconds 30]

Packet layout (from firmware/xiao_imu_ble/xiao_imu_ble.ino):
    uint32  t_ms     bytes 0..3
    int16   ax raw   bytes 4..5    (±16g)
    int16   ay raw   bytes 6..7
    int16   az raw   bytes 8..9
    int16   gx raw   bytes 10..11  (±2000 dps)
    int16   gy raw   bytes 12..13
    int16   gz raw   bytes 14..15
"""
import argparse
import asyncio
import struct
import sys
import time
from pathlib import Path

from bleak import BleakClient, BleakScanner

# The firmware sets the GAP name to "SwingLogger" but BLE advertising
# packets only have ~5 spare bytes after flags+TX-power+128-bit-service-UUID,
# so what gets broadcast is the truncated "Swing".
DEVICE_NAME = "Swing"
# Must match the IMU characteristic UUID in the firmware (little-endian byte
# order in the firmware constant -> standard UUID string form here)
IMU_CHAR_UUID = "6162656e-696c-0002-736e-657342534d4f"

ACCEL_SCALE = 16.0 / 32768.0      # raw -> g
GYRO_SCALE  = 2000.0 / 32768.0    # raw -> dps


async def find_device(timeout: float = 10.0):
    print(f"Scanning for '{DEVICE_NAME}' (timeout {timeout}s)...")
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=timeout)
    if dev is None:
        print(f"  Not found. Is the XIAO powered and advertising?")
        sys.exit(1)
    print(f"  Found {dev.name} @ {dev.address}")
    return dev


async def capture(device, out_path: Path, seconds: float):
    sample_count = 0
    start_wall = time.time()

    with open(out_path, "w") as f:
        f.write("t_ms,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps\n")

        SAMPLE_FMT = "<Ihhhhhh"   # 16 bytes per sample
        SAMPLE_LEN = 16

        def on_packet(_handle, data: bytearray):
            nonlocal sample_count
            # v2 firmware sends 80-byte packets (5 samples). v1 sent 16-byte
            # single samples. Handle either by iterating in 16-byte chunks.
            n = len(data) // SAMPLE_LEN
            for i in range(n):
                chunk = data[i * SAMPLE_LEN : (i + 1) * SAMPLE_LEN]
                t_ms, ax, ay, az, gx, gy, gz = struct.unpack(SAMPLE_FMT, chunk)
                f.write(
                    f"{t_ms},"
                    f"{ax * ACCEL_SCALE:.4f},"
                    f"{ay * ACCEL_SCALE:.4f},"
                    f"{az * ACCEL_SCALE:.4f},"
                    f"{gx * GYRO_SCALE:.2f},"
                    f"{gy * GYRO_SCALE:.2f},"
                    f"{gz * GYRO_SCALE:.2f}\n"
                )
                sample_count += 1
            if sample_count % 100 < n:
                elapsed = time.time() - start_wall
                rate = sample_count / elapsed if elapsed else 0
                print(f"  {sample_count} samples ({rate:.0f} Hz effective)")

        async with BleakClient(device) as client:
            print(f"Connected. Subscribing to IMU notifications...")
            await client.start_notify(IMU_CHAR_UUID, on_packet)
            print(f"Capturing for {seconds}s — swing now!")
            await asyncio.sleep(seconds)
            await client.stop_notify(IMU_CHAR_UUID)

    elapsed = time.time() - start_wall
    rate = sample_count / elapsed if elapsed else 0
    print(f"\nDone. {sample_count} samples in {elapsed:.1f}s ({rate:.0f} Hz)")
    print(f"  Saved to {out_path}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="swings.csv")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--scan-timeout", type=float, default=10.0)
    args = ap.parse_args()

    out_path = Path(args.out).resolve()
    dev = await find_device(args.scan_timeout)
    await capture(dev, out_path, args.seconds)


if __name__ == "__main__":
    asyncio.run(main())
