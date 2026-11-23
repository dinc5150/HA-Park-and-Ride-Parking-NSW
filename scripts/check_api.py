"""Check that your API key works and that the response is parsed correctly.

Run it from any machine that can reach api.transport.nsw.gov.au:

    export TFNSW_API_KEY=your-key
    python scripts/check_api.py              # list every car park
    python scripts/check_api.py Ashfield     # filter by name
    python scripts/check_api.py --raw        # print the first part of the raw JSON

If parsing fails or numbers look wrong, run with --raw and compare it with the
field names documented in the Car Park API documentation (facility_id,
facility_name, spots, occupancy.total, MessageDate).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import aiohttp

API = Path(__file__).parent.parent / "custom_components" / "park_and_ride" / "api.py"
spec = importlib.util.spec_from_file_location("pnr_api", API)
api = importlib.util.module_from_spec(spec)
sys.modules["pnr_api"] = api
spec.loader.exec_module(api)


async def main(term: str, raw: bool) -> int:
    key = os.environ.get("TFNSW_API_KEY", "")
    if not key:
        print(
            "Set TFNSW_API_KEY first (get one at https://opendata.transport.nsw.gov.au)"
        )
        return 2
    async with aiohttp.ClientSession() as session:
        client = api.ParkRideClient(session, key)
        try:
            payload = await client.get_raw()
            if raw:
                print(json.dumps(payload, indent=2)[:4000])
                return 0
            car_parks = api.parse_car_parks(payload)
        except api.ParkRideError as err:
            print(f"FAILED ({type(err).__name__}): {err}")
            return 1
    print(f"OK - {len(car_parks)} car parks\n")
    for cp in sorted(car_parks.values(), key=lambda c: c.short_name):
        if term.lower() in cp.name.lower():
            free = "?" if cp.available is None else cp.available
            when = f"{cp.updated:%d %b %H:%M}" if cp.updated else "no timestamp"
            print(
                f"{cp.id:>4}  {cp.short_name:<40} {free!s:>4} free of {cp.capacity:<4} ({when})"
            )
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--raw"]
    sys.exit(asyncio.run(main(args[0] if args else "", "--raw" in sys.argv)))
