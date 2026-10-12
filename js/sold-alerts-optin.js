/*!
 * Batch A3 (2026-08-05) — sold-alerts opt-in banner on /listings/sold/.
 *
 * Post-unlock dismissible banner: "Want to know when homes sell in your
 * area? Get Sold Alerts." Expands to a city picker + cadence + one consent
 * line, then creates a saved_searches row with alert_types:['sold'].
 *
 * Standalone file, NOT an edit to js/sold-listings.js (2026-08-05 design
 * call): sold-listings.js is large, diverged across all 3 sites, and
 * actively maintains map/filter/render state; this mirrors the SAME
 * independent-file, Conv #74-safe shape js/save-nudge.js already
 * established for the nearly-identical "suggest a saved search" pattern —
 * its own dual-path vow:unlocked + localStorage listener, its own
 * independent fetch of /listings/sold/data.json for the city dropdown
 * (a same-page cache hit in practice, since sold-listings.js already
 * fetched the identical URL to unlock the page).
 *
 * Reuses window.SavedSearch.save()/.update()/.list()/.toast() — the SAME
 * insert/consent machinery every other saved-search surface uses. No new
 * backend, no new consent-recording code path.
 */
(function () {
  "use strict";

  // AddressComplete self-load (2026-09-07). Fails open at every step: no
  // SELF_SRC, a failed load, an empty fleet key, or a service error all
  // leave the address field exactly as a plain, unused text box -- the
  // city CHECKBOXES stay the actual, required mechanism.
  var AC_SELF_SRC = (document.currentScript && document.currentScript.src) || "";
  var AC_LOADERS = null;
  function loadAddressComplete(cb) {
    if (window.AddressComplete) { cb(); return; }
    if (!AC_SELF_SRC) return;
    if (AC_LOADERS) { AC_LOADERS.push(cb); return; }
    AC_LOADERS = [cb];
    var s = document.createElement("script");
    s.src = AC_SELF_SRC.replace(/sold-alerts-optin\.js(\?.*)?$/, "address-complete.js") + "?v=20260907-google-ac";
    s.onload = function () {
      (AC_LOADERS || []).forEach(function (fn) { fn(); });
      AC_LOADERS = null;
    };
    s.onerror = function () { AC_LOADERS = null; };
    document.head.appendChild(s);
  }

  var LS_DISMISSED = "sold-alerts-optin-dismissed-v1";
  var CONSENT_TEXT = "I'd like to receive email alerts when homes sell in the areas I've chosen.";
  var shown = false;
  var banner = null;
  var dataFetched = false;

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

  function siteIdFromHost() {
    var site = window.TURNER_SITE;
    var region = site && window.TURNER_REGIONS && window.TURNER_REGIONS[site];
    if (region && region.site_id) return region.site_id;
    var h = window.location.hostname || "";
    if (h.indexOf("avalonrealestate") !== -1) return "avalonrealestate";
    if (h.indexOf("goosebayrealestate") !== -1) return "goosebayrealestate";
    return "realestategander";
  }

  // Batch D2's funnel beacon — reserved for exactly this opt-in (see
  // js/vow-gate.js/auth.js's own fireFunnelEvent for the sibling copies).
  function fireFunnelEvent(eventName, email) {
    try {
      var payload = {
        event: eventName, email: email || "",
        site: siteIdFromHost(), path: window.location.pathname
      };
      // Attribution (client_id etc.): auth.js's window.TurnerFunnel (redesign slice 1).
      if (window.TurnerFunnel) window.TurnerFunnel.extend(payload);
      var body = JSON.stringify(payload);
      var endpoint = (window.TURNER_API_ORIGIN || "https://realestategander.com") + "/.netlify/functions/vow-funnel-event";
      if (navigator.sendBeacon) {
        navigator.sendBeacon(endpoint, new Blob([body], { type: "text/plain;charset=UTF-8" }));
      } else {
        fetch(endpoint, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: body, keepalive: true, mode: "cors"
        }).catch(function () {});
      }
    } catch (e) { /* a funnel beacon must never break the opt-in flow */ }
  }

  function dataUrl() {
    return (typeof window !== "undefined" && window.SOLD_DATA_URL)
      ? window.SOLD_DATA_URL
      : "/listings/sold/data.json";
  }

  function cityOptionsFrom(dropdown) {
    // Mirrors sold-listings.js's own dropdown-payload shape
    // ({major_centres:[{key,count}], regions:[{key,count}]}) — verified
    // against the real live data.json rather than assumed (Conv #67/#92):
    // each entry is an OBJECT, not a bare string.
    //
    // Deliberately major_centres ONLY, not regions: emit_sold_data() sets
    // dropdown_key = city (exact equality) for a major centre, but = a
    // REGION LABEL for smaller cities rolled up below the threshold — and
    // that dropdown_key is a computed field that only exists in the FULL
    // multi-pass generator, not on the raw RETS cache scan_sold_records()
    // reads. sold_row_matches() compares criteria.cities against the row's
    // plain `city` field, which only equals dropdown_key for major centres
    // — offering a region here would silently match zero sold rows ever.
    // A real, documented scope-narrowing, not a bug: still covers every
    // named town with meaningful sold volume.
    if (!dropdown || typeof dropdown !== "object") return [];
    var out = [];
    (dropdown.major_centres || []).forEach(function (c) { if (c && c.key) out.push(c.key); });
    return out;
  }

  function hideBanner() {
    if (banner && banner.parentNode) banner.parentNode.removeChild(banner);
    banner = null;
  }

  function showError(form, msg) {
    var el = form.querySelector(".sao-error");
    if (el) { el.textContent = msg; el.style.display = "block"; }
  }

  function expandToForm(cities) {
    if (!banner) return;
    var opts = cities.map(function (c) {
      return '<label style="display:inline-flex;align-items:center;gap:5px;margin:0 12px 8px 0;' +
        'font-size:.86rem;color:#333;font-weight:400;">' +
        '<input type="checkbox" class="sao-city" value="' + esc(c) + '"> ' + esc(c) + '</label>';
    }).join("");

    banner.innerHTML =
      '<form class="sao-form" style="flex:1 1 100%;">' +
        '<p style="margin:0 0 10px;font-size:.94rem;font-weight:700;color:#1a1a1a;">Get Listing Sold Alerts</p>' +
        '<input type="text" class="sao-addr" autocomplete="off" placeholder="Type your address to auto-check your area" ' +
          'style="width:100%;box-sizing:border-box;padding:8px 10px;margin:0 0 10px;border:1px solid #ddd;border-radius:6px;font-size:.86rem;">' +
        '<p style="margin:0 0 8px;font-size:.82rem;color:#666;">Choose the area(s) you want to hear about:</p>' +
        '<div style="margin:0 0 12px;">' + (opts || '<span style="font-size:.82rem;color:#999;">No areas available right now.</span>') + '</div>' +
        '<p style="margin:0 0 8px;font-size:.82rem;color:#666;">How often?</p>' +
        '<div style="margin:0 0 14px;">' +
          '<label style="display:inline-flex;align-items:center;gap:5px;margin-right:16px;font-size:.86rem;color:#333;font-weight:400;">' +
            '<input type="radio" name="sao-cadence" value="daily" checked> Daily</label>' +
          '<label style="display:inline-flex;align-items:center;gap:5px;font-size:.86rem;color:#333;font-weight:400;">' +
            '<input type="radio" name="sao-cadence" value="weekly"> Weekly</label>' +
        '</div>' +
        '<label style="display:flex;align-items:flex-start;gap:8px;margin:0 0 14px;font-size:.82rem;color:#555;font-weight:400;line-height:1.4;">' +
          '<input type="checkbox" class="sao-consent" style="margin-top:3px;"> ' + esc(CONSENT_TEXT) +
        '</label>' +
        '<p class="sao-error" role="alert" style="display:none;margin:0 0 10px;font-size:.82rem;color:#a3122a;"></p>' +
        '<button type="submit" style="background:#EA002A;color:#fff;border:none;border-radius:6px;' +
          'padding:10px 20px;font-weight:700;font-size:.88rem;cursor:pointer;">Subscribe</button> ' +
        '<button type="button" class="sao-cancel" style="background:none;border:none;color:#888;' +
          'font-size:.86rem;cursor:pointer;padding:10px 8px;">Not now</button>' +
      '</form>';

    var form = banner.querySelector(".sao-form");
    var addrInput = form.querySelector(".sao-addr");
    if (addrInput) {
      loadAddressComplete(function () {
        if (!window.AddressComplete) return;
        window.AddressComplete.attach(addrInput, {
          fields: false,
          onSelect: function (addr) {
            if (!addr.city) return;
            var norm = String(addr.city).toLowerCase().trim();
            form.querySelectorAll(".sao-city").forEach(function (box) {
              if (String(box.value).toLowerCase().trim() === norm) box.checked = true;
            });
          }
        });
      });
    }
    form.querySelector(".sao-cancel").addEventListener("click", function () {
      setDismissed();
      hideBanner();
    });
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      submitOptin(form);
    });
  }

  function submitOptin(form) {
    var cities = [];
    form.querySelectorAll(".sao-city:checked").forEach(function (el) { cities.push(el.value); });
    var cadence = (form.querySelector('input[name="sao-cadence"]:checked') || {}).value || "daily";
    var consented = !!(form.querySelector(".sao-consent") || {}).checked;

    if (!cities.length) {
      showError(form, "Pick at least one area.");
      return;
    }
    if (!consented) {
      showError(form, "Please check the box to confirm you want these alerts.");
      return;
    }
    if (!window.SavedSearch || !window.SavedSearch.save || !window.SavedSearch.update) {
      showError(form, "Something went wrong — please try again in a moment.");
      return;
    }

    var submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Saving…"; }

    var name = "Sold alerts — " + cities.join(", ");
    var criteria = { v: 2, cities: cities };

    window.SavedSearch.save(name, criteria, cadence).then(function (r) {
      if (r.error || !r.data || !r.data.id) {
        throw new Error((r.error && r.error.message) || "Save failed");
      }
      var email = (r.data.email || "").toString(); // may be absent on the row itself
      var patch = {
        alert_types: ["sold"],
        channel_email: true,
        channel_sms: false,
        email_consent: {
          granted_at: new Date().toISOString(),
          source: "sold-alerts-optin",
          text: CONSENT_TEXT,
          email: email
        }
      };
      return window.SavedSearch.update(r.data.id, patch);
    }).then(function (r2) {
      if (r2.error) throw new Error(r2.error.message || "Save failed");
      fireFunnelEvent("alert_optin");
      setDismissed();
      hideBanner();
      if (window.SavedSearch.toast) {
        window.SavedSearch.toast("✓ Sold Alerts are on — we'll email you when homes sell in " +
          (cities.length === 1 ? cities[0] : cities.length + " areas") + ".");
      }
    }).catch(function (err) {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = "Subscribe"; }
      showError(form, (err && err.message) || "Something went wrong — please try again.");
    });
  }

  function showBanner(cities) {
    if (banner) return;
    var host = document.querySelector("main.cards-section") || document.querySelector("main") || document.body;

    banner = document.createElement("div");
    banner.className = "sold-alerts-optin-banner";
    banner.setAttribute("role", "region");
    banner.setAttribute("aria-label", "Get Sold Alerts");
    banner.style.cssText =
      "display:flex;gap:14px;align-items:center;flex-wrap:wrap;" +
      "background:#fff7f7;border:1px solid #f2c9cf;border-left:4px solid #EA002A;" +
      "border-radius:8px;padding:16px 18px;margin:0 0 20px;" +
      "font-family:Raleway,Arial,sans-serif;";
    banner.innerHTML =
      '<p style="flex:1 1 260px;margin:0;font-size:.94rem;line-height:1.4;color:#1a1a1a;min-width:200px;">' +
        "Want to know when homes sell in your area? Get Sold Alerts." +
      "</p>" +
      '<button type="button" class="sao-cta" style="flex:0 0 auto;background:#EA002A;color:#fff;' +
        'border:none;border-radius:6px;padding:10px 18px;font-weight:700;font-size:.88rem;cursor:pointer;' +
        'white-space:nowrap;">Get Sold Alerts</button>' +
      '<button type="button" class="sao-dismiss" aria-label="Dismiss this suggestion"' +
        ' style="flex:0 0 auto;background:none;border:none;color:#999;font-size:1.35rem;' +
        'line-height:1;cursor:pointer;padding:2px 6px;">&times;</button>';

    host.insertBefore(banner, host.firstChild);

    banner.querySelector(".sao-dismiss").addEventListener("click", function () {
      setDismissed();
      hideBanner();
    });
    banner.querySelector(".sao-cta").addEventListener("click", function () {
      expandToForm(cities);
    });

    if (window.gtag) {
      try { window.gtag("event", "sold_alerts_optin_shown", {}); } catch (e) { /* no-op */ }
    }
  }

  function maybeShow() {
    if (shown || dismissed()) return;
    if (!window.SavedSearch || !window.SavedSearch.list) return;

    window.SavedSearch.list().then(function (searches) {
      var already = (searches || []).some(function (s) {
        return Array.isArray(s.alert_types) && s.alert_types.indexOf("sold") !== -1;
      });
      if (already) return; // already has one — nothing to suggest (Conv #74/save-nudge pattern)

      (window.TurnerAuth && window.TurnerAuth.soldFetch ? window.TurnerAuth.soldFetch : window.fetch.bind(window))(dataUrl(), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (payload) {
          var cities = cityOptionsFrom(payload && payload.dropdown);
          shown = true;
          showBanner(cities);
        })
        .catch(function () { /* Conv #74 — dropdown fetch failure, no banner */ });
    }).catch(function () { /* Conv #74 — SavedSearch.list() failure, no banner */ });
  }

  document.addEventListener("vow:unlocked", function () {
    if (dataFetched) return;
    dataFetched = true;
    maybeShow();
  });

  // PATH B fallback — returning visitor, already-unlocked before this
  // script's listener could ever register (same dual-path shape as
  // sold-listings.js/vow-gate.js's own unlock handling).
  try {
    var raw = localStorage.getItem("vow_gate_v1");
    if (raw) {
      var parsed = JSON.parse(raw);
      if (parsed && parsed.passed === true && !dataFetched) {
        dataFetched = true;
        maybeShow();
      }
    }
  } catch (e) { /* ignore — quota or private browsing */ }
})();
