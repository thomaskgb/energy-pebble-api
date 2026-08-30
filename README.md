# Energy Pebble

Belgian electricity prices change every hour. Energy Pebble is a small device
that glows **green** when power is cheap, **amber** when it is average and
**red** when it is expensive, so running the dishwasher at the right time takes
no app and no reading of price graphs.

This repository is the service behind it: the API the device polls, the website
people configure it on, and the admin console that runs the fleet.

**Live at [energypebble.tdlx.nl](https://energypebble.tdlx.nl)**

## How the colour is decided

Prices come from Elia, the Belgian grid operator, published a day ahead. The
day's range is split into thirds: cheapest third green, middle amber, dearest
third red.

Two rules make it usable rather than merely accurate:

- **Colours are committed for 8 hours.** Once you have seen a colour it will not
  change under you, so you can plan around it.
- **The signal follows the household.** A fixed-price contract, a day/night
  tariff, solar panels or a home battery each change what "cheap" means, so the
  same hour can be green on one pebble and amber on another.

## What is here

| | |
| --- | --- |
| `main.py` | The FastAPI service: prices, colour codes, devices, users, firmware |
| `static/` | The website: landing page, dashboard, insights, simulator, setup, admin |
| `firmware/`, `firmware_signing.py` | Signed over-the-air firmware, see [FIRMWARE_SIGNING.md](FIRMWARE_SIGNING.md) |
| `authelia/` | Authentication config, users and secrets are not in git |
| `deploy/`, `Caddyfile`, `docker-compose.yml` | How it runs in production |
| `tests/` | Pytest suite |

The website ships in **English, Dutch and French**, chosen per account. Admin
pages are deliberately English only.

## The rest of the product

- **[energy-pebble-esphome](https://github.com/thomaskgb/energy-pebble-esphome)**
  is the device: ESPHome firmware, the LED behaviour, and the Wi-Fi setup page.
- **[energy-pebble-homeassistant](https://github.com/thomaskgb/energy-pebble-homeassistant)**
  is the Home Assistant integration, which exposes your pebble's colour as a
  sensor. It lives apart because HACS resolves integrations from a repository
  root.

## Running it

```bash
docker compose up -d
```

For the website and API together on one host, without the edge stack:

```bash
LOCAL_DEV_USER=you python3 -m uvicorn main:app --port 8000
```

`LOCAL_DEV_USER` bypasses authentication and adds the page routes Caddy
normally serves. Local development only; it is never set in production.

## API

The endpoints, the token flow and the Home Assistant integration are documented
at **[energypebble.tdlx.nl/developers](https://energypebble.tdlx.nl/developers)**,
with the generated reference at
**[/docs](https://energypebble.tdlx.nl/docs)**.

## Tests

```bash
python3 -m pytest tests/
```

Some tests expect a running server on `localhost:8000` and fail without one.

## License

MIT. See [LICENSE](LICENSE).
