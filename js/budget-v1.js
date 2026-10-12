/* budget-v1.js -- the whole ownership budget (portal idea 1, Mike D-1009-30 "Portal top 3: plan approved as drawn, order budget ->
 * shortlist -> passport"; drawn in _ops/previews/2026-10-09/redesign_portal_budget_*, plan _research/Portal_Ideas_Plan_2026-10-09.md s.1).
 *
 * Tier-1, byte-identical on Gander, Avalon and Goose Bay (D-1008-25). One sheet per listing, shown two ways: (a) on a listing detail page,
 * opened from a "What would this home cost each month?" line under the price; (b) as the page /budget/?mls=<id>. Both run only while
 * OWNERSHIP_BUDGET is on (SITE.ownershipBudget === 'v1' in js/nav-config.js; ?budget=v1 previews on any page, ?budget=off switches the
 * preview off). Off, this file adds nothing: no line, no sheet, and /budget/ keeps the plain note it ships with.
 *
 * Where each figure comes from (always-on #35: a record, a visitor input, or a labelled assumption the visitor can change; nothing else):
 *  - price: the LIST price from the listing record. No sold price is read or shown anywhere (VOW).
 *  - mortgage: the formulas below are the mortgage calculator's own, copied line for line from pages/mortgage-calculator.html
 *    (monRate, payment, cmhcRate, minDown, deedFee); tools/tests/budget-v1-test.mjs fails if either side changes alone.
 *    Starting figures 20% down, 5.49%, 25 years are the ones the listing page's "Est. $X/mo" line already uses.
 *  - property taxes: the record's Taxamount (a year) when the listing carries it; else "ask the town". Condo fee: the record, only when > 0.
 *  - heating, electricity, insurance, water and sewer, maintenance: never a dollar guess; blank until the visitor types a number.
 *  - cash to close: the down payment and the closing-cost calculator's own registry-fee formula and 15% HST (pages/closing-cost-calculator-nl.html);
 *    legal, title and inspection are blank until the visitor types a quote.
 * The record is the inert JSON island <script id="budget-record"> that the page generator writes on each detail page; the /budget/ page
 * reads the same island from the listing's page (the listing list is /listings/data.json, as the compare page reads it).
 */
