/**
 * Sold-listing-search — filter / sort / map / render.
 *
 * Loaded by /listings/sold/index.html. Waits for the VOW gate to clear
 * (via the `vow:unlocked` event) before fetching data.json.
 *
 * Data source: /listings/sold/data.json (emitted by ddf-generate-pages.py
 * → emit_sold_data() from tools/idx-cache/sold-listings.json, refreshed
 * each nightly cycle).
 *
 * Redesigned 2026-08-06 (Mike: "too complicated to use... maybe even a
 * map-based search"). What changed from the original #134 canary:
 *   - Map is always visible beside the cards on desktop (was: List/Map
 *     toggle, map hidden by default) — see initSoldMap().
 *   - Filters wire IMMEDIATELY after data.json parses; the authenticated
 *     price merge (mergePricesFromRls) now runs in the BACKGROUND and
 *     patches already-rendered cards/pins in place on resolve, instead of
 *     gating every filter click on ~13 parallel PostgREST pages landing
 *     first (see fetchData()).
 *   - "Sold/list ratio" filter removed entirely (Mike's call — it silently
 *     emptied the grid for anyone without a live session, since sa_ratio
 *     only exists post-merge). The per-card ratio text still renders.
 *   - "Multi-fam" ptype chip removed (matched zero rows — the feed has no
 *     "Multi-Family" value; real values are Residential/Lots/Commercial).
 *   - City filter renamed Area and made INCLUSIVE: selecting a region now
 *     matches its major-centre towns too (r.dropdown_key === sel ||
 *     r.region === sel), instead of the old exclusive dropdown_key-only
 *     match. Requires the generator to emit `region` on each row — see
 *     Convention #74 fallback note on AREA_INCLUSIVE below.
 *   - Smart search bar (2026-08-06 night, Joe Whiffen feedback): free-text
 *     search across MLS#, street, city, and area/municipality (region +
 *     dropdown_key). Tokenized AND match — "elizabeth gander" narrows to
 *     rows matching BOTH tokens somewhere in the haystack. See state.q /
 *     rowMatchesQuery() / wireSearchInput().
 *   - "Search this area" (Decision G, previously stubbed on the active
 *     shell) is finished here: pan/zoom → debounced button reveal → click
 *     captures the viewport as a lat/lng box filter.
 *   - Pin ↔ card sync (click pin → scroll+flash the card; hover a card →
 *     highlight its pin) ported from js/listings-index.js.
 *   - Every new DOM hook is null-guarded so this file keeps working,
 *     grid-only, on the ~132 per-city rollup pages that won't carry the
 *     new shell markup until their next nightly regen (Convention #173 —
 *     no forced regen; Convention #74 — a missing element is a no-op,
 *     never a throw).
 *
 * Pagination is critical because the data feed is several MB across 12K+
 * rows; rendering all at once would lock the browser. 60-per-page is what
 * /listings/discover/ uses too.
 */

/* Listing dates are Newfoundland calendar days ("YYYY-MM-DD", rendered by the
 * generator with tools/nl_dates.py). new Date("YYYY-MM-DD") parses as UTC
 * midnight, which is the previous evening in NL (UTC-2:30 / -3:30), so every
 * sold/list date showed one day early (site audit 2026-09-28, 342 Conception
 * Bay Hwy "Sold Sep 24" for a 09-25 close). Format the calendar day as-is.
 * Same body in js/sold-listings.js, sold-detail.js, listings-index.js and
 * agent-sales.js (redefining it on a page that loads two of them is harmless). */
function turnerCalDate(s, opts) {
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s || ""));
  if (!m) return "";
  var o = { timeZone: "UTC" };
  for (var k in (opts || {})) o[k] = opts[k];
  return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-CA", o);
}

