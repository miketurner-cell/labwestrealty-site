/**
 * Sitewide footer injection -- Turner Realty (Tier-1, byte-identical
 * across the fleet, same pattern as js/nav.js: every per-site
 * difference lives in that site's own un-synced js/nav-config.js, in
 * a window.FOOTER object alongside the existing SITE/MENU). Include
 * this script before </body>, after nav-config.js.
 *
 * Deferred-script race (same defect class as nav.js's topBarHTML,
 * banked 2026-09-09): js/regions-data.js loads with `defer` on many
 * generator paths while this script does not, so window.TURNER_REGIONS
 * may not exist yet at parse time. The cross-region network line is
 * therefore computed inside injectFooter(), called on/after
 * DOMContentLoaded, never baked into a module-level string.
 */
(function () {
  'use strict';

  function esc(s) { return String(s == null ? '' : s); }

  function socialIconsHTML(site) {
    var icons = '';
    if (site.facebook) {
      icons += '<a href="' + site.facebook + '" target="_blank" rel="noopener" aria-label="Facebook"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M18 2h-3a5 5 0 0 0-5 5v3H7v4h3v8h4v-8h3l1-4h-4V7a1 1 0 0 1 1-1h3z"/></svg></a>';
    }
    if (site.instagram) {
      icons += '<a href="' + site.instagram + '" target="_blank" rel="noopener" aria-label="Instagram"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2c2.717 0 3.056.01 4.122.06 1.065.05 1.79.217 2.428.465.66.254 1.216.598 1.772 1.153a4.908 4.908 0 0 1 1.153 1.772c.247.637.415 1.363.465 2.428.05 1.066.06 1.405.06 4.122 0 2.717-.01 3.056-.06 4.122-.05 1.065-.218 1.79-.465 2.428a4.883 4.883 0 0 1-1.153 1.772 4.915 4.915 0 0 1-1.772 1.153c-.637.247-1.363.415-2.428.465-1.066.05-1.405.06-4.122.06-2.717 0-3.056-.01-4.122-.06-1.065-.05-1.79-.218-2.428-.465a4.89 4.89 0 0 1-1.772-1.153 4.904 4.904 0 0 1-1.153-1.772c-.248-.637-.415-1.363-.465-2.428-.05-1.066-.06-1.405-.06-4.122 0-2.717.01-3.056.06-4.122.05-1.065.217-1.79.465-2.428a4.88 4.88 0 0 1 1.153-1.772A4.897 4.897 0 0 1 5.45 2.525c.638-.248 1.362-.415 2.428-.465C8.944 2.01 9.283 2 12 2zm0 1.802c-2.67 0-2.986.01-4.04.059-.976.045-1.505.207-1.858.344-.466.181-.8.398-1.15.748-.35.35-.566.683-.747 1.15-.137.353-.3.882-.344 1.857-.049 1.055-.06 1.37-.06 4.04 0 2.67.01 2.986.06 4.04.045.976.207 1.505.344 1.858.181.466.398.8.748 1.15.35.35.683.566 1.15.747.353.137.882.3 1.857.344 1.054.049 1.37.06 4.04.06 2.67 0 2.987-.01 4.04-.06.976-.045 1.505-.207 1.858-.344.466-.181.8-.398 1.15-.748.35-.35.566-.683.747-1.15.137-.353.3-.882.344-1.857.049-1.054.06-1.37.06-4.04 0-2.67-.01-2.986-.06-4.04-.045-.976-.207-1.505-.344-1.858a3.09 3.09 0 0 0-.748-1.15 3.09 3.09 0 0 0-1.15-.747c-.353-.137-.882-.3-1.857-.344-1.054-.049-1.37-.06-4.04-.06zM12 6.865a5.135 5.135 0 1 1 0 10.27 5.135 5.135 0 0 1 0-10.27zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm5.338-9.87a1.2 1.2 0 1 1 0 2.4 1.2 1.2 0 0 1 0-2.4z"/></svg></a>';
    }
    if (site.tiktok) {
      icons += '<a href="' + site.tiktok + '" target="_blank" rel="noopener" aria-label="TikTok"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M16.6 5.82s.51.5 0 0A4.278 4.278 0 0 1 15.54 3h-3.09v12.4a2.592 2.592 0 0 1-2.59 2.5c-1.42 0-2.6-1.16-2.6-2.6 0-1.72 1.66-3.01 3.37-2.48V9.66c-3.45-.46-6.47 2.22-6.47 5.64 0 3.33 2.76 5.7 5.69 5.7 3.14 0 5.69-2.55 5.69-5.7V9.01a7.35 7.35 0 0 0 4.3 1.38V7.3s-1.88.09-3.24-1.48z"/></svg></a>';
    }
    if (site.youtube) {
      icons += '<a href="' + site.youtube + '" target="_blank" rel="noopener" aria-label="YouTube"><svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M22.54 6.42a2.78 2.78 0 0 0-1.94-2C18.88 4 12 4 12 4s-6.88 0-8.6.46a2.78 2.78 0 0 0-1.94 2A29 29 0 0 0 1 12a29 29 0 0 0 .46 5.58A2.78 2.78 0 0 0 3.4 19.6C5.12 20 12 20 12 20s6.88 0 8.6-.46a2.78 2.78 0 0 0 1.94-2A29 29 0 0 0 23 12a29 29 0 0 0-.46-5.58zM9.75 15.02V8.98L15.5 12l-5.75 3.02z"/></svg></a>';
    }
    return icons;
  }

  function columnHTML(col) {
    var items = (col.links || []).map(function (l) {
      return '<li><a href="' + l[1] + '">' + l[0] + '</a></li>';
    }).join('');
    return '<div><div class="footer-heading">' + esc(col.heading) + '</div><ul class="footer-links">' + items + '</ul></div>';
  }

  // Live Turner-operated sibling regions, excluding the current site --
  // reads window.TURNER_REGIONS, which may legitimately be absent (a
  // handful of pages don't load regions-data.js yet). Fail-safe: emit
  // nothing rather than a half line (Convention #74/#202).
  function networkLineHTML() {
    var reg = window.TURNER_REGIONS;
    if (!reg) return '';
    var mySiteKey = window.TURNER_SITE || null;
    var out = [];
    for (var k in reg) {
      if (!reg.hasOwnProperty(k)) continue;
      var r = reg[k];
      if (!r || r.state !== 'live' || r.operator !== 'turner' || !r.domain) continue;
      if (mySiteKey && r.site_key === mySiteKey) continue;
      out.push('<a href="' + r.domain.replace(/\/$/, '') + '/">' + esc(r.nav_label || r.label) + '</a>');
    }
    if (!out.length) return '';
    return '<p class="footer-network-line">Royal LePage Turner Realty also serves ' + out.join(' &middot; ') + '.</p>';
  }

  // Minimal generic-brand fallback, same convention + same Gander-default
  // fields as js/nav.js's own fallback (a page missing nav-config.js --
  // e.g. every 404.html, which loads no nav-config.js at all -- must not
  // render a blank/empty footer). No columns are guessed (menu content
  // is genuinely per-site); turner-network.js is still the source of
  // truth for per-site NAP once window.TURNER_SITE is set correctly.
  var FALLBACK_SITE = {
    logo: '', address: '', email: '',
    facebook: '', instagram: '', youtube: '',
    phoneTel: '7092567999', phone: '709-256-7999'
  };
  var FALLBACK_FOOTER = { copyright: '&copy; 1998&ndash;{year} Royal LePage Turner Realty (2014) Inc.', columns: [] };

  function footerHTML() {
    var site = window.SITE || FALLBACK_SITE;
    var f = window.FOOTER || FALLBACK_FOOTER;
    if (!window.SITE || !window.FOOTER) {
      try { console.warn('[footer.js] window.SITE/window.FOOTER missing on this page -- nav-config.js was not loaded before footer.js. Rendering a minimal fallback footer; fix the page\'s generator to emit nav-config.js.'); } catch (e) {}
    }
    var cols = (f.columns || []).map(columnHTML).join('');
    var brandName = 'Royal LePage Turner Realty';

    var napLine = 'Brokerage: ' + brandName +
      (site.address ? '<br>' + esc(site.address) : '') + '<br>' +
      (site.phoneTel ? '<a href="tel:' + site.phoneTel + '">' + esc(site.phone) + '</a>' : '') +
      (site.phoneTel && site.email ? ' &middot; ' : '') +
      (site.email ? '<a href="mailto:' + site.email + '">' + esc(site.email) + '</a>' : '');

    return '<footer class="site-footer">' +
      '<div class="footer-inner">' +
      '<div class="footer-brand">' +
      (site.logo ? '<img src="' + site.logo + '" alt="' + brandName + '" width="80" loading="lazy">' : '') +
      '<p>' + napLine + '</p>' +
      '<div class="footer-social">' + socialIconsHTML(site) + '</div>' +
      '</div>' +
      cols +
      '</div>' +
      '<div class="footer-proudly-canadian" style="text-align:center;padding:32px 24px 0;border-top:1px solid #222;">' +
      '<img src="/images/proudly-canadian.png" alt="Proudly Canadian" width="220" height="auto" loading="lazy" style="max-width:220px;height:auto;opacity:0.85;">' +
      '</div>' +
      '<div class="footer-bottom">' +
      '<p>' + esc(f.copyright).replace('{year}', new Date().getFullYear()) + '</p>' +
      '<p>Each office independently owned and operated. Not intended to solicit buyers or sellers currently under contract.</p>' +
      networkLineHTML() +
      '<p class="footer-legal-links"><a href="/pages/privacy-policy.html">Privacy Policy</a> &middot; <a href="/pages/terms-of-use.html">Terms of Use</a> &middot; <a href="/pages/accessibility.html">Accessibility</a> &middot; <a href="/agent" rel="nofollow">Agent Login</a></p>' +
      '</div>' +
      '<aside class="crea-compliance" style="text-align:center;padding:16px 24px 32px;">' +
      '<p style="font-size:12px;color:var(--text-secondary,#999);max-width:800px;margin:0 auto;line-height:1.6;">' +
      'The information contained on this page is based in whole or in part on information that is provided by members of The Canadian Real Estate Association, who are responsible for its accuracy. CREA reproduces and distributes this information as a service for its members and assumes no responsibility for its accuracy. ' + brandName + ' is a member of The Canadian Real Estate Association.' +
      '</p>' +
      '<p style="font-size:12px;color:var(--text-secondary,#999);max-width:800px;margin:8px auto 0;line-height:1.6;">' +
      'The trademarks REALTOR&reg;, REALTORS&reg;, and the REALTOR&reg; logo are controlled by The Canadian Real Estate Association (CREA) and identify real estate professionals who are members of CREA. The trademarks MLS&reg;, Multiple Listing Service&reg; and the associated logos are owned by CREA and identify the quality of services provided by real estate professionals who are members of CREA. Used under license.' +
      '</p>' +
      '</aside>' +
      '</footer>';
  }

  function injectFooter() {
    var html = footerHTML();
    var existingFooter = document.querySelector('footer.site-footer') || document.querySelector('footer');
    if (existingFooter) {
      existingFooter.outerHTML = html;
    } else {
      document.body.insertAdjacentHTML('beforeend', html);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectFooter);
  } else {
    injectFooter();
  }
})();
