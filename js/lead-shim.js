/*
 * lead-shim.js — legacy SDK shim for BoldTrail / kvCORE lead capture.
 *
 * Drop-in for the old unpkg @rechat/sdk that some inline forms still call as
 * `new BoldTrail.Sdk()`. Routes every lead to OUR pipeline (lead-receive.ts ->
 * Supabase + office email + kvCORE / rlpSPHERE / BoldTrail). No external SDK,
 * no third-party account.
 *
 * A transitional `window.Rechat` alias keeps any not-yet-regenerated page that
 * still emits `new Rechat.Sdk()` working through the fleet cutover; remove the
 * alias (and this whole shim, once no page emits .Sdk()) after the cutover bakes.
 *
 *   sdk.Leads.track(...)             -> no-op (legacy page-tracking retired)
 *   sdk.Leads.capture(channel,input) -> reshape -> POST lead-receive (returns a
 *   sdk.Leads.create(channel,input)     Promise; forms keep their .then/.catch)
 *
 * The reshape produces the exact payload shape the form library already posts
 * successfully (source:'web' + phone_number + tag[] + lead_source), which
 * lead-receive's coercion accepts.
 */
(function () {
  var LEAD_RECEIVE = 'https://realestategander.com/.netlify/functions/lead-receive';

  function toWebPayload(channel, input) {
    // Forms call either capture(channel, input) or capture(singleObject).
    var p = {};
    if (channel && typeof channel === 'object') { for (var k in channel) if (channel.hasOwnProperty(k)) p[k] = channel[k]; }
    if (input && typeof input === 'object') { for (var j in input) if (input.hasOwnProperty(j)) p[j] = input[j]; }
    var tag = p.tag;
    if (!Array.isArray(tag)) tag = tag ? [tag] : [];
    return {
      source: 'web',
      first_name: p.first_name || '',
      last_name: p.last_name || '',
      email: p.email || '',
      phone_number: p.phone || p.phone_number || '',
      note: p.note || '',
      tag: tag,
      lead_source: p.source || p.lead_source || 'Website',
      referer_url: (typeof window !== 'undefined' && window.location) ? window.location.href : ''
    };
  }

  function capture(channel, input) {
    var body = toWebPayload(channel, input);
    return fetch(LEAD_RECEIVE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (!r.ok) {
        return r.text().then(function (t) { throw new Error('lead-receive ' + r.status + ': ' + t); });
      }
      return r.json().catch(function () { return {}; });
    });
  }

  function Sdk() {
    return {
      Leads: {
        track: function () { /* legacy page-tracking retired — no-op */ },
        capture: capture,
        create: capture
      }
    };
  }

  window.BoldTrail = window.BoldTrail || {};
  window.BoldTrail.Sdk = Sdk;
  window.Rechat = window.BoldTrail;   // transitional alias — remove after fleet cutover bakes
})();