(function () {
  "use strict";

  // Per-city sold rollups override the data URL via inline script
  // (e.g. listings/sold/gander/index.html sets window.SOLD_DATA_URL
  // = "/listings/sold/gander/data.json" before this script loads).
  // Avalon/Goose Bay additionally set SOLD_CITY_SLUG/SOLD_CITY_LABEL —
  // opportunistic, read where present, never required.
  var DATA_URL = (typeof window !== "undefined" && window.SOLD_DATA_URL)
    ? window.SOLD_DATA_URL
    : "/listings/sold/data.json";
  var IS_CITY_PAGE = (typeof window !== "undefined" && !!window.SOLD_DATA_URL);
  var CITY_LABEL = (typeof window !== "undefined" && window.SOLD_CITY_LABEL) || "";
  var PAGE_SIZE = 60;
  // Above this many results, pin LABELS fall back to a plain dot (no price
  // chip) for render perf -- the all-time/all-types view can be 12k+ rows,
  // and an L.divIcon with text markup per marker gets expensive at that
  // scale even inside a chunked-loading cluster. Popups still show price
  // once merged, regardless of count (rendered on click, not up front).
  var MARKER_PRICE_THRESHOLD = 4000;

  var allRows = [];
  var filtered = [];
  // Live map-move filtering (2026-08-06 late night, Mike: "can we have
  // the listings update as the map moves around?"). pinRows is the
  // bounds-FREE row set -- rebuildPins() reads this, never `filtered`,
  // so panning the map can never cull a marker off it. See
  // recomputeFilters() + applyBoundsOnly().
  var pinRows = [];
  // Guards every programmatic map move (initial fitBounds, Recenter,
  // area-select refits) so its own moveend event is never misread as a
  // user pan/zoom and can't overwrite state.bounds. See progMoveGuard().
  var progMove = false;
  var renderedCount = 0;
  var dropdownOptions = null;  // { major_centres: [...], regions: [...], threshold, total_cities_collapsed }

  var state = {
    recency: "2y",   // 3m / 6m / 1y / 2y
    ptype:   "",     // "" = All / Residential / Lots / Commercial
    area:    "",     // matches dropdown_key (major centre) OR region (inclusive, see AREA below)
    sort:    "date-desc",
    // Per-agent widget click-through filters (Ship 3, 2026-05-17).
    team:    "",     // slug like "turner-realty-team" or "dynamic-duo"
    agent:   "",     // slug like "crystal-hynes"
    // Search-this-area bounds box (2026-08-06). {south, west, north, east}
    // or null. Cleared by an area-select change or Clear all -- NOT by
    // further panning, so the filter persists until deliberately released.
    bounds:  null,
    // Smart search query (2026-08-06 night). Free text -- tokenized and
    // matched against MLS#/street/city/region/dropdown_key in
    // rowMatchesQuery(). Empty string = no filter.
    q:       "",
  };

  // ───────── URL filter readers (Ship 3, 2026-05-17) ─────────
  function readUrlFilters() {
    try {
      var sp = new URLSearchParams(window.location.search);
      var team = (sp.get("team") || "").trim().toLowerCase();
      var agent = (sp.get("agent") || "").trim().toLowerCase();
      var q = (sp.get("q") || "").trim();
      if (team) state.team = team;
      if (agent) state.agent = agent;
      if (q) {
        state.q = q;
        var qInput = document.getElementById("sold-search-input");
        if (qInput) qInput.value = q;
      }
    } catch (e) {
      // URLSearchParams unavailable on very old browsers — skip silently.
    }
  }

  // Map recency code → days
  var RECENCY_DAYS = { "3m": 90, "6m": 180, "1y": 365, "2y": 730 };

  // ───────── Boot: wait for VOW gate then fetch ─────────
  // Two-path init to avoid the script-load-order race banked 2026-05-08 —
  // see the identical comment in earlier revisions of this file for the
  // full PATH A / PATH B rationale. Unchanged by this redesign.
  function siteIdFromHost() {
    var site = window.TURNER_SITE;
    var region = site && window.TURNER_REGIONS && window.TURNER_REGIONS[site];
    if (region && region.site_id) return region.site_id;
    var h = window.location.hostname || "";
    if (h.indexOf("avalonrealestate") !== -1) return "avalonrealestate";
    if (h.indexOf("goosebayrealestate") !== -1) return "goosebayrealestate";
    return "realestategander";
  }
  function fireFunnelEvent(eventName) {
    try {
      var body = JSON.stringify({
        event: eventName, email: "",
        site: siteIdFromHost(), path: window.location.pathname
      });
      var endpoint = (window.TURNER_API_ORIGIN || "https://realestategander.com") + "/.netlify/functions/vow-funnel-event";
      if (navigator.sendBeacon) {
        navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      } else {
        fetch(endpoint, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: body, keepalive: true, mode: "cors"
        }).catch(function () {});
      }
    } catch (e) { /* a funnel beacon must never break the unlocked page */ }
  }

  var dataFetched = false;

  // 2026-09-17 (Mobile+iPad review B6): sold listings are now browsable
  // WITHOUT signing in first -- addresses, photos, sold dates, property
  // type, and beds/baths render immediately for every visitor; only the
  // sold PRICE stays gated per-card (see renderCard()'s priceLocked below,
  // and CSS-independent -- js/vow-gate.js no longer blocks #page). Data
  // therefore loads unconditionally at boot instead of waiting for the
  // VOW gate to clear first.
  function boot() {
    if (dataFetched) return;
    dataFetched = true;
    fetchData();
  }
  boot();

  // A real sign-in (the visitor tapped a locked price -> js/vow-gate.js's
  // on-demand gate -> TurnerAuth SIGNED_IN -> this event) means prices can
  // now be fetched for real. Data itself is already loaded by boot() above
  // (or is about to be -- see the fetchData()/mergePricesFromRls wiring),
  // so this listener's only job is to re-run the price merge and patch
  // whatever's already on screen, never to re-fetch data.json.
  document.addEventListener("vow:unlocked", function () {
    fireFunnelEvent("unlock");
    if (!allRows.length) { boot(); return; }
    mergePricesFromRls(allRows).then(function (didMerge) {
      if (didMerge) patchAfterMerge();
    });
  });

  // ───────── Topbar height measurement (mobile map positioning) ─────────
  // Same fix as the active discovery shell (listings-index.js:149-165,
  // caught live 2026-04-27): the topbar can wrap to 2-3 rows on narrow
  // viewports, so a hardcoded height leaves a gap above the fullscreen
  // mobile map. Measures the REAL .topbar element and writes a CSS var
  // sold-discover.css reads with a fallback chain (--sold-topbar-h, then
  // this page's own pre-existing --topbar-h token, then 88px).
  function setSoldTopbarHeightVar() {
    var topbar = document.querySelector(".topbar");
    if (!topbar) return;
    var h = topbar.getBoundingClientRect().height;
    if (h > 0) {
      document.documentElement.style.setProperty("--sold-topbar-h", Math.round(h) + "px");
    }
  }
  if (document.readyState === "complete") {
    setSoldTopbarHeightVar();
  } else {
    window.addEventListener("load", setSoldTopbarHeightVar, { once: true });
  }
  window.addEventListener("resize", setSoldTopbarHeightVar);
  window.addEventListener("orientationchange", function () {
    setTimeout(setSoldTopbarHeightVar, 100);
  });

  // ───────── Sold map (redesigned 2026-08-06) ─────────
  // Config from window.SOLD_MARKET (set inline in index.html, per-site
  // bounds) with a Gander-centred fallback so a page missing that script
  // (an old, un-regenerated city page) still gets a sane default rather
  // than throwing. Gated on the NEW shell marker (.sold-map-pane) so an
  // old city page — which still has a bare #sold-map div with none of this
  // redesign's CSS — never pays for a Leaflet init that would draw into an
  // unstyled, unsized box (Convention #74: grid-only degradation, no throw,
  // and no wasted work either).
  var MARKET = (typeof window !== "undefined" && window.SOLD_MARKET) || {
    bounds: [[48.4, -55.5], [49.9, -53.0]],
    cage:   [[47.3, -56.0], [50.0, -52.5]],
    minZoom: 7, maxZoom: 18, viscosity: 0.6
  };
  var soldMap = null, soldCluster = null, soldMapReady = false, mapView = false;

  function hasNewShell() {
    return !!document.querySelector(".sold-map-pane");
  }

  function soldPinIcon(r, showPrice) {
    if (showPrice) {
      return L.divIcon({
        className: "sold-pin",
        html: '<span class="sold-pin-price">' + esc(fmtPinPrice(r.close_price)) + "</span>",
        iconSize: null,
        iconAnchor: [22, 12],
      });
    }
    return L.divIcon({
      className: "sold-pin",
      html: '<span class="sold-pin-dot"></span>',
      iconSize: [14, 14],
      iconAnchor: [7, 7],
    });
  }

  function fmtPinPrice(n) {
    if (n == null) return "Sold";
    if (n >= 1000000) return "$" + (n / 1000000).toFixed(1).replace(/\.0$/, "") + "M";
    return "$" + Math.round(n / 1000) + "k";
  }

  function soldPopupHtml(r) {
    var addr = esc((r.street || "—") + (r.city ? ", " + r.city : ""));
    var soldDate = r.sold_date
      ? turnerCalDate(r.sold_date, { year: "numeric", month: "short", day: "numeric" })
      : "";
    var href = "/listings/sold/detail.html?mls=" + encodeURIComponent(r.mls || "");
    // Rule 5(k): the sold price appears in the popup ONLY once the
    // authenticated merge has landed (r.close_price is null until then).
    // The address/date/link are ungated content and always safe to show.
    var priceLine = r.close_price != null
      ? '<span class="sold-pin-popup-sub">' + esc(fmtPinPrice(r.close_price)) + "</span>"
      : "";
    return '<div class="sold-pin-popup"><strong>' + addr + "</strong>" +
      (soldDate ? '<span class="sold-pin-popup-sub">Sold ' + esc(soldDate) + "</span>" : "") +
      priceLine +
      '<a href="' + href + '">View sold details &rarr;</a></div>';
  }

  var mlsToMarker = {};

  function rebuildPins() {
    if (!soldCluster) return;
    soldCluster.clearLayers();
    mlsToMarker = {};
    // pinRows (bounds-free), not filtered (cards, bounds-aware) -- see
    // the module-state comment above.
    var showPrice = pricesLoaded && pinRows.length <= MARKER_PRICE_THRESHOLD;
    var markers = [];
    for (var i = 0; i < pinRows.length; i++) {
      var r = pinRows[i];
      if (r.lat == null || r.lng == null) continue;
      var marker = L.marker([r.lat, r.lng], { icon: soldPinIcon(r, showPrice), riseOnHover: true });
      marker.bindPopup(soldPopupHtml(r), { closeButton: true, autoPan: true });
      var mlsKey = String(r.mls);
      marker.on("click", function (mk) {
        return function () { scrollToCard(mk); };
      }(mlsKey));
      markers.push(marker);
      mlsToMarker[mlsKey] = marker;
    }
    if (soldCluster.addLayers) soldCluster.addLayers(markers);
    else markers.forEach(function (m) { soldCluster.addLayer(m); });
  }

  // Live map-move filtering (2026-08-06 late night). See the module-state
  // comment above `var progMove` for what this guards against. Leaflet
  // fires moveend even for {animate:false} fits, so the `once` listener
  // catches the common case; the 800ms timeout is the backstop for a
  // true no-op fit (map already exactly at the target) where moveend may
  // never fire at all.
  //
  // ORDER MATTERS (found live 2026-08-06, hotfix same session): the
  // cleanup `.once("moveend", clear)` listener MUST be registered AFTER
  // fn() runs, not before. Registering it first silently turned every
  // guarded fitBounds() call into a no-op whenever the map wasn't
  // perfectly idle (i.e. Recenter after any prior pan) -- some Leaflet
  // internal moveend/animation bookkeeping gets confused by a new
  // listener arriving mid-flight. progMove is still set to true BEFORE
  // fn() runs, so the auto-apply handler correctly ignores any moveend
  // fn() triggers regardless of registration order -- only the CLEANUP
  // listener's timing changed, not the guard's coverage.
  function progMoveGuard(fn) {
    progMove = true;
    var cleared = false;
    function clear() { if (!cleared) { cleared = true; progMove = false; } }
    fn();
    if (soldMap) soldMap.once("moveend", clear);
    setTimeout(clear, 800);
  }

  function renderMap(opts) {
    if (!soldMapReady || !soldCluster) return;
    rebuildPins();
    // Frame: per-city page, an area filter, or the search-this-area box
    // fits to the markers; the unfiltered fleet view keeps the market's
    // home viewport. `opts.fit` forces a fit even without those (used
    // right after an area-select change).
    // state.bounds deliberately excluded from hasFilter (2026-08-06 late
    // night): once the user has framed the map by panning, a chip/area
    // click must not yank the viewport away underneath them. Panning is
    // now the ONE thing that's allowed to move the map after load.
    var hasFilter = state.area || state.ptype || state.team ||
                    state.agent || (state.recency !== "2y");
    var shouldFit = !state.bounds && ((opts && opts.fit) || IS_CITY_PAGE || hasFilter);
    if (shouldFit && mlsToMarker && Object.keys(mlsToMarker).length) {
      progMoveGuard(function () {
        try { soldMap.fitBounds(soldCluster.getBounds().pad(0.15), { animate: false }); } catch (e) { /* no-op */ }
      });
    }
  }

  function initSoldMap() {
    if (soldMapReady || typeof L === "undefined" || !hasNewShell()) return;
    var el = document.getElementById("sold-map");
    if (!el) return;
    soldMapReady = true;

    // 2026-08-07 -- un-caged, same fix + same reasoning as Round 2 on the
    // active-listings map (Mike: "the map is still sticky"): a finite
    // maxBounds cage recreates the identical stuck-pan bug the moment
    // viewport-at-current-zoom exceeds it, which is inherent to a map
    // this size in a real browser window -- no cage value fixes that,
    // only removing it does. MARKET.cage/viscosity are no longer
    // consumed (kept in the config shape for now, simply unread).
    var fitB = MARKET.bounds;
    var map = L.map(el, {
      zoomControl: true,
      scrollWheelZoom: true,
      minZoom: MARKET.minZoom || 7,
      maxZoom: MARKET.maxZoom || 18,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }).addTo(map);
    soldMap = map;
    progMoveGuard(function () { map.fitBounds(L.latLngBounds(fitB), { animate: false }); });
    window.soldMap = map;
    // Recenter also releases any active viewport filter (2026-08-06 late
    // night) -- it's the explicit "show me everything again" gesture.
    window.soldMapRecenter = function () {
      progMoveGuard(function () { map.fitBounds(L.latLngBounds(fitB), { animate: false }); });
      if (state.bounds) { state.bounds = null; applyAndRender(); }
    };

    soldCluster = (typeof L.markerClusterGroup === "function")
      ? L.markerClusterGroup({ chunkedLoading: true, showCoverageOnHover: false, maxClusterRadius: 50 })
      : L.layerGroup();
    map.addLayer(soldCluster);

    if (allRows.length) renderMap();

    // ── Live map-move filtering (2026-08-06 late night) -- replaces the
    // Decision G manual "Search this area" button with Zillow-style
    // always-on auto-apply. progMove guards out every programmatic move
    // (the initial fit above, Recenter). Only recomputes cards/count/
    // banner (applyBoundsOnly) -- rebuildPins() is deliberately NOT
    // called, since pinRows never depends on state.bounds, so there is
    // nothing for a pan to change there and no fit-loop is possible. ──
    var moveTimer = null;
    map.on("moveend zoomend", function () {
      if (progMove) return;
      clearTimeout(moveTimer);
      moveTimer = setTimeout(function () {
        var b = map.getBounds();
        // Defensive fail-safe (Convention #74), banked 2026-09-17: a
        // #sold-map container that still has zero/unsettled size at the
        // moment Leaflet computes a programmatic fit can yield a
        // degenerate, zero-area box here (south===north and/or
        // west===east) once the container's real size is later resolved
        // (e.g. by invalidateSize()) and fires its own moveend. No row's
        // lat/lng can ever equal that exact box, so latching it into
        // state.bounds silently emptied the whole grid on city-rollup
        // pages (IS_CITY_PAGE=true, which always fits on load). A real
        // user pan/zoom always produces a non-degenerate box, so this
        // never masks a genuine gesture.
        if (b.getSouth() === b.getNorth() || b.getWest() === b.getEast()) return;
        state.bounds = {
          south: b.getSouth(), west: b.getWest(),
          north: b.getNorth(), east: b.getEast(),
        };
        applyBoundsOnly();
      }, 300);
    });

    // ── Mobile overlay pills (Exit / Filters) + Recenter ──
    var exitBtn = document.querySelector(".sold-map-exit");
    var filtersBtn = document.querySelector(".sold-map-filters");
    var recenterBtn = document.querySelector(".sold-map-recenter");
    if (exitBtn) exitBtn.addEventListener("click", function () { setMobileMapView(false); });
    if (filtersBtn) filtersBtn.addEventListener("click", openFilterDrawer);
    if (recenterBtn) recenterBtn.addEventListener("click", function () {
      if (typeof window.soldMapRecenter === "function") window.soldMapRecenter();
    });

    setTimeout(function () { if (soldMap) soldMap.invalidateSize(); }, 60);
  }

  // ── Mobile fullscreen map toggle (single button, replaces the old
  // 2-chip List/Map toggle -- desktop no longer needs one at all since
  // both panes are always visible there; CSS hides .sold-view-btn there). ──
  function setMobileMapView(on) {
    mapView = !!on;
    var shell = document.getElementById("sold-shell");
    var btn = document.getElementById("sold-view-btn");
    if (shell) shell.classList.toggle("sold-shell--map-view", mapView);
    if (btn) {
      btn.setAttribute("aria-pressed", mapView ? "true" : "false");
      btn.setAttribute("aria-label", mapView ? "Switch to list view" : "Switch to map view");
    }
    if (mapView) {
      renderMap();
      setTimeout(function () { if (soldMap) soldMap.invalidateSize(); }, 50);
    }
  }

  function wireViewToggle() {
    var btn = document.getElementById("sold-view-btn");
    if (btn) btn.addEventListener("click", function () { setMobileMapView(!mapView); });
  }

  // ── Mobile filter-rail collapse (#134 mobile fix, 2026-05-29, unchanged
  // structurally by this redesign) ──
  function openFilterDrawer() {
    var rail = document.querySelector(".filter-rail");
    var btn = document.getElementById("filter-toggle");
    if (!rail) return;
    rail.classList.add("open");
    if (btn) btn.setAttribute("aria-expanded", "true");
  }
  function setupFilterToggle() {
    var btn = document.getElementById("filter-toggle");
    var rail = document.querySelector(".filter-rail");
    if (!btn || !rail) return;
    btn.addEventListener("click", function () {
      var open = rail.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      var caret = btn.querySelector(".filter-toggle-caret");
      if (caret) caret.style.transform = open ? "rotate(180deg)" : "none";
    });
    updateFilterToggleLabel();
  }

  function updateFilterToggleLabel() {
    var label = document.getElementById("filter-toggle-label");
    if (!label) return;
    var n = 0;
    if (state.recency && state.recency !== "2y") n++;
    if (state.ptype) n++;
    if (state.area) n++;
    if (state.team) n++;
    if (state.agent) n++;
    if (state.bounds) n++;
    label.textContent = n ? ("Filters (" + n + ")") : "Filters";
  }

  // ───────── Sold prices via RLS (VOW enforcement, 2026-07-28) ─────────
  // Unchanged mechanism from the pre-redesign file — close_price/sa_ratio
  // are the two fields CREA Rule 5(k) requires behind registration, and
  // they arrive from the RLS-gated `viewpoint_prices` table. What CHANGED
  // 2026-08-06: this used to gate wireFilters() itself (a dead-interaction
  // window at boot); it now runs purely in the background and patches
  // whatever's already on screen when it resolves — see patchAfterMerge().
  var pricesLoaded = false;
  var PRICE_PAGE = 1000;

  function _applyPrices(rows, byMls) {
    var filled = 0;
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      if (r.close_price == null) {
        var p = byMls[String(r.mls)];
        if (p != null) { r.close_price = p; filled++; }
      }
      if (r.sa_ratio == null && r.close_price != null && r.list_price) {
        r.sa_ratio = Math.round((100 * r.close_price / r.list_price) * 10) / 10;
      }
    }
    return filled;
  }

  function mergePricesFromRls(rows) {
    var c = (window.TurnerAuth && window.TurnerAuth._client) || null;
    if (!c) return Promise.resolve(false);
    var byMls = Object.create(null);

    function readPage(from) {
      return c.from("viewpoint_prices").select("mls,close_price")
              .range(from, from + PRICE_PAGE - 1)
              .then(function (res) {
                if (res.error) throw res.error;
                var d = res.data || [];
                for (var i = 0; i < d.length; i++) {
                  if (d[i].close_price != null) {
                    byMls[String(d[i].mls)] = Number(d[i].close_price);
                  }
                }
                return d.length;
              });
    }

    return c.from("viewpoint_prices").select("mls", { count: "exact", head: true })
      .then(function (res) {
        var total = (res && !res.error) ? res.count : null;
        if (total == null) {
          var walk = function (from) {
            return readPage(from).then(function (n) {
              if (n === PRICE_PAGE) return walk(from + PRICE_PAGE);
            });
          };
          return walk(0);
        }
        var jobs = [];
        for (var off = 0; off < total; off += PRICE_PAGE) jobs.push(readPage(off));
        return Promise.all(jobs);
      })
      .then(function () {
        _applyPrices(rows, byMls);
        pricesLoaded = true;
        return true;
      })
      .catch(function (err) {
        console.warn("sold-listings: price merge failed:", err && err.message);
        return false;
      });
  }

  // Patch already-rendered cards + pins after the background merge lands —
  // no grid rebuild, no scroll-position reset. `filtered` and `allRows`
  // share object references (mergePricesFromRls mutates in place), so a
  // fresh renderCard(row) call for each on-screen card is sufficient.
  function patchAfterMerge() {
    var grid = document.getElementById("card-grid");
    if (grid) {
      var byMls = {};
      for (var i = 0; i < filtered.length; i++) byMls[String(filtered[i].mls)] = filtered[i];
      var links = grid.querySelectorAll(".sold-card-link[data-mls]");
      for (var j = 0; j < links.length; j++) {
        var link = links[j];
        var row = byMls[link.getAttribute("data-mls")];
        if (row) link.outerHTML = renderCard(row);
      }
    }
    if (soldMapReady) renderMap();
  }

  // ───────── On-demand VOW gate open (B6, 2026-09-17) ─────────
  // A locked price ("Sign in to see sold price") is the tap target that
  // opens js/vow-gate.js's sign-in modal -- see renderCard() below. Only
  // ever wired to a button that IS genuinely locked (isAuthedForPrices()
  // false at render time), so clearing a stale legacy token here is safe:
  // a valid one would already have unlocked the row and no such button
  // would exist to click. Falls back to a reload if vow-gate.js somehow
  // failed to load (Convention #74) -- previously the ONLY behavior this
  // handler had, kept as the defensive floor.
  window.__soldOpenVowGate = function (ev) {
    if (ev && ev.preventDefault) { ev.preventDefault(); ev.stopPropagation(); }
    try { localStorage.removeItem("vow_gate_v1"); } catch (e) {}
    if (window.TurnerVowGate && typeof window.TurnerVowGate.open === "function") {
      window.TurnerVowGate.open();
    } else {
      window.location.reload();
    }
  };

  // Mirrors js/vow-gate.js's own dual auth check (Supabase session OR a
  // still-valid legacy localStorage token) so a card's price-locked state
  // always agrees with whether the gate would actually unlock right now.
  function isAuthedForPrices() {
    try {
      if (window.TurnerAuth && window.TurnerAuth.getSession) {
        var s = window.TurnerAuth.getSession();
        if (s && s.user) return true;
      }
    } catch (e) { /* fall through to legacy check */ }
    try {
      var raw = localStorage.getItem("vow_gate_v1");
      if (raw) {
        var parsed = JSON.parse(raw);
        if (parsed && parsed.passed === true) return true;
      }
    } catch (e) { /* private browsing or quota -- treat as signed out */ }
    return false;
  }

  function fetchData() {
    var meta = document.getElementById("meta-strip");
    if (meta) meta.textContent = "Loading sold listings…";

    (window.TurnerAuth && window.TurnerAuth.soldFetch ? window.TurnerAuth.soldFetch : window.fetch.bind(window))(DATA_URL)
      .then(function (resp) {
        if (resp.status === 401) {
          // Site review item 3: sold listings are for registered users only.
          dataFetched = false;
          if (meta) meta.textContent = "Sold listings are available to registered users. Sign in to see them.";
          if (window.TurnerVowGate && window.TurnerVowGate.open) window.TurnerVowGate.open();
          throw { signInRequired: true };
        }
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        return resp.json();
      })
      .then(function (payload) {
        allRows = payload.rows || [];
        dropdownOptions = payload.dropdown || null;
        if (meta) {
          var fetched = payload.generated_at ? new Date(payload.generated_at).toLocaleDateString() : "today";
          meta.textContent = allRows.length.toLocaleString() +
            " sold listings (NLAR MLS®) · refreshed " + fetched;
        }
        // Decoupled from the price merge (2026-08-06): filters are usable
        // the instant data lands, not after ~13 parallel PostgREST pages.
        populateAreaOptions();
        wireFilters();
        readUrlFilters();
        renderActiveFilterBanner();
        applyAndRender();
        initSoldMap();
        // Price merge runs in the BACKGROUND; patches what's already on
        // screen when (if) it resolves. 2026-09-17 (B6): this now runs for
        // EVERY visitor (data loads before sign-in), so it waits for
        // TurnerAuth.ready first -- calling the RLS-gated query before the
        // SDK has resolved the current session would read as "no session"
        // even for a genuinely signed-in returning visitor, showing them a
        // locked price for a moment they shouldn't see one. RLS itself
        // (table `viewpoint_prices`, policy scoped to role `authenticated`)
        // already guarantees an anonymous call here returns zero rows --
        // this wait is about correctness for authenticated visitors, not
        // about data safety, which was never in question.
        var authReady = (window.TurnerAuth && window.TurnerAuth.ready)
          ? window.TurnerAuth.ready : Promise.resolve();
        authReady.then(function () {
          mergePricesFromRls(allRows).then(function (didMerge) {
            if (didMerge) patchAfterMerge();
          });
        });
      })
      .catch(function (err) {
        if (err && err.signInRequired) return;
        console.error("sold-listings: data fetch failed:", err);
        if (meta) meta.textContent = "Could not load sold listings. Try refreshing.";
      });
  }

  // ───────── Populate the Area filter from data ─────────
  //
  // 2026-08-06 rework — INCLUSIVE region matching. The generator emits:
  //
  //   payload.dropdown = {
  //     major_centres: [{ key: "St. John's", count: 3378 }, ...],
  //     regions:       [{ key: "Avalon Peninsula", count: 1633 }, ...],
  //     threshold: 50, total_cities_collapsed: 870
  //   }
  //
  // Every row's dropdown_key is EITHER its own major-centre name OR its
  // region name (never both) — that part is unchanged. What's new: rows
  // also carry `region` directly (added to SLIM_SOLD_FIELDS 2026-08-06),
  // so picking a REGION now matches every row whose region equals it,
  // major-centre rows included — see rowMatchesArea() below. Rows from a
  // feed that hasn't regenerated since this shipped simply lack `region`
  // (undefined), which degrades to the OLD exclusive behaviour for that
  // row until the next nightly — never an error (Convention #74).
  //
  // On a per-city page (payload has no `dropdown`), the whole Area group
  // is hidden — there's nothing to pick from a single-city feed.
  function populateAreaOptions() {
    var group = document.getElementById("area-group");
    var sel = document.getElementById("area-select");
    if (!sel) return;

    if (!dropdownOptions || !dropdownOptions.major_centres || !dropdownOptions.regions) {
      if (group) group.hidden = true;
      // Legacy fallback — older data.json without a dropdown payload at all.
      var counts = {};
      for (var k = 0; k < allRows.length; k++) {
        var c = allRows[k].city || "";
        if (!c) continue;
        counts[c] = (counts[c] || 0) + 1;
      }
      var entries = Object.keys(counts).sort().map(function (city) {
        return { city: city, count: counts[city] };
      });
      var fallbackHtml = '<option value="">All cities (' + allRows.length.toLocaleString() + ')</option>';
      for (var n = 0; n < entries.length; n++) {
        fallbackHtml += '<option value="' + esc(entries[n].city) + '">' +
                esc(entries[n].city) + " (" + entries[n].count + ")</option>";
      }
      sel.innerHTML = fallbackHtml;
      return;
    }

    if (group) group.hidden = false;
    var html = '<option value="">All areas (' + allRows.length.toLocaleString() + ')</option>';
    var majors = dropdownOptions.major_centres || [];
    var regions = dropdownOptions.regions || [];

    if (majors.length) {
      html += '<optgroup label="Major centres">';
      for (var i = 0; i < majors.length; i++) {
        html += '<option value="' + esc(majors[i].key) + '">' +
                esc(majors[i].key) + " (" + majors[i].count + ")</option>";
      }
      html += "</optgroup>";
    }
    if (regions.length) {
      html += '<optgroup label="Regions (includes their major centres)">';
      for (var j = 0; j < regions.length; j++) {
        html += '<option value="' + esc(regions[j].key) + '">' +
                esc(regions[j].key) + " (" + regions[j].count + "+)</option>";
      }
      html += "</optgroup>";
    }
    sel.innerHTML = html;
  }

  // Inclusive area match: `sel` can be a major-centre name (matches only
  // that town, via dropdown_key) or a region name (matches every row whose
  // dropdown_key OR region equals it — so the region's major centres are
  // included). See populateAreaOptions() comment for the full rationale.
  function rowMatchesArea(r, sel) {
    if (!sel) return true;
    var key = r.dropdown_key || r.city || "";
    if (key === sel) return true;
    return (r.region || "") === sel;
  }

  // Smart search (2026-08-06 night, Joe Whiffen: "search sold listings by
  // address/street/area/municipality"). Tokenized-AND substring match --
  // every token must appear somewhere in the row's haystack, so "elizabeth
  // gander" correctly narrows to rows matching BOTH, not just one.
  function rowMatchesQuery(r, tokens) {
    if (!tokens || !tokens.length) return true;
    var haystack = (
      (r.mls || "") + " " +
      (r.street || "") + " " +
      (r.city || "") + " " +
      (r.region || "") + " " +
      (r.dropdown_key || "")
    ).toLowerCase();
    for (var i = 0; i < tokens.length; i++) {
      if (haystack.indexOf(tokens[i]) === -1) return false;
    }
    return true;
  }

  // ───────── Wire filter UI events ─────────
  // Mirrors js/listings-index.js's updateUrlQuery() pattern (own copy --
  // these two files load on different pages and share no module scope).
  function updateSearchUrl(q) {
    try {
      var url = new URL(window.location.href);
      if (q) { url.searchParams.set("q", q); }
      else { url.searchParams.delete("q"); }
      window.history.replaceState(null, "", url.toString());
    } catch (e) {
      // URL/searchParams unavailable on old environments -- filter still
      // works, just doesn't reflect into the address bar.
    }
  }

  function wireFilters() {
    document.querySelectorAll("#chip-recency .chip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.recency = b.dataset.recency;
        setActive("#chip-recency", b);
        applyAndRender();
      });
    });
    document.querySelectorAll("#chip-ptype .chip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.ptype = b.dataset.ptype;
        setActive("#chip-ptype", b);
        applyAndRender();
      });
    });
    document.querySelectorAll("#chip-sort .chip").forEach(function (b) {
      b.addEventListener("click", function () {
        state.sort = b.dataset.sort;
        setActive("#chip-sort", b);
        applyAndRender();
      });
    });
    // Smart search bar (2026-08-06 night) -- debounced live filter as the
    // user types, matching the site's standing Conv #172 discipline
    // (setTimeout, never rAF -- rAF pauses in background tabs). The form
    // also handles Enter/submit for parity, applying immediately.
    var searchInput = document.getElementById("sold-search-input");
    var searchForm = document.getElementById("sold-search-form");
    if (searchInput) {
      var searchDebounce = null;
      searchInput.addEventListener("input", function () {
        clearTimeout(searchDebounce);
        searchDebounce = setTimeout(function () {
          state.q = searchInput.value.trim();
          updateSearchUrl(state.q);
          applyAndRender();
        }, 150);
      });
    }
    if (searchForm) {
      searchForm.addEventListener("submit", function (ev) {
        ev.preventDefault();
        clearTimeout(searchDebounce);
        state.q = (searchInput && searchInput.value || "").trim();
        updateSearchUrl(state.q);
        applyAndRender();
      });
    }

    var areaSel = document.getElementById("area-select") || document.getElementById("city-select");
    if (areaSel) {
      areaSel.addEventListener("change", function () {
        state.area = areaSel.value;
        state.bounds = null;  // an explicit area pick releases any map-drawn box
        applyAndRender();
        if (soldMapReady && state.area) renderMap({ fit: true });
      });
    }
    var clearBtn = document.getElementById("clear-filters");
    if (clearBtn) {
      clearBtn.addEventListener("click", function () {
        state = { recency: "2y", ptype: "", area: "", sort: "date-desc",
                  team: "", agent: "", bounds: null, q: "" };
        var qInputClr = document.getElementById("sold-search-input");
        if (qInputClr) qInputClr.value = "";
        updateSearchUrl("");
        setActive("#chip-recency", document.querySelector('[data-recency="2y"]'));
        setActive("#chip-ptype", document.querySelector('#chip-ptype [data-ptype=""]'));
        setActive("#chip-sort", document.querySelector('[data-sort="date-desc"]'));
        var sel = document.getElementById("area-select") || document.getElementById("city-select");
        if (sel) sel.value = "";
        // Visibly reset the map too, not just the list (2026-08-06 late
        // night) -- Clear all is as explicit a "show me everything" ask
        // as the Recenter button, so it gets the same treatment.
        if (typeof window.soldMapRecenter === "function") window.soldMapRecenter();
        renderActiveFilterBanner();
        applyAndRender();
      });
    }
    var loadMore = document.getElementById("load-more");
    if (loadMore) loadMore.addEventListener("click", renderNextPage);

    wireViewToggle();
    setupFilterToggle();
    setupCardPinHover();
  }

  function setActive(selector, btn) {
    document.querySelectorAll(selector + " .chip").forEach(function (b) {
      b.classList.remove("active");
    });
    if (btn) btn.classList.add("active");
  }

  // ───────── Active-filter banner (Ship 3, 2026-05-17) — unchanged ─────────
  function renderActiveFilterBanner() {
    var el = document.getElementById("sold-active-filter");
    if (!el) return;
    var team = state.team;
    var agent = state.agent;
    if (!team && !agent) {
      el.innerHTML = "";
      el.style.display = "none";
      return;
    }
    function slugToLabel(s) {
      return (s || "").split("-").map(function (p) {
        return p ? (p.charAt(0).toUpperCase() + p.slice(1)) : p;
      }).join(" ");
    }
    var label = agent ? slugToLabel(agent) : slugToLabel(team);
    el.innerHTML =
      '<div class="sold-active-filter-inner">' +
        '<span class="sold-active-filter-label">' +
          "Filtered by <strong>" + esc(label) + "</strong>" +
        "</span>" +
        '<button type="button" id="sold-active-filter-clear" class="sold-active-filter-clear" aria-label="Clear filter">Clear &times;</button>' +
      "</div>";
    el.style.display = "block";
    var clearLink = document.getElementById("sold-active-filter-clear");
    if (clearLink) {
      clearLink.addEventListener("click", function (e) {
        e.preventDefault();
        state.team = "";
        state.agent = "";
        try {
          var url = new URL(window.location.href);
          url.searchParams.delete("team");
          url.searchParams.delete("agent");
          url.searchParams.delete("city");
          window.history.replaceState({}, "", url.toString());
        } catch (e2) { /* old browsers — leave URL alone */ }
        renderActiveFilterBanner();
        applyAndRender();
      });
    }
  }

  // ───────── Apply filters + sort + render first page ─────────
  // Live map-move filtering (2026-08-06 late night) -- the filtering
  // logic used to live inline in applyAndRender(); factored out so the
  // moveend auto-apply path (applyBoundsOnly) can recompute cards/count
  // without also re-rendering the map/pins on every pan tick.
  //
  // Runs the SAME predicate twice: once with bounds applied (cards,
  // `filtered`) and once without (pins, `pinRows`) -- so panning the map
  // narrows the visible card list without ever culling a marker that's
  // still on screen. The pins pass is skipped entirely when no bounds
  // filter is active (the common case), since the two sets are then
  // identical by construction.
  function recomputeFilters() {
    var cutoffDate = computeCutoff(state.recency);
    var ptype = state.ptype;
    var area = state.area;
    var team = state.team;
    var agent = state.agent;
    var bounds = state.bounds;
    var tokens = (state.q || "").toLowerCase().split(/\s+/).filter(Boolean);

    function rowMatches(r, skipBounds) {
      if (cutoffDate && r.sold_date < cutoffDate) return false;
      if (ptype && r.ptype !== ptype) return false;
      if (area && !rowMatchesArea(r, area)) return false;
      if (tokens.length && !rowMatchesQuery(r, tokens)) return false;
      if (team && (r.team_slug || "") !== team) return false;
      if (agent && (r.list_agent_slug || "") !== agent) return false;
      if (!skipBounds && bounds) {
        if (r.lat == null || r.lng == null) return false;
        if (r.lat < bounds.south || r.lat > bounds.north) return false;
        if (r.lng < bounds.west || r.lng > bounds.east) return false;
      }
      return true;
    }

    filtered = allRows.filter(function (r) { return rowMatches(r, false); });
    pinRows = bounds
      ? allRows.filter(function (r) { return rowMatches(r, true); })
      : filtered;

    filtered.sort(function (a, b) {
      switch (state.sort) {
        case "price-desc":
          return (b.close_price || 0) - (a.close_price || 0);
        case "price-asc":
          return (a.close_price || 0) - (b.close_price || 0);
        case "date-desc":
        default:
          return (b.sold_date || "").localeCompare(a.sold_date || "");
      }
    });
  }

  // The card-grid/empty-state/load-more render tail, shared by
  // applyAndRender() (full refresh) and applyBoundsOnly() (pan-only
  // refresh, below).
  function renderCardGrid() {
    renderedCount = 0;
    var grid = document.getElementById("card-grid");
    if (grid) grid.innerHTML = "";
    var emptyEl = document.getElementById("empty-state");
    var loadMore = document.getElementById("load-more");
    if (filtered.length === 0) {
      if (emptyEl) emptyEl.style.display = "block";
      if (loadMore) loadMore.style.display = "none";
      updateResultCount();
      return;
    }
    if (emptyEl) emptyEl.style.display = "none";
    renderNextPage();
  }

  function applyAndRender() {
    recomputeFilters();
    if (soldMapReady) renderMap();
    updateFilterToggleLabel();
    renderCardGrid();
  }

  // Called from the moveend auto-apply handler ONLY. Deliberately skips
  // renderMap()/rebuildPins() -- pinRows never depends on state.bounds
  // (see recomputeFilters()), so a pan can only ever change the CARD
  // list, never the pins already visible on the map. This is also what
  // makes the whole feature fit-loop-proof: nothing this function does
  // can itself trigger another moveend.
  function applyBoundsOnly() {
    recomputeFilters();
    updateFilterToggleLabel();
    renderCardGrid();
  }

  function computeCutoff(recencyCode) {
    var days = RECENCY_DAYS[recencyCode];
    if (!days) return null;
    var cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - days);
    return cutoff.toISOString().slice(0, 10);
  }

  function renderNextPage() {
    var grid = document.getElementById("card-grid");
    if (!grid) return;
    var slice = filtered.slice(renderedCount, renderedCount + PAGE_SIZE);
    var html = slice.map(renderCard).join("");
    grid.insertAdjacentHTML("beforeend", html);
    renderedCount += slice.length;
    updateResultCount();

    var loadMore = document.getElementById("load-more");
    if (loadMore) {
      if (renderedCount < filtered.length) {
        loadMore.style.display = "block";
        loadMore.textContent = "Load more (" + (filtered.length - renderedCount).toLocaleString() + " more)";
      } else {
        loadMore.style.display = "none";
      }
    }
  }

  function updateResultCount() {
    var el = document.getElementById("result-count");
    if (el) {
      el.textContent = filtered.length.toLocaleString() + " sold" +
        (filtered.length !== allRows.length ? " (of " + allRows.length.toLocaleString() + ")" : "");
    }
  }

  // ───────── Pin ↔ card sync (ported from js/listings-index.js) ─────────
  var cardFlashTimer = null;
  function scrollToCard(mls) {
    var card = document.querySelector('.sold-card-link[data-mls="' + mls + '"]');
    if (!card) return;
    try {
      card.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (e) {
      card.scrollIntoView();
    }
    document.querySelectorAll(".sold-card--highlighted").forEach(function (c) {
      c.classList.remove("sold-card--highlighted");
    });
    clearTimeout(cardFlashTimer);
    card.classList.add("sold-card--highlighted");
    cardFlashTimer = setTimeout(function () {
      card.classList.remove("sold-card--highlighted");
    }, 2400);
  }

  function setupCardPinHover() {
    var grid = document.getElementById("card-grid");
    if (!grid) return;
    function togglePinForEvent(ev, on) {
      var card = ev.target.closest && ev.target.closest(".sold-card-link");
      if (!card) return;
      var mls = card.getAttribute("data-mls");
      if (!mls) return;
      var marker = mlsToMarker[mls];
      if (!marker) return;
      var iconEl = marker.getElement && marker.getElement();
      if (!iconEl) return;  // clustered — no DOM element to highlight
      iconEl.classList.toggle("sold-pin--hover", on);
    }
    grid.addEventListener("mouseover", function (ev) { togglePinForEvent(ev, true); });
    grid.addEventListener("mouseout", function (ev) { togglePinForEvent(ev, false); });
  }

  // ───────── Card render ─────────
  function renderCard(r) {
    var isPending = (r.state === "firm_pending");
    // 2026-09-17 (B6): locked state is keyed on whether the VISITOR is
    // actually signed in right now, not on whether a background merge
    // attempt has completed (pricesLoaded also goes true after an
    // anonymous merge that correctly returned zero rows via RLS -- using
    // it here would have shown a bare "—" instead of an inviting tap
    // target for that visitor). event=passed through from the onclick so
    // the button can stop the click reaching the enclosing <a> (the whole
    // card is a link to the detail page).
    var priceLocked = (!isPending && r.close_price == null && !isAuthedForPrices());
    var price = isPending
      ? fmtPrice(r.list_price)
      : (priceLocked
          ? '<button type="button" class="sold-price-reauth" onclick="__soldOpenVowGate(event)" ' +
            'style="background:none;border:0;padding:0;font:inherit;color:#c8102e;' +
            'text-decoration:underline;cursor:pointer;">Sign in to see sold price</button>'
          : fmtPrice(r.close_price));
    var listPrice = fmtPrice(r.list_price);
    var ratioClass = "";
    var ratioText = "";
    if (isPending) {
      ratioClass = "ratio-pending";
      ratioText = "Firm Sale, Awaiting Close";
    } else if (r.sa_ratio != null) {
      if (r.sa_ratio >= 100.5) {
        ratioClass = "ratio-good";
        ratioText = "Sold +" + (r.sa_ratio - 100).toFixed(1) + "% over ask";
      } else if (r.sa_ratio >= 99 && r.sa_ratio <= 100.5) {
        ratioText = "Sold at ask";
      } else {
        ratioClass = "ratio-bad";
        ratioText = "Sold " + (100 - r.sa_ratio).toFixed(1) + "% under ask";
      }
    }
    var meta = [];
    if (r.beds != null) meta.push(r.beds + " bed");
    if (r.baths != null) meta.push(r.baths + " bath");
    if (r.sqft != null) meta.push(r.sqft.toLocaleString() + " sq ft");
    if (r.dom != null) meta.push(r.dom + "d on market");
    var soldDate = r.sold_date ? turnerCalDate(r.sold_date, { year: "numeric", month: "short", day: "numeric" })
                                : "";
    var ptype = r.psub || r.ptype || "";
    var badgeClass = isPending ? "sold-badge sold-badge-pending" : "sold-badge";
    var badgeText  = isPending ? "Pending" : "Sold";
    var dateLabel  = isPending ? "Pending since " : "Sold ";

    var imgArea;
    if (r.photo) {
      imgArea = '<div class="sold-card-img">' +
                  '<img src="' + esc(r.photo) + '" alt="' + esc(r.street || "Listing") + '" loading="lazy">' +
                  '<span class="' + badgeClass + '">' + badgeText + "</span>" +
                "</div>";
    } else {
      imgArea = '<div class="sold-card-img">' +
                  '<div class="sold-card-img-fallback">Photo on request</div>' +
                  '<span class="' + badgeClass + '">' + badgeText + "</span>" +
                "</div>";
    }

    // 2026-08-06: card wrapper now carries data-mls for pin<->card sync
    // (scrollToCard / setupCardPinHover).
    var detailHref = "/listings/sold/detail.html?mls=" + encodeURIComponent(r.mls || "");
    return '<a href="' + detailHref + '" class="sold-card-link" data-mls="' + esc(String(r.mls || "")) + '">' +
      '<article class="sold-card">' +
        imgArea +
        '<div class="sold-card-body">' +
          // Not esc()'d: `price` is either fmtPrice()'s pure-numeric output
          // or our own static reauth-button markup -- never raw feed text --
          // escaping it here was a pre-existing bug (carried from the
          // original file) that rendered the reauth button as literal
          // "<button ...>" text instead of a clickable element.
          '<p class="sold-price">' + price + "</p>" +
          '<div class="sold-price-sub">' +
            (!isPending && listPrice ? "<span>List " + esc(listPrice) + "</span>" : "") +
            (ratioText ? '<span class="' + ratioClass + '">' + esc(ratioText) + "</span>" : "") +
          "</div>" +
          '<p class="sold-address">' + esc(r.street || "—") + ", " + esc(r.city || "—") + "</p>" +
          // Brokerage attribution RESTORED 2026-09-15 (Mike: "out of an
          // abundance of caution... proper accreditation" -- not required
          // per the 2026-09-15 NLAR advertising-rules review, added anyway;
          // supersedes the 2026-08-06 "no attribution at all" decision).
          // Brokerage name only -- never the individual agent -- per the
          // 2026-08-04 company-not-agent decision this restores. Fail-soft:
          // older/not-yet-regenerated rows simply lack list_office.
          // Reuses the existing .sold-meta style (small, muted text) rather
          // than a new CSS class -- no generator/template CSS change needed.
          (r.list_office ? '<p class="sold-meta">Listed by ' + esc(r.list_office) + "</p>" : "") +
          '<p class="sold-meta">' + dateLabel + esc(soldDate) +
            (meta.length ? " · " + esc(meta.join(" · ")) : "") + "</p>" +
          (ptype ? '<p style="margin-top:8px;"><span class="sold-card-tag">' + esc(ptype) + "</span></p>" : "") +
        "</div>" +
      "</article>" +
    "</a>";
  }

  function fmtPrice(n) {
    if (n == null) return "—";
    if (n >= 1000000) return "$" + (n / 1000000).toFixed(2).replace(/\.?0+$/, "") + "M";
    if (n >= 1000) return "$" + Math.round(n / 1000) + "K";
    return "$" + Math.round(n).toLocaleString();
  }

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
})();
