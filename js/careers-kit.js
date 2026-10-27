/* careers-kit.js -- the recruiting pages' "Talk to Mike" bar and short join form (sites session, B-1027-07; Mike D-1026-31,
 * D-1027-03, D-1027-17).
 *
 * Byte-identical on realestategander.com, avalonrealestate.ca, goosebayrealestate.ca, labwestrealty.com and royallepageturner.com
 * (always-on #27); the copy in realestategander-site is the canonical one. Loaded ONLY by the careers / join / become-a-realtor /
 * first-year / why-join pages (tools/tests/careers-pages-test.py checks the list).
 *
 * 1. A sticky "Talk to Mike" bar under 1024px: Book a chat (Google booking page) - Call (- Text, only when TEXT_ENABLED). It is
 *    class "mab-bar tk-bar" so js/chat-widget.js docks its bubble above it, replaces the generic Call/Text/Home Value bar on these
 *    pages, and steps aside while the join form is on screen or a keyboard is up, so it never covers the Submit button.
 * 2. A short join form in any <div data-tk-join>: name, email, phone, licence status, town. It posts to lead-receive exactly as the
 *    old Join Our Team form did (lead_source "Source: Join Our Team - Agent Recruiting" = the registry's recruiting lane, assignee
 *    Mike). It does NOT use the gated recruit-inquiry lane (RECRUIT_FORM) and does not switch any gate on.
 */
