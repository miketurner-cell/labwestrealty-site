/*!
 * Alert UX Phase 3 (Part A) — save-nudge after favoriting.
 * 2026-07-30. After the 2nd favorite, with no saved search yet on this
 * account, suggests one derived from the favorited listings' city/price
 * range/property type -- an inline dismissible banner, not a modal.
 *
 * Reuses window.SavedSearch.promptSave() (the same save-modal + SMS-upsell
 * chain every other saved-search surface uses) -- no new backend, no new
 * consent flow, no duplicated CASL copy. Conv #74 throughout: a missing
 * dependency (Favorites, SavedSearch, the listings feed, .lst-shell) means
 * the nudge simply never shows -- it never breaks the page.
 *
 * Loaded on listing-detail pages only (they already carry auth.js). City
 * pages are deliberately localStorage-only, no-auth, per the favorites.js
 * comment at their emit site -- adding this there would cross that line
 * for a feature that will show just as reliably a page later.
 */
(function () {
  "use strict";
  if (!window.Favorites) return;

  var LS_DISMISSED = "lst-save-nudge-dismissed-v1";
  var shown = false;
  var banner = null;

  function dismissed() {
    try { return localStorage.getItem(LS_DISMISSED) === "1"; } catch (e) { return false; }
  }
  function setDismissed() {
    try { localStorage.setItem(LS_DISMISSED, "1"); } catch (e) { /* no-op */ }
  }

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function fmtPriceK(n) {
    if (n >= 1000000) return "$" + (Math.round(n / 100000) / 10) + "M";
    return "$" + Math.round(n / 1000) + "K";
  }

  function listingsDataUrl() {
    var site = (window.Favorites && window.Favorites.site) || "";
    if (site === "avalon" || site === "goosebay") return "/listings/data.json";
    return "/listings/data.json";
  }

  // Mirrors favorites.js's own field-reading (list_price falls back to
  // price -- the shape every site's feed actually uses).
  function deriveCriteria(rows) {
    var cities = [], seenCity = {}, prices = [], ptypes = {};
    rows.forEach(function (l) {
      var c = l.city;
      if (c && !seenCity[c.toLowerCase()]) { seenCity[c.toLowerCase()] = true; cities.push(c); }
      var p = Number(l.list_price != null ? l.list_price : l.price);
      if (p) prices.push(p);
      if (l.ptype) ptypes[l.ptype] = true;
    });
    var out = { v: 2 };
    if (cities.length) out.cities = cities;
    if (prices.length) {
      out.priceMin = Math.min.apply(null, prices);
      out.priceMax = Math.max.apply(null, prices);
    }
    var ptypeList = Object.keys(ptypes);
    if (ptypeList.length === 1) out.ptypes = ptypeList;
    return out;
  }

  function summaryText(criteria, count) {
    var where = "";
    if (criteria.cities && criteria.cities.length) {
      where = criteria.cities.length === 1
        ? "in " + criteria.cities[0]
        : "in " + criteria.cities.slice(0, -1).join(", ") + " and " + criteria.cities[criteria.cities.length - 1];
    }
    var price = (criteria.priceMin && criteria.priceMax)
      ? " from " + fmtPriceK(criteria.priceMin) + " to " + fmtPriceK(criteria.priceMax)
      : "";
    return "You’ve saved " + count + " home" + (count === 1 ? "" : "s") + " " + where + price +
      " — want us to alert you when more like these come up?";
  }

  function hideBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  }

  function showBanner(criteria, count) {
    if (banner) return;
    var host = document.querySelector(".lst-shell") || document.body;

    banner = document.createElement("div");
    banner.className = "save-nudge-banner";
    banner.setAttribute("role", "region");
    banner.setAttribute("aria-label", "Suggested saved search");
    banner.style.cssText =
      "display:flex;gap:14px;align-items:center;flex-wrap:wrap;" +
      "background:#fff7f7;border:1px solid #f2c9cf;border-left:4px solid #EA002A;" +
      "border-radius:8px;padding:14px 18px;margin:0 0 20px;" +
      "font-family:Raleway,Arial,sans-serif;";
    banner.innerHTML =
      '<p style="flex:1 1 260px;margin:0;font-size:.94rem;line-height:1.4;color:#1a1a1a;min-width:200px;">' +
        esc(summaryText(criteria, count)) +
      "</p>" +
      '<button type="button" class="save-nudge-cta" style="flex:0 0 auto;background:#EA002A;color:#fff;' +
        'border:none;border-radius:6px;padding:10px 18px;font-weight:700;font-size:.88rem;cursor:pointer;' +
        'white-space:nowrap;">Set up alerts</button>' +
      '<button type="button" class="save-nudge-dismiss" aria-label="Dismiss this suggestion"' +
        ' style="flex:0 0 auto;background:none;border:none;color:#999;font-size:1.35rem;' +
        'line-height:1;cursor:pointer;padding:2px 6px;">&times;</button>';

    host.insertBefore(banner, host.firstChild);

    banner.querySelector(".save-nudge-dismiss").addEventListener("click", function () {
      setDismissed();
      hideBanner();
    });
    banner.querySelector(".save-nudge-cta").addEventListener("click", function () {
      setDismissed(); // engaged -- no need to nag again
      hideBanner();
      if (window.SavedSearch && window.SavedSearch.promptSave) {
        window.SavedSearch.promptSave(function () { return criteria; }, null, {});
      }
    });

    if (window.gtag) {
      try { window.gtag("event", "save_nudge_shown", { favorites_count: count }); } catch (e) { /* no-op */ }
    }
  }

  function maybeNudge(list) {
    if (shown || dismissed()) return;
    if (!list || list.length < 2) return;
    if (!window.SavedSearch || !window.SavedSearch.list || !window.SavedSearch.promptSave) return;

    window.SavedSearch.list().then(function (searches) {
      if (searches && searches.length > 0) return; // already has one -- nothing to suggest

      fetch(listingsDataUrl(), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (payload) {
          var rows = (payload && (payload.listings || payload.rows || payload)) || [];
          var byMls = {};
          for (var i = 0; i < rows.length; i++) {
            if (rows[i] && rows[i].mls != null) byMls[String(rows[i].mls)] = rows[i];
          }
          var matched = [];
          for (var j = 0; j < list.length; j++) {
            if (byMls[list[j]]) matched.push(byMls[list[j]]);
          }
          if (matched.length < 2) return; // favorites resolved to <2 active rows (e.g. sold)
          shown = true;
          showBanner(deriveCriteria(matched), matched.length);
        })
        .catch(function () { /* Conv #74 -- feed fetch failure, no nudge */ });
    }).catch(function () { /* Conv #74 -- SavedSearch.list() failure, no nudge */ });
  }

  function init() {
    if (window.Favorites.onChange) window.Favorites.onChange(maybeNudge);
    if (window.Favorites.list) maybeNudge(window.Favorites.list());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
