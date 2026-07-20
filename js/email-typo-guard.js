/* ============================================================================
 * email-typo-guard.js — soft "Did you mean …?" guard for inbound lead forms
 * ----------------------------------------------------------------------------
 * WHY THIS EXISTS
 *   2026-07-19: a real inbound recruiting lead arrived as
 *   "…@gmail.con" (.con, not .com). Supabase stored it, office@ was notified,
 *   the auto-reply bounced into the void, and the lead was unreachable by
 *   email. Only the phone number worked. A single wrong character cost us
 *   the primary contact channel on a live lead.
 *
 * DESIGN POSTURE — SOFT, NEVER A HARD BLOCK
 *   A legitimate-but-unusual domain must ALWAYS be submittable. This guard
 *   only ever *asks*. Every prompt has a "No, keep mine" escape that submits
 *   the address exactly as typed. We would rather accept ten odd-looking real
 *   addresses than reject one.
 *
 * HOW IT ATTACHES
 *   One document-level CAPTURE-phase submit listener. Capture runs before the
 *   form's own handlers, so this works for:
 *     - BoldTrailForms-generated forms (injected at runtime, 13 form types)
 *     - hand-rolled forms (pages/contact.html, pages/rental-application.html)
 *     - inline onsubmit="" handlers
 *     - any form added in the future
 *   No per-form wiring. Drop the <script> on the page and it covers everything.
 *
 * DETECTION IS DELIBERATELY CONSERVATIVE — see suggestEmailDomain() below for
 * the three tiers and why .co / .cm / .om are treated differently from .con.
 *
 * The same detection table is mirrored server-side in
 * netlify/functions/lead-receive.ts (function suggestEmailDomain). If you edit
 * one, edit both — they are intentionally kept in sync.
 * ========================================================================= */