(function () {
  'use strict';
  if (window.__turnerCareersKit) return;
  window.__turnerCareersKit = true;

  // ONE place for the recruit contact details on this site's careers pages.
  var BOOKING_URL = 'https://calendar.app.google/3S7FJsvtkxxZf9Ja6';
  // NEEDS MIKE (D-1027-17): which number should recruits see - the office 709-256-7999 or Mike's cell 709-424-6517?
  // Set to the office line for now. Change this one constant (and TEXT_ENABLED if the number can take texts) and nothing else.
  var RECRUIT_PHONE = '709-256-7999';
  // 709-256-7999 is the Rogers office line answered by the AI receptionist; text messages to it are not handled, so no Text button.
  var TEXT_ENABLED = false;
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

  var css = '' +
    '.tk-form{max-width:640px;margin:0 auto;background:#fff;color:#1a1a1a;border-radius:12px;padding:24px 20px;box-shadow:0 6px 24px rgba(0,0,0,.25);font-family:Roboto,system-ui,-apple-system,"Segoe UI",sans-serif;text-align:left}' +
    '.tk-form h2{margin:0 0 6px;font-size:1.4rem;line-height:1.25;color:#1a1a1a}' +
    '.tk-form p.tk-sub{margin:0 0 16px;font-size:1rem;line-height:1.5;color:#444}' +
    '.tk-row{display:grid;grid-template-columns:1fr 1fr;gap:12px}' +
    '@media (max-width:520px){.tk-row{grid-template-columns:1fr}}' +
    '.tk-field{display:block;margin:0 0 12px}' +
    '.tk-field>span{display:block;margin:0 0 4px;font-size:.95rem;font-weight:600;color:#222}' +
    '.tk-form input[type=text],.tk-form input[type=email],.tk-form input[type=tel],.tk-form select{width:100%;box-sizing:border-box;min-height:48px;padding:10px 12px;font-size:16px;line-height:1.3;color:#1a1a1a;background:#fff;border:1px solid #8a8a8a;border-radius:8px;font-family:inherit}' +
    '.tk-form input:focus,.tk-form select:focus{outline:3px solid #EA002A;outline-offset:1px}' +
    '.tk-opt{display:flex;gap:12px;align-items:flex-start;min-height:48px;padding:6px 0;font-size:.95rem;line-height:1.4;color:#333;cursor:pointer}' +
    '.tk-opt input{width:24px;height:24px;flex:none;margin:2px 0 0}' +
    '.tk-submit{display:block;width:100%;min-height:52px;margin:8px 0 0;padding:12px 16px;background:#EA002A;color:#fff;border:0;border-radius:8px;font-size:1rem;font-weight:700;letter-spacing:.3px;cursor:pointer;font-family:inherit}' +
    '.tk-submit[disabled]{opacity:.6;cursor:default}' +
    '.tk-consent{margin:12px 0 0;font-size:.85rem;line-height:1.45;color:#555}' +
    '.tk-consent a{color:#b00020;text-decoration:underline}' +
    '.tk-err{display:none;margin:12px 0 0;padding:10px 12px;background:#fdecee;color:#8a0016;border-radius:8px;font-size:.95rem;line-height:1.4}' +
    '.tk-ok{padding:8px 0;font-size:1.05rem;line-height:1.5}' +
    '.tk-hp{position:absolute!important;left:-9999px!important;width:1px;height:1px;overflow:hidden}' +
    '.tk-book-btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:12px 24px;background:#EA002A;color:#fff!important;border-radius:8px;font-weight:700;font-size:1rem;text-decoration:none;text-align:center;box-sizing:border-box}' +
    '.tk-bar{display:none}' +
    '@media (max-width:1023px){' +
      '.tk-bar{display:flex;position:fixed;left:0;right:0;bottom:0;z-index:95;height:56px;background:#EA002A;border-top:1px solid rgba(0,0,0,.2);box-shadow:0 -4px 16px rgba(0,0,0,.35);padding-bottom:env(safe-area-inset-bottom,0);box-sizing:content-box}' +
      '.tk-bar .tk-lbl{display:none}' +
      '.tk-bar a{flex:1;display:flex;align-items:center;justify-content:center;min-height:56px;color:#fff;text-decoration:none;font-weight:800;font-size:.8rem;letter-spacing:.4px;text-transform:uppercase;border-right:1px solid rgba(255,255,255,.22);text-align:center;font-family:Raleway,Roboto,sans-serif}' +
      '.tk-bar a:last-child{border-right:0}' +
      '.tk-bar a.tk-primary{background:#fff;color:#EA002A;flex:1.4}' +
      'body.tk-careers{padding-bottom:calc(56px + env(safe-area-inset-bottom,0))}' +
      'html.tk-form-clear .tk-bar{display:none!important}' +
    '}' +
    '@media (min-width:600px) and (max-width:1023px){.tk-bar .tk-lbl{display:flex;flex:1.2;background:rgba(0,0,0,.18);cursor:default}}' +
    'html.tnr-kb-open .tk-bar{display:none!important}' +
    'body.tk-careers .mab-bar:not(.tk-bar){display:none!important}';
  var st = document.createElement('style');
  st.textContent = css;
  document.head.appendChild(st);

  // ── 1. Talk to Mike bar ───────────────────────────────────────────────────
  function mountBar() {
    if (document.querySelector('.tk-bar')) return;
    document.body.classList.add('tk-careers');
    var bar = document.createElement('div');
    bar.className = 'mab-bar tk-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Talk to Mike');
    bar.innerHTML = '<span class="tk-lbl" style="align-items:center;justify-content:center;color:#fff;font-weight:800;font-size:.8rem;text-transform:uppercase">Talk to Mike</span>' +
      '<a class="tk-primary" href="' + BOOKING_URL + '" target="_blank" rel="noopener" data-tk="book">Book a chat</a>' +
      '<a href="tel:+1' + tel + '" aria-label="Call ' + RECRUIT_PHONE + '" data-tk="call">Call</a>' +
      (TEXT_ENABLED ? '<a href="sms:+1' + tel + '" aria-label="Text ' + RECRUIT_PHONE + '" data-tk="text">Text</a>' : '');
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

  // ── 2. Join form ──────────────────────────────────────────────────────────
  var LICENCE = [
    ['', 'Choose one…'],
    ['Licensed REALTOR', 'I\u2019m a licensed REALTOR\u00ae'],
    ['Licence in progress', 'I\u2019m working on my licence'],
    ['Considering the career', 'I\u2019m thinking about a real estate career']
  ];
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function mountForm(el) {
    var opts = LICENCE.map(function (o) { return '<option value="' + esc(o[0]) + '">' + esc(o[1]) + '</option>'; }).join('');
    el.innerHTML = '<form class="tk-form" novalidate>' +
      '<h2>Talk to Mike</h2>' +
      '<p class="tk-sub">Send your details and Mike Turner will get back to you the same day.</p>' +
      '<div class="tk-row">' +
        '<label class="tk-field"><span>First name</span><input type="text" name="fname" autocomplete="given-name" required></label>' +
        '<label class="tk-field"><span>Last name</span><input type="text" name="lname" autocomplete="family-name" required></label>' +
      '</div>' +
      '<label class="tk-field"><span>Email</span><input type="email" name="email" autocomplete="email" inputmode="email" required></label>' +
      '<label class="tk-field"><span>Phone</span><input type="tel" name="phone" autocomplete="tel" inputmode="tel" required></label>' +
      '<label class="tk-field"><span>Licence status</span><select name="license" required>' + opts + '</select></label>' +
      '<label class="tk-field"><span>Town</span><input type="text" name="town" autocomplete="address-level2" required></label>' +
      '<div class="tk-hp" aria-hidden="true"><label>Company<input type="text" name="_hp_company" tabindex="-1" autocomplete="off"></label></div>' +
      '<button type="submit" class="tk-submit">Send to Mike</button>' +
      '<p class="tk-consent">By sending, you agree we may contact you about this request. <a href="' + PRIVACY_URL + '">Privacy policy</a>.</p>' +
      '<label class="tk-opt"><input type="checkbox" name="updates"><span>Also email me updates</span></label>' +
      '<p class="tk-err" role="alert"></p>' +
      '</form>';
    var form = el.querySelector('form');
    var err = form.querySelector('.tk-err');
    var btn = form.querySelector('.tk-submit');
    var t0 = Date.now();
    function val(n) { var f = form.elements[n]; return f ? String(f.value || '').trim() : ''; }
    function fail(msg) { err.textContent = msg; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'Send to Mike'; }
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      err.style.display = 'none';
      var problem = !val('fname') ? 'Please add your first name.' :
        !val('lname') ? 'Please add your last name.' :
        !/^[^\s@<>]+@[^\s@<>]+\.[a-z]{2,}$/i.test(val('email')) ? 'Please check your email address.' :
        (val('phone').match(/\d/g) || []).length < 7 ? 'Please add a phone number.' :
        !val('license') ? 'Please choose your licence status.' :
        !val('town') ? 'Please add your town.' : '';
      if (problem) { fail(problem); return; }
      btn.disabled = true; btn.textContent = 'Sending…';
      if (val('_hp_company')) { // bot: pretend it worked
        window.setTimeout(function () { done(); }, 800); return;
      }
      var updates = form.elements.updates.checked;
      var note = 'Agent recruiting inquiry — Licence status: ' + val('license') + ' | Town: ' + val('town') +
        ' | Also email me updates: ' + (updates ? 'yes' : 'no') + ' | Form: careers-kit inline join form (' + location.pathname + ')';
      var payload = {
        source: 'web',
        first_name: val('fname'), last_name: val('lname'), email: val('email'), phone_number: val('phone'),
        note: note,
        tag: ['Recruitment', 'Agent Recruiting'],
        lead_source: LEAD_SOURCE,
        assignees: [{ email: MIKE_EMAIL }],
        referer_url: location.href
      };
      var wait = Math.max(0, 3200 - (Date.now() - t0)); // lead-receive drops submits under 3 s
      window.setTimeout(function () {
        fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
          .then(function (r) { if (r.ok) done(); else throw new Error('http ' + r.status); })
          .catch(function () { fail('Something went wrong. Please call ' + RECRUIT_PHONE + '.'); });
      }, wait);
    });
    function done() {
      try { if (typeof window.trackLead === 'function') window.trackLead(LEAD_SOURCE, { region: siteId(), lead_channel: 'recruiting', form_tags: 'Recruitment,Agent Recruiting' }); } catch (x) { /* no-op */ }
      try { if (typeof window.gtag === 'function') window.gtag('event', 'recruiting_inquiry', { form_name: 'careers_kit_join', site: siteId() }); } catch (x) { /* no-op */ }
      form.innerHTML = '<h2>Thank you</h2><p class="tk-ok">Mike Turner will get back to you the same day. You can also <a href="' + BOOKING_URL + '" target="_blank" rel="noopener">book a chat now</a>.</p>';
    }
    watchForm(form);
  }

  // Bar, chat launcher and "Get the app" card step aside while the form is on screen (phone/tablet only), so nothing sits over Submit.
  // Sets html.tk-form-clear (this bar) and html.tnr-form-clear (the fleet's hook: js/chat-widget.js and css/app-shell.css hide their
  // floating pieces on it, whatever the FORM_CLEAR switch says).
  function watchForm(form) {
    var root = document.documentElement, inView = false, last = false;
    var mq = window.matchMedia ? window.matchMedia('(max-width:1023px)') : null;
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
    var els = document.querySelectorAll('[data-tk-join]');
    for (var i = 0; i < els.length; i++) mountForm(els[i]);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
