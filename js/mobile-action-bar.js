/**
 * Site-owned mobile/tablet bottom action bar (Tier-1, byte-identical
 * across the fleet) -- fleet/canonical/js/mobile-action-bar.js.
 *
 * Replaces two older, redundant, per-mechanism bars:
 *   - Gander's per-generator `.lst-mobile-cta` (listing-detail pages only)
 *   - `js/boldtrail-forms.js`'s `.rf-sticky-bar` (marketing pages, on all
 *     3 sites -- `stickyBar()` is now a no-op there, see that file)
 * with ONE bar, shown on every page under 1024px wide: Call + Text
 * (always) plus one page-specific third action.
 *
 * Page-type detection prefers a real DOM signal over the URL, since a
 * DOM marker is true regardless of how deep/aliased a URL is (mirrors
 * the reasoning in js/app-shell.js's pathIsListing()/pathIsHome()):
 *   - #lst-showing-form present (the BoldTrailForms booking panel)
 *       -> listing-detail  -> "Book a Showing"
 *   - <main class="ldisc-cards"> present (the listings-discover shell)
 *       -> listings index  -> "Alerts" (Listing Text/Email Alerts signup)
 *   - anything else (homepage included -- no distinguishing DOM marker
 *     exists there today, same gap app-shell.js works around with a
 *     path check) -> "Home Value"
 *
 * Requires js/nav-config.js loaded first (window.SITE.phone/phoneTel).
 * Docks js/chat-widget.js's bubble above itself via the `.mab-bar`
 * selector already added to that file's positionWidget().
 *
 * Mike 2026-09-17, "Mobile + iPad review of the fleet" plan, Part 1
 * Tier B, row B1.
 */
