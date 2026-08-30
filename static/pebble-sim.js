/**
 * <pebble-sim> — a faithful, minimal replica of the Energy Pebble device:
 * squircle body, 8 ring segments (next 8 hours) and a center dot (now).
 *
 * Usage:
 *   <script src="/pebble-sim.js"></script>
 *   <pebble-sim src="/api/color-code" controls></pebble-sim>   playground with toggles
 *   <pebble-sim src="/api/color-code"></pebble-sim>            display only
 *   <pebble-sim colors="G,G,Y,R,R,Y,G,G,G"></pebble-sim>       static colors (current + 8)
 *
 * JS API: el.setSettings({signal_source, palette, brightness, night_dim_enabled})
 * mirrors the server-side per-user settings, so the dashboard can preview a
 * user's saved profile. Transforms replicate main.py's apply_signal_source.
 */
(function () {
  const SIZE = 240;
  const CX = SIZE / 2, CY = SIZE / 2;
  const R_OUT = 88, R_IN = 60, GAP_DEG = 6, DOT_R = 34;

  const PALETTES = {
    standard: { G: '#3ddc78', Y: '#f5a623', R: '#f0426b', off: '#e6e1d8' },
    // For deuteranopia/protanopia: blue = go, warm white = neutral, red = wait
    colorblind: { G: '#3b8bff', Y: '#f4ead8', R: '#f0426b', off: '#e6e1d8' },
  };

  const SOLAR_SHIFT = { R: 'Y', Y: 'G', G: 'G' };
  const SOLAR_WINDOW = [10, 16];   // local hours, mirrors SOLAR_WINDOW_HOURS
  const NIGHT_START = 22, NIGHT_END = 7;

  function polar(r, deg) {
    const rad = (deg - 90) * Math.PI / 180; // 0° = top
    return [CX + r * Math.cos(rad), CY + r * Math.sin(rad)];
  }

  // Annular segment path for hour slot i (0..7), clockwise from top
  function segmentPath(i) {
    const a0 = i * 45 + GAP_DEG / 2, a1 = (i + 1) * 45 - GAP_DEG / 2;
    const [x0, y0] = polar(R_OUT, a0), [x1, y1] = polar(R_OUT, a1);
    const [x2, y2] = polar(R_IN, a1), [x3, y3] = polar(R_IN, a0);
    return `M ${x0} ${y0} A ${R_OUT} ${R_OUT} 0 0 1 ${x1} ${y1} ` +
           `L ${x2} ${y2} A ${R_IN} ${R_IN} 0 0 0 ${x3} ${y3} Z`;
  }

  class PebbleSim extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      // entries: [{hour: ISO string|null, color_code: 'G'|'Y'|'R'}], first = now
      this._entries = [];
      // Household parameters (the signal is derived) + display preferences,
      // mirroring the server-side user_settings model.
      this._settings = {
        contract_type: 'dynamic',
        has_solar: false,
        has_battery: false,
        palette: 'standard',
        brightness: 100,
        night_dim_enabled: true,
      };
    }

    // Mirrors main.py derive_signal_source
    _signalSource() {
      if (this._settings.contract_type === 'day_night') return 'day_night';
      if (this._settings.contract_type === 'fixed') return 'fixed';
      if (this._settings.has_solar) return 'solar';
      return 'price';
    }

    connectedCallback() {
      this._render();
      const colors = this.getAttribute('colors');
      if (colors) {
        this._entries = colors.split(',').map(c => ({ hour: null, color_code: c.trim().toUpperCase() }));
        this._paint();
      }
      const src = this.getAttribute('src');
      if (src) this._fetch(src);
    }

    refresh() {
      const src = this.getAttribute('src');
      return src ? this._fetch(src) : Promise.resolve();
    }

    // Drive the pebble from scenario data instead of the API:
    // entries = [{hour: ISO string, color_code: 'G'|'Y'|'R'}], first = "now".
    setEntries(entries) {
      this._entries = entries;
      this._paint();
    }

    // Scenario solar production hours (Set/array of entry hour keys). When
    // set, the solar signal boosts exactly these hours; when null, it falls
    // back to the fixed midday window.
    setSolarBoost(hours) {
      this._solarBoost = hours ? new Set(hours) : null;
      this._paint();
    }


    setSettings(partial) {
      Object.assign(this._settings, partial);
      this._syncControls();
      this._changed();
    }

    // Apply this pebble's household transform to arbitrary entries — lets a
    // host page (e.g. the simulator's price strip) share the exact signal.
    transform(entries) {
      return this._transform(entries);
    }

    _changed() {
      this._paint();
      this.dispatchEvent(new CustomEvent('settings-changed', {
        detail: { ...this._settings }
      }));
    }

    async _fetch(src) {
      try {
        const resp = await fetch(src);
        const data = await resp.json();
        this._entries = (data.hour_color_codes || []).map(e => ({ hour: e.hour, color_code: e.color_code }));
        // A personalized endpoint response carries display settings; adopt them
        // unless this instance is an interactive playground.
        if (data.display && !this.hasAttribute('controls')) {
          this._settings.palette = data.display.palette || this._settings.palette;
          this._settings.brightness = data.display.brightness ?? this._settings.brightness;
        }
        this._paint();
      } catch (e) {
        console.log('[pebble-sim] fetch failed:', e);
      }
    }

    // Mirrors main.py apply_signal_source (times interpreted in the viewer's
    // local timezone, which for our users is Europe/Brussels).
    _transform(entries) {
      const source = this._signalSource();
      if (source === 'price') return entries;
      return entries.map((e, i) => {
        const d = e.hour ? new Date(e.hour) : new Date(Date.now() + i * 3600e3);
        const h = d.getHours(), wd = d.getDay();
        let color = e.color_code;
        const solarHour = this._solarBoost
          ? this._solarBoost.has(e.hour)
          : (h >= SOLAR_WINDOW[0] && h < SOLAR_WINDOW[1]);
        const inBridge = h >= 17 && h < 22;
        const batteryCharged = this._settings.has_battery && this._settings.has_solar
          && this._batteryCharged(d);
        if (source === 'day_night') {
          color = (h >= NIGHT_START || h < NIGHT_END || wd === 0 || wd === 6) ? 'G' : 'Y';
          // Solar panels still beat the day tariff during production hours,
          // and a charged battery carries that into the evening
          if (this._settings.has_solar && solarHour) color = 'G';
          if (batteryCharged && inBridge && color === 'Y') color = 'G';
        } else if (source === 'fixed') {
          // Flat tariff: neutral, except own solar production
          color = (this._settings.has_solar && solarHour) ? 'G' : 'Y';
        } else if (source === 'solar') {
          if (solarHour) color = SOLAR_SHIFT[color];
          // Battery evening bridge: only on days the battery actually charged
          if (batteryCharged && inBridge && color === 'R') color = 'Y';
        }
        return { hour: e.hour, color_code: color };
      });
    }

    _batteryCharged(day) {
      if (!this._solarBoost) return true; // no forecast data: assume charged
      let n = 0;
      for (const key of this._solarBoost) {
        const d = new Date(key);
        if (d.toDateString() === day.toDateString() && d.getHours() < 17) n++;
      }
      return n >= 3;
    }

    _isNightNow() {
      const [sh, sm] = (this._settings.night_dim_start || '22:00').split(':').map(Number);
      const [eh, em] = (this._settings.night_dim_end || '07:00').split(':').map(Number);
      // "Now" is the pebble's current-hour entry (a scrubbed scenario time,
      // or live data's current hour); wall clock only as a fallback.
      const now = (this._entries[0] && this._entries[0].hour)
        ? new Date(this._entries[0].hour) : new Date();
      const mins = now.getHours() * 60 + now.getMinutes();
      const start = sh * 60 + sm, end = eh * 60 + em;
      return start <= end ? (mins >= start && mins < end) : (mins >= start || mins < end);
    }

    _paint() {
      const pal = PALETTES[this._settings.palette] || PALETTES.standard;
      // Night dimming overrides the brightness setting with a fixed 30%
      let alpha = Math.max(0.18, this._settings.brightness / 100);
      if (this._settings.night_dim_enabled && this._isNightNow()) alpha = 0.3;
      const entries = this._transform(this._entries);

      const dot = this.shadowRoot.getElementById('dot');
      const now = entries[0];
      this._lit(dot, now ? pal[now.color_code] : null, pal.off, alpha);

      for (let i = 0; i < 8; i++) {
        const seg = this.shadowRoot.getElementById('seg' + i);
        const entry = entries[i + 1];
        this._lit(seg, entry ? pal[entry.color_code] : null, pal.off, alpha);
        const label = this.shadowRoot.getElementById('lab' + i);
        if (label) {
          label.textContent = (entry && entry.hour)
            ? String(new Date(entry.hour).getHours()).padStart(2, '0')
            : '';
        }
      }
    }

    _lit(el, color, off, alpha) {
      if (!el) return;
      if (color) {
        el.style.fill = color;
        el.style.fillOpacity = alpha;
        el.style.filter = `drop-shadow(0 0 ${6 * alpha}px ${color})`;
      } else {
        el.style.fill = off;
        el.style.fillOpacity = 1;
        el.style.filter = 'none';
      }
    }

    _syncControls() {
      if (!this.hasAttribute('controls')) return;
      const $ = id => this.shadowRoot.getElementById(id);
      $('contract').value = this._settings.contract_type;
      $('solar').checked = this._settings.has_solar;
      $('battery').checked = this._settings.has_battery;
      $('pal').checked = this._settings.palette === 'colorblind';
      $('bri').value = this._settings.brightness;
      $('dim').checked = this._settings.night_dim_enabled;
    }

    _render() {
      const controls = this.hasAttribute('controls');
      let segs = '';
      for (let i = 0; i < 8; i++) {
        segs += `<path id="seg${i}" d="${segmentPath(i)}" />`;
        // Hour label at the middle of each segment (filled in by _paint)
        const [lx, ly] = polar((R_OUT + R_IN) / 2, i * 45 + 22.5);
        segs += `<text id="lab${i}" class="hour-label" x="${lx}" y="${ly}"></text>`;
      }
      this.shadowRoot.innerHTML = `
        <style>
          :host { display: inline-block; }
          .wrap { display: flex; flex-wrap: wrap; gap: 24px; align-items: center; justify-content: center; }
          svg { display: block; }
          .body { fill: #f7f4ef; stroke: #e3ded5; stroke-width: 1.5; }
          .well { fill: #efece6; }
          .hour-label {
            font: 600 10px var(--font-sans, system-ui, sans-serif);
            fill: rgba(40, 40, 35, 0.55);
            text-anchor: middle; dominant-baseline: central;
            pointer-events: none;
          }
          .now-label {
            font: 700 11px var(--font-sans, system-ui, sans-serif);
            fill: rgba(40, 40, 35, 0.6);
            text-anchor: middle; dominant-baseline: central;
            letter-spacing: 0.08em; text-transform: uppercase;
            pointer-events: none;
          }
          path, #dot { transition: fill .5s, fill-opacity .5s; }

          /* The controls panel borrows the host page's design tokens, with
             standalone fallbacks for pages that do not load base.css. */
          .panel {
            font-family: var(--font-sans, system-ui, sans-serif);
            font-size: 13px; line-height: 1.5;
            color: var(--text, #39424e);
            display: grid; gap: 10px; min-width: 220px; text-align: left;
          }
          .panel fieldset {
            border: 1px solid var(--border, #e2e7ee);
            border-radius: var(--radius-md, 8px);
            background: var(--surface, #fff);
            padding: 2px 12px 8px; margin: 0;
          }
          .panel legend {
            font-size: 11px; font-weight: 600;
            text-transform: uppercase; letter-spacing: .06em;
            color: var(--text-muted, #6b7686); padding: 0 4px;
          }
          /* Rows read name first, control at the end */
          .panel label {
            display: flex; align-items: center; justify-content: space-between;
            gap: 16px; cursor: pointer; padding: 7px 0;
          }
          .panel label + label { border-top: 1px solid var(--border, #eef1f5); }
          .panel label small { color: var(--text-muted, #6b7686); font-weight: 400; }
          .panel input[type=range] { width: 110px; accent-color: var(--accent, #16815a); }
          .panel input[type=radio], .panel input[type=checkbox] {
            accent-color: var(--accent, #16815a);
            width: 15px; height: 15px; margin: 0;
          }
          .panel select {
            padding: 4px 8px; font: inherit;
            color: var(--text, #39424e);
            background: var(--surface, #fff);
            border: 1px solid var(--border-strong, #cbd3de);
            border-radius: var(--radius-sm, 6px);
          }
          .panel :focus-visible { outline: 2px solid var(--accent, #16815a); outline-offset: 2px; }
        </style>
        <div class="wrap">
          <svg width="${SIZE}" height="${SIZE}" viewBox="0 0 ${SIZE} ${SIZE}" role="img"
               data-i18n-aria-label="pebble.ariaLabel"
               aria-label="Energy Pebble: center shows the current hour, ring segments the next 8 hours">
            <rect class="body" x="6" y="6" width="${SIZE - 12}" height="${SIZE - 12}" rx="78"/>
            <circle class="well" cx="${CX}" cy="${CY}" r="${R_OUT + 6}"/>
            <g>${segs}</g>
            <circle class="well" cx="${CX}" cy="${CY}" r="${R_IN - 6}"/>
            <circle id="dot" cx="${CX}" cy="${CY}" r="${DOT_R}"/>
            <text class="now-label" x="${CX}" y="${CY}" data-i18n="pebble.now">now</text>
          </svg>
          ${controls ? `
          <div class="panel">
            <fieldset>
              <legend data-i18n="pebble.household">Your household</legend>
              <label><span data-i18n="pebble.contract">Contract</span>
                <select id="contract">
                  <option value="dynamic" selected data-i18n="settings.contract.dynamic">Dynamic prices</option>
                  <option value="day_night" data-i18n="settings.contract.dayNight">Day &amp; night tariff</option>
                  <option value="fixed" data-i18n="settings.contract.fixed">Fixed price</option>
                </select>
              </label>
              <label><span data-i18n="settings.pebble.solar">Solar panels</span><input type="checkbox" id="solar"></label>
              <label><span data-i18n="settings.pebble.battery">Home battery</span><input type="checkbox" id="battery"></label>
            </fieldset>
            <fieldset>
              <legend data-i18n="pebble.display">Display</legend>
              <label><span data-i18n="settings.pebble.colorblind">Colorblind-friendly colors</span><input type="checkbox" id="pal"></label>
              <label><span><span data-i18n="pebble.nightDim">Night dimming</span> <small>30% &middot; 22:00&ndash;07:00</small></span><input type="checkbox" id="dim" checked></label>
              <label><span data-i18n="settings.pebble.brightness">Brightness</span><input type="range" id="bri" min="5" max="100" value="100"></label>
            </fieldset>
          </div>` : ''}
        </div>`;

      if (controls) {
        this.shadowRoot.getElementById('contract').addEventListener('change', e => {
          this._settings.contract_type = e.target.value; this._changed();
        });
        this.shadowRoot.getElementById('solar').addEventListener('change', e => {
          this._settings.has_solar = e.target.checked; this._changed();
        });
        this.shadowRoot.getElementById('battery').addEventListener('change', e => {
          this._settings.has_battery = e.target.checked; this._changed();
        });
        this.shadowRoot.getElementById('pal').addEventListener('change', e => {
          this._settings.palette = e.target.checked ? 'colorblind' : 'standard'; this._changed();
        });
        this.shadowRoot.getElementById('dim').addEventListener('change', e => {
          this._settings.night_dim_enabled = e.target.checked; this._changed();
        });
        this.shadowRoot.getElementById('bri').addEventListener('input', e => {
          this._settings.brightness = Number(e.target.value); this._changed();
        });
      }
      if (window.I18n) {
        window.I18n.register(this.shadowRoot);
        window.I18n.apply(this.shadowRoot);
      }
      this._paint();
    }
  }

  customElements.define('pebble-sim', PebbleSim);
})();
