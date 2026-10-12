/* recently-viewed.js — VOW Synthesis Ship #6 (2026-05-18)
 *
 * Records the visitor's listing-detail page views to localStorage and
 * renders a "Recently viewed" strip on browse surfaces.
 *
 * Architecture:
 *   - On every listing-detail page (active or sold), the script scrapes
 *     RealEstateListing JSON-LD and records {mls, street, city, price,
 *     photo, url, sold_state, viewed_at} to localStorage.
 *   - Capped at 12 items, deduplicated by MLS, sorted newest-first.
 *   - On browse surfaces (/listings/, /listings/discover/, future
 *     /listings/sold/), the script renders a strip into any element
 *     with id="lst-recently-viewed".
 *   - Hidden when no items (Convention #74 fail-safe).
 *
 * Storage key: lst-recently-viewed-v1 (versioned for future migration).
 */
(function() {
  "use strict";

  var STORAGE_KEY = "lst-recently-viewed-v1";
  var MAX_ITEMS = 12;

  /* ─────── Storage helpers ─────── */
  function load() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      var data = JSON.parse(raw);
      return Array.isArray(data) ? data : [];
    } catch (e) {
      return [];
    }
  }

  function save(items) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
    } catch (e) { /* quota exceeded or disabled — silent */ }
  }

  function clear() {
    try { localStorage.removeItem(STORAGE_KEY); } catch (e) {}
  }

  /* ─────── Record a viewed listing ─────── */
  function record(meta) {
    if (!meta || !meta.mls) return;
    var items = load();
    // Dedupe — remove any existing entry with same MLS.
    items = items.filter(function(x) { return x.mls !== meta.mls; });
    // Prepend new entry with fresh timestamp.
    items.unshift({
      mls:        String(meta.mls),
      street:     meta.street || "",
      city:       meta.city || "",
      price:      meta.price != null ? Number(meta.price) : null,
      photo:      meta.photo || "",
      url:        meta.url || location.pathname,
      sold_state: meta.sold_state || "active",
      viewed_at:  Date.now()
    });
    // Cap to MAX_ITEMS.
    if (items.length > MAX_ITEMS) items = items.slice(0, MAX_ITEMS);
    save(items);
  }

  /* ─────── Scrape current page's JSON-LD ─────── */
  function findListingJsonLd() {
    var scripts = document.querySelectorAll('script[type="application/ld+json"]');
    for (var i = 0; i < scripts.length; i++) {
      try {
        var data = JSON.parse(scripts[i].textContent);
        var items = Array.isArray(data)
          ? data
          : (data["@graph"] ? data["@graph"] : [data]);
        for (var j = 0; j < items.length; j++) {
          var t = items[j]["@type"];
          if (t === "RealEstateListing" ||
              (Array.isArray(t) && t.indexOf("RealEstateListing") !== -1)) {
            return items[j];
          }
        }
      } catch (e) { /* malformed JSON — skip */ }
    }
    return null;
  }

  function recordCurrentPage() {
    var listing = findListingJsonLd();
    if (!listing) return; // Not a listing-detail page — nothing to record.

    // Extract metadata from the JSON-LD blob.
    var mls = listing.mlsNumber || listing.identifier ||
              (listing.offers && listing.offers.identifier) || "";
    if (!mls) return;

    var street = "", city = "";
    var addr = listing.address;
    if (addr && typeof addr === "object") {
      street = addr.streetAddress || "";
      city   = addr.addressLocality || "";
    } else if (listing.name) {
      street = listing.name; // fallback
    }

    var price = null;
    if (listing.offers && listing.offers.price != null) {
      price = Number(listing.offers.price);
    } else if (listing.price != null) {
      price = Number(listing.price);
    }

    var photo = "";
    if (listing.image) {
      photo = Array.isArray(listing.image) ? listing.image[0] : listing.image;
      // Normalize: if image is an object with .url, use that.
      if (photo && typeof photo === "object" && photo.url) photo = photo.url;
    }

    // Detect sold-state from URL (sold-detail pages live at /listings/sold/detail.html).
    var sold_state = location.pathname.indexOf("/listings/sold/") === 0
      ? "sold" : "active";

    record({
      mls:        mls,
      street:     street,
      city:       city,
      price:      price,
      photo:      photo,
      url:        location.pathname + location.search,
      sold_state: sold_state
    });
  }

  /* ─────── Render the strip ─────── */
  function fmtPrice(n) {
    if (n == null || isNaN(n)) return "—";
    if (n >= 1000000) return "$" + (n / 1000000).toFixed(2).replace(/\.?0+$/, "") + "M";
    if (n >= 1000) return "$" + Math.round(n / 1000) + "K";
    return "$" + Math.round(n).toLocaleString();
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function renderTo(elementId) {
    var el = typeof elementId === "string"
      ? document.getElementById(elementId)
      : elementId;
    if (!el) return;

    var items = load();
    if (items.length === 0) {
      el.style.display = "none";
      return;
    }

    // Limit to first 8 for visual layout (2-3 rows on desktop).
    var visible = items.slice(0, 8);

    var cards = visible.map(function(r) {
      var photoHtml = r.photo
        ? '<img src="' + esc(r.photo) + '" alt="' + esc(r.street) + '" loading="lazy">'
        : '<div class="lst-rv-card-noimg"></div>';
      var priceBadge = r.sold_state === "sold"
        ? '<span class="lst-rv-card-badge lst-rv-card-badge-sold">SOLD</span>'
        : '';
      return ''
        + '<a href="' + esc(r.url) + '" class="lst-rv-card">'
        + '<div class="lst-rv-card-img">' + photoHtml + priceBadge + '</div>'
        + '<div class="lst-rv-card-body">'
        + '<p class="lst-rv-card-price">' + esc(fmtPrice(r.price)) + '</p>'
        + '<p class="lst-rv-card-addr">' + esc(r.street) + (r.city ? ', ' + esc(r.city) : '') + '</p>'
        + '</div>'
        + '</a>';
    }).join("");

    el.innerHTML = ''
      + '<section class="lst-rv-section">'
      + '  <div class="lst-rv-inner">'
      + '    <div class="lst-rv-header">'
      + '      <p class="lst-rv-eyebrow">Recently viewed</p>'
      + '      <h2>Pick up where you left off</h2>'
      + '      <button type="button" class="lst-rv-clear" data-action="clear">Clear history</button>'
      + '    </div>'
      + '    <div class="lst-rv-grid">' + cards + '</div>'
      + '  </div>'
      + '</section>';
    el.style.display = "";

    // Wire up the clear button.
    var btn = el.querySelector('[data-action="clear"]');
    if (btn) {
      btn.addEventListener("click", function(e) {
        e.preventDefault();
        clear();
        el.innerHTML = "";
        el.style.display = "none";
      });
    }
  }

  /* ─────── Public API + auto-record ─────── */
  window.RecentlyViewed = {
    record:   record,
    load:     load,
    clear:    clear,
    renderTo: renderTo
  };

  // Auto-record on DOMContentLoaded if we're on a listing-detail page.
  if (document.readyState !== "loading") {
    recordCurrentPage();
  } else {
    document.addEventListener("DOMContentLoaded", recordCurrentPage);
  }
})();