(function (window, document) {
    'use strict';

    // ─── Domains we consider "known good" ────────────────────────────────
    // An exact match here is never flagged. Includes the big global providers
    // plus the Canadian / Newfoundland ISPs that actually show up in our leads.
    var POPULAR = [
        'gmail.com', 'googlemail.com',
        'hotmail.com', 'hotmail.ca', 'hotmail.co.uk',
        'outlook.com', 'outlook.ca',
        'yahoo.com', 'yahoo.ca', 'yahoo.co.uk',
        'live.com', 'live.ca',
        'icloud.com', 'me.com', 'mac.com',
        'aol.com', 'msn.com',
        'protonmail.com', 'proton.me',
        'gmx.com', 'mail.com', 'zoho.com',
        // Canadian / NL ISPs + local business domains
        'bellaliant.net', 'bell.net', 'sympatico.ca', 'nf.sympatico.ca',
        'eastlink.ca', 'rogers.com', 'nl.rogers.com', 'shaw.ca', 'telus.net',
        'personainternet.com', 'nlbroadband.ca',
        'royallepage.ca', 'realestategander.com', 'nlar.ca'
    ];

    // ─── Tier 1: whole-domain typos we have actually seen or can name ────
    // Highest confidence — an exact key match is an unambiguous misspelling.
    var EXACT_TYPOS = {
        // gmail
        'gmial.com': 'gmail.com', 'gmai.com': 'gmail.com', 'gmal.com': 'gmail.com',
        'gmaill.com': 'gmail.com', 'gmail.cm': 'gmail.com', 'gnail.com': 'gmail.com',
        'gamil.com': 'gmail.com', 'gmailc.om': 'gmail.com', 'ggmail.com': 'gmail.com',
        'gmailcom': 'gmail.com', 'gmail.om': 'gmail.com', 'grmail.com': 'gmail.com',
        // hotmail
        'hotmial.com': 'hotmail.com', 'hotmai.com': 'hotmail.com', 'hotmal.com': 'hotmail.com',
        'hotmaill.com': 'hotmail.com', 'hotamil.com': 'hotmail.com', 'hormail.com': 'hotmail.com',
        'hotmailcom': 'hotmail.com', 'hotmail.cm': 'hotmail.com', 'hotmil.com': 'hotmail.com',
        // outlook
        'outlok.com': 'outlook.com', 'outllok.com': 'outlook.com', 'outloook.com': 'outlook.com',
        'oulook.com': 'outlook.com', 'outlook.cm': 'outlook.com', 'outlookcom': 'outlook.com',
        // yahoo
        'yahooo.com': 'yahoo.com', 'yaho.com': 'yahoo.com', 'yhoo.com': 'yahoo.com',
        'yahoo.cm': 'yahoo.com', 'yahoocom': 'yahoo.com', 'yahou.com': 'yahoo.com',
        // icloud / live / aol
        'iclould.com': 'icloud.com', 'icloud.co': 'icloud.com', 'iclod.com': 'icloud.com',
        'live.cm': 'live.com', 'aol.co': 'aol.com', 'aoll.com': 'aol.com'
    };

    // ─── Tier 2a: TLDs that DO NOT EXIST in the IANA root zone ───────────
    // Nothing legitimate can ever end in these, so suggesting ".com" is safe
    // regardless of what the second-level domain is.
    var DEAD_TLDS = {
        'con': 'com', 'cim': 'com', 'cmo': 'com', 'comm': 'com', 'ccom': 'com',
        'coom': 'com', 'copm': 'com', 'cpm': 'com', 'xom': 'com', 'vom': 'com',
        'ocm': 'com', 'cxom': 'com', 'comn': 'com', 'con.': 'com', 'clm': 'com',
        'nte': 'net', 'ent': 'net', 'nett': 'net', 'ne': 'net',
        'orgg': 'org', 'ogr': 'org', 'rog': 'org',
        'cca': 'ca', 'caa': 'ca'
    };

    // ─── Tier 2b: TLDs that ARE real but are common .com fat-fingers ─────
    // .co (Colombia), .cm (Cameroon), .om (Oman) are all legitimate TLDs and
    // are heavily typo-squatted precisely BECAUSE they neighbour .com. We only
    // suggest a fix when the second-level domain is a known consumer mail
    // provider — "gmail.co" is a typo, but "acme.co" is somebody's real company.
    var RISKY_TLDS = { 'co': 'com', 'cm': 'com', 'om': 'com', 'c': 'com', 'som': 'com' };

    // Second-level domains for which RISKY_TLDS correction is safe to offer.
    var CONSUMER_SLDS = [
        'gmail', 'hotmail', 'outlook', 'yahoo', 'live', 'icloud',
        'aol', 'msn', 'googlemail', 'protonmail'
    ];

    function indexOfIn(list, v) {
        for (var i = 0; i < list.length; i++) { if (list[i] === v) return i; }
        return -1;
    }

    // Levenshtein with an early-exit ceiling — we only care about "close".
    function editDistance(a, b, ceiling) {
        if (a === b) return 0;
        if (Math.abs(a.length - b.length) > ceiling) return ceiling + 1;
        var prev = [], cur = [], i, j;
        for (j = 0; j <= b.length; j++) prev[j] = j;
        for (i = 1; i <= a.length; i++) {
            cur[0] = i;
            var rowMin = cur[0];
            for (j = 1; j <= b.length; j++) {
                var cost = a.charAt(i - 1) === b.charAt(j - 1) ? 0 : 1;
                cur[j] = Math.min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost);
                if (cur[j] < rowMin) rowMin = cur[j];
            }
            if (rowMin > ceiling) return ceiling + 1;   // whole row already too far
            for (j = 0; j <= b.length; j++) prev[j] = cur[j];
        }
        return prev[b.length];
    }

    /**
     * Inspect an email address and return a suggested correction, or null.
     *
     * @param  {string} raw
     * @return {{original:string, suggestion:string, confidence:string}|null}
     *         confidence is 'high' (named typo / impossible TLD) or
     *         'medium' (near-miss against a known provider).
     */
    function suggestEmailDomain(raw) {
        if (!raw || typeof raw !== 'string') return null;
        var email = raw.trim();
        var at = email.lastIndexOf('@');
        if (at < 1 || at === email.length - 1) return null;      // not an address shape
        if (email.indexOf('@') !== at) return null;              // multiple @ — leave alone

        var local = email.slice(0, at);
        var domain = email.slice(at + 1).toLowerCase().replace(/\.+$/, '');
        if (!domain) return null;

        var fix = function (newDomain, confidence) {
            if (newDomain === domain) return null;
            return { original: email, suggestion: local + '@' + newDomain, confidence: confidence };
        };

        // Exact match against a known-good domain → nothing to say.
        if (indexOfIn(POPULAR, domain) !== -1) return null;

        // Tier 1 — named whole-domain typo.
        if (EXACT_TYPOS[domain]) return fix(EXACT_TYPOS[domain], 'high');

        var lastDot = domain.lastIndexOf('.');

        // No dot at all ("gmailcom", "user@localhost") — only actionable if the
        // whole thing is a known provider with the dot dropped.
        if (lastDot === -1) {
            for (var p = 0; p < POPULAR.length; p++) {
                if (POPULAR[p].replace('.', '') === domain) return fix(POPULAR[p], 'high');
            }
            return null;
        }

        var sld = domain.slice(0, lastDot);
        var tld = domain.slice(lastDot + 1);

        // Tier 2a — impossible TLD. Always safe to offer the fix.
        if (DEAD_TLDS[tld]) return fix(sld + '.' + DEAD_TLDS[tld], 'high');

        // Tier 2b — real TLD, but only a typo when paired with a consumer provider.
        if (RISKY_TLDS[tld] && indexOfIn(CONSUMER_SLDS, sld) !== -1) {
            return fix(sld + '.' + RISKY_TLDS[tld], 'high');
        }

        // Tier 3 — near-miss against a known provider. Distance scales with
        // length so short domains can't collide (e.g. "acme.ca" must not become
        // "acne.ca"); we only compare against our POPULAR list, never generally.
        var ceiling = domain.length >= 10 ? 2 : 1;
        var best = null, bestDist = ceiling + 1;
        for (var k = 0; k < POPULAR.length; k++) {
            var cand = POPULAR[k];
            var d = editDistance(domain, cand, ceiling);
            if (d <= ceiling && d < bestDist) { bestDist = d; best = cand; }
        }
        // Guard: never "correct" across different TLD families on a fuzzy match
        // (acme.ca → acme.com would be wrong and annoying). Require the TLD to
        // already match the candidate's.
        if (best) {
            var bestTld = best.slice(best.lastIndexOf('.') + 1);
            if (bestTld === tld) return fix(best, 'medium');
        }

        return null;
    }

    // ═══════════════════════════════════════════════════════════════════
    // UI — inline soft confirmation
    // ═══════════════════════════════════════════════════════════════════

    var STYLE_ID = 'etg-styles';
    var ACK_ATTR = 'data-etg-acknowledged';

    function injectStyles() {
        if (document.getElementById(STYLE_ID)) return;
        var s = document.createElement('style');
        s.id = STYLE_ID;
        // Self-contained colours so the box reads correctly on both the dark
        // BoldTrail form panels and the light hand-rolled page forms.
        s.textContent = [
            '.etg-prompt{margin:8px 0 4px;padding:12px 14px;border:1px solid #f0b429;',
            'border-left:4px solid #f0b429;border-radius:6px;background:#fffaf0;',
            'color:#2b2b2b;font-size:14px;line-height:1.5;',
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}',
            '.etg-prompt-q{margin:0 0 10px;}',
            '.etg-prompt-q strong{color:#0a0a0a;}',
            '.etg-actions{display:flex;flex-wrap:wrap;gap:8px;}',
            '.etg-btn{border:0;border-radius:5px;padding:8px 14px;font-size:13px;',
            'font-weight:700;cursor:pointer;font-family:inherit;line-height:1.2;}',
            '.etg-btn-yes{background:#EA002A;color:#fff;}',
            '.etg-btn-yes:hover{background:#c8001f;}',
            '.etg-btn-no{background:transparent;color:#5a5a5a;',
            'border:1px solid #cfcfcf;}',
            '.etg-btn-no:hover{background:#f0f0f0;}'
        ].join('');
        document.head.appendChild(s);
    }

    function emailFieldIn(form) {
        return form.querySelector('input[type="email"]') ||
               form.querySelector('input[name="email"]') ||
               form.querySelector('input[name="caller_email"]');
    }

    function clearPrompt(form) {
        var old = form.querySelector('.etg-prompt');
        if (old && old.parentNode) old.parentNode.removeChild(old);
    }

    // Re-fire submit so the form's own handlers run normally. The ACK flag on
    // the form makes our capture listener pass the event straight through.
    function resubmit(form) {
        form.setAttribute(ACK_ATTR, '1');
        if (typeof form.requestSubmit === 'function') {
            form.requestSubmit();
        } else {
            form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        }
    }

    function showPrompt(form, field, result) {
        injectStyles();
        clearPrompt(form);

        var box = document.createElement('div');
        box.className = 'etg-prompt';
        box.setAttribute('role', 'alert');

        var q = document.createElement('p');
        q.className = 'etg-prompt-q';
        q.appendChild(document.createTextNode('Did you mean '));
        var strong = document.createElement('strong');
        strong.textContent = result.suggestion;      // textContent — never innerHTML
        q.appendChild(strong);
        q.appendChild(document.createTextNode('?'));
        box.appendChild(q);

        var actions = document.createElement('div');
        actions.className = 'etg-actions';

        var yes = document.createElement('button');
        yes.type = 'button';
        yes.className = 'etg-btn etg-btn-yes';
        yes.textContent = 'Yes, use that';
        yes.addEventListener('click', function () {
            field.value = result.suggestion;
            clearPrompt(form);
            resubmit(form);
        });

        var no = document.createElement('button');
        no.type = 'button';
        no.className = 'etg-btn etg-btn-no';
        no.textContent = 'No, keep what I typed';
        no.addEventListener('click', function () {
            clearPrompt(form);
            resubmit(form);                          // submits the ORIGINAL value
        });

        actions.appendChild(yes);
        actions.appendChild(no);
        box.appendChild(actions);

        // Place directly under the email field so the association is obvious.
        var anchor = field.parentNode || form;
        if (anchor === form) form.appendChild(box);
        else anchor.appendChild(box);

        try { box.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (e) { /* older browsers */ }
    }

    function onSubmitCapture(e) {
        var form = e.target;
        if (!form || form.nodeName !== 'FORM') return;
        if (form.hasAttribute(ACK_ATTR)) return;              // already answered

        var field = emailFieldIn(form);
        if (!field || !field.value) return;

        var result;
        try {
            result = suggestEmailDomain(field.value);
        } catch (err) {
            return;                                           // never block on our own bug
        }
        if (!result) return;

        // Hold the submit and ask. stopPropagation in the capture phase means
        // the form's own submit handlers never fire for this attempt.
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === 'function') e.stopImmediatePropagation();

        showPrompt(form, field, result);
    }

    function install() {
        if (window.__etgInstalled) return;
        window.__etgInstalled = true;
        document.addEventListener('submit', onSubmitCapture, true);   // true = capture
    }

    // Clear the acknowledgement if the user edits the address again, so a
    // second typo in the same session still gets caught.
    document.addEventListener('input', function (e) {
        var t = e.target;
        if (!t || !t.form || !t.form.hasAttribute(ACK_ATTR)) return;
        if (t.type === 'email' || t.name === 'email' || t.name === 'caller_email') {
            t.form.removeAttribute(ACK_ATTR);
        }
    }, true);

    install();

    window.EmailTypoGuard = {
        suggest: suggestEmailDomain,
        install: install
    };
})(window, document);
