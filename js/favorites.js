/**
 * Favorites (Saved Homes) — Phase 2 flywheel item #12.
 *
 * Per _research/Favorites_Design_Spec_2026-06-04.md.
 *
 * Storage model (Decision A): localStorage-first + Supabase sync for
 * signed-in users (merge-on-sign-in). Anonymous users heart to
 * localStorage `lst-favorites-v1` (instant, no sign-in wall — matches the
 * existing ldisc-hidden-v1 / lst-compare-cart-v1 / lst-recently-viewed-v1
 * pattern). Signed-in users additionally sync to the Supabase `favorites`
 * table (cross-device). On sign-in, localStorage favorites merge up into
 * Supabase so nothing hearted-while-anonymous is lost.
 *
 * Convention compliance:
 *   - #15 byte-symmetric across the 3 listings-feed sites (site inferred
 *     from hostname so the file stays identical)
 *   - #74 fail-safe: no TurnerAuth / SDK / table → localStorage-only, still
 *     fully functional (just not cross-device). Every Supabase call is
 *     wrapped so a missing table / RLS error never breaks the heart.
 *   - #106 cache-bust via ?v=YYYYMMDD-favorites on the script src
 *   - card-heart injection mirrors compare-cart.js (MutationObserver +
 *     absolute-positioned button appended to .lst-card)
 */
