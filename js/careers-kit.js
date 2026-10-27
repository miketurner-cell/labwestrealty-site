/* careers-kit.js -- the recruiting pages' "Talk to Mike" bar and short join form (sites session, B-1027-07; Mike D-1026-31,
 * D-1027-03, D-1027-17, D-1027-32, design 2 option A D-1027-43; spec _research/design_specs_2026-10-27/02_careers_pages.md).
 *
 * Byte-identical on realestategander.com, avalonrealestate.ca, goosebayrealestate.ca, labwestrealty.com and royallepageturner.com
 * (always-on #27); the copy in realestategander-site is the canonical one. Loaded ONLY by the careers / join / become-a-realtor /
 * first-year / why-join pages (tools/tests/careers-pages-test.py checks the list).
 *
 * 1. "Talk to Mike" on careers pages: under 861px a fixed bottom bar of three equal buttons Book - Call - Text (class "mab-bar tk-bar" so
 *    js/chat-widget.js knows it is there); from 861px the same three as a compact pill group in the header. The chat bubble, the
 *    Feedback tab and the "Get the app" card are hidden on these pages (one overlay at a time, D-1027-13/-14). The bar steps aside
 *    while the join form is on screen, so nothing covers Send.
 * 2. A short join form in any <div data-tk-join>: name, email, phone, licensed (3 choices), town, optional note. It posts to lead-receive
 *    exactly as the old Join Our Team form did (lead_source "Source: Join Our Team - Agent Recruiting" = the registry's recruiting lane,
 *    assignee Mike). It does NOT use the gated recruit-inquiry lane (RECRUIT_FORM) and does not switch any gate on.
 */
