/**
 * icons.js — the interface icon set.
 *
 * Emoji used to stand in for icons across the UI. They render differently on
 * every platform, cannot take the surrounding text colour, and sit on the text
 * baseline in ways no amount of CSS fixes. These are inline SVGs instead: one
 * stroke weight, one 24-unit grid, always `currentColor`.
 *
 * Usage — put a placeholder in the markup and let it hydrate:
 *   <i data-icon="bolt"></i>
 *   <i data-icon="user" data-icon-size="16"></i>
 * or build one in JavaScript:
 *   Icons.svg('refresh', { size: 16, className: 'spin' })
 *
 * Call Icons.render(root) after inserting markup that contains placeholders;
 * the document is hydrated automatically on DOMContentLoaded.
 *
 * Icons are decorative here — every one sits next to a visible label — so they
 * carry aria-hidden and are skipped by screen readers.
 */
(function (global) {
  'use strict';

  /* Path data only; the wrapper below supplies the shared attributes. */
  var PATHS = {
    bolt:        '<path d="M13 2 4.5 13.5H11l-1 8.5 8.5-11.5H12l1-8.5Z"/>',
    dashboard:   '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
    user:        '<circle cx="12" cy="8" r="3.5"/><path d="M4.5 20a7.5 7.5 0 0 1 15 0"/>',
    settings:    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1Z"/>',
    logout:      '<path d="M15 17l5-5-5-5"/><path d="M20 12H9"/><path d="M12 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h6"/>',
    login:       '<path d="M10 17l5-5-5-5"/><path d="M15 12H4"/><path d="M12 4h6a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/>',
    refresh:     '<path d="M20 11a8 8 0 0 0-13.7-5.2L3 9"/><path d="M4 13a8 8 0 0 0 13.7 5.2L21 15"/><path d="M3 4v5h5"/><path d="M21 20v-5h-5"/>',
    lock:        '<rect x="4.5" y="10.5" width="15" height="10" rx="2"/><path d="M8 10.5V7a4 4 0 0 1 8 0v3.5"/>',
    chevronDown: '<path d="m6 9 6 6 6-6"/>',
    chevronRight:'<path d="m9 6 6 6-6 6"/>',
    arrowRight:  '<path d="M4 12h16"/><path d="m14 6 6 6-6 6"/>',
    arrowLeft:   '<path d="M20 12H4"/><path d="m10 18-6-6 6-6"/>',
    plus:        '<path d="M12 5v14"/><path d="M5 12h14"/>',
    check:       '<path d="m5 12.5 4.5 4.5L19 7"/>',
    checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    shield:      '<path d="M12 3l7.5 3v5.5c0 4.4-3 8.2-7.5 9.5-4.5-1.3-7.5-5.1-7.5-9.5V6L12 3Z"/>',
    globe:       '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z"/>',
    leaf:        '<path d="M4 20c0-8 5-13 16-13 0 9-4.5 13-11 13H4Z"/><path d="M9 15c2-3 4.5-5 8-6.5"/>',
    sun:         '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
    cloud:       '<path d="M17.5 19a4.5 4.5 0 0 0 .3-9 6 6 0 0 0-11.6 1.6A3.7 3.7 0 0 0 7 19h10.5Z"/>',
    wind:        '<path d="M3 8h10a3 3 0 1 0-3-3"/><path d="M3 12h14a3 3 0 1 1-3 3"/><path d="M3 16h7a2.5 2.5 0 1 1-2.5 2.5"/>',
    flame:       '<path d="M12 3s5 4 5 9a5 5 0 0 1-10 0c0-2 1-3.5 2-4.5 0 1.5.8 2.5 2 2.5 1.5 0 1.8-3.5 1-7Z"/>',
    antenna:     '<circle cx="12" cy="12" r="2"/><path d="M8.5 8.5a5 5 0 0 0 0 7M15.5 15.5a5 5 0 0 0 0-7"/><path d="M5.6 5.6a9 9 0 0 0 0 12.8M18.4 18.4a9 9 0 0 0 0-12.8"/>',
    camera:      '<path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13.5" r="3.5"/>',
    sliders:     '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    info:        '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8h.01"/>',
    alert:       '<path d="M12 4 2.8 20h18.4L12 4Z"/><path d="M12 10v4"/><path d="M12 17h.01"/>',
    battery:     '<rect x="2.5" y="8" width="16" height="8" rx="2"/><path d="M21.5 11v2"/><path d="M6 11v2M9.5 11v2"/>',
    chip:        '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    plug:        '<path d="M9 3v6M15 3v6"/><path d="M6 9h12v2a6 6 0 0 1-12 0V9Z"/><path d="M12 17v4"/>',
    book:        '<path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H19v15H6.5A2.5 2.5 0 0 0 4 20.5V5.5Z"/><path d="M4 20.5A2.5 2.5 0 0 1 6.5 18H19v3H6.5A2.5 2.5 0 0 1 4 20.5Z"/>',
    code:        '<path d="m9 8-5 4 5 4"/><path d="m15 8 5 4-5 4"/>',
    external:    '<path d="M14 4h6v6"/><path d="M20 4 11 13"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    clock:       '<circle cx="12" cy="12" r="9"/><path d="M12 7v5.5l3.5 2"/>',
    home:        '<path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-9.5Z"/><path d="M9.5 21v-6h5v6"/>',
    close:       '<path d="M6 6l12 12M18 6 6 18"/>',
    search:      '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4.5 4.5"/>',
    trash:       '<path d="M4 7h16"/><path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/><path d="M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12"/>',
    edit:        '<path d="M4 20h4L19 9a2.1 2.1 0 0 0-3-3L5 17v3Z"/><path d="m14.5 6.5 3 3"/>',
    wifi:        '<path d="M2.5 9a15 15 0 0 1 19 0"/><path d="M6 12.5a10 10 0 0 1 12 0"/><path d="M9.5 16a5 5 0 0 1 5 0"/><path d="M12 19.5h.01"/>'
  };

  function svg(name, options) {
    var opts = options || {};
    var path = PATHS[name];
    if (!path) {
      if (global.console && console.warn) console.warn('[icons] unknown icon:', name);
      return '';
    }
    var size = opts.size || 18;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="' + size +
      '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="1.7"' +
      ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"' +
      (opts.className ? ' class="' + opts.className + '"' : '') + '>' + path + '</svg>';
  }

  /** Replace every un-hydrated <i data-icon="..."> under `root` with its SVG. */
  function render(root) {
    var scope = root || document;
    scope.querySelectorAll('[data-icon]:not([data-icon-done])').forEach(function (el) {
      var markup = svg(el.getAttribute('data-icon'), {
        size: Number(el.getAttribute('data-icon-size')) || 18
      });
      if (!markup) return;
      el.innerHTML = markup;
      el.setAttribute('data-icon-done', '');
    });
  }

  global.Icons = { svg: svg, render: render, names: Object.keys(PATHS) };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { render(); });
  } else {
    render();
  }
})(window);
