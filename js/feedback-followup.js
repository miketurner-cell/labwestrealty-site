/* feedback-followup.js -- the "Talk to a local agent" card after consumer feedback that reads like a lead
 * (lead session, Mike's D-1009-72 (3) and D-1015-21, 2026-10-15).
 *
 * Tier-1, byte-identical on realestategander.com, avalonrealestate.ca, goosebayrealestate.ca, labwestrealty.com and
 * royallepageturner.com (fleet/canonical/js/feedback-followup.js, always-on #27). Loaded by js/site-feedback.js only when
 * Gander's site-feedback function answers looks_like_lead:true, so it never loads while SITE_FEEDBACK is off.
 *
 * Feedback is never a lead. This card only offers the site's existing contact page (which asks its own consent question)
 * and the site's phone; nothing here sends anything, stores anything or calls any function. A lead exists only if the
 * visitor uses that contact page.
 *
 * site-feedback.js un-hides [data-feedback-followup] with data-looks-like-lead="1" and fires "turner:feedback-sent"
 * before this file has loaded, so the card renders into any such slot on load AND on later events.
 */
(function () {
  'use strict';
  if (window.__turnerFeedbackFollowup) return;
  window.__turnerFeedbackFollowup = true;

  // Each site's own contact page and phone (CLAUDE.md "Canonical per-site inquiry email + phone"; contact pages checked
  // live 2026-10-15). An unknown host (a deploy preview, localhost) gets no card rather than another site's details.
  var SITES = {
    'realestategander.com': { contact: '/pages/contact.html', phone: '709-256-7999' },
    'goosebayrealestate.ca': { contact: '/pages/contact.html', phone: '709-896-5001' },
    'avalonrealestate.ca': { contact: '/pages/contact.html', phone: '709-725-6520' },
    'labwestrealty.com': { contact: '/contact.html', phone: '709-256-7999' },
    'royallepageturner.com': { contact: '/contact.html', phone: '709-256-7999' }
  };
  var host = (location.hostname || '').replace(/^www\./, '');
  var site = SITES[host] || (window.TURNER_FEEDBACK_FOLLOWUP_SITE && SITES[window.TURNER_FEEDBACK_FOLLOWUP_SITE]);
  if (!site) return;

  function css() {
    if (document.getElementById('tff-css')) return;
    var st = document.createElement('style');
    st.id = 'tff-css';
    st.textContent =
      '.tff{border-top:1px solid #e6e6e6;margin-top:6px;padding-top:14px;}' +
      '.tff h3{font:800 16px/1.3 Raleway,Arial,sans-serif;margin:0 0 4px;color:#0a0a0a;}' +
      '.tff p{font-size:14px;line-height:1.5;margin:0 0 12px;color:#333;font-weight:400;}' +
      '.tff a{display:flex;align-items:center;justify-content:center;width:100%;min-height:44px;box-sizing:border-box;border-radius:6px;' +
        'font:700 15px/1 Raleway,Arial,sans-serif;letter-spacing:.03em;text-decoration:none;}' +
      '.tff .tff-msg{background:#EA002A;color:#fff;margin-bottom:8px;}' +
      '.tff .tff-call{background:#fff;color:#0a0a0a;border:1px solid #c9c9c9;}' +
      '.tff a:focus-visible{outline:2px solid #EA002A;outline-offset:2px;}';
    document.head.appendChild(st);
  }

  function render(slot) {
    if (!slot || slot.getAttribute('data-looks-like-lead') !== '1' || slot.querySelector('.tff')) return;
    css();
    var digits = site.phone.replace(/\D/g, '');
    var box = document.createElement('div');
    box.className = 'tff';
    box.innerHTML =
      '<h3>Looking to buy or sell?</h3>' +
      '<p>Talk to a local agent.</p>' +
      '<a class="tff-msg" href="' + site.contact + '">Send us a message</a>' +
      '<a class="tff-call" href="tel:+1' + digits + '">Call ' + site.phone + '</a>';
    slot.appendChild(box);
    slot.hidden = false;
  }

  function renderAll() {
    var slots = document.querySelectorAll('[data-feedback-followup][data-looks-like-lead="1"]');
    for (var i = 0; i < slots.length; i++) render(slots[i]);
  }

  document.addEventListener('turner:feedback-sent', function (e) {
    var d = e && e.detail;
    if (d && d.looks_like_lead === true && d.slot) render(d.slot); else renderAll();
  });
  renderAll();
})();
