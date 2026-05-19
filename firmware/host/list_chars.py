"""List all BLE services + characteristics on the XIAO."""
import asyncio
from bleak import BleakClient, BleakScanner

DEVICE_NAME = "Swing"


async def main():
    print(f"Scanning for '{DEVICE_NAME}'...")
    dev = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
    if not dev:
        print("Not found")
        return
    print(f"Connecting to {dev.address}...")
    async with BleakClient(dev) as client:
        for svc in client.services:
            print(f"\nSERVICE {svc.uuid}")
            for ch in svc.characteristics:
                props = ",".join(ch.properties)
                print(f"  CHAR {ch.uuid}  ({props})")


if __name__ == "__main__":
    asyncio.run(main())
