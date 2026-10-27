/**
 * Turner Realty — BoldTrail Lead Capture Forms
 * ==========================================
 * Self-contained, conversion-focused lead capture forms
 * POST to: https://realestategander.com/.netlify/functions/lead-receive
 *   (vendor-agnostic — routes to Supabase + Postmark + kvCORE/rlpSPHERE by
 *    territory. all leads POST to lead-receive.ts -> kvCORE/BoldTrail.)
 * Lead Channel: 9a2a880b-daa0-4463-8a9d-78fc5b5c67ae (Goose Bay)
 *
 * Each form is injected into a target element by ID.
 * Usage: BoldTrailForms.homeValuation('#my-container')
 */

var BoldTrailForms = (function() {
    'use strict';

    // AddressComplete self-load (2026-09-07) -- this file is loaded on
    // essentially every page fleet-wide, most of which have no
    // address-complete.js script tag. Captured HERE (module-init, the only
    // point document.currentScript is guaranteed valid) and reused by any
    // form builder in this file that wants AddressComplete; loadAddressComplete's
    // callback fires only once the dependency is actually ready, avoiding the
    // race a page-order assumption would risk. Fails open at every step: no
    // SELF_SRC, a failed load, an empty fleet key, or a service error all
    // leave the affected input exactly as it behaves today.
    var AC_SELF_SRC = (document.currentScript && document.currentScript.src) || '';
    var AC_LOADERS = null;
    function loadAddressComplete(cb) {
        if (window.AddressComplete) { cb(); return; }
        if (!AC_SELF_SRC) return;
        if (AC_LOADERS) { AC_LOADERS.push(cb); return; }
        AC_LOADERS = [cb];
        var s = document.createElement('script');
        s.src = AC_SELF_SRC.replace(/boldtrail-forms\.js(\?.*)?$/, 'address-complete.js') + '?v=20260907-google-ac';
        s.onload = function () {
            (AC_LOADERS || []).forEach(function (fn) { fn(); });
            AC_LOADERS = null;
        };
        s.onerror = function () { AC_LOADERS = null; };
        document.head.appendChild(s);
    }

    var LEAD_CHANNEL = '9a2a880b-daa0-4463-8a9d-78fc5b5c67ae';
    // BoldTrail → kvCORE/rlpSPHERE cutover 2026-06-16 (Goosebay canary). Posts to our
    // vendor-agnostic function, which routes the lead into rlpSPHERE + Supabase + email.
    var API_URL = 'https://realestategander.com/.netlify/functions/lead-receive';
    var SITE_REGION = 'Goose Bay';

    // ─── Email typo guard (2026-07-20) ───────────────────────
    // Loads js/email-typo-guard.js, which installs ONE document-level
    // capture-phase submit listener and softly asks "Did you mean …?" on a
    // suspected address typo. Loaded from here rather than via a <script> tag
    // on each page because every form-bearing page already loads this file —
    // one hook covers the whole site and survives listing-page regeneration.
    //
    // The path is derived from THIS script's own src so it resolves correctly
    // at any depth (/, /pages/, /listings/<city>/).
    (function loadEmailTypoGuard() {
        try {
            if (window.EmailTypoGuard) return;
            var self = document.currentScript;
            if (!self || !self.src) return;                    // can't derive path — skip silently
            var src = self.src.split('?')[0].replace(/boldtrail-forms\.js$/, 'email-typo-guard.js');
            if (src === self.src.split('?')[0]) return;        // unexpected filename — skip
            if (document.querySelector('script[src^="' + src + '"]')) return;
            var s = document.createElement('script');
            s.src = src + '?v=20260719-typo-guard';
            s.async = true;
            document.head.appendChild(s);
        } catch (e) {
            // Convention #74 — a guard that fails to load must never break forms.
        }
    })();

    // ─── The one reply promise (Mike, D-1008-30, 2026-10-08) ─────────────
    // Every contact and showing form carries the one reply promise (D-1027-01).
    // The wording lives in ONE fleet-canonical file, js/reply-promise.js, which sets
    // window.TURNER_REPLY_WINDOW / TURNER_REPLY_PROMISE. It is loaded from here (same
    // pattern as the typo guard: this file is on every form-bearing page) and read at
    // render time. The fallbacks below are IDENTICAL to the canonical text, so a form
    // that renders before the file arrives, or if it fails to load, still says the
    // same thing; tools/tests/reply-promise-test.py fails CI if they ever differ.
    // careers-only (the confidential broker inquiry form is owned by the careers builder, D-1026-31): remove with that form's rewrite
    var REPLY_WINDOW_FALLBACK = 'within one business hour';
    var REPLY_PROMISE_FALLBACK = 'Our receptionist answers 24/7, and an agent calls you back the same day.';
    function replyWindow() { return window.TURNER_REPLY_WINDOW || REPLY_WINDOW_FALLBACK; }
    function replyPromise() { return window.TURNER_REPLY_PROMISE || REPLY_PROMISE_FALLBACK; }
    (function loadReplyPromise() {
        try {
            if (window.TURNER_REPLY_PROMISE) return;
            var self = document.currentScript;
            if (!self || !self.src) return;
            var src = self.src.split('?')[0].replace(/boldtrail-forms\.js$/, 'reply-promise.js');
            if (src === self.src.split('?')[0]) return;
            if (document.querySelector('script[src^="' + src + '"]')) return;
            var s = document.createElement('script');
            s.src = src + '?v=e52db2b6';
            s.async = true;
            document.head.appendChild(s);
        } catch (e) {
            // a promise that fails to load falls back to the identical text above
        }
    })();


    // CONSENT_FORMS_LOADER_BEGIN
    // (D-1027-02 / D-1027-03): js/consent-forms.js adds the consent line, the optional "Also email me updates"
    // box, 16px inputs and autocomplete to every lead form on the page, and records the consent type for lead-receive. Loaded from
    // here because this file is on every page that carries a lead form. Fails open: without it the forms behave as before.
    (function loadConsentForms() {
        try {
            if (window.TurnerConsent || document.getElementById('tc-consent-js') || !AC_SELF_SRC) return;
            var s = document.createElement('script');
            s.id = 'tc-consent-js';
            s.src = AC_SELF_SRC.split('?')[0].replace(/boldtrail-forms\.js$/, 'consent-forms.js') + '?v=8762e7d1';
            document.head.appendChild(s);
        } catch (e) { /* the forms stay as they were */ }
    })();
    // CONSENT_FORMS_LOADER_END

    // FORMS_V2_LOADER_BEGIN
    // ─── The form pattern (redesign, Mike's D-1008-86) ───────────────────────
    // js/forms-v2.js + css/forms-v2.css are loaded ONLY when the site's nav-config says formsV2: 'v2' or the URL carries
    // ?forms=v2 (?forms=v1 forces the old forms). With the switch off this block does nothing at all: no request, no node,
    // no listener beyond the one that reads the switch. Checked at DOMContentLoaded because nav-config.js (which holds the
    // switch) is a deferred script on most pages.
    (function loadFormsV2() {
        try {
            var q = window.location.search || '';
            var check = function () {
                try {
                    if (window.TurnerFormsV2Loaded || !AC_SELF_SRC) return;
                    var on = /[?&]forms=v2(&|$)/.test(q) || !!(window.SITE && window.SITE.formsV2 === 'v2');
                    if (/[?&]forms=v1(&|$)/.test(q)) on = false;
                    if (!on) return;
                    window.TurnerFormsV2Loaded = true;
                    var base = AC_SELF_SRC.split('?')[0].replace(/boldtrail-forms\.js$/, '');
                    var l = document.createElement('link');
                    l.rel = 'stylesheet';
                    l.href = base.replace(/js\/$/, 'css/') + 'forms-v2.css?v=b9a73ee8';
                    document.head.appendChild(l);
                    var s = document.createElement('script');
                    s.src = base + 'forms-v2.js?v=6632f056';
                    document.head.appendChild(s);
                } catch (e) { /* the old forms stay */ }
            };
            if (document.readyState === 'complete') check();
            else { document.addEventListener('DOMContentLoaded', check); window.addEventListener('load', check); }   // check() is idempotent
        } catch (e) { /* the old forms stay */ }
    })();
    // FORMS_V2_LOADER_END

    // ─── Shared Styles ───────────────────────────────────────
    var sharedCSS = '\
        .rf-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 10000; display: flex; align-items: center; justify-content: center; padding: 20px; opacity: 0; transition: opacity 0.25s; }\
        .rf-overlay.rf-open { opacity: 1; }\
        .rf-overlay .rf-modal { position: relative; max-height: 90vh; overflow-y: auto; width: 100%; max-width: 540px; }\
        .rf-overlay .rf-close { position: absolute; top: 12px; right: 16px; background: none; border: none; color: rgba(255,255,255,0.4); font-size: 1.5rem; cursor: pointer; z-index: 1; line-height: 1; padding: 4px 8px; }\
        .rf-overlay .rf-close:hover { color: #fff; }\
        .rf-form-wrap { max-width: 520px; margin: 0 auto; background: #1a1a1a; padding: 40px 32px; border-radius: 8px; border: 1px solid #2a2a2a; font-family: "Roboto", sans-serif; }\
        .rf-form-wrap h3 { font-family: "Raleway", sans-serif; font-weight: 900; font-size: 1.5rem; color: #fff; margin: 0 0 10px 0; line-height: 1.3; }\
        .rf-form-wrap .rf-subhead { font-size: 0.9rem; color: rgba(255,255,255,0.6); line-height: 1.6; margin: 0 0 28px 0; }\
        .rf-form-wrap label { display: block; font-size: 0.8rem; font-weight: 400; color: rgba(255,255,255,0.5); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }\
        .rf-form-wrap input, .rf-form-wrap select, .rf-form-wrap textarea { width: 100%; padding: 13px 14px; background: #111; border: 1px solid #2a2a2a; border-radius: 4px; color: #fff; font-family: "Roboto", sans-serif; font-size: 16px; box-sizing: border-box; transition: border-color 0.2s; -webkit-appearance: none; appearance: none; }\
        .rf-form-wrap input:focus, .rf-form-wrap select:focus, .rf-form-wrap textarea:focus { outline: none; border-color: #EA002A; box-shadow: 0 0 0 2px rgba(234,0,42,0.15); }\
        .rf-form-wrap input::placeholder, .rf-form-wrap textarea::placeholder { color: rgba(255,255,255,0.25); }\
        .rf-form-wrap select { background-image: url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'8\' viewBox=\'0 0 12 8\'%3E%3Cpath d=\'M1 1l5 5 5-5\' stroke=\'%23888\' stroke-width=\'1.5\' fill=\'none\'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 14px center; padding-right: 36px; cursor: pointer; }\
        .rf-form-wrap select option { background: #111; color: #fff; }\
        .rf-form-wrap textarea { min-height: 90px; resize: vertical; }\
        .rf-form-wrap .rf-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }\
        .rf-form-wrap .rf-field { margin-bottom: 16px; min-width: 0; }\
        .rf-form-wrap .rf-optional { font-size: 0.7rem; color: rgba(255,255,255,0.3); font-weight: 300; }\
        .rf-form-wrap .rf-submit { width: 100%; padding: 16px; background: #EA002A; color: #fff; border: none; border-radius: 4px; font-family: "Raleway", sans-serif; font-weight: 900; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 1px; cursor: pointer; transition: background 0.2s, transform 0.1s; margin-top: 8px; }\
        .rf-form-wrap .rf-submit:hover { background: #c8001f; transform: translateY(-1px); }\
        .rf-form-wrap .rf-submit:active { transform: translateY(0); }\
        .rf-form-wrap .rf-submit:disabled { background: #555; cursor: not-allowed; transform: none; }\
        .rf-form-wrap .rf-error { color: #EA002A; font-size: 0.8rem; margin-top: 12px; display: none; text-align: center; }\
        .rf-form-wrap .rf-success { text-align: center; padding: 40px 20px; }\
        .rf-form-wrap .rf-success h4 { font-family: "Raleway", sans-serif; font-weight: 900; font-size: 1.3rem; color: #fff; margin: 0 0 12px 0; }\
        .rf-form-wrap .rf-success p { font-size: 0.95rem; color: rgba(255,255,255,0.7); line-height: 1.6; margin: 0; }\
        .rf-form-wrap .rf-success .rf-check { width: 48px; height: 48px; background: #EA002A; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin: 0 auto 20px; }\
        .rf-form-wrap .rf-success .rf-check svg { width: 24px; height: 24px; }\
        .rf-form-wrap label.tc-optin, .rf-form-wrap label.tc-alerts { display: flex; gap: 12px; align-items: flex-start; min-height: 44px; padding: 10px 0; margin: 0 0 6px; text-transform: none; letter-spacing: normal; font-size: 14px; line-height: 1.45; color: rgba(255,255,255,0.75); cursor: pointer; }\
        .rf-form-wrap .tc-optin input[type=checkbox], .rf-form-wrap .tc-alerts input[type=checkbox] { width: 22px; height: 22px; min-width: 22px; flex: none; padding: 0; margin: 1px 0 0; accent-color: #EA002A; }\
        .rf-form-wrap .tc-optin .tc-sub { display: block; margin-top: 2px; font-size: 12px; opacity: 0.8; }\
        .rf-form-wrap .tc-line { margin: 10px 0 0; font-size: 13px; line-height: 1.45; color: rgba(255,255,255,0.65); text-align: left; }\
        .rf-form-wrap .tc-line a { color: #fff; text-decoration: underline; }\
        @media (max-width: 600px) { .rf-form-wrap .rf-row { grid-template-columns: 1fr; } .rf-form-wrap { padding: 28px 20px; } }\
    ';

    var styleInjected = false;
    // Team names ("Karen & Roberta") name both partners in the ask-form prompt (D-1012-20).
    function askNames(agentName) {
        var m = /^(\S+)\s+(?:&amp;|&|and)\s+(\S+)/.exec(agentName || '');
        return m ? m[1] + ' and ' + m[2] : (agentName || '').split(' ')[0];
    }

    function injectStyles() {
        if (styleInjected) return;
        var s = document.createElement('style');
        s.textContent = sharedCSS;
        document.head.appendChild(s);
        styleInjected = true;
    }

    // ─── Bot Protection ────────────────────────────────────────
    var botCSS = '.rf-form-wrap .rf-hp-field { position:absolute; left:-9999px; top:-9999px; opacity:0; height:0; width:0; overflow:hidden; pointer-events:none; tabindex: -1; }';
    function injectBotStyles() {
        var s = document.createElement('style');
        s.textContent = botCSS;
        document.head.appendChild(s);
    }
    injectBotStyles();

    var formLoadTimes = {};
    function recordFormLoad(formId) { formLoadTimes[formId] = Date.now(); }
    function secondsSinceLoad(formId) { return formLoadTimes[formId] ? (Date.now() - formLoadTimes[formId]) / 1000 : 999; }

    function botCheck(formId, data) {
        if (data._hp_company && data._hp_company.trim() !== '') return 'bot-honeypot';
        if (secondsSinceLoad(formId) < 3) return 'bot-too-fast';
        var fn = (data.first_name || '').trim().toLowerCase();
        var ln = (data.last_name || '').trim().toLowerCase();
        var junkNames = ['xyz', 'xxx', 'aaa', 'bbb', 'test', 'asdf', 'qwerty', 'john doe', 'jane doe', 'n/a', 'na', 'none', 'null', 'undefined', 'admin', 'root'];
        if (junkNames.indexOf(fn) !== -1 || (ln && junkNames.indexOf(ln) !== -1)) return 'bot-junk-name';
        if (fn.length < 2) return 'bot-short-name';
        if (ln && ln.length > 0 && ln.length < 2) return 'bot-short-name';
        var em = (data.email || '').trim().toLowerCase();
        if (/^(test|spam|fake|bot|noreply|no-reply)@/i.test(em)) return 'bot-fake-email';
        return null;
    }

    var honeypotHTML = '<div class="rf-hp-field" aria-hidden="true"><label for="rf_hp_check">Verify</label><input type="text" name="rf_hp_check" id="rf_hp_check" autocomplete="off" tabindex="-1"></div>';

    // ─── Assignee builder (LCA-F per-territory routing, Convention #15
    //     byte-symmetric port from realestategander-site c2dcf874d 2026-05-20) ─────
    // UUID-first preference: reads data-agent-uuid (from tools/boldtrail-agent-map.json)
    // first; falls back to data-agent-email; then data-team-email. Returns []
    // when no data-* attributes (Convention #74 fail-safe — BoldTrail falls back
    // to default channel routing).
    function buildAssignees(el) {
        if (!el || !el.getAttribute) return [];
        var uuid = (el.getAttribute('data-agent-uuid') || '').trim();
        var email = (el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '').trim();
        if (uuid) return [{ user_id: uuid }];
        if (email) return [{ email: email }];
        return [];
    }

    // ─── POST to BoldTrail ──────────────────────────────────────
    function postLead(data, callback) {
        var payload = {
            source: 'web',
            first_name: data.first_name || '',
            last_name: data.last_name || '',
            email: data.email || '',
            phone_number: data.phone || '',
            note: data.note || '',
            tag: data.tag || [],
            lead_source: data.lead_source || 'Website',
            referer_url: window.location.href
        };
        if (data.assignees) payload.assignees = data.assignees;
        // Structured enrichment (2026-06-18): forward listing/buyer-criteria so the
        // agent's kvCORE view shows them in native fields, not buried in the note blob.
        // Part 8 §8.3(e), the infinite loop's E8 referral edge: passive "Who referred
        // you?" text, forwarded verbatim to lead-receive.ts (resolveReferrer there
        // does the actual matching -- this file never guesses at identity). Ported
        // from Gander (Ship 4, 2026-09-17).
        ['property_address','mls_number','listing_url','property_type','budget','interest_area','timeline','message','preferred_showing_windows','referred_by']
            .forEach(function(k){ if (data[k]) payload[k] = data[k]; });
        // P1d (2026-08-19 on Gander; ported here Ship 4, 2026-09-17): stamp the
        // signed-in visitor's auth user id on every lead form this file sends -- one
        // choke point covers all of them. lead-receive.ts already accepts + UUID-
        // validates auth_user_id and backfills contacts.auth_user_id on it. Guarded --
        // never blocks a signed-out submit (Conv #74).
        try {
            if (window.TurnerAuth && typeof window.TurnerAuth.getUser === 'function') {
                var _authedUser = window.TurnerAuth.getUser();
                if (_authedUser && _authedUser.id) payload.auth_user_id = _authedUser.id;
            }
        } catch (e) { /* never block a real submit over this, Conv #74 */ }

        fetch(API_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(function(res) {
            if (res.ok || res.status === 200 || res.status === 201 || res.status === 204) {
                // GA4 + ad-platform mirror via analytics-events.js.
                // Bot-blocked submits short-circuit in safePostLead,
                // so only real submits reach here.
                if (typeof window.trackLead === 'function') {
                    try {
                        window.trackLead(payload.lead_source || 'boldtrail-form', {
                            region: SITE_REGION,
                            lead_channel: LEAD_CHANNEL,
                            form_tags: (payload.tag || []).join(',')
                        });
                    } catch (e) { /* no-op */ }
                }
                // Tier 1.2 fix 2026-05-19: structured form_submit event with
                // per-form-type + per-source attribution dimensions extracted
                // from the existing tag array. Convention #74 fail-safe.
                try {
                    if (typeof window.gtag === 'function') {
                        var tags = payload.tag || [];
                        var formType = '';
                        var mls = '';
                        var city = '';
                        var agentSlug = '';
                        tags.forEach(function(t) {
                            if (!t) return;
                            if (/^MLS#/i.test(t)) mls = t.replace(/^MLS#/i, '');
                            else if (/^city:/i.test(t)) city = t.replace(/^city:/i, '');
                            else if (/^agent:/i.test(t)) agentSlug = t.replace(/^agent:/i, '');
                            else if (!formType) formType = t;
                        });
                        window.gtag('event', 'form_submit', {
                            form_type: formType || 'unknown',
                            placement: payload.lead_source || '',
                            region: SITE_REGION,
                            lead_channel: LEAD_CHANNEL,
                            mls_number: mls || undefined,
                            listing_city: city || undefined,
                            agent_slug: agentSlug || undefined,
                            has_assignee: !!(payload.assignees && payload.assignees.length)
                        });
                    }
                } catch (e) { /* no-op */ }
                callback(null);
            } else {
                callback('Server error: ' + res.status);
            }
        })
        .catch(function(err) {
            callback(err.message || 'Network error');
        });
    }

    function showSuccess(wrap, html) {
        wrap.innerHTML = '<div class="rf-success"><div class="rf-check"><svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="3"><path d="M5 13l4 4L19 7"/></svg></div>' + html + '</div>';
    }

    function uid() { return 'rf-' + Math.random().toString(36).substr(2, 6); }

    function instrumentForm(formId) {
        var wrap = document.getElementById(formId);
        if (!wrap) return;
        var form = wrap.querySelector('form');
        if (!form) return;
        var btn = form.querySelector('.rf-submit');
        if (btn && !form.querySelector('.rf-hp-field')) {
            btn.insertAdjacentHTML('beforebegin', honeypotHTML);
        }
        recordFormLoad(formId);
    }

    function safePostLead(formId, data, callback) {
        var wrap = document.getElementById(formId);
        var hpVal = '';
        if (wrap) {
            var hpInput = wrap.querySelector('.rf-hp-field input');
            if (hpInput) hpVal = hpInput.value;
        }
        data._hp_company = hpVal;
        var botResult = botCheck(formId, data);
        if (botResult) {
            console.warn('Bot detected (' + botResult + ') — submission blocked');
            setTimeout(function() { callback(null); }, 800);
            return;
        }
        postLead(data, callback);
    }

    // ═══════════════════════════════════════════════════════════
    // 1. HOME VALUATION
    // ═══════════════════════════════════════════════════════════
    function homeValuation(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Find Out What Your Home Is Worth in Today\'s Market</h3>\
            <p class="rf-subhead">We know the Labrador market. Get a free, no-obligation valuation from Karen and Roberta &mdash; the Dynamic Duo.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Property Address</label><input type="text" name="address" data-address-complete autocomplete="off" required placeholder="123 Hamilton River Road, Happy Valley-Goose Bay"></div>\
                <div class="rf-field"><label>Timeline</label>\
                    <select name="timeline">\
                        <option value="">When are you thinking of selling?</option>\
                        <option value="Ready to list">I\'m ready to list</option>\
                        <option value="Within 6 months">Within 6 months</option>\
                        <option value="Just curious">Just curious — no pressure</option>\
                    </select>\
                </div>\
                <div class="rf-field"><label>Who referred you? <span class="rf-optional">(optional)</span></label><input type="text" name="referred_by" placeholder="A friend, past client, agent..."></div>\
                <button type="submit" class="rf-submit">GET MY FREE VALUATION</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        // AddressComplete (Phase 1, 2026-09-06) -- fails open when the fleet
        // key is empty, the service errors, or address-complete.js hasn't
        // loaded on this page yet; the address field behaves exactly as
        // before in every one of those cases.
        if (window.AddressComplete) window.AddressComplete.attach(form.querySelector('[name=address]'), { form: form });
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var timeline = form.querySelector('[name=timeline]').value;
            var address = form.querySelector('[name=address]').value;

            safePostLead(id, {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: Home Evaluation Request | Property: ' + address + (timeline ? ' | Timeline: ' + timeline : ''),
                tag: ['Seller Lead', 'Valuation Request'],
                lead_source: 'Source: Home Evaluation Request',
                property_address: address || undefined,
                address_city: (form.querySelector('[name=address_city]') || {}).value || undefined,
                address_postal: (form.querySelector('[name=address_postal]') || {}).value || undefined,
                address_type: (form.querySelector('[name=address_type]') || {}).value || undefined,
                address_validated: (form.querySelector('[name=address_validated]') || {}).value || undefined,
                timeline: timeline || undefined
            }, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'GET MY FREE VALUATION';
                } else {
                    showSuccess(wrap, '<h4>We\'re On It</h4><p>Thanks ' + fname + ' — one of our team members will be in touch shortly with your home valuation. We know this market inside and out and we\'re glad to help.</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 2. MONTHLY MARKET REPORT (task #81, 2026-07-29 — replaces the generic,
    // Gander-copy-pasted lead-capture stub (wrong area list, wrong phone
    // number) with the real per-region PDF-delivery flow, mirroring
    // realestategander.com's marketReportDownload. Posts to the SHARED
    // Gander-hosted market-report-subscribe function.)
    // ═══════════════════════════════════════════════════════════
    var SUBSCRIBE_URL = API_URL.replace('/lead-receive', '/market-report-subscribe');

        // AddressComplete (2026-09-07) -- kept in lockstep with
    // netlify/functions/market-report-subscribe.ts's REGION_AGENT keys and
    // CITY_TO_REGION_KEY table (see that file's header comment for the full,
    // sourced citation of every alias below -- do not add an entry here that
    // isn't backed by the same citation there).
    var MARKET_REPORT_REGIONS = [
        'Gander and Area', 'Appleton & Glenwood', 'Lewisporte', 'Gambo', 'Gander Loop',
        'Twillingate / Fogo', 'Eastport Peninsula', 'Glovertown / Tray Town',
        'Fogo Island & Change Islands', 'Notre Dame Bay',
        'Bay Bulls and Southern Shore', 'Conception Bay South', "Downtown St. John's",
        "East End St. John's", "Galway St. John's", 'Holyrood and Area',
        "Kenmount St. John's", 'Mount Pearl', "North End St. John's", 'Paradise',
        'Portugal Cove and St. Philips', "South St. John's", "St. John's Metro",
        'Torbay', "West End St. John's", 'Happy Valley / Goose Bay'
    ];
    var MARKET_REPORT_CITY_TO_REGION = {
        'gander': 'Gander and Area', 'appleton': 'Appleton & Glenwood', 'glenwood': 'Appleton & Glenwood',
        'eastport': 'Eastport Peninsula', 'sandringham': 'Eastport Peninsula', 'salvage': 'Eastport Peninsula',
        'happy-adventure': 'Eastport Peninsula', 'gambo': 'Gambo',
        'gander-bay': 'Gander Loop', 'gander-bay-south': 'Gander Loop', 'carmanville': 'Gander Loop',
        'musgrave-harbour': 'Gander Loop', 'lumsden': 'Gander Loop', 'new-wes-valley': 'Gander Loop',
        'greenspond': 'Gander Loop', 'indian-bay': 'Gander Loop', 'hare-bay': 'Gander Loop', 'dover': 'Gander Loop',
        'glovertown': 'Glovertown / Tray Town', 'traytown': 'Glovertown / Tray Town',
        'lewisporte': 'Lewisporte', 'twillingate': 'Twillingate / Fogo',
        'fogo': 'Fogo Island & Change Islands', 'fogo-island': 'Fogo Island & Change Islands',
        'change-islands': 'Fogo Island & Change Islands',
        'notre-dame-bay': 'Notre Dame Bay', 'norris-arm': 'Notre Dame Bay',
        'norris-arm-north': 'Notre Dame Bay', 'campbellton': 'Notre Dame Bay',
        'conception-bay-south': 'Conception Bay South', 'mount-pearl': 'Mount Pearl',
        'paradise': 'Paradise', 'torbay': 'Torbay', 'holyrood': 'Holyrood and Area',
        'bay-bulls': 'Bay Bulls and Southern Shore',
        'portugal-cove-st-philips': 'Portugal Cove and St. Philips',
        'portugal-cove-st-phillips': 'Portugal Cove and St. Philips',
        'portugal-cove-st-phlips': 'Portugal Cove and St. Philips',
        'st-johns': "St. John's Metro", 'happy-valley-goose-bay': 'Happy Valley / Goose Bay'
    };
    function marketReportRegionFromCity(city) {
        if (!city) return '';
        var key = String(city).toLowerCase().trim().replace(/['’]/g, '')
            .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
        return MARKET_REPORT_CITY_TO_REGION[key] || '';
    }

function marketReport(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        var hasKnownRegion = !!(el.getAttribute('data-region-key') || '').trim();
        var regionKey = (el.getAttribute('data-region-key') || 'Happy Valley / Goose Bay').trim();
        var regionLabel = (el.getAttribute('data-region-label') || 'Happy Valley-Goose Bay').trim();
        var source = (el.getAttribute('data-source') || 'market-stats-page').trim();

        var regionFieldHtml = hasKnownRegion ? '' :
            '<div class="rf-field"><label>Your address or postal code</label>' +
            '<input type="text" name="rf-mr-addr" autocomplete="off" placeholder="e.g. 8 Gordon Street, Gander"></div>' +
            '<div class="rf-field"><label>Or pick your area</label><select name="rf-mr-region" required>' +
            '<option value="">' + '\u2014 choose \u2014' + '</option>' +
            MARKET_REPORT_REGIONS.map(function (r) { return '<option value="' + r + '">' + r + '</option>'; }).join('') +
            '</select></div>';

        var headerLabel = hasKnownRegion ? regionLabel : 'local';
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Get the free ' + headerLabel + ' market report</h3>\
            <p class="rf-subhead">A short PDF — the last 12 months of sales, how this year compares to last, the current market balance, and the 10-year trend for ' + headerLabel + ' area. Delivered instantly.</p>\
            <form>\
                <div class="rf-field"><label>Name</label><input type="text" name="fname" required placeholder="Your name"></div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                ' + regionFieldHtml + '\
                <button type="submit" class="rf-submit">SEND ME THE REPORT</button>\
                <p class="rf-consent" style="font-size:11px;color:#888;margin:10px 0 0;line-height:1.5;">Get the report instantly &mdash; we\'ll also email you the link and send you the updated ' + headerLabel + ' report each month. Unsubscribe anytime.</p>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);
        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        var pickedCity = null;
        if (!hasKnownRegion) {
            var addrInput = form.querySelector('[name=rf-mr-addr]');
            loadAddressComplete(function () {
                if (!window.AddressComplete) return;
                window.AddressComplete.attach(addrInput, {
                    fields: false,
                    onSelect: function (addr) {
                        pickedCity = addr.city || null;
                        var resolved = marketReportRegionFromCity(addr.city);
                        var sel = form.querySelector('[name=rf-mr-region]');
                        if (sel && resolved) sel.value = resolved;
                    }
                });
                addrInput.addEventListener('input', function () { pickedCity = null; });
            });
        }
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var name = form.querySelector('[name=fname]').value;
            var email = form.querySelector('[name=email]').value;
            var chosenRegionKey = regionKey;
            var chosenRegionLabel = regionLabel;
            if (!hasKnownRegion) {
                var regionSel = form.querySelector('[name=rf-mr-region]');
                chosenRegionKey = regionSel ? regionSel.value : '';
                chosenRegionLabel = chosenRegionKey || regionLabel;
                if (!chosenRegionKey) {
                    err.textContent = 'Please choose your area.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND ME THE REPORT';
                    return;
                }
            }

            fetch(SUBSCRIBE_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    client_email: email,
                    client_name: name,
                    region_key: chosenRegionKey,
                    city: pickedCity || undefined,
                    site: 'goosebay',
                    source: source,
                    source_url: window.location.href,
                    website: ''
                })
            }).then(function (res) { return res.json().catch(function () { return {}; }); })
              .then(function (data) {
                if (data && data.ok) {
                    try {
                        if (typeof window.gtag === 'function') {
                            window.gtag('event', 'form_submit', {
                                form_type: 'market_report_download',
                                placement: source, region: chosenRegionLabel
                            });
                        }
                        if (typeof window.trackLead === 'function') {
                            window.trackLead('Market Report Download', { region: chosenRegionLabel });
                        }
                    } catch (e2) { /* no-op */ }
                    if (data.pdf_url) {
                        showSuccess(wrap, '<h4>Here\'s your report</h4>' +
                            '<p><a href="' + data.pdf_url + '" target="_blank" rel="noopener" ' +
                            'style="display:inline-block;background:#EA002A;color:#fff;text-decoration:none;font-weight:bold;padding:12px 22px;border-radius:6px;margin:6px 0;">Download the ' + chosenRegionLabel + ' report (PDF)</a></p>' +
                            '<p>We\'ve emailed you the link too &mdash; and we\'ll send an updated report each month.</p>');
                    } else {
                        showSuccess(wrap, '<h4>You\'re subscribed</h4>' +
                            '<p>We\'re preparing this month\'s ' + chosenRegionLabel + ' report &mdash; it\'ll arrive in your inbox shortly, and you\'ll get an updated one each month.</p>');
                    }
                } else {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND ME THE REPORT';
                }
              }).catch(function () {
                err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                err.style.display = 'block';
                btn.disabled = false; btn.textContent = 'SEND ME THE REPORT';
              });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 3. NEW LISTING ALERTS
    // ═══════════════════════════════════════════════════════════
    function listingAlerts(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Be the First to Know When New Homes Hit the Market</h3>\
            <p class="rf-subhead">In a market that moves fast, being first matters. Tell us what you\'re looking for and we\'ll send you matching listings the moment they\'re listed.</p>\
            <form data-consent="alerts">\
                <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name" autocomplete="given-name"></div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com" autocomplete="email"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx" autocomplete="tel"></div>\
                <div class="rf-row">\
                    <div class="rf-field"><label>Price Range</label>\
                        <select name="price">\
                            <option value="">Budget?</option>\
                            <option value="Under $200K">Under $200K</option>\
                            <option value="$200K-$300K">$200K–$300K</option>\
                            <option value="$300K-$400K">$300K–$400K</option>\
                            <option value="$400K-$500K">$400K–$500K</option>\
                            <option value="$500K+">$500K+</option>\
                        </select>\
                    </div>\
                    <div class="rf-field"><label>Property Type</label>\
                        <select name="ptype">\
                            <option value="">What type?</option>\
                            <option value="House">House</option>\
                            <option value="Condo">Condo</option>\
                            <option value="Land">Land</option>\
                            <option value="Commercial">Commercial</option>\
                        </select>\
                    </div>\
                </div>\
                <div class="rf-field"><label>Area</label>\
                    <select name="area">\
                        <option value="">Where?</option>\
                        <option value="Gander">Gander</option>\
                        <option value="Gambo & Area">Gambo & Area</option>\
                        <option value="Glovertown & Area">Glovertown & Area</option>\
                        <option value="All of Central NL">All of Central NL</option>\
                    </select>\
                </div>\
                <label class="tc-alerts" for="' + id + '-lea"><input type="checkbox" id="' + id + '-lea" name="marketing_optin" value="1" data-tc="alerts" required aria-required="true"><span>I agree to receive Listing Email Alerts from Royal LePage Turner Realty, 204 Airport Blvd, Gander NL A1V 1L6. Unsubscribe any time from the link in every email.</span></label>\
                <button type="submit" class="rf-submit">SEND ME LISTINGS</button>\
                <p class="tc-line">Your details are used only to send these alerts and answer you. <a href="/pages/privacy-policy.html">Privacy policy</a>.</p>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var price = form.querySelector('[name=price]').value;
            var ptype = form.querySelector('[name=ptype]').value;
            var area = form.querySelector('[name=area]').value;
            var parts = [];
            if (price) parts.push('Price: ' + price);
            if (ptype) parts.push('Type: ' + ptype);
            if (area) parts.push('Area: ' + area);

            safePostLead(id, {
                first_name: form.querySelector('[name=fname]').value,
                last_name: '',
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: Homepage — Listing Alerts | ' + parts.join(' | '),
                tag: ['Buyer Lead', 'Listing Alert'],
                lead_source: 'Source: Homepage — Listing Alerts',
                property_type: ptype || undefined,
                budget: price || undefined,
                interest_area: area || undefined
            }, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND ME LISTINGS';
                } else {
                    showSuccess(wrap, '<h4>You\'re All Set</h4><p>We\'ll be in touch as soon as something matching your criteria hits the market. In Gander, the good ones move fast.</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 4. NEW CONSTRUCTION INFO PACKAGE
    // ═══════════════════════════════════════════════════════════
    function newConstruction(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Interested in Building New in Gander?</h3>\
            <p class="rf-subhead">Two active subdivisions. Atlantic Home Warranty. Our 5 walk-through system. Get the full info package on East Gate Landing and Cobbs Pond Development — no obligation.</p>\
            <form>\
                <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Which Development?</label>\
                    <select name="dev">\
                        <option value="">What interests you?</option>\
                        <option value="East Gate Landing">East Gate Landing</option>\
                        <option value="Cobbs Pond Development">Cobbs Pond Development</option>\
                        <option value="Both">Both</option>\
                        <option value="Not sure yet">Not sure yet — show me everything</option>\
                    </select>\
                </div>\
                <div class="rf-field"><label>Timeline</label>\
                    <select name="timeline">\
                        <option value="">When are you thinking?</option>\
                        <option value="Ready now">Ready now</option>\
                        <option value="Within a year">Within a year</option>\
                        <option value="Just exploring">Just exploring</option>\
                    </select>\
                </div>\
                <button type="submit" class="rf-submit">SEND ME THE INFO PACKAGE</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var dev = form.querySelector('[name=dev]').value;
            var timeline = form.querySelector('[name=timeline]').value;
            var parts = [];
            if (dev) parts.push('Interest: ' + dev);
            if (timeline) parts.push('Timeline: ' + timeline);

            safePostLead(id, {
                first_name: fname,
                last_name: '',
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: New Construction Inquiry | ' + parts.join(' | '),
                tag: ['New Construction', 'Buyer'],
                lead_source: 'Source: New Construction Inquiry',
                interest_area: dev || undefined,
                property_type: 'New Construction',
                timeline: timeline || undefined
            }, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND ME THE INFO PACKAGE';
                } else {
                    showSuccess(wrap, '<h4>On Its Way</h4><p>Thanks ' + fname + ' — we\'ll send over the full details on both developments. Building new in Gander is one of the best moves you can make right now.</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 5. LISTING INQUIRY
    // ═══════════════════════════════════════════════════════════
    function listingInquiry(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        // Read data attributes from the container element
        var listingAddress = el.getAttribute('data-listing-address') || '';
        var mlsNumber = el.getAttribute('data-mls-number') || '';
        var agentEmail = el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '';

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Interested in This Property?</h3>\
            <p class="rf-subhead">Ask a question, book a showing, or just get more information. ' + replyPromise() + '</p>\
            <form>\
                <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Message</label><textarea name="message" placeholder="What would you like to know?"></textarea></div>\
                <div class="rf-field"><label>Who referred you? <span class="rf-optional">(optional)</span></label><input type="text" name="referred_by" placeholder="A friend, past client, agent..."></div>\
                <button type="submit" class="rf-submit">SEND MY INQUIRY</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var msg = form.querySelector('[name=message]').value;
            var noteParts = [];
            if (listingAddress) noteParts.push('Property: ' + listingAddress);
            if (mlsNumber) noteParts.push('MLS#: ' + mlsNumber);
            if (msg) noteParts.push('Message: ' + msg);

            var data = {
                first_name: form.querySelector('[name=fname]').value,
                last_name: '',
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: Listing Page — Listing Inquiry | ' + noteParts.join(' | '),
                tag: ['Listing Inquiry', 'Buyer'],
                lead_source: 'Source: Listing Page — Listing Inquiry',
                property_address: listingAddress || undefined,
                mls_number: mlsNumber || undefined,
                listing_url: window.location.href,
                message: msg || undefined
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND MY INQUIRY';
                } else {
                    showSuccess(wrap, '<h4>Got It</h4><p>' + replyPromise() + ' If you\'d like to book a showing, just tell us when.</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 6. OPEN HOUSE SIGN-IN
    // ═══════════════════════════════════════════════════════════
    function openHouseSignIn(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        var propertyAddress = el.getAttribute('data-property-address') || '';

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Welcome — Sign In to Stay Connected</h3>\
            <p class="rf-subhead">We\'ll send you the full property details and let you know about similar listings.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Working with an agent?</label>\
                    <select name="hasagent">\
                        <option value="No">No</option>\
                        <option value="Yes">Yes</option>\
                    </select>\
                </div>\
                <button type="submit" class="rf-submit">SIGN IN</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Signing in...'; err.style.display = 'none';

            var hasAgent = form.querySelector('[name=hasagent]').value;
            var noteParts = [];
            if (propertyAddress) noteParts.push('Open House: ' + propertyAddress);
            noteParts.push('Has agent: ' + hasAgent);

            safePostLead(id, {
                first_name: form.querySelector('[name=fname]').value,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: Open House Sign-In | ' + noteParts.join(' | '),
                tag: ['Open House'],
                lead_source: 'Source: Open House Sign-In'
            }, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong — please sign in with the agent at the door.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SIGN IN';
                } else {
                    showSuccess(wrap, '<h4>Thanks for Stopping By</h4><p>We\'ll follow up with the full property details shortly.</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 7. AGENT CONTACT
    // ═══════════════════════════════════════════════════════════
    function agentContact(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        var agentName = el.getAttribute('data-agent-name') || '';
        var agentEmail = el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '';
        var agentPhone = el.getAttribute('data-agent-phone') || '';

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Contact ' + agentName + '</h3>\
            <p class="rf-subhead">Send ' + askNames(agentName) + ' a message directly — whether you\'re buying, selling, or just have a question about the market.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Message <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="How can ' + askNames(agentName) + ' help you?"></textarea></div>\
                <div class="rf-field"><label>Who referred you? <span class="rf-optional">(optional)</span></label><input type="text" name="referred_by" placeholder="A friend, past client, agent..."></div>\
                <button type="submit" class="rf-submit">SEND MESSAGE</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var msg = form.querySelector('[name=message]').value;
            var noteParts = ['Source: Agent Bio — ' + agentName];
            if (msg) noteParts.push('Message: ' + msg);

            var data = {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: noteParts.join(' | '),
                tag: ['Agent Inquiry', agentName],
                lead_source: 'Source: Agent Bio — ' + agentName
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call ' + (agentPhone || '709-896-5001') + ' directly.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND MESSAGE';
                } else {
                    showSuccess(wrap, '<h4>Message Sent</h4><p>Thanks ' + fname + '. ' + replyPromise() + '</p>');
                }
            });
        });
    }

    // ═══════════════════════════════════════════════════════════
    // POPUP MODAL SYSTEM
    // ═══════════════════════════════════════════════════════════
    function popup(formType) {
        injectStyles();
        // Remove any existing overlay
        var old = document.querySelector('.rf-overlay');
        if (old) old.remove();

        // Create overlay
        var overlay = document.createElement('div');
        overlay.className = 'rf-overlay';
        overlay.innerHTML = '<div class="rf-modal"><button class="rf-close" aria-label="Close">&times;</button><div id="rf-popup-target"></div></div>';
        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';

        // Animate in
        requestAnimationFrame(function() { overlay.classList.add('rf-open'); });

        // Close handlers
        function close() {
            overlay.classList.remove('rf-open');
            document.body.style.overflow = '';
            setTimeout(function() { overlay.remove(); }, 250);
        }
        overlay.querySelector('.rf-close').addEventListener('click', close);
        overlay.addEventListener('click', function(e) { if (e.target === overlay) close(); });
        document.addEventListener('keydown', function handler(e) {
            if (e.key === 'Escape') { close(); document.removeEventListener('keydown', handler); }
        });

        // Inject the right form
        var target = '#rf-popup-target';
        var formMap = {
            'homeValuation': homeValuation,
            'marketReport': marketReport,
            'listingAlerts': listingAlerts,
            'newConstruction': newConstruction,
            'listingInquiry': listingInquiry,
            'openHouseSignIn': openHouseSignIn,
            'agentContact': agentContact,
            'buyerConsult': buyerConsult,
            'commercialInquiry': commercialInquiry,
            'preApproval': preApproval
        };
        if (formMap[formType]) {
            formMap[formType](target);
        } else {
            // Default to listing alerts
            listingAlerts(target);
        }
    }

    // ═══════════════════════════════════════════════════════════
    // AUTO-BIND CTA BUTTONS
    // ═══════════════════════════════════════════════════════════
    // Any link with data-rf-popup="formType" will open the popup
    // instead of navigating. Apply after DOM loads.
    function bindPopupButtons() {
        document.querySelectorAll('[data-rf-popup]').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                popup(btn.getAttribute('data-rf-popup'));
            });
        });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindPopupButtons);
    } else {
        bindPopupButtons();
    }

    // ═══════════════════════════════════════════════════════════
    // EXIT-INTENT POPUP
    // ═══════════════════════════════════════════════════════════
    // Triggers when mouse leaves the viewport (desktop) or after
    // 45 seconds on mobile. Shows once per session.
    // D-1009-69 (outside review of the live Avalon homepage: "a listings sign-up popup appeared mid-review and covered the homepage"):
    // the Listing Text/Email Alerts prompt never opens on arrival. It is offered (a) after the visitor has run a search this session
    // (the hero/header search form submitted, or a /listings/ or /search/ page opened with ?q=), on the exit-intent / 45 s triggers
    // below, once per session; and (b) whenever the visitor asks, through any link or button with data-rf-popup="listingAlerts".
    function markSearched() { try { sessionStorage.setItem('rf-searched', '1'); } catch (e) {} }
    function hasSearched() { try { return sessionStorage.getItem('rf-searched') === '1'; } catch (e) { return false; } }
    document.addEventListener('submit', function(e) {
        var f = e.target;
        if (f && f.matches && f.matches('.hp-search-form, form[role="search"], form.hx-search')) markSearched();
    }, true);
    if (/^\/(listings|search)\//.test(location.pathname) && /[?&](q|query)=/.test(location.search)) markSearched();

    function exitIntent(formType) {
        if (sessionStorage.getItem('rf-exit-shown')) return;

        var triggered = false;
        function show() {
            if (triggered) return;
            if (!hasSearched()) return;   // never on arrival: only after a search (D-1009-69)
            if (sessionStorage.getItem('rf-exit-shown')) return;
            triggered = true;
            sessionStorage.setItem('rf-exit-shown', '1');
            popup(formType || 'homeValuation');
        }

        // Desktop: mouse leaves viewport toward top
        document.addEventListener('mouseout', function(e) {
            if (e.clientY < 5 && e.relatedTarget === null) show();
        });

        // Mobile: after 45 seconds of engagement
        setTimeout(function() {
            if (!triggered && document.visibilityState === 'visible') show();
        }, 45000);
    }

    // ═══════════════════════════════════════════════════════════
    // STICKY MOBILE CTA BAR — RETIRED 2026-09-17
    // ═══════════════════════════════════════════════════════════
    // Superseded by the site-owned js/mobile-action-bar.js (Mobile + iPad
    // review of the fleet, Part 1 Tier B row B1): one Call/Text/[Book a
    // Showing|Alerts|Home Value] bar shown on every page under 1024px,
    // instead of every page calling stickyBar() with its own inconsistent
    // form/label pair. Left as a documented no-op (not deleted) so the
    // ~40 existing call sites across pages/*.html keep working without a
    // mechanical per-page edit — none of them may render a `.rf-sticky-bar`
    // again. If a future page genuinely needs a one-off sticky CTA distinct
    // from the shared bar, build that deliberately rather than reviving this.
    function stickyBar() { /* no-op — see comment above */ }

    // ═══════════════════════════════════════════════════════════
    // 8. JOIN OUR TEAM — agent recruiting (routes to the broker, Mike)
    // ═══════════════════════════════════════════════════════════
    function buyerConsult(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Talk to an Agent</h3>\
            <p class="rf-subhead">Get straight answers from a local REALTOR\u00ae \u2014 no pressure, no obligation.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>What can we help with?</label>\
                    <select name="topic">\
                        <option value="">Choose one (optional)</option>\
                        <option value="Buying a home">Buying a home</option>\
                        <option value="Mortgage pre-approval">Mortgage pre-approval</option>\
                        <option value="Selling a home">Selling a home</option>\
                        <option value="Investment property">Investment property</option>\
                        <option value="General question">Just have a question</option>\
                    </select>\
                </div>\
                <div class="rf-field"><label>Message <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="Anything else we should know?"></textarea></div>\
                <button type="submit" class="rf-submit">TALK TO AN AGENT</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var topic = form.querySelector('[name=topic]').value;
            var msg = form.querySelector('[name=message]').value;
            var noteParts = ['Source: Buyer Consultation Request'];
            if (topic) noteParts.push('Topic: ' + topic);
            if (msg) noteParts.push('Message: ' + msg);

            var data = {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: noteParts.join(' | '),
                tag: ['Buyer Consultation'].concat(topic ? [topic] : []),
                lead_source: 'Source: Buyer Consultation Request' + (topic ? ' \u2014 ' + topic : '')
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'TALK TO AN AGENT';
                } else {
                    showSuccess(wrap, '<h4>Message Sent</h4><p>Thanks ' + fname + '. ' + replyPromise() + '</p>');
                }
            });
        });
    }

    // ─── Confidential recruiting lane (gate RECRUIT_FORM, D-1008-106 follow-up) ───
    // Shared endpoint: realestategander.com's recruit-inquiry (its CORS list includes this site; gate RECRUIT_FORM is set on the
    // Gander Netlify site, so one switch covers every site). Ported from realestategander-site js/boldtrail-forms.js (#938).
    // The recruiting function (netlify/functions/recruit-inquiry.ts) answers GET {enabled}. Only on enabled:true does joinTeam
    // send to it (ONE email to the broker; no office inbox, no Cc, no FUB, no phone_leads row) instead of lead-receive. An explicit
    // {enabled:false} leaves joinTeam exactly as it was. Anything else (network error, non-200, no boolean answer) FAILS CLOSED:
    // the form is replaced by a line with the phone numbers below and nothing is posted anywhere (Mike, 2026-10-09: "Fail closed").
    // Same endpoint and payload contract as Gander's js/recruit-form.js.
    var RECRUIT_URL = 'https://realestategander.com/.netlify/functions/recruit-inquiry';
    var RECRUIT_YEARS = ['Not licensed yet', 'Licence in progress', 'Under 2 years', '2 to 5 years', '5 to 10 years', 'Over 10 years'];
    function recruitSiteId() {
        var s = (window.TURNER_SITE || '').toLowerCase();
        if (s) return s;
        var h = location.hostname;
        if (/avalonrealestate/.test(h)) return 'avalon';
        if (/labwest/.test(h)) return 'labwest';
        if (/royallepageturner/.test(h)) return 'hub';
        if (/goosebay/.test(h)) return 'goosebay';
        return 'gander';
    }
    var RECRUIT_CLOSED_HTML = 'Our online form is not available right now. Please call the office at <a href="tel:+17098965001" style="color:inherit;font-weight:600;">709-896-5001</a>.';
    // 'on' | 'off' | 'unknown'. Only an explicit {enabled:false} is 'off'; 'unknown' means fail closed (post nothing).
    function recruitGate() {
        if (typeof fetch !== 'function') return Promise.resolve('unknown');
        return fetch(RECRUIT_URL, { method: 'GET', headers: { Accept: 'application/json' } })
            .then(function(r) { return r.ok ? r.json() : null; })
            .then(function(j) { return (j && j.enabled === true) ? 'on' : (j && j.enabled === false) ? 'off' : 'unknown'; })
            .catch(function() { return 'unknown'; });
    }

    function joinTeam(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Inquire Confidentially</h3>\
            <p class="rf-subhead">Tell us a bit about yourself — every conversation is completely confidential, with no obligation.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Are you currently licensed?</label>\
                    <select name="license">\
                        <option value="">Select one&hellip;</option>\
                        <option value="Licensed REALTOR">Yes — currently licensed REALTOR&reg;</option>\
                        <option value="Licence in progress">In progress — completing licensing</option>\
                        <option value="Considering the career">Considering a career in real estate</option>\
                    </select>\
                </div>\
                <div class="rf-field"><label>Anything you\'d like us to know? <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="Experience, goals, questions&hellip;"></textarea></div>\
                <button type="submit" class="rf-submit">SUBMIT CONFIDENTIAL INQUIRY</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';

        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');

        // RECRUIT_FORM: 'pending' until the gate answers, then 'on', 'off' or 'unknown'. A submit that arrives while pending waits for it.
        var rgate = { state: 'pending', p: null };
        function showClosed() {
            // Fail closed: hide the form, show the phone line once, post nothing.
            form.style.display = 'none';
            if (!wrap.querySelector('.rf-closed')) form.insertAdjacentHTML('afterend', '<p class="rf-closed" style="font-size:1rem;line-height:1.6;margin:0;color:#fff;">' + RECRUIT_CLOSED_HTML + '</p>');
        }
        rgate.p = recruitGate().then(function(st) {
            rgate.state = st;
            if (st === 'unknown') { showClosed(); return; }
            if (st !== 'on') return;
            // Gate on: add the fields the confidential form needs and say who receives it.
            var sub = wrap.querySelector('.rf-subhead');
            if (sub) sub.textContent = 'This goes only to Mike Turner, Broker/Owner. It is not copied to anyone else at the brokerage and is not added to our client database. He will contact you personally.';
            var phoneEl = form.querySelector('[name=phone]');
            if (phoneEl) { phoneEl.required = true; var pl = phoneEl.parentNode.querySelector('.rf-optional'); if (pl) pl.parentNode.removeChild(pl); }
            var msgEl = form.querySelector('[name=message]');
            if (msgEl) { msgEl.required = true; var ml = msgEl.parentNode.querySelector('.rf-optional'); if (ml) ml.parentNode.removeChild(ml); }
            var licField = form.querySelector('[name=license]');
            var yearsHTML = '<div class="rf-field"><label>Current brokerage <span class="rf-optional">(optional)</span></label><input type="text" name="brokerage" autocomplete="organization"></div>' +
                '<div class="rf-field"><label>Years licensed</label><select name="years_licensed" required><option value="">Select one&hellip;</option>' +
                RECRUIT_YEARS.map(function(y) { return '<option value="' + y + '">' + y + '</option>'; }).join('') + '</select></div>';
            if (licField && licField.parentNode) licField.parentNode.insertAdjacentHTML('afterend', yearsHTML);
            var consentHTML = '<div class="rf-field"><label style="display:flex;gap:10px;align-items:flex-start;font-weight:400;"><input type="checkbox" name="consent" style="margin-top:3px;width:18px;height:18px;flex:none;"><span>I agree that Mike Turner may contact me by email or phone about this inquiry.</span></label></div>';
            var hp = form.querySelector('.rf-hp-field');
            var sb = form.querySelector('.rf-submit');
            (hp || sb).insertAdjacentHTML('beforebegin', consentHTML);
        });

        // Gate on: ONE email to the broker through recruit-inquiry. Never safePostLead / lead-receive.
        function sendConfidential(btn, err) {
            var v = function(n) { var f = form.querySelector('[name=' + n + ']'); return f ? String(f.value || '').trim() : ''; };
            var name = (v('fname') + ' ' + v('lname')).trim();
            var problem = !v('fname') ? 'Please add your name.' :
                !/^[^\s@<>]+@[^\s@<>]+\.[a-z]{2,}$/i.test(v('email')) ? 'Please check your email address.' :
                (v('phone').match(/\d/g) || []).length < 7 ? 'Please add a phone number.' :
                !v('years_licensed') ? 'Please choose how long you have been licensed.' :
                !v('message') ? 'Please add a short message.' :
                !form.querySelector('[name=consent]').checked ? 'Please tick the consent box.' : '';
            if (problem) { err.textContent = problem; err.style.display = 'block'; btn.disabled = false; btn.textContent = 'SUBMIT CONFIDENTIAL INQUIRY'; return; }
            var hpIn = wrap.querySelector('.rf-hp-field input');
            var hpVal = hpIn ? hpIn.value : '';
            var botResult = botCheck(id, { _hp_company: hpVal, first_name: v('fname'), last_name: v('lname'), email: v('email') });
            var thanks = '<h4>Thank You</h4><p>Your inquiry is completely confidential. Our broker will be in touch personally ' + replyWindow() + '.</p>';
            if (botResult) { console.warn('Bot detected (' + botResult + ') — submission blocked'); setTimeout(function() { showSuccess(wrap, thanks); }, 800); return; }
            fetch(RECRUIT_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name, email: v('email'), phone: v('phone'), brokerage: v('brokerage'),
                    years_licensed: v('years_licensed'), message: v('message'), consent: true,
                    company_website: hpVal, site: recruitSiteId(), page: location.pathname
                })
            }).then(function(r) { return r.json().catch(function() { return {}; }).then(function(j) { return { ok: r.ok && j && j.ok, j: j || {} }; }); })
              .then(function(res) {
                if (res.ok) {
                    try { if (typeof window.gtag === 'function') window.gtag('event', 'recruiting_inquiry', { form_name: 'confidential_broker_form', site: recruitSiteId() }); } catch (x) { /* no-op */ }
                    showSuccess(wrap, thanks);
                } else {
                    err.textContent = (res.j.message ? res.j.message + ' ' : 'Something went wrong. ') + 'Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SUBMIT CONFIDENTIAL INQUIRY';
                }
              })
              .catch(function() {
                err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                err.style.display = 'block';
                btn.disabled = false; btn.textContent = 'SUBMIT CONFIDENTIAL INQUIRY';
              });
        }

        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            if (rgate.state === 'pending') {
                // The gate has not answered yet: wait for it, then run this same submit again.
                btn.disabled = true; btn.textContent = 'Sending...';
                rgate.p.then(function() { btn.disabled = false; form.dispatchEvent(new Event('submit', { cancelable: true })); });
                return;
            }
            if (rgate.state === 'unknown') { showClosed(); return; }
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';
            if (rgate.state === 'on') { sendConfidential(btn, err); return; }

            var license = form.querySelector('[name=license]').value || 'Not specified';
            var msg = form.querySelector('[name=message]').value;
            var noteParts = ['License status: ' + license];
            if (msg) noteParts.push('Message: ' + msg);

            var data = {
                first_name: form.querySelector('[name=fname]').value,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Agent recruiting inquiry — ' + noteParts.join(' | '),
                tag: ['Recruitment', 'Agent Recruiting'],
                lead_source: 'Source: Join Our Team — Agent Recruiting',
                assignees: [{ email: 'miketurner@royallepage.ca' }]
            };

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SUBMIT CONFIDENTIAL INQUIRY';
                } else {
                    showSuccess(wrap, '<h4>Thank You</h4><p>Your inquiry is completely confidential. Our broker will be in touch personally ' + replyWindow() + '.</p>');
                }
            });
        });
    }

    function bookShowing(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        var listingAddress = el.getAttribute('data-listing-address') || '';
        var listingCity    = el.getAttribute('data-listing-city') || '';
        var listingPrice   = el.getAttribute('data-listing-price') || '';
        var mlsNumber      = el.getAttribute('data-mls-number') || '';
        var agentEmail     = el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '';
        var teamName       = el.getAttribute('data-team-name') || 'The Dynamic Duo';

        var tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        var tomorrowISO = tomorrow.toISOString().slice(0, 10);

        el.innerHTML = '\
        <div class="rf-form-wrap rf-form-flush" id="' + id + '">\
            <h3>Book a Showing</h3>\
            <p class="rf-subhead">Pick a date and time. ' + replyPromise() + '</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name" autocomplete="given-name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name" autocomplete="family-name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com" autocomplete="email"></div>\
                <div class="rf-field"><label>Phone</label><input type="tel" name="phone" required placeholder="709-xxx-xxxx" autocomplete="tel"></div>\
                <div class="rf-row">\
                    <div class="rf-field"><label>Preferred Date</label><input type="date" name="showing_date" required min="' + tomorrowISO + '" value="' + tomorrowISO + '"></div>\
                    <div class="rf-field"><label>Preferred Time</label>\
                        <select name="showing_time" required>\
                            <option value="Morning (9 AM – 12 PM)">Morning (9 AM – 12 PM)</option>\
                            <option value="Afternoon (12 – 5 PM)" selected>Afternoon (12 – 5 PM)</option>\
                            <option value="Evening (5 – 8 PM)">Evening (5 – 8 PM)</option>\
                            <option value="Any time — let\'s coordinate">Any time — let\'s coordinate</option>\
                        </select>\
                    </div>\
                </div>\
                <div class="rf-field"><label>Notes <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="Anything we should know before the showing?"></textarea></div>\
                <div class="rf-field"><label>Who referred you? <span class="rf-optional">(optional)</span></label><input type="text" name="referred_by" placeholder="A friend, past client, agent..."></div>\
                <button type="submit" class="rf-submit">REQUEST SHOWING</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var showingDate = form.querySelector('[name=showing_date]').value;
            var showingTime = form.querySelector('[name=showing_time]').value;
            var msg         = form.querySelector('[name=message]').value;

            // 2026-08-04: surface the requested date/time STRUCTURALLY. These two required
            // fields have always been collected but only ever travelled inside the synthetic
            // `note` blob, which lead-receive.ts drops whenever a structured field is present
            // — so every web showing request reached the agent with no requested time.
            // ⚠ `new Date('2026-08-05')` parses as UTC MIDNIGHT, which in NL (UTC-2:30/-3:30)
            // renders as the PREVIOUS day. Append T00:00:00 to force local-time parsing.
            var showingWhen = showingDate;
            try {
                var _sd = new Date(showingDate + 'T00:00:00');
                if (!isNaN(_sd.getTime())) {
                    showingWhen = _sd.toLocaleDateString('en-CA', {
                        weekday: 'short', year: 'numeric', month: 'short', day: 'numeric'
                    });
                }
            } catch (e) { /* fall back to the raw ISO date — never block the lead */ }

            var noteParts = [];
            if (listingAddress) noteParts.push('Property: ' + listingAddress);
            if (mlsNumber)      noteParts.push('MLS#: ' + mlsNumber);
            if (listingPrice)   noteParts.push('Listed: ' + listingPrice);
            noteParts.push('Requested date: ' + showingDate);
            noteParts.push('Preferred time: ' + showingTime);
            if (msg)            noteParts.push('Notes: ' + msg);

            var tags = ['Showing Request', 'Buyer'];
            if (mlsNumber)   tags.push('MLS#' + mlsNumber);
            if (listingCity) tags.push('city:' + listingCity);

            var data = {
                first_name: form.querySelector('[name=fname]').value,
                last_name:  form.querySelector('[name=lname]').value,
                email:      form.querySelector('[name=email]').value,
                phone:      form.querySelector('[name=phone]').value,
                note:       'Source: Listing Page — Showing Request | ' + noteParts.join(' | '),
                // Structured field (2026-08-04) so the requested window survives the server's
                // note-deduplication and lands in the agent email, the CRM note and the
                // phone_leads.preferred_showing_windows column the phone/Retell path already fills.
                preferred_showing_windows: [showingWhen + ' — ' + showingTime],
                tag:        tags,
                lead_source: 'Source: Listing Page — Showing Request',
                property_address: listingAddress || undefined,
                mls_number: mlsNumber || undefined,
                listing_url: window.location.href,
                interest_area: listingCity || undefined,
                message: msg || undefined
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at 709-896-5001.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'REQUEST SHOWING';
                } else {
                    showSuccess(wrap,
                        '<h4>Showing Request Sent</h4>' +
                        '<p>' + replyPromise() + ' ' +
                        'For urgent same-day showings, please call us at ' +
                        '<a href="tel:7098965001" style="color:#EA002A;">709-896-5001</a>.</p>'
                    );
                }
            });
        });
    }

    function communityInquiry(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        var agentName = el.getAttribute('data-agent-name') || 'the Turner Realty Team';
        var agentEmail = el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '';
        var agentPhone = el.getAttribute('data-agent-phone') || '709-896-5001';
        var agentSlug = el.getAttribute('data-agent-slug') || '';
        var community = el.getAttribute('data-community') || 'the area';
        var communitySlug = el.getAttribute('data-community-slug') || '';
        var first = askNames(agentName);

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Ask ' + agentName + ' about ' + community + '</h3>\
            <p class="rf-subhead">Thinking about ' + community + '? Send ' + first + ' a message &mdash; buying, selling, or just a question about the local market.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Message <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="How can ' + first + ' help you in ' + community + '?"></textarea></div>\
                <div class="rf-field"><label>Who referred you? <span class="rf-optional">(optional)</span></label><input type="text" name="referred_by" placeholder="A friend, past client, agent..."></div>\
                <button type="submit" class="rf-submit">SEND MESSAGE</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var msg = form.querySelector('[name=message]').value;
            var noteParts = ['Source: Community Page — ' + community];
            if (msg) noteParts.push('Message: ' + msg);

            var tags = ['Community Inquiry'];
            if (agentSlug) tags.push('agent:' + agentSlug);
            if (communitySlug) tags.push('city:' + communitySlug);
            tags.push(agentName);

            var data = {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: noteParts.join(' | '),
                tag: tags,
                lead_source: 'Source: Community Page — ' + community,
                interest_area: community
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call ' + agentPhone + ' directly.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND MESSAGE';
                } else {
                    showSuccess(wrap, '<h4>Message Sent</h4><p>Thanks ' + fname + '. ' + replyPromise() + '</p>');
                }
            });
        });
    }

    // ─── COMMERCIAL INQUIRY (2026-07-24) ─────────────────────
    // The commercial hubs had no capture at all — only a tel: and (on Avalon +
    // Goosebay) a raw untracked mailto:. Chris's Jul-24 commercial showing lead
    // arrived despite that, so the surface converts; it just wasn't measured or
    // routed. Container-data-attr driven exactly like communityInquiry, so the
    // generator sets routing per site (Avalon→Chris, Gander→Mike, Goosebay→Duo).
    function commercialInquiry(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();

        var agentName = el.getAttribute('data-agent-name') || 'our commercial team';
        var agentEmail = el.getAttribute('data-agent-email') || el.getAttribute('data-team-email') || '';
        var agentPhone = el.getAttribute('data-agent-phone') || '709-896-5001';
        var agentSlug = el.getAttribute('data-agent-slug') || '';
        var market = el.getAttribute('data-market') || 'Newfoundland and Labrador';
        var first = askNames(agentName);

        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Talk to ' + agentName + ' about commercial property</h3>\
            <p class="rf-subhead">Buying, leasing, or listing commercial space in ' + market + '? Tell ' + first + ' what you\'re after &mdash; you\'ll get a real reply, not a brochure.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-row">\
                    <div class="rf-field"><label>I want to</label><select name="intent" required>\
                        <option value="">Select&hellip;</option>\
                        <option value="Buy">Buy commercial property</option>\
                        <option value="Lease">Lease commercial space</option>\
                        <option value="Sell or lease out">Sell or lease out my property</option>\
                        <option value="Invest">Invest / explore opportunities</option>\
                    </select></div>\
                    <div class="rf-field"><label>Property use</label><select name="use" required>\
                        <option value="">Select&hellip;</option>\
                        <option value="Retail">Retail / storefront</option>\
                        <option value="Office">Office</option>\
                        <option value="Industrial">Industrial / warehouse</option>\
                        <option value="Hospitality">Restaurant / hospitality</option>\
                        <option value="Land">Development land</option>\
                        <option value="Multi-unit">Multi-unit / investment</option>\
                        <option value="Other">Something else</option>\
                    </select></div>\
                </div>\
                <div class="rf-row">\
                    <div class="rf-field"><label>Approx. size <span class="rf-optional">(optional)</span></label><input type="text" name="sqft" placeholder="e.g. 2,500 sq ft"></div>\
                    <div class="rf-field"><label>Timeline <span class="rf-optional">(optional)</span></label><select name="timeline">\
                        <option value="">Select&hellip;</option>\
                        <option value="ASAP">As soon as possible</option>\
                        <option value="1-3 months">1&ndash;3 months</option>\
                        <option value="3-6 months">3&ndash;6 months</option>\
                        <option value="6-12 months">6&ndash;12 months</option>\
                        <option value="Just exploring">Just exploring</option>\
                    </select></div>\
                </div>\
                <div class="rf-field"><label>Details <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="Location, budget, must-haves &mdash; anything that helps ' + first + ' point you at the right space."></textarea></div>\
                <button type="submit" class="rf-submit">SEND INQUIRY</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var intent = form.querySelector('[name=intent]').value;
            var use = form.querySelector('[name=use]').value;
            var sqft = form.querySelector('[name=sqft]').value;
            var timeline = form.querySelector('[name=timeline]').value;
            var msg = form.querySelector('[name=message]').value;

            // The agent-facing summary. Structured fields also ride the payload
            // (property_type/timeline/interest_area) so kvCORE shows them natively.
            var noteParts = ['Source: Commercial — ' + market];
            if (intent) noteParts.push('Intent: ' + intent);
            if (use) noteParts.push('Use: ' + use);
            if (sqft) noteParts.push('Size: ' + sqft);
            if (timeline) noteParts.push('Timeline: ' + timeline);
            if (msg) noteParts.push('Details: ' + msg);

            // First tag = GA4 form_type. 'Commercial Inquiry' also drives the
            // server's lead_type mapping (legacyTagsToLeadType) → listing_inquiry.
            var tags = ['Commercial Inquiry'];
            if (agentSlug) tags.push('agent:' + agentSlug);
            if (use) tags.push('use:' + use);
            tags.push(agentName);

            // Keep the typed details as the real message_body; fold the
            // structured answers in so the agent email leads with them.
            var bodyParts = [];
            if (intent || use) bodyParts.push((intent || 'Inquiry') + ' — ' + (use || 'commercial'));
            if (sqft) bodyParts.push('Approx. ' + sqft);
            if (msg) bodyParts.push(msg);

            var data = {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: noteParts.join(' | '),
                tag: tags,
                lead_source: 'Source: Commercial — ' + market,
                property_type: 'Commercial',
                interest_area: market,
                timeline: timeline,
                message: bodyParts.join(' · ')
            };
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            safePostLead(id, data, function(error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call ' + agentPhone + ' directly.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'SEND INQUIRY';
                } else {
                    showSuccess(wrap, '<h4>Inquiry Sent</h4><p>Thanks ' + fname + '. ' + replyPromise() + ' For anything urgent, call ' + agentPhone + '.</p>');
                }
            });
        });
    }

    // ─── MORTGAGE PRE-APPROVAL (2026-08-18) ───────────────────
    // Captures the buyer as a Turner lead (agent-assigned via buildAssignees),
    // then hands off directly to our RBC mortgage specialist Kevin Doyle via
    // his specialist link + direct phone. Ported from the Gander canary
    // (js/boldtrail-forms.js:preApproval) — same shape, GB's own specialist.
    function preApproval(selector) {
        injectStyles();
        var el = document.querySelector(selector);
        if (!el) return;
        var id = uid();
        el.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>Get Pre-Approved</h3>\
            <p class="rf-subhead">Know your real number before you shop. Send us a couple of details and we\'ll connect you straight to our trusted RBC mortgage specialist, Kevin Doyle — no obligation.</p>\
            <form>\
                <div class="rf-row">\
                    <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                    <div class="rf-field"><label>Last Name</label><input type="text" name="lname" required placeholder="Last name"></div>\
                </div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Price range you\'re considering <span class="rf-optional">(optional)</span></label>\
                    <select name="pricerange">\
                        <option value="">Choose one (optional)</option>\
                        <option value="Under $200K">Under $200K</option>\
                        <option value="$200K–$350K">$200K–$350K</option>\
                        <option value="$350K–$500K">$350K–$500K</option>\
                        <option value="$500K+">$500K+</option>\
                    </select>\
                </div>\
                <div class="rf-field"><label>When are you looking to buy? <span class="rf-optional">(optional)</span></label>\
                    <select name="timeline">\
                        <option value="">Choose one (optional)</option>\
                        <option value="ASAP / actively looking">ASAP / actively looking</option>\
                        <option value="1–3 months">1–3 months</option>\
                        <option value="3–6 months">3–6 months</option>\
                        <option value="Just researching">Just researching</option>\
                    </select>\
                </div>\
                <button type="submit" class="rf-submit">GET PRE-APPROVED</button>\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';

            var fname = form.querySelector('[name=fname]').value;
            var pr = form.querySelector('[name=pricerange]').value;
            var tl = form.querySelector('[name=timeline]').value;
            var noteParts = ['Source: Mortgage Pre-Approval Request'];
            if (pr) noteParts.push('Price range: ' + pr);
            if (tl) noteParts.push('Timeline: ' + tl);

            var data = {
                first_name: fname,
                last_name: form.querySelector('[name=lname]').value,
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: noteParts.join(' | '),
                tag: ['Pre-Approval', 'Mortgage'].concat(tl ? [tl] : []),
                lead_source: 'Source: Mortgage Pre-Approval Request'
            };
            if (pr) data.budget = pr;
            if (tl) data.timeline = tl;
            var assignees = buildAssignees(el);
            if (assignees.length) data.assignees = assignees;

            // The buyer's path to Kevin should not depend on the CRM post
            // (Convention #74) — capture is best-effort; the RBC hand-off
            // shows on both success and error.
            safePostLead(id, data, function() {
                showSuccess(wrap, '<h4>You\'re one step away, ' + fname + '</h4>\
                    <p>A Turner Realty agent will follow up. To get your real pre-approval number, connect directly with our trusted RBC mortgage specialist:</p>\
                    <div style="margin:18px auto 0;max-width:380px;padding:18px;border:1px solid #333;border-radius:8px;background:#111;text-align:left;">\
                        <div style="font-weight:700;color:#fff;font-size:1.05rem;">Kevin Doyle</div>\
                        <div style="color:rgba(255,255,255,0.55);font-size:0.85rem;margin-bottom:14px;">RBC Mortgage Specialist</div>\
                        <a href="https://mortgage.rbc.com/kevin.g.doyle" target="_blank" rel="noopener" style="display:block;text-align:center;padding:13px 16px;background:#EA002A;color:#fff;text-decoration:none;font-weight:700;border-radius:5px;">Start your RBC pre-approval &rarr;</a>\
                        <a href="tel:7098961430" style="display:block;text-align:center;margin-top:10px;color:rgba(255,255,255,0.75);text-decoration:none;font-size:0.9rem;">Or call Kevin directly: 709-896-1430</a>\
                    </div>');
                try {
                    var _rbc = wrap.querySelector('a[href*="kevin.g.doyle"]');
                    var _tel = wrap.querySelector('a[href^="tel:709896"]');
                    var _ho = function(ch){ return function(){ try { if (typeof window.gtag==="function") window.gtag("event","preapproval_handoff",{ partner:"kevin_doyle_rbc", channel:ch, region:"Goose Bay" }); } catch(e){} }; };
                    if (_rbc) _rbc.addEventListener('click', _ho('rbc_apply'));
                    if (_tel) _tel.addEventListener('click', _ho('phone'));
                } catch(e){}
});
        });
    }

    // ═══════════════════════════════════════════════════════════
    // 5c. ASK [AGENT] FOR A PERSONAL REVIEW (site, Mike 2026-09-30 item 6)
    // ═══════════════════════════════════════════════════════════
    // Third tab on the listing-detail inquiry card. Built here (not in the generated HTML) from data-review-*
    // attributes on .lst-cta-card, so with the gate off or in preview the public HTML carries no review text.
    //   data-review="preview": only builds when the URL has ?preview=review;  "on": always;  absent: never.
    // Lead path = the SAME one as "Ask a Question": postLead -> lead-receive, lead_type listing_inquiry via
    // tools/lead_source_registry.json ("source: listing page — personal review request"), tags
    // ['Listing Inquiry','Personal Review','Buyer'], routed to the listing agent (assignees from
    // data-review-agent-uuid / -email, falling back to the team email = Turner Realty Team).
    // No email of its own: whatever lead-receive already does for a listing_inquiry lead.
    // CONSENT OPTION (Mike decides): the Book a Showing / Ask a Question forms carry NO consent text today (server records
    // casl_consent='express_inquiry'), so the default here is none. If Mike writes one line for all three forms, put it in
    // ONE shared helper and use it here too. Do not use the marketing-checkbox path (it upgrades to express_marketing).
    var PERSONAL_REVIEW_CONSENT = '';
    function personalReview(selector) {
        var card = document.querySelector(selector);
        if (!card) return;
        var mode = (card.getAttribute('data-review') || '').toLowerCase();
        if (mode !== 'on' && !(mode === 'preview' && /[?&]preview=review(&|$)/.test(window.location.search))) return;
        var tabs = card.querySelector('.lst-rf-tabs');
        var inquiry = card.querySelector('[data-rf-panel="inquiry"]');
        if (!tabs || !inquiry) return;
        injectStyles();
        var id = uid();
        var agent = card.getAttribute('data-review-agent') || '';
        var first = card.getAttribute('data-review-first') || '';
        var teamLabel = card.getAttribute('data-review-teamlabel') || 'Ask the Turner Realty Team';
        var who = first || (teamLabel.replace(/^Ask /, '').replace(/^./, function (c) { return c.toUpperCase(); }));
        var listingAddress = card.getAttribute('data-review-address') || '';
        var mlsNumber = card.getAttribute('data-review-mls') || '';
        var city = card.getAttribute('data-review-city') || '';
        var assigneeHost = {
            getAttribute: function (n) {
                return card.getAttribute(n.replace('data-', 'data-review-'));
            }
        };
        function esc(t) { return String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }

        var tab = document.createElement('button');
        tab.className = 'lst-rf-tab';
        tab.type = 'button';
        tab.setAttribute('data-rf-tab', 'review');
        tab.setAttribute('role', 'tab');
        tab.setAttribute('aria-selected', 'false');
        tab.textContent = first ? 'Ask ' + first + ' for a personal review' : teamLabel;
        tabs.appendChild(tab);

        var panel = document.createElement('div');
        panel.id = 'lst-review-form';
        panel.className = 'lst-rf-panel';
        panel.setAttribute('data-rf-panel', 'review');
        panel.setAttribute('role', 'tabpanel');
        panel.hidden = true;
        inquiry.parentNode.insertBefore(panel, inquiry.nextSibling);

        panel.innerHTML = '\
        <div class="rf-form-wrap" id="' + id + '">\
            <h3>' + esc(first ? 'Ask ' + first + ' for a personal review' : teamLabel) + '</h3>\
            <p class="rf-subhead">I\'ll look at this one myself and send you my own take.</p>\
            <form>\
                <div class="rf-field"><label>First Name</label><input type="text" name="fname" required placeholder="First name"></div>\
                <div class="rf-field"><label>Email</label><input type="email" name="email" required placeholder="your@email.com"></div>\
                <div class="rf-field"><label>Phone <span class="rf-optional">(optional)</span></label><input type="tel" name="phone" placeholder="709-xxx-xxxx"></div>\
                <div class="rf-field"><label>Anything you want my take on? <span class="rf-optional">(optional)</span></label><textarea name="message" placeholder="Price, condition, the street, what worries you..."></textarea></div>\
                <button type="submit" class="rf-submit">ASK FOR MY PERSONAL REVIEW</button>\
' + (PERSONAL_REVIEW_CONSENT ? '<p class="rf-consent" style="font-size:11px;color:#888;margin:10px 0 0;line-height:1.5;">' + esc(PERSONAL_REVIEW_CONSENT) + '</p>' : '') + '\
                <p class="rf-error"></p>\
            </form>\
        </div>';
        instrumentForm(id);

        var wrap = document.getElementById(id);
        var form = wrap.querySelector('form');
        form.addEventListener('submit', function (e) {
            e.preventDefault();
            var btn = form.querySelector('.rf-submit');
            var err = form.querySelector('.rf-error');
            btn.disabled = true; btn.textContent = 'Sending...'; err.style.display = 'none';
            var msg = form.querySelector('[name=message]').value;
            var noteParts = [];
            if (listingAddress) noteParts.push('Property: ' + listingAddress);
            if (mlsNumber) noteParts.push('MLS#: ' + mlsNumber);
            if (agent) noteParts.push('Asked for a personal review from: ' + agent);
            if (msg) noteParts.push('Message: ' + msg);
            var data = {
                first_name: form.querySelector('[name=fname]').value,
                last_name: '',
                email: form.querySelector('[name=email]').value,
                phone: form.querySelector('[name=phone]').value,
                note: 'Source: Listing Page — Personal Review | ' + noteParts.join(' | '),
                // 'Listing Inquiry' MUST be present and before 'Buyer': the server derives lead_type from the tags; without it
                // ['Personal Review','Buyer'] becomes buyer_alert (saved search, 'no urgent action') -- see personal-review-tab-test.py.
                tag: ['Listing Inquiry', 'Personal Review', 'Buyer'].concat(mlsNumber ? ['MLS#' + mlsNumber] : [], city ? ['city:' + city] : []),
                lead_source: 'Source: Listing Page — Personal Review',
                property_address: listingAddress || undefined,
                mls_number: mlsNumber || undefined,
                listing_url: window.location.href,
                message: msg || undefined
            };
            var assignees = buildAssignees(assigneeHost);
            if (assignees.length) data.assignees = assignees;
            safePostLead(id, data, function (error) {
                if (error) {
                    err.textContent = 'Something went wrong. Please call us at ' + ((window.SITE && window.SITE.phone) || "709-256-7999") + '.';
                    err.style.display = 'block';
                    btn.disabled = false; btn.textContent = 'ASK FOR MY PERSONAL REVIEW';
                } else {
                    showSuccess(wrap, '<h4>Got it</h4><p>' + esc(who) + ' will look at this one and send you a personal take.</p>');
                }
            });
        });
    }

    // ─── Public API ──────────────────────────────────────────
    return {
        homeValuation: homeValuation,
        marketReport: marketReport,
        listingAlerts: listingAlerts,
        newConstruction: newConstruction,
        listingInquiry: listingInquiry,
        personalReview: personalReview,
        bookShowing: bookShowing,
        openHouseSignIn: openHouseSignIn,
        agentContact: agentContact,
        popup: popup,
        exitIntent: exitIntent,
        stickyBar: stickyBar,
        joinTeam: joinTeam,
        communityInquiry: communityInquiry,
        buyerConsult: buyerConsult,
        commercialInquiry: commercialInquiry,
        preApproval: preApproval
    };
})();
