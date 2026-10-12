/* agent-registry-link.js — agent-only "Registry" pill on public listing-detail pages.
 * Deep-links straight into pages/agent-registry.html?q=<street>,<community> so an agent
 * standing on a property doesn't have to open the tool and retype the address.
 *
 * Fleet-verbatim: identical bytes on all 3 sites (see fleet/manifest.json). Self-contained
 * (no CSS file, no dependencies beyond window.TurnerAuth, which every listing page already
 * loads). Gate mirrors js/agent-shell.js's isAgent(): @royallepage.ca only — public visitors
 * never see or fetch anything extra; the check runs client-side after auth.js resolves.
 *
 * TurnerAuth.getUser() is SYNCHRONOUS (returns the cached user or null) -- it is
 * NOT a Promise. Calling .then() on it silently no-ops (caught the pill never
 * rendering, 2026-08-26). Call it directly and wrap in try/catch instead.
 */
(function () {
  "use strict";

  function isAgent(email) {
    return /@royallepage\.ca$/i.test(String(email || "").trim());
  }

  // Primary source: the page's own RealEstateListing JSON-LD (present on every generated
  // listing page fleet-wide) — exact street + community, no guessing from the URL slug.
  function fromJsonLd() {
    var blocks = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < blocks.length; i++) {
      var data;
      try { data = JSON.parse(blocks[i].textContent); } catch (e) { continue; }
      if (data && data["@type"] === "RealEstateListing" && data.address) {
        var street = (data.address.streetAddress || "").trim();
        var comm = (data.address.addressLocality || "").trim();
        if (street && comm) return "?q=" + encodeURIComponent(street + ", " + comm);
      }
    }
    return null;
  }

  // Fallback: the MLS# is always the trailing digits of the page's own URL
  // (/listings/<town>/<street>-<mls>.html). A bare MLS search needs no community.
  function fromUrl() {
    var m = /-(\d{6,8})\.html$/.exec(location.pathname);
    return m ? "?q=" + encodeURIComponent(m[1]) : null;
  }

  function buildLink() {
    var qs = fromJsonLd() || fromUrl();
    return qs ? "/pages/agent-registry.html" + qs : null;
  }

  var PILL_ID = "tc-registry-pill";

  // Listing-detail pages carry their own bottom-anchored UI that varies by site/page — a
  // full-width mobile "Book a showing" bar (.lst-mobile-cta, ~71px on Gander) and/or a chat
  // bubble — and a hardcoded bottom offset collided with both on a real phone (found via
  // screenshot verification, not assumed). Clear whatever is actually there instead of
  // guessing a fleet-wide magic number: scan for fixed/sticky elements whose box reaches
  // into the bottom band and float above the tallest one.
  function safeBottom() {
    var margin = 16, clearance = 12, minTop = window.innerHeight;
    var els = document.body.getElementsByTagName("*");
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (el.id === PILL_ID) continue;   // never let the pill clear itself on a recheck
      var pos = getComputedStyle(el).position;
      if (pos !== "fixed" && pos !== "sticky") continue;
      var r = el.getBoundingClientRect();
      if (r.height <= 0 || r.bottom < window.innerHeight - 100) continue;   // not a bottom occupant
      if (r.top < minTop) minTop = r.top;
    }
    var clearedBottom = window.innerHeight - minTop + clearance;
    return Math.max(margin, clearedBottom);
  }

  function showPill(href) {
    if (document.getElementById(PILL_ID)) return;
    var a = document.createElement("a");
    a.id = PILL_ID;
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener";
    a.title = "Chain of title, zoning & flood — internal, agents only";
    a.textContent = "📋 Registry";
    a.setAttribute(
      "style",
      "position:fixed;left:16px;bottom:" + safeBottom() + "px;z-index:9400;" +
      "display:flex;align-items:center;min-height:44px;padding:0 16px;" +
      "background:#EA002A;color:#fff;border-radius:22px;font:600 14px/1 " +
      "Roboto,system-ui,-apple-system,sans-serif;text-decoration:none;" +
      "box-shadow:0 4px 16px rgba(0,0,0,.35);white-space:nowrap;transition:bottom .15s;"
    );
    document.body.appendChild(a);
    syncKeyboard();
    // Bottom bars can appear/resize after load (e.g. a CTA bar toggling on scroll) — recheck
    // on resize/orientation change so the pill doesn't drift back into a collision.
    window.addEventListener("resize", function () {
      var el = document.getElementById(PILL_ID);
      if (el && !kbOpen()) el.style.bottom = safeBottom() + "px";
    });
    window.addEventListener("tnr:keyboard", syncKeyboard);
  }

  // While a phone keyboard is up (html.tnr-kb-open, set by the keyboard watch
  // in js/mobile-action-bar.js / js/chat-widget.js) the pill would ride on top
  // of the keyboard over the page content: hide it until the keyboard closes.
  function kbOpen() { return document.documentElement.classList.contains("tnr-kb-open"); }
  function syncKeyboard() {
    var el = document.getElementById(PILL_ID);
    if (el) el.style.display = kbOpen() ? "none" : "flex";
  }

  function hidePill() {
    var el = document.getElementById(PILL_ID);
    if (el) el.remove();
  }

  function refresh(user) {
    if (user && isAgent(user.email)) {
      var href = buildLink();
      if (href) showPill(href); else hidePill();
    } else {
      hidePill();
    }
  }

  function init() {
    var TA = window.TurnerAuth;
    if (!TA || !TA.ready || TA._stub) return;   // no Supabase session capability on this load
    TA.ready.then(function () {
      if (TA._stub) return;
      try { refresh(TA.getUser()); } catch (e) { hidePill(); }
      if (typeof TA.onAuthChange === "function") {
        TA.onAuthChange(function () {
          try { refresh(TA.getUser()); } catch (e) { hidePill(); }
        });
      }
    }).catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
