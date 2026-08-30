# Energy Pebble: Home Assistant integration

The integration moved to its own repository:

**<https://github.com/thomaskgb/energy-pebble-homeassistant>**

HACS resolves `custom_components/<domain>/` from a repository root, so it could
never find the component while it lived here under `homeassistant/`. Keeping a
copy in both places would have meant two versions of the same files drifting
apart, so this directory is now only a pointer.

Install instructions, the entity reference and an example automation live in
that repository's README, and on
<https://energypebble.tdlx.nl/developers>.
