/**
 * <settings-modal>: the shared User Settings modal (Pebble / Homes / Account).
 *
 * The single source of truth for the logged-in settings UI: index.html and
 * dashboard.html both mount this element instead of carrying their own copy,
 * so the two pages can no longer drift apart. Follows the <pebble-sim>
 * pattern: a self-contained web component with its styles in the shadow DOM
 * (no dependency on page CSS; the host pages style .modal differently).
 *
 * Usage:
 *   <script src="/pebble-sim.js"></script>      (the preview needs it)
 *   <script src="/settings-modal.js"></script>
 *   <settings-modal id="settings-modal"></settings-modal>
 *   document.getElementById('settings-modal').open();
 *
 * Events (bubble out of the shadow root, composed):
 *   settings-saved   {homeId, settings}   pebble settings saved for a home
 *   homes-changed    {homes}              home added / renamed / deleted
 *   profile-updated  {username, usernameChanged}   account profile saved
 *   language-saved   {language}            interface language saved to the account
 *
 * The language switch itself is broadcast by i18n.js as `language-changed` on
 * `document`, so pages that build markup in JavaScript can re-render.
 */
(function () {
  const t = (key, vars) => window.I18n.t(key, vars);

  function authRedirect() {
    window.location.href = 'https://auth.tdlx.nl/?rd=' + encodeURIComponent(window.location.href);
  }

  const esc = v => String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  // The subset of a settings payload that <pebble-sim> understands.
  const simSettings = s => ({
    contract_type: s.contract_type,
    has_solar: s.has_solar,
    has_battery: s.has_battery,
    palette: s.palette,
    brightness: s.brightness,
    night_dim_enabled: s.night_dim_enabled,
    night_dim_start: s.night_dim_start,
    night_dim_end: s.night_dim_end
  });

  const STYLE = `
    /* The modal lives in a shadow root, so it cannot use base.css directly.
       Custom properties do cross the boundary, so the tokens below are the
       host page's, with standalone fallbacks for anything that loads this
       component without the design system. */
    :host {
      font-family: var(--font-sans, system-ui, sans-serif);
      --c-text: var(--text, #171c24);
      --c-secondary: var(--text-secondary, #4d5765);
      --c-muted: var(--text-muted, #6b7686);
      --c-surface: var(--surface, #fff);
      --c-sunken: var(--surface-sunken, #eef1f5);
      --c-border: var(--border, #e2e7ee);
      --c-border-strong: var(--border-strong, #cbd3de);
      --c-accent: var(--accent, #16815a);
      --c-on-accent: var(--on-accent, #fff);
      --c-accent-hover: var(--accent-hover, #106145);
      --c-danger: var(--danger-500, #d4453c);
      --r-sm: var(--radius-sm, 6px);
      --r-md: var(--radius-md, 8px);
    }

    * { box-sizing: border-box; }

    .modal {
      display: none; position: fixed; inset: 0; z-index: 1000;
      align-items: flex-start; justify-content: center;
      padding: 24px 16px; overflow: auto;
      background: rgba(15, 19, 25, 0.5); backdrop-filter: blur(3px);
    }
    .modal.open { display: flex; }

    .panel {
      width: 100%; max-width: 520px;
      background: var(--c-surface);
      color: var(--c-text);
      border: 1px solid var(--c-border);
      border-radius: var(--radius-xl, 16px);
      box-shadow: var(--shadow-lg, 0 12px 32px rgba(16, 24, 40, 0.16));
      line-height: 1.6;
      animation: modalIn 0.18s cubic-bezier(0.4, 0, 0.2, 1);
    }

    @keyframes modalIn {
      from { opacity: 0; transform: translateY(-8px) scale(0.98); }
      to   { opacity: 1; transform: none; }
    }

    @media (prefers-reduced-motion: reduce) { .panel { animation: none; } }

    .head {
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; padding: 20px 24px; border-bottom: 1px solid var(--c-border);
    }
    .title { margin: 0; font-size: 18px; font-weight: 600; letter-spacing: -0.01em; }

    .close {
      display: flex; align-items: center; justify-content: center;
      width: 30px; height: 30px; padding: 0;
      background: none; border: none; border-radius: var(--r-sm);
      font-size: 22px; line-height: 1; color: var(--c-muted);
      cursor: pointer; transition: background 0.12s, color 0.12s;
    }
    .close:hover { background: var(--c-sunken); color: var(--c-text); }

    .body { padding: 20px 24px 24px; }

    /* Tabs */
    .tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--c-border); margin-bottom: 20px; }
    .tab {
      border: none; background: none; padding: 8px 12px; margin-bottom: -1px;
      font: inherit; font-size: 14px; color: var(--c-muted);
      border-bottom: 2px solid transparent; cursor: pointer;
      transition: color 0.12s, border-color 0.12s;
    }
    .tab:hover { color: var(--c-text); }
    .tab.active { color: var(--c-accent); border-bottom-color: var(--c-accent); font-weight: 600; }

    /* Preview */
    .preview { text-align: center; margin-bottom: 18px; }
    .caption { font-size: 13px; color: var(--c-muted); margin-top: 6px; }

    /* Setting rows: name on the left, control on the right */
    .row {
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--c-border);
      cursor: pointer;
    }
    .row:last-of-type { border-bottom: none; }
    .row small { color: var(--c-muted); font-weight: 400; }
    .row input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--c-accent); }
    .row input[type="range"] { width: 160px; accent-color: var(--c-accent); }

    /* A setting that only applies while the row above it is on: indented under
       its parent, and dimmed and inert when the parent is off, so the
       relationship is visible rather than something you find out by clicking. */
    .row--sub {
      justify-content: flex-start;
      gap: 8px;
      padding-left: 16px;
      border-bottom: 1px solid var(--c-border);
      cursor: default;
      transition: opacity 0.12s;
    }
    .row--sub label { color: var(--c-muted); font-size: 13px; }
    .row--sub[aria-disabled="true"] { opacity: 0.45; pointer-events: none; }

    /* Form controls */
    .input, .select, input[type="time"] {
      padding: 7px 10px; font: inherit; font-size: 14px;
      color: var(--c-text); background: var(--c-surface);
      border: 1px solid var(--c-border-strong); border-radius: var(--r-sm);
      transition: border-color 0.12s, box-shadow 0.12s;
    }
    .input--block { width: 100%; }
    .input:focus, .select:focus, input[type="time"]:focus {
      outline: none; border-color: var(--c-accent);
      box-shadow: 0 0 0 3px var(--accent-soft, rgba(28, 138, 94, 0.15));
    }
    .input--mono { font-family: var(--font-mono, monospace); font-size: 12px; }

    .field { margin-bottom: 18px; }
    .field label { display: block; margin-bottom: 6px; font-weight: 500; }
    .hint { display: block; margin-top: 4px; font-size: 12px; color: var(--c-muted); }

    /* Buttons */
    .btn {
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      height: 34px; padding: 0 14px;
      font: inherit; font-size: 14px; font-weight: 500; line-height: 1;
      border: 1px solid transparent; border-radius: var(--r-md);
      cursor: pointer; white-space: nowrap;
      transition: background 0.12s, border-color 0.12s, color 0.12s;
    }
    .btn--primary { background: var(--c-accent); border-color: var(--c-accent); color: var(--c-on-accent); }
    .btn--primary:hover { background: var(--c-accent-hover); border-color: var(--c-accent-hover); }
    .btn--secondary { background: var(--c-surface); border-color: var(--c-border-strong); color: var(--c-text); }
    .btn--secondary:hover { background: var(--c-sunken); }
    .btn--danger { background: none; border-color: var(--c-danger); color: var(--c-danger); }
    .btn--danger:hover { background: var(--danger-soft, rgba(212, 69, 60, 0.1)); }
    .btn--sm { height: 28px; padding: 0 10px; font-size: 13px; }

    .actions { display: flex; gap: 8px; margin-top: 18px; }
    .actions--end { justify-content: flex-end; }

    /* Inline save feedback */
    .status { font-size: 13px; align-self: center; }
    .status--ok { color: var(--c-accent); }
    .status--error { color: var(--c-danger); }

    /* Repeating rows (homes, tokens) */
    .list { font-size: 14px; color: var(--c-secondary); }
    .list-row {
      display: flex; align-items: center; gap: 8px;
      padding: 8px 0; border-bottom: 1px solid var(--c-border);
    }
    .list-row:last-child { border-bottom: none; }

    /* Homes: every row is four columns, and they line up down the whole tab.
       ONE grid does that. Giving each row its own grid was the bug this
       replaces: tracks only align inside a single container, so a saved row
       carrying a device count sized its columns differently from the add row
       below it. The rows are display:contents so their cells become items of
       this grid, and the separators sit on the cells rather than the row. */
    .homes-grid {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1.4fr) auto auto;
      align-items: center;
      gap: 10px 8px;
    }
    #home-rows, .home-row { display: contents; }

    .home-row__meta {
      justify-self: end;
      font-size: 13px;
      color: var(--c-muted);
      white-space: nowrap;
    }
    .home-row__actions { display: flex; gap: 6px; justify-self: end; }

    /* The add row closes the list, so its cells carry the rule above them */
    .home-row--new > * { margin-top: 6px; padding-top: 14px; border-top: 1px solid var(--c-border); }

    @media (max-width: 560px) {
      .homes-grid { grid-template-columns: minmax(0, 1fr) auto; }
      .home-row__meta { grid-column: 2; }
      .home-row__actions { grid-column: 1 / -1; justify-self: start; }
    }
    .list-row small { color: var(--c-muted); white-space: nowrap; }
    .list-empty { color: var(--c-muted); font-style: normal; }

    .section {
      margin-top: 24px; padding-top: 20px;
      border-top: 1px solid var(--c-border);
    }
    .section h3 { margin: 0 0 6px; font-size: 15px; font-weight: 600; }
    .section p { margin: 0 0 12px; font-size: 13px; color: var(--c-muted); }

    .inline-form { display: flex; gap: 8px; margin-bottom: 12px; }
    .inline-form .input { flex: 1; }

    .token-box {
      display: none;
      padding: 12px; margin-bottom: 12px;
      background: var(--accent-soft, #e8f6ef);
      border: 1px solid var(--c-accent); border-radius: var(--r-md);
    }
    .token-box.show { display: block; }
    .token-box > div { font-size: 13px; margin-bottom: 6px; }

    input, select, button, textarea { font-family: inherit; }
    :focus-visible { outline: 2px solid var(--c-accent); outline-offset: 2px; }

    @media (max-width: 560px) {
      .body { padding: 16px; }
      .head { padding: 16px; }
      .inline-form { flex-wrap: wrap; }
    }
  `;

  const TEMPLATE = `
    <div class="modal" id="modal">
      <div class="panel" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div class="head">
          <h2 class="title" id="settings-title" data-i18n="settings.title">User Settings</h2>
          <button class="close" id="close-x" data-i18n-aria-label="common.close" aria-label="Close">&times;</button>
        </div>
        <div class="body">
          <div class="tabs" role="tablist">
            <button type="button" id="tab-pebble" class="tab active" data-tab="pebble" data-i18n="settings.tab.pebble">Pebble</button>
            <button type="button" id="tab-homes" class="tab" data-tab="homes" data-i18n="settings.tab.homes">Homes</button>
            <button type="button" id="tab-account" class="tab" data-tab="account" data-i18n="settings.tab.account">Account</button>
          </div>

          <div id="pane-pebble">
            <div class="preview">
              <pebble-sim id="settings-preview" src="/api/color-code"></pebble-sim>
              <div class="caption" data-i18n="settings.pebble.previewCaption">
                Live preview: this is what your pebble will show once you save
              </div>
            </div>
            <form id="pebble-settings-form">
              <label class="row" id="ps-home-row" style="display: none;"><span data-i18n="settings.pebble.home">Home</span>
                <select id="ps-home" class="select"></select>
              </label>
              <label class="row"><span data-i18n="settings.pebble.contract">Energy contract</span>
                <select id="ps-contract" class="select">
                  <option value="dynamic" data-i18n="settings.contract.dynamic">Dynamic prices</option>
                  <option value="day_night" data-i18n="settings.contract.dayNight">Day &amp; night tariff</option>
                  <option value="fixed" data-i18n="settings.contract.fixed">Fixed price</option>
                </select>
              </label>
              <label class="row"><span data-i18n="settings.pebble.solar">Solar panels</span><input type="checkbox" id="ps-solar"></label>
              <label class="row"><span><span data-i18n="settings.pebble.battery">Home battery</span> <small data-i18n="settings.pebble.batteryHint">bridges the evening peak on sunny days</small></span><input type="checkbox" id="ps-battery"></label>
              <label class="row"><span data-i18n="settings.pebble.colorblind">Colorblind-friendly colors</span><input type="checkbox" id="ps-palette"></label>
              <label class="row"><span data-i18n="settings.pebble.nightDim">Dim at night to 30%</span>
                <input type="checkbox" id="ps-night-dim"></label>
              <!-- The window only means anything while the toggle is on, so it
                   sits under it and follows its state. -->
              <div class="row row--sub" id="ps-dim-window">
                <label for="ps-dim-start" data-i18n="settings.pebble.nightDimFrom">from</label>
                <input type="time" id="ps-dim-start" value="22:00">
                <label for="ps-dim-end" data-i18n="settings.pebble.nightDimTo">to</label>
                <input type="time" id="ps-dim-end" value="07:00">
              </div>
              <label class="row"><span><span data-i18n="settings.pebble.brightness">Brightness</span> <small><span id="ps-bri-val">100</span>%</small></span>
                <input type="range" id="ps-brightness" min="5" max="100" value="100"></label>
              <div class="actions">
                <button type="submit" class="btn btn--primary" data-i18n="settings.pebble.save">Save Settings</button>
                <span id="ps-status" class="status"></span>
              </div>
            </form>
          </div>

          <div id="pane-homes" style="display: none;">
            <p class="hint" style="margin-bottom: 12px;" data-i18n="settings.homes.intro">
              Devices and pebble settings belong to a home. Add one per address;
              pick which home to configure on the Pebble tab.
            </p>
            <div class="homes-grid" id="home-list">
              <div id="home-rows"></div>
              <div class="home-row home-row--new">
                <input type="text" id="home-name" class="input" placeholder="Name (e.g. Beach house)" data-i18n-placeholder="settings.homes.namePlaceholder">
                <input type="text" id="home-address" class="input" placeholder="Address (optional)" data-i18n-placeholder="settings.homes.addressPlaceholder">
                <span class="home-row__meta"></span>
                <div class="home-row__actions">
                  <button type="button" class="btn btn--primary" id="add-home" data-i18n="settings.homes.add">Add home</button>
                </div>
              </div>
            </div>
          </div>

          <div id="pane-account" style="display: none;">
            <div class="field" style="padding-bottom: 18px; border-bottom: 1px solid var(--c-border);">
              <label for="account-language" data-i18n="settings.account.language">Language:</label>
              <select id="account-language" class="select input--block">
                <option value="en">English</option>
                <option value="nl">Nederlands</option>
                <option value="fr">Français</option>
              </select>
              <small class="hint" data-i18n="settings.account.languageHint">Applies to this website on every device you sign in on. Your pebble shows colors, so it is unaffected.</small>
              <span id="lang-status" class="status"></span>
            </div>

            <form id="account-form">
              <div class="field">
                <label for="newUsername" data-i18n="settings.account.username">Username:</label>
                <input type="text" id="newUsername" name="username" class="input input--block" placeholder="Enter new username" data-i18n-placeholder="settings.account.usernamePlaceholder">
                <small class="hint" data-i18n="settings.account.usernameHint">Username must be unique and contain only letters, numbers, and underscores.</small>
              </div>
              <div class="field">
                <label for="currentPassword" data-i18n="settings.account.currentPassword">Current Password:</label>
                <input type="password" id="currentPassword" name="currentPassword" class="input input--block" placeholder="Enter current password" data-i18n-placeholder="settings.account.currentPasswordPlaceholder">
              </div>
              <div class="field">
                <label for="newPassword" data-i18n="settings.account.newPassword">New Password:</label>
                <input type="password" id="newPassword" name="newPassword" class="input input--block" placeholder="Enter new password" data-i18n-placeholder="settings.account.newPasswordPlaceholder">
                <small class="hint" data-i18n="settings.account.newPasswordHint">Leave blank to keep your current password.</small>
              </div>
              <div class="field">
                <label for="confirmPassword" data-i18n="settings.account.confirmPassword">Confirm New Password:</label>
                <input type="password" id="confirmPassword" name="confirmPassword" class="input input--block" placeholder="Confirm new password" data-i18n-placeholder="settings.account.confirmPasswordPlaceholder">
              </div>
              <div class="actions actions--end">
                <button type="button" class="btn btn--secondary" id="cancel-account" data-i18n="common.cancel">Cancel</button>
                <button type="submit" class="btn btn--primary" data-i18n="common.saveChanges">Save Changes</button>
              </div>
            </form>

            <div class="section">
              <h3 data-i18n="settings.tokens.title">API tokens</h3>
              <p data-i18n="settings.tokens.intro">
                For integrations like Home Assistant. A token acts as you (never as admin) and is shown only once.
              </p>
              <div class="inline-form">
                <input type="text" id="token-name" class="input" placeholder="Token name (e.g. Home Assistant)" data-i18n-placeholder="settings.tokens.namePlaceholder">
                <button type="button" class="btn btn--primary" id="create-token" data-i18n="settings.tokens.create">Create token</button>
              </div>
              <div id="new-token-box" class="token-box">
                <div data-i18n="settings.tokens.copyOnce">Copy this token now; it won't be shown again:</div>
                <input type="text" id="new-token-value" class="input input--block input--mono" readonly>
              </div>
              <div id="token-list" class="list"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `;

  class SettingsModal extends HTMLElement {
    constructor() {
      super();
      this.attachShadow({ mode: 'open' });
      this.shadowRoot.innerHTML = `<style>${STYLE}</style>${TEMPLATE}`;
      this._homes = [];
      this._homeId = null;
      this._wire();
      // Shadow DOM is invisible to document.querySelectorAll, so the runtime
      // needs the root handed to it explicitly: once here, then again on every
      // language change.
      window.I18n.register(this.shadowRoot);
      document.addEventListener('language-changed', () => this._retranslate());
    }

    $(sel) { return this.shadowRoot.querySelector(sel); }

    /** The night window is only editable while night dimming is on. */
    _syncDimWindow() {
      var on = this.$('#ps-night-dim').checked;
      var win = this.$('#ps-dim-window');
      if (win) win.setAttribute('aria-disabled', on ? 'false' : 'true');
    }

    _emit(name, detail) {
      this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
    }

    // --- public API -----------------------------------------------------------

    open() {
      // Remember who opened us, so focus can go back there on close.
      this._opener = document.activeElement;
      this._loadHomes().then(() => this._loadSettings());
      this._loadAccount();
      this._loadLanguage();
      this._loadTokens();
      this._switchTab('pebble');
      this.$('#modal').classList.add('open');
      // Move focus inside: a dialog the keyboard cannot reach is a dialog that
      // traps the reader behind it.
      const first = this._focusable()[0];
      (first || this.$('.panel')).focus();
    }

    close() {
      this.$('#modal').classList.remove('open');
      this.$('#account-form').reset();
      if (this._opener && typeof this._opener.focus === 'function') this._opener.focus();
      this._opener = null;
    }

    get isOpen() {
      return this.$('#modal').classList.contains('open');
    }

    // --- keyboard -------------------------------------------------------------

    /** Every tabbable control currently on screen, in document order. */
    _focusable() {
      const sel = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
      return [...this.shadowRoot.querySelectorAll(sel)].filter(el =>
        !el.disabled && el.offsetParent !== null);
    }

    /**
     * Escape closes; Tab cycles within the dialog. The panel is the only thing
     * on screen while it is open, so letting Tab escape into the page behind it
     * would strand keyboard and screen-reader users.
     */
    _onKeydown(e) {
      if (!this.isOpen) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        this.close();
        return;
      }

      if (e.key !== 'Tab') return;

      const items = this._focusable();
      if (!items.length) return;
      const first = items[0];
      const last = items[items.length - 1];
      // composedPath() sees through the shadow boundary; activeElement on the
      // document only ever reports the host element.
      const active = this.shadowRoot.activeElement;

      if (e.shiftKey && (active === first || !active)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && active === last) {
        e.preventDefault();
        first.focus();
      }
    }

    // --- wiring ---------------------------------------------------------------

    _wire() {
      // The panel takes focus itself when there is nothing tabbable in it yet.
      this.$('.panel').setAttribute('tabindex', '-1');
      // Keydown is bound on the host: shadow DOM events retarget, but the
      // listener still fires for anything inside the panel.
      this.addEventListener('keydown', e => this._onKeydown(e));
      // A click on the backdrop (never on the panel) dismisses too.
      this.$('#modal').addEventListener('mousedown', e => {
        if (e.target === this.$('#modal')) this.close();
      });
      this.$('#close-x').addEventListener('click', () => this.close());
      this.$('#cancel-account').addEventListener('click', () => this.close());
      this.shadowRoot.querySelectorAll('.tab').forEach(btn =>
        btn.addEventListener('click', () => this._switchTab(btn.dataset.tab)));

      // Pebble tab
      this.$('#pebble-settings-form').addEventListener('submit', e => this._saveSettings(e));
      this.$('#ps-home').addEventListener('change', e => {
        this._homeId = Number(e.target.value);
        this._loadSettings();
      });
      ['#ps-contract', '#ps-solar', '#ps-battery', '#ps-palette', '#ps-brightness',
       '#ps-night-dim', '#ps-dim-start', '#ps-dim-end'].forEach(sel => {
        this.$(sel).addEventListener('input', () => {
          this._syncDimWindow();
          this.$('#ps-bri-val').textContent = this.$('#ps-brightness').value;
          this._applyToPreview(this._formToSettings());
        });
      });

      // Homes tab (rows are rendered dynamically, so delegate)
      this.$('#add-home').addEventListener('click', () => this._createHome());
      this.$('#home-list').addEventListener('click', e => {
        const btn = e.target.closest('button[data-action]');
        if (!btn) return;
        const id = Number(btn.dataset.id);
        if (btn.dataset.action === 'save-home') this._saveHome(id);
        else if (btn.dataset.action === 'delete-home') this._deleteHome(id);
      });

      // Account tab
      this.$('#account-language').addEventListener('change', e => this._saveLanguage(e.target.value));
      this.$('#account-form').addEventListener('submit', e => this._saveAccount(e));
      this.$('#create-token').addEventListener('click', () => this._createToken());
      this.$('#new-token-value').addEventListener('click', e => e.target.select());
      this.$('#token-list').addEventListener('click', e => {
        const btn = e.target.closest('button[data-action="revoke-token"]');
        if (btn) this._revokeToken(Number(btn.dataset.id));
      });
    }

    /**
     * Re-render the parts built in JavaScript. The static markup is handled by
     * the runtime through the registered shadow root; these two lists are
     * string-built, so they have to be rebuilt by hand.
     */
    _retranslate() {
      this.$('#account-language').value = window.I18n.language;
      this._loadHomes();
      this._loadTokens();
    }

    _switchTab(tab) {
      for (const name of ['pebble', 'homes', 'account']) {
        this.$('#tab-' + name).classList.toggle('active', tab === name);
        this.$('#pane-' + name).style.display = tab === name ? 'block' : 'none';
      }
    }

    // --- homes ----------------------------------------------------------------

    async _loadHomes() {
      try {
        const resp = await fetch('/api/user/homes');
        if (resp.status === 401) { authRedirect(); return; }
        if (!resp.ok) return;
        this._homes = (await resp.json()).homes;
        if (this._homeId === null && this._homes.length) this._homeId = this._homes[0].id;

        const row = this.$('#ps-home-row');
        const select = this.$('#ps-home');
        row.style.display = this._homes.length > 1 ? 'flex' : 'none';
        select.innerHTML = this._homes.map(h =>
          `<option value="${h.id}" ${h.id === this._homeId ? 'selected' : ''}>${esc(h.name)}</option>`).join('');

        this.$('#home-rows').innerHTML = this._homes.map(h =>
          `<div class="home-row">
              <input type="text" id="home-name-${h.id}" class="input" value="${esc(h.name)}">
              <input type="text" id="home-address-${h.id}" class="input" value="${esc(h.address)}"
                     placeholder="${esc(t('settings.homes.address'))}">
              <small class="home-row__meta">${esc(window.I18n.plural('settings.homes.deviceCount', h.device_count))}</small>
              <div class="home-row__actions">
                <button type="button" class="btn btn--primary" data-action="save-home" data-id="${h.id}">${esc(t('common.save'))}</button>
                ${this._homes.length > 1 && !h.device_count ? `<button type="button" class="btn btn--danger" data-action="delete-home" data-id="${h.id}">${esc(t('common.delete'))}</button>` : ''}
              </div>
          </div>`).join('');
      } catch (e) {
        console.error('Error loading homes:', e);
      }
    }

    async _createHome() {
      const name = this.$('#home-name').value.trim();
      if (!name) { alert(t('settings.homes.nameRequired')); return; }
      const address = this.$('#home-address').value.trim() || null;
      const resp = await fetch('/api/user/homes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, address })
      });
      if (resp.ok) {
        this.$('#home-name').value = '';
        this.$('#home-address').value = '';
        await this._loadHomes();
        this._emit('homes-changed', { homes: this._homes });
      } else {
        alert(t('settings.homes.addFailed'));
      }
    }

    async _saveHome(id) {
      const name = this.$('#home-name-' + id).value.trim();
      if (!name) { alert(t('settings.homes.nameEmpty')); return; }
      const address = this.$('#home-address-' + id).value.trim();
      const resp = await fetch('/api/user/homes/' + id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, address })
      });
      if (resp.ok) {
        await this._loadHomes();
        this._emit('homes-changed', { homes: this._homes });
      } else {
        alert(t('settings.homes.saveFailed'));
      }
    }

    async _deleteHome(id) {
      if (!confirm(t('settings.homes.deleteConfirm'))) return;
      const resp = await fetch('/api/user/homes/' + id, { method: 'DELETE' });
      if (!resp.ok) alert((await resp.json()).detail || t('settings.homes.deleteFailed'));
      if (this._homeId === id) this._homeId = null;
      await this._loadHomes();
      this._loadSettings();
      this._emit('homes-changed', { homes: this._homes });
    }

    // --- pebble settings ------------------------------------------------------

    _formToSettings() {
      return {
        contract_type: this.$('#ps-contract').value,
        has_solar: this.$('#ps-solar').checked,
        has_battery: this.$('#ps-battery').checked,
        palette: this.$('#ps-palette').checked ? 'colorblind' : 'standard',
        brightness: Number(this.$('#ps-brightness').value),
        night_dim_enabled: this.$('#ps-night-dim').checked,
        night_dim_start: this.$('#ps-dim-start').value || '22:00',
        night_dim_end: this.$('#ps-dim-end').value || '07:00'
      };
    }

    _settingsToForm(settings) {
      this.$('#ps-contract').value = settings.contract_type;
      this.$('#ps-solar').checked = settings.has_solar;
      this.$('#ps-battery').checked = settings.has_battery;
      this.$('#ps-palette').checked = settings.palette === 'colorblind';
      this.$('#ps-brightness').value = settings.brightness;
      this.$('#ps-bri-val').textContent = settings.brightness;
      this.$('#ps-night-dim').checked = settings.night_dim_enabled;
      this.$('#ps-dim-start').value = settings.night_dim_start;
      this.$('#ps-dim-end').value = settings.night_dim_end;
      this._syncDimWindow();
    }

    _applyToPreview(settings) {
      const sim = this.$('#settings-preview');
      if (sim && sim.setSettings) sim.setSettings(simSettings(settings));
    }

    async _loadSettings() {
      try {
        const response = await fetch('/api/user/settings' + (this._homeId ? '?home_id=' + this._homeId : ''));
        if (response.status === 401) { authRedirect(); return; }
        if (!response.ok) return;
        const data = await response.json();
        this._homeId = data.home_id;
        this._settingsToForm(data.settings);
        this._applyToPreview(data.settings);
      } catch (error) {
        console.error('Error loading pebble settings:', error);
      }
    }

    async _saveSettings(e) {
      e.preventDefault();
      const status = this.$('#ps-status');
      try {
        const response = await fetch('/api/user/settings' + (this._homeId ? '?home_id=' + this._homeId : ''), {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this._formToSettings())
        });
        if (response.ok) {
          status.className = 'status status--ok';
          status.textContent = t('settings.pebble.saved');
          const result = await response.json();
          this._homeId = result.home_id;
          this._emit('settings-saved', { homeId: result.home_id, settings: result.settings });
        } else {
          const error = await response.json();
          status.className = 'status status--error';
          status.textContent = t('settings.pebble.saveError', { error: error.detail || response.status });
        }
      } catch (error) {
        status.className = 'status status--error';
        status.textContent = t('settings.pebble.saveErrorGeneric');
      }
      setTimeout(() => { status.textContent = ''; }, 5000);
    }

    // --- account & tokens -----------------------------------------------------

    async _loadAccount() {
      try {
        const response = await fetch('/api/verify', { credentials: 'include' });
        if (response.status === 401) { authRedirect(); return; }
        if (!response.ok) return;
        const data = await response.json();
        if (data.user) this.$('#newUsername').value = data.user.split('@')[0];
      } catch (error) {
        console.error('Failed to load user data:', error);
      }
    }

    async _saveAccount(e) {
      e.preventDefault();
      const formData = new FormData(e.target);
      const newUsername = formData.get('username');
      const currentPassword = formData.get('currentPassword');
      const newPassword = formData.get('newPassword');
      const confirmPassword = formData.get('confirmPassword');

      if (!newUsername.trim()) { alert(t('settings.account.usernameRequired')); return; }
      if (newPassword && newPassword !== confirmPassword) { alert(t('settings.account.passwordMismatch')); return; }
      if (newPassword && newPassword.length < 6) { alert(t('settings.account.passwordTooShort')); return; }

      try {
        const updateData = { username: newUsername.trim(), currentPassword };
        if (newPassword) updateData.newPassword = newPassword;

        const response = await fetch('/api/user/profile', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updateData)
        });
        if (response.status === 401) { authRedirect(); return; }
        if (response.ok) {
          const result = await response.json();
          alert(t('settings.account.updated'));
          this.close();
          this._emit('profile-updated', {
            username: newUsername.trim(),
            usernameChanged: !!result.usernameChanged
          });
          if (result.usernameChanged) {
            alert(t('settings.account.usernameChanged'));
          }
        } else {
          const error = await response.json();
          alert(t('settings.account.updateFailed', { error: error.detail }));
        }
      } catch (error) {
        console.error('Error updating settings:', error);
        alert(t('settings.account.updateFailedGeneric'));
      }
    }

    // --- language -------------------------------------------------------------

    /**
     * Show the language stored on the account. The runtime has usually already
     * switched to it on page load; this only makes the select agree with it.
     */
    async _loadLanguage() {
      const select = this.$('#account-language');
      select.value = window.I18n.language;
      try {
        const resp = await fetch('/api/user/preferences');
        if (!resp.ok) return;
        const data = await resp.json();
        const language = data.preferences && data.preferences.language;
        if (language) {
          select.value = language;
          window.I18n.setLanguage(language);
        }
      } catch (e) {
        console.error('Error loading account preferences:', e);
      }
    }

    /** Switch the interface immediately, then persist the choice to the account. */
    async _saveLanguage(language) {
      const status = this.$('#lang-status');
      try {
        await window.I18n.setLanguage(language, { save: true });
        status.className = 'status status--ok';
        status.textContent = t('settings.account.languageSaved');
        this._emit('language-saved', { language });
      } catch (e) {
        status.className = 'status status--error';
        status.textContent = t('settings.account.languageSaveFailed');
      }
      setTimeout(() => { status.textContent = ''; }, 5000);
    }

    async _loadTokens() {
      try {
        const resp = await fetch('/api/user/tokens');
        if (!resp.ok) return;
        const data = await resp.json();
        const list = this.$('#token-list');
        if (!data.tokens.length) {
          list.innerHTML = `<span class="list-empty">${esc(t('settings.tokens.empty'))}</span>`;
          return;
        }
        list.innerHTML = data.tokens.map(token =>
          `<div class="list-row" style="justify-content: space-between;">
              <span>${esc(token.token_name)}
                  <small>· ${esc(t('settings.tokens.created', { date: (token.created_at || '').slice(0, 10) }))}${token.last_used_at ? ' · ' + esc(t('settings.tokens.lastUsed', { date: token.last_used_at.slice(0, 10) })) : ''}</small>
              </span>
              <button type="button" class="btn btn--danger btn--sm" data-action="revoke-token" data-id="${token.id}">${esc(t('settings.tokens.revoke'))}</button>
          </div>`).join('');
      } catch (e) {
        console.error('Error loading tokens:', e);
      }
    }

    async _createToken() {
      const name = this.$('#token-name').value.trim() || 'Home Assistant';
      try {
        const resp = await fetch('/api/user/tokens', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token_name: name })
        });
        if (!resp.ok) { alert(t('settings.tokens.createFailed')); return; }
        const data = await resp.json();
        this.$('#new-token-box').classList.add('show');
        this.$('#new-token-value').value = data.token;
        this.$('#token-name').value = '';
        this._loadTokens();
      } catch (e) {
        alert(t('settings.tokens.createFailed'));
      }
    }

    async _revokeToken(id) {
      if (!confirm(t('settings.tokens.revokeConfirm'))) return;
      await fetch('/api/user/tokens/' + id, { method: 'DELETE' });
      this._loadTokens();
    }
  }

  customElements.define('settings-modal', SettingsModal);
})();
