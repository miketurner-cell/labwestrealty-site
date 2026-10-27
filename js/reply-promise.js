/**
 * Turner Realty -- the ONE reply promise (Mike, D-1027-01, 2026-10-27; replaces the D-1008-30
 * "within one business hour" wording).
 * "Every form and page uses this: 'Our receptionist answers 24/7, and an agent calls you back the same day.'"
 *
 * This file is the single source of that wording. Fleet canonical (Tier 1, verbatim):
 * edit fleet/canonical/js/reply-promise.js, then tools/fleet-sync.py --apply.
 *   - window.TURNER_REPLY_PROMISE  the whole sentence (there is no separate time window any more:
 *     success messages are built as "Thank you. " + the sentence)
 *   - any element carrying data-reply-promise has its text set to the sentence. Static pages ship the
 *     identical text as a fallback; tools/tests/reply-promise-test.py fails CI if a fallback differs.
 * Never put a different reply time (minutes, hours, days, "asap") on a form.
 */
(function (w, d) {
  'use strict';
  w.TURNER_REPLY_PROMISE = "Our receptionist answers 24/7, and an agent calls you back the same day.";

  function fill() {
    try {
      var a = d.querySelectorAll('[data-reply-promise]');
      for (var i = 0; i < a.length; i++) a[i].textContent = w.TURNER_REPLY_PROMISE;
    } catch (e) { /* a filler that fails must never break the page: the static text is already right */ }
  }
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fill);
  else fill();
})(window, document);
