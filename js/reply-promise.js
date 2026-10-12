/**
 * Turner Realty -- the ONE reply promise (Mike, D-1008-30, 2026-10-08).
 * "Every contact and showing form on the three listing sites promises a reply
 *  'within one business hour', from one shared place."
 *
 * This file is the single source of that wording. Fleet canonical (Tier 1, verbatim):
 * edit fleet/canonical/js/reply-promise.js, then tools/fleet-sync.py --apply.
 *   - window.TURNER_REPLY_WINDOW   the time window, for sentences built around it
 *   - window.TURNER_REPLY_PROMISE  the whole sentence
 *   - any element carrying data-reply-promise has its text set to the sentence;
 *     data-reply-window gets the window only. Static pages ship the identical text
 *     as a fallback; tools/tests/reply-promise-test.py fails CI if a fallback differs.
 * Never put a different reply time (minutes, hours, days, "asap") on a form.
 */
(function (w, d) {
  'use strict';
  w.TURNER_REPLY_WINDOW = 'within one business hour';
  w.TURNER_REPLY_PROMISE = "We'll reply within one business hour.";

  function fill() {
    try {
      var a = d.querySelectorAll('[data-reply-promise]');
      for (var i = 0; i < a.length; i++) a[i].textContent = w.TURNER_REPLY_PROMISE;
      var b = d.querySelectorAll('[data-reply-window]');
      for (var j = 0; j < b.length; j++) b[j].textContent = w.TURNER_REPLY_WINDOW;
    } catch (e) { /* a filler that fails must never break the page: the static text is already right */ }
  }
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fill);
  else fill();
})(window, document);
