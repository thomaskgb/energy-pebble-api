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
    :host { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
    .modal {
      display: none; position: fixed; z-index: 1000; left: 0; top: 0;
      width: 100%; height: 100%; overflow: auto;
      background-color: rgba(0, 0, 0, 0.5); backdrop-filter: blur(5px);
    }
    .modal.open { display: block; }
    .modal-content {
      background: white; margin: 5% auto; padding: 30px; border-radius: 15px;
      box-shadow: 0 10px 40px rgba(0, 0, 0, 0.2); width: 90%; max-width: 500px;
      position: relative; animation: modalSlideIn 0.3s ease-out;
      color: #2c3e50; line-height: 1.6;
    }
    @keyframes modalSlideIn {
      from { opacity: 0; transform: translateY(-50px) scale(0.9); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .modal-header {
      display: flex; justify-content: space-between; align-items: center;
      margin-bottom: 20px; border-bottom: 2px solid #f1f3f4; padding-bottom: 15px;
    }
    .modal-title { color: #2c3e50; font-size: 1.4em; font-weight: 600; margin: 0; }
    .close-btn {
      background: none; border: none; font-size: 28px; color: #6c757d;
      cursor: pointer; padding: 0; line-height: 1; transition: color 0.2s ease;
    }
    .close-btn:hover { color: #e74c3c; }
    .settings-tab {
      border: none; background: none; padding: 8px 16px; cursor: pointer;
      font-size: 14px; color: #6c757d; border-bottom: 2px solid transparent;
      font-family: inherit;
    }
    .settings-tab.active { color: #27ae60; border-bottom-color: #27ae60; font-weight: 600; }
    .settings-row {
      display: flex; align-items: center; justify-content: space-between;
      gap: 16px; padding: 9px 0; border-bottom: 1px solid #f1f3f4; cursor: pointer;
    }
    .settings-row small { color: #adb5bd; font-weight: 400; }
    .settings-row input[type="checkbox"] { width: 17px; height: 17px; accent-color: #27ae60; }
    .btn-action {
      display: inline-block; padding: 10px 20px; background: #27ae60; color: white;
      text-decoration: none; border: none; border-radius: 8px; font-weight: 500;
      transition: all 0.2s ease; font-size: 0.9em; cursor: pointer; font-family: inherit;
    }
    .btn-action:hover { background: #229954; transform: translateY(-1px); }
    input, select, button { font-family: inherit; }
    @media (max-width: 768px) {
      .modal-content { margin: 10% auto; width: 95%; padding: 20px; }
    }
  `;

  const TEMPLATE = `
    <div class="modal" id="modal">
      <div class="modal-content">
        <div class="modal-header">
          <h2 class="modal-title" data-i18n="settings.title">User Settings</h2>
          <button class="close-btn" id="close-x">&times;</button>
        </div>
        <div class="modal-body">
          <div class="settings-tabs" style="display: flex; gap: 6px; border-bottom: 1px solid #e9ecef; margin-bottom: 20px;">
            <button type="button" id="tab-pebble" class="settings-tab active" data-tab="pebble" data-i18n="settings.tab.pebble">Pebble</button>
            <button type="button" id="tab-homes" class="settings-tab" data-tab="homes" data-i18n="settings.tab.homes">Homes</button>
            <button type="button" id="tab-account" class="settings-tab" data-tab="account" data-i18n="settings.tab.account">Account</button>
          </div>
          <div id="pane-pebble">
            <div style="text-align: center; margin-bottom: 18px;">
              <pebble-sim id="settings-preview" src="/api/color-code"></pebble-sim>
              <div style="font-size: 0.85em; color: #6c757d; margin-top: 4px;" data-i18n="settings.pebble.previewCaption">
                Live preview: this is what your pebble will show once you save
              </div>
            </div>
            <form id="pebble-settings-form" style="display: grid; gap: 2px; text-align: left;">
              <label class="settings-row" id="ps-home-row" style="display: none;"><span data-i18n="settings.pebble.home">Home</span>
                <select id="ps-home" style="padding: 8px; border: 1px solid #dee2e6; border-radius: 6px;"></select>
              </label>
              <label class="settings-row"><span data-i18n="settings.pebble.contract">Energy contract</span>
                <select id="ps-contract" style="padding: 8px; border: 1px solid #dee2e6; border-radius: 6px;">
                  <option value="dynamic" data-i18n="settings.contract.dynamic">Dynamic prices</option>
                  <option value="day_night" data-i18n="settings.contract.dayNight">Day &amp; night tariff</option>
                  <option value="fixed" data-i18n="settings.contract.fixed">Fixed price</option>
                </select>
              </label>
              <label class="settings-row"><span data-i18n="settings.pebble.solar">Solar panels</span><input type="checkbox" id="ps-solar"></label>
              <label class="settings-row"><span><span data-i18n="settings.pebble.battery">Home battery</span> <small data-i18n="settings.pebble.batteryHint">bridges the evening peak on sunny days</small></span><input type="checkbox" id="ps-battery"></label>
              <label class="settings-row"><span data-i18n="settings.pebble.colorblind">Colorblind-friendly colors</span><input type="checkbox" id="ps-palette"></label>
              <label class="settings-row"><span><span data-i18n="settings.pebble.nightDim">Dim at night to 30%</span>
                (<input type="time" id="ps-dim-start" value="22:00" style="border: 1px solid #dee2e6; border-radius: 4px;"> &ndash;
                <input type="time" id="ps-dim-end" value="07:00" style="border: 1px solid #dee2e6; border-radius: 4px;">)</span>
                <input type="checkbox" id="ps-night-dim"></label>
              <label class="settings-row"><span><span data-i18n="settings.pebble.brightness">Brightness</span> <small><span id="ps-bri-val">100</span>%</small></span>
                <input type="range" id="ps-brightness" min="5" max="100" value="100" style="width: 160px;"></label>
              <div style="margin-top: 14px;">
                <button type="submit" class="btn-action" data-i18n="settings.pebble.save">Save Settings</button>
                <span id="ps-status" style="margin-left: 10px; font-size: 0.85em; color: #27ae60;"></span>
              </div>
            </form>
          </div>
          <div id="pane-homes" style="display: none;">
            <p style="font-size: 0.85em; color: #6c757d; margin-bottom: 12px;" data-i18n="settings.homes.intro">
              Devices and pebble settings belong to a home. Add one per address;
              pick which home to configure on the Pebble tab.
            </p>
            <div id="home-list" style="font-size: 0.9em; color: #495057; margin-bottom: 14px;"></div>
            <div style="display: flex; gap: 8px;">
              <input type="text" id="home-name" placeholder="Name (e.g. Beach house)" data-i18n-placeholder="settings.homes.namePlaceholder"
                     style="flex: 1; padding: 8px; border: 1px solid #dee2e6; border-radius: 6px;">
              <input type="text" id="home-address" placeholder="Address (optional)" data-i18n-placeholder="settings.homes.addressPlaceholder"
                     style="flex: 2; padding: 8px; border: 1px solid #dee2e6; border-radius: 6px;">
              <button type="button" class="btn-action" id="add-home" data-i18n="settings.homes.add">Add home</button>
            </div>
          </div>
          <div id="pane-account" style="display: none;">
            <div style="margin-bottom: 22px; padding-bottom: 18px; border-bottom: 1px solid #e9ecef;">
              <label for="account-language" style="display: block; margin-bottom: 5px; font-weight: 600; color: #2c3e50;" data-i18n="settings.account.language">Language:</label>
              <select id="account-language" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box;">
                <option value="en">English</option>
                <option value="nl">Nederlands</option>
                <option value="fr">Français</option>
              </select>
              <small style="color: #6c757d; font-size: 12px;" data-i18n="settings.account.languageHint">Applies to this website on every device you sign in on. Your pebble shows colors, so it is unaffected.</small>
              <span id="lang-status" style="margin-left: 10px; font-size: 0.85em; color: #27ae60;"></span>
            </div>
            <form id="account-form">
              <div style="margin-bottom: 20px;">
                <label for="newUsername" style="display: block; margin-bottom: 5px; font-weight: 600; color: #2c3e50;" data-i18n="settings.account.username">Username:</label>
                <input type="text" id="newUsername" name="username" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box;" placeholder="Enter new username" data-i18n-placeholder="settings.account.usernamePlaceholder">
                <small style="color: #6c757d; font-size: 12px;" data-i18n="settings.account.usernameHint">Username must be unique and contain only letters, numbers, and underscores.</small>
              </div>
              <div style="margin-bottom: 20px;">
                <label for="currentPassword" style="display: block; margin-bottom: 5px; font-weight: 600; color: #2c3e50;" data-i18n="settings.account.currentPassword">Current Password:</label>
                <input type="password" id="currentPassword" name="currentPassword" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box;" placeholder="Enter current password" data-i18n-placeholder="settings.account.currentPasswordPlaceholder">
              </div>
              <div style="margin-bottom: 20px;">
                <label for="newPassword" style="display: block; margin-bottom: 5px; font-weight: 600; color: #2c3e50;" data-i18n="settings.account.newPassword">New Password:</label>
                <input type="password" id="newPassword" name="newPassword" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box;" placeholder="Enter new password" data-i18n-placeholder="settings.account.newPasswordPlaceholder">
                <small style="color: #6c757d; font-size: 12px;" data-i18n="settings.account.newPasswordHint">Leave blank to keep current password.</small>
              </div>
              <div style="margin-bottom: 20px;">
                <label for="confirmPassword" style="display: block; margin-bottom: 5px; font-weight: 600; color: #2c3e50;" data-i18n="settings.account.confirmPassword">Confirm New Password:</label>
                <input type="password" id="confirmPassword" name="confirmPassword" style="width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; box-sizing: border-box;" placeholder="Confirm new password" data-i18n-placeholder="settings.account.confirmPasswordPlaceholder">
              </div>
              <div style="text-align: right; margin-top: 25px;">
                <button type="button" id="cancel-account" style="background: #6c757d; color: white; border: none; padding: 10px 20px; border-radius: 6px; margin-right: 10px; cursor: pointer;" data-i18n="common.cancel">Cancel</button>
                <button type="submit" style="background: #27ae60; color: white; border: none; padding: 10px 20px; border-radius: 6px; cursor: pointer;" data-i18n="common.saveChanges">Save Changes</button>
              </div>
            </form>
            <div style="border-top: 1px solid #e9ecef; margin-top: 25px; padding-top: 18px;">
              <h3 style="font-size: 1em; color: #2c3e50; margin-bottom: 6px;" data-i18n="settings.tokens.title">API tokens</h3>
              <p style="font-size: 0.85em; color: #6c757d; margin-bottom: 12px;" data-i18n="settings.tokens.intro">
                For integrations like Home Assistant. A token acts as you (never as admin) and is shown only once.
              </p>
              <div style="display: flex; gap: 8px; margin-bottom: 10px;">
                <input type="text" id="token-name" placeholder="Token name (e.g. Home Assistant)" data-i18n-placeholder="settings.tokens.namePlaceholder"
                       style="flex: 1; padding: 8px; border: 1px solid #dee2e6; border-radius: 6px;">
                <button type="button" class="btn-action" id="create-token" data-i18n="settings.tokens.create">Create token</button>
              </div>
              <div id="new-token-box" style="display: none; background: #eafaf1; border: 1px solid #27ae60; border-radius: 6px; padding: 10px; margin-bottom: 10px;">
                <div style="font-size: 0.85em; color: #2c3e50; margin-bottom: 6px;" data-i18n="settings.tokens.copyOnce">Copy this token now; it won't be shown again:</div>
                <input type="text" id="new-token-value" readonly
                       style="width: 100%; padding: 8px; border: 1px solid #dee2e6; border-radius: 6px; font-family: monospace; font-size: 12px; box-sizing: border-box;">
              </div>
              <div id="token-list" style="font-size: 0.9em; color: #495057;"></div>
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

    _emit(name, detail) {
      this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }));
    }

    // --- public API -----------------------------------------------------------

    open() {
      this._loadHomes().then(() => this._loadSettings());
      this._loadAccount();
      this._loadLanguage();
      this._loadTokens();
      this._switchTab('pebble');
      this.$('#modal').classList.add('open');
    }

    close() {
      this.$('#modal').classList.remove('open');
      this.$('#account-form').reset();
    }

    // --- wiring ---------------------------------------------------------------

    _wire() {
      this.$('#close-x').addEventListener('click', () => this.close());
      this.$('#cancel-account').addEventListener('click', () => this.close());
      this.shadowRoot.querySelectorAll('.settings-tab').forEach(btn =>
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

        this.$('#home-list').innerHTML = this._homes.map(h =>
          `<div style="display:flex; gap:8px; align-items:center; padding:6px 0; border-bottom:1px solid #f1f3f4;">
              <input type="text" id="home-name-${h.id}" value="${esc(h.name)}"
                     style="flex:1; padding:6px 8px; border:1px solid #dee2e6; border-radius:6px;">
              <input type="text" id="home-address-${h.id}" value="${esc(h.address)}" placeholder="${esc(t('settings.homes.address'))}"
                     style="flex:2; padding:6px 8px; border:1px solid #dee2e6; border-radius:6px;">
              <small style="color:#adb5bd; white-space:nowrap;">${esc(window.I18n.plural('settings.homes.deviceCount', h.device_count))}</small>
              <button type="button" data-action="save-home" data-id="${h.id}"
                      style="background:#27ae60; color:white; border:none; border-radius:6px; padding:5px 12px; cursor:pointer;">${esc(t('common.save'))}</button>
              ${this._homes.length > 1 && !h.device_count ? `<button type="button" data-action="delete-home" data-id="${h.id}"
                      style="background:none; border:1px solid #e74c3c; color:#e74c3c; border-radius:6px; padding:4px 10px; cursor:pointer;">${esc(t('common.delete'))}</button>` : ''}
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
          status.style.color = '#27ae60';
          status.textContent = t('settings.pebble.saved');
          const result = await response.json();
          this._homeId = result.home_id;
          this._emit('settings-saved', { homeId: result.home_id, settings: result.settings });
        } else {
          const error = await response.json();
          status.style.color = '#e74c3c';
          status.textContent = t('settings.pebble.saveError', { error: error.detail || response.status });
        }
      } catch (error) {
        status.style.color = '#e74c3c';
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
        status.style.color = '#27ae60';
        status.textContent = t('settings.account.languageSaved');
        this._emit('language-saved', { language });
      } catch (e) {
        status.style.color = '#e74c3c';
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
          list.innerHTML = `<em style="color:#adb5bd;">${esc(t('settings.tokens.empty'))}</em>`;
          return;
        }
        list.innerHTML = data.tokens.map(token =>
          `<div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #f1f3f4;">
              <span>${esc(token.token_name)}
                  <small style="color:#adb5bd;">· ${esc(t('settings.tokens.created', { date: (token.created_at || '').slice(0, 10) }))}${token.last_used_at ? ' · ' + esc(t('settings.tokens.lastUsed', { date: token.last_used_at.slice(0, 10) })) : ''}</small>
              </span>
              <button type="button" data-action="revoke-token" data-id="${token.id}"
                      style="background:none; border:1px solid #e74c3c; color:#e74c3c; border-radius:6px; padding:3px 10px; cursor:pointer;">${esc(t('settings.tokens.revoke'))}</button>
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
        this.$('#new-token-box').style.display = 'block';
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