(function () {
  'use strict';
  if (window.__turnerCareersKit) return;
  window.__turnerCareersKit = true;

  // ONE place for the recruit contact details on this site's careers pages.
  var BOOKING_URL = 'https://calendar.app.google/3S7FJsvtkxxZf9Ja6';
  // Mike chose his cell for every recruit contact (D-1027-32, 2026-10-27). Change only these two lines.
  var RECRUIT_PHONE = '709-424-6517';
  // The cell takes texts, so the bar reads Book / Call / Text.
  var TEXT_ENABLED = true;
  var ENDPOINT = 'https://realestategander.com/.netlify/functions/lead-receive';
  var LEAD_SOURCE = 'Source: Join Our Team — Agent Recruiting';
  var MIKE_EMAIL = 'miketurner@royallepage.ca';
  // Privacy policy lives at /pages/privacy-policy.html on the three regional sites and /privacy-policy.html on Lab West and the hub.
  var PRIVACY_URL = /^\/pages\//.test(location.pathname) ? '/pages/privacy-policy.html' : '/privacy-policy.html';

  var tel = RECRUIT_PHONE.replace(/\D/g, '');
  var host = location.hostname;
  function siteId() {
    var s = (window.TURNER_SITE || '').toLowerCase();
    if (s) return s;
    if (/avalonrealestate/.test(host)) return 'avalon';
    if (/labwest/.test(host)) return 'labwest';
    if (/royallepageturner/.test(host)) return 'hub';
    if (/goosebay/.test(host)) return 'goosebay';
    return 'gander';
  }

  var ICON = {
    cal: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M3 10h18M8 3v4M16 3v4" stroke="currentColor" stroke-width="2" fill="none"/></svg>',
    tel: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.6 10.8a15.1 15.1 0 006.6 6.6l2.2-2.2a1 1 0 011-.25 11.4 11.4 0 003.6.57 1 1 0 011 1V20a1 1 0 01-1 1A17 17 0 013 4a1 1 0 011-1h3.5a1 1 0 011 1c0 1.25.2 2.45.57 3.6a1 1 0 01-.25 1z" fill="currentColor"/></svg>',
    sms: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 4h16a1 1 0 011 1v11a1 1 0 01-1 1H9l-5 4V5a1 1 0 011-1z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    warn: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l10 18H2z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M12 10v5M12 17.5v.5" stroke="currentColor" stroke-width="2"/></svg>'
  };

  var css = '' +
    '.tk-form{max-width:640px;margin:0 auto;background:#111;color:#fff;border:1px solid #1e1e1e;border-radius:12px;padding:24px 20px;font-family:Roboto,system-ui,-apple-system,"Segoe UI",sans-serif;text-align:left}' +
    '.tk-form *{box-sizing:border-box}' +
    '.tk-form h2{margin:0 0 6px;font:900 24px/1.25 Raleway,sans-serif;color:#fff}' +
    '.tk-form p.tk-sub{margin:0 0 16px;font-size:16px;line-height:1.5;color:rgba(255,255,255,.78)}' +
    '.tk-field{display:block;margin:0 0 16px;border:0;padding:0;min-width:0}' +
    '.tk-field>.tk-l,.tk-field>legend{display:block;margin:0 0 6px;padding:0;font-size:14px;font-weight:500;color:rgba(255,255,255,.78)}' +
    '.tk-opt{font-weight:300;color:rgba(255,255,255,.62)}' +
    '.tk-form input[type=text],.tk-form input[type=email],.tk-form input[type=tel],.tk-form textarea{display:block;width:100%;min-height:48px;padding:12px 14px;font:400 16px/1.3 Roboto,sans-serif;color:#fff;background:#141414;border:1px solid #5a5a5a;border-radius:6px}' +
    '.tk-form textarea{min-height:88px;resize:vertical}' +
    '.tk-form input::placeholder,.tk-form textarea::placeholder{color:rgba(255,255,255,.5)}' +
    '.tk-form input:focus,.tk-form textarea:focus{outline:3px solid #fff;outline-offset:1px}' +
    '.tk-field.bad input{border:2px solid #ff4d6d}' +
    '.tk-ferr{display:flex;gap:6px;align-items:flex-start;margin:6px 0 0;font-size:14px;color:#ff4d6d}' +
    '.tk-ferr svg{width:16px;height:16px;margin-top:2px;flex:none}' +
    '.tk-seg{display:flex;flex-wrap:wrap;gap:8px}' +
    '.tk-seg label{position:relative;display:inline-flex;align-items:center;min-height:44px;padding:0 16px;font-size:16px;color:#fff;background:#141414;border:1px solid #5a5a5a;border-radius:22px;cursor:pointer}' +
    '.tk-seg input{position:absolute;opacity:0;width:1px;height:1px}' +
    '.tk-seg label.on{border-color:#fff;background:#2a2a2a;font-weight:500}' +
    '.tk-seg label.on::before{content:"";width:8px;height:8px;margin-right:8px;border-radius:50%;background:#fff}' +
    '.tk-seg label:focus-within{outline:3px solid #fff;outline-offset:1px}' +
    '.tk-submit{display:flex;align-items:center;justify-content:center;width:100%;min-height:52px;margin:8px 0 0;padding:0 20px;background:#EA002A;color:#fff;border:0;border-radius:6px;font:800 17px Raleway,sans-serif;cursor:pointer}' +
    '.tk-submit[disabled]{opacity:.6;cursor:default}' +
    '.tk-consent{margin:12px 0 4px;font-size:14px;line-height:1.45;color:rgba(255,255,255,.78)}' +
    '.tk-consent a{color:#fff;text-decoration:underline}' +
    '.tk-chk{display:flex;align-items:center;gap:12px;min-height:44px;font-size:14px;color:rgba(255,255,255,.78);cursor:pointer}' +
    '.tk-chk input{width:22px;height:22px;margin:0;flex:none;accent-color:#EA002A}' +
    '.tk-err{display:none;gap:10px;align-items:flex-start;margin:0 0 16px;padding:12px 14px;font-size:14px;line-height:1.45;color:#fff;background:rgba(234,0,42,.1);border:1px solid #ff4d6d;border-radius:8px}' +
    '.tk-err svg{width:16px;height:16px;margin-top:2px;flex:none;color:#ff4d6d}' +
    '.tk-err a{color:#fff;text-decoration:underline}' +
    '.tk-ok{padding:8px 0;font-size:16px;line-height:1.5;color:rgba(255,255,255,.88)}.tk-ok a{color:#fff;text-decoration:underline}' +
    '.tk-hp{position:absolute!important;left:-9999px!important;width:1px;height:1px;overflow:hidden}' +
    '.tk-bar,.tk-talk{display:none}' +
    /* Talk to Mike, phone and small tablet: fixed bottom bar, three equal buttons (design 2) */
    '@media (max-width:860px){' +
      '.tk-bar{display:grid;grid-template-columns:repeat(3,1fr);position:fixed;left:0;right:0;bottom:0;z-index:95;height:56px;background:#161616;border-top:1px solid #2a2a2a;padding-bottom:env(safe-area-inset-bottom,0);box-sizing:content-box}' +
      '.tk-bar a{display:flex;align-items:center;justify-content:center;gap:8px;min-height:56px;color:#fff;text-decoration:none;font:800 15px Raleway,sans-serif;border-left:1px solid #2a2a2a}' +
      '.tk-bar a:first-child{border-left:0}.tk-bar a.tk-primary{background:#EA002A}' +
      '.tk-bar svg{width:20px;height:20px;flex:none}' +
      'body.tk-careers{padding-bottom:calc(72px + env(safe-area-inset-bottom,0))}' +
      'html.tk-form-clear .tk-bar{display:none!important}' +
    '}' +
    /* from 861px: a compact pill group at the right of the header */
    '@media (min-width:861px){' +
      '.tk-talk{display:flex;align-items:center;flex:none;margin-left:auto;border:1px solid rgba(255,255,255,.35);border-radius:24px;overflow:hidden;background:#161616;font-family:Raleway,sans-serif}' +
      '.tk-talk .tk-lbl{font:700 11px Raleway,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:rgba(255,255,255,.62);padding:0 10px 0 14px}' +
      '.tk-talk a{display:inline-flex;align-items:center;gap:6px;min-height:44px;padding:0 14px;color:#fff;text-decoration:none;font:800 13px Raleway,sans-serif;border-left:1px solid rgba(255,255,255,.2)}' +
      '.tk-talk svg{width:16px;height:16px;flex:none}' +
      '.tk-talk.tk-fixed{position:fixed;top:12px;right:12px;z-index:300}' +
      /* the header's red Free Evaluation and phone pills give way, so the hero's Book is the only red button (design 2) */
      'body.tk-careers .nav-main-bar .nav-cta-outline,body.tk-careers .nav-main-bar .nav-phone-pill,body.tk-careers .nav-main-bar .nav2-cta,body.tk-careers .nav-main-bar .nav2-phone{display:none!important}' +
    '}' +
    '@media (max-width:520px){.tk-form{padding:20px 16px}}' +
    'html{scroll-padding-top:72px;scroll-padding-bottom:72px}' +
    'html.tnr-kb-open .tk-bar{display:none!important}' +
    'body.tk-careers .mab-bar:not(.tk-bar),body.tk-careers .tsf-tab,body.tk-careers .tsf-card,body.tk-careers #tc-bubble,body.tk-careers #tc-panel,body.tk-careers #tnr-install-cta{display:none!important}';
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  // ── 1. Talk to Mike: bottom bar (phone) and header pill group (desktop) ──────────────────────────────
  function links(cls) {
    return '<a class="' + (cls ? 'tk-primary' : '') + '" href="' + BOOKING_URL + '" target="_blank" rel="noopener" data-tk="book">' + ICON.cal + 'Book</a>' +
      '<a href="tel:+1' + tel + '" aria-label="Call ' + RECRUIT_PHONE + '" data-tk="call">' + ICON.tel + 'Call</a>' +
      (TEXT_ENABLED ? '<a href="sms:+1' + tel + '" aria-label="Text ' + RECRUIT_PHONE + '" data-tk="text">' + ICON.sms + 'Text</a>' : '');
  }
  function mountBar() {
    if (document.querySelector('.tk-bar')) return;
    document.body.classList.add('tk-careers');
    var bar = document.createElement('div');
    bar.className = 'mab-bar tk-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Talk to Mike');
    bar.innerHTML = links(true);
    document.body.appendChild(bar);
    dropGenericBar();
    window.setTimeout(dropGenericBar, 400);
    window.setTimeout(dropGenericBar, 1500);
    try { window.dispatchEvent(new Event('resize')); } catch (e) { /* chat widget re-measures on resize */ }
  }
  // The fleet's generic Call/Text/Home Value bar (js/mobile-action-bar.js) is replaced on these pages.
  function dropGenericBar() {
    var gen = document.querySelectorAll('.mab-bar:not(.tk-bar)');
    for (var i = 0; i < gen.length; i++) gen[i].parentNode.removeChild(gen[i]);
    if (gen.length) { try { window.dispatchEvent(new Event('resize')); } catch (e) { /* no-op */ } }
  }
  function mountPill() {
    if (document.querySelector('.tk-talk')) return;
    var pill = document.createElement('nav');
    pill.className = 'tk-talk';
    pill.setAttribute('aria-label', 'Talk to Mike');
    pill.innerHTML = '<span class="tk-lbl">Talk to Mike</span>' + links(false);
    var bar = document.querySelector('.nav-main-bar');
    if (bar && bar.children.length) bar.appendChild(pill);
    else { pill.className += ' tk-fixed'; document.body.appendChild(pill); }
  }
  function pillWhenHeaderReady() {
    var tries = 0;
    (function tryIt() {
      var bar = document.querySelector('.nav-main-bar');
      if ((bar && bar.children.length) || tries++ > 20) mountPill(); else window.setTimeout(tryIt, 250);
    })();
  }

  // ── 2. Join form ──────────────────────────────────────────────────────────
  var LICENCE = [['Licensed REALTOR in NL', 'Yes, in NL'], ['Licensed REALTOR elsewhere', 'Yes, elsewhere'], ['Not licensed yet', 'Not yet']];
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function mountForm(el) {
    var withHead = el.getAttribute('data-tk-heading') !== 'off';
    var seg = LICENCE.map(function (o) { return '<label><input type="radio" name="licensed" value="' + esc(o[0]) + '">' + esc(o[1]) + '</label>'; }).join('');
    el.innerHTML = '<form class="tk-form" novalidate>' +
      (withHead ? '<h2>Talk to Mike</h2><p class="tk-sub">Send your details and Mike Turner will get back to you the same day.</p>' : '') +
      '<div class="tk-err" role="alert"></div>' +
      '<label class="tk-field"><span class="tk-l">Name</span><input type="text" name="name" autocomplete="name" placeholder="First and last" required></label>' +
      '<label class="tk-field"><span class="tk-l">Email</span><input type="email" name="email" autocomplete="email" inputmode="email" placeholder="you@example.com" required></label>' +
      '<label class="tk-field"><span class="tk-l">Phone</span><input type="tel" name="phone" autocomplete="tel" inputmode="tel" placeholder="709-" required></label>' +
      '<fieldset class="tk-field"><legend>Are you licensed?</legend><div class="tk-seg">' + seg + '</div></fieldset>' +
      '<label class="tk-field"><span class="tk-l">Town</span><input type="text" name="town" autocomplete="address-level2" placeholder="Where you live or want to work" required></label>' +
      '<label class="tk-field"><span class="tk-l">Anything you’d like Mike to know? <span class="tk-opt">(optional)</span></span><textarea name="note" placeholder="Your timing, where you are with licensing, a question"></textarea></label>' +
      '<div class="tk-hp" aria-hidden="true"><label>Company<input type="text" name="_hp_company" tabindex="-1" autocomplete="off"></label></div>' +
      '<button type="submit" class="tk-submit">Send to Mike</button>' +
      '<p class="tk-consent">By sending, you agree we may contact you about this request. <a href="' + PRIVACY_URL + '">Privacy policy</a>.</p>' +
      '<label class="tk-chk"><input type="checkbox" name="updates"> Also email me updates about careers at Turner Realty</label>' +
      '</form>';
    var form = el.querySelector('form');
    var banner = form.querySelector('.tk-err');
    var btn = form.querySelector('.tk-submit');
    var t0 = Date.now();
    function val(n) { var f = form.elements[n]; return f && f.value != null ? String(f.value).trim() : ''; }
    function licence() { var c = form.querySelector('input[name=licensed]:checked'); return c ? c.value : ''; }
    function clearErrors() {
      banner.style.display = 'none';
      var bad = form.querySelectorAll('.tk-field.bad');
      for (var i = 0; i < bad.length; i++) { bad[i].classList.remove('bad'); var e = bad[i].querySelector('.tk-ferr'); if (e) e.parentNode.removeChild(e); }
    }
    function fieldError(name, msg) {
      var f = form.elements[name]; var host = f && f.closest ? f.closest('.tk-field') : form.querySelector('fieldset.tk-field');
      if (!host) return;
      host.classList.add('bad');
      host.insertAdjacentHTML('beforeend', '<span class="tk-ferr" id="tk-e-' + name + '">' + ICON.warn + msg + '</span>');
      if (f && f.setAttribute) { f.setAttribute('aria-invalid', 'true'); f.setAttribute('aria-describedby', 'tk-e-' + name); }
    }
    function banner_(msg) { banner.innerHTML = ICON.warn + '<div>' + msg + '</div>'; banner.style.display = 'flex'; btn.disabled = false; btn.textContent = 'Send to Mike'; }
    var radios = form.querySelectorAll('input[name=licensed]');
    for (var r = 0; r < radios.length; r++) radios[r].addEventListener('change', function () {
      var all = form.querySelectorAll('.tk-seg label'); for (var k = 0; k < all.length; k++) all[k].classList.toggle('on', all[k].querySelector('input').checked);
    });
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      clearErrors();
      var bad = 0;
      if (val('name').length < 2) { fieldError('name', 'Add your name.'); bad++; }
      if (!/^[^\s@<>]+@[^\s@<>]+\.[a-z]{2,}$/i.test(val('email'))) { fieldError('email', 'Enter an email we can reply to, like name@example.com.'); bad++; }
      if ((val('phone').match(/\d/g) || []).length < 7) { fieldError('phone', 'Add a phone number Mike can call or text.'); bad++; }
      if (!licence()) { fieldError('licensed', 'Choose one.'); bad++; }
      if (!val('town')) { fieldError('town', 'Add your town.'); bad++; }
      if (bad) { banner_('<b>It didn’t send.</b> Fix the fields marked above and try again, or call Mike at <a href="tel:+1' + tel + '">' + RECRUIT_PHONE + '</a>.'); return; }
      btn.disabled = true; btn.textContent = 'Sending…';
      if (val('_hp_company')) { window.setTimeout(function () { done(); }, 800); return; } // bot: pretend it worked
      var parts = val('name').split(/\s+/), first = parts.shift(), last = parts.join(' ');
      var updates = form.elements.updates.checked;
      var note = 'Agent recruiting inquiry — Licensed: ' + licence() + ' | Town: ' + val('town') +
        (val('note') ? ' | Note: ' + val('note') : '') +
        ' | Also email me updates about careers: ' + (updates ? 'yes' : 'no') + ' | Form: careers-kit inline join form (' + location.pathname + ')';
      var payload = {
        source: 'web',
        first_name: first, last_name: last, email: val('email'), phone_number: val('phone'),
        note: note,
        tag: ['Recruitment', 'Agent Recruiting'],
        lead_source: LEAD_SOURCE,
        assignees: [{ email: MIKE_EMAIL }],
        referer_url: location.href
      };
      var wait = Math.max(0, 3200 - (Date.now() - t0)); // lead-receive drops submits under 3 s
      window.setTimeout(function () {
        fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
          .then(function (r2) { if (r2.ok) done(); else throw new Error('http ' + r2.status); })
          .catch(function () { banner_('<b>It didn’t send.</b> Try again, or call Mike at <a href="tel:+1' + tel + '">' + RECRUIT_PHONE + '</a>.'); });
      }, wait);
    });
    function done() {
      try { if (typeof window.trackLead === 'function') window.trackLead(LEAD_SOURCE, { region: siteId(), lead_channel: 'recruiting', form_tags: 'Recruitment,Agent Recruiting' }); } catch (x) { /* no-op */ }
      try { if (typeof window.gtag === 'function') window.gtag('event', 'recruiting_inquiry', { form_name: 'careers_kit_join', site: siteId() }); } catch (x) { /* no-op */ }
      form.innerHTML = '<h2>Thank you</h2><p class="tk-ok">Mike Turner will get back to you the same day. You can also <a href="' + BOOKING_URL + '" target="_blank" rel="noopener">book a chat now</a>.</p>';
    }
    watchForm(form);
  }

  // Bar, chat launcher and "Get the app" card step aside while the form is on screen (phone/tablet only), so nothing sits over Send.
  // Sets html.tk-form-clear (this bar) and html.tnr-form-clear (the fleet's hook: js/chat-widget.js and css/app-shell.css hide their
  // floating pieces on it, whatever the FORM_CLEAR switch says).
  function watchForm(form) {
    var root = document.documentElement, inView = false, last = false;
    var mq = window.matchMedia ? window.matchMedia('(max-width:860px)') : null;
    function apply() {
      var on = inView && (!mq || mq.matches);
      if (on === last) return;
      last = on;
      root.classList.toggle('tk-form-clear', on);
      root.classList.toggle('tnr-form-clear', on);
      // js/chat-widget.js re-measures the bar's height on resize: tell it the bar just appeared or went away.
      window.setTimeout(function () { try { window.dispatchEvent(new Event('resize')); } catch (e) { /* no-op */ } }, 60);
    }
    if (!('IntersectionObserver' in window)) return;
    new IntersectionObserver(function (ents) { inView = ents[0].isIntersecting; apply(); }, { threshold: 0.01 }).observe(form);
    window.addEventListener('resize', apply);
  }

  function init() {
    mountBar();
    pillWhenHeaderReady();
    var els = document.querySelectorAll('[data-tk-join]');
    for (var i = 0; i < els.length; i++) mountForm(els[i]);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
