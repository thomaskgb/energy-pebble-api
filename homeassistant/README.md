# Energy Pebble — Home Assistant integration

Shows your pebble's color signal in Home Assistant: a `sensor` with the
current color (`green` / `yellow` / `red`) and the next 8 hours as attributes.
The data is personalized to your household profile (contract, solar, battery)
because it polls the same endpoint your physical pebble uses.

## Install (manual, for now)

1. Copy `custom_components/energy_pebble/` into your Home Assistant
   `config/custom_components/` directory and restart Home Assistant.
2. On [energypebble.tdlx.nl/dashboard](https://energypebble.tdlx.nl/dashboard),
   open your user menu → **Settings → Account** and create a
   **Home Assistant token**. Copy it — it is shown only once.
3. In Home Assistant: **Settings → Devices & services → Add integration →
   Energy Pebble**. Paste the token, then pick which of your pebbles to follow.

HACS distribution needs the integration in its own repository — planned once
the integration stabilizes.

## Entities

- `sensor.<nickname>_color` — current color (enum: green/yellow/red), with
  attributes: `next_hours` (hour + color for the next 8 hours),
  `signal_source`, `personalized`, and the `display` block.

## Example automation

```yaml
automation:
  - alias: Start dishwasher when the pebble turns green
    triggers:
      - trigger: state
        entity_id: sensor.kitchen_color
        to: "green"
    actions:
      - action: switch.turn_on
        target:
          entity_id: switch.dishwasher
```
