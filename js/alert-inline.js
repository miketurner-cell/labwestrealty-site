/* Listing Text Alerts — one-tap inline signup widget
 * Drop-in: put  <div data-lta-inline></div>  anywhere + load this script.
 * Renders a phone field + "Text me new listings" + CASL consent into the
 * container, posts to /api/sms-subscribe (same validated path as the full
 * /text-alerts configurer), default criteria = ALL NEW listings.
 * Optional data attrs on the container:
 *   data-lta-label="..."     human label shown on the subscription (default: New listings in <City>, or all new <Area> listings)
 *   data-lta-theme="light"   light surface (default is dark)
 *   data-lta-city="Gander"   scope the alert to one town (Alerts v2 I4)
 *
 * Alerts v2 I4 (2026-07-24): this widget sits on every listing and city page
 * and used to post criteria:{} — subscribe to EVERY new listing on the site.
 * Someone reading a Lewisporte listing got texted about Gander bungalows, and
 * could not narrow it. When the page tells us its town via data-lta-city we
 * now scope to that town; a true site-wide surface omits the attribute and
 * keeps the old behaviour. Either way the manage link (texted on confirm)
 * lets them change it.
 */
(function () {
  "use strict";
  var HOST = location.hostname;
  var SITE = window.TURNER_SITE || (
    HOST.indexOf("goosebay") >= 0 ? "goosebay"
    : HOST.indexOf("avalon") >= 0 || HOST.indexOf("stjohns") >= 0 ? "avalon"
    : "gander");
  var AREA = SITE === "goosebay" ? "Goose Bay" : SITE === "avalon" ? "Avalon" : "Gander-area";
  var RED = "#EA002A";
  // The SMS backend (sms-subscribe + Twilio + inbound webhook + matcher) is
  // single-homed on realestategander.com. On Gander this is same-origin; on
  // sibling sites (Avalon/Goosebay) we POST cross-origin (CORS-allowlisted).
  var SUBSCRIBE_URL = SITE === "gander"
    ? "/api/sms-subscribe"
    : "https://realestategander.com/api/sms-subscribe";

  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function render(box, i) {
    if (box.getAttribute("data-lta-ready")) return;
    box.setAttribute("data-lta-ready", "1");
    var light = box.getAttribute("data-lta-theme") === "light";
    // data-lta-icon="1" (2026-08-20, homepage redesign): a phone icon inside
    // the field + a slightly larger radius + a soft glow on the button.
    // Opt-in only -- every other call site (the listing/city footer band,
    // the community cmx-alert-widget) renders byte-identically to before.
    var icon = box.getAttribute("data-lta-icon") === "1";
    var city = (box.getAttribute("data-lta-city") || "").trim();
    var label = box.getAttribute("data-lta-label")
      || (city ? ("New listings in " + city) : ("All new " + AREA + " listings"));
    var id = "lta" + i;
    var fg = light ? "#1f1f1f" : "#fff";
    var sub = light ? "#555" : "#cdcdcd";
    var fieldBg = light ? "#fff" : "#1a1a1a";
    var fieldBd = light ? "#ccc" : "#333";
    var radius = icon ? "6px" : "4px";
    var fieldPad = icon ? "14px 18px 14px 44px" : "14px 18px";
    var btnShadow = icon ? "box-shadow:0 8px 24px -8px rgba(234,0,42,.45);" : "";
    var fieldFlex = icon ? "width:100%;" : "flex:1 1 220px;";
    var phoneIconSvg = icon
      ? '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="' + fg + '" stroke-width="2" ' +
        'style="position:absolute;left:16px;top:50%;transform:translateY(-50%);opacity:.55;pointer-events:none">' +
        '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.362 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>'
      : "";
    var fieldWrapOpen = icon ? '<div style="position:relative;flex:1 1 220px;min-width:0;">' : "";
    var fieldWrapClose = icon ? "</div>" : "";
    box.innerHTML =
      '<form id="' + id + '-form" novalidate autocomplete="on" style="margin:0;">' +
        // honeypot (bots)
        '<input type="text" id="' + id + '-hp" tabindex="-1" autocomplete="off" ' +
          'style="position:absolute;left:-9999px;width:1px;height:1px;opacity:0;" aria-hidden="true">' +
        '<div style="display:flex;flex-wrap:wrap;gap:10px;align-items:stretch;">' +
          fieldWrapOpen +
            phoneIconSvg +
            '<input id="' + id + '-phone" type="tel" inputmode="tel" autocomplete="tel" ' +
              'placeholder="Your cell number" aria-label="Your cell phone number" ' +
              'style="' + fieldFlex + 'min-width:0;padding:' + fieldPad + ';border-radius:' + radius + ';border:1px solid ' + fieldBd + ';' +
              'background:' + fieldBg + ';color:' + fg + ';font-size:1rem;font-family:Roboto,sans-serif;">' +
          fieldWrapClose +
          '<button id="' + id + '-go" type="submit" ' +
            'style="flex:0 0 auto;padding:14px 26px;border:0;border-radius:' + radius + ';background:' + RED + ';color:#fff;' +
            'font-family:Raleway,sans-serif;font-weight:700;font-size:0.9rem;letter-spacing:0.5px;text-transform:uppercase;cursor:pointer;white-space:nowrap;' + btnShadow + '">' +
            'Text me new listings</button>' +
        '</div>' +
        '<label for="' + id + '-consent" style="display:flex;gap:8px;align-items:flex-start;margin:11px 0 0;' +
          'color:' + sub + ';font-size:0.8rem;cursor:pointer;line-height:1.45;">' +
          '<input id="' + id + '-consent" type="checkbox" style="margin-top:3px;flex:0 0 auto;">' +
          '<span>I agree to receive recurring text alerts from Royal LePage Turner Realty. ' +
          'Msg &amp; data rates may apply. Reply STOP to cancel, HELP for help. No account needed — ' +
          'just reply YES to the confirmation text.</span>' +
        '</label>' +
        '<p id="' + id + '-msg" role="status" aria-live="polite" ' +
          'style="margin:8px 0 0;font-size:0.85rem;min-height:1em;color:#d66;"></p>' +
      '</form>';

    if (typeof window.gtag === "function") {
      try { gtag("event", "sms_upsell_shown", { placement: "alert-inline", site: SITE }); } catch (e) {}
    }

    var form = document.getElementById(id + "-form");
    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var msg = document.getElementById(id + "-msg");
      var go = document.getElementById(id + "-go");
      if (document.getElementById(id + "-hp").value) return; // bot
      var phone = (document.getElementById(id + "-phone").value || "").trim();
      var consent = document.getElementById(id + "-consent").checked;
      msg.style.color = "#d66";
      if (phone.replace(/\D/g, "").length < 10) { msg.textContent = "Please enter a valid 10-digit cell number."; return; }
      if (!consent) { msg.textContent = "Please check the box to confirm you'd like text alerts."; return; }
      go.disabled = true; go.textContent = "Sending…";
      fetch(SUBSCRIBE_URL, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          phone: phone, site: SITE, consent: true,
          // Empty criteria means "every new listing on this site" — right for
          // a site-wide surface, wrong for a listing page. normalizeCriteria
          // on the server is the authority on shape; this just states intent.
          criteria: city ? { v: 2, cities: [city] } : {},
          criteria_label: label.slice(0, 120),
        }),
      }).then(function (r) { return r.json(); }).then(function (j) {
        if (j && (j.ok || j.status === "pending")) {
          if (typeof window.gtag === "function") {
            try { gtag("event", "sms_optin", { placement: "alert-inline", site: SITE }); } catch (e) {}
          }
          box.innerHTML =
            '<div style="text-align:center;padding:6px 0;">' +
              '<h3 style="margin:0 0 6px;font-family:Raleway,sans-serif;font-weight:800;color:' + fg + ';">' +
              'Check your phone</h3>' +
              '<p style="margin:0;color:' + sub + ';font-size:0.92rem;line-height:1.5;">' +
              'We just texted you — <strong>reply YES</strong> to confirm and you’ll start getting new ' +
              esc(AREA) + ' listings the moment they hit the market.</p>' +
            '</div>';
        } else {
          var reason = j && j.reason;
          msg.textContent = reason === "consent_required"
            ? "Please check the consent box to receive texts."
            : reason === "bad_phone"
            ? "That doesn’t look like a valid cell number — please check it."
            : "Sorry, something went wrong. Please try again or call us at " + ((window.SITE && window.SITE.phone) || "709-256-7999") + ".";
          go.disabled = false; go.innerHTML = "Text me new listings";
        }
      }).catch(function () {
        msg.textContent = "Network error — please try again or call " + ((window.SITE && window.SITE.phone) || "709-256-7999") + ".";
        go.disabled = false; go.innerHTML = "Text me new listings";
      });
    });
  }

  function init() {
    var boxes = document.querySelectorAll("[data-lta-inline]");
    for (var i = 0; i < boxes.length; i++) render(boxes[i], i);
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