(function () {
  'use strict';
  if (document.querySelector('.mab-bar')) return; // idempotent — never double-mount

  // ── Keyboard watch (shared snippet, fleet 2026-10-06) ───────────────────
  // Same block is carried by js/app-shell.js, js/mobile-action-bar.js and
  // js/chat-widget.js; whichever runs first installs it (window.__tnrKbWatch).
  // Sets html.tnr-kb-open while a phone keyboard is up: the visual viewport is
  // much shorter than the layout viewport, OR (touch devices) a text field has
  // focus. CSS keyed on that class hides the sticky Call/Text/Book bar, the
  // chat launcher, the "Get the app" card and the Registry pill; the chat
  // panel sizes itself to the visual viewport. Fires "tnr:keyboard".
  (function () {
    if (window.__tnrKbWatch) return;
    window.__tnrKbWatch = true;
    var root = document.documentElement, vv = window.visualViewport;
    var on = false, focused = false, timer = null, touch = false;
    try { touch = (navigator.maxTouchPoints || 0) > 0 || (window.matchMedia && window.matchMedia("(pointer:coarse)").matches); } catch (e) {}
    function isField(el) {
      if (!el || el.nodeType !== 1) return false;
      if (el.tagName === "TEXTAREA") return !el.readOnly;
      if (el.tagName === "INPUT") return !/^(button|checkbox|radio|submit|reset|file|image|range|color|hidden|date|time|datetime-local|month|week)$/i.test(el.type || "text");
      return !!el.isContentEditable;
    }
    function update() {
      var shrunk = !!vv && vv.scale <= 1.02 && (window.innerHeight - vv.height) > 150;
      var now = shrunk || (touch && focused);
      if (now === on) return;
      on = now;
      root.classList.toggle("tnr-kb-open", on);
      try { window.dispatchEvent(new CustomEvent("tnr:keyboard", { detail: { open: on } })); } catch (e) {}
    }
    document.addEventListener("focusin", function (e) { focused = isField(e.target); update(); });
    document.addEventListener("focusout", function () {
      clearTimeout(timer);
      timer = setTimeout(function () { focused = isField(document.activeElement); update(); }, 80);
    });
    if (vv) vv.addEventListener("resize", update);
  })();

  // ── Form clearance (FORM_CLEAR, redesign 2026-10-09, Mike D-1009-77 item 5) ──
  // On a phone nothing may sit over a form's fields or its submit button. While a
  // form is in the viewport, or any field of a form has focus, this sets
  // html.tnr-form-clear. CSS keyed on that class hides the Call/Text/Book bar
  // (css/mobile-action-bar.css), the "Get the app" card (css/app-shell.css) and
  // the chat launcher (js/chat-widget.js, unless its panel is open). The class is
  // never set on a screen wider than 1023px, so desktop is untouched.
  // Switch FORM_CLEAR: window.SITE.formClear === 'on' in js/nav-config.js (default
  // 'off'); ?formclear=on previews it on one page, ?formclear=off forces it off.
  // With the switch off this block returns before it touches the page at all.
  // "In the viewport" = the form overlaps the strip between the header (56px) and
  // the bar (64px): that is where its fields and submit can be reached and covered.
  // Forms = the showing/inquiry panels plus any other <form> with 2+ fields that is
  // not in the header, nav, footer, chat panel or a role=search form.
  (function () {
    var Q = location.search || '', S = window.SITE || {};
    var on = /[?&]formclear=on(&|$)/.test(Q) || (S.formClear === 'on' && !/[?&]formclear=off(&|$)/.test(Q));
    if (!on || window.__tnrFormClear) return;
    window.__tnrFormClear = true;
    var root = document.documentElement, mq = null, io = null, seen = [], inView = {}, nIn = 0, focused = false, timer = null;
    try { mq = window.matchMedia('(max-width: 1023px)'); } catch (e) {}
    var FIELD = 'input:not([type=hidden]):not([type=checkbox]):not([type=radio]):not([type=submit]):not([type=button]),textarea,select';
    function phone() { return mq ? mq.matches : window.innerWidth < 1024; }
    function skip(el) { return !!(el.closest && el.closest('header,nav,footer,#tc-panel,[role=search]')) || el.getAttribute('role') === 'search'; }
    function insideForm(el) {
      return !!(el && el.closest && el.closest('form,#lst-showing-form,#lst-commercial-inquiry,#lst-inquiry-form') && !skip(el));
    }
    function isField(el) { return !!el && el.nodeType === 1 && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) && el.type !== 'hidden'; }
    function apply() {
      var now = phone() && (nIn > 0 || focused);
      if (root.classList.contains('tnr-form-clear') === now) return;
      root.classList.toggle('tnr-form-clear', now);
      try { window.dispatchEvent(new CustomEvent('tnr:floating')); } catch (e) {}
    }
    function watch(el) {
      if (seen.indexOf(el) > -1 || !io) return;
      seen.push(el); el.__tnrFcId = seen.length; io.observe(el);
    }
    function scan() {
      ['lst-showing-form', 'lst-commercial-inquiry', 'lst-inquiry-form'].forEach(function (id) {
        var el = document.getElementById(id); if (el) watch(el);
      });
      Array.prototype.forEach.call(document.querySelectorAll('form'), function (f) {
        if (!skip(f) && f.querySelectorAll(FIELD).length >= 2) watch(f);
      });
    }
    function start() {
      if (window.IntersectionObserver) {
        io = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            var id = en.target.__tnrFcId, was = !!inView[id];
            if (en.isIntersecting && !was) { inView[id] = true; nIn++; }
            else if (!en.isIntersecting && was) { inView[id] = false; nIn--; }
          });
          apply();
        }, { rootMargin: '-56px 0px -64px 0px', threshold: 0 });
      }
      scan();
      [600, 1500, 3500, 7000].forEach(function (ms) { setTimeout(scan, ms); }); // the forms mount async
      document.addEventListener('focusin', function (e) {
        if (!isField(e.target) || !insideForm(e.target)) return;
        focused = true; apply();
      });
      document.addEventListener('focusout', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { var a = document.activeElement; focused = isField(a) && insideForm(a); apply(); }, 80);
      });
      if (mq && mq.addEventListener) mq.addEventListener('change', apply); else window.addEventListener('resize', apply);
    }
    window.TurnerFormClear = { active: function () { return root.classList.contains('tnr-form-clear'); }, rescan: scan };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  })();

  var SITE = window.SITE || {};
  var phone = SITE.phone || '';
  var phoneTel = SITE.phoneTel || '';
  if (!phoneTel) return; // nothing sane to render without a number

  var ICONS = {
    call: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.127.96.362 1.903.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.907.338 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>',
    text: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>',
    calendar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    bell: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" aria-hidden="true"><path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>'
  };

  // A listing-detail page always carries one of these three panels --
  // #lst-showing-form for a residential listing, #lst-commercial-inquiry
  // or #lst-inquiry-form for a commercial one (Goose Bay's generator
  // variant) -- so checking all three is what makes a commercial listing
  // page correctly read as 'listing' too, not fall through to the
  // generic default.
  function bookingTarget() {
    return document.getElementById('lst-showing-form')
        || document.getElementById('lst-commercial-inquiry')
        || document.getElementById('lst-inquiry-form');
  }

  function pageKind() {
    if (bookingTarget()) return 'listing';
    if (document.querySelector('main.ldisc-cards')) return 'index';
    return 'home'; // homepage AND the default for every other marketing page
  }

  // Replicates the listing-detail page's own "Stage 4 mobile CTA" click
  // behaviour (tab activation + scroll + focus the date field) verbatim
  // -- that handler looks up its button by [data-action="scroll-to-showing"]
  // at parse time via a non-deferred inline <script>, which runs BEFORE
  // this deferred script mounts the new button, so it would silently
  // find nothing. Attaching directly here (rather than relying on that
  // handler re-finding this element later) is the reliable fix. The label
  // always reads "Book a Showing" (Goose Bay's commercial-only "Request
  // Info" wording isn't reproduced here -- a simplification per the B1
  // scope of one bar/one label set), but the scroll target still resolves
  // to whichever panel the page actually has.
  function bookShowingClick() {
    var showingTab = document.querySelector('.lst-rf-tab[data-rf-tab="showing"]');
    if (showingTab && !showingTab.classList.contains('active')) showingTab.click();
    var target = bookingTarget();
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'center' });
      setTimeout(function () {
        var dateInput = target.querySelector('input[name="showing_date"]');
        if (dateInput) dateInput.focus();
      }, 600);
    }
  }

  function mount() {
    if (document.querySelector('.mab-bar')) return;
    var kind = pageKind();

    var bar = document.createElement('div');
    bar.className = 'mab-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Quick actions');

    var call = document.createElement('a');
    call.className = 'mab-btn';
    call.href = 'tel:' + phoneTel;
    call.setAttribute('aria-label', 'Call ' + (phone || phoneTel));
    call.innerHTML = ICONS.call + '<span>Call</span>';

    var text = document.createElement('a');
    text.className = 'mab-btn';
    text.href = 'sms:+1' + phoneTel;
    text.setAttribute('aria-label', 'Text ' + (phone || phoneTel));
    text.innerHTML = ICONS.text + '<span>Text</span>';

    var third;
    if (kind === 'listing') {
      third = document.createElement('button');
      third.type = 'button';
      third.setAttribute('data-action', 'scroll-to-showing');
      third.setAttribute('aria-label', 'Scroll to Book a Showing form');
      third.innerHTML = ICONS.calendar + '<span>Book a Showing</span>';
      third.addEventListener('click', bookShowingClick);
    } else if (kind === 'index') {
      third = document.createElement('a');
      third.href = '/pages/text-alerts.html';
      third.innerHTML = ICONS.bell + '<span>Alerts</span>';
    } else {
      third = document.createElement('a');
      third.href = '/pages/home-value.html';
      third.innerHTML = ICONS.home + '<span>Home Value</span>';
    }
    third.className = 'mab-btn mab-btn-primary';

    bar.appendChild(call);
    bar.appendChild(text);
    bar.appendChild(third);

    document.body.appendChild(bar);
    document.body.classList.add('mab-active');
  }

  // A focused form field scrolls clear of the sticky bar. scroll-margin-bottom
  // in css/mobile-action-bar.css does this for browsers that honour it when
  // they scroll a focused control into view; this is the backstop for the
  // rest. While the phone keyboard is up the bar is hidden (display:none),
  // so this does nothing then.
  var FIELD_RE = /^(INPUT|TEXTAREA|SELECT)$/;
  document.addEventListener('focusin', function (e) {
    var el = e.target;
    if (!el || !FIELD_RE.test(el.tagName || '')) return;
    setTimeout(function () {
      try {
        var bar = document.querySelector('.mab-bar');
        if (!bar || getComputedStyle(bar).display === 'none') return;
        var limit = bar.getBoundingClientRect().top - 24;
        var r = el.getBoundingClientRect();
        if (r.bottom > limit) window.scrollBy({ top: r.bottom - limit, behavior: 'smooth' });
      } catch (err) { /* never break a page for scroll polish */ }
    }, 350);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