(function () {
  "use strict";

  var LS_KEY = "lst-favorites-v1";

  // ── Site detection (keeps the file byte-symmetric per Convention #15) ──
  function currentSite() {
    if (window.TURNER_SITE) return window.TURNER_SITE;
    var h = (window.location.hostname || "").toLowerCase();
    if (h.indexOf("avalon") !== -1) return "avalon";
    if (h.indexOf("goosebay") !== -1) return "goosebay";
    return "gander"; // realestategander.com + localhost fallback
  }
  var SITE = currentSite();

  // Active-listings JSON differs per site (keeps this file byte-symmetric):
  // Gander serves /listings/data.json; Avalon + Goosebay serve the projected
  // cache directly. The account renderer resolves saved MLS → cards from here.
  function listingsDataUrl() {
    return "/listings/data.json";
  }

  // ── GA4 helper (Convention #74 fail-safe) ──
  function gaEvent(name, params) {
    try { if (typeof gtag === "function") gtag("event", name, params || {}); } catch (e) { /* silent */ }
  }
  function noop() {}

  // ── localStorage (stores {mls, site, ts} across all sites; favSet is
  //    the in-memory set of MLS strings scoped to the CURRENT site) ──
  function lsRead() {
    try { var v = JSON.parse(localStorage.getItem(LS_KEY)); return Array.isArray(v) ? v : []; }
    catch (e) { return []; }
  }
  function lsWrite(arr) {
    try { localStorage.setItem(LS_KEY, JSON.stringify(arr)); } catch (e) { /* quota / private mode */ }
  }

  var favSet = new Set();          // MLS strings favorited on THIS site
  var changeListeners = [];

  function loadLocal() {
    favSet = new Set(
      lsRead().filter(function (f) { return f && f.site === SITE; })
              .map(function (f) { return String(f.mls); })
    );
  }

  function has(mls) { return favSet.has(String(mls)); }
  function list() { return Array.from(favSet); }

  function notify() {
    syncButtons();
    changeListeners.forEach(function (cb) { try { cb(list()); } catch (e) { /* silent */ } });
  }

  // ── Supabase plumbing (Convention #74 — every path degrades gracefully) ──
  function client() { return (window.TurnerAuth && window.TurnerAuth._client) || null; }
  function userId() {
    try { var u = window.TurnerAuth && window.TurnerAuth.getUser && window.TurnerAuth.getUser(); return u && u.id; }
    catch (e) { return null; }
  }

  function supabaseSync(mls, adding) {
    var c = client(), uid = userId();
    if (!c || !uid) return; // anonymous → localStorage carries it
    try {
      if (adding) {
        c.from("favorites")
         .upsert({ user_id: uid, site: SITE, mls: String(mls) }, { onConflict: "user_id,site,mls" })
         .then(noop, noop);
      } else {
        c.from("favorites").delete().match({ user_id: uid, site: SITE, mls: String(mls) }).then(noop, noop);
      }
    } catch (e) { /* table missing / SDK shape change — localStorage still has it */ }
  }

  // Push local favorites up + pull server favorites down, union into favSet.
  function mergeOnSignIn() {
    var c = client(), uid = userId();
    if (!c || !uid) return;
    try {
      var localRows = lsRead().filter(function (f) { return f && f.site === SITE; });
      if (localRows.length) {
        c.from("favorites")
         .upsert(localRows.map(function (f) { return { user_id: uid, site: SITE, mls: String(f.mls) }; }),
                 { onConflict: "user_id,site,mls" })
         .then(noop, noop);
      }
      c.from("favorites").select("mls").eq("user_id", uid).eq("site", SITE).then(function (res) {
        if (!res || res.error || !res.data) return;
        res.data.forEach(function (row) { favSet.add(String(row.mls)); });
        // Persist merged set back to the localStorage cache (preserve other sites).
        var others = lsRead().filter(function (f) { return f && f.site !== SITE; });
        favSet.forEach(function (m) { others.push({ mls: m, site: SITE, ts: Date.now() }); });
        lsWrite(others);
        notify();
      }, noop);
    } catch (e) { /* silent */ }
  }

  // ── Toggle ──
  function toggle(mls, opts) {
    mls = String(mls); opts = opts || {};
    var adding = !favSet.has(mls);
    if (adding) favSet.add(mls); else favSet.delete(mls);

    var arr = lsRead().filter(function (f) { return !(f && f.site === SITE && String(f.mls) === mls); });
    if (adding) arr.push({ mls: mls, site: SITE, ts: Date.now() });
    lsWrite(arr);

    supabaseSync(mls, adding);
    gaEvent(adding ? "favorite_add" : "favorite_remove",
            { mls: mls, site: SITE, surface: String(opts.surface || "card") });
    notify();
    return adding;
  }

  // ── Heart icon ──
  var HEART = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
    '<path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>' +
    '</svg>';

  // ── Card heart injection (mirrors compare-cart.js) ──
  function injectCardButtons() {
    var cards = document.querySelectorAll(".lst-card[data-mls]");
    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      if (card.querySelector(".lst-card-fav")) continue;
      var mls = card.getAttribute("data-mls");
      if (!mls) continue;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lst-card-fav" + (has(mls) ? " is-fav" : "");
      btn.setAttribute("data-fav-mls", mls);
      btn.setAttribute("aria-pressed", has(mls) ? "true" : "false");
      btn.setAttribute("aria-label", has(mls) ? "Remove from saved homes" : "Save this home");
      btn.innerHTML = HEART;
      (function (m, b) {
        b.addEventListener("click", function (e) {
          e.preventDefault(); e.stopPropagation();
          toggle(m, { surface: "card" });
        });
      })(mls, btn);
      card.appendChild(btn); // CSS absolute-positions it bottom-right
    }
    injectSoldCardButtons();
  }

  // ── Sold-listings page (/listings/sold/) heart injection ──
  // Sold cards use .sold-card inside <a class="sold-card-link" href="...sold/
  // detail.html?mls=X">, not .lst-card[data-mls]. Inject the heart into
  // .sold-card-img (already position:relative) at top-right (clear of the
  // top-left .sold-badge). MLS comes from the link href. preventDefault +
  // stopPropagation so the heart click doesn't navigate the wrapping anchor.
  function injectSoldCardButtons() {
    var links = document.querySelectorAll("a.sold-card-link[href*='mls=']");
    for (var i = 0; i < links.length; i++) {
      var link = links[i];
      var imgArea = link.querySelector(".sold-card-img");
      if (!imgArea || imgArea.querySelector(".lst-card-fav")) continue;
      var m = /[?&]mls=([^&]+)/.exec(link.getAttribute("href") || "");
      if (!m) continue;
      var mls = decodeURIComponent(m[1]);
      if (!mls) continue;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "lst-card-fav" + (has(mls) ? " is-fav" : "");
      btn.setAttribute("data-fav-mls", mls);
      btn.setAttribute("aria-pressed", has(mls) ? "true" : "false");
      btn.setAttribute("aria-label", has(mls) ? "Remove from saved homes" : "Save this home");
      btn.innerHTML = HEART;
      (function (m2, b) {
        b.addEventListener("click", function (e) {
          e.preventDefault(); e.stopPropagation();
          toggle(m2, { surface: "sold-card" });
        });
      })(mls, btn);
      imgArea.appendChild(btn);
    }
  }

  // ── Sync visual state of every heart on the page ──
  function syncButtons() {
    var cardBtns = document.querySelectorAll(".lst-card-fav[data-fav-mls]");
    for (var i = 0; i < cardBtns.length; i++) {
      var b = cardBtns[i], on = has(b.getAttribute("data-fav-mls"));
      b.classList.toggle("is-fav", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.setAttribute("aria-label", on ? "Remove from saved homes" : "Save this home");
    }
    var toggles = document.querySelectorAll("[data-fav-toggle]");
    for (var j = 0; j < toggles.length; j++) {
      var t = toggles[j], onT = has(t.getAttribute("data-fav-toggle"));
      t.classList.toggle("is-fav", onT);
      t.setAttribute("aria-pressed", onT ? "true" : "false");
      var lbl = t.querySelector(".lst-fav-label");
      if (lbl) lbl.textContent = onT ? "Saved" : "Save";
    }
  }

  // ── Explicit detail-page toggle binding ──
  function bindToggles() {
    var toggles = document.querySelectorAll("[data-fav-toggle]");
    for (var i = 0; i < toggles.length; i++) {
      var b = toggles[i];
      if (b.__favBound) continue;
      b.__favBound = true;
      (function (btn) {
        btn.addEventListener("click", function (e) {
          e.preventDefault();
          toggle(btn.getAttribute("data-fav-toggle"), { surface: "detail" });
        });
      })(b);
    }
    syncButtons();
  }

  // ── MutationObserver: re-inject + re-bind as cards render (discovery shell) ──
  var observeScheduled = false;
  function scheduleSync() {
    if (observeScheduled) return;
    observeScheduled = true;
    // setTimeout, not requestAnimationFrame: rAF is paused in background/hidden tabs,
    // so the observer-driven heart injection on the JS-rendered discovery-shell grid
    // would never fire there (compare-cart.js uses setTimeout for the same reason).
    // Injection is lightweight — no paint-sync benefit worth the background-tab gap.
    window.setTimeout(function () {
      observeScheduled = false;
      injectCardButtons();
      bindToggles();
    }, 0);
  }
  function observe() {
    if (!window.MutationObserver || !document.body) return;
    new MutationObserver(scheduleSync).observe(document.body, { childList: true, subtree: true });
  }

  // ── HTML escape ──
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function fmtPrice(v) {
    var n = Number(v);
    if (!v || isNaN(n) || n < 5000) return "Contact for price"; // lease/placeholder guard
    return "$" + Math.round(n).toLocaleString("en-CA");
  }
  // Consumer Dashboard Hub P2 (2026-08-26): richer saved-home cards, built
  // entirely from fields the feed already carries on every site (verified
  // against both live feeds before writing this -- idx_original_list_price/
  // idx_last_list_price/list_date/status are byte-identical field names on
  // Gander AND the Avalon/Goosebay projected cache; only beds/baths/city
  // differ per site, already handled above).
  function daysOnMarket(listDateStr) {
    if (!listDateStr) return null;
    var d = new Date(listDateStr + "T00:00:00Z");
    if (isNaN(d.getTime())) return null;
    var days = Math.floor((Date.now() - d.getTime()) / 86400000);
    return days >= 0 ? days : null;
  }
  function priceDropPct(orig, last) {
    var o = Number(orig), l = Number(last);
    if (!o || !l || isNaN(o) || isNaN(l) || o <= l) return null;
    return Math.round((1 - (l / o)) * 100);
  }

  // ── Account "Saved listings" section renderer (Decision D) ──
  // container: a DOM element. Fetches /listings/data.json, resolves the
  // favorited MLS → mini-cards. Convention #74: missing data → graceful note.
  function renderAccountSection(container) {
    if (!container) return;
    gaEvent("favorites_account_view", { site: SITE, count: favSet.size });
    if (favSet.size === 0) {
      container.innerHTML = '<p class="fav-empty">No saved homes yet — tap the ' +
        '<span class="fav-empty-heart">' + HEART + '</span> on any listing to save it here.</p>';
      return;
    }
    container.innerHTML = '<p class="fav-loading">Loading your saved homes…</p>';
    fetch(listingsDataUrl(), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (payload) {
        var rows = payload && (payload.listings || payload.rows || payload) || [];
        var byMls = {};
        for (var i = 0; i < rows.length; i++) { if (rows[i] && rows[i].mls != null) byMls[String(rows[i].mls)] = rows[i]; }
        var saved = list();
        var goneMls = [];
        for (var gi = 0; gi < saved.length; gi++) { if (!byMls[saved[gi]]) goneMls.push(String(saved[gi])); }
        // Consumer Dashboard Hub P2 (2026-08-26): a favorited home that dropped
        // off the active feed is usually SOLD, not expired -- and this page is
        // already signed-in-only, so per the established VOW policy (gate the
        // price from anonymous visitors, not from an authenticated account)
        // showing the real close price here is compliant. Mirrors the exact
        // viewpoint_prices batch pattern already proven in watched-areas.js.
        var cSb = client();
        var soldLookup = (cSb && goneMls.length)
          ? cSb.from("viewpoint_prices").select("mls,close_price,close_date").in("mls", goneMls)
          : Promise.resolve({ data: [] });
        return soldLookup.then(function (soldRes) {
          var soldByMls = {};
          ((soldRes && soldRes.data) || []).forEach(function (p) { if (p && p.mls) soldByMls[String(p.mls)] = p; });
          var cards = [];
          for (var j = 0; j < saved.length; j++) {
            var mls = saved[j], l = byMls[mls];
            if (l) {
              cards.push(savedCard(l, mls));
            } else {
              var sold = soldByMls[mls];
              if (sold && sold.close_price) {
                cards.push('<div class="fav-card fav-card--gone fav-card--sold"><div class="fav-card-body">' +
                  '<p class="fav-card-price">' + esc(fmtPrice(sold.close_price)) + '</p>' +
                  '<p class="fav-card-addr">MLS&reg; ' + esc(mls) + '</p>' +
                  '<p class="fav-card-note">Sold' + (sold.close_date ? ' ' + esc(sold.close_date) : '') + '</p>' +
                  '<a class="fav-card-soldlink" href="/listings/sold/detail.html?mls=' + encodeURIComponent(mls) + '">View sold record &rarr;</a>' +
                  '<button type="button" class="fav-card-remove" data-fav-toggle="' + esc(mls) + '">Remove</button>' +
                  '</div></div>');
              } else {
                // Favorited but not in the active feed and no sold record yet —
                // almost always a SOLD listing saved from /listings/sold/ whose
                // close price hasn't synced to viewpoint_prices yet (occasionally
                // an expired active listing). Offer the sold record link; the
                // sold detail re-runs the VOW gate itself either way.
                cards.push('<div class="fav-card fav-card--gone"><div class="fav-card-body">' +
                  '<p class="fav-card-addr">MLS&reg; ' + esc(mls) + '</p>' +
                  '<p class="fav-card-note">No longer an active listing</p>' +
                  '<a class="fav-card-soldlink" href="/listings/sold/detail.html?mls=' + encodeURIComponent(mls) + '">View sold record &rarr;</a>' +
                  '<button type="button" class="fav-card-remove" data-fav-toggle="' + esc(mls) + '">Remove</button>' +
                  '</div></div>');
              }
            }
          }
          container.innerHTML = '<div class="fav-grid">' + cards.join("") + '</div>';
          bindToggles();
          // Re-render when a card is un-saved from within the account view.
          container.querySelectorAll("[data-fav-toggle]").forEach(function (b) {
            b.addEventListener("click", function () {
              setTimeout(function () { renderAccountSection(container); }, 50);
            });
          });
        });
      })
      .catch(function () {
        container.innerHTML = '<p class="fav-empty">Couldn\'t load your saved homes right now. ' +
          'Please refresh in a moment.</p>';
      });
  }

  function savedCard(l, mls) {
    var url = l.url || l.url_path || ("/listings/");
    var photo = (l.photos && l.photos[0] && (l.photos[0].url || l.photos[0])) || l.photo || "";
    var street = l.street || l.address_line || "";
    var city = l.city || l.city_raw || "";
    var addr = [street, city].filter(Boolean).join(", ");
    var price = fmtPrice(l.list_price != null ? l.list_price : l.price);
    var bits = [];
    var bd = l.bedrooms != null ? l.bedrooms : l.beds;
    var ba = l.bathrooms != null ? l.bathrooms : l.baths;
    if (bd != null) bits.push(esc(bd) + " bd");
    if (ba != null) bits.push(esc(ba) + " ba");
    var dom = daysOnMarket(l.list_date);
    if (dom != null) bits.push(dom + " days on market");
    var meta = bits.length ? '<p class="fav-card-meta">' + bits.join(" &middot; ") + "</p>" : "";
    var dropPct = priceDropPct(l.idx_original_list_price, l.idx_last_list_price);
    var pending = String(l.status || "").indexOf("Pending") !== -1;
    var badges = "";
    if (dropPct != null) badges += '<span class="fav-badge fav-badge--drop">Price drop &minus;' + dropPct + '%</span>';
    if (pending) badges += '<span class="fav-badge fav-badge--pending">Pending</span>';
    badges = badges ? '<div class="fav-card-badges">' + badges + '</div>' : "";
    var img = photo
      ? '<img src="' + esc(photo) + '" alt="' + esc(addr || "Saved listing") + '" loading="lazy" ' +
        'onerror="this.style.display=\'none\';this.parentElement.classList.add(\'fav-card-img--imgfail\')">'
      : "";
    return '<div class="fav-card">' +
      '<a class="fav-card-link" href="' + esc(url) + '">' +
        '<div class="fav-card-img">' + img + badges + '</div>' +
        '<div class="fav-card-body">' +
          '<p class="fav-card-price">' + esc(price) + '</p>' +
          '<p class="fav-card-addr">' + esc(addr || ("MLS® " + mls)) + '</p>' +
          meta +
        '</div>' +
      '</a>' +
      '<button type="button" class="fav-card-remove" data-fav-toggle="' + esc(mls) + '" ' +
        'aria-label="Remove from saved homes">&times;</button>' +
    '</div>';
  }

  // ── Init ──
  function init() {
    loadLocal();
    injectCardButtons();
    bindToggles();
    observe();
    if (window.TurnerAuth && window.TurnerAuth.ready) {
      window.TurnerAuth.ready.then(function () { if (userId()) mergeOnSignIn(); });
      if (window.TurnerAuth.onAuthChange) {
        window.TurnerAuth.onAuthChange(function (ev, session) {
          if (session && session.user) { mergeOnSignIn(); }
          else { loadLocal(); notify(); }  // signed out → fall back to localStorage view
        });
      }
    }
  }

  // ── Public namespace ──
  window.Favorites = {
    has: has,
    toggle: toggle,
    list: list,
    onChange: function (cb) { if (typeof cb === "function") changeListeners.push(cb); },
    renderAccountSection: renderAccountSection,
    site: SITE
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
