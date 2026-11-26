# Park and Ride (Transport NSW) for Home Assistant

Live **available spaces** for Transport for NSW Park&Ride car parks, as Home Assistant sensors.
Pick one or more of the ~40 car parks and the integration polls Transport NSW on a schedule
you control.

> Unofficial. Not affiliated with or endorsed by Transport for NSW. Uses the official
> [Transport Open Data Car Park API](https://opendata.transport.nsw.gov.au/data/dataset/car-park-api)
> (`/v1/carpark/full-list`), which needs a free API key.

## Install

**Home Assistant Marketplace (2026.11 and later)**

1. Go to *Settings → Marketplace*. On your first visit, select **I understand the risks and agree**.
2. Search for **Park and Ride (Transport NSW)** and open it.
3. Select **Install**, check the version, then select **Install** again.
4. The setup flow opens straight away, with no restart needed. If it doesn't, add the integration from
   *Settings → Devices & services*. If a repair under *Settings → System → Repairs* asks for a restart, restart.

Updates appear under *Settings → Updates* and need a restart.

If it doesn't show up in the search, add it from its link instead: select **Add from link** (top right),
enter `https://github.com/dinc5150/HA-Park-and-Ride-Parking-NSW` in **GitHub link**, and select **Add**.
If asked for a **Type**, choose **Integration**. The first time you add a link, the Marketplace asks you to
sign in with GitHub: select **Continue**, open the GitHub link it shows, enter the code and approve.
Then continue from step 3.

**HACS (Home Assistant 2026.10 and earlier)**

1. Open HACS and search for **Park and Ride (Transport NSW)**.
2. Open it, select **Download**, then restart Home Assistant.

If it doesn't show up in the search (for example, on an older HACS), add it as a custom repository instead:
HACS → ⋮ → *Custom repositories* → add `https://github.com/dinc5150/HA-Park-and-Ride-Parking-NSW`
with category **Integration**, then download it and restart as above.

**Manual**: copy `custom_components/park_and_ride` into your Home Assistant `config/custom_components/` folder and restart.

## Get an API key (free)

1. Register at the [Transport Open Data Hub](https://opendata.transport.nsw.gov.au).
2. Create an application and add the **Car park API** to it.
3. Copy the application's API key.

## Set up

*Settings → Devices & services → Add integration → Park and Ride.*

- **API key** – paste the key (pasting the whole `apikey ...` header value also works). If Transport NSW later rejects it, Home Assistant prompts you to re-enter it.
- **Car parks** – tick one or more. Each becomes its own device.
- **Update interval** – minutes between polls (default 5, range 1–60). One request fetches every
  car park, so tracking more of them costs nothing extra.

Change either later via *Configure* on the integration. Un-ticking a car park removes its
device and sensors.

## Entities (per car park)

| Entity | Notes |
| --- | --- |
| `sensor.<name>_available_spaces` | The headline number. Attributes: address, suburb, lat/long, capacity, occupied |
| `sensor.<name>_occupied_spaces` | As reported by Transport NSW |
| `sensor.<name>_occupancy` | Percent, capped at 100 |
| `sensor.<name>_capacity` | Diagnostic |
| `sensor.<name>_last_updated` | Diagnostic timestamp of the car park's last reading |

Entities go **unavailable** if a poll fails or a car park disappears from the feed.

### Things worth knowing

- The feed sometimes reports more cars than spaces (e.g. 229 in 228). Available spaces are floored at 0.
- Each car park reports on its own schedule, so check `last_updated` before trusting a number.
- Available spaces is `spots - occupancy.total`, Transport NSW's recommended calculation. If a car park isn't reporting a count, the sensors show *unknown* rather than "full".
- Car parks can share a `tsn` (stop id), so this integration keys everything on the feed's `facility_id`.
- Each car park updates on its own schedule (from every 15 seconds to every ~10 minutes), so polling more often than every few minutes rarely helps.
- `MessageDate` carries no timezone; it is Sydney local time (confirmed against the live feed).

## Examples

Dashboard card:

```yaml
type: entities
title: Park & Ride
entities:
  - sensor.ashfield_available_spaces
  - sensor.beverly_hills_available_spaces
```

Notify when a car park has room:

```yaml
automation:
  - alias: "Ashfield car park has space"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.ashfield_available_spaces
        above: 20
    conditions:
      - condition: time
        after: "06:30:00"
        before: "09:00:00"
        weekday: [mon, tue, wed, thu, fri]
    actions:
      - action: notify.notify
        data:
          message: "Ashfield Park&Ride has {{ states('sensor.ashfield_available_spaces') }} spaces"
```

## Development

```bash
pip install -r requirements_test.txt
pytest
export TFNSW_API_KEY=your-key
python scripts/check_api.py Ashfield   # confirm your key works and the response parses
python scripts/check_api.py --raw      # dump the raw JSON if something looks off
```

Python 3.13 / Home Assistant 2025.1+ . CI runs hassfest, HACS validation and the tests.

## Before publishing

- Push a tagged GitHub release (e.g. `v1.0.0`, matching `manifest.json`'s `version`) so the Marketplace (and HACS) can install a pinned version.
- Each user needs their own Open Data Hub key; never commit one.

## Attribution

Car park data © Transport for NSW, licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) via the Open Data Hub.
This project is not endorsed by Transport for NSW.

## License

MIT
