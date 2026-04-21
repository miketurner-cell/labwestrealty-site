/* ═══════════════════════════════════════════════════════════════
   analytics-events.js — Royal LePage Turner Realty
   Shared GA4 key-event tracking + preview-host noindex
   Single file, no external dependencies. Include after the
   gtag.js loader on every page.

   Exposes:
     window.trackLead(formName, extra)  — call from contact form
                                          submit handlers; sends
                                          a GA4 'generate_lead'
                                          key event.
   Auto-tracks:
     mailto:  clicks  -> 'click_email'
     tel:     clicks  -> 'click_phone'
     external http(s) -> 'click_outbound'   (host != current)

   Also inserts <meta name="robots" content="noindex,nofollow">
   when the page is served from a *.netlify.app preview domain or
   a legacy *.squarespace.com host, so staging URLs can't compete
   with the canonical production domain in search results.
   ═══════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  // ── 1. Preview-host noindex ────────────────────────────────────
  var host = (window.location && window.location.hostname) || '';
  var isPreview =
    /\.netlify\.app$/i.test(host) ||
    /\.squarespace\.com$/i.test(host);
  if (isPreview) {
    try {
      var m = document.createElement('meta');
      m.name = 'robots';
      m.content = 'noindex,nofollow';
      (document.head || document.documentElement).appendChild(m);
    } catch (e) { /* no-op */ }
  }

  // ── 2. Helper: safe gtag call + ad-platform mirror ─────────────
  // Mirrors key events to Meta Pixel (if fbq loaded) and Google Ads
  // conversion (if window.GOOGLE_ADS_CONVERSION is set as
  // { send_to: 'AW-XXXX/YYYY' }). All mirrors are no-ops until the
  // respective base tag / pixel is installed on the page.
  var META_EVENT_MAP = {
    generate_lead: 'Lead',
    click_email:   'Contact',
    click_phone:   'Contact'
  };
  function mirrorToMeta(eventName, params) {
    if (typeof window.fbq !== 'function') return;
    var metaEvent = META_EVENT_MAP[eventName];
    if (!metaEvent) return;
    try { window.fbq('track', metaEvent, params || {}); } catch (e) {}
  }
  function mirrorToGoogleAds(eventName, params) {
    // Only mirror lead conversions to Google Ads. Requires caller to
    // set window.GOOGLE_ADS_CONVERSION = { send_to: 'AW-XXXX/YYYY' }.
    if (eventName !== 'generate_lead') return;
    var cfg = window.GOOGLE_ADS_CONVERSION;
    if (!cfg || !cfg.send_to || typeof window.gtag !== 'function') return;
    try { window.gtag('event', 'conversion', { send_to: cfg.send_to }); } catch (e) {}
  }
  function send(eventName, params) {
    try {
      if (typeof window.gtag === 'function') {
        window.gtag('event', eventName, params || {});
      }
    } catch (e) { /* no-op */ }
    mirrorToMeta(eventName, params);
    mirrorToGoogleAds(eventName, params);
  }

  // ── 3. Public: trackLead(formName, extra) ──────────────────────
  window.trackLead = function (formName, extra) {
    var p = Object.assign(
      { form_name: formName || 'unknown', page_path: location.pathname },
      extra || {}
    );
    send('generate_lead', p);
  };

  // ── 4. Auto-track email / phone / outbound clicks ──────────────
  function onDocClick(e) {
    // Find nearest anchor
    var el = e.target;
    while (el && el !== document && el.tagName !== 'A') el = el.parentNode;
    if (!el || el.tagName !== 'A') return;

    var href = el.getAttribute('href') || '';
    if (!href) return;

    // mailto:
    if (/^mailto:/i.test(href)) {
      send('click_email', {
        email_to: href.replace(/^mailto:/i, '').split('?')[0],
        link_text: (el.textContent || '').trim().slice(0, 80),
        page_path: location.pathname
      });
      return;
    }
    // tel:
    if (/^tel:/i.test(href)) {
      send('click_phone', {
        phone: href.replace(/^tel:/i, '').replace(/[^\d+]/g, ''),
        link_text: (el.textContent || '').trim().slice(0, 80),
        page_path: location.pathname
      });
      return;
    }
    // http(s) outbound (different host)
    if (/^https?:/i.test(href)) {
      try {
        var u = new URL(href, location.href);
        if (u.hostname && u.hostname !== location.hostname) {
          send('click_outbound', {
            outbound_url: u.href,
            outbound_host: u.hostname,
            link_text: (el.textContent || '').trim().slice(0, 80),
            page_path: location.pathname
          });
        }
      } catch (err) { /* bad URL, ignore */ }
    }
  }
  document.addEventListener('click', onDocClick, true);
})();
