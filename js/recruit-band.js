/**
 * recruit-band.js -- the "This could be your territory" recruiting band (sites, D-1012-34, component 11).
 *
 * Loaded ONLY by pages the gated Lab West rebuild generates (listing, sold, property, market, community, alerts pages); no
 * hand-written page references it, so index.html, why-join.html and every other live page are untouched while the switch is off.
 * It inserts one band above the site footer and does nothing if a band is already on the page (the generated homepage carries
 * its own) or there is no footer. Copy as drawn in _ops/previews/2026-10-12/redesign_labwest_band_*.png; no number, rating or
 * address is in it (always-on #35).
 */
(function () {
  'use strict';
  function mount() {
    if (document.querySelector('.lwh-recruit, .lw-recruit-band')) return;
    var footer = document.querySelector('footer.site-footer');
    if (!footer || !footer.parentNode) return;
    var css = document.createElement('style');
    css.textContent =
      '.lw-recruit-band{background:#161618;border-left:4px solid #EA002A;margin:42px 0 0;color:#fff;font-family:Roboto,sans-serif}' +
      '.lw-recruit-band-in{max-width:1200px;margin:0 auto;padding:30px 20px;display:flex;gap:28px;align-items:center;justify-content:space-between;flex-wrap:wrap}' +
      '.lw-recruit-band .eb{color:#EA002A;font:700 .78rem/1 Raleway,sans-serif;letter-spacing:.12em;text-transform:uppercase;margin:0 0 10px}' +
      '.lw-recruit-band h2{font:900 1.7rem/1.1 Raleway,sans-serif;margin:0 0 8px}' +
      '.lw-recruit-band p{color:#cfcfd4;line-height:1.5;margin:0;max-width:620px}' +
      '.lw-recruit-band .bt{display:flex;gap:14px;flex-wrap:wrap;align-items:center}' +
      '.lw-recruit-band a.b{display:inline-block;padding:12px 20px;border-radius:6px;font-weight:800;text-decoration:none;background:#EA002A;color:#fff}' +
      '.lw-recruit-band a.l{color:#fff;font-weight:700;text-decoration:none;border-bottom:1px solid #888;padding:12px 2px}';
    document.head.appendChild(css);
    var s = document.createElement('section');
    s.className = 'lw-recruit-band';
    s.setAttribute('aria-labelledby', 'lw-recruit-h');
    s.innerHTML =
      '<div class="lw-recruit-band-in"><div>' +
      '<p class="eb">Now recruiting in Labrador West</p>' +
      '<h2 id="lw-recruit-h">This could be your territory.</h2>' +
      '<p>Labrador West is served from our Gander and Goose Bay offices, and we\'re open to a home-based agent here. Be the first Royal LePage agent in Labrador City and Wabush, with the same tools our agents use every day.</p>' +
      '</div><div class="bt"><a class="b" href="/why-join.html">See what agents get</a><a class="l" href="/contact.html">Talk to Mike Turner</a></div></div>';
    footer.parentNode.insertBefore(s, footer);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount); else mount();
})();
