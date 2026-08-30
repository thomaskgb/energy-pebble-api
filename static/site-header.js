/**
 * <site-header>: the one top bar, for every page that has one.
 *
 * There used to be nine hand-written copies of this markup, and they had
 * drifted: Logout sat in the user menu on the dashboard but inside the Admin
 * menu on admin pages, Settings disappeared on half the site, and the language
 * switcher only existed on the public landing page. Items moved between pages,
 * which is exactly what navigation must never do.
 *
 * So the chrome is persistent and only its STATE changes. Same items, same
 * order, same place everywhere; the current page is marked rather than removed;
 * role decides what exists, never which slot it lives in.
 *
 * Usage:
 *   <site-header current="dashboard"></site-header>
 *
 * `current` is one of: home, dashboard, simulator, impact, admin. It only
 * decides which item is marked; it never changes what is rendered.
 *
 * Renders into the light DOM on purpose: base.css styles it and the i18n
 * runtime translates it, both of which would need extra plumbing in a shadow
 * root for no benefit.
 */
(function () {
  'use strict';

  // The whole of the primary navigation, in the order it is drawn. Anonymous
  // visitors see the same list; the links that need an account send them
  // through the login, which is a clearer answer than a menu that changes
  // shape depending on who is looking.
  var PRIMARY = [
    { key: 'dashboard', href: '/dashboard',      i18nKey: 'nav.dashboard', label: 'Dashboard' },
    { key: 'insights',  href: '/insights',       i18nKey: 'nav.insights',  label: 'Insights' },
    { key: 'simulator', href: '/simulator.html', i18nKey: 'nav.simulator', label: 'Simulator' }
  ];

  var LOGOUT_URL = 'https://auth.tdlx.nl/logout?rd=https://energypebble.tdlx.nl/';

  /** Translate if the runtime is loaded; fall back to English if it is not. */
  function t(key, fallback) {
    return (window.I18n && window.I18n.t) ? window.I18n.t(key) : fallback;
  }

  function icon(name, size) {
    return (window.Icons && window.Icons.svg) ? window.Icons.svg(name, { size: size || 16 }) : '';
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  class SiteHeader extends HTMLElement {
    connectedCallback() {
      this._user = null;
      this._render();
      this._loadUser();
      // Labels follow a language change like any other markup.
      document.addEventListener('language-changed', () => this._render());
    }

    get current() { return this.getAttribute('current') || ''; }

    _render() {
      var cur = this.current;
      var user = this._user;

      var primary = PRIMARY.map(function (item) {
        var active = item.key === cur;
        return '<a href="' + item.href + '" class="site-nav__link' + (active ? ' is-active' : '') + '"' +
               (active ? ' aria-current="page"' : '') + '>' +
               '<span data-i18n="' + item.i18nKey + '">' + esc(t(item.i18nKey, item.label)) + '</span></a>';
      }).join('');

      // The account menu is the single home for Settings, Admin and Log out.
      var account;
      if (user) {
        account =
          '<div class="menu" id="site-account">' +
            '<button type="button" class="btn btn--secondary" id="site-account-trigger"' +
                   ' aria-haspopup="true" aria-expanded="false">' +
              icon('user') +
              '<span class="site-account__name">' + esc(user.name) + '</span>' +
              icon('chevronDown', 14).replace('<svg', '<svg class="menu__chevron"') +
            '</button>' +
            '<div class="menu__panel" role="menu">' +
              '<button type="button" class="menu__item" role="menuitem" data-action="settings">' +
                icon('settings') + '<span data-i18n="nav.settings">' + esc(t('nav.settings', 'Settings')) + '</span>' +
              '</button>' +
              (user.isAdmin
                ? '<a href="/admin/users" class="menu__item' + (cur === 'admin' ? ' menu__item--active' : '') + '" role="menuitem">' +
                    icon('shield') + '<span data-i18n="nav.admin">' + esc(t('nav.admin', 'Admin')) + '</span>' +
                  '</a>'
                : '') +
              '<div class="menu__separator"></div>' +
              '<a href="' + LOGOUT_URL + '" class="menu__item menu__item--danger" role="menuitem">' +
                icon('logout') + '<span data-i18n="nav.logout">' + esc(t('nav.logout', 'Logout')) + '</span>' +
              '</a>' +
            '</div>' +
          '</div>';
      } else {
        account = '<a href="/dashboard" class="btn btn--primary">' +
                  '<span data-i18n="nav.login">' + esc(t('nav.login', 'Login')) + '</span></a>';
      }

      this.innerHTML =
        '<header class="site-header">' +
          '<div class="site-header__inner">' +
            '<a href="/" class="brand">' + icon('bolt', 20).replace('<svg', '<svg class="brand__mark"') +
              'Energy Pebble</a>' +
            '<nav class="site-nav site-nav--primary">' + primary + '</nav>' +
            '<div class="site-nav site-nav--utility">' +
              '<div class="lang-switcher" data-site-lang></div>' +
              account +
            '</div>' +
          '</div>' +
        '</header>';

      if (window.Icons) window.Icons.render(this);
      if (window.I18n && window.I18n.mountSwitcher) {
        window.I18n.mountSwitcher(this.querySelector('[data-site-lang]'), { save: !!user });
      } else {
        // No translation runtime on this page: drop the switcher rather than
        // leave an empty control sitting in the bar.
        var box = this.querySelector('[data-site-lang]');
        if (box) box.remove();
      }
      this._wire();
    }

    _wire() {
      var menu = this.querySelector('#site-account');
      var trigger = this.querySelector('#site-account-trigger');
      var self = this;

      if (menu && trigger) {
        var setOpen = function (open) {
          menu.classList.toggle('is-open', open);
          trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
        };
        trigger.addEventListener('click', function (e) {
          e.preventDefault();
          setOpen(!menu.classList.contains('is-open'));
        });
        document.addEventListener('click', function (e) {
          if (!menu.contains(e.target)) setOpen(false);
        });
        document.addEventListener('keydown', function (e) {
          if (e.key === 'Escape') setOpen(false);
        });
        this._setOpen = setOpen;
      }

      var settings = this.querySelector('[data-action="settings"]');
      if (settings) {
        settings.addEventListener('click', function () {
          if (self._setOpen) self._setOpen(false);
          // The settings modal is heavy, so only the pages that need it embed
          // it. Everywhere else the item goes to the page that has it.
          var modal = document.getElementById('settings-modal');
          if (modal && modal.open) modal.open();
          else window.location.href = '/dashboard';
        });
      }
    }

    /** Ask once who is signed in, then redraw with the account menu. */
    _loadUser() {
      var self = this;
      fetch('/api/verify', { credentials: 'include' })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || !d.authenticated) return;
          self._user = { name: d.display_name || d.user || 'Account', isAdmin: !!d.is_admin };
          self._render();
          self.dispatchEvent(new CustomEvent('user-loaded', {
            detail: self._user, bubbles: true
          }));
        })
        .catch(function () { /* anonymous is a normal state, not an error */ });
    }

    /** Let a page update the name after a profile change, without a reload. */
    setUsername(name) {
      if (!this._user) return;
      this._user.name = name;
      this._render();
    }
  }

  customElements.define('site-header', SiteHeader);
})();