(function () {
  "use strict";

  var CSS_STAMP = "e12f83b5"; // first 8 hex of sha256 of css/budget-v1.css (checked by budget-v1-test)
  var SELF_SRC = (typeof document !== "undefined" && document.currentScript && document.currentScript.src) || "";
  var DEFAULTS = { down: "20", rate: "5.49", amort: "25" };

  /* ---- the mortgage and closing-cost calculators' formulas, verbatim from pages/mortgage-calculator.html ---- */
  function fmt(n){return '$'+Math.round(n).toLocaleString('en-CA');}
  function deedFee(a){if(a<=0)return 0;if(a<=500)return 100;return Math.min(100+Math.ceil((a-500)/100)*0.40,5000);}
  function minDown(p){return p<=500000?p*0.05:500000*0.05+(p-500000)*0.10;}
  function cmhcRate(dp){if(dp>=0.20)return 0;if(dp>=0.15)return 0.028;if(dp>=0.10)return 0.031;return 0.040;}
  function monRate(annualPct){return Math.pow(1+(annualPct/100)/2,1/6)-1;}
  function payment(P,r,n){return r===0?P/n:P*(r*Math.pow(1+r,n))/(Math.pow(1+r,n)-1);}
  /* ---- end of the copied formulas ---- */

  function on() {
    var q = (typeof window !== "undefined" && window.location && window.location.search) || "";
    if (/[?&]budget=off(&|$)/.test(q)) return false;
    if (/[?&]budget=v1(&|$)/.test(q)) return true;
    return !!(window.SITE && window.SITE.ownershipBudget === "v1");
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  /* A typed or recorded number: null when blank, not a number or negative. A blank is never 0. */
  function num(v) {
    if (v == null) return null;
    var s = String(v).replace(/[$,\s]/g, "");
    if (s === "") return null;
    var n = Number(s);
    return isFinite(n) && n >= 0 ? n : null;
  }
  function pos(v) { var n = num(v); return n != null && n > 0 ? n : null; }

  /* The mortgage at one price with the visitor's down payment, rate and amortization (the calculator's own order of steps). */
  function mortgageAt(price, st) {
    var dpPctRaw = num(st.down); if (dpPctRaw == null) dpPctRaw = Number(DEFAULTS.down);
    var dpPct = Math.min(50, Math.max(1.5, dpPctRaw));
    var rate = num(st.rate); if (rate == null) rate = Number(DEFAULTS.rate);
    var yrs = num(st.amort); if (yrs == null || yrs < 1) yrs = Number(DEFAULTS.amort);
    var down = price * (dpPct / 100);
    var base = Math.max(0, price - down);
    var cmhc = base * cmhcRate(dpPct / 100);
    var mort = base + cmhc;
    return { dpPct: dpPct, rate: rate, yrs: yrs, down: down, base: base, cmhc: cmhc, mort: mort, pi: payment(mort, monRate(rate), yrs * 12), minDown: minDown(price) };
  }

  /* model(rec, st) -> everything the sheet shows, as data. rec: {price, tax, taxYear, heating, condo, sub, ...}; st: the visitor's inputs. */
  function model(rec, st) {
    var price = pos(rec.price);
    var m = price ? mortgageAt(price, st) : null;
    var lines = [];
    lines.push({ key: "mortgage", label: "Mortgage payment", chip: "est", monthly: m ? m.pi : null,
      sub: m ? "list price " + fmt(price) + ", " + m.dpPct + "% down, " + m.rate + "%, " + m.yrs + " years" + (m.cmhc > 0 ? ", with the CMHC premium added" : "") + ": your lender's quote replaces these" : "no list price in the record" });
    var tax = pos(rec.tax), taxIn = pos(st.tax);
    lines.push({ key: "tax", label: "Property taxes", chip: tax ? "rec" : "unk", monthly: tax ? tax / 12 : (taxIn ? taxIn / 12 : null), fixed: !!tax, input: !tax, ask: "ask the town", unit: "a year",
      sub: tax ? fmt(tax) + " a year" + (rec.taxYear ? " (" + rec.taxYear + ")" : "") + ", from the MLS® record, divided by 12" : "not in this listing's record: ask the town for the yearly bill" });
    var heatType = rec.heating ? String(rec.heating).split(",").map(function (s) { return s.trim(); }).filter(Boolean).join(", ") : "";
    lines.push({ key: "heat", label: "Heating", chip: "sel", monthly: pos(st.heat), input: true, ask: "ask the seller", unit: "a month",
      sub: (heatType ? "Heating in the record: " + heatType + ". " : "") + "Ask the seller for the last 12 months' bills, divided by 12" });
    lines.push({ key: "elec", label: "Electricity", chip: "sel", monthly: pos(st.elec), input: true, ask: "ask the seller", unit: "a month", sub: "Ask the seller for the last 12 months' bills, divided by 12" });
    lines.push({ key: "ins", label: "Home insurance", chip: "est", monthly: pos(st.ins), input: true, ask: "your quote", unit: "a month", sub: "Type your insurer's quote in" });
    lines.push({ key: "water", label: "Water and sewer", chip: "unk", monthly: pos(st.water), input: true, ask: "municipal rate; confirm", unit: "a month", sub: "The town's rate for this address: confirm it with the town" });
    lines.push({ key: "maint", label: "Maintenance reserve", chip: "est", monthly: pos(st.maint), input: true, ask: "your choice", unit: "a month", sub: "What you choose to set aside; left blank until you type it" });
    var condo = pos(rec.condo);
    if (condo) lines.push({ key: "condo", label: "Condo fee", chip: "rec", monthly: condo, fixed: true, sub: "Monthly fee, from the MLS® record" });
    var rest = 0, blanks = 0, i;
    for (i = 1; i < lines.length; i++) { if (lines[i].monthly == null) blanks++; else rest += lines[i].monthly; }
    var total = m ? m.pi + rest : null;
    if (!m) { for (i = 0; i < lines.length; i++) if (lines[i].monthly != null) total = (total || 0) + lines[i].monthly; }

    var offer = pos(st.offer), offerM = offer ? mortgageAt(offer, st) : null;
    var rent = pos(st.rent);
    var sc = { listed: total, offer: offerM ? offerM.pi + rest : null, offerPrice: offer,
      suite: String(rec.sub || "") === "2-Apartment", suiteTotal: (total != null && rent) ? total - rent : null, rent: rent };

    var legal = num(st.legal), title = num(st.title), insp = num(st.insp);
    var cash = null;
    if (m) {
      var service = (legal || 0) + (title || 0) + (insp || 0), hst = service > 0 ? service * 0.15 : null;
      var dP = deedFee(price), dM = deedFee(m.mort);
      cash = { down: m.down, deedP: dP, deedM: dM, legal: legal, title: title, insp: insp, hst: hst, total: m.down + dP + dM + service + (hst || 0), dpPct: m.dpPct, minDown: m.minDown };
    }
    return { price: price, m: m, lines: lines, total: total, blanks: blanks, sc: sc, cash: cash, hasTax: !!tax };
  }

  var CHIP = { rec: "Official record", sel: "Seller-provided", est: "Estimate", unk: "Awaiting confirmation" };
  function chip(k) { return '<span class="bgt-chip bgt-chip--' + k + '">' + CHIP[k] + '</span>'; }
  function inp(key, st, ph, aria, extra) {
    return '<input class="bgt-in" type="text" inputmode="decimal" autocomplete="off" data-in="' + key + '" value="' + esc(st[key] == null ? "" : st[key]) + '" placeholder="' + esc(ph) + '" aria-label="' + esc(aria) + '"' + (extra || "") + '>';
  }
  function money(n) { var r = Math.round(n); return (r < 0 ? "-" : "") + fmt(Math.abs(r)); }

  function sheetHtml(rec, st, md, page) {
    var addr = [rec.street, rec.city].filter(Boolean).join(", ");
    var h = '<div class="bgt-scope' + (page ? ' bgt-page' : ' bgt-sheet') + '">';
    if (page) {
      h += '<p class="bgt-eyebrow">Whole ownership budget' + (addr ? ' &middot; ' + esc(addr) : '') + '</p>' +
        '<h1 class="bgt-h1">What this home costs to own, not just to buy</h1>' +
        '<p class="bgt-sub">One sheet: the mortgage, the taxes, the heat, the insurance, the upkeep, the cash to close. Every line says where its number came from; you replace any of them with your own quote and the total follows.</p>';
    }
    h += '<div class="bgt-legend"><span>' + chip("rec") + ' the MLS&reg; record</span><span>' + chip("sel") + ' the seller gives it</span><span>' + chip("est") + ' a calculation or your quote</span><span>' + chip("unk") + ' not known yet</span></div>';
    h += '<div class="bgt-grid"><div class="bgt-card"><h3>Each month</h3>';
    h += '<div class="bgt-assume"><label>Down payment (%)' + inp("down", st, DEFAULTS.down, "Down payment, percent") + '</label><label>Rate (%)' + inp("rate", st, DEFAULTS.rate, "Mortgage rate, percent") + '</label><label>Amortization (years)' + inp("amort", st, DEFAULTS.amort, "Amortization, years") + '</label></div>';
    h += '<p class="bgt-note">Starting figures from our mortgage calculator; your lender\'s quote replaces them' + (md.m ? '. Minimum down payment at this price: ' + fmt(md.m.minDown) : '') + '.</p>';
    md.lines.forEach(function (L) {
      var v;
      if (L.fixed) v = '<span class="bgt-v">' + fmt(L.monthly) + '/mo</span>';
      else if (L.input) v = '<span class="bgt-v">' + inp(L.key, st, L.ask, L.label + ", " + L.unit) + '</span>';
      else v = '<span class="bgt-v">' + (L.monthly != null ? fmt(L.monthly) + '/mo' : '') + '</span>';
      h += '<div class="bgt-row" data-line="' + L.key + '"><span class="bgt-k">' + esc(L.label) + '<small>' + esc(L.sub) + '</small></span>' + chip(L.chip) + v + '</div>';
    });
    h += '<div class="bgt-total"><span>Known so far</span><span>' + (md.total != null ? fmt(md.total) + '/month' : 'unknown') +
      (md.blanks ? '<small>+ the ' + md.blanks + ' blank line' + (md.blanks === 1 ? '' : 's') + ' above once known</small>' : '') + '</span></div></div>';

    h += '<div class="bgt-card"><h3>Cash to close</h3>';
    if (md.cash) {
      var c = md.cash;
      h += '<dl class="bgt-dl"><dt>Down payment (' + c.dpPct + '%) ' + chip("est") + '</dt><dd>' + fmt(c.down) + '</dd>' +
        '<dt>Registry of Deeds, on the price ' + chip("est") + '</dt><dd>' + fmt(c.deedP) + '</dd>' +
        '<dt>Registry of Deeds, on the mortgage ' + chip("est") + '</dt><dd>' + fmt(c.deedM) + '</dd>' +
        '<dt>Legal fees</dt><dd>' + inp("legal", st, "your quote", "Legal fees, dollars") + '</dd>' +
        '<dt>Title insurance</dt><dd>' + inp("title", st, "your quote", "Title insurance, dollars") + '</dd>' +
        '<dt>Home inspection</dt><dd>' + inp("insp", st, "your quote", "Home inspection, dollars") + '</dd>' +
        '<dt>HST on those three</dt><dd>' + (c.hst != null ? fmt(c.hst) : '') + '</dd>' +
        '<dt>Adjustments (taxes, oil in the tank) ' + chip("unk") + '</dt><dd>at closing</dd></dl>';
      h += '<div class="bgt-total"><span>Known so far</span><span>' + fmt(c.total) + '</span></div>';
      h += '<p class="bgt-note">The registry fees are the closing-cost calculator\'s formula. Legal, title insurance and inspection stay blank until you type your quotes, and HST follows them. Adjustments are settled at closing and are not guessed here.</p>';
    } else h += '<p class="bgt-note">Needs a list price.</p>';
    h += '</div></div>';

    h += '<div class="bgt-scen"><div class="bgt-card"><b>As listed</b><span class="bgt-big">' + (md.sc.listed != null ? fmt(md.sc.listed) : 'unknown') + '</span>/month known so far</div>';
    h += '<div class="bgt-card"><b>Your offer</b><label class="bgt-field">Offer price' + inp("offer", st, "type an offer", "Your offer price, dollars") + '</label>' +
      '<p class="bgt-note" style="margin-top:8px">' + (md.sc.offer != null ? '<span class="bgt-big">' + fmt(md.sc.offer) + '</span>/month known so far, your number, your scenario' : 'Type a price to see the monthly figure at your offer') + '</p></div>';
    if (md.sc.suite) {
      h += '<div class="bgt-card"><b>With a rental suite</b><label class="bgt-field">Monthly rent you expect from the suite' + inp("rent", st, "your number", "Monthly rent from the suite, dollars") + '</label>' +
        '<p class="bgt-note" style="margin-top:8px">' + (md.sc.suiteTotal != null ? '<span class="bgt-big">' + money(md.sc.suiteTotal) + '</span>/month known so far, after your rent' : 'The record says 2-Apartment. We hold no market rent, so the figure appears once you type one') + '</p></div>';
    }
    h += '</div>';
    h += '<div class="bgt-real"><b>What is real here:</b> the list price ' + (md.price ? fmt(md.price) : 'is not in the record') + ' is the record; the mortgage line is a calculation from the labelled assumptions above (the formula the mortgage calculator uses); the taxes line is the record only when the listing carries it (this one: ' + (md.hasTax ? 'yes' : 'no') + '); every other line is blank until you type a number. The total is only what is known so far.' +
      '<div class="bgt-links"><a href="/pages/mortgage-calculator.html' + (md.price ? '?price=' + Math.round(md.price) : '') + '">Mortgage calculator</a><a href="/pages/closing-cost-calculator-nl.html' + (md.price ? '?price=' + Math.round(md.price) : '') + '">Closing-cost calculator</a>' +
      (page ? '' : '<a href="/budget/?mls=' + encodeURIComponent(rec.mls || "") + '">Open as its own page</a>') + '</div></div></div>';
    return h;
  }

  /* Redraw on every input, then put the cursor back where the visitor was typing. */
  function mount(el, rec, page) {
    var st = {};
    function draw(focusKey, caret) {
      el.innerHTML = sheetHtml(rec, st, model(rec, st), page);
      if (focusKey) {
        var f = el.querySelector('[data-in="' + focusKey + '"]');
        if (f) { f.focus(); try { f.setSelectionRange(caret, caret); } catch (e) { /* not a text field */ } }
      }
    }
    el.addEventListener("input", function (ev) {
      var t = ev.target;
      if (!t || !t.getAttribute) return;
      var k = t.getAttribute("data-in");
      if (!k) return;
      st[k] = t.value;
      draw(k, t.selectionStart == null ? String(t.value).length : t.selectionStart);
    });
    draw();
  }

  function loadCss() {
    if (document.querySelector("link[data-budget-v1]")) return;
    var base = SELF_SRC && /js\/budget-v1\.js(\?[^#]*)?(#.*)?$/.test(SELF_SRC) ? SELF_SRC.replace(/js\/budget-v1\.js(\?[^#]*)?(#.*)?$/, "css/budget-v1.css") : "/css/budget-v1.css";
    var l = document.createElement("link");
    l.rel = "stylesheet"; l.href = base + "?v=" + CSS_STAMP; l.setAttribute("data-budget-v1", "1");
    document.head.appendChild(l);
  }

  /* The record island on a page (text of the page or of the document). */
  function parseRecord(html) {
    var m = /<script[^>]*id="budget-record"[^>]*>([\s\S]*?)<\/script>/.exec(String(html || ""));
    if (!m) return null;
    try { return JSON.parse(m[1]); } catch (e) { return null; }
  }

  function runDetail() {
    var node = document.getElementById("budget-record");
    if (!node) return;
    var rec; try { rec = JSON.parse(node.textContent); } catch (e) { return; }
    if (!rec || !pos(rec.price)) return;
    var anchor = document.querySelector('a[href*="mortgage-calculator.html?price="]');
    var p = anchor && anchor.closest ? anchor.closest("p") : null;
    if (!p) return;
    while (p.nextElementSibling && p.nextElementSibling.tagName === "P" && /all-in/.test(p.nextElementSibling.textContent)) p = p.nextElementSibling;
    loadCss();
    var line = document.createElement("p");
    line.className = "bgt-scope bgt-line";
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "bgt-open"; btn.setAttribute("aria-expanded", "false");
    btn.textContent = "What would this home cost each month?";
    line.appendChild(btn);
    var box = document.createElement("div");
    box.hidden = true; box.id = "bgt-sheet-box";
    btn.setAttribute("aria-controls", "bgt-sheet-box");
    p.parentNode.insertBefore(line, p.nextSibling);
    /* On a phone the price banner collapses to a strip once the photo scrolls away (.lst-detail-banner.is-compact hides everything inside it),
       so the sheet goes after the banner, not inside it: the line stays under the price, the sheet stays put while you read it. */
    var ban = line.closest ? line.closest(".lst-detail-banner") : null;
    if (ban && ban.parentNode) ban.parentNode.insertBefore(box, ban.nextSibling); else line.parentNode.insertBefore(box, line.nextSibling);
    var mounted = false;
    btn.addEventListener("click", function () {
      var open = box.hidden;
      box.hidden = !open;
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && !mounted) { mounted = true; mount(box, rec, false); }
      /* On a phone the fixed Call / Text / Book bar (.mab-bar) would sit over the sheet's first inputs when it opens below the fold: bring the
         sheet's top to the top of the screen (css/budget-v1.css gives it the scroll-margin that clears the header and the bar). */
      if (open && box.scrollIntoView) { try { box.scrollIntoView({ block: "start" }); } catch (e) { box.scrollIntoView(true); } }
    });
  }

  function runPage(content) {
    loadCss();
    var q = new URLSearchParams(window.location.search);
    var mls = (q.get("mls") || "").trim();
    if (!mls) { content.innerHTML = '<p class="bgt-empty bgt-scope">Pick a home first. <a href="/listings/">Browse listings</a>, open one and use "What would this home cost each month?".</p>'; return; }
    content.innerHTML = '<p class="bgt-empty bgt-scope">Loading the sheet…</p>';
    fetch("/listings/data.json").then(function (r) { return r.json(); }).then(function (data) {
      var rows = (data && data.listings) ? data.listings : (Array.isArray(data) ? data : []);
      var row = null;
      for (var i = 0; i < rows.length; i++) if (String(rows[i].mls) === mls) { row = rows[i]; break; }
      if (!row) { content.innerHTML = '<p class="bgt-empty bgt-scope">That home is no longer listed. It may have sold or been withdrawn. <a href="/listings/">Back to listings</a>.</p>'; return; }
      if (row.is_lease) { content.innerHTML = '<p class="bgt-empty bgt-scope">This is a lease listing; the ownership budget is for homes for sale. <a href="/listings/">Back to listings</a>.</p>'; return; }
      var rec = { mls: String(row.mls), price: row.price, street: row.street, city: row.city, sub: row.psub };
      var done = function (isl) {
        if (isl) { ["tax", "taxYear", "heating", "condo"].forEach(function (k) { if (isl[k] != null) rec[k] = isl[k]; }); if (isl.sub) rec.sub = isl.sub; }
        mount(content, rec, true);
      };
      if (!row.url) { done(null); return; }
      fetch(row.url).then(function (r) { return r.text(); }).then(function (t) { done(parseRecord(t)); }).catch(function () { done(null); });
    }).catch(function () {
      content.innerHTML = '<p class="bgt-empty bgt-scope">Could not load the listings. <a href="/listings/">Back to listings</a>.</p>';
    });
  }

  function run() {
    if (!on()) return;
    var content = document.getElementById("bgt-content");
    if (content) runPage(content); else runDetail();
  }

  var api = { model: model, sheetHtml: sheetHtml, parseRecord: parseRecord, mortgageAt: mortgageAt, on: on, fmt: fmt, payment: payment, monRate: monRate, cmhcRate: cmhcRate, deedFee: deedFee, minDown: minDown, DEFAULTS: DEFAULTS };
  if (typeof window !== "undefined") window.TurnerBudget = api;
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof document !== "undefined") {
    if (document.readyState === "complete" || (document.readyState === "interactive" && window.SITE)) run();
    else document.addEventListener("DOMContentLoaded", run);
  }
})();
