# North Herts Bins

A Home Assistant custom integration that reads your bin collection days from
[North Herts Council](https://www.north-herts.gov.uk/find-your-bin-collection-day)
and lets you get a notification on the day your bins go out.

Covers all five bin types:

| Bin | Container |
| --- | --- |
| Cardboard & Paper | Blue lid bin |
| Mixed Recycling | Black lid bin |
| Non-Recyclable Waste | Purple lid bin |
| Food Waste | Brown caddy |
| Garden Waste | Brown lid bin |

## Installation

### HACS (recommended)

1. In HACS, open the three-dot menu → **Custom repositories**.
2. Add `https://github.com/spiros-spiros/hitchin-bin-days` as an **Integration**.
3. Install **North Herts Bins**, then restart Home Assistant.

### Manual

Copy `custom_components/north_herts_bins` into your Home Assistant
`config/custom_components/` directory and restart.

## Setup

The council's lookup tool doesn't have a public API, and its address search is
blocked to non-browser clients. So you do the address lookup once in your
browser and give the integration the resulting link.

1. Go to <https://www.north-herts.gov.uk/find-your-bin-collection-day> and click
   through to the lookup tool.
2. Type your postcode (**with a space**, e.g. `SG6 3JF`), pick your address, and
   submit.
3. When your bin days are shown, copy the whole URL from the browser address
   bar. It looks like:

   ```
   https://waste.nc.north-herts.gov.uk/w/webpage/find-bin-collection-day-show-details?webpage_token=...&auth=...&id=...
   ```

4. In Home Assistant go to **Settings → Devices & Services → Add Integration**,
   search for **North Herts Bins**, and paste the URL.

The integration validates the link immediately, so you'll know straight away if
you pasted the wrong page. Data refreshes every 6 hours.

If the link ever stops working, Home Assistant will prompt you to repair the
integration — repeat the steps above and paste a fresh URL. Your history and
automations are kept.

## Entities

For an address like `1 EXAMPLE STREET`, you get:

**Binary sensors** — the ones to use in automations:

- `binary_sensor.…_bin_day_today` — on if *any* bin goes out today
- `binary_sensor.…_bin_day_tomorrow` — on if any bin goes out tomorrow
- `binary_sensor.…_food_waste_today` — one per bin type

The `bin_day_today` / `bin_day_tomorrow` sensors carry attributes that are handy
in messages:

- `bins` — list of bin names due, e.g. `["Cardboard & Paper", "Food Waste"]`
- `containers` — e.g. `["Blue lid bin", "Brown caddy"]`
- `message` — ready-made text, e.g. `Cardboard & Paper (Blue lid bin), Food Waste (Brown caddy)`

**Sensors:**

- `sensor.…_food_waste` — next collection date (one per bin type), with
  `container`, `cycle`, `days_until`, `is_today` and `is_tomorrow` attributes
- `sensor.…_food_waste_in` — days until that collection, as a number
- `sensor.…_next_collection` — the soonest date across all bins
- `sensor.…_next_collection_bins` — which bins those are, as text

**Calendar:**

- `calendar.…_bin_collections` — upcoming collections as all-day events

These update at midnight as well as on each poll, so "today" is always correct
even between refreshes.

## Notifications

A blueprint is included. Copy
`blueprints/automation/north_herts_bins/bin_day_notification.yaml` into your
`config/blueprints/automation/` folder, then **Settings → Automations &
Scenes → Blueprints → Create automation**.

It asks for the two bin-day sensors, your notify service (e.g.
`mobile_app_your_phone`), and the times to notify. You can enable a morning
reminder on the day, an evening reminder the night before, or both.

Prefer to write it yourself? This is all it takes:

```yaml
automation:
  - alias: Bin day
    triggers:
      - trigger: time
        at: "07:00:00"
    conditions:
      - condition: state
        entity_id: binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today
        state: "on"
    actions:
      - action: notify.mobile_app_your_phone
        data:
          title: Bin day
          message: >-
            Bins go out today:
            {{ state_attr('binary_sensor.1_example_street_hitchin_sg4_0aa_bin_day_today', 'message') }}
```

## How it works

The council's tool is a Netcall Liberty Create app. A plain request returns only
a JavaScript shell, but the page fills itself in with a single AJAX `POST` back
to the same URL, which responds with JSON containing the rendered HTML. The
integration makes exactly that one request per refresh and parses the result —
no browser or scraping framework needed.

Because this reads a public web page rather than a documented API, a redesign of
the council's site could break it. The integration fails loudly (entities go
unavailable, with a clear error in the log) rather than silently reporting stale
dates.

## Development

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m pytest
```

The tests run against a captured copy of the council's response, so they don't
hit the live site. The fixture is anonymised — it has a made-up address and
placeholder tokens.

## Disclaimer

Not affiliated with or endorsed by North Herts Council. Please don't lower the
refresh interval; collection days change at most weekly.
