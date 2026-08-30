/**
 * i18n.js: the translation runtime for the Energy Pebble web UI.
 *
 * Language is an account setting (Settings → Account → Language) so it follows
 * the person across devices. Logged-out visitors get their browser's language
 * when we speak it, and can override it with the switcher in the top nav; that
 * choice lives in localStorage until they sign in, after which the account
 * setting wins.
 *
 * Usage:
 *   <script src="/i18n-strings.js"></script>   (the catalogs, load first)
 *   <script src="/i18n.js"></script>
 *   ... markup carrying data-i18n attributes ...
 *   <script>I18n.start();</script>             (once, at the end of <body>)
 *
 * Markup binding: put the key in an attribute, no JS needed:
 *   data-i18n="nav.login"                textContent
 *   data-i18n-html="home.intro"          innerHTML (for strings with markup)
 *   data-i18n-placeholder="home.name"    any attribute, via data-i18n-<attr>
 *   data-i18n-title / data-i18n-aria-label / data-i18n-alt likewise
 *
 * Strings built in JavaScript use I18n.t('key', {vars}); '{name}' placeholders
 * in the string are replaced from the vars object.
 *
 * Web components hold their strings in a shadow root, which document.querySelectorAll
 * cannot see. They call I18n.register(this.shadowRoot) so their markup is
 * translated on start and re-translated whenever the language changes.
 */
(function (global) {
  'use strict';

  var LANGUAGES = [
    { code: 'en', label: 'English', short: 'EN' },
    { code: 'nl', label: 'Nederlands', short: 'NL' },
    { code: 'fr', label: 'Français', short: 'FR' }
  ];
  var CODES = LANGUAGES.map(function (l) { return l.code; });
  var FALLBACK = 'en';
  var STORAGE_KEY = 'energy-pebble-language';

  // Roots to (re-)translate: the document plus every registered shadow root.
  var roots = [];
  var current = FALLBACK;
  var started = false;

  function catalog(code) {
    var all = global.I18N_STRINGS || {};
    return all[code] || {};
  }

  /** localStorage throws in some privacy modes; a missing preference is not an error. */
  function stored() {
    try {
      var v = global.localStorage.getItem(STORAGE_KEY);
      return CODES.indexOf(v) !== -1 ? v : null;
    } catch (e) {
      return null;
    }
  }

  function store(code) {
    try {
      global.localStorage.setItem(STORAGE_KEY, code);
    } catch (e) {
      /* preference simply won't survive the page, which is acceptable */
    }
  }

  /** First browser-preferred language we actually speak, e.g. 'nl-BE' -> 'nl'. */
  function fromBrowser() {
    var prefs = global.navigator.languages || [global.navigator.language || ''];
    for (var i = 0; i < prefs.length; i++) {
      var code = String(prefs[i]).toLowerCase().split('-')[0];
      if (CODES.indexOf(code) !== -1) return code;
    }
    return null;
  }

  function normalize(code) {
    return CODES.indexOf(code) !== -1 ? code : null;
  }

  /**
   * Look a key up in the active catalog, falling back to English and finally to
   * the key itself; a missing translation shows the English text, never a blank.
   */
  function lookup(key) {
    var value = catalog(current)[key];
    if (typeof value !== 'string') value = catalog(FALLBACK)[key];
    if (typeof value !== 'string') {
      if (global.console && console.warn) console.warn('[i18n] missing key:', key);
      return key;
    }
    return value;
  }

  function interpolate(text, vars) {
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, function (match, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match;
    });
  }

  function t(key, vars) {
    return interpolate(lookup(key), vars);
  }

  /**
   * Plural helper: looks up '<key>.one' or '<key>.other' and passes {count}.
   * Dutch, French and English all split the same way (1 vs. everything else),
   * so one rule covers the three languages we ship.
   */
  function plural(key, count, vars) {
    var suffix = count === 1 ? '.one' : '.other';
    var merged = { count: count };
    for (var k in vars) if (Object.prototype.hasOwnProperty.call(vars, k)) merged[k] = vars[k];
    return interpolate(lookup(key + suffix), merged);
  }

  /** Translate every data-i18n* binding under one root. */
  function apply(root) {
    if (!root) return;
    root.querySelectorAll('[data-i18n]').forEach(function (el) {
      el.textContent = t(el.getAttribute('data-i18n'), dataVars(el));
    });
    root.querySelectorAll('[data-i18n-html]').forEach(function (el) {
      el.innerHTML = t(el.getAttribute('data-i18n-html'), dataVars(el));
    });
    // Any other data-i18n-<attr> sets that attribute: placeholder, title, alt, aria-label...
    root.querySelectorAll('*').forEach(function (el) {
      for (var i = 0; i < el.attributes.length; i++) {
        var name = el.attributes[i].name;
        if (name.indexOf('data-i18n-') !== 0) continue;
        var attr = name.slice('data-i18n-'.length);
        if (attr === 'html' || attr === 'vars') continue;
        el.setAttribute(attr, t(el.attributes[i].value, dataVars(el)));
      }
    });
  }

  /** Optional data-i18n-vars='{"count":3}' for keys with placeholders. */
  function dataVars(el) {
    var raw = el.getAttribute('data-i18n-vars');
    if (!raw) return null;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return null;
    }
  }

  function applyAll() {
    document.documentElement.setAttribute('lang', current);
    roots.forEach(apply);
  }

  /** Shadow roots opt in here so their contents follow language changes. */
  function register(root) {
    if (root && roots.indexOf(root) === -1) {
      roots.push(root);
      if (started) apply(root);
    }
  }

  function unregister(root) {
    var i = roots.indexOf(root);
    if (i !== -1) roots.splice(i, 1);
  }

  /**
   * Switch language. `persist` remembers the choice in this browser; `save`
   * writes it to the account (only meaningful for a signed-in user).
   */
  function setLanguage(code, options) {
    var opts = options || {};
    var next = normalize(code);
    if (!next) return Promise.resolve(current);

    var changed = next !== current;
    current = next;
    if (opts.persist !== false) store(next);
    applyAll();
    if (changed) {
      document.dispatchEvent(new CustomEvent('language-changed', { detail: { language: next } }));
    }
    if (opts.save) return saveToAccount(next).then(function () { return next; });
    return Promise.resolve(next);
  }

  /**
   * Persist to the account. A logged-out visitor gets a 401 here, which is the
   * normal case on the public pages, where their choice lives in localStorage
   * only. We swallow that rather than logging a scary error.
   */
  function saveToAccount(code) {
    return fetch('/api/user/preferences', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ language: code })
    }).then(function (resp) {
      if (!resp.ok && resp.status !== 401) {
        console.error('[i18n] could not save language to the account:', resp.status);
      }
    }).catch(function (e) {
      console.error('[i18n] could not save language to the account:', e);
    });
  }

  /**
   * Adopt the account's language if the user is signed in. Runs after the first
   * render so the page is never blank waiting on the network; the browser or
   * stored language is usually the same one, so a visible switch is rare.
   */
  function syncFromAccount() {
    return fetch('/api/user/preferences')
      .then(function (resp) { return resp.ok ? resp.json() : null; })
      .then(function (data) {
        var code = data && data.preferences && normalize(data.preferences.language);
        if (code && code !== current) return setLanguage(code);
        return current;
      })
      .catch(function () { return current; });
  }

  /**
   * Resolve the language and translate the page. Order: stored choice, then the
   * browser's language, then English. The account setting arrives a moment later
   * via syncFromAccount() and overrides all three for signed-in users.
   */
  function start(options) {
    var opts = options || {};
    current = stored() || fromBrowser() || FALLBACK;
    started = true;
    if (roots.indexOf(document) === -1) roots.unshift(document);
    applyAll();
    if (opts.sync !== false) syncFromAccount();
    return current;
  }

  /**
   * Render a compact EN/NL/FR switcher into `container`. Anonymous visitors need
   * it because they have no account setting to fall back on; signed-in users get
   * the same effect from Settings → Account, and their pick is saved there too.
   */
  function mountSwitcher(container, options) {
    if (!container) return;
    var opts = options || {};
    container.innerHTML = LANGUAGES.map(function (l) {
      return '<button type="button" class="lang-option" data-lang="' + l.code + '"' +
        ' aria-label="' + l.label + '">' + l.short + '</button>';
    }).join('');

    function mark() {
      container.querySelectorAll('.lang-option').forEach(function (btn) {
        var active = btn.dataset.lang === current;
        btn.classList.toggle('active', active);
        btn.setAttribute('aria-pressed', active ? 'true' : 'false');
      });
    }

    container.addEventListener('click', function (e) {
      var btn = e.target.closest('.lang-option');
      if (btn) setLanguage(btn.dataset.lang, { save: !!opts.save });
    });
    document.addEventListener('language-changed', mark);
    mark();
  }

  global.I18n = {
    languages: LANGUAGES,
    codes: CODES,
    fallback: FALLBACK,
    get language() { return current; },
    t: t,
    plural: plural,
    apply: apply,
    applyAll: applyAll,
    register: register,
    unregister: unregister,
    setLanguage: setLanguage,
    syncFromAccount: syncFromAccount,
    mountSwitcher: mountSwitcher,
    start: start
  };
})(window);
